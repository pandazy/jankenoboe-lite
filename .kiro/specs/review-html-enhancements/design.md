# Design Document

## Overview

`scripts/review.py` gets cut in half. After this spec lands, it does only
data work — run the R7 due SQL, join song/artist/shows, build one
Python dict (the Due_Data_Payload), and write one HTML file. Every
HTML tag, every CSS rule, and every line of JavaScript that used to
live in Python moves into a single static file: `scripts/review_template.html`.
`review.py` reads that file as bytes, substitutes the payload into
exactly one marker, and writes the result to
`App_Root/output/review_<EPOCH>.html`. The Review_Page's inline
JavaScript parses the embedded JSON and builds the visible DOM on
load. This design follows the parent `anime-song-learning-app`
design's **HTML Review Generation** section (R8) and its
**Packaging** section (R20); the broader app shape (App_Root, script
I/O contracts, error envelopes, single-time-seam, stdlib-only
runtime) is defined there and not restated here.

## Architecture

### Rendering flow

```mermaid
flowchart LR
  db[("db/datasource.db<br/>SQLite")]
  py["scripts/review.py<br/>(data pipeline)"]
  tpl["scripts/review_template.html<br/>(Template_File, read as bytes)"]
  payload["Due_Data_Payload<br/>(Python dict)"]
  jsonstr["json.dumps(payload,<br/>ensure_ascii=False)<br/>+ &lt; → \\u003c escape"]
  html["output/review_&lt;EPOCH&gt;.html<br/>(Review_Page)"]
  browser["Browser opens file://"]
  dom["Rendered_DOM<br/>(built by Inline_Script)"]

  db -->|R7 due SQL + joins| py
  py --> payload
  tpl -->|read bytes| py
  payload --> jsonstr
  jsonstr -->|substitute exactly<br/>one marker| py
  py -->|write bytes| html
  html --> browser
  browser -->|parse JSON from<br/>&lt;script id=&quot;due-data&quot;&gt;| dom
  dom -->|Inline_Script walks<br/>due_songs[]| dom
```

Key invariants in this flow:

- The marker (see **Template_File skeleton** below) occurs exactly
  once in the Template_File. `review.py` verifies it is present; a
  missing marker is an install-corruption case (`INTERNAL_ERROR` per
  parent R3).
- The payload is serialised with `ensure_ascii=False` so non-ASCII
  song/artist/show names stay human-readable in the rendered file.
- After `json.dumps`, every `<` in the serialised JSON is rewritten
  to `\u003c` (and `&` → `\u0026`, `>` → `\u003e`). This preserves
  the JSON bytes as parsed by `JSON.parse` while guaranteeing no
  `</script>` sequence can appear inside the `<script
  type="application/json">` block, even if a song name literally
  contains `</script>` (R-RH-6.6, R-RH-6.4).
- The payload is carried inside a `<script id="due-data"
  type="application/json">...</script>` element, not a global
  variable. The Inline_Script reads it with
  `document.getElementById('due-data').textContent`. No `eval`, no
  `Function(...)`, no network call (R-RH-6.1 / R-RH-6.2).

## Template_File skeleton

