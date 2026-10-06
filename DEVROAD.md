# Razr development roadmap

Reviewed: 2026-10-05 · Baseline commit: `e2d0f1b`

## Target outcome

A reliable, read-only signal bot for one configured spot market, initially OKX
BTC/USDT at 1m. It should evaluate confirmed candle closes, record each MACD
crossover once, deliver useful alerts, recover from temporary outages, and expose
whether its data and delivery channels are healthy. A signal is an indicator event;
this roadmap does not assume it predicts a profitable trade.

Keep the current Python CLI and Tkinter GUI. Complete the single-market flow
before adding exchanges, strategies, or multiple symbols. Order execution,
account access, leverage, and automatic trading are outside the initial release.

## Current project status

The repository is a prototype with the main components present, but its operational
reliability is not yet demonstrated.

| Area | Implemented | Gap / implication |
| --- | --- | --- |
| Market data | `utils.py` creates a configurable CCXT exchange, loads markets, fetches OHLCV and ticker data | No capability, symbol, timeframe, freshness, ordering, or candle completeness validation |
| Indicators | `indicators.py` computes MACD with pandas exponential moving averages | Imports `pandas_ta` despite never using it; no warm-up eligibility gate or reference fixtures |
| Signals | BUY/SELL crossings between the last two rows | Last row can be unfinished; transient intrabar crosses can generate alerts |
| Signal identity | `main.py` remembers the last BUY/SELL direction | Memory only; restart duplicates and missed same-direction events after unseen intervening crosses |
| Strength label | `detect_macd_signal()` checks histogram sign | BUY implies a positive histogram and SELL a negative one, so every detected crossover is marked strong |
| Historical analysis | `backtest_signals()` counts crosses in the downloaded window | Not a trade backtest: no positions, execution assumptions, costs, or returns; recomputed each poll even with debug off |
| Alerts | Console, file log, Linux desktop notification, sound | Subprocess exit codes are ignored and there are no timeouts; delivery failure can be treated as success |
| Recovery | Network retries, reconnection, wall-clock suspend detection | Initial config/connection failures occur outside loop recovery; no catch-up processing, persistent state, or bounded backoff policy |
| Configuration | YAML and GUI field editing | CLI accepts unchecked settings; GUI checks integer parsing but not ranges; example credentials are nonempty placeholders |
| GUI | Settings, market refresh, subprocess start/stop, streamed output | `start_bot()` proceeds even if saving fails; relative paths depend on launch directory; shutdown is not awaited |
| Packaging | Linux/Windows build scripts and PyInstaller spec | No verified packaged run; notifications use Linux commands even on Windows; no bundled config template in spec |
| Verification | No committed test suite or CI workflow found | Clean install, live data, desktop delivery, and executable behavior remain unverified |

### Checks performed for this review

- Working tree was clean before this document was created.
- All five Python source files passed AST syntax parsing under Python 3.14.4.
- In the available interpreter, `ccxt`, `pandas`, `pandas_ta`, `colorama`,
  `tkinter`, and `pytest` are missing; PyYAML is available. No project `.venv`
  is present. This is an environment finding, not proof that installation fails.
- No live exchange requests, GUI sessions, dependency installations, trading
  operations, or packaged builds were performed. Runtime readiness is unknown.
- Local `config.yaml` is ignored by Git; its credential contents were not inspected.

## Delivery sequence

Each phase depends on the previous phase's exit criteria. Estimates are planning
guidance for one developer, not verified delivery dates.

### Phase 1 — Reproducible startup (1–2 days)

- [x] Remove the unused `pandas_ta` import and dependency, or deliberately adopt
  it with tested numerical compatibility. Prefer the existing pandas calculation.
- [x] Choose and document a supported Python version after a clean install check;
  lock tested runtime dependencies and separate build/test tooling.
- [x] Make public market data the default: blank credentials in the example,
  no mandatory API-key setup, and rejection of placeholder credentials when
  authenticated mode is explicitly requested.
