# Review Offset Consistency Bugfix Design

## Overview

`scripts/learning.py due` and `scripts/review.py song-review` carry near-copies of the same Due_SQL_Condition. `learning.py` already accepts `--offset N` (integer seconds) and threads `+ :offset` into each `CAST(strftime('%s','now') AS INTEGER)` comparison; `review.py` has the same SQL without the `+ :offset` terms and no flag on the subparser. The result is an asymmetric surface — agents can count rows for "tomorrow" via `learning.py due --offset 86400` but cannot render the matching HTML page.

The fix is narrow and additive: add `--offset N` to the `song-review` subparser using the exact argparse kwargs `learning.py` uses, plumb the bind through `_DUE_SQL` in the three places that already exist in `learning.py`'s copy, and add an `offset` integer field to the Success_Envelope alongside `path` and `due_count`. The `_DUE_SQL` duplication between the two scripts stays as-is — deduplication is out of scope per R3.9.

Nothing else moves. `_shows_for_song`, `_media_urls_from_play_history`, `_escape_json_for_html`, `_render_page`, `_TEMPLATE_PATH`, `_MARKER_BYTES`, and `scripts/review_template.html` remain byte-identical. `scripts/_common.py` is untouched (R3.10). `scripts/learning.py` is untouched (R3.6).

## Glossary

- **Bug_Condition (C)**: The caller wants a non-zero time-shifted view of "due" on `review.py song-review`. In v0.1.2 this is literally unrepresentable on the command line — `--offset` is absent and the SQL has no `+ :offset` terms.
- **Property (P)**: When `--offset N` is passed, the set of `learning_id` values in the rendered payload equals the set of `id` values `learning.py due --offset N` would return against the same DB + clock.
- **Preservation**: Every zero-offset invocation produces byte-identical HTML, filename, and payload to v0.1.2; the Success_Envelope is identical except for the new `offset: 0` field.
- **Due_SQL_Condition**: The three-branch `WHERE` predicate inside `_DUE_SQL` that selects rows whose level, `last_level_up_at`, and `level_up_path[level]` mean they're due for review "right now" (or at `now + offset` post-fix).
- **`_build_parser()`**: `scripts/review.py` function that returns the argparse parser. Currently adds the `song-review` subparser with no flags.
- **`_build_payload(conn)`**: Current signature. Runs `_DUE_SQL`, joins shows and media URLs, returns the Due_Data_Payload dict.
- **`_cmd_song_review(conn, args)`**: Subcommand handler. Calls `_build_payload`, reads the template, calls `_render_page`, writes the file, emits the Success_Envelope.
- **Success_Envelope**: The dict `_common.success(...)` serialises to stdout. Currently `{"path": str, "due_count": int}`.

## Bug Details

### Bug Condition

The bug manifests when the caller passes `--offset N` with N ≠ 0 to `review.py song-review`. Today argparse rejects the flag outright (exit 2, "unrecognised argument"). Even if the flag were accepted, the three `CAST(strftime('%s', 'now') AS INTEGER)` sites in `_DUE_SQL` compare against SQLite's actual wall clock with no shift term, so the selected row set could never match the one `learning.py due --offset N` would return.

**Formal Specification:**
```
FUNCTION isBugCondition(invocation)
  INPUT:  invocation of type ReviewInvocation
  OUTPUT: boolean

  // The intent the caller wants to express is a non-zero shift of
  // SQLite's "now" — the same shift learning.py due --offset N would
  // compute for N != 0. That intent is unrepresentable on today's
  // song-review subcommand.
  RETURN invocation.desiredOffsetSeconds != 0
END FUNCTION
```

### Examples

