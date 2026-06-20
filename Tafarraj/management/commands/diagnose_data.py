from django.core.management.base import BaseCommand
from Tafarraj.models import Drama, Genre
from django.db.models import Count, Q


class Command(BaseCommand):
    help = 'Diagnose drama data issues'

    def handle(self, *args, **options):
        self.stdout.write('='*60)
        self.stdout.write('DATABASE DIAGNOSIS')
        self.stdout.write('='*60)

        total_dramas = Drama.objects.count()
        total_genres = Genre.objects.count()

        self.stdout.write(f'\n📊 TOTAL DRAMAS: {total_dramas}')
        self.stdout.write(f'📊 TOTAL GENRES: {total_genres}')

        # Country breakdown
        self.stdout.write('\n' + '='*60)
        self.stdout.write('BY COUNTRY')
        self.stdout.write('='*60)
        countries = Drama.objects.values('country').annotate(count=Count('id')).order_by('-count')
        for c in countries:
            self.stdout.write(f"{c['country']}: {c['count']} dramas")

        # Dramas without genres
        self.stdout.write('\n' + '='*60)
        self.stdout.write('GENRE ASSIGNMENT CHECK')
        self.stdout.write('='*60)
        dramas_without_genres = Drama.objects.annotate(genre_count=Count('genres')).filter(genre_count=0)
        self.stdout.write(f'⚠️  Dramas WITHOUT genres: {dramas_without_genres.count()}')
        if dramas_without_genres.exists():
            self.stdout.write('\nFirst 10 dramas without genres:')
            for drama in dramas_without_genres[:10]:
                self.stdout.write(f'  - {drama.title} ({drama.country}, {drama.release_year})')

        # Genre distribution
        self.stdout.write('\n' + '='*60)
        self.stdout.write('GENRE DISTRIBUTION')
        self.stdout.write('='*60)
        genres = Genre.objects.annotate(drama_count=Count('drama')).order_by('-drama_count')
        for genre in genres[:15]:
            self.stdout.write(f"{genre.name_arabic or genre.name}: {genre.drama_count} dramas")

        # Korean dramas
        self.stdout.write('\n' + '='*60)
        self.stdout.write('KOREAN DRAMAS ANALYSIS')
        self.stdout.write('='*60)
        korean_total = Drama.objects.filter(country='korean').count()
        korean_with_genres = Drama.objects.filter(country='korean').annotate(genre_count=Count('genres')).filter(genre_count__gt=0).count()
        korean_without_genres = korean_total - korean_with_genres

        self.stdout.write(f'Total Korean dramas: {korean_total}')
        self.stdout.write(f'Korean dramas WITH genres: {korean_with_genres}')
        self.stdout.write(f'Korean dramas WITHOUT genres: {korean_without_genres}')

        try:
            romance = Genre.objects.get(name='رومانسي')
            korean_romance = Drama.objects.filter(country='korean', genres=romance).count()
            self.stdout.write(f'Korean Romance dramas: {korean_romance}')
        except Genre.DoesNotExist:
            self.stdout.write('⚠️  رومانسي genre does not exist!')

        # Year distribution
        self.stdout.write('\n' + '='*60)
        self.stdout.write('KOREAN DRAMAS BY YEAR')
        self.stdout.write('='*60)
        korean_years = Drama.objects.filter(country='korean').values('release_year').annotate(count=Count('id')).order_by('-release_year')[:10]
        for year in korean_years:
            self.stdout.write(f"{year['release_year']}: {year['count']} dramas")

        # Data quality
        self.stdout.write('\n' + '='*60)
        self.stdout.write('DATA QUALITY ISSUES')
        self.stdout.write('='*60)
        null_country = Drama.objects.filter(Q(country__isnull=True) | Q(country='')).count()
        null_year = Drama.objects.filter(Q(release_year__isnull=True) | Q(release_year=0)).count()
        self.stdout.write(f'Dramas with NULL/empty country: {null_country}')
        self.stdout.write(f'Dramas with NULL/0 release_year: {null_year}')

        # Sample
        self.stdout.write('\n' + '='*60)
        self.stdout.write('SAMPLE KOREAN DRAMAS')
        self.stdout.write('='*60)
        for drama in Drama.objects.filter(country='korean')[:5]:
            genres_list = ', '.join([g.name_arabic or g.name for g in drama.genres.all()])
            self.stdout.write(f'\n{drama.title}')
            self.stdout.write(f'  Country: {drama.country}')
            self.stdout.write(f'  Year: {drama.release_year}')
            self.stdout.write(f'  Genres: {genres_list if genres_list else "NONE"}')

        self.stdout.write('\n' + '='*60)
        self.stdout.write('DIAGNOSIS COMPLETE')
        self.stdout.write('='*60)