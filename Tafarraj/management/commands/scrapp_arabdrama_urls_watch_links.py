from django.core.management.base import BaseCommand
from Tafarraj.models import Drama, WatchLink
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import time


class Command(BaseCommand):
    help = 'Scrape real drama page URLs from aradramatv.cc'

    def __init__(self):
        super().__init__()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "ar,en;q=0.9",
        }

    def search_aradrama(self, drama):
        """Search aradrama for a drama and return the first matching URL"""
        # Try different title variations
        titles_to_try = []

        # Split title if it contains '/'
        if '/' in drama.title:
            parts = drama.title.split('/')
            for part in parts:
                titles_to_try.append(part.strip())
        else:
            titles_to_try.append(drama.title.strip())

        # Add Arabic title
        if drama.title_arabic:
            if '/' in drama.title_arabic:
                parts = drama.title_arabic.split('/')
                for part in parts:
                    titles_to_try.append(part.strip())
            else:
                titles_to_try.append(drama.title_arabic.strip())

        for title in titles_to_try:
            if not title:
                continue

            try:
                search_url = f"https://aradramatv.cc/search/{title}/"
                res = requests.get(search_url, headers=self.headers, timeout=10)

                if res.status_code != 200:
                    continue

                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.find_all("a", href=True)

                drama_links = []
                for l in links:
                    href = unquote(l['href'])
                    if 'aradramatv.cc/20' in href and 'الحلقة' not in href and 'حلقة' not in href:
                        if href not in drama_links:
                            drama_links.append(href)

                if drama_links:
                    return drama_links[0]  # Return first result

            except Exception:
                continue

        return None

    def handle(self, *args, **options):
        # Only Korean, Chinese, Japanese
        dramas = Drama.objects.filter(
            country__in=['korean', 'chinese', 'japanese']
        ).order_by('-release_year', '-id')

        total = dramas.count()
        fixed = 0
        skipped = 0
        failed = 0

        self.stdout.write(f'🔍 Searching aradrama for {total} dramas...\n')

        for i, drama in enumerate(dramas, 1):
            # Check if aradrama link already exists
            existing = drama.links.filter(website_name='Aradrama').first()
            if existing and 'aradramatv.cc/20' in existing.url:
                skipped += 1
                continue

            self.stdout.write(f'[{i}/{total}] {drama.title_arabic or drama.title}')

            url = self.search_aradrama(drama)

            if url:
                # Delete old aradrama homepage link if exists
                drama.links.filter(website_name='Aradrama').delete()

                # Save real URL
                WatchLink.objects.create(
                    drama=drama,
                    website_name='Aradrama',
                    url=url,
                    language='arabic',
                    episodes_available=drama.total_episodes
                )
                self.stdout.write(f'  ✅ {url}')
                fixed += 1
            else:
                self.stdout.write(f'  ❌ Not found')
                failed += 1

            # Be nice to the server
            time.sleep(1)

        self.stdout.write(f'\n{"="*50}')
        self.stdout.write(f'✅ DONE')
        self.stdout.write(f'Fixed: {fixed}')
        self.stdout.write(f'Skipped (already had real link): {skipped}')
        self.stdout.write(f'Not found: {failed}')
        self.stdout.write(f'{"="*50}')