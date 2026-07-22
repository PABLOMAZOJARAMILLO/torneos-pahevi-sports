from django.db import migrations, models

import torneos.models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0059_equipo_fotos_cuerpo_tecnico"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipo",
            name="foto_delegado",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=torneos.models.ruta_foto_cuerpo_tecnico,
                verbose_name="Foto delegado",
            ),
        ),
    ]
