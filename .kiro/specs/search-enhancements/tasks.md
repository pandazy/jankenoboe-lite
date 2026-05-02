# Implementation Plan: search-enhancements

## Overview

Convert the feature design into a series of prompts for a code-generation LLM
that will implement each step with incremental progress. Make sure that each
prompt builds on the previous prompts, and ends with wiring things together.
There should be no hanging or orphaned code that isn't integrated into a
previous step. Focus ONLY on tasks that involve writing, modifying, or testing
code.

The approach:

1. Pin the CLI surface and envelope contract with example-based integration
   tests first (RED). This forces the implementation to match the shapes in
   the design before any helper is written.
2. Wire `argparse` + `_DISPATCH` + a stub handler that emits the minimal
   envelope (filters echo, `count: 0`, `results: []`). Enough to green the
   simplest of the pinned tests.
3. Implement the query helpers in dependency order (Query 1 → artists →
   Query 2 with media via Query 3 → Query 4 with warnings), then flesh out
   the orchestrator.
4. Add the 1024-byte cap with `INVALID_INPUT`.
5. Add the remaining example tests (warnings, graduated coexist,
   empty-result, over-length, unknown-flag, read-only sanity).
6. Add the P-SE-1..P-SE-9 property tests.
7. Update `skills/searching-library/SKILL.md` per R-SE-5.
8. Final full test run + cleanup.

## Tasks

- [x] 1. Write contract-pinning example tests for the envelope and CLI surface
  - Create `tests/integration/test_search_songs.py` with the tests that define
    the CLI shape and envelope layout before any implementation exists. These
    tests will be RED and will go green as implementation lands in tasks 3–8.
  - Each test uses the `tmp_app_root` + `call_script` + `insert_*` fixtures
    already in `tests/integration/conftest.py`. No new fixtures.
  - Use `json.loads` on stdout and assert on ordered key sets via
    `list(obj.keys()) == [...]` so the tests catch drift in key order
    (R-SE-4.1, P-SE-7).
  - _Requirements: R-SE-1.1, R-SE-1.3, R-SE-1.4, R-SE-3.2, R-SE-3.9, R-SE-4.1, R-SE-4.2, R-SE-4.3, R-SE-4.5_

  - [x] 1.1 Add `test_no_filters_lists_every_live_song`
    - Seed two live songs under one live artist, zero shows, zero learning.
    - Assert exit 0, stdout parses, `envelope` keys are exactly
      `["filters", "count", "results"]` in that order.
    - Assert `filters == {"song_term": None, "show_term": None, "artist_term": None}`
      with key order `["song_term", "show_term", "artist_term"]`.
    - Assert `count == 2 == len(results)` and `results` is ordered by
      `(song.name, song.id)`.
    - _Requirements: R-SE-1.3, R-SE-3.10, R-SE-4.1, R-SE-4.2, R-SE-4.3, R-SE-4.4_

  - [x] 1.2 Add `test_envelope_top_level_shape_and_key_order`
    - Seed any live song. Run with zero filters.
    - Assert the top-level envelope key order, the inner `filters` key order,
      and that stdout ends with exactly one trailing newline.
    - _Requirements: R-SE-4.1, R-SE-4.5_

  - [x] 1.3 Add `test_song_result_shape_keys_and_order`
    - Seed one live song. Run with zero filters.
    - Assert `list(results[0].keys()) == ["song", "artist", "shows", "learning", "graduated", "warnings"]`.
    - Assert `results[0]["song"]` contains every schema column of `song`
      (`id, name, name_context, artist_id, created_at, updated_at, status`).
    - Assert `results[0]["artist"]` key set is exactly
      `{"id", "name", "name_context", "status"}`.
    - Assert `results[0]["shows"] == []`, `results[0]["learning"] is None`,
      `results[0]["graduated"] is False`, `results[0]["warnings"] == []`.
    - _Requirements: R-SE-3.2, R-SE-3.3_

  - [x] 1.4 Add `test_empty_result_set_exits_zero_with_envelope`
    - Seed one live song, then run `--song-term zzz-no-match-zzz`.
    - Assert exit 0, `count == 0`, `results == []`, `filters.song_term == "zzz-no-match-zzz"`.
    - Assert stderr is empty (no Error_Envelope on no-hit runs).
    - _Requirements: R-SE-3.9, R-SE-4.2, R-SE-4.3_

  - [x] 1.5 Add `test_rerun_same_filters_produces_byte_identical_stdout`
    - Seed a small library (2 artists × 2 songs × 1 show × 1 rel each, one
      play_history per pair).
    - Run `search-songs` twice with `--artist-term a` and compare raw stdout
      strings for byte equality.
    - _Requirements: R-SE-4.7_

