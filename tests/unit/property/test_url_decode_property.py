"""Property 2 from requirements.md: URL decode runs at most once.

Two invariants under test:

1. For any string ``S`` without a ``%`` sign, ``urllib.parse.unquote(S) == S``,
   and ``decode_data`` is a no-op on dicts/lists/numbers/booleans/nulls that
   contain only such strings.
2. For any string containing ``%XX`` escapes, ``decode_data`` decodes exactly
   once — a second pass leaves the value unchanged.

``decode_data`` lives in ``scripts/_common.py`` (already built), so this
file is expected to PASS on a fresh clone.
"""

from __future__ import annotations

import random
import string
import urllib.parse

from scripts import _common

SEED = 20240502
ITERATIONS = 200

# Characters that URL-encoding would treat as safe or "just a letter/digit".
# Importantly: no ``%`` in here.
_SAFE_CHARS = string.ascii_letters + string.digits + " _-.~,:/"


def _random_plain_string(rng: random.Random, max_len: int = 40) -> str:
    """A random string with no ``%`` signs."""
    length = rng.randint(0, max_len)
    return "".join(rng.choice(_SAFE_CHARS) for _ in range(length))


def _random_leaf(rng: random.Random) -> object:
    """Random JSON leaf: plain string, int, float, bool, or None."""
    pick = rng.randint(0, 4)
    if pick == 0:
        return _random_plain_string(rng)
    if pick == 1:
        return rng.randint(-10_000, 10_000)
    if pick == 2:
        return rng.random() * 10_000
    if pick == 3:
        return rng.choice([True, False])
    return None


def _random_json_value(rng: random.Random, depth: int = 0) -> object:
    """Random dict / list / leaf, bounded depth to keep tests fast."""
    if depth >= 3 or rng.random() < 0.4:
        return _random_leaf(rng)
    shape = rng.choice(["dict", "list"])
    size = rng.randint(0, 5)
    if shape == "dict":
        # Keys are plain strings — the contract says keys are never decoded,
        # so it doesn't matter what they are, but we keep them simple.
        return {f"k{i}": _random_json_value(rng, depth + 1) for i in range(size)}
    return [_random_json_value(rng, depth + 1) for _ in range(size)]


def test_plain_strings_are_decode_fixed_points() -> None:
    rng = random.Random(SEED)
    for _ in range(ITERATIONS):
        s = _random_plain_string(rng)
        assert urllib.parse.unquote(s) == s
        assert _common.decode_term(s) == s


def test_decode_data_is_noop_on_plain_values() -> None:
    """``decode_data`` leaves dicts/lists of plain values unchanged."""
    rng = random.Random(SEED + 1)
    for _ in range(ITERATIONS):
        obj = _random_json_value(rng)
        assert _common.decode_data(obj) == obj


def test_decode_data_does_not_touch_non_string_leaves() -> None:
    """Numbers, booleans, and nulls are returned unchanged even with ``%`` nearby.

    ``bool`` is a subclass of ``int``, so this also pins the "bool stays bool"
    behavior — the helper must not treat ``True`` as 1.
    """
    rng = random.Random(SEED + 2)
    for _ in range(ITERATIONS):
        obj = {
            "int": rng.randint(-1000, 1000),
            "float": rng.random(),
            "bool_t": True,
            "bool_f": False,
            "null": None,
            "nested": [rng.randint(0, 9), True, None, 1.5],
        }
        got = _common.decode_data(obj)
        assert got == obj
        # Strict type preservation matters here.
        assert got["bool_t"] is True
        assert got["bool_f"] is False
        assert got["null"] is None


def test_decode_data_runs_once_on_percent_strings() -> None:
    """A second pass through ``decode_data`` must be a no-op.

    Uses strings where the once-decoded form has no remaining ``%`` signs —
    the realistic case where an input contains a percent escape that maps to
    a plain character (space, plus, a CJK byte sequence, etc.). The property
    says "a second pass is a no-op on the result", which requires the
    once-decoded form to not look like another escape.
    """
    rng = random.Random(SEED + 3)
    samples = [
        "hello%20world",
        "a%2Bb",  # becomes `a+b`
        "%E6%97%A5%E6%9C%AC",  # `日本`
        "space%20and%20tab",
        "%2C%2Fcomma-slash",
    ]
    for _ in range(ITERATIONS):
        s = rng.choice(samples)
        once = _common.decode_data(s)
        twice = _common.decode_data(once)
        # Sanity: once-decoded form contains no remaining escapes.
        assert "%" not in once
        # First pass actually changed the input.
        assert once != s
        # Second pass is a no-op.
        assert twice == once
        # And the single call matches urllib.parse.unquote once.
        assert once == urllib.parse.unquote(s)


