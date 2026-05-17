# Memory Index — jankenoboe-lite

This directory holds project memory checked into the repo so any new
Claude Code session (or other agent that reads `.claude/memory/`)
starts with the same context. Each line below points at a file in
this directory.

## Setup

The harness's default per-project memory dir is at
`~/.claude/projects/-Users-zmyunqin-local-play-github-jankenoboe-lite/memory/`.
That is NOT this directory. To make a fresh session pick this up,
either symlink it (`ln -s <repo>/.claude/memory ~/.claude/projects/.../memory`)
or paste the relevant memories into the session manually. The user
declined the auto-symlink in the session that wrote this index.

## Project memories

- [Spec workflow conventions](spec_workflow_conventions.md) — how `.kiro/specs/<slug>/` is laid out and which files come first.
- [Open spec: amq-import-romaji-required](open_spec_amq_import_romaji_required.md) — the active bugfix spec; design.md and tasks.md still owed.

## Reference memories

- [Importer architecture pointers](importer_architecture_pointers.md) — script + skill paths for the AMQ import surface.

## Feedback memories

- [Spec authoring rhythm](feedback_spec_authoring_rhythm.md) — write bugfix.md first, defer design + tasks until requirements are signed off.
