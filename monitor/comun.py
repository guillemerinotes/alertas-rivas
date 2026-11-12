"""Piezas comunes de RIV-Alert: niveles, descargas y formato de mensajes."""
from __future__ import annotations

import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
UA = {"User-Agent": "riv-alert/2.0 (+https://github.com/guillemerinotes/alertas-rivas)"}
PANEL_URL = "https://guillemerinotes.github.io/alertas-rivas/"
MARCA = "RIV-Alert"

# Color oficial -> número
NIVELES = {"amarillo": 1, "naranja": 2, "rojo": 3}
NOMBRE = {0: "normalidad", 1: "amarillo", 2: "naranja", 3: "rojo"}
EMOJI = {0: "white_check_mark", 1: "yellow_circle", 2: "orange_circle", 3: "red_circle"}
# Amarillo = notificación · Naranja = alerta media · Rojo = alerta máxima
PRIORIDAD = {1: 3, 2: 4, 3: 5}


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def hora(iso: str) -> str:
    if not iso:
        return "?"
    d = datetime.fromisoformat(iso).astimezone(TZ)
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    return f"{dias[d.weekday()]} {d:%d/%m %H:%M}"


def cuando(iso: str, ahora: datetime) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso).astimezone(TZ).date()
    hoy = ahora.astimezone(TZ).date()
    if d <= hoy:
        return "HOY"
    if d == hoy + timedelta(days=1):
        return "MAÑANA"
    if d == hoy + timedelta(days=2):
        return "PASADO MAÑANA"
    return d.strftime("%d/%m")


def mensaje(nivel: int, texto_titulo: str, cuerpo: str, sube: bool = True, extra_tags=()) -> dict:
    """Construye la notificación. nivel 0 = vuelta a normalidad / fin."""
    if nivel == 0:
        titulo = f"{MARCA} · FIN · {texto_titulo}"
        prioridad = 2
    else:
        titulo = f"{MARCA} {NOMBRE[nivel].upper()} · {texto_titulo}"
        prioridad = PRIORIDAD[nivel] if sube else 3
    return {
        "title": titulo,
        "message": cuerpo + "\n\nRIV-Alert · aviso interno PC Rivas (no oficial). Confirma por canales oficiales.",
        "priority": prioridad,
        "tags": [EMOJI[nivel], f"nivel-{NOMBRE[nivel]}", *extra_tags],
        "click": PANEL_URL,
    }
