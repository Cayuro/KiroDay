"""Repository protocol and transactional action types (task 4.1).

Defines the :class:`PosRepository` protocol that both the in-memory fake
(:mod:`app.repository.memory`) and the DynamoDB-backed repository
(:mod:`app.repository.dynamodb`) implement, plus the storage-agnostic action
types used to describe a ``TransactWriteItems`` batch.

The action model is deliberately small and declarative so the fake can
reproduce DynamoDB semantics exactly and the real repository can translate each
action into the boto3 payload without the services knowing which backend is in
use. Services build actions (via ``Inventory_Service`` in a later wave) and hand
them to :meth:`PosRepository.commit_sale_transaction`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class PutAction:
    """Create an item, guarded by ``attribute_not_exists`` on a key attribute.

    Attributes:
        item: The full item to write (must contain ``PK`` and ``SK``).
        condition_attribute_not_exists: Attribute name whose absence is required
            for the put to succeed (e.g. ``"SK"`` to reject a duplicate sale).
    """

    item: dict[str, Any]
    condition_attribute_not_exists: str | None = None


@dataclass(frozen=True)
class StockDecrementAction:
    """Decrement a product's ``stock`` by ``qty`` if enough stock exists.

    Reproduces the guarded update from ``design.md``:
    ``SET stock = stock - :qty`` with condition
    ``attribute_exists(PK) AND stock >= :qty``.

    Attributes:
        key: Primary key of the product item (``{"PK", "SK"}``).
        sku: SKU this action targets, surfaced in cancellation reasons so the
            service can report offending products.
        qty: Quantity to subtract (positive integer).
    """

    key: dict[str, str]
    sku: str
    qty: int


# A transaction is an ordered list of heterogeneous actions.
TransactionAction = PutAction | StockDecrementAction

# DynamoDB rejects a TransactWriteItems request carrying more than 100 actions
# with a client-side ValidationException (the transaction is never evaluated).
# Both repository backends enforce this so callers see identical behaviour.
MAX_TRANSACTION_ACTIONS = 100


class TransactionValidationError(Exception):
    """Raised when a transaction is malformed before it can be evaluated.

    Mirrors a DynamoDB ``ValidationException`` from ``TransactWriteItems`` — for
    example, a batch with more than :data:`MAX_TRANSACTION_ACTIONS` actions.
    This is a request-shape error (the transaction never runs), distinct from
    :class:`TransactionCancelled`, which reports per-action cancellation reasons
    for a transaction that was evaluated and rejected.
    """


@dataclass(frozen=True)
class CancellationReason:
    """Why a single action in a transaction was cancelled.

    Mirrors a DynamoDB ``CancellationReasons`` entry. ``code`` is
    ``"ConditionalCheckFailed"`` for a failed condition (e.g. insufficient
    stock), ``"None"`` for an action that would have succeeded, or another code
    (e.g. ``"TransactionConflict"``) for a non-condition failure.

    ``sku`` is populated for stock-decrement actions so services can map a
    conditional failure back to the offending product.
    """

    code: str
    sku: str | None = None


class TransactionCancelled(Exception):
    """Raised when a ``commit_sale_transaction`` batch is rejected as a whole.

    Carries the per-action :class:`CancellationReason` list so callers can tell
    insufficient-stock failures (and which SKUs) apart from other transactional
    failures (conflict, throttling, injected non-condition failure).
    """

    CONDITIONAL_CHECK_FAILED = "ConditionalCheckFailed"

    def __init__(self, reasons: list[CancellationReason]) -> None:
        self.reasons = reasons
        super().__init__(self._describe())

    def _describe(self) -> str:
        parts = [r.code if r.sku is None else f"{r.code}({r.sku})" for r in self.reasons]
        return "transaction cancelled: " + ", ".join(parts)

    def conditional_failure_skus(self) -> list[str]:
        """Return SKUs whose stock condition failed (offending products)."""

        return [
            r.sku
            for r in self.reasons
            if r.code == self.CONDITIONAL_CHECK_FAILED and r.sku is not None
        ]

    def has_non_condition_failure(self) -> bool:
        """True if any reason is a failure other than a conditional check.

        Used to distinguish insufficient-stock (``INSUFFICIENT_STOCK``) from
        other transactional failures (``TRANSACTION_FAILED``) per Requirement 3.5.
        """

        return any(
            r.code not in (self.CONDITIONAL_CHECK_FAILED, "None")
            for r in self.reasons
        )


@runtime_checkable
class PosRepository(Protocol):
    """Persistence contract for the POS backend (single DynamoDB table).

    Implemented by the in-memory fake (tests) and the boto3/DynamoDB repository
    (production). All money is handled as :class:`decimal.Decimal`.
    """

    def get_product(self, sku: str) -> dict[str, Any] | None:
        """Return the stored product item for ``sku`` or ``None`` if absent."""
        ...

    def put_product(self, item: dict[str, Any]) -> None:
        """Create a product item, rejecting a duplicate SKU.

        Guarded by ``attribute_not_exists(PK)``.

        Raises:
            DuplicateItem: if a product with the same PK already exists.
        """
        ...

    def list_products(self) -> list[dict[str, Any]]:
        """Return all product items (``entity == "PRODUCT"``); ``[]`` if none."""
        ...

    def update_product(self, item: dict[str, Any]) -> None:
        """Overwrite an existing product item, requiring it to exist.

        Guarded by ``attribute_exists(PK)``.

        Raises:
            ItemNotFound: if no product with the given PK exists.
        """
        ...

    def commit_sale_transaction(self, actions: list[TransactionAction]) -> None:
        """Apply a sale transaction atomically (``TransactWriteItems``).

        Evaluates every action's condition first and applies all writes only if
        all conditions pass; otherwise nothing is written.

        Raises:
            TransactionCancelled: with per-action reasons when the batch is
                rejected (insufficient stock and/or a non-condition failure).
        """
        ...

    def query_sales_by_date(self, date: str) -> list[dict[str, Any]]:
        """Return all sale items for the calendar ``date`` (``SALE#<date>``)."""
        ...


class DuplicateItem(Exception):
    """Raised by ``put_product`` when the item's PK already exists."""


class ItemNotFound(Exception):
    """Raised by ``update_product`` when the target item does not exist."""
