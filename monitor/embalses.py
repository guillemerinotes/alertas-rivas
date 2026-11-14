"""
RIV-Alert · Embalses aguas arriba de Rivas (datos de embalses.net).

embalses.net NO es una fuente oficial: recopila datos del MITECO (boletín semanal) y de los
SAIH de las confederaciones (tiempo real, "no homogeneizado ni confirmado", según la propia web).
Aquí solo se muestran como información, sin generar alertas.

Se leen solo los embalses cuyas aguas pueden llegar a Rivas:
  - Manzanares: Navacerrada, Santillana y El Pardo (el último antes de Madrid y Rivas).
  - Jarama (con Lozoya y Guadalix): El Vado, Pinilla, Riosequillo, Puentes Viejas, El Villar, El Atazar, Pedrezuela.
  - Henares (llega al Jarama aguas arriba de Rivas): Beleña, Pozo de los Ramos, Alcorlo, Pálmaces.
Para no cargar la web, se consulta como mucho una vez por hora.
"""
from __future__ import annotations

import html as _html
import re
import time
from datetime import datetime

BASE = "https://www.embalses.net/"
CUENCA_URL = BASE + "cuenca-3-tajo.html"
CADA_SEG = 3600

# (id en embalses.net, slug, nombre, río, tramo)
EMBALSES = [
    (1026, "navacerrada", "Navacerrada", "Navacerrada → Manzanares", "manzanares"),
    (1013, "santillana", "Santillana", "Manzanares", "manzanares"),
    (1045, "el-pardo", "El Pardo", "Manzanares", "manzanares"),
    (1203, "el-vado", "El Vado", "Jarama", "jarama"),
    (1057, "pinilla", "Pinilla", "Lozoya → Jarama", "jarama"),
    (1072, "riosequillo", "Riosequillo", "Lozoya → Jarama", "jarama"),
    (1067, "puentes-viejas", "Puentes Viejas", "Lozoya → Jarama", "jarama"),
    (1219, "el-villar", "El Villar", "Lozoya → Jarama", "jarama"),
    (908, "el-atazar", "El Atazar", "Lozoya → Jarama", "jarama"),
    (1046, "pedrezuela", "Pedrezuela", "Guadalix → Jarama", "jarama"),
    (920, "belena", "Beleña", "Sorbe → Henares", "henares"),
    (1065, "pozo-de-los-ramos", "Pozo de los Ramos", "Sorbe → Henares", "henares"),
    (887, "alcorlo", "Alcorlo", "Bornova → Henares", "henares"),
    (1043, "palmaces", "Pálmaces", "Cañamares → Henares", "henares"),
]


