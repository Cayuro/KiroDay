"""Unit tests for Sales_Service / Inventory_Service (task 6.10).

Covers the registration-timestamp window (Requirement 2.4) and the injected
non-stock transaction failure path that returns TRANSACTION_FAILED with stock
preserved (Requirement 3.5). Complements the property tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.errors import ErrorCode
from app.repository.memory import InMemoryPosRepository
from app.services.catalog import CatalogService
from app.services.inventory import (
    InsufficientStock,
    InventoryService,
    SaleAlreadyExists,
    TransactionFailed,
)
from app.services.sales import SalesService


def _repo_with_stock() -> InMemoryPosRepository:
    repo = InMemoryPosRepository()
    catalog = CatalogService(repo)
    catalog.create_product(sku="A", name="Café", price="2.50", stock=10)
    catalog.create_product(sku="B", name="Pan", price="1.00", stock=5)
    return repo


def _stock(repo: InMemoryPosRepository, sku: str) -> int:
    product = repo.get_product(sku)
    assert product is not None
    return int(product["stock"])


# Requirement 2.4
def test_timestamp_recorded_within_window_around_now():
    repo = _repo_with_stock()
    service = SalesService(repo)

    before = datetime.now(timezone.utc)
    sale = service.register_sale([{"sku": "A", "qty": 1}], "efectivo")
    after = datetime.now(timezone.utc)

    assert sale.timestamp.tzinfo is not None  # timezone-aware (UTC)
    assert before <= sale.timestamp <= after


# Requirement 3.5
def test_injected_non_stock_failure_returns_transaction_failed_stock_preserved():
    repo = _repo_with_stock()
    service = SalesService(repo)
    repo.fail_next_transaction = True  # force a non-condition cancellation

    with pytest.raises(TransactionFailed) as exc:
        service.register_sale([{"sku": "A", "qty": 2}, {"sku": "B", "qty": 1}], "tarjeta")

    assert exc.value.code == ErrorCode.TRANSACTION_FAILED
    # Nothing committed: stock preserved and no sale persisted.
    assert _stock(repo, "A") == 10
    assert _stock(repo, "B") == 5
    assert repo.query_sales_by_date(datetime.now(timezone.utc).date().isoformat()) == []


def test_insufficient_stock_lists_only_offending_sku():
    repo = _repo_with_stock()
    service = SalesService(repo)

    with pytest.raises(InsufficientStock) as exc:
        service.register_sale(
            [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 99}], "efectivo"
        )

    assert exc.value.skus == ["B"]
    assert _stock(repo, "A") == 10
    assert _stock(repo, "B") == 5


def test_repeated_sku_lines_sum_quantities_for_stock_decrement():
    repo = _repo_with_stock()
    service = SalesService(repo)
    service.register_sale([{"sku": "A", "qty": 3}, {"sku": "A", "qty": 2}], "efectivo")
    assert _stock(repo, "A") == 5  # 10 - (3 + 2)


def test_empty_items_rejected():
    repo = _repo_with_stock()
    service = SalesService(repo)
    with pytest.raises(Exception) as exc:
        service.register_sale([], "efectivo")
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_duplicate_sale_id_maps_to_internal_error_not_transaction_failed():
    # A duplicate sale id (the sale Put's attribute_not_exists(SK) guard fires)
    # is not a transient failure to retry: with server-generated UUIDs it means
    # an internal problem. It maps to INTERNAL_ERROR (500), not 503. Committing
    # the same Sale twice reproduces the collision; nothing partial is written.
    from app.models.product import Product
    from app.models.sale import Sale

    repo = _repo_with_stock()
    inventory = InventoryService(repo)
    product = Product.create(sku="A", name="Café", price="2.50", stock=10)
    sale = Sale.create(
        [{"sku": "A", "qty": 2}],
        "efectivo",
        {"A": Decimal("2.50")},
        sale_id="fixed-id",
    )

    inventory.commit_sale(sale, {"A": product})
    assert _stock(repo, "A") == 8

    with pytest.raises(SaleAlreadyExists) as exc:
        inventory.commit_sale(sale, {"A": product})

    assert exc.value.code == ErrorCode.INTERNAL_ERROR
    # The second decrement was not applied: nothing partial written.
    assert _stock(repo, "A") == 8
    assert len(repo.query_sales_by_date(sale.timestamp.date().isoformat())) == 1
