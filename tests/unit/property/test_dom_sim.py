"""Unit tests for ``tests/integration/_dom_sim.py``.

Pin the simulator's output shape before the property tests under
``tests/integration/property/`` rely on it. Keeps the simulator
honest — if the Inline_Script's render flow in
``scripts/review_template.html`` ever shifts, this file (and the
simulator itself) shifts in lock-step.
"""

from __future__ import annotations

import pathlib
import sys

# Add the repo root to sys.path so we can import from tests/integration/.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.integration import _dom_sim  # noqa: E402

# ---------------------------------------------------------------------------
# media_url_basename edge cases
# ---------------------------------------------------------------------------


def test_basename_for_typical_http_url() -> None:
    assert _dom_sim.media_url_basename("http://example.com/videos/opening.mp4") == "opening.mp4"


def test_basename_for_url_with_query_and_fragment() -> None:
    # Query and fragment should not leak into the basename — only the
    # path's last segment matters.
    assert _dom_sim.media_url_basename("https://host/a/b/c.mp4?q=1#frag") == "c.mp4"


def test_basename_for_empty_path_returns_full_url() -> None:
    assert _dom_sim.media_url_basename("http://host") == "http://host"
    assert _dom_sim.media_url_basename("http://host/") == "http://host/"


def test_basename_trims_trailing_slash() -> None:
    assert _dom_sim.media_url_basename("https://host/foo/bar/") == "bar"


def test_basename_unparseable_returns_full_url() -> None:
    assert _dom_sim.media_url_basename("not a url at all") == "not a url at all"


# ---------------------------------------------------------------------------
# render(empty payload)
# ---------------------------------------------------------------------------


def test_render_empty_payload_returns_empty_state() -> None:
    tree = _dom_sim.render({"generated_at": 0, "due_count": 0, "due_songs": []})
    assert tree.tag == "p"
    assert tree.attrib.get("class") == "empty-state"
    assert tree.text == "No songs due."


# ---------------------------------------------------------------------------
# render(one song, one show, two URLs)
# ---------------------------------------------------------------------------


def _single_song_payload() -> dict:
    """Canonical one-song payload covering every renderable branch."""
    return {
        "generated_at": 1_700_000_000,
        "due_count": 1,
        "due_songs": [
            {
                "learning_id": "ll-1",
                "song_id": "song-1",
                "song_name": "Again",
                "song_name_context": "TV size",
                "artist_id": "artist-1",
                "artist_name": "Yui",
                "artist_name_context": "solo",
                "display_level": 3,
                "shows": [
                    {
                        "show_id": "show-1",
                        "show_name": "FMA: Brotherhood",
                        "show_name_romaji": "Hagane no Renkinjutsushi",
                        "show_vintage": "Spring 2009",
                        "show_s_type": "TV",
                        "media_urls": [
                            "http://example.com/a/clip.mp4",
                            "http://example.com/",  # empty-path fallback
                        ],
                    }
                ],
            }
        ],
    }


def test_render_single_song_shape() -> None:
    tree = _dom_sim.render(_single_song_payload())

    # Root is <ol>.
    assert tree.tag == "ol"
    lis = list(tree)
    assert len(lis) == 1
    li = lis[0]

    # <li data-level="3">.
    assert li.tag == "li"
    assert li.attrib.get("data-level") == "3"


def test_render_level_pill_and_song_title() -> None:
    tree = _dom_sim.render(_single_song_payload())
    li = next(iter(tree))

    # First two children: <span class="level"> and <span class="song">.
    level = li.find("span[@class='level']")
    assert level is not None
    assert level.text == "Level 3"

    title = li.find("span[@class='song']")
    assert title is not None
    assert title.text == "Again"


def test_render_copy_buttons_have_right_data_copy_ids() -> None:
    tree = _dom_sim.render(_single_song_payload())
    buttons = _dom_sim.find_copy_buttons(tree)
    # Three buttons: song, artist, show.
    copy_ids = [b.attrib["data-copy-id"] for b in buttons]
    assert copy_ids == ["song-1", "artist-1", "show-1"]
    # Every button is type=button, no onclick.
    for b in buttons:
        assert b.attrib.get("type") == "button"
        assert "onclick" not in b.attrib


def test_render_name_contexts_rendered_when_present() -> None:
    tree = _dom_sim.render(_single_song_payload())
    contexts = [el for el in tree.iter("span") if el.attrib.get("class") == "name-context"]
    # Song and artist both have a name_context → two elements.
    assert [c.text for c in contexts] == ["(TV size)", "(solo)"]


def test_render_anchors_href_full_text_basename() -> None:
    tree = _dom_sim.render(_single_song_payload())
    anchors = _dom_sim.find_anchors(tree)
    assert len(anchors) == 2

    # The clip.mp4 URL — basename is "clip.mp4".
    assert anchors[0].attrib["href"] == "http://example.com/a/clip.mp4"
    assert anchors[0].text == "clip.mp4"

    # The empty-path URL — fallback is the full URL.
    assert anchors[1].attrib["href"] == "http://example.com/"
    assert anchors[1].text == "http://example.com/"


def test_render_show_block_meta_line() -> None:
    tree = _dom_sim.render(_single_song_payload())
    blocks = _dom_sim.find_show_blocks(tree)
    assert len(blocks) == 1
    block = blocks[0]

    show_name = block.find("span[@class='show-name']")
    assert show_name is not None
    assert show_name.text == "FMA: Brotherhood"

    meta = block.find("span[@class='show-meta']")
    assert meta is not None
    # All three extras present, joined with ", " and prefixed " — ".
    assert meta.text == " \u2014 Hagane no Renkinjutsushi, Spring 2009, TV"


# ---------------------------------------------------------------------------
# render with no shows / no urls / no name contexts
# ---------------------------------------------------------------------------


def test_render_song_with_no_shows_has_no_shows_section() -> None:
    payload = _single_song_payload()
    payload["due_songs"][0]["shows"] = []
    tree = _dom_sim.render(payload)
    assert tree.find(".//div[@class='shows-section']") is None


def test_render_show_block_with_empty_urls_has_no_links_list() -> None:
    payload = _single_song_payload()
    payload["due_songs"][0]["shows"][0]["media_urls"] = []
    tree = _dom_sim.render(payload)
    blocks = _dom_sim.find_show_blocks(tree)
    assert len(blocks) == 1
    # Show block still renders (with name + meta) but has no <ul class="links">.
    assert blocks[0].find("ul[@class='links']") is None


def test_render_song_with_no_name_contexts_omits_those_spans() -> None:
    payload = _single_song_payload()
    payload["due_songs"][0]["song_name_context"] = ""
    payload["due_songs"][0]["artist_name_context"] = None
    tree = _dom_sim.render(payload)
    contexts = [el for el in tree.iter("span") if el.attrib.get("class") == "name-context"]
    assert contexts == []
