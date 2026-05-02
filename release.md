<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite — first release

A small local app for memorising anime songs. One SQLite file, pure
Python stdlib at runtime, driven by an AI agent reading Claude-style
skill docs rather than by the user typing commands.

Built to drop onto restricted hosts — the code-execution sandbox
attached to an AI agent, or any Python 3.10+ environment where you
can't (or don't want to) run `pip install`.

## What's in the box

- **Six skills** under `skills/` covering the full workflow:
  `adding-songs-to-learning`, `reviewing-songs`, `searching-library`,
  `importing-amq-songs`, `merging-artists`, `cleaning-up-dead-records`.
- **Twelve runtime scripts** under `scripts/` — stdlib only, no
  third-party deps, no build step at the target.
- **Empty, schema-ready `db/datasource.db`** so the tree works the
  moment it's unzipped. `scripts/init_db.py` is a safe no-op if a
  populated DB is already in place.
- **Three-step AMQ import pipeline** (plan → resolve → add) that's
  idempotent past the disambiguation step.
- **Spaced-repetition learning** across 20 levels: wait between
  reviews grows from 1 day at level 0 to 574 days at level 19, with
  graduation at the top.
- **Soft-delete everywhere** plus a dry-run `cleanup.py` for hard
  deletes older than a cutoff.
- **HTML review sessions** rendered to `output/review_<EPOCH>.html`
  with every due song, escaped against injection.

## Install

1. Download `jankenoboe-lite-<YYYYMMDD>.zip` from the assets below.
2. Unzip into a fresh directory (becomes your `App_Root`).
3. Hand the tree to your AI agent.

No `pip install`, no venv, no build step on the target.

## Use it

You don't run the scripts by hand. Ask the agent in plain English:

- "What can this app do?"
- "Start a review session."
- "I have an AMQ export I want to import."
- "Find duplicate artists."

See `README.md` and `skills/README.md` inside the zip for the full
map.

## Verified on this build

- `ruff check` + `ruff format --check` clean
- `mypy` clean
- Test suite passes with ≥90% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