- [x] 2. Wire argparse, dispatch, and stub handler for `search-songs`
  - Add the `search-songs` subparser inside `_build_parser()` in
    `scripts/query.py` with three optional flags (`--song-term`, `--show-term`,
    `--artist-term`), no positional args, `default=None`, `dest=` set
    explicitly, no `action="append"`.
  - Add a new `_cmd_search_songs(conn, args)` handler that (for now) emits the
    minimal envelope: `{"filters": {"song_term": args.song_term, "show_term":
    args.show_term, "artist_term": args.artist_term}, "count": 0, "results": []}`.
    URL-decode the terms with `_common.decode_term` for the echo so the shape
    matches tasks 3+. No DB access yet.
  - Add `"search-songs": _cmd_search_songs` to `_DISPATCH`.
  - After this task, tasks 1.2 and 1.4 above should be green; 1.1, 1.3, 1.5
    may still be RED until task 7.
  - _Requirements: R-SE-1.1, R-SE-1.2, R-SE-1.7, R-SE-1.8, R-SE-4.1, R-SE-4.2_

  - [ ]* 2.1 Write a unit-style smoke test that the subparser exists
    - Run `query.py search-songs --help` and assert exit 0 and that stdout
      mentions `--song-term`, `--show-term`, `--artist-term`.
    - _Requirements: R-SE-1.1_

- [x] 3. Implement `_find_matching_songs` (Query 1)
  - Add the helper in `scripts/query.py` near the existing private helpers
    (`_shows_for_song`, `_media_urls`).
  - Build WHERE from `_common.SPECS["song"].searchable_columns`,
    `SPECS["artist"].searchable_columns`, `SPECS["show"].searchable_columns`.
  - Always include `s.status = 0 AND a.status = 0`. Append a song-term
    `(LOWER(s.col) LIKE '%' || LOWER(?) || '%' OR ...)` block when
    `decoded["song"] is not None`. Same shape for artist.
  - For `--show-term` use `EXISTS (SELECT 1 FROM rel_show_song r JOIN show sh
    ON sh.id = r.show_id WHERE r.song_id = s.id AND sh.status = 0 AND
    (LOWER(sh.col) LIKE '%' || LOWER(?) || '%' OR ...))`.
  - `ORDER BY s.name, s.id`. All terms are bound parameters, never
    string-concatenated.
  - Return `[dict(r) for r in cur.fetchall()]` so caller reads `song_rows[i]["id"]`.
  - _Requirements: R-SE-1.4, R-SE-2.1, R-SE-2.2, R-SE-2.3, R-SE-2.4, R-SE-2.5, R-SE-2.6, R-SE-2.7, R-SE-2.8, R-SE-2.9, R-SE-2.10, R-SE-3.10_

- [x] 4. Implement `_load_artists_for_song_rows`
  - Add helper: single batch SELECT by `artist_id IN (...)` for the artist ids
    referenced by the result set, returning `{artist_id: {"id", "name",
    "name_context", "status"}}`. Empty input → empty dict.
  - _Requirements: R-SE-3.2, R-SE-3.4 (artist parity with song-detail)_

