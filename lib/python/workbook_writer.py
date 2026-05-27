# lib/python/workbook_writer.py
#
# Writes the final Ratings workbook by copying the master template, inserting
# a new portfolio block on the Location Ratings tab, and appending per-address
# rows to the Tenancy Schedule tab.
#
# The master is an .xlsm with VBA macros and ~50 named-range / array-formula
# columns per city row. openpyxl MUST be opened with keep_vba=True so the
# macros and formulas survive the round-trip.
#
# Critical discoveries from inspecting the real master workbook:
#
#   Tenancy Schedule tab
#     Headers at row 5: B=Deal, C=Addresses, D=City & Streets, E=City,
#       F=Area, G=Rent, I=Walking Score
#     Existing data rows 6-24 (sample deals)
#     We append from the first empty row after the last existing data row
#
#   Location Ratings tab
#     Row 27 is the "ACTIVE DEAL" placeholder marker (the brief said the new
#     block goes there). The deal block has this structure:
#       - 1 header row:  C=deal_name (matches Tenancy Schedule Deal column),
#                        E="<deal_name>" (this becomes the W. Avg. row label)
#       - N city rows:   F=mapped city name; all other columns are formulas
#                        that we copy from the template row 17 with row
#                        references updated
#       - 1 W. Avg. row: aggregates the city rows above using SUMPRODUCT/SUM
#
#   Critical: the F column drives ~50 dependent formulas across each row.
#   Setting F is sufficient for K, L, O, P, etc to fill themselves when Excel
#   recalculates. The H column (Total Rent) is an array formula that pulls
#   from Tenancy Schedule. So we must write Tenancy Schedule FIRST so the
#   ratings block has data to aggregate.
#
#   The Arax Adjustment lives in column CC. Inherited values are written in
#   blue (font colour RGB 0,0,255). Non-inherited cities leave CC blank for
#   the AM to fill in.

from __future__ import annotations

import io
import re
from copy import copy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

# ---------------------------------------------------------------------------
# Constants - cell anchors discovered from the real master workbook
# ---------------------------------------------------------------------------

LOCATION_RATINGS_SHEET = "Location Ratings"
TENANCY_SCHEDULE_SHEET = "Tenancy Schedule"

# Tenancy Schedule columns (1-indexed)
TS_COL_DEAL = 2  # B
TS_COL_ADDRESSES = 3  # C
TS_COL_CITY_STREET = 4  # D
TS_COL_CITY = 5  # E
TS_COL_AREA = 6  # F
TS_COL_RENT = 7  # G
TS_COL_WALK_SCORE = 9  # I
TS_HEADER_ROW = 5
TS_DATA_START_ROW = 6
TS_DATA_LAST_ROW_BOUND = 8900  # the master's existing formulas reference up to row 8900

# Location Ratings layout
LR_ACTIVE_DEAL_MARKER_ROW = 27  # cell C27 contains "ACTIVE DEAL"
LR_TEMPLATE_CITY_ROW = 17  # row 17 (Hagen in Deal B) is our template city row
LR_TEMPLATE_W_AVG_ROW = 23  # row 23 is the Deal B W. Avg. row template
LR_TEMPLATE_HEADER_ROW = 16  # row 16 is the Deal B header row
LR_CC_COL = 81  # CC = column 81 (Arax Adjustment)
LR_F_COL = 6  # F = city name (drives everything)

# Inherited Arax Adjustment colour (per the brief: RGB 0,0,255)
INHERITED_FONT_COLOR = "FF0000FF"  # ARGB: opaque blue


# ---------------------------------------------------------------------------
# Input data types
# ---------------------------------------------------------------------------


@dataclass
class CityRow:
    """One city to insert into the new deal block."""

    raw_name: str  # original from rent roll (audit only)
    mapped_name: str  # canonical name (goes into F column)
    total_annual_rent: float  # for sort order (descending)


