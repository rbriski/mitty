# Phase 8: Subject-Specific Protocols & Adaptive Targeting

## Context

Phases 6 and 7 built the executable lesson infrastructure: guides, source bundles, artifacts, hint ladders, verification, and coach integration. But the guide compiler uses the same protocol template regardless of subject. A pre-calc problem set and a US history essay need fundamentally different study approaches. And the planner still reasons at the course level ("Biology is weak") instead of the concept level ("light-dependent reactions are weak, but cell structure is solid").

This phase adds domain-specific intelligence and closes the adaptive loop: yesterday's weak concepts automatically appear in today's plan, misconceptions are tracked and targeted, and the system generates transfer problems — not just recall — to test whether learning actually stuck.

IES recommends combining graphics with verbal descriptions, connecting abstract and concrete representations, and using interleaved practice. Self-explanation prompts improve learning more when scaffolded and when students explain why incorrect information is wrong (ScienceDirect, 2024). All of this requires subject-aware protocols, not one-size-fits-all templates.

## Goals

- Build subject-specific protocol compilers for math/science, humanities, essay writing, and foreign language
- Move planner targeting from course-level to concept-level
- Add misconception-level tracking and targeting across evaluator, coach, and self-report
- Implement delayed retrieval (tomorrow's plan automatically retests yesterday's weak concepts)
- Generate transfer problems (near, far, negative) to test application, not just recall
- Track calibration (confidence vs. performance) over time to detect and correct overconfidence

## Work items

### 1. Subject-specific protocol compilers

Create `mitty/guides/protocols/` package:

```
mitty/guides/protocols/
├── __init__.py
├── base.py              # Protocol interface + fallback generic compiler
├── math_science.py      # Math, physics, chemistry, pre-calc, etc.
├── humanities.py        # History, social studies, literature
├── essay_writing.py     # English/language arts essay assignments
└── language.py          # Foreign language courses
```

Each module exports `compile_steps(block_type, concepts, source_bundle, mastery_data, misconceptions) -> list[Step]`.

#### Math/Science protocols

- **Productive failure:** present problem → cold attempt → self-explain → hint ladder → isomorphic transfer
- **Worked example comparison:** study solution → identify strategy → attempt variation → compare approaches
- **Step audit:** show student's previous incorrect work (from practice_results), have them find and fix the error
- **Formula/rule retrieval:** closed-book recall of formulas → check → apply to novel problem

Key difference from generic: heavy emphasis on **step-by-step procedural work**, showing scratch work, and identifying *where* in the procedure the error occurred.

#### Humanities protocols

- **Claim-evidence-reasoning:** make a claim → find evidence from sources → explain reasoning → evaluate strength
- **Source analysis:** read primary source → answer sourcing questions (who wrote this? when? why? for what audience?)
- **Compare/contrast:** two events, perspectives, or concepts → structured comparison using source material
- **Timeline/process reconstruction:** order events from memory → check against sources → fill gaps

Key difference: emphasis on **evidence-based argumentation** and source evaluation, not procedural steps.

#### Essay/Language Arts protocols

- **Outline from memory:** write thesis + 3 supporting points without notes → compare to assignment requirements
- **Thesis critique:** read a weak sample thesis → improve it → justify changes with rubric criteria
- **Evidence selection:** given a claim, select the strongest evidence from source bundle → explain why it's strongest
- **Revision against rubric:** apply rubric criteria to own or sample writing → identify gaps → revise

Key difference: emphasis on **structured writing process** and rubric alignment.

#### Foreign Language protocols

- **Vocabulary retrieval:** target language → native meaning → use in original sentence → self-check
- **Grammar drill:** apply grammar rule to novel sentences (not memorized examples) → check conjugation/agreement
- **Error correction:** find and fix grammar/vocabulary errors in sample text
- **Oral teach-back:** explain the grammar rule in your own words → demonstrate with 3 example sentences

Key difference: emphasis on **production** (generating language, not just recognizing it) and pattern application.

#### Protocol selection

Select the compiler based on course metadata. Add `subject_area` field to courses/enrollments if not present:

1. Try `course.subject_area` (if manually set)
2. Fall back to regex heuristics on course name:
   - `/math|calc|algebra|geometry|trig|statistics/i` → math_science
   - `/physics|chemistry|biology|science|anatomy|environmental/i` → math_science
   - `/history|government|civics|economics|psych|sociology/i` → humanities
   - `/english|writing|composition|literature|rhetoric/i` → essay_writing
   - `/spanish|french|german|latin|chinese|japanese|mandarin/i` → language
3. Fall back to `base.py` generic compiler

### 2. Concept-level planner targeting

Refactor `mitty/planner/scoring.py` to reason about concepts, not just courses.

**Current:** `_compute_mastery_gaps()` in `generator.py` averages mastery per course. Scoring uses one `mastery_gap` number per course. Blocks get titles like "Review Biology."

**New:** scoring receives concept-level data and uses it for granular targeting.

Extend `StudyOpportunity` with optional concept detail:

