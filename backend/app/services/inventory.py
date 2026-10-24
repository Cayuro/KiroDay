"""Inventory_Service: the atomic stock discount (Requirement 3, tasks 6.1-6.2).

This is the core of the business logic. A sale and the stock reduction of all
its items must commit together or not at all, even under concurrency. The
service does not own storage; it builds a storage-agnostic list of transaction
actions (:mod:`app.repository.base`) and hands them to the repository's
``commit_sale_transaction`` (a single DynamoDB ``TransactWriteItems`` in
production, faithfully reproduced by the in-memory fake in tests).

The transaction contains, per ``design.md``:

* one :class:`StockDecrementAction` per distinct product, decrementing ``stock``
  by the ordered quantity, guarded by ``attribute_exists(PK) AND stock >= :qty``;
* one :class:`PutAction` creating the sale item, guarded by
  ``attribute_not_exists(SK)`` so a replayed sale id can never double-write.

On rejection the service distinguishes the two failure classes the API maps to
different HTTP statuses:

* a stock condition failure -> :class:`InsufficientStock` listing exactly the
  offending SKUs (Requirement 3.3);
* any other transactional failure (conflict, throttling, injected non-condition
  failure) -> :class:`TransactionFailed` (Requirement 3.5).

In every rejection path nothing is written, so product stock is preserved
exactly (Requirements 3.4, 3.7).
"""

from __future__ import annotations

from typing import Mapping

from app.errors import ErrorCode, PosError
from app.models.product import Product
from app.models.sale import Sale
from app.repository.base import (
    PosRepository,
    PutAction,
    StockDecrementAction,
    TransactionAction,
    TransactionCancelled,
)
from app.repository.keys import (
    ENTITY,
    ENTITY_SALE,
    PK,
    SK,
    product_key,
    sale_date,
    sale_pk,
    sale_sk,
)


class InsufficientStock(PosError):
    """Raised when one or more products have less stock than requested.

    Carries the exact set of offending SKUs (Requirement 3.3) in both an
    attribute and the error ``details`` so the API can return them.
    """

    code = ErrorCode.INSUFFICIENT_STOCK

    def __init__(self, skus: list[str]) -> None:
        super().__init__(
            "Stock insuficiente para completar la venta.",
            {"skus": list(skus)},
        )
        self.skus = list(skus)


class TransactionFailed(PosError):
    """Raised when the sale transaction fails for a non-stock reason.

    Covers conflicts, throttling, and the injected non-condition failure. The
    transaction never commits, so stock and sales remain unchanged
    (Requirement 3.5).
    """

    code = ErrorCode.TRANSACTION_FAILED

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "No se pudo completar el registro de la venta. Intenta de nuevo.",
        )


class SaleAlreadyExists(PosError):
    """Raised when the sale Put's ``attribute_not_exists(SK)`` guard fires.

    This means a sale with the same id/key already existed — a duplicate sale
    id. With server-generated UUIDs this should never happen; if it does it
    signals an internal problem (e.g. an id-generation bug), not a transient
    condition the client should retry. It therefore maps to ``INTERNAL_ERROR``
    (500), unlike :class:`TransactionFailed` (503, "retry"). Nothing is written,
    so stock and sales remain unchanged.
    """

    code = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "El registro de la venta no se completó (identificador duplicado).",
        )


def _sale_item(sale: Sale) -> dict:
    """Build the single-table item for a sale (self-describing for the receipt)."""

    date = sale_date(sale.timestamp)
    ts = sale.timestamp.isoformat()
    return {
        PK: sale_pk(date),
        SK: sale_sk(ts, sale.sale_id),
        ENTITY: ENTITY_SALE,
        "sale_id": sale.sale_id,
        "total": sale.total,
        "payment_method": sale.payment_method,
        "timestamp": ts,
        "items": [item.to_dict() for item in sale.items],
    }


def _ordered_quantities(sale: Sale) -> dict[str, int]:
    """Sum quantities per distinct SKU (a SKU may appear in several lines)."""

    quantities: dict[str, int] = {}
    for item in sale.items:
        quantities[item.sku] = quantities.get(item.sku, 0) + item.qty
    return quantities


class InventoryService:
    """Build and commit the atomic stock-discount transaction for a sale."""

    def __init__(self, repository: PosRepository) -> None:
        self._repo = repository

    def build_sale_transaction(
        self,
        sale: Sale,
        products: Mapping[str, Product],
    ) -> list[TransactionAction]:
        """Return the ``TransactWriteItems`` actions for ``sale``.

        One guarded stock-decrement per distinct product (quantities summed
        across lines sharing a SKU) plus one guarded put for the sale item.
        ``products`` must contain every referenced SKU (the caller validates
        this first); it is used only to confirm coverage here.
        """

        actions: list[TransactionAction] = []
        for sku, qty in _ordered_quantities(sale).items():
            if sku not in products:
                # Defensive: the caller (Sales_Service) rejects unknown SKUs
                # before building the transaction. Guard anyway so a bad caller
                # fails loudly instead of silently skipping a decrement.
                raise KeyError(f"missing product for sku in transaction: {sku}")
            actions.append(
                StockDecrementAction(key=product_key(sku), sku=sku, qty=qty)
            )

        actions.append(
            PutAction(
                item=_sale_item(sale),
                condition_attribute_not_exists="SK",
            )
        )
        return actions

    def commit_sale(self, sale: Sale, products: Mapping[str, Product]) -> None:
        """Commit the sale atomically, mapping cancellations to service errors.

        Raises:
            InsufficientStock: if any product's ``stock >= qty`` condition fails;
                the offending SKUs are reported and nothing is written.
            SaleAlreadyExists: if the sale Put's ``attribute_not_exists(SK)``
                guard fires (a duplicate sale id); maps to ``INTERNAL_ERROR``.
            TransactionFailed: for any other transactional failure (conflict,
                throttling, injected non-condition failure); nothing is written.
        """

        actions = self.build_sale_transaction(sale, products)
        try:
            self._repo.commit_sale_transaction(actions)
        except TransactionCancelled as exc:
            # A non-condition failure (conflict/throttle/injected) takes
            # precedence: it signals the transaction could not be evaluated
            # normally, which Requirement 3.5 maps to TRANSACTION_FAILED.
            if exc.has_non_condition_failure():
                raise TransactionFailed() from exc
            offending = exc.conditional_failure_skus()
            if offending:
                raise InsufficientStock(offending) from exc
            # A conditional failure with no offending SKU means the sale Put's
            # attribute_not_exists(SK) guard fired (a duplicate sale id). This
            # is not a stock problem and not a transient failure to retry; with
            # server-generated UUIDs it indicates an internal bug, so surface it
            # as an internal error (500). Nothing partial is written.
            raise SaleAlreadyExists() from exc
