# lib/python/inheritance.py
#
# Looks up prior Arax adjustments for cities that appear in the current deal,
# so reviewers don't have to re-rate cities Arax has already rated.
#
# Behaviour
# ---------
# - Scans a folder of prior deal workbooks (the canonical "deals" folder).
# - For each workbook, reads the Ratings sheet and harvests
#   (city -> AdjustmentRecord(value, source_deal, date_rated)).
# - When the same city appears in multiple prior deals, the most-recent
#   `date_rated` wins. Ties are broken alphabetically by source_deal for
#   determinism.
# - Returns a flat dict { city: AdjustmentRecord }.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class AdjustmentRecord:
    value: float  # 0..10
    source_deal: str
    date_rated: date


def lookup_prior_adjustments(deals_folder: Path) -> dict[str, AdjustmentRecord]:
    """Return the most-recent prior adjustment per city across all deal workbooks.

    See module docstring for tie-breaking rules.
    """
    raise NotImplementedError("TODO: implement against real master workbook")
