# PROMPT: Extender regla Km.0 a TODAS las marcas en el pipeline DGT

## Contexto del proyecto

Estamos construyendo un pipeline que sustituye a **Benchmark** (datos de matriculaciones de pago) usando los **microdatos públicos de la DGT**. El pipeline está en `process_month.py` y genera ficheros `dgt_canal_YYYYMM.csv` (1 por mes, 2023–2025 = 36 meses) con el desglose de matriculaciones por marca y canal (Corporate / Private / RAC).

El objetivo es que los totales DGT coincidan con Benchmark por marca y canal. Para ello hay que replicar la lógica de clasificación de Benchmark.

---

## El problema: canal split en Km.0

### Cómo clasifica Benchmark (confirmado directamente con ellos)

> *"Usan estadísticas por zona donde se matricula. Cuando es en el mismo CP que los concesionarios, entonces estiman que es Corporate."*

Es decir: un vehículo con tarjeta de circulación **B00 + persona física (D)** se clasifica como **Corporate** si el municipio de matriculación coincide con el código postal de un concesionario. Esos son los coches **Km.0** (excedentes de fabricante / automadriculaciones / otros excedentes).

### Por qué hay gap

Los microdatos DGT **no tienen código postal (CP)**, solo código INE de municipio (5 dígitos: PP+MMM, donde PP=provincia, MMM=municipio dentro de la provincia). Usamos el municipio como proxy del CP.

La regla actual en `process_month.py` solo está implementada para **BMW y VOLVO**. Hay 27+ marcas más con Km.0 significativo que siguen clasificándose mal: sus B00+D en municipios de concesionario se clasifican como **Private** cuando deberían ser **Corporate**.

---

## Estado actual del delta DGT vs Benchmark (36 meses, 2023–2025)

La columna `ΔCorp = DGT_Corp − SIM_Corp`. Negativo = DGT tiene menos Corporate que Benchmark (estamos perdiendo Km.0). La columna `Km0_36m` = total Km.0 que Benchmark tiene para esa marca en 36 meses.

```
Marca              DGT_Corp  SIM_Corp   ΔCorp  DGT_Priv  SIM_Priv   ΔPriv   Km0_36m
──────────────────────────────────────────────────────────────────────────────────────
RENAULT             147,254   153,085  -5,831    95,185    95,634    -449    16,050
CITROEN              89,729    93,486  -3,757    44,519    43,504  +1,015    17,407
FORD                 76,688    81,364  -4,676    49,019    55,305  -6,286    12,020
PEUGEOT             116,034   119,518  -3,484    57,675    58,084    -409    14,277
SEAT                 64,639    67,472  -2,833    81,979    81,546    +433    14,276
OPEL                 53,326    56,701  -3,375    22,229    21,633    +596    12,025
FIAT                 35,054    37,673  -2,619    10,470    14,025  -3,555    11,295
TOYOTA              105,870   108,234  -2,364   182,151   182,450    -299    12,341
MERCEDES-BENZ        90,282    91,923  -1,641    38,625    37,773    +852    13,831
AUDI                 60,143    61,259  -1,116    35,818    35,549    +269     4,774
DACIA                25,843    27,230  -1,387   133,232   132,844    +388     2,861
NISSAN               45,995    46,751    -756    41,336    41,005    +331     5,185
VOLKSWAGEN          115,897   116,267    -370    91,677    91,433    +244     8,828
HYUNDAI              46,167    47,034    -867   110,333   109,582    +751     8,339
KIA                  46,142    46,478    -336   112,616   112,187    +429     5,248
MITSUBISHI            5,014     5,492    -478     5,843     5,241    +602     2,426
JEEP                 15,580    16,022    -442     7,720     7,363    +357     3,913
VOLVO                28,020    28,395    -375    15,253    14,624    +629     7,354  ← parcialmente corregido
DS                    3,734     6,305  -2,571       890     1,312    -422       515
ALFA ROMEO            5,227     5,439    -212       947       924     +23     1,022
CUPRA                35,583    35,720    -137    19,732    19,564    +168     5,089
MAZDA                14,279    14,391    -112    36,168    36,076     +92     2,997
MINI                 11,668    11,783    -115    12,176    12,027    +149     2,383
VOLKSWAGEN           ...
BMW                  76,776    76,836     -60    36,523    35,870    +653     6,253  ← CORREGIDO ✅
SKODA                49,529    48,344  +1,185    41,139    41,078     +61     4,526  ← sobreclasifica
```

