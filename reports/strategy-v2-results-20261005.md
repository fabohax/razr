# Refinamiento MACD: investigación y resultados

Fecha: 5 de octubre de 2026, America/Lima.

**Conclusión: la estrategia nueva filtra las compras contra el impulso de 5m/15m del ejemplo, pero no demostró rentabilidad después de comisiones. No hay parámetros validados para activar esta estrategia en el bot.**

## Evidencia de las capturas

Descargamos datos confirmados de OKX hasta el cierre de las 21:14 del 5 de octubre (Lima). Reconstruimos los indicadores usando el historial anterior. Los cruces alcistas de 1m cercanos a las capturas quedan descartados:

| Cierre de señal, Lima | Histograma 1m | Impulso 5m | Impulso 15m | Filtro 1h | Entrada v2 |
| --- | ---: | --- | --- | --- | --- |
| 20:51 | 0.453 | Bajista | Bajista | Pasa | Descartada |
| 20:55 | 0.679 | Bajista | Bajista | Pasa | Descartada |

La captura por sí sola no establece el origen de B/S. Esta auditoría identifica cruces de mercado próximos a esas horas, no certifica que las etiquetas sean del bot. Una recuperación del histograma de 1m puede ocurrir mientras su línea MACD continúa negativa. Además, las últimas velas visibles estaban en formación; los filtros sólo usan velas cerradas.

## Fuentes consultadas

