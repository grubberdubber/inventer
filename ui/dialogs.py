"""Frameless modal dialogs for product entry, restocking and barcode scans."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import asdict
from tkinter import ttk
from typing import Any

from core.inventory import (
    Product,
    StockStatus,
    ValidationError,
    classify_stock,
    validate_product,
)
from ui.widgets import (
    ActionButton,
    Theme,
    format_money,
    format_units,
    pill,
    relative_time,
    status_accent,
    truncate,
)


def _dark_entry(
    master: tk.Misc,
    theme: Theme,
    variable: tk.StringVar,
    *,
    font: tuple[str, int, str] | None = None,
    justify: str = "left",
    width: int = 0,
) -> tk.Entry:
    """Build a flat dark entry with a focus accent ring."""
    return tk.Entry(
        master,
        textvariable=variable,
        bg=theme.c("surface_alt"),
        fg=theme.c("text"),
        insertbackground=theme.c("accent"),
        disabledbackground=theme.c("surface"),
        disabledforeground=theme.c("text_faint"),
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=theme.c("border"),
        highlightcolor=theme.c("accent"),
        font=font or theme.font("caption"),
        justify=justify,
        width=width,
    )


def _new_field_block(master: tk.Misc, theme: Theme, label: str) -> tk.Frame:
    """Create a form block with its caption; callers attach the control."""
    block = tk.Frame(master, bg=theme.c("surface"))
    tk.Label(
        block,
        text=label,
        bg=theme.c("surface"),
        fg=theme.c("text_faint"),
        font=theme.font("micro", "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 5))
    return block


class BaseDialog(tk.Toplevel):
    """Frameless modal shell with drag support and a shared header."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        title: str,
        subtitle: str = "",
        width: int,
        height: int,
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self.result: Any = None
        self._drag_offset = (0, 0)

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=theme.c("border"))
        self.resizable(False, False)

        shell = tk.Frame(self, bg=theme.c("surface"))
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        tk.Frame(shell, bg=theme.c("accent"), height=2).pack(fill="x")

        header = tk.Frame(shell, bg=theme.c("surface"), cursor="fleur")
        header.pack(fill="x", padx=22, pady=(18, 12))

        titles = tk.Frame(header, bg=theme.c("surface"))
        titles.pack(side="left", fill="x", expand=True)

        self.title_label = tk.Label(
            titles,
            text=title,
            bg=theme.c("surface"),
            fg=theme.c("text"),
            font=theme.font("heading", "bold"),
            anchor="w",
        )
        self.title_label.pack(fill="x")

        self.subtitle_label = tk.Label(
            titles,
            text=subtitle,
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.subtitle_label.pack(fill="x", pady=(3, 0))

        close = tk.Label(
            header,
            text="✕",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("caption", "bold"),
            padx=9,
            pady=5,
            cursor="hand2",
        )
        close.pack(side="right", anchor="n")
        close.bind("<Button-1>", lambda _event: self._cancel())
        close.bind("<Enter>", lambda _event: close.configure(fg=theme.c("danger")))
        close.bind("<Leave>", lambda _event: close.configure(fg=theme.c("text_faint")))

        for widget in (header, titles, self.title_label, self.subtitle_label):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        self.footer = tk.Frame(shell, bg=theme.c("surface"))
        self.footer.pack(side="bottom", fill="x", padx=22, pady=18)

        self.content = tk.Frame(shell, bg=theme.c("surface"))
        self.content.pack(fill="both", expand=True, padx=22, pady=(2, 0))

        self.update_idletasks()
        self._center(parent, width, height)
        self.deiconify()
        self.lift()
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.after(40, self._focus_initial)

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_offset = (
            event.x_root - self.winfo_x(),
            event.y_root - self.winfo_y(),
        )

    def _drag_move(self, event: tk.Event) -> None:
        offset_x, offset_y = self._drag_offset
        self.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def _center(self, parent: tk.Misc, width: int, height: int) -> None:
        toplevel = parent.winfo_toplevel()
        toplevel.update_idletasks()
        origin_x = toplevel.winfo_rootx()
        origin_y = toplevel.winfo_rooty()
        origin_w = toplevel.winfo_width()
        origin_h = toplevel.winfo_height()
        x = origin_x + (origin_w - width) // 2
        y = origin_y + (origin_h - height) // 2
        x = max(8, min(x, self.winfo_screenwidth() - width - 8))
        y = max(8, min(y, self.winfo_screenheight() - height - 8))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _focus_initial(self) -> None:
        """Hook for subclasses to focus their primary control."""

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        self.destroy()

    def show(self) -> Any:
        """Run the dialog modally and return its result."""
        self.wait_window(self)
        return self.result

    def _footer_actions(
        self,
        primary_text: str,
        primary_command: Callable[[], Any],
        *,
        primary_variant: str = "primary",
        hint: str = "",
    ) -> ActionButton:
        """Attach the standard cancel/confirm footer and return the primary."""
        if hint:
            tk.Label(
                self.footer,
                text=hint,
                bg=self.theme.c("surface"),
                fg=self.theme.c("text_faint"),
                font=self.theme.font("micro"),
                anchor="w",
            ).pack(side="left")

        primary = ActionButton(
            self.footer,
            self.theme,
            primary_text,
            primary_command,
            variant=primary_variant,
        )
        primary.pack(side="right")

        cancel = ActionButton(
            self.footer,
            self.theme,
            "Cancelar",
            self._cancel,
            variant="ghost",
        )
        cancel.pack(side="right", padx=(0, 8))
        return primary


class ProductDialog(BaseDialog):
    """Create or edit a catalog product with strict inline validation."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        categories: Sequence[str],
        units: Sequence[str],
        product: Product | None = None,
    ) -> None:
        editing = product is not None
        super().__init__(
            parent,
            theme,
            title="Editar producto" if editing else "Nuevo producto",
            subtitle="REGISTRO MAESTRO · VALIDACIÓN ESTRICTA · TRAZABILIDAD ACTIVA",
            width=700,
            height=566,
        )
        self._product = product
        self._vars: dict[str, tk.StringVar] = {}
        self._entries: dict[str, tk.Widget] = {}

        defaults = {
            "sku": product.sku if product else "",
            "barcode": product.barcode if product else "",
            "name": product.name if product else "",
            "category": product.category if product else (categories[0] if categories else ""),
            "unit": product.unit if product else (units[0] if units else "Unidad"),
            "stock": str(product.stock) if product else "0",
            "min_stock": str(product.min_stock) if product else "10",
            "max_stock": str(product.max_stock) if product else "60",
            "price": f"{product.price:.2f}" if product else "0.00",
            "cost": f"{product.cost:.2f}" if product else "0.00",
            "supplier": product.supplier if product else "",
        }
        for key, value in defaults.items():
            self._vars[key] = tk.StringVar(value=value)

        form = tk.Frame(self.content, bg=theme.c("surface"))
        form.pack(fill="both", expand=True)
        form.grid_columnconfigure(0, weight=1, uniform="form")
        form.grid_columnconfigure(1, weight=1, uniform="form")

        def add(
            row: int,
            column: int,
            key: str,
            label: str,
            *,
            span: int = 1,
            values: Sequence[str] | None = None,
        ) -> None:
            block = _new_field_block(form, theme, label)
            if values is None:
                widget: tk.Widget = _dark_entry(block, theme, self._vars[key])
                widget.bind("<Return>", lambda _event: self._submit())
            else:
                widget = ttk.Combobox(
                    block,
                    textvariable=self._vars[key],
                    values=list(values),
                    state="normal",
                    style="Dark.TCombobox",
                )
            widget.pack(fill="x", ipady=5)
            padx = (0, 7) if column == 0 else (7, 0)
            block.grid(
                row=row,
                column=column,
                columnspan=span,
                sticky="ew",
                padx=padx,
                pady=(0, 10),
            )
            self._entries[key] = widget

        add(0, 0, "sku", "SKU *")
        add(0, 1, "barcode", "CÓDIGO DE BARRAS *")
        add(1, 0, "name", "NOMBRE DEL PRODUCTO *", span=2)
        add(2, 0, "category", "CATEGORÍA *", values=categories)
        add(2, 1, "unit", "UNIDAD DE MEDIDA", values=units)
        add(3, 0, "stock", "STOCK ACTUAL")
        add(3, 1, "min_stock", "STOCK MÍNIMO *")
        add(4, 0, "max_stock", "STOCK MÁXIMO *")
        add(4, 1, "price", "PRECIO DE VENTA *")
        add(5, 0, "cost", "COSTO UNITARIO")
        add(5, 1, "supplier", "PROVEEDOR")

        self.error_label = tk.Label(
            self.content,
            text="",
            bg=theme.c("surface"),
            fg=theme.c("danger"),
            font=theme.font("micro"),
            anchor="w",
            wraplength=640,
        )
        self.error_label.pack(fill="x", pady=(2, 0))

        self._footer_actions(
            "Guardar producto" if not editing else "Guardar cambios",
            self._submit,
            hint="LOS CAMBIOS SE REGISTRAN EN LA BITÁCORA DE MOVIMIENTOS",
        )
        self.bind("<Control-Return>", lambda _event: self._submit())

    def _focus_initial(self) -> None:
        entry = self._entries.get("sku")
        if entry is not None:
            entry.focus_set()

    def _submit(self) -> None:
        payload: dict[str, Any] = {
            key: variable.get() for key, variable in self._vars.items()
        }
        payload["product_id"] = self._product.id if self._product else None
        try:
            draft = validate_product(payload)
        except ValidationError as exc:
            self.error_label.configure(text=str(exc))
            return
        self.result = asdict(draft)
        self._close()


class RestockDialog(BaseDialog):
    """Register a positive stock movement for one product."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        product: Product,
        suggested: int,
        status: StockStatus,
        alert_factor: float = 1.5,
    ) -> None:
        super().__init__(
            parent,
            theme,
            title="Registrar ingreso",
            subtitle="MOVIMIENTO ATÓMICO DE INVENTARIO · ENTRADA DE MERCANCÍA",
            width=570,
            height=452,
        )
        self._product = product
        self._status = status
        self._quantity = tk.StringVar(value=str(suggested))
        self._note = tk.StringVar(value="Reposición de stock")

        summary = tk.Frame(
            self.content,
            bg=theme.c("surface_alt"),
            highlightthickness=1,
            highlightbackground=theme.c("border"),
        )
        summary.pack(fill="x", pady=(0, 14))

        info = tk.Frame(summary, bg=theme.c("surface_alt"))
        info.pack(side="left", fill="both", expand=True, padx=14, pady=12)
        tk.Label(
            info,
            text=truncate(product.name, 38),
            bg=theme.c("surface_alt"),
            fg=theme.c("text"),
            font=theme.font("title", "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            info,
            text=f"{product.sku} · {product.category} · {product.supplier}",
            bg=theme.c("surface_alt"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        ).pack(fill="x", pady=(3, 6))

        badge = pill(
            info,
            theme,
            status.value,
            fg=status_accent(theme, status),
            bg=theme.c("surface"),
            border=theme.c("border"),
        )
        badge.pack(anchor="w")

        stock_block = tk.Frame(summary, bg=theme.c("surface_alt"))
        stock_block.pack(side="right", padx=14, pady=12, anchor="n")
        tk.Label(
            stock_block,
            text="STOCK ACTUAL",
            bg=theme.c("surface_alt"),
            fg=theme.c("text_faint"),
            font=theme.font("micro", "bold"),
        ).pack(anchor="e")
        tk.Label(
            stock_block,
            text=format_units(product.stock),
            bg=theme.c("surface_alt"),
            fg=status_accent(theme, status),
            font=theme.font("display", "bold", mono=True),
        ).pack(anchor="e")

        quantity_row = tk.Frame(self.content, bg=theme.c("surface"))
        quantity_row.pack(fill="x", pady=(0, 8))

        tk.Label(
            quantity_row,
            text="CANTIDAD A INGRESAR",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro", "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))

        entry_row = tk.Frame(quantity_row, bg=theme.c("surface"))
        entry_row.pack(fill="x")

        qty_entry = _dark_entry(
            entry_row,
            theme,
            self._quantity,
            font=theme.font("title", "bold", mono=True),
            justify="center",
            width=8,
        )
        qty_entry.pack(side="left", ipady=10, padx=(0, 8))
        qty_entry.bind("<Return>", lambda _event: self._submit())

        quick_values = sorted({10, 24, 48, max(1, product.max_stock)})
        for value in quick_values:
            ActionButton(
                entry_row,
                theme,
                f"+{value}",
                lambda _v=value: self._quantity.set(str(_v)),
                variant="ghost",
                compact=True,
            ).pack(side="left", padx=(0, 6))

        self.projection_label = tk.Label(
            self.content,
            text="",
            bg=theme.c("surface"),
            fg=theme.c("text_dim"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.projection_label.pack(fill="x", pady=(0, 10))
        self._quantity.trace_add("write", self._update_projection)

        note_block = _new_field_block(self.content, theme, "MOTIVO DEL MOVIMIENTO")
        note_entry = _dark_entry(note_block, theme, self._note)
        note_entry.pack(fill="x", ipady=5)
        note_block.pack(fill="x", pady=(0, 4))

        self.error_label = tk.Label(
            self.content,
            text="",
            bg=theme.c("surface"),
            fg=theme.c("danger"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.error_label.pack(fill="x")

        self._footer_actions(
            "Registrar ingreso",
            self._submit,
            hint="EL MOVIMIENTO SE APLICA DE FORMA ATÓMICA",
        )
        self._update_projection()
        self.after(60, qty_entry.focus_set)

    def _update_projection(self, *_args: object) -> None:
        try:
            quantity = int(self._quantity.get())
        except ValueError:
            self.projection_label.configure(
                text="Introduce una cantidad entera válida.", fg=self.theme.c("danger")
            )
            return
        projected = self._product.stock + quantity
        if quantity <= 0:
            self.projection_label.configure(
                text="La cantidad debe ser mayor que cero.", fg=self.theme.c("danger")
            )
        elif projected > self._product.max_stock:
            self.projection_label.configure(
                text=(
                    f"Stock proyectado: {format_units(projected)} · supera la capacidad "
                    f"({format_units(self._product.max_stock)})"
                ),
                fg=self.theme.c("warning"),
            )
        else:
            self.projection_label.configure(
                text=(
                    f"Stock proyectado: {format_units(projected)} de "
                    f"{format_units(self._product.max_stock)} unidades"
                ),
                fg=self.theme.c("text_dim"),
            )

    def _submit(self) -> None:
        try:
            quantity = int(self._quantity.get())
        except ValueError:
            self.error_label.configure(text="La cantidad debe ser un número entero.")
            return
        if quantity <= 0:
            self.error_label.configure(text="La cantidad debe ser mayor que cero.")
            return
        note = self._note.get().strip()
        if len(note) > 120:
            self.error_label.configure(text="El motivo no puede superar 120 caracteres.")
            return
        self.result = {"quantity": quantity, "note": note or "Reposición de stock"}
        self._close()


class SaleDialog(BaseDialog):
    """Register a stock exit (sale, shrinkage or manual adjustment)."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        product: Product,
        status: StockStatus,
        alert_factor: float = 1.5,
    ) -> None:
        super().__init__(
            parent,
            theme,
            title="Registrar salida",
            subtitle="MOVIMIENTO DE SALIDA · VENTA / MERMA / AJUSTE",
            width=580,
            height=500,
        )
        self._product = product
        self._status = status
        self._quantity = tk.StringVar(value="1")
        self._reason = tk.StringVar(value="Venta POS")
        self._reference = tk.StringVar(value="")

        summary = tk.Frame(
            self.content,
            bg=theme.c("surface_alt"),
            highlightthickness=1,
            highlightbackground=theme.c("border"),
        )
        summary.pack(fill="x", pady=(0, 14))

        info = tk.Frame(summary, bg=theme.c("surface_alt"))
        info.pack(side="left", fill="both", expand=True, padx=14, pady=12)
        tk.Label(
            info,
            text=truncate(product.name, 38),
            bg=theme.c("surface_alt"),
            fg=theme.c("text"),
            font=theme.font("title", "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            info,
            text=f"{product.sku} · {product.category} · {product.supplier}",
            bg=theme.c("surface_alt"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
            anchor="w",
        ).pack(fill="x", pady=(3, 6))
        pill(
            info,
            theme,
            status.value,
            fg=status_accent(theme, status),
            bg=theme.c("surface"),
            border=theme.c("border"),
        ).pack(anchor="w")

        stock_block = tk.Frame(summary, bg=theme.c("surface_alt"))
        stock_block.pack(side="right", padx=14, pady=12, anchor="n")
        tk.Label(
            stock_block,
            text="DISPONIBLE",
            bg=theme.c("surface_alt"),
            fg=theme.c("text_faint"),
            font=theme.font("micro", "bold"),
        ).pack(anchor="e")
        tk.Label(
            stock_block,
            text=format_units(product.stock),
            bg=theme.c("surface_alt"),
            fg=status_accent(theme, status),
            font=theme.font("display", "bold", mono=True),
        ).pack(anchor="e")

        tk.Label(
            self.content,
            text="CANTIDAD A RETIRAR",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro", "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        entry_row = tk.Frame(self.content, bg=theme.c("surface"))
        entry_row.pack(fill="x", pady=(0, 8))
        qty_entry = _dark_entry(
            entry_row,
            theme,
            self._quantity,
            font=theme.font("title", "bold", mono=True),
            justify="center",
            width=8,
        )
        qty_entry.pack(side="left", ipady=10, padx=(0, 8))
        qty_entry.bind("<Return>", lambda _event: self._submit())
        for value in (1, 2, 5, 10):
            ActionButton(
                entry_row,
                theme,
                f"−{value}",
                lambda _v=value: self._quantity.set(str(_v)),
                variant="ghost",
                compact=True,
            ).pack(side="left", padx=(0, 6))

        self.projection_label = tk.Label(
            self.content,
            text="",
            bg=theme.c("surface"),
            fg=theme.c("text_dim"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.projection_label.pack(fill="x", pady=(0, 8))
        self._quantity.trace_add("write", self._update_projection)

        detail_row = tk.Frame(self.content, bg=theme.c("surface"))
        detail_row.pack(fill="x", pady=(0, 4))

        reason_block = _new_field_block(detail_row, theme, "MOTIVO")
        reason_block.pack(side="left", fill="x", expand=True, padx=(0, 6))
        reason_combo = ttk.Combobox(
            reason_block,
            textvariable=self._reason,
            values=["Venta POS", "Merma", "Ajuste manual"],
            state="readonly",
            style="Dark.TCombobox",
        )
        reason_combo.pack(fill="x", ipady=5)

        reference_block = _new_field_block(detail_row, theme, "REFERENCIA / TICKET")
        reference_block.pack(side="left", fill="x", expand=True, padx=(6, 0))
        reference_entry = _dark_entry(reference_block, theme, self._reference)
        reference_entry.pack(fill="x", ipady=5)
        reference_entry.bind("<Return>", lambda _event: self._submit())

        self.error_label = tk.Label(
            self.content,
            text="",
            bg=theme.c("surface"),
            fg=theme.c("danger"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.error_label.pack(fill="x", pady=(2, 0))

        self._footer_actions(
            "Registrar salida",
            self._submit,
            primary_variant="danger",
            hint="LA SALIDA SE APLICA DE FORMA ATÓMICA",
        )
        self._update_projection()
        self.after(60, qty_entry.focus_set)

    def _update_projection(self, *_args: object) -> None:
        try:
            quantity = int(self._quantity.get())
        except ValueError:
            self.projection_label.configure(
                text="Introduce una cantidad entera válida.", fg=self.theme.c("danger")
            )
            return
        if quantity <= 0:
            self.projection_label.configure(
                text="La cantidad debe ser mayor que cero.", fg=self.theme.c("danger")
            )
            return
        projected = self._product.stock - quantity
        if projected < 0:
            self.projection_label.configure(
                text="Stock insuficiente para registrar esta salida.",
                fg=self.theme.c("danger"),
            )
        elif projected == 0:
            self.projection_label.configure(
                text="Stock proyectado: 0 unidades · el producto quedará agotado.",
                fg=self.theme.c("warning"),
            )
        else:
            self.projection_label.configure(
                text=(
                    f"Stock proyectado: {format_units(projected)} de "
                    f"{format_units(self._product.max_stock)} unidades"
                ),
                fg=self.theme.c("text_dim"),
            )

    def _submit(self) -> None:
        try:
            quantity = int(self._quantity.get())
        except ValueError:
            self.error_label.configure(text="La cantidad debe ser un número entero.")
            return
        if quantity <= 0:
            self.error_label.configure(text="La cantidad debe ser mayor que cero.")
            return
        if quantity > self._product.stock:
            self.error_label.configure(text="Stock insuficiente para registrar la salida.")
            return
        note = self._reason.get().strip()
        reference = self._reference.get().strip()
        if reference:
            note = f"{note} · {reference}"
        if len(note) > 120:
            self.error_label.configure(text="La referencia no puede superar 120 caracteres.")
            return
        self.result = {"quantity": quantity, "note": note}
        self._close()


class ConfirmDialog(BaseDialog):
    """Generic confirmation sheet for high-impact operations."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        title: str,
        subtitle: str,
        message: str,
        metrics: Sequence[tuple[str, str, str]],
        confirm_text: str,
        hint: str = "",
    ) -> None:
        super().__init__(
            parent,
            theme,
            title=title,
            subtitle=subtitle,
            width=600,
            height=390,
        )
        self._message = tk.Label(
            self.content,
            text=message,
            bg=theme.c("surface"),
            fg=theme.c("text_dim"),
            font=theme.font("caption"),
            justify="left",
            anchor="w",
            wraplength=540,
        )
        self._message.pack(fill="x", pady=(4, 16))

        metrics_row = tk.Frame(self.content, bg=theme.c("surface"))
        metrics_row.pack(fill="x", pady=(0, 8))
        for index, (label, value, color) in enumerate(metrics):
            block = tk.Frame(
                metrics_row,
                bg=theme.c("surface_alt"),
                highlightthickness=1,
                highlightbackground=theme.c("border_soft"),
            )
            block.pack(
                side="left",
                fill="x",
                expand=True,
                padx=(0, 8) if index < len(metrics) - 1 else 0,
            )
            tk.Label(
                block,
                text=label,
                bg=theme.c("surface_alt"),
                fg=theme.c("text_faint"),
                font=theme.font("micro", "bold"),
                anchor="w",
            ).pack(fill="x", padx=12, pady=(10, 2))
            tk.Label(
                block,
                text=value,
                bg=theme.c("surface_alt"),
                fg=color,
                font=theme.font("title", "bold", mono=True),
                anchor="w",
            ).pack(fill="x", padx=12, pady=(0, 10))

        if hint:
            tk.Label(
                self.content,
                text=hint,
                bg=theme.c("surface"),
                fg=theme.c("text_faint"),
                font=theme.font("micro"),
                anchor="w",
                wraplength=540,
            ).pack(fill="x", pady=(8, 0))

        self._footer_actions(
            confirm_text,
            self._confirm,
        )

    def _confirm(self) -> None:
        self.result = True
        self._close()


class BarcodeScanDialog(BaseDialog):
    """Simulated optical scanner that resolves barcodes from the catalog."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        lookup: Callable[[str], Product | None],
        sample: str | None = None,
        alert_factor: float = 1.5,
    ) -> None:
        super().__init__(
            parent,
            theme,
            title="Escáner de códigos",
            subtitle="SIMULACIÓN DE LECTOR ÓPTICO · POS SINCRONIZADO",
            width=640,
            height=560,
        )
        self._lookup = lookup
        self._factor = alert_factor
        self._product: Product | None = None
        self._code = tk.StringVar(value="")

        tk.Label(
            self.content,
            text="CÓDIGO EAN-13",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro", "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 5))

        entry_shell = tk.Frame(
            self.content,
            bg=theme.c("surface_alt"),
            highlightthickness=1,
            highlightbackground=theme.c("border"),
        )
        entry_shell.pack(fill="x")
        self.entry = tk.Entry(
            entry_shell,
            textvariable=self._code,
            bg=theme.c("surface_alt"),
            fg=theme.c("text"),
            insertbackground=theme.c("accent"),
            relief="flat",
            bd=0,
            font=theme.font("title", "bold", mono=True),
            width=18,
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=9, padx=12)
        ActionButton(
            entry_shell,
            theme,
            "BUSCAR",
            self._scan,
            variant="ghost",
            compact=True,
        ).pack(side="right", padx=6)
        self.entry.bind("<Return>", lambda _event: self._scan())

        self._barcode_canvas = tk.Canvas(
            self.content,
            height=36,
            bg=theme.c("surface"),
            highlightthickness=0,
            bd=0,
        )
        self._barcode_canvas.pack(fill="x", pady=(9, 2))
        self._barcode_canvas.bind("<Configure>", lambda _event: self._draw_barcode())

        hint_row = tk.Frame(self.content, bg=theme.c("surface"))
        hint_row.pack(fill="x", pady=(0, 10))
        tk.Label(
            hint_row,
            text="LÍNEA DE ESCANEO ACTIVA",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
        ).pack(side="left")
        if sample:
            sample_link = tk.Label(
                hint_row,
                text=f"PRUEBA CON {sample}",
                bg=theme.c("surface"),
                fg=theme.c("info"),
                font=theme.font("micro", "bold"),
                cursor="hand2",
            )
            sample_link.pack(side="right")
            sample_link.bind("<Button-1>", lambda _event: self._use_sample(sample))

        self.error_label = tk.Label(
            self.content,
            text="",
            bg=theme.c("surface"),
            fg=theme.c("danger"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.error_label.pack(fill="x")

        self.result_frame = tk.Frame(self.content, bg=theme.c("surface"))
        self.result_frame.pack(fill="both", expand=True, pady=(8, 0))
        self._render_placeholder()

        tk.Label(
            self.footer,
            text="[ENTER] BUSCAR · [ESC] CERRAR",
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro"),
        ).pack(side="left")
        ActionButton(
            self.footer,
            theme,
            "Cerrar",
            self._cancel,
            variant="ghost",
        ).pack(side="right")

        self.after(60, self.entry.focus_set)

    def _draw_barcode(self) -> None:
        canvas = self._barcode_canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 10:
            return
        pattern = [2, 1, 3, 1, 1, 2, 4, 1, 2, 1, 1, 3, 2, 1, 2, 4, 1, 1, 3, 2]
        x = 2
        index = 0
        margin = 40
        usable = max(10, width - margin * 2)
        while x < usable:
            bar_width = pattern[index % len(pattern)]
            if index % 2 == 0:
                canvas.create_rectangle(
                    margin + x,
                    4,
                    margin + x + bar_width,
                    height - 4,
                    fill=self.theme.c("text_dim"),
                    outline="",
                )
            x += bar_width + 1
            index += 1

    def _use_sample(self, sample: str) -> None:
        self._code.set(sample)
        self._scan()

    def _scan(self) -> None:
        code = self._code.get().strip()
        if not code:
            self.error_label.configure(text="Introduce un código de barras.")
            self._render_placeholder()
            return
        product = self._lookup(code)
        if product is None:
            self.error_label.configure(
                text=f"El código {code} no existe en el catálogo maestro."
            )
            self._render_placeholder("Código no encontrado. Verifica el dígito o el lector.")
            return
        self.error_label.configure(text="")
        self._product = product
        self._render_product(product)

    def _clear_result(self) -> None:
        for child in self.result_frame.winfo_children():
            child.destroy()

    def _render_placeholder(self, text: str = "Escanea o escribe un código para consultar el catálogo.") -> None:
        self._clear_result()
        self._product = None
        box = tk.Frame(
            self.result_frame,
            bg=self.theme.c("surface_alt"),
            highlightthickness=1,
            highlightbackground=self.theme.c("border_soft"),
        )
        box.pack(fill="both", expand=True)
        tk.Label(
            box,
            text="▦",
            bg=self.theme.c("surface_alt"),
            fg=self.theme.c("text_faint"),
            font=self.theme.font("heading"),
        ).pack(pady=(36, 6))
        tk.Label(
            box,
            text=text,
            bg=self.theme.c("surface_alt"),
            fg=self.theme.c("text_faint"),
            font=self.theme.font("caption"),
            wraplength=500,
            justify="center",
        ).pack(padx=20)

    def _render_product(self, product: Product) -> None:
        self._clear_result()
        status = classify_stock(product.stock, product.min_stock, self._factor)

        box = tk.Frame(
            self.result_frame,
            bg=self.theme.c("surface_alt"),
            highlightthickness=1,
            highlightbackground=self.theme.c("border"),
        )
        box.pack(fill="both", expand=True)

        top = tk.Frame(box, bg=self.theme.c("surface_alt"))
        top.pack(fill="x", padx=14, pady=(12, 6))

        left = tk.Frame(top, bg=self.theme.c("surface_alt"))
        left.pack(side="left", fill="x", expand=True)
        tk.Label(
            left,
            text=truncate(product.name, 42),
            bg=self.theme.c("surface_alt"),
            fg=self.theme.c("text"),
            font=self.theme.font("title", "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            left,
            text=(
                f"{product.sku} · {product.category} · {product.unit} · "
                f"{product.supplier}"
            ),
            bg=self.theme.c("surface_alt"),
            fg=self.theme.c("text_faint"),
            font=self.theme.font("micro"),
            anchor="w",
        ).pack(fill="x", pady=(3, 0))

        right = tk.Frame(top, bg=self.theme.c("surface_alt"))
        right.pack(side="right", padx=(12, 0))
        pill(
            right,
            self.theme,
            status.value,
            fg=status_accent(self.theme, status),
            bg=self.theme.c("surface"),
            border=self.theme.c("border"),
        ).pack(anchor="e")

        metrics = tk.Frame(box, bg=self.theme.c("surface_alt"))
        metrics.pack(fill="x", padx=14, pady=(0, 8))
        for caption, value, color in (
            ("STOCK", format_units(product.stock), status_accent(self.theme, status)),
            ("MÍNIMO", format_units(product.min_stock), self.theme.c("text_dim")),
            ("PRECIO", format_money(product.price), self.theme.c("text")),
            ("ÚLTIMO MOV.", relative_time(product.updated_at), self.theme.c("text_faint")),
        ):
            block = tk.Frame(metrics, bg=self.theme.c("surface_alt"))
            block.pack(side="left", padx=(0, 28))
            tk.Label(
                block,
                text=caption,
                bg=self.theme.c("surface_alt"),
                fg=self.theme.c("text_faint"),
                font=self.theme.font("micro", "bold"),
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                block,
                text=value,
                bg=self.theme.c("surface_alt"),
                fg=color,
                font=self.theme.font("subtitle", "bold", mono=True),
                anchor="w",
            ).pack(fill="x")

        actions = tk.Frame(box, bg=self.theme.c("surface_alt"))
        actions.pack(fill="x", padx=14, pady=(2, 12))
        ActionButton(
            actions,
            self.theme,
            "REGISTRAR SALIDA (-1)",
            lambda: self._choose("sale"),
            variant="danger",
            compact=True,
        ).pack(side="left")
        ActionButton(
            actions,
            self.theme,
            "REABASTECER",
            lambda: self._choose("restock"),
            variant="primary",
            compact=True,
        ).pack(side="left", padx=(8, 0))

    def _choose(self, action: str) -> None:
        if self._product is None:
            return
        self.result = {"action": action, "product": self._product, "quantity": 1}
        self._close()
