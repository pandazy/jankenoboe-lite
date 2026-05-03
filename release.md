<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.4

Two small review-page improvements. Template-only; no schema change,
no CLI change, no Python production edits.

### Highlights

- Polished the review page HTML to look better.
- Added a YouTube-search icon next to each artist and show as a
  fallback when stored media links don't work.

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
- 481 tests passing with 95% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
