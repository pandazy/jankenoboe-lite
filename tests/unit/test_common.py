"""Unit tests for scripts/_common.py helpers.

Covers the non-DB plumbing: URL decoding, the time seam, JSON envelopes,
the top-level `run` wrapper, UUID shape, and schema checking.

Run with: `pytest tests/unit/test_common.py` (or via `make test`).
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from scripts import _common as m

# ---------------------------------------------------------------------------
# URL decoding: decode_term, decode_data, parse_data_arg
# ---------------------------------------------------------------------------


def test_decode_term_plain_string_passthrough():
    assert m.decode_term("hello") == "hello"


def test_decode_term_single_decode_once():
    # %20 is a literal space encoded once. A second pass would turn
    # '%2520' into ' ' — we explicitly want only ONE pass.
    assert m.decode_term("hello%20world") == "hello world"
    assert m.decode_term("%2520") == "%20"  # decoded once, not twice


def test_decode_term_empty_string():
    assert m.decode_term("") == ""


def test_decode_term_non_ascii_percent_encoded():
    # 鬼 in UTF-8 is E9 AC BC.
    assert m.decode_term("%E9%AC%BC") == "鬼"


def test_decode_data_scalar_types_unchanged():
    assert m.decode_data(None) is None
    assert m.decode_data(True) is True
    assert m.decode_data(False) is False
    assert m.decode_data(42) == 42
    assert m.decode_data(3.14) == 3.14


def test_decode_data_plain_string():
    assert m.decode_data("hello%20world") == "hello world"


def test_decode_data_nested_dict_values_only():
    src = {
        "name": "hello%20world",
        "count": 3,
        "nested": {"inner": "foo%2Fbar", "n": None},
    }
    got = m.decode_data(src)
    assert got == {
        "name": "hello world",
        "count": 3,
        "nested": {"inner": "foo/bar", "n": None},
    }


def test_decode_data_keys_untouched():
    # %20 in a key must be preserved as-is.
    src = {"hello%20key": "value%20here"}
    got = m.decode_data(src)
    assert "hello%20key" in got
    assert got["hello%20key"] == "value here"


def test_decode_data_list_elements_decoded():
    src = ["a%20b", "c%2Fd", 1, None, True]
    assert m.decode_data(src) == ["a b", "c/d", 1, None, True]


def test_decode_data_tuple_becomes_list():
    # Spec says list/tuple are walked; result shape normalises to list.
    got = m.decode_data(("a%20b", 1))
    assert got == ["a b", 1]


def test_decode_data_idempotent_on_decoded_input():
    # Decoding a value that has no % sequences is a no-op — running twice
    # is the same as running once.
    payload = {"a": ["b c", {"d": "e f", "n": 1}]}
    assert m.decode_data(m.decode_data(payload)) == payload


def test_parse_data_arg_decodes_after_json_parse():
    raw = '{"name": "hello%20world"}'
    assert m.parse_data_arg(raw) == {"name": "hello world"}


def test_parse_data_arg_invalid_json_raises_known_error():
    with pytest.raises(m.KnownError) as exc:
        m.parse_data_arg("{not json")
    assert exc.value.code == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# now_epoch and its env seam
# ---------------------------------------------------------------------------


def test_now_epoch_without_env_returns_positive_int(monkeypatch):
    monkeypatch.delenv("JANKENOBOE_TEST_NOW", raising=False)
    n = m.now_epoch()
    assert isinstance(n, int)
    assert n > 0


def test_now_epoch_with_env_returns_pinned_value(monkeypatch):
    monkeypatch.setenv("JANKENOBOE_TEST_NOW", "1700000000")
    assert m.now_epoch() == 1700000000


def test_now_epoch_env_overrides_real_clock(monkeypatch):
    monkeypatch.setenv("JANKENOBOE_TEST_NOW", "1")
    assert m.now_epoch() == 1


def test_now_epoch_bad_env_raises_value_error(monkeypatch):
    # Non-integer content in the env var is a test bug; we prefer to fail
    # loudly rather than silently fall through to the real clock.
    monkeypatch.setenv("JANKENOBOE_TEST_NOW", "not-a-number")
    with pytest.raises(ValueError):
        m.now_epoch()


# ---------------------------------------------------------------------------
# UUIDs
# ---------------------------------------------------------------------------

_UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_new_uuid_shape_is_lowercase_canonical_v4():
    u = m.new_uuid()
    assert isinstance(u, str)
    assert _UUID4_RE.match(u), f"not canonical lowercase UUID v4: {u}"


def test_new_uuid_is_unique_across_many_calls():
    seen = {m.new_uuid() for _ in range(1000)}
    assert len(seen) == 1000


# ---------------------------------------------------------------------------
# JSON envelopes: success, error, run
# ---------------------------------------------------------------------------


def test_success_writes_json_to_stdout_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        m.success({"ok": True, "n": 1})
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    # Stdout is JSON followed by a single newline.
    line = captured.out.rstrip("\n")
    assert json.loads(line) == {"ok": True, "n": 1}
    assert captured.out.endswith("\n")


def test_success_preserves_non_ascii_without_escaping(capsys):
    with pytest.raises(SystemExit):
        m.success({"name": "鬼滅の刃"})
    captured = capsys.readouterr()
    assert "鬼滅の刃" in captured.out


def test_error_writes_envelope_to_stderr_and_exits_one(capsys):
    with pytest.raises(SystemExit) as exc:
        m.error("NOT_FOUND", "missing", {"id": "abc"})
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err.rstrip("\n"))
    assert payload == {
        "error": {
            "code": "NOT_FOUND",
            "message": "missing",
            "details": {"id": "abc"},
        }
    }


def test_error_allows_null_details(capsys):
    with pytest.raises(SystemExit):
        m.error("INTERNAL_ERROR", "boom")
    captured = capsys.readouterr()
    payload = json.loads(captured.err.rstrip("\n"))
    assert payload["error"]["details"] is None


def test_error_rejects_unknown_code():
    with pytest.raises(ValueError):
        m.error("NOT_A_REAL_CODE", "x")


def test_valid_error_codes_has_exactly_nine_entries():
    assert len(m.VALID_ERROR_CODES) == 9
    assert "DB_NOT_FOUND" in m.VALID_ERROR_CODES
    assert "SCHEMA_MISMATCH" in m.VALID_ERROR_CODES
    assert "INVALID_INPUT" in m.VALID_ERROR_CODES
    assert "NOT_FOUND" in m.VALID_ERROR_CODES
    assert "CONSTRAINT_VIOLATION" in m.VALID_ERROR_CODES
    assert "SONG_INVARIANT_VIOLATION" in m.VALID_ERROR_CODES
    assert "ALREADY_GRADUATED" in m.VALID_ERROR_CODES
    assert "INVALID_ANSWER" in m.VALID_ERROR_CODES
    assert "INTERNAL_ERROR" in m.VALID_ERROR_CODES


def test_run_maps_known_error_to_error_envelope(capsys):
    def main():
        raise m.KnownError("NOT_FOUND", "not here", {"id": "x"})

    with pytest.raises(SystemExit) as exc:
        m.run(main)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.err.rstrip("\n"))
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["message"] == "not here"
    assert payload["error"]["details"] == {"id": "x"}


def test_run_maps_random_exception_to_internal_error(capsys):
    def main():
        raise RuntimeError("something weird")

    with pytest.raises(SystemExit) as exc:
        m.run(main)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.err.rstrip("\n"))
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "something weird" in payload["error"]["message"]


def test_run_empty_exception_message_defaults(capsys):
    def main():
        raise RuntimeError()

    with pytest.raises(SystemExit):
        m.run(main)
    captured = capsys.readouterr()
    payload = json.loads(captured.err.rstrip("\n"))
    assert payload["error"]["message"] == "internal error"


def test_run_successful_main_does_not_swallow_system_exit(capsys):
    # A main that calls success() raises SystemExit(0); run() must
    # propagate so the process exits 0.
    def main():
        m.success({"ok": True})

    with pytest.raises(SystemExit) as exc:
        m.run(main)
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# KnownError
# ---------------------------------------------------------------------------


def test_known_error_stores_fields():
    e = m.KnownError("NOT_FOUND", "nope", {"k": 1})
    assert e.code == "NOT_FOUND"
    assert e.message == "nope"
    assert e.details == {"k": 1}
    assert str(e) == "nope"


def test_known_error_rejects_unknown_code():
    with pytest.raises(ValueError):
        m.KnownError("NOT_A_REAL_CODE", "x")


# ---------------------------------------------------------------------------
# check_schema
# ---------------------------------------------------------------------------


def _make_conn_with(schema_ddl: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    if schema_ddl:
        conn.executescript(schema_ddl)
    return conn


def _full_schema_ddl() -> str:
    # Minimal DDL that declares every expected table and column. Types are
    # loose — check_schema only checks presence of tables and columns.
    return """
    CREATE TABLE song (
        id TEXT PRIMARY KEY, name TEXT, name_context TEXT, artist_id TEXT,
        created_at INTEGER, updated_at INTEGER, status INTEGER
    );
    CREATE TABLE artist (
        id TEXT PRIMARY KEY, name TEXT, name_context TEXT,
        created_at INTEGER, updated_at INTEGER, status INTEGER
    );
    CREATE TABLE show (
        id TEXT PRIMARY KEY, name TEXT, name_romaji TEXT, vintage TEXT,
        s_type TEXT, created_at INTEGER, updated_at INTEGER, status INTEGER
    );
    CREATE TABLE rel_show_song (
        show_id TEXT, song_id TEXT, media_url TEXT, created_at INTEGER,
        PRIMARY KEY (show_id, song_id)
    );
    CREATE TABLE play_history (
        id TEXT PRIMARY KEY, show_id TEXT, song_id TEXT,
        created_at INTEGER, media_url TEXT, status INTEGER
    );
    CREATE TABLE learning (
        id TEXT PRIMARY KEY, song_id TEXT, level INTEGER,
        created_at INTEGER, updated_at INTEGER,
        last_level_up_at INTEGER, level_up_path TEXT, graduated INTEGER
    );
    """


def test_check_schema_passes_on_full_schema():
    conn = _make_conn_with(_full_schema_ddl())
    # Must not raise.
    m.check_schema(conn)


def test_check_schema_detects_missing_table():
    ddl = _full_schema_ddl().replace(
        "CREATE TABLE learning (",
        "CREATE TABLE learning_placeholder_do_not_match (",
    )
    conn = _make_conn_with(ddl)
    with pytest.raises(m.KnownError) as exc:
        m.check_schema(conn)
    assert exc.value.code == "SCHEMA_MISMATCH"
    assert "learning" in exc.value.details["missing_tables"]


def test_check_schema_detects_missing_column():
    # Drop the `graduated` column from the learning table.
    ddl = _full_schema_ddl().replace(
        "last_level_up_at INTEGER, level_up_path TEXT, graduated INTEGER",
        "last_level_up_at INTEGER, level_up_path TEXT",
    )
    conn = _make_conn_with(ddl)
    with pytest.raises(m.KnownError) as exc:
        m.check_schema(conn)
    assert exc.value.code == "SCHEMA_MISMATCH"
    assert "graduated" in exc.value.details["missing_columns"]["learning"]
    # Existing tables are not listed as missing.
    assert "learning" not in exc.value.details["missing_tables"]


def test_check_schema_empty_db_reports_all_tables_missing():
    conn = _make_conn_with("")
    with pytest.raises(m.KnownError) as exc:
        m.check_schema(conn)
    missing = set(exc.value.details["missing_tables"])
    assert missing == set(m.EXPECTED_SCHEMA.keys())


# ---------------------------------------------------------------------------
# app_root, db_path, open_db
# ---------------------------------------------------------------------------


def test_app_root_and_db_path_resolve_correctly(tmp_path):
    # Simulate App_Root/scripts/foo.py.
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    fake_script = scripts_dir / "foo.py"
    fake_script.write_text("")

    assert m.app_root(str(fake_script)) == tmp_path.resolve()
    assert m.db_path(str(fake_script)) == (tmp_path / "db" / "datasource.db").resolve()


def test_open_db_missing_file_raises_db_not_found(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    fake_script = scripts_dir / "foo.py"
    fake_script.write_text("")
    # No db/datasource.db created.

    with pytest.raises(m.KnownError) as exc:
        m.open_db(str(fake_script))
    assert exc.value.code == "DB_NOT_FOUND"


def test_open_db_bad_schema_raises_schema_mismatch(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    fake_script = scripts_dir / "foo.py"
    fake_script.write_text("")
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    # Create the file but leave it schema-less.
    db_file = db_dir / "datasource.db"
    sqlite3.connect(str(db_file)).close()

    with pytest.raises(m.KnownError) as exc:
        m.open_db(str(fake_script))
    assert exc.value.code == "SCHEMA_MISMATCH"


def test_open_db_configures_connection(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    fake_script = scripts_dir / "foo.py"
    fake_script.write_text("")
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_file = db_dir / "datasource.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_full_schema_ddl())
    conn.close()

    conn = m.open_db(str(fake_script))
    try:
        assert conn.isolation_level is None
        # Row factory returns sqlite3.Row objects (support both dict-like access).
        row = conn.execute("SELECT 1 AS x").fetchone()
        assert row["x"] == 1
        fk_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk_on == 1
    finally:
        conn.close()
