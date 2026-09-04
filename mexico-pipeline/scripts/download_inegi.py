"""Download the raw RAIAVL (INEGI) open-data ZIPs used by this project.

Source: Registro Administrativo de la Industria Automotriz de Vehiculos
Ligeros (RAIAVL) - https://www.inegi.org.mx/datosprimarios/iavl/

Re-run monthly (INEGI publishes new figures ~mid-month). Existing files
are overwritten so re-running always picks up revised/preliminary
figures INEGI corrects in later months (ESTATUS column).
"""
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

DATASETS = {
    # marca+modelo level monthly sales, national coverage
    "venta": "https://www.inegi.org.mx/contenidos/datosprimarios/iavl/datosabiertos/conjunto_de_datos_raiavl_mensual_venta_csv.zip",
    # EV/PHEV/HEV monthly sales, state level (no brand/model breakdown)
    "hibrido": "https://www.inegi.org.mx/contenidos/datosprimarios/iavl/datosabiertos/conjunto_de_datos_raiavl_mensual_hibrido_csv.zip",
    # marca+modelo level monthly exports, with destination country
    "exportacion": "https://www.inegi.org.mx/contenidos/datosprimarios/iavl/datosabiertos/conjunto_de_datos_raiavl_mensual_exportacion_csv.zip",
    # marca+modelo level monthly production (domestic sales + exports combined)
    "produccion": "https://www.inegi.org.mx/contenidos/datosprimarios/iavl/datosabiertos/conjunto_de_datos_raiavl_mensual_produccion_csv.zip",
}


def download_and_extract(name: str, url: str) -> None:
    target_dir = RAW_DIR / name
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / f"{name}.zip"

    print(f"Downloading {name} from {url}")
    urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target_dir)
    zip_path.unlink()
    print(f"Extracted to {target_dir}")


def main() -> None:
    for name, url in DATASETS.items():
        download_and_extract(name, url)


if __name__ == "__main__":
    main()
