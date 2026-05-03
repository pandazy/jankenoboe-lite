<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.1

Four fixes on the importer, learning, and skills-documentation
surfaces. Nothing to migrate — the legacy CLI calls and the on-disk
schema are unchanged.

### Highlights

- **AMQ importer accepts the raw AMQ JSON directly.** Three new
  mutually-exclusive flags on `scripts/import_plan.py` —
  `--input-jsonpath PATH` (raw AMQ or flat array), `--input-jsonstr
  JSON` (inline JSON, both shapes), `--input-array JSON` (inline
  flat-only). The legacy `--input` / positional path keeps working
  exactly as before.
- **`learning.py graduate` now pins `level` to `MAX_LEVEL`.** The
  same UPDATE that sets `graduated = 1` also sets `level = 19`, so a
  song graduated via the explicit command ends in the same row state
  as one graduated via `levelup` at the top of the spaced-repetition
  curve.
- **Skill docs gained a dedicated-command preference.**
  `skills/README.md` now steers agents toward dedicated commands
  (e.g. `learning.py graduate`) over raw `data.py` CRUD for work that
  has a dedicated path, with the graduate invariant called out as
  the worked counter-example.
- **Combined-search examples in the search skill.**
  `skills/searching-library/SKILL.md` gained a worked-examples
  section covering the four combined-intent pairings (song+show,
  song+artist, artist+show, all-three) mapped onto the existing
  `query.py search-songs` flags.

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
- 469 tests passing with 95% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
