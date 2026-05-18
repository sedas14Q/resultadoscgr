"""
app.py - Captura manual de actas desde formulario y visualizacion en dashboard.
"""

from __future__ import annotations

import os
import math
import smtplib
from time import perf_counter
from email.message import EmailMessage

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
    usuario = _safe_text((payload or {}).get("usuario")) or ""
    contrasena = str((payload or {}).get("contrasena") or "")
    hash_objetivo = ADMIN_PASSWORD_HASH or DEFAULT_ADMIN_PASSWORD_HASH
    return usuario == ADMIN_USER and check_password_hash(hash_objetivo, contrasena)


def validar_acta(candidatos: list, resumen: dict) -> str | None:
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
    """Calcula punto 11 como suma de puntos 7,8,9,10."""
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
    return (texto or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _as_latin1(texto: str) -> str:
    return (texto or "").encode("latin-1", errors="replace").decode("latin-1")


def _pie_wedge_points(cx: float, cy: float, r: float, a0: float, a1: float, steps: int = 18):
    pts = [(cx, cy)]
    for i in range(steps + 1):
        t = a0 + (a1 - a0) * (i / steps)
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts

def _pdf_draw_pie(cx: float, cy: float, r: float, values: list[float], colors: list[tuple[float, float, float]]) -> list[str]:
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
    # Borde exterior
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
    contenido.append(t(42, 793, "STUNAM - CONGRESO GENERAL DE REPRESENTANTES XXII", "F1", 10))
    contenido.append(t_right(553, 816, f"ID #{acta.get('id', 'N/D')}", "F2", 11))
    setRGB(0, 0, 0)

    # ===================== INFO BAR =====================
    contenido.append("q 0.96 0.97 0.98 rg 36 700 523 70 re f Q")
    contenido.append(f"q {N[0]:.2f} {N[1]:.2f} {N[2]:.2f} RG 0.5 w 36 700 523 70 re S Q")

    dep = f"{(acta.get('numero') or 'N/D')} - {(acta.get('nombre') or 'N/D')}"

    # DEPENDENCIA
    contenido.append(t(44, 755, "DEPENDENCIA", "F2", 7))
    contenido.append(t(44, 742, dep, "F1", 8))

    # FECHA
    contenido.append(t(44, 725, "FECHA", "F2", 7))
    contenido.append(t(44, 712, acta.get('fecha') or 'Sin fecha', "F1", 8))

    # CAPTURISTA
    contenido.append(t(44, 695, "CAPTURISTA", "F2", 7))
    contenido.append(t(44, 682, acta.get('capturista') or 'N/D', "F1", 8))

    # ===================== TABLE =====================
    y_top = 728
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
        dg = money(pz.get("delegados_ganados", 0))
        contenido.append(t(lx + 14, dy, nom, "F1", 7))
        setRGB(*Gn)
        contenido.append(t_right(lx + lw - 14, dy, dg, "F2", 8))
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
    contenido.append(t(42, 7, "STUNAM - Resultados CGR XXII", "F1", 7))
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


def _enviar_pdf_correo(destinatario: str, acta: dict, pdf_bytes: bytes) -> tuple[bool, str]:
    host = os.getenv("SMTP_HOST", "").strip()
    try:
        puerto = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return False, "SMTP_PORT debe ser numerico."
    usuario = os.getenv("SMTP_USER", "").strip()
    contrasena = os.getenv("SMTP_PASSWORD", "")
    remitente = os.getenv("SMTP_FROM", usuario).strip()
    usar_tls = os.getenv("SMTP_TLS", "1").strip() not in {"0", "false", "False"}

    if not host or not remitente:
        return False, "SMTP no configurado. Define SMTP_HOST y SMTP_FROM."

    msg = EmailMessage()
    msg["Subject"] = f"Acta #{acta.get('numero', 'N/D')} - {acta.get('nombre', 'Dependencia')}"
    msg["From"] = remitente
    msg["To"] = destinatario
    msg.set_content("Se adjunta PDF del acta capturada.")
    filename = f"acta_{acta.get('id', 'sin_id')}.pdf"
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    try:
        with smtplib.SMTP(host, puerto, timeout=20) as server:
            if usar_tls:
                server.starttls()
            if usuario:
                server.login(usuario, contrasena)
            server.send_message(msg)
    except Exception as exc:
        return False, f"No se pudo enviar correo: {exc}"
    return True, "Correo enviado"


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = os.getenv("CORS_ORIGIN", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response


def _armar_resultados_dashboard() -> list[dict]:
    resultados = []
    for acta in db.obtener_todas():
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

        resultados.append(
            {
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
            }
        )
    return resultados


@app.route("/")
def dashboard():
    resultados = _armar_resultados_dashboard()
    return render_template("index.html", resultados=resultados)


@app.route("/api/actas", methods=["GET"])
def listar_actas():
    return jsonify({"status": "ok", "data": _armar_resultados_dashboard()})


@app.route("/api/actas", methods=["POST", "OPTIONS"])
def crear_acta_manual():
    if request.method == "OPTIONS":
        return ("", 204)

    inicio = perf_counter()
    payload = request.get_json(silent=True) or {}

    numero_raw = payload.get("numero")
    nombre_raw = payload.get("nombre")
    fecha = _safe_text(payload.get("fecha"))
    capturista = _safe_text(payload.get("capturista"))

    numero, nombre = normalizar_dependencia(numero_raw, nombre_raw)
    numero = _safe_text(numero)
    nombre = _safe_text(nombre)

    if not numero and not nombre:
        return jsonify({"status": "error", "mensaje": "Debes capturar numero o nombre de dependencia"}), 400

    if not numero or not nombre:
        return jsonify({
            "status": "error",
            "mensaje": "No se pudo encontrar coincidencia entre numero y nombre en la base de dependencias",
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


@app.route("/api/actas/estado", methods=["GET"])
def estado_actas():
    return jsonify({"status": "ok", "data": db.obtener_estado()})

@app.route("/api/health/db", methods=["GET"])
def health_db():
    estado = db.healthcheck()
    code = 200 if estado.get("ok") else 503
    return jsonify({"status": "ok" if estado.get("ok") else "error", "data": estado}), code


@app.route("/api/actas/<int:acta_id>/pdf", methods=["GET"])
def descargar_pdf_acta(acta_id: int):
    acta = db.obtener_por_id(acta_id)
    if not acta:
        return jsonify({"status": "error", "mensaje": "Acta no encontrada"}), 404

    pdf = _armar_pdf_acta(acta)
    nombre = f"acta_{acta_id}.pdf"
    return Response(
        pdf,
        headers={
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Cache-Control": "no-store",
        },
    )


@app.route("/api/actas/<int:acta_id>/correo", methods=["POST", "OPTIONS"])
def enviar_pdf_acta_correo(acta_id: int):
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    correo = _safe_text(payload.get("correo"))
    if not correo or "@" not in correo:
        return jsonify({"status": "error", "mensaje": "Correo invalido"}), 400

    acta = db.obtener_por_id(acta_id)
    if not acta:
        return jsonify({"status": "error", "mensaje": "Acta no encontrada"}), 404

    pdf = _armar_pdf_acta(acta)
    ok, mensaje = _enviar_pdf_correo(correo, acta, pdf)
    if not ok:
        return jsonify({"status": "error", "mensaje": mensaje}), 500
    return jsonify({"status": "ok", "mensaje": mensaje})




@app.route("/api/actas/<int:acta_id>", methods=["PUT", "OPTIONS"])
def actualizar_acta_manual(acta_id: int):
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    if not _admin_autorizado(payload):
        return jsonify({"status": "error", "mensaje": "No autorizado"}), 401

    numero_raw = payload.get("numero")
    nombre_raw = payload.get("nombre")
    fecha = _safe_text(payload.get("fecha"))
    capturista = _safe_text(payload.get("capturista"))

    numero, nombre = normalizar_dependencia(numero_raw, nombre_raw)
    numero = _safe_text(numero)
    nombre = _safe_text(nombre)

    if not numero or not nombre:
        return jsonify({"status": "error", "mensaje": "Numero o nombre de dependencia invalido"}), 400

    acta_actual = db.obtener_por_id(acta_id)
    if not acta_actual:
        return jsonify({"status": "error", "mensaje": "Acta no encontrada"}), 404

    if "planillas" in payload and isinstance(payload.get("planillas"), list):
        candidatos = normalizar_candidatos(payload.get("planillas"))
    elif "candidatos" in payload:
        candidatos = normalizar_candidatos(payload.get("candidatos"))
    else:
        candidatos = normalizar_candidatos(acta_actual.get("candidatos"))

    if "resumen" in payload:
        resumen = normalizar_resumen(payload.get("resumen"))
    else:
        resumen = normalizar_resumen(acta_actual.get("resumen"))

    total = resumen.get("votos_totales", 0)
    if total <= 0:
        total = sum(c["votos"] for c in candidatos)
        resumen["votos_totales"] = total
    if total > 0:
        for c in candidatos:
            c["porcentaje"] = round((c["votos"] / total) * 100, 2)

    error_validacion = validar_acta(candidatos, resumen)
    if error_validacion:
        return jsonify({"status": "error", "mensaje": error_validacion}), 400

    resumen, _ = recalcular_padron(resumen)

    ok = db.actualizar_acta(acta_id, numero, nombre, fecha, candidatos, resumen)
    if not ok:
        return jsonify({"status": "error", "mensaje": "Acta no encontrada"}), 404

    return jsonify({"status": "ok", "mensaje": "Acta actualizada"})


@app.route("/api/actas/<int:acta_id>", methods=["DELETE", "OPTIONS"])
def eliminar_acta_manual(acta_id: int):
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    if not _admin_autorizado(payload):
        return jsonify({"status": "error", "mensaje": "No autorizado"}), 401

    ok = db.eliminar_acta(acta_id)
    if not ok:
        return jsonify({"status": "error", "mensaje": "Acta no encontrada"}), 404

    return jsonify({"status": "ok", "mensaje": "Acta eliminada"})


@app.route("/upload", methods=["POST"])
def upload_deprecated():
    return jsonify({"status": "error", "mensaje": "OCR desactivado. Usa el formulario manual."}), 410


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")








