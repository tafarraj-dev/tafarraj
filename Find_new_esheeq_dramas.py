"""
find_new_esheeq_dramas.py
---------------------------
For every drama in esheeq_turkish_index.json:

  1. Fuzzy-matches its title against your EXISTING 80 Turkish dramas.
     - If it MATCHES an existing drama -> do nothing, skip completely.
     - If it does NOT match anything   -> it's a new drama. Visit its
       individual page and scrape:
         - title          (Latin/Turkish, derived from the URL slug)
         - title_arabic   (the Arabic title text)
         - thumbnail_url
         - description_arabic
         - total_episodes (counted from episode links on the page)
         - watch_url      (the Esheeq page itself)

Nothing is written to your database. Only matched dramas are
skipped; new dramas are written to new_dramas_found.json for you
to review before deciding to add them (release_year and
episode_duration are NOT on Esheeq's pages, so you'll need to
fill those in yourself).

Run from your project root:
    pip install requests beautifulsoup4 rapidfuzz
    python find_new_esheeq_dramas.py
"""

import os
import sys
import json
import re
import time
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dramahere.settings")
import django
django.setup()

from Tafarraj.models import Drama
from rapidfuzz import fuzz

INDEX_FILE = "esheeq_turkish_index.json"
NEW_OUTPUT = "new_dramas_found.json"
MATCH_THRESHOLD = 80

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

NOISE_WORDS = [
    "مسلسل", "مترجم", "مدبلج", "الحلقة", "حلقة",
    "الموسم الأول", "الموسم الثاني", "الموسم الثالث", "الموسم الرابع",
    "الموسم", "الجزء",
]

LATIN_RE = re.compile(r"[A-Za-zÇĞİıÖŞÜçğıöşü0-9' .:&-]{3,}")


def clean_arabic(text):
    if not text:
        return ""
    for w in NOISE_WORDS:
        text = text.replace(w, " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_latin(text):
    matches = LATIN_RE.findall(text or "")
    return max(matches, key=len).strip() if matches else ""


def slug_to_title_case(url):
    """Turns a URL slug into a readable Latin title.
    e.g. '3isk-se-halef-koklerin-cagrisi-watch-esh-jh9tz' -> 'Halef Koklerin Cagrisi'
    """
    try:
        slug = url.rstrip("/").split("/series/")[-1]
    except IndexError:
        return ""
    slug = slug.replace("3isk-se-", "").replace("video-3isk-se-", "")
    slug = re.sub(r"-watch.*$", "", slug)
    words = slug.replace("-", " ").split()
    return " ".join(w.capitalize() for w in words)


def best_match_against_db(title, url, db_dramas):
    esheeq_candidates = [title, clean_arabic(title), extract_latin(title), slug_to_title_case(url)]

    best_score = 0
    for drama in db_dramas:
        db_candidates = [drama.title, drama.title_original, drama.title_arabic]
        for a in db_candidates:
            if not a:
                continue
            for b in esheeq_candidates:
                if not b:
                    continue
                score = fuzz.token_sort_ratio(a, b)
                if score > best_score:
                    best_score = score

    return best_score


def scrape_drama_details(page_url):
    """Visits a NEW drama's individual page and extracts full details."""
    details = {
        "title_arabic": None,
        "thumbnail_url": None,
        "description_arabic": None,
        "total_episodes": 0,
    }

    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Title (Arabic) - from og:title or <h1>
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            details["title_arabic"] = og_title["content"].replace("- قصة عشق", "").strip()
        else:
            h1 = soup.find("h1")
            if h1:
                details["title_arabic"] = h1.get_text(strip=True)

        # Thumbnail
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            details["thumbnail_url"] = og_image["content"]
        else:
            img = soup.find("img", src=re.compile(r"cdn\.3isk\.news"))
            if img and img.get("src"):
                details["thumbnail_url"] = img["src"]

        # Description (Arabic) - from og:description or meta description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            details["description_arabic"] = og_desc["content"].strip()
        else:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                details["description_arabic"] = meta_desc["content"].strip()

        # Episode count - count unique episode links on the page
        episode_links = soup.select("a[href*='episode-3isk']")
        episode_numbers = set()
        for a in episode_links:
            href = a.get("href", "")
            match = re.search(r"episode-(\d+)-watch", href)
            if match:
                episode_numbers.add(int(match.group(1)))
        details["total_episodes"] = len(episode_numbers) if episode_numbers else len(episode_links)

    except Exception as e:
        print(f"    ⚠️  Failed to scrape details: {e}")

    return details


def run():
    if not os.path.exists(INDEX_FILE):
        print(f"'{INDEX_FILE}' not found. Run the scraper first.")
        return

    with open(INDEX_FILE, encoding="utf-8") as f:
        esheeq_list = json.load(f)
    print(f"Loaded {len(esheeq_list)} entries from {INDEX_FILE}\n")

    db_dramas = list(Drama.objects.filter(country="turkish"))
    print(f"Comparing against {len(db_dramas)} existing Turkish dramas in your DB\n")

    new_results = []
    skipped_count = 0

    for i, entry in enumerate(esheeq_list):
        title = entry["title"]
        url = entry["url"]

        score = best_match_against_db(title, url, db_dramas)

        if score >= MATCH_THRESHOLD:
            # Already in DB -- do nothing
            skipped_count += 1
            continue

        # Not in DB -- it's new, scrape full details
        print(f"[{i+1}/{len(esheeq_list)}] NEW: {title} (best DB match score: {score:.0f})")
        details = scrape_drama_details(url)
        time.sleep(0.5)  # be polite to the server

        new_results.append({
            "title": slug_to_title_case(url),
            "title_arabic": details["title_arabic"] or title,
            "thumbnail_url": details["thumbnail_url"],
            "description_arabic": details["description_arabic"],
            "total_episodes": details["total_episodes"],
            "watch_url": url,
            "country": "turkish",
            "note": "release_year and episode_duration not available on Esheeq -- fill manually",
        })

    with open(NEW_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(new_results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"  Skipped (already in DB):    {skipped_count}")
    print(f"  NEW dramas found & scraped: {len(new_results)}  -> saved to {NEW_OUTPUT}")
    print("=" * 60)
    print("\nNothing was written to your database.")
    print(f"Review {NEW_OUTPUT} and tell me which ones to add.")


if __name__ == "__main__":
    run()