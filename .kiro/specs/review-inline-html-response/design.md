# Review Inline HTML Response Design

## Overview

`scripts/review.py song-review` today is single-purpose: it reads
the DB, builds the Due_Data_Payload, substitutes the payload into
`scripts/review_template.html`, writes the resulting HTML to
`App_Root/output/review_<EPOCH>.html`, and prints a JSON
Success_Envelope `{"path", "due_count", "offset"}` on stdout. The
file write is the only delivery channel.

For the Reviewing_Agent driving the review loop, the file hop is
overhead — the agent invokes the script, then reads the file off
disk. When the agent only wants the bytes (to display the page, to
hand them onward, to inspect the rendered DOM in-process), the
disk artifact is gratuitous: it gets written, opened, read, and on
most runs never referenced again.

This spec adds a second output mode. A new opt-in CLI flag
`--inline` makes `song-review` skip the disk write entirely and
embed the rendered Review_Page, **minified**, into the
Success_Envelope under a new `html` key. The two modes are
disjoint: Disk_Mode (the v0.1.4 default) returns
`{"path", "due_count", "offset"}` and writes the file;
Inline_Mode returns `{"html", "due_count", "offset"}` and writes
no file.

"Minified" follows the standard web-frontend meaning — collapse
runs of whitespace between tags, strip HTML comments — but
applies **only outside** `<script>` and `<style>` blocks.
Script_Region and Style_Region bytes pass through byte-identically.
This bound is essential: the `<script id="due-data">` payload
block is the post-Escape_Gate JSON document, and the Inline_Script
is the JavaScript that builds the DOM. Touching either would risk
regressing the existing
`tests/integration/property/test_escape_injection_property.py`
oracle.

The diff is confined to two production-touched files:
`scripts/review.py` (the new flag, the minify helper, the small
branch in `_cmd_song_review`) and `tests/integration/test_review.py`
(new tests covering the inline output and the minify pass). The
template, `_common.py`, every other production script, and every
existing test stay byte-identical.

## Glossary

- **Review_Page**: The rendered HTML document — Template_File with
  the Due_Data_Payload substituted into the marker. Disk_Mode
  writes its bytes to a file; Inline_Mode places its bytes (after
  minification) into the Success_Envelope's `html` field.
- **Template_File**: `scripts/review_template.html`. Unchanged.
- **Due_Data_Payload**: The JSON document built by `_build_payload`.
  Unchanged shape; zero new fields.
- **Success_Envelope**: The JSON object on stdout. Two disjoint
  shapes by mode (R-Envelope-Disjoint).
- **Disk_Mode**: Default behavior. v0.1.4-equivalent.
- **Inline_Mode**: Behavior when the Inline_Flag is present.
- **Inline_Flag**: The new CLI option `--inline`. `store_true`,
  default `False`. No short form.
- **Minified_Page**: The Review_Page after `_minify_chrome` has
  run. Bytes inside Script_Regions and Style_Regions are
  byte-identical to the input; bytes inside Chrome_Regions have
  inter-tag whitespace collapsed and HTML comments removed.
- **Chrome_Region**: Any byte range outside a `<script>...</script>`
  or `<style>...</style>` element.
- **Script_Region**: The byte range from the `>` that closes a
  `<script>` start tag through (and not including) the `<` of its
  matching `</script>`. Both `<script id="due-data" type="application/json">`
  (the payload block) and the Inline_Script (the JS) are
  Script_Regions.
- **Style_Region**: The analogous range for `<style>...</style>`.
- **Escape_Gate**: The `_escape_json_for_html` pass in
  `scripts/review.py`. Unchanged.
- **Reviewing_Agent**: The AI agent driving review sessions. The
  primary consumer of Inline_Mode.

## Requirements-to-Design Mapping

The acceptance criteria in `requirements.md` trace into this
design as follows.

- **R-Inline-Flag** (Story 1): the `--inline` flag is added to the
  `song-review` subparser; `_cmd_song_review` branches on
  `args.inline` to pick between Disk_Mode and Inline_Mode (Design
  Decision D1, Low-Level Design).
- **R-Minify** (Story 2): the new `_minify_chrome(html_bytes)`
  helper segments the input into alternating Chrome_Regions and
  Script_Region/Style_Region spans, rewrites only the
  Chrome_Regions, and concatenates the result (Design Decision D2,
  Low-Level Design).
- **R-Escape-Preserve** (Story 3): `_minify_chrome` operates on
  bytes outside `<script>` and `<style>` only. The `<script id="due-data">`
  payload block survives byte-identically; the existing
  Escape_Gate property test holds transitively (Design Decision
  D3, Correctness Properties).
- **R-Envelope-Disjoint** (Story 4): the two envelope shapes are
  produced by two distinct call sites of `_common.success(...)`
  inside `_cmd_song_review`; neither call site emits both `path`
  and `html` (Design Decision D4, Low-Level Design).
