# Implementation Plan: learning-leveldown

## Overview

Convert the feature design into a series of prompts for a code-generation
LLM that will implement each step with incremental progress. Make sure
that each prompt builds on the previous prompts, and ends with wiring
things together. There should be no hanging or orphaned code that isn't
integrated into a previous step. Focus ONLY on tasks that involve
writing, modifying, or testing code.

The approach:

1. Pin the CLI surface, transaction discipline, and Success_Envelope
   shape with example-based integration tests first (RED). This forces
   the implementation to match the shapes in the design before any
   handler is written.
2. Wire `argparse`, `_DISPATCH`, and `_WRITE_CMDS` plus a stub handler
   that emits the minimal `{"updated": []}` envelope on the empty-ids
   path. Enough to green the simplest pinned tests.
3. Add the range check on `--to-level` (R-LD-2.1 step 1.ii / R-LD-2.5).
4. Add the preflight `SELECT * FROM learning WHERE id IN (...)` and
   the three preflight rejections (NOT_FOUND, ALREADY_GRADUATED,
   Strictly_Below_Rule) in the order the requirements doc pins.
5. Add the per-id UPDATE loop and the Leveldown_Update_Entry
   construction.
6. Add the remaining example tests (round-trip with `levelup`,
   due-after-leveldown).
7. Add the P-LD-1..P-LD-6 property tests.
8. Update `skills/reviewing-songs/SKILL.md` per R-LD-5.
9. Final full test run + cleanup.

## Tasks

- [ ] 1. Write contract-pinning example tests for the CLI surface and envelope shape
  - Create `tests/integration/test_learning_leveldown.py` with the tests
    that define the CLI shape and envelope layout before any
    implementation exists. These tests will be RED and will go green as
    implementation lands in tasks 3–6.
  - Each test uses the `tmp_app_root` + `call_script` + `pinned_call` +
    `insert_*` fixtures already in `tests/integration/conftest.py`. No
    new fixtures.
  - Use `json.loads` on stdout and assert on ordered key sets via
    `list(obj.keys()) == [...]` so the tests catch drift in key order
    (R-LD-3.2).
  - _Requirements: R-LD-1.1, R-LD-1.3, R-LD-1.4, R-LD-1.5, R-LD-3.2,
    R-LD-3.3_

  - [ ] 1.1 Add `test_empty_ids_yields_empty_updated_no_writes`
    - Seed any in-range learning row at `level >= 1`. Run
      `leveldown --ids "" --to-level 0`.
    - Assert exit 0, stdout parses, `envelope == {"updated": []}`.
    - Snapshot the `learning` table and the DB file bytes before the
      call; assert byte-identical after.
    - _Requirements: R-LD-1.3, R-LD-1.5_

  - [ ] 1.2 Add `test_output_envelope_keys_in_fixed_order`
    - Seed one active learning row at `level = 5`. Run
      `leveldown --ids L --to-level 2` with a pinned epoch.
    - Assert exit 0, top-level envelope is `{"updated": [...]}` with one
      entry, and the entry's keys are exactly
      `["id", "level", "display_level", "graduated", "previous_level",
      "last_level_up_at", "updated_at"]` in that order.
    - _Requirements: R-LD-3.2_

  - [ ] 1.3 Add `test_now_epoch_consistent_across_batch`
    - Seed two active learning rows at `level = 5`. Run with one pinned
      epoch.
    - Assert both entries' `last_level_up_at == updated_at == pinned`,
      and the two entries share the same value.
    - _Requirements: R-LD-3.3_

  - [ ] 1.4 Add `test_unknown_flag_argparse_error`
    - Run `leveldown --ids L --to-level 0 --foo bar`.
    - Assert exit 2, stderr contains argparse "usage:", stdout empty,
      no JSON parsed.
    - _Requirements: R-LD-1.4_

  - [ ] 1.5 Add `test_missing_to_level_argparse_error`
    - Run `leveldown --ids L`.
    - Assert exit 2, stderr contains argparse "usage:".
    - _Requirements: R-LD-1.4_

  - [ ] 1.6 Add `test_missing_ids_argparse_error`
    - Run `leveldown --to-level 0`.
    - Assert exit 2, stderr contains argparse "usage:".
    - _Requirements: R-LD-1.4_

  - [ ] 1.7 Add `test_non_integer_to_level_argparse_error`
    - Run `leveldown --ids L --to-level abc`.
    - Assert exit 2, stderr contains argparse "usage:".
    - _Requirements: R-LD-1.4_

