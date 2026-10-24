"""Report_Service: the daily sales report (Requirement 4, task 8.1).

Aggregates the sales stored for one calendar date into a count, a total, and a
breakdown by payment method. The date is validated (calendar format; future
dates rejected) before any query, and defaults to the system's current UTC date
when omitted. The service is read-only: it never mutates stored data, so an
invalid date leaves sales unchanged (Requirement 4.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any

from app.errors import ErrorCode, PosError
from app.money import quantize_money
from app.repository.base import PosRepository
from app.repository.keys import from_number

# Canonical calendar date format accepted by the report (YYYY-MM-DD).
_CALENDAR_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class InvalidDate(PosError):
    """Raised for a malformed or future report date (Requirement 4.5)."""

    code = ErrorCode.INVALID_DATE

    def __init__(self, date: str, message: str | None = None) -> None:
        super().__init__(
            message or "La fecha es inválida.",
            {"date": date},
        )
        self.date = date


@dataclass(frozen=True)
class DailyReport:
    """Aggregated sales for one calendar date.

    Attributes:
        date: The report date as ``YYYY-MM-DD``.
        sales_count: Number of sales registered that date (``>= 0``).
        total: Sum of those sales' totals (``Decimal``, 2 decimals, ``>= 0.00``).
        by_payment_method: Total per payment method, containing only methods
            with at least one sale that date.
    """

    date: str
    sales_count: int
    total: Decimal
    by_payment_method: dict[str, Decimal]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "sales_count": self.sales_count,
            "total": str(self.total),
            "by_payment_method": {
                method: str(value) for method, value in self.by_payment_method.items()
            },
        }


def _parse_report_date(raw: str | None, today: date_cls) -> str:
    """Validate ``raw`` (or default to ``today``) and return ``YYYY-MM-DD``.

    Raises:
        InvalidDate: if ``raw`` is not a valid ISO calendar date or is in the
            future relative to ``today``.
    """

    if raw is None:
        return today.isoformat()

    if not isinstance(raw, str):
        raise InvalidDate(str(raw), "La fecha debe tener formato AAAA-MM-DD.")

    # Enforce the canonical YYYY-MM-DD form explicitly. date.fromisoformat on
    # Python 3.11+ also accepts the basic ISO form (e.g. "20250601") and other
    # separators, which the design does not consider a valid calendar date for
    # the report, so a format check precedes parsing.
    if not _CALENDAR_DATE_RE.fullmatch(raw):
        raise InvalidDate(raw, "La fecha debe tener formato AAAA-MM-DD.")
    try:
        # Rejects impossible calendar dates (e.g. 2025-02-30, 2025-13-01).
        parsed = date_cls.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidDate(raw, "La fecha debe tener formato AAAA-MM-DD.") from exc

    if parsed > today:
        raise InvalidDate(raw, "La fecha no puede ser futura.")

    # Normalize (e.g. accept only the canonical form we store under SALE#<date>).
    return parsed.isoformat()


class ReportService:
    """Generate the daily sales report over a :class:`PosRepository`."""

    def __init__(self, repository: PosRepository) -> None:
        self._repo = repository

    def daily_report(self, date: str | None = None) -> DailyReport:
        """Return the :class:`DailyReport` for ``date`` (defaults to today, UTC).

        Raises:
            InvalidDate: for a malformed or future date; stored data is left
                unchanged (no query is issued for an invalid date).
        """

        today = datetime.now(timezone.utc).date()
        report_date = _parse_report_date(date, today)

        sales = self._repo.query_sales_by_date(report_date)

        total = Decimal("0")
        by_payment_method: dict[str, Decimal] = {}
        for sale in sales:
            sale_total = from_number(sale["total"])
            total += sale_total
            method = sale["payment_method"]
            by_payment_method[method] = (
                by_payment_method.get(method, Decimal("0")) + sale_total
            )

        return DailyReport(
            date=report_date,
            sales_count=len(sales),
            total=quantize_money(total),
            by_payment_method={
                method: quantize_money(value)
                for method, value in by_payment_method.items()
            },
        )
