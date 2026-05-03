# Bugfix Requirements Document

## Introduction

The three-branch time-comparison predicate that defines "is this learning
record due?" currently lives as duplicated SQL text inside two scripts:
`scripts/learning.py` (the `_DUE_SQL` used by `learning.py due`) and
`scripts/review.py` (the `_DUE_SQL` used by `review.py song-review`). The
same nine lines of `(...) OR (...) OR (...)` exist in both files. The
duplication has already drifted once: v0.1.2 shipped `review.py` without
the `+ :offset` term in any of the three branches while `learning.py`
had it in all three, which v0.1.3 patched by copying the term back in.
Two copies can drift; they already did. The fix is to extract the
predicate text to a single module-level string constant in
`scripts/_common.py` and have both callers compose their full SQL by
interpolating that constant (Python-side f-string or `.format()`) while
keeping every other piece of their queries — SELECT lists, FROM/JOIN,
status filters, ORDER BY — exactly as they are. The `:offset` binding
stays a bound parameter, not an interpolated string. The `l`/`s`/`a`
table aliases stay pinned as part of the extracted predicate's contract.

## Bug Analysis

### Current Behavior (Defect)

The defect is structural — a duplication of SQL text that has already
caused one drift regression and is certain to cause another if the
predicate semantics ever change again.

1.1 WHEN a developer reads `scripts/learning.py` THEN the system contains
the full nine-line three-branch due-time predicate as literal text
inside `learning.py._DUE_SQL`.

1.2 WHEN a developer reads `scripts/review.py` THEN the system contains
the same full nine-line three-branch due-time predicate as literal text
inside `review.py._DUE_SQL`.

1.3 WHEN a future change needs to adjust the due-time semantics (for
example, change the 300-second level-0 threshold, add a fourth branch,
or alter the `+ :offset` placement) THEN the system requires the change
to be applied to both files in lockstep to stay correct.

1.4 WHEN two copies of the predicate exist and a change lands in only
one of them THEN the system silently diverges between
`learning.py due` and `review.py song-review` — this is exactly what
happened between v0.1.2 and v0.1.3, where `review.py` was missing the
`+ :offset` terms in all three branches while `learning.py` had them,
so `--offset` was silently a no-op on the review page for one release.

1.5 WHEN a developer asks "what is the one source of truth for the
due-time condition?" THEN the system has no answer — there are two
independent textual copies and no single definition either refers to.

### Expected Behavior (Correct)

After the fix, the predicate text exists in exactly one file and both
callers compose their SQL from it.

2.1 WHEN a developer reads `scripts/_common.py` THEN the system SHALL
contain the full three-branch due-time predicate as a single
module-level string constant (the single source of truth).

2.2 WHEN a developer searches `scripts/**/*.py` for the predicate text
(modulo whitespace) THEN the system SHALL return exactly one match,
located in `scripts/_common.py`.

2.3 WHEN `learning.py` defines `_DUE_SQL` THEN the system SHALL compose
the full query by interpolating the shared constant from `_common.py`
into its own SELECT / FROM / WHERE / ORDER BY skeleton using Python-side
string formatting (f-string or `.format()`).

2.4 WHEN `review.py` defines `_DUE_SQL` THEN the system SHALL compose
the full query by interpolating the shared constant from `_common.py`
into its own SELECT / FROM / WHERE / ORDER BY skeleton using Python-side
string formatting (f-string or `.format()`).

2.5 WHEN either caller executes its composed `_DUE_SQL` THEN the system
SHALL pass `:offset` as a bound parameter (via `conn.execute(sql,
{"offset": int(args.offset)})`), not as an interpolated string.

2.6 WHEN the shared predicate references the learning table THEN the
system SHALL assume the alias `l` — the predicate's contract pins the
alias, and callers SHALL continue to alias `learning` as `l` and `song`
as `s` (with `review.py` additionally aliasing `artist` as `a`) exactly
as they do today.

### Unchanged Behavior (Regression Prevention)

Everything outside the extracted predicate must stay byte-identical to
v0.1.3. The fix is purely structural.

3.1 WHEN `learning.py due` runs against any DB state and any `--offset`
value THEN the system SHALL CONTINUE TO return the same row set, in the
same `ORDER BY l.level DESC, l.id ASC` order, with the same
`{"results": [...], "offset": N}` envelope shape, as v0.1.3.

3.2 WHEN `review.py song-review` runs against any DB state and any
`--offset` value THEN the system SHALL CONTINUE TO return the same row
set driving the payload, in the same `ORDER BY l.level DESC, l.id ASC`
order, with the same `{"path": ..., "due_count": N, "offset": N}`
envelope shape, as v0.1.3.

3.3 WHEN `learning.py._DUE_SQL` builds its SELECT list THEN the system
SHALL CONTINUE TO select exactly the nine fields it selects today
(`l.id`, `l.song_id`, `s.name AS song_name`, `l.level`,
`(l.level + 1) AS display_level`, the `wait_days` expression,
`l.last_level_up_at`, `l.updated_at`, `l.graduated`).

