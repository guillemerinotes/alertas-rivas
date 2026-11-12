"""RIV-Alert · Ríos (SAIH Tajo, Confederación Hidrográfica del Tajo) con sus umbrales oficiales."""
from __future__ import annotations

import json

from comun import NOMBRE, mensaje

SAIH_BASE = "https://saihtajo.chtajo.es/"
SAIH_AFOROS = (SAIH_BASE + "index.php?w=get-aforosenrio&x="
               "rNqKxe6hty4sr4HZp9XVmoe063kXz645T1nN5hxLO0w4FKC%2F6Wmn4%2F8RslC5vmZCT5CS03tulPXFhb9erSbxHA%3D%3D")
SAIH_WEB = SAIH_BASE

# Estación -> (tramo, descripción). Solo las que pasan por Rivas o le llegan desde aguas arriba.
ESTACIONES = {
    "AR18": ("rivas", "Manzanares en Rivas-Vaciamadrid"),
    "AR17": ("rivas", "Jarama en Mejorada–San Fernando"),
    "MC02": ("rivas", "Jarama en San Fernando"),
    "MC03": ("arriba", "Manzanares en Puente de San Fernando (Madrid)"),
    "R018": ("arriba", "Manzanares en Colmenar Viejo"),
    "R051": ("arriba", "Jarama en Algete"),
    "AR16": ("arriba", "Jarama en Valdepeñas de la Sierra"),
    "AR13": ("arriba", "Henares en Espinillo (Alcalá)"),
    "R061": ("arriba", "Henares en Humanes"),
}
HISTERESIS = 0.03  # m


def _f(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def descargar(http_get) -> list[dict]:
    data = json.loads(http_get(SAIH_AFOROS, headers={"Accept": "application/json", "Referer": SAIH_BASE}))
    return data["response"]["aforos"]


def nivel_de(valor: float, umbrales: list, nivel_previo: int = 0) -> int:
    n = sum(1 for u in umbrales if u is not None and valor >= u)
    if 0 < nivel_previo <= len(umbrales) and n < nivel_previo:
        u = umbrales[nivel_previo - 1]
        if u is not None and valor >= u - HISTERESIS:
            n = nivel_previo
    return n


def evaluar(aforos: list[dict], prev: dict) -> tuple[dict, list[dict]]:
    estado, msgs = {}, []
    por_codigo = {a.get("codigo"): a for a in aforos}
    for cod, (tramo, desc) in ESTACIONES.items():
        a = por_codigo.get(cod)
        v = _f(a.get("value")) if a else None
        if v is None:
            if cod in prev:
                estado[cod] = prev[cod]
            continue
        umbrales = [_f(a.get("umbral1")), _f(a.get("umbral2")), _f(a.get("umbral3"))]
        n_prev = int(prev.get(cod, {}).get("nivel", 0))
        n = nivel_de(v, umbrales, n_prev)
        unidad = a.get("unidad", "m")
        estado[cod] = {"nivel": n, "valor": v, "tendencia": a.get("tendencia", ""), "nombre": a.get("nombre", desc),
                       "desc": desc, "tramo": tramo, "umbrales": umbrales, "unidad": unidad}
        if n == n_prev:
            continue
        donde = "EN RIVAS" if tramo == "rivas" else "aguas arriba de Rivas"
        u_txt = " · ".join(f"{NOMBRE[i + 1]} {u:.2f} {unidad}" for i, u in enumerate(umbrales) if u is not None)
        cuerpo = (f"{desc} ({donde})\nNivel actual: {v:.2f} {unidad}, {(a.get('tendencia') or '?').lower()}\n"
                  f"Umbrales oficiales CHT: {u_txt}\nEstación {cod} · SAIH Tajo (datos provisionales)")
        if n == 0:
            msgs.append(mensaje(0, f"Río · {desc} vuelve a normalidad", cuerpo, extra_tags=["evento-rio"]))
        elif n > n_prev:
            msgs.append(mensaje(n, f"Río · {desc} ({donde}) en umbral {NOMBRE[n].upper()}", cuerpo,
                                extra_tags=["evento-rio", "ocean"]))
        else:
            msgs.append(mensaje(n, f"Río · {desc} baja a {NOMBRE[n]}", cuerpo, sube=False, extra_tags=["evento-rio"]))
    return estado, msgs
