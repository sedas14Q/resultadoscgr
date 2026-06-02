"""
db.py - Persistencia de actas con Postgres (producción en Render) y SQLite (desarrollo local).
Este archivo encapsula toda la interacción con la base de datos, soportando dos motores distintos
según la presencia de la variable de entorno DATABASE_URL.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Intentar importar psycopg2 con mejor reporte de errores para entornos Postgres
psycopg2 = None
psycopg2_error = None
try:
    import psycopg2
    import psycopg2.extras
except ImportError as e:
    psycopg2_error = str(e)
except Exception as e:
    psycopg2_error = f"Error inesperado: {str(e)}"

# Definición de rutas base y detección del tipo de base de datos
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "actas.db"
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
# Si la URL de conexión inicia con postgres:// o postgresql://, se asume que se usa PostgreSQL
IS_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")


@contextmanager
def _get_conn():
    """
    Context Manager que abre y cierra de forma segura la conexión a la base de datos.
    Si se detecta PostgreSQL, usa psycopg2; de lo contrario usa sqlite3 local.
    """
    if IS_POSTGRES:
        if psycopg2 is None:
            error_msg = f"DATABASE_URL configurada pero psycopg2 no esta disponible"
            if psycopg2_error:
                error_msg += f": {psycopg2_error}"
            raise RuntimeError(error_msg)
        # Normalización del DSN para psycopg2 (reemplaza postgres:// por postgresql://)
        dsn = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(dsn)
        try:
            yield conn
        finally:
            conn.close()
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Configura SQLite para devolver filas accesibles por nombre de columna
    try:
        yield conn
    finally:
        conn.close()


def _fetchall_dict(cur) -> list[dict]:
    """
    Convierte el conjunto de resultados recuperados por un cursor en una lista de diccionarios.
    """
    if IS_POSTGRES:
        return [dict(r) for r in cur.fetchall()]
    return [dict(r) for r in cur.fetchall()]


def _fetchone_dict(cur) -> dict | None:
    """
    Convierte una sola fila de resultados recuperada por un cursor en un diccionario.
    Retorna None si no hay fila.
    """
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


def _columnas_actas() -> set[str]:
    """
    Inspecciona la tabla 'actas' y retorna un conjunto de nombres de las columnas existentes.
    Esto permite ejecutar migraciones dinámicas de la estructura de datos.
    """
    with _get_conn() as conn:
        if IS_POSTGRES:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'actas'
                    """
                )
                return {r["column_name"] for r in cur.fetchall()}

        rows = conn.execute("PRAGMA table_info(actas)").fetchall()
        return {r["name"] for r in rows}


