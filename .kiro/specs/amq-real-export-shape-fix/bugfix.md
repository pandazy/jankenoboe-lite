# Bugfix Requirements Document

## Introduction

The AMQ importer rejects the real file AMQ itself produces. The Bug 1
fix in the `importer-and-graduate-fixes` spec (shipped in v0.1.1)
introduced an AMQ-to-flat preprocessing stage in
`scripts/import_plan.py` and hard-coded a field mapping table
(`_AMQ_FIELD_MAP`) that was guessed from the parent design document
without verifying against the actual AMQ export file linked from
`README.md` (`docs/design/v1/amq_song_export-small.json`). The real
AMQ JSON has a top-level `songs` array whose entries nest the song
data one level deep under a `songInfo` object, with show names nested
a further level under `songInfo.animeNames`, and expose the media URL
as a top-level `videoUrl` field — none of which match the flat
`songs[i].songArtist` / `songs[i].animeEnglishName` / `songs[i].audio`
layout the preprocessor looks for today. On the first real file a
user runs through the importer the preprocessor aborts with
`INVALID_INPUT` naming `artist_name` as the missing field; even if
that were tolerated the show and media lookups would also miss. No
integration test in the current suite reads an actual AMQ export —
every AMQ-shaped test in the repo synthesises a payload in the
guessed shape, so the v0.1.1 CI gate passed despite the mismatch with
reality. This spec fixes the field mapping to match the real nested
AMQ export structure and adds an integration test that drives a
committed copy of the real file end-to-end through
`import_plan.py --input-jsonpath`, so a future mapping regression
cannot land silently.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a user invokes `scripts/import_plan.py --input-jsonpath <path>`
against a JSON file that is the real AMQ export shape (top-level
object with a `songs` array, each entry carrying its data under a
nested `songInfo` sub-object) THEN the system aborts with exit code 1
and an `INVALID_INPUT` error envelope whose
`details.missing_field` is `"artist_name"`, because the preprocessor's
`_AMQ_FIELD_MAP` looks for `songs[i].songArtist` (and the flat alias
`songs[i].artist_name`) at the top level of each song object, and
neither key exists on the real AMQ song — the artist name lives at
`songs[i].songInfo.artist`.

1.2 WHEN the preprocessor's artist lookup is hypothetically tolerated
and execution reaches the show-name lookup on the real AMQ shape THEN
the system aborts with `INVALID_INPUT` naming `show_name` as missing,
because the preprocessor looks for `songs[i].animeEnglishName` /
`songs[i].animeRomajiName` / `songs[i].show_name` at the top level of
each song object, and none of those keys exist on the real AMQ song —
the show names live at `songs[i].songInfo.animeNames.english` and
`songs[i].songInfo.animeNames.romaji`, nested two levels deep.

1.3 WHEN the preprocessor's artist and show lookups are hypothetically
tolerated and execution reaches the song-name and vintage lookups on
the real AMQ shape THEN the system aborts with `INVALID_INPUT` naming
`song_name` (or `vintage`) as missing, because the preprocessor looks
for `songs[i].songName` and `songs[i].vintage` at the top level of
each song object, and neither key exists there — the song name lives
at `songs[i].songInfo.songName` and the vintage at
`songs[i].songInfo.vintage`, one level deeper than the preprocessor
reads.

1.4 WHEN the preprocessor's required-field lookups are all
hypothetically tolerated and execution reaches the `media_url`
fallback on the real AMQ shape THEN the system silently records
`media_url = ""` for every song, because the preprocessor looks for
`songs[i].audio` / `songs[i].media_url` / `songs[i].MP3` /
`songs[i].mp3` and none of them exist on the real AMQ song — the
media URL lives at `songs[i].videoUrl` (top-level of the song object,
not nested under `songInfo`).

1.5 WHEN the full pipeline
(`import_plan.py` → `import_resolve.py` → `add_play_history.py`) is
invoked against a real AMQ export file THEN the system cannot
complete step 1, so no plan is produced and no downstream step runs —
the user sees only the INVALID_INPUT envelope from clause 1.1 and has
no workable path to ingest the file.

1.6 WHEN the v0.1.1 test suite runs against `scripts/import_plan.py`
THEN the system reports a passing CI gate despite the mismatch with
the real AMQ export, because every AMQ-shaped test synthesises its
payload using the guessed field names — `tests/unit/test_importer_preprocessing.py`
builds each test entry with `songArtist` / `songName` /
`animeEnglishName` / `animeRomajiName` / `vintage` / `audio`, and the
integration tests in `tests/integration/test_import_plan.py` and
`tests/integration/property/test_importer_input_channels_property.py`
wrap flat entries into a top-level `{"songs": [...]}` object using
the same guessed per-song keys, so they assert a self-consistent but
fictional shape and never exercise the real `songInfo` / `animeNames`
/ `videoUrl` layout.

