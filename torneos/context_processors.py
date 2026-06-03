from django.db import connection
from django.db.models import Q

from .models import SolicitudValidacion


def tabla_disponible(nombre_tabla):
    try:
        return nombre_tabla in connection.introspection.table_names()
    except Exception:
        return False


def validaciones_pendientes(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return {"validaciones_pendientes_count": 0}
    if not tabla_disponible("torneos_solicitudvalidacion"):
        return {"validaciones_pendientes_count": 0}

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

    return {"validaciones_pendientes_count": solicitudes.count()}