- [x] 5. Implement `_load_shows_for_songs` (Query 2) and `_batch_media_urls` (Query 3)
  - [x] 5.1 Implement `_batch_media_urls(conn, pair_set)`
    - One SELECT `DISTINCT show_id, song_id, media_url FROM play_history
      WHERE show_id IN (...) AND song_id IN (...) AND status = 0 AND
      media_url IS NOT NULL AND media_url <> '' ORDER BY media_url`.
    - Filter pairs client-side against `pair_set`. Return
      `{(show_id, song_id): [url, ...]}` with every pair pre-initialized to `[]`.
    - _Requirements: R-SE-3.4 (`media_urls`), R-SE-3.8_

  - [x] 5.2 Implement `_load_shows_for_songs(conn, song_ids, show_term)`
    - If `song_ids` is empty return `{}`.
    - Single SELECT joining `rel_show_song r` + `show sh` on `sh.id = r.show_id`,
      filtered by `r.song_id IN (...) AND sh.status = 0`.
    - `matched_filter` expression: `1` literal when `show_term is None`,
      otherwise `CASE WHEN (LOWER(sh.col) LIKE '%' || LOWER(?) || '%' OR ...)
      THEN 1 ELSE 0 END` using `SPECS["show"].searchable_columns`.
    - `ORDER BY r.song_id, sh.name, sh.id`.
    - Build `pair_set = {(row["id"], row["song_id"]) for row in rows}`,
      call `_batch_media_urls`, assemble each `Show_Entry` with key order
      exactly `[id, name, name_romaji, vintage, s_type, media_urls, matched_filter]`
      and cast `matched_filter` to Python `bool`.
    - Pre-seed `out` with `{sid: [] for sid in song_ids}` so every input id
      has a (possibly empty) list.
    - _Requirements: R-SE-3.4, R-SE-3.5, R-SE-3.8, R-SE-2.7, R-SE-2.8_

- [x] 6. Implement `_load_learning_state_for_songs` (Query 4) with warnings
  - Add module-level `_DUP_ACTIVE_MSG` constant with the text from the design.
  - Single SELECT `SELECT id, song_id, level, graduated, last_level_up_at,
    updated_at FROM learning WHERE song_id IN (...) ORDER BY graduated ASC,
    updated_at DESC, id ASC`.
  - Walk rows, classifying:
    - Active rows (`graduated == 0`) — first per song wins for
      `learning_by_song[sid]`, emit `Learning_Summary` with key order
      `[id, level, display_level, graduated, last_level_up_at, updated_at]`
      and `display_level = int(level) + 1`. Count active rows per song.
    - Graduated rows (`graduated == 1`) — set `graduated_by_song[sid] = True`.
  - Pre-seed `graduated_by_song = {sid: False for sid in song_ids}` and
    `active_count = {sid: 0 for sid in song_ids}`; empty `song_ids` → three
    empty dicts.
  - After the walk, build `warnings_by_song[sid] = [{"code":
    "duplicate_active_learning", "message": _DUP_ACTIVE_MSG}]` for every
    `sid` where `active_count[sid] >= 2`. At most one warning per song.
  - Return `(learning_by_song, graduated_by_song, warnings_by_song)`.
  - _Requirements: R-SE-3.6, R-SE-3.7, R-SE-3.11, R-SE-3.12_

- [x] 7. Wire `_cmd_search_songs` orchestrator to assemble the full envelope
  - Replace the stub body from task 2 with the full orchestrator per the
    design's "Components and Interfaces" block.
  - Compute `song_ids = [s["id"] for s in song_rows]`, call the four helpers
    in order (Query 1 → artists → Query 2 → Query 4), and assemble each
    `Song_Search_Result` in the exact key order `[song, artist, shows,
    learning, graduated, warnings]` using `.get(..., default)` for defaults.
  - Call `_common.success({"filters": {...}, "count": len(results),
    "results": results})` with `filters` in key order `[song_term, show_term,
    artist_term]` carrying the URL-decoded values (or `None` for Inactive
    filters).
  - After this task, tasks 1.1, 1.3, and 1.5 should be green.
  - _Requirements: R-SE-1.3, R-SE-1.4, R-SE-1.5, R-SE-3.1, R-SE-3.2, R-SE-3.10, R-SE-4.1, R-SE-4.2, R-SE-4.3, R-SE-4.5, R-SE-4.7_

- [x] 8. Add the 1024-byte cap and `INVALID_INPUT` behavior
  - Add module-level `_MAX_TERM_BYTES = 1024` constant in `scripts/query.py`.
  - In `_cmd_search_songs`, after URL-decoding each Active filter, check
    `len(decoded.encode("utf-8")) > _MAX_TERM_BYTES`. When violated, raise
    `_common.KnownError("INVALID_INPUT", f"{kind}-term exceeds
    {_MAX_TERM_BYTES}-byte cap after URL decode", {"flag": f"--{kind}-term",
    "max_bytes": _MAX_TERM_BYTES})`.
  - The check runs before any DB query (validation must not scan the DB per
    R-SE-1.6).
  - Inactive filters (`None`) are skipped — the cap only applies to
    Active filters.
  - _Requirements: R-SE-1.6, R-SE-4.6_

