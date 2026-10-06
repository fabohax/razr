# Estrategia v3: ruptura de rango y volumen relativo

Fecha: 5 de octubre de 2026, America/Lima.

**Conclusión: se descarta este candidato para uso en vivo. Las 12 variantes perdieron en desarrollo; la variante menos negativa también perdió en los dos periodos siguientes. El volumen redujo operaciones, pero no estableció una mejora consistente de expectativa.**

## Nueva opción explorada

- **1h:** EMA50 define contexto alcista/bajista. Se admiten largos y cortos.
- **5m:** ruptura del máximo/mínimo de las 20 velas anteriores, con buffer de 0.1 ATR y cierre cerca del extremo de la vela.
- **Volumen:** RVOL = volumen de la vela de ruptura / promedio de las 20 velas anteriores. Se excluye la vela actual del promedio. Se comparan 0 (sin filtro), 1.5 y 2.0.
- **Entrada:** apertura del siguiente minuto, con slippage adverso. No exige MACD ni propaga una señal de 5m durante varios minutos.
- **SL:** estructura de ruptura y 1.5 ATR, congelados al cerrar la señal; distancia aceptada 0.15–1.20%.
- **TP:** 1:1 o 1.5:1 netos después de comisiones y slippage del SL; objetivo bruto mínimo 0.30%, máximo 3.00%.
- **Tiempo:** comparación 60/120 minutos. Sin trailing ni break-even.
- **Sizing:** riesgo planificado máximo 0.25% de cuenta por SL; 10x; límite de 10% de cuenta en margen. Máximo cuatro entradas/día UTC y cooldown 30 minutos.

La comisión maker 0.02% y taker 0.05% se mantiene porque es un dato confirmado de la cuenta, no un parámetro que pueda optimizarse artificialmente. Slippage base: 1bp por fill taker.

## Datos y selección

- 172,800 velas confirmadas consecutivas de OKX BTC-USDT-SWAP: 20 noviembre de 2025–20 marzo de 2026 exclusivo UTC. Sin minutos faltantes; volumen en contratos.
- SHA-256: `ebe1250af3638a25e6711c0eaa15a3e618ea0469efcc829209f6257093310af2`.
- Calentamiento antes del 1 diciembre. Desarrollo: diciembre–enero (62 días). Comprobación: febrero (28 días). Comprobación final: 1–19 marzo (19 días).
- Doce combinaciones declaradas antes de ejecutar. Selección por mayor R neto realizado promedio en desarrollo, con al menos 30 operaciones. R = P&L / pérdida planificada en SL incluyendo costes.
- Estos intervalos no habían sido evaluados en v1/v2, pero la idea se diseñó tras observar datos posteriores de 2026. Es investigación retrospectiva, no una prueba forward ni evidencia independiente del historial de diseño.
- La selección se guardó antes de evaluar febrero/marzo; no se cambió usando controles ni estrés. Como todas las variantes perdieron en desarrollo, la elegida es sólo una referencia diagnóstica.

## Todas las variantes en desarrollo

| RVOL mínimo | RR neto | Tiempo máximo | Trades | Retorno de cuenta | R promedio | Profit factor |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0 | 1.0:1 | 60 min | 167 | -16.12% | -0.420 | 0.342 |
| 0.0 | 1.0:1 | 120 min | 166 | -15.31% | -0.399 | 0.409 |
| 0.0 | 1.5:1 | 60 min | 167 | -17.43% | -0.458 | 0.332 |
| 0.0 | 1.5:1 | 120 min | 166 | -16.01% | -0.419 | 0.424 |
| 1.5 | 1.0:1 | 60 min | 131 | -13.07% | -0.427 | 0.341 |
| 1.5 | 1.0:1 | 120 min | 130 | -12.32% | -0.403 | 0.410 |
| 1.5 | 1.5:1 | 60 min | 130 | -13.02% | -0.428 | 0.367 |
| 1.5 | 1.5:1 | 120 min | 129 | -12.59% | -0.416 | 0.432 |
| 2.0 | 1.0:1 | 60 min | 102 | -8.81% | -0.361 | 0.413 |
| 2.0 | 1.0:1 | 120 min | 102 | -7.97% | -0.325 | 0.496 |
| 2.0 | 1.5:1 | 60 min | 101 | -9.11% | -0.377 | 0.422 |
| 2.0 | 1.5:1 | 120 min | 101 | -8.14% | -0.335 | 0.519 |

