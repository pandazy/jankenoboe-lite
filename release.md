<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.2

One critical importer fix plus two small quality-of-life touches on
the agent-facing docs. Nothing to migrate — the legacy CLI, on-disk
schema, and existing scripted integrations are all unchanged.

### Highlights

- **AMQ importer now accepts the real AMQ export.** v0.1.1's field
  mapping was guessed from the design doc and didn't match the actual
  file AMQ produces — every user hit `INVALID_INPUT missing_field=artist_name`
  on the first real import. The preprocessor now walks the real nested
  paths (`songInfo.artist`, `songInfo.songName`,
  `songInfo.animeNames.english` / `songInfo.animeNames.romaji`,
  `songInfo.vintage`, top-level `videoUrl`) instead of the guessed
  flat keys. A committed copy of a real AMQ export drives an
  end-to-end integration test so the mapping can't drift silently
  again.
- **Skill docs: "if a script fails, report it — don't patch it."**
  `skills/README.md` gained a short top-of-file section telling
  agents to surface script errors to the user — code, message, and
  input — instead of editing the shipped `scripts/` tree from inside
  a task. Fixes go through the release pipeline, not through session
  patches.
- **Faster property-based test runs.** The PBT iteration count
  dropped from 20 to 5, cutting the full test-suite wall time from
  ~5.8 min to ~2.8 min. Aggregate randomness across the ~60
  property-based tests is still plenty for catching regressions; the
  bigger win is that `make check` stops being a coffee break.

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
- 475 tests passing with 95% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
