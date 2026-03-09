# Mitty — Assignment & Grade Scraper

## Project overview
Scrape assignments from Canvas LMS (https://mitty.instructure.com/) and grades from a secondary portal. Python project using ZenRows for authenticated web scraping.

## Tech stack
- **Language**: Python 3.12+
- **Package manager**: `uv` (lockfile: `uv.lock`, manifest: `pyproject.toml`)
- **Linting / formatting**: `ruff` (format + check)
- **Type checking**: `ty`
- **Web scraping**: ZenRows SDK (`zenrows`) for JS-rendered / anti-bot pages
- **HTTP**: `httpx` (async) for direct API calls where possible
- **HTML parsing**: `beautifulsoup4` + `lxml`

## Key commands
```bash
uv run python -m mitty              # run the scraper
uv run ruff check .                 # lint
uv run ruff format .                # format
uv run ty check                     # typecheck
uv run pytest                       # tests
```

## Project structure (target)
```
mitty/
├── __init__.py
├── __main__.py          # CLI entry point
├── config.py            # Settings / env loading
├── canvas/
│   ├── __init__.py
│   ├── auth.py          # Canvas login / session management
│   └── assignments.py   # Assignment scraping logic
├── grades/
│   ├── __init__.py
│   ├── auth.py          # Grade portal login / session management
│   └── scraper.py       # Grade scraping logic
└── models.py            # Shared data models (Assignment, Grade, etc.)
tests/
├── conftest.py
├── test_canvas/
└── test_grades/
```

## Conventions

### Secrets & credentials
- **Never** hardcode credentials, API keys, or tokens in source files.
- All secrets go in `.env` (gitignored). Load via `os.environ` or a config helper.
- Required env vars: `ZENROWS_API_KEY`, `CANVAS_USERNAME`, `CANVAS_PASSWORD`, plus grade-portal credentials (TBD).

### Scraping patterns
- Prefer Canvas REST API (`/api/v1/...`) with a session token over HTML scraping when available — it's faster and more stable.
- Use ZenRows only when pages require JS rendering or have anti-bot protection.
- Add reasonable delays / rate-limiting between requests; don't hammer endpoints.
- Cache raw responses locally during development to avoid repeated logins (`data/.cache/`, gitignored).

### Code style
- Use `dataclass` or `pydantic.BaseModel` for structured data (assignments, grades).
- Async-first where practical (`httpx.AsyncClient`).
- Keep scraping logic (selectors, parsing) separate from I/O (fetching, saving).
- Type-annotate all public functions; `ruff` + `ty` must pass clean.

### Error handling
- Wrap login flows with clear error messages on auth failure.
- Retry transient HTTP errors (429, 5xx) with exponential backoff.
- Log at INFO for scrape progress, DEBUG for raw responses, WARNING for skipped items.

### Testing
- Mock HTTP responses in tests (use `respx` or `pytest-httpx`); never hit real endpoints in CI.
- Fixture files for sample HTML/JSON go in `tests/fixtures/`.

## Quality gates (run before calling work done)
```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

## Git
- `.env`, `data/`, `__pycache__/`, `.ruff_cache/` are gitignored.
- Small, logical commits; imperative mood messages.
