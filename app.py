"""
app.py - Servidor principal de Flask para captura manual de actas y visualización en el dashboard.
Este script maneja las rutas HTTP para renderizar vistas, endpoints API, validación de datos
y la generación dinámica de archivos PDF de manera directa sin librerías externas.
"""

from __future__ import annotations

import os
import math
import smtplib
import time
from time import perf_counter
from email.message import EmailMessage

# La zona horaria se maneja de forma multiplataforma usando zoneinfo en las funciones que lo requieren


from flask import Flask, Response, jsonify, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash

import db
from dependencias import normalizar_dependencia

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.json.ensure_ascii = False

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
DEFAULT_ADMIN_PASSWORD_HASH = generate_password_hash("1548")


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    txt = str(value).replace("\\", " ").replace('"', "")
    return " ".join(txt.split()).strip()


def obtener_fecha_mexico() -> str:
    """
    Retorna la fecha actual en formato AAAA-MM-DD según la zona horaria de México (America/Mexico_City).
    Funciona tanto en Windows como en servidores Linux de forma nativa sin requerir tzset.
    """
    from datetime import datetime
    import zoneinfo
    try:
        tz = zoneinfo.ZoneInfo("America/Mexico_City")
        return datetime.now(tz).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _to_int(value, default=0):
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalizar_candidatos(data):
    """
    Normaliza y limpia la lista de candidatos recibida desde el frontend.
    Maneja el formato antiguo (candidato unitario) y el formato nuevo (múltiples candidatos por planilla).
    Retorna la lista ordenada descendentemente por número de votos.
    """
    if not isinstance(data, list):
        return []

    candidatos = []
    for c in data:
        item = c or {}
        planilla = _safe_text(item.get("planilla")) or "Sin planilla"

        # Formato nuevo: una planilla puede traer varios candidatos.
        lista = item.get("candidatos")
        if isinstance(lista, list) and lista:
            votos_planilla = _to_int(item.get("votos"), 0)
            porcentaje_planilla = _to_float(item.get("porcentaje"), 0)
            delegados_planilla = _to_int(item.get("delegados_ganados"), 0)
            for idx, nombre in enumerate(lista):
                cand_name = _safe_text(nombre) or "Sin nombre"
                candidatos.append(
                    {
                        "planilla": planilla,
                        "expresion_politica": _safe_text(item.get("expresion_politica")),
                        "candidato": cand_name,
                        "votos": votos_planilla if idx == 0 else 0,
                        "porcentaje": porcentaje_planilla if idx == 0 else 0.0,
                        "delegados_ganados": delegados_planilla if idx == 0 else 0,
                    }
                )
            continue

        candidatos.append(
            {
                "planilla": planilla,
                "expresion_politica": _safe_text(item.get("expresion_politica")),
                "candidato": _safe_text(item.get("candidato")) or "Sin nombre",
                "votos": _to_int(item.get("votos"), 0),
                "porcentaje": _to_float(item.get("porcentaje"), 0),
                "delegados_ganados": _to_int(item.get("delegados_ganados"), 0),
            }
        )

    return sorted(candidatos, key=lambda x: x["votos"], reverse=True)


def normalizar_resumen(resumen):
    """
    Normaliza los valores agregados del acta (votos totales, nulos, abstenciones, boletas no usadas
    y el padrón del sindicato) asegurando que sean enteros válidos y no nulos.
    """
    r = resumen if isinstance(resumen, dict) else {}
    return {
        "votos_totales": _to_int(r.get("votos_totales"), 0),
        "votos_nulos": _to_int(r.get("votos_nulos"), 0),
        "abstenciones": _to_int(r.get("abstenciones"), 0),
        "boletas_no_usadas": _to_int(r.get("boletas_no_usadas"), 0),
        "delegados_totales": _to_int(r.get("delegados_totales"), 0),
        # siempre se recalcula automaticamente
        "total_padron_sindicato": _to_int(r.get("total_padron_sindicato"), 0),
    }


