"""
build_dashboard_data.py — Genera JSON estáticos para el dashboard Vercel.

Salida principal:
  public/data/records.json   — registros planos con todas las dimensiones
  public/data/meta.json      — listas de valores únicos, meses disponibles
  public/data/provinces.json — datos por provincia
  public/data/daily_mtd.json — acumulado MTD diario del mes actual
"""
import argparse, csv, glob, json, re
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
MONTHS_ES = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
             7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}
CANALES = ["Private","Corporate","RAC"]
FUELS   = ["ICE","BEV","PHEV"]

def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            yield {k:(v.strip() if v is not None else "") for k,v in row.items()}

# ── Carga datos ──────────────────────────────────────────────────────────────

def load_monthly(base):
    """Carga dgt_canal_YYYYMM.csv → lista de dicts con todas las dimensiones."""
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
                    "y": yr, "m": mo,
                    "marca":   row.get("marca","").strip().upper(),
                    "modelo":  row.get("modelo","").strip().upper(),
                    "canal":   row.get("canal",""),
                    "fuel":    row.get("fuel_type","ICE") or "ICE",
                    "seg":     row.get("segmento",""),
                    "sub":     row.get("subseg",""),
                    "hp":      row.get("hp",""),
                    "body":    row.get("body_type",""),
                    "n":       n,
                })
            except (ValueError, KeyError): pass
    return records

def load_mtd(base):
    """Carga el último dgt_canal_*_mtd.csv → lista de dicts."""
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
                "y": yr, "m": mo,
                "marca":  row.get("marca","").strip().upper(),
                "modelo": row.get("modelo","").strip().upper(),
                "canal":  row.get("canal",""),
                "fuel":   row.get("fuel_type","ICE") or "ICE",
                "seg":    row.get("segmento",""),
                "sub":    row.get("subseg",""),
                "hp":     row.get("hp",""),
                "body":   row.get("body_type",""),
                "n":      n,
            })
        except (ValueError, KeyError): pass
    return records, yr, mo

def load_daily(base):
    data = defaultdict(int)
    for f in sorted(glob.glob(str(base/"dgt_canal_daily_[0-9]*.csv"))):
        m = re.match(r"dgt_canal_daily_(\d{4})(\d{2})(\d{2})$", Path(f).stem)
        if not m: continue
        yr,mo,dy = int(m.group(1)),int(m.group(2)),int(m.group(3))
        for row in _read_csv(f):
            try:
                fuel = row.get("fuel_type","ICE") or "ICE"
                canal = row.get("canal","")
                if canal not in CANALES: continue
                data[(yr,mo,dy,canal,fuel)] += int(row.get("count",0) or 0)
            except (ValueError,KeyError): pass
    return data

def load_provinces(base):
    data = defaultdict(int)
    for f in sorted(glob.glob(str(base/"dgt_prov_[0-9][0-9][0-9][0-9][0-9][0-9].csv"))):
        m = re.match(r"dgt_prov_(\d{4})(\d{2})$", Path(f).stem)
        if not m: continue
        yr,mo = int(m.group(1)),int(m.group(2))
        for row in _read_csv(f):
            try:
                fuel = row.get("fuel_type","ICE") or "ICE"
                data[(yr,mo,row["cod_prov"],row["provincia"],row["canal"],fuel)] += int(row.get("count",0) or 0)
            except (ValueError,KeyError): pass
    return data

# ── Construcción JSONs ────────────────────────────────────────────────────────

def build_records_json(monthly_records, mtd_records, mtd_yr, mtd_mo):
    """
    Genera JSON compacto con registros planos + índices para filtrado rápido.
    Formato: {cols:[...], rows:[[...],...]}
    """
    # Combinar monthly + MTD (sin duplicar el mes MTD si ya está completo)
    completed = {(r["y"],r["m"]) for r in monthly_records}
    all_records = list(monthly_records)
    if mtd_yr and (mtd_yr, mtd_mo) not in completed:
        all_records.extend(mtd_records)

    if not all_records:
        return {"cols":[], "rows":[], "meta":{}}

    # Compresión: codificar strings repetidas como índices
    marca_idx  = {}; marcas  = []
    modelo_idx = {}; modelos = []
    seg_idx    = {}; segs    = []
    body_idx   = {}; bodies  = []
    sub_idx    = {}; subs    = []
    hp_idx     = {}; hps     = []
    canal_map  = {"Private":0,"Corporate":1,"RAC":2}
    fuel_map   = {"ICE":0,"BEV":1,"PHEV":2}

    def idx(val, d, lst):
        if val not in d:
            d[val] = len(lst)
            lst.append(val)
        return d[val]

    rows = []
    for r in all_records:
        rows.append([
            r["y"], r["m"],
            idx(r["marca"],  marca_idx,  marcas),
            idx(r["modelo"], modelo_idx, modelos),
            canal_map.get(r["canal"], 0),
            fuel_map.get(r["fuel"], 0),
            idx(r["seg"],  seg_idx,  segs),
            idx(r["sub"],  sub_idx,  subs),
            idx(r["hp"],   hp_idx,   hps),
            idx(r["body"], body_idx, bodies),
            r["n"],
        ])

    # Estadísticas
    total = sum(r[-1] for r in rows)
    months_present = sorted({(r[0],r[1]) for r in rows})

    return {
        "cols": ["y","m","marca","modelo","canal","fuel","seg","sub","hp","body","n"],
        "enums": {
            "canal": ["Private","Corporate","RAC"],
            "fuel":  ["ICE","BEV","PHEV"],
            "marca": marcas,
            "modelo": modelos,
            "seg":    segs,
            "sub":    subs,
            "hp":     hps,
            "body":   bodies,
        },
        "rows": rows,
        "total": total,
        "months": [{"y":y,"m":mo,"label":f"{MONTHS_ES[mo]} {y}"} for y,mo in months_present],
        "mtd": {"y":mtd_yr,"m":mtd_mo} if mtd_yr else None,
    }

