# Contribuir a INVENTER

Gracias por tu interés en mejorar **INVENTER**. Este documento describe el flujo de trabajo, los estándares de código y los criterios de aceptación para cambios.

## Código de conducta

Al participar aceptas cumplir el [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Sé respetuoso, constructivo y asume buena fe.

## Configurar el entorno

```bash
git clone https://github.com/grubberdubber/inventer.git
cd inventer

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

python main.py
```

En Debian/Ubuntu, si Tkinter no está disponible:

```bash
sudo apt install python3-tk
```

## Flujo de trabajo

1. Crea una rama desde `main` con un nombre descriptivo:
   - `feat/multi-branch-audit`
   - `fix/atomic-replenishment-rollback`
   - `docs/architecture-adr`
2. Implementa el cambio con tests.
3. Ejecuta las verificaciones locales:
   ```bash
   ruff check .
   python -m pytest -q
   ```
4. Actualiza la documentación o capturas si el cambio es visible.
5. Abre un *pull request* / *merge request* usando la plantilla.

## Estándares de código

- **Python 3.11+** con type hints en todas las funciones y métodos públicos.
- **PEP 8** y formato consistente con el resto del proyecto (4 espacios, líneas ≤ 100).
- **Docstrings Google-style** para clases, métodos públicos y manejadores de estado.
- **Tkinter/ttk exclusivamente** para la UI. No se aceptan PyQt, PySide, Kivy ni frameworks equivalentes.
- **Sin dependencias de runtime** salvo la biblioteca estándar. Las dependencias de desarrollo deben justificarse.
- **Mutaciones atómicas:** toda escritura debe pasar por una transacción y registrar su movimiento de auditoría.
- **Hilos:** las consultas y mutaciones no deben ejecutarse en el hilo de Tk. Usa el executor existente.
- **Errores:** no silencies excepciones; regístralas con el logger `inventer.*` y devuelve un mensaje accionable a la UI.

## Commits

Se usa [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add multi-branch stock aggregation
fix: rollback bulk replenishment on missing product
refactor: extract dashboard telemetry builder
docs: document SQLite WAL concurrency model
test: cover duplicate SKU validation
sec: reject negative replenishment quantities
```

## Tests

- Toda lógica nueva de dominio o persistencia requiere tests.
- Los cambios de UI deben incluir un smoke test o una captura actualizada.
- La suite debe pasar en Python 3.11, 3.12 y 3.13.
- Para cobertura local:
  ```bash
  python -m pytest --cov=core --cov=ui --cov-report=term-missing
  ```

## Pull requests

Incluye en la descripción:

- Qué problema resuelve y por qué.
- Cómo se probó (comandos, escenarios, capturas).
- Impacto en datos, migraciones o configuración.
- Checklist de la plantilla completado.

Los PRs deben mantener el CI en verde y no introducir archivos generados (`var/`, `__pycache__/`, `.venv/`).

## Reportes de seguridad

No abras issues públicos para vulnerabilidades. Sigue el proceso de [`SECURITY.md`](SECURITY.md).