- **R-Additive** (Story 5): the only production file modified is
  `scripts/review.py`; the template, `_common.py`, and every other
  production script stay byte-identical (Design Decision D5,
  Rollout).
- **R-Test-Inline** (Story 6): five new tests are added to
  `tests/integration/test_review.py` covering envelope shape,
  empty-state, no-file-written, the minify pass, and Escape_Gate
  preservation under Inline_Mode (Testing Strategy).

## High-Level Design

### Component Breakdown

Three moving parts, all inside `scripts/review.py`:

1. **`_build_parser` argument addition.** The `song-review`
   subparser gains `--inline` as a `store_true` flag. The existing
   `--offset` argument and its semantics are unchanged.

2. **`_minify_chrome(html_bytes: bytes) -> bytes` helper.** New
   private function. Segments the input HTML at `<script>` and
   `<style>` boundaries, rewrites only the Chrome_Region segments
   (collapse whitespace runs, drop HTML comments), and re-joins.
   Pure function; no I/O; deterministic; idempotent for inputs
   whose Chrome_Regions are already minified.

3. **`_cmd_song_review` branch.** After `_render_page` produces the
   rendered bytes, the function branches:
   - If `args.inline` is `False` (Disk_Mode): write the file under
     `App_Root/output/`, emit `{"path", "due_count", "offset"}` —
     byte-identical to v0.1.4.
   - If `args.inline` is `True` (Inline_Mode): run
     `_minify_chrome(rendered)`, emit
     `{"html", "due_count", "offset"}` where `html` is the minified
     bytes decoded as UTF-8. Skip the file write entirely.

`_build_payload`, `_render_page`, `_escape_json_for_html`, the SQL,
and the template are untouched.

### Data Model Touchpoints

None. No SQL change, no schema change, no payload-shape change,
no new payload field. Inline_Mode uses the same Due_Data_Payload
that Disk_Mode uses; the only divergence is whether the rendered
bytes go to a file or into the envelope.

### Pipeline Touchpoints (Where Each Change Enters)

```
scripts/review.py
─────────────────
  _cmd_song_review(conn, args)
        │
        │ payload   = _build_payload(conn, args.offset)         (unchanged)
        │ template  = _TEMPLATE_PATH.read_bytes()               (unchanged)
        │ rendered  = _render_page(payload, template)           (unchanged)
        │
        │ if not args.inline:                                  ◀── branch on Inline_Flag
        │     # Disk_Mode  (v0.1.4 behavior, byte-identical)
        │     output_dir.mkdir(parents=True, exist_ok=True)
        │     target.write_bytes(rendered)
        │     _common.success({"path": ..., "due_count": ..., "offset": ...})
        │ else:
        │     # Inline_Mode (NEW)
        │     minified = _minify_chrome(rendered)               ◀── NEW helper
        │     _common.success({
        │         "html":      minified.decode("utf-8"),
        │         "due_count": payload["due_count"],
        │         "offset":    int(args.offset),
        │     })
```

`_common.py` is unchanged. `_common.success(...)` already accepts
any JSON-serialisable dict and emits it via `json.dumps(...,
ensure_ascii=False)`, which round-trips a UTF-8 HTML string
losslessly.

### Before / After

**Before** (v0.1.4):

```
$ scripts/review.py song-review
{"path": "/.../output/review_1746555600.html", "due_count": 3, "offset": 0}

$ ls /.../output/
review_1746555600.html
```

**After** (v0.1.5, Disk_Mode default — unchanged):

```
$ scripts/review.py song-review
{"path": "/.../output/review_1746555700.html", "due_count": 3, "offset": 0}

$ ls /.../output/
review_1746555600.html
review_1746555700.html
```

**After** (v0.1.5, Inline_Mode):

```
$ scripts/review.py song-review --inline
{"html": "<!DOCTYPE html><html><head><meta charset=\"utf-8\">...", "due_count": 3, "offset": 0}

$ ls /.../output/
review_1746555600.html
review_1746555700.html
# no new file
```

The agent reads `html` directly out of the envelope:

```
$ scripts/review.py song-review --inline | jq -r .html > /tmp/page.html
```

## Design Decisions

### D1 — CLI surface: `--inline` flag, not a sibling subcommand

**Choice**: add `--inline` (a `store_true` boolean flag) to the
existing `song-review` subparser.

**Considered**:
- **Sibling subcommand** `song-review-inline`. Pro: dispatch is
  trivial. Con: duplicates 90% of the subcommand surface
  (`--offset`, the `_DUE_SQL`, the payload build, the render).
  Two subcommands that share everything except the last-mile
  output is exactly what an `if/else` branch on a flag is for.
- **Mode argument** `--mode {disk,inline}`. Pro: extensible to a
  hypothetical third mode later. Con: speculative; we have one
  new mode today and YAGNI.

