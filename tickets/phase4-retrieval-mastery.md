# Phase 4: Retrieval Practice + Mastery Tracking

## Context

This is where the app becomes a learning tool, not just a planner. Grades and due dates are lagging signals — they tell you what already happened. A real study helper needs leading signals: what the student can actually retrieve, where she gets stuck, what she misexplains, and the gap between what she thinks she knows and what she can do.

The IES practice guide specifically recommends: use quizzing to promote retrieval, help students allocate study time using quiz results, and interleave worked examples with problem solving. This phase implements all of those.

This phase includes lightweight LLM integration for concept extraction, practice generation, and answer evaluation — areas where template/keyword approaches would produce throwaway code that Phase 5 replaces. The LLM client here is intentionally simple; Phase 5 adds the full infrastructure (prompt versioning, audit logging, cost budgeting, conversational coach).

## Goals

- Build LLM-powered concept extraction so the system knows what topics exist per course
- Implement spaced repetition scheduling for review timing
- Generate practice items (quizzes, flashcards, worked examples, explanations) via LLM
- Build the practice session UI for retrieval blocks
- Score answers with LLM evaluation (not just keyword matching)
- Update mastery states from practice results
- Track and surface confidence calibration (what she thinks she knows vs. what she can do)

## The mastery loop

```
Concepts extracted from assignments/resources (LLM-assisted)
    ↓
Spaced repetition scheduler determines what to review
    ↓
Practice generator creates items via LLM + resource chunks
    ↓
Student does practice during retrieval block
    ↓
LLM evaluates answers (partial credit, misconception detection)
    ↓
Results update mastery_states
    ├── mastery_level adjusts up/down
    ├── success_rate updates (rolling)
    ├── confidence calibration tracked
    └── next_review_at recalculated
    ↓
Planner uses updated mastery for tomorrow's plan
```

## Work items

### 1. Lightweight LLM client

Create `mitty/ai/client.py`.

A minimal Claude API wrapper — just enough to power concept extraction, practice generation, and answer evaluation. Phase 5 adds the full infrastructure.

**Scope:**
- Claude API integration via `anthropic` SDK (async)
- Structured output via tool use / JSON mode
- Simple token counting and cost logging (log level, not database — Phase 5 adds `ai_audit_log` table)
- Retry logic for transient errors (429, 5xx) with exponential backoff
- Config: `ANTHROPIC_API_KEY` env var, model selection in `config.py`

**Explicitly deferred to Phase 5:**
- Prompt versioning
- Database audit logging (`ai_audit_log` table)
- Rate limiting infrastructure
- Cost budgeting / alerts
- Input sanitization / prompt injection defense (Phase 4 is single-user, server-side only)

### 2. LLM-powered concept extraction

Create `mitty/mastery/concepts.py`.

Extract concept/topic tags from available data using a hybrid approach:

| Source | Extraction method |
|--------|------------------|
| Assignment names | LLM extracts topics from name + context ("Ch.7 Quiz" → "Chapter 7: Cellular Respiration") |
| Assessment unit_or_topic | Direct (already tagged at entry) |
| Module names | LLM enriches module titles with subtopics |
| Resource chunks | LLM extracts key concepts from chunk content |
| Manual tagging | Parent/student adds concept tags to courses |

The LLM call is batched — send a course's worth of assignment names, module titles, and chunk summaries in one call, get back a structured list of concepts with relationships.

Output: populate `mastery_states` with `(course_id, concept)` pairs, initial `mastery_level = 0.5` (unknown).

**Fallback**: If LLM is unavailable or resource chunks are empty, fall back to simple pattern extraction (chapter numbers, bolded terms, module titles verbatim). This ensures the system works without API access.

### 3. Spaced repetition scheduler

Create `mitty/mastery/scheduler.py`.

Implement a simple SM-2 variant:

```python
def calculate_next_review(
    mastery_level: float,     # 0.0 - 1.0
    success_rate: float,      # rolling accuracy
    retrieval_count: int,     # how many times practiced
    last_retrieval_at: datetime,
) -> datetime:
    """
    High mastery + consistent success → longer interval (days/weeks)
    Low mastery or recent failure → shorter interval (hours/1 day)
    New concept (count=0) → review today
    """
```

Interval progression example:
- First correct: review in 1 day
- Second correct: review in 3 days
- Third correct: review in 7 days
- Each incorrect answer: reset interval to 1 day
- Mastery below 0.3: always review daily

The planner (Phase 3) filters `mastery_states WHERE next_review_at <= today` to select concepts for retrieval blocks.

### 4. LLM practice generator

Create `mitty/practice/generator.py`.

Given `(concept, resource_chunks[], mastery_level)`, call Claude to generate practice items:

| Practice type | What LLM generates |
|---------------|-------------------|
| Multiple choice | Question + 4 options (1 correct, 3 plausible distractors) + explanation |
| Fill-in-the-blank | Key sentence with blanked term + answer |
| Short answer | Factual question + expected answer + grading rubric |
| Flashcard | Term/concept + definition/explanation |
| Worked example | Step-by-step solved problem + similar problem for student |
| Explanation prompt | "Explain why..." / "Compare..." / "What would happen if..." + rubric |

Requirements:
- Every generated question must cite its source chunk(s)
- Difficulty scales with `mastery_level` (low mastery = simpler, more scaffolded)
- Vary question format within a session to avoid pattern matching
- Return structured data (Pydantic models) — not free-form text
- **No source = no practice**: If resource chunks are insufficient for a concept, return a "needs resources" indicator instead of generating from nothing

**Caching**: Generated practice items are stored in `practice_items` table. Re-generation only when mastery level changes significantly or items are exhausted. This keeps LLM costs low — generate a batch per concept, use them across sessions.

### 5. LLM answer evaluator

Create `mitty/practice/evaluator.py`.

Score student answers using Claude:

| Input type | Evaluation approach |
|-----------|-------------------|
| Multiple choice / fill-in-blank | Exact match first; LLM fallback for reasonable variations ("cellular resp" for "cellular respiration") |
| Short answer | LLM scores against rubric: correct, partially correct, incorrect |
| Explanation | LLM assesses completeness, accuracy, depth — partial credit |
| Worked example steps | LLM checks method + answer correctness |

Returns:
- `is_correct` (bool)
- `score` (0.0 - 1.0, for partial credit)
- `feedback` (text — what was right, what was missed, what to review)
- `misconceptions_detected` (list — "You confused X with Y")

**Cost optimization**: Multiple choice and fill-in-blank use exact match first. LLM only called when exact match fails or for free-text answers. This means most quiz answers never hit the API.

### 6. Practice session UI

Launched from a retrieval block in the study plan:

```
┌──────────────────────────────────────────┐
│  Retrieval: Biology Ch.7  (20 min)       │
│  ━━━━━━━━━━━━━━━━━━ 3/8 questions        │
│                                          │
│  How confident are you?                  │
│  ○ Not at all  ○ A little  ● Mostly      │
│  ○ Very  ○ Completely                    │
│                                          │
│  Q: The process by which cells convert   │
│  glucose into ATP is called ________     │
│                                          │
│  [Your answer: ________________]         │
│                                          │
│  [Check Answer]                          │
│                                          │
│  ── After answering ──                   │
│                                          │
│  ✓ Correct! Cellular respiration         │
│  Source: Bio textbook Ch.7, p.142        │
│                                          │
│  [Next Question]                         │
└──────────────────────────────────────────┘
```

Flow per question:
1. Show confidence prompt ("How sure are you?") — captures `confidence_before`
2. Show question
3. Student answers (type, select, or explain)
4. LLM evaluates → immediate feedback: correct/incorrect + explanation + source citation
5. Track: `is_correct`, `score`, `confidence_before`, `time_spent_seconds`, `misconceptions`

End of block summary:
- X/Y correct
- Concepts to review (incorrect ones)
- Confidence calibration: "You were confident on 3 questions you got wrong"
- POST all results to `practice_results` endpoint

### 7. Mastery state updater

Create `mitty/mastery/updater.py`.

After each practice session, update `mastery_states`:

```python
def update_mastery(concept: str, course_id: int, results: list[PracticeResult]):
    # mastery_level: weighted moving average
    # - Correct answer: move toward 1.0 (weight recent results more)
    # - Incorrect: move toward 0.0
    # - Partial credit scores contribute proportionally
    # - Unassisted correct counts more than assisted

    # success_rate: rolling accuracy over last N attempts

    # retrieval_count: increment

    # confidence_self_report: average of recent confidence_before ratings

    # next_review_at: recalculate via scheduler

    # last_retrieval_at: now
```

The gap between `confidence_self_report` and `success_rate` is a key signal:
- High confidence + low accuracy = **false confidence** (needs extra attention)
- Low confidence + high accuracy = **under-confidence** (positive reinforcement)

### 8. Confidence calibration tracking

Surface calibration data throughout the app:

| Location | What to show |
|----------|-------------|
| Practice session summary | "You were confident on 3 questions you got wrong" |
| Mastery dashboard (per concept) | Calibration indicator: well-calibrated / over-confident / under-confident |
| Planner input | `confidence_gap` feeds into priority scoring (Phase 3) |
| Parent dashboard (Phase 6) | "She thinks she knows Bio Ch.7, but accuracy is 40%" |

