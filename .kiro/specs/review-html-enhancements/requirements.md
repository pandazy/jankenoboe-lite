# Requirements Document

## Introduction

This spec extends the HTML review page produced by `scripts/review.py` (see
Requirement 8 of the `anime-song-learning-app` spec) with four usability
features drawn from the original jankenoboe template, plus one small
packaging fix for `tools/package.py`.

The four review-page features are:

1. **Short-name media URL links** — show the filename as the link text,
   keep the full URL in `href`.
2. **Group media URLs by show** — instead of a single flat URL list per
   due song, list each show's URLs under that show.
3. **Copy buttons for song / show / artist IDs** — a small inline
   button next to each name that puts the UUID on the clipboard.
4. **Alternating highlight on click** — clicking a song `<li>` toggles a
   "done for this session" visual marker.

These four features ride on a fifth, foundational change (item 0 below):

0. **Data-only Python, template-based rendering.** `scripts/review.py`
   stops emitting HTML fragments. It becomes a data pipeline that
   outputs one JSON payload describing the due songs. All HTML/CSS/JS
   lives in a single template file. The template carries the payload
   as inline JSON inside a `<script type="application/json">` tag,
   and the template's inline JavaScript renders the DOM client-side
   from that payload.

The packaging fix is item 5 — start shipping `skills/` in the deployable
zip (so Claude working against the deployed tree can see the skill docs)
and keep the `.kiro/` dev folder out of it. The exclusion model gets
documented explicitly in `tools/package.py`.

All runtime constraints from the parent spec still hold: Python 3.10+,
stdlib only, no third-party runtime deps. The inline JavaScript runs in
the user's browser, not on the deploy target, so adding it does not
widen the Python runtime surface.

This document reuses (does not re-state) the contracts defined by the
`anime-song-learning-app` spec, in particular:

- R8 (HTML Review Page) — output path, `html.escape` usage, empty-state
  rendering, no-DB-writes. Requirement R-RH-1 below refines R8.3: the
  Review_Page is still built without a third-party template engine, but
  the document chrome moves out of Python into a static HTML file that
  `scripts/review.py` substitutes a single JSON payload into.
- R17 (Level Display) — `display_level` = stored level + 1.
- R20 (Packaging) — the single source of truth for what ships in the
  deployable zip. Requirement R-RH-7 below extends R20.2's copy list
  to include `skills/`, keeps `.kiro/` off the list, and documents the
  exclusion model.

## Glossary

Terms from the parent `anime-song-learning-app` spec (App_Root, Script,
DB_File, Song, Artist, Show, UUID, now_epoch, etc.) apply here as
defined there. The terms below are specific to this spec.

- **Template_File**: A static HTML file shipped under `scripts/` (path:
  `scripts/review_template.html`). It contains the full document
  chrome — `<!DOCTYPE html>` through `</html>` — with CSS, an inline
  `<script>` that renders the DOM, and a single substitution marker
  where `scripts/review.py` injects the Due_Data_Payload. No HTML tag
  appears in any Python source file under `scripts/`.
- **Due_Data_Payload**: A JSON document produced by `scripts/review.py`
  from the due query results, containing every field the Template_File
  needs to render the page. See the design doc for the exact shape.
  The payload is embedded inside a `<script id="due-data"
  type="application/json">...</script>` element in the rendered
  Review_Page.
- **Review_Page**: The HTML document written by `review.py song-review`
  to `App_Root/output/review_<EPOCH>.html` per the parent R8 contract.
  One file per run. Equal to the Template_File with the
  Due_Data_Payload substituted in.
- **Rendered_DOM**: The DOM produced after the Review_Page's
  Inline_Script parses the Due_Data_Payload and builds the visible
  document. Acceptance criteria that reference `<li>`, `<a>`, or
  `<button>` elements are assertions about the Rendered_DOM, not the
  raw Template_File bytes.
