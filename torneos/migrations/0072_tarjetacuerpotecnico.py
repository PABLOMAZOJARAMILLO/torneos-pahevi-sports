from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("torneos", "0071_partido_enlace_transmision"),
    ]

    operations = [
        migrations.CreateModel(
            name="TarjetaCuerpoTecnico",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cargo", models.CharField(choices=[("DT", "DT"), ("AT", "AT"), ("AC", "AC"), ("DELEGADO", "Delegado"), ("ADMIN_APP", "Admin App"), ("OTRO", "Otro integrante")], max_length=20)),
                ("cargo_detalle", models.CharField(blank=True, max_length=80)),
                ("nombre", models.CharField(max_length=150)),
                ("tipo", models.CharField(choices=[("AMARILLA", "Amarilla"), ("ROJA", "Roja")], max_length=20)),
                ("minuto", models.PositiveIntegerField(blank=True, null=True)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("equipo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="torneos.equipo")),
                ("partido", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tarjetas_cuerpo_tecnico", to="torneos.partido")),
            ],
            options={
                "verbose_name": "Tarjeta del cuerpo técnico",
                "verbose_name_plural": "Tarjetas del cuerpo técnico",
            },
        ),
    ]
