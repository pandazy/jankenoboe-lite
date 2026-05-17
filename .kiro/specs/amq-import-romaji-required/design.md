# AMQ Import — Romaji Required — Bugfix Design

## Overview

The AMQ importer treats the show's romaji name as best-effort. The
preprocessor in `scripts/import_plan.py` reads
`songs[i].songInfo.animeNames.romaji` only as a last-resort fallback
under the `show_name` flat key (the v0.1.2 mapping table from
`amq-real-export-shape-fix`), and `_resolve_show` hard-codes
`name_romaji: None` on every `show_to_create` block. The visible
symptom: every show row created through the importer ends with
`name_romaji = NULL`, regardless of whether the source AMQ file
carried a romaji on the song. The deeper symptom is that the
importer is silent when the romaji is not at the canonical path —
exactly the same drift mode that already triggered the v0.1.1 →
v0.1.2 mapping correction, still latent for romaji.

This fix promotes romaji to a first-class required input. The
mapping table grows a new flat key, `show_name_romaji`, with one
candidate path (`songInfo.animeNames.romaji`); the romaji
fallback is removed from the `show_name` flat key (English-only);
`_resolve_show` carries the romaji onto every `show_to_create`
block; `import_resolve.py` already consumes
`block.get("name_romaji")` and writes it into `show.name_romaji` —
that line stops being a NULL-feeder once the upstream block carries
the value. The agent skill (`skills/importing-amq-songs/SKILL.md`)
gains a Step 0 shape sniff that runs **before** `import_plan.py`
and, on miss, walks a small named hypothesis list and proposes a
recovery via the existing `scripts/data.py create --kind show`
escape hatch.

The error code on the API surface is the existing `INVALID_INPUT`
with `details.kind = "missing_romaji"` — no new entry in
`_common.VALID_ERROR_CODES`. The flat key on the preprocessor
output and on `show_to_create` is `show_name_romaji` (mirroring
`show_name`); `_resolve_show` translates it to the DB column name
`name_romaji` exactly as it does today for the other show fields.
No new script, no new CLI flags on `import_plan.py`, no schema
migration — `show.name_romaji` already exists in `scripts/schema.sql`
and `_common.EXPECTED_SCHEMA["show"]`. v0.1.6 is already tagged;
this ships as v0.1.7 through the existing release pipeline.

## Glossary

- **Bug_Condition (C)**: an AMQ import invocation whose payload
  does not carry a non-empty romaji on at least one entry the
  classifier would otherwise process — either a real AMQ entry
  with empty/missing `songInfo.animeNames.romaji`, or a flat
  legacy entry with empty/missing `show_name_romaji`. See
  bugfix.md "Bug Condition".
- **Property (P)**: when C holds, the fixed code SHALL reject at
  the API surface with `INVALID_INPUT details.kind =
  "missing_romaji"` and SHALL classify the same offending entries
  at the agent surface (Step 0 sniff). When C does not hold, the
  fixed code SHALL produce a plan whose every show-creation block
  carries a non-null `name_romaji`, and SHALL drive that plan to a
  DB state where every newly-created show row's `name_romaji`
  matches the input AMQ song's romaji.
- **Preservation**: every other invocation behaves byte-identically
  to v0.1.6 — same buckets, same plan modulo the `name_romaji`
  column on `show_to_create` blocks, same exit code, same envelope
  shape, same DB writes. Every script other than
  `import_plan.py` and `import_resolve.py`'s show-creation branch
  is unchanged.
- **`_AMQ_FIELD_MAP`**: the path-tuple mapping table in
  `scripts/import_plan.py` that lists, per flat key, the candidate
  paths to walk on a raw AMQ song. After this fix it gains one row
  for `show_name_romaji` and loses the romaji fallback under
  `show_name`.
- **`show_name_romaji`**: the new flat key. Lives on every
  preprocessor output entry, on every `show_to_create` block, and
  on every flat legacy entry. Translates to the DB column
  `show.name_romaji` in `_resolve_show` and `_ensure_show`. Always
  a non-empty string when present (empty strings are rejected
  upstream).
- **`MISSING_ROMAJI` failure**: shorthand for the typed rejection
  the API surface returns when C holds. The wire shape is
  `code = "INVALID_INPUT"`, `details = {"index": <int>,
  "missing_field": "show_name_romaji", "kind": "missing_romaji",
  "available_keys": [...]}`. Agents discriminate on `details.kind`.
- **Step 0 sniff**: the new pre-flight section in
  `skills/importing-amq-songs/SKILL.md`. Read-only, performed by
  the agent (no new script). Walks each `songs[i]` looking for
  romaji at the canonical path; on miss, classifies the failure
  mode, surfaces a candidate recovery path, and asks the user.
- **Manual-recovery branch**: the agent, after user confirmation
  on a Step 0 miss, extracts the romaji from the candidate path
  and inserts the show via
  `scripts/data.py create --kind show '{"name": ..., "name_romaji":
  ..., "vintage": ..., "s_type": ...}'`, then re-runs the three-step
  pipeline so `import_plan.py`'s existence check picks the new
  show up.
- **F (`importPlan` / `ensureShow`)**: `scripts/import_plan.py`
  and `scripts/import_resolve.py` as they exist on `mainline`
  after v0.1.6 — preprocessor reads romaji only as a `show_name`
  fallback; `_resolve_show` always emits `name_romaji: None`.
- **F' (`importPlan'` / `ensureShow'`)**: the same scripts after
  this fix — `show_name_romaji` is its own required flat key;
  `show_name` is English-only; `_resolve_show` carries the romaji
  onto the `show_to_create` block; `_ensure_show` writes it
  through (line already exists, currently fed by `None`).

## Bug Details

### Bug Condition

The bug manifests on two surfaces driven by a single API gap:

1. **Storage gap.** Even when a real AMQ entry carries a non-empty
   `songInfo.animeNames.romaji`, today's preprocessor never plumbs
   that value into the show creation. `_resolve_show` constructs
   `show_to_create` with a literal `"name_romaji": None`. Every
   newly-created show ends with `name_romaji = NULL`.