- **Due_Song_Item**: The `<li data-level="...">` element inside the
  Rendered_DOM corresponding to one due song. Each Due_Song_Item
  carries all render output for one row from the R8 due query.
- **Show_Block**: A container element inside a Due_Song_Item that
  represents one live show linked to the due song. One Show_Block per
  `(show, song)` pair, rendered in the order defined by R8.
- **Media_URL_Basename**: The last non-empty path segment of a URL.
  For parity with the server-side URL parser, the inline JS computes
  this as the last `/`-separated segment of the URL's `pathname`
  (obtained via `new URL(url).pathname`), trimmed of trailing slashes.
  WHEN the URL's pathname is empty or equal to `/`, OR WHEN `new URL`
  fails to parse the string, the Media_URL_Basename SHALL be the full
  URL string as provided.
- **Copy_Target_ID**: The UUID (per the parent Glossary) of a song,
  show, or artist row, carried in the Due_Data_Payload and written
  into a Copy_Button's `data-copy-id` attribute by the Inline_Script.
- **Highlight_Class**: The single CSS class name `done` that the
  Inline_Script toggles on a Due_Song_Item in response to a bare
  click on that item.
- **Copy_Button**: A `<button>` element with `type="button"`, a
  `data-copy-id` attribute, and no `onclick` attribute, rendered by
  the Inline_Script next to a song, artist, or show name in the
  Rendered_DOM.
- **Inline_Script**: The single `<script>` element embedded in the
  Template_File with no `src` attribute. It carries the JSON-parsing
  code, the DOM-building code, the Copy_Button click handler, and
  the Highlight_Class toggle handler.

## Requirements

### Requirement R-RH-1: Data-Only Python, Template-Based Rendering

**User Story:** As a developer, I want `scripts/review.py` to do only
data work — SQL queries, URL parsing, grouping — and keep every line
of HTML, CSS, and JavaScript in a separate template file, so the
rendering concern lives in one place and Python stays easy to test.

#### Acceptance Criteria

1. THE Template_File SHALL exist at `scripts/review_template.html` and
   SHALL contain the Review_Page's full document chrome — the
   `<!DOCTYPE html>` declaration, `<head>` with inline `<style>`,
   `<body>` with the static skeleton, and the Inline_Script. THE
   Template_File SHALL ship as part of the `scripts/` tree per the
   parent R20.2 packaging contract.
2. `scripts/review.py` SHALL NOT contain any HTML tag literal, any
   CSS rule, or any JavaScript statement. Specifically, no Python
   source file under `scripts/` SHALL contain the substrings `<html`,
   `<head`, `<body`, `<li`, `<a `, `<button`, `<script`, `<style`,
   or any other HTML element opening tag, outside of docstring or
   comment context. (The spec's intent is to forbid render-side
   markup in Python; docstring examples referring to tags in prose
   are not a violation.)
3. `scripts/review.py` SHALL produce the Due_Data_Payload — a single
   JSON document that carries every field the Template_File needs to
   render the page. At minimum each entry in the payload's due-song
   array SHALL carry: `learning_id`, `song_id`, `song_name`,
   `song_name_context`, `artist_id`, `artist_name`,
   `artist_name_context`, `display_level`, and a `shows` array where
   each entry has `show_id`, `show_name`, `show_name_romaji`,
   `show_vintage`, `show_s_type`, and `media_urls` (sorted, deduped).
   The design doc fixes the exact schema.
4. `scripts/review.py` SHALL embed the Due_Data_Payload in the
   Rendered_DOM inside a single `<script id="due-data"
   type="application/json">...</script>` element contained in the
   Template_File. `scripts/review.py` SHALL substitute exactly one
   placeholder in the Template_File with `json.dumps(payload,
   ensure_ascii=False)` plus the R-RH-6.6 JSON-in-HTML escape pass.
5. THE Review_Page SHALL render every Due_Song_Item and every
   Show_Block via DOM construction in the Inline_Script at page load.
   Acceptance criteria in R-RH-3 through R-RH-5 that reference HTML
   elements are assertions about the Rendered_DOM, not the raw
   Template_File bytes or any Python output.
