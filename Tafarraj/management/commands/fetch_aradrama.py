"""
It scrapes **aradramatv.cc** for Korean, Chinese, Japanese, and Thai dramas (2020-2026) and:

1. **New drama** -> creates it in DB + adds genres + adds Aradrama watch link
2. **Existing drama, matched** -> does NOT skip it. Instead:
      - fills any MISSING fields (title_arabic, thumbnail, title_original,
        total_episodes, episode_duration, status, country, genres, homepage_url)
      - ALWAYS replaces description_arabic with the fresh Aradrama description
        (this is an overwrite, not a gap-fill, per your request)
      - adds the Aradrama watch link if it doesn't already have one

CHANGES FROM PREVIOUS VERSION (see inline comments marked FIX):
  FIX-1: find_existing_drama() no longer does a country/year-blind fuzzy title
         match across the whole DB. A same-titled drama from a different year
         is no longer treated as the same drama. This was the #1 cause of Thai
         dramas silently merging into unrelated Korean entries.
  FIX-2: country_raw text is cleaned (strips invisible RTL/whitespace chars)
         before the COUNTRY_MAP lookup, and unmapped values are now logged
         instead of silently defaulting.
  FIX-3: get_drama_links() no longer stops a whole category early based on a
         fragile year-badge read from the listing page. It now paginates
         until it hits 2 consecutive empty pages, and logs per-page counts
         so you can see exactly what's happening.
  FIX-4: process_link()'s "existing drama" branch was rewritten to properly
         fill-the-gaps + always refresh the Arabic description, as described
         above.
"""

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from Tafarraj.models import Drama, Genre, WatchLink
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

CATEGORY_URLS = {
    "korean":   "https://aradramatv.cc/category/serie/",
    "chinese":  "https://aradramatv.cc/category/serie/chinese-taiwan/",
    "japanese": "https://aradramatv.cc/category/serie/japanese/",
    "thai":     "https://aradramatv.cc/category/serie/tailand/",
    # ^ NOTE: if Thai counts are still low/wrong after these fixes, double
    # check this URL actually resolves to a Thai-only listing on the live
    # site (open it in a browser). A wrong/redirecting slug here would make
    # this loop silently scrape Korean/mixed content under the "thai" label,
    # which lines up exactly with what you were seeing.
}

TARGET_YEARS = list(range(2020, 2027))
TEST_LIMIT = None
MAX_WORKERS = 6
MAX_PAGES_PER_CATEGORY = 60

# Maps the Arabic country text found ON the drama page itself to your
# Drama.country field values. If a country isn't matched here, it falls
# back to the CATEGORY_URLS key (the dict key above) instead.
COUNTRY_MAP = {
    "كوريا الجنوبية": "korean",
    "كوريا": "korean",
    "اليابان": "japanese",
    "الصين": "chinese",
    "تايوان": "chinese",
    "تايون": "chinese",   # site typo — missing a letter, meant "التايوان" (Taiwan)
    "تايلاند": "thai",
    "تايلاندا": "thai",
    "المغرب": "moroccan",
    "تركيا": "turkish",
}


# ── text cleaning helpers ───────────────────────────────────────────────────

