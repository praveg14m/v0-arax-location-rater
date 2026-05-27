# lib/python/parse_rent_roll.py
#
# Rent-roll parser.
#
# Expected behaviour
# ------------------
# Arax rent rolls arrive as .xlsx / .xlsm files with a leading metadata block
# followed by a tabular section listing units. Column names are inconsistent
# across vendors (e.g. "Stadt", "Ort", "City"; "Strasse", "Street",
# "Adresse"). `detect_columns` is responsible for finding the header row and
# returning a mapping {logical_name: actual_column} where logical_name is one
# of: "city", "street", "house_number", "postal_code", "annual_rent",
# "unit_count". Detection should be tolerant of whitespace, casing and German
# umlauts, and should fall back to the rapidfuzz matcher with a min score of
# 80.
#
# `extract_addresses` consumes the detected mapping and yields a list of
# Address objects (street + house_number + postal_code + city + annual_rent).
# Rows that are subtotal/empty/footer rows must be skipped.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    street: str
    house_number: str
    postal_code: str
    city: str
    annual_rent: float


def detect_columns(df) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Detect logical column names in a parsed pandas DataFrame.

    Returns a dict mapping logical names ("city", "street", "house_number",
    "postal_code", "annual_rent", "unit_count") to the actual column label
    found in the DataFrame.
    """
    raise NotImplementedError("TODO: implement against real master workbook")


def extract_addresses(df, column_map: dict[str, str]) -> list[Address]:  # type: ignore[no-untyped-def]
    """Yield Address rows from the rent-roll DataFrame.

    Skips subtotal, header repeat and footer rows. Coerces numeric fields and
    strips whitespace/umlaut variants from string fields.
    """
    raise NotImplementedError("TODO: implement against real master workbook")
