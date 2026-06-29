# Automatizacion DGT en GitHub Actions

El workflow `.github/workflows/dgt-auto.yml` ejecuta:

```bash
python process_month.py auto --force
```

La sincronizacion hace dos cosas:

- Descubre en la pagina mensual de la DGT los ficheros cerrados de 2026 y genera `dgt_canal_YYYYMM.csv`.
- Descubre en la pagina diaria de la DGT los ficheros del mes en curso, genera `dgt_canal_daily_YYYYMMDD.csv` y recalcula `dgt_canal_YYYYMM_mtd.csv`.

GitHub Actions esta programado entre semana en varias ventanas UTC para cubrir CET/CEST y la actualizacion tardia de algunos lunes. Si no hay nuevos datos, el workflow termina sin commit.

Ficheros que deben estar versionados para que el drift funcione bien:

- `process_month.py`
- `.github/workflows/dgt-auto.yml`
- `dgt_canal_2023*.csv`, `dgt_canal_2024*.csv`, `dgt_canal_2025*.csv`
- Los nuevos `dgt_canal_2026*.csv`, `dgt_canal_daily_2026*.csv` y `dgt_alerts_*.csv` se commitean solos.

Los CSV fuente Simmix `BBDD_*_PRODUCTO.csv` quedan ignorados porque son grandes y no hacen falta para la ejecucion diaria.
