<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.5

One additive CLI surface change to `review.py song-review`: a new
opt-in `--inline` flag returns the rendered review page directly in
the JSON envelope instead of writing it to disk. No schema change,
no template change, no breaking change to the existing CLI surface
or envelope shape.

### Highlights

- **`song-review --inline` returns the rendered HTML in the
  envelope.** With the flag, the Success_Envelope on stdout carries
  the rendered review page directly under a new `html` field (key
  set `{"html", "due_count", "offset"}`) and no file is written to
  `App_Root/output/`. The HTML is minified — inter-tag whitespace
  collapsed, HTML comments stripped — but `<script>` and `<style>`
  bodies pass through byte-identically so the existing XSS-safety
  contract on the embedded JSON payload is preserved unchanged. The
  default (no-flag) behavior is byte-identical to v0.1.4 — same
  file path scheme, same envelope `{"path", "due_count", "offset"}`.

### Install

1. Download `jankenoboe-lite-<YYYYMMDD>.zip` from the assets below.
2. Unzip into a fresh directory (becomes your `App_Root`).
3. Hand the tree to your AI agent.

No `pip install`, no venv, no build step on the target. Runtime is
Python 3.10+ stdlib only.

### Use it

You don't run the scripts by hand. Ask the agent in plain English:

- "What can this app do?"
- "Start a review session."
- "I have an AMQ export I want to import."
- "Find duplicate artists."

See `README.md` and `skills/README.md` inside the zip for the full
map.

### Verified on this build

- `ruff check` + `ruff format --check` clean
- `mypy` clean
- 486 tests passing with 95% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