- [x] Share a typed configuration validator between CLI and GUI. Require a YAML
  mapping, positive MACD periods with `fast < slow`, positive polling interval,
  sufficient history, nonnegative resume grace, and supported notification urgency.
- [x] Validate `fetchOHLCV` support, market existence/type, timeframe support,
  and history limits after loading exchange metadata. Initially support only the
  validated OKX spot configuration; other selections should receive clear errors
  until individually verified.
- [x] Resolve config, logs, and state from an explicit writable application directory
  with a CLI override; avoid dependence on the caller's working directory.
- [x] Add `--check-config`, `--once`, and a notification-disabled mode for controlled
  verification. Invalid settings should exit with a concise actionable error.
- [x] Fix GUI saving to return success/failure and prevent launch after failure.

**Exit criteria:** a fresh environment can install dependencies, validate the
example without credentials, and run one public-data cycle. Invalid settings fail
before polling; GUI and CLI enforce the same rules.

**Completed: 2026-10-05.** Supported runtime: CPython 3.12 (clean install
verified on Linux with 3.12.15). Runtime, build, and test dependencies have separate
fully pinned requirements files; platform-specific dependencies carry markers.
Shared `Settings` validation and atomic GUI saving are implemented in `config.py`.
Application paths default to the per-user data directory, with `--app-dir` and
`--config` overrides. The state path is reserved for Phase 2; no persistent state
is implemented in this phase. Public mode never forwards configured credentials.

Verification evidence:

- Fresh isolated environment: `python -m pip install -r requirements.txt` succeeded;
  `python -m pip check` reported no broken requirements.
- `--check-config` accepted the blank-credential example without network access.
- `--once --no-notifications` validated live OKX spot metadata and processed 200
  public candles, exiting with status 0, including a run launched from `/tmp`.
- `python -m pytest -q`: **31 passed**. Covers invalid settings, metadata rejection,
  ignored public credentials, path resolution, one-cycle success/failure,
  notification suppression, shared GUI validation, and failed-save launch prevention.
- Tkinter construction, default settings, successful save, and absolute runner
  command were checked using a withdrawn real Tk window.
- Python compilation and `git diff --check` passed.

Windows packaging and desktop alert delivery remain unverified. Closed-candle
selection, EMA warm-up eligibility, and persistent event identity remain Phase 2
work; a successful startup cycle does not establish signal correctness.

### Phase 2 — Correct, repeatable signals (2–3 days)

- [x] Normalize OHLCV timestamps to UTC, sort rows, reject conflicting duplicate
  timestamps, malformed/nonfinite values, and invalid OHLC relationships.
- [x] Evaluate only closed candles. For the initial fixed-duration 1m market,
  require candle open time + timeframe duration to be earlier than trusted current
  time minus a small configurable close grace. Do not simply drop the last row:
  some responses already end on a closed candle.
- [x] Detect stale data and missing intervals. Suppress live alerts on stale input;
  fetch missing history or report an explicit unresolved gap before continuing.
- [x] Define EMA seeding and warm-up requirements, including extra history before
  eligible signal candles. Verify outputs against fixed numerical fixtures and
  test whether additional history materially changes recent values.
- [x] Process all unseen closed candles chronologically, rather than just the latest
  pair. Set a first-start baseline so historical crossings do not flood alerts.
- [x] Persist a processing watermark and events in SQLite. Use a unique event key
  containing exchange, market type, symbol, timeframe, strategy version/parameters,
  candle opening timestamp, and direction. Change strategy settings into a new
  processing namespace rather than reusing an incompatible watermark.
- [x] Commit event insertion, per-channel delivery jobs, and watermark updates in
  one transaction. Repeated polls and restarts must not create duplicate events.
- [x] Remove the current strong/weak claim. Any later strength metric must have a
  separate definition, tests, and evaluation evidence.
- [x] Include exchange, market, direction, candle open/close times with UTC label,
  candle close price, indicator values, strategy version, and event ID in alerts.
  Keep optional live ticker price visibly separate from the signal candle price.
