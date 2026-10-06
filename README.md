<p>
  <img src="razr.png" alt="razr-bot" width="400" style="display: block; margin: auto;">
</p>

# razr

**razr** es un bot de monitoreo en tiempo real que analiza el mercado BTC/USDT mediante el indicador MACD y emite alertas automáticas ante cruces confirmados del indicador; no predice rentabilidad ni ejecuta órdenes.

### Ciclo de operación

1. **Conexión al exchange** — Se conecta a los endpoints públicos de OKX mediante `ccxt`, sin credenciales.
2. **Obtención de datos** — Descarga las últimas N velas (OHLCV) del par y timeframe configurados (por defecto `BTC/USDT` en `1m`).
3. **Cálculo de indicadores** — Computa MACD, línea de señal e histograma con parámetros configurables (`fast`, `slow`, `signal`).
4. **Detección de cruces** — Identifica cruces alcistas (BUY) y bajistas (SELL) entre la línea MACD y la línea de señal. Evalúa únicamente velas cerradas y confirmadas; no asigna fuerza al cruce.
5. **Estado persistente** — Guarda cruces, estado EMA y trabajos de entrega en SQLite; procesa las velas nuevas en orden.
6. **Alertas** — Cuando se detecta un nuevo cruce:
   - Envía una **notificación de escritorio** (`notify-send`) con urgencia configurable.
   - Reproduce un **sonido de alerta** (`paplay` / `sox`).
   - Imprime la señal en consola con **colores** (verde = BUY, rojo = SELL) usando `colorama`.
   - Registra el evento en `razr.log`.
7. **Bucle continuo** — Espera `sleep_seconds` (por defecto 30s) y repite. Ante fallos transitorios de red/API, reintenta con backoff exponencial y jitter.
8. **Reanudación tras suspensión** — Si el equipo se suspende (por ejemplo, al cerrar la laptop), el bot detecta el salto de tiempo, reconecta con OKX, verifica frescura y procesa los cierres pendientes en orden.

## Instalación reproducible (Phase 1)

Python **3.12** es la versión soportada. Verificado en Linux con CPython
3.12.15; otras versiones y ejecutables Windows todavía no se han verificado.
`requirements.txt` fija todas las dependencias de ejecución, incluidas las
transitivas. PyInstaller y pytest están separados en `requirements-build.txt`
y `requirements-test.txt`.

Con Python 3.12 y su paquete venv instalados:

```bash
git clone https://github.com/fabohax/razr
cd razr
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Si el sistema no incluye Python 3.12, puedes instalarlo con
[uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
```

La GUI necesita Tkinter (`python3.12-tk` en distribuciones que lo separan).
Las alertas de escritorio Linux necesitan `notify-send` (`libnotify-bin`) y
`pw-play`, `paplay` o `play` para sonido; estos programas no son necesarios en modo
`--no-notifications`.

## Configuración y uso

Solo se admite **OKX spot BTC/USDT, 1m** durante esta fase. El ejemplo usa
credenciales vacías. No necesitas API keys: con `authenticated: false`, las
credenciales se ignoran. Si activas explícitamente `authenticated: true`, se
requieren las tres credenciales no vacías y sin placeholders. El bot sigue
consultando datos de mercado y no realiza órdenes.

La ubicación predeterminada es `${XDG_DATA_HOME:-$HOME/.local/share}/razr` en
Linux y `%LOCALAPPDATA%/razr` en Windows. Allí se encuentran `config.yaml` y
`razr.log` y `state.sqlite3` (estado y eventos persistentes).
Los archivos no dependen del directorio desde el que inicias el programa.
`--app-dir` permite elegir un directorio escribible; `--config` permite usar un
YAML explícito. Los argumentos de ruta relativos se resuelven al iniciar.
El antiguo `config.yaml` del repositorio solo se usa si lo seleccionas con
`--config`; no se modifica ni se migra automáticamente.

Desde el repositorio, prepara y verifica una configuración pública:

```bash
mkdir -p "$HOME/.local/share/razr"
cp config.yaml.example "$HOME/.local/share/razr/config.yaml"
.venv/bin/python main.py --check-config
.venv/bin/python main.py --once --no-notifications
.venv/bin/python main.py --no-notifications
```

También puedes verificar el ejemplo sin copiarlo:

```bash
.venv/bin/python main.py --config config.yaml.example --app-dir /tmp/razr-check --check-config
.venv/bin/python main.py --config config.yaml.example --app-dir /tmp/razr-check --once --no-notifications
```

`--check-config` valida localmente sin acceder a la red. `--once` carga y valida
metadatos del exchange, procesa un ciclo y termina sin dormir ni reintentar.
Salida: `0` = éxito, `2` = configuración inválida, `1` = fallo de arranque o de
un ciclo. Los errores de configuración se muestran antes del polling.
`--no-notifications` desactiva escritorio y sonido; consola y log siguen activos.
También puedes guardar `notifications: false` en YAML o en la GUI.

Los períodos MACD y el intervalo deben ser enteros positivos, `fast < slow`,
`limit` debe estar entre `5 * slow + signal + 2` y 300, el margen de reanudación
no puede ser negativo y la urgencia debe ser `low`, `normal` o `critical`.
El máximo de 300 corresponde al endpoint de
[velas recientes de OKX](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks).
El historial incluye calentamiento de EMA antes de establecer la primera vela elegible.

Para probar las reglas de arranque sin red ni credenciales:

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
```

Para actualizar los locks deliberadamente con uv, desde Python 3.12:

```bash
uv pip compile requirements.in --universal -o requirements.txt --python-version 3.12
uv pip compile requirements-build.in --universal -o requirements-build.txt --python-version 3.12
uv pip compile requirements-test.in --universal -o requirements-test.txt --python-version 3.12
```

## GUI mínima

Puedes usar una interfaz simple para editar `config.yaml` y ejecutar/parar el bot sin terminal:

```bash
source .venv/bin/activate
python gui.py --app-dir "$HOME/.local/share/razr"
```

Funciones incluidas:
- Editar todos los campos de configuración más comunes.
- Guardar `config.yaml` de forma atómica con las mismas reglas del CLI.
- Impedir el inicio si la validación o escritura falla.
- Ejecutar y detener el bot.
- Ver salida en vivo del proceso dentro de la ventana.

## Generar ejecutable

### Linux

```bash
source .venv/bin/activate
python -m pip install -r requirements-build.txt
./build.sh
```

Salida esperada:

```bash
dist/razr-gui
```

### Windows

En una máquina Windows, desde la carpeta del proyecto:

```bat
py -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements-build.txt
build-windows.bat
```

Salida esperada:

```bat
dist\razr-gui.exe
```

> Nota: PyInstaller debe ejecutarse en Windows para generar el `.exe` de Windows.

### Ejecutar en segundo plano con `screen`

```bash
screen -S razr
source .venv/bin/activate
python main.py
```
Para volver a la sesión:

```bash
screen -r razr
```

### Ejecutar con `tmux`

```bash
tmux new -s razr
source .venv/bin/activate
python main.py
```

### Inicio automático (Linux)

La casilla **Start GUI and bot automatically at login** en la pestaña Settings
crea un launcher en `~/.config/autostart/razr.desktop`. En el siguiente login
abre la GUI y arranca el bot con tus rutas/configuración guardadas. Desmarcarla
elimina el launcher. No se activa automáticamente al instalar o abrir Razr.

Para arrancar sin escritorio al encender el sistema, usa el servicio de usuario:

```bash
.venv/bin/python startup.py --enable --mode service --boot \
  --app-dir /home/hax/.local/share/razr
