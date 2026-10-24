"""Property-based tests for Sales_Service + Inventory_Service.

The atomic stock discount is the core of the business logic, so these are the
most important tests in the suite. They run against the in-memory transactional
fake, which reproduces DynamoDB ``TransactWriteItems`` all-or-nothing semantics.

Properties 6-11 from design.md:
* 6  — registered sale round-trips its fields with a unique id (tasks 6.4)
* 7  — invalid sale is rejected and persists nothing (task 6.5)
* 8  — sufficient stock decrements each product by its quantity (task 6.6)
* 9  — sale registration is all-or-nothing (task 6.7)
* 10 — insufficient stock rejects the whole sale and reports SKUs (task 6.8)
* 11 — concurrent sales never oversell a product (task 6.9)

Requirements 2.1, 2.3, 2.5, 2.7, 2.8, 3.1-3.7.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.errors import ValidationError
from app.models.sale import QTY_MAX, QTY_MIN
from app.repository.memory import InMemoryPosRepository
from app.services.catalog import CatalogService
from app.services.inventory import InsufficientStock, TransactionFailed
from app.services.sales import SalesService, UnknownSku


# --- strategies ------------------------------------------------------------

skus = st.text(
    alphabet=st.characters(min_codepoint=48, max_codepoint=90), min_size=1, max_size=8
)
unit_prices = st.integers(min_value=1, max_value=10_000).map(
    lambda cents: str(Decimal(cents) / Decimal(100))
)
payment_methods = st.sampled_from(["efectivo", "tarjeta"])


@st.composite
def catalog_and_sale(draw, *, ensure_sufficient_stock=True):
    """Build a catalog and a sale over 1..5 distinct SKUs.

    When ``ensure_sufficient_stock`` is True, every product gets enough stock to
    cover the sale (so a valid sale always commits). Quantities and prices are
    kept small so the total stays within the valid monetary range.
    """

    count = draw(st.integers(min_value=1, max_value=5))
    sku_set: list[str] = []
    seen: set[str] = set()
    while len(sku_set) < count:
        sku = draw(skus)
        if sku not in seen:
            seen.add(sku)
            sku_set.append(sku)

    catalog: list[dict] = []
    raw_items: list[dict] = []
    for sku in sku_set:
        qty = draw(st.integers(min_value=QTY_MIN, max_value=200))
        price = draw(unit_prices)
        if ensure_sufficient_stock:
            stock = draw(st.integers(min_value=qty, max_value=qty + 500))
        else:
            stock = draw(st.integers(min_value=0, max_value=500))
        catalog.append({"sku": sku, "name": "p", "price": price, "stock": stock})
        raw_items.append({"sku": sku, "qty": qty})

    payment_method = draw(payment_methods)
    return catalog, raw_items, payment_method


def _seed(repo: InMemoryPosRepository, catalog: list[dict]) -> None:
    service = CatalogService(repo)
    for kwargs in catalog:
        service.create_product(**kwargs)


def _stock_map(repo: InMemoryPosRepository) -> dict[str, int]:
    return {
        # PK is PRODUCT#<sku>; recover the sku via the catalog service listing.
        p.sku: p.stock
        for p in CatalogService(repo).list_products()
    }


# --- Property 6 ------------------------------------------------------------

# Feature: pos-mvp, Property 6: Registered sale round-trips its fields with a unique id
@given(data=catalog_and_sale())
def test_sale_round_trips_fields_with_unique_id(data):
    catalog, raw_items, payment_method = data
    repo = InMemoryPosRepository()
    _seed(repo, catalog)
    service = SalesService(repo)

    sale = service.register_sale(raw_items, payment_method)

    # Persisted under its date partition and round-trips its fields.
    stored = repo.query_sales_by_date(sale.timestamp.date().isoformat())
    assert len(stored) == 1
    persisted = stored[0]
    assert persisted["sale_id"] == sale.sale_id
    assert persisted["payment_method"] == payment_method
    assert Decimal(persisted["total"]) == sale.total
    # Items round-trip by sku/qty.
    persisted_items = {i["sku"]: int(i["qty"]) for i in persisted["items"]}
    expected_items = {i["sku"]: i["qty"] for i in raw_items}
    assert persisted_items == expected_items

    # Unique id: registering several sales in the SAME repo yields all-distinct
    # sale ids (not just two fresh UUIDs from independent repos).
    repo_multi = InMemoryPosRepository()
    # Give every product plenty of stock so repeated sales all commit.
    inflated = [{**c, "stock": c["stock"] + 10_000} for c in catalog]
    _seed(repo_multi, inflated)
    multi_service = SalesService(repo_multi)
    sale_ids = [
        multi_service.register_sale(raw_items, payment_method).sale_id
        for _ in range(5)
    ]
    assert len(set(sale_ids)) == len(sale_ids)


# --- Property 7 ------------------------------------------------------------

# Feature: pos-mvp, Property 7: Invalid sale is rejected and persists nothing
@given(
    catalog=st.lists(
        st.fixed_dictionaries(
            {
                "sku": skus,
                "name": st.just("p"),
                "price": unit_prices,
                "stock": st.integers(min_value=1, max_value=100),
            }
        ),
        max_size=3,
    ).map(lambda xs: list({x["sku"]: x for x in xs}.values())),
    bad_payment=st.text(max_size=10).filter(lambda s: s not in {"efectivo", "tarjeta"}),
)
def test_invalid_payment_method_rejected_persists_nothing(catalog, bad_payment):
    repo = InMemoryPosRepository()
    _seed(repo, catalog)
    service = SalesService(repo)
    items = [{"sku": catalog[0]["sku"], "qty": 1}] if catalog else [{"sku": "X", "qty": 1}]
    before = _stock_map(repo)

    with pytest.raises(ValidationError) as exc:
        service.register_sale(items, bad_payment)
    assert exc.value.field == "payment_method"

    assert _stock_map(repo) == before
    # No sale persisted on any date.
    assert _no_sales(repo)


# Feature: pos-mvp, Property 7: Invalid sale is rejected and persists nothing
@given(
    existing=st.fixed_dictionaries(
        {
            "sku": skus,
            "name": st.just("p"),
            "price": unit_prices,
            "stock": st.integers(min_value=1, max_value=100),
        }
    ),
    unknown_sku=skus,
    payment_method=payment_methods,
)
def test_unknown_sku_rejected_persists_nothing(existing, unknown_sku, payment_method):
    assume(unknown_sku != existing["sku"])
    repo = InMemoryPosRepository()
    _seed(repo, [existing])
    service = SalesService(repo)
    before = _stock_map(repo)

    with pytest.raises(UnknownSku) as exc:
        service.register_sale(
            [{"sku": existing["sku"], "qty": 1}, {"sku": unknown_sku, "qty": 1}],
            payment_method,
        )
    assert exc.value.sku == unknown_sku

    assert _stock_map(repo) == before
    assert _no_sales(repo)


# Feature: pos-mvp, Property 7: Invalid sale is rejected and persists nothing
@given(
    product=st.fixed_dictionaries(
        {
            "sku": skus,
            "name": st.just("p"),
            "price": unit_prices,
            "stock": st.integers(min_value=1, max_value=100),
        }
    ),
    bad_qty=st.one_of(
        st.integers(max_value=QTY_MIN - 1),
        st.integers(min_value=QTY_MAX + 1),
    ),
    payment_method=payment_methods,
)
def test_invalid_quantity_rejected_persists_nothing(product, bad_qty, payment_method):
    repo = InMemoryPosRepository()
    _seed(repo, [product])
    service = SalesService(repo)
    before = _stock_map(repo)

    with pytest.raises(ValidationError) as exc:
        service.register_sale([{"sku": product["sku"], "qty": bad_qty}], payment_method)
    assert exc.value.field == "qty"

    assert _stock_map(repo) == before
    assert _no_sales(repo)


# --- Property 8 ------------------------------------------------------------

# Feature: pos-mvp, Property 8: Sufficient stock decrements each product by its quantity
@given(data=catalog_and_sale())
def test_sufficient_stock_decrements_each_product(data):
    catalog, raw_items, payment_method = data
    repo = InMemoryPosRepository()
    _seed(repo, catalog)
    service = SalesService(repo)

    before = _stock_map(repo)
    service.register_sale(raw_items, payment_method)
    after = _stock_map(repo)

    ordered = {item["sku"]: item["qty"] for item in raw_items}
    for sku, prior in before.items():
        expected = prior - ordered.get(sku, 0)
        assert after[sku] == expected
        assert after[sku] >= 0  # never negative


# --- Property 9 ------------------------------------------------------------

# Feature: pos-mvp, Property 9: Sale registration is all-or-nothing
@given(data=catalog_and_sale(ensure_sufficient_stock=False))
def test_sale_registration_is_all_or_nothing(data):
    catalog, raw_items, payment_method = data
    repo = InMemoryPosRepository()
    _seed(repo, catalog)
    service = SalesService(repo)

    before = _stock_map(repo)
    ordered = {item["sku"]: item["qty"] for item in raw_items}

    committed = True
    try:
        sale = service.register_sale(raw_items, payment_method)
    except InsufficientStock:
        committed = False

    after = _stock_map(repo)
    if committed:
        # (a) sale persisted AND every product decremented by its quantity.
        for sku, prior in before.items():
            assert after[sku] == prior - ordered.get(sku, 0)
        assert len(repo.query_sales_by_date(sale.timestamp.date().isoformat())) == 1
    else:
        # (b) no sale persisted AND every stock at its pre-attempt value.
        assert after == before
        assert _no_sales(repo)


# Feature: pos-mvp, Property 9: Sale registration is all-or-nothing
@given(data=catalog_and_sale())
def test_non_condition_failure_leaves_no_partial_state(data):
    # All-or-nothing under the TransactionFailed branch: even with sufficient
    # stock, an injected non-condition failure must leave no partial state
    # (neither the sale nor any stock decrement).
    catalog, raw_items, payment_method = data
    repo = InMemoryPosRepository()
    _seed(repo, catalog)
    service = SalesService(repo)

    before = _stock_map(repo)
    repo.fail_next_transaction = True  # force a non-condition cancellation

    with pytest.raises(TransactionFailed):
        service.register_sale(raw_items, payment_method)

    # Nothing committed: every stock at its pre-attempt value, no sale persisted.
    assert _stock_map(repo) == before
    assert _no_sales(repo)


# --- Property 10 -----------------------------------------------------------

# Feature: pos-mvp, Property 10: Insufficient stock rejects the whole sale and reports offending SKUs
@given(data=catalog_and_sale(ensure_sufficient_stock=False))
def test_insufficient_stock_reports_exactly_offending_skus(data):
    catalog, raw_items, payment_method = data
    # Make the property meaningful: require at least one offending product.
    stock_by_sku = {c["sku"]: c["stock"] for c in catalog}
    ordered = {item["sku"]: item["qty"] for item in raw_items}
    offenders = {sku for sku, qty in ordered.items() if stock_by_sku[sku] < qty}
    assume(offenders)

    repo = InMemoryPosRepository()
    _seed(repo, catalog)
    service = SalesService(repo)
    before = _stock_map(repo)

    with pytest.raises(InsufficientStock) as exc:
        service.register_sale(raw_items, payment_method)

    assert set(exc.value.skus) == offenders
    # Nothing persisted, stock preserved exactly.
    assert _stock_map(repo) == before
    assert _no_sales(repo)


# --- Property 11 -----------------------------------------------------------

# Feature: pos-mvp, Property 11: Concurrent sales never oversell a product
@given(
    initial_stock=st.integers(min_value=0, max_value=50),
    quantities=st.lists(
        st.integers(min_value=QTY_MIN, max_value=20), min_size=1, max_size=10
    ),
    price=unit_prices,
)
def test_concurrent_sales_never_oversell(initial_stock, quantities, price):
    # Competing sales for a single product applied as serialized conditional
    # transactions against the fake (DynamoDB serializes concurrent conditional
    # updates on the same item; the fake reproduces that per-commit).
    repo = InMemoryPosRepository()
    _seed(repo, [{"sku": "P", "name": "p", "price": price, "stock": initial_stock}])
    service = SalesService(repo)

    committed_qty = 0
    for qty in quantities:
        before_attempt = _stock_map(repo)["P"]
        try:
            service.register_sale([{"sku": "P", "qty": qty}], "efectivo")
            committed_qty += qty
            # A commit decrements exactly by qty.
            assert _stock_map(repo)["P"] == before_attempt - qty
        except InsufficientStock:
            # A rejected attempt must change nothing: the invariant is checked
            # at every step of the interleaving, not just at the end.
            assert _stock_map(repo)["P"] == before_attempt

    # Never oversold: committed quantities fit within the prior available stock,
    # and the remaining stock equals initial minus what committed.
    assert committed_qty <= initial_stock
    assert _stock_map(repo)["P"] == initial_stock - committed_qty
    assert _stock_map(repo)["P"] >= 0


# --- helpers ---------------------------------------------------------------


def _no_sales(repo: InMemoryPosRepository) -> bool:
    """True if no sale item exists in the store on any date."""

    from app.repository.keys import SALE_PREFIX

    return not any(
        pk.startswith(SALE_PREFIX) for (pk, _sk) in repo._items  # noqa: SLF001
    )
