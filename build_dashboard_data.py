"""
build_dashboard_data.py — Genera los JSON estáticos para el dashboard Vercel.
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

def load_monthly(base):
    data = defaultdict(int)
    for f in sorted(glob.glob(str(base/"dgt_canal_[0-9][0-9][0-9][0-9][0-9][0-9].csv"))):
        m = re.match(r"dgt_canal_(\d{4})(\d{2})$", Path(f).stem)
        if not m: continue
        yr,mo = int(m.group(1)),int(m.group(2))
        for row in _read_csv(f):
            try:
                fuel = row.get("fuel_type","ICE") or "ICE"
                data[(yr,mo,row["marca"],row["canal"],fuel)] += int(row["count"])
            except (ValueError,KeyError): pass
    return data

def load_daily(base):
    data = defaultdict(int)
    for f in sorted(glob.glob(str(base/"dgt_canal_daily_[0-9]*.csv"))):
        m = re.match(r"dgt_canal_daily_(\d{4})(\d{2})(\d{2})$", Path(f).stem)
        if not m: continue
        yr,mo,dy = int(m.group(1)),int(m.group(2)),int(m.group(3))
        for row in _read_csv(f):
            try:
                fuel = row.get("fuel_type","ICE") or "ICE"
                data[(yr,mo,dy,row["marca"],row["canal"],fuel)] += int(row["count"])
            except (ValueError,KeyError): pass
    return data

def load_mtd(base):
    data = defaultdict(int)
    files = sorted(glob.glob(str(base/"dgt_canal_*_mtd.csv")))
    if not files: return data
    m = re.match(r"dgt_canal_(\d{4})(\d{2})_mtd$", Path(files[-1]).stem)
    if not m: return data
    yr,mo = int(m.group(1)),int(m.group(2))
    for row in _read_csv(files[-1]):
        try:
            fuel = row.get("fuel_type","ICE") or "ICE"
            data[(yr,mo,row["marca"],row["canal"],fuel)] += int(row["count"])
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
                data[(yr,mo,row["cod_prov"],row["provincia"],row["canal"],fuel)] += int(row["count"])
            except (ValueError,KeyError): pass
    return data

def _zero():
    return {c:0 for c in CANALES+FUELS}

def build_monthly_json(monthly_data, mtd_data):
    completed = {(y,mo) for (y,mo,_,_,_) in monthly_data}
    mtd_mos   = {(y,mo) for (y,mo,_,_,_) in mtd_data}
    combined  = dict(monthly_data)
    if any(m not in completed for m in mtd_mos):
        for k,v in mtd_data.items():
            combined[k] = combined.get(k,0)+v

    market       = defaultdict(_zero)
    brand_totals = defaultdict(_zero)
    brand_bm     = defaultdict(lambda: defaultdict(_zero))

    for (yr,mo,brand,canal,fuel),cnt in combined.items():
        if canal not in CANALES: continue
        fuel = fuel if fuel in FUELS else "ICE"
        market[(yr,mo)][canal] += cnt
        market[(yr,mo)][fuel]  += cnt
        brand_totals[brand][canal] += cnt
        brand_totals[brand][fuel]  += cnt
        brand_bm[brand][(yr,mo)][canal] += cnt
        brand_bm[brand][(yr,mo)][fuel]  += cnt

    months_out = []
    for (y,mo) in sorted(market):
        d = market[(y,mo)]
        months_out.append({"y":y,"m":mo,"label":f"{MONTHS_ES[mo]} {y}",
            "is_mtd":(y,mo) in mtd_mos and (y,mo) not in completed,
            "Private":d["Private"],"Corporate":d["Corporate"],"RAC":d["RAC"],
            "total":d["Private"]+d["Corporate"]+d["RAC"],
            "ICE":d["ICE"],"BEV":d["BEV"],"PHEV":d["PHEV"]})

    brands_out = []
    for brand,t in sorted(brand_totals.items(), key=lambda x:-(x[1]["Private"]+x[1]["Corporate"]+x[1]["RAC"]))[:30]:
        bm = {}
        for (y,mo),cv in brand_bm[brand].items():
            bm[f"{y}-{mo:02d}"] = {"Private":cv["Private"],"Corporate":cv["Corporate"],"RAC":cv["RAC"],
                "total":cv["Private"]+cv["Corporate"]+cv["RAC"],
                "ICE":cv["ICE"],"BEV":cv["BEV"],"PHEV":cv["PHEV"]}
        brands_out.append({"brand":brand,"Private":t["Private"],"Corporate":t["Corporate"],"RAC":t["RAC"],
            "total":t["Private"]+t["Corporate"]+t["RAC"],
            "ICE":t["ICE"],"BEV":t["BEV"],"PHEV":t["PHEV"],"by_month":bm})

    return {"months":months_out,"brands":brands_out}

def build_daily_mtd_json(daily_data, cy, cm):
    dm = defaultdict(_zero)
    db = defaultdict(lambda: defaultdict(_zero))
    for (y,mo,day,brand,canal,fuel),cnt in daily_data.items():
        if y!=cy or mo!=cm or canal not in CANALES: continue
        fuel = fuel if fuel in FUELS else "ICE"
        dm[day][canal]+=cnt; dm[day][fuel]+=cnt
        db[brand][day][canal]+=cnt; db[brand][day][fuel]+=cnt

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

    brand_sums = {b:sum(sum(cv[c] for c in CANALES) for cv in dv.values()) for b,dv in db.items()}
    top10 = sorted(brand_sums, key=lambda x:-brand_sums[x])[:10]
    brands_out = []
    for b in top10:
        bt = _zero()
        for day in days_sorted:
            for c in CANALES+FUELS: bt[c]+=db[b][day][c]
        brands_out.append({"brand":b,"total":bt["Private"]+bt["Corporate"]+bt["RAC"],
            "Private":bt["Private"],"Corporate":bt["Corporate"],"RAC":bt["RAC"],
            "ICE":bt["ICE"],"BEV":bt["BEV"],"PHEV":bt["PHEV"]})

    return {"year":cy,"month":cm,"month_label":MONTHS_ES[cm],"days":days_out,"top_brands":brands_out}

def build_provinces_json(prov_data):
    if not prov_data:
        return {"provinces":[],"by_month":{}}
    pt = defaultdict(lambda:{"name":"",**_zero()})
    pbm = defaultdict(lambda:defaultdict(_zero))
    for (yr,mo,cod,nombre,canal,fuel),cnt in prov_data.items():
        if canal not in CANALES: continue
        fuel = fuel if fuel in FUELS else "ICE"
        pt[cod]["name"]=nombre
        pt[cod][canal]+=cnt; pt[cod][fuel]+=cnt
        pbm[cod][f"{yr}-{mo:02d}"][canal]+=cnt; pbm[cod][f"{yr}-{mo:02d}"][fuel]+=cnt

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

def build_meta_json(monthly_data, daily_data, mtd_data, prov_data):
    all_m = sorted({(y,mo) for (y,mo,_,_,_) in monthly_data})
    all_d = sorted({(y,mo,d) for (y,mo,d,_,_,_) in daily_data})
    mtd_m = sorted({(y,mo) for (y,mo,_,_,_) in mtd_data})
    current = None
    if mtd_m:
        cy,cm = mtd_m[-1]
        current = {"year":cy,"month":cm,"label":f"{MONTHS_ES[cm]} {cy}"}
    return {
        "updated": date.today().isoformat(),
        "first_month": f"{all_m[0][0]}-{all_m[0][1]:02d}" if all_m else None,
        "last_completed_month": f"{all_m[-1][0]}-{all_m[-1][1]:02d}" if all_m else None,
        "last_daily": (f"{all_d[-1][0]}-{all_d[-1][1]:02d}-{all_d[-1][2]:02d}" if all_d else None),
        "current_mtd": current,
        "completed_months": len(all_m),
        "total_registrations_historical": sum(monthly_data.values()),
        "mtd_registrations": sum(mtd_data.values()),
        "has_provinces": len(prov_data)>0,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="public/data")
    parser.add_argument("--base",    default=str(BASE))
    args = parser.parse_args()
    base    = Path(args.base)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Leyendo CSV...")
    monthly_data = load_monthly(base)
    daily_data   = load_daily(base)
    mtd_data     = load_mtd(base)
    prov_data    = load_provinces(base)
    mtd_m = sorted({(y,mo) for (y,mo,_,_,_) in mtd_data})
    print(f"  Meses: {len({(y,mo) for (y,mo,_,_,_) in monthly_data})}  MTD: {mtd_m[-1] if mtd_m else '-'}  Prov combos: {len(prov_data)}")

    if mtd_m:
        cy,cm = mtd_m[-1]
    elif daily_data:
        last = max((y,mo,d) for (y,mo,d,_,_,_) in daily_data)
        cy,cm = last[0],last[1]
    else:
        t = date.today(); cy,cm = t.year,t.month

    print("Generando JSONs...")
    for fname, obj in [
        ("monthly.json",   build_monthly_json(monthly_data, mtd_data)),
        ("daily_mtd.json", build_daily_mtd_json(daily_data, cy, cm)),
        ("provinces.json", build_provinces_json(prov_data)),
    ]:
        p = out_dir/fname
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",",":")))
        print(f"  {p}  ({p.stat().st_size/1024:.1f} KB)")

    meta = build_meta_json(monthly_data, daily_data, mtd_data, prov_data)
    p = out_dir/"meta.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"  {p}")
    print(f"\nOK — {meta['total_registrations_historical']:,} matriculas")

if __name__ == "__main__":
    main()
