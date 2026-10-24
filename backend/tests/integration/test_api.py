"""API integration tests over the FastAPI app with the fake repository (task 9.4).

These exercise the full HTTP stack (routing, request schemas, service calls,
and the error-envelope exception handlers) against a fresh in-memory
transactional repository per test, injected by overriding the ``get_repository``
dependency. They cover the catalog, sale, and report happy paths plus the key
error envelopes: ``DUPLICATE_SKU`` (409), ``PRODUCT_NOT_FOUND`` (404),
``INSUFFICIENT_STOCK`` (409 with the offending ``skus``), and ``INVALID_DATE``
(400).

Requirements: 1.1, 1.2, 1.8, 2.1, 2.5, 3.3, 4.1, 4.5.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.deps import get_repository
from app.repository.memory import InMemoryPosRepository


@pytest.fixture()
def repo() -> InMemoryPosRepository:
    """A fresh in-memory repository per test."""

    return InMemoryPosRepository()


@pytest.fixture()
def client(repo: InMemoryPosRepository) -> TestClient:
    """A TestClient whose app uses the fake repository for every request."""

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(app)


def _create_product(client: TestClient, sku: str, name: str, price: str, stock: int):
    return client.post(
        "/products",
        json={"sku": sku, "name": name, "price": price, "stock": stock},
    )


# --- catalog happy paths ----------------------------------------------------


# Requirement 1.1
def test_create_product_happy_path(client: TestClient):
    response = _create_product(client, "CAFE-01", "Café americano", "2.50", 100)
    assert response.status_code == 201
    assert response.json() == {
        "sku": "CAFE-01",
        "name": "Café americano",
        "price": "2.50",
        "stock": 100,
    }


# Requirement 1.5
def test_list_products_happy_path(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 100)
    _create_product(client, "PAN-03", "Pan", "1.00", 20)

    response = client.get("/products")
    assert response.status_code == 200
    body = response.json()
    assert {p["sku"] for p in body} == {"CAFE-01", "PAN-03"}


def test_list_empty_catalog_returns_empty_list(client: TestClient):
    response = client.get("/products")
    assert response.status_code == 200
    assert response.json() == []


# Requirement 1.7
def test_update_product_happy_path(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 100)

    response = client.put("/products/CAFE-01", json={"price": "3.00", "stock": 80})
    assert response.status_code == 200
    body = response.json()
    assert body["price"] == "3.00"
    assert body["stock"] == 80
    assert body["name"] == "Café"  # untouched field preserved


# --- catalog error envelopes ------------------------------------------------


# Requirement 1.2
def test_duplicate_sku_returns_409_envelope(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 100)

    response = _create_product(client, "CAFE-01", "Otro", "9.99", 1)
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "DUPLICATE_SKU"
    assert body["error"]["details"]["sku"] == "CAFE-01"


# Requirement 1.8
def test_update_missing_sku_returns_404_envelope(client: TestClient):
    response = client.put("/products/NOPE", json={"stock": 5})
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "PRODUCT_NOT_FOUND"
    assert body["error"]["details"]["sku"] == "NOPE"


# Requirement 1.3 (field validation surfaces VALIDATION_ERROR 400)
def test_invalid_price_returns_400_envelope(client: TestClient):
    response = _create_product(client, "BAD-01", "Malo", "0.00", 1)
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == "price"


# --- sales ------------------------------------------------------------------


# Requirement 2.1
def test_register_sale_happy_path(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 100)
    _create_product(client, "PAN-03", "Pan", "1.00", 20)

    response = client.post(
        "/sales",
        json={
            "items": [
                {"sku": "CAFE-01", "qty": 2},
                {"sku": "PAN-03", "qty": 1},
            ],
            "payment_method": "efectivo",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["total"] == "6.00"
    assert body["payment_method"] == "efectivo"
    assert body["sale_id"]
    assert len(body["items"]) == 2

    # Stock was discounted atomically.
    products = {p["sku"]: p for p in client.get("/products").json()}
    assert products["CAFE-01"]["stock"] == 98
    assert products["PAN-03"]["stock"] == 19


# Requirement 2.5
def test_sale_unknown_sku_returns_404_envelope(client: TestClient):
    response = client.post(
        "/sales",
        json={"items": [{"sku": "NOPE", "qty": 1}], "payment_method": "efectivo"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "UNKNOWN_SKU"
    assert body["error"]["details"]["sku"] == "NOPE"


# Requirement 3.3
def test_sale_insufficient_stock_returns_409_with_skus(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 1)
    _create_product(client, "PAN-03", "Pan", "1.00", 0)

    response = client.post(
        "/sales",
        json={
            "items": [
                {"sku": "CAFE-01", "qty": 5},
                {"sku": "PAN-03", "qty": 2},
            ],
            "payment_method": "tarjeta",
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "INSUFFICIENT_STOCK"
    assert set(body["error"]["details"]["skus"]) == {"CAFE-01", "PAN-03"}

    # Nothing was persisted: stock preserved exactly.
    products = {p["sku"]: p for p in client.get("/products").json()}
    assert products["CAFE-01"]["stock"] == 1
    assert products["PAN-03"]["stock"] == 0


def test_sale_invalid_payment_method_returns_400(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 10)
    response = client.post(
        "/sales",
        json={"items": [{"sku": "CAFE-01", "qty": 1}], "payment_method": "cheque"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == "payment_method"


def test_sale_empty_items_rejected_at_schema_boundary(client: TestClient):
    # items min_length=1: an empty list is rejected by the schema before any
    # processing, kept inside the canonical envelope.
    response = client.post(
        "/sales", json={"items": [], "payment_method": "efectivo"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sale_oversized_items_rejected_at_schema_boundary(client: TestClient):
    # items max_length=ITEMS_MAX: a payload over the line cap is rejected early
    # (before deserializing/looking up every line), inside the envelope.
    from app.models.sale import ITEMS_MAX

    items = [{"sku": f"S{i}", "qty": 1} for i in range(ITEMS_MAX + 1)]
    response = client.post(
        "/sales", json={"items": items, "payment_method": "efectivo"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sale_qty_out_of_range_rejected_at_schema_boundary(client: TestClient):
    # qty is bounded 1..9999 at the boundary; an absurd qty is rejected early.
    _create_product(client, "CAFE-01", "Café", "2.50", 10)
    response = client.post(
        "/sales",
        json={"items": [{"sku": "CAFE-01", "qty": 10_000}], "payment_method": "efectivo"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- daily report -----------------------------------------------------------


# Requirement 4.1
def test_daily_report_happy_path(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 100)
    _create_product(client, "PAN-03", "Pan", "1.00", 20)
    client.post(
        "/sales",
        json={"items": [{"sku": "CAFE-01", "qty": 2}], "payment_method": "efectivo"},
    )
    client.post(
        "/sales",
        json={"items": [{"sku": "PAN-03", "qty": 3}], "payment_method": "tarjeta"},
    )

    today = datetime.now(timezone.utc).date().isoformat()
    response = client.get("/reports/daily", params={"date": today})
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == today
    assert body["sales_count"] == 2
    assert body["total"] == "8.00"
    assert body["by_payment_method"] == {"efectivo": "5.00", "tarjeta": "3.00"}


def test_daily_report_default_date_no_sales(client: TestClient):
    response = client.get("/reports/daily")
    assert response.status_code == 200
    body = response.json()
    assert body["sales_count"] == 0
    assert body["total"] == "0.00"
    assert body["by_payment_method"] == {}


# Requirement 4.5
def test_daily_report_invalid_date_returns_400(client: TestClient):
    response = client.get("/reports/daily", params={"date": "2025-13-40"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_DATE"
    assert body["error"]["details"]["date"] == "2025-13-40"


# Requirement 4.5 (future date)
def test_daily_report_future_date_returns_400(client: TestClient):
    future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    response = client.get("/reports/daily", params={"date": future})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATE"
