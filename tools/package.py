"""Build a deployable zip for this app.

Produces ``dist/jankenoboe-lite-<YYYYMMDD>.zip`` containing:

  * ``scripts/`` — runtime Python files (stdlib only)
  * ``skills/`` — Claude skill docs that ship with the deployed tree
  * ``docs/`` — user-facing illustrations (SVG) + shipped human docs
  * ``db/datasource.db`` — a fresh, empty DB built from
    ``tests/fixtures/schema.sql``
  * ``Makefile`` — so the user can run ``make test`` or ``make clean``
    in the dropped-in tree (runtime-friendly targets only)
  * ``README.md`` — if present at the repo root

Exclusion model (two layers):

  1. **Inclusion by enumeration.** Top-level directories not on the
     copy list — ``.kiro/`` (the author's hidden spec folder),
     ``dev-docs/`` (author-only development notes, same family as
     ``.kiro/``), ``tests/``, ``tools/``, ``dist/``, ``.venv/``,
     ``venv/``, ``output/`` — are excluded because this module never
     hands them to ``shutil.copytree``. ``.kiro/`` and ``dev-docs/``
     in particular are dev-only folders that stay on the author's
     machine by nature; nothing in their trees ships to the deploy
     target.

  2. **Defense-in-depth.** ``_SKIP_DIR_NAMES`` is a safety net
     applied inside every directory that *is* copied (``scripts/``,
     ``skills/``, ``docs/``). If a cache folder or a build artifact
     (``__pycache__``, ``.pytest_cache``, ``.ruff_cache``,
     ``.mypy_cache``, ``.coverage_data``, ``.venv``, ``venv``,
     ``output``, ``.trace``) somehow ends up nested inside one of
     those trees at packaging time, it is still kept out of the
     zip. ``_SKIP_DIR_NAMES`` is not the sole exclusion mechanism —
     it's a second layer behind the enumerated copy list.

Usage::

    python tools/package.py

Stdlib only — on purpose. The packaging path shouldn't rely on
anything beyond what the runtime uses.
"""

from __future__ import annotations

import datetime
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import zipfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SKILLS_DIR = REPO_ROOT / "skills"
DOCS_DIR = REPO_ROOT / "docs"
# Runtime source of truth for the schema DDL — the same file
# ``scripts/init_db.py`` reads on the create path. Kept byte-identical
# to ``tests/fixtures/schema.sql`` by ``make schema-sync``.
_SCHEMA_AT_SCRIPTS = REPO_ROOT / "scripts" / "schema.sql"
DIST_DIR = REPO_ROOT / "dist"

# Extra top-level files that ship alongside the zip, if they exist.
_EXTRA_TOP_LEVEL = ("Makefile", "README.md")

# Defense-in-depth filter. Directories whose names appear here are
# skipped inside any copied tree even though the top-level layout
# should never include them. See the "Exclusion model" section of
# the module docstring above.
_SKIP_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".coverage_data",
    ".venv",
    "venv",
    "output",
    ".trace",
}


def _stamp() -> str:
    """UTC-dated stamp: ``YYYYMMDD``."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")


def _empty_db(path: pathlib.Path) -> None:
    """Create an empty ``datasource.db`` at ``path`` from the schema source."""
    if not _SCHEMA_AT_SCRIPTS.exists():
        print(
            f"error: schema file missing at {_SCHEMA_AT_SCRIPTS}. Run `make schema-sync` first.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    ddl = _SCHEMA_AT_SCRIPTS.read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


def _copy_scripts(dest: pathlib.Path) -> None:
    """Copy ``scripts/`` into ``dest/scripts/``, skipping caches."""
    shutil.copytree(
        SCRIPTS_DIR,
        dest / "scripts",
        ignore=shutil.ignore_patterns(*_SKIP_DIR_NAMES, "*.pyc"),
    )


def _copy_skills(dest: pathlib.Path) -> None:
    """Copy ``skills/`` into ``dest/skills/``, skipping caches.

    No-ops cleanly when ``skills/`` does not exist — the tree is
    optional even though the current repo always ships it.
    """
    if not SKILLS_DIR.exists():
        return
    shutil.copytree(
        SKILLS_DIR,
        dest / "skills",
        ignore=shutil.ignore_patterns(*_SKIP_DIR_NAMES, "*.pyc"),
    )


def _copy_docs(dest: pathlib.Path) -> None:
    """Copy ``docs/`` into ``dest/docs/``, skipping caches.

    No-ops cleanly when ``docs/`` does not exist — the tree is
    optional even though the current repo always ships it. Holds
    the user-facing SVG illustrations referenced from ``README.md``
    plus any other shipped human-facing docs.
    """
    if not DOCS_DIR.exists():
        return
    shutil.copytree(
        DOCS_DIR,
        dest / "docs",
        ignore=shutil.ignore_patterns(*_SKIP_DIR_NAMES, "*.pyc"),
    )


def _copy_extras(dest: pathlib.Path) -> list[str]:
    """Copy optional top-level files. Returns the names actually included."""
    included: list[str] = []
    for name in _EXTRA_TOP_LEVEL:
        src = REPO_ROOT / name
        if src.exists() and src.is_file():
            shutil.copy2(src, dest / name)
            included.append(name)
    return included


def _zip_dir(src_dir: pathlib.Path, zip_path: pathlib.Path) -> None:
    """Zip everything under ``src_dir`` into ``zip_path``.

    Paths inside the archive are relative to ``src_dir`` so the user
    can unzip directly into a new App_Root.
    """
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(src_dir)
            # Defense in depth — keep the exclude list enforced on the
            # already-filtered tree.
            if any(part in _SKIP_DIR_NAMES for part in rel.parts):
                continue
            zf.write(path, arcname=str(rel))


def main() -> int:
    if not SCRIPTS_DIR.exists():
        print(f"error: {SCRIPTS_DIR} missing", file=sys.stderr)
        return 2

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    zip_name = f"jankenoboe-lite-{_stamp()}.zip"
    zip_path = DIST_DIR / zip_name

    # Build the tree in a temp staging area, then zip. That way the
    # result is atomic and the script leaves no half-state behind.
    with tempfile.TemporaryDirectory() as staging_str:
        staging = pathlib.Path(staging_str)
        _copy_scripts(staging)
        _copy_skills(staging)
        _copy_docs(staging)
        _empty_db(staging / "db" / "datasource.db")
        included_extras = _copy_extras(staging)
        _zip_dir(staging, zip_path)

    print(f"Wrote {zip_path.relative_to(REPO_ROOT)}")
    print(f"  - scripts/ ({sum(1 for _ in SCRIPTS_DIR.rglob('*.py'))} .py files)")
    if SKILLS_DIR.exists():
        print(f"  - skills/  ({sum(1 for _ in SKILLS_DIR.rglob('*.md'))} .md files)")
    if DOCS_DIR.exists():
        n_svg = sum(1 for _ in DOCS_DIR.rglob("*.svg"))
        n_md = sum(1 for _ in DOCS_DIR.rglob("*.md"))
        print(f"  - docs/    ({n_svg} .svg files, {n_md} .md files)")
    print("  - db/datasource.db (empty, schema only)")
    for name in included_extras:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
