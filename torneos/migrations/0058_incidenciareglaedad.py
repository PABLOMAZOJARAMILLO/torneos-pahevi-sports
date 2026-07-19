from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0057_entregaalineacionpartido"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="IncidenciaReglaEdad",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("estado", models.CharField(choices=[("ABIERTA", "Abierta"), ("CORREGIDA", "Corregida")], default="ABIERTA", max_length=15)),
                ("errores", models.JSONField(blank=True, default=list)),
                ("segundo_inicio", models.PositiveIntegerField(default=0)),
                ("minuto_inicio", models.PositiveIntegerField(default=0)),
                ("periodo_inicio", models.CharField(blank=True, max_length=5)),
                ("iniciada_en", models.DateTimeField(auto_now_add=True)),
                ("segundo_fin", models.PositiveIntegerField(blank=True, null=True)),
                ("minuto_fin", models.PositiveIntegerField(blank=True, null=True)),
                ("finalizada_en", models.DateTimeField(blank=True, null=True)),
                ("duracion_segundos", models.PositiveIntegerField(blank=True, null=True)),
                ("confirmada", models.BooleanField(default=False)),
                ("corregida_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incidencias_regla_edad_corregidas", to=settings.AUTH_USER_MODEL)),
                ("creada_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incidencias_regla_edad_creadas", to=settings.AUTH_USER_MODEL)),
                ("equipo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="incidencias_reglas_edad", to="torneos.equipo")),
                ("partido", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="incidencias_reglas_edad", to="torneos.partido")),
                ("sustitucion_inicio", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incidencias_reglas_edad", to="torneos.sustitucionpartido")),
            ],
            options={
                "ordering": ["-iniciada_en", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="incidenciareglaedad",
            index=models.Index(fields=["partido", "equipo", "estado"], name="inc_regla_part_eq_estado"),
        ),
    ]
