from django.db.models.signals import post_save
from django.dispatch import receiver

from torneos.models import Equipo, Tarjeta

from .models import CobroTarjeta, Configuracion, ConfiguracionInscripcionCategoria, CuentaEquipo


def sincronizar_tarjeta(tarjeta):
    torneo = tarjeta.partido.categoria.torneo
    configuracion, _ = Configuracion.objects.get_or_create(torneo=torneo)
    categoria = tarjeta.partido.categoria
    cuenta, _ = CuentaEquipo.objects.update_or_create(
        torneo=torneo,
        equipo=tarjeta.equipo,
        defaults={"torneo": torneo, "categoria": categoria},
    )
    CobroTarjeta.objects.update_or_create(
        tarjeta=tarjeta,
        defaults={"cuenta": cuenta, "tipo": tarjeta.tipo, "valor": configuracion.valor_tarjeta(tarjeta.tipo)},
    )


@receiver(post_save, sender=Tarjeta)
def tarjeta_a_contabilidad(sender, instance, **kwargs):
    sincronizar_tarjeta(instance)


@receiver(post_save, sender=Equipo)
def equipo_a_contabilidad(sender, instance, **kwargs):
    """Mantiene una única cuenta contable por cada equipo de la app deportiva."""
    if not instance.categoria_id:
        return
    valor_inscripcion = ConfiguracionInscripcionCategoria.objects.filter(
        torneo=instance.categoria.torneo, categoria=instance.categoria,
    ).values_list("valor", flat=True).first() or 0
    cuenta, creada = CuentaEquipo.objects.get_or_create(
        torneo=instance.categoria.torneo,
        equipo=instance,
        defaults={
            "torneo": instance.categoria.torneo,
            "categoria": instance.categoria,
            "valor_inscripcion": valor_inscripcion,
        },
    )
    if not creada and cuenta.categoria_id != instance.categoria_id:
        cuenta.categoria = instance.categoria
        cuenta.valor_inscripcion = valor_inscripcion
        cuenta.save(update_fields=["categoria", "valor_inscripcion", "actualizado_en"])
