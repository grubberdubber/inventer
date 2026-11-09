"""High-performance ttk widgets and the dark industrial visual language.

The widgets in this module are presentation-only: they receive immutable
snapshots from the main window and never touch the persistence layer directly.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from core.inventory import StockStatus


class Theme:
    """Resolved palette, typography and spacing for the application."""

    def __init__(self, spec: Mapping[str, Any], root: tk.Misc) -> None:
        """Resolve the theme against the fonts available to the Tk runtime.

        Args:
            spec: Parsed ``configs/theme.json`` content.
            root: Tk root used to enumerate font families.
        """
        self.spec = spec
        self.palette: dict[str, str] = dict(spec.get("palette", {}))
        self.layout: dict[str, int] = dict(spec.get("layout", {}))
        self.window: dict[str, Any] = dict(spec.get("window", {}))

        font_spec = spec.get("fonts", {})
        self.sizes: dict[str, int] = dict(font_spec.get("sizes", {}))
        available = set(tkfont.families(root))
        self.sans = self._resolve(font_spec.get("sans", []), available, "DejaVu Sans")
        self.mono = self._resolve(font_spec.get("mono", []), available, "DejaVu Sans Mono")
        self._font_cache: dict[tuple[str, str, bool], tuple[str, int, str]] = {}

    @staticmethod
    def _resolve(candidates: Sequence[str], available: set[str], fallback: str) -> str:
        """Return the first installed font family from the candidate list."""
        for candidate in candidates:
            if candidate in available:
                return candidate
        return fallback

    def c(self, key: str) -> str:
        """Return a palette color, a literal hex color, or a loud fallback.

        Args:
            key: Palette key (for example ``accent``) or a literal ``#RRGGBB``
                value used by semantic widget variants.

        Returns:
            The resolved color.
        """
        if key.startswith("#"):
            return key
        return self.palette.get(key, "#FF00FF")

    def font(
        self,
        role: str = "body",
        weight: str = "normal",
        *,
        mono: bool = False,
    ) -> tuple[str, int, str]:
        """Build a cached Tk font tuple for a semantic role."""
        cache_key = (role, weight, mono)
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return cached
        size = self.sizes.get(role, self.sizes.get("body", 10))
        family = self.mono if mono else self.sans
        resolved = (family, size, weight)
        self._font_cache[cache_key] = resolved
        return resolved


def configure_styles(root: tk.Misc, theme: Theme) -> None:
    """Apply the industrial dark theme to every ttk control used by the app."""
    style = ttk.Style(root)
    with contextlib.suppress(tk.TclError):
        style.theme_use("clam")

    palette = theme.palette
    row_height = int(theme.layout.get("tree_row_height", 34))

    style.configure(
        ".",
        background=palette["bg"],
        foreground=palette["text"],
        font=theme.font("body"),
        focuscolor=palette["bg"],
    )

    style.configure(
        "Data.Treeview",
        background=palette["surface"],
        fieldbackground=palette["surface"],
        foreground=palette["text"],
        bordercolor=palette["border_soft"],
        borderwidth=0,
        relief="flat",
        rowheight=row_height,
        font=theme.font("caption"),
    )
    style.configure(
        "Data.Treeview.Heading",
        background=palette["surface"],
        foreground=palette["text_faint"],
        bordercolor=palette["border_soft"],
        borderwidth=0,
        relief="flat",
        font=theme.font("micro", "bold"),
        padding=(8, 10),
    )
    style.map(
        "Data.Treeview.Heading",
        background=[("active", palette["surface_alt"])],
        foreground=[("active", palette["text_dim"])],
    )
    style.map(
        "Data.Treeview",
        background=[("selected", palette["accent_dim"])],
        foreground=[("selected", palette["text"])],
    )

    style.configure(
        "Dark.Vertical.TScrollbar",
        gripcount=0,
        background=palette["border"],
        darkcolor=palette["border"],
        lightcolor=palette["border"],
        troughcolor=palette["surface"],
        bordercolor=palette["surface"],
        arrowcolor=palette["text_faint"],
        relief="flat",
        width=9,
    )
    style.map(
        "Dark.Vertical.TScrollbar",
        background=[("active", palette["text_faint"]), ("pressed", palette["accent"])],
    )

    style.configure(
        "Dark.TCombobox",
        fieldbackground=palette["surface_alt"],
        background=palette["surface_alt"],
        foreground=palette["text"],
        arrowcolor=palette["text_dim"],
        bordercolor=palette["border"],
        lightcolor=palette["surface_alt"],
        darkcolor=palette["surface_alt"],
        padding=(10, 6),
        arrowsize=13,
        font=theme.font("caption"),
    )
    style.map(
        "Dark.TCombobox",
        fieldbackground=[
            ("readonly", palette["surface_alt"]),
            ("disabled", palette["surface"]),
        ],
        foreground=[
            ("readonly", palette["text"]),
            ("disabled", palette["text_faint"]),
        ],
        selectbackground=[("readonly", palette["surface_alt"])],
        selectforeground=[("readonly", palette["text"])],
        bordercolor=[("focus", palette["accent"])],
        arrowcolor=[("active", palette["accent"])],
    )

    style.configure(
        "Dark.TCheckbutton",
        background=palette["surface"],
        foreground=palette["text_dim"],
        font=theme.font("caption"),
        focuscolor=palette["surface"],
        padding=(2, 4),
    )
    style.map(
        "Dark.TCheckbutton",
        background=[("active", palette["surface"])],
        foreground=[("active", palette["text"]), ("selected", palette["text"])],
        indicatorcolor=[
            ("selected", palette["accent"]),
            ("!selected", palette["surface_alt"]),
        ],
    )

    root.option_add("*TCombobox*Listbox.background", palette["surface_alt"])
    root.option_add("*TCombobox*Listbox.foreground", palette["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", palette["accent_dim"])
    root.option_add("*TCombobox*Listbox.selectForeground", palette["accent"])
    root.option_add("*TCombobox*Listbox.font", theme.font("caption"))


# --------------------------------------------------------------------- format


def format_money(value: float, symbol: str = "$") -> str:
    """Format a monetary amount with Spanish separators."""
    raw = f"{value:,.2f}"
    raw = raw.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{symbol} {raw}"


def format_units(value: int | float) -> str:
    """Format an integer magnitude with dot thousands separators."""
    return f"{int(value):,}".replace(",", ".")


def truncate(text: str, limit: int) -> str:
    """Shorten text with an ellipsis when it exceeds the limit."""
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def relative_time(moment: datetime, now: datetime | None = None) -> str:
    """Render a compact relative timestamp in Spanish."""
    reference = now or datetime.now()
    seconds = max((reference - moment).total_seconds(), 0)
    if seconds < 60:
        return "ahora"
    if seconds < 3600:
        return f"hace {int(seconds // 60)} min"
    if seconds < 86400:
        return f"hace {int(seconds // 3600)} h"
    return f"hace {int(seconds // 86400)} d"


_WEEKDAYS = ("LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM")
_MONTHS = (
    "ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
    "JUL", "AGO", "SEP", "OCT", "NOV", "DIC",
)


def format_date_es(moment: datetime) -> str:
    """Render an uppercase Spanish short date, e.g. ``LUN 09 NOV``."""
    return f"{_WEEKDAYS[moment.weekday()]} {moment.day:02d} {_MONTHS[moment.month - 1]}"


def status_accent(theme: Theme, status: StockStatus) -> str:
    """Map a stock status to its semantic accent color."""
    return {
        StockStatus.OUT: theme.c("danger"),
        StockStatus.CRITICAL: theme.c("warning"),
        StockStatus.LOW: theme.c("info"),
        StockStatus.OK: theme.c("accent"),
    }[status]


def status_tag(status: StockStatus) -> str:
    """Return the Treeview tag name for a stock status."""
    return {
        StockStatus.OUT: "out",
        StockStatus.CRITICAL: "critical",
        StockStatus.LOW: "low",
        StockStatus.OK: "ok",
    }[status]


def bind_recursive(widget: tk.Misc, sequence: str, callback: Callable[..., Any]) -> None:
    """Bind an event on a widget and all of its descendants."""
    widget.bind(sequence, callback)
    for child in widget.winfo_children():
        bind_recursive(child, sequence, callback)


def pill(
    master: tk.Misc,
    theme: Theme,
    text: str,
    *,
    fg: str,
    bg: str,
    border: str | None = None,
) -> tk.Label:
    """Build a compact status pill label."""
    return tk.Label(
        master,
        text=text,
        bg=bg,
        fg=fg,
        font=theme.font("micro", "bold"),
        padx=8,
        pady=3,
        highlightthickness=1,
        highlightbackground=border or bg,
        bd=0,
    )


# --------------------------------------------------------------------- widgets


class Card(tk.Frame):
    """Panel surface with a crisp one-pixel border."""

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        *,
        padding: int = 16,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master,
            bg=theme.c("surface"),
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.c("border_soft"),
            highlightcolor=theme.c("border_soft"),
            **kwargs,
        )
        self.theme = theme
        self.body = tk.Frame(self, bg=theme.c("surface"))
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class KpiCard(tk.Frame):
    """KPI tile with an accent rail, value and contextual caption."""

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        *,
        label: str,
        accent: str,
        compact: bool = False,
    ) -> None:
        super().__init__(
            master,
            bg=theme.c("surface"),
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.c("border_soft"),
            highlightcolor=theme.c("border_soft"),
        )
        self.theme = theme
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        rail = tk.Frame(self, bg=accent, width=3)
        rail.grid(row=0, column=0, sticky="ns")

        content = tk.Frame(self, bg=theme.c("surface"))
        content.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(14, 12),
            pady=12 if compact else 14,
        )

        self.label = tk.Label(
            content,
            text=label,
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("micro", "bold"),
            anchor="w",
        )
        self.label.pack(fill="x")

        self._value_text = "—"
        self._value_max_size = theme.sizes.get("title" if compact else "display", 26)
        self._value_size = self._value_max_size
        self._value_measure = tkfont.Font(
            root=self,
            family=theme.mono,
            size=self._value_size,
            weight="bold",
        )
        self.value_label = tk.Label(
            content,
            text=self._value_text,
            bg=theme.c("surface"),
            fg=theme.c("text"),
            font=(theme.mono, self._value_size, "bold"),
            anchor="w",
        )
        self.value_label.pack(fill="x", pady=(5, 2))
        self.value_label.bind("<Configure>", self._fit_value)
        self.after_idle(self._fit_value)

        self.caption_label = tk.Label(
            content,
            text="Sincronizando…",
            bg=theme.c("surface"),
            fg=theme.c("text_dim"),
            font=theme.font("micro"),
            anchor="w",
        )
        self.caption_label.pack(fill="x")

    def set(
        self,
        value: str,
        caption: str | None = None,
        *,
        value_color: str | None = None,
        caption_color: str | None = None,
    ) -> None:
        """Update the tile content in place."""
        self._value_text = value
        self.value_label.configure(text=value)
        if value_color:
            self.value_label.configure(fg=value_color)
        if caption is not None:
            self.caption_label.configure(text=caption)
        if caption_color:
            self.caption_label.configure(fg=caption_color)
        self.after_idle(self._fit_value)

    def _fit_value(self, _event: tk.Event | None = None) -> None:
        """Shrink the value font just enough to avoid clipped digits."""
        available = self.value_label.winfo_width()
        if available <= 1:
            return
        size = self._value_max_size
        self._value_measure.configure(size=size)
        while size > 10 and self._value_measure.measure(self._value_text) > available:
            size -= 1
            self._value_measure.configure(size=size)
        if size != self._value_size:
            self._value_size = size
            self.value_label.configure(font=(self.theme.mono, size, "bold"))


class ActionButton(tk.Button):
    """Flat action button with hover feedback and semantic variants."""

    _VARIANTS = {
        "primary": ("accent", "#04110B", "accent_hover", "#04110B"),
        "ghost": ("surface_alt", "text_dim", "surface_high", "text"),
        "outline": ("surface", "text_dim", "surface_alt", "text"),
        "danger": ("surface_alt", "danger", "danger_dim", "danger_hover"),
    }

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        text: str,
        command: Callable[[], Any] | None = None,
        *,
        variant: str = "primary",
        compact: bool = False,
    ) -> None:
        bg_key, fg_key, hover_bg_key, hover_fg_key = self._VARIANTS.get(
            variant, self._VARIANTS["primary"]
        )
        bg = theme.c(bg_key)
        fg = theme.c(fg_key)
        self._hover_bg = theme.c(hover_bg_key)
        self._hover_fg = theme.c(hover_fg_key)
        self._base_bg = bg
        self._base_fg = fg
        self._enabled = True
        self.theme = theme

        super().__init__(
            master,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=self._hover_bg,
            activeforeground=self._hover_fg,
            disabledforeground=theme.c("text_faint"),
            relief="flat",
            bd=0,
            highlightthickness=1 if variant in ("outline", "danger") else 0,
            highlightbackground=(
                theme.c("danger_dim") if variant == "danger" else theme.c("border")
            ),
            highlightcolor=(
                theme.c("danger") if variant == "danger" else theme.c("border")
            ),
            padx=9 if compact else 14,
            pady=4 if compact else 8,
            font=theme.font("micro" if compact else "caption", "bold"),
            cursor="hand2",
            takefocus=0,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event: tk.Event) -> None:
        if self._enabled:
            self.configure(bg=self._hover_bg, fg=self._hover_fg)

    def _on_leave(self, _event: tk.Event) -> None:
        if self._enabled:
            self.configure(bg=self._base_bg, fg=self._base_fg)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the button without rebuilding it."""
        self._enabled = enabled
        self.configure(
            state="normal" if enabled else "disabled",
            cursor="hand2" if enabled else "arrow",
            bg=self._base_bg if enabled else self.theme.c("surface"),
            fg=self._base_fg if enabled else self.theme.c("text_faint"),
        )


