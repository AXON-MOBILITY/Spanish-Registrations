"""
build_dashboard_data.py — Genera JSON estáticos para el dashboard Vercel.

Salida principal:
  public/data/records.json   — registros planos con todas las dimensiones
  public/data/meta.json      — listas de valores únicos, meses disponibles
  public/data/provinces.json — datos por provincia
  public/data/daily_mtd.json — acumulado MTD diario del mes actual

Columnas records.json (índices COL en index.html):
  0:y  1:m  2:marca  3:modelo  4:canal  5:fuel  6:fuel_det  7:seg  8:sub  9:hp  10:body  11:n
"""
import argparse, csv, glob, json, re, unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
MONTHS_ES = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
             7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}
CANALES = ["Private","Corporate","RAC"]
FUELS   = ["ICE","BEV","PHEV"]
MONTH_NAME_TO_NUM = {v.upper(): k for k, v in {
    1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
    7:"July",8:"August",9:"September",10:"October",11:"November",12:"December",
}.items()}

PROV_CODE_BY_SIMMIX_NAME = {
    "A CORUNA": "15", "ALAVA": "01", "ALBACETE": "02", "ALICANTE": "03",
    "ALMERIA": "04", "ASTURIAS": "33", "AVILA": "05", "BADAJOZ": "06",
    "BALEARES": "07", "ISLAS BALEARES": "07", "BARCELONA": "08",
    "BURGOS": "09", "CACERES": "10", "CADIZ": "11", "CANTABRIA": "39",
    "CASTELLON": "12", "CEUTA": "51", "CIUDAD REAL": "13", "CORDOBA": "14",
    "CUENCA": "16", "GIRONA": "17", "GRANADA": "18", "GUADALAJARA": "19",
    "GIPUZKOA": "20", "GUIPUZCOA": "20", "HUELVA": "21", "HUESCA": "22",
    "JAEN": "23", "LA RIOJA": "26", "LAS PALMAS": "35", "LEON": "24",
    "LLEIDA": "25", "LUGO": "27", "MADRID": "28", "MALAGA": "29",
    "MELILLA": "52", "MURCIA": "30", "NAVARRA": "31", "OURENSE": "32",
    "PALENCIA": "34", "PONTEVEDRA": "36", "SALAMANCA": "37",
    "SANTA CRUZ DE TENERIFE": "38", "S.C. TENERIFE": "38", "SEGOVIA": "40",
    "SEVILLA": "41", "SORIA": "42", "TARRAGONA": "43", "TERUEL": "44",
    "TOLEDO": "45", "VALENCIA": "46", "VALLADOLID": "47",
    "BIZKAIA": "48", "VIZCAYA": "48", "ZAMORA": "49", "ZARAGOZA": "50",
}

# ── Normalización de marcas DGT → nombres canónicos Simmix ───────────────────
_BRAND_NORM = {
    'ABARTH': 'Abarth', 'AIWAYS': 'Aiways', 'ALFA ROMEO': 'Alfa Romeo',
    'ALPINE': 'Alpine', 'ALPINA': 'Alpina', 'ASTON MARTIN': 'Aston Martin',
    'AUDI': 'Audi', 'BENTLEY': 'Bentley', 'BMW': 'BMW',
    'CADILLAC': 'Cadillac', 'CENNTRO': 'Cenntro', 'CITROEN': 'Citroen',
    'CUPRA': 'Cupra', 'DACIA': 'Dacia', 'DR': 'DR',
    'DS': 'DS', 'ESAGONO ENERGIA': 'Esagono Energia', 'ETESIA': 'Etesia',
    'EVUM MOTORS': 'Evum Motors', 'FERRARI': 'Ferrari', 'FIAT': 'Fiat',
    'FORD': 'Ford', 'GOUPIL': 'Goupil', 'HONDA': 'Honda',
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
    'ROLLS-ROYCE': 'Rolls-Royce', 'SEAT': 'SEAT', 'SERES': 'Seres',
    'SHINERAY': 'Shineray', 'SKODA': 'Skoda', 'SKYWELL': 'Skywell',
    'SMART': 'Smart', 'SSANGYONG': 'Ssangyong', 'SUBARU': 'Subaru',
    'SUZUKI': 'Suzuki', 'TESLA': 'Tesla', 'TOYOTA': 'Toyota',
    'VOLKSWAGEN': 'Volkswagen', 'VOLVO': 'Volvo', 'VOYAH': 'Voyah',
    'YUDO': 'Yudo',
    # Abreviaciones que .title() rompería
    'BYD': 'BYD', 'DFSK': 'DFSK', 'EVO': 'EVO', 'MAN': 'MAN',
    # Alias adicionales
    'DS AUTOMOBILES': 'DS',
    'MERCEDES BENZ AG': 'Mercedes', 'MERCEDES-BENZ MINIBUS': 'Mercedes',
    'MERCEDES IRIZAR': 'Mercedes',
}

