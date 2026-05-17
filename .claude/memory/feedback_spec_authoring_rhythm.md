---
name: feedback-spec-authoring-rhythm
description: Land the requirements file (bugfix.md or requirements.md) on the first turn; design.md and tasks.md follow only after sign-off.
metadata:
  type: feedback
---

When opening a new spec under `.kiro/specs/`, only land the
requirements file on the first turn — `bugfix.md` for bugfix specs,
`requirements.md` for feature specs. `design.md` and `tasks.md` come
in later turns, after the requirements are signed off.

**Why:** the user explicitly chose "just bugfix.md" over the
all-three-files option when opening
`.kiro/specs/amq-import-romaji-required/` on 2026-05-17, citing the
parent spec (`amq-real-export-shape-fix`) which followed the same
rhythm — bugfix first, design + tasks later. Locking design choices
before requirements review wastes review effort if the requirements
shift.

**How to apply:** On any "create a new spec" request in this repo,
default to writing only the requirements file plus the
`.config.kiro` stub. Ask before adding `design.md` or `tasks.md`
unless the user explicitly asks for the full triple. Use
[[spec-workflow-conventions]] for the file layout and
[[open-spec-amq-import-romaji-required]] as the worked example.
