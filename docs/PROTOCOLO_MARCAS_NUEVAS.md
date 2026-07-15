# Protocolo de marcas y modelos nuevos (sin Simmix)

Objetivo: cuando entra una marca o modelo nuevo en el mercado, detectarlo automáticamente, clasificarlo con criterio propio y persistir la decisión — sin depender de las BBDD del proveedor.

## 1. Detección automática (ya operativa)

- `public/data/pending_classification.json` — se regenera en cada run diario. Contiene: marcas con primera aparición en los últimos 6 meses (≥50 uds/12m) y combinaciones marca+modelo sin segmento con ≥50 uds en el año en curso, ordenadas por volumen.
- `data/processed/dgt_alerts_YYYYMM*.csv` — alertas del pipeline: `NEW_BRAND` (marca desconocida con ≥250 uds), `DRIFT` (caída/subida anómala vs baseline), `CARROCERO_UNMAPPED` (carrocero sin chasis detectado), `KM0_FALLBACK`.

Rutina recomendada: revisar `pending_classification.json` una vez por semana; nada de lo que supere ~250 uds debería quedarse más de un mes sin decisión.

## 2. Cómo decidir la clasificación

| Campo | Criterio |
|---|---|
| `seg` | Por tamaño frente a equivalentes ya clasificados: UKL0 (mini), UKL1 (B), UKL2 (C/compacto-SUV compacto), KKL (C sedán), MKL (D), SKL (E/F), GKL/GKL+ (lujo). Referencia rápida: batalla y longitud del modelo en la ficha técnica del fabricante. |
| `sub` | `FOCUS SEGMENT` si la marca es competidor premium/new-player (criterio actual: premium tradicionales + Tesla/new players); si no, `REST`. |
| `body` | SAV (SUV), SEDAN, ESTATE, HACH 5P/3P, COUPE, CABRIO, MPV, TRANSPORTER, PICKUP. |
| `hp` | Standard salvo variantes de altas prestaciones (M / M Performance / JCW según reglas de la marca). |
| `fuel_detail` | Normalmente lo deriva el DGT solo; rellenar únicamente si el fallback falla. |
| Marca china | Añadirla a la lista Nation CN si aplica (docs/METODOLOGIA_ENRIQUECIMIENTO.md §5b). |
| Carrocero nuevo | Añadir a `CARROCERO_BRANDS` en `scripts/process_month.py` (la alerta CARROCERO_UNMAPPED lo señala). |

## 3. Dónde persistir la decisión

**`masters/master_clasificacion_manual.csv`** — una fila por (brand, model), en MAYÚSCULAS como aparece en DGT:

```
brand,model,seg,sub,hp,body,fuel_detail
XPENG,G6,UKL2,FOCUS SEGMENT,Standard,SAV,Electrico
```

Este maestro se carga el ÚLTIMO en el pipeline y **sobreescribe cualquier otra fuente** (incluidos los antiguos lookups derivados de Simmix). Basta commitear el CSV: el siguiente run diario lo aplica y el modelo desaparece de la cola de pendientes.

Para que la marca aparezca también en el desplegable del dashboard antes de llegar a 250 uds: añadirla a `KNOWN_BRANDS` en `public/index.html`.

## 4. Ciclo completo

1. Alerta o cola detectan la novedad →
2. Decidir con la tabla del §2 →
3. Fila en `master_clasificacion_manual.csv` + commit →
4. El run diario reclasifica y la cola se vacía →
5. (Mientras exista Simmix) el `simmix_drift.json` confirma que la decisión cuadra.

## Pendientes detectados a fecha 2026-07-03

Omoda (4.619 uds) y Jaecoo (4.113) sin modelo canónico en 2026 — primeras candidatas para estrenar el maestro manual. Marcas nuevas recientes: Changan (1.788), Geely (397), Tiger, ICH-X, Bestune.