def _normalize_brand(raw):
    s = (raw or '').strip()
    canon = _BRAND_NORM.get(s.upper())
    return canon if canon else (s.title() if s else s)

def _strip_accents(raw):
    return ''.join(
        c for c in unicodedata.normalize('NFD', raw or '')
        if unicodedata.category(c) != 'Mn'
    )

def _normalize_prov_key(raw):
    return re.sub(r"\s+", " ", _strip_accents(raw).strip().upper())

def _fuel_type_from_simmix(raw_fuel_type, raw_fuel):
    fuel_type = (raw_fuel_type or "").strip().upper()
    if fuel_type in FUELS:
        return fuel_type
    fuel = _strip_accents(raw_fuel).upper()
    if "ENCHUF" in fuel or "PHEV" in fuel:
        return "PHEV"
    if "ELECTR" in fuel or fuel_type == "BEV":
        return "BEV"
    return "ICE"

def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            yield {k:(v.strip() if v is not None else "") for k,v in row.items()}

def load_simmix_scope(base):
    """Infer the valid Simmix export scope by year from BBDD_YYYY_PRODUCTO.csv.

    Some available Simmix exports are cut mid-brand (for example 2024 ends inside
    Mercedes and 2025 inside BMW). We treat that final incomplete brand as
    truncated and exclude it from the scope rather than mixing partial data.
    """
    scopes = {}
    diagnostics = {}
    for path in sorted(base.glob("BBDD_*_PRODUCTO.csv")):
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
    return scopes, diagnostics

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

def load_simmix_records(base):
    """Load historical product records directly from Simmix exports.

    The BBDD files already contain the provider's product/channel/fuel criteria.
    For cut exports, the final incomplete brand is excluded consistently with
    load_simmix_scope.
    """
    record_counts = defaultdict(int)
    prov_data = defaultdict(int)
    diagnostics = {}

    for path in sorted(base.glob("BBDD_*_PRODUCTO.csv")):
        m = re.match(r"BBDD_(\d{4})_PRODUCTO$", path.stem)
        if not m:
            continue
        yr = int(m.group(1))
        cols = {
            "brand": f"Brand_{yr}",
            "model": f"Model_{yr}",
            "fuel": f"Fuel_{yr}",
            "fuel_type": f"Fuel_Type_{yr}",
            "channel": f"Channel_{yr}",
            "year": f"Year_{yr}",
            "month": f"Month_{yr}",
            "segment": f"Segment_{yr}",
            "sub": f"SubSegmento_{yr}",
            "hp": f"High Performance_{yr}",
            "body": f"Body Type_{yr}",
            "regs": f"Registrations_{yr}",
            "prov": f"Provincia_{yr}",
        }
        tmp = []
        malformed = 0
        truncated_brand = None

        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                raw_brand = (row.get(cols["brand"]) or "").strip()
                if not raw_brand or "," in raw_brand or row.get(None):
                    malformed += 1
                    continue
                brand = _normalize_brand(raw_brand)
                raw_regs = (row.get(cols["regs"]) or "").strip()
                if not raw_regs:
                    truncated_brand = brand.upper()
                    continue
                try:
                    n = int(float(raw_regs.replace(",", ".")))
                except ValueError:
                    malformed += 1
                    continue
                raw_month = (row.get(cols["month"]) or "").strip()
                mo = MONTH_NAME_TO_NUM.get(raw_month.upper())
                if not mo:
                    malformed += 1
                    continue
                fuel_det = (row.get(cols["fuel"]) or "").strip()
                fuel_type = _fuel_type_from_simmix(row.get(cols["fuel_type"]), fuel_det)
                channel = (row.get(cols["channel"]) or "").strip()
                if channel not in CANALES:
                    malformed += 1
                    continue
                tmp.append({
                    "y": yr,
                    "m": mo,
                    "marca": brand,
                    "modelo": (row.get(cols["model"]) or "").strip(),
                    "canal": channel,
                    "fuel": fuel_type,
                    "fuel_det": fuel_det,
                    "seg": (row.get(cols["segment"]) or "").strip(),
                    "sub": (row.get(cols["sub"]) or "").strip(),
                    "hp": (row.get(cols["hp"]) or "").strip(),
                    "body": (row.get(cols["body"]) or "").strip(),
                    "n": n,
                    "_prov": (row.get(cols["prov"]) or "").strip(),
                })

        valid_rows = 0
        valid_total = 0
        for r in tmp:
            if truncated_brand and r["marca"].upper() == truncated_brand:
                continue
            prov = r.pop("_prov")
            valid_rows += 1
            valid_total += r["n"]
            rec_key = (
                r["y"], r["m"], r["marca"], r["modelo"], r["canal"], r["fuel"],
                r["fuel_det"], r["seg"], r["sub"], r["hp"], r["body"],
            )
            record_counts[rec_key] += r["n"]
            prov_key = _normalize_prov_key(prov)
            cod = PROV_CODE_BY_SIMMIX_NAME.get(prov_key)
            if cod:
                prov_data[(r["y"], r["m"], r["marca"], cod, prov.title(), r["canal"], r["fuel"])] += r["n"]

        diagnostics[yr] = {
            "file": path.name,
            "rows": len(tmp),
            "loaded_rows": valid_rows,
            "truncated_brand": truncated_brand,
            "malformed_rows": malformed,
            "total": valid_total,
            "province_total": sum(v for k, v in prov_data.items() if k[0] == yr),
        }

    records = [
        {
            "y": y, "m": mo, "marca": marca, "modelo": modelo, "canal": canal,
            "fuel": fuel, "fuel_det": fuel_det, "seg": seg, "sub": sub,
            "hp": hp, "body": body, "n": n,
        }
        for (y, mo, marca, modelo, canal, fuel, fuel_det, seg, sub, hp, body), n
        in sorted(record_counts.items())
    ]
    return records, prov_data, diagnostics

