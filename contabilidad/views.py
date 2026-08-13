import csv
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from torneos.models import Categoria, Equipo, Tarjeta, Torneo
from torneos.views import denegar_permiso_torneo, puede_gestionar_torneo, torneos_para_usuario

from .forms import AbonoForm, EgresoForm
from .models import AbonoInscripcion, CobroTarjeta, Configuracion, CuentaEquipo, Egreso, Ingreso, PagoTarjetas
from .signals import sincronizar_tarjeta


logger = logging.getLogger(__name__)


def _torneo_permitido(request):
    torneos = torneos_para_usuario(request)
    torneo_id = request.session.get("contabilidad_torneo_id") or request.session.get("torneo_id")
    torneo = torneos.filter(id=torneo_id).first() if torneo_id else None
    if not torneo:
        torneo = torneos.filter(estado="ACTIVO").first() or torneos.first()
    if torneo:
        request.session["contabilidad_torneo_id"] = torneo.id
    if not torneo or not puede_gestionar_torneo(request, torneo, "editar"):
        return None
    return torneo


def _torneos_contables(request):
    return [torneo for torneo in torneos_para_usuario(request) if puede_gestionar_torneo(request, torneo, "editar")]


def _sincronizar(torneo):
    Configuracion.objects.get_or_create(torneo=torneo)
    for equipo in Equipo.objects.select_related("categoria").filter(categoria__torneo=torneo):
        try:
            CuentaEquipo.objects.update_or_create(
                equipo=equipo, defaults={"torneo": torneo, "categoria": equipo.categoria},
            )
        except Exception:
            logger.exception("No se pudo sincronizar el equipo %s en contabilidad", equipo.id)
    tarjetas_existentes = Tarjeta.objects.filter(partido__categoria__torneo=torneo).select_related("partido__categoria__torneo", "equipo__categoria")
    for tarjeta in tarjetas_existentes:
        try:
            # La cuenta debe seguir la categoría del partido que originó el cobro.
            # Esto permite procesar tarjetas históricas aunque después el equipo
            # haya sido reinscrito o movido a otra categoría/torneo.
            sincronizar_tarjeta(tarjeta)
        except Exception:
            logger.exception("No se pudo sincronizar la tarjeta %s en contabilidad", tarjeta.id)


def _contexto(torneo):
    _sincronizar(torneo)
    cuentas = list(CuentaEquipo.objects.filter(torneo=torneo).select_related("categoria", "equipo"))
    fondos = []
    for categoria in Categoria.objects.filter(torneo=torneo).order_by("nombre"):
        esperado = sum((c.valor_inscripcion for c in cuentas if c.categoria_id == categoria.id), Decimal("0"))
        recaudado = AbonoInscripcion.objects.filter(cuenta__categoria=categoria).aggregate(total=Sum("valor"))["total"] or Decimal("0")
        egresos = Egreso.objects.filter(torneo=torneo, categoria=categoria).aggregate(total=Sum("valor"))["total"] or Decimal("0")
        fondos.append({"categoria": categoria, "esperado": esperado, "recaudado": recaudado, "pendiente": max(Decimal("0"), esperado-recaudado), "disponible": recaudado-egresos})
    ingresos = Ingreso.objects.filter(torneo=torneo).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    egresos = Egreso.objects.filter(torneo=torneo).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    return {"torneo": torneo, "cuentas": cuentas, "fondos": fondos, "ingresos": ingresos, "egresos_total": egresos, "balance": ingresos-egresos, "movimientos_ingreso": Ingreso.objects.filter(torneo=torneo)[:30], "movimientos_egreso": Egreso.objects.filter(torneo=torneo)[:30], "configuracion": Configuracion.objects.get(torneo=torneo)}


@login_required
def inicio(request):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    contexto = _contexto(torneo)
    contexto["torneos_contables"] = _torneos_contables(request)
    return render(request, "contabilidad/inicio.html", contexto)


@login_required
@require_POST
def seleccionar_torneo(request):
    torneo_id = request.POST.get("torneo_id", "")
    torneo = next((item for item in _torneos_contables(request) if str(item.id) == torneo_id), None)
    if not torneo:
        return denegar_permiso_torneo()
    request.session["contabilidad_torneo_id"] = torneo.id
    messages.success(request, f"Contabilidad seleccionada: {torneo.nombre}.")
    return redirect("contabilidad:inicio")


@login_required
@require_POST
def configurar(request):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    configuracion, _ = Configuracion.objects.get_or_create(torneo=torneo)
    try:
        configuracion.valor_amarilla = max(Decimal("0"), Decimal(request.POST.get("valor_amarilla", "5000")))
        configuracion.valor_roja = max(Decimal("0"), Decimal(request.POST.get("valor_roja", "8000")))
        configuracion.save()
        for cobro in CobroTarjeta.objects.filter(cuenta__torneo=torneo, pago__isnull=True):
            cobro.valor = configuracion.valor_tarjeta(cobro.tipo)
            cobro.save(update_fields=["valor"])
        messages.success(request, "Valores de tarjetas actualizados.")
    except Exception:
        messages.error(request, "Escribe valores numéricos válidos.")
    return redirect("contabilidad:inicio")