> **Nota importante**: Algunos gaps (Ford -6k Priv, DS -2.5k Corp) tienen parte de diferencia de scope (vehículos que DGT incluye pero Benchmark no, o viceversa), no solo Km.0. Sin embargo, la mayoría del gap Corp negativo es recuperable con la regla de municipio de concesionario.

---

## Tarea a realizar

### 1. Extraer los top municipios Km.0 por marca desde Benchmark

**Ficheros Benchmark disponibles en la carpeta del proyecto:**
- `BBDD_2023_PRODUCTO.csv`
- `BBDD_2024_PRODUCTO.csv`
- `BBDD_2025_PRODUCTO.csv`

**Estructura de cada fichero** (campos relevantes, el año varía):
```
Brand_{yr}         → nombre de marca (ej. "BMW", "RENAULT", "CITROEN"...)
Channel_{yr}       → "Corporate" / "Private" / "RAC"
SubCanales_{yr}    → sub-canal Benchmark. Km.0 = contiene 'Km.0', 'Automatr', o 'Excedentes'
Municipio_{yr}     → nombre del municipio según Benchmark (texto libre, no código INE)
Registrations_{yr} → número de unidades
```

**Query equivalente a ejecutar:**
```python
# Para cada año en (2023, 2024, 2025):
# WHERE Channel == 'Corporate' AND SubCanales contiene ('Km.0' OR 'Automatr' OR 'Excedentes')
# GROUP BY Brand, Municipio
# ORDER BY Brand, total DESC
```

**Filtro clave — excluir grandes ciudades** (en ellas hay compradores privados reales que no se pueden distinguir de Km.0 sin el CP exacto):
```
EXCLUIR (población > ~80.000 hab aprox):
Madrid, Barcelona, Valencia, Sevilla, Zaragoza, Málaga, Murcia, Palma de Mallorca,
Las Palmas de Gran Canaria, Bilbao, Alicante, Córdoba, Valladolid, Vigo, Gijón,
Hospitalet de Llobregat, A Coruña, Granada, Vitoria-Gasteiz, Elche, Santa Cruz de Tenerife,
Badalona, Oviedo, Donostia-San Sebastián, Sabadell, Cartagena, Jerez de la Frontera,
Terrassa, Alcobendas, Getafe, Fuenlabrada, Leganés, Alcorcón, Mostoles, Torrejón de Ardoz,
San Sebastián de los Reyes, Rivas-Vaciamadrid, Tres Cantos, Majadahonda, Pozuelo de Alarcón
```
(En general: si el municipio aparece en el listado de grandes ciudades españolas O si la suma multi-marca de Km.0 es baja relativa a su población, descartar.)

**Municipios ya mapeados** (están en DEALER_MUN_BMW y DEALER_MUN_VOLVO del código actual — no hay que buscar su INE code de nuevo):
```
Torrelaguna → 28151        Rozas de Puerto Real → 28128    Ulea → 30040
Llers → 17093              Escorca → 07019                  Castielfabib → 46092
Villamanrique de Tajo → 28173  Moralzarzal → 28090         Bráfim → 43034
Casarrubuelos → 28036      Redován → 03111                  Relleu → 03112
La Hiruela → 28069         Riogordo → 29083                 Sant Joan d'Alacant → 03119
Yuncler → 45203            Navacerrada → 28093              Los Barrios → 11008
Ajalvir → 28002            Benidoleig → 03030               El Catllar → 43043
Erandio → 48902            Oleiros → 15058                  San Andrés del Rabanedo → 24142
Rajadell → 08178           Oiartzun → 20063                 Noain-Valle de Elorz → 31088
Lalín → 36024              Camargo → 39016                  Quart de Poblet → 46102
Hernani → 20040            Retascón → 50224                 Borox → 45021
Villares de la Reina → 37362  Cornellà de Llobregat → 08073
```