**Why a flag**:
- `argparse` makes the flag a one-line addition next to `--offset`.
- The two modes share every code path up to and including
  `_render_page`; they only diverge at the delivery step. A flag
  expresses that exactly.
- The `--help` output lists `--inline` alongside `--offset`,
  giving the agent a single place to discover the option.
- The Reviewing_Agent's invocation becomes
  `scripts/review.py song-review --inline`, which is parallel in
  shape to other flagged invocations across the project.

### D2 — Minify scope: Chrome only; Script_Regions and Style_Regions pass through

**Choice**: `_minify_chrome` rewrites only bytes that are not
inside a `<script>...</script>` or `<style>...</style>` element.
Bytes inside those two element types are copied through
byte-identically.

**Considered**:
- **Full HTML minify** (rewrite everything, including JS and CSS).
  Rejected. Re-encoding the `<script id="due-data">` payload
  block risks regressing the Escape_Gate — the payload is a
  carefully `<` / `>` / `&`-escaped JSON document,
  and any reformat that touches its bytes is a chance to drop a
  backslash. The Inline_Script JavaScript also contains
  string literals (e.g. `'noopener noreferrer'`,
  `'http://www.w3.org/2000/svg'`) where naive whitespace collapse
  would break URLs and class names if it crossed string
  boundaries.
- **Use a third-party minifier** (`htmlmin`, `minify-html`).
  Rejected. Pulling a third-party dependency for a
  ~30-line pure-Python pass violates the project's stdlib-only
  posture. The Brazil package would also need a new dependency
  closure.

**Why Chrome-only**:
- Escape_Gate preservation falls out for free: the property test's
  oracle is "the rendered document's `<script>` content
  round-trips the hostile bytes byte-for-byte". If
  `_minify_chrome` provably never touches those bytes, the
  oracle holds transitively without any new assertion or test
  iteration.
- The wins from minifying inter-tag whitespace and stripping HTML
  comments cover the vast majority of size reduction in a
  static-template-plus-payload page like this one. The CSS and
  JS bodies are bounded in size; the marginal gain from
  minifying them is small.
- Pure-Python implementation in `scripts/review.py` keeps the
  stdlib-only invariant.

**Implementation sketch** (full code in Low-Level Design):

```python
def _minify_chrome(html_bytes: bytes) -> bytes:
    # Walk the input, alternating between Chrome_Regions and
    # <script>...</script> / <style>...</style> spans. Rewrite
    # Chrome_Regions; copy the spans through unchanged.
    ...
```

The walk uses `bytes.find` plus a small case-insensitive match for
the `<script` / `</script>` / `<style` / `</style>` tag opens.
No regex over the full document; no HTML parser. The boundaries
are well-defined for the rendered template (which produces
well-formed HTML by construction).

### D3 — Idempotence and correctness of the minify pass

**Choice**: `_minify_chrome` is idempotent for inputs whose
Chrome_Regions are already minified — running it twice produces
the same bytes as running it once.

**Why this matters**:
- A second-pass test (R-Test-Inline 6.4) is the cheapest
  correctness signal we get without DOM-level golden files. If
  the helper is idempotent, the test is one assertion:
  `_minify_chrome(_minify_chrome(x)) == _minify_chrome(x)`.
- Idempotence forces the helper to be deterministic and
  whitespace-collapsing rather than whitespace-rewriting (e.g. a
  helper that replaces inter-tag whitespace with `\n` would not
  be idempotent under repeated runs that re-collapse the `\n`).
- For Disk_Mode the Review_Page is written un-minified; for
  Inline_Mode it is written minified. A regenerated page that
  goes through `_minify_chrome` twice (e.g. a future cache layer)
  cannot accumulate spurious whitespace differences.

**The minification rules** (acceptance criteria 2.3 — restated for
this section):

1. Inside any Chrome_Region:
   1. Replace every run of two or more whitespace characters
      (one of `\t \n \r \f` or ASCII space) with a single space.
   2. Replace every run of whitespace bytes that sits **between**
      a `>` and a `<` (inter-tag whitespace) with the empty
      string. This rule applies **after** rule 1.1, so a single
      space between `>` and `<` is also dropped.
   3. Strip every HTML comment `<!-- ... -->` in full. Comments
      can span multiple lines and contain `>` characters; the
      pass scans for the literal byte sequence `<!--` and
      removes through the next `-->`.
2. Outside Chrome_Regions (inside Script_Regions and
   Style_Regions): no rewrite.

**Order of operations inside a Chrome_Region**: comments first,
then inter-tag whitespace collapse, then the all-whitespace-runs
collapse. Comments can contain `>` and `<` characters that would
fool a "between `>` and `<`" check if not removed first.

### D4 — Envelope shape disjointness

