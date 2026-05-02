---
name: searching-library
description: Explores the anime song library — songs, artists, shows, and learning records — via read-only queries. Covers search, duplicate detection, cross-references (shows by artist, songs by artist), and detail views. Use when the user says "search", "find", "look up", "show me", "list", "details", or asks about a specific song/artist/show.
---

# Searching the Library

Use this skill when the user wants to read from the library without changing anything. All work goes through `scripts/query.py`, which is read-only. The data lives in `db/datasource.db`.

## Pattern: when the user gives a name, not an ID

Most real questions start with a name ("who sings Song X?"). The answer always involves two steps: search first to get an ID, then use a detail op for the full picture.

1. `scripts/query.py search --kind {song,artist,show} --term "<text>"` returns matching rows with their IDs.
2. Pick the right row with the user's help when needed.
3. Pass that ID to the matching detail op (`song-detail`, `artist-detail`, `show-detail`).

When the user asks a combined question — "songs in show X by artist Y", "which songs from show X does artist Y sing?" — reach for `search-songs` instead. It takes the song, show, and artist name filters together, ANDs the ones you pass, and returns each matching song with the detail-shaped rows already attached, so the follow-up `*-detail` calls are unnecessary.

## Checklist: available ops

1. **Initialize the database.** Run `python scripts/init_db.py`. Creates `db/datasource.db` on first use; safe no-op afterwards.

- **Single row by ID.** `scripts/query.py get --kind {song,artist,show,rel_show_song} --id ID`. Returns `NOT_FOUND` when missing or soft-deleted.
- **Many rows by ID.** `scripts/query.py batch-get --kind ... --ids ID1,ID2,...`. Missing or soft-deleted IDs are silently skipped.
- **Search by text.** `scripts/query.py search --kind {song,artist,show} --term "<text>"`. Case-insensitive substring match over `name` (plus `name_context` for songs/artists, `name_romaji` for shows). The term is URL-decoded once before matching.
- **Search songs with combined filters.** `scripts/query.py search-songs [--song-term "<text>"] [--show-term "<text>"] [--artist-term "<text>"]`. Case-insensitive substring match like `search`, but song-first: each flag is optional, every flag you pass is ANDed together, and each matching song comes back with its artist and the shows it's linked to (with `media_urls`) already attached. With no flags, returns every live song with related details. Terms are URL-decoded once before matching. Envelope shape is `{filters, count, results}` — `filters` echoes the decoded terms (or `null` for flags you skipped), and each entry in `results` has the detail-shaped `song`, `artist`, `shows`, `learning`, `graduated`, and `warnings` fields.
- **Find duplicates.** `scripts/query.py duplicates --kind {song,artist,show}`. Groups rows with the same name (and same artist, for songs). Use this to hunt down namesake artists before merging.
- **Cross-reference.** `scripts/query.py shows-by-artist-ids --artist-ids ...` and `scripts/query.py songs-by-artist-ids --artist-ids ...`. Both filter out soft-deleted rows.
- **Learning records for songs.** `scripts/query.py list-learning --song-ids ...`. Returns every learning record (active or graduated) whose song is live.
- **Full detail.** `scripts/query.py song-detail --id SONG_ID`, `artist-detail --id ARTIST_ID`, `show-detail --id SHOW_ID`, `learning-detail --id LEARNING_ID`. Each returns the row plus related rows — songs include their artist and shows, shows include their songs and media URLs, and so on.

## Notes

- All queries skip soft-deleted rows by default (`status = 0` filter). If the user needs to see a soft-deleted row, they'll need to query SQLite directly or ask to restore the row (which isn't supported out of the box).
- `media_urls` in any detail op is the sorted, deduplicated list from `play_history` only (not `rel_show_song.media_url`).
- `learning-detail` returns `NOT_FOUND` when the referenced song or artist is soft-deleted. That's a hint to clean up the learning row via `cleanup.py`.
- All scripts run on stdlib Python 3.10+. No `pip install` needed.

## Command reference

Run any subcommand with `--help` for the full flag list and output shape. The flag names above are exact.
