---
name: importer-architecture-pointers
description: File and line pointers into the AMQ import surface — scripts, skills, schema columns, and the parent specs that govern them.
metadata:
  type: reference
---

The AMQ import is a three-step pipeline plus an agent skill body:

- `scripts/import_plan.py` — step 1 (plan). Hosts `_AMQ_FIELD_MAP`
  (path-tuple table; see Decision 1 in
  `.kiro/specs/amq-real-export-shape-fix/design.md`),
  `_get_nested`, `_amq_entry_to_flat`, `_flatten_amq`,
  `_discriminate`, `_resolve_show`, `_classify`. The
  `--input` / positional / `--input-jsonpath` / `--input-jsonstr` /
  `--input-array` flag set is the four-channel input surface.
- `scripts/import_resolve.py` — step 2 (resolve ambiguous artists,
  create missing shows / songs / artists).
- `scripts/add_play_history.py` — step 3 (write play_history rows
  and upsert rel_show_song).
- `scripts/data.py` — escape hatch (`create` / `update` / `delete` /
  `bulk-reassign`) used for last-resort recovery.
- `scripts/_common.py` — shared helpers (`open_db`, `now_epoch`,
  `KnownError`, `success`, `decode_data`, `MAX_LEVEL`, the error
  envelope contract).
- `scripts/schema.sql` — `show.name_romaji` is a real column today;
  no migration is needed to start persisting the romaji.
- `skills/importing-amq-songs/SKILL.md` — agent recipe; Checklist
  goes init-db → step 1 → review ambiguous → write answers.json →
  step 2 → step 3.
- `skills/importing-amq-songs/references/plan-shape.md` — JSON
  contract for `plan.json` / `answers.json` / `triples.json`, plus
  the AMQ → flat field mapping table.
- `skills/README.md` — top-level skills index. States the
  "if a script fails, report it" rule and the dedicated-command
  preference.

Specs that govern this surface, in order:

1. `.kiro/specs/anime-song-learning-app/` — the parent spec; defines
   the Success/Error envelope contract (R3), the approved error code
   set, the `BEGIN IMMEDIATE` write-transaction wrapper, the
   `MAX_LEVEL` invariant, etc.
2. `.kiro/specs/importer-and-graduate-fixes/` — v0.1.1; introduced
   the AMQ-to-flat preprocessor and the four-channel input surface.
3. `.kiro/specs/amq-real-export-shape-fix/` — v0.1.2; corrected the
   `_AMQ_FIELD_MAP` after the v0.1.1 mapping was discovered to be
   guessed rather than verified against the real AMQ export at
   `tests/fixtures/amq_song_export-small.json`.
4. `.kiro/specs/amq-import-romaji-required/` — open as of 2026-05-17;
   see [[open-spec-amq-import-romaji-required]].

Tests live under `tests/`. The AMQ-shape fixture is at
`tests/fixtures/amq_song_export-small.json` and is read-only for
every test that consumes it.
