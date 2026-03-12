# Super Plan: Phase 4 — Retrieval Practice + Mastery Tracking

## Meta
- **Ticket**: tickets/phase4-retrieval-mastery.md (local)
- **Branch**: feature/phase4-retrieval-mastery
- **Phase**: detailing
- **Created**: 2026-03-12
- **Sessions**: 1
- **Last session**: 2026-03-12

---

## Discovery

### Ticket Summary

Phase 4 transforms Mitty from a planner into a learning tool by adding LLM-powered retrieval practice, spaced repetition, and mastery tracking. The core loop: extract concepts from course materials → schedule reviews → generate practice items via Claude API → student practices during retrieval blocks → LLM evaluates answers → mastery states update → planner uses updated mastery for future scheduling.

10 work items:
1. Lightweight LLM client (Claude API wrapper)
2. LLM-powered concept extraction
3. Spaced repetition scheduler (SM-2 variant)
4. LLM practice generator (6 question types)
5. LLM answer evaluator (partial credit, misconceptions)
6. Practice session UI
7. Mastery state updater
8. Confidence calibration tracking
9. Mastery dashboard view
10. Canvas discussion topics + announcements ingestion

### Codebase Findings

**What already exists (Phase 1-3 foundation):**

| Component | Status | Notes |
|-----------|--------|-------|
| `mastery_states` table | Exists | Schema in db.py: user_id, course_id, concept, mastery_level, confidence_self_report, last_retrieval_at, next_review_at, retrieval_count, success_rate |
| `practice_results` table | Exists | Schema in db.py: user_id, study_block_id, course_id, concept, practice_type, question_text, student_answer, correct_answer, is_correct, confidence_before, time_spent_seconds |
| Mastery states CRUD API | Exists | `mitty/api/routers/mastery_states.py` — full CRUD with user-scoped RLS |
| Practice results CRUD API | Exists | `mitty/api/routers/practice_results.py` — full CRUD with user-scoped RLS |
| Pydantic schemas | Exist | MasteryStateCreate/Update/Response + PracticeResultCreate/Update/Response in schemas.py |
| Planner "retrieval" blocks | Exists | allocator.py creates retrieval blocks (≥15 min) — Phase 4 fills them |
| Resource chunks | Exist | chunking.py (500-token, 50-token overlap, cl100k_base) + resource_chunks table |
| Canvas fetcher | Exists | All fetch functions except discussion_topics |
| Frontend patterns | Exist | HTMX + Alpine.js + Tailwind + Supabase JS in base.html |
| Auth two-client pattern | Exists | Admin client for JWT validation, data client for RLS queries |

**What needs to be built:**

| Component | Path | Notes |
|-----------|------|-------|
| `practice_items` table | New migration | Cache generated LLM practice items |
| LLM client | `mitty/ai/client.py` | Claude API via `anthropic` SDK (async) |
| Concept extractor | `mitty/mastery/concepts.py` | LLM + pattern fallback |
| Scheduler | `mitty/mastery/scheduler.py` | SM-2 variant |
| Practice generator | `mitty/practice/generator.py` | 6 question types via LLM |
| Answer evaluator | `mitty/practice/evaluator.py` | Exact match + LLM fallback |
| Mastery updater | `mitty/mastery/updater.py` | Weighted moving average + scheduler recalc |
| Practice session UI | `mitty/api/templates/practice_session.html` | HTMX + Alpine.js |
| Mastery dashboard UI | `mitty/api/templates/mastery_dashboard.html` | Per-concept progress |
| Practice session router | `mitty/api/routers/practice_sessions.py` | Orchestrate generation → evaluation → update |
| Discussion fetcher | `mitty/canvas/fetcher.py` | Add `fetch_discussion_topics()` |
| Config: ANTHROPIC_API_KEY | `mitty/config.py` | New SecretStr field |

### Proposed Scope

**In scope:** All 10 work items from the ticket. This is a large phase — likely 15-20 stories.

**Explicitly deferred to Phase 5:**
- Prompt versioning
- Database audit logging (`ai_audit_log` table)
- Rate limiting infrastructure
- Cost budgeting / alerts
- Input sanitization / prompt injection defense
- Conversational coach

### Applicable Rule Constraints

| Rule | Constraint |
|------|-----------|
| architecture.md | Async/await throughout; one service module per domain; thin route handlers |
| coding-style.md | Type hints on all public functions; custom exception classes; < 30 line functions; keyword args for 3+ params |
| testing.md | Mock at boundaries (LLM API, Supabase); parametrize data-driven tests; async tests with pytest-asyncio |
| git-workflow.md | Small logical commits; imperative mood; run ruff + pytest before commit |
| patterns.md | SecretStr for API keys; `mode="json"` for Supabase serialization; UTC dates; semaphore + sleep inside for rate limiting; respx for HTTP mocking |
| api-architecture.md | `_UserScopedClient` for RLS; `maybe_single()` not `single()`; `exclude_unset=True` for updates |