- [x] 9. Checkpoint — ensure tasks 1–8 tests pass
  - Run `pytest tests/integration/test_search_songs.py -x`. All five tests
    from task 1 should be green.
  - Run `pytest tests/integration/test_query.py -x` to confirm no existing
    `query.py` subcommand regressed (R-SE-1.2).
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Add remaining example tests covering filter semantics and warnings
  - Each sub-task appends tests to `tests/integration/test_search_songs.py`.
  - Tests reuse `insert_artist`, `insert_song`, `insert_show`, `insert_rel`,
    `insert_play_history`, `insert_learning` from `conftest.py`.

  - [x] 10.1 Add filter-semantics example tests
    - `test_single_song_term_matches_substring_case_insensitive` — seeds
      mixed-case names, asserts substring match is case-insensitive and
      returns only matching songs.
    - `test_url_decodes_term_once` — seeds a song with a space in its name,
      runs with `--song-term A%20B`, asserts the song is returned.
    - `test_empty_term_matches_every_row` — `--song-term ""` returns every
      live song under a live artist (equivalent to Zero_Filter_Behavior for
      song-term).
    - `test_repeated_flag_last_value_wins` — `--song-term a --song-term b`
      leaves only the `b`-matching set; echoed `filters.song_term == "b"`.
    - `test_show_term_requires_matching_link` — seeds a song with a link
      to show "Zeta" only; `--show-term Fma` returns zero rows; `--show-term
      Zeta` returns the song.
    - `test_show_term_inactive_keeps_songs_with_no_shows` — seeds a song
      with zero `rel_show_song` rows; Zero_Filter_Behavior returns it with
      `shows == []`.
    - `test_song_status_1_excluded` — seeds a live artist + one live + one
      soft-deleted song; Zero_Filter_Behavior returns only the live song.
    - `test_artist_status_1_excludes_song` — seeds soft-deleted artist with
      live song; song is excluded.
    - `test_soft_deleted_show_absent_from_shows_array` — seeds a song
      linked to one live show and one soft-deleted show; the song's `shows`
      array contains only the live show.
    - _Requirements: R-SE-1.4, R-SE-1.5, R-SE-1.7, R-SE-2.1, R-SE-2.5, R-SE-2.6, R-SE-2.7, R-SE-2.8, R-SE-2.9_

  - [x] 10.2 Add shape and ordering example tests
    - `test_show_entry_shape_includes_matched_filter` — asserts per-entry
      key order `[id, name, name_romaji, vintage, s_type, media_urls,
      matched_filter]`.
    - `test_shows_array_contains_every_live_linked_show` — with
      `--show-term` matching one of two linked shows, the song's `shows`
      still lists both and `matched_filter` differs per entry.
    - `test_media_urls_sorted_deduped_play_history_only` — seed two
      duplicate `play_history` URLs on one pair; assert single sorted entry.
      Seed a `rel_show_song.media_url` that doesn't exist in
      `play_history`; assert it does NOT appear in `media_urls`.
    - `test_result_order_is_song_name_then_id` — seeds three songs with
      deliberately same name but different ids; asserts the tie-break.
    - `test_filters_echo_is_decoded_value_or_null` — asserts decoded echo
      for Active filters and `None` for Inactive filters.
    - `test_count_equals_len_results` — trivial invariant.
    - _Requirements: R-SE-3.4, R-SE-3.5, R-SE-3.8, R-SE-3.10, R-SE-4.2, R-SE-4.3_

  - [x] 10.3 Add learning/graduated/warnings example tests
    - `test_learning_summary_shape_and_display_level` — seeds one active
      learning row on `level=0`; assert `display_level == 1` and key order
      `[id, level, display_level, graduated, last_level_up_at, updated_at]`.
    - `test_learning_summary_picks_highest_updated_at_among_active` —
      seeds two active rows with distinct `updated_at`; assert newer wins.
    - `test_learning_null_when_only_graduated_rows_exist` — song with
      only `graduated=1` rows → `learning is None`, `graduated is True`.
    - `test_learning_null_when_no_learning_row` — song with no learning
      rows → `learning is None`, `graduated is False`.
    - `test_graduated_flag_true_when_any_graduated_row` — mixed rows,
      `graduated` is `True`.
    - `test_graduated_flag_false_when_no_learning_row` — explicit.
    - `test_graduated_flag_and_active_learning_coexist` — re-learn flow:
      one graduated + one active row → `learning` is the active summary and
      `graduated is True`.
    - `test_warnings_empty_when_no_glitch` — song with one active row:
      `warnings == []`.
    - `test_duplicate_active_learning_emits_one_warning` — seeds two
      active rows on one song; asserts `warnings` has exactly one entry
      with `code == "duplicate_active_learning"` and `set(entry.keys()) ==
      {"code", "message"}`. Add a third active row and re-run; still
      exactly one warning.
    - `test_warning_does_not_change_exit_code_or_count` — run once with
      the glitch, once without; exit code still 0; envelope `count`
      unchanged; every other Song_Search_Result field byte-identical for
      the shared song (compare with `warnings` key dropped).
    - `test_warning_code_is_exact_string` — assert literal string
      `"duplicate_active_learning"`.
    - _Requirements: R-SE-3.6, R-SE-3.7, R-SE-3.11, R-SE-3.12_

  - [x] 10.4 Add validation and argparse error-path tests
    - `test_over_length_term_returns_invalid_input` — pass a term of
      `"a" * 1100` (> 1024 UTF-8 bytes); assert exit 1, stderr
      `Error_Envelope` with `code == "INVALID_INPUT"`, no stdout.
    - `test_unknown_flag_exits_2` — pass `--foo bar`; assert exit 2,
      stderr contains argparse "usage:", stdout empty, no JSON parsed.
    - _Requirements: R-SE-1.6, R-SE-1.8, R-SE-4.6_

  - [x] 10.5 Add the read-only sanity test
    - `test_query_py_does_not_modify_temp_db_on_search_songs` —
      snapshot `tmp_app_root/db/datasource.db` bytes (or the sqlite3
      `PRAGMA data_version` / `file size + sha256`), run a sweep of
      `search-songs` calls (zero filters, each single filter, all three
      filters), re-snapshot, assert equal.
    - _Requirements: parent R18 (read-only guarantee), R-SE-1.2_

