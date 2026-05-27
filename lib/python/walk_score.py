# lib/python/walk_score.py
#
# Walk Score client for German residential addresses.
#
# The Walk Score API requires latitude and longitude, NOT just a street
# address. The brief gives us only an API key, so we need a geocoding step
# first. We use OpenStreetMap's Nominatim service which is free, requires no
# key, handles German addresses well, and has a 1 req/sec rate limit.
#
# Pipeline per address
# --------------------
# 1. Geocode (street, city) -> (lat, lon) via Nominatim
# 2. Call Walk Score with (lat, lon, address) -> score 0-100
# 3. Cache both stages in-memory for the lifetime of the job
#
# Concurrency
# -----------
# - Walk Score: up to 8 concurrent requests (semaphore)
# - Nominatim: 1 req/sec (semaphore + delay, per their usage policy)
#
# Retries
# -------
# - Up to 3 attempts on 429/5xx with exponential backoff (0.5s, 1.5s, 4.5s)
# - On non-retryable errors (404, 422, bad data), record failure and continue
#
# Walk Score API endpoint (per the brief and Walk Score's public docs):
#   https://api.walkscore.com/score?format=json&lat=...&lon=...&address=...
#     &transit=1&bike=1&wsapikey=<KEY>
#
# Returns one Score record per input address, with score=None for failures.

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx

# Endpoints
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
WALK_SCORE_URL = "https://api.walkscore.com/score"

# Concurrency
WALK_SCORE_CONCURRENCY = 8
NOMINATIM_CONCURRENCY = 1  # Nominatim usage policy: max 1 req/sec
NOMINATIM_DELAY_S = 1.0

# Retries
MAX_RETRIES = 3
RETRY_BACKOFF_S = [0.5, 1.5, 4.5]
REQUEST_TIMEOUT_S = 15.0

# User agent (Nominatim requires a real identifier)
USER_AGENT = "Arax-Location-Rater/1.0 (asset-management; case-study)"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AddressKey:
    """Unique key for deduplication. Two addresses with the same (street, city) get one call."""

    street: str  # e.g. "Blankenberg 8" (may include house number)
    city: str  # mapped (canonical) city, not the raw rent-roll value


@dataclass(frozen=True)
class Score:
    """One Walk Score result, success or failure."""

    street: str
    city: str
    lat: Optional[float]
    lon: Optional[float]
    score: Optional[int]  # 0-100 if successful, None if failed
    description: Optional[str]  # "Walker's Paradise", "Car-Dependent", etc
    reason: Optional[str]  # populated on failure: "geocoding failed", "rate limit", etc


# ---------------------------------------------------------------------------
# Address cleanup
# ---------------------------------------------------------------------------


def _clean_street(street: str) -> str:
    """Normalise a street string for geocoding.

    Examples:
      "Blankenberg 8, Lahnstein"     -> "Blankenberg 8"  (strip trailing city)
      "Karl-Wagener-Str. 70, 72, 74" -> "Karl-Wagener-Str. 70"  (first number only)
      "  Mozartstrasse  5  "         -> "Mozartstrasse 5"
    """
    s = str(street).strip()
    if not s:
        return s
    # Take only the first comma-separated chunk (drops city suffixes)
    s = s.split(",")[0].strip()
    # Collapse multiple house numbers like "70, 72, 74" -> keep just first
    # (already handled by the comma split above)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s


# ---------------------------------------------------------------------------
# Nominatim geocoder (with caching)
# ---------------------------------------------------------------------------


class Geocoder:
    """Async Nominatim geocoder with per-job cache and rate limiting.

    Respects Nominatim's usage policy: 1 request/second max, identifying
    user-agent. Caches results so a repeated (street, city) pair never
    triggers a second call.
    """

    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        self._cache: dict[AddressKey, Optional[tuple[float, float]]] = {}
        self._sem = asyncio.Semaphore(NOMINATIM_CONCURRENCY)
        self._last_request_ts: float = 0.0

    async def geocode(self, street: str, city: str) -> Optional[tuple[float, float]]:
        """Resolve (street, city) to (lat, lon). Returns None on failure."""
        key = AddressKey(street=street, city=city)
        if key in self._cache:
            return self._cache[key]

        cleaned_street = _clean_street(street)
        query = f"{cleaned_street}, {city}, Germany"

        async with self._sem:
            # Honour Nominatim's 1 req/sec policy
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_ts
            if elapsed < NOMINATIM_DELAY_S:
                await asyncio.sleep(NOMINATIM_DELAY_S - elapsed)
            self._last_request_ts = asyncio.get_event_loop().time()

            for attempt in range(MAX_RETRIES):
                try:
                    resp = await self._client.get(
                        NOMINATIM_URL,
                        params={
                            "q": query,
                            "format": "json",
                            "limit": 1,
                            "countrycodes": "de",
                            "addressdetails": 0,
                        },
                        headers={"User-Agent": USER_AGENT},
                        timeout=REQUEST_TIMEOUT_S,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and isinstance(data, list):
                            lat = float(data[0]["lat"])
                            lon = float(data[0]["lon"])
                            self._cache[key] = (lat, lon)
                            return (lat, lon)
                        # No results - cache the negative
                        self._cache[key] = None
                        return None
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_BACKOFF_S[attempt])
                            continue
                    # Other status: give up, cache negative
                    self._cache[key] = None
                    return None
                except (httpx.RequestError, httpx.TimeoutException, ValueError, KeyError, IndexError):
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_BACKOFF_S[attempt])
                        continue

            self._cache[key] = None
            return None


# ---------------------------------------------------------------------------
# Walk Score client
# ---------------------------------------------------------------------------


