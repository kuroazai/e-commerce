"""Parsing the emails marketplaces actually send."""
from __future__ import annotations

import pytest

from cardshop.market.base import Marketplace
from cardshop.vendors import parse_email

EBAY = "ebay@ebay.co.uk"
CARDMARKET = "noreply@cardmarket.com"

EBAY_BODY = """Congratulations, your item sold.
Item: Dark Magician LOB-005 1st Edition NM
Order number: 12-34567-89012
Buyer: cardfan99
Total: GBP 24.50
Postage: GBP 1.55
"""


def test_parses_an_ebay_sale() -> None:
    result = parse_email(EBAY, "Your item sold! Dark Magician LOB-005", EBAY_BODY)
    assert result.ok
    sale = result.sale
    assert sale is not None
    assert sale.marketplace is Marketplace.EBAY_UK
    assert sale.card_name == "Dark Magician LOB-005 1st Edition NM"
    assert sale.price_gbp == pytest.approx(24.50)
    assert sale.postage_gbp == pytest.approx(1.55)
    assert sale.order_reference == "12-34567-89012"
    assert sale.buyer == "cardfan99"
    assert sale.quantity == 1


def test_ebay_title_comes_from_the_body_not_the_subject_prose() -> None:
    """The subject is prose wrapped around the title.

    Taking it from the subject leaves the punctuation attached - "! Dark
    Magician" - which then matches nothing in inventory.
    """
    result = parse_email(EBAY, "Your item sold! Dark Magician LOB-005", EBAY_BODY)
    assert result.sale is not None
    assert not result.sale.card_name.startswith("!")


def test_ebay_falls_back_to_the_subject_when_the_body_has_no_item_line() -> None:
    result = parse_email(
        EBAY, "Your item sold! Mirror Force MRD-138",
        "Order number: 99-11111-22222\nSold for: GBP 18.00\n",
    )
    assert result.ok
    assert result.sale is not None
    assert result.sale.card_name == "Mirror Force MRD-138"


def test_ebay_honours_quantity() -> None:
    result = parse_email(
        EBAY, "Your item sold!",
        "Item: Dark Magician\nOrder number: 12-34567-89012\nQuantity: 3\nTotal: GBP 60.00\n",
    )
    assert result.sale is not None
    assert result.sale.quantity == 3


def test_parses_a_cardmarket_sale_and_converts_the_currency() -> None:
    """Cardmarket settles in euros. Storing that in `price_gbp` unconverted is
    not a rounding error, it is a wrong number in every later calculation."""
    result = parse_email(
        CARDMARKET, "Cardmarket: You have sold 1 article",
        "You sold:\n1x Mirror Force (MRD-138)\nTotal: 18.00 EUR\n"
        "Order: 998877\nUsername: deckbuilder_de\n",
    )
    assert result.ok
    sale = result.sale
    assert sale is not None
    assert sale.marketplace is Marketplace.CARDMARKET
    assert sale.card_name == "Mirror Force (MRD-138)"
    assert sale.quantity == 1
    assert sale.price_gbp == pytest.approx(15.30)  # 18.00 EUR at 0.85
    assert sale.order_reference == "998877"
    assert "EUR" in result.reason


def test_cardmarket_leaves_a_gbp_amount_alone() -> None:
    result = parse_email(
        CARDMARKET, "Cardmarket: You have sold 1 article",
        "1x Mirror Force (MRD-138)\nTotal: 18.00 GBP\nOrder: 998877\n",
    )
    assert result.sale is not None
    assert result.sale.price_gbp == pytest.approx(18.00)
    assert result.reason == ""


def test_cardmarket_reads_a_price_on_the_article_line() -> None:
    result = parse_email(
        CARDMARKET, "Cardmarket: order 445566 sold",
        "2x Dark Magician (LOB-005) 12.50 EUR\nOrder ID: 445566\nShipping: 2.20 EUR\n",
    )
    assert result.ok
    sale = result.sale
    assert sale is not None
    assert sale.card_name == "Dark Magician (LOB-005)"
    assert sale.quantity == 2
    assert sale.price_gbp == pytest.approx(10.62)
    assert sale.postage_gbp == pytest.approx(1.87)


def test_an_unknown_sender_is_not_guessed_at() -> None:
    """A wrong parse silently decrements the wrong stock. Refusing is cheaper."""
    result = parse_email("spam@example.com", "CHEAP CARDS BUY NOW", "unrelated junk")
    assert not result.ok
    assert "no parser recognised" in result.reason


def test_a_sale_email_without_an_order_reference_is_refused() -> None:
    """Without a reference there is no idempotency key, so re-processing the
    mailbox would double-count the sale."""
    result = parse_email(EBAY, "Your item sold!", "Item: Dark Magician\nTotal: GBP 24.50\n")
    assert not result.ok
    assert "order number" in result.reason.lower()


def test_a_sale_email_without_a_price_is_refused() -> None:
    result = parse_email(EBAY, "Your item sold!",
                         "Item: Dark Magician\nOrder number: 12-34567-89012\n")
    assert not result.ok
    assert "price" in result.reason.lower()


def test_an_ebay_newsletter_is_not_treated_as_a_sale() -> None:
    result = parse_email(EBAY, "Deals of the week", "Lots of nice things to buy")
    assert not result.ok