3.4 WHEN `review.py._DUE_SQL` builds its SELECT list THEN the system
SHALL CONTINUE TO select exactly the eleven fields it selects today
(learning_id, song_id, song_name, song_name_context, artist_id,
artist_name, artist_name_context, level, display_level, wait_days).

3.5 WHEN either script's query filters non-time WHERE clauses THEN the
system SHALL CONTINUE TO apply its existing filters unchanged —
`learning.py` keeps `s.status = 0 AND l.graduated = 0`, and
`review.py` keeps `s.status = 0 AND a.status = 0 AND l.graduated = 0`.
The asymmetry (learning.py does NOT filter `a.status = 0` today; review.py
does) SHALL CONTINUE TO exist; that asymmetry may be a separate bug but
is explicitly out of scope here.

3.6 WHEN either script's query joins tables THEN the system SHALL
CONTINUE TO use the exact FROM/JOIN shape it uses today —
`learning.py` joins `song s` only; `review.py` joins `song s` and
`artist a`.

3.7 WHEN `review.py` renders the Review_Page THEN the system SHALL
CONTINUE TO produce byte-identical HTML bytes to v0.1.3 for the same
input — the HTML template `scripts/review_template.html` is not
modified, and the `_build_payload` call site and JSON escape pipeline
are not modified.

3.8 WHEN the full test suite runs THEN the system SHALL CONTINUE TO
pass every existing test unchanged — including
`tests/integration/test_due.py`, `tests/integration/test_review.py`,
and `tests/integration/property/test_due_property.py`. No test's
assertions should need to be edited for behavior; the property test's
inline `DUE_SQL` literal is also independent evidence of the predicate
and SHALL CONTINUE TO match byte-for-byte what `_common.py` exposes.

3.9 WHEN `_common.py` is loaded THEN the system SHALL CONTINUE TO use
only the Python 3.10+ standard library — no new imports are added to
support the shared constant; the constant is a plain string literal.

3.10 WHEN either script binds query parameters THEN the system SHALL
CONTINUE TO use the single `{"offset": int(args.offset)}` dict it uses
today — the bind contract is unchanged.

3.11 WHEN skill documents or developer documentation reference the
due-time condition THEN the system SHALL CONTINUE TO reference them as
they are today; skill docs under `skills/` are not modified.

## Deriving the Bug Condition

This bug is unusual in that its condition is a static property of the
source tree, not a runtime property of a particular invocation. The
predicate text exists in source either once or more than once; the
defect is "more than once".

**Bug Condition Function** — identifies a defective codebase state:

```pascal
FUNCTION isBugCondition(codebase)
  INPUT:  codebase of type SourceTree
  OUTPUT: boolean

  // True iff the three-branch due-time predicate appears as text
  // (modulo whitespace) in more than one source file under scripts/.
  RETURN countOccurrences(codebase, DUE_TIME_PREDICATE_TEXT) > 1
END FUNCTION
```

Concrete counterexample (the state the codebase is in today, v0.1.3):
- `scripts/learning.py` contains the predicate inside `_DUE_SQL`.
- `scripts/review.py` contains the predicate inside `_DUE_SQL`.
- `countOccurrences(...) = 2`, so `isBugCondition(codebase) = true`.

**Key Definitions:**
- **F**: the codebase at v0.1.3, in which the predicate text appears in
  two files.
- **F'**: the fixed codebase, in which the predicate text appears in
  exactly one file (`scripts/_common.py`) and both callers compose
  their SQL by interpolating that constant.

**Fix-Checking Property** — defines the expected post-fix state:

```pascal
// Property: Fix Checking - Single Source of Truth
FOR codebase = F' DO
  ASSERT countOccurrences(codebase, DUE_TIME_PREDICATE_TEXT) = 1
  ASSERT theSingleOccurrence IS in "scripts/_common.py"
  ASSERT learning.py._DUE_SQL COMPOSES shared constant VIA interpolation
  ASSERT review.py._DUE_SQL   COMPOSES shared constant VIA interpolation
END FOR
```

In plain terms: after the fix, a full-text search across
`scripts/**/*.py` for the three-branch predicate returns exactly one
hit, inside `_common.py`, and both callers build their full `_DUE_SQL`
by interpolating that constant into their own SELECT / FROM / WHERE /
ORDER BY skeletons. Python-side string formatting into a SQL constant
is acceptable here because the constant is static text and the only
moving part (`:offset`) remains a bound parameter.

**Preservation Goal** — for every non-buggy dimension, F' must be
indistinguishable from F at the observable boundary:

```pascal
// Property: Preservation Checking - Byte-Identical Behavior
FOR ALL (dbState, offset) DO
  ASSERT learning_due(F, dbState, offset) = learning_due(F', dbState, offset)
  ASSERT review_song_review(F, dbState, offset)
       = review_song_review(F', dbState, offset)  // byte-identical HTML
  ASSERT full_test_suite(F) = full_test_suite(F')  // same pass/fail set
END FOR
```

In plain terms: every row `learning.py due` returns, every envelope it
emits, every byte `review.py song-review` writes to
`output/review_<epoch>.html`, and every assertion the existing test
suite makes, all must be byte-identical between v0.1.3 and the fixed
codebase. The only difference between F and F' lives in the source
tree, not at the observable boundary.
