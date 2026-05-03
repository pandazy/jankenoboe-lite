# Skills Index

This library tracks and reviews anime songs. An AI agent drives it through six skills covering three kinds of work: **querying** the library (search, duplicates, detail views), **memorising** songs via spaced-repetition review sessions, and **managing data** (AMQ imports, artist merges, cleanup). A user's request maps to one or two skills below — pick by user intent, then follow the link to that skill's `SKILL.md` body for the exact steps.

## If a script fails, report it — don't patch it

**The `scripts/` tree is the shipped runtime. Do not edit it in response to an error, crash, or unexpected output.** When a script throws an exception, emits an `INVALID_INPUT` / `INTERNAL_ERROR` envelope, or returns something that doesn't look right, tell the user what happened — include the error code, the full error message, and the input you passed — and stop there. The user decides what to do next: retry with different input, file a bug, ship a fix.

Editing `scripts/` from inside a user task hides the problem, couples the fix to that one session, and can silently violate invariants the rest of the scripts depend on. The runtime is stdlib-only and versioned; it changes through the release pipeline, not through session-level patches.

## Using Dedicated Commands

When a dedicated command exists for what you want to do, use it. `data.py` CRUD (`create`, `update`, `delete`, `bulk-reassign`) is a last-resort fallback for tasks no dedicated command covers.

The dedicated commands preserve invariants that raw CRUD does not. For example, `learning.py graduate --ids <id>` sets `graduated = 1` *and* pins `level = MAX_LEVEL` — the invariant `graduated ↔ level = MAX_LEVEL` holds. `data.py update --kind learning --id <id> --data '{"graduated": 1}'` succeeds as SQL but violates that invariant, leaving the row in a state downstream reads misinterpret.

The dedicated commands for each skill are listed in the Skills table below. If the task you need matches one of those skills, start there.

## Common Workflows

### Adding entries to the library

- The user has an AMQ JSON export and wants to fold it in → [importing-amq-songs](importing-amq-songs/SKILL.md). Three-step pipeline (plan → resolve → add). The operator answers disambiguations between plan and resolve; everything after that is idempotent.
- The user wants to start learning specific songs → [adding-songs-to-learning](adding-songs-to-learning/SKILL.md). Covers three cases the `learning.py batch` response reports back:
  - **New** — no prior learning row for the song. Inserts at stored level 0.
  - **Re-learning** — every prior row is graduated (the user previously finished the song and wants another pass at it). Inserts a fresh row at stored level 7 (`RE_LEARN_LEVEL`), so each learn-graduate cycle leaves its own row in the history.
  - **Skipped** — a non-graduated row already exists. No new row; the existing one keeps its state. Running `batch` twice on the same song is a safe no-op.

### Memorising songs

- The user wants to review what's due → [reviewing-songs](reviewing-songs/SKILL.md). Runs the due query, renders `output/review_<EPOCH>.html`, and records each song's outcome (`learning.py levelup` or `graduate`).
- Wait days grow with each level-up — a song seen seven times sits quietly for a week before the next check, a song at the max level graduates out of the queue entirely. See the spaced-repetition illustration in the repo-root `README.md` for the full curve across 20 levels.

### Exploring the library

- The user is searching, hunting duplicates, or cross-referencing shows and artists → [searching-library](searching-library/SKILL.md). Read-only. Covers `search`, `duplicates`, `songs-by-artist-ids` / `shows-by-artist-ids`, `list-learning`, and the four `*-detail` endpoints.

### Advanced data management

- The user wants to merge duplicate or namesake artists into one → [merging-artists](merging-artists/SKILL.md). Redirects dependents, soft-deletes the sources. Use `query.py duplicates --kind artist` first to find candidates.
- The user wants to hard-delete soft-deleted rows older than a cutoff → [cleaning-up-dead-records](cleaning-up-dead-records/SKILL.md). Dry-run first, then `--confirm`.

## Skills

| Skill | When to use |
|---|---|
| [adding-songs-to-learning](adding-songs-to-learning/SKILL.md) | Build the review queue: find songs, then `learning.py batch`. Handles new / re-learn / skipped cases. |
| [reviewing-songs](reviewing-songs/SKILL.md) | Run a review session: list what's due, render the HTML page, level up or graduate each song. |
| [searching-library](searching-library/SKILL.md) | Explore the library read-only: search, find duplicates, cross-reference shows/artists, detail views. |
| [importing-amq-songs](importing-amq-songs/SKILL.md) | Fold an Anime Music Quiz JSON dump into the library through the three-step plan → resolve → add pipeline. |
| [merging-artists](merging-artists/SKILL.md) | Consolidate duplicate or namesake artists into one, redirect dependents, soft-delete the sources. |
| [cleaning-up-dead-records](cleaning-up-dead-records/SKILL.md) | Hard-delete soft-deleted rows older than a cutoff. Dry-run first, then `--confirm`. |

Every skill assumes the runtime is Python 3.10+ with only the standard library, and that the database lives at `App_Root/db/datasource.db`. Scripts are called as `python scripts/<name>.py ...`. Run any script with `--help` for its exact flag list.

Every skill begins by running `python scripts/init_db.py`, which creates `db/datasource.db` on first use and is a safe no-op afterwards — so Claude never hits `DB_NOT_FOUND` on a fresh deploy regardless of which skill is invoked first.
