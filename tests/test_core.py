"""Unit tests for the inventory domain and the SQLite repository."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from core.database import Database
from core.inventory import (
    Product,
    StockStatus,
    ValidationError,
    build_dashboard,
    classify_stock,
    reorder_quantity,
    sort_products,
    validate_product,
)


def _payload(**overrides: Any) -> dict[str, Any]:
    """Build a valid product payload with optional overrides."""
    payload: dict[str, Any] = {
        "sku": "TST-001",
        "barcode": "7501234567890",
        "name": "Producto de prueba",
        "category": "Pruebas",
        "unit": "Unidad",
        "stock": "10",
        "min_stock": "5",
        "max_stock": "40",
        "price": "2,50",
        "cost": "1.20",
        "supplier": "Proveedor de prueba",
    }
    payload.update(overrides)
    return payload


def _product(
    product_id: int,
    *,
    name: str,
    category: str,
    stock: int,
    min_stock: int,
    max_stock: int,
    price: float = 1.0,
    cost: float = 0.5,
) -> Product:
    """Create an immutable product snapshot for aggregation tests."""
    return Product(
        id=product_id,
        sku=f"SKU-{product_id:03d}",
        barcode=f"750000000{product_id:04d}",
        name=name,
        category=category,
        unit="Unidad",
        stock=stock,
        min_stock=min_stock,
        max_stock=max_stock,
        price=price,
        cost=cost,
        supplier="Proveedor",
        updated_at=datetime(2026, 11, 9, 12, 0, 0),
    )


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Create an initialized repository backed by a temporary database."""
    database = Database(tmp_path / "inventer-test.db")
    database.initialize()
    try:
        yield database
    finally:
        database.close()


# --------------------------------------------------------------------- domain


def test_validate_product_normalizes_fields() -> None:
    draft = validate_product(_payload(sku=" tst-001 ", price="1.234,56"))

    assert draft.product_id is None
    assert draft.sku == "TST-001"
    assert draft.price == pytest.approx(1234.56)
    assert draft.cost == pytest.approx(1.20)
    assert draft.stock == 10
    assert draft.min_stock == 5
    assert draft.max_stock == 40


def test_validate_product_rejects_invalid_sku() -> None:
    with pytest.raises(ValidationError, match="SKU inválido"):
        validate_product(_payload(sku="A!"))


def test_validate_product_rejects_invalid_barcode() -> None:
    with pytest.raises(ValidationError, match="código de barras"):
        validate_product(_payload(barcode="1234"))


def test_validate_product_rejects_negative_stock() -> None:
    with pytest.raises(ValidationError, match="negativas"):
        validate_product(_payload(stock="-1"))


def test_validate_product_rejects_inconsistent_thresholds() -> None:
    with pytest.raises(ValidationError, match="stock máximo"):
        validate_product(_payload(min_stock="20", max_stock="10"))


def test_validate_product_rejects_negative_product_id() -> None:
    with pytest.raises(ValidationError, match="Identificador"):
        validate_product(_payload(product_id="-3"))


def test_validate_product_requires_integer_quantity() -> None:
    with pytest.raises(ValidationError, match="número entero"):
        validate_product(_payload(stock="2.5"))


def test_classify_stock_boundaries() -> None:
    assert classify_stock(0, 10) is StockStatus.OUT
    assert classify_stock(-4, 10) is StockStatus.OUT
    assert classify_stock(10, 10) is StockStatus.CRITICAL
    assert classify_stock(11, 10) is StockStatus.LOW
    assert classify_stock(14, 10) is StockStatus.LOW
    assert classify_stock(15, 10) is StockStatus.OK
    assert classify_stock(99, 10) is StockStatus.OK


def test_classify_stock_respects_custom_factor() -> None:
    assert classify_stock(16, 10, low_stock_factor=2.0) is StockStatus.LOW
    assert classify_stock(20, 10, low_stock_factor=2.0) is StockStatus.OK


def test_reorder_quantity_respects_capacity() -> None:
    product = _product(
        1,
        name="Leche",
        category="Lácteos",
        stock=3,
        min_stock=10,
        max_stock=40,
    )

    assert reorder_quantity(product) == 17

    full = _product(
        2,
        name="Agua",
        category="Bebidas",
        stock=80,
        min_stock=10,
        max_stock=40,
    )
    assert reorder_quantity(full) == 1


def test_sort_products_orders_by_urgency() -> None:
    products = [
        _product(1, name="OK", category="A", stock=40, min_stock=10, max_stock=50),
        _product(2, name="LOW", category="A", stock=12, min_stock=10, max_stock=50),
        _product(3, name="OUT", category="A", stock=0, min_stock=10, max_stock=50),
        _product(4, name="CRIT", category="A", stock=10, min_stock=10, max_stock=50),
    ]

    ordered = sort_products(products)

    assert [product.name for product in ordered] == ["OUT", "CRIT", "LOW", "OK"]


def test_build_dashboard_aggregates_telemetry() -> None:
    products = [
        _product(1, name="A", category="Lácteos", stock=0, min_stock=10, max_stock=20, price=2.0),
        _product(2, name="B", category="Lácteos", stock=10, min_stock=10, max_stock=20, price=3.0),
        _product(3, name="C", category="Bebidas", stock=12, min_stock=10, max_stock=20, price=1.0),
        _product(4, name="D", category="Bebidas", stock=20, min_stock=10, max_stock=20, price=4.0),
    ]

    stats = build_dashboard(products)

    assert stats.total_skus == 4
    assert stats.total_units == 42
    assert stats.inventory_value == pytest.approx(122.0)
    assert stats.out_of_stock == 1
    assert stats.critical_count == 1
    assert stats.low_count == 1
    assert stats.alert_count == 3
    assert stats.health_pct == pytest.approx(25.0)
    assert stats.coverage_pct == pytest.approx(52.5)
    assert [category.name for category in stats.categories] == ["Lácteos", "Bebidas"]
    assert stats.categories[0].alerts == 2
    assert stats.categories[1].health == pytest.approx(50.0)


