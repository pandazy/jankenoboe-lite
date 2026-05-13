---
name: reviewing-songs
description: Guides a spaced-repetition review session for anime songs. Lists due learning records, renders an HTML review page, and records the outcome of each song (leveled up, graduated, or leveled down when forgotten). Use when the user says "review", "what's due", "level up", "graduate", "forgot", "level down", or asks to run a review session.
---

# Reviewing Songs

Use this skill when the user is sitting down to review their anime song queue. The app stores review state in `db/datasource.db`. Every step below is a call to an existing script under `scripts/`.

## Checklist

1. **Initialize the database.** Run `python scripts/init_db.py`. Creates `db/datasource.db` on first use; safe no-op afterwards.
2. **See what's due.** Run `scripts/learning.py due` (with `--offset 0` by default). The response is a JSON array of learning records ready for review. Fields include `id`, `song_id`, `song_name`, `level`, `display_level`, `wait_days`, `last_level_up_at`, `updated_at`, `graduated`.
3. **Render the review page.** Run `scripts/review.py song-review`. The script writes an HTML page to `App_Root/output/review_<EPOCH>.html` (one file per run — previous pages stay) and prints `{"path": "<abs path>", "due_count": N}`. Open the path in a browser for the user.
4. **For each song the user reviews:**
   - **Memorised it this time.** Run `scripts/learning.py levelup --ids L1,L2,...`. This bumps `level` by 1 (capped at the max level; at the cap it sets `graduated = 1`) and updates `last_level_up_at`.
   - **Fully memorised — done.** Run `scripts/learning.py graduate --ids L1,L2,...`. This sets `graduated = 1`. A second call on the same id is a no-op.
   - **Forgot it — drop me back to level N.** Run `scripts/learning.py leveldown --ids L1,L2,... --to-level N`. The target `N` is a stored level (0-indexed) and MUST be strictly below each record's current level. The op sets `level = N`, resets `last_level_up_at` to `now_epoch`, and updates `updated_at`, so the next review is scheduled `level_up_path[N]` days from the forget event (not from the original level-up time). Ask the user which level to drop to when they say they forgot a song.
5. **Need more detail on one song.** Run `scripts/query.py learning-detail --id LEARNING_ID`. Returns the learning row plus its song, artist, and shows (with the song's `media_urls`).

## Notes

- Do not edit learning rows by hand. The only write paths are `learning.py batch`, `levelup`, and `graduate`.
- Display the user-facing level (`display_level`, 1-indexed), not the stored `level`. `review.py` already does this in the HTML page.
- If `learning.py levelup` returns `code = "ALREADY_GRADUATED"`, one of the ids in the call points at a graduated row. Drop it from the list and re-run.
- If `learning.py leveldown` returns `code = "ALREADY_GRADUATED"`, one of the ids points at a graduated row — leveldown does NOT un-graduate rows. Drop the offending id from the call. To re-engage a graduated song, run `scripts/learning.py batch --song-ids S1,S2,...` instead, which inserts a fresh row at the re-learn level (8 displayed). If `leveldown` returns `code = "INVALID_INPUT"` with an `offenders` array, the requested `--to-level` was not strictly below those rows' current levels — pick a lower target and re-run.
- A learning record whose song or artist has been soft-deleted returns `NOT_FOUND` on `learning-detail`. Suggest `cleanup.py` (separately) to the user rather than trying to patch around it here.
- All scripts use only the Python standard library — no `pip install` needed. Run them with `python scripts/<name>.py ...`.

## Command reference

Every script prints JSON on stdout for success and a JSON error envelope on stderr for failure. For the full flag list on any command, run it with `--help`. No flags have been reinvented here.
