# Requirements Document

## Introduction

A small local app that helps one person memorize anime songs using spaced repetition. It reads and writes a single SQLite file that already exists on disk.

The app is a set of Python scripts. Copy the folder (or the packaged zip — see `tools/package.py`) to a machine with Python 3.10+ and run them. No install step, no third-party packages at runtime — only the Python standard library. Tests are a dev-time concern only; they are NOT deployed and NOT expected to run in the target environment.

The app does three kinds of work:

1. **Query** — look up songs, artists, shows, and learning records.
2. **Learning** — add songs to the review queue, mark them as leveled up or done, and make an HTML page listing what's due.
3. **Data management** — edit rows, merge artists, clean up old deleted rows, and import Anime Music Quiz (AMQ) JSON dumps into play history.

All scripts print JSON on success, a JSON error on failure, and use POSIX exit codes (0 or 1).

## Glossary

- **App_Root**: The folder that holds `scripts/` and `db/`.
- **Script**: A Python file under `scripts/`, run directly (e.g. `python scripts/query.py ...`).
- **DB_File**: `App_Root/db/datasource.db`. The one SQLite file the app reads and writes.
- **Song**: A row in `song`. Belongs to one Artist. May appear in any number of Shows.
- **Artist**: A row in `artist`. Two or more artists can share the same `name`; `name_context` is a free-form text field to tell them apart. The app does not assume any format for `name_context`.
- **Show**: A row in `show`. An anime title or season, with a `vintage` (e.g. "Spring 2010") and a type (TV, Movie, etc.).
- **Rel_Show_Song**: A row in `rel_show_song`. Links one show to one song. `UNIQUE(show_id, song_id)`.
- **Learning_Record**: A row in `learning`. Tracks review state for one song: `level` (0–19), `level_up_path` (JSON array of wait-days per level), `last_level_up_at`, and `graduated` (0 or 1). Not soft-deleted, not edited in place. Only `cleanup.py` may hard-delete rows from this table (see Requirement 11).
- **Level_Up_Path**: A JSON array stored in `learning.level_up_path`. Entry `i` is the number of days to wait after reaching stored level `i`. Computed by the easing function below; it is not a fixed table.

  ```
  fibo(0) = 0
  fibo(1) = 1
  fibo(n) = fibo(n - 1) + fibo(n - 2)    for n >= 2

  shrink(n) = (n * 2) // 9               (integer division)

  default_easing(n) =
      let d = shrink(fibo(n + 1)) - shrink(fibo(n))
      in if d == 0 then 1 else d

  level_up_path(max_level) = [ default_easing(0), ..., default_easing(max_level - 1) ]
  ```

  For `max_level = 20` the output is `[1,1,1,1,1,1,1,2,3,5,7,13,19,32,52,84,135,220,355,574]`. New learning records use `max_level = 20`.
- **Max_Level**: The largest valid stored level. Equals `len(level_up_path) - 1`, which is 19 for the default path.
- **Due_SQL_Condition**: The SQL that decides which learning records are ready for review. It is the one source of truth for timing:

  ```sql
  l.graduated = 0
  AND (
      (l.last_level_up_at > 0 AND l.level = 0
       AND (CAST(strftime('%s', 'now') AS INTEGER) + @offset) >= (l.last_level_up_at + 300))
      OR
      (l.last_level_up_at = 0 AND l.level = 0
       AND (CAST(strftime('%s', 'now') AS INTEGER) + @offset) >= (l.updated_at + 300))
      OR
      (l.level > 0
       AND (json_extract(l.level_up_path, '$[' || l.level || ']') * 86400 + l.last_level_up_at)
           <= (CAST(strftime('%s', 'now') AS INTEGER) + @offset))
  )
  ```

  Use the SQL as-is. The notes below are just to explain it:

  - A level-0 record that has been reviewed once is due 5 minutes (300s) after `last_level_up_at`.
  - A brand-new level-0 record (never leveled up) uses `updated_at` as the 5-minute anchor.
  - A record at level 1 or higher is due `level_up_path[level]` days after `last_level_up_at`.
  - `@offset` shifts the comparison time forward by that many seconds. Default is 0, meaning "due now".
- **Graduated**: A learning record with `graduated = 1`. Skipped by `due`. Treated as fully memorized.
- **Re_Learn_Level**: The level to reset to when a graduated song is added back to active learning. Always 7 (displayed level 8).
- **Soft_Delete**: Setting `status = 1`. The row stays in the DB but is hidden from normal queries.
- **Status_Normal**: `status = 0`. Live, visible row.
- **Play_History_Entry**: A row in `play_history`. Records that a song from a show was played. It is an append-only log: duplicates are allowed, no uniqueness, no edits. The only script that may hard-delete these rows is `cleanup.py` (see Requirement 11).
- **AMQ_Import**: The three-step flow for turning an AMQ JSON file into play history rows. Step 1 (plan) reads the DB and sorts entries into three buckets. Step 2 (resolve) creates the artists, songs, and shows that are missing. Step 3 (add play history) writes the play history rows from resolved IDs.
- **Namesake_Disambiguation**: Picking the right artist when two or more artists share a name. Happens only in step 2 of the import, using an answers JSON supplied by the user.
- **Success_Envelope**: Valid JSON printed to stdout on success. Shape depends on the command.
- **Error_Envelope**: JSON printed to stderr on failure. Shape: `{"error": {"code": <string>, "message": <string>, "details": <object|null>}}`.
- **URL_Decoded_Value**: A string run through `urllib.parse.unquote` exactly once. Applied to string values in `--term` and `--data`. Not applied to keys, numbers, booleans, or nulls.
- **Display_Level**: The user-facing level, equal to stored `level + 1`. So stored 0 shows as level 1.
- **UUID**: Whenever the app generates an `id` for a new row, it uses `uuid.uuid4()` (UUID version 4, from the Python standard library) and stores it as its lowercase canonical hyphenated string (e.g. `3b105bd4-c437-4720-a373-660bd5d68532`). Scripts SHALL NOT use any other UUID version.
- **App_Invariant (song names unique per artist)**: For any one artist, no two non-deleted songs share the same name. The DB does not enforce this with a UNIQUE constraint, and the app does not check it on every write. The import pipeline keeps this property in practice because it reuses existing `(song_name, artist_id)` matches instead of inserting new rows. `bulk-reassign` and `merge_artists.py` may break it on purpose during cleanup; the operator (or the merge script) is expected to soft-delete the extras afterward. If a reader runs into two non-deleted songs with the same name under one artist, it must report the situation, not silently pick one.

## Requirements

### Requirement 1: Portable Layout and DB Path

**User Story:** As the user, I want to drop the folder on any machine with Python 3.10+ and run scripts right away, so I don't have to install anything.

#### Acceptance Criteria

1. THE App SHALL consist of Python files under `App_Root/scripts/` and a SQLite file at `App_Root/db/datasource.db`. Runtime SHALL need only Python 3.10+.
2. Every file under `App_Root/scripts/` SHALL import only from the Python standard library. Third-party packages SHALL NOT be imported at runtime.
3. WHEN a Script runs, THE Script SHALL compute `App_Root` from its own file location and open DB_File at `App_Root/db/datasource.db`, regardless of the current working directory.
4. THE App SHALL NOT accept any flag or environment variable that changes the DB path.
5. IF DB_File does not exist, THEN THE Script SHALL print an Error_Envelope with `code = "DB_NOT_FOUND"`, SHALL NOT create the file, and SHALL exit with code 1.
6. THE App SHALL run on Python 3.10, 3.11, 3.12, and 3.13 without code changes. Scripts SHALL NOT use stdlib APIs added after Python 3.10 (for example, `datetime.UTC`, which is a 3.11+ alias — use `datetime.timezone.utc` instead).
7. Running any Script SHALL NOT require a virtual environment, a `pip install` step, or a build step at runtime. The runtime environment (any Python 3.10+ installation, such as a restricted code-execution sandbox) needs nothing beyond the Python standard library. Local development MAY install any dev tooling via `requirements-dev.txt` into a local venv for convenience; THE App SHALL NOT assume those local-dev files exist at runtime.

