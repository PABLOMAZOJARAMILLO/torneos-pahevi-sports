from datetime import date, time, timedelta
from io import BytesIO

from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook

from .forms import JugadorForm, PartidoForm
from .models import AlineacionPartido, AdminOrganizador, AdminTorneo, Categoria, Equipo, Gol, Jugador, Organizador, Partido, ReglaEdadCategoria, RegistroActividad, SustitucionPartido, Tarjeta, Torneo
from .planillas_pdf import _edad
from .views import buscar_planilleros_excel, construir_estructura, construir_estadisticas_foraneos, construir_partidos_portada, construir_partidos_programacion, _clave_orden_evento_resumen, _minuto_evento_en_vivo, _sincronizar_no_disponibles_por_tarjetas, etiqueta_edad_jugador, texto_edad_jugador, validar_reglas_edad_titulares


class SancionesTarjetasTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.equipo = Equipo.objects.create(nombre="Paraiso", categoria=self.categoria)
        self.rival = Equipo.objects.create(nombre="Integracion", categoria=self.categoria)
        self.jugador = Jugador.objects.create(
            equipo=self.equipo,
            dorsal=10,
            nombres="Jugador Sancionado",
            cedula="100",
            fecha_nacimiento=date(1990, 1, 1),
        )

    def crear_partido(self, dia, fase="GRUPOS", estado="FINALIZADO"):
        return Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.rival,
            fecha=date(2026, 5, dia),
            hora=time(15, 0),
            estado=estado,
            fase=fase,
            numero_fecha=str(dia),
        )

    def assert_no_disponible_en(self, partido):
        _sincronizar_no_disponibles_por_tarjetas(partido)
        self.assertTrue(
            AlineacionPartido.objects.filter(
                partido=partido,
                jugador=self.jugador,
                equipo=self.equipo,
                rol="NO_DISPONIBLE",
            ).exists()
        )

    def test_roja_directa_deja_no_disponible_en_siguiente_partido(self):
        partido_origen = self.crear_partido(1)
        Tarjeta.objects.create(
            partido=partido_origen,
            jugador=self.jugador,
            equipo=self.equipo,
            tipo="ROJA",
        )
        siguiente = self.crear_partido(8, estado="PROGRAMADO")

        self.assert_no_disponible_en(siguiente)

    def test_doble_amarilla_deja_no_disponible_en_siguiente_partido(self):
        partido_origen = self.crear_partido(1)
        for _ in range(2):
            Tarjeta.objects.create(
                partido=partido_origen,
                jugador=self.jugador,
                equipo=self.equipo,
                tipo="AMARILLA",
            )
        siguiente = self.crear_partido(8, estado="PROGRAMADO")

        self.assert_no_disponible_en(siguiente)

    def test_tres_amarillas_en_partidos_distintos_de_fase_uno_sancionan(self):
        for dia in [1, 8, 15]:
            partido = self.crear_partido(dia)
            Tarjeta.objects.create(
                partido=partido,
                jugador=self.jugador,
                equipo=self.equipo,
                tipo="AMARILLA",
            )
        siguiente = self.crear_partido(22, fase="CUARTOS", estado="PROGRAMADO")

        self.assert_no_disponible_en(siguiente)


class ResumenPartidoOrdenTests(TestCase):
    def test_muestra_ultimo_movimiento_arriba(self):
        base = timezone.now()
        eventos = [
            SimpleNamespace(minuto=None, creado_en=base, orden=1),
            SimpleNamespace(minuto=15, creado_en=base, orden=3),
            SimpleNamespace(minuto=15, creado_en=base + timedelta(seconds=5), orden=2),
            SimpleNamespace(minuto=None, creado_en=base + timedelta(seconds=10), orden=4),
        ]

        ordenados = sorted(eventos, key=_clave_orden_evento_resumen, reverse=True)

        self.assertEqual([evento.orden for evento in ordenados], [2, 3, 4, 1])


