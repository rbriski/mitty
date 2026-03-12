# Super Plan: Phase 3 — Student Check-in + Deterministic Daily Planner

## Meta
- **Source:** tickets/phase3-planner.md
- **Phase:** detailing
- **Created:** 2026-03-11
- **Sessions:** 1

---

## Discovery

### Ticket Summary

Build a deterministic (no AI) daily study planner that:
1. Collects a 60-second student check-in (time, energy, stress, preferences)
2. Scores study opportunities using urgency, mastery gaps, grade risk, assessment proximity
3. Allocates time into evidence-based study blocks (plan, urgent deliverable, retrieval, worked example, deep explanation, reflection)
4. Presents a focused daily plan UI with block execution tracking

### Codebase Findings

**Schema — READY.** All 5 Phase 3 tables already exist in `mitty/db.py`:
- `student_signals` — available_minutes, energy_level (1-5), stress_level (1-5), confidence_level (1-5), blockers, preferences JSON
- `study_plans` — plan_date, total_minutes, status (draft/active/completed/skipped)
- `study_blocks` — block_type (6 types), title, target_minutes, actual_minutes, sort_order, status, started_at/completed_at, course_id FK, assessment_id FK
- `mastery_states` — course_id, concept, mastery_level (0-1), confidence_self_report, next_review_at, retrieval_count, success_rate
- `practice_results` — study_block_id FK, concept, practice_type, is_correct, confidence_before, time_spent_seconds

**CRUD APIs — READY.** All routers exist with full CRUD:
- `study_plans.router` — POST/GET/GET/{id}/PUT/{id}/DELETE/{id}
- `study_blocks.router` — POST/GET/GET/{id}/PUT/{id}/DELETE/{id} (with plan ownership verification)
- `student_signals.router` — full CRUD
- `mastery_states.router` — full CRUD + course filter
- `practice_results.router` — full CRUD

**Templates — PARTIAL.** `study_plan.html` exists with Alpine.js `studyPlanApp()` component but is a basic scaffold — needs the full plan UI from the ticket.

**Planner logic — DOES NOT EXIST.** No `mitty/planner/` directory. No scoring, allocation, or generation code. This is the core deliverable.

**Data available to the planner:**
- `assignments` — due_at, points_possible + `submissions` — workflow_state, late, missing
- `assessments` — scheduled_date, assessment_type, weight, unit_or_topic, course_id
- `enrollments` — current_score, current_grade
- `grade_snapshots` — time-series for volatility calculation
- `mastery_states` — mastery_level, next_review_at, success_rate
- `student_signals` — latest check-in data

**Patterns to follow:**
- Service logic in dedicated modules (e.g., `mitty/canvas/classify.py` for heuristic classification)
- Storage via async Supabase upserts in `mitty/storage.py`
- API routes: thin handlers calling service layer, auth via `get_current_user` dependency
- Templates: Jinja2 + Alpine.js + HTMX + Tailwind CDN + Supabase JS client
- Tests: mock Supabase client chain, `TestClient`, parametrized scenarios

### Proposed Scope

**In scope:**
- `mitty/planner/` module: scoring.py, allocator.py, generator.py
- New API endpoints: `/plans/generate`, `/plans/today` (the existing CRUD endpoints stay)
- Check-in UI (entry point to study session)
- Study plan UI (block list with start/complete/skip tracking)
- Thorough unit tests for scoring and allocation

**Out of scope (confirmed by ticket):**
- AI/LLM-based recommendations (deterministic only)
- Adaptive time estimates from historical data (Phase 8)
- Mastery tracking population (Phase 4)
- Practice question generation

---

## Scoping Questions

### A. Planner data access pattern
The planner needs to read from 6+ tables (assignments, submissions, assessments, enrollments, grade_snapshots, mastery_states, student_signals) to generate a plan. Two options:

- **A1) Supabase queries via service-role client** — The generator runs server-side with the admin client, reads all needed data, computes the plan, writes results. Simple, but bypasses RLS.
- **A2) Supabase queries via user client** — The generator uses the authenticated user's client (RLS-enforced). More secure but the current data (courses, assignments, etc.) isn't user-scoped with RLS since it's a single-student app.