- [ ] 2. Wire argparse, dispatch, and stub handler for `leveldown`
  - In `scripts/learning.py`, add a `leveldown` subparser inside
    `_build_parser()` with two required flags: `--ids` and `--to-level
    --type=int`. No positional args.
  - Add a new `_cmd_leveldown(conn, args)` handler that (for now) emits
    the minimal envelope `{"updated": []}` when `_csv(args.ids)` is
    empty, and otherwise raises
    `_common.KnownError("INTERNAL_ERROR", "leveldown not implemented")`
    so any non-empty call fails loudly while the rest of the handler is
    still pending.
  - Add `"leveldown": _cmd_leveldown` to `_DISPATCH`.
  - Append `"leveldown"` to `_WRITE_CMDS` so `main()` wraps the call in
    `BEGIN IMMEDIATE` / `COMMIT` (R-LD-1.5).
  - After this task, tasks 1.1, 1.4, 1.5, 1.6, 1.7 should be green;
    1.2 and 1.3 stay RED until task 5.
  - _Requirements: R-LD-1.1, R-LD-1.2, R-LD-1.3, R-LD-1.4, R-LD-1.5_

- [ ] 3. Add the `--to-level` range check
  - In `_cmd_leveldown`, before the empty-ids short-circuit, add the
    range check: `if target < 0 or target > _common.MAX_LEVEL: raise
    KnownError("INVALID_INPUT", "--to-level <N> out of range
    [0, <MAX>]", {"to_level": target, "min": 0, "max":
    _common.MAX_LEVEL})`.
  - The check runs FIRST so an out-of-range `--to-level` with empty
    `--ids` still surfaces `INVALID_INPUT` (R-LD-1.3 caveat).
  - Add example tests to `test_learning_leveldown.py`:
    - `test_to_level_below_zero_invalid_input` — `--to-level -1` →
      exit 1, code `INVALID_INPUT`, `details.min == 0`,
      `details.max == MAX_LEVEL`.
    - `test_to_level_above_max_invalid_input` — `--to-level
      MAX_LEVEL+1` → exit 1, code `INVALID_INPUT`.
    - `test_range_check_runs_before_empty_ids_short_circuit` —
      `--ids "" --to-level -1` → exit 1, code `INVALID_INPUT`. DB
      byte-identical before and after.
  - _Requirements: R-LD-2.1 (step 1.ii), R-LD-2.5_

- [ ] 4. Add preflight `SELECT` and the three preflight rejections
  - In `_cmd_leveldown`, after the range check and the empty-ids
    short-circuit, parse `_csv(args.ids)`, run the preflight `SELECT *
    FROM learning WHERE id IN (?,?,...)`, and build a `rows` dict
    keyed by `id`.
  - In the order pinned by R-LD-2.1, raise:
    1. `KnownError("NOT_FOUND", "<K> learning id(s) not found",
       {"ids": missing})` for any missing id.
    2. `KnownError("ALREADY_GRADUATED", "<K> learning id(s) already
       graduated", {"ids": graduated_ids})` for any row with
       `graduated == 1`.
    3. `KnownError("INVALID_INPUT", "to_level (<N>) must be strictly
       below each record's current level; <K> id(s) failed",
       {"to_level": target, "offenders": [{"id": ..., "level": ...,
       "display_level": ...}, ...]})` for any row with `level <=
       target`.
  - The mid-handler raises rely on `learning.py main()`'s existing
    rollback path; the surrounding `BEGIN IMMEDIATE` is rolled back on
    any non-zero `SystemExit` (R-LD-2.7).
  - Add example tests to `test_learning_leveldown.py`:
    - `test_missing_id_returns_not_found` — one missing id alongside
      two valid ones → exit 1, code `NOT_FOUND`, `details.ids` lists
      only the missing one. DB byte-identical.
    - `test_graduated_id_returns_already_graduated` — one graduated
      id alongside two valid ones → exit 1, code
      `ALREADY_GRADUATED`, `details.ids` lists only the graduated one.
      DB byte-identical.
    - `test_target_equal_to_current_invalid_input` — row at `level =
      5` with `--to-level 5` → exit 1, code `INVALID_INPUT`,
      `details.offenders` contains an entry for the row with `level
      == 5`, `display_level == 6`. DB byte-identical.
    - `test_target_above_current_invalid_input` — row at `level = 5`
      with `--to-level 7` → exit 1, code `INVALID_INPUT`,
      `details.offenders` lists the row.
    - `test_offenders_envelope_includes_level_and_display_level` —
      mixed batch where two rows fail the rule; assert the envelope's
      `details.offenders` contains exactly those two ids and their
      stored `level` / `display_level`.
    - `test_first_failing_preflight_step_wins_not_found_over_other`
      — batch with one missing id AND one graduated id AND one
      below-rule row; assert `code == "NOT_FOUND"` (NOT_FOUND beats
      ALREADY_GRADUATED beats below-rule).
    - `test_first_failing_preflight_step_wins_already_graduated_over_below`
      — batch with one graduated id AND one below-rule row (no
      missing ids); assert `code == "ALREADY_GRADUATED"`.
    - `test_partial_failure_rolls_back_no_partial_writes` — three
      ids, one of which violates the below-rule; assert no row's
      `updated_at` changed and `level` stayed put on every row.
  - _Requirements: R-LD-2.1, R-LD-2.2, R-LD-2.3, R-LD-2.4, R-LD-2.6,
    R-LD-2.7, R-LD-1.5_

