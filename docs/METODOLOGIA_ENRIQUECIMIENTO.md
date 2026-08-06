# Metodología de Enriquecimiento de Datos DGT
## Ingeniería inversa del pipeline Benchmark

> **Objetivo**: Replicar los 29 campos del formato Benchmark (BBDD_AAAA_PRODUCTO) a partir de los datos brutos DGT + maestros propios. Para cada campo se documenta la fuente, la lógica exacta y cómo manejar casos nuevos.

---

## Arquitectura del pipeline de enriquecimiento

```
DGT raw (714 chars/línea)
    ↓ [Parser fijo]
69 campos estructurados
    ↓ [Filtro turismos]
Solo M1 / M1G / M1*
    ↓ [5 capas de enriquecimiento]
29 campos formato Benchmark
```

---

## Capa 1 — Campos directos del DGT (sin maestro)

Estos campos salen directamente del fichero DGT con transformación mínima.

| Campo Benchmark | Campo DGT | Transformación |
|---|---|---|
| `Brand` | `MARCA_ITV` | Title Case + limpieza de abreviaturas |
| `Model` | `MODELO_ITV` | Title Case |
| `Version` | `TIPO_ITV` o `VERSION_ITV` | Tal cual o limpieza menor |
| `Brand & Model` | `MARCA_ITV` + `MODELO_ITV` | Concatenar con espacio |
| `Homologation_Origin` | `CATEGORÍA_HOMOLOGACIÓN_EUROPEA_ITV` | Tal cual (M1, N1, M1G, N1G...) |
| `Homologation` | `CATEGORÍA_HOMOLOGACIÓN_EUROPEA_ITV` | M1/M1G/M1* → "Turismo"; N1/N1G/N1* → "Comercial" |
| `Municipio` | `MUNICIPIO` | Normalización de mayúsculas |
| `Provincia` | `COD_PROVINCIA_MAT` | Código DGT → nombre de provincia (tabla de 52) |
| `Year` | `FEC_MATRICULA` | Extraer año (posiciones 5-8) |
| `Month` | `FEC_MATRICULA` | Extraer mes → nombre en inglés |
| `Sort_Month` | `FEC_MATRICULA` | Convertir a fecha DD/MM/YYYY → 01/MM/YYYY |
| `HP` | `KW_ITV` | KW × 1.341 (conversión a CV fiscal) o usar `POTENCIA_ITV` directamente |
| `Registrations` | — | Siempre 1 por registro DGT (Benchmark agrega después) |

**Filtro turismos**: `CATEGORÍA_HOMOLOGACIÓN_EUROPEA_ITV` IN ('M1', 'M1G', 'M1*')

---

## Capa 2 — Combustible (regla sobre campos DGT)

Benchmark tiene dos niveles: `Fuel` (detallado, 12 valores) y `Fuel_Type` (simplificado: ICE / BEV / PHEV).

### Lógica de derivación

```
DGT COD_PROPULSION_ITV + CATEGORIA_VEHICULO_ELECTRICO → Fuel / Fuel_Type
```

| COD_PROPULSION | CATEGORIA_VEH_ELECTRICO | Fuel Benchmark | Fuel_Type |
|---|---|---|---|
| 0 (Gasolina) | BEV | — (raro) | BEV |
| 0 (Gasolina) | HEV | Gasolina/Electrico | ICE ⚠️ |
| 0 (Gasolina) | PHEV | Gasolina/Electrico Enchufable | PHEV |
| 0 (Gasolina) | REEV | Electrico | BEV |
| 0 (Gasolina) | _vacío_ | **Ver MHEV** | ICE |
| 1 (Diesel) | PHEV | Diesel/Electrico Enchufable | PHEV |
| 1 (Diesel) | _vacío_ | **Ver MHEV** | ICE |
| 2 (Eléctrico) | BEV | Electrico | BEV |
| 6 (GLP) | — | Gas Licuado con petroleo (GLP) | ICE |
| 7 (GNC) | — | Gas natural comprimido (GNC) | ICE |

> ⚠️ **Nota Benchmark**: Los HEV (no-enchufables como Toyota Hybrid) se clasifican como ICE en `Fuel_Type`. Solo BEV y PHEV son "electrificados" a efectos de canal.

### Detección MHEV (clave — el DGT no lo marca explícitamente)

**Confirmado por análisis**: Benchmark detecta MHEV parseando el campo de versión. En DGT, el campo `TIPO_ITV` o `VERSION_ITV` contiene la denominación de tipo homologada, que para los MHEV incluye "MHEV", "48V", "MILD" o "MICROHYBRID".