- [x] Define recovery policy: store missed signals and mark them as recovered;
  deliver only those within a configurable alert-age limit. Flag longer gaps that
  exceed available history rather than silently skipping them.

**Exit criteria:** fixture replay produces the expected crossing events; unfinished
candles cannot trigger alerts; identical polling data and restart replay preserve
event counts; missed candles are processed in order; stale/gapped input cannot
produce an apparently current alert.

**Completed: 2026-10-05.** Strict UTC normalization, closed-candle eligibility,
freshness and interval checks are implemented in `market_data.py`. The host UTC
clock must be synchronized; default close grace is 2s and staleness limit is 120s.
Missing intervals are explicitly rejected, including catch-up beyond available
history; the watermark is retained rather than silently skipping candles.

`signals.py` uses first-close EMA seeds (`adjust=False` convention), requires
`5 * slow + signal` closed candles for first-start warm-up, and persists EMA
accumulators with the watermark. First startup and changed strategy parameters
establish a baseline without historical alerts. `state.py` commits unique events,
per-channel jobs and checkpoint changes atomically. Recovered events are stored;
only events within the configurable 300s age limit are queued. Alerts contain
UTC candle times, candle price, strategy parameters/version and event identity.
The tautological strength label and hot-loop audit/ticker calls were removed.

Verification evidence:

- `python -m pytest -q`: **49 passed**, without network or credentials. Includes
  fixed rational MACD fixtures, seed convergence, equality boundaries, malformed
  and duplicate rows, unfinished candles, staleness, missing intervals, baseline,
  chronological recovery, repeated BUY events separated by SELL, parameter
  namespaces, restart replay, saved EMA consistency, atomic rollback and pending
  jobs after delivery failure.
- Public OKX `--once --no-notifications`: **199 closed candles**, status 0,
  SQLite baseline created and zero historical alerts.
- Python compilation and `git diff --check` passed.

External deliveries may repeat after a crash between sending and acknowledgment.
Delivery retry scheduling, process exclusivity and broader recovery/health work
remain Phase 3. Missing-history backfill is not automatic: the explicit unresolved
error branch satisfies this phase's gap policy.

### Phase 3 — Reliable delivery and recovery (2–3 days)

- [x] Make console/log output available without a desktop. Desktop and sound should
  be optional channels with capability checks, checked exit codes, and timeouts.
- [x] Persist per-channel delivery status, retry count, and next retry time. Retry
  transient failures without recalculating or recreating the signal event.
- [x] Document delivery semantics: one stored event per identity; external delivery
  may repeat if a crash occurs after sending but before acknowledging. Do not
  claim exactly-once desktop delivery.
- [x] Add bounded exponential backoff with jitter for transient network/API errors,
  honor rate limits, and distinguish invalid configuration from recoverable faults.
  Apply the recovery policy during initial connection as well as polling.
- [x] Use monotonic time for retry/poll deadlines and UTC wall time for market
  timestamps. After suspend, reconnect, check freshness, and process missed closes.
- [x] Add rotating logs and periodic health output: last successful fetch, last
  processed close, data lag, pending/failed deliveries, and current retry state.
  Redact credentials and avoid logging private exchange configuration.
- [x] Handle SIGINT/SIGTERM cleanly, finish or roll back state writes, and prevent
  two runners from sharing the same state directory accidentally.
- [ ] If unattended remote delivery is needed, add one optional channel such as
  Telegram with secrets in environment variables, a test-send command, and the
  same delivery queue. Desktop delivery is sufficient for the first local release.

**Exit criteria:** simulated outages, rate limits, notification failures, restart,
and suspend/recovery leave a coherent event history. Headless mode works without
desktop utilities; failures appear in health output; retries remain bounded.