6. WHEN JavaScript is disabled in the user's browser, THE Review_Page
   SHALL still show the page title and a short notice (for example,
   "This page needs JavaScript to render the due list.") rendered in
   plain HTML inside the Template_File so the user is not left with
   a blank screen. The notice SHALL be hidden once the Inline_Script
   starts running.
7. `scripts/review.py` SHALL work from a minimal read-substitute-write
   loop: read the Template_File bytes, substitute the payload
   placeholder with the escaped JSON, write the result to
   `App_Root/output/review_<EPOCH>.html`. No other per-row string
   assembly SHALL occur in Python.
8. THE Template_File SHALL use a substitution marker that cannot
   occur naturally in JSON output — the design doc picks one (for
   example, `<!-- DUE_DATA_JSON -->` inside the
   `<script type="application/json">` block). `scripts/review.py`
   SHALL verify the marker is present before substituting and SHALL
   raise a known error (mapping to `INTERNAL_ERROR` per the parent
   R3.3) when it is missing.

### Requirement R-RH-2: Short-Name Media URL Links

**User Story:** As the user, I want media URL links to show just the
filename, so the review list stays readable when URLs are long.

#### Acceptance Criteria

1. WHEN THE Inline_Script renders a media URL, THE Rendered_DOM SHALL
   contain one `<a>` element per URL whose `href` attribute is the
   full URL and whose visible text is the Media_URL_Basename of that
   URL.
2. THE Inline_Script SHALL set the anchor's `href` via the DOM
   `setAttribute` API or the `.href` property (never via innerHTML)
   and SHALL set the visible text via the `textContent` property
   (never via innerHTML), which gives the browser's own escape
   guarantees for free.
3. WHEN a URL's pathname is empty or equal to `/`, OR WHEN `new URL`
   rejects the string as unparseable, THE Rendered_DOM's anchor
   visible text SHALL be the full URL string as provided.
4. THE `href` attribute on every media URL anchor in the Rendered_DOM
   SHALL be the full, unmodified URL as carried in the
   Due_Data_Payload.

### Requirement R-RH-3: Group Media URLs By Show

**User Story:** As the user, I want to see which show each media URL
belongs to, so I can pick which opening I want to review from.

#### Acceptance Criteria

1. WHEN THE Inline_Script renders a Due_Song_Item, it SHALL render
   one Show_Block per entry in that song's `shows` array from the
   Due_Data_Payload, in the order the array gives them (the order
   defined by R8 from the parent spec).
2. WHEN rendering a Show_Block, THE Inline_Script SHALL list the
   media URLs for that `(show, song)` pair — taken from the
   `show.media_urls` array in the Due_Data_Payload — as `<a>`
   elements inside the Show_Block.
3. THE Rendered_DOM SHALL NOT contain a pooled flat media URL list at
   the Due_Song_Item level alongside the Show_Blocks. Every media
   URL rendered by the Inline_Script SHALL appear inside exactly one
   Show_Block.
4. WHEN a Show_Block has zero media URLs for its `(show, song)` pair,
   THE Rendered_DOM SHALL still contain the Show_Block with the
   show's name and metadata, with no URL list following.
5. FOR any Due_Song_Item, the union of media URLs rendered across all
   of its Show_Blocks SHALL equal the union of `show.media_urls`
   values for that song in the Due_Data_Payload, with no URL
   duplicated across Show_Blocks.
6. THE Due_Data_Payload SHALL be the sole source of truth for
   per-show media URLs. `scripts/review.py` SHALL NOT compute any
   separate aggregate "flat" URL list; the Template_File has no
   element into which to put one.

### Requirement R-RH-4: Copy Buttons for Song / Show / Artist IDs

**User Story:** As the user, I want a one-click way to copy a song,
show, or artist UUID out of the Review_Page, so I can paste it into
`query.py` or `data.py` commands without typing.

