"""Catalog_Service: product create/list/update (Requirement 1, task 5.1).

Owns product validation (delegated to the :class:`app.models.product.Product`
value object) and translates repository outcomes into the service-level errors
the API layer maps to HTTP responses. The service never performs I/O directly:
it is handed a :class:`app.repository.base.PosRepository` so the same logic runs
against the in-memory fake (tests) and DynamoDB (production).

Validation runs before any write, so invalid requests never touch storage
(the "persist nothing" clauses of Requirement 1). A duplicate SKU leaves the
existing product untouched; an invalid or missing update preserves the previous
values.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from app.errors import ErrorCode, PosError, ValidationError
from app.models.product import Product
from app.repository.base import DuplicateItem, ItemNotFound, PosRepository
from app.repository.keys import (
    ENTITY,
    ENTITY_PRODUCT,
    PK,
    SK,
    from_number,
    product_key,
    stock_to_int,
)

# Fields a client may update on an existing product (Requirement 1.7).
UPDATABLE_FIELDS = frozenset({"name", "price", "stock"})


class DuplicateSku(PosError):
    """Raised when creating a product whose SKU already exists (Requirement 1.2)."""

    code = ErrorCode.DUPLICATE_SKU

    def __init__(self, sku: str) -> None:
        super().__init__(
            "El SKU ya existe en el catálogo.",
            {"sku": sku},
        )
        self.sku = sku


class ProductNotFound(PosError):
    """Raised when updating a SKU absent from the catalog (Requirement 1.8)."""

    code = ErrorCode.PRODUCT_NOT_FOUND

    def __init__(self, sku: str) -> None:
        super().__init__(
            "El producto no existe en el catálogo.",
            {"sku": sku},
        )
        self.sku = sku


def _product_item(product: Product) -> dict[str, Any]:
    """Build the single-table item for a product (price/stock as DynamoDB Numbers)."""

    key = product_key(product.sku)
    return {
        PK: key[PK],
        SK: key[SK],
        ENTITY: ENTITY_PRODUCT,
        "name": product.name,
        "price": product.price,  # Decimal -> DynamoDB Number
        "stock": Decimal(product.stock),
    }


def _product_from_item(item: Mapping[str, Any]) -> Product:
    """Rebuild a :class:`Product` from a stored item (inverse of _product_item)."""

    from app.repository.keys import sku_from_product_pk

    return Product.create(
        sku=sku_from_product_pk(item[PK]),
        name=item["name"],
        price=from_number(item["price"]),
        stock=stock_to_int(item["stock"]),
    )


class CatalogService:
    """Create, list, and update catalog products over a :class:`PosRepository`."""

    def __init__(self, repository: PosRepository) -> None:
        self._repo = repository

    def create_product(
        self,
        sku: str,
        name: str,
        price: str | int | Decimal,
        stock: int,
    ) -> Product:
        """Validate and persist a new product, rejecting a duplicate SKU.

        Raises:
            ValidationError: if any field is out of range (nothing persisted).
            DuplicateSku: if the SKU already exists; the existing product is
                left exactly unchanged.
        """

        product = Product.create(sku=sku, name=name, price=price, stock=stock)
        try:
            self._repo.put_product(_product_item(product))
        except DuplicateItem as exc:
            raise DuplicateSku(product.sku) from exc
        return product

    def list_products(self) -> list[Product]:
        """Return every catalog product; an empty catalog returns ``[]``."""

        return [_product_from_item(item) for item in self._repo.list_products()]

    def update_product(self, sku: str, changes: Mapping[str, Any]) -> Product:
        """Apply a subset update of ``{name, price, stock}`` to an existing product.

        The update preserves any field not present in ``changes``. Validation of
        the merged product runs before the write, so an out-of-range value
        leaves the stored product exactly as it was (Requirement 1.9).

        Raises:
            ValidationError: for unknown fields or out-of-range values.
            ProductNotFound: if ``sku`` is absent from the catalog.
        """

        unknown = set(changes) - UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(
                sorted(unknown)[0],
                "Campo no actualizable. Solo se permiten name, price y stock.",
                {"fields": sorted(unknown)},
            )

        existing = self._repo.get_product(sku)
        if existing is None:
            raise ProductNotFound(sku)

        current = _product_from_item(existing)
        # Merge the requested changes over the current values, then re-validate
        # the whole product so out-of-range values are rejected before any write.
        merged = Product.create(
            sku=sku,
            name=changes.get("name", current.name),
            price=changes.get("price", current.price),
            stock=changes.get("stock", current.stock),
        )

        try:
            self._repo.update_product(_product_item(merged))
        except ItemNotFound as exc:
            # The product vanished between read and write; treat as not found.
            raise ProductNotFound(sku) from exc
        return merged
