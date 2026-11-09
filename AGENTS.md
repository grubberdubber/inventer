```markdown
# // INVENTER.SYS // AGENTS DIRECTIVE PROTOCOL v4.0.2

# TARGET: Supermarket Inventory Management Core (Ultra-Professional)

# CLASSIFICATION: INTERNAL // AUTOMATED AGENT INSTRUCTIONS
```

---

## 0x00 // SYSTEM OVERVIEW & DIRECTIVE

You are interfacing with the core architecture of **`inventer`**, an ultra-professional, enterprise-grade Supermarket Inventory Management System.

Your objective as an autonomous agent or developer is to maintain strict code integrity, zero-latency state synchronization, uncompromising modularity, and atomic transaction handling across all supply-chain vectors (stock ingestion, real-time POS syncing, low-stock triggers, barcode scanning simulation, and multi-branch warehouse auditing).

---

## 0x01 // CORE ARCHITECTURAL CONSTRAINTS

1. **GUI Framework Directive:** The graphical user interface **MUST** be built 100% in Python using the native **`tkinter`** library (coupled with `ttk` for modern themed styling). No external heavy UI frameworks (PyQt, PySide, Kivy) are permitted. The UI must render with crisp, high-density, low-overhead performance, featuring a sleek, dark-mode inspired industrial aesthetic.
2. **Data Persistence & Config:** While core execution and UI logic remain strictly Python/Tkinter, configuration files, logging vectors, and local caches may utilize lightweight serialized formats (`JSON`, `YAML`, or local `SQLite`).
3. **Concurrency & Threading:** Inventory database queries and network syncing operations **MUST** execute on asynchronous worker threads (`threading` or `concurrent.futures`) to prevent UI freezing (`tkinter` mainloop blocking).
4. **Error Resilience:** Every data mutation must pass through strict validation layers. Unhandled exceptions are a system failure. Log all anomalies to `var/log/inventer.log`.

---

## 0x02 // REPOSITORY TOPOLOGY

```text
inventer/
├── core/
│   ├── __init__.py
│   ├── database.py      # SQLite/PostgreSQL connection pooling & atomic queries
│   ├── inventory.py     # Stock calculation, SKU indexing, threshold triggers
│   └── logger.py        # System event logging & telemetry
├── ui/
│   ├── __init__.py
│   ├── main_window.py   # Primary Tkinter root & layout grid controller
│   ├── widgets.py       # Custom high-performance ttk widgets & data grids
│   └── dialogs.py       # Modal popups for alerts, audit logs, and config
├── configs/
│   ├── default.json     # System-wide operational parameters
│   └── theme.json       # Dark industrial UI color palettes & typography
├── tests/
│   ├── test_core.py     # Unit tests for inventory logic and transactions
│   └── test_ui.py       # Tkinter component stress tests
├── main.py              # Entry point execution vector
└── AGENTS.md            # [YOU ARE HERE] Operational protocol specification

```

---

## 0x03 // CODE STYLE & CONVENTIONS

- **Type Hinting:** Mandatory across all Python modules (`from typing import ...`). Strict PEP 8 compliance.
- **Docstrings:** Google-style docstrings for every class, public method, and state handler.
- **State Management:** Immutable data flow patterns where feasible. UI state must mirror database state strictly via reactive callback bindings (`trace_add` or custom observer patterns).
- **Git Commit Protocol:** Use conventional commits with descriptive tags (`feat:`, `fix:`, `refactor:`, `sec:`).

---

## 0x04 // EXECUTION & VERIFICATION

To initialize the system locally:

```bash
# Clone and enter directory
git clone https://github.com/grubberdubber/inventer.git
cd inventer

# Set up virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies (if any external packages required beyond standard lib)
pip install -r requirements.txt

# Execute main process
python3 main.py

```

---

```text
[STATUS]: SYSTEM READY. AWAITING INSTRUCTION VECTOR...

```