---

## Scoping Questions

### Q1. Claude model selection → **D) Configurable per task**
Default Sonnet for generation/evaluation. Configurable per task in settings. Haiku available for simple match checks.

### Q2. anthropic SDK vs raw httpx → **C) Use anthropic SDK**
Ticket specifies it. Handles retry/backoff, tool use for structured output, token counting. Purpose-built for this use case.

### Q3. practice_items table → **A) New table via migration**
Generate batches per concept, reuse across sessions. Regenerate when mastery shifts significantly or items exhausted. One migration.

### Q4. Discussion topics → **B) Teacher posts + announcements only**
High signal-to-noise. Skip student replies. Store as resources with `resource_type='discussion'`, feed through existing chunking pipeline.

### Q5. Concept granularity → **C) Start coarse, refine over time**
Chapter/unit level from assignment names and module titles. LLM suggests sub-topic breakdowns as resource coverage improves.

### Q6. Practice session launch → **B) Dedicated /practice page**
"Start Practice" button in study plan navigates to `/practice?block_id=X`. Own template manages multi-step flow (confidence → question → answer → feedback → summary).

---

## Architecture Review

### Summary Table

| Area | Rating | Key Finding |
|------|--------|-------------|
| Security | **PASS** | Existing JWT + RLS pattern is solid. Student input → LLM unsanitized (acceptable; Phase 5 adds defense). |
| Performance | **CONCERN** | LLM latency per-answer evaluation (8-16s per session if sync). N+1 risk on practice item loading. Concurrent session race conditions on mastery updates. |
| Data Model | **CONCERN** | `practice_results` table missing 3 columns (`score`, `feedback`, `misconceptions_detected`). PracticeType enum misaligned (5 types vs 6 needed). ResourceType needs "discussion". |
| API Design | **CONCERN** | Session state model undefined (stateful vs stateless). Endpoint naming/schema incomplete. |
| Testing | **PASS** | Established patterns (AsyncMock, respx, TestClient) cover all Phase 4 needs. Add `anthropic` to deps. |
| Observability | **PASS** | Logging infrastructure well-established. Extend with per-call LLM cost logging at INFO level. |

### Security — PASS

- ANTHROPIC_API_KEY follows existing SecretStr pattern (config.py). No new risks.
- New endpoints inherit JWT + RLS auth via `get_current_user` + `get_user_client`.
- Student input to LLM is unsanitized in Phase 4 — acceptable for single-user server-side. Phase 5 adds sanitization.
- No secrets in logs: log token counts and costs, never student answers or LLM responses.
- RLS policies on practice_items table need setup in Supabase.

### Performance — CONCERN

**LLM latency**: Per-answer evaluation = 1-2s per question × 8 questions = 8-16s total wait. Options:
- (a) Per-answer with immediate feedback (pedagogically ideal but slow UX)
- (b) End-of-session batch (simpler, 2-3s total, but no immediate feedback)
- (c) Hybrid: exact-match instantly, LLM only for free-text at session end

**N+1 queries**: Practice session must load items + mastery + chunks. Must use `IN` clauses, not loops.

**Concurrent sessions**: Two tabs updating mastery simultaneously → race condition. Mitigate with upsert `on_conflict`.

**Concept extraction cost**: ~1.5K tokens per course if using chunk summaries (capped to first 100 tokens each). ~$0.005/course. Manageable.

**practice_items indexing**: Needs composite index `(course_id, concept, created_at DESC)` for the hot path.

### Data Model — CONCERN

**Missing columns in `practice_results`:**
- `score` (float, 0-1) — partial credit from evaluator
- `feedback` (text) — LLM explanation of answer
- `misconceptions_detected` (text[]) — identified misconceptions

All nullable, backward-compatible with existing Phase 3 data.

**PracticeType enum misalignment:**
- Current schemas.py: `"quiz", "flashcard", "worked_example", "reflection", "explanation"`
- Phase 4 spec needs: `"multiple_choice", "fill_in_blank", "short_answer", "flashcard", "worked_example", "explanation"`
- Must reconcile — replace "quiz"/"reflection" with the 4 new types.

**ResourceType**: Add "discussion" to the Literal union.

**New `practice_items` table**: Well-scoped. Add `generation_model` column for Phase 5 forward-compat.

### API Design — CONCERN

