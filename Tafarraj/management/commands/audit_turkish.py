"""
AUDIT SCRIPT — Run in Django shell:
    python manage.py shell < audit_turkish.py
    
Shows a full report of what's wrong with each Turkish drama.
Makes NO changes to the database.
"""

from Tafarraj.models import Drama

turkish = Drama.objects.filter(country='turkish').prefetch_related('genres')

total             = turkish.count()
no_thumbnail      = []
no_description    = []
no_genres         = []
no_desc_no_thumb  = []
all_good          = []

for drama in turkish:
    has_thumb = bool(drama.thumbnail_url and drama.thumbnail_url.strip())
    has_desc  = bool(drama.description and drama.description.strip())
    has_genre = drama.genres.exists()

    issues = []
    if not has_thumb:  issues.append('NO THUMBNAIL')
    if not has_desc:   issues.append('NO DESCRIPTION')
    if not has_genre:  issues.append('NO GENRES')

    if not has_thumb:  no_thumbnail.append(drama)
    if not has_desc:   no_description.append(drama)
    if not has_genre:  no_genres.append(drama)
    if not has_thumb and not has_desc: no_desc_no_thumb.append(drama)
    if not issues:     all_good.append(drama)

    if issues:
        print(f"  ❌ [{drama.tmdb_id}] {drama.title} — {', '.join(issues)}")
    else:
        print(f"  ✅ [{drama.tmdb_id}] {drama.title}")

print(f"""
{'='*60}
AUDIT SUMMARY — TURKISH DRAMAS
{'='*60}
Total dramas         : {total}
✅ All good          : {len(all_good)}
❌ No thumbnail      : {len(no_thumbnail)}
❌ No description    : {len(no_description)}
❌ No genres         : {len(no_genres)}
❌ Both missing      : {len(no_desc_no_thumb)}
{'='*60}

DRAMAS WITH NO THUMBNAIL:
""")
for d in no_thumbnail:
    print(f"  [{d.tmdb_id}] {d.title}")

print(f"""
DRAMAS WITH NO DESCRIPTION:
""")
for d in no_description:
    print(f"  [{d.tmdb_id}] {d.title}")

print(f"""
DRAMAS WITH NO GENRES:
""")
for d in no_genres:
    print(f"  [{d.tmdb_id}] {d.title}")