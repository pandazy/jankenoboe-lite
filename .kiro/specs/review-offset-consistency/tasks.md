# Implementation Plan

This task list translates `design.md` into an executable plan for adding
`--offset N` to `scripts/review.py song-review` so it matches the
existing surface on `scripts/learning.py due`. The order follows the
bugfix workflow's Task-1-first-fails pattern: one exploration test up
front that MUST fail on unfixed code (the failure is the evidence the
bug exists), then the fix applied in one coherent pass to
`scripts/review.py` (argparse flag, SQL binding, payload signature,
envelope key — all four are tightly coupled and splitting them would
leave the repo broken between sub-tasks), then the exploration test
re-run to confirm the fix, then the fix-checking parity test that pins
`review.py --offset N`'s row set to `learning.py due --offset N`'s row
set, then the envelope key-set preservation test, then the final gate,
then the single commit.

**Out of scope, do not touch**: `scripts/learning.py` (R3.6),
`scripts/_common.py` (R3.10), `scripts/review_template.html` (R3.2),
and any skill document under `skills/` including
`skills/reviewing-songs/SKILL.md`. The `--offset` flag on
`review.py song-review` is discoverable via `review.py song-review
--help` and low-enough traffic that the existing skill prose stays
as-is; this spec adds no skill-docs assertion tests.

Ships as v0.1.3 via the existing release pipeline. No new CLI flags
beyond `--offset`, no new error codes, no schema change, no template
change.

## Bug condition exploration test (fails on unfixed code)

- [x] 1. Write bug condition exploration test — `song-review --offset` accepted
  - **Property 1: Bug Condition** — `review.py song-review` rejects `--offset N` on unfixed code
  - **CRITICAL**: This test MUST FAIL on unfixed code — the failure is the evidence that the bug exists.
  - **DO NOT attempt to fix the test or the code when it fails.**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation.
  - **GOAL**: Surface the concrete counterexample (argparse exit 2, "unrecognized arguments: --offset 86400") that demonstrates the bug.
  - **Scoped PBT Approach**: The bug is deterministic — argparse rejection is a single failure mode that reproduces on every invocation with any integer value of N ≠ 0. Scope the property to the concrete failing case `--offset 86400` (the "one day ahead" example from bugfix.md 1.3) for reproducibility. A single integration test is sufficient; `learning.py due --offset` semantics are already property-verified by `tests/integration/property/test_due_property.py`, so transitive coverage applies once the two scripts bind the same `_DUE_SQL` shape post-fix.
  - Add a new integration test `test_song_review_accepts_offset_flag` to `tests/integration/test_review.py` (style matches the existing `test_no_args_prints_help_and_exits_zero` and `test_writes_to_timestamped_path_under_output` in that file).
  - Use the `tmp_app_root` fixture with zero rows seeded — this test is about argparse surface, not row selection; an empty DB is sufficient.
  - Run `call_script("review.py", "song-review", "--offset", "86400", cwd=tmp_app_root)`.
  - Assert `rc == 0` and `err` is empty (no error envelope on stderr).
  - Assert `json.loads(out)` parses, carries `path` (str), `due_count == 0`, and `offset == 86400` (envelope echo per R2.4).
  - **EXPECTED OUTCOME ON UNFIXED CODE**: `rc == 2`, stderr contains argparse's standard unrecognized-arguments message (phrasing: `unrecognized arguments: --offset 86400`), the `rc == 0` assertion fails. This confirms the bug: `_build_parser()` adds the `song-review` subparser without calling `add_argument("--offset", ...)`, so argparse rejects the flag.
  - **EXPECTED OUTCOME ON FIXED CODE**: All assertions pass (rc == 0, stdout envelope parses, `offset == 86400`).
  - Document the exact counterexample (argparse exit 2, `unrecognized arguments: --offset 86400`) in the task's done-when notes.
  - _Requirements: R1.1, R2.1, R2.4, R2.6_

## Fix

Live code in `scripts/review.py`. All four changes land together in the
same pass — argparse flag, SQL binding, payload signature, envelope
key — because they are tightly coupled and splitting them would leave
intermediate sub-task states where the repo does not build green (flag
without binding → SQL error; binding without flag → argparse rejects;
signature change without caller update → TypeError; etc.). No other
file in the repo is touched.