**Completed: 2026-10-05 (local delivery scope).** Desktop and sound are
independently optional, capability-checked Linux adapters with checked exit status
and 10s timeouts. Headless console/log works without either adapter. SQLite
migrates Phase 2 jobs additively and persists status, failure count, next retry UTC,
error category and update time. Transient delivery failures use exponential
backoff with jitter and a configurable five-failure budget; unavailable channels
fail explicitly. `--retry-failed` requeues failed jobs without recreating events.
External delivery can repeat after a send-before-ack crash; event identity remains
unique. No exactly-once external delivery is claimed.

Startup and polling transient faults share bounded exponential backoff. CCXT rate
limiting remains enabled; numeric/date `Retry-After` can extend the local cap.
Permanent exchange/configuration errors stop rather than retry indefinitely.
Monotonic deadlines and UTC market timestamps are separate. Detected suspend or
clock discontinuity reconnects and checks freshness before chronological catch-up.
Missing history still raises an explicit unresolved error instead of advancing.

Health output reports fetch/processed times, data lag, pending/failed jobs and
retry timing. Logs rotate at 5 MiB with three backups. Library errors are logged
as categories to avoid leaking credentials or private response bodies. An OS-held
lock protects the application directory; SIGINT/SIGTERM interrupt scheduler waits,
then close state/exchange and release the lock. In-flight HTTP/subprocess work is
bounded by its timeout. Shared CLI/GUI configuration includes recovery/channel
settings, and the settings panel scrolls to keep them accessible.

Verification evidence:

- `python -m pytest -q`: **72 passed**. Includes persisted retry deadlines and
  budgets, restart, schema migration, permanent channel failure, expiration,
  requeue identity, checked subprocess timeout/status, initial and polling outage,
  rate-limit delay (including metadata startup), suspend catch-up, headless mode,
  cross-process lock exclusion, real SIGTERM during network backoff, SQLite
  integrity after shutdown, rotating logs and secret-safe error logging.
- Real withdrawn Tkinter window: settings construction and shared validated
  configuration save passed, including the new recovery fields.
- Live public OKX `--once --no-notifications`: **198 closed candles**, status 0,
  healthy report, zero first-start alerts and clean state shutdown.
- Python compilation and `git diff --check` passed.

Telegram is conditional and remains deferred: unattended remote delivery was not
requested; local desktop/console/log is the initial release scope. Actual desktop
and sound delivery, Windows behavior and a long-running soak remain manual release
gates; simulated adapters establish failure handling, not target desktop readiness.

### Phase 4 — Verification and historical evaluation (2–3 days)

- [x] Add deterministic tests for MACD fixtures, equality boundaries, warm-up,
  empty/short data, NaNs, closed-candle filtering, duplicate rows, gaps, and staleness.
- [x] Add integration tests with a fake exchange and temporary SQLite database for
  multiple polls, repeated directions separated by missed opposite crossings,
  first-start behavior, parameter changes, crash/restart, and delivery failures.
- [x] Rename the existing backtest function to signal audit, move it out of the
  hot polling path, and provide an offline replay command with exported event data.
- [x] If evaluating strategy performance, separately define a long-only spot
  simulation: entry no earlier than the next candle after a confirmed signal,
  SELL exits an existing position, and fees/slippage are configurable. Report
  assumptions, sample coverage, trade count, drawdown, returns, and a benchmark.
  Split development and evaluation periods and prevent future-data leakage.
- [x] Add CI for supported Python versions: install, compile/import checks, and
  deterministic tests. Keep live API and desktop checks as explicit manual gates.

**Exit criteria:** offline tests pass without credentials or network access; an
exported replay can be reproduced; any performance report states its assumptions
and limitations. Profitability is not a prerequisite for technical correctness.

**Completed: 2026-10-05.** `replay.py` reads historical JSON/CSV without
network access or touching live state. It reuses the production signal processor
with in-memory SQLite, honors the warm-up baseline and explicit closed-candle
cutoffs, and exports deterministic JSON events plus coverage, parameters, strategy
version and input hashes. `backtest_signals()` was replaced by `signal_audit()`;
audit and simulation are absent from the live polling path.

