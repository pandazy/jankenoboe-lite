"""Integration tests for ``scripts/review.py``.

Covers R8 end-to-end, now under the new template-based rendering
model from the ``review-html-enhancements`` spec: ``review.py`` is a
data-only pipeline that substitutes one JSON payload into the static
``scripts/review_template.html``. The tests here assert against the
JSON data block (for fields the Inline_Script would render from) and
against the raw HTML (for static template bytes like DOCTYPE and
``<script>`` tag counts). Structural claims about the Rendered_DOM
— `<li>` / `<a>` / `<button>` shape — live in the property tests
that drive the Python-side DOM simulator.

Uses the same SQLite-clock-anchor pattern as ``test_due.py`` because
review.py's due query runs inside SQLite. On top of that, review.py
names its output file with ``now_epoch()`` in the filename, so tests
also pin ``JANKENOBOE_TEST_NOW`` through ``pinned_call`` when they
need to assert an exact path.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
from html.parser import HTMLParser
from typing import Any

# ---------------------------------------------------------------------------
# Helpers: data-block parse, script-tag enumeration, break-the-symlink setup.
# ---------------------------------------------------------------------------


class _ScriptCollector(HTMLParser):
    """Walk the Review_Page, collecting (attrs, text) pairs for <script> tags.

    Built for tests that need to assert on the exact set of scripts in
    the document (there should be exactly two: the data block and the
    Inline_Script).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        # Public output — list of (attrs_dict, inner_text) tuples, in
        # document order.
        self.scripts: list[tuple[dict[str, str], str]] = []
        # Per-element scratch.
        self._in_script = False
        self._attrs: dict[str, str] = {}
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._in_script = True
            self._attrs = {k: (v or "") for k, v in attrs}
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_script:
            self.scripts.append((self._attrs, "".join(self._buf)))
            self._in_script = False
            self._attrs = {}
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._buf.append(data)


def _parse_scripts(html_text: str) -> list[tuple[dict[str, str], str]]:
    """Return a list of (attrs, inner_text) for every ``<script>`` tag."""
    parser = _ScriptCollector()
    parser.feed(html_text)
    return parser.scripts


def _load_data_block(html_text: str) -> dict[str, Any]:
    """Extract and JSON-parse the ``<script id="due-data">`` element."""
    for attrs, text in _parse_scripts(html_text):
        if attrs.get("id") == "due-data":
            return json.loads(text)
    raise AssertionError("no <script id='due-data'> element found")


def _materialise_scripts_dir(app_root: pathlib.Path) -> pathlib.Path:
    """Replace the ``scripts/`` symlink with a real copy for mutation.

    The default ``tmp_app_root`` fixture symlinks ``scripts/`` into the
    real repo. Tests in this module that need to mutate template files
    for the INTERNAL_ERROR paths must first break that symlink so they
    don't touch the real repo.
    """
    scripts_link = app_root / "scripts"
    real_scripts = scripts_link.resolve()
    scripts_link.unlink()
    shutil.copytree(real_scripts, scripts_link)
    return scripts_link


# ---------------------------------------------------------------------------
# Helpers: SQLite clock, pinned-call wrapper.
# ---------------------------------------------------------------------------


def _sqlite_now(db_file) -> int:
    conn = sqlite3.connect(str(db_file))
    try:
        return int(conn.execute("SELECT CAST(strftime('%s','now') AS INTEGER)").fetchone()[0])
    finally:
        conn.close()


def _run_review_pinned(pinned_call, cwd, now: int) -> tuple[int, Any, Any, pathlib.Path]:
    """Run ``review.py song-review`` with the clock pinned to ``now``.

    Returns ``(rc, stdout_json, stderr_json, expected_path)``. The expected
    path is ``cwd/output/review_<now>.html`` — tests assert against this.
    """
    rc, out, err = pinned_call("review.py", "song-review", cwd=cwd, now=now)
    out_parsed: Any = None
    err_parsed: Any = None
    if out.strip():
        try:
            out_parsed = json.loads(out)
        except json.JSONDecodeError:
            out_parsed = None
    if err.strip():
        try:
            err_parsed = json.loads(err)
        except json.JSONDecodeError:
            err_parsed = None
    expected = cwd / "output" / f"review_{now}.html"
    return rc, out_parsed, err_parsed, expected


