"""
FETCH SCRIPT — Run as management command:
    python manage.py fetch_turkish

Fetches Turkish dramas only (2025 & 2026) from TMDB.
- Uses original_name (real Turkish title) instead of TMDB's English alt-title
- Prefers tr-TR overview/poster, falls back to en-US only if tr-TR is empty
- Filters to drama genre + Turkish original language only
- Safe date parsing (won't crash the whole run on unannounced shows)
- Saves thumbnail_url (URL only, no download)
- Maps genres to YOUR existing genres — never creates new ones
- Updates existing dramas, adds new ones
"""

from django.core.management.base import BaseCommand
from Tafarraj.models import Drama, Genre
from Tafarraj.utils import translate_to_arabic, TMDB_API_KEY, TMDB_BASE_URL
import requests
import time

# Maps TMDB genre ID → your existing Genre IDs in the database
# Edit these IDs if they ever change
TMDB_TO_YOUR_GENRE_IDS = {
    18:    [160],        # Drama        → درامي
    35:    [156],        # Comedy       → كوميدي
    80:    [172],        # Crime        → جريمة
    9648:  [176],        # Mystery      → غموض
    10751: [178],        # Family       → عائلي
    10759: [157, 158],   # Action&Adv   → أكشن + مغامرات
    10762: [161],        # Kids         → شبابي
    10765: [185],        # Sci-Fi       → خيال علمي
    10766: [173],        # Soap         → ميلودراما
    10768: [213, 181],   # War & Pol    → حربي + سياسي
    37:    [183],        # History      → تاريخي
    99:    [193],        # Documentary  → وثائقي
    10763: [],           # News         → skip
    10764: [],           # Reality      → skip
    10767: [],           # Talk Show    → skip
}


def load_genres():
    return {g.id: g for g in Genre.objects.all()}


def get_matched_genres(tmdb_genre_ids, genre_map):
    matched = []
    for tmdb_id in tmdb_genre_ids:
        for db_id in TMDB_TO_YOUR_GENRE_IDS.get(tmdb_id, []):
            genre = genre_map.get(db_id)
            if genre and genre not in matched:
                matched.append(genre)
    return matched


def safe_year(date_str, fallback_year):
    """Parse first_air_date safely — never crash the run on missing/odd dates."""
    if date_str and len(date_str) >= 4:
        try:
            return int(date_str[:4])
        except ValueError:
            pass
    return fallback_year


