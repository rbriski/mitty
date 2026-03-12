# Super Plan: Phase 2 — Broaden Ingestion (Assessments, Resources, Canvas APIs)

## Meta
- **Source**: tickets/phase2-ingestion.md
- **Phase**: devolved
- **Branch**: feature/phase2-ingestion
- **Created**: 2026-03-11
- **Sessions**: 1

---

## Discovery

### Ticket Summary

Phase 2 extends Mitty's data ingestion beyond courses/assignments/enrollments to include:

1. **Manual entry** for assessments (tests, quizzes, projects) and study resources — MVP path to a useful planner
2. **Canvas API expansion**: quizzes, modules, module items, pages, files, calendar events
3. **Resource chunking pipeline**: split ingested content into ~500-token chunks for future retrieval

### Current State

| Component | Status | Notes |
|-----------|--------|-------|
| Schema (assessments, resources, resource_chunks) | ✅ Complete | Phase 1 created all tables with proper indexes |
| CRUD API (assessments, resources, resource_chunks) | ✅ Complete | Full CRUD with pagination, auth, validation |
| Pydantic schemas | ✅ Complete | Create/Update/Response for all three entities |
| Canvas fetcher pattern | ✅ Ready | `fetch_all()` orchestrator, semaphore concurrency, retry/caching |
| Storage/upsert pattern | ✅ Ready | `store_all()` orchestrator, per-table upsert functions |
| Frontend forms | ❌ Missing | No UI for manual assessment/resource entry |
| Canvas quiz/module/page/file/calendar fetching | ❌ Missing | Only courses, assignments, enrollments fetched |
| Chunking pipeline | ❌ Missing | No text processing for resource content |
| Pydantic models for new Canvas data | ❌ Missing | No Quiz, Module, Page, File, CalendarEvent models |

### Key Codebase Findings

- **Canvas fetcher** (`mitty/canvas/fetcher.py`): 148 lines. `fetch_all()` returns dict with courses/assignments/enrollments/errors. Pattern: individual async fetch functions → add to orchestrator.
- **Canvas client** (`mitty/canvas/client.py`): 309 lines. `get_paginated()` handles Link-header pagination, retry with backoff, rate-limiting, optional caching.
- **Storage** (`mitty/storage.py`): 407 lines. `store_all()` runs upserts sequentially with FK-safe ordering.
- **DB schema** (`mitty/db.py`): assessments has `canvas_assignment_id` FK for linking. Resources has `canvas_module_id` for module linking. ResourceChunks has `embedding_vector` (pgvector).
- **API schemas** (`mitty/api/schemas.py`): `AssessmentType = Literal["test", "quiz", "essay", "lab", "project"]`, `ResourceType = Literal["textbook_chapter", "canvas_page", "file", "link", "notes", "video"]`.
- **Test pattern**: AsyncMock, fixtures in `tests/fixtures/`, `@pytest.mark.asyncio`.

### Scoping Decisions

**DEC-001: Frontend forms — dedicated pages**
- New pages (`/assessments/manage`, `/resources/manage`) using Jinja2+HTMX+Alpine pattern
- Rationale: Keeps class detail page focused; management pages can have richer UI (filters, bulk actions)

**DEC-002: Quiz dedup — link to existing assignment**
- Create assessment from quiz data, link via `canvas_assignment_id` to the existing assignment
- Preserves quiz-specific metadata (time limit, quiz type) while avoiding duplicate entries
- UI must filter on `canvas_assignment_id` to avoid showing duplicates
- Rationale: Richer data for the planner without confusing the user

**DEC-003: Manual + Canvas automation in parallel**
- Build all Canvas fetchers + storage alongside manual entry forms, chunking last
- Rationale: No dependency between manual entry and Canvas automation; parallel work is faster

**DEC-004: Chunking — sentence-boundary with overlap**
- Use tiktoken for token counting, split at sentence boundaries
- ~500 token target with configurable overlap (e.g., 50 tokens)
- Strip HTML tags, handle tables gracefully
- Rationale: Better chunk quality than naive paragraph splits; tiktoken gives accurate counts for future embedding

