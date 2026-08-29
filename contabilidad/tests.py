from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from torneos.models import Categoria, Equipo, Jugador, Organizador, Partido, Tarjeta, Torneo

from .models import (
    AbonoInscripcion, CobroTarjeta, Configuracion,
    ConfiguracionInscripcionCategoria, CuentaEquipo, Egreso, Ingreso, PagoTarjetas,
)
from .forms import EgresoForm, IngresoManualForm


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

    def test_doble_amarilla_se_cobra_unicamente_como_roja(self):
        self.client.post(
            f"/partido/{self.partido.id}/agregar-tarjeta-movil/",
            {"jugador": self.jugador.id, "equipo": self.equipo.id, "tipo": "AMARILLA", "minuto": 20},
        )
        self.client.post(
            f"/partido/{self.partido.id}/agregar-tarjeta-movil/",
            {"jugador": self.jugador.id, "equipo": self.equipo.id, "tipo": "AMARILLA", "minuto": 35},
        )

        tarjetas = Tarjeta.objects.filter(partido=self.partido, jugador=self.jugador)
        self.assertFalse(tarjetas.filter(tipo="AMARILLA").exists())
        self.assertEqual(tarjetas.filter(tipo="ROJA").count(), 1)
        cobros = CobroTarjeta.objects.filter(cuenta__equipo=self.equipo)
        self.assertEqual(cobros.count(), 1)
        self.assertEqual(cobros.get().tipo, "ROJA")
        self.assertEqual(cobros.get().valor, Decimal("8000"))

    def test_amarillas_en_partidos_distintos_se_acumulan_por_separado(self):
        segundo_partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.rival,
            fecha=date(2026, 1, 9),
            hora=time(16),
            estado="FINALIZADO",
        )
        for partido in (self.partido, segundo_partido):
            self.client.post(
                f"/partido/{partido.id}/agregar-tarjeta-movil/",
                {"jugador": self.jugador.id, "equipo": self.equipo.id, "tipo": "AMARILLA", "minuto": 20},
            )

        tarjetas = Tarjeta.objects.filter(jugador=self.jugador)
        self.assertEqual(tarjetas.filter(tipo="AMARILLA").count(), 2)
        self.assertFalse(tarjetas.filter(tipo="ROJA").exists())
        self.assertEqual(CobroTarjeta.objects.filter(tipo="AMARILLA").count(), 2)

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

    def test_abrir_tarjetas_repara_valores_historicos_desactualizados(self):
        tarjeta = Tarjeta.objects.create(
            partido=self.partido, jugador=self.jugador, equipo=self.equipo, tipo="AMARILLA"
        )
        cobro = CobroTarjeta.objects.get(tarjeta=tarjeta)
        configuracion = Configuracion.objects.get(torneo=self.torneo)
        configuracion.valor_amarilla = Decimal("4000")
        configuracion.save(update_fields=["valor_amarilla"])

        self.assertEqual(cobro.valor, Decimal("5000"))
        respuesta = self.client.get("/contabilidad/tarjetas/")

        self.assertEqual(respuesta.status_code, 200)
        cobro.refresh_from_db()
        self.assertEqual(cobro.valor, Decimal("4000"))
        self.assertContains(respuesta, "$ 4000")

    def test_interfaz_es_ruta_separada(self):
        respuesta = self.client.get("/contabilidad/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "CONTROL CONTABLE")
        self.assertNotContains(respuesta, 'class="category-accordion" open')
        self.assertContains(respuesta, 'class="configuration-disclosure"')
        self.assertNotContains(respuesta, 'class="configuration-disclosure" open')
        Configuracion.objects.get(torneo=self.torneo)

    def test_configurar_inscripcion_por_categoria_actualiza_todos_los_equipos(self):
        respuesta = self.client.post("/contabilidad/configurar/", {
            "valor_amarilla": "5000",
            "valor_roja": "8000",
            "valor_mensualidad": "0",
            "dia_limite_mensualidad": "10",
            f"valor_inscripcion_categoria_{self.categoria.id}": "175000",
        })

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            ConfiguracionInscripcionCategoria.objects.get(categoria=self.categoria).valor,
            Decimal("175000"),
        )
        self.assertFalse(
            CuentaEquipo.objects.filter(torneo=self.torneo, categoria=self.categoria)
            .exclude(valor_inscripcion=Decimal("175000")).exists()
        )
        self.assertEqual(Ingreso.objects.count(), 0)
        self.assertEqual(AbonoInscripcion.objects.count(), 0)

    def test_equipo_nuevo_hereda_inscripcion_configurada_de_su_categoria(self):
        ConfiguracionInscripcionCategoria.objects.create(
            torneo=self.torneo, categoria=self.categoria, valor=Decimal("210000"),
        )

        nuevo = Equipo.objects.create(nombre="Equipo Tres", categoria=self.categoria)

        self.assertEqual(
            CuentaEquipo.objects.get(torneo=self.torneo, equipo=nuevo).valor_inscripcion,
            Decimal("210000"),
        )

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
        self.assertEqual(pagina.context["totales"]["valor_amarillas"], Decimal("5000"))
        self.assertEqual(pagina.context["totales"]["valor_rojas"], Decimal("8000"))
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

    def test_ingreso_de_arbitraje_puede_asociarse_a_partidos(self):
        self.partido.estado = "PROGRAMADO"
        self.partido.save(update_fields=["estado"])
        respuesta = self.client.post("/contabilidad/ingresos/nuevo/", {
            "categoria": self.categoria.id,
            "concepto": "Pago de arbitraje",
            "partidos": [self.partido.id],
            "valor": "90000",
            "fecha": "2026-01-03",
            "forma_pago": "Efectivo",
            "detalle": "Recaudo de la fecha",
        })

        self.assertEqual(respuesta.status_code, 302)
        ingreso = Ingreso.objects.get(tipo="OTRO")
        self.assertEqual(list(ingreso.partidos.all()), [self.partido])
        pagina = self.client.get("/contabilidad/")
        self.assertContains(pagina, "Equipo Uno vs Equipo Dos")

    def test_registro_egreso_usa_listado_y_fondo_general(self):
        self.partido.estado = "PROGRAMADO"
        self.partido.save(update_fields=["estado"])
        respuesta = self.client.post("/contabilidad/egresos/nuevo/", {
            "categoria": "",
            "concepto": "Pago de árbitros",
            "partidos": [self.partido.id],
            "valor": "80000",
            "fecha": "2026-01-03",
            "forma_pago": "Efectivo",
            "observacion": "Fecha 1",
        })
        self.assertEqual(respuesta.status_code, 302)
        egreso = Egreso.objects.get()
        self.assertEqual(egreso.concepto, "Pago de árbitros")
        self.assertIsNone(egreso.categoria)
        self.assertEqual(list(egreso.partidos.all()), [self.partido])
        pagina = self.client.get("/contabilidad/")
        self.assertContains(pagina, "Equipo Uno vs Equipo Dos")

    def test_selector_de_partidos_esta_oculto_hasta_elegir_arbitraje(self):
        respuesta = self.client.get("/contabilidad/egresos/nuevo/")

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'class="form-field referee-parties-field" hidden')
        self.assertContains(respuesta, '"Pago de árbitros", "Pago de arbitraje"')

    def test_concepto_de_ingreso_y_egreso_no_selecciona_arbitraje_por_defecto(self):
        ingreso = IngresoManualForm(torneo=self.torneo)
        egreso = EgresoForm(torneo=self.torneo)

        self.assertEqual(ingreso.fields["concepto"].choices[0], ("", "Seleccione un concepto"))
        self.assertEqual(egreso.fields["concepto"].choices[0], ("", "Seleccione un concepto"))
        self.assertIsNone(ingreso["concepto"].value())
        self.assertIsNone(egreso["concepto"].value())

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_admin_ve_acceso_contable_en_torneos_del_organizador(self):
        organizador = Organizador.objects.create(nombre="Organizador contable")
        self.torneo.organizador = organizador
        self.torneo.save(update_fields=["organizador"])

        respuesta = self.client.get(f"/?portal=1&organizador={organizador.id}")

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "App contable")
        self.assertContains(respuesta, f'name="torneo_id" value="{self.torneo.id}"')

        self.client.logout()
        respuesta_publica = self.client.get(f"/?portal=1&organizador={organizador.id}")
        self.assertNotContains(respuesta_publica, "App contable")

    def test_egreso_muestra_partidos_pendientes_sin_pago_de_arbitros(self):
        self.partido.estado = "PROGRAMADO"
        self.partido.save(update_fields=["estado"])
        finalizado = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.rival,
            equipo_visitante=self.equipo,
            fecha=date(2026, 1, 4),
            hora=time(18),
            estado="FINALIZADO",
        )

        formulario = EgresoForm(torneo=self.torneo)
        self.assertEqual(
            list(formulario.fields["partidos"].queryset),
            [self.partido, finalizado],
        )

        egreso = Egreso.objects.create(
            torneo=self.torneo,
            concepto="Pago de árbitros",
            valor=Decimal("80000"),
            fecha=date(2026, 1, 3),
        )
        egreso.partidos.add(self.partido)

        formulario = EgresoForm(torneo=self.torneo)
        self.assertEqual(list(formulario.fields["partidos"].queryset), [finalizado])

    def test_ingreso_muestra_solo_programados_sin_recaudo_de_arbitraje(self):
        self.partido.estado = "PROGRAMADO"
        self.partido.save(update_fields=["estado"])

        ingreso = Ingreso.objects.create(
            torneo=self.torneo,
            tipo="OTRO",
            concepto="Pago de arbitraje",
            valor=Decimal("90000"),
            fecha=date(2026, 1, 3),
        )
        ingreso.partidos.add(self.partido)

        respuesta = self.client.get("/contabilidad/ingresos/nuevo/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.context["form"].fields["partidos"].queryset.exists())

    def test_listado_de_egresos_incluye_agua_cal_y_planillero(self):
        conceptos = {valor for valor, _ in EgresoForm(torneo=self.torneo).fields["concepto"].choices}

        self.assertIn("Compra de agua", conceptos)
        self.assertIn("Compra de cal", conceptos)
        self.assertIn("Pago de planillero", conceptos)

    def test_partidos_del_arbitraje_se_limit_an_al_torneo_contable(self):
        otro_torneo = Torneo.objects.create(nombre="Otro", fecha_inicio=date(2026, 2, 1))
        otra_categoria = Categoria.objects.create(
            nombre="Otra", torneo=otro_torneo, edad_minima=18, edad_maxima=70,
        )
        otro_local = Equipo.objects.create(nombre="Otro local", categoria=otra_categoria)
        otro_visitante = Equipo.objects.create(nombre="Otro visitante", categoria=otra_categoria)
        otro_partido = Partido.objects.create(
            categoria=otra_categoria, equipo_local=otro_local, equipo_visitante=otro_visitante,
            fecha=date(2026, 2, 2), hora=time(16),
        )

        respuesta = self.client.post("/contabilidad/egresos/nuevo/", {
            "categoria": "", "concepto": "Pago de árbitros",
            "partidos": [otro_partido.id], "valor": "80000",
            "fecha": "2026-01-03", "forma_pago": "Efectivo",
        })

        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Egreso.objects.exists())
        self.assertContains(respuesta, "Escoja una opción válida")

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
