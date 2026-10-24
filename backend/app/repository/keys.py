"""Single-table key design and Decimal<->DynamoDB Number helpers (task 4.1).

Encodes the key layout from ``design.md`` for the single ``pos`` table:

======= ================= =========================== =================================
Entity  PK                SK                          Other attributes
======= ================= =========================== =================================
Product ``PRODUCT#<sku>``  ``PRODUCT#<sku>``           ``name``, ``price`` (N), ``stock`` (N)
Sale    ``SALE#<date>``    ``SALE#<ts>#<saleId>``      ``total`` (N), ``payment_method``, ...
======= ================= =========================== =================================

Also provides conversion helpers between Python ``Decimal`` and the value shape
DynamoDB uses for ``Number`` attributes (a decimal string), so money never
passes through binary ``float``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

# Key prefixes and the single-table attribute names.
PRODUCT_PREFIX = "PRODUCT#"
SALE_PREFIX = "SALE#"

PK = "PK"
SK = "SK"
ENTITY = "entity"

ENTITY_PRODUCT = "PRODUCT"
ENTITY_SALE = "SALE"


def product_pk(sku: str) -> str:
    """Return the partition key for a product: ``PRODUCT#<sku>``."""

    return f"{PRODUCT_PREFIX}{sku}"


def product_key(sku: str) -> dict[str, str]:
    """Return the full primary key (PK == SK) for a product item."""

    pk = product_pk(sku)
    return {PK: pk, SK: pk}


def sku_from_product_pk(pk: str) -> str:
    """Extract the SKU from a ``PRODUCT#<sku>`` partition key.

    Raises:
        ValueError: if ``pk`` is not a product partition key.
    """

    if not pk.startswith(PRODUCT_PREFIX):
        raise ValueError(f"not a product PK: {pk!r}")
    return pk[len(PRODUCT_PREFIX) :]


def sale_pk(date: str) -> str:
    """Return the partition key for a sale given its calendar date: ``SALE#<date>``."""

    return f"{SALE_PREFIX}{date}"


def sale_sk(timestamp: str, sale_id: str) -> str:
    """Return the sort key for a sale: ``SALE#<ts>#<saleId>``."""

    return f"{SALE_PREFIX}{timestamp}#{sale_id}"


def sale_date(timestamp: datetime) -> str:
    """Return the UTC calendar date ``YYYY-MM-DD`` used to partition a sale.

    The caller is expected to pass a timezone-aware UTC timestamp (sales are
    registered in UTC); the date is taken from it directly.
    """

    return timestamp.date().isoformat()


# --- Decimal <-> DynamoDB Number -------------------------------------------


def to_number(value: Decimal | int) -> Decimal:
    """Convert a money/quantity value to the ``Decimal`` DynamoDB stores as ``N``.

    boto3's resource interface represents ``Number`` attributes as ``Decimal``;
    this helper keeps the conversion explicit and rejects binary ``float`` so
    money never loses precision. Integers (e.g. stock, quantity) are accepted
    and converted to ``Decimal``.

    Raises:
        TypeError: if ``value`` is a ``float`` or an unsupported type.
    """

    if isinstance(value, bool):  # bool is an int subclass; reject explicitly.
        raise TypeError("number value must not be a bool")
    if isinstance(value, float):
        raise TypeError("number value must not be a binary float")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(f"unsupported number type: {type(value).__name__}")


def from_number(value: Decimal | int | str) -> Decimal:
    """Convert a DynamoDB ``Number`` (``Decimal``/int/str) back to ``Decimal``."""

    if isinstance(value, bool):
        raise TypeError("number value must not be a bool")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise TypeError(f"unsupported number type: {type(value).__name__}")


def stock_to_int(value: Decimal | int | str) -> int:
    """Convert a stored stock ``Number`` back to a Python ``int``."""

    return int(from_number(value))
