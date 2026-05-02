# Requirements Document

## Introduction

This spec adds a combined-filter song search to `scripts/query.py`. Today
the search surface is three separate ops — `search --kind song`,
`search --kind artist`, `search --kind show` — and each returns a flat
list of one kind of row (see parent `anime-song-learning-app` R5.5–R5.6
and `skills/searching-library/SKILL.md`). Real questions the user asks
mix the three names at once:

- "show me the song with a name like X in a show like Y"
- "songs sung by the artist with name like X"
- "songs in a show with a name like X"
- "all songs in a show like X sung by an artist like Y"

The new op accepts up to three optional name-LIKE filters (song, show,
artist), ANDs any that are provided, and returns one row per matching
song with the related details already attached — the song's artist and
the shows it is linked to — so the caller gets a full, usable answer in
one call instead of having to follow up with a detail op per row.

This feature is additive: it introduces one new `query.py` subcommand
(`search-songs`) and does not change the existing `search`, `*-detail`,
or any other op. It reuses the parent spec's Success_Envelope /
Error_Envelope contract (R3), URL-decoding rules (R4), soft-delete
semantics, and the detail-op shape for related rows (R5.12, R5.14).

Related skill documentation (`skills/searching-library/SKILL.md`) will
be updated as part of this feature's tasks so the new op is documented
alongside the existing ones. That doc update is in scope; the skill
wording itself is out of this requirements doc.

This document reuses (does not re-state) the contracts defined by the
`anime-song-learning-app` spec, in particular:

- R1 (Portable Layout and DB Path) — the new op runs under the same
  `python scripts/query.py ...` entry point, stdlib only, and reads
  the same fixed DB_File.
- R3 (Output Contract) — Success_Envelope on stdout (exit 0),
  Error_Envelope on stderr (exit 1), error codes drawn from the
  approved set.
- R4 (URL Decoding for Input) — every filter flag that takes a name
  string is URL-decoded exactly once before matching, the same way
  `search --term` is today.
- R5.5 / R5.6 (the existing three-kind `search` op) — unchanged. The
  new op does not replace them.
- R5.12 / R5.14 (the `song-detail` and `show-detail` shapes) — the
  shape of `artist` and `shows` attached to each result row in the new
  op follows the same conventions (nested `artist` carries `status`,
  `shows` entries follow the `song-detail` shape including sorted,
  deduplicated `media_urls` sourced from `play_history` only).
- R17 (Level Display) — when a learning record is included for a song,
  `display_level = stored level + 1`.

## Glossary

Terms from the parent `anime-song-learning-app` spec (App_Root, Script,
DB_File, Song, Artist, Show, Rel_Show_Song, Play_History_Entry,
UUID, Soft_Delete, Status_Normal, URL_Decoded_Value, Success_Envelope,
Error_Envelope, Display_Level, now_epoch, Learning_Record, Graduated)
apply here as defined there. The terms below are specific to this spec.

- **Search_Songs_Op**: The new `scripts/query.py search-songs`
  subcommand introduced by this spec. Takes zero or more of
  `--song-term`, `--show-term`, `--artist-term`. Returns a JSON array
  of Song_Search_Result objects.
- **Filter_Term**: One of the three name-LIKE filter flags passed to
  Search_Songs_Op: `--song-term` (matched against `song.name` and
  `song.name_context`), `--show-term` (matched against `show.name` and
  `show.name_romaji`), or `--artist-term` (matched against
  `artist.name` and `artist.name_context`). Each Filter_Term is a
  single string; a caller never passes two values for the same flag.
- **Active_Filter**: A Filter_Term that the caller passed on the CLI
  at all (i.e. the argparse argument is not `None`), regardless of
  the decoded value. Passing `--song-term ""` or `--song-term %20`
  counts as an Active_Filter whose term decodes to empty or to a
  single space, respectively (per parent R4.3 / R4.4), and applies
  that exact matcher; see Empty_Filter_Term below.
- **Inactive_Filter**: A Filter_Term that was not passed on the CLI.
  An Inactive_Filter contributes no clause to the WHERE, does not
  constrain the result set, and is reported as `null` in the
  Search_Envelope's `filters` echo.
