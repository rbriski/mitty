# Super Plan: Phase 1 — Foundation (Schema, Backend API, Frontend Scaffold)

## Meta
- **Source**: tickets/phase1-foundation.md
- **Phase**: detailing
- **Branch**: feature/phase1-foundation
- **Worktree**: ../worktrees/mitty/phase1-foundation
- **Created**: 2026-03-11
- **Sessions**: 1

---

## Discovery

### Ticket Summary

Phase 1 lays the foundation for Mitty's evolution from a read-only grade dashboard into a study planning and mastery tracking platform. Four categories of work:

1. **New schema (8 tables)**: assessments, resources, resource_chunks, student_signals, study_plans, study_blocks, mastery_states, practice_results
2. **FastAPI backend**: App factory, JWT auth, CORS, health endpoint, Supabase client DI, CRUD endpoints
3. **Frontend scaffold**: Multi-page routing (dashboard, class detail, study plan stub)
4. **Config extraction**: Move hardcoded term, privilege thresholds, and single-student assumption to config

### Current State

| Layer | State |
|-------|-------|
| Schema | 5 tables (courses, assignments, submissions, enrollments, grade_snapshots) via SQLAlchemy Core + Alembic |
| Backend | None — frontend queries Supabase directly via anon key |
| Frontend | Single `web/index.html` with Alpine.js + Tailwind, two views (dashboard/classDetail) via `x-show` |
| Config | Hardcoded term, privilege thresholds, single student |
| Tests | 163 tests, all green |
| Deploy | Docker Compose (scraper + Caddy) on Hetzner VPS |

### Key Codebase Findings

- **SQLAlchemy Core (not ORM)**: `mitty/db.py` uses `sa.Table` on shared `MetaData`
- **Pydantic v2 models**: `mitty/models.py` with `ConfigDict(extra="ignore")`
- **Async Supabase storage**: `mitty/storage.py` — upsert functions, `StorageError`, `store_all()` orchestrator
- **Alembic migrations**: `alembic/versions/001_initial_schema.py` — single migration for all 5 tables
- **FastAPI not in deps**: Would be a new production dependency (+ uvicorn)
- **docker-compose.yml**: Has commented-out `web` and `agent` service placeholders
- **Supabase anon key**: Hardcoded in `web/index.html` line 462

### Ambiguities Identified

1. **Table count**: Ticket says "7 new tables" but defines 8 (study_plans + study_blocks counted as one)
2. **No `user_id` on new tables**: student_signals, study_plans, mastery_states, practice_results are per-student but have no user FK
3. **pgvector for embeddings**: resource_chunks.embedding_vector needs pgvector extension — may not be enabled
4. **Dual schema management**: Alembic migrations vs Supabase dashboard — who's authoritative?
5. **JWT auth mechanism**: Local validation vs Supabase server call? Which key?
6. **Frontend routing**: x-show pattern vs hash router vs HTMX
7. **Config storage**: New DB table, static file, or endpoint?
8. **RLS policies**: Deferred to Phase 7 but new tables need temporary policies
9. **CRUD scope**: Full CRUD or CRU? Pagination? Which tables exactly?
10. **Supabase client DI**: Global client or per-request? Service key or user JWT passthrough?

### Scoping Questions & Decisions

**DEC-001: Migration authority — Supabase only**
- Remove Alembic entirely (dir, dependency, alembic.ini)
- Use Supabase MCP `apply_migration` for all DDL
- Keep SQLAlchemy table defs in `db.py` as code-level reference
- Rationale: Supabase is the production database; Alembic was used out of habit from direct Postgres workflows

**DEC-002: Add `user_id` to per-student tables**
- Add `user_id UUID` (Supabase auth.users FK) to: student_signals, study_plans, mastery_states, practice_results
- Avoids painful migration later when multi-user support is needed
- Rationale: Per-student data must be scoped to a user; retrofitting is harder than adding now

**DEC-003: Include pgvector for embeddings**
- Enable pgvector extension in Supabase
- Use proper `vector` type for resource_chunks.embedding_vector
- Rationale: Phase 4 (retrieval) will need it; adding the column now avoids a schema change later

