# Implementation Plan

This task list translates `design.md` and `requirements.md` into an
executable plan for adding the `--inline` flag to
`scripts/review.py song-review`. The flag opts the caller into
Inline_Mode — the rendered Review_Page is minified and embedded
directly in the Success_Envelope under a new `html` key, and no
file is written to `App_Root/output/`.

The ordering is "smallest-safe-slice-first": the helper lands
first (it's a pure function, easy to test in isolation), then the
argparse + branch wiring, then the regression tests, then the
final `make check` gate, then the release-note bullet.

**Framing invariants** (copied from the spec — these are the hard
boundaries for the release):

- **R-Additive is the hard boundary.** The only production file
  modified is `scripts/review.py`. The template,
  `scripts/_common.py`, every other script under `scripts/`, and
  `tests/integration/_dom_sim.py` stay byte-identical to v0.1.4.
- **Diff is exactly three files**: `scripts/review.py` (the
  `--inline` flag, the `_minify_chrome` helper plus its three
  compiled regexes, and the Inline_Mode branch in
  `_cmd_song_review`); `tests/integration/test_review.py` (five
  new test functions added — no existing test edited);
  `release.md` (one bullet under v0.1.5).
- **Disk_Mode is byte-identical to v0.1.4.** The `if args.inline`
  branch lands in front of the existing Disk_Mode code; the
  Disk_Mode body itself does not change.
- **PBT iteration count stays pinned** at `ITERATIONS = 5` in
  `tests/integration/property/_helpers.py` — no property-test
  changes at all in this release.
- **Coverage floor ≥ 90%** (enforced by `./tests/run.sh` via
  `.coveragerc`).
- **No git commit / tag / push** from this task file — the user
  handles those.
- Ships as **v0.1.5** via the existing release pipeline.

**Out of scope, do not touch**:

- `scripts/review_template.html` — the template is shape-stable
  by R-Additive 5.1.
- `scripts/_common.py` — Inline_Mode reuses the existing
  `success(...)` helper without modification (R-Additive 5.2).
- `scripts/learning.py`, `scripts/import_plan.py`,
  `scripts/init_db.py`, every other script under `scripts/` — all
  byte-identical to v0.1.4 (R-Additive 5.3).
- `tests/integration/_dom_sim.py` — the simulator handles the
  minified HTML unchanged because the parsed DOM is the same as
  the un-minified DOM (R-Additive 5.4).
- Every existing test in `tests/integration/test_review.py` — this
  release only ADDs five new test functions; it does NOT edit any
  existing test (R-Additive 5.5, R-Test-Inline 6.6).
- Every property test under `tests/integration/property/` —
  byte-identical (R-Additive 5.6).
- `Makefile`, `.coveragerc`, `pyproject.toml`, CI / release
  config.

## `scripts/review.py` edits

All production code changes land in `scripts/review.py` in three
coherent sub-tasks. The minify helper goes first (it's a pure
function), then the argparse flag, then the call-site branch.
Each sub-task is independent and testable; they all land together
in one commit.

- [ ] 1. Add the `_minify_chrome` helper and its three module-level compiled regexes to `scripts/review.py`
  - Parent task. Adds the pure-function helper that minifies HTML
    chrome regions while leaving `<script>` and `<style>` bodies
    byte-identical. The helper lives next to `_escape_json_for_html`
    in the "Payload + render pipeline" section of `scripts/review.py`.
  - **File touched**: `scripts/review.py` only.
  - Reference: `design.md` > "Low-Level Design" > "The
    `_minify_chrome` helper (full body)" for the exact regex
    bodies and helper shape.

  - [ ] 1.1 Add the three module-level compiled regexes
    - Add `import re` at the top of `scripts/review.py` if not
      already imported.
    - Define `_PASSTHROUGH_RE`, `_HTML_COMMENT_RE`,
      `_WHITESPACE_RUN_RE`, and `_INTER_TAG_WS_RE` at module
      scope so they compile once at import time, not on every
      render. Use the exact byte patterns and flags from
      `design.md` > "Low-Level Design".
    - Place the regex definitions immediately above the new
      `_minify_chrome` function.
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 1.2 Add the `_minify_chrome(html_bytes: bytes) -> bytes` helper body
    - Use the exact body from `design.md` > "Low-Level Design" >
      "The `_minify_chrome` helper (full body)".
    - The helper MUST split the input via `_PASSTHROUGH_RE.split`,
      iterate the resulting alternating segments (even index =
      Chrome_Region, odd index = passthrough), apply the three
      Chrome_Region rewrites in order (comments, then whitespace
      runs, then inter-tag whitespace), pass through the
      passthrough segments byte-identically, and return
      `b"".join(out)`.
    - The order of Chrome_Region rewrites MUST be:
      1. `_HTML_COMMENT_RE.sub(b"", seg)` first (so subsequent
         passes do not see `<` / `>` characters from inside
         comments).
      2. `_WHITESPACE_RUN_RE.sub(b" ", seg)` second (collapse
         every run of 2+ whitespace bytes to a single space).
      3. `_INTER_TAG_WS_RE.sub(b"><", seg)` third (drop the
         single inter-tag space the previous step left behind).
    - The helper is a pure function: no I/O, no side effects, no
      access to module-level state besides the four regexes.
    - Add a concise docstring matching `design.md` > "Low-Level
      Design" — bytes-in-bytes-out, the contract that
      `<script>` and `<style>` bodies pass through unchanged,
      idempotence, and one or two short example invocations.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.3_

- [ ] 2. Add the `--inline` flag to the `song-review` subparser in `_build_parser`
  - **File touched**: `scripts/review.py` only.
  - In `_build_parser`, after the existing `--offset` argument,
    add a `sr.add_argument("--inline", action="store_true", ...)`
    call with the help text from `design.md` > "Low-Level Design"
    > "The new CLI surface (argparse diff)".
  - The flag MUST default to `False` (the `store_true` default).
    No short form (`-i`) is added.
  - The subparser's main `help=` line is unchanged — it still
    describes the default Disk_Mode output path, which is
    correct because that runs when no flag is given.
  - _Requirements: 1.1, 1.2_

- [ ] 3. Add the Inline_Mode branch in `_cmd_song_review`
  - **File touched**: `scripts/review.py` only.
  - After the existing `rendered = _render_page(payload, template_bytes)`
    line, AND BEFORE the existing `app_root = _common.app_root(__file__)`
    line, insert the Inline_Mode branch verbatim per `design.md`
    > "Low-Level Design" > "The `_cmd_song_review` branch":
    ```python
    if args.inline:
        minified = _minify_chrome(rendered)
        _common.success(
            {
                "html": minified.decode("utf-8"),
                "due_count": payload["due_count"],
                "offset": int(args.offset),
            }
        )
        return
    ```
  - The Disk_Mode code path AFTER this branch (the `mkdir`, the
    `target.write_bytes(rendered)`, the second
    `_common.success({"path": ..., ...})` call) MUST be
    byte-identical to v0.1.4 — do not reformat, rename, or
    re-order the existing lines.
  - The trailing `return` after the Inline_Mode `_common.success`
    call is defensive only — `_common.success` calls
    `sys.exit(0)` and never returns — but it makes the
    Disk_Mode-only fallthrough explicit to readers.
  - The `_common.success(...)` call dict literal MUST list its
    keys in this exact order: `html`, `due_count`, `offset`. The
    Disk_Mode dict literal already lists `path`, `due_count`,
    `offset` in that order; the parallel structure is intentional
    so a future reader can grep both call sites and see the
    contract directly.
  - The Inline_Mode branch MUST NOT call
    `output_dir.mkdir(...)` or otherwise create
    `App_Root/output/` — directory creation lives entirely inside
    the Disk_Mode branch (R-Inline-Flag 1.6).
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 4.1, 4.2, 4.3, 4.4, 5.7_

## Bytes-in-test regression suite

- [ ] 4. Add five new test functions to `tests/integration/test_review.py`
  - Add exactly FIVE new test functions. Do NOT edit any existing
    test in the file (R-Additive 5.5, R-Test-Inline 6.6).
  - **File touched**: `tests/integration/test_review.py` only
    (ADD, no edits to existing tests).
  - The five tests follow the existing file's style — re-use
    `subprocess.run` invocation helpers, the `tmp_app_root`
    fixture, JSON-parse stdout, parse the rendered HTML via
    `tests/integration/_dom_sim.py`. Sketches for each in
    `design.md` > "Low-Level Design" > "The new tests (full
    bodies sketched)".
  - Reference: `design.md` > "Testing Strategy" > "New tests
    added" for the test list and what each one gates.

  - [ ] 4.1 Add `test_song_review_inline_envelope_shape`
    - Seed at least one due song. Run
      `scripts/review.py song-review --inline`. Assert:
      - `result.returncode == 0`.
      - `set(envelope.keys()) == {"html", "due_count", "offset"}`.
      - `"path" not in envelope`.
      - `envelope["due_count"] >= 1`.
      - `envelope["offset"] == 0`.
      - The parsed DOM (via `_dom_sim`) has exactly
        `envelope["due_count"]` `<li data-level>` elements.
      - The parsed DOM has exactly one
        `<script id="due-data">` payload block.
    - _Requirements: 1.3, 1.5, 4.1, 4.2, 4.3, 6.1_

  - [ ] 4.2 Add `test_song_review_inline_empty_state`
    - Use a fixture that yields an empty-due DB (no due songs —
      either no `learning` rows, or all rows soft-deleted /
      graduated). Run
      `scripts/review.py song-review --inline`. Assert:
      - `set(envelope.keys()) == {"html", "due_count", "offset"}`.
      - `envelope["due_count"] == 0`.
      - The parsed DOM has zero `<li data-level>` elements.
      - The parsed DOM still contains the empty-state markup
        (re-use whatever assertion the existing
        `test_song_review_empty_state` test uses against the
        Disk_Mode output, against the inline `html` field
        instead).
    - _Requirements: 1.4, 6.2_

  - [ ] 4.3 Add `test_song_review_inline_writes_no_file`
    - Pre-condition: `output_dir = tmp_app_root / "output"` does
      not exist (or exists but is empty). Assert this
      pre-condition.
    - Run `scripts/review.py song-review --inline`. Assert
      `result.returncode == 0`.
    - Post-condition: assert `output_dir` does not exist OR
      contains zero files. Use
      `assert not output_dir.exists() or not list(output_dir.iterdir())`.
    - _Requirements: 1.6, 6.3_

  - [ ] 4.4 Add `test_minify_chrome_skips_script_and_style_and_is_idempotent`
    - Direct unit test — imports `_minify_chrome` from
      `scripts.review`. No subprocess, no DB, no `tmp_app_root`
      fixture.
    - Use the sample input from `design.md` > "Low-Level Design"
      > "The new tests (full bodies sketched)" verbatim, or an
      equivalent input that exercises:
      - inter-tag whitespace runs in chrome (`>  <`),
      - an HTML comment in chrome (`<!-- a comment -->`),
      - a `<style>` body whose internal whitespace MUST survive,
      - a `<script>` body whose internal whitespace MUST survive
        (the JSON payload's `\n  ` between fields is the
        canonical example).
    - Assert all five sub-properties:
      1. The exact byte sequence of the script body is `in` the
         output (whitespace and all).
      2. The exact byte sequence of the style body is `in` the
         output.
      3. `b">  <" not in out` AND `b"> <" not in out` (inter-tag
         whitespace in chrome was collapsed to nothing).
      4. `b"<!--" not in out` AND `b"a comment" not in out` (the
         HTML comment was stripped).
      5. `_minify_chrome(out) == out` (idempotence).
    - _Requirements: 2.1, 2.2, 2.3, 2.6, 3.3, 6.4_

  - [ ] 4.5 Add `test_song_review_inline_preserves_escape_gate`
    - Seed a song with `song_name` set to the literal string
      `"</script><script>alert(1)</script>"` (re-use the same
      seeding pattern the existing
      `test_song_review_html_injection_escape` test uses, just
      with the `--inline` flag on the subprocess invocation).
    - Run `scripts/review.py song-review --inline`. Parse the
      envelope. Parse `envelope["html"]` via `_dom_sim`. Assert:
      - The parsed DOM has exactly two `<script>` elements (the
        `<script id="due-data">` payload block and the
        Inline_Script).
      - The payload block's textContent JSON-parses to a dict
        whose `due_songs` list contains an entry with
        `song_name == "</script><script>alert(1)</script>"`
        (byte-for-byte round trip).
    - _Requirements: 3.1, 3.2, 6.5_