def agrupar_planillas(candidatos: list[dict], votos_totales: int = 0) -> list[dict]:
    """
    Agrupa los candidatos por planilla. Suma los votos de todos los candidatos de la misma planilla,
    recalcula el porcentaje que representan sobre el total de votos y acumula los delegados ganados.
    """
    grupos: dict[str, dict] = {}

    for c in candidatos or []:
        planilla = _safe_text(c.get("planilla")) or "Sin planilla"
        item = grupos.setdefault(
            planilla,
            {
                "planilla": planilla,
                "expresion_politica": _safe_text(c.get("expresion_politica")) or "",
                "candidatos": [],
                "votos": 0,
                "porcentaje": 0.0,
                "delegados_ganados": 0,
            },
        )

        nombre_candidato = _safe_text(c.get("candidato")) or "Sin nombre"
        if nombre_candidato not in item["candidatos"]:
            item["candidatos"].append(nombre_candidato)

        if not item["expresion_politica"] and _safe_text(c.get("expresion_politica")):
            item["expresion_politica"] = _safe_text(c.get("expresion_politica")) or ""

        item["votos"] += max(0, _to_int(c.get("votos"), 0))
        item["delegados_ganados"] += _to_int(c.get("delegados_ganados"), 0)

    total = _to_int(votos_totales, 0)
    if total <= 0:
        total = sum(g["votos"] for g in grupos.values())

    out = list(grupos.values())
    for g in out:
        g["porcentaje"] = round((g["votos"] / total) * 100, 2) if total > 0 else 0.0

    out.sort(key=lambda x: x["votos"], reverse=True)
    return out


def _admin_autorizado(payload: dict) -> bool:
    """
    Verifica las credenciales de administrador enviadas en el payload.
    Compara el hash de la contraseña usando pbkdf2:sha256 (seguridad de Werkzeug).
    """
    usuario = _safe_text((payload or {}).get("usuario")) or ""
    contrasena = str((payload or {}).get("contrasena") or "")
    hash_objetivo = ADMIN_PASSWORD_HASH or DEFAULT_ADMIN_PASSWORD_HASH
    return usuario == ADMIN_USER and check_password_hash(hash_objetivo, contrasena)


def validar_acta(candidatos: list, resumen: dict) -> str | None:
    """
    Valida la consistencia de los datos del acta electoral.
    Verifica que no haya votos ni delegados negativos y que las planillas contengan votos.
    """
    if not candidatos:
        return "Debes capturar minimo 1 candidato completo."

    for c in candidatos:
        if c.get("planilla") == "Sin planilla" or c.get("candidato") == "Sin nombre":
            return "Cada candidato debe tener planilla y nombre."
        if _to_int(c.get("votos"), 0) < 0:
            return "Los votos no pueden ser negativos."
        if _to_int(c.get("delegados_ganados"), 0) < 0:
            return "Los delegados ganados no pueden ser negativos."

    planillas = agrupar_planillas(candidatos)
    if not planillas or any(p.get("votos", 0) <= 0 for p in planillas):
        return "Cada planilla debe tener votos mayores a 0."

    for campo in ("votos_nulos", "abstenciones", "boletas_no_usadas"):
        if _to_int(resumen.get(campo), 0) < 0:
            return "Los valores del resumen no pueden ser negativos."

    return None

def recalcular_padron(resumen: dict) -> tuple[dict, bool]:
    """
    Recalcula el total del padrón (Punto 11) como la suma aritmética de:
    Votos Totales + Votos Nulos + Abstenciones + Boletas no Usadas.
    Retorna el resumen ajustado y un booleano indicando si el valor original cambió.
    """
    r = normalizar_resumen(resumen)
    total_calculado = (
        r["votos_totales"]
        + r["votos_nulos"]
        + r["abstenciones"]
        + r["boletas_no_usadas"]
    )
    era_distinto = r.get("total_padron_sindicato", 0) != total_calculado
    r["total_padron_sindicato"] = total_calculado
    return r, era_distinto


