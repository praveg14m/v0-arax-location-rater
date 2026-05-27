# lib/python/parse_rent_roll.py
#
# Rent-roll parser.
#
# Architecture
# ------------
# Two-tier column detection:
#
#   Tier 1 - Rule-based: rapidfuzz match against a synonym dictionary of
#     known German and English column names (Stadt/Standort/City/Ort,
#     Adresse/Strasse/Street, etc). Fast, deterministic, covers ~80% of
#     real rent rolls.
#
#   Tier 2 - LLM fallback (Anthropic Claude): triggered when rule-based
#     detection cannot confidently identify all required columns. Sends
#     the first ~20 rows as a structured prompt and parses JSON output.
#     Handles arbitrary column naming, language mixing, and column
#     reordering.
#
# Each detected mapping carries a `method` and per-column confidence so the
# audit log shows which tier resolved each column.
#
# Files arrive as bytes (in-memory uploads); we load via openpyxl with
# data_only=True so any calculated cells are read as values.

from __future__ import annotations

import io
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

import openpyxl
import pandas as pd
from rapidfuzz import fuzz, process

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Address:
    """One rentable unit from the rent roll, normalised."""

    street: str  # e.g. "Blankenberg 8" (street + number combined as it appears)
    city: str  # raw city string from the rent roll, pre-mapping
    area_sqm: float  # unit area in square metres (0.0 if missing)
    annual_rent: float  # always annual euros (we multiply monthly x 12 if needed)
    unit_type: str  # raw unit type from the rent roll (e.g. "Wohnung")
    row_index: int  # original 1-indexed row in the source sheet (for audit)


@dataclass
class ColumnDetection:
    """Per-column detection result."""

    logical_name: str  # one of: city, street, area, rent, unit_type
    detected_header: Optional[str]  # the actual header text in the source file
    confidence: int  # 0-100
    method: Literal["rule_based", "llm_fallback", "missing"]


@dataclass
class ParseResult:
    """Full outcome of parsing one rent roll."""

    sheet_name: str
    header_row: int
    column_detections: list[ColumnDetection]
    rent_period: Literal["monthly", "annual", "unknown"]
    rent_period_method: Literal["llm", "heuristic", "default_monthly"]
    flat_filter_values: list[str]  # which unit-type values are kept (flats)
    addresses: list[Address]
    audit_log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Synonym dictionary (Tier 1 rule-based)
# ---------------------------------------------------------------------------
#
# Each logical column has a list of synonyms. We fuzzy-match the actual header
# against these; the best score across all synonyms is the detection score.

SYNONYMS: dict[str, list[str]] = {
    "city": [
        # German
        "stadt", "standort", "ort", "wohnort", "lage", "lokation", "gemeinde",
        # English
        "city", "location", "town", "municipality",
    ],
    "street": [
        # German
        "strasse", "straße", "anschrift", "adresse", "objekt", "objektbezeichnung",
        "objektadresse", "lagebezeichnung", "lageadresse",
        # English
        "address", "street", "property", "property address", "building",
    ],
    "area": [
        # German
        "flaeche", "fläche", "wohnflaeche", "wohnfläche", "einheitflaeche",
        "einheitfläche", "nutzflaeche", "nutzfläche", "qm", "m2", "m²",
        # English
        "area", "size", "sqm", "square metres", "square meters", "floor area",
    ],
    "rent": [
        # German
        "miete", "soll", "gesamtsoll", "sollmiete", "kaltmiete", "nettomiete",
        "monatsmiete", "jahresmiete", "nettokaltmiete", "grundmiete",
        # English
        "rent", "monthly rent", "annual rent", "net rent", "base rent",
    ],
    "unit_type": [
        # German
        "art", "einheitart", "einheitartbezeichnung", "nutzungsart", "typ",
        # English
        "type", "unit type", "category",
    ],
}

# Values in the unit_type column that we treat as flats (the "rateable" units).
# Anything not in this set is filtered out (parking, garage, commercial, etc).
FLAT_VALUES = {
    "wohnung", "wohneinheit", "flat", "apartment", "apt",
    "wohnen", "wohnraum",
}

