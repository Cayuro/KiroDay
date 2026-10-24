"""Unit tests for CopilotService (SmartPOS Copilot).

Covers generar_promociones() and analisis_gerencial() using the real in-memory
repository and services, without mocks. Validates all business rules:

- Overstock threshold: only products with stock > OVERSTOCK_THRESHOLD (10)
  qualify as combo candidates.
- Margin protection over COST: precio_combo >= costo_total * (1 + MIN_MARGIN),
  where costo_total = quantize(precio_original * COST_RATIO). This is the floor
  defined by Rule 1 ("15% margin over estimated cost"), not a floor over price.
- Overstock priority (Rule 2): candidates are ordered by stock descending, so
  the highest-inventory product anchors the combo.
- Positive saving: no combo is emitted with ahorro <= 0.
- Limit validation: generar_promociones rejects limits outside [1, 100].
- Critical stock alert: products with stock < CRITICAL_STOCK_THRESHOLD (5)
  are reported in productos_criticos.
- Monetary precision: all money values are Decimal, never float.
- Date validation: a future date raises InvalidDate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.repository.memory import InMemoryPosRepository
from app.services.catalog import CatalogService
from app.services.copilot import (
    COST_RATIO,
    CRITICAL_STOCK_THRESHOLD,
    MAX_COMBO_LIMIT,
    MIN_MARGIN,
    OVERSTOCK_THRESHOLD,
    CopilotService,
)
from app.services.report import InvalidDate, ReportService
from app.services.sales import SalesService


def _margin_floor(precio_original: Decimal) -> Decimal:
    """Replicate the service's margin floor: estimated cost * (1 + MIN_MARGIN).

    Mirrors ``CopilotService`` internals so the test asserts against the exact
    same quantization sequence (cost is quantized before the margin is applied).
    """
    costo_total = (precio_original * COST_RATIO).quantize(Decimal("0.01"))
    return (costo_total * (Decimal("1") + MIN_MARGIN)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_services(
    products: list[dict] | None = None,
) -> tuple[CopilotService, InMemoryPosRepository]:
    """Return a (CopilotService, repo) pair pre-loaded with ``products``.

    ``products`` items must have keys: sku, name, price (str), stock (int).
    """
    repo = InMemoryPosRepository()
    catalog = CatalogService(repo)
    if products:
        for p in products:
            catalog.create_product(
                sku=p["sku"],
                name=p["name"],
                price=p["price"],
                stock=p["stock"],
            )
    report = ReportService(repo)
    return CopilotService(catalog, report), repo


def _overstock(stock: int = OVERSTOCK_THRESHOLD + 1) -> int:
    """Return a stock value guaranteed to be above the overstock threshold."""
    return stock


def _understock() -> int:
    """Return a stock value guaranteed NOT to qualify for combos (at threshold)."""
    return OVERSTOCK_THRESHOLD


# ---------------------------------------------------------------------------
# generar_promociones — empty / too-few overstock cases
# ---------------------------------------------------------------------------


def test_promo_empty_catalog_returns_no_combos() -> None:
    """Empty catalog produces no combos."""
    service, _ = _make_services()
    assert service.generar_promociones() == []


def test_promo_single_overstock_product_returns_no_combos() -> None:
    """A single overstock product cannot form a combo (needs at least 2)."""
    service, _ = _make_services(
        [{"sku": "A", "name": "Café", "price": "2.50", "stock": _overstock()}]
    )
    assert service.generar_promociones() == []


def test_promo_no_overstock_products_returns_no_combos() -> None:
    """Products at or below OVERSTOCK_THRESHOLD never qualify as candidates."""
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "2.50", "stock": _understock()},
            {"sku": "B", "name": "Pan", "price": "1.00", "stock": _understock()},
            # One product exactly at threshold also must not qualify.
            {"sku": "C", "name": "Leche", "price": "1.50", "stock": OVERSTOCK_THRESHOLD},
        ]
    )
    assert service.generar_promociones() == []


def test_promo_some_below_threshold_do_not_enter_combos() -> None:
    """Only the overstock product contributes; below-threshold products are excluded."""
    service, _ = _make_services(
        [
            {"sku": "OVER", "name": "Overstock Product", "price": "5.00", "stock": _overstock()},
            # Only one overstock → still not enough for a combo.
            {"sku": "LOW", "name": "Low Stock", "price": "3.00", "stock": 3},
        ]
    )
    assert service.generar_promociones() == []


# ---------------------------------------------------------------------------
# generar_promociones — happy path with 2+ overstock products
# ---------------------------------------------------------------------------


def test_promo_two_overstock_products_generates_exactly_one_combo() -> None:
    """Exactly 1 combo from exactly 2 overstock products."""
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "3.00", "stock": _overstock()},
            {"sku": "B", "name": "Pan", "price": "1.50", "stock": _overstock()},
        ]
    )
    combos = service.generar_promociones()
    assert len(combos) == 1


def test_promo_precio_original_equals_sum_of_unit_prices() -> None:
    """precio_original must equal the sum of the two products' individual prices."""
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "3.00", "stock": _overstock()},
            {"sku": "B", "name": "Pan", "price": "1.50", "stock": _overstock()},
        ]
    )
    combo = service.generar_promociones()[0]
    expected = Decimal("3.00") + Decimal("1.50")
    assert combo.precio_original == expected