systemctl --user start razr.service
systemctl --user status razr.service
journalctl --user -u razr.service -f
```

`--boot` ejecuta `loginctl enable-linger hax` (con el usuario actual), para que
systemd inicie el administrador de usuario al boot y lo mantenga tras logout,
como describe la [documentación de loginctl](https://www.freedesktop.org/software/systemd/man/252/loginctl.html).
Puede requerir permisos de la distribución. El servicio funciona sin GUI y con
consola/log; no envía desktop/sonido antes de que exista una sesión gráfica.
La habilitación prepara el siguiente inicio; `systemctl --user start` lo inicia
ahora. Si ya hay un bot en la GUI, detenlo primero: el lock evita duplicados.

Sin `--boot`, el servicio se habilita para el inicio del administrador de usuario,
habitualmente al login. El modo GUI/login y el servicio son opciones excluyentes.
No se activa el boot ni lingering simplemente al marcar la casilla de la GUI.
El launcher/servicio contiene rutas absolutas; si mueves el repo, virtualenv o
binario, deshabilita y habilita de nuevo desde la nueva ubicación.

```bash
.venv/bin/python startup.py --status --mode service
.venv/bin/python startup.py --disable --mode service
.venv/bin/python startup.py --disable --mode login
```

Deshabilitar el servicio también lo detiene. El programa no desactiva lingering,
porque puede ser necesario para otros servicios del usuario. Si solo lo usabas
para Razr, puedes desactivarlo con `loginctl disable-linger hax`. Los comandos
usan el usuario que los ejecuta; **no ejecutes startup.py con sudo**, porque
instalarías el servicio/launcher para root. Windows tiene consola/log y no tiene
un adaptador de inicio automático verificado en este release.

En la app empaquetada se usa el mismo soporte:

```bash
/home/hax/Documents/razr/dist/razr-gui --startup --enable --mode service --boot
/home/hax/Documents/razr/dist/razr-gui --startup --status --mode service
```

## Qué hace el bot

- Conecta a OKX con `ccxt`
- Descarga velas de BTC/USDT
- Calcula MACD con pandas
- Detecta cruces de MACD/Signal
- Notifica en desktop con `notify-send` + sonido
- Guarda logs en `razr.log`

## Estructura de archivos

- `main.py` - flujo principal
- `indicators.py` - cálculo MACD, señales
- `alerts.py` - notify-send + sonido
- `utils.py` - conexión OKX, logging, config
- `config.yaml.example` - ejemplo de configuración

## Notas de seguridad

- Nunca subas `config.yaml` con tus API keys a repositorios.
- Mantén `config.yaml` fuera de backups públicos.

## Señales repetibles (Phase 2)

El reloj UTC del equipo debe estar sincronizado (por ejemplo, mediante NTP).
Una vela de 1m es elegible cuando apertura + 60s es estrictamente anterior a
ahora − `close_grace_seconds` (2s). Se conservan respuestas que ya terminan en
una vela cerrada. Los timestamps se normalizan a UTC; filas desordenadas se
ordenan y duplicados idénticos se consolidan. Valores no finitos, precios/OHLC
inválidos, timestamps fuera de la cuadrícula de 1m y duplicados contradictorios
rechazan el ciclo completo.

MACD usa EMA `adjust=False`, alfa `2 / (span + 1)`, sembrada con el primer cierre;
la EMA de señal se siembra con MACD=0. El primer inicio exige al menos
`5 * slow + signal` cierres consecutivos y establece una línea base en el último,
sin alertar cruces históricos. Los estados EMA se guardan: mover la ventana de
consulta o reiniciar no vuelve a sembrar el indicador. Las pruebas incluyen
valores racionales fijos y convergencia al ampliar el historial (tolerancia
1e-6 para la fixture incluida; no es una garantía universal de convergencia).

Cada cierre nuevo se procesa cronológicamente. La identidad incluye exchange,
spot, símbolo, timeframe, versión/parámetros de estrategia, apertura y dirección.
Cambiar parámetros crea una nueva línea base. Evento, trabajos por canal y
watermark se guardan en una transacción. No elimines `state.sqlite3` para reiniciar:
eso elimina la continuidad. Para copiar el estado, detén primero el bot.

Si el último cierre tiene más de `stale_after_seconds` (120s), no se procesa ni
se entregan alertas. Un intervalo ausente o recuperación que excede la historia
disponible produce un error explícito y conserva el watermark; no se saltan velas.
En esta fase los huecos se reportan y requieren restaurar historia o decidir
explícitamente una nueva línea base. Los cruces recuperados se almacenan siempre,
con `recovered`; solo se encolan si su edad desde el cierre no supera
`alert_age_limit_seconds` (300s). Los trabajos pendientes que expiran se marcan
`expired`. `--no-notifications` conserva consola/log y suspende trabajos de
escritorio/sonido existentes.

Las alertas muestran mercado, dirección, apertura/cierre UTC, precio de cierre,
MACD/señal/histograma, estrategia y event ID. No usan el ticker como precio de
señal. Un evento se almacena una vez; una entrega externa puede repetirse si hay
un cierre del proceso entre envío y confirmación. Los fallos quedan pendientes;
los reintentos y estados por canal se describen a continuación.

## Entrega y recuperación (Phase 3)

Consola y log funcionan sin escritorio. `notifications: false` o
`--no-notifications` desactivan escritorio y sonido; puedes seleccionar cada uno
con `desktop_notifications` y `sound_notifications`. Los adaptadores actuales
son Linux: escritorio requiere `notify-send`, sesión D-Bus y DISPLAY/Wayland;
sonido requiere un archivo existente y `pw-play`, `paplay` o `play`. Los comandos tienen
un timeout de 10s y deben finalizar con status 0. Un canal no disponible queda
registrado como `failed`, sin bloquear los demás. Windows sigue en consola/log.

SQLite migra automáticamente el estado de Phase 2 sin borrar eventos. Cada
trabajo conserva `status`, `retry_count`, `next_retry_at` (UTC), `last_error`
(categoría) y `updated_at`. Los estados son `pending`, `delivered`, `failed` y
`expired`. Fallos transitorios se reintentan hasta `delivery_max_attempts` (5)
intentos fallidos. El retraso usa jitter entre la mitad y el total del backoff
exponencial: base `retry_base_seconds` (5s), máximo `retry_max_seconds` (300s).
Al vencer la edad máxima de alerta, el trabajo expira. Después de corregir un
canal puedes reencolar sus trabajos fallidos sin recrear eventos:

```bash
.venv/bin/python main.py --retry-failed
```

Esto restablece el presupuesto de intentos de todos los trabajos fallidos; los
canales desactivados continúan suspendidos y los eventos viejos expiran.
Una entrega externa puede repetirse si el proceso muere después del envío y antes
de confirmar SQLite. Hay un evento almacenado por identidad, sin garantía de
exactamente una entrega de escritorio ni confirmación de que el usuario la vio.

Los fallos transitorios durante la conexión inicial y el polling usan el mismo
backoff. `Retry-After` numérico o fecha HTTP se respeta incluso si exige esperar
más que el máximo local; el rate limiter de CCXT permanece habilitado. Errores de
configuración/autenticación o exchange no transitorios terminan con status 2;
errores inesperados terminan con status 1. `--once` no reintenta red y termina al
completar un ciclo; su status 0 no significa que todos los canales se entregaron.
Los errores de datos mantienen el watermark y esperan el siguiente polling.
No se implementa backfill automático para huecos fuera de la historia disponible.

Polling y reintentos usan plazos monotónicos; los tiempos de mercado usan UTC.
Al reiniciar, los deadlines UTC de SQLite se convierten al reloj monotónico del
nuevo proceso. Un salto de reloj/suspensión detectado fuerza reconexión y revisión
de frescura; las alertas se suspenden ante datos rechazados o stale. Los reintentos
de entrega se despachan entre polls mientras el último ciclo válido siga fresco.

Cada `health_interval_seconds` (60s) se emite `Health` con estado, último fetch,
último cierre procesado UTC, retraso, trabajos pendientes/fallidos y próxima
espera de red/entrega. `razr.log` rota a 5 MiB con tres backups. Los fallos de
librerías se registran por categoría; no se imprimen respuestas privadas ni
configuración del exchange. La salud de consola refleja fallos por canal aunque
los datos sigan sanos.

Un lock del sistema operativo impide dos runners en el mismo `--app-dir`.
El archivo `runner.lock` puede permanecer al salir; no lo borres mientras un
proceso esté activo. SIGINT/SIGTERM interrumpen las esperas y cierran SQLite y el
exchange al terminar la operación en curso. Una petición HTTP puede tardar hasta
30s y un comando local hasta 10s en finalizar. El lock se libera automáticamente
si el proceso muere. Telegram se mantiene opcional y no se añade en esta fase:
el alcance actual es entrega local.

## Replay offline y evaluación histórica (Phase 4)

`replay.py` no se conecta a OKX, no envía alertas y no modifica el estado del bot.
Acepta un JSON con filas `[timestamp_ms, open, high, low, close, volume]` o un CSV
con exactamente esas seis columnas, en ese orden. Los timestamps son aperturas
UTC en milisegundos; OHLCV debe cumplir las mismas reglas de validez y continuidad
del flujo live. El replay utiliza el mismo procesador y versión de estrategia,
con SQLite en memoria y una línea base después del calentamiento EMA.

Ejemplo reproducible con **datos sintéticos**, no precios históricos de OKX:

```bash
.venv/bin/python replay.py tests/fixtures/ohlcv.json \
  --data-kind synthetic --output /tmp/razr-audit.json