- [ ] 5. Add the per-id UPDATE loop and Leveldown_Update_Entry construction
  - In `_cmd_leveldown`, after preflight passes, compute `now =
    _common.now_epoch()` once. For each id in input order, run
    `UPDATE learning SET level = ?, last_level_up_at = ?, updated_at
    = ? WHERE id = ?` with `(target, now, now, lid)`, and append a
    Leveldown_Update_Entry to the `updated` list with the key order
    `[id, level, display_level, graduated, previous_level,
    last_level_up_at, updated_at]`. `previous_level` is read from
    `rows[lid]["level"]` (the preflight value, NOT a re-read).
  - Call `_common.success({"updated": updated})` at the end.
  - After this task, tasks 1.2 and 1.3 should be green.
  - Add example tests to `test_learning_leveldown.py`:
    - `test_leveldown_drops_level_and_resets_clock` — seed row at
      `level = 17, last_level_up_at = T_old, updated_at = T_old`;
      run `--to-level 10` at pinned epoch `E`; query the `learning`
      row directly via `temp_conn` and assert `level == 10`,
      `last_level_up_at == E`, `updated_at == E`.
    - `test_previous_level_is_pre_call_value` — output entry's
      `previous_level == 17` for the above seed.
    - `test_level_up_path_unchanged_on_success` — assert the row's
      `level_up_path` JSON string is byte-identical to the seeded
      value.
    - `test_other_learning_rows_unchanged_on_success` — seed a
      second active row not in `--ids`; assert every column is
      byte-identical after the call.
    - `test_other_tables_unchanged_on_success` — seed song / artist
      / show / play_history / rel_show_song rows; snapshot a hash of
      each table; assert byte-identical after a successful
      `leveldown` call.
    - `test_repeat_ids_in_csv_is_benign` — `--ids L1,L1,L1` with the
      same target; assert exit 0, `updated` array has three
      identical entries, the row in the DB ends in the target state.
  - _Requirements: R-LD-3.1, R-LD-3.2, R-LD-3.3, R-LD-3.4, R-LD-3.5,
    R-LD-3.6, R-LD-3.7_

- [ ] 6. Add the round-trip and due-after-leveldown example tests
  - Append to `test_learning_leveldown.py`:
    - `test_levelup_after_leveldown_increments_from_target` — seed
      row at `level = 17`. Pin epoch `E1`, call `leveldown --to-level
      10`. Pin epoch `E2 > E1`, call `levelup --ids L`. Assert row
      ends at `level = 11`, `last_level_up_at == E2`, `graduated ==
      0`. (Mirrors P-LD-5.)
    - `test_due_after_leveldown_at_offset_zero_excludes_row` — seed
      row at `level = 17`. Pin epoch `E`, call `leveldown --to-level
      10`. Run `learning.py due --offset 0` immediately after at the
      same pinned epoch and assert the row is NOT in the results.
      (`level_up_path[10] == 7` days, so offset 0 is far below the
      threshold.)
    - `test_due_after_leveldown_at_wait_offset_includes_row` — same
      seed; run `due --offset (level_up_path[10] * 86400)` at the
      same pinned epoch and assert the row IS in the results
      (boundary `=` is due per parent Due_SQL_Condition).
    - `test_due_after_leveldown_to_zero_at_300s_includes_row` — seed
      row at `level = 5`. Pin `E`, call `leveldown --to-level 0`. Run
      `due --offset 300` at `E` and assert the row IS in the results
      (level-0 5-minute clause).
  - _Requirements: R-LD-3.1, R-LD-4.1, R-LD-4.2_