## Verification — existing suite stays green

- [ ] 5. Verify the new tests pass and the existing suite stays byte-identically green
  - Run `pytest tests/integration/test_review.py -k "inline or minify"`
    — expect all five new tests PASS after Tasks 1, 2, 3, and 4
    land.
  - Run `pytest tests/integration/test_review.py` — expect every
    pre-existing test (empty state, happy path, display level,
    HTML escape, filter rules, output path, INTERNAL_ERROR
    paths, no-write-to-DB, `--offset` parity, envelope key-set)
    to continue passing byte-identically. None of those tests
    were edited.
  - Run `pytest tests/integration/property/test_escape_injection_property.py`
    — expect continued PASS. The property test runs against
    Disk_Mode (it does not pass `--inline`) and the Disk_Mode
    code path is byte-identical to v0.1.4.
  - Run `pytest tests/integration/property/test_due_property.py`
    — expect continued PASS.
  - Run `pytest tests/integration/test_due.py` — expect continued
    PASS. The `learning.py due` surface and its property
    coverage are untouched.
  - If any existing test fails, diagnose the root cause before
    proceeding — a regression in a pre-existing test is a
    fix-regression signal, not something to patch by editing the
    test.
  - _Requirements: 3.1, 3.2, 5.5, 5.6, 5.7_

