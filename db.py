"""
db.py - Persistencia SQLite para actas capturadas manualmente.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "actas.db"


@contextmanager
def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _columnas_actas() -> set[str]:
    with _get_conn() as conn:
        rows = conn.execute("PRAGMA table_info(actas)").fetchall()
    return {r["name"] for r in rows}


def inicializar() -> None:
    with _get_conn() as conn:
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
        if "candidatos" not in columnas:
            conn.execute("ALTER TABLE actas ADD COLUMN candidatos TEXT")
        if "resumen" not in columnas:
            conn.execute("ALTER TABLE actas ADD COLUMN resumen TEXT")
        if "fuente" not in columnas:
            conn.execute("ALTER TABLE actas ADD COLUMN fuente TEXT")
        if "capturista" not in columnas:
            conn.execute("ALTER TABLE actas ADD COLUMN capturista TEXT")
        if "fecha_subida" not in columnas:
            conn.execute("ALTER TABLE actas ADD COLUMN fecha_subida TIMESTAMP")
        conn.commit()


def guardar_manual(numero: str, nombre: str, fecha: str | None, candidatos: list, resumen: dict, fuente: str = "formulario", capturista: str | None = None) -> int:
    inicializar()
    candidatos_json = json.dumps(candidatos or [], ensure_ascii=False)
    resumen_json = json.dumps(resumen or {}, ensure_ascii=False)

    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO actas (numero, nombre, fecha, candidatos, resumen, fuente, capturista)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (numero, nombre, fecha, candidatos_json, resumen_json, fuente, capturista),
        )
        conn.commit()
        return int(cur.lastrowid)


def _deserializar_fila(row):
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
            rows = conn.execute("SELECT * FROM actas ORDER BY id DESC").fetchall()
    except sqlite3.OperationalError:
        inicializar()
        return []

    return [_deserializar_fila(r) for r in rows]


def obtener_por_numero(numero: str) -> list[dict]:
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT * FROM actas WHERE numero = ? ORDER BY id DESC", (numero,)).fetchall()
    except sqlite3.OperationalError:
        inicializar()
        return []

    return [_deserializar_fila(r) for r in rows]


def obtener_por_id(acta_id: int) -> dict | None:
    try:
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM actas WHERE id = ?", (int(acta_id),)).fetchone()
    except (sqlite3.OperationalError, ValueError, TypeError):
        inicializar()
        return None

    if not row:
        return None
    return _deserializar_fila(row)


def obtener_estado() -> dict:
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total_actas, COALESCE(MAX(id), 0) AS ultimo_id FROM actas"
            ).fetchone()
    except sqlite3.OperationalError:
        inicializar()
        return {"total_actas": 0, "ultimo_id": 0}

    return {
        "total_actas": int(row["total_actas"] or 0),
        "ultimo_id": int(row["ultimo_id"] or 0),
    }


def actualizar_acta(acta_id: int, numero: str, nombre: str, fecha: str | None, candidatos: list, resumen: dict) -> bool:
    inicializar()
    candidatos_json = json.dumps(candidatos or [], ensure_ascii=False)
    resumen_json = json.dumps(resumen or {}, ensure_ascii=False)

    with _get_conn() as conn:
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
        cur = conn.execute("DELETE FROM actas WHERE id = ?", (int(acta_id),))
        conn.commit()
        return cur.rowcount > 0


inicializar()
