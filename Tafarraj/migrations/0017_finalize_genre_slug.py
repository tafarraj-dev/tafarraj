from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('Tafarraj', '0016_migrate_genre_translations_and_tags'),
    ]

    operations = [
        migrations.AlterField(
            model_name='genre',
            name='slug',
            field=models.SlugField(max_length=60, unique=True, blank=True, allow_unicode=True),
        ),
    ]