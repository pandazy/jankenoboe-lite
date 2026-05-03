# Implementation Plan

This task list translates `design.md` into an executable plan for four
independent defects in the importer and learning pipelines and the two
skills documents that steer agents through them. The order below is:
one exploration test per bug up front (all four MUST fail on unfixed
code — the failures are the evidence), then the live-code fixes (Bugs 1
and 2) with their helpers, unit tests, preservation PBTs, and integration
tests, then the doc fixes (Bugs 3 and 4) on top, then a final verification
block and per-bug-group commit instruction.

Tests that encode the Bug 2 buggy behavior
(`test_graduate_flips_graduated_flag` and
`property/test_graduate_property.py`) are updated in place as part of the
Bug 2 fix, not preserved verbatim. Every other existing test stays
byte-identical.

## Bug condition exploration tests (all fail on unfixed code)

- [x] 1. Write bug condition exploration tests for all four bugs
  - **CRITICAL**: Every sub-task below MUST FAIL on current code — failure confirms the bug condition.
  - **DO NOT attempt to fix the tests or the code when they fail.**
  - **NOTE**: These tests encode the expected behavior — they will validate each fix when they pass after implementation.
  - Land all four exploration tests in a single pass so the "unfixed baseline" is captured in one place before any fix touches live code or docs.

  - [x] 1.1 Bug 1 exploration test — raw AMQ via `--input-jsonpath`
    - **Property 1: Bug Condition** — Importer rejects raw AMQ and new flags on unfixed code
    - Add a new integration test `test_raw_amq_via_input_jsonpath_matches_flat_via_input` to `tests/integration/test_import_plan.py` (style matches `test_resolved_exact_match_with_existing_show`).
    - Seed the temp DB with one live artist, one live song, one live show using `insert_artist` / `insert_song` / `insert_show`.
    - Write two JSON files under `tmp_app_root`:
      - `amq_raw.json` — the raw AMQ export shape: `{"songs": [{"songArtist": "...", "songName": "...", "animeEnglishName": "...", "animeRomajiName": "...", "vintage": "...", "audio": "..."}], "quizSettings": {...}}` (the extra top-level siblings are there on purpose to prove they are dropped).
      - `amq_flat.json` — the flat five-field array that corresponds to the same single song: `[{"artist_name": ..., "song_name": ..., "show_name": ..., "vintage": ..., "media_url": ...}]`.
    - Run `import_plan.py --input-jsonpath amq_raw.json --output plan_raw.json` via `pinned_call`.
    - Run `import_plan.py --input amq_flat.json --output plan_flat.json` via `pinned_call`.
    - Assert both invocations exit 0 and `plan_raw.json` is byte-identical to `plan_flat.json`.
    - **EXPECTED OUTCOME ON UNFIXED CODE**: The `--input-jsonpath` invocation exits 2 (argparse rejects the unknown flag) — test FAILS on the `rc == 0` assertion. This confirms the bug.
    - **EXPECTED OUTCOME ON FIXED CODE**: Both invocations exit 0 with byte-equal plans.
    - Document the argparse failure in the task's done-when notes.
    - _Requirements: R2.1, R2.2_

  - [x] 1.2 Bug 2 exploration test — `graduate` at level=3 must pin to MAX_LEVEL
    - **Property 3: Bug Condition** — Graduate leaves level below MAX_LEVEL on unfixed code
    - Add a new integration test `test_graduate_pins_level_to_max_level_on_below_max_start` to `tests/integration/test_learning.py`.
    - Seed a learning row via `insert_learning(tmp_app_root, song_id=sid, level=3, graduated=0)`.
    - Run `learning.py graduate --ids <lid>` via `pinned_call`, assert rc == 0.
    - Re-read the row via a sqlite3 connection to `tmp_app_root/db/datasource.db`.
    - Assert `row["level"] == 19` (i.e. `_common.MAX_LEVEL`) AND `row["graduated"] == 1` AND `row["id"]` / `row["song_id"]` / `row["created_at"]` unchanged.
    - Assert the response payload reports `"level": 19` and `"display_level": 20` for that id.
    - **EXPECTED OUTCOME ON UNFIXED CODE**: `row["level"] == 3` after graduate — test FAILS on the level assertion. This confirms the bug.
    - **EXPECTED OUTCOME ON FIXED CODE**: All assertions pass.
    - _Requirements: R2.10, R2.11_

  - [x] 1.3 Bug 3 exploration check — `skills/README.md` preference phrase
    - **Property 5: Bug Condition** — skills docs do not carry the preference guidance on unfixed code
    - Add a new integration test file `tests/integration/test_skills_docs.py` with first test `test_skills_readme_mentions_dedicated_command_preference`.
    - Read `skills/README.md` from the repo root (resolve via `pathlib.Path(__file__).resolve().parents[2] / "skills" / "README.md"`).
    - Assert the file contains the case-insensitive phrase `"dedicated command"`.
    - Assert that the surrounding context (same H2-bounded section) mentions both `"graduate"` and `"data.py"`, validating the named counter-example.
    - **EXPECTED OUTCOME ON UNFIXED CODE**: `"dedicated command"` is absent from `skills/README.md` — test FAILS. This confirms the bug.
    - **EXPECTED OUTCOME ON FIXED CODE**: Phrase is present in the new `## Using Dedicated Commands` section and the graduate counter-example is in the same section.
    - _Requirements: R2.12, R2.13_

  - [x] 1.4 Bug 4 exploration check — `search-songs` appears ≥ 4 times in `searching-library/SKILL.md`
    - **Property 7: Bug Condition** — `searching-library` SKILL.md lacks combined-search examples on unfixed code
    - Extend `tests/integration/test_skills_docs.py` with a second test `test_searching_library_has_combined_search_examples`.
    - Read `skills/searching-library/SKILL.md` from the repo root.
    - Count occurrences of the literal `search-songs` in the file.
    - Assert count >= 4 (one Checklist bullet + one per worked example for the four flag combinations, with the preserved Pattern-section pointer making the lower bound comfortable).
    - **EXPECTED OUTCOME ON UNFIXED CODE**: count is 1 (just the Checklist bullet) — test FAILS on `>= 4`. This confirms the bug.
    - **EXPECTED OUTCOME ON FIXED CODE**: count is >= 4.
    - _Requirements: R2.16_