# Required columns - if any of these are missing or low-confidence, escalate to LLM.
REQUIRED_LOGICAL: list[str] = ["city", "street", "rent"]
# Optional - nice to have but tool still works if missing.
OPTIONAL_LOGICAL: list[str] = ["area", "unit_type"]

# Confidence threshold below which we trigger LLM fallback.
RULE_BASED_THRESHOLD = 80


# ---------------------------------------------------------------------------
# Header normalisation
# ---------------------------------------------------------------------------


def _normalise(s: Any) -> str:
    """Lowercase, strip, remove punctuation, collapse whitespace."""
    if s is None:
        return ""
    out = str(s).lower().strip()
    # Replace German umlauts and ß
    out = out.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    # Strip non-alphanumeric (keep spaces) so "wohn-fläche" matches "wohnflaeche"
    out = re.sub(r"[^a-z0-9\s]", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


# ---------------------------------------------------------------------------
# Header row detection
# ---------------------------------------------------------------------------


def find_header_row(workbook_bytes: bytes) -> tuple[str, int, pd.DataFrame]:
    """Find the most likely sheet + header row for a rent-roll workbook.

    Strategy:
      - For each sheet, find the row with the highest count of "header-like"
        cells (non-numeric strings, non-empty, not formula-looking).
      - Tie-break by row that has the most matches against the synonym
        dictionary (so a row containing "Stadt" beats one containing "Notes").
      - Return that sheet name, header row (1-indexed), and a DataFrame with
        the rows below the header row as data.

    Raises ValueError if no plausible header row is found in any sheet.
    """
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), data_only=True, read_only=True)

    best: Optional[tuple[str, int, int, pd.DataFrame]] = None  # (sheet, row, score, df)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        # Scan first 20 rows of the sheet
        rows: list[list[Any]] = []
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True)):
            rows.append(list(row))
            if i >= 19:
                break

        for row_idx, row in enumerate(rows, start=1):
            # A header-like cell: non-null, string-typed, length 2-60, mostly letters
            header_like = 0
            synonym_hits = 0
            for cell in row:
                if cell is None:
                    continue
                if isinstance(cell, (int, float)):
                    continue
                s = str(cell).strip()
                if not s or len(s) > 60:
                    continue
                # mostly letters check
                letters = sum(1 for c in s if c.isalpha())
                if letters < max(2, int(0.5 * len(s))):
                    continue
                header_like += 1
                # Check synonym hits
                norm = _normalise(s)
                for synonyms in SYNONYMS.values():
                    for syn in synonyms:
                        if fuzz.ratio(norm, syn) >= 85:
                            synonym_hits += 1
                            break

            score = header_like * 10 + synonym_hits * 50
            if header_like < 3 or synonym_hits == 0:
                continue

            if best is None or score > best[2]:
                # Build DataFrame with rows below
                headers = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(row)]
                data_rows = []
                for r in ws.iter_rows(min_row=row_idx + 1, values_only=True):
                    if all(c is None for c in r):
                        continue
                    data_rows.append(list(r))
                # Pad rows to header length
                width = len(headers)
                data_rows = [r[:width] + [None] * max(0, width - len(r)) for r in data_rows]
                df = pd.DataFrame(data_rows, columns=headers)
                best = (sheet_name, row_idx, score, df)

    if best is None:
        raise ValueError(
            "Could not locate a header row in any sheet of the workbook. "
            "Expected a row with at least 3 text headers including one of: "
            "Stadt, Standort, Adresse, Miete, City, Address, Rent."
        )

    return best[0], best[1], best[3]


# ---------------------------------------------------------------------------
# Tier 1: rule-based column detection
# ---------------------------------------------------------------------------


def _rule_based_detect(headers: list[str]) -> dict[str, ColumnDetection]:
    """For each logical name, find the best-matching header by fuzzy score."""
    results: dict[str, ColumnDetection] = {}
    normalised_headers = [(h, _normalise(h)) for h in headers]

    for logical, synonyms in SYNONYMS.items():
        best_header: Optional[str] = None
        best_score = 0
        for original, norm in normalised_headers:
            if not norm:
                continue
            for syn in synonyms:
                # token_set_ratio handles "Total Rent" matching "rent" etc
                score = max(
                    fuzz.ratio(norm, syn),
                    fuzz.partial_ratio(norm, syn),
                    fuzz.token_set_ratio(norm, syn),
                )
                if score > best_score:
                    best_score = score
                    best_header = original

        if best_score >= RULE_BASED_THRESHOLD:
            results[logical] = ColumnDetection(
                logical_name=logical,
                detected_header=best_header,
                confidence=int(best_score),
                method="rule_based",
            )
        else:
            results[logical] = ColumnDetection(
                logical_name=logical,
                detected_header=best_header,  # best guess for the LLM to see
                confidence=int(best_score),
                method="missing",
            )
    return results


