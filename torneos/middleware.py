import uuid

from django.core.signing import salted_hmac
from django.http import HttpResponseBase
from django.utils import timezone


class AuditoriaModificacionesMiddleware:
    """Registra una sola huella liviana por operación de escritura exitosa."""

    metodos_escritura = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._registrar_si_aplica(request, response)
        self._registrar_visita_publica(request, response)
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

    def _registrar_visita_publica(self, request, response):
        if request.method != "GET" or response.status_code >= 400:
            return
        if getattr(request.user, "is_authenticated", False):
            return

        coincidencia = getattr(request, "resolver_match", None)
        vista = getattr(coincidencia, "url_name", "") or ""
        if vista not in {"panel", "partido_live", "partido_detalle_publico"}:
            return

        from .models import Partido, Torneo, VisitaPublicaDiaria

        torneo_id = request.session.get("torneo_id")
        if not torneo_id and vista in {"partido_live", "partido_detalle_publico"}:
            partido_id = (getattr(coincidencia, "kwargs", {}) or {}).get("partido_id")
            torneo_id = Partido.objects.filter(id=partido_id).values_list(
                "categoria__torneo_id", flat=True,
            ).first()

        torneo = Torneo.objects.filter(id=torneo_id).first() if torneo_id else None
        if not torneo:
            return
        fecha = timezone.localdate()
        marcador = f"{fecha.isoformat()}:{torneo_id or 0}"
        if request.COOKIES.get("pahevi_visita_contada") == marcador:
            return

        identificador = request.COOKIES.get("pahevi_visitante") or uuid.uuid4().hex
        visitante_hash = salted_hmac("visita-publica", identificador).hexdigest()
        user_agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
        if request.GET.get("app") == "1" or any(item in user_agent for item in ("capacitor", "; wv)", "pahevi")):
            canal = "APK"
        elif any(item in user_agent for item in ("android", "iphone", "ipad", "mobile")):
            canal = "MOVIL"
        else:
            canal = "ESCRITORIO"

        VisitaPublicaDiaria.objects.get_or_create(
            fecha=fecha,
            torneo=torneo,
            visitante_hash=visitante_hash,
            defaults={"canal": canal},
        )
        response.set_cookie(
            "pahevi_visitante",
            identificador,
            max_age=31536000,
            httponly=True,
            samesite="Lax",
            secure=request.is_secure(),
        )
        response.set_cookie(
            "pahevi_visita_contada",
            marcador,
            max_age=86400,
            httponly=True,
            samesite="Lax",
            secure=request.is_secure(),
        )
