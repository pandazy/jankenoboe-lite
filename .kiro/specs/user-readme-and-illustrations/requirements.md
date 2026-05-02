# Requirements Document

## Introduction

This spec gives the repo a proper human-user landing page and three
SVG illustrations, and re-scopes the top-level `docs/` folder to ship
with the deployable zip instead of staying on the author's machine.
Author-only documentation moves to a new `dev-docs/` folder that is
excluded from the zip by the same construction rule that keeps
`.kiro/` out (see the `review-html-enhancements` spec's R-RH-7).

The audience split this spec formalises across the four top-level
content folders:

- **Repo-root `README.md`** — the human user's landing page. Ships in
  the deployable zip so the same text lands on the deploy target.
- **`docs/`** — user-facing shipping assets. Re-scoped from
  "author-only" to "part of the deployable zip". The three SVGs
  this spec adds live here.
- **`dev-docs/`** (new) — author-only development notes. Houses
  `sandbox-packages.md` (moved from `docs/`), which is a snapshot
  of one sandbox's pre-installed packages the author consulted
  during development. It is development inspiration / research
  material, not a deliverable. Never ships, never referenced from
  the user-facing README.
- **`skills/`** — LLM-facing. Unchanged by this spec.

This document reuses (does not re-state) the contracts defined by the
parent `anime-song-learning-app` spec and the `review-html-enhancements`
spec, in particular:

- Parent R1.2 (stdlib-only runtime). This spec adds no runtime code,
  so it does not widen that surface.
- Parent R20 / `review-html-enhancements` R-RH-7 (packaging). This
  spec amends the copy list: `docs/` joins `scripts/`, `skills/`,
  `db/datasource.db`, `Makefile`, and (when present) `README.md`.
  `dev-docs/` stays off the list.
- `review-html-enhancements` R-RH-7's two-layer exclusion model
  (inclusion-by-enumeration at the top level, `_SKIP_DIR_NAMES`
  defense-in-depth inside every copied tree). This spec extends the
  model to cover `docs/` and explicitly names `dev-docs/` as a
  by-construction exclusion.
- Parent R1 (one DB file at `App_Root/db/datasource.db`) and the
  `db-init-command` spec's I-2 behavior (create-or-skip for
  `scripts/init_db.py`). The README tells the user those facts in
  plain language; it is not a re-definition of them.

### Motivation

The repo today has no human-facing introduction. A person who clones
or downloads it is expected to read the `.kiro/specs/` tree or the
skill docs to figure out what the app is and how to use it, neither
of which is written for that audience. The three things a new reader
most needs to see — the data model, the spaced-repetition timing
idea, and the import flow — are buried in prose and SQL. Three small
hand-authored SVGs fix that for the price of three files.

The `docs/` folder is also misnamed today: it contains exactly one
file (`sandbox-packages.md`), written for the author, and the
packager excludes the folder by construction. This spec repurposes
`docs/` as the user-facing shipping folder and moves the author-only
file out of it, so each folder matches its audience without a second
layer of conditionals in the packager.

## Glossary

Terms from the parent `anime-song-learning-app` spec (App_Root,
Script, DB_File, UUID, etc.) apply here as defined there. Terms
from the `review-html-enhancements` spec's R-RH-7 (the
"exclusion model", `_SKIP_DIR_NAMES`) apply as defined there. The
terms below are specific to this spec.

- **Repo_Root_README**: The Markdown file at `README.md` at the
  repository root. Introduced by this spec. Part of the deployable
  zip (see `tools/package.py._EXTRA_TOP_LEVEL`).
- **User_Docs_Folder**: The directory `docs/` at the repository root,
  after this spec lands. Ships in the deployable zip under the same
  path (`docs/`). Contains the three SVG illustrations defined in
  R-UR-2 and no author-only files.
