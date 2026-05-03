# Feature Requirements Document

## Introduction

Two small, coordinated improvements to the Review_Page landing at
`App_Root/output/review_<EPOCH>.html`. First, the page is given a
full card-and-chip treatment: each song lifts into a white,
rounded, subtly-shadowed card with a hover-lift; each show inside
it wraps into a rounded chip with a soft indigo left-accent bar so
individual shows read as discrete items rather than nested list
rows. The level pill softens to a pastel fully-rounded shape, show
meta fields join with middle-dot separators, per-show media-URL
lists stack below each chip's header row with arrow glyphs in place
of disc bullets, and the default `<ol>` bullet is suppressed in
favor of a CSS counter. Second, a one-click YouTube-search fallback
is added next to the artist name on every Song_Card and next to the
show name inside every Show_Chip — a small inline Globe_Icon
wrapping an `<a>` whose `href` points at
`https://www.youtube.com/results?search_query=<encoded>` computed
client-side from the payload's `song_name`, `artist_name`, and
`show_name` fields. The existing per-show `media_urls` list keeps
rendering unchanged; the Search_Links are an escape hatch for when
a stored link is broken, geoblocked, or empty, not a replacement
for it.

The feature is implemented entirely in `scripts/review_template.html`
— CSS inside `<style>` (the Polish_Scope rewrites) and JavaScript
inside the Inline_Script (the `renderSearchLink` helper plus two
call-site additions). **No Python production file in the repo is
modified.** `scripts/review.py`, `scripts/_common.py`, and
`tests/integration/_dom_sim.py` stay byte-identical to v0.1.3, as do
every existing test in `tests/integration/test_review.py` and every
property test under `tests/integration/property/`. The only
Python-file edit in this release is one new test function in
`tests/integration/test_review.py` that reads
`scripts/review_template.html` as bytes and asserts the file contains
six literal substrings — a coarse, low-false-negative guard against
accidentally dropping the YouTube-search machinery in a future
refactor. No schema change, no new error code, no CLI surface change,
no payload-shape change. This invariant (R-No-Python) is the hard
scope boundary for the release.

## Glossary

- **Review_Page**: The HTML file written to
  `App_Root/output/review_<EPOCH>.html` by `scripts/review.py
  song-review`.
- **Template_File**: `scripts/review_template.html`. Contains a
  `<!-- DUE_DATA_JSON -->` marker that `scripts/review.py` substitutes
  with the JSON-escaped Due_Data_Payload at render time.
- **Due_Data_Payload**: The JSON document built by
  `scripts/review.py._build_payload`. Shape is frozen by the existing
  `review-html-enhancements` contract; any new fields this feature
  adds are **additive only**, and in this release the delta is zero
  fields.
- **Inline_Script**: The single `<script>` at the bottom of the
  Template_File. Runs on DOMContentLoaded, reads the JSON payload
  from `<script id="due-data">`, and builds the Rendered_DOM.
- **Song_Card**: One `<li data-level="N">` node inside the
  Rendered_DOM. Contains the level pill, song title, artist line,
  and shows section.
- **Search_Link**: The new `<a class="yt-search">` element this
  feature introduces. Wraps a small inline Globe_Icon. `href` points
  at `https://www.youtube.com/results?search_query=...`. One next to
  the artist name on every Song_Card; one next to every show name
  inside the `<div class="show-block">`.
- **Escape_Gate**: The `_escape_json_for_html` pass in
  `scripts/review.py` that rewrites `<`, `>`, and `&` in the
  serialised payload to `\u003c`, `\u003e`, and `\u0026` before the
  payload lands inside `<script type="application/json">`. The
  property test `tests/integration/property/test_escape_injection_property.py`
  is the oracle for this gate.
- **Polish_Scope**: The visual tightening pinned in Design Decision
  D5 — consistent padding scale, clearer weight/color hierarchy,
  softer dividers, flex-wrap on the artist line and show block.
  Explicitly does not include dark mode, theming, font family
  changes, or color-scheme media queries.
