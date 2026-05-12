# backend-flask

Carpeta lista para desplegar en Render, Railway o Fly.io.

## Variables de entorno recomendadas
- `ADMIN_USER=admin`
- `ADMIN_PASSWORD=1548`
- `CORS_ORIGIN=*`
- `FLASK_DEBUG=0`

## Start command
`gunicorn app:app`

## Notas
- Incluye `templates/`, `static/` y `baseDatos/`.
- `actas.db` se crea automaticamente al iniciar.
- En hosting con filesystem efimero, SQLite puede perder datos al reiniciar. Para persistencia fuerte, usar Postgres.