2. **Validation gap.** Today's mapping table lists romaji only as
   a fallback under `show_name`. An entry with no English title and
   no romaji raises `INVALID_INPUT missing_field=show_name`; an
   entry with English present and romaji absent passes silently.
   There is no rejection that names romaji as the missing field,
   and the romaji-as-`show_name`-fallback path further conflates
   English and romaji on `show.name`.

The shape-drift sub-case from bugfix.md 1.5 — AMQ moves romaji to
a different path — is a specialisation of the validation gap: the
canonical path returns no non-empty string, but the romaji exists
elsewhere in the entry. The same fix that lands romaji as a
required flat key catches this drift mode.

**Formal Specification:**

```
FUNCTION isBugCondition(input)
  INPUT: input of type AmqImportInvocation
          (channel ∈ {--input, positional, --input-jsonpath,
                      --input-jsonstr, --input-array} +
           parsed payload + per-entry resolved romaji status)
  OUTPUT: boolean

  // True iff the parsed payload reaches the classifier with at
  // least one entry whose canonical romaji slot is empty or
  // missing. Two channels:
  //   - real AMQ shape via --input-jsonpath / --input-jsonstr:
  //     _get_nested(songs[i], ("songInfo","animeNames","romaji"))
  //     is None or "".
  //   - flat array via --input / positional / --input-array
  //     / --input-jsonpath / --input-jsonstr on a flat payload:
  //     entry["show_name_romaji"] is None, missing, or "".
  IF NOT isParseableAmqOrFlat(input.payload) THEN RETURN False
  IF requiredFieldsExceptRomajiAreAllPresent(input.payload) AND
     someEntryHasNoNonEmptyRomajiAtCanonicalPath(input.payload) THEN
    RETURN True
  END IF
  RETURN False
END FUNCTION
```

The "required fields except romaji" precondition matters: a payload
that is *also* missing English titles or vintage on some entry
already gets rejected today (with `missing_field` naming the older
field). The romaji rejection layers on top — it fires only after
the existing required-field gates have passed.

### Examples

- **Real AMQ song, romaji present**:
  `{"songInfo": {"artist": "Tia", "songName": "Chotto Dekakete
  Kimasu", "animeNames": {"english": "Wooser's Hand-to-Mouth
  Life: Awakening Arc", "romaji": "Wooser no Sono Higurashi:
  Kakusei Hen"}, "vintage": "Winter 2014"}, "videoUrl":
  "https://..."}`. Today's preprocessor: emits a flat entry
  without `show_name_romaji`; `_resolve_show` writes
  `name_romaji: None`; the resulting `show.name_romaji` is `NULL`.
  Expected: preprocessor emits
  `show_name_romaji = "Wooser no Sono Higurashi: Kakusei Hen"`;
  `_resolve_show` puts it on the `show_to_create` block;
  `_ensure_show` writes it into `show.name_romaji`.
- **Real AMQ song, English present, romaji empty**: same as above
  with `animeNames.romaji = ""`. Today: passes silently, show
  created with `name_romaji = NULL`. Expected: rejected with
  `INVALID_INPUT details = {index: i, missing_field:
  "show_name_romaji", kind: "missing_romaji",
  available_keys: ["songInfo", "videoUrl", ...]}`.
- **Real AMQ song, English missing, romaji present**:
  `{"songInfo": {"animeNames": {"romaji": "Foo"}, ...}, ...}`.
  Today: silent re-use — preprocessor emits `show_name = "Foo"`
  (the English-falls-back-to-romaji precedence) and creates a show
  whose `name` is the romaji string. Expected: rejected with
  `INVALID_INPUT details = {index: i, missing_field: "show_name",
  ...}` — the English fallback to romaji is removed; missing
  English is a hard rejection.
- **Real AMQ song, English missing AND romaji missing**: today
  rejects on `show_name`. Expected: same — the existing English
  rejection still fires first; the new romaji rejection only
  fires when English is present and romaji is missing.
- **Flat legacy entry**: `{"artist_name": ..., "song_name": ...,
  "show_name": "Wooser's Hand-to-Mouth Life: Awakening Arc",
  "show_name_romaji": "Wooser no Sono Higurashi: Kakusei Hen",
  "vintage": "Winter 2014", "media_url": "..."}`. Same contract
  as the real AMQ entry. A flat entry without
  `show_name_romaji` is rejected with the same `MISSING_ROMAJI`
  envelope.
- **Shape drift (hypothetical AMQ rename)**: AMQ moves romaji to
  `songInfo.animeNames.romajiTitle` instead of `.romaji`. Today:
  passes silently, every show gets `name_romaji = NULL`.
  Expected: every entry gets rejected with
  `MISSING_ROMAJI`; the agent's Step 0 sniff diagnoses the rename
  by reporting that `animeNames` has no `romaji` key but does
  have a `romajiTitle` key, and proposes recovery via
  `scripts/data.py create --kind show` with the romaji extracted
  from `romajiTitle`.
