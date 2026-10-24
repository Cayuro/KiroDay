"""Dependency wiring for the API layer (task 9.2, 9.3).

The repository is exposed through a single FastAPI dependency so routes stay
agnostic about the backend: production resolves the DynamoDB-backed repository,
while tests override the dependency with the in-memory fake. Services are built
per request on top of whichever repository is resolved, keeping them stateless
and the wiring trivial to swap.

To inject a different repository (e.g. the fake in integration tests) override
:func:`get_repository` via ``app.dependency_overrides`` instead of mutating
module state.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.repository.base import PosRepository
from app.services.catalog import CatalogService
from app.services.inventory import InventoryService
from app.services.report import ReportService
from app.services.sales import SalesService


@lru_cache(maxsize=1)
def _default_repository() -> PosRepository:
    """Build (once) the production DynamoDB repository.

    Imported lazily and cached so importing this module never requires AWS and
    the boto3-backed repository is created only when actually used.
    """

    from app.repository.dynamodb import DynamoDBPosRepository

    return DynamoDBPosRepository()


def get_repository() -> PosRepository:
    """Return the repository the API should use.

    Overridden in tests (via ``app.dependency_overrides``) to inject the
    in-memory fake; in production it resolves the DynamoDB repository.
    """

    return _default_repository()


def get_catalog_service(
    repository: PosRepository = Depends(get_repository),
) -> CatalogService:
    """Build a :class:`CatalogService` over the resolved repository."""

    return CatalogService(repository)


def get_sales_service(
    repository: PosRepository = Depends(get_repository),
) -> SalesService:
    """Build a :class:`SalesService` (with its inventory service) per request."""

    return SalesService(repository, InventoryService(repository))


def get_report_service(
    repository: PosRepository = Depends(get_repository),
) -> ReportService:
    """Build a :class:`ReportService` over the resolved repository."""

    return ReportService(repository)
