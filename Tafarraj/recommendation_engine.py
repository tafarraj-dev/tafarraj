"""
Metadata-based "if you liked X, try Y" engine.
"""
from django.core.cache import cache
from django.db.models import Q, Case, When, IntegerField
from collections import defaultdict
from django.db.models.functions import Coalesce
from .models import Drama
from .metadata_engine import combine_rating
from .scoring_config import (
    SIMILARITY_WEIGHTS,
    SIMILARITY_MIN_SCORE_RATIO,
    CANDIDATE_POOL_LIMIT,
    YEAR_GAP_FOR_ZERO_SCORE,
    EPISODE_GAP_FOR_ZERO_SCORE,
    RATING_GAP_FOR_ZERO_SCORE,
)

MIN_SIMILARITY_SCORE = 100 * SIMILARITY_MIN_SCORE_RATIO


def _jaccard(set_a, set_b):
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def _linear_proximity(value_a, value_b, zero_at_gap):
    if value_a is None or value_b is None:
        return 0.0
    gap = abs(value_a - value_b)
    if gap >= zero_at_gap:
        return 0.0
    return 1 - (gap / zero_at_gap)


def _score_candidate(anchor, anchor_genre_ids, anchor_tag_ids, candidate):
    candidate_genre_ids = set(candidate.genres.values_list('id', flat=True))
    candidate_tag_ids = set(candidate.tags.values_list('id', flat=True))

    # Uses the SAME combine_rating() as the ranking engine, so "this
    # drama's rating" means the same thing everywhere on the site
    # instead of ranking_engine and recommendation_engine each having
    # their own mdl-or-tmdb fallback that could disagree.
    anchor_rating = combine_rating(anchor)
    candidate_rating = combine_rating(candidate)

    breakdown = {
        'genre':    _jaccard(anchor_genre_ids, candidate_genre_ids),
        'tag':      _jaccard(anchor_tag_ids, candidate_tag_ids),
        'country':  1.0 if anchor.country == candidate.country else 0.0,
        'year':     _linear_proximity(anchor.release_year, candidate.release_year, YEAR_GAP_FOR_ZERO_SCORE),
        'episodes': _linear_proximity(anchor.total_episodes, candidate.total_episodes, EPISODE_GAP_FOR_ZERO_SCORE),
        'rating':   _linear_proximity(anchor_rating, candidate_rating, RATING_GAP_FOR_ZERO_SCORE),
    }

    weighted_total = sum(breakdown[key] * SIMILARITY_WEIGHTS[key] for key in SIMILARITY_WEIGHTS)
    score_out_of_100 = round(weighted_total * 100, 2)

    return score_out_of_100, breakdown


def get_similar_dramas_v2(drama, limit=6, debug=False):
    anchor_genre_ids = set(drama.genres.values_list('id', flat=True))
    anchor_tag_ids = set(drama.tags.values_list('id', flat=True))

    # NOTE: no longer excludes dramas without watch links — that caused
    # empty recommendation boxes when a whole country/genre had few
    # links. Instead, linked dramas are just sorted first (has_link=1)
    # by _score_candidate ordering below, unlinked ones still show.
    if anchor_genre_ids or anchor_tag_ids:
        candidates_qs = Drama.objects.filter(
            Q(genres__id__in=anchor_genre_ids) | Q(tags__id__in=anchor_tag_ids)
        ).exclude(id=drama.id).distinct()
    else:
        candidates_qs = Drama.objects.filter(country=drama.country).exclude(id=drama.id)

    # NOTE: this Coalesce is a DB-level APPROXIMATION used only to
    # pre-sort/truncate the candidate pool before real scoring happens
    # in Python below. A true vote-weighted combine (like
    # metadata_engine.combine_rating) isn't practical to express as a
    # single SQL expression, so this just picks whichever of
    # mdl_rating/tmdb_rating is present to get a reasonable initial
    # ordering. The actual similarity score used for ranking/filtering
    # candidates uses combine_rating() via _score_candidate() above.
    candidates_qs = candidates_qs.annotate(
        has_link=Case(
            When(links__isnull=False, then=1),
            default=0,
            output_field=IntegerField(),
        ),
        combined_rating=Coalesce('mdl_rating', 'tmdb_rating'),
    ).order_by('-has_link', '-combined_rating').distinct()

    candidates = list(
        candidates_qs.prefetch_related('genres', 'tags')[:CANDIDATE_POOL_LIMIT]
    )

    scored = []
    for candidate in candidates:
        score, breakdown = _score_candidate(drama, anchor_genre_ids, anchor_tag_ids, candidate)
        if score >= MIN_SIMILARITY_SCORE:
            scored.append((candidate, score, breakdown))

    # Sort by similarity score first, but nudge linked dramas ahead of
    # unlinked ones when scores are otherwise close.
    scored.sort(key=lambda item: (item[1], getattr(item[0], 'has_link', 0)), reverse=True)

    if len(scored) < limit:
        seen_ids = {c.id for c, _, _ in scored} | {drama.id}
        fallback = (
            Drama.objects.filter(country=drama.country)
            .exclude(id__in=seen_ids)
            .annotate(
                has_link=Case(
                    When(links__isnull=False, then=1),
                    default=0,
                    output_field=IntegerField(),
                ),
                combined_rating=Coalesce('mdl_rating', 'tmdb_rating'),
            )
            .order_by('-has_link', '-combined_rating')
            .distinct()[: limit - len(scored)]
        )
        scored += [(d, 0.0, {}) for d in fallback]

    top = scored[:limit]
    if debug:
        return top
    return [candidate for candidate, _, _ in top]



