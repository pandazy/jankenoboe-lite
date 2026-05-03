# Due-Time Condition Dedup Bugfix Design

## Overview

The three-branch time-comparison predicate that defines "is this learning
record due?" lives as duplicated SQL text inside two scripts today:
`scripts/learning.py._DUE_SQL` and `scripts/review.py._DUE_SQL`. Two copies
of the same nine-line `(...) OR (...) OR (...)` expression, maintained by
hand, with one documented drift already on record (v0.1.2's `review.py`
was missing `+ :offset` in all three branches while `learning.py` had it
in all three — v0.1.3 patched that by copying the term back).

The fix is structural, not behavioral. The predicate text moves — in
its entirety, including its outer parentheses — from both scripts into a
single module-level string constant in `scripts/_common.py` named
`DUE_TIME_CONDITION_SQL`. Each caller keeps its own SELECT list,
FROM/JOIN shape, non-time WHERE filters, and ORDER BY exactly as they
are today, and composes its full `_DUE_SQL` at module-load time by
interpolating the shared constant via Python f-string. `:offset` stays
a SQLite bind parameter, untouched. Nothing at the observable boundary
changes — row sets, envelope shapes, HTML bytes, and envelope field
order are all byte-identical between v0.1.3 and the fixed codebase.

## Glossary

- **Bug_Condition (C)**: The predicate text appears in more than one file
  under `scripts/**/*.py`. Today `C(codebase) = true` because the text
  exists in both `learning.py` and `review.py`.
- **Property (P)**: After the fix, the predicate text exists in exactly
  one source file (`scripts/_common.py`), and both callers compose their
  full `_DUE_SQL` by interpolating that shared constant.
- **Preservation**: Every observable behavior — `learning.py due` output,
  `review.py song-review` HTML bytes, existing test suite pass/fail set
  — is byte-identical between F (v0.1.3) and F' (the fixed codebase).
- **DUE_TIME_CONDITION_SQL**: The new module-level string constant in
  `scripts/_common.py` holding the three-branch predicate as its single
  source of truth.
- **_DUE_SQL**: A module-level SQL string in each caller. After the fix,
  it is an f-string composed at module-load time rather than a plain
  literal.
- **Predicate text**: The exact outer-parenthesised three-branch `OR`
  expression that lives today under each script's `WHERE` clause. Copied
  verbatim (modulo leading indentation per Decision 3) into the shared
  constant.
- **Alias contract**: The shared predicate references the learning table
  as `l`. Callers must alias `learning` as `l` (and `song` as `s`, which
  both already do; `review.py` also aliases `artist` as `a`). The
  predicate does not reference `s` or `a`, so the constant only pins the
  `l` alias.
- **Bind contract**: Callers bind `:offset` (integer seconds) via
  `conn.execute(sql, {"offset": int(args.offset)})`. The constant
  references `:offset` directly as a SQLite bind placeholder and does
  not interpolate it.
- **F**: The codebase at v0.1.3 — predicate text in two files.
- **F'**: The codebase after the fix — predicate text in one file,
  composed via f-string in both callers.

## Bug Details

### Bug Condition

The bug manifests as a static property of the source tree: the
three-branch due-time predicate appears as textual SQL in more than one
file under `scripts/`. The duplication is the bug. Any future edit to
the semantics requires a lockstep change to both files, and history
shows that lockstep has failed before.

**Formal Specification:**
```
FUNCTION isBugCondition(codebase)
  INPUT:  codebase of type SourceTree
  OUTPUT: boolean

  // True iff the three-branch due-time predicate appears as text
  // (modulo whitespace) in more than one source file under scripts/.
  RETURN countOccurrences(codebase, DUE_TIME_PREDICATE_TEXT) > 1
END FUNCTION
```

### Examples

- **v0.1.3 (current, buggy)**: `scripts/learning.py` contains the
  predicate inside `_DUE_SQL`; `scripts/review.py` contains the same
  predicate inside its own `_DUE_SQL`.
  `countOccurrences = 2`, so `isBugCondition = true`.
- **v0.1.2 historical drift**: `review.py` was missing `+ :offset` in
  all three branches; `learning.py` had it. Observable symptom:
  `review.py song-review --offset N` silently ignored `N` for one
  release. The duplication enabled that divergence.
