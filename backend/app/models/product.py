"""Product domain model and validation (Requirement 1).

A :class:`Product` is an immutable value object validated at construction. All
range checks raise :class:`app.errors.ValidationError` naming the offending
field. Money (``price``) is a :class:`decimal.Decimal`, never a binary float.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.errors import ValidationError
from app.money import MAX_PRICE, MIN_PRICE, to_money

# Field bounds from design.md / Requirement 1.
NAME_MIN_LEN = 1
NAME_MAX_LEN = 100
SKU_MIN_LEN = 1
SKU_MAX_LEN = 50
STOCK_MIN = 0
STOCK_MAX = 999_999


def _validate_sku(sku: str) -> str:
    if not isinstance(sku, str):
        raise ValidationError("sku", "El SKU debe ser una cadena de texto.")
    if not (SKU_MIN_LEN <= len(sku) <= SKU_MAX_LEN):
        raise ValidationError(
            "sku",
            f"El SKU debe tener entre {SKU_MIN_LEN} y {SKU_MAX_LEN} caracteres.",
            {"length": len(sku)},
        )
    return sku


def _validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValidationError("name", "El nombre debe ser una cadena de texto.")
    if not (NAME_MIN_LEN <= len(name) <= NAME_MAX_LEN):
        raise ValidationError(
            "name",
            f"El nombre debe tener entre {NAME_MIN_LEN} y {NAME_MAX_LEN} caracteres.",
            {"length": len(name)},
        )
    return name


def _validate_price(price: str | int | Decimal) -> Decimal:
    # to_money rejects binary float and parses str/int/Decimal to 2 decimals.
    try:
        value = to_money(price)
    except (TypeError, ValueError) as exc:
        raise ValidationError("price", f"El precio no es un valor válido: {exc}") from exc
    if not (MIN_PRICE <= value <= MAX_PRICE):
        raise ValidationError(
            "price",
            f"El precio debe estar entre {MIN_PRICE} y {MAX_PRICE}.",
            {"price": str(value)},
        )
    return value


def _validate_stock(stock: int) -> int:
    # bool is a subclass of int; reject it so True/False cannot pass as stock.
    if isinstance(stock, bool) or not isinstance(stock, int):
        raise ValidationError("stock", "El stock debe ser un número entero.")
    if not (STOCK_MIN <= stock <= STOCK_MAX):
        raise ValidationError(
            "stock",
            f"El stock debe estar entre {STOCK_MIN} y {STOCK_MAX}.",
            {"stock": stock},
        )
    return stock


@dataclass(frozen=True)
class Product:
    """A catalog product identified by SKU.

    Attributes:
        sku: Unique product code, 1–50 characters.
        name: Display name, 1–100 characters.
        price: Unit price as a two-decimal ``Decimal`` in ``[0.01, 999999999.99]``.
        stock: Available quantity, integer in ``[0, 999999]``.
    """

    sku: str
    name: str
    price: Decimal
    stock: int

    @classmethod
    def create(
        cls,
        sku: str,
        name: str,
        price: str | int | Decimal,
        stock: int,
    ) -> "Product":
        """Validate inputs and build a :class:`Product`.

        Raises :class:`app.errors.ValidationError` naming the first offending
        field when any value is out of range.
        """

        return cls(
            sku=_validate_sku(sku),
            name=_validate_name(name),
            price=_validate_price(price),
            stock=_validate_stock(stock),
        )

    def to_dict(self) -> dict:
        """Return the stored representation (price as a decimal string)."""

        return {
            "sku": self.sku,
            "name": self.name,
            "price": str(self.price),
            "stock": self.stock,
        }
