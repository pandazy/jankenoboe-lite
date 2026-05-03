# Review Page Polish and Search Links Design

## Overview

Two small, coordinated changes to the review-page surface:

1. **Polish.** The Review_Page (`scripts/review_template.html`) is
   functional but visually flat — inconsistent padding, blue-on-white
   level pill that collides with the links, show block meta text running
   into the link list, no discipline around how long song names or show
   lists wrap. This spec lifts each song into a white card with a subtle
   shadow, and wraps each show in a rounded chip with a soft indigo
   accent bar so individual shows read as discrete items rather than
   nested list rows. Semantics, payload shape, and the client-side
   render pipeline do not change; the DOM gains one new inner wrapper
   `<div class="show-head">` inside each show block so the show header
   row (name + copy + meta + globe) lays out as a flex unit.

2. **YouTube-search fallback icons.** When a song's stored
   `media_urls` list is empty, broken, or points at a geoblocked clip,
   the reviewing agent (or a human) has no one-click path to the audio.
   Add a small globe icon next to the artist and next to each show that
   opens a YouTube search for `<song_name> <artist_name>` and
   `<song_name> <show_name>` respectively. The icons render alongside
   the existing per-show link list — not replacing it. Existing links
   stay the primary path; the icons are the escape hatch.

Both changes land purely within `scripts/review_template.html`.
**No Python production file is modified.** `scripts/review.py`,
`scripts/_common.py`, and `tests/integration/_dom_sim.py` stay
byte-identical, as do every existing Python test and property test.
The only Python-file edit is a single new test function in
`tests/integration/test_review.py` that reads the template as bytes
and asserts on six literal substrings (no DOM parsing, no payload
rendering, no browser simulation). No schema change, no new error
codes, no CLI surface change, no payload-shape change. Ships as
v0.1.4 through the existing release pipeline, one commit.

## Glossary

- **Review_Page**: The HTML file written to
  `App_Root/output/review_<EPOCH>.html` by `scripts/review.py
  song-review`.
- **Template_File**: `scripts/review_template.html`. Contains a
  `<!-- DUE_DATA_JSON -->` marker that `scripts/review.py` substitutes
  with the JSON-escaped `Due_Data_Payload` at render time.
- **Due_Data_Payload**: The JSON document built by
  `scripts/review.py._build_payload`. Shape is frozen by the existing
  `review-html-enhancements` contract; any new fields this spec adds
  are **additive only**.
- **Inline_Script**: The single `<script>` at the bottom of
  `Template_File`. Runs on DOMContentLoaded, reads the JSON from
  `<script id="due-data">`, builds the rendered DOM.
- **Song_Card**: One `<li data-level="N">` node inside the rendered
  DOM. Contains level pill, song title, artist line, and shows section.
- **Search_Link**: The new `<a>` element this spec introduces.
  Wraps a small globe icon. `href` points at
  `https://www.youtube.com/results?search_query=...`. One next to the
  artist; one next to each show.
- **Escape_Gate**: The `_escape_json_for_html` pass in
  `scripts/review.py` that rewrites `<`, `>`, and `&` in the serialised
  payload to `\u003c`, `\u003e`, and `\u0026` before the payload lands
  inside `<script type="application/json">`. The property-based
  injection test (`tests/integration/property/test_escape_injection_property.py`)
  is the oracle for this gate.
- **Polish_Scope**: The visual tightening described under Design
  Decision D5. Does not introduce a dark mode, does not change
  semantics or DOM shape, does not add external assets.
- **Show_Chip**: The rounded, left-accented inner panel that wraps
  one show inside a Song_Card — introduced by this release. A
  `<div class="show-block">` with its own background, rounded
  corners, and a 3 px indigo left border. Contains a
  `<div class="show-head">` row (name + copy + meta + globe) and,
  below it, the per-show `<ul class="links">`.
- **Globe_Icon**: The inline SVG (Design Decision D1) rendered inside
  every `Search_Link`.

## Requirements-to-Design Mapping

`requirements.md` does not exist yet — under the design-first workflow
it will be derived from this document in the next step. The anchors
this design will carry into `requirements.md`:

- **R-Polish**: the page renders with consistent padding, clear
  hierarchy, soft dividers, and graceful wrapping of long names and
  long show lists (Design Decision D5).
- **R-Search-Artist**: every `Song_Card` contains exactly one
  `Search_Link` after the artist name whose `href` is
  `https://www.youtube.com/results?search_query=<encoded(song_name + " " + artist_name)>`
  (Design Decision D2, Low-Level Design).
- **R-Search-Show**: every show row inside the shows-section contains
  exactly one `Search_Link` after the show name whose `href` is
  `https://www.youtube.com/results?search_query=<encoded(song_name + " " + show_name)>`
  (Design Decision D2, Low-Level Design).
- **R-A11y**: every `Search_Link` has a human-readable `aria-label`
  naming the song and the target (artist or show). The link is
  keyboard-focusable (native `<a>` behaviour); `target="_blank"` is
  paired with `rel="noopener noreferrer"` (Design Decision D3).
- **R-Escape-Preserve**: the existing `Escape_Gate` is not regressed.
  Hostile song / artist / show names still round-trip byte-for-byte
  through the payload and never appear as live markup, including
  inside the new `Search_Link` surface (Design Decision D6, Testing
  Strategy).
- **R-Additive**: if the payload shape changes at all, existing fields
  remain byte-identical; only new additive fields may appear (Design
  Decision D4).
- **R-No-Network**: the `Globe_Icon` is an inline SVG — no CDN, no
  external image fetch, no network dependency at render time (Design
  Decision D1).
- **R-No-Python**: no Python production file in the repo is
  modified by this spec. The only production-code file touched is
  `scripts/review_template.html`. `scripts/review.py`,
  `scripts/_common.py`, `tests/integration/_dom_sim.py`, every
  existing test in `tests/integration/test_review.py`, and every
  property test stay byte-identical. The only Python edit is one
  new test function in `tests/integration/test_review.py` (a plain
  bytes-in-template assertion — see Testing Strategy, Option B).
  This invariant is the hard scope-boundary for the release.

## High-Level Design

### Component Breakdown

Three moving parts, all inside the Template_File — zero Python
files touched:

1. **CSS block** (`<style>` inside `<head>`). Gets the
   Polish_Scope rewrites: padding scale, font weights, link color
   accents, divider rules, wrapping rules. No new classes are
   strictly required — existing class names (`level`, `song`,
   `name-context`, `artist`, `shows-section`, `show-block`,
   `show-name`, `show-meta`, `links`, `copy-btn`) already cover every
   surface. One new class is added: `.yt-search` for the `Search_Link`
   anchor wrapping the Globe_Icon.

2. **Inline_Script render functions.** Two functions grow:
   - `renderSong(s)` appends a `Search_Link` to the artist `<div>`
     after the artist name span and its existing `copy-btn`.
   - `renderShowBlock(sh)` appends a `Search_Link` to the show block
     after the show name span and its existing `copy-btn`.
   Plus one new helper:
   - `renderSearchLink(songName, targetName, targetKind)` — builds the
     `<a>` with the correct `href`, `aria-label`, `target`, `rel`, and
     the inlined Globe_Icon SVG child.

