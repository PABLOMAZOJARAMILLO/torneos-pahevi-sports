import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0055_registroactividad_indices"),
    ]

    operations = [
        migrations.CreateModel(
            name="VisitaPublicaDiaria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha", models.DateField()),
                ("visitante_hash", models.CharField(max_length=64)),
                ("canal", models.CharField(choices=[("APK", "Aplicación"), ("MOVIL", "Navegador móvil"), ("ESCRITORIO", "Computador")], max_length=20)),
                ("primera_visita", models.DateTimeField(auto_now_add=True)),
                ("torneo", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="visitas_publicas_diarias", to="torneos.torneo")),
            ],
            options={
                "verbose_name": "Visita pública diaria",
                "verbose_name_plural": "Visitas públicas diarias",
                "indexes": [
                    models.Index(fields=["fecha", "torneo"], name="visita_fecha_torneo_idx"),
                    models.Index(fields=["fecha", "canal"], name="visita_fecha_canal_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("fecha", "torneo", "visitante_hash"), name="visita_publica_unica_dia_torneo"),
                ],
            },
        ),
    ]
