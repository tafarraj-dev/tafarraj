"""
FETCH SCRIPT — Run as management command:
    python manage.py fetch_turkish

Fetches Turkish DRAMAS ONLY, years 2020-2026, from TMDB.

Changes vs the old version:
- Years: 2020-2026 (was 2025-2026 only)
- Excludes Animation (16) and Kids (10762) both at the API-filter level
  AND as a post-fetch safety check, so cartoons/kids shows stop leaking in
- Genre mapping uses your REAL Genre IDs (237-269 range)
- Matching order: tmdb_id -> (title_original + release_year) -> create new
  (release_year added to prevent remakes/reboots with the same title in a
  different year from overwriting each other)
- Tags: TMDB keywords are translated to Arabic, matched against your
  existing Tag table by name, reused if found, created if not. Attached
  with .add() only -- never removes existing tags, never duplicates.
- New separate TMDB rating fields (tmdb_rating, tmdb_vote_count,
  tmdb_popularity) -- MDL fields (mdl_rating, mdl_rank, mdl_popularity)
  are NEVER touched by this script.
"""

from django.core.management.base import BaseCommand
from django.utils.text import slugify
from Tafarraj.models import Drama, Genre, Tag
from Tafarraj.utils import translate_to_arabic, TMDB_API_KEY, TMDB_BASE_URL
import requests
import time
import re

START_YEAR = 2020
END_YEAR = 2026  # inclusive

# Genre IDs that mean "not a drama" for our purposes -- excluded both in the
# discover API call AND double-checked after fetching full detail.
EXCLUDED_TMDB_GENRE_IDS = {16, 10762, 10763, 10764, 10767, 99}
# 16=Animation, 10762=Kids, 10763=News, 10764=Reality, 10767=Talk, 99=Documentary

EXCLUDED_TMDB_TYPES = {'Reality', 'Talk Show', 'News', 'Game Show'}

