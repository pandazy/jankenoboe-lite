# Implementation Plan

This task list translates `design.md` and `requirements.md` into an
executable plan for two coordinated improvements to the Review_Page:
the Polish_Scope CSS rewrites and the YouTube-search fallback
Search_Links. Both land entirely in `scripts/review_template.html`.
Because this is a feature (not a bugfix) the ordering is
"smallest-safe-slice-first" — template edits first, then the new
bytes-in-template regression test, then verification of the existing
suite, then the final `make check` gate, then the release-note bullet,
then an instructional commit entry.

**Framing invariants** (copied from the spec — these are the hard
boundaries for the release):

- **R-No-Python is the hard boundary.** Only ONE Python file gets
  touched in this release: `tests/integration/test_review.py`, and
  only to ADD one new test function. Every other Python file stays
  byte-identical.
- **Diff is exactly three files**: `scripts/review_template.html`
  (template edit), `tests/integration/test_review.py` (one new test
  function added), `release.md` (one bullet under v0.1.4).
- **PBT iteration count stays pinned** at `ITERATIONS = 5` in
  `tests/integration/property/_helpers.py` — no property-test changes
  at all in this release.
- **Coverage floor ≥ 90%** (enforced by `./tests/run.sh` via
  `.coveragerc`).
- **No git commit / tag / push** from this task file — the user
  handles those.
- Ships as **v0.1.4** via the existing release pipeline.

**Out of scope, do not touch**:

- `scripts/review.py`, `scripts/_common.py`, `scripts/learning.py`,
  any other script.
- `tests/integration/_dom_sim.py` — the simulator does NOT mirror the
  new anchors; simulator/browser divergence on the Search_Link surface
  is deliberate and accepted.
- `tests/integration/property/test_escape_injection_property.py` —
  existing assertions cover the new link surface transitively (per
  design Decision D6).
- Any other existing test in `tests/integration/test_review.py` —
  this release only ADDs one new test function, it does NOT edit any
  existing test.
- `skills/` — the feature is discoverable in the rendered page
  itself; no skill-doc update.
- `Makefile`, `.coveragerc`, `pyproject.toml`, CI / release config.

## Template edits

Live code changes land in `scripts/review_template.html` in two
coherent passes — the Inline_Script additions (Task 1) and the
Polish_Scope CSS rewrites (Task 2). The sub-task numbering is for
readability; each parent task commits as one logical change. No other
file in the repo is touched by Tasks 1 and 2.