- **Show_Chip**: The rounded, left-accented inner panel that wraps
  one show inside a Song_Card — introduced by this release. A
  `<div class="show-block">` with its own background, rounded
  corners, and a 3 px indigo left border. Contains a
  `<div class="show-head">` row (name + copy + meta + globe) and,
  below it, the per-show `<ul class="links">`.
- **Globe_Icon**: The inline monochrome SVG (Design Decision D1)
  rendered inside every Search_Link. 16×16, `viewBox="0 0 16 16"`,
  `aria-hidden="true"`, `stroke="currentColor"` so the
  Polish_Scope's accent color flows through.
- **Rendered_DOM**: The DOM the browser builds after the
  Inline_Script runs. Distinct from the on-disk HTML bytes, which
  contain the template plus the escaped JSON payload but not the
  rendered anchors.

## User Stories

Two personas are addressed.

- **Reviewing_Agent**: the AI agent driving the review session.
  Opens the Review_Page, works through due songs, needs fast escape
  hatches when stored media links fail.
- **Human_Reviewer**: a person opening `review_<EPOCH>.html` in a
  browser directly — keyboard-only, screen-reader, or mouse.

### Story 1: Visually polished review page (R-Polish)

**User Story:** As a Reviewing_Agent and as a Human_Reviewer, I want
the Review_Page to read as a clean vertical stack of Song_Cards on
any reasonable viewport, so that long song names, artist names, and
show lists do not collide with the copy button, overflow the card
edge, or lose visual hierarchy.

#### Acceptance Criteria

1.1 WHEN the Review_Page renders THEN the Template_File SHALL
render each Song_Card (`li[data-level]`) as an individual white
panel with `background: #ffffff`, `1px solid #e5e7eb` border,
`border-radius: 10px`, and a subtle drop shadow
(`box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04)`); AND WHEN a
Song_Card receives `:hover` THEN the Template_File SHALL darken
the border to `#d1d5db` and deepen the shadow to
`0 2px 8px rgba(15, 23, 42, 0.08)` so the card visibly lifts.

1.2 WHEN the Review_Page renders THEN the enclosing `<ol>` SHALL
carry `list-style-position: outside; padding: 0; margin: 0;
counter-reset: song-counter`, AND each Song_Card SHALL render its
position number via a CSS counter `::before`
(`counter-increment: song-counter; content: counter(song-counter)
"."`) in muted gray (`#9ca3af`) so the default browser `<ol>`
bullet is suppressed and replaced by a counter-driven numeral
styled to match the card.

1.3 WHEN the Review_Page renders THEN the level pill (`.level`)
SHALL render as a fully-rounded pastel pill — `background: #eff6ff;
color: #1d4ed8; border: 1px solid #dbeafe; border-radius: 999px;
font-weight: 600; font-size: 0.78em` — rather than a solid-blue
badge.

1.4 WHEN the Review_Page renders a Song_Card with at least one
show THEN every `<div class="show-block">` SHALL render as a
Show_Chip with its own background `#f9fafb`, `1px solid #e5e7eb`
border, a 3 px indigo left accent bar
(`border-left: 3px solid #a5b4fc`), `border-radius: 6px`, and
padding `0.55em 0.8em`; AND the shows SHALL stack vertically
inside the shows section (`display: block` with top margin
`0.5em`) rather than laying out as a shared flex row.

1.5 WHEN the Inline_Script renders a Show_Chip THEN the chip
SHALL contain exactly one inner `<div class="show-head">` child
that wraps the show name span + copy button + optional show-meta
span + show-level Search_Link onto a single row
(`display: flex; flex-wrap: wrap; align-items: center; gap:
0.35em`), AND the per-show `<ul class="links">` SHALL be a
sibling of `.show-head` (a child of `.show-block`) so the links
stack below the header row on their own lines.

1.6 WHEN the Review_Page renders THEN the shows-section label
(`.shows-section`) SHALL be styled with `text-transform:
uppercase; letter-spacing: 0.04em; font-size: 0.85em; color:
#6b7280; font-weight: 500`, AND the Inline_Script SHALL set its
text content to the plain string `"Shows"` with no trailing
colon; the uppercased appearance SHALL come entirely from CSS.

