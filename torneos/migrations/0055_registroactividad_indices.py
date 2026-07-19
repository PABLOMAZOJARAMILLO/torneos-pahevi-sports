from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("torneos", "0054_alter_documento_tipo"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="registroactividad",
            index=models.Index(fields=["usuario", "-creado_en"], name="actividad_usuario_fecha_idx"),
        ),
        migrations.AddIndex(
            model_name="registroactividad",
            index=models.Index(fields=["torneo", "-creado_en"], name="actividad_torneo_fecha_idx"),
        ),
        migrations.AddIndex(
            model_name="registroactividad",
            index=models.Index(fields=["accion", "-creado_en"], name="actividad_accion_fecha_idx"),
        ),
    ]
