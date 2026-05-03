# Implementation Plan

This task list translates `design.md` into an executable plan for the
single defect in the AMQ importer's field-mapping table. The order
below follows the bugfix workflow's Task-1-first-fails pattern: one
exploration test up front that MUST fail on unfixed code (the failure
is the evidence), then the live-code fix (the `_get_nested` helper and
the rewritten `_AMQ_FIELD_MAP` with matching candidate loop, plus the
new unit tests for the new helper), then three batches of existing
tests rewritten in place to the real nested wrapper shape, then the
exploration-test re-run that confirms the fix, then the doc touch,
then the final gate, then the single commit.

Every AMQ-shaped test in the repo currently encodes the v0.1.1 guessed
flat-per-song wrapper. Those tests are self-consistent but fictional
on v0.1.1 — rewriting them to the real nested shape is part of the
fix, not preservation (analogous to Tasks 8.1 / 8.2 in the parent
`importer-and-graduate-fixes` spec, which updated the Bug-2-encoding
tests in the same pass as the fix). The structural contracts each
rewritten test asserts (required-field-missing raises `INVALID_INPUT`,
extras silently dropped, stable key order, byte-equal plans across the
four input channels on equivalent flat payloads) stay unchanged.

Ships as v0.1.2 via the existing release pipeline. No new CLI flags,
no new error codes, no schema change.

## Bug condition exploration test (fails on unfixed code)

- [x] 1. Write bug condition exploration test — real AMQ fixture ingest
  - **Property 1: Bug Condition** — Importer rejects the real AMQ export shape on unfixed code
  - **CRITICAL**: This test MUST FAIL on unfixed code — the failure is the evidence that the bug exists.
  - **DO NOT attempt to fix the test or the code when it fails.**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation.
  - **GOAL**: Surface the concrete counterexample (exit 1 `INVALID_INPUT missing_field=artist_name details.index=0`) that demonstrates the bug.
  - Commit the real AMQ export fixture at `tests/fixtures/amq_song_export-small.json` (the 9-song file linked from `README.md` via `docs/design/v1/amq_song_export-small.json` in the parent repository). Keep it read-only across every test that consumes it (R3.11) — tests that need the fixture inside `tmp_app_root` copy it in via `shutil.copyfile`, not a move or edit.
  - Add a new integration test `test_real_amq_export_file_ingests_end_to_end` to `tests/integration/test_import_plan.py` (style matches `test_resolved_exact_match_with_existing_show`).
  - Resolve the fixture path absolutely from `__file__` via `pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "amq_song_export-small.json"` and `shutil.copyfile` it to `tmp_app_root / "amq_real.json"` so `--input-jsonpath` can read it with a stable path.
  - Use the `tmp_app_root` fixture with zero rows seeded — every AMQ song in the fixture lands in `auto_completable` against an empty DB.
  - Run `import_plan.py --input-jsonpath amq_real.json --output plan.json` via `pinned_call`.
  - Assert:
    - `rc == 0` and `err` is empty (no error envelope on stderr).
    - The parsed `plan.json` satisfies `len(plan["resolved"]) + len(plan["auto_completable"]) + len(plan["ambiguous"]) == 9`.
    - At least one plan entry has `artist_to_create.name == "Tia"`, `song_name == "Chotto Dekakete Kimasu"`, and a `show_to_create.name` matching the real English show name from the fixture (the pinned-song check from design Decision 4).
  - **EXPECTED OUTCOME ON UNFIXED CODE**: The run exits 1 with a JSON error envelope on stderr whose `error.code == "INVALID_INPUT"`, `error.details.missing_field == "artist_name"`, `error.details.index == 0` — the `rc == 0` assertion fails. This confirms the bug: the v0.1.1 `_AMQ_FIELD_MAP` does a 1-level `entry[key]` lookup and the real AMQ nests `artist` under `songInfo`, so the artist lookup aborts on song 0.
  - **EXPECTED OUTCOME ON FIXED CODE**: All assertions pass (rc == 0, three buckets sum to 9, pinned song resolves).
  - Document the exact counterexample (`INVALID_INPUT missing_field=artist_name details.index=0`) in the task's done-when notes.
  - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.9, R2.10, R3.11_

## Fix

Live code (`scripts/import_plan.py`) plus direct unit coverage for the
new `_get_nested` helper. Classifier, four input channels, and error
envelope shape stay byte-identical.

