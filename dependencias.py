"""
dependencias.py - Normaliza numero y nombre de dependencia con catalogo Excel.
Uso actual: formulario manual.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = BASE_DIR / "baseDatos" / "BaseDatoDepAct.xlsx"
NS_MAIN = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"


def _norm_texto(s: str | None) -> str:
    if not s:
        return ""
    txt = unicodedata.normalize("NFKD", str(s))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = re.sub(r"\s+", " ", txt).strip().upper()
    return txt


def _limpiar_numero(v: str | None) -> str | None:
    if not v:
        return None
    m = re.findall(r"\d+", str(v))
    return str(int(m[0])) if m else None


def _leer_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall("a:si", NS_MAIN):
        out.append("".join((t.text or "") for t in si.findall(".//a:t", NS_MAIN)))
    return out


def _valor_celda(celda: ET.Element, shared: list[str]) -> str:
    tipo = celda.attrib.get("t")
    v = celda.find("a:v", NS_MAIN)
    if v is None or v.text is None:
        return ""
    if tipo == "s":
        idx = int(v.text)
        return shared[idx] if 0 <= idx < len(shared) else ""
    return v.text


@lru_cache(maxsize=1)
def catalogo_dependencias() -> dict[str, str]:
    out: dict[str, str] = {}
    if not EXCEL_PATH.exists():
        return out

    try:
        with zipfile.ZipFile(EXCEL_PATH) as zf:
            shared = _leer_shared_strings(zf)
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall(NS_REL)}
            sheets = wb.findall("a:sheets/a:sheet", NS_MAIN)
            if not sheets:
                return out
            rid = sheets[0].attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rid, "worksheets/sheet1.xml")
            if not target.startswith("xl/"):
                target = f"xl/{target}"

            ws = ET.fromstring(zf.read(target))
            rows = ws.findall("a:sheetData/a:row", NS_MAIN)
            if not rows:
                return out

            # Leer primera fila como encabezado
            header_map: dict[str, str] = {}
            first_cells = rows[0].findall("a:c", NS_MAIN)
            for c in first_cells:
                ref = c.attrib.get("r", "")
                col = "".join(ch for ch in ref if ch.isalpha())
                val = _norm_texto(_valor_celda(c, shared))
                if col and val:
                    header_map[col] = val

            col_clave = next((col for col, h in header_map.items() if h == "CLAVE"), "A")
            col_dependencia = next((col for col, h in header_map.items() if h == "DEPENDENCIA"), "B")

            for row in rows[1:]:
                celdas = {}
                for c in row.findall("a:c", NS_MAIN):
                    ref = c.attrib.get("r", "")
                    col = "".join(ch for ch in ref if ch.isalpha())
                    celdas[col] = _valor_celda(c, shared)

                numero = _limpiar_numero(celdas.get(col_clave))
                nombre = (celdas.get(col_dependencia) or "").strip()
                if numero and nombre:
                    out[numero] = nombre
    except (KeyError, ValueError, zipfile.BadZipFile, ET.ParseError, FileNotFoundError):
        return {}

    return out


def normalizar_dependencia(numero: str | None, nombre: str | None) -> tuple[str | None, str | None]:
    numero_limpio = _limpiar_numero(numero)
    nombre_limpio = (nombre or "").strip() or None

    cat = catalogo_dependencias()
    if numero_limpio and numero_limpio in cat:
        return numero_limpio, cat[numero_limpio]

    if nombre_limpio and cat:
        nombre_norm = _norm_texto(nombre_limpio)

        for num, nom in cat.items():
            if _norm_texto(nom) == nombre_norm:
                return num, nom

        mejor_numero = None
        mejor_nombre = None
        mejor_score = 0.0
        for num, nom in cat.items():
            score = difflib.SequenceMatcher(None, nombre_norm, _norm_texto(nom)).ratio()
            if score > mejor_score:
                mejor_score = score
                mejor_numero = num
                mejor_nombre = nom

        if mejor_numero and mejor_score >= 0.72:
            return mejor_numero, mejor_nombre

    return numero_limpio, nombre_limpio