### Expected Behavior (Correct)

2.1 WHEN `scripts/import_plan.py --input-jsonpath <path>` is invoked
against a JSON file that is the real AMQ export shape (top-level
object with a `songs` array, each entry carrying its data under a
nested `songInfo` sub-object) THEN the system SHALL accept the file,
run it through the AMQ-to-flat preprocessing stage, and classify
every song into the `resolved` / `auto_completable` / `ambiguous`
buckets — producing the same kind of plan the flat-array surface
produces today on the equivalent flattened input.

2.2 WHEN the preprocessor resolves the `artist_name` flat field for a
real AMQ song THEN the system SHALL read it from
`songs[i].songInfo.artist`.

2.3 WHEN the preprocessor resolves the `song_name` flat field for a
real AMQ song THEN the system SHALL read it from
`songs[i].songInfo.songName`.

2.4 WHEN the preprocessor resolves the `show_name` flat field for a
real AMQ song AND `songs[i].songInfo.animeNames.english` is a
non-empty string THEN the system SHALL use that value as the
`show_name`.

2.5 WHEN the preprocessor resolves the `show_name` flat field for a
real AMQ song AND `songs[i].songInfo.animeNames.english` is missing
or empty AND `songs[i].songInfo.animeNames.romaji` is a non-empty
string THEN the system SHALL use the romaji value as the `show_name`
(English wins over romaji when both are present, mirroring the
existing English-over-romaji precedence).

2.6 WHEN the preprocessor resolves the `vintage` flat field for a
real AMQ song THEN the system SHALL read it from
`songs[i].songInfo.vintage`.

2.7 WHEN the preprocessor resolves the `media_url` flat field for a
real AMQ song AND `songs[i].videoUrl` is a non-empty string THEN the
system SHALL use that value as the `media_url`. `media_url` SHALL
remain optional: if no media candidate resolves, it SHALL default to
the empty string, matching today's behavior.

2.8 WHEN a real AMQ song object carries any field outside the five
the preprocessor consumes — including per-song game-state fields
(`songNumber`, `correctGuess`, `videoLength`, `type`, `typeNumber`,
`annId`, `fromList`, `startSample`), the `composerInfo` /
`arrangerInfo` subtrees, the `altAnimeNames` / `altAnimeNamesRomaji`
arrays, any other `songInfo` children the preprocessor does not read,
or any top-level sibling of `songs` (e.g. `roomName`, `startTime`) —
THEN the system SHALL silently drop every such field, exactly as the
preprocessor drops extras today. The deeper nesting does not change
the drop-on-the-floor principle; only the five keys the preprocessor
consumes move nesting levels.

2.9 WHEN a required field (any of `artist_name`, `song_name`,
`show_name`, `vintage`) cannot be resolved for a song at index `i`
under the real AMQ shape THEN the system SHALL abort the whole file
with `INVALID_INPUT` and exit code 1, with the error `details`
carrying the index and the name of the missing flat field, matching
the existing strictness contract. A missing nested container
(e.g. `songs[i].songInfo` is absent, or `songs[i].songInfo.animeNames`
is absent when needed) SHALL be treated the same way as a missing
leaf value — the file is rejected with `INVALID_INPUT`, not
silently defaulted.

2.10 WHEN the test suite runs after this fix lands THEN the system
SHALL include at least one integration test that reads a committed
copy of the real AMQ export JSON file from the repository (placed
under `tests/fixtures/` or an equivalent path — the exact location is
a design decision) and drives it through
`scripts/import_plan.py --input-jsonpath` end-to-end, asserting that
the run exits 0 and produces a plan whose three buckets (`resolved`,
`auto_completable`, `ambiguous`) sum to the number of songs in the
fixture file, with no INVALID_INPUT envelope.

2.11 WHEN the existing AMQ-shaped tests under `tests/unit/` and
`tests/integration/` run after the fix lands THEN the system SHALL
express their AMQ-wrapper payloads in the real nested shape
(`songInfo` with nested `animeNames`, plus top-level `videoUrl` on
each song) rather than the v0.1.1 guessed flat shape, so every
AMQ-shaped test in the repo asserts against reality rather than
against a self-consistent fiction. Structural contracts the existing
tests already check — required-field-missing raises `INVALID_INPUT`,
extras are silently dropped, the preprocessor outputs the five-field
flat shape in a stable key order, raw AMQ via `--input-jsonpath` /
`--input-jsonstr` produces byte-equal plans to the legacy flat surface
on the equivalent flat payload, `--input-array` rejects nested AMQ
with `INVALID_INPUT` — SHALL CONTINUE TO hold; only the wrapper shape
the tests encode changes.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `scripts/import_plan.py` is invoked via the legacy
`--input <path>` flag or the positional path equivalent AND the file
is the flat five-field JSON array shape
(`[{artist_name, song_name, show_name, vintage, media_url}, ...]`)
THEN the system SHALL CONTINUE TO accept it and produce the same
plan it produces today — same `resolved` / `auto_completable` /
`ambiguous` bucketing, same URL-decoding, same
`SONG_INVARIANT_VIOLATION` handling. The legacy surface does not
touch the preprocessor and is out of scope for this fix.

