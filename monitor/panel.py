"""Genera los datos del panel web (site/datos.json) y guarda las últimas imágenes del radar de AEMET."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
RADAR_DIR = SITE / "radar"
MAX_FRAMES = 12  # ~2 horas a 10 min
RADAR_API = "https://opendata.aemet.es/opendata/api/red/radar/regional/{codigo}"
CODIGOS_RADAR_MADRID = ["ma", "mad", "MA"]  # no confirmado cuál usa AEMET; se prueban en orden


def _radar_aemet(key: str, http_get, ahora: datetime) -> str:
    """Descarga la imagen actual del radar regional de Madrid. Devuelve un texto de estado."""
    RADAR_DIR.mkdir(parents=True, exist_ok=True)
    ultimo_error = ""
    for cod in CODIGOS_RADAR_MADRID:
        try:
            meta = json.loads(http_get(RADAR_API.format(codigo=cod), headers={"api_key": key}))
            url = meta.get("datos")
            if not url:
                ultimo_error = f"{cod}: {meta.get('descripcion', 'sin datos')}"
                continue
            img = http_get(url)
            if len(img) < 500:
                ultimo_error = f"{cod}: imagen vacía"
                continue
            ext = ".gif" if img[:3] == b"GIF" else ".png" if img[:4] == b"\x89PNG" else ".jpg"
            h = hashlib.sha1(img).hexdigest()[:10]
            if any(h in f.name for f in RADAR_DIR.iterdir()):
                return f"ok ({cod}, sin imagen nueva)"
            nombre = f"{ahora:%Y%m%d%H%M}_{h}{ext}"
            (RADAR_DIR / nombre).write_bytes(img)
            frames = sorted(RADAR_DIR.iterdir())
            for f in frames[:-MAX_FRAMES]:
                f.unlink()
            return f"ok ({cod})"
        except Exception as e:  # noqa: BLE001
            ultimo_error = f"{cod}: {e}"
    return f"error: {ultimo_error}"


def _prevision(horas: list[dict] | None, ahora: datetime) -> list[dict]:
    if not horas:
        return []
    desde = ahora - timedelta(hours=1)
    out = []
    for h in horas:
        if h["hora"] < desde:
            continue
        out.append({
            "hora": h["hora"].isoformat(),
            "lluvia": h.get("lluvia"),
            "racha": h.get("racha"),
            "temp": h.get("temp"),
            "nieve": h.get("nieve"),
            "tormenta": h.get("prob_tormenta"),
        })
        if len(out) >= 36:
            break
    return out


def generar(st: dict, horas, key: str, ahora: datetime, http_get) -> None:
    SITE.mkdir(exist_ok=True)
    shutil.copy(ROOT / "panel" / "index.html", SITE / "index.html")
    estado_radar = "radar en la app (RainViewer)"  # el radar de AEMET ya no se descarga
    print(f"Radar AEMET: {estado_radar}")
    frames = sorted(f.name for f in RADAR_DIR.iterdir()) if RADAR_DIR.exists() else []
    radar = []
    for f in frames:
        try:
            t = datetime.strptime(f[:12], "%Y%m%d%H%M").replace(tzinfo=ahora.tzinfo)
            radar.append({"archivo": f"radar/{f}", "hora": t.isoformat()})
        except ValueError:
            pass
    datos = {
        "actualizado": ahora.isoformat(),
        "avisos": sorted(st.get("avisos", {}).values(), key=lambda a: (a.get("onset", ""), a.get("zona", ""))),
        "rios": st.get("rios", {}),
        "sismos": sorted(st.get("sismos", {}).values(), key=lambda x: -x.get("nivel", 0)),
        "incendios": st.get("incendios", {}),
        "embalses": st.get("embalses", {}),
        "historial": list(reversed(st.get("historial", [])))[:100],
        "noticias": st.get("noticias", {}).get("recientes", []),
        "salud": st.get("salud", {}),
        "prevision_rivas": _prevision(horas, ahora),
        "prevision_fuente": st.get("prevision_meta", {}).get("fuente"),
        "prevision_error": st.get("prevision_meta", {}).get("error"),
        "radar_aemet": radar,
        "radar_estado": estado_radar,
    }
    (SITE / "datos.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    print(f"Panel generado: {len(datos['avisos'])} avisos, {len(radar)} imágenes de radar.", file=sys.stderr)
    return f"radar {estado_radar}; {len(radar)} imágenes; previsión {len(datos['prevision_rivas'])} h"