**DEC-004: Full CRUD for all 8 tables**
- Create, read (list + get), update, delete endpoints for all new tables
- Pagination on list endpoints
- Rationale: Foundation phase should provide complete API surface for later phases to build on

**DEC-005: HTMX + Alpine.js hybrid frontend**
- FastAPI serves Jinja2 templates with HTMX for page transitions
- Alpine.js for in-page reactivity (existing dashboard logic)
- Migrate existing `web/index.html` to templates
- Rationale: Better architecture for scaling to 5+ views; start the journey now rather than outgrowing x-show later

**DEC-006: Config in Supabase `app_config` table**
- New table: `app_config` with structured config (term, privilege thresholds, etc.)
- Backend endpoint to serve config to frontend
- Rationale: Config should be editable without code deploys

---

## Architecture Review

### Review Summary

| Area | Rating | Key Issues |
|------|--------|------------|
| Security | **CONCERN** | JWT auth approach, RLS policies, service role key needed |
| Data Model | **CONCERN** | app_config undefined, indexes missing, pgvector dims unspecified |
| API Design | **PASS** | Error format, HTMX scope clarification, new deps |
| Testing | **PASS** | FastAPI test pattern new, conftest needed, fixtures needed |
| Performance | **CONCERN** | N+1 risk, missing indexes, pagination required |
| Observability | **PASS** | Logging middleware needed, health check design |

### Blockers (must resolve before implementation)

1. **JWT auth**: Use `supabase.auth.getUser()` server-side (not local JWT validation). Requires `SUPABASE_SERVICE_ROLE_KEY`.
2. **RLS policies**: All user-scoped tables need `auth.uid() = user_id` policies. Without them, anon key exposes all data.
3. **Service role key**: Add `SUPABASE_SERVICE_ROLE_KEY` to config/Settings. Backend uses this; frontend keeps anon key.
4. **app_config schema**: Not defined in ticket. Need structured columns: current_term_name, privilege_thresholds (jsonb), privilege_names (jsonb). Singleton row.
5. **Pagination**: All list endpoints must enforce limit+offset (default 50, max 200).

### Concerns (need decisions)

1. **user_id on study_blocks**: Denormalize (add user_id directly) or inherit via plan_id join? Recommend: add it for query efficiency.
2. **pgvector dimension**: Default to 1536 (OpenAI text-embedding-3-small). Cosine distance. IVFFlat index.
3. **HTMX vs Alpine split**: Keep dashboard/class detail client-side (Alpine, fast). Use HTMX for new views (study plan, check-in, practice) that need server logic.
4. **Error tracking**: Sentry or just structured logs for Phase 1? Recommend: logs only, add Sentry in Phase 7.
5. **Error response format**: Standardize with `{error: {code, message, detail}}` on all endpoints.
6. **N+1 avoidance**: Use Supabase nested selects (like existing frontend pattern) in backend. Define query patterns per endpoint.
7. **Cascade deletes**: study_plan → study_blocks (CASCADE), resource → resource_chunks (CASCADE), others RESTRICT.
8. **Missing indexes**: ~12 indexes needed across new tables (scheduled_date, recorded_at, plan_date, etc.).

---

## Refinement Log

### Decisions (continued)

**DEC-007: JWT auth via supabase.auth.getUser()**
- Backend validates JWT by calling Supabase auth API server-side, not local JWT validation
- Requires `SUPABASE_SERVICE_ROLE_KEY` in config (bypasses RLS for server operations)
- Extract user_id from validated session for all user-scoped queries

**DEC-008: RLS policies on all user-scoped tables**
- All tables with `user_id` get `auth.uid() = user_id` policies (SELECT, INSERT, UPDATE, DELETE)
- Service role key bypasses RLS; API enforces its own authorization via get_current_user
- Shared tables (courses, assignments, etc.) keep current open-read policy

**DEC-009: study_blocks user_id — inherit via join**
- No `user_id` on study_blocks; derive from study_plans.user_id via plan_id FK
- Saves a denormalized column; study_blocks always accessed through their parent plan

