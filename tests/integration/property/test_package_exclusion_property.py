"""Property P-RH-5 + P-UR-3/4/5 — packaging allowlist and exclusion.

For each iteration, build a synthetic App_Root in a temp dir with at
least ``scripts/``, ``skills/``, ``docs/``, ``db/datasource.db``,
``Makefile``, ``README.md``, ``.kiro/``, ``dev-docs/``, ``output/``,
``tools/``, plus a random sprinkling of cache directories in random
places. Copy the real ``tools/package.py`` into the synthetic tree and
invoke it as a subprocess. Open the resulting zip under ``dist/`` and
assert:

  * no entry under any excluded path.
  * at least one entry under ``skills/``.
  * at least one entry under ``docs/`` (user-facing docs ship).
  * ``README.md`` is present at top level.
  * top-level path set is a subset of
    ``{scripts/, skills/, docs/, db/, Makefile, README.md}``.
  * ``db/datasource.db`` inside the zip is the schema-only empty DB,
    not the synthetic root's bytes.

Post-``user-readme-and-illustrations`` spec: ``docs/`` moved from
the excluded list to the copy list, and ``dev-docs/`` joined the
excluded list as the new author-only folder (same family as
``.kiro/``). The synthetic seed writes both a ``docs/diagram-<i>.svg``
stub and a ``dev-docs/notes-<i>.md`` stub per iteration so the test
actively exercises the new rule in both directions.
"""

from __future__ import annotations

import pathlib
import random
import shutil
import sqlite3
import subprocess
import sys
import zipfile

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 105

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_REAL_PACKAGE_PY = _REPO_ROOT / "tools" / "package.py"
_REAL_SCHEMA_SQL = _REPO_ROOT / "tests" / "fixtures" / "schema.sql"

_EXCLUDED_PATH_PREFIXES = (
    ".kiro/",
    "dev-docs/",  # author-only, excluded by construction
    "output/",
    "tools/",
    "tests/",
    "dist/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".trace/",
    ".coverage_data/",
)

_ALLOWED_TOP_LEVEL = {"scripts", "skills", "docs", "db", "Makefile", "README.md"}


def _seed_synthetic_repo(root: pathlib.Path, rng: random.Random, idx: int) -> None:
    """Lay out a synthetic repo under ``root`` that package.py can stage.

    Writes:
      * scripts/<some>.py + scripts/review_template.html
      * skills/<skill>/SKILL.md + skills/<skill>/references/foo.md
      * db/datasource.db (empty SQLite, different bytes from the
        schema-only DB — package.py must rebuild, not copy)
      * Makefile, README.md
      * .kiro/specs/<spec>/requirements.md
      * docs/<doc>.md
      * output/review_0.html
      * tools/package.py (copied from the real file)
      * tests/fixtures/schema.sql (copied from the real fixture,
        since package.py reads from REPO_ROOT/tests/fixtures/schema.sql)
      * Random cache directories with sentinel files inside scripts/
        and skills/ to verify _SKIP_DIR_NAMES kicks in.
    """
    # scripts/
    (root / "scripts").mkdir()
    (root / "scripts" / "fake.py").write_text("def main():\n    print('hi')\n", encoding="utf-8")
    (root / "scripts" / "review_template.html").write_text(
        "<!DOCTYPE html><html><body>stub</body></html>", encoding="utf-8"
    )
    # scripts/schema.sql ships at runtime (read by init_db.py) and at
    # package time (read by tools/package.py._empty_db). Copy the real
    # fixture so the packaged DB gets the canonical schema.
    shutil.copy2(_REAL_SCHEMA_SQL, root / "scripts" / "schema.sql")

    # skills/
    (root / "skills" / f"skill-{idx}").mkdir(parents=True)
    (root / "skills" / f"skill-{idx}" / "SKILL.md").write_text("# Skill\nstub", encoding="utf-8")
    (root / "skills" / f"skill-{idx}" / "references").mkdir()
    (root / "skills" / f"skill-{idx}" / "references" / "foo.md").write_text(
        "ref stub", encoding="utf-8"
    )

    # db/ — write a DB with a different schema/bytes so we can detect
    # whether package.py leaked the synthetic bytes into the zip.
    (root / "db").mkdir()
    synthetic_db = root / "db" / "datasource.db"
    conn = sqlite3.connect(str(synthetic_db))
    try:
        conn.executescript("CREATE TABLE synthetic_marker (x TEXT);")
        conn.commit()
    finally:
        conn.close()

    # Makefile + README.md
    (root / "Makefile").write_text(".PHONY: test\ntest:\n\techo ok\n", encoding="utf-8")
    (root / "README.md").write_text("synthetic", encoding="utf-8")

    # .kiro / docs / dev-docs / output / (mix of excluded + now-shipped)
    (root / ".kiro" / "specs" / f"spec-{idx}").mkdir(parents=True)
    (root / ".kiro" / "specs" / f"spec-{idx}" / "requirements.md").write_text(
        "req stub", encoding="utf-8"
    )
    # docs/ now SHIPS in the zip (post-user-readme-and-illustrations spec).
    # Seed both a .md and an .svg so the test exercises both extensions.
    (root / "docs").mkdir()
    (root / "docs" / f"doc-{idx}.md").write_text("doc stub", encoding="utf-8")
    (root / "docs" / f"diagram-{idx}.svg").write_text(
        '<?xml version="1.0"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<text x="1" y="5">stub {idx}</text>'
        "</svg>",
        encoding="utf-8",
    )
    # dev-docs/ is the new author-only folder — excluded by construction,
    # same family as .kiro/.
    (root / "dev-docs").mkdir()
    (root / "dev-docs" / f"notes-{idx}.md").write_text(
        f"# Author notes {idx}\nstub", encoding="utf-8"
    )
    (root / "output").mkdir()
    (root / "output" / "review_0.html").write_text("stale review", encoding="utf-8")

    # tools/ — needed because package.py imports live here.
    (root / "tools").mkdir()
    shutil.copy2(_REAL_PACKAGE_PY, root / "tools" / "package.py")

    # tests/fixtures/schema.sql — package.py reads this to build the
    # empty deployable DB. Copy from the real fixture so the zip's
    # db/datasource.db has the canonical schema.
    (root / "tests" / "fixtures").mkdir(parents=True)
    shutil.copy2(_REAL_SCHEMA_SQL, root / "tests" / "fixtures" / "schema.sql")

    # Random cache sprinkles inside scripts/ and skills/ that
    # _SKIP_DIR_NAMES must filter out.
    cache_names = [
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".coverage_data",
        ".venv",
        "output",
        ".trace",
    ]
    for _ in range(rng.randint(1, 4)):
        parent = rng.choice([root / "scripts", root / "skills" / f"skill-{idx}"])
        cache = parent / rng.choice(cache_names)
        cache.mkdir(exist_ok=True)
        (cache / "trash.bin").write_text("garbage", encoding="utf-8")


