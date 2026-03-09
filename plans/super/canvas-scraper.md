# Super Plan: Canvas Scraper

## Meta
- **Ticket:** tickets/canvas-scraper-plan.md
- **Phase:** detailing
- **Sessions:** 1
- **Branch:** (TBD — will create `feature/canvas-scraper` on approval)

---

## Discovery

### Ticket Summary
Build a Python CLI tool that scrapes courses, assignments, and grades from Canvas LMS at `mitty.instructure.com` using the Canvas REST API with a personal access token. Output JSON to stdout. Student account (not observer).

### Scoping Decisions (from user)
- **Account type**: Student (no observer detection needed)
- **Output format**: JSON to stdout (no `rich` dependency)
- **Course scope**: All courses (active + completed + past terms)
- **Grades portal**: Skip for now — Canvas API only

### Codebase State
- **Greenfield** — zero Python files, no `pyproject.toml`, no commits
- `.env` already has `CANVAS_TOKEN`, `ZENROWS_API_KEY`, and Canvas credentials
- `.gitignore` covers `.env`, `data/`, `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`
- Beads issue tracker initialized but empty
- Comprehensive rules in `.claude/rules/` (architecture, coding-style, testing, git-workflow)

### Key Constraints (from rules)
- **Async-first**: `httpx.AsyncClient`, all I/O functions `async def`, never block the event loop
- **Type hints**: all public functions, must pass `uv run ty check`
- **Testing**: pytest + pytest-asyncio + respx for mocking; never hit real endpoints
- **Quality gates**: `ruff format --check`, `ruff check`, `ty check`, `pytest` — all must pass
- **Git**: feature branches from `main`, small logical commits, imperative mood
- **Beads**: use `bd` for all task tracking (not markdown TODOs)
- **Secrets**: never hardcode; load from `.env` via config helper
- **Scraping**: prefer REST API over HTML; use ZenRows only for JS-rendered/anti-bot pages
- **Caching**: raw responses in `data/.cache/` during dev

### Deviation from CLAUDE.md
The project structure in CLAUDE.md shows `canvas/auth.py` for login/session management. Since we're using Bearer token auth (no login flow needed), we'll use `canvas/client.py` instead — a generic API client with auth headers, pagination, retry, and caching.

---

## Architecture Review

| Area | Rating | Key Findings |
|------|--------|-------------|
| **Security** | **CONCERN** | Token handling sound. Cache files need `0600` perms. DEBUG logging contains PII — must be off by default, logs to stderr. |
| **API Design** | **PASS** | Async context manager, Link-header pagination, pydantic v2 parsing, fetch/client separation all solid. |
| **Performance** | **PASS** | `per_page=100`, semaphored concurrency, rate-limit delay, dev caching appropriate. Need to specify semaphore size. |
| **Observability** | **PASS** | INFO/DEBUG split correct for CLI. Logs must go to stderr (stdout = JSON data). |
| **Testing** | **PASS** | 5-layer strategy (models, client, fetch, integration, CLI) covers the right boundaries. |

### Concerns to resolve in Refinement
1. Cache file permissions + expiry strategy
2. PII in DEBUG logs — stderr routing, off by default
3. Concurrent fetch error isolation (skip failed course vs abort all?)
4. Retry sleep testability (inject sleep dependency)
5. Semaphore concurrency limit default

---

## Refinement Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DEC-001 | Student account only | User confirmed student account. No observer detection needed — removes `detect_account_type()` and observees endpoint. |
| DEC-002 | JSON output to stdout | User chose JSON over rich tables. No `rich` dependency. `json.dumps()` with indent. |
| DEC-003 | Fetch all courses | No `enrollment_state` filter. Include active, completed, and past-term courses. |
| DEC-004 | Canvas API only | Skip grades portal entirely. No `grades/` package, no ZenRows, no beautifulsoup4. |
| DEC-005 | Skip + continue on failure | If fetching assignments for a course fails, log warning, continue. JSON output includes `"errors"` array. |
| DEC-006 | Minimal CLI flags | `--no-cache`, `--verbose` (INFO->stderr), `--debug` (DEBUG->stderr). Use `argparse`. |
| DEC-007 | Cache: 0600 perms + 1hr TTL | Cache key = SHA256(url+params). Files chmod 0600. Skip entries older than 1 hour. |
| DEC-008 | Logs to stderr, default WARNING | `logging.getLogger("mitty")` -> `StreamHandler(sys.stderr)`. Default level WARNING. |
| DEC-009 | Semaphore = 3 concurrent | Conservative default for Canvas rate limits. Configurable via `MAX_CONCURRENT` env var. |
| DEC-010 | Injectable sleep for retry | `CanvasClient` accepts `_sleep` callable (default `asyncio.sleep`) for testable backoff. |

---

## Detailed Breakdown

