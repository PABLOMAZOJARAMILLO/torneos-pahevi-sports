from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("torneos", "0063_cobropenal_periodo_penales")]

    operations = [
        migrations.AddField(
            model_name="partido",
            name="equipo_inicia_penales",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tandas_penales_iniciadas",
                to="torneos.equipo",
                verbose_name="Equipo que inicia la tanda",
            ),
        ),
    ]
