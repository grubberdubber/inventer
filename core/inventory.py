"""Inventory domain models, validation and stock telemetry.

This module is deliberately persistence-agnostic: it owns the shape of the
data, the validation rules applied to every mutation and the threshold logic
that classifies stock and builds dashboard telemetry.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

DEFAULT_LOW_STOCK_FACTOR = 1.5
_SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,19}$")
_BARCODE_PATTERN = re.compile(r"^\d{8,14}$")


class ValidationError(ValueError):
    """Raised when a data mutation payload fails the validation layer."""


class StockStatus(Enum):
    """Operational classification for a product's current stock."""

    OUT = "AGOTADO"
    CRITICAL = "CRÍTICO"
    LOW = "BAJO"
    OK = "OK"

    @property
    def severity(self) -> int:
        """Return the sort rank, lowest meaning most urgent."""
        return {
            StockStatus.OUT: 0,
            StockStatus.CRITICAL: 1,
            StockStatus.LOW: 2,
            StockStatus.OK: 3,
        }[self]

    @property
    def is_alert(self) -> bool:
        """Whether this status requires replenishment attention."""
        return self is not StockStatus.OK


@dataclass(frozen=True, slots=True)
class Product:
    """Immutable snapshot of a catalog product."""

    id: int
    sku: str
    barcode: str
    name: str
    category: str
    unit: str
    stock: int
    min_stock: int
    max_stock: int
    price: float
    cost: float
    supplier: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProductDraft:
    """Validated payload ready to be persisted."""

    product_id: int | None
    sku: str
    barcode: str
    name: str
    category: str
    unit: str
    stock: int
    min_stock: int
    max_stock: int
    price: float
    cost: float
    supplier: str


@dataclass(frozen=True, slots=True)
class Movement:
    """Immutable stock movement record."""

    id: int
    sku: str
    product_name: str
    kind: str
    quantity: int
    note: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CategoryHealth:
    """Aggregated stock coverage for one category."""

    name: str
    products: int
    units: int
    capacity: int
    health: float
    alerts: int


@dataclass(frozen=True, slots=True)
class DashboardStats:
    """Aggregated operational telemetry for the dashboard."""

    total_skus: int
    total_units: int
    inventory_value: float
    critical_count: int
    out_of_stock: int
    low_count: int
    alert_count: int
    health_pct: float
    coverage_pct: float
    categories: tuple[CategoryHealth, ...]


def _as_text(payload: Mapping[str, Any], key: str) -> str:
    """Extract and trim a text field from a mutation payload."""
    value = payload.get(key, "")
    return "" if value is None else str(value).strip()


def _as_int(payload: Mapping[str, Any], key: str) -> int:
    """Parse a strictly integer field from a mutation payload."""
    raw = _as_text(payload, key)
    if not raw:
        raise ValidationError("Completa todos los campos numéricos.")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"El campo '{key}' debe ser un número entero.") from exc


def _as_float(payload: Mapping[str, Any], key: str) -> float:
    """Parse a numeric field accepting dot or comma decimal separators."""
    raw = _as_text(payload, key).replace(" ", "")
    if not raw:
        raise ValidationError("Completa todos los campos numéricos.")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"El campo '{key}' debe ser un número válido.") from exc