**DEC-010: pgvector — 1536 dims, cosine, IVFFlat**
- Enable pgvector extension
- `resource_chunks.embedding_vector` = `vector(1536)` nullable
- Cosine distance (`vector_cosine_ops`), IVFFlat index (upgrade to HNSW if >100k chunks)

**DEC-011: HTMX/Alpine split**
- Dashboard + class detail: stay Alpine.js client-side (already fast, proven)
- New views (study plan, check-in, practice): HTMX + Jinja2 templates
- FastAPI serves all views; base template shared

**DEC-012: Structured logs only for Phase 1**
- No Sentry. Use Python logging with structured format (timestamp, level, module, message)
- Add request/response logging middleware for FastAPI
- Revisit error tracking in Phase 7

**DEC-013: Standardized error responses**
- Format: `{error: {code: str, message: str, detail: str | null}}`
- HTTP status codes: 400 (validation), 401 (auth), 404 (not found), 500 (server)

**DEC-014: Cascade delete policy**
- study_plans → study_blocks: CASCADE
- resources → resource_chunks: CASCADE
- All other FKs: RESTRICT

**DEC-015: Indexes included in migrations**
- ~12 indexes across new tables for common filter/sort patterns
- pgvector IVFFlat index on embedding_vector

**DEC-016: New dependencies approved**
- Production: fastapi, uvicorn[standard], PyJWT, jinja2
- Dev: beautifulsoup4 (for HTMX template testing)

**DEC-017: Pagination on all list endpoints**
- Offset/limit pattern, default 50, max 200
- Response wrapper: `{data: [...], total: int, offset: int, limit: int}`

**DEC-018: app_config — singleton structured table**
- Columns: id (PK, CHECK id=1), current_term_name (text), privilege_thresholds (jsonb), privilege_names (jsonb), created_at, updated_at
- Single row; no user_id (global config)

---

## Detailed Breakdown

### Story dependency graph

```
US-001 (cleanup/deps)
  ↓
US-002 (Supabase migrations)
  ↓
US-003 (SQLAlchemy + Pydantic models)
  ↓
US-004 (FastAPI scaffold)
  ↓
US-005 (Auth middleware)
  ↓
US-006, US-007, US-008 (CRUD routers — parallel)
  ↓
US-009 (Frontend scaffold)
  ↓
US-010, US-011 (Frontend templates — parallel)
  ↓
US-012 (Config extraction)
  ↓
US-013, US-014 (Tests — parallel)
  ↓
US-015 (Quality Gate)
  ↓
US-016 (Patterns & Memory)
```

---

### US-001: Cleanup — Remove Alembic, add new dependencies

**Description:** Remove Alembic infrastructure (directory, config, dependency) since Supabase is now the migration authority (DEC-001). Add FastAPI ecosystem dependencies (DEC-016).

**Traces to:** DEC-001, DEC-016

**Acceptance Criteria:**
- [ ] `alembic/` directory deleted
- [ ] `alembic.ini` deleted
- [ ] `alembic` removed from pyproject.toml dependencies
- [ ] `psycopg2-binary` removed (only needed for Alembic direct DB access)
- [ ] New deps added: `fastapi>=0.115`, `uvicorn[standard]>=0.27`, `PyJWT>=2.8`, `jinja2>=3.1`
- [ ] New dev dep: `beautifulsoup4>=4.12`
- [ ] `uv lock` succeeds
- [ ] Existing tests still pass: `uv run pytest`
- [ ] Quality gates pass: `uv run ruff format --check . && uv run ruff check .`

**Done when:** Alembic removed, new deps installable, 163 existing tests pass.

**Files:**
- DELETE: `alembic/` (entire directory), `alembic.ini`
- EDIT: `pyproject.toml` (remove alembic + psycopg2-binary, add new deps)
- EDIT: `mitty/config.py` (remove `database_url` setting if only used by Alembic)
- EDIT: `tests/test_config.py` (update if database_url tested)

**Depends on:** none

---

### US-002: Supabase migrations — 9 tables + pgvector + indexes + RLS

**Description:** Create all new tables in Supabase via migrations. Enable pgvector extension, add all indexes and CHECK constraints, and set up RLS policies for user-scoped tables. This is the data foundation everything else builds on.

