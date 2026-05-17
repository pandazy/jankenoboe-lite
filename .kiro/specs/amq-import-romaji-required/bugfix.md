# Bugfix Requirements Document

## Introduction

The AMQ importer treats the show's romaji name as best-effort: the
preprocessor in `scripts/import_plan.py` reads
`songs[i].songInfo.animeNames.romaji` only as a **last-resort fallback
for `show_name`** when `animeNames.english` is missing, and the
classifier never plumbs the romaji value through to the DB at all —
`_resolve_show` always passes `name_romaji: None` into the
`show_to_create` block, even though `show.name_romaji` is a real
column in `scripts/schema.sql`. The visible symptom: every show row
created through the importer has `name_romaji = NULL`, regardless of
whether the source AMQ file carried a romaji on the song. The
`show_name` column also conflates English and romaji on
English-missing entries — a row whose `name` is a romaji string is
indistinguishable from one whose `name` is an English title.

The deeper symptom is that the importer is silent when the romaji
**is not where the preprocessor expects to read it**. AMQ has changed
its export shape twice (the v0.1.1 → v0.1.2 fix moved every required
field one nest level deeper into `songInfo`); a future shape drift
that renames or relocates the romaji field would silently produce
shows with `name_romaji = NULL` and a `show_name` that may or may not
be English. CI does not catch this because no test asserts that an
imported show carries a non-null romaji.

This spec makes the show romaji **required input** at the API script
level (`scripts/import_plan.py` aborts the file with a typed error
when no romaji is resolvable) and **persists it into
`show.name_romaji`** when a show needs to be created. The
English-over-romaji fallback for `show_name` is removed: `show_name`
is English-only, and the romaji is its own field on the plan and on
the DB row. The shape of the contract becomes "every AMQ song MUST
carry a non-empty English title and a non-empty romaji title; both
land in their own columns".