### US-001: Project scaffold
**Description:** Create pyproject.toml, package directories, and install dependencies with uv.
**Traces to:** DEC-002 (no rich), DEC-004 (no zenrows/bs4)
**Files:**
- `pyproject.toml` — create (deps: httpx, pydantic, python-dotenv; dev: pytest, pytest-asyncio, respx, ruff)
- `mitty/__init__.py` — create (empty docstring)
- `mitty/canvas/__init__.py` — create
- `tests/__init__.py` — create
- `tests/test_canvas/__init__.py` — create
**Acceptance criteria:**
- `uv sync` completes without errors
- `uv run python -c "import mitty"` succeeds
- `uv run ruff check .` passes
**Done when:** Package installs and imports cleanly.
**Depends on:** none

### US-002: Config module
**Description:** Settings model loading CANVAS_TOKEN from .env, plus CLI argument parsing for --no-cache, --verbose, --debug.
**Traces to:** DEC-006 (CLI flags), DEC-007 (cache config), DEC-008 (log levels), DEC-009 (semaphore)
**Files:**
- `mitty/config.py` — create
- `tests/test_config.py` — create
**Acceptance criteria:**
- `load_settings()` reads CANVAS_TOKEN from env, raises ValueError if missing
- Settings has: canvas_base_url, canvas_token, cache_dir, cache_enabled, cache_ttl_seconds, request_delay, max_retries, per_page, max_concurrent
- `parse_args()` returns parsed CLI args (--no-cache, --verbose, --debug)
- Tests cover: missing token error, default values, env var overrides
**TDD:** Write test for missing token -> ValueError first, then implement.
**Done when:** `uv run pytest tests/test_config.py` passes.
**Depends on:** US-001

### US-003: Data models
**Description:** Pydantic v2 models for Canvas API response parsing: Course, Term, Assignment, Submission, Enrollment.
**Traces to:** DEC-003 (all courses — no filtering in models)
**Files:**
- `mitty/models.py` — create
- `tests/fixtures/courses.json` — create (sample Canvas API response)
- `tests/fixtures/assignments.json` — create
- `tests/fixtures/enrollments.json` — create
- `tests/test_models.py` — create
**Acceptance criteria:**
- All models use `ConfigDict(extra="ignore")` to handle unknown Canvas fields
- Nullable fields (due_at, score, grade, submission, term) parse correctly
- `model_validate()` works on fixture data matching real Canvas JSON shapes
- Tests cover: happy path, nullable fields, extra fields ignored, type coercion
**TDD:** Write model validation tests from fixture data first, then define models.
**Done when:** `uv run pytest tests/test_models.py` passes.
**Depends on:** US-001

### US-004: Canvas client — core HTTP
**Description:** Async CanvasClient context manager with Bearer auth, single-request get(), retry with exponential backoff, and rate limiting.
**Traces to:** DEC-008 (logging), DEC-009 (semaphore), DEC-010 (injectable sleep)
**Files:**
- `mitty/canvas/client.py` — create
- `tests/test_canvas/test_client.py` — create
**Acceptance criteria:**
- `CanvasClient(settings)` as async context manager creates/closes httpx.AsyncClient
- `get(path, params)` sends request with `Authorization: Bearer <token>` header
- Retry with backoff on 429/5xx (up to max_retries). No retry on 401/403.
- `CanvasAuthError` raised on 401/403 with clear message
- `CanvasAPIError` raised on other 4xx
- Rate-limit delay (`asyncio.sleep(request_delay)`) between requests
- `_sleep` injectable for testing
- Tests: auth header, 429 retry, 5xx retry, 401 raises auth error, 404 raises API error, rate-limit delay applied
**TDD:** Write auth header test and 401 error test first, then implement.
**Done when:** `uv run pytest tests/test_canvas/test_client.py` passes.
**Depends on:** US-002

### US-005: Pagination + caching
**Description:** Add get_paginated() to CanvasClient (follows Link rel="next" headers) and file-based JSON caching with TTL.
**Traces to:** DEC-007 (cache perms + TTL)
**Files:**
- `mitty/canvas/client.py` — edit (add get_paginated, cache methods)
- `tests/test_canvas/test_client.py` — edit (add pagination + cache tests)
**Acceptance criteria:**
- `get_paginated(path, params)` follows Link headers, returns concatenated list
- `_parse_link_header()` handles Canvas Link header format (case-insensitive)
- Single-page response (no Link header) returns items directly
- Empty response returns empty list
- Cache: writes JSON to `data/.cache/<sha256>.json` with 0600 permissions
- Cache: reads from cache if file exists and < cache_ttl_seconds old
- Cache: skipped when cache_enabled=False (--no-cache)
- Tests: multi-page pagination, single page, empty, cache hit, cache miss, cache disabled, cache expiry
**Done when:** All pagination + cache tests pass.
**Depends on:** US-004

