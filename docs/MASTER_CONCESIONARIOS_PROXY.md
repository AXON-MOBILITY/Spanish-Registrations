# Master oficial de puntos de venta y proxy geografico

## Alcance

El fichero `masters/master_dealer_points.csv` normaliza puntos de venta publicados
por localizadores oficiales. No demuestra que una matriculacion se vendiera en ese
punto. La asignacion de `scripts/audit_multibrand_dealer_proxy.py` es una estimacion
por proximidad entre el codigo postal del domicilio DGT y la red oficial de la marca.

Solo se procesa canal `Private`. Corporate, RAC, Renting y Demo quedan fuera porque
el domicilio registral puede ser una sede, una campa o una operadora de flota.

Redes incorporadas en esta fase:

| Marca | Puntos de venta | Fuente oficial |
|---|---:|---|
| Toyota | 150 | `https://www.toyota.es/concesionarios` |
| Renault | 344 | `https://www.renault.es/concesionarios.html` |
| Dacia | 342 | `https://www.dacia.es/concesionarios.html` |
| Hyundai | 154 | `https://www.hyundai.com/es/es/concesionarios.html` |
| Kia | 201 | `https://www.kia.com/es/buscador-concesionarios/` |
| SEAT | 176 | `https://www.seat.es/red-de-concesionarios-seat` |
| CUPRA | 88 | red oficial SEAT, puntos marcados `cupra_specialized=true` |

BMW conserva el master territorial y la auditoria especifica ya existentes. No se
mezcla con este master de coordenadas porque su fuente y su grano son distintos.

## Esquema

```text
brand
dealer_id
dealer_name
point_of_sale
point_of_sale_id
address
postcode
city
province
latitude
longitude
source_kind
source_url
retrieved_date
```

No se guardan telefonos, correos, NIF ni datos personales. Los identificadores,
nombres, direcciones y coordenadas proceden directamente de la fuente oficial.

## Regeneracion

```bash
python scripts/build_dealer_points.py
```

El extractor aplica reintentos y minimos de integridad por marca. Si una web devuelve
una respuesta parcial por debajo del umbral, falla antes de reemplazar el master.

## Auditoria

```bash
python scripts/audit_multibrand_dealer_proxy.py --yyyymm 202606
```

La asignacion usa centroides postales GeoNames y devuelve uno de estos estados:

- `estimated_nearest`: punto de venta mas cercano con separacion suficiente.
- `dealer_resolved_pos_ambiguous`: se estima el grupo, no el punto concreto.
- `ambiguous_dealer`: dos grupos cercanos; no se publica nombre.
- `too_far`: ningun punto defendible dentro de 120 km.

Una diferencia inferior a 8 km respecto al siguiente grupo se considera ambigua.
El nombre siempre debe mostrarse como **concesionario estimado**, nunca como vendedor
real o confirmado.

## Piloto junio de 2026

Sobre 217.005 registros DGT se encontraron 23.992 matriculaciones `Private` de las
siete marcas. La auditoria conjunta asigno 12.589 a un concesionario o punto oficial estimado:
cobertura del 52,5%.

| Marca | Private elegibles | Resueltas | Cobertura |
|---|---:|---:|---:|
| Toyota | 5.990 | 3.800 | 63,4% |
| Renault | 3.376 | 1.296 | 38,4% |
| Dacia | 5.439 | 2.282 | 42,0% |
| Hyundai | 2.150 | 1.103 | 51,3% |
| Kia | 3.942 | 2.552 | 64,7% |
| SEAT | 2.097 | 1.090 | 52,0% |
| CUPRA | 998 | 466 | 46,7% |

Esta cifra mide cobertura del proxy, no exactitud. Sin ventas observadas de la marca
o del DMS no se puede calcular accuracy.

## Siguiente expansion

La siguiente prioridad por volumen es Volkswagen, BYD, MG, Tesla, Peugeot/Citroen,
Skoda, Audi y Mercedes. Cada red debe incorporarse solo cuando exista una fuente
oficial reproducible con nombre, direccion y coordenadas. No se completaran nombres
mediante busquedas libres ni inferencias sobre grupos empresariales.
