"""Photo in, candidate identifications out."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .fingerprint import region_hashes
from .index import CardIndex, Match, ReferenceCard
from .preprocess import Detection, detect_card, normalise_scan


@dataclass(frozen=True)
class ScanResult:
    """What a scan produced, and whether it can be trusted without review."""

    matches: list[Match]
    detection: Detection | None
    full_hash: int
    art_hash: int

    @property
    def best(self) -> Match | None:
        return self.matches[0] if self.matches else None

    @property
    def needs_review(self) -> bool:
        """True when a human or the agent should look.

        Three ways a scan is uncertain: nothing matched, the best match is below
        the confidence bar, or the top two are close enough that picking the
        first is arbitrary.
        """
        if not self.matches:
            return True
        if not self.matches[0].confident:
            return True
        if len(self.matches) > 1:
            return (self.matches[0].score - self.matches[1].score) < 0.05
        return False

    def summary(self) -> str:
        if not self.matches:
            return "no match"
        best = self.matches[0]
        flag = " (needs review)" if self.needs_review else ""
        code = f" [{best.card.set_code}]" if best.card.set_code else ""
        return f"{best.card.name}{code} score={best.score:.3f}{flag}"


class CardScanner:
    def __init__(self, index: CardIndex, *, detect: bool = True) -> None:
        self.index = index
        self.detect = detect

    def scan_image(self, image: np.ndarray) -> ScanResult:
        detection = detect_card(image) if self.detect else None
        card_image = detection.image if detection else normalise_scan(image)
        full_hash, art_hash, _ = region_hashes(card_image)
        return ScanResult(
            matches=self.index.search(full_hash, art_hash),
            detection=detection,
            full_hash=full_hash,
            art_hash=art_hash,
        )

    def scan_file(self, path: str | Path) -> ScanResult:
        image = cv2.imread(str(path))
        if image is None:
            raise FileNotFoundError(f"could not read an image at {path}")
        return self.scan_image(image)


def fingerprint_reference(
    image: np.ndarray, card_id: str, name: str, *, set_code: str = "", rarity: str = ""
) -> ReferenceCard:
    """Build an index entry from a clean reference scan of a card."""
    flat = normalise_scan(image)
    full_hash, art_hash, name_hash = region_hashes(flat)
    return ReferenceCard(
        card_id=card_id, name=name, set_code=set_code, rarity=rarity,
        full_hash=full_hash, art_hash=art_hash, name_hash=name_hash,
    )