- [x] 11. Checkpoint — ensure all example tests pass
  - Run `pytest tests/integration/test_search_songs.py -x`.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Add property-based integration tests for P-SE-1..P-SE-9
  - Create `tests/integration/property/test_search_songs_property.py`. Use
    `random.Random(seed)` with a fixed seed derived from `BASE_SEED` in
    `tests/integration/property/_helpers.py` (follow the local convention:
    `SEED = BASE_SEED + <distinct int>`), and `ITERATIONS` from the same
    module. No `hypothesis` (parent R18).
  - Add a small module-level `_build_random_library(rng, tmp_app_root, ...)`
    helper that seeds 5–30 artists, 5–80 songs, 3–20 shows, random
    `rel_show_song` links, random `play_history` rows (including empty and
    duplicate `media_url`), and random learning rows (some graduated, some
    active, occasional duplicate-active glitches). Returns the seeded
    entity ids so tests can assert DB-side truth.
  - Use `pinned_call` (not `call_script`) so `JANKENOBOE_TEST_NOW` is
    pinned — helps when seeders or helpers default `updated_at` off the
    clock.

  - [ ]* 12.1 Write property test for Active Filter Subset Is Monotone
    - **Property P-SE-1: Active Filter Subset Is Monotone (Metamorphic)**
    - For each iteration, pick a random Active filter set `F` and an
      extended set `G ⊇ F`. Run `search-songs` for both and assert
      `{r["song"]["id"] for r in G} ⊆ {r["song"]["id"] for r in F}`, and
      for every song id in both, assert `song` row, `artist` dict, and the
      ordered list of `(show_id, matched_filter)` pairs match across the
      two runs.
    - **Validates: R-SE-1.4, R-SE-2.1, R-SE-2.2, R-SE-2.3, R-SE-3.2, R-SE-3.5**

  - [ ]* 12.2 Write property test for Empty-Filter Equivalence
    - **Property P-SE-2: Empty-Filter Equivalence**
    - Assert `results(no filters)` (ordered list) equals
      `results(--song-term "")` equals `results(--artist-term "")`.
    - Assert `results(--song-term "<decoded form>")` equals
      `results(--song-term "<URL-encoded form>")` where the URL encoding
      round-trips through `urllib.parse.quote`.
    - **Validates: R-SE-1.5, R-SE-2.1, R-SE-2.2, R-SE-2.9**

  - [ ]* 12.3 Write property test for Show-Filter Requires A Matching Link
    - **Property P-SE-3: Show-Filter Requires a Matching Link**
    - Pick a random `--show-term T`. Use the temp DB (via `temp_conn`) to
      compute the set of songs expected by the design (has at least one
      live linked show satisfying Show_Match_Predicate(T)). Assert the
      op's `results` song-id set equals that expected set.
    - For every returned song, assert its `shows` list includes every
      live linked show, `matched_filter` is True iff the show's
      searchable columns substring-match T, and at least one entry has
      `matched_filter is True`.
    - Also run with `--show-term` Inactive and assert every `Show_Entry`
      has `matched_filter is True`.
    - **Validates: R-SE-2.3, R-SE-2.4, R-SE-2.7, R-SE-2.8, R-SE-3.4, R-SE-3.5**

  - [ ]* 12.4 Write property test for Soft-Delete Filtering Invariant
    - **Property P-SE-4: Soft-Delete Filtering (Invariant)**
    - Assert for every returned Song_Search_Result: `song["status"] == 0`,
      `artist["status"] == 0`, and no `Show_Entry` has a show whose
      `status == 1` in the DB.
    - Flip one returned song's status to 1 via a direct DB write and
      re-run with the same filters. Assert that song disappears and every
      other result is byte-identical to the prior run.
    - **Validates: R-SE-2.5, R-SE-2.6, R-SE-3.4 (show side), R-SE-4.7**

  - [ ]* 12.5 Write property test for Detail Consistency With `song-detail`
    - **Property P-SE-5: Detail Consistency With `song-detail`**
    - Zero-filter run over a random library. For each result `R`, call
      `query.py song-detail --id R.song.id` and assert `R.song` deep-equals
      the detail's `song`, `R.artist` deep-equals the detail's `artist`,
      and `[{k: v for k, v in e.items() if k != "matched_filter"} for e in
      R.shows]` equals the detail's `shows` (order-preserving).
    - **Validates: R-SE-3.2, R-SE-3.3, R-SE-3.4 (keys 1-6), R-SE-3.8, R-SE-3.10**

  - [ ]* 12.6 Write property test for Stable Ordering
    - **Property P-SE-6: Stable Ordering (Round-Trip-ish)**
    - Run `search-songs` twice with the same random filter set over the
      same seeded DB; assert raw stdout strings are byte-identical.
    - For every adjacent pair of results, assert
      `(a.song.name, a.song.id) < (b.song.name, b.song.id)`.
    - For every result, assert the `shows` array is ordered by
      `(show.name, show.id)`.
    - **Validates: R-SE-3.10, R-SE-4.7**

  - [ ]* 12.7 Write property test for Envelope Invariants
    - **Property P-SE-7: Envelope Invariants**
    - Assert the envelope has exactly keys `["filters", "count",
      "results"]` in order; `filters` has exactly `["song_term",
      "show_term", "artist_term"]` in order; `count == len(results)`.
    - For every result, assert key set is exactly
      `{"song", "artist", "shows", "learning", "graduated", "warnings"}`
      and order matches the design.
    - For every `Show_Entry`, assert key set is exactly
      `{"id", "name", "name_romaji", "vintage", "s_type", "media_urls",
      "matched_filter"}`.
    - Assert every `graduated` is `True` or `False` (use
      `isinstance(result["graduated"], bool)`), never `None`, never
      omitted. Assert every `warnings` is a `list`, never `None`, never
      omitted, and each entry key set is exactly `{"code", "message"}`.
    - **Validates: R-SE-3.2, R-SE-3.4, R-SE-3.11, R-SE-3.12, R-SE-4.1, R-SE-4.2, R-SE-4.3**

  - [ ]* 12.8 Write property test for Graduated Flag and Active Learning Summary
    - **Property P-SE-8: Graduated Flag And Active Learning Summary**
    - For every song `S` in `results(no filters)`, use `temp_conn` to
      fetch every learning row for `S.song.id`.
    - Assert `S.graduated == any(r["graduated"] == 1 for r in rows)`.
    - Assert `(S.learning is not None) == any(r["graduated"] == 0 for r
      in rows)`.
    - When `S.learning is not None`: assert `S.learning["graduated"] == 0`,
      and `S.learning["id"]` equals the id of the active row with the
      highest `updated_at` (tie-break `id ASC`).
    - Seed at least one re-learn case (graduated + active) and one
      no-learning case per iteration so both branches are hit.
    - **Validates: R-SE-3.6, R-SE-3.7, R-SE-3.11**

  - [ ]* 12.9 Write property test for Duplicate-Active-Learning Warning
    - **Property P-SE-9: Duplicate-Active-Learning Warning**
    - For every song `S` in `results(F)`, assert `S.warnings` contains a
      Warning with `code == "duplicate_active_learning"` iff the song has
      two or more `graduated = 0` learning rows. Otherwise that code must
      not appear in `S.warnings`. At most one such Warning per result.
    - Double-run invariant: run the op on the DB as seeded (with the
      glitch), then delete the extra active rows via `temp_conn` and re-run.
      For each shared song, assert every field except `warnings` is
      byte-identical between the two runs. Assert exit code is still 0 in
      both runs and envelope `count` is unchanged.
    - Assert every `S.warnings` is a list (empty `[]` when no glitches).
    - **Validates: R-SE-3.6, R-SE-3.12**

