"""Smoke tests for the Tkinter shell.

The module is skipped automatically when Tkinter or an X display is unavailable,
so the core suite remains runnable in headless environments.
"""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")

from core.database import Database  # noqa: E402
from core.inventory import Movement  # noqa: E402
from ui.main_window import MainWindow, MovementsView  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""
    with path.open("r", encoding="utf-8") as handle:
        content = json.load(handle)
    assert isinstance(content, dict)
    return content


def _pump(window: MainWindow, predicate: Callable[[], bool], timeout: float = 8.0) -> None:
    """Drive the Tk event loop until a predicate is true or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.root.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for the Tk event loop")


@pytest.fixture()
def window(tmp_path: Path) -> MainWindow:
    """Boot a fully wired MainWindow against a temporary database."""
    config = _load_json(PROJECT_ROOT / "configs" / "default.json")
    theme = _load_json(PROJECT_ROOT / "configs" / "theme.json")
    database = Database(tmp_path / "ui-smoke.db")
    database.initialize()

    try:
        app = MainWindow(database, config, theme)
    except tk.TclError as exc:  # pragma: no cover - headless environments
        database.close()
        pytest.skip(f"Tk display unavailable: {exc}")

    app.root.withdraw()
    try:
        yield app
    finally:
        app.close()
        database.close()


def test_shell_exposes_all_operational_views(window: MainWindow) -> None:
    assert set(window.views) == {
        "dashboard",
        "inventory",
        "movements",
        "alerts",
        "system",
    }
    assert set(window.nav_buttons) == {
        "dashboard",
        "inventory",
        "movements",
        "alerts",
        "system",
    }
    assert window._current_view == "dashboard"

    window.show_view("inventory")
    assert window._current_view == "inventory"
    assert window.view_title.cget("text") == "Inventario"

    window.show_view("alerts")
    assert window._current_view == "alerts"
    assert window.view_title.cget("text") == "Alertas de stock"

    window.show_view("system")
    assert window._current_view == "system"
    assert window.view_title.cget("text") == "Sistema"


def test_theme_resolves_palette_keys_and_literal_colors(window: MainWindow) -> None:
    assert window.theme.c("accent") == "#37E5A5"
    assert window.theme.c("#04110B") == "#04110B"
    assert window.theme.c("missing-key") == "#FF00FF"


def test_worker_pipeline_loads_demo_catalog(window: MainWindow) -> None:
    window.refresh_data()
    _pump(window, lambda: bool(window._products_cache) and not window._loading)

    assert len(window._products_cache) == 28
    assert len(window._alerts) == 8
    assert window.nav_buttons["alerts"].badge.cget("text") == "8"
    assert "28" in window.inventory_view.summary_label.cget("text")
    assert window.system_view.catalog_label.cget("text") == "28 SKU"
    assert window.system_view.alerts_label.cget("text") == "8"


def test_inventory_filters_by_query_and_category(window: MainWindow) -> None:
    window.refresh_data()
    _pump(window, lambda: bool(window._products_cache) and not window._loading)

    window.search_box.set_text("agua")
    window.apply_inventory_filter()
    assert len(window._inventory_filtered) == 1
    assert window._inventory_filtered[0].sku == "BEB-001"

    window.search_box.set_text("")
    window.inventory_view.category_var.set("Lácteos")
    window.apply_inventory_filter()
    assert window._inventory_filtered
    assert all(product.category == "Lácteos" for product in window._inventory_filtered)


def test_movement_date_filter_uses_a_rolling_cutoff(window: MainWindow) -> None:
    window.refresh_data()
    _pump(window, lambda: bool(window._products_cache) and not window._loading)

    old = Movement(
        id=999_999,
        sku="TST-OLD",
        product_name="Movimiento antiguo",
        kind="OUT",
        quantity=1,
        note="Prueba de rango",
        created_at=datetime.now() - timedelta(days=45),
    )
    window._movements_cache.append(old)
    window.show_view("movements")

    window.movements_view.range_var.set(MovementsView.LAST_MONTH)
    window.apply_movement_filter()
    assert all(item.id != old.id for item in window._movements_filtered)

    window.movements_view.range_var.set(MovementsView.ALL_TIME)
    window.apply_movement_filter()
    assert any(item.id == old.id for item in window._movements_filtered)


def test_inventory_export_includes_barcode(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.refresh_data()
    _pump(window, lambda: bool(window._products_cache) and not window._loading)
    destination = tmp_path / "inventario.csv"
    monkeypatch.setattr(
        "ui.main_window.filedialog.asksaveasfilename",
        lambda **_kwargs: str(destination),
    )

    window.export_inventory_csv()

    with destination.open("r", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))
    assert header[:2] == ["SKU", "Código de barras"]
