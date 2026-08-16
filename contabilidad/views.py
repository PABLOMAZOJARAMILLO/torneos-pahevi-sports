import csv
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from torneos.models import Categoria, Equipo, Tarjeta, Torneo
from torneos.views import denegar_permiso_torneo, puede_gestionar_torneo, torneos_para_usuario

from .forms import AbonoForm, EgresoForm, IngresoManualForm
from .models import AbonoInscripcion, CobroTarjeta, Configuracion, CuentaEquipo, Egreso, Ingreso, PagoTarjetas
from .signals import sincronizar_tarjeta


logger = logging.getLogger(__name__)


def _destino_contabilidad(request):
    destino = (request.POST.get("volver") or "").strip()
    return destino if destino.startswith("/contabilidad/") else "contabilidad:inicio"


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
    cuentas_actuales = {
        cuenta.equipo_id: (cuenta.torneo_id, cuenta.categoria_id)
        for cuenta in CuentaEquipo.objects.filter(torneo=torneo).only("equipo_id", "torneo_id", "categoria_id")
    }
    equipos = Equipo.objects.select_related("categoria").filter(categoria__torneo=torneo).only(
        "id", "categoria_id", "categoria__torneo_id",
    )
    for equipo in equipos.iterator(chunk_size=100):
        if cuentas_actuales.get(equipo.id) == (torneo.id, equipo.categoria_id):
            continue
        try:
            CuentaEquipo.objects.update_or_create(
                torneo=torneo, equipo=equipo, defaults={"categoria": equipo.categoria},
            )
        except Exception:
            logger.exception("No se pudo sincronizar el equipo %s en contabilidad", equipo.id)
    # Las señales sincronizan las tarjetas nuevas. Aquí solo recuperamos tarjetas
    # históricas que aún no tengan cobro, evitando reconstruir todo en cada visita.
    tarjetas_pendientes_sincronizacion = Tarjeta.objects.filter(
        partido__categoria__torneo=torneo,
        cobro_contable__isnull=True,
    ).select_related("partido__categoria__torneo", "equipo__categoria").only(
        "id", "tipo", "equipo_id", "partido_id",
        "partido__categoria_id", "partido__categoria__torneo_id",
    ).order_by("id")[:100]
    for tarjeta in tarjetas_pendientes_sincronizacion.iterator(chunk_size=100):
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
        recaudado = AbonoInscripcion.objects.filter(cuenta__categoria=categoria, ingreso__anulado=False).aggregate(total=Sum("valor"))["total"] or Decimal("0")
        egresos = Egreso.objects.filter(torneo=torneo, categoria=categoria, anulado=False).aggregate(total=Sum("valor"))["total"] or Decimal("0")
        fondos.append({"categoria": categoria, "esperado": esperado, "recaudado": recaudado, "pendiente": max(Decimal("0"), esperado-recaudado), "disponible": recaudado-egresos})
    ingresos = Ingreso.objects.filter(torneo=torneo, anulado=False).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    egresos = Egreso.objects.filter(torneo=torneo, anulado=False).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    inscripciones = AbonoInscripcion.objects.filter(cuenta__torneo=torneo, ingreso__anulado=False).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    gastos_inscripcion = Egreso.objects.filter(torneo=torneo, categoria__isnull=False, anulado=False).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    ingresos_generales = Ingreso.objects.filter(torneo=torneo, anulado=False).exclude(tipo="INSCRIPCION").aggregate(total=Sum("valor"))["total"] or Decimal("0")
    egresos_generales = Egreso.objects.filter(torneo=torneo, categoria__isnull=True, anulado=False).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    categorias = list(Categoria.objects.filter(torneo=torneo).order_by("nombre"))
    cuentas_por_categoria = [
        {"categoria": categoria, "cuentas": [c for c in cuentas if c.categoria_id == categoria.id]}
        for categoria in categorias
    ]
    ingresos_recientes = list(Ingreso.objects.filter(torneo=torneo).select_related("categoria", "equipo")[:60])
    egresos_recientes = list(Egreso.objects.filter(torneo=torneo).select_related("categoria")[:60])
    movimientos = [
        {"objeto": item, "tipo": "ingreso", "fecha": item.fecha, "creado_en": item.creado_en}
        for item in ingresos_recientes
    ] + [
        {"objeto": item, "tipo": "egreso", "fecha": item.fecha, "creado_en": item.creado_en}
        for item in egresos_recientes
    ]
    movimientos.sort(key=lambda item: (item["fecha"], item["creado_en"]), reverse=True)
    movimientos = movimientos[:60]
    movimientos_por_categoria = []
    for categoria in categorias:
        items = [m for m in movimientos if m["objeto"].categoria_id == categoria.id]
        if items:
            movimientos_por_categoria.append({"categoria": categoria, "movimientos": items})
    movimientos_generales = [m for m in movimientos if m["objeto"].categoria_id is None]
    return {
        "torneo": torneo, "cuentas": cuentas, "cuentas_por_categoria": cuentas_por_categoria,
        "fondos": fondos, "ingresos": ingresos, "egresos_total": egresos, "balance": ingresos-egresos,
        "inscripciones_recaudadas": inscripciones, "gastos_desde_inscripciones": gastos_inscripcion,
        "inscripciones_disponibles": inscripciones-gastos_inscripcion,
        "fondo_general_disponible": ingresos_generales-egresos_generales,
        "movimientos_por_categoria": movimientos_por_categoria,
        "movimientos_generales": movimientos_generales,
        "puede_anular": False,
        "configuracion": Configuracion.objects.get(torneo=torneo),
    }


