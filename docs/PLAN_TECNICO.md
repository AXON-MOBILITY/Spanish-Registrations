# Plan Técnico: Dashboard Matriculaciones DGT

## Resumen ejecutivo

Pipeline automatizado que descarga, parsea y visualiza los datos de matriculaciones de vehículos de la DGT. Ingesta histórica desde 2023 + actualización diaria automática a las 9am. Dashboard web desplegado en Vercel, pipeline de datos en GitHub Actions.

---

## 1. Fuentes de datos

### Histórico mensual
- **URL**: `https://www.dgt.es/microdatos/salida/{YYYY}/{M}/vehiculos/matriculaciones/export_mensual_mat_{YYYYMM}.zip`
- **Disponible desde**: Diciembre 2014 (usaremos desde enero 2023)
- **Alcance inicial**: 41 meses (enero 2023 – mayo 2026)
- **Tamaño**: ~10–15 MB por ZIP comprimido / ~130 MB descomprimido
- **Registros**: ~190.000 registros/mes

### Diario
- **URL**: `https://www.dgt.es/microdatos/salida/{YYYY}/{M}/vehiculos/matriculaciones/export_mat_{YYYYMMDD}.zip`
- **Publicación**: Cada día laborable, normalmente antes de las 9am
- **Tamaño**: ~1–2 MB comprimido / ~6 MB descomprimido
- **Registros**: ~8.000 registros/día

**Clave**: Las URLs son 100% predecibles. No es necesario hacer scraping del HTML.

---

## 2. Formato de los datos

- Fichero TXT de ancho fijo: **714 caracteres por línea**
- Encoding: **Latin-1 / Windows-1252**
- Primera línea: cabecera textual (ignorar)
- Cada línea = 1 vehículo matriculado

### Campos identificados (aproximados, pendiente de validar con diccionario DGT)

| Posición aprox. | Campo |
|---|---|
| 1–8 | Fecha matriculación (DDMMYYYY) |
| ~10–18 | Código interno |
| ~19–48 | Marca |
| ~49–70 | Modelo |
| ~71–92 | VIN (parcialmente enmascarado con ***) |
| ~93–95 | Código combustible |
| ~96–100 | Cilindrada (cc) |
| ~101–106 | Potencia (CV) |
| ~107–112 | Peso / Tara |
| ~113–118 | PMA |
| ~119–120 | Número plazas |
| ... | Municipio matriculación |
| ... | Código provincia |
| ... | Tipo de vehículo (M1, N1, L3E...) |
| ... | Tipo de carrocería |
| ... | Norma de emisiones |
| ... | Clasificación combustible (HEV, PHEV, BEV...) |

> ⚠️ **Acción requerida**: Conseguir el diccionario oficial de columnas de la DGT o validar contra parsers open-source existentes. El layout puede haber cambiado entre años.

---

## 3. Arquitectura técnica

```
┌─────────────────────────────────────────────────────────┐
│  GitHub Repository                                       │
│                                                         │
│  /scripts/                                              │
│    pipeline.py        ← Parser + agregador principal    │
│    download_historic.py ← Carga inicial histórico       │
│    masters/           ← Ficheros maestros               │
│                                                         │
│  /data/               ← JSONs agregados (versionados)   │
│    daily.json         ← Últimos 90 días por día         │
│    monthly.json       ← Mensual desde 2023              │
│    by_brand.json      ← Por marca                       │
│    by_fuel.json       ← Por tipo combustible            │
│    by_province.json   ← Por provincia/CCAA              │
│    by_segment.json    ← Por segmento de vehículo        │
│    metadata.json      ← Última actualización, totales   │
│                                                         │
│  /dashboard/          ← Código Next.js                  │
│    pages/             ← Rutas de Vercel                 │
│    components/        ← Gráficas, KPIs                  │
└─────────────────────────────────────────────────────────┘
         │                              │
         ↓                              ↓
  GitHub Actions                     Vercel
  (cron 09:05 CET)              (auto-deploy on push)
```

---

## 4. Stack tecnológico

| Capa | Tecnología | Razón |
|---|---|---|
| Pipeline / parser | **Python 3.11+** | pandas / polars para ancho fijo, requests para descarga |
| Procesamiento rápido | **DuckDB** | Agregaciones OLAP sobre 7.8M registros en segundos |
| Almacenamiento intermedio | **Parquet** | Comprimido (300-500 MB para todo el histórico) |
| Salida dashboard | **JSON estático** | Agregados pre-computados, sin base de datos en producción |
| Automatización | **GitHub Actions** | Cron job gratuito, integrado con el repo |
| Frontend | **Next.js** | SSG, lee JSONs del repo en build time |
| Gráficas | **Recharts** o **Chart.js** | Bien integrado con React/Next.js |
| Hosting | **Vercel** | Deploy automático en cada push |

---

## 5. GitHub Actions — cron diario

```yaml
# .github/workflows/daily_update.yml
name: Daily DGT Update
on:
  schedule:
    - cron: '5 8 * * 1-5'  # 9:05h CET (8:05 UTC) lunes-viernes
  workflow_dispatch:         # permite ejecución manual

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt
      - run: python scripts/pipeline.py --mode=daily
      - name: Commit updated data
        run: |
          git config user.name "github-actions[bot]"
          git add data/
          git diff --staged --quiet || git commit -m "data: update $(date +%Y-%m-%d)"
          git push
```