- **Re-import idempotency**: a payload whose entries point at
  shows that already exist in the DB. The classifier still
  matches on `(name, vintage, status = 0)` only — no romaji
  match is required for an existing-show hit (see
  `_classify`'s show-resolution branch). Re-running the import is
  still a no-op.
- **Counterexample that pins the bug**: the committed real AMQ
  fixture at `tests/fixtures/amq_song_export-small.json` (9
  songs, every entry with a non-empty romaji). On v0.1.6 code:
  exit 0, plan with 9 `auto_completable` entries on a fresh DB,
  every `show_to_create.name_romaji` is `None`. On fixed code:
  exit 0, same buckets, every `show_to_create.name_romaji` is
  the romaji string from the fixture; running through to step 2
  produces 9 show rows with non-null `name_romaji`.

## Expected Behavior

### Functional Requirements

After the fix lands:

1. **API surface — preprocessor**:
   `_AMQ_FIELD_MAP` carries a new row for `show_name_romaji` with
   one candidate path, `("songInfo", "animeNames", "romaji")`,
   marked required. The `show_name` row drops its romaji fallback;
   the candidate paths become
   `(("songInfo", "animeNames", "english"), ("show_name",))`
   only. Both rows are required (`required = True`); a missing
   value at every candidate aborts the file with `INVALID_INPUT`
   naming the missing flat key (R2.1, R2.3 of bugfix.md).

2. **API surface — show resolution**: `_resolve_show` reads
   `entry["show_name_romaji"]` (now a non-empty string by
   contract) and threads it onto the `show_to_create` block as
   `name_romaji`. The existing branch that returns
   `{"show_id": ..., "media_url": ...}` for an existing-show hit
   is unchanged — re-import idempotency is preserved (R2.7).

3. **API surface — flat legacy loader**: `_load_entries`
   normalises a sixth flat key, `show_name_romaji`, alongside the
   existing five. Missing or empty raises the same
   `INVALID_INPUT details.kind = "missing_romaji"` envelope the
   AMQ preprocessor raises (R2.4). The legacy `--input` /
   positional surface and the `--input-array` channel both pick
   this up automatically because both route through
   `_load_entries` / `_entries_from_parsed`'s flat path.

4. **Resolve step**: `_ensure_show` already writes
   `name_romaji = block.get("name_romaji")` on a fresh insert.
   Today that line always feeds `None`; after the fix it feeds the
   non-empty string carried by `_resolve_show`. The resolve step
   itself does not change (R2.6).

5. **Agent surface — Step 0 sniff**:
   `skills/importing-amq-songs/SKILL.md` gains a new Checklist
   step before "Step 1 — plan". The agent reads the user's AMQ
   JSON directly (no new script), walks each `songs[i]` looking
   for a non-empty string at `songInfo.animeNames.romaji`, and on
   miss classifies the failure mode against three named
   hypotheses (Decision 5 below) before proceeding. The sniff is
   silent on the success path (R2.12).

6. **Agent surface — manual recovery**: when the user confirms a
   Step 0 diagnosis, the agent extracts the romaji from the
   candidate path the sniff identified, inserts the show via
   `scripts/data.py create --kind show '{"name": ...,
   "name_romaji": ..., "vintage": ..., "s_type": ...}'`, and
   re-runs the three-step pipeline. Step 1's existence check
   picks up the freshly-created show (R2.11). No new script, no
   new flag — purely a documented procedure in the SKILL.md.

7. **Documentation lockstep**:
   `skills/importing-amq-songs/references/plan-shape.md` is
   updated to (a) document `show_name_romaji` as a required field
   on the flat shape, (b) add the row in the AMQ → flat field
   mapping table, (c) drop the `animeNames.romaji` fallback from
   the `show_name` row, (d) document `name_romaji` as a non-null
   string on the `show_to_create` block (R3.12 of bugfix.md).

### Preservation Requirements

**Unchanged Behaviors:**

- Every script other than `scripts/import_plan.py` and
  `scripts/import_resolve.py`'s show-creation branch
  (`add_play_history.py`, `learning.py`, `query.py`,
  `merge_artists.py`, `cleanup.py`, `init_db.py`, `data.py`,
  `review.py`) is byte-identical to v0.1.6 (R3.7, R3.8 of
  bugfix.md).
- `scripts/_common.py` is unchanged. `VALID_ERROR_CODES` does not
  grow a new entry (Decision 1 below); `EXPECTED_SCHEMA["show"]`
  already includes `name_romaji`; `SPECS["show"].columns` already
  includes `name_romaji`.
- `scripts/schema.sql` is byte-identical. `tests/fixtures/schema.sql`
  is byte-identical. No `make schema-sync` needed.
- The four input channels' mutually-exclusive contract is
  unchanged. `--input-array` still rejects nested AMQ shapes
  with `INVALID_INPUT` regardless of romaji presence.
- The classifier's existence query (`SELECT id FROM show WHERE
  name = ? AND vintage = ? AND status = 0`) is unchanged.
  Re-import idempotency holds regardless of whether the existing
  row's `name_romaji` matches the file's romaji (R3.5 of
  bugfix.md).
- The READ-ONLY guarantee on `import_plan.py` is unchanged
  (R3.2 of bugfix.md).
- The artist-creation and song-creation branches in
  `import_resolve.py` are unchanged. Only `_ensure_show`'s
  block-to-INSERT translation changes its observable output, and
  even there only because the upstream block now carries a real
  value where it carried `None`.
- The committed real AMQ fixture is read-only for every test that
  consumes it (R3.10 of bugfix.md).

**Scope:**

The fix is localised to:

- `scripts/import_plan.py`: one new row in `_AMQ_FIELD_MAP`
  (`show_name_romaji`); one row update on the `show_name` entry
  (drop the romaji fallback); one new dict key on
  `_load_entries`'s normalisation; one new dict key on
  `_entries_from_parsed`'s normalisation; `_resolve_show` reads
  the new flat key and threads it onto `show_to_create`.
- `scripts/import_resolve.py`: zero code changes. The line
  `name_romaji = block.get("name_romaji")` already exists.
- `skills/importing-amq-songs/SKILL.md`: new Step 0 section, new
  recovery procedure, updated input-shape documentation.
- `skills/importing-amq-songs/references/plan-shape.md`: field
  table and example snippets updated.
- `tests/`: new fixture variant (romaji-stripped),
  `test_importer_preprocessing.py` updates,
  `test_import_plan.py` and `test_import_resolve.py` updates,
  `test_importer_input_channels_property.py` PBT helper update.

The classifier, the four input channels, the error envelope shape
(modulo the new `details.kind` discriminator), and every other
script boundary are unchanged.

## Hypothesized Root Cause

Two compounding causes:

1. **`_resolve_show` was authored before romaji was a user-visible
   concern.** When the AMQ pipeline first landed, `show.name_romaji`
   was added to the schema (it appears in `scripts/schema.sql` and
   `_common.EXPECTED_SCHEMA["show"]` from day one) but the importer
   never plumbed it through. `_resolve_show` literally writes
   `"name_romaji": None` into every `show_to_create` block. The
   downstream `_ensure_show` reads `block.get("name_romaji")` and
   passes it to `_common.insert_row`, which writes the column —
   so the wiring is in place; only the input value is wrong.

2. **The romaji was repurposed as a fallback for the show name.**
   When the v0.1.2 `amq-real-export-shape-fix` corrected the
   mapping table, romaji was added under `show_name` as a
   secondary candidate path "in case English is missing". This
   conflates two distinct fields (the English title and the
   romanised title) into one column on `show.name`, makes
   English-missing rows indistinguishable from English-present
   rows downstream, and gives the importer no opportunity to
   reject romaji-missing entries that have an English title.

The fix splits the two concerns: `show_name` becomes English-only
(no fallback), `show_name_romaji` is its own required flat key
fed only by `songInfo.animeNames.romaji`. The wiring `_ensure_show`
already provides for `name_romaji` is finally fed a real value.

## Correctness Properties

### Property 1: Bug Condition — Romaji Required and Persisted

_For any_ AMQ import invocation through any channel where the
parsed payload reaches the classifier with at least one entry
whose canonical romaji slot is empty or missing, the fixed
preprocessor SHALL abort the file with
`INVALID_INPUT details = {index: i, missing_field:
"show_name_romaji", kind: "missing_romaji", available_keys: [...]}`
and exit code 1, naming the lowest such index, without writing
anything.

_For any_ AMQ import invocation whose payload reaches the
classifier with every entry carrying a non-empty romaji at the
canonical path, the fixed preprocessor SHALL emit
`show_name_romaji = <input romaji>` on every flattened entry,
`_resolve_show` SHALL thread it onto every `show_to_create` block
as `name_romaji`, and the resolve step SHALL persist
`show.name_romaji = <input romaji>` on every newly-created show
row.

The Step 0 sniff in the agent skill SHALL classify the same
offending entries the API surface would reject.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8–2.13**

### Property 2: Preservation — Every Other Invocation Is Byte-Equal

_For any_ AMQ import invocation whose payload reaches the
classifier with every entry carrying a non-empty romaji at the
canonical path, the fixed code SHALL produce the same bucket
assignments, the same exit code, the same stdout envelope, the
same stderr envelope, and the same plan bytes as v0.1.6 — except
that every `show_to_create` block's `name_romaji` flips from `None`
to the resolved string. Every script outside the
`import_plan.py` / `import_resolve.py` show-creation branch is
byte-identical.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8,
3.9, 3.10, 3.11, 3.13**

## Fix Implementation

### Decision 1 — Error code: reuse `INVALID_INPUT` with a `details.kind` discriminator

The romaji rejection rides the existing `INVALID_INPUT` envelope,
not a new error code. The envelope shape is:

```python
raise _common.KnownError(
    "INVALID_INPUT",
    f"AMQ song at index {i} is missing required field show_name_romaji.",
    {
        "index": i,
        "missing_field": "show_name_romaji",
        "kind": "missing_romaji",
        "available_keys": sorted(entry.keys()),
    },
)
```

The new `kind` discriminator is the surface the agent skill keys
on when deciding whether to enter the manual-recovery branch. Other
`INVALID_INPUT` causes (missing `artist_name`, missing `vintage`,
malformed JSON, etc.) carry no `kind` field today and continue to
carry none after the fix.

The rejected alternative — adding `MISSING_ROMAJI` to
`_common.VALID_ERROR_CODES` — was costlier without a payoff. It
would force a second entry in the approved error code set, a new
case in `tests/integration/test_error_codes.py`, and a fresh wire
contract for any external caller that pattern-matches on `code`.
The agent skill's discrimination logic is the same in either
shape; `details.kind` keeps the contract narrower.

### Decision 2 — Flat-key name: `show_name_romaji`

The flat key on the preprocessor output, on the legacy flat array
shape, and on the `show_to_create` block is `show_name_romaji`.

The other two candidates (`name_romaji` and `anime_romaji`) lose:

- `name_romaji` matches the DB column name, but on the flat
  surface every other key is prefixed with the entity it
  describes (`artist_name`, `song_name`, `show_name`, `vintage`,
  `media_url`). A bare `name_romaji` next to `show_name` reads as
  if it could belong to the artist or song.
- `anime_romaji` is AMQ-natural (AMQ calls them `animeNames`) but
  the rest of the codebase uses "show", not "anime", in
  identifiers (`show.name`, `show_name`, `show_id`,
  `show_to_create`). Mixing vocabularies invites grep-misses
  later.

The flat key → DB column translation lives in `_resolve_show`'s
`show_to_create` block: the block carries `name_romaji` (matching
the DB column), built from the flat key `show_name_romaji`. This
mirrors how `show_name` flat → `name` DB works today — `show_name`
on the flat side, `name` on the block side, `name` on the column.

### Decision 3 — `_AMQ_FIELD_MAP` table update

The mapping table changes in two places. Before:

```python
_AMQ_FIELD_MAP = (
    ("artist_name", (("songInfo", "artist"), ("artist_name",)), True),
    ("song_name",   (("songInfo", "songName"), ("song_name",)), True),
    ("show_name",   (("songInfo", "animeNames", "english"),
                     ("songInfo", "animeNames", "romaji"),
                     ("show_name",)), True),
    ("vintage",     (("songInfo", "vintage"), ("animeVintage",), ("vintage",)), True),
    ("media_url",   (("videoUrl",), ("audio",), ("media_url",),
                     ("MP3",), ("mp3",)), False),
)
```

After:

```python
_AMQ_FIELD_MAP = (
    ("artist_name",        (("songInfo", "artist"), ("artist_name",)), True),
    ("song_name",          (("songInfo", "songName"), ("song_name",)), True),
    ("show_name",          (("songInfo", "animeNames", "english"),
                            ("show_name",)), True),
    ("show_name_romaji",   (("songInfo", "animeNames", "romaji"),
                            ("show_name_romaji",)), True),
    ("vintage",            (("songInfo", "vintage"), ("animeVintage",),
                            ("vintage",)), True),
    ("media_url",          (("videoUrl",), ("audio",), ("media_url",),
                            ("MP3",), ("mp3",)), False),
)
```

Two changes:
- The `show_name` row drops its romaji fallback. English is the
  only AMQ-nested candidate. The single-key `("show_name",)`
  fallback stays so already-flat callers (the four-channel PBT,
  any in-repo tests that pass flat-per-song through the AMQ
  channel) keep working.
- A new `show_name_romaji` row is added, marked required, with
  the AMQ-nested path `songInfo.animeNames.romaji` plus the
  single-key flat alias `show_name_romaji` for the same reason.

The candidate loop in `_amq_entry_to_flat` is unchanged — it
already iterates path tuples and raises `INVALID_INPUT` on a
missing required field. The only patch needed inside the loop is
the new envelope's `details.kind = "missing_romaji"` when the
missing flat key is `show_name_romaji`. See Decision 4.

### Decision 4 — Discriminated `INVALID_INPUT` only for `show_name_romaji`

Only the romaji rejection carries `details.kind =
"missing_romaji"`. Other missing-required-field rejections in the
same loop (`artist_name`, `song_name`, `show_name`, `vintage`)
continue to emit the existing envelope without `kind`, exactly as
v0.1.6 ships. This keeps the wire contract stable for every
existing caller — the new field is purely additive on the romaji
rejection.

The candidate loop becomes:

```python
for flat_key, candidate_paths, required in _AMQ_FIELD_MAP:
    picked: str | None = None
    for path in candidate_paths:
        val = _get_nested(entry, path)
        if isinstance(val, str) and val != "":
            picked = val
            break
    if picked is None:
        if required:
            details: dict[str, Any] = {
                "index": i,
                "missing_field": flat_key,
                "available_keys": sorted(entry.keys()),
            }
            if flat_key == "show_name_romaji":
                details["kind"] = "missing_romaji"
            raise _common.KnownError(
                "INVALID_INPUT",
                f"AMQ song at index {i} is missing required field {flat_key}.",
                details,
            )
        picked = ""
    flat[flat_key] = picked
```

One added branch (`if flat_key == "show_name_romaji"`); every
other line of the loop is verbatim from v0.1.6.

### Decision 5 — Step 0 sniff lives inline in `SKILL.md`, agent runs it

The Step 0 sniff is a procedure the agent performs directly,
documented in `skills/importing-amq-songs/SKILL.md`. It is **not**
a new script under `scripts/`, **not** a new flag on
`import_plan.py`, and not anywhere on the test path. The agent
reads the user-supplied AMQ JSON file, iterates `songs[i]`
entries, and applies a small fixed taxonomy:

- **Hypothesis A — Shape drift**: the JSON has the right
  top-level structure (object with `songs` array, every entry has
  a `songInfo` sub-object), every entry's `songInfo` has an
  `animeNames` sub-object, but `animeNames` has no `romaji` key
  (or the value is empty / null). The sniff report SHALL include
  the actual key list inside `animeNames` for at least one
  affected entry — that's how the agent and user spot the rename
  ("the file has `romajiTitle` where we expect `romaji`"). If a
  plausible candidate path is found (a sibling key on
  `animeNames` whose value is a non-empty string), the sniff
  proposes it as the recovery source with one sample value.
- **Hypothesis B — Truncated / malformed entries**: at least one
  `songs[i]` is missing the `songInfo` container, or `songInfo`
  is missing `animeNames`, entirely. The sniff report SHALL
  include the index of every affected entry plus its top-level
  keys.
- **Hypothesis C — Genuinely-empty romaji**: `songInfo.animeNames`
  is intact and has a `romaji` key whose value is empty or
  `null`. The sniff report SHALL list affected indices. Recovery
  here is up to the user — if they can supply the romaji
  manually, they can use the `data.py create --kind show` path;
  otherwise the file genuinely cannot be ingested.

The taxonomy is intentionally small and named so the SKILL.md
recipe is short. The hypothesis report format is also
prescribed in the SKILL.md so the agent doesn't drift across
sessions:

```
Step 0 — Shape sniff result: FAILED for N entries.

  Hypothesis A — Shape drift (most likely):
    affected indices: [0, 1, 4, 5]
    songInfo.animeNames keys observed: ["english", "romajiTitle"]
    candidate recovery path: songInfo.animeNames.romajiTitle
    sample value at songs[0].songInfo.animeNames.romajiTitle:
      "Wooser no Sono Higurashi: Kakusei-hen"

  Confirm? Type "y" to accept Hypothesis A and recover via
  scripts/data.py create. Type "n" to abort and inspect the file.
```

The agent SHALL surface this report verbatim and ask for
confirmation before running any `scripts/data.py create` command.
On `n`, the agent stops; on `y`, the agent enters the
manual-recovery branch (Decision 6).

The rejected alternatives:

- **New `scripts/import_sniff.py`**: would force a new release
  artifact, new tests, and a new place for the AMQ-shape-knowledge
  to drift out of sync with `_AMQ_FIELD_MAP`. The agent already
  has all the capability needed (read the JSON, walk it, report).
  No new script earns its keep.
- **New `--sniff` flag on `import_plan.py`**: keeps the script
  inventory flat but couples diagnosis logic to the classifier
  file and adds yet another input channel. The classifier would
  need to know about the hypothesis taxonomy. Not worth it for a
  procedure the agent runs once before each import.

### Decision 6 — Manual-recovery branch uses `data.py create --kind show`

When the user confirms a Step 0 diagnosis, the agent:

1. Extracts the romaji from the candidate path the sniff
   identified (or from a user-supplied value, in the
   genuinely-empty case).
2. For each affected entry, runs:

   ```
   python scripts/data.py create --kind show '{
     "name": "<English title>",
     "name_romaji": "<extracted romaji>",
     "vintage": "<vintage>",
     "s_type": null
   }'
   ```

   `data.py create` already handles missing-id / missing-timestamp
   defaults, the `BEGIN IMMEDIATE` / `COMMIT` envelope, and the
   `CONSTRAINT_VIOLATION` rejection on duplicate `(name, vintage)`
   if the show already exists.

3. Re-runs the three-step pipeline. `import_plan.py`'s existence
   check (`name = ? AND vintage = ? AND status = 0`) hits the
   freshly-created show row and emits a `show_id` instead of a
   `show_to_create`. The pipeline proceeds normally.

The romaji on those entries is now baked into the DB and not on
the AMQ JSON — which is fine, because the `show_id` path skips
the `show_to_create` block entirely. Steps 2 and 3 of the
pipeline stay byte-identical.

### Decision 7 — Documentation lockstep

Two skill files change. `skills/importing-amq-songs/SKILL.md` gains:

- A new "Step 0 — Shape sniff" section in the Checklist, before
  "Step 1 — plan", with the hypothesis taxonomy and the report
  format from Decision 5.
- A new "Manual recovery" section after the Checklist describing
  the `data.py create --kind show` recipe from Decision 6.
- An update to the "Input shape" section: the flat array shape
  documents `show_name_romaji` as the sixth required field, and
  the AMQ-nested example carries `animeNames.romaji` non-empty.

`skills/importing-amq-songs/references/plan-shape.md` gains:

- `show_name_romaji` documented as required on the flat shape.
- The AMQ → flat field mapping table grows a row:
  `songInfo.animeNames.romaji`, `show_name_romaji`, required.
- The `show_name` row drops the `animeNames.romaji` fallback.
- `name_romaji` documented as a non-null string on the
  `show_to_create` block (today the example shows
  `name_romaji: null`; the example becomes the resolved romaji
  string).

No other skill file is touched (R3.13 of bugfix.md).

### Changes Required

**File**: `scripts/import_plan.py`

1. **`_AMQ_FIELD_MAP` rewrite** per Decision 3 — drop the
   `animeNames.romaji` fallback under `show_name`, add a new
   `show_name_romaji` row with one AMQ-nested path and one flat
   alias, both required.

2. **Candidate loop in `_amq_entry_to_flat`** per Decision 4 —
   one added branch for the `show_name_romaji` discriminator on
   `details.kind`.

3. **`_load_entries` normalisation block** — add `show_name_romaji`
   to the dict the function builds per entry, and validate it the
   same way the AMQ preprocessor does. The cleanest implementation
   is to share the validator: refactor `_load_entries` to call
   `_amq_entry_to_flat` on the flat alias paths only, so flat and
   AMQ paths share the same required-field-missing rejection. This
   is a one-line behaviour change (flat entries now reject
   `INVALID_INPUT details.kind = "missing_romaji"` when
   `show_name_romaji` is missing) that surfaces immediately on
   the legacy `--input` surface.

4. **`_entries_from_parsed` normalisation block** — add
   `show_name_romaji` to the dict it builds. Same validation as
   `_load_entries` (the function already runs flat-entry payloads
   through the same decode-and-normalise loop today).

5. **`_resolve_show`** — read `entry["show_name_romaji"]` and
   put it on the `show_to_create` block as `name_romaji`. The
   line `"name_romaji": None` becomes `"name_romaji":
   entry["show_name_romaji"]`.

6. **No other code in `scripts/import_plan.py` is touched.**
   `_get_nested`, `_discriminate`, `_flatten_amq`, `_classify`,
   the four-channel input dispatcher, and `_run` stay
   byte-identical.

**File**: `scripts/import_resolve.py`

7. **No code changes.** `_ensure_show` already reads
   `block.get("name_romaji")` and threads it into
   `_common.insert_row`. Today the `.get` returns `None` because
   the upstream block hard-codes it; after the fix it returns the
   resolved romaji string.

**File**: `scripts/_common.py`

8. **No code changes.** `VALID_ERROR_CODES` keeps the v0.1.6
   set; `EXPECTED_SCHEMA["show"]` and `SPECS["show"].columns`
   already include `name_romaji`.

**File**: `scripts/schema.sql`

9. **No code changes.** `show.name_romaji TEXT` already exists.

**File**: `tests/fixtures/amq_song_export-small.json`

10. **No changes.** Every entry already carries a non-empty
    `songInfo.animeNames.romaji`. Read-only per R3.10 of bugfix.md.

**File**: `tests/fixtures/amq_song_export-small-no-romaji.json` (new)

11. **Commit a romaji-stripped variant** of the same 9-song
    fixture, with at least one entry's `animeNames.romaji` set to
    the empty string (or removed entirely). This is the negative
    counterexample fixture: drives `import_plan.py` to the
    `MISSING_ROMAJI` rejection on UNFIXED code (today: passes
    silently with `name_romaji = NULL`), and to a typed rejection
    on fixed code. Read-only.

**File**: `tests/integration/test_import_plan.py`

12. **Add `test_real_amq_export_persists_romaji_into_show_block`**:
    drives `tests/fixtures/amq_song_export-small.json` through
    `import_plan.py --input-jsonpath`, asserts exit 0, and
    asserts every `show_to_create` block in the resulting plan
    carries a non-empty `name_romaji` matching the input AMQ
    song's `songInfo.animeNames.romaji`. Fails on UNFIXED code
    because every block has `name_romaji = null`.

13. **Add `test_real_amq_export_missing_romaji_is_rejected`**:
    drives `tests/fixtures/amq_song_export-small-no-romaji.json`
    through `import_plan.py --input-jsonpath`, asserts exit 1,
    asserts the stderr envelope is
    `INVALID_INPUT details = {"index": <int>, "missing_field":
    "show_name_romaji", "kind": "missing_romaji",
    "available_keys": [...]}`. Fails on UNFIXED code because the
    importer accepts the file silently.

14. **Update existing tests that wrap flat payloads into AMQ
    shape** to include `animeNames.romaji` on every wrapped entry.
    The four-channel byte-equality and the named
    `test_raw_amq_via_input_jsonpath_matches_flat_via_input` /
    `test_input_jsonstr_raw_amq_matches_flat_via_input` /
    `test_input_array_rejects_raw_amq_with_invalid_input` tests
    keep their structural assertions; only the wrapper shape they
    encode changes.

15. **Update existing tests that pass flat arrays through any
    channel** to carry `show_name_romaji` on every entry. Tests
    that already have a valid `show_name` and need a romaji can
    use the same string suffixed with `" (romaji)"` for clarity.
    The bucket-sum and resolve-step assertions are unchanged.

**File**: `tests/integration/test_import_resolve.py`

16. **Add `test_resolve_persists_show_name_romaji_into_db`**:
    given a plan with one `auto_completable` entry whose
    `show_to_create` carries `name_romaji = "Foo Romaji"`, run
    `import_resolve.py --plan plan.json --output triples.json`,
    then read back the `show` row and assert `name_romaji = "Foo
    Romaji"`. Today's resolve code already writes the column; the
    test is new because today no plan ever carries a non-null
    `name_romaji`, so the path is uncovered.

