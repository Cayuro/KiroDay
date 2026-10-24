"""Property-based tests for the Product model (Properties 1 and 2)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.errors import ValidationError
from app.models.product import (
    NAME_MAX_LEN,
    NAME_MIN_LEN,
    SKU_MAX_LEN,
    SKU_MIN_LEN,
    STOCK_MAX,
    STOCK_MIN,
    Product,
)
from app.money import MAX_PRICE, MIN_PRICE


# --- Strategies ------------------------------------------------------------

valid_names = st.text(min_size=NAME_MIN_LEN, max_size=NAME_MAX_LEN)
valid_skus = st.text(min_size=SKU_MIN_LEN, max_size=SKU_MAX_LEN)
valid_stocks = st.integers(min_value=STOCK_MIN, max_value=STOCK_MAX)

# Prices in [0.01, 999999999.99] generated as 2-decimal strings to stay exact.
valid_prices = st.integers(
    min_value=1, max_value=99_999_999_999
).map(lambda cents: str(Decimal(cents) / Decimal(100)))


@st.composite
def valid_products(draw):
    return {
        "sku": draw(valid_skus),
        "name": draw(valid_names),
        "price": draw(valid_prices),
        "stock": draw(valid_stocks),
    }


# --- Property 1 ------------------------------------------------------------

# Feature: pos-mvp, Property 1: Create round-trip preserves fields
@given(data=valid_products())
def test_create_round_trip_preserves_fields(data):
    product = Product.create(**data)

    assert product.sku == data["sku"]
    assert product.name == data["name"]
    assert product.stock == data["stock"]
    # price round-trips as an exact 2-decimal Decimal equal to the input value.
    assert product.price == Decimal(data["price"])


# --- Property 2 (validation half) -----------------------------------------

# Feature: pos-mvp, Property 2: Invalid create is rejected and persists nothing
@given(
    sku=valid_skus,
    name=valid_names,
    stock=valid_stocks,
    cents=st.one_of(
        st.integers(max_value=0),  # price <= 0.00
        st.integers(min_value=100_000_000_000),  # price > MAX_PRICE
    ),
)
def test_invalid_price_is_rejected_naming_field(sku, name, stock, cents):
    price = str(Decimal(cents) / Decimal(100))
    with pytest.raises(ValidationError) as exc:
        Product.create(sku=sku, name=name, price=price, stock=stock)
    assert exc.value.field == "price"


# Feature: pos-mvp, Property 2: Invalid create is rejected and persists nothing
@given(
    sku=valid_skus,
    name=valid_names,
    price=valid_prices,
    stock=st.one_of(
        st.integers(max_value=STOCK_MIN - 1),
        st.integers(min_value=STOCK_MAX + 1),
    ),
)
def test_invalid_stock_is_rejected_naming_field(sku, name, price, stock):
    with pytest.raises(ValidationError) as exc:
        Product.create(sku=sku, name=name, price=price, stock=stock)
    assert exc.value.field == "stock"


# Feature: pos-mvp, Property 2: Invalid create is rejected and persists nothing
@given(
    name=st.one_of(
        st.just(""),
        st.text(min_size=NAME_MAX_LEN + 1, max_size=NAME_MAX_LEN + 50),
    ),
    sku=valid_skus,
    price=valid_prices,
    stock=valid_stocks,
)
def test_invalid_name_is_rejected_naming_field(name, sku, price, stock):
    with pytest.raises(ValidationError) as exc:
        Product.create(sku=sku, name=name, price=price, stock=stock)
    assert exc.value.field == "name"


# Feature: pos-mvp, Property 2: Invalid create is rejected and persists nothing
@given(
    sku=st.one_of(
        st.just(""),
        st.text(min_size=SKU_MAX_LEN + 1, max_size=SKU_MAX_LEN + 50),
    ),
    name=valid_names,
    price=valid_prices,
    stock=valid_stocks,
)
def test_invalid_sku_is_rejected_naming_field(sku, name, price, stock):
    with pytest.raises(ValidationError) as exc:
        Product.create(sku=sku, name=name, price=price, stock=stock)
    assert exc.value.field == "sku"
