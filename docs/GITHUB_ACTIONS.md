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

- `"1"` (transicion): el dashboa