class NavButton(tk.Frame):
    """Sidebar navigation item with active rail and live badge."""

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        *,
        icon: str,
        label: str,
        command: Callable[[], Any],
    ) -> None:
        super().__init__(master, bg=theme.c("sidebar"), height=44, cursor="hand2")
        self.theme = theme
        self._command = command
        self._active = False
        self.pack_propagate(False)

        self.marker = tk.Frame(self, bg=theme.c("sidebar"), width=3)
        self.marker.pack(side="left", fill="y")

        self.inner = tk.Frame(self, bg=theme.c("sidebar"))
        self.inner.pack(side="left", fill="both", expand=True, padx=(13, 10))

        self.icon = tk.Label(
            self.inner,
            text=icon,
            bg=theme.c("sidebar"),
            fg=theme.c("text_faint"),
            font=theme.font("body"),
        )
        self.icon.pack(side="left")

        self.label = tk.Label(
            self.inner,
            text=label,
            bg=theme.c("sidebar"),
            fg=theme.c("text_dim"),
            font=theme.font("caption"),
        )
        self.label.pack(side="left", padx=(10, 0))

        self.badge = tk.Label(
            self.inner,
            text="",
            bg=theme.c("danger_dim"),
            fg=theme.c("danger"),
            font=theme.font("micro", "bold"),
            padx=7,
            pady=2,
        )

        bind_recursive(self, "<Button-1>", self._activate)
        bind_recursive(self, "<Enter>", self._hover_on)
        bind_recursive(self, "<Leave>", self._hover_off)

    def _activate(self, _event: tk.Event) -> None:
        self._command()

    def _hover_on(self, _event: tk.Event) -> None:
        if not self._active:
            self._paint(self.theme.c("surface_alt"), self.theme.c("text"))
            self.icon.configure(fg=self.theme.c("text_dim"))

    def _hover_off(self, _event: tk.Event) -> None:
        if not self._active:
            self._paint(self.theme.c("sidebar"), self.theme.c("text_dim"))
            self.icon.configure(fg=self.theme.c("text_faint"))

    def _paint(self, background: str, foreground: str) -> None:
        for widget in (self, self.inner):
            widget.configure(bg=background)
        self.marker.configure(bg=background)
        self.icon.configure(bg=background)
        self.label.configure(bg=background, fg=foreground)

    def set_active(self, active: bool) -> None:
        """Switch the item between active and idle styling."""
        self._active = active
        if active:
            self._paint(self.theme.c("sidebar_active"), self.theme.c("text"))
            self.marker.configure(bg=self.theme.c("accent"))
            self.icon.configure(fg=self.theme.c("accent"))
        else:
            self._paint(self.theme.c("sidebar"), self.theme.c("text_dim"))
            self.icon.configure(fg=self.theme.c("text_faint"))

    def set_badge(self, count: int) -> None:
        """Show or hide the alert counter."""
        if count > 0:
            self.badge.configure(text=str(count))
            self.badge.pack(side="right")
        else:
            self.badge.pack_forget()