class CronometroEventoTests(TestCase):
    def test_minuto_evento_coincide_con_minuto_visible_del_cronometro(self):
        partido = SimpleNamespace(
            estado="EN_JUEGO",
            segundos_acumulados=(16 * 60) + 42,
            inicio_en_vivo=None,
            cronometro_pausado=True,
        )

        self.assertEqual(_minuto_evento_en_vivo(partido), 16)

    def test_minuto_evento_no_baja_de_uno_al_inicio(self):
        partido = SimpleNamespace(
            estado="EN_JUEGO",
            segundos_acumulados=30,
            inicio_en_vivo=None,
            cronometro_pausado=True,
        )

        self.assertEqual(_minuto_evento_en_vivo(partido), 1)

    def test_sustitucion_sin_minuto_usa_cronometro(self):
        torneo = Torneo.objects.create(nombre="Veranero", fecha_inicio=date(2026, 1, 1))
        categoria = Categoria.objects.create(nombre="Senior", edad_minima=18, edad_maxima=60, torneo=torneo)
        equipo = Equipo.objects.create(nombre="Local", categoria=categoria)
        rival = Equipo.objects.create(nombre="Visitante", categoria=categoria)
        jugador_sale = Jugador.objects.create(equipo=equipo, nombres="Sale Uno", cedula="1", fecha_nacimiento=date(1990, 1, 1))
        jugador_entra = Jugador.objects.create(equipo=equipo, nombres="Entra Uno", cedula="2", fecha_nacimiento=date(1991, 1, 1))
        partido = Partido.objects.create(
            categoria=categoria,
            equipo_local=equipo,
            equipo_visitante=rival,
            fecha=date(2026, 6, 1),
            hora=time(16, 0),
            estado="EN_JUEGO",
            segundos_acumulados=(39 * 60) + 33,
            cronometro_pausado=True,
        )
        admin = User.objects.create_user("admin-crono", password="test", is_staff=True, is_superuser=True)

        self.client.force_login(admin)
        respuesta = self.client.post(
            f"/partido/{partido.id}/agregar-sustitucion-movil/",
            {
                "equipo": str(equipo.id),
                "jugador_sale": str(jugador_sale.id),
                "jugador_entra": str(jugador_entra.id),
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        sustitucion = SustitucionPartido.objects.get(partido=partido)
        self.assertEqual(sustitucion.minuto, 39)


class TablaPosicionesWoTests(TestCase):
    def test_partido_wo_suma_en_tabla(self):
        torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=torneo,
        )
        ganador = Equipo.objects.create(nombre="Ganador WO", categoria=categoria)
        perdedor = Equipo.objects.create(nombre="No Presentado", categoria=categoria)
        Partido.objects.create(
            categoria=categoria,
            equipo_local=ganador,
            equipo_visitante=perdedor,
            fecha=date(2026, 5, 1),
            hora=time(15, 0),
            estado="WO",
            fase="GRUPOS",
            grupo="A",
            numero_fecha="1",
            goles_local=3,
            goles_visitante=-3,
        )

        tabla = construir_estructura(torneo)["Senior"]["grupos"]["A"]["tabla"]
        fila_ganador = next(fila for fila in tabla if fila["id"] == ganador.id)
        fila_perdedor = next(fila for fila in tabla if fila["id"] == perdedor.id)

        self.assertEqual(fila_ganador["pj"], 1)
        self.assertEqual(fila_ganador["pg"], 1)
        self.assertEqual(fila_ganador["pts"], 3)
        self.assertEqual(fila_ganador["gf"], 3)
        self.assertEqual(fila_ganador["gc"], -3)
        self.assertEqual(fila_ganador["dg"], 6)
        self.assertEqual(fila_perdedor["pp"], 1)
        self.assertEqual(fila_perdedor["pts"], 0)


class ReglasEdadCategoriaTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        self.categoria = Categoria.objects.create(
            nombre="Senior Master",
            edad_minima=40,
            edad_maxima=80,
            torneo=self.torneo,
        )
        self.equipo = Equipo.objects.create(nombre="Paraiso", categoria=self.categoria)
        self.rival = Equipo.objects.create(nombre="Integracion", categoria=self.categoria)
        self.partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.rival,
            fecha=date(2026, 5, 1),
            hora=time(15, 0),
            estado="PROGRAMADO",
        )
        ReglaEdadCategoria.objects.create(
            categoria=self.categoria,
            etiqueta="+40",
            edad_minima=40,
            edad_maxima=44,
            maximo_titulares=4,
            orden=1,
        )
        ReglaEdadCategoria.objects.create(
            categoria=self.categoria,
            etiqueta="+45",
            edad_minima=45,
            edad_maxima=49,
            minimo_titulares=4,
            orden=2,
        )
        ReglaEdadCategoria.objects.create(
            categoria=self.categoria,
            etiqueta="+50",
            edad_minima=50,
            minimo_titulares=3,
            orden=3,
        )

    def crear_jugador(self, indice, nacimiento):
        return Jugador.objects.create(
            equipo=self.equipo,
            dorsal=indice,
            nombres=f"Jugador {indice}",
            cedula=f"EDAD{indice}",
            fecha_nacimiento=nacimiento,
        )

    def test_etiqueta_edad_se_calcula_con_fecha_del_partido(self):
        jugador = self.crear_jugador(1, date(1981, 5, 2))

        self.assertEqual(etiqueta_edad_jugador(jugador, self.categoria, self.partido.fecha), "+40")

    def test_edad_planilla_se_calcula_con_fecha_actual(self):
        hoy = date.today()
        nacimiento = hoy.replace(year=hoy.year - 41)

        self.assertEqual(_edad(nacimiento), "41")

    def test_valida_reglas_senior_master_con_reemplazos(self):
        jugadores = []
        for indice in range(1, 4):
            jugadores.append(self.crear_jugador(indice, date(1983, 1, 1)))
        for indice in range(4, 8):
            jugadores.append(self.crear_jugador(indice, date(1978, 1, 1)))
        for indice in range(8, 12):
            jugadores.append(self.crear_jugador(indice, date(1970, 1, 1)))

        errores = validar_reglas_edad_titulares(
            self.partido,
            self.equipo,
            [str(jugador.id) for jugador in jugadores],
        )

        self.assertEqual(errores, [])

    def test_reporta_maximo_de_cuarenta_en_cancha(self):
        jugadores = []
        for indice in range(1, 6):
            jugadores.append(self.crear_jugador(indice, date(1983, 1, 1)))
        for indice in range(6, 9):
            jugadores.append(self.crear_jugador(indice, date(1978, 1, 1)))
        for indice in range(9, 12):
            jugadores.append(self.crear_jugador(indice, date(1970, 1, 1)))

        errores = validar_reglas_edad_titulares(
            self.partido,
            self.equipo,
            [str(jugador.id) for jugador in jugadores],
        )

        self.assertTrue(any("+40" in error and "maximo 4" in error for error in errores))

    def test_cincuenta_reemplaza_cupo_de_cuarenta_y_cinco(self):
        jugadores = []
        for indice in range(1, 5):
            jugadores.append(self.crear_jugador(indice, date(1983, 1, 1)))
        for indice in range(5, 8):
            jugadores.append(self.crear_jugador(indice, date(1978, 1, 1)))
        for indice in range(8, 12):
            jugadores.append(self.crear_jugador(indice, date(1970, 1, 1)))

        errores = validar_reglas_edad_titulares(
            self.partido,
            self.equipo,
            [str(jugador.id) for jugador in jugadores],
        )

        self.assertEqual(errores, [])

    def test_reporta_regla_incompleta_con_once_titulares(self):
        jugadores = []
        for indice in range(1, 5):
            jugadores.append(self.crear_jugador(indice, date(1983, 1, 1)))
        for indice in range(5, 7):
            jugadores.append(self.crear_jugador(indice, date(1978, 1, 1)))
        for indice in range(7, 10):
            jugadores.append(self.crear_jugador(indice, date(1970, 1, 1)))
        for indice in range(10, 12):
            jugadores.append(self.crear_jugador(indice, date(1988, 1, 1)))

        errores = validar_reglas_edad_titulares(
            self.partido,
            self.equipo,
            [str(jugador.id) for jugador in jugadores],
        )

        self.assertTrue(any("+45" in error for error in errores))


class ForaneosTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(
            nombre="IMCRED",
            fecha_inicio=date(2026, 1, 1),
        )
        self.categoria = Categoria.objects.create(
            nombre="Senior Master",
            edad_minima=40,
            edad_maxima=80,
            torneo=self.torneo,
            controlar_foraneos=True,
            porcentaje_minimo_foraneos=50,
        )
        self.equipo = Equipo.objects.create(nombre="Paraiso", categoria=self.categoria)
        self.rival = Equipo.objects.create(nombre="Integracion", categoria=self.categoria)
        self.foraneo = Jugador.objects.create(
            equipo=self.equipo,
            dorsal=9,
            nombres="Jugador Foraneo",
            cedula="F1",
            fecha_nacimiento=date(1970, 1, 1),
            es_foraneo=True,
        )
        self.titular = Jugador.objects.create(
            equipo=self.equipo,
            dorsal=10,
            nombres="Jugador Titular",
            cedula="T1",
            fecha_nacimiento=date(1970, 1, 1),
        )

    def crear_partido(self, dia):
        return Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.rival,
            fecha=date(2026, 5, dia),
            hora=time(15, 0),
            estado="FINALIZADO",
            fase="GRUPOS",
            numero_fecha=str(dia),
        )

    def test_minimo_foraneo_redondea_hacia_abajo(self):
        for dia in [1, 8, 15, 22, 29, 30, 31]:
            self.crear_partido(dia)

        fila = construir_estadisticas_foraneos(self.categoria)[0]

        self.assertEqual(fila["partidos_fase1"], 7)
        self.assertEqual(fila["minimo"], 3)

    def test_cuenta_titular_y_suplente_que_entra(self):
        partido_uno = self.crear_partido(1)
        partido_dos = self.crear_partido(8)
        AlineacionPartido.objects.create(
            partido=partido_uno,
            equipo=self.equipo,
            jugador=self.foraneo,
            rol="TITULAR",
        )
        SustitucionPartido.objects.create(
            partido=partido_dos,
            equipo=self.equipo,
            jugador_sale=self.titular,
            jugador_entra=self.foraneo,
        )

        fila = construir_estadisticas_foraneos(self.categoria)[0]

        self.assertEqual(fila["jugados"], 2)
        self.assertTrue(fila["cumple"])