def test_build_dashboard_handles_empty_catalog() -> None:
    stats = build_dashboard([])

    assert stats.total_skus == 0
    assert stats.total_units == 0
    assert stats.health_pct == pytest.approx(100.0)
    assert stats.coverage_pct == pytest.approx(0.0)
    assert stats.categories == ()


# ----------------------------------------------------------------- persistence


def test_initialize_seeds_demo_catalog(db: Database) -> None:
    products = db.list_products()

    assert len(products) == 28
    assert len(db.list_movements(limit=50)) == 10
    assert len(db.list_categories()) == 9
    assert db.get_by_barcode("7501000110012") is not None


def test_get_unknown_product_returns_none(db: Database) -> None:
    assert db.get_product(999_999) is None
    assert db.get_by_barcode("00000000") is None


def test_save_product_creates_initial_movement(db: Database) -> None:
    product = db.save_product(_payload())

    assert product.id > 0
    assert product.sku == "TST-001"
    assert product.stock == 10
    movements = db.list_movements(limit=5)
    assert movements[0].sku == "TST-001"
    assert movements[0].kind == "IN"
    assert movements[0].quantity == 10
    assert "Stock inicial" in movements[0].note


def test_save_product_rejects_duplicate_sku(db: Database) -> None:
    db.save_product(_payload())

    with pytest.raises(ValidationError, match="SKU"):
        db.save_product(_payload(barcode="7501234567891"))


def test_save_product_rejects_duplicate_barcode(db: Database) -> None:
    db.save_product(_payload())

    with pytest.raises(ValidationError, match="código de barras"):
        db.save_product(_payload(sku="TST-002"))


def test_update_product_records_stock_adjustment(db: Database) -> None:
    product = db.save_product(_payload(stock="10"))
    payload = _payload(stock="17", product_id=str(product.id))

    updated = db.save_product(payload)

    assert updated.stock == 17
    movement = db.list_movements(limit=1)[0]
    assert movement.kind == "IN"
    assert movement.quantity == 7
    assert movement.note == "Ajuste desde edición de producto"


def test_adjust_stock_records_both_directions(db: Database) -> None:
    product = db.save_product(_payload(stock="10"))

    increased = db.adjust_stock(product.id, 5, "Recepción")
    assert increased.stock == 15

    decreased = db.adjust_stock(product.id, -4, "Venta")
    assert decreased.stock == 11

    movements = db.list_movements(limit=2)
    assert [(item.kind, item.quantity) for item in movements] == [
        ("OUT", 4),
        ("IN", 5),
    ]


def test_adjust_stock_rejects_insufficient_stock(db: Database) -> None:
    product = db.save_product(_payload(stock="3"))
    movements_before = len(db.list_movements(limit=100))

    with pytest.raises(ValidationError, match="Stock insuficiente"):
        db.adjust_stock(product.id, -4, "Venta")

    assert db.get_product(product.id).stock == 3  # type: ignore[union-attr]
    assert len(db.list_movements(limit=100)) == movements_before


def test_adjust_stock_rejects_zero_quantity(db: Database) -> None:
    product = db.save_product(_payload())

    with pytest.raises(ValidationError, match="distinta de cero"):
        db.adjust_stock(product.id, 0, "No-op")


def test_bulk_replenish_is_atomic(db: Database) -> None:
    first = db.save_product(_payload(sku="TST-001", barcode="7501234567890", stock="2"))
    second = db.save_product(_payload(sku="TST-002", barcode="7501234567891", stock="4"))
    movements_before = len(db.list_movements(limit=100))

    count = db.bulk_replenish([(first.id, 10), (second.id, 6)], "Reposición de prueba")

    assert count == 2
    assert db.get_product(first.id).stock == 12  # type: ignore[union-attr]
    assert db.get_product(second.id).stock == 10  # type: ignore[union-attr]
    assert len(db.list_movements(limit=100)) == movements_before + 2


def test_bulk_replenish_rolls_back_missing_product(db: Database) -> None:
    product = db.save_product(_payload(stock="2"))
    movements_before = len(db.list_movements(limit=100))

    with pytest.raises(ValidationError, match="ya no existe"):
        db.bulk_replenish([(product.id, 10), (999_999, 5)])

    assert db.get_product(product.id).stock == 2  # type: ignore[union-attr]
    assert len(db.list_movements(limit=100)) == movements_before


def test_bulk_replenish_rejects_duplicates(db: Database) -> None:
    product = db.save_product(_payload())

    with pytest.raises(ValidationError, match="duplicados"):
        db.bulk_replenish([(product.id, 1), (product.id, 2)])


def test_concurrent_adjustments_are_serialized(db: Database) -> None:
    product = db.save_product(_payload(stock="100"))
    movements_before = len(db.list_movements(limit=100))
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(5):
                db.adjust_stock(product.id, 1, "Incremento concurrente")
        except BaseException as exc:  # pragma: no cover - failure diagnostics
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert db.get_product(product.id).stock == 115  # type: ignore[union-attr]
    assert len(db.list_movements(limit=100)) == movements_before + 15
