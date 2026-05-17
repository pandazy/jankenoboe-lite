# Implementation Plan

This task list translates `design.md` into an executable plan for
making the show romaji a required input on the AMQ importer. The
order follows the bugfix workflow's Task-1-first-fails pattern:
two exploration tests up front that MUST fail on unfixed code (the
failures are the evidence of the bug), then the live-code fix
(`scripts/import_plan.py` only — `import_resolve.py` already has
the wiring), then existing AMQ-shaped tests rewritten in place to
carry `show_name_romaji` / `animeNames.romaji`, then the
exploration-test re-run that confirms the fix, then the doc
touches (skill body + plan-shape reference), then the final gate,
then the single commit.

Every AMQ-shaped test in the repo currently encodes payloads with
no romaji on the show. Those tests are self-consistent but
fictional after this fix — rewriting them to carry the new
required field is part of the fix, not preservation (analogous to
Task 3 in the parent `amq-real-export-shape-fix` spec, which
rewrote every AMQ wrapper in the same pass as the mapping-table
fix). The structural contracts each rewritten test asserts
(required-field-missing raises `INVALID_INPUT`, extras silently
dropped, stable key order, byte-equal plans across the four input
channels on equivalent flat payloads) stay unchanged.

Ships as v0.1.7 via the existing release pipeline. No new CLI
flags, no new error codes (the romaji rejection rides
`INVALID_INPUT` with `details.kind = "missing_romaji"` per
Decision 1), no schema change (`show.name_romaji` already exists).

## Bug condition exploration tests (fail on unfixed code)

- [ ] 1. Write the storage-gap exploration test — real AMQ fixture persists romaji into the show block
  - **Property 1: Bug Condition** — Today's `_resolve_show` hard-codes `name_romaji: None`, so the persistence pipe is silently null even when a romaji is present in the input.
  - **CRITICAL**: This test MUST FAIL on unfixed code — the failure is the evidence the bug exists.
  - **DO NOT attempt to fix the test or the code when it fails.**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation.
  - **GOAL**: Surface the concrete counterexample (every `show_to_create.name_romaji` is `null` on the existing 9-song fixture) that demonstrates the storage gap.
  - The committed real AMQ fixture at `tests/fixtures/amq_song_export-small.json` is already read-only across every test that consumes it — reuse it via `shutil.copyfile` per the parent spec's pattern; DO NOT mutate it.
  - Add a new integration test `test_real_amq_export_persists_romaji_into_show_block` to `tests/integration/test_import_plan.py` (style matches `test_real_amq_export_file_ingests_end_to_end` from the parent spec).
  - Resolve the fixture path absolutely from `__file__` and `shutil.copyfile` it to `tmp_app_root / "amq_real.json"`.
  - Use the `tmp_app_root` fixture with zero rows seeded — every AMQ song lands in `auto_completable` against an empty DB.
  - Run `import_plan.py --input-jsonpath amq_real.json --output plan.json` via `pinned_call`.
  - Parse `plan.json` and iterate `plan["auto_completable"]`; for every entry, assert:
    - `entry["show_to_create"]["name_romaji"]` is a non-empty string.
    - `entry["show_to_create"]["name_romaji"]` matches the corresponding `songInfo.animeNames.romaji` value in the source fixture (look up by `(name, vintage)`).
  - **EXPECTED OUTCOME ON UNFIXED CODE**: every `show_to_create.name_romaji` is `null`; the first non-empty assertion fails. This confirms the storage gap.
  - **EXPECTED OUTCOME ON FIXED CODE**: every assertion passes — every block carries the resolved romaji.
  - Document the exact counterexample (`show_to_create.name_romaji is null on every block`) in the task's done-when notes.
  - _Bug_Condition: isBugCondition(input) where input.payload reaches the classifier with romaji present at the canonical path — today's code accepts but does not persist_
  - _Expected_Behavior: Property 1 (Expected Behavior) from design — `_resolve_show` threads romaji onto every `show_to_create` block_
  - _Preservation: None — this is the fix-checking test_
  - _Requirements: R2.2, R2.5, R2.6, R2.13, R3.10_

