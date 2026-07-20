#!/usr/bin/env python3
"""Resolve BMW dealer territories from the internal active-dealer master.

The result is a domicile-territory proxy. It does not identify the dealer that
actually sold the vehicle.
"""

import collections
import csv
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ACTIVE_MASTER = ROOT / "masters" / "master_bmw_active_dealers.csv"
DEFAULT_TERRITORY_MASTER = ROOT / "masters" / "master_concesin_bmw_v2.csv"

MASTER_PROVINCE_NAMES = {
    "07": "ISLAS BALEARES",
    "20": "GUIPUZCOA",
    "35": "LAS PALMAS",
    "38": "SANTA CRUZ DE TENERIFE",
    "48": "VIZCAYA",
}

MUNICIPALITY_ALIASES = {
    ("03", "ALICANTE"): "ALICANTE ALACANT",
    ("03", "ALCOY"): "ALCOY ALCOI",
    ("03", "CAMPELLO"): "EL CAMPELLO",
    ("03", "ELCHE"): "ELCHE ELX",
    ("03", "JAVEA"): "JAVEA XABIA",
    ("08", "S CUGAT DEL VALLES"): "SANT CUGAT DEL VALLES",
    ("08", "S JULIA VILATORTA"): "SANT JULIA DE VILATORTA",
    ("11", "EL PUERTO STA MARIA"): "EL PUERTO DE SANTA MARIA",
    ("11", "JEREZ DE LA FTRA"): "JEREZ DE LA FRONTERA",
    ("12", "BENICASIM"): "BENICASIM BENICASSIM",
    ("12", "CASTELLO PLANA"): "CASTELLON DE LA PLANA CASTELLO DE LA PLANA",
    ("15", "SANTIAGO"): "SANTIAGO DE COMPOSTELA",
    ("28", "SAN SEBASTIAN REYES"): "SAN SEBASTIAN DE LOS REYES",
    ("28", "VILLANUEVA DE CANADA"): "VILLANUEVA DE LA CANADA",
    ("35", "LAS PALMAS G C"): "LAS PALMAS DE GRAN CANARIA",
    ("38", "LA LAGUNA"): "SAN CRISTOBAL DE LA LAGUNA",
    ("38", "S C TENERIFE"): "SANTA CRUZ DE TENERIFE",
    ("46", "LA ELIANA"): "ELIANA L",
    ("07", "PALMA"): "PALMA DE MALLORCA",
}

# The internal BUNO master replaced the former Momentum Norte code.
DEALER_ID_ALIASES = {"100197": "100917"}

DEALER_VARIANT_BY_PROVINCE = {
    ("100380", "CACERES"): "100380:ceres-motor",
    ("100380", "BADAJOZ"): "100380:mandel-motor",
}


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or "").strip().upper())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_municipality(value):
    normalized = normalize_text(value)
    tokens = normalized.split()
    if len(tokens) > 1 and tokens[-1] in {"A", "O", "EL", "LA", "LOS", "LAS"}:
        tokens = [tokens[-1]] + tokens[:-1]
    return " ".join(tokens)


def normalize_dealer_id(value):
    value = str(value or "").strip()
    if value.endswith(".0") and value[:-2].isdigit():
        value = value[:-2]
    return DEALER_ID_ALIASES.get(value, value)


def _normalized_row(row):
    return {normalize_text(key).replace(" ", "_"): (value or "").strip() for key, value in row.items()}


def _first(row, *names):
    for name in names:
        value = row.get(normalize_text(name).replace(" ", "_"), "")
        if value:
            return value
    return ""


def load_active_dealers(path=DEFAULT_ACTIVE_MASTER):
    dealers = {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            dealer_id = normalize_dealer_id(row.get("dealer_id"))
            dealer_name = (row.get("dealer_name") or "").strip()
            if dealer_id and dealer_name:
                dealers[dealer_id] = dealer_name
    return dealers


def load_context(
    active_master=DEFAULT_ACTIVE_MASTER,
    territory_master=DEFAULT_TERRITORY_MASTER,
):
    """Load active BMW dealers and unambiguous municipality territories."""
    active = load_active_dealers(active_master)
    active_by_code = collections.defaultdict(list)
    with open(active_master, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            dealer_id = (row.get("dealer_id") or "").strip()
            dealer_code = normalize_dealer_id(
                row.get("dealer_code") or dealer_id.split(":", 1)[0]
            )
            if dealer_id in active:
                active_by_code[dealer_code].append(dealer_id)
    by_municipality = collections.defaultdict(dict)

    with open(territory_master, encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = _normalized_row(raw)
            province = _first(row, "Provincia")
            municipality = _first(row, "Municipio")
            dealer_code = normalize_dealer_id(
                _first(row, "Id_Concesin", "Id_Concesion")
            )
            variants = active_by_code.get(dealer_code, [])
            if not variants:
                continue
            province_key = normalize_text(province)
            dealer_id = DEALER_VARIANT_BY_PROVINCE.get(
                (dealer_code, province_key)
            )
            if dealer_id is None and len(variants) == 1:
                dealer_id = variants[0]
            if dealer_id not in active:
                continue
            key = (province_key, normalize_municipality(municipality))
            if all(key):
                by_municipality[key][dealer_id] = {
                    "dealer_id": dealer_id,
                    "dealer_estimated": active[dealer_id],
                }

    ambiguous = {key for key, values in by_municipality.items() if len(values) > 1}
    territories = {
        key: next(iter(values.values()))
        for key, values in by_municipality.items()
        if len(values) == 1
    }
    by_name = collections.defaultdict(list)
    for key, territory in territories.items():
        by_name[key[1]].append(territory)
    unique_names = {
        name: values[0]
        for name, values in by_name.items()
        if len({value["dealer_id"] for value in values}) == 1
    }
    return {
        "active_dealers": active,
        "territories": territories,
        "ambiguous": ambiguous,
        "unique_names": unique_names,
    }


def resolve(province_code, municipality, context, province_names=None):
    """Resolve an active BMW dealer from the buyer municipality."""
    province_code = (province_code or "").strip()[:2]
    raw_name = normalize_text(municipality)
    municipality_key = MUNICIPALITY_ALIASES.get(
        (province_code, raw_name), normalize_municipality(municipality)
    )
    names = province_names or {}
    province = MASTER_PROVINCE_NAMES.get(province_code, names.get(province_code, ""))
    key = (normalize_text(province), municipality_key)
    if not municipality_key or key in context["ambiguous"]:
        return None

    territory = context["territories"].get(key)
    confidence = "high"
    status = "municipality_exact"
    if territory is None:
        territory = context["unique_names"].get(municipality_key)
        confidence = "medium"
        status = "municipality_unique_name_fallback"
    if territory is None:
        return None

    return {
        **territory,
        "confidence": confidence,
        "source_confidence": "internal",
        "dealer_method": "bmw_internal_municipality_territory_proxy",
        "territory_status": status,
    }
