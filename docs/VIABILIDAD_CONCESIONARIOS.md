# Viabilidad de atribucion de matriculaciones a concesionario

Fecha de auditoria: 2026-07-16  
Base auditada: origin/main (6674a496)  
Alcance: altas DGT, Simmix usado por el proyecto, indice VIN10 y maestro BMW.

## Respuesta ejecutiva

**No es posible atribuir de forma real y verificable cada matriculacion publica de la DGT a un concesionario o punto de venta con los datos actuales.** El registro publico tiene 69 campos y ninguno identifica vendedor, concesionario, punto de venta, NIF del vendedor, gestor o expediente comercial. La localizacion disponible es el domicilio del vehiculo/titular y la provincia de tramitacion, no el lugar de venta.

Tampoco resuelven el problema por si solos:

- FABRICANTE_ITV, FABRICANTE_VEHICULO_BASE o un maestro de NIF de importadores: identifican fabricante/importador, no vendedor.
- CODIGO_ITV: es un codigo tecnico ITV, no una estacion ni un concesionario.
- COD_PROVINCIA_MAT: indica la provincia donde se matriculo/tramito, no el punto de venta.
- El prefijo de bastidor publico o el actual dgt_vin10_index.txt: no es un identificador unico y no contiene una relacion VIN-concesionario.
- Los exports Simmix usados por el repositorio: aportan producto, canal y validacion agregada, no una dimension dealer/POS enlazable por unidad.

La unica salida defendible con los activos actuales es una **atribucion geografica proxy**, etiquetada como tal. Para BMW Private puede pilotarse la asignacion territorio/POS de masters/master_concesin_bmw.csv usando el municipio de domicilio. Esa salida no debe mostrarse ni venderse como concesionario de venta real.

## Escala de evidencia

| Metodo | Significado | Puede llamarse concesionario real |
|---|---|---:|
| reported | El dealer/POS informa la operacion desde DMS/CRM | Si, sujeto a controles |
| contractual_vin_match | Un feed autorizado relaciona VIN17 con dealer/POS | Si, sujeto a contrato y calidad |
| geo_territory_proxy | Se asigna el domicilio a un territorio comercial | **No** |
| unknown | No hay evidencia suficiente | No |

No se debe convertir una probabilidad o una regla territorial en una afirmacion factual.

## Diccionario completo del registro DGT (714 caracteres)

