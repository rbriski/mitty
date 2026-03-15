# Super Plan: Mastery Hub — Streamlined Test Prep Experience

## Meta

| Field | Value |
|-------|-------|
| **Ticket** | `tickets/phase8-mastery-hub.md` |
| **Branch** | `feature/phase8-mastery-hub` |
| **Worktree** | `../worktrees/mitty/phase8-mastery-hub` |
| **Phase** | `detailing` |
| **Sessions** | 1 |
| **Last session** | 2026-03-15 |

---

## Discovery

### Ticket Summary

Redesign the app around a single learning loop: **see the gap → practice → reflect → repeat**. Remove Study Plan from navigation. Elevate Mastery as the central hub that auto-detects the upcoming test, shows concept-level weakness, and provides one-click entry into test prep sessions. Adjust session phase timing based on learning science research (R1-R6). Shorten feedback, embed running calibration, hide difficulty from student.

### Key Codebase Findings

- **Navigation triplicated**: `partials/nav.html` + each page overrides with custom Alpine.js nav (5 edit points)
- **Mastery dashboard**: `GET /mastery-dashboard/{course_id}` already has calibration computation, sort options, course selector
- **Test Prep**: Alpine.js state machine (setup → analysis → mastery → session → complete), `POST /test-prep/sessions` takes course_id + assessment_id + concepts[]
- **Assessment detection ready**: `assessments` table has `scheduled_date` + `assessment_type`, index on `(course_id, scheduled_date)`
- **Concept-to-assessment gap**: No direct mapping. Concepts live in `homework_analyses.analysis_json`. Assessments have `unit_or_topic` text field.
- **Hard-coded term**: `'2025-2026 Second Semester'` in mastery_dashboard.html

---

## Architecture Review

| Area | Rating | Key Finding |
|------|--------|-------------|
| Security | pass | All endpoints auth-protected. RLS enforced. No data exposure. |
| Performance | concern | Session history needs LIMIT. All indexes exist. |
| Data Model | pass (Phase 8a) | `coach_messages` coupling deferred to Phase 8b. Additive migrations only. |
| API Design | pass | Keeping `/test-prep/*` API routes. Adding `session_type` column. |
| Testing | concern | ~21 new tests needed. Nav/template changes need manual verification. |
| Deletion Impact | deferred | Full Study Plan removal (56+ files) deferred to Phase 8b. |

---

## Refinement Log

### Decisions

**DEC-001 — Concept-to-assessment mapping**
Add nullable `chapter` text field to `assignments` table. Parse from assignment name at Canvas ingestion time (e.g., "(4.1) Homework" → chapter "4"). Match to `assessments.unit_or_topic` for scoping.
*Rationale:* Reliable for Canvas naming conventions, no join table needed, single migration.

**DEC-002 — URL routing**
Keep all API endpoints at `/test-prep/*`. Remove `/test-prep` as standalone page route from `pages.py`. Mastery template links directly to test prep API. Session renders inline or navigates via JS.
*Rationale:* Zero API breaking changes. Mastery becomes the only entry point.

**DEC-003 — Study Plan removal scope**
Split into Phase 8a (Mastery Hub + nav hide, no table drops) and Phase 8b (full code/table removal). Phase 8a hides Study Plan + Test Prep from nav but leaves all code/tables intact.
*Rationale:* Decouples user-facing improvement from large refactor (56+ files, coach/escalation coupling).

**DEC-004 — Session types**
Two modes: `full` (45 min, all 5 phases) and `quick` (15 min, Phase 4+5 only). Add `session_type` text column to `test_prep_sessions` with CHECK constraint and default `'full'`.
*Rationale:* Covers immediate use cases. Column (not state_json) enables filtering/analytics.

**DEC-005 — Multi-test support**
Smart default to nearest upcoming test (query `assessments` where `scheduled_date > now()` ordered ASC). Dropdown to switch between upcoming assessments within next 14 days.
*Rationale:* Simple default, escape hatch for multi-test weeks.

**DEC-006 — Coach/escalation coupling**
Deferred to Phase 8b. Phase 8a does NOT touch coach_messages, flagged_responses, practice_results, escalation detection, or any tables with study_block FKs.
*Rationale:* These features are deeply coupled to study_blocks. Rearchitecting them is a separate workstream.

**DEC-007 — Session history**
Show last 5 sessions with trend text (e.g., "Trend: +14% over 3 sessions"). No pagination. LIMIT 5 ORDER BY started_at DESC.
*Rationale:* Simple, covers 99% of use cases.