**DEC-005: Content storage — both resource + chunks**
- Add `content_text` column to `resources` table (migration needed)
- Store full content on resource AND chunked form in `resource_chunks`
- Rationale: Avoids reassembling chunks for display; low redundancy cost since Canvas content is immutable from our perspective

---

## Architecture Review

| Area | Rating | Key Findings |
|------|--------|-------------|
| **Security** | ✅ PASS | All endpoints require auth (JWT via Supabase). Input validated via Pydantic. Canvas token in SecretStr. Frontend uses `x-text` (no XSS). CORS scoped to configured origins. |
| **Security — HTML storage** | ⚠️ CONCERN | Storing Canvas page HTML in `content_text` could introduce stored XSS if rendered unsafely. Must strip/sanitize HTML before storage. Add `bleach` or use `html2text`. |
| **Security — postgrest concurrency** | ⚠️ CONCERN | `postgrest.auth()` mutates shared client state. Race condition possible with concurrent requests. Acceptable for Phase 2 (single-user), needs per-request client in Phase 3+. |
| **Performance** | ✅ PASS | Semaphore + rate-limiting handles 5 new endpoints. ~15 additional API calls per run is well within Canvas quotas. |
| **Performance — store_all()** | ⚠️ CONCERN | Sequential upserts will add ~2-3s. Independent upserts could be parallelized. Polish task, not a blocker. |
| **Performance — chunking** | ⚠️ CONCERN | Tiktoken is CPU-bound. Must use `asyncio.to_thread()` if chunking runs in async context. |
| **Performance — content_text in list queries** | ⚠️ CONCERN | If `content_text` added to `resources`, `select("*")` on list endpoints will return large text. Must exclude from list queries. |
| **Data Model** | ✅ PASS | `assessments`, `resources`, `resource_chunks` tables ready. `canvas_assignment_id` supports quiz linking. Enums cover Phase 2 types. |
| **Data Model — canvas_item_id** | ⚠️ CONCERN | `resources.canvas_module_id` insufficient for item-level dedup on re-sync. Need `canvas_item_id` column. |
| **Data Model — canvas_quiz_id** | ⚠️ CONCERN | No `canvas_quiz_id` on assessments. Needed for idempotent re-sync of quizzes. |
| **Data Model — content_text migration** | ✅ PASS | Additive `ALTER TABLE resources ADD COLUMN content_text TEXT` — backward compatible. |
| **API Design** | ✅ PASS | Full CRUD already exists for assessments, resources, resource_chunks. Pagination, auth, validation all in place. |
| **Testing Strategy** | ✅ PASS | Strong patterns: AsyncMock + fixtures for fetchers, mock Supabase chains for storage, TestClient for API. ~200 new tests estimated. |
| **Testing — chunking** | ⚠️ CONCERN | Entirely new code path. Needs thorough edge case testing: malformed HTML, empty content, abbreviations in sentence splitting, non-ASCII. |
| **Testing — fixtures** | ⚠️ CONCERN | Need 5 new fixture files (quizzes, pages, modules, files, calendar_events) + HTML samples for chunking. |
| **Observability** | ✅ PASS | Existing logging pattern (INFO for progress, DEBUG for raw, WARNING for skips) applies to new fetchers. |

---

## Refinement Log

### Session 1 — 2026-03-11

**DEC-006: Add canvas_quiz_id and canvas_item_id for idempotent re-sync**
- Add `canvas_quiz_id INTEGER UNIQUE` (nullable) to `assessments`
- Add `canvas_item_id INTEGER UNIQUE` (nullable) to `resources`
- Add `module_name VARCHAR` (nullable) to `resources` (denormalized from module)
- Add `module_position INTEGER` (nullable) to `resources`
- Rationale: DB-enforced dedup via upsert on Canvas IDs. Trivial migration, prevents fragile application-level dedup. Manual entries leave these columns NULL.

**DEC-007: HTML sanitization — beautifulsoup4 .get_text()**
- Use existing bs4 dependency, strip all HTML tags to plain text
- Store plain text in `content_text` (resources) and `content_text` (resource_chunks)
- Rationale: Zero new dependencies. Plain text is ideal for chunking + future embeddings. Source URL preserved for formatted viewing.

