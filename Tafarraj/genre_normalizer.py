# -*- coding: utf-8 -*-
"""
genre_normalizer.py

Drop-in helper for your AraDrama import/scraper code, so it never dumps
raw "النوع" strings straight into Genre again.

Usage in your importer, wherever you currently do something like:

    for raw_value in ara_drama_item['النوع'].split(','):
        genre, _ = Genre.objects.get_or_create(name=raw_value.strip())
        drama.genres.add(genre)

replace it with:

    from Tafarraj.genre_normalizer import classify_genre_field

    for raw_value in ara_drama_item['النوع'].split(','):
        result = classify_genre_field(raw_value)
        if result.kind == 'genre':
            genre = Genre.objects.get(name=result.canonical_name)  # already exists
            drama.genres.add(genre)
        elif result.kind == 'tag':
            tag, _ = Tag.objects.get_or_create(name=result.canonical_name)
            drama.tags.add(tag)
        else:  # 'unknown'
            # log it -- do NOT guess. See UNRECOGNIZED_LOG below.
            log_unrecognized_genre_value(raw_value, drama)
"""
from collections import namedtuple

from Tafarraj.genre_tag_mapping import (
    CANONICAL_GENRES,
    GENRE_ALIASES,
    TAG_LIKE_GENRES,
    MANUAL_REVIEW,
)

ClassificationResult = namedtuple('ClassificationResult', ['kind', 'canonical_name', 'raw_value'])

# Reverse lookup: canonical Arabic name -> canonical English name,
# so raw Arabic strings that exactly match a canonical genre's Arabic
# name are recognized directly (not just merge-mapped duplicates).
_ARABIC_TO_CANONICAL = {
    arabic: english for english, arabic in CANONICAL_GENRES.items() if arabic
}


def classify_genre_field(raw_value):
    """
    Classify a single raw value from AraDrama's "النوع" field.

    Returns a ClassificationResult with kind in {'genre', 'tag', 'unknown'}.
    - 'genre'   -> canonical_name is the English Genre.name to attach.
    - 'tag'     -> canonical_name is the Tag.name to attach (use raw
                   cleaned value, since tags don't have an English form).
    - 'unknown' -> not recognized at all. Do NOT create a Genre or Tag
                   automatically. Log it for manual review -- this is
                   how new unmapped variants get caught before they
                   pollute the table again.
    """
    value = (raw_value or '').strip()
    if not value:
        return ClassificationResult('unknown', None, raw_value)

    # Exact match to a canonical English name
    if value in CANONICAL_GENRES:
        return ClassificationResult('genre', value, raw_value)

    # Exact match to a canonical Arabic name
    if value in _ARABIC_TO_CANONICAL:
        return ClassificationResult('genre', _ARABIC_TO_CANONICAL[value], raw_value)

    # Known duplicate/variant spelling of a canonical genre
    if value in GENRE_ALIASES:
        return ClassificationResult('genre', GENRE_ALIASES[value], raw_value)

    # Known tag-like value
    if value in TAG_LIKE_GENRES:
        return ClassificationResult('tag', value, raw_value)

    # Known ambiguous value -- deliberately NOT auto-classified
    if value in MANUAL_REVIEW:
        return ClassificationResult('unknown', None, raw_value)

    # Never seen before
    return ClassificationResult('unknown', None, raw_value)
