"""Marketplace fees. Getting these wrong means losing money on every sale."""
from __future__ import annotations

import pytest

from cardshop.market.base import Marketplace
from cardshop.market.fees import DEFAULT_POSTAGE_COST_GBP, fees_for


def test_ebay_charges_commission_on_the_postage_too() -> None:
    """The part people get wrong.

    eBay's cut is taken on the total the buyer paid, postage included. Charging
    it on the item price alone understates the fee on every single sale.
    """
    structure = fees_for(Marketplace.EBAY_UK)
    item_only = structure.fees_on(25.00, postage_gbp=0.0)
    with_postage = structure.fees_on(25.00, postage_gbp=3.00)
    assert with_postage > item_only


def test_ebay_is_dearer_than_cardmarket_on_the_same_sale() -> None:
    sale = 25.00
    ebay = fees_for(Marketplace.EBAY_UK).fees_on(sale)
    cardmarket = fees_for(Marketplace.CARDMARKET).fees_on(sale)
    assert ebay > cardmarket


def test_net_subtracts_the_cost_of_posting_it() -> None:
    """Postage the buyer paid is income; the stamp is an expense. Both count."""
    structure = fees_for(Marketplace.EBAY_UK)
    gross_net = structure.net_on(25.00, postage_gbp=3.00, postage_cost_gbp=0.0)
    true_net = structure.net_on(25.00, postage_gbp=3.00,
                                postage_cost_gbp=DEFAULT_POSTAGE_COST_GBP)
    assert true_net == pytest.approx(gross_net - DEFAULT_POSTAGE_COST_GBP, abs=0.01)


def test_fees_scale_with_the_sale() -> None:
    structure = fees_for(Marketplace.EBAY_UK)
    assert structure.fees_on(100.00) > structure.fees_on(10.00)


def test_a_zero_sale_has_only_the_fixed_fee() -> None:
    structure = fees_for(Marketplace.EBAY_UK)
    assert structure.fees_on(0.0) == pytest.approx(structure.fixed_fee_gbp)


def test_every_marketplace_has_a_fee_structure() -> None:
    """A missing one would otherwise surface as a KeyError mid-sale."""
    for marketplace in Marketplace:
        assert fees_for(marketplace) is not None