def load_existing_simmix_records(out_dir):
    path = Path(out_dir) / "records.json"
    if not path.exists():
        return [], set(), {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], set(), {}
    scope = obj.get("scope") or {}
    years = {int(y) for y in scope.get("reference_years", []) if str(y).isdigit()}
    if scope.get("mode") != "simmix" or not years:
        return [], set(), {}

    enums = obj.get("enums", {})
    cols = obj.get("cols", [])
    rows = obj.get("rows", [])
    try:
        col = {k: cols.index(k) for k in cols}
    except ValueError:
        return [], set(), {}

    def enum_value(name, idx):
        vals = enums.get(name, [])
        return vals[idx] if isinstance(idx, int) and 0 <= idx < len(vals) else ""

    records = []
    for r in rows:
        y = r[col["y"]]
        if y not in years:
            continue
        records.append({
            "y": y,
            "m": r[col["m"]],
            "marca": enum_value("marca", r[col["marca"]]),
            "modelo": enum_value("modelo", r[col["modelo"]]),
            "canal": enum_value("canal", r[col["canal"]]),
            "fuel": enum_value("fuel", r[col["fuel"]]),
            "fuel_det": enum_value("fuel_det", r[col["fuel_det"]]),
            "seg": enum_value("seg", r[col["seg"]]),
            "sub": enum_value("sub", r[col["sub"]]),
            "hp": enum_value("hp", r[col["hp"]]),
            "body": enum_value("body", r[col["body"]]),
            "n": r[col["n"]],
        })
    return records, years, scope

# ── Carga datos ──────────────────────────────────────────────────────────────

def load_monthly(base):
    records = []
    for f in sorted(glob.glob(str(base/"dgt_canal_[0-9][0-9][0-9][0-9][0-9][0-9].csv"))):
        m = re.match(r"dgt_canal_(\d{4})(\d{2})$", Path(f).stem)
        if not m: continue
        yr, mo = int(m.group(1)), int(m.group(2))
        for row in _read_csv(f):
            try:
                n = int(row.get("count", 0) or 0)
                if n <= 0: continue
                records.append({
                    "y":        yr,
                    "m":        mo,
                    "marca":    _normalize_brand(row.get("marca", "")),
                    "modelo":   row.get("modelo", "").strip().upper(),
                    "canal":    row.get("canal", ""),
                    "fuel":     row.get("fuel_type", "ICE") or "ICE",
                    "fuel_det": row.get("fuel", "").strip(),
                    "seg":      row.get("segmento", ""),
                    "sub":      row.get("subseg", ""),
                    "hp":       row.get("hp", ""),
                    "body":     row.get("body_type", ""),
                    "n":        n,
                })
            except (ValueError, KeyError):
                pass
    return records

