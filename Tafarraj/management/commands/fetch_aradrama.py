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
}

TARGET_YEARS = [2025, 2026]
TEST_LIMIT = None

# How many drama detail pages to fetch in parallel
# Keep this at 5-8 to avoid getting rate-limited/blocked
MAX_WORKERS = 6

COUNTRY_MAP = {
    "كوريا الجنوبية": "korean",
    "كوريا": "korean",
    "اليابان": "japanese",
    "الصين": "chinese",
    "تايوان": "chinese",
    "المغرب": "moroccan",
    "تركيا": "turkish",
}


# ── unchanged helpers ──────────────────────────────────────────────────────────

def get_drama_links(category_url, target_years, limit=None):
    links = []
    page = 1
    stop = False

    while not stop:
        if limit and len(links) >= limit:
            break

        url = f"{category_url}page/{page}/" if page > 1 else category_url
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
        except Exception as e:
            print(f"  Request error on page {page}: {e}")
            break

        if res.status_code != 200:
            break

        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("article.post")
        if not articles:
            break

        for article in articles:
            if limit and len(links) >= limit:
                stop = True
                break

            year_badge = article.select_one(".b_right, .yr, .year")
            year = None
            if year_badge:
                match = re.search(r'20\d{2}', year_badge.text)
                if match:
                    year = int(match.group())

            if year and year < min(target_years):
                stop = True
                break

            if year and year not in target_years:
                continue

            a_tag = article.select_one("a.first_A, a[href*='aradramatv']")
            if a_tag and a_tag.get("href"):
                href = a_tag["href"]
                if href not in links:
                    links.append(href)

        page += 1
        time.sleep(0.3)  # reduced from 0.5

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
            data["country_raw"] = value

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


# ── NEW: process one drama link and save to DB ─────────────────────────────────

def process_link(link, country_key):
    """Fetch + parse one drama page. Returns a status string for logging."""
    data = parse_drama_page(link)

    if not data:
        return ("skipped", link, "no data")

    title = data.get("title") or data.get("title_arabic", "")
    if not title:
        return ("skipped", link, "no title")

    country = COUNTRY_MAP.get(data.get("country_raw", ""), country_key)

    drama, created = Drama.objects.get_or_create(
        title=title,
        defaults={
            "title_arabic":       data.get("title_arabic", ""),
            "title_original":     data.get("title_original", ""),
            "thumbnail_url":      data.get("thumbnail_url", ""),
            "description_arabic": data.get("description_arabic", ""),
            "description":        data.get("description_arabic", ""),
            "country":            country,
            "release_year":       data.get("release_year", 0),
            "total_episodes":     data.get("total_episodes", 0),
            "episode_duration":   data.get("episode_duration", 0),
            "status":             data.get("status", "ongoing"),
        }
    )

    if created:
        for g_name in data.get("genres_raw", []):
            genre, _ = Genre.objects.get_or_create(
                name=g_name,
                defaults={"name_arabic": g_name}
            )
            drama.genres.add(genre)

        WatchLink.objects.create(
            drama=drama,
            website_name="AraДrama",
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
        updated = False
        if not drama.thumbnail_url and data.get("thumbnail_url"):
            drama.thumbnail_url = data["thumbnail_url"]
            updated = True
        if not drama.description_arabic and data.get("description_arabic"):
            drama.description_arabic = data["description_arabic"]
            drama.description = data["description_arabic"]
            updated = True
        if updated:
            drama.save()
            return ("updated", title, None)
        return ("exists", title, None)


# ── Command ────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Scrape 2025/2026 dramas — parallel detail fetching"

    def handle(self, *args, **kwargs):
        total_added = total_updated = total_skipped = 0

        for country_key, category_url in CATEGORY_URLS.items():
            self.stdout.write(f"\n=== {country_key.upper()} ===")
            links = get_drama_links(category_url, TARGET_YEARS, limit=TEST_LIMIT)
            self.stdout.write(f"  Found {len(links)} links — fetching details in parallel...\n")

            # Submit all links to thread pool; results come back as they finish
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
                        self.stdout.write(f"  ✓ ADDED   : {name}")
                        if extra:
                            self.stdout.write(f"    country  : {extra.get('country_raw','?')}")
                            self.stdout.write(f"    year     : {extra.get('release_year','?')}")
                            self.stdout.write(f"    episodes : {extra.get('total_episodes','?')}")
                    elif status == "updated":
                        total_updated += 1
                        self.stdout.write(f"  UPDATED   : {name}")
                    elif status == "exists":
                        self.stdout.write(f"  EXISTS    : {name}")
                    else:
                        total_skipped += 1
                        self.stdout.write(f"  SKIPPED   : {name} ({extra})")

        self.stdout.write(
            f"\n✅ DONE — ADDED: {total_added} | UPDATED: {total_updated} | SKIPPED: {total_skipped}"
        )