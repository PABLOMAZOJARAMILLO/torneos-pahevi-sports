from django.db import migrations, models
import django.db.models.deletion


def crear_reglas_senior_master(apps, schema_editor):
    Categoria = apps.get_model('torneos', 'Categoria')
    ReglaEdadCategoria = apps.get_model('torneos', 'ReglaEdadCategoria')
    for categoria in Categoria.objects.filter(nombre__iexact='Senior Master'):
        reglas = [
            {'etiqueta': '+40', 'edad_minima': 40, 'edad_maxima': 44, 'minimo_titulares': 4, 'orden': 1},
            {'etiqueta': '+45', 'edad_minima': 45, 'edad_maxima': 49, 'minimo_titulares': 4, 'orden': 2},
            {'etiqueta': '+50', 'edad_minima': 50, 'edad_maxima': None, 'minimo_titulares': 3, 'orden': 3},
        ]
        for regla in reglas:
            ReglaEdadCategoria.objects.get_or_create(categoria=categoria, etiqueta=regla['etiqueta'], defaults=regla)


class Migration(migrations.Migration):

    dependencies = [
        ('torneos', '0037_jugador_cedula_por_equipo'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReglaEdadCategoria',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('etiqueta', models.CharField(max_length=20, verbose_name='Etiqueta')),
                ('edad_minima', models.PositiveIntegerField(verbose_name='Edad minima')),
                ('edad_maxima', models.PositiveIntegerField(blank=True, null=True, verbose_name='Edad maxima')),
                ('minimo_titulares', models.PositiveIntegerField(default=0, verbose_name='Minimo en cancha')),
                ('orden', models.PositiveIntegerField(default=0)),
                ('activa', models.BooleanField(default=True)),
                ('categoria', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reglas_edad', to='torneos.categoria')),
            ],
            options={
                'verbose_name': 'Regla de edad',
                'verbose_name_plural': 'Reglas de edad',
                'ordering': ['categoria__nombre', 'orden', 'edad_minima'],
            },
        ),
        migrations.RunPython(crear_reglas_senior_master, migrations.RunPython.noop),
    ]
