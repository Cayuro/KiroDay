"""Unit tests for Report_Service (task 8.5).

Covers the empty-date report (Requirement 4.3) and the omitted-date default to
the system current date (Requirement 4.4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.errors import ErrorCode
from app.repository.memory import InMemoryPosRepository
from app.services.catalog import CatalogService
from app.services.report import InvalidDate, ReportService
from app.services.sales import SalesService


# Requirement 4.3
def test_report_for_date_with_no_sales_is_empty():
    repo = InMemoryPosRepository()
    service = ReportService(repo)
    report = service.daily_report("2024-01-01")
    assert report.sales_count == 0
    assert report.total == Decimal("0.00")
    assert report.by_payment_method == {}
    assert report.to_dict()["total"] == "0.00"


# Requirement 4.4
def test_omitted_date_uses_system_current_date():
    repo = InMemoryPosRepository()
    catalog = CatalogService(repo)
    catalog.create_product(sku="A", name="Café", price="2.50", stock=10)
    sales = SalesService(repo)
    sale = sales.register_sale([{"sku": "A", "qty": 2}], "efectivo")

    report = ReportService(repo).daily_report()  # no date argument
    today = datetime.now(timezone.utc).date().isoformat()
    assert report.date == today
    assert report.sales_count == 1
    assert report.total == sale.total
    assert report.by_payment_method == {"efectivo": sale.total}


def test_future_date_rejected_with_invalid_date_code():
    repo = InMemoryPosRepository()
    service = ReportService(repo)
    future = "2999-01-01"
    with pytest.raises(InvalidDate) as exc:
        service.daily_report(future)
    assert exc.value.code == ErrorCode.INVALID_DATE


def test_malformed_date_rejected():
    repo = InMemoryPosRepository()
    service = ReportService(repo)
    with pytest.raises(InvalidDate):
        service.daily_report("06-01-2025")
