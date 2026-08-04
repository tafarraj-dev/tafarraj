"""
Central tuning file. Every weight and threshold used by the
recommendation engine and the ranking engine lives here — nowhere else
in the codebase should contain a hardcoded number for these algorithms.
"""

# ── RECOMMENDATION ENGINE ───────────────────────────────────
SIMILARITY_WEIGHTS = {
    'genre':    0.25,
    'tag':      0.60,
    'country':  0.05,
    'year':     0.03,
    'episodes': 0.03,
    'rating':   0.04,
}

SIMILARITY_MIN_SCORE_RATIO = 0.30

CANDIDATE_POOL_LIMIT = 300

YEAR_GAP_FOR_ZERO_SCORE = 10
EPISODE_GAP_FOR_ZERO_SCORE = 40
RATING_GAP_FOR_ZERO_SCORE = 3.0


# ── TOP DRAMAS RANKING (Tafarraj V1) ─────────────────────────
# quality_score = 60% Bayesian rating + 30% vote count + 10% popularity.
#
# MDL Rank is intentionally NOT a signal here. It only exists for a
# tiny, uneven slice of the catalog (present for most Chinese/Korean/
# Thai titles, ~3% of Japanese, 0% of Turkish), so using it makes
# scoring inconsistent across countries. Do not add a 'rank' entry
# back to RANKING_WEIGHTS or reintroduce a RANK_SOURCES list until MDL
# rank coverage is fixed for every country.
RANKING_WEIGHTS = {
    'rating':     0.85,
    'votes':      0.05,
    'popularity': 0.10,
}

POPULARITY_SENTINEL_THRESHOLD = 90000


# ── MULTI-SOURCE COMBINING ───────────────────────────────────
# This section is what makes rating/votes/popularity use ALL available
# sources for a drama (MDL, TMDB, and whatever gets added later)
# instead of picking just one.
#
# To add a new metadata source later (a new site's API), add one
# entry to the relevant list below. combine_rating() / combine_vote_count()
# in metadata_engine.py and compute_quality_scores() in
# ranking_engine.py loop over these lists — no other code needs to
# change when a new source is added.

# (rating_field, vote_count_field_or_None)
RATING_SOURCES = [
    ('mdl_rating', None),               # MDL: no vote count stored on the model yet
    ('tmdb_rating', 'tmdb_vote_count'),
]

# Fixed assumed weight used ONLY when a source has no real vote count
# to weight by — either because the source has no votes field at all
# on the Drama model (MDL, currently), or this specific drama is
# missing that value. This is a documented approximation, not
# measured data, and it is intentionally modest (lower than most real
# vote counts) so it doesn't out-muscle sources that DO have real
# votes behind them. It also feeds combine_vote_count(), which is the
# standalone Vote Count signal (30% of quality_score).
#
# TODO: delete this constant and its usages in metadata_engine.py once
# MDL vote counts are added to the Drama model — at that point every
# source will contribute a real vote-weighted value.
DEFAULT_VOTE_WEIGHT_NO_VOTE_COUNT = 50

# (popularity_field, direction)
#   'asc'  = LOWER raw number is MORE popular (rank-like — e.g. MDL's
#            popularity field is a positional rank: #1 is most popular)
#   'desc' = HIGHER raw number is MORE popular (score-like — e.g.
#            TMDB's popularity is a continuous score)
POPULARITY_SOURCES = [
    ('mdl_popularity', 'asc'),
    ('tmdb_popularity', 'desc'),
]

# MDL Rank is deliberately excluded from Top Dramas scoring (see the
# RANKING_WEIGHTS comment above). There is no RANK_SOURCES list here
# on purpose — do not add one back into this file or into
# ranking_engine.py.