"""Prices out of marketplace emails, in either currency order."""
from __future__ import annotations

import pytest

from cardshop.vendors.parsers import money_after, money_after_with_currency, to_gbp


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Total: GBP 24.50", 24.50),
        ("Total: \u00a324.50", 24.50),
        ("Total: 18.00 GBP", 18.00),       # Cardmarket writes it this way round
        ("Total: 18.00 EUR", 18.00),
        ("Total: \u20ac18.00", 18.00),
        ("Total: GBP 1,250.00", 1250.00),
        ("Total: 18 GBP", 18.00),
    ],
)
def test_reads_an_amount_whichever_side_the_currency_is_on(body: str, expected: float) -> None:
    """eBay UK puts GBP first, Cardmarket puts it last.

    Accepting only one order means every price from the other marketplace fails
    to parse, and the sale is dropped without anything looking broken.
    """
    assert money_after(("Total",), body) == pytest.approx(expected)


def test_missing_amount_is_none_not_zero() -> None:
    """Zero would be indistinguishable from a free item."""
    assert money_after(("Total",), "no money here") is None


def test_picks_the_labelled_amount_not_the_first_number() -> None:
    body = "Reference 12345\nPostage: GBP 1.55\nTotal: GBP 24.50"
    assert money_after(("Total",), body) == pytest.approx(24.50)
    assert money_after(("Postage", "Shipping"), body) == pytest.approx(1.55)


def test_reports_the_currency_it_found() -> None:
    assert money_after_with_currency(("Total",), "Total: 18.00 EUR") == (18.00, "EUR")
    assert money_after_with_currency(("Total",), "Total: GBP 18.00") == (18.00, "GBP")


def test_converts_euros_and_leaves_pounds_alone() -> None:
    assert to_gbp(20.00, "EUR", 0.85) == pytest.approx(17.00)
    assert to_gbp(20.00, "GBP", 0.85) == pytest.approx(20.00)
