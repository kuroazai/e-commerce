"""Card recognition.

Real card photographs cannot go in the repository - they are copyrighted
artwork, and committing a few megabytes of JPEG to prove a hash works is a poor
trade. So the fixtures are generated: a synthetic "card" is drawn, then
photographed badly on purpose - rotated, perspective-warped, darkened, blurred,
noised - and the test asserts it is still recognised.

That is the property that matters. A hash that only matches a pristine scan is
useless against a phone photo taken over a desk.
"""
from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2", exc_type=ImportError)
np = pytest.importorskip("numpy", exc_type=ImportError)

from cardshop.vision import (  # noqa: E402 - after importorskip
    CARD_HEIGHT,
    CARD_WIDTH,
    CardIndex,
    CardScanner,
    detect_card,
    dewarp,
    fingerprint_reference,
    hamming,
    phash,
)
from cardshop.vision.preprocess import order_corners  # noqa: E402

pytestmark = pytest.mark.vision

RNG = np.random.default_rng(20261002)


def make_card(seed: int) -> np.ndarray:
    """A distinctive synthetic card: border, art box, title bar, random blobs."""
    rng = np.random.default_rng(seed)
    card = np.full((CARD_HEIGHT, CARD_WIDTH, 3), 235, np.uint8)
    cv2.rectangle(card, (8, 8), (CARD_WIDTH - 8, CARD_HEIGHT - 8), (40, 40, 40), 6)
    colour = tuple(int(c) for c in rng.integers(30, 220, 3))
    cv2.rectangle(card, (30, 70), (CARD_WIDTH - 30, 380), colour, -1)
    for _ in range(14):
        centre = (int(rng.integers(40, CARD_WIDTH - 40)), int(rng.integers(80, 370)))
        shade = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.circle(card, centre, int(rng.integers(12, 45)), shade, -1)
    cv2.rectangle(card, (24, 20), (CARD_WIDTH - 24, 62), (210, 180, 60), -1)
    cv2.rectangle(card, (30, 400), (CARD_WIDTH - 30, CARD_HEIGHT - 40), (200, 200, 190), -1)
    return card


