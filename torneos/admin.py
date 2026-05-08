from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from .models import (
    Categoria,
    Equipo,
    Jugador,
    Partido,
    Gol,
    Tarjeta,
    AlineacionPartido,
    SustitucionPartido,
)


# ======================================================
# WIDGETS PARA IMPORTAR POR NOMBRE DESDE EXCEL
# ======================================================

class CategoriaWidget(ForeignKeyWidget):
    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None
        nombre = str(value).strip()
        return Categoria.objects.filter(nombre__iexact=nombre).first()


class EquipoWidget(ForeignKeyWidget):
    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None

        nombre_equipo = str(value).strip()
        qs = Equipo.objects.filter(nombre__iexact=nombre_equipo)

        # Si el Excel trae columna categoria, ayuda a evitar duplicados entre categorías.
        categoria_nombre = None
        if row:
            categoria_nombre = row.get("categoria") or row.get("Categoría") or row.get("CATEGORIA")

        if categoria_nombre:
            qs = qs.filter(categoria__nombre__iexact=str(categoria_nombre).strip())

        equipo = qs.first()
        if not equipo:
            raise ValueError(f"No existe el equipo: {nombre_equipo}")
        return equipo


class JugadorWidget(ForeignKeyWidget):
    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None

        valor = str(value).strip()

        # Preferible importar jugadores por cédula.
        jugador = Jugador.objects.filter(cedula=valor).first()

        # Si no encontró por cédula, intenta por nombre.
        if not jugador:
            jugador = Jugador.objects.filter(nombres__iexact=valor).first()

        if not jugador:
            raise ValueError(f"No existe el jugador: {valor}")

        return jugador


# ======================================================
# RESOURCES PARA IMPORTAR / EXPORTAR
# ======================================================

class CategoriaResource(resources.ModelResource):
    class Meta:
        model = Categoria
        import_id_fields = ("nombre",)
        fields = (
            "id",
            "nombre",
            "descripcion",
            "edad_minima",
            "edad_maxima",
            "torneo",
        )


class EquipoResource(resources.ModelResource):
    categoria = fields.Field(
        column_name="categoria",
        attribute="categoria",
        widget=CategoriaWidget(Categoria, "nombre"),
    )

    class Meta:
        model = Equipo
        import_id_fields = ("nombre", "categoria")
        fields = (
            "id",
            "nombre",
            "categoria",
            "delegado",
            "telefono",
            "activo",
        )
        skip_unchanged = True
        report_skipped = True


class JugadorResource(resources.ModelResource):
    equipo = fields.Field(
        column_name="equipo",
        attribute="equipo",
        widget=EquipoWidget(Equipo, "nombre"),
    )

    class Meta:
        model = Jugador
        import_id_fields = ("cedula",)
        fields = (
            "id",
            "equipo",
            "dorsal",
            "nombres",
            "cedula",
            "fecha_nacimiento",
            "telefono",
            "estado",
        )
        skip_unchanged = True
        report_skipped = True


class PartidoResource(resources.ModelResource):
    categoria = fields.Field(
        column_name="categoria",
        attribute="categoria",
        widget=CategoriaWidget(Categoria, "nombre"),
    )
    equipo_local = fields.Field(
        column_name="equipo_local",
        attribute="equipo_local",
        widget=EquipoWidget(Equipo, "nombre"),
    )
    equipo_visitante = fields.Field(
        column_name="equipo_visitante",
        attribute="equipo_visitante",
        widget=EquipoWidget(Equipo, "nombre"),
    )

    class Meta:
        model = Partido
        import_id_fields = ("categoria", "fase", "numero_fecha", "equipo_local", "equipo_visitante")
        fields = (
            "id",
            "categoria",
            "equipo_local",
            "equipo_visitante",
            "fecha",
            "hora",
            "goles_local",
            "goles_visitante",
            "estado",
            "observaciones",
            "numero_fecha",
            "grupo",
            "cancha",
            "fase",
            "ajuste_puntos_local",
            "ajuste_puntos_visitante",
            "observacion_comite",
            "goles_local_penales",
            "goles_visitante_penales",
        )
        skip_unchanged = True
        report_skipped = True


class GolResource(resources.ModelResource):
    partido = fields.Field(column_name="partido", attribute="partido")
    jugador = fields.Field(
        column_name="jugador",
        attribute="jugador",
        widget=JugadorWidget(Jugador, "cedula"),
    )
    equipo = fields.Field(
        column_name="equipo",
        attribute="equipo",
        widget=EquipoWidget(Equipo, "nombre"),
    )

    class Meta:
        model = Gol
        fields = ("id", "partido", "jugador", "equipo", "cantidad")
        skip_unchanged = True
        report_skipped = True