**DEC-008: Calendar events — auto-create assessments**
- Auto-create assessments from calendar events matching heuristics ("test", "exam", "quiz", "midterm", "final")
- Add `auto_created BOOLEAN DEFAULT FALSE` to assessments for UI distinction
- Add `source VARCHAR` (nullable) to assessments — values: 'manual', 'canvas_quiz', 'calendar_event'
- Rationale: Planner needs dates immediately. False positive risk low for single-student Canvas. Users can delete false positives.

**DEC-009: Module items — flat storage with denormalized module name**
- Store items as `resource` rows with `canvas_module_id`, `canvas_item_id`, `module_name`, `module_position`
- No separate modules table
- Rationale: 80% of hierarchy benefit with zero new tables. Module is a grouping mechanism, not a separate entity. Can add modules table in Phase 3+ if needed for unlock rules.

---

## Detailed Breakdown

### US-001: Schema migration — new columns for Phase 2

**Description:** Add new columns to `assessments` and `resources` tables to support Canvas quiz/module linking, content storage, and auto-created assessment tracking. Applied via Supabase MCP migration.

**Traces to:** DEC-005, DEC-006, DEC-008

**Acceptance Criteria:**
- [ ] `resources` gains: `content_text TEXT`, `canvas_item_id INTEGER UNIQUE`, `module_name VARCHAR`, `module_position INTEGER`
- [ ] `assessments` gains: `canvas_quiz_id INTEGER UNIQUE`, `auto_created BOOLEAN DEFAULT FALSE`, `source VARCHAR`
- [ ] Indexes created on `canvas_item_id` and `canvas_quiz_id`
- [ ] `db.py` updated to reflect new columns (schema reference)
- [ ] `schemas.py` updated: ResourceCreate/Update/Response, AssessmentCreate/Update/Response include new fields
- [ ] Existing data unaffected (all new columns nullable or have defaults)
- [ ] Quality gates pass

**Done when:** Migration applied, `db.py` + `schemas.py` updated, existing tests still green.

**Files:**
- `supabase/migrations/` — new migration SQL
- `mitty/db.py` — add columns to table defs
- `mitty/api/schemas.py` — add new fields to Assessment + Resource schemas

**Depends on:** none

---

### US-002: Pydantic models for new Canvas API objects

**Description:** Add Pydantic v2 models for Canvas Quiz, Module, ModuleItem, Page, FileMetadata, and CalendarEvent. These parse raw Canvas API JSON into validated Python objects.

**Traces to:** DEC-002, DEC-009

**Acceptance Criteria:**
- [ ] `Quiz` model: id, title, quiz_type, due_at, points_possible, time_limit, assignment_id (nullable), description
- [ ] `Module` model: id, name, position, unlock_at, items_count
- [ ] `ModuleItem` model: id, module_id, title, type, content_id, position, page_url, external_url
- [ ] `Page` model: page_id, title, body (HTML), url, published
- [ ] `FileMetadata` model: id, display_name, content_type, size, url, folder_id
- [ ] `CalendarEvent` model: id, title, description, start_at, end_at, context_type, context_code
- [ ] All models use `ConfigDict(extra="ignore")` matching existing pattern
- [ ] Quality gates pass

**TDD:**
- Test each model parses from fixture JSON
- Test nullable/optional fields with missing keys
- Test `extra="ignore"` drops unknown fields

**Done when:** Models importable from `mitty/models.py`, all parse fixture data.

**Files:**
- `mitty/models.py` — add 6 new model classes
- `tests/fixtures/quizzes.json` — new fixture
- `tests/fixtures/modules.json` — new fixture
- `tests/fixtures/pages.json` — new fixture
- `tests/fixtures/files.json` — new fixture
- `tests/fixtures/calendar_events.json` — new fixture
- `tests/test_models.py` — new tests (or extend existing)

**Depends on:** none

---

### US-003: Canvas quiz fetcher + storage

**Description:** Add `fetch_quizzes()` to fetch quizzes per course from Canvas API. Add `upsert_quizzes_as_assessments()` to storage that maps quizzes to assessments with `canvas_quiz_id` for dedup and `canvas_assignment_id` for linking.

