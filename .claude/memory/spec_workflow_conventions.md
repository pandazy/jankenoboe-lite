---
name: spec-workflow-conventions
description: Layout and naming conventions every .kiro/specs/<slug>/ directory in this repo follows.
metadata:
  type: project
---

Spec directories under `.kiro/specs/` follow this layout:

- `.config.kiro` — JSON: `{"specId": "<uuid4>", "workflowType": "requirements-first", "specType": "bugfix" | "feature"}`. The spec UUID is generated once at directory creation; never regenerated.
- For `specType: bugfix` — `bugfix.md` (Introduction, Bug Analysis, Deriving the Bug Condition with Property + Preservation Goal, Key Definitions), `design.md`, `tasks.md`. The bugfix.md uses formal-spec-style numbered clauses: 1.x = current defect, 2.x = expected behavior, 3.x = regression prevention.
- For `specType: feature` (e.g. `learning-leveldown`, `anime-song-learning-app`) — `requirements.md` instead of `bugfix.md`; same `design.md` + `tasks.md`.

**Why:** the existing specs (`amq-real-export-shape-fix`, `importer-and-graduate-fixes`, `learning-leveldown`, etc.) all match this shape; matching it makes new specs reviewable against the same template.

**How to apply:** when creating a new spec, generate a fresh UUID for `.config.kiro`, name the directory in kebab-case under `.kiro/specs/`, and only land the requirements file (bugfix.md or requirements.md) on the first turn. See [[feedback-spec-authoring-rhythm]] for why design/tasks come later.

Bugfix specs derive a formal "Bug Condition" predicate plus a "Property (Fix Checking)" and "Preservation Goal" in pascal-style pseudocode — see `amq-real-export-shape-fix/bugfix.md` for the canonical example. The Property quantifies over inputs that meet the bug condition; the Preservation Goal quantifies over inputs that do not. Both are required.

Related: [[open-spec-amq-import-romaji-required]] is the active bugfix spec following this convention.
