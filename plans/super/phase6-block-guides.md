# Super Plan: Phase 6 — Executable Block Guides & Source Bundles

## Meta
- **Ticket:** tickets/phase6-block-guides.md
- **Branch:** feature/phase6-block-guides
- **Phase:** devolved
- **Sessions:** 1
- **Last session:** 2026-03-13

---

## Discovery

### Ticket Summary

**What:** Transform study blocks from hollow timer cards into executable study protocols. Each block gets a compiled guide with target concepts, sourced materials, step-by-step instructions, warm-up questions, and completion criteria. Adds `study_block_guides` and `block_artifacts` tables, a source bundle builder (tiered retrieval), a guide compiler (pipeline stage after allocation), block-type protocols for all 6 types, and a rebuilt step-driven UI.

**Why:** The planner builds a schedule, not a learning experience. Students see a title and Start/Done/Skip buttons but have no idea what to actually do. This is the biggest gap in the product. Evidence supports structured metacognitive prompts tied to curriculum tasks (EEF, 2025 meta-analysis, IES).

**Who:** High school students using Mitty's daily study planner.

### Dependencies (all complete)
- Phase 1: Schema + backend API
- Phase 2: Resources + resource_chunks (source material)
- Phase 3: Planner + study blocks (extended here)
- Phase 4: Practice generator (reused for warm-ups/exit tickets)
- Phase 5: AI client + retriever (extended for source bundles + guide compilation)

### Codebase Findings

**Planner pipeline (`mitty/planner/`):**
- `allocate_blocks()` returns `list[StudyBlock]` (frozen dataclass: block_type, title, duration_minutes, course_name, reason)
- `generator.py` orchestrates: read signals → score → allocate → `_write_blocks()` to Supabase
- 6 block types: plan, urgent_deliverable, retrieval, worked_example, deep_explanation, reflection
- Plan/Reflection are always first/last with fixed 5-min durations

**Database (`mitty/db.py`):**
- 19 tables defined (SQLAlchemy Core)
- Key tables: `study_plans`, `study_blocks`, `mastery_states`, `resources`, `resource_chunks`, `practice_items`, `practice_results`
- `study_blocks` has: id, plan_id, block_type, title, description, target_minutes, actual_minutes, course_id, assessment_id, sort_order, status, started_at, completed_at
- `mastery_states` has: user_id, course_id, concept, mastery_level, confidence_self_report, retrieval_count, success_rate, next_review_at

**Retriever (`mitty/ai/retriever.py`):**
- `retrieve(client, course_id, query, top_k, min_results)` → `RetrievalResult` with `chunks: list[RetrievedChunk]` and `sufficient: bool`
- Uses Postgres FTS with trust scoring per chunk
- `RetrievedChunk`: chunk_id, content_text, resource_id, resource_title, trust_score, rank

**AI client (`mitty/ai/client.py`):**
- `AIClient` with rate limiting, cost budgeting, audit logging, retries
- `call_structured(response_model=PydanticModel)` for structured LLM output
- Prompt versioning in `prompts.py` with content hashing

**Practice generator (`mitty/practice/generator.py`):**
- `generate_practice_items(ai_client, supabase_client, user_id, course_id, concept, mastery_level)` → `GenerationResult`
- 6 types: multiple_choice, fill_in_blank, short_answer, flashcard, worked_example, explanation
- Caches items, reuses via `times_used` counter

**Mastery (`mitty/mastery/`):**
- Concept extraction (LLM + pattern fallback)
- Weighted-moving-average updater
- SM-2 spaced repetition scheduler

**Migration pattern:** `YYYYMMDDHHMMSS_name.sql`, uses `IF NOT EXISTS`, RLS policies, composite indexes

**Reusable patterns:**
1. Orchestrator pattern (read → transform → write) from generator.py
2. Pydantic structured LLM output via `call_structured()`
3. Async Supabase batch upsert from storage.py
4. Retrieval + trust scoring from retriever.py
5. Prompt versioning + injection defense from prompts.py

### Key Ambiguities