**Traces to:** DEC-001, DEC-002, DEC-003, DEC-008, DEC-010, DEC-014, DEC-015, DEC-018

**Acceptance Criteria:**
- [ ] pgvector extension enabled
- [ ] 9 tables created: assessments, resources, resource_chunks, student_signals, study_plans, study_blocks, mastery_states, practice_results, app_config
- [ ] `user_id UUID NOT NULL REFERENCES auth.users` on: student_signals, study_plans, mastery_states, practice_results
- [ ] `embedding_vector vector(1536)` nullable on resource_chunks
- [ ] All FK constraints with correct ON DELETE (CASCADE for plan→blocks, resource→chunks; RESTRICT elsewhere)
- [ ] CHECK constraints: confidence/energy/stress 1-5, mastery_level 0-1, token_count >= 0, app_config id=1
- [ ] Composite unique: (resource_id, chunk_index), (user_id, plan_date), (user_id, course_id, concept)
- [ ] ~12 indexes: scheduled_date, recorded_at DESC, plan_date, plan_id+sort_order, course_id+concept, etc.
- [ ] IVFFlat index on embedding_vector (vector_cosine_ops)
- [ ] RLS enabled on user-scoped tables with `auth.uid() = user_id` policies (SELECT, INSERT, UPDATE, DELETE)
- [ ] Seed app_config row with current hardcoded values (term, privilege thresholds/names)
- [ ] Verify via Supabase MCP: `list_tables` shows all 14 tables (5 existing + 9 new)

**Done when:** All tables, indexes, constraints, and RLS policies are live in Supabase.

**Files:**
- Supabase migrations (via `apply_migration` MCP tool — SQL scripts)

**Depends on:** none (can run parallel with US-001)

---

### US-003: SQLAlchemy table definitions + Pydantic schemas

**Description:** Add SQLAlchemy Core table definitions for all 9 new tables in `db.py` (code-level reference, used by tests). Create Pydantic v2 request/response schemas for all CRUD operations in a new `mitty/api/schemas.py`.

**Traces to:** DEC-002, DEC-003, DEC-013, DEC-017, DEC-018

**TDD:**
- Write schema structural tests first (column types, FKs, indexes) following `test_db.py` pattern
- Write Pydantic model validation tests (happy path, missing fields, extra fields, constraint violations)
- Then implement tables + schemas

**Acceptance Criteria:**
- [ ] 9 new `sa.Table` definitions in `mitty/db.py` matching Supabase schema exactly
- [ ] All indexes defined in SQLAlchemy matching Supabase
- [ ] Pydantic Create/Update/Response schema triplets for all 8 data tables
- [ ] Pydantic schemas for app_config (read + update)
- [ ] `ListResponse[T]` generic wrapper with data, total, offset, limit
- [ ] `ErrorDetail` schema with code, message, detail
- [ ] Field validators: enum values (assessment_type, resource_type, block_type, status, practice_type), range checks (1-5, 0-1)
- [ ] String length limits on free-text fields (blockers, notes, description ≤ 2000 chars)
- [ ] Tests pass for new schema defs + Pydantic validation
- [ ] Quality gates pass

**Done when:** All table defs and schemas defined with passing tests.

**Files:**
- EDIT: `mitty/db.py` (add 9 tables + indexes)
- CREATE: `mitty/api/__init__.py`
- CREATE: `mitty/api/schemas.py` (all Pydantic schemas)
- CREATE: `tests/fixtures/assessments.json`, `resources.json`, `student_signals.json`, `study_plans.json`, `study_blocks.json`, `mastery_states.json`, `practice_results.json`
- EDIT: `tests/test_db.py` (add structural tests for 9 new tables)
- CREATE: `tests/test_api/__init__.py`
- CREATE: `tests/test_api/test_schemas.py` (Pydantic validation tests)

**Depends on:** US-002 (schema must exist in Supabase for reference)

---

### US-004: FastAPI app scaffold

**Description:** Create the FastAPI application with app factory, settings, CORS middleware, request logging, health endpoint, Supabase client lifecycle management, and standardized error handling.

**Traces to:** DEC-005, DEC-012, DEC-013, DEC-016

