from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("torneos", "0068_categoria_control_reemplazos_reemplazojugador"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipo",
            name="cedula_dt",
            field=models.CharField(blank=True, max_length=30, null=True, verbose_name="Cédula DT"),
        ),
        migrations.AddField(
            model_name="equipo",
            name="cedula_at",
            field=models.CharField(blank=True, max_length=30, null=True, verbose_name="Cédula AT"),
        ),
        migrations.AddField(
            model_name="equipo",
            name="auxiliar_campo",
            field=models.CharField(blank=True, max_length=150, null=True, verbose_name="Auxiliar de campo (AC)"),
        ),
        migrations.AddField(
            model_name="equipo",
            name="cedula_ac",
            field=models.CharField(blank=True, max_length=30, null=True, verbose_name="Cédula AC"),
        ),
        migrations.AddField(
            model_name="equipo",
            name="telefono_ac",
            field=models.CharField(blank=True, max_length=30, null=True, verbose_name="Celular AC"),
        ),
    ]
