"""Property-based tests for Catalog_Service (Properties 2, 3, 4; tasks 5.2-5.4).

These exercise catalog *state* against the in-memory transactional fake: after a
rejected create/update the catalog is left exactly as before, listing returns
exactly the created set, and a valid update preserves untouched fields.

Properties 2/3/4 from design.md; Requirements 1.2-1.9.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.errors import ValidationError
from app.models.product import (
    NAME_MAX_LEN,
    NAME_MIN_LEN,
    SKU_MAX_LEN,
    SKU_MIN_LEN,
    STOCK_MAX,
    STOCK_MIN,
)
from app.repository.memory import InMemoryPosRepository
from app.services.catalog import CatalogService, DuplicateSku, ProductNotFound


# --- strategies ------------------------------------------------------------

valid_names = st.text(min_size=NAME_MIN_LEN, max_size=NAME_MAX_LEN)
valid_skus = st.text(min_size=SKU_MIN_LEN, max_size=SKU_MAX_LEN)
valid_stocks = st.integers(min_value=STOCK_MIN, max_value=STOCK_MAX)
valid_prices = st.integers(min_value=1, max_value=99_999_999_999).map(
    lambda cents: str(Decimal(cents) / Decimal(100))
)


@st.composite
def valid_product_kwargs(draw, sku=None):
    return {
        "sku": sku if sku is not None else draw(valid_skus),
        "name": draw(valid_names),
        "price": draw(valid_prices),
        "stock": draw(valid_stocks),
    }


def _catalog_snapshot(service: CatalogService) -> dict:
    """Map SKU -> (name, price, stock) for the current catalog."""

    return {
        p.sku: (p.name, p.price, p.stock) for p in service.list_products()
    }


# --- Property 2 (catalog-state half) ---------------------------------------

# Feature: pos-mvp, Property 2: Invalid create is rejected and persists nothing
@given(
    first=valid_product_kwargs(),
    dup_name=valid_names,
    dup_price=valid_prices,
    dup_stock=valid_stocks,
)
def test_duplicate_sku_create_leaves_catalog_unchanged(
    first, dup_name, dup_price, dup_stock
):
    repo = InMemoryPosRepository()
    service = CatalogService(repo)
    service.create_product(**first)
    before = _catalog_snapshot(service)

    with pytest.raises(DuplicateSku) as exc:
        service.create_product(
            sku=first["sku"], name=dup_name, price=dup_price, stock=dup_stock
        )

    assert exc.value.sku == first["sku"]
    # The catalog (and specifically the existing product) is untouched.
    assert _catalog_snapshot(service) == before


# Feature: pos-mvp, Property 2: Invalid create is rejected and persists nothing
@given(
    existing=valid_product_kwargs(),
    new_sku=valid_skus,
    name=valid_names,
    stock=valid_stocks,
    bad_cents=st.one_of(
        st.integers(max_value=0),
        st.integers(min_value=100_000_000_000),
    ),
)
def test_invalid_create_leaves_catalog_unchanged(
    existing, new_sku, name, stock, bad_cents
):
    assume(new_sku != existing["sku"])
    repo = InMemoryPosRepository()
    service = CatalogService(repo)
    service.create_product(**existing)
    before = _catalog_snapshot(service)

    bad_price = str(Decimal(bad_cents) / Decimal(100))
    with pytest.raises(ValidationError):
        service.create_product(sku=new_sku, name=name, price=bad_price, stock=stock)

    # No new product added, existing one untouched.
    assert _catalog_snapshot(service) == before


# --- Property 3 ------------------------------------------------------------


@st.composite
def distinct_sku_products(draw):
    """Generate 0..8 products with pairwise-distinct SKUs."""

    count = draw(st.integers(min_value=0, max_value=8))
    skus: set[str] = set()
    products: list[dict] = []
    for _ in range(count):
        sku = draw(valid_skus)
        if sku in skus:
            continue
        skus.add(sku)
        products.append(draw(valid_product_kwargs(sku=sku)))
    return products


# Feature: pos-mvp, Property 3: List returns exactly the created products
@given(products=distinct_sku_products())
def test_list_returns_exactly_created_products(products):
    repo = InMemoryPosRepository()
    service = CatalogService(repo)
    for kwargs in products:
        service.create_product(**kwargs)

    listed = _catalog_snapshot(service)

    expected = {
        kwargs["sku"]: (kwargs["name"], Decimal(kwargs["price"]), kwargs["stock"])
        for kwargs in products
    }
    assert listed == expected


# --- Property 4 ------------------------------------------------------------

# Feature: pos-mvp, Property 4: Update preserves untouched fields; invalid or
# missing update is rejected and preserves state
@given(
    original=valid_product_kwargs(),
    new_name=valid_names,
    new_price=valid_prices,
    new_stock=valid_stocks,
    subset=st.lists(
        st.sampled_from(["name", "price", "stock"]),
        min_size=1,
        max_size=3,
        unique=True,
    ),
)
def test_valid_update_preserves_untouched_fields(
    original, new_name, new_price, new_stock, subset
):
    repo = InMemoryPosRepository()
    service = CatalogService(repo)
    service.create_product(**original)

    candidate = {"name": new_name, "price": new_price, "stock": new_stock}
    changes = {field: candidate[field] for field in subset}

    updated = service.update_product(original["sku"], changes)

    # Updated fields reflect the change; untouched fields keep the original.
    expected_name = new_name if "name" in subset else original["name"]
    expected_price = Decimal(new_price) if "price" in subset else Decimal(original["price"])
    expected_stock = new_stock if "stock" in subset else original["stock"]

    assert updated.name == expected_name
    assert updated.price == expected_price
    assert updated.stock == expected_stock
    # Persisted state matches the returned product.
    stored = {p.sku: p for p in service.list_products()}[original["sku"]]
    assert (stored.name, stored.price, stored.stock) == (
        expected_name,
        expected_price,
        expected_stock,
    )


# Feature: pos-mvp, Property 4: Update preserves untouched fields; invalid or
# missing update is rejected and preserves state
@given(
    original=valid_product_kwargs(),
    bad_stock=st.one_of(
        st.integers(max_value=STOCK_MIN - 1),
        st.integers(min_value=STOCK_MAX + 1),
    ),
)
def test_invalid_update_preserves_state(original, bad_stock):
    repo = InMemoryPosRepository()
    service = CatalogService(repo)
    service.create_product(**original)
    before = _catalog_snapshot(service)

    with pytest.raises(ValidationError):
        service.update_product(original["sku"], {"stock": bad_stock})

    assert _catalog_snapshot(service) == before


# Feature: pos-mvp, Property 4: Update preserves untouched fields; invalid or
# missing update is rejected and preserves state
@given(
    catalog=distinct_sku_products(),
    missing_sku=valid_skus,
    new_name=valid_names,
)
def test_missing_update_rejected_and_creates_nothing(catalog, missing_sku, new_name):
    existing_skus = {kwargs["sku"] for kwargs in catalog}
    assume(missing_sku not in existing_skus)

    repo = InMemoryPosRepository()
    service = CatalogService(repo)
    for kwargs in catalog:
        service.create_product(**kwargs)
    before = _catalog_snapshot(service)

    with pytest.raises(ProductNotFound) as exc:
        service.update_product(missing_sku, {"name": new_name})

    assert exc.value.sku == missing_sku
    # No product created; catalog unchanged.
    assert _catalog_snapshot(service) == before