### US-006: Fetch functions
**Description:** High-level async functions that use CanvasClient to fetch courses, assignments, and enrollments, parsing responses into pydantic models.
**Traces to:** DEC-001 (student — no observees), DEC-003 (all courses)
**Files:**
- `mitty/canvas/fetcher.py` — create
- `tests/test_canvas/test_fetcher.py` — create
**Acceptance criteria:**
- `fetch_courses(client)` -> `GET /api/v1/courses?include[]=term&per_page=100` -> `list[Course]`
- `fetch_assignments(client, course_id)` -> `GET /api/v1/courses/:id/assignments?include[]=submission&per_page=100` -> `list[Assignment]`
- `fetch_enrollments(client)` -> `GET /api/v1/users/self/enrollments?include[]=current_points&per_page=100` -> `list[Enrollment]`
- Each function passes correct URL path and params to `client.get_paginated()`
- Response JSON parsed via `model_validate()` for each item
- Tests: mock `CanvasClient.get_paginated()` with `AsyncMock`, verify URL/params/parsing. Test empty responses.
**TDD:** Write tests mocking get_paginated first, then implement functions.
**Done when:** `uv run pytest tests/test_canvas/test_fetcher.py` passes.
**Depends on:** US-003, US-005

### US-007: Fetch orchestration
**Description:** `fetch_all()` that calls all fetch functions concurrently (with semaphore), collects results, and handles per-course errors gracefully.
**Traces to:** DEC-005 (skip + continue), DEC-009 (semaphore=3)
**Files:**
- `mitty/canvas/fetcher.py` — edit (add fetch_all)
- `tests/test_canvas/test_fetcher.py` — edit (add orchestration tests)
**Acceptance criteria:**
- `fetch_all(client, settings)` returns dict: `{"courses": [...], "assignments": {course_id: [...]}, "enrollments": [...], "errors": [...]}`
- Assignment fetching for all courses runs concurrently via `asyncio.gather(return_exceptions=True)` bounded by `asyncio.Semaphore(max_concurrent)`
- If one course's assignments fail, error logged + added to `errors` list, other courses unaffected
- Tests: all courses succeed, one course fails (verify partial results + error), empty course list
**Done when:** Orchestration tests pass including error isolation case.
**Depends on:** US-006

### US-008: CLI entry point
**Description:** `__main__.py` that ties config -> client -> fetch -> JSON output, with logging setup and CLI flags.
**Traces to:** DEC-002 (JSON stdout), DEC-006 (flags), DEC-008 (stderr logging)
**Files:**
- `mitty/__main__.py` — create
- `tests/test_cli.py` — create
**Acceptance criteria:**
- `uv run python -m mitty` outputs valid JSON to stdout
- JSON structure matches fetch_all output: `{"courses": [...], "assignments": {...}, "enrollments": [...], "errors": [...]}`
- `--no-cache` disables caching
- `--verbose` sets logging to INFO on stderr
- `--debug` sets logging to DEBUG on stderr
- Missing CANVAS_TOKEN prints clear error to stderr, exits non-zero
- Auth failure (401) prints clear error to stderr, exits non-zero
- Tests: mock fetch_all, verify JSON output. Test missing token error. Test CLI flag parsing.
**Done when:** `uv run python -m mitty` produces valid JSON (manual test against real Canvas). All pytest tests pass.
**Depends on:** US-007

### US-009: Quality Gate
**Description:** Run code review 4 times across the full changeset, fix all real bugs found each pass. Run all quality gate commands.
**Traces to:** project rules (quality gates)
**Acceptance criteria:**
- `uv run ruff format --check .` passes
- `uv run ruff check .` passes
- `uv run pytest` passes (all tests)
- 4 passes of code review completed, all real bugs fixed
**Done when:** All quality gates green after final review pass.
**Depends on:** US-001 through US-008

### US-010: Patterns & Memory
**Description:** Update CLAUDE.md or memory files with any new patterns learned during implementation.
**Traces to:** super-plan convention
**Acceptance criteria:**
- Any new patterns, gotchas, or lessons captured in appropriate docs
**Done when:** Docs updated if warranted.
**Depends on:** US-009

---

## Verification

1. `uv sync` — installs all dependencies
2. `uv run ruff format --check .` — formatting OK
3. `uv run ruff check .` — no lint errors
4. `uv run pytest -v` — all tests pass
5. Add `CANVAS_TOKEN=<real-token>` to `.env`
6. `uv run python -m mitty` — outputs JSON with courses, assignments, enrollments
7. `uv run python -m mitty --verbose` — shows INFO progress on stderr
8. `uv run python -m mitty | python -m json.tool` — validates JSON output

---

## Beads Manifest

*(Phase 7 — epic and task IDs, filled after approval)*
