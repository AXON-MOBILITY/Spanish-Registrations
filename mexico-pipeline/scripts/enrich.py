"""Fuel-type and body-type enrichment for RAIAVL (INEGI) sales rows.

INEGI's own data gives us MARCA, MODELO, TIPO (Automoviles / Camiones
ligeros) and SEGMENTO (Compactos, De Lujo, Deportivos, Subcompactos,
SUV's, Minivans, Pick Ups) - already a decent proxy for body type, but
it doesn't split Sedan vs Hatchback vs Coupe within "Automoviles", and
it has nothing on propulsion.

Mexico has no public per-model registry of fuel type or body silhouette
(unlike Spain's IDAE WLTP catalogue), so both fields here are *derived*,
not sourced from an official record:

  1. masters/master_model_overrides.csv - hand-curated exceptions for
     models we can identify with confidence (BEV/PHEV/Diesel nameplates,
     Sedan/Hatchback/Coupe/Convertible splits, INEGI TIPO/SEGMENTO
     mis-classifications like the BMW iX1 landing under "Automoviles").
  2. Keyword rules on the MODELO string itself (INEGI often spells out
     "Hatchback", "Sedan", "HEV", "EV", "Diesel", "TDI"...).
  3. Fallback to TIPO/SEGMENTO as INEGI publishes them.

fuel_type follows the same convention already used in the Spanish
Registrations project: non-plug-in hybrids (HEV/MHEV) count as
"Gasolina" since they run on a single fuel and never plug in. Only
Diesel, Hibrido enchufable (PHEV) and Electrico (BEV) are broken out.
Every row also gets a `confidence` flag (alta/media/baja) and a `note`
explaining anything non-obvious - see docs/METODOLOGIA.md.
"""
import csv
import re
import unicodedata
from pathlib import Path

MASTERS_DIR = Path(__file__).resolve().parent.parent / "masters"


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))

SEGMENTO_BODY_DEFAULT = {
    "SUV's": "SUV",
    "Pick Ups": "Pickup",
    "Minivans": "Van",
}

# Substring keywords - safe because DIESEL/TDI/HDI/PHEV/ELECTR are
# distinctive strings unlikely to appear inside an unrelated model name.
FUEL_SUBSTRING_KEYWORDS = [
    ("PHEV", ("Hibrido enchufable (PHEV)", "alta")),
    ("PLUGIN", ("Hibrido enchufable (PHEV)", "alta")),
    ("DIESEL", ("Diesel", "alta")),
    ("TDI", ("Diesel", "alta")),
    ("HDI", ("Diesel", "alta")),
    ("ELECTR", ("Electrico (BEV)", "alta")),  # ELECTRICO / ELECTRICA
]

# Token-suffix keywords - "EV"/"HEV" are only trustworthy as the tail of
# a whole word/token (e.g. "MHEV", "ZSHEV", "BOLT EV"). A plain substring
# check would also fire on unrelated words like "CHEVROLET" (contains
# "HEV") or "SEVEN" (contains "EV"), so these are matched per token.
FUEL_TOKEN_SUFFIX_KEYWORDS = [
    ("HEV", ("Gasolina", "alta")),  # non-plugin (M)HEV: single fuel, counts as Gasolina
    ("EV", ("Electrico (BEV)", "alta")),
    ("BEV", ("Electrico (BEV)", "alta")),
]

BODY_KEYWORDS = [
    ("HATCHBACK", "Hatchback"),
    ("SEDAN", "Sedan"),
    ("CABRIO", "Convertible"),
    ("CONVERTIBLE", "Convertible"),
    ("ROADSTER", "Convertible"),
    ("COUPE", "Coupe"),
]


def _load_overrides() -> dict:
    path = MASTERS_DIR / "master_model_overrides.csv"
    overrides = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["marca"].strip(), row["modelo"].strip())
            overrides[key] = row
    return overrides


_OVERRIDES = _load_overrides()


def classify_fuel_type(modelo: str) -> tuple[str, str]:
    upper = _strip_accents(modelo.upper())
    for kw, (fuel, conf) in FUEL_SUBSTRING_KEYWORDS:
        if kw in upper:
            return fuel, conf

    tokens = upper.replace("-", " ").replace(".", " ").split()
    for token in tokens:
        for suffix, (fuel, conf) in FUEL_TOKEN_SUFFIX_KEYWORDS:
            if token.endswith(suffix):
                return fuel, conf

    return "Gasolina", "media"


def classify_body_type(modelo: str, tipo: str, segmento: str) -> tuple[str, str]:
    upper = _strip_accents(modelo.upper())
    for kw, body in BODY_KEYWORDS:
        if kw in upper:
            return body, "alta"
    if segmento in SEGMENTO_BODY_DEFAULT:
        return SEGMENTO_BODY_DEFAULT[segmento], "alta"
    if segmento == "Deportivos":
        return "Coupe", "media"
    if tipo == "Camiones ligeros":
        return "Van/Comercial", "baja"
    # Automoviles, Compactos/Subcompactos/De Lujo, no explicit cue: the
    # global default body for those segments in the Mexican market is a
    # notchback sedan.
    return "Sedan", "media"


