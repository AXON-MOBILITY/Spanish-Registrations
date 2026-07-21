"""
build_dashboard_data.py — Genera JSON estáticos para el dashboard Vercel.

Salida principal:
  public/data/records.json   — registros planos con todas las dimensiones
  public/data/meta.json      — listas de valores únicos, meses disponibles
  public/data/provinces.json — datos por provincia
  public/data/records_dealer.json — registros Private por dealer estimado
  public/data/daily_mtd.json — acumulado MTD diario del mes actual

Columnas records.json (índices COL en index.html):
  0:y  1:m  2:marca  3:modelo  4:canal  5:fuel  6:fuel_det  7:seg  8:sub  9:hp  10:body  11:n
"""
import argparse, csv, glob, json, os, re
from collections import defaultdict
from datetime import date
from pathlib import Path

# Estructura del repo: script en scripts/, CSVs de la ETL en data/processed/,
# exports Simmix (validación) en validation/, salida del dashboard en public/data/.
_SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = _SCRIPT_DIR.parent if _SCRIPT_DIR.name == "scripts" else _SCRIPT_DIR
DATA_DIR = REPO_ROOT / "data" / "processed"
VALIDATION_DIR = REPO_ROOT / "validation"
BASE = DATA_DIR if DATA_DIR.exists() else REPO_ROOT
MONTHS_ES = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
             7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}
CANALES = ["Private","Corporate","RAC"]
FUELS   = ["ICE","BEV","PHEV"]

# ── Normalización de marcas DGT → nombres canónicos Simmix ───────────────────
_BRAND_NORM = {
    'ABARTH': 'Abarth', 'AIWAYS': 'Aiways', 'ALFA ROMEO': 'Alfa Romeo',
    '212': 'BAW',
    "ALKE'": 'Alke', 'ALKE': 'Alke',
    'AUTOMOBILI LAMBORGHINI S.P.A.': 'Lamborghini',
    'ALPINE': 'Alpine', 'ALPINA': 'Alpina', 'ASTON MARTIN': 'Aston Martin',
    'AUDI': 'Audi', 'BENTLEY': 'Bentley', 'BMW': 'BMW',
    'CADILLAC': 'Cadillac', 'CENNTRO': 'Cenntro', 'CITROEN': 'Citroen',
    'CUPRA': 'Cupra', 'DACIA': 'Dacia', 'DEEPAL': 'Changan', 'DR': 'DR',
    'DS': 'DS', 'ESAGONO ENERGIA': 'Esagono Energia', 'ETESIA': 'Etesia',
    'EVUM MOTORS': 'Evum Motors', 'FERRARI': 'Ferrari', 'FIAT': 'Fiat',
    'FORD': 'Ford', 'FOTON': 'Foton Motors', 'FUSO': 'Mitsubishi-Fuso',
    'GOUPIL': 'Goupil', 'GREAT WALL MOTOR COMPANY LIMIT': 'GWM', 'HONDA': 'Honda',
    'HYUNDAI': 'Hyundai', 'INEOS': 'Ineos', 'ISUZU': 'Isuzu',
    'IVECO': 'Iveco', 'JAGUAR': 'Jaguar', 'JEEP': 'Jeep',
    'KARMA': 'Karma', 'KIA': 'Kia', 'LAMBORGHINI': 'Lamborghini',
    'LAND ROVER': 'Land Rover', 'LEXUS': 'Lexus', 'LOTUS': 'Lotus',
    'LYNK & CO': 'Lynk & Co', 'MASERATI': 'Maserati', 'MAXUS': 'Maxus',
    'MAZDA': 'Mazda', 'MCLAREN': 'McLaren', 'MG': 'MG',
    'MERCEDES': 'Mercedes', 'MERCEDES BENZ': 'Mercedes',
    'MERCEDES-BENZ': 'Mercedes', 'MERCEDES-AMG': 'Mercedes',
    'MERCEDES IDILIS': 'Mercedes', 'MERCEDES-V': 'Mercedes-V',
    'MINI': 'MINI', 'MITSUBISHI': 'Mitsubishi', 'MITSUBISHI FUSO': 'Mitsubishi-Fuso',
    'MITSUBISHI-FUSO': 'Mitsubishi-Fuso', 'MORGAN': 'Morgan',
    'MW MOTORS': 'MW Motors', 'NEXTEM': 'Nextem', 'NISSAN': 'Nissan',
    'OMODA': 'Omoda', 'OPEL': 'Opel', 'PEUGEOT': 'Peugeot',
    'PIAGGIO': 'Piaggio', 'POLESTAR': 'Polestar', 'PORSCHE': 'Porsche',
    'RENAULT': 'Renault', 'RENAULT TRUCKS': 'Renault Trucks',
    'RENAULT TRUCKS SAS': 'Renault Trucks',
    'ROLLS-ROYCE': 'Rolls-Royce', 'SEAT': 'SEAT', 'SERES': 'Seres',
    'SHINERAY': 'Shineray', 'SKODA': 'Skoda', 'SKYWELL': 'Skywell',
    'SMART': 'Smart', 'SSANGYONG': 'Ssangyong', 'SUBARU': 'Subaru',
    'SUZUKI': 'Suzuki', 'SWM': 'Shineray', 'TESLA': 'Tesla', 'TOYOTA': 'Toyota',
    'VOLKSWAGEN': 'Volkswagen', 'VOLVO': 'Volvo', 'VOYAH': 'Voyah',
    'YUDO': 'Yudo',
    # Abreviaciones que .title() rompería
    'BYD': 'BYD', 'DFSK': 'DFSK', 'EVO': 'EVO', 'MAN': 'MAN',
    # Alias adicionales
    'DS AUTOMOBILES': 'DS',
    'MERCEDES BENZ AG': 'Mercedes', 'MERCEDES-BENZ MINIBUS': 'Mercedes',
    'MERCEDES IRIZAR': 'Mercedes',
    # Variantes DGT de Volkswagen
    'VW': 'Volkswagen', ' VW': 'Volkswagen',
    'VOLKSWAGEN VW': 'Volkswagen', 'VOLKSWAGEN, VW': 'Volkswagen',
    'VOLKSWAGEN V W': 'Volkswagen', 'VOLKSWAGEN-AUTOVERO': 'Volkswagen',
}

# ── Marcas ya clasificadas conscientemente ────────────────────────────────────
# Espejo de _CHINESE_BRANDS + _BRAND_CONCEPT de index.html, más marcas conocidas.
# Cuando clasifiques una marca nueva, añádela aquí → deja de aparecer en el panel.
_EXTRA_CLASSIFIED = {
    # Marcas chinas (espejo de _CHINESE_BRANDS en index.html)
    'Aion', 'Arcfox', 'Baic', 'Baojun', 'Baw', 'Bestune', 'BydDidi', 'Byvin',
    'Changan', 'Chery', 'Dayun', 'DFSK', 'Dongfeng', 'Ebro', 'Exlantix',
    'Faw', 'Foton Motor', 'Funky Cat', 'Geely', 'Great Wall', 'Huanghai',
    'JAC', 'Jaecoo', 'Jetour', 'Jiyue', 'JMC', 'Leapmotor',
    'Li', 'Livan', 'Neta', 'NIO', 'Qiantu', 'Tiger', 'Tiggo', 'VGV',
    'Xpeng', 'Yudo', 'Zeekr',
    # Focus Segment / otras marcas conocidas no cubiertas por _BRAND_NORM
    'Genesis', 'Bugatti', 'Donkervoort', 'Lucid Motors', 'Lancia',
    'BAW', 'Wuling',
    # Nuevas marcas clasificadas 2026
    'Gwm', 'Cirelli', 'Yooudooo', 'Eveasy',
    'Rapido', 'Secma', 'Plymouth', 'La Hispano Suiza', 'Abt',
    'Feniks', 'Gruau',
    'Lepas', 'Tecnove',
}
_KNOWN_CLASSIFIED = set(_BRAND_NORM.values()) | _EXTRA_CLASSIFIED

def _normalize_brand(raw):
    s = (raw or '').strip()
    canon = _BRAND_NORM.get(s.upper())
    return canon if canon else (s.title() if s else s)

