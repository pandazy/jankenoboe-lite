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
        "s_type": null, "name_romaji": null
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
                         "s_type": null, "name_romaji": null},
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
