# Auditoría de independencia de Simmix
*Fecha: 2026-07-02 · Repo: Nachoor/Spanish-Registrations · Dashboard: spanish-registrations.vercel.app*

## 1. Objetivo

Sustituir a Simmix como proveedor. El pipeline debe transformar los microdatos brutos de la DGT en la clasificación Simmix (canales, subcanales, segmentos, fuel) de forma autónoma, con el dashboard actualizándose a diario desde la página de la DGT sin intervención manual ni ficheros BBDD del proveedor.

## 2. Estado de la automatización — ✅ operativa

La cadena diaria funciona: GitHub Actions (`dgt-auto.yml`, cron l–v en 4 ventanas UTC) ejecuta `process_month.py auto --force` (descubre y descarga diarios + mensuales de la DGT), luego `build_dashboard_data.py`, commitea los CSV/JSON y Vercel redespliega. Si la DGT no publica, termina sin commit. Idempotente y con alertas de drift (`dgt_alerts_*.csv`).

## 3. Inventario de dependencias de Simmix

| # | Dependencia | Dónde | Tipo | Riesgo |
|---|---|---|---|---|
| 1 | `apply_simmix_2026_targets` | `build_dashboard_data.py` | **Runtime — crítica** | El dashboard NO muestra la ETL: reescala todos los registros 2026 para cuadrar exactamente con el último export Simmix (vía `simmix_2026_targets.json` commiteado), descarta combos que Simmix no tiene y crea registros sintéticos. **El cuadre actual es cosmético.** Solo se aplica mientras el mes del export == mes MTD; al pasar de mes, el dato "cuadrado" revierte a ETL cruda. |
| 2 | `CHANNEL_SCOPE_FACTOR` + `CHANNEL_SUBSEG_SCOPE_FACTOR` | `process_month.py` | Estadística congelada (2023–25) | **Se pudre con el tiempo.** Demostrado: DS inflaba +843 uds y Leapmotor borraba ~1.050 uds reales en H1 2026 (corregido 2026-07-02). VW RAC (+463) y Skoda RAC (+563) también sobrecorrigen ya. |
| 3 | `KM0_BRAND_FALLBACK_RATE` | `process_month.py` | Estadística congelada | Mueve % fijo de B00+D Private→Corporate por marca. Mismo riesgo de obsolescencia; VW Corporate −961 en H1 2026 sugiere drift. |
| 4 | `simmix_model_lookup.json` (enriquecimiento modelo→segmento/body) | `process_month.py` | Maestro estático derivado | Aceptable. Cobertura 95,8% en 2026. Necesita protocolo de modelos nuevos (el fallback + alerts ya existen). |
| 5 | `BBDD_*_PRODUCTO.csv` | Solo validación local | Auditoría | Sin riesgo: no se usan en CI. Es el uso correcto mientras dure el contrato. |

## 4. Precisión real de la ETL (H1 2026, sin la muleta del punto 1)

Tras eliminar los factores DS/Leapmotor:

- Totales por canal: Corporate +1,9%, Private +0,3%, RAC +0,7%.
- De 51 marcas con ≥500 uds, **40 dentro de ±2%** y 42 dentro de ±5%.
- Delta total: +7.324 uds (~1%), casi todo explicado por el punto siguiente.

**Hallazgo metodológico nuevo — carroceros→chasis**: Simmix reasigna los vehículos carrozados/camperizados a la marca y modelo del chasis; la ETL conserva la marca DGT. Explica los outliers: Renault Trucks (−99%: Master/Trafic), MAN (−56%: TGE), Mitsubishi-Fuso (Canter), Isuzu (−24%), Iveco (−9%), Ford (−7%: Transit) y parte de Fiat/Citroën/Peugeot (Ducato/Jumper/Boxer). En DGT esos vehículos aparecen como Erke, Sortimo, Benimar, Igluvan, Capron… (~10k uds/semestre con 0 en Simmix). Los factores Private de Fiat/Ford/Citroën/Renault/Opel están compensando esto estadísticamente — una regla determinista los haría innecesarios.

Pendientes de explicar: VW Corporate −961 (¿Km.0 nuevo 2026?), Ford Corporate −595, grupo DR/EVO (+8%/+28%, posible cruce de marcas del grupo DR: Sportequipe, ICH-X, Tiger).

## 5. Roadmap de independencia

**Fase 1 — hecho (2026-07-02)**: factores DS y Leapmotor eliminados; `process_month.py` reparado (estaba truncado y no compilaba); delta H1 2026 documentado (`delta_dgt_simmix_2026_H1.csv`).

**Fase 2 — reglas deterministas (1–2 semanas)**
1. Regla carroceros→chasis: mapear marca carrocera + texto del modelo raw (DUCATO, TRANSIT, MASTER, TGE, CANTER, BOXER, JUMPER, SPRINTER, CRAFTER…) a la marca/modelo de chasis. Después, retirar los factores Private compensatorios.
2. Investigar VW Corp y grupo DR/EVO con los raw de 2026.
3. Recalibrar los factores restantes con ventana móvil (últimos 6 meses) en lugar de 2023–25, y solo donde no exista regla determinista.

**Fase 3 — desconectar la muleta del dashboard**
Degradar `apply_simmix_2026_targets` a modo auditoría: en lugar de mutar los datos, que genere un informe de drift ETL vs Simmix (JSON/alerta). El dashboard pasa a mostrar siempre la ETL propia. Hacerlo cuando la Fase 2 deje los deltas dentro del KPI.

**Fase 4 — gobernanza sin proveedor**
- KPI de aceptación propuesto: |delta| < 2% por marca/canal (marcas ≥500 uds/semestre) y < 1% por canal a nivel mercado.
- Mientras dure el contrato: cargar cada export Simmix como validación (no como target) y registrar el delta histórico.
- Tras la baja: validación mensual cruzada con cifras públicas (ANFAC/Faconauto/ideauto a nivel marca-mercado) + alertas de drift ya existentes + cola de modelos nuevos sin clasificar (`simmix_model_lookup` pasa a ser "maestro propio", actualización manual trimestral).

## 6. Conocimiento metodológico Simmix consolidado

1. **Canal**: campo SERVICIO + persona física/jurídica (B00+X→Corp, A01→RAC con excepciones campa, A18/B18→Corp…).
2. **Km.0**: B00 + persona física en municipio de concesionario → Corporate (Simmix usa CP; nosotros municipio INE como proxy + fallback estadístico en grandes ciudades).
3. **Carroceros→chasis** (nuevo, confirmado con H1 2026): el carrozado cuenta para la marca del chasis.
4. **Fuel**: COD_PROPULSION + CATEGORIA_VEH_ELECTRICO; HEV cuenta como ICE; MHEV por texto de versión.
5. **Segmento/Body/Focus**: maestro BMW/IHS + lista marcas Focus; ya snapshot propio en `simmix_model_lookup.json`.
6. **Scope**: turismos M1 + furgonetas ligeras N1; excluye pesados, motos, trailers y algunos Mercedes industriales.
