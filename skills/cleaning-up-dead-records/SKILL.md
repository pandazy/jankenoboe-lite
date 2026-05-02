---
name: cleaning-up-dead-records
description: Hard-deletes soft-deleted rows older than a cutoff to reclaim space in the library. Dry-runs by default; requires explicit `--confirm` to actually delete. Use when the user says "cleanup", "compact", "reclaim space", "hard delete", or asks to remove old deleted rows.
---

# Cleaning Up Dead Records

Use this skill when the user wants to free space in `db/datasource.db` by hard-deleting rows that have been soft-deleted (`status = 1`) for a while. `scripts/cleanup.py` is the only script in the app that hard-deletes rows.

## Workflow checklist

1. **Initialize the database.** Run `python scripts/init_db.py`. Creates `db/datasource.db` on first use; safe no-op afterwards.
2. **Pick a cutoff.** The user chooses an epoch-seconds timestamp `T`. Rows soft-deleted at or before `T` are eligible. Common choices:
   - "Anything older than 90 days" — compute `T = now - 90 * 86400`.
   - "Everything deleted before 2025-01-01" — compute `T` from the date.
3. **Dry-run.** Always do this first. Run `scripts/cleanup.py --before T`. No DB writes. The response has:
   - `cutoff_epoch`, `cutoff_iso_utc` — the cutoff in both formats.
   - `target_counts` — how many rows in `song`, `artist`, `show` are eligible.
   - `cascade_counts` — how many dependent rows in `rel_show_song`, `play_history`, `learning` would go with them.
   - `oldest_candidate_updated_at`, `newest_candidate_updated_at` — the age range of targets.
   - `top_cascade_samples` — up to 10 target rows with the largest dependent footprint (most rows following them into the grave).
   - `total_rows_to_hard_delete`, `executed: false`.
4. **Review with the user.** Talk through `top_cascade_samples` — these are the rows where cleanup has the biggest ripple effect. Confirm the user wants the deletion to proceed.
5. **Commit.** Run `scripts/cleanup.py --before T --confirm`. Same response shape as the dry-run, plus `executed: true` and `hard_deleted_counts`. One transaction; rolls back on any error.

## Critical rules

- `--before` is REQUIRED. Bare `cleanup.py` returns `INVALID_INPUT` and writes nothing.
- `--before` MUST be a positive integer. Zero or negative values → `INVALID_INPUT`.
- `cleanup.py` does NOT follow the artist → songs cascade. A live song under a soft-deleted artist is left alone — the operator must soft-delete the song themselves (normally this happens via `data.py delete --kind artist`, which cascades). If the DB has live songs under a soft-deleted artist, they'll survive cleanup.
- Rows with `status = 0` are never touched, period.
- Foreign keys use `rel_show_song.ON DELETE CASCADE`, so that table gets swept automatically. `play_history` and `learning` have explicit `DELETE` statements because their foreign keys don't declare cascade.

## Idempotency

Running `cleanup.py --before T --confirm` a second time with the same T (and no other writes in between) reports all-zero counts. Nothing left to delete.

## Command reference

Run `scripts/cleanup.py --help` for the full flag list. The flag names above are exact.