Which approach? (Given this is a single-student app, A1 seems pragmatic.)

### B. Check-in UI placement
- **B1) Dedicated check-in page** — Separate route `/checkin` that redirects to the plan after submission
- **B2) Modal/overlay on the study plan page** — Check-in appears as a modal when no signal exists for today, then reveals the plan
- **B3) Inline on the study plan page** — Check-in form at the top of the plan page, plan generates below after submission

### C. Plan regeneration behavior
The ticket says "allow re-generating today's plan." When the student regenerates:
- **C1) Replace draft blocks only** — If any block is in_progress or completed, warn and don't replace those
- **C2) Always replace everything** — Simple, but loses progress
- **C3) Replace unstarted blocks only** — Keep completed/in-progress blocks, regenerate the rest with remaining time

### D. Cold start behavior
With no mastery data and possibly no assessments entered:
- **D1) Minimal plan from assignments + grades only** — Skip mastery-based blocks, focus on homework urgency and grade risk. Show a banner: "Add your upcoming tests for better plans."
- **D2) Require at least one assessment** — Gate the planner behind having entered at least one assessment
- **D3) Generate a generic "study skills" plan** — Default blocks for organization/review when no data exists

### E. Scoring weight configurability
The ticket says "all weights configurable." Where should weights live?
- **E1) Python constants in scoring.py** — Simple, change requires code deploy
- **E2) Config via Settings/env vars** — Configurable per environment
- **E3) Database (app_config table)** — Configurable at runtime via admin UI

---

### Scoping Decisions

- **A. Data access** → A1 (service-role client). Single-student app, data isn't user-scoped.
- **B. Check-in UI** → B3 (inline on plan page). Simplest, best on mobile, progressive disclosure.
- **C. Regeneration** → C1 (replace draft, warn on started). Clean replace for common case.
- **D. Cold start** → D1 (minimal plan + banner). Always produce value.
- **E. Weights** → E1 (Python constants). Co-located, testable, easy to promote later.
- **F. Assessment discovery** → Classify assignments as assessments via heuristic (name pattern + points). 40+ assessments already exist in assignments table. Add as Story 0 in Phase 3. Enables full 8-factor scoring on day 1.

---

## Architecture Review

| Area | Rating | Key Finding |
|------|--------|-------------|
| Security | **PASS** | Auth dependency (`get_current_user`) is mandatory on all existing routes. New endpoints follow same pattern. Jinja2 auto-escaping + `x-text` prevent XSS. No new secrets needed. |
| Performance | **PASS** | 6-10 Supabase reads total, each <50 rows. Scoring is O(n) for n≈50. Single student, 1-2 requests/day. ~2KB response. No concerns. |
| Data Model | **BLOCKER** | `canvas_assignment_id` on `assessments` table has no unique constraint → upsert for assignment classifier will fail or create duplicates. Must add unique constraint via migration before implementation. |
| Data Model | **CONCERN** | Plan status lifecycle (draft→active→completed→skipped) enforced at app level only, no DB CHECK constraint. Acceptable for MVP. |
| API Design | **PASS** | Add `/generate` and `/today` to existing `study_plans` router. Return full plan + nested blocks. 404 when no plan exists for today. |
| API Design | **CONCERN** | Must define explicit error codes: `NO_SIGNAL_TODAY` (400), `PLAN_EXISTS` (409), `INVALID_DATE` (400), `GENERATION_FAILED` (500). |
| Testing | **PASS** | Scoring + allocator + classifier are pure functions → highly testable with parametrize. Generator needs mocked Supabase (existing pattern in test_study_plans.py). |
| Observability | **PASS** | Log plan summary at INFO, scoring reasons at DEBUG. Add stopwatch timing. Store human-readable reasons in DB, not logs. |
| Observability | **CONCERN** | No error classification (transient vs permanent). Generator should isolate per-course failures rather than aborting entirely. |

### Blocker Resolution

