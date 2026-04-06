import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ccxt
import yaml

CONFIG_PATH = Path("config.yaml")

# Core fields edited in Settings tab.
FIELD_SPECS = [
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
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("razr")
        self.root.geometry("900x700")

        self.process: subprocess.Popen | None = None
        self.output_thread: threading.Thread | None = None

        self.vars: dict[str, tk.Variable] = {}
        self.secret_entries: dict[str, ttk.Entry] = {}
        self.secret_visible: dict[str, bool] = {}
        self.secret_buttons: dict[str, ttk.Button] = {}

        self.exchange_var = tk.StringVar(value="okx")
        self.symbol_var = tk.StringVar(value="BTC/USDT")
        self.exchange_values = sorted(ccxt.exchanges)
        self.symbol_values: list[str] = []

        self._build_ui()
        self.load_config()

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

        self.status_var = tk.StringVar(value="status: idle")
        ttk.Label(actions, textvariable=self.status_var).pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(parent, text="Bot Output", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.output_text = tk.Text(log_frame, height=20, wrap=tk.WORD)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.output_text.configure(
            state=tk.DISABLED,
            bg=SURFACE_ALT_COLOR,
            fg=TERMINAL_GREEN,
            font=("DejaVu Sans Mono", 10),
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

        cfg_frame = ttk.LabelFrame(parent, text="Config", padding=10)
        cfg_frame.pack(fill=tk.X)

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
        self.exchange_values = sorted(ccxt.exchanges)
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
                markets = exchange.load_markets()
                symbols = sorted(markets.keys())
                self.root.after(0, self._set_symbols, symbols)
            except Exception as exc:
                self.root.after(0, messagebox.showerror, "Markets", f"Could not load markets:\n{exc}")

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
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.insert(tk.END, line)
        self.output_text.see(tk.END)
        self.output_text.configure(state=tk.DISABLED)

    def load_config(self):
        if not CONFIG_PATH.exists():
            self._append_output("config.yaml not found. Fill fields and click Save Config.\n")
            return

        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as exc:
            messagebox.showerror("Config error", f"Could not read config.yaml:\n{exc}")
            return

        for name, typ in FIELD_SPECS:
            val = cfg.get(name)
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

    def _collect_config(self) -> dict:
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
        return cfg

    def save_config(self):
        try:
            cfg = self._collect_config()
        except ValueError as exc:
            messagebox.showerror("Validation error", str(exc))
            return

        try:
            with CONFIG_PATH.open("w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
        except Exception as exc:
            messagebox.showerror("Write error", f"Could not save config.yaml:\n{exc}")
            return

        self._append_output("Saved config.yaml\n")

    def _set_running_state(self, running: bool):
        self.run_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.status_var.set(f"Status: {'running' if running else 'idle'}")

    def start_bot(self):
        if self.process and self.process.poll() is None:
            messagebox.showinfo("Bot", "Bot is already running.")
            return

        self.save_config()

        self._append_output("Starting bot...\n")
        self._set_running_state(True)

        try:
            command = self._build_bot_command()
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._set_running_state(False)
            messagebox.showerror("Start error", f"Could not start bot:\n{exc}")
            return

        self.output_thread = threading.Thread(target=self._read_output, daemon=True)
        self.output_thread.start()

    def _build_bot_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, BOT_RUNNER_ARG]
        return [sys.executable, "main.py"]

    def _read_output(self):
        assert self.process is not None
        assert self.process.stdout is not None

        for line in self.process.stdout:
            self.root.after(0, self._append_output, line)

        rc = self.process.wait()
        self.root.after(0, self._append_output, f"\nBot exited with code {rc}\n")
        self.root.after(0, self._set_running_state, False)

    def stop_bot(self):
        if not self.process or self.process.poll() is not None:
            self._set_running_state(False)
            return

        self._append_output("Stopping bot...\n")
        try:
            self.process.terminate()
        except Exception as exc:
            self._append_output(f"Error stopping bot: {exc}\n")

    def on_close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Quit", "Bot is running. Stop and close?"):
                return
            self.stop_bot()
        self.root.destroy()


def main():
    if BOT_RUNNER_ARG in sys.argv[1:]:
        from main import main as bot_main

        bot_main()
        return

    root = tk.Tk()
    app = RazrGUI(root)
    app._apply_dark_theme()
    root.mainloop()


if __name__ == "__main__":
    main()