**Traces to:** DEC-002, DEC-006

**Acceptance Criteria:**
- [ ] `fetch_quizzes(client, course_id)` calls `GET /api/v1/courses/:id/quizzes` and returns `list[Quiz]`
- [ ] Storage function maps Quiz → assessment row: `assessment_type='quiz'`, `source='canvas_quiz'`, `canvas_quiz_id=quiz.id`
- [ ] If quiz has `assignment_id`, sets `canvas_assignment_id` for linking
- [ ] Upsert uses `on_conflict='canvas_quiz_id'` for idempotent re-sync
- [ ] Tests with mocked responses (happy path, empty list, quiz with/without assignment_id)
- [ ] Quality gates pass

**TDD:**
- `test_fetch_quizzes_parses_fixture`
- `test_fetch_quizzes_empty_list`
- `test_upsert_quizzes_maps_to_assessments`
- `test_upsert_quizzes_links_assignment_id`
- `test_upsert_quizzes_idempotent_resync`

**Done when:** Quizzes fetched from Canvas and stored as assessments with dedup.

**Files:**
- `mitty/canvas/fetcher.py` — add `fetch_quizzes()`
- `mitty/storage.py` — add `upsert_quizzes_as_assessments()`
- `tests/test_canvas/test_fetcher.py` — add TestFetchQuizzes
- `tests/test_storage.py` — add TestUpsertQuizzes

**Depends on:** US-001, US-002

---

### US-004: Canvas modules + module items fetcher + storage

**Description:** Add `fetch_modules()` and `fetch_module_items()` to retrieve course modules and their items. Store items as resources with denormalized module info.

**Traces to:** DEC-006, DEC-009

**Acceptance Criteria:**
- [ ] `fetch_modules(client, course_id)` calls `GET /api/v1/courses/:id/modules?include[]=items` and returns `list[Module]`
- [ ] `fetch_module_items(client, course_id, module_id)` calls items endpoint, returns `list[ModuleItem]`
- [ ] Storage maps ModuleItem → resource row with `canvas_module_id`, `canvas_item_id`, `module_name`, `module_position`
- [ ] Resource type mapped: page→canvas_page, file→file, external_url→link
- [ ] Upsert uses `on_conflict='canvas_item_id'` for idempotent re-sync
- [ ] Tests with mocked responses (modules with items, empty modules, various item types)
- [ ] Quality gates pass

**TDD:**
- `test_fetch_modules_parses_fixture`
- `test_fetch_module_items_parses_fixture`
- `test_upsert_module_items_maps_types`
- `test_upsert_module_items_denormalizes_module_name`
- `test_upsert_module_items_idempotent`

**Done when:** Module items fetched and stored as resources with module context.

**Files:**
- `mitty/canvas/fetcher.py` — add `fetch_modules()`, `fetch_module_items()`
- `mitty/storage.py` — add `upsert_module_items_as_resources()`
- `tests/test_canvas/test_fetcher.py` — add TestFetchModules
- `tests/test_storage.py` — add TestUpsertModuleItems

**Depends on:** US-001, US-002

---

### US-005: Canvas pages fetcher + storage

**Description:** Add `fetch_pages()` to retrieve course page titles and HTML bodies. Store as resources with `content_text` (plain text via bs4 `.get_text()`).

**Traces to:** DEC-005, DEC-007

**Acceptance Criteria:**
- [ ] `fetch_pages(client, course_id)` calls `GET /api/v1/courses/:id/pages` then fetches each page body
- [ ] HTML body stripped to plain text via `BeautifulSoup.get_text()`
- [ ] Stored as resource with `resource_type='canvas_page'`, `content_text` = stripped text, `source_url` = Canvas page URL
- [ ] Tests with mocked responses (page with HTML, empty body, large body)
- [ ] Quality gates pass

**TDD:**
- `test_fetch_pages_parses_fixture`
- `test_fetch_pages_empty_body`
- `test_html_stripping_removes_scripts_and_styles`
- `test_upsert_pages_stores_plain_text`