def load_mtd(base):
    records = []
    files = sorted(glob.glob(str(base/"dgt_canal_*_mtd.csv")))
    if not files: return records, None, None
    m = re.match(r"dgt_canal_(\d{4})(\d{2})_mtd$", Path(files[-1]).stem)
    if not m: return records, None, None
    yr, mo = int(m.group(1)), int(m.group(2))
    for row in _read_csv(files[-1]):
        try:
            n = int(row.get("count", 0) or 0)
            if n <= 0: continue
            records.append({
                "y":        yr,
                "m":        mo,
                "marca":    _normalize_brand(row.get("marca", "")),
                "modelo":   row.get("modelo", "").strip().upper(),
                "canal":    row.get("canal", ""),
                "fuel":     row.get("fuel_type", "ICE") or "ICE",
                "fuel_det": row.get("fuel", "").strip(),
                "seg":      row.get("segmento", ""),
                "sub":      row.get("subseg", ""),
                "hp":       row.get("hp", ""),
                "body":     row.get("body_type", ""),
                "n":        n,
            })
        except (ValueError, KeyError):
            pass
    return records, yr, mo

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
    for f in sorted(glob.glob(str(base/"dgt_prov_[0-9][0-9][0-9][0-9][0-9][0-9].csv"))):
        m = re.match(r"dgt_prov_(\d{4})(\d{2})$", Path(f).stem)
        if not m: continue
        yr, mo = int(m.group(1)), int(m.group(2))
        for row in _read_csv(f):
            try:
                fuel = row.get("fuel_type", "ICE") or "ICE"
                marca = _normalize_brand(row.get("marca", ""))
                data[(yr, mo, marca, row["cod_prov"], row["provincia"], row["canal"], fuel)] += int(row.get("count", 0) or 0)
            except (ValueError, KeyError):
                pass
    return data

def apply_simmix_scope_provinces(prov_data, scopes):
    if not scopes:
        return prov_data, {}
    kept = defaultdict(int)
    stats = defaultdict(lambda: {"kept": 0, "excluded": 0, "scope_brands": 0})
    for (yr, mo, marca, cod, nombre, canal, fuel), cnt in prov_data.items():
        scope = scopes.get(yr)
        if scope is None:
            kept[(yr, mo, marca, cod, nombre, canal, fuel)] += cnt
            stats[yr]["kept"] += cnt
            continue
        stats[yr]["scope_brands"] = len(scope)
        if marca and marca.upper() in scope:
            kept[(yr, mo, marca, cod, nombre, canal, fuel)] += cnt
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

def build_provinces_json(prov_data):
    if not prov_data:
        return {"provinces":[],"by_month":{}}
    pt  = defaultdict(lambda:{"name":"",**_zero()})
    pbm = defaultdict(lambda:defaultdict(_zero))
    for key,cnt in prov_data.items():
        if len(key) == 7:
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

