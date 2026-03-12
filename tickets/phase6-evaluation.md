# Phase 6: Evaluation, Metrics, and Parent Dashboard

## Context

The system now generates plans, runs practice, tracks mastery, and uses AI for coaching. But how do you know it's working? Not "the plan was generated" — actually working. Improving learning, not just improving task completion.

OECD's warning is blunt: some AI use improves task performance without improving learning. The evaluation must measure independent performance, not just assisted performance. The DOE says decision makers should distrust broad claims and prioritize evidence-based measurement.

This phase adds the feedback loop that turns the product from a tool into an accountable system.

## Goals

- Calculate and track outcome metrics that measure actual learning
- Separate assisted vs. unassisted performance measurement
- Detect grade recovery and decline patterns
- Build a parent dashboard with actionable overview
- Generate weekly progress reports
- Implement human escalation workflows
- Compare pre-test practice with post-test results

## Outcome metrics

### What to track

| Metric | What it measures | Source |
|--------|-----------------|--------|
| On-time submission rate | Is she turning work in? | assignments + submissions |
| Block completion rate | Is she following the plan? | study_plans + study_blocks |
| Retrieval accuracy (7d/30d) | Is practice working? | practice_results |
| Delayed retrieval accuracy (24h/7d) | Is she retaining? | practice_results (spaced items) |
| Grade trend | Are grades moving up? | grade_snapshots over time |
| Confidence calibration | Does she know what she knows? | confidence_before vs. is_correct |
| Help request rate | Is she becoming independent? | coach interactions / total practice |
| **Unassisted performance** | Can she do it alone? | practice_results flagged as unassisted |

**Unassisted performance is the most important metric.** If assisted performance is high but unassisted is low, the AI is helping her complete work without helping her learn.

## Work items

### 1. Outcome metrics engine

Create `mitty/evaluation/metrics.py`.

Calculate each metric on demand and on schedule:

```python
async def calculate_metrics(course_id: int | None = None, period: str = "weekly") -> dict:
    return {
        "on_time_submission_rate": ...,     # % submitted before due_at
        "block_completion_rate": ...,        # % of planned blocks completed
        "retrieval_accuracy_7d": ...,        # quiz accuracy, last 7 days
        "retrieval_accuracy_30d": ...,       # quiz accuracy, last 30 days
        "delayed_retrieval_accuracy": ...,   # accuracy on spaced review items
        "grade_trend": ...,                  # slope of grade_snapshots
        "confidence_calibration": ...,       # correlation(confidence, accuracy)
        "help_request_rate": ...,            # coach uses / total practice items
        "unassisted_performance": ...,       # accuracy without AI hints
    }
```

Run after each study session and on a daily schedule. Breakdowns: per-course and overall.

### 2. Metrics storage and history

Add a `metric_snapshots` table:

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| metric_name | text | |
| metric_value | float | |
| dimension | text | course_id or 'all' |
| period | text | daily, weekly, monthly |
| calculated_at | timestamp | |

API endpoints:
- `GET /metrics/current` — latest values for all metrics
- `GET /metrics/history?metric=X&period=weekly` — time series for charting
- `GET /metrics/summary` — high-level dashboard data

### 3. Unassisted vs. assisted tracking

The critical distinction. When a student answers a practice question:

| Scenario | Classification |
|----------|---------------|
| Answers without using coach | Unassisted |
| Answers after viewing a hint | Assisted (light) |
| Answers after coach explanation | Assisted (heavy) |
| Coach gives the answer, student confirms | Not counted as student performance |

Implementation:
- Add `assistance_level` field to `practice_results`: `none`, `hint`, `explanation`, `given`
- Report both assisted and unassisted accuracy, but **emphasize unassisted as the real signal**
- If assisted accuracy >> unassisted accuracy, surface warning: "She's getting help but may not be retaining independently"
- Track the gap over time — it should shrink as she learns

### 4. Grade recovery / decline detection

Analyze `grade_snapshots` for patterns:

| Pattern | Detection | Action |
|---------|-----------|--------|
| Recovery | Grade trending up after decline | Celebrate: "Bio improved 5% since starting daily practice" |
| Decline | Grade trending down (3+ consecutive drops) | Alert: "Math grade declining — review study plan adherence" |
| Volatility | High standard deviation in recent scores | Investigate: might indicate inconsistent effort or hard unit |
| Stagnation | No change despite practice | Suggest: "Consider a different approach or ask for help" |

Tie patterns to study behavior:
- "Grade improved" + "high block completion" → the system is working
- "Grade declining" + "skipping study blocks" → adherence problem
- "Grade declining" + "completing blocks but low unassisted accuracy" → learning problem

### 5. Parent dashboard

A parent-facing view (same app, role-based):