- `review.py song-review --offset 86400` → today: argparse exit 2 ("unrecognised argument"). Expected: exit 0, HTML renders "due as of wall-clock + 1 day," envelope contains `{"path": "...", "due_count": N, "offset": 86400}`.
- `review.py song-review --offset 200` on a DB where a level-0 row has `last_level_up_at = now - 200` (100s away from the 300s level-0 threshold) → today: unrepresentable. Expected: that row lands in the rendered payload's `due_songs` array because `(now + 200) - last_level_up_at = 400 >= 300`.
- `review.py song-review --offset -3600` (look one hour into the past) → today: unrepresentable. Expected: exit 0, mirrors `learning.py due --offset -3600`'s `results` set.
- `review.py song-review` (no flag) and `review.py song-review --offset 0` on the same DB + clock → expected: byte-identical HTML, identical `{path, due_count}` fields in the envelope, new `offset: 0` field.
- `review.py song-review --offset abc` → expected: argparse standard exit-2 usage error, same as `learning.py due --offset abc`.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Zero-offset invocations (no `--offset` or `--offset 0`) render HTML bytes byte-identical to v0.1.2 (R3.1).
- `scripts/review_template.html` is byte-identical (R3.2).
- `scripts/_common.py` is byte-identical (R3.10).
- `scripts/learning.py` is byte-identical — the learning-side `--offset` is already correct (R3.6).
- The Due_Data_Payload schema is unchanged — same field set, same types, same semantics on `generated_at`, `due_count`, `due_songs`, every per-song field, every per-show field (R3.3).
- `_build_payload` still operates on exactly the rows Due_SQL_Condition selects, with no extra filtering, reordering, or projection (R3.4).
- `_render_page` and `_escape_json_for_html` produce byte-identical output for identical inputs (R3.5).
- The `path` and `due_count` envelope fields carry their v0.1.2 values — absolute output path string, integer count (R3.7).
- Output filename uses `_common.now_epoch()` — that is, the filename records when the file was written, not the logical "as of" time (R3.8).
- `_DUE_SQL` duplication between `learning.py` and `review.py` stays (R3.9).
- Due_SQL_Condition semantics are unchanged beyond the ability to shift the compared "now" — no threshold, branch, ordering, or join is altered (R3.11).

**Scope:**
Every invocation the caller could already express in v0.1.2 — the set `{invocation : invocation.desiredOffsetSeconds = 0}` — must be byte-identical post-fix. The only caller-observable difference is the single new `offset` integer field in the Success_Envelope.

## Hypothesized Root Cause

Root cause is well-understood and not hypothetical — the code is open, the asymmetry is visible by eye, and `learning.py` already shows the correct shape. Listed for completeness:

1. **Missing argparse surface**: `_build_parser()` calls `sub.add_parser("song-review", ...)` and returns without adding any arguments. No `--offset` is declared, so argparse rejects it as an unknown flag.

2. **Literal SQL text**: The `_DUE_SQL` constant in `review.py` is a near-copy of `learning.py`'s, but the three `CAST(strftime('%s', 'now') AS INTEGER)` expressions are bare — they lack the `+ :offset` term and the surrounding parentheses that `learning.py`'s copy carries. No bind dict is passed to `conn.execute(_DUE_SQL)`.

3. **Envelope shape**: `_cmd_song_review` emits `{"path": str(target), "due_count": payload["due_count"]}` with no slot for an offset value.

No other mechanism is in play. The fix is a mechanical port of the three sites that already exist, correctly, in `learning.py`.

## Correctness Properties

Property 1: Bug Condition - Offset consistency with learning.py

_For any_ invocation of `review.py song-review --offset N` where N ≠ 0 against a given database state and wall clock, the fixed script SHALL exit 0, SHALL echo `offset: N` in the Success_Envelope, and the set of `learning_id` values in the rendered payload's `due_songs` array SHALL equal the set of `id` values returned by `learning.py due --offset N` against the same database state and wall clock.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - Zero-offset behaviour is unchanged

_For any_ invocation of `review.py song-review` with no `--offset` flag or `--offset 0` against a given database state and wall clock, the fixed script SHALL produce HTML bytes, a `path` field, and a `due_count` field byte-identical to v0.1.2, preserving the template, the payload schema, the filename scheme, the row ordering, and the existing envelope fields. The Success_Envelope SHALL gain exactly one new top-level key, `offset`, with integer value 0.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 3.8, 3.11**

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct (it is — `learning.py` already carries the correct shape), four small changes in `scripts/review.py`. Nothing else changes.

**File**: `scripts/review.py`

#### Change 1 — add `--offset` to the `song-review` subparser

`_build_parser()` currently has `sub.add_parser("song-review", help=...)` with no arguments. Capture the returned subparser and call `add_argument` with the exact kwargs `learning.py due` uses, so the two CLI surfaces feel identical (same type, same default, same help phrasing naming "seconds"). Per R2.1, the argparse semantics must mirror `learning.py due`'s.

Current code:
```python
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review.py",
        description="Generate the HTML review page for due songs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("song-review", help="Render App_Root/output/review_<EPOCH>.html.")
    return p
```