1. **Warm-up generation:** Ticket says Phase 4 practice generator is "reused" but also says compiler "calls LLM with concept + sources." Reuse existing `generate_practice_items()` or new LLM call?
2. **Cache storage backend:** Cache keyed on `(concept, hash(source_chunk_ids))` — in-memory, Supabase table, or the existing practice_items table?
3. **Calibration display data flow:** Plan block warm-up answers happen at runtime but guides are compiled at plan-generation time. UI must compute calibration on-the-fly from submitted artifacts.
4. **Source chunk minimum threshold:** How many chunks needed before `needs_resources=True`?
5. **Artifact API auth/validation:** No specification for artifact type validation or rate limiting.
6. **Guide + block persistence transaction:** Single transaction or separate writes? Failure handling if guide write fails but block write succeeded.
7. **Guide regeneration:** `guide_version` column exists but no invalidation strategy specified.
8. **Mastery data for new students:** Fallback when zero mastery data exists for a course.
9. **Batching LLM calls:** Ticket raises batching all guides into one call as an option vs. one call per block.
10. **Protocol module structure:** Single `protocols.py` with dispatch or separate files per block type?

### Rule Constraints (from .claude/rules/)
- All I/O must be `async def` with `await`
- Type hints on all public functions
- `@dataclass(frozen=True, slots=True)` for value objects
- Pydantic `BaseModel` for API schemas only
- Custom exceptions for domain errors, never bare `except:`
- Mock at boundaries (Supabase, LLM, retriever), not internal functions
- `@pytest.mark.parametrize` for data-driven tests across 6 block types
- Quality gates: `ruff format --check`, `ruff check`, `pytest`
- Feature branch, imperative commit messages
- New `mitty/guides/` subpackage (not top-level)
- Max 88-char lines, f-strings, import order enforced

---

## Scoping Questions & Decisions

### DEC-001: Warm-up/exit ticket generation
**Decision:** A3 — Hybrid. Reuse cached `practice_items` when available, generate fresh via guide-specific prompt when guide context matters (calibration warm-ups, teach-back prompts).
**Rationale:** Bounds LLM cost for courses with rich practice history while allowing guide-specific framing.

### DEC-002: Cache storage backend
**Decision:** B2 — Supabase table (`guide_content_cache`). Persistent, survives restarts, queryable.
**Rationale:** 5-second latency budget depends on cache hits across deploys. In-memory doesn't survive restarts.

### DEC-003: LLM call batching
**Decision:** C1 — One call per block, compiled in parallel via `asyncio.gather` with 4-second timeout.
**Rationale:** Simple, per-block caching works naturally, partial failure isolated. ~$0.10/plan at Sonnet pricing is well within $1/session budget.

### DEC-004: Protocol module structure
**Decision:** D1 — Single `mitty/guides/protocols.py` with dispatch function. Matches `allocator.py` pattern.
**Rationale:** Protocols are mostly data (step definitions, criteria), not complex logic. ~300-400 lines, consistent with codebase style.

### DEC-005: Guide persistence failure handling
**Decision:** E3 — Graceful degradation + flag. Write blocks first (critical), then compile guides (enrichment). Failed guides flagged via `guide_status` field on block.
**Rationale:** Plan generation must never fail. Missing guides degrade to generic templates with retry option.

### DEC-006: Source chunk minimum threshold
**Decision:** F1 — < 3 chunks. Adjusted from < 5 based on live data analysis.
**Rationale:** All academic courses currently have 0-1 chunks. Threshold of 3 catches genuinely thin courses without being meaningless. Made a constant for easy tuning.

### DEC-007: Resource content enrichment (Path A)
**Decision:** Include resource content enrichment as a prerequisite work item in Phase 6. Three content sources:
1. **Canvas file text extraction** — Download PDFs/docs, extract text (highest impact, teachers put core material in files)
2. **Assignment descriptions** — Fetch and store assignment description HTML body
3. **Module item content resolution** — Follow `page_url` links on module items to fetch actual page body
**Rationale:** Without content in chunks, source bundles return empty for every academic course and guides always degrade to generic templates. The guide architecture needs material to work with.

### DEC-008: Scope of content enrichment
**Decision:** Files + assignment descriptions + module item resolution. Quiz content extraction deferred (more complex API, lower priority).
**Rationale:** These three sources cover the bulk of teacher-provided content. Quiz extraction can be a fast-follow.

## Architecture Review

**Completed 2026-03-13. 6 parallel reviews: Security, Performance, Data Model, API Design, Observability, Testing Strategy.**