3. **`_build_payload`** — byte-identical to v0.1.3. URL
   construction is client-side (D2), so no new fields are added.
   R-No-Python pins this: `scripts/review.py` is not touched by
   this spec.

### Data Model Touchpoints

None. No SQL change, no schema change, no new table, no new column.
The data the `Search_Link` needs — `song_name`, `artist_name`, each
`show_name` — is already present in the Due_Data_Payload today. The
payload schema from the prior `review-html-enhancements` spec:

- Per song: `learning_id`, `song_id`, `song_name`, `song_name_context`,
  `artist_id`, `artist_name`, `artist_name_context`, `display_level`,
  `shows`.
- Per show inside `shows`: `show_id`, `show_name`, `show_name_romaji`,
  `show_vintage`, `show_s_type`, `media_urls`.

The Inline_Script already has `s.song_name`, `s.artist_name`, and
`sh.show_name` in scope inside the render functions. Nothing new
travels over the payload boundary.

### Pipeline Touchpoints (Where Each Change Enters)

```
scripts/review.py                       scripts/review_template.html
─────────────────────                   ───────────────────────────
  _build_payload(conn, offset)   ──▶     <script id="due-data">
      │                                    {JSON payload}
      │ unchanged output                 </script>
      ▼                                    │
  _render_page(payload, template) ─▶     <script> Inline_Script
      │                                    renderSong(s) ──┐
      │                                      renderSearchLink(
      ▼                                        s.song_name,
  review_<EPOCH>.html                          s.artist_name,
                                               "artist")              ◀── NEW
                                          renderShowBlock(sh) ──┐
                                            renderSearchLink(
                                              songName,               ◀── NEW (threaded through)
                                              sh.show_name,
                                              "show")                 ◀── NEW
                                            existing media_urls list
                                          </script>
                                          <style> Polish_Scope CSS    ◀── NEW (in-place rewrite)
                                          </style>
```

Every change lands in `scripts/review_template.html`. `scripts/review.py`
is untouched in the minimum implementation.

### Before / After

**Before** — today's Song_Card (class names carry over exactly):

```
┌─────────────────────────────────────────────────┐
│ [Level 3]  Song Title (context)      [copy]     │  ← <li data-level>
│ Artist Name (context)  [copy]                   │  ← .artist
│ Shows:                                          │  ← .shows-section
│   Show Name — romaji, 2009, TV  [copy]          │  ← .show-block
│     • http://example.com/a                       │  ← .links
│     • http://example.com/b                       │
│   Show Name Two — ...  [copy]                   │
│     • http://example.com/c                       │
└─────────────────────────────────────────────────┘
```

**After** — same semantics, tighter spacing, new globe icons on
artist and each show. Long show lists wrap cleanly; long names no
longer run into the copy button. ASCII approximation (`🌐` shown as
stand-in for the inline Globe_Icon SVG):

```
┌─────────────────────────────────────────────────┐
│  [Level 3]  Song Title  (context)      [copy]   │  ← consistent padding
│  ─────                                          │
│  Artist Name  (context)  [copy]  🌐             │  ← 🌐 = Search_Link → YT(song+artist)
│                                                  │
│  Shows                                          │  ← "Shows:" → "Shows" w/ muted label
│    Show Name  —  romaji, 2009, TV  [copy]  🌐   │  ← 🌐 = Search_Link → YT(song+show)
│      • example.com/a                             │  ← basename stays
│      • example.com/b                             │
│    Show Name Two  —  ...  [copy]  🌐            │
│      • example.com/c                             │
└─────────────────────────────────────────────────┘
```

Row ordering within each line:

- Song line:   `[LevelPill] [SongTitle] [copy] [name-context?]`
- Artist line: `[ArtistName] [name-context?] [copy] [Search_Link]`
- Show row:    `[ShowName] [copy] [show-meta?] [Search_Link] + [links ul]`

The `[Search_Link]` placement is **after** the existing copy button on
both surfaces so the copy button's position (a known touch target)
does not shift between v0.1.3 and v0.1.4.

## Design Decisions

### D1 — Icon source: inline SVG, not emoji

**Choice**: inline SVG globe, defined once in the Inline_Script as a
template string or built node-by-node, cloned into every Search_Link.

**Considered**:
- **Emoji `🌐`**: single character, trivially inserted via
  `textContent`. No SVG maintenance.
- **External SVG file** (e.g. `scripts/globe.svg` referenced via
  `<img src="...">`): tidy separation but requires a second file to
  travel with the Review_Page — which it does not today, because
  review.py writes exactly one file.
- **Icon font CDN** (FontAwesome etc.): violates "no network fetch"
  from the `review-html-enhancements` invariant.

**Why inline SVG**:
- The app runs fully offline; the Review_Page must render with no
  network access (a user opens `review_<EPOCH>.html` in a browser with
  Wi-Fi off). Inline SVG is the only option that is both network-free
  **and** renders visually like an icon (emoji rendering is
  font-dependent and on some platforms the `🌐` glyph is oversized,
  colored, or missing).
- Inline SVG is stylable via CSS (`fill`, `stroke`, `width`), so the
  Polish_Scope can tune the accent color in one place.
- One source file discipline is preserved — `review.py` still writes
  exactly one `.html` file.

**Fallback**: if the 16×16 SVG below is ever deemed too busy for a
future theming pass, the inline SVG can be swapped 1-for-1 with the
emoji `🌐` wrapped in a `<span class="yt-search-glyph">` and the
rest of this design is unaffected. This spec picks SVG.

**Exact SVG**: a minimal, monochrome globe at 16×16, `viewBox="0 0 16
16"`. Pure geometry, no gradients, no external references:

```html
<svg class="yt-search-icon" width="16" height="16" viewBox="0 0 16 16"
     aria-hidden="true" focusable="false"
     xmlns="http://www.w3.org/2000/svg">
  <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
  <ellipse cx="8" cy="8" rx="3" ry="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
  <line x1="1.5" y1="8" x2="14.5" y2="8" stroke="currentColor" stroke-width="1"/>
</svg>
```

`aria-hidden="true"` on the SVG means the icon itself is not announced
by screen readers; the parent `<a>`'s `aria-label` carries the name.

### D2 — URL construction lives in the browser (client-side JS)

**Choice**: build the `href` inside the Inline_Script's new
`renderSearchLink(songName, targetName, targetKind)` helper using
`encodeURIComponent`.

**Considered**:
- **Server-side, in `_build_payload`**: add `artist_search_url` (per
  song) and `show_search_url` (per show) using
  `urllib.parse.quote_plus`. Pro: URL construction tested in Python.
  Con: payload schema growth, an additive change that is not strictly
  necessary because the browser has everything it needs.
- **Hybrid** (server emits the query string, client wraps it): worst of
  both — schema grows AND the browser still does work.

**Why client-side**:
- `song_name`, `artist_name`, and `show_name` are already in the
  payload. No new field is needed — the "Additive-only" invariant
  (D4) is satisfied trivially by a zero-field delta.
- `encodeURIComponent` is part of every modern browser. No polyfill,
  no compatibility layer.
- `scripts/review.py` stays byte-identical. The diff is purely in
  `scripts/review_template.html`.
- The existing `tests/integration/property/test_escape_injection_property.py`
  already covers the payload-through-DOM pipeline; extending its
  assertions to the new `<a>` href is a small addition in the same
  test surface.

