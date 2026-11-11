"""
Alertas de nivel de ríos a partir del SAIH Tajo (Confederación Hidrográfica del Tajo).

Usa los umbrales oficiales amarillo / naranja / rojo de cada estación (Protocolo de Comunicación y
Avisos de la Información Hidrológica en caso de crecidas).
"""
from __future__ import annotations

import json
import urllib.request

SAIH_BASE = "https://saihtajo.chtajo.es/"
SAIH_AFOROS = (SAIH_BASE + "index.php?w=get-aforosenrio&x="
               "rNqKxe6hty4sr4HZp9XVmoe063kXz645T1nN5hxLO0w4FKC%2F6Wmn4%2F8RslC5vmZCT5CS03tulPXFhb9erSbxHA%3D%3D")
SAIH_WEB = "https://saihtajo.chtajo.es/"

# Estación -> (nivel de alerta, descripción corta)
ESTACIONES = {
    # RIVAS: en el propio municipio o justo aguas arriba
    "AR18": ("rivas", "Manzanares en Rivas-Vaciamadrid"),
    "AR17": ("rivas", "Jarama en Mejorada–San Fernando (aguas arriba de Rivas)"),
    "MC02": ("rivas", "Jarama en San Fernando (aguas arriba de Rivas)"),
    # CORREDOR / entorno
    "R051": ("corredor", "Jarama en Algete"),
    "AR13": ("corredor", "Henares en Espinillo (Alcalá)"),
    "R061": ("corredor", "Henares en Humanes"),
    "R174": ("corredor", "Jarama en Puente Titulcia (aguas abajo de Rivas)"),
    # MADRID: cabeceras y Madrid capital
    "MC03": ("madrid", "Manzanares en Puente de San Fernando (Madrid)"),
    "R018": ("madrid", "Manzanares en Colmenar Viejo"),
    "AR16": ("madrid", "Jarama en Valdepeñas de la Sierra"),
    "AR15": ("madrid", "Tajuña en Armuña"),
}
NOMBRE_NIVEL = {0: "normalidad", 1: "amarillo", 2: "naranja", 3: "rojo"}
EMOJI = {0: "white_check_mark", 1: "yellow_circle", 2: "orange_circle", 3: "red_circle"}
HISTERESIS = 0.03  # m: para bajar de nivel tiene que quedar 3 cm por debajo del umbral (evita avisos en bucle)


def _f(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def descargar(http_get) -> list[dict]:
    data = json.loads(http_get(SAIH_AFOROS, headers={"Accept": "application/json", "Referer": SAIH_BASE}))
    return data["response"]["aforos"]


def nivel_de(valor: float, umbrales: list[float], nivel_previo: int = 0) -> int:
    n = sum(1 for u in umbrales if u is not None and valor >= u)
    # histéresis al bajar: hay que quedar claramente por debajo del umbral
    if 0 < nivel_previo <= len(umbrales) and n < nivel_previo:
        u = umbrales[nivel_previo - 1]
        if u is not None and valor >= u - HISTERESIS:
            n = nivel_previo
    return n


def evaluar(aforos: list[dict], prev: dict) -> tuple[dict, list[dict]]:
    """Devuelve (estado nuevo, lista de mensajes ntfy)."""
    estado, mensajes = {}, []
    por_codigo = {a.get("codigo"): a for a in aforos}
    for cod, (nivel_alerta, desc) in ESTACIONES.items():
        a = por_codigo.get(cod)
        if not a:
            if cod in prev:
                estado[cod] = prev[cod]
            continue
        v = _f(a.get("value"))
        umbrales = [_f(a.get("umbral1")), _f(a.get("umbral2")), _f(a.get("umbral3"))]
        if v is None:
            if cod in prev:
                estado[cod] = prev[cod]
            continue
        p = prev.get(cod, {})
        n_prev = int(p.get("nivel", 0))
        n = nivel_de(v, umbrales, n_prev)
        unidad = a.get("unidad", "m")
        estado[cod] = {"nivel": n, "valor": v, "tendencia": a.get("tendencia", ""), "nombre": a.get("nombre", desc)}
        if n == n_prev:
            continue
        sube = n > n_prev
        if n == 0:
            accion = "VUELVE A NORMALIDAD"
        elif sube:
            accion = f"UMBRAL {NOMBRE_NIVEL[n].upper()}"
        else:
            accion = f"Baja a {NOMBRE_NIVEL[n]}"
        etiqueta = {"madrid": "MADRID", "corredor": "CORREDOR DEL HENARES", "rivas": "⚠️ RIVAS"}[nivel_alerta]
        prioridad = {"madrid": 3, "corredor": 4, "rivas": 4}[nivel_alerta]
        if nivel_alerta == "rivas" and n >= 2 and sube:
            prioridad = 5  # naranja o rojo en Rivas -> alarma
        elif nivel_alerta == "corredor" and n == 3 and sube:
            prioridad = 5
        if not sube:
            prioridad = 3
        u_txt = " · ".join(f"{NOMBRE_NIVEL[i + 1]} {u:.2f} {unidad}" for i, u in enumerate(umbrales) if u is not None)
        mensajes.append({
            "title": f"{etiqueta} · RÍO · {desc}: {accion}",
            "message": (f"Nivel actual: {v:.2f} {unidad} ({a.get('tendencia', '').lower() or 'tendencia ?'})\n"
                        f"Umbrales oficiales CHT: {u_txt}\n"
                        f"Estación {cod} · {a.get('nombre', '')} · Fuente: SAIH Tajo (datos provisionales)"),
            "priority": prioridad,
            "tags": [EMOJI[n], f"nivel-{nivel_alerta}", "evento-rio", "ocean"],
            "click": SAIH_WEB,
        })
    return estado, mensajes