**`canvas_assignment_id` unique constraint** — The `assessments` table has `unique=True` on `canvas_quiz_id` and `canvas_event_id` but NOT on `canvas_assignment_id`. The assignment classifier needs to upsert on this column. Resolution: add a Supabase migration to add `UNIQUE` constraint on `canvas_assignment_id` as Story 0 prerequisite.

## Refinement Log

### Decisions

| ID | Name | Decision | Rationale |
|----|------|----------|-----------|
| DEC-001 | Data access | Service-role client for planner reads | Single-student app, data not user-scoped |
| DEC-002 | Check-in UI | Inline on plan page (B3) | Simplest, best mobile UX, progressive disclosure |
| DEC-003 | Regeneration | Replace draft plans; 409 on active/completed | Common case is clean replace; protect in-progress work |
| DEC-004 | Cold start | Graceful degradation with banner | Always produce value from available data |
| DEC-005 | Scoring weights | Python constants in scoring.py | Co-located, testable, easy to promote later |
| DEC-006 | Assessment discovery | Classify assignments via name heuristic | 40+ assessments hiding in assignments table; enables full scoring |
| DEC-007 | Status lifecycle | App-level validation, no DB constraint | Add transition validator in generator; revisit for multi-user |
| DEC-008 | API error codes | 400 NO_SIGNAL_TODAY, 409 PLAN_EXISTS | Replace drafts silently; block regeneration of active/completed plans |
| DEC-009 | Error isolation | Per-course graceful degradation | Non-critical reads (snapshots, mastery) degrade; critical reads (assignments, enrollments) fail generation |
| DEC-010 | Classifier signals | Name pattern only with exclusion patterns | "test/quiz/exam/final/assessment/midterm" match; exclude "review/prep" false positives; points vary too much by course |
| DEC-011 | Signal freshness | Last 24 hours | Handles midnight edge case; stale signals (>24h) prompt re-check-in |
| DEC-012 | Generation trigger | Auto-generate after check-in | One action, minimum friction; "under 60 seconds" goal |
| DEC-013 | Block content strategy | Assessment-driven study blocks + grade-risk fallback | Upcoming assessments → "Study for Ch.4 Test"; low-grade courses → "Review AP US History"; never skip Plan/Reflection/protected study time |

### Concern Resolutions

1. **Plan status lifecycle (CONCERN)** → DEC-007: App-level validation. Generator enforces valid transitions. Acceptable for single-student MVP.
2. **API error codes (CONCERN)** → DEC-008: Four explicit error codes. Draft plans replaced silently; active/completed plans return 409.
3. **Error isolation (CONCERN)** → DEC-009: Critical reads fail generation; non-critical reads degrade gracefully with warning logs.
4. **Blocker: canvas_assignment_id unique constraint** → Resolved as Story 0 migration.

## Detailed Breakdown

### US-001: Migration — Add unique constraint on `canvas_assignment_id`

**Description:** The `assessments` table has unique constraints on `canvas_quiz_id` and `canvas_event_id` but not `canvas_assignment_id`. The assignment classifier (US-003) needs to upsert on this column. Add the constraint via Supabase migration.

**Traces to:** DEC-006 (classify assignments as assessments), Architecture Review blocker

**Acceptance Criteria:**
- `canvas_assignment_id` column on `assessments` has a UNIQUE constraint
- Existing data (7 quiz rows with null `canvas_assignment_id`) is unaffected
- `uv run pytest` passes
- Migration is applied to Supabase

**Done when:** `ALTER TABLE assessments ADD CONSTRAINT ... UNIQUE (canvas_assignment_id)` succeeds and is verified.

**Files:**
- `mitty/db.py` — Update SQLAlchemy column definition to add `unique=True` on `canvas_assignment_id`
- Supabase migration via `mcp__supabase__apply_migration`

**Depends on:** none

---

### US-002: Assignment classifier — heuristic detection

**Description:** Create a pure function that determines whether a Canvas assignment is an assessment (test/quiz/exam/midterm/final) based on its name. Uses regex pattern matching with exclusion patterns for false positives like "Quiz Review" or "Test Prep." Returns the assessment type (test, quiz, exam, or None).

