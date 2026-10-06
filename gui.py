import subprocess
import sys
import threading
import queue
import time
import uuid
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ccxt
from dataclasses import asdict, replace
from config import Settings, application_paths, load_config, save_config, validate_config, initialize_config

from operator_state import read_health
from startup import configured, set_startup

# Core fields edited in Settings tab.
FIELD_SPECS = [
    ("authenticated", "bool"),
    ("notifications", "bool"),
    ("desktop_notifications", "bool"),
    ("sound_notifications", "bool"),
    ("retry_base_seconds", "int"),
    ("retry_max_seconds", "int"),
    ("delivery_max_attempts", "int"),
    ("health_interval_seconds", "int"),
    ("api_key", "str"),
    ("api_secret", "str"),
    ("api_passphrase", "str"),
    ("timeframe", "str"),
    ("macd_fast", "int"),
    ("macd_slow", "int"),
    ("macd_signal", "int"),
    ("limit", "int"),
    ("sleep_seconds", "int"),
    ("resume_grace_seconds", "int"),
    ("close_grace_seconds", "int"),
    ("stale_after_seconds", "int"),
    ("alert_age_limit_seconds", "int"),
    ("sound_file", "str"),
    ("debug", "bool"),
    ("notify_urgency", "str"),
]

SECRET_FIELDS = {"api_secret", "api_passphrase"}
EYE_ICON = "👁"

BG_COLOR = "#101010"
SURFACE_COLOR = "#101010"
SURFACE_ALT_COLOR = "#101010"
TEXT_COLOR = "#e5e7eb"
MUTED_TEXT_COLOR = "#9ca3af"
ACCENT_COLOR = "#222222"
ACCENT_ACTIVE_COLOR = "#151515"
TERMINAL_GREEN = "#9dff00"
BORDER_COLOR = "#222222"
INPUT_COLOR = "#101010"
BOT_RUNNER_ARG = "--bot-runner"


