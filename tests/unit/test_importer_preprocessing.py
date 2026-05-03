"""Unit tests for the AMQ-to-flat preprocessing helpers in ``scripts/import_plan.py``.

Covers the three pure functions added for Bug 1:

* ``_discriminate(parsed)`` — tag the parsed JSON shape.
* ``_amq_entry_to_flat(entry, i)`` — field-mapping table for one AMQ song.
* ``_flatten_amq(payload)`` — loop over ``payload["songs"]``.

No DB, no subprocess. ``tests/conftest.py`` already puts the repo root on
``sys.path`` at the session level, so ``from scripts import ...`` works
without a per-file shim.
"""

from __future__ import annotations

import pytest

from scripts import _common
from scripts import import_plan as m

# ---------------------------------------------------------------------------
# _discriminate
# ---------------------------------------------------------------------------


def test_discriminate_empty_list_is_flat():
    assert m._discriminate([]) == "flat"


def test_discriminate_non_empty_list_is_flat():
    assert m._discriminate([{"x": 1}]) == "flat"


def test_discriminate_empty_songs_list_is_raw_amq():
    assert m._discriminate({"songs": []}) == "raw_amq"


def test_discriminate_non_empty_songs_list_is_raw_amq():
    assert m._discriminate({"songs": [{"a": 1}]}) == "raw_amq"


def test_discriminate_songs_not_a_list_raises():
    with pytest.raises(_common.KnownError) as exc:
        m._discriminate({"songs": "not a list"})
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details == {"got_type": "dict"}


def test_discriminate_dict_without_songs_raises():
    with pytest.raises(_common.KnownError) as exc:
        m._discriminate({"no_songs": 1})
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details == {"got_type": "dict"}


def test_discriminate_string_scalar_raises():
    with pytest.raises(_common.KnownError) as exc:
        m._discriminate("scalar")
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details == {"got_type": "str"}


def test_discriminate_int_scalar_raises():
    with pytest.raises(_common.KnownError) as exc:
        m._discriminate(42)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details == {"got_type": "int"}


def test_discriminate_none_raises():
    with pytest.raises(_common.KnownError) as exc:
        m._discriminate(None)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details == {"got_type": "NoneType"}


# ---------------------------------------------------------------------------
# _amq_entry_to_flat
# ---------------------------------------------------------------------------


def test_amq_entry_to_flat_all_amq_keys_present():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "animeRomajiName": "Kuranado",
        "vintage": "Fall 2007",
        "audio": "https://example.com/megumeru.mp3",
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert got == {
        "artist_name": "Lia",
        "song_name": "Megumeru",
        "show_name": "Clannad",
        "vintage": "Fall 2007",
        "media_url": "https://example.com/megumeru.mp3",
    }


def test_amq_entry_to_flat_all_flat_alias_keys_present():
    entry = {
        "artist_name": "Yui",
        "song_name": "Again",
        "show_name": "Fullmetal Alchemist: Brotherhood",
        "vintage": "Spring 2009",
        "media_url": "https://example.com/again.mp3",
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert got == {
        "artist_name": "Yui",
        "song_name": "Again",
        "show_name": "Fullmetal Alchemist: Brotherhood",
        "vintage": "Spring 2009",
        "media_url": "https://example.com/again.mp3",
    }


def test_amq_entry_to_flat_english_name_beats_romaji_when_both_present():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "animeRomajiName": "Kuranado",
        "vintage": "Fall 2007",
        "audio": "https://example.com/megumeru.mp3",
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert got["show_name"] == "Clannad"


def test_amq_entry_to_flat_romaji_used_when_english_absent():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeRomajiName": "Kuranado",
        "vintage": "Fall 2007",
        "audio": "https://example.com/megumeru.mp3",
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert got["show_name"] == "Kuranado"


def test_amq_entry_to_flat_missing_media_url_defaults_to_empty():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "vintage": "Fall 2007",
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert got["media_url"] == ""


def test_amq_entry_to_flat_empty_string_media_candidates_default_to_empty():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "vintage": "Fall 2007",
        "audio": "",
        "media_url": "",
        "MP3": "",
        "mp3": "",
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert got["media_url"] == ""


def test_amq_entry_to_flat_missing_artist_raises_invalid_input():
    entry = {
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "vintage": "Fall 2007",
        "audio": "https://example.com/megumeru.mp3",
    }
    with pytest.raises(_common.KnownError) as exc:
        m._amq_entry_to_flat(entry, 7)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details["missing_field"] == "artist_name"
    assert exc.value.details["index"] == 7
    assert exc.value.details["available_keys"] == sorted(entry.keys())


def test_amq_entry_to_flat_empty_string_artist_counts_as_missing():
    # Empty strings for required fields are treated as missing — no
    # second candidate exists here, so this must raise.
    entry = {
        "songArtist": "",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "vintage": "Fall 2007",
    }
    with pytest.raises(_common.KnownError) as exc:
        m._amq_entry_to_flat(entry, 2)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details["missing_field"] == "artist_name"
    assert exc.value.details["index"] == 2


def test_amq_entry_to_flat_missing_song_name_raises():
    entry = {
        "songArtist": "Lia",
        "animeEnglishName": "Clannad",
        "vintage": "Fall 2007",
    }
    with pytest.raises(_common.KnownError) as exc:
        m._amq_entry_to_flat(entry, 1)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details["missing_field"] == "song_name"
    assert exc.value.details["index"] == 1


def test_amq_entry_to_flat_missing_show_name_raises():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "vintage": "Fall 2007",
    }
    with pytest.raises(_common.KnownError) as exc:
        m._amq_entry_to_flat(entry, 4)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details["missing_field"] == "show_name"
    assert exc.value.details["index"] == 4