**Acceptance Criteria:**
- [ ] `mitty/api/app.py` with `create_app()` factory
- [ ] Lifespan: create Supabase AsyncClient on startup, store in `app.state`
- [ ] CORS middleware with configurable origins (from env `ALLOWED_ORIGINS`)
- [ ] Request logging middleware (method, path, status, duration at INFO; 4xx at WARNING; 5xx at ERROR)
- [ ] `GET /health` returns `{status: "ok"}` (checks Supabase connectivity)
- [ ] `GET /api/v1/` prefix on all API routes
- [ ] Standardized error handler returns `{error: {code, message, detail}}`
- [ ] `mitty/api/dependencies.py` with `get_supabase_client()` dependency
- [ ] Settings updated: `supabase_service_role_key`, `allowed_origins`, `fastapi_debug`
- [ ] App can be run: `uv run uvicorn mitty.api.app:create_app --factory`
- [ ] Quality gates pass

**Done when:** `GET /health` responds 200 from running FastAPI app.

**Files:**
- CREATE: `mitty/api/app.py`
- CREATE: `mitty/api/dependencies.py`
- CREATE: `mitty/api/middleware.py` (logging)
- EDIT: `mitty/config.py` (add service_role_key, allowed_origins, fastapi_debug)

**Depends on:** US-001 (FastAPI dependency), US-003 (error schemas)

---

### US-005: Auth middleware

**Description:** Implement JWT authentication via Supabase's `auth.getUser()` server-side. Create `get_current_user` FastAPI dependency that extracts and validates the Bearer token, returning the authenticated user's ID.

**Traces to:** DEC-007, DEC-008

**TDD:**
- Write tests first: valid token → user_id extracted, missing token → 401, invalid token → 401, expired token → 401
- Then implement auth dependency

**Acceptance Criteria:**
- [ ] `mitty/api/auth.py` with `get_current_user()` async dependency
- [ ] Extracts Bearer token from Authorization header
- [ ] Calls Supabase `auth.get_user(token)` using service role client
- [ ] Returns `{user_id: UUID, email: str}` on success
- [ ] Returns 401 with error detail on: missing token, invalid token, expired token
- [ ] Never logs the JWT token itself
- [ ] Tests cover: valid auth, missing header, malformed header, invalid token, Supabase error
- [ ] Quality gates pass

**Done when:** Authenticated requests succeed; unauthenticated requests get 401.

**Files:**
- CREATE: `mitty/api/auth.py`
- CREATE: `tests/test_api/test_auth.py`
- EDIT: `tests/test_api/conftest.py` (add mock auth fixtures)

**Depends on:** US-004 (app scaffold with Supabase client)

---

### US-006: CRUD routers — assessments, resources, resource_chunks

**Description:** Implement full CRUD endpoints for course-scoped content tables. These don't require user_id (they're course-level data), but require auth.

**Traces to:** DEC-004, DEC-013, DEC-017

**TDD:**
- Write endpoint tests first (create, get, list with pagination, update, delete)
- Mock Supabase client responses
- Then implement routers

**Acceptance Criteria:**
- [ ] `mitty/api/routers/assessments.py` — POST, GET /:id, GET / (paginated), PUT /:id, DELETE /:id
- [ ] `mitty/api/routers/resources.py` — POST, GET /:id, GET / (paginated), PUT /:id, DELETE /:id
- [ ] `mitty/api/routers/resource_chunks.py` — POST, GET /:id, GET / (paginated by resource_id), PUT /:id, DELETE /:id
- [ ] All endpoints require auth (get_current_user dependency)
- [ ] List endpoints: offset/limit pagination (default 50, max 200), filter by course_id
- [ ] Responses use Pydantic schemas from US-003
- [ ] 404 for missing resources, 400 for validation errors
- [ ] Supabase nested selects where appropriate (avoid N+1)
- [ ] Tests pass with mocked Supabase client
- [ ] Quality gates pass

**Done when:** All 15 endpoints respond correctly with mocked Supabase.

