# -*- coding: utf-8 -*-
"""
Genre names that are NOT real TMDB genres -- they're descriptive labels
that belong in the Tag model instead. Used by migrate_tag_genres.py.

IMPORTANT: run merge_duplicate_genres_tags.py (Phase 1, with --commit)
BEFORE this file's script, so each of these already exists as a single
row (spelling duplicates already merged).
"""

TAG_LIKE_GENRES = [
    # merged duplicate-canonicals from Phase 1
    "انتقام",           # Revenge
    "مقتبس من مانجا",     # Adapted from Manga
    "شريحة من الحياة",    # Slice of Life
    "سفر عبر الزمن",      # Time Travel
    "كوميديا سوداء",      # Black Comedy
    "قوى خارقة",         # Superpowers
    "ويب دراما",         # Web Drama

    # standalone, no duplicates found
    "مدرسي",      # School
    "واقعي",      # Realistic
    "إنساني",     # Humanitarian
    "صداقة",      # Friendship
    "تحقيق",      # Investigation
    "مسابقة",     # Competition
    "سفر",        # Travel
    "آيدول",      # Idol
    "ترفيهي",     # Entertainment
    "تجسس",       # Espionage
    "شرطة",       # Police
    "مكتب",       # Office
    "مأساة",      # Tragedy
    "ويبتون",     # Webtoon
    "تنمر",       # Bullying
    "مواعدة",     # Dating
    "تسوق",       # Shopping
    "موضة",       # Fashion
    "مانغا",      # Manga
]