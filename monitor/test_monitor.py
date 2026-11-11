"""Pruebas del vigilante con avisos CAP de ejemplo (no se conecta a internet)."""
import io
import tarfile
import unittest
from datetime import datetime, timedelta, timezone

import monitor as m

CAP = """<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>2.49.0.0.724.0.ES.TEST.{zona}{cod}</identifier>
  <sender>http://www.aemet.es</sender>
  <msgType>{msgtype}</msgType>
  <info>
    <language>es-ES</language>
    <event>Aviso de {fen} de nivel {nivel}</event>
    <onset>{onset}</onset>
    <expires>{expires}</expires>
    <headline>Aviso de {fen} de nivel {nivel}. {zonanombre}</headline>
    <description>Descripción de prueba.</description>
    <parameter><valueName>AEMET-Meteoalerta nivel</valueName><value>{nivel}</value></parameter>
    <parameter><valueName>AEMET-Meteoalerta parametro</valueName><value>{cod};{fen};{valor}</value></parameter>
    <parameter><valueName>AEMET-Meteoalerta probabilidad</valueName><value>40%-70%</value></parameter>
    <area>
      <areaDesc>{zonanombre}</areaDesc>
      <geocode><valueName>AEMET-Meteoalerta zona</valueName><value>{zona}</value></geocode>
    </area>
  </info>
  <info>
    <language>en-GB</language>
    <event>Warning</event>
    <parameter><valueName>AEMET-Meteoalerta nivel</valueName><value>{nivel}</value></parameter>
    <area><areaDesc>{zonanombre}</areaDesc>
      <geocode><valueName>AEMET-Meteoalerta zona</valueName><value>{zona}</value></geocode></area>
  </info>
</alert>"""

AHORA = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def cap(zona="722802", cod="RM", fen="Rachas máximas", valor="80 km/h", nivel="naranja",
        msgtype="Alert", onset="2026-11-12T00:00:00+01:00", expires="2026-11-12T02:59:59+01:00"):
    return CAP.format(zona=zona, zonanombre=m.ZONAS[zona], cod=cod, fen=fen, valor=valor,
                      nivel=nivel, msgtype=msgtype, onset=onset, expires=expires).encode()


def horas(racha=0, lluvia=0, tormenta=0):
    base = datetime(2026, 11, 11, 0, tzinfo=m.TZ)
    return [{"hora": base + timedelta(hours=i), "racha": racha, "lluvia": lluvia,
             "prob_tormenta": tormenta, "nieve": 0, "temp": 10} for i in range(72)]


