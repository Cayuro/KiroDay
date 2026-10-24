"""In-memory transactional fake repository (task 4.2).

Faithfully reproduces DynamoDB ``TransactWriteItems`` semantics so the business
logic — especially the atomic stock discount (Requirement 3) — can be verified
without AWS:

* **All-or-nothing**: every action's condition is evaluated against a snapshot
  of the store first; writes are applied only if *all* conditions pass. If any
  condition fails, nothing is written and the whole batch is rejected.
* **Per-action reasons**: on rejection the raised
  :class:`app.repository.base.TransactionCancelled` carries one
  :class:`CancellationReason` per action, so services can map
  ``ConditionalCheckFailed`` entries back to the offending SKUs.
* **Injectable non-condition failure**: :attr:`InMemoryPosRepository.fail_next_transaction`
  forces the next ``commit_sale_transaction`` to be cancelled as a
  non-condition failure (e.g. a conflict/throttle), exercising Requirement 3.5.

Items are stored keyed by ``(PK, SK)``; stored values use ``Decimal`` for
numeric attributes exactly as the DynamoDB resource interface would.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from app.repository.base import (
    CancellationReason,
    DuplicateItem,
    ItemNotFound,
    MAX_TRANSACTION_ACTIONS,
    PutAction,
    StockDecrementAction,
    TransactionAction,
    TransactionCancelled,
    TransactionValidationError,
)
from app.repository.keys import (
    ENTITY,
    ENTITY_PRODUCT,
    PK,
    SK,
    from_number,
)

_NON_CONDITION_CODE = "TransactionConflict"


class InMemoryPosRepository:
    """A dict-backed :class:`app.repository.base.PosRepository` implementation."""

    def __init__(self) -> None:
        # Keyed by (PK, SK) -> item dict. Stored items are deep-copied on the
        # way in and out so callers can never mutate internal state by alias.
        self._items: dict[tuple[str, str], dict[str, Any]] = {}
        # When set, the next commit_sale_transaction is cancelled as a
        # non-condition failure regardless of conditions (Requirement 3.5).
        self.fail_next_transaction: bool = False

    # --- product operations ------------------------------------------------

    def get_product(self, sku: str) -> dict[str, Any] | None:
        from app.repository.keys import product_pk

        pk = product_pk(sku)
        item = self._items.get((pk, pk))
        return copy.deepcopy(item) if item is not None else None

    def put_product(self, item: dict[str, Any]) -> None:
        key = (item[PK], item[SK])
        if key in self._items:
            raise DuplicateItem(f"product already exists: {item[PK]}")
        self._items[key] = copy.deepcopy(item)

    def list_products(self) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(item)
            for item in self._items.values()
            if item.get(ENTITY) == ENTITY_PRODUCT
        ]

    def update_product(self, item: dict[str, Any]) -> None:
        key = (item[PK], item[SK])
        if key not in self._items:
            raise ItemNotFound(f"product does not exist: {item[PK]}")
        self._items[key] = copy.deepcopy(item)

    # --- sale queries ------------------------------------------------------

    def query_sales_by_date(self, date: str) -> list[dict[str, Any]]:
        from app.repository.keys import sale_pk

        pk = sale_pk(date)
        return [
            copy.deepcopy(item)
            for (item_pk, _sk), item in self._items.items()
            if item_pk == pk
        ]

    # --- transactional commit ---------------------------------------------

    def commit_sale_transaction(self, actions: list[TransactionAction]) -> None:
        """Apply ``actions`` atomically, mirroring ``TransactWriteItems``.

        Phase 1 evaluates every action's condition against the current store
        without mutating anything and records a reason per action. Phase 2
        applies all writes only if no reason failed; otherwise the batch is
        rejected with :class:`TransactionCancelled` and the store is untouched.

        A batch with more than :data:`MAX_TRANSACTION_ACTIONS` actions is
        rejected up front with :class:`TransactionValidationError`, mirroring
        the client-side ``ValidationException`` DynamoDB raises for an oversized
        ``TransactWriteItems`` request (nothing is written).
        """

        # Mirror DynamoDB's 100-action limit: an oversized batch is a request
        # validation error, evaluated by neither backend (nothing is written).
        if len(actions) > MAX_TRANSACTION_ACTIONS:
            raise TransactionValidationError(
                f"TransactWriteItems supports at most {MAX_TRANSACTION_ACTIONS} "
                f"actions, got {len(actions)}."
            )

        # Injected non-condition failure: cancel the whole batch, write nothing.
        if self.fail_next_transaction:
            self.fail_next_transaction = False
            reasons = [self._non_condition_reason(action) for action in actions]
            raise TransactionCancelled(reasons)

        reasons: list[CancellationReason] = []
        any_failed = False
        for action in actions:
            reason = self._evaluate(action)
            reasons.append(reason)
            if reason.code != "None":
                any_failed = True

        if any_failed:
            # All-or-nothing: reject the batch without modifying any item.
            raise TransactionCancelled(reasons)

        # All conditions passed — apply every write atomically.
        for action in actions:
            self._apply(action)

    # --- helpers -----------------------------------------------------------

    def _evaluate(self, action: TransactionAction) -> CancellationReason:
        """Return the cancellation reason for ``action`` without mutating state."""

        if isinstance(action, PutAction):
            attr = action.condition_attribute_not_exists
            if attr is not None:
                key = (action.item[PK], action.item[SK])
                existing = self._items.get(key)
                if existing is not None and attr in existing:
                    return CancellationReason(TransactionCancelled.CONDITIONAL_CHECK_FAILED)
            return CancellationReason("None")

        if isinstance(action, StockDecrementAction):
            key = (action.key[PK], action.key[SK])
            existing = self._items.get(key)
            # Condition: attribute_exists(PK) AND stock >= :qty.
            if existing is None:
                return CancellationReason(
                    TransactionCancelled.CONDITIONAL_CHECK_FAILED, sku=action.sku
                )
            current = from_number(existing["stock"])
            if current < Decimal(action.qty):
                return CancellationReason(
                    TransactionCancelled.CONDITIONAL_CHECK_FAILED, sku=action.sku
                )
            return CancellationReason("None", sku=action.sku)

        raise TypeError(f"unsupported action type: {type(action).__name__}")

    def _apply(self, action: TransactionAction) -> None:
        """Apply ``action``'s write. Called only after all conditions passed."""

        if isinstance(action, PutAction):
            key = (action.item[PK], action.item[SK])
            self._items[key] = copy.deepcopy(action.item)
            return

        if isinstance(action, StockDecrementAction):
            key = (action.key[PK], action.key[SK])
            item = self._items[key]
            current = from_number(item["stock"])
            item["stock"] = current - Decimal(action.qty)
            return

        raise TypeError(f"unsupported action type: {type(action).__name__}")

    @staticmethod
    def _non_condition_reason(action: TransactionAction) -> CancellationReason:
        sku = action.sku if isinstance(action, StockDecrementAction) else None
        return CancellationReason(_NON_CONDITION_CODE, sku=sku)
