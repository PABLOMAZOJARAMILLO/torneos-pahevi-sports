from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Partido


@receiver(post_save, sender=Partido)
def actualizar_fase_siguiente(sender, instance, **kwargs):
    partido = instance

    if not partido.siguiente_partido:
        return

    if not partido.slot_siguiente:
        return

    ganador = partido.ganador()

    if not ganador:
        return

    siguiente = partido.siguiente_partido

    if partido.slot_siguiente == 'LOCAL':
        siguiente.equipo_local = ganador

    elif partido.slot_siguiente == 'VISITANTE':
        siguiente.equipo_visitante = ganador

    siguiente.save()