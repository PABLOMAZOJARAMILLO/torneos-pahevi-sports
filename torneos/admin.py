from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from openpyxl import load_workbook
from datetime import date

from .models import Categoria, Equipo, Jugador
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

class ImportarPlanillaAdminSite(admin.AdminSite):
    pass

def importar_planilla_inscripcion(request):
    if request.method == "POST":
        archivo = request.FILES.get("archivo_excel")

        if not archivo:
            messages.error(request, "Debes seleccionar un archivo Excel.")
            return redirect("admin:importar_planilla_inscripcion")

        wb = load_workbook(archivo, data_only=True)
        ws = wb["Planilla inscripcion"]

        categoria_nombre = str(ws["D3"].value).strip()
        equipo_nombre = str(ws["I3"].value).strip()
        delegado = ws["D4"].value
        telefono = ws["I4"].value

        categoria = Categoria.objects.filter(nombre__iexact=categoria_nombre).first()

        if not categoria:
            messages.error(request, f"No existe la categoría: {categoria_nombre}")
            return redirect("admin:importar_planilla_inscripcion")

        equipo, creado = Equipo.objects.get_or_create(
            nombre__iexact=equipo_nombre,
            categoria=categoria,
            defaults={
                "nombre": equipo_nombre,
                "delegado": delegado,
                "telefono": telefono,
                "activo": True,
            }
        )

        if not creado:
            equipo.delegado = delegado
            equipo.telefono = telefono
            equipo.save()

        importados = 0
        actualizados = 0
        errores = []

        for fila in range(8, 38):
            nombre = ws[f"C{fila}"].value
            dorsal = ws[f"D{fila}"].value
            dia = ws[f"E{fila}"].value
            mes = ws[f"F{fila}"].value
            anio = ws[f"G{fila}"].value
            cedula = ws[f"H{fila}"].value

            if not nombre or not cedula:
                continue

            try:
                fecha_nacimiento = date(int(anio), int(mes), int(dia))
            except Exception:
                errores.append(f"Fila {fila}: fecha inválida para {nombre}")
                continue

            jugador, creado_jugador = Jugador.objects.update_or_create(
                cedula=str(cedula).strip(),
                defaults={
                    "equipo": equipo,
                    "dorsal": int(dorsal) if dorsal not in [None, ""] else None,
                    "nombres": str(nombre).strip().upper(),
                    "fecha_nacimiento": fecha_nacimiento,
                    "estado": "ACTIVO",
                }
            )

            if creado_jugador:
                importados += 1
            else:
                actualizados += 1

        messages.success(
            request,
            f"Importación completa. Nuevos: {importados}. Actualizados: {actualizados}."
        )

        for error in errores:
            messages.warning(request, error)

        return redirect("admin:torneos_jugador_changelist")

    return render(request, "admin/importar_planilla_inscripcion.html")

from django.contrib import admin

original_get_urls = admin.site.get_urls

def get_urls():
    urls = original_get_urls()
    custom_urls = [
        path(
            "importar-planilla-inscripcion/",
            admin.site.admin_view(importar_planilla_inscripcion),
            name="importar_planilla_inscripcion"
        ),
    ]
    return custom_urls + urls

admin.site.get_urls = get_urls