# Modelo != version. DGT's free-text "modelo" field is riddled with spacing/
# hyphenation variants, word-order swaps (BMW "3 SERIES" vs "SERIES 3" vs
# "SERIE 3"), typos, and the occasional version/trim code that leaked in as
# if it were its own model (BMW "228", "123 XDRIVE" are 2-series/1-series
# trims, not separate models). Keyed by the already-_normalize_brand()-ed
# brand name. Canonical choice = whichever spelling has the most registered
# units for that brand, except where the "wrong" spelling is objectively the
# official name (Ford F-150) or where the real model exists as a bare
# entry that a rogue "<BRAND> <MODEL>" duplicate should fold into.
_MODEL_NORM = {
    "BMW": {
        "3 SERIES": "SERIE 3", "SERIES 3": "SERIE 3",
        "2 SERIES": "SERIE 2", "228": "SERIE 2", "228 IXDRIVE": "SERIE 2",
        "123 XDRIVE": "SERIE 1",
        "4SERIES": "SERIE 4",
        "5 SERIES": "SERIE 5",
        "6401 XDRIVE": "SERIE 6",
        "7 SERIES": "SERIE 7",
        "SERIES 8": "SERIE 8",
        "X1XDRIVE28I": "X1",
        "Z REIHE": "Z4",  # "Z Reihe" = German "Z Series"; only Z4 is sold in the 2023+ window this data covers
        # Unrecoverable single rows: no real model can be inferred from these.
        "SERIE X": "", "3.0": "", "2600L 365067": "",
    },
    "Mercedes": {
        "E-CLASS": "CLASE E", "T-CLASS": "CLASE T", "C-CLASS": "CLASE C",
        "E220CDI": "E220 CDI", "C220CDI": "C220 CDI",
    },
    "Citroen": {"SPACE TOURER": "SPACETOURER"},
    "Faw": {"YUEYI 07PHEV": "YUEYI 07 PHEV"},
    "Ford": {"F150": "F-150", "FORD MODEL Y 8HP 399006": "", "TRANSIT/TRANSIT": "TRANSIT"},
    "Honda": {"CRV": "CR-V", "CR V": "CR-V", "HRV": "HR-V"},
    "Mazda": {"CX9": "CX-9"},
    "Opel": {"INSIGNIA LIMOUSINENB": "INSIGNIA LIMOUSINE NB"},
    "Rehatrans": {
        "TRAVELLER_EXPERT": "TRAVELLER EXPERT", "TRAVELLER-EXPERT": "TRAVELLER EXPERT",
        "TGEPMR": "TGE PMR", "SPACETOURER_JUMPY": "SPACETOURER JUMPY",
    },
    "Peugeot": {
        "PART TEP ACT": "PARTNER",  # truncated "Partner Tepee Active"
        "207SW": "207", "207 1.6 16V TURBO": "207",
    },
    "Tesla": {"MODEL3": "MODEL 3", "MODELY": "MODEL Y"},
    "Volkswagen": {"ID 3": "ID.3"},
    "Tripod": {
        "T-CLASS TRIPOD": "T CLASS TRIPOD", "CLASE T TRIPOD": "T CLASS TRIPOD",
        "T CLASS TRIPO": "T CLASS TRIPOD", "T CLASSS TRIPOD": "T CLASS TRIPOD",
    },
    "Caterham Cars Ltd": {"SEVEN SV(DA VARIANT)": "SEVEN SV (DA VARIANT)"},
    "Jaguar": {"JAGUAR XF": "XF"},
    "Fiat": {"FIAT 500X": "500X"},
    "Infiniti": {"INFINITI Q50": "Q50"},
    "Nissan": {
        "NISSAN OASHQAI": "QASHQAI", "NISSAZN QASHQAI": "QASHQAI",
        "NISSAN X-TRIL": "X-TRAIL", "NISSAN X- TRAIL": "X-TRAIL",
    },
    "Chevrolet": {"CHEVROLET CORVETTE": "CORVETTE"},
}

_VIN_FRAGMENT_RE = re.compile(r"\s[0-3][A-Z0-9]{7}$")
# DS (Citroen's premium spin-off) has no clean brand code in DGT's export and
# lands in "Sin Marca" with every trim/engine/generation variant fragmenting
# the model field: "DS 7 BLUEHDI 130", "DS 7 E-TENSE 4X4 300", "DS7 HC 16E
# HYA X", "NUEVO DS 3 E-TENSE"... all belong to one of DS 3/4/7/9.
_DS_MODEL_RE = re.compile(r"^(?:NUEVO\s+)?DS\s?(\d)\b")

def _normalize_modelo(brand, raw):
    m = (raw or "").strip().upper()
    if not m:
        return m
    # Version/trim leaked into the model field ("SERIE 1, 118D" -> "SERIE 1").
    m = m.split(",", 1)[0].strip()
    # DGT placeholder codes for unclassified models (just dashes), not a model.
    if re.fullmatch(r"-+", m):
        return ""
    # A stray trailing WMI/VDS-shaped VIN fragment leaked in for some rows
    # ("E-TRON 50 3WAUZZZG" -> "E-TRON 50"). Exactly 8 chars starting with
    # 0-3 to stay clear of real trim badges like Mercedes "4MATIC".
    m = _VIN_FRAGMENT_RE.sub("", m).strip()
    if brand == "Sin Marca":
        ds = _DS_MODEL_RE.match(m)
        if ds:
            return "DS " + ds.group(1)
    return _MODEL_NORM.get(brand, {}).get(m, m)

_FOCUS_SUBSEGMENTS = {
    "FOCUS SEGMENT",
    "TRADITIONAL COMPETITION",
    "NEW PLAYERS & TESLA",
}

_BRAND_CONCEPT = {
    "BMW": "TRAD. COMP.", "Bmw Ag": "TRAD. COMP.", "Alpina": "TRAD. COMP.",
    "Audi": "TRAD. COMP.", "T.R.Audi": "TRAD. COMP.",
    "Mercedes": "TRAD. COMP.", "Mercedes-V": "TRAD. COMP.",
    "MINI": "TRAD. COMP.", "Porsche": "TRAD. COMP.", "Volvo": "TRAD. COMP.",
    "Lexus": "TRAD. COMP.", "Jaguar": "TRAD. COMP.",
    "Land Rover": "TRAD. COMP.", "Land Rover Santana": "TRAD. COMP.",
    "Land  Rover": "TRAD. COMP.", "Genesis": "TRAD. COMP.",
    "Maserati": "TRAD. COMP.", "Ferrari": "TRAD. COMP.",
    "Lamborghini": "TRAD. COMP.", "Bentley": "TRAD. COMP.",
    "Rolls-Royce": "TRAD. COMP.", "McLaren": "TRAD. COMP.",
    "Aston Martin": "TRAD. COMP.", "Cadillac": "TRAD. COMP.",
    "Bugatti": "TRAD. COMP.", "Donkervoort": "TRAD. COMP.",
    "Tesla": "NEW PLAYERS & TESLA", "Tesla Motors": "NEW PLAYERS & TESLA",
    "Polestar": "NEW PLAYERS & TESLA", "Lotus": "NEW PLAYERS & TESLA",
    "Lotus Cars Ltd": "NEW PLAYERS & TESLA", "Smart": "NEW PLAYERS & TESLA",
    "Xpeng": "NEW PLAYERS & TESLA", "Zeekr": "NEW PLAYERS & TESLA",
    "Lucid Motors": "NEW PLAYERS & TESLA", "Voyah": "NEW PLAYERS & TESLA",
}


def _focus_bucket(raw):
    return "FOCUS SEGMENT" if (raw or "").strip().upper() in _FOCUS_SUBSEGMENTS else "REST"

def _focus_concept(brand):
    return _BRAND_CONCEPT.get(brand, "FOCUS OTHER")

def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            yield {k:(v.strip() if v is not None else "") for k,v in row.items()}

def load_simmix_scope(base, fallback_path=None):
    """Infer the valid Simmix export scope by year from BBDD_YYYY_PRODUCTO.csv.

    Some available Simmix exports are cut mid-brand (for example 2024 ends inside
    Mercedes and 2025 inside BMW). We treat that final incomplete brand as
    truncated and exclude it from the scope rather than mixing partial data.
    """
    scopes = {}
    diagnostics = {}
    fallback_path = Path(fallback_path) if fallback_path else None
    bbdd_dirs = [d for d in (VALIDATION_DIR, REPO_ROOT, base) if d.exists()]
    bbdd_paths = []
    seen = set()
    for d in bbdd_dirs:
        for p in sorted(d.glob("BBDD_*_PRODUCTO.csv")):
            if p.name not in seen:
                seen.add(p.name)
                bbdd_paths.append(p)
    for path in bbdd_paths:
        m = re.match(r"BBDD_(\d{4})_PRODUCTO$", path.stem)
        if not m:
            continue
        yr = int(m.group(1))
        brand_col = f"Brand_{yr}"
        regs_col = f"Registrations_{yr}"
        brands = set()
        totals = defaultdict(int)
        rows = 0
        malformed = 0
        truncated_brand = None

        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                rows += 1
                raw_brand = row.get(brand_col, "").strip()
                if not raw_brand or "," in raw_brand or row.get(None):
                    malformed += 1
                    continue
                brand_key = _normalize_brand(raw_brand).upper()
                raw_regs = (row.get(regs_col) or "").strip()
                if not raw_regs:
                    truncated_brand = brand_key
                    continue
                try:
                    n = int(float(raw_regs.replace(",", ".")))
                except ValueError:
                    malformed += 1
                    continue
                brands.add(brand_key)
                totals[brand_key] += n

        if truncated_brand:
            brands.discard(truncated_brand)

        scopes[yr] = brands
        diagnostics[yr] = {
            "file": path.name,
            "rows": rows,
            "valid_brands": len(brands),
            "truncated_brand": truncated_brand,
            "malformed_rows": malformed,
            "reference_total": sum(totals[b] for b in brands),
        }
    if scopes:
        return scopes, diagnostics

    if fallback_path and fallback_path.exists():
        try:
            payload = json.loads(fallback_path.read_text(encoding="utf-8"))
            brands_by_year = payload.get("brands_by_year", {})
            scopes = {
                int(yr): {str(brand).upper() for brand in brands}
                for yr, brands in brands_by_year.items()
            }
            diagnostics = {
                int(yr): diag
                for yr, diag in payload.get("diagnostics", {}).items()
            }
            return scopes, diagnostics
        except Exception as exc:
            print(f"  Scope Simmix: no se pudo leer fallback {fallback_path}: {exc}")

    return scopes, diagnostics

