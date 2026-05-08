from django.contrib import admin
from .models import (
    Categoria, Equipo, Jugador, Partido, Gol, Tarjeta,
    AlineacionPartido, SustitucionPartido
)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


class JugadorInline(admin.TabularInline):
    model = Jugador
    extra = 0
    fields = ('dorsal', 'nombres', 'cedula', 'fecha_nacimiento')
    ordering = ('dorsal',)


@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria')
    list_filter = ('categoria',)
    search_fields = ('nombre',)
    inlines = [JugadorInline]


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = ('dorsal', 'nombres', 'equipo', 'cedula')
    list_filter = ('equipo',)
    search_fields = ('nombres', 'cedula')


class GolInline(admin.TabularInline):
    model = Gol
    extra = 0


class TarjetaInline(admin.TabularInline):
    model = Tarjeta
    extra = 0


class AlineacionInline(admin.TabularInline):
    model = AlineacionPartido
    extra = 0


class SustitucionInline(admin.TabularInline):
    model = SustitucionPartido
    extra = 0


@admin.register(Partido)
class PartidoAdmin(admin.ModelAdmin):
    list_display = (
        'categoria', 'grupo', 'numero_fecha', 'fase',
        'equipo_local', 'equipo_visitante',
        'goles_local', 'goles_visitante', 'estado',
        'ajuste_puntos_local', 'ajuste_puntos_visitante',
        'observacion_comite', 'goles_local_penales', 'goles_visitante_penales',
        'siguiente_partido', 'slot_siguiente',
    )
    list_filter = ('categoria', 'grupo', 'numero_fecha', 'fase', 'estado')
    search_fields = ('equipo_local__nombre', 'equipo_visitante__nombre')
    inlines = [GolInline, TarjetaInline, AlineacionInline, SustitucionInline]


@admin.register(Gol)
class GolAdmin(admin.ModelAdmin):
    list_display = ('jugador', 'equipo', 'cantidad', 'partido')
    list_filter = ('equipo', 'partido__categoria', 'partido__grupo', 'partido__fase')
    search_fields = ('jugador__nombres',)


@admin.register(Tarjeta)
class TarjetaAdmin(admin.ModelAdmin):
    list_display = ('jugador', 'equipo', 'tipo', 'partido')
    list_filter = ('tipo', 'equipo', 'partido__categoria', 'partido__grupo', 'partido__fase')
    search_fields = ('jugador__nombres',)


@admin.register(AlineacionPartido)
class AlineacionPartidoAdmin(admin.ModelAdmin):
    list_display = ('partido', 'equipo', 'jugador', 'rol')
    list_filter = ('equipo', 'rol', 'partido__categoria', 'partido__fase')
    search_fields = ('jugador__nombres', 'equipo__nombre')


@admin.register(SustitucionPartido)
class SustitucionPartidoAdmin(admin.ModelAdmin):
    list_display = ('partido', 'equipo', 'jugador_sale', 'jugador_entra', 'minuto')
    list_filter = ('equipo', 'partido__categoria', 'partido__fase')
    search_fields = ('jugador_sale__nombres', 'jugador_entra__nombres', 'equipo__nombre')
