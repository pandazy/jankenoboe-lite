---
name: adding-songs-to-learning
description: Builds the spaced-repetition learning queue by adding songs to the `learning` table in batches. Helps find the right songs first, then hands them to `learning.py batch`. Use when the user says "add to learning", "queue songs", "batch add", or asks to start learning new songs.
---

# Adding Songs to Learning

Use this skill when the user wants to put one or more songs into the review queue. Learning state lives in the `learning` table in `db/datasource.db`. Every command below is a call to an existing script under `scripts/`.

## Checklist

1. **Initialize the database.** Run `python scripts/init_db.py`. Creates `db/datasource.db` on first use; safe no-op afterwards.
2. **Find the songs.** Run one of:
   - `scripts/query.py search --kind song --term "<text>"` — case-insensitive substring search over `name` and `name_context`.
   - `scripts/query.py songs-by-artist-ids --artist-ids A1,A2,...` — every live song owned by one or more artists.
3. **Confirm the user picked the right songs.** If the names are ambiguous, look them up with `scripts/query.py song-detail --id SONG_ID` for the full context (artist, shows, media URLs).
4. **Add them to the queue.** Run `scripts/learning.py batch --song-ids S1,S2,...`. The response is `{"inserted": [...], "skipped": [...], "not_found": [...]}`. For each input song:
   - **New** — no prior learning row exists. Inserts a fresh row at stored level 0 (displayed as level 1).
   - **Re-learning** — every prior learning row is graduated. Inserts a fresh row at stored level 7 (`RE_LEARN_LEVEL`), displayed as level 8.
   - **Skipped** — at least one non-graduated row already exists for this song. No new row is inserted; the existing row keeps its state.
   - **Not found** — the song id is missing or soft-deleted. No row is inserted for it.
5. **Report back** with the counts from the three buckets so the user knows what landed.

## Notes

- `batch` is idempotent on songs that already have a non-graduated row. Running it twice is safe.
- Timestamps come from `now_epoch()`. Tests pin the clock via the `JANKENOBOE_TEST_NOW` environment variable; in normal use you don't set it.
- All scripts run on stdlib Python 3.10+. No `pip install` needed.

## Command reference

For flags and output shapes, run each script with `--help`. The flag names above are exact.