def save_simmix_scope(scope_path, scopes, diagnostics):
    if not scopes:
        return
    payload = {
        "source": "Derived from local Simmix BBDD exports; used by GitHub Actions when BBDD files are absent.",
        "brands_by_year": {
            str(yr): sorted(scopes[yr])
            for yr in sorted(scopes)
        },
        "diagnostics": {str(k): v for k, v in sorted(diagnostics.items())},
    }
    scope_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _candidate_simmix_2026_product_paths(base):
    paths = [VALIDATION_DIR / "BBDD_2026_PRODUCTO_06_30.csv",
             REPO_ROOT / "BBDD_2026_PRODUCTO_06_30.csv",
             base / "BBDD_2026_PRODUCTO_06_30.csv"]
    downloads = Path.home() / "Downloads"
    try:
        names = [
            n for n in downloads.iterdir()
            if n.name.upper().startswith("BBDD_2026_PRODUCTO") and n.suffix.lower() == ".csv"
        ]
        paths.extend(sorted(names, reverse=True))
    except OSError:
        pass
    return paths

def load_simmix_2026_targets(base, fallback_path):
    fallback_path = Path(fallback_path)
    for path in _candidate_simmix_2026_product_paths(base):
        if not path.exists():
            continue
        targets = defaultdict(int)
        brands = {}
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw_brand = (row.get("Brand_2026") or "").strip()
                canal = (row.get("Channel_2026") or "").strip()
                if not raw_brand or canal not in CANALES:
                    continue
                try:
                    n = int(float((row.get("Registrations_2026") or "0").replace(",", ".")))
                except ValueError:
                    continue
                if n <= 0:
                    continue
                brand = _normalize_brand(raw_brand)
                brand_key = brand.upper()
                sub = _focus_bucket(row.get("SubSegmento_2026", ""))
                brands[brand_key] = brand
                targets[(brand_key, canal, sub)] += n
        if targets:
            payload = {
                "source": path.name,
                "year": 2026,
                "month": 6,
                "rows": [
                    {"brand": brands[brand], "canal": canal, "sub": sub, "n": n}
                    for (brand, canal, sub), n in sorted(targets.items())
                ],
            }
            fallback_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload

    if fallback_path.exists():
        return json.loads(fallback_path.read_text(encoding="utf-8"))
    return None

def _allocate_to_target(rows, target):
    raw = sum(r["n"] for r in rows)
    if raw <= 0:
        return []

    allocations = []
    assigned = 0
    for i, row in enumerate(rows):
        ideal = row["n"] * target / raw
        base_n = int(ideal)
        assigned += base_n
        allocations.append((ideal - base_n, i, row, base_n))

    remaining = target - assigned
    allocations.sort(key=lambda item: (-item[0], item[1]))
    bonus = {i for _, i, _, _ in allocations[:remaining]} if remaining > 0 else set()
    out = []
    for _, i, row, base_n in allocations:
        n = base_n + (1 if i in bonus else 0)
        if n > 0:
            nr = row.copy()
            nr["n"] = n
            out.append(nr)
    return out

def apply_simmix_2026_targets(monthly_records, mtd_records, mtd_yr, mtd_mo, payload):
    if not payload:
        return monthly_records, mtd_records, {}
    target_year = int(payload.get("year", 0) or 0)
    target_month = int(payload.get("month", 0) or 0)
    if not target_year or not target_month:
        return monthly_records, mtd_records, {"status": "skipped", "reason": "invalid_target_period"}

    targets = {}
    brand_display = {}
    for row in payload.get("rows", []):
        brand = _normalize_brand(row.get("brand", ""))
        brand_key = brand.upper()
        canal = row.get("canal", "")
        sub = _focus_bucket(row.get("sub", ""))
        try:
            n = int(row.get("n", 0))
        except (TypeError, ValueError):
            n = 0
        if brand_key and canal in CANALES and n > 0:
            targets[(brand_key, canal, sub)] = targets.get((brand_key, canal, sub), 0) + n
            brand_display[brand_key] = brand

    all_records = [r.copy() for r in monthly_records] + [r.copy() for r in mtd_records]
    def in_target_period(r):
        return r["y"] == target_year and r["m"] <= target_month

    passthrough = [r for r in all_records if not in_target_period(r)]
    grouped = defaultdict(list)
    dropped = 0
    for r in all_records:
        if not in_target_period(r):
            continue
        key = (r["marca"].upper(), r["canal"], _focus_bucket(r["sub"]))
        if key in targets:
            r["sub"] = key[2]
            grouped[key].append(r)
        else:
            dropped += r["n"]

    aligned = list(passthrough)
    synthetic = 0
    adjusted_groups = 0
    for key, target in sorted(targets.items()):
        rows = grouped.get(key, [])
        if rows:
            raw = sum(r["n"] for r in rows)
            adjusted_groups += int(raw != target)
            aligned.extend(_allocate_to_target(rows, target))
            continue

        brand_key, canal, sub = key
        synthetic += target
        aligned.append({
            "y": target_year,
            "m": target_month,
            "marca": brand_display.get(brand_key, brand_key.title()),
            "modelo": "",
            "canal": canal,
            "fuel": "ICE",
            "fuel_det": "",
            "seg": "",
            "sub": sub,
            "hp": "Standard",
            "body": "",
            "n": target,
        })

    monthly_out = [r for r in aligned if not (r["y"] == mtd_yr and r["m"] == mtd_mo)]
    mtd_out = [r for r in aligned if r["y"] == mtd_yr and r["m"] == mtd_mo]
    stats = {
        "status": "applied",
        "year": target_year,
        "month": target_month,
        "groups": len(targets),
        "adjusted_groups": adjusted_groups,
        "dropped_records": dropped,
        "synthetic_residual": synthetic,
        "target_total": sum(targets.values()),
        "aligned_through_month": target_month,
    }
    return monthly_out, mtd_out, stats

def compute_simmix_drift(monthly_records, mtd_records, payload, min_units=200):
    """Informe de auditoría ETL vs export Simmix (sin mutar los datos).

    Compara los totales de la ETL propia por (marca, canal) del año objetivo
    contra el export Simmix. Es el KPI de la desconexión del proveedor.
    """
    if not payload:
        return {"status": "skipped", "reason": "sin export Simmix disponible"}
    target_year = int(payload.get("year", 0) or 0)
    target_month = int(payload.get("month", 0) or 12)
    targets = defaultdict(int)
    for row in payload.get("rows", []):
        brand = _normalize_brand(row.get("brand", "")).upper()
        canal = row.get("canal", "")
        try:
            n = int(row.get("n", 0))
        except (TypeError, ValueError):
            n = 0
        if brand and canal in CANALES and n > 0:
            targets[(brand, canal)] += n

    etl = defaultdict(int)
    for r in list(monthly_records) + list(mtd_records):
        if r["y"] == target_year and r["m"] <= target_month:
            etl[(r["marca"].upper(), r["canal"])] += r["n"]

    rows = []
    for key in sorted(set(targets) | set(etl)):
        t, e = targets.get(key, 0), etl.get(key, 0)
        if max(t, e) < min_units:
            continue
        delta = e - t
        pct = (100.0 * delta / t) if t else None
        rows.append({"marca": key[0], "canal": key[1], "etl": e, "simmix": t,
                     "delta": delta, "delta_pct": round(pct, 2) if pct is not None else None})
    rows.sort(key=lambda r: -abs(r["delta"]))
    total_t = sum(targets.values())
    total_e = sum(etl.get(k, 0) for k in targets) + sum(
        v for k, v in etl.items() if k not in targets)
    evaluated = [r for r in rows if r["delta_pct"] is not None]
    within = sum(1 for r in evaluated if abs(r["delta_pct"]) <= 2.0)
    return {
        "status": "computed",
        "source": payload.get("source"),
        "year": target_year,
        "total_etl": total_e,
        "total_simmix": total_t,
        "total_delta": total_e - total_t,
        "total_delta_pct": round(100.0 * (total_e - total_t) / total_t, 2) if total_t else None,
        "groups_evaluated": len(evaluated),
        "groups_within_2pct": within,
        "worst": rows[:40],
    }

def apply_simmix_scope(records, scopes):
    if not scopes:
        return records, {}
    kept = []
    stats = defaultdict(lambda: {"kept": 0, "excluded": 0, "scope_brands": 0})
    for r in records:
        scope = scopes.get(r["y"])
        if scope is None:
            kept.append(r)
            stats[r["y"]]["kept"] += r["n"]
            continue
        stats[r["y"]]["scope_brands"] = len(scope)
        if r["marca"].upper() in scope:
            kept.append(r)
            stats[r["y"]]["kept"] += r["n"]
        else:
            stats[r["y"]]["excluded"] += r["n"]
    return kept, {str(y): dict(v) for y, v in sorted(stats.items())}

# ── Carga datos ──────────────────────────────────────────────────────────────

def _load_channel_records(path, yr, mo):
    records = []
    for row in _read_csv(path):
        try:
            n = int(row.get("count", 0) or 0)
            if n <= 0: continue
            brand = _normalize_brand(row.get("marca", ""))
            records.append({
                "y":        yr,
                "m":        mo,
                "marca":    brand,
                "modelo":   _normalize_modelo(brand, row.get("modelo", "")),
                "canal":    row.get("canal", ""),
                "fuel":     row.get("fuel_type", "ICE") or "ICE",
                "fuel_det": row.get("fuel", "").strip(),
                "seg":      row.get("segmento", ""),
                "sub":      _focus_bucket(row.get("subseg", "")),
                "hp":       row.get("hp", ""),
                "body":     row.get("body_type", ""),
                "n":        n,
            })
        except (ValueError, KeyError):
            pass
    return records

