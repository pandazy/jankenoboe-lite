"""Python-side simulator for the review page's Inline_Script.

This is a pure-Python translation of the ``renderList`` / ``renderSong`` /
``renderShowBlock`` / ``renderAnchor`` / ``copyButton`` functions that live
in ``scripts/review_template.html``. Given a ``Due_Data_Payload`` dict,
``render(payload)`` returns an ``xml.etree.ElementTree.Element`` tree
that mirrors what the browser's Inline_Script would build on load.

Tests use this to make structural claims about the Rendered_DOM
(``"the second `<li>` contains exactly one Copy_Button with
data-copy-id == S.song_id after the song title"``) without needing a
real browser. The simulator is test-only; it never runs at runtime.

Keep this file in lock-step with the Inline_Script's render flow in
``scripts/review_template.html``. A small set of unit tests in
``tests/unit/property/test_dom_sim.py`` pins the simulator's output
shape.
"""

from __future__ import annotations

import urllib.parse
from typing import Any
from xml.etree.ElementTree import Element, SubElement


def media_url_basename(url: str) -> str:
    """Python port of the Inline_Script's ``mediaUrlBasename``.

    The Inline_Script uses ``new URL(url, 'https://placeholder')``,
    then trims trailing slashes on the pathname, then takes the last
    ``/``-separated segment. Empty or ``/``-only paths fall back to
    the full URL. Unparseable URLs fall back to the full URL too.
    """
    try:
        # urlparse accepts any string; the result's ``path`` is what
        # ``pathname`` would give the Inline_Script for http(s) URLs.
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return url
    path = parsed.path or ""
    # For URLs without a scheme (e.g. ``"not a url"``) urlparse still
    # parses — it just packs the whole thing into ``path``. The
    # Inline_Script's ``new URL('not a url', base)`` rejects that,
    # so match the browser's behaviour here.
    if not parsed.scheme and not parsed.netloc:
        return url
    while path.endswith("/"):
        path = path[:-1]
    if path == "":
        return url
    idx = path.rfind("/")
    last = path if idx < 0 else path[idx + 1 :]
    if last == "":
        return url
    return last


def _copy_button(parent: Element, copy_target_id: str) -> Element:
    """Mirror of Inline_Script's ``copyButton``."""
    btn = SubElement(
        parent,
        "button",
        {"type": "button", "data-copy-id": copy_target_id, "class": "copy-btn"},
    )
    btn.text = "copy"
    return btn


def _render_anchor(parent: Element, url: str) -> Element:
    a = SubElement(parent, "a", {"href": url})
    a.text = media_url_basename(url)
    return a


def _render_show_block(parent: Element, sh: dict[str, Any]) -> Element:
    block = SubElement(parent, "div", {"class": "show-block"})

    name = SubElement(block, "span", {"class": "show-name"})
    name.text = sh["show_name"]

    _copy_button(block, sh["show_id"])

    extras = [
        x
        for x in (
            sh.get("show_name_romaji"),
            sh.get("show_vintage"),
            sh.get("show_s_type"),
        )
        if x
    ]
    if extras:
        meta = SubElement(block, "span", {"class": "show-meta"})
        meta.text = " \u2014 " + ", ".join(extras)

    urls = sh.get("media_urls") or []
    if urls:
        ul = SubElement(block, "ul", {"class": "links"})
        for u in urls:
            li = SubElement(ul, "li", {})
            _render_anchor(li, u)
    return block


def _render_song(parent: Element, s: dict[str, Any]) -> Element:
    li = SubElement(parent, "li", {"data-level": str(s["display_level"])})

    pill = SubElement(li, "span", {"class": "level"})
    pill.text = "Level " + str(s["display_level"])

    title = SubElement(li, "span", {"class": "song"})
    title.text = s["song_name"]

    _copy_button(li, s["song_id"])

    if s.get("song_name_context"):
        ctx = SubElement(li, "span", {"class": "name-context"})
        ctx.text = "(" + s["song_name_context"] + ")"

    artist = SubElement(li, "div", {"class": "artist"})
    a_name = SubElement(artist, "span", {})
    a_name.text = s["artist_name"]
    _copy_button(artist, s["artist_id"])
    if s.get("artist_name_context"):
        ac = SubElement(artist, "span", {"class": "name-context"})
        ac.text = "(" + s["artist_name_context"] + ")"

    shows = s.get("shows") or []
    if shows:
        section = SubElement(li, "div", {"class": "shows-section"})
        section.text = "Shows:"
        for sh in shows:
            _render_show_block(section, sh)
    return li


def render(payload: dict[str, Any]) -> Element:
    """Return the root Element the Inline_Script would mount at ``#root``.

    For empty payloads this is a ``<p class="empty-state">`` element.
    For non-empty payloads it is an ``<ol>`` whose children are one
    ``<li data-level="...">`` per due song.
    """
    songs = payload.get("due_songs") or []
    if not songs:
        p = Element("p", {"class": "empty-state"})
        p.text = "No songs due."
        return p
    ol = Element("ol", {})
    for s in songs:
        _render_song(ol, s)
    return ol


# ---------------------------------------------------------------------------
# Small helpers test modules find convenient.
# ---------------------------------------------------------------------------


def find_copy_buttons(root: Element) -> list[Element]:
    """All Copy_Buttons under ``root`` (pre-order)."""
    return [
        el
        for el in root.iter("button")
        if el.attrib.get("type") == "button" and "data-copy-id" in el.attrib
    ]


def find_anchors(root: Element) -> list[Element]:
    """All ``<a>`` elements under ``root`` (pre-order)."""
    return list(root.iter("a"))


def find_show_blocks(root: Element) -> list[Element]:
    """All Show_Blocks under ``root`` (pre-order)."""
    return [el for el in root.iter("div") if el.attrib.get("class") == "show-block"]
