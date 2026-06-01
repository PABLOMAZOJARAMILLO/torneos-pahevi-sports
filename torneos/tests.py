from datetime import date, time, timedelta

from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .forms import JugadorForm
from .models import AlineacionPartido, Categoria, Equipo, Gol, Jugador, Partido, ReglaEdadCategoria, SustitucionPartido, Tarjeta, Torneo
from .views import construir_estructura, construir_estadisticas_foraneos, _clave_orden_evento_resumen, _sincronizar_no_disponibles_por_tarjetas, etiqueta_edad_jugador, validar_reglas_edad_titulares


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
    def test_ordena_por_minuto_y_luego_por_edicion(self):
        base = timezone.now()
        eventos = [
            SimpleNamespace(minuto=None, creado_en=base, orden=1),
            SimpleNamespace(minuto=15, creado_en=base, orden=3),
            SimpleNamespace(minuto=15, creado_en=base + timedelta(seconds=5), orden=2),
            SimpleNamespace(minuto=None, creado_en=base + timedelta(seconds=10), orden=4),
        ]

        ordenados = sorted(eventos, key=_clave_orden_evento_resumen)

        self.assertEqual([evento.orden for evento in ordenados], [3, 2, 1, 4])


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
            minimo_titulares=4,
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

    def test_valida_minimos_de_titulares_por_regla(self):
        jugadores = []
        for indice in range(1, 5):
            jugadores.append(self.crear_jugador(indice, date(1983, 1, 1)))
        for indice in range(5, 9):
            jugadores.append(self.crear_jugador(indice, date(1978, 1, 1)))
        for indice in range(9, 12):
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
        for indice in range(5, 12):
            jugadores.append(self.crear_jugador(indice, date(1970, 1, 1)))

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