def merge_existing_provinces(out_dir, generated, preserve_years):
    if not preserve_years:
        return generated
    path = Path(out_dir) / "provinces.json"
    if not path.exists():
        return generated
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return generated

    preserve_prefixes = {f"{int(y)}-" for y in preserve_years}
    by_month = {}
    for ym, rows in (generated.get("by_month") or {}).items():
        if not any(ym.startswith(prefix) for prefix in preserve_prefixes):
            by_month[ym] = rows
    for ym, rows in (existing.get("by_month") or {}).items():
        if any(ym.startswith(prefix) for prefix in preserve_prefixes):
            by_month[ym] = rows

    pt = defaultdict(lambda: {"name": "", **_zero()})
    for rows in by_month.values():
        for row in rows:
            cod = row.get("cod", "")
            if not cod:
                continue
            pt[cod]["name"] = row.get("name", "")
            for k in ("Private", "Corporate", "RAC", "ICE", "BEV", "PHEV", "total"):
                pt[cod][k] += int(row.get(k, 0) or 0)
    provs = [
        {"cod": cod, "name": v["name"], **{k: v[k] for k in ("total", "Private", "Corporate", "RAC", "ICE", "BEV", "PHEV")}}
        for cod, v in pt.items()
    ]
    provs.sort(key=lambda x: -x["total"])
    return {"provinces": provs, "by_month": by_month}

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
    parser.add_argument("--out-dir", default="public/data")
    parser.add_argument("--base",    default=str(BASE))
    parser.add_argument("--scope", choices=("simmix", "dgt"), default="simmix",
                        help="simmix filtra años con BBDD_YYYY_PRODUCTO al scope válido de Simmix; dgt usa mercado DGT completo.")
    args    = parser.parse_args()
    base    = Path(args.base)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Leyendo CSV...")
    monthly_records              = load_monthly(base)
    mtd_records, mtd_yr, mtd_mo = load_mtd(base)
    daily_data                   = load_daily(base)
    prov_data                    = load_provinces(base)

    scope_info = {"mode": args.scope}
    preserve_existing_province_years = set()
    if args.scope == "simmix":
        scopes, scope_diag = load_simmix_scope(base)
        if scopes:
            simmix_records, simmix_prov_data, simmix_diag = load_simmix_records(base)
            simmix_years = set(scopes)
            source = "BBDD_PRODUCTO for years with Simmix export; DGT for remaining years and MTD"
        else:
            simmix_records, simmix_years, existing_scope = load_existing_simmix_records(out_dir)
            simmix_prov_data = defaultdict(int)
            simmix_diag = {}
            source = "existing public/data Simmix history fallback; DGT for remaining years and MTD"
            preserve_existing_province_years = simmix_years
            if existing_scope:
                scope_diag = existing_scope.get("diagnostics", {})

        monthly_records = [r for r in monthly_records if r["y"] not in simmix_years]
        monthly_records.extend(simmix_records)

        dgt_prov_future = defaultdict(int)
        for key, cnt in prov_data.items():
            if key[0] not in simmix_years:
                dgt_prov_future[key] += cnt
        dgt_prov_future.update(simmix_prov_data)
        prov_data = dgt_prov_future

        scope_info = {
            "mode": "simmix",
            "source": source,
            "reference_years": sorted(simmix_years),
            "diagnostics": {str(k): v for k, v in sorted(scope_diag.items())},
            "loaded": {str(k): v for k, v in sorted(simmix_diag.items())},
        }
        if scopes:
            print("  Scope Simmix:", ", ".join(
                f"{y}: {len(scopes[y])} marcas" + (f" (truncada {scope_diag[y]['truncated_brand']})" if scope_diag[y]["truncated_brand"] else "")
                for y in sorted(scopes)
            ))
        elif simmix_records:
            print("  Scope Simmix: usando historico ya publicado para", ", ".join(str(y) for y in sorted(simmix_years)))
        else:
            print("  Scope Simmix: sin BBDD ni historico publicado; usando DGT completo")

    months_done = len({(r["y"],r["m"]) for r in monthly_records})
    mtd_str = f"{mtd_yr}-{mtd_mo:02d}" if mtd_yr else "-"
    print(f"  Meses completos: {months_done}  MTD: {mtd_str}")
    print(f"  Registros mensuales: {len(monthly_records):,}  Prov combos: {len(prov_data):,}")

    cy = mtd_yr or date.today().year
    cm = mtd_mo or date.today().month

    print("Generando JSONs...")
    records_obj = build_records_json(monthly_records, mtd_records, mtd_yr, mtd_mo, scope_info)
    provinces_obj = build_provinces_json(prov_data)
    provinces_obj = merge_existing_provinces(out_dir, provinces_obj, preserve_existing_province_years)

    for fname, obj in [
        ("records.json",   records_obj),
        ("daily_mtd.json", build_daily_mtd_json(daily_data, cy, cm)),
        ("provinces.json", provinces_obj),
    ]:
        p = out_dir / fname
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
        n_items = len(obj.get("rows", obj.get("days", obj.get("provinces", []))))
        print(f"  {fname}: {p.stat().st_size/1024:.0f} KB  ({n_items} rows/items)")

    meta = build_meta_json(monthly_records, mtd_yr, mtd_mo, prov_data, scope_info)
    p    = out_dir / "meta.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  meta.json")
    print(f"OK — {meta['total_registrations_historical']:,} matriculas en {meta['completed_months']} meses")

if __name__ == "__main__":
    main()
