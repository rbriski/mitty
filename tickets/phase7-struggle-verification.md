# Phase 7: Productive Struggle, Verification & Coach Integration

> Replaces the former Phase 7 (privacy/permissions/hardening), which is deferred.

## Context

Phase 6 gave blocks structured guides with steps, source bundles, and completion criteria. But the steps are still self-reported: the student clicks through them and says "done." There's no mechanism for the app to know whether the student actually tried before asking for help, produced a meaningful explanation, or just clicked through to completion.

The bigger gap: the app has no way for a student to **struggle productively** with a problem. The research is strong here — a 2021 meta-analysis found moderate effects favoring problem-solving-first over instruction-first, with stronger effects when designs followed Productive Failure principles. IES recommends interleaving worked examples with problem solving, using retrieval practice, and asking deep explanatory questions. The Harvard physics AI-tutor paper found their system worked not because it was an open chatbot, but because it used sequential scaffolding and step-by-step guidance — prompt engineering alone was not reliable enough.

This phase adds: productive struggle as a first-class block type with a hint ladder, artifact collection so the app records what the student produced, process verification so it knows *how* blocks were completed, teach-the-tutor mode, and coach integration into block execution (not a sidebar chat).

## Goals

- Add productive struggle as a first-class block type with time-gated hint ladder
- Generalize practice items (warm-ups, exit tickets, transfer problems) to all block types
- Collect student artifacts with process metadata (not just completion timestamps)
- Track *how* blocks were completed: hint usage, time-to-first-hint, artifacts produced
- Integrate the coach into block step execution (step-aware, hint-budget-aware)
- Add teach-the-tutor mode where the student explains and the AI probes gaps
- Enforce soft completion gates (required artifacts visible, but student always in control)

## Work items

### 1. Productive struggle block type

Add `productive_failure` to `BlockType` in `allocator.py`.

**Protocol (25–35 min):**

1. **Cold attempt** — Present the problem. No hints, no sources, no coach help. Timer starts. Minimum 5–6 minutes before anything unlocks.
2. **First stuck point** — Student writes what they tried and where they got stuck (artifact: `stuck_point`)
3. **Self-explanation prompt** — "Why did you choose that approach? What were you expecting to happen?"
4. **Hint 1** — Unlocks after minimum attempt time. Conceptual nudge, not procedural. ("Think about what happens when X changes")
5. **Hint 2** — Unlocks if still stuck after Hint 1 (minimum 1 min between hints). Partial worked example — first 2–3 steps only.
6. **Full worked example** — Last resort. Student must explain what they missed before moving on.
7. **Isomorphic problem** — Student solves a structurally similar problem to test transfer.
8. **Unassisted transfer** — One final problem with no hints available.

The critical constraint: **hints don't unlock until the student has spent minimum time on the cold attempt.** This prevents "click hint immediately" behavior.

**Allocator integration:**
- Use for math/science courses when the opportunity is homework or assessment prep
- Preferred when energy >= 3 (productive struggle requires cognitive effort)
- At low energy (1–2), prefer worked_example instead
- Replace some worked_example allocations with productive_failure for appropriate courses

**Guide compiler integration:**
- The compiler generates the problem, hints, worked example, and transfer problems during plan compilation
- Hints stored in `steps_json` but flagged as locked (`locked: true, unlock_after_minutes: 5`)

### 2. Hint ladder system

Create `mitty/guides/hints.py`.

**Hint levels per block:**

| Level | Content | Unlock condition |
|-------|---------|-----------------|
| 0 | Problem only (cold attempt) | Immediately |
| 1 | Conceptual hint | After `min_attempt_minutes` (default 5) |
| 2 | Procedural hint | 1 min after Level 1 accessed |
| 3 | Partial worked example (first 2–3 steps) | 1 min after Level 2 accessed |
| 4 | Full worked example with annotations | 1 min after Level 3 accessed |

The student can always skip a level (tracked as `hint_skipped`). They can also choose to stay at their current level and keep working.

**Hint generation:** the guide compiler generates all hint levels during plan compilation. Store in `steps_json` with `hint_level` metadata. If LLM unavailable, fall back to generic hints ("Re-read the relevant section in your notes").

**Tracking per block:**
- `hints_requested`: count of hints the student actually viewed
- `max_hint_level`: highest level accessed (0 = solved without hints)
- `time_to_first_hint_seconds`: how long they worked before requesting help
- `hints_skipped`: count of levels skipped

Store on `block_artifacts` or as additional columns on `study_blocks`.

### 3. Generalize practice to all block types

Currently, practice items only work for retrieval blocks via `practice_sessions.py`.

Extend so every block type can generate and evaluate practice:

| Block type | Practice usage |
|------------|---------------|
| Plan | 2–3 warm-up items (test prior knowledge, establish baseline) |
| Retrieval | Main practice items (existing behavior, unchanged) |
| Worked example | Isomorphic practice problem after studying the example |
| Deep explanation | Comprehension check question after reading/summarizing |
| Productive struggle | Cold-attempt problem + isomorphic transfer + unassisted transfer |
| Reflection | Exit ticket items (unassisted, on weakest concept) |

Wire the guide's `warmup_items_json` and `exit_items_json` into the practice evaluation pipeline:
- Answers stored in `practice_results` with `study_block_id`
- Evaluated by the existing evaluator (exact-match or LLM)
- Fed into mastery updates

Add `step_context` field to `practice_results`:
- `warmup` — Plan block warm-up
- `main` — Retrieval block practice (existing)
- `exit_ticket` — Reflection exit ticket
- `cold_attempt` — Productive struggle initial attempt
- `transfer` — Productive struggle isomorphic/unassisted problem
- `comprehension` — Deep explanation check question
- `isomorphic` — Worked example practice problem

This field is critical for Phase 8: distinguishing **unassisted performance** (cold_attempt, exit_ticket, transfer) from **assisted performance** (main, comprehension) is the real signal for whether learning is happening.

### 4. Artifact collection formalization

Extend Phase 6's `block_artifacts` table with process metadata:

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| block_id | FK → study_blocks | |
| step_number | int | which step produced this |
| artifact_type | text | |
| content_json | JSONB | flexible payload |
| hint_level_at_submission | int | what hint level was active when artifact was produced (nullable) |
| time_spent_seconds | int | how long the student spent on this step (nullable) |
| created_at | timestamp | |

New artifact types beyond Phase 6:
- `stuck_point` — what the student tried and where they got stuck
- `self_explanation` — why they chose their approach
- `hint_response` — what the student did after viewing a hint
- `transfer_attempt` — solution to isomorphic/transfer problem
- `teach_back_exchange` — full teach-the-tutor conversation

### 5. Process verification columns on study_blocks

Add columns to `study_blocks` to summarize how each block was completed:

| Column | Type | Notes |
|--------|------|-------|
| hints_used | int | default 0 |
| max_hint_level | int | highest hint level accessed (0–4), nullable |
| time_to_first_hint_seconds | int | nullable — NULL if no hints used |
| artifacts_produced | int | count of artifacts submitted |
| steps_completed | int | count of steps the student completed |
| steps_total | int | total steps in the guide |
| completion_quality | text | `full` / `partial` / `skipped_steps` / `skipped_block` |

Computed when `completeBlock()` is called:
- Count artifacts produced vs. guide's completion criteria
- Check hint usage from artifacts
- Set `completion_quality` based on: all criteria met → `full`, some → `partial`, block skipped → `skipped_block`

Add Supabase migration for new columns.

### 6. Coach as block executor

Refactor the coach from a sidebar chat to a step-aware assistant.

**Current behavior:** Coach invoked via separate "Coach" button, scoped to block topic but unaware of the current step.

**New behavior:**
- Coach receives step context: which step the student is on, what the step expects, what artifacts have been produced so far
- Coach sees the hint budget: how many hints used, what level is currently unlocked
- Coach respects the hint ladder: during a cold attempt, the coach asks questions ("What have you tried so far?") instead of explaining
- Coach can prompt for teach-back: "Can you explain [concept] back to me?"
- Coach tracks whether it guided the student or gave the answer

**Implementation:**
- Pass `step_context` (current step number, step_type, hint_level_unlocked) and `artifacts_so_far` to `coach_chat()`
- Update the coach system prompt to be step-aware:
  - During `cold_attempt` steps: "The student is working without help. Ask questions to help them think, but do NOT explain the concept or give hints. Say things like 'What have you tried?' or 'What do you think happens next?'"
  - During `hint` steps: "The student has requested help. Give a hint at level {N}, not a full explanation."
  - During `teach_back` steps: "The student is explaining the concept to you. Act as a naive learner. Ask probing follow-up questions. Identify gaps in their explanation."
- Add `guidance_level` field to `coach_messages`: `question`, `hint`, `nudge`, `explanation`, `answer_given`
- The guidance_level is self-reported by the LLM in structured output — imperfect but useful for tracking the coach's behavior

### 7. Teach-the-tutor mode

New interaction mode, primarily used in reflection blocks and optionally in other blocks:

**Flow:**
1. Student is prompted: "Teach me about [concept] — pretend I know nothing"
2. Student writes their explanation (artifact: `teach_back`)
3. Coach (acting as a naive learner) asks 2–3 follow-up questions probing gaps:
   - "You mentioned X — why does that happen?"
   - "What about Y? Is that related?"
   - "You didn't mention Z — is that important?"
4. Student revises or elaborates
5. Coach gives feedback on completeness and accuracy, citing source material

**Tracking per teach-back:**
- `initial_completeness`: fraction of key concepts the student mentioned unprompted (LLM-assessed)
- `revision_count`: how many times the student elaborated after probing
- `final_completeness`: fraction after revisions

Store the full exchange as a single `teach_back_exchange` artifact with the structured metadata.

This is the highest-leverage single intervention for deep learning: articulating understanding forces the student to notice gaps they didn't know they had. IES-funded work on teachable agents confirmed this approach supports metacognition and science learning.

### 8. Completion gates in UI

Update the study plan UI:

**Visible criteria:** each block card shows its completion requirements:
- "Answer warm-up questions / Set tonight's goals" (Plan)
- "Attempt the problem before requesting hints" (Productive struggle)
- "Submit exit ticket / Write teach-back" (Reflection)

**Soft enforcement:**
- "Done" button is always visible (the student is always in control)
- If criteria are not met, show: "You haven't completed [X yet]. Finish, or skip this step?"
- Progress within a block: "Step 3 of 5 completed" with a mini progress bar

**Step-level UI updates:**
- Locked hints show a countdown: "Hint available in 2:30" during cold attempts
- Unlock animation when a hint becomes available
- Completed steps show a checkmark with the artifact summary
- Current step is highlighted / expanded

This is encouragement, not punishment. The student should feel guided and supported, never trapped.

## Acceptance criteria

- [ ] Productive struggle block type works end-to-end: cold attempt → stuck point → hints → transfer
- [ ] Hint ladder respects time gates (hints don't unlock early)
- [ ] Hint usage tracked per block (hints_used, max_hint_level, time_to_first_hint)
- [ ] Practice items work in all block types (warm-ups, comprehension checks, exit tickets)
- [ ] `practice_results.step_context` distinguishes warmup / main / exit_ticket / cold_attempt / transfer
- [ ] Artifacts collected for all artifact-producing steps with process metadata
- [ ] Process verification columns on study_blocks populated on completion
- [ ] `completion_quality` computed correctly (full / partial / skipped_steps)
- [ ] Coach is step-aware: knows current step, hint budget, artifacts produced
- [ ] Coach respects hint ladder during cold-attempt steps (asks questions, doesn't explain)
- [ ] Coach guidance_level tracked per message
- [ ] Teach-the-tutor mode works: student explains, coach probes, student revises
- [ ] Teach-back completeness tracked (initial and final)
- [ ] Completion gates visible in UI with soft enforcement
- [ ] Locked hints show countdown timer during cold attempts
- [ ] All schema changes have Supabase migrations
- [ ] Mobile-friendly: text inputs comfortable, step navigation thumb-friendly
- [ ] Thorough tests for hint ladder, artifact collection, and process verification
- [ ] Quality gates pass

## Risks & open questions

- **Friction** — Too many required artifacts will feel like homework about homework. Keep required artifacts to 2–3 per block. Make everything else optional. Watch for session abandonment as a signal.
- **Cold-attempt minimum time** — 5 minutes can feel long when stuck. Start with 5 min, make it configurable, and consider reducing to 3 min if students consistently abandon blocks before hints unlock.
- **Coach prompt complexity** — Step-aware coaching adds significant system prompt complexity. Test carefully that the coach doesn't become confused or overly rigid. The structured output for guidance_level helps but isn't perfect.
- **LLM cost for teach-the-tutor** — Multi-turn exchanges add up. Budget 3–5 turns per teach-back. Set a hard turn limit and summarize at the end.
- **Mobile text input** — Typing explanations on a phone is painful. Keep required text inputs short (3–5 sentences). Consider voice-to-text as a future enhancement, but don't block on it.
- **Gaming** — Student could type gibberish to satisfy artifact requirements. The evaluator and coach can catch obvious gaming, but some will slip through. Prioritize measuring *outcomes* (unassisted performance, delayed recall) over *compliance* (artifact count).
- **Productive struggle for non-STEM** — The hint ladder is most natural for math/science. For humanities, "hints" might mean "guiding questions" or "source excerpts." The Phase 8 subject-specific protocols will handle this; for now, use generic hint framing.

## Dependencies

- Phase 6: guide data model, guide compiler, source bundles, step-driven UI, block_artifacts table
- Phase 4: practice generator + evaluator (extended to all block types)
- Phase 5: coach (refactored for step-awareness), AI client