- [x] 2. Apply the four-change fix in `scripts/review.py`
  - Parent task. All four changes land in `scripts/review.py` in one commit-equivalent pass so the repo is never in a state where `_build_parser()`, `_DUE_SQL`, `_build_payload`, and `_cmd_song_review` disagree.
  - **Files touched**: `scripts/review.py` only.
  - **Files NOT touched** (explicit call-out per spec narrative): `scripts/learning.py` (R3.6), `scripts/_common.py` (R3.10), `scripts/review_template.html` (R3.2), and every file under `skills/` — the `--offset` flag is discoverable via `review.py song-review --help` and does not require a skill-prose update.

  - [x] 2.1 Add `--offset` to the `song-review` subparser
    - Change `_build_parser()` per design change #1. Capture the subparser returned by `sub.add_parser("song-review", ...)` into a local `sr`, then call `sr.add_argument("--offset", type=int, default=0, help="Shift the 'now' comparison forward by N seconds (default 0).")`.
    - Argparse kwargs mirror `learning.py due`'s `add_argument("--offset", ...)` byte-for-byte (same `type=int`, same `default=0`, same phrasing).
    - `type=int, default=0` gives R2.6 for free — a non-integer N triggers argparse's standard exit-2 usage error with no new error code.
    - _Bug_Condition: isBugCondition(invocation) where invocation.desiredOffsetSeconds ≠ 0 — surface layer_
    - _Expected_Behavior: Property 1 from design — argparse accepts any integer N and stores it on `args.offset`_
    - _Preservation: Property 2 from design — zero-offset and no-flag invocations still bind `args.offset = 0`_
    - _Requirements: R2.1, R2.6_

  - [x] 2.2 Thread `+ :offset` through `_DUE_SQL`
    - Rewrite the three `CAST(strftime('%s', 'now') AS INTEGER)` sites in `review.py`'s `_DUE_SQL` per design change #2. Each becomes `(CAST(strftime('%s', 'now') AS INTEGER) + :offset)` with parenthesisation matching `learning.py`'s copy verbatim.
    - The three sites are the level-0-with-`last_level_up_at>0` branch, the level-0-with-`last_level_up_at=0` branch, and the level-`>0` branch (R2.2).
    - Final SQL per design change #2: columns, joins, and ORDER BY unchanged from v0.1.2; only the three predicate clauses substituted. Review.py retains its extra `artist` join and its `name_context` / `artist_*` / `wait_days` columns that `learning.py` doesn't need (R3.3, R3.4, R3.11).
    - The three substituted predicates match the three predicates in `learning.py`'s `_DUE_SQL` byte-for-byte, so post-fix the two scripts select the same row set under the same bind (R2.3, R2.5).
    - _Bug_Condition: isBugCondition(invocation) where invocation.desiredOffsetSeconds ≠ 0 — predicate layer_
    - _Expected_Behavior: Property 1 from design — the shifted predicate selects the same rows `learning.py due --offset N` selects_
    - _Preservation: Property 2 from design — `:offset = 0` collapses to v0.1.2's predicate byte-identically_
    - _Requirements: R2.2, R2.3, R2.5, R3.11_

  - [x] 2.3 Change `_build_payload` signature to accept and bind `offset`
    - Change the signature from `_build_payload(conn: sqlite3.Connection) -> dict[str, Any]` to `_build_payload(conn: sqlite3.Connection, offset: int) -> dict[str, Any]` per design change #3.
    - Change the SQL execution site from `conn.execute(_DUE_SQL).fetchall()` to `conn.execute(_DUE_SQL, {"offset": offset}).fetchall()`, mirroring `learning.py`'s `conn.execute(_DUE_SQL, {"offset": int(args.offset)})`.
    - Do NOT add `offset` to `payload["generated_at"]` or to any other payload field — the filename uses `_common.now_epoch()` for the `<EPOCH>` component, `generated_at` stamps when the file was written, not the logical "as of" time (R3.8). Only the Due_SQL_Condition and the Success_Envelope echo see the offset.
    - The Due_Data_Payload schema (R3.3) is unchanged — same fields, same types, same semantics on every per-song and per-show field.
    - _Bug_Condition: isBugCondition(invocation) where invocation.desiredOffsetSeconds ≠ 0 — bind layer_
    - _Expected_Behavior: Property 1 from design — the bind dict reaches the three substituted predicates_
    - _Preservation: Property 2 from design — Due_Data_Payload schema unchanged (R3.3), filename scheme unchanged (R3.8)_
    - _Requirements: R2.2, R3.3, R3.8_

  - [x] 2.4 Update `_cmd_song_review` to extract `args.offset` and surface it in the Success_Envelope
    - Rename the second parameter from `_args` to `args` (the handler now reads `args.offset`). Per design change #4.
    - Call `_build_payload(conn, int(args.offset))`.
    - Add `"offset": int(args.offset)` to the envelope dict as its third key, preserving the existing convention — `path` first, `due_count` second, new `offset` last. The `_common.success(...)` call becomes:
      ```python
      _common.success({
          "path": str(target),
          "due_count": payload["due_count"],
          "offset": int(args.offset),
      })
      ```
    - No other code in `_cmd_song_review` changes — template read, `_render_page` call, `output/` mkdir, and the `review_<EPOCH>.html` target path all stay byte-identical (R3.1, R3.2, R3.5, R3.7, R3.8).
    - _Bug_Condition: isBugCondition(invocation) where invocation.desiredOffsetSeconds ≠ 0 — caller + envelope layer_
    - _Expected_Behavior: Property 1 from design — envelope echoes N back as int (R2.4)_
    - _Preservation: Property 2 from design — `path` / `due_count` fields carry v0.1.2 values unchanged (R3.7); envelope gains exactly one new key `offset`_
    - _Requirements: R2.1, R2.4, R3.7_

