# -*- coding: utf-8 -*-
"""
genre_tag_mapping.py

Single source of truth for the Tafarraj genre/tag cleanup.

This file contains NO Django imports and does NOT touch the database.
It's pure data + lookup helpers, imported by:
  - management/commands/merge_duplicate_genres.py   (Phase 1)
  - management/commands/migrate_tag_genres.py        (Phase 2)
  - scraper/genre_normalizer.py                      (Phase 3, for future imports)

Derived from the actual Genre.objects.values_list('name', flat=True) dump
you posted (137 rows) cross-referenced against the 33 canonical MDL genres.

If you disagree with any classification below, this is the ONLY file you
need to edit -- the migration commands just read from it.
"""

# ---------------------------------------------------------------------------
# 1. Canonical genres (MDL vocabulary). name -> name_arabic
#    These rows are the "keepers". Everything else either merges into one
#    of these, or becomes a Tag.
# ---------------------------------------------------------------------------
CANONICAL_GENRES = {
    'Romance': 'رومانسي',
    'Wuxia': 'ووشيا',
    'Drama': 'دراما',
    'Fantasy': 'فانتازيا',
    'Food': 'طعام',
    'Comedy': 'كوميدي',
    'Thriller': 'إثارة',
    'Historical': 'تاريخي',
    'Crime': 'جريمة',
    'War': 'حرب',
    'Mystery': 'غموض',
    'Music': 'موسيقى',
    'Life': 'حياة',
    'Melodrama': 'ميلودراما',
    'Action': 'أكشن',
    'Sci-Fi': 'خيال علمي',
    'Business': 'أعمال',
    'Medical': 'طبي',
    'Youth': 'شبابي',
    'Adventure': 'مغامرة',
    'Military': 'عسكري',
    'Horror': 'رعب',
    'Sports': 'رياضة',
    'Political': 'سياسي',
    'Supernatural': 'خارق للطبيعة',
    'Psychological': 'نفسي',
    'Law': 'قانوني',
    'Family': 'عائلي',
    'Martial Arts': 'فنون قتالية',
    'Tokusatsu': '',
    'Documentary': 'وثائقي',
    'Sitcom': '',
    'Mature': '',
}

# ---------------------------------------------------------------------------
# 2. Duplicate Genre rows -> canonical English genre name they merge into.
#    Key = the "name" field value exactly as it appears in your DB dump.
#    These are spelling variants, missing hamzas, underscores-for-spaces,
#    plural/singular, noun/adjective forms of an EXISTING canonical genre.
# ---------------------------------------------------------------------------
GENRE_ALIASES = {
    # Romance
    'رومانسي': 'Romance',
    'رمانسي': 'Romance',
    'رومنسي': 'Romance',
    'رومـانسي': 'Romance',   # contains tatweel (ـ)
    'رومانسية': 'Romance',

    # Drama
    'دراما': 'Drama',
    'درامي': 'Drama',

    # Comedy
    'كوميدي': 'Comedy',
    'هزلي': 'Comedy',            # "farcical/comedic" -- reasonable confidence
    'كوميديbr />': 'Comedy',     # corrupted scrape artifact (stray HTML tag)

    # Thriller
    'إثارة': 'Thriller',
    'اثارة': 'Thriller',
    'تشويق': 'Thriller',         # "suspense"

    # Historical
    'تاريخي': 'Historical',
    'تاريخى': 'Historical',      # alternate ya' spelling

    # Crime
    'جريمة': 'Crime',

    # Mystery
    'غموض': 'Mystery',
    'غامض': 'Mystery',           # "mysterious" (adjective form)

    # Life
    'حياة': 'Life',

    # Action
    'أكشن': 'Action',

    # Sci-Fi
    'خيال علمي': 'Sci-Fi',
    'خيال_علمي': 'Sci-Fi',
    'خيالي علمي': 'Sci-Fi',

    # Business
    'أعمال': 'Business',

    # Medical
    'طبي': 'Medical',

    # Youth
    'شبابي': 'Youth',

    # Adventure
    'مغامرة': 'Adventure',
    'مغامرات': 'Adventure',      # plural

    # Military / War
    'عسكري': 'Military',
    'حربي': 'War',               # "war-related" -- closer to War than Military

    # Horror
    'رعب': 'Horror',

    # Sports
    'رياضي': 'Sports',           # "athletic" (adjective form)

    # Political
    'سياسي': 'Political',

    # Supernatural
    'خارق للطبيعة': 'Supernatural',

    # Psychological
    'نفسي': 'Psychological',

    # Law
    'قانوني': 'Law',
    'قانون': 'Law',              # "law" noun form

    # Family
    'عائلي': 'Family',

    # Music
    'موسيقى': 'Music',
    'موسيقي': 'Music',           # alternate spelling

    # Documentary
    'وثائقي': 'Documentary',

    # Wuxia
    'ووشيا': 'Wuxia',

    # Food
    'طعام': 'Food',

    # Melodrama
    'ميلودراما': 'Melodrama',
    'ميلودرامي': 'Melodrama',
}

