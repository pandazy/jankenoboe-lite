# Requirements Document

## Introduction

This spec adds a `leveldown` subcommand to `scripts/learning.py`. Today the
write surface for an existing learning record is `levelup` (advance one
step, or graduate at MAX_LEVEL) and `graduate` (mark done) — both move the
record forward only. Real review sessions are not monotonic: sometimes the
user looks at a song they last reviewed at stored level 17 and realises
they have forgotten it. They want to drop the record back to a lower level
(e.g. 10) and have the next due time follow that lower level's wait, not
the originally-scheduled wait at level 17.

The new op accepts a list of learning record ids and a single target
stored level, and for every id it sets `level = --to-level`,
`last_level_up_at = now_epoch`, and `updated_at = now_epoch`. The
target SHALL be strictly below each record's current level; rows at or
above are rejected before any write so the op stays unambiguously a
"forget" operation. Graduated rows are rejected the same way `levelup`
rejects them today — recovering a graduated song stays the job of
`learning.py batch` and the existing re-learn flow (parent R6.3).

This feature is additive: it introduces one new `learning.py` subcommand
(`leveldown`) and does not change the existing `batch`, `levelup`,
`graduate`, `due`, or `stats` ops. It reuses the parent
`anime-song-learning-app` spec's Success_Envelope / Error_Envelope
contract (R3), the BEGIN IMMEDIATE / COMMIT transaction wrapper that
`learning.py` already uses for write subcommands, and the
`display_level` rule (R17).

The skill doc `skills/reviewing-songs/SKILL.md` will be updated as part
of this feature's tasks so the agent driving the app knows when to use
`leveldown` (i.e. when the user says they forgot a song mid-review and
names a level to drop back to). The wording itself is out of this
requirements doc; the requirement is that the doc reflects the new op.

The HTML review page (`scripts/review.py` and
`scripts/review_template.html`) is **out of scope**. The page is a
static, JS-free file rendered for offline consumption — there is no
form post-back path. The agent learns the user's "I forgot" outcome
from chat and calls `leveldown` itself; no UI affordance is added.

This document reuses (does not re-state) the contracts defined by the
`anime-song-learning-app` spec, in particular:

- R1 (Portable Layout and DB Path) — the new op runs under the same
  `python scripts/learning.py ...` entry point, stdlib only, and
  reads/writes the same fixed DB_File.
- R2.2 (argparse subcommands) — `leveldown` is added as a peer
  subparser alongside `batch`, `levelup`, `graduate`, `due`, `stats`.
- R3 (Output Contract) — Success_Envelope on stdout (exit 0),
  Error_Envelope on stderr (exit 1), error codes drawn from the
  approved set.
- R6.5–R6.7 (the existing `levelup` semantics) — unchanged. `leveldown`
  is the mirror operation: same preflight ergonomics (NOT_FOUND on
  missing ids, ALREADY_GRADUATED on graduated ids — both abort the
  whole batch), same single-transaction guarantee, same per-row output
  shape.
- R6.3 (re-learn flow) — recovering a graduated song stays the job of
  `learning.py batch`. `leveldown` SHALL NOT un-graduate a row.
- R15 (Soft-Delete Visibility) — `leveldown` reads the song row only
  through the existing `learning` row's `song_id` reference; if the
  song is soft-deleted, the learning row is still addressable and the
  op SHALL behave the same as on a live song. (The same posture
  `levelup` and `graduate` take today.)
- R16 (Time Handling) — `now_epoch` is computed via the same
  `_common.now_epoch()` seam every other write op uses, so test-time
  pinning works without changes.
- R17 (Level Display) — `--to-level` is a stored (0-indexed) level.
  Output includes both `level` and `display_level = level + 1`.
- R18 (Test Coverage) — every acceptance criterion below SHALL have at
  least one example or property test that exercises it; the
  Error_Envelope codes used by this op (`INVALID_INPUT`, `NOT_FOUND`,
  `ALREADY_GRADUATED`) SHALL be triggered by integration tests.

## Glossary

Terms from the parent `anime-song-learning-app` spec (App_Root,
Script, DB_File, Song, Learning_Record, Level_Up_Path, Max_Level,
Graduated, Status_Normal, Soft_Delete, Success_Envelope,
Error_Envelope, Display_Level, now_epoch, Re_Learn_Level) apply here
as defined there. The terms below are specific to this spec.

