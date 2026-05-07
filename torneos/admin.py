from django.contrib import admin
from .models import Categoria, Equipo, Jugador, Partido, Gol, Tarjeta


# 🔹 CATEGORIA
@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


# 🔹 JUGADORES dentro del equipo
class JugadorInline(admin.TabularInline):
    model = Jugador
    extra = 0
    fields = ('dorsal', 'nombres', 'cedula', 'fecha_nacimiento')
    ordering = ('dorsal',)


# 🔹 EQUIPO
@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria')
    list_filter = ('categoria',)
    search_fields = ('nombre',)
    inlines = [JugadorInline]


# 🔹 JUGADOR (vista general)
@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = ('dorsal', 'nombres', 'equipo', 'cedula')
    list_filter = ('equipo',)
    search_fields = ('nombres', 'cedula')


# 🔹 GOLES dentro del partido
class GolInline(admin.TabularInline):
    model = Gol
    extra = 0


# 🔹 TARJETAS dentro del partido
class TarjetaInline(admin.TabularInline):
    model = Tarjeta
    extra = 0


# 🔹 PARTIDOS
@admin.register(Partido)
class PartidoAdmin(admin.ModelAdmin):
    list_display = (
        'categoria',
        'grupo',
        'numero_fecha',
        'fase',
        'equipo_local',
        'equipo_visitante',
        'goles_local',
        'goles_visitante',
        'estado',
        'ajuste_puntos_local',
        'ajuste_puntos_visitante',
        'observacion_comite',
    )
    list_filter = ('categoria', 'grupo', 'numero_fecha', 'fase', 'estado')
    search_fields = ('equipo_local__nombre', 'equipo_visitante__nombre')
    inlines = [GolInline, TarjetaInline]


# 🔹 GOLES (vista general)
@admin.register(Gol)
class GolAdmin(admin.ModelAdmin):
    list_display = ('jugador', 'equipo', 'cantidad', 'partido')
    list_filter = ('equipo', 'partido__categoria', 'partido__grupo', 'partido__fase')
    search_fields = ('jugador__nombres',)


# 🔹 TARJETAS (vista general)
@admin.register(Tarjeta)
class TarjetaAdmin(admin.ModelAdmin):
    list_display = ('jugador', 'equipo', 'tipo', 'partido')
    list_filter = ('tipo', 'equipo', 'partido__categoria', 'partido__grupo', 'partido__fase')
    search_fields = ('jugador__nombres',)