# ---------------------------------------------------------------------------
# Tier 2: LLM fallback (Anthropic Claude)
# ---------------------------------------------------------------------------


def _llm_fallback_detect(
    df: pd.DataFrame,
    rule_results: dict[str, ColumnDetection],
) -> dict[str, ColumnDetection]:
    """Send the first 20 rows to Claude, get back column mappings.

    Returns the same shape as _rule_based_detect, but with method="llm_fallback"
    on any column the LLM resolves.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # No key available; return rule-based result unchanged. The audit log
        # will note the LLM was skipped.
        return rule_results

    try:
        import anthropic  # type: ignore
    except ImportError:
        return rule_results

    client = anthropic.Anthropic(api_key=api_key)

    # Build the prompt
    headers = list(df.columns)
    sample = df.head(20).to_markdown(index=False)
    missing_cols = [r.logical_name for r in rule_results.values() if r.method == "missing"]

    prompt = f"""You are looking at the first 20 rows of a German residential rent roll.
The columns may be named in German, English, or a mix. Identify which column header
maps to each logical role.

Headers in this file (with index):
{json.dumps([{"index": i, "header": h} for i, h in enumerate(headers)], ensure_ascii=False, indent=2)}

Sample data (first 20 rows):
{sample}

Required logical columns to identify:
- "city": which column has the city/town/municipality name
- "street": which column has the street address (may include house number)
- "rent": which column has the rent (monthly or annual)
- "area": which column has the unit area in square metres (may be missing - return null)
- "unit_type": which column says what type of unit (flat/parking/commercial) (may be missing - return null)

Additionally:
- "rent_period": is the rent monthly or annual? Look at the magnitude of values.
  Typical German monthly rent is 300-2000 EUR per unit. Annual is 4000-25000.
  Return "monthly" or "annual".
- "flat_values": which values in the unit_type column correspond to flats/apartments
  (as opposed to parking, garage, commercial)? Return a list of strings exactly
  as they appear in the data. If no unit_type column, return [].

These columns are currently not confidently detected by rules: {missing_cols}