- [~] 13. Checkpoint — ensure property tests pass
  - Run `pytest tests/integration/property/test_search_songs_property.py -x`.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Update `skills/searching-library/SKILL.md` per R-SE-5
  - Add one new bullet to the "Checklist: available ops" list for
    `search-songs`. The bullet SHALL name the three filter flags
    (`--song-term`, `--show-term`, `--artist-term`), the AND-over-active-
    filters rule, the Zero_Filter_Behavior ("no flags returns every live
    song with related details"), and the envelope top-level shape
    (`{filters, count, results}`). Detail level MUST match the existing
    `search` and `*-detail` bullets.
  - Add a short companion paragraph under "Pattern: when the user gives a
    name, not an ID" saying `search-songs` is the right op when the user
    asks a combined question ("songs in show X by artist Y") — it returns
    the detail-shaped rows directly so the follow-up `*-detail` calls are
    unnecessary.
  - Do not remove or rewrite any existing bullet or paragraph.
  - _Requirements: R-SE-5.1, R-SE-5.2, R-SE-5.3, R-SE-5.4_

  - [ ]* 14.1 Add a content-assertion test for the SKILL.md update
    - Add `test_skill_md_lists_search_songs` to
      `tests/integration/test_search_songs.py` (or a new unit test file).
    - Read `skills/searching-library/SKILL.md` and assert it contains the
      literal strings `search-songs`, `--song-term`, `--show-term`,
      `--artist-term`. Assert the existing bullets for `search`,
      `batch-get`, `duplicates`, `shows-by-artist-ids`,
      `songs-by-artist-ids`, `list-learning`, `song-detail`,
      `artist-detail`, `show-detail`, `learning-detail` are still present.
    - _Requirements: R-SE-5.1, R-SE-5.3_

- [x] 15. Final checkpoint — full test suite and cleanup
  - Run the complete test suite (`pytest` from repo root, or
    `tests/run.sh` if that's the project's convention).
  - Confirm every `search_songs`-related example and property test passes
    and no existing test regressed.
  - Delete any scratch files or commented-out debug code introduced in
    earlier tasks. The final diff touches only `scripts/query.py`,
    `tests/integration/test_search_songs.py`,
    `tests/integration/property/test_search_songs_property.py`, and
    `skills/searching-library/SKILL.md`.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP.
  All nine property tests (12.1..12.9) are marked optional per the
  "test sub-tasks may be optional" convention, but skipping them leaves
  P-SE-1..P-SE-9 unverified — prefer to implement them.
- Core implementation tasks (2–8, 14) are NOT marked optional.
- Each task references specific sub-requirements (e.g. `R-SE-3.4`) for
  traceability rather than just the parent user story.
- Every property sub-task names its property and lists the exact
  requirements clauses it validates, matching the design's
  "Correctness Properties" section.
- Checkpoints (9, 11, 13, 15) gate forward progress so a failing helper
  is caught before the next layer lands on top of it.
