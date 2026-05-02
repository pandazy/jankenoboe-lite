"""Property P-RH-0.1 — no HTML tag literal in ``scripts/*.py``.

Randomised counterpart to ``tests/unit/test_review_source.py``. For
each iteration, pick a forbidden tag name and a random casing, stitch
it into a regex, and assert the docstring/comment-stripped code of
every ``.py`` file under ``scripts/`` contains zero matches. Also
verify the Template_File exists and carries at least one ``<script``
tag (the negative-space check).
"""

from __future__ import annotations

import pathlib
import random
import re
import sys

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

# Reuse the tokenize stripper from the unit test to stay in lock-step.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tests.unit.test_review_source import (  # noqa: E402
    _python_files_under_scripts,
    _strip_comments_and_docstrings,
)

SEED = BASE_SEED + 100

_FORBIDDEN_TAGS = [
    "html",
    "head",
    "body",
    "li",
    "button",
    "script",
    "style",
    "div",
    "span",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "title",
    "meta",
    "link",
    "br",
    "hr",
    "pre",
    "code",
    "table",
    "tr",
    "td",
    "th",
    "ul",
    "ol",
    "nav",
    "section",
    "article",
    "header",
    "footer",
    "form",
    "input",
    "iframe",
    "img",
]


def _mixcase(rng: random.Random, text: str) -> str:
    """Random case mix for a string — same chars, mixed upper/lower."""
    return "".join(rng.choice([c.lower(), c.upper()]) for c in text)


def test_no_forbidden_tag_literal_in_scripts() -> None:
    """P-RH-0.1: randomised tag + casing sweep over ``scripts/*.py``."""
    rng = random.Random(SEED)
    files = _python_files_under_scripts()
    # Strip once; the stripped source doesn't change between iterations.
    stripped_sources = [
        (str(p.relative_to(_REPO_ROOT)), _strip_comments_and_docstrings(p.read_text("utf-8")))
        for p in files
    ]

    for _ in range(ITERATIONS):
        tag = rng.choice(_FORBIDDEN_TAGS)
        cased = _mixcase(rng, tag)
        # Word boundary after the tag so "<p>" trips but "<print(" doesn't.
        pattern = re.compile(r"<" + re.escape(cased) + r"\b", re.IGNORECASE)

        offenders = [
            (path, snippet.group(0))
            for path, source in stripped_sources
            for snippet in pattern.finditer(source)
        ]
        assert not offenders, f"tag={tag!r} case={cased!r} — offenders: {offenders!r}"


def test_template_file_ships_with_html() -> None:
    """P-RH-0.2 — HTML lives in the Template_File, which exists."""
    tpl = _REPO_ROOT / "scripts" / "review_template.html"
    assert tpl.is_file()
    text = tpl.read_text("utf-8")
    assert "<script" in text
    assert "<!-- DUE_DATA_JSON -->" in text
