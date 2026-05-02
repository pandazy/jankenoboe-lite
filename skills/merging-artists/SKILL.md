---
name: merging-artists
description: Folds two or more artist rows into one — the target artist keeps every song, dependents get redirected, and the sources are soft-deleted. Covers namesake cleanup, renamed artists, and duplicate artist rows. Use when the user says "merge artists", "namesake", "duplicate artist", "same artist under different rows", or asks to consolidate artists.
---

# Merging Artists

Use this skill when the user has multiple artist rows that should be the same artist. `scripts/merge_artists.py` does the heavy lifting in one atomic transaction.

## Pre-flight

1. **Initialize the database.** Run `python scripts/init_db.py`. Creates `db/datasource.db` on first use; safe no-op afterwards.
2. **Find the duplicates.** Run `scripts/query.py duplicates --kind artist`. Returns groups of live artists sharing the same `name`.
3. **Confirm identity.** Run `scripts/query.py artist-detail --id ARTIST_ID` on each candidate to see their songs and shows. The `name_context` field (if set) is the operator's freeform disambiguator.
4. **Decide the target.** The target artist is the one that STAYS. The source artists get soft-deleted at the end.

## Run the merge

```
scripts/merge_artists.py --target-artist-id AT --source-artist-ids A1,A2,...
```

The script runs five steps inside one SQLite transaction:

1. **Reassign** every live song under a source artist to the target (AT).
2. **Find duplicate groups** — songs now under AT that share a name. Pick the winner per group by largest `(updated_at, created_at, id)`.
3. **Redirect dependents** of each losing song to its winner: `play_history.song_id`, `learning.song_id`, and `rel_show_song` (the last one cascade-deletes any row that would collide with the `UNIQUE(show_id, song_id)` constraint).
4. **Soft-delete** every losing song.
5. **Soft-delete** every source artist. The target is never touched.

Success returns a detailed envelope with every counter: `songs_reassigned`, `duplicate_groups_merged`, `songs_soft_deleted`, `play_history_redirected`, `learning_redirected`, `rel_show_song_redirected`, `rel_show_song_cascade_deleted`, `source_artists_soft_deleted`.

## Error paths

- `INVALID_INPUT` — empty source list, duplicate source IDs, or target is in the source list.
- `NOT_FOUND` — target or any source is missing or soft-deleted.
- Any failure mid-merge rolls back the whole transaction. The DB is byte-identical to the state before the call.

## Notes

- `merge_artists.py` is the only write op that may delete rows from `rel_show_song` (and only to preserve `UNIQUE(show_id, song_id)`). It does NOT hard-delete anything from `song`, `artist`, `show`, `play_history`, or `learning`.
- After the merge, re-running with the same source list returns `NOT_FOUND` because the sources are now soft-deleted.
- Every timestamp in the merge comes from `now_epoch()`.
- All scripts use only the Python standard library — no `pip install` needed.

## Command reference

Run `scripts/merge_artists.py --help` for the full flag list. The flag names above are exact.