- **Leveldown_Op**: The new `scripts/learning.py leveldown` subcommand
  introduced by this spec. Takes `--ids` (CSV of learning record ids)
  and `--to-level` (a single integer in `[0, Max_Level]`). Returns a
  Success_Envelope with an `updated` array, one entry per id, in the
  same order as the input.
- **Target_Level**: The integer value of `--to-level`, after argparse
  has parsed it as `int`. Domain: `[0, Max_Level]` inclusive. Out-of-
  range values SHALL be rejected with `INVALID_INPUT` before any DB
  read or write (see R-LD-2.3).
- **Source_Level**: For a given learning record, the stored `level`
  value at the moment `leveldown` reads it (i.e. before any write).
  This is the "where the record is coming from" value. Always in
  `[0, Max_Level]` by parent invariants.
- **Strictly_Below_Rule**: For `leveldown` to be valid for a given
  record, `Target_Level < Source_Level` SHALL hold. Equality
  (`Target_Level == Source_Level`) and going up
  (`Target_Level > Source_Level`) are both rejected with
  `INVALID_INPUT`. Rationale: `leveldown` is the "forget" operation;
  staying put or going up are different operations (a successful no-op
  is not "forgetting", and going up is `levelup`'s job).
- **Forget_Reset**: The set of writes `leveldown` performs on a record
  that passes preflight: `level = Target_Level`,
  `last_level_up_at = now_epoch`, `updated_at = now_epoch`. The
  `level_up_path`, `graduated`, `created_at`, `id`, and `song_id`
  columns SHALL NOT change.
- **Leveldown_Update_Entry**: One element of the `updated` array
  Leveldown_Op returns on success. Shape pinned in R-LD-3.2.
- **Preflight_Phase**: The pre-write validation Leveldown_Op runs
  before any UPDATE statement: parse `--to-level` into `Target_Level`,
  range-check it, parse `--ids`, look up each id, reject the whole
  batch on the first failure (missing id → `NOT_FOUND`; graduated id →
  `ALREADY_GRADUATED`; `Target_Level >= Source_Level` for any id →
  `INVALID_INPUT`). Mirrors `levelup`'s preflight (parent R6.7) so the
  ergonomics match.

## Requirements

### Requirement R-LD-1: New `leveldown` Subcommand on `learning.py`

**User Story:** As the user, I want one command that drops one or more
learning records back to a lower level when I realise I have forgotten
a song, so the next review of that song happens after the lower level's
wait period instead of the higher level's wait period.

#### Acceptance Criteria

1. THE `scripts/learning.py` Script SHALL expose an `argparse`
   subcommand named `leveldown` alongside the existing subcommands
   listed by parent R2 (`batch`, `levelup`, `graduate`, `due`,
   `stats`). The subcommand SHALL accept exactly two flags:
   `--ids CSV` (required, comma-separated learning record ids) and
   `--to-level N` (required, an integer parsed by argparse with
   `type=int`). It SHALL accept no positional arguments.
2. THE `leveldown` subcommand SHALL be addable to the script without
   renaming, removing, or altering any existing subcommand. The
   surface of `batch`, `levelup`, `graduate`, `due`, and `stats` SHALL
   remain identical to parent R6 / R7 / R17.
3. WHEN `leveldown` is invoked with `--ids` parsing to an empty list
   (e.g. `--ids ""` or `--ids ,,`), THE Script SHALL emit
   `{"updated": []}` and exit 0 without touching the DB beyond the
   preflight read. This matches `levelup`'s empty-list behavior.
   `--to-level` is still validated for type and range first (see
   R-LD-2.3); an out-of-range `--to-level` with empty `--ids` SHALL
   still yield `INVALID_INPUT` exit 1, because the CLI invocation is
   bad regardless of whether there is anything to update.
4. IF the caller passes any flag or positional argument not in the
   set `{--ids, --to-level, -h, --help}`, THE Script SHALL reject the
   invocation with argparse's usual `SystemExit(2)` path (argparse
   error), matching the behavior of every other `learning.py`
   subcommand when given an unknown flag.
5. THE `leveldown` op SHALL be a write subcommand. Per the existing
   `learning.py` `main()` pattern, it SHALL run inside a single
   `BEGIN IMMEDIATE` / `COMMIT` transaction; on any exception the
   transaction SHALL be rolled back. No partial writes ever survive a
   failed run.
