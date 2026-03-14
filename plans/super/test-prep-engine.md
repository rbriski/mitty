# Super Plan: Test Prep Engine

## Meta

| Field | Value |
|-------|-------|
| **Ticket** | `tickets/test-prep-engine.md` |
| **Branch** | `feature/test-prep-engine` |
| **Phase** | `detailing` |
| **Sessions** | 2 |
| **Last session** | 2026-03-14 |

---

## Discovery

### Ticket Summary

Build a two-part system for Pre-Calculus Chapter 4 test preparation:

1. **Homework Vision Analysis Pipeline** — Fetch graded homework PDFs from Canvas, use Claude vision to extract per-problem performance data (correct/incorrect, error types, concepts), build a real mastery profile.

2. **Adaptive Test Prep Session** — A 5-phase study session (diagnostic → focused practice → error analysis → mixed test → calibration) grounded in learning science research, with adaptive difficulty, progressive hints, and real-time mastery tracking.

**Urgency:** Chapter 4 Test is March 16 (2 days). Student has B (86.27%). 6 graded homeworks + 1 quiz + 2 review guides available on Canvas but untouched.

**Target:** Pre-Calculus H S2 - DePalma, course_id 4127. Chapter 4: Polynomial & Rational Functions (sections 4.1, 4.3-4.7).

### Key Codebase Findings

**Reusable as-is:**
- `CanvasClient` — async HTTP with retry, pagination, rate limiting
- `fetch_assignments()` — already includes `include[]=submission` for scores
- `download_file_content()` — SSRF-safe file download from Canvas URLs
- `extract_text_from_pdf()` — pymupdf text extraction (pymupdf also has `get_pixmap()`)
- `AIClient.call_structured()` — structured output via tool-use, audit logging, rate limiting
- `evaluate_answer()` — exact-match + LLM hybrid evaluation
- `update_mastery()` — weighted moving average mastery updater
- `calculate_next_review()` — SM-2 spaced repetition scheduler
- Frontend patterns — Alpine.js + HTMX + Supabase auth + Tailwind

**Needs extension:**
- `AIClient` — add vision support (base64 image content blocks)
- `fetcher.py` — add submission attachment fetching (`submissions/self?include[]=attachments`)
- `extract.py` — add `pdf_pages_to_images()` via `page.get_pixmap()`

**New development:**
- `mitty/prep/` — homework analyzer, mastery profiler, problem generator, session engine
- `mitty/api/routers/test_prep.py` — API endpoints
- `mitty/api/templates/test_prep.html` — session UI with KaTeX
- 3 new database tables

**No new dependencies needed** — pymupdf and anthropic SDK already support vision.

### Convention Constraints (from .claude/rules/)

- All async, Python 3.12+, type hints everywhere
- Quality gates: `uv run ruff format --check . && uv run ruff check . && uv run pytest`
- `wrap_user_input()` for all student/user input to LLM
- `.maybe_single()` not `.single()` for Supabase queries
- `.replace()` not `.format()` for prompt templates (math notation has `{}`)
- Mock at API boundaries in tests, never hit real endpoints
- Pydantic v2 with `model_dump(mode="json")` for Supabase
- Graceful degradation when `ai_client is None`
- Small focused modules, < 30 line functions
- `from __future__ import annotations` + `TYPE_CHECKING` guard

### Scoping Decisions (Phase 1)

**DEC-001: Math answer evaluation** — LLM evaluates every answer (option A). Cost is <$1/session, UX is better with immediate rich feedback, math equivalence is too hard to do programmatically. Reuse existing evaluator infrastructure with audit logging.

**DEC-002: Homework analysis trigger** — SSE streaming with manual "Analyze My Homework" button (option A). No task queue needed. Student sees pages processing one by one, then proceeds to session. One-time action per assignment set.

**DEC-003: Practice/mastery system relationship** — Separate generator in `mitty/prep/`, reuse `evaluator.py` (extend for math rubrics) and `mastery/updater.py` (option C). Sync results back to `mastery_states` so existing dashboard and planner see the data.

**DEC-004: Session resume** — Phase-level resume (option B). Store phase completion + running mastery in DB, re-generate problems on resume. Each phase is short enough that restarting is acceptable. Simple state management.