## Final gate — `make check`, coverage ≥ 90%, manual smoke

- [ ] 6. Final gate — run `make check`, confirm coverage ≥ 90%, walk the manual smoke checklist
  - Run `make check` (lint + typecheck + test). Expect all three
    to pass. The Python-file delta is exactly +5 new test
    functions in `tests/integration/test_review.py` and the
    additions to `scripts/review.py` (one new helper, one
    argparse line, one branch). Ruff and mypy should be clean.
  - Confirm coverage stays ≥ 90% — `./tests/run.sh` enforces
    this automatically via `.coveragerc`. The new helper has
    direct unit coverage (Task 4.4) and end-to-end coverage via
    Tasks 4.1, 4.2, 4.3, 4.5; the new argparse flag is
    exercised by every Inline_Mode test. The Disk_Mode branch is
    unchanged and remains covered by the v0.1.4 tests.
  - Verify the Python-file delta by running
    `git -P diff --stat` — expect exactly two files changed
    under `scripts/` and `tests/` (`scripts/review.py` and
    `tests/integration/test_review.py`), ignoring `release.md`
    and `.kiro/specs/` additions.
  - Walk the manual smoke checklist from `design.md` > "Testing
    Strategy" > "Manual smoke checklist":
    1. Run `scripts/review.py song-review --inline | jq -r .html
       > /tmp/page.html` against a populated DB.
    2. Open `/tmp/page.html` in a browser. Confirm the page
       renders identically to a Disk_Mode-generated
       `review_<EPOCH>.html` (same cards, same globe icons,
       same shows).
    3. `wc -c < /tmp/page.html` is strictly less than `wc -c <
       output/review_<EPOCH>.html` for the most recent
       Disk_Mode generation against the same DB state.
    4. `App_Root/output/` did NOT gain a new file from the
       `--inline` invocation.
    5. `scripts/review.py song-review --help` lists `--inline`
       alongside `--offset`.
  - If any checklist step fails, diagnose the root cause before
    proceeding; ask the user if questions arise.
  - _Requirements: 1.1, 1.2, 1.3, 1.6, 2.5, 4.1, 4.2_

