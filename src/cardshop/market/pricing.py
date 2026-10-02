"""Turning a market view into a price to list at."""
from __future__ import annotations

from dataclasses import dataclass

from .base import CONDITION_MULTIPLIER, Condition, Marketplace, MarketSummary
from .fees import DEFAULT_POSTAGE_COST_GBP, fees_for


@dataclass(frozen=True)
class PriceRecommendation:
    """A suggested listing price, and what it leaves after costs."""

    card_name: str
    marketplace: Marketplace
    condition: Condition
    list_price_gbp: float
    estimated_fees_gbp: float
    net_gbp: float
    basis_median_gbp: float
    confident: bool
    notes: tuple[str, ...] = ()

    @property
    def margin_percent(self) -> float:
        if self.list_price_gbp <= 0:
            return 0.0
        return round(100 * self.net_gbp / self.list_price_gbp, 1)


#: Below this, fees and postage eat the entire sale. Cards under it are worth
#: bundling rather than listing individually.
MIN_VIABLE_PRICE_GBP = 2.00


def recommend_price(
    summary: MarketSummary,
    *,
    marketplace: Marketplace = Marketplace.EBAY_UK,
    condition: Condition = Condition.NEAR_MINT,
    undercut: float = 0.05,
    postage_charged_gbp: float = 0.0,
    postage_cost_gbp: float = DEFAULT_POSTAGE_COST_GBP,
) -> PriceRecommendation:
    """Suggest a listing price from a market summary.

    Starts at the median for the condition, undercuts slightly to be the cheapest
    reasonable copy, then reports what actually lands after fees - which is the
    number that decides whether listing it is worth the postage.
    """
    notes: list[str] = []
    multiplier = CONDITION_MULTIPLIER[condition]
    target = summary.median_gbp * multiplier
    list_price = round(target * (1 - undercut), 2)

    if not summary.reliable:
        notes.append(
            f"thin or inconsistent data: {summary.sample_size} observation(s), "
            f"{summary.sold_count} completed sale(s), spread {summary.spread:.1f}x"
        )

    fee_structure = fees_for(marketplace)
    fees = fee_structure.fees_on(list_price, postage_charged_gbp)
    net = fee_structure.net_on(list_price, postage_charged_gbp, postage_cost_gbp)

    if net <= 0:
        notes.append("fees and postage exceed the sale price - bundle rather than list")
    elif list_price < MIN_VIABLE_PRICE_GBP:
        notes.append(f"below the {MIN_VIABLE_PRICE_GBP:.2f} viability floor - consider bundling")

    return PriceRecommendation(
        card_name=summary.card_name,
        marketplace=marketplace,
        condition=condition,
        list_price_gbp=list_price,
        estimated_fees_gbp=fees,
        net_gbp=net,
        basis_median_gbp=summary.median_gbp,
        confident=summary.reliable and net > 0 and list_price >= MIN_VIABLE_PRICE_GBP,
        notes=tuple(notes),
    )