**Choice**: the two modes emit two disjoint key sets via two
separate `_common.success(...)` call sites in `_cmd_song_review`.
Disk_Mode emits `{"path", "due_count", "offset"}`; Inline_Mode
emits `{"html", "due_count", "offset"}`.

**Considered**:
- **Single call site, conditional dict.** A `result =
  {"due_count": ..., "offset": ...}; if args.inline: result["html"]
  = ...; else: result["path"] = ...` style. Pro: less code.
  Con: invites a future bug where both keys are populated.
- **Always-`html`, optional-`path`.** Always emit `html`, and
  also emit `path` in Disk_Mode. Pro: an agent can ignore the
  branch. Con: regresses R-Additive (Disk_Mode envelope grows a
  new key, which is a breaking change for any v0.1.4 consumer
  that asserts the exact key set — and v0.1.4 does have such an
  assertion in `test_review.py`).

**Why disjoint**:
- v0.1.4 has at least one test that asserts the Disk_Mode
  envelope key set is exactly `{"path", "due_count", "offset"}`.
  Adding `html` to the Disk_Mode envelope would break that test;
  R-Additive forbids editing the existing test.
- Two call sites make the contract grep-friendly: searching
  `_common.success(` in `review.py` shows two literal dicts that
  spell out their key sets in source.
- Future extension (a hypothetical third mode) can add a third
  call site without touching the existing two.

### D5 — Scope boundary: only `scripts/review.py` and one test file

**Choice**: the production-code diff is confined to
`scripts/review.py`. The test diff is confined to
`tests/integration/test_review.py` (additive only — no edits to
existing tests). `release.md` gets one bullet under v0.1.5.

**Why this matters**:
- `_common.success(...)` already does what Inline_Mode needs —
  it accepts a dict and emits a JSON envelope on stdout. No
  helper change is required there.
- The template (`scripts/review_template.html`) does not change
  shape; the rendered bytes that flow into `_minify_chrome` are
  byte-identical to the bytes Disk_Mode would have written.
- The DOM simulator (`tests/integration/_dom_sim.py`) is used by
  existing structural tests; Inline_Mode tests can re-use it
  unchanged because the rendered DOM (after JS execution) is
  identical to Disk_Mode's. The minify pass operates only on
  inter-tag whitespace and comments, neither of which affect the
  parsed DOM structure.
- Confining the diff to two files keeps the rollback to a
  trivial `git revert`.

### D6 — Decoding the minified bytes for the envelope

**Choice**: `_minify_chrome` operates on `bytes` and returns
`bytes`. The `_cmd_song_review` Inline_Mode branch decodes the
result via `.decode("utf-8")` before placing it in the envelope
dict, because `json.dumps` requires a `str` for string fields.

**Why bytes-in / bytes-out for the helper**:
- The rendered Review_Page is `bytes` at every step in the
  existing pipeline (`_TEMPLATE_PATH.read_bytes()`,
  `_render_page` returns `bytes`, `target.write_bytes(rendered)`).
  Keeping the minify helper in the same domain avoids spurious
  encode/decode round trips.
- Whitespace and comment scanning is well-defined on UTF-8 bytes
  because every character we inspect (`<`, `>`, `!`, `-`, ASCII
  whitespace) is single-byte in UTF-8 — multi-byte UTF-8
  sequences for non-ASCII characters never collide with these
  delimiters. The helper can scan bytes directly without
  decoding.

The `decode("utf-8")` at the call site is the only conversion;
`json.dumps(..., ensure_ascii=False)` writes the resulting `str`
back as UTF-8 in the envelope.

## Low-Level Design

### The new CLI surface (argparse diff)

```python
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review.py",
        description="Generate the HTML review page for due songs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sr = sub.add_parser("song-review", help="Render App_Root/output/review_<EPOCH>.html.")
    sr.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Shift the 'now' comparison forward by N seconds (default 0).",
    )
    sr.add_argument(                                                     # NEW
        "--inline",                                                      # NEW
        action="store_true",                                             # NEW
        help=(                                                           # NEW
            "Return the rendered HTML in the envelope's 'html' field "   # NEW
            "instead of writing it to disk; skips the file write "       # NEW
            "entirely and minifies the response."                        # NEW
        ),                                                               # NEW
    )                                                                    # NEW
    return p
```

The subparser help line for `song-review` is unchanged (it still
describes the default Disk_Mode output path, which is correct —
that is what runs when no flag is given).

### The `_cmd_song_review` branch