After the fix:
```python
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review.py",
        description="Generate the HTML review page for due songs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sr = sub.add_parser("song-review", help="Render App_Root/output/review_<EPOCH>.html.")
    sr.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Shift the 'now' comparison forward by N seconds (default 0).",
    )
    return p
```

The `type=int, default=0` combination gives R2.6 for free — a non-integer N triggers argparse's standard exit-2 usage error with no new error code required.

#### Change 2 — thread `+ :offset` through `_DUE_SQL`

Each of the three `CAST(strftime('%s', 'now') AS INTEGER)` sites in `review.py`'s `_DUE_SQL` becomes `(CAST(strftime('%s', 'now') AS INTEGER) + :offset)`. Parenthesisation matches `learning.py`'s copy verbatim. Per R2.2, the three sites are the level-0-with-`last_level_up_at>0` branch, the level-0-with-`last_level_up_at=0` branch, and the level-`>0` branch.

The final `_DUE_SQL` (columns and joins unchanged; only the three `(CAST ... + :offset)` substitutions shown for the predicate):

```python
_DUE_SQL = """
SELECT
    l.id                   AS learning_id,
    l.song_id              AS song_id,
    s.name                 AS song_name,
    s.name_context         AS song_name_context,
    s.artist_id            AS artist_id,
    a.name                 AS artist_name,
    a.name_context         AS artist_name_context,
    l.level                AS level,
    (l.level + 1)          AS display_level,
    COALESCE(
        json_extract(l.level_up_path, '$[' || l.level || ']'), 0
    )                      AS wait_days
FROM learning l
JOIN song   s ON s.id = l.song_id
JOIN artist a ON a.id = s.artist_id
WHERE s.status = 0
  AND a.status = 0
  AND l.graduated = 0
  AND (
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
  )
ORDER BY l.level DESC, l.id ASC
"""
```

The three substituted predicates match the three predicates in `learning.py`'s `_DUE_SQL` byte-for-byte. Columns, joins, and ORDER BY are unchanged from v0.1.2 — review.py retains its extra `artist` join and `name_context` / `artist_*` / `wait_days` columns that `learning.py` doesn't need.

#### Change 3 — `_build_payload` accepts and binds `offset`

Current signature: `_build_payload(conn: sqlite3.Connection) -> dict[str, Any]`. After the fix: `_build_payload(conn: sqlite3.Connection, offset: int) -> dict[str, Any]`. The SQL execution site `conn.execute(_DUE_SQL).fetchall()` becomes `conn.execute(_DUE_SQL, {"offset": offset}).fetchall()`, mirroring `learning.py`'s `conn.execute(_DUE_SQL, {"offset": int(args.offset)})`.

Per R3.8, the offset is NOT added to `payload["generated_at"]`. The filename uses `_common.now_epoch()` for the `<EPOCH>` component; `generated_at` stamps when the file was written, not the logical "as of" time. Only the Due_SQL_Condition and the Success_Envelope echo see the offset. The Due_Data_Payload schema (R3.3) is unchanged.

#### Change 4 — Success_Envelope gains `offset`

`_cmd_song_review(conn, args)` extracts `args.offset`, passes `int(args.offset)` to `_build_payload`, and adds `"offset": int(args.offset)` to the envelope dict. The key order is preserved to match the existing convention — `path` first, `due_count` second, new field last:

```python
def _cmd_song_review(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    payload = _build_payload(conn, int(args.offset))
    try:
        template_bytes = _TEMPLATE_PATH.read_bytes()
    except FileNotFoundError as exc:
        raise _common.KnownError(
            "INTERNAL_ERROR",
            "review template missing",
            {"path": str(_TEMPLATE_PATH)},
        ) from exc

    rendered = _render_page(payload, template_bytes)

    app_root = _common.app_root(__file__)
    output_dir = app_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"review_{_common.now_epoch()}.html"
    target.write_bytes(rendered)

    _common.success({
        "path": str(target),
        "due_count": payload["due_count"],
        "offset": int(args.offset),
    })
```

The `_args` rename to `args` is the only other change — the handler now reads `args.offset`.

### Files Not Touched

- `scripts/learning.py` — per R3.6.
- `scripts/_common.py` — per R3.10.
- `scripts/review_template.html` — per R3.2.
- `scripts/review.py`: `_shows_for_song`, `_media_urls_from_play_history`, `_escape_json_for_html`, `_render_page`, `_TEMPLATE_PATH`, `_MARKER_BYTES`, `main`, `_DISPATCH` — unchanged.

