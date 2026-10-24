"""Unit tests for the in-memory transactional fake (task 4.3).

These pin down the semantics the business logic (and the property tests in a
later wave) rely on: ``TransactWriteItems`` is all-or-nothing, cancellation
reasons list the offending SKUs, and an injected non-condition failure rejects
the batch while writing nothing.

Requirements: 3.2, 3.4, 3.5.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.repository.base import (
    DuplicateItem,
    ItemNotFound,
    MAX_TRANSACTION_ACTIONS,
    PutAction,
    StockDecrementAction,
    TransactionCancelled,
    TransactionValidationError,
)
from app.repository.keys import (
    ENTITY,
    ENTITY_PRODUCT,
    ENTITY_SALE,
    PK,
    SK,
    product_key,
    product_pk,
    sale_pk,
    sale_sk,
)
from app.repository.memory import InMemoryPosRepository


# --- helpers ---------------------------------------------------------------


def _product_item(sku: str, stock: int, price: str = "2.50", name: str = "x") -> dict:
    pk = product_pk(sku)
    return {
        PK: pk,
        SK: pk,
        ENTITY: ENTITY_PRODUCT,
        "name": name,
        "price": Decimal(price),
        "stock": Decimal(stock),
    }


def _sale_put(date: str, ts: str, sale_id: str) -> PutAction:
    return PutAction(
        item={
            PK: sale_pk(date),
            SK: sale_sk(ts, sale_id),
            ENTITY: ENTITY_SALE,
            "total": Decimal("5.00"),
            "payment_method": "efectivo",
            "timestamp": ts,
            "items": [{"sku": "A", "qty": 2}],
        },
        condition_attribute_not_exists="SK",
    )


def _stock(repo: InMemoryPosRepository, sku: str) -> int:
    product = repo.get_product(sku)
    assert product is not None
    return int(product["stock"])


# --- basic product operations ---------------------------------------------


def test_put_and_get_product_round_trip():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))
    product = repo.get_product("A")
    assert product is not None
    assert product["stock"] == Decimal("10")


def test_put_duplicate_product_rejected():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))
    with pytest.raises(DuplicateItem):
        repo.put_product(_product_item("A", stock=99))
    # The existing item is left unchanged.
    assert _stock(repo, "A") == 10


def test_update_missing_product_rejected():
    repo = InMemoryPosRepository()
    with pytest.raises(ItemNotFound):
        repo.update_product(_product_item("A", stock=5))
    assert repo.get_product("A") is None


def test_get_returns_deep_copy_not_alias():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))
    product = repo.get_product("A")
    product["stock"] = Decimal("0")  # mutate the returned copy
    assert _stock(repo, "A") == 10  # store is unaffected


# --- transaction: happy path ------------------------------------------------


def test_commit_applies_all_writes_atomically():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))
    repo.put_product(_product_item("B", stock=5))

    repo.commit_sale_transaction(
        [
            StockDecrementAction(key=product_key("A"), sku="A", qty=3),
            StockDecrementAction(key=product_key("B"), sku="B", qty=2),
            _sale_put("2025-06-01", "2025-06-01T14:22:05+00:00", "sale-1"),
        ]
    )

    assert _stock(repo, "A") == 7
    assert _stock(repo, "B") == 3
    sales = repo.query_sales_by_date("2025-06-01")
    assert len(sales) == 1


def test_commit_at_exact_stock_boundary_succeeds():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=3))
    repo.commit_sale_transaction(
        [StockDecrementAction(key=product_key("A"), sku="A", qty=3)]
    )
    assert _stock(repo, "A") == 0


# --- transaction: all-or-nothing on condition failure -----------------------


def test_insufficient_stock_leaves_all_items_unchanged():
    # A fails (qty 6 > stock 5); B would succeed on its own. All-or-nothing: no
    # write happens at all, and no sale is persisted.
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=5))
    repo.put_product(_product_item("B", stock=10))

    with pytest.raises(TransactionCancelled) as exc:
        repo.commit_sale_transaction(
            [
                StockDecrementAction(key=product_key("A"), sku="A", qty=6),
                StockDecrementAction(key=product_key("B"), sku="B", qty=2),
                _sale_put("2025-06-01", "2025-06-01T14:22:05+00:00", "sale-1"),
            ]
        )

    # Only A is offending; B had enough stock.
    assert exc.value.conditional_failure_skus() == ["A"]
    assert not exc.value.has_non_condition_failure()
    # Stocks preserved exactly; nothing written.
    assert _stock(repo, "A") == 5
    assert _stock(repo, "B") == 10
    assert repo.query_sales_by_date("2025-06-01") == []


def test_multiple_offending_skus_all_reported():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=1))
    repo.put_product(_product_item("B", stock=1))
    repo.put_product(_product_item("C", stock=50))

    with pytest.raises(TransactionCancelled) as exc:
        repo.commit_sale_transaction(
            [
                StockDecrementAction(key=product_key("A"), sku="A", qty=5),
                StockDecrementAction(key=product_key("B"), sku="B", qty=9),
                StockDecrementAction(key=product_key("C"), sku="C", qty=1),
            ]
        )

    assert exc.value.conditional_failure_skus() == ["A", "B"]
    assert _stock(repo, "A") == 1
    assert _stock(repo, "B") == 1
    assert _stock(repo, "C") == 50


def test_missing_product_in_transaction_is_conditional_failure():
    # attribute_exists(PK) fails for an unknown product -> ConditionalCheckFailed.
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))

    with pytest.raises(TransactionCancelled) as exc:
        repo.commit_sale_transaction(
            [
                StockDecrementAction(key=product_key("A"), sku="A", qty=1),
                StockDecrementAction(key=product_key("MISSING"), sku="MISSING", qty=1),
            ]
        )

    assert exc.value.conditional_failure_skus() == ["MISSING"]
    assert _stock(repo, "A") == 10


def test_duplicate_sale_put_is_rejected_and_nothing_changes():
    # The sale Put is guarded by attribute_not_exists(SK): a replay is rejected
    # and the stock decrements in the same batch are not applied.
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))
    date, ts, sale_id = "2025-06-01", "2025-06-01T14:22:05+00:00", "sale-1"

    repo.commit_sale_transaction(
        [
            StockDecrementAction(key=product_key("A"), sku="A", qty=2),
            _sale_put(date, ts, sale_id),
        ]
    )
    assert _stock(repo, "A") == 8

    with pytest.raises(TransactionCancelled) as exc:
        repo.commit_sale_transaction(
            [
                StockDecrementAction(key=product_key("A"), sku="A", qty=2),
                _sale_put(date, ts, sale_id),  # same keys -> duplicate
            ]
        )

    assert exc.value.conditional_failure_skus() == []  # the Put failed, no SKU
    assert not exc.value.has_non_condition_failure()
    assert _stock(repo, "A") == 8  # second decrement not applied
    assert len(repo.query_sales_by_date(date)) == 1


# --- transaction: injected non-condition failure (Requirement 3.5) ----------


def test_injected_non_condition_failure_rejects_batch_and_writes_nothing():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))
    repo.fail_next_transaction = True

    with pytest.raises(TransactionCancelled) as exc:
        repo.commit_sale_transaction(
            [
                StockDecrementAction(key=product_key("A"), sku="A", qty=2),
                _sale_put("2025-06-01", "2025-06-01T14:22:05+00:00", "sale-1"),
            ]
        )

    # Non-condition failure, not an insufficient-stock condition.
    assert exc.value.has_non_condition_failure()
    assert exc.value.conditional_failure_skus() == []
    # Nothing written; stock preserved.
    assert _stock(repo, "A") == 10
    assert repo.query_sales_by_date("2025-06-01") == []


def test_injected_failure_is_consumed_once():
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))
    repo.fail_next_transaction = True

    with pytest.raises(TransactionCancelled):
        repo.commit_sale_transaction(
            [StockDecrementAction(key=product_key("A"), sku="A", qty=2)]
        )

    # The next transaction succeeds — the flag applies to a single commit.
    repo.commit_sale_transaction(
        [StockDecrementAction(key=product_key("A"), sku="A", qty=2)]
    )
    assert _stock(repo, "A") == 8


# --- transaction: action-count limit (DynamoDB ValidationException) ---------


def test_oversized_transaction_rejected_and_writes_nothing():
    # DynamoDB rejects a TransactWriteItems with > 100 actions as a client-side
    # ValidationException (the transaction never runs). The fake mirrors that
    # with TransactionValidationError and writes nothing.
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=10))

    actions = [
        StockDecrementAction(key=product_key("A"), sku="A", qty=1)
        for _ in range(MAX_TRANSACTION_ACTIONS + 1)
    ]
    with pytest.raises(TransactionValidationError):
        repo.commit_sale_transaction(actions)

    assert _stock(repo, "A") == 10  # untouched


def test_transaction_at_action_limit_is_allowed():
    # Exactly MAX_TRANSACTION_ACTIONS is within the limit. Use one decrement
    # plus (limit - 1) independent sale Puts so all conditions pass.
    repo = InMemoryPosRepository()
    repo.put_product(_product_item("A", stock=MAX_TRANSACTION_ACTIONS))

    actions = [StockDecrementAction(key=product_key("A"), sku="A", qty=1)]
    for i in range(MAX_TRANSACTION_ACTIONS - 1):
        ts = f"2025-06-01T14:22:{i:02d}+00:00"
        actions.append(_sale_put("2025-06-01", ts, f"sale-{i}"))

    assert len(actions) == MAX_TRANSACTION_ACTIONS
    repo.commit_sale_transaction(actions)
    assert _stock(repo, "A") == MAX_TRANSACTION_ACTIONS - 1