## Verification

- [x] 3. Verify the Task 1 exploration test now passes
  - **Property 1: Expected Behavior** — `review.py song-review --offset 86400` exits 0 and echoes `offset: 86400`
  - **IMPORTANT**: Re-run the SAME test from Task 1 — do NOT write a new test. The Task 1 test encodes the expected behavior.
  - Run `pytest tests/integration/test_review.py::test_song_review_accepts_offset_flag` in isolation.
  - **EXPECTED OUTCOME**: Test PASSES — rc == 0, no stderr envelope, stdout JSON carries `{"path": str, "due_count": 0, "offset": 86400}`. This confirms the bug is fixed.
  - If the test still fails, do not proceed to Task 4 — diagnose the root cause and revisit Task 2 before continuing.
  - _Requirements: R2.1, R2.4, R2.6_

## Fix-checking parity test

- [x] 4. Add the `learning.py due` / `review.py song-review` parity test
  - **Property 1: Fix Checking — Offset parity with `learning.py due`** — for a non-zero offset, the `learning_id` set in `review.py`'s payload equals the `id` set in `learning.py due`'s `results`.
  - Add a new integration test `test_song_review_offset_matches_learning_due` to `tests/integration/test_review.py`. Use the `_sqlite_now`, `_run_review_pinned`, and `_load_data_block` helpers already defined at the top of the file.
  - Per design's "Fix Checking" section: seed one level-0 learning row whose `last_level_up_at = sqlite_now - 200` (100s shy of the 300s level-0 threshold). At `--offset 0` the row is not due; at `--offset 200` it crosses the boundary into due.
  - Run both scripts against the same DB + wall clock, pinning the clock through `pinned_call` for review.py and passing `--offset 200` to `call_script` for learning.py:
    - `learning_rc, learning_out, _err = call_script("learning.py", "due", "--offset", "200", cwd=tmp_app_root)`; assert `learning_rc == 0`; parse `json.loads(learning_out)["results"]`; collect `{r["id"] for r in results}`.
    - `review_rc, review_out, _err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)` — but with the extra `--offset 200` arg. Since `_run_review_pinned` doesn't currently accept extra args, either add an inline `pinned_call("review.py", "song-review", "--offset", "200", cwd=tmp_app_root, now=1_700_000_000)` call in the test body, or extend `_run_review_pinned` to forward varargs. Inline call is lighter.
    - Extract the payload via `_load_data_block(expected.read_text("utf-8"))`; collect `{s["learning_id"] for s in payload["due_songs"]}`.
  - Assert:
    - Both scripts exit 0.
    - The seeded learning id appears in both sets.
    - `{s["learning_id"] for s in payload["due_songs"]} == {r["id"] for r in learning_results}`.
    - `review_out["offset"] == 200` (envelope echo per R2.4).
    - `review_out["path"]` is a string and `review_out["due_count"]` is an integer (R3.7).
  - Set equality (not sequence equality) is the assertion per design — both scripts order by `level DESC, id ASC` but the fix-checking property is row-set equality, not sequence equality.
  - **EXPECTED OUTCOME ON FIXED CODE**: Test PASSES. On unfixed code this test is unreachable because Task 1 blocks argparse before the SQL runs; post-Task-2 it becomes the binding evidence that review.py and learning.py agree on row selection across the offset axis.
  - _Bug_Condition: isBugCondition(invocation) where invocation.desiredOffsetSeconds = 200_
  - _Expected_Behavior: Property 1 from design — set equality of learning_id vs id under the same bind_
  - _Preservation: None — this is a fix-checking test, not a preservation test_
  - _Requirements: R2.2, R2.3, R2.4, R2.5_