def inicializar() -> None:
    """
    Crea la tabla 'actas' en caso de que no exista y agrega columnas faltantes.
    Maneja las diferencias sintácticas entre SQLite (AUTOINCREMENT) y PostgreSQL (BIGSERIAL).
    """
    with _get_conn() as conn:
        if IS_POSTGRES:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS actas (
                        id BIGSERIAL PRIMARY KEY,
                        numero TEXT NOT NULL,
                        nombre TEXT NOT NULL,
                        fecha TEXT,
                        candidatos TEXT,
                        resumen TEXT,
                        fuente TEXT,
                        capturista TEXT,
                        fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            conn.commit()
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    numero TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    fecha TEXT,
                    candidatos TEXT,
                    resumen TEXT,
                    fuente TEXT,
                    capturista TEXT,
                    fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    # Ejecución de migraciones dinámicas para columnas adicionales
    columnas = _columnas_actas()
    with _get_conn() as conn:
        faltantes = [
            "candidatos",
            "resumen",
            "fuente",
            "capturista",
            "fecha_subida",
            "sistema",
        ]
        if IS_POSTGRES:
            with conn.cursor() as cur:
                for c in faltantes:
                    if c not in columnas:
                        tipo = "TIMESTAMP" if c == "fecha_subida" else "TEXT"
                        cur.execute(f"ALTER TABLE actas ADD COLUMN {c} {tipo}")
                cur.execute("UPDATE actas SET sistema = 'CGR' WHERE sistema IS NULL")
            conn.commit()
        else:
            for c in faltantes:
                if c not in columnas:
                    tipo = "TIMESTAMP" if c == "fecha_subida" else "TEXT"
                    conn.execute(f"ALTER TABLE actas ADD COLUMN {c} {tipo}")
            conn.execute("UPDATE actas SET sistema = 'CGR' WHERE sistema IS NULL")
            conn.commit()


def guardar_manual(numero: str, nombre: str, fecha: str | None, candidatos: list, resumen: dict, fuente: str = "formulario", capturista: str | None = None, sistema: str = "CGR") -> int:
    """
    Inserta un nuevo registro de acta en la base de datos.
    Serializa las estructuras complejas (candidatos y resumen) como strings JSON
    para guardarlas en tipos de campo TEXT genéricos compatibles con SQLite/PostgreSQL.
    Retorna el ID del registro creado.
    """
    inicializar()
    candidatos_json = json.dumps(candidatos or [], ensure_ascii=False)
    resumen_json = json.dumps(resumen or {}, ensure_ascii=False)

    with _get_conn() as conn:
        if IS_POSTGRES:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO actas (numero, nombre, fecha, candidatos, resumen, fuente, capturista, sistema)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (numero, nombre, fecha, candidatos_json, resumen_json, fuente, capturista, sistema),
                )
                new_id = int(cur.fetchone()[0])
            conn.commit()
            return new_id

        cur = conn.execute(
            """
            INSERT INTO actas (numero, nombre, fecha, candidatos, resumen, fuente, capturista, sistema)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (numero, nombre, fecha, candidatos_json, resumen_json, fuente, capturista, sistema),
        )
        conn.commit()
        return int(cur.lastrowid)


def _deserializar_fila(row: dict) -> dict:
    """
    Deserializa los campos JSON ('candidatos' y 'resumen') de una fila de la base de datos
    para convertirlos nuevamente a estructuras nativas de Python (listas/diccionarios).
    """
    d = dict(row)
    try:
        d["candidatos"] = json.loads(d.get("candidatos") or "[]")
    except (TypeError, json.JSONDecodeError):
        d["candidatos"] = []

    try:
        d["resumen"] = json.loads(d.get("resumen") or "{}")
    except (TypeError, json.JSONDecodeError):
        d["resumen"] = {}

    return d


def obtener_todas(sistema: str | None = None) -> list[dict]:
    """
    Recupera todos los registros de actas ordenados de forma descendente por ID.
    Retorna una lista de diccionarios deserializados.
    """
    try:
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if sistema:
                        cur.execute("SELECT * FROM actas WHERE sistema = %s ORDER BY id DESC", (sistema,))
                    else:
                        cur.execute("SELECT * FROM actas ORDER BY id DESC")
                    rows = _fetchall_dict(cur)
            else:
                if sistema:
                    cur = conn.execute("SELECT * FROM actas WHERE sistema = ? ORDER BY id DESC", (sistema,))
                else:
                    cur = conn.execute("SELECT * FROM actas ORDER BY id DESC")
                rows = _fetchall_dict(cur)
    except Exception:
        inicializar()
        return []

    return [_deserializar_fila(r) for r in rows]


def obtener_por_numero(numero: str, sistema: str | None = None) -> list[dict]:
    """
    Filtra y devuelve las actas cuyo número de dependencia coincida de manera exacta.
    """
    try:
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if sistema:
                        cur.execute("SELECT * FROM actas WHERE numero = %s AND sistema = %s ORDER BY id DESC", (numero, sistema))
                    else:
                        cur.execute("SELECT * FROM actas WHERE numero = %s ORDER BY id DESC", (numero,))
                    rows = _fetchall_dict(cur)
            else:
                if sistema:
                    cur = conn.execute("SELECT * FROM actas WHERE numero = ? AND sistema = ? ORDER BY id DESC", (numero, sistema))
                else:
                    cur = conn.execute("SELECT * FROM actas WHERE numero = ? ORDER BY id DESC", (numero,))
                rows = _fetchall_dict(cur)
    except Exception:
        inicializar()
        return []

    return [_deserializar_fila(r) for r in rows]


def obtener_por_id(acta_id: int) -> dict | None:
    """
    Recupera un acta específica por su identificador numérico único.
    Retorna la estructura deserializada o None si no existe.
    """
    try:
        _id = int(acta_id)
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM actas WHERE id = %s", (_id,))
                    row = _fetchone_dict(cur)
            else:
                cur = conn.execute("SELECT * FROM actas WHERE id = ?", (_id,))
                row = _fetchone_dict(cur)
    except Exception:
        inicializar()
        return None

    if not row:
        return None
    return _deserializar_fila(row)


def obtener_estado(sistema: str | None = None) -> dict:
    """
    Obtiene métricas rápidas de la base de datos (conteo de actas, último ID registrado
    y tipo de motor de base de datos activo) para el control de sincronización.
    """
    try:
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if sistema:
                        cur.execute("SELECT COUNT(*) AS total_actas, COALESCE(MAX(id), 0) AS ultimo_id FROM actas WHERE sistema = %s", (sistema,))
                    else:
                        cur.execute("SELECT COUNT(*) AS total_actas, COALESCE(MAX(id), 0) AS ultimo_id FROM actas")
                    row = _fetchone_dict(cur) or {"total_actas": 0, "ultimo_id": 0}
            else:
                if sistema:
                    cur = conn.execute("SELECT COUNT(*) AS total_actas, COALESCE(MAX(id), 0) AS ultimo_id FROM actas WHERE sistema = ?", (sistema,))
                else:
                    cur = conn.execute("SELECT COUNT(*) AS total_actas, COALESCE(MAX(id), 0) AS ultimo_id FROM actas")
                row = _fetchone_dict(cur) or {"total_actas": 0, "ultimo_id": 0}
    except Exception:
        inicializar()
        return {"total_actas": 0, "ultimo_id": 0}

    return {
        "total_actas": int(row.get("total_actas") or 0),
        "ultimo_id": int(row.get("ultimo_id") or 0),
        "engine": "postgres" if IS_POSTGRES else "sqlite",
    }


def healthcheck() -> dict:
    """
    Realiza una consulta rápida de prueba ('SELECT 1') para verificar si la base de datos
    está en línea y respondiendo consultas correctamente.
    """
    try:
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            else:
                conn.execute("SELECT 1").fetchone()
        return {"ok": True, "engine": "postgres" if IS_POSTGRES else "sqlite"}
    except Exception as exc:
        return {"ok": False, "engine": "postgres" if IS_POSTGRES else "sqlite", "error": str(exc)}


def actualizar_acta(acta_id: int, numero: str, nombre: str, fecha: str | None, candidatos: list, resumen: dict) -> bool:
    """
    Actualiza la información de un acta existente. Re-serializa campos complejos a strings JSON.
    Retorna True si el acta fue modificada con éxito.
    """
    inicializar()
    candidatos_json = json.dumps(candidatos or [], ensure_ascii=False)
    resumen_json = json.dumps(resumen or {}, ensure_ascii=False)

    with _get_conn() as conn:
        if IS_POSTGRES:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE actas
                    SET numero = %s, nombre = %s, fecha = %s, candidatos = %s, resumen = %s
                    WHERE id = %s
                    """,
                    (numero, nombre, fecha, candidatos_json, resumen_json, int(acta_id)),
                )
                updated = cur.rowcount > 0
            conn.commit()
            return updated

        cur = conn.execute(
            """
            UPDATE actas
            SET numero = ?, nombre = ?, fecha = ?, candidatos = ?, resumen = ?
            WHERE id = ?
            """,
            (numero, nombre, fecha, candidatos_json, resumen_json, int(acta_id)),
        )
        conn.commit()
        return cur.rowcount > 0


def eliminar_acta(acta_id: int) -> bool:
    """
    Elimina un registro de acta permanentemente de la base de datos usando su ID.
    Retorna True si la eliminación tuvo éxito.
    """
    inicializar()
    with _get_conn() as conn:
        if IS_POSTGRES:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM actas WHERE id = %s", (int(acta_id),))
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted

        cur = conn.execute("DELETE FROM actas WHERE id = ?", (int(acta_id),))
        conn.commit()
        return cur.rowcount > 0


# Inicialización de la base de datos al importar el módulo
inicializar()
