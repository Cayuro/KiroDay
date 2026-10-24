"""Example-based unit tests for model validation edge cases (task 2.6).

Covers boundary values for price/stock/name/sku length and quantity bounds, the
empty-items rejection, and the "no binary float for money" rule.
Requirements: 1.3, 1.4, 2.6, 2.7, 2.8.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.models.product import Product
from app.models.sale import Sale


# --- Product boundaries ----------------------------------------------------


def test_price_lower_boundary_accepted():
    product = Product.create(sku="A", name="n", price="0.01", stock=0)
    assert product.price == Decimal("0.01")


def test_price_upper_boundary_accepted():
    product = Product.create(sku="A", name="n", price="999999999.99", stock=0)
    assert product.price == Decimal("999999999.99")


def test_price_just_below_minimum_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="n", price="0.00", stock=0)
    assert exc.value.field == "price"


def test_price_just_above_maximum_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="n", price="1000000000.00", stock=0)
    assert exc.value.field == "price"


def test_price_rejects_binary_float():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="n", price=2.5, stock=0)  # type: ignore[arg-type]
    assert exc.value.field == "price"


def test_stock_boundaries_accepted():
    assert Product.create(sku="A", name="n", price="1.00", stock=0).stock == 0
    assert Product.create(sku="A", name="n", price="1.00", stock=999999).stock == 999999


def test_stock_above_maximum_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="n", price="1.00", stock=1_000_000)
    assert exc.value.field == "stock"


def test_stock_negative_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="n", price="1.00", stock=-1)
    assert exc.value.field == "stock"


def test_stock_bool_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="n", price="1.00", stock=True)  # type: ignore[arg-type]
    assert exc.value.field == "stock"


def test_name_length_boundaries():
    assert Product.create(sku="A", name="x", price="1.00", stock=0).name == "x"
    long_name = "x" * 100
    assert Product.create(sku="A", name=long_name, price="1.00", stock=0).name == long_name


def test_name_empty_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="", price="1.00", stock=0)
    assert exc.value.field == "name"


def test_name_too_long_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="A", name="x" * 101, price="1.00", stock=0)
    assert exc.value.field == "name"


def test_sku_length_boundaries():
    assert Product.create(sku="x", name="n", price="1.00", stock=0).sku == "x"
    long_sku = "x" * 50
    assert Product.create(sku=long_sku, name="n", price="1.00", stock=0).sku == long_sku


def test_sku_empty_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="", name="n", price="1.00", stock=0)
    assert exc.value.field == "sku"


def test_sku_too_long_rejected():
    with pytest.raises(ValidationError) as exc:
        Product.create(sku="x" * 51, name="n", price="1.00", stock=0)
    assert exc.value.field == "sku"


# --- Sale boundaries -------------------------------------------------------


def _prices(*skus: str) -> dict[str, Decimal]:
    return {sku: Decimal("1.00") for sku in skus}


def test_empty_items_rejected():
    with pytest.raises(ValidationError) as exc:
        Sale.create([], "efectivo", {})
    assert exc.value.field == "items"


def test_items_upper_boundary_accepted():
    # 99 distinct lines is the maximum (one decrement each + one sale Put keeps
    # the transaction within DynamoDB's 100-action limit).
    raw = [{"sku": f"S{i}", "qty": 1} for i in range(99)]
    prices = _prices(*(f"S{i}" for i in range(99)))
    sale = Sale.create(raw, "efectivo", prices)
    assert len(sale.items) == 99


def test_items_line_cap_upper_boundary_accepted():
    # ITEMS_MAX lines across <= DISTINCT_SKU_MAX distinct SKUs is accepted:
    # repeated SKUs are summed into one decrement, so distinct SKUs stay <= 99.
    from app.models.sale import DISTINCT_SKU_MAX, ITEMS_MAX

    # 99 distinct SKUs, each repeated so total lines == ITEMS_MAX.
    raw = []
    for i in range(ITEMS_MAX):
        raw.append({"sku": f"S{i % DISTINCT_SKU_MAX}", "qty": 1})
    prices = _prices(*(f"S{i}" for i in range(DISTINCT_SKU_MAX)))
    sale = Sale.create(raw, "efectivo", prices)
    # Distinct SKUs preserved; lines kept individually.
    assert len({item.sku for item in sale.items}) <= DISTINCT_SKU_MAX


def test_too_many_items_rejected():
    # More than ITEMS_MAX request lines is rejected early, naming "items".
    from app.models.sale import ITEMS_MAX

    raw = [{"sku": f"S{i}", "qty": 1} for i in range(ITEMS_MAX + 1)]
    prices = _prices(*(f"S{i}" for i in range(ITEMS_MAX + 1)))
    with pytest.raises(ValidationError) as exc:
        Sale.create(raw, "efectivo", prices)
    assert exc.value.field == "items"


def test_too_many_distinct_skus_rejected():
    # The authoritative business guard: more than DISTINCT_SKU_MAX distinct SKUs
    # would need one decrement each + the sale Put, exceeding DynamoDB's
    # 100-action TransactWriteItems limit. Rejected before building the
    # transaction, naming "items". Uses exactly DISTINCT_SKU_MAX + 1 distinct
    # SKUs on that many lines (within ITEMS_MAX), so this guard — not the line
    # cap — is what fires.
    from app.models.sale import DISTINCT_SKU_MAX

    n = DISTINCT_SKU_MAX + 1
    raw = [{"sku": f"S{i}", "qty": 1} for i in range(n)]
    prices = _prices(*(f"S{i}" for i in range(n)))
    with pytest.raises(ValidationError) as exc:
        Sale.create(raw, "efectivo", prices)
    assert exc.value.field == "items"
    assert exc.value.details.get("distinct_skus") == n


def test_qty_lower_boundary_accepted():
    sale = Sale.create([{"sku": "A", "qty": 1}], "efectivo", _prices("A"))
    assert sale.items[0].qty == 1


def test_qty_upper_boundary_accepted():
    sale = Sale.create([{"sku": "A", "qty": 9999}], "efectivo", _prices("A"))
    assert sale.items[0].qty == 9999


def test_qty_zero_rejected():
    with pytest.raises(ValidationError) as exc:
        Sale.create([{"sku": "A", "qty": 0}], "efectivo", _prices("A"))
    assert exc.value.field == "qty"


def test_qty_above_maximum_rejected():
    with pytest.raises(ValidationError) as exc:
        Sale.create([{"sku": "A", "qty": 10000}], "efectivo", _prices("A"))
    assert exc.value.field == "qty"


def test_qty_bool_rejected():
    with pytest.raises(ValidationError) as exc:
        Sale.create([{"sku": "A", "qty": True}], "efectivo", _prices("A"))
    assert exc.value.field == "qty"


def test_unknown_sku_rejected_naming_sku():
    with pytest.raises(ValidationError) as exc:
        Sale.create([{"sku": "MISSING", "qty": 1}], "efectivo", _prices("A"))
    assert exc.value.field == "sku"
    assert exc.value.details.get("sku") == "MISSING"


def test_invalid_payment_method_rejected():
    with pytest.raises(ValidationError) as exc:
        Sale.create([{"sku": "A", "qty": 1}], "cheque", _prices("A"))
    assert exc.value.field == "payment_method"


def test_valid_payment_methods_accepted():
    for method in ("efectivo", "tarjeta"):
        sale = Sale.create([{"sku": "A", "qty": 1}], method, _prices("A"))
        assert sale.payment_method == method


def test_subtotal_and_total_use_decimal_rounding():
    # 0.10 * 3 = 0.30 exactly; verifies no binary-float drift.
    sale = Sale.create([{"sku": "A", "qty": 3}], "efectivo", {"A": Decimal("0.10")})
    assert sale.items[0].subtotal == Decimal("0.30")
    assert sale.total == Decimal("0.30")


def test_explicit_timestamp_and_sale_id_preserved():
    ts = datetime(2025, 6, 1, 14, 22, 5, tzinfo=timezone.utc)
    sale = Sale.create(
        [{"sku": "A", "qty": 1}],
        "efectivo",
        _prices("A"),
        timestamp=ts,
        sale_id="fixed-id",
    )
    assert sale.timestamp == ts
    assert sale.sale_id == "fixed-id"
