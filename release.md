<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.6

One additive CLI surface change to `learning.py`: a new `leveldown`
subcommand drops one or more learning records back to a strictly-
lower stored level when the user realises they forgot a song
mid-review. No schema change, no breaking change to any existing
subcommand.

### Highlights

- **`learning.py leveldown --ids L1,L2,... --to-level N`** sets
  `level = N`, resets `last_level_up_at` and `updated_at` to
  `now_epoch`, and leaves `level_up_path`, `graduated`,
  `created_at`, `id`, and `song_id` untouched. The next review of a
  leveled-down record is scheduled `level_up_path[N]` days from the
  forget event (not from the original level-up time). `--to-level`
  must be in `[0, MAX_LEVEL]` and strictly below each record's
  current level; the op is batch and all-or-nothing.
- **Preflight mirrors `levelup`.** Range-checks `--to-level`
  (`INVALID_INPUT` with `min`/`max` echo), then rejects in this
  order: any missing id → `NOT_FOUND`, any graduated id →
  `ALREADY_GRADUATED`, any row with `level <= --to-level` →
  `INVALID_INPUT` carrying an `offenders` array `[{id, level,
  display_level}, ...]`. The whole call runs in one
  `BEGIN IMMEDIATE` transaction; any preflight failure rolls back
  with no partial writes.
- **Re-engaging a graduated song stays the job of `learning.py
  batch`.** Per the existing R6.3 re-learn path, calling
  `batch --song-ids <S>` on a song whose every learning row is
  graduated inserts a fresh row at `RE_LEARN_LEVEL = 7` (display
  8). `leveldown` deliberately does NOT un-graduate rows — the
  per-cycle history stays clean.
- **Skill-doc update for the agent.** `skills/reviewing-songs/
  SKILL.md` now teaches the agent to call `leveldown` when the user
  says they forgot a song, and to fall back to `batch --song-ids`
  when `leveldown` returns `ALREADY_GRADUATED`. The skill
  description trigger list grew to include "forgot" and "level
  down".

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
- 521 tests passing with 95% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