@login_required
def cuenta(request, cuenta_id):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    objeto = get_object_or_404(CuentaEquipo.objects.select_related("equipo", "categoria"), id=cuenta_id, torneo=torneo)
    form = AbonoForm(request.POST or None)
    if request.method == "POST" and request.POST.get("accion") == "configurar":
        try:
            objeto.valor_inscripcion = max(Decimal("0"), Decimal(request.POST.get("valor_inscripcion", "0")))
            objeto.observacion = (request.POST.get("observacion") or "")[:250]
            objeto.save()
            messages.success(request, "Valor de inscripción guardado.")
        except Exception:
            messages.error(request, "Valor de inscripción inválido.")
        return redirect("contabilidad:cuenta", cuenta_id=objeto.id)
    if request.method == "POST" and request.POST.get("accion") == "abono" and form.is_valid():
        if form.cleaned_data["valor"] > objeto.saldo_inscripcion:
            form.add_error("valor", "El abono supera el saldo pendiente.")
        else:
            with transaction.atomic():
                ingreso = Ingreso.objects.create(torneo=torneo, categoria=objeto.categoria, equipo=objeto.equipo, tipo="INSCRIPCION", concepto="Inscripción de equipo", detalle=form.cleaned_data["observacion"], valor=form.cleaned_data["valor"], fecha=form.cleaned_data["fecha"], forma_pago=form.cleaned_data["forma_pago"], registrado_por=request.user)
                abono = form.save(commit=False)
                abono.cuenta = objeto
                abono.ingreso = ingreso
                abono.registrado_por = request.user
                abono.save()
            messages.success(request, "Abono e ingreso registrados.")
            return redirect("contabilidad:cuenta", cuenta_id=objeto.id)
    return render(request, "contabilidad/cuenta.html", {"torneo": torneo, "cuenta": objeto, "form": form, "cobros": objeto.cobros_tarjetas.select_related("tarjeta__jugador").all(), "abonos": objeto.abonos.all()})


@login_required
def editar_abono(request, abono_id):
    torneo = _torneo_permitido(request)
    abono = get_object_or_404(AbonoInscripcion.objects.select_related("cuenta", "ingreso"), id=abono_id, cuenta__torneo=torneo)
    form = AbonoForm(request.POST or None, instance=abono, initial={"forma_pago": abono.ingreso.forma_pago})
    if request.method == "POST" and form.is_valid():
        otros = abono.cuenta.total_abonado - abono.valor
        if otros + form.cleaned_data["valor"] > abono.cuenta.valor_inscripcion:
            form.add_error("valor", "El total abonado supera el valor de inscripción.")
        else:
            with transaction.atomic():
                abono = form.save()
                ingreso = abono.ingreso
                ingreso.valor, ingreso.fecha, ingreso.detalle, ingreso.forma_pago = abono.valor, abono.fecha, abono.observacion, form.cleaned_data["forma_pago"]
                ingreso.save()
            messages.success(request, "Abono e ingreso actualizados.")
            return redirect("contabilidad:cuenta", cuenta_id=abono.cuenta_id)
    return render(request, "contabilidad/formulario.html", {"torneo": torneo, "titulo": "Editar abono", "form": form})


@login_required
@require_POST
def pagar_tarjetas(request, cuenta_id):
    torneo = _torneo_permitido(request)
    objeto = get_object_or_404(CuentaEquipo.objects.select_related("categoria", "equipo"), id=cuenta_id, torneo=torneo)
    cobros = list(objeto.cobros_tarjetas.filter(pago__isnull=True))
    if not cobros:
        messages.info(request, "El equipo no tiene tarjetas pendientes.")
        return redirect("contabilidad:cuenta", cuenta_id=objeto.id)
    amarillas = sum(1 for c in cobros if c.tipo == "AMARILLA")
    rojas = sum(1 for c in cobros if c.tipo == "ROJA")
    total = sum((c.valor for c in cobros), Decimal("0"))
    config = Configuracion.objects.get(torneo=torneo)
    with transaction.atomic():
        detalle = f"Amarillas: {amarillas} x ${config.valor_amarilla}; rojas: {rojas} x ${config.valor_roja}; total: ${total}"
        ingreso = Ingreso.objects.create(torneo=torneo, categoria=objeto.categoria, equipo=objeto.equipo, tipo="TARJETAS", concepto=f"Pago de tarjetas - {objeto.equipo.nombre}", detalle=detalle, valor=total, forma_pago=request.POST.get("forma_pago", "Efectivo"), registrado_por=request.user)
        pago = PagoTarjetas.objects.create(cuenta=objeto, ingreso=ingreso, cantidad_amarillas=amarillas, cantidad_rojas=rojas, valor_unitario_amarilla=config.valor_amarilla, valor_unitario_roja=config.valor_roja, total=total, observacion=(request.POST.get("observacion") or "")[:250], registrado_por=request.user)
        CobroTarjeta.objects.filter(id__in=[c.id for c in cobros]).update(pago=pago)
    messages.success(request, "Pago de tarjetas e ingreso registrados automáticamente.")
    return redirect("contabilidad:cuenta", cuenta_id=objeto.id)


