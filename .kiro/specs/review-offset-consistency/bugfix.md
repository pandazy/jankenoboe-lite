# Bugfix Requirements Document

## Introduction

The two "due" surfaces in `scripts/` disagree about which clock they can see. `scripts/learning.py due` accepts `--offset N` (an integer of seconds) and threads `+ :offset` into every `CAST(strftime('%s','now') AS INTEGER)` comparison in its `_DUE_SQL`, so a caller can ask "what will be due in N seconds." `scripts/review.py song-review`, which renders the HTML review page, carries a near-copy of the same SQL but omits the `+ :offset` term in all three time-comparison branches and exposes no `--offset` flag — so it can only ever render "due right now." The symptom is an asymmetric surface: an agent planning tomorrow's reviews can count rows with `learning.py due --offset 86400` but cannot render the corresponding HTML page, because `review.py song-review` has no way to express the same time shift. The fix is additive and narrow: add `--offset N` (integer seconds, default 0) to `review.py song-review`, plumb it through `review.py`'s `_DUE_SQL` in the same three places `learning.py` already plumbs it, bind `{"offset": int(args.offset)}`, and surface the field in the response envelope alongside `path` and `due_count`. The `_DUE_SQL` duplication between the two scripts stays as-is; deduplication is explicitly out of scope.

## Bug Analysis

### Current Behavior (Defect)

Today, `review.py song-review` cannot express any time intent other than "exactly wall-clock now," and the Due_SQL_Condition it runs diverges from the one `learning.py due` runs whenever a non-zero offset would matter.

1.1 WHEN a caller invokes `scripts/review.py song-review` THEN the script exposes no `--offset` flag and rejects `--offset N` as an unrecognised argument
1.2 WHEN `review.py`'s `_DUE_SQL` runs THEN each of the three `CAST(strftime('%s', 'now') AS INTEGER)` comparisons is evaluated without a `+ :offset` term, so the selected row set cannot be shifted relative to SQLite's current clock
1.3 WHEN an agent wants to preview tomorrow's review as rendered HTML (for example, to plan the next day's session) THEN the agent can see the row count via `learning.py due --offset 86400` but has no way to render the corresponding HTML page for those rows
1.4 WHEN an agent reads `skills/reviewing-songs/SKILL.md` and sees that `learning.py due` accepts `--offset` THEN the agent reasonably expects `review.py song-review` to accept the same flag with the same semantics, and the CLI asymmetry between the two "due" surfaces is confusing
1.5 WHEN the response envelope from `review.py song-review` is inspected THEN it carries only `path` and `due_count` and has no field that records the time shift the payload was computed against

### Expected Behavior (Correct)

After the fix, `review.py song-review --offset N` behaves identically to `learning.py due --offset N` on the time-comparison axis, the envelope records the shift, and the rendered HTML reflects the shifted row set.

2.1 WHEN a caller invokes `scripts/review.py song-review --offset N` for any integer N (default 0 when the flag is omitted) THEN the script SHALL accept the flag and parse N as an integer with the same argparse semantics `learning.py due` uses
2.2 WHEN `review.py`'s `_DUE_SQL` runs THEN the query SHALL add `+ :offset` to every `CAST(strftime('%s', 'now') AS INTEGER)` comparison — in the level-0-with-last_level_up_at branch, the level-0-without-last_level_up_at branch, and the level > 0 branch — in the same three places `learning.py`'s `_DUE_SQL` already carries that term, and SHALL bind the query with `{"offset": int(args.offset)}`
2.3 WHEN `review.py song-review --offset N` and `learning.py due --offset N` are executed against the same database state and wall clock THEN the set of `learning_id` values in the rendered payload's `due_songs[*].learning_id` SHALL equal the set of `id` values returned by `learning.py due --offset N`'s `results` array
2.4 WHEN `review.py song-review --offset N` succeeds THEN the response envelope SHALL include an integer `offset` field alongside the existing `path` and `due_count` fields, carrying the same integer value that was passed on the command line (0 when omitted)
2.5 WHEN `review.py song-review --offset N` renders the HTML page THEN the rendered HTML bytes SHALL reflect the rows the Due_SQL_Condition selects at `now + N`, which is the same row set `learning.py due --offset N` would return under the same clock and database state
2.6 WHEN a caller invokes `scripts/review.py song-review --offset N` with a non-integer N THEN the script SHALL exit with argparse's standard exit-2 usage-error behavior, matching `learning.py due`'s behavior in the same situation (no new error code is introduced)