class Pruebas(unittest.TestCase):
    def test_parseo(self):
        a = m.parse_cap(cap())[0]
        self.assertEqual(a["zona"], "722802")
        self.assertEqual(a["nivel"], "naranja")
        self.assertEqual(a["fenomeno"], "Rachas máximas")
        self.assertEqual(a["valor"], "80 km/h")

    def test_filtra_verde_cancelado_y_caducado(self):
        caps = [cap(nivel="verde"), cap(msgtype="Cancel"),
                cap(onset="2026-11-10T00:00:00+01:00", expires="2026-11-10T03:00:00+01:00")]
        self.assertEqual(m.avisos_activos(caps, AHORA), {})

    def test_niveles_de_alerta(self):
        act = m.avisos_activos([cap(zona="722801"), cap(zona="722802")], AHORA)
        sierra = next(a for a in act.values() if a["zona"] == "722801")
        metro = next(a for a in act.values() if a["zona"] == "722802")
        self.assertEqual(m.nivel_alerta(sierra), "madrid")
        metro["rivas"], _ = m.confirmar_en_rivas(metro, horas(racha=75))
        self.assertEqual(m.nivel_alerta(metro), "rivas")
        metro["rivas"], _ = m.confirmar_en_rivas(metro, horas(racha=30))
        self.assertEqual(m.nivel_alerta(metro), "corredor")
        metro["rivas"], _ = m.confirmar_en_rivas(metro, None)
        self.assertEqual(m.nivel_alerta(metro), "rivas")  # sin datos -> por seguridad, Rivas

    def test_eventos(self):
        act1 = m.avisos_activos([cap(nivel="amarillo")], AHORA)
        ev = m.calcular_eventos({}, act1, AHORA)
        self.assertEqual([e["tipo"] for e in ev], ["nuevo"])
        # sube de nivel
        act2 = m.avisos_activos([cap(nivel="naranja")], AHORA)
        ev = m.calcular_eventos(act1, act2, AHORA)
        self.assertEqual([e["tipo"] for e in ev], ["sube"])
        # entra en vigor
        luego = datetime(2026, 11, 11, 23, 30, tzinfo=timezone.utc)
        act3 = m.avisos_activos([cap(nivel="naranja")], luego)
        ev = m.calcular_eventos(act2, act3, luego)
        self.assertEqual([e["tipo"] for e in ev], ["en_vigor"])
        # sin cambios -> nada
        act4 = m.avisos_activos([cap(nivel="naranja")], luego)
        self.assertEqual(m.calcular_eventos(act3, act4, luego), [])
        # desaparece antes de terminar -> cancelado
        ev = m.calcular_eventos(act4, {}, luego)
        self.assertEqual([e["tipo"] for e in ev], ["cancelado"])
        # caduca normalmente -> nada
        mucho_despues = datetime(2026, 11, 12, 5, 0, tzinfo=timezone.utc)
        self.assertEqual(m.calcular_eventos(act4, {}, mucho_despues), [])

    def test_mensaje(self):
        a = m.avisos_activos([cap()], AHORA)
        a = next(iter(a.values()))
        a["rivas"], a["rivas_motivo"] = "si", "racha máx. prevista en Rivas 75 km/h"
        msg = m.construir_mensaje({"tipo": "nuevo", "aviso": a}, AHORA)
        self.assertIn("RIVAS", msg["title"])
        self.assertIn("MAÑANA", msg["title"])
        self.assertEqual(msg["priority"], 5)
        self.assertIn("nivel-rivas", msg["tags"])

    def test_tar(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            for i, c in enumerate([cap(), cap(zona="722803", cod="NV", fen="Nevadas", valor="5 cm")]):
                info = tarfile.TarInfo(f"a{i}.xml")
                info.size = len(c)
                t.addfile(info, io.BytesIO(c))
        with tarfile.open(fileobj=io.BytesIO(buf.getvalue()), mode="r:gz") as t:
            caps = [t.extractfile(x).read() for x in t.getmembers()]
        self.assertEqual(len(m.avisos_activos(caps, AHORA)), 2)

    def test_prevision_aemet(self):
        datos = [{"prediccion": {"dia": [{
            "fecha": "2026-11-12T00:00:00",
            "precipitacion": [{"value": "Ip", "periodo": "00"}, {"value": "2.4", "periodo": "01"}],
            "nieve": [{"value": "0", "periodo": "00"}],
            "temperatura": [{"value": "9", "periodo": "00"}],
            "vientoAndRachaMax": [{"direccion": ["O"], "velocidad": ["30"], "periodo": "00"},
                                  {"value": "72", "periodo": "00"}],
            "probTormenta": [{"value": "10", "periodo": "0208"}],
        }]}}]
        h = m.horas_desde_prevision(datos)
        self.assertEqual(h[0]["racha"], 72)
        self.assertEqual(h[1]["lluvia"], 2.4)
        a = next(iter(m.avisos_activos([cap()], AHORA).values()))
        self.assertEqual(m.confirmar_en_rivas(a, h)[0], "si")


class PruebasAgrupar(unittest.TestCase):
    def test_agrupa_por_nivel(self):
        caps = [cap(zona=z, cod=c, fen=f) for z in ("722801", "722802", "722803")
                for c, f in (("RM", "Rachas máximas"), ("P1", "Precipitación acumulada en una hora"))]
        act = m.avisos_activos(caps, AHORA)
        for a in act.values():
            if a["zona"] == "722802":
                a["rivas"], a["rivas_motivo"] = "desconocido", ""
        msgs = m.agrupar([m.construir_mensaje(e, AHORA) for e in m.calcular_eventos({}, act, AHORA)])
        self.assertEqual(len(msgs), 2)  # uno MADRID (4 avisos) y uno RIVAS (2 avisos)
        self.assertEqual(sorted(x["priority"] for x in msgs), [3, 5])


if __name__ == "__main__":
    unittest.main()