- **Author_Docs_Folder**: The new directory `dev-docs/` at the
  repository root, introduced by this spec. Houses author-only
  documentation — at minimum `dev-docs/sandbox-packages.md`,
  relocated from `docs/sandbox-packages.md`. Excluded from the
  deployable zip by construction (see R-UR-3.4).
- **Data_Model_SVG**: The illustration at `docs/data-model.svg`.
  Shows the six tables of the app's SQLite schema (`artist`, `song`,
  `show`, `rel_show_song`, `play_history`, `learning`) and the
  foreign-key arrows between them.
- **Spaced_Repetition_SVG**: The illustration at
  `docs/spaced-repetition.svg`. Shows the level-up wait-days curve
  defined by the parent spec's Glossary (`default_easing`,
  `level_up_path` — concretely `[1, 1, 1, 1, 1, 1, 1, 2, 3, 5, 7,
  13, 19, 32, 52, 84, 135, 220, 355, 574]` days for `max_level = 20`)
  and illustrates the "review → level up → wait longer next time"
  loop.
- **Import_Pipeline_SVG**: The illustration at
  `docs/import-pipeline.svg`. Shows the three-step AMQ import flow
  (`import_plan.py → plan.json` → operator-filled `answers.json` for
  ambiguous entries → `import_resolve.py → triples.json` →
  `add_play_history.py` → the deployed DB).
- **Illustration_Set**: The set
  `{Data_Model_SVG, Spaced_Repetition_SVG, Import_Pipeline_SVG}`. All
  three are required for this spec to be complete.
- **Valid_SVG**: An SVG file that (a) parses as well-formed XML and
  (b) has `<svg>` as its root element. No stricter validation is
  required — the intent is "opens in a browser without error", not
  full W3C conformance.
- **Text_Rendered_SVG**: A Valid_SVG in which every caption, label,
  or title appears as a `<text>` element (so the text is selectable,
  searchable, and accessible), not as a path tracing a glyph. See
  R-UR-2 for the exact rule.

## Requirements

### Requirement R-UR-1: Repo-Root README for the Human User

**User Story:** As a human user who just downloaded or cloned this
repo, I want a short, clear README at the root that tells me what
this app is, where it's meant to run, how to deploy it, how to get a
working database, and how to actually use it, so I don't have to
read the spec tree to figure it out.

#### Acceptance Criteria

1. THE Repo_Root_README SHALL exist at `README.md` at the repository
   root and SHALL be a plain Markdown document (no HTML tag literals
   are required; one-off `<img>` tags for illustrations are
   permitted). THE Repo_Root_README SHALL be written for a human
   user, not for Claude or another LLM and not for the author of
   the repo.
