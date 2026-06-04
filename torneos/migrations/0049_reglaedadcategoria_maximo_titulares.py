from django.db import migrations, models


def actualizar_reglas_senior_master(apps, schema_editor):
    Categoria = apps.get_model("torneos", "Categoria")
    ReglaEdadCategoria = apps.get_model("torneos", "ReglaEdadCategoria")
    categorias = Categoria.objects.filter(nombre__iexact="Senior Master")
    for categoria in categorias:
        reglas = [
            {
                "etiqueta": "+40",
                "edad_minima": 40,
                "edad_maxima": 44,
                "minimo_titulares": 0,
                "maximo_titulares": 4,
                "orden": 1,
            },
            {
                "etiqueta": "+45",
                "edad_minima": 45,
                "edad_maxima": 49,
                "minimo_titulares": 4,
                "maximo_titulares": None,
                "orden": 2,
            },
            {
                "etiqueta": "+50",
                "edad_minima": 50,
                "edad_maxima": None,
                "minimo_titulares": 3,
                "maximo_titulares": None,
                "orden": 3,
            },
        ]
        for datos in reglas:
            regla, _ = ReglaEdadCategoria.objects.get_or_create(
                categoria=categoria,
                etiqueta=datos["etiqueta"],
                defaults=datos,
            )
            for campo, valor in datos.items():
                setattr(regla, campo, valor)
            regla.activa = True
            regla.save()


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0048_adminorganizador_puede_descargar_planillas_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="reglaedadcategoria",
            name="maximo_titulares",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="Maximo en cancha"),
        ),
        migrations.RunPython(actualizar_reglas_senior_master, migrations.RunPython.noop),
    ]
