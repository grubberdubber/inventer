.PHONY: help run test test-core test-ui lint format coverage clean

PYTHON ?= python3
VENV ?= .venv

help:
	@echo "INVENTER — comandos disponibles"
	@echo "  make run        Ejecuta la aplicación"
	@echo "  make test       Ejecuta toda la suite"
	@echo "  make test-core  Ejecuta solo los tests de dominio/persistencia"
	@echo "  make test-ui    Ejecuta el smoke test de Tkinter"
	@echo "  make lint       Verifica el código con Ruff"
	@echo "  make format     Formatea el código con Ruff"
	@echo "  make coverage   Ejecuta tests con cobertura"
	@echo "  make clean      Elimina cachés locales"

run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m pytest -q

test-core:
	$(PYTHON) -m pytest -q tests/test_core.py

test-ui:
	$(PYTHON) -m pytest -q tests/test_ui.py

lint:
	ruff check .

format:
	ruff format .

coverage:
	$(PYTHON) -m pytest --cov=core --cov=ui --cov-report=term-missing

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