1.7 WHEN the Review_Page renders a Show_Chip with non-empty
`media_urls` THEN the per-show `<ul class="links">` SHALL carry
`list-style: none` and each `<li>` SHALL render a leading `↳ `
arrow glyph in `#9ca3af` via a `::before` pseudo-element, so
disc-style browser bullets are suppressed in favor of the arrow
prefix.

1.8 WHEN the Inline_Script renders a Show_Chip's meta span THEN
non-empty values among `show_name_romaji`, `show_vintage`, and
`show_s_type` SHALL be joined with ` · ` (space-padded middle
dot) and the result SHALL be prefixed with `· ` (middle-dot +
space), so a complete meta reads as `· romaji · 2015 · TV`
rather than the v0.1.3 ` — romaji, 2015, TV` form.

1.9 WHEN the Polish_Scope diff is applied THEN the Template_File
SHALL NOT remove any existing CSS selector — every class name
present in v0.1.3 (`level`, `song`, `name-context`, `artist`,
`shows-section`, `show-block`, `show-name`, `show-meta`, `links`,
`copy-btn`) SHALL CONTINUE TO be referenced by the stylesheet,
AND new selectors (`.show-head`, `.yt-search`, `.yt-search:hover`,
`.yt-search:focus-visible`, `.yt-search-icon`, plus the
`li[data-level]::before` and `.links li::before` pseudo-elements)
SHALL be added alongside so existing static-template substring
assertions in `tests/integration/test_review.py` do not regress.

### Story 2: YouTube search link next to the artist (R-Search-Artist + R-A11y artist half)

**User Story:** As a Reviewing_Agent, I want a one-click path to
search YouTube for the `<song_name> <artist_name>` combination when
the stored artist-level media links are broken or missing, so that I
have a fast escape hatch without leaving the Review_Page.

#### Acceptance Criteria

2.1 WHEN the Inline_Script renders a Song_Card THEN every
`<div class="artist">` SHALL contain exactly one `<a
class="yt-search">` descendant, appended after the existing copy
button.

2.2 WHEN the Inline_Script builds the artist Search_Link's `href`
THEN the href SHALL be
`https://www.youtube.com/results?search_query=` concatenated with
`encodeURIComponent(song_name + ' ' + artist_name)` — the
single-space separator is a literal ASCII `' '` and
`encodeURIComponent` rewrites it to `%20`.

2.3 WHEN the Inline_Script builds the artist Search_Link THEN the
anchor SHALL carry `target="_blank"` AND
`rel="noopener noreferrer"` so activating the link opens YouTube in
a new tab without tab-napping or referrer leakage.

2.4 WHEN the Inline_Script builds the artist Search_Link THEN the
anchor SHALL carry `aria-label="Search YouTube for <song_name> by
<artist_name>"` where `<song_name>` and `<artist_name>` are the
payload's literal string values, unescaped (the browser treats
`setAttribute('aria-label', ...)` as a string, not as markup).

2.5 WHEN the Inline_Script builds the artist Search_Link THEN the
anchor SHALL wrap exactly one Globe_Icon child (see Story 5 for the
Globe_Icon criteria).

### Story 3: YouTube search link next to each show (R-Search-Show + R-A11y show half)

**User Story:** As a Reviewing_Agent, I want a per-show one-click
path to search YouTube for the `<song_name> <show_name>`
combination when a show's direct `media_urls` entries are broken,
so that I can fall back per show rather than per artist.

#### Acceptance Criteria

3.1 WHEN the Inline_Script renders a Song_Card with at least one
show THEN every `<div class="show-block">` inside that Song_Card
SHALL contain exactly one child `<a class="yt-search">`, appended
after the existing copy button and before the per-show `<ul
class="links">`.

3.2 WHEN the Inline_Script builds a show Search_Link's `href` THEN
the href SHALL be
`https://www.youtube.com/results?search_query=` concatenated with
`encodeURIComponent(song_name + ' ' + show_name)`, using the
enclosing Song_Card's `song_name` threaded through to
`renderShowBlock(sh, songName)` as its second parameter.

