"""Shared error primitives for the POS MVP.

Defines the machine-readable ``ErrorCode`` enum, the JSON error envelope
``{ "error": { "code", "message", "details" } }`` used across the API, and a
base ``PosError`` exception that domain and service layers raise. The FastAPI
layer (later wave) maps these to HTTP responses.

Code and comments are in English per project conventions; user-facing messages
are rendered in Spanish by the frontend using the ``code``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Machine-readable error codes returned by the backend.

    Mirrors the error table in ``design.md``. Inherits from ``str`` so the value
    serializes directly to JSON as its string form.
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_SKU = "DUPLICATE_SKU"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    UNKNOWN_SKU = "UNKNOWN_SKU"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    INVALID_DATE = "INVALID_DATE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def error_envelope(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical JSON error envelope.

    Returns ``{ "error": { "code", "message", "details" } }``. The ``details``
    key is always present (an empty dict when no details are supplied) so
    clients can rely on a stable shape.
    """

    return {
        "error": {
            "code": code.value,
            "message": message,
            "details": details or {},
        }
    }


class PosError(Exception):
    """Base class for all domain/service errors in the POS backend.

    Carries an ``ErrorCode``, a human-readable message, and optional structured
    ``details``. Services raise subclasses of this and the API layer turns them
    into the error envelope with the matching HTTP status.
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        code: ErrorCode | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        if code is not None:
            self.code = code

    def to_envelope(self) -> dict[str, Any]:
        """Render this error as the canonical JSON error envelope."""

        return error_envelope(self.code, self.message, self.details)


class ValidationError(PosError):
    """Raised when a field fails validation.

    The offending field name is recorded in ``details["field"]`` so the error
    message identifies the invalid field, as required by the design.
    """

    code = ErrorCode.VALIDATION_ERROR

    def __init__(
        self,
        field: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = {"field": field}
        if details:
            merged.update(details)
        super().__init__(message, merged)
        self.field = field