**Session state model is undefined.** Two options:
- **Stateless (recommended)**: No `practice_sessions` table. Client manages flow state in Alpine.js. API provides: generate items, evaluate answers, update mastery — all as independent endpoints.
- **Stateful**: Create `practice_sessions` table with state machine. More complex, no clear benefit for single-user.

**Proposed stateless endpoints:**
- `POST /study-blocks/{block_id}/practice/generate` → returns practice items for the block's concept
- `POST /practice-results/evaluate` → submit answer, get LLM feedback, store result
- `POST /mastery-states/update-from-results` → batch mastery update after session
- `GET /mastery-dashboard/{course_id}` → aggregated mastery view with calibration

### Testing — PASS

- Mock `anthropic` SDK via `AsyncMock` on `client.messages.create` (cleaner than respx for SDK).
- Parametrize scheduler tests across mastery levels, success rates, retrieval counts.
- Separate exact-match evaluator tests (no mock) from LLM evaluator tests (mock).
- Follow existing `test_planner/` patterns for async + Supabase mocking.
- New test dirs: `tests/test_mastery/`, `tests/test_practice/`, `tests/test_ai/`.

### Observability — PASS

- Logger convention: `logging.getLogger("mitty.ai")` for LLM module.
- Per-call logging at INFO: model, input_tokens, output_tokens, estimated_cost, elapsed_seconds.
- Session logging at INFO: start/end with aggregate stats (questions, correct count, time).
- Never log student answers or LLM responses (sensitive). Concepts and costs are safe.
- Fallback paths logged at WARNING (pattern matching, exact-match-only mode).

---

## Refinement Log

### Decisions

**DEC-001: Claude model selection — Configurable per task, default Sonnet**
- Decision: Model is configurable in Settings. Default claude-sonnet-4-20250514 for generation/evaluation.
- Rationale: Best cost/quality tradeoff. Haiku available for simple checks. Per-task config avoids lock-in.

**DEC-002: Use anthropic SDK (not raw httpx)**
- Decision: Add `anthropic` package as dependency. Use `AsyncAnthropic` client.
- Rationale: SDK handles retry/backoff, tool use for structured output, token counting. Purpose-built; avoids reimplementing what the SDK provides.

**DEC-003: New practice_items table for caching**
- Decision: Create `practice_items` table via Supabase migration. Generate batches per concept, reuse across sessions.
- Rationale: Avoids regenerating every session (~$0.02/session saved). Enables item rotation and exhaustion tracking.

**DEC-004: Discussion topics — teacher posts + announcements only**
- Decision: Fetch topics where `is_announcement=true` OR author is teacher. Skip student replies.
- Rationale: Teacher posts are high-signal (study guides, exam tips). Student replies are mostly noise for concept extraction.

**DEC-005: Concept granularity — start coarse, refine over time**
- Decision: Start at chapter/unit level from assignment names + module titles. LLM suggests sub-topic breakdowns as resource coverage improves.
- Rationale: Avoids cold-start problem of many concepts with zero practice items each.

**DEC-006: Dedicated /practice page (not inline)**
- Decision: "Start Practice" button in study plan navigates to `/practice?block_id=X`. Own template manages the multi-step flow.
- Rationale: Better UX for multi-step interactive flow. Simpler than HTMX partial swaps for state management.

**DEC-007: Hybrid answer evaluation (exact-match + LLM)**
- Decision: Multiple choice + fill-in-blank use instant exact-match (zero LLM cost). Short answer + explanation + worked example get per-answer LLM evaluation (1-2s).
- Rationale: ~70% of items are MC/fill-in-blank — instant feedback. Free-text answers genuinely need LLM and 1-2s wait feels natural. Minimizes cost while preserving pedagogy.

**DEC-008: Stateless practice sessions (no practice_sessions table)**
- Decision: Alpine.js manages session flow client-side. API provides independent endpoints: generate items, evaluate answer, update mastery.
- Rationale: Consistent with existing patterns (study_plan.html). No state machine complexity. Session analytics reconstructable from practice_results WHERE study_block_id = X.

**DEC-009: Replace PracticeType enum entirely**
- Decision: New 6 canonical types: multiple_choice, fill_in_blank, short_answer, flashcard, worked_example, explanation. Drop "quiz" and "reflection".
- Rationale: No existing practice_results rows to migrate. Clean slate.

**DEC-010: Add score/feedback/misconceptions to practice_results**
- Decision: Add 3 nullable columns via migration: score (float), feedback (text), misconceptions_detected (text[]).
- Rationale: Required for partial credit, LLM feedback storage, and misconception tracking. Nullable = backward compatible.

---