def test_promo_margin_protection_never_violated() -> None:
    """precio_combo never breaches the 15% margin floor over estimated cost.

    The floor is ``costo_total * (1 + MIN_MARGIN)`` where
    ``costo_total = quantize(precio_original * COST_RATIO)`` (Rule 1).
    """
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "3.00", "stock": _overstock()},
            {"sku": "B", "name": "Pan", "price": "1.50", "stock": _overstock()},
            {"sku": "C", "name": "Jugo", "price": "2.00", "stock": _overstock()},
            {"sku": "D", "name": "Galleta", "price": "0.80", "stock": _overstock()},
        ]
    )
    combos = service.generar_promociones(limite_combos=10)
    assert combos, "expected at least one combo"
    for combo in combos:
        costo_total = (combo.precio_original * COST_RATIO).quantize(Decimal("0.01"))
        floor = _margin_floor(combo.precio_original)
        assert combo.precio_combo >= floor, (
            f"Margin violated for {combo.nombre}: "
            f"precio_combo={combo.precio_combo} < floor={floor}"
        )
        # The floor is exactly cost plus the minimum margin over that cost.
        assert floor == (costo_total * (Decimal("1") + MIN_MARGIN)).quantize(
            Decimal("0.01")
        )


def test_promo_ahorro_is_non_negative() -> None:
    """ahorro = precio_original - precio_combo must be >= 0 always."""
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "3.00", "stock": _overstock()},
            {"sku": "B", "name": "Pan", "price": "1.50", "stock": _overstock()},
        ]
    )
    combo = service.generar_promociones()[0]
    assert combo.ahorro >= Decimal("0.00")
    assert combo.ahorro == combo.precio_original - combo.precio_combo


def test_promo_pitch_cajero_is_non_empty_and_mentions_product_names() -> None:
    """pitch_cajero must be a non-empty string that references both product names."""
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "3.00", "stock": _overstock()},
            {"sku": "B", "name": "Pan", "price": "1.50", "stock": _overstock()},
        ]
    )
    combo = service.generar_promociones()[0]
    assert isinstance(combo.pitch_cajero, str)
    assert len(combo.pitch_cajero) > 0
    assert "Café" in combo.pitch_cajero
    assert "Pan" in combo.pitch_cajero


def test_promo_limite_combos_is_respected() -> None:
    """generar_promociones never returns more combos than limite_combos."""
    # 6 overstock products → at most 3 pairs; request only 2.
    products = [
        {"sku": f"P{i}", "name": f"Producto {i}", "price": f"{i + 1}.00", "stock": _overstock()}
        for i in range(6)
    ]
    service, _ = _make_services(products)
    for limit in (1, 2, 3):
        combos = service.generar_promociones(limite_combos=limit)
        assert len(combos) <= limit, f"Expected <= {limit} combos, got {len(combos)}"


# ---------------------------------------------------------------------------
# generar_promociones — overstock priority (Rule 2)
# ---------------------------------------------------------------------------


def test_promo_anchors_on_highest_stock_product() -> None:
    """With 3+ overstock products of different stock, the combo anchors on the
    highest-stock item (Rule 2: prioritise moving the largest inventory first)."""
    service, _ = _make_services(
        [
            {"sku": "LOW", "name": "Bajo", "price": "2.00", "stock": 12},
            {"sku": "MID", "name": "Medio", "price": "2.00", "stock": 30},
            {"sku": "HIGH", "name": "Alto", "price": "2.00", "stock": 99},
        ]
    )
    combos = service.generar_promociones(limite_combos=5)
    assert combos, "expected at least one combo"
    # Candidates sorted by stock desc → HIGH anchors (hi=0), LOW is the inner
    # pair partner (lo=last). The first combo must include the highest-stock SKU.
    assert "HIGH" in combos[0].skus


