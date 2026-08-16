from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from torneos.models import Categoria, Equipo, Jugador, Partido, Tarjeta, Torneo

from .models import CobroTarjeta, Configuracion, CuentaEquipo, Egreso, Ingreso, PagoTarjetas


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
        cuenta = CuentaEquipo.objects.get(torneo=self.torneo, equipo=self.equipo)
        respuesta = self.client.post(f"/contabilidad/cuentas/{cuenta.id}/pagar-tarjetas/", {"forma_pago": "Nequi"})
        self.assertEqual(respuesta.status_code, 302)
        pago = PagoTarjetas.objects.get()
        self.assertEqual((pago.cantidad_amarillas, pago.cantidad_rojas, pago.total), (1, 1, Decimal("13000")))
        self.assertEqual(Ingreso.objects.filter(tipo="TARJETAS").count(), 1)
        self.assertIn("Amarillas: 1", pago.ingreso.detalle)

    def test_cambiar_valores_tarjetas_recalcula_pagos_e_ingresos_activos(self):
        amarilla = Tarjeta.objects.create(
            partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA"
        )
        roja = Tarjeta.objects.create(
            partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="ROJA"
        )
        cuenta = CuentaEquipo.objects.get(torneo=self.torneo, equipo=self.equipo)
        self.client.post(f"/contabilidad/cuentas/{cuenta.id}/pagar-tarjetas/")
        pago = PagoTarjetas.objects.get()

        respuesta = self.client.post("/contabilidad/configurar/", {
            "valor_amarilla": "6000",
            "valor_roja": "10000",
            "valor_mensualidad": "0",
            "dia_limite_mensualidad": "10",
        })

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(CobroTarjeta.objects.get(tarjeta=amarilla).valor, Decimal("6000"))
        self.assertEqual(CobroTarjeta.objects.get(tarjeta=roja).valor, Decimal("10000"))
        pago.refresh_from_db()
        pago.ingreso.refresh_from_db()
        self.assertEqual(pago.valor_unitario_amarilla, Decimal("6000"))
        self.assertEqual(pago.valor_unitario_roja, Decimal("10000"))
        self.assertEqual(pago.total, Decimal("16000"))
        self.assertEqual(pago.ingreso.valor, Decimal("16000"))
        self.assertIn("Amarillas: 1 x $6000", pago.ingreso.detalle)
        self.assertEqual(self.client.get("/contabilidad/").context["ingresos"], Decimal("16000"))

    def test_interfaz_es_ruta_separada(self):
        respuesta = self.client.get("/contabilidad/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "CONTROL CONTABLE")
        self.assertNotContains(respuesta, 'class="category-accordion" open')
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
        self.assertIn("TOTALIZADO DE TARJETAS", contenido)

    def test_totalizado_tarjetas_muestra_cantidades_dinero_pagado_y_pendiente(self):
        Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA")
        Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="ROJA")
        cuenta = CuentaEquipo.objects.get(torneo=self.torneo, equipo=self.equipo)
        pagina = self.client.get("/contabilidad/tarjetas/")
        self.assertEqual(pagina.context["totales"]["cantidad"], 2)
        self.assertEqual(pagina.context["totales"]["amarillas"], 1)
        self.assertEqual(pagina.context["totales"]["rojas"], 1)
        self.assertEqual(pagina.context["totales"]["valor_total"], Decimal("13000"))
        self.assertEqual(pagina.context["totales"]["valor_pendiente"], Decimal("13000"))

        self.client.post(f"/contabilidad/cuentas/{cuenta.id}/pagar-tarjetas/")
        pagina = self.client.get("/contabilidad/tarjetas/")
        self.assertEqual(pagina.context["totales"]["valor_pagado"], Decimal("13000"))
        self.assertEqual(pagina.context["totales"]["valor_pendiente"], Decimal("0"))

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

    def test_equipos_del_torneo_se_sincronizan_sin_crearlos_manualmente(self):
        cuenta = CuentaEquipo.objects.get(equipo=self.equipo)
        self.assertEqual(cuenta.torneo, self.torneo)
        self.assertEqual(cuenta.categoria, self.categoria)

        categoria_nueva = Categoria.objects.create(
            nombre="Veteranos", torneo=self.torneo, edad_minima=35, edad_maxima=80,
        )
        self.equipo.categoria = categoria_nueva
        self.equipo.save(update_fields=["categoria"])

        cuenta.refresh_from_db()
        self.assertEqual(CuentaEquipo.objects.filter(torneo=self.torneo, equipo=self.equipo).count(), 1)
        self.assertEqual(cuenta.categoria, categoria_nueva)

    def test_tarjeta_historica_no_derrumba_contabilidad_si_equipo_cambio_categoria(self):
        tarjeta = Tarjeta.objects.create(
            partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA",
        )
        otro_torneo = Torneo.objects.create(nombre="Torneo posterior", fecha_inicio=date(2027, 1, 1))
        otra_categoria = Categoria.objects.create(
            nombre="Senior posterior", torneo=otro_torneo, edad_minima=18, edad_maxima=80,
        )
        self.equipo.categoria = otra_categoria
        self.equipo.save(update_fields=["categoria"])

        respuesta = self.client.get("/contabilidad/")
        self.assertEqual(respuesta.status_code, 200)
        cobro = CobroTarjeta.objects.get(tarjeta=tarjeta)
        self.assertEqual(cobro.cuenta.torneo, self.torneo)
        self.assertEqual(cobro.cuenta.categoria, self.categoria)

    def test_apertura_no_reprocesa_tarjetas_que_ya_estan_sincronizadas(self):
        Tarjeta.objects.create(
            partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA",
        )
        respuesta = self.client.get("/contabilidad/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(CobroTarjeta.objects.count(), 1)

    def test_registro_manual_de_ingreso_usa_listado_y_fondo(self):
        respuesta = self.client.post("/contabilidad/ingresos/nuevo/", {
            "categoria": self.categoria.id,
            "concepto": "Patrocinio",
            "valor": "250000",
            "fecha": "2026-01-03",
            "forma_pago": "Transferencia",
            "detalle": "Patrocinador principal",
        })
        self.assertEqual(respuesta.status_code, 302)
        ingreso = Ingreso.objects.get(tipo="OTRO")
        self.assertEqual(ingreso.concepto, "Patrocinio")
        self.assertEqual(ingreso.categoria, self.categoria)
        self.assertEqual(ingreso.forma_pago, "Transferencia")

    def test_registro_egreso_usa_listado_y_fondo_general(self):
        respuesta = self.client.post("/contabilidad/egresos/nuevo/", {
            "categoria": "",
            "concepto": "Pago de árbitros",
            "valor": "80000",
            "fecha": "2026-01-03",
            "forma_pago": "Efectivo",
            "observacion": "Fecha 1",
        })
        self.assertEqual(respuesta.status_code, 302)
        egreso = Egreso.objects.get()
        self.assertEqual(egreso.concepto, "Pago de árbitros")
        self.assertIsNone(egreso.categoria)

    def test_inscripciones_pueden_financiar_premiacion_y_otros_gastos(self):
        cuenta = CuentaEquipo.objects.get(torneo=self.torneo, equipo=self.equipo)
        cuenta.valor_inscripcion = Decimal("500000")
        cuenta.save(update_fields=["valor_inscripcion"])
        self.client.post("/contabilidad/cuentas/%s/" % cuenta.id, {
            "accion": "abono", "valor": "300000", "fecha": "2026-01-03",
            "observacion": "Abono", "forma_pago": "Efectivo",
        })
        self.client.post("/contabilidad/egresos/nuevo/", {
            "categoria": self.categoria.id, "concepto": "Premiación", "valor": "100000",
            "fecha": "2026-01-04", "forma_pago": "Efectivo", "observacion": "Trofeos",
        })
        self.client.post("/contabilidad/egresos/nuevo/", {
            "categoria": self.categoria.id, "concepto": "Alquiler de cancha", "valor": "50000",
            "fecha": "2026-01-04", "forma_pago": "Efectivo", "observacion": "Fecha final",
        })
        pagina = self.client.get("/contabilidad/")
        self.assertEqual(pagina.context["inscripciones_recaudadas"], Decimal("300000"))
        self.assertEqual(pagina.context["gastos_desde_inscripciones"], Decimal("150000"))
        self.assertEqual(pagina.context["inscripciones_disponibles"], Decimal("150000"))

    def test_anular_abono_lo_conserva_en_auditoria_y_restaura_deuda(self):
        cuenta = CuentaEquipo.objects.get(torneo=self.torneo, equipo=self.equipo)
        cuenta.valor_inscripcion = Decimal("150000")
        cuenta.save(update_fields=["valor_inscripcion"])
        self.client.post(f"/contabilidad/cuentas/{cuenta.id}/", {
            "accion": "abono", "valor": "100000", "fecha": "2026-01-03",
            "observacion": "Primer pago", "forma_pago": "Efectivo",
        })
        ingreso = Ingreso.objects.get(tipo="INSCRIPCION")
        self.assertEqual(cuenta.saldo_inscripcion, Decimal("50000"))
        respuesta = self.client.post(
            f"/contabilidad/movimientos/ingreso/{ingreso.id}/anular/",
            {"motivo": "Pago registrado por error"},
        )
        self.assertEqual(respuesta.status_code, 302)
        ingreso.refresh_from_db()
        self.assertTrue(ingreso.anulado)
        self.assertEqual(ingreso.anulado_por, self.user)
        self.assertEqual(cuenta.saldo_inscripcion, Decimal("150000"))
        self.assertTrue(ingreso.abono_inscripcion.pk)

    def test_anular_pago_tarjetas_devuelve_los_cobros_a_pendientes(self):
        Tarjeta.objects.create(partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="ROJA")
        cuenta = CuentaEquipo.objects.get(torneo=self.torneo, equipo=self.equipo)
        self.client.post(f"/contabilidad/cuentas/{cuenta.id}/pagar-tarjetas/")
        ingreso = Ingreso.objects.get(tipo="TARJETAS")
        self.assertEqual(cuenta.saldo_tarjetas, Decimal("0"))
        self.client.post(
            f"/contabilidad/movimientos/ingreso/{ingreso.id}/anular/",
            {"motivo": "El pago no fue recibido"},
        )
        ingreso.refresh_from_db()
        self.assertTrue(ingreso.anulado)
        self.assertEqual(cuenta.saldo_tarjetas, Decimal("8000"))
        self.assertIsNone(CobroTarjeta.objects.get().pago_id)

    def test_anular_egreso_lo_excluye_del_balance_sin_borrarlo(self):
        egreso = Egreso.objects.create(
            torneo=self.torneo, categoria=self.categoria, concepto="Premiación",
            valor=Decimal("50000"), registrado_por=self.user,
        )
        self.client.post(
            f"/contabilidad/movimientos/egreso/{egreso.id}/anular/",
            {"motivo": "Comprobante equivocado"},
        )
        egreso.refresh_from_db()
        self.assertTrue(egreso.anulado)
        pagina = self.client.get("/contabilidad/")
        self.assertEqual(pagina.context["egresos_total"], Decimal("0"))
        self.assertContains(pagina, "Comprobante equivocado")

    def test_mensualidades_permanecen_ocultas_en_torneos_no_habilitados(self):
        pagina = self.client.get("/contabilidad/")
        self.assertNotContains(pagina, ">Mensualidades</a>")
        respuesta = self.client.get("/contabilidad/mensualidades/")
        self.assertRedirects(respuesta, "/contabilidad/")

    def test_torneo_puede_habilitar_mensualidades_sin_afectar_otros_torneos(self):
        otro = Torneo.objects.create(nombre="Torneo sin mensualidad", fecha_inicio=date(2026, 2, 1))
        Configuracion.objects.create(torneo=otro)
        respuesta = self.client.post("/contabilidad/configurar/", {
            "valor_amarilla": "5000", "valor_roja": "8000",
            "mensualidades_habilitadas": "1", "valor_mensualidad": "100000",
            "dia_limite_mensualidad": "10", "mes_inicio_mensualidades": "2026-08",
            "mes_fin_mensualidades": "2026-12",
        })
        self.assertEqual(respuesta.status_code, 302)
        configuracion = Configuracion.objects.get(torneo=self.torneo)
        self.assertTrue(configuracion.mensualidades_habilitadas)
        self.assertEqual(configuracion.valor_mensualidad, Decimal("100000"))
        self.assertFalse(Configuracion.objects.get(torneo=otro).mensualidades_habilitadas)
        self.assertContains(self.client.get("/contabilidad/"), "Mensualidades")

    def test_mensualidad_admite_abonos_y_anulacion_restaura_el_pendiente(self):
        configuracion = Configuracion.objects.get_or_create(torneo=self.torneo)[0]
        configuracion.mensualidades_habilitadas = True
        configuracion.valor_mensualidad = Decimal("100000")
        configuracion.mes_inicio_mensualidades = date(2026, 8, 1)
        configuracion.mes_fin_mensualidades = date(2026, 12, 1)
        configuracion.save()
        cuenta = CuentaEquipo.objects.get(torneo=self.torneo, equipo=self.equipo)
        respuesta = self.client.post("/contabilidad/mensualidades/", {
            "cuenta_id": cuenta.id, "periodo": "2026-08", "valor": "40000",
            "fecha": "2026-08-05", "forma_pago": "Nequi", "observacion": "Primer abono",
        })
        self.assertEqual(respuesta.status_code, 302)
        pago = Ingreso.objects.get(tipo="MENSUALIDAD")
        self.assertEqual(pago.equipo, self.equipo)
        self.assertEqual(pago.periodo_mensualidad, date(2026, 8, 1))
        pagina = self.client.get("/contabilidad/mensualidades/?periodo=2026-08")
        fila = next(item for item in pagina.context["filas"] if item["cuenta"] == cuenta)
        self.assertEqual(fila["pagado"], Decimal("40000"))
        self.assertEqual(fila["pendiente"], Decimal("60000"))
        self.assertEqual(fila["estado"], "ABONO")

        self.client.post(f"/contabilidad/movimientos/ingreso/{pago.id}/anular/", {
            "motivo": "Pago registrado por error", "volver": "/contabilidad/mensualidades/?periodo=2026-08",
        })
        pagina = self.client.get("/contabilidad/mensualidades/?periodo=2026-08")
        fila = next(item for item in pagina.context["filas"] if item["cuenta"] == cuenta)
        self.assertEqual(fila["pagado"], Decimal("0"))
        self.assertEqual(fila["pendiente"], Decimal("100000"))
