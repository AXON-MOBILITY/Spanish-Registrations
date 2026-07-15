# Automatizacion DGT en GitHub Actions

Dos workflows:

- `.github/workflows/dgt-auto.yml` — sincronizacion diaria. Instala `requirements.txt`, corre los tests como gate (`pytest tests/`), ejecuta `python scripts/process_month.py auto --force` y `python scripts/build_dashboard_data.py`, y commitea `data/processed/` + `public/`.
- `.github/workflows/ci.yml` — tests + smoke build en cada push/PR.

La sincronizacion hace dos cosas:

- Descubre en la pagina mensual de la DGT los ficheros cerrados de 2026 y genera `data/processed/dgt_canal_YYYYMM.csv`.
- Descubre en la pagina diaria de la DGT los ficheros del mes en curso, genera `data/processed/dgt_canal_daily_YYYYMMDD.csv` y recalcula `dgt_canal_YYYYMM_mtd.csv`.

GitHub Actions esta programado entre semana en varias ventanas UTC para cubrir CET/CEST y la actualizacion tardia de algunos lunes. Si no hay nuevos datos, el workflow termina sin commit.

## Interruptor de independencia

La variable `SIMMIX_ALIGN` (definida en `dgt-auto.yml`, seccion `env`):

- `"1"` (legado): el dashboard alinea 2026 al ultimo export Simmix. En paralelo se publica siempre `public/data/simmix_drift.json` con el delta real de la ETL propia.
- `"0"` (actual, independiente): el dashboard publica la ETL propia; Simmix solo alimenta el drift.

El workflow ya usa `"0"`; para comparar contra Simmix se revisa `public/data/simmix_drift.json`.

## Ficheros versionados

- `scripts/`, `tests/`, `masters/`, `.github/workflows/`
- `data/processed/dgt_canal_*.csv`, `dgt_prov_*.csv`, `dgt_alerts_*.csv` (se commitean solos)
- Los CSV fuente Simmix `BBDD_*` viven en `validation/` y quedan ignorados (grandes y de pago); no hacen falta para la ejecucion diaria.
