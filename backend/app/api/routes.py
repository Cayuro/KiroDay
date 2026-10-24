"""HTTP routes for catalog, sales, and daily report (tasks 9.2, 9.3).

Each route is a thin adapter: it converts the validated request schema into the
service call, lets the service enforce business rules (raising a
:class:`app.errors.PosError` on failure, mapped to HTTP by the exception
handlers), and shapes the result into a response schema. Money is carried as
decimal strings end to end; nothing here touches a binary ``float``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    get_catalog_service,
    get_copilot_service,
    get_report_service,
    get_sales_service,
)
from app.api.schemas import (
    DailyReportResponse,
    ProductCreateRequest,
    ProductResponse,
    ProductUpdateRequest,
    PromoComboResponse,
    ResumenGerencialResponse,
    SaleCreateRequest,
    SaleItemResponse,
    SaleResponse,
)
from app.models.product import Product
from app.models.sale import Sale
from app.models.copilot import PromoCombo, ResumenGerencial
from app.services.catalog import CatalogService
from app.services.copilot import CopilotService
from app.services.report import DailyReport, ReportService
from app.services.sales import SalesService

router = APIRouter()


def _product_response(product: Product) -> ProductResponse:
    """Shape a domain :class:`Product` into its response (price as string)."""

    return ProductResponse(
        sku=product.sku,
        name=product.name,
        price=str(product.price),
        stock=product.stock,
    )


def _sale_response(sale: Sale) -> SaleResponse:
    """Shape a domain :class:`Sale` into its response (money as strings)."""

    return SaleResponse(
        sale_id=sale.sale_id,
        total=str(sale.total),
        payment_method=sale.payment_method,
        timestamp=sale.timestamp.isoformat(),
        items=[
            SaleItemResponse(
                sku=item.sku,
                qty=item.qty,
                unit_price=str(item.unit_price),
                subtotal=str(item.subtotal),
            )
            for item in sale.items
        ],
    )


def _report_response(report: DailyReport) -> DailyReportResponse:
    """Shape a :class:`DailyReport` into its response (totals as strings)."""

    return DailyReportResponse(
        date=report.date,
        sales_count=report.sales_count,
        total=str(report.total),
        by_payment_method={
            method: str(value) for method, value in report.by_payment_method.items()
        },
    )


# --- catalog routes (Requirement 1) ----------------------------------------


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    body: ProductCreateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> ProductResponse:
    """Create a product (Requirements 1.1, 1.2)."""

    product = service.create_product(
        sku=body.sku,
        name=body.name,
        price=body.price,
        stock=body.stock,
    )
    return _product_response(product)


@router.get("/products", response_model=list[ProductResponse])
def list_products(
    service: CatalogService = Depends(get_catalog_service),
) -> list[ProductResponse]:
    """List all products; an empty catalog returns ``[]`` (Requirements 1.5, 1.6)."""

    return [_product_response(product) for product in service.list_products()]


@router.put("/products/{sku}", response_model=ProductResponse)
def update_product(
    sku: str,
    body: ProductUpdateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> ProductResponse:
    """Update a subset of ``{name, price, stock}`` (Requirements 1.7, 1.8, 1.9)."""

    product = service.update_product(sku, body.to_changes())
    return _product_response(product)


# --- sales route (Requirements 2 and 3) -------------------------------------


@router.post(
    "/sales",
    response_model=SaleResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_sale(
    body: SaleCreateRequest,
    service: SalesService = Depends(get_sales_service),
) -> SaleResponse:
    """Register a sale and discount stock atomically (Requirements 2.1, 3.3)."""

    raw_items = [{"sku": item.sku, "qty": item.qty} for item in body.items]
    sale = service.register_sale(raw_items, body.payment_method)
    return _sale_response(sale)


# --- report route (Requirement 4) ------------------------------------------


@router.get("/reports/daily", response_model=DailyReportResponse)
def daily_report(
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to today"),
    service: ReportService = Depends(get_report_service),
) -> DailyReportResponse:
    """Return the daily sales report; ``date`` is optional (Requirements 4.1, 4.4, 4.5)."""

    return _report_response(service.daily_report(date))


# --- SmartPOS Copilot routes (US-1, US-2) -----------------------------------


def _promo_combo_response(combo: PromoCombo) -> PromoComboResponse:
    """Shape a domain :class:`PromoCombo` into its response schema."""
    return PromoComboResponse(
        nombre=combo.nombre,
        skus=list(combo.skus),
        precio_original=str(combo.precio_original),
        precio_combo=str(combo.precio_combo),
        ahorro=str(combo.ahorro),
        pitch_cajero=combo.pitch_cajero,
    )


def _resumen_gerencial_response(resumen: ResumenGerencial) -> ResumenGerencialResponse:
    """Shape a domain :class:`ResumenGerencial` into its response schema."""
    return ResumenGerencialResponse(
        fecha=resumen.fecha,
        total_ventas=str(resumen.total_ventas),
        productos_criticos=list(resumen.productos_criticos),
        recomendacion_estrategica=resumen.recomendacion_estrategica,
    )


@router.get("/copilot/promociones", response_model=list[PromoComboResponse])
def get_promociones(
    limite: int = Query(default=5, ge=1, le=100, description="Maximum combos to return"),
    service: CopilotService = Depends(get_copilot_service),
) -> list[PromoComboResponse]:
    """Return dynamic combo suggestions based on current inventory (US-1)."""

    combos = service.generar_promociones(limite_combos=limite)
    return [_promo_combo_response(c) for c in combos]


@router.get("/copilot/diagnostico-hoy", response_model=ResumenGerencialResponse)
def get_diagnostico_hoy(
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to today"),
    service: CopilotService = Depends(get_copilot_service),
) -> ResumenGerencialResponse:
    """Return the managerial diagnostic with stock alerts and recommendations (US-2)."""

    resumen = service.analisis_gerencial(fecha=date)
    return _resumen_gerencial_response(resumen)
