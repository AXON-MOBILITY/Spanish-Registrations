# Master de puntos de venta y proxy geografico

## Alcance

El fichero masters/master_dealer_points.csv contiene puntos de venta publicos y
trazables. No demuestra que una matriculacion se vendiera en ese punto. La asignacion
del auditor es una estimacion por proximidad entre el codigo postal del domicilio DGT
y los puntos conocidos de la marca.

La auditoria procesa todas las marcas observadas, aunque no exista una red localizable.
En ese caso emite unmapped_brand y deja el nombre vacio. Nunca inventa un concesionario.

Solo se procesa canal Private. Corporate, RAC, Renting y Demo quedan fuera porque el
domicilio registral puede ser una sede, una campa o una operadora de flota.

## Fuentes y confianza

El master general actual contiene 1.671 puntos de 9 marcas, todos procedentes de
localizadores oficiales:

| Confianza de fuente | Puntos | Uso |
|---|---:|---|
| official | 1.671 | Localizadores oficiales de Toyota, Renault, Dacia, Hyundai, Kia, SEAT, CUPRA, Nissan y Lexus |

Cada fila conserva source_kind, source_confidence, source_url y retrieved_date. No se
publican puntos obtenidos de OpenStreetMap, directorios comerciales ni nombres
inferidos. En Lexus, la identidad y direccion proceden del localizador oficial y la
coordenada se aproxima mediante el centroide publico de su codigo postal.

BMW mantiene ademas su master territorial y auditoria especifica, con mejor cobertura
que el fallback general de coordenadas.

## Esquema

brand, dealer_id, dealer_name, point_of_sale, point_of_sale_id, address, postcode,
city, province, latitude, longitude, source_kind, source_confidence, source_url y
retrieved_date.

No se guardan telefonos, correos, NIF ni datos personales.

## Regeneracion

    python scripts/build_dealer_points.py

Para regenerar las nueve redes oficiales:

    python scripts/build_dealer_points.py --official-only

Los extractores oficiales aplican reintentos y minimos de integridad. La regeneracion
falla si una respuesta queda por debajo de sus umbrales, para evitar reemplazar el
master con una descarga parcial.

## Estados de auditoria

    python scripts/audit_multibrand_dealer_proxy.py --yyyymm 202606

- estimated_nearest: punto mas cercano con separacion suficiente.
- dealer_resolved_pos_ambiguous: grupo estimado, punto concreto ambiguo.
- ambiguous_dealer: dos grupos cercanos; no se publica nombre.
- too_far: ningun punto defendible dentro de 120 km.
- unmapped_brand: no existe una red trazable para esa marca.
- missing_centroid o invalid_postcode: no puede calcularse la distancia.

El nombre siempre debe mostrarse como concesionario estimado, nunca como vendedor
real o confirmado.

## Auditoria completa de junio de 2026

Sobre 217.005 registros DGT se encontraron 56.481 matriculaciones Private de 74
marcas. Se resolvio un nombre estimado para 26.956: cobertura del 47,7%.

| Resultado | Matriculaciones |
|---|---:|
| Nombre o grupo estimado | 26.956 |
| Ambiguo entre concesionarios | 22.339 |
| Punto conocido demasiado lejano | 6.946 |
| Marca sin red trazable | 227 |
| Sin centroide postal | 13 |

Estas cifras corresponden a una auditoria anterior y no deben interpretarse como la
cobertura actual. La cobertura se recalcula al reconstruir el historico con el master
oficial vigente. Las marcas sin red oficial integrada se conservan como
unmapped_brand. La cobertura mide disponibilidad del proxy, no exactitud. Sin ventas
observadas de la marca o del DMS no puede calcularse accuracy.

## Filtro del dashboard

El ETL genera dgt_dealer_YYYYMM.csv y dgt_dealer_daily_YYYYMMDD.csv mientras
todavia dispone del codigo postal del domicilio. El dashboard los compacta en
public/data/records_dealer.json y solo descarga ese fichero cuando se usa el
selector Dealer (est.).

El filtro afecta a Overview, Ranking y Channel & Monthly, y se puede combinar con
marca, modelo, carroceria y provincia. Solo contiene asignaciones resueltas del
canal Private; los estados ambiguos, lejanos o sin master quedan fuera.

El repositorio incluye junio de 2026 como primer mes. Despues de fusionar el cambio,
hay que ejecutar DGT auto sync en modo de reconstruccion completa para generar la
dimension dealer en todo el historico disponible.