**URL shape**:
- Artist: `https://www.youtube.com/results?search_query=` +
  `encodeURIComponent(songName + ' ' + artistName)`.
- Show: `https://www.youtube.com/results?search_query=` +
  `encodeURIComponent(songName + ' ' + showName)`.

The space separator is a plain ASCII `' '`. `encodeURIComponent`
rewrites it to `%20`. (YouTube also accepts `+` — both forms work —
but `%20` is what `encodeURIComponent` emits and the test oracle
assertion matches exactly.)

### D3 — Accessible-name scheme

**Choice**: the `<a>` carries an `aria-label` that names the song and
the target. The inline SVG is `aria-hidden="true"` because the `<a>`
already has its accessible name from the label.

- Artist link: `aria-label="Search YouTube for <song_name> by <artist_name>"`.
- Show link:   `aria-label="Search YouTube for <song_name> in <show_name>"`.

The name literal goes into `aria-label` unescaped — the browser treats
`setAttribute('aria-label', value)` as a string, not as markup. Same
rules as `setAttribute('href', url)`: the value never re-enters the
HTML parser. So a hostile song name like `<script>alert(1)</script>`
lands in the `aria-label` as the literal string; it cannot break out.
The Escape_Gate (D6) is not bypassed because the value was never
inside a script-text context to begin with — it came out of
`JSON.parse(node.textContent)` as a string primitive, then straight
into `setAttribute`.

`target="_blank"` opens the search in a new tab (reviewing agents
typically want to keep the Review_Page visible while they search).
`rel="noopener noreferrer"` paired with `target="_blank"` is the
standard guard against window-opener tab-napping and stops the
referrer header from leaking the reviewer's local file path.

Keyboard focus is native — `<a href="...">` is focusable by default,
reachable via Tab, and activated by Enter. No additional `tabindex`
or key handler is needed.

### D4 — Additive-only payload invariant

**Choice**: the Due_Data_Payload schema is byte-identical to v0.1.3
in the minimum implementation. Because URL construction is
client-side (D2), there are zero new fields in this release.

If a future release wants to move URL construction server-side (for
example to add per-link analytics or to plumb a non-YouTube fallback),
that would grow the payload additively — existing field names, types,
and orders preserved; new fields named `artist_search_url` and
`show_search_url` added alongside the existing ones. Not happening in
this spec.

The existing payload consumers — the Inline_Script and
`tests/integration/_dom_sim.py` — continue to work unchanged.

### D5 — Polish_Scope (what "polish" means, concretely)

"Polish" is unbounded if left undefined. This decision pins the scope
to the concrete treatment that shipped. Anything outside these
bullets is out of scope (see "Out of Scope" below).

1. **Song cards.** Each `<li data-level="...">` renders as a real
   panel rather than a flat list row — `background: #ffffff`,
   `1px solid #e5e7eb` border, `border-radius: 10px`, a subtle drop
   shadow (`box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04)`), and a
   hover-lift that darkens the border to `#d1d5db` and deepens the
   shadow to `0 2px 8px rgba(15, 23, 42, 0.08)`. Padding is
   `1em 1.2em`, with `0.9em` bottom margin so cards stack with air
   between them. The enclosing `<ol>` gets `list-style-position:
   outside; padding: 0; margin: 0` plus `counter-reset:
   song-counter`, and each `<li>` gets a CSS counter `::before`
   (`counter-increment: song-counter; content: counter(song-counter)
   "."`) so the default-list bullet is suppressed and replaced by a
   muted-gray numeral styled to match the card.

2. **Level pill.** No longer a solid blue chip. Renders as a
   fully-rounded pastel pill: `background: #eff6ff; color: #1d4ed8;
   border: 1px solid #dbeafe; border-radius: 999px; font-weight: 600;
   font-size: 0.78em`. The softer blue reads as a tag rather than a
   badge and keeps the song title as the dominant element on the
   line.

3. **Show chips** (Show_Chip glossary term). Each
   `<div class="show-block">` renders as a distinct inner chip —
   own background `#f9fafb`, `1px solid #e5e7eb` border, a 3 px
   indigo left accent bar (`border-left: 3px solid #a5b4fc`),
   `border-radius: 6px`, padding `0.55em 0.8em`. Shows stack
   vertically inside the shows section (`display: block`, top margin
   `0.5em`) so each one reads as its own card-within-a-card rather
   than a flex row that shares a line with its siblings.

4. **`.show-head` inner wrapper** — DOM structure change. Inside
   each Show_Chip, a new `<div class="show-head">` wraps the show
   name + copy button + optional meta + globe Search_Link onto a
   single flex row (`display: flex; flex-wrap: wrap; align-items:
   center; gap: 0.35em`). The links `<ul>` is a sibling below the
   `.show-head`, not a child of it. `renderShowBlock(sh, songName)`
   builds the `.show-head` explicitly and appends the links list to
   the enclosing `.show-block` so the two render as header + body
   rather than as a single flex row.

5. **Links list.** Per-show `<ul class="links">` stacks BELOW the
   `.show-head` instead of trailing after it on the same line. The
   `<ul>` is `list-style: none`, `padding: 0`, `margin: 0.4em 0 0 0`;
   each `<li>` gets a `::before` arrow `↳ ` in `#9ca3af` instead of
   a disc bullet. Link color is `#2563eb`.

6. **Shows-section label.** The section header above the chips
   reads as a muted small-caps label — `color: #6b7280; font-size:
   0.85em; font-weight: 500; text-transform: uppercase;
   letter-spacing: 0.04em`. The Inline_Script sets the text to the
   plain string `"Shows"` (no trailing colon); the uppercasing is
   purely CSS.

7. **Show meta separator.** The meta line joins romaji + vintage +
   s_type with ` · ` (middle dot, space-padded) and prefixes the
   whole thing with `· `, so a full meta reads as
   `· romaji · 2015 · TV`. Replaces the previous `—` separator
   and `, ` join. Color `#6b7280`, font-size `0.88em`.

8. **Copy button baseline.** Rewritten to match the card palette:
   `border: 1px solid #e5e7eb`, `background: #ffffff`,
   `color: #6b7280`, `border-radius: 4px`, `font-size: 0.72em`,
   `vertical-align: middle`, `line-height: 1.4`. The flash state
   uses green tokens (`background: #dcfce7; border-color: #86efac;
   color: #166534`) instead of the v0.1.3 blue flash.

9. **YouTube-search anchor.** `.yt-search` renders as a fixed
   22 × 22 circle (`width: 22px; height: 22px; border-radius: 50%;
   display: inline-flex; align-items: center; justify-content:
   center`). Idle color `#6366f1` (indigo); hover
   `background: #eef2ff; color: #4338ca`. `:focus-visible` paints
   a 2 px indigo ring with 2 px offset (`outline: 2px solid #6366f1;
   outline-offset: 2px`).

10. **Body and headings.** `body { max-width: 820px; background:
    #fafbfc; color: #1a1a1a; line-height: 1.5 }`; `h1 { font-size:
    1.8em; letter-spacing: -0.01em }`.

11. **"Done" and empty states.** Clicking a card toggles
    `li[data-level].done { opacity: 0.5; background: #f3f4f6 }`,
    with a defensive `.show-block { background: #ffffff }` reset
    inside so the chips stay visible against the dimmed card.
    Empty state is a dashed-border centered panel
    (`border: 1px dashed #d1d5db; background: #ffffff;
    border-radius: 10px`).