@login_required
def inicio(request):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    contexto = _contexto(torneo)
    contexto["torneos_contables"] = _torneos_contables(request)
    contexto["puede_anular"] = request.user.is_superuser or request.user.is_staff
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
        configuracion.mensualidades_habilitadas = request.POST.get("mensualidades_habilitadas") == "1"
        configuracion.valor_mensualidad = max(Decimal("0"), Decimal(request.POST.get("valor_mensualidad", "0") or "0"))
        configuracion.dia_limite_mensualidad = min(31, max(1, int(request.POST.get("dia_limite_mensualidad", "10") or "10")))
        inicio = (request.POST.get("mes_inicio_mensualidades") or "").strip()
        fin = (request.POST.get("mes_fin_mensualidades") or "").strip()
        configuracion.mes_inicio_mensualidades = parse_date(f"{inicio}-01") if inicio else None
        configuracion.mes_fin_mensualidades = parse_date(f"{fin}-01") if fin else None
        if configuracion.mes_inicio_mensualidades and configuracion.mes_fin_mensualidades and configuracion.mes_inicio_mensualidades > configuracion.mes_fin_mensualidades:
            raise ValueError("El mes inicial no puede ser posterior al mes final.")
        configuracion.save()
        for cobro in CobroTarjeta.objects.filter(cuenta__torneo=torneo, pago__isnull=True):
            cobro.valor = configuracion.valor_tarjeta(cobro.tipo)
            cobro.save(update_fields=["valor"])
        messages.success(request, "Configuración contable actualizada.")
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
    return render(request, "contabilidad/cuenta.html", {"torneo": torneo, "cuenta": objeto, "form": form, "cobros": objeto.cobros_tarjetas.select_related("tarjeta__jugador").all(), "abonos": objeto.abonos.select_related("ingreso", "ingreso__anulado_por").all(), "puede_anular": request.user.is_superuser or request.user.is_staff})


@login_required
def editar_abono(request, abono_id):
    torneo = _torneo_permitido(request)
    abono = get_object_or_404(AbonoInscripcion.objects.select_related("cuenta", "ingreso"), id=abono_id, cuenta__torneo=torneo)
    if abono.ingreso.anulado:
        messages.error(request, "Un movimiento anulado no se puede editar.")
        return redirect("contabilidad:cuenta", cuenta_id=abono.cuenta_id)
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


@login_required
def nuevo_ingreso(request):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    form = IngresoManualForm(request.POST or None, torneo=torneo)
    if request.method == "POST" and form.is_valid():
        ingreso = form.save(commit=False)
        ingreso.torneo = torneo
        ingreso.tipo = "OTRO"
        ingreso.registrado_por = request.user
        ingreso.save()
        messages.success(request, "Ingreso guardado.")
        return redirect("contabilidad:inicio")
    return render(request, "contabilidad/formulario.html", {"torneo": torneo, "titulo": "Registrar ingreso", "form": form})


