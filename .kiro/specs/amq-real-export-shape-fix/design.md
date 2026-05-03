# AMQ Real Export Shape Fix — Bugfix Design

## Overview

The AMQ importer rejects the real file AMQ itself produces. The Bug 1
fix in the parent `importer-and-graduate-fixes` spec (shipped in
v0.1.1) introduced an AMQ-to-flat preprocessing stage in
`scripts/import_plan.py` and hard-coded its field mapping table
(`_AMQ_FIELD_MAP`) from the parent design document instead of the
actual AMQ export linked from `README.md`
(`docs/design/v1/amq_song_export-small.json`). The real AMQ JSON
nests every required field one level deep under `songInfo`, nests
show names a further level under `songInfo.animeNames`, and exposes
the media URL as a top-level `videoUrl` on the song — none of which
match the flat `songArtist` / `animeEnglishName` / `audio` keys the
preprocessor looks for today. On the first real file a user runs
through the importer the preprocessor aborts with
`INVALID_INPUT missing_field=artist_name`.

This fix changes `_AMQ_FIELD_MAP` from a flat-key table to a
**path-tuple** table, adds one tiny `_get_nested` helper to walk the
paths, and leaves the surrounding structure of
`_amq_entry_to_flat` / `_flatten_amq` exactly as it is. A committed
copy of the real AMQ export lands under `tests/fixtures/` and drives
a new integration test end-to-end through
`import_plan.py --input-jsonpath`, so a future mapping regression
cannot land silently. Every existing AMQ-shaped test in the repo is
rewritten to use the real nested wrapper; the structural contracts
they already assert (required-field-missing raises `INVALID_INPUT`,
extras silently dropped, stable key order, byte-equal plans across
the four input channels) stay unchanged. The one documentation
touch is `skills/importing-amq-songs/references/plan-shape.md` — its
field-mapping table currently encodes the v0.1.1 guessed flat-key
mapping and would otherwise contradict the fixed code.

No new CLI flags. No new error codes. No schema change. v0.1.1 is
already tagged and released; this ships as v0.1.2 through the
existing release pipeline unchanged.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — an
  invocation of `scripts/import_plan.py` via `--input-jsonpath` or
  `--input-jsonstr` whose parsed payload is the real AMQ export
  shape (a JSON object with a top-level `songs` array whose entries
  expose their data under a `songInfo` sub-object). See bugfix.md
  "Bug Condition".
- **Property (P)**: The desired behavior when C holds — the fixed
  preprocessor resolves the five flat fields from the correct
  nested paths, produces a valid flat entry list, and drives that
  list through the classifier to a plan (exit 0, no INVALID_INPUT,
  every required flat field populated from the right place).
- **Preservation**: Behavior on every invocation that does **not**
  meet C — flat-array payloads through any channel, non-AMQ garbage
  through any channel, every legacy `--input` / positional call.
  The fix must leave all of those byte-identical to v0.1.1.
- **`_AMQ_FIELD_MAP`**: The table in `scripts/import_plan.py` that
  lists, per flat key, the candidate places to read from on a raw
  AMQ song object. After this fix each candidate is a **path**
  (tuple of keys) rather than a single top-level key.
- **`_get_nested(obj, path)`**: New one-screen helper that walks
  `obj` along `path`, returning `None` on any missing container or
  non-dict container mid-walk.
- **`_amq_entry_to_flat(entry, i)`**: Existing per-song converter.
  After this fix it iterates the candidate **paths** instead of
  candidate top-level keys, but its outer contract (returns a dict
  with the five flat keys in declared order; raises
  `INVALID_INPUT` naming the missing flat key) is unchanged.
- **`_flatten_amq(payload)`**: Existing per-file converter that
  iterates `payload["songs"]`. Untouched by this fix.
- **Real AMQ export shape**: A JSON object whose top-level `songs`
  array has entries of the form
  `{"songInfo": {"artist", "songName", "animeNames": {"english",
  "romaji"}, "vintage", ...}, "videoUrl", ...<game-state>...}`.
  Distinguishing marker relative to the v0.1.1 guessed shape: the
  presence of a `songInfo` sub-object on at least one song.
- **F (`importPlan`)**: `scripts/import_plan.py` as it exists on
  `mainline` after v0.1.1 shipped — `_AMQ_FIELD_MAP` reads
  `songArtist` / `songName` / `animeEnglishName` /
  `animeRomajiName` / `vintage` / `audio` at the top level of each
  song object.