**DEC-005: Scope** — Full ticket, all 12 work items, all 5 phases, KaTeX, heat map, everything (option A).

---

## Architecture Review

| Area | Rating | Key Findings |
|------|--------|-------------|
| **Security** | pass | Auth, SSRF, prompt injection covered by existing patterns. XSS/KaTeX: use `x-text` not `x-html`, add CSP. |
| **Performance** | concern | Vision API sequential = 70-140s. Parallelize with Semaphore(3). Answer eval pipelining saves 30-60s/session. |
| **Data Model** | blocker→resolved | Missing indexes (7 added). `user_id` added to `test_prep_results`. CHECK constraints added. `ON DELETE CASCADE` on assignment FK. |
| **API Design** | concern→resolved | UUID for session IDs. SSE with safeguards. Server-authoritative state. Pydantic schemas required. |
| **Testing** | pass | Mature infra. Need 4 new patterns: SSE, vision mocks, state machine, math equivalence. All low-risk. |
| **Observability** | concern→resolved | Add vision pricing to PRICING dict. Per-page pipeline logging. Session phase transition logging. |

---

## Refinement Log

### Decisions

- DEC-001: LLM evaluates every math answer (cost <$1/session)
- DEC-002: SSE streaming with manual trigger for homework analysis
- DEC-003: Separate generator, reuse evaluator + mastery updater
- DEC-004: Phase-level session resume
- DEC-005: Full scope — all 12 work items
- DEC-006: UUID for `test_prep_sessions.id` (matches `study_plans` pattern)
- DEC-007: Vision API parallelization — `asyncio.Semaphore(3)`, 3 concurrent calls
- DEC-008: Add `user_id` to `test_prep_results` (denormalized, matches `practice_results`)
- DEC-009: All 9 CHECK constraints in migration
- DEC-010: SSE with 30-min timeout + 1 concurrent stream per user

---

## Detailed Breakdown

### US-001: Database schema & migration

**Description:** Create 3 new tables (`homework_analyses`, `test_prep_sessions`, `test_prep_results`) with all indexes, CHECK constraints, RLS policies, and FK relationships. Add SQLAlchemy table definitions to `db.py`.

**Traces to:** DEC-006 (UUID sessions), DEC-008 (user_id in results), DEC-009 (CHECK constraints)

**Acceptance criteria:**
- Migration creates all 3 tables with correct types, FKs, cascades
- 7 indexes created (see architecture review)
- 9 CHECK constraints applied
- RLS policies: users can only read/write own data
- SQLAlchemy definitions in `db.py` match migration
- `uv run ruff format --check . && uv run ruff check . && uv run pytest` passes

**Done when:** `supabase migration apply` succeeds, RLS verified via test queries

**Files:**
- `supabase/migrations/YYYYMMDD_test_prep_tables.sql` (new)
- `mitty/db.py` (add 3 table definitions)

**Depends on:** none

---

### US-002: Pydantic schemas & API models

**Description:** Define all request/response Pydantic models for the test prep API in `schemas.py`. Includes homework analysis, session CRUD, answer evaluation, mastery profile, and SSE event types.

**Traces to:** DEC-006 (UUID session_id type), DEC-008 (user_id in results)

**Acceptance criteria:**
- All request/response models defined with proper types and validation
- `model_dump(mode="json")` works for Supabase insertion
- Models documented with field descriptions
- Quality gates pass

**Done when:** All models importable and validated in tests

**Files:**
- `mitty/api/schemas.py` (extend with ~10 new models)

**Depends on:** US-001

---

### US-003: Canvas submission fetcher

**Description:** Add `fetch_submission_attachments()` to `fetcher.py` that calls `GET /courses/:id/assignments/:id/submissions/self?include[]=attachments` and returns attachment metadata (URLs, filenames, content types).

**Traces to:** ticket work item 1

**Acceptance criteria:**
- Fetches submission attachments for given course_id + assignment_ids
- Uses existing `CanvasClient` with retry/pagination
- Returns list of attachment dicts with url, filename, content_type
- Handles missing submissions gracefully (empty list, not error)
- Quality gates pass

**Done when:** Tests verify correct Canvas API call structure and response parsing