**Lógica de reintento**: si el ZIP del día no está disponible aún (HTTP 404), el script espera 15 min y reintenta hasta 3 veces.

**Idempotencia**: el script verifica si el fichero del día ya fue procesado antes de insertar, para evitar duplicados si se ejecuta dos veces.

---

## 6. Maestros necesarios

| Maestro | Estado | Descripción |
|---|---|---|
| Marcas / grupos | Parcial (usuario tiene algo) | Normalizar nombres DGT → marca comercial → grupo empresarial |
| Tipos de vehículo (M1, N1…) | Pendiente de construir | Clasificación por categoría homologación |
| Segmentos | Parcial (usuario tiene algo) | A, B, C, D, SUV, Comercial, Moto... |
| Provincias / CCAA | Construir desde datos | Código DGT → nombre provincia → CCAA → región |
| Tipo combustible | Pendiente | BEV, PHEV, HEV, GAS, DIE, GLP, HID... |

---

## 7. Modelo de datos final (JSONs)

```json
// monthly.json
{
  "2026-05": { "total": 189626, "bev": 12450, "phev": 8320, ... },
  "2026-04": { ... },
  ...
}

// by_brand.json  (acumulado año en curso)
{
  "VOLKSWAGEN": { "total": 15420, "bev": 2100, "phev": 1800, ... },
  "TOYOTA": { ... },
  ...
}
```

---

## 8. Dashboard — páginas y KPIs

### Página principal
- Total matriculaciones del día / mes en curso / año en curso
- Variación vs. mismo período año anterior (YoY %)
- Gráfica de línea: últimos 12 meses
- Mini mapa de España: matriculaciones por provincia (heat map)

### Página de electrificación
- Cuota BEV, PHEV, HEV, MHEV del mes
- Evolución mensual de cuotas de electrificación (barras apiladas)
- Top 10 modelos BEV/PHEV

### Página de marcas
- Ranking top 20 marcas (mes / año)
- Cuota de mercado por grupo empresarial
- Evolución cuota mensual (seleccionable por marca)

### Filtros globales
- Año / Mes
- Provincia / CCAA
- Tipo de vehículo (M1 turismos / N1 comerciales / L motos)

---

## 9. Fases de ejecución

### Fase 0 — Prerequisitos (antes de empezar)
- [ ] Conseguir/validar el diccionario de columnas del formato fijo DGT
- [ ] Revisar parsers open-source existentes (GitHub)
- [ ] Recopilar los ficheros maestros del usuario
- [ ] Crear el repositorio GitHub

### Fase 1 — Parser y carga histórica (~1 semana)
- [ ] Script Python que parsea el formato fijo con columnas correctas
- [ ] Validar contra 3-4 meses de diferentes años (¿cambió el layout?)
- [ ] Descargar los 41 ZIPs mensuales (2023–2026)
- [ ] Generar los ficheros Parquet / base DuckDB local
- [ ] Script de generación de los JSONs agregados

### Fase 2 — Automatización GitHub Actions (~2-3 días)
- [ ] Workflow diario con cron
- [ ] Lógica de reintento si el fichero no está disponible
- [ ] Commit automático de `data/`

### Fase 3 — Dashboard Next.js (~1 semana)
- [ ] Scaffold del proyecto Next.js
- [ ] Componentes de KPI, gráficas de línea, barras, mapa
- [ ] Integración con los JSONs del repo
- [ ] Despliegue en Vercel + dominio

### Fase 4 — Maestros y enriquecimiento (~1 semana)
- [ ] Integrar ficheros maestros del usuario
- [ ] Completar los maestros que faltan
- [ ] Validar clasificaciones vs. fuentes externas (ANFAC, Faconauto)

---

## 10. Estimación de volumen

| Concepto | Valor |
|---|---|
| Registros totales histórico 2023–2026 | ~7,8 millones |
| Tamaño raw descomprimido | ~5,3 GB |
| Tamaño en Parquet comprimido | ~300–500 MB |
| Tamaño JSONs agregados dashboard | ~5–20 MB |
| Tiempo carga inicial (script Python) | ~1–2 horas |
| Tiempo proceso diario (GitHub Actions) | ~2–5 minutos |
| Coste infraestructura | **0€** (GitHub Free + Vercel Free) |

---

## 11. Riesgos y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| El layout del fichero fijo cambió entre años | Media | Validar contra muestras de 2023, 2024, 2025 antes de procesar todo |
| DGT sube el fichero tarde (>9am) | Baja-Media | Lógica de reintento hasta las 10:30am |
| DGT cambia la URL o el formato | Baja | Alertas de fallo en GitHub Actions (email automático) |
| GitHub Actions gratuito (2000 min/mes) | Muy baja | El job diario tardará <5 min, consume <100 min/mes |
| Límite de repo size de GitHub | Baja | Los JSONs pesan MBs, no GBs. Los Parquet se excluyen del repo |

---

*Documento generado: 2026-06-25*
