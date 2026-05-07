# Feature Requirements Document

## Introduction

Today, `scripts/review.py song-review` always materialises a file at
`App_Root/output/review_<EPOCH>.html` and emits a Success_Envelope on
stdout that points at it. For the Reviewing_Agent driving the review
session, this is two steps: invoke the script, then read the file
back from disk. When the agent only wants the rendered page in order
to display it, parse it, or pipe it onward, the disk hop is
overhead — the file is written, opened, read, and on most runs never
referenced again.

This feature adds a second output mode. A new opt-in CLI flag
`--inline` makes `song-review` skip the disk write and instead embed
the rendered page, **minified**, directly inside the Success_Envelope
under a new `html` key. "Minified" follows the standard web-frontend
meaning — collapse runs of whitespace between tags, strip HTML
comments — applied **only to the document chrome outside `<script>`
and `<style>` blocks**. Script bodies (the embedded JSON payload, the
Inline_Script JavaScript) and style-sheet bodies stay byte-identical
to the unminified template; minification never re-parses or
re-encodes them. The Escape_Gate is preserved unchanged.

The default (no-flag) behavior is byte-identical to v0.1.4 — the file
is still written to `output/review_<EPOCH>.html`, the envelope still
carries `path`, and no minification runs. `--inline` is the only new
surface and it's strictly additive: the only Python production file
modified is `scripts/review.py`, with one new helper for the minify
pass and a small branch in `_cmd_song_review` that selects between
the two output modes. `_common.py`, `learning.py`, every other
production script, the template, and every existing test stay
byte-identical.

## Glossary

- **Review_Page**: The HTML document produced by
  `scripts/review.py song-review`. In Disk_Mode (the existing
  default) the bytes land at `App_Root/output/review_<EPOCH>.html`;
  in Inline_Mode (new) the bytes live in the Success_Envelope's
  `html` field on stdout.
- **Template_File**: `scripts/review_template.html`. Unchanged by
  this feature.
- **Due_Data_Payload**: The JSON document built by
  `scripts/review.py._build_payload`. Shape and field set are frozen
  by the existing `review-html-enhancements` contract; this feature
  adds zero fields.
- **Success_Envelope**: The single JSON object written to stdout by
  `_common.success(...)`. In Disk_Mode (v0.1.4) the key set is
  `{"path", "due_count", "offset"}`. This feature adds Inline_Mode
  with key set `{"html", "due_count", "offset"}` — `path` is
  replaced by `html`, never co-emitted.
- **Disk_Mode**: The default `song-review` behavior — write the
  file, return `path` in the envelope. No CLI flag required.
- **Inline_Mode**: The opt-in `song-review --inline` behavior — skip
  the disk write entirely, return the Minified_Page in the envelope's
  `html` field.
- **Inline_Flag**: The new CLI option `--inline`. A
  `store_true`/false boolean flag on the `song-review` subparser. No
  short form. Default: `False`.
- **Minified_Page**: The Review_Page after the `_minify_chrome` pass
  has run over it. The pass collapses runs of whitespace between
  tags and strips HTML comments — but **only outside** `<script>`
  and `<style>` blocks. The bytes inside those two element types are
  byte-identical to the pre-minify input.
- **Chrome_Region**: Any byte range of the rendered HTML that is not
  inside a `<script>...</script>` or `<style>...</style>` element.
  The Minified_Page's whitespace and comment rewrites apply only to
  Chrome_Regions.
- **Script_Region**: Any byte range from the start tag of a
  `<script>` element (immediately after the `>`) through and not
  including its `</script>` end tag. Includes both the
  `<script id="due-data" type="application/json">` payload block
  and the Inline_Script JavaScript. Untouched by minification.
- **Style_Region**: Any byte range from the start tag of a
  `<style>` element through and not including its `</style>` end
  tag. Untouched by minification.
- **Escape_Gate**: The `_escape_json_for_html` pass in
  `scripts/review.py` that rewrites `<`, `>`, and `&` in the
  serialised payload to `<`, `>`, `&`. Unchanged by
  this feature. The property test
  `tests/integration/property/test_escape_injection_property.py`
  remains the oracle.
- **Reviewing_Agent**: The AI agent driving the review session.
  Primary consumer of Inline_Mode — the agent reads `html` directly
  out of the envelope rather than reading the file off disk.

## User Stories

### Story 1: Opt-in inline HTML response (R-Inline-Flag)

**User Story:** As a Reviewing_Agent driving the review session, I
want one CLI invocation to return the rendered Review_Page directly
in the JSON envelope instead of writing it to disk, so that I can
consume the page without an intermediate file read and without
leaving artifacts behind in `App_Root/output/`.

