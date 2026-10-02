"""The reference index: fingerprints of known cards, and lookup."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .fingerprint import HASH_BITS, hamming, similarity


@dataclass(frozen=True)
class ReferenceCard:
    """A known card and its fingerprints."""

    card_id: str
    name: str
    set_code: str = ""
    rarity: str = ""
    full_hash: int = 0
    art_hash: int = 0
    name_hash: int = 0


@dataclass(frozen=True)
class Match:
    """A candidate identification, with the evidence behind it."""

    card: ReferenceCard
    score: float
    full_distance: int
    art_distance: int

    @property
    def confident(self) -> bool:
        """Whether this can be accepted without a human or an LLM looking.

        Tuned deliberately tight. Misidentifying a card means listing the wrong
        item for sale, which costs a refund and a feedback hit - far more than
        the few seconds of reviewing an uncertain scan.
        """
        return self.score >= 0.90 and self.full_distance <= 6


@dataclass
class CardIndex:
    """Fingerprints of every known card, searchable by Hamming distance.

    Linear scan. At a few tens of thousands of cards that is around a millisecond
    and needs no extra dependency; a BK-tree or vector index only earns its
    complexity well past that.
    """

    cards: list[ReferenceCard] = field(default_factory=list)

    def add(self, card: ReferenceCard) -> None:
        self.cards.append(card)

    def __len__(self) -> int:
        return len(self.cards)

    def search(self, full_hash: int, art_hash: int = 0, limit: int = 5) -> list[Match]:
        """Best matches for a scanned fingerprint, most likely first.

        The full-card hash dominates; the artwork hash breaks ties between
        reprints that share a frame and differ only in the picture.
        """
        matches = []
        for card in self.cards:
            full_distance = hamming(full_hash, card.full_hash)
            full_score = similarity(full_hash, card.full_hash)
            have_art = bool(art_hash and card.art_hash)

            if have_art:
                art_distance = hamming(art_hash, card.art_hash)
                art_score = 1.0 - art_distance / HASH_BITS
            else:
                # No artwork hash on one side or the other, so there is nothing
                # to break the tie with. Fall back to the full-card score rather
                # than scoring the artwork as a mismatch, which would penalise
                # every card in an index built without art hashes.
                art_distance = HASH_BITS
                art_score = full_score

            score = 0.75 * full_score + 0.25 * art_score
            matches.append(Match(card, round(score, 4), full_distance, art_distance))

        matches.sort(key=lambda m: (-m.score, m.full_distance))
        return matches[:limit]

    # -- persistence -------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps([asdict(c) for c in self.cards], indent=2), encoding="utf-8"
        )
        return out

    @classmethod
    def load(cls, path: str | Path) -> CardIndex:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(cards=[ReferenceCard(**row) for row in data])