Optional simulation is long-only, starts flat at an explicit evaluation boundary,
executes confirmed signals at the following candle open and applies configurable
fees/slippage. It reports trade records/count, open positions, marked equity,
returns, candle-close drawdown, a comparable buy-and-hold benchmark, sample
coverage and explicit assumptions. Development candles warm the indicator; their
signals cannot open evaluation positions. There is no automatic parameter tuning,
no final forced liquidation and no claim of profitability. The committed sample
is synthetic and labeled as such, not a market performance evaluation.

Verification evidence:

- **95 tests passed** with socket connections and DNS blocked by an autouse
  fixture. Coverage includes fixed numerical fixtures, NaNs, empty/short data,
  equality/warm-up boundaries, closed candles, gaps/staleness, multi-poll replay,
  parameter namespaces, restart, queue rollback/failure and send-before-ack crash.
- The committed 240-candle synthetic fixture yields **8 events** matching saved
  direction/timestamp fixtures and independent pandas batch indicator values.
  Two CLI simulation exports with the same split/parameters are byte-identical.
- Tests verify next-open execution/cost arithmetic, SELL without a position,
  final-candle nonexecution, open-position marking, evaluation starting flat,
  and invariance of earlier signals/results when future data changes.
- Fresh CPython **3.12.15** environment installed the pinned test lock; dependency
  compatibility, compile/import checks and the offline suite passed.
- `.github/workflows/verify.yml` runs installation, dependency checks, compilation,
  imports, deterministic tests and replay reproducibility on supported Python 3.12.
  The workflow was verified locally; a hosted GitHub Actions run is not yet observed.
- `git diff --check` passed. Live API, desktop/sound and soak remain explicit manual
  gates and are not part of automated CI.

### Phase 5 — Operator experience and release (1–2 days plus soak)

- [x] Show starting, healthy, stale, retrying, failed, and stopped states in the GUI,
  along with last candle time and pending delivery count.
- [x] Bound GUI output history, handle process exit consistently, and wait for
  graceful shutdown with a timeout and forced termination fallback. Ensure background
  callbacks do not update a destroyed window.
- [x] Bundle the example configuration and document first-run writable paths for
  source and frozen applications. Test launching from a different directory.
- [ ] Verify the Linux executable on a clean target machine. Either implement and
  test Windows notification adapters or document Windows as console/log-only;
  build-script presence alone is not cross-platform support.
- [x] Update README setup, public-data operation, signal meaning, health states,
  recovery policy, state backup, and troubleshooting. Provide a tested headless
  service example using concrete user paths rather than literal `$USER` values.
- [ ] Run a 72-hour OKX public-data soak with recorded health, event history, a
  restart, a deliberate network interruption, and laptop suspend/resume where applicable.

- [x] Add opt-in automatic startup: GUI/login launcher and a headless systemd
  user service with boot/linger support, absolute paths and disable/status controls.

**Exit criteria:** an operator can install, start, confirm health, receive a test
alert, recover after restart, and stop the bot using documented steps. Soak results
show no unexplained event duplication, skipped eligible candles, or silent failures.

**Implementation completed: 2026-10-05. Release gates still pending.**
Atomic `health.json` snapshots expose run identity, state, candle time and delivery
counts to the GUI. UI output is capped at 2000 lines and worker messages use a
bounded main-thread queue. Process exit is reconciled by the UI pump; closing
waits for SIGTERM, then a 45s timeout and kill/5s fallback. Late callbacks cannot
update destroyed widgets. First start creates a public configuration without
replacing existing files, using the bundled template for frozen applications.
`--test-alert` and the GUI test action check local delivery without creating a
strategy event or contacting the exchange.

Automatic startup is opt-in. The GUI toggle writes an XDG login launcher that
starts the GUI and bot; `startup.py --enable --mode service --boot` configures a
headless systemd user service and requests user lingering. Startup modes are
mutually exclusive; disabling the service stops it. Disabling Razr does not
remove account lingering needed by other services. Actual reboot behavior is
not yet observed.

