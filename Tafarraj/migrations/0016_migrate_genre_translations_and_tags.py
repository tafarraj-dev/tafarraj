from django.db import migrations
from django.utils.text import slugify

MERGE_MAP = {
    237: 161,  # Adolescence/Teen -> Youth
    162: 209,  # Life -> Slice of Life
}

GENRE_ENGLISH = {
    156: 'Comedy', 157: 'Action', 158: 'Adventure', 160: 'Drama',
    161: 'Youth', 164: 'Military', 167: 'Romance', 170: 'Fantasy',
    171: 'Thriller', 172: 'Crime', 173: 'Melodrama', 174: 'Horror',
    175: 'Psychological', 176: 'Mystery', 177: 'Wuxia', 178: 'Family',
    180: 'Medical', 181: 'Political', 182: 'Law', 183: 'Historical',
    185: 'Sci-Fi', 187: 'Supernatural', 188: 'Business', 189: 'Sports',
    193: 'Documentary', 195: 'School', 198: 'Sitcom', 205: 'Friendship',
    209: 'Slice of Life', 210: 'Time Travel', 212: 'Music', 213: 'War',
    218: 'Food', 219: 'Travel', 233: 'Tragedy',
}

TAG_ENGLISH = {
    192: 'Revenge', 196: 'Adapted From Manga', 200: 'Realistic',
    204: 'Humane', 211: 'Investigation', 214: 'Black Comedy',
    217: 'Competition', 226: 'Web Drama', 227: 'Idol',
    229: 'Entertainment', 231: 'Police', 232: 'Office',
    235: 'Dating', 236: 'Bullying', 239: 'Era',
    241: 'Shopping', 242: 'Fashion', 256: 'Espionage',
}


def migrate_forward(apps, schema_editor):
    Genre = apps.get_model('Tafarraj', 'Genre')
    Tag = apps.get_model('Tafarraj', 'Tag')

    # 1. Merge duplicate genre pairs
    for drop_id, keep_id in MERGE_MAP.items():
        try:
            drop_genre = Genre.objects.get(id=drop_id)
            keep_genre = Genre.objects.get(id=keep_id)
        except Genre.DoesNotExist:
            continue
        for drama in drop_genre.drama_set.all():
            drama.genres.add(keep_genre)
            drama.genres.remove(drop_genre)
        drop_genre.delete()

    # 2. Translate remaining genres: English into name, slug from English
    for genre_id, english_name in GENRE_ENGLISH.items():
        try:
            g = Genre.objects.get(id=genre_id)
        except Genre.DoesNotExist:
            continue
        g.name = english_name
        g.slug = slugify(english_name, allow_unicode=True)
        g.save()

    # 3. Move reclassified rows from Genre into Tag, preserving Arabic, reattaching dramas
    for genre_id, english_name in TAG_ENGLISH.items():
        try:
            g = Genre.objects.get(id=genre_id)
        except Genre.DoesNotExist:
            continue
        tag, _ = Tag.objects.get_or_create(
            name=english_name,
            defaults={
                'name_arabic': g.name_arabic,
                'slug': slugify(english_name, allow_unicode=True),
            },
        )
        for drama in g.drama_set.all():
            drama.tags.add(tag)
        g.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('Tafarraj', '0015_tag_name_arabic'),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrations.RunPython.noop),
    ]