# ---------------------------------------------------------------------------
# Output path + envelope shape
# ---------------------------------------------------------------------------


def test_writes_to_timestamped_path_under_output(tmp_app_root, pinned_call) -> None:
    """R8.7: HTML lands at ``App_Root/output/review_<epoch>.html``.

    No due rows — this is the "empty" path; file still gets written.
    """
    pinned = 1_700_000_000
    rc, out, err, expected = _run_review_pinned(pinned_call, tmp_app_root, pinned)
    assert rc == 0, err
    assert expected.exists()
    assert out["path"] == str(expected)
    assert out["due_count"] == 0


def test_output_directory_created_when_missing(tmp_app_root, pinned_call) -> None:
    """R8.7: review.py creates ``App_Root/output/`` on demand."""
    assert not (tmp_app_root / "output").exists()
    rc, _out, _err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0
    assert (tmp_app_root / "output").is_dir()
    assert expected.exists()


def test_review_script_does_not_write_elsewhere(tmp_app_root, pinned_call) -> None:
    """Sanity: no stray files under App_Root besides the timestamped HTML."""
    rc, _out, _err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0
    created = {p.relative_to(tmp_app_root) for p in tmp_app_root.rglob("*")}
    # No stray review.html or review_*.html at the repo root.
    assert pathlib.Path("review.html") not in created
    # The timestamped file is under output/.
    assert expected.relative_to(tmp_app_root) in created


def test_two_runs_at_different_times_produce_two_files(tmp_app_root, pinned_call) -> None:
    """R8.7: previous review files are left in place.

    Running twice at different pinned epochs should leave both HTML
    files sitting side-by-side under ``output/``.
    """
    first_epoch = 1_700_000_000
    second_epoch = 1_700_003_600

    rc, _out, _err, first = _run_review_pinned(pinned_call, tmp_app_root, first_epoch)
    assert rc == 0
    rc, _out, _err, second = _run_review_pinned(pinned_call, tmp_app_root, second_epoch)
    assert rc == 0

    assert first.exists()
    assert second.exists()
    assert first != second
    files = sorted((tmp_app_root / "output").iterdir())
    assert [p.name for p in files] == [first.name, second.name]


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


def test_no_due_rows_still_writes_valid_html(tmp_app_root, pinned_call) -> None:
    """R8.6 + R-RH-1.3: empty queue writes a valid HTML file with due_count=0."""
    rc, out, _err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0
    assert out["due_count"] == 0
    html_text = expected.read_text("utf-8")
    # Static chrome is present.
    assert "<!DOCTYPE html>" in html_text
    # The "No songs due." message lives in the Template_File's empty-state
    # rendering path; the Inline_Script outputs it at runtime. As a static
    # text check we assert the template's static empty-state string
    # (which the Inline_Script reads) appears somewhere.
    assert "No songs due." in html_text
    # The data block has the right empty shape.
    payload = _load_data_block(html_text)
    assert payload["due_count"] == 0
    assert payload["due_songs"] == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_renders_due_song(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """R-RH-1.3, R-RH-1.4, R-RH-3.5: one due row lands in the data block.

    The due query uses SQLite's ``strftime('%s','now')`` (not the pinned
    clock), so we seed timestamps relative to SQLite's "now" and pin only
    the filename through pinned_call.
    """
    aid = insert_artist(tmp_app_root, name="Yui", name_context="solo")
    sid = insert_song(tmp_app_root, name="Again", artist_id=aid)
    shid = insert_show(tmp_app_root, name="FMA: Brotherhood", vintage="Spring 2009", s_type="TV")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="http://rel/u")
    insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url="http://ph/a")
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=sqlite_now - 400,  # past the 300s threshold → due
        updated_at=sqlite_now - 400,
    )

    rc, out, err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0, err
    assert out["due_count"] == 1

    payload = _load_data_block(expected.read_text("utf-8"))
    assert payload["due_count"] == 1
    assert len(payload["due_songs"]) == 1

    song = payload["due_songs"][0]
    assert song["song_id"] == sid
    assert song["song_name"] == "Again"
    assert song["artist_id"] == aid
    assert song["artist_name"] == "Yui"
    assert song["artist_name_context"] == "solo"
    assert song["display_level"] == 1  # stored 0 → displayed 1

    assert len(song["shows"]) == 1
    show = song["shows"][0]
    assert show["show_id"] == shid
    assert show["show_name"] == "FMA: Brotherhood"
    assert show["show_vintage"] == "Spring 2009"
    assert show["show_s_type"] == "TV"
    # Both play_history and rel_show_song urls appear (R8.5 — union).
    assert set(show["media_urls"]) == {"http://ph/a", "http://rel/u"}