2. THE Repo_Root_README SHALL cover these six topics, in this
   order, each with a short heading (the sixth MAY be a
   sub-section of the fifth rather than a peer heading):
   1. **What this app is** — one paragraph describing it as a local
      SQLite-backed spaced-repetition app for memorising anime
      songs, stdlib-only Python, one DB file at
      `App_Root/db/datasource.db`.
   2. **Where it's meant to run** — one paragraph explaining the
      deploy target: a restricted Python 3.10+ environment such as a
      code-execution sandbox attached to an LLM (OpenAI ChatGPT,
      xAI Grok, Anthropic Claude, etc.) or any Python 3.10+ install
      without `pip install`. THE paragraph SHALL restate the
      parent-spec rule that there are no third-party runtime
      dependencies. Naming specific vendors is illustrative, not
      an endorsement; the constraint is "restricted Python 3.10+
      with stdlib only".
   3. **How to deploy** — a short section explaining that deployment
      is: download the latest zip under `dist/` (or build it with
      `make package`), upload it to the sandbox, unzip. No
      `pip install`, no venv, no build step at the target.
   4. **How to get a database** — a short section covering the three
      paths defined by the parent spec and the `db-init-command`
      spec:
      a. The zip ships an empty schema-only `db/datasource.db`;
         after unzip, the DB already exists and no action is
         needed.
      b. To bring an existing DB in, drop it at
         `db/datasource.db` before handing the tree to the agent.
      c. To start fresh (or recover from a deleted DB), run
         `python scripts/init_db.py` — which is a safe no-op when
         the DB already exists (per `db-init-command` spec I-2.2).
   5. **How to use it** — one paragraph making clear that the user
      does not use the scripts directly; they hand the deployed
      tree to an AI agent and ask it to do things. THE section
      SHALL include a short list of suggested first prompts, at
      minimum: "What can this app do?", "Explain the workflow for
      learning a new song.", "Start a review session.", "I have an
      AMQ export I want to import."
   6. **How to get an AMQ export file** — a short sub-section (or
      a short note attached to the AMQ-related suggested prompt in
      topic 5, at the author's discretion) telling the user where
      the AMQ JSON comes from. It SHALL state, in plain English:
      a. Go to AnimeMusicQuiz at
         `https://animemusicquiz.com/`.
      b. Play a game (any mode).
      c. After the game, export the last-played songs — the site
         produces a JSON file listing the songs that just played,
         including fields such as song name, artist, show name
         and vintage.
      d. Hand that JSON file to the agent and ask it to import it.
         The `import_plan.py` / `import_resolve.py` /
         `add_play_history.py` pipeline (see the import
         illustration) reads that file.
      e. The Repo_Root_README SHALL link at least once to an
         example of the export shape, pointing at
         `https://github.com/pandazy/jankenoboe/blob/main/docs/design/v1/amq_song_export-small.json`
         so a curious reader can see the structure without
         playing a game first. The link text SHALL make clear
         that this is an example from a sibling project and not
         part of this repo.
      THE sub-section SHALL NOT attempt to document the AMQ JSON
      schema field-by-field; pointing at the sample file is the
      documentation. The sub-section text SHALL be short — a few
      lines at most — to stay within the R-UR-1.7 line ceiling.
3. THE Repo_Root_README SHALL reference every SVG in the
   Illustration_Set inline, each next to the topic it illustrates:
   - Data_Model_SVG next to or inside the "What this app is"
     section (the data model is what the app is about).
   - Spaced_Repetition_SVG next to or inside a short passage on the
     review loop. The passage MAY live under "How to use it" or in
     its own one-paragraph section; the spec does not mandate which.
   - Import_Pipeline_SVG next to or inside the AMQ-related suggested
     prompt in "How to use it".
4. WHEN the Repo_Root_README embeds an image, it SHALL use a path
   relative to the README (i.e. `docs/...`), so that the link
   resolves both in the source repo (where it points at
   `docs/data-model.svg` next to the README) and in the deployable
   zip (where the same relative path resolves, since both the
   README and `docs/` ship at the zip root — see R-UR-3).
5. FOR every image reference in the Repo_Root_README — whether
   `![alt](path)` Markdown form or `<img src="path">` HTML form —
   the referenced `path`, resolved relative to the README's own
   directory, SHALL point at a file that exists on disk at that
   path in the source repo. Broken image links are an author-side
   review item (verified by opening the README), not a mechanical
   check.
6. THE Repo_Root_README SHALL ship in the deployable zip. The
   existing `tools/package.py._copy_extras` hook already copies
   `README.md` when present at the repo root (`_EXTRA_TOP_LEVEL`
   includes `"README.md"`); this criterion is the reason that hook
   exists and SHALL NOT be bypassed.
7. THE Repo_Root_README SHALL be at most 200 lines long (counting
   every line in the file, including blank lines, headings, and
   image references). This is a ceiling, not a target. (Rationale:
   the same "don't turn into a manual" discipline the parent specs
   apply to their own docs — when prose grows past ~200 lines, it
   has stopped being a landing page.)
8. THE Repo_Root_README SHALL NOT include GitHub-specific chrome
   (CI badges, status shields, issue-template links, PR-template
   links, contributor guidelines) or translations into any
   language other than English. (Rationale: the README ships in
   the zip too; CI badges and GitHub links are noise in that
   context.)
9. THE Repo_Root_README SHALL NOT duplicate content from
   `skills/*/SKILL.md`. It MAY point at those files in a one-line
   note ("for the LLM-facing skill docs, see `skills/`") but SHALL
   NOT reproduce any skill's workflow. (Rationale: the skills
   target a different audience and have their own lifecycle.)
