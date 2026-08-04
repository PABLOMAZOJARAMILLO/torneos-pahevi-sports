from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("torneos", "0062_torneo_canchas_habilitadas_alter_torneo_estado")]

    operations = [
        migrations.AlterField(
            model_name="partido",
            name="periodo_en_vivo",
            field=models.CharField(blank=True, choices=[("PT", "Primer tiempo"), ("ET", "Entretiempo"), ("ST", "Segundo tiempo"), ("PEN", "Tanda de penales"), ("FIN", "Finalizado")], default="PT", max_length=5),
        ),
        migrations.CreateModel(
            name="CobroPenal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("orden", models.PositiveIntegerField()),
                ("convertido", models.BooleanField(default=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("equipo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cobros_penales", to="torneos.equipo")),
                ("jugador", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cobros_penales", to="torneos.jugador")),
                ("partido", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cobros_penales", to="torneos.partido")),
            ],
            options={"ordering": ["orden", "id"]},
        ),
        migrations.AddConstraint(
            model_name="cobropenal",
            constraint=models.UniqueConstraint(fields=("partido", "orden"), name="cobro_penal_orden_unico_partido"),
        ),
    ]
