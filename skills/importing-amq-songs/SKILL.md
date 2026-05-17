---
name: importing-amq-songs
description: Imports Anime Music Quiz (AMQ) JSON dumps into the library as `play_history` rows, creating any missing artists/songs/shows along the way. Walks a three-step pipeline: plan → resolve ambiguous artists → add play history. Use when the user mentions "AMQ", "import", "Anime Music Quiz", "play history dump", or asks to bring songs from AMQ into their library.
---

# Importing AMQ Songs

Use this skill when the user has an AMQ JSON file they want to fold into `db/datasource.db`. The import is a three-step pipeline — each step is one script under `scripts/`. The pipeline is idempotent on artists, songs, shows, and `rel_show_song`: rerunning it only adds new `play_history` rows. See `references/plan-shape.md` for the full JSON contract.

## Input shape

`import_plan.py` accepts two JSON shapes, via four mutually-exclusive input flags.

**Raw AMQ export shape** (recommended — the file AMQ itself produces). A JSON object with a top-level `songs` array; sibling game-metadata keys are dropped silently.

```json
{
  "songs": [
    {"songArtist": "...", "songName": "...",
     "animeEnglishName": "...", "animeRomajiName": "...",
     "vintage": "Spring 2024", "audio": "https://..."}
  ],
  "quizSettings": {}
}
```

**Flat shape** (legacy). A JSON array of six-field objects; extras are ignored. `media_url` is optional — every other key is required.

```json
[
  {"artist_name": "...", "song_name": "...",
   "show_name": "...", "show_name_romaji": "...",
   "vintage": "Spring 2024", "media_url": "https://..."}
]
```

See `references/plan-shape.md` for the AMQ → flat field mapping. The romaji is required on every entry on both shapes — see "Step 0 — Shape sniff" below for what to do when the file's romaji is at a different path or missing.

**One AMQ JSON file per run.** The input flags take a single path or a single JSON string, not a list or a glob. If the user hands you multiple AMQ dumps, run the full three-step pipeline once per file (or merge the arrays into one JSON first). Same goes for `import_resolve.py --plan` and `add_play_history.py --input` — each accepts exactly one file at a time.

## Checklist

1. **Initialize the database.** Run `python scripts/init_db.py`. Creates `db/datasource.db` on first use; safe no-op afterwards.

2. **Step 0 — Shape sniff.** Read-only. Run before `import_plan.py` to catch AMQ-shape drift (specifically the romaji field) before the API surface rejects with `INVALID_INPUT details.kind = "missing_romaji"`.
   - Read the user's AMQ JSON, walk each `songs[i]`, and check that `songInfo.animeNames.romaji` is a non-empty string.
   - If every entry has a non-empty romaji at the canonical path, Step 0 is silent — proceed straight to Step 1.
   - If at least one entry fails, classify against the named hypotheses:
     - **Hypothesis A — Shape drift.** Every entry has a `songInfo.animeNames` sub-object but `animeNames` has no `romaji` key (or the value is empty/null), AND a sibling key on `animeNames` holds a plausible romaji value. Report the actual key list at `animeNames` for one affected entry and propose the candidate sibling path.
     - **Hypothesis B — Truncated / malformed entries.** At least one `songs[i]` is missing the `songInfo` container, or `songInfo` is missing `animeNames` entirely. Report indices and the entry's top-level keys.
     - **Hypothesis C — Genuinely-empty romaji.** `songInfo.animeNames.romaji` exists but is empty/null on at least one entry. Report indices.
   - Surface the failure mode verbatim and ask the user to confirm before doing anything else:
     ```
     Step 0 — Shape sniff result: FAILED for N entries.

       Hypothesis A — Shape drift (most likely):
         affected indices: [0, 1, 4, 5]
         songInfo.animeNames keys observed: ["english", "romajiTitle"]
         candidate recovery path: songInfo.animeNames.romajiTitle
         sample value at songs[0].songInfo.animeNames.romajiTitle:
           "Wooser no Sono Higurashi: Kakusei-hen"

       Confirm? Type "y" to accept Hypothesis A and recover via
       scripts/data.py create. Type "n" to abort and inspect the file.
     ```
   - On `n`, stop. On `y`, see "Manual recovery" below.

