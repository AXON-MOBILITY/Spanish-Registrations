"""Filter RAIAVL "Venta de vehiculos" from MIN_YEAR onward and enrich each
row with derived fuel_type / body_type. Writes data/processed/mx_registrations.csv.

Years are auto-discovered from whatever yearly CSVs download_inegi.py has
pulled into data/raw/ - no year to edit here when a new year rolls around
or the pipeline is re-run months later.
"""
import csv
import re
from pathlib import Path

from enrich import enrich_row, normalize_model_name

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "venta" / "conjunto_de_datos"
OUT_PATH = ROOT / "data" / "processed" / "mx_registrations.csv"

MIN_YEAR = 2023
FILE_RE = re.compile(r"raiavl_venta_mensual_tr_cifra_(\d{4})\.csv$")


def discover_years() -> list[int]:
    years = []
    for path in RAW_DIR.glob("raiavl_venta_mensual_tr_cifra_*.csv"):
        m = FILE_RE.match(path.name)
        if m and int(m.group(1)) >= MIN_YEAR:
            years.append(int(m.group(1)))
    return sorted(years)


OUT_FIELDS = [
    "anio", "mes", "marca", "modelo", "modelo_raw", "tipo", "segmento",
    "origen", "unidades", "estatus",
    "fuel_type", "body_type", "confidence", "note",
]


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows_out = []
    years = discover_years()
    print(f"Years found in data/raw: {years}")

    for year in years:
        src = RAW_DIR / f"raiavl_venta_mensual_tr_cifra_{year}.csv"
        with open(src, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                marca = row["MARCA"].strip()
                modelo_raw = row["MODELO"].strip()
                tipo = row["TIPO"].strip()
                segmento = row["SEGMENTO"].strip()
                # enrich_row keys off the raw MODELO text (keyword rules
                # and the overrides table both match against it); the
                # normalized name is purely a display-name cleanup applied
                # after, so it can't affect fuel_type/body_type detection.
                enrichment = enrich_row(marca, modelo_raw, tipo, segmento)
                modelo = normalize_model_name(marca, modelo_raw)

                rows_out.append({
                    "anio": row["ANIO"],
                    "mes": row["ID_MES"],
                    "marca": marca,
                    "modelo": modelo,
                    "modelo_raw": modelo_raw,
                    "tipo": tipo,
                    "segmento": segmento,
                    "origen": row["ORIGEN"].strip(),
                    "unidades": row["UNI_VEH"],
                    "estatus": row["ESTATUS"].strip(),
                    **enrichment,
                })

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Wrote {len(rows_out)} rows to {OUT_PATH}")

    low_conf = sum(1 for r in rows_out if r["confidence"] == "baja")
    print(f"  confidence=baja: {low_conf} rows ({low_conf / len(rows_out):.1%})")


if __name__ == "__main__":
    main()
