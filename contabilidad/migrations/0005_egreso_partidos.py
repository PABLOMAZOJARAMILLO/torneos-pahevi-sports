from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contabilidad", "0004_configuracion_dia_limite_mensualidad_and_more"),
        ("torneos", "0066_torneo_visible_publico"),
    ]

    operations = [
        migrations.AddField(
            model_name="egreso",
            name="partidos",
            field=models.ManyToManyField(
                blank=True,
                related_name="egresos_arbitraje",
                to="torneos.partido",
                verbose_name="Partidos asociados",
            ),
        ),
    ]