#### Acceptance Criteria

1.1 WHEN `scripts/review.py song-review --help` is invoked THEN the
help text SHALL document the `--inline` Inline_Flag with a short
description ("Return the rendered HTML in the envelope's `html`
field instead of writing it to disk; skips the file write entirely
and minifies the response.") AND SHALL list `--inline` alongside
the existing `--offset` flag.

1.2 WHEN `scripts/review.py song-review` is invoked WITHOUT
`--inline` THEN the script SHALL behave byte-identically to v0.1.4 —
write the rendered bytes to `App_Root/output/review_<EPOCH>.html`,
emit a Success_Envelope on stdout with key set
`{"path", "due_count", "offset"}`, and run NO minification pass.

1.3 WHEN `scripts/review.py song-review --inline` is invoked AND the
DB has at least one due song THEN the script SHALL NOT write any
file under `App_Root/output/` AND SHALL emit a Success_Envelope on
stdout with key set EXACTLY `{"html", "due_count", "offset"}`,
where `html` is the Minified_Page as a UTF-8 string.

1.4 WHEN `scripts/review.py song-review --inline` is invoked AND the
DB has zero due songs THEN the script SHALL still emit the
Inline_Mode envelope (`html`, `due_count: 0`, `offset`) — the
empty-state Review_Page renders identically; the only difference
from Disk_Mode is the absence of the file write and the swap of
`path` for `html`.

1.5 WHEN `scripts/review.py song-review --inline --offset N` is
invoked THEN the `--offset` semantics SHALL be byte-identical to
Disk_Mode — the same `_build_payload(conn, offset)` runs, the
rendered template is the same, and the envelope's `offset` field
mirrors the input N.

1.6 WHEN `scripts/review.py song-review --inline` runs successfully
THEN the `App_Root/output/` directory SHALL NOT be created if it
does not already exist — the directory creation lives inside the
Disk_Mode branch only.

### Story 2: Minified HTML payload (R-Minify)

**User Story:** As a Reviewing_Agent receiving the Review_Page over
stdout, I want the inline HTML to be size-minimised in the standard
web-frontend sense, so that the JSON envelope stays compact and the
agent's downstream processing reads less text.

#### Acceptance Criteria

2.1 WHEN the Minified_Page is computed from a rendered Review_Page
THEN every byte range that is a Script_Region (the
`<script id="due-data">` payload block and the Inline_Script) SHALL
be byte-identical to the same range in the pre-minify input — no
whitespace collapse, no comment strip, no character escape rewrite
applies inside `<script>...</script>`.

2.2 WHEN the Minified_Page is computed THEN every byte range that
is a Style_Region SHALL be byte-identical to the same range in the
pre-minify input — no whitespace collapse, no comment strip, no
selector reformat applies inside `<style>...</style>`.

2.3 WHEN the Minified_Page is computed THEN every Chrome_Region
SHALL have:
  - every run of two or more whitespace characters (space, tab,
    `\n`, `\r`, `\f`) collapsed to a single space,
  - every run of whitespace that sits **between** a `>` and a `<`
    (i.e. between two adjacent tags, with no non-whitespace text
    in between) collapsed to the empty string,
  - every HTML comment (`<!-- ... -->`) removed in full.

2.4 WHEN the Minified_Page is parsed as HTML THEN it SHALL parse to
the same DOM (same element tree, same attributes, same script and
style text content) as the pre-minify input. The minify pass SHALL
NOT introduce, reorder, rename, or drop any element, attribute, or
attribute value.

2.5 WHEN the Minified_Page is encoded as UTF-8 bytes THEN its
byte length SHALL be less than or equal to the pre-minify input's
byte length. For a non-empty due-songs render against the shipped
v0.1.4 template, the Minified_Page SHALL be strictly smaller than
the pre-minify input (the template ships with non-trivial
whitespace and at least one HTML comment — the substitution marker
is rewritten before minify, but the template carries other comments
that the pass strips).

2.6 WHEN the rendered Review_Page is supplied to `_minify_chrome`
AND every Chrome_Region of the input contains only ASCII whitespace
between tags THEN `_minify_chrome` SHALL be idempotent — running
it a second time on its own output produces output byte-identical
to the first pass.

### Story 3: Escape_Gate preserved under Inline_Mode (R-Escape-Preserve)

**User Story:** As any user of the Review_Page, I want XSS safety
to stay airtight when the rendered page is delivered inline through
the JSON envelope, so that adding the inline output mode does not
open a new injection vector.

#### Acceptance Criteria

3.1 WHEN `scripts/review.py song-review --inline` is invoked with
a payload whose `song_name`, `artist_name`, or `show_name` contains
a hostile substring (for example `<script>alert(1)</script>` or
`</script>`) THEN HTML-parsing the envelope's `html` field SHALL
yield exactly two `<script>` elements — the
`<script id="due-data">` payload block and the Inline_Script —
the same invariant Disk_Mode satisfies today.

3.2 WHEN the Inline_Script in the Minified_Page parses its payload
via `JSON.parse(node.textContent)` THEN the parsed `song_name`,
`artist_name`, and `show_name` strings SHALL round-trip
byte-for-byte through the payload — every hostile byte appears in
the parsed string exactly as it appeared in the caller's input.
This holds because the Script_Region containing the payload is
byte-identical to the pre-minify input (R-Minify, 2.1) and the
pre-minify input is the same byte sequence Disk_Mode would have
written to the file.

3.3 WHEN the `_minify_chrome` helper runs over a rendered
Review_Page THEN the helper SHALL NOT decode or re-encode any
Script_Region or Style_Region content — those bytes pass through
untouched. The helper SHALL operate on Chrome_Regions only.

### Story 4: Envelope shape disjointness (R-Envelope-Disjoint)

**User Story:** As any caller parsing the Success_Envelope, I want
the Disk_Mode and Inline_Mode envelope shapes to be disjoint and
self-describing, so that branching on which mode produced the
output is unambiguous and a single envelope cannot accidentally
carry both `path` and `html`.

#### Acceptance Criteria

4.1 WHEN Disk_Mode emits its Success_Envelope THEN the envelope's
key set SHALL be EXACTLY `{"path", "due_count", "offset"}` — no
`html` key SHALL appear.

4.2 WHEN Inline_Mode emits its Success_Envelope THEN the envelope's
key set SHALL be EXACTLY `{"html", "due_count", "offset"}` — no
`path` key SHALL appear, and no file is written to `App_Root/output/`.

4.3 WHEN either mode emits its envelope THEN `due_count` and
`offset` SHALL carry the same semantics and types as v0.1.4 —
`due_count` is the integer length of `due_songs` in the payload,
`offset` echoes the input `--offset N` as an int.

4.4 WHEN any field in either envelope contains a string (the `path`
field in Disk_Mode, the `html` field in Inline_Mode) THEN that
string SHALL be JSON-encoded by the shared `_common.success` helper
with `ensure_ascii=False` — non-ASCII characters in song / artist /
show names appear as their literal UTF-8 codepoints, not as
`\uXXXX` escape sequences. (This matches the existing v0.1.4
behavior of `_common.success`.)

### Story 5: Byte-identical surface for unrelated paths (R-Additive)

**User Story:** As a release engineer, I want this release to leave
every code path unrelated to Inline_Mode byte-identical to v0.1.4,
so that a rollback is a trivial revert and the existing payload /
envelope / schema contracts stay pinned.

#### Acceptance Criteria

5.1 WHEN the release is applied THEN `scripts/review_template.html`
SHALL be byte-identical to its v0.1.4 contents — the inline-output
mode is a server-side feature; the template does not change.

5.2 WHEN the release is applied THEN `scripts/_common.py` SHALL be
byte-identical to its v0.1.4 contents — Inline_Mode reuses the
existing `success(...)` helper without modification.

5.3 WHEN the release is applied THEN every Python file under
`scripts/` other than `scripts/review.py` SHALL be byte-identical
to its v0.1.4 contents.

5.4 WHEN the release is applied THEN `tests/integration/_dom_sim.py`
SHALL be byte-identical to its v0.1.4 contents.

5.5 WHEN the full test suite runs against the post-feature tree
THEN every existing test in `tests/integration/test_review.py`
SHALL continue to pass with zero assertion edits and zero
iteration-count changes — the Disk_Mode default behavior is the
v0.1.4 behavior.

5.6 WHEN the full test suite runs against the post-feature tree
THEN every property test under `tests/integration/property/` SHALL
continue to pass with zero assertion edits and zero
iteration-count changes — Inline_Mode's payload bytes inside the
Script_Region are byte-identical to Disk_Mode's, so the existing
Escape_Gate property test holds transitively without modification.

5.7 WHEN `scripts/review.py song-review` is invoked WITHOUT the
Inline_Flag THEN the Disk_Mode code path SHALL be byte-identical
in observable behavior to v0.1.4 — same file path scheme, same
envelope key set, same envelope values, same exit code.

### Story 6: Test coverage for the new surface (R-Test-Inline)

**User Story:** As a release engineer, I want the Inline_Mode
behavior to be covered by automated tests at the same fidelity as
the existing Disk_Mode behavior, so that future refactors cannot
silently break the inline output path.

#### Acceptance Criteria

6.1 WHEN the release is applied THEN
`tests/integration/test_review.py` SHALL gain a test asserting that
`scripts/review.py song-review --inline` against a populated DB
emits a Success_Envelope with key set EXACTLY
`{"html", "due_count", "offset"}` (no `path`), AND that the `html`
field parses as HTML to the same DOM structure that Disk_Mode
produces (same number of `<li data-level>` elements, same
`<script id="due-data">` payload).

6.2 WHEN the release is applied THEN
`tests/integration/test_review.py` SHALL gain a test asserting that
`scripts/review.py song-review --inline` against an empty-due DB
emits the Inline_Mode envelope with `due_count: 0` and an `html`
field that contains the empty-state markup (parses to a document
with no `<li data-level>` elements).

6.3 WHEN the release is applied THEN
`tests/integration/test_review.py` SHALL gain a test asserting that
`scripts/review.py song-review --inline` does NOT create any file
under `App_Root/output/` — the test seeds an empty `App_Root` (or
removes any pre-existing `output/` directory), runs the command,
and asserts `App_Root/output/` does not exist OR is empty after
the run completes.

6.4 WHEN the release is applied THEN
`tests/integration/test_review.py` SHALL gain a test asserting that
the `_minify_chrome` helper:
  - leaves Script_Region bytes byte-identical (feed an input where
    `<script>...</script>` contains deliberate whitespace and a
    `<!-- ... -->`-shaped comment in JS string form; assert the
    region survives unchanged),
  - leaves Style_Region bytes byte-identical,
  - collapses inter-tag whitespace runs in Chrome_Regions to the
    empty string,
  - strips HTML comments in Chrome_Regions,
  - is idempotent (a second pass over the output returns the
    output unchanged).

6.5 WHEN the release is applied THEN
`tests/integration/test_review.py` SHALL gain a test asserting that
Inline_Mode preserves the Escape_Gate — feed a payload whose
`song_name` is `"</script><script>alert(1)</script>"`, run
`song-review --inline`, parse the envelope's `html` as HTML, and
assert exactly two `<script>` elements appear in the parsed DOM
and the payload-block's `JSON.parse`-equivalent textContent
round-trips the hostile string byte-for-byte.

6.6 WHEN the release is applied THEN every new test added by this
release SHALL live in `tests/integration/test_review.py` — no new
test file is created, and no existing test in that file is edited.

## Non-Goals (Out of Scope)

The following are explicitly out of scope for this release.

- **Minifying JavaScript or CSS.** The minify pass is HTML-only and
  by construction skips Script_Regions and Style_Regions. JS
  minification (renaming locals, dropping dead branches) and CSS
  minification (selector merging, value shortening) require a real
  parser and are out of scope.
- **Server-side rendering of the DOM.** The Inline_Script still
  builds the DOM in the browser from `JSON.parse(textContent)`. The
  inline output mode delivers the same template-plus-payload bytes
  that Disk_Mode delivers, just over stdout instead of via a file.
- **Streaming output.** The Success_Envelope is one JSON document
  on one line. No chunked output, no progress events.
- **Compression** (gzip, brotli) of the inline payload. The user
  asked for minification; compression is a separate concern and
  out of scope for this release.
- **A "both" mode** that writes the file *and* echoes inline. The
  two modes are disjoint by R-Envelope-Disjoint. If a future use
  case ever needs both, it can be added additively.
- **Changing the template, `_common.py`, or any other production
  script.** R-Additive pins the scope boundary — only
  `scripts/review.py` and `tests/integration/test_review.py` change
  in this release (plus a one-line bullet in `release.md`).
- **A short-form CLI alias** (`-i`) for `--inline`. The full flag
  is the only surface; short forms can be added later if needed.
- **Stdout vs envelope split.** The HTML lives in a JSON field, not
  on raw stdout. This keeps the envelope contract uniform with
  every other script under `scripts/`.

## Release Constraints

This feature ships as v0.1.5 through the existing release pipeline
(`.github/workflows/release.yml`), one commit, scope `review`. The
diff is exactly three files: `scripts/review.py` (the
`--inline` flag, the `_minify_chrome` helper, and the small branch
in `_cmd_song_review` that selects between Disk_Mode and
Inline_Mode), `tests/integration/test_review.py` (new tests added
per Story 6 — no existing test is edited), and `release.md` (one
bullet under v0.1.5). No schema change, no payload-shape change,
no template change, no new error code, no breaking change to the
existing CLI surface or envelope shape. Disk_Mode (the default)
remains byte-identical to v0.1.4. Rollback is a trivial revert.
