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

    # Este context processor se ejecuta en todas las paginas renderizadas.
    # Mantenerlo sin consultas evita que un conteo lento tumbe el login en Render.
    return {
        "validaciones_pendientes_count": 0,
        "puede_editar": user.is_superuser,
        "puede_validar": user.is_superuser,
        "puede_programar": user.is_superuser,
        "puede_descargar_planillas": user.is_superuser,
    }
