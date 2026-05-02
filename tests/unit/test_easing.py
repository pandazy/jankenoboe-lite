"""Unit tests for the easing functions in scripts/_common.py.

These cover the Fibonacci base, the integer shrink, the default easing
function's zero-collapse rule, and the fixed ``generate_level_up_path(20)``
sequence that every new learning row is seeded with.
"""

from __future__ import annotations

import pytest

from scripts import _common as m

# ---------------------------------------------------------------------------
# fibo
# ---------------------------------------------------------------------------

# Known Fibonacci values for n in [0, 25]. Produced by hand to avoid depending
# on the implementation under test.
_FIBO_EXPECTED = [
    0,
    1,
    1,
    2,
    3,
    5,
    8,
    13,
    21,
    34,
    55,
    89,
    144,
    233,
    377,
    610,
    987,
    1597,
    2584,
    4181,
    6765,
    10946,
    17711,
    28657,
    46368,
    75025,
]


@pytest.mark.parametrize("n, expected", list(enumerate(_FIBO_EXPECTED)))
def test_fibo_matches_known_sequence(n, expected):
    assert m.fibo(n) == expected


def test_fibo_zero_and_one_are_base_cases():
    assert m.fibo(0) == 0
    assert m.fibo(1) == 1


# ---------------------------------------------------------------------------
# shrink
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n, expected",
    [
        (0, 0),
        (1, 0),  # (1*2)//9 = 0
        (4, 0),  # (8)//9   = 0
        (5, 1),  # (10)//9  = 1
        (9, 2),  # (18)//9  = 2
        (10, 2),  # (20)//9  = 2
        (13, 2),  # (26)//9  = 2
        (14, 3),  # (28)//9  = 3
        (100, 22),  # (200)//9 = 22
    ],
)
def test_shrink_spot_checks(n, expected):
    assert m.shrink(n) == expected


def test_shrink_is_integer_flooring():
    # Make sure shrink is NOT using true division (which would give a float).
    out = m.shrink(7)
    assert isinstance(out, int)
    assert out == 1  # (14)//9 = 1


# ---------------------------------------------------------------------------
# default_easing
# ---------------------------------------------------------------------------


def test_default_easing_collapses_zero_to_one():
    # For small n, shrink(fibo(n+1)) - shrink(fibo(n)) is 0; spec says the
    # result becomes 1.
    for n in range(7):
        assert m.default_easing(n) == 1, f"default_easing({n}) should be 1"


def test_default_easing_matches_fixed_path_sequence():
    # Each default_easing(i) must equal DEFAULT_LEVEL_UP_PATH[i] for
    # i in [0, len).
    for i, expected in enumerate(m.DEFAULT_LEVEL_UP_PATH):
        assert m.default_easing(i) == expected


# ---------------------------------------------------------------------------
# generate_level_up_path
# ---------------------------------------------------------------------------


def test_generate_level_up_path_20_matches_fixed_sequence():
    assert m.generate_level_up_path(20) == [
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        2,
        3,
        5,
        7,
        13,
        19,
        32,
        52,
        84,
        135,
        220,
        355,
        574,
    ]


def test_default_level_up_path_constant_matches():
    assert m.generate_level_up_path(20) == m.DEFAULT_LEVEL_UP_PATH


def test_generate_level_up_path_length_matches_argument():
    for n in range(1, 26):
        assert len(m.generate_level_up_path(n)) == n


def test_generate_level_up_path_zero_is_empty():
    assert m.generate_level_up_path(0) == []


def test_generate_level_up_path_values_are_positive_non_decreasing():
    # The path is monotone non-decreasing and every step is >= 1.
    for n in range(1, 26):
        path = m.generate_level_up_path(n)
        assert all(v >= 1 for v in path)
        assert all(path[i] <= path[i + 1] for i in range(len(path) - 1))


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_max_level_is_nineteen():
    assert m.MAX_LEVEL == 19


def test_re_learn_level_is_seven():
    assert m.RE_LEARN_LEVEL == 7
