from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0053_equipo_delegado_puede_cargar_fotos_jugadores_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="documento",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("REGLAMENTO", "Reglamento"),
                    ("RESOLUCION", "Resolución"),
                    ("DEMANDA", "Demanda"),
                    ("COMUNICADO", "Comunicado"),
                    ("PLANILLA_JUEGO", "Planilla de juego"),
                    ("OTRO", "Otro"),
                ],
                max_length=20,
                verbose_name="Tipo",
            ),
        ),
    ]
