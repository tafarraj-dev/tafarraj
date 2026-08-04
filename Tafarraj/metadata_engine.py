from .scoring_config import RATING_SOURCES, DEFAULT_VOTE_WEIGHT_NO_VOTE_COUNT

MINIMUM_VOTES_FOR_FULL_TRUST = 50
GLOBAL_AVERAGE_RATING = 7.5


def _rating_contributions(drama):
    """
    Shared by combine_rating() and combine_vote_count() so both use
    the exact same per-source (rating, votes) pairs — same sources,
    same fallback vote weight when a source has no real vote count.
    """
    contributions = []

    for rating_field, vote_field in RATING_SOURCES:
        rating = getattr(drama, rating_field, None)
        if rating is None:
            continue

        votes = getattr(drama, vote_field, None) if vote_field else None
        if votes is None:
            votes = DEFAULT_VOTE_WEIGHT_NO_VOTE_COUNT

        contributions.append((rating, votes))

    return contributions


def combine_rating(drama):
    """
    Bayesian-adjusted rating (never the raw rating). Blends every
    available rating source, weighted by votes, then shrinks toward
    the global average based on total vote confidence — so e.g. 9.8
    from 5 votes doesn't outrank 8.7 from 15,000 votes.
    """
    contributions = _rating_contributions(drama)
    if not contributions:
        return None

    total_votes = sum(v for _, v in contributions)
    if total_votes == 0:
        return None

    raw_rating = sum(r * v for r, v in contributions) / total_votes

    m = MINIMUM_VOTES_FOR_FULL_TRUST
    C = GLOBAL_AVERAGE_RATING

    return (
        (total_votes / (total_votes + m)) * raw_rating
        + (m / (total_votes + m)) * C
    )


def combine_vote_count(drama):
    """
    Total vote weight backing this drama's rating, summed across
    sources. This is the standalone Vote Count signal (30% of
    quality_score) — distinct from how votes are used *inside*
    combine_rating() to weight/shrink the rating itself. Returns None
    if the drama has no rating sources at all (so it's excluded from
    the vote-count normalization batch rather than counted as 0).
    """
    contributions = _rating_contributions(drama)
    if not contributions:
        return None

    return sum(v for _, v in contributions)