### Requirement 2: Script Layout

**User Story:** As the user, I want one script per job so each file is small and easy to read.

#### Acceptance Criteria

1. THE App SHALL provide these Scripts under `App_Root/scripts/`, each run with `python scripts/<name>.py`:
   - `query.py` — read-only lookups on songs, artists, shows, and learning records.
   - `learning.py` — write operations for learning records (batch add, levelup, graduate, due, stats).
   - `review.py` — generate the HTML review page.
   - `data.py` — create, update, soft-delete, and bulk-reassign for songs, artists, shows, and rel_show_song.
   - `merge_artists.py` — merge two or more artists into one; handle duplicate songs.
   - `cleanup.py` — hard-delete soft-deleted rows older than a cutoff. Dry-run by default.
   - `import_plan.py` — AMQ import step 1: read the JSON, sort entries into buckets, write a plan.
   - `import_resolve.py` — AMQ import step 2: read the plan and user answers, create missing rows, write triples.
   - `add_play_history.py` — AMQ import step 3 (and also standalone): write play_history and rel_show_song rows from `(song_id, show_id, media_url)` triples.
2. WHERE a Script has multiple operations, THE Script SHALL use `argparse` subcommands.
3. THE App SHALL NOT have a single top-level CLI that wraps all operations.
4. WHEN a Script is called with no arguments or with `--help`, THE Script SHALL print usage and exit with code 0. **Exception**: `cleanup.py` takes `--before` as a required flag (see R11.1); called with no arguments, it SHALL emit `INVALID_INPUT` and exit with code 1. `--help` still exits 0 via the usual argparse handling.
5. WHERE Scripts share code (DB connection, JSON I/O, URL decode, error envelope), THE App MAY put it in a shared module under `scripts/` (e.g. `scripts/_common.py`). THE shared module SHALL NOT be run as a Script.

### Requirement 3: Output Contract

**User Story:** As the user, I want every script to print JSON and use clear exit codes so I can pipe results or stop on failure.

#### Acceptance Criteria

1. ON success, THE Script SHALL print a Success_Envelope as valid JSON to stdout and exit with code 0.
2. ON handled failure (bad input, missing row, constraint violation, missing DB, unknown subcommand), THE Script SHALL print an Error_Envelope to stderr and exit with code 1.
3. THE Error_Envelope shape SHALL be `{"error": {"code": <string>, "message": <string>, "details": <object|null>}}`. `code` SHALL be one of: `DB_NOT_FOUND`, `SCHEMA_MISMATCH`, `INVALID_INPUT`, `NOT_FOUND`, `CONSTRAINT_VIOLATION`, `SONG_INVARIANT_VIOLATION`, `ALREADY_GRADUATED`, `INVALID_ANSWER`, `INTERNAL_ERROR`.
4. Stdout SHALL contain only the Success_Envelope JSON. Log lines SHALL go to stderr.
5. WHEN a read op like `get` finds zero rows, THE Script SHALL print an Error_Envelope with `code = "NOT_FOUND"` and exit with code 1.
6. WHEN a batch read op (e.g. `batch-get`, `list-learning`) finds some but not all IDs, THE Script SHALL return the rows that exist as a JSON array and SHALL NOT error. Missing IDs simply do not appear in the result.
7. ON an unexpected exception, THE Script SHALL print an Error_Envelope with `code = "INTERNAL_ERROR"` and exit with code 1. THE Script SHALL NOT print a Python traceback on stdout.

### Requirement 4: URL Decoding for Input

**User Story:** As the user, I want to pass values that contain special characters without fighting shell quoting.

#### Acceptance Criteria

1. WHEN `--term` is a string, THE Script SHALL run `urllib.parse.unquote` on it once before using it.
2. WHEN `--data` is a JSON object, THE Script SHALL run `urllib.parse.unquote` once on every string leaf value. THE Script SHALL NOT decode keys, numbers, booleans, nulls, or non-string array items.
3. WHEN a value has no `%` in it, decoding SHALL leave it unchanged.
4. THE Script SHALL decode each string at most once per run.
5. WHERE `--data` contains nested objects or arrays, THE Script SHALL walk them and decode every string leaf under the same rules.

### Requirement 5: Query Operations

**User Story:** As the user, I want to look up rows and find duplicates or cross-references from the CLI.

#### Acceptance Criteria

1. `query.py get` SHALL take a kind (`song`, `artist`, `show`, `rel_show_song`) and an ID, and return that row.
2. WHEN the row exists with `status = 0`, THE `get` op SHALL print it as a JSON object.
3. IF the row is missing or soft-deleted, THEN `get` SHALL print an Error_Envelope with `code = "NOT_FOUND"`.
4. `query.py batch-get` SHALL take a kind and a list of IDs, and return the matching `status = 0` rows as a JSON array. Missing or soft-deleted IDs are skipped without error.
5. `query.py search` SHALL take `--term` and return `status = 0` rows whose `name` (or `name_context` / `name_romaji` where present) contains the term, case-insensitive.
6. `query.py search` SHALL take a `--kind` flag to search songs, artists, or shows.
7. `query.py duplicates` SHALL return groups of `status = 0` rows sharing the same `name` (and, for songs, the same `artist_id`) where a group has two or more rows.
8. `query.py shows-by-artist-ids` SHALL take a list of artist IDs and return the `status = 0` shows that have at least one song by any of those artists via `rel_show_song`.
9. `query.py list-learning` SHALL take `--song-ids` and return all learning records (active and graduated) whose `song_id` is in the list.
10. `query.py songs-by-artist-ids` SHALL take a list of artist IDs and return the `status = 0` songs owned by any of them.
11. Every list result SHALL be a JSON array with a stable order (e.g. by `name`, then `id`), unless the op documents a different order.
12. `query.py song-detail` SHALL take `--id SONG_ID` and return a single JSON object with:
    - `song`: the song row (from `song`), with all its columns.
    - `artist`: the artist row that owns this song, with `{id, name, name_context, status}`. Under normal operation the artist has `status = 0` (deleting an artist cascades to its songs, so a live song under a soft-deleted artist should not exist). If a broken DB has this inconsistency, the artist is still returned here with its `status` visible so the caller can see the problem.
    - `shows`: an array, one entry per show linked to this song via `rel_show_song` where the show has `status = 0`, sorted by show `name` then `id`. Each entry has `{id, name, name_romaji, vintage, s_type, media_urls}` where `media_urls` is the sorted, deduplicated list of non-empty `play_history.media_url` values with `play_history.status = 0` for this `(show_id, song_id)` pair.
    
    IF the song itself is missing or soft-deleted, THEN the op SHALL print an Error_Envelope with `code = "NOT_FOUND"`.
13. `query.py artist-detail` SHALL take `--id ARTIST_ID` and return a single JSON object with:
    - `artist`: the artist row.
    - `songs`: an array, one entry per `status = 0` song owned by this artist, sorted by song `name` then `id`. Each entry has `{id, name, name_context, shows}` where `shows` follows the same shape as in `song-detail` (only `status = 0` shows, sorted by show `name` then `id`, each with its `media_urls`).
    
    IF the artist is missing or soft-deleted, THEN the op SHALL print an Error_Envelope with `code = "NOT_FOUND"`.