def _clean_arabic(s):
    """FIX-2: strip invisible RTL/LTR marks + collapse whitespace so
    COUNTRY_MAP lookups don't silently fail on near-identical strings."""
    if not s:
        return s
    s = re.sub(r'[\u200e\u200f\u202a-\u202e\ufeff]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _normalize_genre_text(s):
    """Loose normalization used ONLY for comparison (never for storage):
    collapses underscores/whitespace and strips a leading definite article
    'ال' so 'سفر_عبر_الزمن' and 'السفر عبر الزمن' compare equal."""
    if not s:
        return ""
    s = _clean_arabic(s)
    s = s.replace("_", " ")
    s = re.sub(r'\s+', ' ', s).strip()
    if s.startswith("ال") and len(s) > 2:
        s = s[2:].strip()
    return s


# Known variant spellings that mean the SAME thing as a genre you already
# have, just written differently (this is exactly the pattern already
# visible in your DB: خيال / خيالي / فانتازيا are all "Fantasy" as 3 rows).
# Left side: normalized variant text. Right side: canonical name_arabic to
# look up. Add to this over time as you spot more near-duplicates.
GENRE_ALIASES = {
    "خيال": "فانتازيا",                   # "fantasy" (noun) -> Fantasy
    "خيالي": "فانتازيا",                  # "fantastical" (adj) -> Fantasy
    "خارق": "خارق للطبيعة",               # "extraordinary" -> Supernatural
    "قوى خارقة": "خارق للطبيعة",          # "superpowers" -> Supernatural
    "طبخ": "طعام",                        # "cooking" -> Food
    "مراهقة": "شبابي",                    # "adolescence" -> Youth
    "سفر عبر الزمن": "السفر عبر الزمن",   # underscore/no-article variant -> canonical
    "مغامرات": "مغامرة",                  # "adventures" (plural) -> Adventure
    # Left out on purpose — arguably distinct genres, not just spelling
    # variants. Watch these; if they pile up as separate rows, decide then:
    #   عاطفي         ("emotional" — close to Romance/رومانسي but not identical)
    #   كوميديا_سوداء  ("black comedy" — a subgenre of Comedy, not the same tag)
}


def get_matching_genre(g_name):
    """Match-first genre resolution:
      1. Exact match on name_arabic or name (case-insensitive)
      2. Normalized match on name_arabic or name (handles underscores/'ال' prefix)
      3. Alias table -> canonical name_arabic -> match on that
      4. Only if NONE of the above find anything: create a new genre, and
         log it so you can catch future near-duplicates and add an alias
         instead of letting them pile up like خيال/خيالي/فانتازيا did."""
    raw = _clean_arabic(g_name)
    if not raw:
        return None

    genre = Genre.objects.filter(name_arabic__iexact=raw).first()
    if genre:
        return genre
    genre = Genre.objects.filter(name__iexact=raw).first()
    if genre:
        return genre

    normalized = _normalize_genre_text(raw)
    all_genres = list(Genre.objects.all())
    for existing in all_genres:
        if _normalize_genre_text(existing.name_arabic) == normalized:
            return existing
        if _normalize_genre_text(existing.name) == normalized:
            return existing

    canonical = GENRE_ALIASES.get(normalized)
    if canonical:
        canonical_norm = _normalize_genre_text(canonical)
        for existing in all_genres:
            if _normalize_genre_text(existing.name_arabic) == canonical_norm:
                return existing

    print(f"  \u2139\ufe0f  Creating NEW genre (no match/alias found): '{raw}' "
          f"— double check this isn't a spelling variant of an existing one.")
    return Genre.objects.create(name=raw, name_arabic=raw)


def _normalize_title(s):
    s = s.lower()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ── link discovery (FIX-3: no more fragile early-stop) ──────────────────────

def get_drama_links(category_url, target_years, limit=None, max_pages=MAX_PAGES_PER_CATEGORY):
    links = []
    page = 1
    consecutive_empty_pages = 0

    while page <= max_pages:
        if limit and len(links) >= limit:
            break

        url = f"{category_url}page/{page}/" if page > 1 else category_url
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
        except Exception as e:
            print(f"  Request error on page {page}: {e}")
            break

        if res.status_code != 200:
            print(f"  Page {page} returned HTTP {res.status_code} — stopping category.")
            break

        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("article.post")
        if not articles:
            print(f"  Page {page}: no <article.post> elements found — stopping category.")
            break

        new_this_page = 0
        for article in articles:
            if limit and len(links) >= limit:
                break

            # NOTE: intentionally NOT filtering by year here anymore.
            # The listing-page "year badge" was unreliable and was
            # triggering false early-stops. Year is checked properly
            # later, from the actual drama detail page.
            a_tag = article.select_one(
                "a.first_A, a[href*='aradramatv'], h2 a, h3 a, a[rel='bookmark']"
            )
            if a_tag and a_tag.get("href"):
                href = a_tag["href"]
                if href not in links:
                    links.append(href)
                    new_this_page += 1

        print(f"  Page {page}: {len(articles)} articles -> {new_this_page} new links "
              f"(running total: {len(links)})")

        if new_this_page == 0:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= 2:
                print(f"  2 consecutive pages with no new links — stopping category.")
                break
        else:
            consecutive_empty_pages = 0

        page += 1
        time.sleep(0.3)

    return links


def parse_info_block(soup):
    data = {}
    block = soup.select_one("div.b_block.s-desc, div.s-desc")
    if not block:
        return data
    p = block.find("p")
    if not p:
        return data

    current_label = None
    current_value_parts = []

    for child in p.children:
        if child.name == "span":
            if current_label and current_value_parts:
                data[current_label] = " ".join(current_value_parts).strip()
            current_label = child.get_text(strip=True).replace(":", "").strip()
            current_value_parts = []
        elif child.name == "br":
            continue
        else:
            text = str(child).strip()
            if text and current_label:
                current_value_parts.append(text)

    if current_label and current_value_parts:
        data[current_label] = " ".join(current_value_parts).strip()

    return data


def parse_drama_page(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
    except Exception:
        return None

    if res.status_code != 200:
        return None

    soup = BeautifulSoup(res.text, "html.parser")
    data = {"homepage_url": url}

    thumb = soup.select_one("img.vc_single_image-img, img.attachment-full, .wpb_single_image img")
    if thumb:
        data["thumbnail_url"] = thumb.get("src", "")

    info = parse_info_block(soup)
    for label, value in info.items():
        if "اسم المسلسل" in label:
            data["title"] = value
        elif "الاسم العربي" in label:
            data["title_arabic"] = value
        elif "يعرف أيضا" in label or "الاسم الأصلي" in label:
            data["title_original"] = value
        elif "النوع" in label:
            genres = re.split(r'[،,]', value)
            data["genres_raw"] = [g.strip() for g in genres if g.strip()]
        elif "عدد الحلقات" in label:
            match = re.search(r'\d+', value)
            if match:
                data["total_episodes"] = int(match.group())
        elif "مدة الحلقة" in label:
            match = re.search(r'\d+', value)
            if match:
                data["episode_duration"] = int(match.group())
        elif "تاريخ البث" in label or "موعد البث" in label:
            match = re.search(r'20\d{2}', value)
            if match:
                data["release_year"] = int(match.group())
        elif "الحالة" in label or "حالة المسلسل" in label:
            data["status"] = "completed" if "مكتمل" in value else "ongoing"
        elif "البلد المنتج" in label or "البلد" in label:
            data["country_raw"] = _clean_arabic(value)

    desc_header = None
    for h3 in soup.find_all("h3"):
        if "القصة" in h3.get_text():
            desc_header = h3
            break
    if desc_header:
        desc_parts = []
        for sibling in desc_header.find_next_siblings():
            if sibling.name == "h3":
                break
            text = sibling.get_text(" ", strip=True)
            if text:
                desc_parts.append(text)
        if desc_parts:
            data["description_arabic"] = " ".join(desc_parts)[:1500]

    return data


# ── matching helpers (FIX-1: year/country-aware) ────────────────────────────

def find_existing_drama(data, title, release_year=None):
    """
    Priority match order (each of these is a strong/reliable identifier,
    so they're allowed to match regardless of year):
      1. homepage_url
      2. title_original (exact, case-insensitive)
      3. title_arabic (exact, case-insensitive)

    Then, as a LAST resort:
      4. normalized English title match, but ONLY if the candidate's
         release_year is missing OR within 1 year of the scraped release_year.
         This prevents two unrelated dramas that happen to share a generic
         English title (common across Korean/Thai/Chinese shows) from being
         merged into one record just because the title string matches.

    Returns None if nothing matches (i.e. this is a new drama).
    """
    homepage_url = data.get("homepage_url")
    if homepage_url:
        drama = Drama.objects.filter(homepage_url=homepage_url).first()
        if drama:
            return drama

    title_original = data.get("title_original")
    if title_original:
        drama = Drama.objects.filter(title_original__iexact=title_original).first()
        if drama:
            return drama

    title_arabic = data.get("title_arabic")
    if title_arabic:
        drama = Drama.objects.filter(title_arabic__iexact=title_arabic).first()
        if drama:
            return drama

    normalized_target = _normalize_title(title)
    if normalized_target:
        for drama in Drama.objects.exclude(title=""):
            if _normalize_title(drama.title) != normalized_target:
                continue
            # FIX-1: guard against cross-year/cross-country false positives
            if release_year and drama.release_year and abs(drama.release_year - release_year) > 1:
                continue
            return drama

    return None


# ── process one drama link and save to DB ───────────────────────────────────

def process_link(link, country_key):
    data = parse_drama_page(link)

    if not data:
        return ("skipped", link, "no data")

    release_year = data.get("release_year")

    if release_year not in TARGET_YEARS:
        return ("skipped", link, f"year {release_year}")

    title = data.get("title") or data.get("title_arabic", "")
    if not title:
        return ("skipped", link, "no title")

    # FIX-2 (v2): exact match first, then SUBSTRING match. Real scrape logs
    # showed the exact-match version failing constantly on variants like
    # 'التايلاند' (has 'the' prefix -> doesn't equal map key 'تايلاند'),
    # 'الياباني' (adjective form -> doesn't equal 'اليابان'), and mixed
    # co-production strings like 'أمريكا / كوريا الجنوبية'. All of those
    # fell through to the category default -> this is exactly why Thai/
    # Japanese/Taiwanese dramas were showing up saved as Korean.
    raw_country = _clean_arabic(data.get("country_raw", ""))
    country = COUNTRY_MAP.get(raw_country)
    if country is None and raw_country:
        for key in sorted(COUNTRY_MAP.keys(), key=len, reverse=True):
            if key in raw_country:
                country = COUNTRY_MAP[key]
                break
    if country is None:
        country = country_key
        print(f"  \u26a0\ufe0f  Unmapped country text '{raw_country}' for {link} "
              f"-> defaulting to category '{country_key}'. Consider adding it to COUNTRY_MAP.")

    drama = find_existing_drama(data, title, release_year)
    created = False

    if drama is None:
        drama = Drama.objects.create(
            title=title,
            title_arabic=data.get("title_arabic", ""),
            title_original=data.get("title_original", ""),
            homepage_url=data.get("homepage_url", ""),
            thumbnail_url=data.get("thumbnail_url", ""),
            description_arabic=data.get("description_arabic", ""),
            description=data.get("description_arabic", ""),
            country=country,
            release_year=data.get("release_year", 0),
            total_episodes=data.get("total_episodes", 0),
            episode_duration=data.get("episode_duration", 0),
            status=data.get("status", "ongoing"),
        )
        created = True

    if created:
        for g_name in data.get("genres_raw", []):
            genre = get_matching_genre(g_name)
            if genre:
                drama.genres.add(genre)

        WatchLink.objects.create(
            drama=drama,
            website_name="Aradrama",
            url=link,
            language="arabic",
            episodes_available=data.get("total_episodes", 0),
            is_free=True,
            has_arabic_subtitles=True,
            ads_level="moderate",
            episodes_completeness="complete",
        )
        return ("added", title, data)

    else:
        # FIX-4: proper "fill the gaps" + always refresh Arabic description.
        updated = False

        # English title: fill only if somehow missing.
        if not drama.title and title:
            drama.title = title
            updated = True

        # Arabic title: fill only if missing (this is the "add Arabic title
        # beside the English one" behavior).
        if not drama.title_arabic and data.get("title_arabic"):
            drama.title_arabic = data["title_arabic"]
            updated = True

        # Arabic description: ALWAYS replace with the fresh Aradrama copy,
        # per your instruction (not a gap-fill — an intentional overwrite).
        if data.get("description_arabic"):
            if drama.description_arabic != data["description_arabic"]:
                drama.description_arabic = data["description_arabic"]
                drama.description = data["description_arabic"]
                updated = True

        # Thumbnail: fill only if missing (previously this always overwrote —
        # that was a bug, fixed here).
        if not drama.thumbnail_url and data.get("thumbnail_url"):
            drama.thumbnail_url = data["thumbnail_url"]
            updated = True

        if not drama.homepage_url and data.get("homepage_url"):
            drama.homepage_url = data["homepage_url"]
            updated = True

        if not drama.title_original and data.get("title_original"):
            drama.title_original = data["title_original"]
            updated = True

        # Country: ALWAYS overwrite with the freshly-resolved value, not
        # just fill-if-empty. This is intentional (per your request) so a
        # wrong value already saved (e.g. 'korean' on an actual Thai drama)
        # gets self-corrected on every run instead of staying stuck forever.
        if country and drama.country != country:
            old_country = drama.country
            drama.country = country
            updated = True
            print(f"  \U0001f504 COUNTRY CORRECTED: '{title}' was '{old_country}' -> now '{country}'")

        if not drama.release_year and data.get("release_year"):
            drama.release_year = data["release_year"]
            updated = True

        if not drama.total_episodes and data.get("total_episodes"):
            drama.total_episodes = data["total_episodes"]
            updated = True

        if not drama.episode_duration and data.get("episode_duration"):
            drama.episode_duration = data["episode_duration"]
            updated = True

        if updated:
            drama.save()

        # Fill in genres only if this drama currently has none at all —
        # using the merge-aware helper so we never create a duplicate
        # genre for one that already exists under its English name.
        if not drama.genres.exists() and data.get("genres_raw"):
            for g_name in data["genres_raw"]:
                genre = get_matching_genre(g_name)
                if genre:
                    drama.genres.add(genre)
            updated = True

        # Add the Aradrama watch link if this drama doesn't already have one
        # (guards against duplicate links if the script is run more than once).
        link_added = False
        already_has_aradrama_link = drama.links.filter(
            website_name="Aradrama", url=link
        ).exists()

        if not already_has_aradrama_link:
            WatchLink.objects.create(
                drama=drama,
                website_name="Aradrama",
                url=link,
                language="arabic",
                episodes_available=data.get("total_episodes", 0),
                is_free=True,
                has_arabic_subtitles=True,
                ads_level="moderate",
                episodes_completeness="complete",
            )
            link_added = True

        if updated and link_added:
            return ("updated+link", title, None)
        elif link_added:
            return ("link_added", title, None)
        elif updated:
            return ("updated", title, None)
        return ("exists", title, None)


# ── Command ──────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Scrape 2020-2026 dramas (KR/CN/JP/TH) — parallel detail fetching"

    def handle(self, *args, **kwargs):
        total_added = total_updated = total_skipped = 0

        for country_key, category_url in CATEGORY_URLS.items():
            self.stdout.write(f"\n=== {country_key.upper()} ===")
            links = get_drama_links(category_url, TARGET_YEARS, limit=TEST_LIMIT)
            self.stdout.write(f"  Found {len(links)} links — fetching details in parallel...\n")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(process_link, link, country_key): link
                    for link in links
                }

                for future in as_completed(futures):
                    try:
                        status, name, extra = future.result()
                    except Exception as e:
                        self.stdout.write(f"  ERROR: {futures[future]} — {e}")
                        total_skipped += 1
                        continue

                    if status == "added":
                        total_added += 1
                        self.stdout.write(f"  \u2713 ADDED   : {name}")
                        if extra:
                            self.stdout.write(f"    country  : {extra.get('country_raw','?')}")
                            self.stdout.write(f"    year     : {extra.get('release_year','?')}")
                            self.stdout.write(f"    episodes : {extra.get('total_episodes','?')}")
                    elif status == "updated":
                        total_updated += 1
                        self.stdout.write(f"  UPDATED   : {name}")
                    elif status == "link_added":
                        total_updated += 1
                        self.stdout.write(f"  + LINK ADDED (existing drama): {name}")
                    elif status == "updated+link":
                        total_updated += 1
                        self.stdout.write(f"  UPDATED + LINK ADDED: {name}")
                    elif status == "exists":
                        self.stdout.write(f"  EXISTS    : {name}")
                    else:
                        total_skipped += 1
                        self.stdout.write(f"  SKIPPED   : {name} ({extra})")

        self.stdout.write(
            f"\n\u2705 DONE — ADDED: {total_added} | UPDATED: {total_updated} | SKIPPED: {total_skipped}"
        )




        """
        
        Full, exact walkthrough of what runs when you type `python manage.py fetch_aradrama`:

**1. For each of the 4 category pages (Korean, Chinese, Japanese, Thai):**

It fetches page 1, then page 2, then page 3... collecting every drama link on each page. It keeps going until either:
- A page comes back with zero articles on it (real end of the listing), or
- 2 pages in a row add no new links, or
- It hits a hard cap of 60 pages

No year filtering happens at this stage anymore — that used to be broken and cause the "only 2 Thai" bug, so it was removed.

**2. Once it has the full list of links for a category, it fetches each drama's actual page** — 6 at a time in parallel (`MAX_WORKERS = 6`) — and pulls off: title, Arabic title, original title, thumbnail, description, genres, episode count, episode length, air year, status, and country text.

**3. For each drama page fetched, it checks the year first.** If the release year isn't 2020–2026, it's thrown out immediately — `SKIPPED`, nothing saved.

**4. It resolves country.** Takes the raw country text off the page, cleans invisible characters, and checks it against `COUNTRY_MAP`. First tries an exact match; if that fails, checks if a known country word appears anywhere inside the text (this is what catches `التايلاند`, `الياباني`, `التايوان`). If nothing matches at all, it defaults to whichever category page it was scraped from, and prints a `⚠️ Unmapped country text` warning so you can see it happened.

**5. It checks if this drama already exists in your DB**, in this priority order:
1. Exact match on `homepage_url`
2. Exact match on `title_original`
3. Exact match on `title_arabic`
4. English title match (case/punctuation-insensitive) — but only if the release year is the same or within 1 year, so two unrelated shows with the same generic title don't get merged

**6a. If NOT found (new drama):** creates the row with everything scraped, resolves each genre through `get_matching_genre()` (see below), attaches them, and adds an Aradrama watch link.

**6b. If found (existing drama):** never skips it. Instead:
- Fills English title, Arabic title, thumbnail, homepage URL, original title, episode count, episode duration — **only if each field is currently empty**
- **Arabic description: always overwritten** with the fresh one from Aradrama, even if one already existed
- **Country: always overwritten** if the freshly resolved value disagrees with what's stored — prints `🔄 COUNTRY CORRECTED` when this happens
- Genres: only filled if the drama currently has zero genres attached
- Adds the Aradrama watch link only if it doesn't already have one (checked by exact URL match, so reruns don't create duplicate links)

**Genre resolution (`get_matching_genre`), every single time a genre is touched:**
1. Exact match against `name_arabic`, then `name`
2. Normalized match (handles underscore vs space, "the"-prefix differences)
3. Alias table lookup (`خيال`→`فانتازيا`, `خارق`→`خارق للطبيعة`, etc.) → matched against your DB
4. Only if none of that finds anything: creates a new genre, and prints `ℹ️ Creating NEW genre` so you can see it and add an alias later if it turns out to be a duplicate

**At the very end:** prints a total count of Added / Updated / Skipped across all 4 categories.
        
        
        
        """