### Unchanged Behavior (Regression Prevention)

The following surfaces must be byte-identical to v0.1.2 after the fix, with the one exception that the envelope gains an `offset` field.

3.1 WHEN `scripts/review.py song-review` is invoked with no `--offset` flag (or with `--offset 0`) on a given database state and wall clock THEN the rendered HTML bytes at `App_Root/output/review_<EPOCH>.html` SHALL CONTINUE TO be identical to the bytes v0.1.2 would produce under the same inputs
3.2 WHEN the HTML template at `scripts/review_template.html` is read THEN the file SHALL CONTINUE TO be byte-identical to v0.1.2
3.3 WHEN the Due_Data_Payload is built THEN the schema SHALL CONTINUE TO carry `generated_at`, `due_count`, `due_songs`, and every per-song field (`learning_id`, `song_id`, `song_name`, `song_name_context`, `artist_id`, `artist_name`, `artist_name_context`, `display_level`, `shows`) with the same semantics and types as v0.1.2; per-show entries SHALL CONTINUE TO carry `show_id`, `show_name`, `show_name_romaji`, `show_vintage`, `show_s_type`, and `media_urls` with the same semantics
3.4 WHEN `_build_payload` runs THEN it SHALL CONTINUE TO operate on exactly the rows the Due_SQL_Condition selects, with no additional filtering, reordering, or projection
3.5 WHEN `_render_page` and `_escape_json_for_html` are invoked with the same inputs as v0.1.2 THEN their outputs SHALL CONTINUE TO be byte-identical
3.6 WHEN `scripts/learning.py due` is invoked THEN its flag surface, `_DUE_SQL` text, binding dict, response envelope (`results` and `offset`), and row ordering SHALL CONTINUE TO be byte-identical to v0.1.2 (the learning-side `--offset` support is already correct and is not touched)
3.7 WHEN the response envelope from `review.py song-review` is produced THEN the existing `path` and `due_count` fields SHALL CONTINUE TO carry their v0.1.2 values (absolute output path string and integer count of due songs in the payload)
3.8 WHEN `review.py` writes its output file THEN the filename `App_Root/output/review_<EPOCH>.html` SHALL CONTINUE TO use `_common.now_epoch()` for the `<EPOCH>` component — that is, the filename records when the file was written, not the logical "as of" time the payload represents (which may be shifted by `--offset`)
3.9 WHEN the two "due" SQL statements in `scripts/learning.py` and `scripts/review.py` are compared THEN the duplication SHALL CONTINUE TO exist (deduplication into `_common.py` or elsewhere is explicitly out of scope for this fix)
3.10 WHEN `scripts/_common.py` is inspected THEN it SHALL CONTINUE TO be byte-identical to v0.1.2
3.11 WHEN the Due_SQL_Condition itself is evaluated THEN its semantics SHALL CONTINUE TO be unchanged beyond the ability to shift the "now" it compares against — no threshold, branch, ordering, or join is altered

## Deriving the Bug Condition

Let `ReviewInvocation` describe one invocation of `scripts/review.py song-review`, carrying the command-line arguments and the database + wall-clock state at invocation time. The caller's time intent is the integer number of seconds by which the caller wants to shift the "now" the Due_SQL_Condition compares against (0 for "right now," 86400 for "one day ahead," etc.).

