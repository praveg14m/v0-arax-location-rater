# lib/python/inheritance.py
#
# Look up prior Arax Adjustments so cities Arax has already rated don't have
# to be re-rated. Per the brief: "if a city has been rated in a prior deal,
# we inherit the previous Arax Adjustment as a starting point and mark it in
# blue."
#
# How it works
# ------------
# The tool maintains a `deals/` folder (path configurable via env var
# DEALS_FOLDER, default ./deals) containing prior deal workbooks named
# `YYMMDD_Ratings_<DealName>.xlsm`. On each run, this module:
#
#   1. Lists every .xlsm in the folder
#   2. Parses the filename for date and deal name
#   3. Opens each, reads the Location Ratings tab, and harvests every
#      (city, CC_value) pair where CC has a numeric value
#   4. Builds a dict {city -> most-recent AdjustmentRecord}, with ties
#      broken by filename date
#
# Robustness
# ----------
# - Filenames that don't match the expected pattern are skipped with a log
#   line, not an error.
# - Workbooks that fail to open are skipped with a log line.
# - The deals folder being absent is not an error - the dict is just empty,
#   and the run proceeds normally with no inherited values.

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import openpyxl

# Filename pattern: YYMMDD_Ratings_<DealName>.xlsm
DEAL_FILENAME_RE = re.compile(r"^(\d{6})_Ratings_(.+)\.xlsm$", re.IGNORECASE)

# Location Ratings column indices (must stay in sync with workbook_writer.py)
LR_F_COL = 6  # city name
LR_CC_COL = 81  # Arax Adjustment


@dataclass
class AdjustmentRecord:
    """A prior Arax Adjustment to inherit."""

    city: str  # canonical city name (as written in the prior workbook's F column)
    value: float  # 0-10 score
    source_deal: str  # deal name extracted from filename
    date_rated: date  # date extracted from filename


@dataclass
class InheritanceSummary:
    adjustments: dict[str, AdjustmentRecord] = field(default_factory=dict)
    source_deals_scanned: list[str] = field(default_factory=list)
    skipped_files: list[tuple[str, str]] = field(default_factory=list)  # (filename, reason)
    audit_log: list[str] = field(default_factory=list)


def _parse_filename(filename: str) -> Optional[tuple[date, str]]:
    """Extract (date, deal_name) from a YYMMDD_Ratings_<DealName>.xlsm filename."""
    m = DEAL_FILENAME_RE.match(filename)
    if not m:
        return None
    date_str, deal_name = m.group(1), m.group(2)
    try:
        # YYMMDD - assume 20YY
        d = datetime.strptime(date_str, "%y%m%d").date()
        return (d, deal_name)
    except ValueError:
        return None


def _harvest_adjustments_from_workbook(
    path: Path,
) -> list[tuple[str, float]]:
    """Open a deal workbook and return list of (city, CC_value) pairs.

    Reads the Location Ratings tab, walks rows in F column. For every row with
    a non-empty F (city name) AND a numeric CC value, emit one pair. The CC
    value may have been written manually by an AM or inherited from an earlier
    deal; either way it's an Arax Adjustment we can carry forward.
    """
    pairs: list[tuple[str, float]] = []
    try:
        wb = openpyxl.load_workbook(path, keep_vba=True, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return pairs

    if "Location Ratings" not in wb.sheetnames:
        return pairs
    ws = wb["Location Ratings"]

    # Walk rows; we don't know the exact city-row positions in arbitrary prior
    # workbooks, so we scan every row that has both a city name (F) and a
    # numeric CC value.
    for row in ws.iter_rows(values_only=False):
        if len(row) < LR_CC_COL:
            continue
        f_cell = row[LR_F_COL - 1]
        cc_cell = row[LR_CC_COL - 1]
        city = f_cell.value
        if not isinstance(city, str) or not city.strip():
            continue
        # Skip header rows and W. Avg. rows that might have a city-like string
        # but obviously aren't city rows (e.g. "Hagen" is fine, "PROJECT FALCON - W. Avg." is not)
        s = city.strip()
        if " - " in s or s.upper() == s and len(s) > 4:
            # Heuristic: "DEAL NAME" headers are all-caps; W. Avg. rows contain " - "
            continue
        cc = cc_cell.value
        # Accept int/float; reject formula strings or None
        if isinstance(cc, (int, float)):
            pairs.append((s, float(cc)))

    return pairs


def lookup_prior_adjustments(
    deals_folder: Optional[Path] = None,
) -> InheritanceSummary:
    """Scan a folder of prior deal workbooks and return inherited adjustments.

    If `deals_folder` is None, reads from env var DEALS_FOLDER. If that's also
    absent, defaults to ./deals. If the folder doesn't exist, returns an empty
    summary with a one-line audit note.
    """
    summary = InheritanceSummary()

    if deals_folder is None:
        env_folder = os.environ.get("DEALS_FOLDER", "deals")
        deals_folder = Path(env_folder)

    if not deals_folder.exists():
        summary.audit_log.append(
            f"Inheritance: deals folder {deals_folder} does not exist; no prior adjustments"
        )
        return summary

    if not deals_folder.is_dir():
        summary.audit_log.append(
            f"Inheritance: {deals_folder} is not a directory; skipped"
        )
        return summary

    # Collect all candidate files
    candidates = sorted(deals_folder.glob("*.xlsm"))
    summary.audit_log.append(
        f"Inheritance: scanning {len(candidates)} candidate files in {deals_folder}"
    )

    # Most recent first so we can short-circuit collisions
    parsed_files: list[tuple[date, str, Path]] = []
    for path in candidates:
        parsed = _parse_filename(path.name)
        if not parsed:
            summary.skipped_files.append((path.name, "filename does not match YYMMDD_Ratings_*.xlsm"))
            continue
        d, deal = parsed
        parsed_files.append((d, deal, path))

    parsed_files.sort(key=lambda t: t[0], reverse=True)  # newest first

    for d, deal_name, path in parsed_files:
        try:
            pairs = _harvest_adjustments_from_workbook(path)
        except Exception as e:  # noqa: BLE001
            summary.skipped_files.append((path.name, f"failed to read: {type(e).__name__}"))
            continue
        summary.source_deals_scanned.append(deal_name)
        for city, value in pairs:
            # First-write-wins (most-recent-deal-wins, since we sorted desc)
            if city in summary.adjustments:
                continue
            summary.adjustments[city] = AdjustmentRecord(
                city=city,
                value=value,
                source_deal=deal_name,
                date_rated=d,
            )

    summary.audit_log.append(
        f"Inheritance: {len(summary.adjustments)} city adjustments inherited "
        f"from {len(summary.source_deals_scanned)} prior deals "
        f"({len(summary.skipped_files)} files skipped)"
    )
    return summary
