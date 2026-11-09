## Resumen

<!-- Qué cambia y por qué. -->

## Tipo de cambio

- [ ] `feat`: nueva funcionalidad
- [ ] `fix`: corrección de bug
- [ ] `refactor`: cambio interno sin alterar comportamiento
- [ ] `docs`: documentación
- [ ] `test`: tests
- [ ] `sec`: seguridad
- [ ] `ci`: tooling / pipelines

## Cómo se probó

<!-- Comandos, escenarios manuales, capturas. -->

```bash
ruff check .
python -m pytest -q
```

## Impacto

- [ ] Requiere migración de base de datos
- [ ] Cambia configuración (`configs/*.json`)
- [ ] Cambia la UI (adjunto captura)
- [ ] Afecta concurrencia o transacciones
- [ ] Sin impacto operativo

## Checklist

- [ ] El código sigue los estándares de `CONTRIBUTING.md`.
- [ ] Añadí o actualicé tests para la lógica modificada.
- [ ] `ruff check .` y `pytest -q` pasan localmente.
- [ ] Actualicé documentación o CHANGELOG si corresponde.
- [ ] No incluí archivos generados (`var/`, `__pycache__/`, `.venv/`).
