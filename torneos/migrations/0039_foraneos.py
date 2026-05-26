from django.db import migrations, models


def activar_control_foraneos(apps, schema_editor):
    Categoria = apps.get_model('torneos', 'Categoria')
    Categoria.objects.filter(nombre__iexact='Senior Master').update(
        controlar_foraneos=True,
        porcentaje_minimo_foraneos=50,
    )
    Categoria.objects.filter(nombre__iexact='Plus 50').update(
        controlar_foraneos=True,
        porcentaje_minimo_foraneos=50,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('torneos', '0038_reglaedadcategoria'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoria',
            name='controlar_foraneos',
            field=models.BooleanField(default=False, verbose_name='Controlar foráneos'),
        ),
        migrations.AddField(
            model_name='categoria',
            name='porcentaje_minimo_foraneos',
            field=models.PositiveIntegerField(default=50, verbose_name='Porcentaje mínimo fase 1 foráneos'),
        ),
        migrations.AddField(
            model_name='jugador',
            name='es_foraneo',
            field=models.BooleanField(default=False, verbose_name='Foráneo'),
        ),
        migrations.AddField(
            model_name='jugador',
            name='municipio',
            field=models.CharField(blank=True, max_length=120, null=True, verbose_name='Municipio'),
        ),
        migrations.RunPython(activar_control_foraneos, migrations.RunPython.noop),
    ]