```

El archivo tiene 240 velas y produce ocho eventos con los parámetros 12/26/9.
El reporte JSON exporta identidades, tiempos UTC, valores del indicador, conteos,
cobertura, parámetros y hashes del archivo y de las velas normalizadas. Ejecutar
la misma entrada y argumentos produce el mismo reporte byte por byte.
`signal_audit()` cuenta cruces; no calcula rendimiento. El código anteriormente
llamado `backtest_signals()` se reemplazó y no se ejecuta en el polling.

Por defecto, el archivo declara que todas sus velas son históricas y cerradas;
el cutoff se deriva del último cierre más el grace, sin consultar el reloj actual.
Si la última vela puede estar en formación, exige un cutoff explícito:

```bash
.venv/bin/python replay.py candles.json --as-of 2026-01-01T04:00:00Z \
  --output /tmp/razr-audit.json
```

`--as-of` aplica la misma desigualdad estricta del cierre confirmado, incluido
`close_grace_seconds`; por eso una vela que cierra exactamente en el cutoff no
es elegible. `--config` permite otro YAML validado. Las etiquetas recovered y
edad de entrega de los eventos se calculan respecto al cutoff histórico, pero
no se crean trabajos de entrega. `--data-kind` es una declaración del operador,
no una verificación del origen de los datos.

La simulación es separada y opcional. Requiere un inicio de evaluación explícito
que coincida con una apertura UTC y deje suficiente historia de desarrollo para
el calentamiento. Elige el split y los parámetros antes de inspeccionar el
resultado; no ajustes parámetros sobre el período reservado para evaluación.

```bash
.venv/bin/python replay.py tests/fixtures/ohlcv.json --data-kind synthetic \
  --output /tmp/razr-evaluation.json --simulate \
  --evaluation-start 2026-01-01T03:00:00Z \
  --fee-bps 10 --slippage-bps 5 --initial-cash 1000