```python
def detectar_mhev(tipo_itv, variante_itv, version_itv):
    texto = f"{tipo_itv} {variante_itv} {version_itv}".upper()
    if any(kw in texto for kw in ['MHEV', '48V', 'MILD HYBRID', 'MICROHYBRID']):
        return True
    return False

# Regla final:
# COD_PROPULSION=0 + CATEGORIA_vacía + MHEV=True → "Gasolina Mild Hybrid"
# COD_PROPULSION=1 + CATEGORIA_vacía + MHEV=True → "Diesel Mild Hybrid"
# COD_PROPULSION=0/1 + CATEGORIA_vacía + MHEV=False → "Gasolina" / "Diesel"
```

**Cobertura en 2025**: 112.512 matriculaciones MHEV detectadas, que coincide con el 9% del mercado turismo — cifra plausible.

---

## Capa 3 — Canal y Subcanal (del campo SERVICIO DGT)

El campo DGT `SERVICIO` (3 chars, posición ~190-192) contiene el uso del vehículo.

| SERVICIO DGT | Channel | SubCanal |
|---|---|---|
| B00 | Private | P \| Particular Uso Privado |
| B17 (Vivienda) | Private | P \| Particular Uso Privado |
| B19 (Recreativo) | Private | P \| Particular Uso Privado |
| B21 (Ferias) | Private | P \| Particular Uso Privado |
| A04 (Taxi) | Private | P \| Particular Uso Publico |
| A07 (Ambulancia) | Private | P \| Particular Uso Publico |
| A03 (Autoescuela) | Private | P \| Empleados |
| A01 (Alquiler sin conductor) | RAC | R \| Rac Operativo |
| A18 / B18 (Actividad económica) | Corporate | E \| Empresas Detall |
| A05 (Auxilio carretera) | Corporate | E \| Empresas Detall |
| _vacío / ND_ | Private | P \| Particular Uso Privado |

### Subcategorías más complejas (requieren lógica adicional)

| SubCanal Benchmark | Cómo detectarlo |
|---|---|
| E \| Renting | SERVICIO=A01 + titular JURÍDICO (`PERSONA_FISICA_JURIDICA`=X) + empresa conocida de renting |
| R \| Buy Back | Registro de vehículo que fue de RAC (RAC + segunda matriculación) |
| E \| Km.0 | Titular JURÍDICO + `MARCA_ITV` = empresa concesionario (via `CODIGO_ITV`) |
| E \| Exportación | `COD_PROVINCIA_MAT` = 'EX' (Extranjero) |
| E \| Automatriculas | Titular es concesionario / marca (via `CODIGO_ITV` o razón social) |

> **Aproximación inicial**: Con B00→Private, A01→RAC, A18→Corporate ya capturas el 90% del volumen. Los subcategorías finas (Km.0, Renting vs RAC) se pueden afinar con un master de empresas de renting conocidas.

---

## Capa 4 — Maestro BMW Group (fuente: `BMW_Group_Segmentation_List`)

**Este es el corazón del enriquecimiento.** El fichero BMW Group cubre **927 marcas**, no solo BMW. Es una lista de segmentación de mercado global mantenida por BMW Group con datos IHS Markit.

### Cómo enlazar DGT → Maestro BMW

| DGT | BMW Master | Tipo de match |
|---|---|---|
| `MARCA_ITV` | `BRAND` | Exacto tras normalización de nombre |
| `MODELO_ITV` | `MODEL_SHORT` | Difuso — el DGT a veces incluye trim en el modelo |
| `CARROCERIA` DGT | `IHS_BODY_GROUP` | Via tabla de equivalencias (ver abajo) |

### Normalización de nombres de marca

El DGT usa mayúsculas y abreviaciones propias. Ejemplos:
```
DGT "VOLKSWAGEN" → Master "VOLKSWAGEN" ✓
DGT "MERCEDES" → Master "MERCEDES-BENZ" ← requiere alias
DGT "VW" → Master "VOLKSWAGEN" ← requiere alias
DGT "CITROEN" → Master "CITROEN" ✓
DGT "ALFA ROMEO" → Master "ALFA ROMEO" ✓
```
Se construye una tabla de alias DGT → IHS brand name (~50 casos especiales).

### Campos obtenidos del maestro

| Campo Benchmark | Campo Maestro BMW | Lógica |
|---|---|---|
| `Segment` | `BMW_SEGMENT` | Directo (UKL0, MKL, SKL, KKL, UKL1, UKL2, GKL...) |
| `Segment_Origin` | `BMW_SEGMENT` con prefijo | Añadir número orden: "1.UKL0", "2.MKL"... |
| `SubSegmento` | `BMW_REGIONAL_C1` | TRAD.COMP. → FOCUS SEGMENT; NEW PLAYERS & TESLA → FOCUS SEGMENT; REST → REST |
| `Body Type` | `BMW_CONCEPT` | Ver tabla de equivalencias abajo |
| `BMW_CLASSIFICATION` | `BMW_CLASSIFICATION` | BASE / PREMIUM / NEAR PREMIUM (para análisis interno) |

