"""INVENTER entry point execution vector.

Usage:
    python3 main.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.database import Database
from core.logger import configure_logging
from ui.main_window import MainWindow

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_json(path: Path) -> dict[str, Any]:
    """Read a JSON configuration file."""
    with path.open("r", encoding="utf-8") as handle:
        content = json.load(handle)
    if not isinstance(content, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return content


def main() -> int:
    """Boot the system and run the Tk event loop."""
    config_path = PROJECT_ROOT / "configs" / "default.json"
    theme_path = PROJECT_ROOT / "configs" / "theme.json"

    try:
        config = _load_json(config_path)
        theme_spec = _load_json(theme_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[INVENTER] Configuration failure: {exc}", flush=True)
        return 1

    log_path = PROJECT_ROOT / str(config.get("logging", {}).get("path", "var/log/inventer.log"))
    level_name = str(config.get("logging", {}).get("level", "INFO")).upper()
    logger = configure_logging(log_path, getattr(logging, level_name, logging.INFO))
    logger.info("INVENTER boot sequence initiated")

    database = Database(
        PROJECT_ROOT / str(config.get("database", {}).get("path", "var/inventer.db"))
    )

    try:
        database.initialize()
        window = MainWindow(database, config, theme_spec)
        window.run()
    except Exception:
        logger.exception("Fatal startup failure")
        try:
            import tkinter as tk
            from tkinter import messagebox

            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror(
                "INVENTER — Error fatal",
                "El núcleo no pudo iniciarse. Revisa var/log/inventer.log.",
            )
            fallback.destroy()
        except Exception:
            pass
        return 1
    finally:
        database.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
