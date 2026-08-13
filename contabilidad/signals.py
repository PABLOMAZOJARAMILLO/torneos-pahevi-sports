from django.db.models.signals import post_save
from django.dispatch import receiver

from torneos.models import Tarjeta

from .models import CobroTarjeta, Configuracion, CuentaEquipo


def sincronizar_tarjeta(tarjeta):
    torneo = tarjeta.partido.categoria.torneo
    configuracion, _ = Configuracion.objects.get_or_create(torneo=torneo)
    cuenta, _ = CuentaEquipo.objects.update_or_create(
        equipo=tarjeta.equipo,
        defaults={"torneo": torneo, "categoria": tarjeta.equipo.categoria},
    )
    CobroTarjeta.objects.update_or_create(
        tarjeta=tarjeta,
        defaults={"cuenta": cuenta, "tipo": tarjeta.tipo, "valor": configuracion.valor_tarjeta(tarjeta.tipo)},
    )


@receiver(post_save, sender=Tarjeta)
def tarjeta_a_contabilidad(sender, instance, **kwargs):
    sincronizar_tarjeta(instance)
