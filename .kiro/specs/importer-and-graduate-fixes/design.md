# Importer and Graduate Fixes — Bugfix Design

## Overview

This spec covers four independent defects that all sit on the
user-facing surface of the local library tooling:

- **Bug 1 — `scripts/import_plan.py` only accepts one input shape.**
  The current CLI has a single input channel (`--input <path>` or a
  positional path) that will only load a pre-flattened JSON array of
  five-field entries. There is no way to hand it the JSON AMQ itself
  produces (a nested object with a top-level `songs` array), no way to
  pass JSON text inline, and no dedicated flat-only channel for
  internal callers. The fix adds three new mutually-exclusive input
  flags and an internal AMQ-to-flat preprocessing stage in front of
  the existing classifier.
- **Bug 2 — `scripts/learning.py graduate` leaves `level` untouched.**
  Graduating a row via the explicit `graduate` command sets
  `graduated = 1` but does not touch `level`. A row graduated at
  `level = 3` therefore ends in a different observable state than a
  row graduated via `levelup` at `MAX_LEVEL`. The fix extends the
  `graduate` UPDATE to also set `level = MAX_LEVEL` so the two paths
  converge.
- **Bug 3 — `skills/` docs don't rank dedicated commands above raw
  CRUD.** The skills documentation lists every available command but
  never tells an agent to prefer `learning.py graduate` over
  `data.py update`. An agent acting only on the catalog can pick the
  raw-CRUD path and silently produce rows that violate the
  `graduated ↔ level = MAX_LEVEL` invariant Bug 2 establishes. The
  fix adds a short, globally-reachable preference statement to
  `skills/README.md`, anchored by one named worked counter-example
  (the graduate-via-`data.py` case), without removing or rerouting
  any existing content.