def test_promo_pairs_highest_stock_with_lowest_stock() -> None:
    """The first combo pairs the top-stock product with the bottom-stock one."""
    service, _ = _make_services(
        [
            {"sku": "S12", "name": "P12", "price": "2.00", "stock": 12},
            {"sku": "S30", "name": "P30", "price": "2.00", "stock": 30},
            {"sku": "S55", "name": "P55", "price": "2.00", "stock": 55},
            {"sku": "S99", "name": "P99", "price": "2.00", "stock": 99},
        ]
    )
    combos = service.generar_promociones(limite_combos=5)
    assert combos, "expected at least one combo"
    # Sorted by stock desc: [S99, S55, S30, S12]. First pair = outermost = S99+S12.
    assert set(combos[0].skus) == {"S99", "S12"}


# ---------------------------------------------------------------------------
# generar_promociones — limit validation (Rule 3)
# ---------------------------------------------------------------------------


def test_promo_limite_zero_raises_validation_error() -> None:
    """A limit of 0 is outside [1, MAX_COMBO_LIMIT] and must raise ValidationError."""
    service, _ = _make_services()
    with pytest.raises(ValidationError):
        service.generar_promociones(limite_combos=0)


def test_promo_limite_negative_raises_validation_error() -> None:
    """A negative limit must raise ValidationError."""
    service, _ = _make_services()
    with pytest.raises(ValidationError):
        service.generar_promociones(limite_combos=-1)


def test_promo_limite_above_max_raises_validation_error() -> None:
    """A limit above MAX_COMBO_LIMIT (100) must raise ValidationError."""
    service, _ = _make_services()
    with pytest.raises(ValidationError):
        service.generar_promociones(limite_combos=MAX_COMBO_LIMIT + 1)


def test_promo_limite_at_bounds_is_accepted() -> None:
    """The inclusive bounds 1 and MAX_COMBO_LIMIT must be accepted (no raise)."""
    service, _ = _make_services()
    # No overstock products → returns [] but must not raise for valid bounds.
    assert service.generar_promociones(limite_combos=1) == []
    assert service.generar_promociones(limite_combos=MAX_COMBO_LIMIT) == []


# ---------------------------------------------------------------------------
# generar_promociones — no combo with non-positive saving (Rule 4)
# ---------------------------------------------------------------------------


def test_promo_no_combo_has_non_positive_saving() -> None:
    """Every emitted combo must offer a strictly positive ahorro (> 0)."""
    products = [
        {"sku": f"P{i}", "name": f"Producto {i}", "price": f"{i + 1}.00", "stock": _overstock()}
        for i in range(6)
    ]
    service, _ = _make_services(products)
    combos = service.generar_promociones(limite_combos=MAX_COMBO_LIMIT)
    assert combos, "expected at least one combo"
    for combo in combos:
        assert combo.ahorro > Decimal("0.00"), (
            f"Combo {combo.nombre} has non-positive saving: {combo.ahorro}"
        )


def test_promo_money_values_are_decimal_not_float() -> None:
    """All monetary fields on PromoCombo must be Decimal instances."""
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "3.00", "stock": _overstock()},
            {"sku": "B", "name": "Pan", "price": "1.50", "stock": _overstock()},
        ]
    )
    combo = service.generar_promociones()[0]
    assert isinstance(combo.precio_original, Decimal), "precio_original must be Decimal"
    assert isinstance(combo.precio_combo, Decimal), "precio_combo must be Decimal"
    assert isinstance(combo.ahorro, Decimal), "ahorro must be Decimal"


def test_promo_skus_list_contains_both_product_skus() -> None:
    """The combo's skus list must include exactly the two participating SKUs."""
    service, _ = _make_services(
        [
            {"sku": "CAF", "name": "Café", "price": "3.00", "stock": _overstock()},
            {"sku": "PAN", "name": "Pan", "price": "1.50", "stock": _overstock()},
        ]
    )
    combo = service.generar_promociones()[0]
    assert set(combo.skus) == {"CAF", "PAN"}


# ---------------------------------------------------------------------------
# analisis_gerencial — no sales today
# ---------------------------------------------------------------------------


def test_diagnostico_no_sales_total_is_zero() -> None:
    """When no sales exist for the given date, total_ventas must be Decimal('0.00')."""
    service, _ = _make_services()
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert resumen.total_ventas == Decimal("0.00")


def test_diagnostico_no_sales_products_criticos_empty_when_no_low_stock() -> None:
    """With sufficient stock and no sales, productos_criticos is empty."""
    service, _ = _make_services(
        [{"sku": "A", "name": "Café", "price": "2.50", "stock": 20}]
    )
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert resumen.productos_criticos == []