def _mtd_files(base):
    files = []
    for f in sorted(glob.glob(str(base/"dgt_canal_*_mtd.csv"))):
        m = re.match(r"dgt_canal_(\d{4})(\d{2})_mtd$", Path(f).stem)
        if m:
            files.append((int(m.group(1)), int(m.group(2)), f))
    return files

def load_monthly(base):
    records = []
    completed = set()
    for f in sorted(glob.glob(str(base/"dgt_canal_[0-9][0-9][0-9][0-9][0-9][0-9].csv"))):
        m = re.match(r"dgt_canal_(\d{4})(\d{2})$", Path(f).stem)
        if not m: continue
        yr, mo = int(m.group(1)), int(m.group(2))
        records.extend(_load_channel_records(f, yr, mo))
        completed.add((yr, mo))

    mtd_files = _mtd_files(base)
    if mtd_files:
        latest_mtd = max((yr, mo) for yr, mo, _ in mtd_files)
        for yr, mo, f in mtd_files:
            if (yr, mo) != latest_mtd and (yr, mo) not in completed:
                records.extend(_load_channel_records(f, yr, mo))
                completed.add((yr, mo))
    return records

def load_mtd(base):
    files = _mtd_files(base)
    if not files: return [], None, None
    yr, mo, f = files[-1]
    return _load_channel_records(f, yr, mo), yr, mo

def load_daily(base):
    data = defaultdict(int)
    for f in sorted(glob.glob(str(base/"dgt_canal_daily_[0-9]*.csv"))):
        m = re.match(r"dgt_canal_daily_(\d{4})(\d{2})(\d{2})$", Path(f).stem)
        if not m: continue
        yr, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        for row in _read_csv(f):
            try:
                fuel  = row.get("fuel_type", "ICE") or "ICE"
                canal = row.get("canal", "")
                if canal not in CANALES: continue
                data[(yr, mo, dy, canal, fuel)] += int(row.get("count", 0) or 0)
            except (ValueError, KeyError):
                pass
    return data

def load_provinces(base):
    data = defaultdict(int)
    completed = set()
    for f in sorted(glob.glob(str(base/"dgt_prov_[0-9][0-9][0-9][0-9][0-9][0-9].csv"))):
        m = re.match(r"dgt_prov_(\d{4})(\d{2})$", Path(f).stem)
        if not m: continue
        yr, mo = int(m.group(1)), int(m.group(2))
        completed.add((yr, mo))
        for row in _read_csv(f):
            try:
                fuel = row.get("fuel_type", "ICE") or "ICE"
                marca = _normalize_brand(row.get("marca", ""))
                seg = row.get("segmento", "") or ""
                sub = row.get("subseg", "") or ""
                hp  = row.get("hp", "") or ""
                data[(yr, mo, marca, row["cod_prov"], row["provincia"], row["canal"], fuel, seg, sub, hp)] += int(row.get("count", 0) or 0)
            except (ValueError, KeyError):
                pass
    for f in sorted(glob.glob(str(base/"dgt_prov_daily_[0-9]*.csv"))):
        m = re.match(r"dgt_prov_daily_(\d{4})(\d{2})(\d{2})$", Path(f).stem)
        if not m: continue
        yr, mo = int(m.group(1)), int(m.group(2))
        if (yr, mo) in completed:
            continue
        for row in _read_csv(f):
            try:
                canal = row.get("canal", "")
                if canal not in CANALES:
                    continue
                fuel = row.get("fuel_type", "ICE") or "ICE"
                marca = _normalize_brand(row.get("marca", ""))
                seg = row.get("segmento", "") or ""
                sub = row.get("subseg", "") or ""
                hp  = row.get("hp", "") or ""
                data[(yr, mo, marca, row["cod_prov"], row["provincia"], canal, fuel, seg, sub, hp)] += int(row.get("count", 0) or 0)
            except (ValueError, KeyError):
                pass
    return data

def apply_simmix_scope_provinces(prov_data, scopes):
    if not scopes:
        return prov_data, {}
    kept = defaultdict(int)
    stats = defaultdict(lambda: {"kept": 0, "excluded": 0, "scope_brands": 0})
    for key, cnt in prov_data.items():
        yr, mo, marca = key[0], key[1], key[2]
        scope = scopes.get(yr)
        if scope is None:
            kept[key] += cnt
            stats[yr]["kept"] += cnt
            continue
        stats[yr]["scope_brands"] = len(scope)
        if marca and marca.upper() in scope:
            kept[key] += cnt
            stats[yr]["kept"] += cnt
        else:
            stats[yr]["excluded"] += cnt
    return kept, {str(y): dict(v) for y, v in sorted(stats.items())}

# ── Construcción JSONs ────────────────────────────────────────────────────────

def build_records_json(monthly_records, mtd_records, mtd_yr, mtd_mo, scope_info=None):
    """
    Layout columnas (sincronizado con COL en index.html):
      0:y  1:m  2:marca  3:modelo  4:canal(0-2)  5:fuel(0-2)
      6:fuel_det  7:seg  8:sub  9:hp  10:body  11:n
    """
    completed = {(r["y"], r["m"]) for r in monthly_records}
    all_records = list(monthly_records)
    if mtd_yr and (mtd_yr, mtd_mo) not in completed:
        all_records.extend(mtd_records)

    if not all_records:
        return {"cols": [], "rows": [], "meta": {}}

    marca_idx    = {}; marcas    = []
    modelo_idx   = {}; modelos   = []
    fuel_det_idx = {}; fuel_dets = []
    seg_idx      = {}; segs      = []
    sub_idx      = {}; subs      = []
    hp_idx       = {}; hps       = []
    body_idx     = {}; bodies    = []

    canal_map = {"Private": 0, "Corporate": 1, "RAC": 2}
    fuel_map  = {"ICE": 0, "BEV": 1, "PHEV": 2}

    def idx(val, d, lst):
        if val not in d:
            d[val] = len(lst)
            lst.append(val)
        return d[val]

    rows = []
    for r in all_records:
        rows.append([
            r["y"], r["m"],
            idx(r["marca"],    marca_idx,    marcas),
            idx(r["modelo"],   modelo_idx,   modelos),
            canal_map.get(r["canal"], 0),
            fuel_map.get(r["fuel"], 0),
            idx(r["fuel_det"], fuel_det_idx, fuel_dets),
            idx(r["seg"],      seg_idx,      segs),
            idx(r["sub"],      sub_idx,      subs),
            idx(r["hp"],       hp_idx,       hps),
            idx(r["body"],     body_idx,     bodies),
            r["n"],
        ])

    total = sum(r[-1] for r in rows)
    months_present = sorted({(r[0], r[1]) for r in rows})

    return {
        "cols": ["y","m","marca","modelo","canal","fuel","fuel_det","seg","sub","hp","body","n"],
        "enums": {
            "canal":    ["Private","Corporate","RAC"],
            "fuel":     ["ICE","BEV","PHEV"],
            "fuel_det": fuel_dets,
            "marca":    marcas,
            "modelo":   modelos,
            "seg":      segs,
            "sub":      subs,
            "hp":       hps,
            "body":     bodies,
        },
        "rows":   rows,
        "total":  total,
        "months": [{"y":y,"m":mo,"label":f"{MONTHS_ES[mo]} {y}"} for y,mo in months_present],
        "mtd":    {"y":mtd_yr,"m":mtd_mo} if mtd_yr else None,
        "scope":  scope_info or {"mode": "dgt"},
    }

def _load_prov_records_file(path, yr, mo):
    """Lee un dgt_prov[_daily] con grano modelo+provincia -> lista de dicts."""
    out = []
    for row in _read_csv(path):
        try:
            n = int(row.get("count", 0) or 0)
            if n <= 0:
                continue
            canal = row.get("canal", "")
            if canal not in CANALES:
                continue
            brand = _normalize_brand(row.get("marca", ""))
            out.append({
                "y":      yr,
                "m":      mo,
                "marca":  brand,
                "modelo": _normalize_modelo(brand, row.get("modelo", "")),
                "cod":    row.get("cod_prov", ""),
                "prov":   row.get("provincia", "") or "",
                "canal":  canal,
                "fuel":   row.get("fuel_type", "ICE") or "ICE",
                "seg":    row.get("segmento", "") or "",
                "sub":    _focus_bucket(row.get("subseg", "")),
                "hp":     row.get("hp", "") or "",
                "body":   row.get("body_type", "") or "",
                "n":      n,
            })
        except (ValueError, KeyError):
            pass
    return out


def load_prov_records(base):
    """Registros con grano marca+modelo+provincia (mensuales + MTD desde diarios).

    Requiere dgt_prov_*.csv con columnas modelo/body_type (pipeline nuevo).
    Los meses sin modelo (historico antiguo) simplemente aportan modelo vacio."""
    records = []
    completed = set()
    for f in sorted(glob.glob(str(base/"dgt_prov_[0-9][0-9][0-9][0-9][0-9][0-9].csv"))):
        m = re.match(r"dgt_prov_(\d{4})(\d{2})$", Path(f).stem)
        if not m:
            continue
        yr, mo = int(m.group(1)), int(m.group(2))
        completed.add((yr, mo))
        records.extend(_load_prov_records_file(f, yr, mo))
    for f in sorted(glob.glob(str(base/"dgt_prov_daily_[0-9]*.csv"))):
        m = re.match(r"dgt_prov_daily_(\d{4})(\d{2})(\d{2})$", Path(f).stem)
        if not m:
            continue
        yr, mo = int(m.group(1)), int(m.group(2))
        if (yr, mo) in completed:
            continue
        records.extend(_load_prov_records_file(f, yr, mo))
    return records


