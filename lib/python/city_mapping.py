# lib/python/city_mapping.py
#
# Three-tier city matcher.
#
# Tier 1 — Exact: case- and whitespace-insensitive equality against the master
#   city table (sheet "Cities" in the Arax master workbook).
# Tier 2 — Fuzzy: rapidfuzz token_set_ratio against the master list, returning
#   the top candidate if score >= 85, otherwise the top 5 alternatives.
# Tier 3 — District-aware: if the raw value contains a hyphenated district
#   suffix (e.g. "Wuppertal-Elberfeld", "Düsseldorf-Bilk"), strip the suffix
#   and retry tiers 1 & 2 against the parent city. The original string is
#   preserved in the result for audit.
#
# `match_city` returns a MatchResult union tagged with `kind`:
#   { kind: "exact",   raw, mapped }
#   { kind: "fuzzy",   raw, proposed, confidence, alternatives }
#   { kind: "unmatched", raw, candidates }

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union


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


def match_city(raw_city: str, mapping_df) -> MatchResult:  # type: ignore[no-untyped-def]
    """Resolve a raw rent-roll city string to the master city list.

    Implements the three-tier strategy described at the top of this file.
    """
    raise NotImplementedError("TODO: implement against real master workbook")