**Traces to:** DEC-006, DEC-010 (name pattern only, exclude review/prep)

**Acceptance Criteria:**
- `is_assessment_assignment(name: str) -> str | None` returns assessment type or None
- Matches: test, quiz, exam, midterm, final, assessment (case-insensitive)
- Excludes: names containing "review", "prep" alongside keywords
- Parametrized tests with real assignment names from the database (both positive and negative cases)
- `uv run ruff check .` and `uv run pytest` pass

**Done when:** Classifier correctly identifies 40+ known assessments from the real data and rejects homework/review items.

**Files:**
- `mitty/planner/__init__.py` — Create package
- `mitty/planner/classify.py` — `is_assessment_assignment()` function
- `tests/test_planner/__init__.py` — Create test package
- `tests/test_planner/test_classify.py` — Parametrized tests

**Depends on:** none

**TDD:**
1. Write parametrized test cases with real names: "Chapter 4 Test" → "test", "Quiz - Unit 7 Acid, Base, Equlibria" → "quiz", "Spring Final Exam" → "exam", "Homework 14.3" → None, "Quiz Review - Unit 6" → None, "Unit 5 Test Review" → None
2. Implement classifier to pass all cases
3. Verify edge cases: empty string, no keywords, mixed case

---

### US-003: Classifier ingestion — upsert assignments as assessments

**Description:** Add a storage function that scans assignments, runs the classifier, and upserts matching items into the `assessments` table with `source='canvas_assignment'`. Integrate into the existing ingestion pipeline so classified assessments are refreshed on every scrape.

**Traces to:** DEC-006

**Acceptance Criteria:**
- `upsert_assignments_as_assessments()` in `storage.py` reads assignments, classifies them, upserts into assessments
- Upserts on `canvas_assignment_id` conflict (idempotent)
- Sets: `assessment_type` from classifier, `source='canvas_assignment'`, `scheduled_date` from `due_at`, `name` from assignment name, `course_id` from assignment
- Does not overwrite manually-created assessments or quiz/calendar assessments
- Integrated into `store_all()` or equivalent ingestion orchestrator
- Tests with mocked Supabase client
- Quality gates pass

**Done when:** Running the ingestion pipeline populates ~40 assessment rows from classified assignments.

**Files:**
- `mitty/storage.py` — Add `upsert_assignments_as_assessments()` function
- `mitty/__main__.py` — Call new function in ingestion flow (if not already via `store_all()`)
- `tests/test_storage.py` — Tests for the new upsert function

**Depends on:** US-001 (unique constraint), US-002 (classifier function)

---

### US-004: Priority scoring engine

**Description:** Create a deterministic scoring function that takes a list of study opportunities (assignments, assessments, courses with grades) and returns a ranked list of `(opportunity, score, reason)` tuples. Each opportunity is scored across 6 weighted factors: homework urgency, assessment proximity, late/missing recovery, grade risk, grade volatility, and student preference.

**Traces to:** DEC-005 (Python constants), DEC-009 (graceful degradation), DEC-013 (assessment-driven + grade-risk fallback)

**Acceptance Criteria:**
- `score_opportunities(opportunities, signal, now) -> list[ScoredOpportunity]` is a pure function
- 6 weighted factors with module-level constants (WEIGHT_URGENCY, WEIGHT_ASSESSMENT_PROXIMITY, etc.)
- Tests in ≤ 3 days dominate the score (DEC from ticket)
- Overdue/missing homework gets high urgency regardless
- Spaced review items surface when nothing is urgent
- Each scored item has a human-readable `reason` string
- Fully deterministic: same inputs → same output
- Parametrized tests covering: exam tomorrow, nothing urgent, mixed priorities, cold start (no assessments), low-grade course boost
- Quality gates pass

**Done when:** Scoring engine correctly ranks diverse scenarios with explainable reasons.

**Files:**
- `mitty/planner/scoring.py` — `score_opportunities()`, weight constants, `ScoredOpportunity` dataclass
- `tests/test_planner/test_scoring.py` — Parametrized scenario tests