No dark mode, no font family change, no font-file download, no
color-scheme media query.

### D6 — Escape_Gate preservation

**Claim**: the Polish_Scope and Search_Link changes do not regress
the `test_escape_injection_property.py` oracle.

**Why it holds**:
- Polish_Scope is a CSS-only diff. CSS text lives in `<style>` and
  cannot be a vector for script injection.
- The new `renderSearchLink` helper consumes `s.song_name`,
  `s.artist_name`, and `sh.show_name` as string primitives obtained
  from `JSON.parse(textContent)`. These values are passed to
  `setAttribute('href', ...)`, `setAttribute('aria-label', ...)`, and
  (for defensive UI text) nowhere as HTML. `setAttribute` does not
  re-parse its arguments — a hostile `</script>` in a name lands in
  the attribute as a literal string, not as markup.
- `encodeURIComponent` further percent-encodes every byte that is not
  an unreserved URI character, so the `href` value contains no
  `<` / `>` / `&` even before it enters `setAttribute`.
- The inline Globe_Icon is a static string inside the Inline_Script
  (see Low-Level Design). No payload value substitutes into it; a
  hostile name cannot poison the SVG markup.

**Coverage argument — no new test needed**: the existing
`test_escape_injection_property.py` already asserts, for every
iteration, that the rendered document parses to exactly two
`<script>` elements and that the payload round-trips the hostile
string byte-for-byte. Every byte the new `renderSearchLink` helper
reads (song name, artist name, show name) comes out of the same
`JSON.parse(node.textContent)` channel that the existing test
already gates. If Escape_Gate holds for the payload going in, it
holds transitively for the Search_Link coming out — the helper
never puts a payload string anywhere the browser's HTML parser can
reach (only into `setAttribute('href', encodeURIComponent(...))`,
`setAttribute('aria-label', ...)`, and DOM-node construction via
`createElement` / `createElementNS`, none of which re-enter the
parser). No additional Python-side assertion about the new `<a>`
surface is added to `test_escape_injection_property.py`; the test
stays byte-identical to its v0.1.3 form.

## Low-Level Design

### The new Search_Link HTML (what the browser renders)

For the artist:

```html
<a class="yt-search"
   href="https://www.youtube.com/results?search_query=Song%20Name%20Artist%20Name"
   target="_blank"
   rel="noopener noreferrer"
   aria-label="Search YouTube for Song Name by Artist Name">
  <svg class="yt-search-icon" width="16" height="16" viewBox="0 0 16 16"
       aria-hidden="true" focusable="false"
       xmlns="http://www.w3.org/2000/svg">
    <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
    <ellipse cx="8" cy="8" rx="3" ry="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
    <line x1="1.5" y1="8" x2="14.5" y2="8" stroke="currentColor" stroke-width="1"/>
  </svg>
</a>
```

For each show: identical shape, the `aria-label` names the show
instead of the artist, and the `href`'s encoded query is
`<song_name>%20<show_name>`.

### The new Song_Card HTML (rendered, complete)

The card is numbered by a CSS counter (`li[data-level]::before`),
not by a browser-default `<ol>` bullet. The Show_Chip contains a
`.show-head` inner wrapper; the links `<ul>` is a sibling of
`.show-head`, not a child. Meta is joined with ` · ` and prefixed
with `· `:

```html
<li data-level="3">
  <span class="level">Level 3</span>
  <span class="song">Song Title</span>
  <button type="button" data-copy-id="song-uuid" class="copy-btn">copy</button>
  <span class="name-context">(context)</span>
  <div class="artist">
    <span>Artist Name</span>
    <button type="button" data-copy-id="artist-uuid" class="copy-btn">copy</button>
    <span class="name-context">(solo)</span>
    <a class="yt-search"
       href="https://www.youtube.com/results?search_query=Song%20Title%20Artist%20Name"
       target="_blank"
       rel="noopener noreferrer"
       aria-label="Search YouTube for Song Title by Artist Name">
      <svg class="yt-search-icon" width="16" height="16" viewBox="0 0 16 16"
           aria-hidden="true" focusable="false">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
        <ellipse cx="8" cy="8" rx="3" ry="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
        <line x1="1.5" y1="8" x2="14.5" y2="8" stroke="currentColor" stroke-width="1"/>
      </svg>
    </a>
  </div>
  <div class="shows-section">Shows
    <div class="show-block">
      <div class="show-head">
        <span class="show-name">Show Name</span>
        <button type="button" data-copy-id="show-uuid" class="copy-btn">copy</button>
        <span class="show-meta">· romaji · 2009 · TV</span>
        <a class="yt-search"
           href="https://www.youtube.com/results?search_query=Song%20Title%20Show%20Name"
           target="_blank"
           rel="noopener noreferrer"
           aria-label="Search YouTube for Song Title in Show Name">
          <svg class="yt-search-icon" width="16" height="16" viewBox="0 0 16 16"
               aria-hidden="true" focusable="false">
            <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
            <ellipse cx="8" cy="8" rx="3" ry="6.5" fill="none" stroke="currentColor" stroke-width="1"/>
            <line x1="1.5" y1="8" x2="14.5" y2="8" stroke="currentColor" stroke-width="1"/>
          </svg>
        </a>
      </div>
      <ul class="links">
        <li><a href="http://example.com/a">a</a></li>
        <li><a href="http://example.com/b">b</a></li>
      </ul>
    </div>
  </div>
</li>
```

The rendered numeral "3." in front of the level pill comes from the
`li[data-level]::before` counter; similarly the "↳" prefix in each
`.links li` comes from `.links li::before`. Neither glyph is emitted
by the Inline_Script — both are purely CSS.

### The new CSS block (Polish_Scope + `.yt-search`)

The full shipped `<style>` block from `scripts/review_template.html`.
All values are pinned here; the template is the source of truth.