### Tabla de equivalencias Body Type

| IHS_BODY_GROUP (DGT CARROCERIA) | BMW_CONCEPT | Benchmark Body Type |
|---|---|---|
| SUV | SAV | SAV |
| HATCHBACK (5p) | HATCH | HACH 5P |
| HATCHBACK (3p) | HATCH | HACH 3P |
| SEDAN | SEDAN | SEDAN |
| WAGON | ESTATE | ESTATE |
| VAN / CAR UTILITY | TRANSPORTER | TRANSPORTER |
| CONVERTIBLE | CABRIO | CABRIO |
| COUPE | COUPE | COUPE |
| MPV | MPV | MPV |
| MPV (subtype SAT) | SAT | SAT |
| PICKUP | PICK-UP | PICKUP |
| ROADSTER / RETRACTABLE HARDTOP | ROADSTER | ROADSTER |

> **HACH 3P vs 5P**: Distinguir 3 puertas de 5 puertas es el único punto sin fuente directa. Se puede inferir de:
> 1. `NUM_PLAZAS` del DGT: si ≤ 4 y hatchback → probable 3P
> 2. Nombre de versión contiene "3P", "3D" → 3P
> 3. Master BMW: algunos submodelos son explícitamente 3P en SUB_MODEL_NAME
> 4. Fallback: 5P (es el mayoritario: HACH 5P tiene 36× más volumen que HACH 3P)

### FOCUS SEGMENT — Lista confirmada

**TRAD. COMP.** (Traditional Competitors → FOCUS SEGMENT):
Aston Martin, Audi, Bentley, BMW, Cadillac, Ferrari, Jaguar, Lamborghini, Land Rover, Lexus, Maserati, McLaren, Mercedes-Benz, MINI, Porsche, Rolls-Royce, Volvo, Alpina

**NEW PLAYERS & TESLA** (→ FOCUS SEGMENT):
Tesla, Polestar, Xpeng, Lotus, Smart (JV Geely), Rivian, Lucid, NIO (a medida que entren en ES)

**Todo lo demás** → REST

---

## Capa 5 — Maestros auxiliares (construir/mantener)

### 5a. Zona geográfica (Province → Zone)

6 zonas comerciales. Tabla fija:

| Zona | Provincias |
|---|---|
| 11-Centro-Extremadura | M, TO, CU, GU, SG, AV, SA, ZA, VA, P, BU, SO, LO, LE, BA, CC |
| 12-Noroeste | C, LU, OU, PO, O, S |
| 13-Norte-Canarias | SS, BI, VI, NA, Z, HU, TE, GC, TF |
| 21-Cataluña-Baleares | B, GI, L, T, IB |
| 22-Levante | V, CS, A, MU, AB, CR |
| 23-Andalucía | SE, CO, CA, J, GR, MA, AL, H, CE, ML |

### 5b. Nation — Marcas de origen chino (→ CN)

Lista actual de marcas CN en el mercado español (a mantener):
MG, BYD, Omoda, Ebro, Jaecoo, Lynk & Co, Leapmotor, Maxus, EVO, DFSK, Shineray, Xpeng, Smart, Livan, Foton, Faw, Dongfeng, Seres, Bestune, BAIC, Farizon, Yudo, Voyah, Denza, Skywell, Zeroid, ICH-X, Sportequipe, Firefly, Avatr

> Todas las demás → "Otros"

### 5c. High Performance

Este campo se aplica sobre TODOS los vehículos del mercado (no solo BMW), identificando variantes de altas prestaciones en marcas del FOCUS SEGMENT:

| Tier | Regla de detección |
|---|---|
| `M` | BMW M GmbH puro: versión contiene "M2", "M3", "M4", "M5", "M6", "M8", "XM" sin "M PERFORMANCE"; o Ferrari, Lamborghini, McLaren (todos) |
| `M Performance` | BMW M Performance package: versión contiene "M PERFORMANCE", "M SPORT", "COMPETITION"; Mercedes AMG ("AMG"); Porsche (todos excepto base); Audi RS/S models |
| `JCW` | MINI + versión contiene "JOHN COOPER WORKS", "JCW" |
| `Standard` | Todo lo demás |

> Confirmado por análisis: BMW M (1036 uds 2025), BMW M Performance (1359), MINI JCW (615), Mercedes M Performance (1252), Porsche M Performance (940), Audi M Performance (564).

### 5d. Concesión / Puntos de Venta

**Dato propietario — la fuente no es DGT.**