Calibration metric: `confidence_self_report - success_rate`
- Near 0: well-calibrated
- Positive (> 0.2): over-confident (thinks she knows it, doesn't)
- Negative (< -0.2): under-confident (knows it, doesn't think she does)

### 9. Mastery dashboard view

Add to the frontend:

```
┌──────────────────────────────────────────┐
│  Mastery: AP US History                  │
│                                          │
│  Topic 7.11: Progressive Era             │
│  ████████████░░░░░░ 65%  · Review today  │
│  ⚠ Over-confident (says 90%, scores 65%) │
│                                          │
│  Topic 7.10: Imperialism                 │
│  ██████████████████ 85%  · Review in 3d  │
│  ✓ Well calibrated                       │
│                                          │
│  Topic 7.9: Gilded Age                   │
│  ████░░░░░░░░░░░░░░ 25%  · Review today │
│  No study materials                      │
│                                          │
│  Topic 7.12: World War I                 │
│  ░░░░░░░░░░░░░░░░░░  0%  · Not started  │
│  📝 Test in 5 days                       │
└──────────────────────────────────────────┘
```

Per concept: mastery bar, last practiced, next review, calibration indicator, resource coverage ("No study materials" = needs resources added).

Sortable by: mastery level, next review date, course, calibration gap.

### 10. Canvas discussion topics + announcements ingestion

Discussions and announcements are a rich source of study content — teachers often post study guides, exam tips, and supplementary explanations there. Canvas exposes these fully via REST API:

- `GET /api/v1/courses/:id/discussion_topics` — lists all discussions and announcements
- `GET /api/v1/courses/:id/discussion_topics/:id/view` — full thread with all entries

Work items:
- Fetch discussion topics per course (title, message body, posted_at, author)
- Store as resources with `resource_type='discussion'` (add to ResourceType enum)
- Strip HTML from message bodies using the same bs4 pipeline from Phase 2
- Feed into the chunking pipeline for concept extraction
- Include announcement-type topics (Canvas uses `is_announcement` flag)
- Add tests with mocked responses

This extends Phase 2's ingestion pattern into a new content type, but it's deferred here because concept extraction (work item 2) is its primary consumer.

## Acceptance criteria

- [ ] Lightweight LLM client calls Claude API with structured output and retry logic
- [ ] Concepts extracted from assignments and resources using LLM (with pattern-matching fallback)
- [ ] Spaced repetition scheduler produces sensible review intervals
- [ ] LLM practice generator produces quality questions with citations from resource chunks
- [ ] LLM evaluator scores answers with partial credit and misconception detection
- [ ] Practice session UI works end-to-end (confidence → question → answer → LLM feedback → results stored)
- [ ] Mastery states update after practice sessions
- [ ] Confidence calibration calculated and surfaced (over-confident / under-confident / calibrated)
- [ ] Mastery dashboard shows per-concept progress with calibration indicators
- [ ] Worked example exercises display step-by-step solutions then prompt for practice
- [ ] Explanation exercises accept free-text answers with LLM scoring
- [ ] Practice results feed back into planner scoring (mastery_gap, confidence_gap)
- [ ] Generated practice items cached to minimize LLM costs
- [ ] System works (degraded) without LLM access (pattern-based concept extraction, exact-match scoring)
- [ ] Tests for scheduler, updater, generator, evaluator, and calibration logic
- [ ] Quality gates pass

## Risks & open questions

- **LLM cost** — Practice generation + evaluation per session adds up. Mitigations: cache generated items, exact-match before LLM evaluation, batch concept extraction. Track cost per session even with simple logging.
- **Concept granularity** — "Biology Ch.7" vs "cellular respiration" vs "ATP synthesis" — how fine-grained? Start coarse (chapter/unit level) and let LLM suggest finer breakdowns as resource coverage improves.
- **Cold start** — Without resources to extract from, practice items will be sparse. The "needs resources" indicator surfaces this clearly. Manual resource upload (Phase 2) is the workaround.
- **LLM evaluation accuracy** — The evaluator may over- or under-score. Log scores and student feedback for tuning. For now, emphasize that the practice itself is the learning activity, even if scoring has rough edges.
- **Student engagement** — Practice must feel productive, not punitive. Celebrate correct answers, be gentle on incorrect ones, show progress clearly. LLM-generated feedback should be encouraging and specific.
- **API availability** — If Claude API is down, practice sessions should still work with cached items and exact-match scoring. Degrade gracefully.

## Dependencies

- Phase 1: schema (mastery_states, practice_results tables)
- Phase 2: resources + resource_chunks (content to generate practice from)
- Phase 3: planner (retrieval blocks that launch practice sessions)
- `ANTHROPIC_API_KEY` environment variable configured