## Detailed Breakdown

### US-001: Schema migrations — practice_items table + practice_results columns + ResourceType

**Description:** Create the `practice_items` table for caching LLM-generated questions. Add 3 missing columns to `practice_results` (score, feedback, misconceptions_detected). Add "discussion" to ResourceType. Update PracticeType enum to the 6 canonical types.

**Traces to:** DEC-003, DEC-009, DEC-010

**Acceptance criteria:**
- [ ] `practice_items` table created via Supabase migration with columns: id, user_id, course_id, concept, practice_type, question_text, correct_answer, options_json (jsonb), explanation, source_chunk_ids (int[]), difficulty_level (float), generation_model (varchar), times_used (int), last_used_at, created_at
- [ ] Composite index `(user_id, course_id, concept)` on practice_items
- [ ] RLS policy on practice_items: `user_id = auth.uid()`
- [ ] `practice_results` table altered: + score (float, nullable), + feedback (text, nullable), + misconceptions_detected (text[], nullable)
- [ ] `db.py` updated with practice_items table definition and practice_results new columns
- [ ] `schemas.py`: PracticeType updated to 6 types (multiple_choice, fill_in_blank, short_answer, flashcard, worked_example, explanation)
- [ ] `schemas.py`: PracticeItemCreate/Update/Response triplet added
- [ ] `schemas.py`: PracticeResultCreate/Update/Response updated with score, feedback, misconceptions_detected
- [ ] `schemas.py`: ResourceType expanded with "discussion"
- [ ] Quality gates pass: `uv run ruff format --check . && uv run ruff check . && uv run pytest`

**Done when:** All migrations applied, db.py matches Supabase schema, schemas.py updated, existing tests pass.

**Files:**
- `mitty/db.py` — add practice_items table, update practice_results columns
- `mitty/api/schemas.py` — update PracticeType, add PracticeItem schemas, update PracticeResult schemas, expand ResourceType

**Depends on:** none

---

### US-002: Config + lightweight LLM client

**Description:** Add ANTHROPIC_API_KEY to config, install `anthropic` SDK, create `mitty/ai/client.py` — a minimal async Claude API wrapper with structured output, token counting, cost logging, and retry logic for transient errors.

**Traces to:** DEC-001, DEC-002

**Acceptance criteria:**
- [ ] `anthropic` added to pyproject.toml dependencies
- [ ] `config.py`: new fields `anthropic_api_key: SecretStr | None`, `anthropic_model: str = "claude-sonnet-4-20250514"`
- [ ] `load_settings()` reads `ANTHROPIC_API_KEY` from env
- [ ] `mitty/ai/__init__.py` + `mitty/ai/client.py` created
- [ ] `AIClient` class wrapping `AsyncAnthropic` with: `call_structured(system, user_prompt, response_model) -> T` using tool use for structured output
- [ ] Retry logic: exponential backoff on 429 and 5xx (max 3 retries), no retry on 4xx
- [ ] Per-call INFO logging: model, input_tokens, output_tokens, estimated_cost, elapsed_seconds
- [ ] `AIClientError`, `RateLimitError` custom exceptions in `mitty/ai/errors.py`
- [ ] Tests: mock `AsyncAnthropic.messages.create` via AsyncMock; test happy path, retry on 429, permanent failure on 401, structured output parsing
- [ ] Quality gates pass

**Done when:** `AIClient` can make structured Claude API calls with retry and logging. Tests cover happy path + error paths.

**Files:**
- `pyproject.toml` — add `anthropic` dependency
- `mitty/config.py` — add anthropic fields + env loading
- `mitty/ai/__init__.py` — new module
- `mitty/ai/client.py` — AIClient class
- `mitty/ai/errors.py` — custom exceptions
- `tests/test_ai/__init__.py` + `tests/test_ai/test_client.py`

**Depends on:** US-001 (needs PracticeType enum finalized)

**TDD:**
- test_call_structured_returns_parsed_model
- test_retries_on_429_then_succeeds
- test_retries_on_500_then_succeeds
- test_raises_on_401_no_retry
- test_raises_after_max_retries_exhausted
- test_logs_token_usage_and_cost
- test_client_not_created_without_api_key

---

### US-003: LLM-powered concept extraction

**Description:** Create `mitty/mastery/concepts.py` — extract concept/topic tags from course data using LLM (with pattern-matching fallback when LLM unavailable). Populates mastery_states with initial concept entries.

**Traces to:** DEC-005