| Area | Rating | Resolution |
|------|--------|------------|
| Security: Auth | PASS | Use existing `CurrentUser` + `UserClient` + ownership verify |
| Security: RLS | PASS | Inner join policy pattern through block → plan → user_id |
| Security: XSS | CONCERN → DEC-013 | Always `x-text`/autoescape for artifacts |
| Security: SSRF | PASS | Canvas API URLs only; validate hostnames |
| Security: LLM injection | CONCERN → DEC-013 | Always `wrap_user_input()` for artifact content |
| Security: Secrets | PASS | AIClient logs metrics only, never content |
| Performance: Latency | PASS | 4-5s parallel compilation within 5s budget |
| Performance: FTS | PASS | 5 parallel retrieve() calls, GIN-indexed |
| Performance: File extraction | PASS | Batch in fetch_all, not per-request |
| Performance: Cache | PASS | 20-40% hit rate day 2+, auto-invalidates |
| Performance: DB writes | PASS | ~15KB/plan, batch inserts <50ms |
| Data Model: FKs | PASS | Surrogate ID + UNIQUE FK + CASCADE |
| Data Model: JSONB | PASS | 7 JSONB columns for reference data |
| Data Model: Backward compat | PASS | Additive; old plans render without guides |
| Data Model: Migration | PASS | Net-new tables, IF NOT EXISTS |
| Data Model: Indexes | CONCERN → DEC-014 | block_artifacts(block_id), cache(concept, source_hash) UNIQUE |
| Data Model: RLS | CONCERN → DEC-009 | Skip RLS, trust app-layer |
| API: REST conventions | PASS | Matches coach/practice patterns |
| API: Response enrichment | CONCERN → DEC-010 | Separate guide fetch, not inlined |
| API: Error handling | PASS | GUIDE_NOT_FOUND, GUIDE_FAILED codes |
| API: Pagination | PASS | Artifacts paginated (limit=20) |
| Observability: Logging | PASS | Guide LLM calls auto-captured in ai_audit_log |
| Observability: Errors | CONCERN → DEC-015 | GuideCompilationError with structured context |
| Testing: Patterns | PASS | _QueryChain, AsyncMock, parametrize proven |
| Testing: Edge cases | CONCERN → addressed in story ACs | LLM failure, cache, empty sources |

## Refinement Log

### DEC-009: RLS on new tables
**Decision:** Skip RLS on `study_block_guides`, `block_artifacts`, `guide_content_cache`. Trust app-layer auth.
**Rationale:** Consistent with `study_blocks` (no RLS). Parent table has no RLS — adding to children creates false sense of security. App-layer ownership verify proven across 5 routers.

### DEC-010: Guide fetch strategy
**Decision:** Both batch and per-block endpoints. `GET /study-plans/{id}/guides` for plan load, `POST /study-blocks/{id}/guide/retry` for targeted retry.
**Rationale:** Batch eliminates 5-request waterfall on mobile plan load. Per-block retry is surgical for failed guides. Both are thin queries.

### DEC-011: PDF extraction library
**Decision:** pymupdf for PDFs, python-docx for Word docs. Typed text only.
**Rationale:** Fast (10-50x pdfplumber), good accuracy on formatted worksheets/study guides. Right-sized for student materials.

### DEC-012: Content enrichment trigger
**Decision:** During `fetch_all()` in existing Canvas sync pipeline.
**Rationale:** Content stays current automatically. No manual steps. 10-30s increase in sync time acceptable. On-demand (option C) would blow 5s guide compilation budget.

### DEC-013: Handwriting extraction
**Decision:** Skip for Phase 6. pymupdf extracts typed content only.
**Rationale:** Teacher handouts are mostly typed (questions, instructions, rubrics). Handwritten content (answer keys, graded feedback) deferred to future Claude Vision pass when data shows which courses need it.

### DEC-014: Index design
**Decision:** Three indexes in migration: `study_block_guides(block_id) UNIQUE` (via FK constraint), `block_artifacts(block_id)`, `guide_content_cache(concept, source_hash) UNIQUE`.
**Rationale:** Covers all query patterns. Simple compound indexes, standard practice.

### DEC-015: Structured error tracking
**Decision:** Define `GuideCompilationError(block_id, step, message)` with fields for `sources_fetched` and `llm_called`. Log checkpoints at each compilation stage.
**Rationale:** Multi-step pipeline needs structured context for debugging partial failures.

## Detailed Breakdown

### US-001: Schema migration + SQLAlchemy definitions

**Description:** Create the three new tables (`study_block_guides`, `block_artifacts`, `guide_content_cache`) via Supabase migration and add SQLAlchemy Core definitions to `db.py`.

**Traces to:** DEC-002, DEC-005, DEC-009, DEC-014

