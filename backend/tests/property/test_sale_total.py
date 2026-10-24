"""Property-based test for sale total calculation (Property 5)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from app.models.sale import DISTINCT_SKU_MAX, QTY_MAX, QTY_MIN, Sale
from app.money import MAX_PRICE, MIN_PRICE, quantize_money


# Unit prices as exact 2-decimal Decimals in a modest range so that totals can
# realistically stay within [0.01, 999999999.99] across up to 99 distinct SKUs.
unit_prices = st.integers(min_value=1, max_value=100_000).map(
    lambda cents: Decimal(cents) / Decimal(100)
)
qtys = st.integers(min_value=QTY_MIN, max_value=QTY_MAX)


@st.composite
def sale_inputs(draw):
    """Generate (raw_items, prices) for a sale with 1..DISTINCT_SKU_MAX SKUs."""

    count = draw(st.integers(min_value=1, max_value=DISTINCT_SKU_MAX))
    prices: dict[str, Decimal] = {}
    raw_items: list[dict] = []
    for i in range(count):
        sku = f"SKU-{i}"
        prices[sku] = draw(unit_prices)
        raw_items.append({"sku": sku, "qty": draw(qtys)})
    return raw_items, prices


# Feature: pos-mvp, Property 5: Sale total equals the sum of rounded subtotals
@given(data=sale_inputs())
def test_total_equals_sum_of_rounded_subtotals(data):
    raw_items, prices = data

    expected_total = sum(
        (
            Sale.compute_subtotal(prices[item["sku"]], item["qty"])
            for item in raw_items
        ),
        Decimal("0"),
    )
    expected_total = quantize_money(expected_total)

    # Keep the generated sale within the valid total range so create() succeeds;
    # the property under test is the arithmetic equality, not the range guard.
    assume(MIN_PRICE <= expected_total <= MAX_PRICE)

    sale = Sale.create(raw_items, "efectivo", prices)

    assert sale.total == expected_total
    # And the total equals the sum of the model's own stored subtotals.
    assert sale.total == quantize_money(sum((i.subtotal for i in sale.items), Decimal("0")))
    assert MIN_PRICE <= sale.total <= MAX_PRICE