- [x] 1. Add `renderSearchLink` helper and its two call sites to the Inline_Script in `scripts/review_template.html`
  - Parent task. All four sub-tasks land together so the helper and
    both call sites are introduced in a single coherent edit to the
    Inline_Script; the template is never in a half-wired state where
    the helper exists but no one calls it (or a call site references
    a helper that isn't defined yet).
  - **File touched**: `scripts/review_template.html` only.
  - Reference: `design.md` > "Low-Level Design" > "The new
    Inline_Script additions" for the exact helper body and the exact
    call-site placement.

  - [x] 1.1 Add the `renderSearchLink(songName, targetName, targetKind)` helper body
    - Add the function next to `copyButton` in the Inline_Script's
      function list, using the exact shape from `design.md` >
      "Low-Level Design" > "The new Inline_Script additions" >
      "New helper".
    - The helper MUST construct an `<a>` with `class="yt-search"`,
      `href` set via
      `'https://www.youtube.com/results?search_query=' + encodeURIComponent(songName + ' ' + targetName)`,
      `target="_blank"`, `rel="noopener noreferrer"`, and an
      `aria-label` that is
      `'Search YouTube for ' + songName + ' by ' + targetName` when
      `targetKind === 'artist'` and
      `'Search YouTube for ' + songName + ' in ' + targetName`
      otherwise.
    - The inline Globe_Icon SVG child MUST be built via
      `document.createElementNS('http://www.w3.org/2000/svg', ...)`
      for the `svg`, `circle`, `ellipse`, and `line` elements — never
      via `innerHTML`, `outerHTML`, or `insertAdjacentHTML`. The SVG
      carries `class="yt-search-icon"`, `width="16"`, `height="16"`,
      `viewBox="0 0 16 16"`, `aria-hidden="true"`, and
      `focusable="false"`, and every stroked child uses
      `stroke="currentColor"`.
    - The helper returns the built `<a>` element; it does not append
      it to the DOM. Callers append.
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3, 6.3_

  - [x] 1.2 Thread `songName` into `renderShowBlock` as a second parameter
    - Change the existing `renderShowBlock(sh)` signature to
      `renderShowBlock(sh, songName)` so the show-level Search_Link
      has the enclosing Song_Card's song name in scope.
    - Update the caller inside `renderSong`'s show loop to pass
      `s.song_name` as the second argument:
      `renderShowBlock(sh, s.song_name)`. No other caller exists.
    - _Requirements: 3.2_

  - [x] 1.3 Add the artist-level Search_Link call site in `renderSong`
    - After the existing `artist.appendChild(copyButton(s.artist_id))`
      line (and after the optional `.name-context` span if present),
      append the Search_Link:
      `artist.appendChild(renderSearchLink(s.song_name, s.artist_name, 'artist'));`.
    - The Search_Link is the last child of the `<div class="artist">`
      — after the artist name span, any `.name-context` span, and the
      existing copy button. The copy button's position does not shift.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 1.4 Add the show-level Search_Link call site in `renderShowBlock`
    - After the existing `show.appendChild(copyButton(sh.show_id))`
      line (and after the optional `.show-meta` span) AND BEFORE the
      `<ul class="links">` that renders `sh.media_urls`, append:
      `show.appendChild(renderSearchLink(songName, sh.show_name, 'show'));`.
    - The existing per-show `media_urls` list continues to render
      unchanged — the Search_Link is an additional sibling, not a
      replacement.
    - **Shipped-form note.** During execution, `renderShowBlock` was
      refactored to build an inner `<div class="show-head">` flex
      wrapper that holds the show name + copy button + optional
      meta + show-level Search_Link on one row; the `<ul
      class="links">` is appended to the enclosing `.show-block`
      (sibling of `.show-head`) so the links stack below the header
      rather than trail after it. The show-meta separator also
      changed: the Inline_Script now emits `'· ' + extras.join(' ·
      ')` instead of `' — ' + extras.join(', ')`, so a full meta
      reads as `· romaji · 2015 · TV`. The Search_Link itself still
      lands inside the header row (now as a child of `.show-head`
      rather than a direct child of `.show-block`), and the
      `media_urls` list still renders unchanged.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 2. Apply Polish_Scope CSS rewrites to `<style>` in `scripts/review_template.html`
  - Parent task. All six sub-tasks land together in the same `<style>`
    block. In collaboration with the user the visual treatment grew
    beyond the original Polish_Scope bullets into a full card +
    chip layout; the sub-tasks below describe what actually landed.
    No pre-existing selector is removed — every v0.1.3 class name is
    still referenced; new selectors (`.show-head`, `.yt-search*`,
    plus `li[data-level]::before` and `.links li::before`) are added
    alongside.
  - **File touched**: `scripts/review_template.html` only (the same
    file as Task 1 — these two parent tasks land in the same commit).

  - [x] 2.1 Rewrite body / h1 / ol for the card-layout baseline
    - Body gets `max-width: 820px`, page background `#fafbfc`, text
      color `#1a1a1a`, `line-height: 1.5`.
    - `h1` tightens to `font-size: 1.8em; letter-spacing: -0.01em`.
    - The enclosing `<ol>` gets `list-style-position: outside;
      padding: 0; margin: 0` plus a `counter-reset: song-counter` so
      the card CSS counter has a host to increment.
    - _Requirements: 1.1_

  - [x] 2.2 Rewrite `li[data-level]` as a white card with shadow, hover-lift, and CSS-counter numbering
    - Cards render as `display: block` panels with
      `background: #ffffff`, `1px solid #e5e7eb` border,
      `border-radius: 10px`, `padding: 1em 1.2em`,
      `margin: 0 0 0.9em 0`, and
      `box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04)`.
    - Hover deepens the shadow to
      `0 2px 8px rgba(15, 23, 42, 0.08)` and darkens the border to
      `#d1d5db`, with a 0.15s transition on `box-shadow` and
      `border-color`.
    - A CSS counter `::before` pseudo (`counter-increment:
      song-counter; content: counter(song-counter) "."`) in
      `#9ca3af` replaces the default `<ol>` bullet.
    - _Requirements: 1.1, 1.2_

  - [x] 2.3 Rewrite `.level` as a fully-rounded pastel pill
    - `background: #eff6ff`, `color: #1d4ed8`,
      `border: 1px solid #dbeafe`, `border-radius: 999px`,
      `font-weight: 600`, `font-size: 0.78em`, padding
      `0.15em 0.65em`, `letter-spacing: 0.01em`.
    - Moves the level indicator from a solid-blue badge to a soft
      tag that reads quieter than the song title.
    - _Requirements: 1.3_

  - [x] 2.4 Add the Show_Chip treatment (new `.show-block` + `.show-head` + `.show-name` + `.show-meta` styling)
    - `.show-block` renders as a chip: `display: block`, top margin
      `0.5em`, `padding: 0.55em 0.8em`, `background: #f9fafb`,
      `1px solid #e5e7eb` border, `border-left: 3px solid #a5b4fc`
      (indigo accent bar), `border-radius: 6px`, `color: #1f2937`.
    - New `.show-head` selector added: `display: flex; flex-wrap:
      wrap; align-items: center; gap: 0.35em` — the inner flex
      wrapper that `renderShowBlock` builds to hold name + copy +
      meta + globe on one line.
    - `.show-name` reads as `font-weight: 600; color: #111827;
      font-size: 0.98em`.
    - `.show-meta` reads as `color: #6b7280; font-size: 0.88em;
      font-weight: 400; font-style: normal; text-transform: none;
      letter-spacing: normal` (the explicit resets defend against
      inherited transforms from a parent selector).
    - `.shows-section` becomes an uppercased label:
      `text-transform: uppercase; letter-spacing: 0.04em;
      font-size: 0.85em; font-weight: 500; color: #6b7280; margin-top:
      0.75em`. The Inline_Script writes the plain string `"Shows"`
      with no trailing colon; the uppercased appearance is CSS-only.
    - _Requirements: 1.4, 1.5, 1.6_

  - [x] 2.5 Rewrite `.links` as an arrow-prefixed stacked list (no disc bullets)
    - `.links`: `display: block; margin: 0.4em 0 0 0; padding: 0;
      list-style: none; font-size: 0.9em`.
    - `.links li { padding: 0.1em 0 }`.
    - `.links li::before { content: "↳ "; color: #9ca3af;
      margin-right: 0.15em }` — arrow glyph replaces the default
      disc bullet.
    - `.links a { color: #2563eb; text-decoration: none }` with
      hover underline.
    - _Requirements: 1.7_

  - [x] 2.6 Add `.yt-search` as a 22×22 indigo circle anchor and refresh the copy-button baseline
    - Append to the same `<style>` block:
      ```css
      .yt-search { display: inline-flex; align-items: center;
                   justify-content: center;
                   width: 22px; height: 22px;
                   color: #6366f1; text-decoration: none;
                   border-radius: 50%;
                   line-height: 1;
                   vertical-align: middle;
                   transition: background 0.12s ease,
                               color 0.12s ease; }
      .yt-search:hover { background: #eef2ff; color: #4338ca; }
      .yt-search:focus-visible { outline: 2px solid #6366f1;
                                 outline-offset: 2px; }
      .yt-search-icon { display: block; }
      ```
    - Copy-button baseline rewritten to match the card palette:
      `border: 1px solid #e5e7eb; background: #ffffff;
      color: #6b7280; border-radius: 4px; font-size: 0.72em;
      padding: 0.1em 0.5em; font-weight: 500;
      vertical-align: middle; line-height: 1.4`, with
      `transition: all 0.12s ease`. Flash state moves to green
      tokens (`background: #dcfce7; border-color: #86efac;
      color: #166534`).
    - `:focus-visible` gives the keyboard-only focus ring required
      by a11y story 4.2 (indigo, 2 px ring, 2 px offset).
    - After the rewrites land, visually scan the `<style>` block and
      confirm every pre-existing selector (`level`, `song`,
      `name-context`, `artist`, `shows-section`, `show-block`,
      `show-name`, `show-meta`, `links`, `copy-btn`) is still
      present. The Template_File is HTML so ruff doesn't parse it;
      the check is visual. Removing any pre-existing selector would
      regress 1.9.
    - _Requirements: 1.9, 4.2, 5.3_

## Bytes-in-template regression test

- [x] 3. Add `test_template_ships_youtube_search_link_machinery` to `tests/integration/test_review.py`
  - Add exactly ONE new test function. Do NOT edit any existing test
    in the file.
  - **File touched**: `tests/integration/test_review.py` only (ADD,
    no edits to existing tests).
  - The test reads `scripts/review_template.html` as bytes via
    `pathlib.Path("scripts/review_template.html").read_bytes()` and
    asserts, with a descriptive failure message on each assertion,
    that the file contains every one of the following six
    substrings (plain `in` checks — no DOM parsing, no JavaScript
    parsing, no subprocess, no `tmp_app_root` fixture):
    - `b"renderSearchLink"` — the JS helper name.
    - `b"https://www.youtube.com/results?search_query="` — the
      YouTube search URL literal.
    - `b"encodeURIComponent"` — the client-side URL encoder.
    - `content.count(b"yt-search") >= 2` — the `yt-search` token
      appears at least twice in the template (once in the CSS
      selector `.yt-search`, once in the JS class assignment
      `a.className = 'yt-search'`). Relaxed from the originally-
      planned literal `b'class="yt-search"'` because the shipped
      template sets the class via `a.className` rather than an
      inline HTML attribute, so the double-quoted attribute form
      never appears in the bytes.
    - `b"aria-label"` AND `b"Search YouTube"`, with the two
      substrings appearing within a 500-byte proximity window —
      `abs(bytes_content.find(b"aria-label") - bytes_content.find(b"Search YouTube")) < 500`.
    - `b"noopener noreferrer"` — the link-safety contract.
      Relaxed from `b'rel="noopener noreferrer"'` because the
      shipped template wires the rel attribute via
      `setAttribute('rel', 'noopener noreferrer')` with single
      quotes, so the double-quoted HTML-attribute form never
      appears in the bytes.
  - Each assertion carries a descriptive failure message pointing at
    which substring is missing (e.g.
    `"template must ship the renderSearchLink helper"`).
  - The test does NOT import anything from `scripts/` and does NOT
    invoke `review.py` via subprocess. It is a plain
    bytes-in-template substring check and nothing more.
  - _Requirements: 8.1, 8.2, 8.3_

## Verification — existing suite stays green

- [x] 4. Verify the new bytes-in-template test passes and the existing suite stays byte-identically green
  - Run `pytest tests/integration/test_review.py::test_template_ships_youtube_search_link_machinery`
    — expect PASS after Tasks 1, 2, and 3 land.
  - Run `pytest tests/integration/test_review.py` — expect every
    pre-existing test (empty state, happy path, display level,
    HTML escape, filter rules, output path, INTERNAL_ERROR paths,
    no-write-to-DB, `--offset` parity, envelope key-set) to continue
    passing byte-identically. None of those tests were edited.
  - Run `pytest tests/integration/property/test_escape_injection_property.py`
    — expect continued PASS. Escape_Gate preservation under the new
    link surface holds transitively per design Decision D6; the
    property test's assertions are byte-identical to v0.1.3.
  - Run `pytest tests/integration/test_due.py` and
    `pytest tests/integration/property/test_due_property.py` — expect
    continued PASS. The `learning.py due` surface and its property
    coverage are untouched.
  - If any existing test fails, diagnose the root cause before
    proceeding — a regression in a pre-existing test is a
    fix-regression signal, not something to patch by editing the
    test.
  - _Requirements: 6.1, 6.2, 6.4, 7.4, 7.5, 8.1_

## Final gate — `make check`, coverage ≥ 90%, visual smoke

- [x] 5. Final gate — run `make check`, confirm coverage ≥ 90%, walk the visual smoke checklist
  - Run `make check` (lint + typecheck + test). Expect all three to
    pass. The Python-file delta is exactly +1 new test function in
    `tests/integration/test_review.py`; every other Python file is
    byte-identical. Ruff and mypy should be clean.
  - Confirm coverage stays ≥ 90% — `./tests/run.sh` enforces this
    automatically via `.coveragerc`; fail the task if coverage
    drops. This release adds no new Python production code paths, so
    the coverage floor should be unaffected.
  - Verify the Python-file delta by running `git -P diff --stat` —
    expect exactly two files changed under `scripts/` and `tests/`
    (the template plus the one new test function's host file),
    ignoring `release.md` and `.kiro/specs/` additions.
  - Walk the visual smoke checklist from `design.md` > "Testing
    Strategy" > "Manual smoke checklist":
    1. Seed a due song with at least two shows; run
       `python scripts/review.py song-review`; open the generated
       `output/review_<EPOCH>.html` in a browser.
    2. Globe icons render next to the artist AND next to each show,
       at 16 px, in accent blue.
    3. The artist globe opens YouTube with query
       `<song_name> <artist_name>` in a new tab.
    4. The show globe opens YouTube with query
       `<song_name> <show_name>` in a new tab.
    5. Keyboard Tab reaches each globe anchor with a visible focus
       ring; Enter activates the link.
    6. DevTools inspection of one globe anchor shows
       `aria-label="Search YouTube for <song_name> by <artist_name>"`
       (or `... in <show_name>` for show links).
    7. Narrow the viewport — `.artist` and `.show-block` wrap the
       globe + copy button cleanly onto the next line without
       overflow.
  - If any checklist step fails, diagnose the root cause before
    proceeding; ask the user if questions arise.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.5, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4_

## Release note

- [x] 6. Update `release.md` for v0.1.4 with the polish + search-link bullet
  - **File touched**: `release.md` only.
  - Bump the header from `## jankenoboe-lite v0.1.3` to
    `## jankenoboe-lite v0.1.4`.
  - Rewrite the preamble sentence (currently "One small consistency
    fix and one internal refactor...") to reflect v0.1.4's scope: two
    coordinated UX improvements to the Review_Page (visual polish plus
    the YouTube-search fallback icons), no breaking changes, no schema
    migration, no CLI change.
  - Replace the two v0.1.3 Highlight bullets with one new bullet
    describing v0.1.4:
    - **Review page polish + YouTube-search fallback icons.**
      Describe that the Review_Page now renders with consistent
      padding across the Song_Card / show block / links list, softer
      `#f0f0f0` dividers, clearer weight and color hierarchy between
      song title / artist / show meta, and `flex-wrap` on the artist
      line and show block so long names wrap gracefully on narrow
      viewports. Describe that every Song_Card gains a small inline
      globe icon next to the artist (opens a YouTube search for
      `<song_name> <artist_name>` in a new tab) and next to each show
      (opens a YouTube search for `<song_name> <show_name>`) as an
      escape hatch for broken stored media links. Note that the
      existing per-show `media_urls` list still renders as today, and
      that the feature is a template-only change with zero Python
      production-code edits.
  - Update the "Verified on this build" block to reflect the new
    test count (v0.1.3 shipped with 480 passing; this release adds
    one new bytes-in-template test, so the post-release count is 481)
    and re-confirm 95% line coverage.
  - Leave the `Install` and `Use it` sections byte-identical — the
    UX flow and CLI are unchanged.
  - _References: all Stories 1 – 8 in `requirements.md`; no
    individual acceptance criterion drives this release-note edit._