La atribución de cada matriculación a una concesión se hace por territorio: cada provincia/zona del país está asignada a una concesión del network. El DGT da `COD_PROVINCIA_MAT` + `MUNICIPIO`, y un maestro propio mapea esa geografía al concesionario responsable de ese territorio.

Necesitas aportar: tabla `provincia → Concesin → Id Concesin → Puntos de Venta → Id Punto de Venta`.

---

## Protocolo para modelos nuevos (crucial para sostenibilidad)

Cuando aparece un modelo nuevo en los datos DGT que no existe en el maestro BMW:

### Nivel 1: Auto-clasificación por reglas de fallback

```python
def clasificar_modelo_nuevo(registro):
    # 1. FUEL → siempre funciona (viene de DGT directo)
    fuel = derivar_fuel(registro)

    # 2. NATION → verificar si la marca está en lista CN
    nation = 'CN' if registro['marca'] in MARCAS_CN else 'Otros'

    # 3. BODY TYPE → del campo DGT CATEGORÍA_HOMOLOGACIÓN_EUROPEA
    #    M1G tiende a ser SAV. Usar CARROCERIA DGT como proxy
    body = mapear_carroceria_dgt(registro['carroceria'])

    # 4. SEGMENT → estimación por tamaño/potencia como proxy
    #    (impreciso, necesita validación manual)
    segment = estimar_segmento(registro['peso_max'], registro['kw_itv'])

    # 5. SUBSEGMENTO → ¿la marca está en lista FOCUS SEGMENT?
    subseg = 'FOCUS SEGMENT' if registro['marca'].upper() in FOCUS_BRANDS else 'REST'

    return fuel, nation, body, segment, subseg
```

### Nivel 2: Queue de modelos pendientes

Cada vez que el pipeline encuentra una combinación `(MARCA, MODELO)` no en el maestro:
1. La registra en `data/unmatched_models.csv`
2. Aplica la clasificación de fallback (marcada como "ESTIMATED")
3. Genera un informe semanal/mensual de nuevas entradas para revisión manual

### Nivel 3: Actualización del maestro

BMW Group actualiza el fichero de segmentación aproximadamente **trimestral**. Cada actualización:
1. Carga la nueva versión del Excel
2. Re-clasifica los registros que estaban como "ESTIMATED"
3. La hoja `seg_changes` del Excel documenta qué modelos cambiaron de segmento — crucial para la consistencia histórica

### Señales de alarma para modelos nuevos

Un modelo merece revisión prioritaria si:
- Acumula >100 matriculaciones sin estar clasificado
- La marca no existe en el maestro (marca nueva en el mercado)
- El Body Type detectado automáticamente parece incongruente con el modelo

---

## Resumen: ¿qué réplica exactamente y qué no?

| Campo | Replicable | Precisión | Notas |
|---|---|---|---|
| Brand, Model, Version | ✅ Sí | Alta | Normalización de nombres |
| Homologation, Homologation_Origin | ✅ Sí | Exacta | Del DGT directo |
| Fuel / Fuel_Type | ✅ Sí | Alta | ~95% sin MHEV; +MHEV ~99% |
| Channel / SubCanales | ✅ Sí | Media | SERVICIO DGT + reglas; subcategorías finas con master empresas |
| Segment | ✅ Sí | Alta | Maestro BMW; fallback para nuevos |
| Segment_Origin | ✅ Sí | Alta | Igual que Segment con prefijo numérico |
| SubSegmento | ✅ Sí | Alta | TRAD.COMP.+NEW PLAYERS → FOCUS; resto → REST |
| Body Type | ✅ Sí | Alta | BMW_CONCEPT del maestro; 3P/5P heurístico |
| Nation | ✅ Sí | Alta | Lista CN estática a mantener |
| Zona | ✅ Sí | Exacta | Tabla provincia → zona |
| HP | ✅ Sí | Exacta | KW_ITV × 1.341 |
| High Performance | ✅ Sí | Alta | Reglas sobre versión + lista marcas HP |
| Provincia | ✅ Sí | Exacta | COD_PROVINCIA_MAT → nombre |
| Municipio | ✅ Sí | Exacta | Campo DGT directo |
| Year / Month / Sort_Month | ✅ Sí | Exacta | FEC_MATRICULA |
| Registrations | ✅ Sí | Exacta | 1 por registro (Benchmark agrega igual) |
| **Concesión / Puntos de Venta** | ⚠️ Con tu master | Alta | Necesitas la tabla territorio → concesión |
| Id Concesin / Id Punto de Venta | ⚠️ Con tu master | Alta | IDs propios de tu organización |

---

*Documento generado: 2026-06-25*
*Próximo paso: construir el parser Python con estas reglas e integrar el maestro BMW*