```python
def _cmd_song_review(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Build payload, render page, and either write a file (Disk_Mode)
    or emit the minified HTML inline (Inline_Mode)."""
    payload = _build_payload(conn, int(args.offset))
    try:
        template_bytes = _TEMPLATE_PATH.read_bytes()
    except FileNotFoundError as exc:
        raise _common.KnownError(
            "INTERNAL_ERROR",
            "review template missing",
            {"path": str(_TEMPLATE_PATH)},
        ) from exc

    rendered = _render_page(payload, template_bytes)

    if args.inline:                                                      # NEW
        minified = _minify_chrome(rendered)                              # NEW
        _common.success(                                                 # NEW
            {                                                            # NEW
                "html": minified.decode("utf-8"),                        # NEW
                "due_count": payload["due_count"],                       # NEW
                "offset": int(args.offset),                              # NEW
            }                                                            # NEW
        )                                                                # NEW
        return                                                           # NEW (defensive — success() exits)

    app_root = _common.app_root(__file__)
    output_dir = app_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"review_{_common.now_epoch()}.html"
    target.write_bytes(rendered)

    _common.success(
        {
            "path": str(target),
            "due_count": payload["due_count"],
            "offset": int(args.offset),
        }
    )
```

The Disk_Mode branch (after the `if args.inline:` block) is
byte-identical to v0.1.4 — same `mkdir`, same filename scheme,
same envelope dict literal. R-Additive 5.7 is satisfied by
inspection of the diff.

### The `_minify_chrome` helper (full body)

Pure-Python, stdlib-only. Bytes in, bytes out. Operates on the
rendered HTML in three passes:

1. Segment the input into alternating Chrome_Regions and
   passthrough spans (`<script>...</script>` and
   `<style>...</style>`).
2. For each Chrome_Region: strip HTML comments, collapse
   whitespace, drop inter-tag whitespace.
3. Re-join with the passthrough spans untouched.

```python
import re

# Compiled regexes used by _minify_chrome. Defined at module scope so
# they are compiled once at import time, not on every render.
_PASSTHROUGH_RE = re.compile(
    rb"(?is)(<(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>)"
)
_HTML_COMMENT_RE = re.compile(rb"<!--.*?-->", re.DOTALL)
_WHITESPACE_RUN_RE = re.compile(rb"[ \t\n\r\f]{2,}")
_INTER_TAG_WS_RE = re.compile(rb">[ \t\n\r\f]+<")


def _minify_chrome(html_bytes: bytes) -> bytes:
    """Minify HTML chrome — collapse inter-tag whitespace and strip
    HTML comments — without touching <script> or <style> bodies.

    The pass is a three-step pipeline applied only to byte ranges
    that sit OUTSIDE <script>...</script> and <style>...</style>
    elements. Bytes inside those two element types pass through
    byte-identically. This is the contract relied on by the
    Escape_Gate property test: the <script id="due-data"> payload
    block survives untouched, so the test's "two <script> elements"
    and "payload round-trips byte-for-byte" oracles hold
    transitively.

    The pass is idempotent for inputs whose chrome regions are
    already minified.

    Args:
        html_bytes: A complete rendered Review_Page as UTF-8 bytes.

    Returns:
        The minified bytes. Length is less than or equal to the
        input length; for the shipped review template the output is
        strictly smaller because the template carries inter-tag
        whitespace and at least one HTML comment outside its
        <script> / <style> blocks.

    Examples:
        >>> _minify_chrome(b"<html>  <body>  <p>hi</p>  </body></html>")
        b'<html><body><p>hi</p></body></html>'
        >>> _minify_chrome(b"<html><!-- a comment --><body></body></html>")
        b'<html><body></body></html>'
        >>> # Script bodies pass through:
        >>> _minify_chrome(b"<html><script>  var x = 1;  </script></html>")
        b'<html><script>  var x = 1;  </script></html>'
    """
    parts = _PASSTHROUGH_RE.split(html_bytes)
    # _PASSTHROUGH_RE.split returns alternating non-match / match
    # segments: index 0 is chrome, 1 is the first <script> or <style>,
    # 2 is chrome, 3 is the next passthrough, and so on.
    out: list[bytes] = []
    for i, seg in enumerate(parts):
        if i % 2 == 1:
            out.append(seg)  # passthrough — byte-identical
            continue
        # Chrome region.
        seg = _HTML_COMMENT_RE.sub(b"", seg)
        seg = _WHITESPACE_RUN_RE.sub(b" ", seg)
        seg = _INTER_TAG_WS_RE.sub(b"><", seg)
        out.append(seg)
    return b"".join(out)
```

**Why three passes inside the chrome region, in this order**:

1. **Comments first.** A comment can contain `>` and `<`
   characters; if the inter-tag-whitespace pass ran first it would
   misinterpret comment internals as tag boundaries.
2. **Whitespace runs.** After comments are stripped, collapse
   every run of 2+ whitespace bytes to a single space. This
   normalises the input so the inter-tag pass has a single,
   predictable byte to delete.
3. **Inter-tag whitespace.** A single space between `>` and `<`
   is no longer needed for browser parsing; drop it. (Browsers
   ignore inter-tag whitespace anyway when laying out non-text
   content, so this is a pure size win.)

