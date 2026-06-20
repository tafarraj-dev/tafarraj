"""
CLEAN SCRIPT — Run as management command:
    python manage.py clean_turkish

Fetches each Turkish drama's TMDB type and deletes anything that isn't
an actual drama (reality shows, talk shows, news, game shows, etc.)

Safe: prints everything it plans to delete BEFORE deleting.
Asks for confirmation first.
"""

from django.core.management.base import BaseCommand
from Tafarraj.models import Drama
from Tafarraj.utils import TMDB_API_KEY, TMDB_BASE_URL
import requests
import time

# TMDB genre IDs that are NOT dramas — anything with ONLY these genres gets deleted
NON_DRAMA_GENRE_IDS = {
    10763,  # News
    10764,  # Reality
    10767,  # Talk Show
    10766,  # Soap (debatable — keep if you want)
}

# TMDB types that are definitely not dramas
NON_DRAMA_TYPES = {
    'Reality',
    'Talk Show',
    'News',
    'Game Show',
}


class Command(BaseCommand):
    help = 'Delete non-drama Turkish shows from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually delete — without this flag it only shows what would be deleted (dry run)',
        )

    def handle(self, *args, **options):
        dry_run = not options['confirm']
        turkish = Drama.objects.filter(country='turkish')
        total = turkish.count()

        if dry_run:
            self.stdout.write(f'\n🔍 DRY RUN — nothing will be deleted')
            self.stdout.write(f'Run with --confirm to actually delete\n')
        else:
            self.stdout.write(f'\n🗑  LIVE RUN — will delete non-dramas\n')

        self.stdout.write(f'Checking {total} Turkish entries...\n')

        to_delete = []
        to_keep   = []
        failed    = []

        for i, drama in enumerate(turkish, 1):
            self.stdout.write(f'[{i}/{total}] Checking: {drama.title}')

            if not drama.tmdb_id:
                self.stdout.write(f'  ⚠ No TMDB ID — keeping')
                to_keep.append((drama, 'no tmdb_id'))
                continue

            try:
                resp = requests.get(
                    f"{TMDB_BASE_URL}/tv/{drama.tmdb_id}",
                    params={'api_key': TMDB_API_KEY},
                    timeout=10
                )
                if resp.status_code != 200:
                    self.stdout.write(f'  ⚠ TMDB error {resp.status_code} — keeping to be safe')
                    failed.append(drama.title)
                    continue

                detail = resp.json()

                tmdb_type   = detail.get('type', '')
                tmdb_genres = {g['id'] for g in detail.get('genres', [])}
                name        = detail.get('name', drama.title)

                # Delete if type is non-drama
                if tmdb_type in NON_DRAMA_TYPES:
                    reason = f'type={tmdb_type}'
                    self.stdout.write(f'  ❌ WILL DELETE — {reason}: {name}')
                    to_delete.append((drama, reason))
                    time.sleep(0.2)
                    continue

                # Delete if ALL genres are non-drama genres (and has no drama genre)
                has_drama_genre = bool(tmdb_genres - NON_DRAMA_GENRE_IDS)
                if tmdb_genres and not has_drama_genre:
                    reason = f'only non-drama genres: {tmdb_genres}'
                    self.stdout.write(f'  ❌ WILL DELETE — {reason}: {name}')
                    to_delete.append((drama, reason))
                    time.sleep(0.2)
                    continue

                self.stdout.write(f'  ✅ KEEP — type={tmdb_type}')
                to_keep.append((drama, tmdb_type))

            except Exception as e:
                self.stdout.write(f'  ⚠ Error: {e} — keeping to be safe')
                failed.append(drama.title)

            time.sleep(0.25)

        # --- Summary ---
        self.stdout.write(f'\n{"="*55}')
        self.stdout.write(f'CLEAN SUMMARY')
        self.stdout.write(f'{"="*55}')
        self.stdout.write(f'Total checked : {total}')
        self.stdout.write(f'To keep       : {len(to_keep)}')
        self.stdout.write(f'To delete     : {len(to_delete)}')
        self.stdout.write(f'Failed checks : {len(failed)}')

        if to_delete:
            self.stdout.write(f'\nWILL DELETE:')
            for drama, reason in to_delete:
                self.stdout.write(f'  🗑  [{drama.tmdb_id}] {drama.title} — {reason}')

        if not dry_run and to_delete:
            ids_to_delete = [d.id for d, _ in to_delete]
            Drama.objects.filter(id__in=ids_to_delete).delete()
            self.stdout.write(self.style.SUCCESS(f'\n✅ Deleted {len(to_delete)} non-drama shows'))
        elif dry_run:
            self.stdout.write(f'\n⚠  Dry run — run with --confirm to delete these {len(to_delete)} shows')