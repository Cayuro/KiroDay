"""Sales_Service: register a sale and coordinate the atomic discount.

Requirement 2 (validation, total, timestamp, id) and the orchestration half of
Requirement 3 (atomic commit via :class:`app.services.inventory.InventoryService`),
tasks 6.3.

Flow (``design.md`` Concurrency and Atomicity Strategy):

1. Validate the request shape (payment method, items present, quantities) and
   look up every referenced product. An unknown SKU, empty items, invalid
   quantity, or invalid payment method is rejected **before any write**, so a
   rejected sale persists nothing (Requirements 2.5-2.8).
2. Build a :class:`app.models.sale.Sale` with the looked-up prices, which
   computes subtotals and the total, and assigns a unique ``sale_id`` and a UTC
   registration timestamp (Requirements 2.1-2.4).
3. Commit the sale and all stock decrements atomically via the inventory
   service; map insufficient-stock / transaction failures to their errors
   (Requirements 3.1, 3.3, 3.5, 3.7).

The service holds no stock logic of its own; the atomic transaction lives in
:class:`InventoryService`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence
from uuid import uuid4

from app.errors import ErrorCode, PosError, ValidationError
from app.models.product import Product
from app.models.sale import PAYMENT_METHODS, Sale
from app.repository.base import PosRepository
from app.repository.keys import from_number, stock_to_int
from app.services.inventory import InventoryService


class UnknownSku(PosError):
    """Raised when a sale references a SKU absent from the catalog (Requirement 2.5)."""

    code = ErrorCode.UNKNOWN_SKU

    def __init__(self, sku: str) -> None:
        super().__init__(
            "El SKU no existe en el catálogo.",
            {"sku": sku},
        )
        self.sku = sku


def _price_from_item(item: Mapping[str, object]) -> Decimal:
    return from_number(item["price"])


class SalesService:
    """Register sales: validate, price, assign id/timestamp, commit atomically."""

    def __init__(
        self,
        repository: PosRepository,
        inventory: InventoryService | None = None,
    ) -> None:
        self._repo = repository
        self._inventory = inventory or InventoryService(repository)

    def register_sale(
        self,
        raw_items: Sequence[Mapping[str, object]],
        payment_method: str,
    ) -> Sale:
        """Register a sale and return the persisted :class:`Sale`.

        Raises:
            ValidationError: empty/oversized items, invalid quantity, or invalid
                payment method (nothing persisted).
            UnknownSku: if any item references a SKU absent from the catalog
                (nothing persisted).
            InsufficientStock: if any product lacks enough stock; reports the
                offending SKUs and persists nothing.
            TransactionFailed: on a non-stock transactional failure; persists
                nothing.
        """

        # --- shape validation before any lookup/write -------------------------
        # Payment method and item-list bounds are validated up front so an
        # obviously invalid request never hits storage. Full per-item validation
        # (quantity bounds, totals) is delegated to Sale.create below.
        if payment_method not in PAYMENT_METHODS:
            raise ValidationError(
                "payment_method",
                'El método de pago debe ser "efectivo" o "tarjeta".',
                {"payment_method": payment_method},
            )
        if not isinstance(raw_items, (list, tuple)):
            raise ValidationError("items", "Los ítems deben ser una lista.")
        if not raw_items:
            raise ValidationError(
                "items",
                "La venta debe tener al menos un ítem.",
                {"count": 0},
            )

        # --- look up referenced products (prices) -----------------------------
        # Unknown SKUs are rejected here, before any write. Quantity validity is
        # not yet checked; Sale.create enforces it (also before any write).
        prices: dict[str, Decimal] = {}
        products: dict[str, Product] = {}
        for raw in raw_items:
            sku = raw.get("sku")
            if not isinstance(sku, str) or not sku:
                raise ValidationError("sku", "Cada ítem debe referenciar un SKU.")
            if sku in prices:
                continue  # already looked up (repeated SKU across lines)
            item = self._repo.get_product(sku)
            if item is None:
                raise UnknownSku(sku)
            prices[sku] = _price_from_item(item)
            products[sku] = Product.create(
                sku=sku,
                name=item["name"],
                price=prices[sku],
                stock=stock_to_int(item["stock"]),
            )

        # --- build the sale (validates quantities, computes total/id/ts) ------
        sale = Sale.create(
            list(raw_items),
            payment_method,
            prices,
            timestamp=datetime.now(timezone.utc),
            sale_id=str(uuid4()),
        )

        # --- atomic commit (stock discount + sale put) ------------------------
        self._inventory.commit_sale(sale, products)
        return sale