**Files:**
- CREATE: `mitty/api/routers/__init__.py`
- CREATE: `mitty/api/routers/assessments.py`
- CREATE: `mitty/api/routers/resources.py`
- CREATE: `mitty/api/routers/resource_chunks.py`
- EDIT: `mitty/api/app.py` (register routers)
- CREATE: `tests/test_api/test_assessments.py`
- CREATE: `tests/test_api/test_resources.py`
- CREATE: `tests/test_api/test_resource_chunks.py`

**Depends on:** US-005 (auth middleware)

---

### US-007: CRUD routers — student_signals, study_plans, study_blocks

**Description:** Implement full CRUD for user-scoped study tables. All queries filter by authenticated user_id. study_blocks inherit user scope via plan_id join.

**Traces to:** DEC-004, DEC-007, DEC-009, DEC-013, DEC-017

**TDD:**
- Write tests first, including cross-user access prevention tests
- Mock Supabase to verify user_id filtering on every query

**Acceptance Criteria:**
- [ ] `mitty/api/routers/student_signals.py` — CRUD with user_id filter
- [ ] `mitty/api/routers/study_plans.py` — CRUD with user_id filter
- [ ] `mitty/api/routers/study_blocks.py` — CRUD, verify plan ownership via user_id join
- [ ] All writes inject `user_id` from authenticated user (not from request body)
- [ ] All reads filter by `user_id` (never return other users' data)
- [ ] study_plans list: filter by date range
- [ ] study_blocks list: filter by plan_id, include sort_order
- [ ] Cross-user access tests: user A cannot read/modify user B's data
- [ ] Tests pass, quality gates pass

**Done when:** All 15 endpoints enforce user isolation.

**Files:**
- CREATE: `mitty/api/routers/student_signals.py`
- CREATE: `mitty/api/routers/study_plans.py`
- CREATE: `mitty/api/routers/study_blocks.py`
- EDIT: `mitty/api/app.py` (register routers)
- CREATE: `tests/test_api/test_student_signals.py`
- CREATE: `tests/test_api/test_study_plans.py`
- CREATE: `tests/test_api/test_study_blocks.py`

**Depends on:** US-005 (auth middleware)

---

### US-008: CRUD routers — mastery_states, practice_results, app_config

**Description:** Implement CRUD for learning tracking tables (user-scoped) and the app_config singleton (global, read-heavy).

**Traces to:** DEC-004, DEC-006, DEC-013, DEC-017, DEC-018

**Acceptance Criteria:**
- [ ] `mitty/api/routers/mastery_states.py` — CRUD with user_id filter, filter by course_id
- [ ] `mitty/api/routers/practice_results.py` — CRUD with user_id filter, filter by course_id and study_block_id
- [ ] `mitty/api/routers/config.py` — GET (public, no auth required), PUT (auth required)
- [ ] mastery_states: upsert by (user_id, course_id, concept) composite key
- [ ] practice_results: list with created_at DESC sort
- [ ] app_config: always returns single row (id=1), update merges fields
- [ ] Tests pass, quality gates pass

**Done when:** All endpoints working; config is readable without auth.

**Files:**
- CREATE: `mitty/api/routers/mastery_states.py`
- CREATE: `mitty/api/routers/practice_results.py`
- CREATE: `mitty/api/routers/config.py`
- EDIT: `mitty/api/app.py` (register routers)
- CREATE: `tests/test_api/test_mastery_states.py`
- CREATE: `tests/test_api/test_practice_results.py`
- CREATE: `tests/test_api/test_config.py`

**Depends on:** US-005 (auth middleware)

---

### US-009: Frontend scaffold — Jinja2 + HTMX base template

**Description:** Set up Jinja2 template rendering in FastAPI, create a base template with HTMX + Alpine.js + Tailwind, and configure static file serving. This replaces the single `web/index.html` with a template-based architecture.

**Traces to:** DEC-005, DEC-011

**Acceptance Criteria:**
- [ ] `mitty/api/templates/base.html` — shared layout with `<head>` (Tailwind CDN, Alpine.js CDN, HTMX CDN), nav, content block
- [ ] Jinja2Templates configured in FastAPI app
- [ ] Static files served from `mitty/api/static/` (or `web/static/`)
- [ ] Navigation bar with links: Dashboard, Study Plan (routes via HTMX `hx-get` + `hx-push-url`)
- [ ] Login/logout flow preserved (Supabase Auth via Alpine.js)
- [ ] `GET /` serves the base template with dashboard content
- [ ] Quality gates pass

**Done when:** Base template renders in browser with nav + Alpine.js + HTMX loaded.

**Files:**
- CREATE: `mitty/api/templates/base.html`
- CREATE: `mitty/api/templates/partials/nav.html`
- CREATE: `mitty/api/routers/pages.py` (page-serving routes)
- EDIT: `mitty/api/app.py` (add template config, page router)

**Depends on:** US-004 (FastAPI scaffold)

---

### US-010: Frontend — dashboard + class detail templates

**Description:** Migrate the existing dashboard and class detail views from `web/index.html` into Jinja2 templates. Preserve all Alpine.js interactivity (grade cards, privilege scoreboard, due tomorrow, assignment lists). Dashboard and class detail remain Alpine.js client-side (DEC-011).

**Traces to:** DEC-005, DEC-011

**Acceptance Criteria:**
- [ ] `mitty/api/templates/dashboard.html` — grade overview, privilege scoreboard, due tomorrow, assignment counts
- [ ] `mitty/api/templates/class_detail.html` — overdue, this week, later assignment lists
- [ ] All Alpine.js logic preserved (login, fetchGrades, fetchAssignments, privilege calculation)
- [ ] Supabase JS client queries still work from templates (anon key)
- [ ] View switching works via HTMX navigation (hx-get + hx-push-url)
- [ ] Existing functionality verified: login, grade display, class click, assignment status icons
- [ ] `web/index.html` kept as fallback (not deleted yet)
- [ ] Quality gates pass

**Done when:** Dashboard + class detail look and function identically to current `web/index.html`.

**Files:**
- CREATE: `mitty/api/templates/dashboard.html`
- CREATE: `mitty/api/templates/class_detail.html`
- CREATE: `mitty/api/templates/partials/login.html`
- CREATE: `mitty/api/templates/partials/grade_card.html`
- CREATE: `mitty/api/templates/partials/privilege_scoreboard.html`
- EDIT: `mitty/api/routers/pages.py` (dashboard + class detail routes)

**Depends on:** US-009 (base template)

---

### US-011: Frontend — study plan stub view

**Description:** Create a minimal study plan view as the first HTMX-driven page. Shows today's plan (if any) with blocks, or a "no plan yet" placeholder. This proves the HTMX + Jinja2 pattern works for new views.

**Traces to:** DEC-005, DEC-011

**Acceptance Criteria:**
- [ ] `mitty/api/templates/study_plan.html` — extends base, shows today's study plan
- [ ] Fetches plan data from `/api/v1/study-plans?plan_date=today` via backend (not direct Supabase)
- [ ] If plan exists: render blocks with title, target_minutes, status
- [ ] If no plan: show placeholder with "No study plan for today"
- [ ] Navigation from dashboard via HTMX works (no full page reload)
- [ ] Quality gates pass

**Done when:** Study plan page loads via HTMX navigation and displays data from API.

**Files:**
- CREATE: `mitty/api/templates/study_plan.html`
- CREATE: `mitty/api/templates/partials/study_block.html`
- EDIT: `mitty/api/routers/pages.py` (study plan route)

**Depends on:** US-007 (study_plans CRUD), US-009 (base template)

---

### US-012: Config extraction

**Description:** Replace all hardcoded config values in the frontend with data from the app_config API endpoint. Update the dashboard template to fetch config on load.

**Traces to:** DEC-006, DEC-018

**Acceptance Criteria:**
- [ ] Dashboard fetches term name from `GET /api/v1/config` instead of hardcoded `'2025-2026 Second Semester'`
- [ ] Privilege thresholds loaded from config instead of hardcoded `[8, 10, 11, 12]`
- [ ] Privilege level names loaded from config
- [ ] Config endpoint returns data without requiring auth (public read)
- [ ] Fallback: if config fetch fails, use sensible defaults (graceful degradation)
- [ ] Quality gates pass

**Done when:** No hardcoded term or privilege values remain in templates.

**Files:**
- EDIT: `mitty/api/templates/dashboard.html` (replace hardcoded values with config fetch)
- EDIT: `mitty/api/templates/class_detail.html` (if term filter used here)

**Depends on:** US-008 (config endpoint), US-010 (dashboard template)

---

### US-013: Tests — models, schema, storage

**Description:** Comprehensive tests for all new SQLAlchemy table definitions and Pydantic schemas. Follows existing test_db.py and test_models.py patterns.

**Traces to:** DEC-004

**Acceptance Criteria:**
- [ ] Structural tests for all 9 new SQLAlchemy tables (columns, types, PKs, FKs, indexes, constraints)
- [ ] Pydantic validation tests for all Create/Update/Response schemas
- [ ] Fixture JSON files for all new entities
- [ ] Tests for ListResponse wrapper
- [ ] Tests for ErrorDetail schema
- [ ] Tests for field validators (enum values, ranges, string lengths)
- [ ] All tests pass, quality gates pass

**Done when:** Full test coverage for data layer.

**Files:**
- EDIT: `tests/test_db.py` (add 9 table test classes)
- CREATE: `tests/test_api/test_schemas.py`
- CREATE: test fixture files in `tests/fixtures/`

**Depends on:** US-003 (tables + schemas exist)

*Note: If TDD is followed in US-003, these tests are already written. This story covers any gaps.*

---

### US-014: Tests — API endpoints, auth, config

**Description:** Comprehensive endpoint tests for all CRUD routers and auth middleware. Uses httpx.AsyncClient with FastAPI test app and mocked Supabase client.

**Traces to:** DEC-004, DEC-007

**Acceptance Criteria:**
- [ ] `tests/test_api/conftest.py` with: FastAPI app fixture, mock Supabase client, auth override, async httpx client
- [ ] Auth tests: valid token, missing token, invalid token, expired token
- [ ] CRUD tests for all 8 data table routers (create, get, list, update, delete)
- [ ] Pagination tests: default limit, custom limit, offset, max limit cap
- [ ] User isolation tests: user A cannot access user B's data
- [ ] Config tests: public read, authenticated write
- [ ] Error response format validated on all error paths
- [ ] All tests pass, quality gates pass

**Done when:** All API endpoints have test coverage.

**Files:**
- CREATE: `tests/test_api/conftest.py`
- Tests in `tests/test_api/test_*.py` (may already exist from US-005 through US-008 TDD)

**Depends on:** US-006, US-007, US-008 (routers exist)

*Note: If TDD is followed in US-005-008, these tests are already written. This story covers gaps and integration tests.*

---

### US-015: Quality Gate — code review x4 + validation

**Description:** Run code reviewer 4 times across the full changeset, fixing all real bugs found each pass. Run CodeRabbit review if available. Ensure all quality gates pass after fixes.

**Acceptance Criteria:**
- [ ] 4 passes of code review across full changeset
- [ ] All real bugs fixed (not style nits)
- [ ] CodeRabbit review (if available) — address findings
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` passes (all tests including new ones)
- [ ] No security vulnerabilities introduced
- [ ] No hardcoded secrets

**Done when:** All reviews pass, all quality gates green.

**Depends on:** US-001 through US-014

---

### US-016: Patterns & Memory — update conventions and docs

**Description:** Update project memory, rules, and documentation with patterns learned during Phase 1 implementation.

**Acceptance Criteria:**
- [ ] Update MEMORY.md with new architecture (FastAPI backend, HTMX frontend)
- [ ] Update patterns.md with FastAPI patterns (DI, auth, error handling, pagination)
- [ ] Update CLAUDE.md if any commands/conventions changed
- [ ] Add `testing-project.md` rule with FastAPI test patterns
- [ ] Document Supabase migration workflow (no more Alembic)
- [ ] Document HTMX + Alpine.js split decision

**Done when:** Future sessions have full context on Phase 1 architecture.

**Depends on:** US-015 (Quality Gate)

---

## Beads Manifest

*(Phase 7 — pending)*

| Field | Value |
|-------|-------|
| Epic ID | |
| Task IDs | |
| Worktree | ../worktrees/mitty/phase1-foundation |