## Envelope key-set preservation test

- [x] 5. Add the envelope key-set preservation test
  - **Property 2: Preservation** — Zero-offset envelope is exactly `{path, due_count, offset}` with `offset == 0`
  - **IMPORTANT**: Follow observation-first methodology — the existing zero-offset invocation is v0.1.2's behaviour; we observe it and pin the new shape (v0.1.2 keys plus exactly one new `offset` key with value 0).
  - Add a new integration test `test_song_review_envelope_key_set_with_no_offset` to `tests/integration/test_review.py`. Style matches the existing `test_writes_to_timestamped_path_under_output`.
  - Use the `tmp_app_root` fixture with zero rows seeded — the key-set invariant doesn't depend on row count.
  - Invoke `review.py song-review` with **no** `--offset` flag via `_run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)`.
  - Assert:
    - `rc == 0`.
    - `set(out.keys()) == {"path", "due_count", "offset"}`.
    - `out["offset"] == 0`.
    - `out["path"] == str(expected)` (absolute output path string, R3.7).
    - `out["due_count"] == 0` (integer count, R3.7).
  - This one test codifies the envelope contract from R3.7 + R2.4: the envelope gains exactly one new key, named `offset`, with integer value 0 when the flag is absent. Combined with the existing per-key assertions already in the file (`test_writes_to_timestamped_path_under_output` asserts `out["path"]` and `out["due_count"]`), preservation of the full envelope surface is covered.
  - **EXPECTED OUTCOME ON UNFIXED CODE**: This test fails on unfixed code — the envelope would lack the `offset` key entirely and the `set(out.keys()) == {"path", "due_count", "offset"}` assertion fires. Running it pre-fix is not required; the Task 1 exploration test is already the canonical pre-fix evidence. Post-fix the assertion passes and becomes the preservation gate.
  - **EXPECTED OUTCOME ON FIXED CODE**: Test PASSES — envelope is exactly `{path, due_count, offset}` with `offset == 0`.
  - Every other test in `tests/integration/test_review.py` (empty state, happy path, display level, HTML escape, filter rules, output path, INTERNAL_ERROR paths, no-write-to-DB) stays byte-identical and continues to pass unchanged — those tests assert individual envelope keys (`out["path"]`, `out["due_count"]`) which remain correct post-fix. No modifications to existing tests are required. This is the main structural evidence for R3.1, R3.2, R3.3, R3.4, R3.5.
  - _Bug_Condition: isBugCondition(invocation) where invocation.desiredOffsetSeconds = 0 (i.e. ¬C) — this is the preservation codomain_
  - _Expected_Behavior: Property 2 from design — envelope gains exactly one new key `offset` with value 0_
  - _Preservation: Property 2 from design — `path` / `due_count` fields carry v0.1.2 values unchanged_
  - _Requirements: R3.1, R3.7_

## Final gate

