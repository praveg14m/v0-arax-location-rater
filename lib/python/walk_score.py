# lib/python/walk_score.py
#
# Walk Score API client.
#
# Behaviour
# ---------
# - One unique request per (street, house_number, city) tuple. Deduplicate
#   before issuing calls.
# - Concurrency: cap at 8 in-flight requests via asyncio.Semaphore to respect
#   Walk Score's published rate limits.
# - Retry policy: up to 3 attempts on 429/5xx with exponential backoff
#   (0.5s, 1.5s, 4.5s). On non-retryable errors (404, 422), record the
#   failure and continue.
# - Returns a list of Score records. Failures are surfaced as Score(... score=None,
#   reason="...") so callers can include them in the review payload.
#
# The WALK_SCORE_API_KEY is provided via Vercel project env vars and passed
# in by the caller; this module never reads env directly.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Score:
    street: str
    house_number: str
    city: str
    score: int | None
    reason: str | None


async def score_addresses(addresses: list, api_key: str) -> list[Score]:  # type: ignore[no-untyped-def]
    """Score a list of addresses against the Walk Score API.

    `addresses` is a list of Address objects from parse_rent_roll. The function
    deduplicates by (street, house_number, city) before calling the API, and
    expands the result list back to one entry per input address.
    """
    raise NotImplementedError("TODO: implement against real master workbook")