3.3 WHEN the Inline_Script builds a show Search_Link THEN the
anchor SHALL carry `target="_blank"` AND
`rel="noopener noreferrer"`.

3.4 WHEN the Inline_Script builds a show Search_Link THEN the
anchor SHALL carry `aria-label="Search YouTube for <song_name> in
<show_name>"` where `<song_name>` and `<show_name>` are the
payload's literal string values, unescaped.

3.5 WHEN the Inline_Script renders a show block THEN the existing
per-show `<ul class="links">` list of `media_urls` SHALL CONTINUE
TO render unchanged — the Search_Link is an additional sibling, not
a replacement for the existing links.

### Story 4: Accessibility and keyboard navigation (R-A11y)

**User Story:** As a Human_Reviewer using keyboard-only navigation
or a screen reader, I want every Search_Link to be reachable,
announced sensibly, and visibly focused, so that the escape hatch
is usable without a pointing device.

#### Acceptance Criteria

4.1 WHEN a Human_Reviewer tabs through the Review_Page THEN every
Search_Link SHALL receive keyboard focus via the native `<a
href="...">` tab order — no custom `tabindex` is needed and none is
added.

4.2 WHEN a Search_Link receives keyboard focus THEN the
Template_File's `.yt-search:focus-visible` rule SHALL render a
visible focus ring (`outline: 2px solid #6366f1; outline-offset:
2px;`) so the focused anchor is distinguishable from its
neighbours.

4.3 WHEN a screen reader encounters a Search_Link THEN the
Inline_Script SHALL set `aria-hidden="true"` on the Globe_Icon SVG
so the reader announces the parent anchor's `aria-label` instead of
the SVG's element tree.

4.4 WHEN a Human_Reviewer presses Enter while a Search_Link is
focused THEN the browser's native `<a>` behaviour SHALL activate
the link (the Inline_Script attaches no custom key handler — Enter
activation is native).

### Story 5: Offline-first globe icon (R-No-Network)

**User Story:** As a Human_Reviewer opening the Review_Page offline
(the project runs fully local), I want the Globe_Icons to render
without any network fetch, so that the page is self-contained and
works with Wi-Fi off.

#### Acceptance Criteria

5.1 WHEN the Inline_Script builds a Globe_Icon THEN the icon SHALL
be an inline SVG constructed via `document.createElementNS` in the
SVG namespace — no `<img src="...">`, no `@font-face` icon-font, no
CDN URL, no external asset.

5.2 WHEN a Globe_Icon is rendered THEN the SVG SHALL carry
`width="16"`, `height="16"`, and `viewBox="0 0 16 16"`.

5.3 WHEN a Globe_Icon is rendered THEN every stroked child element
SHALL use `stroke="currentColor"` so the Polish_Scope's accent
color (`.yt-search { color: #0a84ff; }`) flows through to the
icon's strokes.

5.4 WHEN `scripts/review.py song-review` writes its output THEN the
script SHALL CONTINUE TO emit exactly one file per invocation
(`App_Root/output/review_<EPOCH>.html`) — no sibling SVG, CSS, or
asset file SHALL be added alongside it.

### Story 6: Escape_Gate preservation under the new link surface (R-Escape-Preserve)

**User Story:** As any user of the Review_Page, I want XSS safety to
stay airtight even when a song name, artist name, or show name
contains hostile characters like `<script>` or `</script>`, so that
adding the Search_Link surface does not open a new injection
vector.

#### Acceptance Criteria

6.1 WHEN `scripts/review.py song-review` renders a payload whose
`song_name`, `artist_name`, or `show_name` contains a hostile
substring (for example `<script>alert(1)</script>` or `</script>`)
THEN HTML-parsing the resulting `review_<EPOCH>.html` SHALL
CONTINUE TO yield exactly two `<script>` elements — the
`<script id="due-data">` payload block and the Inline_Script.

6.2 WHEN the Inline_Script parses its payload via
`JSON.parse(node.textContent)` THEN the parsed `song_name`,
`artist_name`, and `show_name` strings SHALL CONTINUE TO round-trip
byte-for-byte through the payload — every hostile byte appears in
the parsed string exactly as it appeared in the caller's input.

