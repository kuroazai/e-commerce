"""smolagents tools.

Each tool is a thin wrapper over something the package already does
deterministically. That is on purpose: the agent decides *which* action to take
and reads ambiguous input, it does not reimplement pricing or stock arithmetic.
Business rules that must be right every time should never depend on a sampled
token.

Tools are built by a factory rather than declared at module scope, so they close
over a real inventory service and price providers instead of reaching for
globals.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..inventory.matching import match_title
from ..inventory.service import ITEMS, InventoryService
from ..market.base import Condition, Marketplace, PriceProvider, summarise
from ..market.pricing import recommend_price


def build_tool_functions(
    inventory: InventoryService,
    providers: list[PriceProvider] | None = None,
) -> dict[str, Callable[..., str]]:
    """Plain callables, returning JSON strings.

    Kept free of smolagents imports so the whole tool layer is unit-testable
    without the agent framework installed.
    """
    providers = providers or []

    def look_up_stock(card_name: str) -> str:
        """How many of a card are in stock, and where."""
        rows = inventory.db.find(ITEMS, {"card_name": card_name})
        return json.dumps({
            "card_name": card_name,
            "total": sum(int(r.get("quantity", 0)) for r in rows),
            "entries": [
                {"item_id": r.get("item_id"), "set_code": r.get("set_code"),
                 "condition": r.get("condition"), "quantity": r.get("quantity"),
                 "location": r.get("location")}
                for r in rows
            ],
        })

    def match_listing_title(title: str) -> str:
        """Candidate inventory items for a messy marketplace title."""
        candidates = match_title(title, inventory.db.find(ITEMS, {}))
        return json.dumps({
            "title": title,
            "candidates": [
                {"item_id": m.item.get("item_id"), "card_name": m.item.get("card_name"),
                 "set_code": m.item.get("set_code"), "score": m.score,
                 "set_code_matched": m.set_code_matched, "confident": m.confident}
                for m in candidates
            ],
        })

    def price_card(card_name: str, condition: str = "NM") -> str:
        """Market price and a suggested eBay UK listing price, net of fees."""
        quotes: list[Any] = []
        failures: list[str] = []
        for provider in providers:
            try:
                quotes.extend(provider.quotes(card_name))
            except Exception as exc:  # noqa: BLE001
                # Broad on purpose: a provider is a network call to someone
                # else's API, and one of them being down must still leave the
                # model an answer from the others.
                failures.append(f"{type(provider).__name__}: {exc}")

        if not quotes:
            return json.dumps({
                "card_name": card_name,
                "error": "no price data available",
                "failures": failures,
            })

        summary = summarise(quotes, card_name)
        try:
            grade = Condition(condition.upper())
        except ValueError:
            grade = Condition.NEAR_MINT
        recommendation = recommend_price(summary, marketplace=Marketplace.EBAY_UK,
                                         condition=grade)
        return json.dumps({
            "card_name": card_name,
            "median_gbp": summary.median_gbp,
            "observations": summary.sample_size,
            "completed_sales": summary.sold_count,
            "reliable": summary.reliable,
            "suggested_list_gbp": recommendation.list_price_gbp,
            "net_after_fees_gbp": recommendation.net_gbp,
            "confident": recommendation.confident,
            "notes": list(recommendation.notes),
            # Surfaced rather than hidden: a price built from one provider
            # because the other was down is worth less than one from both.
            "failures": failures,
        })

    return {
        "look_up_stock": look_up_stock,
        "match_listing_title": match_listing_title,
        "price_card": price_card,
    }


def build_smolagent_tools(
    inventory: InventoryService,
    providers: list[PriceProvider] | None = None,
) -> list:
    """The same functions, wrapped as smolagents tools.

    Imported lazily so `import cardshop` never requires smolagents.
    """
    try:
        from smolagents import tool
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ImportError(
            "smolagents is required for the agent layer: pip install 'cardshop[agents]'"
        ) from exc

    functions = build_tool_functions(inventory, providers)

    @tool
    def look_up_stock(card_name: str) -> str:
        """Look up how many of a card are in stock and where they are kept.

        Args:
            card_name: The exact card name as held in inventory.
        """
        return functions["look_up_stock"](card_name)

    @tool
    def match_listing_title(title: str) -> str:
        """Find which inventory item a marketplace listing title refers to.

        Args:
            title: The raw listing title from eBay or Cardmarket.
        """
        return functions["match_listing_title"](title)

    @tool
    def price_card(card_name: str, condition: str = "NM") -> str:
        """Get the market price and a suggested listing price net of fees.

        Args:
            card_name: The card to price.
            condition: Grade - MT, NM, EX, GD, LP, PL or PO.
        """
        return functions["price_card"](card_name, condition)

    return [look_up_stock, match_listing_title, price_card]