14. `query.py show-detail` SHALL take `--id SHOW_ID` and return a single JSON object with:
    - `show`: the show row.
    - `songs`: an array, one entry per `status = 0` song linked to this show via `rel_show_song`, sorted by song `name` then `id`. Each entry has `{id, name, name_context, artist: {id, name, name_context, status}, media_urls}` where `media_urls` is the sorted, deduplicated list of non-empty `play_history.media_url` values with `play_history.status = 0` for this `(show_id, song_id)` pair. The nested `artist` object includes its `status` so a caller can detect an inconsistency (under normal operation the artist is `status = 0`).
    
    IF the show is missing or soft-deleted, THEN the op SHALL print an Error_Envelope with `code = "NOT_FOUND"`.
15. `query.py learning-detail` SHALL take `--id LEARNING_ID` and return a single JSON object with:
    - `learning`: the learning row (all its columns).
    - `song`: the song row that `learning.song_id` points to.
    - `artist`: the artist row that owns the song, with `{id, name, name_context, status}`.
    - `shows`: the shows linked to the song, in the same shape as `song-detail` (only `status = 0` shows, sorted by show `name` then `id`, each with its `media_urls`).
    
    IF the learning row is missing, THEN the op SHALL print an Error_Envelope with `code = "NOT_FOUND"`. IF the referenced `song` or its `artist` is soft-deleted, THEN the op SHALL ALSO print `code = "NOT_FOUND"` — a learning row whose song or artist is soft-deleted points at data that is no longer live, and the operator should clean up the learning row (e.g. via `cleanup.py`) before reviewing.
16. The four `-detail` ops SHALL compute their `media_urls` lists from `play_history` alone (not `rel_show_song.media_url`). Empty-string `media_url` values in `play_history` SHALL be excluded from the output. `media_urls` SHALL be sorted lexicographically and SHALL contain no duplicates.

### Requirement 6: Learning Record Lifecycle

**User Story:** As the user, I want to add songs to review, level them up as I memorize them, and graduate them when I'm done.

#### Acceptance Criteria

1. `learning.py batch` SHALL take a list of song IDs and insert one learning record per ID with `level = 0`, `graduated = 0`, the default level_up_path, and `last_level_up_at = now_epoch`.
2. WHEN `batch` gets a song that already has a non-graduated learning record, THE op SHALL skip it without error and list it under `skipped` in the output.
3. WHEN `batch` gets a song whose only existing learning record is graduated, THE op SHALL insert a new active record at stored level 7 (re-learn level) with `last_level_up_at = now_epoch`.
4. IF `batch` gets a song ID that does not exist or is soft-deleted, THEN THE op SHALL list it under `not_found` in the output and SHALL NOT insert anything for it.
5. `learning.py levelup` SHALL take a list of learning record IDs and, for each, set `level = min(level + 1, Max_Level)`, `last_level_up_at = now_epoch`, and `updated_at = now_epoch`.
6. WHEN `levelup` is run on a record at `level == Max_Level`, THE op SHALL leave `level` alone, set `graduated = 1`, and set `updated_at = now_epoch`.
7. IF any ID passed to `levelup` points to a graduated record, THEN THE op SHALL print an Error_Envelope with `code = "ALREADY_GRADUATED"` listing those IDs, abort the whole call, and write nothing.
8. `learning.py graduate` SHALL take a list of learning record IDs and set `graduated = 1` and `updated_at = now_epoch` for each.
9. WHEN `graduate` is run on a record that is already graduated, THE op SHALL treat it as a no-op and return success for that ID.
10. `learning.py stats` SHALL return counts grouped by stored `level` and by `graduated`, counting only learning records whose song has `status = 0`.

### Requirement 7: Due Selection

**User Story:** As the user, I want to see exactly the songs that are ready for review right now.

#### Acceptance Criteria

1. `learning.py due` SHALL return the learning records that match the Due_SQL_Condition when the command runs.
2. THE `due` op SHALL run the Due_SQL_Condition as-is inside SQLite. It SHALL NOT reimplement `strftime('%s','now')` or `json_extract` in Python.
3. THE `due` op SHALL take an optional `--offset SECONDS` integer (default `0`) and bind it as `@offset`. A positive offset includes records that will be due within that many seconds.
4. THE `due` op SHALL NOT return records with `graduated = 1`.
5. THE `due` op SHALL NOT return records whose song has `status = 1`.
6. THE `due` op SHALL order results by stored `level` descending, with ties broken by `id` ascending.
7. Each returned record SHALL include at least `id`, `song_id`, `song_name` (from the joined song), stored `level`, `display_level`, and `wait_days` (the value of `json_extract(level_up_path, '$[' || level || ']')`, or `0` when missing).

### Requirement 8: HTML Review Page

**User Story:** As the user, I want a single HTML page listing my due songs so I can review in a browser.

#### Acceptance Criteria

1. `review.py song-review` SHALL pull the due records, look up each song's artist and shows, and render one HTML file.
2. THE Script SHALL write the file to disk and print its path as the `path` field of the Success_Envelope. THE Script SHALL NOT print the HTML on stdout.
3. THE HTML SHALL be built with `html.escape` and plain string templating. No template engine.
4. THE HTML SHALL escape every text field from the DB (song name, artist name, show name, `name_context`, `name_romaji`, `media_url`) before embedding it, to avoid HTML injection.
5. For each due song, THE HTML SHALL show `display_level`, the song's name and name_context, the artist's name, the list of shows (name and vintage), and any `media_url` from matching `play_history` or `rel_show_song` rows as clickable links.
6. IF no records are due, THEN THE Script SHALL still write a valid HTML page with a "No songs due" message and exit with code 0.
7. THE Script SHALL write the HTML file under `App_Root/output/` with a timestamped name of the form `review_<EPOCH>.html` (where `<EPOCH>` is the UNIX epoch seconds from `now_epoch`). THE Script SHALL create `App_Root/output/` if it does not exist. It SHALL NOT write anywhere else. THE Script SHALL NOT delete or overwrite previous review files in that folder.

### Requirement 9: Data Management

**User Story:** As the user, I want to create and edit songs, artists, shows, and their links from the CLI.

#### Acceptance Criteria

