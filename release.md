<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.3

One small consistency fix and one internal refactor. Both additive /
structural; no migration required.

### Highlights

- **`review.py song-review` now accepts `--offset N`.** Mirrors the
  flag `learning.py due` has had all along. Agents can now render the
  HTML review page for a shifted wall clock —
  `review.py song-review --offset 86400` previews tomorrow's session
  the same way `learning.py due --offset 86400` previews its row
  count. The rendered HTML reflects the shifted row set, and the
  Success_Envelope echoes `offset` back as a third field next to
  `path` and `due_count`. No-flag / `--offset 0` invocations produce
  byte-identical HTML and the same envelope plus one new `offset: 0`
  key.
- **Deduplicated the due-time predicate.** Both `learning.py due` and
  `review.py song-review` used to carry their own near-copy of the
  three-branch "is this record due?" SQL. The predicate now lives in
  exactly one place — `scripts/_common.py` as the module-level
  constant `DUE_TIME_CONDITION_SQL` — and both callers compose their
  full query via f-string interpolation. Eliminates the class of
  drift that caused v0.1.2's missing-offset regression. Observable
  behavior is byte-identical to the fix above.

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
