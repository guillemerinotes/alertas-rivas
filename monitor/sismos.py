"""
RIV-Alert · Terremotos (Instituto Geográfico Nacional, feed GeoRSS de los últimos 10 días).

El IGN no asigna colores a los terremotos. El nivel lo calcula RIV-Alert según magnitud y distancia a Rivas
(criterio propio, NO oficial, ajustable en NIVELES_SISMO).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from comun import mensaje

FEEDS = ["https://www.ign.es/ign/RssTools/sismologia.xml", "http://www.ign.es/ign/RssTools/sismologia.xml"]
RIVAS = (40.3283, -3.5158)
GEO = "{http://www.w3.org/2003/01/geo/wgs84_pos#}"

# (distancia máxima km, magnitud mínima amarillo, naranja, rojo)
NIVELES_SISMO = [
    (50, 2.5, 3.5, 4.5),
    (150, 3.5, 4.5, 5.5),
    (300, 5.0, 6.0, None),
]


def distancia_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def nivel_sismo(mag: float, dist: float) -> int:
    for dmax, am, na, ro in NIVELES_SISMO:
        if dist <= dmax:
            if ro is not None and mag >= ro:
                return 3
            if mag >= na:
                return 2
            if mag >= am:
                return 1
            return 0
    return 0


def descargar(http_get) -> bytes:
    err = None
    for u in FEEDS:
        try:
            return http_get(u)
        except Exception as e:  # noqa: BLE001
            err = e
    raise err


def parsear(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for it in root.iter("item"):
        desc = (it.findtext("description") or "").strip()
        titulo = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        lat, lon = it.findtext(f"{GEO}lat"), it.findtext(f"{GEO}long")
        if not (lat and lon):
            m = re.search(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", desc)
            if m:
                lat, lon = m.group(1), m.group(2)
        m = re.search(r"magnitud\s+(\d+(?:[.,]\d+)?)", desc + " " + titulo, re.I)
        if not (lat and lon and m):
            continue
        lugar = re.search(r"magnitud\s+[\d.,]+\s+en\s+(.+?)\s+en la fecha", desc, re.I)
        fecha = re.search(r"en la fecha\s+([\d/]+\s+[\d:]+)", desc, re.I)
        evid = re.search(r"evid=([\w-]+)", link)
        out.append({
            "id": evid.group(1) if evid else (link or titulo),
            "lat": float(lat), "lon": float(lon),
            "mag": float(m.group(1).replace(",", ".")),
            "lugar": lugar.group(1).strip() if lugar else "",
            "fecha": fecha.group(1) if fecha else (it.findtext("pubDate") or ""),
            "link": link,
        })
    return out


def evaluar(xml: bytes, prev: dict, ahora) -> tuple[dict, list[dict]]:
    estado, msgs = {}, []
    for s in parsear(xml):
        dist = distancia_km(RIVAS, (s["lat"], s["lon"]))
        n = nivel_sismo(s["mag"], dist)
        if n == 0:
            continue
        s.update({"dist": round(dist, 1), "nivel": n})
        estado[s["id"]] = s
        if s["id"] in prev:
            continue
        cuerpo = (f"Magnitud {s['mag']} · {s['lugar'] or 'lugar sin indicar'}\n"
                  f"A {dist:.0f} km de Rivas · {s['fecha']} (hora oficial)\n"
                  f"Fuente: IGN. El nivel por magnitud y distancia es un criterio de RIV-Alert, no oficial.\n{s['link']}")
        msgs.append(mensaje(n, f"Terremoto M{s['mag']} a {dist:.0f} km", cuerpo, extra_tags=["evento-sismo"]))
    return estado, msgs