**Acceptance Criteria:**
- [ ] Migration `20260314000000_phase6_block_guides.sql` creates all 3 tables with `IF NOT EXISTS`
- [ ] `study_block_guides`: surrogate PK, `block_id` UNIQUE FK → `study_blocks(id) ON DELETE CASCADE`, 7 JSONB columns, `guide_version`, `generated_at`
- [ ] `block_artifacts`: PK, `block_id` FK → `study_blocks(id) ON DELETE CASCADE`, `step_number`, `artifact_type`, `content_json`, `created_at`
- [ ] `guide_content_cache`: PK, `concept` + `source_hash` UNIQUE, `content_type`, `content_json`, `created_at`
- [ ] Indexes: `block_artifacts(block_id)`, `guide_content_cache(concept, source_hash)` unique
- [ ] No RLS policies on new tables (DEC-009)
- [ ] SQLAlchemy table definitions added to `mitty/db.py` matching migration
- [ ] `uv run ruff format --check . && uv run ruff check . && uv run pytest` passes

**Done when:** Migration applies cleanly; db.py has matching definitions; existing tests still pass.

**Files:**
- `supabase/migrations/20260314000000_phase6_block_guides.sql` (new)
- `mitty/db.py` (extend, ~lines 440+)

**Depends on:** none

---

### US-002: Add pymupdf + python-docx dependencies

**Description:** Add PDF and Word document text extraction libraries to the project.

**Traces to:** DEC-011

**Acceptance Criteria:**
- [ ] `pymupdf` added to `pyproject.toml` dependencies
- [ ] `python-docx` added to `pyproject.toml` dependencies
- [ ] `uv lock` succeeds, `uv sync` installs both
- [ ] Quick smoke test: `uv run python -c "import pymupdf; import docx"` succeeds
- [ ] Quality gates pass

**Done when:** Both libraries importable; lockfile updated.

**Files:**
- `pyproject.toml` (edit dependencies)

**Depends on:** none

---

### US-003: File content download + text extraction

**Description:** Add functions to download Canvas file content (PDFs, DOCX) and extract plain text. This is the highest-impact content enrichment — teachers put core material in files.

**Traces to:** DEC-007, DEC-008, DEC-011, DEC-013

**Acceptance Criteria:**
- [ ] New `mitty/canvas/extract.py` module with `extract_text_from_pdf(content: bytes) -> str` and `extract_text_from_docx(content: bytes) -> str`
- [ ] New `download_file_content(client, file_url) -> bytes` in fetcher or extract module
- [ ] PDF extraction uses pymupdf; DOCX uses python-docx
- [ ] Handles: empty files (returns ""), corrupt files (logs warning, returns ""), unsupported formats (skips)
- [ ] Max file size limit (10MB) — skip larger files with warning
- [ ] Canvas URL validated before download (DEC-013 security: hostname check)
- [ ] Type hints on all public functions
- [ ] Tests with sample PDF and DOCX fixtures in `tests/fixtures/`
- [ ] Quality gates pass

**Done when:** Can download a Canvas file URL and get plain text back for PDFs and DOCX files.

**Files:**
- `mitty/canvas/extract.py` (new)
- `tests/test_canvas/test_extract.py` (new)
- `tests/fixtures/sample.pdf` (new, small test PDF)
- `tests/fixtures/sample.docx` (new, small test DOCX)

**Depends on:** US-002

**TDD:**
- `test_extract_pdf_returns_text` — basic PDF extraction
- `test_extract_docx_returns_text` — basic DOCX extraction
- `test_extract_empty_file_returns_empty_string`
- `test_extract_corrupt_file_returns_empty_string`
- `test_extract_oversized_file_skipped`
- `test_download_validates_canvas_hostname`

---

### US-004: Assignment descriptions + module item page resolution

**Description:** Fetch assignment description HTML bodies and resolve module item `page_url` links to get actual page content. Store as `content_text` on existing resource rows.

**Traces to:** DEC-007, DEC-008

**Acceptance Criteria:**
- [ ] `fetch_assignments()` in `fetcher.py` now includes `description` field (HTML body)
- [ ] New helper to resolve module item `page_url` → fetch page body via Canvas Pages API
- [ ] `upsert_module_items_as_resources()` in `storage.py` populates `content_text` for resolved pages
- [ ] Assignment descriptions stored as `content_text` on assignment resources (HTML stripped to plain text)
- [ ] Graceful skip if page fetch fails (log warning, continue)
- [ ] Tests mock Canvas API responses for descriptions and page resolution
- [ ] Quality gates pass