1. `data.py create` SHALL support kinds `song`, `artist`, `show`, and `rel_show_song`. It takes a `--data` JSON object and inserts a row.
2. FOR `create song`, `create artist`, `create show`: if `--data` has no `id`, THE Script SHALL generate one per the UUID glossary entry. THE Script SHALL set `created_at = updated_at = now_epoch` and `status = 0`.
3. FOR `create rel_show_song`: `--data` SHALL include `show_id` and `song_id`. THE Script SHALL set `created_at = now_epoch` and honor `UNIQUE(show_id, song_id)`.
4. IF `create rel_show_song` is called with a `(show_id, song_id)` pair that already exists, THEN THE Script SHALL print an Error_Envelope with `code = "CONSTRAINT_VIOLATION"` and leave the existing row alone.
5. `data.py update` SHALL support `song`, `artist`, `show`. It takes `--id` and `--data`, patches the given fields, and sets `updated_at = now_epoch`.
6. THE `update` op SHALL NOT let the caller change `id` or `created_at`. Trying to do so SHALL produce `code = "INVALID_INPUT"`.
7. `data.py delete` SHALL soft-delete a row of kind `song`, `artist`, or `show`: set `status = 1` and `updated_at = now_epoch`.
8. WHEN `delete` is called on an artist with `status = 0`, THE Script SHALL first soft-delete every `status = 0` song owned by that artist (set `status = 1` and `updated_at = now_epoch` on each), then soft-delete the artist. The whole cascade runs in one transaction.
9. WHEN `delete` is called on a song or show that is already soft-deleted, OR on an artist whose songs are all already soft-deleted and the artist itself is already soft-deleted, THE Script SHALL treat it as a no-op and return success.
10. `data.py bulk-reassign` SHALL take `--from-artist-id`, `--to-artist-id`, and optional `--song-ids`, and set `artist_id = --to-artist-id` on the matching songs. `updated_at` SHALL be set to `now_epoch`.
11. THE `bulk-reassign` op SHALL change only `artist_id` and `updated_at` on affected songs. `id`, `name`, `name_context`, `created_at`, and `status` stay the same.
12. IF `bulk-reassign` is given a `--to-artist-id` that is missing or soft-deleted, THEN THE Script SHALL print an Error_Envelope with `code = "NOT_FOUND"` and change nothing.
13. Every `data.py` write op SHALL run inside one SQLite transaction. On exception, the transaction SHALL be rolled back.

### Requirement 10: Artist Merge

**User Story:** As the user, I want to fold two or more artists into one in a single run, including cleaning up duplicate songs, so I don't have to patch things up by hand afterwards.

#### Acceptance Criteria

1. `merge_artists.py` SHALL take `--target-artist-id AT` and `--source-artist-ids A1,A2,...` (one or more). `AT` is the artist that stays; the source artists get merged into it.
2. `merge_artists.py` SHALL check that `AT` and every source ID exist with `status = 0`. IF any is missing or soft-deleted, THEN THE Script SHALL print an Error_Envelope with `code = "NOT_FOUND"` and change nothing.
3. `merge_artists.py` SHALL reject the call with `code = "INVALID_INPUT"` if `AT` is in the source list, the source list is empty, or the source list has duplicate IDs.
4. FOR each song with `artist_id ∈ {A1..An} AND status = 0`, THE Script SHALL set `artist_id = AT` and `updated_at = now_epoch`. No other song column changes at this step.
5. AFTER step 4, FOR each group of songs now sharing `(artist_id = AT, name)` with two or more members, THE Script SHALL pick the one with the largest `updated_at` as the winner. Ties break by largest `created_at`, then largest `id`.
6. FOR each losing song `SL` with winner `SW` in its group, THE Script SHALL redirect dependents:
   - `play_history`: update rows with `song_id = SL.id` to `song_id = SW.id`. No rows deleted.
   - `learning`: update rows with `song_id = SL.id` to `song_id = SW.id`. Only `song_id` and `updated_at` change; `level`, `graduated`, `level_up_path`, `last_level_up_at`, and `created_at` stay the same.
   - `rel_show_song`: for each row with `song_id = SL.id`, check whether `(show_id, SW.id)` already exists. If yes, delete the `SL`-pointing row (to stay within `UNIQUE(show_id, song_id)`). If no, update its `song_id` to `SW.id`.
7. AFTER redirecting dependents, THE Script SHALL soft-delete each losing song `SL` (`status = 1`, `updated_at = now_epoch`).
8. AFTER song work is done, THE Script SHALL soft-delete each source artist `A1..An`. `AT` is not touched.
9. THE whole merge SHALL run in one SQLite transaction. On exception, the transaction SHALL be rolled back.
10. ON success, THE Script SHALL print a Success_Envelope with:
    - `target_artist_id`, `source_artist_ids`.
    - `songs_reassigned`: how many songs got their `artist_id` changed in step 4.
    - `duplicate_groups_merged`: how many `(AT, name)` groups needed a winner pick.
    - `songs_soft_deleted`: losing songs soft-deleted in step 7.
    - `play_history_redirected`, `learning_redirected`, `rel_show_song_redirected`: rows whose `song_id` was updated.
    - `rel_show_song_cascade_deleted`: rows deleted because of the UNIQUE constraint.
    - `source_artists_soft_deleted`: source artists soft-deleted in step 8.
11. `merge_artists.py` SHALL NOT hard-delete any row from `song`, `artist`, `show`, `play_history`, or `learning`. THE only table it may remove rows from is `rel_show_song`, and only to keep `UNIQUE(show_id, song_id)`.

### Requirement 11: Periodic Cleanup

**User Story:** As the user, I want to hard-delete old soft-deleted rows so the DB doesn't grow forever.

#### Acceptance Criteria

1. `cleanup.py` SHALL require `--before EPOCH_SECONDS` (a positive integer UNIX timestamp in UTC). There is no default. IF `--before` is missing, THE Script SHALL print an Error_Envelope with `code = "INVALID_INPUT"` and change nothing.
2. THE Script SHALL pick **target rows** in `song`, `artist`, and `show` using `status = 1 AND updated_at <= EPOCH_SECONDS`. Rows with `status = 0` are never touched.
3. THE Script SHALL hard-delete the target rows plus these **dependent rows**:
   - `rel_show_song` rows where `song_id` or `show_id` is a target.
   - `play_history` rows where `song_id` or `show_id` is a target.
   - `learning` rows where `song_id` is a target.
   - THE Script SHALL NOT follow artist → songs. Songs owned by a target artist are only deleted if they are themselves target rows (i.e. the operator already soft-deleted them). Live songs under a deleted artist stay.
4. THE Script SHALL take an optional `--confirm` flag. Without `--confirm`, the run is a dry-run and nothing is written.
5. ON a dry-run, THE Script SHALL print a Success_Envelope with:
   - `cutoff_epoch` and `cutoff_iso_utc` (e.g. `"2025-10-01T00:00:00Z"`).
   - `target_counts`: `{song, artist, show}` counts.
   - `cascade_counts`: `{rel_show_song, play_history, learning}` counts.
   - `oldest_candidate_updated_at`, `newest_candidate_updated_at`: across all target rows (null if none).
   - `top_cascade_samples`: up to 10 target rows with the largest dependent footprint. Each entry has `kind`, `id`, `name`, and per-table cascade counts.
   - `total_rows_to_hard_delete`.
   - `executed: false`.
6. A dry-run SHALL NOT list every candidate row.
7. WITH `--confirm`, THE Script SHALL delete dependent rows first, then target rows, all in one transaction. On exception, roll back.
8. WITH `--confirm`, THE Script SHALL print the same fields as a dry-run plus `executed: true` and `hard_deleted_counts` (same shape as `target_counts + cascade_counts`).
9. THE Script SHALL enable `PRAGMA foreign_keys = ON`. It MAY rely on `rel_show_song.ON DELETE CASCADE`, but SHALL issue explicit DELETEs for `play_history` and `learning` since those tables do not declare `ON DELETE CASCADE`.
10. IF `--before` is non-positive or not an integer, THE Script SHALL print an Error_Envelope with `code = "INVALID_INPUT"` and change nothing.
11. `cleanup.py` is the only Script that may hard-delete rows from `song`, `artist`, `show`, `play_history`, or `learning`. Every other Script leaves those tables soft-delete-or-append-only.
12. Running `cleanup.py` twice with the same `--before` SHALL find zero candidates the second time (assuming no other writes in between) and report all-zero counts.

### Requirement 12: AMQ Import — Step 1 (Plan)

**User Story:** As the user, I want the app to scan an AMQ JSON file and tell me which entries can be imported automatically and which need my input, so I only look at the tricky cases.