def test_amq_entry_to_flat_missing_vintage_raises():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
    }
    with pytest.raises(_common.KnownError) as exc:
        m._amq_entry_to_flat(entry, 0)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details["missing_field"] == "vintage"


def test_amq_entry_to_flat_drops_extra_amq_native_fields():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "vintage": "Fall 2007",
        "audio": "https://example.com/megumeru.mp3",
        # Extra AMQ-native noise that must be silently dropped.
        "type": 1,
        "fromList": 0,
        "startSample": 42,
        "videoLength": 180,
        "urlMap": {"catbox": {"0": "https://files.catbox.moe/x.webm"}},
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert set(got.keys()) == {
        "artist_name",
        "song_name",
        "show_name",
        "vintage",
        "media_url",
    }


def test_amq_entry_to_flat_key_order_is_stable():
    entry = {
        "songArtist": "Lia",
        "songName": "Megumeru",
        "animeEnglishName": "Clannad",
        "vintage": "Fall 2007",
        "audio": "https://example.com/megumeru.mp3",
    }
    got = m._amq_entry_to_flat(entry, 0)
    assert list(got.keys()) == [
        "artist_name",
        "song_name",
        "show_name",
        "vintage",
        "media_url",
    ]


# ---------------------------------------------------------------------------
# _flatten_amq
# ---------------------------------------------------------------------------


def test_flatten_amq_three_song_happy_path():
    payload = {
        "songs": [
            {
                "songArtist": "Lia",
                "songName": "Megumeru",
                "animeEnglishName": "Clannad",
                "vintage": "Fall 2007",
                "audio": "https://example.com/megumeru.mp3",
            },
            {
                "songArtist": "Yui",
                "songName": "Again",
                "animeEnglishName": "Fullmetal Alchemist: Brotherhood",
                "vintage": "Spring 2009",
                "audio": "https://example.com/again.mp3",
            },
            {
                "songArtist": "FLOW",
                "songName": "GO!!!",
                "animeEnglishName": "Naruto",
                "vintage": "Fall 2002",
                "audio": "https://example.com/go.mp3",
            },
        ],
        # Extra top-level siblings that must be ignored.
        "quizSettings": {"songCount": 40},
        "exportTimestamp": 1700000000,
    }
    got = m._flatten_amq(payload)
    assert got == [
        {
            "artist_name": "Lia",
            "song_name": "Megumeru",
            "show_name": "Clannad",
            "vintage": "Fall 2007",
            "media_url": "https://example.com/megumeru.mp3",
        },
        {
            "artist_name": "Yui",
            "song_name": "Again",
            "show_name": "Fullmetal Alchemist: Brotherhood",
            "vintage": "Spring 2009",
            "media_url": "https://example.com/again.mp3",
        },
        {
            "artist_name": "FLOW",
            "song_name": "GO!!!",
            "show_name": "Naruto",
            "vintage": "Fall 2002",
            "media_url": "https://example.com/go.mp3",
        },
    ]


def test_flatten_amq_non_dict_entry_raises_with_index():
    payload = {
        "songs": [
            {
                "songArtist": "Lia",
                "songName": "Megumeru",
                "animeEnglishName": "Clannad",
                "vintage": "Fall 2007",
                "audio": "https://example.com/megumeru.mp3",
            },
            "not a dict",
            {
                "songArtist": "FLOW",
                "songName": "GO!!!",
                "animeEnglishName": "Naruto",
                "vintage": "Fall 2002",
                "audio": "https://example.com/go.mp3",
            },
        ],
    }
    with pytest.raises(_common.KnownError) as exc:
        m._flatten_amq(payload)
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details == {"index": 1}


def test_flatten_amq_empty_songs_returns_empty_list():
    assert m._flatten_amq({"songs": []}) == []


def test_flatten_amq_ignores_top_level_siblings():
    payload = {
        "songs": [
            {
                "songArtist": "Lia",
                "songName": "Megumeru",
                "animeEnglishName": "Clannad",
                "vintage": "Fall 2007",
                "audio": "https://example.com/megumeru.mp3",
            },
        ],
        "quizSettings": {"songCount": 1, "guessTime": 20},
        "exportTimestamp": 1700000000,
        "gameMode": "Standard",
        "extra": "metadata",
    }
    got = m._flatten_amq(payload)
    assert got == [
        {
            "artist_name": "Lia",
            "song_name": "Megumeru",
            "show_name": "Clannad",
            "vintage": "Fall 2007",
            "media_url": "https://example.com/megumeru.mp3",
        },
    ]
