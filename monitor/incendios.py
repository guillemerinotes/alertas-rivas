"""
RIV-Alert · Riesgo meteorológico de incendio forestal en Rivas (AEMET).

AEMET publica el riesgo en cinco niveles: bajo, moderado, alto, muy alto y extremo, como mapas GeoTIFF descargables.
RIV-Alert lee el valor en el punto de Rivas. Equivalencia con colores (criterio de RIV-Alert, NO oficial):
  alto -> amarillo · muy alto -> naranja · extremo (o superior) -> rojo
"""
from __future__ import annotations

import io
import re
import tarfile
from datetime import datetime, timedelta

from comun import NOMBRE, TZ, mensaje

URL = "https://www.aemet.es/es/api-eltiempo/incendios/download"
RIVAS = (40.3283, -3.5158)  # lat, lon
CLASES = {1: "bajo", 2: "moderado", 3: "alto", 4: "muy alto", 5: "extremo", 6: "extremo"}
A_COLOR = {3: 1, 4: 2, 5: 3, 6: 3}


def descargar(http_get) -> dict:
    """Devuelve {fecha (date): clase} para el punto de Rivas, hoy y días siguientes."""
    import numpy as np  # noqa: F401  (lo usa tifffile)
    import tifffile

    data = http_get(URL, timeout=60)
    res, nombres = {}, []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for m in tar.getmembers():
            nombre = m.name.split("/")[-1]
            nombres.append(nombre)
            if not nombre.lower().endswith((".tif", ".tiff")) or "_p_" not in nombre:
                continue
            partes = re.split(r"[_.]", nombre)
            fecha_base = None
            for p in partes:
                if re.fullmatch(r"\d{8}", p):
                    for fmt in ("%Y%m%d", "%d%m%Y"):
                        try:
                            d = datetime.strptime(p, fmt).date()
                        except ValueError:
                            continue
                        if abs((d - datetime.now().date()).days) <= 10:
                            fecha_base = d
                            break
                if fecha_base:
                    break
            desfase = next((int(p) for p in partes[1:4] if re.fullmatch(r"\d{1,2}", p)), 0)
            if not fecha_base:
                continue
            fecha = fecha_base + timedelta(days=desfase)
            clase = valor_en_punto(tar.extractfile(m).read(), RIVAS)
            if clase:
                res[fecha] = clase
    if not res:
        raise ValueError(f"no se encontraron mapas de la península; archivos: {nombres[:6]}")
    res["_archivos"] = nombres[:12]
    return res


def valor_en_punto(tif_bytes: bytes, punto) -> int | None:
    import tifffile

    with tifffile.TiffFile(io.BytesIO(tif_bytes)) as t:
        page = t.pages[0]
        tags = page.tags
        escala = tags["ModelPixelScaleTag"].value
        tie = tags["ModelTiepointTag"].value
        img = page.asarray()
    x0, y0 = tie[3], tie[4]
    sx, sy = escala[0], escala[1]
    lat, lon = punto
    if abs(x0) > 1000:  # coordenadas proyectadas: no sabemos convertir sin la proyección
        raise ValueError("el mapa no está en coordenadas geográficas")
    col = int((lon - x0) / sx)
    fila = int((y0 - lat) / sy)
    if img.ndim > 2:
        img = img[..., 0] if img.shape[-1] < 8 else img[0]
    if not (0 <= fila < img.shape[0] and 0 <= col < img.shape[1]):
        raise ValueError("Rivas cae fuera del mapa")
    v = int(img[fila, col])
    return v if 1 <= v <= 6 else None


def evaluar(por_dia: dict, prev: dict, ahora) -> tuple[dict, list[dict]]:
    archivos = por_dia.pop("_archivos", None)
    hoy = ahora.astimezone(TZ).date()
    c_hoy = por_dia.get(hoy)
    c_man = por_dia.get(hoy + timedelta(days=1))
    estado = {"hoy": CLASES.get(c_hoy, ""), "manana": CLASES.get(c_man, ""), "clase": c_hoy or 0,
              "nivel": A_COLOR.get(c_hoy, 0), "nivel_manana": A_COLOR.get(c_man, 0), "fecha": hoy.isoformat(),
              "dias": {d.isoformat(): CLASES.get(c, "?") for d, c in sorted(por_dia.items())}, "archivos": archivos}
    msgs = []
    n, n_prev = estado["nivel"], int(prev.get("nivel", 0)) if prev.get("fecha") else 0
    cuerpo = (f"Riesgo meteorológico de incendio forestal en Rivas (AEMET): hoy {estado['hoy'] or '?'}"
              f"{', mañana ' + estado['manana'] if estado['manana'] else ''}.\n"
              "Escala AEMET: bajo, moderado, alto, muy alto, extremo. "
              "Equivalencia con colores: alto=amarillo, muy alto=naranja, extremo=rojo (criterio RIV-Alert).")
    if n != n_prev:
        if n == 0:
            msgs.append(mensaje(0, "Riesgo de incendio forestal baja", cuerpo, extra_tags=["evento-incendio"]))
        else:
            msgs.append(mensaje(n, f"Riesgo de incendio forestal {estado['hoy'].upper()} hoy", cuerpo,
                                sube=n > n_prev, extra_tags=["evento-incendio", "fire"]))
    elif estado["nivel_manana"] > max(n, int(prev.get("nivel_manana", 0))):
        nm = estado["nivel_manana"]
        msgs.append(mensaje(nm, f"Riesgo de incendio forestal {estado['manana'].upper()} MAÑANA", cuerpo,
                            extra_tags=["evento-incendio", "fire"]))
    return estado, msgs