**Why `(?is)` on the passthrough regex**:

- `(?i)` (case-insensitive) catches `<SCRIPT>` and `<STYLE>` in
  the unlikely case the template ever uses uppercase tag names.
  The shipped template uses lowercase, but this is cheap defense.
- `(?s)` (dot-matches-newline) lets `.*?` cross line boundaries
  in multi-line script bodies — which the shipped Inline_Script
  is.
- The `[^>]*` inside `<script\b[^>]*>` consumes attributes on
  the start tag (e.g. `<script id="due-data" type="application/json">`).
- The closing tag `</(?:script|style)\s*>` allows optional
  whitespace before the `>` per the HTML spec, even though the
  shipped template doesn't use it.

**Why segmenting via `re.split` rather than a hand-rolled walk**:

- `re.split` with a capturing group yields alternating
  non-matched / matched segments — exactly the structure the
  pass needs.
- Even-indexed segments are chrome; odd-indexed segments are
  passthrough.
- Segment boundaries are exact: every byte of the input lands in
  exactly one segment, so concatenation reconstructs the input
  losslessly when no rewrites apply (idempotence base case).

### Edge cases the helper handles

The helper's correctness rests on three facts about the shipped
template:

1. **`<script>` and `<style>` start tags are well-formed and not
   nested** — HTML forbids nesting `<script>` inside `<script>`,
   and the template does not nest `<style>` either. The greedy
   `.*?` between the start and end tag captures exactly one
   element body per match.
2. **No `</script>` substring appears inside `<script>` bodies
   except as the literal end tag.** This is exactly the property
   the Escape_Gate guarantees for the payload block: hostile
   `</script>` bytes in a song name are rewritten to
   `<\/script>` (via the `<` escape) before they enter the
   payload, so the regex `</script\s*>` cannot misfire inside
   the payload block.
3. **No `<script` or `<style` substring appears inside an HTML
   attribute value** in the rendered template. The template's
   chrome contains only plain markup, and the payload's hostile
   bytes are escaped before they land in the document.

If a future template change ever violates one of these
preconditions, the test added per R-Test-Inline 6.5 (Escape_Gate
preservation) is the failing oracle — the parsed DOM count of
`<script>` elements would diverge.

### The new tests (full bodies sketched)

All five live in `tests/integration/test_review.py`. They follow
the existing file's style — `subprocess.run` against the script,
JSON-parse stdout, parse the rendered HTML via the existing
`_dom_sim.py` simulator (which is byte-identical from v0.1.4).

```python
def test_song_review_inline_envelope_shape(tmp_app_root, populate_due):
    # ... seed at least one due song ...
    result = run_song_review(tmp_app_root, ["--inline"])
    envelope = json.loads(result.stdout)
    assert set(envelope.keys()) == {"html", "due_count", "offset"}
    assert "path" not in envelope
    assert envelope["due_count"] >= 1
    assert envelope["offset"] == 0
    # html parses to the same DOM structure Disk_Mode produces
    dom = parse_html(envelope["html"])
    assert count_li_data_level(dom) == envelope["due_count"]
    assert count_script_data_block(dom) == 1


def test_song_review_inline_empty_state(tmp_app_root):
    # ... seed an empty DB (no due songs) ...
    result = run_song_review(tmp_app_root, ["--inline"])
    envelope = json.loads(result.stdout)
    assert set(envelope.keys()) == {"html", "due_count", "offset"}
    assert envelope["due_count"] == 0
    dom = parse_html(envelope["html"])
    assert count_li_data_level(dom) == 0


def test_song_review_inline_writes_no_file(tmp_app_root, populate_due):
    output_dir = tmp_app_root / "output"
    # Pre-condition: output dir doesn't exist (or is empty).
    assert not output_dir.exists() or not list(output_dir.iterdir())
    result = run_song_review(tmp_app_root, ["--inline"])
    assert result.returncode == 0
    # Post-condition: still no file.
    assert not output_dir.exists() or not list(output_dir.iterdir())


def test_minify_chrome_skips_script_and_style_and_is_idempotent():
    from scripts.review import _minify_chrome
    sample = (
        b"<html>  <head>\n  <style>\n  body { color: red; }\n  </style>\n  "
        b"</head><body>  <!-- a comment -->  <p>hi</p>  "
        b"<script id=\"due-data\" type=\"application/json\">"
        b"{\"a\":\n  1, \n \"b\":\n  2}"
        b"</script>  </body></html>"
    )
    out = _minify_chrome(sample)
    # 1. Script body byte-identical
    assert b"{\"a\":\n  1, \n \"b\":\n  2}" in out
    # 2. Style body byte-identical
    assert b"\n  body { color: red; }\n  " in out
    # 3. Inter-tag whitespace collapsed in chrome
    assert b">  <" not in out
    assert b"> <" not in out
    # 4. HTML comment stripped from chrome
    assert b"<!--" not in out
    assert b"a comment" not in out
    # 5. Idempotence
    assert _minify_chrome(out) == out


def test_song_review_inline_preserves_escape_gate(tmp_app_root, populate_due_with_hostile_song_name):
    # Seed a song whose name is the literal string
    # "</script><script>alert(1)</script>".
    result = run_song_review(tmp_app_root, ["--inline"])
    envelope = json.loads(result.stdout)
    # Exactly two <script> elements in the envelope's html: the
    # payload block and the Inline_Script.
    dom = parse_html(envelope["html"])
    assert count_script_elements(dom) == 2
    # The payload's song_name round-trips byte-for-byte.
    payload = parse_payload_from_dom(dom)
    assert any(
        s["song_name"] == "</script><script>alert(1)</script>"
        for s in payload["due_songs"]
    )
```