**Done when:** Pages fetched, HTML stripped, stored as resources with content.

**Files:**
- `mitty/canvas/fetcher.py` — add `fetch_pages()`
- `mitty/storage.py` — add `upsert_pages_as_resources()`
- `tests/test_canvas/test_fetcher.py` — add TestFetchPages
- `tests/test_storage.py` — add TestUpsertPages
- `tests/fixtures/pages.json` — page fixture with HTML body samples

**Depends on:** US-001, US-002

---

### US-006: Canvas files (metadata) fetcher + storage

**Description:** Add `fetch_files()` to retrieve file metadata per course. Store as resources — no content download, just metadata and URLs.

**Traces to:** DEC-006

**Acceptance Criteria:**
- [ ] `fetch_files(client, course_id)` calls `GET /api/v1/courses/:id/files` and returns `list[FileMetadata]`
- [ ] Stored as resource with `resource_type='file'`, `source_url` = file download URL, `title` = display_name
- [ ] Upsert uses `canvas_item_id` = file.id for dedup
- [ ] No file content downloaded
- [ ] Tests with mocked responses (various MIME types, empty list)
- [ ] Quality gates pass

**TDD:**
- `test_fetch_files_parses_fixture`
- `test_fetch_files_empty_list`
- `test_upsert_files_stores_metadata_only`

**Done when:** File metadata fetched and stored as resources.

**Files:**
- `mitty/canvas/fetcher.py` — add `fetch_files()`
- `mitty/storage.py` — add `upsert_files_as_resources()`
- `tests/test_canvas/test_fetcher.py` — add TestFetchFiles
- `tests/test_storage.py` — add TestUpsertFiles

**Depends on:** US-001, US-002

---

### US-007: Canvas calendar events fetcher + storage

**Description:** Add `fetch_calendar_events()` to retrieve calendar events. Auto-create assessments from events matching test/quiz/exam heuristics.

**Traces to:** DEC-008

**Acceptance Criteria:**
- [ ] `fetch_calendar_events(client, course_ids)` calls `GET /api/v1/calendar_events` with context codes and date range
- [ ] Heuristic classifier: title contains "test", "exam", "quiz", "midterm", "final" (case-insensitive)
- [ ] Matching events → assessment rows with `source='calendar_event'`, `auto_created=True`
- [ ] Non-matching events logged at DEBUG and skipped
- [ ] Tests: matching titles, non-matching titles, edge cases ("Quiz Bowl" false positive)
- [ ] Quality gates pass

**TDD:**
- `test_fetch_calendar_events_parses_fixture`
- `test_classify_event_matches_test_keywords`
- `test_classify_event_ignores_non_academic`
- `test_upsert_calendar_assessments_sets_auto_created`
- `test_upsert_calendar_assessments_idempotent`

**Done when:** Calendar events fetched, test-like events auto-create assessments.

**Files:**
- `mitty/canvas/fetcher.py` — add `fetch_calendar_events()`
- `mitty/canvas/classify.py` — new file for event classification heuristics
- `mitty/storage.py` — add `upsert_calendar_events_as_assessments()`
- `tests/test_canvas/test_fetcher.py` — add TestFetchCalendarEvents
- `tests/test_canvas/test_classify.py` — new tests for classifier
- `tests/test_storage.py` — add TestUpsertCalendarAssessments

**Depends on:** US-001, US-002

---

### US-008: Extend fetch_all() + store_all() orchestrators

**Description:** Wire all new fetchers into `fetch_all()` and all new storage functions into `store_all()`. New endpoints fetched per-course with existing semaphore concurrency. Storage runs in FK-safe order.

**Traces to:** DEC-003

**Acceptance Criteria:**
- [ ] `fetch_all()` returns new keys: `quizzes`, `modules`, `pages`, `files`, `calendar_events`
- [ ] Per-course fetching uses existing semaphore for bounded concurrency
- [ ] Per-course failures logged and appended to `errors`, don't block other courses
- [ ] `store_all()` calls new upsert functions in correct order (resources before chunks)
- [ ] Calendar events fetched once (global, not per-course) with all course context codes
- [ ] Existing courses/assignments/enrollments fetching unchanged
- [ ] Tests: orchestrator with all new data types, partial failure handling
- [ ] Quality gates pass