3.2 WHEN `scripts/import_plan.py` is invoked via `--input-jsonpath`,
`--input-jsonstr`, or `--input-array` AND the payload is the flat
five-field array shape THEN the system SHALL CONTINUE TO accept it
and produce the same plan the legacy `--input` surface produces
today on the same content. The three new flags already route flat
payloads around the preprocessor; this fix does not change that
path.

3.3 WHEN `scripts/import_plan.py` is invoked via `--input-array`
AND the payload is any nested AMQ object shape (the v0.1.1 guessed
flat-per-song shape or the real nested `songInfo` shape) THEN the
system SHALL CONTINUE TO abort with `INVALID_INPUT` and exit code 1.
`--input-array` remains the flat-only channel; it SHALL NOT silently
accept any nested AMQ object shape.

3.4 WHEN `scripts/import_plan.py` runs successfully on any input
shape THEN the system SHALL CONTINUE TO be read-only: the SQLite file
at `db/datasource.db` is byte-identical before and after every run.

3.5 WHEN `scripts/import_plan.py` classifies entries — regardless of
which input channel or which payload shape arrived — THEN the system
SHALL CONTINUE TO URL-decode every string field of every flattened
entry before any DB lookup, honor `SONG_INVARIANT_VIOLATION` when one
artist owns two live songs with the same name, and carry `media_url`
and the resolved `show_id` / `show_to_create` block through to the
plan exactly as it does today.

3.6 WHEN the three-step pipeline
(`import_plan.py` → `import_resolve.py` → `add_play_history.py`) is
invoked THEN the system SHALL CONTINUE TO hand off via the same
`plan.json` / `answers.json` / `triples.json` contract it uses today.
Steps 2 and 3 are not touched by this fix; only step 1's AMQ
preprocessor changes.

3.7 WHEN `scripts/learning.py` is invoked for any purpose
(`graduate`, `levelup`, `list-learning`, etc.) THEN the system SHALL
CONTINUE TO behave exactly as it does today. Bug 2 from the parent
`importer-and-graduate-fixes` spec is not re-addressed here.

3.8 WHEN the skills documentation tree is read — `skills/README.md`
and every `skills/*/SKILL.md` — THEN the system SHALL CONTINUE TO
carry the content each file has today. Bugs 3 and 4 from the parent
spec (the `data.py` preference guidance in `skills/README.md` and the
combined-search examples in `skills/searching-library/SKILL.md`) are
not re-addressed here. The one documentation touch permitted in scope
is an update to `skills/importing-amq-songs/references/plan-shape.md`
to reflect the real field mapping, since the current table in that
file encodes the v0.1.1 guessed mapping and would otherwise contradict
the fixed code.

3.9 WHEN a non-AMQ input is passed through any channel — a JSON
scalar, a JSON object without a `songs` array, a non-parseable JSON
file, or a missing file — THEN the system SHALL CONTINUE TO abort
with `INVALID_INPUT` and exit code 1, without writing anything.

3.10 WHEN the existing unit tests in
`tests/unit/test_importer_preprocessing.py` and the integration tests
in `tests/integration/test_import_plan.py` and
`tests/integration/property/test_importer_input_channels_property.py`
are updated to express their AMQ wrappers in the real nested shape
THEN the structural assertions they already make SHALL CONTINUE TO
hold: the preprocessor still outputs the five flat keys in a stable
order, still raises `INVALID_INPUT` on a missing required field,
still drops extras silently, and still produces byte-equal plans
across the four input channels on equivalent flat payloads. Only the
wrapper shape the tests build changes; the contracts they assert do
not.

3.11 WHEN a new integration test lands that reads a committed copy of
the real AMQ export JSON file THEN the system SHALL CONTINUE TO leave
that committed fixture in its original, unmodified form in the
repository. The fixture is a read-only reference input to the test;
no test is permitted to mutate it in place.

## Deriving the Bug Condition

This spec covers one defect: the preprocessor rejects the real AMQ
export shape because its field mapping table was guessed instead of
verified. One bug condition, one fix-checking property, one
preservation goal.

### Bug Condition

