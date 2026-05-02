"""Property P-RH-1 — short-name link round-trip.

For each random URL: seed a DB with one due song whose one show has
that URL, shell out to ``review.py song-review``, parse the
Rendered_DOM via the DOM simulator, and assert the single anchor
carries ``href == url`` and ``textContent == mediaUrlBasename(url)``.
"""

from __future__ import annotations

import json
import random
import sqlite3
from html.parser import HTMLParser

# Add repo root to import the simulator.
from tests.integration import _dom_sim
from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 101

_URL_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def _random_url(rng: random.Random) -> str:
    """Random http(s) URL with 1-5 path segments."""
    scheme = rng.choice(["http", "https"])
    host = "".join(rng.choice(_URL_CHARS) for _ in range(rng.randint(3, 10)))
    tld = rng.choice(["com", "net", "org"])
    n_segments = rng.randint(1, 5)
    segments = []
    for _ in range(n_segments):
        seg_len = rng.randint(1, 8)
        segments.append("".join(rng.choice(_URL_CHARS) for _ in range(seg_len)))
    path = "/".join(segments)
    return f"{scheme}://{host}.{tld}/{path}"


class _DataBlockFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._in = False
        self.text: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "due-data":
            self._in = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in = False

    def handle_data(self, data: str) -> None:
        if self._in:
            self.text += data


def _load_data_block(html_text: str) -> dict:
    parser = _DataBlockFinder()
    parser.feed(html_text)
    return json.loads(parser.text)


def _sqlite_now(db_file) -> int:
    conn = sqlite3.connect(str(db_file))
    try:
        return int(conn.execute("SELECT CAST(strftime('%s','now') AS INTEGER)").fetchone()[0])
    finally:
        conn.close()


def test_basename_round_trip(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """P-RH-1: for each random URL, the anchor href is full and text is the basename."""
    rng = random.Random(SEED)

    for i in range(ITERATIONS):
        # Fresh App_Root per iteration? No — tmp_app_root is per-test,
        # so accumulate. Using unique names per iteration so the due
        # query returns one fresh row each time. The test asserts
        # on the single most-recently-inserted URL by filtering the
        # payload.
        url = _random_url(rng)
        suffix = f"-iter-{i}"

        aid = insert_artist(tmp_app_root, name=f"A{suffix}")
        sid = insert_song(tmp_app_root, name=f"S{suffix}", artist_id=aid)
        shid = insert_show(tmp_app_root, name=f"Sh{suffix}")
        insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="")
        insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url=url)

        # Short-term learning row so this song is due right now.
        sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
        insert_learning(
            tmp_app_root,
            song_id=sid,
            level=0,
            last_level_up_at=sqlite_now - 400,
            updated_at=sqlite_now - 400,
        )

        rc, out, err = pinned_call(
            "review.py",
            "song-review",
            cwd=tmp_app_root,
            now=1_700_000_000 + i,
        )
        assert rc == 0, err
        out_parsed = json.loads(out)
        expected_path = tmp_app_root / "output" / f"review_{1_700_000_000 + i}.html"
        assert out_parsed["path"] == str(expected_path)

        payload = _load_data_block(expected_path.read_text("utf-8"))

        # Find this iteration's song in the payload.
        song_rows = [s for s in payload["due_songs"] if s["song_id"] == sid]
        assert len(song_rows) == 1, f"iter {i}: song not found in payload"
        song = song_rows[0]
        assert len(song["shows"]) == 1
        show = song["shows"][0]
        assert show["media_urls"] == [url]

        # Run the simulator and pull out the anchor for this URL.
        tree = _dom_sim.render(payload)
        anchors = [a for a in _dom_sim.find_anchors(tree) if a.attrib.get("href") == url]
        assert len(anchors) == 1, f"iter {i}: expected 1 anchor for url, got {len(anchors)}"
        anchor = anchors[0]
        expected_text = _dom_sim.media_url_basename(url)
        assert anchor.text == expected_text, (
            f"iter {i}: url={url!r} got text={anchor.text!r} expected={expected_text!r}"
        )