```

Ese ejemplo separa 180 velas de desarrollo y 60 de evaluación. La evaluación
empieza sin posición. BUY invierte el efectivo disponible en la apertura de la
siguiente vela; SELL cierra solo una posición existente, también en la siguiente
apertura. Un cruce de la última vela no puede ejecutarse sin otra vela. Fees y
slippage se aplican en cada orden. No hay shorts, leverage, sizing, restricciones
de lote ni modelado de liquidez; tampoco hay liquidación forzada al terminar.

El reporte incluye supuestos, operaciones cerradas, posición abierta, equity
marcado al último cierre, retorno, drawdown de equity en cierres y benchmark
buy-and-hold con los mismos costos de entrada. El benchmark se marca al cierre
sin costo de salida, igual que una posición abierta de la estrategia. No se
reportan extremos intrabar ni se anualiza una muestra corta. Los resultados de
la fixture sirven para verificar el software, no para demostrar rentabilidad.

La suite bloquea acceso de red y cubre fixtures numéricas, replay, múltiples
polls, recuperación, reinicio, entregas y ausencia de look-ahead. GitHub Actions
instala las dependencias fijadas en Python 3.12, verifica compatibilidad, compila,
importa módulos, ejecuta tests y compara dos exports. Los checks live de OKX,
escritorio/sonido y soak permanecen gates manuales fuera de CI.

## Operación y release (Phase 5)

La GUI abre en pantalla completa. **Esc** vuelve a ventana y **F11** alterna
pantalla completa.

En la GUI, `starting` espera la conexión; `healthy` significa que el último ciclo
validó datos; `stale` bloquea alertas por retraso; `retrying` indica backoff de
red; `failed` indica datos/canal inválidos o salida con error; `stopped` significa
que el proceso terminó. La línea de salud muestra último cierre UTC, trabajos
pendientes y entregas fallidas. El output retiene hasta 2000 líneas; el archivo
rotativo conserva historia más larga. Health se publica atómicamente en
`health.json` por cada ciclo y periódicamente entre ciclos. La GUI comprueba el
ID de su ejecución para no mostrar salud de un proceso anterior.

**Stop Bot** y cerrar la ventana esperan el shutdown: SIGTERM, hasta 45s para
terminar trabajo en curso y guardar estado, luego kill y una espera final de 5s.
Las tareas de background pasan por una cola acotada; no tocan widgets después
de destruir la ventana. La GUI controla solo el hijo que inició, no un servicio
systemd ya activo; para ese servicio usa `systemctl --user stop razr.service`.

El primer inicio de GUI crea `config.yaml` público si falta. CLI/binario puede
hacerlo explícitamente sin reemplazar archivos existentes:

```bash
.venv/bin/python main.py --init-config --check-config
/home/hax/Documents/razr/dist/razr-gui --bot-runner --init-config --check-config
```

El binario incluye el template y usa un directorio de datos escribible externo,
no la carpeta temporal de PyInstaller ni la carpeta del ejecutable. Las rutas
predeterminadas son las descritas arriba. Windows crea defaults sin desktop ni
sonido; empaquetado/GUI en Windows aún no están verificados.

Para probar alertas sin esperar un cruce, usa **Test Alerts** en la GUI o:

```bash
.venv/bin/python main.py --test-alert
.venv/bin/python main.py --test-alert --no-notifications
```

No consulta exchange, no crea un evento MACD y muestra TEST ALERT. Si un canal
habilitado falla, el CLI devuelve 1. Desactiva `sound_notifications` si no tienes
`pw-play`/`paplay`/`play`; desktop necesita una sesión válida y `notify-send`.

Para backup, detén el bot/servicio, espera su salida, y copia `config.yaml`,
`state.sqlite3` y los logs de su app-dir. Guarda el backup en un lugar privado
si configuraste credenciales. Restaura la base antes de arrancar para conservar
watermarks, EMA y cola de entrega. No copies una base mientras está escribiendo
sin usar la API de backup de SQLite.

Troubleshooting:

- **Otro runner activo:** detén la GUI o servicio del mismo app-dir; no borres el lock.
- **Stale/gap:** verifica reloj UTC y red, revisa el intervalo faltante en el log;
  no borres la base para ocultar el error. Gaps fuera de la historia disponible
  requieren restaurar historia o decidir explícitamente una nueva línea base.
- **Failed delivery:** corrige sesión/herramientas/archivo, luego `--retry-failed`;
  los eventos demasiado viejos expiran aunque se reencolen.
- **No señales al arrancar:** el primer inicio establece una línea base; no alerta
  cruces históricos. Comprueba `healthy` y último cierre antes de esperar cruces.
- **Startup falla:** verifica rutas absolutas, `systemctl --user status`, journal y
  `loginctl show-user hax -p Linger` para boot. No uses simultáneamente GUI/login
  y servicio, ni intentes iniciar el servicio como root.

### Soak de 72 horas

`soak.py` crea una configuración pública y estado aislados y un servicio transitorio
systemd de usuario con deadline UTC fijo. No modifica la configuración del bot
normal ni habilita startup. Logs rotativos, SQLite, `health.json` y `soak.json`
conservan evidencias. Necesita que el administrador systemd del usuario siga activo
(login o lingering); apagar/suspender/cerrar sesión puede interrumpir la cobertura.

```bash
.venv/bin/python soak.py start --app-dir /home/hax/.local/share/razr/soak-new --hours 72
.venv/bin/python soak.py status --app-dir /home/hax/.local/share/razr/soak-new
.venv/bin/python soak.py outage --app-dir /home/hax/.local/share/razr/soak-new --outage-seconds 45
.venv/bin/python soak.py restart --app-dir /home/hax/.local/share/razr/soak-new
.venv/bin/python soak.py report --app-dir /home/hax/.local/share/razr/soak-new
.venv/bin/python soak.py stop --app-dir /home/hax/.local/share/razr/soak-new
```

`outage` bloquea temporalmente los fetches de ese runner para verificar backoff y
catch-up; no corta la red de otras aplicaciones y no prueba una falla física del
adaptador de red. Tras una suspensión real, registra el check con `mark-suspend`
y revisa la evidencia del log. El reporte no concede aprobación automática de
release: se deben revisar duración/cobertura completa, integridad/eventos, salud,
restart/outage y suspend si aplica. Una corrida iniciada no es una corrida aprobada.

El binario Linux se construyó y probó en este host desde `/tmp`, sin depender de
Python/venv en PATH, incluyendo defaults empaquetados y un ciclo público. Desktop
test entregado en esta sesión; reproducción con PipeWire (`pw-play`) verificada sin errores; la audibilidad
debe confirmarse en el escritorio.
Una máquina Linux limpia distinta, boot real, Windows y el soak completo siguen
siendo gates pendientes; el binario depende de compatibilidad del sistema/glibc.
