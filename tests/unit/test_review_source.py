"""Assert no ``.py`` file under ``scripts/`` contains HTML tag literals.

The review-html-enhancements spec (R-RH-1.2, P-RH-0.1) forbids HTML
element opening tags from appearing as code literals in any Python
file under ``scripts/``. Docstrings and comments are exempt — the
intent is to forbid render-side markup in Python, not to stop a
docstring from mentioning a tag name in prose. This test uses
``tokenize`` to strip docstrings and comments, then greps the
remaining code tokens for HTML opening-tag patterns.

The Template_File (``scripts/review_template.html``) is intentionally
NOT a ``.py`` file, so this test does not look at it.
"""

from __future__ import annotations

import io
import pathlib
import re
import tokenize

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"


# Opening-tag patterns. ``<a `` has a trailing space on purpose so we
# don't match the Python expression ``<a`` (identifier comparison) or
# the substring ``<anything>`` spelled in identifier form. Every other
# entry is a standard HTML element that should never appear as a code
# literal in this runtime.
_FORBIDDEN_TAG_PATTERNS = [
    r"<html\b",
    r"<head\b",
    r"<body\b",
    r"<li\b",
    r"<a\s",
    r"<button\b",
    r"<script\b",
    r"<style\b",
    r"<div\b",
    r"<span\b",
    r"<p\b",
    r"<h[1-6]\b",
    r"<title\b",
    r"<meta\b",
    r"<link\b",
    r"<br\b",
    r"<hr\b",
    r"<pre\b",
    r"<code\b",
    r"<table\b",
    r"<tr\b",
    r"<td\b",
    r"<th\b",
    r"<ul\b",
    r"<ol\b",
    r"<nav\b",
    r"<section\b",
    r"<article\b",
    r"<header\b",
    r"<footer\b",
    r"<form\b",
    r"<input\b",
    r"<iframe\b",
    r"<img\b",
]

_COMBINED_PATTERN = re.compile("|".join(_FORBIDDEN_TAG_PATTERNS), re.IGNORECASE)


def _strip_comments_and_docstrings(source: str) -> str:
    """Return ``source`` with comments and docstrings replaced by blanks.

    Docstrings are identified structurally: a ``STRING`` token that sits
    at the start of a module, class, or function body (first statement
    position, with only optional preceding ``INDENT`` / ``NEWLINE``
    tokens). Every other string literal is code and stays in scope.
    ``tokenize`` handles the token stream; we rebuild the source with
    comment and docstring ranges blanked out.
    """
    lines = source.splitlines(keepends=True)

    def blank_range(start: tuple[int, int], end: tuple[int, int]) -> None:
        (srow, scol), (erow, ecol) = start, end
        if srow == erow:
            line = lines[srow - 1]
            lines[srow - 1] = line[:scol] + (" " * (ecol - scol)) + line[ecol:]
            return
        # Multi-line range (e.g. triple-quoted docstring or multi-line
        # string). Blank the first line from scol to EOL, the last line
        # up to ecol, and every middle line entirely.
        first = lines[srow - 1]
        lines[srow - 1] = first[:scol] + (" " * (len(first) - scol))
        for i in range(srow, erow - 1):
            ln = lines[i]
            lines[i] = " " * len(ln)
        last = lines[erow - 1]
        lines[erow - 1] = (" " * ecol) + last[ecol:]

    readline = io.StringIO(source).readline
    tokens = list(tokenize.generate_tokens(readline))

    # First pass — blank every comment.
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            blank_range(tok.start, tok.end)

    # Second pass — blank docstrings. A docstring is a STRING token that
    # appears in "statement-start" position: either the first code
    # token of the module, or immediately after a `:` NEWLINE INDENT
    # sequence opening a class/function body. We can identify these by
    # walking the logical-line stream.
    def is_docstring_position(idx: int) -> bool:
        """Is ``tokens[idx]`` a docstring, i.e. at statement start?"""
        if tokens[idx].type != tokenize.STRING:
            return False
        # Scan backwards past any NL, NEWLINE, INDENT, COMMENT.
        j = idx - 1
        while j >= 0 and tokens[j].type in (
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.COMMENT,
            tokenize.ENCODING,
        ):
            j -= 1
        if j < 0:
            return True  # module-level first statement — module docstring.
        # Otherwise, a docstring sits right after a `:` that closed a
        # class/function header, OR right after a function/class colon.
        prev = tokens[j]
        return prev.type == tokenize.OP and prev.string == ":"

    for i, tok in enumerate(tokens):
        if is_docstring_position(i):
            blank_range(tok.start, tok.end)

    return "".join(lines)


def _python_files_under_scripts() -> list[pathlib.Path]:
    return sorted(p for p in _SCRIPTS_DIR.rglob("*.py"))


def test_scripts_contain_no_html_tag_literals() -> None:
    """R-RH-1.2 / P-RH-0.1 — no ``.py`` file under ``scripts/`` contains HTML.

    Runs ``_strip_comments_and_docstrings`` over each file's source
    and asserts the remaining code text matches none of the forbidden
    HTML opening-tag patterns.
    """
    files = _python_files_under_scripts()
    assert files, "expected at least one .py file under scripts/"

    offenders: list[tuple[str, str]] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        stripped = _strip_comments_and_docstrings(source)
        for match in _COMBINED_PATTERN.finditer(stripped):
            offenders.append((str(path.relative_to(_REPO_ROOT)), match.group(0)))

    assert not offenders, (
        "Expected no HTML tag literals in scripts/*.py code (docstrings "
        "and comments are allowed to mention tags in prose). Offenders:\n"
        + "\n".join(f"  {path}: {snippet!r}" for path, snippet in offenders)
    )


def test_template_file_exists_and_has_script_tag() -> None:
    """The Template_File ships with the scripts/ tree and carries its HTML.

    Negative-space counterpart to the test above — the Template_File is
    where HTML tags *do* belong, and it must exist for the runtime to
    work.
    """
    tpl = _SCRIPTS_DIR / "review_template.html"
    assert tpl.is_file()
    text = tpl.read_text(encoding="utf-8")
    assert "<script" in text
    assert "<!-- DUE_DATA_JSON -->" in text
