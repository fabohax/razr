<p>
  <img src="razr.png" alt="razr-bot" width="400" style="display: block; margin: auto;">
</p>

# razr

**razr** es un bot de monitoreo en tiempo real que analiza el mercado BTC/USDT mediante el indicador MACD y emite alertas automáticas ante oportunidades de compra o venta.

### Ciclo de operación

1. **Conexión al exchange** — Se conecta a OKX vía API usando `ccxt` con las credenciales definidas en `config.yaml`.
2. **Obtención de datos** — Descarga las últimas N velas (OHLCV) del par y timeframe configurados (por defecto `BTC/USDT` en `15m`).
3. **Cálculo de indicadores** — Computa MACD, línea de señal e histograma con parámetros configurables (`fast`, `slow`, `signal`).
4. **Detección de cruces** — Identifica cruces alcistas (BUY) y bajistas (SELL) entre la línea MACD y la línea de señal. Clasifica cada cruce como **fuerte** o **débil** según la posición del histograma.
5. **Backtesting ligero** — Ejecuta un backtest rápido sobre las velas descargadas para auditar la frecuencia de señales recientes.
6. **Alertas** — Cuando se detecta un nuevo cruce:
   - Envía una **notificación de escritorio** (`notify-send`) con urgencia configurable.
   - Reproduce un **sonido de alerta** (`paplay` / `sox`).
   - Imprime la señal en consola con **colores** (verde = BUY, rojo = SELL) usando `colorama`.
   - Registra el evento en `razr.log`.
7. **Bucle continuo** — Espera `sleep_seconds` (por defecto 30s) y repite. Ante errores de red o API, reintenta automáticamente tras 30s.

## Requisitos previos (Ubuntu 22.04/24.04)

1. Actualizar sistema:

```bash
sudo apt update && sudo apt upgrade -y
```

2. Instalar Python 3 y herramientas nativas:

```bash
sudo apt install -y python3 python3-venv python3-pip libnotify-bin sox
```

3. (Opcional) Instalar `screen` o `tmux` para ejecutar en segundo plano:

```bash
sudo apt install -y screen tmux
```

4. Clonar/descargar este proyecto:

```bash
cd ~/Documents
git clone https://github.com/fabohax/razr
cd razr
```

5. Crear entorno virtual e instalar dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

6. Copiar configuración y editar la API Key/Secret:

```bash
cp config.yaml.example config.yaml
nano config.yaml
```

Configura `api_key`, `api_secret`, `api_passphrase` (si aplica), `timeframe` y `sound_file`.

## Uso

```bash
source .venv/bin/activate
python main.py
```

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

### Ejecutar con `systemd` (opcional para segundo plano)

Crea `/etc/systemd/system/razr.service`:

```ini
[Unit]
Description=Razr MACD Alert Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/Documents/razr
ExecStart=/home/$USER/Documents/razr/.venv/bin/python /home/$USER/Documents/razr/main.py
Restart=on-failure
RestartSec=20
Environment="DISPLAY=:0" "XAUTHORITY=/home/$USER/.Xauthority"

[Install]
WantedBy=default.target
```

Después:

```bash
sudo systemctl daemon-reload
sudo systemctl enable razr.service
sudo systemctl start razr.service
sudo systemctl status razr.service
```

## Qué hace el bot

- Conecta a OKX con `ccxt`
- Descarga velas de BTC/USDT
- Calcula MACD con `pandas_ta`
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
