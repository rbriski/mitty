# Phase 3: Student Check-in + Deterministic Daily Planner

## Context

This is the core product. The current app shows grades and homework status — useful, but reactive. A study helper needs to be proactive: "here's what you should study tonight, for how long, and in what order." The planner must be deterministic (no AI), evidence-based (spacing, retrieval, worked examples), and respect the student's available time and energy.

The evidence base is clear: spacing learning over time, interleaving practice with worked examples, low-stakes quizzing, and metacognitive planning all have strong support from IES and EEF research. The planner encodes these principles as scheduling rules.

## Goals

- Build a daily check-in flow where the student reports available time, energy, and blockers
- Build a deterministic priority scoring engine that ranks study opportunities
- Build a time allocation algorithm that produces evidence-based study blocks
- Ship a study plan UI that feels like a focused to-do list

## The nightly plan loop

```
Student check-in (60 sec)
    ↓
Gather inputs
    ├── Assignments due soon
    ├── Upcoming assessments (tests in 1-7 days)
    ├── Late/missing items
    ├── Weak-grade courses (enrollment grades)
    ├── Low-mastery concepts (mastery_states)
    ├── Spaced-review items (next_review_at ≤ today)
    └── Student signals (time, energy, stress, preferences)
    ↓
Score & rank opportunities
    ↓
Allocate into study blocks
    ↓
Present plan → student works through blocks
    ↓
Track execution → feed back into next day's scoring
```

## Work items

### 1. Student daily check-in UI + API
- Simple screen: "How's tonight looking?"
- Fields: available study time (slider or quick picks: 30/60/90/120/150/180 min), energy (1-5), stress (1-5), blockers (optional text), "any class you want to focus on?" (optional)
- Must take under 60 seconds — this is a gate to studying, not a chore
- POST to `student_signals` endpoint
- Show as the entry point when opening the app at study time

### 2. Priority scoring engine

Create `mitty/planner/scoring.py`.

For each potential study item, compute a composite priority score:

| Factor | Weight | Source | Logic |
|--------|--------|--------|-------|
| Urgency | high | assignments.due_at | Hours until due, exponential decay |
| Assessment proximity | high | assessments.scheduled_date | Days to next test in this course |
| Mastery gap | medium | mastery_states.mastery_level | `1.0 - mastery_level` for related concepts |
| Grade risk | medium | enrollments.current_score | Below B threshold → boost |
| Historical volatility | low | grade_snapshots | Standard deviation of recent scores |
| Confidence gap | medium | mastery_states | `confidence_self_report - success_rate` |
| Student preference | low | student_signals.preferences | Boost preferred subjects |
| Spaced review due | medium | mastery_states.next_review_at | Items overdue for review |

All weights configurable. Output: ranked list of `(study_opportunity, score, reason)` tuples.

Key rules:
- Tests in the next 3 days dominate the score
- Overdue/missing homework gets high urgency regardless
- Even when nothing is urgent, spaced review items should surface
- The scoring must be fully deterministic and explainable ("this is #1 because you have a Bio test in 2 days and your Ch.7 mastery is 0.4")

### 3. Study block time allocator

Create `mitty/planner/allocator.py`.

Given ranked opportunities and available minutes, allocate into blocks:

| Block type | Duration | Purpose | When |
|------------|----------|---------|------|
| Plan | 5-10 min | Choose goals, estimate time, identify blockers | Always first |
| Urgent deliverable | 30-45 min | Finish homework due tomorrow | When items due ≤ 24h |
| Retrieval | 15-25 min | Low-stakes quiz on current + prior units | Always (protected) |
| Worked example | 20-35 min | Solve problems with faded scaffolding | Math/science courses |
| Deep explanation | 10-20 min | Explain why/how, compare concepts | Any course |
| Reflection | 5 min | "What do I still not get?" | Always last |

Allocation rules:
- **Always** include Plan at start and Reflection at end
- **Always** protect at least 15 min for retrieval/spaced review — even on busy nights. Otherwise the system becomes homework triage, not a learning tool
- **Cap total** at available_minutes from check-in (hard stop, configurable max default 180 min)
- Distribute remaining time by priority score
- On very short nights (< 30 min): Plan (5) + Retrieval (15) + Reflection (5) — skip homework, keep learning
- On exam-eve nights: Plan (5) + Retrieval for that subject (60%+) + Reflection (5)

### 4. Plan generation orchestrator

Create `mitty/planner/generator.py`.

Orchestrates: gather inputs → score → allocate → write to database.

- Reads: assignments (due soon), assessments (upcoming), enrollments (grades), mastery_states, latest student_signal
- Calls scoring engine → allocator
- Writes: `study_plan` row + `study_block` rows
- Supports: manual trigger via API, and scheduled trigger (cron)
- Regeneration: if the student updates their check-in or situation changes, allow re-generating today's plan (replaces draft blocks, warns if blocks already started)