- [ ] 2. Write the validation-gap exploration test — romaji-stripped variant is rejected
  - **Property 1: Bug Condition** — Today's preprocessor lists romaji only as a fallback under `show_name`; an entry with English present and romaji empty/missing passes silently.
  - **CRITICAL**: This test MUST FAIL on unfixed code — the failure is the evidence the bug exists.
  - **DO NOT attempt to fix the test or the code when it fails.**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation.
  - **GOAL**: Surface the concrete counterexample (importer accepts a romaji-stripped fixture without rejection) that demonstrates the validation gap.
  - Commit a new fixture at `tests/fixtures/amq_song_export-small-no-romaji.json`. It is byte-identical to `amq_song_export-small.json` except every `songs[i].songInfo.animeNames.romaji` is set to the empty string. Keep it read-only across every test that consumes it (R3.10) — copy it into `tmp_app_root` via `shutil.copyfile`, never mutate it.
  - Add a new integration test `test_real_amq_export_missing_romaji_is_rejected` to `tests/integration/test_import_plan.py`.
  - Resolve the fixture path absolutely from `__file__` and `shutil.copyfile` it to `tmp_app_root / "amq_real_no_romaji.json"`.
  - Use the `tmp_app_root` fixture with zero rows seeded.
  - Run `import_plan.py --input-jsonpath amq_real_no_romaji.json --output plan.json` via `pinned_call`.
  - Assert:
    - `rc == 1` and `plan.json` is not written (or is empty / missing).
    - The stderr envelope is `{"ok": false, "error": {"code": "INVALID_INPUT", "message": "AMQ song at index 0 is missing required field show_name_romaji.", "details": {"index": 0, "missing_field": "show_name_romaji", "kind": "missing_romaji", "available_keys": [...]}}}`.
    - `error.details.kind == "missing_romaji"` — this is the discriminator the agent's Step 0 sniff and recovery branch key on.
  - **EXPECTED OUTCOME ON UNFIXED CODE**: `rc == 0`, `plan.json` is written, every `show_to_create.name_romaji` is `null`. The `rc == 1` assertion fails. This confirms the validation gap.
  - **EXPECTED OUTCOME ON FIXED CODE**: all assertions pass.
  - Document the exact counterexample (`rc == 0 on the romaji-stripped fixture`) in the task's done-when notes.
  - _Bug_Condition: isBugCondition(input) where input.payload reaches the classifier with at least one entry whose canonical romaji slot is empty_
  - _Expected_Behavior: Property 1 from design — typed rejection naming `show_name_romaji` with `kind = "missing_romaji"`_
  - _Preservation: None — this is the fix-checking test_
  - _Requirements: R2.1, R2.13, R3.10_

## Fix

Live code in `scripts/import_plan.py` only. The classifier, the
four input channels, the resolve step, the schema, and
`_common.VALID_ERROR_CODES` stay byte-identical.