class JugadorFormTests(TestCase):
    def test_fecha_nacimiento_se_renderiza_en_formato_html_date(self):
        torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=torneo,
        )
        equipo = Equipo.objects.create(nombre="Paraiso", categoria=categoria)
        jugador = Jugador.objects.create(
            equipo=equipo,
            dorsal=31,
            nombres="Ilario Rodriguez",
            cedula="15679719",
            fecha_nacimiento=date(1980, 5, 7),
        )

        html = str(JugadorForm(instance=jugador))

        self.assertIn('value="1980-05-07"', html)


class PlanilleroPartidoTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.local = Equipo.objects.create(nombre="Local", categoria=self.categoria)
        self.visitante = Equipo.objects.create(nombre="Visitante", categoria=self.categoria)
        self.jugador = Jugador.objects.create(
            equipo=self.local,
            dorsal=9,
            nombres="Planillero Gol",
            cedula="PG1",
            fecha_nacimiento=date(1990, 1, 1),
        )
        self.partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.local,
            equipo_visitante=self.visitante,
            fecha=date(2026, 5, 1),
            hora=time(15, 0),
            estado="PROGRAMADO",
        )
        self.planillero = User.objects.create_user("planillero", password="test")
        self.otro_usuario = User.objects.create_user("otro", password="test")
        self.admin = User.objects.create_user("admin", password="test", is_staff=True)
        AdminTorneo.objects.create(usuario=self.admin, torneo=self.torneo)
        self.partido.planilleros.add(self.planillero)

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_planillero_asignado_puede_abrir_editor(self):
        self.client.force_login(self.planillero)

        respuesta = self.client.get(f"/partido/{self.partido.id}/editor-movil/")

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Resultado del partido")
        self.assertNotContains(respuesta, 'name="cancha"')

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_editor_movil_muestra_edad_en_alineacion(self):
        self.client.force_login(self.planillero)

        respuesta = self.client.get(f"/partido/{self.partido.id}/editor-movil/")

        self.assertContains(respuesta, "36 años")

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_editor_movil_actualiza_edad_despues_del_cumpleanos(self):
        hoy = date.today()
        self.jugador.fecha_nacimiento = hoy.replace(year=hoy.year - 41)
        self.jugador.save(update_fields=["fecha_nacimiento"])
        self.partido.fecha = hoy - timedelta(days=1)
        self.partido.save(update_fields=["fecha"])
        self.client.force_login(self.planillero)

        respuesta = self.client.get(f"/partido/{self.partido.id}/editor-movil/")

        self.assertContains(respuesta, "41 a")

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_editor_movil_muestra_rango_edad_en_selector_y_cancha(self):
        hoy = date.today()
        self.jugador.fecha_nacimiento = hoy.replace(year=hoy.year - 41)
        self.jugador.save(update_fields=["fecha_nacimiento"])
        ReglaEdadCategoria.objects.create(
            categoria=self.categoria,
            etiqueta="+40",
            edad_minima=40,
            edad_maxima=44,
        )
        self.client.force_login(self.planillero)

        respuesta = self.client.get(f"/partido/{self.partido.id}/editor-movil/")

        self.assertContains(respuesta, "(+40)")
        self.assertContains(respuesta, "return rango ? corto")

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_planillero_ve_mensaje_de_acceso_exitoso_al_ingresar(self):
        respuesta = self.client.post(
            f"/ingresar/?next=/partido/{self.partido.id}/editor-movil/",
            {
                "username": "planillero",
                "password": "test",
                "next": f"/partido/{self.partido.id}/editor-movil/",
            },
            follow=True,
        )

        self.assertContains(respuesta, "Acceso exitoso. Ya puedes diligenciar tus partidos asignados.")

    def test_login_no_precarga_usuario_y_desactiva_autocompletado(self):
        respuesta = self.client.get("/ingresar/")

        self.assertContains(respuesta, 'name="username"')
        self.assertContains(respuesta, 'autocomplete="off"')
        self.assertContains(respuesta, 'autocomplete="new-password"')
        self.assertNotContains(respuesta, 'value="pablo"')

    def test_usuario_no_asignado_no_puede_abrir_editor(self):
        self.client.force_login(self.otro_usuario)

        respuesta = self.client.get(f"/partido/{self.partido.id}/editor-movil/")

        self.assertEqual(respuesta.status_code, 403)

    def test_planillero_asignado_puede_registrar_gol(self):
        self.client.force_login(self.planillero)

        respuesta = self.client.post(
            f"/partido/{self.partido.id}/agregar-gol-movil/",
            {
                "equipo": self.local.id,
                "jugador": self.jugador.id,
                "cantidad": 1,
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Gol.objects.filter(partido=self.partido, jugador=self.jugador).exists())
        self.partido.refresh_from_db()
        self.assertFalse(self.partido.estadisticas_validadas)

    def test_planillero_no_puede_marcar_wo(self):
        self.client.force_login(self.planillero)

        self.client.post(
            f"/partido/{self.partido.id}/guardar-info-movil/",
            {
                "goles_local": 3,
                "goles_visitante": -3,
                "estado": "WO",
            },
        )

        self.partido.refresh_from_db()
        self.assertEqual(self.partido.estado, "PROGRAMADO")
        self.assertEqual(self.partido.goles_visitante, 0)

    def test_planillero_pierde_acceso_cuando_finaliza_partido(self):
        self.client.force_login(self.planillero)

        respuesta = self.client.post(
            f"/partido/{self.partido.id}/guardar-info-movil/",
            {
                "goles_local": 2,
                "goles_visitante": 1,
                "estado": "FINALIZADO",
            },
        )

        self.partido.refresh_from_db()
        self.assertEqual(self.partido.estado, "FINALIZADO")
        self.assertRedirects(respuesta, f"/partido/{self.partido.id}/live/", fetch_redirect_response=False)

        respuesta_editor = self.client.get(f"/partido/{self.partido.id}/editor-movil/")
        self.assertEqual(respuesta_editor.status_code, 403)

    def test_estadisticas_pendientes_no_entran_a_tabla_ni_goleadores(self):
        self.partido.estado = "FINALIZADO"
        self.partido.goles_local = 2
        self.partido.goles_visitante = 0
        self.partido.estadisticas_validadas = False
        self.partido.save()
        Gol.objects.create(partido=self.partido, equipo=self.local, jugador=self.jugador, cantidad=2)

        estructura = construir_estructura(self.torneo)
        datos = estructura["Senior"]["grupos"]["SIN GRUPO"]
        fila_local = next(fila for fila in datos["tabla"] if fila["id"] == self.local.id)

        self.assertEqual(fila_local["pj"], 0)
        self.assertEqual(estructura["Senior"]["goleadores_planilla"], [])

    def test_admin_valida_estadisticas_y_entran_a_reportes(self):
        self.partido.estado = "FINALIZADO"
        self.partido.goles_local = 2
        self.partido.goles_visitante = 0
        self.partido.estadisticas_validadas = False
        self.partido.save()
        Gol.objects.create(partido=self.partido, equipo=self.local, jugador=self.jugador, cantidad=2)
        self.client.force_login(self.admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.post(f"/gestion/partidos/{self.partido.id}/validar-estadisticas/")

        self.assertEqual(respuesta.status_code, 302)
        self.partido.refresh_from_db()
        self.assertTrue(self.partido.estadisticas_validadas)
        estructura = construir_estructura(self.torneo)
        fila_local = next(fila for fila in estructura["Senior"]["grupos"]["SIN GRUPO"]["tabla"] if fila["id"] == self.local.id)
        self.assertEqual(fila_local["pj"], 1)
        self.assertEqual(estructura["Senior"]["goleadores_planilla"][0]["total"], 2)


class AdminTorneoPermisosTests(TestCase):
    def setUp(self):
        self.organizador = Organizador.objects.create(nombre="Liga Pahevi")
        self.otro_organizador = Organizador.objects.create(nombre="Otra Liga")
        self.torneo = Torneo.objects.create(nombre="Autorizado", organizador=self.organizador, fecha_inicio=date(2026, 1, 1))
        self.otro_torneo = Torneo.objects.create(nombre="Bloqueado", fecha_inicio=date(2026, 2, 1))
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.otra_categoria = Categoria.objects.create(
            nombre="Libre",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.otro_torneo,
        )
        self.equipo = Equipo.objects.create(nombre="Permitido", categoria=self.categoria)
        self.otro_equipo = Equipo.objects.create(nombre="Privado", categoria=self.otra_categoria)
        self.admin = User.objects.create_user("admin-torneo", password="test", is_staff=True)
        AdminTorneo.objects.create(usuario=self.admin, torneo=self.torneo, puede_editar=True, puede_validar=False, puede_programar=False)

    def test_admin_solo_ve_torneos_asignados(self):
        self.client.force_login(self.admin)

        respuesta = self.client.get("/gestion/torneos/")

        self.assertContains(respuesta, "Autorizado")
        self.assertNotContains(respuesta, "Bloqueado")

    def test_admin_no_puede_editar_equipo_de_otro_torneo_por_url(self):
        self.client.force_login(self.admin)

        respuesta = self.client.get(f"/gestion/equipos/{self.otro_equipo.id}/editar/")

        self.assertEqual(respuesta.status_code, 404)

    def test_admin_asignado_registra_actividad_al_editar_equipo(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.post(
            f"/gestion/equipos/{self.equipo.id}/editar/",
            {
                "nombre": "Permitido FC",
                "categoria": self.categoria.id,
                "activo": "on",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(
            RegistroActividad.objects.filter(
                usuario=self.admin,
                torneo=self.torneo,
                accion="EDITAR",
                modelo="Equipo",
            ).exists()
        )

    def test_admin_sin_permiso_de_validar_no_valida_estadisticas(self):
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=Equipo.objects.create(nombre="Rival", categoria=self.categoria),
            fecha=date(2026, 5, 1),
            hora=time(15, 0),
            estado="FINALIZADO",
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.post(f"/gestion/partidos/{partido.id}/validar-estadisticas/")

        self.assertEqual(respuesta.status_code, 403)

    def test_admin_de_organizador_ve_torneos_del_organizador(self):
        torneo_organizador = Torneo.objects.create(
            nombre="Segundo del organizador",
            organizador=self.organizador,
            fecha_inicio=date(2026, 3, 1),
        )
        admin = User.objects.create_user("admin-organizador", password="test", is_staff=True)
        AdminOrganizador.objects.create(usuario=admin, organizador=self.organizador)
        self.client.force_login(admin)

        respuesta = self.client.get("/gestion/torneos/")

        self.assertContains(respuesta, "Autorizado")
        self.assertContains(respuesta, torneo_organizador.nombre)
        self.assertNotContains(respuesta, "Bloqueado")

    def test_admin_de_organizador_accede_torneo_creado_despues(self):
        admin = User.objects.create_user("admin-organizador-futuro", password="test", is_staff=True)
        AdminOrganizador.objects.create(usuario=admin, organizador=self.organizador)
        torneo_nuevo = Torneo.objects.create(
            nombre="Torneo futuro",
            organizador=self.organizador,
            fecha_inicio=date(2026, 4, 1),
        )
        categoria_nueva = Categoria.objects.create(
            nombre="Futuro",
            edad_minima=18,
            edad_maxima=60,
            torneo=torneo_nuevo,
        )
        Equipo.objects.create(nombre="Equipo Futuro", categoria=categoria_nueva)
        self.client.force_login(admin)
        session = self.client.session
        session["torneo_id"] = torneo_nuevo.id
        session.save()

        respuesta = self.client.get("/gestion/equipos/")

        self.assertContains(respuesta, "Equipo Futuro")

    def test_admin_torneo_solo_planillas_entra_a_gestion_al_ingresar(self):
        admin = User.objects.create_user("admin-planillas", password="test")
        AdminTorneo.objects.create(
            usuario=admin,
            torneo=self.torneo,
            puede_editar=False,
            puede_validar=False,
            puede_programar=False,
            puede_descargar_planillas=True,
        )

        respuesta = self.client.post(
            "/ingresar/",
            {
                "username": "admin-planillas",
                "password": "test",
            },
        )

        self.assertRedirects(respuesta, "/gestion/", fetch_redirect_response=False)

    def test_admin_torneo_no_staff_solo_planillas_puede_ver_gestion(self):
        admin = User.objects.create_user("admin-planillas-no-staff", password="test")
        AdminTorneo.objects.create(
            usuario=admin,
            torneo=self.torneo,
            puede_editar=False,
            puede_validar=False,
            puede_programar=False,
            puede_descargar_planillas=True,
        )
        self.client.force_login(admin)

        respuesta = self.client.get("/gestion/")

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Partidos")
        self.assertContains(respuesta, "Descargar planillas de impresion")

    def test_admin_programador_no_ve_editor_juego_en_partidos(self):
        admin = User.objects.create_user("admin-programa", password="test")
        AdminTorneo.objects.create(
            usuario=admin,
            torneo=self.torneo,
            puede_editar=False,
            puede_validar=False,
            puede_programar=True,
            puede_descargar_planillas=True,
        )
        Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=Equipo.objects.create(nombre="Rival", categoria=self.categoria),
            fecha=date(2026, 5, 1),
            hora=time(15, 0),
            estado="PROGRAMADO",
        )
        self.client.force_login(admin)

        respuesta = self.client.get("/gestion/partidos/")

        self.assertContains(respuesta, "Programar")
        self.assertNotContains(respuesta, "Editor juego")

    def test_programar_partido_no_muestra_campos_de_resultado(self):
        admin = User.objects.create_user("admin-programa-form", password="test")
        AdminTorneo.objects.create(
            usuario=admin,
            torneo=self.torneo,
            puede_editar=False,
            puede_validar=False,
            puede_programar=True,
            puede_descargar_planillas=True,
        )
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=Equipo.objects.create(nombre="Rival Form", categoria=self.categoria),
            fecha=date(2026, 5, 1),
            hora=time(15, 0),
            estado="PROGRAMADO",
        )
        self.client.force_login(admin)

        respuesta = self.client.get(f"/gestion/partidos/{partido.id}/editar/")

        self.assertContains(respuesta, "Programar partido")
        self.assertNotContains(respuesta, 'name="goles_local"')
        self.assertNotContains(respuesta, 'name="goles_visitante"')
        self.assertNotContains(respuesta, 'name="ajuste_puntos_local"')
        self.assertNotContains(respuesta, 'name="ajuste_puntos_visitante"')
        self.assertNotContains(respuesta, 'name="goles_local_penales"')
        self.assertNotContains(respuesta, 'name="goles_visitante_penales"')
        self.assertNotContains(respuesta, 'name="estadisticas_validadas"')

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_admin_asignado_regresa_del_panel_a_gestion_sin_nuevo_login(self):
        admin = User.objects.create_user("admin-regresa", password="test")
        AdminTorneo.objects.create(
            usuario=admin,
            torneo=self.torneo,
            puede_editar=False,
            puede_validar=False,
            puede_programar=True,
            puede_descargar_planillas=True,
        )
        self.client.force_login(admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.get("/")

        self.assertContains(respuesta, 'href="/gestion/"')
        self.assertNotContains(respuesta, "Ingresar admin")
        self.assertIn("_auth_user_id", self.client.session)


class FixtureProgramacionBalanceadaTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(nombre="Programacion", fecha_inicio=date(2026, 1, 1))
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.equipos = [
            Equipo.objects.create(nombre=f"Equipo {indice}", categoria=self.categoria)
            for indice in range(1, 5)
        ]
        self.admin = User.objects.create_user("super", password="test", is_staff=True, is_superuser=True)

    def datos_fixture(self, programacion=False):
        datos = {
            "categoria": self.categoria.id,
            "grupos": 1,
            "reemplazar": "on",
        }
        for equipo in self.equipos:
            datos.setdefault("equipos_grupo_0", []).append(str(equipo.id))
        if programacion:
            datos.update({
                "generar_programacion": "on",
                "fecha_inicio_programacion": "2026-06-06",
                "canchas_programacion": "Principal\r\nPorvenir",
                "cancha_obligatoria": "Porvenir",
                "franjas_programacion": ["SAB_16", "SAB_18", "DOM_08", "DOM_10", "DOM_14", "DOM_16"],
            })
        return datos

    def test_fixture_sin_programacion_mantiene_comportamiento_actual(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post("/gestion/generar-fixture/", self.datos_fixture())

        self.assertEqual(respuesta.status_code, 200)
        partidos = Partido.objects.filter(categoria=self.categoria)
        self.assertEqual(partidos.count(), 6)
        self.assertTrue(all(partido.cancha == "" for partido in partidos))
        self.assertTrue(all(partido.hora == time(0, 0) for partido in partidos))
        self.assertTrue(all(partido.estado_programacion == "MANUAL" for partido in partidos))

    def test_portada_distingue_programados_reales_de_futuros_sin_programar(self):
        programado = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipos[0],
            equipo_visitante=self.equipos[1],
            fecha=date.today() + timedelta(days=30),
            hora=time(16, 0),
            cancha="Porvenir",
            estado="PROGRAMADO",
            numero_fecha="1",
            grupo="A",
        )
        futuro = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipos[2],
            equipo_visitante=self.equipos[3],
            fecha=date.today() + timedelta(days=30),
            hora=time(0, 0),
            cancha="",
            estado="PROGRAMADO",
            numero_fecha="1",
            grupo="A",
        )

        partidos_portada = {partido["id"]: partido for partido in construir_partidos_portada(self.torneo)}

        self.assertEqual(partidos_portada[programado.id]["bloque"], "PROGRAMADOS")
        self.assertEqual(partidos_portada[futuro.id]["bloque"], "FUTUROS")

    def test_fixture_con_programacion_balancea_cancha_obligatoria(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post("/gestion/generar-fixture/", self.datos_fixture(programacion=True))

        self.assertContains(respuesta, "Resumen de equidad")
        partidos = Partido.objects.filter(categoria=self.categoria)
        self.assertEqual(partidos.count(), 6)
        self.assertTrue(all(partido.cancha in ["Principal", "Porvenir"] for partido in partidos))
        self.assertTrue(all(partido.hora != time(0, 0) for partido in partidos))
        self.assertTrue(all(partido.estado_programacion == "SUGERIDA" for partido in partidos))

        apariciones_porvenir = {equipo.id: 0 for equipo in self.equipos}
        for partido in partidos.filter(cancha__iexact="Porvenir"):
            apariciones_porvenir[partido.equipo_local_id] += 1
            apariciones_porvenir[partido.equipo_visitante_id] += 1

        self.assertTrue(all(cantidad >= 1 for cantidad in apariciones_porvenir.values()))

    def test_descarga_programacion_excluye_partidos_sugeridos(self):
        self.client.force_login(self.admin)
        self.client.post("/gestion/generar-fixture/", self.datos_fixture(programacion=True))
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        request = self.client.get("/gestion/partidos/").wsgi_request
        partidos = construir_partidos_programacion(request, self.categoria)

        self.assertEqual(partidos, [])

    def test_confirmar_programacion_vuelve_partido_oficial(self):
        self.client.force_login(self.admin)
        self.client.post("/gestion/generar-fixture/", self.datos_fixture(programacion=True))
        partido = Partido.objects.filter(categoria=self.categoria).first()

        respuesta = self.client.post(f"/gestion/partidos/{partido.id}/confirmar-programacion/")

        self.assertEqual(respuesta.status_code, 302)
        partido.refresh_from_db()
        self.assertEqual(partido.estado_programacion, "OFICIAL")


class ImportacionPartidosPlanillerosTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(nombre="Veranero", fecha_inicio=date(2026, 1, 1))
        self.categoria = Categoria.objects.create(
            nombre="Senior Master",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.local = Equipo.objects.create(nombre="Local", categoria=self.categoria)
        self.visitante = Equipo.objects.create(nombre="Visitante", categoria=self.categoria)
        self.admin = User.objects.create_user("admin-importa", password="test", is_staff=True, is_superuser=True)

    def test_busca_planilleros_por_usuario_correo_y_nombre(self):
        usuario = User.objects.create_user(
            "planilla1",
            email="planilla1@example.com",
            password="test",
            first_name="Carlos",
            last_name="Planillero",
        )
        otro = User.objects.create_user("planilla2", email="planilla2@example.com", password="test")

        planilleros, no_encontrados = buscar_planilleros_excel(
            "planilla1; planilla2@example.com; Carlos Planillero; noexiste"
        )

        self.assertEqual(planilleros, [usuario, otro])
        self.assertEqual(no_encontrados, ["noexiste"])

    def test_busca_planillero_ignorando_espacios_en_usuario(self):
        usuario = User.objects.create_user("Planillero 1", password="test")

        planilleros, no_encontrados = buscar_planilleros_excel("planillero1")

        self.assertEqual(planilleros, [usuario])
        self.assertEqual(no_encontrados, [])

    def test_importacion_asigna_planillero_desde_columna_planilleros(self):
        planillero = User.objects.create_user("Planillero 1", password="test")
        workbook = Workbook()
        hoja = workbook.active
        hoja.append([
            "categoria",
            "equipo_local",
            "equipo_visitante",
            "fecha",
            "hora",
            "numero_fecha",
            "grupo",
            "cancha",
            "fase",
            "estado",
            "planilleros",
        ])
        hoja.append([
            self.categoria.nombre,
            self.local.nombre,
            self.visitante.nombre,
            date(2026, 6, 1),
            time(16, 0),
            "1",
            "A",
            "Porvenir",
            "GRUPOS",
            "PROGRAMADO",
            "planillero1",
        ])
        archivo = BytesIO()
        workbook.save(archivo)
        archivo.seek(0)

        self.client.force_login(self.admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()
        respuesta = self.client.post(
            "/gestion/partidos/importar/",
            {
                "archivo_excel": SimpleUploadedFile(
                    "partidos.xlsx",
                    archivo.read(),
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        partido = Partido.objects.get(categoria=self.categoria, equipo_local=self.local, equipo_visitante=self.visitante)
        self.assertEqual(list(partido.planilleros.all()), [planillero])


class PartidoFormTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(nombre="Veranero", fecha_inicio=date(2026, 1, 1))
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.local = Equipo.objects.create(nombre="Local", categoria=self.categoria)
        self.visitante = Equipo.objects.create(nombre="Visitante", categoria=self.categoria)
        self.planillero = User.objects.create_user("planillero1", password="test")
        self.planillero_no_asignado = User.objects.create_user("planillero2", password="test")
        self.admin = User.objects.create_user("admin-torneo", password="test", is_staff=True)
        self.admin_asignado = User.objects.create_user("admin-asignado", password="test", is_staff=True)
        self.partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.local,
            equipo_visitante=self.visitante,
            fecha=date(2026, 6, 1),
            hora=time(16, 0),
            estado="PROGRAMADO",
            numero_fecha="1",
            grupo="A",
            cancha="Porvenir",
        )
        self.partido.planilleros.add(self.planillero, self.admin_asignado)

    def test_fecha_se_renderiza_en_formato_html_date(self):
        form = PartidoForm(instance=self.partido, torneo=self.torneo)

        self.assertIn('value="2026-06-01"', str(form["fecha"]))

    def test_planilleros_muestra_solo_asignados_si_el_partido_ya_los_tiene(self):
        form = PartidoForm(instance=self.partido, torneo=self.torneo)
        usuarios = list(form.fields["planilleros"].queryset)

        self.assertIn(self.planillero, usuarios)
        self.assertIn(self.admin_asignado, usuarios)
        self.assertNotIn(self.planillero_no_asignado, usuarios)
        self.assertNotIn(self.admin, usuarios)


class GestionEquiposAccesoDelegadoMasivoTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(nombre="Veranero", fecha_inicio=date(2026, 1, 1))
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.otra_categoria = Categoria.objects.create(
            nombre="Plus",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.delegado_uno = User.objects.create_user("delegado-uno", password="test")
        self.delegado_dos = User.objects.create_user("delegado-dos", password="test")
        self.equipo_uno = Equipo.objects.create(nombre="Equipo Uno", categoria=self.categoria, responsable=self.delegado_uno)
        self.equipo_dos = Equipo.objects.create(nombre="Equipo Dos", categoria=self.categoria, responsable=self.delegado_dos)
        self.equipo_otro = Equipo.objects.create(nombre="Equipo Otro", categoria=self.otra_categoria)
        self.admin = User.objects.create_user("admin-masivo", password="test", is_staff=True, is_superuser=True)

    def test_actualiza_vencimiento_sin_reemplazar_delegados(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.post(
            "/gestion/equipos/acceso-delegado-masivo/",
            {
                "acceso_delegado_hasta": "2026-06-10T18:00",
                "categoria": str(self.categoria.id),
                "q": "",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.equipo_uno.refresh_from_db()
        self.equipo_dos.refresh_from_db()
        self.equipo_otro.refresh_from_db()
        self.assertEqual(self.equipo_uno.responsable, self.delegado_uno)
        self.assertEqual(self.equipo_dos.responsable, self.delegado_dos)
        self.assertIsNone(self.equipo_otro.responsable)
        self.assertEqual(timezone.localtime(self.equipo_uno.acceso_delegado_hasta).strftime("%Y-%m-%dT%H:%M"), "2026-06-10T18:00")
        self.assertEqual(timezone.localtime(self.equipo_dos.acceso_delegado_hasta).strftime("%Y-%m-%dT%H:%M"), "2026-06-10T18:00")
        self.assertIsNone(self.equipo_otro.acceso_delegado_hasta)


class GestionEquiposCrearDelegadosMasivoTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(nombre="Veranero", fecha_inicio=date(2026, 1, 1))
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.equipo_uno = Equipo.objects.create(nombre="Equipo Uno", categoria=self.categoria)
        self.equipo_dos = Equipo.objects.create(nombre="Equipo Dos", categoria=self.categoria)
        self.delegado_existente = User.objects.create_user("delegado-existente", password="test")
        self.equipo_con_delegado = Equipo.objects.create(
            nombre="Equipo Con Delegado",
            categoria=self.categoria,
            responsable=self.delegado_existente,
        )
        self.admin = User.objects.create_user("admin-crea-delegados", password="test", is_staff=True, is_superuser=True)

    def test_crea_un_usuario_por_equipo_sin_responsable(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.post(
            "/gestion/equipos/crear-delegados-masivo/",
            {
                "password_temporal": "Temporal123",
                "acceso_delegado_hasta": "2026-06-10T18:00",
                "categoria": str(self.categoria.id),
                "q": "",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.equipo_uno.refresh_from_db()
        self.equipo_dos.refresh_from_db()
        self.equipo_con_delegado.refresh_from_db()
        self.assertIsNotNone(self.equipo_uno.responsable)
        self.assertIsNotNone(self.equipo_dos.responsable)
        self.assertEqual(self.equipo_uno.responsable.username, "admin-equipouno")
        self.assertEqual(self.equipo_dos.responsable.username, "admin-equipodos")
        self.assertNotEqual(self.equipo_uno.responsable, self.equipo_dos.responsable)
        self.assertEqual(self.equipo_con_delegado.responsable, self.delegado_existente)
        self.assertTrue(self.equipo_uno.responsable.check_password("Temporal123"))
        self.assertEqual(timezone.localtime(self.equipo_uno.acceso_delegado_hasta).strftime("%Y-%m-%dT%H:%M"), "2026-06-10T18:00")


class GestionEquiposRenombrarDelegadosMasivoTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(nombre="Veranero", fecha_inicio=date(2026, 1, 1))
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.usuario_largo = User.objects.create_user("delegado-senior-niqueleros-fc", password="Temporal123")
        self.equipo = Equipo.objects.create(
            nombre="Niqueleros FC",
            categoria=self.categoria,
            responsable=self.usuario_largo,
        )
        self.admin = User.objects.create_user("admin-renombra-delegados", password="test", is_staff=True, is_superuser=True)

    def test_renombra_usuario_largo_a_formato_corto_sin_cambiar_password(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.post(
            "/gestion/equipos/renombrar-delegados-masivo/",
            {
                "categoria": str(self.categoria.id),
                "q": "",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.usuario_largo.refresh_from_db()
        self.assertEqual(self.usuario_largo.username, "admin-niquelerosfc")
        self.assertTrue(self.usuario_largo.check_password("Temporal123"))


class DelegadoEquipoTests(TestCase):
    def setUp(self):
        self.torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        self.categoria = Categoria.objects.create(
            nombre="Senior",
            edad_minima=18,
            edad_maxima=60,
            torneo=self.torneo,
        )
        self.delegado = User.objects.create_user("delegado", password="test")
        self.otro_usuario = User.objects.create_user("otro-delegado", password="test")
        self.equipo = Equipo.objects.create(
            nombre="Niqueleros",
            categoria=self.categoria,
            responsable=self.delegado,
            acceso_delegado_hasta=timezone.now() + timedelta(days=2),
        )
        self.otro_equipo = Equipo.objects.create(
            nombre="Rival",
            categoria=self.categoria,
            responsable=self.otro_usuario,
            acceso_delegado_hasta=timezone.now() + timedelta(days=2),
        )
        self.jugador = Jugador.objects.create(
            equipo=self.equipo,
            dorsal=7,
            nombres="Jugador Uno",
            cedula="123",
            fecha_nacimiento=date(1990, 1, 1),
        )

    def test_delegado_con_acceso_vigente_puede_editar_su_equipo(self):
        self.client.force_login(self.delegado)

        respuesta = self.client.post(
            f"/delegado/equipos/{self.equipo.id}/editar/",
            {
                "delegado": "Pablo Mazo",
                "telefono": "300123",
                "director_tecnico": "DT Uno",
                "telefono_dt": "300456",
                "asistente_tecnico": "AT Uno",
                "telefono_at": "300789",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.equipo.refresh_from_db()
        self.assertEqual(self.equipo.delegado, "Pablo Mazo")
        self.assertEqual(self.equipo.director_tecnico, "DT Uno")

    def test_delegado_ve_mensaje_de_acceso_exitoso_al_ingresar(self):
        respuesta = self.client.post(
            "/ingresar/",
            {
                "username": "delegado",
                "password": "test",
            },
            follow=True,
        )

        self.assertContains(respuesta, "Acceso exitoso. Bienvenido al portal de delegados.")

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_delegado_regresa_del_panel_a_mis_equipos_sin_nuevo_login(self):
        self.client.force_login(self.delegado)
        session = self.client.session
        session["torneo_id"] = self.torneo.id
        session.save()

        respuesta = self.client.get("/")

        self.assertContains(respuesta, f'href="/delegado/equipos/"')
        self.assertIn("_auth_user_id", self.client.session)

    def test_delegado_con_next_de_admin_entra_a_mis_equipos(self):
        respuesta = self.client.post(
            "/ingresar/?next=/gestion/",
            {
                "username": "delegado",
                "password": "test",
                "next": "/gestion/",
            },
        )

        self.assertRedirects(respuesta, "/delegado/equipos/", fetch_redirect_response=False)

    def test_delegado_sin_acceso_vigente_tambien_entra_a_mis_equipos(self):
        self.equipo.acceso_delegado_hasta = None
        self.equipo.save(update_fields=["acceso_delegado_hasta"])

        respuesta = self.client.post(
            "/ingresar/?next=/gestion/",
            {
                "username": "delegado",
                "password": "test",
                "next": "/gestion/",
            },
            follow=True,
        )

        self.assertContains(respuesta, "Niqueleros")
        self.assertContains(respuesta, "Sin fecha de acceso asignada.")
        self.assertContains(respuesta, "Alineacion de partidos")
        self.assertContains(respuesta, "Edicion de equipo bloqueada")

    def test_delegado_sin_acceso_a_edicion_de_equipo_puede_ver_partidos_de_alineacion(self):
        self.equipo.acceso_delegado_hasta = None
        self.equipo.save(update_fields=["acceso_delegado_hasta"])
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=(ahora_local - timedelta(hours=1)).date(),
            hora=(ahora_local - timedelta(hours=1)).time(),
            estado="PROGRAMADO",
        )
        self.client.force_login(self.delegado)

        respuesta_lista = self.client.get(f"/delegado/equipos/{self.equipo.id}/partidos/")
        respuesta_guardar = self.client.post(
            f"/delegado/equipos/{self.equipo.id}/partidos/{partido.id}/alineacion/",
            {
                "cancha_DC": self.jugador.id,
            },
        )

        self.assertContains(respuesta_lista, "Cargar alineacion")
        self.assertEqual(respuesta_guardar.status_code, 302)
        self.assertTrue(
            AlineacionPartido.objects.filter(
                partido=partido,
                equipo=self.equipo,
                jugador=self.jugador,
                rol="TITULAR",
                posicion_cancha="DC",
            ).exists()
        )

    def test_editar_equipo_bloqueado_redirige_a_partidos_de_alineacion(self):
        self.equipo.acceso_delegado_hasta = None
        self.equipo.save(update_fields=["acceso_delegado_hasta"])
        self.client.force_login(self.delegado)

        respuesta = self.client.get(f"/delegado/equipos/{self.equipo.id}/editar/")

        self.assertRedirects(
            respuesta,
            f"/delegado/equipos/{self.equipo.id}/partidos/",
            fetch_redirect_response=False,
        )

    def test_delegado_puede_agregar_jugador_a_su_equipo(self):
        self.client.force_login(self.delegado)

        respuesta = self.client.post(
            f"/delegado/equipos/{self.equipo.id}/jugadores/nuevo/",
            {
                "dorsal": 10,
                "nombres": "Jugador Nuevo",
                "cedula": "456",
                "fecha_nacimiento": "1995-02-03",
                "telefono": "301000",
                "estado": "ACTIVO",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Jugador.objects.filter(equipo=self.equipo, cedula="456", nombres="JUGADOR NUEVO").exists())

    def test_delegado_no_puede_editar_otro_equipo(self):
        self.client.force_login(self.delegado)

        respuesta = self.client.get(f"/delegado/equipos/{self.otro_equipo.id}/editar/")

        self.assertEqual(respuesta.status_code, 404)

    def test_delegado_pierde_acceso_al_vencer_plazo(self):
        self.equipo.acceso_delegado_hasta = timezone.now() - timedelta(minutes=1)
        self.equipo.save(update_fields=["acceso_delegado_hasta"])
        self.client.force_login(self.delegado)

        respuesta = self.client.get(f"/delegado/equipos/{self.equipo.id}/editar/")

        self.assertRedirects(
            respuesta,
            f"/delegado/equipos/{self.equipo.id}/partidos/",
            fetch_redirect_response=False,
        )

    def test_delegado_puede_guardar_alineacion_desde_hora_programada(self):
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=(ahora_local - timedelta(hours=1)).date(),
            hora=(ahora_local - timedelta(hours=1)).time(),
            estado="PROGRAMADO",
        )
        self.client.force_login(self.delegado)

        respuesta = self.client.post(
            f"/delegado/equipos/{self.equipo.id}/partidos/{partido.id}/alineacion/",
            {
                f"rol_{self.jugador.id}": "TITULAR",
                f"posicion_{self.jugador.id}": "DC",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(
            AlineacionPartido.objects.filter(
                partido=partido,
                equipo=self.equipo,
                jugador=self.jugador,
                rol="TITULAR",
                posicion_cancha="DC",
            ).exists()
        )

    def test_delegado_guarda_titular_desde_cancha_y_suplente_desde_banco(self):
        suplente = Jugador.objects.create(
            equipo=self.equipo,
            dorsal=8,
            nombres="Jugador Suplente",
            cedula="789",
            fecha_nacimiento=date(1991, 1, 1),
        )
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=(ahora_local - timedelta(hours=1)).date(),
            hora=(ahora_local - timedelta(hours=1)).time(),
            estado="PROGRAMADO",
        )
        self.client.force_login(self.delegado)

        respuesta = self.client.post(
            f"/delegado/equipos/{self.equipo.id}/partidos/{partido.id}/alineacion/",
            {
                "cancha_DC": self.jugador.id,
                f"rol_{suplente.id}": "SUPLENTE",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(
            AlineacionPartido.objects.filter(
                partido=partido,
                equipo=self.equipo,
                jugador=self.jugador,
                rol="TITULAR",
                posicion_cancha="DC",
            ).exists()
        )
        self.assertTrue(
            AlineacionPartido.objects.filter(
                partido=partido,
                equipo=self.equipo,
                jugador=suplente,
                rol="SUPLENTE",
            ).exists()
        )

    def test_delegado_ve_edad_en_editor_de_alineacion(self):
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=(ahora_local - timedelta(hours=1)).date(),
            hora=(ahora_local - timedelta(hours=1)).time(),
            estado="PROGRAMADO",
        )
        self.client.force_login(self.delegado)

        respuesta = self.client.get(f"/delegado/equipos/{self.equipo.id}/partidos/{partido.id}/alineacion/")

        self.assertContains(respuesta, texto_edad_jugador(self.jugador, self.categoria, partido.fecha))

    def test_delegado_no_puede_guardar_alineacion_antes_de_hora_programada(self):
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=(ahora_local + timedelta(hours=1)).date(),
            hora=(ahora_local + timedelta(hours=1)).time(),
            estado="PROGRAMADO",
        )
        self.client.force_login(self.delegado)

        respuesta = self.client.post(
            f"/delegado/equipos/{self.equipo.id}/partidos/{partido.id}/alineacion/",
            {
                f"rol_{self.jugador.id}": "TITULAR",
                f"posicion_{self.jugador.id}": "DC",
            },
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(AlineacionPartido.objects.filter(partido=partido).exists())

    def test_delegado_no_puede_guardar_alineacion_despues_de_diez_minutos_en_juego(self):
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=ahora_local.date(),
            hora=(ahora_local - timedelta(hours=1)).time(),
            estado="EN_JUEGO",
            inicio_en_vivo=timezone.now() - timedelta(minutes=11),
        )
        self.client.force_login(self.delegado)

        respuesta = self.client.post(
            f"/delegado/equipos/{self.equipo.id}/partidos/{partido.id}/alineacion/",
            {
                f"rol_{self.jugador.id}": "TITULAR",
                f"posicion_{self.jugador.id}": "DC",
            },
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(AlineacionPartido.objects.filter(partido=partido).exists())

    def test_delegado_asignado_como_planillero_no_abre_editor_completo(self):
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=(ahora_local - timedelta(hours=1)).date(),
            hora=(ahora_local - timedelta(hours=1)).time(),
            estado="PROGRAMADO",
        )
        partido.planilleros.add(self.delegado)
        self.client.force_login(self.delegado)

        respuesta = self.client.get(f"/partido/{partido.id}/editor-movil/")

        self.assertRedirects(
            respuesta,
            f"/delegado/equipos/{self.equipo.id}/partidos/{partido.id}/alineacion/",
            fetch_redirect_response=False,
        )

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_partido_en_vivo_muestra_solo_boton_de_alineacion_a_delegado(self):
        ahora_local = timezone.localtime()
        partido = Partido.objects.create(
            categoria=self.categoria,
            equipo_local=self.equipo,
            equipo_visitante=self.otro_equipo,
            fecha=(ahora_local - timedelta(hours=1)).date(),
            hora=(ahora_local - timedelta(hours=1)).time(),
            estado="PROGRAMADO",
        )
        partido.planilleros.add(self.delegado)
        self.client.force_login(self.delegado)

        respuesta = self.client.get(f"/partido/{partido.id}/live/")

        self.assertContains(respuesta, "Cargar alineaci")
        self.assertNotContains(respuesta, "Goles <span>")
        self.assertNotContains(respuesta, "Tarjetas <span>")


class JugadorCedulaPorEquipoTests(TransactionTestCase):
    def test_permite_misma_cedula_en_categorias_distintas(self):
        torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        senior = Categoria.objects.create(
            nombre="Senior Master",
            edad_minima=18,
            edad_maxima=60,
            torneo=torneo,
        )
        plus = Categoria.objects.create(
            nombre="Plus 50",
            edad_minima=50,
            edad_maxima=80,
            torneo=torneo,
        )
        equipo_senior = Equipo.objects.create(nombre="Niqueleros", categoria=senior)
        equipo_plus = Equipo.objects.create(nombre="Niqueleros", categoria=plus)

        Jugador.objects.create(
            equipo=equipo_senior,
            dorsal=7,
            nombres="Jugador Compartido",
            cedula="12345",
            fecha_nacimiento=date(1970, 1, 1),
        )
        Jugador.objects.create(
            equipo=equipo_plus,
            dorsal=7,
            nombres="Jugador Compartido",
            cedula="12345",
            fecha_nacimiento=date(1970, 1, 1),
        )

        self.assertEqual(Jugador.objects.filter(cedula="12345").count(), 2)

    def test_no_permite_misma_cedula_dos_veces_en_el_mismo_equipo(self):
        torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        categoria = Categoria.objects.create(
            nombre="Senior Master",
            edad_minima=18,
            edad_maxima=60,
            torneo=torneo,
        )
        equipo = Equipo.objects.create(nombre="Niqueleros", categoria=categoria)

        Jugador.objects.create(
            equipo=equipo,
            dorsal=7,
            nombres="Jugador Uno",
            cedula="12345",
            fecha_nacimiento=date(1970, 1, 1),
        )

        with self.assertRaises(ValidationError):
            Jugador.objects.create(
                equipo=equipo,
                dorsal=8,
                nombres="Jugador Dos",
                cedula="12345",
                fecha_nacimiento=date(1975, 1, 1),
            )

    def test_no_permite_misma_cedula_en_otro_equipo_de_la_misma_categoria(self):
        torneo = Torneo.objects.create(
            nombre="Veranero",
            fecha_inicio=date(2026, 1, 1),
        )
        categoria = Categoria.objects.create(
            nombre="Senior Master",
            edad_minima=18,
            edad_maxima=60,
            torneo=torneo,
        )
        niqueleros = Equipo.objects.create(nombre="Niqueleros", categoria=categoria)
        otro_equipo = Equipo.objects.create(nombre="Otro Equipo", categoria=categoria)

        Jugador.objects.create(
            equipo=niqueleros,
            dorsal=7,
            nombres="Jugador Uno",
            cedula="12345",
            fecha_nacimiento=date(1970, 1, 1),
        )

        with self.assertRaises(ValidationError):
            Jugador.objects.create(
                equipo=otro_equipo,
                dorsal=8,
                nombres="Jugador Dos",
                cedula="12345",
                fecha_nacimiento=date(1975, 1, 1),
            )