def test_renders_display_level_not_stored_level(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R17.2: ``display_level`` is stored level + 1, carried in the payload."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    # level = 2 → display 3.
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=2,
        last_level_up_at=sqlite_now - 365 * 86400,
        updated_at=sqlite_now - 365 * 86400,
    )

    rc, out, _err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0
    assert out["due_count"] == 1

    payload = _load_data_block(expected.read_text("utf-8"))
    assert payload["due_songs"][0]["display_level"] == 3


# ---------------------------------------------------------------------------
# HTML escape and JSON-in-HTML safety (R-RH-6.4, R-RH-6.6)
# ---------------------------------------------------------------------------


def test_html_injection_in_song_name_is_escaped(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R-RH-6.6: ``</script>`` in a string field cannot break out of the data block.

    The payload JSON ends up inside ``<script type="application/json">``.
    The Python pipeline escapes ``<`` to ``\\u003c`` so no literal
    ``</script>`` ever appears inside that element. HTML-parsing the
    document yields exactly two ``<script>`` elements (the data block
    and the Inline_Script), not three.
    """
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(
        tmp_app_root,
        name="<script>alert(1)</script>",
        artist_id=aid,
    )
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=sqlite_now - 10_000,
        updated_at=sqlite_now - 10_000,
    )

    rc, _out, err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0, err
    text = expected.read_text("utf-8")

    # The literal </script> MUST NOT appear verbatim anywhere in the page.
    # If it did, the first <script> element would be closed early and the
    # rest parsed as markup.
    assert "</script>alert(1)</script>" not in text
    # The escape form is present inside the data block region.
    assert "\\u003c/script\\u003e" in text
    # Exactly two <script> elements: the data block and the Inline_Script.
    scripts = _parse_scripts(text)
    assert len(scripts) == 2
    data_attrs, _data_text = scripts[0]
    assert data_attrs.get("id") == "due-data"
    assert data_attrs.get("type") == "application/json"
    inline_attrs, _inline_text = scripts[1]
    assert "src" not in inline_attrs
    assert inline_attrs.get("type", "") != "module"

    # The payload round-trips the hostile string byte-for-byte.
    payload = _load_data_block(text)
    assert payload["due_songs"][0]["song_name"] == "<script>alert(1)</script>"


def test_media_url_quotes_are_escaped(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_show,
    insert_play_history,
    insert_learning,
    insert_rel,
) -> None:
    """A ``"`` in a media_url rides through JSON escape, not HTML escape.

    In the new pipeline nothing escapes via ``html.escape``. The url is
    a string value inside the JSON payload, so its literal ``"`` is
    escaped as ``\\"`` by ``json.dumps``. The Inline_Script then writes
    it via ``setAttribute`` / ``textContent``, which the browser quotes
    on its own.
    """
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Show")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid)
    insert_play_history(
        tmp_app_root,
        show_id=shid,
        song_id=sid,
        media_url='http://evil"/inject',
    )
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=sqlite_now - 10_000,
        updated_at=sqlite_now - 10_000,
    )

    rc, _out, err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0, err
    text = expected.read_text("utf-8")

    # The payload round-trips the url byte-for-byte.
    payload = _load_data_block(text)
    urls = payload["due_songs"][0]["shows"][0]["media_urls"]
    assert 'http://evil"/inject' in urls

    # The JSON-escaped form appears in the raw bytes inside the data block.
    # (Python's json.dumps writes the \" escape; we only care that the
    # raw " isn't a bare character in the data block region.)
    assert '\\"' in text


# ---------------------------------------------------------------------------
# Filter rules that matter for review.py
# ---------------------------------------------------------------------------


def test_soft_deleted_song_does_not_appear(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R7.5 / R8.1: soft-deleted songs never land in the review page."""
    aid = insert_artist(tmp_app_root, name="A")
    dead = insert_song(tmp_app_root, name="Hidden", artist_id=aid, status=1)
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=dead,
        level=0,
        last_level_up_at=sqlite_now - 10_000,
        updated_at=sqlite_now - 10_000,
    )
    rc, out, _err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0
    assert out["due_count"] == 0
    payload = _load_data_block(expected.read_text("utf-8"))
    assert payload["due_songs"] == []
    # Negative-space check: "Hidden" does not appear in any payload song_name.
    assert not any(s.get("song_name") == "Hidden" for s in payload["due_songs"])