def _pdf_escape(texto: str) -> str:
    """
    Escapa caracteres especiales del estándar PDF para evitar que rompan la estructura del stream.
    Duplica las diagonales invertidas y escapa paréntesis.
    """
    return (texto or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _as_latin1(texto: str) -> str:
    """
    Codifica el texto en latin-1 para compatibilidad directa con los tipos de fuente estándar
    de PDF (Helvetica, Helvetica-Bold) y evitar caracteres multibyte UTF-8 que romperían el visor.
    """
    return (texto or "").encode("latin-1", errors="replace").decode("latin-1")


def _pie_wedge_points(cx: float, cy: float, r: float, a0: float, a1: float, steps: int = 18):
    """
    Calcula los puntos vectoriales que conforman un sector de la gráfica de pastel
    desde el ángulo a0 hasta a1, con un radio r centrado en cx, cy.
    Retorna una lista de tuplas (x, y) donde el primer punto es el centro del pastel.
    """
    pts = [(cx, cy)]
    for i in range(steps + 1):
        t = a0 + (a1 - a0) * (i / steps)
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts

def _pdf_draw_pie(cx: float, cy: float, r: float, values: list[float], colors: list[tuple[float, float, float]]) -> list[str]:
    """
    Genera comandos de dibujo de gráficos vectoriales en sintaxis PDF nativa
    para representar una gráfica circular (pie chart) basándose en los votos de las planillas.
    """
    total = sum(max(0.0, float(v)) for v in values)
    if total <= 0:
        return []
    cmds: list[str] = []
    ang = -math.pi / 2
    for idx, v in enumerate(values):
        v = max(0.0, float(v))
        if v <= 0:
            continue
        span = (v / total) * (2 * math.pi)
        next_ang = ang + span
        rr, gg, bb = colors[idx % len(colors)]
        pts = _pie_wedge_points(cx, cy, r, ang, next_ang)
        cmds.append(f"q {rr:.3f} {gg:.3f} {bb:.3f} rg")
        x0, y0 = pts[0]
        cmds.append(f"{x0:.2f} {y0:.2f} m")
        for x, y in pts[1:]:
            cmds.append(f"{x:.2f} {y:.2f} l")
        cmds.append("h f Q")
        ang = next_ang
    # Borde exterior de la gráfica circular
    ring_pts = _pie_wedge_points(cx, cy, r, 0, 2 * math.pi, 48)[1:]
    if ring_pts:
        cmds.append("q 0.35 0.45 0.60 RG 0.8 w")
        x0, y0 = ring_pts[0]
        cmds.append(f"{x0:.2f} {y0:.2f} m")
        for x, y in ring_pts[1:]:
            cmds.append(f"{x:.2f} {y:.2f} l")
        cmds.append("h S Q")
    return cmds

def _armar_pdf_acta(acta: dict) -> bytes:
    """
    Ensambla de forma dinámica y a nivel de bytes un archivo PDF compatible con la especificación 1.4.
    Dibuja la cabecera, barra de información, tabla de planillas con ganadores resaltados en verde,
    el desglose de delegados ganados, el resumen general y el gráfico circular de votación.
    """
    candidatos = normalizar_candidatos((acta or {}).get("candidatos"))
    resumen = normalizar_resumen((acta or {}).get("resumen"))
    planillas = agrupar_planillas(candidatos, resumen.get("votos_totales", 0))
    max_votos = max((p.get("votos", 0) for p in planillas), default=0)
    ganador_nombre = None
    for p in planillas:
        if p.get("votos", 0) == max_votos and max_votos > 0:
            ganador_nombre = p.get("planilla")
            break

    if resumen.get("votos_totales", 0) <= 0:
        resumen["votos_totales"] = sum(p.get("votos", 0) for p in planillas)
    resumen, _ = recalcular_padron(resumen)

    N = (0.11, 0.23, 0.37)
    G = (0.83, 0.65, 0.13)
    Gn = (0.16, 0.52, 0.20)

    def t(x: float, y: float, text: str, font: str = "F1", size: int = 11) -> str:
        txt = _pdf_escape(_as_latin1(text))
        return f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({txt}) Tj ET"

    def t_right(x_right: float, y: float, text: str, font: str = "F1", size: int = 11) -> str:
        txt = str(text or "")
        ancho_aprox = max(0, len(txt)) * (size * 0.52)
        return t(x_right - ancho_aprox, y, txt, font, size)

    def money(v) -> str:
        return str(_to_int(v, 0))

    def setRGB(r, g, b):
        contenido.append(f"{r:.3f} {g:.3f} {b:.3f} rg")

    contenido = []

    # ===================== HEADER =====================
    contenido.append(f"q {N[0]:.2f} {N[1]:.2f} {N[2]:.2f} rg 0 770 595 72 re f Q")
    contenido.append(f"q {G[0]:.2f} {G[1]:.2f} {G[2]:.2f} rg 0 770 595 3 re f Q")
    setRGB(1, 1, 1)
    contenido.append(t(42, 816, "ACTA ELECTORAL", "F2", 20))
    titulo_congreso = "STUNAM - CONGRESO GENERAL ORDINARIO XLIII" if acta.get("sistema") == "CGO" else "STUNAM - CONGRESO GENERAL DE REPRESENTANTES XXII"
    contenido.append(t(42, 793, titulo_congreso, "F1", 10))
    contenido.append(t_right(553, 816, f"ID #{acta.get('id', 'N/D')}", "F2", 11))
    setRGB(0, 0, 0)
    # ===================== INFO BAR =====================
    # Caja más alta para evitar colisiones
    contenido.append("q 0.96 0.97 0.98 rg 36 660 523 90 re f Q")
    contenido.append(f"q {N[0]:.2f} {N[1]:.2f} {N[2]:.2f} RG 0.5 w 36 660 523 90 re S Q")

    dep = f"{(acta.get('numero') or 'N/D')} - {(acta.get('nombre') or 'N/D')}"

    # DEPENDENCIA
    contenido.append(t(44, 735, "DEPENDENCIA", "F2", 7))
    contenido.append(t(44, 720, dep, "F1", 8))

    # FECHA (izquierda)
    contenido.append(t(44, 695, "FECHA", "F2", 7))
    contenido.append(t(44, 680, acta.get('fecha') or 'Sin fecha', "F1", 8))

    # CAPTURISTA (al lado de FECHA)
    contenido.append(t(300, 695, "CAPTURISTA", "F2", 7))
    contenido.append(t(300, 680, acta.get('capturista') or 'N/D', "F1", 8))
    # ===================== TABLE =====================
    y_top = 645
    contenido.append(t(36, y_top, "PLANILLAS PARTICIPANTES", "F2", 11))

    head_top = y_top - 14
    head_h = 18
    head_bot = head_top - head_h

    contenido.append(f"q {N[0]:.2f} {N[1]:.2f} {N[2]:.2f} rg 36 {head_bot:.2f} 523 {head_h} re f Q")
    setRGB(1, 1, 1)

    x_plan = 44
    x_expr = 150
    x_cands = 278
    x_votos_r = 462
    x_pct_r = 508
    x_dg_r = 555

    contenido.append(t(x_plan, head_bot + 4, "PLANILLA", "F2", 8))
    contenido.append(t(x_expr, head_bot + 4, "EXP. POLITICA", "F2", 8))
    contenido.append(t(x_cands, head_bot + 4, "CANDIDATOS", "F2", 8))
    contenido.append(t(432, head_bot + 4, "VOTOS", "F2", 8))
    contenido.append(t(497, head_bot + 4, "%", "F2", 8))
    contenido.append(t(533, head_bot + 4, "DEL.", "F2", 8))
    setRGB(0, 0, 0)

    y = head_bot - 2
    line_h = 10
    base_sz = 9

    for i, pz in enumerate(planillas):
        lista_cands = [str(n).strip() for n in (pz.get("candidatos", []) or []) if str(n).strip()]
        if not lista_cands:
            lista_cands = ["N/D"]

        show_cands = lista_cands[:3]
        remaining = len(lista_cands) - 3
        lines = list(show_cands)
        if remaining > 0:
            last = lines[-1] if lines else ""
            lines[-1] = last if len(last) < 34 else last[:34]
            lines.append(f"+ {remaining} mas")

        wrapped = []
        for nombre in lines:
            if len(nombre) <= 36:
                wrapped.append(nombre)
            else:
                words = nombre.split()
                cur = ""
                for w in words:
                    if len(cur) + len(w) + 1 <= 36:
                        cur += (" " if cur else "") + w
                    else:
                        if cur:
                            wrapped.append(cur)
                        cur = w
                if cur:
                    wrapped.append(cur)
        lines = wrapped or ["N/D"]

        row_h = max(28, 8 + len(lines) * line_h + 4)
        row_top = y
        row_bot = row_top - row_h
        es_ganador = pz.get("planilla") == ganador_nombre

        if es_ganador:
            contenido.append(f"q 0.92 0.98 0.92 rg 36 {row_bot:.2f} 523 {row_h} re f Q")
            contenido.append(f"q {Gn[0]:.2f} {Gn[1]:.2f} {Gn[2]:.2f} rg 36 {row_bot:.2f} 4 {row_h} re f Q")
        elif i % 2 == 1:
            contenido.append(f"q 0.965 0.972 0.978 rg 36 {row_bot:.2f} 523 {row_h} re f Q")

        contenido.append(f"q 0.88 0.90 0.92 RG 0.3 w 36 {row_bot:.2f} 523 0 re S Q")

        fnt = "F2" if es_ganador else "F1"
        plan_name = str(pz.get("planilla", "N/D"))[:22]
        expr = str(pz.get("expresion_politica", "") or "")[:28]
        cy = row_top - (row_h / 2) - 2

        contenido.append(t(x_plan, cy, plan_name, fnt, base_sz))
        contenido.append(t(x_expr, cy, expr, fnt, base_sz))

        cy_c = row_top - 9
        for line in lines:
            contenido.append(t(x_cands, cy_c, line, fnt, base_sz - 1))
            cy_c -= line_h

        votos = money(pz.get("votos", 0))
        pct = f"{_to_float(pz.get('porcentaje', 0), 0):.1f}%"
        dg = money(pz.get("delegados_ganados", 0))

        contenido.append(t_right(x_votos_r, cy, votos, fnt, base_sz))
        contenido.append(t_right(x_pct_r, cy, pct, fnt, base_sz))
        if es_ganador:
            setRGB(*Gn)
        contenido.append(t_right(x_dg_r, cy, dg, "F2", base_sz))
        if es_ganador:
            setRGB(0, 0, 0)

        y = row_bot - 4
        if y < 300:
            break

    # ===================== BOTTOM SECTION =====================
    sec_top = y - 8
    lx = 36
    lw = 275
    rx = 324
    rw = 235
    sh = 240
    sb = sec_top - sh

    # --- RESUMEN CARD ---
    contenido.append(t(lx, sec_top + 6, "RESUMEN", "F2", 11))
    contenido.append(f"q 0.99 0.995 1 rg {lx} {sb:.2f} {lw} {sh-6} re f Q")
    contenido.append(f"q 0.78 0.86 0.93 RG 0.6 w {lx} {sb:.2f} {lw} {sh-6} re S Q")

    resumen_lineas = [
        ("Votos totales", resumen.get("votos_totales", 0)),
        ("Votos nulos", resumen.get("votos_nulos", 0)),
        ("Abstenciones", resumen.get("abstenciones", 0)),
        ("Boletas no usadas", resumen.get("boletas_no_usadas", 0)),
        ("Padron sindicato", resumen.get("total_padron_sindicato", 0)),
    ]
    ry = sec_top - 18
    for label, value in resumen_lineas:
        contenido.append(t(lx + 14, ry, label, "F1", 9))
        contenido.append(t_right(lx + lw - 14, ry, money(value), "F2", 9))
        contenido.append(f"q 0.88 0.90 0.92 RG 0.2 w {lx + 14} {ry - 9:.2f} {lw - 28} 0 re S Q")
        ry -= 19

    sep_y = ry + 8
    contenido.append(f"q 0.78 0.86 0.93 RG 0.4 w {lx + 14} {sep_y:.2f} {lw - 28} 0 re S Q")

    dl_y = sep_y - 18
    visibles_deleg = planillas[:6]
    contenido.append(t(lx + 14, dl_y, "DELEGADOS GANADOS", "F2", 9))
    contenido.append(t(lx + 14, dl_y - 14, "Total en disputa:", "F1", 8))
    setRGB(*Gn)
    contenido.append(t_right(lx + lw - 14, dl_y - 14, money(resumen.get("delegados_totales", 0)), "F2", 9))
    setRGB(0, 0, 0)

    dy = dl_y - 32

    for pz in visibles_deleg:
        nom = str(pz.get("planilla", "N/D"))[:14]
        dg = _to_int(pz.get("delegados_ganados", 0), 0)
        contenido.append(t(lx + 14, dy, nom, "F1", 7))
        # Solo ganadores en rojo
        if dg > 0:
            setRGB(0.85, 0.15, 0.15)   # rojo
        else:
            setRGB(0, 0, 0)            # negro

        contenido.append(t_right(
            lx + lw - 14,
            dy,
            str(dg),
            "F2",
            8
        ))

        setRGB(0, 0, 0)
        dy -= 11
    if len(planillas) > len(visibles_deleg):
        contenido.append(t(lx + 14, dy, f"... +{len(planillas) - len(visibles_deleg)} planillas", "F1", 7))

    # --- PIE CHART ---
    contenido.append(t(rx, sec_top + 6, "DISTRIBUCION DE VOTOS", "F2", 9))
    contenido.append(f"q 0.99 0.995 1 rg {rx} {sb:.2f} {rw} {sh-6} re f Q")
    contenido.append(f"q 0.78 0.86 0.93 RG 0.6 w {rx} {sb:.2f} {rw} {sh-6} re S Q")

    pie_values = [max(0, _to_int(pz.get("votos"), 0)) for pz in planillas[:5]]
    pie_colors = []
    for idx, pz in enumerate(planillas[:5]):
        if ganador_nombre and pz.get("planilla") == ganador_nombre:
            pie_colors.append(Gn)
        else:
            paleta = [N, G, (0.93, 0.36, 0.34), (0.56, 0.44, 0.84)]
            pie_colors.append(paleta[idx % len(paleta)])

    pie_cx = rx + 68
    pie_cy = sb + 105
    pie_r = 40
    contenido.extend(_pdf_draw_pie(pie_cx, pie_cy, pie_r, pie_values, pie_colors))

    ly2 = sec_top - 18
    for i, pz in enumerate(planillas[:4]):
        rr, gg, bb = pie_colors[i % len(pie_colors)]
        vp = _to_int(pz.get("votos"), 0)
        pp = _to_float(pz.get("porcentaje"), 0)
        np_ = str(pz.get("planilla", "N/D"))[:10]
        lx2 = rx + 122
        contenido.append(f"q {rr:.3f} {gg:.3f} {bb:.3f} rg {lx2} {ly2 - 1:.2f} 7 7 re f Q")
        contenido.append(f"q 0.35 0.45 0.60 RG 0.3 w {lx2} {ly2 - 1:.2f} 7 7 re S Q")
        contenido.append(t(lx2 + 10, ly2, f"{np_}: {vp} ({pp:.1f}%)", "F1", 7))
        ly2 -= 12

    # ===================== FOOTER =====================
    contenido.append(f"q {N[0]:.2f} {N[1]:.2f} {N[2]:.2f} rg 0 0 595 32 re f Q")
    contenido.append(f"q {G[0]:.2f} {G[1]:.2f} {G[2]:.2f} rg 0 32 595 2 re f Q")
    setRGB(1, 1, 1)
    contenido.append(t(42, 18, "Documento generado automaticamente por el sistema de captura oficial", "F1", 8))
    footer_texto = "STUNAM - Resultados CGO XLIII" if acta.get("sistema") == "CGO" else "STUNAM - Resultados CGR XXII"
    contenido.append(t(42, 7, footer_texto, "F1", 7))
    setRGB(0, 0, 0)

    # ===================== PDF ASSEMBLY =====================
    stream = "\n".join(contenido).encode("latin-1", errors="replace")
    objs = []
    objs.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objs.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objs.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>\nendobj\n"
    )
    objs.append(
        b"4 0 obj\n<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream\nendobj\n"
    )
    objs.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
    objs.append(b"6 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for o in objs:
        offsets.append(len(pdf))
        pdf.extend(o)
    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objs)+1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)

