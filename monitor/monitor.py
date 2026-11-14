"""
RIV-Alert · Vigilante de emergencias que pueden afectar a Rivas-Vaciamadrid.

Cada ejecución (cron-job.org la lanza cada 10 min en GitHub Actions):
  1. AEMET Meteoalerta: avisos de la zona Metropolitana y Henares (722802), la de Rivas. Todos los fenómenos.
  2. SAIH Tajo: ríos en Rivas y aguas arriba (rios.py).
  3. IGN: terremotos cerca de Rivas (sismos.py).
  4. AEMET: riesgo meteorológico de incendio forestal en Rivas (incendios.py).
El nivel de RIV-Alert es el color oficial: amarillo = notificación, naranja = alerta media, rojo = alerta máxima.
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

import comun
from comun import NIVELES, TZ, http_get, hora, cuando, mensaje

RSS_URL = "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAC72_RSS.xml"
OPENDATA_HORARIA = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/horaria/28123"
ZONA_RIVAS = "722802"
ZONA_NOMBRE = "Metropolitana y Henares"
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
PANEL_URL = comun.PANEL_URL

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"


# ======================================================================= AEMET avisos

def descargar_caps() -> list[bytes]:
    rss = ET.fromstring(http_get(RSS_URL))
    links = [(i.findtext("link") or "").strip() for i in rss.iter("item")]
    tar_links = [l for l in links if l.endswith(".tar.gz")]
    if tar_links:
        caps = []
        with tarfile.open(fileobj=io.BytesIO(http_get(tar_links[0])), mode="r:gz") as tar:
            for m in tar.getmembers():
                if m.isfile() and m.name.lower().endswith(".xml"):
                    f = tar.extractfile(m)
                    if f:
                        caps.append(f.read())
        return caps
    return [http_get(l) for l in links if l.endswith(".xml")]


def _param(info, name):
    for p in info.findall("cap:parameter", CAP_NS):
        if (p.findtext("cap:valueName", "", CAP_NS) or "").strip() == name:
            return (p.findtext("cap:value", "", CAP_NS) or "").strip()
    return ""


def _dt(s):
    try:
        return datetime.fromisoformat(s.strip()) if s else None
    except ValueError:
        return None


def parse_cap(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    msg_type = (root.findtext("cap:msgType", "", CAP_NS) or "").strip()
    infos = root.findall("cap:info", CAP_NS)
    info = next((i for i in infos if (i.findtext("cap:language", "", CAP_NS) or "").lower().startswith("es")),
                infos[0] if infos else None)
    if info is None:
        return []
    nivel = _param(info, "AEMET-Meteoalerta nivel").lower()
    partes = [p.strip() for p in _param(info, "AEMET-Meteoalerta parametro").split(";")]
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
        if not zona and desc.lower() == ZONA_NOMBRE.lower():
            zona = ZONA_RIVAS
        if zona != ZONA_RIVAS:
            continue
        out.append({
            "zona": zona, "zona_nombre": ZONA_NOMBRE, "nivel": nivel, "msg_type": msg_type,
            "fen_cod": fen_cod, "fenomeno": fen_nombre, "valor": valor,
            "probabilidad": _param(info, "AEMET-Meteoalerta probabilidad"),
            "descripcion": (info.findtext("cap:description", "", CAP_NS) or "").strip(),
            "onset": onset.isoformat() if onset else "", "expires": expires.isoformat() if expires else "",
        })
    return out


def clave_aviso(a: dict) -> str:
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
            if k in res:
                p = res[k]
                if NIVELES[a["nivel"]] > NIVELES[p["nivel"]]:
                    p.update({x: a[x] for x in ("nivel", "valor", "descripcion", "probabilidad")})
                p["onset"] = min(p["onset"], a["onset"]) if p["onset"] and a["onset"] else p["onset"] or a["onset"]
                p["expires"] = max(p["expires"], a["expires"])
            else:
                res[k] = a
    return res


# ======================================================================= previsión de Rivas (dato informativo)

def _num(s):
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(s)) if s is not None else None
    return float(m.group().replace(",", ".")) if m else None


PREV = {"fuente": None, "error": None}
OPENMETEO = ("https://api.open-meteo.com/v1/forecast?latitude=40.3283&longitude=-3.5158"
             "&hourly=temperature_2m,precipitation,snowfall,wind_gusts_10m,weather_code"
             "&timezone=Europe%2FMadrid&forecast_days=3&wind_speed_unit=kmh")


def prevision_openmeteo():
    """Respaldo sin clave (modelos meteorológicos vía Open-Meteo) si la de AEMET falla."""
    try:
        d = json.loads(http_get(OPENMETEO))["hourly"]
        out = []
        for i, t in enumerate(d["time"]):
            def v(k):
                x = d.get(k, [None] * (i + 1))[i]
                return float(x) if x is not None else None
            wc = v("weather_code") or 0
            out.append({"hora": datetime.fromisoformat(t).replace(tzinfo=TZ), "lluvia": v("precipitation"),
                        "nieve": v("snowfall"), "temp": v("temperature_2m"), "racha": v("wind_gusts_10m"),
                        "prob_tormenta": 100.0 if wc >= 95 else 0.0})
        PREV["fuente"] = "Open-Meteo (modelos, no oficial)"
        return out
    except Exception as e:  # noqa: BLE001
        PREV["error"] = (PREV["error"] or "") + f" · Open-Meteo: {e}"
        return None


def descargar_prevision_rivas(api_key: str):
    r = _prevision_aemet(api_key) if api_key else None
    if r:
        PREV["fuente"] = "AEMET (oficial)"
        return r
    if not api_key:
        PREV["error"] = "sin clave de AEMET"
    return prevision_openmeteo()


def _prevision_aemet(api_key: str):
    try:
        meta = json.loads(http_get(OPENDATA_HORARIA, headers={"api_key": api_key}))
        if not meta.get("datos"):
            PREV["error"] = f"AEMET: {meta.get('descripcion') or meta.get('estado') or 'sin datos'}"
            return None
        raw = http_get(meta["datos"])
        try:
            datos = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            datos = json.loads(raw.decode("latin-1"))
        return horas_desde_prevision(datos)
    except Exception as e:  # noqa: BLE001
        print(f"[aviso] previsión de Rivas: {e}", file=sys.stderr)
        PREV["error"] = f"AEMET: {type(e).__name__}: {str(e)[:120]}"
        return None


def horas_desde_prevision(datos) -> list[dict]:
    horas: dict[datetime, dict] = {}
    tormentas = []
    pred = datos[0]["prediccion"]["dia"] if isinstance(datos, list) else datos["prediccion"]["dia"]
    for dia in pred:
        fecha = datetime.fromisoformat(dia["fecha"][:10]).replace(tzinfo=TZ)

        def h(p):
            return fecha + timedelta(hours=int(p[:2]))

        def slot(t):
            return horas.setdefault(t, {"hora": t})

        for x in dia.get("precipitacion", []):
            slot(h(x["periodo"]))["lluvia"] = 0.0 if str(x.get("value")).lower() == "ip" else (_num(x.get("value")) or 0.0)
        for x in dia.get("nieve", []):
            slot(h(x["periodo"]))["nieve"] = 0.0 if str(x.get("value")).lower() == "ip" else (_num(x.get("value")) or 0.0)
        for x in dia.get("temperatura", []):
            slot(h(x["periodo"]))["temp"] = _num(x.get("value"))
        for x in dia.get("vientoAndRachaMax", []):
            if "value" in x and "periodo" in x and _num(x.get("value")) is not None:
                slot(h(x["periodo"]))["racha"] = _num(x.get("value"))
        for x in dia.get("probTormenta", []):
            p = str(x.get("periodo", ""))
            if len(p) == 4:
                ini, fin_h = h(p[:2]), int(p[2:])
                fin = fecha + timedelta(hours=fin_h) if fin_h > int(p[:2]) else fecha + timedelta(days=1, hours=fin_h)
                tormentas.append((ini, fin, _num(x.get("value")) or 0.0))
    lista = sorted(horas.values(), key=lambda d: d["hora"])
    for d in lista:
        d["prob_tormenta"] = max((p for ini, fin, p in tormentas if ini <= d["hora"] < fin), default=0.0)
    return lista


def prevision_en_rivas(aviso: dict, horas) -> str:
    """Texto informativo: qué prevé AEMET para el municipio de Rivas en la ventana del aviso."""
    if not horas:
        return ""
    ini = datetime.fromisoformat(aviso["onset"]) if aviso["onset"] else None
    fin = datetime.fromisoformat(aviso["expires"]) if aviso["expires"] else None
    v = [d for d in horas if (ini is None or d["hora"] >= ini - timedelta(hours=1)) and (fin is None or d["hora"] <= fin)]
    if not v:
        return ""
    fen = (aviso["fenomeno"] + " " + aviso["fen_cod"]).lower()
    if "racha" in fen or "viento" in fen:
        return f"racha máx. {max((d.get('racha') or 0) for d in v):.0f} km/h"
    if "tormenta" in fen:
        return f"prob. de tormenta {max((d.get('prob_tormenta') or 0) for d in v):.0f} %"
    if "nieve" in fen or "nevada" in fen:
        return f"nieve {sum((d.get('nieve') or 0) for d in v):.1f} cm"
    if "lluvia" in fen or "precipit" in fen:
        tot = sum((d.get("lluvia") or 0) for d in v)
        return f"lluvia {tot:.1f} mm en total, máx. {max((d.get('lluvia') or 0) for d in v):.1f} mm/h"
    if "máxima" in fen or "maxima" in fen:
        return f"temp. máx. {max((d.get('temp') or -99) for d in v):.0f} ºC"
    if "mínima" in fen or "minima" in fen:
        return f"temp. mín. {min((d['temp'] if d.get('temp') is not None else 99) for d in v):.0f} ºC"
    return ""


# ======================================================================= eventos AEMET

def eventos_aemet(prev: dict, act: dict, ahora: datetime) -> list[dict]:
    msgs = []

    def cuerpo(a):
        l = [f"Zona AEMET: {a['zona_nombre']} (la de Rivas)"]
        if a["valor"]:
            l.append(f"Umbral del aviso: {a['valor']}")
        l.append(f"Desde {hora(a['onset'])} hasta {hora(a['expires'])}")
        if a.get("probabilidad"):
            l.append(f"Probabilidad: {a['probabilidad']}")
        if a.get("rivas"):
            l.append(f"Previsión AEMET para Rivas: {a['rivas']}")
        if a.get("descripcion"):
            l.append(a["descripcion"])
        return "\n".join(l)

    for k, a in act.items():
        p = prev.get(k)
        n = NIVELES[a["nivel"]]
        fen = a["fenomeno"] or "Fenómeno adverso"
        en_vigor = bool(a["onset"]) and datetime.fromisoformat(a["onset"]) <= ahora
        a["en_vigor_notificado"] = p.get("en_vigor_notificado", False) if p else False
        if p is None:
            msgs.append(mensaje(n, f"{fen} · {cuando(a['onset'], ahora)}", cuerpo(a), extra_tags=["evento-nuevo"]))
            a["en_vigor_notificado"] = en_vigor
            continue
        dn = n - NIVELES[p["nivel"]]
        if dn > 0:
            msgs.append(mensaje(n, f"SUBE · {fen} · {cuando(a['onset'], ahora)}", cuerpo(a), extra_tags=["evento-sube"]))
        elif dn < 0:
            msgs.append(mensaje(n, f"Baja · {fen} · {cuando(a['onset'], ahora)}", cuerpo(a), sube=False,
                                extra_tags=["evento-baja"]))
        if en_vigor and not a["en_vigor_notificado"]:
            msgs.append(mensaje(n, f"EN VIGOR AHORA · {fen}", cuerpo(a), extra_tags=["evento-en-vigor"]))
            a["en_vigor_notificado"] = True
    for k, p in prev.items():
        if k in act:
            continue
        exp = datetime.fromisoformat(p["expires"]) if p.get("expires") else None
        if exp is None or exp > ahora:
            msgs.append(mensaje(0, f"AEMET retira el aviso · {p['fenomeno']} {p['nivel']}",
                                f"El aviso {p['nivel']} de {p['fenomeno']} ({p['valor']}) ya no está activo.",
                                extra_tags=["evento-cancelado"]))
    return msgs


# ======================================================================= agrupado, envío, estado

def agrupar(mensajes: list[dict]) -> list[dict]:
    """Varias novedades del mismo nivel en una comprobación -> una sola notificación."""
    por_nivel: dict[str, list[dict]] = {}
    sueltos = [m for m in mensajes if {"evento-comunicado", "evento-resumen"} & set(m["tags"])]
    mensajes = [m for m in mensajes if m not in sueltos]
    for m in mensajes:
        n = next((t[6:] for t in m["tags"] if t.startswith("nivel-")), "amarillo")
        por_nivel.setdefault(n, []).append(m)
    res = []
    for n in ("info", "normalidad", "amarillo", "naranja", "rojo"):
        lista = por_nivel.get(n, [])
        if len(lista) <= 1:
            res.extend(lista)
            continue
        cuerpo = "\n\n".join(f"• {m['title']}\n{m['message'].split(chr(10) + chr(10) + 'RIV-Alert')[0]}" for m in lista)
        cuerpo = cuerpo[:3600] + "\n\nRIV-Alert · aviso interno PC Rivas (no oficial). Confirma por canales oficiales."
        top = max(lista, key=lambda m: m["priority"])
        if n == "info":  # las noticias ya vienen agrupadas
            res.extend(lista)
            continue
        etq = "FIN" if n == "normalidad" else n.upper()
        res.append({"title": f"{comun.MARCA} {etq} · {len(lista)} novedades", "message": cuerpo,
                    "priority": top["priority"], "tags": [top["tags"][0], f"nivel-{n}", "evento-varios"],
                    "click": PANEL_URL})
    return res + sueltos


def enviar_ntfy(topic: str, msg: dict, server: str = "https://ntfy.sh") -> None:
    body = json.dumps({"topic": topic, **msg}).encode("utf-8")
    req = urllib.request.Request(server, data=body, method="POST",
                                 headers={**comun.UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def cargar_grupos() -> list:
    """Grupos y qué recibe cada uno (grupo.json, editable desde la app por los coordinadores).
    Acepta el formato antiguo de un solo grupo {"niveles", "tipos"}."""
    try:
        d = json.loads((ROOT / "grupo.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    grupos = d.get("grupos") or {"voluntarios": d}
    out = []
    for k, g in grupos.items():
        # El canal es secreto: viene de CANAL_JEFES / CANAL_VOLUNTARIOS (secretos de GitHub), no del repo
        canal = os.environ.get("CANAL_" + k.upper(), "").strip() or g.get("canal", "")
        if canal:
            out.append((k, {**g, "canal": canal}))
    return out


def tipo_de(m: dict) -> str:
    tags = set(m.get("tags", []))
    for t, clave in (("evento-comunicado", "comunicado"), ("evento-resumen", "resumen"), ("evento-noticia", "noticias"),
                     ("evento-rio", "rios"), ("evento-embalse", "embalses"), ("evento-sismo", "sismos"), ("evento-incendio", "incendios"),
                     ("evento-sistema", "sistema"), ("evento-prueba", "prueba")):
        if t in tags:
            return clave
    return "aemet"


def para_grupo(m: dict, cfg: dict) -> bool:
    tipo = tipo_de(m)
    if tipo == "comunicado":
        return True
    if tipo in ("sistema", "prueba"):
        return False
    tipos = cfg.get("tipos", {})
    if tipo in ("resumen", "noticias", "embalses"):
        return bool(tipos.get(tipo))
    if not tipos.get(tipo, True):
        return False
    nivel = next((t[6:] for t in m.get("tags", []) if t.startswith("nivel-")), "")
    if nivel == "normalidad":
        return bool(tipos.get("fin", True))
    return nivel in cfg.get("niveles", ["amarillo", "naranja", "rojo"])


def cargar_estado() -> dict:
    if STATE_FILE.exists():
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    else:
        st = {}
    if st.get("version") != 2:  # migración a RIV-Alert: solo la zona de Rivas, sin avisos de golpe
        st["avisos"] = {k: v for k, v in st.get("avisos", {}).items() if v.get("zona") == ZONA_RIVAS}
        st["version"] = 2
    return st


def guardar_estado(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True, default=str) + "\n",
                          encoding="utf-8")


def resumen(st: dict, ahora: datetime) -> dict:
    l = [f"Situación a las {ahora.astimezone(TZ):%H:%M} del {ahora.astimezone(TZ):%d/%m}", "", "AEMET (zona de Rivas):"]
    peor = 0
    if not st.get("avisos"):
        l.append("• Sin avisos")
    for a in sorted(st.get("avisos", {}).values(), key=lambda a: -NIVELES[a["nivel"]]):
        peor = max(peor, NIVELES[a["nivel"]])
        l.append(f"• {a['nivel'].upper()} {a['fenomeno']} {a['valor']} · {hora(a['onset'])}–{hora(a['expires'])}")
    l += ["", "RÍOS (SAIH Tajo):"]
    for cod, r in sorted(st.get("rios", {}).items(), key=lambda kv: (kv[1].get("tramo") != "rivas", -kv[1].get("nivel", 0))):
        peor = max(peor, r.get("nivel", 0))
        l.append(f"• {r.get('desc', cod)}: {r['valor']:.2f} {r.get('unidad', 'm')} {comun.NOMBRE[r.get('nivel', 0)]}, "
                 f"{(r.get('tendencia') or '').lower()}")
    inc = st.get("incendios", {})
    if inc.get("hoy"):
        l += ["", f"INCENDIOS (AEMET): riesgo hoy {inc['hoy']}" + (f", mañana {inc['manana']}" if inc.get("manana") else "")]
        peor = max(peor, inc.get("nivel", 0))
    s = [x for x in st.get("sismos", {}).values() if x.get("nivel", 0) > 0]
    if s:
        l += ["", "TERREMOTOS (IGN, últimos 10 días):"] + [f"• M{x['mag']} a {x['dist']:.0f} km · {x['lugar']}" for x in s]
    m = mensaje(peor, "RESUMEN de la situación", "\n".join(l), sube=False, extra_tags=["evento-resumen"])
    m["priority"] = 3
    m["title"] = f"{comun.MARCA} · RESUMEN · peor nivel: {comun.NOMBRE[peor].upper()}"
    return m


def comunicado(texto: str, nivel: str, ahora: datetime) -> dict:
    """Mensaje manual del responsable a todos los suscritos."""
    n = NIVELES.get(nivel.lower(), 0)
    cuerpo = (texto[:3000] + f"\n\nComunicado manual enviado el {ahora.astimezone(TZ):%d/%m a las %H:%M} "
              "desde RIV-Alert · Protección Civil Rivas (aviso interno, no oficial).")
    return {
        "title": f"{comun.MARCA} · COMUNICADO" + (f" {nivel.upper()}" if n else "") + f" · {texto.splitlines()[0][:80]}",
        "message": cuerpo,
        "priority": comun.PRIORIDAD.get(n, 3),
        "tags": [comun.EMOJI.get(n, "loudspeaker") if n else "loudspeaker", f"nivel-{comun.NOMBRE[n] if n else 'info'}",
                 "evento-comunicado"],
        "click": PANEL_URL,
    }


def mensajes_de_prueba() -> list[dict]:
    return [
        mensaje(1, "PRUEBA · Lluvia 15 mm en 1 h", "Prueba de RIV-Alert AMARILLO (notificación). No es un aviso real."),
        mensaje(2, "PRUEBA · Rachas 90 km/h", "Prueba de RIV-Alert NARANJA (alerta media). No es un aviso real."),
        mensaje(3, "PRUEBA · Río Manzanares en Rivas", "Prueba de RIV-Alert ROJO (alerta máxima). No es un aviso real."),
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
    key = os.environ.get("AEMET_API_KEY", "").strip()
    horas = descargar_prevision_rivas(key)
    mensajes: list[dict] = []
    salud = st.setdefault("salud", {})

    def fuente(nombre, fn):
        try:
            fn()
            if salud.get(nombre, 0) >= 3:
                mensajes.append({"title": f"{comun.MARCA} · {nombre} vuelve a responder", "priority": 2,
                                 "message": "La fuente vuelve a funcionar.", "tags": ["white_check_mark", "nivel-normalidad"],
                                 "click": PANEL_URL})
            salud[nombre] = 0
            salud.pop(nombre + " · último error", None)
        except Exception as e:  # noqa: BLE001 - una fuente caída no tumba las demás
            salud[nombre] = salud.get(nombre, 0) + 1
            salud[nombre + " · último error"] = f"{type(e).__name__}: {e}"[:300]
            print(f"[aviso] {nombre}: {e}", file=sys.stderr)
            if salud[nombre] == 3:
                mensajes.append({"title": f"{comun.MARCA} · No puedo leer {nombre}", "priority": 3,
                                 "message": f"Llevo 3 comprobaciones sin datos de {nombre}. Vigílalo a mano.",
                                 "tags": ["warning", "nivel-amarillo", "evento-sistema"], "click": PANEL_URL})

    def f_aemet():
        act = avisos_activos(descargar_caps(), ahora)
        for a in act.values():
            a["rivas"] = prevision_en_rivas(a, horas)
        mensajes.extend(eventos_aemet(st.get("avisos", {}), act, ahora))
        st["avisos"] = act

    def f_rios():
        import rios
        st["rios"], m = rios.evaluar(rios.descargar(http_get), st.get("rios", {}))
        mensajes.extend(m)

    def f_sismos():
        import sismos
        st["sismos"], m = sismos.evaluar(sismos.descargar(http_get), st.get("sismos", {}), ahora)
        mensajes.extend(m)

    def f_incendios():
        import incendios
        st["incendios"], m = incendios.evaluar(incendios.descargar(http_get), st.get("incendios", {}), ahora)
        mensajes.extend(m)

    def f_noticias():
        import noticias
        st["noticias"], m = noticias.evaluar(noticias.descargar(http_get), st.get("noticias", {}), ahora)
        mensajes.extend(m)

    fuente("AEMET avisos", f_aemet)
    fuente("SAIH Tajo", f_rios)
    fuente("IGN terremotos", f_sismos)
    fuente("AEMET incendios", f_incendios)
    fuente("Noticias", f_noticias)

    def f_embalses():
        import embalses
        st["embalses"] = embalses.descargar(http_get, st.get("embalses"))
        lluvia = any(re.search(r"lluvi|precip|tormenta", str(a.get("fenomeno", "")), re.I)
                     for a in st.get("avisos", {}).values())
        st["embalses_flags"], m_emb = embalses.evaluar(st["embalses"], st.get("embalses_flags", {}), lluvia)
        mensajes.extend(m_emb)

    fuente("Embalses (embalses.net)", f_embalses)

    extra = []
    if os.environ.get("MODO_RESUMEN") == "1":
        extra.append(resumen(st, ahora))
    texto = os.environ.get("COMUNICADO", "").strip()
    if texto:
        extra.append(comunicado(texto, os.environ.get("NIVEL_COMUNICADO", "informativo"), ahora))

    envios = [("yo", topic, m) for m in agrupar(mensajes) + extra]
    for nombre, cfg in cargar_grupos():
        envios += [(nombre, cfg["canal"], m) for m in agrupar([x for x in mensajes if para_grupo(x, cfg)])
                   + [x for x in extra if para_grupo(x, cfg)]]
    fallos = 0
    for quien, canal, msg in envios:
        print(f"-> [{quien}] {msg['title']}")
        try:
            enviar_ntfy(canal, msg)
        except Exception as e:  # noqa: BLE001
            fallos += 1
            print(f"[error] ntfy: {e}", file=sys.stderr)
    mensajes = [(c, m) for _, c, m in envios]

    # Historial de lo enviado automáticamente (una entrada por notificación, con los grupos que la recibieron)
    hist = st.setdefault("historial", [])
    por_titulo: dict[str, dict] = {}
    for quien, _c, msg in envios:
        if any(t in msg.get("tags", []) for t in ("evento-prueba",)):
            continue
        e = por_titulo.setdefault(msg["title"], {"ts": ahora.isoformat(), "titulo": msg["title"],
                                                 "texto": msg.get("message", "").split("\n\nRIV-Alert ·")[0][:600],
                                                 "nivel": next((t[6:] for t in msg.get("tags", []) if t.startswith("nivel-")), ""),
                                                 "tipo": tipo_de(msg), "para": []})
        if quien != "yo" and quien not in e["para"]:
            e["para"].append(quien)
    hist.extend(por_titulo.values())
    st["historial"] = hist[-200:]

    hb = st.get("heartbeat") or ""
    if not hb or datetime.fromisoformat(hb) < ahora - timedelta(days=20):
        st["heartbeat"] = ahora.isoformat()
    try:
        import panel
        st["prevision_meta"] = dict(PREV)
        st["panel"] = panel.generar(st, horas, key, ahora, http_get)
    except Exception as e:  # noqa: BLE001
        st["panel"] = f"error: {e}"
    guardar_estado(st)
    print(f"{len(st.get('avisos', {}))} avisos, {len(mensajes)} notificaciones.")
    return 1 if fallos and fallos == len(mensajes) else 0


if __name__ == "__main__":
    sys.exit(main())