- **F' (`importPlan'`)**: `scripts/import_plan.py` after this fix —
  `_AMQ_FIELD_MAP` reads from the nested paths
  `songInfo.artist`, `songInfo.songName`,
  `songInfo.animeNames.english` / `songInfo.animeNames.romaji`,
  `songInfo.vintage`, and the top-level `videoUrl`.

## Bug Details

### Bug Condition

The bug manifests whenever `scripts/import_plan.py` is invoked via
`--input-jsonpath` or `--input-jsonstr` with the real AMQ export
shape. The preprocessor's `_AMQ_FIELD_MAP` performs a 1-level
`entry[key]` lookup at the top of each song object, so every
required field it looks for (`songArtist`, `songName`,
`animeEnglishName` / `animeRomajiName`, `vintage`) is missing. The
artist lookup fires first and the file is rejected with
`INVALID_INPUT missing_field=artist_name`. Even if that were
tolerated, the show and media lookups would also miss (the show
names live two levels deep under `songInfo.animeNames`; the media
URL lives at the top-level `videoUrl`, not `audio`). `--input-array`
is out of scope — it is flat-only by contract and never runs the
preprocessor.

**Formal Specification:**

```
FUNCTION isBugCondition(input)
  INPUT: input of type ImportPlanInvocation
          (argv + parsed payload; channel is --input-jsonpath
           or --input-jsonstr — --input-array is out of scope
           because it is flat-only and never runs the preprocessor)
  OUTPUT: boolean

  // True iff the parsed payload is the real AMQ export shape:
  // a dict with a `songs` list, at least one of whose entries
  // carries a `songInfo` sub-object. The presence of `songInfo`
  // is the distinguishing marker relative to the v0.1.1 guessed
  // flat-per-song shape.
  IF NOT isinstance(input.payload, dict) THEN RETURN False
  IF NOT isinstance(input.payload.get("songs"), list) THEN RETURN False
  FOR song IN input.payload["songs"] DO
    IF isinstance(song, dict) AND isinstance(song.get("songInfo"), dict) THEN
      RETURN True
    END IF
  END FOR
  RETURN False