## Testing Strategy

### Validation Approach

Two phases: first surface a counterexample that demonstrates the bug on unfixed code (argparse rejecting `--offset`), then verify the fix exposes the same row set `learning.py due --offset N` would return, and preserve zero-offset behaviour byte-identically.

All new tests live in `tests/integration/test_review.py`. It already has the helpers needed — `_load_data_block`, `_parse_scripts`, `_run_review_pinned`, `_sqlite_now` — so no new infrastructure is required.

### Exploratory Bug Condition Checking

**Goal**: Surface a counterexample that demonstrates the bug BEFORE implementing the fix. The exploration test is this spec's Task 1 PBT — it MUST fail on unfixed code.

**Test Plan**: A single integration test that invokes `review.py song-review --offset 86400` on an empty DB and asserts the script exits 0. On unfixed code argparse exits 2 with "unrecognised argument --offset"; the `rc == 0` assertion is the counterexample. After Change 1 lands, the test flips green.

**Test Cases**:
1. **Argparse acceptance test** — `call_script("review.py", "song-review", "--offset", "86400", cwd=tmp_app_root)` SHALL return rc == 0 (will fail on unfixed code with rc == 2).

**Expected Counterexample**:
- Unfixed code: `rc == 2`, stderr contains "unrecognised argument --offset" (or argparse's standard phrasing).
- Root cause confirmed: `_build_parser()` adds no argument to the `song-review` subparser.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (N ≠ 0), the fixed script selects the same row set `learning.py due --offset N` would select under the same DB + clock.

**Pseudocode:**
```
FOR ALL invocation WHERE isBugCondition(invocation) DO
  N      := invocation.desiredOffsetSeconds
  db     := invocation.database
  clock  := invocation.wallClock

  review_result   := review.py song-review --offset N
  learning_result := learning.py due --offset N

  ASSERT review_result.exitCode == 0
  ASSERT review_result.envelope.offset == N
  ASSERT { s.learning_id : s IN review_result.payload.due_songs }
         == { r.id       : r IN learning_result.results }
END FOR
```

**Test Plan**: Seed one level-0 learning row whose `last_level_up_at = sqlite_now - 200` (100s shy of the 300s level-0 threshold). At `--offset 0` it's not due; at `--offset 200` it crosses the boundary and becomes due. Run both `learning.py due --offset 200` and `review.py song-review --offset 200` against the same DB. Extract the payload via `_load_data_block(expected.read_text("utf-8"))`. Assert the `learning_id` set in `due_songs` equals the `id` set in `results`.

**Test Cases**:
1. **Positive-offset parity** — seed a row 100s shy of the level-0 threshold; run both scripts with `--offset 200`; assert `{s["learning_id"] for s in payload["due_songs"]} == {r["id"] for r in learning_results}`; assert both contain the seeded id. Per R2.3.
2. **Envelope echo** — assert `review.py song-review --offset 200`'s envelope has `offset == 200` and still carries `path` (str) and `due_count` (int). Per R2.4.

### Preservation Checking

**Goal**: Verify that for zero-offset invocations (the set `{invocation : invocation.desiredOffsetSeconds = 0}`), the fixed script produces byte-identical HTML and the envelope gains exactly one new key `offset` with value 0.

**Pseudocode:**
```
FOR ALL invocation WHERE NOT isBugCondition(invocation) DO
  before := review.py_v0.1.2(invocation)
  after  := review.py_post_fix(invocation)

  ASSERT after.htmlBytes          == before.htmlBytes
  ASSERT after.envelope.path      == before.envelope.path
  ASSERT after.envelope.due_count == before.envelope.due_count
  ASSERT after.envelope.offset    == 0
  ASSERT keys(after.envelope) \ keys(before.envelope) == {"offset"}
  ASSERT keys(before.envelope) \ keys(after.envelope) == {}
END FOR
```

**Testing Approach**: The existing `tests/integration/test_review.py` suite already exercises `review.py song-review` without `--offset` across every preservation-relevant axis — empty state, happy path, display level, HTML escape, filter rules, output path, idempotent directory creation, error paths. Post-fix, every test in that file MUST pass unchanged except where it asserts the envelope's exact key set. Those tests currently assert `out["path"]` and `out["due_count"]` individually, which is still correct post-fix — the new `offset` key doesn't break per-key access. No modifications to existing tests are required for them to keep passing.

The envelope-shape invariant gets one dedicated preservation test rather than threading a new assertion through every existing test in the file.

**Test Plan**:
1. Observe behaviour on unfixed code by running the existing `test_writes_to_timestamped_path_under_output` and `test_happy_path_renders_due_song` tests — they pass today.
2. Add one new preservation test that pins the envelope's top-level key set to exactly `{"path", "due_count", "offset"}` on a no-flag invocation. This codifies the "one new key, named `offset`, value 0" contract from R3.7 + R2.4.
3. Re-run the full existing `tests/integration/test_review.py` suite and assert every test still passes byte-identically post-fix. No existing test needs to change.

**Test Cases**:
1. **Envelope key set preservation** — invoke `review.py song-review` with no `--offset` flag. Assert `set(out.keys()) == {"path", "due_count", "offset"}` and `out["offset"] == 0`. This is a single new test; combined with the existing suite's per-key assertions it covers R3.7 completely.
2. **HTML byte-identity (existing tests)** — every existing test in `test_review.py` that renders without `--offset` (every test in the file today) SHALL continue to pass byte-identically. No modifications. Covers R3.1, R3.3, R3.4, R3.5.
3. **Zero-offset explicit form** — invoke `review.py song-review --offset 0` and assert the output HTML bytes are identical to an invocation with no `--offset` flag (same pinned epoch for both runs). Covers the R3.1 edge where `--offset 0` must behave as if the flag were absent.

### Edge Cases

- **Negative offset** (`--offset -3600`) — `learning.py due --offset -3600` already accepts negative offsets (per `test_due.py` and `learning.py`'s `type=int` with no lower bound); `review.py` mirrors this by reusing the same `type=int, default=0` kwargs. No dedicated test needed; the positive-offset parity test covers the mechanism and the argparse contract covers the signedness.
- **Non-integer offset** (`--offset abc`) — argparse's standard exit-2 usage error; no new error code (R2.6). Covered by argparse's built-in behaviour and the shared `type=int` contract with `learning.py due`, which already has this implicitly.
- **Offset = 0 explicitly passed vs. omitted** — both must produce byte-identical HTML. The `default=0` argparse wiring ensures `args.offset == 0` in both cases, and the byte-identity test in preservation case 3 nails this down.

### Unit Tests

No new unit tests required. `review.py` is driven end-to-end by integration tests in `tests/integration/test_review.py`; the fix is small enough that integration coverage is sufficient.

### Property-Based Tests

No new property-based tests required. `tests/integration/property/test_due_property.py` already exercises `learning.py due` across offset values; the learning-side `--offset` semantics are already property-verified. For `review.py`, the `learning_id` set-equality assertion in the fix-checking integration test (test case 1) binds review.py's row selection to learning.py's across the one DB+clock configuration we seed — the two scripts share the same `_DUE_SQL` predicate shape post-fix, so point-wise equivalence on one seeded configuration plus the existing property coverage of `learning.py due` transitively covers review.py's selection across the input domain.

### Integration Tests

- **Task 1 exploration test** (new): `review.py song-review --offset 86400` exits 0. Runs against an empty DB; asserts rc == 0 and stdout parses as JSON with `offset: 86400`.
- **Fix-checking test** (new): seed one learning row at the level-0 boundary, run both `learning.py due --offset 200` and `review.py song-review --offset 200`, extract the review payload via `_load_data_block`, assert set equality of `learning_id` vs `id` and that the seeded id appears in both.
- **Envelope key-set preservation test** (new): no-flag invocation returns envelope with key set exactly `{"path", "due_count", "offset"}` and `offset == 0`.
- **Existing tests** (unchanged): every test in `tests/integration/test_review.py` continues to pass byte-identically.

## Rollout

- No new CLI flags beyond `--offset` on the `song-review` subparser.
- No new error codes (R2.6 — argparse's standard exit-2 covers invalid integer).
- No schema change (R3.3).
- No template change (R3.2).
- No change to `scripts/_common.py` (R3.10) or `scripts/learning.py` (R3.6).
- Ships as v0.1.3 through the existing release pipeline; `release.md` update lands with the final commit (or as a separate `docs(release)` commit). This design document does not pin the release commit strategy.
