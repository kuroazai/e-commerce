"""Stock management.

The rule that shapes this module: **a sale must never be applied twice.**
Marketplaces resend notification emails, IMAP fetches overlap, and a retried run
sees the same message again. Double-applying decrements stock you still own, and
you find out when you cannot post an order.

Every sale is therefore keyed by its order reference and recorded before stock
moves.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..db import Database
from ..market.base import Condition, Marketplace
from .matching import best_match, match_title
from .models import InventoryItem, Listing, ListingStatus, SaleEvent

ITEMS = "inventory"
LISTINGS = "listings"
SALES = "sale_events"
#: Sales that went through but whose stock movement could not be applied.
DISCREPANCIES = "stock_discrepancies"


class InventoryError(RuntimeError):
    """The requested stock movement is not possible."""


@dataclass
class InventoryService:
    db: Database

    # -- stock -------------------------------------------------------------
    def add_item(self, item: InventoryItem) -> InventoryItem:
        if item.quantity < 0:
            raise InventoryError("quantity cannot be negative")
        self.db.insert_one(ITEMS, item.to_dict())
        return item

    def find_item(
        self, card_name: str, *, set_code: str = "", condition: Condition | None = None
    ) -> dict | None:
        query: dict = {"card_name": card_name}
        if set_code:
            query["set_code"] = set_code
        if condition:
            query["condition"] = condition.value
        return self.db.find_one(ITEMS, query)

    def resolve_item(self, card_name: str) -> tuple[dict | None, str]:
        """Find the inventory item a sale refers to. Returns (item, explanation).

        An exact name match is tried first, because that is what a sale from your
        own listing produces. Marketplace emails carry the full listing title
        instead - "Dark Magician LOB-005 1st Edition NM" - which matches nothing
        exactly, so the second pass scores the title against every item.

        A None item with a non-empty explanation is the signal to escalate.
        """
        exact = self.find_item(card_name)
        if exact is not None:
            return exact, "exact name match"

        items = self.db.find(ITEMS, {})
        match = best_match(card_name, items)
        if match is not None:
            how = "set code" if match.set_code_matched else f"title score {match.score}"
            return match.item, f"matched {match.item.get('card_name')!r} by {how}"

        candidates = match_title(card_name, items)
        if candidates:
            names = ", ".join(repr(c.item.get("card_name")) for c in candidates)
            return None, f"ambiguous between {names}"
        return None, "no inventory item resembles this title"

    def stock_level(self, card_name: str, *, set_code: str = "") -> int:
        query: dict = {"card_name": card_name}
        if set_code:
            query["set_code"] = set_code
        return sum(int(row.get("quantity", 0)) for row in self.db.find(ITEMS, query))

    def adjust_quantity(self, item_id: str, delta: int) -> int:
        record = self.db.find_one(ITEMS, {"item_id": item_id})
        if record is None:
            raise InventoryError(f"no inventory item {item_id}")
        new_quantity = int(record.get("quantity", 0)) + delta
        if new_quantity < 0:
            raise InventoryError(
                f"cannot reduce {record['card_name']} below zero "
                f"(have {record.get('quantity', 0)}, asked for {-delta})"
            )
        self.db.update_one(ITEMS, {"item_id": item_id}, {"$set": {"quantity": new_quantity}})
        return new_quantity

    # -- listings ----------------------------------------------------------
    def create_listing(self, listing: Listing) -> Listing:
        if self.db.find_one(ITEMS, {"item_id": listing.item_id}) is None:
            raise InventoryError(f"cannot list unknown item {listing.item_id}")
        self.db.insert_one(LISTINGS, listing.to_dict())
        return listing

    def active_listings(self, marketplace: Marketplace | None = None) -> list[dict]:
        query: dict = {"status": ListingStatus.ACTIVE.value}
        if marketplace:
            query["marketplace"] = marketplace.value
        return self.db.find(LISTINGS, query)

    def mark_listing_sold(self, external_id: str, marketplace: Marketplace) -> dict | None:
        listing = self.db.find_one(
            LISTINGS, {"external_id": external_id, "marketplace": marketplace.value}
        )
        if listing is None:
            return None
        self.db.update_one(
            LISTINGS,
            {"listing_id": listing["listing_id"]},
            {"$set": {"status": ListingStatus.SOLD.value}},
        )
        return listing

    # -- sales -------------------------------------------------------------
    def already_recorded(self, sale: SaleEvent) -> bool:
        """Whether this order reference has been seen before.

        Sales without a reference cannot be deduplicated, so they are always
        treated as new - better a duplicate flagged for review than a silently
        dropped sale.
        """
        if not sale.order_reference:
            return False
        return self.db.find_one(
            SALES,
            {"order_reference": sale.order_reference, "marketplace": sale.marketplace.value},
        ) is not None

    def record_sale(self, sale: SaleEvent) -> tuple[bool, str]:
        """Apply a sale. Returns (applied, explanation).

        Returns rather than raises on a duplicate: re-processing a mailbox is
        routine, not exceptional, and the caller wants a count, not a traceback.
        """
        if self.already_recorded(sale):
            return False, f"duplicate order {sale.order_reference}, already recorded"

        self.db.insert_one(SALES, sale.to_dict())

        item, how = self.resolve_item(sale.card_name)
        if item is None:
            self._flag(sale, f"could not identify the inventory item ({how})")
            return True, (
                f"recorded sale of {sale.card_name!r} but could not identify the "
                f"inventory item ({how}) - stock not adjusted"
            )

        try:
            remaining = self.adjust_quantity(item["item_id"], -sale.quantity)
        except InventoryError as exc:
            self._flag(sale, str(exc))
            return True, f"recorded sale but stock not adjusted: {exc}"

        sold_as = item.get("card_name", sale.card_name)
        note = f"{sold_as} x{sale.quantity} sold, {remaining} left"
        if how != "exact name match":
            note += f" ({how})"
        if remaining == 0:
            note += " - OUT OF STOCK, delist elsewhere"
        return True, note

    def _flag(self, sale: SaleEvent, problem: str) -> None:
        """Record that a sale went through but stock could not follow it.

        This is the case that matters most and is easiest to lose: the money has
        moved, so the sale is real, but the inventory no longer describes what is
        on the shelf. Left as a log line it gets scrolled past. Stored, it can be
        listed, counted and cleared.
        """
        self.db.insert_one(DISCREPANCIES, {
            "sale_id": sale.sale_id,
            "order_reference": sale.order_reference,
            "card_name": sale.card_name,
            "quantity": sale.quantity,
            "problem": problem,
            "resolved": False,
        })

    def discrepancies(self, *, unresolved_only: bool = True) -> list[dict]:
        """Sales whose stock movement could not be applied."""
        rows = self.db.find(DISCREPANCIES, {})
        return [r for r in rows if not r.get("resolved")] if unresolved_only else rows

    def resolve_discrepancy(self, sale_id: str) -> bool:
        """Mark a discrepancy dealt with, once you have fixed the count by hand."""
        record = self.db.find_one(DISCREPANCIES, {"sale_id": sale_id})
        if record is None:
            return False
        self.db.update_one(
            DISCREPANCIES, {"sale_id": sale_id}, {"$set": {"resolved": True}}
        )
        return True

    def sales_total_gbp(self) -> float:
        return round(sum(float(s.get("price_gbp", 0)) for s in self.db.find(SALES, {})), 2)
