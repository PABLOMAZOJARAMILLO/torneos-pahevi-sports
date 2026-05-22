import django.db.models.deletion
import torneos.models
from django.db import migrations, models


def migrar_organizadores(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Torneo = apps.get_model("torneos", "Torneo")
    Organizador = apps.get_model("torneos", "Organizador")

    for torneo in Torneo.objects.all():
        usuario_id = torneo.organizador_id
        if not usuario_id:
            continue

        usuario = User.objects.filter(id=usuario_id).first()
        if not usuario:
            continue

        nombre_completo = f"{usuario.first_name or ''} {usuario.last_name or ''}".strip()
        nombre = (nombre_completo or usuario.username or f"Organizador {usuario_id}").strip()
        organizador, _ = Organizador.objects.get_or_create(
            nombre=nombre,
            defaults={"activo": True},
        )

        if getattr(torneo, "logo_portada", None) and not organizador.logo:
            organizador.logo = torneo.logo_portada
            organizador.save(update_fields=["logo"])

        torneo.organizador_entidad_id = organizador.id
        torneo.save(update_fields=["organizador_entidad"])


def revertir_organizadores(apps, schema_editor):
    Torneo = apps.get_model("torneos", "Torneo")
    Torneo.objects.update(organizador_entidad=None)


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0031_renombrar_torneo_inicial_pahevi"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organizador",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=150, unique=True, verbose_name="Nombre del organizador")),
                ("descripcion", models.TextField(blank=True, null=True, verbose_name="DescripciÃ³n")),
                ("logo", models.ImageField(blank=True, null=True, upload_to=torneos.models.ruta_logo_organizador, verbose_name="Logo del organizador")),
                ("portada", models.ImageField(blank=True, null=True, upload_to=torneos.models.ruta_portada_organizador, verbose_name="Portada del organizador")),
                ("activo", models.BooleanField(default=True, verbose_name="Activo")),
                ("creado_en", models.DateTimeField(auto_now_add=True, verbose_name="Creado en")),
            ],
            options={
                "verbose_name": "Organizador",
                "verbose_name_plural": "Organizadores",
                "ordering": ["nombre"],
            },
        ),
        migrations.AddField(
            model_name="torneo",
            name="organizador_entidad",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="torneos_temp", to="torneos.organizador", verbose_name="Organizador"),
        ),
        migrations.RunPython(migrar_organizadores, revertir_organizadores),
        migrations.RemoveField(
            model_name="torneo",
            name="organizador",
        ),
        migrations.RenameField(
            model_name="torneo",
            old_name="organizador_entidad",
            new_name="organizador",
        ),
        migrations.AlterField(
            model_name="torneo",
            name="organizador",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="torneos", to="torneos.organizador", verbose_name="Organizador"),
        ),
    ]
