from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('torneos', '0039_foraneos'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='jugador',
            name='municipio',
        ),
    ]