6. THE `leveldown` op SHALL NOT print a Python traceback on stdout or
   stderr on a handled error. The Error_Envelope is the only failure
   output, per parent R3.7.

### Requirement R-LD-2: Preflight Validation

**User Story:** As the user, I want `leveldown` to validate the whole
batch before it writes anything, so a typo in one id (or a stale id
that has graduated) does not leave half my records in a half-updated
state.

#### Acceptance Criteria

1. THE Preflight_Phase SHALL run in this fixed order, and the FIRST
   failing check SHALL produce the corresponding Error_Envelope; no
   later checks run, no UPDATE statements run:
   1. argparse type-parses `--to-level` as `int` (out-of-range string
      → argparse `SystemExit(2)` per R-LD-1.4 behavior of unknown
      input).
   2. Range check: `0 <= Target_Level <= Max_Level`. Failure →
      `INVALID_INPUT`.
   3. Empty-`--ids` short-circuit (R-LD-1.3).
   4. Look up every id in `learning` by primary key. Any id missing →
      `NOT_FOUND` listing the missing ids.
   5. For every existing row, check `graduated == 0`. Any row with
      `graduated == 1` → `ALREADY_GRADUATED` listing the offending
      ids.
   6. For every existing row, check `Target_Level < Source_Level`
      (`row["level"]`). Any row failing → `INVALID_INPUT` listing the
      offending ids and, in `details`, each id's `level` and
      `display_level`. (The Strictly_Below_Rule rejection.)
2. WHEN Preflight_Phase fails at step 1.iv (`NOT_FOUND`), THE Error_
   Envelope SHALL list every missing id under
   `details.ids` (a JSON array of strings) and the message SHALL name
   how many were missing. Format mirrors `levelup`'s NOT_FOUND
   envelope verbatim.
3. WHEN Preflight_Phase fails at step 1.v (`ALREADY_GRADUATED`), THE
   Error_Envelope SHALL list every graduated id under `details.ids`
   and the message SHALL name how many were graduated. Format
   mirrors `levelup`'s ALREADY_GRADUATED envelope verbatim.
4. WHEN Preflight_Phase fails at step 1.vi (Strictly_Below_Rule), THE
   Error_Envelope's `details` SHALL include a `to_level` field with
   the requested target and an `offenders` array. Each `offenders`
   entry SHALL be `{"id": "<learning-id>", "level": <stored>,
   "display_level": <stored+1>}` so the operator can immediately see
   which rows were not strictly above the target. The message SHALL
   read along the lines of `"to_level (<N>) must be strictly below
   each record's current level; <K> id(s) failed"`.
5. WHEN Preflight_Phase fails at step 1.ii (range check), THE Error_
   Envelope's `details` SHALL include `to_level` and the inclusive
   bounds `{"min": 0, "max": Max_Level}` so the operator can see what
   range was expected. Message: `"--to-level <N> out of range
   [0, <Max_Level>]"` or equivalent.
6. THE Preflight_Phase SHALL NOT short-circuit at step 1.iv on
   partial overlap: even if some ids exist, if any id is missing the
   whole batch is rejected. The op is all-or-nothing. Mirrors
   `levelup`.
7. THE Preflight_Phase SHALL run inside the same BEGIN IMMEDIATE
   transaction as the writes. A preflight failure SHALL still
   ROLLBACK (a no-op rollback because no writes happened, but the
   transaction discipline is uniform with the existing `levelup`
   path).

### Requirement R-LD-3: Forget_Reset Semantics and Output

**User Story:** As the user, I want every record in a successful
`leveldown` call to come back at the target level with its review
clock reset to "now", so the next review is scheduled `wait_days[N]`
days from now (not from the original level-up time).

#### Acceptance Criteria

1. AFTER Preflight_Phase passes, FOR each id in the input order,
   Leveldown_Op SHALL execute one `UPDATE learning SET level = ?,
   last_level_up_at = ?, updated_at = ? WHERE id = ?` with
   `(Target_Level, now_epoch, now_epoch, id)`. The
   `level_up_path`, `graduated`, `created_at`, and `song_id` columns
   SHALL NOT be touched. (Forget_Reset.)
