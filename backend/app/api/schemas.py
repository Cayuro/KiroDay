"""Pydantic request/response schemas for the POS API (task 9.2, 9.3).

These models shape and validate the JSON at the HTTP boundary only; the domain
models (:mod:`app.models`) still own the authoritative business validation. The
schemas deliberately keep money as a **decimal string** (never a binary
``float``): prices and totals are accepted and returned as strings so JSON
numbers can never introduce floating-point rounding, matching ``design.md``.

Stock and quantity are integers, as in the data model.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.sale import ITEMS_MAX, ITEMS_MIN, QTY_MAX, QTY_MIN


class ProductCreateRequest(BaseModel):
    """Body of ``POST /products`` (``price`` is a decimal string)."""

    sku: str
    name: str
    # Money as a decimal string; the domain model parses/validates it with
    # Decimal so no binary float is ever involved.
    price: str
    stock: int


class ProductUpdateRequest(BaseModel):
    """Body of ``PUT /products/{sku}``: any subset of ``{name, price, stock}``.

    All fields are optional; only the ones present are applied. ``price`` stays
    a decimal string for the same no-float reason as on create.
    """

    name: str | None = None
    price: str | None = None
    stock: int | None = None

    def to_changes(self) -> dict[str, Any]:
        """Return only the fields the client actually sent (exclude unset)."""

        return self.model_dump(exclude_unset=True, exclude_none=True)


class ProductResponse(BaseModel):
    """Stored product representation echoed back to clients."""

    sku: str
    name: str
    price: str  # decimal string
    stock: int


class SaleItemRequest(BaseModel):
    """A single requested sale line (``{sku, qty}``).

    ``qty`` is bounded at the HTTP boundary so an absurd quantity is rejected
    before any processing; the domain model re-validates the same range.
    """

    sku: str
    qty: int = Field(ge=QTY_MIN, le=QTY_MAX)


class SaleCreateRequest(BaseModel):
    """Body of ``POST /sales``.

    ``items`` is bounded to ``[ITEMS_MIN, ITEMS_MAX]`` (the request-line cap) so
    an oversized payload is rejected early, before deserializing and processing
    every line. The authoritative business limit is the domain's distinct-SKU
    cap (``DISTINCT_SKU_MAX``): a sale commits as one DynamoDB
    ``TransactWriteItems`` of at most 100 actions (one decrement per distinct
    SKU + the sale Put), which :class:`app.models.sale.Sale` enforces before
    building the transaction. The line cap and that domain limit are kept
    consistent (lines may repeat a SKU, so ``ITEMS_MAX >= DISTINCT_SKU_MAX``).
    """

    items: list[SaleItemRequest] = Field(min_length=ITEMS_MIN, max_length=ITEMS_MAX)
    payment_method: str


class SaleItemResponse(BaseModel):
    """A priced sale line in the response (money as decimal strings)."""

    sku: str
    qty: int
    unit_price: str
    subtotal: str


class SaleResponse(BaseModel):
    """Registered sale echoed back to the client."""

    sale_id: str
    total: str
    payment_method: str
    timestamp: str
    items: list[SaleItemResponse]


class DailyReportResponse(BaseModel):
    """Daily report (totals as decimal strings)."""

    date: str
    sales_count: int
    total: str
    by_payment_method: dict[str, str]