```css
/* Base layout. */
body { font-family: system-ui, -apple-system, sans-serif;
       max-width: 820px; margin: 2em auto; padding: 0 1em;
       color: #1a1a1a; background: #fafbfc; line-height: 1.5; }
h1 { margin-bottom: 0.2em; font-size: 1.8em; letter-spacing: -0.01em; }
.meta { color: #6b7280; margin-bottom: 1.5em; font-size: 0.95em; }

/* Noscript fallback: shown by default, hidden once the Inline_Script
   tags <body> as js-active. */
.js-required { color: #a00; font-weight: 600; padding: 1em 0; }
body.js-active .js-required { display: none; }

/* Song cards — each <li> renders as a real panel with its own
   background, subtle shadow, and rounded corners. */
ol { list-style-position: outside; padding: 0; margin: 0; }
ol { counter-reset: song-counter; }
li[data-level] { display: block;
                 padding: 1em 1.2em;
                 margin: 0 0 0.9em 0;
                 background: #ffffff;
                 border: 1px solid #e5e7eb;
                 border-radius: 10px;
                 box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
                 cursor: pointer;
                 transition: box-shadow 0.15s ease,
                             border-color 0.15s ease; }
li[data-level]:hover { box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
                       border-color: #d1d5db; }
li[data-level]::before { counter-increment: song-counter;
                         content: counter(song-counter) ".";
                         color: #9ca3af; font-weight: 500;
                         margin-right: 0.5em; font-size: 0.9em; }

/* Level pill — softer pastel, less shouty than solid blue. */
.level { display: inline-block; padding: 0.15em 0.65em;
         background: #eff6ff; color: #1d4ed8;
         border: 1px solid #dbeafe;
         border-radius: 999px;
         font-size: 0.78em; font-weight: 600;
         margin-right: 0.6em;
         letter-spacing: 0.01em; }

/* Song title + inline name_context. */
.song { font-size: 1.1em; font-weight: 600; color: #111827;
        display: inline-block; }
.name-context { color: #6b7280; font-style: italic;
                margin-left: 0.3em; font-weight: 400; }

/* Artist line sits under the title. Wraps as a unit on narrow viewports. */
.artist { color: #374151; margin-top: 0.35em;
          display: flex; flex-wrap: wrap;
          align-items: center; gap: 0.4em;
          font-weight: 500; font-size: 0.98em; }

/* Shows section — "Shows" label + stacked show chips. */
.shows-section { margin-top: 0.75em; color: #6b7280;
                 font-size: 0.85em; font-weight: 500;
                 text-transform: uppercase;
                 letter-spacing: 0.04em; }

/* Each show renders as a distinct "chip" — its own background,
   rounded corners, left accent bar. Shows stack vertically. */
.show-block { display: block;
              margin: 0.5em 0 0 0;
              padding: 0.55em 0.8em;
              background: #f9fafb;
              border: 1px solid #e5e7eb;
              border-left: 3px solid #a5b4fc;
              border-radius: 6px;
              color: #1f2937; }
/* The show header row (name + copy + meta + globe) sits on one line,
   wraps gracefully on narrow viewports. */
.show-head { display: flex; flex-wrap: wrap;
             align-items: center; gap: 0.35em; }
.show-name { font-weight: 600; color: #111827; font-size: 0.98em; }
.show-meta { color: #6b7280; font-size: 0.88em;
             font-weight: 400; font-style: normal;
             text-transform: none; letter-spacing: normal; }

/* Per-show link list — stacked BELOW the show header, not beside. */
.links { display: block;
         margin: 0.4em 0 0 0;
         padding: 0; list-style: none;
         font-size: 0.9em; }
.links li { padding: 0.1em 0; }
.links li::before { content: "↳ "; color: #9ca3af;
                    margin-right: 0.15em; }
.links a { color: #2563eb; text-decoration: none; }
.links a:hover { text-decoration: underline; }

/* Copy buttons. */
.copy-btn { font-size: 0.72em;
            padding: 0.1em 0.5em; cursor: pointer;
            border: 1px solid #e5e7eb; border-radius: 4px;
            background: #ffffff; color: #6b7280;
            font-weight: 500; transition: all 0.12s ease;
            line-height: 1.4;
            vertical-align: middle; }
.copy-btn:hover { background: #f3f4f6; color: #1f2937;
                  border-color: #d1d5db; }
.copy-btn.flash { background: #dcfce7; border-color: #86efac;
                  color: #166534; }

/* YouTube-search fallback anchor. Small, accent-colored, with
   hover and focus affordances. */
.yt-search { display: inline-flex; align-items: center;
             justify-content: center;
             width: 22px; height: 22px;
             color: #6366f1; text-decoration: none;
             border-radius: 50%;
             line-height: 1;
             vertical-align: middle;
             transition: background 0.12s ease, color 0.12s ease; }
.yt-search:hover { background: #eef2ff; color: #4338ca; }
.yt-search:focus-visible { outline: 2px solid #6366f1;
                           outline-offset: 2px; }
.yt-search-icon { display: block; }

/* Session "done" highlight — dims the whole card. */
li[data-level].done { opacity: 0.5;
                      background: #f3f4f6; }
li[data-level].done .show-block { background: #ffffff; }

/* Empty state. */
.empty-state { color: #6b7280; font-style: italic;
               padding: 3em 0; text-align: center;
               background: #ffffff;
               border: 1px dashed #d1d5db;
               border-radius: 10px; }
```

Every pre-existing selector from v0.1.3 (`level`, `song`,
`name-context`, `artist`, `shows-section`, `show-block`, `show-name`,
`show-meta`, `links`, `copy-btn`) is still referenced. New selectors
added alongside: `.show-head` (the inner flex wrapper), `.yt-search`,
`.yt-search:hover`, `.yt-search:focus-visible`, `.yt-search-icon`,
plus the `::before` pseudo-elements on `li[data-level]` and
`.links li`.

### The new Inline_Script additions

The existing `renderSong` and `renderShowBlock` gain a single line
each. One new helper `renderSearchLink` is added.

**New helper** (lives next to `copyButton` in the Inline_Script's
function list):

```javascript
function renderSearchLink(songName, targetName, targetKind) {
  // targetKind is "artist" or "show" — controls the aria-label phrasing.
  var query = songName + ' ' + targetName;
  var href = 'https://www.youtube.com/results?search_query='
           + encodeURIComponent(query);

  var a = document.createElement('a');
  a.className = 'yt-search';
  a.setAttribute('href', href);
  a.setAttribute('target', '_blank');
  a.setAttribute('rel', 'noopener noreferrer');
  var label = targetKind === 'artist'
    ? ('Search YouTube for ' + songName + ' by ' + targetName)
    : ('Search YouTube for ' + songName + ' in ' + targetName);
  a.setAttribute('aria-label', label);

  // Inline Globe_Icon SVG — constructed via DOM APIs in the SVG namespace
  // so every element is a real SVGElement, not an HTMLUnknownElement.
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'yt-search-icon');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');

  var circle = document.createElementNS(SVG_NS, 'circle');
  circle.setAttribute('cx', '8'); circle.setAttribute('cy', '8');
  circle.setAttribute('r', '6.5'); circle.setAttribute('fill', 'none');
  circle.setAttribute('stroke', 'currentColor');
  circle.setAttribute('stroke-width', '1');
  svg.appendChild(circle);

  var ellipse = document.createElementNS(SVG_NS, 'ellipse');
  ellipse.setAttribute('cx', '8'); ellipse.setAttribute('cy', '8');
  ellipse.setAttribute('rx', '3'); ellipse.setAttribute('ry', '6.5');
  ellipse.setAttribute('fill', 'none');
  ellipse.setAttribute('stroke', 'currentColor');
  ellipse.setAttribute('stroke-width', '1');
  svg.appendChild(ellipse);

  var line = document.createElementNS(SVG_NS, 'line');
  line.setAttribute('x1', '1.5'); line.setAttribute('y1', '8');
  line.setAttribute('x2', '14.5'); line.setAttribute('y2', '8');
  line.setAttribute('stroke', 'currentColor');
  line.setAttribute('stroke-width', '1');
  svg.appendChild(line);

  a.appendChild(svg);
  return a;
}
```

**`renderSong` diff** — one line appended to the artist `<div>`
after the existing copy button call:

```javascript
// existing:
var artist = document.createElement('div');
artist.className = 'artist';
var aName = document.createElement('span');
aName.textContent = s.artist_name;
artist.appendChild(aName);
artist.appendChild(copyButton(s.artist_id));
if (s.artist_name_context) { /* ... existing ... */ }
// NEW — after the copy button (and after the optional name_context):
artist.appendChild(renderSearchLink(s.song_name, s.artist_name, 'artist'));
li.appendChild(artist);
```