**File**: `tests/integration/test_import_pipeline_e2e.py`

17. **Update the end-to-end pipeline test** to assert that
    every newly-created show row carries a non-null `name_romaji`
    when the input AMQ JSON had a romaji on the corresponding
    entry. This is the integration evidence for Property 1's
    persistence claim.

**File**: `tests/unit/test_importer_preprocessing.py`

18. **Add three new `_amq_entry_to_flat` tests**:
    - `show_name_romaji_present`: emits the expected flat key.
    - `missing_show_name_romaji_raises_with_kind_missing_romaji`:
      asserts the discriminator is on the rejection envelope.
    - `missing_english_no_longer_falls_back_to_romaji`: an entry
      with `animeNames.english = ""` and `animeNames.romaji =
      "..."` raises `INVALID_INPUT missing_field=show_name`
      (no `kind`), confirming the fallback is removed.

19. **Update existing `_amq_entry_to_flat` tests** that
    construct flat entries to include `show_name_romaji` on every
    payload. The tests that exercise other missing-required-field
    rejections (`artist_name`, `song_name`, `vintage`,
    `show_name` with neither English nor flat alias present)
    keep their structural assertions; the entries grow one extra
    field but the envelope under test is unchanged.

**File**: `tests/integration/property/test_importer_input_channels_property.py`

