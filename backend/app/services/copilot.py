"""CopilotService: smart promotion engine and managerial analytics (SmartPOS Copilot).

This service analyses the live product catalog and today's sales to produce:

* **PromoCombo** suggestions — dynamic bundles that prioritise overstock
  products (``stock > OVERSTOCK_THRESHOLD``) while protecting a minimum 15%
  margin over the product's estimated cost, per ``.kiro/steering/promos-rules.md``.
* **ResumenGerencial** — a daily diagnostic with the day's total, critical-stock
  alerts (``stock < CRITICAL_STOCK_THRESHOLD``), and a plain-Spanish strategic
  recommendation for the store owner.

Business rules enforced here (``.kiro/steering/promos-rules.md``):
- **Margin protection (Rule 1)**: a combo price never drops below 15% margin
  over the *estimated cost*. The ``Product`` model has no cost field, so the
  cost is estimated as ``price * COST_RATIO`` (a conservative proxy); the combo
  price floor is ``costo_total * (1 + MIN_MARGIN)``. If that floor cannot be met
  with the configured discount, the combo is skipped rather than sold under margin.
- **Overstock priority (Rule 2)**: only products with ``stock > OVERSTOCK_THRESHOLD``
  are candidates, and candidates are ordered by stock descending so the highest
  inventory moves first.
- **Monetary precision (Rule 4)**: every calculation uses ``Decimal``; ``float``
  is never used.
- **Strict typing (Rule 4)**: all signatures carry explicit type annotations.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from app.errors import ValidationError
from app.models.copilot import PromoCombo, ResumenGerencial
from app.money import quantize_money
from app.services.catalog import CatalogService
from app.services.report import ReportService

if TYPE_CHECKING:
    from app.models.product import Product

# Products with stock above this threshold are overstock candidates for combos.
OVERSTOCK_THRESHOLD: int = 10

# Products with stock below this threshold trigger a critical-stock alert.
CRITICAL_STOCK_THRESHOLD: int = 5

# Target discount applied to a combo (10 % off the summed original price).
COMBO_DISCOUNT_RATE: Decimal = Decimal("0.10")

# The Product model carries no cost, so we estimate cost as a fraction of the
# sale price. 0.70 means we assume a 30 % markup on cost at the listed price;
# this is a conservative proxy used only to protect the minimum margin (Rule 1).
COST_RATIO: Decimal = Decimal("0.70")

# Minimum margin over estimated cost that a combo price must preserve (Rule 1).
MIN_MARGIN: Decimal = Decimal("0.15")

# Default and maximum number of combos the service will return.
DEFAULT_COMBO_LIMIT: int = 5
MAX_COMBO_LIMIT: int = 100


def _build_pitch(product_a_name: str, product_b_name: str, ahorro: Decimal) -> str:
    """Generate a persuasive, ready-to-say cashier pitch in Spanish.

    Structure: [empathetic greeting] + [opportunity offer] + [direct benefit].
    Only called for combos with a strictly positive ``ahorro``.
    """
    return (
        f"¿Le gustaría llevarse {product_a_name} junto con {product_b_name} "
        f"en combo? ¡Hoy se ahorra ${ahorro} llevando los dos juntos!"
    )


def _estimated_cost(precio: Decimal) -> Decimal:
    """Estimate a product's cost from its sale price (Rule 1 proxy)."""
    return quantize_money(precio * COST_RATIO)


def _margin_floor(precio_original: Decimal) -> Decimal:
    """Return the lowest combo price that still preserves the 15% margin.

    The floor is ``estimated_cost * (1 + MIN_MARGIN)``: selling below this would
    breach the minimum margin over cost defined by Rule 1.
    """
    costo = _estimated_cost(precio_original)
    return quantize_money(costo * (Decimal("1") + MIN_MARGIN))


def _combo_price(precio_original: Decimal) -> Decimal | None:
    """Compute the discounted combo price, protecting the 15% margin over cost.

    Applies ``COMBO_DISCOUNT_RATE``. Returns ``None`` when even the discounted
    price would breach the margin floor, signalling the combo must be skipped
    rather than sold under margin (Rule 1).
    """
    discounted = quantize_money(precio_original * (Decimal("1") - COMBO_DISCOUNT_RATE))
    floor_price = _margin_floor(precio_original)
    if discounted < floor_price:
        # Selling at the discount would breach the minimum margin: skip it.
        return None
    return discounted