**Top municipios nuevos de alta prioridad** (con muchos Km.0 multi-marca, pendientes de mapear):
```
Robledo de Chavela   5,390 total  → INE 28125  (verificado Wikipedia)
La Hiruela / Hiruela (La)  4,719  → INE 28069  (ya en código, extender a todas marcas)
Montejaque           3,787 total  → INE 29074  (verificado Wikipedia)
Aguilar de Segarra   3,448 total  → INE 08002  (verificado Wikipedia)
Sarratella           2,713 total  → INE 12103  (verificado Wikipedia)
Patones              2,384 total  → PENDIENTE (Madrid provincia, ~450 hab)
Collado Mediano      1,636 total  → PENDIENTE (Madrid, ~4k hab, zona Sierra)
El Ronquillo         1,217 total  → PENDIENTE (Sevilla, ~1.3k hab)
Les Cabanyes         1,190 total  → PENDIENTE (Barcelona, muy pequeño)
Albatarrec           1,162 total  → PENDIENTE (Lleida, ~900 hab)
Torremocha de Jarama   976 total  → PENDIENTE (Madrid)
Navas del Rey          953 total  → PENDIENTE (Madrid, ~2.3k hab)
Collado Mediano        ...
Olaberria              529 total  → PENDIENTE (Gipuzkoa, ~800 hab)
Olías del Rey          512 total  → PENDIENTE (Toledo, ~6k hab)
Cendea de Olza         341 total  → PENDIENTE (Navarra, casi todo VW)
San Justo de la Vega   209 total  → PENDIENTE (León, Skoda+VW)
Villagonzalo Pedernales 316 total → PENDIENTE (Burgos)
Portomarin             422 total  → PENDIENTE (Lugo)
Cañada de Calatrava    409 total  → PENDIENTE (Ciudad Real)
Algar                  533 total  → PENDIENTE (Cádiz, Mercedes)
Figuerola del Camp     360 total  → PENDIENTE (Tarragona)
Reducena               176 total  → PENDIENTE (Madrid, VW+Seat+Skoda)
Galdakao               343 total  → PENDIENTE (Bizkaia)
Ojos                   149 total  → PENDIENTE (Murcia)
Valcabado              105 total  → PENDIENTE (posiblemente Zamora)
```

### 2. Buscar los códigos INE que faltan

**⚠️ CRÍTICO: Los códigos INE NO se pueden sacar de memoria — se equivocan frecuentemente.**

En sesiones anteriores se han encontrado errores como:
- Erandio: memoria → 48027, real → **48902**
- Ulea: memoria → 30042, real → **30040**
- Torrelaguna: memoria → 28149, real → **28151**
- Rozas de Puerto Real: memoria → 28125, real → **28128**
- Hernani: memoria → 20039, real → **20040**
- Ajalvir: memoria → 28004, real → **28002**
- Rajadell: memoria → 08173, real → **08178**
- Cornellà: memoria → 08076, real → **08073**

**Método que funciona: Wikipedia en español via Chrome MCP**
```
URL patrón: https://es.wikipedia.org/wiki/[NombreMunicipio]
Buscar: "INE code" con el find tool
```
Se pueden batear 4 municipios por llamada a `browser_batch`. Los resultados son fiables.

**Las APIs públicas NO funcionan** (todas bloquean el sandbox):
- INE REST API → respuestas vacías / "operación no existe"
- datos.gob.es → HTTP 404
- Wikidata SPARQL → HTTP 429
- Overpass API → HTTP 406

### 3. Modificar `process_month.py`

**Estructura objetivo**: en lugar de sets separados por marca, crear un diccionario universal:

```python
# Opción A: dict por marca (más granular, recomendada)
DEALER_MUN = {
    'BMW':      {'28151', '28128', '30040', ...},  # ya existente
    'VOLVO':    {'28151', '28128', '20040', ...},  # ya existente
    'RENAULT':  {'XXXXX', 'XXXXX', ...},           # NUEVO
    'CITROEN':  {'XXXXX', 'XXXXX', ...},           # NUEVO
    'PEUGEOT':  {'XXXXX', 'XXXXX', ...},           # NUEVO
    # ... etc para todas las marcas con Km.0 significativo
}

# Opción B: set universal (más simple)
DEALER_MUN_ALL = {'28151', '28125', '29074', '08002', '12103', ...}
# Cualquier marca + B00+D en estos municipios → Corporate
```

**Cambio en `classify()`** (actualmente solo BMW y Volvo):
```python
if s == 'B00':
    if p == 'X': return 'Corporate'
    # ANTES (solo BMW/Volvo):
    # if m == 'BMW'   and mu in DEALER_MUN_BMW:   return 'Corporate'
    # if m == 'VOLVO' and mu in DEALER_MUN_VOLVO: return 'Corporate'
    
    # DESPUÉS (todas las marcas):
    dealer_set = DEALER_MUN.get(m, set())
    if mu in dealer_set: return 'Corporate'
    # O si usas Opción B:
    # if mu in DEALER_MUN_ALL: return 'Corporate'
    
    return 'Private'
```