class RazrGUI:
    def __init__(self, root: tk.Tk, paths=None):
        self.paths = paths or application_paths()
        initialize_config(self.paths)
        self._events = queue.Queue(maxsize=1000)
        self._closed = False
        self._closing = False
        self._stopping = False
        self._pump_job = None
        self._session_id = None
        self._next_health = 0.
        self.root = root
        self.root.title("razr")
        self.root.geometry("900x700")
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda event: self.root.attributes("-fullscreen", False))
        self.root.bind("<F11>", lambda event: self.root.attributes(
            "-fullscreen", not self.root.attributes("-fullscreen")))

        self.process: subprocess.Popen | None = None
        self.output_thread: threading.Thread | None = None

        self.vars: dict[str, tk.Variable] = {}
        self.secret_entries: dict[str, ttk.Entry] = {}
        self.secret_visible: dict[str, bool] = {}
        self.secret_buttons: dict[str, ttk.Button] = {}

        self.exchange_var = tk.StringVar(value="okx")
        self.symbol_var = tk.StringVar(value="BTC/USDT")
        self.exchange_values = ["okx"]
        self.symbol_values: list[str] = []

        self._build_ui()
        self.load_config()
        self._pump_events()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.BOTH, expand=True)

        control_tab = ttk.Frame(notebook, padding=10)
        settings_tab = ttk.Frame(notebook, padding=10)
        notebook.add(control_tab, text="Bot")
        notebook.add(settings_tab, text="Settings")

        self._build_control_tab(control_tab)
        self._build_settings_tab(settings_tab)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _apply_dark_theme(self):
        style = ttk.Style()
        style.theme_use("clam")

        self.root.configure(bg=BG_COLOR)

        style.configure(".", background=BG_COLOR, foreground=TEXT_COLOR, fieldbackground=INPUT_COLOR)
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR)
        style.configure(
            "TButton",
            background=SURFACE_COLOR,
            foreground=TEXT_COLOR,
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
            focuscolor=BORDER_COLOR,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", ACCENT_ACTIVE_COLOR), ("pressed", ACCENT_ACTIVE_COLOR)],
            foreground=[("disabled", MUTED_TEXT_COLOR), ("active", TEXT_COLOR)],
            lightcolor=[("active", BORDER_COLOR), ("pressed", BORDER_COLOR)],
            darkcolor=[("active", BORDER_COLOR), ("pressed", BORDER_COLOR)],
            bordercolor=[("active", BORDER_COLOR), ("pressed", BORDER_COLOR)],
        )
        style.configure("TCheckbutton", background=BG_COLOR, foreground=TEXT_COLOR)
        style.configure("Startup.TCheckbutton", background="#000000", foreground=TEXT_COLOR)
        style.map("Startup.TCheckbutton",
                  background=[("disabled", "#000000"), ("active", "#000000"), ("selected", "#000000"), ("!disabled", "#000000")],
                  foreground=[("disabled", MUTED_TEXT_COLOR), ("!disabled", TEXT_COLOR)])

        style.configure(
            "TLabelframe",
            background=BG_COLOR,
            foreground=TEXT_COLOR,
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
            borderwidth=1,
            relief="solid",
        )
        style.configure("TLabelframe.Label", background=BG_COLOR, foreground=TEXT_COLOR)
        style.configure(
            "TNotebook",
            background=BG_COLOR,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
        )
        style.configure(
            "TNotebook.Tab",
            background=SURFACE_COLOR,
            foreground=TEXT_COLOR,
            lightcolor=SURFACE_COLOR,
            darkcolor=SURFACE_COLOR,
            bordercolor=BORDER_COLOR,
            borderwidth=1,
            relief="flat",
            padding=(22, 10),
            width=14,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT_COLOR), ("active", SURFACE_ALT_COLOR)],
            foreground=[("selected", TEXT_COLOR)],
            lightcolor=[("selected", ACCENT_COLOR), ("active", SURFACE_ALT_COLOR)],
            darkcolor=[("selected", ACCENT_COLOR), ("active", SURFACE_ALT_COLOR)],
            bordercolor=[("selected", ACCENT_COLOR), ("active", BORDER_COLOR)],
            borderwidth=[("selected", 1), ("active", 1)],
            relief=[("selected", "flat"), ("active", "flat")],
            padding=[("selected", (22, 10)), ("active", (22, 10))],
        )
        style.configure(
            "TEntry",
            fieldbackground=INPUT_COLOR,
            foreground=TEXT_COLOR,
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
            borderwidth=1,
            padding=3,
        )
        style.configure(
            "TCombobox",
            fieldbackground=INPUT_COLOR,
            background=SURFACE_COLOR,
            foreground=TEXT_COLOR,
            arrowcolor=TEXT_COLOR,
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
            borderwidth=1,
            padding=3,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", INPUT_COLOR)],
            background=[("readonly", SURFACE_COLOR)],
            foreground=[("readonly", TEXT_COLOR)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=SURFACE_COLOR,
            troughcolor=BG_COLOR,
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
            arrowcolor=TEXT_COLOR,
        )

    def _build_control_tab(self, parent: ttk.Frame):
        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X, pady=(0, 8))

        self.run_btn = ttk.Button(actions, text="Run Bot", command=self.start_bot)
        self.run_btn.pack(side=tk.LEFT)

        self.stop_btn = ttk.Button(actions, text="Stop Bot", command=self.stop_bot, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=8)

        self.status_var = tk.StringVar(value="Status: stopped")
        ttk.Label(actions, textvariable=self.status_var).pack(side=tk.RIGHT)

        self.health_var = tk.StringVar(value="Last candle: — | Pending: 0 | Failed deliveries: 0")
        ttk.Label(parent, textvariable=self.health_var).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(actions, text="Test Alerts", command=self.test_alerts).pack(side=tk.LEFT, padx=8)

        log_frame = ttk.LabelFrame(parent, text="Bot Output", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.output_text = tk.Text(log_frame, height=20, wrap=tk.WORD)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.output_text.configure(
            state=tk.DISABLED,
            bg=SURFACE_ALT_COLOR,
            fg=TERMINAL_GREEN,
            font=("DejaVu Sans Mono", 20),
            insertbackground=TERMINAL_GREEN,
            selectbackground=ACCENT_COLOR,
            selectforeground=SURFACE_ALT_COLOR,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_COLOR,
        )

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.output_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.configure(yscrollcommand=scrollbar.set)

    def _build_settings_tab(self, parent: ttk.Frame):
        self.startup_var = tk.BooleanVar(value=configured('login') if sys.platform=='linux' else False)
        self.startup_check = ttk.Checkbutton(
            parent, text="Start GUI and bot automatically at login", variable=self.startup_var,
            command=self._toggle_startup, style="Startup.TCheckbutton",
            state=tk.NORMAL if sys.platform=='linux' else tk.DISABLED)
        self.startup_check.pack(anchor="w", pady=(0, 10))

        market_frame = ttk.LabelFrame(parent, text="Market", padding=10)
        market_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(market_frame, text="exchange", width=22).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.exchange_combo = ttk.Combobox(
            market_frame,
            textvariable=self.exchange_var,
            values=self.exchange_values,
            state="readonly",
        )
        self.exchange_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.exchange_combo.bind("<<ComboboxSelected>>", self._on_exchange_selected)

        ttk.Button(market_frame, text="Refresh Pairs", command=self.refresh_symbols).grid(
            row=0, column=2, padx=(8, 0), pady=4
        )

        ttk.Label(market_frame, text="symbol", width=22).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.symbol_combo = ttk.Combobox(market_frame, textvariable=self.symbol_var, values=[], state="readonly")
        self.symbol_combo.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(market_frame, text="Reload Exchanges", command=self.reload_exchanges).grid(
            row=1, column=2, padx=(8, 0), pady=4
        )

        market_frame.columnconfigure(1, weight=1)

        settings_scroll = ttk.Frame(parent)
        settings_scroll.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(settings_scroll, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(settings_scroll, orient="vertical", command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        cfg_frame = ttk.LabelFrame(canvas, text="Config", padding=10)
        window = canvas.create_window((0, 0), window=cfg_frame, anchor="nw")
        cfg_frame.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

        for row, (name, typ) in enumerate(FIELD_SPECS):
            ttk.Label(cfg_frame, text=name, width=22).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)

            if typ == "bool":
                var = tk.BooleanVar(value=False)
                widget = ttk.Checkbutton(cfg_frame, variable=var)
                widget.grid(row=row, column=1, sticky="w", pady=4)
            else:
                var = tk.StringVar(value="")
                entry = ttk.Entry(cfg_frame, textvariable=var)
                if name in SECRET_FIELDS:
                    entry.configure(show="*")
                entry.grid(row=row, column=1, sticky="ew", pady=4)
                if name in SECRET_FIELDS:
                    self.secret_entries[name] = entry
                    self.secret_visible[name] = False
                    btn = ttk.Button(
                        cfg_frame,
                        text=EYE_ICON,
                        command=lambda n=name: self.toggle_secret(n),
                        width=3,
                    )
                    btn.grid(row=row, column=2, padx=(8, 0), pady=4)
                    self.secret_buttons[name] = btn
                if name == "sound_file":
                    ttk.Button(cfg_frame, text="Browse", command=self._browse_sound_file).grid(
                        row=row, column=3, padx=(8, 0), pady=4
                    )

            self.vars[name] = var

        cfg_frame.columnconfigure(1, weight=1)

        save_frame = ttk.Frame(parent)
        save_frame.pack(fill=tk.X, pady=(10, 0))
        self.save_btn = ttk.Button(save_frame, text="Save Config", command=self.save_config)
        self.save_btn.pack(side=tk.LEFT)

    def _browse_sound_file(self):
        path = filedialog.askopenfilename(title="Select sound file")
        if path:
            self.vars["sound_file"].set(path)

    def toggle_secret(self, field_name: str):
        entry = self.secret_entries.get(field_name)
        if not entry:
            return
        visible = self.secret_visible.get(field_name, False)
        entry.configure(show="" if not visible else "*")
        self.secret_visible[field_name] = not visible

    def reload_exchanges(self):
        self.exchange_values = ["okx"]
        self.exchange_combo.configure(values=self.exchange_values)

    def _on_exchange_selected(self, _event=None):
        self.refresh_symbols()

    def refresh_symbols(self):
        exchange_id = self.exchange_var.get().strip().lower()
        if not exchange_id:
            return
        if exchange_id not in ccxt.exchanges:
            messagebox.showerror("Exchange", f"Unknown exchange: {exchange_id}")
            return

        self._append_output(f"Loading markets for {exchange_id}...\n")

        def worker():
            try:
                exchange_class = getattr(ccxt, exchange_id)
                exchange = exchange_class({"enableRateLimit": True, "timeout": 30000})
                try:
                    markets = exchange.load_markets()
                finally:
                    from utils import close_exchange
                    close_exchange(exchange)
                symbols = ["BTC/USDT"] if markets.get("BTC/USDT", {}).get("spot") else []
                self._post(self._set_symbols, symbols)
            except Exception as exc:
                self._post(messagebox.showerror, "Markets", f"Could not load markets ({type(exc).__name__})")

        threading.Thread(target=worker, daemon=True).start()

    def _set_symbols(self, symbols: list[str]):
        self.symbol_values = symbols
        self.symbol_combo.configure(values=self.symbol_values)
        current = self.symbol_var.get().strip()
        if current and current in self.symbol_values:
            return
        if "BTC/USDT" in self.symbol_values:
            self.symbol_var.set("BTC/USDT")
        elif self.symbol_values:
            self.symbol_var.set(self.symbol_values[0])
        self._append_output(f"Loaded {len(self.symbol_values)} pairs\n")

    def _append_output(self, line: str):
        if getattr(self, "_closed", False):
            return
        line = line[:8192]
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.insert(tk.END, line)
        lines = int(self.output_text.index('end-1c').split('.')[0])
        if lines > 2000:
            self.output_text.delete('1.0', f'{lines-2000+1}.0')
        self.output_text.see(tk.END)
        self.output_text.configure(state=tk.DISABLED)

    def load_config(self):
        try:
            cfg = asdict(load_config(self.paths.config)) if self.paths.config.exists() else asdict(Settings())
        except Exception as exc:
            messagebox.showerror("Config error", str(exc))
            cfg = asdict(Settings())

        for name, typ in FIELD_SPECS:
            val = cfg.get(name, "1m" if name == "timeframe" else None)
            if typ == "bool":
                self.vars[name].set(bool(val))
            else:
                self.vars[name].set("" if val is None else str(val))

        exchange_val = cfg.get("exchange", "okx")
        symbol_val = cfg.get("symbol", "BTC/USDT")
        self.exchange_var.set(str(exchange_val))
        self.symbol_var.set(str(symbol_val))

        # Load pairs in background using configured exchange.
        self.refresh_symbols()

        self._append_output("Loaded config.yaml\n")

    def _collect_config(self) -> Settings:
        cfg: dict[str, object] = {}
        for name, typ in FIELD_SPECS:
            raw = self.vars[name].get()
            if typ == "int":
                try:
                    cfg[name] = int(raw)
                except Exception as exc:
                    raise ValueError(f"{name} must be an integer") from exc
            elif typ == "bool":
                cfg[name] = bool(raw)
            else:
                cfg[name] = str(raw)

        cfg["exchange"] = self.exchange_var.get().strip()
        cfg["symbol"] = self.symbol_var.get().strip()

        if not cfg["exchange"]:
            raise ValueError("exchange is required")
        if not cfg["symbol"]:
            raise ValueError("symbol is required")
        return validate_config(cfg)

    def save_config(self):
        try:
            cfg = self._collect_config()
        except ValueError as exc:
            messagebox.showerror("Validation error", str(exc))
            return False

        try:
            save_config(self.paths.config, cfg)
        except Exception as exc:
            messagebox.showerror("Write error", f"Could not save config.yaml:\n{exc}")
            return False

        self._append_output(f"Saved {self.paths.config}\n")
        return True

    def _set_running_state(self, running: bool):
        self.run_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.status_var.set(f"Status: {'starting' if running else 'stopped'}")

    def start_bot(self):
        if self.process and self.process.poll() is None:
            messagebox.showinfo("Bot", "Bot is already running.")
            return

        if not self.save_config():
            return

        self._stopping = False
        self._session_id = uuid.uuid4().hex
        self._append_output("Starting bot...\n")
        self._set_running_state(True)

        try:
            command = self._build_bot_command() + ["--session-id", self._session_id]
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._set_running_state(False)
            self.status_var.set("Status: failed")
            messagebox.showerror("Start error", f"Could not start bot:\n{exc}")
            return

        self.output_thread = threading.Thread(target=self._read_output, args=(self.process,), daemon=True)
        self.output_thread.start()

    def _build_bot_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            command = [sys.executable, BOT_RUNNER_ARG]
        else:
            command = [sys.executable, "-u", str(Path(__file__).resolve().with_name("main.py"))]
        return command + ["--app-dir", str(self.paths.directory), "--config", str(self.paths.config)]

    def _post(self, callback, *args):
        if self._closed:
            return
        item = (callback, args)
        try:
            self._events.put_nowait(item)
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._events.put_nowait(item)
            except queue.Full:
                pass

    def _pump_events(self):
        if self._closed:
            return
        for _ in range(100):
            try:
                callback, args = self._events.get_nowait()
            except queue.Empty:
                break
            if self._closing and callback not in (self._finish_process, self._append_output):
                continue
            callback(*args)
            if self._closed:
                return
        # Process state is authoritative even if a finish message was dropped.
        if self.process is not None and self.process.poll() is not None:
            self._finish_process(self.process, self.process.returncode)
            if self._closed:
                return
        if time.monotonic() >= self._next_health:
            self._update_health()
            self._next_health = time.monotonic()+1
        self._pump_job = self.root.after(100, self._pump_events)

    def _update_health(self):
        if self.process is None or self._stopping:
            return
        health = read_health(self.paths.directory)
        if not health or health.get('session_id') != self._session_id:
            return
        status = health.get('status','starting')
        status = {'recovering':'starting','data_error':'failed'}.get(status,status)
        if health.get('failed',0) and status=='healthy':
            status='failed'
        if time.time()-health.get('updated_at',0)>120 and status=='healthy':
            status='stale (health report)'
        self.status_var.set(f"Status: {status}")
        self.health_var.set(f"Last candle: {health.get('last_candle_utc') or '—'} | Pending: {health.get('pending',0)} | Failed deliveries: {health.get('failed',0)}")

    def _read_output(self, process):
        try:
            if process.stdout:
                for line in iter(lambda: process.stdout.readline(8192), ''):
                    self._post(self._append_output, line)
                process.stdout.close()
            rc = process.wait()
            self._post(self._finish_process, process, rc)
        except (OSError, ValueError):
            self._post(self._append_output, 'Output stream closed.\n')

    def _finish_process(self, process, rc):
        if process is not self.process or self._closed:
            return
        self._append_output(f"\nBot exited with code {rc}\n")
        self.process = None
        self._stopping = False
        self._set_running_state(False)
        self.status_var.set('Status: stopped' if rc==0 else f'Status: failed (exit {rc})')
        if self._closing:
            self._close_window()

    def stop_bot(self):
        if not self.process or self.process.poll() is not None:
            if self.process:
                self._finish_process(self.process, self.process.returncode)
            else:
                self._set_running_state(False)
                if self._closing:
                    self._close_window()
            return
        if self._stopping:
            return
        self._stopping = True
        self.stop_btn.configure(state=tk.DISABLED)
        self.status_var.set('Status: stopping')
        self._append_output('Stopping bot; waiting for state shutdown...\n')
        process = self.process
        def worker():
            try:
                process.terminate()
                try:
                    rc = process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    self._post(self._append_output,'Graceful shutdown timed out; forcing termination.\n')
                    process.kill()
                    rc = process.wait(timeout=5)
                self._post(self._finish_process,process,rc)
            except (OSError,subprocess.SubprocessError):
                self._post(self._append_output,'Could not stop child process; check the process manually.\n')
        threading.Thread(target=worker,daemon=True).start()

    def _toggle_startup(self):
        enabled = self.startup_var.get()
        if enabled and not self.save_config():
            self.startup_var.set(False)
            return
        try:
            path = set_startup(self.paths,enabled,'login')
            self._append_output(f"Login startup {'enabled' if enabled else 'disabled'}: {path}\n")
        except (OSError,ValueError,RuntimeError) as exc:
            self.startup_var.set(configured('login'))
            messagebox.showerror('Automatic startup',str(exc))

    def test_alerts(self):
        if not self.save_config():
            return
        # Use a separate directory to avoid taking the active runner's lock.
        test_paths = application_paths(self.paths.directory/'alert-test')
        cfg = self._collect_config()
        sound = Path(cfg.sound_file).expanduser() if cfg.sound_file else None
        if sound is not None and not sound.is_absolute():
            sound = self.paths.directory / sound
        save_config(test_paths.config,replace(cfg,sound_file=str(sound) if sound else ''))
        command = self._build_bot_command()
        command[command.index('--config')+1] = str(test_paths.config)
        command[command.index('--app-dir')+1] = str(self.paths.directory/'alert-test')
        command += ['--test-alert']
        def worker():
            try:
                result = subprocess.run(command,capture_output=True,text=True,timeout=30)
                self._post(self._append_output,result.stdout+result.stderr)
                self._post(self._append_output,f'Test alerts exit status: {result.returncode}\n')
            except (OSError,subprocess.SubprocessError):
                self._post(self._append_output,'Alert test failed or timed out.\n')
        threading.Thread(target=worker,daemon=True).start()

    def _close_window(self):
        self._closed = True
        if self._pump_job is not None:
            self.root.after_cancel(self._pump_job)
            self._pump_job = None
        self.root.destroy()

    def on_close(self):
        self._closing = True
        if self.process and self.process.poll() is None:
            self.run_btn.configure(state=tk.DISABLED)
            self.stop_bot()
        else:
            self._close_window()


def main():
    if "--startup" in sys.argv[1:]:
        from startup import main as startup_main
        sys.exit(startup_main([arg for arg in sys.argv[1:] if arg != "--startup"]))
    if BOT_RUNNER_ARG in sys.argv[1:]:
        from main import main as bot_main

        sys.exit(bot_main([arg for arg in sys.argv[1:] if arg != BOT_RUNNER_ARG]))
        return

    import argparse
    parser = argparse.ArgumentParser(description="Razr settings and monitor")
    parser.add_argument("--autostart-bot",action="store_true")
    parser.add_argument("--app-dir")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        paths = application_paths(args.app_dir, args.config)
    except ValueError as exc:
        parser.error(str(exc))
    root = tk.Tk()
    app = RazrGUI(root, paths)
    app._apply_dark_theme()
    if args.autostart_bot:
        root.after(0,app.start_bot)
    root.mainloop()


if __name__ == "__main__":
    main()