_DEALER_NAME_BY_ID = None


def _dealer_name_by_id():
    """Canonical dealer labels keyed by normalized brand and stable point ID."""
    global _DEALER_NAME_BY_ID
    if _DEALER_NAME_BY_ID is None:
        import audit_multibrand_dealer_proxy as dealer_proxy
        import bmw_dealer_territory as bmw_dealer
        points = dealer_proxy.load_points(
            dealer_proxy.DEFAULT_MASTER, official_only=True
        )
        _DEALER_NAME_BY_ID = {
            (_normalize_brand(brand), row["dealer_id"]): row["dealer_name"]
            for brand, brand_points in points.items()
            if brand != "BMW"
            for row in brand_points
        }
        _DEALER_NAME_BY_ID.update({
            ("BMW", dealer_id): dealer_name
            for dealer_id, dealer_name in bmw_dealer.load_active_dealers().items()
        })
        # MINI is sold through the same BMW Group dealer groups in Spain and
        # resolves via the same municipality-territory proxy (process_month.py).
        _DEALER_NAME_BY_ID.update({
            ("MINI", dealer_id): dealer_name
            for dealer_id, dealer_name in bmw_dealer.load_active_dealers().items()
        })
    return _DEALER_NAME_BY_ID


def _load_dealer_records_file(path, yr, mo):
    """Read a resolved Private dealer aggregate produced while parsing DGT raw."""
    out = []
    for row in _read_csv(path):
        try:
            n = int(row.get("count", 0) or 0)
            dealer = (row.get("dealer_estimated", "") or "").strip()
            source_confidence = (row.get("source_confidence", "") or "").strip()
            if (
                n <= 0
                or not dealer
                or source_confidence not in {"official", "internal"}
            ):
                continue
            marca = _normalize_brand(row.get("marca", ""))
            dealer_id = (row.get("dealer_id", "") or "").strip()
            dealer = _dealer_name_by_id().get((marca, dealer_id))
            if not dealer:
                continue
            out.append({
                "y": yr,
                "m": mo,
                "marca": marca,
                "modelo": _normalize_modelo(marca, row.get("modelo", "")),
                "canal": row.get("canal", "Private") or "Private",
                "fuel": row.get("fuel_type", "ICE") or "ICE",
                "fuel_det": row.get("fuel", "") or "",
                "seg": row.get("segmento", "") or "",
                "sub": _focus_bucket(row.get("subseg", "")),
                "hp": row.get("hp", "") or "",
                "body": row.get("body_type", "") or "",
                "prov": row.get("provincia", "") or "",
                "dealer": "{} | {}".format(marca, dealer),
                "confidence": row.get("confidence", "") or "",
                "source_confidence": row.get("source_confidence", "") or "",
                "n": n,
            })
        except (TypeError, ValueError, KeyError):
            pass
    return out


def load_dealer_records(base):
    """Load monthly dealer aggregates and daily rows only for incomplete months."""
    records = []
    completed = set()
    pattern = str(base / "dgt_dealer_[0-9][0-9][0-9][0-9][0-9][0-9].csv")
    for filename in sorted(glob.glob(pattern)):
        match = re.match(r"dgt_dealer_(\d{4})(\d{2})$", Path(filename).stem)
        if not match:
            continue
        yr, mo = int(match.group(1)), int(match.group(2))
        completed.add((yr, mo))
        records.extend(_load_dealer_records_file(filename, yr, mo))
    for filename in sorted(glob.glob(str(base / "dgt_dealer_daily_[0-9]*.csv"))):
        match = re.match(r"dgt_dealer_daily_(\d{4})(\d{2})(\d{2})$", Path(filename).stem)
        if not match:
            continue
        yr, mo = int(match.group(1)), int(match.group(2))
        if (yr, mo) in completed:
            continue
        records.extend(_load_dealer_records_file(filename, yr, mo))
    return records


def build_records_dealer_json(dealer_records, mtd_yr, mtd_mo, scope_info=None):
    """Compact lazy dataset with the canonical record dimensions plus dealer."""
    agg = defaultdict(int)
    for row in dealer_records:
        key = (
            row["y"], row["m"], row["marca"], row["modelo"], row["canal"],
            row["fuel"], row["fuel_det"], row["seg"], row["sub"], row["hp"],
            row["body"], row["prov"], row["dealer"], row["confidence"],
            row["source_confidence"],
        )
        agg[key] += row["n"]

    if not agg:
        return {
            "cols": [], "rows": [], "enums": {}, "total": 0, "months": [],
            "mtd": None, "scope": scope_info or {"mode": "dgt"},
        }

    enum_names = (
        "marca", "modelo", "fuel_det", "seg", "sub", "hp", "body", "prov",
        "dealer", "confidence", "source_confidence",
    )
    indexes = {name: {} for name in enum_names}
    enums = {name: [] for name in enum_names}
    canal_map = {"Private": 0, "Corporate": 1, "RAC": 2}
    fuel_map = {"ICE": 0, "BEV": 1, "PHEV": 2}

    def idx(name, value):
        if value not in indexes[name]:
            indexes[name][value] = len(enums[name])
            enums[name].append(value)
        return indexes[name][value]

    rows = []
    for key, n in agg.items():
        (y, mo, marca, modelo, canal, fuel, fuel_det, seg, sub, hp, body,
         prov, dealer, confidence, source_confidence) = key
        rows.append([
            y, mo, idx("marca", marca), idx("modelo", modelo),
            canal_map.get(canal, 0), fuel_map.get(fuel, 0),
            idx("fuel_det", fuel_det), idx("seg", seg), idx("sub", sub),
            idx("hp", hp), idx("body", body), idx("prov", prov),
            idx("dealer", dealer), idx("confidence", confidence),
            idx("source_confidence", source_confidence), n,
        ])

    months_present = sorted({(row[0], row[1]) for row in rows})
    enums.update({
        "canal": ["Private", "Corporate", "RAC"],
        "fuel": ["ICE", "BEV", "PHEV"],
    })
    return {
        "cols": [
            "y", "m", "marca", "modelo", "canal", "fuel", "fuel_det",
            "seg", "sub", "hp", "body", "prov", "dealer", "confidence",
            "source_confidence", "n",
        ],
        "enums": enums,
        "rows": rows,
        "total": sum(row[-1] for row in rows),
        "months": [
            {"y": y, "m": mo, "label": "{} {}".format(MONTHS_ES[mo], y)}
            for y, mo in months_present
        ],
        "mtd": {"y": mtd_yr, "m": mtd_mo} if mtd_yr else None,
        "scope": scope_info or {"mode": "dgt"},
    }


def build_records_prov_json(prov_records, mtd_yr, mtd_mo, scope_info=None):
    """records_prov.json: mismo formato columnar indexado que records.json pero
    con dimension prov. Se carga en el dashboard SOLO cuando el filtro de
    provincia esta activo (Overview/Ranking/Channel&Monthly). Agrega los dicts de
    load_prov_records por la clave completa para colapsar duplicados diarios."""
    agg = defaultdict(int)
    for r in prov_records:
        key = (r["y"], r["m"], r["marca"], r["modelo"], r["canal"], r["fuel"],
               r["seg"], r["sub"], r["hp"], r["body"], r["cod"], r["prov"])
        agg[key] += r["n"]

    if not agg:
        return {"cols": [], "rows": [], "enums": {}, "total": 0, "months": [],
                "mtd": None, "scope": scope_info or {"mode": "dgt"}}

    marca_idx  = {}; marcas  = []
    modelo_idx = {}; modelos = []
    seg_idx    = {}; segs    = []
    sub_idx    = {}; subs    = []
    hp_idx     = {}; hps     = []
    body_idx   = {}; bodies  = []
    prov_idx   = {}; provs   = []

    canal_map = {"Private": 0, "Corporate": 1, "RAC": 2}
    fuel_map  = {"ICE": 0, "BEV": 1, "PHEV": 2}

    def idx(val, d, lst):
        if val not in d:
            d[val] = len(lst)
            lst.append(val)
        return d[val]

    rows = []
    for (y, mo, marca, modelo, canal, fuel, seg, sub, hp, body, cod, prov), n in agg.items():
        rows.append([
            y, mo,
            idx(marca,  marca_idx,  marcas),
            idx(modelo, modelo_idx, modelos),
            canal_map.get(canal, 0),
            fuel_map.get(fuel, 0),
            idx(seg,  seg_idx,  segs),
            idx(sub,  sub_idx,  subs),
            idx(hp,   hp_idx,   hps),
            idx(body, body_idx, bodies),
            idx(prov, prov_idx, provs),
            n,
        ])

    total = sum(r[-1] for r in rows)
    months_present = sorted({(r[0], r[1]) for r in rows})

    return {
        "cols": ["y","m","marca","modelo","canal","fuel","seg","sub","hp","body","prov","n"],
        "enums": {
            "canal":  ["Private","Corporate","RAC"],
            "fuel":   ["ICE","BEV","PHEV"],
            "marca":  marcas,
            "modelo": modelos,
            "seg":    segs,
            "sub":    subs,
            "hp":     hps,
            "body":   bodies,
            "prov":   provs,
        },
        "rows":   rows,
        "total":  total,
        "months": [{"y":y,"m":mo,"label":f"{MONTHS_ES[mo]} {y}"} for y,mo in months_present],
        "mtd":    {"y":mtd_yr,"m":mtd_mo} if mtd_yr else None,
        "scope":  scope_info or {"mode": "dgt"},
    }


