# Arquitectura de INVENTER

Este documento describe las decisiones de diseño, el modelo de concurrencia y los puntos de extensión del núcleo de inventario.

## 1. Objetivos

- **Operación fluida:** la UI de Tkinter nunca debe bloquearse por una consulta o escritura.
- **Integridad:** ninguna mutación puede dejar stock y auditoría en estados inconsistentes.
- **Modularidad:** dominio, persistencia y presentación se comunican mediante contratos explícitos.
- **Observabilidad:** toda anomalía queda registrada con contexto suficiente para diagnosticarla.
- **Cero dependencias de runtime:** solo biblioteca estándar de Python.

## 2. Capas

```text
┌─────────────────────────────────────────────────────────────┐
│ ui/                                                         │
│ MainWindow · DashboardView · InventoryView · AlertsView     │
│ MovementsView · ProductDialog · RestockDialog · SaleDialog  │
└──────────────────────────────┬──────────────────────────────┘
                               │ snapshots inmutables / comandos
┌──────────────────────────────▼──────────────────────────────┐
│ core/inventory.py                                           │
│ Product · ProductDraft · Movement · StockStatus             │
│ validate_product · classify_stock · build_dashboard         │
└──────────────────────────────┬──────────────────────────────┘
                               │ ProductDraft / deltas
┌──────────────────────────────▼──────────────────────────────┐
│ core/database.py                                            │
│ Database · transacciones · conexiones thread-local          │
└──────────────────────────────┬──────────────────────────────┘
                               │ SQL
┌──────────────────────────────▼──────────────────────────────┐
│ SQLite (WAL)                                                │
│ products · movements · índices · restricciones              │
└─────────────────────────────────────────────────────────────┘
```

### `core/inventory.py`

No conoce SQLite ni Tkinter. Define:

- **Modelos inmutables** (`frozen=True, slots=True`): `Product`, `ProductDraft`, `Movement`, `CategoryHealth`, `DashboardStats`.
- **Validación** (`validate_product`): normaliza textos, parsea enteros/decimales y aplica reglas de negocio.
- **Clasificación** (`classify_stock`): `OUT → CRITICAL → LOW → OK`.
- **Reposición** (`reorder_quantity`): objetivo acotado por `max_stock`.
- **Telemetría** (`build_dashboard`): agregados por categoría, cobertura y salud.

### `core/database.py`

Implementa el repositorio. Cada hilo obtiene su propia conexión SQLite mediante `threading.local()`. Las conexiones configuran:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

Las escrituras usan `BEGIN IMMEDIATE` para adquirir el lock de escritura antes de leer y mutar, evitando carreras entre workers. El contexto `_transaction()` hace `COMMIT` en éxito y `ROLLBACK` ante cualquier excepción.

### `ui/`

La UI es la única capa que coordina workers. `MainWindow._run_async()` envía una tarea al `ThreadPoolExecutor` y sondea el `Future` con `root.after(40, poll)`. El resultado se entrega en el hilo de Tk, donde se actualizan los widgets.

## 3. Modelo de datos

```sql
CREATE TABLE products (
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

CREATE TABLE movements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('IN', 'OUT')),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);
```

### Invariantes

1. `movements.quantity` siempre es positiva; el signo se deriva de `kind`.
2. `products.stock` nunca es negativo.
3. Toda variación de stock genera exactamente un movimiento de auditoría.
4. `sku` y `barcode` son únicos a nivel de base.
5. `max_stock >= min_stock` se valida en dominio; la base refuerza los mínimos.

## 4. Concurrencia

```text
Tk mainloop
   │
   ├── submit(task) ──▶ ThreadPoolExecutor (N workers)
   │                         │
   │                         ├── conexión SQLite del worker
   │                         └── BEGIN IMMEDIATE … COMMIT
   │
   └── after(40ms, poll) ◀── Future done
```

- **Un solo escritor lógico:** `BEGIN IMMEDIATE` serializa las escrituras; SQLite WAL permite lecturas concurrentes.
- **Sin objetos compartidos mutables:** la UI recibe `Product`, `Movement` y `DashboardStats` inmutables.
- **Reintento de UI:** si se solicita refrescar mientras hay una carga en curso, se marca `_refresh_again` y se relanza al terminar.
- **Cierre ordenado:** `MainWindow.close()` cancela timers, apaga el executor y destruye el root.

## 5. Flujo de una mutación

1. El usuario confirma un modal.
2. `MainWindow._mutate()` envía la operación al executor.
3. `Database.save_product()` / `adjust_stock()` / `bulk_replenish()` valida y abre una transacción.
4. Se actualiza `products` y se inserta el `movement` correspondiente.
5. Si algo falla, `ROLLBACK` revierte ambos cambios.
6. La UI recibe el resultado, muestra un toast y solicita un refresco completo.

## 6. Decisiones y trade-offs

| Decisión | Motivo | Trade-off |
| --- | --- | --- |
| SQLite local | Cero infraestructura, ideal para una sucursal. | No apto para escritura concurrente multi-sucursal sin un servicio central. |
| Tkinter/ttk | Requisito del proyecto y máxima portabilidad. | Menor ecosistema visual que frameworks web. |
| Snapshots inmutables | Evita condiciones de carrera y estados parciales. | Copias adicionales en memoria. |
| Thread pool | Aísla I/O sin `asyncio` en Tk. | Requiere polling explícito con `after()`. |
| Validación duplicada | Defensa en profundidad (dominio + SQL). | Reglas deben mantenerse sincronizadas. |

## 7. Puntos de extensión

- **Multi-sucursal:** añadir `branch_id` a `products`/`movements` y un agregado por sucursal.
- **PostgreSQL:** implementar un repositorio con la misma interfaz que `Database`.
- **API REST:** exponer comandos de dominio desde un servicio separado y consumir snapshots.
- **Roles:** añadir operador a `movements` y autorización en la capa de aplicación.
- **Tema:** extender `configs/theme.json`; `Theme` resuelve fuentes y colores en runtime.

## 8. Observabilidad

- Logger `inventer` con rotación de 1 MB × 3 archivos.
- Eventos registrados: arranque, seed, altas/ediciones, ajustes, reposiciones, exportaciones, cierres y excepciones.
- La UI muestra estado de sincronización, errores y última carga en la statusbar.

## 9. Testing

- `tests/test_core.py`: dominio y persistencia con bases temporales.
- `tests/test_ui.py`: smoke test de la shell Tkinter; se omite sin display.
- CI ejecuta Ruff y pytest en matriz de Python; el job de UI usa Xvfb.
