from datetime import date, time, timedelta

from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import AlineacionPartido, Categoria, Equipo, Jugador, Partido, ReglaEdadCategoria, SustitucionPartido, Tarjeta, Torneo
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
            municipio="Puerto Libertador",
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
