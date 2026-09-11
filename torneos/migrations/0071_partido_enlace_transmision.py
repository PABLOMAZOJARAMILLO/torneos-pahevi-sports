from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("torneos", "0070_torneo_habilitar_auxiliar_campo"),
    ]

    operations = [
        migrations.AddField(
            model_name="partido",
            name="enlace_transmision",
            field=models.URLField(
                blank=True,
                default="",
                help_text="Enlace externo de YouTube, Facebook u otra plataforma.",
                max_length=500,
                verbose_name="Enlace de transmisión",
            ),
        ),
    ]
