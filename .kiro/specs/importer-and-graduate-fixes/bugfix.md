# Bugfix Requirements Document

## Introduction

This spec covers four independent defects in the user-facing contracts
of the importer and learning-path pipelines, plus the skills
documentation that steers agents through them:

- **Bug 1 — AMQ importer input shape.** `scripts/import_plan.py` (step
  one of the three-step AMQ ingestion pipeline) currently exposes a
  single CLI entry point for input (`--input <path>` or a positional
  path) and that entry point only accepts a pre-flattened JSON array
  whose entries have exactly `artist_name`, `song_name`, `show_name`,
  `vintage`, `media_url`. There is no way to hand it the file AMQ
  itself produced (the nested JSON with top-level game metadata and a
  `songs` array of AMQ song objects — "raw AMQ export shape"), no way
  to pass JSON inline on the command line, and no distinct channel for
  internal/programmatic callers that have already flattened. The CLI
  surface should grow three explicit, mutually-exclusive input flags
  that together cover these cases:
  `--input-jsonpath <path>` (a file holding either the raw AMQ export
  shape or the legacy flat array shape),
  `--input-jsonstr <json>` (the same two payload shapes passed inline
  as a JSON string), and `--input-array <json>` (the flat array shape
  only, intended for internal callers and explicitly rejecting the
  raw AMQ object shape). The three flags make the caller's intent
  explicit at the CLI level — the disambiguation is the flag chosen,
  not payload-content sniffing of a single ambiguous argument.
  Internally, a new preprocessing stage converts any accepted raw AMQ
  payload to the same flat five-field shape the classifier consumes
  today, so the `resolved` / `auto_completable` / `ambiguous`
  classification, URL-decoding, `SONG_INVARIANT_VIOLATION` handling,
  and plan output all stay unchanged.

- **Bug 2 — `graduate` doesn't pin `level` to the max.**
  `scripts/learning.py graduate --ids <id>` currently sets
  `graduated = 1` but leaves `level` at whatever it was. A graduated
  song has by definition reached the top of the spaced-repetition
  curve, so the row should also end at `level = MAX_LEVEL` (19, the
  final entry in `DEFAULT_LEVEL_UP_PATH`). The `levelup` command
  already auto-graduates at `MAX_LEVEL`; the two paths to
  `graduated = 1` should leave the row in the same observable state.
  The symptom is misleading `level` values surfacing in `search-songs`,
  `list-learning`, and the `learning-detail` view (e.g. a graduated
  song showing `level = 3`).

- **Bug 3 — skills docs don't rank dedicated commands above raw CRUD.**
  The skills documentation lists the available commands but does not
  tell the agent to prefer dedicated commands over raw CRUD. An agent
  could use `data.py update` to flip `learning.graduated` to 1
  directly, which succeeds and writes valid SQL but violates the
  `graduated ↔ level = MAX_LEVEL` contract that Bug 2 establishes. Raw
  CRUD via `data.py` should be a documented last resort, used only
  when no dedicated command exists for the intent. This bug is in the
  skills documentation itself (`skills/README.md` and
  `skills/*/SKILL.md`), not in code.

- **Bug 4 — `searching-library` SKILL.md lacks worked combined-search
  examples.** The skill already lists `search-songs` in its Checklist,
  but nothing in the SKILL.md shows how to translate a natural-language
  combined-intent question ("songs from show X by artist Y") into the
  right `search-songs` flags. Agents who haven't internalised the op
  can fall back to chaining three `search` calls and intersecting IDs
  by hand — strictly worse. The fix is a short, example-driven section
  inside `skills/searching-library/SKILL.md` covering the common
  combined-intent pairings (song+show, song+artist, artist+show,
  all-three) with one worked invocation each. This bug is in the skill
  documentation, not in code.

Bugs 1 and 2 live in existing live code (`scripts/import_plan.py`,
`scripts/learning.py`) and both have integration tests that currently
encode the buggy behavior. Bugs 3 and 4 live in the documentation tree
under `skills/` and have no test coverage today — they are two
complementary documentation touches on the same failure mode (agent
picks the wrong command).

## Bug Analysis

### Current Behavior (Defect)

Bugs 1 and 2 are currently observable against the code on `mainline`;
Bug 3 is currently observable in the `skills/` tree on `mainline`.

1.1 WHEN `import_plan.py` is invoked with `--input <path>` (or a
positional path) pointing at the raw AMQ export JSON (a JSON object
with top-level game metadata and a `songs` array of AMQ song objects)
THEN the system rejects the input with
`INVALID_INPUT` ("AMQ input must be a JSON array of entries.") because
the loader requires the top level to already be a flat array of
`{artist_name, song_name, show_name, vintage, media_url}` records, and
there is no alternative CLI flag that would accept the raw AMQ shape.

