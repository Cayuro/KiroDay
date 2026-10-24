"""DynamoDB-backed repository over boto3 (task 4.4).

Implements :class:`app.repository.base.PosRepository` against a single
DynamoDB table using the boto3 *resource* interface (which represents ``Number``
attributes as :class:`decimal.Decimal`, matching how the rest of the backend
handles money).

Configuration (table name, region) comes from environment variables so no
secrets live in code or the repo:

* ``POS_TABLE_NAME`` — the single-table name (defaults to ``pos``).
* ``POS_AWS_REGION`` / ``AWS_REGION`` — the AWS region (optional; boto3 resolves
  it from the standard provider chain when unset).

Access patterns map to ``GetItem``, ``PutItem``, ``Scan`` (filtered by
``entity == "PRODUCT"``), ``UpdateItem``, ``TransactWriteItems``, and ``Query``
on ``PK = SALE#<date>``, exactly as in ``design.md``.

No live AWS connection is required to import this module; the boto3 client is
created lazily on first use.
"""

from __future__ import annotations

import os
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
    product_key,
    product_pk,
    sale_pk,
)

TABLE_NAME_ENV = "POS_TABLE_NAME"
REGION_ENV = "POS_AWS_REGION"
DEFAULT_TABLE_NAME = "pos"

# DynamoDB cancellation reason codes we care about.
_CONDITIONAL_CHECK_FAILED = "ConditionalCheckFailed"
_NONE = "None"


