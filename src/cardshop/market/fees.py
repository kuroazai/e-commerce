"""What a sale actually nets, after the platform has taken its cut.

Listing at the market median and assuming that is what you receive is how a
nominally profitable inventory loses money. Every marketplace takes a percentage,
most take a fixed fee too, and postage comes out of the seller's side on almost
every low-value card.

Rates are UK-facing and change; they live here so there is one place to update
and `effective_from` records when they were checked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .base import Marketplace


@dataclass(frozen=True)
class FeeStructure:
    """Marketplace costs. Percentages are fractions, not whole numbers."""

    marketplace: Marketplace
    commission: float
    fixed_fee_gbp: float = 0.0
    payment_percent: float = 0.0
    effective_from: date = date(2026, 1, 1)

    def fees_on(self, sale_price_gbp: float, postage_gbp: float = 0.0) -> float:
        """Total deducted from a sale.

        Commission is charged on the postage too on most platforms, which is the
        part sellers routinely forget.
        """
        chargeable = sale_price_gbp + postage_gbp
        return round(
            chargeable * (self.commission + self.payment_percent) + self.fixed_fee_gbp, 2
        )

    def net_on(self, sale_price_gbp: float, postage_gbp: float = 0.0,
               postage_cost_gbp: float = 0.0) -> float:
        """What reaches your account, after fees and the cost of posting it."""
        return round(
            sale_price_gbp + postage_gbp
            - self.fees_on(sale_price_gbp, postage_gbp)
            - postage_cost_gbp,
            2,
        )


#: Indicative UK rates. Verify against the current schedule before relying on
#: them for anything at volume.
FEES = {
    Marketplace.EBAY_UK: FeeStructure(
        Marketplace.EBAY_UK, commission=0.128, fixed_fee_gbp=0.30
    ),
    Marketplace.CARDMARKET: FeeStructure(
        Marketplace.CARDMARKET, commission=0.05
    ),
    Marketplace.TCGPLAYER: FeeStructure(
        Marketplace.TCGPLAYER, commission=0.1025, payment_percent=0.025, fixed_fee_gbp=0.25
    ),
    Marketplace.MANUAL: FeeStructure(Marketplace.MANUAL, commission=0.0),
}

#: Royal Mail Large Letter, the normal way a few cards travel in the UK.
DEFAULT_POSTAGE_COST_GBP = 1.55


def fees_for(marketplace: Marketplace) -> FeeStructure:
    return FEES.get(marketplace, FEES[Marketplace.MANUAL])