#### Acceptance Criteria

1. `import_plan.py` SHALL take a path to an AMQ JSON file (via `--input` or positional) and parse it with `json.load`.
2. THE Script SHALL treat the input as a flat list of entries with fields `song_name`, `artist_name`, `show_name`, `vintage`, and optional `media_url`. Extra fields are ignored.
3. THE Script SHALL URL-decode every string field in every entry before any DB lookup (per Requirement 4).
4. FOR each entry, THE Script SHALL resolve the song by `(song_name, artist_name)` against the DB:
   - Let `A = { artist rows where name = entry.artist_name AND status = 0 }`.
   - If `|A| == 1`, look for a song with `name = entry.song_name AND artist_id = A[0].id AND status = 0`. If one exists, mark the entry **resolved** with that `song_id`. If zero exist, mark it **auto_completable** (artist is clear, song is missing). If two or more exist, the DB has broken the per-artist unique-name property; THE Script SHALL print an Error_Envelope with `code = "SONG_INVARIANT_VIOLATION"`, list the offending song IDs and the `(artist_id, song_name)` pair in `details`, and abort. The operator should soft-delete the extras before retrying.
   - If `|A| == 0`, mark the entry **auto_completable** (artist and song both missing).
   - If `|A| >= 2`, mark the entry **ambiguous** and attach the matching artist rows as candidates.
5. FOR each entry, THE Script SHALL resolve the show by `(show_name, vintage)`:
   - If a show with `name = entry.show_name AND vintage = entry.vintage AND status = 0` exists, record its `id`.
   - Otherwise mark the show for creation. A missing show by itself SHALL NOT make the entry ambiguous.
6. THE Success_Envelope SHALL be an object with three arrays:
   - `resolved`: entries where the song already exists. Each item has `song_id`, either `show_id` or a `show_to_create` block, and `media_url`.
   - `auto_completable`: entries where the song does not exist but the artist is clear. Each item has either `artist_id` or an `artist_to_create` block, plus `song_name`, the show info, and `media_url`.
   - `ambiguous`: entries where the artist name matches two or more artists. Each item has `artist_name`, `song_name`, `show_name`, `vintage`, `media_url`, and a `candidates` array of matching artist rows (`id`, `name`, `name_context`).
7. `import_plan.py` SHALL NOT write to DB_File. THE plan JSON is the only hand-off from step 1 to step 2.
8. Each plan entry SHALL carry at most one artist choice. Step 2 resolves ambiguous entries to exactly one artist. v1 does not support attaching multiple artists to a single song.
9. WITH `--output PATH`, THE Script SHALL write the plan JSON to PATH (creating parent directories under `App_Root` if needed) and print a short summary (`resolved_count`, `auto_completable_count`, `ambiguous_count`, `path`) to stdout. WITHOUT `--output`, THE Script SHALL print the full plan JSON to stdout.

### Requirement 13: AMQ Import — Step 2 (Resolve)

**User Story:** As the user, I want to hand the plan plus my answers back to the app and have it create any missing rows, so every entry ends up with real database IDs.

#### Acceptance Criteria

1. `import_resolve.py` SHALL take `--plan PATH` pointing to a step 1 plan, and an optional `--answers PATH` with disambiguation answers.
2. THE Script SHALL process entries in order: `resolved`, `auto_completable`, then answered `ambiguous`. Each entry ends with a concrete `(song_id, show_id, media_url)` triple.
3. FOR each `resolved` entry, THE Script SHALL:
   - Use the `song_id` from the plan directly. THE Script SHALL NOT re-query the song or artist.
   - If the plan has `show_id`, use it. If the plan has a `show_to_create` block (fields `name`, `vintage`, optional `s_type` / `name_romaji`), reuse an existing live `(name, vintage)` show when one exists, otherwise create the show with a fresh UUID (see Glossary), `now_epoch` timestamps, and `status = 0`, and use the new ID.
   - Emit `(song_id, show_id, media_url)`.
   - `--answers` is ignored for resolved entries.
4. FOR each `auto_completable` entry, THE Script SHALL:
   - If the entry has `artist_to_create`, create a new artist row with the given `name`, empty `name_context` unless one is supplied, a fresh UUID (see Glossary), `now_epoch` timestamps, and `status = 0`. Otherwise use the given `artist_id`.
   - Create a new song row with `name = song_name`, the resolved `artist_id`, a fresh UUID (see Glossary), `now_epoch` timestamps, empty `name_context`, and `status = 0`. Exception: if a live song with the exact `(name, artist_id)` pair already exists, reuse its id instead of inserting. This makes rerunning the full pipeline idempotent on songs (Property 13.7).
   - Resolve or create the show (same as criterion 3).
   - Emit `(song_id, show_id, media_url)`.
   - `--answers` is ignored for auto_completable entries.
5. THE `--answers` JSON SHALL be an object keyed by the stringified index of an ambiguous entry. Each value is one of:
   - `{"choose_artist_id": "<existing-id>"}` — use one of the candidate artists.
   - `{"create_artist": {"name": "...", "name_context": "..."}}` — make a new artist with this name and name_context.
6. FOR each `ambiguous` entry, THE Script SHALL read the corresponding answer:
   - `choose_artist_id`: the ID SHALL be in the entry's `candidates`. Otherwise, print `code = "INVALID_ANSWER"` and abort.
   - `create_artist`: create the new artist row (UUID per Glossary, `now_epoch`, `status = 0`) and use its ID.
   - Then create the song row with that `artist_id` — reusing an existing live `(name, artist_id)` row when one already exists, same idempotency rule as criterion 4 — resolve or create the show (per criterion 3), and emit `(song_id, show_id, media_url)`.
7. IF an ambiguous entry has no matching answer, THEN THE Script SHALL leave it unresolved, create no rows for it, and list it under `unresolved_ambiguous` in the Success_Envelope (entry index and candidates). Other entries still get processed.
8. THE Script SHALL run all writes in one SQLite transaction. On exception, roll back and print an Error_Envelope.
9. THE Success_Envelope SHALL include:
   - `triples`: the list of `(song_id, show_id, media_url)` for step 3.
   - `artists_created`, `shows_created`, `songs_created`.
   - `unresolved_ambiguous`: entries still needing answers (empty when all are answered).
10. WITH `--output PATH`, THE Script SHALL write the Success_Envelope JSON to PATH under `App_Root` and print a summary to stdout. Without it, print the full envelope to stdout.

### Requirement 14: AMQ Import — Step 3 (Add Play History)

**User Story:** As the user, I want a single-purpose script that turns `(song_id, show_id, media_url)` triples into play_history rows, so this step stays simple.

#### Acceptance Criteria

