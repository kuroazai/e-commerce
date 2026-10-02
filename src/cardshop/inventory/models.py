"""Stock, listings and sales."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ..market.base import Condition, Marketplace


def _new_id() -> str:
    return uuid.uuid4().hex[:12]



def _now() -> datetime:
    """Timezone-aware UTC.

    `datetime.utcnow` returns a naive value and is deprecated, and comparing a
    naive datetime with an aware one raises.

    `timezone.utc` rather than `datetime.UTC`: the latter was added in 3.11 and
    this package supports 3.10, where importing it fails at module scope and
    takes the whole package with it.
    """
    return datetime.now(timezone.utc)

class ListingStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SOLD = "sold"
    CANCELLED = "cancelled"


@dataclass
class InventoryItem:
    """A physical card you own."""

    card_name: str
    set_code: str = ""
    condition: Condition = Condition.NEAR_MINT
    quantity: int = 1
    cost_gbp: float = 0.0  # what you paid, for margin
    location: str = ""  # binder, box, page - so you can find it to post it
    item_id: str = field(default_factory=_new_id)
    scan_confidence: float = 0.0  # 0.0 when entered by hand

    def to_dict(self) -> dict:
        data = asdict(self)
        data["condition"] = self.condition.value
        return data


@dataclass
class Listing:
    """An item offered on a marketplace."""

    item_id: str
    marketplace: Marketplace
    price_gbp: float
    status: ListingStatus = ListingStatus.DRAFT
    external_id: str = ""  # the marketplace's own id, how emails are matched back
    quantity: int = 1
    listing_id: str = field(default_factory=_new_id)
    created: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["marketplace"] = self.marketplace.value
        data["status"] = self.status.value
        data["created"] = self.created.isoformat()
        return data


@dataclass
class SaleEvent:
    """A confirmed sale, usually parsed out of a marketplace email."""

    marketplace: Marketplace
    card_name: str
    price_gbp: float
    quantity: int = 1
    order_reference: str = ""
    buyer: str = ""
    postage_gbp: float = 0.0
    occurred: datetime = field(default_factory=_now)
    raw_subject: str = ""
    sale_id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["marketplace"] = self.marketplace.value
        data["occurred"] = self.occurred.isoformat()
        return data