def test_graduated_row_does_not_appear(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="Done", artist_id=aid)
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        graduated=1,
        last_level_up_at=sqlite_now - 10_000_000,
        updated_at=sqlite_now - 10_000_000,
    )
    rc, out, _err, _expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0
    assert out["due_count"] == 0


def test_soft_deleted_show_not_listed(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """R8.1: the shows array only includes live shows (per-show data-block check)."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="Track", artist_id=aid)
    dead_show = insert_show(tmp_app_root, name="Old Hidden Show", status=1)
    live_show = insert_show(tmp_app_root, name="Visible Show")
    insert_rel(tmp_app_root, show_id=dead_show, song_id=sid)
    insert_rel(tmp_app_root, show_id=live_show, song_id=sid)
    insert_play_history(tmp_app_root, show_id=dead_show, song_id=sid, media_url="http://hidden")
    insert_play_history(tmp_app_root, show_id=live_show, song_id=sid, media_url="http://visible")
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=sqlite_now - 10_000,
        updated_at=sqlite_now - 10_000,
    )
    rc, _out, _err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0
    payload = _load_data_block(expected.read_text("utf-8"))
    show_names = [sh["show_name"] for s in payload["due_songs"] for sh in s["shows"]]
    assert "Visible Show" in show_names
    assert "Old Hidden Show" not in show_names


# ---------------------------------------------------------------------------
# INTERNAL_ERROR paths (R-RH-1.8)
# ---------------------------------------------------------------------------


def test_missing_template_raises_internal_error(tmp_app_root, pinned_call) -> None:
    """R-RH-1.8: missing template file → INTERNAL_ERROR, no output written."""
    scripts_dir = _materialise_scripts_dir(tmp_app_root)
    (scripts_dir / "review_template.html").unlink()

    rc, out, err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 1
    assert out is None or out == {}
    assert err["error"]["code"] == "INTERNAL_ERROR"
    assert "template" in err["error"]["message"].lower()
    assert not expected.exists()
    # output/ may or may not exist (mkdir happens before the template read);
    # what matters is no review file landed.
    if (tmp_app_root / "output").exists():
        assert list((tmp_app_root / "output").iterdir()) == []


def test_missing_marker_raises_internal_error(tmp_app_root, pinned_call) -> None:
    """R-RH-1.8: template without the marker → INTERNAL_ERROR."""
    scripts_dir = _materialise_scripts_dir(tmp_app_root)
    # Write a stub template that lacks the substitution marker.
    (scripts_dir / "review_template.html").write_text(
        "<!DOCTYPE html><html><body>no marker here</body></html>",
        encoding="utf-8",
    )

    rc, out, err, expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 1
    assert out is None or out == {}
    assert err["error"]["code"] == "INTERNAL_ERROR"
    assert "marker" in err["error"]["message"].lower()
    assert not expected.exists()


# ---------------------------------------------------------------------------
# Bare `--help` / no-args behavior (R2.4)
# ---------------------------------------------------------------------------


def test_no_args_prints_help_and_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, err = call_script("review.py", cwd=tmp_app_root)
    assert rc == 0
    combined = (out + err).lower()
    assert "usage" in combined or "review.py" in combined


def test_help_flag_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, _err = call_script("review.py", "--help", cwd=tmp_app_root)
    assert rc == 0
    assert "usage" in out.lower()


# ---------------------------------------------------------------------------
# review.py does not write to the DB
# ---------------------------------------------------------------------------


def test_review_does_not_modify_db(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=sqlite_now - 10_000,
        updated_at=sqlite_now - 10_000,
    )
    db = tmp_app_root / "db" / "datasource.db"
    before = db.read_bytes()
    rc, _out, err, _expected = _run_review_pinned(pinned_call, tmp_app_root, 1_700_000_000)
    assert rc == 0, err
    after = db.read_bytes()
    assert before == after
