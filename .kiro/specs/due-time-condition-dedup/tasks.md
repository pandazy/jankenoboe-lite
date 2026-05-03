# Implementation Plan

This task list translates `design.md` into an executable plan for
deduplicating the three-branch due-time predicate that currently lives
as literal SQL text in both `scripts/learning.py._DUE_SQL` and
`scripts/review.py._DUE_SQL`. The order follows the bugfix workflow's
Task-1-first-fails pattern: one static-source-tree exploration test up
front that MUST fail on unfixed code (the failure is the evidence the
bug exists), then the fix applied in one coherent three-file pass
(constant added to `scripts/_common.py`, both callers' `_DUE_SQL`
converted to f-strings referencing it), then the exploration test
re-run to confirm the fix, then a small importability smoke test as an
extra structural gate, then preservation via the existing test suite
(no new preservation test is written — the suite IS the oracle), then
the final gate, then the single commit.

**Note on bug-condition scope**: The bug condition in this spec is a
**static source-tree property**, not a runtime property. It asks
"does the three-branch due-time predicate text appear in more than one
file under `scripts/**/*.py`?" The fix is structural — no observable
behavior changes between v0.1.3 and the fixed codebase. The existing
integration suite is therefore the preservation oracle, and the
exploration test (Task 1) is a static file-count test living under
`tests/unit/`, not an integration test.

**Out of scope, do not touch**:
- `tests/integration/property/test_due_property.py` — its inline
  `DUE_SQL` literal is an **independent textual oracle** for the
  predicate. Its value comes precisely from its independence; keeping
  it as a standalone third copy preserves the "two witnesses" quality
  of the property-based coverage. Per design's "Out of scope for this
  refactor" section, do NOT rewire it to consume
  `_common.DUE_TIME_CONDITION_SQL`. Do NOT edit a single byte of it.
- The `a.status = 0` filter asymmetry — `review.py._DUE_SQL` filters
  soft-deleted artists; `learning.py._DUE_SQL` does not. That
  asymmetry may be a separate bug but changing it would alter
  observable behavior and is a separate scope.
- `skills/` — user has explicitly stated skill documents do not get
  assertion tests. The extracted predicate is internal structural
  refactoring; no skill prose references it today and none will be
  added.
- `scripts/review_template.html`, every other script under `scripts/`
  besides the three named in Task 2, `release.md`,
  `.github/workflows/release.yml`, `Makefile`, `.coveragerc`,
  `pyproject.toml` — none are touched.

Ships as v0.1.4 via the existing release pipeline. No new CLI flags,
no new error codes, no schema change, no template change, no config
or CI change. The user tags and pushes; the subagent does not commit,
tag, or push.

## Bug condition exploration test (fails on unfixed code)