@login_required
def mensualidades(request):
    torneo = _torneo_permitido(request)
    if not torneo:
        return denegar_permiso_torneo()
    _sincronizar(torneo)
    configuracion = Configuracion.objects.get(torneo=torneo)
    if not configuracion.mensualidades_habilitadas:
        messages.info(request, "Las mensualidades no están habilitadas para este torneo.")
        return redirect("contabilidad:inicio")

    periodo_texto = (request.POST.get("periodo") or request.GET.get("periodo") or "").strip()
    periodo = parse_date(f"{periodo_texto}-01") if periodo_texto else None
    periodo = periodo or timezone.localdate().replace(day=1)
    cuentas = list(CuentaEquipo.objects.filter(torneo=torneo).select_related("equipo").order_by("equipo__nombre"))
    pagos_activos = Ingreso.objects.filter(
        torneo=torneo, tipo="MENSUALIDAD", periodo_mensualidad=periodo, anulado=False,
    )
    pagado_por_equipo = {
        fila["equipo_id"]: fila["total"] or Decimal("0")
        for fila in pagos_activos.values("equipo_id").annotate(total=Sum("valor"))
    }

    if request.method == "POST":
        cuenta = get_object_or_404(CuentaEquipo, torneo=torneo, id=request.POST.get("cuenta_id"))
        try:
            valor = Decimal(request.POST.get("valor", "0"))
        except Exception:
            valor = Decimal("0")
        pagado = pagado_por_equipo.get(cuenta.equipo_id, Decimal("0"))
        pendiente = max(Decimal("0"), configuracion.valor_mensualidad - pagado)
        fuera_periodo = (
            (configuracion.mes_inicio_mensualidades and periodo < configuracion.mes_inicio_mensualidades)
            or (configuracion.mes_fin_mensualidades and periodo > configuracion.mes_fin_mensualidades)
        )
        if fuera_periodo:
            messages.error(request, "El mes seleccionado está fuera del periodo configurado.")
        elif valor <= 0:
            messages.error(request, "El valor del pago debe ser mayor que cero.")
        elif valor > pendiente:
            messages.error(request, f"El pago supera el saldo pendiente de ${pendiente:.0f}.")
        else:
            Ingreso.objects.create(
                torneo=torneo, categoria=cuenta.categoria, equipo=cuenta.equipo,
                tipo="MENSUALIDAD", concepto=f"Mensualidad - {cuenta.equipo.nombre}",
                detalle=(request.POST.get("observacion") or "")[:300], valor=valor,
                fecha=parse_date(request.POST.get("fecha", "")) or timezone.localdate(),
                forma_pago=(request.POST.get("forma_pago") or "Efectivo")[:40],
                periodo_mensualidad=periodo, registrado_por=request.user,
            )
            messages.success(request, "Pago mensual registrado correctamente.")
        return redirect(f"/contabilidad/mensualidades/?periodo={periodo:%Y-%m}")

    filas = []
    for cuenta in cuentas:
        pagado = pagado_por_equipo.get(cuenta.equipo_id, Decimal("0"))
        pendiente = max(Decimal("0"), configuracion.valor_mensualidad - pagado)
        filas.append({
            "cuenta": cuenta, "esperado": configuracion.valor_mensualidad,
            "pagado": pagado, "pendiente": pendiente,
            "estado": "PAGADO" if not pendiente else "ABONO" if pagado else "PENDIENTE",
        })
    esperado_total = configuracion.valor_mensualidad * len(cuentas)
    recaudado_total = sum((fila["pagado"] for fila in filas), Decimal("0"))
    historial = Ingreso.objects.filter(
        torneo=torneo, tipo="MENSUALIDAD", periodo_mensualidad=periodo,
    ).select_related("equipo", "registrado_por", "anulado_por")
    return render(request, "contabilidad/mensualidades.html", {
        "torneo": torneo, "configuracion": configuracion, "periodo": periodo,
        "periodo_texto": periodo.strftime("%Y-%m"), "filas": filas,
        "esperado_total": esperado_total, "recaudado_total": recaudado_total,
        "pendiente_total": max(Decimal("0"), esperado_total - recaudado_total),
        "historial": historial, "puede_anular": request.user.is_superuser or request.user.is_staff,
    })