**`renderShowBlock` diff** — `renderShowBlock` needs the enclosing
song's `song_name` to build the show Search_Link, so it gains a
second parameter. It also builds an inner `.show-head` flex wrapper
that holds the show name + copy button + meta + globe on one line,
and appends the links `<ul>` as a sibling of `.show-head` (child of
`.show-block`) so the links stack below the header rather than
trailing after it:

```javascript
function renderShowBlock(sh, songName) {   // NEW 2nd param
  var block = document.createElement('div');
  block.className = 'show-block';

  // NEW — inner flex wrapper for the show header row.
  var head = document.createElement('div');
  head.className = 'show-head';

  var name = document.createElement('span');
  name.className = 'show-name';
  name.textContent = sh.show_name;
  head.appendChild(name);

  head.appendChild(copyButton(sh.show_id));

  var extras = [sh.show_name_romaji, sh.show_vintage, sh.show_s_type]
    .filter(function (x) { return x; });
  if (extras.length > 0) {
    var meta = document.createElement('span');
    meta.className = 'show-meta';
    // NEW separator: '· ' prefix + ' · ' join (was ' — ' / ', ').
    meta.textContent = '· ' + extras.join(' · ');
    head.appendChild(meta);
  }

  head.appendChild(renderSearchLink(songName, sh.show_name, 'show'));
  block.appendChild(head);

  // Links list is a sibling of .show-head, child of .show-block.
  if (sh.media_urls && sh.media_urls.length > 0) {
    var ul = document.createElement('ul');
    ul.className = 'links';
    for (var i = 0; i < sh.media_urls.length; i += 1) {
      var li = document.createElement('li');
      li.appendChild(renderAnchor(sh.media_urls[i]));
      ul.appendChild(li);
    }
    block.appendChild(ul);
  }
  return block;
}
```

The shows-section header text is `"Shows"` (no trailing colon); the
uppercasing and letter-spacing happen in CSS (see the
`.shows-section` rule). The Inline_Script writes the plain string.

And in `renderSong`'s show loop:

```javascript
// existing:
for (var i = 0; i < s.shows.length; i += 1) {
  section.appendChild(renderShowBlock(s.shows[i]));     // OLD
  section.appendChild(renderShowBlock(s.shows[i], s.song_name));  // NEW
}
```

### URL construction: why client-side is enough

No Python helper is added to `scripts/_common.py` or
`scripts/review.py`. The URL-construction logic lives in one place —
inside the Inline_Script's `renderSearchLink`:

```javascript
var href = 'https://www.youtube.com/results?search_query='
         + encodeURIComponent(songName + ' ' + targetName);
```

There is no Python counterpart and no Python test oracle that
independently reconstructs the URL to compare against it — the
rendered `href` only exists after the browser runs the
Inline_Script, and the on-disk `.html` file contains the template +
escaped JSON payload, not the rendered anchor. The coverage
argument is layered:

- **Template ships the machinery**: a bytes-in-template test
  (Testing Strategy, Option B) asserts that
  `scripts/review_template.html` literally contains the string
  `https://www.youtube.com/results?search_query=`, the string
  `encodeURIComponent`, the helper name `renderSearchLink`, and the
  anchor class `class="yt-search"`. This proves the JS code that
  builds the URL is present in the shipped template.
- **Escape_Gate still holds**: because `renderSearchLink` reads
  strings that came out of `JSON.parse(textContent)` and passes
  them through `encodeURIComponent` and `setAttribute`, none of
  those bytes re-enter the HTML parser. The existing
  `test_escape_injection_property.py` covers this transitively (D6).
- **Rendered correctness**: that the browser actually builds the
  right `href`, renders the SVG, and opens YouTube on click is
  verified by the manual smoke checklist in Testing Strategy. This
  is the same trade-off the project already accepts for the copy
  button's clipboard behaviour (also only manually verified).

See D2 for the rationale on keeping URL construction client-side —
the alternative (server-side `urllib.parse.quote` in `_build_payload`)
would grow the payload schema with no user-visible benefit and would
violate R-No-Python.

## Correctness Properties

The rendered `<a class="yt-search">` anchors only exist in the
browser's DOM after the Inline_Script runs. The on-disk
`review_<EPOCH>.html` contains the template plus the escaped JSON
payload, not the rendered anchors. Because no Python-side DOM
simulator is updated to mirror the new link surface (R-No-Python,
Testing Strategy), these
properties describe **what is true about the browser's Rendered_DOM
after the Inline_Script runs** — the test oracle for Properties 1
and 2 is manual smoke (Testing Strategy). Properties 3 and 4
describe what is true about the on-disk HTML bytes and are covered
automatically by the existing Python test suite.

### Property 1 — Artist Search_Link on every Song_Card

_For any_ Due_Data_Payload with `len(due_songs) >= 1`, after the
browser renders the page, every Song_Card `<li data-level="...">` in
the Rendered_DOM SHALL contain exactly one descendant
`<a class="yt-search">` inside its `<div class="artist">`, whose
`href` starts with `https://www.youtube.com/results?search_query=`
AND whose query component, decoded via `decodeURIComponent`, equals
`f"{song_name} {artist_name}"` byte-for-byte.

**Validates**: the requirements this spec will declare as
R-Search-Artist.

**Test oracle**: manual smoke. Open a generated
`review_<EPOCH>.html` with at least one due song; right-click the
artist-line globe icon and confirm the target URL. Automated
coverage is indirect via the bytes-in-template test (Option B in
Testing Strategy): the template contains `renderSearchLink`, the
YouTube search URL literal, `encodeURIComponent`, and
`class="yt-search"`, proving the JS machinery that constructs the
anchor ships with the template. No Python-side DOM assertion counts
the anchors or decodes their `href`.

### Property 2 — Show Search_Link on every show row

_For any_ Due_Data_Payload and any `song` in `due_songs` with
`len(song.shows) >= 1`, after the browser renders the page, every
`<div class="show-block">` inside that Song_Card SHALL contain
exactly one child `<a class="yt-search">` whose `href` starts with
`https://www.youtube.com/results?search_query=` AND whose decoded
query component equals `f"{song_name} {show_name}"` byte-for-byte.

**Validates**: R-Search-Show.

**Test oracle**: manual smoke — same generated page as Property 1,
confirm each show row has its own globe icon and the target URL
matches. Automated coverage is the same bytes-in-template assertion
as Property 1 — the template must contain `renderShowBlock` and a
`renderSearchLink` call site for the show target.

### Property 3 — Escape_Gate preservation under the new link surface

_For any_ iteration of the existing
`tests/integration/property/test_escape_injection_property.py` test
where the hostile string lands in `song_name`, `artist_name`, or
`show_name`, after render:

- HTML-parsing the on-disk file yields exactly two `<script>`
  elements (the data block and the Inline_Script).
- The payload round-trips the hostile string byte-for-byte.

**Validates**: R-Escape-Preserve.