20. **Update `_wrap_as_raw_amq`** to add `animeNames.romaji` on
    every wrapped entry, and update the flat baseline payload
    builder to add `show_name_romaji` on every entry. The
    four-channel byte-equality property is unchanged.

**File**: `skills/importing-amq-songs/SKILL.md`

21. **Add Step 0 — Shape sniff** to the Checklist per Decision
    5: hypothesis taxonomy, report format, agent procedure.

22. **Add Manual recovery** section per Decision 6.

23. **Update Input shape** section: flat array now documents
    `show_name_romaji`; AMQ-nested example shows
    `animeNames.romaji` populated.

**File**: `skills/importing-amq-songs/references/plan-shape.md`

24. **Update field-mapping table** per Decision 7: add the
    `show_name_romaji` row, drop the romaji fallback from
    `show_name`, document `name_romaji` as a non-null string on
    `show_to_create`.

### Rollout

- No new CLI flags, no new error codes, no schema migration. The
  envelope shape on the romaji rejection is additive
  (`details.kind` is a new key; existing keys keep their meaning).
- v0.1.6 is already tagged. This ships as v0.1.7 through the
  existing release pipeline (`release.md`,
  `.github/workflows/release.yml`) unchanged.
- `tests/fixtures/schema.sql` is byte-identical; no
  `make schema-sync` needed.