- [ ] 7. Checkpoint — ensure tasks 1–6 tests pass
  - Run `pytest tests/integration/test_learning_leveldown.py -x`. All
    tests from tasks 1, 3, 4, 5, 6 should be green.
  - Run `pytest tests/integration/test_learning.py -x` to confirm no
    existing `learning.py` subcommand regressed (R-LD-1.2).
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Add property-based integration tests for P-LD-1..P-LD-6
  - Create
    `tests/integration/property/test_learning_leveldown_property.py`.
    Use `random.Random(seed)` with a fixed seed derived from
    `BASE_SEED` in `tests/integration/property/_helpers.py` (follow
    the local convention: `SEED = BASE_SEED + <distinct int>`), and
    `ITERATIONS` from the same module. No `hypothesis` (parent R18).
  - Add a small module-level helper `_build_random_learning_set(rng,
    tmp_app_root, ...)` that seeds 3–10 artists, 5–25 songs, and
    5–40 learning rows with random `level` (uniform over `[0,
    MAX_LEVEL]`), random `graduated` (~10% of rows), random
    `last_level_up_at` and `updated_at`, and a few duplicate
    `(song_id, graduated=0)` rows to exercise the
    `duplicate_active_learning` glitch path. Returns the seeded
    learning ids and their column values for DB-side truth checks.
  - Use `pinned_call` (not `call_script`) so `JANKENOBOE_TEST_NOW`
    is pinned per iteration.

  - [ ]* 8.1 Write property test for Forget_Reset Touches Exactly The Three Columns
    - **Property P-LD-1: Forget_Reset Touches Exactly The Three
      Columns**
    - For each iteration: pick a random active row `R`, pick a
      target `T` strictly below `R.level`, run `leveldown` at
      pinned epoch `E`, then read the row from `temp_conn` and
      assert `level == T`, `last_level_up_at == E`, `updated_at ==
      E`, every other column is byte-identical to the pre-call
      value, and every other learning row plus every row in
      `song`, `artist`, `show`, `play_history`, `rel_show_song`
      is byte-identical to the pre-call snapshot.
    - **Validates: R-LD-3.1, R-LD-3.6, R-LD-3.7**

  - [ ]* 8.2 Write property test for Strictly_Below_Rule Rejects Equal Or Greater
    - **Property P-LD-2: Strictly_Below_Rule Rejects Equal Or
      Greater**
    - For each iteration: pick a random active row `R`, pick a
      target `T` with `R.level <= T <= MAX_LEVEL`, run
      `leveldown`, assert exit 1 with `code == "INVALID_INPUT"`,
      assert the DB is byte-identical pre/post, assert
      `details.offenders` contains an entry with `id == R.id`,
      `level == R.level`, `display_level == R.level + 1`, and
      `details.to_level == T`.
    - **Validates: R-LD-2.1 (step 1.vi), R-LD-2.4, R-LD-3.7**

  - [ ]* 8.3 Write property test for Graduated Rows Are Rejected, Untouched
    - **Property P-LD-3: Graduated Rows Are Rejected, Untouched**
    - For each iteration: seed at least one graduated row `R`,
      pick any valid `T` in `[0, MAX_LEVEL]`, run `leveldown
      --ids R.id --to-level T`, assert exit 1 with `code ==
      "ALREADY_GRADUATED"`, assert the DB is byte-identical
      pre/post, assert `details.ids` contains `R.id`.
    - **Validates: R-LD-2.1 (step 1.v), R-LD-2.3, R-LD-3.7**

  - [ ]* 8.4 Write property test for Batch All-Or-Nothing
    - **Property P-LD-4: Batch All-Or-Nothing**
    - For each iteration: build a mixed batch with at least one
      passing id and at least one failing id (failure mode
      randomly chosen from missing / graduated / below-rule),
      pick a `T`, run `leveldown`, assert exit 1, assert the DB
      is byte-identical pre/post (no partial writes on the
      passing ids), assert the envelope's `code` matches the
      ordering rule (NOT_FOUND beats ALREADY_GRADUATED beats
      below-rule). Iterate over the three failure modes
      explicitly across the test (each mode appears at least
      twice over the iterations).
    - **Validates: R-LD-2.1 (ordering), R-LD-2.6, R-LD-2.7,
      R-LD-1.5**

  - [ ]* 8.5 Write property test for Leveldown Then Levelup Round-Trip
    - **Property P-LD-5: Leveldown Then Levelup Round-Trip**
    - For each iteration: pick a random active row `R` with
      `R.level >= 2`, set `T = R.level - 2`, pin epoch `E1`, run
      `leveldown --ids R.id --to-level T`, pin epoch `E2 > E1`,
      run `levelup --ids R.id`. Read `R` from `temp_conn` and
      assert `R.level == T + 1`, `R.last_level_up_at == E2`,
      `R.graduated == 0`.
    - **Validates: R-LD-3.1, parent R6.5 / R6.6 compatibility**

  - [ ]* 8.6 Write property test for Due-After-Leveldown Tracks The Lower Wait
    - **Property P-LD-6: Due-After-Leveldown Tracks The Lower
      Wait**
    - For each iteration: pick a random active row `R` with
      `R.level >= 1`, pick `T` in `[0, R.level - 1]`, pin epoch
      `E`, run `leveldown --ids R.id --to-level T`. Run
      `learning.py due --offset 0` at pinned epoch `E`; assert
      `R.id` is NOT in the results. Then compute `wait_offset =
      300` if `T == 0` else `level_up_path[T] * 86400`, run `due
      --offset <wait_offset>` at pinned epoch `E`, and assert
      `R.id` IS in the results. Read `R.level_up_path` JSON via
      `temp_conn` and assert it is byte-identical to the seeded
      value.
    - **Validates: R-LD-3.1, R-LD-4.1, R-LD-4.2**