10. THE Repo_Root_README SHALL NOT reference any file or folder
    under `dev-docs/` (including `dev-docs/sandbox-packages.md`)
    or under `.kiro/`. Those paths are author-only development
    notes, not deliverables for the package user, and linking to
    them from the user-facing README would (a) break after the
    user unzips the deployable (which does not contain
    `dev-docs/` or `.kiro/`) and (b) expose authoring scaffolding
    the user has no reason to read. (Rationale: the audience
    split documented in the Introduction is load-bearing —
    `dev-docs/` is written for the author, not for the user.)

### Requirement R-UR-2: Three SVG Illustrations Under `docs/`

**User Story:** As a human user reading the README, I want to see
the app's data shape, its review-timing concept, and its import flow
as diagrams, so I can form a mental model without reading every
script's source.

#### Acceptance Criteria

1. THE User_Docs_Folder SHALL contain, at minimum, the three files
   in the Illustration_Set: `docs/data-model.svg`,
   `docs/spaced-repetition.svg`, and `docs/import-pipeline.svg`.
2. Every file in the Illustration_Set SHALL be a Valid_SVG.
3. Every file in the Illustration_Set SHALL be a Text_Rendered_SVG:
   every visible caption, axis label, table name, node name, or
   other user-readable string SHALL appear in the file as the text
   content of a `<text>`, `<tspan>`, or `<title>` element, not as a
   `<path>` tracing the shape of glyphs. (Rationale: keeps the
   file small, keeps the text selectable and accessible, and
   avoids depending on a font being installed on the reader's
   machine.)
4. The Data_Model_SVG SHALL depict the six tables from the parent
   spec's schema — `artist`, `song`, `show`, `rel_show_song`,
   `play_history`, `learning` — and the foreign-key relationships
   among them: `song.artist_id → artist.id`, `rel_show_song.song_id
   → song.id`, `rel_show_song.show_id → show.id`,
   `play_history.song_id → song.id`, `play_history.show_id →
   show.id`, and `learning.song_id → song.id`. Arrow direction
   SHALL go from the referencing table to the referenced table.
   Depicting every column is NOT required; tables MAY be drawn as
   labelled boxes.
5. The Spaced_Repetition_SVG SHALL depict the level-up wait-days
   curve from the parent Glossary's `level_up_path` for
   `max_level = 20` — the sequence
   `[1, 1, 1, 1, 1, 1, 1, 2, 3, 5, 7, 13, 19, 32, 52, 84, 135,
   220, 355, 574]` days. Either a growing-bar chart or a
   monotonically-rising curve is acceptable. THE illustration
   SHALL include a short textual annotation of the loop "review →
   level up → wait longer next time" (or equivalent phrasing)
   rendered as `<text>` elements per R-UR-2.3.
6. The Import_Pipeline_SVG SHALL depict the three-step AMQ import
   flow from the parent spec's Requirements 12, 13, and 14:
   - Step 1 box labelled `import_plan.py` producing `plan.json`
     with the three buckets (resolved / auto_completable /
     ambiguous).
   - Operator-filled `answers.json` shown as an input to step 2,
     with a note that it is required only when the plan has
     ambiguous entries.
   - Step 2 box labelled `import_resolve.py` producing
     `triples.json`, with a note that it is idempotent (creates
     missing rows, reuses existing ones).
   - Step 3 box labelled `add_play_history.py` writing to the
     deployed DB (`play_history` and `rel_show_song`).
   - Arrows connecting the steps in order.
