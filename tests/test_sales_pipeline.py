"""The pipeline: mailbox in, stock and notifications out."""
from __future__ import annotations

import pytest

from cardshop.db import InMemoryDatabase
from cardshop.inventory import InventoryItem, InventoryService
from cardshop.vendors import (
    CollectingNotifier,
    InboundEmail,
    MemoryMailbox,
    SalesPipeline,
)

EBAY_SALE = InboundEmail(
    "ebay@ebay.co.uk",
    "Your item sold! Dark Magician LOB-005",
    "Item: Dark Magician LOB-005 1st Edition NM\n"
    "Order number: 12-34567-89012\nBuyer: cardfan99\nTotal: GBP 24.50\nPostage: GBP 1.55\n",
    uid="1",
)
CARDMARKET_SALE = InboundEmail(
    "noreply@cardmarket.com",
    "Cardmarket: You have sold 1 article",
    "1x Mirror Force (MRD-138)\nTotal: 18.00 GBP\nOrder: 998877\nUsername: deckbuilder_de\n",
    uid="2",
)
JUNK = InboundEmail("spam@example.com", "CHEAP CARDS BUY NOW", "unrelated junk", uid="3")


@pytest.fixture
def inventory() -> InventoryService:
    service = InventoryService(InMemoryDatabase())
    service.add_item(InventoryItem(card_name="Dark Magician", set_code="LOB-005",
                                   quantity=3, cost_gbp=4.0))
    service.add_item(InventoryItem(card_name="Mirror Force", set_code="MRD-138",
                                   quantity=1, cost_gbp=4.0))
    return service


def build(inventory: InventoryService, messages: list[InboundEmail]):
    notifier = CollectingNotifier()
    mailbox = MemoryMailbox(messages=list(messages))
    return SalesPipeline(inventory=inventory, mailbox=mailbox, notifier=notifier), notifier


def test_records_sales_and_decrements_stock(inventory: InventoryService) -> None:
    pipeline, _ = build(inventory, [EBAY_SALE, CARDMARKET_SALE])
    result = pipeline.run()

    assert result.recorded == 2
    assert inventory.stock_level("Dark Magician") == 2
    assert inventory.stock_level("Mirror Force") == 0


def test_a_messy_listing_title_still_finds_the_item(inventory: InventoryService) -> None:
    """The eBay title is "Dark Magician LOB-005 1st Edition NM" and the item is
    "Dark Magician". Exact matching fails here, and stock quietly stops moving."""
    pipeline, _ = build(inventory, [EBAY_SALE])
    pipeline.run()
    assert inventory.stock_level("Dark Magician") == 2


def test_a_dry_run_changes_nothing_and_notifies_nobody(inventory: InventoryService) -> None:
    pipeline, notifier = build(inventory, [EBAY_SALE, JUNK])
    result = pipeline.run(dry_run=True)

    assert result.recorded == 0
    assert inventory.stock_level("Dark Magician") == 3
    assert notifier.sent == []
    assert any("would record" in note for note in result.notes)


def test_reprocessing_the_same_mailbox_does_not_double_count(
    inventory: InventoryService,
) -> None:
    """Re-running is routine - a crash, a cron overlap, a manual retry. The
    order reference is the idempotency key."""
    pipeline, _ = build(inventory, [EBAY_SALE, CARDMARKET_SALE])
    pipeline.run()

    pipeline.mailbox.processed.clear()  # force the messages to be seen again
    second = pipeline.run()

    assert second.recorded == 0
    assert second.duplicates == 2
    assert inventory.stock_level("Dark Magician") == 2
    assert inventory.stock_level("Mirror Force") == 0


def test_an_unparsed_message_is_not_marked_processed(inventory: InventoryService) -> None:
    """It needs a human, so it must still be there next time."""
    pipeline, notifier = build(inventory, [JUNK])
    result = pipeline.run()

    assert result.needs_attention
    assert result.unparsed
    assert JUNK.uid not in pipeline.mailbox.processed
    assert notifier.sent and notifier.sent[0][0] == "Unrecognised email"


def test_a_parsed_message_is_marked_processed(inventory: InventoryService) -> None:
    pipeline, _ = build(inventory, [EBAY_SALE])
    pipeline.run()
    assert EBAY_SALE.uid in pipeline.mailbox.processed


def test_overselling_records_the_sale_and_flags_the_discrepancy(
    inventory: InventoryService,
) -> None:
    """The money has moved, so the sale is real. But stock cannot go negative,
    and pretending it can is worse than saying so."""
    oversell = InboundEmail(
        "ebay@ebay.co.uk", "Your item sold!",
        "Item: Mirror Force MRD-138\nOrder number: 77-88888-99999\n"
        "Quantity: 5\nTotal: GBP 90.00\n",
        uid="9",
    )
    pipeline, notifier = build(inventory, [oversell])
    result = pipeline.run()

    assert result.recorded == 1            # the sale happened
    assert result.discrepancies            # but stock could not follow
    assert result.needs_attention
    assert inventory.stock_level("Mirror Force") == 1  # not negative
    assert notifier.sent[0][0] == "Sale - STOCK NEEDS FIXING"

    outstanding = inventory.discrepancies()
    assert len(outstanding) == 1
    assert outstanding[0]["order_reference"] == "77-88888-99999"


def test_a_discrepancy_can_be_cleared(inventory: InventoryService) -> None:
    oversell = InboundEmail(
        "ebay@ebay.co.uk", "Your item sold!",
        "Item: Mirror Force MRD-138\nOrder number: 77-88888-99999\n"
        "Quantity: 5\nTotal: GBP 90.00\n",
        uid="9",
    )
    pipeline, _ = build(inventory, [oversell])
    pipeline.run()

    sale_id = inventory.discrepancies()[0]["sale_id"]
    assert inventory.resolve_discrepancy(sale_id)
    assert inventory.discrepancies() == []
    assert not inventory.resolve_discrepancy("not-a-real-id")


def test_a_sale_of_something_not_stocked_is_recorded_and_flagged(
    inventory: InventoryService,
) -> None:
    unknown = InboundEmail(
        "ebay@ebay.co.uk", "Your item sold!",
        "Item: Pot of Greed LOB-119\nOrder number: 55-55555-55555\nTotal: GBP 3.00\n",
        uid="7",
    )
    pipeline, _ = build(inventory, [unknown])
    result = pipeline.run()

    assert result.recorded == 1
    assert result.discrepancies
    assert inventory.discrepancies()[0]["card_name"] == "Pot of Greed LOB-119"


def test_revenue_is_totalled(inventory: InventoryService) -> None:
    pipeline, _ = build(inventory, [EBAY_SALE, CARDMARKET_SALE])
    pipeline.run()
    assert inventory.sales_total_gbp() == pytest.approx(42.50)


def test_an_empty_mailbox_is_not_an_error(inventory: InventoryService) -> None:
    pipeline, notifier = build(inventory, [])
    result = pipeline.run()
    assert result.processed == 0
    assert not result.needs_attention
    assert notifier.sent == []
