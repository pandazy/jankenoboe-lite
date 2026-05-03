<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.4

One internal refactor. Pure structural change, byte-identical
observable behavior.

### Highlights

- **Deduplicated the due-time predicate.** Both `learning.py due` and
  `review.py song-review` used to carry their own near-copy of the
  three-branch "is this record due?" SQL. The predicate now lives in
  exactly one place — `scripts/_common.py` as the module-level
  constant `DUE_TIME_CONDITION_SQL` — and both callers compose their
  full query via f-string interpolation of that constant. Fixes the
  class of drift that caused v0.1.2's missing-offset regression on
  the review page. Every row set, HTML byte, and JSON envelope is
  byte-identical to v0.1.3.

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
- 480 tests passing with 95% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