- [ ] 3. Land the romaji as a required flat key end-to-end through `import_plan.py`
  - Parent task. All changes land in `scripts/import_plan.py` in one pass so the mapping table, the candidate loop, the flat loader, the AMQ loader, and `_resolve_show` stay consistent at every commit-boundary. No code changes to `import_resolve.py` (Decision in design — `_ensure_show` already reads `block.get("name_romaji")`).

  - [ ] 3.1 Update `_AMQ_FIELD_MAP` per Decision 3 — drop romaji fallback under `show_name`, add `show_name_romaji` as its own required row
    - The table's row signature stays `(flat_key, tuple[tuple[str, ...], ...], required)` per Decision 1 of the parent `amq-real-export-shape-fix` spec.
    - Final table:
      ```python
      _AMQ_FIELD_MAP: tuple[tuple[str, tuple[tuple[str, ...], ...], bool], ...] = (
          ("artist_name",      (("songInfo", "artist"), ("artist_name",)), True),
          ("song_name",        (("songInfo", "songName"), ("song_name",)), True),
          ("show_name",        (("songInfo", "animeNames", "english"),
                                ("show_name",)), True),
          ("show_name_romaji", (("songInfo", "animeNames", "romaji"),
                                ("show_name_romaji",)), True),
          ("vintage",          (("songInfo", "vintage"), ("animeVintage",),
                                ("vintage",)), True),
          ("media_url",        (("videoUrl",), ("audio",), ("media_url",),
                                ("MP3",), ("mp3",)), False),
      )
      ```
    - Two changes from v0.1.6:
      - `show_name` row drops `("songInfo", "animeNames", "romaji")` from its candidate paths. English is the only AMQ-nested candidate; the single-key `("show_name",)` flat alias stays so already-flat callers keep working.
      - New `show_name_romaji` row, marked required, with the AMQ-nested path `songInfo.animeNames.romaji` plus the single-key flat alias `show_name_romaji`.
    - No other entry in `_AMQ_FIELD_MAP` changes — `artist_name`, `song_name`, `vintage`, `media_url` rows stay byte-identical.
    - _Bug_Condition: isBugCondition(input) where input.payload reaches the classifier with at least one entry whose romaji is empty / missing_
    - _Expected_Behavior: Property 1 from design — romaji is a first-class required flat key on the preprocessor output_
    - _Preservation: Property 2 from design — every other flat key resolves from the same paths it does today_
    - _Requirements: R2.1, R2.2, R2.3, R2.4_

  - [ ] 3.2 Update the candidate loop in `_amq_entry_to_flat` per Decision 4 — add `details.kind = "missing_romaji"` discriminator
    - The candidate loop's iteration logic stays exactly as the parent `amq-real-export-shape-fix` spec landed it. Only the `details` dict on the rejection envelope grows one conditional key when the missing flat key is `show_name_romaji`:
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
                  details: dict[str, Any] = {
                      "index": i,
                      "missing_field": flat_key,
                      "available_keys": sorted(entry.keys()),
                  }
                  if flat_key == "show_name_romaji":
                      details["kind"] = "missing_romaji"
                  raise _common.KnownError(
                      "INVALID_INPUT",
                      f"AMQ song at index {i} is missing required field {flat_key}.",
                      details,
                  )
              picked = ""
          flat[flat_key] = picked
      ```
    - Other missing-required-field rejections (`artist_name`, `song_name`, `show_name`, `vintage`) continue to emit the existing envelope without `details.kind`. The new field is purely additive on the romaji rejection — no existing wire contract is changed.
    - The error message string (`"AMQ song at index {i} is missing required field {flat_key}."`) is unchanged across every flat key — only the structured `details` dict varies.
    - _Bug_Condition: isBugCondition(input) where input.payload reaches the classifier with at least one entry whose romaji is empty / missing_
    - _Expected_Behavior: Property 1 from design — typed rejection naming `show_name_romaji` carries `kind = "missing_romaji"`_
    - _Preservation: Property 2 from design — every other rejection envelope is byte-identical to v0.1.6_
    - _Requirements: R2.1_

  - [ ] 3.3 Update `_load_entries` (legacy flat surface) and `_entries_from_parsed` (new-channel flat path) to require `show_name_romaji`
    - `_load_entries` and `_entries_from_parsed` both build a normalised dict with the five flat keys today; they need to grow `show_name_romaji` and validate it the same way `_amq_entry_to_flat` does.
    - The cleanest implementation per the design's "Changes Required" item 3 is to share the validator: refactor both functions to hand each entry through `_amq_entry_to_flat` against a flat-only path tuple subset of `_AMQ_FIELD_MAP`. The flat-alias single-key paths in the table (e.g. `("show_name_romaji",)` on the new row, `("artist_name",)` on the artist row) already cover the flat case — `_amq_entry_to_flat` walks them via `_get_nested` and rejects with the same envelope shape.
    - If sharing the validator costs too many cross-cutting changes, the safe alternative is:
      - Add `show_name_romaji` to the dict literal in both functions:
        ```python
        normalised = {
            "artist_name": str(decoded.get("artist_name", "")),
            "song_name": str(decoded.get("song_name", "")),
            "show_name": str(decoded.get("show_name", "")),
            "show_name_romaji": str(decoded.get("show_name_romaji", "")),
            "vintage": str(decoded.get("vintage", "")),
            "media_url": str(decoded.get("media_url", "")),
        }
        ```
      - After the dict is built, raise `INVALID_INPUT details.kind = "missing_romaji"` if `normalised["show_name_romaji"] == ""`. Same envelope shape as the AMQ-preprocessor rejection. Use `index` from the enumerate counter as today.
    - Either approach is acceptable; the requirement is that flat entries with no `show_name_romaji` get rejected with the same `INVALID_INPUT details.kind = "missing_romaji"` envelope the AMQ preprocessor raises (R2.4).
    - The legacy `--input` / positional surface, the `--input-array` channel, and `--input-jsonpath` / `--input-jsonstr` on flat payloads all route through one of these two functions, so the rejection surfaces uniformly across channels.
    - _Bug_Condition: isBugCondition(input) for flat payloads through any channel_
    - _Expected_Behavior: Property 1 from design — flat-channel rejection envelope matches AMQ-channel rejection envelope_
    - _Preservation: Property 2 from design — flat entries that already carry a non-empty `show_name_romaji` produce the same plan they do today_
    - _Requirements: R2.4_

  - [ ] 3.4 Update `_resolve_show` per Decision in design's "Changes Required" item 5 — thread romaji onto the `show_to_create` block
    - The `_resolve_show` function today emits `"name_romaji": None` on the `show_to_create` block. After this fix it emits the resolved romaji string.
    - Before:
      ```python
      return {
          "show_to_create": {
              "name": entry["show_name"],
              "vintage": entry["vintage"],
              "s_type": None,
              "name_romaji": None,
          },
          "media_url": entry["media_url"],
      }
      ```
    - After:
      ```python
      return {
          "show_to_create": {
              "name": entry["show_name"],
              "vintage": entry["vintage"],
              "s_type": None,
              "name_romaji": entry["show_name_romaji"],
          },
          "media_url": entry["media_url"],
      }
      ```
    - Only the `name_romaji` value changes from `None` to a real string. The block's key order, the block's other fields, and the `show_id` branch (when an existing show matches) stay byte-identical.
    - The downstream `_ensure_show` in `scripts/import_resolve.py` already reads `block.get("name_romaji")` and passes it to `_common.insert_row`. No code change there is needed (R3.6 of bugfix.md).
    - _Bug_Condition: isBugCondition(input) where input.payload reaches the classifier with romaji present_
    - _Expected_Behavior: Property 1 from design — `show_to_create.name_romaji` is a non-null string on every block_
    - _Preservation: Property 2 from design — `show_id` branch is byte-identical when an existing show matches_
    - _Requirements: R2.5, R2.6_

  - [ ] 3.5 Confirm no other code in `scripts/import_plan.py` is touched
    - `_get_nested`, `_discriminate`, `_flatten_amq`, `_classify`, the four-channel input dispatcher (`--input-jsonpath` / `--input-jsonstr` / `--input-array` / legacy `--input`), and `_run` all stay byte-identical.
    - Confirm `scripts/import_resolve.py` is untouched — `_ensure_show` already handles `name_romaji` correctly through `block.get`.
    - Confirm `scripts/_common.py` is untouched — `VALID_ERROR_CODES` does not grow a new entry (Decision 1); `EXPECTED_SCHEMA["show"]` and `SPECS["show"].columns` already include `name_romaji`.
    - Confirm `scripts/schema.sql` is untouched and `tests/fixtures/schema.sql` is byte-identical (no `make schema-sync` needed).
    - _Bug_Condition: n/a (preservation check)_
    - _Expected_Behavior: n/a (preservation check)_
    - _Preservation: Property 2 from design — every script other than `import_plan.py` is byte-identical_
    - _Requirements: R3.7, R3.8_

## Resolve-step coverage

The resolve step's `_ensure_show` already writes
`name_romaji = block.get("name_romaji")` into the new show row.
Today that line always feeds `None`, so the path is uncovered by
the test suite. After Task 3.4 lands, the path starts feeding real
strings — but no test asserts this end-to-end yet.

- [ ] 4. Add `test_resolve_persists_show_name_romaji_into_db` to `tests/integration/test_import_resolve.py`
  - Goal: cover the resolve step's column write so a future regression that flips `name_romaji = None` back into the block (or strips the column from `_common.SPECS["show"]`) gets caught.
  - Hand-craft a `plan.json` with one `auto_completable` entry whose `show_to_create` carries:
    ```python
    {
      "name": "Foo",
      "vintage": "Spring 2010",
      "s_type": None,
      "name_romaji": "Foo Romaji",
    }
    ```
    plus an `artist_to_create` and `song_name`. Use `tmp_app_root` with zero rows seeded.
  - Run `import_resolve.py --plan plan.json --output triples.json` via `pinned_call`. Assert `rc == 0`.
  - Open `db/datasource.db` (via `_common.open_db` or sqlite3 directly), `SELECT name, name_romaji FROM show WHERE name = 'Foo'`, and assert `name_romaji == "Foo Romaji"`.
  - **EXPECTED OUTCOME ON UNFIXED CODE**: passes — `_ensure_show` writes whatever the block carries; this is a coverage-only test, so it does not depend on Task 3.
  - **EXPECTED OUTCOME ON FIXED CODE**: passes — same wiring, now actually exercised end-to-end.
  - This test is preservation-focused: it locks in `_ensure_show`'s behaviour so if a future refactor breaks the wiring, the test catches it.
  - _Bug_Condition: n/a (coverage only)_
  - _Expected_Behavior: Property 1 from design — column write_
  - _Preservation: Property 2 from design — `_ensure_show` keeps writing `name_romaji` on insert_
  - _Requirements: R2.6_

## Rewrite existing AMQ-shaped tests to carry romaji

Every AMQ-shaped test in the repo currently encodes payloads with
no `songInfo.animeNames.romaji` and no `show_name_romaji` flat key.
Those tests are self-consistent but fictional after this fix —
updating them to carry the new required field is part of the fix,
not preservation. The structural assertions each test makes
(required-field-missing raises `INVALID_INPUT`, extras silently
dropped, stable key order, byte-equal plans across the four input
channels, etc.) are preserved verbatim; only the payload shape
each test builds grows the new field.

- [ ] 5. Rewrite every pre-existing AMQ-shaped test to carry `animeNames.romaji` and `show_name_romaji`
  - Parent task. Three batches below cover the unit-test file, the named integration tests, and the property-based four-channel equivalence helper. All three batches land in the same pass as the Task 3 fix so the repo is never in a state where the table and the tests disagree.

  - [ ] 5.1 Rewrite `tests/unit/test_importer_preprocessing.py` — every AMQ-shaped test plus three new tests
    - For every existing `_amq_entry_to_flat` test that constructs a real-AMQ-shape entry: add `"romaji": "<string>"` to the inner `animeNames` dict (or, for tests that exercise the romaji-as-show-name fallback, decide whether the test stays — see below).
    - For every existing `_amq_entry_to_flat` test that constructs a flat-alias entry: add `"show_name_romaji": "<string>"` next to `"show_name"`.
    - Specifically:
      - **Existing test `test_amq_entry_to_flat_english_name_beats_romaji_when_both_present`**: keep — the English-over-romaji precedence on `show_name` is gone, but the test now asserts that `show_name = english` and `show_name_romaji = romaji` (both fields land separately). Update the assertion accordingly.
      - **Existing test `test_amq_entry_to_flat_romaji_used_when_english_absent`**: REWRITE — the fallback is removed. The test becomes `test_amq_entry_to_flat_missing_english_raises_invalid_input`: an entry with `animeNames.english = ""` and `animeNames.romaji = "Foo"` raises `INVALID_INPUT missing_field=show_name` (no `kind` field), confirming the fallback is gone (R2.3).
      - **Add new test `test_amq_entry_to_flat_show_name_romaji_present`**: an entry with both `animeNames.english` and `animeNames.romaji` populated emits `show_name_romaji = animeNames.romaji` on the flat output dict.
      - **Add new test `test_amq_entry_to_flat_missing_show_name_romaji_raises_with_kind_missing_romaji`**: an entry with `animeNames.english = "Foo"` and `animeNames.romaji = ""` raises `INVALID_INPUT details.missing_field = "show_name_romaji"` AND `details.kind = "missing_romaji"`. This locks the discriminator the agent's Step 0 sniff and recovery branch key on.
      - **Add new test `test_amq_entry_to_flat_show_name_romaji_flat_alias_works`**: an entry with `show_name_romaji` at the top level (the flat-alias single-key path) emits the value through. This locks the four-channel byte-equality contract for the new field.
      - **Existing test `test_amq_entry_to_flat_key_order_is_stable`**: update the expected key list to include `show_name_romaji` between `show_name` and `vintage`, matching `_AMQ_FIELD_MAP`'s declared order in Task 3.1.
      - **Every other `_amq_entry_to_flat` test** (`test_amq_entry_to_flat_all_amq_keys_present`, `test_amq_entry_to_flat_all_flat_alias_keys_present`, `test_amq_entry_to_flat_missing_media_url_defaults_to_empty`, `test_amq_entry_to_flat_empty_string_media_candidates_default_to_empty`, `test_amq_entry_to_flat_missing_artist_raises_invalid_input`, `test_amq_entry_to_flat_empty_string_artist_counts_as_missing`, `test_amq_entry_to_flat_missing_song_name_raises`, `test_amq_entry_to_flat_missing_show_name_raises`, `test_amq_entry_to_flat_missing_vintage_raises`, `test_amq_entry_to_flat_drops_extra_amq_native_fields`): grow the entry by `animeNames.romaji` (or `show_name_romaji` on flat-alias variants) so the entry passes every other required-field check; otherwise the missing-romaji rejection now fires before the test's intended rejection, which would change the asserted `missing_field`.
      - For tests that explicitly assert the order of rejection (`missing_artist` fires first, then `missing_song`, etc.), the order is unchanged: rejections fire in `_AMQ_FIELD_MAP` declaration order, and `show_name_romaji` is between `show_name` and `vintage`, so `artist_name` / `song_name` / `show_name` rejections still beat it.
    - For every existing `_flatten_amq` test that constructs songs: grow each song dict by `animeNames.romaji` so the file is acceptable end-to-end. The structural assertions (three-song happy path, non-dict-entry-raises-with-index, empty-songs-returns-empty-list, ignores-top-level-siblings) stay verbatim.
    - The `_discriminate` tests at the top of the file stay byte-identical — the discriminator only inspects top-level list-vs-dict-with-`songs`-list and doesn't care about per-song shape.
    - Update the `available_keys` assertions on the `missing_artist` test if the real top-level keys of a real nested entry change (they should not — `available_keys` is the entry's own top-level keys, e.g. `["songInfo", "videoUrl"]`, and the romaji lives nested inside `songInfo.animeNames` so adding it does not change the top-level key list).
    - **Rationale for editing these tests in place**: they were self-consistent but fictional with respect to the new required field — updating them is part of the fix, not preservation.
    - _Bug_Condition: isBugCondition(input) for AMQ-shaped entries_
    - _Expected_Behavior: Property 1 from design — `_amq_entry_to_flat` emits the romaji as its own flat key, rejects when missing with `kind = "missing_romaji"`_
    - _Preservation: Property 2 from design — structural contracts (envelope shape, extras dropped, key order) hold on the new shape_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R3.11_

  - [ ] 5.2 Rewrite three named AMQ-shaped tests in `tests/integration/test_import_plan.py`
    - `test_raw_amq_via_input_jsonpath_matches_flat_via_input`: add `"romaji"` to every `animeNames` dict in `amq_raw_payload`, and add `show_name_romaji` to every flat baseline entry the test constructs to compare against. Test purpose (raw AMQ via `--input-jsonpath` byte-matches the equivalent flat array via legacy `--input`) and every assertion stay unchanged.
    - `test_input_jsonstr_raw_amq_matches_flat_via_input`: same update.
    - `test_input_array_rejects_raw_amq_with_invalid_input`: add `"romaji"` to the inner `animeNames` dict in `amq_raw_jsonstr`. Assertions unchanged — the `--input-array` flat-only rejection contract holds for the real nested AMQ shape regardless of romaji presence per R3.3 of the parent spec.
    - **Existing test `test_real_amq_export_file_ingests_end_to_end`** (from the parent `amq-real-export-shape-fix` spec): keep — the existing fixture already carries `animeNames.romaji` on every entry. After the fix lands, this test continues to pass; it no longer fails on a missing romaji, since one is present.
    - Every other integration test in `tests/integration/test_import_plan.py` that drives a flat array (legacy `--input` flow, `--input-array` flat flow, error paths, read-only DB, mixed buckets) grows `show_name_romaji` on every entry it constructs. Tests that explicitly exercise rejection paths (`INVALID_INPUT` on missing required field, `INVALID_INPUT` on non-array top-level, etc.) carry `show_name_romaji` so the rejection under test still fires before the new romaji rejection — preserving the asserted `missing_field`.
    - **Rationale for editing these tests in place**: they were self-consistent but fictional with respect to the new required field — updating them is part of the fix, not preservation.
    - _Bug_Condition: isBugCondition(input) for AMQ payloads through any channel_
    - _Expected_Behavior: Property 1 from design — byte-equal plans across channels carry the new `show_name_romaji` key uniformly_
    - _Preservation: Property 2 from design — `--input-array` flat-only rejection contract preserved against the new shape_
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R3.11_

  - [ ] 5.3 Update `_wrap_as_raw_amq` and the flat baseline builder in `tests/integration/property/test_importer_input_channels_property.py`
    - Add `"romaji": e["show_name_romaji"]` to the inner `animeNames` dict produced by `_wrap_as_raw_amq`:
      ```python
      return {
          "songs": [
              {
                  "songInfo": {
                      "artist": e["artist_name"],
                      "songName": e["song_name"],
                      "animeNames": {
                          "english": e["show_name"],
                          "romaji": e["show_name_romaji"],
                      },
                      "vintage": e["vintage"],
                  },
                  "videoUrl": e["media_url"],
              }
              for e in flat
          ],
          "extra": "metadata",
      }
      ```
    - Update the flat baseline payload generator to include a non-empty `show_name_romaji` on every entry. If the existing generator uses Hypothesis strategies, add a strategy for `show_name_romaji` that mirrors the `show_name` strategy (non-empty text). If it uses fixed values, pick a deterministic non-empty string (e.g. `f"romaji_{i}"`).
    - Update the per-file docstring to note the wrapper now exercises the romaji field (the rest of the docstring — property names, iteration semantics, seed offset — stays).
    - The test function `test_all_input_channels_produce_byte_equal_plans` is unchanged — it still drives every generated flat payload through all six channels (legacy `--input`, `--input-jsonpath` on flat, `--input-jsonstr` on flat, `--input-array` on flat, `--input-jsonpath` on raw AMQ, `--input-jsonstr` on raw AMQ) and asserts byte-equality against the legacy baseline. The property is the same; the wrapper shape it exercises grows one field.
    - This is the preservation vehicle for Property 2 (see design "Preservation Checking"). On unfixed code with only this helper updated (no table fix), the PBT fails with `INVALID_INPUT missing_field=show_name_romaji` — that's the intended shape of the regression gate; running it that way is not part of the task order but is documented in the design for future reference.
    - **Rationale for editing this helper in place**: the helper was self-consistent but fictional with respect to the new required field — updating it is part of the fix, not preservation.
    - _Bug_Condition: isBugCondition(input) for AMQ payloads through `--input-jsonpath` and `--input-jsonstr`_
    - _Expected_Behavior: Property 1 from design — raw-AMQ-equivalent-to-flat byte-equality carries `show_name_romaji` across randomised payloads_
    - _Preservation: Property 2 from design — flat-array byte-equality across channels unchanged_
    - _Requirements: R2.1, R2.2, R2.4, R3.11_

## End-to-end pipeline coverage

- [ ] 6. Update `tests/integration/test_import_pipeline_e2e.py` to assert `show.name_romaji` is non-null on newly-created shows
  - The end-to-end pipeline test today drives `import_plan.py` → `import_resolve.py` → `add_play_history.py` against a flat or AMQ payload and checks the resulting DB rows. After this fix, every newly-created show row should carry a non-null `name_romaji` matching the input AMQ song's romaji.
  - For every existing test in this file that creates show rows from a payload: after the pipeline finishes, `SELECT name, name_romaji FROM show` and assert that for every row whose `name` matches an input entry's English title, `name_romaji` matches the corresponding entry's romaji. (Skip existing-show rows the test seeded directly via fixtures — only assert on newly-created rows.)
  - If the existing test payloads have no romaji today, grow them to carry `show_name_romaji` (flat) or `animeNames.romaji` (AMQ) on every entry — same fix-not-preservation rationale as Task 5.
  - Test purpose (the three-step pipeline produces `play_history` rows pointing at the right show / song / artist) is unchanged; only the additional `name_romaji` assertion is new.
  - This is the integration evidence for Property 1's persistence claim — the romaji travels from input AMQ JSON → flat preprocessor output → `show_to_create` block → `_ensure_show` INSERT → `show.name_romaji` column.
  - _Bug_Condition: isBugCondition(input) where input.payload reaches the classifier with romaji present_
  - _Expected_Behavior: Property 1 from design — every newly-created show row carries non-null `name_romaji`_
  - _Preservation: Property 2 from design — `play_history` / `rel_show_song` / `song` / `artist` rows are byte-identical to v0.1.6_
  - _Requirements: R2.5, R2.6, R2.13_

## Verification

- [ ] 7. Verify the Task 1 and Task 2 exploration tests now pass
  - **Property 1: Expected Behavior** — Persistence: every `show_to_create.name_romaji` is non-null on the existing fixture. Validation: the romaji-stripped variant is rejected with `INVALID_INPUT details.kind = "missing_romaji"`.
  - **IMPORTANT**: Re-run the SAME tests from Task 1 and Task 2 — do NOT write new tests. The Task 1 and Task 2 tests encode the expected behavior.
  - Run in isolation:
    - `pytest tests/integration/test_import_plan.py::test_real_amq_export_persists_romaji_into_show_block`
    - `pytest tests/integration/test_import_plan.py::test_real_amq_export_missing_romaji_is_rejected`
  - **EXPECTED OUTCOME**:
    - Test 1 PASSES — every `show_to_create.name_romaji` matches the source fixture's `songInfo.animeNames.romaji`.
    - Test 2 PASSES — `rc == 1`, stderr envelope is `INVALID_INPUT details.kind = "missing_romaji"` naming `show_name_romaji` as the missing field on entry index 0.
  - If either test still fails, do not proceed to Task 8 — diagnose the root cause and revisit Task 3 (and possibly Task 5) before continuing.
  - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.13_

## Documentation

The agent surface (`skills/importing-amq-songs/SKILL.md`) and the
plan-shape reference both need updates per Decision 7. Skill docs
do not get assertion tests per the parent spec's decision.

- [ ] 8. Add Step 0 — Shape sniff and Manual recovery sections to `skills/importing-amq-songs/SKILL.md`
  - Per Decision 5 of design.md. The sniff is a procedure the agent performs directly — no new script, no new flag.
  - Add a new "Step 0 — Shape sniff" section to the Checklist, **before** "Step 1 — plan". Section content:
    - One-paragraph intro: the sniff is read-only, runs before `import_plan.py`, and catches romaji-shape drift before the API surface rejects.
    - Procedure: read the user's AMQ JSON, walk each `songs[i]`, and verify `songInfo.animeNames.romaji` is a non-empty string. On miss, classify the failure mode against the named hypothesis taxonomy (Decision 5):
      - **Hypothesis A — Shape drift**: every entry has a `songInfo.animeNames` sub-object but `animeNames` has no `romaji` key (or the value is empty / null). Report the actual key list inside `animeNames` for at least one affected entry. If a sibling key holds a plausible romaji value (non-empty string), propose it as the candidate recovery path with one sample value.
      - **Hypothesis B — Truncated / malformed entries**: at least one `songs[i]` is missing the `songInfo` container, or `songInfo` is missing `animeNames`, entirely. Report the index of every affected entry plus its top-level keys.
      - **Hypothesis C — Genuinely-empty romaji**: `songInfo.animeNames` is intact and has a `romaji` key whose value is empty or `null`. Report affected indices.
    - Report format (verbatim, so the agent doesn't drift across sessions):
      ```
      Step 0 — Shape sniff result: FAILED for N entries.

        Hypothesis A — Shape drift (most likely):
          affected indices: [0, 1, 4, 5]
          songInfo.animeNames keys observed: ["english", "romajiTitle"]
          candidate recovery path: songInfo.animeNames.romajiTitle
          sample value at songs[0].songInfo.animeNames.romajiTitle:
            "Wooser no Sono Higurashi: Kakusei-hen"

        Confirm? Type "y" to accept Hypothesis A and recover via
        scripts/data.py create. Type "n" to abort and inspect the file.
      ```
    - On success (every entry has a non-empty romaji at the canonical path), Step 0 is silent — the agent proceeds straight to Step 1.
  - Add a new "Manual recovery" section after the Checklist, per Decision 6 of design.md:
    - One-paragraph intro: when the user confirms a Step 0 diagnosis, the agent extracts the romaji and inserts the show via `scripts/data.py create --kind show`, then re-runs the three-step pipeline.
    - Procedure: for each affected entry, run:
      ```
      python scripts/data.py create --kind show '{
        "name": "<English title from the entry>",
        "name_romaji": "<extracted romaji>",
        "vintage": "<vintage from the entry>",
        "s_type": null
      }'
      ```
      Then re-run Steps 1–3 of the import pipeline. The classifier's existence query (`name = ? AND vintage = ?`) hits the freshly-created show row and emits a `show_id` instead of a `show_to_create`.
  - Update the existing "Input shape" section to reflect the new contract:
    - The flat array shape now carries six required fields per entry: `artist_name`, `song_name`, `show_name`, `show_name_romaji`, `vintage`, plus optional `media_url`.
    - The AMQ-nested example shows `animeNames.romaji` populated.
  - Do NOT touch any other skill file under `skills/` — only `importing-amq-songs/SKILL.md` and the plan-shape reference (Task 9) are in scope for this fix.
  - **Skill docs do not get assertion tests** — the parent spec's decision stands.
  - _Bug_Condition: isBugCondition(input) — agent surface diagnoses the same entries the API rejects_
  - _Expected_Behavior: Property 1 from design — Step 0 sniff classifies failures against the named taxonomy; Manual recovery uses `data.py create --kind show`_
  - _Preservation: R3.13 — no other `skills/**` file is touched_
  - _Requirements: R2.8, R2.9, R2.10, R2.11, R2.12, R3.13_

- [ ] 9. Update `skills/importing-amq-songs/references/plan-shape.md` per Decision 7
  - Document `show_name_romaji` as a required field on the flat array shape. The flat array section grows from five to six required fields per entry.
  - Add a row to the AMQ → flat field mapping table:
    | Raw AMQ path(s) tried, in order | Flat key | Required? |
    |---|---|---|
    | `songInfo.artist`, `artist_name` | `artist_name` | yes |
    | `songInfo.songName`, `song_name` | `song_name` | yes |
    | `songInfo.animeNames.english`, `show_name` | `show_name` | yes |
    | `songInfo.animeNames.romaji`, `show_name_romaji` | `show_name_romaji` | yes |
    | `songInfo.vintage`, `animeVintage`, `vintage` | `vintage` | yes |
    | `videoUrl`, `audio`, `media_url`, `MP3`, `mp3` | `media_url` | no — defaults to `""` |
  - Drop the `songInfo.animeNames.romaji` fallback from the `show_name` row (the new row owns that path).
  - Drop the "English wins over Romaji" note — the fallback is gone, English and romaji are independent fields.
  - Update the `show_to_create` example: change `name_romaji: null` to `name_romaji: "<resolved romaji>"`. Both occurrences (`resolved` bucket's create branch and `auto_completable` bucket's create branch).
  - Preserve the drop-on-the-floor note for per-song fields outside the mapping and for top-level siblings of `songs`.
  - Do NOT touch any other subsection (`plan.json`'s top-level structure, `answers.json`, `triples.json`).
  - **Skill docs do not get assertion tests** — the parent spec's decision stands.
  - _Bug_Condition: isBugCondition(input) — the doc currently encodes the v0.1.6 mapping and would contradict the fixed code_
  - _Expected_Behavior: Property 1 from design — doc matches the fixed code's mapping_
  - _Preservation: R3.13 — no other `skills/**` file is touched_
  - _Requirements: R3.12_

## Final gate

- [ ] 10. Checkpoint — run `make check` and confirm coverage ≥ 90%
  - Run `make check` (lint + typecheck + test). Expect all three to pass.
  - Confirm coverage stays ≥ 90% — `./tests/run.sh` enforces this automatically; fail the task if coverage drops. The new flat key, the new `details.kind` discriminator, and the threaded `show_to_create.name_romaji` are exercised by the Task 1, Task 2, Task 4, and Task 6 tests plus the rewritten unit / integration / property tests.
  - Re-run the Task 1 and Task 2 exploration tests and confirm they pass:
    - `pytest tests/integration/test_import_plan.py::test_real_amq_export_persists_romaji_into_show_block`
    - `pytest tests/integration/test_import_plan.py::test_real_amq_export_missing_romaji_is_rejected`
  - Re-run the Task 4 resolve-step coverage test:
    - `pytest tests/integration/test_import_resolve.py::test_resolve_persists_show_name_romaji_into_db`
  - Re-run the Task 6 end-to-end pipeline test (whatever its existing test names are in `test_import_pipeline_e2e.py`).
  - Re-run every rewritten test batch and confirm no regressions:
    - `pytest tests/unit/test_importer_preprocessing.py` — every `_amq_entry_to_flat` test (rewritten + new), every `_flatten_amq` test (rewritten), every `_discriminate` test (unchanged), and every `_get_nested` test (unchanged) pass.
    - `pytest tests/integration/test_import_plan.py` — three rewritten AMQ-shaped tests pass; `test_real_amq_export_file_ingests_end_to_end` from the parent spec stays green; every legacy and flat-path test stays green.
    - `pytest tests/integration/property/test_importer_input_channels_property.py` — four-channel byte-equality holds across iterations with the romaji field on every wrapped entry.
  - Re-run the broader preservation sweep and confirm no regressions:
    - `pytest tests/integration/test_error_codes.py` (unchanged — no new error code).
    - `pytest tests/integration/test_learning.py` (unchanged — Bug 2 is from an earlier spec).
    - `pytest tests/integration/test_data.py` (unchanged — `data.py` is untouched, but the manual-recovery branch in Task 8 invokes it; no test changes needed).
  - Confirm `tests/fixtures/schema.sql` is byte-identical to the pre-fix version (no `make schema-sync` needed).
  - If any test fails or coverage drops, diagnose the root cause before proceeding; ask the user if questions arise.
  - _Requirements: All R2.* and R3.* from bugfix.md_

## Commit

- [ ] 11. Commit the fix as a single `fix(import_plan)` commit
  - **DO NOT actually commit from this task file** — this entry is instructional for when the implementation phase lands.
  - Follow Amazon Conventional-Commits (`fix:`).
  - Suggested commit message:
    - Subject (≤ 50 chars): `fix(import_plan): require show romaji`
    - Body: explain that today's preprocessor reads `songInfo.animeNames.romaji` only as a `show_name` fallback and `_resolve_show` hard-codes `name_romaji: None`, so every newly-created show row gets `name_romaji = NULL`; note that the fix promotes romaji to a required flat key (`show_name_romaji`) with its own row in `_AMQ_FIELD_MAP`, removes the English-falls-back-to-romaji precedence, threads the value onto every `show_to_create` block, and adds a `details.kind = "missing_romaji"` discriminator on the rejection envelope so the agent's Step 0 sniff and recovery branch can key on it; note that no new error code is added (`INVALID_INPUT` is reused), no new CLI flags are added, and no schema migration is needed (`show.name_romaji` already exists); note that `skills/importing-amq-songs/SKILL.md` gains the Step 0 sniff procedure and the `data.py create --kind show` recovery recipe; note v0.1.7 ships via the existing release pipeline.
  - Scope: all files touched in one logical change — `scripts/import_plan.py`, `tests/fixtures/amq_song_export-small-no-romaji.json` (new), `tests/unit/test_importer_preprocessing.py`, `tests/integration/test_import_plan.py`, `tests/integration/test_import_resolve.py`, `tests/integration/test_import_pipeline_e2e.py`, `tests/integration/property/test_importer_input_channels_property.py`, `skills/importing-amq-songs/SKILL.md`, `skills/importing-amq-songs/references/plan-shape.md`.
  - Keep the commit self-contained: code fix, tests, fixtures, and docs land together so commit history never contains a persistently-failing test.
  - Rollout per design: v0.1.6 is already tagged and released; this ships as v0.1.7 when the user tags and pushes. The existing release pipeline (`release.md`, `.github/workflows/release.yml`) produces a v0.1.7 zip unchanged.
  - Do NOT `git push`.
  - _Requirements: n/a (instructional task, no validation)_