def _zero():
    return {c:0 for c in CANALES+FUELS}

def build_daily_mtd_json(daily_data, cy, cm):
    dm = defaultdict(_zero)
    db = defaultdict(lambda: defaultdict(_zero))
    for (y,mo,day,canal,fuel),cnt in daily_data.items():
        if y!=cy or mo!=cm or canal not in CANALES: continue
        fuel2 = fuel if fuel in FUELS else "ICE"
        dm[day][canal]+=cnt; dm[day][fuel2]+=cnt
        # We don't have brand in this aggregation anymore (daily doesn't expand brand by default)

    days_sorted = sorted(dm)
    cumul = _zero()
    days_out = []
    for day in days_sorted:
        d = dm[day]
        for c in CANALES+FUELS: cumul[c]+=d[c]
        days_out.append({"day":day,
            "daily":{"Private":d["Private"],"Corporate":d["Corporate"],"RAC":d["RAC"],
                     "total":d["Private"]+d["Corporate"]+d["RAC"],
                     "ICE":d["ICE"],"BEV":d["BEV"],"PHEV":d["PHEV"]},
            "cumul":{"Private":cumul["Private"],"Corporate":cumul["Corporate"],"RAC":cumul["RAC"],
                     "total":cumul["Private"]+cumul["Corporate"]+cumul["RAC"],
                     "ICE":cumul["ICE"],"BEV":cumul["BEV"],"PHEV":cumul["PHEV"]}})
    return {"year":cy,"month":cm,"month_label":MONTHS_ES[cm],"days":days_out}

def build_provinces_json(prov_data):
    if not prov_data:
        return {"provinces":[],"by_month":{}}
    pt = defaultdict(lambda:{"name":"",**_zero()})
    pbm = defaultdict(lambda:defaultdict(_zero))
    for (yr,mo,cod,nombre,canal,fuel),cnt in prov_data.items():
        if canal not in CANALES: continue
        fuel2 = fuel if fuel in FUELS else "ICE"
        pt[cod]["name"]=nombre
        pt[cod][canal]+=cnt; pt[cod][fuel2]+=cnt
        pbm[cod][f"{yr}-{mo:02d}"][canal]+=cnt; pbm[cod][f"{yr}-{mo:02d}"][fuel2]+=cnt

    provs = []
    for cod,d in sorted(pt.items()):
        bm = {}
        for ym,cv in pbm[cod].items():
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
        for cod,d in pt.items():
            cv = pbm[cod].get(ym,_zero())
            t = cv.get("Private",0)+cv.get("Corporate",0)+cv.get("RAC",0)
            if t>0:
                rows.append({"cod":cod,"name":d["name"],"total":t,
                    "Private":cv.get("Private",0),"Corporate":cv.get("Corporate",0),"RAC":cv.get("RAC",0),
                    "ICE":cv.get("ICE",0),"BEV":cv.get("BEV",0),"PHEV":cv.get("PHEV",0)})
        by_month[ym]=sorted(rows,key=lambda x:-x["total"])
    return {"provinces":provs,"by_month":by_month}

def build_meta_json(monthly_records, mtd_yr, mtd_mo, prov_data):
    months = sorted({(r["y"],r["m"]) for r in monthly_records})
    total = sum(r["n"] for r in monthly_records)
    return {
        "updated": date.today().isoformat(),
        "first_month": f"{months[0][0]}-{months[0][1]:02d}" if months else None,
        "last_completed_month": f"{months[-1][0]}-{months[-1][1]:02d}" if months else None,
        "current_mtd": {"year":mtd_yr,"month":mtd_mo,"label":f"{MONTHS_ES[mtd_mo]} {mtd_yr}"} if mtd_yr else None,
        "completed_months": len(months),
        "total_registrations_historical": total,
        "has_provinces": len(prov_data) > 0,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="public/data")
    parser.add_argument("--base", default=str(BASE))
    args = parser.parse_args()
    base    = Path(args.base)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Leyendo CSV...")
    monthly_records           = load_monthly(base)
    mtd_records, mtd_yr, mtd_mo = load_mtd(base)
    daily_data                = load_daily(base)
    prov_data                 = load_provinces(base)

    months_done = len({(r["y"],r["m"]) for r in monthly_records})
    print(f"  Meses completos: {months_done}  MTD: {mtd_yr}-{mtd_mo:02d} if mtd_yr else '-'")
    print(f"  Registros mensuales: {len(monthly_records):,}  Prov combos: {len(prov_data):,}")

    cy = mtd_yr or date.today().year
    cm = mtd_mo or date.today().month

    print("Generando JSONs...")
    records_obj = build_records_json(monthly_records, mtd_records, mtd_yr, mtd_mo)
    for fname, obj in [
        ("records.json",   records_obj),
        ("daily_mtd.json", build_daily_mtd_json(daily_data, cy, cm)),
        ("provinces.json", build_provinces_json(prov_data)),
    ]:
        p = out_dir / fname
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",",":")))
        print(f"  {fname}: {p.stat().st_size/1024:.0f} KB  ({len(records_obj.get('rows', obj.get('days', obj.get('provinces', []))))} rows/items)")

    meta = build_meta_json(monthly_records, mtd_yr, mtd_mo, prov_data)
    p = out_dir / "meta.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"  meta.json")
    print(f"\nOK — {meta['total_registrations_historical']:,} matriculas en {meta['completed_months']} meses")

if __name__ == "__main__":
    main()