1. `add_play_history.py` SHALL take input as `--input PATH` (a JSON file with `{"triples": [{"song_id":..., "show_id":..., "media_url":...}, ...]}`) or inline via `--triples`.
2. FOR each triple, THE Script SHALL check that `song_id` and `show_id` both point to rows with `status = 0`. IF any is missing or soft-deleted, THEN THE Script SHALL abort with `code = "NOT_FOUND"` and write nothing.
3. FOR each triple, THE Script SHALL upsert a `rel_show_song` row for `(show_id, song_id)`: insert if missing (with `created_at = now_epoch` and the triple's `media_url`); leave an existing row as it is.
4. FOR each triple, THE Script SHALL insert one `play_history` row with a fresh UUID (see Glossary), `show_id`, `song_id`, `created_at = now_epoch`, `status = 0`, and the triple's `media_url` (empty string if none).
5. THE Script SHALL run all writes in one SQLite transaction. On exception, roll back.
6. THE Success_Envelope SHALL include `play_history_created` and `rel_show_song_created` counts.
7. THE Script SHALL NOT accept song, artist, or show names. It works only from IDs.
8. THE Script SHALL run standalone too: an operator who already has triples can use it without touching steps 1 and 2.
9. THE Script SHALL NOT deduplicate `play_history` rows. Running it twice with the same triples produces twice the rows. Only `rel_show_song` is de-duped, because of its UNIQUE constraint.

### Requirement 15: Soft-Delete Visibility

**User Story:** As the user, I want deleted rows to stay out of my normal workflows but still sit in the DB in case I want them back.

#### Acceptance Criteria

1. WHEN any `query.py` op returns rows by default, THE op SHALL skip rows with `status = 1`.
2. WHEN any `learning.py` op reads songs (directly or via join), THE op SHALL skip songs with `status = 1`.
3. `data.py delete` SHALL leave the row in the DB with `status = 1`. It SHALL NOT run a SQL `DELETE`.
4. `data.py update` SHALL NOT allow setting `status` to arbitrary values. Status changes only through `create` (→ 0) and `delete` (→ 1).

### Requirement 16: Time Handling

**User Story:** As the user, I want the app to use one clear notion of "now" so due times behave the same regardless of timezone.

#### Acceptance Criteria

1. All stored timestamps (`created_at`, `updated_at`, `last_level_up_at`, `play_history.created_at`) SHALL be UNIX epoch seconds (UTC).
2. WHEN a Script needs the current time, THE Script SHALL compute `now_epoch = int(datetime.datetime.now(datetime.timezone.utc).timestamp())`.
3. THE App SHALL NOT use the system's local timezone for any stored timestamp or for due selection.
4. WHERE the app converts days to seconds, THE App SHALL use exactly `86400`. No daylight-saving adjustments.
5. WHERE a Script reads a learning record's `level_up_path` and it is NULL or not valid JSON, THE Script SHALL fall back to the default level_up_path (from the Glossary) and SHALL NOT crash.

### Requirement 17: Level Display

**User Story:** As the user, I want levels to start at 1 because 0-indexed levels are confusing to humans.

#### Acceptance Criteria

1. WHEN any Script prints a learning level for a human, THE Script SHALL include both stored `level` (0-indexed) and `display_level` (1-indexed).
2. THE HTML review page SHALL show `display_level`, not stored `level`.
3. WHEN a Script takes a level as input (e.g. in `--data`), THE Script SHALL treat it as stored (0-indexed). THE Script SHALL NOT shift it.

### Requirement 18: Test Coverage

**User Story:** As the user, I want the code well tested end-to-end so I can trust the scripts before I run them against my real DB.

#### Acceptance Criteria

1. THE App SHALL ship a `tests/` folder at the repo root, sibling to `scripts/` and `db/`. Tests SHALL NOT live under `scripts/`.
2. THE `tests/` folder SHALL have two subfolders:
    - `tests/unit/` — tests that call Python functions directly (helpers in `scripts/_common.py`, the easing function, etc.).
    - `tests/integration/` — tests that call each script by running `python scripts/<name>.py ...` as a subprocess and checking stdout, stderr, and exit code.
3. Integration tests SHALL use `subprocess.run` (from the stdlib) to invoke scripts, not `import` + call `main()`. This tests the same surface a user or shell pipeline sees.
4. Tests SHALL NEVER read from, write to, create, delete, or rename the real `db/datasource.db` file at the repo root. This is a hard rule.
   - Unit tests that need a DB SHALL use `:memory:` or a temp-directory SQLite file they own.
   - Integration tests SHALL run each script against a temp `App_Root` (created under `pytest`'s `tmp_path` or equivalent) containing its own fresh `db/datasource.db`. The real repo-root `db/datasource.db` SHALL NOT be the script's `App_Root`.
   - End-to-end tests that chain scripts SHALL share one temp `App_Root` across the chain; they SHALL NOT fall back to the real DB for any step.
   - THE test harness SHALL guard this rule mechanically: before a test runs, it SHALL record `db/datasource.db`'s size and mtime; after the test, it SHALL re-check both and fail the suite if either changed.
5. FOR each acceptance criterion in Requirements 1 through 17, THE `tests/` folder SHALL include at least one test (unit or integration) that exercises it.
6. Every Error_Envelope `code` listed in Requirement 3 (`DB_NOT_FOUND`, `SCHEMA_MISMATCH`, `INVALID_INPUT`, `NOT_FOUND`, `CONSTRAINT_VIOLATION`, `SONG_INVARIANT_VIOLATION`, `ALREADY_GRADUATED`, `INVALID_ANSWER`, `INTERNAL_ERROR`) SHALL have at least one integration test that triggers it and asserts the exact code string in the stderr JSON.
7. THE test suite is a dev-time artifact; it SHALL NOT be deployed, and it SHALL NOT run in the restricted runtime environment. Dev tooling for the test suite MAY use any package that makes developer life easier — `pytest`, `coverage`, `ruff`, `mypy`, and so on — all pinned in `requirements-dev.txt`. No file under `scripts/` imports from any of those packages. The packaging command (`make package`) excludes `tests/`, `requirements-dev.txt`, `pyproject.toml`, `tools/`, and caches from the deployable zip.
8. Tests SHALL seed `random` explicitly with a fixed integer so property-style tests are reproducible.
9. THE test suite SHALL be runnable with a single command. `tests/run.sh` (invoked by `make test`) runs the whole suite and measures line coverage.
10. Line coverage across `scripts/` (excluding `tests/` and `scripts/__init__.py`) SHALL be at least **90%** when the full test suite runs. THE target is line coverage, measured by `coverage.py` (pinned in `requirements-dev.txt`). Branch coverage is not required.
11. Hitting the 90% target SHALL be enforced by `tests/run.sh`: it runs the suite under `coverage`, reports per-file line coverage, and exits non-zero when the total ratio is below 0.90.
12. THE test suite SHALL be deterministic: repeated runs with the same inputs produce the same pass/fail results. Tests that use random data SHALL seed `random` explicitly.
13. Integration tests SHALL set a fixed epoch for `now_epoch` through a test seam (for example a `JANKENOBOE_TEST_NOW` env var read by `scripts/_common.py`, or a module-level `_clock()` function patched by unit tests) so timing-dependent assertions are stable.
14. Property-based tests (per the Correctness Properties section) SHALL live under `tests/unit/property/` or similar, and their coverage SHALL count toward the 90% target.

### Requirement 20: Packaging

**User Story:** As the user, I want a single command that builds a deployable zip so I can drop the app onto a new machine (or restricted sandbox) without hauling the dev tree along.

#### Acceptance Criteria

1. THE App SHALL provide a `make package` target (and a standalone `python3 tools/package.py` entry point) that writes `dist/anilearn-simple-<YYYYMMDD>.zip`, where `<YYYYMMDD>` is the UTC date.
2. THE zip SHALL contain exactly these paths relative to its archive root:
   - `scripts/` (runtime Python files, caches excluded)
   - `db/datasource.db` (empty, schema only, built from `tests/fixtures/schema.sql`)
   - `Makefile` (top-level; runtime targets only)
   - `README.md` (when present at the repo root)
3. THE zip SHALL NOT contain any of: `tests/`, `.kiro/`, `docs/`, `tools/`, `requirements-dev.txt`, `pyproject.toml`, `.gitignore`, `.venv/`, `venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.trace/`, `.coverage_data/`, `.coveragerc`, `output/`, `dist/`, or the repo's real (non-empty) `db/datasource.db`.
4. `tools/package.py` SHALL import only from the Python standard library — the packaging step runs on the same footing as the runtime.
5. `make package` SHALL be deterministic when run from a clean checkout: re-running it on the same day produces a zip with the same file contents (file ordering inside the archive may vary if the tool can't guarantee it, but the set of paths and their bytes SHALL match).
6. Unzipping the archive into an empty directory SHALL yield a working App_Root: `python3 scripts/query.py --help` (or any other help-only invocation) succeeds without a `pip install`.

### Requirement 19: Out of Scope for v1

**User Story:** As the user, I want v1 scope pinned so the app doesn't drift away from a single-user local tool.

#### Acceptance Criteria

1. THE App SHALL NOT provide cloud sync, remote storage, or a network-accessible server.
2. THE App SHALL NOT support multiple users, authentication, or authorization.
3. THE App SHALL NOT provide a GUI or web UI. All interaction is through Scripts.
4. THE App SHALL NOT migrate DB_File's schema. It assumes the schema already matches.
5. IF DB_File's schema is missing a required table or column, THEN THE Script SHALL print an Error_Envelope with `code = "SCHEMA_MISMATCH"` and exit with code 1. It SHALL NOT try to repair the schema.
6. THE App SHALL NOT require any package manager, virtual environment, or third-party runtime. Tests live outside the deployable tree and are a dev-time concern only; the runtime environment is not expected to host the test suite.

## Correctness Properties for Property-Based Testing

Each property below is an invariant to check across many randomized inputs. Tests run under the rules in Requirement 18 — including a temp SQLite database per test (never the real `db/datasource.db`).

### Property 1: Create–Get Round-Trip

For any valid `--data` payload for `data.py create` on kind K in `{song, artist, show}`:
1. Create a row with that payload.
2. Run `query.py get` on the returned ID.
3. The returned row contains every field from the create payload (after URL decoding) plus a generated `id`, `created_at`, `updated_at`, and `status = 0`.

### Property 2: URL Decode Runs Once

For any string S with no `%`:
1. `urllib.parse.unquote(S) == S`.
2. Passing S through the `--term` / `--data` decode pipeline leaves it unchanged.

For any string S with `%XX` sequences: decoding runs at most once per call. Running the command does not decode twice.

### Property 3: Soft-Delete Hides Rows

For any row R of kind K in `{song, artist, show}` with `status = 0`:
1. After `data.py delete --id R.id`, R is not returned by `query.py get`, `batch-get`, or `search` (without a `--include-deleted` flag).
2. A direct SQLite `SELECT` by ID still returns R with `status = 1`.
3. R's other columns (`name`, `name_context`, `created_at`, etc.) are unchanged.

For any artist A with `status = 0` owning songs `S1..Sn` (each `status = 0`):
4. After `data.py delete --id A.id`, every Si has `status = 1` and `updated_at = now_epoch`. A also has `status = 1`.
5. Other columns on every Si (`id`, `name`, `name_context`, `artist_id`, `created_at`) are unchanged.
6. Other artists' songs, and any `rel_show_song`, `play_history`, or `learning` rows, are not touched.

### Property 4: Level-Up Moves Up By One

For any learning record L with `graduated = 0` and stored level `L0`:
1. After `learning.py levelup --ids [L.id]`, the new level `L1 == min(L0 + 1, Max_Level)`.
2. `L1 - L0 ∈ {0, 1}`.
3. `L1 <= Max_Level`.
4. `last_level_up_at == now_epoch`.
5. If `L0 == Max_Level`, then `graduated == 1`.

### Property 5: Graduate Is Safe To Repeat

For any learning record L:
1. After one `learning.py graduate --ids [L.id]`, `graduated = 1`.
2. A second `graduate` on the same ID leaves `level` unchanged and keeps `graduated = 1`.
3. `graduate` does not change `created_at` or `id`.

### Property 6: Easing Function Matches Its Definition

For the Python `fibo`, `shrink`, `default_easing`, and `generate_level_up_path` defined in the Glossary:
1. FOR every integer `n` in `[0, 25]`, `fibo(n)` matches the textbook Fibonacci sequence.
2. FOR every non-negative integer `n`, `shrink(n) == (n * 2) // 9`.
3. FOR every integer `n` in `[0, max_level - 1]`, `default_easing(n) = 1` if `shrink(fibo(n+1)) - shrink(fibo(n)) == 0`, else that difference.
4. `generate_level_up_path(20) == [1,1,1,1,1,1,1,2,3,5,7,13,19,32,52,84,135,220,355,574]`.
5. `generate_level_up_path(max_level)` for any `max_level` in `[1, 25]` returns exactly `max_level` positive integers, non-decreasing.

### Property 7: Due Matches the SQL

The one source of truth for "due" is Due_SQL_Condition in the Glossary. This property checks that `learning.py due` returns exactly what that SQL selects.

For any population of learning records with random `level`, `graduated`, `last_level_up_at`, `updated_at`, and `level_up_path`, given a fixed `now_epoch`:
1. Let `E` be the set of rows that Due_SQL_Condition returns (with `strftime('%s','now')` pinned to `now_epoch` and `@offset = 0`) whose song has `status = 0`.
2. `learning.py due` returns exactly the rows in `E`.
3. Every L with `graduated = 1` is not in `E`.
4. Every L whose song has `status = 1` is not in `E`.
5. The test covers each of the three Due_SQL_Condition clauses (including the boundary value where the comparison is `=`, which is due).
6. With `--offset K` for any non-negative integer K, the result matches Due_SQL_Condition with `@offset = K`.

### Property 8: Bulk-Reassign Keeps Song Identity

For any set of song IDs S owned by artist A1, given a target artist A2 (distinct, `status = 0`):
1. After `data.py bulk-reassign --from-artist-id A1 --to-artist-id A2 --song-ids S`:
   - Every song in S has `artist_id = A2`.
   - `id`, `name`, `name_context`, `created_at`, and `status` on each song in S match their pre-call values.
   - Only `artist_id` and `updated_at` change.
2. Songs not in S are unchanged.
3. `bulk-reassign` succeeds even when the reassignment creates a `(A2, name)` collision with an existing A2-owned song. This is the expected merge-duplicates workflow.

### Property 9: Artist Merge Preserves History

For target artist `AT` with `status = 0` and a non-empty list of source artists `A1..An` (distinct from `AT`, each `status = 0`):
1. After `merge_artists.py`:
   - Every song previously owned by a source artist is now owned by `AT`, either as a live row (winner) or soft-deleted (loser).
   - Every source artist has `status = 1`.
   - `AT` still has `status = 0`.
2. FOR each `(AT, name)` duplicate group, exactly one song survives, chosen by largest `updated_at` (ties by largest `created_at`, then largest `id`).
3. `COUNT(*) FROM play_history` is unchanged. Every play_history row that pointed to a losing song now points to its winner. No row added or removed.
4. `COUNT(*) FROM learning` is unchanged. Every learning row that pointed to a losing song now points to its winner. `level`, `graduated`, `level_up_path`, `last_level_up_at`, and `created_at` are unchanged on redirected rows.
5. `rel_show_song`: every pre-merge `(show_id, winner_song_id)` pair is still present. `UNIQUE(show_id, song_id)` holds after the merge. Rows removed to keep the constraint are reported in `rel_show_song_cascade_deleted`.
6. Running the same `merge_artists.py` command a second time fails with `code = "NOT_FOUND"` on the now-soft-deleted source IDs.
7. No rows are hard-deleted from `song`, `artist`, `show`, `play_history`, or `learning`. Only `rel_show_song` may have rows removed (for the UNIQUE constraint).
8. On an injected mid-operation failure, the whole merge rolls back: every table's count and every row's columns match their pre-merge values.

### Property 10: Cleanup Stays in Its Lane

For any cutoff `T` and a seeded DB with a mix of `status = 0` and `status = 1` rows across `song`, `artist`, `show`, plus dependents in `rel_show_song`, `play_history`, and `learning`:
1. `cleanup.py --before T` in dry-run mode does not change anything. `COUNT(*)` for every table is the same before and after.
2. After `cleanup.py --before T --confirm`:
   - Every surviving `song`/`artist`/`show` row has `status = 0 OR updated_at > T`. No row with `status = 1 AND updated_at <= T` remains.
   - Every `status = 0` row is unchanged.
   - Every `rel_show_song`, `play_history`, and `learning` row points to a surviving `song_id` (and `show_id` where relevant).
3. Running `cleanup.py --before T --confirm` a second time deletes zero rows.
4. `cleanup.py` without `--before` prints `code = "INVALID_INPUT"` and does not open the DB beyond what's needed to emit the error.
5. Any number of dry-runs against any DB state are safe: the DB is byte-identical before and after.
6. `cleanup.py` is the only Script that hard-deletes from `song`, `artist`, `show`, `play_history`, or `learning`.

### Property 11: Show–Song Uniqueness

For any `(show_id, song_id)` pair:
1. The first `data.py create rel_show_song` succeeds.
2. A second `create` with the same pair fails with `code = "CONSTRAINT_VIOLATION"`.
3. After the failed second insert, the existing `rel_show_song` row is unchanged.
4. `COUNT(*) FROM rel_show_song WHERE show_id = ? AND song_id = ?` equals 1.

### Property 12: Detail Ops Compose Cleanly

For any song S with `status = 0` whose owning artist A has `status = 0`:
1. `query.py song-detail --id S.id` returns an object where `song` has every column of S, `artist` has A's fields plus its `status`, and `shows` lists exactly the shows linked to S via `rel_show_song` where the show has `status = 0`.
2. FOR each show entry, `media_urls` is the sorted, deduplicated list of non-empty `play_history.media_url` values with `play_history.status = 0` for that `(show_id, song_id)` pair. URLs from `rel_show_song.media_url` do not appear unless they also appear in `play_history`.

For any artist A with `status = 0` owning songs `S1..Sn` (all `status = 0`):
3. `query.py artist-detail --id A.id` returns `artist` = A and `songs` = the sorted list of only `status = 0` songs owned by A. Each song carries its own `shows` list built by the same rule as in `song-detail`.
4. The set of media URLs across all `Si.shows[].media_urls` in `artist-detail` equals the set that would come from running `song-detail` on each Si and collecting the same fields.

For any show SH with `status = 0`:
5. `query.py show-detail --id SH.id` returns `show` = SH and `songs` = the sorted list of `status = 0` songs linked to SH. Each song carries its `artist` (with `status`) and its per-`(SH, song)` `media_urls`.

For any detail op called on a missing or soft-deleted target ID:
6. The op returns `code = "NOT_FOUND"`.

For `data.py delete` followed by any detail op:
7. After soft-deleting artist A, `artist-detail --id A.id` returns `NOT_FOUND`. Every song previously owned by A is also soft-deleted, so `song-detail` on any of those songs also returns `NOT_FOUND`, and `show-detail` no longer lists those songs under any show.

For any learning record L whose song S has `status = 0` and S's artist A has `status = 0`:
8. `query.py learning-detail --id L.id` returns `{learning, song, artist, shows}` where `learning` has every column of L, `song` and `artist` match what `song-detail --id L.song_id` would return for those two fields, and `shows` matches what that same `song-detail` would return under the same key.
9. IF S is soft-deleted OR A is soft-deleted (which under normal operation only happens after `data.py delete` on A, which cascades to S), THEN `learning-detail --id L.id` returns `NOT_FOUND`.
10. IF L itself is missing, THEN `learning-detail` returns `NOT_FOUND`.

### Property 13: Import Pipeline End-to-End

For any AMQ input of entries where some reference existing artists, some reference new names, some reference existing songs, and some reference artist names shared by two or more artists:
1. After `import_plan.py`, every entry is in exactly one of `resolved`, `auto_completable`, or `ambiguous`. `len(resolved) + len(auto_completable) + len(ambiguous) == len(entries)`.
2. `import_plan.py` does not modify the DB. Two runs on the same input produce the same plan JSON.
3. An entry lands in `ambiguous` if and only if two or more `status = 0` artists share `artist_name`.
4. An entry lands in `resolved` if and only if `(song_name, artist_name)` matches exactly one `status = 0` artist and one `status = 0` song owned by that artist.
5. After `import_resolve.py` runs with answers for every `ambiguous` entry, every entry produces exactly one `(song_id, show_id, media_url)` triple. `len(triples) == len(entries)`.
6. After `add_play_history.py` runs on those triples, every triple adds exactly one new `play_history` row. Each `(show_id, song_id)` pair has exactly one `rel_show_song` row, whether or not one existed before.
7. Running the full plan → resolve → add_play_history pipeline a second time on the same input and answers adds no new artists, songs, shows, or `rel_show_song` rows. Only new `play_history` rows are added each run.

### Property 14: Step Boundaries

1. `import_plan.py` does not change the DB. Before and after byte-identical.
2. `import_resolve.py` on a plan with empty `ambiguous` and `auto_completable` entries that all have `artist_id` creates zero new artist rows. New rows are limited to songs and shows that the plan marked for creation.
3. `add_play_history.py` does not change `song`, `artist`, or `show`. Writes happen only on `play_history` (insert) and `rel_show_song` (upsert). Tests snapshot those three tables before and after and assert equality.
4. `add_play_history.py` rejects the whole batch with `code = "NOT_FOUND"` if any triple references a missing or soft-deleted `song_id` or `show_id`. No partial writes.

### Property 15: JSON Output Validity

For every successful Script call across representative inputs:
1. Stdout parses with `json.loads`.
2. Stderr is either empty or does not interfere with parsing stdout.
3. On failure, stderr parses with `json.loads` and matches the Error_Envelope shape.

### Property 16: Rollback on Failure

For any `data.py` write, `merge_artists.py`, `cleanup.py --confirm`, `import_resolve.py`, or `add_play_history.py` call with an injected mid-operation failure:
1. No new rows appear.
2. No pre-existing rows are changed.
3. THE Script exits with code 1 and prints an Error_Envelope.

### Testing Notes

- Tests use `pytest` and `coverage.py` (pinned in `requirements-dev.txt`). No `hypothesis` — property-style tests use a seeded `random` generator (each test seeds `random.seed(...)` with a fixed integer). The state space per property is small enough that a few hundred iterations through seeded `random` gives good coverage.
- Import-pipeline tests run against an in-memory SQLite DB built from the real schema. They do not touch real data.
- Due-selection tests inject `now_epoch` through a test seam (e.g. a module-level `_clock()` function) so they are deterministic.

## References

The deploy-time package inventory for the sandbox this app runs in lives at [`dev-docs/sandbox-packages.md`](../../../dev-docs/sandbox-packages.md). Check that list before reaching for any third-party package.

This document stands on its own. The timing SQL, the easing function, the import flow, and the schema conventions came from an earlier Rust project with a similar workflow:

- https://github.com/pandazy/jankenoboe

Nothing in this document depends on that project.