Fuente primaria: [diseno de registro de matriculaciones DGT](https://www.dgt.es/export/sites/web-DGT/.galleries/downloads/dgt-en-cifras/matraba/MATRICULACIONES_MATRABA.pdf). Las posiciones son inclusivas y 1-indexadas; los slices Python usan inicio 0-indexado y fin exclusivo. La suma de longitudes es exactamente 714.

| # | Campo | Posicion | Long. | Descripcion y valor para atribucion |
|---:|---|---:|---:|---|
| 1 | FEC_MATRICULA | 1-8 | 8 | Fecha de matriculacion. No identifica vendedor. |
| 2 | COD_CLASE_MAT | 9 | 1 | Clase de matricula. No. |
| 3 | FEC_TRAMITACION | 10-17 | 8 | Fecha de tramitacion. No. |
| 4 | MARCA_ITV | 18-47 | 30 | Marca. Dimension de producto. |
| 5 | MODELO_ITV | 48-69 | 22 | Modelo. Dimension de producto. |
| 6 | COD_PROCEDENCIA_ITV | 70 | 1 | Nacional, importacion no UE, subasta o UE. No identifica importador/vendedor. |
| 7 | BASTIDOR_ITV | 71-91 | 21 | Ocho primeros caracteres y resto enmascarado con asteriscos. No es VIN17 unitario. |
| 8 | COD_TIPO | 92-93 | 2 | Tipo de vehiculo. No. |
| 9 | COD_PROPULSION_ITV | 94 | 1 | Propulsion. No. |
| 10 | CILINDRADA_ITV | 95-99 | 5 | Cilindrada. No. |
| 11 | POTENCIA_ITV | 100-105 | 6 | Potencia fiscal. No. |
| 12 | TARA | 106-111 | 6 | Tara. No. |
| 13 | PESO_MAX | 112-117 | 6 | Peso maximo. No. |
| 14 | NUM_PLAZAS | 118-120 | 3 | Numero de plazas. No. |
| 15 | IND_PRECINTO | 121-122 | 2 | Vehiculo precintado. No. |
| 16 | IND_EMBARGO | 123-124 | 2 | Vehiculo embargado. No. |
| 17 | NUM_TRANSMISIONES | 125-126 | 2 | Numero de transmisiones. No. |
| 18 | NUM_TITULARES | 127-128 | 2 | Numero de titulares. No identifica al titular. |
| 19 | LOCALIDAD_VEHICULO | 129-152 | 24 | Localidad del domicilio. Solo proxy geografica. |
| 20 | COD_PROVINCIA_VEH | 153-154 | 2 | Provincia de domicilio. Solo proxy geografica. |
| 21 | COD_PROVINCIA_MAT | 155-156 | 2 | Provincia donde se matriculo. Tramite, no venta. |
| 22 | CLAVE_TRAMITE | 157 | 1 | Tipo de tramite. No. |
| 23 | FEC_TRAMITE | 158-165 | 8 | Fecha del tramite. No. |
| 24 | CODIGO_POSTAL | 166-170 | 5 | CP de domicilio. Solo proxy geografica. |
| 25 | FEC_PRIM_MATRICULACION | 171-178 | 8 | Primera matriculacion. No. |
| 26 | IND_NUEVO_USADO | 179 | 1 | Nuevo/usado. Scope, no dealer. |
| 27 | PERSONA_FISICA_JURIDICA | 180 | 1 | Tipo de titular, sin identidad. Util para canal. |
| 28 | CODIGO_ITV | 181-189 | 9 | Codigo ITV tecnico. No es concesionario. |
| 29 | SERVICIO | 190-192 | 3 | Servicio del vehiculo. Util para canal. |
| 30 | COD_MUNICIPIO_INE_VEH | 193-197 | 5 | Municipio INE de domicilio. Mejor clave para proxy. |
| 31 | MUNICIPIO | 198-227 | 30 | Nombre del municipio de domicilio. Proxy si falta INE en el maestro. |
| 32 | KW_ITV | 228-234 | 7 | Potencia neta maxima. No. |
| 33 | NUM_PLAZAS_MAX | 235-237 | 3 | Plazas maximas. No. |
| 34 | CO2_ITV | 238-242 | 5 | Emisiones CO2. No. |
| 35 | RENTING | 243 | 1 | Indicador de renting. Util para canal, no dealer. |
| 36 | COD_TUTELA | 244 | 1 | Tutela del titular. Innecesario y sensible para este objetivo. |
| 37 | COD_POSESION | 245 | 1 | Tipo de posesion. No. |
| 38 | IND_BAJA_DEF | 246 | 1 | Baja definitiva. No. |
| 39 | IND_BAJA_TEMP | 247 | 1 | Baja temporal. No. |
| 40 | IND_SUSTRACCION | 248 | 1 | Sustraccion. No. |
| 41 | BAJA_TELEMATICA | 249-259 | 11 | Indicador/literal de desguace. No. |
| 42 | TIPO_ITV | 260-284 | 25 | Tipo homologado. Producto, no vendedor. |
| 43 | VARIANTE_ITV | 285-309 | 25 | Variante homologada. Producto. |
| 44 | VERSION_ITV | 310-344 | 35 | Version homologada. Producto. |
| 45 | FABRICANTE_ITV | 345-414 | 70 | Fabricante completo/completado. No es concesionario. |
| 46 | MASA_ORDEN_MARCHA_ITV | 415-420 | 6 | Masa en orden de marcha. No. |
| 47 | MASA_MAXIMA_TECNICA_ADMISIBLE_ITV | 421-426 | 6 | Masa maxima tecnicamente admisible. No. |
| 48 | CATEGORIA_HOMOLOGACION_EUROPEA_ITV | 427-430 | 4 | Categoria UE. No. |
| 49 | CARROCERIA | 431-434 | 4 | Codigo de carroceria. No. |
| 50 | PLAZAS_PIE | 435-437 | 3 | Plazas de pie. No. |
| 51 | NIVEL_EMISIONES_EURO_ITV | 438-445 | 8 | Nivel Euro. No. |
| 52 | CONSUMO_WH_KM_ITV | 446-449 | 4 | Consumo electrico. No. |
| 53 | CLASIFICACION_REGLAMENTO_VEHICULOS_ITV | 450-453 | 4 | Clasificacion del Reglamento. No. |
| 54 | CATEGORIA_VEHICULO_ELECTRICO | 454-457 | 4 | Categoria electrica. No. |
| 55 | AUTONOMIA_VEHICULO_ELECTRICO | 458-463 | 6 | Autonomia electrica. No. |
| 56 | MARCA_VEHICULO_BASE | 464-493 | 30 | Marca del vehiculo base. Fabricacion, no venta. |
| 57 | FABRICANTE_VEHICULO_BASE | 494-543 | 50 | Fabricante del vehiculo base. No es concesionario. |
| 58 | TIPO_VEHICULO_BASE | 544-578 | 35 | Tipo del vehiculo base. No. |
| 59 | VARIANTE_VEHICULO_BASE | 579-603 | 25 | Variante del vehiculo base. No. |
| 60 | VERSION_VEHICULO_BASE | 604-638 | 35 | Version del vehiculo base. No. |
| 61 | DISTANCIA_EJES_12_ITV | 639-642 | 4 | Distancia entre ejes. No. |
| 62 | VIA_ANTERIOR_ITV | 643-646 | 4 | Via anterior. No. |
| 63 | VIA_POSTERIOR_ITV | 647-650 | 4 | Via posterior. No. |
| 64 | TIPO_ALIMENTACION_ITV | 651 | 1 | Tipo de alimentacion. No. |
| 65 | CONTRASENA_HOMOLOGACION_ITV | 652-676 | 25 | Contrasena de homologacion. No. |
| 66 | ECO_INNOVACION_ITV | 677 | 1 | Indicador ecoinnovacion. No. |
| 67 | REDUCCION_ECO_ITV | 678-681 | 4 | Reduccion por ecoinnovacion. No. |
| 68 | CODIGO_ECO_ITV | 682-706 | 25 | Codigo ecoinnovacion. No. |
| 69 | FEC_PROCESO | 707-714 | 8 | Fecha de grabacion. No. |

Resultado: **0 de 69 campos observan el concesionario real**. Los campos de localidad, provincia, CP y municipio solo permiten una proxy del domicilio.

## Auditoria del parser actual

La comparacion de scripts/process_month.py con el diseno oficial identifica tres desalineaciones que conviene corregir en una tarea separada, con regresion contra totales historicos:

1. F_MODELO = (47, 77) deberia terminar en 69. El slice actual incorpora COD_PROCEDENCIA_ITV y los primeros siete caracteres de BASTIDOR_ITV. Parte del codigo parece aprovechar accidentalmente ese solapamiento para enriquecer modelos; cambiarlo sin pruebas puede alterar clasificaciones.
2. F_PLAZAS = (119, 120) lee solo el ultimo caracter del campo oficial de tres posiciones (117:120). Para turismos de una cifra suele coincidir, pero no es el campo completo.
3. invalid_itv_scope_reason() usa line_s[330:390] como fabricante. El campo oficial FABRICANTE_ITV es 344:414; el slice actual mezcla el final de VERSION_ITV y parte del fabricante.

Estas incidencias no crean un campo dealer oculto, pero impiden inferir semantica comercial a partir de offsets aproximados.

## Auditoria de las vias candidatas

### 1. DGT publica

Cobertura de matriculaciones: alta para el universo DGT.  
Cobertura dealer real: **0%**.  
Fiabilidad dealer: **nula**, porque la variable no existe.

Desde el 1 de febrero de 2025 la DGT indica que MATRABA ya no publica el bastidor completo. El acceso a VIN completo requiere acreditar interes legitimo. La [pagina oficial](https://www.dgt.es/menusecundario/dgt-en-cifras/dgt-en-cifras-resultados/dgt-en-cifras-detalle/Microdatos-de-Matriculaciones-de-Vehiculos-diarios/) lo confirma. A fecha de auditoria, el formulario enlazado devolvia 404; el contacto publicado en [datos.gob.es](https://datos.gob.es/es/catalogo/e00130502-microdatos-de-matriculaciones-de-vehiculos-diarios) es movilidad.vehiculos@dgt.es.

La [Instruccion DGT VEH 2025/02](https://www.dgt.es/export/sites/web-DGT/.galleries/downloads/muevete-con-seguridad/normas-de-trafico/VEH-vehiculos/2025/report_Instruccion-VEH-2025_02-copia.pdf) exige justificar interes legitimo, identificacion, proposito y abonar la tasa IV.1. Incluso obteniendo VIN17, la DGT seguiria sin aportar necesariamente dealer: haria falta un segundo feed autorizado VIN17-dealer/POS.

Coste: tasa DGT y coste operativo/juridico; debe confirmarse con DGT. No hay base para estimar importe ni aprobacion.

### 2. Simmix/MSI disponible en el proyecto

El codigo consume BBDD_*_PRODUCTO.csv con marca, modelo, combustible, segmento, body y canal. Los artefactos versionados derivados contienen:

- simmix_model_lookup.json: 651 combinaciones marca-modelo.
- simmix_2026_targets.json: 268 agregados marca-canal-subsegmento.
- Ningun campo dealer, POS, NIF vendedor, VIN17 o municipio utilizable para join unitario.

La validacion publicada actual tampoco soporta una imputacion fina: ETL DGT 665.956 frente a Simmix 749.707, diferencia -83.751 (-11,17%); solo 74 de 141 grupos marca-canal estan dentro de +/-2%. Esto mide alineacion de mercado, no precision dealer.

Simmix es comercial. MSI/GANVAM describe [SIMMIX-KPI Automocion](https://ganvam.es/ganvam-y-msi-impulsan-el-primer-espacio-de-datos-europeo-para-el-sector-la-distribucion-de-vehiculos/) como espacio de distribucion/posventa, pero eso no demuestra que el export contratado incluya atribucion unitaria. Hay que solicitar:

1. Diccionario y muestra de 1.000 filas.
2. Clave estable (VIN17 o ID seudonimizado comun) y dealer/POS.
3. Cobertura por marca, canal, mes y provincia.
4. Origen, deduplicacion y tasa de correccion.
5. Derechos de uso, redistribucion, retencion, auditoria y subencargo.
6. Precio de alta, licencia, usuarios y volumen API/export.

Sin esas respuestas, cobertura, fiabilidad y coste son **desconocidos**.

### 3. Indice VIN10

Auditoria de data/processed/dgt_vin10_index.txt:

| Metrica | Valor |
|---|---:|
| Entradas | 43.066 |
| Distintas | 43.066 |
| Duplicados conservados | 0 (se persiste un set) |
| Formato VIN-like de 10 caracteres | 41.950 (97,41%) |
| Longitud/caracteres no validos | 1.116 (2,59%) |

visible_dgt_vin10() busca en line_s[47:110], zona que mezcla modelo, procedencia, bastidor y campos posteriores. Ejemplos invalidos incluyen 0, 0B1E0T y 1B0S. Diez caracteres no implican VIN unico.

No puede calcularse la colision real porque el indice elimina duplicados y no conserva VIN17 de referencia. La especificacion publica solo garantiza ocho caracteres iniciales. Por tanto:

- Cobertura como clave dealer: **0%**.
- Fiabilidad como identidad unitaria: **no demostrada y estructuralmente insuficiente**.
- Utilidad valida: deduplicacion muy acotada y auditada, no atribucion comercial.

### 4. Importadores y campas

Un maestro de NIF de importadores solo seria enlazable si la fuente expusiera NIF. MATRABA publico solo indica fisica/juridica. Importador tampoco identifica que miembro de la red vendio.

Las campas (Venturada, Navacerrada, Boadilla y reglas similares del parser) corrigen canal/logistica. Una campa puede recibir vehiculos de varios dealers y no prueba la venta final.

No se encontro en origin/main un fichero versionado de NIF/importadores o campas con el que calcular cobertura adicional; las reglas observables estan embebidas en el parser. Los maestros locales no versionados deben auditarse aparte y no publicarse si contienen datos restringidos.

### 5. Fuentes externas

| Fuente | Granularidad publica | Potencial dealer | Limitacion |
|---|---|---:|---|
| ANFAC/FACONAUTO/GANVAM | Estadistica sectorial agregada | Baja | No ofrece publicamente matricula/VIN-dealer. |
| IDAE base de vehiculos | Catalogo marca-modelo/eficiencia | 0% | Producto elegible, no transaccion. |
| Expedientes MOVES | Solicitud/entidad colaboradora, restringido | Parcial | Solo tecnologias/periodos elegibles y acceso fragmentado. |
| DMS/CRM de red | Operacion/VIN17/dealer/POS | Muy alto | Acuerdos con cada marca/grupo. |
| Feed fabricante/importador | VIN17/dealer de facturacion o entrega | Muy alto | Ruta preferida, contractual y no publica. |
| Proveedor unitario | Depende del producto | Potencialmente alto | Verificar origen, licencia, cobertura y join. |

La [base publica IDAE](https://coches.idae.es/base-datos/vehiculos-elegibles-programa-MOVES-III) identifica vehiculos elegibles, no su punto de venta. MOVES reconoce operaciones de POS, pero sus expedientes no forman un censo nacional publico y completo.

## Cobertura del maestro BMW

Auditoria de masters/master_concesin_bmw.csv:

| Metrica | Valor |
|---|---:|
| Filas / pares provincia-municipio | 3.352 |
| Concesiones distintas | 56 |
| POS distintos | 112 |
| Municipios con mas de un POS en el maestro | 0 |
| Volumen historico sumado | 318.487 |
| Cobertura territorial teorica | 3.352 de 8.132 municipios (41,22%) |

El denominador procede de la [infografia municipal 2025 del INE](https://www.ine.es/infografias/infografia_censo.pdf); el [INE publica la relacion actualizada](https://www.ine.es/dyngs/INEbase/operacion.htm?c=Estadistica_C&cid=1254736177031&idp=1254734710990&menu=ultiDatos) cada ano.

Interpretacion:

- Dentro de los 3.352 pares, el maestro produce una asignacion determinista.
- 41,22% es cobertura de municipios, no de volumen BMW.
- Cero ambiguedad demuestra un mapa territorial uno-a-uno, no que el cliente comprara en ese POS.
- El ETL actual conserva provincia, pero no municipio, en dgt_prov_*; no puede calcularse retroactivamente cobertura BMW Private con los procesados. Debe medirse al leer de nuevo el raw.

## Resultado del piloto real: junio de 2026

Se ejecuto el auditor contra el fichero mensual real de la DGT de junio de 2026, aplicando el scope y las reglas de canal vigentes del pipeline.

| Metrica | Valor |
|---|---:|
| Filas DGT leidas | 217.005 |
| BMW Private elegibles | 1.148 |
| Con CP valido | 1.148 (100%) |
| Asignadas a territorio/POS | 1.060 |
| Sin asignar por municipio | 88 |
| Cobertura por volumen | **92,33%** |
| Territorios de CP generados | 680 |
| CP ambiguos entre varios POS | **0** |
| Concesiones del maestro | 56 |
| POS del maestro | 112 |

La cobertura demuestra que el metodo es tecnicamente util para un analisis territorial. No mide exactitud comercial: sin una muestra BMW/DMS no puede comprobarse si el POS territorial coincide con el vendedor real. Por tanto, la salida debe conservar la etiqueta `geo_territory_proxy` y no presentarse como venta observada del concesionario.

Queda un 7,67% sin resolver, principalmente por abreviaturas y denominaciones municipales no equivalentes entre DGT y el maestro. Puede reducirse con un catalogo INE versionado, sin relajar la regla que evita asignaciones ambiguas.

## Piloto BMW Private: proxy geografica

### Poblacion

- BMW normalizada. MINI requiere maestro y validacion propios.
- Canal Private segun reglas vigentes.
- Excluir renting, persona juridica, RAC, Corporate, campas y municipio INE invalido.
- Tres meses completos recientes; conservar raw solo durante proceso.

### Join y salida

1. Incorporar COD_MUNICIPIO_INE_VEH de cinco digitos al maestro. Es preferible a texto.
2. Mientras se completa, normalizar provincia/municipio: Unicode, tildes, articulos, guiones y denominaciones INE.
3. Left join de BMW Private por INE contra territorio BMW.
4. Emitir solo:

~~~text
dealer_method=geo_territory_proxy
dealer_id_proxy
pos_id_proxy
territory_match=matched|unmapped|ambiguous
master_version
~~~

No persistir bastidor, CP completo ni atributos innecesarios.

### Metricas y validacion

Por mes y provincia:

- coverage_volume = matched_bmw_private / eligible_bmw_private.
- Unmapped rate y top municipios no mapeados.
- Ambiguedad del maestro por INE.
- Estabilidad mensual del mix POS.
- Precision frente a BMW/DMS: exact match POS y concesion, con intervalo de confianza.

Sin ground truth solo hay coverage, nunca accuracy. Para validar uso operativo se recomienda una muestra autorizada de al menos 1.000 operaciones o tres meses completos, incluyendo grandes ciudades, dealer unico y operaciones fuera de territorio.

Criterios propuestos:

- Cobertura volumen >=95%.
- Ambiguedad <0,5%.
- Exactitud POS >=90% y concesion >=95% contra BMW/DMS para uso operativo.
- Sin ground truth, mantener siempre geo_territory_proxy y no publicar rankings de venta por dealer.

## Arquitectura para atribucion real

~~~text
DGT restringida (VIN17, fecha, vehiculo)
                 |
                 | join exacto VIN17 + controles de fecha
                 v
Feed autorizado (VIN17, dealer_id, pos_id, fecha factura/entrega)
                 |
                 v
Tabla seudonimizada de atribucion -> agregados dealer/mes/modelo/canal
~~~

Controles minimos:

1. No usar VIN parcial para join exacto.
2. HMAC de VIN con clave fuera del repositorio; no hash simple.
3. Separar zona restringida y salida agregada; acceso y auditoria.
4. Gestionar reasignaciones/cancelaciones y definir verdad: facturacion, entrega o reporting.
5. Catalogos versionados de dealer/POS y aperturas/cierres.
6. Reconciliacion mensual contra DGT/Simmix y muestreo de falsos joins.
7. Umbrales de publicacion para celdas pequenas.

## RGPD, licencia y seguridad

El VIN puede vincularse a una persona y es dato personal cuando permite identificarla directa o indirectamente. Interes legitimo no es autorizacion automatica: exige finalidad, necesidad y ponderacion.

La [AEPD resume las bases](https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/5-bases-legitimadoras-del-tratamiento/FAQ-0214-cuales-son-las-bases-de-legitimacion-para-el-tratamiento-de-datos). Sus [principios](https://www.aepd.es/derechos-y-deberes/cumple-tus-deberes/principios) incluyen finalidad, minimizacion, exactitud, conservacion, seguridad y responsabilidad demostrada. La [proteccion por defecto](https://www.aepd.es/derechos-y-deberes/cumple-tus-deberes/medidas-de-cumplimiento/proteccion-de-datos-por-defecto) limita cantidad, alcance, plazo y acceso.

Antes de datos unitarios:

- Documentar finalidad y ponderacion, o base juridica aplicable.
- Consultar DPD/asesoria; analisis de riesgos y, si procede, EIPD.
- Contratos de encargado/cesion y revision de sublicencia.
- Retencion corta del VIN y borrado verificable.
- Datos restringidos, secretos y claves fuera de GitHub.
- Publicar solo agregados con umbral minimo y sin VIN, matricula o CP.

## Decision y siguientes pasos

1. **No implementar dealer real con MATRABA publico, VIN10, fabricante/importador o campas.**
2. Corregir y probar aparte los offsets de MODELO_ITV, NUM_PLAZAS y FABRICANTE_ITV.
3. Ejecutar BMW Private como geo_territory_proxy, midiendo cobertura durante el parseo raw y sin alterar el dataset canonico.
4. Solicitar a BMW/MSI una muestra autorizada con VIN17 seudonimizable y dealer/POS para medir accuracy.
5. Solicitar a DGT el procedimiento vigente para VIN completo; el formulario enlazado esta roto.
6. Solo tras contrato, base juridica y validacion, crear una tabla real separada y agregada.

La atribucion dealer requiere una nueva fuente contractual unit-level. Con el stack actual solo es defendible un analisis territorial proxy.

## Actualizacion: cobertura de todas las marcas

La auditoria multibrand procesa las 74 marcas observadas en junio de 2026. El master
contiene 3.802 puntos para 56 marcas: 1.447 de localizadores oficiales y 2.355 de
OpenStreetMap con confianza comunitaria baja. Para las 18 marcas sin una red trazable
se emite unmapped_brand; no se completa ningun nombre por intuicion.

Sobre 56.481 matriculaciones Private, el proxy resuelve un nombre estimado para
26.956 (47,7%). Otras 22.339 quedan ambiguas, 6.946 demasiado lejos, 227 pertenecen
a marcas sin master y 13 no tienen centroide postal.

El detalle de fuentes, esquema, estados y cobertura esta en
MASTER_CONCESIONARIOS_PROXY.md. La conclusion no cambia: es cobertura de un proxy
geografico, no accuracy ni prueba del vendedor real.