@login_required
@require_POST
def anular_movimiento(request, tipo, movimiento_id):
    torneo = _torneo_permitido(request)
    if not torneo or not (request.user.is_superuser or request.user.is_staff):
        return denegar_permiso_torneo()
    motivo = (request.POST.get("motivo") or "").strip()
    if len(motivo) < 5:
        messages.error(request, "Escribe el motivo de la anulación (mínimo 5 caracteres).")
        return redirect(_destino_contabilidad(request))
    modelo = Ingreso if tipo == "ingreso" else Egreso if tipo == "egreso" else None
    if modelo is None:
        return denegar_permiso_torneo()
    movimiento = get_object_or_404(modelo, id=movimiento_id, torneo=torneo)
    if movimiento.anulado:
        messages.info(request, "Este movimiento ya estaba anulado.")
        return redirect(_destino_contabilidad(request))
    with transaction.atomic():
        movimiento.anulado = True
        movimiento.motivo_anulacion = motivo[:300]
        movimiento.anulado_por = request.user
        movimiento.anulado_en = timezone.now()
        movimiento.save(update_fields=["anulado", "motivo_anulacion", "anulado_por", "anulado_en"])
        if tipo == "ingreso" and movimiento.tipo == "TARJETAS":
            try:
                pago = movimiento.pago_tarjetas
            except PagoTarjetas.DoesNotExist:
                pago = None
            if pago:
                CobroTarjeta.objects.filter(pago=pago).update(pago=None)
    messages.success(request, "Movimiento anulado. Se conservará en la auditoría y ya no afectará los saldos.")
    return redirect(_destino_contabilidad(request))


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
    totales = cobros.aggregate(
        cantidad=Count("id"),
        amarillas=Count("id", filter=Q(tipo="AMARILLA")),
        rojas=Count("id", filter=Q(tipo="ROJA")),
        valor_total=Sum("valor"),
        valor_pagado=Sum("valor", filter=Q(pago__isnull=False)),
        valor_pendiente=Sum("valor", filter=Q(pago__isnull=True)),
    )
    for clave in ("cantidad", "amarillas", "rojas"):
        totales[clave] = totales[clave] or 0
    for clave in ("valor_total", "valor_pagado", "valor_pendiente"):
        totales[clave] = totales[clave] or Decimal("0")
    resumen = cobros.values("cuenta__categoria__nombre", "cuenta__equipo__nombre", "tarjeta__partido__fecha").annotate(
        cantidad=Count("id"), amarillas=Count("id", filter=Q(tipo="AMARILLA")),
        rojas=Count("id", filter=Q(tipo="ROJA")), total=Sum("valor"),
    ).order_by("-tarjeta__partido__fecha", "cuenta__categoria__nombre", "cuenta__equipo__nombre")
    return render(request, "contabilidad/tarjetas.html", {
        "torneo": torneo, "cobros": cobros, "resumen": resumen,
        "categorias": Categoria.objects.filter(torneo=torneo).order_by("nombre"),
        "equipos": Equipo.objects.filter(categoria__torneo=torneo).select_related("categoria").order_by("categoria__nombre", "nombre"),
        "filtros": request.GET, "totales": totales,
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
    cobros = _tarjetas_filtradas(request, torneo)
    totales = cobros.aggregate(
        cantidad=Count("id"), amarillas=Count("id", filter=Q(tipo="AMARILLA")),
        rojas=Count("id", filter=Q(tipo="ROJA")), valor_total=Sum("valor"),
        valor_pagado=Sum("valor", filter=Q(pago__isnull=False)),
        valor_pendiente=Sum("valor", filter=Q(pago__isnull=True)),
    )
    writer.writerow(["TOTALIZADO DE TARJETAS"])
    writer.writerow(["Amarillas", "Rojas", "Cantidad total", "Valor total", "Valor pagado", "Saldo pendiente"])
    writer.writerow([totales["amarillas"] or 0, totales["rojas"] or 0, totales["cantidad"] or 0, totales["valor_total"] or 0, totales["valor_pagado"] or 0, totales["valor_pendiente"] or 0])
    writer.writerow([])
    writer.writerow(["Fecha", "Categoría", "Equipo", "Jugador", "Partido", "Tipo", "Minuto", "Valor", "Estado"])
    for cobro in cobros:
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
    writer.writerow(["Fecha", "Tipo", "Categoría/Fondo", "Equipo", "Mes mensualidad", "Concepto", "Detalle", "Valor", "Estado", "Motivo anulación", "Anulado por", "Fecha anulación"])
    for i in Ingreso.objects.filter(torneo=torneo):
        writer.writerow([i.fecha, "Ingreso", i.categoria.nombre if i.categoria else "Fondo general", i.equipo.nombre if i.equipo else "", i.periodo_mensualidad.strftime("%Y-%m") if i.periodo_mensualidad else "", i.concepto, i.detalle, i.valor, "ANULADO" if i.anulado else "ACTIVO", i.motivo_anulacion, i.anulado_por or "", i.anulado_en or ""])
    for e in Egreso.objects.filter(torneo=torneo):
        writer.writerow([e.fecha, "Egreso", e.fondo, "", "", e.concepto, e.observacion, e.valor, "ANULADO" if e.anulado else "ACTIVO", e.motivo_anulacion, e.anulado_por or "", e.anulado_en or ""])
    return response
