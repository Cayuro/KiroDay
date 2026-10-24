"""Property-based tests for Report_Service (Properties 12-14; tasks 8.2-8.4).

Exercised against the in-memory fake, seeding sales directly through the
Sales_Service so the stored shape matches production. Sales are spread across
several dates by controlling the registration timestamp.

Properties 12/13/14 from design.md; Requirements 4.1, 4.2, 4.5.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.repository.keys import ENTITY, ENTITY_SALE, PK, SK, sale_pk, sale_sk
from app.repository.memory import InMemoryPosRepository
from app.services.report import InvalidDate, ReportService


# --- helpers ---------------------------------------------------------------

payment_methods = st.sampled_from(["efectivo", "tarjeta"])
totals = st.integers(min_value=1, max_value=1_000_00).map(
    lambda cents: Decimal(cents) / Decimal(100)
)


def _put_sale(repo: InMemoryPosRepository, date: str, total: Decimal, method: str) -> None:
    """Insert a sale item directly for a given date/total/payment method."""

    ts = f"{date}T12:00:00+00:00"
    sale_id = f"{date}-{len(repo.query_sales_by_date(date))}-{method}"
    repo._items[(sale_pk(date), sale_sk(ts, sale_id))] = {  # noqa: SLF001
        PK: sale_pk(date),
        SK: sale_sk(ts, sale_id),
        ENTITY: ENTITY_SALE,
        "sale_id": sale_id,
        "total": total,
        "payment_method": method,
        "timestamp": ts,
        "items": [],
    }


# A pool of distinct past dates so "today" is never in the future.
@st.composite
def dated_sales(draw):
    """Generate a mapping date -> list of (total, payment_method)."""

    num_dates = draw(st.integers(min_value=1, max_value=4))
    base = date_cls(2024, 1, 1)
    dates = [base + timedelta(days=draw(st.integers(0, 300))) for _ in range(num_dates)]
    sales_by_date: dict[str, list[tuple[Decimal, str]]] = {}
    for d in dates:
        iso = d.isoformat()
        count = draw(st.integers(min_value=0, max_value=5))
        sales_by_date.setdefault(iso, [])
        for _ in range(count):
            sales_by_date[iso].append((draw(totals), draw(payment_methods)))
    return sales_by_date


# --- Property 12 -----------------------------------------------------------

# Feature: pos-mvp, Property 12: Daily report aggregates count and total for its date
@given(sales_by_date=dated_sales())
def test_report_aggregates_count_and_total(sales_by_date):
    repo = InMemoryPosRepository()
    for date, sales in sales_by_date.items():
        for total, method in sales:
            _put_sale(repo, date, total, method)

    service = ReportService(repo)
    for date, sales in sales_by_date.items():
        report = service.daily_report(date)
        assert report.sales_count == len(sales)
        expected_total = sum((t for t, _ in sales), Decimal("0"))
        assert report.total == expected_total.quantize(Decimal("0.01"))
        assert Decimal("0.00") <= report.total


# --- Property 13 -----------------------------------------------------------

# Feature: pos-mvp, Property 13: Daily report breakdown partitions the total by payment method
@given(sales_by_date=dated_sales())
def test_report_breakdown_partitions_total(sales_by_date):
    repo = InMemoryPosRepository()
    for date, sales in sales_by_date.items():
        for total, method in sales:
            _put_sale(repo, date, total, method)

    service = ReportService(repo)
    for date, sales in sales_by_date.items():
        report = service.daily_report(date)

        used_methods = {method for _, method in sales}
        # Exactly the methods with at least one sale appear as keys.
        assert set(report.by_payment_method) == used_methods
        # Each method maps to the sum of that method's totals.
        for method in used_methods:
            expected = sum(
                (t for t, m in sales if m == method), Decimal("0")
            ).quantize(Decimal("0.01"))
            assert report.by_payment_method[method] == expected
        # The breakdown values sum to the overall total.
        breakdown_sum = sum(report.by_payment_method.values(), Decimal("0"))
        assert breakdown_sum.quantize(Decimal("0.01")) == report.total


# --- Property 14 -----------------------------------------------------------

# Feature: pos-mvp, Property 14: Invalid or future report dates are rejected and leave data unchanged
@given(
    sales_by_date=dated_sales(),
    bad_date=st.one_of(
        st.text(max_size=12).filter(lambda s: not _looks_like_iso(s)),
        st.just("2025-13-01"),
        st.just("2025-02-30"),
        st.just("not-a-date"),
        st.just("20250601"),
    ),
)
def test_invalid_date_rejected_data_unchanged(sales_by_date, bad_date):
    repo = InMemoryPosRepository()
    for date, sales in sales_by_date.items():
        for total, method in sales:
            _put_sale(repo, date, total, method)
    before = dict(repo._items)  # noqa: SLF001

    service = ReportService(repo)
    with pytest.raises(InvalidDate):
        service.daily_report(bad_date)

    assert repo._items == before  # noqa: SLF001


# Feature: pos-mvp, Property 14: Invalid or future report dates are rejected and leave data unchanged
@given(days_ahead=st.integers(min_value=1, max_value=3650))
def test_future_date_rejected(days_ahead):
    repo = InMemoryPosRepository()
    _put_sale(repo, "2024-01-01", Decimal("5.00"), "efectivo")
    before = dict(repo._items)  # noqa: SLF001

    future = (datetime.now(timezone.utc).date() + timedelta(days=days_ahead)).isoformat()
    service = ReportService(repo)
    with pytest.raises(InvalidDate):
        service.daily_report(future)

    assert repo._items == before  # noqa: SLF001


def _looks_like_iso(s: str) -> bool:
    try:
        date_cls.fromisoformat(s)
        return True
    except ValueError:
        return False
