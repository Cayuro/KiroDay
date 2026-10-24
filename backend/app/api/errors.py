"""FastAPI exception handlers and the domain-error -> HTTP mapping (task 9.1).

Every domain/service error is a :class:`app.errors.PosError` carrying an
:class:`app.errors.ErrorCode`. This module maps each code to its HTTP status
(per the error table in ``design.md``) and renders the error with the canonical
envelope ``{ "error": { "code", "message", "details" } }`` produced by
``PosError.to_envelope()``.

Mapping (design.md):

======================  ====  =================================================
``ErrorCode``           HTTP  Notes
======================  ====  =================================================
VALIDATION_ERROR        400
DUPLICATE_SKU           409
PRODUCT_NOT_FOUND       404
UNKNOWN_SKU             404
INSUFFICIENT_STOCK      409   ``details.skus`` lists the offending SKUs
TRANSACTION_FAILED      503
INVALID_DATE            400
INTERNAL_ERROR          500
======================  ====  =================================================

Two extra handlers keep the envelope consistent for failures that do not
originate as a ``PosError``:

* request-body validation from FastAPI/Pydantic -> ``400 VALIDATION_ERROR``;
* any uncaught exception -> ``500 INTERNAL_ERROR`` (details withheld).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import ErrorCode, PosError, error_envelope

logger = logging.getLogger(__name__)

# Each machine-readable code maps to exactly one HTTP status.
STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.DUPLICATE_SKU: 409,
    ErrorCode.PRODUCT_NOT_FOUND: 404,
    ErrorCode.UNKNOWN_SKU: 404,
    ErrorCode.INSUFFICIENT_STOCK: 409,
    ErrorCode.TRANSACTION_FAILED: 503,
    ErrorCode.INVALID_DATE: 400,
    ErrorCode.INTERNAL_ERROR: 500,
}


def status_for(code: ErrorCode) -> int:
    """Return the HTTP status for ``code`` (defaults to 500 if unmapped)."""

    return STATUS_BY_CODE.get(code, 500)


async def pos_error_handler(_request: Request, exc: PosError) -> JSONResponse:
    """Render any domain/service ``PosError`` as its envelope + HTTP status."""

    return JSONResponse(
        status_code=status_for(exc.code),
        content=exc.to_envelope(),
    )


async def request_validation_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Map FastAPI/Pydantic body validation failures to ``400 VALIDATION_ERROR``.

    The raw Pydantic error list is passed through under ``details.errors`` so
    clients can see which field failed, while keeping the canonical envelope.
    """

    return JSONResponse(
        status_code=status_for(ErrorCode.VALIDATION_ERROR),
        content=error_envelope(
            ErrorCode.VALIDATION_ERROR,
            "La solicitud tiene campos inválidos.",
            {"errors": _jsonable_errors(exc)},
        ),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: map any uncaught error to ``500 INTERNAL_ERROR``.

    The uncaught exception is logged with its traceback for diagnosis, but its
    detail is intentionally not leaked to the client.
    """

    logger.exception(
        "Unhandled exception while processing %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=status_for(ErrorCode.INTERNAL_ERROR),
        content=error_envelope(
            ErrorCode.INTERNAL_ERROR,
            "Ocurrió un error inesperado.",
        ),
    )


def _jsonable_errors(exc: RequestValidationError) -> list[dict]:
    """Return the Pydantic errors reduced to JSON-serializable fields."""

    cleaned: list[dict] = []
    for err in exc.errors():
        cleaned.append(
            {
                "loc": [str(part) for part in err.get("loc", [])],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return cleaned


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all POS exception handlers to ``app``."""

    app.add_exception_handler(PosError, pos_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