class SearchBox(tk.Frame):
    """Dark search field with placeholder and focus ring."""

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        *,
        placeholder: str,
        on_change: Callable[[str], Any] | None = None,
        on_submit: Callable[[str], Any] | None = None,
        width: int = 30,
    ) -> None:
        super().__init__(
            master,
            bg=theme.c("surface_alt"),
            highlightthickness=1,
            highlightbackground=theme.c("border"),
            highlightcolor=theme.c("border"),
        )
        self.theme = theme
        self._on_change = on_change
        self._on_submit = on_submit
        self.var = tk.StringVar(value="")

        self.icon_label = tk.Label(
            self,
            text="⌕",
            bg=theme.c("surface_alt"),
            fg=theme.c("text_faint"),
            font=theme.font("subtitle"),
        )
        self.icon_label.pack(side="left", padx=(10, 4))

        self.entry = tk.Entry(
            self,
            textvariable=self.var,
            bg=theme.c("surface_alt"),
            fg=theme.c("text"),
            insertbackground=theme.c("accent"),
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=theme.font("caption"),
            width=width,
        )
        self.entry.pack(side="left", fill="x", expand=True, pady=7, padx=(0, 10))

        self.placeholder = tk.Label(
            self,
            text=placeholder,
            bg=theme.c("surface_alt"),
            fg=theme.c("text_faint"),
            font=theme.font("caption"),
            cursor="xterm",
        )
        self.placeholder.place(x=32, rely=0.5, anchor="w")
        self.placeholder.bind("<Button-1>", lambda _event: self.entry.focus_set())

        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<Return>", self._submit)
        self.var.trace_add("write", self._changed)

    def _focus_in(self, _event: tk.Event) -> None:
        self.configure(highlightbackground=self.theme.c("accent"))
        self.placeholder.place_forget()

    def _focus_out(self, _event: tk.Event) -> None:
        self.configure(highlightbackground=self.theme.c("border"))
        if not self.var.get():
            self.placeholder.place(x=32, rely=0.5, anchor="w")

    def _changed(self, *_args: object) -> None:
        if self.var.get():
            self.placeholder.place_forget()
        elif self.focus_get() is not self.entry:
            self.placeholder.place(x=32, rely=0.5, anchor="w")
        if self._on_change:
            self._on_change(self.var.get())

    def _submit(self, _event: tk.Event) -> None:
        if self._on_submit:
            self._on_submit(self.var.get())

    def set_text(self, text: str) -> None:
        """Programmatically set the query."""
        self.var.set(text)

    def get_text(self) -> str:
        """Return the current query."""
        return self.var.get()


