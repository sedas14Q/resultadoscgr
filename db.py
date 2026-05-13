"""
db.py - Persistencia de actas con Postgres (produccion) y SQLite (local).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Intentar importar psycopg2 con mejor reporte de errores
psycopg2 = None
psycopg2_error = None
try:
    import psycopg2
    import psycopg2.extras
except ImportError as e:
    psycopg2_error = str(e)
except Exception as e:
    psycopg2_error = f"Error inesperado: {str(e)}"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "actas.db"
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")


@contextmanager
def _get_conn():
    if IS_POSTGRES:
        if psycopg2 is None:
            error_msg = f"DATABASE_URL configurada pero psycopg2 no esta disponible"
            if psycopg2_error:
                error_msg += f": {psycopg2_error}"
            raise RuntimeError(error_msg)
        dsn = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(dsn)
        try:
            yield conn
        finally:
            conn.close()
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _fetchall_dict(cur) -> list[dict]:
    if IS_POSTGRES:
        return [dict(r) for r in cur.fetchall()]
    return [dict(r) for r in cur.fetchall()]


def _fetchone_dict(cur) -> dict | None:
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


def _columnas_actas() -> set[str]:
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

    columnas = _columnas_actas()
    with _get_conn() as conn:
        faltantes = [
            "candidatos",
            "resumen",
            "fuente",
            "capturista",
            "fecha_subida",
        ]
        if IS_POSTGRES:
            with conn.cursor() as cur:
                for c in faltantes:
                    if c not in columnas:
                        tipo = "TIMESTAMP" if c == "fecha_subida" else "TEXT"
                        cur.execute(f"ALTER TABLE actas ADD COLUMN {c} {tipo}")
            conn.commit()
        else:
            for c in faltantes:
                if c not in columnas:
                    tipo = "TIMESTAMP" if c == "fecha_subida" else "TEXT"
                    conn.execute(f"ALTER TABLE actas ADD COLUMN {c} {tipo}")
            conn.commit()


def guardar_manual(numero: str, nombre: str, fecha: str | None, candidatos: list, resumen: dict, fuente: str = "formulario", capturista: str | None = None) -> int:
    inicializar()
    candidatos_json = json.dumps(candidatos or [], ensure_ascii=False)
    resumen_json = json.dumps(resumen or {}, ensure_ascii=False)

    with _get_conn() as conn:
        if IS_POSTGRES:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO actas (numero, nombre, fecha, candidatos, resumen, fuente, capturista)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (numero, nombre, fecha, candidatos_json, resumen_json, fuente, capturista),
                )
                new_id = int(cur.fetchone()[0])
            conn.commit()
            return new_id

        cur = conn.execute(
            """
            INSERT INTO actas (numero, nombre, fecha, candidatos, resumen, fuente, capturista)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (numero, nombre, fecha, candidatos_json, resumen_json, fuente, capturista),
        )
        conn.commit()
        return int(cur.lastrowid)


def _deserializar_fila(row: dict) -> dict:
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


def obtener_todas() -> list[dict]:
    try:
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM actas ORDER BY id DESC")
                    rows = _fetchall_dict(cur)
            else:
                cur = conn.execute("SELECT * FROM actas ORDER BY id DESC")
                rows = _fetchall_dict(cur)
    except Exception:
        inicializar()
        return []

    return [_deserializar_fila(r) for r in rows]


def obtener_por_numero(numero: str) -> list[dict]:
    try:
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM actas WHERE numero = %s ORDER BY id DESC", (numero,))
                    rows = _fetchall_dict(cur)
            else:
                cur = conn.execute("SELECT * FROM actas WHERE numero = ? ORDER BY id DESC", (numero,))
                rows = _fetchall_dict(cur)
    except Exception:
        inicializar()
        return []

    return [_deserializar_fila(r) for r in rows]


def obtener_por_id(acta_id: int) -> dict | None:
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


def obtener_estado() -> dict:
    try:
        with _get_conn() as conn:
            if IS_POSTGRES:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT COUNT(*) AS total_actas, COALESCE(MAX(id), 0) AS ultimo_id FROM actas")
                    row = _fetchone_dict(cur) or {"total_actas": 0, "ultimo_id": 0}
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


inicializar()
