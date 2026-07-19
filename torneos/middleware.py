from django.http import HttpResponseBase


class AuditoriaModificacionesMiddleware:
    """Registra una sola huella liviana por operación de escritura exitosa."""

    metodos_escritura = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._registrar_si_aplica(request, response)
        return response

    def _registrar_si_aplica(self, request, response):
        if request.method not in self.metodos_escritura:
            return
        if not isinstance(response, HttpResponseBase) or response.status_code >= 400:
            return
        if not getattr(request.user, "is_authenticated", False):
            return
        if getattr(request, "_actividad_registrada", False):
            return

        from .models import Torneo
        from .views import registrar_actividad

        torneo = None
        torneo_id = request.session.get("torneo_id")
        if torneo_id:
            torneo = Torneo.objects.filter(id=torneo_id).first()

        coincidencia = getattr(request, "resolver_match", None)
        vista = getattr(coincidencia, "url_name", "") or ""
        registrar_actividad(
            request,
            "MODIFICAR",
            torneo=torneo,
            descripcion=f"Operación {request.method} en {request.path}.",
            datos={
                "metodo": request.method,
                "ruta": request.path[:500],
                "vista": vista[:120],
            },
        )
