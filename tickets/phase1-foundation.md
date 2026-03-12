# Phase 1: Foundation — Schema, Backend API, Frontend Scaffold

## Context

The current codebase is a solid grade/deadline data spine: 5 tables (courses, assignments, submissions, enrollments, grade_snapshots), a Canvas scraper, and a static `web/index.html` dashboard with privilege logic. But it has no concept of tests, study resources, student self-reports, study plans, concept mastery, or practice results. Before adding any study planning or AI features, the data model and architecture need to support them.

The dashboard also hardcodes the current term, privilege thresholds, and assumes a single student — all of which become blockers as the app grows.

## Goals

- Extend the schema with tables needed for study planning, mastery tracking, and practice
- Add a FastAPI backend so server-side logic can live somewhere (planning, AI, audit)
- Scaffold the frontend for multiple pages/views beyond the single-file dashboard
- Extract hardcoded config into a manageable layer

## What exists today

| Layer | Current state |
|-------|---------------|
| Schema | `courses`, `assignments`, `submissions`, `enrollments`, `grade_snapshots` |
| Backend | None — frontend queries Supabase directly via anon key |
| Frontend | Single `web/index.html` with Alpine.js + Tailwind, Supabase JS client |
| Config | Hardcoded term `'2025-2026 Second Semester'`, privilege thresholds `8/10/11/12`, single student |

## New schema entities

### `assessments`
Tests, quizzes, essays, labs, projects — anything with a scheduled date that impacts grades.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| course_id | int FK → courses | |
| name | text | |
| assessment_type | text | test, quiz, essay, lab, project |
| scheduled_date | timestamp | When it happens |
| weight | float nullable | % of course grade, if known |
| unit_or_topic | text nullable | Chapter/unit label |
| description | text nullable | |
| canvas_assignment_id | int nullable FK → assignments | Link to Canvas if applicable |
| created_at | timestamp | |
| updated_at | timestamp | |

### `resources`
Textbook chapters, Canvas pages, files, links, notes, videos — anything the student can study from.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| course_id | int FK → courses | |
| title | text | |
| resource_type | text | textbook_chapter, canvas_page, file, link, notes, video |
| source_url | text nullable | |
| canvas_module_id | int nullable | |
| sort_order | int default 0 | |
| created_at | timestamp | |
| updated_at | timestamp | |

### `resource_chunks`
Chunked content for retrieval/citation later.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| resource_id | int FK → resources | |
| chunk_index | int | Position within resource |
| content_text | text | |
| embedding_vector | vector nullable | For future embedding search |
| token_count | int | |
| created_at | timestamp | |

### `student_signals`
Daily check-in data — how the student is feeling, what time they have.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| recorded_at | timestamp | |
| available_minutes | int | Study time tonight |
| confidence_level | int | 1-5 |
| energy_level | int | 1-5 |
| stress_level | int | 1-5 |
| blockers | text nullable | Free text |
| preferences | jsonb nullable | Subject preferences, etc. |
| notes | text nullable | |

### `study_plans` + `study_blocks`
The daily plan and its constituent blocks.

**study_plans:**

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| plan_date | date unique | One plan per day |
| total_minutes | int | |
| status | text | draft, active, completed, skipped |
| created_at | timestamp | |
| updated_at | timestamp | |

**study_blocks:**

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| plan_id | int FK → study_plans | |
| block_type | text | plan, urgent_deliverable, retrieval, worked_example, deep_explanation, reflection |
| title | text | |
| description | text nullable | |
| target_minutes | int | |
| actual_minutes | int nullable | |
| course_id | int nullable FK → courses | |
| assessment_id | int nullable FK → assessments | |
| sort_order | int | |
| status | text | pending, in_progress, completed, skipped |
| started_at | timestamp nullable | |
| completed_at | timestamp nullable | |

### `mastery_states`
Per-concept mastery tracking — the core learning model.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| course_id | int FK → courses | |
| concept | text | Topic/concept label |
| mastery_level | float | 0.0 - 1.0 |
| confidence_self_report | float nullable | 0.0 - 1.0 |
| last_retrieval_at | timestamp nullable | |
| next_review_at | timestamp nullable | Spaced repetition scheduling |
| retrieval_count | int default 0 | |
| success_rate | float nullable | Rolling accuracy |
| updated_at | timestamp | |

### `practice_results`
Individual practice item outcomes — quizzes, flashcards, explanations.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| study_block_id | int nullable FK → study_blocks | |
| course_id | int FK → courses | |
| concept | text nullable | |
| practice_type | text | quiz, flashcard, worked_example, reflection, explanation |
| question_text | text | |
| student_answer | text nullable | |
| correct_answer | text nullable | |
| is_correct | bool nullable | |
| confidence_before | float nullable | 1-5, asked before answering |
| time_spent_seconds | int nullable | |
| created_at | timestamp | |

## Backend API scaffold

Create `mitty/api/` with:

- **App factory** — FastAPI app with versioned routes
- **Auth middleware** — Verify Supabase JWT tokens (the frontend already uses Supabase Auth)
- **CORS config** — Allow local dev + production origins
- **Health endpoint** — `GET /health`
- **Supabase client DI** — Async client injected into route handlers
- **CRUD endpoints** for new tables — create/read/update for assessments, student_signals, study_plans, study_blocks, mastery_states, practice_results

The existing direct-Supabase frontend queries keep working during transition. The backend takes over progressively for anything that needs server-side logic.

## Frontend scaffold

Move from the single `web/index.html` monolith toward a multi-page structure:

- Keep Alpine.js (or evaluate a lightweight alternative) but add page routing
- Pages needed: Dashboard (existing), Class Detail (existing), Study Plan (new), Check-in (new), Practice (new)
- Extract hardcoded config:
  - Current term → fetch from config endpoint or table
  - Privilege thresholds → config table
  - Per-student settings → config table
  - Available study window → student_signals

## Config extraction

Move these out of hardcoded frontend logic:

| Value | Current location | Target |
|-------|-----------------|--------|
| `'2025-2026 Second Semester'` | `web/index.html` filter | Config table / endpoint |
| Privilege thresholds (8/10/11/12) | `PRIVILEGE_LEVELS` array in JS | Config table |
| Privilege names | Hardcoded in JS | Config table |
| Single-student assumption | Implicit everywhere | User/student model |

## Acceptance criteria

- [ ] All 7 new tables exist in Supabase with Alembic migrations
- [ ] Pydantic models for all new entities in `mitty/models.py`
- [ ] SQLAlchemy table definitions in `mitty/db.py`
- [ ] FastAPI app runs at `mitty/api/`, Supabase JWT auth works
- [ ] CRUD endpoints for new tables return proper responses
- [ ] Frontend has routing between at least 3 views (dashboard, class detail, study plan stub)
- [ ] Hardcoded term and privilege config moved to a config source
- [ ] Existing dashboard + homework viewer still work
- [ ] Tests for new models, endpoints, and storage functions
- [ ] Quality gates pass: `ruff format`, `ruff check`, `pytest`

## Risks & open questions

- **Schema may evolve** — these table designs are a starting point. Expect to iterate as the planner and practice systems get built.
- **Backend framework choice** — FastAPI is proposed. If there's a strong preference for something else (Litestar, Django, etc.), decide now.
- **Frontend framework** — Staying with Alpine.js keeps it simple but may feel constrained for the practice/chat UIs in later phases. Could consider HTMX or a lightweight build step.
- **Supabase RLS** — New tables need read/write policies. Design these with role-based access in mind (Phase 7).

## Dependencies

- None — this is the foundation phase.
- All subsequent phases depend on this.
