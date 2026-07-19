import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0056_visitapublicadiaria"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EntregaAlineacionPartido",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enviada_en", models.DateTimeField(auto_now_add=True)),
                ("enviada_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="alineaciones_definitivas_enviadas", to=settings.AUTH_USER_MODEL)),
                ("equipo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alineaciones_definitivas", to="torneos.equipo")),
                ("partido", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alineaciones_definitivas", to="torneos.partido")),
            ],
            options={
                "verbose_name": "Entrega definitiva de alineación",
                "verbose_name_plural": "Entregas definitivas de alineación",
                "constraints": [models.UniqueConstraint(fields=("partido", "equipo"), name="alineacion_definitiva_unica_equipo")],
            },
        ),
    ]