6.3 WHEN the `renderSearchLink` helper consumes a payload string
THEN the helper SHALL pass the string into the DOM only through
`setAttribute('href', encodeURIComponent(...))`,
`setAttribute('aria-label', ...)`, `document.createElement`, and
`document.createElementNS` — never through `innerHTML`,
`outerHTML`, `insertAdjacentHTML`, or any other parser-re-entry
API.

6.4 WHEN the existing property test
`tests/integration/property/test_escape_injection_property.py` runs
against the post-feature Template_File THEN the test SHALL CONTINUE
TO pass with zero assertion edits and zero iteration-count
changes — the two-`<script>`-elements invariant and payload
round-trip are the oracle for this story.

### Story 7: Byte-identical Python surface (R-Additive + R-No-Python)

**User Story:** As a release engineer, I want this release to be
confidently reversible and to avoid any chance of regressing the
Python code path, so that a rollback is a trivial `git revert` and
the payload / envelope / schema contracts stay pinned.

#### Acceptance Criteria

7.1 WHEN the release is applied THEN `scripts/review.py` SHALL
CONTINUE TO be byte-identical to its v0.1.3 contents — no edit to
`_build_payload`, `_render_page`, `_escape_json_for_html`,
`_cmd_song_review`, `_DUE_SQL`, the argparse surface, or any other
symbol.

7.2 WHEN the release is applied THEN `scripts/_common.py` SHALL
CONTINUE TO be byte-identical to its v0.1.3 contents.

7.3 WHEN the release is applied THEN `tests/integration/_dom_sim.py`
SHALL CONTINUE TO be byte-identical to its v0.1.3 contents — the
simulator does NOT mirror the new `<a class="yt-search">` anchors
and the release accepts the simulator/browser divergence on the
Search_Link surface.

7.4 WHEN the full test suite runs against the post-feature tree
THEN every existing test in `tests/integration/test_review.py`
SHALL CONTINUE TO pass with zero assertion edits and zero
iteration-count changes.

7.5 WHEN the full test suite runs against the post-feature tree
THEN every property test under `tests/integration/property/` SHALL
CONTINUE TO pass with zero assertion edits and zero
iteration-count changes.

7.6 WHEN `scripts/review.py song-review` emits its Success_Envelope
THEN the envelope's key set SHALL CONTINUE TO be exactly
`{"path", "due_count", "offset"}` with the same semantics and types
as v0.1.3; the Due_Data_Payload's per-song and per-show field sets
SHALL CONTINUE TO match v0.1.3 byte-for-byte under the same DB
state and pinned clock.

7.7 WHEN the release diff against v0.1.3 is inspected THEN the only
Python-file edit SHALL be the addition of one new test function
`test_template_ships_youtube_search_link_machinery` in
`tests/integration/test_review.py` — no other Python file in the
repo SHALL be modified by this feature.

### Story 8: Shipped-machinery regression guard (bytes-in-template test)

**User Story:** As a release engineer, I want a cheap automated
guard against accidentally dropping the YouTube-search machinery
from the Template_File in a future refactor, so that a rename,
reformat, or template rewrite cannot silently remove the feature.

#### Acceptance Criteria

8.1 WHEN the release is applied THEN `tests/integration/test_review.py`
SHALL contain exactly one new test function,
`test_template_ships_youtube_search_link_machinery`, added
alongside the existing tests.

