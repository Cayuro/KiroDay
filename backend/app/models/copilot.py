"""Copilot domain models: PromoCombo and ResumenGerencial.

These are read-only value objects produced by :class:`app.services.copilot.CopilotService`.
Money fields are always :class:`decimal.Decimal` (never ``float``), per the
project's strict monetary precision rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PromoCombo:
    """A suggested promotional bundle for the cashier to offer at the counter.

    Attributes:
        nombre: Human-readable combo name (in Spanish).
        skus: List of SKUs included in this combo (at least 2).
        precio_original: Sum of the individual unit prices (Decimal, 2 dec).
        precio_combo: Discounted bundle price; always >= precio_original * 0.85
            to respect the 15% minimum margin rule.
        ahorro: precio_original - precio_combo (Decimal, 2 dec, >= 0).
        pitch_cajero: Ready-to-say sales phrase for the cashier.
    """

    nombre: str
    skus: list[str]
    precio_original: Decimal
    precio_combo: Decimal
    ahorro: Decimal
    pitch_cajero: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "nombre": self.nombre,
            "skus": list(self.skus),
            "precio_original": str(self.precio_original),
            "precio_combo": str(self.precio_combo),
            "ahorro": str(self.ahorro),
            "pitch_cajero": self.pitch_cajero,
        }


@dataclass(frozen=True)
class ResumenGerencial:
    """Daily managerial summary with stock alerts and strategic recommendations.

    Attributes:
        fecha: Report date as ``YYYY-MM-DD``.
        total_ventas: Total sales amount for the day (Decimal, 2 dec, >= 0.00).
        productos_criticos: SKUs whose stock is below the critical threshold (< 5).
        recomendacion_estrategica: Plain-Spanish text with actionable advice for
            the store owner.
    """

    fecha: str
    total_ventas: Decimal
    productos_criticos: list[str]
    recomendacion_estrategica: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fecha": self.fecha,
            "total_ventas": str(self.total_ventas),
            "productos_criticos": list(self.productos_criticos),
            "recomendacion_estrategica": self.recomendacion_estrategica,
        }