**Campas ya correctas** (NO tocar — ya clasifican bien):
```python
CAMPA_MUNICIPIOS_ALL = {'28169'}    # Venturada (A01)
CAMPA_MUNICIPIOS_PSA = {'28022'}    # Boadilla del Monte (A01, PSA group)
```

### 4. Reprocesar los 36 meses

```bash
python process_month.py all --force
```

El script descarga/procesa directamente desde DGT. Los ficheros `dgt_canal_YYYYMM.csv` ya existen — el `--force` los sobreescribe con la nueva lógica.

**Por timeout (45s límite por llamada bash)**, procesar en lotes de 6 meses:
```bash
python process_month.py 202301 --force && python process_month.py 202302 --force && ...
```

### 5. Validar mejora

```python
# Calcular delta DGT vs Benchmark después del reprocesado
# Para cada marca: ΔCorp = DGT_Corp - SIM_Corp
# Objetivo: llevar todos los ΔCorp lo más cerca posible de 0
# (el gap residual = grandes ciudades sin CP exacto + diferencias de scope)
```

---

## Estructura del fichero `process_month.py`

**Posiciones de campos** (0-indexed, formato fixed-width 714 chars, Latin-1):
```python
F_NUEVO_USADO = (178, 179)   # 'N' = nuevo
F_PERSONA_FJ  = (179, 180)   # 'X' = empresa, 'D' = persona física
F_SERVICIO    = (189, 192)   # 'B00'=particular/Km0, 'A01'=campa, 'A18'/'B18'=alquiler...
F_MUNICIPIO   = (192, 197)   # código INE 5 dígitos (PPMMM)
F_RENTING     = (242, 243)   # 'S' = renting
F_MARCA       = (17,   47)   # nombre de marca (texto, relleno con espacios)
F_PLAZAS      = (119, 120)   # número de plazas
F_MMA         = (111, 117)   # masa máxima autorizada en kg
```

**Lógica de clasificación actual** (función `classify(servicio, persona, renting, mun, marca)`):
- `A01` + Venturada (`28169`) → Corporate (excepto Toyota/Lexus/Audi → RAC)
- `A01` + Boadilla (`28022`) + marca PSA → Corporate
- `A01` demás → RAC
- `B00` + `X` → Corporate
- `B00` + `D` + municipio dealer → **Corporate (Km.0)** ← esto es lo que hay que extender
- `B00` + `D` demás → Private
- `A18`, `B18` → Corporate
- `B17`, `B19`, `B21`, `A04`, `A07`, `A03` → Private
- resto → Corporate si `X`, Private si `D`

---

## Resultado esperado tras el fix

Con BMW ya corregido de referencia:
- BMW tenía -336 Corp antes del fix → después -60 (mejora del 82%)
- El gap residual de BMW son grandes ciudades (Madrid, Bcn, etc.) donde no podemos distinguir

Para las demás marcas se espera mejora proporcional al Km.0 que tienen en municipios pequeños/medianos. Renault (-5.831), Citroën (-3.757), Ford (-4.676), SEAT (-2.833), Peugeot (-3.484), Opel (-3.375) son las marcas con mayor potencial de mejora.

---

## Archivos de referencia en la carpeta del proyecto

```
process_month.py              ← pipeline principal (MODIFICAR)
BBDD_2023_PRODUCTO.csv        ← Benchmark 2023 (36 meses total con 2024+2025)
BBDD_2024_PRODUCTO.csv        ← Benchmark 2024
BBDD_2025_PRODUCTO.csv        ← Benchmark 2025
dgt_canal_YYYYMM.csv (×36)   ← outputs actuales a reprocesar
delta_dgt_benchmark_36m.csv      ← delta actual por marca/canal para validación
```

---

## Resumen de la tarea en orden

1. **Leer** los CSV Benchmark → extraer top municipios Km.0 por marca (excluyendo grandes ciudades)
2. **Buscar INE codes** de los municipios nuevos via Wikipedia (Chrome MCP, batches de 4)  
   ⚠️ NUNCA usar códigos de memoria — siempre verificar en Wikipedia
3. **Actualizar** `process_month.py`: añadir `DEALER_MUN` dict con sets por marca
4. **Modificar** `classify()` para aplicar la regla a TODAS las marcas (no solo BMW/Volvo)
5. **Reprocesar** 36 meses: `python process_month.py all --force` (en lotes de 6 meses)
6. **Validar**: recalcular delta DGT vs Benchmark y verificar mejora en todas las marcas
