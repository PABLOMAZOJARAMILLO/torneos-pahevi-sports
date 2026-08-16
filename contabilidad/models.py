import os
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from torneos.models import Categoria, Equipo, Partido, Tarjeta, Torneo


def ruta_soporte(instance, filename):
    extension = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"contabilidad/torneo_{instance.torneo_id}/soportes/{uuid.uuid4().hex}{extension}"


class Configuracion(models.Model):
    torneo = models.OneToOneField(Torneo, on_delete=models.CASCADE, related_name="contabilidad_configuracion")
    valor_amarilla = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("5000"))
    valor_roja = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("8000"))
    mensualidades_habilitadas = models.BooleanField(default=False)
    valor_mensualidad = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    dia_limite_mensualidad = models.PositiveSmallIntegerField(default=10)
    mes_inicio_mensualidades = models.DateField(null=True, blank=True)
    mes_fin_mensualidades = models.DateField(null=True, blank=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def valor_tarjeta(self, tipo):
        return self.valor_roja if str(tipo).upper() == "ROJA" else self.valor_amarilla


class CuentaEquipo(models.Model):
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name="contabilidad_cuentas")
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name="contabilidad_cuentas")
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="contabilidad_cuentas")
    valor_inscripcion = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    observacion = models.CharField(max_length=250, blank=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria__nombre", "equipo__nombre"]
        constraints = [
            models.UniqueConstraint(fields=["torneo", "equipo"], name="cuenta_contable_unica_torneo_equipo"),
        ]

    @property
    def total_abonado(self):
        return self.abonos.filter(ingreso__anulado=False).aggregate(total=models.Sum("valor"))["total"] or Decimal("0")

    @property
    def saldo_inscripcion(self):
        return max(Decimal("0"), self.valor_inscripcion - self.total_abonado)

    @property
    def saldo_tarjetas(self):
        return self.cobros_tarjetas.filter(pago__isnull=True).aggregate(total=models.Sum("valor"))["total"] or Decimal("0")

    def clean(self):
        if self.equipo_id and self.categoria_id and self.equipo.categoria_id != self.categoria_id:
            raise ValidationError("El equipo no pertenece a la categoría seleccionada.")
        if self.categoria_id and self.torneo_id and self.categoria.torneo_id != self.torneo_id:
            raise ValidationError("La categoría no pertenece al torneo seleccionado.")


class Ingreso(models.Model):
    TIPOS = [("INSCRIPCION", "Inscripción"), ("TARJETAS", "Pago de tarjetas"), ("MENSUALIDAD", "Pago de mensualidad"), ("OTRO", "Otro")]
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name="contabilidad_ingresos")
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    equipo = models.ForeignKey(Equipo, on_delete=models.SET_NULL, null=True, blank=True)
    partidos = models.ManyToManyField(
        Partido,
        blank=True,
        related_name="ingresos_arbitraje",
        verbose_name="Partidos asociados",
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    concepto = models.CharField(max_length=180)
    detalle = models.TextField(blank=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(default=timezone.localdate)
    forma_pago = models.CharField(max_length=40, default="Efectivo")
    periodo_mensualidad = models.DateField(null=True, blank=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="contabilidad_ingresos_registrados")
    creado_en = models.DateTimeField(auto_now_add=True)
    anulado = models.BooleanField(default=False)
    motivo_anulacion = models.CharField(max_length=300, blank=True)
    anulado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="contabilidad_ingresos_anulados")
    anulado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha", "-creado_en"]


class AbonoInscripcion(models.Model):
    cuenta = models.ForeignKey(CuentaEquipo, on_delete=models.CASCADE, related_name="abonos")
    ingreso = models.OneToOneField(Ingreso, on_delete=models.CASCADE, related_name="abono_inscripcion")
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(default=timezone.localdate)
    observacion = models.CharField(max_length=250, blank=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="contabilidad_abonos_registrados")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-creado_en"]


class PagoTarjetas(models.Model):
    cuenta = models.ForeignKey(CuentaEquipo, on_delete=models.CASCADE, related_name="pagos_tarjetas")
    ingreso = models.OneToOneField(Ingreso, on_delete=models.CASCADE, related_name="pago_tarjetas")
    cantidad_amarillas = models.PositiveIntegerField(default=0)
    cantidad_rojas = models.PositiveIntegerField(default=0)
    valor_unitario_amarilla = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_unitario_roja = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(default=timezone.localdate)
    observacion = models.CharField(max_length=250, blank=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="contabilidad_pagos_tarjetas_registrados")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-creado_en"]


class CobroTarjeta(models.Model):
    tarjeta = models.OneToOneField(Tarjeta, on_delete=models.CASCADE, related_name="cobro_contable")
    cuenta = models.ForeignKey(CuentaEquipo, on_delete=models.CASCADE, related_name="cobros_tarjetas")
    tipo = models.CharField(max_length=20)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    pago = models.ForeignKey(PagoTarjetas, on_delete=models.SET_NULL, null=True, blank=True, related_name="cobros")
    creado_en = models.DateTimeField(auto_now_add=True)


class Egreso(models.Model):
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name="contabilidad_egresos")
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    partidos = models.ManyToManyField(
        Partido,
        blank=True,
        related_name="egresos_arbitraje",
        verbose_name="Partidos asociados",
    )
    concepto = models.CharField(max_length=180)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(default=timezone.localdate)
    forma_pago = models.CharField(max_length=40, default="Efectivo")
    soporte = models.ImageField(upload_to=ruta_soporte, null=True, blank=True)
    observacion = models.TextField(blank=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="contabilidad_egresos_registrados")
    creado_en = models.DateTimeField(auto_now_add=True)
    anulado = models.BooleanField(default=False)
    motivo_anulacion = models.CharField(max_length=300, blank=True)
    anulado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="contabilidad_egresos_anulados")
    anulado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha", "-creado_en"]

    @property
    def fondo(self):
        return self.categoria.nombre if self.categoria_id else "Fondo general"