class Command(BaseCommand):
    help = 'Fetch Turkish dramas 2025 & 2026 from TMDB — drama only, proper data'

    def handle(self, *args, **options):
        genre_map = load_genres()
        self.stdout.write(f'Loaded {len(genre_map)} genres from DB\n')

        added = updated = skipped = 0

        for year in [2025, 2026]:
            self.stdout.write(f'\n{"="*55}')
            self.stdout.write(f'FETCHING TURKISH DRAMAS — {year}')
            self.stdout.write(f'{"="*55}\n')

            for page in range(1, 21):
                self.stdout.write(f'--- Page {page}/20 ---')

                try:
                    resp = requests.get(
                        f"{TMDB_BASE_URL}/discover/tv",
                        params={
                            'api_key':               TMDB_API_KEY,
                            'language':              'tr-TR',   # real Turkish metadata by default
                            'with_origin_country':   'TR',
                            'with_original_language': 'tr',     # excludes non-Turkish-language shows tagged TR
                            'with_genres':           '18',       # Drama only
                            'without_genres':        '10763,10764,10767,99',  # No news/reality/talk/doc
                            'first_air_date.gte':    f'{year}-01-01',
                            'first_air_date.lte':    f'{year}-12-31',
                            'sort_by':               'popularity.desc',
                            'page':                  page,
                        },
                        timeout=10
                    )
                except Exception as e:
                    self.stdout.write(f'Request failed: {e} — stopping page loop')
                    break

                if resp.status_code != 200:
                    self.stdout.write(f'API error: {resp.status_code} — stopping')
                    break

                results = resp.json().get('results', [])
                if not results:
                    self.stdout.write('No more results')
                    break

                for show in results:
                    tmdb_id = show.get('id')
                    # Prefer the real Turkish title, not TMDB's (often bad) English alt-title
                    original_name = show.get('original_name', '')
                    display_name = original_name or show.get('name', '')

                    # --- Fetch full detail in Turkish first ---
                    try:
                        detail_resp = requests.get(
                            f"{TMDB_BASE_URL}/tv/{tmdb_id}",
                            params={'api_key': TMDB_API_KEY, 'language': 'tr-TR'},
                            timeout=10
                        )
                        detail = detail_resp.json()
                    except Exception as e:
                        self.stdout.write(f'  ⚠ Detail fetch failed for {display_name}: {e}')
                        skipped += 1
                        continue

                    # --- Skip non-drama types ---
                    tmdb_type = detail.get('type', '')
                    if tmdb_type in ('Reality', 'Talk Show', 'News', 'Game Show'):
                        self.stdout.write(f'  ⏭ SKIP ({tmdb_type}): {display_name}')
                        skipped += 1
                        continue

                    overview = (detail.get('overview') or '').strip()
                    poster_path = detail.get('poster_path')

                    # --- Fallback to English ONLY if Turkish came back empty ---
                    if not overview or not poster_path:
                        try:
                            en_resp = requests.get(
                                f"{TMDB_BASE_URL}/tv/{tmdb_id}",
                                params={'api_key': TMDB_API_KEY, 'language': 'en-US'},
                                timeout=10
                            )
                            en_detail = en_resp.json()
                            if not overview:
                                overview = (en_detail.get('overview') or '').strip()
                            if not poster_path:
                                poster_path = en_detail.get('poster_path')
                        except Exception:
                            pass

                    thumbnail_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                    new_episodes  = detail.get('number_of_episodes') or 0
                    new_status    = 'completed' if detail.get('status') == 'Ended' else 'ongoing'
                    run_times     = detail.get('episode_run_time', [])
                    new_duration  = run_times[0] if run_times else 45

                    # Genres — map to YOUR existing ones only
                    tmdb_genre_ids = [g['id'] for g in detail.get('genres', [])]
                    matched_genres = get_matched_genres(tmdb_genre_ids, genre_map)

                    # --- Update existing (by TMDB ID) ---
                    drama = Drama.objects.filter(tmdb_id=tmdb_id).first()
                    if drama:
                        drama.title             = display_name
                        drama.title_original    = original_name
                        drama.total_episodes    = new_episodes
                        drama.status            = new_status
                        drama.episode_duration  = new_duration
                        if thumbnail_url:
                            drama.thumbnail_url = thumbnail_url
                        if overview:
                            drama.description        = overview
                            drama.description_arabic = translate_to_arabic(overview)
                        drama.save()
                        if matched_genres:
                            drama.genres.set(matched_genres)
                        self.stdout.write(f'  🔄 UPDATED: {display_name}')
                        updated += 1
                        time.sleep(0.25)
                        continue

                    # --- Update existing (by original title, in case it predates this fix) ---
                    drama = Drama.objects.filter(title_original=original_name).exclude(title_original='').first()
                    if drama:
                        drama.tmdb_id           = tmdb_id
                        drama.title             = display_name
                        drama.total_episodes    = new_episodes
                        drama.status            = new_status
                        drama.episode_duration  = new_duration
                        if thumbnail_url:
                            drama.thumbnail_url = thumbnail_url
                        if overview:
                            drama.description        = overview
                            drama.description_arabic = translate_to_arabic(overview)
                        drama.save()
                        if matched_genres:
                            drama.genres.set(matched_genres)
                        self.stdout.write(f'  🔄 UPDATED (title): {display_name}')
                        updated += 1
                        time.sleep(0.25)
                        continue

                    # --- Create new ---
                    drama = Drama.objects.create(
                        tmdb_id            = tmdb_id,
                        title              = display_name,
                        title_arabic       = translate_to_arabic(display_name),
                        title_original     = original_name,
                        description        = overview,
                        description_arabic = translate_to_arabic(overview) if overview else '',
                        country            = 'turkish',
                        release_year       = safe_year(show.get('first_air_date'), year),
                        total_episodes     = new_episodes,
                        episode_duration   = new_duration,
                        status             = new_status,
                        thumbnail_url      = thumbnail_url,
                    )
                    if matched_genres:
                        drama.genres.set(matched_genres)

                    self.stdout.write(self.style.SUCCESS(f'  ✅ ADDED: {display_name}'))
                    added += 1
                    time.sleep(0.25)

        self.stdout.write(self.style.SUCCESS(
            f'\n{"="*55}\n'
            f'✅ DONE\n'
            f'   Added   : {added}\n'
            f'   Updated : {updated}\n'
            f'   Skipped : {skipped}\n'
            f'{"="*55}'
        ))