1.2 WHEN the user has the JSON text already in hand (from a shell
variable, from `jq` output, from an upstream tool, or copy-pasted from
AMQ) AND wants to pass it to `import_plan.py` without round-tripping
through a temporary file THEN the system offers no way to do so,
because the only accepted input channel is a file path on disk
(`--input <path>` or the positional path equivalent).

1.3 WHEN an internal or programmatic caller has already produced the
flat five-field array and wants a dedicated channel that guarantees
the input is flat (and rejects anything else) THEN the system offers
no such distinction: the only channel is the legacy `--input <path>`
file-based entry point, and it accepts no alternative shape today
regardless of caller intent.

1.4 WHEN `learning.py graduate --ids <id>` is run against a non-graduated
learning row whose `level` is less than `MAX_LEVEL` (e.g. `level = 3`)
THEN the system sets `graduated = 1` but leaves `level` unchanged,
producing a row with `graduated = 1 AND level < MAX_LEVEL`.

1.5 WHEN a row has been graduated via the explicit `graduate` command
AND that row is surfaced by downstream read ops (`search-songs`
learning summary, `list-learning`, `learning-detail`) THEN the system
reports a `level` (and derived `display_level`) that does not match
the row reached by `levelup` at `MAX_LEVEL`, even though both paths
result in `graduated = 1`.

1.6 WHEN an agent consults the skills documentation (`skills/README.md`
and the per-skill `skills/*/SKILL.md` bodies) to decide how to
accomplish a task THEN the system presents an enumeration of scripts
and subcommands without ranking them: `data.py` CRUD and the
dedicated commands (`learning.py graduate`, `learning.py levelup`,
`learning.py batch`, `merge_artists.py`, `cleanup.py`, and the
`import_plan.py` → `import_resolve.py` → `add_play_history.py`
pipeline) are all documented as available with no stated preference
between them.

1.7 WHEN an agent follows only the skills index to pick a command to
graduate a song THEN the system offers no reason to prefer
`learning.py graduate --ids <id>` over
`data.py update --kind learning --id <id> --data '{"graduated": 1}'`;
both are documented as available paths.

1.8 WHEN an agent takes the raw-CRUD path (e.g. sets
`learning.graduated = 1` via `data.py update`) THEN the system
accepts the write and the resulting row carries valid SQL values but
sits in an observably inconsistent state relative to what the
dedicated command would have produced — for example, a graduated row
whose `level` is not `MAX_LEVEL` after the Bug 2 fix ships, visible
to downstream reads (`search-songs`, `list-learning`,
`learning-detail`).

1.9 WHEN an agent reads `skills/searching-library/SKILL.md` to answer
a combined-intent question (a user asking about two or more of
{song name, show name, artist name} at once) THEN the system offers
only a single paragraph mention of `search-songs` in the "Pattern"
section and a terse Checklist bullet with its flags, with no worked
example mapping a natural-language question onto the corresponding
`--song-term` / `--show-term` / `--artist-term` invocation.

1.10 WHEN an agent is not already fluent in `search-songs` AND
encounters a combined-intent question THEN the system leaves no
pattern in the SKILL.md that nudges the agent toward `search-songs`;
the agent can reasonably fall back to chaining three `search` calls
(once per kind) and intersecting ids by hand, which is strictly
worse — more DB roundtrips, no related-detail attachment, no
byte-stable ordering.

### Expected Behavior (Correct)

2.1 WHEN `import_plan.py` is invoked with
`--input-jsonpath <path>` pointing at a JSON file whose content is
the raw AMQ export shape (a JSON object with a top-level `songs` key
holding an array of AMQ song objects, plus arbitrary game-metadata
siblings of `songs`) THEN the system SHALL accept the file as-is,
internally extract and flatten the `songs` array via the
preprocessing stage, and classify every song in it into the
`resolved` / `auto_completable` / `ambiguous` buckets — producing
exactly the same plan it would produce from the equivalent
already-flat input.

2.2 WHEN `import_plan.py` is invoked with
`--input-jsonpath <path>` pointing at a JSON file whose content is
the legacy flat array shape (a JSON array of
`{artist_name, song_name, show_name, vintage, media_url}` entries)
THEN the system SHALL accept the file and produce the same plan the
legacy `--input <path>` surface produces today on the same content.