**Done when:** Assignment resources and module-item-page resources have `content_text` populated after sync.

**Files:**
- `mitty/canvas/fetcher.py` (modify `fetch_assignments` ~line 60+, add page resolution helper)
- `mitty/storage.py` (modify `upsert_module_items_as_resources` ~line 601+, assignment description storage)
- `tests/test_canvas/test_fetcher.py` (extend)
- `tests/test_storage.py` (extend)

**Depends on:** none

---

### US-005: Content enrichment pipeline integration

**Description:** Wire file extraction (US-003) and content resolution (US-004) into the `fetch_all()` → `store_all()` pipeline. Run chunking on all newly populated `content_text`.

**Traces to:** DEC-007, DEC-012

**Acceptance Criteria:**
- [ ] `fetch_all()` in `fetcher.py` downloads file content for supported types (PDF, DOCX) during sync
- [ ] `store_all()` in `storage.py` calls `chunk_and_store_resources()` for file resources with populated `content_text`
- [ ] Assignment description resources and resolved module-item pages are also chunked
- [ ] Pipeline handles file download failures gracefully (log warning, skip file, continue)
- [ ] Rate limiting on Canvas file downloads (respect Canvas API limits)
- [ ] Sync time increase documented (expected 10-30s for file downloads)
- [ ] Integration test: mock full pipeline from fetch → store → chunk for a course with files
- [ ] Quality gates pass

**Done when:** Running `uv run python -m mitty` populates `content_text` and creates `resource_chunks` for files, assignments, and resolved module pages.

**Files:**
- `mitty/canvas/fetcher.py` (modify `fetch_all()` ~line 334+)
- `mitty/storage.py` (modify `store_all()` ~line 994+, extend chunking calls)
- `tests/test_storage.py` (extend integration tests)

**Depends on:** US-003, US-004

---

### US-006: Source bundle builder

**Description:** Build `mitty/guides/sources.py` — assembles tiered source bundles for a given course + concepts using the existing retriever. Organizes results by trust tier (teacher materials > supplementary > external).

**Traces to:** DEC-006, DEC-007

**Acceptance Criteria:**
- [ ] New `mitty/guides/__init__.py` (package marker)
- [ ] New `mitty/guides/sources.py` with `build_source_bundle(client, course_id, concepts) -> SourceBundle`
- [ ] `SourceBundle` frozen dataclass: `chunks: list[TieredChunk]`, `needs_resources: bool`, `tier_counts: dict`
- [ ] `TieredChunk` frozen dataclass: `chunk_id, content_text, resource_title, trust_score, tier: Literal["teacher", "supplementary", "external"]`
- [ ] Tier assignment based on resource type: canvas_page/file → teacher, discussion/prior_assignment → supplementary, web_link → external
- [ ] Uses existing `retrieve()` from `mitty/ai/retriever.py` for FTS
- [ ] `needs_resources = True` when total chunks < 3 (DEC-006, `MIN_SOURCE_CHUNKS` constant)
- [ ] Chunks sorted by tier (teacher first) then trust_score descending
- [ ] Async function with type hints
- [ ] Tests: sufficient sources, thin sources (needs_resources), empty sources, tier sorting
- [ ] Quality gates pass

**Done when:** Given a course and concepts, returns a tiered source bundle with trust labels.

**Files:**
- `mitty/guides/__init__.py` (new)
- `mitty/guides/sources.py` (new)
- `tests/test_guides/__init__.py` (new)
- `tests/test_guides/test_sources.py` (new)

**Depends on:** none (uses existing retriever)

**TDD:**
- `test_build_source_bundle_returns_tiered_chunks`
- `test_needs_resources_true_when_below_threshold`
- `test_needs_resources_false_when_sufficient`
- `test_chunks_sorted_by_tier_then_trust`
- `test_empty_retrieval_returns_empty_bundle`
- `test_tier_assignment_by_resource_type`

---

### US-007: Block-type protocols

**Description:** Define step-by-step protocol templates for all 6 block types in a single `protocols.py` module with a dispatch function.

**Traces to:** DEC-004