Verification evidence:

- **110 offline tests passed**, including initialization/template preservation,
  health identity, all operator states, bounded queues/output, delayed close,
  forced termination, stale process exit, login startup enable/disable, service
  generation/boot calls, unmanaged-file protection, test-alert failures, bounded
  monitoring and isolated soak supervision.
- Real Tkinter: settings save, rendered health, output cap and graceful close
  passed with a child process. A separate live GUI + public OKX + child runner
  run reached healthy and closed cleanly.
- Linux one-file executable built with the pinned build lock. From `/tmp`, a
  minimal environment with no project Python/venv in PATH initialized bundled
  public defaults; a live cycle processed **199 closed candles**, status 0.
  The final binary passed live health and graceful SIGTERM/state closure checks.
- A packaged desktop TEST ALERT was delivered successfully. Sound is unavailable
  on this host (no paplay/play); sound delivery remains unverified.
- Generated headless unit passed `systemd-analyze --user verify`; a real transient
  user service is running the soak. Compile/import and `git diff --check` passed.

**72-hour soak running:** isolated directory
`/home/hax/.local/share/razr/soak-20261005`, user unit
`razr-soak-fdbd3da03b`. Started 2026-10-05 20:12 America/Lima; scheduled end
2026-10-08 20:12 America/Lima. Public credentials-free configuration and console/log
only. The initial controlled 45s fetch outage produced four bounded retries and
returned to healthy; a subsequent service restart retained SQLite processing state
and returned to healthy. Current SQLite integrity is `ok`. `soak.py report` writes
an evidence summary without claiming the release gate passed. The user manager
must remain active for the run; no actual system suspend/reboot was performed.

Do not mark this phase/release fully verified yet: the full soak, a distinct clean
Linux target, actual boot and sound checks remain pending. Windows is documented
as console/log-only and is not a verified target. See `release/STATUS.md`.

## Suggested implementation boundaries

Keep modules small and evolve the current structure rather than rewriting it.

| Module | Responsibility |
| --- | --- |
| `main.py` | Startup, polling orchestration, recovery, shutdown |
| `config.py` (new) | Validated settings and application paths shared with GUI |
| `utils.py` / `market_data.py` | Exchange adapter, UTC OHLCV normalization, close/freshness checks |
| `indicators.py` | Pure MACD computation and crossing detection |
| `state.py` (new) | SQLite schema, event uniqueness, watermarks, delivery queue |
| `alerts.py` | Channel adapters with explicit delivery outcomes and timeouts |
| `replay.py` (new) | Offline signal audit and optional trade simulation |
| `gui.py` | Settings and operator controls using shared validation |
| `tests/` (new) | Fixtures, fake exchange, deterministic unit/integration checks |

## Release checklist

- [x] Public-data startup needs no exchange credentials.
- [x] Only valid, fresh, closed candles generate eligible signals.
- [x] MACD convention and warm-up are documented and fixture-tested.
- [x] Event identity and processing state survive restart.
- [x] Outage catch-up and old-alert behavior are explicit and tested.
- [x] Delivery failures remain visible and retryable.
- [x] GUI saving, starting, stopping, and launch paths are verified.
- [ ] Clean installation, CI, target-platform smoke checks, and soak pass.
- [x] README distinguishes indicator events, signal audit, and performance simulation.

Start with Phase 1, then closed-candle evaluation and persistent event identity in
Phase 2. These unblock meaningful live verification. Additional indicators,
multi-market scanning, dashboards, and automatic execution should wait until the
release checklist is complete.

### Sound follow-up — 2026-10-05

The installed PipeWire player (`pw-play`) was previously ignored because adapters
only checked paplay/play. Added PipeWire support; source playback completed with
status 0 and the regression suite now has **111 passing tests**. The executable
is rebuilt with this fix. Operator confirmation of audible output remains useful;
a successful command alone cannot establish speaker volume or output routing.