`run_song_review`, `parse_html`, `count_li_data_level`,
`count_script_data_block`, `count_script_elements`, and
`parse_payload_from_dom` are existing test helpers in
`tests/integration/test_review.py` and `tests/integration/_dom_sim.py`.
The tests reuse them; no new helper is added.

## Correctness Properties

### Property 1 — Disk_Mode envelope unchanged

_For any_ DB state and any `--offset N`, when `song-review` is
invoked WITHOUT `--inline`, the resulting Success_Envelope's key
set SHALL be exactly `{"path", "due_count", "offset"}` and the
file at `path` SHALL be byte-identical to what v0.1.4 would have
produced for the same inputs.

**Validates**: R-Additive (5.7).

**Test oracle**: every existing test in
`tests/integration/test_review.py` — unchanged. They already pin
this contract.

### Property 2 — Inline_Mode envelope shape and minify-DOM equivalence

_For any_ DB state and any `--offset N`, when `song-review` is
invoked WITH `--inline`, the resulting Success_Envelope's key set
SHALL be exactly `{"html", "due_count", "offset"}` and the
`html` field SHALL parse to the same DOM tree (same elements,
attributes, script content, style content) as the Disk_Mode file
parsed for the same inputs.

**Validates**: R-Inline-Flag (1.3, 1.5), R-Minify (2.4),
R-Envelope-Disjoint (4.2).

**Test oracle**: the new
`test_song_review_inline_envelope_shape` test (R-Test-Inline 6.1).

### Property 3 — Script_Region byte-equality

_For any_ rendered Review_Page `R` and any `<script>...</script>`
element with start offset `s_open` and end offset `s_close`,
`_minify_chrome(R)[corresponding range]` SHALL be byte-identical
to `R[s_open:s_close]`. Same for `<style>...</style>` ranges.

**Validates**: R-Minify (2.1, 2.2), R-Escape-Preserve (3.3).

**Test oracle**: the new
`test_minify_chrome_skips_script_and_style_and_is_idempotent`
test (R-Test-Inline 6.4) plus, transitively, the existing
`tests/integration/property/test_escape_injection_property.py` —
unchanged. Because Script_Region bytes are unchanged by the
minify pass, the existing property test's "two `<script>`
elements + payload round-trip" oracle holds when applied to the
Disk_Mode bytes; for Inline_Mode, the new
`test_song_review_inline_preserves_escape_gate` test (6.5)
covers the same oracle directly.

### Property 4 — Idempotence of the minify pass

_For any_ input `x` such that `_minify_chrome(x)`'s
Chrome_Regions are already minified, `_minify_chrome(_minify_chrome(x)) ==
_minify_chrome(x)`.

**Validates**: R-Minify (2.6).

**Test oracle**: assertion 5 in the
`test_minify_chrome_skips_script_and_style_and_is_idempotent`
test.

## Testing Strategy

### Existing tests that stay unchanged

All of these continue to pass byte-identically. Zero assertion
edits, zero iteration-count changes.

- **`tests/integration/test_review.py`** — every existing test in
  the file. The Disk_Mode default path is byte-identical to
  v0.1.4, so every existing assertion (envelope shape, payload
  fields, file path scheme, INTERNAL_ERROR paths, `--offset`
  parity, no-DB-write, etc.) holds without modification.
- **`tests/integration/property/test_escape_injection_property.py`**
  — unchanged. The property test runs against the Disk_Mode
  output (it invokes `song-review` without `--inline`); that
  surface is byte-identical to v0.1.4. Inline_Mode's
  Escape_Gate preservation is covered by the new
  `test_song_review_inline_preserves_escape_gate` test, not by
  extending this property test.
- **`tests/integration/property/test_due_property.py`** —
  unchanged.
- **`tests/integration/_dom_sim.py`** — unchanged. The simulator
  is shape-agnostic; it parses whatever HTML you hand it. The
  minified HTML parses to the same DOM as the un-minified HTML
  (the minify pass only touches inter-tag whitespace and HTML
  comments, neither of which affects the parsed tree), so the
  simulator works on Inline_Mode output without modification.
