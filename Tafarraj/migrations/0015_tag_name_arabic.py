from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('Tafarraj', '0014_tag_drama_aired_end_date_drama_aired_start_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tag',
            name='name_arabic',
            field=models.CharField(max_length=100, blank=True),
        ),
    ]