**Files:**
- `mitty/canvas/fetcher.py` (add function)
- `tests/test_canvas/test_fetcher.py` (add tests)

**Depends on:** none

**TDD:**
- `test_fetch_submission_attachments_success` — mock Canvas API, verify correct URL and parsed output
- `test_fetch_submission_attachments_no_submission` — returns empty list
- `test_fetch_submission_attachments_no_attachments` — submission exists but no files

---

### US-004: PDF-to-images extraction

**Description:** Add `pdf_pages_to_images()` to `extract.py` using pymupdf `page.get_pixmap(dpi=200)`. Returns list of PNG bytes per page. Cap at `max_pages=10`.

**Traces to:** ticket work item 2

**Acceptance criteria:**
- Converts PDF bytes to list of PNG image bytes
- 200 DPI default, configurable
- Caps at max_pages (default 10)
- Handles corrupted PDFs gracefully (returns partial results + logs warning)
- Quality gates pass

**Done when:** Tests verify correct image output for sample PDF fixture

**Files:**
- `mitty/canvas/extract.py` (add function)
- `tests/test_canvas/test_extract.py` (add tests)

**Depends on:** none

**TDD:**
- `test_pdf_pages_to_images_single_page` — 1-page PDF returns 1 PNG
- `test_pdf_pages_to_images_max_pages` — 15-page PDF capped at 10
- `test_pdf_pages_to_images_corrupted` — invalid bytes raises/returns empty

---

### US-005: AI client vision support

**Description:** Add `call_vision()` method to `AIClient` that accepts a list of base64-encoded images alongside text prompts. Uses existing `call_structured()` infrastructure (audit logging, rate limiting, cost tracking). Add vision model pricing to PRICING dict.

**Traces to:** DEC-007 (parallelization), ticket work item 3

**Acceptance criteria:**
- `call_vision(images, system, user_prompt, response_model)` works with base64 PNG images
- Constructs proper Anthropic API message with image content blocks
- Audit logging captures vision calls with correct `call_type`
- Vision pricing added to PRICING dict for accurate cost tracking
- Rate limiter enforced per call
- Quality gates pass

**Done when:** Tests verify correct API message construction, audit row, and cost calculation

**Files:**
- `mitty/ai/client.py` (add method + pricing)
- `tests/test_ai/test_client.py` (add vision tests)

**Depends on:** none

**TDD:**
- `test_call_vision_constructs_image_blocks` — verify message structure
- `test_call_vision_audit_logging` — verify audit row with vision call_type
- `test_call_vision_cost_calculation` — verify vision pricing used, not text pricing
- `test_call_vision_rate_limited` — verify rate limiter checked

---

### US-006: Homework analyzer

**Description:** Create `mitty/prep/analyzer.py` with `analyze_homework_set()` that orchestrates: fetch attachments → download PDFs → convert to images → parallel vision analysis (Semaphore(3)) → store results in `homework_analyses` table. Includes cache check (skip already-analyzed pages).

**Traces to:** DEC-002 (SSE trigger), DEC-007 (parallel vision), ticket work items 4-5

**Acceptance criteria:**
- Fetches and analyzes all submission attachments for given assignment_ids
- Parallelizes vision calls with `asyncio.Semaphore(3)` (DEC-007)
- Caches results: skips pages already in `homework_analyses` table
- Extracts per-problem: correct/incorrect, error type, concept, difficulty
- Uses `wrap_user_input()` for all extracted student content
- Stores results via Supabase upsert on `(user_id, assignment_id, page_number)`
- Graceful partial failure: if page N fails, continues with page N+1
- Quality gates pass

**Done when:** Tests verify full pipeline with mocked Canvas + Vision APIs

**Files:**
- `mitty/prep/analyzer.py` (new)
- `mitty/prep/__init__.py` (new)
- `mitty/ai/prompts.py` (add homework_analyzer role)
- `tests/test_prep/test_analyzer.py` (new)
- `tests/test_prep/__init__.py` (new)
- `tests/test_prep/conftest.py` (new — PDF fixtures)

**Depends on:** US-003, US-004, US-005

