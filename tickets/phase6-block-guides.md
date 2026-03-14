# Phase 6: Executable Block Guides & Source Bundles

> Replaces the former Phase 6 (evaluation/metrics/parent dashboard), which is deferred.

## Context

The planner produces smart schedules — the scoring engine and time allocator work well. But every study block is a hollow timer card. It shows a title ("Practice 1920s clip review"), a scoring rationale, and Start/Done/Skip buttons. The student has no idea what to actually do.

The "Plan session" block says "Set goals and review priorities." The "Reflect" block says "Review what you learned." The "Start" button records `started_at` and ticks a clock. That's it.

This is the biggest gap in the product. The planner builds a schedule, not a learning experience. The fix is a new abstraction: **each block carries an executable study guide** with target concepts, sourced materials, step-by-step instructions, warm-up questions, and completion criteria.

The evidence base supports this directly: metacognition works best when planning, monitoring, and evaluating are tied to the actual curriculum task — not split off as generic "thinking skills" exercises (EEF). Digital learning prompts improve achievement across 68 studies (2025 meta-analysis). IES recommends using quizzes to promote learning, helping students allocate study time efficiently, and asking deep explanatory questions.

## Goals

- Transform study blocks from timer cards into executable study protocols
- Add guide data model (`study_block_guides` table)
- Build source bundle assembler with tiered retrieval (teacher materials > textbook > external)
- Build guide compiler as a pipeline stage after `allocate_blocks()`
- Define step-by-step protocols for all 6 block types
- Upgrade Plan block from "review priorities" to calibration + warm-up + goal commit
- Upgrade Reflection block from "how did it go?" to exit ticket + teach-back + misconception log
- Rebuild the study plan UI to execute guides instead of running timers

## Work items

### 1. Schema: `study_block_guides` table

The execution layer for study blocks. One guide per block, compiled during plan generation.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| block_id | FK → study_blocks | unique — one guide per block |
| concepts_json | JSONB | `[{name, mastery_level, confidence, source_type}]` |
| source_bundle_json | JSONB | `[{chunk_id, resource_title, trust_level, tier, excerpt}]` |
| steps_json | JSONB | `[{step_number, instruction, step_type, requires_artifact, artifact_type, time_limit_minutes}]` |
| warmup_items_json | JSONB | `[{question, answer, type}]` — 2-3 items for Plan/Retrieval blocks |
| exit_items_json | JSONB | `[{question, answer, type}]` — 1-2 items for Reflection |
| completion_criteria_json | JSONB | `{required_steps: [], min_artifacts: int}` |
| success_criteria_json | JSONB | `["criteria 1", "criteria 2"]` — what "done well" looks like |
| guide_version | text | compiler version for cache invalidation |
| generated_at | timestamp | |

`step_type` values: `instruction`, `recall_prompt`, `confidence_check`, `practice_item`, `teach_back`, `misconception_log`, `goal_commit`, `review_source`, `attempt_problem`

`artifact_type` values: `text_response`, `confidence_rating`, `practice_answer`, `explanation`, `misconception_entry`, `goal_selection`

Add Supabase migration. Add SQLAlchemy table definition to `db.py`.

### 2. Source bundle builder

Create `mitty/guides/sources.py`.

Build a tiered source bundle for a given course + concept(s). The tiers establish provenance and trust:

**Tier 1 — Teacher materials (highest trust):**
- Canvas assignment descriptions and rubrics for the target topic
- Canvas pages from the relevant module
- Teacher-uploaded files and resources
- Quiz/test prompts for the target assessment

**Tier 2 — Supplementary course materials:**
- Textbook chapter/section chunks
- Prior related assignments (graded, for reference)
- Concept-linked past mistakes from `practice_results`

**Tier 3 — External (lowest trust, clearly labeled):**
- Web resources with `source_type = 'web_link'`
- Only included when Tier 1–2 are thin

Uses the existing `retriever.py` for FTS but organizes results by tier. Returns `SourceBundle` with chunks sorted by tier then trust_score.

If total chunks < minimum threshold, set `needs_resources=True` so the UI can prompt "Add study materials for this topic."

### 3. Guide compiler

Create `mitty/guides/compiler.py`.

New pipeline stage inserted between allocation and persistence:

```
allocate_blocks(scored, available_minutes, energy)
    → compile_block_guides(blocks, mastery_data, source_data)
    → _write_blocks(blocks_with_guides)
```

