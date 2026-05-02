"""Property 6 from requirements.md: Easing function matches its definition.

These checks pin down the easing math that produces ``DEFAULT_LEVEL_UP_PATH``.
The easing math lives in ``scripts/_common.py`` (already built), so this file
is expected to PASS on a fresh clone. It stays here so the correctness
property is executable alongside the other 15.

Uses stdlib ``random`` only — ``hypothesis`` is not on the deploy sandbox.
``random.seed`` is set to a fixed integer for reproducibility. Each property
runs at least 100 iterations.
"""

from __future__ import annotations

import itertools
import random

from scripts import _common

SEED = 20240501
ITERATIONS = 200


def _textbook_fibo(n: int) -> int:
    """Standalone textbook Fibonacci — an independent check for ``fibo``.

    Using ``functools.cache`` + recursion would be fine too; the loop form
    is simpler and has no stack-depth concerns.
    """
    if n == 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b


def test_fibo_matches_textbook_for_small_n() -> None:
    expected = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610]
    for i, value in enumerate(expected):
        assert _common.fibo(i) == value, f"fibo({i}) wrong"


def test_fibo_matches_textbook_up_to_25() -> None:
    for n in range(26):
        assert _common.fibo(n) == _textbook_fibo(n), f"fibo({n}) disagrees"


def test_fibo_property_on_random_seed() -> None:
    """`fibo(n) == fibo(n-1) + fibo(n-2)` for n >= 2.

    Random sampling in [2, 30] — 30 is small enough for a loop-based Fibonacci
    to stay cheap but wide enough to exercise non-trivial values.
    """
    rng = random.Random(SEED)
    for _ in range(ITERATIONS):
        n = rng.randint(2, 30)
        assert _common.fibo(n) == _common.fibo(n - 1) + _common.fibo(n - 2)


def test_shrink_matches_definition() -> None:
    """``shrink(n) == (n * 2) // 9`` — random spot checks."""
    rng = random.Random(SEED + 1)
    for _ in range(ITERATIONS):
        n = rng.randint(0, 10_000)
        assert _common.shrink(n) == (n * 2) // 9


def test_default_easing_zero_collapse_rule() -> None:
    """``default_easing(n) = 1`` when the shrink-of-fibo diff is zero, else the diff.

    Walks ``n`` from 0 to 24 — that covers every value used by
    ``generate_level_up_path(20)`` with a cushion.
    """
    for n in range(25):
        diff = _common.shrink(_common.fibo(n + 1)) - _common.shrink(_common.fibo(n))
        expected = 1 if diff == 0 else diff
        assert _common.default_easing(n) == expected, f"default_easing({n}) wrong"


def test_default_easing_is_always_positive() -> None:
    """Every step is at least 1 day — the zero-collapse guarantees that."""
    for n in range(25):
        assert _common.default_easing(n) >= 1


def test_generate_level_up_path_20_matches_glossary() -> None:
    """The published default path in the Glossary — pinned literal."""
    expected = [1, 1, 1, 1, 1, 1, 1, 2, 3, 5, 7, 13, 19, 32, 52, 84, 135, 220, 355, 574]
    assert _common.generate_level_up_path(20) == expected


def test_default_level_up_path_constant_matches_function() -> None:
    assert _common.generate_level_up_path(20) == _common.DEFAULT_LEVEL_UP_PATH


def test_generate_level_up_path_length_and_positivity() -> None:
    """For every ``max_level`` in [1, 25]:
    * result has exactly ``max_level`` entries
    * every entry is a positive integer
    * the sequence is non-decreasing
    """
    for max_level in range(1, 26):
        path = _common.generate_level_up_path(max_level)
        assert len(path) == max_level
        assert all(isinstance(v, int) for v in path)
        assert all(v >= 1 for v in path)
        for earlier, later in itertools.pairwise(path):
            assert later >= earlier, f"decreasing at max_level={max_level}: {path}"


def test_generate_level_up_path_prefix_property() -> None:
    """``generate_level_up_path(k)`` is a prefix of ``generate_level_up_path(k + j)``.

    Random ``k`` in [1, 20] and ``j`` in [0, 5] — more than enough coverage.
    """
    rng = random.Random(SEED + 2)
    for _ in range(ITERATIONS):
        k = rng.randint(1, 20)
        j = rng.randint(0, 5)
        shorter = _common.generate_level_up_path(k)
        longer = _common.generate_level_up_path(k + j)
        assert longer[:k] == shorter
