"""Static source-tree tests that pin the due-time predicate to a single file.

The three-branch "is this learning record due?" predicate is the single
source of truth for both ``learning.py due`` and ``review.py song-review``.
Before v0.1.4 it existed as literal SQL text in two files (``learning.py``
and ``review.py``) and drift between the copies already caused one
regression (v0.1.2 shipped ``review.py`` without the ``+ :offset`` terms
while ``learning.py`` had them). After v0.1.4 the predicate lives in
exactly one file — ``scripts/_common.py`` — and both callers compose
their ``_DUE_SQL`` via f-string interpolation.

These tests are static-analysis tests: they read ``.py`` files under
``scripts/`` and assert structural properties. No DB, no subprocess, no
fixtures.
"""

from __future__ import annotations

import pathlib
import re

from scripts import _common, learning, review

SCRIPTS_DIR = pathlib.Path(__file__).parent.parent.parent / "scripts"

# A three-substring fingerprint that identifies "the three-branch
# due-time predicate" robustly. Matching is done against the file's
# text after collapsing runs of whitespace to a single space, so
# formatting differences between callers don't defeat the check.
FINGERPRINTS = (
    "l.last_level_up_at + 300",
    "l.updated_at + 300",
    "json_extract(l.level_up_path",
)


def _matches(path: pathlib.Path) -> bool:
    text = path.read_text(encoding="utf-8")
    collapsed = re.sub(r"\s+", " ", text)
    return all(fp in collapsed for fp in FINGERPRINTS)


def test_due_time_predicate_lives_in_exactly_one_file() -> None:
    """The predicate text appears in exactly one file — ``scripts/_common.py``.

    On v0.1.3 (unfixed): this test FAILS with count == 2 and the list
    ``['scripts/learning.py', 'scripts/review.py']``.
    On v0.1.4 (fixed): PASSES with count == 1 in ``scripts/_common.py``.
    """
    matches = sorted(p for p in SCRIPTS_DIR.rglob("*.py") if _matches(p))
    rel = [str(p.relative_to(SCRIPTS_DIR.parent)) for p in matches]
    assert len(matches) == 1, f"expected predicate in exactly one file, found {len(matches)}: {rel}"
    assert matches[0].name == "_common.py", (
        f"expected single match in scripts/_common.py, got {matches[0]}"
    )


def test_due_sql_strings_compose_from_common() -> None:
    """Both callers' ``_DUE_SQL`` embed ``_common.DUE_TIME_CONDITION_SQL``.

    Structural witness via Python import rather than text grep — proves
    the composed f-strings actually include the shared constant at module
    load, not just that they look similar.
    """
    assert hasattr(_common, "DUE_TIME_CONDITION_SQL"), (
        "scripts/_common.py must define DUE_TIME_CONDITION_SQL"
    )
    assert isinstance(_common.DUE_TIME_CONDITION_SQL, str)

    predicate = _common.DUE_TIME_CONDITION_SQL
    assert predicate in learning._DUE_SQL, (
        "scripts/learning.py._DUE_SQL must contain DUE_TIME_CONDITION_SQL as a substring"
    )
    assert predicate in review._DUE_SQL, (
        "scripts/review.py._DUE_SQL must contain DUE_TIME_CONDITION_SQL as a substring"
    )