- [ ] 9. Checkpoint — ensure property tests pass
  - Run `pytest
    tests/integration/property/test_learning_leveldown_property.py
    -x`.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Update `skills/reviewing-songs/SKILL.md` per R-LD-5
  - Under step 4 ("For each song the user reviews:"), add one new
    sub-bullet for the "Forgot it" outcome that names
    `learning.py leveldown --ids L1,L2,... --to-level N`, the
    strictly-below rule, and the fact that `last_level_up_at` is
    reset to `now_epoch` so the next review is scheduled from the
    forget event. Detail level matches the existing `levelup` and
    `graduate` sub-bullets.
  - Under "Notes", add one line that mirrors the existing
    `ALREADY_GRADUATED` advice: if `learning.py leveldown` returns
    `code = "ALREADY_GRADUATED"`, drop that id and (when the user
    wants the song re-engaged) call `learning.py batch` instead,
    which inserts a fresh row at `Re_Learn_Level` per parent R6.3.
  - Update the frontmatter `description` to include "forget" or
    "level down" in its trigger list, alongside the existing
    "review", "level up", "graduate" triggers.
  - Do not remove or rewrite any existing bullet or paragraph
    (R-LD-5.3).
  - _Requirements: R-LD-5.1, R-LD-5.2, R-LD-5.3, R-LD-5.4_

  - [ ] 10.1 Add a content-assertion test for the SKILL.md update
    - Add `test_skill_md_lists_leveldown` to
      `tests/integration/test_learning_leveldown.py`.
    - Read `skills/reviewing-songs/SKILL.md` and assert it contains
      the literal strings `leveldown`, `--ids`, `--to-level`, and
      `ALREADY_GRADUATED` in the same logical region as `levelup` /
      `graduate`. Assert the existing bullets for `levelup`,
      `graduate`, `due`, `batch`, and `learning-detail` are still
      present.
    - _Requirements: R-LD-5.1, R-LD-5.2, R-LD-5.3_

- [ ] 11. Final checkpoint — full test suite and cleanup
  - Run the complete test suite (`pytest` from repo root, or
    `tests/run.sh` if that's the project's convention).
  - Confirm every `leveldown`-related example and property test
    passes and no existing test regressed.
  - Delete any scratch files or commented-out debug code introduced
    in earlier tasks. The final diff touches only
    `scripts/learning.py`,
    `tests/integration/test_learning_leveldown.py`,
    `tests/integration/property/test_learning_leveldown_property.py`,
    and `skills/reviewing-songs/SKILL.md`.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster
  MVP. All six property tests (8.1..8.6) are marked optional per the
  "test sub-tasks may be optional" convention, but skipping them
  leaves P-LD-1..P-LD-6 unverified — prefer to implement them.
- Core implementation tasks (2–6, 10) are NOT marked optional.
- Each task references specific sub-requirements (e.g. `R-LD-3.4`)
  for traceability rather than just the parent user story.
- Every property sub-task names its property and lists the exact
  requirements clauses it validates, matching the design's
  "Correctness Properties" section.
- Checkpoints (7, 9, 11) gate forward progress so a failing layer
  is caught before the next one lands on top of it.
- The skill-doc update (task 10) is a hard prerequisite for "done"
  per R-LD-5.4 — don't ship the code without it.