## Variante congelada: RVOL 2×, RR neto 1:1, 120 minutos

| Periodo, UTC | Trades | Largos / cortos | Retorno cuenta | Drawdown | Trades rentables | Entradas/día |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dic 2025–ene 2026 | 102 | 48 / 54 | -7.97% | 9.20% | 34.3% | 1.65 |
| Febrero 2026 | 59 | 16 / 43 | -2.92% | 4.41% | 40.7% | 2.11 |
| 1–19 marzo 2026 | 36 | 18 / 18 | -2.39% | 2.76% | 36.1% | 1.89 |

En marzo, SL mediano **0.384%** y TP mediano **0.564%** desde el fill; no son parámetros óptimos establecidos. Hubo 13 TP, 22 SL y una salida por tiempo. P&L bruto después del slippage modelado: −$6.40; fees: $17.49; pérdida neta: $23.89 sobre $1,000 iniciales.

## Aporte del volumen en marzo, manteniendo RR y tiempo

| RVOL | Trades | Retorno cuenta | Expectativa neta por notional | R promedio | Profit factor |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0 | 62 | -3.30% | -0.0926% | -0.216 | 0.631 |
| 1.5 | 46 | -2.18% | -0.0973% | -0.191 | 0.672 |
| 2.0 | 36 | -2.39% | -0.1255% | -0.267 | 0.575 |

RVOL 2× pierde menos dinero acumulado que operar sin filtro, pero realiza menos trades y su R promedio es peor en marzo. RVOL 1.5× tuvo una pequeña ganancia bruta antes de fees (+$1.65), que los costes convirtieron en pérdida. No seleccionar un nuevo umbral a partir de esta comprobación final.

## Sensibilidad de marzo

| Cambio | Trades | Retorno cuenta |
| --- | ---: | ---: |
| 2bps_slippage | 36 | -3.37% |
| 5minute_entry_delay | 28 | -2.67% |
| taker_tp | 36 | -3.36% |
| hypothetical_1bp_funding | 36 | -2.40% |

Los targets se calculan con los costes de cada escenario. Funding stress cobra hipotéticamente 1bp a cualquiera de los dos lados en UTC 00/08/16; no es una reconstrucción de funding histórico. El escenario base no incluye funding.

## Alcance y verificación

- Los porcentajes son retornos de cuenta con sizing por riesgo y límite de exposición, no una multiplicación arbitraria del movimiento BTC por 10x/100x. Cada periodo comienza con $1,000.
- Los gaps pueden superar el riesgo planificado. El simulador usa apertura para gaps y tiempo; SL primero si TP/SL se tocan en una vela con orden desconocido.
- TP maker exige negociar más allá del límite, sin modelar cola real. No hay datos de agresores: volumen total no equivale a compras netas ni demuestra acumulación institucional.
- Se cierra cualquier posición terminal con costes taker y etiqueta END. No hubo cierres END en los tres periodos de la variante congelada.
- Drawdown usa equity a cierres de minuto e incluye coste taker estimado de cerrar posiciones abiertas. No reconstruye extremos intrabar de equity.
- No se modelan mark-price liquidation, profundidad real, redondeo de contratos ni funding histórico. No se modificó el bot en vivo.
- **153 pruebas pasaron**, incluyendo RVOL sin la vela actual, canal sin datos futuros, ejecución de largos/cortos, fees, R neto exacto, sizing por riesgo, funding stress, gaps, time stops y límites diarios.

## Fuentes y archivos

- [Definición de volumen relativo — TradingView](https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/). Nuestra ventana de 20 velas es una adaptación.
- [Gerritsen et al.: reglas técnicas de BTC](https://www.sciencedirect.com/science/article/pii/S1544612319303770). Evidencia histórica diaria para estudiar rupturas; no valida este candidato intradía.
- [Reglas y diseño del experimento](../STRATEGY_V3.md).
- [Reporte completo y todas las operaciones](strategy-v3-market-20261005.json).
- [CSV de trades de la variante congelada](strategy-v3-trades-20261005.csv).

```bash
.venv/bin/python run_strategy_v3.py data/okx-btc-usdt-swap-1m-20251120-20260320.json \
  --output reports/strategy-v3-market-20261005.json
```

No se amplió la búsqueda para rescatar un resultado favorable: las 12 combinaciones predefinidas fueron negativas. Esta exploración no encontró una ventaja rentable.
