from django.db import connection
from django.db.models import Q

from .models import AdminOrganizador, AdminTorneo, SolicitudValidacion, Torneo


def tabla_disponible(nombre_tabla):
    try:
        return nombre_tabla in connection.introspection.table_names()
    except Exception:
        return False


def validaciones_pendientes(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return {
            "validaciones_pendientes_count": 0,
            "puede_editar": False,
            "puede_validar": False,
            "puede_programar": False,
            "puede_descargar_planillas": False,
        }

    permisos = {
        "puede_editar": user.is_superuser,
        "puede_validar": user.is_superuser,
        "puede_programar": user.is_superuser,
        "puede_descargar_planillas": user.is_superuser,
    }
    torneo_id = request.session.get("torneo_id")
    torneo = Torneo.objects.filter(id=torneo_id).first() if torneo_id and tabla_disponible("torneos_torneo") else None
    if not user.is_superuser and torneo and tabla_disponible("torneos_admintorneo"):
        permiso_torneo = AdminTorneo.objects.filter(usuario=user, torneo=torneo, activo=True).first()
        permiso_organizador = None
        if tabla_disponible("torneos_adminorganizador") and getattr(torneo, "organizador_id", None):
            permiso_organizador = AdminOrganizador.objects.filter(
                usuario=user,
                organizador_id=torneo.organizador_id,
                activo=True,
            ).first()
        for permiso in (permiso_torneo, permiso_organizador):
            if permiso:
                permisos["puede_editar"] = permisos["puede_editar"] or permiso.puede_editar
                permisos["puede_validar"] = permisos["puede_validar"] or permiso.puede_validar
                permisos["puede_programar"] = permisos["puede_programar"] or permiso.puede_programar
                permisos["puede_descargar_planillas"] = (
                    permisos["puede_descargar_planillas"]
                    or getattr(permiso, "puede_descargar_planillas", False)
                )

    if not tabla_disponible("torneos_solicitudvalidacion"):
        return {"validaciones_pendientes_count": 0, **permisos}

    solicitudes = SolicitudValidacion.objects.filter(estado="PENDIENTE")
    if not user.is_superuser:
        if not tabla_disponible("torneos_admintorneo"):
            return {"validaciones_pendientes_count": solicitudes.count()}
        filtro = Q(
            torneo__admins_asignados__usuario=user,
            torneo__admins_asignados__activo=True,
            torneo__admins_asignados__puede_validar=True,
        )
        if tabla_disponible("torneos_adminorganizador"):
            filtro |= Q(
                torneo__organizador__admins_asignados__usuario=user,
                torneo__organizador__admins_asignados__activo=True,
                torneo__organizador__admins_asignados__puede_validar=True,
            )
        solicitudes = solicitudes.filter(filtro).distinct()

    return {"validaciones_pendientes_count": solicitudes.count(), **permisos}
