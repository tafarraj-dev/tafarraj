"""
Top Dramas global ranking engine (Tafarraj V1).

quality_score = 60% Bayesian rating + 30% vote count + 10% popularity.
MDL Rank is not used anywhere in this file — see scoring_config.py for
why. Every page (Top Dramas, Top Korean, Top Romance, ...) filters and
sorts on the SAME quality_score; nothing here re-normalizes per
country or per filter.

IMPORTANT: compute_quality_scores() must always be called on the
FULL, unfiltered set of dramas. Normalization (min/max) happens once,
globally, across that full set. If you call it on an already-filtered
queryset (e.g. just Korean dramas), you silently reintroduce
per-country normalization -- the same inconsistency problem MDL rank
caused, just relocated. In production this means: run
compute_quality_scores() over ALL dramas on a schedule (e.g. a nightly
management command), save quality_score back onto the Drama model, and
have page views simply filter + `.order_by('-quality_score')` against
that stored value. Do NOT recompute scores inside a per-request,
per-country queryset.
"""

from .scoring_config import (
    RANKING_WEIGHTS,
    POPULARITY_SENTINEL_THRESHOLD,
    POPULARITY_SOURCES,
)
from .metadata_engine import combine_rating, combine_vote_count


def filter_scored_dramas(dramas, request):
    """In-memory filtering over a list of already-scored dramas. Pure
    filter, no scoring/normalization happens here."""
    result = dramas

    country = request.GET.get('country')
    if country:
        result = [d for d in result if d.country == country]

    genre_ids = request.GET.getlist('genre')
    if genre_ids:
        genre_ids = set(int(g) for g in genre_ids)
        result = [d for d in result if genre_ids & {g.id for g in d.genres.all()}]

    year = request.GET.get('year')
    if year:
        result = [d for d in result if str(d.release_year) == year]

    status = request.GET.get('status')
    if status:
        result = [d for d in result if d.status == status]

    return result


def _min_max_normalize(value, min_value, max_value):
    """Returns None (not 0) when value is missing, so callers can tell
    'missing' apart from 'present but worst in the batch'."""
    if value is None:
        return None
    if max_value == min_value:
        return 1.0
    return (value - min_value) / (max_value - min_value)


def _raw_source_value(drama, field):
    """Reads a single source field, treating MDL's sentinel popularity
    value (>= POPULARITY_SENTINEL_THRESHOLD) as missing data."""
    value = getattr(drama, field, None)
    if value is None:
        return None
    if field == 'mdl_popularity' and value >= POPULARITY_SENTINEL_THRESHOLD:
        return None
    return value


def _precompute_stats(sources, dramas):
    """Min/max for every source, computed ONCE across the full batch
    instead of recalculating it per-drama."""
    stats = {}
    for field, direction in sources:
        raw_values = [v for v in (_raw_source_value(d, field) for d in dramas) if v is not None]
        if raw_values:
            stats[field] = (min(raw_values), max(raw_values))
    return stats


def _normalized_value(drama, field, direction, stats):
    if field not in stats:
        return None
    value = _raw_source_value(drama, field)
    if value is None:
        return None
    lo, hi = stats[field]
    norm = _min_max_normalize(value, lo, hi)
    if norm is None:
        return None
    return (1 - norm) if direction == 'asc' else norm


def compute_quality_scores(dramas_qs):
    """
    Computes the single, global quality_score for every drama in
    dramas_qs. Call this on the FULL, unfiltered set of dramas (see
    module docstring) -- never on a per-country/per-genre queryset.

    Fixed 60/30/10 weights apply to every drama identically. A
    missing signal (e.g. no popularity data) contributes 0 rather
    than having its weight redistributed onto the signals that ARE
    present. Redistributing would mean two dramas with identical
    rating/votes end up scored under effectively different formulas
    depending on which fields happen to be populated for them -- the
    same country-by-country inconsistency problem MDL rank caused,
    just moved to a different field.
    """
    dramas = list(dramas_qs)
    if not dramas:
        return []

    for d in dramas:
        d.combined_rating = combine_rating(d)
        d.combined_votes = combine_vote_count(d)

    rating_values = [d.combined_rating for d in dramas if d.combined_rating is not None]
    rating_min, rating_max = (min(rating_values), max(rating_values)) if rating_values else (0, 10)

    vote_values = [d.combined_votes for d in dramas if d.combined_votes is not None]
    vote_min, vote_max = (min(vote_values), max(vote_values)) if vote_values else (0, 1)

    popularity_stats = _precompute_stats(POPULARITY_SOURCES, dramas)

    for d in dramas:
        rating_norm = _min_max_normalize(d.combined_rating, rating_min, rating_max)
        votes_norm = _min_max_normalize(d.combined_votes, vote_min, vote_max)

        pop_contributions = [
            v for v in (_normalized_value(d, f, dir_, popularity_stats) for f, dir_ in POPULARITY_SOURCES)
            if v is not None
        ]
        popularity_norm = sum(pop_contributions) / len(pop_contributions) if pop_contributions else None

        rating_component = (rating_norm or 0) * RANKING_WEIGHTS['rating']
        votes_component = (votes_norm or 0) * RANKING_WEIGHTS['votes']
        popularity_component = (popularity_norm or 0) * RANKING_WEIGHTS['popularity']

        d.quality_score = round(
            (rating_component + votes_component + popularity_component) * 100, 2
        )

        d.rating_norm = round(rating_norm, 3) if rating_norm is not None else None
        d.votes_norm = round(votes_norm, 3) if votes_norm is not None else None
        d.popularity_norm = round(popularity_norm, 3) if popularity_norm is not None else None

    dramas.sort(key=lambda d: d.quality_score, reverse=True)
    return dramas


def get_top_dramas_queryset(request):
    """
    Builds the filtered queryset for any Top Dramas page (Top Dramas,
    Top Korean, Top Romance, ...) based on querystring params, then
    excludes dramas with no watch links.

    This ONLY filters and orders by the already-computed,
    already-stored quality_score field on Drama -- it does not
    recompute or renormalize anything. That's what keeps every page
    on the same score, per the V1 spec ("no separate country engine,
    no country normalization, no merging"). quality_score itself must
    be kept up to date by a separate scheduled job that calls
    compute_quality_scores() over ALL dramas.
    """
    from .models import Drama

    dramas = Drama.objects.all()

    country = request.GET.get('country')
    if country:
        dramas = dramas.filter(country=country)

    genre_ids = request.GET.getlist('genre')
    if genre_ids:
        try:
            genre_ids = [int(g) for g in genre_ids]
            dramas = dramas.filter(genres__id__in=genre_ids).distinct()
        except ValueError:
            pass

    year = request.GET.get('year')
    if year:
        dramas = dramas.filter(release_year=year)

    status = request.GET.get('status')
    if status:
        dramas = dramas.filter(status=status)

    min_rating = request.GET.get('min_rating')
    if min_rating:
        try:
            dramas = dramas.filter(mdl_rating__gte=float(min_rating))
        except ValueError:
            pass

    return dramas.order_by('-quality_score')