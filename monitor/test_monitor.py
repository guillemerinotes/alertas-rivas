"""Pruebas de RIV-Alert con datos de ejemplo (sin internet)."""
import io
import unittest
from datetime import datetime, timedelta, timezone

import comun
import incendios
import monitor as m
import rios
import sismos

CAP = """<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <msgType>{msgtype}</msgType>
  <info>
    <language>es-ES</language>
    <event>Aviso</event>
    <onset>{onset}</onset><expires>{expires}</expires>
    <description>Descripción.</description>
    <parameter><valueName>AEMET-Meteoalerta nivel</valueName><value>{nivel}</value></parameter>
    <parameter><valueName>AEMET-Meteoalerta parametro</valueName><value>{cod};{fen};{valor}</value></parameter>
    <parameter><valueName>AEMET-Meteoalerta probabilidad</valueName><value>40%-70%</value></parameter>
    <area><areaDesc>{zn}</areaDesc>
      <geocode><valueName>AEMET-Meteoalerta zona</valueName><value>{zona}</value></geocode></area>
  </info>
</alert>"""
AHORA = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
ZN = {"722801": "Sierra de Madrid", "722802": "Metropolitana y Henares", "722803": "Sur, Vegas y Oeste"}


def cap(zona="722802", cod="RM", fen="Rachas máximas", valor="90 km/h", nivel="naranja", msgtype="Alert",
        onset="2026-11-12T00:00:00+01:00", expires="2026-11-12T02:59:59+01:00"):
    return CAP.format(zona=zona, zn=ZN[zona], cod=cod, fen=fen, valor=valor, nivel=nivel, msgtype=msgtype,
                      onset=onset, expires=expires).encode()


class PruebasAEMET(unittest.TestCase):
    def test_solo_zona_de_rivas(self):
        act = m.avisos_activos([cap(zona="722801"), cap(zona="722803"), cap()], AHORA)
        self.assertEqual([a["zona"] for a in act.values()], ["722802"])

    def test_colores_y_prioridades(self):
        for nivel, prio in (("amarillo", 3), ("naranja", 4), ("rojo", 5)):
            act = m.avisos_activos([cap(nivel=nivel)], AHORA)
            msgs = m.eventos_aemet({}, act, AHORA)
            self.assertEqual(msgs[0]["priority"], prio)
            self.assertIn(f"RIV-Alert {nivel.upper()}", msgs[0]["title"])

    def test_nieve_y_tormenta(self):
        act = m.avisos_activos([cap(cod="NE", fen="Nevadas", valor="5 cm"),
                                cap(cod="TO", fen="Tormentas", valor="", nivel="amarillo")], AHORA)
        self.assertEqual(len(act), 2)

    def test_eventos(self):
        a1 = m.avisos_activos([cap(nivel="amarillo")], AHORA)
        self.assertIn("evento-nuevo", m.eventos_aemet({}, a1, AHORA)[0]["tags"])
        a2 = m.avisos_activos([cap(nivel="rojo")], AHORA)
        ev = m.eventos_aemet(a1, a2, AHORA)
        self.assertIn("SUBE", ev[0]["title"])
        self.assertEqual(ev[0]["priority"], 5)
        luego = datetime(2026, 11, 11, 23, 30, tzinfo=timezone.utc)
        a3 = m.avisos_activos([cap(nivel="rojo")], luego)
        self.assertIn("EN VIGOR", m.eventos_aemet(a2, a3, luego)[0]["title"])
        self.assertIn("FIN", m.eventos_aemet(a3, {}, luego)[0]["title"])
        self.assertEqual(m.eventos_aemet(a3, {}, datetime(2026, 11, 12, 5, tzinfo=timezone.utc)), [])

    def test_agrupar(self):
        g = m.agrupar([comun.mensaje(1, "a", "x"), comun.mensaje(1, "b", "y"), comun.mensaje(3, "c", "z")])
        self.assertEqual(sorted(x["priority"] for x in g), [3, 5])