#### Acceptance Criteria

1. WHEN THE Inline_Script renders a Due_Song_Item, THE Rendered_DOM
   SHALL contain a Copy_Button immediately after the song name, a
   Copy_Button immediately after the artist name, and, inside every
   Show_Block, a Copy_Button immediately after the show name.
2. THE Inline_Script SHALL set each Copy_Button's `data-copy-id`
   attribute to the UUID (Copy_Target_ID) of the referenced song,
   artist, or show row, taken directly from the Due_Data_Payload.
3. THE Inline_Script SHALL give every Copy_Button `type="button"`
   so activating it SHALL NOT submit a form or navigate the page.
4. WHEN a Copy_Button is clicked, THE Inline_Script SHALL call
   `navigator.clipboard.writeText` with the button's `data-copy-id`
   value.
5. IF the clipboard write fails (for example, when
   `navigator.clipboard` is unavailable or the write is rejected),
   THEN THE Inline_Script SHALL NOT raise an uncaught error that
   bubbles to the window, and SHALL NOT navigate the page.
6. THE Inline_Script SHALL install the Copy_Button click handler via
   a single delegated listener on the document (event delegation).
   THE Rendered_DOM SHALL NOT contain per-button inline `onclick`
   attributes.
7. WHEN a Copy_Button click is handled, THE Inline_Script SHALL call
   `event.stopPropagation()` so the same click does not also trigger
   the R-RH-5 highlight toggle on the enclosing Due_Song_Item.
8. THE Template_File SHALL use only inline JavaScript. THE
   Template_File SHALL NOT reference external JS files, external
   CDNs, or any off-document `<link>` or `<script src>`.

### Requirement R-RH-5: Alternating Highlight On Click

**User Story:** As the user, I want to click a song to mark it "done
for this session", so I can visually track progress as I work through
the list.

#### Acceptance Criteria

1. WHEN a Due_Song_Item is clicked AND the click target is not inside
   an `<a>` element, a `<button>` element, or another interactive
   control, THE Inline_Script SHALL toggle the Highlight_Class on
   that Due_Song_Item.
2. THE Template_File's inline `<style>` block SHALL ship a CSS rule
   for `li[data-level].done` that visibly distinguishes highlighted
   items from non-highlighted ones (for example, dimmed text or a
   muted background).
3. WHEN a media URL `<a>` element inside a Due_Song_Item is clicked,
   THE Inline_Script SHALL NOT toggle the Highlight_Class on the
   enclosing Due_Song_Item, and the anchor's default navigation
   SHALL proceed unimpeded.
4. THE Highlight_Class toggle SHALL be cosmetic only: toggling it
   SHALL NOT modify any `data-*` attribute, SHALL NOT submit any
   request, and SHALL NOT alter the DOM beyond the class list of
   the clicked Due_Song_Item.
5. THE Inline_Script SHALL install the highlight handler via a single
   delegated listener on the document. THE Rendered_DOM SHALL NOT
   contain per-item inline `onclick` attributes.

### Requirement R-RH-6: Inline JS Safety

**User Story:** As the user, I want the Review_Page's inline script to
be safe to open locally without network access or surprises.

#### Acceptance Criteria

1. THE Template_File SHALL declare its Inline_Script inside a single
   `<script>` element with no `src` attribute and no `type="module"`
   that would require a network fetch.
2. THE Inline_Script SHALL NOT make any network request. It SHALL
   NOT call `fetch`, construct an `XMLHttpRequest`, inject a
   `<script>` element, set `new Image().src`, or otherwise trigger
   an outbound request. The Due_Data_Payload is loaded by reading
   `document.getElementById('due-data').textContent` — no
   network is involved.
3. THE Inline_Script SHALL operate entirely on the Review_Page's DOM
   and on `navigator.clipboard`. It SHALL NOT write to
   `localStorage`, `sessionStorage`, `IndexedDB`, `document.cookie`,
   or any other persistent browser storage.
