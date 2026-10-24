"""API integration tests for the SmartPOS Copilot endpoints (US-1, US-2).

These exercise the full HTTP stack (routing, FastAPI Query validation, service
calls, and the error-envelope exception handlers) against a fresh in-memory
transactional repository per test, injected by overriding the ``get_repository``
dependency — the same pattern as ``test_api.py``.

Coverage:
- ``GET /copilot/promociones`` returns 200 and a list of combos when overstock
  products exist.
- ``GET /copilot/promociones`` honours the ``limite`` query param.
- ``GET /copilot/promociones?limite=0`` is rejected by FastAPI Query(ge=1); the
  app's RequestValidationError handler normalises it to 400 VALIDATION_ERROR.
- ``GET /copilot/diagnostico-hoy`` returns 200 with the correct shape.
- ``GET /copilot/diagnostico-hoy?date=<future>`` returns 400 with code INVALID_DATE.
- Money fields in responses are serialised as strings (Decimal precision, Rule 4).
"""

from __future__ import annotations

from datetime import datetime, timezone

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


def _seed_overstock_catalog(client: TestClient) -> None:
    """Seed several overstock products (stock > 10) of different stock levels."""

    _create_product(client, "CAFE-01", "Café", "3.00", 99)
    _create_product(client, "PAN-03", "Pan", "1.50", 55)
    _create_product(client, "JUG-02", "Jugo", "2.00", 30)
    _create_product(client, "GAL-04", "Galleta", "0.80", 12)


# --- GET /copilot/promociones ----------------------------------------------


def test_promociones_returns_200_and_combos_when_overstock_exists(client: TestClient):
    _seed_overstock_catalog(client)

    response = client.get("/copilot/promociones")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    # Each combo has the expected shape.
    first = body[0]
    assert set(first.keys()) == {
        "nombre",
        "skus",
        "precio_original",
        "precio_combo",
        "ahorro",
        "pitch_cajero",
    }
    assert len(first["skus"]) == 2
    assert isinstance(first["pitch_cajero"], str) and first["pitch_cajero"]


def test_promociones_empty_catalog_returns_empty_list(client: TestClient):
    response = client.get("/copilot/promociones")
    assert response.status_code == 200
    assert response.json() == []


def test_promociones_respects_limite_query_param(client: TestClient):
    # Seed 6 overstock products → up to 3 possible pairs.
    for i in range(6):
        _create_product(client, f"P{i}", f"Producto {i}", f"{i + 1}.00", 20 + i)

    response = client.get("/copilot/promociones", params={"limite": 1})
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = client.get("/copilot/promociones", params={"limite": 2})
    assert response.status_code == 200
    assert len(response.json()) <= 2


def test_promociones_limite_zero_returns_400_validation_error(client: TestClient):
    # FastAPI Query(ge=1) rejects 0; the app's RequestValidationError handler
    # normalises it to the canonical 400 VALIDATION_ERROR envelope.
    response = client.get("/copilot/promociones", params={"limite": 0})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_promociones_limite_above_max_returns_400_validation_error(client: TestClient):
    # FastAPI Query(le=100) rejects 101; normalised to 400 VALIDATION_ERROR.
    response = client.get("/copilot/promociones", params={"limite": 101})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_promociones_money_fields_are_strings(client: TestClient):
    _seed_overstock_catalog(client)

    response = client.get("/copilot/promociones")
    assert response.status_code == 200
    body = response.json()
    assert body, "expected at least one combo"
    combo = body[0]
    for field in ("precio_original", "precio_combo", "ahorro"):
        assert isinstance(combo[field], str), f"{field} must be a string, got {type(combo[field])}"
    # A positive saving is offered (string compares fine for "X.XX" but assert value).
    assert combo["ahorro"] != "0.00"


# --- GET /copilot/diagnostico-hoy ------------------------------------------


def test_diagnostico_hoy_returns_200_with_correct_shape(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 100)
    _create_product(client, "LOW-01", "Casi agotado", "1.00", 2)

    response = client.get("/copilot/diagnostico-hoy")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "fecha",
        "total_ventas",
        "productos_criticos",
        "recomendacion_estrategica",
    }
    today = datetime.now(timezone.utc).date().isoformat()
    assert body["fecha"] == today
    assert isinstance(body["productos_criticos"], list)
    # LOW-01 (stock 2 < 5) is flagged as critical.
    assert "LOW-01" in body["productos_criticos"]
    assert isinstance(body["recomendacion_estrategica"], str)
    assert body["recomendacion_estrategica"]


def test_diagnostico_hoy_total_ventas_is_string(client: TestClient):
    response = client.get("/copilot/diagnostico-hoy")
    assert response.status_code == 200
    body = response.json()
    # Money carried as a decimal string (Rule 4), never a JSON number.
    assert isinstance(body["total_ventas"], str)
    assert body["total_ventas"] == "0.00"


def test_diagnostico_hoy_reflects_registered_sales(client: TestClient):
    _create_product(client, "CAFE-01", "Café", "2.50", 100)
    client.post(
        "/sales",
        json={"items": [{"sku": "CAFE-01", "qty": 2}], "payment_method": "efectivo"},
    )

    response = client.get("/copilot/diagnostico-hoy")
    assert response.status_code == 200
    assert response.json()["total_ventas"] == "5.00"


def test_diagnostico_hoy_future_date_returns_400_invalid_date(client: TestClient):
    response = client.get("/copilot/diagnostico-hoy", params={"date": "2099-01-01"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_DATE"
    assert body["error"]["details"]["date"] == "2099-01-01"


def test_diagnostico_hoy_malformed_date_returns_400_invalid_date(client: TestClient):
    response = client.get("/copilot/diagnostico-hoy", params={"date": "2025-13-40"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATE"
