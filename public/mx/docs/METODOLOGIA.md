# Metodologia

## Fuente

INEGI, Registro Administrativo de la Industria Automotriz de Vehiculos
Ligeros (RAIAVL) &mdash; conjunto "Venta de vehiculos".
https://www.inegi.org.mx/datosprimarios/iavl/

Datos mensuales, cobertura **nacional** (no hay desglose por estado en
este conjunto), por marca + modelo. El pipeline descarga la serie
completa (2005&ndash;actualidad) y la filtra a 2023&ndash;2025.

A diferencia de las matriculaciones DGT que usa
[Spanish Registrations](https://spanish-registrations.vercel.app/), el
RAIAVL **no es un registro por unidad** (no hay VIN, concesionario,
persona fisica/moral, etc.) &mdash; es un agregado mensual por
marca+modelo. Eso descarta de raiz cualquier clasificacion de canal,
Km.0 o corporate como la que existe en el proyecto espanol: esa
informacion simplemente no esta en el dato de origen.

## Por que fuel_type y body_type son campos derivados

INEGI publica `TIPO` (Automoviles / Camiones ligeros) y `SEGMENTO`
(Compactos, De Lujo, Deportivos, Subcompactos, SUV's, Minivans, Pick
Ups) por fila, pero:

- No dice si un modelo es sedan, hatchback o coupe dentro de
  "Automoviles".
- No dice el tipo de combustible por modelo. El unico dato de
  hibridos/electricos que publica INEGI (`Venta de vehiculos hibridos
  y electricos`) va por **estado**, no por marca/modelo &mdash; no
  comparte clave con el fichero principal, asi que no se puede cruzar.

Mexico no tiene un equivalente al catalogo WLTP del IDAE espanol (que
sí usa `Spanish-Registrations`/MATRICULACIONES_DEALER_FIX para
combustible por version homologada). Por tanto `fuel_type` y
`body_type` aqui **no son datos oficiales**, son inferidos.

## Como se infieren (`scripts/enrich.py`)

1. **`masters/master_model_overrides.csv`**: tabla curada a mano con
   los modelos que se pueden identificar con confianza (BEV/PHEV/Diesel
   conocidos, splits Sedan/Hatchback/Coupe/Convertible, y correcciones
   a filas donde el `SEGMENTO` de INEGI no refleja bien la carroceria
   real &mdash; ej. BMW iX1 viene marcado "Automoviles/De Lujo" pero es
   un SUV).
2. **Reglas por palabra clave** sobre el propio `MODELO` (INEGI a
   menudo ya lo deja explicito: "Hatchback", "Sedan", "PHEV", "TDI",
   "HDI", "Diesel", "HEV"/"EV" como sufijo de token).
3. **Fallback a `TIPO`/`SEGMENTO`** tal como los publica INEGI
   (`SUV's`&rarr;SUV, `Pick Ups`&rarr;Pickup, `Minivans`&rarr;Van).

Cada fila queda con un campo `confidence` (`alta`/`media`/`baja`) y un
`note` opcional para que el dato dudoso sea auditable, no silencioso.
Las marcas chinas/de reciente llegada a Mexico (Changan, JAC, Foton,
Geely, Chirey, Great Wall, MOTORNATION, Jetour, Omoda, Auteco) bajan un
nivel de confianza por defecto salvo que esten en el override.

## Convencion de `fuel_type`

Igual que en `Spanish-Registrations` ("HEV cuenta como ICE"): los
hibridos no enchufables (HEV/MHEV) **cuentan como `Gasolina`** porque
usan un solo combustible y nunca se enchufan. Solo se separan:

- `Diesel`
- `Hibrido enchufable (PHEV)`
- `Electrico (BEV)`
- `Electrico (BEV con autonomia extendida)` (REEV &mdash; el motor de
  combustion solo genera electricidad, no mueve las ruedas)

Modelos con variantes mixtas que INEGI no separa (ej. Toyota RAV4
Gasolina/Hibrido/Prime bajo una sola linea "Rav4") quedan en su
combustible dominante con `confidence=media` y una `note` explicando
la limitacion &mdash; no se reparte la cifra entre variantes porque no
hay forma de saber el mix real.

## Mantenimiento

Al re-ejecutar `scripts/process_data.py` con datos de meses nuevos,
cualquier marca+modelo que no este en `master_model_overrides.csv` ni
tenga una palabra clave reconocible cae a los defaults de
`TIPO`/`SEGMENTO` con confianza `media` o `baja`. Revisar
`public/data/confidence_totals.json` tras cada actualizacion y anadir
al override los modelos nuevos que lo merezcan.
