from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from torneos.models import Categoria, Equipo, Jugador, Partido, Tarjeta, Torneo

from .models import CobroTarjeta, Configuracion, CuentaEquipo, Ingreso, PagoTarjetas


class ContabilidadIndependienteTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(nombre="Torneo contable", fecha_inicio=date(2026, 1, 1))
        self.categoria = Categoria.objects.create(nombre="Senior", torneo=self.torneo, edad_minima=18, edad_maxima=70)
        self.equipo = Equipo.objects.create(nombre="Equipo Uno", categoria=self.categoria)
        self.rival = Equipo.objects.create(nombre="Equipo Dos", categoria=self.categoria)
        self.jugador = Jugador.objects.create(equipo=self.equipo, nombres="Jugador Uno", cedula="CT-1", fecha_nacimiento=date(1990, 1, 1))
        self.partido = Partido.objects.create(categoria=self.categoria, equipo_local=self.equipo, equipo_visitante=self.rival, fecha=date(2026, 1, 2), hora=time(16), estado="FINALIZADO")
        self.user = User.objects.create_superuser("contable", password="clave")
        self.client.force_login(self.user)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

    def test_tarjeta_crea_un_cobro_unico_y_al_eliminarla_desaparece(self):
        tarjeta = Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA")
        self.assertEqual(CobroTarjeta.objects.get(tarjeta=tarjeta).valor, Decimal("5000"))
        tarjeta.save()
        self.assertEqual(CobroTarjeta.objects.filter(tarjeta=tarjeta).count(), 1)
        tarjeta.delete()
        self.assertFalse(CobroTarjeta.objects.exists())

    def test_pago_tarjetas_genera_un_solo_ingreso_detallado(self):
        Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA")
        Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="ROJA")
        cuenta = CuentaEquipo.objects.get(equipo=self.equipo)
        respuesta = self.client.post(f"/contabilidad/cuentas/{cuenta.id}/pagar-tarjetas/", {"forma_pago": "Nequi"})
        self.assertEqual(respuesta.status_code, 302)
        pago = PagoTarjetas.objects.get()
        self.assertEqual((pago.cantidad_amarillas, pago.cantidad_rojas, pago.total), (1, 1, Decimal("13000")))
        self.assertEqual(Ingreso.objects.filter(tipo="TARJETAS").count(), 1)
        self.assertIn("Amarillas: 1", pago.ingreso.detalle)

    def test_interfaz_es_ruta_separada(self):
        respuesta = self.client.get("/contabilidad/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "CONTROL CONTABLE")
        Configuracion.objects.get(torneo=self.torneo)

    def test_tarjetas_se_filtran_por_categoria_equipo_y_fecha(self):
        Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA")
        respuesta = self.client.get("/contabilidad/tarjetas/", {
            "categoria": self.categoria.id,
            "equipo": self.equipo.id,
            "desde": "2026-01-02",
            "hasta": "2026-01-02",
            "estado": "pendiente",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(list(respuesta.context["cobros"]), list(CobroTarjeta.objects.all()))
        self.assertContains(respuesta, "Equipo Uno")

        vacia = self.client.get("/contabilidad/tarjetas/", {"desde": "2026-01-03"})
        self.assertFalse(vacia.context["cobros"].exists())

    def test_reporte_tarjetas_respeta_filtros(self):
        Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="ROJA")
        respuesta = self.client.get("/contabilidad/tarjetas/reporte/", {"equipo": self.equipo.id})
        contenido = respuesta.content.decode("utf-8-sig")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("Equipo Uno", contenido)
        self.assertIn("Roja", contenido)

    def test_selector_contable_cambia_torneo_en_su_propia_sesion(self):
        otro = Torneo.objects.create(nombre="Otro torneo", fecha_inicio=date(2026, 2, 1))
        respuesta = self.client.post("/contabilidad/seleccionar-torneo/", {"torneo_id": otro.id})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.client.session["contabilidad_torneo_id"], otro.id)
        self.assertEqual(self.client.session["torneo_id"], self.torneo.id)

        pagina = self.client.get("/contabilidad/")
        self.assertContains(pagina, "Otro torneo")
        self.assertEqual(pagina.context["torneo"], otro)

    def test_torneo_finalizado_puede_consultarse_en_contabilidad(self):
        self.torneo.estado = "FINALIZADO"
        self.torneo.save(update_fields=["estado"])
        respuesta = self.client.get("/contabilidad/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Torneo contable")