7. Every file in the Illustration_Set SHALL be hand-authored (or
   authored with a tool whose output can be freely hand-edited)
   and committed as its final artifact. THIS spec SHALL NOT
   introduce a generator script, a build dependency, or any
   tool that converts another format to SVG at build time.
8. Every file in the Illustration_Set SHALL be referenced from the
   Repo_Root_README per R-UR-1.3.

### Requirement R-UR-3: `docs/` Ships, `dev-docs/` Does Not

**User Story:** As the operator building the deployable zip, I want
the user-facing `docs/` folder to ship alongside the README and
scripts, while the new author-only `dev-docs/` folder stays on the
dev machine, so the zip carries exactly the content a deploy-time
reader would want.

#### Acceptance Criteria

1. `tools/package.py` SHALL copy `docs/` from the repository root
   into the staged zip under the top-level path `docs/`. THE
   implementation SHALL follow the same pattern
   `_copy_scripts` / `_copy_skills` already use: a `_copy_docs`
   helper that calls `shutil.copytree` with the existing
   `_SKIP_DIR_NAMES` ignore filter applied, invoked from `main()`
   before the zip step. The helper SHALL no-op cleanly when the
   `docs/` directory is absent (mirroring `_copy_skills`).
2. THE top-level directories copied into the deployable zip SHALL
   be exactly `{scripts/, skills/, docs/, db/}`. THE top-level
   files copied SHALL be exactly the subset of `{Makefile,
   README.md}` that exists at the repo root. No other top-level
   entries SHALL appear in the zip.
3. THE packaging command SHALL print a summary line for `docs/`
   alongside the existing lines for `scripts/` and `skills/`. The
   line MAY report a count (e.g. `".svg files + .md files"`) or
   simply a total file count; the spec does not fix the exact
   wording, only that the line exists so a reader running
   `make package` can see that `docs/` was included.
4. THE Author_Docs_Folder (`dev-docs/`) SHALL NOT appear in the
   deployable zip. This SHALL be true by construction — i.e. by
   not adding `dev-docs` to the copy list in `tools/package.py` —
   rather than by filename blacklisting. (Rationale: matches the
   `review-html-enhancements` R-RH-7.4 exclusion-by-construction
   treatment of `.kiro/`.)
5. THE `tools/package.py` module docstring SHALL explicitly name
   `docs/` as a top-level directory that IS copied into the zip,
   SHALL explicitly name `dev-docs/` as a top-level directory
   that is NOT copied (by construction), and SHALL keep the
   existing naming of `.kiro/` as a by-construction exclusion.
   (Rationale: extends the two-layer exclusion model documentation
   introduced by `review-html-enhancements` R-RH-7.4.)
6. THE existing `_SKIP_DIR_NAMES` defense-in-depth filter SHALL
   apply inside the copied `docs/` tree too, i.e. if a cache
   directory (e.g. `__pycache__`, `.mypy_cache`) somehow ends up
   nested inside `docs/` at packaging time, it SHALL still be
   excluded. (Rationale: unlikely in practice — `docs/` is a
   text/SVG folder — but the filter is cheap and the existing
   tests rely on it being applied uniformly.)
7. THE existing integration test
   `tests/integration/property/test_package_exclusion_property.py`
   SHALL be updated so that:
   - `_ALLOWED_TOP_LEVEL` includes `"docs"` alongside
     `"scripts"`, `"skills"`, `"db"`, `"Makefile"`, and
     `"README.md"`.
   - `_EXCLUDED_PATH_PREFIXES` drops `"docs/"` (since `docs/` now
     ships) and adds `"dev-docs/"` (which does not).
   - The synthetic-repo seed function additionally creates a
     `dev-docs/` directory with a stub Markdown file, so the
     test actively exercises the new exclusion.
   - The synthetic-repo seed function additionally creates a
     `docs/` directory with at least one stub SVG file, and the
     test asserts that at least one `docs/` entry appears in the
     resulting zip.
   The test SHALL still be a single property test (no duplicate
   test file); extending it in place is the intent.

