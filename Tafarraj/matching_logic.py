"""
matching_logic.py

Pure scoring/classification logic for deciding whether an MDL-origin Drama row
and an Aradrama-origin Drama row are actually the same drama.

Design goals:
- No Django import. No DB access. Takes plain data in, returns a verdict.
- Testable with synthetic dicts (see `if __name__ == "__main__"` block below).
- Multi-signal: title similarity + year + country + episode count, combined,
  never a single field deciding alone (this is what the old get_or_create(title=...)
  and the abandoned enrich_from_aradrama.py both got wrong).

Classification output is one of:
    MATCH       - safe to auto-merge
    UNCERTAIN   - send to manual review report, do NOT touch DB
    NO_MATCH    - skip entirely

Nothing in this file writes to a database. It only computes a verdict for a
single (mdl_row, aradrama_row) pair. The Django management command
(find_potential_duplicates.py) is what loops over the real tables and calls this.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Tunable thresholds. Adjust these after eyeballing a first report, not blind.
# ---------------------------------------------------------------------------

TITLE_AUTO_MATCH_MIN = 90       # title score >= this, with no contradictions -> MATCH
TITLE_UNCERTAIN_MIN = 70        # title score >= this (but < auto min) -> candidate for UNCERTAIN
TITLE_NO_MATCH_MAX = 70         # below this, and nothing else saves it -> NO_MATCH

YEAR_WEAK_TOLERANCE = 1         # off-by-this-many-years counts as "weak support", not contradiction
YEAR_CONTRADICT_THRESHOLD = 2   # off by this many years or more = contradiction

EPISODE_WEAK_TOLERANCE = 2      # +/- this many episodes counts as weak support
EPISODE_CONTRADICT_THRESHOLD = 3  # off by more than this = contradiction


class Verdict(str, Enum):
    MATCH = "MATCH"
    UNCERTAIN = "UNCERTAIN"
    NO_MATCH = "NO_MATCH"


class SignalResult(str, Enum):
    SUPPORTS = "supports"
    WEAK_SUPPORTS = "weak_supports"
    CONTRADICTS = "contradicts"
    STRONG_CONTRADICTS = "strong_contradicts"
    NEUTRAL = "neutral"  # data missing on one/both sides, signal has no opinion


@dataclass
class MatchResult:
    verdict: Verdict
    title_score: float
    best_title_pair: tuple[str, str]  # which two variant strings scored highest
    year_signal: SignalResult
    country_signal: SignalResult
    episode_signal: SignalResult
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "title_score": round(self.title_score, 1),
            "best_title_pair": self.best_title_pair,
            "year_signal": self.year_signal.value,
            "country_signal": self.country_signal.value,
            "episode_signal": self.episode_signal.value,
            "reasons": self.reasons,
        }


# ---------------------------------------------------------------------------
# Helpers to read fields off either a dict or a Django model instance,
# so this module works identically against ORM objects and plain test dicts.
# ---------------------------------------------------------------------------

def _get(record: Any, field_name: str) -> Optional[Any]:
    if isinstance(record, dict):
        return record.get(field_name)
    return getattr(record, field_name, None)


def _normalize_title(raw: Optional[str]) -> str:
    """Lowercase, strip punctuation/whitespace noise so 'The King's Affair'
    and 'the kings affair' compare cleanly. Deliberately simple - no
    transliteration, no stemming. Arabic strings pass through unchanged
    except whitespace/punctuation trimming, which still helps."""
    if not raw:
        return ""
    text = raw.strip().lower()
    text = re.sub(r"[^\w\s\u0600-\u06FF]", "", text)  # keep word chars + Arabic block
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_variants(record: Any, field_names: list[str]) -> list[str]:
    variants = []
    for f in field_names:
        raw = _get(record, f)

        # Django RelatedManager (M2M or reverse FK) - has .all(), not a plain value.
        if hasattr(raw, "all") and callable(getattr(raw, "all")):
            try:
                related_objs = list(raw.all())
            except Exception:
                related_objs = []
            for obj in related_objs:
                text = _extract_text_from_related(obj)
                norm = _normalize_title(text)
                if norm:
                    variants.append(norm)
            continue

        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                norm = _normalize_title(str(item))
                if norm:
                    variants.append(norm)
            continue
        if isinstance(raw, str) and any(sep in raw for sep in (",", ";", "|")):
            # e.g. alternate_titles stored as "Title A, Title B; Title C"
            for part in re.split(r"[,;|]", raw):
                norm = _normalize_title(part)
                if norm:
                    variants.append(norm)
            continue
        norm = _normalize_title(raw)
        if norm:
            variants.append(norm)
    return variants


def _extract_text_from_related(obj: Any) -> str:
    """
    Best-effort extraction of a title string from a related model instance
    (e.g. an AlternateTitle row). We don't know the exact field name your
    related model uses, so try common candidates in order, then fall back
    to str(obj) as a last resort.
    """
    if isinstance(obj, str):
        return obj
    for attr in ("title", "name", "alt_title", "alternate_title", "value", "text"):
        val = getattr(obj, attr, None)
        if isinstance(val, str) and val.strip():
            return val
    fallback = str(obj)
    if " object (" in fallback:
        # Django's default __str__ - not usable text, skip it rather than pollute matching
        return ""
    return fallback


def _string_similarity(a: str, b: str) -> float:
    """0-100 similarity score using stdlib difflib (no extra dependency)."""
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio() * 100


def best_title_score(
    mdl_record: Any,
    aradrama_record: Any,
    mdl_title_fields: list[str] = ("title", "title_original", "alternate_titles"),
    aradrama_title_fields: list[str] = ("title", "title_arabic", "title_original"),
) -> tuple[float, tuple[str, str]]:
    """
    Compare every MDL title variant against every Aradrama title variant,
    return the single best-scoring pair. This is the "check ALL available
    title variants, take the best score" rule from the design notes.
    """
    mdl_variants = _title_variants(mdl_record, list(mdl_title_fields))
    ara_variants = _title_variants(aradrama_record, list(aradrama_title_fields))

    best = 0.0
    best_pair = ("", "")
    for mv in mdl_variants:
        for av in ara_variants:
            score = _string_similarity(mv, av)
            if score > best:
                best = score
                best_pair = (mv, av)
    return best, best_pair


# ---------------------------------------------------------------------------
# Individual signal evaluators
# ---------------------------------------------------------------------------

def year_signal(mdl_record: Any, aradrama_record: Any) -> SignalResult:
    y1 = _get(mdl_record, "release_year")
    y2 = _get(aradrama_record, "release_year")
    if y1 is None or y2 is None:
        return SignalResult.NEUTRAL
    diff = abs(int(y1) - int(y2))
    if diff == 0:
        return SignalResult.SUPPORTS
    if diff <= YEAR_WEAK_TOLERANCE:
        return SignalResult.WEAK_SUPPORTS
    if diff >= YEAR_CONTRADICT_THRESHOLD:
        return SignalResult.CONTRADICTS
    return SignalResult.NEUTRAL


def country_signal(mdl_record: Any, aradrama_record: Any) -> SignalResult:
    c1 = _get(mdl_record, "country")
    c2 = _get(aradrama_record, "country")
    if not c1 or not c2:
        return SignalResult.NEUTRAL
    if str(c1).strip().lower() == str(c2).strip().lower():
        return SignalResult.SUPPORTS
    return SignalResult.STRONG_CONTRADICTS


def episode_signal(mdl_record: Any, aradrama_record: Any) -> SignalResult:
    e1 = _get(mdl_record, "total_episodes")
    e2 = _get(aradrama_record, "total_episodes")
    if not e1 or not e2:
        return SignalResult.NEUTRAL
    diff = abs(int(e1) - int(e2))
    if diff == 0:
        return SignalResult.SUPPORTS
    if diff <= EPISODE_WEAK_TOLERANCE:
        return SignalResult.WEAK_SUPPORTS
    if diff > EPISODE_CONTRADICT_THRESHOLD:
        return SignalResult.CONTRADICTS
    return SignalResult.NEUTRAL


# ---------------------------------------------------------------------------
# Top-level classifier
# ---------------------------------------------------------------------------

def classify_pair(mdl_record: Any, aradrama_record: Any) -> MatchResult:
    title_score, best_pair = best_title_score(mdl_record, aradrama_record)

    y_sig = year_signal(mdl_record, aradrama_record)
    c_sig = country_signal(mdl_record, aradrama_record)
    e_sig = episode_signal(mdl_record, aradrama_record)

    signals = [y_sig, c_sig, e_sig]
    has_strong_contradiction = SignalResult.STRONG_CONTRADICTS in signals
    contradiction_count = sum(
        1 for s in signals if s in (SignalResult.CONTRADICTS, SignalResult.STRONG_CONTRADICTS)
    )
    weak_support_count = sum(1 for s in signals if s == SignalResult.WEAK_SUPPORTS)

    reasons = []

    # --- Hard stop: strong contradiction (country mismatch) always kills auto-match ---
    if has_strong_contradiction:
        reasons.append("country mismatch is a strong contradiction")
        if title_score >= TITLE_AUTO_MATCH_MIN:
            # very similar titles but different country - suspicious, needs a human,
            # don't auto-skip in case it's a remake or a data-entry error worth checking
            reasons.append(f"title score {title_score:.1f} is high despite country mismatch")
            return MatchResult(Verdict.UNCERTAIN, title_score, best_pair, y_sig, c_sig, e_sig, reasons)
        reasons.append(f"title score {title_score:.1f} not high enough to override country mismatch")
        return MatchResult(Verdict.NO_MATCH, title_score, best_pair, y_sig, c_sig, e_sig, reasons)

    # --- High title score path ---
    if title_score >= TITLE_AUTO_MATCH_MIN:
        if contradiction_count == 0:
            reasons.append(f"title score {title_score:.1f} >= {TITLE_AUTO_MATCH_MIN}, no contradictions")
            return MatchResult(Verdict.MATCH, title_score, best_pair, y_sig, c_sig, e_sig, reasons)
        else:
            reasons.append(
                f"title score {title_score:.1f} >= {TITLE_AUTO_MATCH_MIN} but "
                f"{contradiction_count} contradicting signal(s) present"
            )
            return MatchResult(Verdict.UNCERTAIN, title_score, best_pair, y_sig, c_sig, e_sig, reasons)

    # --- Moderate title score path ---
    if title_score >= TITLE_UNCERTAIN_MIN:
        if contradiction_count == 0:
            reasons.append(
                f"moderate title score {title_score:.1f} but all other signals agree "
                f"({weak_support_count} weak support signal(s))"
            )
            return MatchResult(Verdict.UNCERTAIN, title_score, best_pair, y_sig, c_sig, e_sig, reasons)
        else:
            reasons.append(
                f"moderate title score {title_score:.1f} and {contradiction_count} contradicting signal(s)"
            )
            return MatchResult(Verdict.NO_MATCH, title_score, best_pair, y_sig, c_sig, e_sig, reasons)

    # --- Low title score: only worth a second look if everything else strongly agrees ---
    all_support = all(s == SignalResult.SUPPORTS for s in signals if s != SignalResult.NEUTRAL)
    non_neutral_signals = [s for s in signals if s != SignalResult.NEUTRAL]
    if title_score >= 50 and non_neutral_signals and all_support:
        reasons.append(
            f"low-ish title score {title_score:.1f} but every available non-title signal supports a match "
            "(e.g. title stored in an unindexed script/translation) - flagged for human eyes"
        )
        return MatchResult(Verdict.UNCERTAIN, title_score, best_pair, y_sig, c_sig, e_sig, reasons)

    reasons.append(f"title score {title_score:.1f} < {TITLE_UNCERTAIN_MIN}, insufficient support elsewhere")
    return MatchResult(Verdict.NO_MATCH, title_score, best_pair, y_sig, c_sig, e_sig, reasons)


# ---------------------------------------------------------------------------
# Self-test: synthetic sanity checks only (NOT calibrated against real data,
# per instructions - these just confirm the logic doesn't have obvious bugs).
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cases = [
        (
            "obvious same drama, same everything",
            {"title": "Crash Landing on You", "title_original": "", "release_year": 2020,
             "country": "South Korea", "total_episodes": 16},
            {"title": "Crash Landing on You", "title_arabic": "الهبوط الاضطراري عليك",
             "title_original": "", "release_year": 2020, "country": "South Korea", "total_episodes": 16},
            Verdict.MATCH,
        ),
        (
            "same drama, minor year drift + near-identical episode count",
            {"title": "The Glory", "title_original": "", "release_year": 2022,
             "country": "South Korea", "total_episodes": 16},
            {"title": "The Glory", "title_arabic": "المجد", "title_original": "",
             "release_year": 2023, "country": "South Korea", "total_episodes": 15},
            Verdict.MATCH,  # year weak-support, episode weak-support, no contradiction
        ),
        (
            "Drama #6956-style false match: similar-ish title, wrong country",
            {"title": "My Love", "title_original": "", "release_year": 2021,
             "country": "South Korea", "total_episodes": 16},
            {"title": "My Love", "title_arabic": "حبيبي", "title_original": "",
             "release_year": 2021, "country": "Thailand", "total_episodes": 16},
            Verdict.UNCERTAIN,  # title identical but country strongly contradicts -> human review
        ),
        (
            "clearly unrelated dramas",
            {"title": "Reborn Rich", "title_original": "", "release_year": 2022,
             "country": "South Korea", "total_episodes": 16},
            {"title": "Weightlifting Fairy Kim Bok Joo", "title_arabic": "", "title_original": "",
             "release_year": 2016, "country": "South Korea", "total_episodes": 16},
            Verdict.NO_MATCH,
        ),
        (
            "same drama but MDL title is English, Aradrama only has Arabic title stored",
            {"title": "Business Proposal", "title_original": "", "release_year": 2022,
             "country": "South Korea", "total_episodes": 12},
            {"title": "", "title_arabic": "عرض عمل", "title_original": "",
             "release_year": 2022, "country": "South Korea", "total_episodes": 12},
            Verdict.NO_MATCH,  # no comparable title text at all -> correctly can't match on title alone
        ),
        (
            "missing country data on both sides, decent title + year match",
            {"title": "Twenty Five Twenty One", "title_original": "", "release_year": 2022,
             "country": None, "total_episodes": 16},
            {"title": "Twenty Five Twenty One", "title_arabic": "", "title_original": "",
             "release_year": 2022, "country": None, "total_episodes": 16},
            Verdict.MATCH,
        ),
    ]

    passed = 0
    for name, mdl, ara, expected in cases:
        result = classify_pair(mdl, ara)
        ok = result.verdict == expected
        passed += int(ok)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        print(f"        expected={expected.value}  got={result.verdict.value}  "
              f"title_score={result.title_score:.1f}  pair={result.best_title_pair}")
        print(f"        signals: year={result.year_signal.value} country={result.country_signal.value} "
              f"episode={result.episode_signal.value}")
        print(f"        reasons: {result.reasons}")
        print()

    print(f"{passed}/{len(cases)} synthetic sanity checks passed")