from django.db import migrations, models
import torneos.models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0058_incidenciareglaedad"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipo",
            name="foto_asistente_tecnico",
            field=models.ImageField(blank=True, null=True, upload_to=torneos.models.ruta_foto_cuerpo_tecnico, verbose_name="Foto asistente técnico"),
        ),
        migrations.AddField(
            model_name="equipo",
            name="foto_director_tecnico",
            field=models.ImageField(blank=True, null=True, upload_to=torneos.models.ruta_foto_cuerpo_tecnico, verbose_name="Foto director técnico"),
        ),
    ]
