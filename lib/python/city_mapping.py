# lib/python/city_mapping.py
#
# Three-tier city matcher against the master workbook's "City Mapping" tab.
#
# The City Mapping table has 10,696 rows, with column A as the canonical
# municipality name. This is what the master workbook's INDEX/MATCH and
# XLOOKUP formulas resolve against. If a city in the rent roll does not
# map exactly to a row in column A, the formulas return #N/A and the
# whole deal block becomes useless.
#
# Tier 1 - Exact: case- and whitespace-normalised equality. Most rent rolls
#   (including the sample) hit this 100%.
#
# Tier 2 - Fuzzy: rapidfuzz token_set_ratio against the master list.
#   Confidence >= 90 returns a single proposed match; 70-89 returns the
#   match plus alternatives for human review; below 70 escalates to Tier 3.
#
# Tier 3 - District-aware: if the raw value contains a hyphenated district
#   suffix (e.g. "Wuppertal-Elberfeld", "Düsseldorf-Bilk", "Köln-Mülheim"),
#   strip the suffix and retry tiers 1 and 2 against the parent city.
#   The original string is preserved in the result for audit.
#
# Returns one of three result kinds tagged with `kind`:
#   { kind: "exact",     raw, mapped }
#   { kind: "fuzzy",     raw, proposed, confidence, alternatives }
#   { kind: "unmatched", raw, candidates }

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Literal, Optional, Union

import openpyxl
from rapidfuzz import fuzz, process

# Thresholds
EXACT_CONFIDENCE = 100
FUZZY_HIGH = 90  # >= this score = confident fuzzy
FUZZY_LOW = 70  # < this score = unmatched, return top candidates
MAX_ALTERNATIVES = 5


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExactMatch:
    kind: Literal["exact"]
    raw: str
    mapped: str


@dataclass(frozen=True)
class FuzzyMatch:
    kind: Literal["fuzzy"]
    raw: str
    proposed: str
    confidence: int
    alternatives: list[str]


@dataclass(frozen=True)
class Unmatched:
    kind: Literal["unmatched"]
    raw: str
    candidates: list[str]


MatchResult = Union[ExactMatch, FuzzyMatch, Unmatched]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _normalise(s: str) -> str:
    """Lower-case, strip, collapse whitespace. Keep umlauts (the master keeps them too)."""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _fold_umlauts(s: str) -> str:
    """Fold German umlauts and ß for accent-insensitive matching."""
    return (
        s.replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
        .replace("ß", "ss")
        .replace("Ä", "A")
        .replace("Ö", "O")
        .replace("Ü", "U")
    )


def _strip_district_suffix(s: str) -> Optional[str]:
    """If the city has a hyphenated district, strip it: 'Wuppertal-Elberfeld' -> 'Wuppertal'.

    Returns None if no hyphen found.
    """
    if "-" not in s:
        return None
    # Some city names legitimately have hyphens (Bingen-am-Rhein has spaces,
    # not hyphens; but Bad-Kreuznach is two words). We only strip if there's
    # exactly one hyphen and the left side is a plausible city.
    parts = s.split("-", 1)
    parent = parts[0].strip()
    if len(parent) < 3:
        return None
    return parent


# ---------------------------------------------------------------------------
# Load the City Mapping table
# ---------------------------------------------------------------------------


@dataclass
class CityMapping:
    """In-memory representation of the master workbook's City Mapping tab.

    Built once per process call. Column A is the canonical city name (the
    string the master workbook's formulas match against).
    """

    canonical_cities: list[str]  # column A values, deduped, in original case
    canonical_lookup: dict[str, str]  # normalised -> original case
    canonical_lookup_folded: dict[str, str]  # umlaut-folded normalised -> original