**DEC-008 — Real-time heat map**
Local Alpine.js state updates after each answer (from session engine's per-concept running mastery). No server round-trip for map. Sync to `mastery_states` on session completion.
*Rationale:* Fast UX, no latency. Session engine already tracks concept_mastery in state_json.

---

## Detailed Breakdown

### US-001: Schema migrations

**Description:** Add `chapter` column to `assignments` and `session_type` column to `test_prep_sessions`. Two additive, backward-compatible migrations.

**Traces to:** DEC-001, DEC-004

**Acceptance Criteria:**
- `assignments.chapter` is nullable text, no default
- `test_prep_sessions.session_type` is text NOT NULL, default `'full'`, CHECK `IN ('full', 'quick')`
- Both migrations applied via Supabase MCP
- `mitty/db.py` updated with new columns
- `uv run ruff check . && uv run pytest` pass

**Done when:** Columns exist in both db.py and Supabase, existing data unaffected.

**Files:**
- `mitty/db.py` — add columns to table definitions
- `supabase/migrations/20260316000001_add_chapter_and_session_type.sql` — new migration

**Depends on:** none

---

### US-002: Navigation surgery

**Description:** Remove Study Plan and Test Prep from all navigation locations. Keep routes and code intact (Phase 8a scope). Add redirect banner on `/study-plan` page.

**Traces to:** DEC-003

**Acceptance Criteria:**
- Study Plan link removed from: `partials/nav.html`, `dashboard.html`, `mastery_dashboard.html`, `test_prep.html`, `study_plan.html` inline navs
- Test Prep link removed from same 5 locations
- Nav shows only: Dashboard, Mastery
- `/study-plan` page shows "This feature has moved to Mastery" banner with link
- `/test-prep` route removed from `pages.py` (API routes remain)
- `uv run ruff check . && uv run pytest` pass

**Done when:** Nav shows 2 items across all pages. `/study-plan` shows redirect.

**Files:**
- `mitty/api/templates/partials/nav.html`
- `mitty/api/templates/dashboard.html`
- `mitty/api/templates/mastery_dashboard.html`
- `mitty/api/templates/test_prep.html`
- `mitty/api/templates/study_plan.html`
- `mitty/api/routers/pages.py` — remove `/test-prep` page route

**Depends on:** none

---

### US-003: Upcoming assessment detection endpoint

**Description:** New endpoint to find the nearest upcoming test/quiz for a student's courses. Returns assessment details + associated concepts from homework analyses.

**Traces to:** DEC-001, DEC-005

**Acceptance Criteria:**
- `GET /mastery-dashboard/upcoming?course_id={id}` returns nearest assessment with `scheduled_date > now()` and `assessment_type IN ('test', 'quiz')`
- Response includes: assessment_id, name, scheduled_date, assessment_type, course_id, concepts (from homework_analyses for same course)
- If no upcoming assessment, returns null/empty
- Optional `course_id` param — if omitted, searches across all enrolled courses
- Auth-protected, RLS-enforced
- `uv run ruff check . && uv run pytest` pass

**Done when:** Endpoint returns correct upcoming assessment with concept list.

**Files:**
- `mitty/api/routers/mastery_dashboard.py` — new endpoint
- `mitty/api/schemas.py` — new `UpcomingAssessmentResponse` schema
- `tests/test_api/test_mastery_dashboard.py` — new tests

**TDD:**
- `test_upcoming_assessment_returns_nearest_future_test`
- `test_upcoming_assessment_no_future_tests_returns_empty`
- `test_upcoming_assessment_filters_by_type_test_quiz_only`
- `test_upcoming_assessment_includes_concepts_from_homework`

**Depends on:** US-001 (chapter field for concept mapping)

---

### US-004: Session history endpoint

**Description:** New endpoint returning the last 5 test prep sessions for a user/course, with accuracy and trend calculation.

**Traces to:** DEC-007

**Acceptance Criteria:**
- `GET /mastery-dashboard/session-history?course_id={id}` returns last 5 completed sessions
- Each session includes: session_id, started_at, total_problems, total_correct, accuracy (%), duration_seconds, phase_reached, session_type
- Response includes `trend_text` computed from last 3+ sessions (e.g., "+14% over 3 sessions" or null if <3)
- Ordered by started_at DESC, LIMIT 5
- Auth-protected, RLS-enforced
- `uv run ruff check . && uv run pytest` pass

**Done when:** Endpoint returns session history with trend.

**Files:**
- `mitty/api/routers/mastery_dashboard.py` — new endpoint
- `mitty/api/schemas.py` — new `SessionHistoryResponse`, `SessionHistoryEntry` schemas
- `tests/test_api/test_mastery_dashboard.py` — new tests

**TDD:**
- `test_session_history_returns_last_5_ordered_desc`
- `test_session_history_trend_text_with_3_sessions`
- `test_session_history_no_sessions_returns_empty`

**Depends on:** none

---

### US-005: Mastery hub template redesign

**Description:** Complete redesign of `mastery_dashboard.html` as the central hub. Three states: upcoming test view (default), no-test fallback, session entry. Includes concept heat map sorted by weakness, calibration callouts, smart CTA, session history, and assessment switcher dropdown.

**Traces to:** DEC-005, DEC-007, DEC-008

**Acceptance Criteria:**
- On load, fetches upcoming assessment + mastery data + session history (3 parallel API calls)
- Concept heat map: visual bars sorted weakest-last, color-coded (green >80%, yellow 50-80%, red <50%)
- Calibration callout: prominent message when any concept has confidence - mastery > 0.2
- Primary CTA: "Start Practice — [weakest concept]" button
- Secondary CTAs: "Full session (all concepts)" and "Quick review (15 min)"
- Session history: last 5 sessions with trend text
- Assessment switcher: dropdown of upcoming assessments (next 14 days)
- No-test fallback: shows all courses with mastery data, "Analyze Homework" CTA for courses without
- Mobile: heat map collapses to progress bar at <768px
- `uv run ruff check . && uv run pytest` pass

**Done when:** Mastery page renders hub with all three states correctly.

**Files:**
- `mitty/api/templates/mastery_dashboard.html` — complete rewrite

**Depends on:** US-002 (nav updated), US-003 (upcoming assessment endpoint), US-004 (session history endpoint)

---

### US-006: One-click session entry + return flow

**Description:** Connect Mastery hub CTAs to test prep session creation. "Start Practice" skips the setup flow entirely — creates session with pre-filled params from Mastery data. Session completion navigates back to Mastery with updated heat map and "Next focus" suggestion.

**Traces to:** DEC-002, DEC-004, DEC-008

**Acceptance Criteria:**
- "Start Practice — [concept]" creates session via `POST /test-prep/sessions` with course_id, assessment_id, and concepts from Mastery data
- Session renders inline within Mastery page (Alpine.js view transition) or navigates to session view
- On session complete, "Back to Mastery" button replaces "Start New Session"
- Mastery re-fetches data on return (heat map reflects session results)
- Post-session suggestion text: "You improved on [concept] (+X%). Next focus: [weakest]."
- Quick review CTA creates session with `session_type: 'quick'`
- `uv run ruff check . && uv run pytest` pass

**Done when:** Full loop works: Mastery → Start Practice → session → complete → back to Mastery with updated data.

**Files:**
- `mitty/api/templates/mastery_dashboard.html` — session entry logic
- `mitty/api/templates/test_prep.html` — completion view changes (back-to-mastery CTA, remove start-new-session)
- `mitty/api/routers/test_prep.py` — accept `session_type` in `TestPrepSessionCreate`
- `mitty/api/schemas.py` — add `session_type` to `TestPrepSessionCreate`

**Depends on:** US-005 (Mastery hub template)

---

### US-007: Session phase timing + quick review mode

**Description:** Update session engine phase durations to match research-driven timing. Implement quick review mode that skips Phases 1-3.

**Traces to:** DEC-004, R3 (interleaving), R6 (error analysis)

**Acceptance Criteria:**
- Full session (45 min): Diagnostic 5min, Focused 8min, Error Analysis 12min, Mixed 15min, Calibration 5min
- Quick review (15 min): Mixed Test 10min, Calibration 5min (skips Phases 1-3)
- Session engine `from_state_dict()` respects `session_type` for phase list and durations
- Phase auto-advance uses new durations
- `uv run ruff check . && uv run pytest` pass

**Done when:** `SessionEngine` produces correct phase sequences and durations for both session types.

**Files:**
- `mitty/prep/session.py` — phase timing constants, quick review phase list
- `tests/test_prep/test_session.py` — update timing assertions

**TDD:**
- `test_full_session_phase_durations_match_spec`
- `test_quick_session_skips_phases_1_through_3`
- `test_quick_session_starts_at_mixed_test`
- `test_phase_advance_uses_new_durations`

**Depends on:** US-001 (session_type column)

---

### US-008: Shorten feedback + hide difficulty

**Description:** Change answer feedback to one-line error summary + correct answer, with expandable worked solution. Remove all visible difficulty indicators from the session UI.

**Traces to:** R4 (CMU Cognitive Tutor — brief feedback), R2 (invisible difficulty)

**Acceptance Criteria:**
- After wrong answer: one sentence identifying error type/location + correct answer visible
- "Show worked solution" link expands step-by-step explanation (collapsed by default)
- After correct answer: brief "Correct!" + correct answer (no lengthy explanation)
- "Difficulty: X%" label removed from session header
- Difficulty number removed from problem cards
- Evaluator response includes `error_summary` (1 sentence) and `worked_solution` (expandable)
- `uv run ruff check . && uv run pytest` pass

**Done when:** Feedback is concise by default. No difficulty visible to student.

**Files:**
- `mitty/api/templates/test_prep.html` — feedback rendering, remove difficulty labels
- `mitty/api/routers/test_prep.py` — update answer response to include `error_summary`
- `mitty/api/schemas.py` — add `error_summary` to `TestPrepAnswerResult` (if needed)

**Depends on:** none

---

### US-009: Running calibration checkpoints

**Description:** Add confidence checks at phase transitions (before/after Focused Practice, before Mixed Test). Store in session state_json. Display gap after each checkpoint.

**Traces to:** DEC-008, R5 (metacognition)

**Acceptance Criteria:**
- Before Phase 2 (Focused Practice): "How confident are you on [concept]?" (1-5 scale)
- After Phase 2: "You rated X/5, you scored Y/Z (N%)." with gap indicator
- Before Phase 4 (Mixed Test): brief confidence check across all concepts
- Phase 5 (Calibration): full comparison table including running checkpoints from this session
- Confidence ratings stored in `state_json.per_concept_confidence`
- `uv run ruff check . && uv run pytest` pass

**Done when:** Confidence prompts appear at phase transitions. Gap is displayed. Data persists in state_json.

**Files:**
- `mitty/api/templates/test_prep.html` — confidence UI at phase transitions
- `mitty/prep/session.py` — store confidence in state, provide calibration data at Phase 5

**Depends on:** US-007 (phase timing, so transitions are correct)

---

### US-010: Error analysis enhancements

**Description:** Add two problem subtypes to Phase 3: find-the-mistake (worked solution with deliberate error) and review-own-errors (student's incorrect answers from earlier phases, presented for self-explanation).

**Traces to:** R6 (derring effect — deliberate errors produce superior transfer)

**Acceptance Criteria:**
- Find-the-mistake: problem generator produces a worked solution with one deliberate error. Student identifies and explains the error.
- Review-own-errors: system pulls student's wrong answers from Phases 1-2 of current session. Presents: "Here's your answer to problem N. What went wrong?"
- Self-explanation (review-own-errors) is ungraded — student writes reflection, system acknowledges
- Phase 3 alternates between find-the-mistake and review-own-errors
- `uv run ruff check . && uv run pytest` pass

**Done when:** Phase 3 presents both problem types. Find-the-mistake is AI-generated. Review-own-errors pulls from session history.

**Files:**
- `mitty/prep/generator.py` — `error_analysis` problem type generates deliberate-error variants
- `mitty/prep/session.py` — Phase 3 logic alternates subtypes, pulls own errors
- `mitty/api/templates/test_prep.html` — review-own-errors UI (reflection text input, no scoring)
- `mitty/api/routers/test_prep.py` — handle ungraded reflection submissions

**Depends on:** US-007 (phase timing for Phase 3 duration)

---

### US-011: Quality Gate

**Description:** Run 4 code-reviewer passes across the full Phase 8a changeset, fixing all real bugs found each pass. Run CodeRabbit review. Ensure all quality gates pass.

**Acceptance Criteria:**
- 4 code review passes completed, all real bugs fixed
- CodeRabbit review completed, findings addressed
- `uv run ruff format --check . && uv run ruff check . && uv run pytest` all pass
- No regressions in existing test suite

**Done when:** All review findings addressed. Quality gates green.

**Files:** Any files touched by US-001 through US-010.

**Depends on:** US-001 through US-010

---

### US-012: Patterns & Memory

**Description:** Update `.claude/rules/`, `docs/`, or memory with new patterns learned during Phase 8a implementation. Update MEMORY.md with Phase 8a completion status.

**Acceptance Criteria:**
- Memory updated with Phase 8a status and any new architectural patterns
- Any new conventions documented

**Done when:** Memory and docs reflect current state.

**Files:** `.claude/projects/*/memory/`, `.claude/rules/` (if applicable)

**Depends on:** US-011

---

## Dependency Graph

```
US-001 (migrations) ──┬──→ US-003 (upcoming assessment) ──→ US-005 (hub template) ──→ US-006 (session entry + return)
                      │                                         ↑
US-002 (nav surgery) ─┘          US-004 (session history) ─────┘

US-007 (phase timing + quick) ──→ US-009 (calibration)
                                  US-010 (error analysis)

US-008 (feedback + hide difficulty) — independent

All US-001..010 ──→ US-011 (Quality Gate) ──→ US-012 (Patterns)
```

---

## Beads Manifest

*(Pending — Phase 7, after approval)*
