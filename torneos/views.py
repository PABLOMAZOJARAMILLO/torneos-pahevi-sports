from collections import defaultdict
from datetime import date, datetime, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
import re
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import FileResponse, HttpResponse
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.templatetags.static import static
from html2image import Html2Image
from django.views.decorators.http import require_POST
from openpyxl import load_workbook

from .forms import DocumentoForm, EquipoForm, JugadorForm, PartidoForm
from .models import Categoria, Documento, Equipo, Partido, Gol, Tarjeta, Jugador, AlineacionPartido, SustitucionPartido, limpiar_ruta_cloudinary


def es_editor_torneo(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


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
    imagenes = listar_imagenes_cloudinary(500)
    q = request.GET.get("q", "").strip()

    if q:
        imagenes = [
            imagen for imagen in imagenes
            if q.lower() in imagen["public_id"].lower()
        ]

    return render(request, "gestion/biblioteca_cloudinary.html", {
        "imagenes": imagenes,
        "q": q,
        "equipos": Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre"),
        "jugadores": Jugador.objects.select_related("equipo").order_by("equipo__nombre", "nombres"),
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_asignar_imagen_cloudinary(request):
    if request.method != "POST":
        return redirect("gestion_biblioteca_cloudinary")

    public_id = (request.POST.get("public_id") or "").strip()
    tipo = request.POST.get("tipo")
    objeto_id = request.POST.get("objeto_id")

    if not public_id or not tipo or not objeto_id:
        messages.error(request, "Selecciona una imagen y un destino.")
        return redirect("gestion_biblioteca_cloudinary")

    if tipo == "equipo":
        equipo = get_object_or_404(Equipo, id=objeto_id)
        equipo.escudo = public_id
        equipo.save(update_fields=["escudo"])
        messages.success(request, f"Imagen asignada al equipo {equipo.nombre}.")
        return redirect("gestion_equipo_editar", equipo_id=equipo.id)

    if tipo == "jugador":
        jugador = get_object_or_404(Jugador, id=objeto_id)
        jugador.foto = public_id
        jugador.save(update_fields=["foto"])
        messages.success(request, f"Imagen asignada al jugador {jugador.nombres}.")
        return redirect("gestion_jugador_editar", jugador_id=jugador.id)

    messages.error(request, "Destino no valido.")
    return redirect("gestion_biblioteca_cloudinary")


def aplicar_imagen_cloudinary(instancia, campo, public_id, archivo_subido):
    public_id = (public_id or "").strip()
    if public_id and not archivo_subido:
        setattr(instancia, campo, public_id)


def documentos_publicos_por_tipo():
    documentos = Documento.objects.filter(activo=True).order_by("tipo", "-creado_en", "titulo")
    return {
        "reglamentos": documentos.filter(tipo="REGLAMENTO"),
        "resoluciones": documentos.filter(tipo="RESOLUCION"),
        "demandas": documentos.filter(tipo="DEMANDA"),
        "comunicados": documentos.filter(tipo="COMUNICADO"),
    }


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


def escudo_url(equipo):
    if not equipo:
        return ""

    if equipo.escudo and equipo.escudo.storage.exists(equipo.escudo.name):
        return equipo.escudo.url

    if equipo.escudo:
        nombre_archivo = os.path.basename(equipo.escudo.name).replace(" ", "_")
        escudo = escudo_estatico_url(nombre_archivo)

        if escudo:
            return escudo

    nombre_equipo = limpiar_nombre(equipo.nombre)

    for extension in ("png", "jpg", "jpeg", "webp"):
        escudo = escudo_estatico_url(f"{nombre_equipo}.{extension}")

        if escudo:
            return escudo

    return ""

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
        "logo_torneo": request.build_absolute_uri(static("torneos/img/logo_torneo.png")),
        "logo_imcred": request.build_absolute_uri(static("torneos/img/logo_imcred.png")),
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


def construir_estructura():
    estructura = {}

    categorias = Categoria.objects.all().order_by("nombre")

    for categoria in categorias:
        estructura[categoria.nombre] = estructura_base_categoria()

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
                datos_grupo["tabla"].setdefault(equipo.nombre, {
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

        if partido.estado in ["FINALIZADO", "DECIDIDO_COMITE"]:
            gl = partido.goles_local or 0
            gv = partido.goles_visitante or 0

            local = datos_grupo["tabla"][partido.equipo_local.nombre]
            visitante = datos_grupo["tabla"][partido.equipo_visitante.nombre]

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

    for gol in Gol.objects.select_related(
        "partido__categoria",
        "jugador",
        "equipo",
        "partido"
    ):
        if gol.partido.estado not in ["FINALIZADO", "DECIDIDO_COMITE"]:
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

    for tarjeta in Tarjeta.objects.select_related(
        "partido__categoria",
        "jugador",
        "equipo",
        "partido"
    ):
        if tarjeta.partido.estado not in ["FINALIZADO", "DECIDIDO_COMITE"]:
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
        if partido.estado not in ["FINALIZADO", "DECIDIDO_COMITE"]:
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

    for tarjeta in Tarjeta.objects.select_related(
        "partido__categoria",
        "jugador",
        "equipo",
        "partido"
    ):
        if tarjeta.partido.estado not in ["FINALIZADO", "DECIDIDO_COMITE"]:
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

            if p.estado in ["FINALIZADO", "DECIDIDO_COMITE"]:
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
                "numero_fecha": p.numero_fecha,
                "fecha": p.fecha,
                "hora": p.hora,
                "cancha": p.cancha,
            }

            if p.fase == "CUARTOS":
                llaves["cuartos"].append(item)
            elif p.fase == "SEMIFINAL":
                llaves["semifinal"].append(item)
            elif p.fase == "FINAL":
                llaves["final"].append(item)
            elif p.fase == "TERCER_PUESTO":
                llaves["tercer_puesto"].append(item)

        datos_categoria["llaves"] = llaves

    # ==================================================
    # EQUIPOS Y JUGADORES POR CATEGORÍA
    # ==================================================

    for categoria_nombre, datos_categoria in estructura.items():
        equipos_categoria = Equipo.objects.filter(
            categoria__nombre=categoria_nombre,
            activo=True
        ).prefetch_related("jugadores").order_by("nombre")

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


def construir_partidos_portada():
    hoy = date.today()
    partidos = Partido.objects.filter(
        fecha__isnull=False,
    ).select_related(
        "categoria",
        "equipo_local",
        "equipo_visitante",
    )

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

    for item in Tarjeta.objects.values("partido_id"):
        tarjetas_por_partido[item["partido_id"]] += 1

    for item in Gol.objects.values("partido_id"):
        goles_por_partido[item["partido_id"]] += 1

    partidos_portada = []

    for partido in partidos:
        if partido.estado not in estados_visibles:
            continue

        if partido.estado in ["FINALIZADO", "DECIDIDO_COMITE", "WO"]:
            bloque = "RESULTADOS RECIENTES"
            orden_bloque = 0
            orden_fecha = partido.fecha.toordinal()
        elif partido.fecha <= hoy:
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

        if fase != "GRUPOS" and partido.estado in ["FINALIZADO", "DECIDIDO_COMITE", "WO"]:
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
    categoria_seleccionada = request.GET.get("categoria", "").strip()
    categorias = Categoria.objects.order_by("nombre")

    if categoria_seleccionada:
        estructura_total = construir_estructura()
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

    logos = rutas_logos(request)
    partidos_portada = construir_partidos_portada()
    documentos = documentos_publicos_por_tipo()
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
    partidos_resultados = sorted(
        [p for p in partidos_portada if p["bloque"] == "RESULTADOS RECIENTES"],
        key=lambda p: (-p["orden_fecha"], p["hora_orden"], p["categoria"]),
    )
    partidos_programados = sorted(
        [p for p in partidos_portada if p["bloque"] == "PROGRAMADOS"],
        key=lambda p: (
            0 if p["fecha"] >= date.today() else 1,
            p["orden_fecha"] if p["fecha"] >= date.today() else -p["orden_fecha"],
            p["hora_orden"],
            p["categoria"],
        ),
    )
    partidos_futuros = sorted(
        [p for p in partidos_portada if p["bloque"] == "FUTUROS"],
        key=lambda p: (p["orden_fecha"], p["hora_orden"], p["categoria"]),
    )

    return render(request, "panel_principal.html", {
        "estructura": estructura,
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
    partido = get_object_or_404(
        Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante"),
        id=partido_id
    )
    goles = Gol.objects.filter(partido=partido).select_related("jugador", "equipo").order_by("equipo__nombre", "jugador__nombres")
    tarjetas = Tarjeta.objects.filter(partido=partido).select_related("jugador", "equipo").order_by("equipo__nombre", "jugador__nombres")
    alineaciones = AlineacionPartido.objects.filter(partido=partido).select_related("jugador", "equipo").order_by("equipo__nombre", "rol", "jugador__nombres")
    sustituciones = SustitucionPartido.objects.filter(partido=partido).select_related("equipo", "jugador_sale", "jugador_entra").order_by("equipo__nombre", "minuto", "id")

    return render(request, "partido_detalle_publico.html", {
        "partido": partido,
        "goles": goles,
        "tarjetas": tarjetas,
        "alineaciones": alineaciones,
        "sustituciones": sustituciones,
        "escudo_local": escudo_url(partido.equipo_local),
        "escudo_visitante": escudo_url(partido.equipo_visitante),
    })


def crear_imagen_desde_html(html, nombre_archivo, ancho=1600, alto=1800):
    return render(None, "descargas/auto_descarga.html", {
        "contenido_html": html,
        "nombre_archivo": nombre_archivo,
        "ancho": ancho,
        "alto": alto,
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
    estructura = construir_estructura()
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    datos_grupo = datos_categoria["grupos"].get(grupo)

    if not datos_grupo:
        return HttpResponse("Grupo no encontrado")

    logos = rutas_logos(request)

    html = render_to_string("descargas/tabla_grupo.html", {
        "categoria": categoria,
        "grupo": grupo,
        "datos_grupo": datos_grupo,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"TABLA_{categoria}_{grupo}.png")
    return crear_imagen_desde_html(html, nombre, 1600, 1200)


@login_required
@user_passes_test(es_editor_torneo)
def descargar_goleadores_categoria(request, categoria):
    estructura = construir_estructura()
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    logos = rutas_logos(request)

    html = render_to_string("descargas/goleadores_categoria.html", {
        "categoria": categoria,
        "datos_categoria": datos_categoria,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"GOLEADORES_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1800, 2000)


@login_required
@user_passes_test(es_editor_torneo)
def descargar_tarjetas_categoria(request, categoria):
    estructura = construir_estructura()
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    logos = rutas_logos(request)

    html = render_to_string("descargas/tarjetas_categoria.html", {
        "categoria": categoria,
        "datos_categoria": datos_categoria,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"TARJETAS_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1800, 2000)


@login_required
@user_passes_test(es_editor_torneo)
def descargar_valla_categoria(request, categoria):
    estructura = construir_estructura()
    datos_categoria = estructura.get(categoria)

    if not datos_categoria:
        return HttpResponse("Categoría no encontrada")

    datos_categoria = preparar_categoria_para_descarga(request, datos_categoria)
    logos = rutas_logos(request)

    html = render_to_string("descargas/valla_categoria.html", {
        "categoria": categoria,
        "datos_categoria": datos_categoria,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"VALLA_MENOS_VENCIDA_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1800, 1800)


@login_required
@user_passes_test(es_editor_torneo)
def descargar_imagen(request, categoria):
    estructura_total = construir_estructura()

    if categoria not in estructura_total:
        return HttpResponse("Categoría no encontrada")

    estructura = {
        categoria: estructura_total[categoria]
    }

    logos = rutas_logos(request)

    html = render_to_string("panel_principal.html", {
        "estructura": estructura,
        "logo_alcaldia": logos["logo_alcaldia"],
        "logo_torneo": logos["logo_torneo"],
        "logo_imcred": logos["logo_imcred"],
    })

    nombre = limpiar_nombre(f"PANEL_{categoria}.png")
    return crear_imagen_desde_html(html, nombre, 1600, 2800)


def grupo_completo(categoria, grupo):
    partidos = Partido.objects.filter(
        categoria=categoria,
        grupo=grupo,
        fase="GRUPOS"
    )

    if not partidos.exists():
        return False

    for partido in partidos:
        if partido.estado not in ["FINALIZADO", "DECIDIDO_COMITE"]:
            return False

    return True


def obtener_tabla_categoria_grupo(categoria_nombre, grupo):
    estructura = construir_estructura()
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

    if partido.estado in ["FINALIZADO", "DECIDIDO_COMITE"]:
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
    categoria_obj = Categoria.objects.filter(nombre=categoria).first()

    if not categoria_obj:
        messages.error(request, "Categoría no encontrada.")
        return redirect("panel")

    # PLUS 50: un solo grupo
    if categoria.upper() == "PLUS 50":
        tabla_general = obtener_tabla_categoria_grupo(categoria, "A")

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

    tabla_a = obtener_tabla_categoria_grupo(categoria, "A")
    tabla_b = obtener_tabla_categoria_grupo(categoria, "B")

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
    if partido.estado not in ["FINALIZADO", "DECIDIDO_COMITE"]:
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

    if partido.estado in ["FINALIZADO", "DECIDIDO_COMITE"]:
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
    categoria_obj = Categoria.objects.filter(nombre=categoria).first()

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
    categoria_obj = Categoria.objects.filter(nombre=categoria).first()

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
    if partido.estado not in ["FINALIZADO", "DECIDIDO_COMITE"]:
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
    categoria_obj = Categoria.objects.filter(nombre=categoria).first()

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

    partidos = Partido.objects.filter(
        estado="PROGRAMADO",
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
    categoria_obj = Categoria.objects.filter(nombre=categoria).first()

    if not categoria_obj:
        return HttpResponse("Categoría no encontrada")

    partidos_programacion = construir_partidos_programacion(request, categoria_obj)

    if not partidos_programacion:
        return HttpResponse("No hay partidos programados con fecha, hora y cancha para esta categoría.")

    logos = rutas_logos(request)
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
    return crear_imagen_desde_html(html, nombre, medidas["ancho"], medidas["alto"])


@login_required
@user_passes_test(es_editor_torneo)
def descargar_programacion_general(request):
    partidos_programacion = construir_partidos_programacion(request)

    if not partidos_programacion:
        return HttpResponse("No hay partidos programados con fecha, hora y cancha asignada.")

    logos = rutas_logos(request)
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
    return crear_imagen_desde_html(html, nombre, medidas["ancho"], medidas["alto"])


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


@login_required
@user_passes_test(es_editor_torneo)
def editor_partido_movil(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related('categoria', 'equipo_local', 'equipo_visitante'),
        id=partido_id
    )

    jugadores_local, jugadores_visitante = _jugadores_del_partido(partido)

    goles = Gol.objects.filter(partido=partido).select_related('jugador', 'equipo').order_by('equipo__nombre', 'jugador__nombres')
    tarjetas = Tarjeta.objects.filter(partido=partido).select_related('jugador', 'equipo').order_by('equipo__nombre', 'tipo', 'jugador__nombres')
    alineaciones = AlineacionPartido.objects.filter(partido=partido).select_related('jugador', 'equipo').order_by('equipo__nombre', 'rol', 'jugador__nombres')
    sustituciones = SustitucionPartido.objects.filter(partido=partido).select_related('equipo', 'jugador_sale', 'jugador_entra').order_by('equipo__nombre', 'minuto', 'id')

    return render(request, 'editor_partido_movil.html', {
        'partido': partido,
        'jugadores_local': jugadores_local,
        'jugadores_visitante': jugadores_visitante,
        'goles': goles,
        'tarjetas': tarjetas,
        'alineaciones': alineaciones,
        'sustituciones': sustituciones,
        'estados_partido': Partido.ESTADOS,
        'fases_partido': Partido.FASES,
    })


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def guardar_info_partido_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)

    partido.goles_local = request.POST.get('goles_local') or 0
    partido.goles_visitante = request.POST.get('goles_visitante') or 0
    partido.estado = request.POST.get('estado') or partido.estado
    partido.fecha = request.POST.get('fecha') or partido.fecha
    partido.hora = request.POST.get('hora') or partido.hora
    partido.cancha = request.POST.get('cancha') or ''
    partido.numero_fecha = request.POST.get('numero_fecha') or ''
    partido.grupo = request.POST.get('grupo') or ''
    partido.fase = request.POST.get('fase') or partido.fase
    partido.goles_local_penales = request.POST.get('goles_local_penales') or 0
    partido.goles_visitante_penales = request.POST.get('goles_visitante_penales') or 0
    partido.ajuste_puntos_local = request.POST.get('ajuste_puntos_local') or 0
    partido.ajuste_puntos_visitante = request.POST.get('ajuste_puntos_visitante') or 0
    partido.observaciones = request.POST.get('observaciones') or ''
    partido.observacion_comite = request.POST.get('observacion_comite') or ''
    partido.save()

    messages.success(request, 'Partido actualizado correctamente.')
    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def agregar_gol_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    jugador_id = request.POST.get('jugador')
    equipo_id = request.POST.get('equipo')
    cantidad = request.POST.get('cantidad') or 1

    if jugador_id and equipo_id:
        jugador = get_object_or_404(Jugador, id=jugador_id)
        equipo = get_object_or_404(Equipo, id=equipo_id)

        if _validar_jugador_equipo(jugador, equipo, partido):
            Gol.objects.create(partido=partido, jugador=jugador, equipo=equipo, cantidad=cantidad)
            messages.success(request, 'Gol agregado correctamente.')
        else:
            messages.error(request, 'El jugador no pertenece al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def agregar_tarjeta_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    jugador_id = request.POST.get('jugador')
    equipo_id = request.POST.get('equipo')
    tipo = request.POST.get('tipo')

    if jugador_id and equipo_id and tipo:
        jugador = get_object_or_404(Jugador, id=jugador_id)
        equipo = get_object_or_404(Equipo, id=equipo_id)

        if _validar_jugador_equipo(jugador, equipo, partido):
            Tarjeta.objects.create(partido=partido, jugador=jugador, equipo=equipo, tipo=tipo)
            messages.success(request, 'Tarjeta agregada correctamente.')
        else:
            messages.error(request, 'El jugador no pertenece al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def agregar_alineacion_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    jugador_id = request.POST.get('jugador')
    equipo_id = request.POST.get('equipo')
    rol = request.POST.get('rol') or 'TITULAR'

    if jugador_id and equipo_id:
        jugador = get_object_or_404(Jugador, id=jugador_id)
        equipo = get_object_or_404(Equipo, id=equipo_id)

        if _validar_jugador_equipo(jugador, equipo, partido):
            AlineacionPartido.objects.update_or_create(
                partido=partido,
                jugador=jugador,
                defaults={'equipo': equipo, 'rol': rol}
            )
            messages.success(request, 'Jugador agregado a la alineación.')
        else:
            messages.error(request, 'El jugador no pertenece al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def agregar_sustitucion_movil(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
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
            messages.success(request, 'Sustitución agregada correctamente.')
        else:
            messages.error(request, 'Los jugadores deben pertenecer al equipo seleccionado.')

    return redirect('editor_partido_movil', partido_id=partido.id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def eliminar_gol_movil(request, gol_id):
    gol = get_object_or_404(Gol, id=gol_id)
    partido_id = gol.partido_id
    gol.delete()
    messages.success(request, 'Gol eliminado.')
    return redirect('editor_partido_movil', partido_id=partido_id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def eliminar_tarjeta_movil(request, tarjeta_id):
    tarjeta = get_object_or_404(Tarjeta, id=tarjeta_id)
    partido_id = tarjeta.partido_id
    tarjeta.delete()
    messages.success(request, 'Tarjeta eliminada.')
    return redirect('editor_partido_movil', partido_id=partido_id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def eliminar_alineacion_movil(request, alineacion_id):
    alineacion = get_object_or_404(AlineacionPartido, id=alineacion_id)
    partido_id = alineacion.partido_id
    alineacion.delete()
    messages.success(request, 'Jugador eliminado de la alineación.')
    return redirect('editor_partido_movil', partido_id=partido_id)


@login_required
@user_passes_test(es_editor_torneo)
@require_POST
def eliminar_sustitucion_movil(request, sustitucion_id):
    sustitucion = get_object_or_404(SustitucionPartido, id=sustitucion_id)
    partido_id = sustitucion.partido_id
    sustitucion.delete()
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
    equipos = Equipo.objects.filter(responsable=request.user).order_by('nombre')

    return render(request, 'equipos/mis_equipos.html', {
        'equipos': equipos
    })

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
    return render(request, "gestion/panel.html", {
        "total_equipos": Equipo.objects.count(),
        "total_jugadores": Jugador.objects.count(),
        "total_partidos": Partido.objects.count(),
        "total_documentos": Documento.objects.count(),
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_documentos(request):
    documentos = Documento.objects.order_by("tipo", "-creado_en", "titulo")
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
    form = DocumentoForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        documento = form.save(commit=False)
        documento.archivo = subir_documento_torneo(
            form.cleaned_data["archivo_subido"],
            documento.tipo,
        )
        documento.save()
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
    documento = get_object_or_404(Documento, id=documento_id)
    form = DocumentoForm(request.POST or None, request.FILES or None, instance=documento)

    if request.method == "POST" and form.is_valid():
        documento = form.save(commit=False)
        archivo_subido = form.cleaned_data.get("archivo_subido")

        if archivo_subido:
            documento.archivo = subir_documento_torneo(archivo_subido, documento.tipo)

        documento.save()
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


@login_required
@user_passes_test(es_editor_torneo)
def gestion_generar_fixture(request):
    categorias = Categoria.objects.order_by("nombre")
    categoria = None
    equipos = Equipo.objects.none()
    cantidad_grupos = 2
    grupos_generados = None

    categoria_id = request.GET.get("categoria") or request.POST.get("categoria")

    if categoria_id:
        categoria = Categoria.objects.filter(id=categoria_id).first()

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

        for grupo_nombre, equipos_grupo in grupos_generados.items():
            calendario = generar_fixture_grupo(equipos_grupo)

            for indice_fecha, partidos_fecha in enumerate(calendario, start=1):
                for local, visitante in partidos_fecha:
                    _, creado = Partido.objects.get_or_create(
                        categoria=categoria,
                        fase="GRUPOS",
                        grupo=grupo_nombre,
                        numero_fecha=str(indice_fecha),
                        equipo_local=local,
                        equipo_visitante=visitante,
                        defaults={
                            "fecha": date.today(),
                            "hora": time(0, 0),
                            "estado": "PROGRAMADO",
                            "cancha": "",
                        },
                    )

                    if creado:
                        creados += 1

        messages.success(request, f"Fixture generado para {categoria.nombre}. Partidos creados: {creados}.")

    return render(request, "gestion/generar_fixture.html", {
        "categorias": categorias,
        "categoria": categoria,
        "equipos": equipos,
        "cantidad_grupos": cantidad_grupos,
        "letras_grupos": letras_grupos,
        "grupos_generados": grupos_generados,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_equipos(request):
    equipos = Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre")
    q = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "").strip()

    if q:
        equipos = equipos.filter(nombre__icontains=q)

    if categoria_id:
        equipos = equipos.filter(categoria_id=categoria_id)

    return render(request, "gestion/equipos.html", {
        "equipos": equipos,
        "categorias": Categoria.objects.order_by("nombre"),
        "q": q,
        "categoria_id": categoria_id,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_equipo_nuevo(request):
    form = EquipoForm(request.POST or None, request.FILES or None)

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
    equipo = get_object_or_404(Equipo, id=equipo_id)
    form = EquipoForm(request.POST or None, request.FILES or None, instance=equipo)

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
        messages.success(request, "Equipo actualizado correctamente.")
        return redirect("gestion_equipos")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar equipo: {equipo.nombre}",
        "form": form,
        "volver_url": "gestion_equipos",
        "cloudinary_images": listar_imagenes_cloudinary(),
        "cloudinary_label": "Seleccionar escudo existente de Cloudinary",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_jugadores(request):
    jugadores = Jugador.objects.select_related("equipo", "equipo__categoria").order_by(
        "equipo__categoria__nombre",
        "equipo__nombre",
        "dorsal",
        "nombres",
    )
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
        "categorias": Categoria.objects.order_by("nombre"),
        "equipos": Equipo.objects.select_related("categoria").order_by("categoria__nombre", "nombre"),
        "q": q,
        "categoria_id": categoria_id,
        "equipo_id": equipo_id,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_jugador_nuevo(request):
    form = JugadorForm(request.POST or None, request.FILES or None)

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
    jugador = get_object_or_404(Jugador.objects.select_related("equipo"), id=jugador_id)
    form = JugadorForm(request.POST or None, request.FILES or None, instance=jugador)

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
def gestion_importar_planilla(request):
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

            categoria = Categoria.objects.filter(nombre__iexact=categoria_nombre).first()

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

                _, creado = Jugador.objects.update_or_create(
                    cedula=cedula,
                    defaults={
                        "equipo": equipo,
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
    partidos = Partido.objects.select_related("categoria", "equipo_local", "equipo_visitante").order_by(
        "fecha",
        "hora",
        "categoria__nombre",
        "grupo",
        "fase",
    )
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
        "categorias": Categoria.objects.order_by("nombre"),
        "estados": Partido.ESTADOS,
        "q": q,
        "categoria_id": categoria_id,
        "estado": estado,
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_partido_nuevo(request):
    form = PartidoForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        partido = form.save()
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
    partido = get_object_or_404(Partido, id=partido_id)
    form = PartidoForm(request.POST or None, instance=partido)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Partido actualizado correctamente.")
        return redirect("gestion_partidos")

    return render(request, "gestion/formulario.html", {
        "titulo": f"Editar partido: {partido.equipo_local} vs {partido.equipo_visitante}",
        "form": form,
        "volver_url": "gestion_partidos",
    })


@login_required
@user_passes_test(es_editor_torneo)
def gestion_importar_partidos(request):
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

                categoria = Categoria.objects.filter(nombre__iexact=categoria_nombre).first()

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

            for error in errores[:12]:
                messages.warning(request, error)

            if len(errores) > 12:
                messages.warning(request, f"Hay {len(errores) - 12} advertencias adicionales.")

            return redirect("gestion_partidos")

        except Exception as exc:
            messages.error(request, f"No se pudo importar el archivo: {exc}")
            return redirect("gestion_importar_partidos")

    return render(request, "gestion/importar_partidos.html")