2.3 WHEN `import_plan.py` is invoked with `--input-jsonstr <json>`
whose argument is a JSON string containing either the raw AMQ export
shape OR the legacy flat array shape THEN the system SHALL parse the
string as JSON in place (without reading any file), dispatch through
the preprocessing stage, and produce the same plan it would produce
from the equivalent `--input-jsonpath` invocation pointing at a file
containing that same JSON text.

2.4 WHEN `import_plan.py` is invoked with `--input-array <json>`
whose argument is a JSON string containing the flat array shape THEN
the system SHALL parse the string as JSON in place and produce the
same plan the legacy `--input <path>` surface produces today on a
file containing the same flat array.

2.5 WHEN `import_plan.py` is invoked with `--input-array <json>`
AND the parsed JSON is the raw AMQ object shape (or anything that is
not a flat array of the expected entry shape) THEN the system SHALL
abort with `INVALID_INPUT` and exit code 1, without dispatching
through the AMQ-to-flat preprocessing stage — this flag is the
flat-only internal channel and SHALL NOT silently accept nested AMQ
JSON.

2.6 WHEN `import_plan.py` is invoked AND exactly one of
`--input-jsonpath`, `--input-jsonstr`, and `--input-array` is
supplied (not counting the legacy `--input` / positional surface
covered by the regression-prevention clauses below) THEN the system
SHALL treat that flag as the input channel for this invocation.
Supplying more than one of the three new flags in the same
invocation SHALL abort with `INVALID_INPUT` and exit code 1.

2.7 WHEN `import_plan.py` is invoked AND none of the three new
flags is supplied AND no legacy `--input` / positional path is
supplied either THEN the system SHALL abort with `INVALID_INPUT` and
exit code 1, with an error message naming the available input flags.
At least one input channel (one of the three new flags or the legacy
surface) SHALL be required per invocation.

2.8 WHEN any of the three new flags is used AND the supplied payload
is the raw AMQ export shape THEN the preprocessing stage SHALL
convert it into the flat five-field shape
(`artist_name`, `song_name`, `show_name`, `vintage`, `media_url` per
entry) before handing the entries to the classifier, so every
downstream step (resolved / auto_completable / ambiguous bucketing,
URL-decoding, `SONG_INVARIANT_VIOLATION` handling, `media_url` and
`show_id` / `show_to_create` carry-through) operates on a uniform
intermediate representation regardless of which input channel was
used.

2.9 WHEN the raw AMQ export contains fields beyond the five the
classifier uses (`artist_name`, `song_name`, `show_name`, `vintage`,
`media_url`) — including the `type` field and any other AMQ-native
noise on each song, and any top-level game metadata siblings of
`songs` — THEN the system SHALL ignore those extra fields and produce
the same plan it would have produced from the equivalent flattened
input.

2.10 WHEN `learning.py graduate --ids <id>` is run against a
non-graduated learning row whose `level` is less than `MAX_LEVEL`
THEN the system SHALL set `graduated = 1` AND set `level = MAX_LEVEL`
(19) in the same update, so the row ends in the same observable state
as one graduated via `levelup` at `MAX_LEVEL`.

2.11 WHEN `learning.py graduate --ids <id>` succeeds on a previously
non-graduated row THEN the response payload SHALL report
`level = MAX_LEVEL` and `display_level = MAX_LEVEL + 1` (20) for that
row, matching what `levelup` would have reported on the same row had
it been at `MAX_LEVEL` already.

2.12 WHEN an agent reads the skills documentation THEN the system SHALL
state an explicit preference, in a globally-reachable location (the
top-level `skills/README.md` or equivalent page every skill links
back to), that dedicated commands are to be used for their stated
intent when one exists, and that `data.py` CRUD is a last-resort
fallback used only when no dedicated command covers the task.

2.13 WHEN the preference guidance is presented THEN the system SHALL
include at least one worked counter-example contrasting a raw-CRUD
path against the dedicated command — ideally the graduate case
(flipping `learning.graduated = 1` via `data.py update` vs calling
`learning.py graduate`) — naming the invariant the dedicated command
preserves (`graduated ↔ level = MAX_LEVEL` post Bug 2 fix) and the
raw path does not.

2.14 WHEN an agent scans the guidance to decide whether a dedicated
command exists for their intent THEN the system SHALL list, or
reference the existing `skills/README.md` listing of, the dedicated
commands that exist and the kinds of work they cover, so the agent
can check that catalog before falling back to raw CRUD. The existing
`skills/README.md` already enumerates the six skills and their
dedicated commands; the new guidance SHALL reference that list
rather than duplicate it.