def _zero():
    return {c: 0 for c in CANALES + FUELS}

def build_daily_mtd_json(daily_data, cy, cm):
    dm = defaultdict(_zero)
    for (y, mo, day, canal, fuel), cnt in daily_data.items():
        if y != cy or mo != cm or canal not in CANALES: continue
        fuel2 = fuel if fuel in FUELS else "ICE"
        dm[day][canal] += cnt
        dm[day][fuel2] += cnt

    days_sorted = sorted(dm)
    cumul = _zero()
    days_out = []
    for day in days_sorted:
        d = dm[day]
        for c in CANALES + FUELS:
            cumul[c] += d[c]
        days_out.append({
            "day": day,
            "daily": {"Private":d["Private"],"Corporate":d["Corporate"],"RAC":d["RAC"],
                      "total":d["Private"]+d["Corporate"]+d["RAC"],
                      "ICE":d["ICE"],"BEV":d["BEV"],"PHEV":d["PHEV"]},
            "cumul": {"Private":cumul["Private"],"Corporate":cumul["Corporate"],"RAC":cumul["RAC"],
                      "total":cumul["Private"]+cumul["Corporate"]+cumul["RAC"],
                      "ICE":cumul["ICE"],"BEV":cumul["BEV"],"PHEV":cumul["PHEV"]},
        })
    return {"year":cy,"month":cm,"month_label":MONTHS_ES[cm],"days":days_out}


def build_province_brand_ranking(prov_data, monthly_records, mtd_records):
    """province_brands.json: provincia x marca Focus x [total, BEV, PHEV, canal*fuel...].

    Alimenta el ranking Top-5 provincial del dashboard. Las marcas Focus se
    derivan de los datos (mayoria de volumen en FOCUS SEGMENT), sin listas
    hardcodeadas, para que altas nuevas (Xpeng, Polestar...) entren solas.
    """
    vol = defaultdict(lambda: [0, 0])
    for r in list(monthly_records) + list(mtd_records):
        v = vol[r["marca"]]
        v[0] += r["n"]
        if r["sub"] == "FOCUS SEGMENT":
            v[1] += r["n"]
    focus = {m for m, (t, f) in vol.items() if t > 0 and f / t >= 0.5}
    focus |= {"BYD"}   # inclusion explicita solicitada (no es Focus por volumen)

    out = {}
    years = set()
    months = set()
    for key, cnt in prov_data.items():
        # Soporte backward-compat: clave antigua (7), sub/hp (9) y seg/sub/hp (10)
        if len(key) == 10:
            yr, mo, marca, cod, nombre, canal, fuel, seg, sub, hp = key
        elif len(key) == 9:
            yr, mo, marca, cod, nombre, canal, fuel, sub, hp = key
            seg = ""
        elif len(key) == 7:
            yr, mo, marca, cod, nombre, canal, fuel = key
            seg = sub = hp = ""
        else:
            continue
        if canal not in CANALES or marca not in focus:
            continue
        years.add(yr)
        ym = f"{yr}-{mo:02d}"
        months.add(ym)
        d = out.setdefault(cod, {"name": nombre, "years": {}, "months": {},
                                  "years_filt": {}, "months_filt": {}})
        d["name"] = nombre
        # Estructura principal (agrega todos los sub/hp — comportamiento original)
        cell  = d["years"].setdefault(yr, {}).setdefault(marca, [0] * 12)
        mcell = d["months"].setdefault(ym, {}).setdefault(marca, [0] * 12)
        # Estructura filt: clave "marca|seg|sub|hp" → [total, BEV, PHEV, canal*fuel...]
        fk = f"{marca}|{seg}|{sub}|{hp}"
        fcell  = d["years_filt"].setdefault(yr, {}).setdefault(fk, [0] * 12)
        mfcell = d["months_filt"].setdefault(ym, {}).setdefault(fk, [0] * 12)
        ci = 3 + CANALES.index(canal) * len(FUELS) + FUELS.index(fuel)
        for c in (cell, mcell, fcell, mfcell):
            c[0] += cnt
            if fuel == "BEV":
                c[1] += cnt
            elif fuel == "PHEV":
                c[2] += cnt
            c[ci] += cnt

    provinces = [
        {"cod": cod, "name": d["name"],
         "years":       {str(y): brands for y, brands in sorted(d["years"].items())},
         "months":      {ym: brands for ym, brands in sorted(d["months"].items())},
         "years_filt":  {str(y): fk for y, fk in sorted(d["years_filt"].items())},
         "months_filt": {ym: fk for ym, fk in sorted(d["months_filt"].items())}}
        for cod, d in sorted(out.items())
    ]
    return {"years": sorted(years), "months": sorted(months),
            "focus_brands": sorted(focus), "provinces": provinces}

def build_daily_brand_trend(base):
    """daily_brands.json: por marca y dia, matriz 3x3 canal x fuel.

    Celda idx = canal_idx*3 + fuel_idx, con canal en orden CANALES
    (Private, Corporate, RAC) y fuel en orden FUELS (ICE, BEV, PHEV).
    Permite que el tab Trend respete los filtros de canal, fuel y subsegmento.
    """
    days = {}
    sub_days = {}
    for f in sorted(glob.glob(str(base / "dgt_canal_daily_[0-9]*.csv"))):
        m = re.match(r"dgt_canal_daily_(\d{4})(\d{2})(\d{2})$", Path(f).stem)
        if not m:
            continue
        day = "{}-{}-{}".format(m.group(1), m.group(2), m.group(3))
        agg = {}
        sub_agg = {}
        for row in _read_csv(f):
            try:
                n = int(row.get("count", 0) or 0)
                if n <= 0:
                    continue
                canal = row.get("canal", "")
                if canal not in CANALES:
                    continue
                fuel = row.get("fuel_type", "ICE") or "ICE"
                if fuel not in FUELS:
                    fuel = "ICE"
                b = _normalize_brand(row.get("marca", ""))
                cell = CANALES.index(canal) * 3 + FUELS.index(fuel)
                agg.setdefault(b, [0] * 9)[cell] += n
                sub = _focus_bucket(row.get("subseg", ""))
                sub_key = "REST" if sub == "REST" else _focus_concept(b)
                by_brand = sub_agg.setdefault(b, {})
                by_brand.setdefault(sub_key, [0] * 9)[cell] += n
                if sub != "REST":
                    by_brand.setdefault("FOCUS", [0] * 9)[cell] += n
            except (ValueError, KeyError):
                pass
        if agg:
            days[day] = {b: v for b, v in sorted(agg.items())}
            sub_days[day] = {
                b: {k: vv for k, vv in sorted(v.items())}
                for b, v in sorted(sub_agg.items())
            }
    brands = sorted({b for d in days.values() for b in d})
    return {"canales": CANALES, "fuels": FUELS,
            "days": [{"day": k, "brands": v, "subBrands": sub_days.get(k, {})} for k, v in sorted(days.items())],
            "brands": brands}

def build_provinces_json(prov_data):
    if not prov_data:
        return {"provinces":[],"by_month":{}}
    pt  = defaultdict(lambda:{"name":"",**_zero()})
    pbm = defaultdict(lambda:defaultdict(_zero))
    for key,cnt in prov_data.items():
        if len(key) == 10:
            yr, mo, _marca, cod, nombre, canal, fuel, _seg, _sub, _hp = key
        elif len(key) == 9:
            yr, mo, _marca, cod, nombre, canal, fuel, _sub, _hp = key
        elif len(key) == 7:
            yr, mo, _marca, cod, nombre, canal, fuel = key
        else:
            yr, mo, cod, nombre, canal, fuel = key
        if canal not in CANALES: continue
        fuel2 = fuel if fuel in FUELS else "ICE"
        pt[cod]["name"] = nombre
        pt[cod][canal] += cnt; pt[cod][fuel2] += cnt
        pbm[cod][f"{yr}-{mo:02d}"][canal] += cnt; pbm[cod][f"{yr}-{mo:02d}"][fuel2] += cnt

    provs = []
    for cod, d in sorted(pt.items()):
        bm = {}
        for ym, cv in pbm[cod].items():
            bm[ym]={"Private":cv["Private"],"Corporate":cv["Corporate"],"RAC":cv["RAC"],
                    "total":cv["Private"]+cv["Corporate"]+cv["RAC"],
                    "ICE":cv["ICE"],"BEV":cv["BEV"],"PHEV":cv["PHEV"]}
        provs.append({"cod":cod,"name":d["name"],
            "total":d["Private"]+d["Corporate"]+d["RAC"],
            "Private":d["Private"],"Corporate":d["Corporate"],"RAC":d["RAC"],
            "ICE":d["ICE"],"BEV":d["BEV"],"PHEV":d["PHEV"],"by_month":bm})
    provs.sort(key=lambda x:-x["total"])

    all_ym = sorted({ym for cod in pbm for ym in pbm[cod]})
    by_month = {}
    for ym in all_ym:
        rows = []
        for cod, d in pt.items():
            cv = pbm[cod].get(ym, _zero())
            t  = cv.get("Private",0)+cv.get("Corporate",0)+cv.get("RAC",0)
            if t>0:
                rows.append({"cod":cod,"name":d["name"],"total":t,
                    "Private":cv.get("Private",0),"Corporate":cv.get("Corporate",0),
                    "RAC":cv.get("RAC",0),"ICE":cv.get("ICE",0),
                    "BEV":cv.get("BEV",0),"PHEV":cv.get("PHEV",0)})
        by_month[ym]=sorted(rows,key=lambda x:-x["total"])
    return {"provinces":provs,"by_month":by_month}