```python
@dataclass
class ConceptTarget:
    name: str
    mastery_level: float
    confidence: float | None
    last_reviewed: datetime | None
    next_review_at: datetime | None
    unresolved_misconceptions: int

# On StudyOpportunity:
concepts: list[ConceptTarget] = field(default_factory=list)
```

When concepts are available:
- Score using **worst concept mastery** for the course (not average — average hides weak spots)
- Generate concept-specific block titles: "Review light-dependent reactions" instead of "Review Biology"
- Allocate time proportional to concept weakness: more time for weaker concepts
- Skip well-mastered concepts: don't generate blocks for concepts where `mastery > 0.85` and confidence is calibrated

When concepts are unavailable (cold start): fall back to course-level scoring exactly as today.

### 3. Misconception-level tracking

Create `mitty/mastery/misconceptions.py` + schema.

**`misconception_log` table:**

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| user_id | UUID | |
| course_id | FK → courses | |
| concept | text | which concept this misconception relates to |
| misconception | text | what the student believed |
| correction | text | what's actually true |
| source | text | `evaluator`, `coach`, `student_self_report` |
| times_seen | int | how often this misconception recurred |
| resolved | boolean | default false — true when student demonstrates correct understanding |
| first_seen_at | timestamp | |
| last_seen_at | timestamp | |

**Three input sources:**

1. **Practice evaluator:** `misconceptions_detected` from LLM evaluation already exists in `practice_results`. Extract unique misconceptions and upsert to the log, incrementing `times_seen`.
2. **Coach:** misconceptions identified during coaching exchanges. Add a `misconceptions_identified` field to coach structured output. Extract and upsert.
3. **Student self-report:** misconception log artifacts from reflection blocks (Phase 6/7). Parse the "what I thought / why it was wrong / corrected rule" structure and upsert.

**Integration with guides:**
- Guide compiler queries `misconception_log` for unresolved misconceptions in the target concept
- Uses them to generate targeted questions: "Last time you confused mitosis with meiosis — which process results in genetically identical cells?"
- Misconceptions with `times_seen >= 2` get priority targeting (single occurrences may be noise)

**Integration with planner:**
- Add `unresolved_misconceptions` count to `ConceptTarget`
- Concepts with unresolved misconceptions get a scoring boost

**Resolution:**
- When the student correctly answers a question that specifically targets a misconception (tracked via artifact metadata), mark the misconception as `resolved = true`
- If it recurs later, reopen it (`resolved = false`, increment `times_seen`)

### 4. Delayed retrieval

Modify plan generation to automatically include spaced review of prior days' weak concepts.

**Current state:** `mastery_states` has `next_review_at` from the SM-2 scheduler, but the planner doesn't use it for block compilation — it only uses upcoming assignments and assessments as opportunities.

**New behavior:**

1. During plan generation, query `mastery_states WHERE next_review_at <= today AND mastery_level < 0.85`
2. Create "spaced review" opportunities from these — they don't correspond to any assignment, just concepts that need reinforcement
3. Score them with a new `W_SPACED_REVIEW` weight (medium priority — below urgent homework, above general practice)
4. The guide compiler generates retrieval-focused guides for spaced review blocks: closed-book recall → self-check → targeted practice
5. After completion: update mastery based on results. If correct, extend `next_review_at` (scheduler computes new interval). If incorrect, reset to 1 day.

Add `is_spaced_review` boolean to `study_blocks` so the UI labels them distinctly:
- "Review from Tuesday: light-dependent reactions"
- Different icon/color to distinguish from assignment-driven blocks

This closes the core learning loop:
```
Exit ticket reveals weak concept
    → mastery updated → scheduler sets next_review_at
    → tomorrow's plan includes spaced review
    → student retested → mastery updated
    → cycle continues until mastered
```

### 5. Transfer problem generation

Create `mitty/practice/transfer.py`.

Transfer problems test whether the student can **apply** a concept in a new context, not just recall it. This is the strongest signal of real learning.

**Transfer types:**

| Type | Description | Example |
|------|-------------|---------|
| `near_transfer` | Same concept, different surface features | Same equation type, different numbers |
| `far_transfer` | Same principle, different domain or framing | Physics momentum applied to economics (supply/demand equilibrium) |
| `negative_transfer` | Looks similar but different concept applies | Problem that looks like multiplication but requires division |

Add `transfer_type` parameter to practice generator:
- `recall` (default, existing behavior)
- `near_transfer`
- `far_transfer`
- `negative_transfer`

**Usage by block type:**

| Block type | Transfer usage |
|------------|---------------|
| Productive struggle | Step 7: isomorphic (near_transfer). Step 8: unassisted (far_transfer) |
| Reflection | Exit ticket: prefer near_transfer over recall |
| Spaced review | Use near_transfer to test retention in new context |
| Worked example | Practice problem: near_transfer after studying example |

Track `transfer_type` in `practice_results` for analysis. Far-transfer success rate is the strongest evidence of deep learning.

