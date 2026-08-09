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
        if request.method in self.metodos_escritura and getattr(request.user, "is_authenticated", False):
            request._contexto_auditoria = self._contexto_operacion(request)
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
        contexto = getattr(request, "_contexto_auditoria", {}) or {}
        accion = contexto.get("accion") or (vista.upper()[:40] if vista else "MODIFICAR")
        registrar_actividad(
            request,
            accion,
            objeto=contexto.get("objeto"),
            torneo=contexto.get("torneo") or torneo,
            descripcion=contexto.get("descripcion") or f"Ejecutó {vista.replace('_', ' ') or request.method} en {request.path}.",
            datos={
                "metodo": request.method,
                "ruta": request.path[:500],
                "vista": vista[:120],
                **contexto.get("datos", {}),
            },
        )

    def _contexto_operacion(self, request):
        """Resume la operación sin conservar campos sensibles del formulario."""
        from .models import AlineacionPartido, CobroPenal, Equipo, Gol, Jugador, Partido, SustitucionPartido, Tarjeta

        coincidencia = getattr(request, "resolver_match", None)
        vista = getattr(coincidencia, "url_name", "") or ""
        kwargs = getattr(coincidencia, "kwargs", {}) or {}
        partido = None
        objeto = None
        partido_id = kwargs.get("partido_id")
        if partido_id:
            partido = Partido.objects.select_related(
                "categoria__torneo", "equipo_local", "equipo_visitante",
            ).filter(id=partido_id).first()
            objeto = partido
        else:
            relaciones = (
                ("gol_id", Gol), ("tarjeta_id", Tarjeta),
                ("alineacion_id", AlineacionPartido),
                ("sustitucion_id", SustitucionPartido), ("cobro_id", CobroPenal),
            )
            for llave, modelo in relaciones:
                if kwargs.get(llave):
                    objeto = modelo.objects.select_related(
                        "partido__categoria__torneo", "partido__equipo_local", "partido__equipo_visitante",
                    ).filter(id=kwargs[llave]).first()
                    partido = getattr(objeto, "partido", None)
                    break

        equipo_id = request.POST.get("equipo") or kwargs.get("equipo_id")
        equipo = Equipo.objects.select_related("categoria__torneo").filter(id=equipo_id).first() if str(equipo_id or "").isdigit() else None
        jugador_id = request.POST.get("jugador") or kwargs.get("jugador_id")
        jugador = Jugador.objects.select_related("equipo").filter(id=jugador_id).first() if str(jugador_id or "").isdigit() else None
        jugador_solicitado = jugador
        jugador_sale_id = request.POST.get("jugador_sale")
        jugador_entra_id = request.POST.get("jugador_entra")
        jugador_sale = Jugador.objects.select_related("equipo").filter(id=jugador_sale_id).first() if str(jugador_sale_id or "").isdigit() else None
        jugador_entra = Jugador.objects.select_related("equipo").filter(id=jugador_entra_id).first() if str(jugador_entra_id or "").isdigit() else None
        if isinstance(objeto, SustitucionPartido):
            equipo = objeto.equipo
            jugador_sale = objeto.jugador_sale
            jugador_entra = objeto.jugador_entra
        elif isinstance(objeto, (Gol, Tarjeta, AlineacionPartido, CobroPenal)):
            equipo = objeto.equipo
            jugador = objeto.jugador
        if vista == "deshacer_cobro_penal" and partido:
            objeto = partido.cobros_penales.select_related("equipo", "jugador").order_by("-orden", "-id").first()
            if objeto:
                equipo = objeto.equipo
                jugador = objeto.jugador
        if vista in {"iniciar_tanda_penales", "cambiar_equipo_inicia_penales"} and partido:
            equipo_inicial_id = request.POST.get("equipo_inicia_penales")
            if str(equipo_inicial_id or "").isdigit():
                equipo = Equipo.objects.filter(id=equipo_inicial_id).first()
        datos = {}
        partes = []
        if partido:
            partes.append(f"Partido #{partido.id}: {partido.equipo_local.nombre} vs {partido.equipo_visitante.nombre}.")
            datos.update({"partido_id": partido.id, "equipo_local": partido.equipo_local.nombre, "equipo_visitante": partido.equipo_visitante.nombre})
        if equipo:
            datos.update({"equipo_id": equipo.id, "equipo": equipo.nombre})
        if jugador:
            datos.update({"jugador_id": jugador.id, "jugador": jugador.nombres})
        if jugador_sale:
            datos.update({"jugador_sale_id": jugador_sale.id, "jugador_sale": jugador_sale.nombres})
        if jugador_entra:
            datos.update({"jugador_entra_id": jugador_entra.id, "jugador_entra": jugador_entra.nombres})

        etiquetas = {
            "guardar_info_partido_movil": ("ACTUALIZAR_PARTIDO", "Actualizó la información general del partido."),
            "agregar_gol_movil": ("REGISTRAR_GOL", "Registró un gol."),
            "agregar_tarjeta_movil": ("REGISTRAR_INFRACCION", "Registró una infracción disciplinaria."),
            "agregar_alineacion_movil": ("AGREGAR_ALINEACION", "Agregó un jugador a la alineación."),
            "guardar_alineacion_masiva_movil": ("GUARDAR_ALINEACION", "Guardó la alineación del equipo."),
            "agregar_sustitucion_movil": ("REGISTRAR_SUSTITUCION", "Registró una sustitución."),
            "eliminar_gol_movil": ("ELIMINAR_GOL", "Eliminó un gol registrado."),
            "eliminar_tarjeta_movil": ("ELIMINAR_INFRACCION", "Eliminó una tarjeta registrada."),
            "eliminar_alineacion_movil": ("ELIMINAR_ALINEACION", "Retiró un jugador de la alineación."),
            "eliminar_sustitucion_movil": ("ELIMINAR_SUSTITUCION", "Eliminó una sustitución."),
            "cronometro_primer_tiempo": ("INICIAR_PRIMER_TIEMPO", "Inició el primer tiempo."),
            "cronometro_entretiempo": ("MARCAR_ENTRETIEMPO", "Marcó el entretiempo."),
            "cronometro_segundo_tiempo": ("INICIAR_SEGUNDO_TIEMPO", "Inició el segundo tiempo."),
            "cronometro_pausar": ("PAUSAR_CRONOMETRO", "Pausó el cronómetro."),
            "cronometro_reanudar": ("REANUDAR_CRONOMETRO", "Reanudó el cronómetro."),
            "cronometro_suspender": ("SUSPENDER_PARTIDO", "Suspendió el partido."),
            "cronometro_finalizar": ("FINALIZAR_PARTIDO", "Finalizó el partido."),
            "preparar_tanda_penales": ("PREPARAR_PENALES", "Activó la sección de tanda de penales."),
            "iniciar_tanda_penales": ("INICIAR_PENALES", "Inició la tanda de penales."),
            "registrar_cobro_penal": ("REGISTRAR_COBRO_PENAL", "Registró un cobro de la tanda de penales."),
            "deshacer_cobro_penal": ("DESHACER_COBRO_PENAL", "Eliminó el último cobro de la tanda."),
            "modificar_cobrador_penal": ("MODIFICAR_COBRADOR_PENAL", "Corrigió el cobrador de un penal."),
        }
        accion, detalle = etiquetas.get(vista, (vista.upper()[:40] or "MODIFICAR", f"Ejecutó la acción {vista.replace('_', ' ')}."))
        partes.append(detalle)

        if vista == "guardar_info_partido_movil" and partido:
            gl = request.POST.get("goles_local", partido.goles_local)
            gv = request.POST.get("goles_visitante", partido.goles_visitante)
            estado = request.POST.get("estado", partido.estado)
            partes.append(f"Marcador informado: {partido.equipo_local.nombre} {gl} - {gv} {partido.equipo_visitante.nombre}. Estado: {estado}.")
            datos.update({"goles_local": gl, "goles_visitante": gv, "estado": estado})
        elif vista == "agregar_tarjeta_movil":
            afectado = equipo or getattr(jugador, "equipo", None)
            tipo = (request.POST.get("tipo") or "tarjeta").upper()
            minuto = request.POST.get("minuto") or request.POST.get("minuto_manual") or "cronómetro en vivo"
            partes.append(f"Equipo infractor: {afectado.nombre if afectado else 'por identificar'}. Jugador: {jugador.nombres if jugador else 'por identificar'}. Tipo: {tipo}. Minuto: {minuto}.")
            datos.update({"tipo_infraccion": tipo, "minuto": minuto})
        elif vista == "agregar_gol_movil":
            afectado = equipo or getattr(jugador, "equipo", None)
            minuto = request.POST.get("minuto") or request.POST.get("minuto_manual") or "cronómetro en vivo"
            partes.append(f"Equipo que anotó: {afectado.nombre if afectado else 'por identificar'}. Jugador: {jugador.nombres if jugador else 'por identificar'}. Minuto: {minuto}.")
            datos.update({"minuto": minuto, "cantidad": request.POST.get("cantidad") or "1"})
        elif vista == "registrar_cobro_penal":
            resultado = "ANOTÓ" if request.POST.get("resultado") == "GOL" else "FALLÓ"
            partes.append(
                f"Equipo cobrador: {equipo.nombre if equipo else getattr(getattr(jugador, 'equipo', None), 'nombre', 'por identificar')}. "
                f"Cobrador: {jugador.nombres if jugador else 'por identificar'}. Resultado: {resultado}."
            )
            datos.update({"resultado_cobro": resultado})
        elif vista == "deshacer_cobro_penal":
            partes.append(
                f"Cobro eliminado: {jugador.nombres if jugador else 'por identificar'}, "
                f"equipo {equipo.nombre if equipo else 'por identificar'}, orden #{getattr(objeto, 'orden', 'por identificar')}."
            )
            datos.update({"orden_cobro": getattr(objeto, "orden", None)})
        elif vista == "modificar_cobrador_penal":
            partes.append(
                f"Cobro #{getattr(objeto, 'orden', 'por identificar')}, equipo {equipo.nombre if equipo else 'por identificar'}. "
                f"Cambió cobrador de {jugador.nombres if jugador else 'por identificar'} "
                f"a {jugador_solicitado.nombres if jugador_solicitado else 'por identificar'}."
            )
            datos.update({
                "cobrador_anterior": jugador.nombres if jugador else "",
                "cobrador_nuevo": jugador_solicitado.nombres if jugador_solicitado else "",
            })
        elif vista in {"iniciar_tanda_penales", "cambiar_equipo_inicia_penales"}:
            partes.append(f"Equipo seleccionado para cobrar primero: {equipo.nombre if equipo else 'por identificar'}.")
        elif vista in {"eliminar_gol_movil", "eliminar_tarjeta_movil", "eliminar_alineacion_movil"}:
            partes.append(
                f"Equipo: {equipo.nombre if equipo else 'por identificar'}. "
                f"Jugador: {jugador.nombres if jugador else 'por identificar'}."
            )
        elif vista in {"agregar_sustitucion_movil", "eliminar_sustitucion_movil"}:
            minuto = request.POST.get("minuto") or getattr(objeto, "minuto", None) or "cronómetro en vivo"
            partes.append(
                f"Equipo: {equipo.nombre if equipo else 'por identificar'}. "
                f"Salió: {jugador_sale.nombres if jugador_sale else 'por identificar'}. "
                f"Entró: {jugador_entra.nombres if jugador_entra else 'por identificar'}. Minuto: {minuto}."
            )
            datos.update({"minuto": minuto})
        elif equipo:
            partes.append(f"Equipo modificado: {equipo.nombre}.")
        elif jugador:
            partes.append(f"Jugador involucrado: {jugador.nombres}, equipo {jugador.equipo.nombre}.")

        torneo = partido.categoria.torneo if partido else getattr(getattr(equipo, "categoria", None), "torneo", None)
        return {"accion": accion, "descripcion": " ".join(partes), "datos": datos, "objeto": objeto, "torneo": torneo}

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
