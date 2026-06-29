"""
run_pipeline.py — Orquestador completo DGT → BBDD_DGT.csv
Descarga todos los ficheros mensuales (2023→mes_anterior) y diarios (mes_actual),
los procesa con pipeline.py y los une en un único CSV de salida.

Uso:
    python run_pipeline.py                         # procesa todo desde 2023
    python run_pipeline.py --desde 2024-01         # desde enero 2024
    python run_pipeline.py --reset                 # borra checkpoint y reprocesa todo
    python run_pipeline.py --solo-diarios          # solo actualiza mes actual

Salida: BBDD_DGT.csv (en la misma carpeta)
Checkpoint: .checkpoint.json (registra qué meses/días ya están procesados)
"""

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

import requests

# ── Importar lógica de pipeline.py ──────────────────────────────────────────
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from pipeline import parse_line, is_turismo, enrich, load_masters

# ── Configuración ────────────────────────────────────────────────────────────
OUT_CSV     = BASE / "BBDD_DGT.csv"
CHECKPOINT  = BASE / ".checkpoint.json"
HEADERS_DGT = {"User-Agent": "Mozilla/5.0 (compatible; DGT-pipeline/1.0)"}

URL_MENSUAL_PAGE = "https://www.dgt.es/menusecundario/dgt-en-cifras/matraba-listados/matriculaciones-automoviles-mensual.html"
URL_DIARIO_PAGE  = "https://www.dgt.es/menusecundario/dgt-en-cifras/matraba-listados/matriculaciones-automoviles-diario.html"

# Columnas de salida (orden Simmix)
COLS_OUT = [
    "Brand","Model","Fuel","Channel","SubCanales","Provincia","Zona",
    "Year","Month","Segment_Origin","SubSegmento","High Performance",
    "Version","Body Type","Brand & Model","Homologation_Origin",
    "Concesin","Id Concesin","Puntos de Venta","Id Punto de Venta",
    "Municipio","Registrations","HP","Sort_Month","Homologation",
    "Nation","Fuel_Type","Segment","Sort_Segment",
    "_version_source","_variante","_kw",
]


# ── Descubrimiento de URLs ────────────────────────────────────────────────────

def scrape_urls(page_url, pattern):
    """Devuelve lista de URLs ZIP que encajan con el patrón regex."""
    try:
        r = requests.get(page_url, headers=HEADERS_DGT, timeout=30)
        r.raise_for_status()
        return sorted(set(re.findall(pattern, r.text)))
    except Exception as e:
        print(f"  ⚠️  Error scrapeando {page_url}: {e}")
        return []


def get_monthly_urls(desde_yyyymm=None):
    """Lista URLs mensuales disponibles, opcionalmente filtradas por fecha mínima."""
    urls = scrape_urls(URL_MENSUAL_PAGE,
                       r'https://www\.dgt\.es/microdatos/salida/\d+/\d+/vehiculos/matriculaciones/export_mensual_mat_\d{6}\.zip')
    if desde_yyyymm:
        urls = [u for u in urls if _yyyymm_from_monthly_url(u) >= desde_yyyymm]
    return urls


def get_daily_urls():
    """Lista URLs diarias del mes actual."""
    return scrape_urls(URL_DIARIO_PAGE,
                       r'https://www\.dgt\.es/microdatos/salida/\d+/\d+/vehiculos/matriculaciones/export_mat_\d{8}\.zip')


def _yyyymm_from_monthly_url(url):
    m = re.search(r'export_mensual_mat_(\d{6})\.zip', url)
    return m.group(1) if m else "000000"

def _yyyymmdd_from_daily_url(url):
    m = re.search(r'export_mat_(\d{8})\.zip', url)
    return m.group(1) if m else "00000000"


# ── Checkpoint ────────────────────────────────────────────────────────────────

def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"monthly": [], "daily": []}

def save_checkpoint(cp):
    CHECKPOINT.write_text(json.dumps(cp, indent=2))


# ── Descarga + parseo de un fichero ZIP ──────────────────────────────────────

def download_and_iter_lines(url):
    """Descarga el ZIP, extrae el TXT y devuelve un iterador de líneas."""
    r = requests.get(url, headers=HEADERS_DGT, timeout=120, stream=True)
    r.raise_for_status()
    raw = b"".join(r.iter_content(65536))
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = z.namelist()[0]
    return io.TextIOWrapper(z.open(name), encoding="latin-1", errors="replace")


# ── Procesar un fichero y escribir al CSV ────────────────────────────────────

