from collections import defaultdict
from types import SimpleNamespace
from datetime import date, datetime, time, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
import re
import uuid
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.http import FileResponse, HttpResponse, HttpResponseForbidden
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils.html import escape
from django.utils.http import url_has_allowed_host_and_scheme
from html2image import Html2Image
import requests
from django.views.decorators.http import require_POST
from openpyxl import load_workbook

from .forms import TorneoForm, OrganizadorForm, CategoriaForm, DocumentoForm, EquipoForm, EquipoDelegadoForm, JugadorForm, JugadorDelegadoForm, PartidoForm, AdminTorneoForm, AdminOrganizadorForm
from .models import Torneo, Organizador, Categoria, Documento, Equipo, Partido, Gol, Tarjeta, Jugador, AlineacionPartido, SustitucionPartido, ReglaEdadCategoria, AdminTorneo, AdminOrganizador, RegistroActividad, limpiar_ruta_cloudinary
from django.utils import timezone

def es_editor_torneo(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not user.is_staff:
        return False
    if not tabla_disponible("torneos_admintorneo"):
        return True
    tiene_torneos = AdminTorneo.objects.filter(usuario=user, activo=True).exists()
    tiene_organizadores = (
        tabla_disponible("torneos_adminorganizador")
        and AdminOrganizador.objects.filter(usuario=user, activo=True).exists()
    )
    return tiene_torneos or tiene_organizadores


def es_superadmin(user):
    return user.is_authenticated and user.is_superuser


def puede_diligenciar_partido(user, partido):
    if user.is_authenticated and user.is_superuser:
        return True
    if user.is_authenticated and user.is_staff and partido:
        if not tabla_disponible("torneos_admintorneo"):
            return True
        return usuario_puede_editar_torneo(user, partido.categoria.torneo if partido.categoria_id else None)
    if not user.is_authenticated or not partido:
        return False
    if partido.estado == "FINALIZADO":
        return False
    return partido.planilleros.filter(id=user.id).exists()


def denegar_partido_no_autorizado():
    return HttpResponseForbidden("No tienes permiso para editar este partido.")


def equipos_delegado_vigentes(user):
    if not user.is_authenticated:
        return Equipo.objects.none()
    return Equipo.objects.select_related("categoria").filter(
        responsable=user,
        acceso_delegado_hasta__gte=timezone.now(),
    )


def equipos_delegado_asignados(user):
    if not user.is_authenticated:
        return Equipo.objects.none()
    return Equipo.objects.select_related("categoria").filter(responsable=user)


def puede_editar_equipo_delegado(user, equipo):
    if user.is_authenticated and user.is_superuser:
        return True
    if user.is_authenticated and user.is_staff:
        if not tabla_disponible("torneos_admintorneo"):
            return True
        return usuario_puede_editar_torneo(user, equipo.categoria.torneo if equipo.categoria_id else None)
    return bool(
        user.is_authenticated
        and equipo.responsable_id == user.id
        and equipo.acceso_delegado_vigente()
    )


def equipos_editables_para_usuario(user):
    equipos = Equipo.objects.select_related("categoria")
    if user.is_authenticated and user.is_superuser:
        return equipos
    if user.is_authenticated and user.is_staff:
        if not tabla_disponible("torneos_admintorneo"):
            return equipos
        filtro = Q(categoria__torneo__admins_asignados__usuario=user, categoria__torneo__admins_asignados__activo=True)
        if tabla_disponible("torneos_adminorganizador"):
            filtro |= Q(categoria__torneo__organizador__admins_asignados__usuario=user, categoria__torneo__organizador__admins_asignados__activo=True)
        return equipos.filter(filtro).distinct()
    return equipos_delegado_vigentes(user)


def equipos_alineacion_para_usuario(user):
    equipos = Equipo.objects.select_related("categoria")
    if user.is_authenticated and user.is_superuser:
        return equipos
    if user.is_authenticated and user.is_staff:
        if not tabla_disponible("torneos_admintorneo"):
            return equipos
        filtro = Q(categoria__torneo__admins_asignados__usuario=user, categoria__torneo__admins_asignados__activo=True)
        if tabla_disponible("torneos_adminorganizador"):
            filtro |= Q(categoria__torneo__organizador__admins_asignados__usuario=user, categoria__torneo__organizador__admins_asignados__activo=True)
        return equipos.filter(filtro).distinct()
    return equipos_delegado_asignados(user)


def inicio_programado_partido(partido):
    if not partido.fecha or not partido.hora:
        return None
    inicio = datetime.combine(partido.fecha, partido.hora)
    if timezone.is_naive(inicio):
        return timezone.make_aware(inicio, timezone.get_current_timezone())
    return inicio


def ventana_alineacion_delegado(partido, ahora=None):
    ahora = ahora or timezone.now()
    if partido.estado == "PROGRAMADO":
        inicio = inicio_programado_partido(partido)
        if not inicio:
            return False, "Sin fecha u hora programada."
        if ahora < inicio:
            return False, f"Disponible desde {inicio.strftime('%d/%m/%Y %H:%M')}."
        return True, "Disponible por hora programada."
    if partido.estado == "EN_JUEGO":
        if not partido.inicio_en_vivo:
            return False, "El partido esta en juego, pero no tiene hora de inicio registrada."
        cierre = partido.inicio_en_vivo + timedelta(minutes=10)
        if ahora <= cierre:
            return True, f"Disponible hasta {cierre.strftime('%H:%M')}."
        return False, "La ventana de 10 minutos ya finalizo."
    return False, "Disponible solo en partidos programados o en los primeros 10 minutos de juego."


def partido_pertenece_equipo(partido, equipo):
    return equipo.id in [partido.equipo_local_id, partido.equipo_visitante_id]


def puede_editar_alineacion_delegado(user, partido, equipo):
    if user.is_authenticated and user.is_superuser:
        return partido_pertenece_equipo(partido, equipo)
    if user.is_authenticated and user.is_staff:
        if not tabla_disponible("torneos_admintorneo"):
            return partido_pertenece_equipo(partido, equipo)
        return partido_pertenece_equipo(partido, equipo) and usuario_puede_editar_torneo(user, partido.categoria.torneo if partido.categoria_id else None)
    if not user.is_authenticated or equipo.responsable_id != user.id:
        return False
    if not partido_pertenece_equipo(partido, equipo):
        return False
    habilitado, _ = ventana_alineacion_delegado(partido)
    return habilitado


def partidos_alineacion_para_equipo(equipo):
    partidos = Partido.objects.select_related(
        "categoria",
        "equipo_local",
        "equipo_visitante",
    ).filter(
        categoria=equipo.categoria,
    ).filter(
        Q(equipo_local=equipo) | Q(equipo_visitante=equipo)
    ).filter(
        estado__in=["PROGRAMADO", "EN_JUEGO"]
    ).order_by("fecha", "hora", "id")

    items = []
    for partido in partidos:
        habilitado, motivo = ventana_alineacion_delegado(partido)
        items.append(SimpleNamespace(
            partido=partido,
            rival=partido.equipo_visitante if partido.equipo_local_id == equipo.id else partido.equipo_local,
            habilitado=habilitado,
            motivo=motivo,
        ))
    return items


def equipo_delegado_para_partido(user, partido):
    if not user.is_authenticated or not partido or es_editor_torneo(user):
        return None
    return equipos_delegado_asignados(user).filter(
        id__in=[partido.equipo_local_id, partido.equipo_visitante_id],
    ).first()


def url_alineacion_delegado_si_aplica(user, partido):
    equipo = equipo_delegado_para_partido(user, partido)
    if not equipo:
        return ""
    habilitado, _ = ventana_alineacion_delegado(partido)
    if not habilitado:
        return ""
    return reverse("delegado_alineacion_partido", args=[equipo.id, partido.id])


class IngresoTorneosView(LoginView):
    template_name = "registration/login.html"

    def get_success_url(self):
        if (
            self.request.user.is_authenticated
            and not es_editor_torneo(self.request.user)
            and equipos_delegado_asignados(self.request.user).exists()
        ):
            return reverse("delegado_mis_equipos")
        return super().get_success_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        if es_editor_torneo(user):
            messages.success(self.request, "Acceso exitoso. Bienvenido al panel de gestion.")
        elif equipos_delegado_asignados(user).exists():
            messages.success(self.request, "Acceso exitoso. Bienvenido al portal de delegados.")
        elif user.partidos_planillero.exclude(estado="FINALIZADO").exists():
            messages.success(self.request, "Acceso exitoso. Ya puedes diligenciar tus partidos asignados.")
        else:
            messages.success(self.request, "Acceso exitoso.")
        return response

    def get_default_redirect_url(self):
        if (
            self.request.user.is_authenticated
            and not es_editor_torneo(self.request.user)
            and equipos_delegado_asignados(self.request.user).exists()
        ):
            return reverse("delegado_mis_equipos")
        return super().get_default_redirect_url()


ESTADOS_PLANILLERO_PARTIDO = {"PROGRAMADO", "EN_JUEGO", "FINALIZADO", "SUSPENDIDO"}


def entero_post(request, campo, predeterminado=0, minimo=None):
    try:
        valor = int(request.POST.get(campo, predeterminado) or predeterminado)
    except (TypeError, ValueError):
        valor = predeterminado
    if minimo is not None:
        valor = max(valor, minimo)
    return valor


def tabla_disponible(nombre_tabla):
    try:
        return nombre_tabla in connection.introspection.table_names()
    except Exception:
        return False


def torneos_para_usuario(request):
    # No usamos select_related ni filtros por Organizador aqui porque Render puede
    # servir el codigo nuevo unos segundos antes de aplicar la migracion.
    torneos = Torneo.objects.order_by("-fecha_inicio", "nombre")
    usuario = getattr(request, "user", None)

    if not usuario or not usuario.is_authenticated:
        return torneos

    if usuario.is_superuser:
        return torneos

    if usuario.is_staff and tabla_disponible("torneos_admintorneo"):
        filtro = Q(admins_asignados__usuario=usuario, admins_asignados__activo=True)
        if tabla_disponible("torneos_adminorganizador"):
            filtro |= Q(organizador__admins_asignados__usuario=usuario, organizador__admins_asignados__activo=True)
        return torneos.filter(filtro).distinct()

    return torneos


def permisos_torneo_usuario(user, torneo):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return SimpleNamespace(puede_editar=True, puede_validar=True, puede_programar=True, activo=True)
    if not user.is_staff or not torneo or not tabla_disponible("torneos_admintorneo"):
        return None
    permiso_torneo = AdminTorneo.objects.filter(usuario=user, torneo=torneo, activo=True).first()
    permiso_organizador = None
    if (
        tabla_disponible("torneos_adminorganizador")
        and getattr(torneo, "organizador_id", None)
    ):
        permiso_organizador = AdminOrganizador.objects.filter(
            usuario=user,
            organizador_id=torneo.organizador_id,
            activo=True,
        ).first()

    if permiso_torneo and permiso_organizador:
        return SimpleNamespace(
            puede_editar=permiso_torneo.puede_editar or permiso_organizador.puede_editar,
            puede_validar=permiso_torneo.puede_validar or permiso_organizador.puede_validar,
            puede_programar=permiso_torneo.puede_programar or permiso_organizador.puede_programar,
            activo=True,
        )

    return permiso_torneo or permiso_organizador


def usuario_puede_editar_torneo(user, torneo):
    permisos = permisos_torneo_usuario(user, torneo)
    return bool(permisos and permisos.puede_editar)


def usuario_puede_validar_torneo(user, torneo):
    permisos = permisos_torneo_usuario(user, torneo)
    return bool(permisos and permisos.puede_validar)


def usuario_puede_programar_torneo(user, torneo):
    permisos = permisos_torneo_usuario(user, torneo)
    return bool(permisos and permisos.puede_programar)


def denegar_permiso_torneo():
    return HttpResponseForbidden("No tienes permiso para manipular este torneo.")


def puede_gestionar_torneo(request, torneo, permiso="editar"):
    if request.user.is_superuser:
        return True
    if not tabla_disponible("torneos_admintorneo"):
        return True
    if permiso == "validar":
        return usuario_puede_validar_torneo(request.user, torneo)
    if permiso == "programar":
        return usuario_puede_programar_torneo(request.user, torneo)
    return usuario_puede_editar_torneo(request.user, torneo)


def ip_cliente(request):
    encabezado = request.META.get("HTTP_X_FORWARDED_FOR")
    if encabezado:
        return encabezado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def registrar_actividad(request, accion, objeto=None, torneo=None, descripcion="", datos=None):
    if not tabla_disponible("torneos_registroactividad"):
        return

    if not torneo and objeto is not None:
        torneo = torneo_de_objeto(objeto)

    RegistroActividad.objects.create(
        usuario=request.user if request.user.is_authenticated else None,
        torneo=torneo,
        accion=accion,
        modelo=objeto.__class__.__name__ if objeto is not None else "",
        objeto_id=getattr(objeto, "id", None),
        objeto_repr=str(objeto)[:255] if objeto is not None else "",
        descripcion=descripcion,
        datos=datos or {},
        ip=ip_cliente(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )


def torneo_de_objeto(objeto):
    if isinstance(objeto, Torneo):
        return objeto
    if isinstance(objeto, Categoria):
        return objeto.torneo
    if isinstance(objeto, Documento):
        return objeto.torneo
    if isinstance(objeto, Equipo):
        return objeto.categoria.torneo if objeto.categoria_id else None
    if isinstance(objeto, Jugador):
        return objeto.equipo.categoria.torneo if objeto.equipo_id and objeto.equipo.categoria_id else None
    if isinstance(objeto, Partido):
        return objeto.categoria.torneo if objeto.categoria_id else None
    return None


def organizador_seguro(torneo):
    if torneo.organizador_id:
        try:
            return torneo.organizador
        except Exception:
            return None
    return None


def nombre_organizador_torneo(torneo):
    organizador = organizador_seguro(torneo)
    if organizador:
        return organizador.nombre.strip() or torneo.nombre
    return torneo.nombre


def organizadores_para_portal(torneos):
    organizadores = {}
    independientes = []

    for torneo in torneos:
        organizador = organizador_seguro(torneo)
        if organizador:
            grupo = organizadores.get(torneo.organizador_id)
            if not grupo:
                grupo = SimpleNamespace(
                    id=torneo.organizador_id,
                    nombre=nombre_organizador_torneo(torneo),
                    logo=organizador.logo or torneo.logo_portada,
                    torneos=[],
                    es_organizador=True,
                )
                organizadores[torneo.organizador_id] = grupo
            if not grupo.logo and torneo.logo_portada:
                grupo.logo = torneo.logo_portada
            grupo.torneos.append(torneo)
        else:
            independientes.append(SimpleNamespace(
                id=None,
                nombre=torneo.nombre,
                logo=torneo.logo_portada,
                torneos=[torneo],
                es_organizador=False,
                torneo_id=torneo.id,
            ))

    return list(organizadores.values()) + independientes


def cerrar_sesion(request):
    logout(request)
    return redirect("panel")


def service_worker(request):
    sw_path = finders.find("sw.js")
    if not sw_path:
        return HttpResponse("", content_type="application/javascript")

    with open(sw_path, "r", encoding="utf-8") as archivo:
        response = HttpResponse(archivo.read(), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def torneo_actual(request, auto_seleccionar=True):
    torneos = torneos_para_usuario(request)
    torneo_id = request.GET.get("torneo") or request.session.get("torneo_id")
    torneo = None

    if torneo_id:
        torneo = torneos.filter(id=torneo_id).first()

    if not torneo and auto_seleccionar:
        torneo = torneos.filter(estado="ACTIVO").first() or torneos.first()

    if torneo:
        request.session["torneo_id"] = torneo.id

    return torneo


def listar_imagenes_cloudinary(max_results=80):
    imagenes = []

    if getattr(settings, "USE_CLOUDINARY_STORAGE", False):
        try:
            import cloudinary.api

            configurar = getattr(default_storage, "_configure", None)
            if configurar:
                configurar()

            respuesta = cloudinary.api.resources(
                resource_type="image",
                type="upload",
                max_results=max_results,
            )
        except Exception as exc:
            print(f"No se pudieron listar imagenes de Cloudinary: {exc}")
        else:
            for recurso in respuesta.get("resources", []):
                public_id = recurso.get("public_id", "")
                url = recurso.get("secure_url") or recurso.get("url")
                if not public_id or not url:
                    continue
                if public_id.startswith("documentos/"):
                    continue

                carpeta = public_id.split("/", 1)[0] if "/" in public_id else "General"
                imagenes.append({
                    "public_id": public_id,
                    "url": url,
                    "carpeta": carpeta,
                    "nombre": public_id.rsplit("/", 1)[-1],
                })

    if imagenes:
        return imagenes

    return listar_imagenes_usadas()


def listar_imagenes_usadas():
    imagenes = []
    vistos = set()

    def agregar(nombre, url):
        nombre = str(nombre or "").strip()
        url = str(url or "").strip()
        if not nombre or nombre in vistos:
            return
        vistos.add(nombre)
        imagenes.append({
            "public_id": nombre,
            "url": url,
            "carpeta": nombre.split("/", 1)[0] if "/" in nombre else "General",
            "nombre": nombre.rsplit("/", 1)[-1],
        })

    for equipo in Equipo.objects.exclude(escudo="").exclude(escudo__isnull=True).order_by("nombre"):
        try:
            agregar(equipo.escudo.name, equipo.escudo.url)
        except Exception:
            continue

    for jugador in Jugador.objects.exclude(foto="").exclude(foto__isnull=True).order_by("nombres"):
        try:
            agregar(jugador.foto.name, jugador.foto.url)
        except Exception:
            continue

    return imagenes


def url_imagen_cloudinary(public_id):
    if not public_id:
        return ""

    try:
        configurar = getattr(default_storage, "_configure", None)
        if configurar:
            configurar()

        import cloudinary.utils

        return cloudinary.utils.cloudinary_url(
            str(public_id),
            resource_type="image",
            secure=True,
        )[0]
    except Exception:
        return ""


@login_required
@user_passes_test(es_editor_torneo)
def gestion_biblioteca_cloudinary(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    imagenes = listar_imagenes_cloudinary(500)
    q = request.GET.get("q", "").strip()
    equipos = Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre")
    jugadores = Jugador.objects.select_related("equipo", "equipo__categoria").order_by("equipo__nombre", "nombres")

    if torneo:
        equipos = equipos.filter(categoria__torneo=torneo)
        jugadores = jugadores.filter(equipo__categoria__torneo=torneo)

    if q:
        imagenes = [
            imagen for imagen in imagenes
            if q.lower() in imagen["public_id"].lower()
        ]

    return render(request, "gestion/biblioteca_cloudinary.html", {
        "imagenes": imagenes,
        "q": q,
        "equipos": equipos,
        "jugadores": jugadores,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_asignar_imagen_cloudinary(request):
    if request.method != "POST":
        return redirect("gestion_biblioteca_cloudinary")

    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    public_id = (request.POST.get("public_id") or "").strip()
    tipo = request.POST.get("tipo")
    objeto_id = request.POST.get("objeto_id")

    if not public_id or not tipo or not objeto_id:
        messages.error(request, "Selecciona una imagen y un destino.")
        return redirect("gestion_biblioteca_cloudinary")

    if tipo == "equipo":
        equipos = Equipo.objects.select_related("categoria")
        if torneo:
            equipos = equipos.filter(categoria__torneo=torneo)
        equipo = get_object_or_404(equipos, id=objeto_id)
        equipo.escudo = public_id
        equipo.save(update_fields=["escudo"])
        registrar_actividad(request, "ASIGNAR_IMAGEN", equipo, descripcion=f"Asigno imagen al equipo {equipo.nombre}.")
        messages.success(request, f"Imagen asignada al equipo {equipo.nombre}.")
        return redirect("gestion_equipo_editar", equipo_id=equipo.id)

    if tipo == "jugador":
        jugadores = Jugador.objects.select_related("equipo", "equipo__categoria")
        if torneo:
            jugadores = jugadores.filter(equipo__categoria__torneo=torneo)
        jugador = get_object_or_404(jugadores, id=objeto_id)
        jugador.foto = public_id
        jugador.save(update_fields=["foto"])
        registrar_actividad(request, "ASIGNAR_IMAGEN", jugador, descripcion=f"Asigno imagen al jugador {jugador.nombres}.")
        messages.success(request, f"Imagen asignada al jugador {jugador.nombres}.")
        return redirect("gestion_jugador_editar", jugador_id=jugador.id)

    messages.error(request, "Destino no valido.")
    return redirect("gestion_biblioteca_cloudinary")


def aplicar_imagen_cloudinary(instancia, campo, public_id, archivo_subido):
    public_id = (public_id or "").strip()
    if public_id and not archivo_subido:
        setattr(instancia, campo, public_id)


def subir_imagen_torneo_cloudinary(archivo, torneo, campo):
    if not archivo:
        return ""
    if not getattr(settings, "USE_CLOUDINARY_STORAGE", False):
        return ""

    import cloudinary
    import cloudinary.uploader

    cloudinary_url = getattr(settings, "CLOUDINARY_URL", "").strip()
    if cloudinary_url:
        os.environ["CLOUDINARY_URL"] = cloudinary_url

    cloudinary.config(secure=True)

    torneo_nombre = limpiar_ruta_cloudinary(getattr(torneo, "nombre", "SIN_TORNEO"))
    archivo.seek(0)
    resultado = cloudinary.uploader.upload(
        archivo,
        resource_type="image",
        folder=f"torneos/{torneo_nombre}",
        public_id=campo,
        overwrite=True,
        invalidate=True,
    )
    return resultado.get("public_id") or ""


def aplicar_imagenes_torneo_cloudinary(torneo, archivos):
    for campo in ("logo_portada", "logo_izquierdo", "imagen_central", "logo_derecho"):
        public_id = subir_imagen_torneo_cloudinary(archivos.get(campo), torneo, campo)
        if public_id:
            setattr(torneo, campo, public_id)


def documentos_publicos_por_tipo(torneo=None):
    documentos = Documento.objects.filter(activo=True).order_by("tipo", "-creado_en", "titulo")
    if torneo:
        documentos = documentos.filter(Q(torneo=torneo) | Q(torneo__isnull=True))
    documentos_por_tipo = {
        "reglamentos": documentos.filter(tipo="REGLAMENTO"),
        "resoluciones": documentos.filter(tipo="RESOLUCION"),
        "demandas": documentos.filter(tipo="DEMANDA"),
        "comunicados": documentos.filter(tipo="COMUNICADO"),
    }

    documentos_cloudinary = listar_documentos_cloudinary_por_tipo()
    for tipo, lista_cloudinary in documentos_cloudinary.items():
        if not documentos_por_tipo[tipo].exists() and lista_cloudinary:
            documentos_por_tipo[tipo] = lista_cloudinary

    return documentos_por_tipo


def listar_documentos_cloudinary_por_tipo(max_results=500):
    documentos = {
        "reglamentos": [],
        "resoluciones": [],
        "demandas": [],
        "comunicados": [],
    }

    if not getattr(settings, "USE_CLOUDINARY_STORAGE", False):
        return documentos

    try:
        configurar = getattr(default_storage, "_configure", None)
        if configurar:
            configurar()

        import cloudinary.api

        recursos = []
        for resource_type in ("raw", "image"):
            respuesta = cloudinary.api.resources(
                resource_type=resource_type,
                type="upload",
                prefix="documentos/",
                max_results=max_results,
            )
            recursos.extend(respuesta.get("resources", []))
    except Exception as exc:
        print(f"No se pudieron recuperar documentos de Cloudinary: {exc}")
        return documentos

    tipos = {
        "REGLAMENTO": "reglamentos",
        "RESOLUCION": "resoluciones",
        "DEMANDA": "demandas",
        "COMUNICADO": "comunicados",
    }

    vistos = set()
    for recurso in recursos:
        public_id = recurso.get("public_id", "")
        url = recurso.get("secure_url") or recurso.get("url")
        if not public_id or not url or public_id in vistos:
            continue

        partes = public_id.split("/")
        if len(partes) < 3:
            continue

        tipo = partes[1].upper()
        llave = tipos.get(tipo)
        if not llave:
            continue

        vistos.add(public_id)
        titulo = partes[-1].rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip().upper()
        documentos[llave].append(SimpleNamespace(
            id=None,
            titulo=titulo or tipo,
            descripcion="",
            archivo=url,
            tipo=tipo,
        ))

    for llave in documentos:
        documentos[llave].sort(key=lambda item: item.titulo)

    return documentos


def documento_publico(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id, activo=True)
    archivo_url = request.build_absolute_uri(reverse("documento_archivo_publico", args=[documento.id]))
    visor_url = f"https://docs.google.com/gview?embedded=1&url={quote(archivo_url, safe='')}"
    return redirect(visor_url)


def documento_archivo_publico(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id, activo=True)
    respuesta = requests.get(documento.archivo, timeout=20)
    respuesta.raise_for_status()
    content_type = respuesta.headers.get("Content-Type") or "application/pdf"
    response = HttpResponse(respuesta.content, content_type=content_type)
    nombre = limpiar_ruta_cloudinary(documento.titulo) or f"documento-{documento.id}"
    response["Content-Disposition"] = f'inline; filename="{nombre}.pdf"'
    return response


def subir_documento_supabase(archivo, tipo):
    import boto3
    from urllib.parse import quote

    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "torneos-media").strip()
    endpoint_url = os.getenv("SUPABASE_S3_ENDPOINT_URL", "").strip()
    access_key = os.getenv("SUPABASE_S3_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY", "").strip()
    region_name = os.getenv("SUPABASE_S3_REGION_NAME", "us-east-1").strip()
    public_base = os.getenv("SUPABASE_PUBLIC_MEDIA_URL", "").strip().rstrip("/")

    if not all([bucket, endpoint_url, access_key, secret_key, public_base]):
        return ""

    nombre_archivo = limpiar_ruta_cloudinary(os.path.splitext(archivo.name)[0])
    extension = os.path.splitext(archivo.name)[1].lower() or ".pdf"
    llave = f"documentos/{limpiar_ruta_cloudinary(tipo)}/{uuid.uuid4().hex}_{nombre_archivo}{extension}"

    cliente = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region_name,
    )

    archivo.seek(0)
    cliente.upload_fileobj(
        archivo,
        bucket,
        llave,
        ExtraArgs={
            "ContentType": getattr(archivo, "content_type", "application/octet-stream"),
        },
    )
    return f"{public_base}/{quote(llave, safe='/')}"


def subir_documento_cloudinary(archivo, tipo):
    import cloudinary
    import cloudinary.uploader

    cloudinary_url = getattr(settings, "CLOUDINARY_URL", "").strip()
    if cloudinary_url:
        os.environ["CLOUDINARY_URL"] = cloudinary_url

    cloudinary.config(secure=True)

    archivo.seek(0)
    resultado = cloudinary.uploader.upload(
        archivo,
        resource_type="raw",
        folder=f"documentos/{limpiar_ruta_cloudinary(tipo)}",
    )
    return resultado.get("secure_url") or resultado["url"]


def subir_documento_torneo(archivo, tipo):
    url_supabase = subir_documento_supabase(archivo, tipo)
    if url_supabase:
        return url_supabase

    return subir_documento_cloudinary(archivo, tipo)


def limpiar_nombre(nombre):
    nombre = str(nombre).strip()
    nombre = re.sub(r'[\\/*?:"<>|]', '', nombre)
    return nombre.replace(' ', '_').upper()


def limpiar_texto_excel(valor):
    return "" if valor is None else str(valor).strip()


def limpiar_cedula_excel(valor):
    if valor is None:
        return ""

    valor = str(valor).strip()

    if valor.endswith(".0"):
        valor = valor[:-2]

    return valor.replace(".", "").replace(",", "").replace(" ", "")


def limpiar_entero_excel(valor):
    if valor in [None, ""]:
        return None

    try:
        return int(float(valor))
    except Exception:
        return None


def normalizar_anio_excel(anio):
    anio = limpiar_entero_excel(anio)

    if anio is None:
        return None

    if anio < 100:
        return 2000 + anio if anio <= 30 else 1900 + anio

    return anio


def construir_fecha_excel(dia, mes, anio):
    dia = limpiar_entero_excel(dia)
    mes = limpiar_entero_excel(mes)
    anio = normalizar_anio_excel(anio)

    if not dia or not mes or not anio:
        return None

    try:
        return date(anio, mes, dia)
    except Exception:
        return None


def obtener_hoja_planilla_excel(workbook):
    nombres = [
        "Planilla inscripcion",
        "Planilla inscripción",
        "PLANILLA INSCRIPCION",
        "PLANILLA INSCRIPCIÓN",
        "Inscripcion",
        "Inscripción",
    ]

    for nombre in nombres:
        if nombre in workbook.sheetnames:
            return workbook[nombre]

    return workbook.active


def normalizar_encabezado_excel(valor):
    valor = limpiar_nombre(limpiar_texto_excel(valor)).lower()
    return valor.replace("_", "")


def valor_por_encabezado(row, indices, *nombres):
    for nombre in nombres:
        indice = indices.get(normalizar_encabezado_excel(nombre))

        if indice is not None:
            return row[indice].value

    return None


def construir_fecha_partido_excel(valor):
    if not valor:
        return None

    if isinstance(valor, datetime):
        return valor.date()

    if isinstance(valor, date):
        return valor

    texto = limpiar_texto_excel(valor)

    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass

    return None


def construir_hora_partido_excel(valor):
    if not valor:
        return None

    if isinstance(valor, datetime):
        return valor.time().replace(second=0, microsecond=0)

    if isinstance(valor, time):
        return valor.replace(second=0, microsecond=0)

    texto = limpiar_texto_excel(valor).upper().replace(".", "")

    for formato in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(texto, formato).time().replace(second=0, microsecond=0)
        except ValueError:
            pass

    return None


def escudo_estatico_url(nombre_archivo):
    if not nombre_archivo:
        return ""

    ruta = f"torneos/escudos/{nombre_archivo}"

    if finders.find(ruta):
        return static(ruta)

    return ""


def escudo_default_url():
    return static("torneos/img/logo_imcred.png")


def escudo_url(equipo):
    if not equipo:
        return escudo_default_url()

    if equipo.escudo:
        try:
            if equipo.escudo.url:
                return equipo.escudo.url
        except Exception:
            pass

        try:
            if equipo.escudo.storage.exists(equipo.escudo.name):
                return equipo.escudo.url
        except Exception:
            pass

        nombre_archivo = os.path.basename(equipo.escudo.name).replace(" ", "_")
        escudo = escudo_estatico_url(nombre_archivo)

        if escudo:
            return escudo

    nombre_equipo = limpiar_nombre(equipo.nombre)

    for extension in ("png", "jpg", "jpeg", "webp"):
        escudo = escudo_estatico_url(f"{nombre_equipo}.{extension}")

        if escudo:
            return escudo

    return escudo_default_url()

def url_absoluta(request, url):
    if not url:
        return ""

    url = str(url)

    if url.startswith("http://") or url.startswith("https://"):
        return url

    return request.build_absolute_uri(url)


def rutas_logos(request):
    return {
        "logo_alcaldia": request.build_absolute_uri(static("torneos/img/logo_alcaldia.png")),
        "logo_app": request.build_absolute_uri(static("torneos/img/logo_app.png")),
        "logo_torneo": request.build_absolute_uri(static("torneos/img/logo_torneo.png")),
        "logo_imcred": request.build_absolute_uri(static("torneos/img/logo_imcred.png")),
    }


def url_campo_imagen(campo):
    if not campo:
        return ""
    try:
        return campo.url
    except Exception:
        return ""


def logos_torneo(request, torneo=None):
    logos = rutas_logos(request)
    if not torneo:
        return logos
    return {
        "logo_alcaldia": url_campo_imagen(torneo.logo_izquierdo),
        "logo_torneo": url_campo_imagen(torneo.imagen_central),
        "logo_imcred": url_campo_imagen(torneo.logo_derecho),
    }


def estructura_base_categoria():
    return {
        "grupos": {},
        "partidos_por_fecha": {},
        "columnas_planilla": [],
        "goleadores_planilla": [],
        "tarjetas_planilla": [],
        "valla_planilla": [],
        "alertas_tarjetas": [],
        "foraneos": [],
        "controlar_foraneos": False,
        "porcentaje_foraneos": 50,
        "equipos": [],
        "llaves": {
            "cuartos": [],
            "semifinal": [],
            "final": [],
            "tercer_puesto": [],
        },
    }


def nombre_columna_partido(partido):
    fase = partido.fase or "GRUPOS"

    if fase == "GRUPOS":
        return partido.numero_fecha or "SIN FECHA"

    return fase


def etiqueta_columna_planilla(columna):
    etiquetas = {
        "CUARTOS": "CTOS",
        "SEMIFINAL": "SF",
        "TERCER_PUESTO": "TP",
        "FINAL": "F",
    }
    return etiquetas.get(columna, columna)


ESTADOS_PARTIDO_CERRADO = ["FINALIZADO", "DECIDIDO_COMITE", "WO"]


def _marcar_estadisticas_pendientes(partido, user=None):
    if user is not None and es_editor_torneo(user):
        return
    partido.estadisticas_validadas = False
    partido.estadisticas_validadas_en = None
    partido.estadisticas_validadas_por = None
    partido.save(update_fields=[
        "estadisticas_validadas",
        "estadisticas_validadas_en",
        "estadisticas_validadas_por",
    ])


def _validar_estadisticas_partido(partido, user):
    partido.estadisticas_validadas = True
    partido.estadisticas_validadas_en = timezone.now()
    partido.estadisticas_validadas_por = user
    partido.save(update_fields=[
        "estadisticas_validadas",
        "estadisticas_validadas_en",
        "estadisticas_validadas_por",
    ])


def construir_estadisticas_foraneos(categoria):
    if not categoria or not categoria.controlar_foraneos:
        return []

    partidos_fase1 = Partido.objects.filter(
        categoria=categoria,
        fase="GRUPOS",
        estado__in=ESTADOS_PARTIDO_CERRADO,
        estadisticas_validadas=True,
    )
    total_partidos_por_equipo = defaultdict(int)
    partidos_por_equipo = defaultdict(set)
    for partido in partidos_fase1.only("id", "equipo_local_id", "equipo_visitante_id"):
        partidos_por_equipo[partido.equipo_local_id].add(partido.id)
        partidos_por_equipo[partido.equipo_visitante_id].add(partido.id)
    for equipo_id, partidos_ids in partidos_por_equipo.items():
        total_partidos_por_equipo[equipo_id] = len(partidos_ids)

    partidos_jugados_por_jugador = defaultdict(set)
    alineaciones = AlineacionPartido.objects.filter(
        partido__categoria=categoria,
        partido__fase="GRUPOS",
        partido__estado__in=ESTADOS_PARTIDO_CERRADO,
        partido__estadisticas_validadas=True,
        rol="TITULAR",
        jugador__es_foraneo=True,
    ).values_list("jugador_id", "partido_id")
    for jugador_id, partido_id in alineaciones:
        partidos_jugados_por_jugador[jugador_id].add(partido_id)

    sustituciones = SustitucionPartido.objects.filter(
        partido__categoria=categoria,
        partido__fase="GRUPOS",
        partido__estado__in=ESTADOS_PARTIDO_CERRADO,
        partido__estadisticas_validadas=True,
        jugador_entra__es_foraneo=True,
    ).values_list("jugador_entra_id", "partido_id")
    for jugador_id, partido_id in sustituciones:
        partidos_jugados_por_jugador[jugador_id].add(partido_id)

    porcentaje = categoria.porcentaje_minimo_foraneos or 0
    filas = []
    jugadores = Jugador.objects.filter(
        equipo__categoria=categoria,
        es_foraneo=True,
    ).select_related("equipo").only(
        "id",
        "nombres",
        "equipo_id",
        "equipo__id",
        "equipo__nombre",
        "equipo__escudo",
    ).order_by("equipo__nombre", "nombres")
    for jugador in jugadores:
        total_fase1 = total_partidos_por_equipo.get(jugador.equipo_id, 0)
        minimo = int((total_fase1 * porcentaje) / 100)
        jugados = len(partidos_jugados_por_jugador.get(jugador.id, set()))
        filas.append({
            "jugador": jugador.nombres,
            "equipo": jugador.equipo.nombre,
            "escudo": escudo_url(jugador.equipo),
            "partidos_fase1": total_fase1,
            "jugados": jugados,
            "minimo": minimo,
            "porcentaje": porcentaje,
            "cumple": jugados >= minimo,
            "estado": "Habilitado" if jugados >= minimo else "Pendiente",
        })

    return sorted(filas, key=lambda fila: (fila["cumple"], fila["equipo"], fila["jugador"]))


def construir_estructura(torneo=None):
    estructura = {}

    categorias = Categoria.objects.all().order_by("nombre")
    if torneo:
        categorias = categorias.filter(torneo=torneo)

    for categoria in categorias:
        estructura[categoria.nombre] = estructura_base_categoria()
        estructura[categoria.nombre]["controlar_foraneos"] = categoria.controlar_foraneos
        estructura[categoria.nombre]["porcentaje_foraneos"] = categoria.porcentaje_minimo_foraneos
        estructura[categoria.nombre]["foraneos"] = construir_estadisticas_foraneos(categoria)

    partidos = Partido.objects.select_related(
        "categoria",
        "equipo_local",
        "equipo_visitante"
    ).order_by(
        "categoria__nombre",
        "grupo",
        "numero_fecha",
        "fase",
        "fecha",
        "hora"
    )
    if torneo:
        partidos = partidos.filter(categoria__torneo=torneo)

    columnas_por_categoria = defaultdict(list)

    for partido in partidos:
        categoria = partido.categoria.nombre
        grupo = partido.grupo or "SIN GRUPO"
        fecha = partido.numero_fecha or "SIN FECHA"
        columna = nombre_columna_partido(partido)

        estructura.setdefault(categoria, estructura_base_categoria())

        if columna not in columnas_por_categoria[categoria]:
            columnas_por_categoria[categoria].append(columna)

        estructura[categoria]["grupos"].setdefault(grupo, {
            "fechas": {},
            "tabla": {}
        })

        datos_grupo = estructura[categoria]["grupos"][grupo]

        datos_grupo["fechas"].setdefault(fecha, [])
        datos_grupo["fechas"][fecha].append(partido)

        if partido.fase == "GRUPOS":
            estructura[categoria]["partidos_por_fecha"].setdefault(fecha, [])
            estructura[categoria]["partidos_por_fecha"][fecha].append({
                "grupo": grupo,
                "partido": partido,
                "escudo_local": escudo_url(partido.equipo_local),
                "escudo_visitante": escudo_url(partido.equipo_visitante),
            })

        for equipo in [partido.equipo_local, partido.equipo_visitante]:
            if equipo:
                datos_grupo["tabla"].setdefault(equipo.id, {
                    "id": equipo.id,
                    "equipo": equipo.nombre,
                    "escudo": escudo_url(equipo),
                    "pj": 0,
                    "pg": 0,
                    "pe": 0,
                    "pp": 0,
                    "gf": 0,
                    "gc": 0,
                    "dg": 0,
                    "pts": 0,
                })

        if partido.estado in ESTADOS_PARTIDO_CERRADO and partido.estadisticas_validadas:
            gl = partido.goles_local or 0
            gv = partido.goles_visitante or 0

            local = datos_grupo["tabla"][partido.equipo_local_id]
            visitante = datos_grupo["tabla"][partido.equipo_visitante_id]

            local["pj"] += 1
            visitante["pj"] += 1

            local["gf"] += gl
            local["gc"] += gv

            visitante["gf"] += gv
            visitante["gc"] += gl

            if gl > gv:
                local["pg"] += 1
                local["pts"] += 3
                visitante["pp"] += 1

            elif gl < gv:
                visitante["pg"] += 1
                visitante["pts"] += 3
                local["pp"] += 1

            else:
                local["pe"] += 1
                visitante["pe"] += 1
                local["pts"] += 1
                visitante["pts"] += 1

            local["pts"] += partido.ajuste_puntos_local or 0
            visitante["pts"] += partido.ajuste_puntos_visitante or 0

    for categoria, datos_categoria in estructura.items():
        for grupo, datos_grupo in datos_categoria["grupos"].items():
            for equipo in datos_grupo["tabla"].values():
                equipo["dg"] = equipo["gf"] - equipo["gc"]

            datos_grupo["tabla"] = sorted(
                datos_grupo["tabla"].values(),
                key=lambda x: (x["pts"], x["dg"], x["gf"]),
                reverse=True
            )

    goleadores_temp = defaultdict(lambda: defaultdict(lambda: {
        "jugador": "",
        "equipo": "",
        "escudo": "",
        "valores": defaultdict(int),
        "total": 0,
    }))

    goles_qs = Gol.objects.select_related(
        "partido__categoria",
        "jugador",
        "equipo",
        "partido"
    )
    if torneo:
        goles_qs = goles_qs.filter(partido__categoria__torneo=torneo)
    goles_qs = goles_qs.filter(partido__estadisticas_validadas=True)

    for gol in goles_qs:
        if gol.partido.estado not in ESTADOS_PARTIDO_CERRADO:
            continue

        categoria = gol.partido.categoria.nombre
        columna = nombre_columna_partido(gol.partido)
        jugador = gol.jugador.nombres
        cantidad = gol.cantidad or 1

        data = goleadores_temp[categoria][jugador]
        data["jugador"] = jugador
        data["equipo"] = gol.equipo.nombre
        data["escudo"] = escudo_url(gol.equipo)
        data["valores"][columna] += cantidad
        data["total"] += cantidad

        if columna not in columnas_por_categoria[categoria]:
            columnas_por_categoria[categoria].append(columna)

    tarjetas_temp = defaultdict(lambda: defaultdict(lambda: {
        "jugador": "",
        "equipo": "",
        "escudo": "",
        "valores": defaultdict(str),
        "total_a": 0,
        "total_r": 0,
        "total": 0,
    }))

    tarjetas_qs = Tarjeta.objects.select_related(
        "partido__categoria",
        "jugador",
        "equipo",
        "partido"
    )
    if torneo:
        tarjetas_qs = tarjetas_qs.filter(partido__categoria__torneo=torneo)
    tarjetas_qs = tarjetas_qs.filter(partido__estadisticas_validadas=True)

    for tarjeta in tarjetas_qs:
        if tarjeta.partido.estado not in ESTADOS_PARTIDO_CERRADO:
            continue

        categoria = tarjeta.partido.categoria.nombre
        columna = nombre_columna_partido(tarjeta.partido)
        jugador = tarjeta.jugador.nombres

        data = tarjetas_temp[categoria][jugador]
        data["jugador"] = jugador
        data["equipo"] = tarjeta.equipo.nombre
        data["escudo"] = escudo_url(tarjeta.equipo)

        actual = data["valores"][columna]

        if tarjeta.tipo == "AMARILLA":
            data["total_a"] += 1
            data["valores"][columna] = (actual + " A").strip()

        elif tarjeta.tipo == "ROJA":
            data["total_r"] += 1
            data["valores"][columna] = (actual + " R").strip()

        data["total"] += 1

        if columna not in columnas_por_categoria[categoria]:
            columnas_por_categoria[categoria].append(columna)

    valla_temp = defaultdict(lambda: defaultdict(lambda: {
        "equipo": "",
        "escudo": "",
        "valores": defaultdict(str),
        "pj": 0,
        "gc": 0,
        "promedio": 0,
    }))

    for partido in partidos:
        if partido.estado not in ESTADOS_PARTIDO_CERRADO or not partido.estadisticas_validadas:
            continue

        categoria = partido.categoria.nombre
        columna = nombre_columna_partido(partido)

        gl = partido.goles_local or 0
        gv = partido.goles_visitante or 0

        local = partido.equipo_local.nombre
        visitante = partido.equipo_visitante.nombre

        data_local = valla_temp[categoria][local]
        data_local["equipo"] = local
        data_local["escudo"] = escudo_url(partido.equipo_local)
        data_local["valores"][columna] = str(gv)
        data_local["pj"] += 1
        data_local["gc"] += gv

        data_visitante = valla_temp[categoria][visitante]
        data_visitante["equipo"] = visitante
        data_visitante["escudo"] = escudo_url(partido.equipo_visitante)
        data_visitante["valores"][columna] = str(gl)
        data_visitante["pj"] += 1
        data_visitante["gc"] += gl

    alertas_temp = defaultdict(lambda: defaultdict(lambda: {
        "jugador": "",
        "equipo": "",
        "escudo": "",
        "amarillas_grupos": 0,
        "amarillas_finales": 0,
        "rojas_total": 0,
    }))

    alertas_tarjetas_qs = Tarjeta.objects.select_related(
        "partido__categoria",
        "jugador",
        "equipo",
        "partido"
    )
    if torneo:
        alertas_tarjetas_qs = alertas_tarjetas_qs.filter(partido__categoria__torneo=torneo)
    alertas_tarjetas_qs = alertas_tarjetas_qs.filter(partido__estadisticas_validadas=True)

    for tarjeta in alertas_tarjetas_qs:
        if tarjeta.partido.estado not in ESTADOS_PARTIDO_CERRADO:
            continue

        categoria = tarjeta.partido.categoria.nombre
        jugador_id = tarjeta.jugador.id
        fase = tarjeta.partido.fase or "GRUPOS"

        data = alertas_temp[categoria][jugador_id]
        data["jugador"] = tarjeta.jugador.nombres
        data["equipo"] = tarjeta.equipo.nombre
        data["escudo"] = escudo_url(tarjeta.equipo)

        if tarjeta.tipo == "AMARILLA":
            if fase == "GRUPOS":
                data["amarillas_grupos"] += 1
            else:
                data["amarillas_finales"] += 1

        elif tarjeta.tipo == "ROJA":
            data["rojas_total"] += 1

    for categoria, datos_categoria in estructura.items():
        columnas_ordenadas = []

        for col in columnas_por_categoria[categoria]:
            if col not in columnas_ordenadas:
                columnas_ordenadas.append(col)

        columnas_ordenadas = []

        for col in columnas_por_categoria[categoria]:
           if col not in columnas_ordenadas:
                columnas_ordenadas.append(col)

        fases_finales = ["CUARTOS", "SEMIFINAL", "TERCER_PUESTO", "FINAL"]

        columnas_ordenadas = [
            col for col in columnas_ordenadas
            if col not in fases_finales
        ]

        for fase_fija in fases_finales:
            columnas_ordenadas.append(fase_fija)

        datos_categoria["columnas_planilla"] = columnas_ordenadas
        datos_categoria["columnas_planilla_display"] = [
            {
                "valor": col,
                "etiqueta": etiqueta_columna_planilla(col),
            }
            for col in columnas_ordenadas
        ]

        goleadores = []

        for jugador in goleadores_temp[categoria].values():
            fila = {
                "jugador": jugador["jugador"],
                "equipo": jugador["equipo"],
                "escudo": jugador["escudo"],
                "celdas": [],
                "total": jugador["total"],
            }

            for col in columnas_ordenadas:
                fila["celdas"].append(jugador["valores"].get(col, ""))

            goleadores.append(fila)

        datos_categoria["goleadores_planilla"] = sorted(
            goleadores,
            key=lambda x: x["total"],
            reverse=True
        )

        tarjetas = []

        for jugador in tarjetas_temp[categoria].values():
            fila = {
                "jugador": jugador["jugador"],
                "equipo": jugador["equipo"],
                "escudo": jugador["escudo"],
                "celdas": [],
                "total_a": jugador["total_a"],
                "total_r": jugador["total_r"],
                "total": jugador["total"],
            }

            for col in columnas_ordenadas:
                fila["celdas"].append(jugador["valores"].get(col, ""))

            tarjetas.append(fila)

        datos_categoria["tarjetas_planilla"] = sorted(
            tarjetas,
            key=lambda x: x["total"],
            reverse=True
        )

        vallas = []

        for equipo in valla_temp[categoria].values():
            promedio = round(equipo["gc"] / equipo["pj"], 2) if equipo["pj"] > 0 else 0

            fila = {
                "equipo": equipo["equipo"],
                "escudo": equipo["escudo"],
                "celdas": [],
                "pj": equipo["pj"],
                "gc": equipo["gc"],
                "promedio": promedio,
            }

            for col in columnas_ordenadas:
                fila["celdas"].append(equipo["valores"].get(col, ""))

            vallas.append(fila)

        datos_categoria["valla_planilla"] = sorted(
            vallas,
            key=lambda x: (x["promedio"], x["gc"])
        )

        alertas = []

        for data in alertas_temp[categoria].values():
            observaciones = []

            if data["amarillas_grupos"] >= 3:
                observaciones.append("SUSPENSIÓN 1 FECHA POR 3 AMARILLAS EN GRUPOS")
            elif data["amarillas_grupos"] == 2:
                observaciones.append("ALERTA: A 1 AMARILLA DE SUSPENSIÓN EN GRUPOS")

            if data["amarillas_finales"] >= 3:
                observaciones.append("SUSPENSIÓN 1 FECHA POR 3 AMARILLAS EN FASE FINAL")
            elif data["amarillas_finales"] == 2:
                observaciones.append("ALERTA: A 1 AMARILLA DE SUSPENSIÓN EN FASE FINAL")

            if data["rojas_total"] >= 3:
                observaciones.append("SANCIÓN: RESTO DEL TORNEO POR 3 ROJAS")
            elif data["rojas_total"] == 2:
                observaciones.append("ALERTA: A 1 ROJA DE SANCIÓN POR RESTO DEL TORNEO")

            if observaciones:
                alertas.append({
                    "jugador": data["jugador"],
                    "equipo": data["equipo"],
                    "escudo": data["escudo"],
                    "amarillas_grupos": data["amarillas_grupos"],
                    "amarillas_finales": data["amarillas_finales"],
                    "rojas_total": data["rojas_total"],
                    "observacion": " / ".join(observaciones),
                })

        datos_categoria["alertas_tarjetas"] = sorted(
            alertas,
            key=lambda x: (
                x["rojas_total"],
                x["amarillas_grupos"],
                x["amarillas_finales"]
            ),
            reverse=True
        )

        # ==================================================
    # LLAVES DE FASE FINAL
    # ==================================================

    for categoria_nombre, datos_categoria in estructura.items():
        partidos_finales = Partido.objects.filter(
            categoria__nombre=categoria_nombre,
            fase__in=["CUARTOS", "SEMIFINAL", "FINAL", "TERCER_PUESTO"]
        ).select_related(
            "equipo_local",
            "equipo_visitante"
        ).order_by(
            "fase",
            "numero_fecha",
            "id"
        )
        if torneo:
            partidos_finales = partidos_finales.filter(categoria__torneo=torneo)

        llaves = {
            "cuartos": [],
            "semifinal": [],
            "final": [],
            "tercer_puesto": [],
        }

        for p in partidos_finales:
            gl = p.goles_local if p.goles_local is not None else 0
            gv = p.goles_visitante if p.goles_visitante is not None else 0
            pl = p.goles_local_penales if p.goles_local_penales is not None else 0
            pv = p.goles_visitante_penales if p.goles_visitante_penales is not None else 0

            ganador_local = False
            ganador_visitante = False

            if p.estado in ESTADOS_PARTIDO_CERRADO:
                if gl > gv:
                    ganador_local = True
                elif gv > gl:
                    ganador_visitante = True
                else:
                    if pl > pv:
                        ganador_local = True
                    elif pv > pl:
                        ganador_visitante = True

            item = {
                "id": p.id,
                "local": p.equipo_local.nombre if p.equipo_local else "Por definir",
                "visitante": p.equipo_visitante.nombre if p.equipo_visitante else "Por definir",
                "escudo_local": escudo_url(p.equipo_local),
                "escudo_visitante": escudo_url(p.equipo_visitante),
                "gl": gl,
                "gv": gv,
                "pl": pl,
                "pv": pv,
                "tiene_penales": gl == gv and (pl > 0 or pv > 0),
                "ganador_local": ganador_local,
                "ganador_visitante": ganador_visitante,
                "estado": p.estado,
                "estado_display": p.get_estado_display(),
                "numero_fecha": p.numero_fecha,
                "numero_llave": int(re.search(r"\d+", p.numero_fecha or "0").group()) if re.search(r"\d+", p.numero_fecha or "") else 0,
                "fecha": p.fecha,
                "hora": p.hora,
                "cancha": p.cancha,
                "inicio_en_vivo": p.inicio_en_vivo,
                "cronometro_pausado": p.cronometro_pausado,
                "periodo_en_vivo": p.periodo_en_vivo,
                "segundos_vivos": segundos_vivos_partido(p),
            }

            if p.fase == "CUARTOS":
                llaves["cuartos"].append(item)
            elif p.fase == "SEMIFINAL":
                llaves["semifinal"].append(item)
            elif p.fase == "FINAL":
                llaves["final"].append(item)
            elif p.fase == "TERCER_PUESTO":
                llaves["tercer_puesto"].append(item)

        orden_cuartos = {1: 1, 4: 2, 2: 3, 3: 4}
        llaves["cuartos"] = sorted(
            llaves["cuartos"],
            key=lambda item: (orden_cuartos.get(item["numero_llave"], item["numero_llave"] or 99), item["id"] or 0)
        )
        llaves["semifinal"] = sorted(
            llaves["semifinal"],
            key=lambda item: (item["numero_llave"] or 99, item["id"] or 0)
        )

        datos_categoria["llaves"] = llaves

    # ==================================================
    # EQUIPOS Y JUGADORES POR CATEGORÍA
    # ==================================================

    for categoria_nombre, datos_categoria in estructura.items():
        equipos_categoria = Equipo.objects.filter(
            categoria__nombre=categoria_nombre,
            activo=True
        ).prefetch_related("jugadores").order_by("nombre")
        if torneo:
            equipos_categoria = equipos_categoria.filter(categoria__torneo=torneo)

        lista_equipos = []

        for equipo_obj in equipos_categoria:
            jugadores = []

            for jugador in equipo_obj.jugadores.all().order_by("dorsal", "nombres"):
                edad = ""

                if jugador.fecha_nacimiento:
                    hoy = date.today()
                    edad = hoy.year - jugador.fecha_nacimiento.year - (
                        (hoy.month, hoy.day) < (
                            jugador.fecha_nacimiento.month,
                            jugador.fecha_nacimiento.day
                        )
                    )

                jugadores.append({
                    "dorsal": jugador.dorsal,
                    "nombres": jugador.nombres,
                    "cedula": jugador.cedula,
                    "estado": jugador.estado,
                    "foto": jugador.foto.url if jugador.foto else "",
                    "edad": edad,
                })

            lista_equipos.append({
                "id": equipo_obj.id,
                "nombre": equipo_obj.nombre,
                "escudo": escudo_url(equipo_obj),
                "jugadores": jugadores,
                "director_tecnico": equipo_obj.director_tecnico,
                "asistente_tecnico": equipo_obj.asistente_tecnico,
                "delegado": equipo_obj.delegado,
            })

        datos_categoria["equipos"] = lista_equipos
    return estructura


def preparar_categoria_para_descarga(request, datos_categoria):
    if not datos_categoria:
        return datos_categoria

    for grupo, datos_grupo in datos_categoria["grupos"].items():
        for equipo in datos_grupo["tabla"]:
            equipo["escudo"] = url_absoluta(request, equipo.get("escudo"))

    for g in datos_categoria["goleadores_planilla"]:
        g["escudo"] = url_absoluta(request, g.get("escudo"))

    for t in datos_categoria["tarjetas_planilla"]:
        t["escudo"] = url_absoluta(request, t.get("escudo"))

    for v in datos_categoria["valla_planilla"]:
        v["escudo"] = url_absoluta(request, v.get("escudo"))

    return datos_categoria


def segundos_vivos_partido(partido):
    segundos = partido.segundos_acumulados or 0
    if (
        partido.estado == "EN_JUEGO"
        and partido.inicio_en_vivo
        and not partido.cronometro_pausado
    ):
        diferencia = timezone.now() - partido.inicio_en_vivo
        segundos += max(0, int(diferencia.total_seconds()))
    return segundos


def foto_jugador_url(jugador):
    if jugador and jugador.foto:
        try:
            return jugador.foto.url
        except Exception:
            return ""
    return ""


def iniciales_jugador(jugador):
    nombre = (getattr(jugador, "nombres", "") or "").strip()
    partes = [parte[0] for parte in nombre.split()[:2] if parte]
    return "".join(partes).upper() or "J"


def _nombre_primer_apellido(jugador):
    nombre = (getattr(jugador, "nombres", "") or "").strip()
    partes = [parte for parte in nombre.split() if parte]
    conectores_apellido = {"de", "del", "la", "las", "los", "da", "das", "do", "dos", "van", "von", "y"}
    if len(partes) >= 4:
        apellido = [partes[2]]
        idx = 3
        while apellido[-1].lower() in conectores_apellido and idx < len(partes):
            apellido.append(partes[idx])
            idx += 1
        return f"{partes[0]} {' '.join(apellido)}"
    if len(partes) >= 3:
        apellido = [partes[1]]
        idx = 2
        while apellido[-1].lower() in conectores_apellido and idx < len(partes):
            apellido.append(partes[idx])
            idx += 1
        return f"{partes[0]} {' '.join(apellido)}"
    if len(partes) >= 2:
        return f"{partes[0]} {partes[1]}"
    return nombre or "Jugador"


def nombre_corto_jugador(jugador):
    return _nombre_primer_apellido(jugador)


def nombre_resumen_jugador(jugador):
    return _nombre_primer_apellido(jugador)


def edad_jugador_en_fecha(jugador, fecha_referencia=None):
    if not jugador or not jugador.fecha_nacimiento:
        return None
    fecha = fecha_referencia or date.today()
    return fecha.year - jugador.fecha_nacimiento.year - (
        (fecha.month, fecha.day) < (jugador.fecha_nacimiento.month, jugador.fecha_nacimiento.day)
    )


def reglas_edad_categoria(categoria):
    if not categoria:
        return []
    reglas_cache = getattr(categoria, "_reglas_edad_cache", None)
    if reglas_cache is None:
        reglas_cache = list(
            categoria.reglas_edad.filter(activa=True).order_by("orden", "edad_minima", "id")
        )
        categoria._reglas_edad_cache = reglas_cache
    return reglas_cache


def regla_edad_jugador(jugador, categoria=None, fecha_referencia=None):
    categoria = categoria or getattr(getattr(jugador, "equipo", None), "categoria", None)
    edad = edad_jugador_en_fecha(jugador, fecha_referencia)
    for regla in reglas_edad_categoria(categoria):
        if regla.coincide_con_edad(edad):
            return regla
    return None


def etiqueta_edad_jugador(jugador, categoria=None, fecha_referencia=None):
    regla = regla_edad_jugador(jugador, categoria, fecha_referencia)
    return regla.etiqueta if regla else ""


def texto_edad_jugador(jugador, categoria=None, fecha_referencia=None):
    etiqueta = etiqueta_edad_jugador(jugador, categoria, fecha_referencia)
    if etiqueta:
        return etiqueta
    edad = edad_jugador_en_fecha(jugador, fecha_referencia)
    if edad is None:
        return ""
    return f"{edad} años"


def validar_reglas_edad_titulares(partido, equipo, titulares_ids):
    reglas = [regla for regla in reglas_edad_categoria(partido.categoria) if regla.minimo_titulares]
    if not reglas or len(titulares_ids) < 11:
        return []

    jugadores = Jugador.objects.filter(id__in=titulares_ids, equipo=equipo)
    conteos = {regla.id: 0 for regla in reglas}
    for jugador in jugadores:
        regla = regla_edad_jugador(jugador, partido.categoria, partido.fecha)
        if regla and regla.id in conteos:
            conteos[regla.id] += 1

    errores = []
    for regla in reglas:
        cantidad = conteos.get(regla.id, 0)
        if cantidad < regla.minimo_titulares:
            errores.append(
                f"{regla.etiqueta}: minimo {regla.minimo_titulares} en cancha, tienes {cantidad}."
            )
    return errores


def construir_partidos_portada(torneo=None):
    partidos = Partido.objects.filter(
        fecha__isnull=False,
    ).select_related(
        "categoria",
        "equipo_local",
        "equipo_visitante",
    )
    if torneo:
        partidos = partidos.filter(categoria__torneo=torneo)

    estados_visibles = [
        "PROGRAMADO",
        "EN_JUEGO",
        "FINALIZADO",
        "DECIDIDO_COMITE",
        "WO",
        "APLAZADO",
        "SUSPENDIDO",
    ]
    tarjetas_por_partido = defaultdict(int)
    goles_por_partido = defaultdict(int)

    tarjetas_eventos = Tarjeta.objects.all()
    goles_eventos = Gol.objects.all()
    if torneo:
        tarjetas_eventos = tarjetas_eventos.filter(partido__categoria__torneo=torneo)
        goles_eventos = goles_eventos.filter(partido__categoria__torneo=torneo)

    for item in tarjetas_eventos.values("partido_id"):
        tarjetas_por_partido[item["partido_id"]] += 1

    for item in goles_eventos.values("partido_id"):
        goles_por_partido[item["partido_id"]] += 1

    partidos_portada = []

    for partido in partidos:
        if partido.estado not in estados_visibles:
            continue

        cancha_normalizada = (partido.cancha or "").strip().lower()
        programacion_completa = (
            bool(cancha_normalizada)
            and cancha_normalizada != "por definir"
            and partido.hora
            and partido.hora != time(0, 0)
        )

        if partido.estado in ESTADOS_PARTIDO_CERRADO:
            bloque = "RESULTADOS RECIENTES"
            orden_bloque = 0
            orden_fecha = partido.fecha.toordinal()
        elif partido.estado == "EN_JUEGO" or programacion_completa:
            bloque = "PROGRAMADOS"
            orden_bloque = 1
            orden_fecha = partido.fecha.toordinal()
        else:
            bloque = "FUTUROS"
            orden_bloque = 2
            orden_fecha = partido.fecha.toordinal()

        fase = partido.fase or "GRUPOS"
        gl = partido.goles_local or 0
        gv = partido.goles_visitante or 0
        pl = partido.goles_local_penales or 0
        pv = partido.goles_visitante_penales or 0
        ganador_local = False
        ganador_visitante = False

        if fase != "GRUPOS" and partido.estado in ESTADOS_PARTIDO_CERRADO:
            if gl > gv:
                ganador_local = True
            elif gv > gl:
                ganador_visitante = True
            elif pl > pv:
                ganador_local = True
            elif pv > pl:
                ganador_visitante = True

        categoria_nombre = partido.categoria.nombre
        categoria_mayuscula = categoria_nombre.upper()
        if "PLUS" in categoria_mayuscula:
            categoria_clase = "cat-plus"
        elif "SENIOR" in categoria_mayuscula:
            categoria_clase = "cat-senior"
        elif "INTER" in categoria_mayuscula:
            categoria_clase = "cat-interbarrios"
        else:
            categoria_clase = "cat-general"

        partidos_portada.append({
            "id": partido.id,
            "bloque": bloque,
            "orden_bloque": orden_bloque,
            "orden_fecha": orden_fecha,
            "categoria": categoria_nombre,
            "categoria_clase": categoria_clase,
            "grupo": partido.grupo or "",
            "fase": fase,
            "numero_fecha": partido.numero_fecha or "",
            "estado": partido.estado,
            "estado_display": partido.get_estado_display(),
            "fecha": partido.fecha,
            "hora": partido.hora.strftime("%H:%M") if partido.hora else "Por definir",
            "hora_orden": partido.hora or time(0, 0),
            "cancha": partido.cancha or "Por definir",
            "local": partido.equipo_local.nombre,
            "visitante": partido.equipo_visitante.nombre,
            "escudo_local": escudo_url(partido.equipo_local),
            "escudo_visitante": escudo_url(partido.equipo_visitante),
            "goles_local": gl,
            "goles_visitante": gv,
            "goles_local_penales": pl,
            "goles_visitante_penales": pv,
            "tiene_penales": pl > 0 or pv > 0,
            "ganador_local": ganador_local,
            "ganador_visitante": ganador_visitante,
            "eventos": goles_por_partido[partido.id] + tarjetas_por_partido[partido.id],
            "inicio_en_vivo": partido.inicio_en_vivo,
            "cronometro_pausado": partido.cronometro_pausado,
            "segundos_acumulados": partido.segundos_acumulados,
            "segundos_vivos": segundos_vivos_partido(partido),
            "periodo_en_vivo": partido.periodo_en_vivo,
        })

    return sorted(
        partidos_portada,
        key=lambda partido: (
            partido["orden_bloque"],
            partido["orden_fecha"],
            partido["hora_orden"],
            partido["categoria"],
        )
    )


def panel_principal(request):
    if request.GET.get("portal") == "1":
        request.session.pop("torneo_id", None)

    torneo = torneo_actual(request, auto_seleccionar=False)
    torneos_menu = torneos_para_usuario(request)
    if not torneo:
        organizador_id = request.GET.get("organizador")
        organizador_actual = None
        torneos_portal = torneos_menu
        if organizador_id and str(organizador_id).isdigit():
            torneos_portal = torneos_menu.filter(organizador_id=organizador_id)
            try:
                organizador = Organizador.objects.filter(id=organizador_id, activo=True).first()
            except Exception:
                organizador = None
            if organizador:
                organizador_actual = SimpleNamespace(
                    id=organizador.id,
                    nombre=organizador.nombre,
                )

        logos = rutas_logos(request)
        return render(request, "portal_torneos.html", {
            "torneos_menu": torneos_portal,
            "organizadores_portal": organizadores_para_portal(torneos_menu),
            "organizador_actual": organizador_actual,
            "logo_alcaldia": logos["logo_alcaldia"],
            "logo_app": logos["logo_app"],
            "logo_torneo": logos["logo_torneo"],
            "logo_imcred": logos["logo_imcred"],
        })

    if torneo.organizador_id:
        torneos_menu = torneos_menu.filter(organizador_id=torneo.organizador_id)
    else:
        torneos_menu = torneos_menu.filter(id=torneo.id)

    categoria_seleccionada = request.GET.get("categoria", "").strip()
    categorias = Categoria.objects.order_by("nombre")
    if torneo:
        categorias = categorias.filter(torneo=torneo)

    if categoria_seleccionada:
        estructura_total = construir_estructura(torneo)
        estructura = {
            nombre: datos
            for nombre, datos in estructura_total.items()
            if nombre == categoria_seleccionada
        }
    else:
        estructura = {
            categoria.nombre: estructura_base_categoria()
            for categoria in categorias
        }

    logos = logos_torneo(request, torneo)
    partidos_portada = construir_partidos_portada(torneo)
    documentos = documentos_publicos_por_tipo(torneo)
    fechas_grupos = sorted(
        {
            p["numero_fecha"]
            for p in partidos_portada
            if p["numero_fecha"]
        },
        key=lambda valor: (
            int(valor) if str(valor).isdigit() else 9999,
            str(valor),
        )
    )
    partidos_fechas = [
        {
            "key": f"fecha-{re.sub(r'[^a-zA-Z0-9_-]+', '-', str(fecha)).strip('-').lower()}",
            "label": f"Fecha {fecha}",
            "partidos": [p for p in partidos_portada if p["numero_fecha"] == fecha],
        }
        for fecha in fechas_grupos
    ]
    partidos_cuartos = [p for p in partidos_portada if p["fase"] == "CUARTOS"]
    partidos_semifinal = [p for p in partidos_portada if p["fase"] == "SEMIFINAL"]
    partidos_final = [p for p in partidos_portada if p["fase"] in ["FINAL", "TERCER_PUESTO"]]

    def orden_fecha_fixture(partido):
        numero_fecha = partido["numero_fecha"]
        return (
            int(numero_fecha) if str(numero_fecha).isdigit() else 9999,
            str(numero_fecha),
        )

    partidos_resultados = sorted(
        [p for p in partidos_portada if p["bloque"] == "RESULTADOS RECIENTES"],
        key=lambda p: (
            p["orden_fecha"],
            p["hora_orden"],
            p["categoria"],
            p["grupo"],
        ),
    )
    partidos_programados = sorted(
        [p for p in partidos_portada if p["bloque"] == "PROGRAMADOS"],
        key=lambda p: (
            orden_fecha_fixture(p),
            p["orden_fecha"],
            p["hora_orden"],
            p["categoria"],
            p["grupo"],
        ),
    )
    partidos_futuros = sorted(
        [p for p in partidos_portada if p["bloque"] == "FUTUROS"],
        key=lambda p: (
            orden_fecha_fixture(p),
            p["orden_fecha"],
            p["hora_orden"],
            p["categoria"],
            p["grupo"],
        ),
    )

    return render(request, "panel_principal.html", {
        "estructura": estructura,
        "torneos_menu": torneos_menu,
        "torneo_seleccionado": torneo,
        "organizador_portal_id": torneo.organizador_id,
        "categorias_menu": categorias,
        "categoria_seleccionada": categoria_seleccionada,
        "renderizar_categorias_detalle": bool(categoria_seleccionada),
        "partidos_portada": partidos_portada,
        "partidos_resultados": partidos_resultados,
        "partidos_programados": partidos_programados,
        "partidos_futuros": partidos_futuros,
        "partidos_fechas": partidos_fechas,
        "partidos_cuartos": partidos_cuartos,
        "partidos_semifinal": partidos_semifinal,
        "partidos_final": partidos_final,
        "reglamentos": documentos["reglamentos"],
        "resoluciones": documentos["resoluciones"],
        "demandas": documentos["demandas"],
        "comunicados": documentos["comunicados"],
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })


def detalle_partido_publico(request, partido_id):
    return redirect("partido_live", partido_id=partido_id)


def url_retorno_descarga(request):
    return (
        request.GET.get("volver")
        or request.META.get("HTTP_REFERER")
        or reverse("panel")
    )


def respuesta_descarga_sin_partidos(request, mensaje):
    volver_url = escape(url_retorno_descarga(request))
    mensaje = escape(mensaje)
    return HttpResponse(f"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sin programación</title>
<style>
body {{
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: #eef3f9;
    color: #061426;
    font-family: Arial, sans-serif;
    padding: 24px;
    box-sizing: border-box;
}}
.caja {{
    width: min(92vw, 520px);
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 18px;
    padding: 24px;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.12);
    text-align: center;
}}
p {{
    font-size: 20px;
    font-weight: 800;
    margin: 0 0 18px;
}}
a {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 0 22px;
    border-radius: 999px;
    background: #00e676;
    color: #061426;
    font-weight: 900;
    text-decoration: none;
}}
</style>
</head>
<body>
<div class="caja">
    <p>{mensaje}</p>
    <a href="{volver_url}">Volver al panel</a>
</div>
<script>
setTimeout(function() {{
    window.location.href = "{volver_url}";
}}, 3500);
</script>
</body>
</html>
""")


def crear_imagen_desde_html(html, nombre_archivo, ancho=1600, alto=1800, volver_url="/"):
    return render(None, "descargas/auto_descarga.html", {
        "contenido_html": html,
        "nombre_archivo": nombre_archivo,
        "ancho": ancho,
        "alto": alto,
        "volver_url": volver_url,
    })
    carpeta_media = os.path.join(os.getcwd(), "media", "descargas")
    os.makedirs(carpeta_media, exist_ok=True)

    ruta_archivo = os.path.join(carpeta_media, nombre_archivo)

    hti = Html2Image(output_path=carpeta_media)
    hti.browser.flags = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--allow-file-access-from-files",
    ]

    hti.screenshot(
        html_str=html,
        save_as=nombre_archivo,
        size=(ancho, alto)
    )

    return FileResponse(
        open(ruta_archivo, "rb"),
        as_attachment=True,
        filename=nombre_archivo,
        content_type="image/png"
    )


@login_required
@user_passes_test(es_editor_torneo)
def descargar_tabla_grupo(request, categoria, grupo):
    torneo = torneo_actual(request)
    estructura = construir_estructura(torneo)
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    datos_grupo = datos_categoria["grupos"].get(grupo)

    if not datos_grupo:
        return HttpResponse("Grupo no encontrado")

    logos = logos_torneo(request, torneo)

    html = render_to_string("descargas/tabla_grupo.html", {
        "categoria": categoria,
        "grupo": grupo,
        "datos_grupo": datos_grupo,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"TABLA_{categoria}_{grupo}.png")
    return crear_imagen_desde_html(html, nombre, 1600, 1200, url_retorno_descarga(request))


@login_required
@user_passes_test(es_editor_torneo)
def descargar_goleadores_categoria(request, categoria):
    torneo = torneo_actual(request)
    estructura = construir_estructura(torneo)
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    logos = logos_torneo(request, torneo)

    html = render_to_string("descargas/goleadores_categoria.html", {
        "categoria": categoria,
        "datos_categoria": datos_categoria,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"GOLEADORES_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1800, 2000, url_retorno_descarga(request))


@login_required
@user_passes_test(es_editor_torneo)
def descargar_tarjetas_categoria(request, categoria):
    torneo = torneo_actual(request)
    estructura = construir_estructura(torneo)
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    logos = logos_torneo(request, torneo)

    html = render_to_string("descargas/tarjetas_categoria.html", {
        "categoria": categoria,
        "datos_categoria": datos_categoria,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"TARJETAS_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1800, 2000, url_retorno_descarga(request))


@login_required
@user_passes_test(es_editor_torneo)
def descargar_valla_categoria(request, categoria):
    torneo = torneo_actual(request)
    estructura = construir_estructura(torneo)
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    logos = logos_torneo(request, torneo)

    html = render_to_string("descargas/valla_categoria.html", {
        "categoria": categoria,
        "datos_categoria": datos_categoria,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"VALLA_MENOS_VENCIDA_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1800, 1800, url_retorno_descarga(request))


@login_required
@user_passes_test(es_editor_torneo)
def descargar_foraneos_categoria(request, categoria):
    torneo = torneo_actual(request)
    estructura = construir_estructura(torneo)
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoria no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    logos = logos_torneo(request, torneo)

    html = render_to_string("descargas/foraneos_categoria.html", {
        "categoria": categoria,
        "datos_categoria": datos_categoria,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
        "tiene_equipos_delegado": equipos_delegado_asignados(request.user).exists(),
    })

    nombre = limpiar_nombre(f"FORANEOS_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1800, 2000, url_retorno_descarga(request))


@login_required
@user_passes_test(es_editor_torneo)
def descargar_imagen(request, categoria):
    torneo = torneo_actual(request)
    estructura_total = construir_estructura(torneo)

    if categoria not in estructura_total:
        return HttpResponse("Categoría no encontrada")

    estructura = {
        categoria: estructura_total[categoria]
    }

    logos = logos_torneo(request, torneo)

    html = render_to_string("panel_principal.html", {
        "estructura": estructura,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"PANEL_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1600, 2800, url_retorno_descarga(request))


def grupo_completo(categoria, grupo):
    partidos = Partido.objects.filter(
        categoria=categoria,
        grupo=grupo,
        fase="GRUPOS"
    )

    if not partidos.exists():
        return False

    for partido in partidos:
        if partido.estado not in ESTADOS_PARTIDO_CERRADO:
            return False

    return True


def obtener_tabla_categoria_grupo(categoria_nombre, grupo, torneo=None):
    estructura = construir_estructura(torneo)
    datos_categoria = estructura.get(categoria_nombre)

    if not datos_categoria:
        return []

    datos_grupo = datos_categoria["grupos"].get(grupo)

    if not datos_grupo:
        return []

    return datos_grupo["tabla"]


def crear_o_actualizar_cuarto(categoria, numero, local, visitante):
    partido, creado = Partido.objects.get_or_create(
        categoria=categoria,
        fase="CUARTOS",
        numero_fecha=f"CUARTOS #{numero}",
        defaults={
            "grupo": "FINAL",
            "equipo_local": local,
            "equipo_visitante": visitante,
            "goles_local": 0,
            "goles_visitante": 0,
            "estado": "PROGRAMADO",
            "fecha": date.today(),
            "hora": time(0, 0),
            "cancha": "Por definir",
        }
    )

    if partido.estado in ESTADOS_PARTIDO_CERRADO:
        return partido

    partido.grupo = "FINAL"
    partido.equipo_local = local
    partido.equipo_visitante = visitante
    partido.estado = "PROGRAMADO"

    if not partido.fecha:
        partido.fecha = date.today()

    if not partido.hora:
        partido.hora = time(0, 0)

    if not partido.cancha:
        partido.cancha = "Por definir"

    partido.save()

    return partido


@login_required
@user_passes_test(es_editor_torneo)
def generar_llaves_cuartos(request, categoria):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.filter(nombre=categoria)
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria_obj = categorias.first()

    if not categoria_obj:
        messages.error(request, "Categoría no encontrada.")
        return redirect("panel")

    # PLUS 50: un solo grupo
    if categoria.upper() == "PLUS 50":
        tabla_general = obtener_tabla_categoria_grupo(categoria, "A", torneo)

        if len(tabla_general) < 4:
            messages.error(request, "No hay suficientes equipos para generar las semifinales de PLUS 50.")
            return redirect("panel")

        primero = Equipo.objects.get(nombre=tabla_general[0]["equipo"], categoria=categoria_obj)
        segundo = Equipo.objects.get(nombre=tabla_general[1]["equipo"], categoria=categoria_obj)
        tercero = Equipo.objects.get(nombre=tabla_general[2]["equipo"], categoria=categoria_obj)
        cuarto = Equipo.objects.get(nombre=tabla_general[3]["equipo"], categoria=categoria_obj)

        crear_o_actualizar_cuarto(categoria_obj, 1, primero, cuarto)
        crear_o_actualizar_cuarto(categoria_obj, 2, segundo, tercero)

        messages.success(request, f"Llaves generadas correctamente para {categoria}.")
        return redirect("panel")

    # SENIOR MASTER u otras categorías con grupos A y B
    if not grupo_completo(categoria_obj, "A"):
        messages.error(request, f"El Grupo A de {categoria} todavía tiene partidos pendientes.")
        return redirect("panel")

    if not grupo_completo(categoria_obj, "B"):
        messages.error(request, f"El Grupo B de {categoria} todavía tiene partidos pendientes.")
        return redirect("panel")

    tabla_a = obtener_tabla_categoria_grupo(categoria, "A", torneo)
    tabla_b = obtener_tabla_categoria_grupo(categoria, "B", torneo)

    if len(tabla_a) < 4 or len(tabla_b) < 4:
        messages.error(request, "No hay suficientes equipos para generar los cuartos.")
        return redirect("panel")

    primero_a = Equipo.objects.get(nombre=tabla_a[0]["equipo"], categoria=categoria_obj)
    segundo_a = Equipo.objects.get(nombre=tabla_a[1]["equipo"], categoria=categoria_obj)
    tercero_a = Equipo.objects.get(nombre=tabla_a[2]["equipo"], categoria=categoria_obj)
    cuarto_a = Equipo.objects.get(nombre=tabla_a[3]["equipo"], categoria=categoria_obj)

    primero_b = Equipo.objects.get(nombre=tabla_b[0]["equipo"], categoria=categoria_obj)
    segundo_b = Equipo.objects.get(nombre=tabla_b[1]["equipo"], categoria=categoria_obj)
    tercero_b = Equipo.objects.get(nombre=tabla_b[2]["equipo"], categoria=categoria_obj)
    cuarto_b = Equipo.objects.get(nombre=tabla_b[3]["equipo"], categoria=categoria_obj)

    crear_o_actualizar_cuarto(categoria_obj, 1, primero_a, cuarto_b)
    crear_o_actualizar_cuarto(categoria_obj, 2, segundo_a, tercero_b)
    crear_o_actualizar_cuarto(categoria_obj, 3, primero_b, cuarto_a)
    crear_o_actualizar_cuarto(categoria_obj, 4, segundo_b, tercero_a)

    messages.success(request, f"Llaves de cuartos generadas correctamente para {categoria}.")
    return redirect("panel")

def ganador_partido(partido):
    if partido.estado not in ESTADOS_PARTIDO_CERRADO:
        return None

    gl = partido.goles_local or 0
    gv = partido.goles_visitante or 0

    if gl > gv:
        return partido.equipo_local

    if gv > gl:
        return partido.equipo_visitante

    # Si el partido quedó empatado, decide por penales
    pl = partido.goles_local_penales or 0
    pv = partido.goles_visitante_penales or 0

    if pl > pv:
        return partido.equipo_local

    if pv > pl:
        return partido.equipo_visitante

    return None


def crear_o_actualizar_partido_final(categoria, fase, numero_fecha, local, visitante):
    partido, creado = Partido.objects.get_or_create(
        categoria=categoria,
        fase=fase,
        numero_fecha=numero_fecha,
        defaults={
            "grupo": "FINAL",
            "equipo_local": local,
            "equipo_visitante": visitante,
            "goles_local": 0,
            "goles_visitante": 0,
            "estado": "PROGRAMADO",
            "fecha": date.today(),
            "hora": time(0, 0),
            "cancha": "Por definir",
        }
    )

    if partido.estado in ESTADOS_PARTIDO_CERRADO:
        return partido

    partido.grupo = "FINAL"
    partido.equipo_local = local
    partido.equipo_visitante = visitante
    partido.estado = "PROGRAMADO"

    if not partido.fecha:
        partido.fecha = date.today()

    if not partido.hora:
        partido.hora = time(0, 0)

    if not partido.cancha:
        partido.cancha = "Por definir"

    partido.save()
    return partido


@login_required
@user_passes_test(es_editor_torneo)
def generar_semifinales(request, categoria):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.filter(nombre=categoria)
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria_obj = categorias.first()

    if not categoria_obj:
        messages.error(request, "Categoría no encontrada.")
        return redirect("panel")

    q1 = Partido.objects.filter(categoria=categoria_obj, fase="CUARTOS", numero_fecha="CUARTOS #1").first()
    q2 = Partido.objects.filter(categoria=categoria_obj, fase="CUARTOS", numero_fecha="CUARTOS #2").first()
    q3 = Partido.objects.filter(categoria=categoria_obj, fase="CUARTOS", numero_fecha="CUARTOS #3").first()
    q4 = Partido.objects.filter(categoria=categoria_obj, fase="CUARTOS", numero_fecha="CUARTOS #4").first()

    if not all([q1, q2, q3, q4]):
        messages.error(request, "Primero debes generar los cuartos de final.")
        return redirect("panel")

    g1 = ganador_partido(q1)
    g2 = ganador_partido(q2)
    g3 = ganador_partido(q3)
    g4 = ganador_partido(q4)

    if not all([g1, g2, g3, g4]):
        messages.error(request, "Todos los cuartos deben estar finalizados para generar semifinales.")
        return redirect("panel")

    crear_o_actualizar_partido_final(categoria_obj, "SEMIFINAL", "SEMIFINAL #1", g1, g4)
    crear_o_actualizar_partido_final(categoria_obj, "SEMIFINAL", "SEMIFINAL #2", g2, g3)

    messages.success(request, f"Semifinales generadas correctamente para {categoria}.")
    return redirect("panel")


@login_required
@user_passes_test(es_editor_torneo)
def generar_final(request, categoria):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.filter(nombre=categoria)
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria_obj = categorias.first()

    if not categoria_obj:
        messages.error(request, "Categoría no encontrada.")
        return redirect("panel")

    sf1 = Partido.objects.filter(categoria=categoria_obj, fase="SEMIFINAL", numero_fecha="SEMIFINAL #1").first()
    sf2 = Partido.objects.filter(categoria=categoria_obj, fase="SEMIFINAL", numero_fecha="SEMIFINAL #2").first()

    if not all([sf1, sf2]):
        messages.error(request, "Primero debes generar las semifinales.")
        return redirect("panel")

    g1 = ganador_partido(sf1)
    g2 = ganador_partido(sf2)

    if not all([g1, g2]):
        messages.error(request, "Las semifinales deben estar finalizadas para generar la final.")
        return redirect("panel")

    crear_o_actualizar_partido_final(categoria_obj, "FINAL", "FINAL", g1, g2)

    messages.success(request, f"Final generada correctamente para {categoria}.")
    return redirect("panel")

def perdedor_partido(partido):
    if partido.estado not in ESTADOS_PARTIDO_CERRADO:
        return None

    gl = partido.goles_local or 0
    gv = partido.goles_visitante or 0

    if gl > gv:
        return partido.equipo_visitante

    if gv > gl:
        return partido.equipo_local

    pl = partido.goles_local_penales or 0
    pv = partido.goles_visitante_penales or 0

    if pl > pv:
        return partido.equipo_visitante

    if pv > pl:
        return partido.equipo_local

    return None


@login_required
@user_passes_test(es_editor_torneo)
def generar_tercer_puesto(request, categoria):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.filter(nombre=categoria)
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria_obj = categorias.first()

    if not categoria_obj:
        messages.error(request, "Categoría no encontrada.")
        return redirect("panel")

    sf1 = Partido.objects.filter(
        categoria=categoria_obj,
        fase="SEMIFINAL",
        numero_fecha="SEMIFINAL #1"
    ).first()

    sf2 = Partido.objects.filter(
        categoria=categoria_obj,
        fase="SEMIFINAL",
        numero_fecha="SEMIFINAL #2"
    ).first()

    if not all([sf1, sf2]):
        messages.error(request, "Primero debes generar las semifinales.")
        return redirect("panel")

    perdedor_1 = perdedor_partido(sf1)
    perdedor_2 = perdedor_partido(sf2)

    if not all([perdedor_1, perdedor_2]):
        messages.error(request, "Las semifinales deben estar finalizadas para generar el tercer puesto.")
        return redirect("panel")

    crear_o_actualizar_partido_final(
        categoria_obj,
        "TERCER_PUESTO",
        "TERCER PUESTO",
        perdedor_1,
        perdedor_2
    )

    messages.success(request, f"Partido por tercer puesto generado correctamente para {categoria}.")
    return redirect("panel")
def construir_partidos_programacion(request, categoria_obj=None):
    dias_semana = {
        0: "LUNES",
        1: "MARTES",
        2: "MIÉRCOLES",
        3: "JUEVES",
        4: "VIERNES",
        5: "SÁBADO",
        6: "DOMINGO",
    }
    meses = {
        1: "ENERO",
        2: "FEBRERO",
        3: "MARZO",
        4: "ABRIL",
        5: "MAYO",
        6: "JUNIO",
        7: "JULIO",
        8: "AGOSTO",
        9: "SEPTIEMBRE",
        10: "OCTUBRE",
        11: "NOVIEMBRE",
        12: "DICIEMBRE",
    }

    torneo = torneo_actual(request)
    partidos = Partido.objects.filter(
        estado="PROGRAMADO",
        estado_programacion__in=["MANUAL", "OFICIAL"],
        fecha__isnull=False,
        hora__isnull=False,
        cancha__isnull=False,
    ).exclude(
        cancha=""
    ).exclude(
        cancha__iexact="Por definir"
    ).exclude(
        hora=time(0, 0)
    ).select_related(
        "categoria",
        "equipo_local",
        "equipo_visitante"
    ).order_by(
        "fecha",
        "cancha",
        "hora",
        "categoria__nombre",
        "grupo",
        "fase"
    )

    if torneo:
        partidos = partidos.filter(categoria__torneo=torneo)

    if categoria_obj:
        partidos = partidos.filter(categoria=categoria_obj)

    partidos_programacion = []

    for p in partidos:
        dia_semana = ""

        if p.fecha:
            dia_semana = dias_semana[p.fecha.weekday()]

        fase = p.fase or "GRUPOS"
        fecha_corta = ""

        if p.fecha:
            fecha_corta = f"{dia_semana} {p.fecha.day} {meses[p.fecha.month]}"

        hora_12 = ""

        if p.hora:
            hora = p.hora.hour
            periodo = "AM" if hora < 12 else "PM"
            hora_12 = hora % 12 or 12
            minuto = f":{p.hora.minute:02d}" if p.hora.minute else ""
            hora_12 = f"{hora_12}{minuto} {periodo}"

        categoria_nombre = p.categoria.nombre if p.categoria else ""
        categoria_normalizada = limpiar_nombre(categoria_nombre)
        color_categoria = "#f1db19"
        color_texto_categoria = "#111827"

        if "PLUS_50" in categoria_normalizada:
            color_categoria = "#075985"
            color_texto_categoria = "#ffffff"
        elif "INTERBARRIOS" in categoria_normalizada:
            color_categoria = "#166534"
            color_texto_categoria = "#ffffff"
        elif "SENIOR" in categoria_normalizada:
            color_categoria = "#f1db19"
            color_texto_categoria = "#111827"

        partidos_programacion.append({
            "categoria": categoria_nombre,
            "color_categoria": color_categoria,
            "color_texto_categoria": color_texto_categoria,
            "bloque": f"{fecha_corta} / CANCHA {p.cancha}",
            "hora_texto": hora_12,
            "numero_fecha": p.numero_fecha or "",
            "grupo": p.grupo,
            "fase": fase,
            "estado": p.estado,
            "dia_semana": dia_semana,
            "fecha": p.fecha,
            "hora": p.hora,
            "cancha": p.cancha,
            "local": p.equipo_local.nombre if p.equipo_local else "POR DEFINIR",
            "visitante": p.equipo_visitante.nombre if p.equipo_visitante else "POR DEFINIR",
            "escudo_local": url_absoluta(request, escudo_url(p.equipo_local)),
            "escudo_visitante": url_absoluta(request, escudo_url(p.equipo_visitante)),
        })

    return partidos_programacion


def medidas_programacion(cantidad):
    if cantidad > 8:
        filas = (cantidad + 1) // 2
        alto_disponible = 1600
        espacio_entre_tarjetas = 12 * max(filas - 1, 0)
        alto_tarjeta = max(95, min(270, (alto_disponible - espacio_entre_tarjetas) // filas))

        if alto_tarjeta >= 240:
            fuente_detalle = 18
            fuente_grupo = 19
            fuente_equipo = 21
            escudo = 56
        elif alto_tarjeta >= 180:
            fuente_detalle = 15
            fuente_grupo = 16
            fuente_equipo = 18
            escudo = 44
        else:
            fuente_detalle = 13
            fuente_grupo = 14
            fuente_equipo = 15
            escudo = 34

        return {
            "ancho": 1080,
            "alto": 1920,
            "compacta": True,
            "alto_tarjeta": alto_tarjeta,
            "fuente_detalle": fuente_detalle,
            "fuente_grupo": fuente_grupo,
            "fuente_equipo": fuente_equipo,
            "escudo": escudo,
        }

    if cantidad <= 4:
        alto = 1920
    elif cantidad <= 8:
        alto = 2850
    else:
        alto = 650 + (cantidad * 270)

    return {
        "ancho": 1080,
        "alto": alto,
        "compacta": False,
        "alto_tarjeta": 0,
        "fuente_detalle": 0,
        "fuente_grupo": 0,
        "fuente_equipo": 0,
        "escudo": 0,
    }


@login_required
@user_passes_test(es_editor_torneo)
def descargar_programacion_categoria(request, categoria):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.filter(nombre=categoria)
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria_obj = categorias.first()

    if not categoria_obj:
        return HttpResponse("Categoría no encontrada")

    partidos_programacion = construir_partidos_programacion(request, categoria_obj)

    if not partidos_programacion:
        return respuesta_descarga_sin_partidos(request, "No hay partidos programados con fecha, hora y cancha para esta categoria.")

    logos = logos_torneo(request, torneo)
    cantidad = len(partidos_programacion)
    medidas = medidas_programacion(cantidad)

    html = render_to_string("descargas/programacion_categoria.html", {
        "categoria": categoria,
        "partidos": partidos_programacion,
        "ancho": medidas["ancho"],
        "compacta": medidas["compacta"],
        "alto_tarjeta": medidas["alto_tarjeta"],
        "fuente_detalle": medidas["fuente_detalle"],
        "fuente_grupo": medidas["fuente_grupo"],
        "fuente_equipo": medidas["fuente_equipo"],
        "escudo": medidas["escudo"],
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"PROGRAMACION_PARTIDOS_PROGRAMADOS_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, medidas["ancho"], medidas["alto"], url_retorno_descarga(request))


@login_required
@user_passes_test(es_editor_torneo)
def descargar_programacion_general(request):
    torneo = torneo_actual(request)
    partidos_programacion = construir_partidos_programacion(request)

    if not partidos_programacion:
        return respuesta_descarga_sin_partidos(request, "No hay partidos programados con fecha, hora y cancha asignada.")

    logos = logos_torneo(request, torneo)
    cantidad = len(partidos_programacion)
    medidas = medidas_programacion(cantidad)

    html = render_to_string("descargas/programacion_categoria.html", {
        "categoria": "TODAS LAS CATEGORIAS",
        "mostrar_categoria": True,
        "partidos": partidos_programacion,
        "ancho": medidas["ancho"],
        "compacta": medidas["compacta"],
        "alto_tarjeta": medidas["alto_tarjeta"],
        "fuente_detalle": medidas["fuente_detalle"],
        "fuente_grupo": medidas["fuente_grupo"],
        "fuente_equipo": medidas["fuente_equipo"],
        "escudo": medidas["escudo"],
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = "PROGRAMACION_TODAS_LAS_CATEGORIAS.png"
    return crear_imagen_desde_html(html, nombre, medidas["ancho"], medidas["alto"], url_retorno_descarga(request))


# ======================================================
# EDITOR MÓVIL PROFESIONAL DE PARTIDOS
# ======================================================

def _jugadores_del_partido(partido):
    jugadores_local = Jugador.objects.filter(
        equipo=partido.equipo_local,
        estado='ACTIVO'
    ).order_by('dorsal', 'nombres')

    jugadores_visitante = Jugador.objects.filter(
        equipo=partido.equipo_visitante,
        estado='ACTIVO'
    ).order_by('dorsal', 'nombres')

    return jugadores_local, jugadores_visitante


def _validar_jugador_equipo(jugador, equipo, partido):
    equipos_validos = [partido.equipo_local_id, partido.equipo_visitante_id]
    return jugador.equipo_id == equipo.id and equipo.id in equipos_validos


def _url_editor_tab(partido_id, tab):
    return f"{reverse('editor_partido_movil', args=[partido_id])}#{tab}"


POSICIONES_ALINEACION_DEFAULT = [codigo for codigo, _ in AlineacionPartido.POSICIONES_CANCHA]


def _orden_partido(partido):
    return (
        partido.fecha or date.min,
        partido.hora or time.min,
        partido.id or 0,
    )


def _partidos_equipo_antes(partido, equipo):
    fecha_partido, hora_partido, _ = _orden_partido(partido)
    return Partido.objects.filter(
        categoria=partido.categoria,
        estado__in=ESTADOS_PARTIDO_CERRADO,
        estadisticas_validadas=True,
    ).filter(
        Q(equipo_local=equipo) | Q(equipo_visitante=equipo)
    ).filter(
        Q(fecha__lt=fecha_partido) |
        Q(fecha=fecha_partido, hora__lt=hora_partido) |
        Q(fecha=fecha_partido, hora=hora_partido, id__lt=partido.id)
    ).order_by("fecha", "hora", "id")


def _jugadores_sancionados_por_tarjetas(partido):
    sancionados = {}

    for equipo in [partido.equipo_local, partido.equipo_visitante]:
        partidos_previos = list(_partidos_equipo_antes(partido, equipo))
        if not partidos_previos:
            continue

        ultimo_partido = partidos_previos[-1]
        tarjetas_previas = Tarjeta.objects.filter(
            partido__in=partidos_previos,
            equipo=equipo,
        ).select_related("partido", "jugador", "equipo")

        tarjetas_por_jugador_partido = defaultdict(lambda: {"A": 0, "R": 0})
        amarillas_grupos_por_jugador = defaultdict(set)

        for tarjeta in tarjetas_previas:
            resumen = tarjetas_por_jugador_partido[(tarjeta.jugador_id, tarjeta.partido_id)]
            if tarjeta.tipo == "AMARILLA":
                resumen["A"] += 1
                if (tarjeta.partido.fase or "GRUPOS") == "GRUPOS":
                    amarillas_grupos_por_jugador[tarjeta.jugador_id].add(tarjeta.partido_id)
            elif tarjeta.tipo == "ROJA":
                resumen["R"] += 1

        jugadores_con_tarjeta = {
            jugador_id
            for jugador_id, _ in tarjetas_por_jugador_partido.keys()
        }

        for jugador_id in jugadores_con_tarjeta:
            tarjetas_ultimo = tarjetas_por_jugador_partido.get((jugador_id, ultimo_partido.id), {"A": 0, "R": 0})
            motivo = ""

            if tarjetas_ultimo["R"] > 0:
                motivo = "roja directa"
            elif tarjetas_ultimo["A"] >= 2:
                motivo = "doble amarilla"
            elif (ultimo_partido.fase or "GRUPOS") == "GRUPOS" and tarjetas_ultimo["A"] > 0:
                amarillas_hasta_ultimo = len(amarillas_grupos_por_jugador[jugador_id])
                amarillas_antes_ultimo = amarillas_hasta_ultimo - 1
                if amarillas_antes_ultimo < 3 <= amarillas_hasta_ultimo:
                    motivo = "3 amarillas en fase 1"

            if motivo:
                sancionados[jugador_id] = {
                    "equipo_id": equipo.id,
                    "motivo": motivo,
                    "partido_origen": ultimo_partido,
                }

    return sancionados


def _sincronizar_no_disponibles_por_tarjetas(partido):
    if partido.estado in ESTADOS_PARTIDO_CERRADO:
        return {}

    sancionados = _jugadores_sancionados_por_tarjetas(partido)
    if not sancionados:
        return {}

    alineaciones = AlineacionPartido.objects.filter(
        partido=partido,
        jugador_id__in=sancionados.keys(),
    )
    alineaciones_por_jugador = {alineacion.jugador_id: alineacion for alineacion in alineaciones}
    nuevas = []

    for jugador_id, data in sancionados.items():
        alineacion = alineaciones_por_jugador.get(jugador_id)
        if alineacion:
            if alineacion.rol != "NO_DISPONIBLE" or alineacion.posicion_cancha:
                alineacion.rol = "NO_DISPONIBLE"
                alineacion.posicion_cancha = ""
                alineacion.equipo_id = data["equipo_id"]
                alineacion.save(update_fields=["rol", "posicion_cancha", "equipo"])
        else:
            nuevas.append(AlineacionPartido(
                partido=partido,
                equipo_id=data["equipo_id"],
                jugador_id=jugador_id,
                rol="NO_DISPONIBLE",
                posicion_cancha="",
            ))

    if nuevas:
        AlineacionPartido.objects.bulk_create(nuevas, ignore_conflicts=True)

    return sancionados


def _marcar_roles_alineacion(jugadores, alineaciones_por_jugador, partido=None):
    for jugador in jugadores:
        alineacion = alineaciones_por_jugador.get(jugador.id)
        jugador.rol_alineacion = alineacion.rol if alineacion else ""
        jugador.posicion_alineacion = alineacion.posicion_cancha if alineacion else ""
        jugador.foto_alineacion = foto_jugador_url(jugador)
        jugador.iniciales_alineacion = iniciales_jugador(jugador)
        jugador.etiqueta_edad = etiqueta_edad_jugador(
            jugador,
            partido.categoria if partido else None,
            partido.fecha if partido else None,
        )
        jugador.texto_edad = texto_edad_jugador(
            jugador,
            partido.categoria if partido else None,
            partido.fecha if partido else None,
        )
    return jugadores


def _ordenar_titulares_cancha(items):
    usadas = {item.posicion for item in items if item.posicion}
    disponibles = [posicion for posicion in POSICIONES_ALINEACION_DEFAULT if posicion not in usadas]
    for item in items:
        if not item.posicion:
            item.posicion = disponibles.pop(0) if disponibles else ""
    return sorted(items, key=lambda item: AlineacionPartido.ORDEN_POSICIONES_CANCHA.get(item.posicion, 99))


def _recalcular_marcador_por_goles(partido):
    goles_local = 0
    goles_visitante = 0

    for gol in Gol.objects.filter(partido=partido).only("equipo_id", "cantidad", "es_autogol"):
        cantidad = max(gol.cantidad or 1, 1)
        if gol.es_autogol:
            if gol.equipo_id == partido.equipo_local_id:
                goles_visitante += cantidad
            elif gol.equipo_id == partido.equipo_visitante_id:
                goles_local += cantidad
        elif gol.equipo_id == partido.equipo_local_id:
            goles_local += cantidad
        elif gol.equipo_id == partido.equipo_visitante_id:
            goles_visitante += cantidad

    partido.goles_local = goles_local
    partido.goles_visitante = goles_visitante
    partido.save(update_fields=["goles_local", "goles_visitante"])


def _minuto_evento_en_vivo(partido):
    if partido.estado != "EN_JUEGO":
        return None

    segundos = partido.segundos_acumulados or 0
    if partido.inicio_en_vivo and not partido.cronometro_pausado:
        segundos += max(int((timezone.now() - partido.inicio_en_vivo).total_seconds()), 0)

    return max((segundos // 60) + 1, 1)


def _clave_orden_evento_resumen(evento):
    creado_en = getattr(evento, "creado_en", None)
    return (
        evento.minuto is None,
        evento.minuto if evento.minuto is not None else 999,
        creado_en is None,
        creado_en.timestamp() if creado_en else 0,
        evento.orden or 0,
    )


@login_required
def editor_partido_movil(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related('categoria', 'equipo_local', 'equipo_visitante'),
        id=partido_id
    )
    equipo_delegado = equipo_delegado_para_partido(request.user, partido)
    if equipo_delegado:
        if puede_editar_alineacion_delegado(request.user, partido, equipo_delegado):
            return redirect("delegado_alineacion_partido", equipo_id=equipo_delegado.id, partido_id=partido.id)
        _, motivo = ventana_alineacion_delegado(partido)
        return HttpResponseForbidden(f"Los delegados solo pueden editar la alineacion de su equipo. {motivo}")
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    sancionados_tarjetas = _sincronizar_no_disponibles_por_tarjetas(partido)

    jugadores_local, jugadores_visitante = _jugadores_del_partido(partido)

    goles = Gol.objects.filter(partido=partido).select_related('jugador', 'equipo').order_by('equipo__nombre', 'jugador__nombres')
    tarjetas = Tarjeta.objects.filter(partido=partido).select_related('jugador', 'equipo').order_by('equipo__nombre', 'tipo', 'jugador__nombres')
    alineaciones = AlineacionPartido.objects.filter(partido=partido).select_related('jugador', 'equipo').order_by('equipo__nombre', 'rol', 'jugador__nombres')
    sustituciones = SustitucionPartido.objects.filter(partido=partido).select_related('equipo', 'jugador_sale', 'jugador_entra').order_by('equipo__nombre', 'minuto', 'id')
    alineaciones_por_jugador = {alineacion.jugador_id: alineacion for alineacion in alineaciones}
    jugadores_local = _marcar_roles_alineacion(jugadores_local, alineaciones_por_jugador, partido)
    jugadores_visitante = _marcar_roles_alineacion(jugadores_visitante, alineaciones_por_jugador, partido)

    return render(request, 'editor_partido_movil.html', {
        'partido': partido,
        'jugadores_local': jugadores_local,
        'jugadores_visitante': jugadores_visitante,
        'goles': goles,
        'tarjetas': tarjetas,
        'alineaciones': alineaciones,
        'sustituciones': sustituciones,
        'estados_partido': (
            Partido.ESTADOS
            if es_editor_torneo(request.user)
            else [(valor, etiqueta) for valor, etiqueta in Partido.ESTADOS if valor in ESTADOS_PLANILLERO_PARTIDO]
        ),
        'fases_partido': Partido.FASES,
        'posiciones_cancha': AlineacionPartido.POSICIONES_CANCHA,
        'sancionados_tarjetas': sancionados_tarjetas,
        'puede_editar_programacion': es_editor_torneo(request.user),
    })


@login_required
@require_POST
def guardar_info_partido_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()

    minimo_goles = None if es_editor_torneo(request.user) else 0
    partido.goles_local = entero_post(request, 'goles_local', 0, minimo_goles)
    partido.goles_visitante = entero_post(request, 'goles_visitante', 0, minimo_goles)
    estado_solicitado = request.POST.get('estado') or partido.estado
    if es_editor_torneo(request.user) or estado_solicitado in ESTADOS_PLANILLERO_PARTIDO:
        partido.estado = estado_solicitado

    if partido.estado == "EN_JUEGO" and not partido.inicio_en_vivo:
        partido.inicio_en_vivo = timezone.now()

    partido.goles_local_penales = entero_post(request, 'goles_local_penales', 0, 0)
    partido.goles_visitante_penales = entero_post(request, 'goles_visitante_penales', 0, 0)
    partido.observaciones = request.POST.get('observaciones') or ''

    if es_editor_torneo(request.user):
        partido.fecha = request.POST.get('fecha') or partido.fecha
        partido.hora = request.POST.get('hora') or partido.hora
        partido.cancha = request.POST.get('cancha') or ''
        partido.numero_fecha = request.POST.get('numero_fecha') or ''
        partido.grupo = request.POST.get('grupo') or ''
        partido.fase = request.POST.get('fase') or partido.fase
        partido.ajuste_puntos_local = entero_post(request, 'ajuste_puntos_local', 0)
        partido.ajuste_puntos_visitante = entero_post(request, 'ajuste_puntos_visitante', 0)
        partido.observacion_comite = request.POST.get('observacion_comite') or ''
    partido.save()
    _marcar_estadisticas_pendientes(partido, request.user)

    messages.success(request, 'Partido actualizado correctamente.')
    if not es_editor_torneo(request.user) and partido.estado == "FINALIZADO":
        return redirect('partido_live', partido_id=partido.id)
    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@require_POST
def agregar_gol_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    jugador_id = request.POST.get('jugador')
    equipo_id = request.POST.get('equipo')
    cantidad = request.POST.get('cantidad') or 1
    es_autogol = request.POST.get('es_autogol') == '1'
    es_penal = request.POST.get('es_penal') == '1'
    try:
        cantidad = max(int(cantidad), 1)
    except (TypeError, ValueError):
        cantidad = 1

    if jugador_id and equipo_id:
        jugador = get_object_or_404(Jugador, id=jugador_id)
        equipo = get_object_or_404(Equipo, id=equipo_id)

        if _validar_jugador_equipo(jugador, equipo, partido):
            Gol.objects.create(
                partido=partido,
                jugador=jugador,
                equipo=equipo,
                cantidad=cantidad,
                es_autogol=es_autogol,
                es_penal=es_penal,
                minuto=_minuto_evento_en_vivo(partido),
            )
            _recalcular_marcador_por_goles(partido)
            _marcar_estadisticas_pendientes(partido, request.user)
            if es_autogol:
                messages.success(request, 'Autogol agregado correctamente.')
            elif es_penal:
                messages.success(request, 'Gol de penal agregado correctamente.')
            else:
                messages.success(request, 'Gol agregado correctamente.')
        else:
            messages.error(request, 'El jugador no pertenece al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@require_POST
def agregar_tarjeta_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    jugador_id = request.POST.get('jugador')
    equipo_id = request.POST.get('equipo')
    tipo = request.POST.get('tipo')

    if jugador_id and equipo_id and tipo:
        jugador = get_object_or_404(Jugador, id=jugador_id)
        equipo = get_object_or_404(Equipo, id=equipo_id)

        if _validar_jugador_equipo(jugador, equipo, partido):
            Tarjeta.objects.create(
                partido=partido,
                jugador=jugador,
                equipo=equipo,
                tipo=tipo,
                minuto=_minuto_evento_en_vivo(partido),
            )
            _marcar_estadisticas_pendientes(partido, request.user)
            messages.success(request, 'Tarjeta agregada correctamente.')
        else:
            messages.error(request, 'El jugador no pertenece al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@require_POST
def agregar_alineacion_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    sancionados_tarjetas = _sincronizar_no_disponibles_por_tarjetas(partido)
    jugador_id = request.POST.get('jugador')
    equipo_id = request.POST.get('equipo')
    rol = request.POST.get('rol') or 'TITULAR'
    posicion_cancha = request.POST.get('posicion_cancha') or ''
    posiciones_validas = {codigo for codigo, _ in AlineacionPartido.POSICIONES_CANCHA}
    if posicion_cancha not in posiciones_validas:
        posicion_cancha = ''

    if jugador_id and equipo_id:
        jugador = get_object_or_404(Jugador, id=jugador_id)
        equipo = get_object_or_404(Equipo, id=equipo_id)

        if _validar_jugador_equipo(jugador, equipo, partido):
            if jugador.id in sancionados_tarjetas and rol != "NO_DISPONIBLE":
                messages.error(request, 'Este jugador esta sancionado por tarjetas y queda como no disponible.')
                return redirect(_url_editor_tab(partido.id, "alineacion"))
            AlineacionPartido.objects.update_or_create(
                partido=partido,
                jugador=jugador,
                defaults={'equipo': equipo, 'rol': rol, 'posicion_cancha': posicion_cancha if rol == 'TITULAR' else ''}
            )
            _marcar_estadisticas_pendientes(partido, request.user)
            messages.success(request, 'Jugador agregado a la alineación.')
        else:
            messages.error(request, 'El jugador no pertenece al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@require_POST
def guardar_alineacion_masiva_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    sancionados_tarjetas = _sincronizar_no_disponibles_por_tarjetas(partido)
    equipo_id = request.POST.get("equipo")
    equipo = get_object_or_404(Equipo, id=equipo_id)

    if equipo.id not in [partido.equipo_local_id, partido.equipo_visitante_id]:
        messages.error(request, "Ese equipo no pertenece al partido.")
        return redirect(_url_editor_tab(partido.id, "alineacion"))

    jugadores_equipo = Jugador.objects.filter(equipo=equipo).only("id")
    jugadores_validos = {str(jugador.id) for jugador in jugadores_equipo}
    roles_validos = {"TITULAR", "SUPLENTE", "NO_DISPONIBLE"}
    posiciones_validas = {codigo for codigo, _ in AlineacionPartido.POSICIONES_CANCHA}
    sancionados_equipo = {
        str(jugador_id)
        for jugador_id, data in sancionados_tarjetas.items()
        if data["equipo_id"] == equipo.id
    }
    posiciones_usadas = set()
    seleccionados = []

    for llave, rol in request.POST.items():
        if not llave.startswith("rol_") or rol not in roles_validos:
            continue

        jugador_id = llave.replace("rol_", "", 1)
        if jugador_id in jugadores_validos:
            posicion = request.POST.get(f"posicion_{jugador_id}") or ""
            if jugador_id in sancionados_equipo:
                rol = "NO_DISPONIBLE"
            if rol == "TITULAR":
                if posicion not in posiciones_validas:
                    posicion = ""
                if posicion and posicion in posiciones_usadas:
                    messages.error(request, "No repitas la misma posición en la cancha.")
                    return redirect(_url_editor_tab(partido.id, "alineacion"))
                if posicion:
                    posiciones_usadas.add(posicion)
            else:
                posicion = ""
            seleccionados.append((jugador_id, rol, posicion))

    seleccionados_ids = {jugador_id for jugador_id, _, _ in seleccionados}
    for jugador_id in sancionados_equipo - seleccionados_ids:
        if jugador_id in jugadores_validos:
            seleccionados.append((jugador_id, "NO_DISPONIBLE", ""))

    titulares = [jugador_id for jugador_id, rol, _ in seleccionados if rol == "TITULAR"]
    if len(titulares) > 11:
        messages.error(request, "Solo puedes seleccionar 11 titulares por equipo.")
        return redirect(_url_editor_tab(partido.id, "alineacion"))
    errores_edad = validar_reglas_edad_titulares(partido, equipo, titulares)

    AlineacionPartido.objects.filter(partido=partido, equipo=equipo).delete()
    nuevas_alineaciones = [
        AlineacionPartido(partido=partido, equipo=equipo, jugador_id=jugador_id, rol=rol, posicion_cancha=posicion)
        for jugador_id, rol, posicion in seleccionados
    ]
    AlineacionPartido.objects.bulk_create(nuevas_alineaciones)
    _marcar_estadisticas_pendientes(partido, request.user)

    if sancionados_equipo:
        messages.warning(
            request,
            "Los jugadores sancionados por tarjetas quedaron como no disponibles."
        )
    if errores_edad:
        messages.warning(
            request,
            "Advertencia de reglas de edad: " + " ".join(errores_edad)
        )
    messages.success(
        request,
        f"Alineacion de {equipo.nombre} guardada: {len(titulares)} titulares, "
        f"{sum(1 for _, rol, _ in seleccionados if rol == 'SUPLENTE')} suplentes."
    )
    return redirect(_url_editor_tab(partido.id, "alineacion"))


@login_required
@require_POST
def agregar_sustitucion_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    equipo_id = request.POST.get('equipo')
    jugador_sale_id = request.POST.get('jugador_sale')
    jugador_entra_id = request.POST.get('jugador_entra')
    minuto = request.POST.get('minuto') or None
    observacion = request.POST.get('observacion') or ''

    if equipo_id and jugador_sale_id and jugador_entra_id:
        equipo = get_object_or_404(Equipo, id=equipo_id)
        jugador_sale = get_object_or_404(Jugador, id=jugador_sale_id)
        jugador_entra = get_object_or_404(Jugador, id=jugador_entra_id)

        if _validar_jugador_equipo(jugador_sale, equipo, partido) and _validar_jugador_equipo(jugador_entra, equipo, partido):
            SustitucionPartido.objects.create(
                partido=partido,
                equipo=equipo,
                jugador_sale=jugador_sale,
                jugador_entra=jugador_entra,
                minuto=minuto,
                observacion=observacion
            )
            _marcar_estadisticas_pendientes(partido, request.user)
            messages.success(request, 'Sustitución agregada correctamente.')
        else:
            messages.error(request, 'Los jugadores deben pertenecer al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@require_POST
def eliminar_gol_movil(request, gol_id):
    gol = get_object_or_404(Gol, id=gol_id)
    partido_id = gol.partido_id
    partido = gol.partido
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    gol.delete()
    _recalcular_marcador_por_goles(partido)
    _marcar_estadisticas_pendientes(partido, request.user)
    messages.success(request, 'Gol eliminado.')
    return redirect('editor_partido_movil', partido_id=partido_id)


@login_required
@require_POST
def eliminar_tarjeta_movil(request, tarjeta_id):
    tarjeta = get_object_or_404(Tarjeta, id=tarjeta_id)
    partido_id = tarjeta.partido_id
    if not puede_diligenciar_partido(request.user, tarjeta.partido):
        return denegar_partido_no_autorizado()
    tarjeta.delete()
    _marcar_estadisticas_pendientes(tarjeta.partido, request.user)
    messages.success(request, 'Tarjeta eliminada.')
    return redirect('editor_partido_movil', partido_id=partido_id)


@login_required
@require_POST
def eliminar_alineacion_movil(request, alineacion_id):
    alineacion = get_object_or_404(AlineacionPartido, id=alineacion_id)
    partido_id = alineacion.partido_id
    if not puede_diligenciar_partido(request.user, alineacion.partido):
        return denegar_partido_no_autorizado()
    alineacion.delete()
    _marcar_estadisticas_pendientes(alineacion.partido, request.user)
    messages.success(request, 'Jugador eliminado de la alineación.')
    return redirect('editor_partido_movil', partido_id=partido_id)


@login_required
@require_POST
def eliminar_sustitucion_movil(request, sustitucion_id):
    sustitucion = get_object_or_404(SustitucionPartido, id=sustitucion_id)
    partido_id = sustitucion.partido_id
    if not puede_diligenciar_partido(request.user, sustitucion.partido):
        return denegar_partido_no_autorizado()
    sustitucion.delete()
    _marcar_estadisticas_pendientes(sustitucion.partido, request.user)
    messages.success(request, 'Sustitución eliminada.')
    return redirect('editor_partido_movil', partido_id=partido_id)

def lista_equipos(request):
    equipos = Equipo.objects.select_related(
        'categoria'
    ).order_by(
        'categoria__nombre',
        'nombre'
    )

    return render(request, 'equipos/lista_equipos.html', {
        'equipos': equipos
    })


def detalle_equipo(request, equipo_id):
    equipo = get_object_or_404(
        Equipo.objects.select_related('categoria'),
        id=equipo_id
    )

    jugadores = Jugador.objects.filter(
        equipo=equipo
    ).order_by(
        'dorsal',
        'nombres'
    )

    return render(request, 'equipos/detalle_equipo.html', {
        'equipo': equipo,
        'jugadores': jugadores
    })

@login_required
def mis_equipos(request):
    equipos = list(equipos_delegado_asignados(request.user).order_by('categoria__nombre', 'nombre'))
    ahora = timezone.now()
    for equipo in equipos:
        equipo.acceso_vigente_delegado = equipo.acceso_delegado_vigente()
        if not equipo.acceso_delegado_hasta:
            equipo.estado_acceso_delegado = "Sin fecha de acceso asignada."
        elif equipo.acceso_delegado_hasta < ahora:
            equipo.estado_acceso_delegado = f"Acceso vencido el {timezone.localtime(equipo.acceso_delegado_hasta).strftime('%d/%m/%Y %H:%M')}."
        else:
            equipo.estado_acceso_delegado = f"Disponible hasta {timezone.localtime(equipo.acceso_delegado_hasta).strftime('%d/%m/%Y %H:%M')}."

    return render(request, 'equipos/mis_equipos.html', {
        'equipos': equipos
    })


@login_required
def delegado_equipo_editar(request, equipo_id):
    equipo = get_object_or_404(equipos_alineacion_para_usuario(request.user), id=equipo_id)
    if not puede_editar_equipo_delegado(request.user, equipo):
        messages.warning(request, "La edicion del equipo esta bloqueada. Puedes cargar la alineacion de partidos desde aqui.")
        return redirect("delegado_partidos_equipo", equipo_id=equipo.id)

    form = EquipoDelegadoForm(request.POST or None, request.FILES or None, instance=equipo)
    jugadores = equipo.jugadores.order_by("dorsal", "nombres")

    if request.method == "POST" and form.is_valid():
        equipo = form.save(commit=False)
        equipo.save()
        messages.success(request, "Equipo actualizado correctamente.")
        return redirect("delegado_equipo_editar", equipo_id=equipo.id)

    return render(request, "equipos/delegado_equipo_formulario.html", {
        "titulo": f"Editar equipo: {equipo.nombre}",
        "equipo": equipo,
        "form": form,
        "jugadores": jugadores,
    })


@login_required
def delegado_partidos_equipo(request, equipo_id):
    equipo = get_object_or_404(equipos_alineacion_para_usuario(request.user), id=equipo_id)

    return render(request, "equipos/delegado_partidos_equipo.html", {
        "equipo": equipo,
        "partidos_alineacion": partidos_alineacion_para_equipo(equipo),
    })


@login_required
def delegado_alineacion_partido(request, equipo_id, partido_id):
    equipo = get_object_or_404(equipos_alineacion_para_usuario(request.user), id=equipo_id)
    partido = get_object_or_404(
        Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante"),
        id=partido_id,
        categoria=equipo.categoria,
    )
    if not partido_pertenece_equipo(partido, equipo):
        return HttpResponseForbidden("Este equipo no pertenece al partido.")
    if not puede_editar_alineacion_delegado(request.user, partido, equipo):
        _, motivo = ventana_alineacion_delegado(partido)
        return HttpResponseForbidden(f"No puedes editar esta alineacion en este momento. {motivo}")

    sancionados_tarjetas = _sincronizar_no_disponibles_por_tarjetas(partido)
    jugadores = list(Jugador.objects.filter(equipo=equipo, estado="ACTIVO").order_by("dorsal", "nombres"))
    alineaciones = AlineacionPartido.objects.filter(partido=partido, equipo=equipo).select_related("jugador")
    alineaciones_por_jugador = {alineacion.jugador_id: alineacion for alineacion in alineaciones}
    jugadores = _marcar_roles_alineacion(jugadores, alineaciones_por_jugador, partido)
    sancionados_equipo = {
        jugador_id: data
        for jugador_id, data in sancionados_tarjetas.items()
        if data["equipo_id"] == equipo.id
    }

    if request.method == "POST":
        jugadores_validos = {str(jugador.id) for jugador in jugadores}
        roles_validos = {"TITULAR", "SUPLENTE", "NO_DISPONIBLE"}
        posiciones_validas = {codigo for codigo, _ in AlineacionPartido.POSICIONES_CANCHA}
        posiciones_usadas = set()
        jugadores_en_cancha = {}
        seleccionados = []

        for posicion in posiciones_validas:
            jugador_id = request.POST.get(f"cancha_{posicion}") or ""
            if not jugador_id:
                continue
            if jugador_id not in jugadores_validos:
                continue
            if jugador_id in jugadores_en_cancha:
                messages.error(request, "No repitas el mismo jugador en la cancha.")
                return redirect("delegado_alineacion_partido", equipo_id=equipo.id, partido_id=partido.id)
            if int(jugador_id) in sancionados_equipo:
                messages.error(request, "Un jugador sancionado no puede quedar como titular.")
                return redirect("delegado_alineacion_partido", equipo_id=equipo.id, partido_id=partido.id)
            jugadores_en_cancha[jugador_id] = posicion
            posiciones_usadas.add(posicion)

        for jugador in jugadores:
            jugador_id = str(jugador.id)
            rol = request.POST.get(f"rol_{jugador_id}") or ""
            if jugador_id in jugadores_en_cancha:
                rol = "TITULAR"
            if rol not in roles_validos:
                continue
            if jugador_id not in jugadores_validos:
                continue
            if jugador.id in sancionados_equipo:
                rol = "NO_DISPONIBLE"
            posicion = jugadores_en_cancha.get(jugador_id) or request.POST.get(f"posicion_{jugador_id}") or ""
            if rol == "TITULAR":
                if posicion not in posiciones_validas:
                    posicion = ""
                if posicion and posicion not in jugadores_en_cancha.values() and posicion in posiciones_usadas:
                    messages.error(request, "No repitas la misma posicion en la cancha.")
                    return redirect("delegado_alineacion_partido", equipo_id=equipo.id, partido_id=partido.id)
                if posicion:
                    posiciones_usadas.add(posicion)
            else:
                posicion = ""
            seleccionados.append((jugador.id, rol, posicion))

        seleccionados_ids = {jugador_id for jugador_id, _, _ in seleccionados}
        for jugador_id in sancionados_equipo.keys() - seleccionados_ids:
            seleccionados.append((jugador_id, "NO_DISPONIBLE", ""))

        titulares = [jugador_id for jugador_id, rol, _ in seleccionados if rol == "TITULAR"]
        if len(titulares) > 11:
            messages.error(request, "Solo puedes seleccionar 11 titulares.")
            return redirect("delegado_alineacion_partido", equipo_id=equipo.id, partido_id=partido.id)

        errores_edad = validar_reglas_edad_titulares(partido, equipo, titulares)
        AlineacionPartido.objects.filter(partido=partido, equipo=equipo).delete()
        AlineacionPartido.objects.bulk_create([
            AlineacionPartido(partido=partido, equipo=equipo, jugador_id=jugador_id, rol=rol, posicion_cancha=posicion)
            for jugador_id, rol, posicion in seleccionados
        ])
        _marcar_estadisticas_pendientes(partido, request.user)

        if sancionados_equipo:
            messages.warning(request, "Los jugadores sancionados quedaron como no disponibles.")
        if errores_edad:
            messages.warning(request, "Advertencia de reglas de edad: " + " ".join(errores_edad))
        messages.success(request, f"Alineacion guardada para {equipo.nombre}.")
        return redirect("delegado_partidos_equipo", equipo_id=equipo.id)

    return render(request, "equipos/delegado_alineacion_partido.html", {
        "equipo": equipo,
        "partido": partido,
        "jugadores": jugadores,
        "posiciones_cancha": AlineacionPartido.POSICIONES_CANCHA,
        "sancionados_tarjetas": sancionados_equipo,
    })


@login_required
def delegado_jugador_nuevo(request, equipo_id):
    equipo = get_object_or_404(equipos_editables_para_usuario(request.user), id=equipo_id)
    if not puede_editar_equipo_delegado(request.user, equipo):
        return HttpResponseForbidden("El acceso a este equipo ya no esta vigente.")

    form = JugadorDelegadoForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        jugador = form.save(commit=False)
        jugador.equipo = equipo
        jugador.nombres = jugador.nombres.upper()
        jugador.save()
        messages.success(request, "Jugador agregado correctamente.")
        return redirect("delegado_equipo_editar", equipo_id=equipo.id)

    return render(request, "equipos/delegado_jugador_formulario.html", {
        "titulo": f"Agregar jugador: {equipo.nombre}",
        "equipo": equipo,
        "form": form,
    })


@login_required
def delegado_jugador_editar(request, jugador_id):
    jugador = get_object_or_404(
        Jugador.objects.select_related("equipo", "equipo__categoria"),
        id=jugador_id,
    )
    if not puede_editar_equipo_delegado(request.user, jugador.equipo):
        return HttpResponseForbidden("No tienes permiso para editar este jugador.")

    form = JugadorDelegadoForm(request.POST or None, request.FILES or None, instance=jugador)

    if request.method == "POST" and form.is_valid():
        jugador = form.save(commit=False)
        jugador.nombres = jugador.nombres.upper()
        jugador.save()
        messages.success(request, "Jugador actualizado correctamente.")
        return redirect("delegado_equipo_editar", equipo_id=jugador.equipo_id)

    return render(request, "equipos/delegado_jugador_formulario.html", {
        "titulo": f"Editar jugador: {jugador.nombres}",
        "equipo": jugador.equipo,
        "form": form,
        "jugador": jugador,
    })


@login_required
@require_POST
def delegado_jugador_eliminar(request, jugador_id):
    jugador = get_object_or_404(
        Jugador.objects.select_related("equipo"),
        id=jugador_id,
    )
    equipo_id = jugador.equipo_id
    if not puede_editar_equipo_delegado(request.user, jugador.equipo):
        return HttpResponseForbidden("No tienes permiso para eliminar este jugador.")

    nombre = jugador.nombres
    jugador.delete()
    messages.success(request, f"Jugador eliminado: {nombre}.")
    return redirect("delegado_equipo_editar", equipo_id=equipo_id)


@login_required
@user_passes_test(es_editor_torneo)
def crear_jugador_equipo(request, equipo_id):
    equipo = get_object_or_404(
        Equipo,
        id=equipo_id,
        responsable=request.user
    )

    if request.method == 'POST':
        nombres = request.POST.get('nombres')
        dorsal = request.POST.get('dorsal')
        cedula = request.POST.get('cedula')
        fecha_nacimiento = request.POST.get('fecha_nacimiento')
        foto = request.FILES.get('foto')

        Jugador.objects.create(
            equipo=equipo,
            nombres=nombres,
            dorsal=dorsal,
            cedula=cedula,
            fecha_nacimiento=fecha_nacimiento,
            foto=foto
        )

        return redirect('detalle_equipo', equipo_id=equipo.id)

    return render(request, 'equipos/crear_jugador.html', {
        'equipo': equipo
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_probar_storage(request):
    def subir_prueba():
        nombre_archivo = f"pruebas/render-test-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
        nombre = default_storage.save(nombre_archivo, ContentFile(b"ok"))
        return nombre, default_storage.url(nombre)

    try:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(subir_prueba)
        try:
            nombre, url = future.result(timeout=10)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except TimeoutError:
        return HttpResponse(
            "ERROR STORAGE\n\nTimeoutError: Supabase Storage no respondio en 10 segundos desde Render.",
            status=504,
            content_type="text/plain",
        )
    except Exception as exc:
        return HttpResponse(
            f"ERROR STORAGE\n\n{type(exc).__name__}: {exc}",
            status=500,
            content_type="text/plain",
        )

    return HttpResponse(
        f"STORAGE OK\n\nArchivo: {nombre}\nURL: {url}",
        content_type="text/plain",
    )


@login_required
@user_passes_test(es_editor_torneo)
def gestion_panel(request):
    torneo = torneo_actual(request)
    organizadores = Organizador.objects.all() if tabla_disponible("torneos_organizador") else None
    categorias = Categoria.objects.all()
    equipos = Equipo.objects.all()
    jugadores = Jugador.objects.all()
    partidos = Partido.objects.all()
    documentos = Documento.objects.all()

    if torneo:
        categorias = categorias.filter(torneo=torneo)
        equipos = equipos.filter(categoria__torneo=torneo)
        jugadores = jugadores.filter(equipo__categoria__torneo=torneo)
        partidos = partidos.filter(categoria__torneo=torneo)
        documentos = documentos.filter(torneo=torneo)

    return render(request, "gestion/panel.html", {
        "torneo_seleccionado": torneo,
        "total_organizadores": organizadores.count() if organizadores is not None else 0,
        "total_categorias": categorias.count(),
        "total_equipos": equipos.count(),
        "total_jugadores": jugadores.count(),
        "total_partidos": partidos.count(),
        "total_documentos": documentos.count(),
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_actividad(request):
    if not tabla_disponible("torneos_registroactividad"):
        messages.error(request, "La tabla de actividad todavia no esta creada. Ejecuta las migraciones.")
        return redirect("gestion_panel")

    torneo = torneo_actual(request)
    registros = RegistroActividad.objects.select_related("usuario", "torneo").order_by("-creado_en")
    torneos = torneos_para_usuario(request)

    if not request.user.is_superuser:
        registros = registros.filter(Q(torneo__in=torneos) | Q(torneo__isnull=True))
    elif torneo:
        registros = registros.filter(torneo=torneo)

    usuario_id = request.GET.get("usuario", "").strip()
    accion = request.GET.get("accion", "").strip()

    if usuario_id:
        registros = registros.filter(usuario_id=usuario_id)

    if accion:
        registros = registros.filter(accion=accion)

    acciones = RegistroActividad.objects.order_by("accion").values_list("accion", flat=True).distinct()
    usuarios = User.objects.filter(actividad_admin__isnull=False).distinct().order_by("username")

    return render(request, "gestion/actividad.html", {
        "registros": registros[:250],
        "torneo_seleccionado": torneo,
        "usuarios": usuarios,
        "acciones": acciones,
        "usuario_id": usuario_id,
        "accion": accion,
    })


@login_required
@user_passes_test(es_superadmin)
def gestion_organizadores(request):
    if not tabla_disponible("torneos_organizador"):
        messages.error(request, "La tabla de organizadores todavia no esta creada. Espera que Render termine de aplicar las migraciones.")
        return redirect("gestion_panel")

    organizadores = Organizador.objects.order_by("nombre")

    return render(request, "gestion/organizadores.html", {
        "organizadores": organizadores,
    })


@login_required
@user_passes_test(es_superadmin)
def gestion_organizador_nuevo(request):
    form = OrganizadorForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        organizador = form.save()
        registrar_actividad(request, "CREAR", organizador, descripcion=f"Creo organizador {organizador.nombre}.")
        messages.success(request, "Organizador creado correctamente.")
        return redirect("gestion_organizadores")

    return render(request, "gestion/formulario.html", {
        "titulo": "Nuevo organizador",
        "form": form,
        "volver_url": "gestion_organizadores",
    })


@login_required
@user_passes_test(es_superadmin)
def gestion_organizador_editar(request, organizador_id):
    organizador = get_object_or_404(Organizador, id=organizador_id)
    form = OrganizadorForm(request.POST or None, request.FILES or None, instance=organizador)

    if request.method == "POST" and form.is_valid():
        organizador = form.save()
        registrar_actividad(request, "EDITAR", organizador, descripcion=f"Actualizo organizador {organizador.nombre}.")
        messages.success(request, "Organizador actualizado correctamente.")
        return redirect("gestion_organizadores")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar organizador: {organizador.nombre}",
        "form": form,
        "volver_url": "gestion_organizadores",
    })


@login_required
@user_passes_test(es_superadmin)
def gestion_organizador_admins(request, organizador_id):
    organizador = get_object_or_404(Organizador, id=organizador_id)
    asignaciones = AdminOrganizador.objects.select_related("usuario").filter(organizador=organizador)
    form = AdminOrganizadorForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        asignacion = form.save(commit=False)
        asignacion.organizador = organizador
        existente = AdminOrganizador.objects.filter(organizador=organizador, usuario=asignacion.usuario).first()

        if existente:
            existente.puede_editar = asignacion.puede_editar
            existente.puede_validar = asignacion.puede_validar
            existente.puede_programar = asignacion.puede_programar
            existente.activo = asignacion.activo
            existente.save()
            asignacion = existente
            mensaje = "Admin actualizado correctamente."
        else:
            asignacion.save()
            mensaje = "Admin asignado correctamente."

        registrar_actividad(
            request,
            "ASIGNAR_ADMIN_ORGANIZADOR",
            torneo=None,
            descripcion=f"Asigno admin {asignacion.usuario.username} al organizador {organizador.nombre}.",
            datos={
                "organizador": organizador.nombre,
                "usuario": asignacion.usuario.username,
                "puede_editar": asignacion.puede_editar,
                "puede_validar": asignacion.puede_validar,
                "puede_programar": asignacion.puede_programar,
                "activo": asignacion.activo,
            },
        )
        messages.success(request, mensaje)
        return redirect("gestion_organizador_admins", organizador_id=organizador.id)

    return render(request, "gestion/organizador_admins.html", {
        "organizador": organizador,
        "asignaciones": asignaciones,
        "form": form,
        "torneos": organizador.torneos.order_by("-fecha_inicio", "nombre"),
    })


@login_required
@user_passes_test(es_superadmin)
@require_POST
def gestion_organizador_admin_eliminar(request, asignacion_id):
    asignacion = get_object_or_404(AdminOrganizador.objects.select_related("organizador", "usuario"), id=asignacion_id)
    organizador = asignacion.organizador
    usuario = asignacion.usuario.username
    registrar_actividad(
        request,
        "QUITAR_ADMIN_ORGANIZADOR",
        torneo=None,
        descripcion=f"Quito admin {usuario} del organizador {organizador.nombre}.",
        datos={"organizador": organizador.nombre, "usuario": usuario},
    )
    asignacion.delete()
    messages.success(request, f"Admin retirado: {usuario}.")
    return redirect("gestion_organizador_admins", organizador_id=organizador.id)


@login_required
@user_passes_test(es_editor_torneo)
def gestion_torneos(request):
    torneos = torneos_para_usuario(request)

    return render(request, "gestion/torneos.html", {
        "torneos": torneos,
        "torneo_seleccionado": torneo_actual(request),
    })


@login_required
@user_passes_test(es_superadmin)
def gestion_torneo_nuevo(request):
    form = TorneoForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        torneo = form.save(commit=False)
        aplicar_imagenes_torneo_cloudinary(torneo, request.FILES)
        torneo.save()
        request.session["torneo_id"] = torneo.id
        registrar_actividad(request, "CREAR", torneo, descripcion=f"Creo torneo {torneo.nombre}.")
        messages.success(request, "Torneo creado correctamente.")
        return redirect("gestion_torneos")

    return render(request, "gestion/formulario.html", {
        "titulo": "Nuevo torneo",
        "form": form,
        "volver_url": "gestion_torneos",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_torneo_editar(request, torneo_id):
    torneo = get_object_or_404(torneos_para_usuario(request), id=torneo_id)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    form = TorneoForm(request.POST or None, request.FILES or None, instance=torneo)

    if request.method == "POST" and form.is_valid():
        torneo = form.save(commit=False)
        aplicar_imagenes_torneo_cloudinary(torneo, request.FILES)
        torneo.save()
        request.session["torneo_id"] = torneo.id
        registrar_actividad(request, "EDITAR", torneo, descripcion=f"Actualizo torneo {torneo.nombre}.")
        messages.success(request, "Torneo actualizado correctamente.")
        return redirect("gestion_torneos")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar torneo: {torneo.nombre}",
        "form": form,
        "volver_url": "gestion_torneos",
    })


@login_required
@user_passes_test(es_superadmin)
def gestion_torneo_admins(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    asignaciones = AdminTorneo.objects.select_related("usuario").filter(torneo=torneo)
    form = AdminTorneoForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        asignacion = form.save(commit=False)
        asignacion.torneo = torneo
        existente = AdminTorneo.objects.filter(torneo=torneo, usuario=asignacion.usuario).first()

        if existente:
            existente.puede_editar = asignacion.puede_editar
            existente.puede_validar = asignacion.puede_validar
            existente.puede_programar = asignacion.puede_programar
            existente.activo = asignacion.activo
            existente.save()
            asignacion = existente
            mensaje = "Admin actualizado correctamente."
        else:
            asignacion.save()
            mensaje = "Admin asignado correctamente."

        registrar_actividad(
            request,
            "ASIGNAR_ADMIN",
            torneo,
            descripcion=f"Asigno admin {asignacion.usuario.username} al torneo {torneo.nombre}.",
            datos={
                "usuario": asignacion.usuario.username,
                "puede_editar": asignacion.puede_editar,
                "puede_validar": asignacion.puede_validar,
                "puede_programar": asignacion.puede_programar,
                "activo": asignacion.activo,
            },
        )
        messages.success(request, mensaje)
        return redirect("gestion_torneo_admins", torneo_id=torneo.id)

    return render(request, "gestion/torneo_admins.html", {
        "torneo": torneo,
        "asignaciones": asignaciones,
        "form": form,
    })


@login_required
@user_passes_test(es_superadmin)
@require_POST
def gestion_torneo_admin_eliminar(request, asignacion_id):
    asignacion = get_object_or_404(AdminTorneo.objects.select_related("torneo", "usuario"), id=asignacion_id)
    torneo = asignacion.torneo
    usuario = asignacion.usuario.username
    registrar_actividad(request, "QUITAR_ADMIN", torneo, descripcion=f"Quito admin {usuario} del torneo {torneo.nombre}.")
    asignacion.delete()
    messages.success(request, f"Admin retirado: {usuario}.")
    return redirect("gestion_torneo_admins", torneo_id=torneo.id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def gestion_torneo_activar(request, torneo_id):
    torneo = get_object_or_404(torneos_para_usuario(request), id=torneo_id)
    request.session["torneo_id"] = torneo.id
    messages.success(request, f"Ahora estás gestionando: {torneo.nombre}.")
    return redirect("gestion_torneos")


@login_required
@user_passes_test(es_superadmin)
@require_POST
def gestion_torneo_eliminar(request, torneo_id):
    torneo = get_object_or_404(torneos_para_usuario(request), id=torneo_id)
    nombre = torneo.nombre
    if request.session.get("torneo_id") == torneo.id:
        request.session.pop("torneo_id", None)
    registrar_actividad(request, "ELIMINAR", torneo, descripcion=f"Elimino torneo {nombre}.")
    torneo.delete()
    messages.success(request, f"Torneo eliminado: {nombre}.")
    return redirect("gestion_torneos")


@login_required
@user_passes_test(es_editor_torneo)
def gestion_categorias(request):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.select_related("torneo").order_by("nombre")
    if torneo:
        categorias = categorias.filter(torneo=torneo)

    return render(request, "gestion/categorias.html", {
        "categorias": categorias,
        "torneo_seleccionado": torneo,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_categoria_nueva(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    form = CategoriaForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        categoria = form.save(commit=False)
        categoria.torneo = torneo
        categoria.save()
        registrar_actividad(request, "CREAR", categoria, descripcion=f"Creo categoria {categoria.nombre}.")
        messages.success(request, "Categoría creada correctamente.")
        return redirect("gestion_categorias")

    return render(request, "gestion/formulario.html", {
        "titulo": "Nueva categoría",
        "form": form,
        "volver_url": "gestion_categorias",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_categoria_editar(request, categoria_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    categorias = Categoria.objects.select_related("torneo")
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria = get_object_or_404(categorias, id=categoria_id)
    form = CategoriaForm(request.POST or None, instance=categoria)

    if request.method == "POST" and form.is_valid():
        categoria = form.save(commit=False)
        if torneo:
            categoria.torneo = torneo
        categoria.save()
        registrar_actividad(request, "EDITAR", categoria, descripcion=f"Actualizo categoria {categoria.nombre}.")
        messages.success(request, "Categoría actualizada correctamente.")
        return redirect("gestion_categorias")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar categoría: {categoria.nombre}",
        "form": form,
        "volver_url": "gestion_categorias",
    })


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def gestion_categoria_eliminar(request, categoria_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    categorias = Categoria.objects.select_related("torneo")
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria = get_object_or_404(categorias, id=categoria_id)
    nombre = categoria.nombre
    registrar_actividad(request, "ELIMINAR", categoria, descripcion=f"Elimino categoria {nombre}.")
    categoria.delete()
    messages.success(request, f"Categoria eliminada: {nombre}.")
    return redirect("gestion_categorias")


@login_required
@user_passes_test(es_editor_torneo)
def gestion_documentos(request):
    torneo = torneo_actual(request)
    documentos = Documento.objects.order_by("tipo", "-creado_en", "titulo")
    if torneo:
        documentos = documentos.filter(Q(torneo=torneo) | Q(torneo__isnull=True))
    tipo = request.GET.get("tipo", "").strip()

    if tipo:
        documentos = documentos.filter(tipo=tipo)

    return render(request, "gestion/documentos.html", {
        "documentos": documentos,
        "tipo": tipo,
        "tipos": Documento.TIPOS,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_documento_nuevo(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    form = DocumentoForm(request.POST or None, request.FILES or None, initial={"torneo": torneo}, torneo=torneo)

    if request.method == "POST" and form.is_valid():
        documento = form.save(commit=False)
        if not documento.torneo:
            documento.torneo = torneo
        documento.archivo = subir_documento_torneo(
            form.cleaned_data["archivo_subido"],
            documento.tipo,
        )
        documento.save()
        registrar_actividad(request, "CREAR", documento, descripcion=f"Creo documento {documento.titulo}.")
        messages.success(request, "Documento creado correctamente.")
        return redirect("gestion_documentos")

    return render(request, "gestion/formulario.html", {
        "titulo": "Nuevo documento",
        "form": form,
        "volver_url": "gestion_documentos",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_documento_editar(request, documento_id):
    torneo = torneo_actual(request)
    documentos = Documento.objects.all()
    if torneo:
        documentos = documentos.filter(Q(torneo=torneo) | Q(torneo__isnull=True))
    documento = get_object_or_404(documentos, id=documento_id)
    if not puede_gestionar_torneo(request, documento.torneo or torneo, "editar"):
        return denegar_permiso_torneo()
    form = DocumentoForm(request.POST or None, request.FILES or None, instance=documento, torneo=torneo)

    if request.method == "POST" and form.is_valid():
        documento = form.save(commit=False)
        archivo_subido = form.cleaned_data.get("archivo_subido")

        if archivo_subido:
            documento.archivo = subir_documento_torneo(archivo_subido, documento.tipo)

        documento.save()
        registrar_actividad(request, "EDITAR", documento, descripcion=f"Actualizo documento {documento.titulo}.")
        messages.success(request, "Documento actualizado correctamente.")
        return redirect("gestion_documentos")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar documento: {documento.titulo}",
        "form": form,
        "volver_url": "gestion_documentos",
    })


def generar_fixture_grupo(equipos):
    equipos = list(equipos)

    if len(equipos) % 2:
        equipos.append(None)

    total = len(equipos)
    rondas = total - 1
    mitad = total // 2
    calendario = []

    for numero_fecha in range(1, rondas + 1):
        partidos_fecha = []

        for i in range(mitad):
            local = equipos[i]
            visitante = equipos[total - 1 - i]

            if local and visitante:
                if numero_fecha % 2 == 0:
                    local, visitante = visitante, local

                partidos_fecha.append((local, visitante))

        calendario.append(partidos_fecha)
        equipos = [equipos[0]] + [equipos[-1]] + equipos[1:-1]

    return calendario


def distribuir_equipos_en_grupos(equipos, cabezas, cantidad_grupos):
    grupos = {chr(65 + i): [] for i in range(cantidad_grupos)}
    usados = set()

    for indice, cabeza in enumerate(cabezas):
        if cabeza and cabeza.id not in usados:
            grupos[chr(65 + indice)].append(cabeza)
            usados.add(cabeza.id)

    restantes = [equipo for equipo in equipos if equipo.id not in usados]

    for equipo in restantes:
        grupo_destino = min(grupos, key=lambda nombre: len(grupos[nombre]))
        grupos[grupo_destino].append(equipo)

    return grupos


def armar_grupos_desde_formulario(equipos, cabezas, request_post, cantidad_grupos):
    grupos = {chr(65 + i): [] for i in range(cantidad_grupos)}
    equipos_por_id = {str(equipo.id): equipo for equipo in equipos}
    usados = set()

    for indice, cabeza in enumerate(cabezas):
        if cabeza and cabeza.id not in usados:
            grupos[chr(65 + indice)].append(cabeza)
            usados.add(cabeza.id)

    for indice in range(cantidad_grupos):
        grupo_nombre = chr(65 + indice)

        for equipo_id in request_post.getlist(f"equipos_grupo_{indice}"):
            equipo = equipos_por_id.get(equipo_id)

            if equipo and equipo.id not in usados:
                grupos[grupo_nombre].append(equipo)
                usados.add(equipo.id)

    sin_asignar = [equipo for equipo in equipos if equipo.id not in usados]

    return grupos, sin_asignar


FRANJAS_PROGRAMACION_FIXTURE = [
    ("SAB_16", "Sabado 4:00 pm", 5, time(16, 0)),
    ("SAB_18", "Sabado 6:00 pm", 5, time(18, 0)),
    ("DOM_08", "Domingo 8:00 am", 6, time(8, 0)),
    ("DOM_10", "Domingo 10:00 am", 6, time(10, 0)),
    ("DOM_14", "Domingo 2:00 pm", 6, time(14, 0)),
    ("DOM_16", "Domingo 4:00 pm", 6, time(16, 0)),
]


def fecha_desde_texto(valor):
    try:
        return datetime.strptime((valor or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def canchas_desde_texto(valor):
    canchas = []
    for linea in (valor or "").splitlines():
        cancha = linea.strip()
        if cancha and cancha not in canchas:
            canchas.append(cancha)
    return canchas


def siguiente_dia_semana(fecha_base, dia_semana):
    diferencia = (dia_semana - fecha_base.weekday()) % 7
    return fecha_base + timedelta(days=diferencia)


def cupos_programacion_fixture(fecha_inicio, canchas, franjas, cantidad_partidos):
    if not fecha_inicio or not canchas or not franjas:
        return []

    cupos = []
    sabado_base = siguiente_dia_semana(fecha_inicio, 5)
    semanas = 0

    while len(cupos) < cantidad_partidos and semanas < 30:
        inicio_semana = sabado_base + timedelta(days=semanas * 7)
        for codigo, etiqueta, dia_semana, hora in franjas:
            fecha_cupo = siguiente_dia_semana(inicio_semana, dia_semana)
            for cancha in canchas:
                cupos.append({
                    "fecha": fecha_cupo,
                    "hora": hora,
                    "cancha": cancha,
                    "franja": codigo,
                    "etiqueta": etiqueta,
                })
        semanas += 1

    return cupos[:cantidad_partidos]


def elegir_cupo_balanceado(local, visitante, cupos, usados, conteos, equipos_ids, cancha_obligatoria):
    mejor_indice = None
    mejor_puntaje = None

    for indice, cupo in enumerate(cupos):
        if indice in usados:
            continue

        local_id = local.id
        visitante_id = visitante.id
        cancha = cupo["cancha"]
        franja = cupo["franja"]
        es_obligatoria = cancha_obligatoria and cancha.lower() == cancha_obligatoria.lower()

        conteo_cancha_local = conteos["cancha"].get(local_id, 0)
        conteo_cancha_visitante = conteos["cancha"].get(visitante_id, 0)
        conteo_franja_local = conteos["franjas"].setdefault(local_id, {}).get(franja, 0)
        conteo_franja_visitante = conteos["franjas"].setdefault(visitante_id, {}).get(franja, 0)
        conteo_fecha_local = conteos["fechas"].setdefault(local_id, {}).get(cupo["fecha"], 0)
        conteo_fecha_visitante = conteos["fechas"].setdefault(visitante_id, {}).get(cupo["fecha"], 0)

        puntaje = 0
        if es_obligatoria:
            puntaje += (conteo_cancha_local + conteo_cancha_visitante) * 40
        else:
            pendientes = sum(1 for equipo_id in equipos_ids if conteos["cancha"].get(equipo_id, 0) == 0)
            if pendientes:
                if conteo_cancha_local == 0:
                    puntaje += 12
                if conteo_cancha_visitante == 0:
                    puntaje += 12

        puntaje += (conteo_franja_local + conteo_franja_visitante) * 12
        puntaje += (conteo_fecha_local + conteo_fecha_visitante) * 25

        if mejor_puntaje is None or puntaje < mejor_puntaje:
            mejor_puntaje = puntaje
            mejor_indice = indice

    return mejor_indice


def resumen_equidad_programacion(conteos, equipos_por_id, franjas):
    resumen = []
    for equipo_id, equipo in sorted(equipos_por_id.items(), key=lambda item: item[1].nombre):
        resumen.append({
            "equipo": equipo,
            "cancha_obligatoria": conteos["cancha"].get(equipo_id, 0),
            "franjas": [
                (etiqueta, conteos["franjas"].setdefault(equipo_id, {}).get(codigo, 0))
                for codigo, etiqueta, _, _ in franjas
            ],
        })
    return resumen


@login_required
@user_passes_test(es_editor_torneo)
def gestion_generar_fixture(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "programar"):
        return denegar_permiso_torneo()
    categorias = Categoria.objects.order_by("nombre")
    if torneo:
        categorias = categorias.filter(torneo=torneo)
    categoria = None
    equipos = Equipo.objects.none()
    cantidad_grupos = 2
    grupos_generados = None
    resumen_programacion = None
    advertencias_programacion = []

    categoria_id = request.GET.get("categoria") or request.POST.get("categoria")

    if categoria_id:
        categoria = categorias.filter(id=categoria_id).first()

    if categoria:
        equipos = Equipo.objects.filter(categoria=categoria, activo=True).order_by("nombre")

    cantidad_grupos_valor = request.GET.get("grupos") or request.POST.get("grupos")

    if cantidad_grupos_valor:
        try:
            cantidad_grupos = max(1, min(8, int(cantidad_grupos_valor)))
        except ValueError:
            cantidad_grupos = 2

    letras_grupos = [chr(65 + i) for i in range(cantidad_grupos)]

    if request.method == "POST" and categoria:
        reemplazar = request.POST.get("reemplazar") == "on"
        generar_programacion = request.POST.get("generar_programacion") == "on"
        fecha_inicio_programacion = fecha_desde_texto(request.POST.get("fecha_inicio_programacion"))
        canchas_programacion = canchas_desde_texto(request.POST.get("canchas_programacion")) or ["Principal", "Porvenir"]
        cancha_obligatoria = (request.POST.get("cancha_obligatoria") or "Porvenir").strip()
        franjas_seleccionadas = request.POST.getlist("franjas_programacion")
        franjas_programacion = [
            franja for franja in FRANJAS_PROGRAMACION_FIXTURE
            if not franjas_seleccionadas or franja[0] in franjas_seleccionadas
        ]
        existentes = Partido.objects.filter(categoria=categoria, fase="GRUPOS").exists()

        if existentes and not reemplazar:
            messages.error(request, "Esta categoría ya tiene partidos de grupos. Marca reemplazar fixture para generarlo de nuevo.")
            return redirect(f"{request.path}?categoria={categoria.id}&grupos={cantidad_grupos}")

        cabezas = []

        for indice in range(cantidad_grupos):
            cabeza_id = request.POST.get(f"cabeza_{indice}")
            cabeza = equipos.filter(id=cabeza_id).first() if cabeza_id else None
            cabezas.append(cabeza)

        grupos_generados, sin_asignar = armar_grupos_desde_formulario(equipos, cabezas, request.POST, cantidad_grupos)

        if sin_asignar:
            nombres_sin_asignar = ", ".join(equipo.nombre for equipo in sin_asignar)
            messages.error(request, f"Faltan equipos por asignar a un grupo: {nombres_sin_asignar}.")
            return redirect(f"{request.path}?categoria={categoria.id}&grupos={cantidad_grupos}")

        grupos_vacios = [nombre for nombre, equipos_grupo in grupos_generados.items() if len(equipos_grupo) < 2]

        if grupos_vacios:
            messages.error(request, f"Cada grupo debe tener al menos 2 equipos. Revisa: {', '.join(grupos_vacios)}.")
            return redirect(f"{request.path}?categoria={categoria.id}&grupos={cantidad_grupos}")

        if reemplazar:
            Partido.objects.filter(categoria=categoria, fase="GRUPOS").delete()

        creados = 0
        partidos_a_crear = []

        for grupo_nombre, equipos_grupo in grupos_generados.items():
            calendario = generar_fixture_grupo(equipos_grupo)

            for indice_fecha, partidos_fecha in enumerate(calendario, start=1):
                for local, visitante in partidos_fecha:
                    partidos_a_crear.append((grupo_nombre, indice_fecha, local, visitante))

        cupos = []
        conteos = {"cancha": {}, "franjas": {}, "fechas": {}}
        usados = set()
        equipos_por_id = {equipo.id: equipo for equipo in equipos}
        if generar_programacion:
            if not fecha_inicio_programacion:
                messages.error(request, "Para generar programacion automatica debes indicar la fecha de inicio.")
                return redirect(f"{request.path}?categoria={categoria.id}&grupos={cantidad_grupos}")

            cupos = cupos_programacion_fixture(
                fecha_inicio_programacion,
                canchas_programacion,
                franjas_programacion,
                len(partidos_a_crear),
            )

            if len(cupos) < len(partidos_a_crear):
                advertencias_programacion.append(
                    "No hay suficientes cupos configurados; algunos partidos quedaran sin fecha/hora/cancha balanceada."
                )

        for grupo_nombre, indice_fecha, local, visitante in partidos_a_crear:
            defaults = {
                "fecha": date.today(),
                "hora": time(0, 0),
                "estado": "PROGRAMADO",
                "cancha": "",
                "estado_programacion": "MANUAL",
            }

            if generar_programacion and cupos:
                indice_cupo = elegir_cupo_balanceado(
                    local,
                    visitante,
                    cupos,
                    usados,
                    conteos,
                    equipos_por_id.keys(),
                    cancha_obligatoria,
                )

                if indice_cupo is not None:
                    usados.add(indice_cupo)
                    cupo = cupos[indice_cupo]
                    defaults.update({
                        "fecha": cupo["fecha"],
                        "hora": cupo["hora"],
                        "cancha": cupo["cancha"],
                        "estado_programacion": "SUGERIDA",
                    })

                    for equipo_id in [local.id, visitante.id]:
                        conteos["franjas"].setdefault(equipo_id, {})
                        conteos["fechas"].setdefault(equipo_id, {})
                        conteos["franjas"][equipo_id][cupo["franja"]] = conteos["franjas"][equipo_id].get(cupo["franja"], 0) + 1
                        conteos["fechas"][equipo_id][cupo["fecha"]] = conteos["fechas"][equipo_id].get(cupo["fecha"], 0) + 1
                        if cancha_obligatoria and cupo["cancha"].lower() == cancha_obligatoria.lower():
                            conteos["cancha"][equipo_id] = conteos["cancha"].get(equipo_id, 0) + 1

            _, creado = Partido.objects.get_or_create(
                categoria=categoria,
                fase="GRUPOS",
                grupo=grupo_nombre,
                numero_fecha=str(indice_fecha),
                equipo_local=local,
                equipo_visitante=visitante,
                defaults=defaults,
            )

            if creado:
                creados += 1

        if generar_programacion:
            resumen_programacion = resumen_equidad_programacion(conteos, equipos_por_id, franjas_programacion)
            sin_cancha_obligatoria = [
                item["equipo"].nombre
                for item in resumen_programacion
                if item["cancha_obligatoria"] == 0
            ]
            if sin_cancha_obligatoria:
                advertencias_programacion.append(
                    f"Equipos pendientes por jugar en {cancha_obligatoria}: {', '.join(sin_cancha_obligatoria)}."
                )

            if advertencias_programacion:
                for advertencia in advertencias_programacion:
                    messages.warning(request, advertencia)
            else:
                messages.success(request, "Programacion automatica balanceada sin alertas de equidad.")

        messages.success(request, f"Fixture generado para {categoria.nombre}. Partidos creados: {creados}.")
        registrar_actividad(
            request,
            "GENERAR_FIXTURE",
            categoria,
            descripcion=f"Genero fixture para {categoria.nombre}. Partidos creados: {creados}.",
            datos={
                "partidos_creados": creados,
                "grupos": cantidad_grupos,
                "programacion_automatica": generar_programacion,
                "cancha_obligatoria": cancha_obligatoria if generar_programacion else "",
            },
        )

    return render(request, "gestion/generar_fixture.html", {
        "categorias": categorias,
        "categoria": categoria,
        "equipos": equipos,
        "cantidad_grupos": cantidad_grupos,
        "letras_grupos": letras_grupos,
        "grupos_generados": grupos_generados,
        "franjas_programacion": FRANJAS_PROGRAMACION_FIXTURE,
        "resumen_programacion": resumen_programacion,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_equipos(request):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.order_by("nombre")
    equipos = Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre")
    if torneo:
        categorias = categorias.filter(torneo=torneo)
        equipos = equipos.filter(categoria__torneo=torneo)
    q = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "").strip()

    if q:
        equipos = equipos.filter(nombre__icontains=q)

    if categoria_id:
        equipos = equipos.filter(categoria_id=categoria_id)

    return render(request, "gestion/equipos.html", {
        "equipos": equipos,
        "categorias": categorias,
        "q": q,
        "categoria_id": categoria_id,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_equipo_nuevo(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    form = EquipoForm(request.POST or None, request.FILES or None, torneo=torneo)

    if request.method == "POST" and form.is_valid():
        equipo = form.save(commit=False)
        aplicar_imagen_cloudinary(
            equipo,
            "escudo",
            request.POST.get("imagen_cloudinary"),
            request.FILES.get("escudo"),
        )
        equipo.save()
        form.save_m2m()
        registrar_actividad(request, "CREAR", equipo, descripcion=f"Creo equipo {equipo.nombre}.")
        messages.success(request, "Equipo creado correctamente.")
        return redirect("gestion_equipo_editar", equipo_id=equipo.id)

    return render(request, "gestion/formulario.html", {
        "titulo": "Nuevo equipo",
        "form": form,
        "volver_url": "gestion_equipos",
        "cloudinary_images": listar_imagenes_cloudinary(),
        "cloudinary_label": "Seleccionar escudo existente de Cloudinary",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_equipo_editar(request, equipo_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    equipos = Equipo.objects.select_related("categoria")
    if torneo:
        equipos = equipos.filter(categoria__torneo=torneo)
    equipo = get_object_or_404(equipos, id=equipo_id)
    form = EquipoForm(request.POST or None, request.FILES or None, instance=equipo, torneo=torneo)
    jugadores = equipo.jugadores.order_by("dorsal", "nombres")

    if request.method == "POST" and form.is_valid():
        equipo = form.save(commit=False)
        aplicar_imagen_cloudinary(
            equipo,
            "escudo",
            request.POST.get("imagen_cloudinary"),
            request.FILES.get("escudo"),
        )
        equipo.save()
        form.save_m2m()
        registrar_actividad(request, "EDITAR", equipo, descripcion=f"Actualizo equipo {equipo.nombre}.")
        messages.success(request, "Equipo actualizado correctamente.")
        return redirect("gestion_equipo_editar", equipo_id=equipo.id)

    return render(request, "gestion/equipo_formulario.html", {
        "titulo": f"Editar equipo: {equipo.nombre}",
        "form": form,
        "equipo": equipo,
        "jugadores": jugadores,
        "estados_jugador": Jugador.ESTADOS,
        "volver_url": "gestion_equipos",
        "cloudinary_images": listar_imagenes_cloudinary(),
        "cloudinary_label": "Seleccionar escudo existente de Cloudinary",
    })


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def gestion_equipo_jugadores_guardar(request, equipo_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    equipos = Equipo.objects.select_related("categoria")
    if torneo:
        equipos = equipos.filter(categoria__torneo=torneo)
    equipo = get_object_or_404(equipos, id=equipo_id)

    jugadores = list(equipo.jugadores.all())
    errores = []
    actualizados = 0

    for jugador in jugadores:
        prefijo = f"jugador_{jugador.id}_"
        nombres = (request.POST.get(prefijo + "nombres") or "").strip()
        cedula = (request.POST.get(prefijo + "cedula") or "").strip()
        fecha_nacimiento = (request.POST.get(prefijo + "fecha_nacimiento") or "").strip()
        estado = request.POST.get(prefijo + "estado") or "ACTIVO"

        if not nombres or not cedula or not fecha_nacimiento:
            errores.append(f"{jugador.nombres}: nombre, cedula y fecha son obligatorios.")
            continue

        jugador.dorsal = request.POST.get(prefijo + "dorsal") or None
        jugador.nombres = nombres.upper()
        jugador.cedula = cedula
        jugador.fecha_nacimiento = fecha_nacimiento
        jugador.estado = estado
        jugador.es_foraneo = request.POST.get(prefijo + "es_foraneo") == "on"

        try:
            jugador.save()
            actualizados += 1
        except Exception as exc:
            errores.append(f"{nombres}: {exc}")

    nuevo_nombre = (request.POST.get("nuevo_nombres") or "").strip()
    nuevo_cedula = (request.POST.get("nuevo_cedula") or "").strip()
    nuevo_fecha = (request.POST.get("nuevo_fecha_nacimiento") or "").strip()
    if nuevo_nombre or nuevo_cedula or nuevo_fecha:
        if not nuevo_nombre or not nuevo_cedula or not nuevo_fecha:
            errores.append("Para agregar jugador nuevo debes llenar nombre, cedula y fecha de nacimiento.")
        else:
            nuevo = Jugador(
                equipo=equipo,
                dorsal=request.POST.get("nuevo_dorsal") or None,
                nombres=nuevo_nombre.upper(),
                cedula=nuevo_cedula,
                fecha_nacimiento=nuevo_fecha,
                estado=request.POST.get("nuevo_estado") or "ACTIVO",
                es_foraneo=request.POST.get("nuevo_es_foraneo") == "on",
            )
            try:
                nuevo.save()
                registrar_actividad(request, "CREAR", nuevo, descripcion=f"Agrego jugador {nuevo.nombres} al equipo {equipo.nombre}.")
                messages.success(request, f"Jugador agregado: {nuevo.nombres}.")
            except Exception as exc:
                errores.append(f"No se pudo agregar {nuevo_nombre}: {exc}")

    if actualizados:
        registrar_actividad(
            request,
            "EDITAR_PLANTILLA",
            equipo,
            descripcion=f"Actualizo plantilla de {equipo.nombre}. Jugadores actualizados: {actualizados}.",
            datos={"actualizados": actualizados},
        )
        messages.success(request, f"Plantilla actualizada: {actualizados} jugador(es).")
    for error in errores[:8]:
        messages.error(request, error)
    if len(errores) > 8:
        messages.error(request, f"Hay {len(errores) - 8} errores adicionales.")

    return redirect("gestion_equipo_editar", equipo_id=equipo.id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def gestion_equipo_eliminar(request, equipo_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    equipos = Equipo.objects.select_related("categoria")
    if torneo:
        equipos = equipos.filter(categoria__torneo=torneo)
    equipo = get_object_or_404(equipos, id=equipo_id)
    nombre = equipo.nombre
    registrar_actividad(request, "ELIMINAR", equipo, descripcion=f"Elimino equipo {nombre}.")
    equipo.delete()
    messages.success(request, f"Equipo eliminado: {nombre}.")
    return redirect("gestion_equipos")


@login_required
@user_passes_test(es_editor_torneo)
def gestion_jugadores(request):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.order_by("nombre")
    equipos = Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre")
    jugadores = Jugador.objects.select_related("equipo", "equipo__categoria").order_by(
        "equipo__categoria__nombre",
        "equipo__nombre",
        "dorsal",
        "nombres",
    )
    if torneo:
        categorias = categorias.filter(torneo=torneo)
        equipos = equipos.filter(categoria__torneo=torneo)
        jugadores = jugadores.filter(equipo__categoria__torneo=torneo)
    q = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "").strip()
    equipo_id = request.GET.get("equipo", "").strip()

    if q:
        jugadores = jugadores.filter(Q(nombres__icontains=q) | Q(cedula__icontains=q))

    if categoria_id:
        jugadores = jugadores.filter(equipo__categoria_id=categoria_id)

    if equipo_id:
        jugadores = jugadores.filter(equipo_id=equipo_id)

    return render(request, "gestion/jugadores.html", {
        "jugadores": jugadores,
        "categorias": categorias,
        "equipos": equipos,
        "q": q,
        "categoria_id": categoria_id,
        "equipo_id": equipo_id,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_jugador_nuevo(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    form = JugadorForm(request.POST or None, request.FILES or None, torneo=torneo)

    if request.method == "POST" and form.is_valid():
        jugador = form.save(commit=False)
        aplicar_imagen_cloudinary(
            jugador,
            "foto",
            request.POST.get("imagen_cloudinary"),
            request.FILES.get("foto"),
        )
        jugador.save()
        form.save_m2m()
        registrar_actividad(request, "CREAR", jugador, descripcion=f"Creo jugador {jugador.nombres}.")
        messages.success(request, "Jugador creado correctamente.")
        return redirect("gestion_jugador_editar", jugador_id=jugador.id)

    return render(request, "gestion/formulario.html", {
        "titulo": "Nuevo jugador",
        "form": form,
        "volver_url": "gestion_jugadores",
        "cloudinary_images": listar_imagenes_cloudinary(),
        "cloudinary_label": "Seleccionar foto existente de Cloudinary",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_jugador_editar(request, jugador_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    jugadores = Jugador.objects.select_related("equipo", "equipo__categoria")
    if torneo:
        jugadores = jugadores.filter(equipo__categoria__torneo=torneo)
    jugador = get_object_or_404(jugadores, id=jugador_id)
    form = JugadorForm(request.POST or None, request.FILES or None, instance=jugador, torneo=torneo)

    if request.method == "POST" and form.is_valid():
        jugador = form.save(commit=False)
        aplicar_imagen_cloudinary(
            jugador,
            "foto",
            request.POST.get("imagen_cloudinary"),
            request.FILES.get("foto"),
        )
        jugador.save()
        form.save_m2m()
        registrar_actividad(request, "EDITAR", jugador, descripcion=f"Actualizo jugador {jugador.nombres}.")
        messages.success(request, "Jugador actualizado correctamente.")
        return redirect("gestion_jugadores")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar jugador: {jugador.nombres}",
        "form": form,
        "volver_url": "gestion_jugadores",
        "cloudinary_images": listar_imagenes_cloudinary(),
        "cloudinary_label": "Seleccionar foto existente de Cloudinary",
    })


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def gestion_jugador_eliminar(request, jugador_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()
    jugadores = Jugador.objects.select_related("equipo", "equipo__categoria")
    if torneo:
        jugadores = jugadores.filter(equipo__categoria__torneo=torneo)
    jugador = get_object_or_404(jugadores, id=jugador_id)
    nombre = jugador.nombres
    registrar_actividad(request, "ELIMINAR", jugador, descripcion=f"Elimino jugador {nombre}.")
    jugador.delete()
    messages.success(request, f"Jugador eliminado: {nombre}.")
    return redirect("gestion_jugadores")


@login_required
@user_passes_test(es_editor_torneo)
def gestion_importar_planilla(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "editar"):
        return denegar_permiso_torneo()

    if request.method == "POST":
        archivo = request.FILES.get("archivo_excel")

        if not archivo:
            messages.error(request, "Selecciona un archivo Excel.")
            return redirect("gestion_importar_planilla")

        try:
            workbook = load_workbook(archivo, data_only=True)
            hoja = obtener_hoja_planilla_excel(workbook)

            categoria_nombre = limpiar_texto_excel(hoja["D3"].value)
            equipo_nombre = limpiar_texto_excel(hoja["I3"].value)
            delegado = limpiar_texto_excel(hoja["D4"].value)
            telefono_delegado = limpiar_cedula_excel(hoja["I4"].value)
            director_tecnico = limpiar_texto_excel(hoja["C39"].value)
            telefono_dt = limpiar_cedula_excel(hoja["G39"].value)
            asistente_tecnico = limpiar_texto_excel(hoja["C40"].value)
            telefono_at = limpiar_cedula_excel(hoja["G40"].value)

            if not categoria_nombre:
                messages.error(request, "No se encontró la categoría en la celda D3.")
                return redirect("gestion_importar_planilla")

            if not equipo_nombre:
                messages.error(request, "No se encontró el equipo en la celda I3.")
                return redirect("gestion_importar_planilla")

            categorias = Categoria.objects.filter(nombre__iexact=categoria_nombre)
            if torneo:
                categorias = categorias.filter(torneo=torneo)
            categoria = categorias.first()

            if not categoria:
                messages.error(request, f"No existe la categoría: {categoria_nombre}. Créala primero.")
                return redirect("gestion_importar_planilla")

            equipo, _ = Equipo.objects.get_or_create(
                nombre=equipo_nombre.upper(),
                categoria=categoria,
                defaults={"activo": True},
            )

            equipo.delegado = delegado.upper() if delegado else equipo.delegado
            equipo.telefono = telefono_delegado or equipo.telefono
            equipo.director_tecnico = director_tecnico.upper() if director_tecnico else equipo.director_tecnico
            equipo.telefono_dt = telefono_dt or equipo.telefono_dt
            equipo.asistente_tecnico = asistente_tecnico.upper() if asistente_tecnico else equipo.asistente_tecnico
            equipo.telefono_at = telefono_at or equipo.telefono_at
            equipo.activo = True
            equipo.save()

            creados = 0
            actualizados = 0
            omitidos = 0
            errores = []

            for fila in range(8, 38):
                nombre = limpiar_texto_excel(hoja[f"C{fila}"].value)
                dorsal = limpiar_entero_excel(hoja[f"D{fila}"].value)
                dia = hoja[f"E{fila}"].value
                mes = hoja[f"F{fila}"].value
                anio = hoja[f"G{fila}"].value
                cedula = limpiar_cedula_excel(hoja[f"H{fila}"].value)

                if not nombre and not cedula:
                    continue

                if not nombre:
                    omitidos += 1
                    errores.append(f"Fila {fila}: falta el nombre del jugador.")
                    continue

                if not cedula:
                    omitidos += 1
                    errores.append(f"Fila {fila}: falta la cédula de {nombre}.")
                    continue

                fecha_nacimiento = construir_fecha_excel(dia, mes, anio)

                if not fecha_nacimiento:
                    omitidos += 1
                    errores.append(f"Fila {fila}: fecha de nacimiento inválida para {nombre}.")
                    continue

                jugador_misma_categoria = Jugador.objects.filter(
                    cedula=cedula,
                    equipo__categoria=categoria,
                ).exclude(equipo=equipo).select_related("equipo").first()
                if jugador_misma_categoria:
                    omitidos += 1
                    errores.append(
                        f"Fila {fila}: {nombre} ya esta inscrito en {jugador_misma_categoria.equipo.nombre} "
                        f"para {categoria.nombre}."
                    )
                    continue

                _, creado = Jugador.objects.update_or_create(
                    equipo=equipo,
                    cedula=cedula,
                    defaults={
                        "dorsal": dorsal,
                        "nombres": nombre.upper(),
                        "fecha_nacimiento": fecha_nacimiento,
                        "estado": "ACTIVO",
                    },
                )

                if creado:
                    creados += 1
                else:
                    actualizados += 1

            messages.success(
                request,
                f"Planilla importada: {equipo.nombre} / {categoria.nombre}. Nuevos: {creados}. Actualizados: {actualizados}. Omitidos: {omitidos}.",
            )
            registrar_actividad(
                request,
                "IMPORTAR_PLANILLA",
                equipo,
                descripcion=f"Importo planilla de {equipo.nombre}. Nuevos: {creados}. Actualizados: {actualizados}. Omitidos: {omitidos}.",
                datos={"creados": creados, "actualizados": actualizados, "omitidos": omitidos},
            )

            for error in errores[:12]:
                messages.warning(request, error)

            if len(errores) > 12:
                messages.warning(request, f"Hay {len(errores) - 12} advertencias adicionales.")

            return redirect("gestion_jugadores")

        except Exception as exc:
            messages.error(request, f"No se pudo importar la planilla: {exc}")
            return redirect("gestion_importar_planilla")

    return render(request, "gestion/importar_planilla.html")


@login_required
@user_passes_test(es_editor_torneo)
def gestion_partidos(request):
    torneo = torneo_actual(request)
    categorias = Categoria.objects.order_by("nombre")
    if torneo:
        categorias = categorias.filter(torneo=torneo)

    partidos = Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante").order_by(
        "fecha",
        "hora",
        "categoria__nombre",
        "grupo",
        "fase",
    )
    if torneo:
        partidos = partidos.filter(categoria__torneo=torneo)

    q = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "").strip()
    estado = request.GET.get("estado", "").strip()

    if q:
        partidos = partidos.filter(
            Q(equipo_local__nombre__icontains=q) |
            Q(equipo_visitante__nombre__icontains=q) |
            Q(cancha__icontains=q)
        )

    if categoria_id:
        partidos = partidos.filter(categoria_id=categoria_id)

    if estado:
        partidos = partidos.filter(estado=estado)

    return render(request, "gestion/partidos.html", {
        "partidos": partidos,
        "categorias": categorias,
        "estados": Partido.ESTADOS,
        "q": q,
        "categoria_id": categoria_id,
        "estado": estado,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_partido_nuevo(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "programar"):
        return denegar_permiso_torneo()
    form = PartidoForm(request.POST or None, torneo=torneo)

    if request.method == "POST" and form.is_valid():
        partido = form.save()
        from django.utils import timezone

        if partido.estado == "EN_JUEGO" and not partido.inicio_en_vivo:
            partido.inicio_en_vivo = timezone.now()
            partido.save()
        registrar_actividad(request, "CREAR", partido, descripcion=f"Creo partido {partido.equipo_local} vs {partido.equipo_visitante}.")
        messages.success(request, "Partido creado correctamente.")
        return redirect("gestion_partido_editar", partido_id=partido.id)
        
    return render(request, "gestion/formulario.html", {
        "titulo": "Nuevo partido",
        "form": form,
        "volver_url": "gestion_partidos",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_partido_editar(request, partido_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "programar"):
        return denegar_permiso_torneo()
    partidos = Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante")
    if torneo:
        partidos = partidos.filter(categoria__torneo=torneo)
    partido = get_object_or_404(partidos, id=partido_id)
    form = PartidoForm(request.POST or None, instance=partido, torneo=torneo)

    if request.method == "POST" and form.is_valid():
        partido = form.save()
        if partido.estado_programacion == "SUGERIDA":
            partido.estado_programacion = "OFICIAL"
            partido.save(update_fields=["estado_programacion"])
        if partido.estadisticas_validadas and not partido.estadisticas_validadas_en:
            _validar_estadisticas_partido(partido, request.user)
        registrar_actividad(request, "EDITAR", partido, descripcion=f"Actualizo partido {partido.equipo_local} vs {partido.equipo_visitante}.")
        messages.success(request, "Partido actualizado correctamente.")
        return redirect("gestion_partidos")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar partido: {partido.equipo_local} vs {partido.equipo_visitante}",
        "form": form,
        "volver_url": "gestion_partidos",
    })


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def gestion_partido_confirmar_programacion(request, partido_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "programar"):
        return denegar_permiso_torneo()
    partidos = Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante")
    if torneo:
        partidos = partidos.filter(categoria__torneo=torneo)
    partido = get_object_or_404(partidos, id=partido_id)
    partido.estado_programacion = "OFICIAL"
    partido.save(update_fields=["estado_programacion"])
    registrar_actividad(
        request,
        "CONFIRMAR_PROGRAMACION",
        partido,
        descripcion=f"Confirmo programacion de {partido.equipo_local} vs {partido.equipo_visitante}.",
    )
    messages.success(request, f"Programacion oficial: {partido.equipo_local} vs {partido.equipo_visitante}.")
    return redirect(request.POST.get("next") or "gestion_partidos")


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def gestion_partido_validar_estadisticas(request, partido_id):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "validar"):
        return denegar_permiso_torneo()
    partidos = Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante")
    if torneo:
        partidos = partidos.filter(categoria__torneo=torneo)
    partido = get_object_or_404(partidos, id=partido_id)
    _validar_estadisticas_partido(partido, request.user)
    registrar_actividad(request, "VALIDAR_ESTADISTICAS", partido, descripcion=f"Valido estadisticas de {partido.equipo_local} vs {partido.equipo_visitante}.")
    messages.success(request, f"Estadisticas validadas: {partido.equipo_local} vs {partido.equipo_visitante}.")
    return redirect(request.POST.get("next") or "gestion_partidos")


@login_required
@user_passes_test(es_editor_torneo)
def gestion_importar_partidos(request):
    torneo = torneo_actual(request)
    if not puede_gestionar_torneo(request, torneo, "programar"):
        return denegar_permiso_torneo()

    if request.method == "POST":
        archivo = request.FILES.get("archivo_excel")

        if not archivo:
            messages.error(request, "Selecciona un archivo Excel.")
            return redirect("gestion_importar_partidos")

        try:
            workbook = load_workbook(archivo, data_only=True)
            hoja = workbook.active
            encabezados = {}

            for indice, celda in enumerate(hoja[1]):
                if celda.value:
                    encabezados[normalizar_encabezado_excel(celda.value)] = indice

            creados = 0
            actualizados = 0
            omitidos = 0
            errores = []

            for numero_fila, row in enumerate(hoja.iter_rows(min_row=2), start=2):
                categoria_nombre = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "categoria", "categoría"))
                local_nombre = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "equipo_local", "local", "equipo local"))
                visitante_nombre = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "equipo_visitante", "visitante", "equipo visitante"))

                if not categoria_nombre and not local_nombre and not visitante_nombre:
                    continue

                if not categoria_nombre or not local_nombre or not visitante_nombre:
                    omitidos += 1
                    errores.append(f"Fila {numero_fila}: falta categoría, local o visitante.")
                    continue

                categorias = Categoria.objects.filter(nombre__iexact=categoria_nombre)
                if torneo:
                    categorias = categorias.filter(torneo=torneo)
                categoria = categorias.first()

                if not categoria:
                    omitidos += 1
                    errores.append(f"Fila {numero_fila}: no existe la categoría {categoria_nombre}.")
                    continue

                local = Equipo.objects.filter(nombre__iexact=local_nombre, categoria=categoria).first()
                visitante = Equipo.objects.filter(nombre__iexact=visitante_nombre, categoria=categoria).first()

                if not local:
                    omitidos += 1
                    errores.append(f"Fila {numero_fila}: no existe el equipo local {local_nombre} en {categoria.nombre}.")
                    continue

                if not visitante:
                    omitidos += 1
                    errores.append(f"Fila {numero_fila}: no existe el equipo visitante {visitante_nombre} en {categoria.nombre}.")
                    continue

                numero_fecha = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "numero_fecha", "fecha fixture", "jornada")) or "1"
                grupo = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "grupo")) or "SIN GRUPO"
                fase = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "fase")) or "GRUPOS"
                cancha = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "cancha"))
                estado = limpiar_texto_excel(valor_por_encabezado(row, encabezados, "estado")) or "PROGRAMADO"
                fecha_partido = construir_fecha_partido_excel(valor_por_encabezado(row, encabezados, "fecha", "fecha_partido", "dia", "día", "fecha calendario"))
                hora_partido = construir_hora_partido_excel(valor_por_encabezado(row, encabezados, "hora"))
                goles_local = limpiar_entero_excel(valor_por_encabezado(row, encabezados, "goles_local", "gl")) or 0
                goles_visitante = limpiar_entero_excel(valor_por_encabezado(row, encabezados, "goles_visitante", "gv")) or 0

                if fase not in dict(Partido.FASES):
                    fase = fase.upper().replace(" ", "_")

                if fase not in dict(Partido.FASES):
                    fase = "GRUPOS"

                if estado not in dict(Partido.ESTADOS):
                    estado = estado.upper().replace(" ", "_")

                if estado not in dict(Partido.ESTADOS):
                    estado = "PROGRAMADO"

                partido, creado = Partido.objects.update_or_create(
                    categoria=categoria,
                    fase=fase,
                    numero_fecha=numero_fecha,
                    equipo_local=local,
                    equipo_visitante=visitante,
                    defaults={
                        "fecha": fecha_partido or date.today(),
                        "hora": hora_partido or time(0, 0),
                        "estado": estado,
                        "estado_programacion": "MANUAL",
                        "grupo": grupo,
                        "cancha": cancha,
                        "goles_local": goles_local,
                        "goles_visitante": goles_visitante,
                    },
                )

                if creado:
                    creados += 1
                else:
                    actualizados += 1

            messages.success(
                request,
                f"Partidos importados. Nuevos: {creados}. Actualizados: {actualizados}. Omitidos: {omitidos}.",
            )
            registrar_actividad(
                request,
                "IMPORTAR_PARTIDOS",
                torneo=torneo,
                descripcion=f"Importo partidos. Nuevos: {creados}. Actualizados: {actualizados}. Omitidos: {omitidos}.",
                datos={"creados": creados, "actualizados": actualizados, "omitidos": omitidos},
            )

            for error in errores[:12]:
                messages.warning(request, error)

            if len(errores) > 12:
                messages.warning(request, f"Hay {len(errores) - 12} advertencias adicionales.")

            return redirect("gestion_partidos")

        except Exception as exc:
            messages.error(request, f"No se pudo importar el archivo: {exc}")
            return redirect("gestion_importar_partidos")

    return render(request, "gestion/importar_partidos.html")
def partido_live(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related(
            "categoria",
            "categoria__torneo",
            "equipo_local",
            "equipo_visitante"
        ),
        id=partido_id
    )
    volver_url = request.GET.get("volver", "").strip()
    if volver_url and not url_has_allowed_host_and_scheme(
        volver_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        volver_url = ""
    if not volver_url:
        volver_url = f"{reverse('panel')}?torneo={partido.categoria.torneo_id}"

    goles = Gol.objects.filter(partido=partido).select_related("jugador", "equipo").order_by("minuto", "creado_en", "id")
    tarjetas = Tarjeta.objects.filter(partido=partido).select_related("jugador", "equipo").order_by("minuto", "creado_en", "id")
    alineaciones = AlineacionPartido.objects.filter(partido=partido).select_related("jugador", "equipo").order_by("equipo__nombre", "rol", "jugador__nombres")
    sustituciones = SustitucionPartido.objects.filter(partido=partido).select_related("equipo", "jugador_sale", "jugador_entra").order_by("minuto", "creado_en", "id")
    sustituciones_local = [cambio for cambio in sustituciones if cambio.equipo_id == partido.equipo_local_id]
    sustituciones_visitante = [cambio for cambio in sustituciones if cambio.equipo_id == partido.equipo_visitante_id]
    for cambio in sustituciones:
        cambio.jugador_entra_corto = nombre_corto_jugador(cambio.jugador_entra)
        cambio.jugador_sale_corto = nombre_corto_jugador(cambio.jugador_sale)
        cambio.jugador_entra_edad = etiqueta_edad_jugador(cambio.jugador_entra, partido.categoria, partido.fecha)
        cambio.jugador_sale_edad = etiqueta_edad_jugador(cambio.jugador_sale, partido.categoria, partido.fecha)

    eventos_por_jugador = defaultdict(dict)

    def agregar_evento_jugador(jugador_id, tipo, titulo, cantidad=1):
        if not jugador_id:
            return
        eventos = eventos_por_jugador[jugador_id]
        if tipo in eventos:
            eventos[tipo].cantidad += cantidad
        else:
            eventos[tipo] = SimpleNamespace(
                tipo=tipo,
                titulo=titulo,
                cantidad=cantidad,
            )

    for gol in goles:
        if not gol.jugador_id:
            continue
        cantidad = max(gol.cantidad or 1, 1)
        es_autogol = bool(
            getattr(gol, "autogol", False)
            or getattr(gol, "es_autogol", False)
            or getattr(gol, "tipo", "") == "AUTOGOL"
        )
        es_penal = bool(getattr(gol, "es_penal", False))
        if es_autogol:
            tipo_gol = "autogol"
            titulo_gol = "Autogol"
        elif es_penal:
            tipo_gol = "penal"
            titulo_gol = "Gol de penal"
        else:
            tipo_gol = "gol"
            titulo_gol = "Gol"
        agregar_evento_jugador(gol.jugador_id, tipo_gol, titulo_gol, cantidad)

    for tarjeta in tarjetas:
        if not tarjeta.jugador_id:
            continue
        agregar_evento_jugador(
            tarjeta.jugador_id,
            "roja" if tarjeta.tipo == "ROJA" else "amarilla",
            tarjeta.get_tipo_display(),
        )

    for sustitucion in sustituciones:
        agregar_evento_jugador(sustitucion.jugador_sale_id, "sale", "Sustituido")
        agregar_evento_jugador(sustitucion.jugador_entra_id, "entra", "Ingreso")

    orden_ingreso_suplente = {}
    for indice, sustitucion in enumerate(sustituciones, start=1):
        orden_ingreso_suplente.setdefault(sustitucion.jugador_entra_id, indice)

    alineaciones_local = []
    alineaciones_visitante = []
    suplentes_local = []
    suplentes_visitante = []
    no_disponibles_local = []
    no_disponibles_visitante = []
    for alineacion in alineaciones:
        jugador = alineacion.jugador
        item = SimpleNamespace(
            jugador=jugador,
            nombre=jugador.nombres,
            nombre_corto=nombre_corto_jugador(jugador),
            dorsal=jugador.dorsal,
            rol=alineacion.rol,
            posicion=alineacion.posicion_cancha,
            foto=foto_jugador_url(jugador),
            iniciales=iniciales_jugador(jugador),
            etiqueta_edad=etiqueta_edad_jugador(jugador, partido.categoria, partido.fecha),
            eventos=list(eventos_por_jugador.get(jugador.id, {}).values()),
            orden_ingreso=orden_ingreso_suplente.get(jugador.id, 9999),
        )
        if alineacion.equipo_id == partido.equipo_local_id:
            if alineacion.rol == "SUPLENTE":
                suplentes_local.append(item)
            elif alineacion.rol == "NO_DISPONIBLE":
                no_disponibles_local.append(item)
            else:
                alineaciones_local.append(item)
        elif alineacion.equipo_id == partido.equipo_visitante_id:
            if alineacion.rol == "SUPLENTE":
                suplentes_visitante.append(item)
            elif alineacion.rol == "NO_DISPONIBLE":
                no_disponibles_visitante.append(item)
            else:
                alineaciones_visitante.append(item)

    alineaciones_local = _ordenar_titulares_cancha(alineaciones_local)
    alineaciones_visitante = _ordenar_titulares_cancha(alineaciones_visitante)
    suplentes_local = sorted(suplentes_local, key=lambda item: (item.orden_ingreso, item.nombre_corto))
    suplentes_visitante = sorted(suplentes_visitante, key=lambda item: (item.orden_ingreso, item.nombre_corto))

    eventos_live = []
    orden = 0
    for gol in goles:
        orden += 1
        if gol.es_autogol:
            tipo_evento = "autogol"
            detalle_gol = "Autogol"
        elif gol.es_penal:
            tipo_evento = "gol"
            detalle_gol = "Gol de penal"
        else:
            tipo_evento = "gol"
            detalle_gol = f"{gol.cantidad} gol(es)" if gol.cantidad > 1 else "Gol"
        eventos_live.append(SimpleNamespace(
            tipo=tipo_evento,
            icono="\u26bd",
            minuto=gol.minuto,
            equipo_id=gol.equipo_id,
            texto=nombre_resumen_jugador(gol.jugador),
            detalle=detalle_gol,
            creado_en=gol.creado_en,
            orden=gol.id,
        ))

    for tarjeta in tarjetas:
        orden += 1
        eventos_live.append(SimpleNamespace(
            tipo="tarjeta",
            icono="🟥" if tarjeta.tipo == "ROJA" else "🟨",
            minuto=tarjeta.minuto,
            equipo_id=tarjeta.equipo_id,
            texto=nombre_resumen_jugador(tarjeta.jugador),
            detalle=tarjeta.get_tipo_display(),
            creado_en=tarjeta.creado_en,
            orden=tarjeta.id,
        ))

    for sustitucion in sustituciones:
        orden += 1
        eventos_live.append(SimpleNamespace(
            tipo="sustitucion",
            icono="🔁",
            minuto=sustitucion.minuto,
            equipo_id=sustitucion.equipo_id,
            texto=nombre_resumen_jugador(sustitucion.jugador_entra),
            detalle=f"Sale {nombre_resumen_jugador(sustitucion.jugador_sale)}",
            jugador_entra=nombre_resumen_jugador(sustitucion.jugador_entra),
            jugador_sale=nombre_resumen_jugador(sustitucion.jugador_sale),
            creado_en=sustitucion.creado_en,
            orden=sustitucion.id,
        ))

    eventos_live = sorted(
        eventos_live,
        key=_clave_orden_evento_resumen,
    )

    return render(request, "partido_live.html", {
        "partido": partido,
        "escudo_local": escudo_url(partido.equipo_local),
        "escudo_visitante": escudo_url(partido.equipo_visitante),
        "fecha_inicio_live": partido.fecha.strftime("%Y-%m-%d") if partido.fecha else "",
        "hora_inicio_live": partido.hora.strftime("%H:%M") if partido.hora else "",
        "goles": goles,
        "tarjetas": tarjetas,
        "sustituciones": sustituciones,
        "sustituciones_local": sustituciones_local,
        "sustituciones_visitante": sustituciones_visitante,
        "alineaciones_local": alineaciones_local,
        "alineaciones_visitante": alineaciones_visitante,
        "suplentes_local": suplentes_local,
        "suplentes_visitante": suplentes_visitante,
        "no_disponibles_local": no_disponibles_local,
        "no_disponibles_visitante": no_disponibles_visitante,
        "eventos_live": eventos_live,
        "segundos_vivos": segundos_vivos_partido(partido),
        "volver_url": volver_url,
        "delegado_alineacion_url": url_alineacion_delegado_si_aplica(request.user, partido),
        "puede_diligenciar_partido": puede_diligenciar_partido(request.user, partido),
    })
def _pausar_cronometro(partido):
    if partido.inicio_en_vivo:
        diferencia = timezone.now() - partido.inicio_en_vivo
        partido.segundos_acumulados += int(diferencia.total_seconds())

    partido.inicio_en_vivo = None
    partido.cronometro_pausado = True
    partido.save()


@login_required
def cronometro_primer_tiempo(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    partido.estado = "EN_JUEGO"
    partido.periodo_en_vivo = "PT"
    partido.cronometro_pausado = False

    if not partido.inicio_en_vivo:
        partido.inicio_en_vivo = timezone.now()

    partido.save()
    return redirect("editor_partido_movil", partido_id=partido.id)


@login_required
def cronometro_entretiempo(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    _pausar_cronometro(partido)
    partido.periodo_en_vivo = "ET"
    partido.save()
    return redirect("editor_partido_movil", partido_id=partido.id)


@login_required
def cronometro_segundo_tiempo(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    partido.estado = "EN_JUEGO"
    partido.periodo_en_vivo = "ST"
    partido.cronometro_pausado = False
    partido.inicio_en_vivo = timezone.now()
    partido.save()
    return redirect("editor_partido_movil", partido_id=partido.id)


@login_required
def cronometro_pausar(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    _pausar_cronometro(partido)
    return redirect("editor_partido_movil", partido_id=partido.id)


@login_required
def cronometro_reanudar(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    partido.estado = "EN_JUEGO"
    partido.cronometro_pausado = False
    partido.inicio_en_vivo = timezone.now()
    partido.save()
    return redirect("editor_partido_movil", partido_id=partido.id)


@login_required
def cronometro_suspender(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    _pausar_cronometro(partido)
    partido.estado = "SUSPENDIDO"
    partido.save()
    return redirect("editor_partido_movil", partido_id=partido.id)


@login_required
def cronometro_finalizar(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not puede_diligenciar_partido(request.user, partido):
        return denegar_partido_no_autorizado()
    _pausar_cronometro(partido)
    partido.estado = "FINALIZADO"
    partido.periodo_en_vivo = "FIN"
    partido.save()
    if not es_editor_torneo(request.user):
        return redirect("partido_live", partido_id=partido.id)
    return redirect("editor_partido_movil", partido_id=partido.id)

