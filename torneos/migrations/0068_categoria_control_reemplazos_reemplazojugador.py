from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("torneos", "0067_tarjeta_origen_roja"),
    ]

    operations = [
        migrations.AddField(
            model_name="categoria",
            name="controlar_reemplazos_jugadores",
            field=models.BooleanField(default=False, verbose_name="Bloquear reemplazos de jugadores desde la tercera fecha"),
        ),
        migrations.CreateModel(
            name="ReemplazoJugador",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("es_fuerza_mayor", models.BooleanField(default=False)),
                ("motivo", models.CharField(blank=True, choices=[("LESION", "Lesión"), ("ENFERMEDAD", "Enfermedad"), ("FALLECIMIENTO", "Fallecimiento"), ("OTRO", "Otra fuerza mayor")], max_length=20)),
                ("justificacion", models.TextField(blank=True)),
                ("soporte", models.FileField(blank=True, null=True, upload_to="reemplazos_jugadores/%Y/%m/")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("autorizado_por", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reemplazos_jugadores_autorizados", to=settings.AUTH_USER_MODEL)),
                ("categoria", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reemplazos_jugadores", to="torneos.categoria")),
                ("equipo", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reemplazos_jugadores", to="torneos.equipo")),
                ("jugador_entrante", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reemplazos_como_entrante", to="torneos.jugador")),
                ("jugador_saliente", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reemplazos_como_saliente", to="torneos.jugador")),
            ],
            options={"verbose_name": "Reemplazo de jugador", "verbose_name_plural": "Reemplazos de jugadores", "ordering": ["-creado_en"]},
        ),
    ]
