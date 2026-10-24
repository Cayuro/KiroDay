"""Decimal-based money helpers for the POS MVP.

Monetary values are always represented with :class:`decimal.Decimal` and
quantized to two decimal places with ``ROUND_HALF_UP``. Binary ``float`` is
never used for money, to avoid rounding surprises at range boundaries.

Parsing from untrusted input goes through :func:`to_money`, which accepts
``str``, ``int``, or ``Decimal`` but rejects ``float`` (binary floating point)
so callers cannot silently introduce rounding error.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# Price bounds shared by products and sale totals (design.md).
MIN_PRICE = Decimal("0.01")
MAX_PRICE = Decimal("999999999.99")

# A report total may be zero (a day with no sales), unlike a product price.
MIN_REPORT_TOTAL = Decimal("0.00")

# The quantization target: exactly two decimal places.
CENTS = Decimal("0.01")


def to_money(value: str | int | Decimal) -> Decimal:
    """Convert a value to a two-decimal :class:`Decimal`.

    Accepts ``str``, ``int``, or ``Decimal``. A ``float`` is rejected with
    :class:`TypeError` because binary floats cannot represent decimal money
    exactly. The result is quantized to two decimals with ``ROUND_HALF_UP``.

    Raises:
        TypeError: if ``value`` is a ``float`` or an unsupported type.
        ValueError: if ``value`` is a string that is not a valid decimal.
    """

    if isinstance(value, bool):  # bool is a subclass of int; reject explicitly.
        raise TypeError("money value must not be a bool")
    if isinstance(value, float):
        raise TypeError("money value must not be a binary float; use str/Decimal")
    if isinstance(value, (str, int, Decimal)):
        try:
            dec = Decimal(value)
            return quantize_money(dec)
        except InvalidOperation as exc:
            # Covers unparseable strings and values with too many digits to
            # quantize to two decimals; both are invalid money values.
            raise ValueError(f"invalid decimal value: {value!r}") from exc
    raise TypeError(f"unsupported money type: {type(value).__name__}")


def quantize_money(value: Decimal) -> Decimal:
    """Round a :class:`Decimal` to two decimal places with ``ROUND_HALF_UP``."""

    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def is_within_price_range(value: Decimal) -> bool:
    """Return True if ``value`` is within the valid price range ``[0.01, 1e9-.01]``."""

    return MIN_PRICE <= value <= MAX_PRICE