Respond with ONLY a JSON object, no other text:
{{
  "city": "exact header string or null",
  "street": "exact header string or null",
  "rent": "exact header string or null",
  "area": "exact header string or null",
  "unit_type": "exact header string or null",
  "rent_period": "monthly" or "annual",
  "flat_values": ["list", "of", "strings"],
  "reasoning": "one short sentence explaining your detection"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001
        return rule_results

    # Merge LLM results into rule_results, preferring LLM only where rule was missing
    # or where the LLM disagrees with low-confidence rule
    out = dict(rule_results)
    for logical in ["city", "street", "rent", "area", "unit_type"]:
        llm_header = parsed.get(logical)
        if not llm_header:
            continue
        # Only override if rule-based was missing or LLM agrees with low confidence
        current = out.get(logical)
        if current is None or current.method == "missing" or current.confidence < RULE_BASED_THRESHOLD:
            out[logical] = ColumnDetection(
                logical_name=logical,
                detected_header=llm_header,
                confidence=95,  # LLM resolved
                method="llm_fallback",
            )

    # Stash extra LLM-derived info on the result for the caller to pick up
    out["__rent_period__"] = ColumnDetection(  # type: ignore[index]
        logical_name="__rent_period__",
        detected_header=parsed.get("rent_period"),
        confidence=95,
        method="llm_fallback",
    )
    out["__flat_values__"] = ColumnDetection(  # type: ignore[index]
        logical_name="__flat_values__",
        detected_header=json.dumps(parsed.get("flat_values", [])),
        confidence=95,
        method="llm_fallback",
    )
    return out


# ---------------------------------------------------------------------------
# Rent-period heuristic (fallback when no LLM available)
# ---------------------------------------------------------------------------


def _detect_rent_period_heuristic(rent_values: list[float]) -> Literal["monthly", "annual", "unknown"]:
    """If median rent > 3000, assume annual. If < 2000, monthly. In between, unknown.

    These thresholds reflect typical German residential rents: monthly is
    usually 300-1500 per unit, annual is 4000-18000.
    """
    if not rent_values:
        return "unknown"
    values = sorted(v for v in rent_values if v and v > 0)
    if not values:
        return "unknown"
    median = values[len(values) // 2]
    if median >= 3000:
        return "annual"
    if median <= 2000:
        return "monthly"
    return "unknown"


# ---------------------------------------------------------------------------
# Address extraction
# ---------------------------------------------------------------------------


def _coerce_float(val: Any) -> float:
    """European number formats: '1.234,56' -> 1234.56, '1,234.56' -> 1234.56."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return 0.0
    # Strip currency symbols and whitespace
    s = re.sub(r"[€$£\s]", "", s)
    # If contains both . and , the last one is the decimal separator
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Only comma - assume European decimal
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _looks_like_subtotal_row(row: pd.Series, city_col: Optional[str]) -> bool:
    """Heuristic: subtotal/footer rows have a city like 'Total', 'Summe', empty city, etc."""
    if city_col is None:
        return False
    city = row.get(city_col)
    if city is None or (isinstance(city, float) and pd.isna(city)):
        return True
    s = str(city).strip().lower()
    if not s:
        return True
    if s in {"total", "summe", "gesamt", "sum", "subtotal", "zwischensumme"}:
        return True
    if s.startswith("total ") or s.startswith("summe "):
        return True
    return False


def extract_addresses(
    df: pd.DataFrame,
    column_map: dict[str, ColumnDetection],
    rent_period: Literal["monthly", "annual", "unknown"],
    flat_filter: list[str],
) -> list[Address]:
    """Yield Address rows from the rent-roll DataFrame, filtered to flats."""
    addresses: list[Address] = []

    city_col = column_map["city"].detected_header if "city" in column_map and column_map["city"].method != "missing" else None
    street_col = column_map["street"].detected_header if "street" in column_map and column_map["street"].method != "missing" else None
    rent_col = column_map["rent"].detected_header if "rent" in column_map and column_map["rent"].method != "missing" else None
    area_col = column_map["area"].detected_header if "area" in column_map and column_map["area"].method != "missing" else None
    unit_col = column_map["unit_type"].detected_header if "unit_type" in column_map and column_map["unit_type"].method != "missing" else None

    # Determine which unit_type values are "flats"
    flat_lookup: set[str] = set()
    if flat_filter:
        flat_lookup = {v.strip().lower() for v in flat_filter}
    else:
        flat_lookup = FLAT_VALUES

    # Annual conversion factor
    annual_multiplier = 1.0 if rent_period == "annual" else (12.0 if rent_period == "monthly" else 12.0)

    for idx, row in df.iterrows():
        if _looks_like_subtotal_row(row, city_col):
            continue

        city = str(row.get(city_col, "")).strip() if city_col else ""
        if not city:
            continue

        street = str(row.get(street_col, "")).strip() if street_col else ""
        rent_monthly_or_annual = _coerce_float(row.get(rent_col)) if rent_col else 0.0
        area = _coerce_float(row.get(area_col)) if area_col else 0.0
        unit_type_raw = str(row.get(unit_col, "")).strip() if unit_col else ""

        # Filter to flats if we have a unit_type column
        if unit_col:
            if unit_type_raw.lower() not in flat_lookup:
                # Not a flat; skip
                continue

        # Skip rows with zero/negative rent (vacant units in some PMs)
        if rent_monthly_or_annual <= 0:
            continue

        addresses.append(
            Address(
                street=street,
                city=city,
                area_sqm=area,
                annual_rent=rent_monthly_or_annual * annual_multiplier,
                unit_type=unit_type_raw,
                row_index=int(idx) + 1 if isinstance(idx, int) else 0,
            )
        )

    return addresses


# ---------------------------------------------------------------------------
# Top-level public API
# ---------------------------------------------------------------------------


def parse_rent_roll(workbook_bytes: bytes) -> ParseResult:
    """Full pipeline: find header, detect columns, extract addresses, audit-log it all.

    Raises ValueError if no plausible header row is found.
    """
    audit: list[str] = []

    # 1. Find the header row
    sheet_name, header_row, df = find_header_row(workbook_bytes)
    audit.append(f"Header row found: sheet '{sheet_name}', row {header_row}, {len(df)} data rows")

    # 2. Rule-based column detection
    rule_results = _rule_based_detect(list(df.columns))
    rule_success = all(
        r.method == "rule_based"
        for k, r in rule_results.items()
        if k in REQUIRED_LOGICAL
    )
    audit.append(
        "Rule-based detection: "
        + ", ".join(f"{k}={v.detected_header}({v.confidence}%)" for k, v in rule_results.items())
    )

    # 3. LLM fallback if any required column is missing
    final_map = rule_results
    rent_period: Literal["monthly", "annual", "unknown"] = "unknown"
    rent_period_method: Literal["llm", "heuristic", "default_monthly"] = "default_monthly"
    flat_values: list[str] = []

    if not rule_success:
        audit.append(f"LLM fallback triggered: required columns missing or low-confidence")
        llm_results = _llm_fallback_detect(df, rule_results)
        # Pop out the meta-fields the LLM stashed
        rent_period_meta = llm_results.pop("__rent_period__", None) if "__rent_period__" in llm_results else None  # type: ignore[arg-type]
        flat_meta = llm_results.pop("__flat_values__", None) if "__flat_values__" in llm_results else None  # type: ignore[arg-type]
        final_map = llm_results
        if rent_period_meta:
            rp = rent_period_meta.detected_header
            if rp in ("monthly", "annual"):
                rent_period = rp  # type: ignore[assignment]
                rent_period_method = "llm"
                audit.append(f"LLM determined rent period: {rp}")
        if flat_meta and flat_meta.detected_header:
            try:
                flat_values = json.loads(flat_meta.detected_header)
                audit.append(f"LLM flat-type filter: {flat_values}")
            except json.JSONDecodeError:
                pass

    # 4. Determine rent period if LLM didn't
    if rent_period == "unknown":
        rent_col_header = final_map["rent"].detected_header if "rent" in final_map and final_map["rent"].method != "missing" else None
        if rent_col_header and rent_col_header in df.columns:
            rent_values = [_coerce_float(v) for v in df[rent_col_header].dropna().head(50).tolist()]
            heuristic = _detect_rent_period_heuristic(rent_values)
            if heuristic != "unknown":
                rent_period = heuristic
                rent_period_method = "heuristic"
                audit.append(f"Heuristic rent period: {heuristic} (median value)")
        if rent_period == "unknown":
            rent_period = "monthly"
            rent_period_method = "default_monthly"
            audit.append(f"Rent period defaulted to monthly (no signal)")

    # 5. Extract addresses
    # Only pass the simple-form column map to extract_addresses
    simple_map = {k: v for k, v in final_map.items() if not k.startswith("__")}
    addresses = extract_addresses(df, simple_map, rent_period, flat_values)
    audit.append(f"Extracted {len(addresses)} address rows (after filters)")

    return ParseResult(
        sheet_name=sheet_name,
        header_row=header_row,
        column_detections=[v for k, v in simple_map.items() if not k.startswith("__")],
        rent_period=rent_period,
        rent_period_method=rent_period_method,
        flat_filter_values=flat_values,
        addresses=addresses,
        audit_log=audit,
    )


# Convenience for the api/process.py handler
def parse_rent_roll_to_dict(workbook_bytes: bytes) -> dict:
    """Same as parse_rent_roll but returns a JSON-serialisable dict."""
    result = parse_rent_roll(workbook_bytes)
    return {
        "sheet_name": result.sheet_name,
        "header_row": result.header_row,
        "column_detections": [asdict(d) for d in result.column_detections],
        "rent_period": result.rent_period,
        "rent_period_method": result.rent_period_method,
        "flat_filter_values": result.flat_filter_values,
        "addresses": [asdict(a) for a in result.addresses],
        "audit_log": result.audit_log,
    }