## Bug 1 — `import_plan.py` input-shape expansion

Live code (`scripts/import_plan.py`). Decision 1 = Option B: legacy `--input`
stays flat-only; three new mutually-exclusive flags add the new channels.
New helpers live in the same file as pure functions.

- [x] 2. Add preprocessing helpers to `scripts/import_plan.py`
  - Parent task. Each sub-task adds one pure helper with direct unit coverage; no CLI wiring yet.
  - All three helpers are covered by a new `tests/unit/test_importer_preprocessing.py` file (no DB, no subprocess, stdlib-only).

  - [x] 2.1 Add `_discriminate(parsed) -> str`
    - Pure function. Returns `"flat"` if `isinstance(parsed, list)`, `"raw_amq"` if `isinstance(parsed, dict) and isinstance(parsed.get("songs"), list)`, raises `KnownError("INVALID_INPUT", ...)` otherwise with `{"got_type": type(parsed).__name__}` in details.
    - Add unit tests in `tests/unit/test_importer_preprocessing.py` parametrised over: `[]`, `[{...}]`, `{"songs": []}`, `{"songs": [{...}]}`, `{"songs": "not a list"}`, `{"no_songs": 1}`, `"scalar"`, `42`, `None`.
    - _Bug_Condition: isBugConditionImporter(invocation) — shape discrimination is the front-door decision for the new flags_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5_

  - [x] 2.2 Add `_amq_entry_to_flat(entry, i) -> dict`
    - Pure function. Walks the field mapping table (AMQ keys first, then flat-alias fallback):
      - `artist_name`: try `songArtist`, then `artist_name`. Required.
      - `song_name`: try `songName`, then `song_name`. Required.
      - `show_name`: try `animeEnglishName`, then `animeRomajiName`, then `show_name`. Required.
      - `vintage`: try `vintage`, then `animeVintage`. Required.
      - `media_url`: try `audio`, then `media_url`, then `MP3`, then `mp3`. Optional, defaults to `""`.
    - For each required key: pick the first candidate whose value is a non-empty string. If none match, raise `KnownError("INVALID_INPUT", f"AMQ song at index {i} is missing required field {fieldname}.", {"index": i, "missing_field": fieldname, "available_keys": sorted(entry.keys())})`.
    - Silently drop every other field (e.g. `type`, `fromList`, `startSample`, `videoLength`, `urlMap` beyond the picked key).
    - Unit tests parametrised over: all AMQ keys present → flat dict; all flat-alias keys present → flat dict (identity-ish); `animeEnglishName` beats `animeRomajiName` when both present; missing `media_url` defaults to `""`; missing each of the four required fields raises with that field named; extra AMQ-native fields dropped.
    - _Bug_Condition: isBugConditionImporter(invocation) where payload is raw AMQ_
    - _Requirements: R2.1, R2.8, R2.9_

  - [x] 2.3 Add `_flatten_amq(payload) -> list[dict]`
    - Pure function. Loops `payload["songs"]`. For each entry: if `not isinstance(entry, dict)`, raise `KnownError("INVALID_INPUT", f"AMQ song at index {i} is not a JSON object.", {"index": i})`; else call `_amq_entry_to_flat(entry, i)`.
    - Unit tests parametrised over: three-song AMQ payload happy path; non-dict entry at index 1 raises citing index 1; empty `songs` list returns `[]`.
    - _Bug_Condition: isBugConditionImporter(invocation) where payload is raw AMQ_
    - _Requirements: R2.8, R2.9_

