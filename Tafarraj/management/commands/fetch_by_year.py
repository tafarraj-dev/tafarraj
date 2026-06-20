from django.core.management.base import BaseCommand
from Tafarraj.models import Drama, Genre
from Tafarraj.utils import translate_to_arabic, TMDB_API_KEY, TMDB_BASE_URL
import requests
from django.core.files.base import ContentFile
import time

class Command(BaseCommand):
    help = 'Fetch dramas by year and country'

    def add_arguments(self, parser):
        parser.add_argument('country', type=str, help='KR, TR, CN, IN')
        parser.add_argument('year', type=int, help='2025, 2026, etc.')
        parser.add_argument('--pages', type=int, default=20, help='Number of pages')

    def handle(self, *args, **options):
        country = options['country'].upper()
        year = options['year']
        pages = options['pages']

        country_map = {'KR': 'korean', 'TR': 'turkish', 'CN': 'chinese', 'IN': 'indian'}

        if country not in country_map:
            self.stdout.write('Use: KR, TR, CN, IN')
            return

        genre_resp = requests.get(f"{TMDB_BASE_URL}/genre/tv/list", params={'api_key': TMDB_API_KEY})
        tmdb_genres = {g['id']: g['name'] for g in genre_resp.json().get('genres', [])}

        for genre_id, genre_name in tmdb_genres.items():
            Genre.objects.get_or_create(
                name=genre_name,
                defaults={'name_arabic': translate_to_arabic(genre_name)}
            )

        country_name = country_map[country]
        added = 0
        updated = 0

        self.stdout.write(f'Fetching {country} dramas from {year}...')

        for page in range(1, pages + 1):
            self.stdout.write(f'PAGE {page}/{pages}')

            resp = requests.get(f"{TMDB_BASE_URL}/discover/tv", params={
                'api_key': TMDB_API_KEY,
                'with_origin_country': country,
                'first_air_date.gte': f'{year}-01-01',
                'first_air_date.lte': f'{year}-12-31',
                'sort_by': 'popularity.desc',
                'page': page
            })

            if resp.status_code != 200:
                self.stdout.write(f'API Error: {resp.status_code}')
                break

            results = resp.json().get('results', [])

            if not results:
                self.stdout.write('No more results')
                break

            for show in results:
                name = show.get('name', '')
                tmdb_id = show.get('id')

                detail = requests.get(f"{TMDB_BASE_URL}/tv/{show['id']}", params={'api_key': TMDB_API_KEY}).json()
                new_episodes = detail.get('number_of_episodes') or 0
                new_status = 'completed' if detail.get('status') == 'Ended' else 'ongoing'
                new_duration = detail.get('episode_run_time', [45])[0] if detail.get('episode_run_time') else 45

                # Already in DB by TMDB ID → just update info
                drama = Drama.objects.filter(tmdb_id=tmdb_id).first()
                if drama:
                    drama.total_episodes = new_episodes
                    drama.status = new_status
                    drama.episode_duration = new_duration
                    drama.save()
                    self.stdout.write(f'UPDATED (id): {name}')
                    updated += 1
                    continue

                # Already in DB by title (from scrapers) → update and save tmdb_id
                drama = Drama.objects.filter(title=name).first()
                if drama:
                    drama.tmdb_id = tmdb_id
                    drama.total_episodes = new_episodes
                    drama.status = new_status
                    drama.episode_duration = new_duration
                    drama.save()
                    self.stdout.write(f'UPDATED (title): {name}')
                    updated += 1
                    continue

                # New drama → create it
                drama = Drama.objects.create(
                    tmdb_id=tmdb_id,
                    title=name,
                    title_arabic=translate_to_arabic(name),
                    title_original=show.get('original_name', ''),
                    description=show.get('overview', 'No description'),
                    description_arabic=translate_to_arabic(show.get('overview', 'No description')),
                    country=country_name,
                    release_year=int(show.get('first_air_date', f'{year}-01-01')[:4]),
                    total_episodes=new_episodes,
                    episode_duration=new_duration,
                    status=new_status,
                )

                for genre_id in show.get('genre_ids', []):
                    genre_name = tmdb_genres.get(genre_id)
                    if genre_name:
                        try:
                            genre = Genre.objects.get(name=genre_name)
                            drama.genres.add(genre)
                        except:
                            pass

                if show.get('poster_path'):
                    try:
                        img = requests.get(f"https://image.tmdb.org/t/p/w500{show['poster_path']}")
                        drama.thumbnail.save(f'{drama.id}.jpg', ContentFile(img.content), save=True)
                    except:
                        pass

                self.stdout.write(self.style.SUCCESS(f'✓ {drama.title_arabic}'))
                added += 1
                time.sleep(0.3)

        self.stdout.write(self.style.SUCCESS(f'\n✅ ADDED: {added} | UPDATED: {updated}'))