3. **Step 1 — plan.** Run `scripts/import_plan.py --input-jsonpath amq.json --output plan.json`. Read-only. The summary on stdout has `resolved_count`, `auto_completable_count`, `ambiguous_count`, and `path`.
   - `--input-jsonpath PATH` — recommended for files. Accepts both the raw AMQ export and the flat array.
   - `--input-jsonstr '<json>'` — inline JSON string, same two shapes. Useful for piped `jq` output.
   - `--input-array '<json>'` — inline flat-only channel for programmatic callers; rejects raw AMQ on purpose.
   - `--input PATH` (and the positional path) — legacy flat-only surface, kept for compatibility with existing scripts.
   - Buckets returned in `plan.json`:
     - `resolved` — the song already exists. Nothing to confirm.
     - `auto_completable` — the artist is unambiguous (one match, or none → create). Nothing to confirm.
     - `ambiguous` — two or more live artists share the `artist_name`. The user MUST pick one per entry.

4. **Review the ambiguous bucket with the user.** Open `plan.json` and look at each entry's `candidates` (list of `{id, name, name_context}`). For each one, ask the user which artist it should be.

5. **Write `answers.json`.** Keyed by the stringified index of the ambiguous entry. Shape:

   ```json
   {
     "0": {"choose_artist_id": "<existing-artist-uuid>"},
     "2": {"create_artist": {"name": "...", "name_context": "..."}}
   }
   ```

   - `choose_artist_id` — pick one of the `candidates[*].id` values from the plan.
   - `create_artist` — the user wants a brand new artist distinct from all candidates.

6. **Step 2 — resolve.** Run `scripts/import_resolve.py --plan plan.json --answers answers.json --output triples.json`. Creates any missing artists, songs, and shows (idempotent on all three — existing live rows are reused). Response: `{triples_count, artists_created, songs_created, shows_created, unresolved_ambiguous_count, path}`. `unresolved_ambiguous_count > 0` means at least one ambiguous entry had no answer in `answers.json`.

7. **Step 3 — add play history.** Run `scripts/add_play_history.py --input triples.json`. Inserts one `play_history` row per triple and upserts `rel_show_song`. Response: `{play_history_created, rel_show_song_created}`. If any triple points at a missing or soft-deleted id, the whole batch aborts with `NOT_FOUND` and writes nothing.

## Manual recovery (after Step 0 confirms a sniff failure)

When the user types `y` in response to the Step 0 report, extract the romaji from the candidate path the sniff identified (or, in the genuinely-empty case, ask the user to supply one) and insert each affected show via `scripts/data.py create --kind show`:

```
python scripts/data.py create --kind show '{
  "name": "<English title from songInfo.animeNames.english>",
  "name_romaji": "<romaji extracted from the candidate path>",
  "vintage": "<vintage from songInfo.vintage>",
  "s_type": null
}'
```

Then re-run Steps 1–7. `import_plan.py`'s existence query (`name = ? AND vintage = ?`) hits the freshly-created show row and emits a `show_id` instead of a `show_to_create` block, so the romaji-on-the-AMQ-JSON requirement is bypassed for those entries via the existing-show path. No new flag, no new script.

## Gotchas

- **Always rerun from step 1** when a previous run didn't make it all the way through. The fresh plan sees any rows step 2 just created.
- `add_play_history.py` does NOT dedupe `play_history`. Running the pipeline twice on the same input adds play_history rows twice (once per run) — that's the design. It's how multiple plays of the same song get logged.
- `SONG_INVARIANT_VIOLATION` on step 1 means one artist has two live songs with the same name. Soft-delete the extras via `scripts/data.py delete --kind song --id ...` before retrying.
- Every string in the input is URL-decoded once before DB lookups. Encoded values in the JSON file will match unencoded rows in the DB.

## Command reference

Run each script with `--help` for the full flag list. The flag names above are exact.

## References

- `references/plan-shape.md` — the exact JSON contract for `plan.json`, `answers.json`, and `triples.json`.
