from django.db import migrations


def renombrar_torneo_inicial(apps, schema_editor):
    Torneo = apps.get_model("torneos", "Torneo")
    Torneo.objects.filter(nombre__iexact="Torneo IMCRED").update(
        nombre="TORNEOS PAHEVI SPORTS",
        lema="Tu app de torneos",
    )


def revertir_torneo_inicial(apps, schema_editor):
    Torneo = apps.get_model("torneos", "Torneo")
    Torneo.objects.filter(nombre__iexact="TORNEOS PAHEVI SPORTS").update(
        nombre="Torneo IMCRED",
        lema=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0030_torneo_imagen_central_torneo_lema_and_more"),
    ]

    operations = [
        migrations.RunPython(renombrar_torneo_inicial, revertir_torneo_inicial),
    ]
