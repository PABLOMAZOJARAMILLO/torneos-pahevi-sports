from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("torneos", "0040_remove_jugador_municipio"),
    ]

    operations = [
        migrations.AddField(
            model_name="partido",
            name="planilleros",
            field=models.ManyToManyField(
                blank=True,
                related_name="partidos_planillero",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Planilleros autorizados",
            ),
        ),
    ]