### 5. Plan API endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/plans/today` | GET | Get today's plan with blocks |
| `/plans/generate` | POST | Trigger plan generation (uses latest signal) |
| `/plans/{id}` | GET | Get a specific plan |
| `/plans/{id}/blocks/{id}` | PUT | Update block status (start, complete, skip) |
| `/plans/history` | GET | Past plans with summary stats |

Plan lifecycle: `draft` → `active` (first block started) → `completed` (all done or time up)

### 6. Study plan UI

The daily plan page. Shows:

```
┌──────────────────────────────────────────┐
│  Tonight's Study Plan                    │
│  Available: 90 min  │  Energy: ●●●○○     │
│                                          │
│  📝 Bio test in 2 days                   │
│  📝 Pre-Calc quiz Friday                 │
│                                          │
│  ┌─ 1. Plan (5 min) ─────────── ✓ ─────┐│
│  │  Review tonight's goals               ││
│  └───────────────────────────────────────┘│
│  ┌─ 2. Homework: Pre-Calc 14.4 (30 min) ┐│
│  │  Due tomorrow · 5 pts                 ││
│  │  [Start]                              ││
│  └───────────────────────────────────────┘│
│  ┌─ 3. Retrieval: Bio Ch.7 (20 min) ────┐│
│  │  Test in 2 days · Mastery: 40%        ││
│  │  [Start]                              ││
│  └───────────────────────────────────────┘│
│  ┌─ 4. Worked Example: Pre-Calc (20 min) ┐│
│  │  Quiz Friday · Integration practice   ││
│  │  [Start]                              ││
│  └───────────────────────────────────────┘│
│  ┌─ 5. Reflection (5 min) ──────────────┐│
│  │  What do I still not get?             ││
│  │  [Start]                              ││
│  └───────────────────────────────────────┘│
│                                          │
│  ━━━━━━━━━━━━━━━━━━━━━━━ 0/90 min       │
└──────────────────────────────────────────┘
```

- Each block: type icon, title, target time, course context, action button
- Running timer when a block is in progress
- Progress bar for overall session
- Assessment alerts at the top ("Bio test in 2 days")
- Completed blocks get a checkmark, skipped blocks get dimmed

### 7. Block execution tracking

- When student taps "Start": record `started_at`, update status to `in_progress`
- When student taps "Done" or timer expires: record `completed_at`, calculate `actual_minutes`
- When student taps "Skip": record as skipped with reason (optional)
- Calculate: `blocks_completed / blocks_total`, `actual_time / planned_time`
- Store on the study_plan record
- Surface basic stats: today's progress, weekly completion rate

## Acceptance criteria

- [ ] Check-in flow works end-to-end, takes < 60 seconds
- [ ] Scoring engine ranks opportunities correctly (test scenarios: exam tomorrow, nothing urgent, mixed priorities)
- [ ] Allocator produces valid plans that respect time constraints and block type rules
- [ ] Plan always includes Plan + Reflection blocks and protected retrieval time
- [ ] Plan caps at available_minutes, never exceeds
- [ ] Very short sessions (< 30 min) get a sensible minimal plan
- [ ] Exam-eve sessions prioritize the right subject
- [ ] Plan UI renders clearly on mobile
- [ ] Block start/complete/skip tracking works
- [ ] Upcoming assessments displayed prominently in plan
- [ ] Scoring reasons are human-readable ("Bio test in 2 days, mastery 40%")
- [ ] Thorough unit tests for scoring and allocation with diverse scenarios
- [ ] Quality gates pass

## Risks & open questions

- **Cold start** — With no mastery data and no assessments entered, the planner can only use grades and due dates. Need a graceful degradation: "enter your upcoming tests to get better plans."
- **Student buy-in** — The check-in must feel fast and useful, not like homework about homework. Quick picks > sliders > text fields.
- **Stop conditions** — Never plan more than the student's available time. Never guilt-trip for skipping. The system should be helpful, not punitive.
- **Block duration accuracy** — Initial time estimates will be wrong. Track actual vs. planned and adjust over time (Phase 8 feedback loop).
- **What counts as a "concept"?** — Until mastery tracking is populated (Phase 4), the planner's concept-level signals will be empty. It should still produce useful plans from grades + due dates alone.

## Dependencies

- Phase 1: schema (study_plans, study_blocks, student_signals, mastery_states, assessments tables)
- Phase 1: backend API (endpoints)
- Phase 1: frontend scaffold (routing, study plan page)
- Phase 2: assessment data (manual entry at minimum, Canvas quizzes ideally)