8.2 WHEN `test_template_ships_youtube_search_link_machinery` runs
THEN the test SHALL read `scripts/review_template.html` as bytes
(via `Path.read_bytes` or equivalent) and SHALL assert the file
contains each of the following six substrings via plain `in`
checks (bullets 4 and 6 are relaxed from the originally-planned
literal attribute forms to match how the shipped Inline_Script
wires the class and rel attributes):

  - `b"renderSearchLink"` — the JS helper name.
  - `b"https://www.youtube.com/results?search_query="` — the
    YouTube search URL literal.
  - `b"encodeURIComponent"` — the client-side URL encoder.
  - `b"yt-search"` appearing at least twice in the template —
    `content.count(b"yt-search") >= 2` — so the token shows up
    once in the CSS (`.yt-search`) and once in the JS class
    assignment (`a.className = 'yt-search'`); the originally-
    planned literal `b'class="yt-search"'` is not emitted by
    the shipped template because the class is set via
    `a.className` rather than an inline HTML attribute.
  - `b"aria-label"` AND `b"Search YouTube"`, with the two
    substrings appearing within a 500-byte proximity window (i.e.
    `abs(find(a) - find(b)) < 500`) so the assertion catches the
    helper being deleted while still letting the Inline_Script
    order its functions freely.
  - `b"noopener noreferrer"` — the link-safety contract. Relaxed
    from `b'rel="noopener noreferrer"'` because the shipped
    Inline_Script pairs the rel attribute via
    `setAttribute('rel', 'noopener noreferrer')` with single
    quotes, so the double-quoted HTML-attribute form never
    appears in the template bytes.

8.3 WHEN `test_template_ships_youtube_search_link_machinery` runs
THEN the test SHALL NOT parse the template as HTML, SHALL NOT parse
JavaScript, SHALL NOT require a Due_Data_Payload, and SHALL NOT
invoke `scripts/review.py` via subprocess — the test is a plain
bytes-in-file substring check and nothing more.

## Non-Goals (Out of Scope)

The following are explicitly out of scope for this release. Each is
listed to prevent scope creep during implementation and review.

- **Fetching or verifying the YouTube search result.** Whether the
  search returns the right video is browser + YouTube behavior; the
  feature only constructs the URL.
- **Non-YouTube fallback providers.** Spotify search, Bandcamp
  search, or an arbitrary user-configured search engine are not
  added. If added later, the payload would grow additively with a
  small lookup object.
- **Dark mode or theming.** The Polish_Scope is layout, padding,
  hierarchy, and wrapping — no color-scheme media query, no CSS
  custom properties for theme-switching, no new color tokens
  beyond the minor accent tweaks in Design Decision D5.
- **Skill-doc updates.** `skills/reviewing-songs/SKILL.md` is not
  modified. The Search_Links are discoverable in the rendered page
  itself; the skill doc's job is to tell the agent how to run the
  pipeline, not to enumerate every UI affordance.
- **Any Python production-file changes.** R-No-Python pins the
  scope boundary — `scripts/review.py`, `scripts/_common.py`,
  `scripts/learning.py`, `tests/integration/_dom_sim.py`, and every
  file under `tests/integration/property/` stay byte-identical.
- **Server-side URL construction in `_build_payload`.** URL
  construction lives in the browser (Design Decision D2); no
  Python helper is added to `_common.py` or elsewhere.
- **Full WCAG 2.x conformance validation.** The `aria-label`,
  `rel="noopener noreferrer"`, `aria-hidden="true"` on the SVG, and
  native focus handling are the concrete a11y affordances this
  feature commits to; broader WCAG validation requires manual
  testing with assistive technologies and is out of scope for a
  one-commit polish release.
- **Changes to `scripts/_common.py`.** Subsumed by the no-Python
  boundary above; no shared URL helper is added.

## Release Constraints

This feature ships as v0.1.4 through the existing release pipeline
(`.github/workflows/release.yml`), one commit, scope `review`. No
CLI flag is added, no schema or payload shape changes, no new error
code, and the existing Success_Envelope key set
(`{"path", "due_count", "offset"}`) and Due_Data_Payload field set
stay byte-identical to v0.1.3. Zero existing Python tests are
edited; exactly one new Python test function is added to
`tests/integration/test_review.py`. The release diff is limited to
three files — `scripts/review_template.html` (Polish_Scope CSS plus
the Inline_Script additions), `tests/integration/test_review.py`
(the one new bytes-in-template test function), and `release.md`
(one bullet under v0.1.4). Post-release the suite runs at 481
passing tests with 95% line coverage across `scripts/`. Rollback is
a trivial revert; previously-generated `review_<EPOCH>.html` files
are self-contained and keep working.
