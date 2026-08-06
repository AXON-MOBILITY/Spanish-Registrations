# Spanish Registrations — Matriculaciones DGT

Pipeline de datos y dashboard de matriculaciones de vehículos en España, construido sobre los **microdatos públicos de la DGT** y replicando la metodología de clasificación de Benchmark (canales, subcanales, segmentos, combustible) para independizarse del proveedor.

**Dashboard**: https://spanish-registrations.vercel.app/

## Arquitectura

```
DGT (diario/mensual, TXT ancho fijo 714 chars)
   │  scripts/process_month.py  ← ETL: parseo, scope, clasificación, enriquecimiento
   ▼
data/processed/dgt_canal_*.csv · dgt_prov_*.csv · dgt_alerts_*.csv
   │  scripts/build_dashboard_data.py  ← agregados + drift vs Benchmark
   ▼
public/data/*.json  →  Vercel (dashboard estático)
```

GitHub Actions (`.github/workflows/dgt-auto.yml`) ejecuta la cadena entre semana en varias ventanas horarias; si la DGT no ha publicado, termina sin commit. `ci.yml` corre los tests en cada push/PR.

## Estructura del repo

| Ruta | Contenido |
|---|---|
| `scripts/` | `process_month.py` (ETL), `build_dashboard_data.py` (agregados dashboard), `nif_lookup.py` |
| `data/processed/` | Salidas versionadas de la ETL (canal, provincia, alertas; mensual y diario) |
| `masters/` | Maestros propios (enriquecimiento modelo→segmento, concesiones, municipios, NIF) |
| `validation/` | Exports Benchmark `BBDD_*` (gitignored) y deltas de validación |
| `tests/` | Tests unitarios de las reglas de negocio (pytest) |
| `docs/` | Metodología, plan técnico, auditoría de independencia |
| `public/` | Dashboard estático + JSONs generados |
| `legacy/` | Scripts antiguos fuera de uso |

## Metodología (resumen)

La ETL replica la clasificación Benchmark desde el dato bruto DGT. Reglas principales, documentadas en `docs/`:

1. **Scope**: turismos M1 + furgonetas ligeras N1, más rescate N2 de derivados de furgoneta que Benchmark incluye (Renault Trucks Master, MAN TGE, Fuso Canter, Isuzu serie N, Iveco Daily).
2. **Canal**: campo SERVICIO + persona física/jurídica (B00+X→Corporate, A01→RAC con excepciones de campa, A18/B18→Corporate…).
3. **Km.0**: B00 + persona física en municipio de concesionario → Corporate; fallback estadístico por marca en grandes ciudades.
4. **Carroceros→chasis**: los carrozados/camperizados (Benimar, Erke, Sortimo…) se atribuyen a la marca/modelo del chasis (Ducato→Fiat, Transit→Ford, TGE→MAN…), como hace Benchmark. Los no mapeados generan alerta `CARROCERO_UNMAPPED`.
5. **Combustible**: propulsión DGT + categoría eléctrica; HEV cuenta como ICE; MHEV por texto de versión.
6. **Segmento/Body/Focus**: maestro propio derivado (`public/data/benchmark_model_lookup.json` + `masters/`), con cola de modelos nuevos vía alertas.
7. **Calibración residual**: factores estadísticos mínimos por marca/canal (`CHANNEL_SCOPE_FACTOR`), en retirada progresiva a medida que se sustituyen por reglas deterministas.

## Independencia de Benchmark

- `BENCHMARK_ALIGN=1` (legado): el dashboard alinea 2026 al ultimo export Benchmark; en paralelo se publica `public/data/benchmark_drift.json` con el delta real de la ETL.
- `BENCHMARK_ALIGN=0` (actual): el dashboard publica la ETL propia; el export Benchmark (mientras exista) solo alimenta el informe de drift.
- **KPI de desconexión**: |delta| ≤ 2% por marca/canal (marcas ≥500 uds/semestre) y ≤ 1% por canal a nivel mercado. Ver `docs/AUDITORIA_INDEPENDENCIA_BENCHMARK.md`.

## Uso

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                    # tests de reglas
python scripts/process_month.py auto --force  # sync diario + mensual
python scripts/process_month.py all --force   # reprocesar todo el histórico
python scripts/build_dashboard_data.py        # regenerar public/data
python scripts/build_dashboard_data.py                 # modo independiente por defecto
```

## Validación

Con cada export Benchmark nuevo: dejarlo en `validation/`, reprocesar y revisar `public/data/benchmark_drift.json` (o los `delta_*.csv` de `validation/`). Las alertas de drift diarias salen en `data/processed/dgt_alerts_*.csv`.