### Requirement R-UR-4: `sandbox-packages.md` Relocation

**User Story:** As the author, I want the one existing author-only
document (`sandbox-packages.md`) to live in the new `dev-docs/`
folder alongside any future author-only docs, and I want every
cross-reference to the old path to point at the new one, so nothing
breaks silently.

#### Acceptance Criteria

1. THE file at `docs/sandbox-packages.md` SHALL be moved to
   `dev-docs/sandbox-packages.md`. The file's content SHALL be
   preserved byte-for-byte except that Markdown links or prose
   mentions inside the document itself that refer to its own old
   path SHALL be updated to reflect the new path (if any such
   self-references exist). An in-document line mentioning
   "`docs/sandbox-packages.md`" is acceptable to keep as historical
   narrative only if the document makes clear it is describing the
   old location; otherwise it is updated.
2. `.kiro/specs/anime-song-learning-app/requirements.md` SHALL have
   its References section updated so that the Markdown link and
   surrounding prose point at `dev-docs/sandbox-packages.md`
   instead of `docs/sandbox-packages.md`.
3. `.kiro/specs/anime-song-learning-app/design.md` SHALL have its
   reference to `docs/sandbox-packages.md` (in the Introduction /
   Overview) updated to `dev-docs/sandbox-packages.md`.
4. `.kiro/specs/anime-song-learning-app/tasks.md` SHALL have its
   references to `docs/sandbox-packages.md` (in the Testing Notes
   / Intro sections) updated to `dev-docs/sandbox-packages.md`.
5. WHERE `tools/package.py`'s module docstring, comments, or log
   output mention the old location `docs/sandbox-packages.md`, it
   SHALL be updated to the new location. (In the current repo the
   docstring does not name the file by path; criterion applies
   only if such a reference exists at implementation time.)
6. AFTER the move, repo-wide search for the substring
   `docs/sandbox-packages` SHALL return zero matches outside of
   historical changelog entries (the repo has no such changelog,
   so in practice this means zero matches). Repo-wide search for
   the substring `dev-docs/sandbox-packages` SHALL return at least
   the matches required by criteria 2–4 above.

### Requirement R-UR-5: LLM-Facing `skills/README.md` Intro

**User Story:** As an AI agent handed this deployed tree with a
plain-English user request, I want the `skills/README.md` to frame
the library by common workflows so I can pick the right skill to
consult without having to open all six and read them.

#### Acceptance Criteria

1. THE file at `skills/README.md` SHALL be rewritten to begin
   with a short "what this app does" paragraph written for an AI
   agent, naming the three kinds of work the app does (querying,
   spaced-repetition learning, data management) in the same shape
   the Repo_Root_README's "What this app is" section uses. The
   paragraph SHALL be at most 6 lines.
2. AFTER the framing paragraph and BEFORE the existing skills
   table, the file SHALL contain a "Common Workflows" section
   organised by user intent, not by script name. THE section
   SHALL cover, at minimum, these four workflow groups in this
   order:
   1. **Adding entries to the library** — covers importing an AMQ
      JSON dump (points at `importing-amq-songs`), building the
      review queue (points at `adding-songs-to-learning` for new
      or re-learn cases).
   2. **Memorising songs** — covers the review loop: running a
      session (points at `reviewing-songs`), levelling up or
      graduating each song at the end of a session. The group
      SHALL briefly note that wait days grow with each level-up,
      pointing at Repo_Root_README's spaced-repetition illustration
      as the visual (do not duplicate the illustration in
      `skills/README.md`).
   3. **Exploring the library** — covers read-only searches,
      duplicate detection, show/artist cross-references (points
      at `searching-library`).
   4. **Advanced data management** — covers merging duplicate
      artists (points at `merging-artists`) and hard-deleting
      stale soft-deleted rows (points at
      `cleaning-up-dead-records`).
