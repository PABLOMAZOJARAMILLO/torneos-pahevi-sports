from datetime import date

from django.db import migrations, models
import django.db.models.deletion


def columna_existe(connection, tabla, columna):
    with connection.cursor() as cursor:
        columnas = connection.introspection.get_table_description(cursor, tabla)
    return columna in {item.name for item in columnas}


def asegurar_esquema_torneo(apps, schema_editor):
    connection = schema_editor.connection
    tablas = set(connection.introspection.table_names())

    if "torneos_torneo" not in tablas:
        Torneo = apps.get_model("torneos", "Torneo")
        schema_editor.create_model(Torneo)

    with connection.cursor() as cursor:
        if not columna_existe(connection, "torneos_categoria", "torneo_id"):
            if connection.vendor == "postgresql":
                cursor.execute('ALTER TABLE "torneos_categoria" ADD COLUMN IF NOT EXISTS "torneo_id" bigint NULL')
            else:
                cursor.execute('ALTER TABLE "torneos_categoria" ADD COLUMN "torneo_id" bigint NULL')

        if not columna_existe(connection, "torneos_documento", "torneo_id"):
            if connection.vendor == "postgresql":
                cursor.execute('ALTER TABLE "torneos_documento" ADD COLUMN IF NOT EXISTS "torneo_id" bigint NULL')
            else:
                cursor.execute('ALTER TABLE "torneos_documento" ADD COLUMN "torneo_id" bigint NULL')


def crear_torneo_inicial(apps, schema_editor):
    Torneo = apps.get_model("torneos", "Torneo")
    Categoria = apps.get_model("torneos", "Categoria")
    Documento = apps.get_model("torneos", "Documento")

    torneo, _ = Torneo.objects.get_or_create(
        nombre="Torneo IMCRED",
        defaults={
            "descripcion": "Torneo inicial creado automaticamente para organizar la informacion existente.",
            "fecha_inicio": date(2026, 1, 1),
            "estado": "ACTIVO",
        },
    )

    Categoria.objects.filter(torneo__isnull=True).update(torneo=torneo)
    Documento.objects.filter(torneo__isnull=True).update(torneo=torneo)


def deshacer_torneo_inicial(apps, schema_editor):
    Categoria = apps.get_model("torneos", "Categoria")
    Documento = apps.get_model("torneos", "Documento")

    Categoria.objects.update(torneo=None)
    Documento.objects.update(torneo=None)


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0022_alter_documento_tipo"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(asegurar_esquema_torneo, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="Torneo",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("nombre", models.CharField(max_length=150, verbose_name="Nombre del torneo")),
                        ("descripcion", models.TextField(blank=True, null=True, verbose_name="Descripci\u00f3n")),
                        ("fecha_inicio", models.DateField(verbose_name="Fecha de inicio")),
                        ("fecha_fin", models.DateField(blank=True, null=True, verbose_name="Fecha de finalizaci\u00f3n")),
                        ("estado", models.CharField(choices=[("ACTIVO", "Activo"), ("FINALIZADO", "Finalizado"), ("SUSPENDIDO", "Suspendido")], default="ACTIVO", max_length=20, verbose_name="Estado")),
                        ("creado_en", models.DateTimeField(auto_now_add=True, verbose_name="Creado en")),
                    ],
                    options={
                        "verbose_name": "Torneo",
                        "verbose_name_plural": "Torneos",
                        "ordering": ["-fecha_inicio"],
                    },
                ),
                migrations.AddField(
                    model_name="categoria",
                    name="torneo",
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="categorias", to="torneos.torneo"),
                ),
                migrations.AddField(
                    model_name="documento",
                    name="torneo",
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="documentos", to="torneos.torneo"),
                ),
            ],
        ),
        migrations.RunPython(crear_torneo_inicial, deshacer_torneo_inicial),
    ]