- The romaji-stripped fixture lands as a sibling read-only file;
  no test mutates it.

## Testing Strategy

### Validation Approach

Two phases. First, surface the bug on UNFIXED code via two new
integration tests:

1. The "romaji is silently null" counterexample
   (`test_real_amq_export_persists_romaji_into_show_block`) —
   passes on the existing fixture against UNFIXED code only by
   asserting the broken state today; we want it written to assert
   the fixed contract, so it WILL fail on UNFIXED code.
2. The "missing romaji is silently accepted" counterexample
   (`test_real_amq_export_missing_romaji_is_rejected` against the
   new romaji-stripped fixture) — fails on UNFIXED code (importer
   exits 0 today, exit 1 expected after the fix).

Then verify the fix works on those tests and preserves every
existing contract on every other input. The preservation vehicle
is the existing `test_importer_input_channels_property.py` PBT,
extended to include `animeNames.romaji` and `show_name_romaji` on
every wrapped entry.

### Exploratory Bug Condition Checking

**Goal**: Surface the counterexamples that demonstrate the bug
BEFORE implementing the fix. Confirm the root cause analysis. If
root-cause analysis is refuted, re-hypothesize.

**Test Plan**: Land two integration tests against the existing
fixture and a new romaji-stripped fixture. Run them on UNFIXED
code to observe the failures.

