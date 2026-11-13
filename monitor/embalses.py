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
