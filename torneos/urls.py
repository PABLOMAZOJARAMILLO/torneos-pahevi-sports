from django.urls import path
from . import views
from .views import (
    panel_principal,
    descargar_tabla_grupo,
    descargar_tabla_general_mata_mata,
    descargar_goleadores_categoria,
    descargar_tarjetas_categoria,
    descargar_disciplina_equipos_categoria,
    descargar_valla_categoria,
    descargar_foraneos_categoria,
    generar_llaves_cuartos,
    generar_semifinales,
    generar_final,
    generar_tercer_puesto,
    descargar_programacion_categoria,
    descargar_programacion_general,
    seleccionar_descarga_programacion,
    editor_partido_movil,
    guardar_info_partido_movil,
    agregar_gol_movil,
    agregar_tarjeta_movil,
    agregar_alineacion_movil,
    guardar_alineacion_masiva_movil,
    agregar_sustitucion_movil,
    eliminar_gol_movil,
    eliminar_tarjeta_movil,
    eliminar_alineacion_movil,
    eliminar_sustitucion_movil,
    
)

urlpatterns = [
    path('', panel_principal, name='panel'),
    path('actualizaciones/posiciones-en-vivo/', views.panel_posiciones_en_vivo, name='panel_posiciones_en_vivo'),
    path('ingresar/', views.IngresoTorneosView.as_view(), name='login'),
    path('sw.js', views.service_worker, name='service_worker'),
    path('salir/', views.cerrar_sesion, name='cerrar_sesion'),
    path('mi-cuenta/cambiar-contrasena/', views.cambiar_contrasena, name='cambiar_contrasena'),
    path('partido/<int:partido_id>/', views.detalle_partido_publico, name='partido_detalle_publico'),
    path('documentos/<int:documento_id>/', views.documento_publico, name='documento_publico'),
    path('documentos/<int:documento_id>/archivo.pdf', views.documento_archivo_publico, name='documento_archivo_publico'),
    path(
    'partido/<int:partido_id>/live/',
    views.partido_live,
    name='partido_live'
    ),
    path(
    'partido/<int:partido_id>/live/revision/',
    views.revision_partido_live,
    name='revision_partido_live'
    ),
    path(
        'descargar/tabla/<str:categoria>/<str:grupo>/',
        descargar_tabla_grupo,
        name='descargar_tabla_grupo'
    ),
    path(
        'descargar/tabla-general-mata-mata/<str:categoria>/',
        descargar_tabla_general_mata_mata,
        name='descargar_tabla_general_mata_mata'
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
        'descargar/disciplina-equipos/<str:categoria>/',
        descargar_disciplina_equipos_categoria,
        name='descargar_disciplina_equipos_categoria'
    ),

    path(
        'descargar/valla/<str:categoria>/',
        descargar_valla_categoria,
        name='descargar_valla_categoria'
    ),

    path(
        'descargar/foraneos/<str:categoria>/',
        descargar_foraneos_categoria,
        name='descargar_foraneos_categoria'
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
        'descargar/programacion/',
        seleccionar_descarga_programacion,
        name='seleccionar_descarga_programacion'
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
        'partido/<int:partido_id>/guardar-alineacion-movil/',
        guardar_alineacion_masiva_movil,
        name='guardar_alineacion_masiva_movil'
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
    path('delegado/equipos/', views.mis_equipos, name='delegado_mis_equipos'),
    path('delegado/equipos/<int:equipo_id>/editar/', views.delegado_equipo_editar, name='delegado_equipo_editar'),
    path('delegado/equipos/<int:equipo_id>/fotos-jugadores/', views.delegado_fotos_jugadores, name='delegado_fotos_jugadores'),
    path('delegado/equipos/<int:equipo_id>/partidos/', views.delegado_partidos_equipo, name='delegado_partidos_equipo'),
    path('delegado/equipos/<int:equipo_id>/partidos/<int:partido_id>/alineacion/', views.delegado_alineacion_partido, name='delegado_alineacion_partido'),
    path('delegado/equipos/<int:equipo_id>/jugadores/nuevo/', views.delegado_jugador_nuevo, name='delegado_jugador_nuevo'),
    path('delegado/jugadores/<int:jugador_id>/editar/', views.delegado_jugador_editar, name='delegado_jugador_editar'),
    path('delegado/jugadores/<int:jugador_id>/eliminar/', views.delegado_jugador_eliminar, name='delegado_jugador_eliminar'),

    path('planillero/partidos/', views.planillero_mis_partidos, name='planillero_mis_partidos'),

    path('gestion/', views.gestion_panel, name='gestion_panel'),
    path('gestion/actividad/', views.gestion_actividad, name='gestion_actividad'),
    path('gestion/organizadores/', views.gestion_organizadores, name='gestion_organizadores'),
    path('gestion/organizadores/nuevo/', views.gestion_organizador_nuevo, name='gestion_organizador_nuevo'),
    path('gestion/organizadores/<int:organizador_id>/editar/', views.gestion_organizador_editar, name='gestion_organizador_editar'),
    path('gestion/organizadores/<int:organizador_id>/admins/', views.gestion_organizador_admins, name='gestion_organizador_admins'),
    path('gestion/organizadores/admins/<int:asignacion_id>/eliminar/', views.gestion_organizador_admin_eliminar, name='gestion_organizador_admin_eliminar'),
    path('gestion/torneos/', views.gestion_torneos, name='gestion_torneos'),
    path('gestion/torneos/nuevo/', views.gestion_torneo_nuevo, name='gestion_torneo_nuevo'),
    path('gestion/torneos/<int:torneo_id>/editar/', views.gestion_torneo_editar, name='gestion_torneo_editar'),
    path('gestion/torneos/<int:torneo_id>/admins/', views.gestion_torneo_admins, name='gestion_torneo_admins'),
    path('gestion/torneos/admins/<int:asignacion_id>/eliminar/', views.gestion_torneo_admin_eliminar, name='gestion_torneo_admin_eliminar'),
    path('gestion/torneos/<int:torneo_id>/activar/', views.gestion_torneo_activar, name='gestion_torneo_activar'),
    path('gestion/torneos/<int:torneo_id>/finalizar/', views.gestion_torneo_finalizar, name='gestion_torneo_finalizar'),
    path('gestion/torneos/<int:torneo_id>/archivar/', views.gestion_torneo_archivar, name='gestion_torneo_archivar'),
    path('gestion/torneos/<int:torneo_id>/desarchivar/', views.gestion_torneo_desarchivar, name='gestion_torneo_desarchivar'),
    path('gestion/torneos/<int:torneo_id>/eliminar/', views.gestion_torneo_eliminar, name='gestion_torneo_eliminar'),
    path('gestion/categorias/', views.gestion_categorias, name='gestion_categorias'),
    path('gestion/categorias/nueva/', views.gestion_categoria_nueva, name='gestion_categoria_nueva'),
    path('gestion/categorias/<int:categoria_id>/editar/', views.gestion_categoria_editar, name='gestion_categoria_editar'),
    path('gestion/categorias/<int:categoria_id>/eliminar/', views.gestion_categoria_eliminar, name='gestion_categoria_eliminar'),
    path('gestion/probar-storage/', views.gestion_probar_storage, name='gestion_probar_storage'),
    path('gestion/biblioteca-cloudinary/', views.gestion_biblioteca_cloudinary, name='gestion_biblioteca_cloudinary'),
    path('gestion/biblioteca-cloudinary/asignar/', views.gestion_asignar_imagen_cloudinary, name='gestion_asignar_imagen_cloudinary'),
    path('gestion/documentos/', views.gestion_documentos, name='gestion_documentos'),
    path('gestion/documentos/nuevo/', views.gestion_documento_nuevo, name='gestion_documento_nuevo'),
    path('gestion/documentos/<int:documento_id>/editar/', views.gestion_documento_editar, name='gestion_documento_editar'),
    path('gestion/planillas-juego/', views.gestion_planillas_juego, name='gestion_planillas_juego'),
    path('gestion/planillas-juego/nueva/', views.gestion_planilla_juego_nueva, name='gestion_planilla_juego_nueva'),
    path('gestion/generar-fixture/', views.gestion_generar_fixture, name='gestion_generar_fixture'),
    path('gestion/validaciones/', views.gestion_validaciones, name='gestion_validaciones'),
    path('gestion/validaciones/<int:solicitud_id>/resolver/', views.gestion_validacion_resolver, name='gestion_validacion_resolver'),
    path('gestion/equipos/', views.gestion_equipos, name='gestion_equipos'),
    path('gestion/equipos/acceso-delegado-masivo/', views.gestion_equipos_acceso_delegado_masivo, name='gestion_equipos_acceso_delegado_masivo'),
    path('gestion/equipos/crear-delegados-masivo/', views.gestion_equipos_crear_delegados_masivo, name='gestion_equipos_crear_delegados_masivo'),
    path('gestion/equipos/renombrar-delegados-masivo/', views.gestion_equipos_renombrar_delegados_masivo, name='gestion_equipos_renombrar_delegados_masivo'),
    path('gestion/equipos/permisos-delegados-masivo/', views.gestion_equipos_permisos_delegados_masivo, name='gestion_equipos_permisos_delegados_masivo'),
    path('gestion/equipos/nuevo/', views.gestion_equipo_nuevo, name='gestion_equipo_nuevo'),
    path('gestion/equipos/<int:equipo_id>/editar/', views.gestion_equipo_editar, name='gestion_equipo_editar'),
    path('gestion/equipos/<int:equipo_id>/reinscribir/', views.gestion_equipo_reinscribir, name='gestion_equipo_reinscribir'),
    path('gestion/equipos/<int:equipo_id>/jugadores/guardar/', views.gestion_equipo_jugadores_guardar, name='gestion_equipo_jugadores_guardar'),
    path('gestion/equipos/<int:equipo_id>/eliminar/', views.gestion_equipo_eliminar, name='gestion_equipo_eliminar'),
    path('gestion/jugadores/', views.gestion_jugadores, name='gestion_jugadores'),
    path('gestion/jugadores/importar-planilla/', views.gestion_importar_planilla, name='gestion_importar_planilla'),
    path('gestion/jugadores/nuevo/', views.gestion_jugador_nuevo, name='gestion_jugador_nuevo'),
    path('gestion/jugadores/<int:jugador_id>/editar/', views.gestion_jugador_editar, name='gestion_jugador_editar'),
    path('gestion/jugadores/<int:jugador_id>/eliminar/', views.gestion_jugador_eliminar, name='gestion_jugador_eliminar'),
    path('gestion/partidos/', views.gestion_partidos, name='gestion_partidos'),
    path('gestion/partidos/importar/', views.gestion_importar_partidos, name='gestion_importar_partidos'),
    path('gestion/partidos/nuevo/', views.gestion_partido_nuevo, name='gestion_partido_nuevo'),
    path('gestion/partidos/<int:partido_id>/editar/', views.gestion_partido_editar, name='gestion_partido_editar'),
    path('gestion/partidos/<int:partido_id>/eliminar/', views.gestion_partido_eliminar, name='gestion_partido_eliminar'),
    path('gestion/partidos/<int:partido_id>/confirmar-programacion/', views.gestion_partido_confirmar_programacion, name='gestion_partido_confirmar_programacion'),
    path('gestion/partidos/<int:partido_id>/validar-estadisticas/', views.gestion_partido_validar_estadisticas, name='gestion_partido_validar_estadisticas'),
    path('partido/<int:partido_id>/cronometro/primer-tiempo/', views.cronometro_primer_tiempo, name='cronometro_primer_tiempo'),
    path('partido/<int:partido_id>/cronometro/entretiempo/', views.cronometro_entretiempo, name='cronometro_entretiempo'),
    path('partido/<int:partido_id>/cronometro/segundo-tiempo/', views.cronometro_segundo_tiempo, name='cronometro_segundo_tiempo'),
    path('partido/<int:partido_id>/cronometro/pausar/', views.cronometro_pausar, name='cronometro_pausar'),
    path('partido/<int:partido_id>/cronometro/reanudar/', views.cronometro_reanudar, name='cronometro_reanudar'),
    path('partido/<int:partido_id>/cronometro/suspender/', views.cronometro_suspender, name='cronometro_suspender'),
    path('partido/<int:partido_id>/cronometro/finalizar/', views.cronometro_finalizar, name='cronometro_finalizar'),
    path('partido/<int:partido_id>/cronometro/penales/iniciar/', views.iniciar_tanda_penales, name='iniciar_tanda_penales'),
    path('partido/<int:partido_id>/cronometro/penales/cobro/', views.registrar_cobro_penal, name='registrar_cobro_penal'),
    path('partido/<int:partido_id>/cronometro/penales/deshacer/', views.deshacer_cobro_penal, name='deshacer_cobro_penal'),
    path('partido/cronometro/penales/cobro/<int:cobro_id>/modificar/', views.modificar_cobrador_penal, name='modificar_cobrador_penal'),
]

urlpatterns += [
    path(
        'gestion/partidos/<int:partido_id>/planilla-pdf/',
        views.descargar_planilla_juego_partido,
        name='descargar_planilla_juego_partido',
    ),
    path(
        'gestion/partidos/planillas-pdf/categoria/<int:categoria_id>/',
        views.descargar_planillas_juego_categoria,
        name='descargar_planillas_juego_categoria',
    ),
    path(
        'gestion/partidos/planillas-pdf/torneo/',
        views.descargar_planillas_juego_torneo,
        name='descargar_planillas_juego_torneo',
    ),
]
