# Phase 4: Retrieval Practice + Mastery Tracking

## Context

This is where the app becomes a learning tool, not just a planner. Grades and due dates are lagging signals — they tell you what already happened. A real study helper needs leading signals: what the student can actually retrieve, where she gets stuck, what she misexplains, and the gap between what she thinks she knows and what she can do.

The IES practice guide specifically recommends: use quizzing to promote retrieval, help students allocate study time using quiz results, and interleave worked examples with problem solving. This phase implements all of those.

## Goals

- Build concept extraction so the system knows what topics exist per course
- Implement spaced repetition scheduling for review timing
- Generate practice items (quizzes, flashcards, worked examples, explanations) from templates
- Build the practice session UI for retrieval blocks
- Update mastery states from practice results
- Track and surface confidence calibration (what she thinks she knows vs. what she can do)

## The mastery loop

```
Concepts extracted from assignments/resources
    ↓
Spaced repetition scheduler determines what to review
    ↓
Practice generator creates items for those concepts
    ↓
Student does practice during retrieval block
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

### 1. Concept extraction

Create `mitty/mastery/concepts.py`.

Extract concept/topic tags from available data:

| Source | Extraction method |
|--------|------------------|
| Assignment names | Keyword/pattern extraction ("Ch.7", "quadratic equations", "The Great Depression") |
| Assessment unit_or_topic | Direct (already tagged at entry) |
| Module names | Direct (Canvas module titles often map to units) |
| Resource content | Keyword extraction from chunk text |
| Manual tagging | Parent/student adds concept tags to courses |

Start simple — keyword extraction, course-unit mapping, manual tagging. LLM-powered extraction comes in Phase 5.

Output: populate `mastery_states` with `(course_id, concept)` pairs, initial `mastery_level = 0.5` (unknown).

### 2. Spaced repetition scheduler

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

### 3. Template-based practice generator

Create `mitty/practice/generator.py`.

Generate practice items without LLM (templates only):

| Practice type | Template approach |
|---------------|------------------|
| Fill-in-the-blank | Extract key sentence from resource chunk, blank out key term |
| Term flashcard | Extract bolded/defined terms from content → term + definition |
| True/false | Take a factual statement from content, optionally negate it |
| Multiple choice | Correct answer from content + distractors from related concepts |
| Worked example | Show solved problem step-by-step, then present similar problem |
| Explanation prompt | "Explain why X works" / "Compare X and Y" / "What would happen if..." |

Each generated item includes:
- `question_text`, `correct_answer`, `practice_type`
- `concept` tag (what mastery_state this tests)
- `source_resource_id` (for citation)

Quality will be limited without LLM — that's fine. The structure and tracking matter more than question quality at this stage.

### 4. Practice session UI

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
4. Immediate feedback: correct/incorrect + explanation + source citation
5. Track: `is_correct`, `confidence_before`, `time_spent_seconds`

End of block summary:
- X/Y correct
- Concepts to review (incorrect ones)
- Confidence calibration: "You were confident on 3 questions you got wrong"
- POST all results to `practice_results` endpoint

### 5. Mastery state updater

Create `mitty/mastery/updater.py`.

After each practice session, update `mastery_states`:

```python
def update_mastery(concept: str, course_id: int, results: list[PracticeResult]):
    # mastery_level: weighted moving average
    # - Correct answer: move toward 1.0 (weight recent results more)
    # - Incorrect: move toward 0.0
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

### 6. Confidence calibration tracking

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

### 7. Mastery dashboard view

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

### 8. Worked example + explanation exercises

Beyond quiz/flashcard, two more practice types:

**Worked examples** (IES evidence: interleave worked examples with problems):
- Show a fully solved problem step-by-step
- Then present a similar problem for the student to solve
- Track each step: did she follow the method correctly?
- Best for math/science courses

**Explanation prompts** (IES evidence: ask deep explanatory questions):
- "Explain why [concept] works this way"
- "Compare [concept A] and [concept B]"
- "What would happen if [condition changed]?"
- Student writes a short answer
- For now: score with simple keyword/rubric matching (LLM scoring in Phase 5)
- Even without good scoring, the act of writing an explanation is the learning activity

### 9. Canvas discussion topics + announcements ingestion

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

This extends Phase 2's ingestion pattern into a new content type, but it's deferred here because concept extraction (work item 1) is its primary consumer.

## Acceptance criteria

- [ ] Concepts extracted from assignments and resources for at least one course
- [ ] Spaced repetition scheduler produces sensible review intervals
- [ ] Template generator produces practice items for quiz, flashcard, true/false, multiple choice
- [ ] Practice session UI works end-to-end (confidence → question → answer → feedback → results stored)
- [ ] Mastery states update after practice sessions
- [ ] Confidence calibration calculated and surfaced (over-confident / under-confident / calibrated)
- [ ] Mastery dashboard shows per-concept progress with calibration indicators
- [ ] Worked example exercises display step-by-step solutions then prompt for practice
- [ ] Explanation exercises accept free-text answers with basic scoring
- [ ] Practice results feed back into planner scoring (mastery_gap, confidence_gap)
- [ ] Tests for scheduler, updater, generator, and calibration logic
- [ ] Quality gates pass

## Risks & open questions

- **Concept granularity** — "Biology Ch.7" vs "cellular respiration" vs "ATP synthesis" — how fine-grained? Start coarse (chapter/unit level) and let it get more specific over time.
- **Template quality** — Template-generated questions will be mediocre. That's OK — the retrieval practice itself is the value, not question polish. Phase 5 LLM generation will improve quality significantly.
- **Cold start again** — Without resources to extract from, practice items will be sparse. Manual resource upload (Phase 2) is the workaround.
- **Explanation scoring** — Simple keyword matching will under-score good novel explanations and over-score keyword-stuffed bad ones. Phase 5 LLM evaluator fixes this. For now, emphasize that writing the explanation is the practice, even if scoring is imperfect.
- **Student engagement** — Practice must feel productive, not punitive. Celebrate correct answers, be gentle on incorrect ones, show progress clearly.

## Dependencies

- Phase 1: schema (mastery_states, practice_results tables)
- Phase 2: resources + resource_chunks (content to generate practice from)
- Phase 3: planner (retrieval blocks that launch practice sessions)