2. THE Success_Envelope SHALL be `{"updated": [Leveldown_Update_Entry,
   ...]}` with exactly one entry per input id, in input order. Each
   Leveldown_Update_Entry SHALL be a JSON object with these keys, in
   this order:
   - `id` — the learning record id (same as input).
   - `level` — the new stored level (equals Target_Level).
   - `display_level` — `level + 1`, per parent R17.1.
   - `graduated` — always `0` here. Surfaced for parsing parity with
     `levelup` / `graduate` outputs (which also emit `graduated`).
   - `previous_level` — the Source_Level the record was read at
     during preflight. Stored level (0-indexed). `previous_display_
     level` is NOT emitted (callers can compute it; the spec keeps
     the entry small).
   - `last_level_up_at` — `now_epoch`.
   - `updated_at` — `now_epoch`.
   Key order is fixed by the dict construction in Python 3.10+ so
   tests can byte-diff the stdout.
3. ALL `now_epoch` values within one Leveldown_Op invocation SHALL
   be identical — the op SHALL compute `now_epoch` exactly once at
   the top of the write phase and reuse it for every UPDATE and every
   output entry. Same convention `levelup` uses.
4. THE `previous_level` field on each Leveldown_Update_Entry SHALL
   reflect the value read in preflight, NOT a re-read after the
   UPDATE. Rationale: a re-read after the UPDATE would always be
   equal to `Target_Level`, defeating the purpose of the field.
5. WHEN multiple ids in the input refer to the same `song_id` (the
   data glitch documented in `search-enhancements`'s
   `duplicate_active_learning` warning), THE Leveldown_Op SHALL
   still update each row independently — the spec does not consult
   the song graph. `level_up_path` is a per-row column; the writes
   do not interact.
6. THE Leveldown_Op SHALL NOT modify any column on any other table
   (`song`, `artist`, `show`, `play_history`, `rel_show_song`,
   `learning` rows whose ids are not in `--ids`). The Forget_Reset
   touches only the listed `learning` rows.
7. THE Leveldown_Op SHALL NOT change a record's `graduated` column.
   A graduated row is rejected at preflight (R-LD-2 step 1.v), so
   no graduated row ever reaches the write phase. Recovering a
   graduated song remains the job of `learning.py batch` per parent
   R6.3.

### Requirement R-LD-4: Interaction with the Due Selector

**User Story:** As the user, I want the next-due time of a leveled-
down record to follow the target level's wait, so the song reappears
in the review queue after `wait_days[Target_Level]` days from the
forget event.

#### Acceptance Criteria

1. THE Leveldown_Op SHALL NOT change the parent `Due_SQL_Condition`
   (parent Glossary). The condition already keys off
   `(level, level_up_path, last_level_up_at)`, all three of which the
   op sets correctly via Forget_Reset.
2. AFTER a successful Leveldown_Op on a record `R` at `Target_Level
   = N`, the next call to `learning.py due` SHALL include `R` in its
   results iff `Due_SQL_Condition` evaluates to true for `R` —
   i.e. `level_up_path[N] * 86400 + now_epoch <= strftime('%s','now')
   + @offset` (using the level > 0 clause when `N > 0`, or the
   `last_level_up_at > 0 AND level = 0` 5-minute clause when
   `N == 0`). The op does not need to special-case `N == 0`; setting
   `last_level_up_at = now_epoch` makes the level-0 clause work
   correctly because `last_level_up_at > 0` (R16.2 guarantees
   `now_epoch > 0` for any real run).
3. THE Leveldown_Op SHALL NOT pre-read or pre-render `due`. Its only
   responsibility is the Forget_Reset write. The next `due` run
   computes due-ness on the new state.

### Requirement R-LD-5: Skill Documentation Update

**User Story:** As an operator (or an LLM working from the shipped
skill docs), I want the new `leveldown` op to be documented in
`skills/reviewing-songs/SKILL.md`, so the review workflow guide
reflects what the library actually supports and the agent knows
when to call it.

#### Acceptance Criteria

1. THE file `skills/reviewing-songs/SKILL.md` SHALL be updated under
   step 4 ("For each song the user reviews:") to add a new
   sub-bullet for the "user forgot a song" outcome that names
   `learning.py leveldown --ids L1,L2,... --to-level N`, the
   strictly-below rule, and the fact that `last_level_up_at` is
   reset to `now_epoch` so the next review is scheduled from the
   forget event.
2. THE SKILL.md update SHALL document, in the same Notes section
   that already lists the `levelup`/`graduate` invariants, that
   `leveldown` rejects graduated rows (mirrors `levelup`'s
   `ALREADY_GRADUATED` rejection) — to recover a graduated song the
   agent uses `learning.py batch` per parent R6.3.
