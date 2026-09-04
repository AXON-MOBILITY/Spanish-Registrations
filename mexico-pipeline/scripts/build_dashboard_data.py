"""Build data/processed/mx_registrations.csv into the JSON the
static dashboard (public/index.html) consumes.

Mirrors the enum-encoded "records.json" pattern used by the Spanish
Registrations dashboard: rows are stored as compact index arrays against
shared lookup tables (enums), and all filtering/aggregation happens
client-side in JS. Our dataset (~19.5k rows) is far smaller than the
Spanish daily-DGT one, but the same encoding keeps the two dashboards
consistent and the payload small.
"""
import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "processed" / "mx_registrations.csv"
EXPORT_SRC = ROOT / "data" / "processed" / "mx_exports.csv"
PRODUCTION_SRC = ROOT / "data" / "processed" / "mx_production.csv"
OUT_DIR = ROOT / "public" / "data"

COL = ["anio", "mes", "marca", "modelo", "fuel_type", "body_type", "origen", "confidence"]
EXPORT_COL = ["anio", "mes", "marca", "modelo", "body_type", "pais_destino"]
PRODUCTION_COL = ["anio", "mes", "marca", "modelo", "body_type"]


def enum_encode(rows, columns):
    """Encode CSV rows into {enums, rows} against shared lookup tables,
    same pattern the dashboard's JS expects (see records.json)."""
    enums = {c: [] for c in columns}
    enum_idx = {c: {} for c in columns}

    def idx_for(col, value):
        m = enum_idx[col]
        if value not in m:
            m[value] = len(enums[col])
            enums[col].append(value)
        return m[value]

    out_rows = []
    for r in rows:
        out_rows.append([idx_for(c, int(r[c]) if c == "anio" else r[c]) for c in columns] + [int(r["unidades"])])

    enums["anio"], remap_anio = _sorted_remap(enums["anio"])
    enums["mes"], remap_mes = _sorted_remap(enums["mes"])
    for row in out_rows:
        row[columns.index("anio")] = remap_anio[row[columns.index("anio")]]
        row[columns.index("mes")] = remap_mes[row[columns.index("mes")]]

    return {
        "col": {name: i for i, name in enumerate(columns + ["unidades"])},
        "enums": enums,
        "rows": out_rows,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(SRC, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    payload = enum_encode(rows, COL)
    with open(OUT_DIR / "records.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    write_meta(rows)
    print(f"Wrote {len(payload['rows'])} rows to {OUT_DIR / 'records.json'}")

    with open(EXPORT_SRC, encoding="utf-8") as f:
        export_rows = list(csv.DictReader(f))
    export_payload = enum_encode(export_rows, EXPORT_COL)
    with open(OUT_DIR / "records_export.json", "w", encoding="utf-8") as f:
        json.dump(export_payload, f, ensure_ascii=False, separators=(",", ":"))
    write_meta_export(export_rows)
    print(f"Wrote {len(export_payload['rows'])} rows to {OUT_DIR / 'records_export.json'}")

    with open(PRODUCTION_SRC, encoding="utf-8") as f:
        production_rows = list(csv.DictReader(f))
    production_payload = enum_encode(production_rows, PRODUCTION_COL)
    with open(OUT_DIR / "records_production.json", "w", encoding="utf-8") as f:
        json.dump(production_payload, f, ensure_ascii=False, separators=(",", ":"))
    write_meta_production(production_rows)
    print(f"Wrote {len(production_payload['rows'])} rows to {OUT_DIR / 'records_production.json'}")

    docs_out = ROOT / "public" / "docs"
    docs_out.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "docs" / "METODOLOGIA.md", docs_out / "METODOLOGIA.md")


def _sorted_remap(values):
    """Sort an enum's values and return (sorted_list, old_idx -> new_idx)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    sorted_values = [values[i] for i in order]
    remap = {old: new for new, old in enumerate(order)}
    return sorted_values, remap


def write_meta(rows) -> None:
    from datetime import datetime, timezone

    total_units = sum(int(r["unidades"]) for r in rows)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "INEGI RAIAVL - Registro Administrativo de la Industria "
                   "Automotriz de Vehiculos Ligeros. Venta de vehiculos",
        "source_url": "https://www.inegi.org.mx/datosprimarios/iavl/",
        "coverage": "Nacional (Mexico), sin desglose por estado",
        "years": sorted({r["anio"] for r in rows}),
        "total_units": total_units,
        "brands": len({r["marca"] for r in rows}),
        "models": len({(r["marca"], r["modelo"]) for r in rows}),
    }
    with open(OUT_DIR / "meta.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def write_meta_export(rows) -> None:
    from datetime import datetime, timezone

    total_units = sum(int(r["unidades"]) for r in rows)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "INEGI RAIAVL - Registro Administrativo de la Industria "
                   "Automotriz de Vehiculos Ligeros. Exportacion de vehiculos",
        "source_url": "https://www.inegi.org.mx/datosprimarios/iavl/",
        "coverage": "Nacional (Mexico), origen de fabricacion; destino = pais receptor",
        "years": sorted({r["anio"] for r in rows}),
        "total_units": total_units,
        "brands": len({r["marca"] for r in rows}),
        "models": len({(r["marca"], r["modelo"]) for r in rows}),
        "countries": len({r["pais_destino"] for r in rows}),
    }
    with open(OUT_DIR / "meta_export.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def write_meta_production(rows) -> None:
    from datetime import datetime, timezone

    total_units = sum(int(r["unidades"]) for r in rows)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "INEGI RAIAVL - Registro Administrativo de la Industria "
                   "Automotriz de Vehiculos Ligeros. Produccion de vehiculos",
        "source_url": "https://www.inegi.org.mx/datosprimarios/iavl/",
        "coverage": "Nacional (Mexico) - unidades fabricadas, para venta domestica o exportacion",
        "years": sorted({r["anio"] for r in rows}),
        "total_units": total_units,
        "brands": len({r["marca"] for r in rows}),
        "models": len({(r["marca"], r["modelo"]) for r in rows}),
    }
    with open(OUT_DIR / "meta_production.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