**Depends on:** none (pure logic, no DB dependency)

**TDD:**
1. Define `ScoredOpportunity` dataclass (opportunity ref, score, reason)
2. Write test scenarios: exam_tomorrow (score > 0.9), nothing_urgent (even distribution), mixed (exam > homework > review), cold_start (only homework + grades), low_grade_boost (C course boosted)
3. Implement scoring logic factor by factor, validating each
4. Test relative ordering: `score[exam_tomorrow] > score[homework_next_week]`

---

### US-005: Study block time allocator

**Description:** Create a deterministic allocation function that takes ranked opportunities and available minutes, and produces an ordered list of study blocks respecting the ticket's block type rules: always Plan + Reflection, always protected retrieval time, cap at available_minutes.

**Traces to:** DEC-013 (assessment-driven blocks + grade-risk fallback), ticket block type rules

**Acceptance Criteria:**
- `allocate_blocks(scored, available_minutes, energy) -> list[StudyBlock]` is a pure function
- Always includes Plan (first) and Reflection (last)
- Always protects ≥15 min for retrieval/study (even on busy nights)
- Very short nights (<30 min): Plan (5) + Retrieval (15) + Reflection (5)
- Exam-eve: Plan (5) + subject retrieval (60%+) + Reflection (5)
- Total never exceeds `available_minutes`
- Block types: plan, urgent_deliverable, retrieval, worked_example, deep_explanation, reflection
- Assessment-driven blocks: "Study for [Assessment Name]" when assessment upcoming
- Grade-risk blocks: "Review [Course Name]" as fallback when no assessments imminent
- Energy level affects block duration (low energy → shorter blocks)
- Parametrized tests for: 25 min, 60 min, 90 min, 120 min, 180 min sessions; exam-eve; no urgent items
- Quality gates pass

**Done when:** Allocator produces valid plans for all time budgets that respect mandatory block rules.

**Files:**
- `mitty/planner/allocator.py` — `allocate_blocks()`, block duration constants
- `tests/test_planner/test_allocator.py` — Parametrized time budget tests

**Depends on:** US-004 (uses ScoredOpportunity as input type)

**TDD:**
1. Write tests for mandatory invariants: Plan always first, Reflection always last, total ≤ available_minutes
2. Write tests for short night (25 min), normal night (90 min), exam eve
3. Implement allocation logic
4. Verify no block is < 5 min (minimum useful duration)

---

### US-006: Plan generator orchestrator

**Description:** Create the orchestrator that reads inputs from Supabase (latest signal, assignments, submissions, assessments, enrollments, grade_snapshots, mastery_states), calls the scoring engine and allocator, and writes the resulting study_plan + study_blocks to Supabase. Handles error isolation (DEC-009) and signal freshness (DEC-011).

**Traces to:** DEC-001 (service-role client), DEC-009 (error isolation), DEC-011 (24h signal freshness), DEC-003 (replace drafts, 409 on active)

**Acceptance Criteria:**
- `generate_plan(client, user_id, plan_date) -> StudyPlan` orchestrates the full flow
- Reads latest student_signal within 24h; raises if none found
- Critical reads (assignments, enrollments) fail the generation
- Non-critical reads (grade_snapshots, mastery_states) degrade gracefully with warning
- Replaces existing draft plan for the same date; raises if active/completed plan exists
- Writes 1 study_plan row + N study_block rows to Supabase
- Logs plan summary at INFO, scoring details at DEBUG, timing with stopwatch
- Tests with mocked Supabase client (read chains + write verification)
- Quality gates pass

**Done when:** Generator produces correct plans from mocked data and handles all error/edge cases.

**Files:**
- `mitty/planner/generator.py` — `generate_plan()` orchestrator
- `tests/test_planner/test_generator.py` — Orchestration tests with mocked Supabase

**Depends on:** US-004 (scoring), US-005 (allocator)

---

### US-007: API endpoints — `/generate` and `/today`

**Description:** Add two new endpoints to the existing `study_plans` router: POST `/study-plans/generate` triggers plan generation and returns the full plan with nested blocks; GET `/study-plans/today` returns today's plan or 404. Add a `StudyPlanWithBlocksResponse` schema for the nested response.

