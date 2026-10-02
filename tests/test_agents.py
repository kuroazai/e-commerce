"""The agent layer.

Two things are being checked. That the tools return what they claim to, and -
more importantly - that the whole system still works with no model configured.
Running deterministic-only is a supported mode, so it needs a test.
"""
from __future__ import annotations

import json

import pytest

from cardshop.agents import AgentTriage, build_tool_functions
from cardshop.db import InMemoryDatabase
from cardshop.inventory import InventoryItem, InventoryService
from cardshop.market.base import Condition, Marketplace, PriceQuote
from cardshop.market.providers import StaticPriceProvider
from cardshop.vendors import InboundEmail


@pytest.fixture
def inventory() -> InventoryService:
    service = InventoryService(InMemoryDatabase())
    service.add_item(InventoryItem(card_name="Dark Magician", set_code="LOB-005",
                                   quantity=3, cost_gbp=4.0, location="Binder A"))
    service.add_item(InventoryItem(card_name="Mirror Force", set_code="MRD-138",
                                   quantity=1, cost_gbp=4.0, location="Box 2"))
    return service


def test_stock_tool_reports_quantity_and_location(inventory: InventoryService) -> None:
    tools = build_tool_functions(inventory)
    payload = json.loads(tools["look_up_stock"]("Dark Magician"))

    assert payload["total"] == 3
    assert payload["entries"][0]["location"] == "Binder A"
    assert payload["entries"][0]["set_code"] == "LOB-005"


def test_stock_tool_on_something_not_held(inventory: InventoryService) -> None:
    tools = build_tool_functions(inventory)
    payload = json.loads(tools["look_up_stock"]("Pot of Greed"))
    assert payload["total"] == 0
    assert payload["entries"] == []


def test_title_tool_returns_ranked_candidates(inventory: InventoryService) -> None:
    tools = build_tool_functions(inventory)
    payload = json.loads(
        tools["match_listing_title"]("Yugioh Dark Magician LOB-005 1st Edition NM")
    )
    assert payload["candidates"][0]["card_name"] == "Dark Magician"
    assert payload["candidates"][0]["confident"] is True


def test_price_tool_reports_net_after_fees(inventory: InventoryService) -> None:
    provider = StaticPriceProvider(catalogue={
        "Dark Magician": [
            PriceQuote(card_name="Dark Magician", price_gbp=25.00,
                       marketplace=Marketplace.EBAY_UK, condition=Condition.NEAR_MINT,
                       sold=True),
            PriceQuote(card_name="Dark Magician", price_gbp=27.00,
                       marketplace=Marketplace.EBAY_UK, condition=Condition.NEAR_MINT,
                       sold=True),
        ]
    })
    tools = build_tool_functions(inventory, [provider])
    payload = json.loads(tools["price_card"]("Dark Magician"))

    assert payload["observations"] == 2
    assert payload["net_after_fees_gbp"] < payload["suggested_list_gbp"]


def test_price_tool_says_so_when_there_is_no_data(inventory: InventoryService) -> None:
    tools = build_tool_functions(inventory, [StaticPriceProvider(catalogue={})])
    payload = json.loads(tools["price_card"]("Dark Magician"))
    assert "error" in payload


def test_triage_without_a_model_reports_instead_of_failing(
    inventory: InventoryService,
) -> None:
    """No model is a supported configuration, not a broken one."""
    triage = AgentTriage(inventory=inventory, model=None)
    assert not triage.available

    result = triage.parse_unrecognised_email(
        InboundEmail("odd@example.com", "a new format", "body")
    )
    assert not result.ok
    assert "no model configured" in result.reason
    assert triage.escalations == ["unparsed email: 'a new format'"]


def test_triage_enforces_its_escalation_budget(inventory: InventoryService) -> None:
    """A mailbox full of junk would otherwise escalate every message, every
    run, and spend money doing it."""
    triage = AgentTriage(inventory=inventory, model=None, max_escalations=2)
    for index in range(4):
        triage.parse_unrecognised_email(
            InboundEmail("odd@example.com", f"subject {index}", "body")
        )

    assert len(triage.escalations) == 2
    assert triage.exhausted

    final = triage.parse_unrecognised_email(
        InboundEmail("odd@example.com", "one more", "body")
    )
    assert "budget" in final.reason


def test_triage_extracts_a_sale_from_an_unknown_format() -> None:
    """A stub model stands in for the real one. What is being tested is the
    handling of the response, which is the part that can break."""
    service = InventoryService(InMemoryDatabase())

    def stub(messages):
        return (
            '```json\n{"marketplace": "ebay_uk", "card_name": "Pot of Greed", '
            '"price_gbp": 3.5, "quantity": 1, "order_reference": "A-1", '
            '"buyer": "someone", "postage_gbp": 1.55}\n```'
        )

    triage = AgentTriage(inventory=service, model=stub)
    result = triage.parse_unrecognised_email(
        InboundEmail("new@marketplace.com", "sold", "body")
    )

    assert result.ok
    assert result.sale is not None
    assert result.sale.card_name == "Pot of Greed"
    assert result.sale.price_gbp == pytest.approx(3.5)
    # Never applied silently: a hallucinated order is a stock count nobody
    # notices is wrong.
    assert "verify" in result.reason


def test_triage_rejects_a_model_response_that_is_not_a_sale() -> None:
    service = InventoryService(InMemoryDatabase())
    triage = AgentTriage(inventory=service, model=lambda m: '{"not_a_sale": true}')
    result = triage.parse_unrecognised_email(InboundEmail("x@y.com", "newsletter", "body"))
    assert not result.ok
    assert "not to be a sale" in result.reason


def test_triage_survives_unusable_model_output() -> None:
    service = InventoryService(InMemoryDatabase())

    for response in ["not json at all", '{"card_name": "x"}', '{"marketplace": "nonsense"}']:
        triage = AgentTriage(inventory=service, model=lambda m, r=response: r)
        result = triage.parse_unrecognised_email(InboundEmail("x@y.com", "s", "b"))
        assert not result.ok
        assert result.reason


def test_triage_survives_a_model_that_raises() -> None:
    service = InventoryService(InMemoryDatabase())

    def broken(messages):
        raise RuntimeError("the endpoint is down")

    triage = AgentTriage(inventory=service, model=broken)
    result = triage.parse_unrecognised_email(InboundEmail("x@y.com", "s", "b"))
    assert not result.ok
    assert "the endpoint is down" in result.reason


def test_triage_resolves_an_ambiguous_title(inventory: InventoryService) -> None:
    candidates = [
        {"card_name": "Dark Magician", "set_code": "LOB-005", "quantity": 3},
        {"card_name": "Dark Magician", "set_code": "SDY-006", "quantity": 1},
    ]
    triage = AgentTriage(inventory=inventory, model=lambda m: "1")
    outcome = triage.resolve_ambiguous_title("Dark Magician NM", candidates)
    assert outcome.handled

    refused = AgentTriage(inventory=inventory, model=lambda m: "NONE")
    assert not refused.resolve_ambiguous_title("Dark Magician NM", candidates).handled

    nonsense = AgentTriage(inventory=inventory, model=lambda m: "the second one")
    assert not nonsense.resolve_ambiguous_title("Dark Magician NM", candidates).handled