def validate_product(payload: Mapping[str, Any]) -> ProductDraft:
    """Validate and normalize a product mutation payload.

    Args:
        payload: Raw field values, usually straight from the UI form.

    Returns:
        A normalized, immutable draft.

    Raises:
        ValidationError: If any field violates the catalog rules.
    """
    product_id_raw = payload.get("product_id")
    product_id: int | None = None
    if product_id_raw not in (None, ""):
        try:
            product_id = int(product_id_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValidationError("Identificador de producto inválido.") from exc
        if product_id <= 0:
            raise ValidationError("Identificador de producto inválido.")

    sku = _as_text(payload, "sku").upper()
    barcode = _as_text(payload, "barcode")
    name = _as_text(payload, "name")
    category = _as_text(payload, "category")
    unit = _as_text(payload, "unit") or "Unidad"
    supplier = _as_text(payload, "supplier")

    if not _SKU_PATTERN.match(sku):
        raise ValidationError(
            "SKU inválido: usa de 3 a 20 caracteres (A-Z, 0-9 o guiones)."
        )
    if not _BARCODE_PATTERN.match(barcode):
        raise ValidationError("El código de barras debe tener entre 8 y 14 dígitos.")
    if not 2 <= len(name) <= 80:
        raise ValidationError("El nombre del producto debe tener entre 2 y 80 caracteres.")
    if not 2 <= len(category) <= 40:
        raise ValidationError("La categoría debe tener entre 2 y 40 caracteres.")
    if len(unit) > 20:
        raise ValidationError("La unidad de medida no puede superar 20 caracteres.")
    if len(supplier) > 80:
        raise ValidationError("El proveedor no puede superar 80 caracteres.")

    stock = _as_int(payload, "stock")
    min_stock = _as_int(payload, "min_stock")
    max_stock = _as_int(payload, "max_stock")
    price = _as_float(payload, "price")
    cost = _as_float(payload, "cost")

    if min(stock, min_stock, max_stock) < 0:
        raise ValidationError("Las cantidades de stock no pueden ser negativas.")
    if min_stock < 1:
        raise ValidationError("El stock mínimo debe ser al menos 1 unidad.")
    if max_stock < min_stock:
        raise ValidationError("El stock máximo debe ser mayor o igual al mínimo.")
    if price < 0 or cost < 0:
        raise ValidationError("Los importes no pueden ser negativos.")

    return ProductDraft(
        product_id=product_id,
        sku=sku,
        barcode=barcode,
        name=name,
        category=category,
        unit=unit,
        stock=stock,
        min_stock=min_stock,
        max_stock=max_stock,
        price=price,
        cost=cost,
        supplier=supplier,
    )


def classify_stock(
    stock: int,
    min_stock: int,
    low_stock_factor: float = DEFAULT_LOW_STOCK_FACTOR,
) -> StockStatus:
    """Classify a stock level against its configured thresholds.

    Args:
        stock: Current units on hand.
        min_stock: Reorder threshold.
        low_stock_factor: Multiplier that defines the low-stock band.

    Returns:
        The matching stock status.
    """
    if stock <= 0:
        return StockStatus.OUT
    if stock <= min_stock:
        return StockStatus.CRITICAL
    if stock < min_stock * low_stock_factor:
        return StockStatus.LOW
    return StockStatus.OK


def reorder_quantity(product: Product) -> int:
    """Suggest a replenishment quantity capped by the product's capacity."""
    target = min(product.max_stock, max(product.min_stock * 2, product.min_stock + 1))
    return max(target - product.stock, 1)


def sort_products(
    products: Iterable[Product],
    low_stock_factor: float = DEFAULT_LOW_STOCK_FACTOR,
) -> list[Product]:
    """Sort products by urgency and then by name."""
    return sorted(
        products,
        key=lambda product: (
            classify_stock(product.stock, product.min_stock, low_stock_factor).severity,
            product.name.casefold(),
        ),
    )


def build_dashboard(
    products: Sequence[Product],
    low_stock_factor: float = DEFAULT_LOW_STOCK_FACTOR,
) -> DashboardStats:
    """Aggregate stock telemetry for the dashboard surfaces.

    Args:
        products: Current catalog snapshot.
        low_stock_factor: Multiplier that defines the low-stock band.

    Returns:
        Immutable dashboard statistics.
    """
    total_skus = len(products)
    total_units = sum(product.stock for product in products)
    inventory_value = sum(product.stock * product.price for product in products)

    statuses = {
        product.id: classify_stock(product.stock, product.min_stock, low_stock_factor)
        for product in products
    }
    out_of_stock = sum(1 for status in statuses.values() if status is StockStatus.OUT)
    critical_count = sum(
        1 for status in statuses.values() if status is StockStatus.CRITICAL
    )
    low_count = sum(1 for status in statuses.values() if status is StockStatus.LOW)
    alert_count = out_of_stock + critical_count + low_count
    healthy = sum(1 for status in statuses.values() if status is StockStatus.OK)

    capacity = sum(product.max_stock for product in products)
    coverage_pct = (total_units / capacity * 100.0) if capacity else 0.0
    health_pct = (healthy / total_skus * 100.0) if total_skus else 100.0

    grouped: dict[str, list[Product]] = defaultdict(list)
    for product in products:
        grouped[product.category].append(product)

    categories = []
    for category_name, items in grouped.items():
        units = sum(item.stock for item in items)
        category_capacity = sum(item.max_stock for item in items)
        category_alerts = sum(
            1
            for item in items
            if classify_stock(item.stock, item.min_stock, low_stock_factor).is_alert
        )
        category_health = (
            (len(items) - category_alerts) / len(items) * 100.0 if items else 0.0
        )
        categories.append(
            CategoryHealth(
                name=category_name,
                products=len(items),
                units=units,
                capacity=category_capacity,
                health=category_health,
                alerts=category_alerts,
            )
        )

    categories.sort(key=lambda item: (item.health, item.name.casefold()))

    return DashboardStats(
        total_skus=total_skus,
        total_units=total_units,
        inventory_value=inventory_value,
        critical_count=critical_count,
        out_of_stock=out_of_stock,
        low_count=low_count,
        alert_count=alert_count,
        health_pct=health_pct,
        coverage_pct=coverage_pct,
        categories=tuple(categories),
    )
