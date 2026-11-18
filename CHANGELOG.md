# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Added

- Vista **Sistema** con diagnóstico del núcleo, accesos directos y mantenimiento de datos.
- Importación atómica de catálogo desde CSV, con validación previa de todas las filas y emparejamiento por SKU.
- Respaldo consistente de la base SQLite mediante la API nativa `backup`.
- Filtros de fecha en Movimientos: hoy, últimos 7 días, últimos 30 días o historial completo.
- KPI de valor de inventario con costo y margen potencial.
- Activación de filas con `Enter` en las tablas y atajos `Ctrl+I` / `Ctrl+B`.
- Exportación de inventario con columna de código de barras para permitir el ciclo exportar → importar.

### Changed

- El historial de auditoría carga hasta 500 movimientos recientes por sincronización.
- El CSV de importación acepta encabezados en español o inglés y variantes con o sin acentos.

### Fixed

- La exportación de catálogo ya no omite el código de barras.
- Los textos del diálogo de confirmación y de las tarjetas KPI se ajustan sin recortarse a 1240 px.

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
