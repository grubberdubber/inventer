"""SQLite persistence layer with atomic transactions.

Every worker thread receives its own connection (thread-local), so inventory
queries and mutations can run safely from the executor without blocking the
Tkinter main loop. Writes are wrapped in ``BEGIN IMMEDIATE`` transactions.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .inventory import (
    Movement,
    Product,
    ValidationError,
    validate_product,
)

logger = logging.getLogger("inventer.database")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT    NOT NULL UNIQUE,
    barcode     TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    unit        TEXT    NOT NULL DEFAULT 'Unidad',
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    min_stock   INTEGER NOT NULL DEFAULT 1 CHECK (min_stock >= 1),
    max_stock   INTEGER NOT NULL DEFAULT 1 CHECK (max_stock >= 1),
    price       REAL    NOT NULL DEFAULT 0 CHECK (price >= 0),
    cost        REAL    NOT NULL DEFAULT 0 CHECK (cost >= 0),
    supplier    TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS movements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('IN', 'OUT')),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock, min_stock);
CREATE INDEX IF NOT EXISTS idx_movements_created ON movements(created_at DESC);
"""

# (sku, barcode, name, category, unit, stock, min, max, price, cost, supplier)
_SEED_PRODUCTS: tuple[tuple[Any, ...], ...] = (
    ("LAC-001", "7501000110012", "Leche Entera 1L", "Lácteos", "Unidad", 48, 24, 120, 1.35, 1.05, "Lácteos del Valle"),
    ("LAC-002", "7501000110029", "Yogur Natural 900g", "Lácteos", "Unidad", 12, 18, 80, 2.45, 1.80, "Lácteos del Valle"),
    ("LAC-003", "7501000110036", "Queso Manchego 250g", "Lácteos", "Unidad", 7, 10, 40, 4.90, 3.60, "Lácteos del Valle"),
    ("CAR-001", "7501000220018", "Pechuga de Pollo kg", "Carnes", "Kg", 26, 15, 60, 5.80, 4.20, "Frigoríficos Andinos"),
    ("CAR-002", "7501000220025", "Carne Molida 500g", "Carnes", "Unidad", 0, 10, 50, 4.30, 3.10, "Frigoríficos Andinos"),
    ("CAR-003", "7501000220032", "Chuleta de Cerdo kg", "Carnes", "Kg", 31, 12, 45, 6.20, 4.65, "Frigoríficos Andinos"),
    ("FRV-001", "7501000330014", "Manzana Fuji kg", "Frutas y Verduras", "Kg", 54, 20, 90, 1.95, 1.20, "Mercado Central"),
    ("FRV-002", "7501000330021", "Plátano kg", "Frutas y Verduras", "Kg", 38, 25, 100, 1.10, 0.65, "Mercado Central"),
    ("FRV-003", "7501000330038", "Tomate Pera kg", "Frutas y Verduras", "Kg", 9, 15, 70, 1.65, 0.95, "Mercado Central"),
    ("FRV-004", "7501000330045", "Lechuga Romana", "Frutas y Verduras", "Unidad", 15, 10, 40, 0.95, 0.55, "Mercado Central"),
    ("PAN-001", "7501000440011", "Pan de Molde 700g", "Panadería", "Unidad", 19, 12, 50, 2.10, 1.45, "Horno del Barrio"),
    ("PAN-002", "7501000440028", "Croissant de Mantequilla", "Panadería", "Unidad", 45, 20, 80, 0.85, 0.45, "Horno del Barrio"),
    ("BEB-001", "7501000550019", "Agua Mineral 1.5L", "Bebidas", "Unidad", 120, 40, 200, 0.70, 0.40, "Manantial Sur"),
    ("BEB-002", "7501000550026", "Refresco Cola 2L", "Bebidas", "Unidad", 64, 30, 150, 1.95, 1.30, "Distribuidora Norte"),
    ("BEB-003", "7501000550033", "Jugo de Naranja 1L", "Bebidas", "Unidad", 8, 16, 90, 2.25, 1.60, "Distribuidora Norte"),
    ("BEB-004", "7501000550040", "Café Molido 500g", "Bebidas", "Unidad", 26, 10, 40, 6.80, 5.10, "Tostadores del Sur"),
    ("DES-001", "7501000660017", "Arroz Blanco 1kg", "Despensa", "Unidad", 85, 25, 150, 1.25, 0.80, "Granos del Valle"),
    ("DES-002", "7501000660024", "Frijol Negro 1kg", "Despensa", "Unidad", 42, 20, 120, 1.90, 1.15, "Granos del Valle"),
    ("DES-003", "7501000660031", "Aceite de Girasol 1L", "Despensa", "Unidad", 5, 14, 60, 3.40, 2.55, "Aceites del Norte"),
    ("DES-004", "7501000660048", "Pasta Espagueti 500g", "Despensa", "Unidad", 73, 22, 140, 0.95, 0.60, "Molinos del Sur"),
    ("LIM-001", "7501000770015", "Detergente 1.5L", "Limpieza", "Unidad", 20, 12, 45, 4.60, 3.30, "Química Industrial"),
    ("LIM-002", "7501000770022", "Papel Higiénico 12u", "Limpieza", "Unidad", 23, 15, 60, 7.90, 5.90, "Papelera Central"),
    ("LIM-003", "7501000770039", "Limpiavidrios 750ml", "Limpieza", "Unidad", 3, 8, 30, 2.75, 1.85, "Química Industrial"),
    ("CON-001", "7501000880013", "Pizza Cuatro Quesos", "Congelados", "Unidad", 13, 8, 35, 4.50, 3.20, "Frío Express"),
    ("CON-002", "7501000880020", "Helado de Vainilla 1L", "Congelados", "Unidad", 6, 10, 40, 3.95, 2.70, "Frío Express"),
    ("CUI-001", "7501000990011", "Shampoo 400ml", "Cuidado Personal", "Unidad", 29, 12, 60, 4.20, 2.90, "Farmacéutica Andina"),
    ("CUI-002", "7501000990028", "Pasta Dental 100ml", "Cuidado Personal", "Unidad", 36, 18, 70, 2.60, 1.75, "Farmacéutica Andina"),
    ("CUI-003", "7501000990035", "Jabón de Tocador", "Cuidado Personal", "Unidad", 52, 20, 90, 1.15, 0.65, "Farmacéutica Andina"),
)