- [Documentación de Elder Impulse en StockCharts](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/elder-impulse-system): EMA13 e histograma para impulso; contexto de periodos superiores. Se adapta la idea, no se afirma equivalencia con el sistema original.
- [MACD-V, Alex Spiroglou / NAAIM, 2022](https://www.naaim.org/wp-content/uploads/2022/05/MACD-V-Alex-Spiroglou-WEB.pdf): normalización por ATR y bandas de impulso. Su ejemplo histórico DAX no valida este scalping de BTC.
- [MACD MTF de JoseMetal](https://www.tradingview.com/script/GxAhH0i3/): reglas documentadas de concordancia entre periodos y SL/TP por ATR; código protegido y recomendación de periodos mucho mayores. No se copió código ni se verificó su afirmación de rentabilidad.
- [Deprez y Frommel, 2024](https://www.sciencedirect.com/science/article/pii/S1059056024003010): resultados favorables fuera de muestra en carteras de reglas BTC, con costes y control de múltiples pruebas. No demuestra una estrategia copiable para estas condiciones exactas.

## Reglas de la variante sencilla

1. **1h:** precio sobre EMA50 ascendente; veto si EMA13 e histograma caen simultáneamente.
2. **15m:** veto de impulso bajista; precio sobre EMA50 y EMA20 sobre EMA50.
3. **5m:** histograma recuperándose y precio sobre EMA20 tras un retroceso que la tocó dentro de seis velas.
4. **1m:** segundo cierre positivo del histograma tras el cruce; cierre sobre el máximo de la vela del cruce y EMA20; volumen no inferior al promedio previo de 20 velas.
5. Entrada a la apertura siguiente; máximo cuatro entradas por día UTC; cooldown 60 minutos; no superposición; no mínimo diario. Sólo largos.

**SL:** bajo el mínimo de tres velas cerradas de 5m, con buffer de 0.1 ATR; como mínimo a una distancia de 1 o 1.5 ATR respecto al cierre de señal. Congelado al emitir la señal. Se rechaza si la distancia desde el fill no queda entre 0.10% y 0.35%.

**TP:** objetivo calculado para 1:1 o 1.5:1 neto después de comisiones y slippage de la salida por SL. Piso bruto 0.30%; techo 0.80%. No se ajusta el stop hacia dentro de la estructura para forzar el trade.

Se mantuvo el límite de **17 minutos desde el fill**. Con SL de 0.20%, las tasas confirmadas y 1bp de slippage en el stop implican aproximadamente TP 0.38% para 1:1 neto o 0.535% para 1.5:1 neto. Son cálculos de relación, no parámetros con rentabilidad demostrada.

## Primer experimento estricto

Ocho variantes predefinidas: Elder impulse o filtro MACD-V, dos multiplicadores ATR y dos relaciones netas. Todas exigían impulso favorable simultáneo en varios periodos. Sólo una operación en 45 días de desarrollo; ninguna en los 35 días siguientes. Su única operación ganadora no es evidencia de rentabilidad. [Reporte íntegro](strategy-v2-market-20261005.json).

## Segundo experimento: veto de impulso

La variante sencilla se definió después de observar la escasez de operaciones del experimento estricto. Se probaron cuatro combinaciones sólo para seleccionar según desarrollo; su evaluación posterior es **exploratoria**, porque esas fechas ya fueron observadas. No es un nuevo holdout independiente.

| ATR mínimo | Relación neta objetivo | Trades desarrollo | Retorno cuenta | Profit factor |
| ---: | ---: | ---: | ---: | ---: |
| 1.0 | 1.0:1 | 33 | -2.54% | 0.404 |
| 1.0 | 1.5:1 | 33 | -2.99% | 0.300 |
| 1.5 | 1.0:1 | 34 | -3.25% | 0.306 |
| 1.5 | 1.5:1 | 34 | -3.35% | 0.284 |

La combinación 1 ATR / 1:1 neto fue la menos negativa; se congeló antes de ejecutar las evaluaciones de esta segunda prueba. No se eligió por resultado de esas evaluaciones.

| Periodo 2026, UTC | Trades | Retorno cuenta | Trades rentables | Salidas por tiempo | Entradas/día |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 abril–15 mayo | 33 | -2.54% | 27.3% | 22 | 0.73 |
| 16–31 mayo | 4 | -0.14% | 25.0% | 4 | 0.25 |
| 1–19 junio | 4 | -0.23% | 25.0% | 4 | 0.21 |
| 1 julio–4 octubre, datos reutilizados | 63 | -6.21% | 19.0% | 47 | 0.66 |

En desarrollo el SL mediano fue **0.181%** y el TP mediano **0.361%**. No son un SL/TP óptimos establecidos. En mayo y junio las ocho operaciones salieron por tiempo antes de TP/SL; esos resultados apuntan a la dificultad de alcanzar objetivos que cubran costes en 17 minutos.

En desarrollo, P&L bruto después del slippage modelado: +$5.65; comisiones: $31.02; P&L neto: −$25.37. En los datos reutilizados de julio–octubre también hubo pérdida bruta. El filtrado por sí solo no estableció una ventaja sostenible.

## Sensibilidad del tramo 1–19 junio

| Caso | Trades | Retorno cuenta |
| --- | ---: | ---: |
| 2bps_slippage | 4 | -0.31% |
| 1minute_entry_delay | 6 | -1.06% |
| taker_tp | 4 | -0.23% |

Los cambios de latencia pueden cambiar qué entradas pasan los límites del stop; por eso la cantidad de trades puede variar. Los objetivos se vuelven a calcular según los costes de cada escenario; no se reelige la estrategia.

## Datos, supuestos y verificación

- Datos adicionales: 132,480 velas consecutivas confirmadas de OKX BTC-USDT-SWAP, 20 marzo–20 junio exclusive, sin minutos faltantes. Se excluye el calentamiento previo al 1 de abril.
- Los nuevos intervalos preceden a julio–octubre, que ya influyó en la idea de refinamiento. Toda la investigación es retrospectiva; requiere una prueba futura para establecer una ventaja.
- $1,000 iniciales por periodo; 1% de la cuenta como margen a 100x. Los retornos de la tabla son de cuenta, no de todo el capital apalancado 100x. No sumar los porcentajes de periodos como si fueran una sola curva.
- Maker 0.02%; taker 0.05%; 1bp de slippage adverso por fill taker. TP maker exige negociación por encima del límite; no modela cola real. Orden intrabar desconocido: SL primero.
- Funding, liquidación, profundidad del libro y redondeo de contratos no incluidos. No hubo posición abierta al final de los cuatro periodos mostrados.
- **137 pruebas pasaron**, incluyendo confirmación, rechazo de impulso bajista, invariancia ante precios futuros, SL estructural, cálculo exacto de relación neta y compatibilidad con v1.

## Archivos y reproducción

- [Reglas y diseño de investigación](../STRATEGY_V2.md).
- [Reporte completo de variante sencilla](strategy-v2-censored-20261005.json), con todos los trades y auditoría del ejemplo.
- [Trades de todos los periodos en CSV](strategy-v2-trades-20261005.csv).

```bash
.venv/bin/python run_strategy_v2.py data/okx-btc-usdt-swap-1m-20260320-20260620.json \
  --families censored --output reports/strategy-v2-censored-20261005.json \
  --reused-data data/okx-btc-usdt-swap-1m-20260620-20261005.json \
  --screenshot-data data/okx-btc-usdt-swap-1m-screenshot-20261006.json
```

Las reglas se implementaron en el backtester. La lógica del bot en vivo sigue sin integrar estos filtros. No se activó una estrategia con pérdidas como si fuera rentable.
