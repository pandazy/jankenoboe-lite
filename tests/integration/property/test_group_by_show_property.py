"""Property P-RH-2 — group-by-show partition.

For a random number of shows linked to one due song, with a random
per-(show, song) mix of play_history and rel_show_song media URLs:
each rendered Show_Block carries exactly the URLs of its own
(show, song) pair, every URL rendered in the tree appears in exactly
one Show_Block, and a Show_Block with zero URLs still renders
(carrying the show's name) with no ``<ul class="links">`` child.
"""

from __future__ import annotations

import json
import random
import sqlite3
from html.parser import HTMLParser

from tests.integration import _dom_sim
from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 102


class _DataBlockFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._in = False
        self.text: str = ""

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "due-data":
            self._in = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = False

    def handle_data(self, data):
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


def _rand_url(rng: random.Random, tag: str) -> str:
    return f"http://example.com/{tag}/{rng.randint(1, 1_000_000)}.mp4"


def test_group_by_show_partition(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    rng = random.Random(SEED)

    for i in range(ITERATIONS):
        # One new song per iteration.
        aid = insert_artist(tmp_app_root, name=f"A{i}")
        sid = insert_song(tmp_app_root, name=f"Song{i}", artist_id=aid)
        n_shows = rng.randint(1, 5)

        # For each show, decide a random set of URLs (possibly empty).
        # Some URLs come from play_history, some from rel_show_song.
        expected_urls_by_show: dict[str, set[str]] = {}

        for j in range(n_shows):
            # Deterministic name so sort order is predictable.
            shid = insert_show(tmp_app_root, name=f"Sh{i:04d}-{j:02d}")
            show_urls: set[str] = set()

            # rel_show_song may carry one URL (or empty).
            rel_url = ""
            if rng.random() < 0.5:
                rel_url = _rand_url(rng, f"rel-{i}-{j}")
                show_urls.add(rel_url)
            insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url=rel_url)

            # play_history: zero to three rows.
            n_ph = rng.randint(0, 3)
            for k in range(n_ph):
                ph_url = _rand_url(rng, f"ph-{i}-{j}-{k}")
                insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url=ph_url)
                show_urls.add(ph_url)

            expected_urls_by_show[shid] = show_urls

        # Make the song due.
        sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
        insert_learning(
            tmp_app_root,
            song_id=sid,
            level=0,
            last_level_up_at=sqlite_now - 400,
            updated_at=sqlite_now - 400,
        )

        # Render.
        rc, _out, err = pinned_call(
            "review.py", "song-review", cwd=tmp_app_root, now=1_700_000_000 + i
        )
        assert rc == 0, err
        path = tmp_app_root / "output" / f"review_{1_700_000_000 + i}.html"
        payload = _load_data_block(path.read_text("utf-8"))

        song = next(s for s in payload["due_songs"] if s["song_id"] == sid)
        assert len(song["shows"]) == n_shows

        # Assert the payload's per-show media_urls match our expectation.
        for show_entry in song["shows"]:
            got = set(show_entry["media_urls"])
            expected = expected_urls_by_show[show_entry["show_id"]]
            assert got == expected, (
                f"iter {i} show {show_entry['show_id']}: got={got} expected={expected}"
            )

        # Assert the simulator renders those same URLs grouped by show
        # with no flat aggregate list elsewhere.
        tree = _dom_sim.render({"due_count": 1, "due_songs": [song]})
        blocks = _dom_sim.find_show_blocks(tree)
        assert len(blocks) == n_shows

        # Every URL appears in exactly one Show_Block.
        all_rendered_urls: list[str] = []
        for block in blocks:
            block_urls = [a.attrib["href"] for a in _dom_sim.find_anchors(block)]
            all_rendered_urls.extend(block_urls)

        # No duplicates across blocks.
        assert len(all_rendered_urls) == len(set(all_rendered_urls))

        # Set equality with the union across shows.
        expected_union: set[str] = set()
        for s in expected_urls_by_show.values():
            expected_union |= s
        assert set(all_rendered_urls) == expected_union

        # A show with zero URLs: block still present, no <ul class="links">.
        for block in blocks:
            # Pull the show name's span text to look up expected URLs.
            name_el = block.find("span[@class='show-name']")
            assert name_el is not None
            # The show_id lives on the Copy_Button inside this block.
            btn = block.find("button[@data-copy-id]")
            assert btn is not None
            shid = btn.attrib["data-copy-id"]
            if not expected_urls_by_show[shid]:
                assert block.find("ul[@class='links']") is None, (
                    f"iter {i}: show {shid} has empty URLs but has a <ul class='links'>"
                )