def url(id_: int, slug: str) -> str:
    return f"{BASE}pantano-{id_}-{slug}.html"


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace("%", "").replace("\xa0", "").strip()
    if not s or s in ("-", "&nbsp;"):
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _texto(fragmento: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", " ", fragmento)).strip()


def _seccion(h: str, marca: str) -> str:
    i = h.find(marca)
    if i < 0:
        return ""
    j = h.find("SeccionCentral_Titulo", i + len(marca))
    return h[i: j if j > 0 else i + 8000]


def _filas(seccion: str) -> list[list[str]]:
    filas = []
    for tr in re.findall(r'<tr class="ResultadoCampo">(.*?)</tr>', seccion, re.S):
        celdas = [re.sub(r"\s+", " ", _texto(td)) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        filas.append(celdas)
    return filas


def _fecha(s: str) -> str | None:
    for f in ("%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), f).isoformat()
        except ValueError:
            pass
    return None


def parsear(h: str) -> dict:
    """Extrae de la ficha de un embalse: dato semanal, tiempo real y caudal desembalsado."""
    d: dict = {}
    m = re.search(r"Agua embalsada \((\d{2}-\d{2}-\d{4})\):.*?<div class=\"Resultado\">(.*?)</div>.*?"
                  r"<div class=\"Resultado\">(.*?)</div>", h, re.S)
    if m:
        d["semana_fecha"] = _fecha(m.group(1))
        d["semana_hm3"] = _num(_texto(m.group(2)))
        d["semana_pct"] = _num(_texto(m.group(3)))
    m = re.search(r"Capacidad:</div>\s*<div class=\"Resultado\">(.*?)</div>", h, re.S)
    if m:
        d["capacidad"] = _num(_texto(m.group(1)))
    m = re.search(r"Variaci[oó]n semana Anterior:</div>\s*<div class=\"Resultado\">(.*?)</div>", h, re.S)
    if m:
        d["semana_var_hm3"] = _num(_texto(m.group(1)))

    tr = _filas(_seccion(h, "(Tiempo Real)"))
    if tr and len(tr[0]) >= 3:
        d["tr_fecha"] = _fecha(tr[0][0])
        d["tr_hm3"] = _num(tr[0][1])
        d["tr_pct"] = _num(tr[0][2])

    ds = _filas(_seccion(h, "(Caudal desembalsado)"))
    serie = [(_fecha(f[0]), _num(f[1])) for f in ds if len(f) >= 2 and _num(f[1]) is not None]
    if serie:
        d["desembalse_fecha"], d["desembalse"] = serie[0]
        # Tendencia frente al dato más antiguo de la tabla (suele ser ~24-36 h antes)
        antiguo = serie[-1][1]
        if len(serie) > 1 and antiguo is not None:
            dif = d["desembalse"] - antiguo
            d["desembalse_antes"] = antiguo
            d["desembalse_tend"] = "sube" if dif > max(0.5, 0.2 * antiguo) else "baja" if dif < -max(0.5, 0.2 * antiguo) else "estable"
    return d


def descargar(http_get, previo: dict | None = None, ahora_ts: float | None = None) -> dict:
    """Devuelve {"t": timestamp, "embalses": [...]}. Reutiliza los datos si tienen menos de una hora."""
    ahora_ts = ahora_ts or time.time()
    if previo and previo.get("embalses") and ahora_ts - previo.get("t", 0) < CADA_SEG:
        return previo
    lista, errores = [], 0
    for id_, slug, nombre, rio, tramo in EMBALSES:
        e = {"nombre": nombre, "rio": rio, "tramo": tramo, "url": url(id_, slug)}
        try:
            e.update(parsear(http_get(e["url"]).decode("utf-8", "replace")))
        except Exception as ex:  # noqa: BLE001 - un embalse caído no tumba los demás
            errores += 1
            e["error"] = type(ex).__name__
        lista.append(e)
        time.sleep(0.5)
    if errores == len(EMBALSES):
        raise RuntimeError("no se pudo leer ningún embalse")
    return {"t": ahora_ts, "embalses": lista, "fuente": "embalses.net", "cuenca_url": CUENCA_URL}


# ---------------------------------------------------------------------------
# Avisos informativos (criterio propio de RIV-Alert, NO oficial).
# Umbrales sacados de las crecidas de marzo de 2025 y febrero de 2026.
# Se avisa al pasar el umbral y otra vez cuando vuelve a bajar (con margen).
# ---------------------------------------------------------------------------
SUMAS = [
    # clave, texto, embalses que suman, umbral m³/s
    ("pardo10", "El Pardo (Manzanares)", ["El Pardo"], 10.0),
    ("pardo30", "El Pardo (Manzanares)", ["El Pardo"], 30.0),
    ("jarama50", "Jarama (El Vado + El Atazar + Pedrezuela)", ["El Vado", "El Atazar", "Pedrezuela"], 50.0),
    ("henares30", "Henares (Beleña + Alcorlo + Pálmaces)", ["Beleña", "Alcorlo", "Pálmaces"], 30.0),
]
LLENO = 90.0
MARGEN = 0.8   # para dar por terminado: bajar del 80 % del umbral (caudal) o 2 puntos (llenado)
PIE = ("Criterio propio de RIV-Alert (no oficial), con datos de embalses.net. "
       "Lo que manda es el nivel de los ríos y los avisos oficiales de AEMET y la Confederación.")


def _f(x):
    return f"{x:.1f}".replace(".", ",")


def _msg(titulo: str, cuerpo: str, fin: bool) -> dict:
    return {"title": f"RIV-Alert · EMBALSES · {titulo}",
            "message": cuerpo + "\n\n" + PIE + "\n\nRIV-Alert · aviso interno PC Rivas (no oficial). Confirma por canales oficiales.",
            "priority": 2 if fin else 3,
            "tags": ["droplet", "nivel-info", "evento-embalse"]}


def evaluar(datos: dict, flags: dict, aviso_lluvia: bool) -> tuple[dict, list[dict]]:
    """Devuelve (flags nuevos, mensajes). flags guarda qué umbrales están superados."""
    flags = dict(flags or {})
    msgs: list[dict] = []
    por_nombre = {e["nombre"]: e for e in (datos or {}).get("embalses", [])}
    if not por_nombre:
        return flags, msgs

    for clave, texto, nombres, umbral in SUMAS:
        vals = [por_nombre.get(n, {}).get("desembalse") for n in nombres]
        if all(v is None for v in vals):
            continue
        total = sum(v for v in vals if v is not None)
        detalle = ", ".join(f"{n} {_f(v)}" for n, v in zip(nombres, vals) if v is not None) if len(nombres) > 1 else ""
        activo = flags.get(clave, False)
        if not activo and total > umbral:
            flags[clave] = True
            msgs.append(_msg(f"{texto} suelta {_f(total)} m³/s",
                             f"{texto}: caudal desembalsado {_f(total)} m³/s, por encima de {_f(umbral)} m³/s."
                             + (f"\nDetalle (m³/s): {detalle}." if detalle else "")
                             + "\nPuede subir el río aguas abajo hacia Rivas: vigila la tarjeta de Ríos.", False))
        elif activo and total < umbral * MARGEN:
            flags[clave] = False
            msgs.append(_msg(f"{texto} baja a {_f(total)} m³/s",
                             f"{texto}: el caudal desembalsado ha bajado a {_f(total)} m³/s (umbral {_f(umbral)} m³/s).", True))

    for nombre, e in por_nombre.items():
        pct = e.get("tr_pct") if e.get("tr_pct") is not None else e.get("semana_pct")
        if pct is None:
            continue
        clave = "lleno:" + nombre
        activo = flags.get(clave, False)
        if not activo and pct >= LLENO and aviso_lluvia:
            flags[clave] = True
            msgs.append(_msg(f"{nombre} al {_f(pct)} % con aviso de lluvia",
                             f"El embalse de {nombre} ({e.get('rio', '')}) está al {_f(pct)} % y AEMET tiene aviso por lluvia o tormenta "
                             "en la zona de Rivas. Tiene poco margen para retener agua: puede tener que soltar más.", False))
        elif activo and (pct < LLENO - 2 or not aviso_lluvia):
            flags[clave] = False
            msgs.append(_msg(f"{nombre} sin riesgo de llenado",
                             f"{nombre}: {_f(pct)} %{' y ya no hay aviso de lluvia' if not aviso_lluvia else ''}.", True))
    return flags, msgs
