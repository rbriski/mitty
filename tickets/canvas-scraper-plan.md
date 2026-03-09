# Mitty Canvas Scraper — Implementation Plan

## Context

You want to scrape courses, assignments, and grades from Canvas LMS at `mitty.instructure.com`. The login uses a multi-domain OAuth2/SSO flow that ZenRows can't easily automate, so we'll use a **personal access token** with the **Canvas REST API** (JSON endpoints). ZenRows will be set up as a dependency for the future grades portal scraper.

You'll generate a token at: Canvas → Profile → Settings → New Access Token, and add it to `.env` as `CANVAS_TOKEN`.

## Approach

- **httpx** (async) for all Canvas API calls with Bearer token auth
- **Pydantic v2** models for parsing Canvas JSON responses (handles nullable fields, extra fields gracefully)
- **rich** for pretty CLI tables showing courses/grades/assignments
- Auto-detect observer vs student account by probing `/api/v1/users/self/observees`
- Pagination via Link headers, retry with backoff on 429/5xx, dev-time caching

## Implementation Steps

### Step 1: Project scaffold
- Create `pyproject.toml` (deps: httpx, pydantic, python-dotenv, rich; dev: pytest, pytest-asyncio, respx, ruff)
- Create all `__init__.py` files for `mitty/`, `mitty/canvas/`, `mitty/grades/`, `tests/`, `tests/test_canvas/`
- `uv sync` to install and generate lockfile
- **Verify**: `uv run python -c "import mitty"` works

### Step 2: Config + Models
- `mitty/config.py` — `Settings` pydantic model, `load_settings()` reading from `.env`
  - Required: `CANVAS_TOKEN`; defaults for base URL, cache dir, rate limit delay
- `mitty/models.py` — `Course`, `Term`, `Assignment`, `Submission`, `Enrollment`, `Observee`
- Test fixtures in `tests/fixtures/` (sample Canvas API JSON)
- Tests: `tests/test_models.py`

### Step 3: Canvas API client
- `mitty/canvas/client.py` — `CanvasClient` (async context manager)
  - `get()` — single request with retry + rate-limit delay
  - `get_paginated()` — follows `Link: rel="next"` headers, returns full list
  - Retry with exponential backoff on 429/5xx; raise `CanvasAuthError` on 401/403
  - Dev-time JSON caching in `data/.cache/`
- Tests: `tests/test_canvas/test_client.py` (using respx to mock httpx)

### Step 4: Fetch logic
- `mitty/canvas/assignments.py`
  - `detect_account_type()` — probe `/users/self/observees`, fallback to student
  - `fetch_courses()` — `GET /api/v1/courses?enrollment_state=active&include[]=term&per_page=100`
  - `fetch_assignments(course_id)` — `GET /api/v1/courses/:id/assignments?include[]=submission&per_page=100`
  - `fetch_enrollments()` — `GET /api/v1/users/:id/enrollments?include[]=current_points`
  - `fetch_all()` — orchestrate everything, concurrent assignment fetching with semaphore
- Tests: `tests/test_canvas/test_assignments.py`

### Step 5: CLI entry point
- `mitty/__main__.py` — `asyncio.run(main())`
  - Load config → create client → fetch all → display with rich tables
  - Course summary table (name, grade, score)
  - Per-course assignment tables (name, due date, score, status)
  - Clear error messages for bad token, network issues
- Placeholder files: `mitty/grades/__init__.py`, `mitty/grades/scraper.py`

### Step 6: Quality gates
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run pytest`
- Manual test: `uv run python -m mitty` against real Canvas (requires your token)

## Key Files
- `pyproject.toml` — project manifest
- `mitty/config.py` — env-based settings
- `mitty/models.py` — pydantic data models
- `mitty/canvas/client.py` — async HTTP client (auth, pagination, retry, cache)
- `mitty/canvas/assignments.py` — fetch orchestration
- `mitty/__main__.py` — CLI entry point

## Pre-requisite from you
Add `CANVAS_TOKEN=<your-token>` to `.env` after generating it from Canvas Settings.
