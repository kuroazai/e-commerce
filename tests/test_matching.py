"""Matching a messy marketplace title to something you own."""
from __future__ import annotations

import pytest

from cardshop.inventory.matching import (
    best_match,
    extract_set_code,
    match_title,
    score_title,
    tokenise,
)

ITEMS = [
    {"item_id": "a", "card_name": "Dark Magician", "set_code": "LOB-005", "quantity": 3},
    {"item_id": "b", "card_name": "Mirror Force", "set_code": "MRD-138", "quantity": 1},
    {"item_id": "c", "card_name": "Blue-Eyes White Dragon", "set_code": "LOB-001", "quantity": 2},
    {"item_id": "d", "card_name": "Dark Magician Girl", "set_code": "MFC-000", "quantity": 1},
]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Dark Magician LOB-005", "LOB-005"),
        ("Blue-Eyes LOB 001 Ultra Rare", "LOB-001"),
        ("Mirror Force SDK-EN001", "SDK-EN001"),
        ("Dark Magician", ""),
    ],
)
def test_extracts_set_code(title: str, expected: str) -> None:
    assert extract_set_code(title) == expected


def test_tokenise_drops_noise_and_set_codes() -> None:
    tokens = tokenise("Yugioh Dark Magician LOB-005 1st Edition Ultra Rare NM UK Free Post")
    assert tokens == ["dark", "magician"]


@pytest.mark.parametrize(
    "title",
    [
        "Dark Magician LOB-005",
        "Yugioh Dark Magician LOB-005 1st Edition Ultra Rare NM Near Mint UK Free Post",
        "DARK MAGICIAN LOB005 nm",
    ],
)
def test_real_listing_titles_resolve(title: str) -> None:
    """The whole point. An exact-name match fails on every one of these."""
    match = best_match(title, ITEMS)
    assert match is not None
    assert match.item["card_name"] == "Dark Magician"


def test_a_bare_name_still_matches() -> None:
    match = best_match("Dark Magician", ITEMS)
    assert match is not None
    assert match.item["card_name"] == "Dark Magician"


def test_does_not_confuse_a_card_with_its_near_namesake() -> None:
    match = best_match("Dark Magician Girl MFC-000 Secret Rare", ITEMS)
    assert match is not None
    assert match.item["card_name"] == "Dark Magician Girl"


def test_unrelated_title_matches_nothing() -> None:
    assert best_match("Pokemon Charizard Base Set Holo", ITEMS) is None
    assert match_title("Pokemon Charizard Base Set Holo", ITEMS) == []


def test_refuses_to_guess_between_two_printings() -> None:
    """Two printings, and a title that cannot distinguish them.

    Picking arbitrarily decrements the wrong one, and nobody finds out until an
    order cannot be posted. None is the correct answer; it means escalate.
    """
    printings = [
        {"item_id": "a", "card_name": "Dark Magician", "set_code": "LOB-005", "quantity": 3},
        {"item_id": "b", "card_name": "Dark Magician", "set_code": "SDY-006", "quantity": 1},
    ]
    assert best_match("Dark Magician NM 1st Edition", printings) is None

    # The same title plus a set code is no longer ambiguous.
    resolved = best_match("Dark Magician SDY-006 NM", printings)
    assert resolved is not None
    assert resolved.item["set_code"] == "SDY-006"


def test_set_code_match_is_reported() -> None:
    score, code_matched = score_title("Dark Magician LOB-005 NM", "Dark Magician", "LOB-005")
    assert code_matched
    assert score == pytest.approx(1.0)


def test_wrong_set_code_is_not_a_code_match() -> None:
    _, code_matched = score_title("Dark Magician SDY-006", "Dark Magician", "LOB-005")
    assert not code_matched


def test_a_set_code_cannot_rescue_a_zero_name_match() -> None:
    """A code is strong evidence, not a licence to ignore the name entirely."""
    score, _ = score_title("LOB-005", "Dark Magician", "LOB-005")
    assert score == 0.0


def test_handles_empty_input() -> None:
    assert best_match("", ITEMS) is None
    assert best_match("Dark Magician", []) is None
    assert tokenise("") == []
    assert extract_set_code("") == ""
