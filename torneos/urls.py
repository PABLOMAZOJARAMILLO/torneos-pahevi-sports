from django.urls import path
from . import views
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
    descargar_programacion_general,
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
    path('partido/<int:partido_id>/', views.detalle_partido_publico, name='partido_detalle_publico'),

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

    path(
        'descargar/programacion-general/',
        descargar_programacion_general,
        name='descargar_programacion_general'
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

    path(
    'equipos/<int:equipo_id>/crear-jugador/',
    views.crear_jugador_equipo,
    name='crear_jugador_equipo'
   ),

    path('equipos/', views.lista_equipos, name='lista_equipos'),
    path('equipos/<int:equipo_id>/', views.detalle_equipo, name='detalle_equipo'),
    path('mis-equipos/', views.mis_equipos, name='mis_equipos'),

    path('gestion/', views.gestion_panel, name='gestion_panel'),
    path('gestion/probar-storage/', views.gestion_probar_storage, name='gestion_probar_storage'),
    path('gestion/generar-fixture/', views.gestion_generar_fixture, name='gestion_generar_fixture'),
    path('gestion/equipos/', views.gestion_equipos, name='gestion_equipos'),
    path('gestion/equipos/nuevo/', views.gestion_equipo_nuevo, name='gestion_equipo_nuevo'),
    path('gestion/equipos/<int:equipo_id>/editar/', views.gestion_equipo_editar, name='gestion_equipo_editar'),
    path('gestion/jugadores/', views.gestion_jugadores, name='gestion_jugadores'),
    path('gestion/jugadores/importar-planilla/', views.gestion_importar_planilla, name='gestion_importar_planilla'),
    path('gestion/jugadores/nuevo/', views.gestion_jugador_nuevo, name='gestion_jugador_nuevo'),
    path('gestion/jugadores/<int:jugador_id>/editar/', views.gestion_jugador_editar, name='gestion_jugador_editar'),
    path('gestion/partidos/', views.gestion_partidos, name='gestion_partidos'),
    path('gestion/partidos/importar/', views.gestion_importar_partidos, name='gestion_importar_partidos'),
    path('gestion/partidos/nuevo/', views.gestion_partido_nuevo, name='gestion_partido_nuevo'),
    path('gestion/partidos/<int:partido_id>/editar/', views.gestion_partido_editar, name='gestion_partido_editar'),

]