```
┌──────────────────────────────────────────┐
│  This Week's Overview                    │
│                                          │
│  📊 Study: 6.5 hrs / 7 hrs planned      │
│  📝 Submitted: 12/14 assignments on time │
│  🎯 Practice accuracy: 72% (↑ from 65%) │
│                                          │
│  ─── Privilege Score: 10/12 ───          │
│  [existing scoreboard]                   │
│                                          │
│  ─── By Course ───                       │
│  Pre-Calc    B+ (87%)  ↑  Practice: 78% │
│  Biology     C+ (78%)  ↓  Practice: 55% │
│  AP US Hist  B  (83%)  →  Practice: 70% │
│  Spanish     A- (91%)  ↑  Practice: 82% │
│  Chemistry   B  (84%)  →  Practice: 65% │
│                                          │
│  ⚠ Alert: Biology mastery declining.     │
│    Ch.7 concepts need extra practice or  │
│    teacher help.                         │
│                                          │
│  📅 Upcoming: Bio test (3 days),         │
│     Pre-Calc quiz (5 days)               │
└──────────────────────────────────────────┘
```

Parents see:
- Overall study effort and compliance
- Grades with trend arrows
- Practice accuracy per course (unassisted emphasized)
- Escalation alerts with context
- Upcoming assessments

Parents do NOT see:
- Individual chat logs (student privacy)
- Specific practice answers
- Detailed emotional check-in data
- The student's private notes or blockers

### 6. Human escalation workflow

When the escalation detector (Phase 5) or metrics engine flags a concern:

1. **Student notification** — gentle, in-app: "This topic is tough — consider asking your teacher about [specific concept]"
2. **Parent notification** — configurable (email or in-app): "[Student] may need help with Biology Ch.7. Practice accuracy is 35% after 2 weeks of study."
3. **Escalation log** — stored with context: which concept, how many failures, relevant practice history, suggested action
4. **Suggested actions** — "Review Ch.7 with a tutor", "Ask teacher about quadratic equations", "Consider a study group"
5. **Parent acknowledgment** — parents can acknowledge or dismiss escalations
6. **Never auto-contact teachers** — that's a parent decision

### 7. Weekly progress report

Generated Sunday evening (configurable):

```
Weekly Study Report — March 3-9, 2026

📊 Study Time: 8.5 hrs (planned: 9 hrs) — 94%
📝 Blocks Completed: 24/27 — 89%
🎯 Practice Accuracy: 72% overall (↑ 4% from last week)

🏆 Biggest Win: Pre-Calc mastery up 12% — integration practice is working

⚠ Biggest Concern: Biology Ch.7 accuracy stuck at 40% despite 3 practice sessions.
   Recommendation: Ask teacher for help or try worked examples instead of quizzes.

📅 Next Week:
   - Biology test (Wednesday)
   - Pre-Calc quiz (Friday)
   - AP US History essay due (Thursday)

💪 Streak: 12 days consecutive study sessions
```

Delivery: in-app notification + optional email to parent. Concise and scannable.

### 8. Pre-test vs. post-test comparison

When an assessment has a `unit_or_topic`:

1. **Before test**: snapshot mastery_states and recent retrieval accuracy for related concepts
2. **After grade comes in**: compare predicted vs. actual
3. **Store comparison**: `pre_post_comparisons` table (assessment_id, pre_mastery, pre_accuracy, actual_grade, created_at)
4. **Surface**: "You practiced 15 Bio Ch.7 questions (72% accuracy) and scored 78% on the test"
5. **Over time**: build a model of how well practice predicts test results — if it doesn't, the practice needs to change

This closes the feedback loop between daily practice and actual outcomes.

## Acceptance criteria

- [ ] All 8 outcome metrics calculated correctly from real data
- [ ] Metrics stored with history, queryable by period and course
- [ ] Assisted vs. unassisted performance tracked separately
- [ ] Warning surfaced when assisted >> unassisted accuracy
- [ ] Grade recovery/decline detection produces correct alerts
- [ ] Alerts tied to study behavior ("declined + skipping blocks" vs "declined + completing blocks")
- [ ] Parent dashboard shows overview without exposing private data
- [ ] Escalation workflow: student notification → parent notification → acknowledgment
- [ ] Weekly report generated with wins, concerns, and upcoming assessments
- [ ] Pre-test/post-test comparison works for at least one assessment
- [ ] Tests for all metric calculations and detection logic
- [ ] Quality gates pass

## Risks & open questions

- **Data density** — Most metrics need weeks of data to be meaningful. Early on, show "not enough data yet" rather than misleading numbers.
- **Correlation vs. causation** — "Grade improved while using the app" ≠ "the app caused improvement." Be honest in reporting: show correlation, don't claim causation.
- **Information overload for parents** — The parent dashboard must be scannable, not a wall of charts. Lead with: biggest win, biggest concern, action needed.
- **Privacy tension** — Parents want visibility; the student needs safe space to be honest in check-ins and with the coach. The role-based access design matters.
- **Metric gaming** — If the student knows her metrics are being watched, she might optimize for looking good (fast answers, skipping hard ones). The unassisted performance metric and confidence calibration guard against this.

## Dependencies

- Phase 1: schema + backend API
- Phase 3: planner + study blocks (block completion tracking)
- Phase 4: practice results + mastery states (accuracy metrics)
- Phase 5: AI interactions (assisted vs. unassisted classification, escalation detection)
