# Requirements Document

## Introduction

This spec adds a new runtime script, `scripts/init_db.py`, that creates an
empty `App_Root/db/datasource.db` when one does not exist, and is a safe
no-op when one already does. It extends the `anime-song-learning-app`
spec; every runtime rule from that spec still holds (Python 3.10+,
stdlib-only under `scripts/`, self-locating `App_Root`, JSON I/O, POSIX
exit codes).

### Motivation

The parent spec's Requirement 1.5 says: if `App_Root/db/datasource.db`
does not exist, every Script prints an Error_Envelope with
`code = "DB_NOT_FOUND"` and exits 1. That is a hard dead end on a
fresh host — the user has no first-party way to create the file. The
packaged zip (parent R20.2) ships an empty schema-only DB so that the
happy path works on unzip, but the zip cannot help a user who deletes
the DB by accident, and the user can't run the tool at all before the
package step has been taken.

`scripts/init_db.py` fills that gap. It is the canonical way to recover
from `DB_NOT_FOUND` on a clean host, and it composes cleanly with the
packaging path: the same DDL used by `tools/package.py._empty_db`
(parent R20.2's "built from `tests/fixtures/schema.sql`") is the DDL
`init_db.py` applies at runtime.

Every skill under `skills/*/SKILL.md` runs `init_db.py` as its first
step so Claude never hits `DB_NOT_FOUND` on a fresh deploy. The Script
must therefore make the skip path as cheap as possible — see
Requirement I-5.

### Relation to parent spec

- **R1.5 (`DB_NOT_FOUND`)** — this feature is the first-party recovery
  path. After `init_db.py` runs successfully, a subsequent invocation
  of any other Script no longer hits R1.5.
- **R1.2 (stdlib-only runtime)** — `init_db.py` lives under `scripts/`
  and so is bound by this rule. It uses only `sqlite3`, `argparse`,
  `pathlib`, `json`, `sys`, and friends from the Python standard
  library.
- **R2.1 (Script layout) and R2.4 (bare invocation behavior)** —
  `init_db.py` is a single-operation Script. Per R2.2 it does not need
  argparse subcommands; per R2.4 a bare invocation does the one job.
  `--help` still exits 0 with usage text.
- **R3.2 / R3.3 (Error_Envelope contract)** — failures print the
  standard `{"error": {"code": ..., "message": ..., "details": ...}}`
  envelope on stderr with exit 1.
- **R19.5 (`SCHEMA_MISMATCH`)** — the DB produced by `init_db.py`
  SHALL pass `scripts/_common.check_schema` (i.e. contain every table
  and column listed in `EXPECTED_SCHEMA`) on the next Script
  invocation. If it doesn't, that's a bug in `init_db.py`, not a
  feature the user has to work around.
- **R20.2 (packaging copy list)** — `scripts/init_db.py` ships in the
  zip for free because R20.2 already includes everything under
  `scripts/`. No change to R20.2 is required. The DDL source is
  discussed below as an open design question.
- **Skills (parent Task 19)** — every skill's SKILL.md file begins
  with `python scripts/init_db.py` as the first workflow step. See
  Requirement I-6 below.

### Open design question (for the design doc to resolve)

The DDL has to be readable by `init_db.py` at runtime. Two options,
either of which satisfies the requirements below:

1. **Recommended: ship `scripts/schema.sql`.** A new file under
   `scripts/` holds the DDL. It mirrors how `scripts/review.py` loads
   `scripts/review_template.html`. `tests/fixtures/schema.sql` remains
   the dev-time source of truth (kept up to date by
   `tests/fixtures/dump_schema.py`); either `make package` regenerates
   `scripts/schema.sql` from it, or a pre-commit hook keeps the two
   in sync. The dev-time fixture is still excluded from the zip by
   parent R20.3.
2. **Alternative: embed the DDL as a string constant** inside
   `scripts/init_db.py`. No new file. Same dev-time sync concern
   applies — the constant has to be regenerated when the schema
   changes.

The requirements below hold either way. The design doc picks one and
documents the sync story.

## Glossary

Terms from the parent `anime-song-learning-app` spec (App_Root, Script,
DB_File, Success_Envelope, Error_Envelope, UUID, now_epoch,
EXPECTED_SCHEMA — the set of tables and columns the parent spec
requires, as enumerated by `scripts/_common.EXPECTED_SCHEMA`) apply
here as defined there. The terms below are specific to this spec.

- **Init_Script**: `App_Root/scripts/init_db.py`. The Script this spec
  introduces.
- **Schema_Source**: The source of the DDL statements `init_db.py`
  applies when creating a fresh DB_File. Its concrete form (file path
  under `scripts/` or an embedded string constant) is chosen in the
  design doc; this spec only constrains its content.
- **Fresh_DB**: A new SQLite file produced by `init_db.py` from the
  Schema_Source. Contains the schema and no rows. All required tables
  and columns from EXPECTED_SCHEMA are present.
- **Init_Success_Created**: The Success_Envelope shape emitted when
  `init_db.py` had to create DB_File: `{"created": true, "path": "<abs>"}`
  where `<abs>` is the absolute path of the created DB_File.
- **Init_Success_Skipped**: The Success_Envelope shape emitted when
  DB_File already existed and `init_db.py` did nothing:
  `{"created": false, "path": "<abs>"}`.

## Requirements

### Requirement I-1: Script Layout and Runtime Constraints

**User Story:** As the user, I want `init_db.py` to follow the same
rules as every other Script under `scripts/`, so that it drops into
the packaged zip without changes to the runtime environment.

#### Acceptance Criteria

1. THE App SHALL provide a Script at `App_Root/scripts/init_db.py`,
   run with `python scripts/init_db.py`.
2. THE Init_Script SHALL import only from the Python standard library
   (per parent R1.2). In particular, THE Init_Script SHALL use
   `sqlite3` from the stdlib and SHALL NOT import any third-party
   package.
3. WHEN the Init_Script runs, THE Init_Script SHALL compute `App_Root`
   from its own file location and operate on DB_File at
   `App_Root/db/datasource.db`, regardless of the current working
   directory (per parent R1.3).
4. THE Init_Script SHALL NOT accept any flag or environment variable
   that changes the DB path (per parent R1.4).
5. WHEN the Init_Script is invoked with no arguments, THE Init_Script
   SHALL perform the init-or-skip operation defined in Requirement
   I-2. THE Init_Script SHALL NOT print help text in this case.
   (Rationale: parent R2.4 permits a bare invocation to either print
   help or do the one job; the user's intent for this Script is
   unambiguously the latter.)
6. WHEN the Init_Script is invoked with `--help` or `-h`, THE
   Init_Script SHALL print argparse-generated usage text to stdout
   and exit with code 0.
7. IF the Init_Script is invoked with any positional argument or any
   flag other than `--help` / `-h`, THEN THE Init_Script SHALL print
   an Error_Envelope with `code = "INVALID_INPUT"` and exit with
   code 1. (Rationale: pins the seam against future feature-creep
   flags like `--force`; see Out-of-Scope.)

### Requirement I-2: Init-or-Skip Behavior

**User Story:** As the user, I want to run `init_db.py` on a clean
host and get a working DB_File, and I want running it a second time
to do nothing instead of wiping my data.

#### Acceptance Criteria

1. WHEN the Init_Script runs and DB_File does not exist at
   `App_Root/db/datasource.db`, THE Init_Script SHALL create the
   parent directory `App_Root/db/` if it does not exist, open a new
   SQLite file at DB_File, apply every DDL statement from the
   Schema_Source inside one transaction, close the connection, print
   an Init_Success_Created envelope to stdout, and exit with code 0.
2. WHEN the Init_Script runs and DB_File already exists at
   `App_Root/db/datasource.db`, THE Init_Script SHALL NOT open it,
   SHALL NOT read it, SHALL NOT write to it, SHALL NOT rename it,
   SHALL NOT delete it, print an Init_Success_Skipped envelope to
   stdout, and exit with code 0. Existence is determined by
   `pathlib.Path.exists()` on DB_File.
3. THE Init_Script SHALL NOT provide any flag (`--force`, `--reset`,
   `--drop-existing`, `--backup`, or otherwise) that bypasses the
   skip-if-exists rule. The only way to get a fresh DB from an
   existing one is for the operator to delete or move DB_File
   manually, then re-run `init_db.py`.
4. WHERE DB_File already exists and is a zero-byte file, THE
   Init_Script SHALL still treat it as "exists" and skip per criterion
   2. (Rationale: the user, not the Script, decides what to do with
   an existing file of any size. Never overwrite.)
5. WHERE `App_Root/db/` exists as a file (not a directory), THE
   Init_Script SHALL print an Error_Envelope with
   `code = "INVALID_INPUT"`, the offending path in `details.path`,
   and exit with code 1. THE Init_Script SHALL NOT remove or rename
   the offending file.
6. WHERE DB_File's parent directory is not writable by the current
   process and DB_File does not exist, THE Init_Script SHALL print
   an Error_Envelope with `code = "INTERNAL_ERROR"`, include the
   underlying OSError message in `details`, and exit with code 1.
7. IF any DDL statement from the Schema_Source raises a `sqlite3`
   error during the create path (criterion 1), THEN THE Init_Script
   SHALL roll back the transaction, close the connection, attempt to
   remove the half-written DB_File so a retry starts from a clean
   slate, print an Error_Envelope with `code = "INTERNAL_ERROR"`
   including the sqlite3 error message in `details`, and exit with
   code 1.

### Requirement I-3: Output Envelope

**User Story:** As the user, I want `init_db.py` to emit the same
JSON shape on stdout and stderr as every other Script, so that I can
pipe its output or wrap it in the same tooling.

#### Acceptance Criteria

1. ON the created-path (Requirement I-2 criterion 1), THE Init_Script
   SHALL print exactly one JSON object to stdout equal to
   Init_Success_Created: `{"created": true, "path": "<abs>"}`.
   `<abs>` SHALL be the absolute, resolved path of DB_File (no
   symlinks, no trailing slash). Stdout SHALL contain no other
   bytes before or after the JSON (aside from a trailing newline).
2. ON the skipped-path (Requirement I-2 criterion 2), THE Init_Script
   SHALL print exactly one JSON object to stdout equal to
   Init_Success_Skipped: `{"created": false, "path": "<abs>"}`. Same
   absolute-path rule as criterion 1.
3. ON any failure, THE Init_Script SHALL print an Error_Envelope to
   stderr in the shape defined by parent R3.3 (`{"error": {"code":
   ..., "message": ..., "details": ...}}`) and SHALL exit with code
   1 (per parent R3.2). THE `code` field SHALL be one of the codes
   enumerated by parent R3.3; this Script uses `INVALID_INPUT` and
   `INTERNAL_ERROR`.
4. ON any failure, THE Init_Script SHALL NOT print a Python traceback
   to stdout (per parent R3.7). Tracebacks MAY appear on stderr
   inside `details` when useful, but SHALL NOT appear on stdout.
5. Log lines, if any, SHALL go to stderr. Stdout SHALL contain only
   the Success_Envelope JSON on success (per parent R3.4).

### Requirement I-4: Schema Correctness of a Fresh DB

**User Story:** As the user, I want the DB produced by `init_db.py`
to be immediately usable by every other Script, with no further
setup.

#### Acceptance Criteria

1. THE Schema_Source SHALL contain every CREATE TABLE and CREATE
   INDEX statement needed to make the resulting DB satisfy
   EXPECTED_SCHEMA (as defined in `scripts/_common.EXPECTED_SCHEMA`
   and grounded in parent R19.5). At minimum, the Fresh_DB SHALL
   contain these tables: `song`, `artist`, `show`, `rel_show_song`,
   `play_history`, `learning`.
2. AFTER the Init_Script creates a Fresh_DB, opening it via
   `scripts/_common.open_db` (which runs `check_schema`) SHALL
   succeed without raising `SCHEMA_MISMATCH`.
3. A Fresh_DB SHALL contain zero rows in every table. The Init_Script
   SHALL NOT seed any example data.
4. THE Schema_Source used at runtime SHALL match the one used by
   `tools/package.py._empty_db` at packaging time. The design doc
   decides how this is kept in sync (regeneration, duplication, or a
   single shared file); this requirement is on the semantic equality
   of the two schemas, not their physical location.
5. THE Init_Script SHALL NOT run `PRAGMA user_version` or any
   migration logic. Schema evolution is out of scope (per parent
   R19.4) and this Script is bound by that.

### Requirement I-5: Skip-Path Performance

**User Story:** As the user (and as Claude running a skill), I want
`init_db.py` on the skip path to be as close to "just interpreter
startup" as possible, so that prefixing every skill's workflow with
it does not add noticeable latency.

The goal is structural: running `init_db.py` when
`App_Root/db/datasource.db` already exists should do the least
possible work. Skills run this as their first step on every
invocation (see Requirement I-6), so the skip path is the hot path.
The acceptance criteria below are framed against observable structure
(what the Script does and does not do, which modules get imported)
rather than wall-clock thresholds, which would be flaky across hosts.

#### Acceptance Criteria

1. WHEN the Init_Script takes the skipped-path (Requirement I-2
   criterion 2), THE Init_Script SHALL NOT call `sqlite3.connect` on
   DB_File, SHALL NOT call `scripts._common.open_db` (which runs
   `check_schema`), and SHALL NOT read the Schema_Source from disk.
2. WHERE the Init_Script can avoid importing `sqlite3` on the
   skipped-path, THE Init_Script SHALL defer that import so it runs
   only on the created-path. (Rationale: `sqlite3` is one of the
   slower stdlib imports. Deferring saves ~10–15ms on the hot path.
   Tests can assert this structurally via `sys.modules` inspection
   from a subprocess that exercises the skipped-path.)
3. WHERE the Init_Script can short-circuit argparse on a bare
   invocation (no args) and go straight to the init-or-skip handler,
   THE Init_Script MAY do so. When any argument is present (e.g.
   `--help`, or an unknown flag), argparse SHALL run and the
   behaviors in Requirement I-1 criterion 6 and criterion 7 still
   hold. (Rationale: argparse adds ~5–10ms to module load; on the
   skills' hot path the bare call is overwhelmingly common.)
4. THE Init_Script SHALL NOT introduce any new filesystem write on
   the skipped-path beyond what Requirement I-2 criterion 2 already
   rules out. In particular, THE Init_Script SHALL NOT create a
   `.lock` file, a `.stamp` file, a `.init_complete` marker, or any
   caching artifact.

**Non-goal:** this block does NOT add a wall-clock performance
requirement. Skip-path latency on any given machine is dominated by
Python interpreter startup (~40ms), which is outside the Script's
control. The requirement is on what the Script does, not how long it
takes.

### Requirement I-6: Skill Integration

**User Story:** As the user, I want every skill to run `init_db.py`
as its first step, so that Claude never hits `DB_NOT_FOUND` on a
fresh deploy regardless of which skill the user invokes.

#### Acceptance Criteria

1. EVERY skill's `SKILL.md` file under `skills/<skill-name>/SKILL.md`
   SHALL begin its "Checklist" or "Workflow" section with a single
   first step: "Run `python scripts/init_db.py`." The step SHALL
   explain (one sentence) that this creates the DB on first use and
   is a safe no-op afterwards.
2. THE `skills/README.md` index file SHALL note (one sentence) that
   every skill begins with the `init_db` step, so a reader does not
   have to scan every SKILL.md to see the pattern.
3. THE Init_Script's skip-path performance is captured by Requirement
   I-5. This requirement does NOT add a per-skill performance
   requirement.
4. WHERE a new skill is added after this spec ships, the new skill's
   SKILL.md SHALL follow the same pattern (first step runs
   `init_db.py`). This is a convention for the skill author, not a
   runtime-enforceable check; the requirement is authorial.

## Correctness Properties for Property-Based Testing

Each property below is an invariant to check across many randomized
inputs. Tests run under the rules in parent Requirement 18 —
including a temp `App_Root` per test, never the real
`db/datasource.db`. The parent spec's `_guard_real_db` harness rule
(parent R18.4) applies to this Script's tests without exception:
every test SHALL point the Init_Script at a per-test `tmp_app_root`,
never at the real repo's `db/`.

### Property I-1: Skip-Idempotency on an Existing DB

For any existing DB_File D in a per-test `tmp_app_root`:

1. Record `D`'s byte contents and mtime before any run.
2. Run `python scripts/init_db.py` against that `tmp_app_root` N
   times (N drawn from a small random range, e.g. 1..5).
3. Every run exits with code 0 and prints an Init_Success_Skipped
   envelope.
4. `D`'s byte contents are identical to the pre-run snapshot after
   every run and at the end. (mtime may be platform-dependent and is
   not asserted.)

(Directly tests parent R1.5's recovery path plus the skip-if-exists
rule in Requirement I-2 criterion 2.)

### Property I-2: Fresh DB Has the Expected Schema

For any per-test `tmp_app_root` whose `db/` directory is empty or
missing:

1. Run `python scripts/init_db.py` against that `tmp_app_root` once.
2. The exit code is 0 and stdout is an Init_Success_Created envelope
   with `"created": true` and a `"path"` that exists on disk.
3. Opening the resulting DB_File via `scripts/_common.open_db`
   succeeds without raising `SCHEMA_MISMATCH`.
4. For every `(table, columns)` pair in
   `scripts/_common.EXPECTED_SCHEMA`, the table exists in the
   Fresh_DB and every listed column is present on it.

### Property I-3: User Data Preserved

For any DB_File D in a per-test `tmp_app_root` pre-populated with a
randomized but schema-valid set of rows (artists, songs, shows,
rel_show_song, play_history, learning — with non-empty text fields,
realistic timestamps, and valid foreign keys):

1. Snapshot every row in every table (ordered by `id`) before the
   run.
2. Run `python scripts/init_db.py` against that `tmp_app_root` once.
3. The exit code is 0 and stdout is an Init_Success_Skipped envelope.
4. Re-reading every row in every table yields exactly the same set
   of rows as the snapshot. No row was added, removed, or modified.

(Follows from the skip-if-exists rule but worth testing directly so
a regression that accidentally opens the existing DB in rw mode is
caught.)

### Property I-4: Create-Then-Skip Composition

For any per-test `tmp_app_root` whose `db/` directory starts empty:

1. Run `python scripts/init_db.py` once. It exits 0 with
   Init_Success_Created.
2. Snapshot the resulting DB_File's bytes.
3. Run `python scripts/init_db.py` again, M times (M drawn from a
   small random range, e.g. 1..4).
4. Each re-run exits 0 with Init_Success_Skipped.
5. The DB_File's bytes are identical to the post-step-1 snapshot
   after every re-run.

(Composes I-1 with the created path; ensures the created-DB byte
contents are stable under re-runs even within the same test.)

### Property I-5: Skills Prefix init_db.py

For every skill file matching `skills/*/SKILL.md`:

1. Parse the file's Markdown structure.
2. Locate the first workflow section — the first `##` heading whose
   body contains an ordered or unordered list of steps (in practice:
   "Checklist", "Workflow", "Workflow checklist", or equivalent).
3. The first step in that list (in document order) mentions
   `python scripts/init_db.py`.

This is deterministic once the skills are laid out, but framed as a
property because it quantifies over "every skill" — adding a new
skill extends the test's input set for free. Directly tests
Requirement I-6 criterion 1.

### Property I-6: Skip Path Does Not Import sqlite3

For any pre-existing DB_File in a per-test `tmp_app_root`:

1. Run `python scripts/init_db.py` in that `tmp_app_root` as a
   subprocess with an introspection hook (e.g. the env var
   `JANKENOBOE_PROBE_SKIP=1` that causes the Script to print the
   relevant subset of `sys.modules` to stderr just before exit, or
   an equivalent mechanism the design doc pins down).
2. The subprocess exits 0 with an Init_Success_Skipped envelope on
   stdout.
3. `sqlite3` is NOT in the reported `sys.modules` after the
   skipped-path completes.
4. (Only if the short-circuit from Requirement I-5 criterion 3 is
   taken) `argparse` is NOT in the reported `sys.modules` either.
   If the design doc instead opts to always run argparse, this
   sub-property is dropped rather than inverted.

Directly tests Requirement I-5 criteria 1 and 2. The exact
introspection mechanism is intentionally left to the design doc —
the requirement is on what gets imported, not how the test learns
about it.

## Out of Scope for This Spec

The following are explicitly NOT part of this feature. If any of
them becomes desirable later, they need a new spec or a follow-up
amendment to this one — not a flag added to `init_db.py`.

1. **No `--force`, `--reset`, or `--drop-existing` flag.** Clean slate
   is achieved by the operator deleting DB_File manually, then
   running `init_db.py`.
2. **No schema migration.** The Init_Script only creates from
   scratch. Evolving an existing DB's schema is bound by parent
   R19.4 (out of scope) and parent R19.5 (`SCHEMA_MISMATCH`).
3. **No backup-before-overwrite logic.** There is no overwrite path,
   so there is nothing to back up. If the operator wants a backup
   before they delete their DB, that's an operator concern outside
   this Script.
4. **No seed data.** A Fresh_DB contains the schema and zero rows.
   Populating it is done through `data.py`, the import pipeline, or
   direct SQL — not through `init_db.py`.
5. **No DB path override.** Parent R1.4 already forbids this; it is
   re-stated here (Requirement I-1 criterion 4) so that no future
   change introduces one for `init_db.py` in particular.
6. **No GUI, prompt, or interactive confirmation.** The Init_Script
   never asks the user anything. Skip-if-exists is the entire
   safety story.
7. **No skill-side retry, caching, or state-checking** beyond
   running `init_db.py` and trusting its Success_Envelope. Skills
   do not check for DB_File's existence themselves, do not cache
   the "already initialised" result across invocations, and do not
   retry on failure — they run `init_db.py` once at the top of
   their workflow and read its output.