- **Bug 4 — `searching-library` SKILL.md lacks worked combined-search
  examples.** The skill already mentions `search-songs` once in its
  "Pattern" paragraph and once in the Checklist, but it does not
  show an agent how to translate a natural-language combined-intent
  question ("songs from show X by artist Y", "the Clannad OP by
  Lia", "which shows does Hikaru Midorikawa sing in?") into the
  corresponding `--song-term` / `--show-term` / `--artist-term`
  invocation. An agent that hasn't internalised the op can fall back
  to chaining three single-kind `search` calls and intersecting ids
  by hand — strictly worse (more DB roundtrips, no detail
  attachment, no byte-stable ordering). The fix adds a short,
  example-driven section inside `skills/searching-library/SKILL.md`
  covering the four combined-intent pairings (song+show, song+artist,
  artist+show, all-three), each with one worked CLI invocation and
  one user-intent framing. This is a documentation fix that
  complements Bug 3: Bug 3 tells the agent to prefer dedicated
  commands in general; Bug 4 shows the agent, on the most natural
  skill for it, exactly what that preference looks like for
  combined-intent search.

Each bug has its own root cause, implementation surface, and test
plan. The four fixes are genuinely independent — none depend on the
others landing first — but they share a single spec because they are
all small contract-level repairs on the same release. Bugs 3 and 4
are two complementary documentation touches on the same failure
mode (agent picks the wrong command) and share a test file but not
an edit location.

This spec does **not** rewrite the packaged tree. We ship the same
`scripts/` and `skills/` directories; only the behavior inside them
changes. There are no schema changes, no new error codes, and no new
top-level scripts. `tests/fixtures/schema.sql` stays byte-identical.

## Glossary

- **Bug_Condition (C)**: The condition that triggers a bug. Each of
  the four bugs has its own `isBugCondition` predicate in
  `bugfix.md`.
- **Property (P)**: The desired behavior when the bug condition
  holds. Each bug has its own property statement.
- **Preservation**: Behavior on inputs that do **not** meet the bug
  condition. The fix must not change it.
- **MAX_LEVEL**: `scripts/_common.MAX_LEVEL`, currently `19`. The
  final index of `DEFAULT_LEVEL_UP_PATH`.
- **Legacy `--input` surface**: The CLI surface on
  `scripts/import_plan.py` that exists today — `--input <path>` and
  the positional path equivalent. Accepts only the flat five-field
  JSON array shape.
- **Flat five-field shape**: A JSON array whose elements are objects
  with keys `artist_name`, `song_name`, `show_name`, `vintage`,
  `media_url`. Extra keys are tolerated and ignored. This is what the
  existing classifier in `import_plan.py` already consumes.
- **Raw AMQ export shape**: A JSON object produced by AMQ's own
  export feature. Its top-level object has a `songs` key holding an
  array of AMQ song objects (with keys like `songArtist`, `songName`,
  `animeEnglishName`, `animeRomajiName`, `vintage`, `audio`,
  `startSample`, `type`, `fromList`, etc.), plus arbitrary
  game-metadata siblings of `songs`.
- **Preprocessing stage**: A new pure function inside
  `scripts/import_plan.py` that converts a raw AMQ payload to the
  flat five-field shape. Identity on already-flat payloads.
- **Dedicated command**: A script-subcommand pair that encodes a
  business invariant atomically (e.g. `learning.py graduate`,
  `learning.py levelup`, `learning.py batch`, `merge_artists.py`,
  `cleanup.py`, and the `import_plan.py` → `import_resolve.py` →
  `add_play_history.py` pipeline).
- **Raw CRUD**: `data.py`'s `create`, `update`, `delete`,
  `bulk-reassign` subcommands, which write directly to tables.

---

## Bug 1 — AMQ importer input shape

### Bug Details

#### Bug Condition

The bug manifests whenever a caller of `scripts/import_plan.py`
wants one of three things that the current CLI cannot express:

1. Load a file that is in the raw AMQ export shape (a JSON object
   with a top-level `songs` array, plus arbitrary game-metadata
   siblings) — the current loader asserts `isinstance(data, list)`
   and rejects everything else with `INVALID_INPUT`.
2. Pass JSON text inline on the command line without writing it to a
   temp file first — the current CLI has no inline input flag.
3. Ask for a flat-array-only channel that rejects nested AMQ JSON on
   purpose (internal or programmatic use) — the legacy `--input`
   doesn't distinguish intent, and under the fix (see decision below)
   still won't.

**Formal specification** (from `bugfix.md`, reproduced here for
traceability):

```
FUNCTION isBugConditionImporter(invocation)
  INPUT: invocation of type CLIInvocation
  OUTPUT: boolean

  RETURN isRawAmqShape(invocation.payload)
      OR invocation.inputChannel = "inline-jsonstr"
      OR invocation.inputChannel = "flat-only"
END FUNCTION
```

#### Examples of the bug today

- A user downloads `amq_song_export-small.json` from AMQ directly and
  runs `python scripts/import_plan.py --input amq_song_export-small.json`.
  Result today: exit 1 with `INVALID_INPUT` ("AMQ input must be a JSON
  array of entries."). Expected: same plan as if the file had been
  manually flattened first.
- A user pipes `jq`-filtered JSON into the importer:
  `python scripts/import_plan.py --input-jsonstr "$(jq ... < amq.json)"`.
  Result today: exit 2 from argparse (`--input-jsonstr` is unknown).
  Expected: same plan as writing the same JSON to a file and passing
  `--input-jsonpath`.
- A programmatic caller that has already flattened the AMQ data wants
  to assert flatness at the CLI boundary:
  `python scripts/import_plan.py --input-array '[{"artist_name":...}]'`.
  Result today: exit 2 from argparse. Expected: same plan as the
  legacy surface on the equivalent file.
- The flat-only channel must also reject raw AMQ on purpose. Passing
  `--input-array '{"songs":[...]}'` today fails for the wrong reason
  (argparse); after the fix it must fail with `INVALID_INPUT` citing
  that `--input-array` is flat-only.

### Expected Behavior

#### Preservation Requirements

**Unchanged behaviors:**

- Every legacy flat-array-against-`--input` invocation produces the
  same plan it produces today (same `resolved` / `auto_completable` /
  `ambiguous` bucketing, same URL-decoded strings, same
  `SONG_INVARIANT_VIOLATION` on two live same-name songs per artist,
  same `media_url` / `show_id` / `show_to_create` carry-through).
- The positional path surface keeps working on flat arrays.
- Missing files, malformed JSON, and non-array/non-object JSON on the
  legacy surface all still produce `INVALID_INPUT` with exit 1.
- `import_plan.py` stays read-only. The SQLite file at
  `db/datasource.db` is byte-identical before and after every
  invocation.
- The `--output` behavior (print summary to stdout, write full plan
  to file) and the no-args help-on-stdout-exit-0 behavior both stay
  as-is.

**Scope of the change:**

Only the input-loading front door changes. The classifier
(`_classify`, `_resolve_show`, URL-decoding, bucket shape) is left
alone. Every new input channel funnels into the same entries list
the classifier already consumes.

### Hypothesized Root Cause

`_load_entries` in `scripts/import_plan.py` opens the file, parses
JSON, and asserts `isinstance(data, list)`. Anything else — including
the raw AMQ object shape that is the natural output of AMQ itself —
is rejected with `INVALID_INPUT`. There is no code path that accepts
the AMQ object, no code path that accepts JSON text by value, and no
argparse wiring to distinguish caller intent. The fix is entirely in
the front of the file: new flags in `_build_parser`, a tiny
preprocessing function, a discriminator step, and a slightly richer
dispatch in `_run`.

### Correctness Properties

> See section "Correctness Properties" at the end of this document
> for the single source of truth. Property 1 covers the Bug 1 fix
> surface; Property 2 covers Bug 1 preservation.

### Fix Implementation

#### Decision 1 — CLI flag layout (chosen: Option B)

**Decision:** Option B. Leave the legacy `--input` and positional
path surface **strictly flat-only**, exactly as they are today. The
three new flags live alongside it without overlapping.

**Rationale:** Option A (turning `--input` into a silent alias of
`--input-jsonpath` that grows AMQ-shape acceptance) would change the
observable behavior of a flag that is used by existing scripts and
skills documentation. The requirements only demand that existing
flat-via-legacy callers keep working (R3.1, R3.2). Option B is the
minimum behavior change that satisfies that constraint; every new
capability lives behind a new flag, so a reader of `--help` can tell
which entry point does what without reading the source.

**argparse structure:**

```
import_plan.py
  [--input PATH | <positional path>]      # legacy, flat-only
  [--input-jsonpath PATH
   | --input-jsonstr JSON
   | --input-array JSON]                   # new, mutually exclusive
  [--output PATH]
```

Implementation shape in `_build_parser`:

- The legacy `--input` argument and the `positional_input` argument
  stay on the top-level parser unchanged.
- A new mutually-exclusive group is added via
  `parser.add_mutually_exclusive_group(required=False)`. The three
  new flags (`--input-jsonpath`, `--input-jsonstr`, `--input-array`)
  are added to it. The group is **not** `required=True` because the
  legacy `--input` / positional path must still be accepted on its
  own; `required=True` would force the new flags every time.
- A manual validation step in `_run` enforces the R2.7 rule: at least
  one input channel must be supplied. Specifically, if none of
  `args.input_path`, `args.positional_input`, `args.input_jsonpath`,
  `args.input_jsonstr`, and `args.input_array` is set, raise
  `KnownError("INVALID_INPUT", "No input: pass --input-jsonpath, --input-jsonstr, --input-array, --input, or a positional path.")`.
- A second manual validation step enforces R2.6 at the group
  boundary: if any of the three new flags is set **and** a legacy
  `--input` / positional path is also set, raise
  `KnownError("INVALID_INPUT", "Mix of legacy --input and new input flags is not supported.")`.
  argparse's mutually-exclusive group already rejects two-of-three
  from the new flags with its own message; we do not re-validate
  that case.
- `--help` output lists the legacy surface first (to match historical
  docs), then the three new flags inside a "Input" section. The
  `skills/importing-amq-songs/SKILL.md` update below mirrors the same
  ordering.

#### Decision 2 — Payload shape discrimination

**Decision:** Discriminate strictly by parsed JSON shape. Pin the
rule in one helper, `_discriminate(parsed)`, that returns one of
three tags: `"flat"`, `"raw_amq"`, or raises `INVALID_INPUT`.

Rule:

- If `isinstance(parsed, list)` → `"flat"`. Pass straight to the
  classifier.
- If `isinstance(parsed, dict) and isinstance(parsed.get("songs"), list)` →
  `"raw_amq"`. Run the preprocessing stage to produce the flat
  five-field list.
- Anything else (JSON scalar, object without `songs`, object whose
  `songs` is not a list) → `KnownError("INVALID_INPUT", "Input must be a JSON array (flat shape) or a JSON object with a `songs` array (raw AMQ shape).", {"got_type": type(parsed).__name__})`.

`--input-array` calls `_discriminate` and additionally rejects the
`"raw_amq"` tag up front, satisfying R2.5:
`KnownError("INVALID_INPUT", "--input-array is flat-only; nested AMQ objects are not accepted on this channel.")`.

This keeps the discriminator a pure function of the parsed value,
independent of which flag was used — the flag only controls the
post-discrimination gate (flat-only channel says "no" to `raw_amq`).

#### Decision 3 — Raw-AMQ preprocessing: field mapping and strictness

**Decision:** Translate each AMQ song object with an explicit field
mapping table, reject the whole file on any missing required field,
and silently drop every other field.

**Field mapping table** (raw AMQ key → flat five-field key):

| Raw AMQ key(s) tried, in order | Flat key      | Required? |
|--------------------------------|---------------|-----------|
| `songArtist`, `artist_name`    | `artist_name` | yes       |
| `songName`, `song_name`        | `song_name`   | yes       |
| `animeEnglishName`, `animeRomajiName`, `show_name` | `show_name` | yes |
| `vintage`, `animeVintage`      | `vintage`     | yes       |
| `audio`, `media_url`, `MP3`, `mp3`, `urlMap.catbox.0` | `media_url` | no — defaults to `""` |

Notes on the mapping:

- The `songArtist` / `songName` / `animeEnglishName` / `vintage` names
  are what the AMQ export referenced from the repo-root `README.md`
  (`amq_song_export-small.json`) uses. The flat names
  (`artist_name` / `song_name` / `show_name`) are what the current
  classifier consumes; accepting both in the same preprocessor makes
  the function idempotent on already-flat entries and lets it also
  accept a few forgiving variants.
- `animeEnglishName` wins over `animeRomajiName` when both are
  present. The existing library matches shows by `show.name` /
  `show.vintage` with `show.name_romaji` as a separate column, so
  using the English name as the primary `show_name` is consistent
  with how the classifier looks up the `show` row today.
- `media_url` is explicitly *optional* — the classifier already
  accepts empty `media_url` values and carries them through. Missing
  audio defaults to `""`, matching the existing `_load_entries`
  default for missing keys.
- Extra AMQ-native fields (`type`, `fromList`, `startSample`,
  `videoLength`, any `urlMap` keys beyond the first one picked, any
  unknown keys) are silently dropped. No warnings, no errors.
- Top-level siblings of `songs` (game metadata, quiz settings, export
  timestamps, etc.) are silently dropped. Only `root["songs"]` is
  read.

**Strictness on missing required fields:** If any of `artist_name`,
`song_name`, `show_name`, or `vintage` cannot be resolved for any
AMQ song entry, abort the whole file with
`KnownError("INVALID_INPUT", "AMQ song at index {i} is missing required field {fieldname}.", {"index": i, "missing_field": fieldname, "available_keys": sorted(entry.keys())})`.

Rationale for whole-file reject rather than skip-and-continue: the
plan output is used downstream to drive `import_resolve.py` and
`add_play_history.py`, and silently dropping songs from an AMQ file
would be a silent data-loss path. The requirements
(`bugfix.md` clause 2.8) already commit to "every downstream step
operates on a uniform intermediate representation" — a malformed AMQ
entry cannot produce that representation, so it is correct to abort.
This also matches the spirit of the existing `_load_entries` loop,
which raises on any non-dict entry.

**Function shape:**

```python
def _flatten_amq(payload: dict) -> list[dict]:
    """Convert a raw AMQ export object to the flat five-field list.

    Expects `payload["songs"]` to be a list. Caller discriminated
    the shape; this function assumes it.
    """
    flat: list[dict] = []
    for i, entry in enumerate(payload["songs"]):
        if not isinstance(entry, dict):
            raise _common.KnownError(
                "INVALID_INPUT",
                f"AMQ song at index {i} is not a JSON object.",
                {"index": i},
            )
        flat.append(_amq_entry_to_flat(entry, i))
    return flat
```

`_amq_entry_to_flat(entry, i)` runs the field mapping table: for
each required flat key, iterate the candidate raw keys in order,
pick the first one whose value is a non-empty string, and raise
`INVALID_INPUT` if none match. For `media_url`, pick the first
non-empty value from the candidate list, default to `""` if none
match.

This function is a pure transformation on a dict. It lives in
`scripts/import_plan.py` alongside `_load_entries` and is covered by
a dedicated unit test (see Testing Strategy below).

#### Code changes summary

**File:** `scripts/import_plan.py`

1. `_build_parser()`: add `--input-jsonpath`, `--input-jsonstr`,
   `--input-array` inside a new mutually-exclusive group. Keep the
   legacy `--input` and positional argument unchanged.
2. New helper `_discriminate(parsed) -> str`: returns `"flat"` or
   `"raw_amq"`, raises `INVALID_INPUT` otherwise.
3. New helper `_amq_entry_to_flat(entry, i) -> dict`: the field
   mapping table.
4. New helper `_flatten_amq(payload) -> list[dict]`: loops
   `payload["songs"]` and calls `_amq_entry_to_flat`.
5. New helper `_entries_from_parsed(parsed, *, channel) -> list[dict]`:
   runs `_discriminate`, enforces the flat-only gate for the
   `--input-array` channel, runs `_flatten_amq` for raw AMQ, then
   runs the existing per-entry URL-decode-and-normalise loop from
   `_load_entries`. Returning a list of five-field dicts keeps the
   classifier's input type unchanged.
6. `_load_entries(path)` stays as the legacy code path. It only has
   to keep accepting the flat array shape, and its
   `isinstance(data, list)` check continues to enforce that.
   Alternatively, refactor it to call `_entries_from_parsed` with a
   "legacy" channel tag that rejects `raw_amq` — this is a clean
   structural choice, but only if it does not change observable
   behavior on the legacy path. Pick the no-refactor option for this
   spec: Option B already commits to not changing the legacy surface.
7. `_run(args)`: compute which input channel fired, load the entries
   via the matching path (`_load_entries` for legacy;
   `_entries_from_parsed` for each new flag with the parsed JSON),
   then pass the entries to the existing classifier loop unchanged.

**Files explicitly not touched:** `_classify`, `_resolve_show`,
`main`, `_common`.

---

## Bug 2 — `graduate` doesn't pin `level` to `MAX_LEVEL`

### Bug Details

#### Bug Condition

The bug triggers on any learning row that is not yet graduated and
whose stored `level` is below `MAX_LEVEL`. Running
`learning.py graduate --ids <id>` on such a row flips `graduated` to
`1` but leaves `level` at its original value, producing a row in a
state that `levelup`-at-`MAX_LEVEL` would never produce.

**Formal specification** (from `bugfix.md`):

```
FUNCTION isBugConditionGraduate(L)
  RETURN L.graduated = 0 AND L.level < MAX_LEVEL
END FUNCTION
```

#### Examples of the bug today

- A user at `level = 3` decides they've fully memorised a song and
  runs `learning.py graduate --ids <id>`. Today the row ends at
  `graduated = 1, level = 3`. Downstream reads (`search-songs`
  learning summary, `list-learning`, `query.py learning-detail`)
  render `display_level = 4` for a song the user is done with.
- The same song reached by `levelup` (six more successful reviews to
  get from 3 to 19, then one more at 19 to graduate) ends at
  `graduated = 1, level = 19, display_level = 20`. Two different
  paths to `graduated = 1` produce two different row states.

### Expected Behavior

#### Preservation Requirements

**Unchanged behaviors:**

- `graduate` on an already-graduated row stays a no-op success
  (R3.6). `level`, `graduated`, `created_at`, `updated_at`,
  `last_level_up_at`, `level_up_path` all untouched.
- `graduate` on a row whose `level` is already `MAX_LEVEL`
  (non-graduated) still flips `graduated` to `1` and stamps
  `updated_at`. The `SET level = MAX_LEVEL` is a redundant write in
  this case, producing the same observable result. We do not need a
  separate SQL branch for it.
- `graduate` with a missing id in the batch still aborts with
  `NOT_FOUND` and writes nothing (R3.7). The transaction wrapper in
  `main()` already handles this; the SQL change does not alter it.
- `levelup` is unchanged — it already auto-graduates at `MAX_LEVEL`
  with `level` staying at `MAX_LEVEL` per R6.6 / R3.8.
- `id`, `song_id`, `created_at`, `level_up_path`, and
  `last_level_up_at` are preserved on the graduating row (R3.9).
- `last_level_up_at` is **not** updated by `graduate`, even after the
  fix. This is intentional: graduating via `graduate` is not a
  "level-up event" (the user is declaring the song finished, not
  reporting a successful recall at a given level). The fix pins
  `level` to `MAX_LEVEL` but does not pretend a level-up occurred.
  This also keeps `graduate` behaviorally aligned with the
  `levelup`-at-`MAX_LEVEL` path, which also leaves
  `last_level_up_at` untouched per R6.6.

**Response-payload shape:** The `{"updated": [...]}` envelope shape
returned by `_cmd_graduate` does not change. Only the **values** in
the payload shift: `level` and `display_level` in each entry now
reflect the pinned `MAX_LEVEL` for rows that met the bug condition.
Rows that were already graduated continue to report their pre-fix
`level`, so no-op calls on old data do not surprise callers by
silently upgrading their reported level.

### Hypothesized Root Cause

`_cmd_graduate` in `scripts/learning.py` runs
`UPDATE learning SET graduated = 1, updated_at = ? WHERE id = ?` on
every non-graduated id in the batch. The UPDATE never touches
`level`. The fix is to extend the SET clause in that single
statement.

### Fix Implementation

**File:** `scripts/learning.py`

**Function:** `_cmd_graduate`

**Change:** Rewrite the UPDATE and the corresponding response row.

Before:

```python
conn.execute(
    "UPDATE learning SET graduated = 1, updated_at = ? WHERE id = ?",
    (now, lid),
)
updated.append(
    {
        "id": lid,
        "level": row["level"],
        "display_level": row["level"] + 1,
        "graduated": 1,
        "updated_at": now,
    }
)
```

After:

```python
conn.execute(
    "UPDATE learning SET graduated = 1, level = ?, updated_at = ? WHERE id = ?",
    (_common.MAX_LEVEL, now, lid),
)
updated.append(
    {
        "id": lid,
        "level": _common.MAX_LEVEL,
        "display_level": _common.MAX_LEVEL + 1,
        "graduated": 1,
        "updated_at": now,
    }
)
```

**What stays the same:**

- The already-graduated branch above it. That branch still returns
  the row's existing `level` unchanged and does not run any UPDATE.
- The `NOT_FOUND` preflight. The SQL change is inside the per-id
  loop, after the preflight has passed for every id in the batch.
- The transaction wrapper in `main()`. `_cmd_graduate` still runs
  inside `BEGIN IMMEDIATE` / `COMMIT` exactly as before.
- `level_up_path` and `last_level_up_at` columns. Neither appears in
  the new SET clause.

The change is one new column in the SET list plus the matching value
in the response. No other function in `learning.py` is touched.

---

## Bug 3 — skills docs don't rank dedicated commands above raw CRUD

### Bug Details

#### Bug Condition

The bug triggers when the skills documentation set, viewed as a whole,
lacks a globally-reachable preference statement ("use dedicated
commands when one exists, fall back to `data.py` only when one
doesn't") or lacks a named worked counter-example. Both parts must be
present; the fix must add both.

**Formal specification** (from `bugfix.md`):

```
FUNCTION isBugConditionSkillsGuidance(D)
  RETURN NOT hasGloballyReachableStatement(
             D, "prefer dedicated commands over raw data.py CRUD"
         )
      OR NOT hasNamedWorkedExample(
             D, "contract-breaking raw-CRUD path"
         )
END FUNCTION
```

#### Examples of the bug today

- An agent reading `skills/README.md` sees six skills listed with
  their commands and sees no ranking among them. Nothing in the tree
  says `learning.py graduate` is preferred over
  `data.py update --kind learning --data '{"graduated": 1}'`.
- Post Bug 2 fix, the raw-CRUD path produces an observably wrong row
  (graduated with `level` not equal to `MAX_LEVEL`), but the docs
  give no warning that this is the outcome of picking the raw-CRUD
  path.

### Expected Behavior

#### Preservation Requirements

**Unchanged behaviors:**

- Every command listed in any `SKILL.md` at spec start is still
  listed in the same file with the same command string and
  subcommand after the fix (R3.13).
- `data.py` stays fully documented with its four subcommands
  (`create`, `update`, `delete`, `bulk-reassign`). The fix adds
  preference guidance, not a removal (R3.10).
- The existing `data.py` reference inside
  `skills/importing-amq-songs/SKILL.md` (the `SONG_INVARIANT_VIOLATION`
  note that points at `scripts/data.py delete --kind song`) stays
  unchanged (R3.11).
- Each `SKILL.md` remains standalone-readable for its own scope
  (R3.12). The new guidance complements `skills/README.md`; it does
  not require per-skill bodies to be re-read end-to-end.
- No skill is rerouted to or away from `data.py` as a side effect
  (R3.11).

### Hypothesized Root Cause

`skills/README.md` was written as a navigational index — it answers
"which skill applies to which task" but not "which command within
the skill's toolbox is the right one to reach for". The absence of
an explicit preference is a documentation gap, not a bug in any
script.

### Fix Implementation

#### Decision 4 — Where the guidance lands

**Decision:** A new, short `## Using Dedicated Commands` section
inserted into `skills/README.md` immediately after the opening
paragraph, before the `## Common Workflows` section.

**Rationale:** The placement constraint in R2.15 is reachability
from every skill entry point. Every `SKILL.md` already links back to
`skills/README.md` implicitly (they are navigated to from it); an
agent landing on an individual skill can be directed to
`skills/README.md` by a single pointer if needed, but the primary
read-path — an agent orienting itself by reading `skills/README.md`
first — is where the guidance is maximally visible. Placing it above
the workflows, but below the one-paragraph orientation, makes it
globally reachable (R2.15) without front-loading the file to the
point of obscuring the navigation tables.

**Content outline** (concrete draft follows in the tasks phase; this
section pins the shape):

- One paragraph stating the preference: "When a dedicated command
  exists for the task you need to do, use it. `data.py` CRUD
  (`create`, `update`, `delete`, `bulk-reassign`) is a last-resort
  fallback for work that no dedicated command covers."
- One worked counter-example naming the invariant:
  `data.py update --kind learning --id <id> --data '{"graduated": 1}'`
  vs. `learning.py graduate --ids <id>`. The dedicated command
  preserves the invariant `graduated ↔ level = MAX_LEVEL`; the raw
  path does not.
- One pointer back at the skills table below: "The dedicated
  commands for each skill are listed in the Skills table below. If
  the task you need matches one of those skills, start there."
- One explicit statement that `data.py` remains fully documented for
  the cases it is genuinely needed (e.g. the
  `SONG_INVARIANT_VIOLATION` cleanup path already called out in
  `importing-amq-songs/SKILL.md`).

Length budget: ≤ 12 lines of Markdown. The goal is a paragraph an
agent reads once on entry, not a new essay.

#### Decision 5 — Per-skill bodies

**Decision:** Do not bloat individual `SKILL.md` bodies. They stay
standalone-readable for their own scope (R3.12). The only exception
is `skills/importing-amq-songs/SKILL.md`, which is updated for Bug 1
(see next section) — that update is about the new CLI flags, not
about the preference guidance.

The existing `data.py` reference inside
`importing-amq-songs/SKILL.md` (the `SONG_INVARIANT_VIOLATION`
cleanup tip) stays exactly as-is. It is a legitimate last-resort
use: there is no dedicated command for "soft-delete the extra
duplicate song", and the skill already documents it as a cleanup
step specific to this error path.

#### Decision 6 — `skills/importing-amq-songs/SKILL.md` update (Bug 1 follow-on)

**Decision:** Update `skills/importing-amq-songs/SKILL.md` in this
same spec to document:

- The new flags (`--input-jsonpath`, `--input-jsonstr`,
  `--input-array`) in the "Checklist" / "Input shape" sections.
- The fact that the raw AMQ export JSON is now accepted directly by
  `--input-jsonpath` — callers no longer need to pre-flatten.
- The legacy `--input` / positional surface stays documented as the
  flat-only path, with a one-line note that it is kept for
  compatibility with existing scripts.

This is not strictly required by `bugfix.md` (R3.13 only forbids
*removing* existing command documentation), but leaving the body out
of sync with the new CLI would make the skill misleading. Pin it as
a named design item so the tasks phase produces it; do not wait for
a follow-up spec.

The AMQ-to-flat field mapping table (Decision 3) is referenced from
the body but lives in `skills/importing-amq-songs/references/plan-shape.md`
under a new "Raw AMQ input mapping" subsection, keeping the main
`SKILL.md` terse.

---

## Bug 4 — `searching-library` SKILL.md combined-search examples

### Bug Details

#### Bug Condition

The bug triggers when `skills/searching-library/SKILL.md` lacks a
worked example for any of the four combined-intent pairings that
`search-songs` is built to serve: song+show, song+artist,
artist+show, and all-three together. Any single missing pairing is
enough to trigger the bug; the fix must add all four.

**Formal specification** (from `bugfix.md`, reproduced here for
traceability):

```
FUNCTION isBugConditionCombinedSearchExamples(D)
  INPUT: D of type SkillsDocSet
  OUTPUT: boolean

  file ← D.fileByPath("skills/searching-library/SKILL.md")
  RETURN NOT hasWorkedExample(file, {song_term, show_term})
      OR NOT hasWorkedExample(file, {song_term, artist_term})
      OR NOT hasWorkedExample(file, {artist_term, show_term})
      OR NOT hasWorkedExample(file, {song_term, show_term, artist_term})
END FUNCTION
```

Where `hasWorkedExample(file, flagSet)` requires a concrete
`scripts/query.py search-songs` invocation that uses exactly the
flags in `flagSet`, accompanied by at least one natural-language
user-intent framing nearby in the same markdown section.

#### Examples of the bug today

- An agent asked "what's the opening of Clannad by Lia?" reads
  `skills/searching-library/SKILL.md` top-to-bottom, sees the
  "Pattern" section's single mention of `search-songs`, and still
  reaches for `search --kind song --term "dango"` followed by a
  `song-detail` roundtrip — because the pattern paragraph does not
  show the shape `search-songs --song-term "dango" --show-term "Clannad"`
  would take on for this exact user intent.
- An agent asked "songs from FMA by Yui" decomposes the question
  into three `search` calls —
  `search --kind show --term "FMA"`,
  `search --kind artist --term "Yui"`,
  `search --kind song --term ...` — and intersects ids in Python.
  Three DB roundtrips, no detail attachment, no byte-stable
  ordering. One `search-songs --show-term "FMA" --artist-term "Yui"`
  call would have returned the same rows in one round trip, with
  artist and show and `media_urls` already attached.
- An agent asked "which shows does Hikaru Midorikawa sing in?" runs
  `search --kind artist --term "Hikaru Midorikawa"` to get the
  artist id, then `shows-by-artist-ids --artist-ids <id>` — which
  works, but only because this agent already knew about the
  cross-reference op. A less-fluent agent staring at the same
  SKILL.md would have no signal that `search-songs --artist-term
  "Hikaru Midorikawa"` returns every song by that artist along with
  the shows it's linked to, in a single op.

### Expected Behavior

#### Preservation Requirements

**Unchanged behaviors:**

- Every query `skills/searching-library/SKILL.md` already documents
  (the single-kind `search`, `get`, `batch-get`, `duplicates`,
  `shows-by-artist-ids`, `songs-by-artist-ids`, `list-learning`,
  and the four `*-detail` ops) stays documented with the same
  command string, the same flags, and the same paragraph position
  in the Checklist (R3.14).
- The existing "Pattern: when the user gives a name, not an ID"
  section keeps its single mention of `search-songs` — the new
  examples section complements it rather than replacing it. The
  `search-songs` pointer in the Pattern section MAY be pruned to a
  single sentence that points at the new section, but it MUST NOT
  disappear (R3.15).
- The existing Checklist bullet for `search-songs` (which enumerates
  the flags and the envelope shape) stays as the authoritative flag
  reference (R3.14); the new section is pattern-teaching, not
  reference.
- No new commands are introduced. Every invocation shown in the new
  section is already `scripts/query.py search-songs` with some
  subset of the three existing flags.
- No other `SKILL.md` is touched. Bug 4 is scoped to one file.

### Hypothesized Root Cause

`skills/searching-library/SKILL.md` was written at a time when the
Checklist was treated as the primary reference for every op.
`search-songs` was added later and got the same one-bullet treatment
every other op has. The Pattern section above the Checklist got one
follow-on paragraph mentioning `search-songs` for combined-intent
questions — enough to establish that the op exists, not enough to
teach the translation from user intent to CLI invocation. As the
library grew and combined-intent questions became the common case,
the skill never got a worked-examples pass. An agent who hasn't
used the op before has no pattern to match on and falls back to the
single-kind `search` op they already understand.

### Fix Implementation

#### Decision 7 — Where the combined-search examples land

**Decision:** A new H2 section (suggested heading:
`## Combined searches: song + show + artist`) inserted into
`skills/searching-library/SKILL.md` immediately after the existing
`## Pattern: when the user gives a name, not an ID` section and
before `## Checklist: available ops`.

**Rationale:** R2.19 pins the placement constraint to "near the top
of the file, so an agent reading the file top-to-bottom sees the
combined-search guidance before the general per-op Checklist". The
existing Pattern section is the natural neighbor — it already
introduces the "search first, then detail" workflow, and a dedicated
follow-on section is the least disruptive way to layer combined-
intent teaching on top of it without reorganising the Checklist.
Placing it above the Checklist (rather than folded into the
Checklist's `search-songs` bullet) matches the "pattern-teaching,
not reference" intent — the Checklist bullet stays compact and
reference-shaped, the new section stays example-shaped.

**Content outline** (concrete prose comes in the tasks phase; this
section pins the shape):

- 1–2 sentences stating when to reach for `search-songs` vs. chaining
  single-kind `search` calls. Specifically: if the user's question
  names two or more of {song, show, artist}, `search-songs` is the
  first-line tool.
- One table or compact list mapping each of the four flag combinations
  to a user-intent framing plus the exact CLI invocation. For
  example:
  - **song + show** ("the Clannad OP by some unknown artist"):
    `scripts/query.py search-songs --song-term "<song>" --show-term "<show>"`
  - **song + artist** ("the Lia song in that one show"):
    `scripts/query.py search-songs --song-term "<song>" --artist-term "<artist>"`
  - **artist + show** ("which songs by Yui are in FMA?"):
    `scripts/query.py search-songs --artist-term "<artist>" --show-term "<show>"`
  - **all three** ("the Clannad OP by Lia called Megumeru"):
    `scripts/query.py search-songs --song-term "<song>" --show-term "<show>" --artist-term "<artist>"`
- One explicit "anti-pattern" callout naming the chained-search
  fallback (three `search` calls + manual id intersection) and why
  it's worse: three DB roundtrips, no artist/show/`media_urls`
  attachment, no byte-stable ordering.
- A one-line pointer back at the Checklist's `search-songs` bullet
  for the full flag list and envelope shape: "See the Checklist
  entry below for the exact flag syntax and the `{filters, count,
  results}` envelope shape."

Length budget: ≤ 25 lines of Markdown, comparable to the existing
"Pattern" section's length. The goal is a pattern-teaching section
an agent reads once, not a new reference.

#### Decision 8 — Relationship to Decision 4 (Bug 3)

**Decision:** The Bug 3 preference statement in `skills/README.md`
and the Bug 4 combined-search examples in
`skills/searching-library/SKILL.md` are two complementary touches on
the same failure mode (agent picks the wrong command). They remain
separate deliverables because they target different files and
different kinds of evidence:

- Bug 3 adds a globally-reachable preference paragraph that names
  the raw-CRUD-vs-dedicated contrast in the abstract, with the
  graduate invariant as its worked counter-example.
- Bug 4 adds a skill-local, example-driven section that shows the
  agent, on the most natural skill for it, how to map combined-
  intent user questions onto `search-songs` flags and why the
  chained-search fallback is worse.

Neither section references the other in prose. An agent reading
`skills/README.md` gets the general ranking; an agent already
inside `skills/searching-library/SKILL.md` gets the combined-search
examples. Both land the same message ("reach for the dedicated op")
from different entry points.

---

## Correctness Properties

This section is the single source of truth for the correctness
properties validated by the tests below. Each property is cited by
number from the PBT files.

Property 1: Bug Condition — Importer accepts the three new inputs
equivalently to legacy flat

_For any_ `CLIInvocation` whose `inputChannel` is one of the three
new flags (`--input-jsonpath`, `--input-jsonstr`, `--input-array`)
and whose payload is either the raw AMQ export shape or the flat
five-field shape, the fixed `import_plan.py` SHALL produce the same
plan (`resolved` / `auto_completable` / `ambiguous`) as the legacy
`--input` surface invoked on the equivalent already-flat payload,
**except** when `inputChannel = --input-array` AND the payload is
raw AMQ — in that case the fixed CLI SHALL exit `1` with
`INVALID_INPUT` rather than falling through to preprocessing.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9**

Property 2: Preservation — Importer legacy surface unchanged

_For any_ `CLIInvocation` against the legacy `--input` / positional
path surface — whether the payload is valid flat, malformed JSON, a
missing file, or any non-array JSON — the fixed `import_plan.py`
SHALL produce the same exit code, stdout envelope, and stderr
envelope as the original.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

Property 3: Bug Condition — Graduate pins level to MAX_LEVEL

_For any_ learning row `L` where `L.graduated = 0` and
`L.level < MAX_LEVEL`, after `learning.py graduate --ids [L.id]` the
fixed code SHALL produce a row with `graduated = 1` AND
`level = MAX_LEVEL` AND unchanged `id` / `song_id` / `created_at` /
`level_up_path` / `last_level_up_at`, AND the response payload for
that id SHALL report `level = MAX_LEVEL` and
`display_level = MAX_LEVEL + 1`.

**Validates: Requirements 2.10, 2.11**

Property 4: Preservation — Graduate on non-bug inputs unchanged

_For any_ learning row `L` where `NOT isBugConditionGraduate(L)` —
i.e. `L.graduated = 1` (no-op path) or
`L.graduated = 0 AND L.level = MAX_LEVEL` — the fixed `graduate`
SHALL produce the same row state and the same response payload as
the original.

**Validates: Requirements 3.6, 3.7, 3.8, 3.9**

Property 5: Bug Condition — Skills docs carry the preference
guidance

_For any_ version of the skills doc tree `D'` after the fix, a
case-insensitive search for "dedicated command" (or an equivalent
author-chosen synonym) SHALL find a match in a globally-reachable
location (`skills/README.md`), AND that location SHALL contain at
least one named worked counter-example naming the
`graduated ↔ level = MAX_LEVEL` invariant that the raw-CRUD path
does not preserve.

**Validates: Requirements 2.12, 2.13, 2.14, 2.15**

Property 6: Preservation — Skills docs retain every pre-fix command
listing

_For any_ `(skillFile, commandString, subcommand)` triple documented
in the skill set at spec start, the fixed skill set SHALL still
document that triple in the same file with the same string and
subcommand. `data.py` SHALL remain documented with `create`,
`update`, `delete`, and `bulk-reassign`.

**Validates: Requirements 3.10, 3.11, 3.12, 3.13**

Property 7: Bug Condition — `searching-library` SKILL.md contains
combined-search examples

_For any_ version of the skills doc tree `D'` after the fix,
`skills/searching-library/SKILL.md` SHALL contain at least one
worked `scripts/query.py search-songs` invocation for each of the
four flag combinations
`{song+show, song+artist, artist+show, song+show+artist}`, AND each
SHALL be paired with a natural-language user-intent framing in the
same markdown section.

**Validates: Requirements 2.16, 2.17, 2.18, 2.19**

Property 8: Preservation — `searching-library` SKILL.md retains
every pre-fix command reference

_For any_ `(script, subcommand, flag)` triple documented in
`skills/searching-library/SKILL.md` at spec start, the fixed file
SHALL still document that triple. The eight ops present today
(`search`, `get`, `batch-get`, `duplicates`, `shows-by-artist-ids`,
`songs-by-artist-ids`, `list-learning`, and the four `*-detail`
ops — counted together as they share the Checklist bullet style)
all stay present.

**Validates: Requirements 3.14, 3.15**

---

## Testing Strategy

The testing strategy has two phases per bug: first, an exploratory
counterexample test that fails on the unfixed code to confirm the
root cause, then fix-checking + preservation assertions that pass
only on fixed code.

### Validation Approach

- **Unfixed-code exploration.** For Bugs 1 and 2 we will run one
  targeted test (or small PBT) against `mainline` before any code
  change and confirm it fails exactly how the bug description
  predicts. For Bugs 3 and 4 the "unfixed code" is the relevant
  SKILL.md as it exists today; the exploration is a simple `grep` on
  the file. For Bug 4 specifically,
  `grep -c 'search-songs' skills/searching-library/SKILL.md` returns
  `1` on unfixed code (just the Checklist bullet mention) and ≥ `4`
  on fixed code (one per combined-intent example, plus the
  preserved Checklist bullet).
- **Fix-checking tests** pass on fixed code and validate Properties
  1, 3, 5, 7 respectively.
- **Preservation tests** reuse the existing integration tests
  verbatim wherever possible (`tests/integration/test_import_plan.py`,
  `tests/integration/test_error_codes.py::test_song_invariant_violation`,
  `tests/integration/test_learning.py` graduate section) and extend
  them only where the pre-fix behavior they encode was itself buggy
  (see the note in the Bug 2 subsection below). Bug 4's preservation
  assertions are folded into the same `tests/integration/test_skills_docs.py`
  file introduced for Bug 3.

### Exploratory Bug Condition Checking

**Bug 1 — Exploratory test plan:** Write an integration test that
feeds `import_plan.py` a tiny raw AMQ JSON file via a new flag. On
unfixed code, argparse rejects the flag with exit 2; on unfixed code
`--input` applied to the same raw-AMQ file produces exit 1 with
`INVALID_INPUT`. Either counterexample demonstrates the bug. On
fixed code, the invocation exits 0 and its plan matches the plan
produced by the equivalent flat-array `--input` call.

**Test cases:**

1. Raw AMQ one-song file via `--input-jsonpath`: exits 0 and the
   plan has exactly one entry in one bucket. Will fail on unfixed
   code (argparse rejects `--input-jsonpath`).
2. Inline JSON via `--input-jsonstr '{"songs":[...]}'`: same
   assertion. Will fail on unfixed code.
3. Inline flat JSON via `--input-array '[{...}]'`: same assertion.
   Will fail on unfixed code.
4. Inline raw AMQ via `--input-array '{"songs":[...]}'`: exits 1
   with `INVALID_INPUT` and the error message mentions "flat-only".
   Will fail on unfixed code (argparse rejects the flag).
5. No input channel at all: exits 1 with `INVALID_INPUT` and the
   message names the available flags. Will pass on unfixed code
   *accidentally* because `--input` and positional are both missing;
   the new test tightens the assertion by requiring the error
   message to mention all four channels.

**Bug 2 — Exploratory test plan:** Write an integration test that
seeds a learning row at `level = 3, graduated = 0`, runs
`learning.py graduate --ids <id>`, and asserts `row["level"] == 19`
afterwards. On unfixed code the row ends at `level = 3, graduated = 1`
and the test fails on the level assertion. On fixed code both
assertions pass.

**Test cases:**

1. Seed at `level = 3, graduated = 0`, graduate, assert
   `level == 19, graduated == 1`. Fails on unfixed code.
2. Seed at `level = 0, graduated = 0`, graduate, assert
   `level == 19, graduated == 1`. Fails on unfixed code.
3. Seed at `level = 19, graduated = 0`, graduate, assert
   `level == 19, graduated == 1`. Passes on both (preservation
   corner).
4. Seed at `level = 5, graduated = 1`, graduate, assert
   `level == 5, graduated == 1, updated_at unchanged`. Passes on
   both (no-op preservation).

**Bug 3 — Exploratory test plan:** A textual test against
`skills/README.md`. On unfixed code the file does not contain the
phrase "dedicated command" (or any equivalent ranked preference);
on fixed code it does and the match is in a section that also names
the graduate counter-example.

**Bug 4 — Exploratory test plan:** A textual test against
`skills/searching-library/SKILL.md`. On unfixed code,
`grep -c 'search-songs' skills/searching-library/SKILL.md` returns
`1` (just the Checklist bullet mention); on fixed code the count is
`≥ 4` (one per worked example for the four flag combinations, plus
the preserved Checklist bullet and the preserved Pattern-section
pointer). Additionally, on fixed code each of the four flag
combinations `{--song-term + --show-term, --song-term +
--artist-term, --show-term + --artist-term, all three}` appears on
a `scripts/query.py search-songs …` line inside the new combined-
searches section.

### Fix Checking

**Goal:** For every input where the bug condition holds, the fixed
code produces the expected behavior. Pseudocode per bug below mirrors
the properties above.

**Bug 1:**

```
FOR ALL invocation WHERE isBugConditionImporter(invocation) DO
  result   ← importPlan'(invocation)
  flat     ← toFlatFiveField(invocation.payload)
  IF invocation.inputChannel = "flat-only"
     AND isRawAmqShape(invocation.payload) THEN
    ASSERT result.exitCode = 1
    ASSERT result.error.code = "INVALID_INPUT"
  ELSE
    expected ← importPlan'(legacy(flat))
    ASSERT result.exitCode = 0
    ASSERT result.plan     = expected.plan
  END IF
END FOR
```

**Bug 2:**

```
FOR ALL L WHERE isBugConditionGraduate(L) DO
  after ← graduate'(L)
  ASSERT after.graduated = 1
  ASSERT after.level     = MAX_LEVEL
  ASSERT after.id          = L.id
  ASSERT after.song_id     = L.song_id
  ASSERT after.created_at  = L.created_at
END FOR
```

**Bug 3:** Single textual property; no `FOR ALL` loop.

**Bug 4:** Four textual sub-properties (one per flag combination),
each asserting that
`skills/searching-library/SKILL.md` contains a
`scripts/query.py search-songs …` line with exactly the expected
flag set inside a markdown section that also carries a natural-
language user-intent phrase. No runtime `FOR ALL` loop — the
assertions iterate the four flag combinations in the test body.

### Preservation Checking

**Goal:** For every input where the bug condition does NOT hold, the
fixed code behaves identically to the original.

**Bug 1 preservation test plan:**

- Every existing test in `tests/integration/test_import_plan.py`
  (legacy `--input`, positional path, `--output`, missing file,
  non-JSON, non-array JSON) keeps passing byte-identical. These are
  the strongest single preservation signal.
- `tests/integration/test_error_codes.py::test_song_invariant_violation`
  keeps passing without modification.
- A new PBT `tests/integration/property/test_importer_input_channels_property.py`
  generates random flat-array payloads, drives them through all
  accepted channels (legacy `--input`, `--input-jsonpath`,
  `--input-jsonstr`, `--input-array`), and asserts the four plans
  are byte-equal. Seeded with a fixed `random.Random`, ~30
  iterations, matching the pattern in
  `tests/integration/property/test_import_property.py`.
- Same PBT generates raw AMQ payloads derived from its flat payloads
  (by wrapping them in `{"songs": [...]}` and renaming a few keys
  per the field mapping table) and asserts `--input-jsonpath` /
  `--input-jsonstr` produce the same plan as the flat legacy call
  on the original flat payload.

**Bug 2 preservation test plan:**

- `tests/integration/test_learning.py::test_graduate_flips_graduated_flag`
  currently asserts `payload["display_level"] == 6` (i.e.
  `level == 5`) after graduating a row at `level = 5`. This assertion
  **encodes the bug** — `bugfix.md` explicitly notes existing tests
  encode the buggy behavior. Update the test to assert
  `level == MAX_LEVEL` and `display_level == MAX_LEVEL + 1`. Every
  other assertion in the test is preserved.
- `tests/integration/test_learning.py::test_graduate_second_call_is_noop`
  — already correct, no change needed.
- `tests/integration/test_learning.py::test_graduate_missing_id_is_not_found`
  — already correct, no change needed.
- `tests/integration/property/test_graduate_property.py` currently
  asserts `mid["level"] == before["level"]` after the first graduate
  call. This **encodes the bug** for the case
  `before["graduated"] == 0 AND before["level"] < MAX_LEVEL`. Update
  the test to assert:
  - If `before["graduated"] == 1`: `after["level"] == before["level"]`
    (no-op preservation).
  - If `before["graduated"] == 0`: `after["level"] == MAX_LEVEL`.
  The second-call idempotency assertion stays intact for both
  branches.
- `tests/integration/test_error_codes.py::test_already_graduated`
  and every other learning-facing error-code test — no change,
  preservation is free.

**Bug 3 preservation test plan:**

- A new `tests/unit/test_skills_docs.py` or
  `tests/integration/test_skills_docs.py` (whichever slot matches
  existing conventions — `tests/integration/property/test_skill_prefix_property.py`
  lives in the integration tree, so the new file goes there too).
  For every file in `skills/**/SKILL.md` it walks the file's
  code-fence contents and collects `(script, subcommand)` pairs.
  Asserts that every pair present at spec start is still present in
  the fixed tree. Asserts `data.py` has its four subcommands listed
  somewhere in the skill set.
- Asserts `skills/README.md` contains the phrase "dedicated command"
  (case-insensitive) and that the surrounding context also mentions
  both `graduate` and `data.py`, validating the named counter-example.

**Bug 4 preservation test plan:**

- Extend the same `tests/integration/test_skills_docs.py` file
  introduced for Bug 3 — no new test file.
- Fix-checking assertions: for each of the four flag combinations
  `{--song-term + --show-term, --song-term + --artist-term,
  --show-term + --artist-term, all three}`, assert that
  `skills/searching-library/SKILL.md` contains a
  `scripts/query.py search-songs` invocation line using exactly
  that flag set, and that the enclosing markdown section (bounded
  by the nearest H2/H3 headings) also carries a natural-language
  intent phrase. "Natural-language intent phrase" is implemented as
  a presence check for at least one of a small seed list of
  anchors (the test spec pins the list in the test-file docstring;
  candidates include "opening", "songs from", "by", "which shows",
  with case-insensitive matching).
- Preservation assertions: for every
  `scripts/query.py <subcommand>` reference present in
  `skills/searching-library/SKILL.md` at spec start, the fixed file
  still contains that reference. The pre-fix reference set is
  captured by reading the file at spec-start HEAD in the test
  fixture; it covers `search`, `get`, `batch-get`, `duplicates`,
  `shows-by-artist-ids`, `songs-by-artist-ids`, `list-learning`,
  `song-detail`, `artist-detail`, `show-detail`, `learning-detail`,
  and the existing `search-songs` Checklist bullet.
- Exploratory counter-example: before the fix,
  `grep -c 'search-songs' skills/searching-library/SKILL.md` returns
  `1`; after the fix it returns `≥ 4`. This assertion is included
  in the fix-checking portion of the file so a regression that
  silently strips the examples would fail here.

### Unit Tests

New unit test file: `tests/unit/test_importer_preprocessing.py`.

Covers the three new pure helpers in `scripts/import_plan.py`:

- `_discriminate(parsed)` — returns `"flat"` for lists, `"raw_amq"`
  for dicts with a `songs` array, raises `INVALID_INPUT` otherwise.
  Parametrised over shape variants (list, dict-with-songs,
  dict-without-songs, scalar, dict-with-non-array-songs).
- `_amq_entry_to_flat(entry, i)` — the field mapping table.
  Parametrised over: all five target fields present under their AMQ
  name; all five present under their flat name; `animeEnglishName`
  beating `animeRomajiName`; missing `media_url` defaulting to `""`;
  missing required field raising `INVALID_INPUT` with the field
  name in details; extra AMQ-native fields silently dropped.
- `_flatten_amq(payload)` — happy path on a three-song AMQ payload;
  non-dict entry at index 1 raising `INVALID_INPUT` citing the
  index.

These are pure-function tests. No DB setup, no subprocess, just
direct imports from `scripts.import_plan`. They run in the same
harness as `tests/unit/test_common.py`.

### Property-Based Tests

New PBT files:

- `tests/integration/property/test_importer_input_channels_property.py`
  — validates Properties 1 and 2 for Bug 1. Uses seeded
  `random.Random` to build flat payloads with a mix of
  resolved / auto_completable / ambiguous entries, then routes each
  through every accepted channel and compares plans.
- `tests/integration/property/test_graduate_level_max_property.py`
  — validates Properties 3 and 4 for Bug 2. Uses seeded
  `random.Random` (extending the existing pattern from
  `test_graduate_property.py`) to build random learning rows and
  assert the post-graduate `level == MAX_LEVEL` invariant for rows
  that met the bug condition, plus behavior-equal assertions for
  rows that did not.

Both files follow `tests/integration/property/_helpers.py`
conventions: `BASE_SEED + N`, `ITERATIONS` constant, per-file
docstring naming the property from this document.

### Integration Tests

Extensions to existing integration files:

- `tests/integration/test_import_plan.py` gains three small test
  functions covering the three new flags end-to-end on seeded DBs,
  mirroring the existing `test_resolved_exact_match_with_existing_show`
  style.
- `tests/integration/test_learning.py` gets its existing
  `test_graduate_flips_graduated_flag` updated (see preservation
  notes above) and gains one new test
  `test_graduate_pins_level_to_max_for_all_below_max_starts` that
  parametrises across `level ∈ {0, 3, 10, 18}` and asserts each
  ends at `level = 19` post-graduate.
- No new integration file is created for Bug 3; the doc-tree test
  goes under `tests/integration/test_skills_docs.py` per the
  preservation plan above. Bug 4 extends that same file rather than
  introducing a separate one — both bugs are doc-tree assertions,
  and folding them into one file keeps the spec-start-vs-fixed
  fixture setup in one place.

### Test infrastructure notes

- All new tests follow the 90% line-coverage floor enforced by
  `tests/coverage_runner.py` + `tests/run.sh`. The new preprocessing
  helpers are all exercised by the unit test file above, so
  line-coverage on them is at 100% by construction.
- Python 3.12 remains the pinned dev interpreter per
  `dev-docs/python-version.md`. No new dependency on any newer
  feature.
- The session-scoped DB guard in `tests/conftest.py` continues to
  protect `db/datasource.db` — every new test uses `tmp_app_root`.

---

## Rollout / compatibility

- **No schema change.** `tests/fixtures/schema.sql` is unchanged. No
  `schema-sync` / `schema-regen` pass is required for this spec.
- **Packaging unchanged.** `package.py` and `make package` still
  build the same `scripts/` + `skills/` tree; only the file contents
  inside change.
- **Runtime constraints preserved.** Every change lives in Python
  stdlib. No new imports outside `argparse`, `json`, `pathlib`,
  `sqlite3`, `sys` — all already used by the files being edited.
- **Legacy CLI callers preserved.** Any existing script that invokes
  `python scripts/import_plan.py --input amq.json --output plan.json`
  against a flat array keeps working with the same exit code, stdout
  envelope, and plan contents.
- **Documentation update pinned.**
  `skills/importing-amq-songs/SKILL.md` and
  `skills/importing-amq-songs/references/plan-shape.md` are updated
  in this spec (Decision 6) so the skill body stays in sync with
  the new flags. `skills/README.md` gains the preference section
  (Decision 4). `skills/searching-library/SKILL.md` gains the
  combined-search examples section (Decision 7) — a skill-body
  documentation update with no runtime, packaging, or test-harness
  changes beyond the doc-tree test file introduced for Bug 3.
- **Tests that encode the buggy behavior will be updated** in the
  same spec, as explicitly noted in the Bug 2 preservation plan.
  This is distinct from test files that merely cover unchanged
  surface area, which stay byte-identical.