def build_pending_classification(monthly_records, mtd_records):
    """pending_classification.json — cola diaria de revision manual.

    1. Marcas nuevas: primera aparicion en los ultimos 6 meses y volumen >=50.
    2. Modelos sin clasificar: sin segmento, >=50 uds en el anyo en curso.
    Las decisiones se persisten en masters/master_clasificacion_manual.csv.
    """
    rows = list(monthly_records) + list(mtd_records)
    if not rows:
        return {"new_brands": [], "unclassified_models": []}
    last = max((r["y"], r["m"]) for r in rows)
    cur_year = last[0]
    horizon = (last[0] * 12 + last[1]) - 6

    first_seen = {}
    vol12 = defaultdict(int)
    brand_models = defaultdict(lambda: defaultdict(int))
    for r in rows:
        b = r["marca"]
        ym = r["y"] * 12 + r["m"]
        if b not in first_seen or ym < first_seen[b]:
            first_seen[b] = ym
        if ym > (last[0] * 12 + last[1]) - 12:
            vol12[b] += r["n"]
            mo = r.get("modelo") or "(sin modelo)"
            brand_models[b][mo] += r["n"]

    def _brand_entry(b):
        models = sorted(
            [{"modelo": mo, "uds": n} for mo, n in brand_models[b].items()],
            key=lambda x: -x["uds"]
        )[:15]
        return {"marca": b,
         "desde": f"{first_seen[b] // 12}-{(first_seen[b] % 12) or 12:02d}"
                  if first_seen[b] % 12 else f"{first_seen[b] // 12 - 1}-12",
         "uds_12m": vol12[b],
         "models": models}

    new_brands = sorted((
        _brand_entry(b)
        for b in vol12
        if first_seen[b] >= horizon and vol12[b] >= 1 and b not in _KNOWN_CLASSIFIED
    ), key=lambda x: -x["uds_12m"])

    pend = defaultdict(int)
    for r in rows:
        if r["y"] == cur_year and not (r["seg"] or "").strip():
            pend[(r["marca"], r["modelo"] or "(sin modelo)")] += r["n"]
    unclassified = sorted((
        {"marca": m, "modelo": mo, "uds": n}
        for (m, mo), n in pend.items() if n >= 50
    ), key=lambda x: -x["uds"])

    return {
        "generated": date.today().isoformat(),
        "year": cur_year,
        "new_brands": new_brands,
        "unclassified_models": unclassified[:200],
        "how_to": "Decidir y anadir fila en masters/master_clasificacion_manual.csv (brand,model,seg,sub,hp,body,fuel_detail); el siguiente run la aplica.",
    }