- [x] 3. Wire the new CLI flags in `scripts/import_plan.py`
  - Parent task. This is the only task that changes the CLI surface and the `_run` dispatch; the helpers from Task 2 are already in place.

  - [x] 3.1 Extend `_build_parser()` with the three new flags
    - Add a mutually-exclusive group via `parser.add_mutually_exclusive_group(required=False)`.
    - Add `--input-jsonpath PATH`, `--input-jsonstr JSON`, `--input-array JSON` to the group. Keep legacy `--input` and the `positional_input` argument on the top-level parser unchanged.
    - Help text lists the legacy surface first, then the three new flags under an "Input" section.
    - _Requirements: R2.6_

  - [x] 3.2 Add `_entries_from_parsed(parsed, *, channel) -> list[dict]`
    - Calls `_discriminate(parsed)` first.
    - If `channel == "flat-only"` and discriminator returned `"raw_amq"`, raise `KnownError("INVALID_INPUT", "--input-array is flat-only; nested AMQ objects are not accepted on this channel.")`.
    - If discriminator returned `"raw_amq"`, run `_flatten_amq(parsed)`; if `"flat"`, use `parsed` as-is.
    - Run the existing per-entry URL-decode-and-normalise loop from `_load_entries` against the resulting list so every channel produces the same five-field shape the classifier consumes.
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.8_

  - [x] 3.3 Update `_run(args)` to dispatch over the new channels
    - Determine which channel fired. Legacy: `args.input_path` or `args.positional_input` (mutually exclusive with the new flags — enforce with a manual `KnownError("INVALID_INPUT", "Mix of legacy --input and new input flags is not supported.")` if any new flag is set alongside a legacy one; argparse's group already rejects two-of-three among the new flags).
    - If none of `input_path`, `positional_input`, `input_jsonpath`, `input_jsonstr`, `input_array` is set, raise `KnownError("INVALID_INPUT", "No input: pass --input-jsonpath, --input-jsonstr, --input-array, --input, or a positional path.")`.
    - Legacy channel: call `_load_entries(path)` unchanged.
    - `--input-jsonpath`: read the file, `json.loads`, pass to `_entries_from_parsed(parsed, channel="jsonpath")`.
    - `--input-jsonstr`: `json.loads(args.input_jsonstr)`, pass to `_entries_from_parsed(parsed, channel="jsonstr")`. Wrap the `json.loads` call so a `JSONDecodeError` becomes `INVALID_INPUT`.
    - `--input-array`: `json.loads(args.input_array)`, pass to `_entries_from_parsed(parsed, channel="flat-only")`.
    - Classifier loop (`_classify`, `_resolve_show`, plan assembly, `--output` handling) stays unchanged.
    - _Bug_Condition: isBugConditionImporter(invocation) for all three new channels_
    - _Expected_Behavior: Property 1 from design — each new channel produces the same plan as legacy `--input` on the equivalent flat payload_
    - _Preservation: Property 2 from design — legacy flat-via-`--input` behavior unchanged_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9_

- [x] 4. Add the three end-to-end integration tests for the new flags
  - Extend `tests/integration/test_import_plan.py`. Style matches the existing `test_resolved_exact_match_with_existing_show`: seed DB via `insert_*` helpers, call the script through `pinned_call`, assert on the returned plan and on the read-only DB hash.
  - Task 1.1's exploration test covers `--input-jsonpath` on a raw AMQ payload; the three tasks below extend coverage to the remaining channels and payload shapes.

  - [x] 4.1 `test_input_jsonstr_raw_amq_matches_flat_via_input`
    - Inline raw AMQ JSON via `--input-jsonstr '{"songs":[...]}'`.
    - Compare plan against legacy `--input` on the equivalent flat array file.
    - Assert rc == 0, plans byte-equal, DB hash unchanged.
    - _Requirements: R2.3, R2.8_

  - [x] 4.2 `test_input_array_flat_matches_flat_via_input`
    - Inline flat JSON via `--input-array '[{"artist_name": ..., ...}]'`.
    - Compare plan against legacy `--input` on the same flat array written to a file.
    - Assert rc == 0, plans byte-equal.
    - _Requirements: R2.4_

  - [x] 4.3 `test_input_array_rejects_raw_amq_with_invalid_input`
    - Inline raw AMQ JSON via `--input-array '{"songs":[...]}'`.
    - Assert rc == 1, stderr JSON error code `INVALID_INPUT`, message mentions "flat-only".
    - _Requirements: R2.5_

- [x] 5. Write PBT for Bug 1 — four-channel equivalence on flat payloads and raw AMQ payloads
  - **Property 1: Expected Behavior** — Importer accepts the three new inputs equivalently to legacy flat
  - **Property 2: Preservation** — Importer legacy surface unchanged
  - Create new file `tests/integration/property/test_importer_input_channels_property.py`. Follow the `_helpers.py` conventions: `BASE_SEED + N`, `ITERATIONS` constant, per-file docstring naming Properties 1 and 2.
  - Seeded `random.Random` generates random flat payloads mixing resolved / auto_completable / ambiguous entries (reuse shapes from `test_import_property.py::_build_amq_input`).
  - For each generated flat payload, drive it through every accepted channel: legacy `--input` (baseline), `--input-jsonpath`, `--input-jsonstr`, `--input-array`. Assert all four plans are byte-equal.
  - For each generated flat payload, also build a raw AMQ payload by wrapping it: `{"songs": [{"songArtist": e["artist_name"], "songName": e["song_name"], "animeEnglishName": e["show_name"], "vintage": e["vintage"], "audio": e["media_url"]} for e in flat], "extra": "metadata"}`. Drive through `--input-jsonpath` (file) and `--input-jsonstr` (inline). Assert plans byte-equal to the legacy flat baseline.
  - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.8, R2.9, R3.1, R3.2, R3.4, R3.5_

- [x] 6. Update `skills/importing-amq-songs/SKILL.md` with the new flags
  - Document `--input-jsonpath`, `--input-jsonstr`, `--input-array` in the "Input shape" and "Checklist" sections.
  - Note that the raw AMQ export JSON is now accepted directly by `--input-jsonpath` — no pre-flattening needed.
  - Keep the legacy `--input` / positional surface documented as the flat-only compat path, with one line noting it is retained for compatibility with existing scripts.
  - Do not remove the `SONG_INVARIANT_VIOLATION` cleanup note pointing at `scripts/data.py delete --kind song`.
  - _Requirements: R3.11, R3.13 (preservation of existing data.py reference)_

- [x] 7. Update `skills/importing-amq-songs/references/plan-shape.md` with the AMQ field mapping
  - Add a new subsection `## Raw AMQ input mapping` documenting the field mapping table from Decision 3 (AMQ keys → flat keys, required vs. optional, `animeEnglishName > animeRomajiName > show_name` precedence, whole-file reject on missing required field).
  - Keep every existing subsection (`plan.json`, `answers.json`, `triples.json` shapes) unchanged.
  - _Requirements: R3.1 (preservation of plan-shape contract)_

## Bug 2 — `graduate` pins `level` to `MAX_LEVEL`

Live code (`scripts/learning.py::_cmd_graduate`). One-line UPDATE change
plus matching response value. Does NOT touch `last_level_up_at` or
`level_up_path`. Already-graduated branch unchanged.

- [x] 8. Update existing Bug-2-encoding tests in place (do this BEFORE the code change)
  - **IMPORTANT**: These two tests currently assert the buggy behavior. Per design, they must be updated in the same release — not preserved verbatim. Updating them before the code change means they go from "passing by encoding the bug" to "failing against unfixed code" to "passing against fixed code", which is the correct transition for tests that encode expected behavior.

  - [x] 8.1 Update `tests/integration/test_learning.py::test_graduate_flips_graduated_flag`
    - Seed already uses `level=5, graduated=0`. Keep the seed and the `graduate` invocation unchanged.
    - Change `payload["display_level"] == 6` to `payload["display_level"] == 20` (i.e. `_common.MAX_LEVEL + 1`).
    - Add assertion `payload["level"] == _common.MAX_LEVEL`.
    - Change the `row` assertions to include `assert row["level"] == _common.MAX_LEVEL`.
    - Every other assertion (`row["graduated"] == 1`, `row["updated_at"] == pinned_now`) stays.
    - _Requirements: R2.10, R2.11_

  - [x] 8.2 Update `tests/integration/property/test_graduate_property.py`
    - The test currently asserts `mid["level"] == before["level"]` and `after["level"] == before["level"]` after the first and second graduate calls. That encodes the bug for the case `before["graduated"] == 0 AND before["level"] < MAX_LEVEL`.
    - Replace the per-iteration assertions with a branch on `before["graduated"]`:
      - If `before["graduated"] == 1`: keep `mid["level"] == before["level"]` and `after["level"] == before["level"]` (no-op preservation path).
      - If `before["graduated"] == 0`: assert `mid["level"] == MAX_LEVEL` and `after["level"] == MAX_LEVEL` (the fix pins).
    - Keep every other invariant (`mid["graduated"] == 1`, `mid["id"] == before["id"]`, `mid["created_at"] == before["created_at"]`, second-call idempotency for `graduated`, `id`, `created_at`) unchanged.
    - _Requirements: R2.10, R2.11, R3.6, R3.7, R3.9_

- [x] 9. Fix `_cmd_graduate` in `scripts/learning.py`
  - Extend the per-id UPDATE in the non-graduated branch to also set `level`:
    - Change `UPDATE learning SET graduated = 1, updated_at = ? WHERE id = ?` to `UPDATE learning SET graduated = 1, level = ?, updated_at = ? WHERE id = ?`.
    - Bind `_common.MAX_LEVEL` as the new first parameter.
  - Update the corresponding response entry:
    - `"level"` becomes `_common.MAX_LEVEL`.
    - `"display_level"` becomes `_common.MAX_LEVEL + 1`.
  - Do NOT touch the already-graduated branch (no-op path) — it keeps returning the row's existing `level`.
  - Do NOT touch `last_level_up_at` or `level_up_path` anywhere.
  - Do NOT touch `_cmd_levelup`, `_cmd_batch`, `_cmd_due`, `_cmd_stats`, or `main`.
  - _Bug_Condition: isBugConditionGraduate(L) where L.graduated = 0 AND L.level < MAX_LEVEL_
  - _Expected_Behavior: Property 3 from design — after graduate, graduated = 1 AND level = MAX_LEVEL, id/song_id/created_at/level_up_path/last_level_up_at unchanged, response reports level = MAX_LEVEL and display_level = MAX_LEVEL + 1_
  - _Preservation: Property 4 from design — no-op path and already-at-MAX_LEVEL path unchanged_
  - _Requirements: R2.10, R2.11_

- [x] 10. Verify Bug 1 and Bug 2 exploration tests (Tasks 1.1 and 1.2) now pass
  - **Property 1: Expected Behavior** — raw AMQ via `--input-jsonpath` produces same plan as flat via `--input`
  - **Property 3: Expected Behavior** — graduate pins level to MAX_LEVEL
  - **IMPORTANT**: Re-run the SAME tests from Tasks 1.1 and 1.2 — do NOT write new tests. The tests from Task 1 encode the expected behavior.
  - Run `pytest tests/integration/test_import_plan.py::test_raw_amq_via_input_jsonpath_matches_flat_via_input tests/integration/test_learning.py::test_graduate_pins_level_to_max_level_on_below_max_start`.
  - **EXPECTED OUTCOME**: Both tests PASS (confirms the bug conditions are resolved).
  - _Requirements: R2.1, R2.2, R2.10, R2.11_

- [x] 11. Add new integration test for Bug 2 — parametrised `level` starts
  - Add `test_graduate_pins_level_to_max_for_all_below_max_starts` to `tests/integration/test_learning.py`, parametrised across `level ∈ {0, 3, 10, 18}`.
  - For each parametrised level, seed a learning row with that level and `graduated=0`, run `graduate`, assert post-state `level == 19, graduated == 1` on both the response payload and the re-read row.
  - Also assert `id`, `song_id`, `created_at`, `level_up_path`, and `last_level_up_at` are unchanged per R3.9.
  - _Requirements: R2.10, R2.11, R3.9_

- [x] 12. Write PBT for Bug 2 — `level == MAX_LEVEL` invariant on random learning rows
  - **Property 3: Expected Behavior** — For all L with isBugConditionGraduate(L), after graduate: level = MAX_LEVEL, graduated = 1
  - **Property 4: Preservation** — For all L where NOT isBugConditionGraduate(L), graduate produces same row state and response as original
  - Create new file `tests/integration/property/test_graduate_level_max_property.py`. Follow the `_helpers.py` conventions (`BASE_SEED + N` unique offset, `ITERATIONS`, docstring naming Properties 3 and 4).
  - Seeded `random.Random` generates learning rows with `level ∈ [0, MAX_LEVEL]` and `graduated ∈ {0, 1}`. For each row:
    - Read pre-state via sqlite3.
    - Run `graduate` via `pinned_call`.
    - Read post-state.
    - If `before.graduated == 0 AND before.level < MAX_LEVEL` (bug condition): assert `after.level == MAX_LEVEL`, `after.graduated == 1`, `after.updated_at == pinned_now`, response payload matches.
    - If `before.graduated == 0 AND before.level == MAX_LEVEL` (preservation corner): assert `after.level == MAX_LEVEL`, `after.graduated == 1`, `after.updated_at == pinned_now`.
    - If `before.graduated == 1` (no-op path): assert `after.level == before.level`, `after.graduated == 1`, `after.updated_at == before.updated_at` (no re-stamp).
    - In all cases: `after.id == before.id`, `after.song_id == before.song_id`, `after.created_at == before.created_at`, `after.level_up_path == before.level_up_path`, `after.last_level_up_at == before.last_level_up_at`.
  - _Requirements: R2.10, R2.11, R3.6, R3.7, R3.8, R3.9_

## Bug 3 — `skills/README.md` preference paragraph

Docs-only. New `## Using Dedicated Commands` section between the intro
paragraph and `## Common Workflows`. ≤ 12 lines Markdown. One preference
sentence, one worked counter-example naming the graduate invariant, one
pointer at the skills table.

- [x] 13. Add `## Using Dedicated Commands` section to `skills/README.md`
  - Insert the new H2 section immediately after the opening paragraph and before `## Common Workflows`.
  - Content (≤ 12 lines of Markdown):
    - One preference sentence: use the dedicated command for the task if one exists; `data.py` CRUD (`create`, `update`, `delete`, `bulk-reassign`) is a last-resort fallback for work no dedicated command covers.
    - One worked counter-example: graduating a song via `data.py update --kind learning --id <id> --data '{"graduated": 1}'` succeeds as SQL but leaves `level` below `MAX_LEVEL`, violating the `graduated ↔ level = MAX_LEVEL` invariant; `learning.py graduate --ids <id>` preserves it.
    - One pointer: "The dedicated commands for each skill are listed in the Skills table below. If the task you need matches one of those skills, start there."
  - Do NOT modify any existing paragraph, workflow bullet, or table entry.
  - Do NOT touch any `SKILL.md` under `skills/` for Bug 3 (bodies stay standalone per R3.12).
  - _Bug_Condition: isBugConditionSkillsGuidance(D) — D lacks the globally-reachable statement AND the named worked example_
  - _Expected_Behavior: Property 5 from design — case-insensitive search for "dedicated command" finds a match in skills/README.md, and the context names the graduate invariant_
  - _Preservation: Property 6 from design — every pre-fix command listing retained_
  - _Requirements: R2.12, R2.13, R2.14, R2.15, R3.10, R3.11, R3.12, R3.13_

- [ ] 14. Extend `tests/integration/test_skills_docs.py` with command-inventory preservation test
  - Add a test `test_every_command_at_spec_start_still_documented` to the file introduced in Task 1.3.
  - Walk every `skills/**/SKILL.md` file and `skills/README.md`, collect every `(script, subcommand)` pair referenced in fenced code blocks and inline code spans where the pattern is `scripts/<name>.py <subcommand>` or `<name>.py <subcommand>`.
  - Pin the pre-fix reference set in the test fixture (hard-coded list derived from reading the files at spec start) so a silent removal of any pair fails the test.
  - Assert `data.py` has all four subcommands (`create`, `update`, `delete`, `bulk-reassign`) referenced somewhere in the skill set.
  - _Requirements: R3.10, R3.11, R3.13_

## Bug 4 — `skills/searching-library/SKILL.md` combined-search examples

Docs-only. New H2 `## Combined searches: song + show + artist` between the
existing "Pattern" section and "Checklist". ≤ 25 lines. Four worked
examples (song+show, song+artist, artist+show, all-three) each with a
natural-language intent phrase and exact `scripts/query.py search-songs ...`
invocation. One anti-pattern callout (chained single-kind search → manual
id intersection).

- [x] 15. Add `## Combined searches: song + show + artist` section to `skills/searching-library/SKILL.md`
  - Insert the new H2 immediately after `## Pattern: when the user gives a name, not an ID` and before `## Checklist: available ops`.
  - Content (≤ 25 lines of Markdown):
    - 1–2 sentences naming when to reach for `search-songs` vs. chaining single-kind `search` calls.
    - One compact list mapping each of the four flag combinations to a natural-language user-intent phrase and the exact CLI invocation:
      - **song + show** (e.g. "the opening of Clannad"): `scripts/query.py search-songs --song-term "<song>" --show-term "<show>"`
      - **song + artist** (e.g. "the Lia song called Megumeru"): `scripts/query.py search-songs --song-term "<song>" --artist-term "<artist>"`
      - **artist + show** (e.g. "songs from FMA by Yui"): `scripts/query.py search-songs --artist-term "<artist>" --show-term "<show>"`
      - **all three** (e.g. "the Clannad OP by Lia called Megumeru"): `scripts/query.py search-songs --song-term "<song>" --show-term "<show>" --artist-term "<artist>"`
    - One anti-pattern callout naming the chained-search fallback (three `search` calls + manual id intersect) and why it's worse: three DB roundtrips, no artist/show/`media_urls` attachment, no byte-stable ordering.
    - One pointer: "See the Checklist entry below for the exact flag syntax and the `{filters, count, results}` envelope shape."
  - Do NOT modify the existing `## Pattern: when the user gives a name, not an ID` section content (its existing `search-songs` mention stays as-is or is pruned to a one-sentence pointer at the new section, but it MUST NOT disappear per R3.15).
  - Do NOT modify any Checklist bullet or Notes bullet — every existing op keeps the same command string, flags, and paragraph position per R3.14.
  - _Bug_Condition: isBugConditionCombinedSearchExamples(D) — file lacks a worked example for any of the four flag pairings_
  - _Expected_Behavior: Property 7 from design — all four worked examples present, each paired with a natural-language intent phrase_
  - _Preservation: Property 8 from design — every pre-fix (script, subcommand, flag) triple retained_
  - _Requirements: R2.16, R2.17, R2.18, R2.19, R3.14, R3.15_

- [ ] 16. Extend `tests/integration/test_skills_docs.py` with combined-search fix-check and preservation assertions
  - Add `test_searching_library_has_worked_example_for_each_flag_combination`.
    - For each of the four flag sets `{--song-term, --show-term}`, `{--song-term, --artist-term}`, `{--show-term, --artist-term}`, `{--song-term, --show-term, --artist-term}`: parse `skills/searching-library/SKILL.md`, find each `scripts/query.py search-songs ...` invocation line, extract the `--*-term` flags present on that line, and assert at least one invocation line uses exactly that flag set (not a superset, not a subset).
    - For each matched invocation, assert the enclosing H2-bounded section contains at least one natural-language intent anchor (case-insensitive match against a seed list pinned in the test docstring: `"opening"`, `"songs from"`, `"by "`, `"which shows"`, `"the clannad"`, `"called"`).
    - Assert the anti-pattern callout exists — presence check for the phrase `"three"` AND `"search"` AND (`"intersect"` OR `"roundtrip"`) within the new H2 section.
  - Add `test_searching_library_retains_every_pre_fix_command_reference`.
    - Pin the pre-fix `(script, subcommand)` set from `skills/searching-library/SKILL.md` as a hard-coded fixture list: `search`, `get`, `batch-get`, `duplicates`, `shows-by-artist-ids`, `songs-by-artist-ids`, `list-learning`, `song-detail`, `artist-detail`, `show-detail`, `learning-detail`, `search-songs`.
    - Assert every entry in the pinned set appears at least once as `scripts/query.py <subcommand>` in the fixed file.
  - Keep the exploratory count check from Task 1.4 (`search-songs` count >= 4) — rename it in the same file if helpful, but do not drop it; it's the regression guard for the new section.
  - _Requirements: R2.16, R2.17, R2.18, R3.14, R3.15_

## Verification

- [x] 17. Checkpoint — run the full gate and confirm coverage ≥ 90%
  - Run `make check` (lint + typecheck + test). Expect all three to pass.
  - Confirm coverage stays ≥ 90% — `./tests/run.sh` enforces this automatically; fail the task if coverage drops. The new preprocessing helpers are exercised 100% by `tests/unit/test_importer_preprocessing.py`, so the floor should be unaffected.
  - Re-run all four exploration tests from Task 1. All four MUST now pass:
    - Task 1.1 — raw AMQ via `--input-jsonpath` produces plan equal to flat via `--input`.
    - Task 1.2 — `graduate` at `level=3` ends at `level=19`.
    - Task 1.3 — `skills/README.md` contains `"dedicated command"` with graduate counter-example nearby.
    - Task 1.4 — `search-songs` appears ≥ 4 times in `skills/searching-library/SKILL.md`.
  - Re-run all preservation PBTs and integration tests. Confirm no regressions in:
    - `tests/integration/test_import_plan.py` (all existing tests byte-identical behavior).
    - `tests/integration/test_error_codes.py::test_song_invariant_violation` (unchanged).
    - `tests/integration/test_learning.py::test_graduate_second_call_is_noop`, `::test_graduate_missing_id_is_not_found`, `tests/integration/test_error_codes.py::test_already_graduated` (unchanged).
  - If any test fails or coverage drops, diagnose root cause before proceeding; ask if questions arise.
  - _Requirements: All R2.* and R3.* from bugfix.md_

## Commit

- [ ] 18. Commit per bug group, in order: Bug 1 commit, Bug 2 commit, Bug 3+4 commit (docs together)
  - **DO NOT actually commit from this task file** — this entry is instructional for when the implementation phase lands each group.
  - Follow Amazon Conventional-Commits (`feat:`, `fix:`, `docs:`) per the `amazon-builder/amazon-builder-git.md` user rule.
  - Suggested commit order and messages:
    1. **Bug 1 commit** — `feat(import_plan): accept raw AMQ export and inline JSON via three new input flags`. Scope: Tasks 2, 3, 4, 5, 6, 7. Files: `scripts/import_plan.py`, `tests/unit/test_importer_preprocessing.py`, `tests/integration/test_import_plan.py`, `tests/integration/property/test_importer_input_channels_property.py`, `skills/importing-amq-songs/SKILL.md`, `skills/importing-amq-songs/references/plan-shape.md`. Includes the Task 1.1 exploration test.
    2. **Bug 2 commit** — `fix(learning): pin level to MAX_LEVEL when graduate flips graduated flag`. Scope: Tasks 8, 9, 10 (verification for Bug 2 half only), 11, 12. Files: `scripts/learning.py`, `tests/integration/test_learning.py`, `tests/integration/property/test_graduate_property.py`, `tests/integration/property/test_graduate_level_max_property.py`. Includes the Task 1.2 exploration test.
    3. **Bug 3 + Bug 4 commit** — `docs(skills): add dedicated-command preference and combined-search examples`. Scope: Tasks 13, 14, 15, 16. Files: `skills/README.md`, `skills/searching-library/SKILL.md`, `tests/integration/test_skills_docs.py`. Includes the Task 1.3 and 1.4 exploration tests (which land together with the new test file in the Bug 3 commit; the Bug 4 assertions extend the same file).
  - Keep each commit self-contained: tests and code land together; exploration tests land in the same commit as the fix they validate so the commit history never contains a persistently-failing test.
  - Do NOT `git push`.
  - _Requirements: n/a (instructional task, no validation)_