@dataclass
class TenancySchedRow:
    """One address row to append to Tenancy Schedule."""

    deal: str
    addresses: str  # column C - typically "Street Number, Postcode City"
    city_and_street: str  # column D - typically "City, Street"
    city: str  # canonical city (column E) - must match Location Ratings F values
    area: float  # column F (sqm)
    rent: float  # column G (annual euros)
    walk_score: Optional[int]  # column I (0-100, or None for skipped)


@dataclass
class InheritedAdjustment:
    """A prior Arax Adjustment to render in blue."""

    city: str  # canonical city name
    value: float  # 0-10
    source_deal: str  # for audit
    date_rated: str  # ISO date string for audit


# ---------------------------------------------------------------------------
# Helpers - formula reference rewriting
# ---------------------------------------------------------------------------


def _rewrite_formula_row_refs(formula: str, old_row: int, new_row: int) -> str:
    """Replace row references in a formula string.

    Examples:
        '=IF(CT17=0,F17,F17&" ("&CT17&")")' with old=17 new=28
          -> '=IF(CT28=0,F28,F28&" ("&CT28&")")'

    Critically, this is row-only: ABSOLUTE column references like $K$10 (which
    point to weights at row 10) must NOT change. We only swap unanchored row
    references that match exactly old_row.

    Strategy: regex match patterns like ColLetter+digits, where digits == old_row
    AND the row is not absolute-anchored (no '$' before the digit). Replace with
    same column + new_row.
    """
    # Match: ([A-Z]+) (digits)  where digits == old_row, NOT preceded by $.
    # Use lookbehind to ensure the row isn't $-anchored.
    pattern = re.compile(rf"(?<![\$\d]){old_row}(?![\d])")
    # We need to be more precise: only match digits that follow a column letter
    # (i.e., they're a row reference, not a numeric literal).
    pattern = re.compile(
        rf"(?<![A-Z\$])(\$?[A-Z]{{1,3}})(\$?){old_row}(?!\d)",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        col_part = m.group(1)
        anchor = m.group(2)
        # If the row was $-anchored ($17), leave it alone
        if anchor == "$":
            return m.group(0)
        return f"{col_part}{anchor}{new_row}"

    return pattern.sub(_replace, formula)


def _rewrite_array_formula(af: ArrayFormula, old_row: int, new_row: int) -> ArrayFormula:
    """Rewrite an ArrayFormula's text and ref to use new_row."""
    new_text = _rewrite_formula_row_refs(af.text, old_row, new_row)
    # ref may be a single cell ref like "H17" or a range like "CT17:CW17"
    parts = af.ref.split(":")
    new_parts = [_rewrite_formula_row_refs(p, old_row, new_row) for p in parts]
    new_ref = ":".join(new_parts)
    return ArrayFormula(ref=new_ref, text=new_text)


def _rewrite_sumproduct_range(formula: str, old_start: int, old_end: int, new_start: int, new_end: int) -> str:
    """Special rewrite for the W. Avg. row formulas.

    The template W. Avg. row (e.g. row 23 for Deal B) contains formulas like:
        =SUMPRODUCT(K17:K22,$H17:$H22)/$H23
        =SUM(H17:H22)

    When we insert a new block with M cities spanning row N to N+M-1 and a
    W. Avg. row at N+M, we need to rewrite:
      - The W. Avg. row itself's own-row references (23 -> N+M)
      - The range references (17:22 -> N:N+M-1)
    """
    # First rewrite the W. Avg. row's own references (old W. Avg. row -> new)
    new_wavg = new_end + 1
    old_wavg = old_end + 1
    out = _rewrite_formula_row_refs(formula, old_wavg, new_wavg)
    # Now rewrite the range references. We use a pattern that matches
    # any reference at row old_start or old_end.
    out = _rewrite_formula_row_refs(out, old_start, new_start)
    out = _rewrite_formula_row_refs(out, old_end, new_end)
    return out


# ---------------------------------------------------------------------------
# Master loader
# ---------------------------------------------------------------------------


def _shift_row_refs_in_formula(formula: str, shift_threshold: int, shift_amount: int) -> str:
    """Shift every row reference >= shift_threshold by shift_amount.

    Used after openpyxl insert_rows to fix the row references in displaced
    cells. Only unanchored row references are shifted (absolute $row stays).
    """
    pattern = re.compile(r"(\$?[A-Z]{1,3})(\$?)(\d+)", re.IGNORECASE)

    def _replace(m: re.Match) -> str:
        col_part = m.group(1)
        anchor = m.group(2)
        row_num = int(m.group(3))
        if anchor == "$":
            return m.group(0)  # absolute row, don't shift
        if row_num >= shift_threshold:
            return f"{col_part}{anchor}{row_num + shift_amount}"
        return m.group(0)

    return pattern.sub(_replace, formula)


def _update_displaced_formulas(ws, shift_threshold: int, shift_amount: int) -> None:  # type: ignore[no-untyped-def]
    """Walk the whole sheet and rewrite formulas in cells that were displaced
    by an insert_rows operation.

    Iterates over every cell. For cells at row > shift_threshold (i.e. cells
    that were shifted down), rewrites any unanchored row reference >= shift_threshold
    to add shift_amount.
    """
    # We need to scan ALL cells, not just the displaced ones, because formulas
    # ABOVE the insert point might also reference rows BELOW it. (Unlikely in
    # the Arax workbook but defensively correct.)
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if isinstance(v, str) and v.startswith("="):
                cell.value = _shift_row_refs_in_formula(v, shift_threshold, shift_amount)
            elif isinstance(v, ArrayFormula):
                new_text = _shift_row_refs_in_formula(v.text, shift_threshold, shift_amount)
                ref_parts = v.ref.split(":")
                new_ref_parts = [
                    _shift_row_refs_in_formula(p, shift_threshold, shift_amount)
                    for p in ref_parts
                ]
                cell.value = ArrayFormula(ref=":".join(new_ref_parts), text=new_text)


def load_master(master_xlsm_bytes: bytes) -> openpyxl.Workbook:
    """Load the master workbook with VBA preserved."""
    return openpyxl.load_workbook(
        io.BytesIO(master_xlsm_bytes),
        keep_vba=True,
        data_only=False,
    )


# ---------------------------------------------------------------------------
# Tenancy Schedule append
# ---------------------------------------------------------------------------


def _find_next_tenancy_row(ws) -> int:  # type: ignore[no-untyped-def]
    """Find the first empty row in Tenancy Schedule AFTER all existing data.

    The master uses blank rows as separators between deal blocks (e.g. row 9
    is blank between Deal A and Deal B), so we can't take the first empty
    row. Instead, scan from the end of the populated range backwards to find
    the last non-empty Deal cell, and return last_filled + 2 (leaving a one-row
    gap to match the existing separator convention).
    """
    # Find the last row with a non-empty Deal cell (column B)
    last_filled = TS_DATA_START_ROW - 1
    for row in range(TS_DATA_START_ROW, TS_DATA_LAST_ROW_BOUND + 1):
        if ws.cell(row=row, column=TS_COL_DEAL).value is not None:
            last_filled = row
    # Leave one blank separator row between the previous deal and ours
    return last_filled + 2


def append_tenancy_rows(
    wb: openpyxl.Workbook,
    rows: list[TenancySchedRow],
) -> tuple[int, int]:
    """Append rows to the Tenancy Schedule tab.

    Returns (first_row, last_row) inclusive 1-indexed row numbers of the
    appended block, for audit.
    """
    ws = wb[TENANCY_SCHEDULE_SHEET]
    start = _find_next_tenancy_row(ws)

    for i, row in enumerate(rows):
        r = start + i
        ws.cell(row=r, column=TS_COL_DEAL, value=row.deal)
        ws.cell(row=r, column=TS_COL_ADDRESSES, value=row.addresses)
        ws.cell(row=r, column=TS_COL_CITY_STREET, value=row.city_and_street)
        ws.cell(row=r, column=TS_COL_CITY, value=row.city)
        ws.cell(row=r, column=TS_COL_AREA, value=row.area)
        ws.cell(row=r, column=TS_COL_RENT, value=row.rent)
        if row.walk_score is not None:
            ws.cell(row=r, column=TS_COL_WALK_SCORE, value=row.walk_score)

    return start, start + len(rows) - 1


# ---------------------------------------------------------------------------
# Location Ratings block insertion
# ---------------------------------------------------------------------------


def _copy_cell_full(src_cell, dst_cell, old_row: int, new_row: int) -> None:  # type: ignore[no-untyped-def]
    """Copy a cell's value AND style, rewriting formula row refs as we go."""
    src_value = src_cell.value
    if isinstance(src_value, ArrayFormula):
        dst_cell.value = _rewrite_array_formula(src_value, old_row, new_row)
    elif isinstance(src_value, str) and src_value.startswith("="):
        dst_cell.value = _rewrite_formula_row_refs(src_value, old_row, new_row)
    else:
        dst_cell.value = src_value

    # Copy style
    if src_cell.has_style:
        dst_cell.font = copy(src_cell.font)
        dst_cell.fill = copy(src_cell.fill)
        dst_cell.border = copy(src_cell.border)
        dst_cell.alignment = copy(src_cell.alignment)
        dst_cell.number_format = src_cell.number_format
        dst_cell.protection = copy(src_cell.protection)


def _copy_template_row(
    ws,  # type: ignore[no-untyped-def]
    template_row: int,
    target_row: int,
    max_col: int = 110,
) -> None:
    """Copy an entire row from template_row to target_row, rewriting formula refs."""
    for col in range(1, max_col + 1):
        src = ws.cell(row=template_row, column=col)
        dst = ws.cell(row=target_row, column=col)
        _copy_cell_full(src, dst, template_row, target_row)


def insert_deal_block(
    wb: openpyxl.Workbook,
    deal_name: str,
    cities: list[CityRow],
    inherited: dict[str, InheritedAdjustment],
    insert_at_row: int = LR_ACTIVE_DEAL_MARKER_ROW,
) -> tuple[int, int]:
    """Insert a new deal block on the Location Ratings tab.

    Layout produced (1-indexed rows):
        insert_at_row     : header (C=deal_name, E=deal_name)
        insert_at_row + 1 : first city row
        ...
        insert_at_row + N : last city row
        insert_at_row+N+1 : W. Avg. row

    Cities are inserted sorted by total_annual_rent descending (per the brief).
    Inherited Arax Adjustments are written to column CC in blue.

    Returns (first_inserted_row, last_inserted_row) for audit.
    """
    ws = wb[LOCATION_RATINGS_SHEET]

    # Sort cities by descending annual rent
    sorted_cities = sorted(cities, key=lambda c: -c.total_annual_rent)
    n_cities = len(sorted_cities)
    if n_cities == 0:
        raise ValueError("Cannot insert a deal block with no cities")

    # Layout: header at insert_at_row, cities from insert_at_row+1 to insert_at_row+n
    # W. Avg. at insert_at_row + n + 1
    header_row = insert_at_row
    first_city_row = insert_at_row + 1
    last_city_row = insert_at_row + n_cities
    wavg_row = insert_at_row + n_cities + 1

    # We need to make space. Use ws.insert_rows() so existing data shifts down.
    # The ACTIVE DEAL marker currently sits at row 27 alone. We:
    #   1. Clear the marker at insert_at_row (so we can reuse it as header)
    #   2. Insert (n_cities + 1) blank rows AFTER insert_at_row so we have room
    #      for n_cities city rows + 1 W. Avg. row.
    # Note: insert_rows inserts BEFORE the given row, shifting that row down.
    rows_needed = n_cities + 1  # cities + W. Avg.
    ws.insert_rows(idx=insert_at_row + 1, amount=rows_needed)

    # CRITICAL: openpyxl's insert_rows shifts data but does NOT update formula
    # references in displaced cells. Any formula referring to row N (where
    # N > insert_at_row) is now wrong because that cell moved to row N + rows_needed.
    # We must walk the displaced rows and rewrite their formula references.
    _update_displaced_formulas(ws, shift_threshold=insert_at_row, shift_amount=rows_needed)

    # 1. Write the header row at insert_at_row
    # Pattern matches existing deal headers (row 12, 16, 29):
    #   C = deal_name  (used by Tenancy Schedule SUMPRODUCT)
    #   E = deal_name  (display label)
    # Clear the "ACTIVE DEAL" placeholder text and overwrite
    ws.cell(row=header_row, column=3, value=deal_name)  # C
    ws.cell(row=header_row, column=5, value=deal_name)  # E
    # Optional: bold styling matches existing headers
    header_font = ws.cell(row=LR_TEMPLATE_HEADER_ROW, column=5).font
    ws.cell(row=header_row, column=3).font = copy(header_font)
    ws.cell(row=header_row, column=5).font = copy(header_font)

    # 2. Write the city rows by copying the template (row 17) and rewriting refs
    for i, city in enumerate(sorted_cities):
        target_row = first_city_row + i
        _copy_template_row(ws, LR_TEMPLATE_CITY_ROW, target_row)

        # Override F with our city name
        ws.cell(row=target_row, column=LR_F_COL, value=city.mapped_name)

        # Override C with formula =E<header_row> (so each city row links back to the header)
        # In the template, C17 = =E16 (linking to Deal B header at row 16)
        ws.cell(row=target_row, column=3, value=f"=E{header_row}")

        # If this is an inherited city, write Arax Adjustment in blue
        if city.mapped_name in inherited:
            adj = inherited[city.mapped_name]
            cc_cell = ws.cell(row=target_row, column=LR_CC_COL)
            cc_cell.value = adj.value
            blue_font = Font(
                name=cc_cell.font.name,
                size=cc_cell.font.size,
                bold=cc_cell.font.bold,
                italic=cc_cell.font.italic,
                color=INHERITED_FONT_COLOR,
            )
            cc_cell.font = blue_font
        # Otherwise CC is copied from the template (the template city happens
        # to have a value like 8.25). Clear it so the AM fills it in manually.
        # NB: ws.cell(row, col, value=None) does NOT clear in openpyxl;
        # we must assign to .value directly.
        else:
            ws.cell(row=target_row, column=LR_CC_COL).value = None

        # Each city row's I column references the W. Avg. row's H value
        # (% of portfolio rent). Template has =H17/$H$23 referencing Deal B's
        # W. Avg. at row 23. Rewrite to point to our W. Avg. row.
        i_formula = f"=H{target_row}/$H${wavg_row}"
        ws.cell(row=target_row, column=9).value = i_formula

    # 3. Write the W. Avg. row at wavg_row by copying template row 23
    _copy_template_row(ws, LR_TEMPLATE_W_AVG_ROW, wavg_row)
    # The template W. Avg. row references rows 17:22 (the city range for Deal B).
    # Our city range is first_city_row : last_city_row. Rewrite ranges.
    # Also: template references $H$23 (absolute - the W. Avg. row itself).
    # That absolute reference must now point to OUR W. Avg. row.
    for col in range(1, 110):
        cell = ws.cell(row=wavg_row, column=col)
        v = cell.value
        if isinstance(v, str) and v.startswith("="):
            new_formula = _rewrite_sumproduct_range(
                v, LR_TEMPLATE_CITY_ROW, LR_TEMPLATE_W_AVG_ROW - 1,
                first_city_row, last_city_row,
            )
            # Also rewrite absolute references to the template W. Avg. row.
            # $H$23 -> $H$<wavg_row>; $K$23 -> $K$<wavg_row>; etc.
            new_formula = re.sub(
                rf"\$([A-Z]{{1,3}})\${LR_TEMPLATE_W_AVG_ROW}\b",
                rf"$\1${wavg_row}",
                new_formula,
            )
            cell.value = new_formula
        elif isinstance(v, ArrayFormula):
            new_text = _rewrite_sumproduct_range(
                v.text, LR_TEMPLATE_CITY_ROW, LR_TEMPLATE_W_AVG_ROW - 1,
                first_city_row, last_city_row,
            )
            new_text = re.sub(
                rf"\$([A-Z]{{1,3}})\${LR_TEMPLATE_W_AVG_ROW}\b",
                rf"$\1${wavg_row}",
                new_text,
            )
            # Rewrite ref too
            ref_parts = v.ref.split(":")
            new_ref_parts = [
                _rewrite_formula_row_refs(p, LR_TEMPLATE_W_AVG_ROW, wavg_row)
                for p in ref_parts
            ]
            cell.value = ArrayFormula(ref=":".join(new_ref_parts), text=new_text)

    # E column on W. Avg. row: pattern in template is =E16&" - "&"W. Avg."
    # We want =E<header_row>&" - "&"W. Avg."
    ws.cell(row=wavg_row, column=5, value=f'=E{header_row}&" - "&"W. Avg."')

    return header_row, wavg_row


# ---------------------------------------------------------------------------
# Top-level: full workbook write
# ---------------------------------------------------------------------------


@dataclass
class WriteResult:
    workbook_bytes: bytes
    filename: str
    tenancy_first_row: int
    tenancy_last_row: int
    ratings_first_row: int
    ratings_last_row: int
    audit_log: list[str]


def write_ratings_workbook(
    master_xlsm_bytes: bytes,
    deal_name: str,
    cities: list[CityRow],
    tenancy_rows: list[TenancySchedRow],
    inherited: dict[str, InheritedAdjustment],
    run_date: Optional[date] = None,
) -> WriteResult:
    """Produce a fully-wired Ratings working copy of the master workbook.

    Steps:
      1. Load master with keep_vba=True
      2. Append per-address rows to Tenancy Schedule
      3. Insert deal block on Location Ratings (one row per city + W. Avg.)
      4. Save to bytes and return with a date-stamped filename
    """
    if run_date is None:
        run_date = date.today()

    audit: list[str] = []
    audit.append(f"Loading master workbook ({len(master_xlsm_bytes)} bytes)")
    wb = load_master(master_xlsm_bytes)

    # Step 1: Tenancy Schedule (write first so SUMPRODUCT formulas have data)
    ts_first, ts_last = append_tenancy_rows(wb, tenancy_rows)
    audit.append(
        f"Tenancy Schedule: appended rows {ts_first} - {ts_last} "
        f"({len(tenancy_rows)} addresses)"
    )

    # Step 2: Location Ratings block
    lr_first, lr_last = insert_deal_block(wb, deal_name, cities, inherited)
    audit.append(
        f"Location Ratings: inserted deal block at rows {lr_first} - {lr_last} "
        f"({len(cities)} cities + W. Avg.)"
    )

    # Step 3: Save to bytes
    safe_deal = re.sub(r"[^A-Za-z0-9_-]", "", deal_name)
    filename = f"{run_date.strftime('%y%m%d')}_Ratings_{safe_deal}.xlsm"
    buffer = io.BytesIO()
    wb.save(buffer)
    workbook_bytes = buffer.getvalue()
    audit.append(f"Saved working copy: {filename} ({len(workbook_bytes)} bytes)")

    return WriteResult(
        workbook_bytes=workbook_bytes,
        filename=filename,
        tenancy_first_row=ts_first,
        tenancy_last_row=ts_last,
        ratings_first_row=lr_first,
        ratings_last_row=lr_last,
        audit_log=audit,
    )