def build_forecast(monthly_records, mtd_records, daily_brands_obj):
    """forecast.json — motor del modelo predictivo (ver docs/MODELO_PREDICTIVO.md).

    Mercado ex-RAC: blend 0,10*A + 0,50*B + 0,40*E con correccion de sesgo
    adaptativa (residuo medio 6m) y componente intramensual D con peso creciente.
    Bandas empiricas: conservador x0,94 / optimista x1,04 (P10/P90 backtest).
    Marcas: cuota 0,6*3m + 0,4*12m con momentum acotado [0,8, 1,5].
    """
    W_A, W_B, W_E = 0.10, 0.50, 0.40
    BAND_OPT, BAND_CONS = 1.04, 0.94

    ex = defaultdict(float)
    exb = defaultdict(lambda: defaultdict(float))
    racm = defaultdict(float)
    for r in monthly_records:
        ym = r["y"] * 100 + r["m"]
        if r["canal"] == "RAC":
            racm[ym] += r["n"]
        else:
            ex[ym] += r["n"]
            exb[ym][r["marca"]] += r["n"]
    yms = sorted(ex)
    if len(yms) < 26:
        return {"status": "skipped", "reason": "historico insuficiente"}

    mtd_ym = None
    mtd_ex = 0.0
    mtd_brands = defaultdict(float)
    mtd_rac = 0.0
    for r in mtd_records:
        mtd_ym = r["y"] * 100 + r["m"]
        if r["canal"] != "RAC":
            mtd_ex += r["n"]
            mtd_brands[r["marca"]] += r["n"]
        else:
            mtd_rac += r["n"]
    if mtd_ym is None:
        return {"status": "skipped", "reason": "sin MTD"}
    ty, tm = divmod(mtd_ym, 100)

    seas = defaultdict(list)
    for y in (2023, 2024, 2025):
        yr = [ym for ym in yms if ym // 100 == y]
        if len(yr) == 12:
            tot = sum(ex[m] for m in yr)
            for m in yr:
                seas[m % 100].append(ex[m] / tot)
    s = {m: sum(v) / len(v) for m, v in seas.items()}

    def back12(ym):
        y, m = divmod(ym, 100)
        return (y - 1) * 100 + m

    def blend_for(ym, hist):
        i = hist.index(ym) if ym in hist else len(hist)
        l12 = hist[i - 12:i]
        p12 = hist[i - 24:i - 12]
        m3 = hist[i - 3:i]
        m1 = hist[i - 1]
        trend = sum(ex[x] for x in l12) / max(1.0, sum(ex[x] for x in p12))
        A = ex.get(back12(ym), 0) * trend
        B = (sum(ex[x] for x in m3) / 3) * s[ym % 100] / (sum(s[x % 100] for x in m3) / 3)
        E = ex[m1] * s[ym % 100] / s[m1 % 100]
        return W_A * A + W_B * B + W_E * E, trend

    resid = []
    for ym in yms[-6:]:
        f, _ = blend_for(ym, yms)
        if f > 0:
            resid.append(ex[ym] / f - 1)
    bias = 1 + (sum(resid) / len(resid) if resid else 0)

    f_blend, trend12 = blend_for(mtd_ym, yms + [mtd_ym])
    f_blend *= bias

    def day_exrac(brands):
        t = 0
        for v in brands.values():
            t += sum(v[0:6]) if isinstance(v, list) else v
        return t
    days = daily_brands_obj.get("days", [])
    prev_mm = f"{(ty if tm > 1 else ty - 1)}-{(tm - 1 if tm > 1 else 12):02d}"
    cur_mm = f"{ty}-{tm:02d}"
    curve_days = [day_exrac(d["brands"]) for d in days if d["day"].startswith(prev_mm)]
    k_days = sum(1 for d in days if d["day"].startswith(cur_mm))
    import calendar
    bdays_target = sum(1 for dd in range(1, calendar.monthrange(ty, tm)[1] + 1)
                       if calendar.weekday(ty, tm, dd) < 5)
    f_mtd = None
    w_d = 0.0
    if curve_days and k_days and mtd_ex:
        tot = sum(curve_days)
        cum = 0.0
        curve = []
        for v in curve_days:
            cum += v
            curve.append(cum / tot)
        pos = min(len(curve) - 1, max(0, round(k_days / bdays_target * len(curve)) - 1))
        completion = max(0.02, curve[pos])
        f_mtd = mtd_ex / completion
        w_d = min(0.85, k_days / bdays_target)
    f_month = (w_d * f_mtd + (1 - w_d) * f_blend) if f_mtd else f_blend

    rest = []
    l12sum = sum(ex[x] for x in yms[-12:])
    for m in range(tm + 1, 13):
        ymf = ty * 100 + m
        A = ex.get(back12(ymf), 0) * trend12
        Fc = (l12sum / 12) * s[m] * 12
        rest.append({"ym": f"{ty}-{m:02d}", "base": round(0.5 * A + 0.5 * Fc)})

    ytd_ex = sum(ex[ym] for ym in yms if ym // 100 == ty) + mtd_ex
    year_base = sum(ex[ym] for ym in yms if ym // 100 == ty) + f_month + sum(r["base"] for r in rest)

    m3 = yms[-3:]
    l12 = yms[-12:]
    tot3 = sum(sum(exb[ym].values()) for ym in m3)
    tot12 = sum(sum(exb[ym].values()) for ym in l12)
    brands_all = {b for ym in l12 for b in exb[ym]}
    brands = []
    fut_market = f_month - mtd_ex + sum(r["base"] for r in rest)
    for b in brands_all:
        v3 = sum(exb[ym].get(b, 0) for ym in m3)
        v12 = sum(exb[ym].get(b, 0) for ym in l12)
        if v12 < 300:
            continue
        sh3, sh12 = v3 / tot3, v12 / tot12
        mom = max(0.8, min(1.5, (sh3 / sh12) if sh12 > 0 else 1))
        share = (0.6 * sh3 + 0.4 * sh12) * mom
        ytd_b = sum(exb[ym].get(b, 0) for ym in yms if ym // 100 == ty) + mtd_brands.get(b, 0)
        brands.append({"marca": b, "ytd_exrac": round(ytd_b), "share_hat": share})
    ssum = sum(x["share_hat"] for x in brands)
    for x in brands:
        x["share_hat"] = round(x["share_hat"] / ssum, 5)
        x["year_base_exrac"] = round(x["ytd_exrac"] + x["share_hat"] * fut_market)
    brands.sort(key=lambda x: -x["year_base_exrac"])

    rac_mes_def = round(racm.get(back12(mtd_ym), 0))
    rac_resto_def = round(sum(racm.get((ty - 1) * 100 + m, 0) for m in range(tm + 1, 13)))
    rac_ytd = sum(v for ym, v in racm.items() if ym // 100 == ty) + mtd_rac

    return {
        "status": "ok",
        "generated": date.today().isoformat(),
        "target_month": f"{ty}-{tm:02d}",
        "weights": {"A": W_A, "B": W_B, "E": W_E, "bias": round(bias, 4), "w_d": round(w_d, 3)},
        "bands": {"optimista": BAND_OPT, "conservador": BAND_CONS},
        "context_default": 0.01,
        "market": {
            "mtd_exrac": round(mtd_ex), "mtd_bdays": k_days, "bdays_month": bdays_target,
            "f_month_exrac_base": round(f_month),
            "f_month_components": {"blend": round(f_blend), "mtd_proj": round(f_mtd) if f_mtd else None},
            "months_rest": rest,
            "ytd_exrac": round(ytd_ex),
            "year_base_exrac": round(year_base),
        },
        "rac": {"mes_default": rac_mes_def, "resto_default": rac_resto_def, "ytd": round(rac_ytd)},
        "brands": brands,
    }

def build_meta_json(monthly_records, mtd_yr, mtd_mo, prov_data, scope_info=None):
    months = sorted({(r["y"],r["m"]) for r in monthly_records})
    total  = sum(r["n"] for r in monthly_records)
    return {
        "updated":                        date.today().isoformat(),
        "first_month":                    f"{months[0][0]}-{months[0][1]:02d}" if months else None,
        "last_completed_month":           f"{months[-1][0]}-{months[-1][1]:02d}" if months else None,
        "current_mtd":                    {"year":mtd_yr,"month":mtd_mo,
                                           "label":f"{MONTHS_ES[mtd_mo]} {mtd_yr}"} if mtd_yr else None,
        "completed_months":               len(months),
        "total_registrations_historical": total,
        "has_provinces":                  len(prov_data) > 0,
        "scope":                          scope_info or {"mode": "dgt"},
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "public" / "data"))
    parser.add_argument("--base",    default=str(BASE))
    parser.add_argument("--scope", choices=("simmix", "dgt"), default="dgt",
                        help="dgt usa mercado DGT completo tras la ETL; simmix filtra al scope de BBDD solo para auditoria/comparacion.")
    args    = parser.parse_args()
    base    = Path(args.base)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Leyendo CSV...")
    monthly_records              = load_monthly(base)
    mtd_records, mtd_yr, mtd_mo = load_mtd(base)
    daily_data                   = load_daily(base)
    prov_data                    = load_provinces(base)
    prov_records                 = load_prov_records(base)
    dealer_records               = load_dealer_records(base)

    scope_info = {
        "mode": args.scope,
        "source": "DGT microdata processed by the independent ETL; Simmix is audit/drift only.",
    }
    if args.scope == "simmix":
        scope_fallback = out_dir / "simmix_scope_brands.json"
        scopes, scope_diag = load_simmix_scope(base, scope_fallback)
        save_simmix_scope(scope_fallback, scopes, scope_diag)
        monthly_records, monthly_scope_stats = apply_simmix_scope(monthly_records, scopes)
        mtd_records, mtd_scope_stats = apply_simmix_scope(mtd_records, scopes)
        prov_data, prov_scope_stats = apply_simmix_scope_provinces(prov_data, scopes)

        scope_info = {
            "mode": "simmix",
            "source": "DGT microdata filtered with Simmix-derived scope; DGT for 2026 and MTD",
            "reference_years": sorted(scopes),
            "diagnostics": {str(k): v for k, v in sorted(scope_diag.items())},
            "monthly_stats": monthly_scope_stats,
            "mtd_stats": mtd_scope_stats,
            "province_stats": prov_scope_stats,
        }
        if scopes:
            print("  Scope Simmix:", ", ".join(
                f"{y}: {len(scopes[y])} marcas" + (f" (truncada {scope_diag[y]['truncated_brand']})" if scope_diag[y]["truncated_brand"] else "")
                for y in sorted(scopes)
            ))
        else:
            print("  Scope Simmix: sin BBDD de referencia; usando DGT completo")

    # ── Alineación a targets Simmix ──────────────────────────────────────────
    # SIMMIX_ALIGN=1: modo legado, reescala 2026 al export.
    # SIMMIX_ALIGN=0 (default): modo independiente — el dashboard publica la ETL propia y
    # el export Simmix se usa SOLO para el informe de drift (auditoría).
    # Criterio para pasar a 0: drift por marca/canal < 2% (ver docs/AUDITORIA).
    ranking_obj      = build_province_brand_ranking(prov_data, monthly_records, mtd_records)
    daily_brands_obj = build_daily_brand_trend(base)
    forecast_obj     = build_forecast(monthly_records, mtd_records, daily_brands_obj)
    if forecast_obj.get("status") == "ok":
        log_dir = REPO_ROOT / "data" / "forecast_log"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / ("forecast_" + date.today().strftime("%Y%m%d") + ".json")).write_text(
            json.dumps(forecast_obj, ensure_ascii=False), encoding="utf-8")

    align_enabled = os.environ.get("SIMMIX_ALIGN", "0") != "0"
    target_payload = load_simmix_2026_targets(base, out_dir / "simmix_2026_targets.json")

    drift = compute_simmix_drift(monthly_records, mtd_records, target_payload)
    (out_dir / "simmix_drift.json").write_text(
        json.dumps(drift, ensure_ascii=False, indent=2), encoding="utf-8")
    if drift.get("status") == "computed":
        print(f"  Drift ETL vs Simmix: total {drift['total_delta']:+,} "
              f"({drift['total_delta_pct']:+.2f}%), "
              f"{drift['groups_within_2pct']}/{drift['groups_evaluated']} grupos ±2%")

    if not align_enabled:
        target_stats = {"status": "skipped", "reason": "SIMMIX_ALIGN=0 (modo independiente)"}
    else:
        monthly_records, mtd_records, target_stats = apply_simmix_2026_targets(
            monthly_records, mtd_records, mtd_yr, mtd_mo, target_payload
        )
    if target_stats.get("status") == "applied":
        scope_info = {
            **scope_info,
            "alignment": "simmix_2026_product_export",
            "alignment_stats": target_stats,
        }
        print(
            "  Alineacion Simmix 2026: "
            f"{target_stats['groups']} grupos, residual sintetico {target_stats['synthetic_residual']:,}, "
            f"drop scope {target_stats['dropped_records']:,}"
        )
    elif target_stats:
        print(f"  Alineacion Simmix 2026: omitida ({target_stats.get('reason')})")

    months_done = len({(r["y"],r["m"]) for r in monthly_records})
    mtd_str = f"{mtd_yr}-{mtd_mo:02d}" if mtd_yr else "-"
    print(f"  Meses completos: {months_done}  MTD: {mtd_str}")
    print(f"  Registros mensuales: {len(monthly_records):,}  Prov combos: {len(prov_data):,}")

    cy = mtd_yr or date.today().year
    cm = mtd_mo or date.today().month

    print("Generando JSONs...")
    records_obj = build_records_json(monthly_records, mtd_records, mtd_yr, mtd_mo, scope_info)
    records_prov_obj = build_records_prov_json(prov_records, mtd_yr, mtd_mo, scope_info)
    records_dealer_obj = build_records_dealer_json(
        dealer_records, mtd_yr, mtd_mo, scope_info
    )
    provinces_obj = build_provinces_json(prov_data)

    for fname, obj in [
        ("records.json",   records_obj),
        ("records_prov.json", records_prov_obj),
        ("records_dealer.json", records_dealer_obj),
        ("daily_mtd.json", build_daily_mtd_json(daily_data, cy, cm)),
        ("provinces.json", provinces_obj),
        ("province_brands.json", ranking_obj),
        ("daily_brands.json", daily_brands_obj),
        ("pending_classification.json", build_pending_classification(monthly_records, mtd_records)),
        ("forecast.json", forecast_obj),
    ]:
        p = out_dir / fname
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
        n_items = len(obj.get("rows", obj.get("days", obj.get("provinces", []))))
        print(f"  {fname}: {p.stat().st_size/1024:.0f} KB  ({n_items} rows/items)")

    meta = build_meta_json(monthly_records, mtd_yr, mtd_mo, prov_data, scope_info)
    meta["has_dealers"] = bool(dealer_records)
    meta["dealer_source_policy"] = "official_or_internal"
    meta["dealer_months"] = len({(row["y"], row["m"]) for row in dealer_records})
    p    = out_dir / "meta.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  meta.json")
    print(f"OK - {meta['total_registrations_historical']:,} matriculas en {meta['completed_months']} meses")

if __name__ == "__main__":
    main()
