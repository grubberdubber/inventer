# Política de seguridad

## Versiones soportadas

| Versión | Soporte |
| --- | --- |
| `1.x` | ✅ Activo |

## Reportar una vulnerabilidad

**No abras un issue público.** Usa uno de estos canales privados:

- **GitHub:** pestaña **Security → Report a vulnerability** del repositorio.
- **GitLab:** crea un issue **confidencial** en el proyecto y etiqueta a los mantenedores.

Incluye, si es posible:

- Versión de INVENTER y sistema operativo.
- Pasos de reproducción.
- Impacto esperado (confidencialidad, integridad, disponibilidad).
- Evidencia o prueba de concepto.
- Mitigación sugerida.

## Proceso de respuesta

1. Confirmación de recepción en un plazo orientativo de **72 horas**.
2. Evaluación y clasificación del impacto.
3. Corrección en una rama privada y coordinación de la divulgación.
4. Publicación de un parche y reconocimiento al reportero (si lo desea).

## Alcance

Se consideran vulnerabilidades relevantes:

- Inyección SQL o manipulación de consultas.
- Escrituras no atómicas que corrompan stock o auditoría.
- Bypass de la validación de dominio.
- Ejecución de código o escalado de privilegios.
- Exposición de datos sensibles en logs o exportaciones.

## Buenas prácticas para despliegues

- Ejecuta la aplicación con un usuario sin privilegios.
- Restringe permisos de `var/inventer.db` y `var/log/`.
- Mantén Python y Tkinter actualizados.
- Realiza copias de seguridad periódicas de la base SQLite.
- No expongas la base de datos directamente a la red.