# ---------------------------------------------------------------------------
# analisis_gerencial — critical stock detection
# ---------------------------------------------------------------------------


def test_diagnostico_identifies_critical_stock_products() -> None:
    """Products with stock < CRITICAL_STOCK_THRESHOLD appear in productos_criticos."""
    service, _ = _make_services(
        [
            # Exactly below threshold → critical.
            {"sku": "CRIT", "name": "Crítico", "price": "1.00", "stock": CRITICAL_STOCK_THRESHOLD - 1},
            # Exactly at threshold → not critical.
            {"sku": "OK", "name": "Normal", "price": "2.00", "stock": CRITICAL_STOCK_THRESHOLD},
        ]
    )
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert "CRIT" in resumen.productos_criticos
    assert "OK" not in resumen.productos_criticos


def test_diagnostico_zero_stock_is_critical() -> None:
    """A product with stock=0 is definitely critical (< 5)."""
    service, _ = _make_services(
        [{"sku": "ZERO", "name": "Sin stock", "price": "1.50", "stock": 0}]
    )
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert "ZERO" in resumen.productos_criticos


def test_diagnostico_all_above_threshold_no_criticos() -> None:
    """When all products are above the critical threshold, list is empty."""
    service, _ = _make_services(
        [
            {"sku": "A", "name": "Café", "price": "2.50", "stock": 10},
            {"sku": "B", "name": "Pan", "price": "1.00", "stock": 50},
        ]
    )
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert resumen.productos_criticos == []


# ---------------------------------------------------------------------------
# analisis_gerencial — with sales registered today
# ---------------------------------------------------------------------------


def test_diagnostico_total_ventas_reflects_registered_sales() -> None:
    """total_ventas equals the sum of registered sales for the requested date."""
    repo = InMemoryPosRepository()
    catalog = CatalogService(repo)
    catalog.create_product(sku="A", name="Café", price="2.50", stock=20)
    catalog.create_product(sku="B", name="Pan", price="1.00", stock=20)
    report = ReportService(repo)
    copilot = CopilotService(catalog, report)
    sales_svc = SalesService(repo)

    # Register two sales: 2×2.50 + 3×1.00 = 5.00 + 3.00 = 8.00.
    sales_svc.register_sale([{"sku": "A", "qty": 2}], "efectivo")
    sales_svc.register_sale([{"sku": "B", "qty": 3}], "tarjeta")

    today = datetime.now(timezone.utc).date().isoformat()
    resumen = copilot.analisis_gerencial(fecha=today)
    assert resumen.total_ventas == Decimal("8.00")


# ---------------------------------------------------------------------------
# analisis_gerencial — response shape
# ---------------------------------------------------------------------------


def test_diagnostico_recomendacion_is_non_empty_string() -> None:
    """recomendacion_estrategica must always be a non-empty string."""
    service, _ = _make_services()
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert isinstance(resumen.recomendacion_estrategica, str)
    assert len(resumen.recomendacion_estrategica) > 0


def test_diagnostico_fecha_has_correct_format() -> None:
    """fecha in the result must be a YYYY-MM-DD string matching the requested date."""
    service, _ = _make_services()
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert resumen.fecha == today
    # Validate format: must be parseable as a date and match YYYY-MM-DD pattern.
    from datetime import date as date_cls
    parsed = date_cls.fromisoformat(resumen.fecha)
    assert parsed.isoformat() == resumen.fecha


def test_diagnostico_total_ventas_is_decimal() -> None:
    """total_ventas must be a Decimal, never a float."""
    service, _ = _make_services()
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial(fecha=today)
    assert isinstance(resumen.total_ventas, Decimal)


# ---------------------------------------------------------------------------
# analisis_gerencial — date validation
# ---------------------------------------------------------------------------


def test_diagnostico_future_date_raises_invalid_date() -> None:
    """Passing a future date raises InvalidDate (from ReportService)."""
    service, _ = _make_services()
    with pytest.raises(InvalidDate):
        service.analisis_gerencial(fecha="2099-12-31")


def test_diagnostico_malformed_date_raises_invalid_date() -> None:
    """A non-ISO date string raises InvalidDate."""
    service, _ = _make_services()
    with pytest.raises(InvalidDate):
        service.analisis_gerencial(fecha="not-a-date")


def test_diagnostico_defaults_to_today_when_no_date_given() -> None:
    """Calling analisis_gerencial() without a date defaults to today (UTC)."""
    service, _ = _make_services()
    today = datetime.now(timezone.utc).date().isoformat()
    resumen = service.analisis_gerencial()  # no fecha argument
    assert resumen.fecha == today
