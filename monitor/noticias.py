"""
RIV-Alert · Noticias de medios sobre emergencias en Rivas (Google News RSS).

NO es una fuente oficial: cada notificación indica el medio y su web. Sirve para enterarse de lo que se publica
(activaciones, cortes, desalojos...) y contrastarlo con los canales oficiales.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime

from comun import PANEL_URL

CONSULTA = ('"Rivas" (inundación OR desbordamiento OR crecida OR aviso OR alerta OR AEMET OR Manzanares OR Jarama '
            'OR incendio OR terremoto OR temporal OR borrasca OR tormenta OR nevada OR 112 OR desalojo OR emergencia)')
URL = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(CONSULTA + " when:2d")
       + "&hl=es&gl=ES&ceid=ES:es")
# El titular debe hablar de Rivas Y de alguna emergencia (evita noticias que solo mencionan Rivas)
RE_RIVAS = re.compile(r"\brivas\b", re.I)
RE_EMERG = re.compile(r"inund|desbord|crecid|aviso|alerta|aemet|lluvi|tormenta|temporal|borrasca|nieve|nevad|granizo|"
                      r"viento|racha|incendi|fuego|terremoto|se[ií]smo|sismo|manzanares|jarama|112|evacu|desaloj|"
                      r"emergencia|protecci[oó]n civil|bomberos|corte|cortad", re.I)
MAX_HORAS = 36


def descargar(http_get) -> bytes:
    return http_get(URL)


def parsear(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for it in root.iter("item"):
        titulo = html.unescape(it.findtext("title") or "").strip()
        src = it.find("source")
        medio = (src.text or "").strip() if src is not None else ""
        web = src.get("url", "") if src is not None else ""
        if medio and titulo.endswith(" - " + medio):
            titulo = titulo[: -len(" - " + medio)]
        try:
            fecha = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            fecha = None
        out.append({"id": (it.findtext("guid") or it.findtext("link") or titulo).strip(), "titulo": titulo,
                    "medio": medio, "web": web, "link": (it.findtext("link") or "").strip(),
                    "fecha": fecha.isoformat() if fecha else ""})
    return out


def relevante(n: dict) -> bool:
    return bool(RE_RIVAS.search(n["titulo"]) and RE_EMERG.search(n["titulo"]))


def evaluar(xml: bytes, prev: dict, ahora) -> tuple[dict, list[dict]]:
    vistas = dict(prev.get("vistas", {}))
    nuevas, recientes = [], []
    limite = ahora - timedelta(hours=MAX_HORAS)
    from datetime import datetime
    for n in parsear(xml):
        if not relevante(n) or not n["fecha"] or datetime.fromisoformat(n["fecha"]) < limite:
            continue
        recientes.append(n)
        if n["id"] not in vistas:
            nuevas.append(n)
            vistas[n["id"]] = n["fecha"]
    # olvidar las vistas de hace más de 3 días
    vistas = {k: v for k, v in vistas.items() if v and datetime.fromisoformat(v) > ahora - timedelta(days=3)}
    recientes.sort(key=lambda n: n["fecha"], reverse=True)
    estado = {"vistas": vistas, "recientes": recientes[:15]}
    msgs = []
    if nuevas:
        nuevas.sort(key=lambda n: n["fecha"], reverse=True)
        lineas = [f"• {n['titulo']}\n  Fuente: {n['medio'] or '?'} ({urllib.parse.urlparse(n['web']).netloc or n['web']})"
                  for n in nuevas[:8]]
        titulo = (f"RIV-Alert · NOTICIA (no oficial) · {nuevas[0]['medio']}: {nuevas[0]['titulo']}" if len(nuevas) == 1
                  else f"RIV-Alert · {len(nuevas)} NOTICIAS (no oficiales) sobre Rivas")
        msgs.append({
            "title": titulo[:250],
            "message": "\n".join(lineas) + "\n\nNoticias de medios de comunicación (vía Google News), NO son avisos oficiales. "
                                          "Contrástalo con AEMET, SAIH, 112 o el Ayuntamiento.",
            "priority": 3,
            "tags": ["newspaper", "nivel-info", "evento-noticia"],
            "click": PANEL_URL,
            **({"actions": [{"action": "view", "label": "Leer la noticia", "url": nuevas[0]["link"]}]} if len(nuevas) == 1 else {}),
        })
    return estado, msgs
