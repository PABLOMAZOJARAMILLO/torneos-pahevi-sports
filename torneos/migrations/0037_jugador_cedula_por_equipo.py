from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0036_gol_minuto_tarjeta_minuto"),
    ]

    operations = [
        migrations.AlterField(
            model_name="jugador",
            name="cedula",
            field=models.CharField(max_length=30, verbose_name="Cédula"),
        ),
        migrations.AddConstraint(
            model_name="jugador",
            constraint=models.UniqueConstraint(
                fields=("equipo", "cedula"),
                name="jugador_unico_por_equipo_cedula",
            ),
        ),
    ]