# (sku, kind, quantity, note, hours_ago)
_SEED_MOVEMENTS: tuple[tuple[str, str, int, str, float], ...] = (
    ("BEB-001", "OUT", 6, "Venta POS · Ticket #1042", 0.4),
    ("LAC-002", "OUT", 3, "Venta POS · Ticket #1041", 1.1),
    ("CAR-001", "IN", 24, "Recepción · Frigoríficos Andinos", 2.3),
    ("FRV-003", "OUT", 5, "Merma · producto dañado", 3.2),
    ("DES-003", "OUT", 2, "Venta POS · Ticket #1038", 4.1),
    ("PAN-001", "IN", 30, "Reposición de panadería", 5.4),
    ("LIM-003", "OUT", 4, "Venta POS · Ticket #1036", 6.8),
    ("LAC-001", "IN", 48, "Recepción · Lácteos del Valle", 8.2),
    ("CON-002", "OUT", 3, "Venta POS · Ticket #1034", 9.6),
    ("FRV-001", "IN", 40, "Recepción · Mercado Central", 11.3),
)


def _row_to_product(row: sqlite3.Row) -> Product:
    """Map a database row to an immutable product snapshot."""
    return Product(
        id=int(row["id"]),
        sku=str(row["sku"]),
        barcode=str(row["barcode"]),
        name=str(row["name"]),
        category=str(row["category"]),
        unit=str(row["unit"]),
        stock=int(row["stock"]),
        min_stock=int(row["min_stock"]),
        max_stock=int(row["max_stock"]),
        price=float(row["price"]),
        cost=float(row["cost"]),
        supplier=str(row["supplier"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _row_to_movement(row: sqlite3.Row) -> Movement:
    """Map a joined database row to an immutable movement snapshot."""
    return Movement(
        id=int(row["id"]),
        sku=str(row["sku"]),
        product_name=str(row["product_name"]),
        kind=str(row["kind"]),
        quantity=int(row["quantity"]),
        note=str(row["note"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


class Database:
    """Thread-safe SQLite repository for catalog and stock movements."""

    def __init__(self, path: Path) -> None:
        """Create a repository bound to the given database file.

        Args:
            path: SQLite database path.
        """
        self.path = Path(path)
        self._local = threading.local()
        self._init_lock = threading.Lock()

    # ------------------------------------------------------------------ setup

    def _connection(self) -> sqlite3.Connection:
        """Return the current thread's connection, creating it on demand."""
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.path,
                timeout=15.0,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            self._local.connection = connection
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a write operation inside an atomic immediate transaction."""
        connection = self._connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    def initialize(self) -> None:
        """Create the schema and seed the demo catalog when empty."""
        with self._init_lock:
            connection = self._connection()
            connection.executescript(_SCHEMA)
            existing = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            if existing:
                return

            logger.info("Seeding catalog with %d demo products", len(_SEED_PRODUCTS))
            now = datetime.now()
            with self._transaction() as tx:
                for index, product in enumerate(_SEED_PRODUCTS):
                    tx.execute(
                        """
                        INSERT INTO products (
                            sku, barcode, name, category, unit, stock, min_stock,
                            max_stock, price, cost, supplier, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (*product, (now - timedelta(minutes=index * 9)).isoformat(timespec="seconds")),
                    )

                ids_by_sku = {
                    str(row["sku"]): int(row["id"])
                    for row in tx.execute("SELECT id, sku FROM products")
                }
                for sku, kind, quantity, note, hours_ago in _SEED_MOVEMENTS:
                    product_id = ids_by_sku.get(sku)
                    if product_id is None:
                        continue
                    tx.execute(
                        """
                        INSERT INTO movements (product_id, kind, quantity, note, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            product_id,
                            kind,
                            quantity,
                            note,
                            (now - timedelta(hours=hours_ago)).isoformat(timespec="seconds"),
                        ),
                    )

    # ------------------------------------------------------------------ reads

    def list_products(self) -> list[Product]:
        """Return every product in the catalog ordered by name."""
        rows = self._connection().execute(
            "SELECT * FROM products ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [_row_to_product(row) for row in rows]

    def get_product(self, product_id: int) -> Product | None:
        """Fetch one product by primary key."""
        row = self._connection().execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return _row_to_product(row) if row else None

    def get_by_barcode(self, barcode: str) -> Product | None:
        """Fetch one product by its EAN barcode."""
        row = self._connection().execute(
            "SELECT * FROM products WHERE barcode = ?", (barcode.strip(),)
        ).fetchone()
        return _row_to_product(row) if row else None

    def list_categories(self) -> list[str]:
        """Return the distinct catalog categories."""
        rows = self._connection().execute(
            "SELECT DISTINCT category FROM products ORDER BY category COLLATE NOCASE"
        ).fetchall()
        return [str(row["category"]) for row in rows]

    def list_movements(self, limit: int = 10) -> list[Movement]:
        """Return the most recent stock movements with product context."""
        safe_limit = max(1, min(int(limit), 500))
        rows = self._connection().execute(
            """
            SELECT m.id, m.kind, m.quantity, m.note, m.created_at,
                   p.sku, p.name AS product_name
            FROM movements AS m
            JOIN products AS p ON p.id = m.product_id
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [_row_to_movement(row) for row in rows]

    # -------------------------------------------------------------- mutations

    def save_product(self, payload: Mapping[str, Any]) -> Product:
        """Insert or update a product after strict validation.

        Args:
            payload: Raw form values. ``product_id`` selects update mode.

        Returns:
            The persisted product snapshot.

        Raises:
            ValidationError: If the payload or uniqueness constraints fail.
        """
        draft = validate_product(payload)
        now = datetime.now().isoformat(timespec="seconds")

        with self._transaction() as tx:
            try:
                if draft.product_id is None:
                    cursor = tx.execute(
                        """
                        INSERT INTO products (
                            sku, barcode, name, category, unit, stock, min_stock,
                            max_stock, price, cost, supplier, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            draft.sku,
                            draft.barcode,
                            draft.name,
                            draft.category,
                            draft.unit,
                            draft.stock,
                            draft.min_stock,
                            draft.max_stock,
                            draft.price,
                            draft.cost,
                            draft.supplier,
                            now,
                        ),
                    )
                    product_id = int(cursor.lastrowid)
                    if draft.stock > 0:
                        tx.execute(
                            """
                            INSERT INTO movements (product_id, kind, quantity, note, created_at)
                            VALUES (?, 'IN', ?, 'Stock inicial de catálogo', ?)
                            """,
                            (product_id, draft.stock, now),
                        )
                    logger.info("Product created sku=%s id=%s", draft.sku, product_id)
                else:
                    previous = tx.execute(
                        "SELECT stock FROM products WHERE id = ?",
                        (draft.product_id,),
                    ).fetchone()
                    if previous is None:
                        raise ValidationError("El producto ya no existe en el catálogo.")

                    tx.execute(
                        """
                        UPDATE products
                        SET sku = ?, barcode = ?, name = ?, category = ?, unit = ?,
                            stock = ?, min_stock = ?, max_stock = ?, price = ?,
                            cost = ?, supplier = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            draft.sku,
                            draft.barcode,
                            draft.name,
                            draft.category,
                            draft.unit,
                            draft.stock,
                            draft.min_stock,
                            draft.max_stock,
                            draft.price,
                            draft.cost,
                            draft.supplier,
                            now,
                            draft.product_id,
                        ),
                    )
                    product_id = draft.product_id
                    delta = draft.stock - int(previous["stock"])
                    if delta:
                        tx.execute(
                            """
                            INSERT INTO movements (product_id, kind, quantity, note, created_at)
                            VALUES (?, ?, ?, 'Ajuste desde edición de producto', ?)
                            """,
                            (product_id, "IN" if delta > 0 else "OUT", abs(delta), now),
                        )
                    logger.info("Product updated sku=%s id=%s", draft.sku, product_id)
            except sqlite3.IntegrityError as exc:
                message = str(exc).lower()
                if "barcode" in message:
                    raise ValidationError("El código de barras ya está registrado.") from exc
                if "sku" in message:
                    raise ValidationError("El SKU ya está registrado.") from exc
                raise ValidationError("Conflicto de integridad al guardar el producto.") from exc

        product = self.get_product(product_id)
        if product is None:
            raise ValidationError("No se pudo recuperar el producto guardado.")
        return product

    def adjust_stock(self, product_id: int, delta: int, note: str) -> Product:
        """Atomically adjust stock and record the matching movement.

        Args:
            product_id: Target product primary key.
            delta: Signed quantity. Positive means ingress, negative egress.
            note: Short audit description.

        Returns:
            The updated product snapshot.

        Raises:
            ValidationError: If the quantity is invalid or stock is insufficient.
        """
        try:
            delta = int(delta)
        except (TypeError, ValueError) as exc:
            raise ValidationError("La cantidad debe ser un número entero.") from exc
        if delta == 0:
            raise ValidationError("La cantidad del movimiento debe ser distinta de cero.")

        clean_note = (note or "").strip()
        if len(clean_note) > 120:
            raise ValidationError("La nota del movimiento no puede superar 120 caracteres.")

        now = datetime.now().isoformat(timespec="seconds")
        kind = "IN" if delta > 0 else "OUT"

        with self._transaction() as tx:
            row = tx.execute(
                "SELECT stock, name FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if row is None:
                raise ValidationError("El producto ya no existe en el catálogo.")

            new_stock = int(row["stock"]) + delta
            if new_stock < 0:
                raise ValidationError("Stock insuficiente para registrar la salida.")

            tx.execute(
                "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
                (new_stock, now, product_id),
            )
            tx.execute(
                """
                INSERT INTO movements (product_id, kind, quantity, note, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (product_id, kind, abs(delta), clean_note, now),
            )
            logger.info(
                "Stock adjusted product_id=%s kind=%s qty=%s new=%s",
                product_id,
                kind,
                abs(delta),
                new_stock,
            )

        product = self.get_product(product_id)
        if product is None:
            raise ValidationError("No se pudo recuperar el producto actualizado.")
        return product

    def bulk_replenish(
        self,
        items: Sequence[tuple[int, int]],
        note: str = "Reposición masiva de stock",
    ) -> int:
        """Apply multiple ingress movements inside one atomic transaction.

        Args:
            items: ``(product_id, quantity)`` pairs with positive quantities.
            note: Audit description shared by every generated movement.

        Returns:
            The number of replenished products.

        Raises:
            ValidationError: If the batch is empty, duplicated or invalid.
        """
        if not items:
            raise ValidationError("No hay productos para reponer.")
        clean_note = (note or "Reposición masiva de stock").strip()
        if len(clean_note) > 120:
            raise ValidationError("La nota del movimiento no puede superar 120 caracteres.")

        normalized: list[tuple[int, int]] = []
        seen: set[int] = set()
        for raw_product_id, raw_quantity in items:
            try:
                product_id = int(raw_product_id)
                quantity = int(raw_quantity)
            except (TypeError, ValueError) as exc:
                raise ValidationError("La reposición contiene valores inválidos.") from exc
            if product_id <= 0 or quantity <= 0:
                raise ValidationError("Las cantidades de reposición deben ser positivas.")
            if product_id in seen:
                raise ValidationError("La reposición contiene productos duplicados.")
            seen.add(product_id)
            normalized.append((product_id, quantity))

        now = datetime.now().isoformat(timespec="seconds")
        with self._transaction() as tx:
            for product_id, quantity in normalized:
                row = tx.execute(
                    "SELECT stock FROM products WHERE id = ?", (product_id,)
                ).fetchone()
                if row is None:
                    raise ValidationError(
                        "Uno de los productos de la reposición ya no existe."
                    )
                tx.execute(
                    "UPDATE products SET stock = stock + ?, updated_at = ? WHERE id = ?",
                    (quantity, now, product_id),
                )
                tx.execute(
                    """
                    INSERT INTO movements (product_id, kind, quantity, note, created_at)
                    VALUES (?, 'IN', ?, ?, ?)
                    """,
                    (product_id, quantity, clean_note, now),
                )

        logger.info(
            "Bulk replenishment applied products=%d units=%d",
            len(normalized),
            sum(quantity for _, quantity in normalized),
        )
        return len(normalized)

    def close(self) -> None:
        """Close the current thread's connection, if any."""
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None
