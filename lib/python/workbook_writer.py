# lib/python/workbook_writer.py
#
# Writes the final Ratings workbook by copying the Arax master template and
# filling the Ratings block with city-level adjustments, Walk Score data and
# inherited values.
#
# Critical: the master is an .xlsm file with VBA macros and named ranges that
# downstream Arax workflows depend on. openpyxl MUST be opened with
# keep_vba=True so the macros and formulas survive the round-trip.
#
# The Ratings block layout, named ranges and conditional-formatting rules are
# defined in the master template and must NOT be re-created in code — only
# the data cells are written.
#
# Inherited values (from prior deals) are written with the explicit font
# colour #0066CC so reviewers can spot them in the workbook. Newly-rated
# values use the default font colour from the master template.

from __future__ import annotations

from pathlib import Path


def write_ratings_block(
    master_path: Path,
    output_path: Path,
    deal_name: str,
    cities: list,  # type: ignore[type-arg]
    walk_scores: list,  # type: ignore[type-arg]
    inherited: dict,  # type: ignore[type-arg]
) -> None:
    """Open the master .xlsm, populate the Ratings block, and save to output_path.

    - master_path: path to the Arax master .xlsm template (must remain unmodified).
    - output_path: where to write the populated workbook.
    - deal_name: written into the Ratings block header.
    - cities: list of resolved city records with adjustments.
    - walk_scores: list of Score records (see walk_score.py).
    - inherited: dict mapping city -> AdjustmentRecord to render in #0066CC.
    """
    raise NotImplementedError("TODO: implement against real master workbook")
