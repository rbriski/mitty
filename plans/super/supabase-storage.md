# Super Plan: Supabase Storage

## Meta
- **Ticket:** tickets/supabase-storage.md
- **Phase:** published
- **PR:** https://github.com/rbriski/mitty/pull/2
- **Sessions:** 1
- **Branch:** `feature/supabase-storage` (from `main`)

---

## Discovery

### Ticket Summary
Replace the Canvas scraper's JSON-to-stdout output with persistent storage in Supabase (hosted Postgres). Store courses, assignments, submissions, and enrollments via upsert. Track grade changes over time with historical snapshots. Preserve JSON output as `--json` flag for debugging.

### Codebase State
- **Existing**: 64 tests passing, full Canvas scraper working on `feature/canvas-scraper` branch (11 commits ahead of main, PR #1 open)
- **Current output**: `fetch_all()` returns dict → `_serialize_result()` → JSON to stdout
- **Models**: Course, Term, Assignment, Submission, Enrollment (pydantic v2, `extra="ignore"`)
- **Config**: `Settings` pydantic model, loads from `.env`, CLI flags via argparse
- **Client pattern**: `CanvasClient` async context manager with retry, pagination, caching
- **Dependencies**: httpx, pydantic, python-dotenv (dev: pytest, pytest-asyncio, respx, ruff)

### Key Constraints (from rules)
- **Async-first**: All I/O functions must be `async def`
- **Type hints**: All public functions, must pass quality gates
- **Testing**: pytest + pytest-asyncio + mocks; never hit real endpoints in CI
- **Quality gates**: `ruff format --check`, `ruff check`, `pytest`
- **Secrets**: Never hardcode; load from `.env` via config helper; use `SecretStr`
- **Architecture rule note**: `architecture.md` says "No persistent database" — this ticket explicitly overrides that
- **Small commits**: Each commit compiles and passes tests
- **Tests-first**: Write failing tests, then implement

### Data Model Mapping
Current pydantic models map to proposed DB schema with these transformations:
- `Course.term.name` → `courses.term_name` (denormalize nested object)
- `Course.term.id` → `courses.term_id` (denormalize nested object)
- `Assignment.submission` → separate `submissions` table (flatten nested model)
- `Enrollment.grades` dict → individual columns (`current_score`, `current_grade`, `final_score`, `final_grade`)
- All tables get `updated_at` (computed at scrape time)
- `grade_snapshots` is insert-only (no upsert), one row per enrollment per scrape

### Scoping Decisions (from user)
- **SDK choice**: Use `supabase-py` official SDK (v2.28+, has async via `acreate_client()`)
- **Branch strategy**: Merge PR #1 first, create `feature/supabase-storage` from `main`
- **Error handling**: Fail with clear error on Supabase connection/auth failure (exit non-zero)
- **Migrations**: Alembic with SQLAlchemy models as source of truth (autogenerate)
- **Env vars**: 3 new vars — `SUPABASE_URL`, `SUPABASE_KEY`, `DATABASE_URL`
- **Migration style**: SQLAlchemy table models → Alembic autogenerate

### New Dependencies
- `supabase` (>=2.28) — async REST API client for data operations
- `sqlalchemy` (>=2.0) — table model definitions for Alembic autogenerate
- `alembic` (>=1.18) — database migration tool
- `psycopg2-binary` (>=2.9) — Postgres driver for Alembic direct connection

---

## Architecture Review

| Area | Rating | Key Findings |
|------|--------|-------------|
| **Security** | **CONCERN** | Secrets pattern solid (SecretStr exists). Must use SecretStr for SUPABASE_KEY + DATABASE_URL. Sanitize tracebacks to avoid credential leaks. Key type (anon vs service role) needs decision — recommend anon key even for single-user. |
| **Performance** | **CONCERN** | Must use batch upserts (5 API calls vs 60-240 individual). Sequential writes fine given FK dependencies. Data volumes small (5-20 courses, 50-200 assignments). Snapshot growth needs retention strategy if scraping frequently. |
| **Data Model** | **CONCERN** | Schema 80% correct. Submissions PK needs fix — `assignment_id` alone works for single-student (1:1 with assignment). Nullable columns need explicit marking. Add `enrollment_id` to grade_snapshots. Add FK indexes. |
| **Testing** | **PASS** | Mock supabase-py with AsyncMock (existing pattern). ~40-50 new tests. Migration testing: manual initially. No integration tests required for merge. |
| **Observability** | **PASS** | Follow existing logging pattern (INFO progress, DEBUG detail, WARNING on errors, all to stderr). |
| **API Design** | **PASS** | supabase-py async API is clean. Batch upsert supported. Context manager pattern for client lifecycle. |

### Concerns to resolve in Refinement
1. **Submissions PK**: `assignment_id` as sole PK — is this single-student only (1:1) or multi-student?
2. **Key type**: Anon key vs service role key — RLS implications
3. **Snapshot growth**: Scrape frequency? Retention policy? Change-detection vs always-insert?
4. **grade_snapshots**: Add `enrollment_id` column?
5. **Batch size**: Any Supabase payload limits to worry about?
6. **Float precision**: Use `float` or `numeric` for scores?

---

## Refinement Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DEC-001 | Use `supabase-py` SDK with `acreate_client()` | Official SDK, full async support since v2.2.0. User preference over raw httpx. |
| DEC-002 | Branch from `main` after merging PR #1 | Clean separation. `feature/supabase-storage` starts fresh from merged main. |
| DEC-003 | Fail hard on Supabase errors | Connection/auth failures print clear error to stderr, exit non-zero. No silent fallback. |
| DEC-004 | Alembic + SQLAlchemy models for migrations | Autogenerate from SQLAlchemy table definitions. Version-controlled, rollback support. |
| DEC-005 | 3 env vars: SUPABASE_URL, SUPABASE_KEY, DATABASE_URL | SDK needs URL+KEY for REST API. Alembic needs DATABASE_URL for direct Postgres. |
| DEC-006 | Submissions PK = assignment_id (1:1) | Single-student scraper. Each assignment has exactly one submission. No multi-student support needed. |
| DEC-007 | Snapshots only on grade change | Compare current enrollment grades to latest snapshot. Insert only if values differ. Reduces storage 80-95%. |
| DEC-008 | Service role key (bypass RLS) | Single-user local CLI. No RLS policies needed. Simpler setup. Key stays in .env (gitignored). |
| DEC-009 | Batch upserts per table | One API call per table (5 total), not one per row. Dramatically reduces network round-trips. |
| DEC-010 | Sequential writes respecting FK order | courses → enrollments → assignments → submissions → grade_snapshots. Prevents FK constraint violations. |
| DEC-011 | Float type for scores | Canvas returns standard float values (96.2, 94.8). Postgres `float8` (double precision) is sufficient. No need for `numeric`. |
| DEC-012 | Add enrollment_id to grade_snapshots | Track which enrollment a snapshot belongs to. Enables correct history if student drops/re-enrolls. |
| DEC-013 | Add FK indexes on all foreign key columns | assignments(course_id), enrollments(course_id), grade_snapshots(course_id, enrollment_id), grade_snapshots(scraped_at). |
| DEC-014 | Mock-first testing, no integration tests required | Use AsyncMock for supabase-py client. Follow existing test_client.py patterns. ~40-50 new tests. |

---

## Detailed Breakdown

### US-001: Add dependencies and extend config
**Description:** Add supabase, sqlalchemy, alembic, psycopg2-binary to pyproject.toml. Extend Settings model with supabase_url, supabase_key (SecretStr), and database_url (SecretStr). Add `--json` flag to CLI arg parser.
**Traces to:** DEC-001, DEC-005, DEC-008
**Files:**
- `pyproject.toml` — edit (add 4 runtime deps)
- `mitty/config.py` — edit (add supabase fields to Settings, add `--json` flag to `parse_args()`)
- `tests/test_config.py` — edit (add tests for new env vars, `--json` flag)
**Acceptance criteria:**
- `uv sync` installs all new deps without errors
- `Settings` has `supabase_url: str | None`, `supabase_key: SecretStr | None`, `database_url: SecretStr | None`
- Supabase fields are optional (None when not set) — allows `--json` mode without Supabase config
- `parse_args()` accepts `--json` flag
- Tests cover: supabase env vars loaded, missing vars return None, `--json` flag parsed
- `uv run ruff check .` and `uv run pytest` pass
**TDD:** Write tests for new Settings fields and `--json` flag first.
**Done when:** Config loads Supabase settings and `--json` flag works.
**Depends on:** none

### US-002: SQLAlchemy table models + Alembic init
**Description:** Define SQLAlchemy Table objects for all 5 tables matching the proposed schema. Initialize Alembic with `alembic init`. Generate first migration via `alembic revision --autogenerate`.
**Traces to:** DEC-004, DEC-006, DEC-012, DEC-013
**Files:**
- `mitty/db.py` — create (SQLAlchemy metadata + Table definitions for courses, assignments, submissions, enrollments, grade_snapshots)
- `alembic.ini` — create (Alembic config, reads DATABASE_URL from env)
- `alembic/env.py` — create (Alembic environment, imports metadata from mitty.db)
- `alembic/versions/001_initial_schema.py` — create (autogenerated migration)
- `tests/test_db.py` — create (verify table definitions: column names, types, PKs, FKs, indexes)
**Acceptance criteria:**
- 5 tables defined with correct columns, types, PKs, FKs per schema
- `submissions.assignment_id` is PK (1:1 with assignment, DEC-006)
- `grade_snapshots` has `enrollment_id` FK (DEC-012)
- FK indexes on `assignments(course_id)`, `enrollments(course_id)`, `grade_snapshots(course_id, enrollment_id)` (DEC-013)
- `grade_snapshots(scraped_at DESC)` index for time-series queries
- All nullable columns explicitly marked (term_id, term_name, points_possible, score, grade, etc.)
- Alembic migration file generated and importable
- Tests verify table structure (column count, PK, FK, nullable flags)
- `uv run ruff check .` and `uv run pytest` pass
**Done when:** `alembic upgrade head` creates all tables correctly.
**Depends on:** US-001

### US-003: Storage module — Supabase client + upsert functions
**Description:** Create `mitty/storage.py` with async Supabase client setup and batch upsert functions for courses, assignments, submissions, enrollments. Transform pydantic models to row dicts.
**Traces to:** DEC-001, DEC-003, DEC-009, DEC-010, DEC-011
**Files:**
- `mitty/storage.py` — create (SupabaseStorage class or functions: `create_storage()`, `upsert_courses()`, `upsert_assignments()`, `upsert_submissions()`, `upsert_enrollments()`)
- `tests/test_storage.py` — create (mock supabase client, test each upsert function)
**Acceptance criteria:**
- `create_storage(settings)` returns async supabase client via `acreate_client()`
- `upsert_courses(client, courses: list[Course])` → batch upsert with ON CONFLICT id
  - Denormalizes Term: extracts `term.name` → `term_name`, `term.id` → `term_id`
  - Sets `updated_at` to current UTC time
- `upsert_assignments(client, assignments: dict[str, list[Assignment]])` → batch upsert with ON CONFLICT id
  - Flattens course_id-keyed dict into flat list
  - Sets `updated_at`
- `upsert_submissions(client, assignments: dict[str, list[Assignment]])` → batch upsert with ON CONFLICT assignment_id
  - Extracts `assignment.submission` (skip if None)
  - Sets `assignment_id` from parent, `updated_at`
- `upsert_enrollments(client, enrollments: list[Enrollment])` → batch upsert with ON CONFLICT id
  - Flattens `grades` dict → individual columns
  - Sets `updated_at`
- `StorageError` custom exception for Supabase failures
- All functions are `async def` with type hints
- Tests: successful upsert per table, empty data, null fields, StorageError on API failure
- `uv run ruff check .` and `uv run pytest` pass
**TDD:** Write tests mocking supabase client with AsyncMock first, then implement.
**Done when:** All upsert functions pass tests with mocked client.
**Depends on:** US-001

### US-004: Grade snapshot with change detection
**Description:** Add `insert_grade_snapshots()` that compares current enrollment grades to the latest snapshot in Supabase and only inserts rows where grades changed.
**Traces to:** DEC-007, DEC-012
**Files:**
- `mitty/storage.py` — edit (add `insert_grade_snapshots()`, `_get_latest_snapshots()`)
- `tests/test_storage.py` — edit (add snapshot tests)
**Acceptance criteria:**
- `_get_latest_snapshots(client, enrollment_ids)` fetches most recent snapshot per enrollment from Supabase
- `insert_grade_snapshots(client, enrollments)` compares current grades to latest snapshot
- Only inserts a new row if any grade field changed (current_score, current_grade, final_score, final_grade)
- Includes `enrollment_id` and `course_id` on each snapshot row
- Sets `scraped_at` to current UTC time
- First scrape (no prior snapshot) always inserts
- Tests: first scrape inserts all, no change skips, partial change inserts changed only, empty enrollments
- `uv run ruff check .` and `uv run pytest` pass
**TDD:** Write change-detection tests first.
**Done when:** Snapshot change detection works correctly in tests.
**Depends on:** US-003

### US-005: store_all orchestrator
**Description:** Create `store_all()` that calls all upsert functions in FK-safe order, wraps in error handling, and logs progress.
**Traces to:** DEC-003, DEC-010
**Files:**
- `mitty/storage.py` — edit (add `store_all()`)
- `tests/test_storage.py` — edit (add orchestration tests)
**Acceptance criteria:**
- `store_all(client, data)` accepts the same dict shape as `fetch_all()` output
- Calls upserts in order: courses → enrollments → assignments → submissions → grade_snapshots (DEC-010)
- Logs INFO for each table upsert (e.g., "Upserting 15 courses...")
- On failure: raises `StorageError` with clear message including table name and original error
- Tests: full success path, failure mid-sequence raises StorageError, empty data succeeds silently
- `uv run ruff check .` and `uv run pytest` pass
**Done when:** Orchestrator passes tests including error scenarios.
**Depends on:** US-004

### US-006: CLI integration — default to Supabase, --json fallback
**Description:** Update `__main__.py` to write to Supabase by default. When `--json` flag is set, preserve old JSON stdout behavior. Require Supabase env vars when not using `--json`.
**Traces to:** DEC-003, DEC-005
**Files:**
- `mitty/__main__.py` — edit (add Supabase write path, `--json` branching)
- `tests/test_cli.py` — edit (add Supabase success/failure tests, `--json` flag tests)
**Acceptance criteria:**
- Default (no `--json`): creates Supabase client, calls `store_all()`, prints success summary to stderr
- With `--json`: preserves current behavior exactly (JSON to stdout, no Supabase)
- Missing SUPABASE_URL or SUPABASE_KEY (without `--json`): prints clear error to stderr, exits 1
- Supabase connection failure: prints error to stderr, exits 1
- `--json` works even without Supabase env vars set
- Tests: default mode mocks store_all, --json mode outputs JSON, missing env vars error, Supabase failure error
- `uv run ruff check .` and `uv run pytest` pass
**Done when:** CLI works in both modes with proper error handling.
**Depends on:** US-005

### US-007: Quality Gate
**Description:** Run code review 4 times across the full changeset, fix all real bugs found each pass. Run all quality gate commands. Run CodeRabbit review if available.
**Traces to:** project rules (quality gates)
**Acceptance criteria:**
- `uv run ruff format --check .` passes
- `uv run ruff check .` passes
- `uv run pytest` passes (all tests, old + new)
- 4 passes of code review completed, all real bugs fixed
- CodeRabbit review completed (if available)
**Done when:** All quality gates green after final review pass.
**Depends on:** US-001 through US-006

### US-008: Patterns & Memory
**Description:** Update memory files and docs with new patterns learned during implementation.
**Traces to:** super-plan convention
**Acceptance criteria:**
- Update MEMORY.md with Supabase storage patterns
- Update patterns.md with any new gotchas (supabase-py, Alembic, etc.)
- Update architecture rule if needed (database layer now exists)
**Done when:** Docs updated.
**Depends on:** US-007

---

---

## Verification

1. `uv sync` — installs all dependencies (including supabase, sqlalchemy, alembic, psycopg2-binary)
2. `uv run ruff format --check .` — formatting OK
3. `uv run ruff check .` — no lint errors
4. `uv run pytest -v` — all tests pass (old 64 + new ~40-50)
5. Set SUPABASE_URL, SUPABASE_KEY, DATABASE_URL in `.env`
6. `uv run alembic upgrade head` — creates all 5 tables in Supabase
7. `uv run python -m mitty` — scrapes Canvas and writes to Supabase (default mode)
8. `uv run python -m mitty --json` — outputs JSON to stdout (legacy mode)
9. `uv run python -m mitty --json --verbose` — shows INFO progress on stderr
10. Verify data in Supabase dashboard: courses, assignments, submissions, enrollments populated
11. Run scraper again — verify upserts (no duplicates), snapshots only on change

---

## Beads Manifest
*(Pending — Phase 7)*