For each allocated block:
1. Query `mastery_states` for target concepts (by course_id)
2. Build source bundle via the source builder
3. Apply the block-type-specific protocol template (work item 4)
4. For steps needing generated content (warm-ups, exit tickets), call LLM with concept + sources
5. Assemble the guide: steps, criteria, source refs

**Deterministic parts (no LLM):** step structure, completion criteria, time allocation per step, concept selection from mastery data.

**LLM-generated parts:** warm-up questions, exit ticket questions, teach-back prompts, success criteria wording.

**Caching:** cache generated content keyed on `(concept, hash(source_chunk_ids))`. If the same concept + sources were compiled recently, reuse. This bounds LLM costs.

**Graceful degradation:** if LLM unavailable, produce a guide with generic step templates and flag it. The student still gets structured instructions, just not personalized questions.

### 4. Block-type protocols

Define the step-by-step protocol for each block type. These are templates the compiler fills in with concept-specific content.

#### Plan block (5–10 min)

1. **Warm-up:** 3 closed-book questions from tonight's target concepts (tests prior knowledge)
2. **Confidence check:** rate confidence 1–5 for each target concept
3. **Calibration display:** show confidence vs. warm-up performance ("You rated Bio confidence 4/5 but got 1/3 warm-up right")
4. **Goal commit:** choose 2 success criteria from generated suggestions
5. **Materials check:** list what to have open (Canvas page, notes section, textbook pages)

Completion: warm-up answered, confidence rated, goals selected.

#### Retrieval block (15–25 min)

1. **Close notes** — explicit instruction to put away materials
2. **Free recall:** write everything you remember about [concept] (3–5 min, unassisted)
3. **Self-check:** reopen sources, compare your recall to the material, note what you missed
4. **Targeted practice:** 3–5 practice items focused on gaps (from practice generator)
5. **Summary:** list 2 things you understand better now

Completion: recall attempt submitted, practice items attempted.

#### Worked example block (20–35 min)

1. **Review example:** study a worked solution from source material (specific page/section cited)
2. **Identify pattern:** what strategy was used? what are the key steps?
3. **Attempt similar:** try an isomorphic problem without looking back at the example
4. **Check work:** compare your approach to the example — what's different?
5. **Practice:** solve one more variation

Completion: at least one problem attempted, check step completed.

#### Deep explanation block (20–30 min)

1. **Read source material** on [topic] (specific page refs from source bundle)
2. **Close notes, summarize** the key ideas in 3–5 sentences
3. **Explain why:** answer a "why does this work?" question about the core concept
4. **Compare/contrast:** how is [concept] different from [related concept]?
5. **Check:** answer a comprehension question

Completion: summary written, explanation submitted.

#### Urgent deliverable block (20–45 min)

1. **Open assignment:** link to Canvas assignment page
2. **Review requirements:** what's expected, points possible, submission format
3. **Work on it:** focus on completion over perfection — ship it
4. **Self-check:** does your work address all the requirements?
5. **Submit:** submit on Canvas before moving on

