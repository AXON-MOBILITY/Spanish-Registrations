"""Filter RAIAVL "Exportacion de vehiculos" from MIN_YEAR onward and
enrich each row with a derived body_type (same method as process_data.py).
Writes data/processed/mx_exports.csv.

Years are auto-discovered from data/raw/, same as process_data.py.

Export brand names differ cosmetically from the sales dataset ("BMW
Group", "Mercedes Benz_Prod_Expo") - normalized here so brand logos and
the body_type override table (keyed by the sales dataset's names) line
up between the two datasets.
"""
import csv
import re
from pathlib import Path

from enrich import classify_body_type, normalize_model_name, _OVERRIDES

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "exportacion" / "conjunto_de_datos"
CATALOGOS_DIR = ROOT / "data" / "raw" / "exportacion" / "catalogos"
OUT_PATH = ROOT / "data" / "processed" / "mx_exports.csv"

MIN_YEAR = 2023
FILE_RE = re.compile(r"raiavl_exportacion_mensual_tr_cifra_(\d{4})\.csv$")


def discover_years() -> list[int]:
    years = []
    for path in RAW_DIR.glob("raiavl_exportacion_mensual_tr_cifra_*.csv"):
        m = FILE_RE.match(path.name)
        if m and int(m.group(1)) >= MIN_YEAR:
            years.append(int(m.group(1)))
    return sorted(years)


BRAND_ALIASES = {
    "BMW Group": "BMW",
    "Mercedes Benz_Prod_Expo": "Mercedes Benz",
}

OUT_FIELDS = ["anio", "mes", "marca", "modelo", "modelo_raw", "tipo", "segmento", "body_type", "pais_destino", "unidades", "estatus"]


def load_country_names() -> dict:
    path = CATALOGOS_DIR / "tc_pais_destino.csv"
    with open(path, encoding="utf-8") as f:
        return {row["ID_PAIS_DESTINO"]: row["DESC_PAIS_DESTINO"] for row in csv.DictReader(f)}


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    country_names = load_country_names()
    rows_out = []
    years = discover_years()
    print(f"Years found in data/raw: {years}")

    for year in years:
        src = RAW_DIR / f"raiavl_exportacion_mensual_tr_cifra_{year}.csv"
        with open(src, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                marca = BRAND_ALIASES.get(row["MARCA"].strip(), row["MARCA"].strip())
                modelo_raw = row["MODELO"].strip()
                tipo = row["TIPO"].strip()
                segmento = row["SEGMENTO"].strip()

                override = _OVERRIDES.get((marca, modelo_raw))
                if override:
                    body_type = override["body_type"]
                else:
                    body_type, _ = classify_body_type(modelo_raw, tipo, segmento)
                modelo = normalize_model_name(marca, modelo_raw)

                rows_out.append({
                    "anio": row["ANIO"],
                    "mes": row["ID_MES"],
                    "marca": marca,
                    "modelo": modelo,
                    "modelo_raw": modelo_raw,
                    "tipo": tipo,
                    "segmento": segmento,
                    "body_type": body_type,
                    "pais_destino": country_names.get(row["ID_PAIS_DESTINO"], "Desconocido"),
                    "unidades": row["UNI_VEH"],
                    "estatus": row["ESTATUS"].strip(),
                })

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Wrote {len(rows_out)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