- [x] 1. Write bug condition exploration test — predicate text duplicated across `scripts/`
  - **Property 1: Bug Condition** — the three-branch due-time predicate appears in more than one source file under `scripts/**/*.py` on unfixed code
  - **CRITICAL**: This test MUST FAIL on unfixed code — the failure is the evidence that the bug exists.
  - **DO NOT attempt to fix the test or the code when it fails.**
  - **NOTE**: This test encodes the expected post-fix state — it will validate the fix when it passes after implementation.
  - **GOAL**: Surface the concrete counterexample (two files contain the predicate: `scripts/learning.py` and `scripts/review.py`) that demonstrates the bug.
  - **Scoped PBT Approach**: The bug is deterministic — the predicate either exists in a given file or doesn't. The counterexample is the pair of file paths `scripts/learning.py` and `scripts/review.py`. Scope the property to the concrete static state of the source tree for reproducibility. A single unit test is sufficient; there is no runtime input domain to quantify over.
  - **Location**: Add a new test file `tests/unit/test_due_time_condition_single_source.py`. This lives in `tests/unit/` (NOT `tests/integration/`) because it reads `.py` files from the `scripts/` directory and counts predicate occurrences — it does not exercise the DB, CLI, or any subprocess. The test has no fixtures and does not import any runtime script.
  - **Fingerprint**: Pick a whitespace-insensitive three-substring fingerprint that robustly identifies "the three-branch due-time predicate" without tying to exact indentation:
    - `l.last_level_up_at + 300` (branch A threshold)
    - `l.updated_at + 300` (branch B threshold)
    - `json_extract(l.level_up_path` (branch C `wait_days` expression)
    - A file matches the predicate iff it contains **all three** substrings, measured against the file's text after collapsing runs of whitespace to single spaces (so formatting differences between the two current copies and the future extracted constant don't defeat the check).
  - **Implementation outline** (keep the test self-contained — no imports from `scripts/`):
    ```python
    import pathlib
    import re

    SCRIPTS_DIR = pathlib.Path(__file__).parent.parent.parent / "scripts"
    FINGERPRINTS = (
        "l.last_level_up_at + 300",
        "l.updated_at + 300",
        "json_extract(l.level_up_path",
    )

    def _matches(path: pathlib.Path) -> bool:
        text = path.read_text(encoding="utf-8")
        collapsed = re.sub(r"\s+", " ", text)
        return all(fp in collapsed for fp in FINGERPRINTS)

    def test_due_time_predicate_lives_in_exactly_one_file() -> None:
        matches = sorted(p for p in SCRIPTS_DIR.rglob("*.py") if _matches(p))
        assert len(matches) == 1, (
            "expected predicate in exactly one file, "
            f"found {len(matches)}: {[str(p.relative_to(SCRIPTS_DIR.parent)) for p in matches]}"
        )
        assert matches[0].name == "_common.py", (
            f"expected single match in scripts/_common.py, got {matches[0]}"
        )
    ```
  - **EXPECTED OUTCOME ON UNFIXED CODE**: Test FAILS. `len(matches) == 2` with the list `['scripts/learning.py', 'scripts/review.py']`. This confirms the bug: the predicate text is duplicated across two files. Do NOT modify the test to make it pass — the failure is the point.
  - **EXPECTED OUTCOME ON FIXED CODE**: Test PASSES. `len(matches) == 1` and the single match is `scripts/_common.py`.
  - Document the exact counterexample (two files: `scripts/learning.py` and `scripts/review.py`) in the task's done-when notes.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2_

## Fix

Live code changes land in three files in one coherent pass. The three
sub-tasks are numbered 2.1 / 2.2 / 2.3 for book-keeping but commit
together so the repo is never in a half-fixed state (e.g. constant
added but neither caller interpolates, or one caller converted to
f-string while the other still carries the literal). No other file in
the repo is touched.

