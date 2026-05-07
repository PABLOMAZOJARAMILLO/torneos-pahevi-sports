from django.urls import path
from .views import (
    panel_principal,
    descargar_tabla_grupo,
    descargar_goleadores_categoria,
    descargar_tarjetas_categoria,
    descargar_valla_categoria,
    generar_llaves_cuartos,
    generar_semifinales,
    generar_final,
    generar_tercer_puesto,
    descargar_programacion_categoria,
)

urlpatterns = [
    path('', panel_principal, name='panel'),

    path(
        'descargar/tabla/<str:categoria>/<str:grupo>/',
        descargar_tabla_grupo,
        name='descargar_tabla_grupo'
    ),

    path(
        'descargar/goleadores/<str:categoria>/',
        descargar_goleadores_categoria,
        name='descargar_goleadores_categoria'
    ),

    path(
        'descargar/tarjetas/<str:categoria>/',
        descargar_tarjetas_categoria,
        name='descargar_tarjetas_categoria'
    ),

    path(
        'descargar/valla/<str:categoria>/',
        descargar_valla_categoria,
        name='descargar_valla_categoria'
    ),

    path(
        'generar-llaves/<str:categoria>/',
        generar_llaves_cuartos,
        name='generar_llaves_cuartos'
    ),

    path(
        'generar-semifinales/<str:categoria>/',
        generar_semifinales,
        name='generar_semifinales'
    ),

    path(
        'generar-final/<str:categoria>/',
        generar_final,
        name='generar_final'
    ),

    path(
        'generar-tercer-puesto/<str:categoria>/',
        generar_tercer_puesto,
        name='generar_tercer_puesto'
    ),

    path(
        'descargar/programacion/<str:categoria>/',
        descargar_programacion_categoria,
        name='descargar_programacion_categoria'
    ),
]