**TDD:**
- `test_analyze_homework_set_full_pipeline` — mock all externals, verify DB inserts
- `test_analyze_homework_set_cache_hit` — pre-existing analysis skipped
- `test_analyze_homework_set_partial_failure` — page 2 fails, pages 1+3 stored
- `test_analyze_homework_set_parallel` — verify semaphore limits concurrency

---

### US-007: Mastery profiler

**Description:** Create `mitty/prep/profiler.py` with `build_mastery_profile()` that aggregates `homework_analyses` rows into a per-concept mastery profile. Maps concepts to sections (4.1, 4.3-4.7), computes accuracy and weakness ranking. Syncs to `mastery_states` table.

**Traces to:** DEC-003 (sync to mastery_states), ticket work item 6

**Acceptance criteria:**
- Reads all `homework_analyses` for user + course
- Aggregates by concept: accuracy, total attempts, error patterns
- Ranks concepts by weakness (lowest accuracy first)
- Syncs results to `mastery_states` using existing `update_mastery()` function
- Quality gates pass

**Done when:** Tests verify correct aggregation and mastery sync

**Files:**
- `mitty/prep/profiler.py` (new)
- `tests/test_prep/test_profiler.py` (new)

**Depends on:** US-001, US-006

**TDD:**
- `test_build_mastery_profile_basic` — 3 concepts, verify ranking
- `test_build_mastery_profile_syncs_mastery` — verify `update_mastery()` called per concept
- `test_build_mastery_profile_no_data` — returns empty profile gracefully

---

### US-008: Problem generator

**Description:** Create `mitty/prep/generator.py` with `generate_problem()` that uses Claude to generate math problems at a target difficulty for a given concept. Supports 6 problem types (multiple choice, free response, worked example, error analysis, mixed, calibration). Uses `.replace()` for prompt templates.

**Traces to:** DEC-001 (LLM for all problems), ticket work item 7

**Acceptance criteria:**
- Generates problems for any Chapter 4 concept at target difficulty 0.0-1.0
- Supports all 6 problem types
- Returns structured `GeneratedProblem` with problem_text, solution, hints, LaTeX
- Uses `wrap_user_input()` for any student context in prompts
- Graceful degradation: returns cached/fallback problem if AI unavailable
- Quality gates pass

**Done when:** Tests verify structured output for each problem type

**Files:**
- `mitty/prep/generator.py` (new)
- `mitty/ai/prompts.py` (add problem_generator role)
- `tests/test_prep/test_generator.py` (new)

**Depends on:** US-005

**TDD:**
- `test_generate_problem_multiple_choice` — verify 4 options returned
- `test_generate_problem_free_response` — verify solution + hints
- `test_generate_problem_worked_example` — verify step-by-step solution
- `test_generate_problem_difficulty_scaling` — harder difficulty = harder content
- `test_generate_problem_ai_unavailable` — graceful degradation

---

### US-009: Session engine

**Description:** Create `mitty/prep/session.py` with `SessionEngine` class that manages the 5-phase adaptive session: diagnostic → focused practice → error analysis → mixed test → calibration. Handles phase transitions, difficulty adaptation (±0.15 on 2 correct/wrong), running mastery, and state persistence.

**Traces to:** DEC-004 (phase-level resume), DEC-006 (UUID sessions), ticket work item 8

**Acceptance criteria:**
- 5-phase flow with correct transition rules
- Diagnostic: 1-2 problems per concept, builds initial accuracy map
- Focused practice: targets weakest concepts, adapts difficulty
- Error analysis: worked examples for misconceptions
- Mixed test: interleaved problems across all concepts
- Calibration: confidence vs. accuracy comparison
- Difficulty adapts: 2 correct → +0.15, 2 wrong → -0.15, clamped [0.1, 0.95]
- State serializable to JSON, persistable to `test_prep_sessions.state_json`
- Phase-level resume: load state from DB, re-generate current phase problems
- Quality gates pass

**Done when:** Parametrized tests verify all phase transitions and difficulty adaptation

**Files:**
- `mitty/prep/session.py` (new)
- `tests/test_prep/test_session.py` (new)

**Depends on:** US-007, US-008

