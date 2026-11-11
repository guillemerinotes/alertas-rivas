import unittest
import rios


def aforo(cod, v, u=(1.92, 2.35, 2.66)):
    return {"codigo": cod, "nombre": "X", "value": v, "umbral1": str(u[0]), "umbral2": str(u[1]),
            "umbral3": str(u[2]), "unidad": "m", "tendencia": "Ascendente"}


class PruebasRios(unittest.TestCase):
    def test_sube_y_baja(self):
        st, m = rios.evaluar([aforo("AR18", 2.33)], {})
        self.assertEqual(st["AR18"]["nivel"], 1)
        self.assertEqual(len(m), 1)
        self.assertIn("RIVAS", m[0]["title"])
        self.assertEqual(m[0]["priority"], 4)
        st2, m = rios.evaluar([aforo("AR18", 2.40)], st)
        self.assertEqual(m[0]["priority"], 5)  # naranja en Rivas -> alarma
        st3, m = rios.evaluar([aforo("AR18", 2.34)], st2)
        self.assertEqual(m, [])  # histéresis: aún no baja
        st4, m = rios.evaluar([aforo("AR18", 2.30)], st3)
        self.assertEqual(st4["AR18"]["nivel"], 1)
        st5, m = rios.evaluar([aforo("AR18", 1.50)], st4)
        self.assertIn("NORMALIDAD", m[0]["title"])

    def test_estacion_desconocida_se_ignora(self):
        st, m = rios.evaluar([aforo("ZZ99", 9)], {})
        self.assertEqual((st, m), ({}, []))


if __name__ == "__main__":
    unittest.main()
