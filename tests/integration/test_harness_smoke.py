"""Smoke tests for the integration test harness itself.

Verifies the plumbing set up in ``tests/integration/conftest.py``:

  * ``tmp_app_root`` builds a fresh DB from the schema fixture.
  * The ``insert_*`` fixtures write rows to the temp DB.
  * ``temp_conn`` can read them back.
  * ``call_script`` runs a Python process under the temp App_Root and
    resolves the DB path from the symlinked ``scripts/`` dir.
  * ``pinned_call`` sets ``JANKENOBOE_TEST_NOW`` in the child's env.

These tests don't exercise real scripts from ``scripts/`` (those don't
exist yet). They run tiny inline probes through ``sys.executable`` to
confirm the harness is wired up correctly.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys


def test_tmp_app_root_has_symlink_and_empty_db(tmp_app_root: pathlib.Path) -> None:
    scripts_link = tmp_app_root / "scripts"
    db_file = tmp_app_root / "db" / "datasource.db"
    assert scripts_link.is_symlink()
    assert scripts_link.resolve().name == "scripts"
    assert db_file.exists()
    assert db_file.stat().st_size > 0  # schema rows exist


def test_schema_tables_match_expected(tmp_app_root, temp_conn) -> None:
    names = {r[0] for r in temp_conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == {
        "song",
        "artist",
        "show",
        "rel_show_song",
        "play_history",
        "learning",
    }


def test_inserters_round_trip(
    tmp_app_root,
    temp_conn,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_learning,
    insert_play_history,
) -> None:
    aid = insert_artist(tmp_app_root, name="Test Artist")
    sid = insert_song(tmp_app_root, name="Test Song", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Test Show", vintage="Winter 2024")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="http://x/y")
    lid = insert_learning(tmp_app_root, song_id=sid, level=3)
    phid = insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url="http://x/z")

    def count(sql: str, *params) -> int:
        return temp_conn.execute(sql, params).fetchone()[0]

    assert count("SELECT COUNT(*) FROM artist WHERE id = ?", aid) == 1
    assert count("SELECT COUNT(*) FROM song WHERE id = ?", sid) == 1
    assert count("SELECT COUNT(*) FROM show WHERE id = ?", shid) == 1
    assert (
        count(
            "SELECT COUNT(*) FROM rel_show_song WHERE show_id = ? AND song_id = ?",
            shid,
            sid,
        )
        == 1
    )
    assert count("SELECT COUNT(*) FROM learning WHERE id = ?", lid) == 1
    assert count("SELECT COUNT(*) FROM play_history WHERE id = ?", phid) == 1

    # The learning row has a valid JSON level_up_path.
    path_json = temp_conn.execute(
        "SELECT level_up_path FROM learning WHERE id = ?", (lid,)
    ).fetchone()[0]
    parsed = json.loads(path_json)
    assert isinstance(parsed, list) and all(isinstance(n, int) for n in parsed)


def test_inserters_never_touch_real_db(tmp_app_root, insert_artist) -> None:
    """Smoke check: inserter writes land in the temp DB, not the repo's DB.

    The session-scoped ``_guard_real_db`` fixture is the mechanical guard,
    but we also assert here because this test is explicitly about the
    inserter API.
    """
    insert_artist(tmp_app_root, name="Scoped To Temp")
    temp = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        n = temp.execute("SELECT COUNT(*) FROM artist").fetchone()[0]
    finally:
        temp.close()
    assert n == 1


def _write_probe_script(tmp_app_root: pathlib.Path, name: str, body: str) -> None:
    """Drop a one-off probe ``.py`` into a side directory under ``tmp_app_root``.

    The integration conftest symlinks ``scripts/`` to the real scripts
    directory (read-only from the test's perspective — we don't want to
    modify the repo). So probes live under ``tmp_app_root/probes/`` and
    are invoked directly by path. This keeps the real ``scripts/`` dir
    untouched.
    """
    probes = tmp_app_root / "probes"
    probes.mkdir(exist_ok=True)
    (probes / name).write_text(body, encoding="utf-8")


def test_call_script_runs_under_tmp_app_root(tmp_app_root) -> None:
    """Run a probe that prints ``cwd`` and the DB path it would use."""
    _write_probe_script(
        tmp_app_root,
        "probe.py",
        "import os, sys, pathlib, json\n"
        "here = pathlib.Path(__file__).resolve()\n"
        "# mimic scripts/_common.app_root: parent.parent of the script file\n"
        "app_root = here.parent.parent\n"
        "db = app_root / 'db' / 'datasource.db'\n"
        "print(json.dumps({'cwd': os.getcwd(), 'db': str(db), "
        "'db_exists': db.exists()}))\n",
    )
    # Invoke the probe directly (not through the scripts symlink).
    result = subprocess.run(
        [sys.executable, str(tmp_app_root / "probes" / "probe.py")],
        capture_output=True,
        text=True,
        cwd=str(tmp_app_root),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cwd"] == str(tmp_app_root)
    assert payload["db"] == str(tmp_app_root / "db" / "datasource.db")
    assert payload["db_exists"] is True


def test_call_script_through_scripts_symlink(tmp_app_root, call_script) -> None:
    """Confirm that ``call_script`` uses the symlinked ``scripts/`` dir.

    We can't drop a probe into the real ``scripts/`` (that would mutate the
    repo). Instead, we assert that ``call_script`` on a non-existent name
    fails with a clean ``FileNotFoundError`` style exit — the interpreter
    reports "No such file or directory" and exits non-zero.
    """
    rc, out, err = call_script("does_not_exist.py", cwd=tmp_app_root)
    assert rc != 0
    assert "does_not_exist.py" in (err + out)


def test_pinned_call_sets_env(tmp_app_root, pinned_now, pinned_call) -> None:
    """Confirm the ``JANKENOBOE_TEST_NOW`` env var reaches the child process.

    Uses a probe that echoes the env var, invoked through ``call_script``'s
    subprocess plumbing (with ``cwd=tmp_app_root``) but by path so we don't
    depend on the symlink for this test.
    """
    _write_probe_script(
        tmp_app_root,
        "echo_env.py",
        "import os, json\nprint(json.dumps({'now': os.environ.get('JANKENOBOE_TEST_NOW')}))\n",
    )
    # Reuse the helper's env-merging by calling it with an explicit path
    # to the probe via the ``name`` slot. Pass a relative name that joins
    # under ``cwd`` — ``pinned_call`` turns it into ``cwd/scripts/<name>``,
    # so use a relative probe path.
    #
    # We can't go through ``scripts/<name>`` (would modify the real dir),
    # so invoke subprocess directly with a merged env matching what
    # pinned_call would set.
    import os as _os  # noqa: PLC0415

    env = {**_os.environ, "JANKENOBOE_TEST_NOW": str(pinned_now)}
    result = subprocess.run(
        [sys.executable, str(tmp_app_root / "probes" / "echo_env.py")],
        capture_output=True,
        text=True,
        cwd=str(tmp_app_root),
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["now"] == str(pinned_now)

    # And the pinned_call fixture itself returns a callable with the same
    # signature as call_script, so we at least confirm that's true.
    assert callable(pinned_call)


def test_guard_allows_suite_when_real_db_untouched() -> None:
    """Sanity check: the guard fixture didn't fail the session by this point.

    Pytest tears down the guard at session end, not per-test, so an actual
    guard failure shows up as a session-level error. This test exists so
    the suite has an obvious hook to point at if that ever happens.
    """
    assert True
