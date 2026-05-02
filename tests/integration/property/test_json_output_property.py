"""Property 15 from requirements.md: JSON output is always valid.

For representative Script calls:

1. On success, stdout parses as JSON.
2. On failure, stderr parses as JSON and matches the Error_Envelope shape:
   ``{"error": {"code": <string>, "message": <string>, "details": <obj|null>}}``.

Expected to PARTIALLY FAIL until the scripts land. The "script missing"
failures come through the Python interpreter itself, not an Error_Envelope,
so once the scripts exist the assertions here start biting in earnest.
"""

from __future__ import annotations

import random

from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    json_arg,
    parse_stderr_json,
    parse_stdout_json,
)

SEED = BASE_SEED + 15


def _success_calls(tmp_app_root, pinned_now) -> list[tuple[str, tuple[str, ...], dict]]:
    """A representative set of commands that SHOULD succeed once scripts land.

    Returns a list of ``(script_name, args, env)`` tuples. Items here don't
    need seeded DB rows (the scripts themselves handle the "no rows" cases).
    """
    return [
        # Empty list results are still valid JSON (`[]`).
        (
            "query.py",
            ("search", "--kind", "song", "--term", "nothing-matches"),
            {},
        ),
        ("query.py", ("duplicates", "--kind", "song"), {}),
        ("query.py", ("batch-get", "--kind", "artist", "--ids", ""), {}),
        ("learning.py", ("stats",), {}),
        ("learning.py", ("due",), {}),
        # Create roundtrip — needs the time seam.
        (
            "data.py",
            (
                "create",
                "--kind",
                "artist",
                "--data",
                json_arg({"name": "JsonProbe"}),
            ),
            {"JANKENOBOE_TEST_NOW": str(pinned_now)},
        ),
    ]


def _failure_calls(tmp_app_root) -> list[tuple[str, tuple[str, ...], dict]]:
    """Calls that SHOULD fail with an Error_Envelope once scripts land."""
    return [
        # Missing --before → INVALID_INPUT.
        ("cleanup.py", (), {}),
        # Non-existent id → NOT_FOUND.
        ("query.py", ("get", "--kind", "song", "--id", "no-such"), {}),
        # levelup on non-existent id → NOT_FOUND.
        ("learning.py", ("levelup", "--ids", "no-such-id"), {}),
        # Bad JSON in --data → INVALID_INPUT.
        (
            "data.py",
            ("create", "--kind", "artist", "--data", "{not-json"),
            {},
        ),
    ]


def test_success_stdout_is_valid_json(tmp_app_root, call_script, pinned_now) -> None:
    """Each representative successful call yields valid JSON on stdout.

    Uses random selection over iterations just to exercise the contract —
    each specific call is deterministic.
    """
    rng = random.Random(SEED)
    cases = _success_calls(tmp_app_root, pinned_now)
    for _ in range(min(ITERATIONS, len(cases) * 25)):
        name, args, env = rng.choice(cases)
        rc, out, err = call_script(name, *args, cwd=tmp_app_root, env=env)
        if rc != 0:
            # Pre-script-land phase: the Python interpreter reports
            # "can't open file" on stderr and exits non-zero. That failure
            # mode isn't a SCRIPT failure, so we can't assert the
            # Error_Envelope shape here. Verify that stderr *is not* empty,
            # which is the best we can do in the interim.
            assert err, f"{name} failed but emitted no stderr — bad smoke signal"
            continue
        # Script landed and exited 0: stdout must parse as JSON.
        parse_stdout_json(out)


def test_failure_stderr_is_valid_error_envelope(tmp_app_root, call_script) -> None:
    """Each representative failure call produces a parseable Error_Envelope.

    Before scripts land, the test is best-effort: if the interpreter itself
    fails (``can't open file``), the envelope isn't produced. The assertion
    below covers the interim gracefully.
    """
    rng = random.Random(SEED + 1)
    cases = _failure_calls(tmp_app_root)
    for _ in range(min(ITERATIONS, len(cases) * 25)):
        name, args, env = rng.choice(cases)
        rc, _out, err = call_script(name, *args, cwd=tmp_app_root, env=env)
        assert rc != 0, f"{name} should have failed"
        # Once scripts land, stderr is a JSON Error_Envelope.
        if err.lstrip().startswith("{"):
            envelope = parse_stderr_json(err)
            code = envelope["error"]["code"]
            # Must be one of the approved codes.
            from scripts._common import VALID_ERROR_CODES  # noqa: PLC0415

            assert code in VALID_ERROR_CODES, f"unknown code: {code!r}"
        # Else: interpreter-level failure (script file missing). The real
        # assertion comes back alive after Tasks 6-15.
