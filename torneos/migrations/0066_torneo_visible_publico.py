from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0065_equipo_telefono_administrador_app"),
    ]

    operations = [
        migrations.AddField(
            model_name="torneo",
            name="visible_publico",
            field=models.BooleanField(
                default=True,
                help_text="Desactiva esta opción para ocultar el torneo del portal y de los enlaces públicos.",
                verbose_name="Visible para el público",
            ),
        ),
    ]
