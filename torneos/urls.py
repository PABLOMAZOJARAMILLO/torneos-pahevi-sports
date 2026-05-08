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
    editor_partido_movil,
    guardar_info_partido_movil,
    agregar_gol_movil,
    agregar_tarjeta_movil,
    agregar_alineacion_movil,
    agregar_sustitucion_movil,
    eliminar_gol_movil,
    eliminar_tarjeta_movil,
    eliminar_alineacion_movil,
    eliminar_sustitucion_movil,
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

    # Editor móvil profesional de partidos
    path(
        'partido/<int:partido_id>/editor-movil/',
        editor_partido_movil,
        name='editor_partido_movil'
    ),
    path(
        'partido/<int:partido_id>/guardar-info-movil/',
        guardar_info_partido_movil,
        name='guardar_info_partido_movil'
    ),
    path(
        'partido/<int:partido_id>/agregar-gol-movil/',
        agregar_gol_movil,
        name='agregar_gol_movil'
    ),
    path(
        'partido/<int:partido_id>/agregar-tarjeta-movil/',
        agregar_tarjeta_movil,
        name='agregar_tarjeta_movil'
    ),
    path(
        'partido/<int:partido_id>/agregar-alineacion-movil/',
        agregar_alineacion_movil,
        name='agregar_alineacion_movil'
    ),
    path(
        'partido/<int:partido_id>/agregar-sustitucion-movil/',
        agregar_sustitucion_movil,
        name='agregar_sustitucion_movil'
    ),
    path(
        'gol/<int:gol_id>/eliminar-movil/',
        eliminar_gol_movil,
        name='eliminar_gol_movil'
    ),
    path(
        'tarjeta/<int:tarjeta_id>/eliminar-movil/',
        eliminar_tarjeta_movil,
        name='eliminar_tarjeta_movil'
    ),
    path(
        'alineacion/<int:alineacion_id>/eliminar-movil/',
        eliminar_alineacion_movil,
        name='eliminar_alineacion_movil'
    ),
    path(
        'sustitucion/<int:sustitucion_id>/eliminar-movil/',
        eliminar_sustitucion_movil,
        name='eliminar_sustitucion_movil'
    ),

]