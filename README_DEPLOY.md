# backend-flask

Carpeta lista para desplegar en Render, Railway o Fly.io.

## Variables de entorno recomendadas
- `ADMIN_USER=admin`
- `ADMIN_PASSWORD_HASH=<hash generado para 1548>`
- `CORS_ORIGIN=https://tu-frontend.com`
- `FLASK_DEBUG=0`
- `DATABASE_URL=postgresql://resultados_db_xncl_user:ifbrIRGvdGNGWONoIIvlhdfefhfJTqaz@dpg-d8mu3uvlk1mc7394rfbg-a/resultados_db_xncl`

## Como generar hash para la contrasena 1548
Ejecuta una vez en local:

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('1548'))"
```

Copia la salida y colocala en `ADMIN_PASSWORD_HASH`.

## Start command
`gunicorn app:app`

## Persistencia de actas
- Produccion: usa `DATABASE_URL` (PostgreSQL). Los datos quedan persistentes aunque el servidor reinicie.
- Local: sin `DATABASE_URL`, usa SQLite (`actas.db`) solo para desarrollo.

## Endpoints de estado
- `GET /api/actas/estado`: total de actas, ultimo id y motor (`postgres` o `sqlite`).
- `GET /api/health/db`: valida conectividad real a base y responde `200` (ok) o `503` (error).

## Mantener el servicio activo
- Si tu proveedor permite `always on`, habilitalo.
- Si entra en sleep, configura un monitor externo (UptimeRobot/BetterStack) cada 5 minutos a:
  - `/api/health/db`
  - o `/api/actas/estado`

## Seguridad minima recomendada
- No usar `CORS_ORIGIN=*` en produccion.
- Guardar secretos solo en variables de entorno.
- Rotar periodicamente la contrasena de admin.
