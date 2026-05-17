---
name: open-spec-amq-import-romaji-required
description: Active bugfix spec that makes show romaji a required input on the AMQ importer; design.md and tasks.md are still owed.
metadata:
  type: project
---

`.kiro/specs/amq-import-romaji-required/` was opened on 2026-05-17.
All four files landed: `.config.kiro`, `bugfix.md`, `design.md`,
`tasks.md`. Spec is ready for implementation; nothing else owed
until the implementation phase begins.

**Why:** the AMQ importer treats `songInfo.animeNames.romaji` as
a silent fallback for `show_name` and never persists it into
`show.name_romaji` (which is hard-coded to `None` in
`scripts/import_plan.py`'s `_resolve_show`). A future shape drift
that moves the romaji to a different path would silently produce
shows with `name_romaji = NULL` and an English-or-romaji-conflated
`show_name`, repeating the v0.1.1 → v0.1.2 drift that
`amq-real-export-shape-fix` corrected for the other fields.

**How to apply** when continuing this spec:

- Scope is locked to **show romaji only** (not song-name romaji, not
  artist romaji). Schema has `show.name_romaji`; no migration.
- Storage decision is "persist into `show.name_romaji` AND remove the
  English-falls-back-to-romaji precedence on `show_name`". `show_name`
  becomes English-only; romaji is its own required flat key.
- Recovery path on shape drift uses `scripts/data.py create --kind show`
  — no new script, no new flag on `import_plan.py`.
- Trigger for the agent's diagnosis flow is **proactive** — a Step 0
  shape sniff that runs **before** every `scripts/import_plan.py`
  invocation, not just on rejection.
- Design decisions (locked in `design.md`):
  - Error code = `INVALID_INPUT` with `details.kind =
    "missing_romaji"` (no new `MISSING_ROMAJI` code).
  - Flat key = `show_name_romaji` on the preprocessor output and
    on the `show_to_create` block (translates to DB column
    `name_romaji` in `_resolve_show`).
  - Step 0 sniff is inline in `skills/importing-amq-songs/SKILL.md` —
    no new script, no new `--sniff` flag on `import_plan.py`.
  - Sniff scope = romaji only.
  - Recovery = `scripts/data.py create --kind show` with
    `name`, `name_romaji`, `vintage`, `s_type`, then re-run the
    three-step pipeline.

See [[importer-architecture-pointers]] for the file/line context the
design phase will need.