Completion: self-check completed (we can't verify Canvas submission).

#### Reflection block (5–12 min)

1. **Exit ticket:** one unassisted question on tonight's weakest concept (closed-book)
2. **Teach-back:** explain [concept] as if teaching a friend, in 3–4 sentences
3. **Misconception log:** "What did I think was true that turned out wrong?" — write one entry with: what I thought / why it was wrong / corrected rule
4. **Confidence re-rate:** rate confidence 1–5 for tonight's concepts again
5. **Review target:** "What should tomorrow's plan prioritize?"

Completion: exit ticket answered, teach-back submitted, confidence re-rated.

### 5. Plan generation pipeline update

Modify `mitty/planner/generator.py`:

1. After `allocate_blocks()`, call `compile_block_guides()` for each block
2. Pass `mastery_states` (concept-level) and course resources to the compiler
3. Persist guide data to `study_block_guides` alongside `study_blocks`
4. Query mastery_states per concept for each block's course — not just course-level averages

This is additive: the existing scoring/allocation logic stays the same, but the output is enriched with executable guides.

Compile blocks in parallel (`asyncio.gather`) to keep plan generation fast.

### 6. Study plan UI rebuild

Replace the timer-card view with step-driven execution.

**Collapsed view (all blocks visible):**
- Block card: type icon, title, duration, concept tags, step count
- Status: pending / in_progress / completed
- Progress: "3/5 steps completed"

**Expanded view (active block):**
- Step-by-step guide displayed
- Each step shows instruction + input area (if `requires_artifact`)
- Source references inline (with tier labels for trust transparency)
- Practice items (warm-ups, exit tickets) rendered inline with answer input
- Completion criteria visible: what needs to be done before marking "Done"
- Calibration display in Plan block (confidence vs. warm-up results)

**Key UX changes:**
- "Start" becomes "Begin" and expands the block to show its steps
- Timer runs in background but is secondary to step completion
- "Done" button enables when completion criteria are met (but student can always skip — soft gate, not hard lock)
- Completed blocks show a summary of what was produced

Keep mobile-friendly: steps are thumb-scrollable, text inputs comfortable on phone.

### 7. Concept-level data in guides

The guide compiler queries `mastery_states` directly for concept-level targeting:

- For each block's `course_id`, fetch all mastery_states rows
- Identify weakest concepts (lowest `mastery_level`)
- Identify overconfident concepts (`confidence_self_report >> mastery_level`)
- Use for: warm-up targeting, practice focus, exit ticket topics, teach-back prompts

This is the foundation for Phase 8's full concept-level planner refactor, but here we only use concept data within the guide compiler — the planner scoring still works at course level.

### 8. Simple artifact storage

For this phase, store artifacts produced during guide execution in a lightweight `block_artifacts` table:

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| block_id | FK → study_blocks | |
| step_number | int | which step produced this |
| artifact_type | text | matches step's artifact_type |
| content_json | JSONB | flexible payload |
| created_at | timestamp | |

API: `POST /study-blocks/{block_id}/artifacts` (submit), `GET /study-blocks/{block_id}/artifacts` (retrieve).

Phase 7 extends this with process verification metadata. For now, just capture what the student produces.

## Acceptance criteria

- [ ] `study_block_guides` table created with migration
- [ ] `block_artifacts` table created with migration
- [ ] Source bundle builder returns tiered chunks with trust labels
- [ ] Guide compiler produces structured guides for all 6 block types
- [ ] Plan block guide includes warm-up questions, calibration display, and goal commit
- [ ] Reflection block guide includes exit ticket, teach-back prompt, and misconception log
- [ ] All block types have step-by-step instructions (not just a title + scoring reason)
- [ ] Guides include concept-level targeting from `mastery_states`
- [ ] Guides include source references with tier labels
- [ ] UI shows step-by-step view when block is expanded/active
- [ ] Completion criteria displayed and tracked per block
- [ ] Artifacts captured and stored for artifact-producing steps
- [ ] Graceful degradation: guides work (with generic templates) when LLM unavailable
- [ ] Warm-up and exit ticket content cached by (concept, source hash) to bound LLM costs
- [ ] Guide compilation doesn't add more than 5 seconds to plan generation
- [ ] Mobile-friendly step-by-step view
- [ ] Thorough tests for guide compiler, source builder, and block protocols
- [ ] Quality gates pass

## Risks & open questions

- **LLM cost** — One call per block during compilation (~5 blocks = ~5 calls per plan generation). Cache aggressively by `(concept, source_chunk_ids_hash)`. Consider batching all guides into a single LLM call to reduce overhead.
- **Latency** — Guide compilation adds time to plan generation. Compile in parallel with `asyncio.gather`. Set a timeout and fall back to generic templates if compilation is slow.
- **Source quality** — Guides are only as good as the source material. Courses with thin resources will get generic guides. The `needs_resources` flag makes this visible.
- **Step count** — Too many steps per block will feel like homework about homework. Cap at 4–6 steps per block type. The student should feel guided, not micromanaged.
- **Artifact fatigue** — Keep required artifacts to 2–3 per block. Make the rest optional/skippable. Watch for session abandonment.
- **Cache invalidation** — When new resources are added to a course, cached guides should regenerate. Key the cache on source chunk IDs so this happens naturally.

## Dependencies

- Phase 1: schema + backend API
- Phase 2: resources + resource_chunks (source material for bundles)
- Phase 3: planner + study blocks (extended in this phase)
- Phase 4: practice generator (reused for warm-ups and exit tickets)
- Phase 5: AI client + retriever (extended for source bundles and guide compilation)