- [x] 2. Rewrite `_AMQ_FIELD_MAP` to path-tuple candidates, add `_get_nested` helper, update the candidate loop in `_amq_entry_to_flat`
  - Parent task. All changes land in `scripts/import_plan.py` in one pass so the helper, the table, and the loop stay consistent at every commit-boundary. Also ships the direct unit tests for the new helper, since `_get_nested` is brand new code that must not land without coverage.

  - [x] 2.1 Add `_get_nested(obj, path)` helper
    - Pure function. Walks `obj` along `path` one key at a time. Returns `None` on any missing container or non-dict container mid-walk. Returns the final value regardless of type — the caller decides what counts as "present".
    - Place it in `scripts/import_plan.py` inside the "Raw-AMQ preprocessing helpers" block, directly above `_AMQ_FIELD_MAP` (design Decision 2).
    - Signature and body per design change #1:
      ```python
      def _get_nested(obj: object, path: tuple[str, ...]) -> object:
          cur: object = obj
          for key in path:
              if not isinstance(cur, dict):
                  return None
              cur = cur.get(key)
              if cur is None:
                  return None
          return cur
      ```
    - Add 3–5 direct unit tests in `tests/unit/test_importer_preprocessing.py` under a new `# _get_nested` section header that mirrors the existing `# _discriminate` / `# _amq_entry_to_flat` / `# _flatten_amq` block style:
      - Path of length 0 returns the input object unchanged.
      - Path of length 1 hitting a leaf returns the leaf value.
      - Path of length 3 hitting a leaf through nested dicts returns the leaf value.
      - Missing container mid-walk (e.g. `_get_nested({"a": {}}, ("a", "b", "c"))`) returns `None`.
      - Non-dict container mid-walk (e.g. `_get_nested({"a": "scalar"}, ("a", "b"))`) returns `None`.
    - _Bug_Condition: isBugCondition(input) where input.payload is the real AMQ shape — the helper is the front-door primitive that unlocks the fix_
    - _Expected_Behavior: Property 1 (Expected Behavior) from design — path-tuple lookups reach values nested under `songInfo` / `songInfo.animeNames`_
    - _Preservation: None — `_get_nested` is new code with no pre-existing caller_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6_

  - [x] 2.2 Rewrite `_AMQ_FIELD_MAP` to path-tuple candidates
    - Change the table's row signature from `(flat_key, tuple[str, ...], required)` to `(flat_key, tuple[tuple[str, ...], ...], required)`. Each candidate becomes a **path** — a tuple of keys to walk with `_get_nested`.
    - Final table per design change #2 (real nested paths first, flat aliases retained as single-key paths so already-flat callers keep working per R2.11 and the existing four-channel byte-equality PBT):
      ```python
      _AMQ_FIELD_MAP: tuple[tuple[str, tuple[tuple[str, ...], ...], bool], ...] = (
          ("artist_name", (("songInfo", "artist"), ("artist_name",)), True),
          ("song_name",   (("songInfo", "songName"), ("song_name",)), True),
          ("show_name",   (("songInfo", "animeNames", "english"),
                           ("songInfo", "animeNames", "romaji"),
                           ("show_name",)), True),
          ("vintage",     (("songInfo", "vintage"), ("animeVintage",), ("vintage",)), True),
          ("media_url",   (("videoUrl",), ("audio",), ("media_url",),
                           ("MP3",), ("mp3",)), False),
      )
      ```
    - Preserve the English-over-Romaji precedence: `songInfo.animeNames.english` is listed before `songInfo.animeNames.romaji` in the `show_name` candidate tuple.
    - Preserve the required/optional column: `artist_name`, `song_name`, `show_name`, `vintage` remain required; `media_url` remains optional with default `""`.
    - _Bug_Condition: isBugCondition(input) where input.payload is the real AMQ shape_
    - _Expected_Behavior: Property 1 from design — each flat key resolves from the correct nested path_
    - _Preservation: Property 2 from design — flat-alias single-key paths keep already-flat callers working unchanged_
    - _Requirements: R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.11_

  - [x] 2.3 Rewrite the candidate loop in `_amq_entry_to_flat` to dispatch through `_get_nested`
    - Inside `_amq_entry_to_flat(entry, i)`, change the inner `for raw_key in candidates` loop to iterate **paths** instead of top-level keys and call `_get_nested(entry, path)` per path per design change #3:
      ```python
      for flat_key, candidate_paths, required in _AMQ_FIELD_MAP:
          picked: str | None = None
          for path in candidate_paths:
              val = _get_nested(entry, path)
              if isinstance(val, str) and val != "":
                  picked = val
                  break
          if picked is None:
              if required:
                  raise _common.KnownError(
                      "INVALID_INPUT",
                      f"AMQ song at index {i} is missing required field {flat_key}.",
                      {
                          "index": i,
                          "missing_field": flat_key,
                          "available_keys": sorted(entry.keys()),
                      },
                  )
              picked = ""
          flat[flat_key] = picked
      ```
    - Every contract on `_amq_entry_to_flat` outside the candidate loop is unchanged: same `INVALID_INPUT` envelope shape and detail keys on a missing required field, same drop-on-the-floor behavior for extras, same declared key order on the returned dict, same default for optional `media_url`. A missing nested container mid-walk surfaces the same `INVALID_INPUT` as a missing leaf (R2.9) because `_get_nested` returns `None` in both cases.
    - `_flatten_amq` is NOT modified — it still iterates `payload["songs"]` and calls `_amq_entry_to_flat` per entry (design change #4).
    - No other code in `scripts/import_plan.py` is touched — `_discriminate`, `_entries_from_parsed`, the classifier, the four input channels, and `_run` stay byte-identical (design change #5).
    - _Bug_Condition: isBugCondition(input) where input.payload is the real AMQ shape_
    - _Expected_Behavior: Property 1 from design — the fixed preprocessor drives the classifier to a plan with exit 0, no `INVALID_INPUT`, every required flat field populated from the right nested path_
    - _Preservation: Property 2 from design — every non-bug-condition invocation is byte-identical to v0.1.1_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9_

## Rewrite existing AMQ-shaped tests to the real nested wrapper shape

Every AMQ-shaped test in the repo currently encodes the v0.1.1 guessed
flat-per-song wrapper. Those tests are self-consistent but fictional
on v0.1.1 — updating them to the real nested wrapper is part of the
fix, not preservation (analogous to Tasks 8.1 / 8.2 in the parent
`importer-and-graduate-fixes` spec, which rewrote the Bug-2-encoding
tests in the same pass as the fix). The structural assertions each
test makes (required-field-missing raises `INVALID_INPUT`, extras
silently dropped, stable key order, byte-equal plans across the four
input channels, etc.) are preserved verbatim; only the wrapper shape
the test builds changes.

- [-] 3. Rewrite every pre-existing AMQ-shaped test to the real nested wrapper shape
  - Parent task. Three batches below cover the unit-test file, the named integration tests, and the property-based four-channel equivalence helper. All three batches land in the same pass as the Task 2 fix so the repo is never in a state where the table and the tests disagree.

  - [x] 3.1 Rewrite `tests/unit/test_importer_preprocessing.py` — 14 `_amq_entry_to_flat` tests + 4 `_flatten_amq` tests
    - Replace every per-song literal of the form `{"songArtist": ..., "songName": ..., "animeEnglishName": ..., "animeRomajiName": ..., "vintage": ..., "audio": ...}` with the real nested shape `{"songInfo": {"artist": ..., "songName": ..., "animeNames": {"english": ..., "romaji": ...}, "vintage": ...}, "videoUrl": ...}`.
    - Covers the 14 `_amq_entry_to_flat` tests: `test_amq_entry_to_flat_all_amq_keys_present`, `test_amq_entry_to_flat_all_flat_alias_keys_present`, `test_amq_entry_to_flat_english_name_beats_romaji_when_both_present`, `test_amq_entry_to_flat_romaji_used_when_english_absent`, `test_amq_entry_to_flat_missing_media_url_defaults_to_empty`, `test_amq_entry_to_flat_empty_string_media_candidates_default_to_empty`, `test_amq_entry_to_flat_missing_artist_raises_invalid_input`, `test_amq_entry_to_flat_empty_string_artist_counts_as_missing`, `test_amq_entry_to_flat_missing_song_name_raises`, `test_amq_entry_to_flat_missing_show_name_raises`, `test_amq_entry_to_flat_missing_vintage_raises`, `test_amq_entry_to_flat_drops_extra_amq_native_fields`, `test_amq_entry_to_flat_key_order_is_stable`, plus the existing `test_amq_entry_to_flat_all_flat_alias_keys_present` which continues to exercise the flat-alias single-key paths retained by design Decision 1.
    - Covers the 4 `_flatten_amq` tests: `test_flatten_amq_three_song_happy_path`, `test_flatten_amq_non_dict_entry_raises_with_index`, `test_flatten_amq_empty_songs_returns_empty_list`, `test_flatten_amq_ignores_top_level_siblings`.
    - Update the `available_keys` assertion on `test_amq_entry_to_flat_missing_artist_raises_invalid_input` to reflect the real top-level keys of a real nested entry (e.g. `["songInfo", "videoUrl"]` when `songInfo.artist` is missing) rather than the v0.1.1 flat keys.
    - Preserve every structural assertion exactly: required-field-missing raises `INVALID_INPUT` with the same error code, `index`, and `missing_field` detail keys; extras are silently dropped; the returned dict always has the five flat keys in declared order; empty-string leaves count as missing; English wins over Romaji; optional `media_url` defaults to `""`.
    - The 9 `_discriminate` tests at the top of the file stay byte-identical — the discriminator only inspects top-level list-vs-dict-with-`songs`-list and doesn't care about per-song shape (design Testing Strategy).
    - **Rationale for editing these tests in place**: they were self-consistent but fictional on v0.1.1 — updating them is part of the fix, not preservation.
    - _Bug_Condition: isBugCondition(input) where input.payload is the real AMQ shape_
    - _Expected_Behavior: Property 1 from design — `_amq_entry_to_flat` resolves from the real nested paths_
    - _Preservation: Property 2 from design — structural contracts (missing-field envelope, extras dropped, key order) hold on the real shape_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.11, R3.10_

  - [x] 3.2 Rewrite three named AMQ-shaped tests in `tests/integration/test_import_plan.py`
    - `test_raw_amq_via_input_jsonpath_matches_flat_via_input` (design change #8): change `amq_raw_payload` from the v0.1.1 per-song keys to the real nested shape:
      ```python
      amq_raw_payload = {
          "songs": [
              {
                  "songInfo": {
                      "artist": "Artist A",
                      "songName": "Song A",
                      "animeNames": {"english": "Show A", "romaji": "Shou A"},
                      "vintage": "Fall 2024",
                  },
                  "videoUrl": "http://x/a",
              }
          ],
          "quizSettings": {"gameMode": "Solo", "songCount": 1},
      }
      ```
      Test purpose (raw AMQ via `--input-jsonpath` byte-matches equivalent flat via legacy `--input`) and every assertion stay unchanged. Keep the preamble comment's "Task 1.1 bug-condition exploration test" framing as historical context from the parent spec; the new Task 1 in this spec is the real-fixture end-to-end test.
    - `test_input_jsonstr_raw_amq_matches_flat_via_input` (design change #9): rewrite `amq_raw_jsonstr` the same way. Test purpose unchanged.
    - `test_input_array_rejects_raw_amq_with_invalid_input` (design change #10): rewrite `amq_raw_jsonstr` to the real nested shape. Assertions unchanged — the `--input-array` flat-only rejection contract holds for the real nested AMQ shape too per R3.3.
    - Every other test in `tests/integration/test_import_plan.py` (legacy `--input` flow, `--input-array` flat flow, error paths, read-only DB, mixed buckets) stays byte-identical — those tests don't touch the AMQ wrapper shape. This is the main structural evidence for R3.1, R3.2, R3.4, R3.5, R3.9.
    - **Rationale for editing these tests in place**: they were self-consistent but fictional on v0.1.1 — updating them is part of the fix, not preservation.
    - _Bug_Condition: isBugCondition(input) where input.payload is the real AMQ shape, through `--input-jsonpath` and `--input-jsonstr`_
    - _Expected_Behavior: Property 1 from design — byte-equal plans across channels on the real shape_
    - _Preservation: Property 2 from design — `--input-array` flat-only rejection contract preserved against the real shape_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.10, R2.11, R3.2, R3.3_

  - [x] 3.3 Rewrite `_wrap_as_raw_amq` in `tests/integration/property/test_importer_input_channels_property.py`
    - Design change #14. Replace the per-song dict from the v0.1.1 guessed keys to the real nested shape:
      ```python
      return {
          "songs": [
              {
                  "songInfo": {
                      "artist": e["artist_name"],
                      "songName": e["song_name"],
                      "animeNames": {"english": e["show_name"]},
                      "vintage": e["vintage"],
                  },
                  "videoUrl": e["media_url"],
              }
              for e in flat
          ],
          "extra": "metadata",
      }
      ```
    - The test function `test_all_input_channels_produce_byte_equal_plans` is unchanged — it still drives every generated flat payload through all six channels (legacy `--input`, `--input-jsonpath` on flat, `--input-jsonstr` on flat, `--input-array` on flat, `--input-jsonpath` on raw AMQ, `--input-jsonstr` on raw AMQ) and asserts byte-equality against the legacy baseline. The property is the same; the wrapper shape it exercises changes.
    - Update the per-file docstring to note the wrapper now exercises the real nested shape (the rest of the docstring — property names, iteration semantics, seed offset — stays).
    - This is the preservation vehicle for Property 2 (see design "Preservation Checking"). On unfixed code with only this helper updated (no table fix), the PBT fails with `INVALID_INPUT missing_field=artist_name` — that's the intended shape of the regression gate; running it that way is not part of the task order but is documented in the design for future reference.
    - **Rationale for editing this helper in place**: the helper was self-consistent but fictional on v0.1.1 — updating it is part of the fix, not preservation.
    - _Bug_Condition: isBugCondition(input) where input.payload is the real AMQ shape, through `--input-jsonpath` and `--input-jsonstr`_
    - _Expected_Behavior: Property 1 from design — raw-AMQ-equivalent-to-flat byte-equality on the real shape across randomised payloads_
    - _Preservation: Property 2 from design — flat-array byte-equality across channels unchanged_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.11, R3.1, R3.2, R3.10_

## Verification

- [x] 4. Verify the Task 1 exploration test now passes
  - **Property 1: Expected Behavior** — Real AMQ export ingests end-to-end through `--input-jsonpath`
  - **IMPORTANT**: Re-run the SAME test from Task 1 — do NOT write a new test. The Task 1 test encodes the expected behavior.
  - Run `pytest tests/integration/test_import_plan.py::test_real_amq_export_file_ingests_end_to_end` in isolation.
  - **EXPECTED OUTCOME**: Test PASSES — rc == 0, no stderr envelope, `len(plan["resolved"]) + len(plan["auto_completable"]) + len(plan["ambiguous"]) == 9`, pinned song (Tia / "Chotto Dekakete Kimasu") present in the plan. This confirms the bug is fixed.
  - If the test still fails, do not proceed to Task 5 — diagnose the root cause and revisit Tasks 2 / 3 before continuing.
  - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.9, R2.10_

## Documentation

- [x] 5. Rewrite the AMQ field mapping section in `skills/importing-amq-songs/references/plan-shape.md`
  - Design change #15. This is a manual content rewrite — skill docs do not get assertion tests per the parent `importer-and-graduate-fixes` spec's decision (no test coverage for `skills/**/*.md` bodies beyond the pinned-reference test file the parent spec created).
  - Rewrite the "Raw AMQ input mapping" section: the JSON example snippet and the field-mapping table. The example becomes a real nested AMQ song; the table shows the real nested paths tried per flat key, in order:
    | Raw AMQ path(s) tried, in order | Flat key | Required? |
    |---|---|---|
    | `songInfo.artist`, `artist_name` | `artist_name` | yes |
    | `songInfo.songName`, `song_name` | `song_name` | yes |
    | `songInfo.animeNames.english`, `songInfo.animeNames.romaji`, `show_name` | `show_name` | yes (English beats Romaji) |
    | `songInfo.vintage`, `animeVintage`, `vintage` | `vintage` | yes |
    | `videoUrl`, `audio`, `media_url`, `MP3`, `mp3` | `media_url` | no — defaults to `""` |
  - Preserve the "English wins over Romaji" note and the required/optional column as written.
  - Preserve the drop-on-the-floor note for per-song fields outside the mapping and for top-level siblings of `songs`; extend the wording to cover the real nested per-song game-state fields (`songNumber`, `correctGuess`, `videoLength`, `type`, `typeNumber`, `annId`, `fromList`, `startSample`, `composerInfo`, `arrangerInfo`, `altAnimeNames`, `altAnimeNamesRomaji`) per R2.8.
  - Do NOT touch any other subsection (`plan.json`, `answers.json`, `triples.json`).
  - Do NOT touch any other skill file under `skills/` — Bug 3 and Bug 4 docs from the parent spec are not re-addressed here (R3.8).
  - **Skill docs do not get assertion tests** — the parent spec's decision stands.
  - _Bug_Condition: isBugCondition(input) where input.payload is the real AMQ shape — the doc currently encodes the v0.1.1 guessed mapping and would contradict the fixed code_
  - _Expected_Behavior: Property 1 from design — doc matches the fixed code's real nested mapping_
  - _Preservation: R3.8 — no other `skills/**` file is touched_
  - _Requirements: R2.8, R3.8_

## Final gate

- [x] 6. Checkpoint — run `make check` and confirm coverage ≥ 90%
  - Run `make check` (lint + typecheck + test). Expect all three to pass.
  - Confirm coverage stays ≥ 90% — `./tests/run.sh` enforces this automatically; fail the task if coverage drops. The new `_get_nested` helper is exercised 100% by the 5 direct unit tests added in Task 2.1 plus every path-tuple lookup in the rewritten `_amq_entry_to_flat` tests, so the floor should be unaffected.
  - Re-run the Task 1 exploration test and confirm it still passes:
    - `pytest tests/integration/test_import_plan.py::test_real_amq_export_file_ingests_end_to_end` — real AMQ fixture ingests end-to-end, three buckets sum to 9.
  - Re-run every rewritten test batch and confirm no regressions:
    - `pytest tests/unit/test_importer_preprocessing.py` — all 14 `_amq_entry_to_flat` tests, all 4 `_flatten_amq` tests, all 9 `_discriminate` tests, and the 5 new `_get_nested` tests pass.
    - `pytest tests/integration/test_import_plan.py` — the three rewritten AMQ-shaped tests pass, every legacy and flat-path test stays green.
    - `pytest tests/integration/property/test_importer_input_channels_property.py` — four-channel byte-equality holds across iterations with the real nested wrapper.
  - Re-run the broader preservation sweep and confirm no regressions:
    - `pytest tests/integration/test_error_codes.py` (unchanged).
    - `pytest tests/integration/test_learning.py` (unchanged — Bug 2 from the parent spec is not re-addressed here per R3.7).
  - If any test fails or coverage drops, diagnose the root cause before proceeding; ask the user if questions arise.
  - _Requirements: All R2.* and R3.* from bugfix.md_

## Commit

- [x] 7. Commit the fix as a single `fix(import_plan)` commit
  - **DO NOT actually commit from this task file** — this entry is instructional for when the implementation phase lands.
  - Follow Amazon Conventional-Commits (`fix:`) per the `amazon-builder/amazon-builder-git.md` user rule.
  - Suggested commit message:
    - Subject (≤ 50 chars): `fix(import_plan): resolve real AMQ nested paths`
    - Body: explain that `_AMQ_FIELD_MAP` was guessed on v0.1.1 and rejected the real AMQ export (`INVALID_INPUT missing_field=artist_name`); note that the real shape nests required fields under `songInfo` / `songInfo.animeNames` and exposes the media URL as top-level `videoUrl`; note that the table is rewritten to path-tuple candidates with a new `_get_nested` helper, and every AMQ-shaped test plus the `skills/importing-amq-songs/references/plan-shape.md` doc is rewritten in the same pass so nothing contradicts the fixed code; note v0.1.2 ships via the existing release pipeline with no CLI / error-code / schema change.
  - Scope: all files touched in one logical change — `scripts/import_plan.py`, `tests/fixtures/amq_song_export-small.json`, `tests/unit/test_importer_preprocessing.py`, `tests/integration/test_import_plan.py`, `tests/integration/property/test_importer_input_channels_property.py`, `skills/importing-amq-songs/references/plan-shape.md`.
  - Keep the commit self-contained: fixture, code fix, helper, unit tests, rewritten AMQ-shaped tests, and doc land together so commit history never contains a persistently-failing test.
  - Rollout per design: v0.1.1 is already tagged and released; this ships as v0.1.2 when the user tags and pushes. The existing release pipeline (`release.md`, `.github/workflows/release.yml`) produces a v0.1.2 zip unchanged.
  - Do NOT `git push`.
  - _Requirements: n/a (instructional task, no validation)_