**Done when:** Full scrape pipeline fetches and stores all Phase 2 data types.

**Files:**
- `mitty/canvas/fetcher.py` — extend `fetch_all()`
- `mitty/storage.py` — extend `store_all()`
- `tests/test_canvas/test_fetcher.py` — extend TestFetchAll
- `tests/test_storage.py` — extend TestStoreAll

**Depends on:** US-003, US-004, US-005, US-006, US-007

---

### US-009: Resource chunking pipeline

**Description:** Build a chunking module that splits resource `content_text` into ~500-token chunks with sentence-boundary awareness and configurable overlap. Uses tiktoken for token counting. Runs via `asyncio.to_thread()` since tiktoken is CPU-bound.

**Traces to:** DEC-004, DEC-007

**Acceptance Criteria:**
- [ ] `chunk_text(text, target_tokens=500, overlap_tokens=50)` splits text at sentence boundaries
- [ ] Token counting via tiktoken (cl100k_base encoding)
- [ ] Each chunk: `content_text`, `chunk_index`, `token_count`
- [ ] Empty/whitespace-only text returns empty list
- [ ] HTML already stripped before chunking (by storage layer in US-005)
- [ ] Async wrapper uses `asyncio.to_thread()` for CPU-bound work
- [ ] Storage function creates resource_chunks rows from chunked output
- [ ] Tests: normal text, single sentence, very long text, empty text, non-ASCII
- [ ] Quality gates pass

**TDD:**
- `test_chunk_text_splits_at_sentence_boundaries`
- `test_chunk_text_respects_token_target`
- `test_chunk_text_overlap_between_chunks`
- `test_chunk_text_empty_input`
- `test_chunk_text_single_sentence`
- `test_chunk_text_non_ascii`
- `test_chunk_text_very_long_input`
- `test_async_chunk_uses_to_thread`

**Done when:** Chunking module produces correctly-sized chunks with proper indexing.

**Files:**
- `mitty/chunking.py` — new module: `chunk_text()`, `async_chunk_text()`
- `mitty/storage.py` — add `upsert_resource_chunks()`
- `tests/test_chunking.py` — new test file
- `tests/test_storage.py` — add TestUpsertResourceChunks
- `pyproject.toml` — add `tiktoken` dependency

**Depends on:** US-001

---

### US-010: Frontend — assessment management page

**Description:** New Jinja2+HTMX+Alpine page at `/assessments/manage` for listing, creating, editing, and deleting assessments. Uses existing CRUD API endpoints.

**Traces to:** DEC-001

**Acceptance Criteria:**
- [ ] Page renders at `/assessments/manage` with course dropdown filter
- [ ] Create form: course, name, type (dropdown), scheduled date, weight, unit/topic, description
- [ ] List view: table of assessments with edit/delete actions
- [ ] HTMX form submission POSTs to `/assessments/` API
- [ ] Edit inline or modal, PUT to `/assessments/{id}`
- [ ] Delete with confirmation, DELETE to `/assessments/{id}`
- [ ] Auto-created assessments visually distinguished (badge/tag)
- [ ] Page requires authentication
- [ ] Quality gates pass

**Done when:** User can manage assessments end-to-end through the UI.

**Files:**
- `mitty/api/templates/assessments.html` — new template
- `mitty/api/routers/pages.py` — add route for `/assessments/manage`
- `tests/test_api/test_pages.py` — test page renders

**Depends on:** US-001

---

### US-011: Frontend — resource management page

**Description:** New Jinja2+HTMX+Alpine page at `/resources/manage` for listing, creating, editing, and deleting resources. Uses existing CRUD API endpoints.

**Traces to:** DEC-001

**Acceptance Criteria:**
- [ ] Page renders at `/resources/manage` with course + type dropdown filters
- [ ] Create form: course, title, type (dropdown), URL, content text (textarea)
- [ ] List view: grouped by course, shows type badge, module name if present
- [ ] HTMX form submission POSTs to `/resources/` API
- [ ] Edit/delete with existing CRUD endpoints
- [ ] Page requires authentication
- [ ] Quality gates pass

