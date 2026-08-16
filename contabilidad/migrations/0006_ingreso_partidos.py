from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contabilidad", "0005_egreso_partidos"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingreso",
            name="partidos",
            field=models.ManyToManyField(
                blank=True,
                related_name="ingresos_arbitraje",
                to="torneos.partido",
                verbose_name="Partidos asociados",
            ),
        ),
    ]
