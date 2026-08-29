from django.db import migrations, models
from django.db.models import Count


def identificar_rojas_por_doble_amarilla(apps, schema_editor):
    Tarjeta = apps.get_model("torneos", "Tarjeta")
    grupos = (Tarjeta.objects.filter(tipo="AMARILLA")
        .values("partido_id", "jugador_id", "equipo_id")
        .annotate(cantidad=Count("id")).filter(cantidad__gte=1))
    for grupo in grupos.iterator():
        filtro = {"partido_id": grupo["partido_id"], "jugador_id": grupo["jugador_id"], "equipo_id": grupo["equipo_id"]}
        roja = Tarjeta.objects.filter(tipo="ROJA", **filtro).order_by("id").first()
        if roja:
            roja.origen_roja = "DOBLE_AMARILLA"
            roja.save(update_fields=["origen_roja"])


class Migration(migrations.Migration):
    dependencies = [("torneos", "0066_torneo_visible_publico")]
    operations = [
        migrations.AddField(
            model_name="tarjeta", name="origen_roja",
            field=models.CharField(blank=True, choices=[
                ("DIRECTA", "Roja directa"),
                ("DOBLE_AMARILLA", "Roja por doble amarilla"),
            ], default="DIRECTA", max_length=20),
        ),
        migrations.RunPython(identificar_rojas_por_doble_amarilla, migrations.RunPython.noop),
    ]