- **Empty_Filter_Term**: A Filter_Term whose URL-decoded value is the
  empty string `""`. Matching an Empty_Filter_Term against the
  indicated column set is treated as "matches every row where the
  column set is non-null" — i.e. `LOWER(col) LIKE '%' || LOWER('') ||
  '%'` — and is the same behavior the existing `search --term ""`
  has today. Empty_Filter_Term does not error.
- **Song_Match_Predicate**: A SQL predicate over the `song` table that
  is true iff the URL-decoded `--song-term` value appears as a
  case-insensitive substring of `song.name` or `song.name_context`.
  Built the same way as the existing `search --kind song` matcher
  (parent R5.5).
- **Show_Match_Predicate**: A SQL predicate over the `show` table
  that is true iff the URL-decoded `--show-term` value appears as a
  case-insensitive substring of `show.name` or `show.name_romaji`.
  Same construction as the existing `search --kind show` matcher.
- **Artist_Match_Predicate**: A SQL predicate over the `artist` table
  that is true iff the URL-decoded `--artist-term` value appears as
  a case-insensitive substring of `artist.name` or
  `artist.name_context`. Same construction as the existing
  `search --kind artist` matcher.
- **Combined_Filter**: The conjunction (AND) of every Active_Filter's
  predicate. A song row is in the result set iff, for every
  Active_Filter, the corresponding match predicate is satisfied. The
  combined filter additionally requires `song.status = 0`,
  `artist.status = 0`, and that at least one matching show row
  satisfies `show.status = 0` (when `--show-term` is active). A run
  with zero Active_Filters returns every live song (see
  Zero_Filter_Behavior).
- **Zero_Filter_Behavior**: The defined behavior when the caller
  invokes Search_Songs_Op with no Active_Filters — the op returns
  every Song_Search_Result for which `song.status = 0` and
  `artist.status = 0`, matching the same envelope shape as a filtered
  run. This is useful as a "list everything" call; it is not an
  error.
- **Song_Search_Result**: One entry in the Search_Songs_Op result
  array. Represents exactly one live song and carries all the
  related rows needed to make the result immediately usable without a
  follow-up detail op. The exact shape is pinned in R-SE-3.
- **Show_Filter_Match_Flag**: A boolean field on each Show_Entry
  inside a Song_Search_Result indicating whether that specific show
  satisfied the `--show-term` predicate. Always present; when
  `--show-term` is an Inactive_Filter, every Show_Entry has
  `matched_filter = true` (the filter is vacuously satisfied).
- **Show_Entry**: One element of the `shows` array on a
  Song_Search_Result. Follows the same shape as `shows` entries in
  the parent `song-detail` op (R5.12) — `{id, name, name_romaji,
  vintage, s_type, media_urls}` — and adds one field,
  `matched_filter`, per the Show_Filter_Match_Flag definition.
- **Search_Envelope**: The full Success_Envelope body that
  Search_Songs_Op writes to stdout. Not just the result array — it
  also echoes the filters that were applied, the count, and any
  defaulting decisions, so callers can audit "what was this result
  actually filtered on". Exact shape is pinned in R-SE-4.

## Requirements

### Requirement R-SE-1: New `search-songs` Subcommand on `query.py`

**User Story:** As the user, I want one command that combines song,
show, and artist name filters and returns the matching songs with
their related details, so I can answer "songs in show X by artist Y"
without stitching together several `search` and `*-detail` calls.

#### Acceptance Criteria

1. THE `scripts/query.py` Script SHALL expose an `argparse` subcommand
   named `search-songs` alongside the existing subcommands listed by
   parent R5. The subcommand SHALL accept three optional flags:
   `--song-term STR`, `--show-term STR`, `--artist-term STR`. It
   SHALL accept no positional arguments.
2. THE `search-songs` subcommand SHALL be addable to the script
   without renaming, removing, or altering any existing subcommand
   (`get`, `batch-get`, `search`, `duplicates`, `shows-by-artist-ids`,
   `songs-by-artist-ids`, `list-learning`, `song-detail`,
   `artist-detail`, `show-detail`, `learning-detail`). The surface of
   those ops SHALL remain identical to parent R5.
3. WHEN `search-songs` is invoked with zero Active_Filters (no
   `--song-term`, no `--show-term`, no `--artist-term`), THE Script
   SHALL apply Zero_Filter_Behavior — return every live song with
   its related details — and exit 0.
4. WHEN `search-songs` is invoked with one, two, or three
   Active_Filters, THE Script SHALL apply Combined_Filter (AND over
   the active predicates) and exit 0.
5. WHEN any Filter_Term is passed on the CLI, THE Script SHALL
   URL-decode its value exactly once using `urllib.parse.unquote`
   (the same helper parent R4 mandates) before building the match
   predicate. An Empty_Filter_Term (decoded value `""`) SHALL NOT
   produce an error; it SHALL be applied as a literal empty
   substring match, matching every row in the indicated column set.
6. WHERE a Filter_Term flag is present on the command line with a
   value that decodes to a string longer than 1024 UTF-8 bytes, THE
   Script SHALL print an Error_Envelope with `code = "INVALID_INPUT"`
   and exit 1 without scanning the DB. (The cap is documented so
   callers know a predictable, finite SQL parameter is bound.)
7. IF the caller passes the same filter flag more than once (for
   example, `--song-term a --song-term b`), THE behavior SHALL be
   whatever `argparse` does by default for a non-`append` flag —
   the last value wins. THE subcommand SHALL NOT declare any filter
   flag as `action="append"`, so the CLI surface stays
   one-value-per-flag.
8. IF the caller passes any flag or positional argument not in the
   set `{--song-term, --show-term, --artist-term, -h, --help}`, THE
   Script SHALL reject the invocation with argparse's usual
   SystemExit(2) path (argparse error), matching the behavior of
   every other `query.py` subcommand when given an unknown flag.

### Requirement R-SE-2: Filter Semantics and Match Predicates

**User Story:** As the user, I want filter matching to behave like the
existing `search` op so I do not have to learn two different sets of
rules.

#### Acceptance Criteria

1. THE `--song-term` filter SHALL use the Song_Match_Predicate. The
   predicate SHALL match a song row `S` iff the decoded term appears
   as a case-insensitive substring in `S.name` OR in `S.name_context`.
   This mirrors the `song` entry in `SPECS` in `scripts/_common.py`
   whose `searchable_columns` is `("name", "name_context")`.
2. THE `--artist-term` filter SHALL use the Artist_Match_Predicate.
   The predicate SHALL match an artist row `A` iff the decoded term
   appears as a case-insensitive substring in `A.name` OR in
   `A.name_context`. This mirrors the existing `artist`
   `searchable_columns` tuple.
3. THE `--show-term` filter SHALL use the Show_Match_Predicate. The
   predicate SHALL match a show row `SH` iff the decoded term appears
   as a case-insensitive substring in `SH.name` OR in `SH.name_romaji`.
   This mirrors the existing `show` `searchable_columns` tuple.
4. THE three match predicates SHALL NOT consult any column outside
   the tuples listed in R-SE-2.1..3. In particular, `--show-term`
   SHALL NOT match against `show.vintage` or `show.s_type`.
5. THE Combined_Filter SHALL exclude any song row where
   `song.status = 1`. Soft-deleted songs SHALL NOT appear in any
   Song_Search_Result.
6. THE Combined_Filter SHALL exclude any song row whose referenced
   `artist` has `status = 1`. A live song dangling off a
   soft-deleted artist SHALL NOT appear in the result. (Consistent
   with parent R5.10 `songs-by-artist-ids` behavior.)
7. WHEN `--show-term` is an Active_Filter, THE Combined_Filter SHALL
   require that the song has at least one `rel_show_song` link to a
   `show` row where `show.status = 0` AND the Show_Match_Predicate
   is satisfied. A song linked only to soft-deleted or
   non-matching shows SHALL NOT appear in the result even if the
   other filters match.
8. WHEN `--show-term` is an Inactive_Filter, THE Combined_Filter
   SHALL NOT require that the song have any linked show; a live
   song with zero `rel_show_song` rows and no show constraint SHALL
   still appear in the result (with an empty `shows` array per
   R-SE-3.5).
9. Filter matching SHALL be case-insensitive in the SQL layer using
   the same `LOWER(col) LIKE '%' || LOWER(?) || '%'` pattern as
   `scripts/_common.py :: search_rows`. Callers SHALL NOT need to
   pre-fold or pre-escape case.
10. Filter matching SHALL treat the SQL `LIKE` wildcard characters
    `%` and `_` as literal characters. That is, the binding path
    SHALL pass the decoded term as a parameter to SQLite (not
    concatenated into the SQL string) so a `%` in the term means
    "literal percent", not "match-any-run". This matches the
    existing `search_rows` behavior — no special `ESCAPE` clause is
    introduced by this spec. If this later turns out to be a
    problem in practice, the parent-spec's `search` op has the same
    behavior and any fix applies uniformly.

### Requirement R-SE-3: Result Shape — Song_Search_Result

**User Story:** As the user, I want each matching song to come back
with the details I would otherwise have to fetch via a follow-up
`song-detail` call — its artist and every show it appears in —
including the play-history media URLs, so I can skim the list and act
on it without further queries.

#### Acceptance Criteria

1. THE Search_Songs_Op SHALL return exactly one Song_Search_Result
   entry per distinct live song that satisfies the Combined_Filter.
   A song linked to multiple matching shows SHALL still appear
   once; its Show_Entry list carries the multiplicity.
2. Each Song_Search_Result SHALL be a JSON object with these
   top-level keys, in this order:
   - `song`: the full `song` row as returned by `SELECT * FROM song`,
     with every column the schema defines (`id`, `name`,
     `name_context`, `artist_id`, `created_at`, `updated_at`,
     `status`). `status` is always `0` here, by R-SE-2.5.
   - `artist`: the artist row that owns this song, with
     `{id, name, name_context, status}`. Under normal operation the
     artist has `status = 0`; by R-SE-2.6 any other value cannot
     reach this result, but the field is emitted to mirror parent
     `song-detail` so callers can reuse the same parsing code.
   - `shows`: an array of Show_Entry objects, one per live show
     linked to this song via `rel_show_song`, ordered by `show.name
     ASC`, then `show.id ASC`. See R-SE-3.4 / R-SE-3.5.
   - `learning`: either `null` or a Learning_Summary object for the
     song's active (un-graduated) learning row. See R-SE-3.6.
   - `graduated`: a boolean. `true` iff at least one learning row
     for this song has `graduated = 1`. See R-SE-3.11.
   - `warnings`: an array of Warning objects. Empty array `[]` when
     the song has no data glitches; populated when, for example, the
     song has more than one active learning row. Always present.
     See R-SE-3.12.
3. THE Song_Search_Result's `song` field SHALL include every column
   SELECTed by `SELECT * FROM song`. Callers SHALL NOT need to look
   up the schema to know what columns are present — they come back
   verbatim. The op SHALL NOT filter, rename, or coerce any column.
4. Each Show_Entry SHALL be a JSON object with these keys:
   - `id`, `name`, `name_romaji`, `vintage`, `s_type`: mirroring the
     parent `song-detail` `shows` entries (R5.12).
   - `media_urls`: the sorted, deduplicated list of non-empty
     `play_history.media_url` strings for the `(show.id, song.id)`
     pair with `play_history.status = 0`, computed the same way
     parent R5.16 defines it. Empty-string `media_url` values SHALL
     be excluded. `media_urls` SHALL be sorted lexicographically.
   - `matched_filter`: a boolean, per Show_Filter_Match_Flag. WHEN
     `--show-term` is an Inactive_Filter, every Show_Entry SHALL
     have `matched_filter = true`. WHEN `--show-term` is an
     Active_Filter, `matched_filter = true` iff the show row
     satisfies the Show_Match_Predicate AND has `status = 0`, and
     `matched_filter = false` otherwise.
5. THE `shows` array SHALL include every live show (`show.status =
   0`) the song is linked to via `rel_show_song`, not just the
   shows that matched `--show-term`. Callers who want only
   matching shows can filter on `matched_filter = true`
   client-side. Rationale: the user's ask is for "songs in show X
   sung by artist Y — with related details of each song"; the
   related details are "all shows for this song", which is what
   `song-detail` already returns. Clamping the list to only
   matching shows would hide context the user asked for.
6. THE Song_Search_Result's `learning` field SHALL be either
   `null` (no active learning row exists for this song) or a
   Learning_Summary object with the keys
   `{id, level, display_level, graduated, last_level_up_at,
   updated_at}` taken from the song's **active (un-graduated)**
   learning row — the row where `learning.graduated = 0`. WHEN the
   song has no active learning row (every learning row has
   `graduated = 1`, or the song has no learning rows at all),
   `learning` SHALL be `null`. WHEN the song has two or more
   active learning rows (a data glitch — parent R6 is designed to
   maintain at most one un-graduated row per song), the
   Learning_Summary SHALL be taken from the active row with the
   highest `updated_at`; ties break by `id ASC`. The op SHALL
   surface every such duplicate as a `duplicate_active_learning`
   warning on the Song_Search_Result's `warnings` array (see
   R-SE-3.12) rather than erroring out; the Search_Songs_Op SHALL
   still exit 0 and return the full result set. The `graduated`
   key on the embedded summary SHALL always be `0` by construction
   and is kept for parsing parity with `song-detail` /
   `learning-detail`. Rationale: the user asked "show related
   details of each song", and the caller's current practice state
   — the active row — is the one relevant piece of learning info
   for the list view; whether the song has been fully graduated is
   a separate bit, exposed on the sibling `graduated` field
   (R-SE-3.11).
7. THE `display_level` field in Learning_Summary SHALL equal
   `int(stored level) + 1`, per parent R17.
8. THE `media_urls` on each Show_Entry SHALL be sourced from
   `play_history` only (not `rel_show_song.media_url`). THE op
   SHALL apply the same sort-and-dedupe rules parent R5.16 defines.
9. WHEN zero songs match the Combined_Filter, THE Search_Songs_Op
   SHALL exit 0 and emit a Search_Envelope whose `results` array
   is empty `[]`. THE op SHALL NOT return a `NOT_FOUND`
   Error_Envelope. (Zero matches is a successful query with no
   hits, not an error — same pattern parent R5.4 sets for
   `batch-get`.)
10. THE Search_Songs_Op SHALL return results in a stable order:
    `song.name ASC`, then `song.id ASC`. This matches the ordering
    parent R5.11 mandates for list results and R5.14 uses for
    `show-detail`'s nested songs.
11. THE Song_Search_Result's `graduated` field SHALL be a JSON
    boolean. It SHALL be `true` iff the song has at least one
    learning row with `graduated = 1`, and `false` otherwise. The
    presence or absence of an active (un-graduated) learning row
    SHALL NOT affect this value — a song MAY have `graduated =
    true` and `learning != null` at the same time if it has both
    a graduated row (from a prior run) and a new active row
    (inserted per parent R6.3's re-learn flow). The `graduated`
    field SHALL always be present on every Song_Search_Result,
    never `null` and never omitted.
12. THE Song_Search_Result's `warnings` field SHALL be a JSON
    array of Warning objects. Each Warning object SHALL have
    exactly two keys:
    - `code`: a short machine-readable string drawn from a fixed
      vocabulary. This spec introduces one code:
      `"duplicate_active_learning"`.
    - `message`: a human-readable string describing the glitch
      and suggesting a clean-up action (e.g. pointing at
      `scripts/cleanup.py` or `learning.py graduate`).
    The `warnings` field SHALL always be present on every
    Song_Search_Result. When the song has no glitches, `warnings`
    SHALL be `[]` (empty array, never `null`, never omitted).
    WHEN the song has two or more active learning rows, the
    Search_Songs_Op SHALL emit exactly one Warning with
    `code = "duplicate_active_learning"` on that
    Song_Search_Result. Its `details` (if any future code needs
    structured data, see below) are carried in the `message`
    string; the field set remains `{code, message}` for every
    emitted warning. Warnings are advisory — emitting a Warning
    SHALL NOT change the exit code (still 0), the `count`, the
    `results` order, or the `song`/`artist`/`shows`/`learning`/
    `graduated` fields. Future glitches MAY introduce new `code`
    values; existing codes SHALL NOT be renamed or removed.

### Requirement R-SE-4: Output Envelope and Filter Echo

**User Story:** As the user, I want the op's output to restate the
filters it applied, so when I skim the JSON I can see at a glance
whether the result set reflects the query I thought I wrote.

#### Acceptance Criteria

1. THE Search_Songs_Op Success_Envelope SHALL be a single JSON
   object (not a bare array). The top-level shape SHALL be:
   ```
   {
     "filters": {
       "song_term":   <string | null>,
       "show_term":   <string | null>,
       "artist_term": <string | null>
     },
     "count": <non-negative integer>,
     "results": [ Song_Search_Result, ... ]
   }
   ```
   Key order in the envelope SHALL be `filters`, `count`, `results`
   so downstream `jq`-style consumers can rely on a predictable
   layout.
2. FOR each of `song_term`, `show_term`, `artist_term` in the
   `filters` object: the value SHALL be the URL-decoded string
   actually passed by the caller when that flag is an
   Active_Filter, or JSON `null` when it is an Inactive_Filter.
   THE envelope SHALL NOT omit any of the three keys.
3. `count` SHALL equal `len(results)`. Callers SHALL NOT have to
   parse the array to know how many hits the op returned.
4. WHEN Zero_Filter_Behavior applies (no Active_Filters), THE
   envelope's `filters` SHALL be `{"song_term": null,
   "show_term": null, "artist_term": null}` and `results` SHALL be
   every live song under a live artist, in the R-SE-3.10 order.
5. THE Search_Envelope SHALL be written to stdout exactly once per
   successful invocation, as a single JSON document followed by
   one trailing newline, matching the stdout conventions of every
   other `query.py` op (parent R3.1, R3.4).
6. ON handled failure (unknown flag, over-length term, internal DB
   error), THE Script SHALL follow parent R3.2 / R3.7 — write an
   Error_Envelope to stderr and exit 1. It SHALL NOT write a
   partial or empty Search_Envelope on stdout.
7. THE Search_Envelope's `results` array entries SHALL be ordered
   per R-SE-3.10. Re-running the same filter set against an
   unchanged DB SHALL produce byte-identical stdout (so tests and
   external callers can diff output runs).

### Requirement R-SE-5: Skill Documentation Update

**User Story:** As an operator (or an LLM working from the shipped
skill docs), I want the new `search-songs` op to be documented in
`skills/searching-library/SKILL.md`, so the search workflow guide
reflects what the library actually supports.

#### Acceptance Criteria

1. THE file `skills/searching-library/SKILL.md` SHALL be updated to
   list `search-songs` alongside the existing `search`,
   `duplicates`, and detail ops. The description SHALL call out
   that `search-songs` is the right op when the user combines two
   or more of song / show / artist name filters, or asks for songs
   "in show X by artist Y" in one go.
2. THE SKILL.md update SHALL document the three filter flags
   (`--song-term`, `--show-term`, `--artist-term`), the
   ANDing rule, the Zero_Filter_Behavior ("no flags returns every
   live song with related details"), and the Search_Envelope
   shape at a level of detail consistent with the rest of the
   file — enough that a reader can write a working invocation
   without reading the requirements doc.
3. THE SKILL.md update SHALL NOT remove or alter the existing
   guidance for `search`, `*-detail`, or any other op. It SHALL
   add `search-songs` as a new bullet in the "available ops"
   checklist, not replace the existing bullets.
4. THE SKILL.md update SHALL be shipped in the same change that
   introduces `search-songs`. THE feature is not considered
   delivered with R-SE-1..R-SE-4 in place but the skill doc still
   listing only the old search op.

## Correctness Properties for Property-Based Testing

These properties extend the parent `anime-song-learning-app` spec's
"Correctness Properties" rules: temp `App_Root` per test, stdlib
`random.Random(seed)` with a fixed seed (no `hypothesis`, per
parent R18), and integration tests drive scripts via
`subprocess.run`. Each property below is testable on top of the
existing `tests/integration/conftest.py` seeders (`insert_artist`,
`insert_song`, `insert_show`, `insert_rel`, `insert_play_history`)
without new infrastructure.

### Property P-SE-1: Active Filter Subset Is Monotone (Metamorphic)

For any seeded random DB and any two sets of Active_Filters `F ⊆ G`
(i.e. `G` adds one or more filters on top of `F`, with new
Filter_Terms independent of the DB state):

1. `results(G) ⊆ results(F)` as a set of song `id` values. Adding
   a filter SHALL never grow the result set.
2. For every song `id` that appears in both `results(F)` and
   `results(G)`, the `song` row, `artist` object, and the ordered
   `shows` list (comparing `id` and `matched_filter` pairs) SHALL
   be identical across the two runs. Adding a filter does not
   rewrite the per-song payload, only narrows which songs come
   back.

Rationale: tests the AND semantics directly. This is a classic
metamorphic property — we do not need to know the true answer for
any single filter combination, only that tightening constraints
never expands results.

### Property P-SE-2: Empty-Filter Equivalence

For any seeded random DB:

1. `results(no Active_Filters)` as a list SHALL equal
   `results(--song-term "")` as a list (same order, same elements,
   same per-song payload). The decoded empty string behaves as a
   vacuous match against the song column set, so the `song.status
   = 0` AND `artist.status = 0` conditions alone decide membership.
2. Similarly, `results(no Active_Filters)` SHALL equal
   `results(--artist-term "")` as a list. Tests MAY omit the
   `--show-term ""` case because an Active show-term requires at
   least one linked show (R-SE-2.7), which differs from the
   no-show-filter vacuous case; that difference is by design and
   covered by P-SE-3.
3. Decoded forms SHALL be respected: `results(--song-term %20%20)`
   (two URL-encoded spaces, decoded to `"  "`) SHALL equal the
   set of songs whose `name` or `name_context`, lower-cased,
   contains two consecutive spaces.

### Property P-SE-3: Show-Filter Requires A Matching Link

For any seeded random DB, any song `S` whose linked shows are
`SH_1..SH_k`, and any `--show-term T`:

1. `S.id ∈ results({--show-term: T})` iff there exists at least
   one `SH_i` with `SH_i.status = 0` and `SH_i` satisfies
   Show_Match_Predicate(T). This matches R-SE-2.7 and rules out
   songs with only soft-deleted or non-matching shows.
2. For every `S` in `results({--show-term: T})`, the `shows`
   array in its Song_Search_Result SHALL still list every live
   show linked to `S` — including ones that did not match `T` —
   and each Show_Entry's `matched_filter` field SHALL be `true`
   iff that specific show row satisfied Show_Match_Predicate(T).
   At least one Show_Entry in the array SHALL have
   `matched_filter = true` (from point 1).
3. For every `S` in `results(no Active_Filters)` that has at least
   one live show, every Show_Entry SHALL have `matched_filter =
   true` (Inactive_Filter → vacuously satisfied).

### Property P-SE-4: Soft-Delete Filtering (Invariant)

For any seeded random DB and any filter set `F`:

1. No Song_Search_Result in `results(F)` SHALL have `song.status =
   1`. Soft-deleted songs never surface.
2. No Song_Search_Result's `artist` object in `results(F)` SHALL
   have `artist.status = 1`. Songs whose artist is soft-deleted
   never surface (parent R5 songs-by-artist-ids parity).
3. No Show_Entry in any Song_Search_Result SHALL correspond to a
   `show` row with `status = 1`. Soft-deleted shows are excluded
   from the `shows` array outright, regardless of whether
   `--show-term` is active.
4. Flipping a previously-live song to `status = 1` between two
   otherwise-identical runs SHALL remove exactly that song from
   the `results` array and leave every other Song_Search_Result
   byte-identical across the runs.

### Property P-SE-5: Detail Consistency With `song-detail`

For any seeded random DB and any song `S` appearing in
`results(no Active_Filters)`:

1. The `song` row in `S`'s Song_Search_Result SHALL deep-equal
   the `song` field returned by `python scripts/query.py
   song-detail --id S.id`.
2. The `artist` object in `S`'s Song_Search_Result SHALL
   deep-equal the `artist` field returned by
   `song-detail --id S.id`.
3. The `shows` array in `S`'s Song_Search_Result, after dropping
   the `matched_filter` key from each Show_Entry, SHALL equal
   (order-preserving) the `shows` array returned by
   `song-detail --id S.id` — same entries, same per-entry keys,
   same `media_urls` (sorted, deduped, play-history-only per
   parent R5.16).

Rationale: the new op is purposely a multi-song version of
`song-detail` plus a filter. Pinning deep equality keeps the two
ops from drifting apart — if `song-detail` changes, `search-songs`
rides along for free.

### Property P-SE-6: Stable Ordering (Round-Trip-ish)

For any seeded random DB and any filter set `F`:

1. Running Search_Songs_Op twice in a row with `F` against the
   same DB SHALL produce byte-identical stdout (per R-SE-4.7).
2. For any two songs `S_a`, `S_b` in `results(F)`, `S_a` precedes
   `S_b` in the array iff `(S_a.song.name, S_a.song.id) <
   (S_b.song.name, S_b.song.id)` under Python's default string
   ordering. No other tie-break.
3. For any Song_Search_Result, the `shows` array SHALL be
   ordered by `(show.name ASC, show.id ASC)`. Any two Show_Entries
   with the same `show.name` SHALL come back in `show.id`
   ascending order.

### Property P-SE-7: Envelope Invariants

For any seeded random DB and any filter set `F`:

1. The Success_Envelope SHALL always have exactly the three
   top-level keys `filters`, `count`, `results`, in that order.
2. `envelope.filters` SHALL always have exactly the three keys
   `song_term`, `show_term`, `artist_term`. Each value is either
   a string (matching the decoded term the caller passed for an
   Active_Filter) or JSON `null` (for an Inactive_Filter).
3. `envelope.count == len(envelope.results)`, for every run.
4. For every Song_Search_Result `R`, the key set of `R` SHALL be
   exactly `{"song", "artist", "shows", "learning", "graduated",
   "warnings"}` and the key set of each Show_Entry SHALL be
   exactly `{"id", "name", "name_romaji", "vintage", "s_type",
   "media_urls", "matched_filter"}`. No extra keys, no missing
   keys. The `graduated` field SHALL always be a JSON boolean
   (never `null`, never omitted). The `warnings` field SHALL
   always be a JSON array (possibly empty, never `null`, never
   omitted), and each entry SHALL have exactly the key set
   `{"code", "message"}`.

### Property P-SE-8: Graduated Flag And Active Learning Summary

For any seeded random DB and any song `S` that appears in
`results(no Active_Filters)`:

1. `S.graduated == true` iff there exists at least one learning
   row with `song_id = S.song.id` and `graduated = 1`.
2. `S.learning` is non-null iff there exists at least one learning
   row with `song_id = S.song.id` and `graduated = 0`. When
   non-null, `S.learning.graduated == 0`.
3. When `S.learning` is non-null and the song has multiple
   un-graduated learning rows, `S.learning.id` equals the id of
   the un-graduated row with the highest `updated_at` (tie-break
   `id ASC`).
4. `S.graduated` and (`S.learning != null`) are independent: a
   song MAY have both `S.graduated == true` and `S.learning !=
   null` (the re-learn flow from parent R6.3), and a song with no
   learning rows at all SHALL have `S.graduated == false` and
   `S.learning == null`.
5. `S.graduated` is always a JSON boolean — never `null`, never
   `0` or `1`, never omitted — regardless of whether the song has
   any learning rows.

### Property P-SE-9: Duplicate-Active-Learning Warning

For any seeded random DB and any song `S` in `results(F)` (any
filter set `F`):

1. `S.warnings` contains a Warning with
   `code = "duplicate_active_learning"` iff the song has two or
   more learning rows with `graduated = 0`. In all other cases
   that code SHALL NOT appear in `S.warnings`.
2. At most one `duplicate_active_learning` Warning SHALL be
   emitted per Song_Search_Result, regardless of how many extra
   active rows exist.
3. Emitting a `duplicate_active_learning` Warning SHALL NOT
   change the exit code (still 0), the envelope `count`, the
   `results` ordering, or the `song`, `artist`, `shows`,
   `learning`, or `graduated` fields of that (or any other)
   Song_Search_Result — measured by running the op twice, once
   on a DB with a duplicate-active-row glitch and once on the
   same DB with the extra row removed, and asserting every other
   field is byte-identical for the shared songs.
4. `S.warnings` is always an array — empty `[]` when the song has
   no glitches, never `null`, never omitted.

### Note on Non-Property Tests

Per the workflow's "When NOT to Use Property-Based Testing"
guidance, the following are covered by small, example-style
integration tests rather than property tests:

- Over-length term rejected with `INVALID_INPUT` exit 1 (R-SE-1.6)
  — single representative string longer than 1024 UTF-8 bytes.
- Unknown flag rejected by argparse SystemExit(2) (R-SE-1.8) —
  `--foo bar` reaches the usual argparse error path.
- Empty-result run emits a valid Search_Envelope with
  `count = 0` and `results = []` (R-SE-3.9) — one seeded DB with
  a filter known to match nothing.
- Skill doc update (R-SE-5) — a file-content assertion, not a
  property.

## Out of Scope for This Spec

The following items are explicitly out of scope for
`search-enhancements` and SHALL NOT be introduced as part of
implementing R-SE-1..R-SE-5:

1. A new top-level CLI that wraps `query.py` (the parent R2.3
   prohibition still holds).
2. Filtering by columns outside the three searchable-column
   tuples — `vintage`, `s_type`, `created_at`, `updated_at`, and
   `artist_id` are not filter flags in this spec. Callers who
   need that today can still use `songs-by-artist-ids`.
3. Pagination, `--limit`, or `--offset` flags. The existing
   `search` op has no pagination; this op follows the same
   convention. If the DB grows to a scale where that matters,
   it is a follow-up spec.
4. Regex or glob matching for filter terms. Filtering stays on
   plain case-insensitive substring (`LIKE` with bound
   parameters), same as the existing `search` op.
5. Writing any row (learning state, play history, etc.) from
   within the new op. `search-songs` is read-only — same as every
   other `query.py` subcommand.
6. Changes to `scripts/review.py`, `scripts/learning.py`, or the
   review HTML template. Those ops already have the data they
   need; this feature is purely about the CLI search surface.
7. Exposing a "search everything" op that mixes songs, artists,
   and shows in one result array. This op's result unit is the
   song, not a heterogeneous list.