3. THE SKILL.md update SHALL NOT remove or alter the existing
   guidance for `levelup`, `graduate`, `due`, `batch`, or
   `learning-detail`. It SHALL add `leveldown` as a new sub-bullet
   under step 4 and a complementary line in Notes, not replace any
   existing bullet.
4. THE SKILL.md update SHALL be shipped in the same change that
   introduces `leveldown`. THE feature is not considered delivered
   with R-LD-1..R-LD-4 in place but the skill doc still listing
   only `levelup` and `graduate` for the per-song outcomes.

## Correctness Properties for Property-Based Testing

These properties extend the parent `anime-song-learning-app` spec's
"Correctness Properties" rules: temp `App_Root` per test, stdlib
`random.Random(seed)` with a fixed seed (no `hypothesis`, per parent
R18), and integration tests drive scripts via `subprocess.run`.
`now_epoch` is pinned via the test-seam env var (parent R18.13) so
timing-dependent assertions are stable. Each property below is
testable on top of the existing
`tests/integration/conftest.py` seeders (`insert_learning`, etc.).

### Property P-LD-1: Forget_Reset Touches Exactly The Three Columns

For any seeded learning record `R` with `R.graduated == 0`, any
`Target_Level T` such that `0 <= T < R.level`, after
`learning.py leveldown --ids R.id --to-level T`:

1. `R.level == T`.
2. `R.last_level_up_at == now_epoch`.
3. `R.updated_at == now_epoch`.
4. `R.graduated == 0` (unchanged).
5. `R.level_up_path == <pre-call value>` (unchanged, byte-identical
   JSON string).
6. `R.created_at == <pre-call value>` (unchanged).
7. `R.id == <pre-call value>` (unchanged).
8. `R.song_id == <pre-call value>` (unchanged).
9. No other learning row in the DB SHALL change in any column.
10. No row in `song`, `artist`, `show`, `play_history`, or
    `rel_show_song` SHALL change.

**Validates: R-LD-3.1, R-LD-3.6, R-LD-3.7**

### Property P-LD-2: Strictly_Below_Rule Rejects Equal Or Greater

For any seeded learning record `R` with `R.graduated == 0` and any
target `T` with `T >= R.level` and `0 <= T <= Max_Level`:

1. `learning.py leveldown --ids R.id --to-level T` exits 1 with an
   Error_Envelope `code == "INVALID_INPUT"`.
2. The DB is byte-identical before and after the call (including
   `R.updated_at` — the timestamp is NOT bumped on a rejected call).
3. The Error_Envelope's `details.offenders` array contains an entry
   for `R.id` with `level == R.level` and `display_level == R.level
   + 1`.
4. The Error_Envelope's `details.to_level == T`.

**Validates: R-LD-2.1 (step 1.vi), R-LD-2.4, R-LD-3.7**

### Property P-LD-3: Graduated Rows Are Rejected, Untouched

For any seeded learning record `R` with `R.graduated == 1` and any
valid `Target_Level T` in `[0, Max_Level]`:

1. `learning.py leveldown --ids R.id --to-level T` exits 1 with
   `code == "ALREADY_GRADUATED"`.
2. The DB is byte-identical before and after the call.
3. The Error_Envelope's `details.ids` contains `R.id`.

**Validates: R-LD-2.1 (step 1.v), R-LD-2.3, R-LD-3.7**

### Property P-LD-4: Batch All-Or-Nothing

