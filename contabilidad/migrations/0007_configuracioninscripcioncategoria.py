from django.db import migrations, models
import django.db.models.deletion


def migrar_valores_existentes(apps, schema_editor):
    CuentaEquipo = apps.get_model("contabilidad", "CuentaEquipo")
    ConfiguracionCategoria = apps.get_model("contabilidad", "ConfiguracionInscripcionCategoria")
    categorias = CuentaEquipo.objects.values_list("torneo_id", "categoria_id").distinct()
    for torneo_id, categoria_id in categorias.iterator():
        valores = list(
            CuentaEquipo.objects.filter(torneo_id=torneo_id, categoria_id=categoria_id)
            .values_list("valor_inscripcion", flat=True)
        )
        if not valores:
            continue
        valor = max(set(valores), key=lambda item: (valores.count(item), item))
        ConfiguracionCategoria.objects.create(
            torneo_id=torneo_id, categoria_id=categoria_id, valor=valor,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("contabilidad", "0006_ingreso_partidos"),
        ("torneos", "0066_torneo_visible_publico"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfiguracionInscripcionCategoria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("valor", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("categoria", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="contabilidad_inscripcion_configurada", to="torneos.categoria")),
                ("torneo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contabilidad_inscripciones_configuradas", to="torneos.torneo")),
            ],
            options={"ordering": ["categoria__nombre"]},
        ),
        migrations.RunPython(migrar_valores_existentes, migrations.RunPython.noop),
    ]
