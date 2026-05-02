"""Property I-5 — every skill begins with `python scripts/init_db.py`.

For every skills/*/SKILL.md: parse the file's Markdown, locate the
first workflow-shaped section (heading text contains "Checklist" or
"Workflow"), and assert the first list item under that heading
mentions `python scripts/init_db.py`. Adding a new skill extends
the test input set automatically via parametrization.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SKILLS = sorted((_REPO_ROOT / "skills").glob("*/SKILL.md"))


def _first_workflow_step(md_text: str) -> str | None:
    """Return the text of the first list item under the first
    workflow-shaped section, or None if none found.

    A workflow-shaped section is any ``##`` heading whose text
    contains ``checklist``, ``workflow``, or ``pre-flight``
    (case-insensitive). Matching "pre-flight" catches skills like
    ``merging-artists`` whose first actionable section is titled
    that way.
    """
    lines = md_text.splitlines()
    in_workflow = False
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            in_workflow = any(token in heading for token in ("checklist", "workflow", "pre-flight"))
            continue
        if in_workflow:
            stripped = line.strip()
            # Ordered (1. ...) or unordered (- ... / * ...) list item.
            if re.match(r"^\d+\.\s", stripped) or stripped.startswith(("- ", "* ")):
                return stripped
            # Non-list, non-blank line before a list: keep scanning.
    return None


@pytest.mark.parametrize("skill_path", _SKILLS, ids=lambda p: p.parent.name)
def test_skill_workflow_begins_with_init_db(skill_path: pathlib.Path) -> None:
    assert _SKILLS, "expected at least one skill under skills/*/SKILL.md"

    first_step = _first_workflow_step(skill_path.read_text("utf-8"))
    assert first_step is not None, (
        f"{skill_path}: could not find a workflow section with a first list item"
    )
    assert "python scripts/init_db.py" in first_step, (
        f"{skill_path}: first workflow step must mention "
        f"`python scripts/init_db.py`, got: {first_step!r}"
    )
