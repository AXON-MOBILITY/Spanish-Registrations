# Matriculaciones de Portugal — fuentes y plan

Portugal NO tiene equivalente público a los microdatos DGT. El homólogo de ANFAC es **ACAP** (acap.pt), y su filial de datos de pago es **Autoinforma / MotorData** (el "Benchmark portugués": mensual por marca/modelo/canal bajo suscripción).

## Qué hay gratis y qué cubre

| Fuente | Detalle | Periodo | Formato |
|---|---|---|---|
| **EEA CO₂ monitoring** (Agencia Europea M.A.) | Registro a registro: marca, modelo, fuel, CO₂… turismos nuevos | 2023, 2024 finales; 2025 provisional cuando lo publiquen | CSV descargable (misma fuente que `masters/master_eea_versions_spain.csv`) |
| **ACAP — XLSX por marca** (URL fija, se actualiza cada mes) | Marca: mes actual + acumulado año + comparativa año anterior | Mes en curso (desde jul-2026 acumulamos snapshots) | XLSX público |
| **ACAP — PDF por energía** | Totales por tipo de energía | Mensual | PDF |
| **ACAP notas de prensa / ACEA / Eurostat** | Totales de mercado mensuales | Desde siempre | Web |

**Hueco sin fuente gratuita**: serie mensual por marca 2023 → may-2026. Solo la vende Autoinforma/MotorData. Alternativa parcial: el XLSX de cada mes trae la comparativa del mismo mes del año anterior → en 12 meses de snapshots se reconstruye también el año previo.

## Operativa montada

- `scripts/fetch_portugal_acap.py` — descarga el XLSX+PDF de ACAP, archiva snapshot fechado en `data/portugal/raw/`, parsea marcas y mantiene la serie `data/portugal/pt_marcas_mensual.csv`. Ejecutar el día ~3 de cada mes (workflow `portugal.yml`).
- Histórico 2023–2024: descargar el CSV de Portugal del portal EEA (co2cars, "All Data") y colocarlo en `data/portugal/raw/`; el análisis por marca/fuel sale directo con pandas.

## URLs

- ACAP estadísticas: https://www.acap.pt/pt/estatisticas
- XLSX marcas: https://www.acap.pt/site/uploads/paginas/documentos/07BAB4AD-CDBD0_1.xlsx
- PDF energía: https://www.acap.pt/site/uploads/paginas/documentos/3E585470-43560_1.pdf
- EEA CO₂ cars: https://www.eea.europa.eu/en/datahub/datahubitem-view/fa8b1229-3db6-495d-b18e-9c9b3267c02b
- Autoinforma (pago): https://autoinforma.pt / https://motordata.pt

## Decisión pendiente

Si Portugal necesita el mismo nivel que España (mensual por marca con histórico y canales), hay que presupuestar MotorData de Autoinforma — contacto vía ACAP (mail@acap.pt, +351 213 035 300).