**Test oracle**: the existing `test_escape_injection_property.py`
test — **unmodified**. The coverage argument (D6): every byte the
new `renderSearchLink` helper reads comes out of
`JSON.parse(node.textContent)`, the same channel the existing test
gates. The helper funnels those bytes through `encodeURIComponent`
and `setAttribute`, neither of which re-enters the HTML parser. If
the existing two-`<script>` invariant and payload round-trip hold
for the current payload (the test's current assertions), they hold
transitively for the new link surface. No new property-test
iteration or assertion is added.

### Property 4 — Additive envelope invariant

_For any_ invocation of `scripts/review.py song-review` with the same
DB state and same pinned clock, the Success_Envelope on stdout SHALL
be identical to v0.1.3 (key set exactly `{"path", "due_count",
"offset"}`, same values). The Due_Data_Payload JSON inside
`<script id="due-data">` SHALL round-trip to the same dict as v0.1.3
(every per-song and per-show field identical, same orderings).

**Validates**: R-Additive, R-No-Python.

**Test oracle**: every existing test in
`tests/integration/test_review.py` and
`tests/integration/property/test_due_property.py` — all unmodified.
These already pin envelope shape, payload shape, and row-ordering;
because this spec touches no Python file and no payload-producing
code path, those tests continue to pass byte-identically with zero
edits.

## Testing Strategy

### Why Python-free testing

The feature's scope boundary (R-No-Python) rules out updating the
Python simulator at `tests/integration/_dom_sim.py` to mirror the
new `<a class="yt-search">` surface. That means no Python-side DOM
assertion can directly observe the rendered anchors — the on-disk
`review_<EPOCH>.html` contains the template plus the escaped JSON
payload; the anchors only exist after the browser runs the
Inline_Script.

Three options were considered:

**Option A — headless browser runner (Playwright, Pyppeteer).**
Rejected. The project is Python stdlib only; `requirements-dev.txt`
contains no browser-automation dependency and the CI pipeline does
not install Chromium. Adding one would be a much larger scope leak
than the feature itself.

**Option B — bytes-in-template assertion (RECOMMENDED).** Add one
small Python-side test in `tests/integration/test_review.py` that
reads `scripts/review_template.html` as bytes and uses plain
`in`-substring search (not DOM parsing, no `_dom_sim.py`). The
template ships with the Inline_Script code that builds the anchors;
asserting the template contains the required substrings proves the
JS machinery ships. Rendered correctness (href construction, SVG
rendering, aria-label substitution) is verified by manual smoke.

**Option C — manual-only.** Skip automated test additions entirely;
rely on manual smoke plus the existing Escape_Gate property test to
gate XSS. Fine, but leaves zero regression protection against
someone deleting the `renderSearchLink` helper or breaking the JS
machinery.

This spec picks **Option B**. It matches the project's stdlib-only
Python-test discipline, needs no new tooling, and adds a
meaningfully-low-false-negative guard against accidental machinery
removal.

### Existing tests that stay unchanged

All of these continue to pass byte-identically. Zero assertion
edits, zero iteration-count changes, zero file-touches in the
test suite beyond the one new function described below.

- **`tests/integration/test_review.py`** — every existing test in
  the file. The full list of existing assertions is untouched:
  - Output path scheme (`output/review_<EPOCH>.html`).
  - Output dir creation on demand.
  - Envelope shape `{"path", "due_count", "offset"}` and values.
  - Empty-state render.
  - Happy-path render (payload fields).
  - Display-level carry-through.
  - HTML injection escape (`<script>alert(1)</script>` in song name
    round-trips in payload; exactly two `<script>` elements in the
    document; `\u003c/script\u003e` escape present).
  - Media-url `"` escape.
  - Soft-delete / graduated filtering.
  - Soft-deleted show exclusion.
  - Missing-template INTERNAL_ERROR.
  - Missing-marker INTERNAL_ERROR.
  - `--offset` surface parity with `learning.py due`.
  - `--offset 0` envelope key-set preservation.
  - `--help` / no-args help surface.
  - Read-only DB invariant.
- **`tests/integration/property/test_due_property.py`** — unchanged.
- **`tests/integration/property/test_escape_injection_property.py`**
  — unchanged. The existing two-`<script>`-elements invariant and
  the payload round-trip assertion already gate injection into the
  template; the new Search_Link surface is constructed client-side
  from already-escaped payload values read out of
  `JSON.parse(textContent)`, so the existing gate covers it
  transitively (D6, Property 3). No new assertion or iteration is
  added.
- **`tests/integration/_dom_sim.py`** — unchanged. The simulator
  will NOT grow mirror nodes for the new `<a class="yt-search">`
  anchors (R-No-Python). Existing structural tests that consume the
  simulator assert on DOM shape they already know about (positive
  claims about existing surfaces); none of them make negative
  claims like "the `<div class="artist">` contains exactly N
  children" that would be falsified by an added sibling. The
  rendered browser DOM diverges from the simulator for the new
  link surface and that is explicitly accepted.
- Every other property test in `tests/integration/property/` —
  unchanged.

### New test to add

Exactly one new test function lives in
`tests/integration/test_review.py` alongside the existing ones. It
follows the existing file's style but uses a much simpler oracle —
read the template bytes, assert on six substrings.

**`test_template_ships_youtube_search_link_machinery`** — reads
`scripts/review_template.html` as bytes and asserts the file
contains each of the following substrings (plain `in` checks, no
DOM parsing, no JS parsing, no payload needed):

1. `b"renderSearchLink"` — the JS helper name. Gates "the helper
   still exists in the template".
2. `b"https://www.youtube.com/results?search_query="` — the YouTube
   search URL literal. Gates "the anchor points at YouTube".
3. `b"encodeURIComponent"` — the client-side URL encoder. Gates
   "the helper percent-encodes before building the href"; catches
   the regression where someone swaps in raw string concatenation.
4. `content.count(b"yt-search") >= 2` — the `yt-search` token
   must appear at least twice in the template: once in the CSS
   selector (`.yt-search`) and once in the JS class assignment
   (`a.className = 'yt-search'`). Relaxed from the originally-planned
   literal `b'class="yt-search"'` because the shipped Inline_Script
   sets the class via `a.className` (no quoted HTML attribute lands
   in the template bytes). The two forms are equivalent by intent
   because the CSS block itself guarantees the class name ships —
   if someone deleted the `a.className = 'yt-search'` line, the
   anchor would still render (without the class) and the CSS
   selector would orphan; the count-≥-2 check catches that
   regression because deleting either site drops the count to one
   or zero.
5. `b"aria-label"` AND, in bytes proximity, `b"Search YouTube"` —
   the accessibility contract. The proximity test is done as two
   independent `in` checks plus an `abs(find(a) - find(b)) < 500`
   byte-window check, which is more than enough to catch the
   helper being deleted while still letting the Inline_Script lay
   out its functions in any order.
6. `b"noopener noreferrer"` — the link-safety contract. Relaxed
   from the originally-planned literal `b'rel="noopener noreferrer"'`
   because the shipped Inline_Script pairs the rel attribute via
   `setAttribute('rel', 'noopener noreferrer')` with single quotes,
   so the bytes `rel="noopener noreferrer"` (double-quoted) never
   appear. The shorter substring still gates the safety contract —
   if the `noopener noreferrer` token is present anywhere in the
   template, the only place it can live is in the
   `setAttribute('rel', ...)` call that wires it onto the anchor.

The test is intentionally coarse — it does not parse JavaScript, it
does not try to build an AST, it does not simulate the browser. It
reads raw bytes and asserts six substrings appear. If all six are
present, the feature's machinery ships with the release; if any is
missing (e.g. someone accidentally dropped `encodeURIComponent` in
a refactor), the test fails with an obvious "substring X not found
in template".

### Manual smoke checklist

Automated coverage stops at "the machinery ships". Rendered
correctness is verified by one run of the manual smoke checklist
below whenever the template's `<script>` or `<style>` changes:

1. Populate the test DB with at least one due song that belongs to
   at least two shows. Run `python scripts/review.py song-review`
   and open the resulting `output/review_<EPOCH>.html` in a
   browser.
2. **Globe icons render.** Confirm a small globe icon appears next
   to the artist name on the song card AND next to each show name
   in the shows block. The icon should be crisp at 16 px; it should
   pick up `currentColor` (i.e. the accent blue).
3. **Artist link works.** Click the artist-line globe. Confirm
   YouTube opens in a new tab with the search query
   `<song_name> <artist_name>`.
4. **Show link works.** Click any show-line globe. Confirm YouTube
   opens in a new tab with the search query
   `<song_name> <show_name>`.
5. **Keyboard focus.** Tab through the page. Confirm each globe
   anchor receives a visible focus ring (the
   `.yt-search:focus-visible` rule) and Enter activates the link.
6. **Screen-reader text.** Inspect one of the globe anchors in the
   browser's devtools; confirm the `aria-label` reads
   `Search YouTube for <song_name> by <artist_name>` (artist) or
   `Search YouTube for <song_name> in <show_name>` (show). A full
   screen-reader run is out of scope.
7. **Polish_Scope visual.** Resize the window narrower than a song
   name. Confirm the artist line and show block wrap the globe
   icon and copy button onto the next line gracefully rather than
   overflowing.

If any smoke step fails, the release does not ship. The checklist
lives in the release PR description.

### Polish_Scope testing

CSS changes are not unit-tested. Verification is:

- **Static**: the diff changes selectors that already exist
  (`li[data-level]`, `.artist`, `.show-block`, `.show-meta`,
  `.links`) plus four new selectors (`.yt-search`,
  `.yt-search:hover`, `.yt-search:focus-visible`, `.yt-search-icon`).
  No selector gets removed. This preserves every existing
  static-template assertion in `test_review.py` that looks for
  class names by substring.
- **Visual**: manual smoke — step 7 of the checklist above.

No screenshot tests, no Puppeteer. Out of scope for a stdlib-only
project.

### Accessibility testing

- The bytes-in-template test pins that `aria-label`, `Search
  YouTube`, and `rel="noopener noreferrer"` all ship in the
  template.
- Manual smoke step 5 confirms keyboard focus.
- Manual smoke step 6 spot-checks the rendered `aria-label` text.
- Full WCAG validation is out of scope for this feature; see
  Rollout.

## Out of Scope

Explicitly not part of this spec. Listed to prevent scope creep.

- **Fetching or verifying the YouTube search result.** Whether the
  search returns the right video is browser + YouTube behavior; we
  only construct the URL.
- **Non-YouTube fallback providers** (Spotify search, Bandcamp
  search, arbitrary user-configured search engine). If added later,
  that would grow the payload additively with a small lookup object.
- **Dark mode / theming.** Polish_Scope is layout, padding,
  hierarchy, and wrapping — no color-scheme media query, no CSS
  custom properties for theme-switching, no new color tokens beyond
  the minor accent tweaks in D5.
- **Skill-doc updates.** `skills/reviewing-songs/SKILL.md` is not
  modified. The feature is discoverable in the rendered page itself —
  a reviewer sees the globe icons and intuits "click this if the
  direct link breaks". The skill doc's job is to tell the agent how
  to run the pipeline, not to enumerate every UI affordance.
- **Any Python production-file changes.** R-No-Python pins the
  scope boundary: no script in `scripts/` is modified, no existing
  test is modified, and no file in `tests/integration/property/` is
  touched. `scripts/review.py`, `scripts/_common.py`,
  `scripts/learning.py`, `tests/integration/_dom_sim.py`, and every
  property test stay byte-identical. The only Python-file edit in
  this release is one new test function in
  `tests/integration/test_review.py` that reads the template as
  bytes and asserts on six literal substrings.
- **Server-side URL construction in `_build_payload`.** Could be
  done in a future pass if a server-side URL becomes valuable (for
  example to plumb analytics or a non-YouTube fallback). Out of
  scope for this release — URL construction lives in the browser
  (D2).
- **Full WCAG 2.x conformance validation.** The `aria-label`,
  `rel="noopener noreferrer"`, and native focus handling are the
  concrete a11y affordances this spec commits to. Broader WCAG
  validation is out of scope for a one-commit polish release.
- **Changes to `scripts/_common.py`.** Subsumed by "Any Python-file
  changes" above — no shared URL helper is added.

## Rollout

- **Release vehicle**: v0.1.4 through the existing release pipeline
  (`.github/workflows/release.yml`). No pipeline changes.
- **Commit shape**: one commit.
  `feat(review): polish review page and add YouTube-search fallback links`
  — scope `review` matches the other recent review-page commits in
  `release.md`.
- **Schema**: no change. `scripts/_common.py:EXPECTED_SCHEMA` is
  untouched.
- **Payload schema**: no change in this release (additive-only
  invariant preserved by zero additions — see D4).
- **CLI surface**: no change. `review.py song-review --offset N`
  continues to accept the `--offset` flag added in v0.1.3. No new
  flags.
- **File delta** (exhaustive — the spec's diff is exactly these
  three files, nothing else):
  - `scripts/review_template.html` — a full rewrite of the `<style>`
    block (card + chip Polish_Scope, D5) plus `<script>` additions
    (the `renderSearchLink` helper, its two call sites, and the new
    `.show-head` inner wrapper that `renderShowBlock` builds inside
    each Show_Chip). Marker line and `<script id="due-data">`
    unchanged.
  - `tests/integration/test_review.py` — one new test function
    (`test_template_ships_youtube_search_link_machinery`), a
    bytes-in-template assertion over six substrings (4 and 6
    relaxed to match how the shipped template wires the
    `yt-search` class and the `noopener noreferrer` rel —
    `content.count(b"yt-search") >= 2` and `b"noopener noreferrer"`
    respectively). Every other test in the file is byte-identical.
  - `release.md` — one bullet under v0.1.4 describing polish +
    search-link fallback.

  **Zero Python production files touched, zero existing Python
  tests modified.** `scripts/review.py`, `scripts/_common.py`,
  `tests/integration/_dom_sim.py`, every existing test in
  `tests/integration/test_review.py`, and every property test
  (including
  `tests/integration/property/test_escape_injection_property.py`
  and `tests/integration/property/test_due_property.py`) stay
  byte-identical. The only Python-file edit is the one new test
  function in `tests/integration/test_review.py` listed above.
  R-No-Python is the hard scope boundary.
- **Risk**: low. Diff is confined to the template and one test
  file. The existing full Python suite — byte-identical in this
  release — gates payload, envelope, DOM shape, and Escape_Gate;
  the one new bytes-in-template test gates the presence of the new
  link-surface machinery.
- **Rollback**: trivial — revert the commit. Previously-generated
  `review_<EPOCH>.html` files are self-contained and keep working;
  only new generations would revert to the v0.1.3 look.