**Acceptance Criteria:**
- [ ] New `mitty/guides/protocols.py` with `get_protocol(block_type: BlockType) -> Protocol`
- [ ] `Protocol` frozen dataclass: `block_type, steps: list[ProtocolStep], completion_criteria, max_steps`
- [ ] `ProtocolStep` frozen dataclass: `step_number, instruction_template, step_type, requires_artifact, artifact_type, time_limit_minutes`
- [ ] All 6 block types defined: plan, retrieval, worked_example, deep_explanation, urgent_deliverable, reflection
- [ ] Plan protocol: warm-up (3 items), confidence check, calibration display, goal commit, materials check
- [ ] Retrieval protocol: close notes, free recall, self-check, targeted practice, summary
- [ ] Worked example: review example, identify pattern, attempt similar, check work, practice
- [ ] Deep explanation: read source, close-notes summarize, explain why, compare/contrast, check
- [ ] Urgent deliverable: open assignment, review requirements, work on it, self-check, submit
- [ ] Reflection: exit ticket, teach-back, misconception log, confidence re-rate, review target
- [ ] `step_type` values match ticket spec: instruction, recall_prompt, confidence_check, practice_item, teach_back, misconception_log, goal_commit, review_source, attempt_problem
- [ ] Each protocol capped at 4-6 steps
- [ ] Tests: all 6 types via `@pytest.mark.parametrize`, step count validation, dispatch function
- [ ] Quality gates pass

**Done when:** `get_protocol("retrieval")` returns the complete protocol template for retrieval blocks.

**Files:**
- `mitty/guides/protocols.py` (new)
- `tests/test_guides/test_protocols.py` (new)

**Depends on:** none

**TDD:**
- `test_get_protocol_returns_protocol_for_all_6_types` (parametrized)
- `test_protocol_step_count_within_bounds` (4-6 per type)
- `test_protocol_step_types_are_valid`
- `test_plan_protocol_has_warmup_and_goal_commit`
- `test_reflection_protocol_has_exit_ticket_and_teachback`
- `test_unknown_block_type_raises_value_error`

---

### US-008: Guide compiler + prompts

**Description:** Build the guide compiler that orchestrates: mastery query → source bundle → protocol → LLM generation → cache → assembly. Add `guide_compiler` prompt role.

**Traces to:** DEC-001, DEC-002, DEC-003, DEC-005, DEC-015

**Acceptance Criteria:**
- [ ] New `mitty/guides/compiler.py` with `compile_block_guide(ai_client, client, block, course_id, user_id) -> BlockGuide`
- [ ] `BlockGuide` frozen dataclass matching `study_block_guides` schema: concepts_json, source_bundle_json, steps_json, warmup_items_json, exit_items_json, completion_criteria_json, success_criteria_json
- [ ] Queries `mastery_states` for concept-level targeting (weakest concepts, overconfident concepts)
- [ ] Calls `build_source_bundle()` for tiered sources
- [ ] Applies `get_protocol()` template for the block type
- [ ] LLM call via `AIClient.call_structured()` for: warm-up questions (plan/retrieval), exit tickets (reflection), teach-back prompts, success criteria wording
- [ ] Hybrid warm-up generation (DEC-001): check `practice_items` cache first, generate fresh only when needed
- [ ] Cache: check `guide_content_cache` before LLM call, store after (DEC-002)
- [ ] Graceful degradation: if LLM unavailable or times out, produce guide with generic step templates (DEC-005)
- [ ] `GuideCompilationError` exception class with block_id, step, sources_fetched, llm_called (DEC-015)
- [ ] Logging: INFO for compilation progress, WARNING for degradation, DEBUG for step details
- [ ] New `guide_compiler` prompt role in `mitty/ai/prompts.py` with versioned system prompt + user template
- [ ] `wrap_user_input()` used for any student-produced content passed to LLM
- [ ] Type hints on all public functions
- [ ] Tests: happy path, cache hit (no LLM), LLM failure (graceful degradation), empty mastery data, empty sources
- [ ] Quality gates pass

**Done when:** Given a study block, produces a complete executable guide with concepts, sources, steps, warm-ups, and completion criteria.

**Files:**
- `mitty/guides/compiler.py` (new)
- `mitty/ai/prompts.py` (extend with `guide_compiler` role, ~line 234+)
- `tests/test_guides/test_compiler.py` (new)

**Depends on:** US-001, US-006, US-007

**TDD:**
- `test_compile_guide_happy_path` — all 6 block types (parametrized)
- `test_compile_guide_cache_hit_skips_llm`
- `test_compile_guide_caches_after_llm_call`
- `test_compile_guide_graceful_degradation_on_llm_failure`
- `test_compile_guide_with_empty_mastery_data`
- `test_compile_guide_with_empty_sources_sets_needs_resources`
- `test_compile_guide_wraps_user_input`
- `test_hybrid_warmup_reuses_practice_items`

