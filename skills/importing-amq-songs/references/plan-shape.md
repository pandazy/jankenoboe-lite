# AMQ Import — JSON Contracts

These are the exact shapes of the three handoff files in the AMQ import pipeline. See `design.md` ("Shared Contracts") in the spec for the source of truth.

## `plan.json` (output of `import_plan.py`)

```json
{
  "resolved": [
    {
      "song_id": "<uuid>",
      "show_id": "<uuid>",
      "media_url": "https://..."
    },
    {
      "song_id": "<uuid>",
      "show_to_create": {
        "name": "Foo", "vintage": "Spring 2010",
        "s_type": null, "name_romaji": "Foo Romaji"
      },
      "media_url": ""
    }
  ],
  "auto_completable": [
    {
      "artist_id": "<uuid>",
      "song_name": "Some Song",
      "show_id": "<uuid>",
      "media_url": "https://..."
    },
    {
      "artist_to_create": {"name": "New Artist"},
      "song_name": "Some Song",
      "show_to_create": {"name": "Bar", "vintage": "Fall 2015",
                         "s_type": null, "name_romaji": "Baa"},
      "media_url": ""
    }
  ],
  "ambiguous": [
    {
      "artist_name": "Yui",
      "song_name": "Again",
      "show_name": "FMA: Brotherhood",
      "vintage": "Spring 2009",
      "show_id": "<uuid>",
      "media_url": "https://...",
      "candidates": [
        {"id": "<uuid>", "name": "Yui", "name_context": "solo"},
        {"id": "<uuid>", "name": "Yui", "name_context": "FLOWER FLOWER"}
      ]
    }
  ]
}
```

## `answers.json` (input to `import_resolve.py`)

Object keyed by the stringified index of an ambiguous entry.

```json
{
  "0": {"choose_artist_id": "<uuid>"},
  "2": {"create_artist": {"name": "New Artist", "name_context": "anime band"}}
}
```

- `choose_artist_id` must match one of the entry's `candidates[*].id`.
- `create_artist` makes a new artist — it MUST be distinct from every candidate (that's the whole point).
- Entries with no answer land in `unresolved_ambiguous` in the step-2 envelope.

## `triples.json` (output of `import_resolve.py`, input to `add_play_history.py`)

```json
{
  "triples": [
    {"song_id": "<uuid>", "show_id": "<uuid>", "media_url": "https://..."}
  ],
  "artists_created": 0,
  "songs_created": 0,
  "shows_created": 0,
  "unresolved_ambiguous": []
}
```

`add_play_history.py` only cares about the `triples` array. The other fields are diagnostic.

## Raw AMQ input mapping

`--input-jsonpath` and `--input-jsonstr` also accept the raw AMQ export shape: a JSON object with a top-level `songs` array. Each song object nests its data under a `songInfo` sub-object (with show names one level deeper under `songInfo.animeNames`), and exposes the media URL as the top-level `videoUrl` on the song. Top-level siblings of `songs` (game metadata, quiz settings, export timestamps) are silently dropped.

```json
{
  "songs": [
    {
      "songInfo": {
        "artist": "...",
        "songName": "...",
        "animeNames": {"english": "...", "romaji": "..."},
        "vintage": "Spring 2024"
      },
      "videoUrl": "https://..."
    }
  ],
  "roomName": "Solo",
  "startTime": "..."
}
```

Each AMQ song object is translated to the flat five-field shape via the mapping below. For each flat key the candidate raw paths are walked in order; the first non-empty string wins.

| Raw AMQ path(s) tried, in order                                             | Flat key            | Required?              |
|-----------------------------------------------------------------------------|---------------------|------------------------|
| `songInfo.artist`, `artist_name`                                            | `artist_name`       | yes                    |
| `songInfo.songName`, `song_name`                                            | `song_name`         | yes                    |
| `songInfo.animeNames.english`, `show_name`                                  | `show_name`         | yes (English-only)     |
| `songInfo.animeNames.romaji`, `show_name_romaji`                            | `show_name_romaji`  | yes                    |
| `songInfo.vintage`, `animeVintage`, `vintage`                               | `vintage`           | yes                    |
| `videoUrl`, `audio`, `media_url`, `MP3`, `mp3`                              | `media_url`         | no — defaults to `""`  |

A missing required field aborts the whole file with `INVALID_INPUT`, naming the index and the missing flat key. The romaji rejection additionally carries `details.kind = "missing_romaji"` so the agent's Step 0 sniff and recovery branch can discriminate it from other `INVALID_INPUT` causes. English and romaji are independent fields — there is no fallback from one to the other; both are required and both land in their own DB columns (`show.name` and `show.name_romaji`). Extra AMQ-native fields per-song — `songNumber`, `correctGuess`, `videoLength`, `type`, `typeNumber`, `annId`, `fromList`, `startSample`, `composerInfo`, `arrangerInfo`, `altAnimeNames`, `altAnimeNamesRomaji`, and the like — are silently dropped, as are top-level siblings of `songs` (`roomName`, `startTime`, `quizSettings`, etc.). The flat-alias single-key paths (`artist_name`, `song_name`, `show_name`, `vintage`, `media_url`, plus `audio` / `MP3` / `mp3` / `animeVintage`) are retained as fallbacks so already-flat callers keep working.