@app.after_request
def add_cors_headers(response):
    """
    Middleware que inyecta cabeceras CORS (Cross-Origin Resource Sharing) en cada respuesta HTTP.
    Permite llamadas AJAX desde orígenes externos (como el sitio estático de Netlify).
    """
    response.headers["Access-Control-Allow-Origin"] = os.getenv("CORS_ORIGIN", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response


def _armar_resultados_dashboard(sistema: str | None = None) -> list[dict]:
    """
    Recupera todas las actas de la base de datos y las procesa para darles el formato
    necesitado por el dashboard, incluyendo ganadores y empates.
    """
    resultados = []
    for acta in db.obtener_todas(sistema):
        resultados.append(_armar_resultado_desde_acta(acta))
    return resultados


def _armar_resultado_desde_acta(acta: dict) -> dict:
    """
    Genera la estructura de resultados detallados para un acta, resolviendo la planilla
    ganadora o la existencia de empates.
    """
    candidatos = normalizar_candidatos(acta.get("candidatos"))
    resumen = normalizar_resumen(acta.get("resumen"))
    planillas = agrupar_planillas(candidatos, resumen.get("votos_totales", 0))

    ganador = None
    ganadores = []
    empate = False
    if planillas:
        max_votos = max(p.get("votos", 0) for p in planillas)
        ganadores = [p for p in planillas if p.get("votos", 0) == max_votos]
        ganador = ganadores[0] if ganadores else None
        empate = len(ganadores) > 1

    return {
        "id": acta.get("id"),
        "numero": acta.get("numero"),
        "nombre": acta.get("nombre"),
        "fecha": acta.get("fecha"),
        "capturista": acta.get("capturista"),
        "candidatos": candidatos,
        "planillas": planillas,
        "ganador": ganador,
        "ganadores": ganadores,
        "empate": empate,
        "resumen": resumen,
        "sistema": acta.get("sistema"),
    }


def _crear_acta_sistema(sistema: str, cross_ref: bool):
    inicio = perf_counter()
    payload = request.get_json(silent=True) or {}

    numero_raw = payload.get("numero")
    nombre_raw = payload.get("nombre")
    fecha = _safe_text(payload.get("fecha"))
    if not fecha:
        fecha = obtener_fecha_mexico()
    capturista = _safe_text(payload.get("capturista"))

    if cross_ref:
        numero, nombre = normalizar_dependencia(numero_raw, nombre_raw)
        numero = _safe_text(numero)
        nombre = _safe_text(nombre)
    else:
        numero = _safe_text(numero_raw)
        nombre = _safe_text(nombre_raw)

    if not numero and not nombre:
        return jsonify({"status": "error", "mensaje": "Debes capturar numero o nombre de dependencia"}), 400

    if not numero or not nombre:
        return jsonify({
            "status": "error",
            "mensaje": "No se pudo encontrar coincidencia entre numero y nombre de dependencia",
        }), 400

    # Priorizar formato nuevo: planillas con candidatos ligados a cada planilla.
    candidatos_src = payload.get("planillas")
    if not isinstance(candidatos_src, list):
        candidatos_src = payload.get("candidatos")

    resumen_src = payload.get("resumen")
    if not isinstance(resumen_src, dict):
        resumen_src = payload.get("resumen datos")

    candidatos = normalizar_candidatos(candidatos_src)
    resumen = normalizar_resumen(resumen_src)
    error_validacion = validar_acta(candidatos, resumen)
    if error_validacion:
        return jsonify({"status": "error", "mensaje": error_validacion}), 400

    total = resumen.get("votos_totales", 0)
    if total <= 0:
        total = sum(c["votos"] for c in candidatos)
        resumen["votos_totales"] = total

    if total > 0:
        for c in candidatos:
            if not c.get("porcentaje"):
                c["porcentaje"] = round((c["votos"] / total) * 100, 2)

    resumen, padron_ajustado = recalcular_padron(resumen)

    save_id = db.guardar_manual(
        numero=numero,
        nombre=nombre,
        fecha=fecha,
        candidatos=candidatos,
        resumen=resumen,
        fuente="formulario_online",
        capturista=capturista,
        sistema=sistema
    )

    fin = perf_counter()
    data = {
        "id": save_id,
        "numero": numero,
        "nombre": nombre,
        "fecha": fecha,
        "capturista": capturista,
        "candidatos": candidatos,
        "planillas": agrupar_planillas(candidatos, resumen.get("votos_totales", 0)),
        "resumen": resumen,
        "processing_ms": int((fin - inicio) * 1000),
        "processing_s": round(fin - inicio, 3),
    }
    if padron_ajustado:
        data["aviso"] = "El total padron sindicato fue recalculado como suma de puntos 7+8+9+10."
    return jsonify({"status": "ok", "data": data})


# ---------------- WEB ROUTING VIEWS ----------------

@app.route("/favicon.ico")
def favicon():
    """
    Ruta para el favicon por defecto de los navegadores.
    """
    return app.send_static_file("favicon.svg")


@app.route("/")
def dashboard():
    """
    Ruta principal. Renderiza el portal de bienvenida y selector.
    """
    return render_template("bienvenida.html")


@app.route("/<any(cgr, cgo):sistema>")
def dashboard_sistema(sistema: str):
    """
    Dashboard de Resultados para CGR XXII o CGO XLIII de forma dinámica.
    """
    sistema_upper = sistema.upper()
    resultados = _armar_resultados_dashboard(sistema_upper)
    return render_template(f"resultados_{sistema}.html", resultados=resultados)


def calcular_estadisticas_generales(resultados: list[dict]) -> dict:
    """
    Calcula estadísticas consolidadas del sistema, incluyendo:
    - Actas computadas
    - Votación total acumulada (suma de votos de todas las planillas)
    - Puestos delegados disponibles (suma de delegados_totales de los resúmenes)
    - Top dos planillas con:
      - Nombre
      - Delegados ganados
      - Votos acumulados
      - Porcentaje de votación
      - Dependencias ganadas
    """
    actas_computadas = len(resultados)
    votacion_total_acumulada = 0
    puestos_delegados_disponibles = 0

    planillas_datos = {} # planilla -> {nombre, votos, delegados_ganados, dependencias_ganadas}

    for r in resultados:
        resumen = r.get("resumen") or {}
        puestos_delegados_disponibles += _to_int(resumen.get("delegados_totales"), 0)

        # Ganador de esta acta/dependencia para contar dependencias ganadas
        ganador_planilla = None
        if not r.get("empate") and r.get("ganador"):
            ganador_planilla = r["ganador"].get("planilla")

        for p in r.get("planillas") or []:
            nombre = p.get("planilla") or "Sin planilla"
            votos = _to_int(p.get("votos"), 0)
            delegados = _to_int(p.get("delegados_ganados"), 0)

            votacion_total_acumulada += votos

            if nombre not in planillas_datos:
                planillas_datos[nombre] = {
                    "nombre": nombre,
                    "votos": 0,
                    "delegados_ganados": 0,
                    "dependencias_ganadas": 0,
                }
            
            planillas_datos[nombre]["votos"] += votos
            planillas_datos[nombre]["delegados_ganados"] += delegados
            if ganador_planilla and nombre == ganador_planilla:
                planillas_datos[nombre]["dependencias_ganadas"] += 1

    # Convertir a lista y ordenar por votos descendentemente
    lista_planillas = list(planillas_datos.values())
    lista_planillas.sort(key=lambda x: x["votos"], reverse=True)

    # Calcular porcentaje de votación para cada planilla y formatear votos
    for p in lista_planillas:
        if votacion_total_acumulada > 0:
            p["porcentaje_votacion"] = round((p["votos"] / votacion_total_acumulada) * 100, 2)
        else:
            p["porcentaje_votacion"] = 0.0
        p["votos_formateados"] = f"{p['votos']:,}"

    top_dos = lista_planillas[:2]

    return {
        "actas_computadas": actas_computadas,
        "votacion_total_acumulada": votacion_total_acumulada,
        "votacion_total_acumulada_formateada": f"{votacion_total_acumulada:,}",
        "puestos_delegados_disponibles": puestos_delegados_disponibles,
        "puestos_delegados_disponibles_formateados": f"{puestos_delegados_disponibles:,}",
        "top_dos_planillas": top_dos,
    }


@app.route("/<any(cgr, cgo):sistema>/estadisticas")
def estadisticas_sistema(sistema: str):
    """
    Pagina dedicada a las estadisticas generales del CGR XXII o CGO XLIII.
    """
    sistema_upper = sistema.upper()
    resultados = _armar_resultados_dashboard(sistema_upper)
    estadisticas = calcular_estadisticas_generales(resultados)
    return render_template(f"estadisticas_{sistema}.html", resultados=resultados, estadisticas=estadisticas)


@app.route("/<any(cgr, cgo):sistema>/acta/<int:acta_id>", methods=["GET"])
def detalle_acta(sistema: str, acta_id: int):
    """
    Pagina de detalle de un acta para CGR XXII o CGO XLIII.
    """
    sistema_upper = sistema.upper()
    acta = db.obtener_por_id(acta_id)
    if not acta or acta.get("sistema") != sistema_upper:
        return Response(f"Acta no encontrada en {sistema_upper}", status=404, mimetype="text/plain")
    resultado = _armar_resultado_desde_acta(acta)
    return render_template(f"acta_detalle_{sistema}.html", r=resultado)


# ---------------- API ENDPOINTS (DYNAMICAL CGR / CGO) ----------------

@app.route("/api/<any(cgr, cgo):sistema>/actas", methods=["GET"])
def listar_actas(sistema: str):
    sistema_upper = sistema.upper()
    return jsonify({"status": "ok", "data": _armar_resultados_dashboard(sistema_upper)})


@app.route("/api/<any(cgr, cgo):sistema>/actas", methods=["POST", "OPTIONS"])
def crear_acta_manual(sistema: str):
    if request.method == "OPTIONS":
        return ("", 204)
    sistema_upper = sistema.upper()
    cross_ref = (sistema_upper == "CGR")
    return _crear_acta_sistema(sistema_upper, cross_ref=cross_ref)


@app.route("/api/<any(cgr, cgo):sistema>/actas/estado", methods=["GET"])
def estado_actas(sistema: str):
    sistema_upper = sistema.upper()
    return jsonify({"status": "ok", "data": db.obtener_estado(sistema_upper)})


@app.route("/api/<any(cgr, cgo):sistema>/estadisticas", methods=["GET"])
def api_estadisticas(sistema: str):
    sistema_upper = sistema.upper()
    resultados = _armar_resultados_dashboard(sistema_upper)
    stats = calcular_estadisticas_generales(resultados)
    return jsonify({"status": "ok", "data": stats})


@app.route("/api/<any(cgr, cgo):sistema>/actas/<int:acta_id>/pdf", methods=["GET"])
def descargar_pdf_acta(sistema: str, acta_id: int):
    sistema_upper = sistema.upper()
    acta = db.obtener_por_id(acta_id)
    if not acta or acta.get("sistema") != sistema_upper:
        return jsonify({"status": "error", "mensaje": f"Acta {sistema_upper} no encontrada"}), 404
    pdf = _armar_pdf_acta(acta)
    nombre = f"acta_{sistema}_{acta_id}.pdf"
    return Response(
        pdf,
        headers={
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Cache-Control": "no-store",
        },
    )


@app.route("/api/<any(cgr, cgo):sistema>/actas/<int:acta_id>", methods=["DELETE", "OPTIONS"])
def eliminar_acta_manual(sistema: str, acta_id: int):
    if request.method == "OPTIONS":
        return ("", 204)
    payload = request.get_json(silent=True) or {}
    if not _admin_autorizado(payload):
        return jsonify({"status": "error", "mensaje": "No autorizado"}), 401
    sistema_upper = sistema.upper()
    acta = db.obtener_por_id(acta_id)
    if not acta or acta.get("sistema") != sistema_upper:
        return jsonify({"status": "error", "mensaje": "Acta no encontrada"}), 404
    ok = db.eliminar_acta(acta_id)
    if not ok:
        return jsonify({"status": "error", "mensaje": "Error al eliminar"}), 500
    return jsonify({"status": "ok", "mensaje": "Acta eliminada"})


# ---------------- DEPRECATED COMPATIBILITY ENDPOINTS ----------------

@app.route("/api/actas", methods=["GET", "POST", "OPTIONS"])
def api_actas_compat():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.method == "POST":
        return crear_acta_manual("cgr")
    return listar_actas("cgr")


@app.route("/api/actas/estado", methods=["GET"])
def api_estado_compat():
    return estado_actas("cgr")


@app.route("/api/actas/<int:acta_id>/pdf", methods=["GET"])
def api_pdf_compat(acta_id: int):
    return descargar_pdf_acta("cgr", acta_id)


@app.route("/upload", methods=["POST"])
def upload_deprecated():
    return jsonify({"status": "error", "mensaje": "OCR desactivado. Usa el formulario manual."}), 410


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")








