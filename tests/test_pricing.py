"""What to list a card at, and what you actually keep."""
from __future__ import annotations

import pytest

from cardshop.market.base import Condition, Marketplace, PriceQuote, summarise
from cardshop.market.pricing import MIN_VIABLE_PRICE_GBP, recommend_price


def quote(price: float, *, sold: bool = True,
          condition: Condition = Condition.NEAR_MINT) -> PriceQuote:
    return PriceQuote(card_name="Dark Magician", price_gbp=price,
                      marketplace=Marketplace.EBAY_UK, condition=condition, sold=sold)


def test_completed_sales_beat_asking_prices() -> None:
    """Anyone can ask any price. Only a completed sale is evidence."""
    with_optimist = summarise([quote(25.0), quote(26.0), quote(99.0, sold=False)])
    sold_only = summarise([quote(25.0), quote(26.0)])
    assert with_optimist.median_gbp == pytest.approx(sold_only.median_gbp)


def test_asking_prices_are_used_when_there_is_nothing_better() -> None:
    summary = summarise([quote(30.0, sold=False), quote(32.0, sold=False)])
    assert summary.median_gbp > 0
    assert summary.sold_count == 0


def test_a_single_observation_is_not_trusted() -> None:
    assert not summarise([quote(25.0)]).reliable


def test_several_agreeing_sales_are_trusted() -> None:
    assert summarise([quote(25.0), quote(26.0), quote(25.5), quote(26.5)]).reliable


def test_a_played_copy_is_normalised_to_near_mint() -> None:
    """A Light Played copy at a low price does not mean a NM copy is cheap."""
    played = quote(18.0, condition=Condition.LIGHT_PLAYED)
    assert played.normalised_to_nm() > played.price_gbp


def test_recommendation_undercuts_the_median() -> None:
    summary = summarise([quote(25.0), quote(26.0), quote(25.5)], "Dark Magician")
    recommendation = recommend_price(summary, marketplace=Marketplace.EBAY_UK)
    assert recommendation.list_price_gbp < summary.median_gbp
    assert recommendation.net_gbp < recommendation.list_price_gbp


def test_cardmarket_leaves_more_than_ebay_on_the_same_card() -> None:
    summary = summarise([quote(25.0), quote(26.0), quote(25.5)], "Dark Magician")
    ebay = recommend_price(summary, marketplace=Marketplace.EBAY_UK)
    cardmarket = recommend_price(summary, marketplace=Marketplace.CARDMARKET)
    assert cardmarket.net_gbp > ebay.net_gbp


def test_a_cheap_card_is_refused_rather_than_listed_at_a_loss() -> None:
    """Fees plus a stamp exceed the sale price. Listing it loses money, so the
    recommendation says to bundle it instead."""
    summary = summarise([quote(0.80), quote(0.90), quote(0.85)], "Common Card")
    recommendation = recommend_price(summary, marketplace=Marketplace.EBAY_UK)

    assert recommendation.net_gbp <= 0 or recommendation.list_price_gbp < MIN_VIABLE_PRICE_GBP
    assert not recommendation.confident
    assert recommendation.notes


def test_a_recommendation_from_thin_data_is_not_confident() -> None:
    assert not recommend_price(summarise([quote(25.0)], "Dark Magician")).confident


def test_no_data_does_not_crash() -> None:
    recommendation = recommend_price(summarise([], "Unknown Card"))
    assert not recommendation.confident
    assert recommendation.notes