- **Hypothetical future change**: Swap the 300-second level-0 threshold
  for a configurable value. Under F, this edit must land identically in
  both files; missing one file is a silent regression. Under F', a
  single-file edit suffices.
- **Edge case (no drift yet)**: Even when the two copies agree
  byte-for-byte, `isBugCondition = true`. The bug is the existence of
  the second copy, not the presence of a mismatch.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- `learning.py due` returns the same row set, in the same
  `ORDER BY l.level DESC, l.id ASC` order, with the same
  `{"results": [...], "offset": N}` envelope shape, for any DB state and
  any `--offset` value.
- `review.py song-review` writes byte-identical HTML to
  `App_Root/output/review_<epoch>.html` and emits the same
  `{"path": ..., "due_count": N, "offset": N}` envelope, for any DB
  state and any `--offset` value.
- `_DUE_SQL` in each script selects the same columns it selects today
  (9 fields in `learning.py`, 11 fields in `review.py`) with the same
  aliases.
- Each script's FROM/JOIN shape is unchanged (`learning.py` joins
  `song s` only; `review.py` joins `song s` and `artist a`).
- Each script's non-time WHERE filters are unchanged
  (`learning.py`: `s.status = 0 AND l.graduated = 0`;
  `review.py`: `s.status = 0 AND a.status = 0 AND l.graduated = 0`).
  The known asymmetry — `learning.py` does not filter `a.status = 0`,
  `review.py` does — is explicitly out of scope for this spec.
- `:offset` stays a SQLite bind parameter throughout, bound via the
  same `{"offset": int(args.offset)}` dict both scripts use today.
- `scripts/_common.py` stays on the Python 3.10+ standard library. The
  new constant is a plain `str` literal, no new imports.
- Skill documents under `skills/` and developer docs under `dev-docs/`
  are not modified.
- Every existing test passes unchanged — no assertions are edited for
  behavior, including the inline `DUE_SQL` oracle in
  `tests/integration/property/test_due_property.py`.

**Scope:**
All observable behavior is preserved. The only changes live inside
`scripts/` source files. The diff is a textual reshuffle: one added
constant in `_common.py`, two `_DUE_SQL` literals converted to
f-strings, and the deleted predicate text inside each `_DUE_SQL`.

## Hypothesized Root Cause

