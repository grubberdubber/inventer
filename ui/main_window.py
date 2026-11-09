"""Primary Tkinter window, shell layout and operational views.

The window is the only component that coordinates data loading. Every query
and mutation runs in the executor and returns to the Tk main loop through an
``after`` poll, so the interface never blocks.
"""

from __future__ import annotations

import contextlib
import csv
import logging
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from tkinter import filedialog, ttk
from typing import Any

from core.database import Database
from core.inventory import (
    DashboardStats,
    Movement,
    Product,
    build_dashboard,
    classify_stock,
    reorder_quantity,
    sort_products,
)
from ui.dialogs import (
    BarcodeScanDialog,
    ConfirmDialog,
    ProductDialog,
    RestockDialog,
    SaleDialog,
)
from ui.widgets import (
    ActionButton,
    Card,
    DataTable,
    KpiCard,
    Meter,
    NavButton,
    SearchBox,
    TableColumn,
    Theme,
    ToastManager,
    configure_styles,
    format_date_es,
    format_money,
    format_units,
    pill,
    relative_time,
    status_tag,
    truncate,
)

logger = logging.getLogger("inventer.ui")

ALL_CATEGORIES = "Todas las categorías"


def _panel_heading(
    parent: tk.Misc,
    theme: Theme,
    *,
    kicker: str,
    kicker_color: str,
    title: str,
) -> tk.Frame:
    """Compose the compact panel heading used across the dashboard."""
    frame = tk.Frame(parent, bg=theme.c("surface"))
    left = tk.Frame(frame, bg=theme.c("surface"))
    left.pack(side="left", anchor="w")
    tk.Label(
        left,
        text=kicker,
        bg=theme.c("surface"),
        fg=kicker_color,
        font=theme.font("micro", "bold"),
        anchor="w",
    ).pack(anchor="w")
    tk.Label(
        left,
        text=title,
        bg=theme.c("surface"),
        fg=theme.c("text"),
        font=theme.font("title", "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(2, 0))
    return frame


def _turn_name(moment: datetime) -> str:
    """Return the operational shift for the current time."""
    hour = moment.hour
    if 6 <= hour < 14:
        return "Matutino"
    if 14 <= hour < 22:
        return "Vespertino"
    return "Nocturno"


class DashboardView(tk.Frame):
    """Operational overview: KPIs, critical stock, category health, activity."""

    def __init__(self, master: tk.Misc, app: MainWindow) -> None:
        super().__init__(master, bg=app.theme.c("bg"))
        self.app = app
        self.theme = app.theme
        self._alert_map: dict[str, Product] = {}
        theme = app.theme

        self.grid_columnconfigure(0, weight=3, uniform="dash")
        self.grid_columnconfigure(1, weight=2, uniform="dash")
        self.grid_rowconfigure(1, weight=1)

        kpi_row = tk.Frame(self, bg=theme.c("bg"))
        kpi_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        for column in range(4):
            kpi_row.grid_columnconfigure(column, weight=1, uniform="kpi")

        self.kpi_skus = KpiCard(kpi_row, theme, label="SKU ACTIVOS", accent=theme.c("accent"))
        self.kpi_units = KpiCard(kpi_row, theme, label="UNIDADES EN STOCK", accent=theme.c("info"))
        self.kpi_value = KpiCard(kpi_row, theme, label="VALOR DE INVENTARIO", accent=theme.c("accent"))
        self.kpi_alerts = KpiCard(kpi_row, theme, label="ALERTAS DE STOCK", accent=theme.c("danger"))
        for index, card in enumerate(
            (self.kpi_skus, self.kpi_units, self.kpi_value, self.kpi_alerts)
        ):
            card.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0, 12) if index < 3 else 0,
            )

        alerts_card = Card(self, theme, padding=16)
        alerts_card.grid(row=1, column=0, sticky="nsew", padx=(0, 7))
        alerts_body = alerts_card.body

        heading = _panel_heading(
            alerts_body,
            theme,
            kicker="ALERTA OPERATIVA",
            kicker_color=theme.c("danger"),
            title="Reposición requerida",
        )
        heading.pack(fill="x")

        self.alert_pill = pill(
            heading,
            theme,
            "0 ACTIVAS",
            fg=theme.c("danger"),
            bg=theme.c("danger_dim"),
        )
        self.alert_pill.pack(side="right")
        ActionButton(
            heading,
            theme,
            "VER TODAS",
            lambda: self.app.show_view("alerts"),
            variant="ghost",
            compact=True,
        ).pack(side="right", padx=(0, 8))

        alert_columns = (
            TableColumn("product", "PRODUCTO", 210, stretch=True),
            TableColumn("sku", "SKU", 90),
            TableColumn("stock", "STOCK", 60, "e"),
            TableColumn("min", "MÍN.", 50, "e"),
            TableColumn("status", "ESTADO", 86, "center"),
        )
        self.alert_table = DataTable(
            alerts_body,
            theme,
            alert_columns,
            height=6,
            empty_text="Sin alertas activas · inventario dentro de umbrales",
            on_activate=self._restock_row,
        )
        self.alert_table.pack(fill="both", expand=True, pady=(10, 0))

        right = tk.Frame(self, bg=theme.c("bg"))
        right.grid(row=1, column=1, sticky="nsew", padx=(7, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=3)
        right.grid_rowconfigure(1, weight=2)

        health_card = Card(right, theme, padding=16)
        health_card.grid(row=0, column=0, sticky="nsew", pady=(0, 14))
        health_body = health_card.body
        health_heading = _panel_heading(
            health_body,
            theme,
            kicker="TELEMETRÍA",
            kicker_color=theme.c("info"),
            title="Salud por categoría",
        )
        health_heading.pack(fill="x")
        self.health_pill = pill(
            health_heading,
            theme,
            "0% COBERTURA",
            fg=theme.c("accent"),
            bg=theme.c("accent_dim"),
        )
        self.health_pill.pack(side="right")
        self.health_rows = tk.Frame(health_body, bg=theme.c("surface"))
        self.health_rows.pack(fill="both", expand=True, pady=(8, 0))

        activity_card = Card(right, theme, padding=16)
        activity_card.grid(row=1, column=0, sticky="nsew")
        activity_body = activity_card.body
        activity_heading = _panel_heading(
            activity_body,
            theme,
            kicker="FLUJO RECIENTE",
            kicker_color=theme.c("accent"),
            title="Actividad",
        )
        activity_heading.pack(fill="x")
        ActionButton(
            activity_heading,
            theme,
            "VER HISTORIAL",
            lambda: self.app.show_view("movements"),
            variant="ghost",
            compact=True,
        ).pack(side="right")
        pill(
            activity_heading,
            theme,
            "LOCAL",
            fg=theme.c("info"),
            bg=theme.c("info_dim"),
        ).pack(side="right", padx=(0, 8))
        self.activity_rows = tk.Frame(activity_body, bg=theme.c("surface"))
        self.activity_rows.pack(fill="both", expand=True, pady=(4, 0))

    def set_data(
        self,
        stats: DashboardStats,
        alerts: Sequence[Product],
        movements: Sequence[Movement],
    ) -> None:
        """Refresh every dashboard surface from immutable snapshots."""
        theme = self.theme
        currency = self.app.currency

        self.kpi_skus.set(
            format_units(stats.total_skus),
            f"{len(stats.categories)} categorías monitoreadas",
        )
        self.kpi_units.set(
            format_units(stats.total_units),
            f"Cobertura {stats.coverage_pct:.0f}% de la capacidad",
        )
        self.kpi_value.set(
            format_money(stats.inventory_value, currency),
            "Valorizado a precio de venta",
        )
        self.kpi_alerts.set(
            format_units(stats.alert_count),
            (
                f"{stats.out_of_stock} agotado"
                f"{'s' if stats.out_of_stock != 1 else ''} · "
                f"{stats.critical_count + stats.low_count} bajo mínimo"
                if stats.alert_count
                else "Inventario dentro de umbrales"
            ),
            value_color=theme.c("danger") if stats.alert_count else theme.c("accent"),
            caption_color=theme.c("danger") if stats.alert_count else theme.c("text_dim"),
        )

        self._alert_map = {}
        rows = []
        for index, product in enumerate(alerts[:6]):
            status = classify_stock(product.stock, product.min_stock, self.app.alert_factor)
            self._alert_map[str(product.id)] = product
            tags = [status_tag(status)]
            if index % 2:
                tags.append("stripe")
            rows.append(
                (
                    str(product.id),
                    (
                        truncate(product.name, 30),
                        product.sku,
                        format_units(product.stock),
                        format_units(product.min_stock),
                        status.value,
                    ),
                    tags,
                )
            )
        self.alert_table.set_rows(rows)

        if alerts:
            self.alert_pill.configure(
                text=f"{len(alerts)} ACTIVAS",
                fg=theme.c("danger"),
                bg=theme.c("danger_dim"),
                highlightbackground=theme.c("danger_dim"),
            )
        else:
            self.alert_pill.configure(
                text="SIN ALERTAS",
                fg=theme.c("accent"),
                bg=theme.c("accent_dim"),
                highlightbackground=theme.c("accent_dim"),
            )

        self.health_pill.configure(
            text=f"{stats.health_pct:.0f}% SALUDABLE",
            fg=(
                theme.c("accent")
                if stats.health_pct >= 75
                else theme.c("warning")
                if stats.health_pct >= 50
                else theme.c("danger")
            ),
        )
        self._fill_health(stats)
        self._fill_activity(movements)

    def _fill_health(self, stats: DashboardStats) -> None:
        theme = self.theme
        for child in self.health_rows.winfo_children():
            child.destroy()

        if not stats.categories:
            tk.Label(
                self.health_rows,
                text="Sin datos de categoría",
                bg=theme.c("surface"),
                fg=theme.c("text_faint"),
                font=theme.font("caption"),
            ).pack(anchor="w", pady=8)
            return

        for category in stats.categories[:5]:
            if category.health >= 75:
                color = theme.c("accent")
            elif category.health >= 50:
                color = theme.c("warning")
            else:
                color = theme.c("danger")

            row = tk.Frame(self.health_rows, bg=theme.c("surface"))
            row.pack(fill="x", pady=2)
            tk.Label(
                row,
                text=truncate(category.name, 17),
                bg=theme.c("surface"),
                fg=theme.c("text_dim"),
                font=theme.font("micro"),
                width=17,
                anchor="w",
            ).pack(side="left")
            tk.Label(
                row,
                text=f"{category.health:.0f}%",
                bg=theme.c("surface"),
                fg=color,
                font=theme.font("micro", "bold", mono=True),
                width=5,
                anchor="e",
            ).pack(side="right")
            meter = Meter(row, theme, height=6, color=color)
            meter.pack(side="left", fill="x", expand=True, padx=8, pady=3)
            meter.set(category.health)

        if len(stats.categories) > 5:
            tk.Label(
                self.health_rows,
                text=(
                    f"{len(stats.categories) - 5} categorías adicionales · "
                    "ordenadas por riesgo"
                ),
                bg=theme.c("surface"),
                fg=theme.c("text_faint"),
                font=theme.font("micro"),
                anchor="w",
            ).pack(fill="x", pady=(4, 0))

    def _fill_activity(self, movements: Sequence[Movement]) -> None:
        theme = self.theme
        for child in self.activity_rows.winfo_children():
            child.destroy()

        if not movements:
            tk.Label(
                self.activity_rows,
                text="Sin movimientos registrados",
                bg=theme.c("surface"),
                fg=theme.c("text_faint"),
                font=theme.font("caption"),
            ).pack(anchor="w", pady=8)
            return

        for movement in movements[:2]:
            incoming = movement.kind == "IN"
            color = theme.c("accent") if incoming else theme.c("danger")
            dim = theme.c("accent_dim") if incoming else theme.c("danger_dim")

            row = tk.Frame(self.activity_rows, bg=theme.c("surface"))
            row.pack(fill="x", pady=4)

            tk.Label(
                row,
                text=movement.kind,
                bg=dim,
                fg=color,
                font=theme.font("micro", "bold"),
                padx=5,
                pady=2,
            ).pack(side="left", anchor="n")

            center = tk.Frame(row, bg=theme.c("surface"))
            center.pack(side="left", fill="x", expand=True, padx=8)
            tk.Label(
                center,
                text=truncate(movement.product_name, 26),
                bg=theme.c("surface"),
                fg=theme.c("text"),
                font=theme.font("micro", "bold"),
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                center,
                text=truncate(movement.note, 34),
                bg=theme.c("surface"),
                fg=theme.c("text_faint"),
                font=theme.font("micro"),
                anchor="w",
            ).pack(fill="x")

            right = tk.Frame(row, bg=theme.c("surface"))
            right.pack(side="right", anchor="n")
            tk.Label(
                right,
                text=("+" if incoming else "−") + format_units(movement.quantity),
                bg=theme.c("surface"),
                fg=color,
                font=theme.font("micro", "bold", mono=True),
                anchor="e",
            ).pack(anchor="e")
            tk.Label(
                right,
                text=relative_time(movement.created_at),
                bg=theme.c("surface"),
                fg=theme.c("text_faint"),
                font=theme.font("micro"),
                anchor="e",
            ).pack(anchor="e")

    def _restock_row(self, item_id: str) -> None:
        product = self._alert_map.get(item_id)
        if product is not None:
            self.app.restock_product(product)


class InventoryView(tk.Frame):
    """Full catalog with search, category/alert filters and row actions."""

    def __init__(self, master: tk.Misc, app: MainWindow) -> None:
        super().__init__(master, bg=app.theme.c("bg"))
        self.app = app
        self.theme = app.theme
        theme = app.theme

        self.category_var = tk.StringVar(value=ALL_CATEGORIES)
        self.alerts_only = tk.BooleanVar(value=False)

        toolbar = tk.Frame(self, bg=theme.c("bg"))
        toolbar.pack(fill="x", pady=(0, 14))

        self.category_combo = ttk.Combobox(
            toolbar,
            textvariable=self.category_var,
            values=[ALL_CATEGORIES],
            state="readonly",
            style="Dark.TCombobox",
            width=20,
        )
        self.category_combo.pack(side="left")
        self.category_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self.app.apply_inventory_filter()
        )

        ttk.Checkbutton(
            toolbar,
            text="Solo alertas",
            variable=self.alerts_only,
            command=self.app.apply_inventory_filter,
            style="Dark.TCheckbutton",
        ).pack(side="left", padx=12)

        ActionButton(
            toolbar,
            theme,
            "LIMPIAR",
            self.clear_filters,
            variant="ghost",
            compact=True,
        ).pack(side="left")

        self.new_button = ActionButton(
            toolbar,
            theme,
            "+ NUEVO PRODUCTO",
            app.open_new_product,
            variant="primary",
            compact=True,
        )
        self.new_button.pack(side="right")

        self.edit_button = ActionButton(
            toolbar,
            theme,
            "EDITAR",
            self._edit_selected,
            variant="ghost",
            compact=True,
        )
        self.edit_button.pack(side="right", padx=(0, 8))

        self.sale_button = ActionButton(
            toolbar,
            theme,
            "SALIDA",
            self._sale_selected,
            variant="ghost",
            compact=True,
        )
        self.sale_button.pack(side="right", padx=(0, 8))

        self.restock_button = ActionButton(
            toolbar,
            theme,
            "REPONER",
            self._restock_selected,
            variant="ghost",
            compact=True,
        )
        self.restock_button.pack(side="right", padx=(0, 8))

        ActionButton(
            toolbar,
            theme,
            "EXPORTAR",
            app.export_inventory_csv,
            variant="ghost",
            compact=True,
        ).pack(side="right", padx=(0, 8))

        ActionButton(
            toolbar,
            theme,
            "ACTUALIZAR",
            app.refresh_data,
            variant="ghost",
            compact=True,
        ).pack(side="right", padx=(0, 8))

        card = Card(self, theme, padding=0)
        card.pack(fill="both", expand=True)

        table_area = tk.Frame(card.body, bg=theme.c("surface"))
        table_area.pack(fill="both", expand=True, padx=16, pady=(14, 8))

        columns = (
            TableColumn("sku", "SKU", 104),
            TableColumn("product", "PRODUCTO", 250, stretch=True),
            TableColumn("category", "CATEGORÍA", 140),
            TableColumn("stock", "STOCK", 64, "e"),
            TableColumn("min", "MÍN.", 56, "e"),
            TableColumn("price", "PRECIO", 90, "e"),
            TableColumn("value", "VALOR", 98, "e"),
            TableColumn("status", "ESTADO", 92, "center"),
        )
        self.table = DataTable(
            table_area,
            theme,
            columns,
            height=12,
            empty_text="Ningún producto coincide con los filtros actuales",
            on_activate=self._edit_row,
            on_select=self._on_select,
        )
        self.table.pack(fill="both", expand=True)

        footer = tk.Frame(card.body, bg=theme.c("surface"))
        footer.pack(fill="x", padx=16, pady=(0, 12))
        self.summary_label = tk.Label(
            footer,
            text="Esperando sincronización del catálogo…",
            bg=theme.c("surface"),
            fg=theme.c("text_dim"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.summary_label.pack(side="left")
        tk.Label(
            footer,
            text="F5 ACTUALIZAR · CTRL+F BUSCAR · DOBLE CLIC EDITAR",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="e",
        ).pack(side="right")

        self.set_actions_enabled(False)

    def set_categories(self, categories: Sequence[str]) -> None:
        """Refresh the category filter while preserving the selection."""
        values = [ALL_CATEGORIES, *categories]
        self.category_combo.configure(values=values)
        if self.category_var.get() not in values:
            self.category_var.set(ALL_CATEGORIES)

    def set_products(self, products: Sequence[Product], total: int) -> None:
        """Render the filtered catalog snapshot."""
        rows = []
        units = 0
        value = 0.0
        for index, product in enumerate(products):
            status = classify_stock(product.stock, product.min_stock, self.app.alert_factor)
            units += product.stock
            value += product.stock * product.price
            tags = [status_tag(status)]
            if index % 2:
                tags.append("stripe")
            rows.append(
                (
                    str(product.id),
                    (
                        product.sku,
                        product.name,
                        product.category,
                        format_units(product.stock),
                        format_units(product.min_stock),
                        format_money(product.price, self.app.currency),
                        format_money(product.stock * product.price, self.app.currency),
                        status.value,
                    ),
                    tags,
                )
            )
        self.table.set_rows(rows)
        self.summary_label.configure(
            text=(
                f"{len(products)} de {total} SKU · {format_units(units)} unidades · "
                f"{format_money(value, self.app.currency)}"
            )
        )
        self._on_select(self.table.selected_id())

    def clear_filters(self) -> None:
        """Reset every catalog filter."""
        self.category_var.set(ALL_CATEGORIES)
        self.alerts_only.set(False)
        self.app.search_box.set_text("")
        self.app.apply_inventory_filter()

    def _on_select(self, item_id: str | None) -> None:
        self.set_actions_enabled(item_id is not None)

    def set_actions_enabled(self, enabled: bool) -> None:
        """Toggle the selection-dependent row actions."""
        self.edit_button.set_enabled(enabled)
        self.restock_button.set_enabled(enabled)
        self.sale_button.set_enabled(enabled)

    def _edit_row(self, item_id: str) -> None:
        self.app.edit_product_by_id(item_id)

    def _edit_selected(self) -> None:
        item_id = self.table.selected_id()
        if item_id:
            self.app.edit_product_by_id(item_id)

    def _restock_selected(self) -> None:
        item_id = self.table.selected_id()
        if item_id:
            self.app.restock_alert_by_id(item_id)
        else:
            self.app.toasts.show("Selecciona un producto para reponer.", "warning")

    def _sale_selected(self) -> None:
        item_id = self.table.selected_id()
        if item_id:
            self.app.sell_product_by_id(item_id)
        else:
            self.app.toasts.show("Selecciona un producto para registrar la salida.", "warning")


class AlertsView(tk.Frame):
    """Prioritized replenishment queue with severity summary tiles."""

    def __init__(self, master: tk.Misc, app: MainWindow) -> None:
        super().__init__(master, bg=app.theme.c("bg"))
        self.app = app
        self.theme = app.theme
        theme = app.theme
        self._alert_map: dict[str, Product] = {}

        summary = tk.Frame(self, bg=theme.c("bg"))
        summary.pack(fill="x", pady=(0, 14))
        for column in range(3):
            summary.grid_columnconfigure(column, weight=1, uniform="alert-kpi")

        self.kpi_out = KpiCard(
            summary,
            theme,
            label="AGOTADOS",
            accent=theme.c("danger"),
            compact=True,
        )
        self.kpi_critical = KpiCard(
            summary,
            theme,
            label="CRÍTICOS",
            accent=theme.c("warning"),
            compact=True,
        )
        self.kpi_low = KpiCard(
            summary,
            theme,
            label="BAJO MÍNIMO",
            accent=theme.c("info"),
            compact=True,
        )
        for index, card in enumerate((self.kpi_out, self.kpi_critical, self.kpi_low)):
            card.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0, 12) if index < 2 else 0,
            )

        card = Card(self, theme, padding=16)
        card.pack(fill="both", expand=True)
        body = card.body

        heading = _panel_heading(
            body,
            theme,
            kicker="COLA DE REPOSICIÓN",
            kicker_color=theme.c("danger"),
            title="Prioridad operativa",
        )
        heading.pack(fill="x")

        self.restock_button = ActionButton(
            heading,
            theme,
            "REPONER SELECCIONADO",
            self._restock_selected,
            variant="primary",
            compact=True,
        )
        self.restock_button.pack(side="right")
        self.bulk_button = ActionButton(
            heading,
            theme,
            "REPONER TODO",
            app.open_bulk_restock,
            variant="ghost",
            compact=True,
        )
        self.bulk_button.pack(side="right", padx=(0, 8))
        ActionButton(
            heading,
            theme,
            "ACTUALIZAR",
            app.refresh_data,
            variant="ghost",
            compact=True,
        ).pack(side="right", padx=(0, 8))

        hint = tk.Frame(body, bg=theme.c("surface"))
        hint.pack(fill="x", pady=(8, 6))
        tk.Label(
            hint,
            text="●",
            bg=theme.c("surface"),
            fg=theme.c("warning"),
            font=theme.font("micro"),
        ).pack(side="left")
        tk.Label(
            hint,
            text=(
                "  La cola se ordena por severidad: agotados, críticos y bajo mínimo. "
                "El ingreso sugerido respeta la capacidad máxima del producto."
            ),
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        ).pack(side="left")

        columns = (
            TableColumn("product", "PRODUCTO", 226, stretch=True),
            TableColumn("category", "CATEGORÍA", 128),
            TableColumn("sku", "SKU", 94),
            TableColumn("stock", "STOCK", 62, "e"),
            TableColumn("min", "MÍN.", 56, "e"),
            TableColumn("target", "OBJETIVO", 80, "e"),
            TableColumn("suggested", "SUGERIDO", 86, "e"),
            TableColumn("status", "ESTADO", 96, "center"),
        )
        self.table = DataTable(
            body,
            theme,
            columns,
            height=8,
            empty_text="Sin reposiciones pendientes · operación estable",
            on_activate=self._restock_row,
            on_select=self._on_select,
        )
        self.table.pack(fill="both", expand=True, pady=(4, 0))

        footer = tk.Frame(body, bg=theme.c("surface"))
        footer.pack(fill="x", pady=(8, 0))
        self.summary_label = tk.Label(
            footer,
            text="Esperando análisis de umbrales…",
            bg=theme.c("surface"),
            fg=theme.c("text_dim"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.summary_label.pack(side="left")
        tk.Label(
            footer,
            text="DOBLE CLIC PARA REPONER",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
        ).pack(side="right")

        self.set_actions_enabled(False)
        self.bulk_button.set_enabled(False)

    def set_data(self, stats: DashboardStats, alerts: Sequence[Product]) -> None:
        """Refresh summary tiles, queue and footer."""
        theme = self.theme
        self.kpi_out.set(
            format_units(stats.out_of_stock),
            "Reposición inmediata",
            value_color=theme.c("danger") if stats.out_of_stock else theme.c("text"),
            caption_color=theme.c("danger") if stats.out_of_stock else None,
        )
        self.kpi_critical.set(
            format_units(stats.critical_count),
            "Umbral mínimo alcanzado",
            value_color=theme.c("warning") if stats.critical_count else theme.c("text"),
            caption_color=theme.c("warning") if stats.critical_count else None,
        )
        self.kpi_low.set(
            format_units(stats.low_count),
            "Vigilancia preventiva",
            value_color=theme.c("info") if stats.low_count else theme.c("text"),
            caption_color=theme.c("info") if stats.low_count else None,
        )

        self._alert_map = {}
        rows = []
        suggested_total = 0
        for index, product in enumerate(alerts):
            status = classify_stock(product.stock, product.min_stock, self.app.alert_factor)
            suggested = reorder_quantity(product)
            suggested_total += suggested
            self._alert_map[str(product.id)] = product
            tags = [status_tag(status)]
            if index % 2:
                tags.append("stripe")
            rows.append(
                (
                    str(product.id),
                    (
                        truncate(product.name, 32),
                        product.category,
                        product.sku,
                        format_units(product.stock),
                        format_units(product.min_stock),
                        format_units(product.stock + suggested),
                        format_units(suggested),
                        status.value,
                    ),
                    tags,
                )
            )
        self.table.set_rows(rows)
        self._on_select(self.table.selected_id())
        self.bulk_button.set_enabled(bool(alerts))
        self.summary_label.configure(
            text=(
                f"{len(alerts)} productos requieren reposición · "
                f"{format_units(suggested_total)} unidades sugeridas"
                if alerts
                else "Ningún producto requiere reposición en este ciclo"
            )
        )

    def _on_select(self, item_id: str | None) -> None:
        self.set_actions_enabled(item_id is not None)

    def set_actions_enabled(self, enabled: bool) -> None:
        """Toggle the replenishment action."""
        self.restock_button.set_enabled(enabled)

    def _restock_row(self, item_id: str) -> None:
        product = self._alert_map.get(item_id)
        if product is not None:
            self.app.restock_product(product)

    def _restock_selected(self) -> None:
        item_id = self.table.selected_id()
        if item_id:
            self._restock_row(item_id)
        else:
            self.app.toasts.show("Selecciona un producto de la cola.", "warning")


class MovementsView(tk.Frame):
    """Filterable audit trail for every stock movement."""

    ALL = "Todos los movimientos"
    INCOMING = "Entradas"
    OUTGOING = "Salidas"

    def __init__(self, master: tk.Misc, app: MainWindow) -> None:
        super().__init__(master, bg=app.theme.c("bg"))
        self.app = app
        self.theme = app.theme
        theme = app.theme
        self.kind_var = tk.StringVar(value=self.ALL)

        toolbar = tk.Frame(self, bg=theme.c("bg"))
        toolbar.pack(fill="x", pady=(0, 14))

        self.kind_combo = ttk.Combobox(
            toolbar,
            textvariable=self.kind_var,
            values=[self.ALL, self.INCOMING, self.OUTGOING],
            state="readonly",
            style="Dark.TCombobox",
            width=22,
        )
        self.kind_combo.pack(side="left")
        self.kind_combo.bind(
            "<<ComboboxSelected>>", lambda _event: app.apply_movement_filter()
        )

        ActionButton(
            toolbar,
            theme,
            "LIMPIAR",
            self.clear_filters,
            variant="ghost",
            compact=True,
        ).pack(side="left", padx=(12, 0))

        pill(
            toolbar,
            theme,
            "AUDITORÍA LOCAL",
            fg=theme.c("info"),
            bg=theme.c("info_dim"),
        ).pack(side="left", padx=(14, 0))

        ActionButton(
            toolbar,
            theme,
            "EXPORTAR CSV",
            app.export_movements_csv,
            variant="ghost",
            compact=True,
        ).pack(side="right")
        ActionButton(
            toolbar,
            theme,
            "ACTUALIZAR",
            app.refresh_data,
            variant="ghost",
            compact=True,
        ).pack(side="right", padx=(0, 8))

        card = Card(self, theme, padding=0)
        card.pack(fill="both", expand=True)

        table_area = tk.Frame(card.body, bg=theme.c("surface"))
        table_area.pack(fill="both", expand=True, padx=16, pady=(14, 8))

        columns = (
            TableColumn("date", "FECHA / HORA", 126),
            TableColumn("kind", "TIPO", 82),
            TableColumn("product", "PRODUCTO", 220, stretch=True),
            TableColumn("sku", "SKU", 94),
            TableColumn("qty", "CANTIDAD", 82, "e"),
            TableColumn("note", "MOTIVO", 300, stretch=True),
        )
        self.table = DataTable(
            table_area,
            theme,
            columns,
            height=11,
            empty_text="Sin movimientos para los filtros actuales",
        )
        self.table.pack(fill="both", expand=True)

        footer = tk.Frame(card.body, bg=theme.c("surface"))
        footer.pack(fill="x", padx=16, pady=(0, 12))
        self.summary_label = tk.Label(
            footer,
            text="Esperando historial de auditoría…",
            bg=theme.c("surface"),
            fg=theme.c("text_dim"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.summary_label.pack(side="left")
        tk.Label(
            footer,
            text="F5 ACTUALIZAR · CTRL+F BUSCAR · CTRL+E EXPORTAR",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
        ).pack(side="right")

    def set_data(self, movements: Sequence[Movement], total: int) -> None:
        """Render the filtered audit history."""
        rows = []
        incoming = 0
        outgoing = 0
        for index, movement in enumerate(movements):
            is_incoming = movement.kind == "IN"
            if is_incoming:
                incoming += movement.quantity
            else:
                outgoing += movement.quantity
            tags = ["in" if is_incoming else "out"]
            if index % 2:
                tags.append("stripe")
            rows.append(
                (
                    str(movement.id),
                    (
                        movement.created_at.strftime("%d/%m/%Y %H:%M"),
                        "ENTRADA" if is_incoming else "SALIDA",
                        movement.product_name,
                        movement.sku,
                        ("+" if is_incoming else "−") + format_units(movement.quantity),
                        movement.note,
                    ),
                    tags,
                )
            )
        self.table.set_rows(rows)
        self.summary_label.configure(
            text=(
                f"{len(movements)} de {total} movimientos · "
                f"+{format_units(incoming)} / −{format_units(outgoing)} unidades"
            )
        )

    def clear_filters(self) -> None:
        """Reset the movement type and global search query."""
        self.kind_var.set(self.ALL)
        self.app.search_box.set_text("")
        self.app.apply_movement_filter()


class MainWindow:
    """Application shell that coordinates data, views and worker threads."""

    def __init__(
        self,
        database: Database,
        config: Mapping[str, Any],
        theme_spec: Mapping[str, Any],
    ) -> None:
        """Compose the full interface.

        Args:
            database: Initialized repository.
            config: Parsed system configuration.
            theme_spec: Parsed visual theme.
        """
        self.db = database
        self.config = config
        inventory_config = config.get("inventory", {})
        ui_config = config.get("ui", {})
        self.currency = str(inventory_config.get("currency", "$"))
        self.alert_factor = float(inventory_config.get("low_stock_factor", 1.5))
        self.units = list(inventory_config.get("units", ["Unidad"]))
        self.toast_ms = int(ui_config.get("toast_ms", 2800))
        self.search_debounce_ms = int(ui_config.get("search_debounce_ms", 260))
        self.version = str(config.get("version", "1.0.0"))
        self.workers = int(ui_config.get("worker_threads", 4))

        self.root = tk.Tk()
        self.theme = Theme(theme_spec, self.root)
        self._apply_window(theme_spec)

        configure_styles(self.root, self.theme)

        self._products_cache: list[Product] = []
        self._categories: list[str] = []
        self._alerts: list[Product] = []
        self._movements_cache: list[Movement] = []
        self._inventory_filtered: list[Product] = []
        self._movements_filtered: list[Movement] = []
        self._loading = False
        self._refresh_again = False
        self._alive = True
        self._search_after: str | None = None
        self._clock_after: str | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=self.workers,
            thread_name_prefix="inventer",
        )
        self._turn = _turn_name(datetime.now())

        self.root.report_callback_exception = self._on_tk_exception
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_shell()
        self._build_views()
        self.toasts = ToastManager(self.content, self.theme)
        self.show_view("dashboard")
        self._clock_tick()
        self._bind_shortcuts()
        self.root.after(80, self.refresh_data)

        logger.info(
            "Main window initialized db=%s workers=%s", self.db.path, self.workers
        )

    # --------------------------------------------------------------- window

    def _apply_window(self, theme_spec: Mapping[str, Any]) -> None:
        window_spec = theme_spec.get("window", {})
        title = str(window_spec.get("title", "INVENTER"))
        geometry = str(window_spec.get("geometry", "1360x740"))
        try:
            width_text, height_text = geometry.lower().split("x")
            width = int(width_text)
            height = int(height_text)
        except ValueError:
            width, height = 1360, 740

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 8)

        self.root.title(title)
        self.root.configure(bg=self.theme.c("bg"))
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(
            int(window_spec.get("min_width", 1180)),
            int(window_spec.get("min_height", 680)),
        )

    def _build_shell(self) -> None:
        theme = self.theme
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        sidebar_width = int(theme.layout.get("sidebar_width", 236))
        self.sidebar = tk.Frame(self.root, bg=theme.c("sidebar"), width=sidebar_width)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        workspace = tk.Frame(self.root, bg=theme.c("bg"))
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.grid_rowconfigure(1, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        topbar_height = int(theme.layout.get("topbar_height", 74))
        self.topbar = tk.Frame(workspace, bg=theme.c("bg"), height=topbar_height)
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.pack_propagate(False)
        self._build_topbar()

        self.content = tk.Frame(workspace, bg=theme.c("bg"))
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self._build_statusbar(workspace)

    def _build_sidebar(self) -> None:
        theme = self.theme
        sidebar = self.sidebar

        brand = tk.Frame(sidebar, bg=theme.c("sidebar"), height=74)
        brand.pack(fill="x")
        brand.pack_propagate(False)

        logo = tk.Canvas(
            brand,
            width=36,
            height=36,
            bg=theme.c("sidebar"),
            highlightthickness=0,
            bd=0,
        )
        logo.pack(side="left", padx=(18, 10), pady=19)
        logo.create_polygon(
            18, 1, 34, 10, 34, 26, 18, 35, 2, 26, 2, 10,
            fill=theme.c("accent"),
            outline="",
        )
        logo.create_text(
            18,
            18,
            text="I",
            fill="#04110B",
            font=theme.font("title", "bold"),
        )

        brand_text = tk.Frame(brand, bg=theme.c("sidebar"))
        brand_text.pack(side="left", fill="y", pady=14)
        tk.Label(
            brand_text,
            text="INVENTER",
            bg=theme.c("sidebar"),
            fg=theme.c("text"),
            font=theme.font("title", "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            brand_text,
            text="SUPERMARKET CORE",
            bg=theme.c("sidebar"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        tk.Frame(sidebar, bg=theme.c("border_soft"), height=1).pack(fill="x")

        tk.Label(
            sidebar,
            text="OPERACIONES",
            bg=theme.c("sidebar"),
            fg=theme.c("text_faint"),
            font=theme.font("micro", "bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(20, 8))

        self.nav_buttons: dict[str, NavButton] = {}
        navigation = (
            ("dashboard", "◈", "Panel de control"),
            ("inventory", "▤", "Inventario"),
            ("movements", "⇅", "Movimientos"),
            ("alerts", "⚠", "Alertas de stock"),
        )
        for key, icon, label in navigation:
            button = NavButton(
                sidebar,
                theme,
                icon=icon,
                label=label,
                command=lambda target=key: self.show_view(target),
            )
            button.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = button

        operator = tk.Frame(sidebar, bg=theme.c("sidebar"))
        operator.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        avatar = tk.Frame(operator, bg=theme.c("accent_dim"), width=34, height=34)
        avatar.pack(side="left")
        avatar.pack_propagate(False)
        tk.Label(
            avatar,
            text="AD",
            bg=theme.c("accent_dim"),
            fg=theme.c("accent"),
            font=theme.font("micro", "bold"),
        ).pack(expand=True)
        operator_text = tk.Frame(operator, bg=theme.c("sidebar"))
        operator_text.pack(side="left", padx=(10, 0))
        tk.Label(
            operator_text,
            text="Administrador",
            bg=theme.c("sidebar"),
            fg=theme.c("text"),
            font=theme.font("micro", "bold"),
            anchor="w",
        ).pack(anchor="w")
        self.turn_label = tk.Label(
            operator_text,
            text=f"Turno {self._turn.lower()} · local",
            bg=theme.c("sidebar"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.turn_label.pack(anchor="w", pady=(1, 0))

        status_card = tk.Frame(
            sidebar,
            bg=theme.c("surface"),
            highlightthickness=1,
            highlightbackground=theme.c("border_soft"),
        )
        status_card.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        status_inner = tk.Frame(status_card, bg=theme.c("surface"))
        status_inner.pack(fill="x", padx=12, pady=10)

        status_top = tk.Frame(status_inner, bg=theme.c("surface"))
        status_top.pack(fill="x")
        self.sidebar_status_dot = tk.Label(
            status_top,
            text="●",
            bg=theme.c("surface"),
            fg=theme.c("accent"),
            font=theme.font("micro"),
        )
        self.sidebar_status_dot.pack(side="left")
        self.sidebar_status_label = tk.Label(
            status_top,
            text="SISTEMA EN LÍNEA",
            bg=theme.c("surface"),
            fg=theme.c("accent"),
            font=theme.font("micro", "bold"),
            anchor="w",
        )
        self.sidebar_status_label.pack(side="left", padx=(5, 0))
        tk.Label(
            status_inner,
            text="SQLite · WAL local",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        ).pack(fill="x", pady=(5, 0))
        tk.Label(
            status_inner,
            text=f"{self.workers} workers asíncronos",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        ).pack(fill="x", pady=(1, 0))

    def _build_topbar(self) -> None:
        theme = self.theme
        topbar = self.topbar

        tk.Frame(topbar, bg=theme.c("border_soft"), height=1).pack(side="bottom", fill="x")

        right = tk.Frame(topbar, bg=theme.c("bg"))
        right.pack(side="right", padx=(0, 20), pady=(16, 14))

        clock = tk.Frame(right, bg=theme.c("bg"))
        clock.pack(side="right", padx=(14, 0), anchor="e")
        self.clock_time = tk.Label(
            clock,
            text="--:--:--",
            bg=theme.c("bg"),
            fg=theme.c("text"),
            font=theme.font("subtitle", "bold", mono=True),
            anchor="e",
        )
        self.clock_time.pack(anchor="e")
        self.clock_date = tk.Label(
            clock,
            text="—",
            bg=theme.c("bg"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="e",
        )
        self.clock_date.pack(anchor="e", pady=(1, 0))

        vertical = tk.Frame(right, bg=theme.c("border"), width=1)
        vertical.pack(side="right", fill="y", padx=(6, 0), pady=3)
        vertical.pack_propagate(False)

        ActionButton(
            right,
            theme,
            "⌗  ESCANEAR",
            self.open_scanner,
            variant="outline",
            compact=True,
        ).pack(side="right", padx=(14, 14))

        self.search_box = SearchBox(
            right,
            theme,
            placeholder="Buscar producto, SKU o código…",
            on_change=self._on_search_change,
            on_submit=self._on_search_submit,
            width=27,
        )
        self.search_box.pack(side="right")

        left = tk.Frame(topbar, bg=theme.c("bg"))
        left.pack(side="left", padx=(22, 0), pady=(11, 9))
        self.view_title = tk.Label(
            left,
            text="Panel de control",
            bg=theme.c("bg"),
            fg=theme.c("text"),
            font=theme.font("heading", "bold"),
            anchor="w",
        )
        self.view_title.pack(anchor="w")
        self.view_subtitle = tk.Label(
            left,
            text="Supervisión operativa en tiempo real",
            bg=theme.c("bg"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.view_subtitle.pack(anchor="w", pady=(2, 0))

    def _build_statusbar(self, workspace: tk.Frame) -> None:
        theme = self.theme
        bar = tk.Frame(workspace, bg=theme.c("bg"), height=30)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.pack_propagate(False)

        tk.Frame(bar, bg=theme.c("border_soft"), height=1).pack(side="top", fill="x")

        inner = tk.Frame(bar, bg=theme.c("bg"))
        inner.pack(fill="both", expand=True)

        self.status_dot = tk.Label(
            inner,
            text="●",
            bg=theme.c("bg"),
            fg=theme.c("accent"),
            font=theme.font("micro"),
        )
        self.status_dot.pack(side="left", padx=(20, 4))
        self.status_mode = tk.Label(
            inner,
            text="NÚCLEO OPERATIVO",
            bg=theme.c("bg"),
            fg=theme.c("text_dim"),
            font=theme.font("micro", "bold"),
        )
        self.status_mode.pack(side="left")
        tk.Label(
            inner,
            text=f"{self.db.path.name} · SQLite WAL",
            bg=theme.c("bg"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
        ).pack(side="left", padx=(16, 0))

        tk.Label(
            inner,
            text=f"v{self.version} · {self.workers} WORKERS",
            bg=theme.c("bg"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
        ).pack(side="right", padx=(0, 20))
        self.status_sync = tk.Label(
            inner,
            text="ÚLTIMA CARGA —",
            bg=theme.c("bg"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
        )
        self.status_sync.pack(side="right", padx=(0, 14))

    def _build_views(self) -> None:
        self.dashboard_view = DashboardView(self.content, self)
        self.inventory_view = InventoryView(self.content, self)
        self.movements_view = MovementsView(self.content, self)
        self.alerts_view = AlertsView(self.content, self)
        self.views: dict[str, tk.Frame] = {
            "dashboard": self.dashboard_view,
            "inventory": self.inventory_view,
            "movements": self.movements_view,
            "alerts": self.alerts_view,
        }
        for view in self.views.values():
            view.grid(row=0, column=0, sticky="nsew", padx=18, pady=16)
        self._current_view = "dashboard"

    # ----------------------------------------------------------- interaction

    def show_view(self, key: str) -> None:
        """Raise one view and synchronize navigation state."""
        if key not in self.views:
            return
        self.views[key].tkraise()
        self._current_view = key
        for name, button in self.nav_buttons.items():
            button.set_active(name == key)

        titles = {
            "dashboard": (
                "Panel de control",
                f"Supervisión operativa en tiempo real · Turno {self._turn.lower()}",
            ),
            "inventory": (
                "Inventario",
                "Catálogo maestro · SKUs, umbrales y valorización",
            ),
            "movements": (
                "Movimientos",
                "Historial de auditoría · entradas y salidas de stock",
            ),
            "alerts": (
                "Alertas de stock",
                "Cola de reposición priorizada por severidad",
            ),
        }
        title, subtitle = titles.get(key, ("INVENTER", ""))
        self.view_title.configure(text=title)
        self.view_subtitle.configure(text=subtitle)

        if key == "inventory":
            self.apply_inventory_filter()
        elif key == "movements":
            self.apply_movement_filter()

    def _clock_tick(self) -> None:
        if not self._alive:
            return
        now = datetime.now()
        self.clock_time.configure(text=now.strftime("%H:%M:%S"))
        self.clock_date.configure(text=format_date_es(now))
        self._clock_after = self.root.after(1000, self._clock_tick)

    def _bind_shortcuts(self) -> None:
        """Expose the most frequent operations through keyboard shortcuts."""
        self.root.bind("<F5>", self._shortcut_refresh)
        self.root.bind("<Control-n>", self._shortcut_new)
        self.root.bind("<Control-f>", self._shortcut_search)
        self.root.bind("<Control-e>", self._shortcut_export)

    def _shortcut_refresh(self, _event: tk.Event) -> str:
        self.refresh_data()
        return "break"

    def _shortcut_new(self, _event: tk.Event) -> str:
        self.open_new_product()
        return "break"

    def _shortcut_search(self, _event: tk.Event) -> str:
        self.search_box.entry.focus_set()
        self.search_box.entry.icursor("end")
        return "break"

    def _shortcut_export(self, _event: tk.Event) -> str:
        if self._current_view == "inventory":
            self.export_inventory_csv()
        elif self._current_view == "movements":
            self.export_movements_csv()
        else:
            self.toasts.show(
                "La exportación está disponible en Inventario y Movimientos.", "info"
            )
        return "break"

    def _on_search_change(self, _query: str) -> None:
        if self._search_after is not None:
            self.root.after_cancel(self._search_after)
        self._search_after = self.root.after(
            self.search_debounce_ms, self._apply_pending_search
        )

    def _apply_pending_search(self) -> None:
        self._search_after = None
        if self._current_view == "movements":
            self.apply_movement_filter()
            return
        query = self.search_box.get_text().strip()
        if query and self._current_view != "inventory":
            self.show_view("inventory")
        self.apply_inventory_filter()

    def _on_search_submit(self, _query: str) -> None:
        if self._current_view == "movements":
            self.apply_movement_filter()
        elif self._current_view == "inventory":
            self.apply_inventory_filter()
        else:
            self.show_view("inventory")

    # ---------------------------------------------------------------- data

    def refresh_data(self) -> None:
        """Reload products, telemetry and movements on a worker thread."""
        if self._loading:
            self._refresh_again = True
            return
        self._loading = True
        self._set_status("loading")
        self._set_sidebar_status("SINCRONIZANDO…", "info")

        def task() -> tuple[
            list[Product], DashboardStats, list[str], list[Movement]
        ]:
            products = self.db.list_products()
            stats = build_dashboard(products, self.alert_factor)
            categories = sorted({product.category for product in products}, key=str.casefold)
            movements = self.db.list_movements(limit=200)
            return products, stats, categories, movements

        self._run_async(task, self._on_data_loaded, self._on_data_error)

    def _on_data_loaded(
        self,
        result: tuple[list[Product], DashboardStats, list[str], list[Movement]],
    ) -> None:
        products, stats, categories, movements = result
        self._loading = False
        self._products_cache = products
        self._categories = categories
        self._movements_cache = movements
        self._alerts = sort_products(
            [
                product
                for product in products
                if classify_stock(
                    product.stock, product.min_stock, self.alert_factor
                ).is_alert
            ],
            self.alert_factor,
        )

        self.dashboard_view.set_data(stats, self._alerts, movements[:4])
        self.inventory_view.set_categories(categories)
        self.apply_inventory_filter()
        self.apply_movement_filter()
        self.alerts_view.set_data(stats, self._alerts)
        self.nav_buttons["alerts"].set_badge(stats.alert_count)
        self.status_sync.configure(text=f"ÚLTIMA CARGA {datetime.now():%H:%M:%S}")
        self._set_status("idle")
        self._set_sidebar_status("SISTEMA EN LÍNEA", "ok")

        if self._refresh_again:
            self._refresh_again = False
            self.refresh_data()

    def _on_data_error(self, error: Exception) -> None:
        self._loading = False
        logger.error(
            "Inventory sync failed: %s",
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
        self._set_status("error")
        self._set_sidebar_status("ERROR DE NÚCLEO", "error")
        if hasattr(self, "toasts"):
            self.toasts.show(f"No se pudo sincronizar el inventario: {error}", "danger", 5200)
        if self._refresh_again:
            self._refresh_again = False
            self.root.after(400, self.refresh_data)

    def apply_inventory_filter(self) -> None:
        """Filter the cached catalog and repaint the inventory grid."""
        query = self.search_box.get_text().strip().casefold()
        category = self.inventory_view.category_var.get()
        only_alerts = self.inventory_view.alerts_only.get()

        filtered: list[Product] = []
        for product in self._products_cache:
            if category != ALL_CATEGORIES and product.category != category:
                continue
            status = classify_stock(product.stock, product.min_stock, self.alert_factor)
            if only_alerts and not status.is_alert:
                continue
            if query:
                haystack = (
                    f"{product.name} {product.sku} {product.barcode} {product.category}"
                ).casefold()
                if query not in haystack:
                    continue
            filtered.append(product)

        ordered = sort_products(filtered, self.alert_factor)
        self._inventory_filtered = ordered
        self.inventory_view.set_products(ordered, len(self._products_cache))

    def apply_movement_filter(self) -> None:
        """Filter the cached audit log and repaint the movements grid."""
        query = self.search_box.get_text().strip().casefold()
        kind = self.movements_view.kind_var.get()
        filtered: list[Movement] = []
        for movement in self._movements_cache:
            if kind == MovementsView.INCOMING and movement.kind != "IN":
                continue
            if kind == MovementsView.OUTGOING and movement.kind != "OUT":
                continue
            if query:
                haystack = (
                    f"{movement.product_name} {movement.sku} {movement.note}"
                ).casefold()
                if query not in haystack:
                    continue
            filtered.append(movement)

        self._movements_filtered = filtered
        self.movements_view.set_data(filtered, len(self._movements_cache))

    def _run_async(
        self,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """Submit a task and deliver its result on the Tk main thread."""
        if not self._alive:
            return
        try:
            future: Future[Any] = self._executor.submit(task)
        except RuntimeError as exc:
            on_error(exc)
            return

        def poll() -> None:
            if not self._alive:
                return
            if future.done():
                try:
                    output = future.result()
                except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                    on_error(exc)
                else:
                    on_success(output)
            else:
                self.root.after(40, poll)

        self.root.after(40, poll)

    def _mutate(self, task: Callable[[], Any], message: str) -> None:
        """Run a validated mutation and refresh the interface afterwards."""
        self._set_status("working")
        self._set_sidebar_status("APLICANDO CAMBIOS…", "info")

        def done(_result: Any) -> None:
            self.toasts.show(message, "success", self.toast_ms)
            self.refresh_data()

        def failed(error: Exception) -> None:
            logger.error(
                "Mutation rejected: %s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )
            self._set_status("error")
            self._set_sidebar_status("OPERACIÓN RECHAZADA", "error")
            self.toasts.show(str(error), "danger", 5200)

        self._run_async(task, done, failed)

    # -------------------------------------------------------------- actions

    def _find_product(self, item_id: str | None) -> Product | None:
        if not item_id:
            return None
        try:
            product_id = int(item_id)
        except (TypeError, ValueError):
            return None
        return next(
            (product for product in self._products_cache if product.id == product_id),
            None,
        )

    def open_new_product(self) -> None:
        """Open the creation form and persist a validated payload."""
        dialog = ProductDialog(
            self.root,
            self.theme,
            categories=self._categories,
            units=self.units,
        )
        payload = dialog.show()
        if payload:
            self._mutate(
                lambda: self.db.save_product(payload),
                "Producto registrado en el catálogo maestro",
            )

    def edit_product_by_id(self, item_id: str) -> None:
        """Open the edit form for a specific grid row."""
        product = self._find_product(item_id)
        if product is None:
            self.toasts.show("El producto ya no está disponible.", "warning")
            return
        dialog = ProductDialog(
            self.root,
            self.theme,
            categories=self._categories,
            units=self.units,
            product=product,
        )
        payload = dialog.show()
        if payload:
            self._mutate(
                lambda: self.db.save_product(payload),
                f"Producto actualizado · {product.name}",
            )

    def restock_product(self, product: Product) -> None:
        """Open the ingress dialog for a product snapshot."""
        status = classify_stock(product.stock, product.min_stock, self.alert_factor)
        dialog = RestockDialog(
            self.root,
            self.theme,
            product=product,
            suggested=reorder_quantity(product),
            status=status,
            alert_factor=self.alert_factor,
        )
        result = dialog.show()
        if not result:
            return
        quantity = int(result["quantity"])
        note = str(result["note"])
        self._mutate(
            lambda: self.db.adjust_stock(product.id, quantity, note),
            f"+{format_units(quantity)} unidades · {product.name}",
        )

    def restock_alert_by_id(self, item_id: str) -> None:
        """Open replenishment from any view row."""
        product = self._find_product(item_id)
        if product is None:
            self.toasts.show("Selecciona un producto válido.", "warning")
            return
        self.restock_product(product)

    def sell_product_by_id(self, item_id: str) -> None:
        """Open the manual stock-exit form for a catalog row."""
        product = self._find_product(item_id)
        if product is None:
            self.toasts.show("Selecciona un producto válido.", "warning")
            return
        status = classify_stock(product.stock, product.min_stock, self.alert_factor)
        dialog = SaleDialog(
            self.root,
            self.theme,
            product=product,
            status=status,
            alert_factor=self.alert_factor,
        )
        result = dialog.show()
        if not result:
            return
        quantity = int(result["quantity"])
        note = str(result["note"])
        self._mutate(
            lambda: self.db.adjust_stock(product.id, -quantity, note),
            f"Salida de {format_units(quantity)} unidades · {product.name}",
        )

    def open_bulk_restock(self) -> None:
        """Replenish every current alert in one atomic transaction."""
        if not self._alerts:
            self.toasts.show("No hay alertas pendientes de reposición.", "info")
            return

        items = [
            (product.id, reorder_quantity(product)) for product in self._alerts
        ]
        total_units = sum(quantity for _, quantity in items)
        investment = sum(
            reorder_quantity(product) * product.cost for product in self._alerts
        )
        dialog = ConfirmDialog(
            self.root,
            self.theme,
            title="Reposición masiva",
            subtitle="OPERACIÓN ATÓMICA · COLA DE ALERTAS",
            message=(
                f"Se registrarán {len(items)} movimientos de entrada en una sola "
                "transacción. Los productos de la cola quedarán por encima de su "
                "umbral mínimo, respetando la capacidad configurada."
            ),
            metrics=(
                ("PRODUCTOS", format_units(len(items)), self.theme.c("text")),
                ("UNIDADES", format_units(total_units), self.theme.c("accent")),
                (
                    "INVERSIÓN EST.",
                    format_money(investment, self.currency),
                    self.theme.c("warning"),
                ),
            ),
            confirm_text="CONFIRMAR REPOSICIÓN",
            hint="OPERACIÓN ATÓMICA · QUEDA REGISTRADA EN AUDITORÍA",
        )
        if not dialog.show():
            return
        self._mutate(
            lambda: self.db.bulk_replenish(
                items, "Reposición masiva · alertas de stock"
            ),
            f"{len(items)} productos reabastecidos",
        )

    def _write_csv(
        self,
        path: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> None:
        """Write a UTF-8 CSV file for spreadsheet consumption."""
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)

    def export_inventory_csv(self) -> None:
        """Export the currently filtered catalog to CSV."""
        products = self._inventory_filtered
        if not products:
            self.toasts.show("No hay productos visibles para exportar.", "warning")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Exportar inventario a CSV",
            defaultextension=".csv",
            initialfile=f"inventario_{datetime.now():%Y%m%d_%H%M}.csv",
            filetypes=[("Archivo CSV", "*.csv"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return
        rows = []
        for product in products:
            status = classify_stock(
                product.stock, product.min_stock, self.alert_factor
            )
            rows.append(
                (
                    product.sku,
                    product.name,
                    product.category,
                    product.unit,
                    product.stock,
                    product.min_stock,
                    product.max_stock,
                    f"{product.price:.2f}",
                    f"{product.cost:.2f}",
                    f"{product.stock * product.price:.2f}",
                    product.supplier,
                    status.value,
                    product.updated_at.isoformat(timespec="seconds"),
                )
            )
        try:
            self._write_csv(
                path,
                (
                    "SKU",
                    "Producto",
                    "Categoría",
                    "Unidad",
                    "Stock",
                    "Mínimo",
                    "Máximo",
                    "Precio",
                    "Costo",
                    "Valor",
                    "Proveedor",
                    "Estado",
                    "Actualizado",
                ),
                rows,
            )
        except OSError as exc:
            logger.error("Inventory export failed: %s", exc)
            self.toasts.show(f"No se pudo exportar el inventario: {exc}", "danger", 5200)
            return
        logger.info("Inventory exported rows=%d path=%s", len(rows), path)
        self.toasts.show(
            f"Inventario exportado · {len(rows)} SKU", "success", self.toast_ms
        )

    def export_movements_csv(self) -> None:
        """Export the currently filtered audit history to CSV."""
        movements = self._movements_filtered
        if not movements:
            self.toasts.show("No hay movimientos visibles para exportar.", "warning")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Exportar movimientos a CSV",
            defaultextension=".csv",
            initialfile=f"movimientos_{datetime.now():%Y%m%d_%H%M}.csv",
            filetypes=[("Archivo CSV", "*.csv"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return
        rows = [
            (
                movement.created_at.isoformat(timespec="seconds"),
                "ENTRADA" if movement.kind == "IN" else "SALIDA",
                movement.product_name,
                movement.sku,
                movement.quantity,
                movement.note,
            )
            for movement in movements
        ]
        try:
            self._write_csv(
                path,
                ("Fecha", "Tipo", "Producto", "SKU", "Cantidad", "Motivo"),
                rows,
            )
        except OSError as exc:
            logger.error("Movement export failed: %s", exc)
            self.toasts.show(f"No se pudo exportar el historial: {exc}", "danger", 5200)
            return
        logger.info("Movements exported rows=%d path=%s", len(rows), path)
        self.toasts.show(
            f"Historial exportado · {len(rows)} movimientos",
            "success",
            self.toast_ms,
        )

    def open_scanner(self) -> None:
        """Open the barcode simulation against the cached catalog."""
        lookup = lambda code: next(  # noqa: E731 - tiny local adapter
            (
                product
                for product in self._products_cache
                if product.barcode == code.strip()
            ),
            None,
        )
        sample = self._products_cache[0].barcode if self._products_cache else None
        dialog = BarcodeScanDialog(
            self.root,
            self.theme,
            lookup=lookup,
            sample=sample,
            alert_factor=self.alert_factor,
        )
        result = dialog.show()
        if not result:
            return

        product = result["product"]
        action = result["action"]
        if action == "sale":
            self._mutate(
                lambda: self.db.adjust_stock(
                    product.id,
                    -int(result["quantity"]),
                    f"Salida rápida · escáner {product.barcode}",
                ),
                f"Salida registrada · {product.name}",
            )
        elif action == "restock":
            self.restock_product(product)

    # ---------------------------------------------------------- status & exit

    def _set_status(self, mode: str) -> None:
        modes = {
            "idle": (self.theme.c("accent"), "NÚCLEO OPERATIVO"),
            "loading": (self.theme.c("info"), "SINCRONIZANDO…"),
            "working": (self.theme.c("warning"), "APLICANDO CAMBIOS…"),
            "error": (self.theme.c("danger"), "ERROR DE SINCRONIZACIÓN"),
        }
        color, text = modes.get(mode, modes["idle"])
        self.status_dot.configure(fg=color)
        self.status_mode.configure(text=text)

    def _set_sidebar_status(self, text: str, kind: str) -> None:
        colors = {
            "ok": self.theme.c("accent"),
            "info": self.theme.c("info"),
            "error": self.theme.c("danger"),
        }
        color = colors.get(kind, self.theme.c("text_dim"))
        self.sidebar_status_label.configure(text=text, fg=color)
        self.sidebar_status_dot.configure(fg=color)

    def _on_tk_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: Any,
    ) -> None:
        logger.error(
            "Unhandled Tk callback exception",
            exc_info=(exc_type, exc_value, traceback),
        )
        if not self._alive:
            return
        try:
            self._set_status("error")
            if hasattr(self, "toasts"):
                self.toasts.show(f"Error inesperado: {exc_value}", "danger", 5200)
        except tk.TclError:
            logger.warning("Could not render the exception notification")

    def close(self) -> None:
        """Cancel timers, stop workers and destroy the root window."""
        if not self._alive:
            return
        self._alive = False
        if self._search_after is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._search_after)
        if self._clock_after is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._clock_after)
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("Main window closed")
        with contextlib.suppress(tk.TclError):
            self.root.destroy()

    def run(self) -> None:
        """Start the Tk event loop."""
        self.root.mainloop()