class DynamoDBPosRepository:
    """A boto3/DynamoDB implementation of :class:`PosRepository`.

    The table name and region are read from environment variables at
    construction (overridable via constructor arguments for testing/wiring).
    The underlying boto3 ``Table`` resource is created lazily so importing and
    constructing the repository never requires AWS credentials.
    """

    def __init__(
        self,
        table_name: str | None = None,
        region_name: str | None = None,
    ) -> None:
        self._table_name = table_name or os.environ.get(
            TABLE_NAME_ENV, DEFAULT_TABLE_NAME
        )
        self._region_name = region_name or os.environ.get(REGION_ENV) or os.environ.get(
            "AWS_REGION"
        )
        self._table = None  # lazily created boto3 Table resource
        self._client = None  # lazily created boto3 DynamoDB client (for transactions)

    # --- lazy boto3 wiring -------------------------------------------------

    def _get_table(self):
        if self._table is None:
            import boto3  # imported lazily so AWS libs aren't needed to import this module

            resource = boto3.resource("dynamodb", region_name=self._region_name)
            self._table = resource.Table(self._table_name)
        return self._table

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("dynamodb", region_name=self._region_name)
        return self._client

    # --- product operations ------------------------------------------------

    def get_product(self, sku: str) -> dict[str, Any] | None:
        response = self._get_table().get_item(Key=product_key(sku))
        return response.get("Item")

    def put_product(self, item: dict[str, Any]) -> None:
        from botocore.exceptions import ClientError

        try:
            self._get_table().put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
        except ClientError as exc:
            if _is_conditional_check_failed(exc):
                raise DuplicateItem(f"product already exists: {item[PK]}") from exc
            raise

    def list_products(self) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Attr

        table = self._get_table()
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"FilterExpression": Attr(ENTITY).eq(ENTITY_PRODUCT)}
        while True:
            response = table.scan(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    def update_product(self, item: dict[str, Any]) -> None:
        from botocore.exceptions import ClientError

        try:
            self._get_table().put_item(
                Item=item,
                ConditionExpression="attribute_exists(PK)",
            )
        except ClientError as exc:
            if _is_conditional_check_failed(exc):
                raise ItemNotFound(f"product does not exist: {item[PK]}") from exc
            raise

    # --- sale queries ------------------------------------------------------

    def query_sales_by_date(self, date: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        table = self._get_table()
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key(PK).eq(sale_pk(date))
        }
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    # --- transactional commit ---------------------------------------------

    def commit_sale_transaction(self, actions: list[TransactionAction]) -> None:
        """Issue a single ``TransactWriteItems`` for ``actions``.

        Uses the low-level client (whose ``TransactWriteItems`` returns
        ``CancellationReasons`` on failure). On
        ``TransactionCanceledException`` the per-action reasons are parsed back
        into :class:`CancellationReason` objects — the same shape the in-memory
        fake raises — so services treat both backends identically.

        A batch exceeding :data:`MAX_TRANSACTION_ACTIONS` is rejected up front
        with :class:`TransactionValidationError` (the same shape the fake
        raises) instead of letting DynamoDB return a ``ValidationException``,
        so both backends fail identically and no AWS call is wasted.
        """

        from botocore.exceptions import ClientError

        if len(actions) > MAX_TRANSACTION_ACTIONS:
            raise TransactionValidationError(
                f"TransactWriteItems supports at most {MAX_TRANSACTION_ACTIONS} "
                f"actions, got {len(actions)}."
            )

        transact_items = [self._to_transact_item(action) for action in actions]
        try:
            self._get_client().transact_write_items(TransactItems=transact_items)
        except ClientError as exc:
            if _is_transaction_canceled(exc):
                reasons = self._parse_cancellation_reasons(exc, actions)
                raise TransactionCancelled(reasons) from exc
            raise

    # --- action translation ------------------------------------------------

    def _to_transact_item(self, action: TransactionAction) -> dict[str, Any]:
        """Translate a storage-agnostic action into a client TransactItem.

        The low-level client expects attribute values in the typed DynamoDB JSON
        shape, so values are serialized with a ``TypeSerializer``.
        """

        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()

        def serialize(mapping: dict[str, Any]) -> dict[str, Any]:
            return {k: serializer.serialize(v) for k, v in mapping.items()}

        if isinstance(action, PutAction):
            put: dict[str, Any] = {
                "TableName": self._table_name,
                "Item": serialize(action.item),
            }
            if action.condition_attribute_not_exists is not None:
                put["ConditionExpression"] = (
                    f"attribute_not_exists({action.condition_attribute_not_exists})"
                )
            return {"Put": put}

        if isinstance(action, StockDecrementAction):
            return {
                "Update": {
                    "TableName": self._table_name,
                    "Key": serialize(action.key),
                    "UpdateExpression": "SET stock = stock - :qty",
                    "ConditionExpression": "attribute_exists(PK) AND stock >= :qty",
                    "ExpressionAttributeValues": serialize({":qty": action.qty}),
                }
            }

        raise TypeError(f"unsupported action type: {type(action).__name__}")

    @staticmethod
    def _parse_cancellation_reasons(
        exc: Exception,
        actions: list[TransactionAction],
    ) -> list[CancellationReason]:
        """Parse ``CancellationReasons`` into per-action reasons.

        DynamoDB returns one reason per TransactItem, positionally aligned with
        the request. Each ``ConditionalCheckFailed`` on a stock-decrement action
        maps to that action's SKU (an offending product); other codes (conflict,
        throttling) become non-condition failures.
        """

        raw_reasons = getattr(exc, "response", {}).get("CancellationReasons", [])
        reasons: list[CancellationReason] = []
        for index, action in enumerate(actions):
            code = _NONE
            if index < len(raw_reasons):
                code = raw_reasons[index].get("Code", _NONE) or _NONE
            sku = action.sku if isinstance(action, StockDecrementAction) else None
            reasons.append(CancellationReason(code, sku=sku))
        return reasons


# --- botocore error helpers -------------------------------------------------


def _error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _is_conditional_check_failed(exc: Exception) -> bool:
    return _error_code(exc) == "ConditionalCheckFailedException"


def _is_transaction_canceled(exc: Exception) -> bool:
    return _error_code(exc) == "TransactionCanceledException"