class TarjetaResource(resources.ModelResource):
    partido = fields.Field(column_name="partido", attribute="partido")
    jugador = fields.Field(
        column_name="jugador",
        attribute="jugador",
        widget=JugadorWidget(Jugador, "cedula"),
    )
    equipo = fields.Field(
        column_name="equipo",
        attribute="equipo",
        widget=EquipoWidget(Equipo, "nombre"),
    )

    class Meta:
        model = Tarjeta
        fields = ("id", "partido", "jugador", "equipo", "tipo")
        skip_unchanged = True
        report_skipped = True


# ======================================================
# ADMIN
# ======================================================

@admin.register(Categoria)
class CategoriaAdmin(ImportExportModelAdmin):
    resource_class = CategoriaResource
    list_display = ("nombre", "edad_minima", "edad_maxima")
    search_fields = ("nombre",)


class JugadorInline(admin.TabularInline):
    model = Jugador
    extra = 0
    fields = ("dorsal", "nombres", "cedula", "fecha_nacimiento", "estado")
    ordering = ("dorsal", "nombres")


@admin.register(Equipo)
class EquipoAdmin(ImportExportModelAdmin):
    resource_class = EquipoResource
    list_display = ("nombre", "categoria", "delegado", "telefono", "activo")
    list_filter = ("categoria", "activo")
    search_fields = ("nombre", "delegado", "telefono")
    inlines = [JugadorInline]


@admin.register(Jugador)
class JugadorAdmin(ImportExportModelAdmin):
    resource_class = JugadorResource
    list_display = ("dorsal", "nombres", "equipo", "cedula", "fecha_nacimiento", "estado")
    list_filter = ("equipo", "equipo__categoria", "estado")
    search_fields = ("nombres", "cedula", "equipo__nombre")
    ordering = ("equipo__nombre", "dorsal", "nombres")


class GolInline(admin.TabularInline):
    model = Gol
    extra = 0


class TarjetaInline(admin.TabularInline):
    model = Tarjeta
    extra = 0


@admin.register(Partido)
class PartidoAdmin(ImportExportModelAdmin):
    resource_class = PartidoResource
    list_display = (
        "categoria",
        "grupo",
        "numero_fecha",
        "fase",
        "equipo_local",
        "equipo_visitante",
        "goles_local",
        "goles_visitante",
        "estado",
        "fecha",
        "hora",
        "cancha",
        "ajuste_puntos_local",
        "ajuste_puntos_visitante",
        "goles_local_penales",
        "goles_visitante_penales",
    )
    list_filter = ("categoria", "grupo", "numero_fecha", "fase", "estado")
    search_fields = ("equipo_local__nombre", "equipo_visitante__nombre", "cancha")
    inlines = [GolInline, TarjetaInline]
    ordering = ("categoria__nombre", "grupo", "numero_fecha", "fase", "fecha", "hora")


@admin.register(Gol)
class GolAdmin(ImportExportModelAdmin):
    resource_class = GolResource
    list_display = ("jugador", "equipo", "cantidad", "partido")
    list_filter = ("equipo", "partido__categoria", "partido__grupo", "partido__fase")
    search_fields = ("jugador__nombres", "jugador__cedula", "equipo__nombre")


@admin.register(Tarjeta)
class TarjetaAdmin(ImportExportModelAdmin):
    resource_class = TarjetaResource
    list_display = ("jugador", "equipo", "tipo", "partido")
    list_filter = ("tipo", "equipo", "partido__categoria", "partido__grupo", "partido__fase")
    search_fields = ("jugador__nombres", "jugador__cedula", "equipo__nombre")


@admin.register(AlineacionPartido)
class AlineacionPartidoAdmin(admin.ModelAdmin):
    list_display = ("partido", "equipo", "jugador", "rol")
    list_filter = ("equipo", "rol", "partido__categoria", "partido__fase")
    search_fields = ("jugador__nombres", "jugador__cedula", "equipo__nombre")


@admin.register(SustitucionPartido)
class SustitucionPartidoAdmin(admin.ModelAdmin):
    list_display = ("partido", "equipo", "jugador_sale", "jugador_entra", "minuto")
    list_filter = ("equipo", "partido__categoria", "partido__fase")
    search_fields = (
        "jugador_sale__nombres",
        "jugador_entra__nombres",
        "equipo__nombre",
    )
