# Arax Properties — Location Rater

Internal tool for Arax Properties asset management. The user uploads a German residential rent roll (.xlsx / .xlsm) and a deal name; the system parses every address, reconciles each city against Arax's master location-ratings workbook, inherits prior pillar adjustments where the city has been rated before, calls Walk Score for every unique street, and emits a date-stamped working copy of the master workbook with all results filled in. The master file is never modified.

## Architecture

```
+---------+      multipart/form-data       +-----------------------+
| Browser | ------------------------------>|  Python serverless    |
| (Next   |   POST /api/process            |  function (Vercel)    |
|  App    |   file + deal_name             |                       |
|  Router)|                                |  - parses bytes in    |
+---------+                                |    memory (openpyxl)  |
    ^  |                                   |  - matches cities     |
    |  | poll /api/status every 2s         |  - inherits prior     |
    |  v                                   |    adjustments        |
    | StatusResponse JSON                  |  - calls Walk Score   |
    |                                      |  - writes workbook    |
    | GET /api/download                    +-----------------------+
    | (response stream of .xlsm bytes)              |
    |                                                v
    |                                        external Walk Score API
```

No external storage. The rent-roll bytes live in the function instance's memory for the lifetime of the job; the generated workbook is streamed back through `/api/download` and never persisted.

## Tech stack

- **Frontend**: Next.js 16 (App Router), React 19, TypeScript, Tailwind v4, sonner, lucide-react.
- **Backend**: Python 3.11 serverless functions on Vercel (`api/*.py`), `openpyxl` for reading and writing the macro-enabled workbook, `requests` for the Walk Score API, `rapidfuzz` for city matching.
- **External services**: Walk Score (street-level scoring).
- **Hosting**: Vercel.

## Setup

```bash
git clone <repo-url>
cd arax-properties
pnpm install
pip install -r requirements.txt
cp .env.example .env.local
# edit .env.local and set WALK_SCORE_API_KEY
```

Required environment variables:

| Variable             | Purpose                                          |
| -------------------- | ------------------------------------------------ |
| `WALK_SCORE_API_KEY` | Auth key for the Walk Score street-scoring API. |

## Local development

```bash
vercel dev
```

`vercel dev` runs both the Next.js frontend and the Python serverless functions in one process, with `/api/:path*` routed through `next.config.mjs` to the Python handlers in `api/`. Hot-reload works for the frontend; Python handlers reload on file save.

The full mocked end-to-end flow (upload → processing timeline → review screen → finalize → download) runs locally without `WALK_SCORE_API_KEY` because the Walk Score module currently returns mocked scores — see the TODO section.

## Deployment

The repo auto-deploys on push to `main` via Vercel's GitHub integration. The Python runtime (3.11), per-function memory (1024 MB), and timeout (800 s on Enterprise) are declared in `vercel.json`. `WALK_SCORE_API_KEY` must be set in the Vercel project's environment variables before any production run.

## Assumptions

> _Placeholder — to be filled in by the team._
>
> Examples to capture: rent-roll column conventions, master workbook sheet/cell anchors, valid German city name set, expected confidence threshold for "fuzzy" vs "unmatched", inheritance scoring rules across prior deal workbooks.

## TODO — modules awaiting real implementations

The following Python modules are scaffolded with `NotImplementedError` and full docstrings describing the expected behaviour. They must be implemented before the tool produces real outputs:

- `lib/python/parse_rent_roll.py` — Read the user's `.xlsx` / `.xlsm` rent roll from in-memory bytes and yield normalised `(address, street, city, postal_code, annual_rent)` rows.
- `lib/python/city_mapping.py` — Reconcile each parsed city against Arax's master city list. Produce exact / fuzzy (`rapidfuzz`) / unmatched buckets with confidence and candidate alternatives.
- `lib/python/inheritance.py` — Locate prior deal workbooks for any city already rated, and pull the most recent pillar adjustment values (these render in `#0066CC` blue in the workbook).
- `lib/python/walk_score.py` — Call the Walk Score API for every unique street in the deal, with retry, rate-limit handling, and per-address failure capture.
- `lib/python/workbook_writer.py` — Open the master location-ratings workbook (read-only template), populate inherited adjustments, walk scores, and per-pillar formulas, preserve macros (`keep_vba=True`), and return the workbook bytes for streaming back through `/api/download`.

In addition:

- `api/_state.py` currently keeps job state in a process-local dict. This is fine for development and Pro-tier single-instance demos, but is **not durable** across function instance restarts. Migrate to Vercel KV (or another shared store) before the tool has multiple concurrent users.

## Known limits

- **Walk Score**: 5,000 calls/day on the free tier. A typical Arax deal touches a few hundred unique streets, so this is comfortably below the cap, but a single extreme-portfolio run could exhaust a full day's quota.
- **Vercel function timeout**: 800 s on Enterprise (declared in `vercel.json`); 300 s on Pro. End-to-end runs to date have completed well inside both, but if a future deal pushes past this limit the workbook step is the most likely culprit and should be moved to a background queue (Vercel Queues, or Inngest).
- **Upload size**: capped at 4 MB by Vercel's serverless function request-body limit. Typical Arax rent rolls are well under this; the frontend surfaces a specific 413 message if a larger file is uploaded.
- **In-memory job state**: jobs live in the function instance's memory. A Vercel cold start or instance recycle between `process` and `confirm` will surface a 404 to the frontend, which renders a "Job not found — please start over" banner. Migrating `_state.py` to Vercel KV removes this constraint.