### Bug Condition

```pascal
FUNCTION isBugCondition(invocation)
  INPUT:  invocation of type ReviewInvocation
  OUTPUT: boolean

  // The bug manifests when the caller wants a non-zero time-shifted
  // view of "due" — the same shift `learning.py due --offset N` would
  // compute for N ≠ 0 — but the invocation has no way to express it
  // because `--offset` is absent on the song-review subcommand.
  RETURN invocation.desiredOffsetSeconds ≠ 0
END FUNCTION
```

In v0.1.2 the set of expressible `ReviewInvocation` values is exactly `{ invocation : invocation.desiredOffsetSeconds = 0 }`, so every buggy input is literally unrepresentable on the command line today — the defect is the absence of a syntactic surface for non-zero offsets, plus the corresponding absence of the `+ :offset` term in the SQL that would honour it.

### Fix-Checking Property

Let `F` be `review.py song-review` in v0.1.2 (no `--offset` flag, `_DUE_SQL` without the `+ :offset` terms) and `F'` be `review.py song-review` after the fix. Let `learningDueIds(N, db, clock)` denote the set of `id` values in the `results` array of `learning.py due --offset N`'s Success_Envelope against database state `db` at wall clock `clock`. Let `reviewDueIds(N, db, clock)` denote the set of `learning_id` values in the Due_Data_Payload's `due_songs` array produced by `F'` invoked with `--offset N` against the same `db` and `clock`.

```pascal
// Property: Fix Checking — review.py's offset semantics match learning.py's.
FOR ALL invocation WHERE isBugCondition(invocation) DO
  N      ← invocation.desiredOffsetSeconds
  db     ← invocation.database
  clock  ← invocation.wallClock

  reviewResult ← F'(invocation)                         // --offset N accepted
  ASSERT reviewResult.exitCode = 0
  ASSERT reviewResult.envelope.offset = N               // echoed back as int
  ASSERT reviewDueIds(N, db, clock)
         = learningDueIds(N, db, clock)                 // same SET of ids
END FOR
```

Set equality (not sequence equality) is the assertion, because `review.py`'s payload orders by `level DESC, id ASC` while `learning.py`'s results are also ordered by `level DESC, id ASC`; the two orderings should agree, but the property that matters for the fix is that the same rows are selected.

### Preservation Goal

For every invocation the caller could already express in v0.1.2 — that is, every invocation whose intent is "exactly wall-clock now" — the fixed script must be byte-identical to the original, except that the response envelope gains one new integer field `offset` with value `0`.

```pascal
// Property: Preservation Checking — zero-offset behaviour is unchanged.
FOR ALL invocation WHERE NOT isBugCondition(invocation) DO
  // i.e. invocation.desiredOffsetSeconds = 0

  before ← F(invocation)                                // v0.1.2
  after  ← F'(invocation)                               // post-fix, --offset
                                                        // absent or = 0

  ASSERT after.htmlBytes             = before.htmlBytes
  ASSERT after.envelope.path         = before.envelope.path
  ASSERT after.envelope.due_count    = before.envelope.due_count
  ASSERT after.envelope.offset       = 0                // new field only
  ASSERT keys(after.envelope) \ keys(before.envelope) = {"offset"}
  ASSERT keys(before.envelope) \ keys(after.envelope) = {}
END FOR
```

Here `F` denotes the v0.1.2 script and `F'` denotes the post-fix script; `keys(...)` denotes the set of top-level keys in the Success_Envelope. The `htmlBytes` equality is byte-level — the template is untouched (3.2), the payload schema is unchanged (3.3), `_build_payload` still operates on the same row set when offset is zero (3.4, 3.11), and `_render_page` / `_escape_json_for_html` are byte-identical (3.5), so the rendered file bytes match exactly. The only permitted difference in the caller-observable surface is the single new `offset` integer field in the envelope.
