# Modelo predictivo de matriculaciones — diseño y validación

*Diseñado y backtesteado el 2026-07-03 sobre el histórico propio (ene-2023 → jun-2026, 42 meses). Test out-of-sample: 24 meses (jul-2024 → jun-2026), ventana expandible sin fuga de información.*

## 1. Principios

1. **RAC fuera del modelo.** Su volatilidad YoY mensual es σ=28,1% frente a 7,8% del resto del mercado (medido en el backtest): es ruido de decisiones puntuales de las rentacar. Se predice el mercado **ex-RAC** y el RAC se introduce **a mano** (con un default sugerido = mismo período año anterior).
2. **Señales simples validadas, no cajas negras.** Cada componente se pesa según su error medido en backtest, y las bandas de escenarios salen de los cuantiles empíricos del error, no de opiniones.
3. **Jerarquía mercado → marca.** Primero se predice el total ex-RAC (donde el modelo es fuerte), y las marcas se derivan por cuotas (donde hay más ruido). Así los errores de marca no contaminan el total.
4. **El usuario manda.** Objetivo de mercado y ajustes por marca del usuario se integran por reconciliación, no se ignoran.

## 2. Capa 1 — Mercado ex-RAC, mes en curso

Componentes probados (MAPE out-of-sample, 24 meses):

| Componente | Fórmula | MAPE |
|---|---|---|
| A. Interanual con tendencia | `mes_año_anterior × (últimos12m / 12m_previos)` | 7,92% |
| **B. Ritmo 3m estacionalizado** | `media_3m × (índice_estacional_mes / índice_medio_3m)` | **3,63%** |
| **E. Ritmo mes anterior** | `mes_anterior × (s_mes / s_mes_anterior)` | **3,76%** |
| F. Ritmo medio 12m | `media_12m × s_mes × 12` | 5,52% |
| **Blend final** | **`0,10·A + 0,50·B + 0,40·E`** | **~3,4%** |

Óptimo del barrido en el simplex: B=0,55 + E=0,45 (MAPE 3,43%); se añade A con peso 0,10 como estabilizador estructural anti-sobreajuste (coste <0,1 pt). F no aporta (colinear con B). Cuantiles del error del blend: P10 −5,7% / P90 +4,2% → bandas Conservador ×0,94, Optimista ×1,04. Estabilidad temporal: MAPE 2,5% (24H2-25H1) vs 4,4% (25H2-26H1) — el mercado acelerado de 2026 es más difícil; la corrección de sesgo adaptativa (residuo medio 6m, hoy +1,1%) compensa.

**Componente D — curva intramensual (solo mes corriente):** proyección `MTD / %completado_esperado(día_hábil_k)`, con la curva de completado acumulada de los diarios DGT disponibles (junio-2026 en adelante; la curva se enriquece cada mes). El peso de D crece linealmente con el avance del mes: `w_D = díahábil/díashábiles_mes` (día 2 apenas pesa; día 18 domina). Fórmula final del mes en curso:

```
F_mes = w_D · D + (1 − w_D) · (0,10·A + 0,50·B + 0,40·E) × sesgo_adaptativo × (1 + ajuste_contexto)
```

**Corrección de sesgo:** el blend infraestima −1,55% de media en mercado creciente; se aplica corrección adaptativa con el residuo medio de los últimos 6 meses evaluados (recalculada sola cada mes).

## 3. Capa 2 — Resto del año (prognosis anual)

Para cada mes futuro m: `F_m = mes_m_año_anterior × tendencia12m × (1 + ajuste_contexto)`, y
`Año = YTD_real + F_mes_en_curso + Σ F_meses_restantes` (todo ex-RAC) + RAC manual anual.

## 4. Capa 3 — Marcas (cuotas ex-RAC)

Cuota prevista: `share = 0,6·cuota_3m + 0,4·cuota_12m` (MAPE medio 11% dado el total del mes, top-15 marcas). Para marcas en rampa (BYD 28% de error: el share retrospectivo siempre llega tarde) se aplica **factor de momentum**: `share ×= clip(cuota_3m/cuota_12m, 0,8, 1,5)`. Marca = cuota × forecast de mercado.

## 5. Escenarios — bandas empíricas, no inventadas

Cuantiles del error out-of-sample del blend final: P10 = −5,7%, P90 = +4,2% (asimétrico: el riesgo es más bajista que alcista).

- **Optimista** = Base × 1,04
- **Base** = F
- **Conservador** = Base × 0,94

## 6. Ajuste de contexto (entorno)

Deslizador ±5% con default documentado desde fuentes públicas, revisable cada mes. Calibración jul-2026: H1 cerró +6,2% (647.711 uds ANFAC) y la patronal apunta a 1,2–1,25M en el año; viento de cola moderado pero condicionado a incentivos → **default +1,0%** en Base (ya que la tendencia12m captura la mayor parte del crecimiento; el contexto solo añade lo no capturado).

## 7. Interacción con el usuario

- **RAC manual**: campos para RAC del mes y RAC resto de año (defaults = año anterior × tendencia).
- **Objetivo de mercado**: si el usuario fija un total anual (ej. 1.250.000), la parte futura de las marcas *no ajustadas* se reescala proporcionalmente para cuadrar con el objetivo (raking).
- **Override por marca**: si el modelo dice Mercedes 80.000 y el usuario pone 85.000, esa marca queda fijada; el resto se reequilibra contra el objetivo de mercado (si lo hay) o simplemente se recalcula el total. Los overrides se marcan visualmente como "ajuste manual".

## 8. Evaluación continua

Cada build diario guarda la prognosis del día en `data/forecast_log/` (fecha, mes objetivo, F por escenario). Al cerrar cada mes se compara contra el real → el MAPE publicado se recalcula y los pesos/bandas se recalibran con el mes nuevo. El modelo se audita a sí mismo.

## 9. Limitaciones honestas

- Curva intramensual construida solo con los diarios desde jun-2026 (la DGT no repubica diarios); mejora sola mes a mes.
- Las cuotas de marca en rampa fuerte (chinas) llevan retardo inherente ~1 mes pese al momentum.
- El RAC no se modela: es una decisión de negocio de terceros, no una serie predecible (σ 28%).
- Julio-agosto 2026: la tendencia12m aún arrastra la base débil de 2025; el ajuste de contexto existe para eso.

## Fuentes de contexto (jul-2026)

[ANFAC — cierre H1 2026 (+6,2%, 647.711 uds)](https://anfac.com/el-primer-semestre-de-2026-cierra-con-647-711-ventas-un-62-mas/) · [ANFAC — junio 2026 (+15%)](https://anfac.com/las-ventas-crecen-un-15-en-junio-con-mas-de-119-000-nuevos-turismos/) · [Faconauto — riesgo por falta de incentivos](https://www.faconauto.com/noticias-automocion/espana-arranca-2026-con-crecimiento-en-el-mercado-de-coches-nuevos-pero-la-falta-de-incentivos-amenaza-con-frenar-el-ritmo/)
