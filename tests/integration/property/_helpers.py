"""Shared utilities for the integration property-based tests.

Every file under ``tests/integration/property/`` imports from here to keep
the per-test code short. The helpers themselves are stdlib-only and make
no DB calls.
"""

from __future__ import annotations

import json
import random
import string
from collections.abc import Sequence

# Each property test file uses its own seed offset so failures are isolated.
BASE_SEED = 20_240_601

# Iteration count for integration property tests. Each iteration fires two
# or more Python subprocesses (R18.3 mandates subprocess-level testing), and
# each subprocess adds ~150 ms of interpreter startup + DB open overhead.
# Keeping this to 20 lets the full suite finish in ~1-2 minutes rather than
# ~5+. With 14 integration property files and 1-3 tests each, the aggregate
# iteration count across the suite still exceeds 500 — enough randomness to
# surface bugs the deterministic tests miss.
ITERATIONS = 20

# Character set for randomly generated "name"-like strings. No ``%`` so the
# decode layer doesn't transform the values; tests that specifically care
# about URL decoding build their own strings.
_NAME_CHARS = string.ascii_letters + string.digits + " "


def random_name(rng: random.Random, *, min_len: int = 1, max_len: int = 20) -> str:
    """A readable ASCII name. Never empty, never all spaces."""
    while True:
        length = rng.randint(min_len, max_len)
        s = "".join(rng.choice(_NAME_CHARS) for _ in range(length)).strip()
        if s:
            return s


def random_context(rng: random.Random) -> str:
    """Name context can be empty or short — both are realistic."""
    if rng.random() < 0.3:
        return ""
    return random_name(rng, min_len=1, max_len=10)


def random_song_data(rng: random.Random, artist_id: str) -> dict:
    """Shape: matches R9.1/R9.2 payload for ``data.py create --kind song``."""
    return {
        "name": random_name(rng),
        "name_context": random_context(rng),
        "artist_id": artist_id,
    }


def random_artist_data(rng: random.Random) -> dict:
    return {
        "name": random_name(rng),
        "name_context": random_context(rng),
    }


def random_show_data(rng: random.Random) -> dict:
    return {
        "name": random_name(rng),
        "name_romaji": rng.choice(["", random_name(rng, max_len=12)]),
        "vintage": rng.choice(["Spring 2010", "Fall 2021", "Winter 2024", ""]),
        "s_type": rng.choice(["TV", "Movie", "OVA", ""]),
    }


def json_arg(payload: dict | list) -> str:
    """Serialize a payload for the ``--data`` or ``--triples`` CLI flag."""
    return json.dumps(payload, ensure_ascii=False)


def parse_stdout_json(stdout: str) -> dict | list:
    """Parse a Success_Envelope. Fails loudly on empty or malformed output."""
    stripped = stdout.strip()
    assert stripped, f"expected JSON on stdout, got empty: {stdout!r}"
    return json.loads(stripped)


def parse_stderr_json(stderr: str) -> dict:
    """Parse an Error_Envelope. Shape: ``{"error": {"code", "message", "details"}}``."""
    stripped = stderr.strip()
    assert stripped, f"expected JSON on stderr, got empty: {stderr!r}"
    parsed = json.loads(stripped)
    assert "error" in parsed, f"missing `error` key: {parsed!r}"
    err = parsed["error"]
    assert "code" in err and "message" in err, f"malformed error envelope: {err!r}"
    return parsed


def csv(items: Sequence[str]) -> str:
    """Comma-joined string for ``--ids`` / ``--song-ids`` style flags."""
    return ",".join(items)