**Start with near_transfer** — it's the easiest to generate well. Add far_transfer and negative_transfer incrementally as prompt quality improves.

### 6. Calibration tracking

Create `mitty/mastery/calibration.py` + schema.

**`calibration_snapshots` table:**

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| user_id | UUID | |
| course_id | FK → courses | nullable for overall |
| concept | text | nullable for course-level |
| confidence_avg | float | average confidence rating (normalized 0–1) |
| performance_avg | float | average score |
| calibration_gap | float | confidence - performance (positive = overconfident) |
| sample_size | int | number of items in this snapshot |
| snapshot_date | date | |

**Computed daily** after study session completes:
- Per concept: compare `confidence_before` ratings from `practice_results` with `score`
- Per course: aggregate concept-level calibration
- Overall: aggregate course-level calibration

**Integration with planner:**
- Overconfident concepts (`calibration_gap > 0.2`) get a scoring boost — these are the most dangerous because the student thinks they're fine
- Well-calibrated concepts get normal priority
- Under-confident concepts get slight priority reduction (the student already knows they need help)

**Integration with guides:**
- Plan block calibration display (foundation from Phase 6): now shows historical trend
- "You tend to be overconfident about [concept] — the warm-up will help you check"
- "Your confidence in [concept] matches your performance now — that's good calibration"
- "You're being hard on yourself about [concept] — your scores are better than you think"

**Integration with mastery:**
- `confidence_self_report` on `mastery_states` is already there
- Add `calibration_gap` to `mastery_states` (updated during daily snapshot)
- Use `calibration_gap` as a signal in the guide compiler: overconfident concepts get harder warm-ups, under-confident concepts get encouragement

## Acceptance criteria

- [ ] Subject-specific protocols produce different step structures for math/science vs. humanities vs. essay vs. language
- [ ] Protocol selection works: regex heuristics on course name, manual override via subject_area
- [ ] Generic fallback works when course subject can't be determined
- [ ] Planner scoring uses concept-level mastery when available (worst concept, not average)
- [ ] Planner generates concept-specific block titles ("Review light-dependent reactions" not "Review Biology")
- [ ] Well-mastered concepts (mastery > 0.85 + calibrated confidence) deprioritized
- [ ] `misconception_log` collects from evaluator, coach, and student self-report
- [ ] Misconceptions with `times_seen >= 2` influence guide content
- [ ] Misconception resolution tracked: correct targeted answer → resolved, recurrence → reopened
- [ ] Delayed retrieval: spaced review items appear in today's plan when `next_review_at <= today`
- [ ] Spaced review blocks labeled distinctly in UI ("Review from Tuesday: ...")
- [ ] Spaced review results update mastery and reschedule next_review_at
- [ ] Transfer problems generated (at least near_transfer working reliably)
- [ ] `transfer_type` tracked in `practice_results`
- [ ] Calibration snapshots computed daily per concept + course + overall
- [ ] Overconfident concepts get planner priority boost
- [ ] Calibration display in Plan block shows trend ("You tend to be overconfident about X")
- [ ] All new tables have Supabase migrations
- [ ] Subject protocol can fall back to generic if course subject unknown
- [ ] Thorough tests for each protocol compiler, misconception tracking, and calibration
- [ ] Quality gates pass

## Risks & open questions

- **Subject classification** — Determining course subject from name alone is fragile ("Period 3 Smith" tells us nothing). Regex heuristics will cover most cases, but add a manual subject_area override for edge cases. Don't block plan generation on subject detection — fall back to generic.
- **Concept-level planning complexity** — The planner becomes significantly more complex when reasoning about concepts. Keep the course-level fallback for cold start and ensure the concept-level path is well-tested.
- **Misconception noise** — LLM-detected "misconceptions" will include false positives. Require `times_seen >= 2` before targeting. Let the student dispute misconceptions ("I don't think this is wrong").
- **Transfer problem quality** — Far transfer and negative transfer are genuinely hard to generate well. Start with near_transfer only. Add far_transfer for math/science first where it's most natural. Negative_transfer is the highest quality bar — defer until near and far are reliable.
- **Calibration data density** — Need ~20+ data points per concept for meaningful calibration. Show "not enough data yet" early on. Don't show calibration warnings until sample size is adequate.
- **Over-targeting weaknesses** — Don't let the system become a misconception drill. Balance weakness targeting with reinforcement of strengths. Include "easy win" items in each session for motivation and confidence maintenance.
- **Protocol maintenance** — Four subject-specific compilers is four codepaths to maintain. Keep the interface minimal (`compile_steps()` only) and share as much infrastructure as possible through `base.py`.

## Dependencies

- Phase 6: guide compiler + source bundles + study plan UI (extended with subject protocols)
- Phase 7: artifact collection + process verification + coach integration (data sources for calibration + misconception tracking)
- Phase 4: practice generator + evaluator (extended for transfer types), mastery tracking + scheduler
- Phase 5: AI client (for subject-specific prompt templates)
- Phase 3: planner scoring + allocation (refactored for concept-level targeting)
