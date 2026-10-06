"""Shared typed settings and paths for source and frozen applications."""
from dataclasses import asdict, dataclass
from pathlib import Path
import os
import sys
import tempfile
import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    exchange: str = 'okx'
    symbol: str = 'BTC/USDT'
    timeframe: str = '1m'
    authenticated: bool = False
    api_key: str = ''
    api_secret: str = ''
    api_passphrase: str = ''
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    limit: int = 200
    sleep_seconds: int = 30
    resume_grace_seconds: int = 10
    close_grace_seconds: int = 2
    stale_after_seconds: int = 120
    alert_age_limit_seconds: int = 300
    sound_file: str = ''
    debug: bool = False
    notifications: bool = True
    notify_urgency: str = 'critical'
    desktop_notifications: bool = True
    sound_notifications: bool = True
    retry_base_seconds: int = 5
    retry_max_seconds: int = 300
    delivery_max_attempts: int = 5
    health_interval_seconds: int = 60

    def get(self, key, default=None):
        return getattr(self, key, default)


def validate_config(raw) -> Settings:
    if not isinstance(raw, dict):
        raise ConfigError('configuration must be a YAML mapping')
    unknown = set(raw) - set(Settings.__dataclass_fields__)
    if unknown:
        raise ConfigError('unknown settings: ' + ', '.join(sorted(map(str, unknown))))
    values = asdict(Settings()) | raw
    for key, default in asdict(Settings()).items():
        value = values[key]
        if type(value) is not type(default):
            raise ConfigError(f'{key} must be {type(default).__name__}')
    cfg = Settings(**values)
    for key in ('macd_fast', 'macd_slow', 'macd_signal', 'sleep_seconds', 'retry_base_seconds',
                'retry_max_seconds', 'delivery_max_attempts', 'health_interval_seconds'):
        if cfg.get(key) <= 0:
            raise ConfigError(f'{key} must be positive')
    if cfg.retry_max_seconds < cfg.retry_base_seconds:
        raise ConfigError('retry_max_seconds must be at least retry_base_seconds')
    if cfg.macd_fast >= cfg.macd_slow:
        raise ConfigError('macd_fast must be less than macd_slow')
    minimum = 5 * cfg.macd_slow + cfg.macd_signal + 2
    if not minimum <= cfg.limit <= 300:
        raise ConfigError(f'limit must be between {minimum} and 300 candles')
    for key in ('close_grace_seconds', 'alert_age_limit_seconds'):
        if cfg.get(key) < 0:
            raise ConfigError(f'{key} must be nonnegative')
    if cfg.stale_after_seconds <= 60 + cfg.close_grace_seconds:
        raise ConfigError('stale_after_seconds must exceed 60 + close_grace_seconds')
    if cfg.resume_grace_seconds < 0:
        raise ConfigError('resume_grace_seconds must be nonnegative')
    if cfg.notify_urgency not in ('low', 'normal', 'critical'):
        raise ConfigError('notify_urgency must be low, normal, or critical')
    if (cfg.exchange, cfg.symbol, cfg.timeframe) != ('okx', 'BTC/USDT', '1m'):
        raise ConfigError('only OKX spot BTC/USDT at 1m is currently supported')
    if cfg.authenticated:
        for key in ('api_key', 'api_secret', 'api_passphrase'):
            value = cfg.get(key).strip()
            if not value or any(token in value.upper() for token in ('EXCHANGE_API', 'PASSPHRASE', 'YOUR_', 'PLACEHOLDER')):
                raise ConfigError(f'{key} requires a real credential in authenticated mode')
    return cfg


def load_config(path) -> Settings:
    try:
        with Path(path).open(encoding='utf-8') as stream:
            return validate_config(yaml.safe_load(stream))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f'cannot read configuration at {path}: {exc}') from exc


@dataclass(frozen=True)
class AppPaths:
    directory: Path
    config: Path
    log: Path
    state: Path


def application_paths(directory=None, config_path=None) -> AppPaths:
    if directory is None:
        if sys.platform == 'win32':
            base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
        else:
            base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
        directory = base / 'razr'
    directory = Path(directory).expanduser().resolve()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
    except OSError as exc:
        raise ConfigError(f'application directory must be writable: {directory}: {exc}') from exc
    config = Path(config_path).expanduser().resolve() if config_path else directory / 'config.yaml'
    return AppPaths(directory, config, directory / 'razr.log', directory / 'state.sqlite3')


def save_config(path, settings: Settings):
    """Replace configuration atomically after successful validation."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(asdict(settings), stream, sort_keys=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def config_template():
    """Bundled resource in a frozen app, repository resource in source."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'config.yaml.example'


def initialize_config(paths):
    """Create a public default once; never replace an existing configuration."""
    if paths.config.exists():
        return False
    settings = load_config(config_template())
    if sys.platform == 'win32':
        from dataclasses import replace
        settings = replace(settings, notifications=False)
    paths.config.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids overwriting a concurrent first-start writer.
    with paths.config.open('x', encoding='utf-8') as stream:
        yaml.safe_dump(asdict(settings), stream, sort_keys=False)
    return True