## Release note

- [ ] 7. Update `release.md` for v0.1.5 with the inline-HTML-response bullet
  - **File touched**: `release.md` only.
  - Bump the header from `## jankenoboe-lite v0.1.4` to
    `## jankenoboe-lite v0.1.5`.
  - Rewrite the preamble sentence to reflect v0.1.5's scope: one
    additive CLI surface change to `review.py song-review` (the
    new `--inline` flag) and the corresponding minified HTML
    response, no breaking changes, no schema migration, no
    template change.
  - Replace the v0.1.4 Highlight bullet with one new bullet
    describing v0.1.5:
    - **`song-review --inline` returns the rendered HTML in the
      envelope.** Describe that `scripts/review.py song-review`
      now accepts an opt-in `--inline` flag. With the flag, the
      Success_Envelope on stdout carries the rendered Review_Page
      directly under a new `html` field (key set
      `{"html", "due_count", "offset"}`) and no file is written
      to `App_Root/output/`. The HTML is minified in the
      standard web-frontend sense — inter-tag whitespace
      collapsed, HTML comments stripped — but `<script>` and
      `<style>` bodies pass through byte-identically so the
      Escape_Gate is preserved unchanged. Note the default
      (no-flag) Disk_Mode behavior is byte-identical to v0.1.4
      — same file path scheme, same envelope key set
      `{"path", "due_count", "offset"}`, same exit code.
  - Update the "Verified on this build" block to reflect the new
    test count (v0.1.4 shipped with 481 passing; this release
    adds five new tests, so the post-release count is 486) and
    re-confirm 95% line coverage (or whatever the current floor
    is — verify after Task 6).
  - Leave the `Install` and `Use it` sections byte-identical
    apart from one new sub-bullet under the `song-review` usage
    showing how to read the inline HTML:
    `python scripts/review.py song-review --inline | jq -r .html > page.html`.
  - _References: all Stories 1 – 6 in `requirements.md`; no
    individual acceptance criterion drives this release-note
    edit._
