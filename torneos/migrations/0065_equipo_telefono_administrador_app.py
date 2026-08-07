from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("torneos", "0064_partido_equipo_inicia_penales"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipo",
            name="telefono_administrador_app",
            field=models.CharField(
                blank=True,
                max_length=30,
                null=True,
                verbose_name="Celular Admin App",
            ),
        ),
    ]