# ---------------------------------------------------------------------------
# 3. Genre rows that are actually TAGS (descriptive, not a genre).
#    These get copied to Drama.tags and their Drama<->Genre relationship
#    removed. List = the "name" field value in your DB dump.
# ---------------------------------------------------------------------------
TAG_LIKE_GENRES = [
    'آيدول',              # idol
    'إنتقام',             # revenge (alt spelling)
    'إنساني',             # humane / human-interest
    'السفر عبر الزمن',    # time travel (alt phrasing)
    'انتقام',             # revenge
    'تجسس',               # espionage / spy
    'تحقيق',              # investigation
    'ترفيهي',             # entertainment
    'تسوق',               # shopping
    'تنمر',               # bullying
    'حقبة',               # era / period
    'دراما الويب',        # web drama
    'سفر',                # travel
    'سفر عبر الزمن',      # time travel
    'سفر_عبر_الزمن',      # time travel (underscore)
    'شرطة',               # police
    'شريحة من الحياة',    # slice of life
    'شريحة من حياة',      # slice of life (alt)
    'صداقة',              # friendship
    'طبخ',                # cooking
    'قوى خارقة',          # superpowers
    'قوى_خارقة',          # superpowers (underscore)
    'كوميديا سوداء',      # black comedy
    'كوميديا_سوداء',      # black comedy (underscore)
    'مأساة',              # tragedy
    'مانغا',              # manga
    'مدرسي',              # school-setting
    'مراهقة',             # adolescence / teen
    'مسابقة',             # competition
    'مقتبس من مانجا',     # adapted from manga (alt spelling)
    'مقتبس من مانغا',     # adapted from manga
    'مكتب',               # office
    'مواعدة',             # dating
    'موضة',               # fashion
    'واقعي',              # realistic
    'ويب دراما',          # web drama (alt)
    'ويبتون',             # webtoon
]

# ---------------------------------------------------------------------------
# 4. Ambiguous rows. Genuinely unclear whether these are a genre variant
#    (and if so, which one) or a tag. NOT touched by any automated script.
#    Decide manually, then either add to GENRE_ALIASES or TAG_LIKE_GENRES
#    and re-run the relevant command.
# ---------------------------------------------------------------------------
MANUAL_REVIEW = [
    'خارق',    # "super" -- Supernatural? or a tag on its own?
    'خيال',    # "fantasy/imagination" -- Sci-Fi? Fantasy? too bare to tell
    'خيالي',   # "imaginary/fantastical" -- same ambiguity as خيال
    'عاطفي',   # "emotional" -- Romance/Melodrama flavor tag, or its own tag?
]


def get_canonical_target(genre_name):
    """Return the canonical English genre name a duplicate should merge
    into, or None if genre_name is not a known duplicate."""
    return GENRE_ALIASES.get(genre_name)


def is_tag_like(genre_name):
    return genre_name in TAG_LIKE_GENRES


def is_manual_review(genre_name):
    return genre_name in MANUAL_REVIEW