# Pure body-style words INEGI sometimes appends to MODELO, splitting one
# real nameplate into two+ rows (e.g. "K3 Hatchback" / "K3 Sedan"). Body
# style is already captured independently in the `body_type` column, so
# stripping the suffix from the display name doesn't lose information -
# it just stops the same model fragmenting the brand's ranking. Door-count
# suffixes ("4 Ptas") and powertrain suffixes ("HEV") are deliberately
# NOT stripped: those are genuinely informative, not formatting noise.
BODY_SUFFIX_WORDS = {"SEDAN", "HATCHBACK", "HB", "COUPE", "CABRIO", "CONVERTIBLE", "ROADSTER"}
# Door-count shorthand ("3 Ptas", "4PTAS.") is genuinely informative on
# its own but reads as meaningless once stripped of the brand name (a
# bare "3 PTAS" says nothing) - blocks the brand-prefix-strip step below,
# same reasoning as the body-word-only guard.
_DOOR_ONLY_RE = re.compile(r"^[2-5]\s*P(TAS?|TS)?\.?$")


def normalize_model_name(marca: str, modelo: str) -> str:
    """Canonical display name for a marca+modelo pair.

    Cleans up three INEGI formatting quirks that otherwise split one real
    model into several rows in the dashboard: a trailing "-" (data-entry
    artifact, no meaning), a trailing body-style word ("K3 Hatchback" vs
    "K3 Sedan" -> both "K3"), and the brand name redundantly repeated
    inside MODELO ("Mazda 2" under marca "Mazda" -> "2" reads as
    meaningless on its own, so that last step only fires when at least
    two alphanumeric characters with a letter survive, e.g. "Honda City"
    -> "City", but "Chrysler 300" and "Mazda 2" keep their brand prefix).
    """
    s = re.sub(r"\s+", " ", modelo.strip())

    changed = True
    while changed:
        changed = False
        trimmed = re.sub(r"[\s\-]+$", "", s)
        if trimmed != s:
            s = trimmed
            changed = True
            continue
        tokens = s.split(" ") if s else []
        if tokens and _strip_accents(tokens[-1].upper()) in BODY_SUFFIX_WORDS:
            s = " ".join(tokens[:-1]).strip()
            changed = True

    marca_stripped = marca.strip()
    marca_upper = _strip_accents(marca_stripped.upper())
    # Suffix-stripping consumed everything except the brand name itself
    # (e.g. "MINI Coupe" -> "MINI") - the body word IS the model name here
    # (MINI badges trims as Coupe/Convertible/Clubman/...), so undo the
    # strip and use the untouched MODELO as-is instead of mangling it
    # further with the brand-prefix step below.
    if not s or _strip_accents(s.upper()) == marca_upper:
        return modelo.strip()

    if _strip_accents(s.upper()).startswith(marca_upper + " "):
        candidate = s[len(marca_stripped):].strip()
        candidate_norm = _strip_accents(candidate.upper())
        if (len(candidate) >= 2
                and re.search(r"[A-Za-zÀ-ÿ]", candidate)
                and not _DOOR_ONLY_RE.match(candidate_norm)):
            s = candidate

    return s or modelo.strip()


# Chinese-brand / newly-arrived importers where our own automotive
# knowledge is thin; anything not in the overrides table for these
# brands gets its confidence downgraded rather than asserted as "alta".
LOW_CONFIDENCE_BRANDS = {
    "MOTORNATION", "JETOUR", "Jetour Soueast", "Omoda", "Auteco",
    "Foton", "JAC", "Changan", "Great Wall Motor", "Chirey", "Geely",
}


def enrich_row(marca: str, modelo: str, tipo: str, segmento: str) -> dict:
    marca = marca.strip()
    modelo = modelo.strip()
    override = _OVERRIDES.get((marca, modelo))
    if override:
        return {
            "fuel_type": override["fuel_type"],
            "body_type": override["body_type"],
            "confidence": override["confidence"],
            "note": override["note"],
        }

    fuel_type, fuel_conf = classify_fuel_type(modelo)
    body_type, body_conf = classify_body_type(modelo, tipo, segmento)
    confidence = "media" if "alta" in (fuel_conf, body_conf) else fuel_conf
    if fuel_conf == "alta" and body_conf == "alta":
        confidence = "alta"
    if marca in LOW_CONFIDENCE_BRANDS and confidence == "media":
        confidence = "baja"

    return {
        "fuel_type": fuel_type,
        "body_type": body_type,
        "confidence": confidence,
        "note": "",
    }