class WalkScoreClient:
    """Async Walk Score client with cache, concurrency cap, and retry."""

    def __init__(self, client: httpx.AsyncClient, api_key: str):
        self._client = client
        self._api_key = api_key
        self._cache: dict[AddressKey, Score] = {}
        self._sem = asyncio.Semaphore(WALK_SCORE_CONCURRENCY)

    async def score(
        self,
        street: str,
        city: str,
        lat: float,
        lon: float,
    ) -> Score:
        """Get Walk Score for a single (street, city, lat, lon)."""
        key = AddressKey(street=street, city=city)
        if key in self._cache:
            return self._cache[key]

        full_address = f"{_clean_street(street)}, {city}, Germany"

        async with self._sem:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await self._client.get(
                        WALK_SCORE_URL,
                        params={
                            "format": "json",
                            "lat": lat,
                            "lon": lon,
                            "address": full_address,
                            "transit": 0,  # we only want walk score
                            "bike": 0,
                            "wsapikey": self._api_key,
                        },
                        headers={"User-Agent": USER_AGENT},
                        timeout=REQUEST_TIMEOUT_S,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        # Walk Score status codes (from their docs):
                        #   1 = OK; 2 = score being calculated; 30/31 = invalid coords/key
                        #   40/41/42 = no score available; 500 = API error
                        status = data.get("status")
                        if status == 1 and "walkscore" in data:
                            result = Score(
                                street=street,
                                city=city,
                                lat=lat,
                                lon=lon,
                                score=int(data["walkscore"]),
                                description=data.get("description"),
                                reason=None,
                            )
                            self._cache[key] = result
                            return result
                        if status in (2,):  # being calculated, retry
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_BACKOFF_S[attempt])
                                continue
                            result = Score(
                                street=street, city=city, lat=lat, lon=lon,
                                score=None, description=None,
                                reason="Walk Score still calculating after retries",
                            )
                            self._cache[key] = result
                            return result
                        # Other status - permanent failure
                        result = Score(
                            street=street, city=city, lat=lat, lon=lon,
                            score=None, description=None,
                            reason=f"Walk Score status {status}",
                        )
                        self._cache[key] = result
                        return result
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_BACKOFF_S[attempt])
                            continue
                    # Non-retryable HTTP error
                    result = Score(
                        street=street, city=city, lat=lat, lon=lon,
                        score=None, description=None,
                        reason=f"HTTP {resp.status_code}",
                    )
                    self._cache[key] = result
                    return result
                except (httpx.RequestError, httpx.TimeoutException) as e:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_BACKOFF_S[attempt])
                        continue
                    result = Score(
                        street=street, city=city, lat=lat, lon=lon,
                        score=None, description=None,
                        reason=f"network: {type(e).__name__}",
                    )
                    self._cache[key] = result
                    return result

            result = Score(
                street=street, city=city, lat=lat, lon=lon,
                score=None, description=None,
                reason="Exhausted retries",
            )
            self._cache[key] = result
            return result


# ---------------------------------------------------------------------------
# Top-level: score a list of addresses
# ---------------------------------------------------------------------------


@dataclass
class WalkScoreSummary:
    scores: list[Score] = field(default_factory=list)  # one entry per unique (street, city)
    audit_log: list[str] = field(default_factory=list)


async def score_addresses(
    address_pairs: list[tuple[str, str]],  # list of (street, mapped_city) tuples
    api_key: str,
    progress_callback: Optional[callable] = None,  # type: ignore[type-arg]
) -> WalkScoreSummary:
    """Geocode and Walk Score a list of unique (street, city) pairs.

    The caller is responsible for deduplication upstream; we assume each pair
    is unique. progress_callback is called with (current, total) after each
    Walk Score call (used by /api/status to drive the progress bar).
    """
    summary = WalkScoreSummary()

    # Dedupe defensively
    seen: set[AddressKey] = set()
    unique_pairs: list[tuple[str, str]] = []
    for street, city in address_pairs:
        key = AddressKey(street=street, city=city)
        if key in seen:
            continue
        seen.add(key)
        unique_pairs.append((street, city))

    total = len(unique_pairs)
    summary.audit_log.append(
        f"Walk Score: {total} unique (street, city) pairs to score "
        f"(deduped from {len(address_pairs)} input addresses)"
    )

    if total == 0:
        return summary

    async with httpx.AsyncClient() as client:
        geocoder = Geocoder(client)
        walkscore_client = WalkScoreClient(client, api_key)

        # Step 1: geocode all addresses (serially - Nominatim is 1 req/sec)
        geocoded: list[tuple[str, str, Optional[tuple[float, float]]]] = []
        for street, city in unique_pairs:
            coords = await geocoder.geocode(street, city)
            geocoded.append((street, city, coords))

        geocode_failures = sum(1 for _, _, c in geocoded if c is None)
        summary.audit_log.append(
            f"Geocoding: {len(geocoded) - geocode_failures} successful, "
            f"{geocode_failures} failed (will be skipped at Walk Score step)"
        )

        # Step 2: Walk Score all geocoded addresses concurrently
        async def score_one(idx: int, street: str, city: str, coords: Optional[tuple[float, float]]) -> Score:
            if coords is None:
                return Score(
                    street=street, city=city, lat=None, lon=None,
                    score=None, description=None,
                    reason="geocoding failed (Nominatim returned no result)",
                )
            score = await walkscore_client.score(street, city, coords[0], coords[1])
            if progress_callback is not None:
                progress_callback(idx + 1, total)
            return score

        tasks = [
            score_one(i, street, city, coords)
            for i, (street, city, coords) in enumerate(geocoded)
        ]
        summary.scores = await asyncio.gather(*tasks)

    success_count = sum(1 for s in summary.scores if s.score is not None)
    summary.audit_log.append(
        f"Walk Score: {success_count} succeeded, {total - success_count} failed"
    )
    return summary