def process_file(url, writer, masters, label):
    """Descarga, parsea y escribe filas enriquecidas. Devuelve nº de turismos escritos."""
    try:
        fh = download_and_iter_lines(url)
    except Exception as e:
        print(f"    ❌ Error descargando {label}: {e}")
        return 0

    count = 0
    for i, raw_line in enumerate(fh):
        line = raw_line.rstrip("\n")
        if i == 0 and not line[:8].isdigit():
            continue  # cabecera
        rec = parse_line(line)
        if rec is None or not is_turismo(rec["CATEGORIA_HOMOLOGACION_ITV"]):
            continue
        row = enrich(rec, *masters)
        writer.writerow({k: row.get(k, "") for k in COLS_OUT})
        count += 1

    return count


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Orquestador DGT completo")
    parser.add_argument("--desde",       help="Mes mínimo YYYY-MM (ej: 2023-01)", default="2023-01")
    parser.add_argument("--reset",       action="store_true", help="Borra checkpoint y reprocesa todo")
    parser.add_argument("--solo-diarios",action="store_true", help="Solo procesa ficheros diarios del mes actual")
    parser.add_argument("--out",         help="Ruta CSV de salida", default=str(OUT_CSV))
    args = parser.parse_args()

    out_path = Path(args.out)
    desde_yyyymm = args.desde.replace("-", "")  # "2023-01" → "202301"

    # Checkpoint
    if args.reset and CHECKPOINT.exists():
        CHECKPOINT.unlink()
        print("🔄 Checkpoint borrado — reprocesando todo")
    cp = load_checkpoint()

    # Cargar maestros de enriquecimiento (una sola vez)
    masters = load_masters()

    # Descubrir URLs
    if args.solo_diarios:
        monthly_urls = []
    else:
        print("\n📋 Descubriendo ficheros mensuales...")
        monthly_urls = get_monthly_urls(desde_yyyymm)
        monthly_new  = [u for u in monthly_urls if _yyyymm_from_monthly_url(u) not in cp["monthly"]]
        print(f"   Total mensual disponible: {len(monthly_urls)} | Nuevos: {len(monthly_new)}")

    print("📋 Descubriendo ficheros diarios...")
    daily_urls = get_daily_urls()
    daily_new  = [u for u in daily_urls if _yyyymmdd_from_daily_url(u) not in cp["daily"]]
    print(f"   Total diarios disponibles: {len(daily_urls)} | Nuevos: {len(daily_new)}")

    total_new = len(monthly_new if not args.solo_diarios else []) + len(daily_new)
    if total_new == 0:
        print("\n✅ Todo al día — no hay ficheros nuevos que procesar.")
        return

    # Abrir CSV (append si ya existe, create si no)
    file_exists = out_path.exists() and out_path.stat().st_size > 0
    mode = "a" if file_exists else "w"
    if mode == "w":
        print(f"\n📁 Creando {out_path.name}")
    else:
        print(f"\n📁 Añadiendo a {out_path.name} (ya existente)")

    total_rows = 0
    with open(out_path, mode, newline="", encoding="utf-8-sig") as fout:
        writer = csv.DictWriter(fout, fieldnames=COLS_OUT)
        if mode == "w":
            writer.writeheader()

        # ── Mensuales ──────────────────────────────────────────────────────
        if not args.solo_diarios:
            for url in monthly_new:
                label = _yyyymm_from_monthly_url(url)
                yyyymm_fmt = f"{label[:4]}/{label[4:]}"
                print(f"  ⬇️  Mensual {yyyymm_fmt} ...", end=" ", flush=True)
                n = process_file(url, writer, masters, label)
                print(f"{n:,} turismos")
                total_rows += n
                cp["monthly"].append(label)
                save_checkpoint(cp)

        # ── Diarios ────────────────────────────────────────────────────────
        # Antes de añadir diarios: si el mes ya está completo en mensual, ignorar
        for url in daily_new:
            label = _yyyymmdd_from_daily_url(url)
            month_key = label[:6]  # YYYYMM
            if month_key in cp["monthly"]:
                print(f"  ⏭️  Diario {label} — mes {month_key} ya en mensual, skip")
                cp["daily"].append(label)
                save_checkpoint(cp)
                continue
            date_fmt = f"{label[6:8]}/{label[4:6]}/{label[:4]}"
            print(f"  ⬇️  Diario {date_fmt} ...", end=" ", flush=True)
            n = process_file(url, writer, masters, label)
            print(f"{n:,} turismos")
            total_rows += n
            cp["daily"].append(label)
            save_checkpoint(cp)

    print(f"\n✅ Completado: {total_rows:,} turismos nuevos → {out_path.name}")
    print(f"   Meses en checkpoint: {len(cp['monthly'])} mensuales + {len(cp['daily'])} diarios")


if __name__ == "__main__":
    main()