---

### US-009: Pipeline integration

**Description:** Modify `generate_plan()` to call the guide compiler after block allocation. Compile guides in parallel via `asyncio.gather` with 4-second timeout.

**Traces to:** DEC-003, DEC-005

**Acceptance Criteria:**
- [ ] `generate_plan()` in `generator.py` calls `compile_block_guides()` after `_write_blocks()`
- [ ] New `compile_block_guides(ai_client, client, blocks, plan_id, user_id) -> list[BlockGuide | None]` orchestrator
- [ ] Compiles all blocks in parallel via `asyncio.gather(return_exceptions=True)` with 4-second timeout per block
- [ ] Persists guides to `study_block_guides` table via batch insert
- [ ] Failed guide compilations don't fail plan generation (DEC-005) — block works without guide
- [ ] `generate_plan()` accepts optional `ai_client` parameter (None = skip guide compilation)
- [ ] Guide compilation adds < 5 seconds to plan generation (acceptance criterion from ticket)
- [ ] Tests: plan generation with guides, plan generation without AI client (skips guides), partial guide failure
- [ ] Quality gates pass

**Done when:** `POST /study-plans/generate` produces a plan with compiled guides for each block.

**Files:**
- `mitty/planner/generator.py` (modify `generate_plan()` ~line 514+, `_write_blocks()` ~line 480+)
- `mitty/api/routers/study_plans.py` (pass `ai_client` to `generate_plan`)
- `mitty/api/dependencies.py` (may need to expose `ai_client` for plan generation)
- `tests/test_planner/test_generator.py` (extend)

**Depends on:** US-008

---

### US-010: API schemas + guide/artifact router

**Description:** Add Pydantic response schemas and create the guide + artifact API router with batch and per-block endpoints.

**Traces to:** DEC-010

**Acceptance Criteria:**
- [ ] New schemas in `schemas.py`: `BlockGuideResponse`, `BlockArtifactCreate`, `BlockArtifactResponse`
- [ ] `BlockGuideResponse` includes all JSONB fields deserialized + `guide_version` + `generated_at`
- [ ] `BlockArtifactCreate`: `step_number`, `artifact_type`, `content_json` (max_length validated)
- [ ] New `mitty/api/routers/block_guides.py` router with:
  - `GET /study-plans/{plan_id}/guides` — batch fetch all guides for a plan (DEC-010)
  - `GET /study-blocks/{block_id}/guide` — fetch single guide
  - `POST /study-blocks/{block_id}/guide/retry` — recompile failed guide
  - `POST /study-blocks/{block_id}/artifacts` — submit artifact
  - `GET /study-blocks/{block_id}/artifacts` — list artifacts (paginated, limit=20)
- [ ] All endpoints require `CurrentUser` + `UserClient` + ownership verification
- [ ] Error codes: `GUIDE_NOT_FOUND` (404), `GUIDE_FAILED` (409), `BLOCK_NOT_FOUND` (404)
- [ ] Router registered in `app.py`
- [ ] Tests for all endpoints: happy path, auth failures, not found, artifact validation
- [ ] Quality gates pass

**Done when:** All 5 endpoints work with proper auth, validation, and error handling.

**Files:**
- `mitty/api/schemas.py` (extend, ~line 761+)
- `mitty/api/routers/block_guides.py` (new)
- `mitty/api/app.py` (register router)
- `tests/test_api/test_block_guides.py` (new)

**Depends on:** US-001

---

### US-011: Study plan UI rebuild

**Description:** Replace the timer-card study plan view with step-driven guide execution. Collapsed view shows block cards with progress; expanded view shows step-by-step guide with artifact inputs.

**Traces to:** DEC-010, DEC-013

**Acceptance Criteria:**
- [ ] Collapsed block card: type icon, title, duration, concept tags, step progress ("3/5 steps")
- [ ] Expanded block: step-by-step guide with instructions, source references (tier labels), artifact input areas
- [ ] "Begin" button expands block and shows steps (replaces bare "Start")
- [ ] Timer runs in background, secondary to step completion
- [ ] "Done" button soft-gated: enables when completion criteria met, but always skippable
- [ ] Completed blocks show summary of artifacts produced
- [ ] Plan block: warm-up questions inline, confidence slider, calibration display (computed from submitted artifacts), goal commit
- [ ] Reflection block: exit ticket inline, teach-back text area, misconception log form, confidence re-rate
- [ ] Source references shown inline with tier badges (Teacher/Supplementary/External)
- [ ] Blocks without guides fall back to title + duration + description (backward compat)
- [ ] Batch guide fetch on plan load (`GET /study-plans/{id}/guides`)
- [ ] Artifact submission via `POST /study-blocks/{id}/artifacts` on step completion
- [ ] Mobile-friendly: steps thumb-scrollable, text inputs comfortable on phone
- [ ] Quality gates pass

