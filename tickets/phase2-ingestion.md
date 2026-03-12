# Phase 2: Broaden Ingestion — Assessments, Resources, Canvas APIs

## Context

The scraper currently pulls courses, assignments (with submissions), and enrollments. The planner (Phase 3) needs richer data: upcoming tests/quizzes, course content (modules, pages, files), and calendar events. Canvas already exposes official APIs for all of these — most of the missing school-side data can come from Canvas before inventing manual workflows.

But the fastest MVP path is: manual test entry first, then automate Canvas ingestion. That gets a useful planner weeks earlier.

## Goals

- Add manual entry for assessments (tests, quizzes, projects) and study resources
- Extend the Canvas scraper to fetch quizzes, modules, pages, files, and calendar events
- Build a resource chunking pipeline to prepare content for retrieval

## What Canvas exposes that we don't use yet

| API | Endpoint | What it gives us |
|-----|----------|-----------------|
| Quizzes | `GET /api/v1/courses/:id/quizzes` | Quiz title, due date, points, time limit, quiz type |
| Modules | `GET /api/v1/courses/:id/modules` | Course sequencing, unlock rules, module items |
| Module Items | `GET /api/v1/courses/:id/modules/:id/items` | Pages, files, assignments, external URLs per module |
| Pages | `GET /api/v1/courses/:id/pages` | Course content pages with HTML body |
| Files | `GET /api/v1/courses/:id/files` | File metadata: name, type, size, URL, folder |
| Calendar Events | `GET /api/v1/calendar_events` | Test dates, course events, scheduling |

## Work items

### 1. Manual assessment entry (MVP — do first)
**Why first**: The planner needs assessment dates immediately. Waiting for full Canvas automation delays the core product.

- Add a form in the frontend: course (dropdown), name, type (test/quiz/essay/lab/project), scheduled date, weight (optional), unit/topic (optional), notes
- POST to `POST /assessments` API endpoint
- List/edit/delete existing assessments
- This is the fastest path to a useful planner

### 2. Manual resource upload
- Add a form for adding study resources: course, title, type (textbook_chapter/notes/video/link), URL or text content, sort order
- POST to `POST /resources` API endpoint
- This enables the retrieval system before Canvas automation is complete

### 3. Canvas quiz fetching
- `GET /api/v1/courses/:id/quizzes` — fetch per course
- Map to `assessments` table with `assessment_type='quiz'`
- Include: title, due_at, points_possible, quiz_type, time_limit
- Link to Canvas via `canvas_assignment_id` where applicable
- Extend `fetch_all()` in `mitty/canvas/fetcher.py`
- Add tests with mocked responses

### 4. Canvas modules + module items
- `GET /api/v1/courses/:id/modules` — module name, position, unlock_at, prerequisites
- `GET /api/v1/courses/:id/modules/:id/items` — pages, files, assignments, external URLs
- Modules encode course sequencing and unlock rules — useful for understanding what to study when
- Store items as `resources` with `canvas_module_id` linkage
- Add tests

### 5. Canvas pages
- `GET /api/v1/courses/:id/pages` and `GET /api/v1/courses/:id/pages/:url`
- Fetch page titles and HTML bodies
- Store as `resources` with `resource_type='canvas_page'`
- Page body HTML feeds into the chunking pipeline
- Add tests

### 6. Canvas files (metadata only)
- `GET /api/v1/courses/:id/files`
- Fetch metadata: display_name, content_type, size, url, folder
- Store as `resources` with `resource_type='file'`
- Do NOT download file contents yet — just metadata and URLs
- Add tests

### 7. Canvas calendar events
- `GET /api/v1/calendar_events` with date range params
- Map events that look like tests/quizzes/exams to `assessments`
- Use title heuristics (contains "test", "exam", "quiz") and event type to classify
- This fills the assessment calendar gap critical for the planner
- Add tests

### 8. Resource chunking pipeline
- When resources are ingested (Canvas pages, uploaded notes, etc.), chunk their text content into `resource_chunks`
- Strategy: split by paragraphs/sections, ~500 token chunks with overlap
- Store: chunk text, index, token count
- Embedding generation deferred to Phase 5 (AI roles)
- Run as background processing step in the storage layer
- Add tests for chunking logic with sample HTML and text content

## Implementation order

```
Manual assessment entry ─┐
Manual resource upload ──┤── These are MVP, do first
                         │
Canvas quiz fetching ────┤
Canvas calendar events ──┤── These enrich assessment data
                         │
Canvas modules ──────────┤
Canvas pages ────────────┤── These provide study content
Canvas files (metadata) ─┤
                         │
Resource chunking ───────┘── Runs on any ingested content
```

## Acceptance criteria

- [ ] Manual assessment entry works end-to-end (form → API → database → displayed)
- [ ] Manual resource upload works end-to-end
- [ ] Canvas quizzes are fetched and stored as assessments
- [ ] Canvas modules and module items are fetched and stored as resources
- [ ] Canvas pages are fetched with HTML body content
- [ ] Canvas file metadata is stored (no content download)
- [ ] Calendar events that match test/quiz patterns are stored as assessments
- [ ] Resource chunking produces correctly-sized chunks with proper indexing
- [ ] All new fetcher functions have mocked tests
- [ ] Existing scraper (courses, assignments, enrollments) still works
- [ ] `fetch_all()` orchestrates new endpoints alongside existing ones
- [ ] Quality gates pass

## Risks & open questions

- **Canvas API permissions** — The existing token may not have access to all endpoints (quizzes, files, modules). Need to verify scopes.
- **Quiz vs assignment overlap** — Some quizzes are also assignments in Canvas. Need deduplication logic so assessments aren't double-counted.
- **Calendar event classification** — Heuristic matching ("test", "exam", "quiz" in title) will have false positives and miss events with non-standard names. Manual entry remains the fallback.
- **Rate limiting** — Adding 5 new API endpoints per course increases request volume. The existing 0.25s delay and semaphore may need tuning.
- **HTML content size** — Canvas page bodies can be large. Chunking needs to handle messy HTML gracefully (strip tags, handle tables, etc.).

## Dependencies

- Phase 1 schema (assessments, resources, resource_chunks tables must exist)
- Phase 1 backend API (endpoints to POST manual entries)