**TDD:**
- `test_phase_transitions_valid` — parametrized: all valid transitions succeed
- `test_phase_transitions_invalid` — parametrized: skip/backward transitions rejected
- `test_difficulty_increase` — 2 consecutive correct → +0.15
- `test_difficulty_decrease` — 2 consecutive wrong → -0.15
- `test_difficulty_clamped` — stays in [0.1, 0.95]
- `test_session_state_serialization` — round-trip to JSON and back
- `test_session_resume` — load from DB state, verify phase restored

---

### US-010: API endpoints + SSE

**Description:** Create `mitty/api/routers/test_prep.py` with all endpoints: POST analyze-homework (SSE), GET mastery-profile, POST/GET sessions, POST answer, POST skip-phase, POST complete. SSE has 30-min timeout + 1 concurrent per user. Server-authoritative state.

**Traces to:** DEC-002 (SSE), DEC-006 (UUID), DEC-010 (SSE safeguards), ticket work item 9

**Acceptance criteria:**
- All endpoints require auth via `get_current_user`
- `POST /test-prep/analyze-homework` returns SSE stream with per-page progress
- SSE enforces 30-min timeout and max 1 concurrent stream per user
- `POST /test-prep/sessions/{id}/answer` validates problem_id matches current problem
- Server is authoritative for session state (client cannot mutate directly)
- All queries scoped to user_id
- Error responses use `{"code": "...", "message": "..."}` format
- Quality gates pass

**Done when:** Integration tests verify all endpoints with mocked dependencies

**Files:**
- `mitty/api/routers/test_prep.py` (new)
- `mitty/api/app.py` (register router)
- `tests/test_api/test_test_prep.py` (new)

**Depends on:** US-001, US-002, US-006, US-009

**TDD:**
- `test_analyze_homework_requires_auth` — 401 without token
- `test_analyze_homework_sse_stream` — verify SSE event format
- `test_create_session` — returns UUID session_id + initial state
- `test_submit_answer_correct` — verify evaluation + next action returned
- `test_submit_answer_stale_problem` — 422 PROBLEM_OUTDATED
- `test_get_session_other_user` — 404 (RLS)
- `test_mastery_profile` — returns per-concept breakdown

---

### US-011: Test prep UI with KaTeX

**Description:** Create `mitty/api/templates/test_prep.html` — single-page session UI with Alpine.js + HTMX + KaTeX. Shows homework analysis progress, mastery heat map, 5-phase session flow, problem display with LaTeX, answer input, feedback, confidence calibration chart.

**Traces to:** DEC-002 (SSE progress), DEC-005 (full scope), ticket work items 10-12

**Acceptance criteria:**
- KaTeX renders all math notation correctly
- SSE connection shows per-page analysis progress
- Mastery heat map shows concept strengths/weaknesses
- Session phases flow naturally with transitions
- Answer input accepts plain text (evaluator handles equivalence)
- Feedback shown immediately after each answer
- Confidence calibration chart at end of session
- CSP header allows KaTeX CDN, uses `x-text` not `x-html` for LLM content
- Responsive on desktop (mobile not required for v1)
- Quality gates pass

**Done when:** Full session flow works end-to-end in browser

**Files:**
- `mitty/api/templates/test_prep.html` (new)
- `mitty/api/templates/base.html` (add KaTeX CDN + CSP)

**Depends on:** US-010

---

### US-012: Quality Gate

**Description:** Run code reviewer 4 times across the full changeset, fixing all real bugs found each pass. Run CodeRabbit review. Run quality gates after all fixes.

**Acceptance criteria:**
- 4 code review passes completed, all real bugs fixed
- CodeRabbit review completed, critical findings addressed
- `uv run ruff format --check . && uv run ruff check . && uv run pytest` passes
- No security vulnerabilities (XSS, injection, SSRF)

**Done when:** All reviews clean, quality gates green

**Depends on:** US-001 through US-011

---

### US-013: Patterns & Memory

**Description:** Update `.claude/rules/`, docs, or memory with new patterns learned during implementation (vision API patterns, SSE streaming, KaTeX integration, session state machine).

**Acceptance criteria:**
- New patterns documented where they'll be found
- Memory updated with test-prep-engine architecture notes

**Done when:** Patterns captured for future reference

**Depends on:** US-012

---

## Beads Manifest

*(Pending — Phase 7)*