The agent-level recovery — what
`skills/importing-amq-songs/SKILL.md` tells the agent to do when the
API rejects with the new error code, and the proactive JSON-shape
sniff that runs **before** every `import_plan.py` invocation — is
also covered by this spec, because the bug is observable on both the
API surface (it returns the wrong DB state today) and the skills
surface (today there is no recipe at all for "AMQ added a new field
name; let's diagnose and recover"). Both touches ship together.

The recovery path uses the existing `scripts/data.py create` surface
documented in `skills/README.md` as the last-resort fallback. No new
script, no new CLI flags on `import_plan.py`, no schema migration —
`show.name_romaji` already exists.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `scripts/import_plan.py` is invoked via `--input-jsonpath`,
`--input-jsonstr`, or the legacy flat surface against any payload —
real AMQ object shape, legacy flat array, or any mix — AND none of
the entries in the payload carries a romaji THEN the system SHALL
classify every entry into `resolved` / `auto_completable` /
`ambiguous` without ever raising — it does not check for romaji
presence, because `_AMQ_FIELD_MAP` lists `songInfo.animeNames.romaji`
only as a **non-required** fallback path under the `show_name` flat
key, and the flat surface does not look for romaji at all.

1.2 WHEN `scripts/import_plan.py` produces an `auto_completable`
plan entry whose show does not yet exist in the DB THEN the system
SHALL emit a `show_to_create` block whose `name_romaji` is always
`None`, even when the source AMQ song carried a non-empty
`songInfo.animeNames.romaji`. `_resolve_show` hard-codes
`"name_romaji": None`; the value is not even read off the
preprocessor output.

1.3 WHEN `scripts/import_resolve.py` consumes such a plan AND
creates the show row THEN the system SHALL persist the show with
`name_romaji = NULL`, regardless of whether a usable romaji existed
in the upstream AMQ file. The resulting DB row carries the English
title in `name` and `NULL` in `name_romaji`.

1.4 WHEN `scripts/import_plan.py` resolves `show_name` for a real
AMQ song AND `songInfo.animeNames.english` is empty or missing AND
`songInfo.animeNames.romaji` is a non-empty string THEN the system
SHALL silently use the romaji value as the `show_name` (and emit it
into `show.name`), so a row whose `name` column holds a romaji
string is indistinguishable downstream from a row whose `name` holds
an English title.

1.5 WHEN AMQ ships a future export-shape change that renames or
relocates the romaji field (e.g. moves it out of `animeNames.romaji`
into a sibling key or removes the `animeNames` sub-object entirely)
AND a user runs the new file through `scripts/import_plan.py` THEN
the system SHALL accept the file and produce shows with
`name_romaji = NULL` without alerting the user — every existing path
in the preprocessor either does not read romaji, treats romaji as a
silent fallback, or treats romaji as optional with a default of `""`.
The same drift mode that triggered the v0.1.1 → v0.1.2
`amq-real-export-shape-fix` is therefore still latent for romaji.

1.6 WHEN an agent following `skills/importing-amq-songs/SKILL.md`
hands an AMQ JSON file to `scripts/import_plan.py` THEN the system
SHALL offer no proactive shape-sniff before the script is invoked —
the SKILL.md Checklist goes straight from "Initialize the database"
to "Step 1 — plan", with no step that examines the JSON for the
romaji field's location and reports anomalies up front. Drift is
caught only after a write surface fails (and per 1.1–1.4 above,
today it does not even fail — it succeeds with NULL romaji).

1.7 WHEN `scripts/import_plan.py` rejects a file for any reason
today (`INVALID_INPUT`, `SONG_INVARIANT_VIOLATION`) THEN
`skills/importing-amq-songs/SKILL.md` SHALL guide the agent only as
far as the project-wide
"If a script fails, report it — don't patch it" rule in
`skills/README.md`: the agent surfaces the envelope to the user and
stops. There is no recovery branch in the SKILL.md for "the
preprocessor cannot find the romaji because the JSON shape has
drifted".

1.8 WHEN the test suite runs against the importer THEN the system
SHALL report a passing CI gate despite 1.1–1.4 — the existing
`tests/fixtures/amq_song_export-small.json` integration test asserts
only the bucket counts (`resolved + auto_completable + ambiguous ==
N`), and no test in the repo reads back the created show row to
check that `name_romaji` is non-null when a romaji existed in the
fixture.

### Expected Behavior (Correct)

2.1 WHEN `scripts/import_plan.py` is invoked via `--input-jsonpath`,
`--input-jsonstr`, or `--input-array` against any AMQ entry — real
AMQ shape via the preprocessor, or legacy flat shape via the
straight loader — AND that entry does not carry a non-empty romaji
on the show THEN the system SHALL abort the whole file with a typed
error envelope, `MISSING_ROMAJI`, exit code 1, with `details`
carrying the entry index and the available keys, naming romaji as
the missing field. The error code SHALL be drawn from the approved
set the rest of the importer uses (R3.3 of the parent
`anime-song-learning-app` spec) — if a fresh code is not warranted
the existing `INVALID_INPUT` MAY be reused, with `details.kind =
"missing_romaji"` so the recovery branch in the agent skill can
distinguish it from other `INVALID_INPUT` causes. The choice
between a fresh code and a discriminated `INVALID_INPUT` is deferred
to design.

2.2 WHEN the preprocessor resolves the romaji field for a real AMQ
song THEN the system SHALL read it from
`songs[i].songInfo.animeNames.romaji`. The romaji is its own flat
key on the preprocessor output (`show_name_romaji` or equivalent —
exact name deferred to design); it SHALL NOT be a fallback for
`show_name`.

2.3 WHEN the preprocessor resolves `show_name` for a real AMQ song
THEN the system SHALL read it from
`songs[i].songInfo.animeNames.english` only. The
English-falls-back-to-romaji precedence in the existing
`_AMQ_FIELD_MAP` SHALL be removed: an empty / missing English with
a non-empty romaji is a `MISSING` failure on the English flat key,
not a silent re-use of the romaji value. (The companion failure on
the romaji flat key is covered by 2.1.)

2.4 WHEN the legacy flat surface (`--input <path>` / positional
path / `--input-array`) accepts a flat entry THEN the entry SHALL
carry a `show_name_romaji` (or equivalent — keyed the same way the
preprocessor output is keyed) and that key SHALL be required, with
the same `MISSING_ROMAJI` rejection 2.1 describes when missing or
empty. The flat surface and the AMQ-via-preprocessor surface
produce byte-equal plans on equivalent inputs (parent
`amq-real-export-shape-fix` R3.2); that equivalence SHALL hold for
the romaji field too.

2.5 WHEN `scripts/import_plan.py` produces a `show_to_create` block
on an `auto_completable` or `resolved-with-create` entry THEN the
block SHALL carry the resolved romaji as `name_romaji` (a non-empty
string), not `None`. The existing `_resolve_show` SHALL stop
hard-coding `name_romaji: None` and SHALL pass the preprocessor's
romaji through.

2.6 WHEN `scripts/import_resolve.py` creates a show from a
`show_to_create` block THEN the system SHALL persist
`show.name_romaji` to the value carried on the block, so the DB row
ends with a non-null `name_romaji` matching the input AMQ song's
romaji.

2.7 WHEN `scripts/import_plan.py` resolves an existing show — the
classifier hits a row with the right `name` and `vintage` and
`status = 0` — THEN the existence check SHALL CONTINUE TO be on
`(name, vintage, status)` only (3.5 below); no romaji match is
required for an existing-show hit, so re-importing the same AMQ
file is still idempotent.

2.8 WHEN
`skills/importing-amq-songs/SKILL.md` runs an AMQ import THEN the
system SHALL include a new **Step 0 — Shape sniff** in the Checklist
that runs **before** `import_plan.py`. The sniff reads the user's
AMQ JSON, walks each `songs[i]` entry, and verifies that every
entry exposes a non-empty string at `songInfo.animeNames.romaji`
(plus the existing required keys the API checks for). The sniff is
read-only.

2.9 WHEN the Step 0 sniff finds at least one entry with no
non-empty romaji at the canonical path THEN the system SHALL
diagnose the cause from a small, named list of hypotheses and
present the diagnosis to the user before proceeding. The hypothesis
list SHALL include at least:
   - **Shape drift** — the JSON has the right top-level structure
     (object with `songs` array, each entry has `songInfo`) but the
     romaji lives at a different path (e.g. `songInfo.animeNames`
     has been renamed, or romaji moved to a sibling key on
     `songInfo`). The sniff SHALL report the actual keys it found at
     each level.
   - **Truncated / malformed JSON** — the file parsed but one or
     more `songs[i]` entries are missing the `songInfo` container,
     or the `animeNames` sub-object, entirely.
   - **Genuinely-empty romaji** — every level of the nesting is
     intact and the romaji value really is empty / null in the
     source.
   The exact taxonomy and format of the hypothesis report are
   deferred to design; the requirement is that the agent surfaces
   the failure mode, the index list, and the available keys it
   sniffed, so the user can decide.

2.10 WHEN the Step 0 sniff identifies a "Shape drift" candidate
path that holds the romaji THEN the system SHALL include the
candidate path and a sample value in the report so the user can
verify the agent's guess.

2.11 WHEN the user reviews the Step 0 report AND confirms the
agent's diagnosis THEN the system SHALL fall back to a manual
extraction path: the agent reads the romaji (and any other field
the diagnosis surfaces) from the candidate path, populates the show
row through `scripts/data.py create --kind show` with `name`,
`name_romaji`, `vintage`, and (if known) `s_type`, and then re-runs
the three-step pipeline so step 1 picks up the freshly-created show
on its existence check (2.7). This stays on existing rails — no
new script, no new flag.

2.12 WHEN the Step 0 sniff finds every entry with a non-empty
romaji at the canonical path THEN the system SHALL proceed straight
to Step 1 (`import_plan.py`) with no additional user
prompt. The sniff is silent on the success path.

2.13 WHEN the test suite runs after this fix lands THEN the system
SHALL include at least one integration test that drives a fixture
through `import_plan.py --input-jsonpath` end-to-end and asserts
that every created show row carries a non-null `name_romaji`
matching the input AMQ song's romaji, plus at least one negative
integration test that drives a romaji-stripped variant of the same
fixture and asserts that the run exits 1 with the
`MISSING_ROMAJI` envelope (or `INVALID_INPUT details.kind =
"missing_romaji"`, per the design decision deferred from 2.1)
naming the offending entry index.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `scripts/import_plan.py` is invoked against any input
where every entry carries a non-empty English title AND a non-empty
romaji title at the canonical paths THEN the system SHALL CONTINUE
TO classify entries into `resolved` / `auto_completable` /
`ambiguous` exactly as today — same bucket assignments, same
URL-decoding, same `SONG_INVARIANT_VIOLATION` handling, same
`media_url` / `show_id` / `show_to_create` carry-through. Only the
romaji column on the `show_to_create` block changes from `None` to
the resolved value; every other field on the block, and every other
bucket, is byte-identical to today.

3.2 WHEN `scripts/import_plan.py` runs successfully on any input
shape THEN the system SHALL CONTINUE TO be read-only: the SQLite
file at `db/datasource.db` is byte-identical before and after every
run (parent `amq-real-export-shape-fix` R3.4).

3.3 WHEN `scripts/import_plan.py` is given a non-AMQ input — a JSON
scalar, a JSON object without a `songs` array, a non-parseable JSON
file, or a missing file — THEN the system SHALL CONTINUE TO abort
with `INVALID_INPUT` and exit code 1, without writing anything. The
new `MISSING_ROMAJI` rejection layers on top of the existing
required-field validation; it does not replace the
"is this even valid AMQ" gate.

3.4 WHEN `scripts/import_plan.py` rejects a real-AMQ-shape file
because some other required field is missing — `artist_name`,
`song_name`, `show_name` (now English-only per 2.3), or `vintage` —
THEN the system SHALL CONTINUE TO abort with `INVALID_INPUT` exactly
as today, naming that field. The romaji rejection (2.1) fires only
when every other required field is present and the romaji
specifically is missing; it does not pre-empt the existing
required-field rejections.

3.5 WHEN `scripts/import_plan.py`'s classifier checks whether a
show already exists THEN the system SHALL CONTINUE TO match on
`name = ? AND vintage = ? AND status = 0` only. The romaji column
SHALL NOT be added to the existence query — re-running the import
on the same AMQ file is idempotent regardless of whether the
existing show row's `name_romaji` matches the file's romaji.

3.6 WHEN `scripts/import_resolve.py` creates an artist or a song
(not a show) THEN the system SHALL CONTINUE TO behave exactly as
today. Only the show-creation path changes — the artist and song
creation paths do not gain a romaji column.

3.7 WHEN `scripts/add_play_history.py` runs THEN the system SHALL
CONTINUE TO behave exactly as today. The romaji change is confined
to step 1 (plan) and step 2 (resolve, only the show INSERT line);
step 3 reads ids from the triple list and is untouched.

3.8 WHEN any other script under `scripts/` is invoked
(`learning.py`, `query.py`, `merge_artists.py`, `cleanup.py`,
`add_play_history.py`, `init_db.py`, `data.py`, `review.py`) THEN
the system SHALL CONTINUE TO behave exactly as today. This bug is
confined to the AMQ import surface and the skills doc that drives
it.

3.9 WHEN the Step 0 sniff in
`skills/importing-amq-songs/SKILL.md` finds nothing wrong THEN the
agent SHALL CONTINUE TO follow the existing three-step pipeline
(plan → resolve → add) verbatim: same scripts, same flags, same
handoff files (`plan.json`, `answers.json`, `triples.json`).
Step 0 is purely a pre-flight check; it adds no state for steps 1–3
to consume.

3.10 WHEN the agent takes the manual-recovery branch (2.11) THEN
the system SHALL CONTINUE TO leave the user-supplied AMQ JSON file
on disk unmodified. The recovery extracts values out of the file
into a `data.py create --kind show` invocation; it never rewrites
the source file. The committed real-AMQ test fixture
(`tests/fixtures/amq_song_export-small.json`) SHALL CONTINUE TO be
read-only for every test that consumes it.

3.11 WHEN the existing tests under `tests/unit/` and
`tests/integration/` run after the fix lands THEN the system SHALL
express their AMQ-wrapper payloads with a non-empty romaji on every
entry that they expect to classify successfully, so the structural
contracts they already assert
(`resolved + auto_completable + ambiguous` sums, byte-equal plans
across the four input channels, `--input-array` rejects nested AMQ
with `INVALID_INPUT`, etc.) SHALL CONTINUE TO hold. Tests that
currently rely on the English-falls-back-to-romaji precedence (if
any) SHALL be rewritten to assert the new contract: missing English
is a hard rejection, romaji is its own required field.

3.12 WHEN the fix ships THEN
`skills/importing-amq-songs/references/plan-shape.md` SHALL be
updated in lockstep so the documented `show_to_create` block, the
field-mapping table, and the required-field list match the new
contract — `name_romaji` is documented as a non-null string on the
block; the romaji row in the field-mapping table is documented as
required; the English row no longer lists `animeRomajiName` as a
fallback. This is the same scope-permitted documentation touch the
parent `amq-real-export-shape-fix` spec performed when the field
mapping last changed (R3.8 of that spec).

3.13 WHEN any other skill doc under `skills/` is read
(`adding-songs-to-learning`, `reviewing-songs`, `searching-library`,
`merging-artists`, `cleaning-up-dead-records`, and the top-level
`skills/README.md`) THEN the system SHALL CONTINUE TO carry the
content each file has today. The romaji change is scoped to
`skills/importing-amq-songs/` only.

## Deriving the Bug Condition

This spec covers one defect surface — the AMQ importer's treatment
of the show romaji as best-effort instead of required — observable
on two layers (the API script and the agent skill). Both layers
share the same bug condition; the property and preservation goal
quantify over both.

### Bug Condition

```pascal
FUNCTION isBugConditionRomajiRequired(X)
  INPUT: X of type AmqImportInvocation
          (the AMQ JSON payload the user hands the agent, plus the
           argv pair the agent passes to scripts/import_plan.py via
           --input-jsonpath / --input-jsonstr / --input-array / the
           legacy flat surface; the recovery path through
           scripts/data.py create --kind show is layered on top of
           this and is checked separately)
  OUTPUT: boolean

  // The bug is triggered whenever the payload that reaches
  // import_plan.py does not carry a non-empty romaji on at least
  // one entry the script would otherwise classify successfully.
  // Two cases:
  //   (a) the payload is the real AMQ shape and at least one
  //       songs[i] does not expose a non-empty string at
  //       songInfo.animeNames.romaji;
  //   (b) the payload is the legacy flat shape and at least one
  //       entry does not carry a non-empty show_name_romaji
  //       (or equivalent) at the agreed flat key.
  // The shape-drift sub-case in 1.5 — romaji moved to a different
  // path — is a specialisation of (a): songInfo.animeNames.romaji
  // is empty / missing, but a romaji exists elsewhere in the
  // entry. Both sub-cases of (a) are captured by the predicate
  // below.
  IF NOT isParseableAmq(X.payload) THEN RETURN False
  IF requiredFieldsExceptRomajiAreAllPresent(X.payload) AND
     someEntryHasNoNonEmptyRomajiAtCanonicalPath(X.payload) THEN
    RETURN True
  END IF
  RETURN False
END FUNCTION
```

Where `someEntryHasNoNonEmptyRomajiAtCanonicalPath(payload)` is true
iff there exists at least one `songs[i]` (real AMQ shape) or one
flat entry (legacy shape) for which the canonical romaji path
returns no non-empty string. The romaji being silently consumed as
a `show_name` fallback (1.4) is **not** a separate condition — the
fix that lands the romaji into its own column makes the
fallback go away as a side effect.

### Property (Fix Checking)

```pascal
// For every invocation whose payload meets the bug condition, the
// fixed code SHALL produce a typed error envelope at the API
// surface and a Step 0 sniff failure at the agent surface — both
// pointing at the same offending entries — and, on user
// confirmation, the manual-recovery branch SHALL produce a show
// row whose name_romaji is non-null.
//
// For every invocation whose payload does NOT meet the bug
// condition, the fixed code SHALL produce a plan whose every
// auto_completable / resolved-with-create show_to_create block
// carries a non-null name_romaji, and SHALL drive that plan
// through resolve / add to a DB state where every newly-created
// show row's name_romaji column matches the input AMQ song's
// romaji.
FOR ALL X DO
  IF isBugConditionRomajiRequired(X) THEN
    apiResult ← importPlan'(X)
    ASSERT apiResult.exitCode = 1
    ASSERT apiResult.error.code IN {"MISSING_ROMAJI", "INVALID_INPUT"}
    ASSERT apiResult.error.details.kind = "missing_romaji"
    ASSERT apiResult.error.details.index IS NOT NULL

    sniffReport ← step0Sniff'(X.payload)
    ASSERT sniffReport.failed = TRUE
    ASSERT sniffReport.offendingIndices = apiResult.error.details.indices
              // same set; agent surface diagnoses the same entries
              // the API would reject.

    IF userConfirmsRecovery(sniffReport) THEN
      recovered ← manualRecover'(X.payload, sniffReport)
                  // calls scripts/data.py create --kind show with
                  // the romaji extracted from the candidate path,
                  // then re-runs the three-step pipeline.
      ASSERT recovered.show.name_romaji IS NOT NULL
      ASSERT recovered.show.name_romaji ≠ ""
    END IF
  ELSE
    apiResult ← importPlan'(X)
    ASSERT apiResult.exitCode = 0
    FOR ALL block IN auto_completable_and_resolved_with_create(apiResult.plan) DO
      ASSERT block.show_to_create.name_romaji IS NOT NULL
      ASSERT block.show_to_create.name_romaji ≠ ""
    END FOR

    after ← runResolveAndAdd'(apiResult.plan)
    FOR ALL row IN newlyCreatedShowRows(after) DO
      ASSERT row.name_romaji IS NOT NULL
      ASSERT row.name_romaji = correspondingInputRomaji(X.payload, row)
    END FOR
  END IF
END FOR
```

### Preservation Goal

```pascal
// For every invocation whose payload does NOT meet the bug
// condition AND whose entries already carry a romaji at the
// canonical path, the fixed code SHALL produce the same bucket
// assignments, the same byte-equal plan structure (modulo the
// name_romaji column on show_to_create blocks flipping from null
// to the resolved string), and the same exit code, stdout
// envelope, and stderr envelope as today on the equivalent input.
//
// The legacy --input / positional flat surface, the
// --input-array flat-only contract, and every non-AMQ-import
// script under scripts/ SHALL remain byte-identical.
FOR ALL X WHERE NOT isBugConditionRomajiRequired(X) DO
  before ← importPlan(X)
  after  ← importPlan'(X)
  ASSERT after.exitCode = before.exitCode
  ASSERT after.plan.bucketAssignments = before.plan.bucketAssignments
  ASSERT planEqualUpToNameRomajiColumn(after.plan, before.plan)
END FOR

FOR ALL invocationOfScript NOT IN
       {import_plan, import_resolve.show_creation_branch,
        skill: importing-amq-songs} DO
  ASSERT behavior(invocationOfScript) = behavior'(invocationOfScript)
END FOR
```

**Key Definitions:**

- **F (`importPlan`)**: `scripts/import_plan.py` as it exists on
  `mainline` after v0.1.6 shipped — `_AMQ_FIELD_MAP` reads
  `songInfo.animeNames.romaji` only as a fallback under the
  `show_name` flat key; `_resolve_show` always emits
  `name_romaji: None`.
- **F' (`importPlan'`)**: `scripts/import_plan.py` after this fix —
  romaji is its own required flat key on the preprocessor output;
  the English-falls-back-to-romaji precedence on `show_name` is
  removed; `_resolve_show` carries the resolved romaji onto every
  `show_to_create` block.
- **`MISSING_ROMAJI`** (or `INVALID_INPUT details.kind =
  "missing_romaji"`): the typed error envelope `importPlan'`
  returns when the bug condition holds. The choice between a fresh
  error code and a discriminated `INVALID_INPUT` is deferred to
  design.
- **Step 0 sniff**: the read-only pre-flight the new
  `skills/importing-amq-songs/SKILL.md` Checklist runs **before**
  `scripts/import_plan.py`. Walks each `songs[i]` looking for
  romaji at the canonical path; on miss, classifies the failure
  mode (shape drift / truncated / genuinely-empty), reports the
  available keys at each nesting level, and surfaces a candidate
  recovery path to the user.
- **Manual-recovery branch**: the agent, after user confirmation,
  reads the romaji out of the candidate path the sniff identified
  and inserts the show via `scripts/data.py create --kind show`
  with `name`, `name_romaji`, `vintage`, and (if known) `s_type`,
  then re-runs the three-step pipeline so step 1's existence check
  picks up the new show.
- **Real AMQ export shape**: same definition as the parent
  `amq-real-export-shape-fix` spec — a JSON object with a top-level
  `songs` array whose entries carry their data under a `songInfo`
  sub-object, with show names under
  `songInfo.animeNames.{english,romaji}`. The romaji's canonical
  path is `songs[i].songInfo.animeNames.romaji`.
- **Counterexample (evidence of the bug)**: any AMQ song with a
  non-empty `songInfo.animeNames.romaji`. Today's importer creates
  the show with `name_romaji = NULL`. The fixed importer creates
  the same show with `name_romaji` equal to the romaji in the
  input. Today's importer also accepts a song with an empty romaji
  silently; the fixed importer rejects with `MISSING_ROMAJI`.
