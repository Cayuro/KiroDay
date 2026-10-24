"""Sale domain model, validation, and total calculation (Requirement 2).

A :class:`Sale` groups ``ITEMS_MIN``..``ITEMS_MAX`` :class:`SaleItem` lines over
at most ``DISTINCT_SKU_MAX`` distinct SKUs (lines may repeat a SKU), a payment
method, a computed total, a registration timestamp, and a unique sale id.
Totals are computed with :class:`decimal.Decimal`: each subtotal is
``round(unit_price * qty, 2)`` and the total is the sum of subtotals, within
``[0.01, 999999999.99]``.

The distinct-SKU cap exists because committing a sale is a single DynamoDB
``TransactWriteItems`` call, which accepts at most 100 actions. A sale builds
one ``StockDecrementAction`` per distinct SKU (lines sharing a SKU are summed)
plus one ``PutAction`` for the sale item, so distinct SKUs must stay ``<= 99``
to keep the whole transaction ``<= 100`` actions and avoid a DynamoDB
``ValidationException``.

Validation raises :class:`app.errors.ValidationError` naming the offending
field. The unit price for a line comes from the referenced product; it is
supplied to :meth:`Sale.create` as a ``prices`` mapping so this model stays pure
(no I/O / catalog lookups).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping
from uuid import uuid4

from app.errors import ValidationError
from app.money import MAX_PRICE, MIN_PRICE, quantize_money, to_money

# Bounds from design.md / Requirement 2.
ITEMS_MIN = 1
# Bounds from design.md / Requirement 2.
ITEMS_MIN = 1
# A sale commits as one DynamoDB TransactWriteItems (<= 100 actions): one
# StockDecrementAction per DISTINCT SKU + one PutAction for the sale. Lines
# sharing a SKU are summed into a single decrement, so the binding business
# limit is the number of distinct SKUs, which must be <= 99 to keep the whole
# transaction <= 100 actions. ITEMS_MAX only caps the number of request lines
# to reject oversized payloads early; a sale may repeat a SKU across lines, so
# ITEMS_MAX is allowed to exceed DISTINCT_SKU_MAX. The distinct-SKU check in
# Sale.create is the authoritative guard, enforced before the transaction.
DISTINCT_SKU_MAX = 99
ITEMS_MAX = 198
QTY_MIN = 1
QTY_MAX = 9_999

PAYMENT_METHODS = frozenset({"efectivo", "tarjeta"})


def _validate_qty(qty: int, sku: str) -> int:
    # bool is a subclass of int; reject it explicitly.
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise ValidationError(
            "qty",
            "La cantidad debe ser un número entero.",
            {"sku": sku},
        )
    if not (QTY_MIN <= qty <= QTY_MAX):
        raise ValidationError(
            "qty",
            f"La cantidad debe estar entre {QTY_MIN} y {QTY_MAX}.",
            {"sku": sku, "qty": qty},
        )
    return qty


def _validate_payment_method(payment_method: str) -> str:
    if payment_method not in PAYMENT_METHODS:
        raise ValidationError(
            "payment_method",
            'El método de pago debe ser "efectivo" o "tarjeta".',
            {"payment_method": payment_method},
        )
    return payment_method


@dataclass(frozen=True)
class SaleItem:
    """A single line of a sale.

    Attributes:
        sku: Product code referenced by this line.
        qty: Quantity sold, integer in ``[1, 9999]``.
        unit_price: Unit price captured at sale time (``Decimal``, 2 decimals).
        subtotal: ``round(unit_price * qty, 2)`` (``Decimal``, 2 decimals).
    """

    sku: str
    qty: int
    unit_price: Decimal
    subtotal: Decimal

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "qty": self.qty,
            "unit_price": str(self.unit_price),
            "subtotal": str(self.subtotal),
        }


@dataclass(frozen=True)
class Sale:
    """A registered sale.

    Attributes:
        items: Validated sale lines (ITEMS_MIN..ITEMS_MAX, at most DISTINCT_SKU_MAX distinct SKUs).
        payment_method: One of ``{"efectivo", "tarjeta"}``.
        total: Sum of subtotals (``Decimal``, 2 decimals) in ``[0.01, ...]``.
        timestamp: UTC registration time.
        sale_id: Unique identifier (UUID string).
    """

    items: tuple[SaleItem, ...]
    payment_method: str
    total: Decimal
    timestamp: datetime
    sale_id: str = field(default_factory=lambda: str(uuid4()))

    @staticmethod
    def compute_subtotal(unit_price: Decimal, qty: int) -> Decimal:
        """Return ``round(unit_price * qty, 2)`` as a two-decimal ``Decimal``."""

        return quantize_money(unit_price * qty)

    @classmethod
    def create(
        cls,
        raw_items: list[Mapping[str, object]],
        payment_method: str,
        prices: Mapping[str, Decimal],
        *,
        timestamp: datetime | None = None,
        sale_id: str | None = None,
    ) -> "Sale":
        """Validate a sale request and compute its totals.

        Args:
            raw_items: List of ``{"sku", "qty"}`` mappings (ITEMS_MIN..ITEMS_MAX
                lines, referencing at most ``DISTINCT_SKU_MAX`` distinct SKUs).
            payment_method: ``"efectivo"`` or ``"tarjeta"``.
            prices: Mapping of SKU -> unit price (``Decimal``) for referenced
                products. Every item's SKU must be present here; a missing SKU
                raises a validation error naming the ``sku`` field.
            timestamp: Registration time; defaults to ``datetime.now(UTC)``.
            sale_id: Unique id; defaults to a new UUID.

        Raises:
            ValidationError: naming the offending field for empty/oversized item
                lists, too many distinct SKUs, invalid quantities, unknown SKUs,
                invalid payment method, or a total outside
                ``[0.01, 999999999.99]``.
        """

        _validate_payment_method(payment_method)

        if not isinstance(raw_items, (list, tuple)):
            raise ValidationError("items", "Los ítems deben ser una lista.")
        if not (ITEMS_MIN <= len(raw_items) <= ITEMS_MAX):
            raise ValidationError(
                "items",
                f"La venta debe tener entre {ITEMS_MIN} y {ITEMS_MAX} ítems.",
                {"count": len(raw_items)},
            )

        items: list[SaleItem] = []
        total = Decimal("0")
        distinct_skus: set[str] = set()
        for raw in raw_items:
            sku = raw.get("sku")
            if not isinstance(sku, str) or not sku:
                raise ValidationError("sku", "Cada ítem debe referenciar un SKU.")
            qty = _validate_qty(raw.get("qty"), sku)
            if sku not in prices:
                raise ValidationError(
                    "sku",
                    "El SKU no existe en el catálogo.",
                    {"sku": sku},
                )
            distinct_skus.add(sku)
            # A sale commits as one TransactWriteItems (one decrement per
            # distinct SKU + one Put); reject before building it if the distinct
            # SKUs would push the transaction past DynamoDB's 100-action limit.
            if len(distinct_skus) > DISTINCT_SKU_MAX:
                raise ValidationError(
                    "items",
                    f"La venta no puede tener más de {DISTINCT_SKU_MAX} productos distintos.",
                    {"distinct_skus": len(distinct_skus)},
                )
            unit_price = to_money(prices[sku])
            subtotal = cls.compute_subtotal(unit_price, qty)
            total += subtotal
            items.append(
                SaleItem(sku=sku, qty=qty, unit_price=unit_price, subtotal=subtotal)
            )

        total = quantize_money(total)
        if not (MIN_PRICE <= total <= MAX_PRICE):
            raise ValidationError(
                "total",
                f"El total debe estar entre {MIN_PRICE} y {MAX_PRICE}.",
                {"total": str(total)},
            )

        return cls(
            items=tuple(items),
            payment_method=payment_method,
            total=total,
            timestamp=timestamp or datetime.now(timezone.utc),
            sale_id=sale_id or str(uuid4()),
        )

    def to_dict(self) -> dict:
        return {
            "sale_id": self.sale_id,
            "total": str(self.total),
            "payment_method": self.payment_method,
            "timestamp": self.timestamp.isoformat(),
            "items": [item.to_dict() for item in self.items],
        }