def load_city_mapping(master_xlsm_bytes: bytes) -> CityMapping:
    """Load the City Mapping tab (column A) from the master workbook bytes."""
    wb = openpyxl.load_workbook(io.BytesIO(master_xlsm_bytes), keep_vba=True, read_only=True, data_only=True)
    if "City Mapping" not in wb.sheetnames:
        raise ValueError(
            f"Master workbook is missing the 'City Mapping' sheet. "
            f"Available sheets: {wb.sheetnames}"
        )
    ws = wb["City Mapping"]

    cities: list[str] = []
    seen: set[str] = set()
    canonical_lookup: dict[str, str] = {}
    canonical_lookup_folded: dict[str, str] = {}

    # First row is the header ("Municipality"); start from row 2
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, max_col=1, values_only=True), start=2):
        cell = row[0]
        if cell is None:
            continue
        s = str(cell).strip()
        if not s:
            continue
        norm = _normalise(s)
        if norm in seen:
            continue
        seen.add(norm)
        cities.append(s)
        canonical_lookup[norm] = s
        # Also index by umlaut-folded form, but only if it's a NEW key (don't
        # overwrite a canonical match - "Munchen" would clobber "München" otherwise)
        folded = _fold_umlauts(norm)
        if folded != norm and folded not in canonical_lookup_folded:
            canonical_lookup_folded[folded] = s

    return CityMapping(
        canonical_cities=cities,
        canonical_lookup=canonical_lookup,
        canonical_lookup_folded=canonical_lookup_folded,
    )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def match_city(raw_city: str, mapping: CityMapping) -> MatchResult:
    """Resolve a raw rent-roll city string to the master city list.

    Implements the three-tier strategy described at the top of this file.
    """
    raw = str(raw_city).strip()
    if not raw:
        return Unmatched(kind="unmatched", raw=raw_city, candidates=[])

    # Tier 1 - Exact (normalised)
    norm = _normalise(raw)
    if norm in mapping.canonical_lookup:
        return ExactMatch(kind="exact", raw=raw, mapped=mapping.canonical_lookup[norm])

    # Tier 1b - Umlaut-folded exact (e.g. "Munchen" matches "München", "koln" matches "Köln")
    folded = _fold_umlauts(norm)
    if folded in mapping.canonical_lookup_folded:
        # Treat as fuzzy at 95% since we made a small change (umlaut substitution)
        return FuzzyMatch(
            kind="fuzzy",
            raw=raw,
            proposed=mapping.canonical_lookup_folded[folded],
            confidence=95,
            alternatives=[],
        )

    # Tier 2 - Fuzzy
    # process.extract returns list of (match_string, score, index) tuples
    matches = process.extract(
        raw,
        mapping.canonical_cities,
        scorer=fuzz.token_set_ratio,
        limit=MAX_ALTERNATIVES,
    )
    if matches:
        top_match, top_score, _ = matches[0]
        if top_score >= FUZZY_HIGH:
            # High confidence fuzzy
            alternatives = [m[0] for m in matches[1:4]]  # next 3 as alternatives
            return FuzzyMatch(
                kind="fuzzy",
                raw=raw,
                proposed=top_match,
                confidence=int(top_score),
                alternatives=alternatives,
            )
        if top_score >= FUZZY_LOW:
            # Medium confidence - propose but as fuzzy (review screen will show)
            alternatives = [m[0] for m in matches[1:]]
            return FuzzyMatch(
                kind="fuzzy",
                raw=raw,
                proposed=top_match,
                confidence=int(top_score),
                alternatives=alternatives,
            )

    # Tier 3 - District-aware: strip hyphen suffix and retry
    parent = _strip_district_suffix(raw)
    if parent and parent.lower() != raw.lower():
        parent_norm = _normalise(parent)
        if parent_norm in mapping.canonical_lookup:
            # Found exact parent. Treat as fuzzy with high confidence since
            # the AM needs to be told we dropped the district.
            return FuzzyMatch(
                kind="fuzzy",
                raw=raw,
                proposed=mapping.canonical_lookup[parent_norm],
                confidence=92,
                alternatives=[],
            )
        # Try fuzzy on parent
        parent_matches = process.extract(
            parent,
            mapping.canonical_cities,
            scorer=fuzz.token_set_ratio,
            limit=MAX_ALTERNATIVES,
        )
        if parent_matches and parent_matches[0][1] >= FUZZY_HIGH:
            top_match, top_score, _ = parent_matches[0]
            alternatives = [m[0] for m in parent_matches[1:4]]
            return FuzzyMatch(
                kind="fuzzy",
                raw=raw,
                proposed=top_match,
                confidence=int(top_score),
                alternatives=alternatives,
            )

    # Tier 3 fallback - unmatched with top candidates for human review
    candidates = [m[0] for m in matches[:MAX_ALTERNATIVES]] if matches else []
    return Unmatched(kind="unmatched", raw=raw, candidates=candidates)


# ---------------------------------------------------------------------------
# Bulk match (convenience for api/process.py)
# ---------------------------------------------------------------------------


@dataclass
class CityMatchSummary:
    exact_matches: list[ExactMatch] = field(default_factory=list)
    fuzzy_matches: list[FuzzyMatch] = field(default_factory=list)
    unmatched: list[Unmatched] = field(default_factory=list)
    audit_log: list[str] = field(default_factory=list)


def match_all_cities(
    raw_cities: list[str],
    mapping: CityMapping,
) -> CityMatchSummary:
    """Match a list of unique raw city strings against the City Mapping table.

    Returns three buckets and an audit log.
    """
    summary = CityMatchSummary()
    seen: set[str] = set()
    unique_cities: list[str] = []
    for c in raw_cities:
        norm = _normalise(c)
        if norm in seen:
            continue
        seen.add(norm)
        unique_cities.append(c)

    for raw in unique_cities:
        result = match_city(raw, mapping)
        if isinstance(result, ExactMatch):
            summary.exact_matches.append(result)
        elif isinstance(result, FuzzyMatch):
            summary.fuzzy_matches.append(result)
        else:
            summary.unmatched.append(result)

    summary.audit_log.append(
        f"City matching: {len(summary.exact_matches)} exact, "
        f"{len(summary.fuzzy_matches)} fuzzy, "
        f"{len(summary.unmatched)} unmatched "
        f"(across {len(unique_cities)} unique cities)"
    )
    return summary
