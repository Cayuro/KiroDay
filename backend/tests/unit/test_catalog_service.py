"""Unit tests for Catalog_Service edge cases (task 5.5).

Covers the empty-catalog list (Requirement 1.6) and a few example-based
create/update behaviors that complement the property tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.repository.memory import InMemoryPosRepository
from app.services.catalog import CatalogService, DuplicateSku, ProductNotFound


def _service() -> CatalogService:
    return CatalogService(InMemoryPosRepository())


# Requirement 1.6
def test_empty_catalog_list_returns_empty_list():
    service = _service()
    assert service.list_products() == []


def test_create_round_trips_stored_representation():
    service = _service()
    product = service.create_product(sku="CAFE-01", name="Café", price="2.50", stock=100)
    assert product.sku == "CAFE-01"
    assert product.price == Decimal("2.50")
    assert product.stock == 100
    listed = service.list_products()
    assert len(listed) == 1
    assert listed[0].sku == "CAFE-01"


def test_duplicate_sku_rejected_existing_unchanged():
    service = _service()
    service.create_product(sku="A", name="first", price="2.00", stock=10)
    with pytest.raises(DuplicateSku):
        service.create_product(sku="A", name="second", price="9.99", stock=0)
    stored = service.list_products()[0]
    assert (stored.name, stored.price, stored.stock) == ("first", Decimal("2.00"), 10)


def test_update_unknown_field_rejected():
    service = _service()
    service.create_product(sku="A", name="n", price="2.00", stock=10)
    with pytest.raises(ValidationError) as exc:
        service.update_product("A", {"sku": "B"})
    assert exc.value.field == "sku"


def test_update_missing_sku_rejected():
    service = _service()
    with pytest.raises(ProductNotFound):
        service.update_product("NOPE", {"stock": 1})


def test_partial_update_preserves_other_fields():
    service = _service()
    service.create_product(sku="A", name="Café", price="2.50", stock=10)
    updated = service.update_product("A", {"stock": 3})
    assert updated.name == "Café"
    assert updated.price == Decimal("2.50")
    assert updated.stock == 3