class PruebasRios(unittest.TestCase):
    def af(self, cod, v):
        return {"codigo": cod, "value": v, "umbral1": "1.92", "umbral2": "2.35", "umbral3": "2.66",
                "unidad": "m", "tendencia": "Ascendente", "nombre": "X"}

    def test_colores(self):
        st, ms = rios.evaluar([self.af("AR18", 2.0)], {})
        self.assertEqual(ms[0]["priority"], 3)
        st, ms = rios.evaluar([self.af("AR18", 2.4)], st)
        self.assertEqual(ms[0]["priority"], 4)
        st, ms = rios.evaluar([self.af("AR18", 4.3)], st)
        self.assertEqual(ms[0]["priority"], 5)
        st, ms = rios.evaluar([self.af("AR18", 1.0)], st)
        self.assertIn("normalidad", ms[0]["title"])

    def test_fuera_de_rivas_se_ignora(self):
        self.assertEqual(rios.evaluar([self.af("R174", 3.0), self.af("AR15", 3.0)], {}), ({}, []))


RSS_IGN = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#"><channel>
<item><title>-Info.terremoto: 12/11/2026 08:00:00</title>
<link>http://www.ign.es/x?evid=es2026abcd</link>
<description>Se ha producido un terremoto de magnitud 3.8 en ARGANDA DEL REY.M en la fecha 12/11/2026 08:00:00 en la siguiente localización: 40.30,-3.44</description>
<geo:lat>40.30</geo:lat><geo:long>-3.44</geo:long></item>
<item><title>x</title><link>http://x?evid=es2026zz</link>
<description>Se ha producido un terremoto de magnitud 2.0 en ALBORÁN en la fecha 12/11/2026 07:00:00 en la siguiente localización: 35.9,-3.0</description>
<geo:lat>35.9</geo:lat><geo:long>-3.0</geo:long></item>
</channel></rss>"""


class PruebasSismos(unittest.TestCase):
    def test_cercano_y_lejano(self):
        st, ms = sismos.evaluar(RSS_IGN.encode(), {}, AHORA)
        self.assertEqual(list(st), ["es2026abcd"])
        self.assertEqual(ms[0]["priority"], 4)
        self.assertEqual(sismos.evaluar(RSS_IGN.encode(), st, AHORA)[1], [])

    def test_tabla(self):
        self.assertEqual(sismos.nivel_sismo(2.0, 10), 0)
        self.assertEqual(sismos.nivel_sismo(5.6, 120), 3)
        self.assertEqual(sismos.nivel_sismo(4.0, 500), 0)


class PruebasIncendios(unittest.TestCase):
    def test_evaluar(self):
        hoy = AHORA.astimezone(comun.TZ).date()
        d = {hoy: 4, hoy + timedelta(days=1): 5}
        st, ms = incendios.evaluar(d, {}, AHORA)
        self.assertEqual((st["nivel"], ms[0]["priority"]), (2, 4))
        self.assertEqual(incendios.evaluar(d, st, AHORA)[1], [])

    def test_geotiff(self):
        try:
            import numpy as np
            import tifffile
        except ImportError:
            self.skipTest("tifffile no instalado")
        img = np.zeros((100, 100), dtype=np.uint8)
        img[36, 54] = 4  # rejilla 0.1º desde lon -9, lat 44 -> Rivas en col 54, fila 36
        buf = io.BytesIO()
        tifffile.imwrite(buf, img, extratags=[(33550, "d", 3, (0.1, 0.1, 0.0), False),
                                               (33922, "d", 6, (0, 0, 0, -9.0, 44.0, 0), False)])
        self.assertEqual(incendios.valor_en_punto(buf.getvalue(), incendios.RIVAS), 4)


class PruebasResumen(unittest.TestCase):
    def test_resumen(self):
        st = {"avisos": m.avisos_activos([cap()], AHORA),
              "rios": {"AR18": {"nivel": 3, "valor": 4.3, "desc": "Manzanares en Rivas", "tramo": "rivas",
                                "tendencia": "Estable", "unidad": "m"}},
              "incendios": {"hoy": "bajo", "nivel": 0}}
        r = m.resumen(st, AHORA)
        self.assertIn("ROJO", r["title"])
        self.assertEqual(r["priority"], 3)


if __name__ == "__main__":
    unittest.main()