4. THE R8.4 HTML-escape guarantee SHALL continue to hold for
   `song.name`, `artist.name`, `show.name`, `name_context`,
   `name_romaji`, and `media_url`. Every DOM string leaf built by
   the Inline_Script from the Due_Data_Payload SHALL be placed into
   the DOM via the `textContent` property or via `setAttribute`
   (never via `innerHTML` or via attribute concatenation into an
   `innerHTML` assignment). Embedding `<script>alert(1)</script>`
   in any text field SHALL render as inert escaped text in both its
   visible position and inside any attribute value where that field
   flows through (including the anchor `href`, the anchor's visible
   Media_URL_Basename text, and `data-copy-id` attributes).
5. WHERE `navigator.clipboard` is unavailable (for example, when
   the browser disables the Clipboard API on `file://`), THE
   Inline_Script SHALL detect its absence before calling it, SHALL
   NOT throw, and SHALL leave Copy_Buttons as no-ops in that
   environment. THE Review_Page is not required to provide a
   fallback UI for v1.
6. WHEN `scripts/review.py` embeds the Due_Data_Payload as inline
   JSON, it SHALL escape every `<` character in the serialised JSON
   as `\u003c` so that a field whose value literally contains
   `</script>` cannot break out of the `<script
   type="application/json">` element and inject new markup. (This
   is the standard "JSON in HTML" escape — `&` and `>` are also
   safe to escape the same way, but at minimum `<` MUST be escaped
   to prevent the `</script>` breakout.)

**Note (informational, not an acceptance criterion):**
`navigator.clipboard.writeText` requires a browser "secure context"
(HTTPS, `localhost`, or — in most current browsers — a `file://`
origin). Because the Review_Page is opened locally from
`App_Root/output/review_<EPOCH>.html`, the common case is `file://`,
which qualifies as a secure context in Chrome, Edge, and Firefox.
The design doc calls this out; this spec does not constrain the
browser.

### Requirement R-RH-7: Packaging Ships `skills/`, Excludes `.kiro/`

**User Story:** As the operator, I want the deployable zip to contain
the Claude skill docs (so Claude working against the deployed tree can
see them), but not the `.kiro/` spec folder — `.kiro/` is dev
infrastructure and stays on the author's machine.

#### Acceptance Criteria

1. THE R20.2 copy list SHALL be extended so that `skills/` is included
   in the deployable zip. `tools/package.py` SHALL copy the repo's
   `skills/` tree verbatim into the staged zip, subject to the same
   cache-defense filter (`_SKIP_DIR_NAMES`) that already guards
   `scripts/`.
2. THE deployable zip produced by `tools/package.py` SHALL contain
   exactly the top-level paths: `scripts/`, `skills/`, `db/datasource.db`
   (empty, schema only, built from `tests/fixtures/schema.sql`),
   `Makefile`, and, when present at the repo root, `README.md`. No
   other top-level paths SHALL appear.
