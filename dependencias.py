"""
dependencias.py - Módulo para normalizar números y nombres de dependencias electorales.
Contiene el catálogo embebido de dependencias electorales para evitar la carga de archivos Excel
y acelerar la ejecución del servidor y la compatibilidad en producción.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache

# Catálogo consolidado de dependencias electorales (clave: nombre)
CATALOGO: dict[str, str] = {
    "0": "Afiliados sin Delegación Sindical",
    "1": "Anexo Ingeniería",
    "2": "Base y Buque de Operaciones \"El Puma\", Mazatlán, Sinaloa",
    "3": "Base y Buque de Operaciones \"Justo Sierra\", Tuxpan, Veracruz",
    "4": "Biblioteca Nacional",
    "5": "Casa del Lago",
    "6": "Centro de Investigaciones sobre América Latina y el Caribe, Centro de Investigaciones y Estudios de Género",
    "7": "Centro de Asimilación Tecnológica y Vinculación",
    "8": "Instituto de Ciencias Aplicadas y Tecnología",
    "9": "Instituto de Ciencias de la Atmósfera y Cambio Climático",
    "10": "Instituto de Ciencias Físicas, Cuernavaca, Morelos",
    "11": "Centro de Desarrollo Infantil C.U.",
    "12": "Centro de Desarrollo Infantil Mascarones",
    "13": "Centro de Desarrollo Infantil Zaragoza",
    "14": "Centro de Educación Preescolar y Primaria del STUNAM",
    "15": "Escuela Nacional de Lenguas, Lingüística y Traducción",
    "16": "Centro de Enseñanza para Extranjeros",
    "17": "Centro de Enseñanza, Investigación y Extensión en Producción Animal en Altiplano, Tequisquiapan, Querétaro",
    "18": "Centro de Enseñanza Práctica e Investigación en Producción Salud Animal, Topilejo",
    "19": "Centro de Enseñanza, Investigación y Extensión en Ganadería Tropical, Martínez de la Torre, Veracruz",
    "20": "Centro de Enseñanza, Investigación y Extensión en Producción Avícola, Granja Veracruz, Zapotitlán, Tláhuac",
    "21": "Centro de Enseñanza, Investigación y Extensión en Producción Ovina, Tres Marías",
    "22": "Centro de Enseñanza, Investigación y Extensión en Producción Porcina, Jilotepec",
    "23": "Instituto de Investigaciones Sobre la Universidad y la Educación",
    "24": "Subdirección de Servicios e Información Especializada, DGB Anexo",
    "25": "Instituto de Energías Renovables, Temixco, Morelos",
    "26": "Centro de Ciencias Genómicas, Cuernavaca, Morelos",
    "27": "Centro de Investigaciones Interdisciplinarias en Ciencias y Humanidades",
    "28": "Centro de Investigaciones sobre América del Norte",
    "29": "Centro de Nanociencias y Nanotecnología, Ensenada, Baja California",
    "30": "Coordinación de Servicios Administrativos, Juriquilla, Querétaro",
    "31": "Centro Regional de Investigaciones Multidisciplinarias, Cuernavaca, Morelos",
    "32": "Escuela Nacional de Artes Cinematográficas",
    "33": "Instituto de Investigaciones Bibliotecológicas y de la Información",
    "34": "Clínica Acatlán",
    "35": "Clínica Almaraz",
    "36": "Clínica Aragón",
    "37": "Clínica Cuautepec",
    "38": "Clínica Cuautitlán",
    "39": "Clínica Ecatepec",
    "40": "Clínica El Molinito",
    "41": "Clínica Aurora",
    "42": "Clínica Benito Juárez",
    "43": "Clínica Estado de México",
    "44": "Clínica Reforma",
    "45": "Clínica Los Reyes",
    "46": "Clínica Tamaulipas",
    "47": "C.C.H. Azcapotzalco",
    "48": "C.C.H. Naucalpan",
    "49": "C.C.H. Oriente",
    "50": "C.C.H. SUR",
    "51": "C.C.H. Vallejo",
    "52": "Colegio de San Ildefonso",
    "53": "Unidad Coordinadora de Servicios de Apoyo Administrativo a los Consejos Académicos de Área",
    "54": "Coordinación de Difusión Cultural",
    "55": "Coordinación de Humanidades y Consejo Técnico",
    "56": "Consejo Técnico y Coordinación de la Investigación Científica",
    "57": "Coordinación de Servicios Administrativos, Morelia, Michoacán",
    "58": "Coordinación de Universidad Abierta, Innovación Educativa y Educación a Distancia",
    "59": "Programa de Edificios Universitarios",
    "60": "Escuela Nacional de Estudios Superiores, Campus León, Guanajuato",
    "61": "Departamento de Archivo General",
    "62": "Departamento de Correspondencia",
    "63": "Departamento de Jefe de Servicio",
    "64": "Departamento de Prevención y Combate de Siniestros",
    "65": "Departamento de Transportes",
    "66": "Departamento de Vigilancia 1er. Turno Nocturno",
    "67": "Departamento de Vigilancia 2do. Turno Nocturno",
    "68": "Departamento de Vigilancia Turno Matutino",
    "69": "Departamento de Vigilancia Turno Vespertino",
    "70": "Departamento de Vigilancia 5º Turno Especial",
    "71": "Dirección de Sistemas",
    "72": "Dirección General de Relaciones Laborales",
    "73": "Dirección de Teatro",
    "74": "Dirección General de Actividades Cinematográficas",
    "75": "Dirección General del Deporte Universitario",
    "76": "Dirección General de Administración Escolar, C.U.",
    "77": "Dirección General de Administración Escolar, Local de Registro",
    "78": "Dirección General de Administración Escolar, Sur",
    "79": "Dirección General de Artes Visuales (MUAC)",
    "80": "Dirección General de Asuntos del Personal Académico y Defensoría",
    "81": "Dirección General de Asuntos Jurídicos",
    "82": "Dirección General de Atención a la Comunidad",
    "83": "Dirección General de Bibliotecas",
    "84": "Dirección General de Comunicación Social",
    "85": "Dirección General de Control Presupuestal",
    "86": "Dirección General de Divulgación de la Ciencia \"UNIVERSUM\"",
    "87": "Coordinación de Estudios de Posgrado",
    "88": "Dirección General de Finanzas",
    "89": "Dirección General de Incorporación y Revalidación de Estudios",
    "90": "Dirección General de la Escuela Nacional Preparatoria",
    "91": "Dirección General de la Escuela Nacional del Colegio de Ciencias y Humanidades",
    "92": "Sistemas, Capacitación y Evaluación de la DGPE",
    "93": "Dirección General de Obras y Conservación, Of. Centrales",
    "94": "Dirección General de Orientación y Atención Educativa",
    "95": "Dirección General de Patrimonio Universitario",
    "96": "Dirección General de Personal",
    "97": "Dirección General de Planeación, Evaluación y Simplificación de la Gestión Institucional",
    "98": "Dirección General de Presupuesto",
    "99": "Dirección General de Proveeduría",
    "100": "Dirección General de Publicaciones y Fomento Editorial",
    "101": "Dirección General de Radio UNAM",
    "102": "Dirección General de Cómputo y Tecnologías de Información y Comunicación",
    "103": "Dirección General de Atención a la Salud",
    "104": "Dirección General de Televisión Universitaria",
    "105": "División de Educación Continua de la Facultad de Contaduría y Administración",
    "106": "División de Educación Continua de la Facultad de Ingeniería, Palacio de Minería",
    "107": "División de Educación Continua de la Facultad de Medicina, Palacio de Medicina",
    "108": "Secretaría de Posgrado e Investigación de la Facultad de Ingeniería",
    "109": "Facultad de Artes y Diseño, Academia de San Carlos",
    "110": "Facultad de Artes y Diseño, Xochimilco",
    "111": "Facultad Nacional de Enfermería y Obstetricia",
    "112": "Facultad de Estudios Superiores Aragón",
    "113": "Facultad de Música",
    "114": "Escuela Nacional de Trabajo Social",
    "115": "Escuela Nacional Preparatoria Plantel 1 \"Gabino Barreda\"",
    "116": "Escuela Nacional Preparatoria Plantel 2 \"Erasmo Castellanos Quinto\"",
    "117": "Escuela Nacional Preparatoria Plantel 3 \"Justo Sierra\"",
    "118": "Escuela Nacional Preparatoria Plantel 4 \"Vidal Castañeda y Nájera\"",
    "119": "Escuela Nacional Preparatoria Plantel 5 \"José Vasconcelos\"",
    "120": "Escuela Nacional Preparatoria Plantel 6 \"Antonio Caso\"",
    "121": "Escuela Nacional Preparatoria Plantel 7 \"Ezequiel A. Chávez\"",
    "122": "Escuela Nacional Preparatoria Plantel 8 \"Miguel E. Schultz\"",
    "123": "Escuela Nacional Preparatoria Plantel 9 \"Pedro de Alba\"",
    "124": "Estación de Biología Tropical, \"Los Tuxtlas\", Tuxtla, Veracruz",
    "125": "Estación de Investigación Experimental y Difusión, Chamela, Jalisco",
    "126": "Estación Marina, Ciudad del Carmen, Campeche",
    "127": "Unidad Académica, Mazatlán, Sinaloa",
    "128": "Estación Regional del Noroeste, Hermosillo, Sonora",
    "129": "Facultad de Arquitectura",
    "130": "Facultad de Ciencias",
    "131": "Facultad de Ciencias Políticas y Sociales",
    "132": "Facultad de Contaduría y Administración",
    "133": "Facultad de Derecho",
    "134": "Facultad de Economía",
    "135": "Facultad de Estudios Superiores Acatlán",
    "136": "Facultad de Estudios Superiores Iztacala",
    "137": "Facultad de Estudios Superiores Cuautitlán Campo 1",
    "138": "Facultad de Estudios Superiores Cuautitlán Campo 4",
    "139": "Facultad de Estudios Superiores Zaragoza Campo 1",
    "140": "Facultad de Estudios Superiores Zaragoza Campo 2",
    "141": "Facultad de Filosofía y Letras",
    "142": "Facultad de Ingeniería",
    "143": "Facultad de Medicina",
    "144": "Facultad de Medicina Veterinaria y Zootecnia",
    "145": "Facultad de Odontología",
    "146": "Facultad de Psicología",
    "147": "Facultad de Química, Edificios A, B, C, F, G y H",
    "148": "Facultad de Química, Edificios D y E",
    "149": "Gasolinería C.U.",
    "150": "Hemeroteca Nacional",
    "151": "Hospital General",
    "152": "Imprenta Universitaria",
    "153": "Instituto de Astronomía",
    "154": "Instituto de Biología",
    "155": "Instituto de Biotecnología, Cuernavaca, Morelos",
    "156": "Instituto de Ciencias del Mar y Limnología",
    "157": "Instituto de Ciencias Nucleares",
    "158": "Instituto de Ecología",
    "159": "Instituto de Física",
    "160": "Instituto de Fisiología Celular",
    "161": "Instituto de Geofísica",
    "162": "Instituto de Geografía",
    "163": "Instituto de Geología",
    "164": "Instituto de Ingeniería",
    "165": "Instituto de Investigaciones Antropológicas",
    "166": "Instituto de Investigaciones Antropológicas, Campamento Arqueológico, Mapachapa, Veracruz",
    "167": "Instituto de Investigaciones Biomédicas",
    "168": "Instituto de Investigaciones Económicas",
    "169": "Instituto de Investigaciones en Materiales",
    "170": "Instituto de Investigaciones Estéticas",
    "171": "Instituto de Investigaciones Filológicas",
    "172": "Instituto de Investigaciones Filosóficas",
    "173": "Instituto de Investigaciones Históricas",
    "174": "Instituto de Investigaciones Jurídicas",
    "175": "Instituto de Investigaciones Sociales",
    "176": "Instituto de Investigaciones en Matemáticas Aplicadas y Sistemas",
    "177": "Instituto de Matemáticas",
    "178": "Instituto de Matemáticas, Cuernavaca, Morelos",
    "179": "Instituto de Química",
    "180": "Departamento de Intendencia General",
    "181": "Jardín Botánico",
    "182": "Jardín de Niños C.U.",
    "183": "Museo de Geología",
    "184": "Museo de la Luz",
    "185": "Museo Universitario del Chopo",
    "186": "Observatorio Astronómico, San Pedro Mártir, Baja California",
    "187": "Observatorio Astronómico, Tonantzintla, Puebla",
    "188": "Oficinas Administrativas No. 2",
    "189": "Oficinas Sindicales y Clínica Dental (Centeno)",
    "190": "Orquesta Filarmónica de la UNAM",
    "191": "Centro de Investigaciones Multidisciplinarias sobre Chiapas y la Frontera Sur (CIMSUR), San Cristóbal de las Casas, Chiapas",
    "192": "Recintos Culturales",
    "193": "Subdirección de Capacitación y Desarrollo",
    "194": "Talleres de Zoquipa",
    "195": "Talleres de Conservación, Zona Cultural",
    "196": "Talleres de Conservación, C.U.",
    "197": "Escuela Nacional de Estudios Superiores, Morelia, Michoacán",
    "198": "Tienda UNAM 03 Metro C.U.",
    "199": "Unidad Académica, Puerto Morelos, Quintana Roo",
    "200": "Unidad de Informática, Planeación, Diseño y Protección Civil",
    "201": "Vigilancia de la Torre de Rectoría",
    "202": "Departamento de Viveros y Forestación",
    "203": "Unidad Administradora de la Torre de Ingeniería",
    "204": "Centro Peninsular en Humanidades y Ciencias Sociales, Mérida, Yucatán",
    "205": "Programa de Transporte Alternativo Universitario, BICIPUMA",
    "206": "Unidad Académica de Ciencias y Tecnología de la UNAM, Yucatán",
    "207": "Centro Cultural Universitario Tlatelolco",
    "208": "Dirección General de Cooperación e Internacionalización",
    "209": "Taller Coreográfico",
    "210": "Dirección de Danza",
    "211": "Centro de Ciencias de la Complejidad",
    "212": "Torre U.N.A.M. Tlatelolco",
    "213": "Estacionamientos Controlados Matutino",
    "214": "Unid. Farmacología, Clínica Cd. Nezahualcóyotl",
    "215": "Oficina de Abogacía General y Legislación Universitaria",
    "216": "Estacionamientos Controlados Vespertino",
    "217": "Clínica Odontológica Naucalpan",
    "218": "Estacionamientos Controlados 5º Turno",
    "219": "Escuela Nacional de Estudios Superiores, Campus Mérida, Yucatán",
    "220": "Escuela Nacional de Ciencias de la Tierra (ENCiT)",
    "221": "Museo de la Luz, Mérida",
    "222": "Facultad de Estudios Superiores Zaragoza C-III, Tlaxcala",
    "223": "Escuela Nacional de Ciencias Forenses",
    "224": "Escuela Nacional de Estudios Superiores Juriquilla, Querétaro",
    "225": "Unidad Académica de Estudios Regionales UNAM-Jiquilpan",
    "226": "Unidad de Extensión Universitaria UNAM-San Miguel de Allende",
}


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


@lru_cache(maxsize=1)
def catalogo_dependencias() -> dict[str, str]:
    """
    Retorna el catálogo estático consolidado.
    """
    return CATALOGO


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
