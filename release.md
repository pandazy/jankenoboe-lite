<!--
  This file is used as the body of GitHub Releases created by the
  `Release` workflow (.github/workflows/release.yml). Edit it before
  pushing a `v*` tag. GitHub's auto-generated changelog (commit/PR
  list) is appended below whatever you write here.
-->

## jankenoboe-lite v0.1.7

Bugfix release: the AMQ importer now treats the show romaji as a
required input and persists it into `show.name_romaji`. Before this
fix, `_resolve_show` hard-coded `name_romaji = None` on every
`show_to_create` block, so every newly-created show row landed with
`name_romaji = NULL` regardless of whether the source AMQ file
carried a romaji. The `show_name` column also conflated English and
romaji on English-missing entries (the v0.1.2 mapping listed
`animeNames.romaji` as a fallback under `show_name`). No new CLI
flags, no new error codes, no schema migration —
`show.name_romaji` already existed.

### Highlights

- **Romaji is required.** `_AMQ_FIELD_MAP` grew a new
  `show_name_romaji` row, marked required, fed by
  `songInfo.animeNames.romaji` (with a flat alias for the legacy
  shape). The `show_name` row dropped its romaji fallback —
  `show_name` is English-only now; romaji is its own field. An
  entry with English present and romaji missing is rejected with
  `INVALID_INPUT` and exit code 1, naming `show_name_romaji` as
  the missing field. The flat array shape on the legacy
  `--input` / positional / `--input-array` channels grew the same
  required key.
- **Romaji is persisted.** `_resolve_show` now reads
  `entry["show_name_romaji"]` and threads it onto every
  `show_to_create` block as `name_romaji`. The downstream
  `_ensure_show` in `import_resolve.py` was already wired to write
  the column — that pipe was just being fed `None` until now. Every
  newly-created show row carries a non-null `name_romaji` matching
  its source entry.
- **Discriminated rejection envelope.** The romaji rejection
  carries `details.kind = "missing_romaji"` (in addition to the
  existing `index`, `missing_field`, `available_keys`). The agent
  skill keys on this discriminator to enter the new recovery
  branch; every other `INVALID_INPUT` cause keeps its v0.1.6
  envelope shape unchanged.
- **Step 0 sniff in the agent skill.** `skills/importing-amq-songs/
  SKILL.md` gained a new pre-flight step that runs **before**
  `import_plan.py`. The agent walks each `songs[i]` looking for a
  non-empty romaji at the canonical path; on miss it classifies
  the failure mode against three named hypotheses (Shape drift,
  Truncated/malformed, Genuinely-empty), surfaces the actual
  observed keys, proposes a candidate recovery path, and asks the
  user to confirm. Silent on the success path.
- **Manual recovery via existing `data.py create`.** When the user
  confirms a Step 0 diagnosis, the agent extracts the romaji from
  the candidate path, inserts each affected show via
  `scripts/data.py create --kind show '{"name": ..., "name_romaji":
  ..., "vintage": ..., "s_type": null}'`, then re-runs the
  three-step pipeline. The classifier's existence query
  (`name = ? AND vintage = ?`) hits the freshly-created rows and
  emits a `show_id` instead of a `show_to_create`. No new script,
  no new flag — stays on existing rails.
- **Documentation lockstep.** `skills/importing-amq-songs/
  references/plan-shape.md` field-mapping table grew the
  `show_name_romaji` row; `show_to_create` example shows
  `name_romaji` as a non-null string; the English-falls-back-to-
  romaji note is gone.

### Behaviour preserved

- `show.name_romaji` was already a real column in
  `scripts/schema.sql` and `_common.EXPECTED_SCHEMA["show"]`. No
  schema migration. `tests/fixtures/schema.sql` is byte-identical.
- Rejection envelopes for every other missing required field
  (`artist_name`, `song_name`, `show_name`, `vintage`) keep the
  v0.1.6 shape — only the romaji rejection carries `details.kind`.
- The classifier's existence query for shows still keys on
  `(name, vintage, status = 0)` only. Re-running an import on the
  same AMQ file is still idempotent.
- The four input channels (`--input`, positional path,
  `--input-jsonpath`, `--input-jsonstr`, `--input-array`) keep
  their existing dispatch semantics. `--input-array` still
  rejects nested AMQ shapes with `INVALID_INPUT`.
- `scripts/import_resolve.py`, `scripts/_common.py`,
  `scripts/schema.sql` are byte-identical to v0.1.6.
- Every script outside the importer (`learning.py`, `query.py`,
  `merge_artists.py`, `cleanup.py`, `add_play_history.py`,
  `init_db.py`, `data.py`, `review.py`) is byte-identical.

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
- 527 tests passing with 95% line coverage across `scripts/`
  (enforced by `tests/coverage_runner.py`)