**Traces to:** DEC-003 (replace drafts/409), DEC-008 (error codes), DEC-012 (auto-generate)

**Acceptance Criteria:**
- `POST /study-plans/generate` requires auth, calls generator, returns 201 with plan + blocks
- `POST /study-plans/generate` returns 400 `NO_SIGNAL_TODAY` if no recent signal
- `POST /study-plans/generate` returns 409 `PLAN_EXISTS` if active/completed plan exists for today
- `POST /study-plans/generate` silently replaces draft plans
- `GET /study-plans/today` requires auth, returns 200 with plan + blocks or 404
- `StudyPlanWithBlocksResponse` schema includes plan fields + `blocks: list[StudyBlockResponse]`
- API tests following existing `test_study_plans.py` patterns
- Quality gates pass

**Done when:** Both endpoints work end-to-end with correct error handling and auth.

**Files:**
- `mitty/api/routers/study_plans.py` — Add `/generate` and `/today` endpoints
- `mitty/api/schemas.py` — Add `StudyPlanWithBlocksResponse`
- `tests/test_api/test_planner.py` — Endpoint tests

**Depends on:** US-006 (generator)

---

### US-008: Study plan UI — check-in + plan display + block tracking

**Description:** Update the study plan template with: (1) inline check-in form that appears when no plan exists for today, (2) full plan display with block cards showing type, title, target time, course context, and assessment alerts, (3) block execution tracking (start/complete/skip buttons with timer), (4) progress bar for overall session.

**Traces to:** DEC-002 (inline check-in), DEC-004 (cold start banner), DEC-012 (auto-generate on submit), ticket UI mockup

**Acceptance Criteria:**
- Check-in form: quick picks for time (30/60/90/120/150/180 min), energy (1-5), stress (1-5), optional focus course, optional blockers
- Submitting check-in auto-calls POST `/student-signals/` then POST `/study-plans/generate`
- Plan display: ordered block cards with type icon, title, target minutes, course name
- Assessment alerts at top ("Pre-Calc Ch.4 Test in 2 days")
- Each block has Start/Done/Skip buttons
- Start sets `started_at` + status `in_progress` via PUT `/study-blocks/{id}`
- Done sets `completed_at` + `actual_minutes` + status `completed`
- Skip sets status `skipped`
- Progress bar: completed blocks / total blocks, actual time / planned time
- Cold start banner when no assessments: "Enter your upcoming tests for better study plans"
- Mobile-friendly layout (Tailwind responsive)
- Quality gates pass

**Done when:** Full check-in → generate → work through blocks flow works on mobile.

**Files:**
- `mitty/api/templates/study_plan.html` — Rewrite with check-in + plan display + block tracking

**Depends on:** US-007 (API endpoints)

---

### US-009: Quality Gate — code review x4 + CodeRabbit

**Description:** Run code reviewer 4 times across the full Phase 3 changeset, fixing all real bugs found each pass. Run CodeRabbit review. Project validation must pass after all fixes.

**Traces to:** All decisions

**Acceptance Criteria:**
- 4 passes of code review with all real bugs fixed
- CodeRabbit review with findings addressed
- `uv run ruff format --check .` passes
- `uv run ruff check .` passes
- `uv run pytest` passes (all tests including new Phase 3 tests)

**Done when:** All review passes clean, quality gates green.

**Files:** Any files touched during bug fixes

**Depends on:** US-001 through US-008

---

### US-010: Patterns & Memory — update conventions and docs

**Description:** Update `.claude/rules/`, memory files, or docs with new patterns learned during Phase 3 implementation. Document the planner architecture, scoring factors, and block allocation rules.

**Traces to:** All decisions

**Acceptance Criteria:**
- Memory files updated with Phase 3 architecture patterns
- Any new conventions documented

**Done when:** Future sessions have context on the planner module.

**Files:** `.claude/` memory files, optionally `docs/`

**Depends on:** US-009 (Quality Gate)

## Beads Manifest
*(Pending)*