The Template_File lives at `scripts/review_template.html`. It ships
as part of the `scripts/` tree per R20.2 / R-RH-7.1. The skeleton
below is a design-level reference — the actual file can format its
CSS however it likes as long as the marker element, the classes the
Inline_Script targets, and the noscript fallback are preserved.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Songs due for review</title>
  <style>
    /* Base layout — stays close to the jankenoboe look. */
    body { font-family: system-ui, sans-serif; max-width: 780px;
           margin: 2em auto; padding: 0 1em; }
    h1 { margin-bottom: 0.2em; }
    .meta { color: #666; margin-bottom: 1.5em; }

    /* Noscript fallback: shown by default, hidden once the
       Inline_Script tags <body> as js-active. Satisfies
       R-RH-1.6. */
    .js-required { color: #a00; font-weight: 600; padding: 1em 0; }
    body.js-active .js-required { display: none; }

    /* Per-item structure (built at runtime by the Inline_Script). */
    ol { list-style-position: inside; padding: 0; }
    li[data-level] { padding: 0.8em 0; border-top: 1px solid #eee; }
    li[data-level]:first-child { border-top: 0; }

    /* Level pill. */
    .level { display: inline-block; padding: 0.1em 0.6em;
             background: #0a84ff; color: white; border-radius: 3px;
             font-size: 0.85em; margin-right: 0.6em; }

    /* Song title + inline name_context. */
    .song { font-size: 1.15em; font-weight: 600; display: inline-block; }
    .name-context { color: #888; font-style: italic; margin-left: 0.3em; }

    /* Artist line sits under the title. */
    .artist { color: #333; margin-top: 0.1em; }

    /* Shows block and per-show sub-blocks (R-RH-3). */
    .shows-section { margin-top: 0.3em; }
    .show-block { margin: 0.3em 0 0 1.2em; }
    .show-name { font-weight: 500; }
    .show-meta { color: #777; font-size: 0.9em; }

    /* Per-show link list (R-RH-2, R-RH-3.2). */
    .links { margin: 0.2em 0 0 0; padding-left: 1.4em;
             font-size: 0.9em; }
    .links li { list-style-type: disc; }
    .links a { color: #0a84ff; text-decoration: none; }
    .links a:hover { text-decoration: underline; }

    /* Copy buttons (R-RH-4). No onclick, no icons from CDN. */
    .copy-btn { margin-left: 0.4em; font-size: 0.8em;
                padding: 0 0.4em; cursor: pointer; }
    .copy-btn.flash { background: #d5f5d5; }

    /* Session "done" highlight (R-RH-5). Cosmetic only. */
    li[data-level].done { opacity: 0.45; background: #f5f5f5; }

    /* Empty state. */
    .empty-state { color: #777; font-style: italic;
                   padding: 2em 0; text-align: center; }
  </style>
</head>
<body>
  <h1>Songs due for review</h1>

  <!-- Visible only before the Inline_Script adds body.js-active. -->
  <p class="js-required">
    This page needs JavaScript to render the due list.
  </p>

  <!-- The Inline_Script mounts the Rendered_DOM into this element. -->
  <div id="root"></div>

  <!-- The Due_Data_Payload. `review.py` substitutes this marker with
       the escaped JSON. The marker is unique in the Template_File
       and cannot occur naturally in JSON output. -->
  <script id="due-data" type="application/json"><!-- DUE_DATA_JSON --></script>

  <!-- The Inline_Script: single element, no src, no type="module",
       no network references. -->
  <script>
    /* See the "Inline_Script flow" section below for the full
       algorithm. Tagged here only to mark the element. */
  </script>
</body>
</html>
```

Notes on the skeleton:

- The substitution marker is the literal string
  `<!-- DUE_DATA_JSON -->`. It sits inside the
  `<script type="application/json">` so it is never rendered as
  visible text and is never parsed as JavaScript by the browser.
- The `root` `<div>` exists so the Inline_Script can attach the
  built `<ol>` under a known node without touching `<body>`
  directly. This keeps the noscript fallback paragraph's position
  predictable.
- `body.js-active` is added by the Inline_Script as its first DOM
  action, which hides the `<p class="js-required">` message. On a
  browser with JS disabled, the message stays visible and no DOM
  construction happens (R-RH-1.6).

## Components and Interfaces

Three components; one per layer.

1. **Data pipeline** (`scripts/review.py`). Queries the DB. Builds
   the Due_Data_Payload. Reads the Template_File. Substitutes the
   payload. Writes the Review_Page. No HTML tag literals.
2. **Template_File** (`scripts/review_template.html`). Static bytes.
   Carries the document chrome, CSS, the Inline_Script, and the
   substitution marker. Never read by any other script.
3. **Inline_Script** (embedded in the Template_File). Reads the
   payload from `<script id="due-data">`. Builds the DOM. Installs
   delegated event handlers for copy buttons, link clicks, and item
   clicks.

The interface between (1) and (2) is the substitution marker plus
the JSON schema below. The interface between (2) and (3) is
`document.getElementById('due-data').textContent`.

## Data Models

### Due_Data_Payload schema (exact)

```json
{
  "generated_at": 1777660532,
  "due_count": 1059,
  "due_songs": [
    {
      "learning_id": "11111111-1111-1111-1111-111111111111",
      "song_id":     "22222222-2222-2222-2222-222222222222",
      "song_name":   "Again",
      "song_name_context": "TV size",
      "artist_id":   "33333333-3333-3333-3333-333333333333",
      "artist_name": "Yui",
      "artist_name_context": "solo",
      "display_level": 18,
      "shows": [
        {
          "show_id":        "44444444-4444-4444-4444-444444444444",
          "show_name":      "Fullmetal Alchemist: Brotherhood",
          "show_name_romaji": "Hagane no Renkinjutsushi",
          "show_vintage":   "Spring 2009",
          "show_s_type":    "TV",
          "media_urls": [
            "http://example/ph/a.mp4",
            "http://example/rel/b.mp4"
          ]
        }
      ]
    }
  ]
}
```

Field contract, per field:

| Field                     | Type            | Nullable? | Notes                                                  |
|---------------------------|-----------------|-----------|--------------------------------------------------------|
| `generated_at`            | integer (epoch) | no        | `_common.now_epoch()` at render time.                  |
| `due_count`               | integer         | no        | `== len(due_songs)`.                                   |
| `due_songs`               | array           | no        | May be empty (empty-state case).                       |
| `due_songs[].learning_id` | string (UUID)   | no        | From `learning.id`.                                    |
| `due_songs[].song_id`     | string (UUID)   | no        | From `song.id`.                                        |
| `due_songs[].song_name`   | string          | no        | From `song.name`; DB column NOT NULL.                  |
| `due_songs[].song_name_context` | string    | **yes — `null` or `""`** | From `song.name_context`; parent R8 allows NULL in DB. |
| `due_songs[].artist_id`   | string (UUID)   | no        | From `artist.id`.                                      |
| `due_songs[].artist_name` | string          | no        | From `artist.name`; DB column NOT NULL.                |
| `due_songs[].artist_name_context` | string  | **yes — `null` or `""`** | From `artist.name_context`.                            |
| `due_songs[].display_level` | integer       | no        | R17.2: `learning.level + 1`.                           |
| `due_songs[].shows`       | array           | no        | May be empty if the song has no live shows.            |
| `shows[].show_id`         | string (UUID)   | no        | From `show.id`.                                        |
| `shows[].show_name`       | string          | no        | From `show.name`; DB column NOT NULL.                  |
| `shows[].show_name_romaji`| string          | **yes — `null` or `""`** | From `show.name_romaji`; NULL allowed per parent R8.   |
| `shows[].show_vintage`    | string          | **yes — `null` or `""`** | From `show.vintage`.                                   |
| `shows[].show_s_type`     | string          | **yes — `null` or `""`** | From `show.s_type`.                                    |
| `shows[].media_urls`      | array of string | no (may be empty) | Sorted, deduped. R8.5 union of `play_history.media_url` and `rel_show_song.media_url` for `(show, song)`, empty strings dropped. |

Null vs empty string: the DB allows `name_context`, `name_romaji`,
`vintage`, `s_type` to be NULL (parent R8 data model). `review.py`
passes those through unchanged — `None` in Python becomes `null` in
JSON. Existing `_shows_for_song` already normalises missing media
URLs to `""` and drops them before building the sorted-deduped set,
so `media_urls` elements are always non-empty strings.

Payload ordering is fully determined by the existing SQL:
`due_songs` is ordered `ORDER BY l.level DESC, l.id ASC` (matches
`_DUE_SQL`); `shows` is ordered `ORDER BY sh.name, sh.id` (matches
`_shows_for_song`); `media_urls` is the sorted set union.

### Template substitution marker

The marker is the exact byte sequence `<!-- DUE_DATA_JSON -->`.
`review.py` asserts `template_bytes.count(b"<!-- DUE_DATA_JSON -->") == 1`
before substituting. Zero occurrences → `INTERNAL_ERROR` (template
corrupt). More than one → `INTERNAL_ERROR` (ambiguous). The marker
is not valid JSON, so it cannot arise from any payload value; and
it appears inside a `<script type="application/json">` tag so the
browser never tries to execute it.

## Python data pipeline (`scripts/review.py` after the rewrite)

The file keeps its argparse front (`song-review` subcommand),
`_common.open_db`, and `_common.success` / `_common.run`
integration. Everything that used to build HTML strings is
deleted. No function under `scripts/` contains an HTML tag literal.

### Module layout

```python
# scripts/review.py — pseudocode / signatures only.

_TEMPLATE_PATH = pathlib.Path(__file__).parent / "review_template.html"
_MARKER_BYTES = b"<!-- DUE_DATA_JSON -->"

def _build_payload(conn: sqlite3.Connection) -> dict:
    """
    Run _DUE_SQL, join shows + media URLs per existing helpers,
    return the Due_Data_Payload dict.

    - Reuses _DUE_SQL unchanged.
    - Reuses _shows_for_song / _media_urls_from_play_history unchanged
      (they already produce the sorted, deduped media_urls lists).
    - display_level is taken from the SELECT (l.level + 1).
    - generated_at = _common.now_epoch().
    - due_count = len(due_songs).
    """
    ...

def _escape_json_for_html(text: str) -> str:
    """
    Replace `<`, `>`, and `&` in a serialised JSON string so it can
    be safely placed inside a <script type="application/json"> tag.
    - '<'  -> r'\u003c'
    - '>'  -> r'\u003e'
    - '&'  -> r'\u0026'
    Only affects the three ASCII characters above; all other bytes
    are passed through unchanged. The escaped string remains valid
    JSON (each \uXXXX is already a legal JSON escape).
    """
    return (
        text
        .replace("&", r"\u0026")
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
    )

def _render_page(payload: dict, template_bytes: bytes) -> bytes:
    """
    Turn the payload + template bytes into the final Review_Page bytes.

    - Serialises payload with json.dumps(payload, ensure_ascii=False).
    - Runs _escape_json_for_html over the JSON string.
    - Verifies the marker is present exactly once; raises
      KnownError("INTERNAL_ERROR", ...) otherwise.
    - Substitutes exactly one occurrence of _MARKER_BYTES with the
      escaped JSON encoded as UTF-8.
    - Returns the final HTML bytes (no extra formatting).
    """
    ...

def _cmd_song_review(conn, _args) -> None:
    """
    Orchestrates the pipeline:
      1. payload = _build_payload(conn)
      2. template_bytes = _TEMPLATE_PATH.read_bytes()
         - FileNotFoundError -> KnownError("INTERNAL_ERROR",
           "review template missing", {"path": str(_TEMPLATE_PATH)})
      3. rendered = _render_page(payload, template_bytes)
      4. output_dir = _common.app_root(__file__) / "output"
         output_dir.mkdir(parents=True, exist_ok=True)
      5. target = output_dir / f"review_{_common.now_epoch()}.html"
         target.write_bytes(rendered)
      6. _common.success({"path": str(target),
                          "due_count": payload["due_count"]})
    """
    ...
```

All of the existing SQL (`_DUE_SQL`, `_shows_for_song`,
`_media_urls_from_play_history`) stays as-is — the query layer is
already correct per parent R7 and R8. Every `html.escape` call, the
`_HEADER`/`_FOOTER` string constants, the `_render`, `_render_item`,
`_render_shows`, and `_render_urls` functions are deleted.

### Why bytes, not strings

Reading and writing the Template_File as bytes (rather than text)
keeps the pipeline neutral about the template's line endings and
trailing whitespace and avoids Python coercing anything through the
`str` UTF-8 round-trip twice. The escaped JSON is encoded to UTF-8
bytes before substitution because the Template_File's `<meta
charset="utf-8">` sets the document charset.

## Inline_Script flow

The Inline_Script is the one `<script>` element in the Template_File
with no `src`. It runs on document load and does exactly three
things: parse the payload, build the DOM, install delegated event
listeners.

### Load and parse

```js
// Inline_Script — pseudocode.

document.addEventListener('DOMContentLoaded', () => {
  const node = document.getElementById('due-data');
  const data = JSON.parse(node.textContent);   // may throw on a
                                               // corrupt payload;
                                               // see Error Handling.

  document.body.classList.add('js-active');    // hides .js-required.

  const root = document.getElementById('root');
  root.appendChild(renderMeta(data));
  root.appendChild(renderList(data.due_songs));
});
```

### DOM construction

```js
function renderMeta(data) {
  const p = document.createElement('p');
  p.className = 'meta';
  p.textContent = data.due_count + ' due.';
  return p;
}

function renderList(songs) {
  if (!songs || songs.length === 0) {
    const p = document.createElement('p');
    p.className = 'empty-state';
    p.textContent = 'No songs due.';
    return p;
  }
  const ol = document.createElement('ol');
  for (const s of songs) {
    ol.appendChild(renderSong(s));
  }
  return ol;
}

function renderSong(s) {
  const li = document.createElement('li');
  li.setAttribute('data-level', String(s.display_level));

  // Level pill.
  const pill = document.createElement('span');
  pill.className = 'level';
  pill.textContent = 'Level ' + s.display_level;
  li.appendChild(pill);

  // Song title + copy button + optional name_context.
  const title = document.createElement('span');
  title.className = 'song';
  title.textContent = s.song_name;
  li.appendChild(title);

  li.appendChild(copyButton(s.song_id));

  if (s.song_name_context) {
    const ctx = document.createElement('span');
    ctx.className = 'name-context';
    ctx.textContent = '(' + s.song_name_context + ')';
    li.appendChild(ctx);
  }

  // Artist line + copy button.
  const artist = document.createElement('div');
  artist.className = 'artist';
  const aName = document.createElement('span');
  aName.textContent = s.artist_name;
  artist.appendChild(aName);
  artist.appendChild(copyButton(s.artist_id));
  if (s.artist_name_context) {
    const ac = document.createElement('span');
    ac.className = 'name-context';
    ac.textContent = '(' + s.artist_name_context + ')';
    artist.appendChild(ac);
  }
  li.appendChild(artist);

  // Shows section — one block per linked live show.
  if (s.shows && s.shows.length > 0) {
    const section = document.createElement('div');
    section.className = 'shows-section';
    section.textContent = 'Shows:';
    for (const sh of s.shows) {
      section.appendChild(renderShowBlock(sh));
    }
    li.appendChild(section);
  }
  return li;
}

function renderShowBlock(sh) {
  const block = document.createElement('div');
  block.className = 'show-block';

  const name = document.createElement('span');
  name.className = 'show-name';
  name.textContent = sh.show_name;
  block.appendChild(name);

  block.appendChild(copyButton(sh.show_id));

  const extras = [sh.show_name_romaji, sh.show_vintage, sh.show_s_type]
    .filter(x => x);
  if (extras.length > 0) {
    const meta = document.createElement('span');
    meta.className = 'show-meta';
    meta.textContent = ' — ' + extras.join(', ');
    block.appendChild(meta);
  }

  // Per-show URL list (R-RH-3.2). Rendered only when media_urls
  // is non-empty, but the Show_Block itself is always rendered
  // (R-RH-3.4).
  if (sh.media_urls && sh.media_urls.length > 0) {
    const ul = document.createElement('ul');
    ul.className = 'links';
    for (const u of sh.media_urls) {
      const li = document.createElement('li');
      li.appendChild(renderAnchor(u));
      ul.appendChild(li);
    }
    block.appendChild(ul);
  }
  return block;
}

function renderAnchor(url) {
  const a = document.createElement('a');
  a.setAttribute('href', url);             // full, unmodified URL.
  a.textContent = mediaUrlBasename(url);   // short display text.
  return a;
}

function copyButton(copyTargetId) {
  const btn = document.createElement('button');
  btn.setAttribute('type', 'button');
  btn.setAttribute('data-copy-id', copyTargetId);
  btn.className = 'copy-btn';
  btn.textContent = '⧉';   // or 'copy'; purely cosmetic.
  return btn;
}
```

Every string leaf from the payload (`song_name`,
`artist_name`, `show_name`, name contexts, romaji, vintage, s_type,
and `url` for both the anchor's `href` attribute and its visible
text) is placed into the DOM via `textContent` or `setAttribute`.
The Inline_Script never builds HTML by string concatenation and
never assigns to `innerHTML`. This is the browser's own escape
guarantee: a song_name of `</script><script>alert(1)</script>` is
inserted as literal characters, not parsed as markup
(R-RH-6.4, P-RH-4).

### `Media_URL_Basename(url)`

```js
function mediaUrlBasename(url) {
  try {
    // Second arg is a throwaway base — makes protocol-relative or
    // relative URLs parseable. For well-formed http(s) URLs it has
    // no effect.
    const u = new URL(url, 'https://placeholder');
    let path = u.pathname || '';
    // Trim trailing slashes.
    while (path.endsWith('/')) path = path.slice(0, -1);
    if (path === '') return url;               // empty or '/' path.
    const idx = path.lastIndexOf('/');
    const last = idx < 0 ? path : path.slice(idx + 1);
    return last === '' ? url : last;
  } catch (_e) {
    return url;                                 // unparseable URL.
  }
}
```

Per R-RH-2.3 and the glossary: empty/`/` pathnames and unparseable
URLs fall back to the full URL string. The function never throws.

### Event delegation

Exactly one `click` listener on `document`, handling all three
interaction kinds:

```js
document.addEventListener('click', (ev) => {
  // 1. Copy button click — uses closest() to support clicks on
  //    inner text/glyph nodes inside the button.
  const btn = ev.target.closest('button[data-copy-id]');
  if (btn) {
    const id = btn.getAttribute('data-copy-id');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      // .writeText returns a Promise; swallow rejections so a
      // clipboard-permission denial cannot bubble to window.
      navigator.clipboard.writeText(id).catch(() => { /* no-op */ });
    }
    // Optional UX sugar: briefly flash the button.
    btn.classList.add('flash');
    setTimeout(() => btn.classList.remove('flash'), 600);
    ev.stopPropagation();                 // R-RH-4.7
    return;
  }

  // 2. Link click — default navigation; don't interfere with it.
  if (ev.target.closest('a[href]')) {
    return;                               // R-RH-5.3
  }

  // 3. Anywhere else inside a due-song <li> — toggle the
  //    Highlight_Class.
  const li = ev.target.closest('li[data-level]');
  if (li) {
    li.classList.toggle('done');          // R-RH-5.1, R-RH-5.4
  }
});
```

Three things to call out:

- The copy feedback flash (add `.flash` for ~600ms) is optional UX
  sugar. The acceptance criteria only require the clipboard call
  and `stopPropagation`; the flash is a design-level choice and
  can be removed without changing contracts.
- `navigator.clipboard?.writeText(...)` is guarded so the handler
  is a no-op on browsers or origins where the Clipboard API is
  unavailable (R-RH-6.5). The `.catch()` ensures a rejected promise
  (permission denied) does not surface as an unhandled promise
  rejection.
- The handler is installed on `document`, not on each button or
  each `<li>`. There are zero inline `onclick` attributes anywhere
  in the Rendered_DOM (R-RH-4.6, R-RH-5.5).

## Packaging edit (`tools/package.py`)

Per R-RH-7 the deployable zip must start shipping the `skills/`
tree while continuing to exclude `.kiro/`. The fix is a two-layer
model, documented explicitly in the module docstring and on the
`_SKIP_DIR_NAMES` comment.

### Layer 1: top-level copy list (inclusion by enumeration)

`tools/package.py` only ever asks `shutil.copytree` to look at
directories it explicitly names. Today that list is:

```python
_copy_scripts(staging)   # copies scripts/
```

After the edit:

```python
_copy_scripts(staging)   # copies scripts/
_copy_skills(staging)    # copies skills/   (new)
```

Plus `_empty_db(...)` and `_copy_extras(...)` as before for
`db/datasource.db`, `Makefile`, and `README.md`. No other directory
is ever passed to `copytree`, which means `.kiro/`, `docs/`,
`tests/`, `tools/`, `dist/`, `.venv/`, and similar are excluded
simply by not being named. `.kiro/` in particular is called out in
the updated module docstring as a hidden dev folder that
intentionally stays on the author's machine (R-RH-7.4).

### Layer 2: `_SKIP_DIR_NAMES` (defense-in-depth filter)

`_SKIP_DIR_NAMES` keeps its current role. It is applied in two
places:

1. As `shutil.ignore_patterns(*_SKIP_DIR_NAMES, "*.pyc")` inside
   both `_copy_scripts` and the new `_copy_skills` — so a
   `__pycache__` or `.pytest_cache` that somehow appears inside
   `scripts/` or `skills/` is filtered on copy.
2. As the `any(part in _SKIP_DIR_NAMES for part in rel.parts)`
   check inside `_zip_dir` — so even if a staging tree contains
   one of those names, the final archive skips the entry.

The set itself does not change (`__pycache__`, `.pytest_cache`,
`.ruff_cache`, `.mypy_cache`, `.coverage_data`, `.venv`, `venv`,
`output`, `.trace`). The docstring is updated to call this out as
defense-in-depth, not as the sole exclusion mechanism.

### New helper

```python
SKILLS_DIR = REPO_ROOT / "skills"

def _copy_skills(dest: pathlib.Path) -> None:
    """Copy ``skills/`` into ``dest/skills/``, skipping caches.

    Mirrors ``_copy_scripts``. The skill docs ship so Claude
    working against the deployed tree can see them.
    """
    if not SKILLS_DIR.exists():
        return
    shutil.copytree(
        SKILLS_DIR,
        dest / "skills",
        ignore=shutil.ignore_patterns(*_SKIP_DIR_NAMES, "*.pyc"),
    )
```

### Zip internal order

Stays stable. `_zip_dir` already walks `sorted(src_dir.rglob('*'))`
and writes entries in that order. With `skills/` added to the copy
list, the sort key simply grows by the new paths; the archive
remains byte-reproducible given identical source trees.

### Print summary

Append one line to the summary printed at the end of `main()`:

```
  - scripts/ (... .py files)
  - skills/  (... .md files)
  - db/datasource.db (empty, schema only)
  - Makefile, README.md (if present)
```

### Docstring update (excerpt)

The module docstring is updated to say, near the top:

> Produces ``dist/anilearn-simple-<YYYYMMDD>.zip`` containing:
>
>   * ``scripts/`` — runtime Python files (stdlib only)
>   * ``skills/`` — Claude skill docs that ship with the deployed tree
>   * ``db/datasource.db`` — a fresh, empty DB built from
>     ``tests/fixtures/schema.sql``
>   * ``Makefile`` — so the user can run ``make test`` or ``make clean``
>     in the dropped-in tree (runtime-friendly targets only)
>   * ``README.md`` — if present at the repo root
>
> Exclusion model (two layers):
>
>   1. **Inclusion by enumeration.** Top-level directories not on
>      the copy list — ``.kiro/`` (the author's spec folder),
>      ``docs/``, ``tests/``, ``tools/``, ``dist/``, ``.venv/``,
>      ``venv/``, ``output/`` — are excluded because
>      ``tools/package.py`` never hands them to ``shutil.copytree``
>      in the first place. ``.kiro/`` is called out by name as a
>      hidden dev folder that stays on the author's machine.
>
>   2. **Defense-in-depth.** ``_SKIP_DIR_NAMES`` is applied inside
>      every directory that *is* copied (``scripts/``, ``skills/``)
>      to keep caches (``__pycache__``, ``.pytest_cache``,
>      ``.ruff_cache``, ``.mypy_cache``, ``.coverage_data``,
>      ``.venv``, ``venv``, ``output``, ``.trace``) out of the zip
>      even if they happen to appear inside a copied tree.

## Correctness Properties

*A property is a characteristic or behavior that should hold true
across all valid executions of a system — essentially, a formal
statement about what the system should do. Properties serve as the
bridge between human-readable specifications and machine-verifiable
correctness guarantees.*

The parent spec already covers the due-selection SQL (parent
Properties 1-16). This spec adds properties specific to the
rendering-rewrite layer. Properties here reference Rendered_DOM;
tests resolve that by running the Python-side DOM simulator
described in **Testing Strategy**.

### Property 1: Python has no HTML tags

*For any* snapshot of the `scripts/` tree, no `.py` file contains an
HTML element opening tag as a code literal (outside docstrings and
comments).

**Validates: Requirements R-RH-1.2, P-RH-0.1**

### Property 2: Template substitution is total and unique

*For any* Due_Data_Payload produced by `_build_payload`, loading the
Template_File and passing it through `_render_page` with that
payload produces HTML bytes in which (a) the marker string no longer
appears, (b) the embedded `<script id="due-data">` textContent
parses as JSON equal to the payload, and (c) the document contains
exactly two `<script>` elements — the data block and the
Inline_Script.

**Validates: Requirements R-RH-1.4, R-RH-1.7, R-RH-6.4, P-RH-4.2**

### Property 3: Missing marker is an internal error

*For any* Template_File whose byte stream does not contain exactly
one `<!-- DUE_DATA_JSON -->` marker, `review.py song-review` exits
with `code = "INTERNAL_ERROR"` and writes nothing to `output/`.

**Validates: Requirements R-RH-1.8, P-RH-0.4**

### Property 4: `< ` escape breaks no JSON

*For any* Due_Data_Payload containing a string value that literally
includes the substring `</script>`, the rendered Review_Page's
`<script id="due-data">` textContent parses with `JSON.parse` to an
object equal to the original payload, and feeding the full document
to an HTML parser yields at most two `<script>` elements (the data
block and the Inline_Script).

**Validates: Requirements R-RH-6.6, R-RH-6.4, P-RH-4**

### Property 5: Short-name anchor round-trip

*For any* URL `U` drawn from a generator whose scheme is `http` or
`https`, host is a random hostname, and path is a random non-empty
path, the Rendered_DOM contains exactly one `<a>` element whose
`href` attribute parses back to `U` and whose visible text equals
`Media_URL_Basename(U)`. *For any* URL `U` whose path is empty or
`/`, or whose string is unparseable by `new URL`, the anchor's
visible text equals the full `U`.

**Validates: Requirements R-RH-2.1, R-RH-2.3, R-RH-2.4, P-RH-1**

### Property 6: Group-by-show partition

*For any* due song `S` with live linked shows `SH_1..SH_n` and
per-pair media-URL sets `U_1..U_n`:

1. The Rendered_DOM for `S` contains one Show_Block per show, in
   order.
2. The set of URLs rendered inside `SH_i`'s Show_Block equals `U_i`.
3. The URLs across all Show_Blocks for `S` partition `U_1 ∪ ... ∪ U_n`
   — every URL appears in exactly one Show_Block.
4. A Show_Block with `U_i == {}` still appears in the Rendered_DOM
   carrying the show's name and metadata.

**Validates: Requirements R-RH-3.1..R-RH-3.5, P-RH-2**

### Property 7: Copy button coverage

*For any* due song `S` with artist `A` and live shows `SH_1..SH_n`,
the Rendered_DOM contains: exactly one Copy_Button with
`data-copy-id == S.song_id` in `S`'s Due_Song_Item placed after the
song title; exactly one with `data-copy-id == A.artist_id` placed
after the artist name; and, for each `SH_i`, exactly one with
`data-copy-id == SH_i.show_id` inside that show's Show_Block placed
after the show name. Every Copy_Button has `type="button"` and no
`onclick` attribute.

**Validates: Requirements R-RH-4.1, R-RH-4.2, R-RH-4.3, R-RH-4.6, P-RH-3**

### Property 8: Text-field escape survives injection

*For any* name / name-context / romaji / vintage / s_type field
drawn from a generator that includes `<`, `>`, `&`, `"`, `'`, and
the literal strings `<script>`, `</script>`, and `javascript:`, the
field's characters never appear as live markup in the Review_Page —
HTML-parsing the Review_Page produces no `<script>` element beyond
the two declared by the Template_File, and the field's characters
appear only inside text nodes or attribute values built via
`textContent` / `setAttribute` in the Inline_Script's equivalent.

**Validates: Requirements R-RH-6.4, P-RH-4.1, P-RH-4.2**

### Property 9: Packaging allowlist and exclusion

*For any* synthetic `App_Root` containing at least `scripts/`,
`skills/`, `db/datasource.db`, `Makefile`, `README.md`,
`.kiro/specs/<SPEC>/requirements.md`, `docs/<DOC>.md`,
`output/review_<EPOCH>.html`, and `tools/package.py`, the zip
produced by `tools/package.py` (a) has no entry under `.kiro/`,
`docs/`, `output/`, `tools/`, `tests/`, `dist/`, `.venv/`, `venv/`,
`__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
`.trace/`, or `.coverage_data/`; (b) contains at least one entry
under `skills/`; (c) has a top-level path set that is a subset of
`{scripts/, skills/, db/, Makefile, README.md}`; and (d) contains
`db/datasource.db` as an empty schema-only database, not the
synthetic root's bytes.

**Validates: Requirements R-RH-7.1..R-RH-7.4, P-RH-5**

### Not a property: session highlight toggle

Per the spec's note on R-RH-5 (and the workflow's guidance on PBT
applicability), the `done`-class toggle is a cosmetic DOM change
whose behaviour does not vary meaningfully with input. It is
covered by three example-style tests, not a property:

- Click on a Due_Song_Item → `done` toggles on; click again → off.
- Click on a media `<a>` inside a Due_Song_Item → no toggle;
  default navigation proceeds.
- Click on a Copy_Button → no toggle (because `stopPropagation`
  runs before the `<li>` branch of the delegated handler).

## Error Handling

Three error surfaces on the Python side, all routed through
`_common.KnownError` / `_common.run` to the `INTERNAL_ERROR` code
per parent R3.7:

| Condition                                           | Code             | Where raised                                              |
|-----------------------------------------------------|------------------|-----------------------------------------------------------|
| `scripts/review_template.html` missing              | `INTERNAL_ERROR` | `_cmd_song_review` — treat as broken install.             |
| Marker absent or duplicated in Template_File bytes  | `INTERNAL_ERROR` | `_render_page` pre-substitution check.                    |
| Any other unexpected exception                      | `INTERNAL_ERROR` | `_common.run` catch-all (parent contract).                |

Message fields are short and actionable, following the parent
envelope shape:

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "review template missing",
    "details": {"path": "/.../scripts/review_template.html"}
  }
}
```

Browser-side surfaces are defensive-by-construction:

- Unparseable `media_url` → `Media_URL_Basename` returns the full
  URL string; `renderAnchor` sets it as both `href` and visible
  text. The anchor still renders. Never throws.
- `navigator.clipboard` undefined (e.g. Safari on `file://`, or a
  browser with the API disabled) → the delegated handler's
  feature-check skips the `.writeText` call. The button click is a
  no-op. No uncaught exception bubbles to the window (R-RH-6.5).
- A `navigator.clipboard.writeText` Promise rejection
  (permission denied, transient failure) is swallowed by the
  chained `.catch(() => {})`. The click is still a no-op.

If the embedded JSON itself is somehow malformed (cannot happen
with the Python pipeline as designed but is possible if someone
hand-edits a Review_Page), `JSON.parse` throws synchronously. This
is caught by the Inline_Script bootstrap by not catching it — the
browser logs the exception to the console, the noscript fallback
(`<p class="js-required">...</p>`) stays visible because
`body.js-active` was never added, and the document is still
human-readable as an unrendered page.

## Testing Strategy

This spec's tests extend the existing parent-design test layout
(`tests/integration/test_review.py` and the `tests/integration/property/`
tree). Stdlib-only and `subprocess.run`-driven, per parent R18.

### Integration tests (`tests/integration/test_review.py`)

The existing test file continues to shell out to `scripts/review.py
song-review` via the `pinned_call` fixture and read the resulting
HTML file from `App_Root/output/review_<EPOCH>.html`. New
assertions:

- **JSON data block exists and parses.** Parse the Review_Page with
  `html.parser.HTMLParser`, pull the contents of the `<script
  id="due-data" type="application/json">` element, `json.loads` it,
  and assert the expected top-level keys (`generated_at`,
  `due_count`, `due_songs`) and shape per the schema above.
- **Inline_Script is inline.** Among the Review_Page's `<script>`
  elements, exactly one has `type="application/json"` and `id="due-data"`;
  the other has no `src` attribute and no `type="module"`.
- **No HTML tag literal in Python.** A new unit test
  (`tests/unit/test_review_source.py`) reads every `.py` file under
  `scripts/` and asserts that a code-only scan (stripping
  docstrings and comments via `tokenize`) contains none of the
  tag opening tokens listed in P-RH-0 / R-RH-1.2. This gives the
  zero-HTML-in-Python check a real home.
- **`</script>` in a song name escapes correctly.** The existing
  `test_html_injection_in_song_name_is_escaped` case is updated
  to the new escape form: assert that `</script>` does not appear
  verbatim in the Review_Page bytes (it should appear as
  `\u003c/script\u003e` inside the JSON data block), and that
  HTML-parsing the file yields exactly two `<script>` elements.

### Python-side DOM simulator

A small test helper (on the order of a few dozen lines) at
`tests/integration/_dom_sim.py` walks a Due_Data_Payload and
produces an ElementTree-like structure identical to what the
Inline_Script would build. Its algorithm is a 1:1 Python
translation of `renderList` / `renderSong` / `renderShowBlock` /
`renderAnchor` above — it is *not* a generic JS engine, and it is
*not* used at runtime. Tests that need to assert Rendered_DOM
properties (Properties 5, 6, 7, 8 below) run the simulator
against the same payload that `_build_payload` produced and
compare structures.

The simulator shares one helper with the Template_File spec:
`media_url_basename(url)` implemented in Python with the same
fallback rules. Small inline duplication; its correctness is
covered by its own unit test.

### Property tests (new, under `tests/integration/property/`)

One file per cluster:

| Property | File                                                                   | Generator                                    |
|----------|------------------------------------------------------------------------|----------------------------------------------|
| P-RH-0.1 | `test_no_html_in_python_property.py`                                   | `random.Random(seed)` choosing tags + casing |
| P-RH-1   | `test_basename_property.py`                                            | `random.Random(seed)` URL parts              |
| P-RH-2   | `test_group_by_show_property.py`                                       | seeded random songs + shows + URLs           |
| P-RH-3   | `test_copy_button_coverage_property.py`                                | seeded random songs + shows                  |
| P-RH-4   | `test_escape_injection_property.py`                                    | seeded random name fields with injection     |
| P-RH-5   | `test_package_exclusion_property.py`                                   | seeded random synthetic App_Root trees       |

All generators use stdlib `random.Random(seed)` with a fixed seed
per the parent R18 rule — no `hypothesis`. Each test runs
≥ 100 iterations (the property-test-style parent contract). Each
test is tagged with:

```python
# Feature: review-html-enhancements, Property N: <property text>
```

### Browser compatibility note

`navigator.clipboard.writeText` requires a browser "secure
context". On Chrome, Edge, and Firefox, `file://` origins qualify
and Copy_Buttons work when the Review_Page is opened locally from
`App_Root/output/review_<EPOCH>.html`. On Safari ≤ 13 and on some
older browsers the API is gated behind HTTPS and Copy_Buttons will
silently no-op via the R-RH-6.5 guard. This is acknowledged, not
constrained — the spec does not dictate the operator's browser.
Automated verification is done by the Python test harness against
the JSON payload and the Template_File's DOM structure, not by
running a browser.

## Files Touched During Implementation

The implementation of this design affects the following files.
Task breakdown lives in `tasks.md`.

- `scripts/review.py` — rewrite to the data-only pipeline described
  in **Python data pipeline**. Delete the `_HEADER`/`_FOOTER`
  strings and the `_render*` helpers; add `_build_payload`,
  `_escape_json_for_html`, `_render_page`, and the new
  `_cmd_song_review` body.
- `scripts/review_template.html` — **new file**. The Template_File
  described in **Template_File skeleton**, including the inline
  `<style>` block, the `<p class="js-required">` noscript fallback,
  the `<script id="due-data" type="application/json"><!-- DUE_DATA_JSON --></script>`
  marker element, and the Inline_Script.
- `tools/package.py` — add `SKILLS_DIR` and `_copy_skills`, wire
  `_copy_skills(staging)` into `main()`, update the module
  docstring and the `_SKIP_DIR_NAMES` comment per **Packaging
  edit**, append the `skills/` line to the summary `print()`.
- `tests/integration/test_review.py` — update the escape-injection
  assertion to the new escape form, add the JSON data-block
  parse-and-shape assertions, add the single-Inline_Script
  assertion.
- `tests/integration/_dom_sim.py` — **new file**. The Python-side
  DOM simulator.
- `tests/unit/test_review_source.py` — **new file**. Asserts no
  HTML tag literals appear in `scripts/*.py` code (P-RH-0.1).
- `tests/integration/property/test_no_html_in_python_property.py` —
  **new file**. P-RH-0.1 property test.
- `tests/integration/property/test_basename_property.py` —
  **new file**. P-RH-1 property test.
- `tests/integration/property/test_group_by_show_property.py` —
  **new file**. P-RH-2 property test.
- `tests/integration/property/test_copy_button_coverage_property.py` —
  **new file**. P-RH-3 property test.
- `tests/integration/property/test_escape_injection_property.py` —
  **new file**. P-RH-4 property test.
- `tests/integration/property/test_package_exclusion_property.py` —
  **new file**. P-RH-5 property test.