class CopilotService:
    """Analyse catalog and sales data to generate promotions and daily insights.

    Injected with a :class:`CatalogService` and a :class:`ReportService` so it
    stays pure (no direct I/O) and is trivially testable with the in-memory
    fake repository.
    """

    def __init__(
        self,
        catalog: CatalogService,
        report: ReportService,
    ) -> None:
        self._catalog = catalog
        self._report = report

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generar_promociones(
        self, limite_combos: int = DEFAULT_COMBO_LIMIT
    ) -> list[PromoCombo]:
        """Return up to ``limite_combos`` dynamic combo suggestions.

        Algorithm:
        1. List all products from the catalog.
        2. Keep only those with ``stock > OVERSTOCK_THRESHOLD`` (overstock rule).
        3. Sort candidates by stock descending (highest inventory first, Rule 2),
           breaking ties by price descending so the pairing stays deterministic.
        4. Pair them: highest-stock with lowest-stock candidate, walking inward.
        5. For each pair compute ``precio_combo`` protecting the 15% margin;
           skip any pair whose discount would breach the margin or yield no saving.
        6. Build a ``PromoCombo`` with a ready-to-say ``pitch_cajero``.

        Args:
            limite_combos: Maximum number of combos to return (1..MAX_COMBO_LIMIT).

        Raises:
            ValidationError: if ``limite_combos`` is outside ``[1, MAX_COMBO_LIMIT]``.

        Returns an empty list when fewer than 2 eligible overstock products exist.
        """

        if isinstance(limite_combos, bool) or not isinstance(limite_combos, int):
            raise ValidationError("limite_combos", "El límite debe ser un entero.")
        if not (1 <= limite_combos <= MAX_COMBO_LIMIT):
            raise ValidationError(
                "limite_combos",
                f"El límite debe estar entre 1 y {MAX_COMBO_LIMIT}.",
                {"limite_combos": limite_combos},
            )

        products: list[Product] = self._catalog.list_products()
        # Rule 2: prioritise the highest inventory. Tie-break by price so the
        # ordering is deterministic and the expensive item anchors the combo.
        candidates: list[Product] = sorted(
            [p for p in products if p.stock > OVERSTOCK_THRESHOLD],
            key=lambda p: (p.stock, p.price),
            reverse=True,
        )

        combos: list[PromoCombo] = []
        lo: int = len(candidates) - 1
        hi: int = 0

        while hi < lo and len(combos) < limite_combos:
            a = candidates[hi]
            b = candidates[lo]
            hi += 1
            lo -= 1

            precio_original = quantize_money(a.price + b.price)
            precio_combo = _combo_price(precio_original)
            if precio_combo is None:
                # Would breach the minimum margin over cost (Rule 1): skip.
                continue

            ahorro = quantize_money(precio_original - precio_combo)
            if ahorro <= Decimal("0.00"):
                # No real saving to offer; a "$0.00 off" pitch is counter-productive.
                continue

            combos.append(
                PromoCombo(
                    nombre=f"Combo {a.name} + {b.name}",
                    skus=[a.sku, b.sku],
                    precio_original=precio_original,
                    precio_combo=precio_combo,
                    ahorro=ahorro,
                    pitch_cajero=_build_pitch(a.name, b.name, ahorro),
                )
            )

        return combos

    def analisis_gerencial(self, fecha: str | None = None) -> ResumenGerencial:
        """Return the managerial diagnostic for ``fecha`` (defaults to today UTC).

        Combines the daily sales report with a catalog scan to detect critical
        stock levels and produce a plain-Spanish strategic recommendation.

        Raises:
            app.services.report.InvalidDate: if ``fecha`` is malformed or future.
        """

        report = self._report.daily_report(fecha)
        products: list[Product] = self._catalog.list_products()

        criticos: list[str] = [
            p.sku for p in products if p.stock < CRITICAL_STOCK_THRESHOLD
        ]

        recomendacion = self._build_recomendacion(
            total_ventas=report.total,
            sales_count=report.sales_count,
            criticos=criticos,
            products=products,
        )

        return ResumenGerencial(
            fecha=report.date,
            total_ventas=report.total,
            productos_criticos=criticos,
            recomendacion_estrategica=recomendacion,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_recomendacion(
        self,
        total_ventas: Decimal,
        sales_count: int,
        criticos: list[str],
        products: list[Product],
    ) -> str:
        """Generate a plain-Spanish strategic recommendation for the owner."""

        parts: list[str] = []

        if sales_count == 0:
            parts.append("Hoy no se registraron ventas.")
        else:
            # sales_count > 0 here, so the division is always safe.
            ticket_promedio = quantize_money(total_ventas / Decimal(sales_count))
            parts.append(
                f"Hoy se realizaron {sales_count} venta(s) por un total de "
                f"${total_ventas} (ticket promedio: ${ticket_promedio})."
            )

        if criticos:
            skus_str = ", ".join(criticos)
            parts.append(
                f"⚠️ Productos con stock crítico (menos de {CRITICAL_STOCK_THRESHOLD} unidades): "
                f"{skus_str}. Se recomienda reabastecer antes de abrir mañana."
            )
        else:
            parts.append("✅ Todos los productos tienen stock suficiente.")

        # Rule 2: highlight the highest-inventory products first.
        overstock_candidates = sorted(
            [p for p in products if p.stock > OVERSTOCK_THRESHOLD],
            key=lambda p: p.stock,
            reverse=True,
        )
        if overstock_candidates:
            nombres = ", ".join(p.name for p in overstock_candidates[:3])
            parts.append(
                f"💡 Productos con alto inventario listos para combos: {nombres}. "
                "Activa las promociones del copiloto para moverlos hoy."
            )

        return " ".join(parts)
