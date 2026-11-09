# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

## [1.0.0] — 2026-11-09

### Added

- Shell Tkinter/ttk con tema industrial oscuro, sidebar, topbar, statusbar y notificaciones.
- Panel de control con KPIs, alertas priorizadas, salud por categoría y actividad reciente.
- Catálogo maestro con búsqueda, filtros por categoría/alerta, edición y exportación CSV.
- Cola de reposición por severidad con cantidad sugerida y reposición masiva atómica.
- Bitácora de movimientos con filtros y exportación para auditoría.
- Simulador de escáner EAN-13 con salida rápida y reposición.
- Persistencia SQLite en modo WAL con conexiones thread-local y transacciones `BEGIN IMMEDIATE`.
- Pool de workers asíncronos para mantener la UI fluida.
- Validación estricta de SKU, código de barras, cantidades, importes y umbrales.
- Logging rotativo en `var/log/inventer.log`.
- Suite de tests de dominio, persistencia y smoke test de UI.
- CI para GitHub Actions y GitLab CI con Ruff, pytest y Xvfb.
- Documentación de arquitectura, contribución, seguridad y código de conducta.

### Security

- Restricciones `CHECK` y `UNIQUE` en la base para reforzar la validación de dominio.
- Rollback automático ante errores de integridad o stock insuficiente.
