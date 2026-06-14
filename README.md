# Backend Flask - Sistema de Actas

Backend para captura y gestión de actas electorales con persistencia en PostgreSQL.

## 🔧 Configuración en Render

### 1. Crear Base de Datos PostgreSQL

En tu dashboard de Render:

1. Click en **"New +"** → **"PostgreSQL"**
2. Configura la base de datos:
   - **Name**: `actas-db` (o el nombre que prefieras)
   - **Database**: `actas`
   - **User**: se genera automáticamente
   - **Region**: elige la más cercana
   - **Instance Type**: Free (para desarrollo)

3. Una vez creada, copia la **Internal Database URL** (aparece en la pestaña "Connect")
   - Debe verse así: `postgresql://usuario:password@hostname:5432/dbname`

### 2. Crear Web Service

1. Click en **"New +"** → **"Web Service"**
2. Conecta tu repositorio de GitHub
3. Configura el servicio:
   - **Name**: `actas-backend`
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: Free

### 3. Configurar Variables de Entorno

En la sección **Environment** de tu Web Service, añade:

```bash
# REQUERIDA - Conexión a PostgreSQL
DATABASE_URL=postgresql://resultados_db_xncl_user:ifbrIRGvdGNGWONoIIvlhdfefhfJTqaz@dpg-d8mu3uvlk1mc7394rfbg-a/resultados_db_xncl

# Credenciales de administrador
ADMIN_USER=admin
ADMIN_PASSWORD_HASH=scrypt:32768:8:1:ABC123... # Ver abajo cómo generarlo

# CORS (ajusta al dominio de tu frontend)
CORS_ORIGIN=https://tu-frontend.com

# Modo producción
FLASK_DEBUG=0
```

### 4. Generar Hash de Contraseña

Para generar el hash de la contraseña `1548`:

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('1548'))"
```

Copia el resultado completo (empieza con `scrypt:32768:8:1:...`) y pégalo en `ADMIN_PASSWORD_HASH`.

### 5. Deploy

Render iniciará el deployment automáticamente. Verifica:

1. Que el build termine exitosamente
2. Que el servicio esté ejecutándose (status verde)

## ✅ Verificación

Una vez desplegado, prueba estos endpoints:

### Health Check de Base de Datos
```bash
curl https://tu-servicio.onrender.com/api/health/db
```

Debe responder:
```json
{
  "status": "ok",
  "data": {
    "ok": true,
    "engine": "postgres"
  }
}
```

### Estado de Actas
```bash
curl https://tu-servicio.onrender.com/api/actas/estado
```

Debe responder:
```json
{
  "status": "ok",
  "data": {
    "total_actas": 0,
    "ultimo_id": 0,
    "engine": "postgres"
  }
}
```

**IMPORTANTE**: Si `"engine"` dice `"sqlite"` en lugar de `"postgres"`, significa que `DATABASE_URL` no está configurada correctamente.

## 📁 Estructura de Archivos

```
.
├── app.py              # Aplicación Flask principal
├── db.py               # Capa de persistencia (PostgreSQL/SQLite)
├── dependencias.py     # Normalización de dependencias
├── requirements.txt    # Dependencias Python
├── runtime.txt         # Versión de Python
├── Procfile           # Comando de inicio para Render
└── README.md          # Este archivo
```

## 🔒 Seguridad

- ✅ Usa PostgreSQL con `DATABASE_URL` (no SQLite en producción)
- ✅ Guarda `ADMIN_PASSWORD_HASH` como variable de entorno
- ✅ Configura `CORS_ORIGIN` específico (no uses `*` en producción)
- ✅ Mantén `FLASK_DEBUG=0` en producción
- ✅ Rota la contraseña de admin periódicamente

## 🐛 Solución de Problemas

### Error: "DATABASE_URL configurada pero psycopg2 no esta disponible"

**Causa**: La dependencia `psycopg2-binary` no se instaló correctamente.

**Solución**: Verifica que `requirements.txt` contenga:
```
psycopg2-binary==2.9.9
```

### Las actas se borran al reiniciar

**Causa**: Estás usando SQLite en lugar de PostgreSQL.

**Solución**: 
1. Crea una base de datos PostgreSQL en Render
2. Configura `DATABASE_URL` en las variables de entorno
3. Verifica con `/api/actas/estado` que `"engine": "postgres"`

### El servicio entra en "sleep"

**Causa**: Plan Free de Render desactiva servicios inactivos después de 15 minutos.

**Solución**:
- Upgrade a un plan de pago, O
- Configura un monitor externo (UptimeRobot, BetterStack) para hacer ping cada 5-10 minutos a `/api/health/db`

## 📡 Endpoints API

### GET `/api/actas`
Lista todas las actas guardadas.

### POST `/api/actas`
Crea una nueva acta (requiere JSON con número, nombre, candidatos, resumen).

### GET `/api/actas/estado`
Obtiene estadísticas: total de actas, último ID, motor de BD.

### GET `/api/health/db`
Health check de la base de datos.

### GET `/api/actas/<id>/pdf`
Descarga el PDF de un acta específica.

### PUT `/api/actas/<id>`
Actualiza un acta (requiere autenticación admin).

### DELETE `/api/actas/<id>`
Elimina un acta (requiere autenticación admin).

## 🚀 Mantenimiento

### Backup de Base de Datos

En Render Dashboard:
1. Ve a tu base de datos PostgreSQL
2. Pestaña "Backups"
3. Click en "Create Backup"

### Ver Logs

En Render Dashboard:
1. Ve a tu Web Service
2. Pestaña "Logs"
3. Filtra por errores o busca mensajes específicos

## 📞 Soporte

Si tienes problemas:
1. Revisa los logs en Render
2. Verifica que `DATABASE_URL` esté configurada
3. Confirma que el health check responda correctamente
4. Verifica que `"engine": "postgres"` en `/api/actas/estado`