```pascal
FUNCTION isBugConditionRealAmqShape(X)
  INPUT: X of type ImportPlanInvocation
          (an argv + parsed-payload pair representing a call to
           import_plan.py via --input-jsonpath or --input-jsonstr;
           --input-array is out of scope — it is flat-only by
           contract and never runs the preprocessor)
  OUTPUT: boolean

  // The bug is triggered whenever the parsed payload is the real
  // AMQ export shape: a JSON object with a top-level `songs` array
  // whose entries expose their data under a `songInfo` sub-object
  // (and, for the show names, a further `songInfo.animeNames`
  // sub-object), with the media URL as a top-level `videoUrl` on
  // the song.
  RETURN isRealAmqShape(X.payload)
END FUNCTION
```

Where `isRealAmqShape(payload)` is true iff `payload` is a JSON
object, `payload["songs"]` is a list, and for at least one entry
`s` in that list, `s["songInfo"]` is an object (the distinguishing
marker — the v0.1.1 guessed shape has no `songInfo` level at all).

### Property (Fix Checking)

```pascal
// For every invocation whose payload is the real AMQ export shape,
// the fixed preprocessor resolves the five flat fields from the
// correct nested paths (artist from songInfo.artist, song from
// songInfo.songName, show from songInfo.animeNames.english falling
// back to songInfo.animeNames.romaji, vintage from songInfo.vintage,
// media_url from the top-level videoUrl), produces a valid flat
// entry list, and drives that list through the classifier to a
// plan — exit code 0, no INVALID_INPUT envelope, every required
// flat field populated from the right place.
FOR ALL X WHERE isBugConditionRealAmqShape(X) DO
  result ← importPlan'(X)

  ASSERT result.exitCode = 0
  ASSERT result.error    = null

  flattened ← toFlatFiveField'(X.payload)
        // preprocessing output; one dict per `songs[i]` with the
        // five flat keys in the declared order.

  FOR ALL i, entry IN enumerate(flattened) DO
    ASSERT entry.artist_name = X.payload.songs[i].songInfo.artist
    ASSERT entry.song_name   = X.payload.songs[i].songInfo.songName

    english ← X.payload.songs[i].songInfo.animeNames.english
    romaji  ← X.payload.songs[i].songInfo.animeNames.romaji
    IF english ≠ "" AND english ≠ null THEN
      ASSERT entry.show_name = english
    ELSE
      ASSERT entry.show_name = romaji
    END IF

    ASSERT entry.vintage = X.payload.songs[i].songInfo.vintage

    videoUrl ← X.payload.songs[i].videoUrl
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

### Preservation Goal

```pascal
// For every invocation NOT meeting the bug condition — flat-array
// payloads through any channel, non-AMQ garbage through any channel,
// and every legacy --input / positional path call — the fixed
// preprocessor behaves identically to the v0.1.1 code: same exit
// code, same stdout envelope, same stderr envelope, same plan bytes.
FOR ALL X WHERE NOT isBugConditionRealAmqShape(X) DO
  ASSERT importPlan(X) = importPlan'(X)
END FOR
```

**Key Definitions:**

- **F (`importPlan`)**: `scripts/import_plan.py` as it exists on
  `mainline` after v0.1.1 shipped — the preprocessor's
  `_AMQ_FIELD_MAP` reads `songArtist` / `songName` /
  `animeEnglishName` / `animeRomajiName` / `vintage` / `audio` at
  the top level of each song object.
- **F' (`importPlan'`)**: `scripts/import_plan.py` after this fix —
  the preprocessor's field mapping resolves from the real nested
  paths: `songInfo.artist`, `songInfo.songName`,
  `songInfo.animeNames.english` / `songInfo.animeNames.romaji`,
  `songInfo.vintage`, and top-level `videoUrl` on the song.
- **Real AMQ export shape**: a JSON object with a top-level `songs`
  array, whose entries carry their song data under a `songInfo`
  sub-object (and their show names under
  `songInfo.animeNames.{english,romaji}`), with the media URL as a
  top-level `videoUrl` on the song. Per-song siblings of `songInfo`
  (e.g. `songNumber`, `correctGuess`, `videoLength`) and top-level
  siblings of `songs` (e.g. `roomName`, `startTime`) are arbitrary
  game-state fields that the preprocessor silently drops.
- **`toFlatFiveField'`**: the fixed preprocessing function
  (`_flatten_amq` composed with `_amq_entry_to_flat`) that converts
  a real AMQ payload to the flat five-field list the classifier
  consumes. Identity on payloads that are already flat arrays.
- **Counterexample (evidence of the bug)**: the committed copy of
  the real AMQ export file (the file the user fetched from
  `docs/design/v1/amq_song_export-small.json` in the parent
  repository). Running `scripts/import_plan.py --input-jsonpath
  <that file>` against the v0.1.1 code exits 1 with
  `INVALID_INPUT` and `details.missing_field = "artist_name"`; the
  same invocation against the fixed code exits 0 and produces a
  valid plan.
