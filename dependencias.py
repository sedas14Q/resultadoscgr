"""
dependencias.py - Módulo para normalizar números y nombres de dependencias electorales.
Carga directamente y bajo demanda el catálogo contenido en un archivo de Excel (.xlsx)
para validar e identificar dependencias mediante búsquedas exactas o algoritmos difusos.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

# Definición de rutas y namespaces de OpenXML para analizar el archivo XLSX
BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = BASE_DIR / "baseDatos" / "BaseDatoDepAct.xlsx"
NS_MAIN = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"


def _norm_texto(s: str | None) -> str:
    """
    Normaliza y limpia el texto para facilitar comparaciones uniformes.
    Remueve diacríticos (acentos), reemplaza secuencias de espacios por uno solo,
    elimina espacios externos y convierte el texto a mayúsculas.
    """
    if not s:
        return ""
    txt = unicodedata.normalize("NFKD", str(s))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = re.sub(r"\s+", " ", txt).strip().upper()
    return txt


def _limpiar_numero(v: str | None) -> str | None:
    """
    Extrae únicamente los dígitos numéricos de una cadena, retornando el entero como texto.
    Útil para limpiar claves de dependencia con formatos mixtos.
    """
    if not v:
        return None
    m = re.findall(r"\d+", str(v))
    return str(int(m[0])) if m else None


def _leer_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """
    Extrae la lista de Shared Strings (cadenas compartidas) del archivo XML del XLSX.
    En el formato de Excel OpenXML, los textos repetidos se indexan en un XML común
    llamado 'sharedStrings.xml' para ahorrar espacio.
    """
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall("a:si", NS_MAIN):
        out.append("".join((t.text or "") for t in si.findall(".//a:t", NS_MAIN)))
    return out


def _valor_celda(celda: ET.Element, shared: list[str]) -> str:
    """
    Obtiene el valor real de una celda XML. Si el atributo 't' es 's', el valor de la
    celda representa un índice entero que apunta a la lista de Shared Strings.
    """
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
    """
    Lee la primera hoja del archivo Excel (BaseDatoDepAct.xlsx) de forma nativa.
    Carga el mapeo entre la CLAVE y la DEPENDENCIA.
    Utiliza lru_cache para evitar re-leer el archivo en disco múltiples veces.
    Retorna un diccionario de mapeo {número_clave: nombre_dependencia}.
    """
    out: dict[str, str] = {}
    if not EXCEL_PATH.exists():
        return out

    try:
        # Abre el XLSX como un archivo ZIP y lee las relaciones internas de hojas
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

            # Leer primera fila como encabezado para identificar qué columnas contienen la CLAVE y DEPENDENCIA
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

            # Itera a partir de la segunda fila y extrae los registros
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
    """
    Intenta asociar los valores de entrada con una dependencia real del catálogo.
    Flujo de normalización:
    1. Si se ingresa una clave numérica que existe en el catálogo, devuelve esa clave y su dependencia oficial.
    2. Si se ingresa una cadena de texto, busca coincidencias exactas con el nombre normalizado.
    3. Si no hay coincidencia exacta, busca coincidencias difusas usando SequenceMatcher (Jaccard-like ratio).
       Si la coincidencia supera el 72% de confianza, se asume correcta y se autocompletan los datos.
    """
    numero_limpio = _limpiar_numero(numero)
    nombre_limpio = (nombre or "").strip() or None

    cat = catalogo_dependencias()
    # 1. Coincidencia exacta por clave numérica
    if numero_limpio and numero_limpio in cat:
        return numero_limpio, cat[numero_limpio]

    # 2. Búsqueda exacta y difusa por nombre
    if nombre_limpio and cat:
        nombre_norm = _norm_texto(nombre_limpio)

        for num, nom in cat.items():
            if _norm_texto(nom) == nombre_norm:
                return num, nom

        # Búsqueda difusa si no hay correspondencia exacta
        mejor_numero = None
        mejor_nombre = None
        mejor_score = 0.0
        for num, nom in cat.items():
            score = difflib.SequenceMatcher(None, nombre_norm, _norm_texto(nom)).ratio()
            if score > mejor_score:
                mejor_score = score
                mejor_numero = num
                mejor_nombre = nom

        # Umbral mínimo de coincidencia: 72%
        if mejor_numero and mejor_score >= 0.72:
            return mejor_numero, mejor_nombre

    return numero_limpio, nombre_limpio