3. Each workflow group SHALL name the relevant skill(s) as
   Markdown links (`[skill-name](skill-name/SKILL.md)`), not as
   plain text, so an LLM walking the tree can follow the link
   directly to the SKILL.md body.
4. THE existing skills table SHALL be preserved after the
   Common Workflows section as a quick index. Its current
   content (names, one-line descriptions, links) stays as-is
   unless a workflow-group rewrite would leave the table text
   out of date — in which case both update together.
5. THE existing note about stdlib-only runtime and the DB path
   SHALL be preserved. THE existing note about
   `python scripts/init_db.py` being the first call of every
   skill SHALL be preserved.
6. THE rewritten `skills/README.md` SHALL NOT duplicate any
   SKILL.md body. It points; it does not reproduce. (Same
   rationale as R-UR-1.9 for the Repo_Root_README.)
7. THE file SHALL stay at or under 120 lines total. (Rationale:
   it is an index, not a manual. Workflows get one short
   paragraph each, not a full tutorial.)
8. THE rewritten `skills/README.md` SHALL remain LLM-facing.
   It SHALL NOT try to double as human-user documentation. The
   Repo_Root_README is the human's landing page; this file is
   the LLM's.

## Correctness Properties for Property-Based Testing

These properties extend the `anime-song-learning-app` spec's
"Correctness Properties" section and the
`review-html-enhancements` spec's P-RH-5 (packaging allowlist).
Tests follow the parent R18 rules: temp working directories per
test, stdlib `random.Random(seed)` with a fixed seed (no
`hypothesis`), and integration tests drive `tools/package.py` via
`subprocess.run`.

The README and the three SVGs under `docs/` are static
hand-authored artifacts verified by eyeball in a browser, not by
automated tests. R-UR-1's image-link rules and R-UR-2's
Valid_SVG / Text_Rendered_SVG rules are still requirements on the
author — they just aren't mechanically asserted. (If the set of
illustrations or the README grow large enough that eyeball
verification becomes unwieldy, a future spec can re-add a walker;
this spec keeps the test surface minimal.)

### Property P-UR-1: README Image Link Integrity

Author-side review only. See the note above.

### Property P-UR-2: SVG Validity

Author-side review only. See the note above.

### Property P-UR-3: `docs/` Ships and `dev-docs/` Does Not

Extension of the existing `review-html-enhancements` P-RH-5
(property test
`tests/integration/property/test_package_exclusion_property.py`).
For each iteration of the existing synthetic-repo loop:

1. In addition to the existing synthetic top-level paths, the seed
   function creates `docs/` with a stub `docs/diagram-<i>.svg`
   file and creates `dev-docs/` with a stub
   `dev-docs/notes-<i>.md` file.
2. Run `tools/package.py` against the synthetic root.
3. Assert the resulting zip contains at least one entry whose path
   starts with `docs/` (the user-facing docs ship).
4. Assert the resulting zip contains zero entries whose path
   starts with `dev-docs/` (author docs do not).
5. Assert the zip's top-level path set is a subset of
   `{scripts/, skills/, docs/, db/, Makefile, README.md}` — the
   same allowlist P-RH-5.3 enforces, amended to include `docs/`
   and nothing else new. `dev-docs/` is therefore excluded from
   this allowlist, which is what makes criterion 4 hold.

This property extends P-RH-5 in place rather than duplicating it.

### Property P-UR-4: README Ships In Zip

For each iteration of the same synthetic-repo loop as P-UR-3:

1. The synthetic repo already contains a `README.md` at the root
   (P-RH-5's existing seed writes `"synthetic"` there).
2. Run `tools/package.py` against the synthetic root.
3. Assert the resulting zip contains exactly one entry whose name
   is `README.md` at the top level (no subpath prefix).

This is already implicit in P-RH-5's current allowlist assertion
(`README.md` is allowed at top level), but after this spec lands
the README ships unconditionally rather than being a
"when present" concession. Making the assertion explicit keeps a
regression that silently stops copying `README.md` from passing
the top-level-subset check.

### Property P-UR-5: Allowed Top-Level Path Set Is Exactly What This Spec Defines

For each iteration of the same synthetic-repo loop as P-UR-3 (or,
equivalently, the real repo's packaging output in a separate
smoke check):

1. Enumerate the set of top-level segments in the zip: for every
   entry `e` in the zip's namelist, let
   `top = e.split('/', 1)[0]`.
2. Assert this set is a subset of
   `{scripts, skills, docs, db, Makefile, README.md}`.
3. Assert every element of `{scripts, skills, docs, db}` that the
   synthetic root supplied non-empty is present in the zip.
4. Assert every element of `{Makefile, README.md}` that the
   synthetic root supplied is present in the zip.

P-RH-5.3's existing assertion already enforces the subset half of
this; P-UR-5 is the same property after this spec adds `docs/`.
It is called out as its own property because it is the single
structural invariant that `review-html-enhancements` R-RH-7.2
plus this spec's R-UR-3.2 together establish — spelling it out
makes a regression in either direction (a new top-level directory
sneaking in, or `docs/` silently disappearing) trip a named test.

## Out of Scope for This Spec

The following are explicitly NOT part of this feature. If any of
them becomes desirable later, they need a new spec.

1. **No changes to `skills/*/SKILL.md`.** R-UR-5 rewrites
   `skills/README.md` into a workflow-oriented LLM landing page,
   but the six individual `SKILL.md` files stay as they are.
   Their content is load-bearing for Claude's skill system and
   out of scope for this spec.
2. **No new runtime scripts.** `scripts/init_db.py`, `scripts/review.py`,
   and every other runtime Script are untouched by this spec. The
   parent R1.2 stdlib-only rule is reaffirmed by omission.
3. **No image-generation tooling dependency.** Every SVG in the
   Illustration_Set is hand-authored and committed as a final
   artifact. No generator script, no build-time `dot`, `mermaid`,
   `graphviz`, or `manim` dependency is introduced.
4. **No `Makefile` changes beyond what the packager genuinely
   requires.** The most likely answer is "no changes at all" —
   `make package` already runs `python3 tools/package.py`, which
   picks up the new `docs/` copy step automatically. If a schema
   or target actually breaks without a Makefile edit, the
   implementer makes the smallest edit needed; this spec does not
   authorise broader Makefile rework.
5. **No translation or internationalisation of the
   Repo_Root_README.** English only.
6. **No GitHub-specific README chrome.** No CI badges, no status
   shields, no contributor-guideline sections, no issue / PR
   templates. (Re-stated from R-UR-1.8 for emphasis — the README
   ships in the zip, and every one of those lines is noise on
   the deploy target.)
7. **No other author-only docs besides `sandbox-packages.md`.**
   `dev-docs/` starts its life with exactly one file. Populating
   it further is left to future specs.
8. **No changes to the exclusion model beyond the copy-list
   extension.** `_SKIP_DIR_NAMES` keeps exactly its current
   membership; `_EXTRA_TOP_LEVEL` keeps exactly its current
   membership. The only structural change in `tools/package.py`
   is the addition of `_copy_docs` and its call site, plus the
   docstring updates required by R-UR-3.5.
9. **No README-side documentation of the schema columns or SQL
   timing details.** The Data_Model_SVG shows shape; the
   Spaced_Repetition_SVG shows concept. Exact columns and SQL live
   in the parent spec's Requirements and Glossary, and the README
   points readers there rather than duplicating the content.