For any seeded set of learning records `R_1..R_k` with mixed states
(some active, some graduated, some at the target's level or below)
and any `Target_Level T`:

1. IF any `R_i` would fail any preflight check (missing,
   graduated, or `T >= R_i.level`), THEN every `R_j` (including the
   ones that would have passed) SHALL be byte-identical before and
   after the call. No partial writes.
2. The Error_Envelope's `code` SHALL be the code of the first
   failing preflight step in the order pinned by R-LD-2.1: NOT_FOUND
   beats ALREADY_GRADUATED beats Strictly_Below_Rule.

**Validates: R-LD-2.1 (ordering), R-LD-2.6, R-LD-2.7, R-LD-1.5
(rollback)**

### Property P-LD-5: Leveldown Then Levelup Round-Trip

For any seeded learning record `R` with `R.graduated == 0` and
`R.level >= 2`, picking `T = R.level - 2`:

1. After `leveldown --ids R.id --to-level T`, then
   `levelup --ids R.id`, `R.level == T + 1`.
2. After both calls, `R.last_level_up_at == now_epoch_of_levelup`
   (the second call's epoch, not the leveldown's).
3. After both calls, `R.graduated == 0` (T + 1 is still strictly
   below Max_Level by the precondition).

**Validates: R-LD-3.1, parent R6.5 / R6.6 compatibility**

### Property P-LD-6: Due-After-Leveldown Tracks The Lower Wait

For any seeded learning record `R` with `R.graduated == 0` and
`R.level >= 1`, picking `T` in `[0, R.level - 1]`:

1. Immediately after `leveldown --ids R.id --to-level T` at pinned
   epoch `E`, `learning.py due --offset 0` SHALL NOT include `R.id`
   in its results (the next-due time is `E + level_up_path[T] *
   86400`, strictly greater than `E` for `T >= 1`; for `T == 0` the
   level-0 clause's 300-second window applies and `R` is also not
   yet due at offset 0).
2. With `--offset (level_up_path[T] * 86400)` for `T >= 1`, OR
   `--offset 300` for `T == 0`, `learning.py due` SHALL include
   `R.id` (boundary case: `=` is due, per parent Due_SQL_Condition).
3. The `level_up_path` JSON on `R` is unchanged across the call, so
   `wait_days` reported by `due` for `R` after the leveldown equals
   the `T`-th entry of the original path.

**Validates: R-LD-3.1, R-LD-4.1, R-LD-4.2**

### Note on Non-Property Tests

Per parent R18 and the "When NOT to Use Property-Based Testing"
guidance, the following are covered by example-style integration
tests rather than property tests:

- Out-of-range `--to-level` (negative, `>Max_Level`, missing) →
  `INVALID_INPUT` exit 1 with the `min`/`max` echo (R-LD-2.1 step
  1.ii, R-LD-2.5).
- Missing required flag (`--ids` or `--to-level` absent) → argparse
  `SystemExit(2)` (R-LD-1.4).
- Empty `--ids` → exit 0 with `{"updated": []}` and no DB writes
  (R-LD-1.3).
- Non-integer `--to-level` (e.g. `--to-level abc`) → argparse
  `SystemExit(2)` (R-LD-1.4).
- Skill doc update (R-LD-5) — file-content assertion, not a
  property.

## Out of Scope for This Spec

The following items are explicitly out of scope for
`learning-leveldown` and SHALL NOT be introduced as part of
implementing R-LD-1..R-LD-5:

1. A "level-down by N steps" form of the flag (`--steps N` /
   `--by N`). The CLI takes one absolute target level for the
   whole batch via `--to-level N`. Per-id targets and per-call
   step deltas are follow-up specs if a real workflow needs them.
2. Un-graduating a record (clearing `graduated = 1` back to `0`).
   Recovering a graduated song stays the job of `learning.py batch`
   and the existing re-learn flow (parent R6.3); inserting a fresh
   row at `Re_Learn_Level` keeps the per-cycle history clean.
3. Changes to the `Due_SQL_Condition` (parent Glossary) or to
   `learning.py due`. The op writes `level`, `last_level_up_at`,
   and `updated_at`; the existing condition handles those columns
   unchanged.
4. Changes to `scripts/review.py` or `scripts/review_template.html`
   to surface a "forget" affordance in the review HTML. The page is
   a static, JS-free file; the forget outcome is communicated to
   the agent via chat and the agent calls `leveldown` directly.
5. A "set level to anything" op (e.g. allowing `Target_Level >=
   Source_Level`). The Strictly_Below_Rule pins this op to the
   "forget" semantic; arbitrary level edits remain `data.py` /
   merge-style territory and would defeat the named operation.
6. A history table or audit log of forget events. The
   `previous_level` field on the Leveldown_Update_Entry is the only
   trace; downstream callers who want a durable log can capture
   the Success_Envelope.
7. Changes to the parent `level_up_path` easing function or to its
   default value. The path stays attached to each row at create
   time and is not rewritten on `leveldown`.
8. Bulk forms keyed off non-id criteria (e.g. "level down every row
   above level 15"). The op takes explicit ids only; bulk patterns
   are the caller's responsibility (e.g. `query.py list-learning`
   followed by `leveldown --ids ...`).