@login_required
def nuevo_egreso(request):
    torneo = _torneo_permitido(request)
    form = EgresoForm(request.POST or None, request.FILES or None, torneo=torneo)
    if request.method == "POST" and form.is_valid():
        egreso = form.save(commit=False)
        egreso.torneo, egreso.registrado_por = torneo, request.user
        egreso.save()
        messages.success(request, "Egreso y soporte guardados.")
        return redirect("contabilidad:inicio")
    return render(request, "contabilidad/formulario.html", {"torneo": torneo, "titulo": "Registrar egreso", "form": form})


def _tarjetas_filtradas(request, torneo):
    cobros = CobroTarjeta.objects.filter(cuenta__torneo=torneo).select_related(
        "cuenta__categoria", "cuenta__equipo", "tarjeta__jugador", "tarjeta__partido",
    )
    categoria_id = request.GET.get("categoria", "").strip()
    equipo_id = request.GET.get("equipo", "").strip()
    fecha_desde = parse_date(request.GET.get("desde", ""))
    fecha_hasta = parse_date(request.GET.get("hasta", ""))
    estado = request.GET.get("estado", "").strip()
    if categoria_id.isdigit():
        cobros = cobros.filter(cuenta__categoria_id=categoria_id)
    if equipo_id.isdigit():
        cobros = cobros.filter(cuenta__equipo_id=equipo_id)
    if fecha_desde:
        cobros = cobros.filter(tarjeta__partido__fecha__gte=fecha_desde)
    if fecha_hasta:
        cobros = cobros.filter(tarjeta__partido__fecha__lte=fecha_hasta)
    if estado == "pendiente":
        cobros = cobros.filter(pago__isnull=True)
    elif estado == "pagado":
        cobros = cobros.filter(pago__isnull=False)
    return cobros.order_by("-tarjeta__partido__fecha", "cuenta__categoria__nombre", "cuenta__equipo__nombre", "tarjeta__id")


@login_required
def tarjetas(request):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    _sincronizar(torneo)
    cobros = _tarjetas_filtradas(request, torneo)
    resumen = cobros.values("cuenta__categoria__nombre", "cuenta__equipo__nombre", "tarjeta__partido__fecha").annotate(
        cantidad=Count("id"), amarillas=Count("id", filter=Q(tipo="AMARILLA")),
        rojas=Count("id", filter=Q(tipo="ROJA")), total=Sum("valor"),
    ).order_by("-tarjeta__partido__fecha", "cuenta__categoria__nombre", "cuenta__equipo__nombre")
    return render(request, "contabilidad/tarjetas.html", {
        "torneo": torneo, "cobros": cobros, "resumen": resumen,
        "categorias": Categoria.objects.filter(torneo=torneo).order_by("nombre"),
        "equipos": Equipo.objects.filter(categoria__torneo=torneo).select_related("categoria").order_by("categoria__nombre", "nombre"),
        "filtros": request.GET, "total": cobros.aggregate(total=Sum("valor"))["total"] or Decimal("0"),
    })


@login_required
def reporte_tarjetas(request):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    _sincronizar(torneo)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="tarjetas-contabilidad.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Fecha", "Categoría", "Equipo", "Jugador", "Partido", "Tipo", "Minuto", "Valor", "Estado"])
    for cobro in _tarjetas_filtradas(request, torneo):
        tarjeta = cobro.tarjeta
        writer.writerow([tarjeta.partido.fecha, cobro.cuenta.categoria.nombre, cobro.cuenta.equipo.nombre, tarjeta.jugador.nombres, str(tarjeta.partido), tarjeta.get_tipo_display(), tarjeta.minuto or "", cobro.valor, "Pagado" if cobro.pago_id else "Pendiente"])
    return response


@login_required
def reporte(request):
    torneo = _torneo_permitido(request)
    contexto = _contexto(torneo)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="estado-cuentas.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Categoría", "Equipo", "Inscripción", "Abonado", "Debe inscripción", "Debe tarjetas", "Estado"])
    for c in contexto["cuentas"]:
        deuda = c.saldo_inscripcion + c.saldo_tarjetas
        writer.writerow([c.categoria.nombre, c.equipo.nombre, c.valor_inscripcion, c.total_abonado, c.saldo_inscripcion, c.saldo_tarjetas, "DEBE" if deuda else "PAZ Y SALVO"])
    writer.writerow([])
    writer.writerow(["Fecha", "Tipo", "Categoría/Fondo", "Concepto", "Detalle", "Valor"])
    for i in Ingreso.objects.filter(torneo=torneo):
        writer.writerow([i.fecha, "Ingreso", i.categoria.nombre if i.categoria else "Fondo general", i.concepto, i.detalle, i.valor])
    for e in Egreso.objects.filter(torneo=torneo):
        writer.writerow([e.fecha, "Egreso", e.fondo, e.concepto, e.observacion, e.valor])
    return response