- [x] 2. Extract `DUE_TIME_CONDITION_SQL` and compose both `_DUE_SQL` strings via f-string
  - Parent task. All three sub-tasks land together in `scripts/_common.py`, `scripts/learning.py`, and `scripts/review.py` so the repo is never in a state where the three files disagree.
  - **Files touched**: `scripts/_common.py`, `scripts/learning.py`, `scripts/review.py`.
  - **Files NOT touched** (explicit call-out per the "Out of scope" block above): `tests/integration/property/test_due_property.py` (independent oracle), `scripts/review_template.html`, any other `scripts/*.py` file, and every file under `skills/`.
  - Both callers already have `from scripts import _common` at module top — **no new imports are added** to either script. The f-string expression is `{_common.DUE_TIME_CONDITION_SQL}`.

  - [x] 2.1 Add `DUE_TIME_CONDITION_SQL` to `scripts/_common.py`
    - Place the new module-level string constant near the existing SQL/schema constants — specifically in the region that already holds `EXPECTED_SCHEMA`, `MAX_LEVEL`, `DEFAULT_LEVEL_UP_PATH`, and `RE_LEARN_LEVEL`. A natural home is a small "SQL fragments" section either just above `MAX_LEVEL` or directly below `RE_LEARN_LEVEL` — pick whichever reads best; both are adjacent to the constants the design names.
    - Precede the constant with a leading comment block (per Decision 4) documenting:
      - **Role**: the three-branch due-time predicate — the one source of truth consumed by both `learning.py._DUE_SQL` and `review.py._DUE_SQL`.
      - **Alias contract**: callers MUST alias the `learning` table as `l`. The predicate references only `l.last_level_up_at`, `l.level`, `l.updated_at`, and `l.level_up_path`; it does not reference `s` or `a`.
      - **Bind contract**: callers MUST bind `:offset` (integer seconds) via `conn.execute(sql, {"offset": int(args.offset)})`. `:offset` is a SQLite bind parameter, NOT an interpolated string.
      - **Branches**: (A) `level = 0` and `last_level_up_at > 0` — due when `now + offset >= last_level_up_at + 300`; (B) `level = 0` and `last_level_up_at = 0` — due when `now + offset >= updated_at + 300` (never-reviewed rows fall back to `updated_at`); (C) `level > 0` — due when `level_up_path[level] * 86400 + last_level_up_at <= now + offset`.
    - The constant's value is the three-branch predicate, **outer `(...)` included**, copied verbatim from the current `_DUE_SQL` bodies modulo leading whitespace per Decision 3. Strip leading indentation from the constant — SQLite is whitespace-insensitive; the rendered `_DUE_SQL` text after interpolation does not need to be aesthetically perfect, and clean formatting in `_common.py` is what matters for readability. Final shape:
      ```python
      DUE_TIME_CONDITION_SQL = """(
          (l.last_level_up_at > 0 AND l.level = 0
           AND (CAST(strftime('%s', 'now') AS INTEGER) + :offset)
               >= (l.last_level_up_at + 300))
          OR
          (l.last_level_up_at = 0 AND l.level = 0
           AND (CAST(strftime('%s', 'now') AS INTEGER) + :offset)
               >= (l.updated_at + 300))
          OR
          (l.level > 0
           AND (json_extract(l.level_up_path, '$[' || l.level || ']') * 86400
                + l.last_level_up_at)
               <= (CAST(strftime('%s', 'now') AS INTEGER) + :offset))
      )"""
      ```
    - No new imports. The constant is a plain `str` literal — Python 3.10+ stdlib only per R1.6.
    - _Bug_Condition: isBugCondition(codebase) where countOccurrences(predicate, scripts/**/*.py) > 1 — source-of-truth layer_
    - _Expected_Behavior: Property 1 from design — the predicate text lives in exactly one file (`scripts/_common.py`) after the fix_
    - _Preservation: Property 2 from design — the constant's text (modulo whitespace) matches what both `_DUE_SQL` bodies carry on v0.1.3, so composed SQL is semantically identical_
    - _Requirements: 2.1, 2.2, 2.6_

  - [x] 2.2 Convert `scripts/learning.py._DUE_SQL` to f-string referencing `_common.DUE_TIME_CONDITION_SQL`
    - Change the `_DUE_SQL = """..."""` triple-quoted literal to an f-string: `_DUE_SQL = f"""..."""`.
    - Replace the nine lines that today spell out the three-branch predicate — from `AND (` through the closing `)` at the end of the predicate block — with a single line: `  AND {_common.DUE_TIME_CONDITION_SQL}`.
    - Leave every other line of `_DUE_SQL` **byte-identical** to v0.1.3:
      - The 9-field SELECT list (`l.id`, `l.song_id`, `s.name AS song_name`, `l.level`, `(l.level + 1) AS display_level`, the `wait_days` COALESCE/json_extract expression, `l.last_level_up_at`, `l.updated_at`, `l.graduated`).
      - The FROM/JOIN: `FROM learning l JOIN song s ON s.id = l.song_id`.
      - The non-time WHERE filters: `WHERE s.status = 0 AND l.graduated = 0` (the `a.status = 0` asymmetry is preserved by NOT filtering artists here — per design's "Unchanged Behaviors" bullet, this is intentional and out of scope).
      - The ORDER BY: `ORDER BY l.level DESC, l.id ASC`.
    - No new import lines added — `from scripts import _common  # noqa: E402` is already at module top.
    - `:offset` stays a SQLite bind parameter via the existing `conn.execute(_DUE_SQL, {"offset": int(args.offset)})` call in `_cmd_due`. The f-string only interpolates the static predicate text; it does not interpolate `:offset`.
    - _Bug_Condition: isBugCondition(codebase) — caller layer (learning.py)_
    - _Expected_Behavior: Property 1 from design — `learning.py._DUE_SQL` composes the shared constant via f-string interpolation_
    - _Preservation: Property 2 from design — `learning.py due` returns byte-identical row sets and envelopes to v0.1.3 for every DB state and `--offset` value_
    - _Requirements: 2.3, 2.5, 2.6, 3.1, 3.3, 3.5, 3.6_

  - [x] 2.3 Convert `scripts/review.py._DUE_SQL` to f-string referencing `_common.DUE_TIME_CONDITION_SQL`
    - Change the `_DUE_SQL = """..."""` triple-quoted literal to an f-string: `_DUE_SQL = f"""..."""`.
    - Replace the same nine lines — from `AND (` through the closing `)` at the end of the predicate block — with a single line: `  AND {_common.DUE_TIME_CONDITION_SQL}`.
    - Leave every other line of `_DUE_SQL` **byte-identical** to v0.1.3:
      - The 11-field SELECT list (`l.id AS learning_id`, `l.song_id AS song_id`, `s.name AS song_name`, `s.name_context AS song_name_context`, `s.artist_id AS artist_id`, `a.name AS artist_name`, `a.name_context AS artist_name_context`, `l.level AS level`, `(l.level + 1) AS display_level`, the `wait_days` COALESCE/json_extract expression aliased identically).
      - The FROM/JOIN: `FROM learning l JOIN song s ON s.id = l.song_id JOIN artist a ON a.id = s.artist_id`.
      - The non-time WHERE filters: `WHERE s.status = 0 AND a.status = 0 AND l.graduated = 0` (the `a.status = 0` filter stays in `review.py`; the asymmetry with `learning.py` is preserved byte-for-byte per design).
      - The ORDER BY: `ORDER BY l.level DESC, l.id ASC`.
    - No new import lines added — `from scripts import _common  # noqa: E402` is already at module top.
    - `:offset` stays a SQLite bind parameter via the existing `conn.execute(_DUE_SQL, {"offset": offset})` call in `_build_payload`. The f-string only interpolates the static predicate text; it does not interpolate `:offset`.
    - _Bug_Condition: isBugCondition(codebase) — caller layer (review.py)_
    - _Expected_Behavior: Property 1 from design — `review.py._DUE_SQL` composes the shared constant via f-string interpolation_
    - _Preservation: Property 2 from design — `review.py song-review` writes byte-identical HTML bytes and emits byte-identical envelopes to v0.1.3 for every DB state and `--offset` value_
    - _Requirements: 2.4, 2.5, 2.6, 3.2, 3.4, 3.5, 3.6, 3.7_

## Verification

- [x] 3. Verify the Task 1 exploration test now passes
  - **Property 1: Expected Behavior** — the predicate text lives in exactly one file, `scripts/_common.py`
  - **IMPORTANT**: Re-run the SAME test from Task 1 — do NOT write a new test. The Task 1 test encodes the expected post-fix state.
  - Run `pytest tests/unit/test_due_time_condition_single_source.py` in isolation.
  - **EXPECTED OUTCOME**: Test PASSES — `len(matches) == 1` and `matches[0].name == "_common.py"`. This confirms the bug is fixed: the predicate text has been consolidated to a single source of truth.
  - If the test still fails, do not proceed to Task 4 — diagnose the root cause and revisit Task 2 before continuing.
  - _Requirements: 2.1, 2.2_

## Fix-checking importability smoke test

- [x] 4. Add the importability smoke test — composed `_DUE_SQL` contains the shared constant
  - **Property 1: Fix Checking — Structural Composition** — after the fix, both callers' `_DUE_SQL` module-level strings contain `_common.DUE_TIME_CONDITION_SQL`'s value as a substring, evidenced by Python import rather than text grep.
  - Add a new test `test_due_sql_strings_compose_from_common` to `tests/unit/test_due_time_condition_single_source.py` (same file as Task 1 — they cover the same structural property from two angles).
  - Text grep (Task 1) proves the predicate text only lives in one file. Import-time assertion (this task) proves both callers' `_DUE_SQL` strings are actually composed from that constant at module load, not just visually similar. Two independent structural witnesses.
  - **Implementation outline** (self-contained unit test, no subprocess):
    ```python
    def test_due_sql_strings_compose_from_common() -> None:
        from scripts import _common, learning, review

        assert hasattr(_common, "DUE_TIME_CONDITION_SQL"), (
            "scripts/_common.py must define DUE_TIME_CONDITION_SQL"
        )
        assert isinstance(_common.DUE_TIME_CONDITION_SQL, str)

        predicate = _common.DUE_TIME_CONDITION_SQL
        assert predicate in learning._DUE_SQL, (
            "scripts/learning.py._DUE_SQL must contain DUE_TIME_CONDITION_SQL as a substring"
        )
        assert predicate in review._DUE_SQL, (
            "scripts/review.py._DUE_SQL must contain DUE_TIME_CONDITION_SQL as a substring"
        )
    ```
  - Alternative / equivalent shell check (for manual verification, not the test itself): `python -c "from scripts import learning, review, _common; assert _common.DUE_TIME_CONDITION_SQL in learning._DUE_SQL; assert _common.DUE_TIME_CONDITION_SQL in review._DUE_SQL"` exits 0.
  - **EXPECTED OUTCOME ON UNFIXED CODE**: Test FAILS — `_common.DUE_TIME_CONDITION_SQL` doesn't exist yet, so `hasattr(...)` returns False and the first assertion fires. Running this pre-fix is not required; the Task 1 test is the canonical pre-fix failure. This test becomes meaningful after Task 2.
  - **EXPECTED OUTCOME ON FIXED CODE**: Test PASSES — the constant exists, is a string, and both callers' `_DUE_SQL` strings embed it as a substring at module load time (f-string evaluated once at import).
  - _Bug_Condition: isBugCondition(codebase) — structural composition layer_
  - _Expected_Behavior: Property 1 from design — both `_DUE_SQL` strings are composed by interpolating `_common.DUE_TIME_CONDITION_SQL`_
  - _Preservation: None — this is a fix-checking test, not a preservation test_
  - _Requirements: 2.3, 2.4_

## Preservation — existing suite is the oracle

- [x] 5. Preservation — no new test authored; existing suite pins every observable surface
  - **Property 2: Preservation** — every observable behavior (row sets, envelope shapes, HTML bytes, test-suite pass/fail set) is byte-identical between v0.1.3 (F) and the fixed codebase (F').
  - **IMPORTANT**: Follow observation-first methodology. The existing test suite IS the preservation oracle. **No new preservation test is authored by this spec** — writing one would add noise without adding coverage that the existing tests don't already provide.
  - The preservation oracle comprises three independent witnesses:
    - `tests/integration/test_due.py` — pins every branch of the predicate (level-0 with prior level-up, level-0 never-reviewed, level-above-zero with `level_up_path`), the `>=` equality boundary, `--offset` semantics, soft-delete + graduated filtering, ordering, and the full envelope field set for `learning.py due`.
    - `tests/integration/test_review.py` — pins `review.py song-review`'s HTML pipeline (output path + filename, empty-state rendering, happy-path payload, display-level carry-through, HTML escape and JSON-in-HTML safety, soft-delete + graduated filtering, soft-deleted show exclusion, INTERNAL_ERROR paths, `--offset` parity with `learning.py due`, envelope key-set shape, help/no-args surface, read-only DB invariant).
    - `tests/integration/property/test_due_property.py` — the strongest preservation test for this refactor: its inline `DUE_SQL` literal is an **independent textual oracle** for the predicate, and its three property-based tests seed random DB states and assert row-set equality between `learning.py due` and a direct SQL execution of that oracle. **Critical**: this file's `DUE_SQL` constant MUST stay byte-for-byte unchanged per design's "Out of scope for this refactor" section — its value comes from its independence, and rewiring it to consume `_common.DUE_TIME_CONDITION_SQL` would destroy its role as a third witness.
  - **Test plan** (observation-first, no new assertions):
    1. On F (v0.1.3, before Task 2 lands): run the full existing suite. Record the pass/fail set as the baseline.
    2. Land Task 2 (the fix).
    3. On F' (after Task 2 lands): run the full existing suite again. Record the pass/fail set.
    4. Assert the pass/fail sets are **identical** (all previously passing tests still pass; no previously failing tests now pass; no previously passing tests now fail).
    5. The Task 1 static-duplication test transitions from FAIL on F to PASS on F' — this transition is the expected fix signal, NOT a preservation violation, and is explicitly excluded from the preservation pass/fail comparison.
  - **EXPECTED OUTCOME ON FIXED CODE**: every existing test passes unchanged. Every row set `learning.py due` returns, every byte of HTML `review.py song-review` writes, and every envelope either emits is byte-identical to v0.1.3 output on the same input.
  - **PBT iterations**: `ITERATIONS = 5` in `tests/integration/property/_helpers.py` — **do NOT bump** this value as part of this spec. The existing property coverage is sufficient for a structural refactor.
  - Do NOT edit any existing test file. Do NOT edit the inline `DUE_SQL` literal in `test_due_property.py`. Do NOT add assertions to any existing test.
  - _Bug_Condition: ¬isBugCondition(codebase) — preservation codomain (all observable surfaces)_
  - _Expected_Behavior: Property 2 from design — byte-identical observable behavior_
  - _Preservation: Property 2 from design — row sets, envelopes, HTML bytes, and test pass/fail set all unchanged_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

## Final gate

- [x] 6. Checkpoint — run `make check`, confirm coverage ≥ 90%, full suite green
  - Run `make check` (lint + typecheck + test). Expect all three to pass.
  - Confirm coverage stays ≥ 90% — `./tests/run.sh` enforces this automatically via `.coveragerc`; fail the task if coverage drops. This is a **structural refactor with no new runtime code paths** — the three changes in Task 2 (one added constant, two `_DUE_SQL` literals converted to f-strings) are exercised by every existing test that runs `learning.py due` or `review.py song-review`, so the coverage floor should be unaffected. The new unit test file `tests/unit/test_due_time_condition_single_source.py` adds two tiny test functions but no new production code to cover.
  - Re-run the Task 1 exploration test and confirm it still passes:
    - `pytest tests/unit/test_due_time_condition_single_source.py::test_due_time_predicate_lives_in_exactly_one_file` — predicate text lives in exactly one file, `scripts/_common.py`.
  - Re-run the Task 4 importability smoke test and confirm it passes:
    - `pytest tests/unit/test_due_time_condition_single_source.py::test_due_sql_strings_compose_from_common` — both callers' `_DUE_SQL` strings embed `_common.DUE_TIME_CONDITION_SQL` as a substring at module load.
  - Re-run the full existing preservation suite and confirm every pre-existing test still passes byte-identically:
    - `pytest tests/integration/test_due.py` — `learning.py due` row sets, ordering, envelopes, `--offset` semantics, branch coverage, boundary conditions, and filter rules all unchanged (evidence for 3.1, 3.3, 3.5, 3.6, 3.10).
    - `pytest tests/integration/test_review.py` — `review.py song-review` HTML bytes, envelopes, output paths, template substitution, error paths, and `--offset` parity all unchanged (evidence for 3.2, 3.4, 3.5, 3.6, 3.7, 3.10).
    - `pytest tests/integration/property/test_due_property.py` — property-based coverage of `learning.py due` against the inline independent oracle unchanged. This is the strongest preservation signal: random DB seeds + an independent SQL oracle; any semantic drift in the extracted predicate would fail here (evidence for 3.8 — the `DUE_SQL` literal in this file stays byte-for-byte identical to v0.1.3).
    - `pytest tests/integration/test_error_codes.py` — error-envelope surface unchanged.
  - If any test fails or coverage drops, diagnose the root cause before proceeding; ask the user if questions arise. **Do not** "fix" a preservation-test failure by editing the test — a preservation-test failure on F' is a fix-regression signal and means Task 2 needs revisiting.
  - _Requirements: All 2.* and 3.* from bugfix.md_

## Commit

- [x] 7. Commit the fix as a single `refactor(common)` commit
  - **DO NOT actually commit from this task file** — this entry is instructional for when the implementation phase lands. The subagent does not run `git commit`, does not run `git tag`, and does not run `git push`. The user performs those actions.
  - Follow Conventional-Commits per the user rule.
  - Suggested commit message:
    - Subject (≤ 72 chars, imperative mood, no trailing period): `refactor(common): extract due-time predicate to single source of truth in _common.py`
    - Body: explain that `scripts/learning.py._DUE_SQL` and `scripts/review.py._DUE_SQL` each carried a near-copy of the three-branch due-time predicate as literal SQL text (the same nine-line `(...) OR (...) OR (...)` shape in both files), that this duplication already drifted once — v0.1.2 shipped `review.py` without the `+ :offset` terms in any of the three branches while `learning.py` had them, silently making `--offset` a no-op on the review page for one release, patched by v0.1.3 copying the term back — and that the fix extracts the predicate text to a single module-level constant `DUE_TIME_CONDITION_SQL` in `scripts/_common.py` and has both callers compose their full `_DUE_SQL` by f-string interpolation of that constant into their own SELECT / FROM / non-time-WHERE / ORDER BY skeletons; note that `:offset` remains a SQLite bind parameter throughout (bound via `{"offset": int(args.offset)}` in both scripts, identical to v0.1.3), that the alias contract (`learning` aliased as `l`) is preserved byte-for-byte, that no new imports are added to either script (`from scripts import _common` is already present in both), that observable behavior is **byte-identical** to v0.1.3 on every surface — row sets returned by `learning.py due`, HTML bytes written by `review.py song-review` to `App_Root/output/review_<epoch>.html`, envelope shapes, and test-suite pass/fail set — and that the inline `DUE_SQL` literal in `tests/integration/property/test_due_property.py` is **deliberately** preserved byte-for-byte as an independent third textual oracle of the predicate (the property test's value as an external witness depends on its independence); note v0.1.4 ships via the existing release pipeline (`release.md`, `.github/workflows/release.yml`) with no CLI change, no error-code change, no schema change, no template change, no CI / release-pipeline change, and no skill-doc change.
  - Scope: all files touched in one logical change — `scripts/_common.py`, `scripts/learning.py`, `scripts/review.py`, and the new `tests/unit/test_due_time_condition_single_source.py`.
  - Keep the commit self-contained: the three code changes and the two new unit tests (Task 1 text-grep exploration test, Task 4 importability smoke test) land together so commit history never contains a persistently-failing test.
  - Rollout per design: ships as v0.1.4 when the user tags and pushes. The existing release pipeline produces a v0.1.4 zip unchanged.
  - Do NOT `git push`. Do NOT `git tag`. Do NOT `git commit` from this task.
  - _Requirements: n/a (instructional task, no validation)_