END FUNCTION
```

### Examples

- **Real AMQ song (required fields)**:
  `{"songInfo": {"artist": "Tia", "songName": "Chotto Dekakete
  Kimasu", "animeNames": {"english": "Wooser's Hand-to-Mouth Life:
  Awakening Arc", "romaji": "Wooser no Sono Higurashi: Kakusei
  Hen"}, "vintage": "Winter 2014"}, "videoUrl": "https://..."}`.
  Today: exit 1 with
  `INVALID_INPUT details.missing_field="artist_name"`.
  Expected: the preprocessor emits
  `{"artist_name": "Tia", "song_name": "Chotto Dekakete Kimasu",
  "show_name": "Wooser's Hand-to-Mouth Life: Awakening Arc",
  "vintage": "Winter 2014", "media_url": "https://..."}`.
- **English-over-romaji precedence**: same song with
  `animeNames.english = ""` and `animeNames.romaji` populated. Today:
  same `INVALID_INPUT` from the artist lookup firing first.
  Expected: `show_name` resolves to the romaji value; every other
  field from the nested paths.
- **Top-level `videoUrl` absent**: real AMQ shape with no
  `videoUrl` on a song. Expected: `media_url = ""` (the preprocessor
  defaults optional `media_url` to the empty string, same as today
  on the v0.1.1 guessed shape). Today: preprocessor never gets
  there — the artist lookup aborts first.
- **Missing `songInfo` container** on one song, real AMQ shape
  otherwise: expected behavior is `INVALID_INPUT` naming
  `artist_name` as the missing field, same strictness contract as a
  missing leaf today. A missing nested container is treated the
  same as a missing leaf value — the file is rejected, not silently
  defaulted.
- **Flat five-field array** through `--input-jsonpath`: unchanged
  by this fix. The preprocessor only runs on the object shape; a
  list payload skips `_flatten_amq` entirely.
- **Counterexample that pins the bug**: the committed real AMQ
  export at `tests/fixtures/amq_song_export-small.json` (9 songs).
  On v0.1.1 code: exit 1,
  `INVALID_INPUT details.missing_field="artist_name"
  details.index=0`. On fixed code: exit 0, plan where
  `resolved + auto_completable + ambiguous == 9`.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- The legacy `--input <path>` / positional path surface: still
  flat-only, still parses files via `_load_entries`, identical plan
  output on identical input (R3.1).
- `--input-jsonpath` / `--input-jsonstr` / `--input-array` on the
  flat five-field JSON array shape: identical plan output to the
  legacy surface on the equivalent content (R3.2).
- `--input-array` rejection of any nested AMQ object shape with
  `INVALID_INPUT`, regardless of whether the nested shape is the
  v0.1.1 guessed one or the real nested one (R3.3).
- Read-only guarantee: the SQLite file at `db/datasource.db` is
  byte-identical before and after every run (R3.4).
- URL-decoding of every string field before any DB lookup,
  `SONG_INVARIANT_VIOLATION` handling, `media_url` carry-through,
  resolved `show_id` / `show_to_create` block (R3.5).
- The three-step pipeline handoff contract
  (`plan.json` / `answers.json` / `triples.json`). Steps 2 and 3
  are not touched (R3.6).
- `scripts/learning.py` behavior — Bug 2 from the parent spec is
  not re-addressed (R3.7).
- The skills tree content (`skills/README.md` and every
  `skills/*/SKILL.md`). Bugs 3 and 4 from the parent spec are not
  re-addressed. The one permitted documentation touch is the
  field-mapping table in
  `skills/importing-amq-songs/references/plan-shape.md`, which
  currently encodes the v0.1.1 guessed mapping and would otherwise
  contradict the fixed code (R3.8).
- Non-AMQ input rejection with `INVALID_INPUT` through any channel
  (R3.9).
- Structural assertions the existing unit and integration tests
  make — preprocessor outputs the five flat keys in a stable order,
  raises `INVALID_INPUT` on a missing required field, drops extras
  silently, produces byte-equal plans across the four input
  channels on equivalent flat payloads (R3.10).
- The committed real AMQ fixture is read-only for every test that
  consumes it (R3.11).

**Scope:**

All inputs that do NOT meet the Bug Condition should be completely
unaffected by this fix. This includes:

- Flat five-field JSON array payloads through any channel
  (`--input`, positional path, `--input-jsonpath`,
  `--input-jsonstr`, `--input-array`).
- Non-AMQ JSON (scalars, objects without a `songs` array,
  non-parseable JSON, missing files).
- Every downstream step (`import_resolve.py`,
  `add_play_history.py`, `learning.py`, `merge_artists.py`,
  `cleanup.py`, `query.py`, `data.py`, `review.py`, `init_db.py`).

The fix is localised to `_AMQ_FIELD_MAP`, one new tiny helper
(`_get_nested`), and the inner candidate loop inside
`_amq_entry_to_flat`. The classifier, the four input channels, the
error envelope shape, and every script boundary are unchanged.

## Hypothesized Root Cause

Based on the bug description and inspection of
`scripts/import_plan.py`, the cause is unambiguous:

1. **Field mapping table is flat-keyed, real shape is nested.**
   `_AMQ_FIELD_MAP` was authored from the parent design document
   (`importer-and-graduate-fixes/design.md`), which listed candidate
   raw keys as `songArtist` / `songName` / `animeEnglishName` /
   `animeRomajiName` / `vintage` / `audio`. `_amq_entry_to_flat`
   does a 1-level `entry.get(raw_key)` lookup per candidate. The
   real AMQ export nests every one of those under
   `songInfo.*` (and `songInfo.animeNames.*` for show names), with
   the media URL as a top-level `videoUrl` on the song. Every
   top-level lookup therefore returns `None`. The artist lookup
   fires first and the file is rejected.

2. **No test in the v0.1.1 suite reads the real AMQ export.**
   Every AMQ-shaped test in the repo synthesises a payload in the
   guessed shape — `tests/unit/test_importer_preprocessing.py`
   builds per-song entries with `songArtist` / `songName` / etc.;
   the integration tests in `tests/integration/test_import_plan.py`
   and `tests/integration/property/test_importer_input_channels_property.py`
   wrap flat entries into a top-level `{"songs": [...]}` object
   using the same guessed per-song keys. Every assertion is
   self-consistent but fictional. CI passed on v0.1.1 despite the
   mismatch with reality because nothing in the suite crossed the
   mapping-table boundary with a real payload.

The fix is therefore a table update plus one small nested-lookup
helper. The classifier, the four input channels, and the error
envelope shape all stay exactly as they are.

## Correctness Properties

Property 1: Bug Condition — Real AMQ Export Shape Is Accepted

_For any_ invocation of `scripts/import_plan.py` via
`--input-jsonpath` or `--input-jsonstr` where the parsed payload is
the real AMQ export shape (a dict with a top-level `songs` array
whose entries carry their song data under a `songInfo` sub-object),
the fixed preprocessor SHALL resolve the five flat fields from the
correct nested paths — `artist_name` from `songInfo.artist`,
`song_name` from `songInfo.songName`, `show_name` from
`songInfo.animeNames.english` (falling back to
`songInfo.animeNames.romaji`), `vintage` from `songInfo.vintage`,
and `media_url` from the top-level `videoUrl` — and drive the
resulting flat entry list through the classifier to a plan (exit 0,
no `INVALID_INPUT` envelope).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**

Property 2: Preservation — Every Other Invocation Is Byte-Identical

_For any_ invocation of `scripts/import_plan.py` where the parsed
payload is **not** the real AMQ export shape — flat five-field
arrays through any channel, non-AMQ garbage through any channel,
every legacy `--input` / positional call, and every
`--input-array` call regardless of shape — the fixed code SHALL
produce exit code, stdout bytes, stderr bytes, and plan bytes
identical to the v0.1.1 code, preserving the legacy surface, the
flat-array paths through the three new channels, the
`--input-array` flat-only contract, read-only DB behavior,
URL-decoding, `SONG_INVARIANT_VIOLATION` handling, the pipeline
handoff contract, and every structural assertion the existing
tests make.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.9, 3.10, 3.11**

## Fix Implementation

### Decision 1 — Field mapping format: path tuples (Option A)

`_AMQ_FIELD_MAP` changes from a flat tuple of
`(flat_key, tuple[str, ...], required)` rows to a tuple of
`(flat_key, tuple[tuple[str, ...], ...], required)` rows. Each
**candidate** is now a **path** — a tuple of keys to walk one step
at a time. The legacy flat aliases (`artist_name`, `song_name`,
`show_name`, `vintage`, `media_url`, plus `MP3`/`mp3`/`audio`/
`animeVintage`) stay in the table as single-key paths so tests and
callers that pass already-flat entries through the AMQ channel
still work (important for R2.11, which keeps those callers working,
and for the existing property-based four-channel equivalence test).

The rejected alternative, Option B ("one-time flattener" that
normalises real AMQ entries into the v0.1.1 flat-per-song shape
before the existing table sees them), would introduce two layers of
aliases on the same input domain: the per-song flattener picks
between `songInfo.artist` and top-level `songArtist`, and then the
existing table picks between `songArtist` and `artist_name`. The
mapping table stops being the single source of truth. Option A
keeps the table authoritative and self-documenting about the real
nesting; the fix is ~10 lines of real code plus the tightly-scoped
changes to the candidate loop inside `_amq_entry_to_flat`.

### Decision 2 — Nested lookup helper

A new pure helper `_get_nested(obj, path)` walks `obj` along
`path`, returning `None` on any missing container or non-dict
container mid-walk. It returns the final value regardless of type;
the caller (`_amq_entry_to_flat`) decides what counts as "present"
(currently: non-empty string).

### Decision 3 — Fixture location

The committed copy of the real AMQ export lands at
`tests/fixtures/amq_song_export-small.json`. `tests/fixtures/` is
the repo's existing convention for shared test reference inputs
(`tests/fixtures/schema.sql` lives there too). The file is ~10 KB,
which is fine to commit.

### Decision 4 — Integration test shape

The new integration test
`test_real_amq_export_file_ingests_end_to_end` in
`tests/integration/test_import_plan.py` drives the full fixture
through the `--input-jsonpath` channel end-to-end and asserts the
plan shape, using the `tmp_app_root` fixture for isolation.

### Decision 5 — Updating existing tests

Every existing AMQ-shaped test in the repo is rewritten to use the
real nested wrapper (no wrapper-shape tests stay on the old
guessed shape). Structural assertions are preserved verbatim. The
four-channel byte-equality PBT helper is the only test-helper
change; the property it asserts is unchanged.

### Decision 6 — Documentation touch

`skills/importing-amq-songs/references/plan-shape.md` has its field
mapping table and the example AMQ JSON snippet rewritten to show
the real nested paths. The "English wins over Romaji" note and the
required/optional column are preserved.

### Changes Required

**File**: `scripts/import_plan.py`

**Specific Changes**:

1. **Add `_get_nested(obj, path)` helper** near the top of the
   "Raw-AMQ preprocessing helpers" block, above `_AMQ_FIELD_MAP`:

   ```python
   def _get_nested(obj: object, path: tuple[str, ...]) -> object:
       """Walk `obj` along `path`. Return None on any missing
       container or non-dict container mid-walk. Returns the final
       value even if it's not a string — caller decides what counts
       as "present".
       """
       cur: object = obj
       for key in path:
           if not isinstance(cur, dict):
               return None
           cur = cur.get(key)
           if cur is None:
               return None
       return cur
   ```

2. **Change `_AMQ_FIELD_MAP` candidates from top-level keys to
   path tuples**. The table becomes:

   ```python
   _AMQ_FIELD_MAP: tuple[tuple[str, tuple[tuple[str, ...], ...], bool], ...] = (
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

   Each candidate is now a path tuple. The real nested paths come
   first so they win on real AMQ payloads; the flat aliases stay as
   single-key paths so already-flat callers (the in-repo tests that
   pass flat-per-song entries through the AMQ channel, and the
   four-channel PBT helper) still work.

3. **Change the candidate loop in `_amq_entry_to_flat`** from
   iterating `candidates` as top-level keys to iterating them as
   paths, dispatching through `_get_nested`:

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
               raise _common.KnownError(
                   "INVALID_INPUT",
                   f"AMQ song at index {i} is missing required field {flat_key}.",
                   {
                       "index": i,
                       "missing_field": flat_key,
                       "available_keys": sorted(entry.keys()),
                   },
               )
           picked = ""
       flat[flat_key] = picked
   ```

   Every contract on `_amq_entry_to_flat` outside the candidate
   loop is unchanged: same `INVALID_INPUT` envelope on a missing
   required field (same `index` / `missing_field` /
   `available_keys` details), same drop-on-the-floor behavior for
   extras, same declared key order on the return dict, same default
   for optional `media_url`.

4. **`_flatten_amq` is not modified.** It still iterates
   `payload["songs"]` and calls `_amq_entry_to_flat` per entry.

5. **No other code in `scripts/import_plan.py` is touched.**
   `_discriminate`, `_entries_from_parsed`, the classifier, the
   four input channels, and `_run` stay byte-identical.

**File**: `tests/fixtures/amq_song_export-small.json`

**Specific Changes**:

6. **Commit a copy of the real AMQ export** (9 songs, ~10 KB) at
   this path. The file is read-only for every test that consumes
   it (R3.11).

**File**: `tests/integration/test_import_plan.py`

**Specific Changes**:

7. **Add `test_real_amq_export_file_ingests_end_to_end`**. The
   test:
   - Uses the `tmp_app_root` fixture (zero rows seeded — every AMQ
     song will land in `auto_completable` since the DB is empty).
   - Resolves the fixture path absolutely from `__file__` and
     copies it into `tmp_app_root` so `--input-jsonpath` can read
     it with a stable path.
   - Runs `import_plan.py --input-jsonpath <fixture>
     --output plan.json` via `pinned_call`.
   - Asserts exit 0 and no stderr error envelope.
   - Asserts
     `len(plan["resolved"]) + len(plan["auto_completable"]) + len(plan["ambiguous"]) == 9`.
   - Pins one song by name — e.g. "Chotto Dekakete Kimasu" by
     "Tia", show "Wooser's Hand-to-Mouth Life: Awakening Arc" — and
     asserts at least one entry in the plan has
     `artist_to_create.name == "Tia"`, `song_name == "Chotto
     Dekakete Kimasu"`, and a `show_to_create.name` matching the
     real English show name from the fixture.

8. **Rewrite
   `test_raw_amq_via_input_jsonpath_matches_flat_via_input`**.
   Change the `amq_raw_payload` dict from the v0.1.1 guessed
   per-song keys to the real nested shape:

   ```python
   amq_raw_payload = {
       "songs": [
           {
               "songInfo": {
                   "artist": "Artist A",
                   "songName": "Song A",
                   "animeNames": {"english": "Show A", "romaji": "Shou A"},
                   "vintage": "Fall 2024",
               },
               "videoUrl": "http://x/a",
           }
       ],
       "quizSettings": {"gameMode": "Solo", "songCount": 1},
   }
   ```

   The test's purpose (raw AMQ via `--input-jsonpath` produces a
   byte-equal plan to the equivalent flat array via legacy
   `--input`) is unchanged.

9. **Rewrite
   `test_input_jsonstr_raw_amq_matches_flat_via_input`**. Same
   shape update as change 8 — the `amq_raw_jsonstr` dict is
   rewritten to the real nested shape. Test purpose unchanged.

10. **Rewrite
    `test_input_array_rejects_raw_amq_with_invalid_input`**. Same
    shape update — the raw AMQ JSON string is rewritten to the
    real nested shape. The test's purpose
    (`--input-array` rejects any nested AMQ object with
    `INVALID_INPUT`) is unchanged; R3.3 guarantees the rejection
    contract holds for the real shape too.

**File**: `tests/unit/test_importer_preprocessing.py`

**Specific Changes**:

11. **Rewrite all 14 `_amq_entry_to_flat` tests** that use the
    v0.1.1 guessed per-song keys. Replace
    `{"songArtist": ..., "songName": ..., "animeEnglishName": ...,
    "animeRomajiName": ..., "vintage": ..., "audio": ...}` with
    `{"songInfo": {"artist": ..., "songName": ..., "animeNames":
    {"english": ..., "romaji": ...}, "vintage": ...},
    "videoUrl": ...}`. Preserve every structural assertion:
    required-field-missing raises `INVALID_INPUT`, extras silently
    dropped, stable key order, empty-string-counts-as-missing,
    English wins over Romaji, optional `media_url` defaults to
    `""`. The `available_keys` assertion on the missing-artist
    test needs to reflect the real top-level keys of the real
    nested entry (e.g. `["songInfo", "videoUrl"]` when
    `songInfo.artist` is missing) rather than the v0.1.1 flat keys.

12. **Rewrite all 4 `_flatten_amq` tests** the same way. Payload
    structure changes; structural assertions stay.

13. **Add 3 new tests for `_get_nested`** (direct coverage for the
    new helper):
    - Path of length 0: returns the input object unchanged.
    - Path of length 1 hits a leaf: returns the leaf.
    - Path of length 3 hits a leaf through nested dicts: returns
      the leaf.
    - Missing mid-walk: returns `None`.
    - Non-dict mid-walk (e.g. the path tries to descend into a
      string): returns `None`.

**File**:
`tests/integration/property/test_importer_input_channels_property.py`

**Specific Changes**:

14. **Rewrite `_wrap_as_raw_amq(flat)`** — the helper that wraps a
    flat payload into an AMQ-shaped dict. The per-song dict
    changes from the v0.1.1 guessed keys to the real nested
    shape:

    ```python
    return {
        "songs": [
            {
                "songInfo": {
                    "artist": e["artist_name"],
                    "songName": e["song_name"],
                    "animeNames": {"english": e["show_name"]},
                    "vintage": e["vintage"],
                },
                "videoUrl": e["media_url"],
            }
            for e in flat
        ],
        "extra": "metadata",
    }
    ```

    The test itself (`test_all_input_channels_produce_byte_equal_plans`)
    is unchanged — it still asserts that all six output files
    (legacy `--input`, `--input-jsonpath` on flat, `--input-jsonstr`
    on flat, `--input-array` on flat, `--input-jsonpath` on raw
    AMQ, `--input-jsonstr` on raw AMQ) are byte-equal to the
    legacy baseline. The property is the same; the wrapper shape
    it exercises changes.

**File**:
`skills/importing-amq-songs/references/plan-shape.md`

**Specific Changes**:

15. **Rewrite the "Raw AMQ input mapping" section** — the JSON
    example snippet and the field-mapping table. The example
    becomes the real nested shape; the table shows the real nested
    paths:

    | Raw AMQ path(s) tried, in order | Flat key | Required? |
    |---|---|---|
    | `songInfo.artist`, `artist_name` | `artist_name` | yes |
    | `songInfo.songName`, `song_name` | `song_name` | yes |
    | `songInfo.animeNames.english`, `songInfo.animeNames.romaji`, `show_name` | `show_name` | yes (English beats Romaji) |
    | `songInfo.vintage`, `animeVintage`, `vintage` | `vintage` | yes |
    | `videoUrl`, `audio`, `media_url`, `MP3`, `mp3` | `media_url` | no — defaults to `""` |

    The English-over-romaji note and the required/optional column
    are preserved. No other skill file is touched.

**Rollout:**

- No new CLI flags, no new error codes, no schema change.
- Every workflow (`release.md`, `.github/workflows/release.yml`)
  stays as-is. v0.1.1 is already tagged and released; this ships
  as v0.1.2 when the user tags and pushes. The existing release
  pipeline produces a v0.1.2 zip unchanged.
- `tests/fixtures/schema.sql` is byte-identical; no
  `make schema-sync` needed.

## Testing Strategy

### Validation Approach

Two phases: first, surface the counterexample that demonstrates the
bug on unfixed code (a real AMQ fixture ingest that exits 1 with
`INVALID_INPUT missing_field=artist_name`); then verify the fix
works correctly on that real fixture and preserves every existing
contract on every other input shape and channel.

The preservation approach is shifted onto existing coverage in the
repo. `test_importer_input_channels_property.py` already runs a
four-channel byte-equality property-based test; the only change is
rewriting `_wrap_as_raw_amq` to produce the real nested shape so
the test crosses the fixed mapping-table boundary. No new
preservation PBT is needed.

### Exploratory Bug Condition Checking

**Goal**: Surface the counterexample that demonstrates the bug
BEFORE implementing the fix. Confirm the root cause analysis. If
root-cause analysis is refuted, re-hypothesize.

**Test Plan**: Commit the real AMQ export fixture at
`tests/fixtures/amq_song_export-small.json`. Write one integration
test that drives the fixture through `import_plan.py
--input-jsonpath` end-to-end and asserts the three-bucket sum.
Run this test on the UNFIXED code to observe the failure and
understand the root cause.

**Test Cases**:

1. **Real AMQ fixture ingest**
   (`test_real_amq_export_file_ingests_end_to_end` in
   `tests/integration/test_import_plan.py`): ingests the 9-song
   real AMQ fixture end-to-end, asserts exit 0, no stderr envelope,
   `resolved + auto_completable + ambiguous == 9`, and one pinned
   song resolves with the expected artist / song / show names.
   Will fail on unfixed code with exit 1 and
   `INVALID_INPUT details.missing_field="artist_name"
   details.index=0`.

**Expected Counterexamples**:

- Exit 1 with `INVALID_INPUT details.missing_field="artist_name"`
  on song index 0 — the first song in the fixture has no top-level
  `songArtist` key; the artist lookup aborts before any other
  field is checked.
- Root cause: `_AMQ_FIELD_MAP` does a 1-level `entry[key]` lookup;
  the real AMQ nests `artist` one level deep under `songInfo`.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds,
the fixed function produces the expected behavior.

**Pseudocode:**

```
FOR ALL input WHERE isBugCondition(input) DO
  result := importPlan'(input)
  ASSERT result.exitCode = 0
  ASSERT result.error    = null

  flattened := toFlatFiveField'(input.payload)
  FOR ALL i, entry IN enumerate(flattened) DO
    ASSERT entry.artist_name = input.payload.songs[i].songInfo.artist
    ASSERT entry.song_name   = input.payload.songs[i].songInfo.songName
    english := input.payload.songs[i].songInfo.animeNames.english
    romaji  := input.payload.songs[i].songInfo.animeNames.romaji
    IF english ≠ "" AND english ≠ null THEN
      ASSERT entry.show_name = english
    ELSE
      ASSERT entry.show_name = romaji
    END IF
    ASSERT entry.vintage   = input.payload.songs[i].songInfo.vintage
    videoUrl := input.payload.songs[i].videoUrl
    IF videoUrl ≠ "" AND videoUrl ≠ null THEN
      ASSERT entry.media_url = videoUrl
    ELSE
      ASSERT entry.media_url = ""
    END IF
  END FOR

  ASSERT length(flattened)
       = length(result.plan.resolved)
       + length(result.plan.auto_completable)
       + length(result.plan.ambiguous)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does
NOT hold, the fixed function produces the same result as the
original function.

**Pseudocode:**

```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT importPlan(input) = importPlan'(input)
END FOR
```

**Testing Approach**: The existing
`test_importer_input_channels_property.py` already asserts a
four-channel byte-equality property across randomly generated flat
payloads. It is the preservation vehicle for this fix. Rewriting
`_wrap_as_raw_amq` to produce the real nested shape forces the PBT
to cross the fixed mapping-table boundary on every iteration; the
assertion (all six plan outputs byte-equal to the legacy baseline)
is unchanged. This covers preservation on the flat-array paths
through every channel, the legacy surface's byte-identity with
itself, and the raw-AMQ-equivalent-to-flat guarantee for the
real nested shape.

Property-based coverage is the right fit here: it generates many
random payloads across `resolved` / `auto_completable` /
`ambiguous` bucketings and stresses the byte-equality invariant
across six output files per iteration. Manual unit tests alone
would not catch a regression that only surfaces on a specific
bucket mix.

**Test Plan**: Observe the existing PBT's baseline behavior on
UNFIXED code first — it currently passes with the v0.1.1 guessed
`_wrap_as_raw_amq` because both the table and the wrapper live in
the same fiction. After rewriting `_wrap_as_raw_amq` to the real
shape AND fixing `_AMQ_FIELD_MAP`, the PBT continues to pass. If
the wrapper is updated without the table fix, the PBT fails with
the same `INVALID_INPUT missing_field=artist_name` as the Task 1
exploration test — that's the intended shape of the regression
gate.

**Test Cases**:

1. **Four-channel byte-equality across flat + real-nested**
   (`test_all_input_channels_produce_byte_equal_plans`, existing):
   after the `_wrap_as_raw_amq` update, verifies that legacy
   `--input`, `--input-jsonpath` on flat, `--input-jsonstr` on
   flat, `--input-array` on flat, `--input-jsonpath` on real
   nested AMQ, and `--input-jsonstr` on real nested AMQ all
   produce byte-equal plans to the legacy baseline, across many
   randomly generated flat payloads. Preserves R3.1, R3.2, R3.10.
2. **Raw AMQ via `--input-jsonpath` byte-matches flat via
   `--input`** (`test_raw_amq_via_input_jsonpath_matches_flat_via_input`,
   rewritten): single-entry variant of case 1 with the real nested
   wrapper; keeps the named integration test green.
3. **Raw AMQ via `--input-jsonstr` byte-matches flat via
   `--input`** (`test_input_jsonstr_raw_amq_matches_flat_via_input`,
   rewritten): same update.
4. **`--input-array` rejects the real nested AMQ shape**
   (`test_input_array_rejects_raw_amq_with_invalid_input`,
   rewritten): preserves R3.3 — the flat-only channel rejects any
   nested AMQ object, including the real shape.
5. **Existing `--input` / positional flat-array tests**: every
   test in `test_import_plan.py` that uses the legacy surface on
   flat arrays (resolved exact match, auto_completable artist
   exists, auto_completable artist missing, ambiguous, invariant
   violation, missing-show, URL-decoded, `--output`, positional
   path, read-only, mixed buckets, missing file, non-JSON,
   non-array top-level) stays unchanged and stays green.
   Preserves R3.1, R3.4, R3.5, R3.9.

### Unit Tests

Coverage for the pure preprocessing helpers, direct per-function:

- **`_get_nested`** (new helper, 3-5 tests in
  `test_importer_preprocessing.py`): path of length 0 / 1 / 3;
  missing mid-walk; non-dict mid-walk. Pins the helper's contract
  so a future refactor can't silently change it.
- **`_amq_entry_to_flat`** (14 existing tests, rewritten to the
  real nested shape): all-amq-keys-present, all-flat-alias-keys-
  present, english-beats-romaji, romaji-fallback, missing-optional-
  media-defaults-empty, empty-string-media-defaults-empty,
  missing-artist-raises (plus index and `available_keys` details
  on the real shape), empty-string-artist-counts-as-missing,
  missing-song-raises, missing-show-raises, missing-vintage-raises,
  drops-extra-amq-native-fields, stable-key-order. Every structural
  assertion is preserved.
- **`_flatten_amq`** (4 existing tests, rewritten to the real
  nested shape): three-song-happy-path, non-dict-entry-raises-
  with-index, empty-songs-returns-empty-list, ignores-top-level-
  siblings. Structure preserved.
- **`_discriminate`** (9 existing tests, unchanged): the
  discriminator doesn't care about per-song shape, only the
  top-level list-vs-dict-with-`songs`-list distinction. These
  tests stay byte-identical.

### Property-Based Tests

Exactly one PBT is in scope for this fix, and it already exists:

- **`test_all_input_channels_produce_byte_equal_plans`**
  (`tests/integration/property/test_importer_input_channels_property.py`,
  existing with `_wrap_as_raw_amq` rewritten): the four-channel
  byte-equality property across many randomly generated flat
  payloads, now exercising the real nested wrapper shape through
  the preprocessor on every iteration. This is the preservation
  vehicle (Property 2 in the Correctness Properties section).

No new PBT is needed. The existing PBT already covers the
preservation property; it was just asserting against the wrong
wrapper. The fix-checking property (Property 1) is covered by the
deterministic real-fixture integration test (Task 1 exploration)
plus the pinned-song assertions — it's not a randomised property,
so a PBT wouldn't add value.

### Integration Tests

End-to-end CLI coverage through the `pinned_call` subprocess
harness:

- **`test_real_amq_export_file_ingests_end_to_end`** (new, Task 1
  exploration test): drives the committed 9-song real AMQ fixture
  through `--input-jsonpath` and asserts the plan shape plus one
  pinned song. This is the named counterexample that demonstrates
  the bug on unfixed code and that must pass on fixed code.
- **`test_raw_amq_via_input_jsonpath_matches_flat_via_input`**
  (existing, rewritten): single-entry real nested payload through
  `--input-jsonpath` byte-matches the equivalent flat array
  through legacy `--input`. Keeps the named byte-equality
  integration test honest.
- **`test_input_jsonstr_raw_amq_matches_flat_via_input`**
  (existing, rewritten): same test for the `--input-jsonstr`
  channel.
- **`test_input_array_rejects_raw_amq_with_invalid_input`**
  (existing, rewritten): preserves the `--input-array` flat-only
  rejection contract against the real nested shape.
- **Every other integration test in `test_import_plan.py`**:
  unchanged. The legacy `--input` / positional path flow is
  untouched by this fix; its tests stay byte-identical and stay
  green. This is the main structural evidence for R3.1, R3.4,
  R3.5, R3.6, R3.9.

The real fixture stays read-only across every test that consumes
it (R3.11); tests that need a working copy inside `tmp_app_root`
copy the fixture via `shutil.copyfile` rather than mutating the
committed file.
