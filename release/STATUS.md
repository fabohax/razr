# Release verification status

As of 2026-10-05 (America/Lima): v0.1.0 is the initial prerelease; full release
sign-off is pending. No claim of completed 72-hour reliability testing or broad Linux/
Windows compatibility.

## Artifact and completed checks

- Linux x86_64 artifact: `dist/razr-gui` (54 MiB, generated, not committed).
- SHA-256: `1ad20b553c1fb72379dd90ae5043375c77623b85fb8ac81215ff373ee5de3a24`.
- Build: CPython 3.12.15, pinned `requirements-build.txt`, PyInstaller 6.22.3,
  Linux glibc 2.43 host. A compatible target system is still required.
- 111 offline tests; compile/import checks and whitespace validation passed.
- Real Tk GUI settings, health display, bounded output and graceful close passed.
- Real GUI → runner → public OKX → health → shutdown passed.
- Packaged first startup from `/tmp` initialized the bundled public template.
- Public closed-candle cycle, health and SIGTERM/state closure passed.
- Desktop and PipeWire sound test alerts completed with status 0 after adding
  pw-play support. Default sink volume was 34%, unmuted. Operator audibility
  confirmation remains pending.
- Login startup file toggles and absolute-path generation tested.
- Generated headless unit passed systemd verification; boot/linger calls tested
  using fakes. A real boot has not been tested.

## Running soak

- Directory: `/home/hax/.local/share/razr/soak-20261005`.
- User service: `razr-soak-fdbd3da03b`.
- Start: October 5, 2026, 20:12 America/Lima.
- Deadline: October 8, 2026, 20:12 America/Lima (October 9, 01:12 UTC).
- Isolated public OKX configuration, no desktop/sound or account access.
- Controlled 45-second fetch interruption showed four backoff attempts, then a
  healthy cycle. This is not a physical network failure test.
- Explicit service restart completed, preserved SQLite checkpoint, and returned
  to healthy; integrity check `ok`.
- Logs, event history, health snapshot and interruption markers are retained in
  the directory. The user manager must stay active; this run did not enable
  account lingering or persistent startup. Logout/shutdown can end coverage.

```bash
/home/hax/Documents/razr/.venv/bin/python /home/hax/Documents/razr/soak.py report \
  --app-dir /home/hax/.local/share/razr/soak-20261005
/home/hax/Documents/razr/.venv/bin/python /home/hax/Documents/razr/soak.py stop \
  --app-dir /home/hax/.local/share/razr/soak-20261005
```

## Remaining release gates

- Finish 72 hours and review full coverage, health, event continuity, duplicate
  identities, delivery failures and interruption recovery.
- Verify physical network failure and laptop suspend/resume where applicable.
- Run the executable on a distinct clean Linux target with compatible libraries.
- Verify actual startup at boot/login on the intended desktop.
- Confirm audible sound and intended output routing in the operator desktop.
- Hosted CI did not start; local tests passed. Rerun the workflow when hosting
  restrictions are resolved. Windows packaging/GUI remains unverified; notifications and
  automatic-startup adapters are Linux-only in this release.
