"""
Vigilante de avisos AEMET para la Comunidad de Madrid, el Corredor del Henares y Rivas-Vaciamadrid.

Se ejecuta cada pocos minutos en GitHub Actions:
  1. Descarga el estado completo de avisos de AEMET para la Comunidad de Madrid (CAP, sin clave).
  2. Clasifica cada aviso en tres niveles:
       - MADRID   -> zonas Sierra de Madrid y Sur, Vegas y Oeste
       - CORREDOR -> zona Metropolitana y Henares, sin confirmar en Rivas
       - RIVAS    -> zona Metropolitana y Henares y confirmado con la previsión horaria de AEMET
                     para Rivas (municipio 28123). Si no hay clave o datos, se trata como RIVAS
                     por seguridad ("sin confirmar").
  3. Compara con el estado anterior (state.json) y envía a ntfy:
       nuevo, sube de nivel, baja de nivel, entra en vigor, cancelado, cambio de confirmación en Rivas.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import rios

TZ = ZoneInfo("Europe/Madrid")
RSS_URL = "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAC72_RSS.xml"
AEMET_AVISOS_WEB = "https://www.aemet.es/es/eltiempo/prediccion/avisos?k=mad"
RIVAS_MUNICIPIO = "28123"
OPENDATA_HORARIA = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/horaria/" + RIVAS_MUNICIPIO
UA = {"User-Agent": "alertas-rivas/1.0 (+https://github.com/guillemerinotes/alertas-rivas)"}

ZONA_CORREDOR = "722802"
ZONAS = {
    "722801": "Sierra de Madrid",
    "722802": "Metropolitana y Henares",
    "722803": "Sur, Vegas y Oeste",
}
NIVELES = {"amarillo": 1, "naranja": 2, "rojo": 3}
NIVEL_EMOJI = {"amarillo": "yellow_circle", "naranja": "orange_circle", "rojo": "red_circle"}
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"


# ---------------------------------------------------------------- descarga

def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def descargar_caps() -> list[bytes]:
    """Devuelve el contenido XML de todos los avisos CAP activos de la Comunidad de Madrid."""
    rss = ET.fromstring(http_get(RSS_URL))
    links = [(i.findtext("link") or "").strip() for i in rss.iter("item")]
    tar_links = [l for l in links if l.endswith(".tar.gz")]
    if tar_links:
        data = http_get(tar_links[0])
        caps = []
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                if m.isfile() and m.name.lower().endswith(".xml"):
                    f = tar.extractfile(m)
                    if f:
                        caps.append(f.read())
        return caps
    # Plan B: descargar cada CAP por separado
    return [http_get(l) for l in links if l.endswith(".xml")]


# ---------------------------------------------------------------- parseo CAP

def _param(info: ET.Element, name: str) -> str:
    for p in info.findall("cap:parameter", CAP_NS):
        if (p.findtext("cap:valueName", "", CAP_NS) or "").strip() == name:
            return (p.findtext("cap:value", "", CAP_NS) or "").strip()
    return ""


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip())
    except ValueError:
        return None


def parse_cap(xml: bytes) -> list[dict]:
    """Un CAP de AEMET -> lista de avisos (uno por zona) con la info en español."""
    root = ET.fromstring(xml)
    msg_type = root.findtext("cap:msgType", "", CAP_NS).strip()
    infos = root.findall("cap:info", CAP_NS)
    info = next((i for i in infos if (i.findtext("cap:language", "", CAP_NS) or "").lower().startswith("es")),
                infos[0] if infos else None)
    if info is None:
        return []
    nivel = _param(info, "AEMET-Meteoalerta nivel").lower()
    parametro = _param(info, "AEMET-Meteoalerta parametro")  # p.ej. "TA;Temperatura máxima;36 ºC"
    partes = [p.strip() for p in parametro.split(";")]
    fen_cod = partes[0] if partes and partes[0] else ""
    fen_nombre = partes[1] if len(partes) > 1 else (info.findtext("cap:event", "", CAP_NS) or "").strip()
    valor = partes[2] if len(partes) > 2 else ""
    if not fen_cod:
        fen_cod = re.sub(r"\W+", "_", fen_nombre.lower())[:30] or "desconocido"
    onset = _dt(info.findtext("cap:onset", None, CAP_NS)) or _dt(info.findtext("cap:effective", None, CAP_NS))
    expires = _dt(info.findtext("cap:expires", None, CAP_NS))
    out = []
    for area in info.findall("cap:area", CAP_NS):
        zona = ""
        for g in area.findall("cap:geocode", CAP_NS):
            if "zona" in (g.findtext("cap:valueName", "", CAP_NS) or "").lower():
                zona = (g.findtext("cap:value", "", CAP_NS) or "").strip()
        desc = (area.findtext("cap:areaDesc", "", CAP_NS) or "").strip()
        if not zona:
            zona = next((k for k, v in ZONAS.items() if v.lower() == desc.lower()), "")
        if zona not in ZONAS:
            continue
        out.append({
            "zona": zona,
            "zona_nombre": ZONAS[zona],
            "nivel": nivel,
            "msg_type": msg_type,
            "fen_cod": fen_cod,
            "fenomeno": fen_nombre,
            "valor": valor,
            "probabilidad": _param(info, "AEMET-Meteoalerta probabilidad"),
            "headline": (info.findtext("cap:headline", "", CAP_NS) or "").strip(),
            "descripcion": (info.findtext("cap:description", "", CAP_NS) or "").strip(),
            "onset": onset.isoformat() if onset else "",
            "expires": expires.isoformat() if expires else "",
        })
    return out


def clave_aviso(a: dict) -> str:
    """Mismo fenómeno, misma zona y mismo día de inicio = mismo aviso (aunque AEMET lo actualice)."""
    dia = datetime.fromisoformat(a["onset"]).astimezone(TZ).date().isoformat() if a["onset"] else "?"
    return f"{a['zona']}|{a['fen_cod']}|{dia}"


def avisos_activos(caps: list[bytes], ahora: datetime) -> dict[str, dict]:
    res: dict[str, dict] = {}
    for xml in caps:
        try:
            lista = parse_cap(xml)
        except ET.ParseError:
            continue
        for a in lista:
            if a["msg_type"].lower() == "cancel" or a["nivel"] not in NIVELES:
                continue
            if a["expires"] and datetime.fromisoformat(a["expires"]) <= ahora:
                continue
            k = clave_aviso(a)
            # si hay varios tramos del mismo aviso ese día, nos quedamos con el nivel más alto
            # y con la ventana completa
            if k in res:
                prev = res[k]
                if NIVELES[a["nivel"]] > NIVELES[prev["nivel"]]:
                    prev.update({x: a[x] for x in ("nivel", "valor", "headline", "descripcion", "probabilidad")})
                prev["onset"] = min(prev["onset"], a["onset"]) if prev["onset"] and a["onset"] else prev["onset"] or a["onset"]
                prev["expires"] = max(prev["expires"], a["expires"])
            else:
                res[k] = a
    return res


# ---------------------------------------------------------------- confirmación en Rivas

def _num(s) -> float | None:
    if s is None:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(s))
    return float(m.group().replace(",", ".")) if m else None


def descargar_prevision_rivas(api_key: str) -> list[dict] | None:
    """Previsión horaria de AEMET OpenData para Rivas. Devuelve lista de horas o None si falla."""
    try:
        meta = json.loads(http_get(OPENDATA_HORARIA, headers={"api_key": api_key}))
        url = meta.get("datos")
        if not url:
            return None
        raw = http_get(url)
        try:
            datos = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            datos = json.loads(raw.decode("latin-1"))
        return horas_desde_prevision(datos)
    except Exception as e:  # noqa: BLE001 - la confirmación nunca debe tumbar el vigilante
        print(f"[aviso] No se pudo descargar la previsión de Rivas: {e}", file=sys.stderr)
        return None


def horas_desde_prevision(datos) -> list[dict]:
    """Aplana la previsión horaria de AEMET a una lista {hora, lluvia, racha, nieve, temp, prob_tormenta}."""
    horas: dict[datetime, dict] = {}
    tormentas: list[tuple[datetime, datetime, float]] = []
    pred = datos[0]["prediccion"]["dia"] if isinstance(datos, list) else datos["prediccion"]["dia"]
    for dia in pred:
        fecha = datetime.fromisoformat(dia["fecha"][:10]).replace(tzinfo=TZ)

        def h(periodo: str) -> datetime:
            return fecha + timedelta(hours=int(periodo[:2]))

        def slot(t: datetime) -> dict:
            return horas.setdefault(t, {"hora": t})

        for x in dia.get("precipitacion", []):
            slot(h(x["periodo"]))["lluvia"] = 0.0 if str(x.get("value")).lower() == "ip" else (_num(x.get("value")) or 0.0)
        for x in dia.get("nieve", []):
            slot(h(x["periodo"]))["nieve"] = 0.0 if str(x.get("value")).lower() == "ip" else (_num(x.get("value")) or 0.0)
        for x in dia.get("temperatura", []):
            slot(h(x["periodo"]))["temp"] = _num(x.get("value"))
        for x in dia.get("vientoAndRachaMax", []):
            if "value" in x and "periodo" in x:  # las entradas con 'value' son las rachas máximas
                v = _num(x.get("value"))
                if v is not None:
                    slot(h(x["periodo"]))["racha"] = v
        for x in dia.get("probTormenta", []):
            p = str(x.get("periodo", ""))
            if len(p) == 4:
                ini = h(p[:2])
                fin = fecha + timedelta(hours=int(p[2:])) if int(p[2:]) > int(p[:2]) else fecha + timedelta(days=1, hours=int(p[2:]))
                tormentas.append((ini, fin, _num(x.get("value")) or 0.0))
    lista = sorted(horas.values(), key=lambda d: d["hora"])
    for d in lista:
        d["prob_tormenta"] = max((p for ini, fin, p in tormentas if ini <= d["hora"] < fin), default=0.0)
    return lista


def confirmar_en_rivas(aviso: dict, horas: list[dict] | None) -> tuple[str, str]:
    """
    Devuelve (estado, motivo) con estado:
      'si'          -> la previsión de Rivas muestra el fenómeno
      'no'          -> la previsión de Rivas NO lo muestra (queda como Corredor)
      'desconocido' -> no hay datos para comprobarlo (se trata como Rivas por seguridad)
    """
    if NIVELES.get(aviso["nivel"], 0) >= NIVELES["naranja"]:
        return "si", f"aviso {aviso['nivel']} en la zona: se trata siempre como alerta de Rivas"
    if horas is None:
        return "desconocido", "sin previsión de Rivas (falta la clave de AEMET o no respondió)"
    ini = datetime.fromisoformat(aviso["onset"]) if aviso["onset"] else None
    fin = datetime.fromisoformat(aviso["expires"]) if aviso["expires"] else None
    ventana = [d for d in horas if (ini is None or d["hora"] >= ini - timedelta(hours=1))
               and (fin is None or d["hora"] <= fin)]
    if not ventana:
        return "desconocido", "la previsión horaria de Rivas aún no llega a esas horas"

    fen = (aviso["fenomeno"] + " " + aviso["fen_cod"]).lower()
    umbral = _num(aviso["valor"])

    if "racha" in fen or "viento" in fen:
        m = max((d.get("racha") or 0) for d in ventana)
        u = (umbral or 70) * 0.65
        return ("si" if m >= u else "no"), f"racha máx. prevista en Rivas {m:.0f} km/h"
    if "tormenta" in fen:
        m = max((d.get("prob_tormenta") or 0) for d in ventana)
        return ("si" if m >= 20 else "no"), f"prob. de tormenta en Rivas {m:.0f} %"
    if "nieve" in fen or "nevada" in fen:
        m = sum((d.get("nieve") or 0) for d in ventana)
        return ("si" if m > 0 else "no"), f"nieve prevista en Rivas {m:.1f} mm"
    if "lluvia" in fen or "precipit" in fen:
        total = sum((d.get("lluvia") or 0) for d in ventana)
        m1 = max((d.get("lluvia") or 0) for d in ventana)
        u = umbral or 15
        texto = (aviso["fenomeno"] + " " + aviso["valor"]).lower()
        if "una hora" in texto or "1 hora" in texto or "1h" in texto or aviso["fen_cod"].upper() == "P1":
            ok = m1 >= u * 0.3
        else:
            ok = total >= u * 0.35
        return ("si" if ok else "no"), f"lluvia prevista en Rivas {total:.1f} mm (máx. {m1:.1f} mm/h)"
    if "máxima" in fen or "maxima" in fen:
        m = max((d.get("temp") or -99) for d in ventana)
        u = (umbral or 36) - 1
        return ("si" if m >= u else "no"), f"temp. máx. prevista en Rivas {m:.0f} ºC"
    if "mínima" in fen or "minima" in fen:
        m = min((d.get("temp") if d.get("temp") is not None else 99) for d in ventana)
        u = (umbral if umbral is not None else -4) + 1
        return ("si" if m <= u else "no"), f"temp. mín. prevista en Rivas {m:.0f} ºC"
    # niebla, polvo, deshielo, etc.: la previsión municipal no lo permite comprobar
    return "desconocido", "este fenómeno no se puede comprobar con la previsión municipal"


def nivel_alerta(aviso: dict) -> str:
    if aviso["zona"] != ZONA_CORREDOR:
        return "madrid"
    return "corredor" if aviso.get("rivas") == "no" else "rivas"


# ---------------------------------------------------------------- eventos

def calcular_eventos(prev: dict, act: dict, ahora: datetime) -> list[dict]:
    eventos = []
    for k, a in act.items():
        p = prev.get(k)
        en_vigor = bool(a["onset"]) and datetime.fromisoformat(a["onset"]) <= ahora
        a["en_vigor_notificado"] = p.get("en_vigor_notificado", False) if p else False
        if p is None:
            eventos.append({"tipo": "nuevo", "aviso": a})
            if en_vigor:
                a["en_vigor_notificado"] = True
            continue
        dn = NIVELES[a["nivel"]] - NIVELES[p["nivel"]]
        if dn > 0:
            eventos.append({"tipo": "sube", "aviso": a, "antes": p["nivel"]})
        elif dn < 0:
            eventos.append({"tipo": "baja", "aviso": a, "antes": p["nivel"]})
        elif a["zona"] == ZONA_CORREDOR and nivel_alerta(a) != nivel_alerta(p):
            eventos.append({"tipo": "confirmacion", "aviso": a, "antes_nivel_alerta": nivel_alerta(p)})
        if en_vigor and not a["en_vigor_notificado"]:
            eventos.append({"tipo": "en_vigor", "aviso": a})
            a["en_vigor_notificado"] = True
    for k, p in prev.items():
        if k in act:
            continue
        exp = datetime.fromisoformat(p["expires"]) if p.get("expires") else None
        if exp is None or exp > ahora:
            eventos.append({"tipo": "cancelado", "aviso": p})
        # si simplemente ha caducado, no molestamos
    return eventos


# ---------------------------------------------------------------- mensajes

def _hora(iso: str) -> str:
    if not iso:
        return "?"
    d = datetime.fromisoformat(iso).astimezone(TZ)
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    return f"{dias[d.weekday()]} {d:%d/%m %H:%M}"


def _cuando(a: dict, ahora: datetime) -> str:
    if not a["onset"]:
        return ""
    d = datetime.fromisoformat(a["onset"]).astimezone(TZ).date()
    hoy = ahora.astimezone(TZ).date()
    if d == hoy:
        return "HOY"
    if d == hoy + timedelta(days=1):
        return "MAÑANA"
    if d == hoy + timedelta(days=2):
        return "PASADO MAÑANA"
    return d.strftime("%d/%m")


def construir_mensaje(ev: dict, ahora: datetime) -> dict:
    a = ev["aviso"]
    nivel_al = nivel_alerta(a)
    nivel = a["nivel"].upper()
    fen = a["fenomeno"] or "Fenómeno adverso"
    cuando = _cuando(a, ahora)
    etiqueta = {"madrid": "MADRID", "corredor": "CORREDOR DEL HENARES", "rivas": "⚠️ RIVAS"}[nivel_al]
    t = ev["tipo"]
    if t == "nuevo":
        titulo = f"{etiqueta} · Aviso {nivel} · {fen} ({cuando})"
    elif t == "sube":
        titulo = f"{etiqueta} · SUBE a {nivel} · {fen} ({cuando})"
    elif t == "baja":
        titulo = f"{etiqueta} · Baja a {nivel} · {fen} ({cuando})"
    elif t == "en_vigor":
        titulo = f"{etiqueta} · EN VIGOR AHORA · {fen} {nivel}"
    elif t == "confirmacion":
        titulo = (f"⚠️ RIVAS · Confirmado en Rivas · {fen} {nivel}" if nivel_al == "rivas"
                  else f"CORREDOR · Ya no se prevé en Rivas · {fen} {nivel}")
    else:  # cancelado
        titulo = f"{etiqueta} · CANCELADO · {fen} ({cuando})"

    lineas = [f"Zona AEMET: {a['zona_nombre']}"]
    if a["valor"]:
        lineas.append(f"Valor: {a['valor']}")
    lineas.append(f"Desde {_hora(a['onset'])} hasta {_hora(a['expires'])}")
    if a.get("probabilidad"):
        lineas.append(f"Probabilidad: {a['probabilidad']}")
    if a["zona"] == ZONA_CORREDOR:
        estado = {"si": "confirmado en la previsión de Rivas", "no": "no se prevé en Rivas",
                  "desconocido": "sin confirmar en Rivas"}.get(a.get("rivas", ""), "")
        if estado:
            lineas.append(f"Rivas: {estado} ({a.get('rivas_motivo', '')})")
    if a.get("descripcion") and t != "cancelado":
        lineas.append(a["descripcion"])

    prioridad = {"madrid": 3, "corredor": 4, "rivas": 5}[nivel_al]
    if t == "cancelado":
        prioridad = min(prioridad, 3)
    if t == "baja":
        prioridad = max(prioridad - 1, 2)
    tags = [NIVEL_EMOJI.get(a["nivel"], "warning"), f"nivel-{nivel_al}", f"evento-{t}"]
    if t == "cancelado":
        tags[0] = "white_check_mark"
    return {
        "title": titulo,
        "message": "\n".join(lineas),
        "priority": prioridad,
        "tags": tags,
        "click": os.environ.get("PANEL_URL") or AEMET_AVISOS_WEB,
    }


def agrupar(mensajes: list[dict]) -> list[dict]:
    """Si en una misma comprobación hay varias novedades del mismo nivel, las junta en una sola notificación."""
    por_nivel: dict[str, list[dict]] = {}
    for m in mensajes:
        nivel = next((t[6:] for t in m["tags"] if t.startswith("nivel-")), "madrid")
        por_nivel.setdefault(nivel, []).append(m)
    res = []
    for nivel in ("madrid", "corredor", "rivas"):
        lista = por_nivel.get(nivel, [])
        if len(lista) <= 1:
            res.extend(lista)
            continue
        etiqueta = {"madrid": "MADRID", "corredor": "CORREDOR DEL HENARES", "rivas": "⚠️ RIVAS"}[nivel]
        cuerpo = "\n\n".join(f"• {m['title']}\n{m['message']}" for m in lista)
        if len(cuerpo) > 3800:
            cuerpo = cuerpo[:3800] + "\n…"
        prioridad = max(m["priority"] for m in lista)
        top = max(lista, key=lambda m: m["priority"])
        res.append({
            "title": f"{etiqueta} · {len(lista)} novedades (avisos y ríos)",
            "message": cuerpo,
            "priority": prioridad,
            "tags": [top["tags"][0], f"nivel-{nivel}", "evento-varios"],
            "click": top["click"],
        })
    return res


def enviar_ntfy(topic: str, msg: dict, server: str = "https://ntfy.sh") -> None:
    body = json.dumps({"topic": topic, **msg}).encode("utf-8")
    req = urllib.request.Request(server, data=body, method="POST",
                                 headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


# ---------------------------------------------------------------- principal

def cargar_estado() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"avisos": {}, "heartbeat": ""}


def guardar_estado(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def mensajes_de_prueba() -> list[dict]:
    base = {"click": AEMET_AVISOS_WEB}
    return [
        {**base, "title": "MADRID · PRUEBA · Aviso AMARILLO · Vientos", "priority": 3,
         "tags": ["yellow_circle", "nivel-madrid", "evento-prueba"],
         "message": "Esto es una prueba del nivel MADRID. No hay ningún aviso real."},
        {**base, "title": "CORREDOR DEL HENARES · PRUEBA · Aviso NARANJA · Lluvias", "priority": 4,
         "tags": ["orange_circle", "nivel-corredor", "evento-prueba"],
         "message": "Esto es una prueba del nivel CORREDOR. No hay ningún aviso real."},
        {**base, "title": "⚠️ RIVAS · PRUEBA · Aviso ROJO · Tormentas", "priority": 5,
         "tags": ["red_circle", "nivel-rivas", "evento-prueba"],
         "message": "Esto es una prueba de la ALERTA DE RIVAS. No hay ningún aviso real."},
    ]


def main() -> int:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("Falta el secreto NTFY_TOPIC", file=sys.stderr)
        return 1
    ahora = datetime.now(timezone.utc)

    if os.environ.get("MODO_PRUEBA") == "1":
        for m in mensajes_de_prueba():
            enviar_ntfy(topic, m)
        print("Enviadas 3 notificaciones de prueba.")
        return 0

    st = cargar_estado()
    caps = descargar_caps()
    act = avisos_activos(caps, ahora)

    prev = st.get("avisos", {})
    if any(a["zona"] == ZONA_CORREDOR for a in act.values()):
        key = os.environ.get("AEMET_API_KEY", "").strip()
        horas = descargar_prevision_rivas(key) if key else None
        for k, a in act.items():
            if a["zona"] == ZONA_CORREDOR:
                a["rivas"], a["rivas_motivo"] = confirmar_en_rivas(a, horas)
                # si esta vez no hay datos, mantenemos lo último que sabíamos (evita avisos en bucle)
                p = prev.get(k)
                if a["rivas"] == "desconocido" and p and p.get("rivas") in ("si", "no"):
                    a["rivas"], a["rivas_motivo"] = p["rivas"], p.get("rivas_motivo", "")

    eventos = calcular_eventos(prev, act, ahora)
    orden = {"madrid": 0, "corredor": 1, "rivas": 2}
    eventos.sort(key=lambda e: orden[nivel_alerta(e["aviso"])])
    mensajes = [construir_mensaje(ev, ahora) for ev in eventos]

    # --- Ríos (SAIH Tajo) ---
    try:
        st["rios"], msgs_rios = rios.evaluar(rios.descargar(http_get), st.get("rios", {}))
        if st.get("rios_fallos", 0) >= 3:
            msgs_rios.append({"title": "Alertas Rivas · SAIH Tajo vuelve a responder", "priority": 2,
                              "message": "Vuelvo a leer los niveles de los ríos con normalidad.",
                              "tags": ["white_check_mark", "nivel-madrid", "evento-sistema"], "click": rios.SAIH_WEB})
        st["rios_fallos"] = 0
        mensajes += msgs_rios
    except Exception as e:  # noqa: BLE001
        st["rios_fallos"] = st.get("rios_fallos", 0) + 1
        print(f"[aviso] SAIH Tajo no disponible: {e}", file=sys.stderr)
        if st["rios_fallos"] == 3:
            mensajes.append({"title": "Alertas Rivas · No puedo leer los ríos (SAIH Tajo)", "priority": 3,
                             "message": "Llevo 3 comprobaciones sin poder leer el SAIH Tajo. Los avisos de AEMET siguen "
                                        "funcionando, pero vigila los ríos a mano en saihtajo.chtajo.es.",
                             "tags": ["warning", "nivel-madrid", "evento-sistema"], "click": rios.SAIH_WEB})

    mensajes = agrupar(mensajes)
    fallos = 0
    for msg in mensajes:
        print(f"-> {msg['title']}")
        try:
            enviar_ntfy(topic, msg)
        except Exception as e:  # noqa: BLE001
            fallos += 1
            print(f"[error] ntfy: {e}", file=sys.stderr)

    st["avisos"] = act
    hb = st.get("heartbeat") or ""
    if not hb or datetime.fromisoformat(hb) < ahora - timedelta(days=20):
        st["heartbeat"] = ahora.isoformat()  # mantiene el repo "activo" para que GitHub no pare el cron
    guardar_estado(st)
    print(f"{len(act)} avisos activos, {len(mensajes)} notificaciones.")
    return 1 if fallos and fallos == len(mensajes) else 0


if __name__ == "__main__":
    sys.exit(main())