3. THE deployable zip SHALL NOT contain any path under `.kiro/`,
   `docs/`, `output/`, `tools/`, `tests/`, `dist/`, `.venv/`, `venv/`,
   `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
   `.trace/`, or `.coverage_data/`, nor the repo's real (non-empty)
   `db/datasource.db`, nor any of `.gitignore`, `.coveragerc`,
   `requirements-dev.txt`, or `pyproject.toml`.
4. THE `tools/package.py` module docstring and the comment on
   `_SKIP_DIR_NAMES` SHALL document the two-layer exclusion model
   explicitly:
   - Top-level directories not on the copy list (`.kiro/`, `docs/`,
     `tests/`, `tools/`) are excluded by construction —
     `tools/package.py` never asks `shutil.copytree` to look at them.
     `.kiro/` is called out by name as a hidden dev folder that
     intentionally stays on the author's machine.
   - `_SKIP_DIR_NAMES` is a defense-in-depth filter applied to every
     directory that is copied (`scripts/`, `skills/`) to keep caches
     and generated subdirectories (`__pycache__`, `.pytest_cache`,
     `output`, etc.) out of the zip even if they happen to appear
     inside a copied tree.

## Correctness Properties for Property-Based Testing

These properties extend the `anime-song-learning-app` spec's
"Correctness Properties" section. Tests follow R18's rules from that
spec: temp `App_Root` per test (never the real `db/datasource.db`),
stdlib `random.Random(seed)` with a fixed seed (no `hypothesis`), and
integration tests drive scripts via `subprocess.run`.

Several of these properties reference the Rendered_DOM. Because the
spec forbids adding a browser runtime dependency (see Out of Scope),
tests that assert on Rendered_DOM structure use Python to load the
Template_File and the Due_Data_Payload, then simulate what the
Inline_Script would build in a pure-Python equivalent (for example, a
small helper in the test harness that reads the payload and produces
the expected element tree). The properties describe what the rendered
document must equal; the test harness provides the comparison.

### Property P-RH-0: Zero HTML in Python

For any snapshot of the repo's `scripts/` tree at head:

1. No `.py` file under `scripts/` contains any HTML element opening
   tag as a code literal. Specifically, grepping every `.py` file in
   `scripts/` for the regex `<(html|head|body|li|ul|ol|a|button|script|style|div|span|p|h[1-6]|title|meta|link|br|hr|pre|code|table|tr|td|th)\b`
   (applied only to code, not to docstrings or comments) MUST return
   zero matches.
2. The Template_File exists at `scripts/review_template.html` and
   the exclusion above does not cover it (HTML tags belong there).
3. For any Due_Data_Payload `P` produced from a seeded random DB,
   substituting `P` into the Template_File and loading the result
   into a DOM (the test's Python-side equivalent) yields a
   Rendered_DOM whose Due_Song_Item count equals `len(P.due_songs)`.
4. Swapping the Template_File for an unrelated stub file (a
   Template_File missing the substitution marker) causes
   `scripts/review.py` to exit with `code = "INTERNAL_ERROR"` per
   R-RH-1.8.

### Property P-RH-1: Short-Name Link Round-Trip

For any URL `U` generated from a scheme in `{"http", "https"}`, a
random host, and a random non-empty path:

1. The Rendered_DOM contains one `<a>` element for `U` whose `href`,
   after attribute parsing, equals `U`.
2. That anchor's visible text, after text-node extraction, equals
   `Media_URL_Basename(U)`.

For any URL `U` whose parsed path is empty or equal to `/`:

3. That anchor's visible text, after text-node extraction, equals `U`
   (the full URL).

### Property P-RH-2: Group-By-Show Partition

For any due song `S` with live shows `SH_1..SH_n` and media URL sets
`U_1..U_n` (where each `U_i` is the sorted, deduplicated union of
`play_history.media_url` and `rel_show_song.media_url` for
`(SH_i, S)`, with empty strings dropped, per R8.5):

1. The `shows` array in the Due_Data_Payload for `S` has `n` entries
   with `media_urls` equal to `U_1, ..., U_n` respectively.
2. The set of media URLs rendered across `S`'s Show_Blocks in the
   Rendered_DOM equals `U_1 ∪ U_2 ∪ ... ∪ U_n`.
3. Every URL appears in exactly one Show_Block.
4. For each `SH_i`, the URLs rendered inside its Show_Block equal
   `U_i` (set equality).

### Property P-RH-3: Copy Button Coverage

For any due song `S` owned by artist `A` with live shows
`SH_1..SH_n`:

1. THE Rendered_DOM contains exactly one Copy_Button with
   `data-copy-id == S.id` inside `S`'s Due_Song_Item, rendered after
   `S.name`.
2. THE Rendered_DOM contains exactly one Copy_Button with
   `data-copy-id == A.id` inside `S`'s Due_Song_Item, rendered after
   `A.name`.
3. FOR each `SH_i`, THE Rendered_DOM contains exactly one Copy_Button
   with `data-copy-id == SH_i.id` inside the Show_Block for
   `(SH_i, S)`, rendered after `SH_i.name`.
4. Every Copy_Button emitted has `type="button"` and no `onclick`
   attribute.

### Property P-RH-4: HTML Escape Holds Under New Elements

For any song, artist, or show `name` and `name_context` drawn from a
generator that includes `<`, `>`, `&`, `"`, `'`, and the literal
strings `<script>`, `</script>`, and `javascript:`:

1. The chosen name SHALL NOT appear unescaped anywhere in the
   Rendered_DOM's visible text nodes, anchor `href` values, anchor
   visible text, or attribute values.
2. Feeding the Review_Page (the raw HTML bytes) to an HTML parser
   SHALL NOT produce any `<script>` element beyond the two declared
   by the Template_File (the Inline_Script and the
   `<script type="application/json">` data block) — specifically,
   a song name of exactly `</script><script>alert(1)</script>`
   SHALL NOT cause the HTML parser to emit a third `<script>` tag.
3. Copy_Button `data-copy-id` attributes contain only UUIDs (which,
   by the parent Glossary, are lowercase hexadecimal with hyphens and
   cannot contain markup); this property covers name fields only.

### Property P-RH-5: Packaging Allowlist and Exclusion

For any synthetic `App_Root` assembled in a temp directory containing
at least: `scripts/*.py`, `db/datasource.db`, `Makefile`, `README.md`,
`skills/<SKILL>/SKILL.md`, `skills/<SKILL>/references/foo.md`,
`.kiro/specs/<SPEC>/requirements.md`, `docs/<DOC>.md`,
`output/review_<EPOCH>.html`, and `tools/package.py`:

1. The zip written by `tools/package.py` (run against that synthetic
   root) has no entry whose path starts with `.kiro/`, `docs/`,
   `output/`, `tools/`, `tests/`, `dist/`, `.venv/`, `venv/`,
   `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
   `.trace/`, or `.coverage_data/`.
2. The zip contains at least one entry whose path starts with
   `skills/` (the skill docs ship).
3. The zip's top-level path set is a subset of
   `{scripts/, skills/, db/, Makefile, README.md}` (no other top-level
   paths appear).
4. The zip contains `db/datasource.db` as an empty schema-only DB
   (not the synthetic root's `db/datasource.db` bytes).

### Note on R-RH-5 (Highlight Toggle)

Per the workflow's "When NOT to Use Property-Based Testing" guidance,
the highlight toggle is a DOM-side cosmetic change that does not vary
meaningfully with input. It is covered by small, example-style unit
tests rather than a property:

- Clicking a Due_Song_Item toggles the Highlight_Class on, then off.
- Clicking a media URL anchor inside a Due_Song_Item does not toggle
  the Highlight_Class (anchor navigation takes precedence).
- Clicking a Copy_Button inside a Due_Song_Item does not toggle the
  Highlight_Class (R-RH-4.7 `stopPropagation`).

These example tests exercise the JavaScript behavior via a minimal
DOM harness (for example, a small Python helper that parses the
generated HTML with `html.parser` and walks click-handler-reachable
elements); they do not need a browser runtime.

## Out of Scope for This Spec

The following items are explicitly out of scope for
`review-html-enhancements` and SHALL NOT be introduced as part of
implementing R-RH-1..R-RH-7:

1. A persistent "done" marker: the highlight toggle is session-only,
   not written to the DB.
2. A `--include-deleted` flag or any other CLI option change on
   `review.py`. The subcommand surface stays exactly as defined by
   parent R8.
3. Any change to the due-selection SQL (parent R7) or the R8.5
   media-URL union rules.
4. External CSS, icon fonts, or client-side frameworks in the
   Review_Page.
5. A browser-runtime test harness (Playwright, Selenium, jsdom). The
   tests described above use stdlib HTML parsing and pure-Python
   DOM walks; a real browser run is a manual verification step.