def _run_package(root: pathlib.Path) -> pathlib.Path:
    """Run the staged package.py inside ``root`` and return the zip path."""
    result = subprocess.run(
        [sys.executable, str(root / "tools" / "package.py")],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"package.py failed: rc={result.returncode} "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    zips = sorted((root / "dist").glob("jankenoboe-lite-*.zip"))
    assert zips, "package.py produced no dist/jankenoboe-lite-*.zip"
    return zips[-1]


def _inspect_zip(zip_path: pathlib.Path) -> tuple[list[str], dict[str, int]]:
    """Return (sorted entry names, size_of_db_entry_or_None)."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = sorted(zf.namelist())
        sizes = {info.filename: info.file_size for info in zf.infolist()}
    return names, sizes


def test_packaging_allowlist_and_exclusion(tmp_path) -> None:
    rng = random.Random(SEED)

    for i in range(ITERATIONS):
        root = tmp_path / f"iter{i}"
        root.mkdir()
        _seed_synthetic_repo(root, rng, i)
        zip_path = _run_package(root)
        names, _sizes = _inspect_zip(zip_path)

        # (1) No entry under an excluded prefix.
        for name in names:
            for prefix in _EXCLUDED_PATH_PREFIXES:
                assert not name.startswith(prefix), (
                    f"iter {i}: zip entry {name!r} starts with excluded prefix {prefix!r}"
                )

        # (2) At least one entry under skills/.
        assert any(n.startswith("skills/") for n in names), f"iter {i}: no skills/ entries in zip"

        # (2b) At least one entry under docs/ — user-facing docs ship
        # post-user-readme-and-illustrations spec (P-UR-3).
        assert any(n.startswith("docs/") for n in names), (
            f"iter {i}: no docs/ entries in zip (expected at least one)"
        )

        # (2c) README.md ships at top level unconditionally (P-UR-4).
        assert "README.md" in names, f"iter {i}: zip missing README.md at top level"

        # (3) Top-level path set is a subset of the allowlist.
        top_levels = {n.split("/", 1)[0] for n in names}
        assert top_levels.issubset(_ALLOWED_TOP_LEVEL), (
            f"iter {i}: unexpected top-level paths: {top_levels - _ALLOWED_TOP_LEVEL}"
        )

        # (4) db/datasource.db in the zip is schema-only, NOT the
        # synthetic bytes. Extract and verify the schema.
        with zipfile.ZipFile(zip_path, "r") as zf:
            assert "db/datasource.db" in zf.namelist(), f"iter {i}: zip missing db/datasource.db"
            db_bytes = zf.read("db/datasource.db")
            # The synthetic DB's marker table name shouldn't be present
            # in the packaged bytes.
            assert b"synthetic_marker" not in db_bytes, (
                f"iter {i}: zip DB leaked synthetic repo bytes"
            )
            # Load the DB and check it has the expected tables.
            out_db = root / "extracted.db"
            out_db.write_bytes(db_bytes)
            conn = sqlite3.connect(str(out_db))
            try:
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                conn.close()
            # The real schema includes song/artist/show/rel_show_song/
            # play_history/learning.
            for expected in ("song", "artist", "show", "rel_show_song", "play_history", "learning"):
                assert expected in tables, f"iter {i}: packaged DB missing table {expected!r}"