**Test Cases**:

1. **Romaji persistence on the real AMQ fixture**
   (`test_real_amq_export_persists_romaji_into_show_block`).
   Drives the 9-song fixture through `--input-jsonpath`,
   asserts every `show_to_create.name_romaji` is non-empty.
   Fails on UNFIXED code: every block has `name_romaji = null`.
2. **Rejection on a romaji-stripped fixture variant**
   (`test_real_amq_export_missing_romaji_is_rejected`). Drives
   `amq_song_export-small-no-romaji.json` through
   `--input-jsonpath`, asserts exit 1 with
   `INVALID_INPUT details.kind = "missing_romaji"`. Fails on
   UNFIXED code: importer exits 0 today.

**Expected Counterexamples**:

- Test 1 fails with every block emitting `name_romaji: null`.
  Root cause: `_resolve_show` hard-codes the value.
- Test 2 fails with exit 0 on the stripped fixture. Root cause:
  the romaji is a fallback under `show_name` today, not a
  required field; English present + romaji absent passes
  silently.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition
holds, the fixed function produces the expected behavior.

**Pseudocode:**

```
FOR ALL input WHERE isBugCondition(input) DO
  result := importPlan'(input)
  ASSERT result.exitCode = 1
  ASSERT result.error.code = "INVALID_INPUT"
  ASSERT result.error.details.kind = "missing_romaji"
  ASSERT result.error.details.missing_field = "show_name_romaji"
  ASSERT result.error.details.index ∈ ℕ
END FOR

FOR ALL input WHERE NOT isBugCondition(input) AND payloadIsValid(input) DO
  result := importPlan'(input)
  ASSERT result.exitCode = 0
  FOR ALL entry IN result.plan.auto_completable_and_resolved_with_create_blocks DO
    ASSERT entry.show_to_create.name_romaji ≠ null
    ASSERT entry.show_to_create.name_romaji ≠ ""
    ASSERT entry.show_to_create.name_romaji = correspondingInputRomaji(input.payload, entry)
  END FOR

  // After step 2:
  after := runResolve'(result.plan)
  FOR ALL row IN newlyCreatedShowRows(after) DO
    ASSERT row.name_romaji = correspondingInputRomaji(input.payload, row)
  END FOR
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does
NOT hold, the fixed function produces the same result as the
original function.

**Pseudocode:**

```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT importPlan(input).exitCode  = importPlan'(input).exitCode
  ASSERT importPlan(input).buckets   = importPlan'(input).buckets
  ASSERT planEqualUpToNameRomaji(importPlan(input), importPlan'(input))
END FOR
```

**Testing Approach**: The existing
`test_importer_input_channels_property.py` is the preservation
vehicle. After updating `_wrap_as_raw_amq` to include
`animeNames.romaji` and the flat baseline to include
`show_name_romaji`, the PBT asserts the same four-channel
byte-equality across many randomly generated payloads. The
property is unchanged; the wrapper shape it exercises grows one
field. This crosses the fixed mapping-table boundary on every
iteration.

### Unit Tests

`tests/unit/test_importer_preprocessing.py`:

- **`_amq_entry_to_flat`** (existing tests rewritten to include
  romaji on every payload, plus 3 new): all-amq-keys-present,
  all-flat-alias-keys-present, missing-required-fields each
  raising `INVALID_INPUT` with the right `missing_field`,
  `show_name_romaji_present` (new), `missing_show_name_romaji_raises_with_kind`
  (new), `missing_english_no_longer_falls_back_to_romaji` (new),
  drops-extra-amq-native-fields, stable-key-order.
- **`_flatten_amq`** (existing tests with one extra field per
  entry): structural assertions preserved.
- **`_get_nested`** (no changes — the helper's contract didn't
  shift).
- **`_discriminate`** (no changes — top-level shape detection
  didn't shift).

### Property-Based Tests

One existing PBT covers preservation; no new PBT is needed.

- **`test_all_input_channels_produce_byte_equal_plans`**
  (existing, with `_wrap_as_raw_amq` and the flat baseline
  builder updated): four-channel byte-equality across many
  randomly generated payloads. Now exercises
  `show_name_romaji` on every iteration. The property is
  unchanged.

The fix-checking property is covered by the deterministic
real-fixture integration test in Test Case 1 above plus the
romaji-stripped fixture in Test Case 2 — these are not random,
so a PBT wouldn't add value over the named tests.

### Integration Tests

`tests/integration/test_import_plan.py`:

- **`test_real_amq_export_persists_romaji_into_show_block`** (new,
  Task 12 of "Changes Required"): the persistence assertion on the
  9-song fixture.
- **`test_real_amq_export_missing_romaji_is_rejected`** (new, Task
  13): the rejection assertion on the romaji-stripped fixture.
- **Every existing AMQ-shape test** (Task 14): wrappers updated
  to include `animeNames.romaji`; structural assertions
  preserved.
- **Every existing flat-array-via-any-channel test** (Task 15):
  payloads grow `show_name_romaji`; bucket-sum and resolve
  assertions preserved.

`tests/integration/test_import_resolve.py`:

- **`test_resolve_persists_show_name_romaji_into_db`** (new, Task
  16): asserts the resolve step writes the column when the plan
  carries a non-null `name_romaji` on the block.

`tests/integration/test_import_pipeline_e2e.py`:

- **End-to-end pipeline test** (Task 17): asserts every newly
  created show row carries a non-null `name_romaji` matching the
  input.

The committed fixtures stay read-only across every test that
consumes them (R3.10).

## Out of Scope

- **Backfill of existing rows.** Shows already in the user's DB
  with `name_romaji = NULL` are not touched. The fix is
  forward-only; pre-existing rows stay as-is. A user who wants
  to populate them can do so via `scripts/data.py update --kind
  show --id <id> --data '{"name_romaji": "..."}'` per row, but
  that is not part of this spec.
- **Romaji on song or artist.** Schema has only `show.name_romaji`.
  Adding song-name or artist-name romaji is out of scope and
  would require a schema migration plus much wider import
  semantics.
- **Fuzzy match on existing-show lookups.** The existence query
  in `_classify` stays `name = ? AND vintage = ?`. Adding
  romaji to the match key would change re-import idempotency
  semantics and is out of scope.
- **Step 0 sniff for non-romaji fields.** The agent's pre-flight
  check is romaji-only. Other required fields are already gated
  by `import_plan.py`'s existing rejections; broadening the
  sniff is out of scope (the parent
  `amq-real-export-shape-fix` covered that audit one fix ago).
- **A new `--sniff` flag on `import_plan.py`** or a new
  `scripts/import_sniff.py` helper. Decision 5 rejects both.
- **A new `MISSING_ROMAJI` error code.** Decision 1 rejects it.
- **`scripts/learning.py`, `query.py`, `merge_artists.py`,
  `cleanup.py`, `add_play_history.py`, `init_db.py`, `data.py`,
  `review.py`** behaviors. None of these change. The romaji
  change is confined to `import_plan.py` and one already-existing
  line in `import_resolve.py`.