# Maps TMDB genre ID -> your existing Genre IDs (English genre table, 237-269)
# Edit these IDs if they ever change in your DB.
TMDB_TO_YOUR_GENRE_IDS = {
    18:    [239],        # Drama            -> Drama
    35:    [242],        # Comedy           -> Comedy
    80:    [245],        # Crime            -> Crime
    9648:  [247],        # Mystery          -> Mystery
    10751: [264],        # Family           -> Family
    10759: [251, 256],   # Action & Adv     -> Action + Adventure
    10765: [252, 240],   # Sci-Fi & Fantasy -> Sci-Fi + Fantasy
    10766: [250],        # Soap             -> Melodrama
    10768: [246, 260],   # War & Politics   -> War + Political
    37:    [],           # Western          -> no match, skip
    # Excluded genres below are never matched to anything (kept here only
    # for clarity -- they never reach this dict in practice because the
    # discover call and the post-fetch check filter them out first).
    16:    [],
    10762: [],
    10763: [],
    10764: [],
    10767: [],
    99:    [],
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
    """Parse first_air_date safely -- never crash the run on missing/odd dates."""
    if date_str and len(date_str) >= 4:
        try:
            return int(date_str[:4])
        except ValueError:
            pass
    return fallback_year


def normalize_tag_name(name):
    """Collapse whitespace so 'اسم ' and 'اسم' are treated as the same tag."""
    if not name:
        return ''
    return re.sub(r'\s+', ' ', name).strip()


def get_or_create_tags(tmdb_keywords, tag_cache):
    """
    For each TMDB keyword (English): translate to Arabic, normalize,
    check tag_cache / DB for an existing Tag with that name, reuse it,
    otherwise create a new Tag. tag_cache is a dict of
    {normalized_arabic_name: Tag} kept across the whole run to avoid
    hitting the DB repeatedly for the same tag and to avoid creating
    the same new tag twice in one run.
    Returns (list_of_tag_objects, num_reused, num_created).
    """
    result_tags = []
    reused = 0
    created = 0

    for kw in tmdb_keywords:
        raw_name = (kw.get('name') or '').strip()
        if not raw_name:
            continue

        try:
            arabic_name = translate_to_arabic(raw_name)
        except Exception:
            # If translation fails for some reason, skip this keyword
            # rather than saving an English tag into an Arabic-only table.
            continue

        norm_arabic = normalize_tag_name(arabic_name)
        norm_english = normalize_tag_name(raw_name)
        if not norm_arabic or not norm_english:
            continue

        cache_key = norm_english.lower()
        if cache_key in tag_cache:
            tag = tag_cache[cache_key]
            reused += 1
        else:
            tag = Tag.objects.filter(name__iexact=norm_english).first()
            if tag:
                if not tag.name_arabic:
                    tag.name_arabic = norm_arabic
                    tag.save()
                reused += 1
            else:
                tag = Tag.objects.create(name=norm_english, name_arabic=norm_arabic)
                created += 1
            tag_cache[cache_key] = tag

        if tag not in result_tags:
            result_tags.append(tag)

    return result_tags, reused, created


class Command(BaseCommand):
    help = 'Fetch Turkish dramas 2020-2026 from TMDB -- drama only, with tags & ratings'

    def handle(self, *args, **options):
        genre_map = load_genres()
        self.stdout.write(f'Loaded {len(genre_map)} genres from DB\n')

        tag_cache = {}  # normalized Arabic tag name -> Tag object, shared across whole run

        added = updated = skipped = 0
        tags_reused_total = tags_created_total = 0

        for year in range(START_YEAR, END_YEAR + 1):
            self.stdout.write(f'\n{"="*55}')
            self.stdout.write(f'FETCHING TURKISH DRAMAS -- {year}')
            self.stdout.write(f'{"="*55}\n')

            for page in range(1, 21):
                self.stdout.write(f'--- Page {page}/20 ---')

                try:
                    resp = requests.get(
                        f"{TMDB_BASE_URL}/discover/tv",
                        params={
                            'api_key':                TMDB_API_KEY,
                            'language':                'tr-TR',
                            'with_origin_country':     'TR',
                            'with_original_language':  'tr',
                            'with_genres':             '18',   # Drama only
                            'without_genres':          ','.join(str(g) for g in EXCLUDED_TMDB_GENRE_IDS),
                            'first_air_date.gte':      f'{year}-01-01',
                            'first_air_date.lte':      f'{year}-12-31',
                            'sort_by':                 'popularity.desc',
                            'page':                    page,
                        },
                        timeout=10
                    )
                except Exception as e:
                    self.stdout.write(f'Request failed: {e} -- stopping page loop')
                    break

                if resp.status_code != 200:
                    self.stdout.write(f'API error: {resp.status_code} -- stopping')
                    break

                results = resp.json().get('results', [])
                if not results:
                    self.stdout.write('No more results')
                    break

                for show in results:
                    tmdb_id = show.get('id')
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
                        self.stdout.write(f'  \u26a0 Detail fetch failed for {display_name}: {e}')
                        skipped += 1
                        continue

                    tmdb_genre_ids = [g['id'] for g in detail.get('genres', [])]

                    # --- Skip non-drama types ---
                    tmdb_type = detail.get('type', '')
                    if tmdb_type in EXCLUDED_TMDB_TYPES:
                        self.stdout.write(f'  \u23ed SKIP ({tmdb_type}): {display_name}')
                        skipped += 1
                        continue

                    # --- Post-fetch safety net: block animation/kids/etc even if
                    #     the discover filter somehow missed them ---
                    if any(g in EXCLUDED_TMDB_GENRE_IDS for g in tmdb_genre_ids):
                        self.stdout.write(f'  \u23ed SKIP (excluded genre): {display_name}')
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
                    release_year  = safe_year(show.get('first_air_date'), year)

                    # TMDB rating/popularity -- separate fields, never mixed with MDL
                    tmdb_rating     = detail.get('vote_average')
                    tmdb_vote_count = detail.get('vote_count')
                    tmdb_popularity = detail.get('popularity')

                    matched_genres = get_matched_genres(tmdb_genre_ids, genre_map)

                    # --- Fetch keywords (tags) ---
                    try:
                        kw_resp = requests.get(
                            f"{TMDB_BASE_URL}/tv/{tmdb_id}/keywords",
                            params={'api_key': TMDB_API_KEY},
                            timeout=10
                        )
                        tmdb_keywords = kw_resp.json().get('results', [])
                    except Exception as e:
                        self.stdout.write(f'  \u26a0 Keywords fetch failed for {display_name}: {e}')
                        tmdb_keywords = []

                    matched_tags, kw_reused, kw_created = get_or_create_tags(tmdb_keywords, tag_cache)
                    tags_reused_total += kw_reused
                    tags_created_total += kw_created

                    # --- Find existing drama: tmdb_id first, then
                    #     title_original + release_year (prevents remakes
                    #     in different years from colliding) ---
                    drama = Drama.objects.filter(tmdb_id=tmdb_id).first()
                    match_type = 'tmdb_id'

                    if not drama and original_name:
                        drama = Drama.objects.filter(
                            title_original=original_name,
                            release_year=release_year,
                        ).first()
                        match_type = 'title+year'

                    if drama:
                        drama.title             = display_name
                        drama.title_original    = original_name
                        drama.tmdb_id            = tmdb_id
                        drama.total_episodes     = new_episodes
                        drama.status             = new_status
                        drama.episode_duration   = new_duration
                        if thumbnail_url:
                            drama.thumbnail_url = thumbnail_url
                        if overview:
                            drama.description        = overview
                            drama.description_arabic = translate_to_arabic(overview)
                        drama.tmdb_rating     = tmdb_rating
                        drama.tmdb_vote_count = tmdb_vote_count
                        drama.tmdb_popularity = tmdb_popularity
                        drama.save()

                        if matched_genres:
                            drama.genres.add(*matched_genres)  # merge only: never removes existing genres
                        if matched_tags:
                            drama.tags.add(*matched_tags)      # tags: additive only, never removes manual tags

                        self.stdout.write(f'  \U0001f504 UPDATED ({match_type}): {display_name}')
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
                        release_year       = release_year,
                        total_episodes     = new_episodes,
                        episode_duration   = new_duration,
                        status             = new_status,
                        thumbnail_url      = thumbnail_url,
                        tmdb_rating        = tmdb_rating,
                        tmdb_vote_count    = tmdb_vote_count,
                        tmdb_popularity    = tmdb_popularity,
                    )
                    if matched_genres:
                        drama.genres.set(matched_genres)
                    if matched_tags:
                        drama.tags.add(*matched_tags)

                    self.stdout.write(self.style.SUCCESS(f'  \u2705 ADDED: {display_name}'))
                    added += 1
                    time.sleep(0.25)

        self.stdout.write(self.style.SUCCESS(
            f'\n{"="*55}\n'
            f'\u2705 DONE\n'
            f'   Added         : {added}\n'
            f'   Updated       : {updated}\n'
            f'   Skipped       : {skipped}\n'
            f'   Tags reused   : {tags_reused_total}\n'
            f'   Tags created  : {tags_created_total}\n'
            f'{"="*55}'
        ))