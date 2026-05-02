# Python Version for Local Development

**Use Python 3.12 for the local `.venv` until this note says otherwise.**

The deploy sandbox runs Python 3.12, so dev should match. The runtime
(`scripts/`) stays stdlib-only and works on any 3.10+ interpreter — the
constraint below is about the dev tooling, not about what the app
needs at runtime.

## Why 3.12 specifically

The test harness (`tests/coverage_runner.py`) relies on `coverage.py`'s
subprocess-tracing feature. That feature is plumbed through a
`sitecustomize.py` shim and a C tracer extension that ships with the
pinned `coverage==7.6.10` from `requirements-dev.txt`.

On Python 3.14 (and likely 3.13), that tracer silently fails to write
per-subprocess `.coverage.<pid>` files for any script invoked through
`subprocess.run`. The tests themselves still pass — the harness just
reports near-zero coverage for every script under `scripts/`. The
failure mode is easy to miss: pytest exits 0, and only the coverage
report at the end hints that anything went wrong.

The root cause is the pinned `coverage` release predating CPython's
newer tracer wiring (`sys.monitoring` was added in 3.12, and the
C extension's startup path shifted in later versions). `coverage.py`
itself is fine — the pinned version is just too old for newer
interpreters.

## What "until this note says otherwise" looks like

Once a newer `coverage` release with stable tracer support on
3.13+ is pinned in `requirements-dev.txt`, and `./tests/run.sh`
produces ≥90% coverage on that interpreter locally, this note can
be updated (or removed) and the CI workflow's `python-version`
bumped to match.

Until then:

- `.venv` is created with `python3.12` (see `make setup`).
- `.github/workflows/release.yml` pins `python-version: "3.12"`.
- CI and local dev stay lockstep with the deploy sandbox.

## If you see near-zero coverage

Before investigating anything else, check the interpreter:

```bash
.venv/bin/python3 --version
```

If it's anything newer than 3.12, rebuild the venv with 3.12
explicitly:

```bash
rm -rf .venv
python3.12 -m venv .venv
make setup  # or: .venv/bin/pip install -r requirements-dev.txt
```
