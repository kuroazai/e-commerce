"""Marketplace abstractions.

Every provider returns the same `PriceQuote`, so pricing logic never branches on
which site a number came from. Adding a marketplace means writing one adapter.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Protocol


class Marketplace(str, Enum):
    EBAY_UK = "ebay_uk"
    CARDMARKET = "cardmarket"
    TCGPLAYER = "tcgplayer"
    MANUAL = "manual"


class Condition(str, Enum):
    """Cardmarket's grades. eBay is looser, so adapters map onto these."""

    MINT = "MT"
    NEAR_MINT = "NM"
    EXCELLENT = "EX"
    GOOD = "GD"
    LIGHT_PLAYED = "LP"
    PLAYED = "PL"
    POOR = "PO"


#: Rough multipliers off a Near Mint reference price. Condition is the single
#: biggest driver of card value after the card itself, so pricing everything at
#: NM is how you end up with returns.
CONDITION_MULTIPLIER = {
    Condition.MINT: 1.10,
    Condition.NEAR_MINT: 1.00,
    Condition.EXCELLENT: 0.85,
    Condition.GOOD: 0.70,
    Condition.LIGHT_PLAYED: 0.55,
    Condition.PLAYED: 0.40,
    Condition.POOR: 0.25,
}


@dataclass(frozen=True)
class PriceQuote:
    """One observed price, normalised to GBP."""

    marketplace: Marketplace
    card_name: str
    price_gbp: float
    condition: Condition = Condition.NEAR_MINT
    set_code: str = ""
    sold: bool = False  # a completed sale, not an asking price
    observed: date = field(default_factory=date.today)
    url: str = ""

    def normalised_to_nm(self) -> float:
        """This price adjusted to what Near Mint would be worth.

        Without this, averaging a played copy against a mint one produces a
        number that describes neither.
        """
        multiplier = CONDITION_MULTIPLIER[self.condition]
        return self.price_gbp / multiplier if multiplier else self.price_gbp


class PriceProvider(Protocol):
    """A source of prices for a named card."""

    marketplace: Marketplace

    def quotes(self, card_name: str, *, set_code: str = "") -> list[PriceQuote]: ...


@dataclass(frozen=True)
class MarketSummary:
    """What the market says a card is worth, and how much to trust it."""

    card_name: str
    sample_size: int
    median_gbp: float
    low_gbp: float
    high_gbp: float
    sold_count: int
    sources: tuple[Marketplace, ...]

    @property
    def spread(self) -> float:
        """High over low. A wide spread means the market disagrees with itself."""
        return self.high_gbp / self.low_gbp if self.low_gbp > 0 else 0.0

    @property
    def reliable(self) -> bool:
        """Whether this is worth pricing against automatically.

        Needs enough observations, at least one completed sale, and a spread that
        is not absurd. Asking prices alone tell you what sellers hope for, not
        what buyers paid.
        """
        return self.sample_size >= 3 and self.sold_count >= 1 and self.spread <= 4.0


def summarise(quotes: list[PriceQuote], card_name: str = "") -> MarketSummary:
    """Collapse quotes into one view, weighting completed sales.

    Median rather than mean: one mispriced listing at 50x should not move the
    number, and on thin markets it always eventually appears.
    """
    if not quotes:
        return MarketSummary(card_name, 0, 0.0, 0.0, 0.0, 0, ())

    sold = [q for q in quotes if q.sold]
    # Completed sales are what the card is worth. Asking prices are only used
    # when nothing has actually sold.
    basis = sold or quotes
    values = sorted(q.normalised_to_nm() for q in basis)

    return MarketSummary(
        card_name=card_name or quotes[0].card_name,
        sample_size=len(basis),
        median_gbp=round(statistics.median(values), 2),
        low_gbp=round(values[0], 2),
        high_gbp=round(values[-1], 2),
        sold_count=len(sold),
        sources=tuple(sorted({q.marketplace for q in quotes}, key=lambda m: m.value)),
    )