def photograph(card: np.ndarray, seed: int) -> np.ndarray:
    """Put the card on a desk and take a bad photo of it."""
    rng = np.random.default_rng(seed)
    scene = np.full((900, 700, 3), 110, np.uint8)
    scene[:] = rng.integers(95, 125, (900, 700, 3)).astype(np.uint8)

    source = np.float32([[0, 0], [CARD_WIDTH, 0],
                         [CARD_WIDTH, CARD_HEIGHT], [0, CARD_HEIGHT]])
    jitter = rng.integers(-30, 30, (4, 2)).astype(np.float32)
    target = np.float32([[140, 150], [540, 150], [540, 720], [140, 720]]) + jitter

    warp = cv2.getPerspectiveTransform(source, target)
    placed = cv2.warpPerspective(card, warp, (700, 900), borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(
        np.full((CARD_HEIGHT, CARD_WIDTH), 255, np.uint8), warp, (700, 900)
    )
    scene[mask > 0] = placed[mask > 0]

    scene = cv2.convertScaleAbs(scene, alpha=float(rng.uniform(0.75, 1.15)),
                                beta=float(rng.integers(-25, 25)))
    scene = cv2.GaussianBlur(scene, (3, 3), 0)
    noise = rng.normal(0, 5, scene.shape)
    return np.clip(scene.astype(np.float32) + noise, 0, 255).astype(np.uint8)


@pytest.fixture(scope="module")
def reference_set() -> tuple[CardIndex, dict[str, np.ndarray]]:
    index = CardIndex()
    cards = {}
    for number in range(6):
        card_id = f"SYN-{number:03d}"
        card = make_card(number)
        cards[card_id] = card
        index.add(fingerprint_reference(card, card_id, f"Synthetic Card {number}",
                                        set_code="SYN"))
    return index, cards


# -- fingerprinting ---------------------------------------------------------

def test_the_same_image_hashes_identically() -> None:
    card = make_card(1)
    assert phash(card) == phash(card)


def test_different_cards_hash_differently() -> None:
    assert hamming(phash(make_card(1)), phash(make_card(2))) > 10


def test_a_hash_survives_rescaling() -> None:
    """A phone photo is never the resolution of the reference scan."""
    card = make_card(3)
    smaller = cv2.resize(card, (CARD_WIDTH // 2, CARD_HEIGHT // 2))
    assert hamming(phash(card), phash(smaller)) <= 6


def test_a_hash_survives_a_brightness_change() -> None:
    """This is why it is a DCT hash and not a checksum. Desk lighting varies."""
    card = make_card(4)
    darker = cv2.convertScaleAbs(card, alpha=0.7, beta=-20)
    assert hamming(phash(card), phash(darker)) <= 6


def test_a_hash_survives_mild_blur() -> None:
    card = make_card(5)
    blurred = cv2.GaussianBlur(card, (5, 5), 0)
    assert hamming(phash(card), phash(blurred)) <= 6


# -- geometry ---------------------------------------------------------------

def test_corners_are_ordered_clockwise_from_top_left() -> None:
    scrambled = np.float32([[300, 400], [10, 20], [310, 25], [5, 395]])
    ordered = order_corners(scrambled)
    assert ordered[0].tolist() == [10, 20]     # top-left
    assert ordered[1].tolist() == [310, 25]    # top-right
    assert ordered[2].tolist() == [300, 400]   # bottom-right
    assert ordered[3].tolist() == [5, 395]     # bottom-left


def test_finds_a_card_in_a_photograph() -> None:
    detection = detect_card(photograph(make_card(1), 1))
    assert detection is not None
    assert detection.corners.shape == (4, 2)


def test_finds_nothing_in_an_empty_frame() -> None:
    """An empty desk must not produce a confident detection of the desk."""
    assert detect_card(np.full((900, 700, 3), 120, np.uint8)) is None


def test_dewarp_returns_a_card_shaped_image() -> None:
    photo = photograph(make_card(2), 2)
    detection = detect_card(photo)
    assert detection is not None
    assert dewarp(photo, detection.corners).shape[:2] == (CARD_HEIGHT, CARD_WIDTH)


# -- end to end -------------------------------------------------------------

def test_recognises_every_card_from_a_bad_photograph(reference_set) -> None:
    """The whole point of the subsystem."""
    index, cards = reference_set
    scanner = CardScanner(index)

    for offset, card_id in enumerate(cards):
        result = scanner.scan_image(photograph(cards[card_id], 500 + offset))
        assert result.best is not None, f"{card_id} was not recognised at all"
        assert result.best.card.card_id == card_id, (
            f"{card_id} matched {result.best.card.card_id} instead"
        )


def test_an_unknown_card_is_not_matched_confidently(reference_set) -> None:
    """A card that is not in the index must come back for review, not come back
    as the nearest thing in the index."""
    index, _ = reference_set
    stranger = photograph(make_card(999), 999)
    result = CardScanner(index).scan_image(stranger)

    if result.best is not None:
        assert result.needs_review, "an unknown card was matched confidently"


def test_a_scan_reports_its_own_uncertainty(reference_set) -> None:
    index, cards = reference_set
    result = CardScanner(index).scan_image(photograph(cards["SYN-000"], 1))
    assert 0.0 <= result.best.score <= 1.0
    assert isinstance(result.needs_review, bool)
    assert result.summary()


def test_a_frame_with_no_card_scans_without_crashing(reference_set) -> None:
    index, _ = reference_set
    result = CardScanner(index).scan_image(np.full((600, 400, 3), 118, np.uint8))
    assert result.needs_review


def test_the_index_round_trips_through_a_file(tmp_path, reference_set) -> None:
    index, cards = reference_set
    path = index.save(tmp_path / "reference.json")
    reloaded = CardIndex.load(path)

    assert len(reloaded) == len(index)
    result = CardScanner(reloaded).scan_image(photograph(cards["SYN-003"], 77))
    assert result.best is not None
    assert result.best.card.card_id == "SYN-003"


def test_an_empty_index_matches_nothing() -> None:
    result = CardScanner(CardIndex()).scan_image(photograph(make_card(1), 1))
    assert result.best is None
    assert result.needs_review