- [x] 6. Checkpoint — run `make check`, confirm coverage ≥ 90%, full suite green
  - Run `make check` (lint + typecheck + test). Expect all three to pass.
  - Confirm coverage stays ≥ 90% — `./tests/run.sh` enforces this automatically via `.coveragerc`; fail the task if coverage drops. The four changes in `scripts/review.py` are exercised by the new Task 1, Task 4, and Task 5 tests plus every existing test in `tests/integration/test_review.py`, so the floor should be unaffected.
  - Re-run the Task 1 exploration test and confirm it still passes:
    - `pytest tests/integration/test_review.py::test_song_review_accepts_offset_flag` — argparse accepts `--offset 86400`, envelope echoes.
  - Re-run the Task 4 parity test and confirm it passes:
    - `pytest tests/integration/test_review.py::test_song_review_offset_matches_learning_due` — `learning_id` set equals `id` set under `--offset 200` on a boundary-seeded row.
  - Re-run the Task 5 preservation test and confirm it passes:
    - `pytest tests/integration/test_review.py::test_song_review_envelope_key_set_with_no_offset` — no-flag envelope is exactly `{path, due_count, offset}` with `offset == 0`.
  - Re-run the full existing `tests/integration/test_review.py` suite and confirm every pre-existing test still passes byte-identically:
    - `pytest tests/integration/test_review.py` — all of `test_writes_to_timestamped_path_under_output`, `test_output_directory_created_when_missing`, `test_review_script_does_not_write_elsewhere`, `test_two_runs_at_different_times_produce_two_files`, `test_no_due_rows_still_writes_valid_html`, `test_happy_path_renders_due_song`, `test_renders_display_level_not_stored_level`, `test_html_injection_in_song_name_is_escaped`, `test_media_url_quotes_are_escaped`, `test_soft_deleted_song_does_not_appear`, `test_graduated_row_does_not_appear`, `test_soft_deleted_show_not_listed`, `test_missing_template_raises_internal_error`, `test_missing_marker_raises_internal_error`, `test_no_args_prints_help_and_exits_zero`, `test_help_flag_exits_zero`, `test_review_does_not_modify_db` still pass unchanged. This is the main structural evidence for R3.1 (zero-offset HTML byte-identity), R3.2 (template untouched), R3.3 (payload schema unchanged), R3.4 (same row set on zero offset), R3.5 (`_render_page` / `_escape_json_for_html` byte-identical).
  - Re-run the broader preservation sweep and confirm no regressions:
    - `pytest tests/integration/test_due.py` — `learning.py due` surface unchanged (R3.6).
    - `pytest tests/integration/property/test_due_property.py` — property coverage of `learning.py due` offset semantics unchanged (R3.6).
    - `pytest tests/integration/test_error_codes.py` — error-envelope surface unchanged.
  - If any test fails or coverage drops, diagnose the root cause before proceeding; ask the user if questions arise.
  - _Requirements: All R2.* and R3.* from bugfix.md_

## Commit

- [x] 7. Commit the fix as a single `fix(review)` commit
  - **DO NOT actually commit from this task file** — this entry is instructional for when the implementation phase lands.
  - Follow Amazon Conventional-Commits (`fix:`) per the `amazon-builder/amazon-builder-git.md` user rule.
  - Suggested commit message:
    - Subject (≤ 50 chars): `fix(review): add --offset to song-review for parity with learning.py due`
    - Body: explain that `review.py song-review` carried a near-copy of `learning.py due`'s `_DUE_SQL` but omitted the `+ :offset` terms in all three time-comparison branches and exposed no `--offset` flag, making it impossible to render a shifted-clock HTML review page that agents could already count via `learning.py due --offset N`; note that the fix adds `--offset N` (integer seconds, default 0) to the `song-review` subparser with argparse kwargs identical to `learning.py due`, threads `+ :offset` through the three `CAST(strftime('%s','now') AS INTEGER)` sites, changes `_build_payload(conn)` to `_build_payload(conn, offset)` binding `{"offset": offset}`, and surfaces `offset: int(args.offset)` as the third key in the Success_Envelope alongside the existing `path` and `due_count`; note that zero-offset and no-flag invocations are byte-identical to v0.1.2 on rendered HTML and on the `path` / `due_count` envelope fields (R3.1, R3.7), the envelope gains exactly one new key (`offset`, integer, 0 when the flag is absent), and the `_DUE_SQL` duplication between the two scripts is deliberately preserved (R3.9); note v0.1.3 ships via the existing release pipeline with no CLI / error-code / schema / template change.
  - Scope: all files touched in one logical change — `scripts/review.py`, `tests/integration/test_review.py`.
  - Keep the commit self-contained: code fix and the three new tests (Task 1 exploration, Task 4 parity, Task 5 envelope preservation) land together so commit history never contains a persistently-failing test.
  - Rollout per design: ships as v0.1.3 when the user tags and pushes. The existing release pipeline (`release.md`, `.github/workflows/release.yml`) produces a v0.1.3 zip unchanged.
  - Do NOT `git push`.
  - _Requirements: n/a (instructional task, no validation)_