The root cause of the dedup bug is simple: both `learning.py due` and
`review.py song-review` need to answer the same question ("is this
learning record due?") and, during their initial authoring, the
predicate was typed into each file independently rather than factored
into a shared helper. The four contributing factors:

1. **Independent authorship**: `learning.py` and `review.py` were
   written as separate pipelines. Each needed the due predicate.
   Neither author reached for `_common.py` at the time; the textual copy
   was the path of least resistance.

2. **No lint rule against SQL duplication**: The project has no static
   check (grep-based or AST-based) asserting that this specific
   predicate appears only once. Python duplication detectors do not
   generally catch SQL-string duplication.

3. **Predicate is stable enough to get away with it**: The three-branch
   shape has held through multiple releases. Both authors assumed
   "we'll factor this if it ever changes" — which is exactly when
   v0.1.2 drifted, because the `+ :offset` change landed in one file
   and not the other.

4. **The predicate is also copy-pasted into a test oracle**:
   `tests/integration/property/test_due_property.py` keeps its own inline
   copy of the full `DUE_SQL` as an independent oracle for the
   property-based test. That's a third copy on top of the two in
   `scripts/`. This spec does NOT deduplicate the test oracle — see
   "Out of scope for this refactor" at the end of Testing Strategy.

## Correctness Properties

Property 1: Bug Condition - Single Source of Truth for Due-Time Predicate

_For any_ state of the source tree where the bug condition holds
(`isBugCondition` returns true — i.e. the three-branch predicate text
appears in more than one file under `scripts/**/*.py`), the fixed
codebase SHALL reduce the count to exactly one occurrence, located in
`scripts/_common.py` as the module-level string constant
`DUE_TIME_CONDITION_SQL`. Both `scripts/learning.py._DUE_SQL` and
`scripts/review.py._DUE_SQL` SHALL be composed by f-string
interpolation of that constant into their own SELECT / FROM /
non-time-WHERE / ORDER BY skeletons at module-load time, and every
runtime invocation of `learning.py due` and `review.py song-review`
SHALL continue to bind `:offset` as a SQLite parameter, not as an
interpolated string.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**

Property 2: Preservation - Byte-Identical Observable Behavior

_For any_ input (database state, `--offset` value, and script
invocation) where the bug condition does NOT hold (the predicate text
is already at a count of one — the post-fix state), the fixed codebase
SHALL produce exactly the same result as the v0.1.3 codebase for every
observable surface:

- `learning.py due` returns the same row set, same order, same envelope
  shape, and same field set for every row.
- `review.py song-review` writes byte-identical HTML bytes to
  `App_Root/output/review_<epoch>.html` and emits the same envelope.
- The existing test suite — including `tests/integration/test_due.py`,
  `tests/integration/test_review.py`, and
  `tests/integration/property/test_due_property.py` — passes with
  zero assertion edits.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11**

## Fix Implementation

### Decision 1 — Where to put the constant

`scripts/_common.py`. Already imported by both scripts, already the
shared-module hub, already Python 3.10+ stdlib only (no new imports
needed — the constant is a plain `str` literal). Name:
`DUE_TIME_CONDITION_SQL`. Place it adjacent to the other SQL/schema
constants (`EXPECTED_SCHEMA`, `MAX_LEVEL`, `DEFAULT_LEVEL_UP_PATH`,
`RE_LEARN_LEVEL`) — a "SQL fragments" section near the easing constants
is a natural home. The constant carries a docstring (string literal
preceded by a comment header, or a leading comment block) that pins the
alias contract, the bind contract, and the role of each branch.

### Decision 2 — Interpolation mechanism

F-string interpolation in each script's module-level `_DUE_SQL`
definition. Example shape for `learning.py`:

```python
_DUE_SQL = f"""
SELECT
    l.id,
    l.song_id,
    s.name AS song_name,
    l.level,
    (l.level + 1) AS display_level,
    COALESCE(json_extract(l.level_up_path, '$[' || l.level || ']'), 0) AS wait_days,
    l.last_level_up_at,
    l.updated_at,
    l.graduated
FROM learning l
JOIN song s ON s.id = l.song_id
WHERE s.status = 0
  AND l.graduated = 0
  AND {_common.DUE_TIME_CONDITION_SQL}
ORDER BY l.level DESC, l.id ASC
"""
```

The f-string interpolates the static predicate string only; `:offset`
stays a SQLite bind parameter throughout, unchanged. Python's f-string
is evaluated once at module load time, so runtime cost is zero — the
composed `_DUE_SQL` is the same plain `str` object after module init as
a hand-written literal would be.

### Decision 3 — Indentation handling

Strip leading whitespace from the constant and let the composed
`WHERE` clause read as `AND <condition>` on a single logical line.
SQLite is whitespace-insensitive, so the rendered `_DUE_SQL` text will
not be aesthetically perfect, but the test for correctness is SQL
semantics, not text shape. The constant itself is stored with clean
formatting (outer `(...)` preserved, inner branches indented for
readability when reading `_common.py`). The composition does not try to
re-indent anything.

### Decision 4 — What the predicate constant's docstring says

A leading comment block and/or adjacent docstring naming:

- **Role**: the three-branch due-time predicate — the one source of
  truth consumed by both `learning.py._DUE_SQL` and
  `review.py._DUE_SQL`.
- **Alias contract**: callers must alias the `learning` table as `l`.
  The predicate does not reference any other table; it only touches
  `l.last_level_up_at`, `l.level`, `l.updated_at`, and
  `l.level_up_path`.
- **Bind contract**: callers must bind `:offset` (integer seconds)
  via `conn.execute(..., {"offset": int(args.offset)})`. Do not
  interpolate `:offset` into the constant — it is a SQLite bind
  parameter.
- **Branches**:
  - Branch A: `level = 0` and `last_level_up_at > 0` — due when
    `now + offset >= last_level_up_at + 300`.
  - Branch B: `level = 0` and `last_level_up_at = 0` — due when
    `now + offset >= updated_at + 300` (never-reviewed rows fall
    back to `updated_at`).
  - Branch C: `level > 0` — due when
    `level_up_path[level] * 86400 + last_level_up_at <= now + offset`
    (wait-days path from the stored `level_up_path` JSON).

### Decision 5 — What stays in each caller

**`scripts/learning.py._DUE_SQL`** keeps:
- Its 9-field SELECT list: `l.id`, `l.song_id`, `s.name AS song_name`,
  `l.level`, `(l.level + 1) AS display_level`, the `wait_days`
  expression (`COALESCE(json_extract(l.level_up_path, '$[' || l.level
  || ']'), 0) AS wait_days`), `l.last_level_up_at`, `l.updated_at`,
  `l.graduated`.
- Its FROM/JOIN: `FROM learning l JOIN song s ON s.id = l.song_id`.
- Its non-time WHERE filters:
  `WHERE s.status = 0 AND l.graduated = 0 AND {predicate}`.
- Its ORDER BY: `ORDER BY l.level DESC, l.id ASC`.

**`scripts/review.py._DUE_SQL`** keeps:
- Its 11-field SELECT list: `l.id AS learning_id`, `l.song_id AS
  song_id`, `s.name AS song_name`, `s.name_context AS song_name_context`,
  `s.artist_id AS artist_id`, `a.name AS artist_name`, `a.name_context
  AS artist_name_context`, `l.level AS level`, `(l.level + 1) AS
  display_level`, the `wait_days` expression aliased identically
  (`COALESCE(json_extract(l.level_up_path, '$[' || l.level || ']'), 0)
  AS wait_days`).
- Its FROM/JOIN:
  `FROM learning l JOIN song s ON s.id = l.song_id JOIN artist a ON
  a.id = s.artist_id`.
- Its non-time WHERE filters:
  `WHERE s.status = 0 AND a.status = 0 AND l.graduated = 0 AND
  {predicate}`.
- Its ORDER BY: `ORDER BY l.level DESC, l.id ASC`.

The asymmetry (learning.py does NOT filter `a.status = 0`, review.py
does) is preserved byte-for-byte. Whether that asymmetry is itself a
bug is a separate question and out of scope here.

### Decision 6 — Imports

Both scripts already have `from scripts import _common`. No new import
lines are added. The constant reference in each `_DUE_SQL` f-string is
`_common.DUE_TIME_CONDITION_SQL`.

### Changes Required

**File: `scripts/_common.py`**

- Add a new module-level string constant
  `DUE_TIME_CONDITION_SQL` near the existing SQL/schema constants
  (adjacent to `DEFAULT_LEVEL_UP_PATH` / `MAX_LEVEL` / `RE_LEARN_LEVEL`
  or just above them, in a small "SQL fragments" section).
- The constant's value is the three-branch predicate, outer `(...)`
  included, copied verbatim from the current `_DUE_SQL` bodies (modulo
  leading indentation per Decision 3).
- Document the constant with a leading comment block (or an assigned
  string preceded by a comment) naming role, alias contract, bind
  contract, and branch coverage (see Decision 4).

**File: `scripts/learning.py`**

- Convert `_DUE_SQL` from a triple-quoted literal to an f-string.
- Replace the nine lines that today spell out the predicate — from
  `AND (` through the closing `)` — with `AND
  {_common.DUE_TIME_CONDITION_SQL}`.
- Leave every other line of `_DUE_SQL` byte-for-byte identical
  (SELECT, FROM/JOIN, other WHERE clauses, ORDER BY).

**File: `scripts/review.py`**

- Convert `_DUE_SQL` from a triple-quoted literal to an f-string.
- Replace the same nine lines — from `AND (` through the closing `)` —
  with `AND {_common.DUE_TIME_CONDITION_SQL}`.
- Leave every other line byte-for-byte identical.

No other files are touched. No tests are edited. No skill docs are
edited. No config or CI files are edited.

## Testing Strategy

### Validation Approach

This is a pure refactor. The preservation property is the primary
correctness concern, and the existing test suite is the oracle for it.
The bug condition — the static "predicate text exists in more than one
file" property — needs one new tiny test that reads the `scripts/`
directory and counts occurrences. Everything else leans on existing
coverage.

Two-phase approach:

1. **Exploratory bug-condition test first** — write a static source-tree
   test that counts predicate occurrences under `scripts/**/*.py`.
   Observe it fails on v0.1.3 (count == 2) before the fix lands.
2. **Run the fix, then verify preservation** — re-run the existing
   suite unchanged. All pass, plus the new test flips to passing
   because the predicate now lives in exactly one file.

### Exploratory Bug Condition Checking

**Goal**: Surface a counterexample that demonstrates the bug BEFORE
implementing the fix. Confirm that the textual duplication is real and
detectable by a simple static check. If the test somehow passes on
unfixed code, the root-cause analysis is wrong and we need to
re-hypothesize.

**Test Plan**: Write one new test that walks every `.py` file under
`scripts/` and counts how many contain the three-branch predicate
(matched modulo whitespace — normalize runs of whitespace to single
spaces before matching, so indentation differences between the two
current copies don't defeat the check). Place the test in `tests/unit/`
— it's a static source-tree inspection, not a subprocess test, and
doesn't need the integration fixtures. The test should pick a stable
fingerprint substring of the predicate (for example the unique sequence
`l.last_level_up_at + 300` followed later by
`l.updated_at + 300` followed by `json_extract(l.level_up_path`) rather
than a full whitespace-sensitive literal match — the goal is to detect
"this predicate shape" robustly.

**Test Cases**:

1. **Static count test**: Count `.py` files under `scripts/` that
   contain the predicate's fingerprint. Assert the count is exactly
   one, and assert the single match lives in `scripts/_common.py`.
   - On **F (v0.1.3, unfixed)**: count is 2 — test FAILS.
   - On **F' (fixed)**: count is 1, in `_common.py` — test PASSES.

**Expected Counterexamples**:

- Running the test before the fix lands yields a `count == 2` failure
  with the two file paths (`scripts/learning.py` and `scripts/review.py`).
- This confirms the root cause is textual duplication in two specific
  files, which is exactly what the fix extracts.

### Fix Checking

**Goal**: Verify that for every codebase state where the bug condition
holds (predicate text in more than one file), the fix reduces the count
to exactly one occurrence located in `_common.py`, and both callers
compose their SQL by f-string interpolation rather than by direct
literal.

**Pseudocode:**
```
FOR ALL codebase WHERE isBugCondition(codebase) DO
  codebase' := applyFix(codebase)
  ASSERT countOccurrences(codebase', predicate) = 1
  ASSERT theSingleOccurrence IS in "scripts/_common.py"
  ASSERT learning.py._DUE_SQL COMPOSES _common.DUE_TIME_CONDITION_SQL VIA f-string
  ASSERT review.py._DUE_SQL   COMPOSES _common.DUE_TIME_CONDITION_SQL VIA f-string
END FOR
```

In practice the fix-checking set is a singleton — there's one codebase
to fix. The assertion collapses to: the new static test passes on F',
and both `_DUE_SQL` literals in `scripts/` now reference
`_common.DUE_TIME_CONDITION_SQL`.

### Preservation Checking

**Goal**: Verify that for every (DB state, offset) input the refactor
produces byte-identical observable behavior — same rows, same HTML
bytes, same envelopes, same test-suite pass/fail set.

**Pseudocode:**
```
FOR ALL (dbState, offset) DO
  ASSERT learning_due(F, dbState, offset)
       = learning_due(F', dbState, offset)
  ASSERT review_song_review_bytes(F, dbState, offset)
       = review_song_review_bytes(F', dbState, offset)
  ASSERT full_test_suite(F) = full_test_suite(F')
END FOR
```

**Testing Approach**: The existing test suite is the preservation
oracle. No new preservation tests are written. Running the full suite
against F' is the check — every test that passes on F must pass on F',
with no assertion edits.

The following existing tests collectively pin every moving surface of
the refactor:

- `tests/integration/test_due.py` — pins every branch of the predicate
  (`test_branch_a_level_zero_after_first_review`,
  `test_branch_b_level_zero_never_reviewed`,
  `test_branch_c_level_above_zero_uses_level_up_path`), the `>=`
  equality boundary (`test_boundary_equal_is_due`), `--offset`
  semantics (`test_offset_shifts_otherwise_not_due_row_into_result`),
  soft-delete + graduated filtering, ordering, and the full envelope
  field set.
- `tests/integration/test_review.py` — pins the HTML pipeline
  (output path + filename, empty-state rendering, happy-path payload,
  display-level carry-through, HTML escape / JSON-in-HTML safety,
  soft-delete + graduated filtering, soft-deleted show exclusion,
  INTERNAL_ERROR paths for missing template / missing marker,
  `--offset` parity with `learning.py due`, envelope key-set shape,
  help/no-args surface, and the read-only DB invariant).
- `tests/integration/property/test_due_property.py` — the strongest
  preservation test for this refactor: its inline `DUE_SQL` literal is
  an independent textual oracle for the predicate, and its three
  property-based tests seed random DB states and assert row-set equality
  between `learning.py due` and a direct SQL execution of that oracle.
  If the extraction changes the predicate semantics in any way, this
  test set catches it.

**Test Plan**: Run the existing suite on F before starting work to
baseline the pass/fail set. Land the fix. Run the existing suite on F'.
Assert that the pass/fail sets are identical (all previously passing
tests still pass; no previously failing tests now pass, and no
previously passing tests now fail). The new static-duplication test
transitions from failing on F to passing on F', which is the expected
fix-check signal — that transition is not considered a preservation
violation.

**Test Cases** (all existing, no edits):

1. **Row-set preservation (learning.py)**: `test_due.py` run unchanged.
   Observe on F, observe on F' — result sets match.
2. **HTML-bytes preservation (review.py)**: `test_review.py` run
   unchanged. Observe on F, observe on F' — generated HTML bytes and
   JSON envelopes match.
3. **Property preservation**: `test_due_property.py` run unchanged.
   Observe on F, observe on F' — random DB seeds yield identical
   `learning.py due` output vs direct-SQL oracle output under both.

### Unit Tests

- The new static-duplication test (see Exploratory Bug Condition
  Checking) lives in `tests/unit/`. It has no fixtures, no subprocess,
  no DB — it reads files under `scripts/` and counts.

### Property-Based Tests

- **No new property-based tests** are authored by this spec. The
  existing `test_due_property.py` already encodes the preservation
  property (random DB seed → `learning.py due` output matches an
  independent SQL oracle) and provides strong coverage without any
  additions.
- The inline `DUE_SQL` constant inside `test_due_property.py` stays
  byte-for-byte identical to its v0.1.3 text. Updating it to consume
  `_common.DUE_TIME_CONDITION_SQL` is tempting — the property test's
  "independent oracle" value comes precisely from its independence, so
  leaving it as a standalone copy preserves the "two witnesses" quality
  of the test. (See Out of scope below.)

### Integration Tests

- **No new integration tests** are authored by this spec. The existing
  `test_due.py` and `test_review.py` cover every observable surface
  that this refactor could possibly change.

### Out of scope for this refactor

- **Deduplicating the test oracle**: The inline `DUE_SQL` constant in
  `tests/integration/property/test_due_property.py` is a third textual
  copy of the predicate. The bug condition in this spec is scoped
  specifically to `scripts/**/*.py` — the test oracle is not a
  production-code duplicate, and keeping it independent preserves the
  test's value as an external witness. Flagged here for a future pass.
- **Eliminating the `a.status = 0` asymmetry**: `review.py` filters
  soft-deleted artists but `learning.py` does not. This may be a bug in
  its own right, but changing it would alter observable behavior and is
  a separate scope.

## Rollout

- **Single commit**:
  `refactor(common): extract due-time predicate to single source of
  truth in _common.py`.
- **Release vehicle**: ships as **v0.1.4** through the existing release
  pipeline (`.github/workflows/release.yml`), no pipeline changes.
- **Release notes** (`release.md`): one bullet naming the dedup and
  noting byte-identical behavior — for example:
  > Refactor: extracted the three-branch due-time predicate to a single
  > module-level constant in `scripts/_common.py`
  > (`DUE_TIME_CONDITION_SQL`). Both `learning.py due` and
  > `review.py song-review` now compose their SQL from that single
  > source. Observable behavior is byte-identical to v0.1.3.
- **Risk**: low. The diff is a textual reshuffle inside `scripts/`. No
  schema change, no bind-contract change, no CLI surface change, no
  HTML template change. The full existing test suite plus the new
  static-duplication test gate the change.
- **Rollback**: trivial — the commit is self-contained. Revert the
  commit, release v0.1.5 as a revert if any regression is observed in
  the field. No data migration considerations.
