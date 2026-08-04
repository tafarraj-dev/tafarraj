"""
matching.py

Shared matching engine for the Tafarraj import pipeline.

Answers exactly one question, regardless of which source (MDL or AraDrama)
is asking it:

    "Given this candidate drama, does a Drama row already exist in the
    database for it — and if so, which one?"

Used by:
    - management/commands/import_mdl.py      (Script 1)
    - management/commands/update_mdl.py      (Script 2, only needs the
      mdl_id tier, but imports from here to stay consistent)
    - management/commands/import_aradrama.py (Script 3)

Matching priority (first confident hit wins, we stop there):
    1. MDL ID                      — exact, unique, always trusted
    2. Exact title + year + country
    3. Normalized title + year + country
    4. Alternate titles + year + country
    5. High-confidence fuzzy title match + year + country

Country + year alone (no title signal at all) is intentionally NOT a match
tier on its own — too many distinct dramas share a country and year, and a
false-positive merge is much more damaging than a missed match (which just
means a manual review or a slightly duplicate row you can merge later).

Nothing in this file writes to the database or scrapes anything. It only
reads and compares.
"""

from dataclasses import dataclass
from typing import Optional
import re

from django.db.models import Q

from rapidfuzz import fuzz

from Tafarraj.models import Drama, AlternateTitle


# Tune this if fuzzy matching feels too loose or too strict once you see
# real results. 90 is deliberately conservative — we'd rather miss a match
# and create a near-duplicate you can merge manually than wrongly merge two
# different dramas into one record.
FUZZY_MATCH_THRESHOLD = 90


@dataclass
class MatchResult:
    drama: Optional[Drama]
    tier: Optional[str]  # which rule matched, for logging. None if no match.

    @property
    def found(self) -> bool:
        return self.drama is not None


def normalize_title(title: str) -> str:
    """
    Lowercase, strip punctuation/whitespace noise, collapse multiple spaces.
    Used for tier 3 (normalized title) and as a pre-filter before fuzzy
    matching, so we're not fuzzy-comparing raw strings with different
    casing/punctuation making otherwise-identical titles look distant.
    """
    if not title:
        return ""
    text = title.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)   # drop punctuation
    text = re.sub(r"\s+", " ", text)      # collapse whitespace
    return text


def find_existing_drama(
    *,
    mdl_id: Optional[str] = None,
    title: str,
    year: Optional[int] = None,
    country: Optional[str] = None,
    alternate_titles: Optional[list[str]] = None,
) -> MatchResult:
    """
    The one entry point every importer calls before creating a new Drama.

    All arguments except `title` are optional because AraDrama entries
    won't have an mdl_id, and some sources may be missing year or country
    for a given item — the function degrades gracefully through the tiers
    it has enough data for.
    """
    alternate_titles = alternate_titles or []

    # --- Tier 1: MDL ID -----------------------------------------------
    # Exact and unique on the model, so if this hits, we're done -
    # no need to consider anything else.
    if mdl_id:
        drama = Drama.objects.filter(mdl_id=mdl_id).first()
        if drama:
            return MatchResult(drama=drama, tier="mdl_id")

    # --- Tier 2: exact title + year + country ---------------------------
    if year and country:
        drama = Drama.objects.filter(
            title__iexact=title, release_year=year, country=country
        ).first()
        if drama:
            return MatchResult(drama=drama, tier="exact_title_year_country")

    # --- Tier 3: normalized title + year + country ----------------------
    # Drama.title isn't stored normalized, so we normalize the candidate
    # and compare against a normalized version of each same-year/country
    # row. This tier only makes sense once tier 2 (exact) has already
    # failed, and it's cheap because year+country narrows the queryset
    # down first.
    if year and country:
        normalized_candidate = normalize_title(title)
        same_year_country = Drama.objects.filter(release_year=year, country=country)
        for drama in same_year_country:
            if normalize_title(drama.title) == normalized_candidate:
                return MatchResult(drama=drama, tier="normalized_title_year_country")

    # --- Tier 4: alternate titles + year + country -----------------------
    if alternate_titles and year and country:
        normalized_alts = {normalize_title(t) for t in alternate_titles if t}
        candidates = AlternateTitle.objects.filter(
            drama__release_year=year, drama__country=country
        ).select_related("drama")
        for alt in candidates:
            if normalize_title(alt.title) in normalized_alts:
                return MatchResult(drama=alt.drama, tier="alternate_title_year_country")

    # --- Tier 5: high-confidence fuzzy title match + year + country -----
    # Deliberately last resort, and deliberately still scoped to
    # year+country - we never fuzzy-match across different years or
    # countries, since that's how two unrelated dramas end up merged.
    if year and country:
        normalized_candidate = normalize_title(title)
        best_drama = None
        best_score = 0
        for drama in Drama.objects.filter(release_year=year, country=country):
            score = fuzz.ratio(normalized_candidate, normalize_title(drama.title))
            if score > best_score:
                best_score = score
                best_drama = drama
        if best_drama and best_score >= FUZZY_MATCH_THRESHOLD:
            return MatchResult(drama=best_drama, tier=f"fuzzy_title ({best_score:.0f}%)")

    # --- No confident match anywhere ------------------------------------
    return MatchResult(drama=None, tier=None)