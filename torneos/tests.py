from datetime import date, time, timedelta

from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from .models import AlineacionPartido, Categoria, Equipo, Jugador, Partido, Tarjeta, Torneo
from .views import construir_estructura, _clave_orden_evento_resumen, _sincronizar_no_disponibles_por_tarjetas


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
