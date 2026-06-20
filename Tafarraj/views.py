from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Count, Case, When, IntegerField
from django.core.paginator import Paginator
from .models import Drama, Genre, WatchLink, SavedDrama, WatchHistory
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from .models import CustomUser, WatchSite
from itertools import zip_longest
from django.utils import timezone


def get_active_filters(request):
    search = request.GET.get('search', '').strip()
    active_country = request.GET.get('countries', '')
    active_status = request.GET.get('status', '')
    active_countries_list = request.GET.getlist('countries')
    has_active_filters = bool(search or active_country or active_status)

    if search:
        grid_title = f'Results for "{search}"'
    elif active_country:
        grid_title = f'{active_country} Dramas'
    elif active_status:
        grid_title = f'{active_status} Dramas'
    else:
        grid_title = 'All Dramas'

    return {
        'active_filters': has_active_filters,
        'active_country': active_country,
        'active_status': active_status,
        'active_countries_list': active_countries_list,
        'grid_title': grid_title,
        'has_active_filters': has_active_filters,
    }

COUNTRY_ORDER = {'korean': 0, 'japanese': 1, 'chinese': 2, 'thai': 3, 'turkish': 4}


def format_ar(dt):
    diff = timezone.now() - dt
    s = diff.total_seconds()
    if s < 3600:
        m = int(s // 60)
        return f"منذ {m} دقيقة"
    elif s < 86400:
        h = int(s // 3600)
        return f"منذ {h} ساعة"
    elif s < 604800:
        d = int(s // 86400)
        return f"منذ {d} يوم"
    else:
        return dt.strftime("%d %b %Y")


def drama_list(request):
    dramas = Drama.objects.all()

    countries = request.GET.getlist('countries')
    if countries:
        dramas = dramas.filter(country__in=countries)

    status = request.GET.get('status')
    if status:
        dramas = dramas.filter(status=status)

    genre = request.GET.get('genre')
    if genre:
        try:
            dramas = dramas.filter(genres__id=int(genre))
        except ValueError:
            pass

    year = request.GET.get('year')
    if year:
        dramas = dramas.filter(release_year=year)

    
    search = request.GET.get('search')
    if search:
        dramas = dramas.filter(
            Q(title__icontains=search) |
            Q(title_arabic__icontains=search)
        ).annotate(
            search_rank=Case(
                When(title__istartswith=search, then=0),
                When(title_arabic__istartswith=search, then=1),
                When(title__icontains=search, then=2),
                When(title_arabic__icontains=search, then=3),
                default=4,
                output_field=IntegerField(),
            )
        ).order_by('search_rank', '-release_year')

    dramas = dramas.annotate(
        country_order=Case(
            When(country='korean', then=0),
            When(country='japanese', then=1),
            When(country='chinese', then=2),
            When(country='thai', then=3),
            When(country='turkish', then=4),
            default=5,
            output_field=IntegerField(),
        )
    ).order_by('-release_year', 'country_order', '-id')

    paginator = Paginator(dramas, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    genres = Genre.objects.annotate(drama_count=Count('drama')).filter(drama_count__gt=0).order_by('-drama_count')
    years = Drama.objects.values_list('release_year', flat=True).distinct().order_by('-release_year')

    countries_order = ['korean', 'chinese', 'japanese', 'thai', 'turkish']
    grouped = []
    for country in countries_order:
        country_dramas = list(
            Drama.objects.filter(
                country=country,
                release_year=2026,
                thumbnail_url__isnull=False
            ).exclude(thumbnail_url='').order_by('-id')[:4]
        )
        grouped.append(country_dramas)
    newest_dramas = [d for row in zip_longest(*grouped) for d in row if d is not None]

    continue_watching = []
    saved_drama_ids = set()
    if request.user.is_authenticated:
        continue_watching = WatchHistory.objects.filter(
            user=request.user
        ).select_related('drama').order_by('-last_updated')[:10]
        saved_drama_ids = set(
            SavedDrama.objects.filter(user=request.user).values_list('drama_id', flat=True)
        )

    filter_ctx = get_active_filters(request)
    context = {
        'dramas': page_obj,
        'genres': genres,
        'years': years,
        'status': status,
        'genre': genre,
        'year': year,
        'search': search,
        'is_search': bool(search),
        'newest_dramas': newest_dramas,
        'continue_watching': continue_watching,
        'saved_drama_ids': saved_drama_ids,
        **filter_ctx,
    }
    return render(request, 'Tafarraj/drama_list.html', context)


def drama_detail(request, pk):
    drama = get_object_or_404(Drama, pk=pk)
    is_saved = False
    save_type = None
    if request.user.is_authenticated:
        saved = SavedDrama.objects.filter(user=request.user, drama=drama).first()
        if saved:
            is_saved = True
            save_type = saved.list_type
    return render(request, 'Tafarraj/drama_detail.html', {
        'drama': drama,
        'is_saved': is_saved,
        'save_type': save_type,
    })


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('tafarraj:drama_list')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')

        if not username or not email or not password:
            messages.error(request, 'جميع الحقول مطلوبة')
        elif password != password2:
            messages.error(request, 'كلمتا المرور غير متطابقتين')
        elif CustomUser.objects.filter(username=username).exists():
            messages.error(request, 'اسم المستخدم مستخدم بالفعل')
        elif CustomUser.objects.filter(email=email).exists():
            messages.error(request, 'البريد الإلكتروني مستخدم بالفعل')
        else:
            user = CustomUser.objects.create_user(username=username, email=email, password=password)
            login(request, user, backend='Tafarraj.auth_backend.EmailOrUsernameBackend')
            return redirect('tafarraj:drama_list')

    return render(request, 'Tafarraj/signup.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('tafarraj:drama_list')
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=identifier, password=password)
        if user:
            login(request, user)
            return redirect(request.GET.get('next', 'tafarraj:drama_list'))
        else:
            messages.error(request, 'بيانات الدخول غير صحيحة')
    return render(request, 'Tafarraj/login.html')


def logout_view(request):
    logout(request)
    return redirect('tafarraj:drama_list')


@login_required
def my_list_view(request):
    tab = request.GET.get('tab', 'watchlist')
    saved = SavedDrama.objects.filter(
        user=request.user, list_type=tab
    ).select_related('drama').order_by('-created_at')

    history_qs = WatchHistory.objects.filter(
        user=request.user
    ).select_related('drama').order_by('-last_updated')

    history_with_time = [
        {'obj': h, 'time_str': format_ar(h.last_updated)}
        for h in history_qs
    ]

    context = {
        'saved': saved,
        'history': history_with_time,
        'tab': tab,
    }
    return render(request, 'Tafarraj/my_list.html', context)


@login_required
@require_POST
def record_watch_click(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    drama_id  = data.get('drama_id')
    site_name = data.get('site_name', '').strip()

    if not drama_id:
        return JsonResponse({'error': 'drama_id is required'}, status=400)

    drama = get_object_or_404(Drama, pk=drama_id)
    watch_site = WatchSite.objects.filter(name__iexact=site_name).first()

    WatchHistory.objects.update_or_create(
        user=request.user,
        drama=drama,
        defaults={
            'last_watched_site': watch_site,
            'last_updated': timezone.now(),
        }
    )

    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def save_drama_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    drama_id  = data.get('drama_id')
    list_type = data.get('list_type', 'watchlist')
    action    = data.get('action', 'save')

    if not drama_id:
        return JsonResponse({'error': 'drama_id is required'}, status=400)

    valid_list_types = {'watchlist', 'favorites', 'completed'}
    if list_type not in valid_list_types:
        return JsonResponse({'error': f'list_type must be one of {valid_list_types}'}, status=400)

    drama = get_object_or_404(Drama, pk=drama_id)

    if action == 'remove':
        deleted_count, _ = SavedDrama.objects.filter(user=request.user, drama=drama).delete()
        return JsonResponse({'status': 'removed', 'deleted': deleted_count > 0})

    obj, created = SavedDrama.objects.update_or_create(
        user=request.user,
        drama=drama,
        defaults={'list_type': list_type},
    )
    return JsonResponse({'status': 'saved', 'list_type': list_type, 'created': created})


def link_tool(request):
    return render(request, 'Tafarraj/link_tool.html')


def top_dramas_api(request):
    result = []
    for country in ['korean', 'chinese', 'japanese', 'turkish']:
        country_dramas = Drama.objects.filter(country=country).order_by('-release_year', '-id')[:25]
        for d in country_dramas:
            result.append({
                'id': d.id,
                'title': d.title,
                'title_arabic': d.title_arabic,
                'title_original': d.title_original,
                'country': d.country,
                'release_year': d.release_year,
            })
    return JsonResponse({'dramas': result})


@csrf_exempt
@require_http_methods(["POST"])
def save_watch_link_api(request):
    try:
        data = json.loads(request.body)
        drama = Drama.objects.get(id=data['drama_id'])
        link, created = WatchLink.objects.update_or_create(
            drama=drama,
            website_name=data['website_name'],
            defaults={
                'url': data['url'],
                'language': 'arabic',
                'episodes_available': data.get('episodes_available', 0),
                'is_free': data.get('is_free', True),
                'has_arabic_subtitles': data.get('has_arabic_subtitles', True),
                'ads_level': data.get('ads_level', 'moderate'),
                'episodes_completeness': data.get('episodes_completeness', 'complete'),
            }
        )
        return JsonResponse({'success': True, 'created': created})
    except Drama.DoesNotExist:
        return JsonResponse({'error': 'Drama not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


SITES = [
    {
        "name": "Asia2TV",
        "domain": "asia2tv.com",
        "path_patterns": ["/serie/"],
        "bad_patterns": ["/episode", "/ep-", "?s=", "/search", "/category", "/tag", "/page/", "/celebrities", "/actors", "/news", "/most-viewed", "/latest"],
    },
    {
        "name": "Best Drama",
        "domain": "best-drama.com",
        "path_patterns": ["/series/"],
        "bad_patterns": ["/episode", "/ep-", "?s=", "/search", "/category", "/tag", "/page/", "/actors", "/news"],
    },
    {
        "name": "Shahid Mosalsalat",
        "domain": "shahidmosalsalat",
        "path_patterns": ["/watch.php"],
        "bad_patterns": ["?s=", "/search", "/category", "/tag", "/page/", "/actors", "/news", "ep=", "episode="],
    },
    {
        "name": "Viki",
        "domain": "viki.com",
        "path_patterns": ["/tv/"],
        "bad_patterns": ["/explore", "/search", "/episodes", "?q=", "/page/", "/news", "/people", "utm_"],
    },
    {
        "name": "WeTV",
        "domain": "wetv.vip",
        "path_patterns": ["/play/"],
        "bad_patterns": ["/search", "?keyword=", "/episode", "/page/", "/news", "/en/", "Special_Feature", "utm_"],
    },
]


def score_url(url, domain_config):
    url_lower = url.lower()
    has_good_path = any(p in url_lower for p in domain_config["path_patterns"])
    if not has_good_path:
        return -100
    score = 30
    for pattern in domain_config["bad_patterns"]:
        if pattern in url_lower:
            return -100
    path = url.split("?")[0]
    segments = [s for s in path.split("/") if s]
    if len(segments) <= 2:
        score += 20
    elif len(segments) <= 3:
        score += 10
    elif len(segments) >= 5:
        score -= 40
    return score


def search_valueserp(query, max_results=5):
    try:
        resp = requests.get(
            "https://api.valueserp.com/search",
            params={
                "api_key": "********",
                "q": query,
                "num": max_results,
            },
            timeout=10,
        )
        data = resp.json()
        urls = [r["link"] for r in data.get("organic_results", []) if "link" in r]
        return urls[:max_results]
    except Exception as e:
        print("Search error:", e)
        return []


def find_url_for_site(drama_title, drama_title_arabic, site_config):
    domain = site_config["domain"]
    all_candidates = []

    if drama_title:
        results = search_valueserp(f'{drama_title} korean drama site:{domain}', max_results=5)
        for url in results:
            if domain in url:
                s = score_url(url, site_config)
                all_candidates.append((url, s))

    if not any(s >= 30 for _, s in all_candidates) and drama_title_arabic:
        results = search_valueserp(f'{drama_title_arabic} site:{domain}', max_results=5)
        for url in results:
            if domain in url:
                s = score_url(url, site_config)
                all_candidates.append((url, s))

    if not all_candidates:
        return {"url": None, "confidence": "not_found"}

    all_candidates.sort(key=lambda x: x[1], reverse=True)
    best_url, best_score = all_candidates[0]

    if best_score < 0:
        return {"url": None, "confidence": "not_found"}

    confidence = "high" if best_score >= 30 else "low"
    return {"url": best_url, "confidence": confidence}


@require_POST
def auto_find_links(request):
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    drama_title = body.get("drama_title", "").strip()
    drama_title_arabic = body.get("drama_title_arabic", "").strip()
    requested_sites = body.get("sites", None)

    if not drama_title and not drama_title_arabic:
        return JsonResponse({"error": "يجب توفير عنوان المسلسل"}, status=400)

    sites_to_check = SITES
    if requested_sites:
        sites_to_check = [s for s in SITES if s["name"] in requested_sites]

    results = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(find_url_for_site, drama_title, drama_title_arabic, site): site["name"]
            for site in sites_to_check
        }
        for future in as_completed(futures):
            site_name = futures[future]
            try:
                results[site_name] = future.result()
            except Exception:
                results[site_name] = {"url": None, "confidence": "not_found"}

    return JsonResponse({"results": results})


def drama_autocomplete(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    dramas = Drama.objects.filter(
        Q(title__icontains=q) |
        Q(title_arabic__icontains=q) |
        Q(title_original__icontains=q)
    )[:8]
    results = []
    for d in dramas:
        results.append({
            'id': d.pk,
            'title_arabic': d.title_arabic or d.title,
            'title': d.title,
            'url': f'/drama/{d.pk}/'
        })
    return JsonResponse({'results': results})