**Acceptance criteria:**
- [ ] `extract_concepts(client, ai_client, course_id)` async function: reads assignments, modules, resource chunks from Supabase; sends batched prompt to Claude; returns list of concepts
- [ ] Structured output: LLM returns `list[ConceptExtraction]` with name, description, source_type
- [ ] Pattern fallback: when LLM unavailable, extract chapter numbers, module titles verbatim, assessment unit_or_topic
- [ ] Populates mastery_states with `(user_id, course_id, concept)` pairs, initial mastery_level=0.5
- [ ] Upserts (doesn't duplicate on re-extraction): uses `on_conflict="user_id,course_id,concept"`
- [ ] Chunk summaries capped to first 100 tokens each before batching (cost control)
- [ ] Tests: mock LLM response, verify concept list; test pattern fallback without LLM; test upsert doesn't create duplicates
- [ ] Quality gates pass

**Done when:** Concepts extracted from a course's data via LLM or fallback, stored in mastery_states.

**Files:**
- `mitty/mastery/__init__.py` — new module
- `mitty/mastery/concepts.py` — extraction logic
- `tests/test_mastery/__init__.py` + `tests/test_mastery/test_concepts.py`

**Depends on:** US-002 (needs AIClient)

**TDD:**
- test_extract_concepts_llm_returns_structured_list
- test_extract_concepts_fallback_chapter_numbers
- test_extract_concepts_fallback_module_titles
- test_extract_concepts_fallback_assessment_unit_or_topic
- test_upsert_mastery_states_no_duplicates
- test_chunk_summaries_capped_to_100_tokens

---

### US-004: Spaced repetition scheduler

**Description:** Create `mitty/mastery/scheduler.py` — SM-2 variant that calculates next_review_at from mastery state. Pure logic, no I/O.

**Traces to:** ticket work item 3

**Acceptance criteria:**
- [ ] `calculate_next_review(mastery_level, success_rate, retrieval_count, last_retrieval_at) -> datetime` pure function
- [ ] Interval progression: 1st correct → 1 day, 2nd → 3 days, 3rd → 7 days, 4th+ → exponential
- [ ] Incorrect answer → reset interval to 1 day
- [ ] Mastery < 0.3 → always review daily regardless of other factors
- [ ] New concept (retrieval_count=0) → review today
- [ ] Uses `datetime.now(UTC)` for all date calculations (not date.today())
- [ ] Tests: parametrize across mastery levels, retrieval counts, success rates. Verify interval progression, failure reset, mastery floor, new concept edge case.
- [ ] Quality gates pass

**Done when:** Scheduler produces correct review dates for all mastery state combinations. Fully unit-tested.

**Files:**
- `mitty/mastery/scheduler.py`
- `tests/test_mastery/test_scheduler.py`

**Depends on:** none (pure logic)

**TDD:**
- test_new_concept_reviews_today
- test_first_correct_reviews_in_1_day
- test_second_correct_reviews_in_3_days
- test_third_correct_reviews_in_7_days
- test_incorrect_resets_to_1_day
- test_low_mastery_always_daily
- test_high_mastery_high_success_long_interval
- test_uses_utc_dates

---

### US-005: LLM practice generator

**Description:** Create `mitty/practice/generator.py` — given a concept and resource chunks, call Claude to generate practice items (6 types). Cache generated items in practice_items table.

**Traces to:** DEC-003, DEC-007

**Acceptance criteria:**
- [ ] `generate_practice_items(ai_client, supabase_client, course_id, concept, mastery_level, resource_chunks) -> list[PracticeItem]` async function
- [ ] Generates 6-8 items per concept in one batched LLM call
- [ ] All 6 types: multiple_choice (4 options, 1 correct), fill_in_blank, short_answer (with rubric), flashcard, worked_example (steps + practice problem), explanation (with rubric)
- [ ] Every item cites source chunk IDs
- [ ] Difficulty scales with mastery_level (low mastery = simpler, more scaffolded)
- [ ] Varies question type within a batch
- [ ] Returns "needs_resources" indicator when chunks insufficient (no LLM call)
- [ ] Generated items stored in practice_items table via upsert
- [ ] Checks cache first: returns existing items if available and not exhausted
- [ ] Pydantic models for structured LLM output
- [ ] Tests: mock LLM, verify all 6 types generated; test needs_resources fallback; test caching (cache hit skips LLM)
- [ ] Quality gates pass

**Done when:** Practice items generated for a concept, cached, and reused across sessions.

**Files:**
- `mitty/practice/__init__.py` — new module
- `mitty/practice/generator.py`
- `tests/test_practice/__init__.py` + `tests/test_practice/test_generator.py`

**Depends on:** US-001 (practice_items table), US-002 (AIClient)

**TDD:**
- test_generate_all_6_types
- test_items_cite_source_chunks
- test_difficulty_scales_with_mastery_level
- test_needs_resources_when_no_chunks
- test_cache_hit_skips_llm_call
- test_items_stored_in_practice_items_table
- test_varies_question_types_in_batch

---

### US-006: LLM answer evaluator

**Description:** Create `mitty/practice/evaluator.py` — hybrid evaluation: exact-match for MC/fill-in-blank, LLM for free-text. Returns score, feedback, misconceptions.

**Traces to:** DEC-007

**Acceptance criteria:**
- [ ] `evaluate_answer(ai_client, practice_item, student_answer) -> EvaluationResult` async function
- [ ] Multiple choice: exact match on correct option (case-insensitive, trimmed)
- [ ] Fill-in-blank: exact match first; LLM fallback for reasonable variations ("cellular resp" → "cellular respiration")
- [ ] Short answer: LLM scores against rubric (0.0-1.0 partial credit)
- [ ] Explanation: LLM assesses completeness, accuracy, depth
- [ ] Worked example: LLM checks method + answer correctness
- [ ] Returns: `EvaluationResult(is_correct, score, feedback, misconceptions_detected)`
- [ ] Exact-match path never calls LLM (cost optimization verified in tests)
- [ ] Tests: test exact-match for MC (no mock needed); test LLM evaluation for short answer (mock); test partial credit scoring; test misconception detection
- [ ] Quality gates pass

**Done when:** All answer types evaluated correctly with hybrid exact-match/LLM approach.

**Files:**
- `mitty/practice/evaluator.py`
- `tests/test_practice/test_evaluator.py`

**Depends on:** US-002 (AIClient)

**TDD:**
- test_mc_exact_match_correct
- test_mc_exact_match_incorrect
- test_mc_case_insensitive
- test_fill_in_blank_exact_match
- test_fill_in_blank_llm_fallback_for_variation
- test_short_answer_llm_partial_credit
- test_explanation_llm_scoring_with_rubric
- test_worked_example_llm_method_check
- test_exact_match_never_calls_llm
- test_misconception_detection_returned

---

### US-007: Mastery state updater

**Description:** Create `mitty/mastery/updater.py` — after practice results, update mastery_level (weighted moving average), success_rate (rolling), confidence_self_report, retrieval_count, and recalculate next_review_at via scheduler.

**Traces to:** DEC-008, ticket work items 7 + 8

**Acceptance criteria:**
- [ ] `update_mastery(supabase_client, user_id, course_id, concept, results: list[PracticeResult]) -> MasteryState` async function
- [ ] mastery_level: weighted moving average (recent results weighted more; correct → toward 1.0, incorrect → toward 0.0, partial credit proportional)
- [ ] success_rate: rolling accuracy over last 20 attempts
- [ ] confidence_self_report: average of recent confidence_before ratings
- [ ] retrieval_count: increment by len(results)
- [ ] next_review_at: recalculated via `calculate_next_review()` from scheduler
- [ ] last_retrieval_at: `datetime.now(UTC)`
- [ ] Upsert with `on_conflict="user_id,course_id,concept"` (atomic, race-condition safe)
- [ ] Confidence calibration gap: `confidence_self_report - success_rate` calculated and available
- [ ] Handles null scores gracefully (falls back to is_correct boolean)
- [ ] Tests: parametrize across result batches; verify weighted average; test rolling window; test confidence calibration calculation; test scheduler integration
- [ ] Quality gates pass

**Done when:** Mastery states updated correctly after practice, with calibration metrics.

**Files:**
- `mitty/mastery/updater.py`
- `tests/test_mastery/test_updater.py`

**Depends on:** US-004 (scheduler)

**TDD:**
- test_correct_answers_increase_mastery
- test_incorrect_answers_decrease_mastery
- test_partial_credit_proportional
- test_rolling_success_rate_last_20
- test_confidence_calibration_gap_positive_overconfident
- test_confidence_calibration_gap_negative_underconfident
- test_retrieval_count_incremented
- test_next_review_recalculated
- test_upsert_atomic_on_conflict
- test_handles_null_scores_uses_is_correct

---

### US-008: Canvas discussion topics + announcements ingestion

**Description:** Add `fetch_discussion_topics()` to Canvas fetcher. Store teacher posts/announcements as resources with `resource_type='discussion'`. Strip HTML, feed through chunking pipeline.

**Traces to:** DEC-004, ticket work item 10

**Acceptance criteria:**
- [ ] `fetch_discussion_topics(client, course_id) -> list[DiscussionTopic]` in `mitty/canvas/fetcher.py`
- [ ] Fetches `GET /api/v1/courses/:id/discussion_topics` with pagination
- [ ] Filters: includes announcements (`is_announcement=true`) and teacher-authored posts; excludes student replies
- [ ] `DiscussionTopic` Pydantic model in `mitty/models.py` (title, message, posted_at, author, is_announcement)
- [ ] HTML stripping via bs4 (same pipeline as Phase 2)
- [ ] Storage: upsert as resources with `resource_type='discussion'`
- [ ] Chunking: feed through `achunk_text()` → store in resource_chunks
- [ ] `fetch_all()` updated to include discussion topics
- [ ] Tests: mock Canvas API responses with respx; test HTML stripping; test resource creation
- [ ] Quality gates pass

**Done when:** Discussion topics fetched, stored as resources, chunked, ready for concept extraction.

**Files:**
- `mitty/canvas/fetcher.py` — add fetch_discussion_topics()
- `mitty/models.py` — add DiscussionTopic model
- `mitty/storage.py` — add discussion ingestion to pipeline
- `tests/test_canvas/test_fetcher_discussions.py`

**Depends on:** US-001 (ResourceType includes "discussion")

---

### US-009: Practice session API endpoints

**Description:** Create stateless practice session endpoints: generate items for a block, evaluate an answer, batch-update mastery after session. Orchestrates generator, evaluator, and updater.

**Traces to:** DEC-006, DEC-007, DEC-008

**Acceptance criteria:**
- [ ] `POST /study-blocks/{block_id}/practice/generate` — fetches concept from block, calls generator, returns practice items (cached or fresh)
- [ ] `POST /practice-results/evaluate` — accepts { practice_item_id, student_answer, confidence_before }, calls evaluator, stores result, returns EvaluationResult with feedback
- [ ] `POST /mastery-states/update-from-results` — accepts { study_block_id }, reads practice_results for that block, calls updater per concept, returns updated mastery states
- [ ] All endpoints: user-scoped via `get_current_user` + `get_user_client`
- [ ] Practice items router registered in `app.py`
- [ ] New Pydantic schemas: PracticeGenerateRequest, PracticeGenerateResponse, EvaluateRequest, EvaluateResponse, MasteryUpdateRequest, MasteryUpdateResponse
- [ ] Graceful degradation: if LLM unavailable, generate endpoint returns cached items only; evaluate endpoint uses exact-match only
- [ ] Tests: mock Supabase + AIClient; test generate returns items; test evaluate stores result; test mastery update flow
- [ ] Quality gates pass

**Done when:** All 3 endpoints work end-to-end with mocked dependencies.

**Files:**
- `mitty/api/routers/practice_sessions.py` — new router
- `mitty/api/schemas.py` — add request/response schemas
- `mitty/api/app.py` — register new router
- `tests/test_api/test_practice_sessions.py`

**Depends on:** US-005 (generator), US-006 (evaluator), US-007 (updater)

---

### US-010: Practice session UI

**Description:** Create the practice session page — HTMX + Alpine.js template. Multi-step flow: confidence → question → answer → feedback → next → session summary.

**Traces to:** DEC-006, DEC-008, ticket work item 6

**Acceptance criteria:**
- [ ] `mitty/api/templates/practice_session.html` template (extends base.html)
- [ ] Page route: `GET /practice` in pages.py, accepts `block_id` query param
- [ ] Alpine.js state machine: confidence_prompt → question → answer_submitted → feedback → next_question → session_complete
- [ ] Per question: confidence slider (1-5) → display question → text input/radio buttons (type-dependent) → "Check Answer" button → feedback panel (correct/incorrect + explanation + source citation)
- [ ] Progress bar: "3/8 questions"
- [ ] Session summary view: X/Y correct, concepts to review, confidence calibration message ("You were confident on 3 questions you got wrong")
- [ ] Calls API endpoints: POST /study-blocks/{block_id}/practice/generate on load, POST /practice-results/evaluate per answer, POST /mastery-states/update-from-results on complete
- [ ] Study plan "Start Practice" button links to `/practice?block_id=X` for retrieval blocks
- [ ] Tailwind styling consistent with existing templates
- [ ] Quality gates pass

**Done when:** Student can complete a full practice session from study plan through to summary.

**Files:**
- `mitty/api/templates/practice_session.html` — new template
- `mitty/api/routers/pages.py` — add `/practice` route
- `mitty/api/templates/study_plan.html` — add "Start Practice" button on retrieval blocks

**Depends on:** US-009 (practice API endpoints)

---

### US-011: Mastery dashboard API + UI

**Description:** Create mastery dashboard — per-concept progress view with mastery bars, calibration indicators, next review dates, and resource coverage.

**Traces to:** ticket work items 8 + 9

**Acceptance criteria:**
- [ ] `GET /mastery-dashboard/{course_id}` endpoint returns aggregated mastery data: concepts with mastery_level, success_rate, confidence_self_report, calibration_status (well_calibrated/over_confident/under_confident), next_review_at, has_resources (bool)
- [ ] Calibration thresholds: gap > 0.2 = over_confident, gap < -0.2 = under_confident, else well_calibrated
- [ ] Sortable by: mastery_level, next_review_at, calibration gap
- [ ] `mitty/api/templates/mastery_dashboard.html` template: per-concept rows with mastery bar (colored by level), calibration badge, next review, "No study materials" indicator
- [ ] Page route: `GET /mastery` in pages.py
- [ ] Navigation: link from dashboard/study plan to mastery dashboard
- [ ] Tailwind styling consistent with existing templates
- [ ] Tests: test endpoint returns correct calibration status; test sorting
- [ ] Quality gates pass

**Done when:** Mastery dashboard shows per-concept progress with calibration indicators.

**Files:**
- `mitty/api/routers/mastery_dashboard.py` — new router
- `mitty/api/schemas.py` — add MasteryDashboardResponse
- `mitty/api/app.py` — register router
- `mitty/api/templates/mastery_dashboard.html` — new template
- `mitty/api/routers/pages.py` — add `/mastery` route
- `tests/test_api/test_mastery_dashboard.py`

**Depends on:** US-003 (concepts populated), US-007 (mastery updated)

---

### US-012: Planner integration — mastery_gap + confidence_gap scoring

**Description:** Wire mastery data into the planner's priority scoring. Concepts with low mastery or high confidence gap get scored higher for retrieval blocks.

**Traces to:** ticket acceptance criteria: "Practice results feed back into planner scoring (mastery_gap, confidence_gap)"

**Acceptance criteria:**
- [ ] `scoring.py`: add `W_MASTERY_GAP` and `W_CONFIDENCE_GAP` weights (small, additive to existing 6 factors)
- [ ] `StudyOpportunity` dataclass: add optional `mastery_gap: float` and `confidence_gap: float` fields
- [ ] `generator.py`: when building opportunities, fetch mastery_states for the course; compute mastery_gap (1.0 - mastery_level) and confidence_gap (confidence_self_report - success_rate) per concept; attach to relevant opportunities
- [ ] Retrieval block allocation: prefer concepts with highest mastery_gap or positive confidence_gap (overconfident)
- [ ] Backward compatible: mastery_gap/confidence_gap default to 0.0 when no mastery data exists
- [ ] Tests: verify scoring with mastery data present vs absent; verify retrieval block selects highest-gap concept
- [ ] Quality gates pass

**Done when:** Planner uses mastery data to prioritize study topics.

**Files:**
- `mitty/planner/scoring.py` — add mastery/confidence weights + factors
- `mitty/planner/generator.py` — fetch mastery data, attach to opportunities
- `mitty/planner/allocator.py` — use mastery gap for retrieval block concept selection
- `tests/test_planner/test_scoring_mastery.py`
- `tests/test_planner/test_generator.py` — update for new mastery data reads

**Depends on:** US-007 (mastery updater)

---

### US-013: Quality Gate — code review x4 + CodeRabbit

**Description:** Run code reviewer 4 passes across the full Phase 4 changeset, fixing all real bugs found each pass. Run CodeRabbit review if available. All quality gates must pass.

**Acceptance criteria:**
- [ ] 4 code review passes completed, all findings addressed
- [ ] CodeRabbit review completed (if available)
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` passes (all tests green)
- [ ] No security issues introduced (OWASP top 10 check)

**Done when:** All quality gates green, code reviewed 4x, no outstanding findings.

**Files:** Any files touched by US-001 through US-012.

**Depends on:** US-001 through US-012

---

### US-014: Patterns & Memory — update conventions and docs

**Description:** Update `.claude/rules/`, memory files, and documentation with new patterns learned from Phase 4 implementation.

**Acceptance criteria:**
- [ ] Memory files updated with Phase 4 architecture (ai module, mastery module, practice module)
- [ ] patterns.md updated with LLM client patterns, anthropic SDK mocking patterns
- [ ] Any new conventions or gotchas documented

**Done when:** Future conversations have full context on Phase 4 patterns.

**Files:** Memory files, patterns.md, MEMORY.md

**Depends on:** US-013 (Quality Gate)

---

## Beads Manifest

*(Phase 7 — after approval)*

- **Epic ID**: TBD
- **Task IDs**: TBD
- **Worktree**: ../worktrees/mitty/phase4-retrieval-mastery