@dataclass(frozen=True, slots=True)
class TableColumn:
    """Declarative data-grid column definition."""

    key: str
    title: str
    width: int
    anchor: str = "w"
    stretch: bool = False


class DataTable(tk.Frame):
    """Treeview-backed data grid with striping, empty state and row tags."""

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        columns: Sequence[TableColumn],
        *,
        height: int = 10,
        empty_text: str = "Sin datos para mostrar",
        on_activate: Callable[[str], Any] | None = None,
        on_select: Callable[[str | None], Any] | None = None,
    ) -> None:
        super().__init__(master, bg=theme.c("surface"))
        self.theme = theme
        self._on_activate = on_activate
        self._on_select = on_select
        self._empty_text = empty_text
        self._row_height = int(theme.layout.get("tree_row_height", 34))
        self._visible_rows = -1

        self.grid_rowconfigure(0, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            self,
            columns=[column.key for column in columns],
            show="headings",
            height=height,
            selectmode="browse",
            style="Data.Treeview",
        )
        for column in columns:
            self.tree.heading(
                column.key,
                text=column.title,
                anchor=column.anchor,
            )
            self.tree.column(
                column.key,
                width=column.width,
                minwidth=max(46, int(column.width * 0.65)),
                anchor=column.anchor,
                stretch=column.stretch,
            )

        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.tree.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self.tree.configure(yscrollcommand=self.scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="ew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.bind("<Configure>", self._fit_visible_rows)
        self.after_idle(self._fit_visible_rows)

        self.tree.tag_configure("stripe", background=theme.c("tree_alt"))
        self.tree.tag_configure("in", foreground=theme.c("accent"))
        self.tree.tag_configure("out", foreground=theme.c("danger"))
        self.tree.tag_configure("critical", foreground=theme.c("warning"))
        self.tree.tag_configure("low", foreground=theme.c("info"))
        self.tree.tag_configure("ok", foreground=theme.c("accent"))

        self.empty_label = tk.Label(
            self,
            text=empty_text,
            bg=theme.c("surface"),
            fg=theme.c("text_faint"),
            font=theme.font("caption"),
            padx=16,
            pady=10,
        )
        self._row_clip = tk.Frame(self, bg=theme.c("surface"), height=2)

        self.tree.bind("<Double-1>", self._handle_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._handle_select)
        self.tree.bind("<Configure>", self._position_row_clip, add="+")

    def _fit_visible_rows(self, _event: tk.Event | None = None) -> None:
        """Size the viewport to whole rows so text is never cut in half."""
        height = self.winfo_height()
        if height <= 1:
            return
        heading_height = self._row_height + 3
        children = self.tree.get_children()
        if children and self.tree.yview()[0] <= 0.0:
            bbox = self.tree.bbox(children[0])
            if bbox and 0 < int(bbox[1]) < self._row_height * 2:
                heading_height = max(heading_height, int(bbox[1]) + 2)
        rows = max(1, (height - heading_height) // self._row_height)
        if rows != self._visible_rows:
            self._visible_rows = rows
            self.tree.configure(height=rows)
        self.after_idle(self._position_row_clip)

    def _position_row_clip(self, _event: tk.Event | None = None) -> None:
        """Cover the two-pixel Tk sliver of the next partially visible row."""
        height = self.tree.winfo_height()
        width = self.tree.winfo_width()
        if height <= 2 or width <= 1:
            return
        self._row_clip.place(x=0, y=height - 2, width=width, height=2)
        self._row_clip.lift()

    def _handle_double_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self._on_activate:
            self.tree.selection_set(row)
            self._on_activate(row)

    def _handle_select(self, _event: tk.Event) -> None:
        if self._on_select:
            self._on_select(self.selected_id())

    def set_rows(
        self,
        rows: Iterable[tuple[str, Sequence[Any], Sequence[str]]],
    ) -> None:
        """Replace the grid contents while preserving a valid selection."""
        selected = self.selected_id()
        materialized = list(rows)
        self.tree.delete(*self.tree.get_children())
        for item_id, values, tags in materialized:
            self.tree.insert(
                "",
                "end",
                iid=item_id,
                values=tuple(values),
                tags=tuple(tags),
            )
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.focus(selected)
        if materialized:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        self.after_idle(self._fit_visible_rows)

    def selected_id(self) -> str | None:
        """Return the selected row identifier, if any."""
        selection = self.tree.selection()
        return selection[0] if selection else None

    def select(self, item_id: str) -> None:
        """Select a row programmatically when it exists."""
        if self.tree.exists(item_id):
            self.tree.selection_set(item_id)
            self.tree.focus(item_id)

    def set_empty_text(self, text: str) -> None:
        """Update the empty-state copy."""
        self.empty_label.configure(text=text)

    def focus_first(self) -> None:
        """Move keyboard focus into the grid."""
        children = self.tree.get_children()
        if children:
            self.tree.focus(children[0])
        self.tree.focus_set()


class Meter(tk.Canvas):
    """Thin coverage meter used by the category health telemetry."""

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        *,
        height: int = 6,
        color: str | None = None,
    ) -> None:
        super().__init__(
            master,
            height=height,
            bg=theme.c("surface"),
            highlightthickness=0,
            bd=0,
        )
        self.theme = theme
        self._value = 0.0
        self._color = color or theme.c("accent")
        self.bind("<Configure>", lambda _event: self._draw())

    def set(self, value: float, color: str | None = None) -> None:
        """Set the 0..100 coverage value and optional fill color."""
        self._value = max(0.0, min(100.0, float(value)))
        if color:
            self._color = color
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 2 or height <= 0:
            return
        self.create_rectangle(0, 0, width, height, fill=self.theme.c("surface_high"), outline="")
        filled = width * self._value / 100.0
        if filled > 1:
            self.create_rectangle(0, 0, filled, height, fill=self._color, outline="")


class ToastManager:
    """Bottom-right ephemeral notifications rendered over the content area."""

    def __init__(self, host: tk.Misc, theme: Theme) -> None:
        self.host = host
        self.theme = theme
        self._frame: tk.Frame | None = None
        self._after_id: str | None = None

    def show(self, message: str, kind: str = "success", duration: int = 2800) -> None:
        """Display a toast message, replacing any visible toast."""
        self._dismiss()

        fg, bg = {
            "success": (self.theme.c("accent"), self.theme.c("accent_dim")),
            "danger": (self.theme.c("danger"), self.theme.c("danger_dim")),
            "warning": (self.theme.c("warning"), self.theme.c("warning_dim")),
            "info": (self.theme.c("info"), self.theme.c("info_dim")),
        }.get(kind, (self.theme.c("text"), self.theme.c("surface_high")))
        glyph = {"success": "✓", "danger": "!", "warning": "⚠", "info": "i"}.get(kind, "•")

        frame = tk.Frame(
            self.host,
            bg=self.theme.c("surface_alt"),
            highlightthickness=1,
            highlightbackground=fg,
            bd=0,
        )
        dot = tk.Label(
            frame,
            text=glyph,
            bg=bg,
            fg=fg,
            font=self.theme.font("caption", "bold"),
            padx=8,
            pady=5,
        )
        dot.pack(side="left", padx=(10, 0), pady=10)
        label = tk.Label(
            frame,
            text=message,
            bg=self.theme.c("surface_alt"),
            fg=self.theme.c("text"),
            font=self.theme.font("caption"),
            justify="left",
            wraplength=340,
            padx=10,
            pady=10,
        )
        label.pack(side="left")

        frame.place(relx=1.0, rely=1.0, x=-20, y=-20, anchor="se")
        frame.lift()
        self._frame = frame
        self._after_id = self.host.after(max(900, duration), self._dismiss)

    def _dismiss(self) -> None:
        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.host.after_cancel(self._after_id)
            self._after_id = None
        if self._frame is not None:
            with contextlib.suppress(tk.TclError):
                self._frame.destroy()
            self._frame = None
