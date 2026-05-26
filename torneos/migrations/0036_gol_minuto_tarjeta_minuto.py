from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0035_gol_es_autogol_gol_es_penal"),
    ]

    operations = [
        migrations.AddField(
            model_name="gol",
            name="minuto",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="Minuto"),
        ),
        migrations.AddField(
            model_name="gol",
            name="creado_en",
            field=models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name="Creado en"),
        ),
        migrations.AddField(
            model_name="tarjeta",
            name="minuto",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="Minuto"),
        ),
        migrations.AddField(
            model_name="tarjeta",
            name="creado_en",
            field=models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name="Creado en"),
        ),
        migrations.AddField(
            model_name="sustitucionpartido",
            name="creado_en",
            field=models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name="Creado en"),
        ),
    ]