**Done when:** Student can load a plan, expand a block, follow step-by-step instructions, submit artifacts, and see completion progress.

**Files:**
- `mitty/api/templates/study_plan.html` (major rewrite)

**Depends on:** US-009, US-010

---

### US-012: Quality Gate

**Description:** Run code reviewer across the full Phase 6 changeset. Fix all real bugs found. Run CodeRabbit review if available. All quality gates must pass after fixes.

**Acceptance Criteria:**
- [ ] Code review pass 1: correctness + edge cases
- [ ] Code review pass 2: security (XSS, injection, auth)
- [ ] Code review pass 3: performance (N+1, unbounded queries, missing indexes)
- [ ] Code review pass 4: consistency (naming, patterns, style)
- [ ] CodeRabbit review (if available) — address all findings
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` passes (all tests, including new Phase 6 tests)
- [ ] All real bugs fixed; false positives documented

**Done when:** All 4 review passes complete, all quality gates green, no open issues.

**Files:** Any files touched in US-001 through US-011.

**Depends on:** US-001 through US-011

---

### US-013: Patterns & Memory

**Description:** Update project conventions, documentation, and memory with patterns learned during Phase 6 implementation.

**Acceptance Criteria:**
- [ ] Update `.claude/rules/` if new patterns established (guide compilation, content extraction)
- [ ] Update memory with Phase 6 completion status and new module architecture
- [ ] Document any gotchas discovered during implementation

**Done when:** Future conversations have full context on Phase 6 architecture.

**Files:** `.claude/rules/`, memory files

**Depends on:** US-012

---

### Dependency Graph

```
US-001 (schema) ──────────────────────┬──→ US-008 (compiler) ──→ US-009 (pipeline) ──┐
                                      │                                                ├──→ US-011 (UI)
US-002 (deps) ──→ US-003 (files) ──┐  │                                                │
                                   ├──→ US-005 (enrichment)                            │
US-004 (assignments) ──────────────┘                                                   │
                                                                                       │
US-006 (sources) ─────────────────────→ US-008 (compiler)                              │
                                                                                       │
US-007 (protocols) ───────────────────→ US-008 (compiler)                              │
                                                                                       │
US-001 (schema) ──────────────────────→ US-010 (API) ──────────────────────────────────┘

US-011 (UI) ──→ US-012 (quality gate) ──→ US-013 (patterns)
```

**Parallel tracks:**
- Track A: US-001 → US-010 (schema → API) — can start immediately
- Track B: US-002 → US-003 → US-005 (deps → files → enrichment) — content pipeline
- Track C: US-004 → US-005 (assignments → enrichment) — parallel with Track B
- Track D: US-006, US-007 (sources, protocols) — independent, can start immediately
- Track E: US-008 → US-009 → US-011 (compiler → pipeline → UI) — main critical path

## Beads Manifest

- **Epic:** `mitty-hns`
- **Branch:** `feature/phase6-block-guides`
- **Tasks:** 13

| Story | Bead ID | Status |
|-------|---------|--------|
| US-001: Schema migration | `mitty-hns.1` | open |
| US-002: Add pymupdf + python-docx | `mitty-hns.2` | open |
| US-003: File download + extraction | `mitty-hns.3` | blocked |
| US-004: Assignment descriptions + module resolution | `mitty-hns.4` | open |
| US-005: Content enrichment integration | `mitty-hns.5` | blocked |
| US-006: Source bundle builder | `mitty-hns.6` | open |
| US-007: Block-type protocols | `mitty-hns.7` | open |
| US-008: Guide compiler + prompts | `mitty-hns.8` | blocked |
| US-009: Pipeline integration | `mitty-hns.9` | blocked |
| US-010: API schemas + router | `mitty-hns.10` | blocked |
| US-011: Study plan UI rebuild | `mitty-hns.11` | blocked |
| US-012: Quality Gate | `mitty-hns.12` | blocked |
| US-013: Patterns & Memory | `mitty-hns.13` | blocked |

**Ready now (5):** US-001, US-002, US-004, US-006, US-007
