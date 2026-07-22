from django.db import migrations, models

import torneos.models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0060_equipo_foto_delegado"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipo",
            name="administrador_app",
            field=models.CharField(blank=True, max_length=150, null=True, verbose_name="Admin App"),
        ),
        migrations.AddField(
            model_name="equipo",
            name="foto_administrador_app",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=torneos.models.ruta_foto_cuerpo_tecnico,
                verbose_name="Foto Admin App",
            ),
        ),
    ]