- Every other test in `tests/integration/`.

### New tests added

Five new tests in `tests/integration/test_review.py` per
R-Test-Inline (6.1 – 6.5). All five live in the same file as the
existing tests; no new test file is created.

1. `test_song_review_inline_envelope_shape` — happy-path
   Inline_Mode against a populated DB.
2. `test_song_review_inline_empty_state` — Inline_Mode against
   an empty-due DB.
3. `test_song_review_inline_writes_no_file` — confirms no file
   under `App_Root/output/`.
4. `test_minify_chrome_skips_script_and_style_and_is_idempotent`
   — direct unit test of the helper.
5. `test_song_review_inline_preserves_escape_gate` — hostile
   song name; assert two `<script>` elements and byte-for-byte
   payload round-trip in the envelope's `html` field.

### Manual smoke checklist

Automated coverage stops at "the helper works and the envelope
shape is right". For human verification:

1. Run `scripts/review.py song-review --inline | jq -r .html >
   /tmp/page.html`.
2. Open `/tmp/page.html` in a browser. Confirm the page renders
   identically to a Disk_Mode-generated `review_<EPOCH>.html` —
   same cards, same globe icons, same shows.
3. Compare byte sizes: `wc -c < /tmp/page.html` vs.
   `wc -c < output/review_<EPOCH>.html` (the most recent
   Disk_Mode generation). The minified file SHALL be smaller.
4. Confirm `App_Root/output/` did not gain a new file from the
   `--inline` invocation.
5. Run `scripts/review.py song-review --help` and confirm
   `--inline` appears in the help text alongside `--offset`.

If any step fails, the release does not ship.

## Out of Scope

Explicitly not part of this spec.

- **JavaScript or CSS minification.** The minify pass is HTML-only
  and skips Script_Regions and Style_Regions by construction. JS
  minification would require a real JS parser and is out of scope.
- **Server-side DOM rendering.** The Inline_Script still builds
  the DOM in the browser from `JSON.parse(textContent)`. Inline_Mode
  delivers the same template + payload bytes that Disk_Mode
  delivers; the DOM is built browser-side in both modes.
- **Streaming output.** The Success_Envelope is one JSON document
  on one line, written via the existing `_common.success(...)`
  helper. No chunking, no progress events.
- **Compression** (gzip, brotli) of the inline payload. Out of
  scope for this release.
- **A "both" mode** that writes the file *and* returns the HTML
  inline. R-Envelope-Disjoint forbids this in the current release.
- **Template changes**, `_common.py` changes, or any other
  production-script changes. R-Additive pins the boundary.
- **Short-form CLI alias** (`-i`) for `--inline`.

## Rollout

- **Release vehicle**: v0.1.5 through the existing release
  pipeline (`.github/workflows/release.yml`). No pipeline changes.
- **Commit shape**: one commit. Scope `review`. Suggested title:
  `feat(review): add --inline flag for inline minified HTML response`.
- **Schema**: no change. `scripts/_common.py:EXPECTED_SCHEMA` is
  untouched.
- **Payload schema**: no change. The Due_Data_Payload is
  byte-identical between Disk_Mode and Inline_Mode for the same
  inputs.
- **CLI surface**: additive. `--inline` is a new opt-in flag on
  `song-review`. Existing invocations (`song-review`,
  `song-review --offset N`) keep their v0.1.4 semantics.
- **File delta** (exhaustive — the spec's diff is exactly these
  three files):
  - `scripts/review.py` — the `--inline` argparse addition, the
    new `_minify_chrome` helper plus its three module-level
    compiled regexes, and the small Inline_Mode branch in
    `_cmd_song_review`. Disk_Mode code path is byte-identical to
    v0.1.4.
  - `tests/integration/test_review.py` — five new test functions
    per R-Test-Inline (6.1 – 6.5). No existing test in the file
    is edited.
  - `release.md` — one bullet under v0.1.5 describing the new
    flag and the minified inline HTML response.

  **Zero changes to**: `scripts/review_template.html`,
  `scripts/_common.py`, every other production script,
  `tests/integration/_dom_sim.py`, every existing test in
  `tests/integration/test_review.py`, every property test under
  `tests/integration/property/`.

- **Risk**: low. The Disk_Mode default behavior is
  byte-identical, so the existing test suite (the v0.1.4-passing
  set, unchanged) gates regression. The new code is additive and
  guarded by the explicit `--inline` opt-in.
- **Rollback**: trivial — revert the commit. The v0.1.4 surface
  comes back; previously-generated `review_<EPOCH>.html` files
  are unaffected; agents that adopted `--inline` see the flag
  disappear from `--help` and revert to the file-based flow.