def _build_reco_index():
    index = cache.get('reco_index_v1')
    if index is not None:
        return index

    dramas = list(Drama.objects.all())
    drama_by_id = {d.id: d for d in dramas}

    genre_map = defaultdict(set)
    tag_map = defaultdict(set)
    genre_index = defaultdict(set)
    tag_index = defaultdict(set)

    for drama_id, genre_id in Drama.genres.through.objects.values_list('drama_id', 'genre_id'):
        genre_map[drama_id].add(genre_id)
        genre_index[genre_id].add(drama_id)

    for drama_id, tag_id in Drama.tags.through.objects.values_list('drama_id', 'tag_id'):
        tag_map[drama_id].add(tag_id)
        tag_index[tag_id].add(drama_id)

    linked_ids = set(Drama.objects.filter(links__isnull=False).values_list('id', flat=True).distinct())
    rating_map = {d.id: combine_rating(d) for d in dramas}

    index = {
        'drama_by_id': drama_by_id,
        'genre_map': genre_map,
        'tag_map': tag_map,
        'genre_index': genre_index,
        'tag_index': tag_index,
        'linked_ids': linked_ids,
        'rating_map': rating_map,
    }
    cache.set('reco_index_v1', index, timeout=None)
    return index
    

def get_similar_dramas_batch(anchors, limit=4):
    index = _build_reco_index()
    drama_by_id = index['drama_by_id']
    genre_map = index['genre_map']
    tag_map = index['tag_map']
    genre_index = index['genre_index']
    tag_index = index['tag_index']
    linked_ids = index['linked_ids']
    rating_map = index['rating_map']

    results = {}

    for anchor in anchors:
        anchor_genre_ids = genre_map.get(anchor.id, set())
        anchor_tag_ids = tag_map.get(anchor.id, set())

        if anchor_genre_ids or anchor_tag_ids:
            candidate_ids = set()
            for gid in anchor_genre_ids:
                candidate_ids |= genre_index.get(gid, set())
            for tid in anchor_tag_ids:
                candidate_ids |= tag_index.get(tid, set())
            candidate_ids.discard(anchor.id)
        else:
            candidate_ids = {
                d_id for d_id, d in drama_by_id.items()
                if d.country == anchor.country and d_id != anchor.id
            }

        anchor_rating = rating_map.get(anchor.id)
        scored = []

        for cid in candidate_ids:
            candidate = drama_by_id.get(cid)
            if candidate is None:
                continue
            candidate_genre_ids = genre_map.get(cid, set())
            candidate_tag_ids = tag_map.get(cid, set())
            candidate_rating = rating_map.get(cid)

            breakdown = {
                'genre':    _jaccard(anchor_genre_ids, candidate_genre_ids),
                'tag':      _jaccard(anchor_tag_ids, candidate_tag_ids),
                'country':  1.0 if anchor.country == candidate.country else 0.0,
                'year':     _linear_proximity(anchor.release_year, candidate.release_year, YEAR_GAP_FOR_ZERO_SCORE),
                'episodes': _linear_proximity(anchor.total_episodes, candidate.total_episodes, EPISODE_GAP_FOR_ZERO_SCORE),
                'rating':   _linear_proximity(anchor_rating, candidate_rating, RATING_GAP_FOR_ZERO_SCORE),
            }
            weighted_total = sum(breakdown[key] * SIMILARITY_WEIGHTS[key] for key in SIMILARITY_WEIGHTS)
            score = round(weighted_total * 100, 2)
            if score >= MIN_SIMILARITY_SCORE:
                has_link = 1 if cid in linked_ids else 0
                scored.append((candidate, score, has_link))

        scored.sort(key=lambda item: (item[1], item[2]), reverse=True)

        if len(scored) < limit:
            seen_ids = {c.id for c, _, _ in scored} | {anchor.id}
            fallback = [
                d for d_id, d in drama_by_id.items()
                if d.country == anchor.country and d_id not in seen_ids
            ]
            fallback.sort(
                key=lambda d: (1 if d.id in linked_ids else 0, rating_map.get(d.id) or 0),
                reverse=True
            )
            needed = limit - len(scored)
            scored += [(d, 0.0, 1 if d.id in linked_ids else 0) for d in fallback[:needed]]

        results[anchor.id] = [c for c, _, _ in scored[:limit]]

    return results