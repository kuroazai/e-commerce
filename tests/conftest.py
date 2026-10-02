"""Shared fixtures."""
from __future__ import annotations

import pytest

from cardshop.db import InMemoryDatabase
from cardshop.inventory import InventoryItem, InventoryService


@pytest.fixture
def stocked_inventory() -> InventoryService:
    """Three cards, one of them down to a single copy."""
    service = InventoryService(InMemoryDatabase())
    service.add_item(InventoryItem(card_name="Dark Magician", set_code="LOB-005",
                                   quantity=3, cost_gbp=4.00, location="Binder A"))
    service.add_item(InventoryItem(card_name="Mirror Force", set_code="MRD-138",
                                   quantity=1, cost_gbp=6.00, location="Box 2"))
    service.add_item(InventoryItem(card_name="Blue-Eyes White Dragon", set_code="LOB-001",
                                   quantity=2, cost_gbp=20.00, location="Binder A"))
    return service