2.15 WHEN the guidance is placed in the documentation tree THEN the
system SHALL locate it where every agent path will see it — the
top-level `skills/README.md` is the natural home since every skill
links back to it. The requirement is on the content being reachable
from every skill entry point, not on a specific filename.

2.16 WHEN an agent reads `skills/searching-library/SKILL.md` THEN
the system SHALL provide a short, example-driven section covering
the common combined-intent pairings: (a) song name + show name,
(b) song name + artist name, (c) artist name + show name, (d) all
three together. Each example SHALL show the full
`scripts/query.py search-songs` invocation with the relevant
`--song-term` / `--show-term` / `--artist-term` flags, plus a
one-line description of what the envelope returns.

2.17 WHEN the combined-search examples are presented THEN the
system SHALL anchor them in concrete natural-language questions the
user is likely to ask (e.g. "the opening of Clannad by Lia", "songs
from FMA by Yui", "which shows does Hikaru Midorikawa sing in?"),
so the agent has a pattern to match user intent onto.

2.18 WHEN the examples are shown THEN the system SHALL explicitly
contrast them with the "chain three `search` calls and intersect"
anti-pattern, so an agent scanning the section knows which approach
to prefer and why.

2.19 WHEN the examples section lands in the SKILL.md THEN the
system SHALL place it near the top of the file (after the opening
paragraph, alongside or just after the existing "Pattern: when the
user gives a name, not an ID" section) so an agent reading the file
top-to-bottom sees the combined-search guidance before the general
per-op Checklist.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `import_plan.py` is invoked via the legacy `--input <path>`
flag (or the positional path equivalent) AND the file at that path
is the flat JSON array shape documented in the current
`skills/importing-amq-songs/SKILL.md` and `references/plan-shape.md`
(entries with `artist_name`, `song_name`, `show_name`, `vintage`,
`media_url`) THEN the system SHALL CONTINUE TO accept it and produce
the same `resolved` / `auto_completable` / `ambiguous` bucketing it
produces today, so users already scripted against the legacy surface
are not broken.

3.2 WHEN the design phase chooses the treatment of the legacy
`--input <path>` (and positional) surface — either leaving it
flat-only as it is today, or routing it through the new
preprocessing stage so it also accepts raw AMQ payloads (i.e. making
it a deprecated alias of `--input-jsonpath`) — THEN the system SHALL
in either case CONTINUE TO accept flat-array-against-`--input`
invocations with the same plan output they produce today. The
regression requirement is "existing flat-array-via-legacy callers
don't break"; the choice of whether legacy `--input` also gains the
raw-AMQ behavior is deferred to design.

3.3 WHEN `import_plan.py` is given an input that is neither the raw
AMQ export shape nor the flat array shape (e.g. a JSON scalar, a JSON
object without a `songs` array, a file that is not valid JSON, or a
missing file) THEN the system SHALL CONTINUE TO abort with
`INVALID_INPUT` and exit code 1, without writing anything.

3.4 WHEN `import_plan.py` runs successfully THEN the system SHALL
CONTINUE TO be read-only: the SQLite DB file at `db/datasource.db` is
byte-identical before and after the run.

3.5 WHEN `import_plan.py` classifies AMQ entries THEN the system
SHALL CONTINUE TO URL-decode every string field of every entry before
any DB lookup, honor `SONG_INVARIANT_VIOLATION` when one artist owns
two live songs with the same name, and carry `media_url` and the
resolved `show_id` / `show_to_create` block through to the plan
exactly as it does today.

3.6 WHEN `learning.py graduate --ids <id>` is run against an
already-graduated row (`graduated = 1`) THEN the system SHALL
CONTINUE TO be a no-op success: `level`, `graduated`, `created_at`,
and `updated_at` on the row are unchanged, and the response reports
the row's existing state.

3.7 WHEN `learning.py graduate --ids <id>` is run and any id in the
batch is missing from the `learning` table THEN the system SHALL
CONTINUE TO abort with `NOT_FOUND` (exit code 1) and leave every
other row in the batch untouched.

3.8 WHEN `learning.py levelup --ids <id>` is run against a row at
`level = MAX_LEVEL` THEN the system SHALL CONTINUE TO graduate it
(`graduated = 1`) with `level` staying at `MAX_LEVEL` and
`last_level_up_at` unchanged per R6.6 — this bug fix does not change
the `levelup` path.

3.9 WHEN `learning.py graduate` flips a row's `graduated` flag from
`0` to `1` THEN the system SHALL CONTINUE TO stamp `updated_at` with
the current epoch and leave `id`, `song_id`, `created_at`,
`level_up_path`, and `last_level_up_at` unchanged.

3.10 WHEN an agent or a human operator needs `data.py` (for genuine
escape-hatch work, or any task no dedicated command covers) THEN the
system SHALL CONTINUE TO document `data.py` as a fully available
tool with its full set of subcommands (`create`, `update`, `delete`,
`bulk-reassign`) and their flags. This bug fix is about agent
guidance — `data.py` is not being removed, hidden, or gated.

3.11 WHEN an agent follows any existing skill
(`adding-songs-to-learning`, `reviewing-songs`, `searching-library`,
`importing-amq-songs`, `merging-artists`, `cleaning-up-dead-records`)
THEN the system SHALL CONTINUE TO link that skill to the same
dedicated commands it links to today. No skill is being rerouted to
`data.py` as a result of this fix, and no skill is being rerouted
away from `data.py` where it already references it (e.g. the
`SONG_INVARIANT_VIOLATION` note in `importing-amq-songs` that points
at `scripts/data.py delete --kind song`).

3.12 WHEN an agent lands on a single `SKILL.md` body directly (without
first reading `skills/README.md`) THEN the system SHALL CONTINUE TO
let that `SKILL.md` work as a standalone page for the skill's own
scope. The new preference guidance complements the per-skill bodies
rather than requiring them to be re-read end-to-end.

3.13 WHEN the fix ships THEN for every command documented in any
`SKILL.md` at spec start, the system SHALL CONTINUE TO document that
command in the same skill file, with the same command string and
subcommand names. No dedicated command is silently undocumented as
collateral damage of adding the preference guidance.

3.14 WHEN an agent reads `skills/searching-library/SKILL.md` for
any query it already documents (the single-kind `search`, `get`,
`batch-get`, `duplicates`, `*-by-artist-ids`, `list-learning`,
`*-detail` ops) THEN the system SHALL CONTINUE TO document them
exactly as today: same command strings, same flags, same paragraph
positions in the Checklist. The new section adds combined-search
examples; it does not reorganise or remove existing content.

3.15 WHEN the fix ships THEN the existing "Pattern" section's
mention of `search-songs` SHALL CONTINUE TO be present (and MAY
remain as-is, or be pruned to one sentence that points at the new
examples section). The requirement is that the `search-songs`
pointer does not disappear — the detailed examples are an addition,
not a replacement.

## Deriving the Bug Conditions

This spec covers four independent defects, so each has its own bug
condition and property. Bugs 3 and 4 are complementary documentation
touches on the same failure mode (agent picks the wrong command);
they remain separate bug-condition blocks because they target
different files and different kinds of evidence.

### Bug 1 — AMQ importer input shape

**Bug Condition:**

```pascal
FUNCTION isBugConditionImporter(invocation)
  INPUT: invocation of type CLIInvocation
          (an argv + payload pair representing a call to
           import_plan.py: which input flag was used, and the
           parsed JSON payload the caller wants classified)
  OUTPUT: boolean

  // The bug is triggered when any of the following is true of the
  // invocation against the CLI surface that exists today:
  //
  //   (a) the payload is the raw AMQ export shape (a JSON object
  //       with a `songs` array) AND the current CLI cannot accept
  //       it on any channel — today the sole channel is --input
  //       (file path) which requires the flat array shape.
  //
  //   (b) the caller wants to pass JSON inline on the command line
  //       (not via a file path) AND the current CLI offers no
  //       inline flag.
  //
  //   (c) the caller wants a flat-array-only channel (internal /
  //       programmatic use, e.g. a tool that has already flattened
  //       and wants the importer to reject any nested AMQ shape it
  //       is accidentally handed) AND the current CLI offers no
  //       such distinction from the file-based legacy --input.
  RETURN isRawAmqShape(invocation.payload)
      OR invocation.inputChannel = "inline-jsonstr"
      OR invocation.inputChannel = "flat-only"
END FUNCTION
```

Where `isRawAmqShape(payload)` is true iff the payload is a JSON
object whose `songs` key holds an array of AMQ song objects (with
arbitrary top-level game-metadata siblings of `songs`), and
`invocation.inputChannel` is the caller's chosen input flag —
`inline-jsonstr` meaning the caller intends to pass JSON text directly
on the command line, and `flat-only` meaning the caller wants a
channel guaranteed to accept only the flat array shape.

**Property (Fix Checking):**

```pascal
// For every invocation meeting the bug condition, the fixed CLI
// routes it through the right new flag (--input-jsonpath for file
// paths, --input-jsonstr for inline JSON, --input-array for
// flat-only), runs the preprocessing stage where applicable to
// convert any raw AMQ payload to the flat five-field shape, and
// produces the same plan the classifier produces on an equivalent
// already-flat input.
FOR ALL invocation WHERE isBugConditionImporter(invocation) DO
  result ← importPlan'(invocation)
  flat   ← toFlatFiveField(invocation.payload)
                // extracts and flattens `songs` for raw AMQ payloads;
                // identity for already-flat payloads; undefined for
                // --input-array invocations against raw AMQ (see
                // rejection clause below).
  IF invocation.inputChannel = "flat-only"
     AND isRawAmqShape(invocation.payload) THEN
    // --input-array explicitly rejects raw AMQ nested JSON.
    ASSERT result.exitCode = 1
    ASSERT result.error.code = "INVALID_INPUT"
  ELSE
    expected ← importPlan'(
                 CLIInvocation(
                   inputChannel = "legacy-flat",
                   payload      = flat
                 )
               )
    ASSERT result.exitCode = 0
    ASSERT result.plan     = expected.plan
  END IF
END FOR
```

**Preservation Goal:**

```pascal
// For every invocation NOT meeting the bug condition — in particular,
// flat-array-via-legacy --input (or the positional path equivalent),
// malformed files, missing files, and non-array/non-object JSON on
// the legacy surface — the fixed CLI behaves identically to the
// original: same exit code, same stdout envelope, same stderr
// envelope, same plan.
FOR ALL invocation WHERE NOT isBugConditionImporter(invocation) DO
  ASSERT importPlan(invocation) = importPlan'(invocation)
END FOR
```

### Bug 2 — `graduate` doesn't pin level to MAX_LEVEL

**Bug Condition:**

```pascal
FUNCTION isBugConditionGraduate(L)
  INPUT: L of type LearningRow
  OUTPUT: boolean

  // The bug is triggered when graduate() is asked to flip a
  // non-graduated row whose level is not already at MAX_LEVEL.
  RETURN L.graduated = 0
     AND L.level       < MAX_LEVEL
END FUNCTION
```

**Property (Fix Checking):**

```pascal
// After graduate, a row that met the bug condition ends with both
// graduated = 1 AND level = MAX_LEVEL, matching the state produced
// by levelup at MAX_LEVEL.
FOR ALL L WHERE isBugConditionGraduate(L) DO
  after ← graduate'(L)
  ASSERT after.graduated = 1
  ASSERT after.level     = MAX_LEVEL
  ASSERT after.id        = L.id
  ASSERT after.song_id   = L.song_id
  ASSERT after.created_at = L.created_at
END FOR
```

**Preservation Goal:**

```pascal
// For every learning row NOT meeting the bug condition —
// already-graduated rows (no-op path) and rows already at MAX_LEVEL
// being graduated for the first time — the fixed graduate behaves
// identically to the original.
FOR ALL L WHERE NOT isBugConditionGraduate(L) DO
  ASSERT graduate(L) = graduate'(L)
END FOR
```

**Key Definitions:**

- **MAX_LEVEL**: `_common.MAX_LEVEL = 19`, the final index of
  `DEFAULT_LEVEL_UP_PATH`.
- **F (importPlan / graduate)**: the scripts as they exist today on
  `mainline`.
- **F' (importPlan' / graduate')**: the scripts after this fix.
- **`--input-jsonpath <path>`**: new CLI flag on `import_plan.py`
  that reads a JSON file at `<path>` and accepts either the raw AMQ
  export shape (JSON object with a `songs` array, plus arbitrary
  top-level game-metadata siblings) or the legacy flat array shape.
  The CLI dispatches internally based on the parsed payload.
- **`--input-jsonstr <json>`**: new CLI flag on `import_plan.py`
  that parses its argument as a JSON string in place (no file read)
  and accepts the same two payload shapes as `--input-jsonpath`.
  Intended for callers that already have the JSON text in hand.
- **`--input-array <json>`**: new CLI flag on `import_plan.py`
  that parses its argument as a JSON string in place and accepts
  **only** the flat array shape. Intended for internal /
  programmatic callers that have already flattened; explicitly
  rejects the raw AMQ object shape with `INVALID_INPUT` so an
  internal caller cannot accidentally feed nested AMQ JSON through
  this door.
- **Preprocessing stage**: the internal AMQ-to-flat step that sits
  between the CLI front door and the classifier. When the payload
  arriving through any of the three new flags is the raw AMQ export
  shape, preprocessing extracts the `songs` array and flattens each
  AMQ song object to the five-field shape
  (`artist_name`, `song_name`, `show_name`, `vintage`, `media_url`)
  the classifier consumes. For already-flat payloads it is the
  identity. Downstream steps (URL-decoding,
  `resolved` / `auto_completable` / `ambiguous` bucketing,
  `SONG_INVARIANT_VIOLATION` handling, plan output) all operate on
  the output of this stage regardless of which input channel was
  used.
- **Legacy `--input` surface**: the CLI surface that exists today on
  `mainline` — `--input <path>` plus the positional path equivalent
  — which accepts only the flat array shape. Its treatment under the
  fix (flat-only vs. deprecated alias of `--input-jsonpath`) is
  deferred to the design phase; the regression requirement is that
  existing flat-array-via-legacy callers do not break.

### Bug 3 — skills documentation doesn't rank dedicated commands above raw CRUD

Unlike Bugs 1 and 2, the "input" here is not a runtime value — it is
the documentation set itself. The bug condition is a predicate over
the tree of skill documents, the property is checked against the
rendered text, and the preservation goal is that no existing command
listing is lost as collateral damage.

**Bug Condition:**

```pascal
FUNCTION isBugConditionSkillsGuidance(D)
  INPUT: D of type SkillsDocSet
          (the tree rooted at skills/, i.e. skills/README.md plus
           every skills/*/SKILL.md reachable from it)
  OUTPUT: boolean

  // The bug is triggered when D contains no globally-reachable
  // statement preferring dedicated commands over raw data.py CRUD,
  // AND no accompanying named example of a contract-breaking
  // raw-CRUD path. Both parts must be missing for the bug to hold;
  // the fix must add both.
  RETURN NOT hasGloballyReachableStatement(
             D,
             "prefer dedicated commands over raw data.py CRUD"
         )
      OR NOT hasNamedWorkedExample(
             D,
             "contract-breaking raw-CRUD path"
         )
END FUNCTION
```

Where `hasGloballyReachableStatement(D, claim)` is true iff the claim
appears in a location every skill links back to (today: the top-level
`skills/README.md`, or any future page playing the same role), and
`hasNamedWorkedExample(D, topic)` is true iff the guidance is
accompanied by at least one concrete contrast (e.g. the
`data.py update --kind learning --data '{"graduated": 1}'` vs
`learning.py graduate --ids <id>` pairing).

**Property (Fix Checking):**

```pascal
// After the fix, a textual search of the documented skill set D'
// for the phrase "dedicated command" (case-insensitive, or an
// equivalent author-chosen term covered by a synonym set) lands in
// a globally-reachable location AND that match is accompanied by at
// least one concrete worked example naming an invariant the
// dedicated command preserves that the raw-CRUD path does not.
FOR ALL D' WHERE D' = fixedSkillsDocs() DO
  match ← textSearch(
            D',
            /dedicated command/i,
            scope = "globally-reachable"
          )
  ASSERT match ≠ ∅
  ASSERT hasNamedWorkedExample(
           D',
           "contract-breaking raw-CRUD path"
         )
  ASSERT namesInvariant(
           match.context,
           "graduated ↔ level = MAX_LEVEL"
         )
    OR   namesInvariant(
           match.context,
           any_other_dedicated_command_invariant
         )
END FOR
```

**Preservation Goal:**

```pascal
// For every command documented in any SKILL.md at spec start, the
// fixed documentation still documents it in the same skill file
// with the same command string and subcommand. Equivalently: no
// command listing silently disappears as a side effect of adding
// the preference guidance.
FOR ALL (skillFile, commandString, subcommand)
        WHERE documentedIn(
                skillSetAtSpecStart(),
                skillFile,
                commandString,
                subcommand
              ) DO
  ASSERT documentedIn(
           fixedSkillsDocs(),
           skillFile,
           commandString,
           subcommand
         )
END FOR

// And: data.py remains documented with its full set of subcommands
// (create, update, delete, bulk-reassign). The guidance adds a
// preference, not a removal.
FOR ALL sub IN {"create", "update", "delete", "bulk-reassign"} DO
  ASSERT dataPyDocumented(fixedSkillsDocs(), sub)
END FOR
```

**Key Definitions:**

- **D (skillSetAtSpecStart)**: the tree of skill documents as they
  exist at the start of this spec — `skills/README.md` plus the six
  `skills/*/SKILL.md` bodies reachable from it.
- **D' (fixedSkillsDocs)**: the same tree after this fix ships.
- **Globally-reachable**: a location every agent path reaches,
  regardless of which skill entry point they start from. Today that
  is `skills/README.md` (every `SKILL.md` links back to it). The
  requirement is on the reachability, not the specific filename.
- **Dedicated command**: a script-subcommand pair that encodes a
  business invariant atomically — e.g. `learning.py graduate`,
  `learning.py levelup`, `learning.py batch`, `merge_artists.py`,
  `cleanup.py`, and the `import_plan.py` → `import_resolve.py` →
  `add_play_history.py` pipeline. Contrast with `data.py` CRUD,
  which writes straight to tables and bypasses these invariants.
- **Counterexample for Bug 3**: the raw-CRUD graduate path —
  `data.py update --kind learning --id <id> --data '{"graduated": 1}'`
  — which succeeds today, writes valid SQL, and (post Bug 2 fix)
  leaves `level` inconsistent with `graduated`, visibly diverging
  from what `learning.py graduate --ids <id>` would have produced.

### Bug 4 — `searching-library` SKILL.md lacks worked combined-search examples

Structurally parallel to Bug 3 — the "input" is a doc file, not a
runtime value. The bug is scoped to a single SKILL.md rather than
the whole skill tree, and the evidence is the presence or absence of
concrete `search-songs` invocations with specific flag combinations.

**Bug Condition:**

```pascal
FUNCTION isBugConditionCombinedSearchExamples(D)
  INPUT: D of type SkillsDocSet
  OUTPUT: boolean

  // The bug is triggered when the `searching-library` SKILL.md
  // lacks a worked example for any of the four combined-intent
  // pairings. Any single missing pairing is enough to trigger.
  file ← D.fileByPath("skills/searching-library/SKILL.md")
  RETURN NOT hasWorkedExample(file, {song_term, show_term})
      OR NOT hasWorkedExample(file, {song_term, artist_term})
      OR NOT hasWorkedExample(file, {artist_term, show_term})
      OR NOT hasWorkedExample(file, {song_term, show_term, artist_term})
END FUNCTION
```

Where `hasWorkedExample(file, flagSet)` is true iff the file
contains a concrete `scripts/query.py search-songs` invocation that
uses exactly the flags in `flagSet` (not a superset, not a subset),
accompanied by at least one natural-language user-intent framing.

**Property (Fix Checking):**

```pascal
// For the fixed doc set D', the searching-library SKILL.md
// contains all four worked examples and each is paired with a
// concrete user-intent framing.
FOR ALL D' WHERE D' = fixedSkillsDocs() DO
  file ← D'.fileByPath("skills/searching-library/SKILL.md")
  ASSERT hasWorkedExample(file, {song_term, show_term})
  ASSERT hasWorkedExample(file, {song_term, artist_term})
  ASSERT hasWorkedExample(file, {artist_term, show_term})
  ASSERT hasWorkedExample(file, {song_term, show_term, artist_term})
  FOR ALL flagSet IN {
        {song_term, show_term},
        {song_term, artist_term},
        {artist_term, show_term},
        {song_term, show_term, artist_term}
      } DO
    ASSERT hasUserIntentFraming(
             nearbyContext(file, flagSet),
             "natural-language combined-intent question"
           )
  END FOR
END FOR
```

**Preservation Goal:**

```pascal
// For every paragraph, Checklist bullet, or command reference
// present in skills/searching-library/SKILL.md at spec start, the
// fixed file still contains that content (possibly rephrased but
// still covering the same commands and flags). No op is silently
// undocumented.
FOR ALL (script, subcommand, flag)
        WHERE documentedIn(
                skillSetAtSpecStart().fileByPath(
                  "skills/searching-library/SKILL.md"
                ),
                script, subcommand, flag
              ) DO
  ASSERT documentedIn(
           fixedSkillsDocs().fileByPath(
             "skills/searching-library/SKILL.md"
           ),
           script, subcommand, flag
         )
END FOR
```

**Key Definitions:**

- **Combined-intent question**: a natural-language user query that
  names two or more of {song name, show name, artist name} at once.
  Distinct from a single-kind question ("find songs called 'Again'"),
  which `search` already covers.
- **search-songs**: the `scripts/query.py search-songs` subcommand.
  Takes `--song-term`, `--show-term`, `--artist-term`, all optional,
  ANDed. Returns a `{filters, count, results}` envelope with
  detail-shaped rows per result. Already documented in
  `skills/searching-library/SKILL.md`; this fix adds worked examples.
- **Counterexample for Bug 4**: an agent answering "songs from FMA
  by Yui" by running three `search` calls
  (`--kind show --term "FMA"`, `--kind artist --term "Yui"`,
  `--kind song --term ...`) and intersecting ids by hand. Strictly
  worse than one `search-songs --show-term "FMA" --artist-term "Yui"`
  call: three DB roundtrips instead of one, no detail attachment,
  no byte-stable ordering.