def test_decode_data_keys_are_not_decoded() -> None:
    """Keys pass through untouched, even if they look like escapes."""
    obj = {"%20": "hello%20world", "plain": "foo%2Bbar"}
    got = _common.decode_data(obj)
    assert set(got.keys()) == {"%20", "plain"}
    assert got["%20"] == "hello world"
    assert got["plain"] == "foo+bar"


def test_decode_data_walks_nested_structures() -> None:
    """Every string leaf decoded once, shape preserved."""
    obj = {
        "outer": {
            "inner_list": ["a%20b", 42, {"k": "c%2Bd"}, None, True],
            "inner_str": "%E4%B8%AD",  # `中`
        },
        "top_list": [[1, "x%20y"], [False, {"deep": "z%2Fw"}]],
    }
    got = _common.decode_data(obj)
    assert got["outer"]["inner_list"][0] == "a b"
    assert got["outer"]["inner_list"][1] == 42
    assert got["outer"]["inner_list"][2] == {"k": "c+d"}
    assert got["outer"]["inner_list"][3] is None
    assert got["outer"]["inner_list"][4] is True
    assert got["outer"]["inner_str"] == "中"
    assert got["top_list"][0] == [1, "x y"]
    assert got["top_list"][1][0] is False
    assert got["top_list"][1][1] == {"deep": "z/w"}


def test_decode_term_runs_once() -> None:
    """Same single-pass rule as ``decode_data`` for the scalar entry point.

    Uses realistic samples where the once-decoded form has no remaining
    percent escapes (see ``test_decode_data_runs_once_on_percent_strings``).
    """
    rng = random.Random(SEED + 4)
    samples = ["hello%20world", "a%2Bb%2Cc", "%E4%B8%AD"]
    for _ in range(ITERATIONS):
        s = rng.choice(samples)
        once = _common.decode_term(s)
        twice = _common.decode_term(once)
        assert "%" not in once
        assert twice == once
        assert once == urllib.parse.unquote(s)


def test_decode_runs_exactly_once_even_on_double_encoded_input() -> None:
    """The "at most once per call" rule catches the double-encode case.

    If a caller sends ``"%2520"`` (which is ``%20`` double-encoded), the app
    must decode it exactly once to ``"%20"`` and stop. A second call on the
    result would wrongly collapse it to a space — that's a bug the Property 2
    wording explicitly rules out ("decodes each string at most once per run").
    """
    s = "%2520"
    once = _common.decode_data(s)
    assert once == "%20"
    # A second call WOULD decode further — but the app only calls decode_data
    # once per run. This assertion documents the hazard.
    assert _common.decode_data(once) == " "
    # The contract the app relies on: one call through the decode pipeline
    # per input, no matter how many layers of encoding the caller stacked.


def test_tuples_are_decoded_as_lists() -> None:
    """The helper treats list/tuple the same on the way in, list on the way out."""
    got = _common.decode_data(("a%20b", 2, "c%2Bd"))
    assert got == ["a b", 2, "c+d"]


def test_parse_data_arg_decodes_once() -> None:
    """``parse_data_arg`` calls ``json.loads`` then ``decode_data``.

    Verifying that the helper runs the same "decode once" rule on whatever
    the JSON parse produces.
    """
    raw = '{"name": "hello%20world", "count": 3, "nested": {"k": "a%2Bb"}}'
    got = _common.parse_data_arg(raw)
    assert got == {"name": "hello world", "count": 3, "nested": {"k": "a+b"}}
    # And decoding the result again is a no-op.
    assert _common.decode_data(got) == got


def test_parse_data_arg_invalid_json_raises_known_error() -> None:
    """Malformed JSON comes back as ``INVALID_INPUT``, not a raw Python error."""
    import pytest  # noqa: PLC0415

    with pytest.raises(_common.KnownError) as exc:
        _common.parse_data_arg("{not valid json")
    assert exc.value.code == "INVALID_INPUT"