**Done when:** User can manage resources end-to-end through the UI.

**Files:**
- `mitty/api/templates/resources.html` — new template
- `mitty/api/routers/pages.py` — add route for `/resources/manage`
- `tests/test_api/test_pages.py` — test page renders

**Depends on:** US-001

---

### US-012: Integrate chunking into resource storage pipeline

**Description:** Wire the chunking pipeline into the storage flow so that when resources with `content_text` are stored (from Canvas pages or manual entry), chunks are automatically generated and stored.

**Traces to:** DEC-004, DEC-005

**Acceptance Criteria:**
- [ ] After upserting resources with `content_text`, run chunking and upsert chunks
- [ ] Existing resource_chunks for the resource are replaced on re-sync (delete + insert)
- [ ] Chunking runs via `asyncio.to_thread()` in the storage pipeline
- [ ] Empty `content_text` skips chunking
- [ ] Tests: resource with content → chunks created, resource without content → no chunks
- [ ] Quality gates pass

**Done when:** Resources with content automatically have chunks generated and stored.

**Files:**
- `mitty/storage.py` — integrate chunking into `store_all()` after resource upserts
- `tests/test_storage.py` — add TestResourceChunkingIntegration

**Depends on:** US-005, US-008, US-009

---

### US-013: Quality Gate — code review x4 + CodeRabbit

**Description:** Run code reviewer 4 times across the full Phase 2 changeset, fixing all real bugs found each pass. Run CodeRabbit review if available. Ensure all quality gates pass after fixes.

**Acceptance Criteria:**
- [ ] 4 passes of code review with all bugs fixed
- [ ] CodeRabbit review (if available) with findings addressed
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` passes (all tests green)
- [ ] No security issues introduced
- [ ] No regressions in existing functionality

**Done when:** All review passes clean, all quality gates green.

**Files:** Any files modified during review fixes

**Depends on:** US-001 through US-012

---

### US-014: Patterns & Memory — update conventions and docs

**Description:** Update `.claude/rules/`, memory files, and docs with new patterns learned during Phase 2 implementation.

**Acceptance Criteria:**
- [ ] Memory files updated with Phase 2 patterns (chunking, new fetcher conventions, tiktoken usage)
- [ ] Any new gotchas documented (e.g., tiktoken encoding, bs4 text extraction patterns)
- [ ] Architecture docs reflect new modules (`mitty/chunking.py`, `mitty/canvas/classify.py`)

**Done when:** Future sessions can build on Phase 2 patterns without rediscovery.

**Files:** Memory files, `.claude/rules/`, docs as needed

**Depends on:** US-013

---

## Beads Manifest

- **Epic**: mitty-t2d
- **Branch**: feature/phase2-ingestion
- **Tasks**: 14 (12 implementation + Quality Gate + Patterns & Memory)

| Bead | Story | Depends On |
|------|-------|-----------|
| mitty-t2d.1 | US-001: Schema migration | none |
| mitty-t2d.2 | US-002: Pydantic models | none |
| mitty-t2d.3 | US-003: Quiz fetcher + storage | .1, .2 |
| mitty-t2d.4 | US-004: Modules + items fetcher + storage | .1, .2 |
| mitty-t2d.5 | US-005: Pages fetcher + storage | .1, .2 |
| mitty-t2d.6 | US-006: Files fetcher + storage | .1, .2 |
| mitty-t2d.7 | US-007: Calendar events fetcher + storage | .1, .2 |
| mitty-t2d.8 | US-008: Wire fetch_all() + store_all() | .3, .4, .5, .6, .7 |
| mitty-t2d.9 | US-009: Chunking pipeline | .1 |
| mitty-t2d.10 | US-010: Assessment management page | .1 |
| mitty-t2d.11 | US-011: Resource management page | .1 |
| mitty-t2d.12 | US-012: Integrate chunking into storage | .5, .8, .9 |
| mitty-t2d.13 | US-013: Quality Gate | .8, .9, .10, .11, .12 |
| mitty-t2d.14 | US-014: Patterns & Memory | .13 |
