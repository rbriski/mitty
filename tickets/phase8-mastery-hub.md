# Phase 8: Mastery Hub — Streamlined Test Prep Experience

## Context

The app currently has four top-level views: Dashboard, Study Plan, Mastery, and Test Prep. For a student prepping for a specific test (Pre-Calculus Chapter 4, March 16), this is disorienting. The Study Plan was built for multi-subject daily scheduling — a different product. The Mastery tab shows a flat list of concepts with no connection to what's coming up. Test Prep is a separate destination with its own setup flow. The student has to mentally stitch these together.

The research is unambiguous about what works: a tight loop of **see the gap → practice → reflect → repeat**. Every extra click, every disconnected view, every context switch is friction against that loop.

This phase removes the Study Plan, elevates Mastery to the central hub, and makes Test Prep a seamless sub-flow that starts and ends in Mastery. The goal is an app that feels like one thing: a coach that knows what you're weak on and puts a problem in front of you.

## Research foundation

Six findings from the learning science literature drive every design decision below. Each is tagged (R1–R6) and referenced in the work items.

### R1: Retrieval practice IS the learning (Karpicke & Roediger, 2006)

Taking a test produces 150% better retention at one week than re-studying the same material. Students prefer re-reading because it feels productive ("illusion of competence"), but the act of retrieving from memory is what builds durable knowledge. Re-reading, reviewing notes, and looking at study plans do not produce learning — only active retrieval does.

**Design principle:** The primary action in the app is always "start practicing." There are no passive review screens, no "study guides," no content to read. Every minute in the app is spent retrieving.

*Source: [Test-Enhanced Learning](https://journals.sagepub.com/doi/abs/10.1111/j.1467-9280.2006.01693.x)*

### R2: Adaptive difficulty in the zone of proximal development (Harvard/Kestin et al., 2025)

A randomized controlled trial at Harvard found students learned 2x as much in less time when an AI tutor adapted to keep them in the zone of proximal development (~70-80% success rate). Too easy = boredom, too hard = frustration. The system monitors performance in real-time and adjusts.

**Design principle:** Difficulty adaptation is invisible to the student. No "Difficulty: 50%" label. The system just keeps problems in the zone. The student should feel challenged but not stuck.

*Source: [AI tutoring outperforms active learning (Nature)](https://www.nature.com/articles/s41598-025-97652-6)*

### R3: Interleaving beats blocking (Rohrer & Dedrick; MIT Open Learning)

Practicing one concept at a time (blocked) feels productive but produces worse outcomes than mixing concepts (interleaved). Interleaving forces the student to choose a strategy — the same discrimination required on a real test. The benefit holds at 1-day and 30-day delays.

**Design principle:** The focused practice phase (Phase 2) should be brief — just enough to build initial competence on the weakest concept. The majority of practice time should be interleaved (Phase 4). Current timing is backwards (18 min focused, 15 min mixed). Flip it.

*Source: [MIT Open Learning — Spaced and Interleaved Practice](https://openlearning.mit.edu/mit-faculty/research-based-learning-findings/spaced-and-interleaved-practice)*

### R4: Immediate, brief feedback (CMU Cognitive Tutor, Anderson et al.)

30 years of Cognitive Tutor research found optimal feedback is: immediate, short, directed at the specific error. Students reached the same proficiency in **one-third** the time. Long explanations are counterproductive — they shift the student from active retrieval back to passive reading.

**Design principle:** Default feedback is one sentence identifying the error + the correct answer. "Show full explanation" is available but collapsed. The student should spend 5 seconds reading feedback, not 30.

*Source: [Cognitive Tutors: Lessons Learned](http://act-r.psy.cmu.edu/papers/Lessons_Learned.html)*

### R5: Calibration training fixes overconfidence (metacognition research)

Math students are more overconfident than students in any other subject. A 3-step cycle — predict performance, perform, compare prediction to reality — measurably improves both calibration accuracy and actual performance over ~6 sessions. Overconfident students skip self-regulation behaviors and ignore feedback.

**Design principle:** Calibration isn't just Phase 5. It's a running theme. Before each concept block: "How confident are you?" After: "Here's how you did." The gap between confidence and reality is the most important learning signal in the app.

*Source: [Metacognition and confidence in math (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4451238/)*

### R6: Error analysis produces superior transfer (the "derring effect")

Students who deliberately make and correct errors outperform error-free practitioners on complex transfer tasks. Find-the-mistake problems force deeper processing than correct-only practice. The benefit is strongest for far transfer — applying knowledge to novel problem formats (like a test with problems you haven't seen).

**Design principle:** Error analysis (Phase 3) is not a brief pit stop. It should include "find the error in this worked solution" AND "here's your mistake from problem 6 — explain what went wrong." This phase may be the single highest-value activity in the session.

*Source: [Deliberate Erring Improves Far Transfer (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9902256/)*

## Goals

- Remove Study Plan from the navigation and primary UX flow
- Make Mastery the single hub for understanding where you stand and starting practice
- Mastery defaults to the upcoming test, sorted by weakest concept
- One click from Mastery to a test prep session
- Session completion returns to Mastery with updated data and calibration insights
- Adjust session phase timing to match research (more interleaving, more error analysis)
- Shorten default feedback, make explanations expandable
- Embed running calibration (confidence vs. reality) throughout the experience
- The app should feel like one coherent thing, not four disconnected tools

## UX vision

### App identity: a coach, not a dashboard

The app today feels like an admin panel — data tables, separate CRUD views, lots of navigation. For a student prepping for a test, it should feel like a coach sitting next to her. The coach knows:

- What test is coming up and when
- Which concepts she's strong on and which she's not
- What mistakes she keeps making
- When she's overconfident

The coach doesn't show her a dashboard of data. The coach says: "You're weak on rational functions. Let's work on that. Ready?"

### Navigation: three views, one flow

```
Dashboard  ·  Mastery  ·  (Test Prep is a sub-view of Mastery)
```

- **Dashboard**: Overview of all classes, grades, upcoming assignments. Unchanged.
- **Mastery**: The hub. Shows concept map for the upcoming test. Entry point for practice.
- **Test Prep**: Not a nav item. It's the session view you enter from Mastery and return to when done.

Study Plan is removed from navigation entirely. The `/study-plan` route can remain for now (in case of bookmarks) but it's no longer linked.

### Mastery: the hub

The Mastery tab becomes the center of gravity. Three states:

#### State 1: Upcoming test view (default)

The system detects the next upcoming assessment and scopes the mastery view to that test's concepts.

```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  Pre-Calculus — Chapter 4 Test                              │
│  Tomorrow · 100 pts · Polynomial & Rational Functions        │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                                                         ││
│  │  Polynomial Functions     ████████████████████  100%  ✓ ││
│  │  Polynomial Division      ████████████████░░░░   82%    ││
│  │  End Behavior             ███████████████░░░░░   75%    ││
│  │  Rational Functions       █████████████░░░░░░░   65%  ↓ ││
│  │  Inequalities             ████████████░░░░░░░░   60%  ⚠ ││
│  │  Finding Zeros            █████████░░░░░░░░░░░   45%  ! ││
│  │                                                         ││
│  └─────────────────────────────────────────────────────────┘│
│                                                              │
│  You're overconfident on Finding Zeros — you rated 4/5      │
│  but scored 45%. Focus here.                                │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                                                         ││
│  │  [  Start Practice — Finding Zeros  ]                   ││
│  │                                                         ││
│  │  Or: Full session (all concepts) · Quick review (15min) ││
│  │                                                         ││
│  └─────────────────────────────────────────────────────────┘│
│                                                              │
│  Session history                                             │
│  ─────────────                                               │
│  Mar 14  23/31 (74%)  58 min  Calibration: 2 overconfident  │
│  Mar 12  18/28 (64%)  45 min  Calibration: 3 overconfident  │
│  Mar 10  12/20 (60%)  30 min  First session                 │
│                                                              │
│  Trend: +14% over 3 sessions. Keep going.                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

Key UX decisions:
- **Smart default**: System identifies the next assessment from Canvas data (assignment with `is_assessment=true` and nearest future `due_at`). No manual selection needed.
- **Sorted by weakness**: Weakest concept at the bottom, strongest at top. The eye naturally lands on the problem area. The red `!` marker draws attention.
- **Calibration callout**: If overconfidence detected (confidence rating > actual performance by >20%), surface it prominently. This is R5 in action.
- **One primary CTA**: "Start Practice — [weakest concept]". Not a form with dropdowns. One button. The system picks the right focus.
- **Secondary options**: "Full session" runs all 5 phases across all concepts. "Quick review" is a 15-minute interleaved session (Phase 4 only) for day-before cramming.
- **Session history**: Shows the trajectory. Students are motivated by visible progress. Each row shows accuracy, calibration quality, and time spent.

#### State 2: No upcoming test

If there's no upcoming assessment in the near future (>7 days out), show all courses with mastery data, sorted by lowest overall mastery:

```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  Your Mastery                                               │
│                                                              │
│  Pre-Calculus H S2                   Overall: 68%           │
│  6 concepts tracked · Last session: 2 days ago              │
│  [Continue Practice]                                        │
│                                                              │
│  Chemistry S2                        Overall: —             │
│  No homework analyzed yet                                   │
│  [Analyze Homework]                                         │
│                                                              │
│  AP US History S2                    Overall: —             │
│  No homework analyzed yet                                   │
│  [Analyze Homework]                                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

For courses without mastery data, the CTA is "Analyze Homework" which triggers the homework vision pipeline. Once analyzed, the course card expands to show concept data and "Start Practice."

#### State 3: Inside a session (Test Prep)

When the student clicks "Start Practice," the Mastery view transitions into the session view. This is the current Test Prep UI, with these adjustments:

- **No separate /test-prep route** — the session renders within /mastery (or /mastery/session/{id})
- **The concept heat map stays visible** (left sidebar on desktop, collapsible on mobile) and updates in real-time as the student answers problems (R1: immediate feedback on progress)
- **Back arrow** exits the session (with confirmation) and returns to Mastery
- **On completion**, the calibration report renders inline on Mastery, then the concept heat map updates and the CTA refreshes to suggest the next weakest concept

### Session flow adjustments (research-driven)

#### Revised phase timing (45-minute default)

| Phase | Current | Revised | Rationale |
|-------|---------|---------|-----------|
| Diagnostic | 8 min | 5 min | Confidence scan + 6 quick problems. Keep it snappy. (R1: more time practicing, less assessing) |
| Focused Practice | 18 min | 8 min | Brief scaffolding on weakest concept. Worked example → 3-4 independent problems. Just enough to build initial competence. (R3: blocking is less effective) |
| Error Analysis | 10 min | 12 min | Expanded. 2-3 find-the-mistake problems + review of own errors from Diagnostic and Focused phases. (R6: highest transfer value) |
| Mixed Test | 15 min | 15 min | Interleaved problems across all concepts, no hints, simulates test conditions. (R3: this is where discrimination learning happens) |
| Calibration | 4 min | 5 min | Predict → compare → reflect per concept. Confidence vs. reality table. Key takeaway message. (R5) |

Total: 55 → 45 minutes. Tighter. Research shows shorter, more frequent sessions are better than marathon sessions. Offer "extend" if the student wants more time in any phase.

#### Feedback redesign (R4)

Current: paragraph of explanation after every answer.

Revised:
```
┌─────────────────────────────────────────────────────────┐
│  ✗  Sign error in synthetic division step.              │
│     Correct answer: x = 3, x = -1/2, x = 1            │
│                                                         │
│  [Show worked solution]  [Next →]                       │
└─────────────────────────────────────────────────────────┘
```

- **One line** identifying the error type + where it occurred
- **Correct answer** always visible
- **"Show worked solution"** expands step-by-step if the student wants it (most won't — R4 says brief is better)
- No "Try Again" — in test prep, you get one shot per problem (simulates test conditions). "Try Again" trains the wrong behavior.

#### Running calibration (R5)

Before each new concept block (not just Phase 1):
```
  How confident are you on Rational Functions?
  [1] [2] [3] [4] [5]
```

After the concept block:
```
  You rated 4/5 but scored 2/4 (50%).
  This gap means you may underestimate the difficulty on the test.
```

This micro-calibration loop happens naturally throughout the session, not just at the end. By session 3-4, the student's confidence ratings should start matching reality.

### Difficulty adaptation UX (R2)

Remove all visible difficulty indicators. No "Difficulty: 50%" label. No difficulty slider. The system adapts silently:

- 2 correct → harder (shift +0.15)
- 2 wrong → easier (shift -0.15), offer a worked example
- Target: 70-80% success rate across a rolling window of 6 problems

The only visible signal is the concept heat map updating in real-time. The student sees her mastery percentage climbing (or not). That's the feedback loop, not a difficulty number.

### Mobile considerations

The student might use this on an iPad at her desk or on her phone between classes. The layout must work at both sizes:

- **Desktop (>768px)**: Concept heat map as left sidebar, problem area center, session controls right
- **Mobile (<768px)**: Concept heat map collapses to a thin progress bar at top (showing overall % and current concept). Full-width problem area. Swipe or tap to see heat map details.
- **MathLive**: Already works on touch devices. The virtual keyboard activates on mobile.
- **Touch targets**: All buttons minimum 44x44px. Answer input area should be generous on mobile.

### Visual design principles

- **Calm, focused**: White space, no visual clutter. The student is doing cognitive work — the UI should be quiet.
- **Progress is visible but not noisy**: Heat map bars update smoothly. No confetti, no achievement badges, no gamification. This is serious test prep.
- **Color carries meaning**: Green (>80% mastery) / Yellow (50-80%) / Red (<50%). Calibration gaps highlighted in orange. These are the only uses of color for data.
- **Typography**: Problem text in a clear serif or well-spaced sans-serif at 16px minimum. Math notation (KaTeX) needs breathing room. Small UI labels in the system font.
- **One thing at a time**: Each screen has one primary action. Mastery: "Start Practice." Session: "Submit Answer." Calibration: "See results." No competing CTAs.

## Work items

### 1. Remove Study Plan from navigation

Remove the Study Plan link from the base template nav bar. Keep the `/study-plan` route and template functional (don't delete the code) but remove it from primary navigation. If a user navigates to `/study-plan` directly, show a gentle redirect notice pointing to Mastery.

**Files:** `mitty/api/templates/base.html` (or wherever nav is defined), potentially `study_plan.html`

### 2. Redesign Mastery as the hub

The current Mastery tab (`/mastery`) shows a flat concept list from `mastery_states`. Redesign it to:

a. **Smart default to upcoming test**: Query `assessments` for the nearest future `due_at` where `is_assessment=true` for the student's courses. Scope the mastery view to concepts relevant to that assessment. Fall back to showing all courses if no upcoming test.

b. **Concept heat map**: Visual bar chart of per-concept mastery, sorted weakest-last. Each bar shows concept name, mastery %, and status indicator (✓ / ⚠ / !).

c. **Calibration callout**: If any concept has confidence_rating - actual_performance > 20%, show a prominent callout: "You're overconfident on [concept]."

d. **Primary CTA**: "Start Practice — [weakest concept]" button. Pre-selects the weakest concept for session creation. Also offer "Full session" and "Quick review (15min)" as secondary links.

e. **Session history**: Query `test_prep_sessions` for this user/course. Show date, accuracy, duration, calibration summary per session. Show trend line if 3+ sessions.

**Files:** `mitty/api/routers/mastery_dashboard.py`, `mitty/api/templates/mastery_dashboard.html` (or new template), new endpoint for "upcoming assessment" detection

### 3. Connect Mastery → Test Prep as sub-flow

When the student clicks "Start Practice" on Mastery:

a. **Skip the setup flow**: No course dropdown, no assignment dropdown, no "Analyze Homework" step. The system already knows the course, the assessment, and the concepts (from the Mastery view). Go straight to session creation.

b. **Homework analysis on demand**: If the student's homework hasn't been analyzed for the relevant assignments, trigger analysis automatically (or show a brief "Analyzing your homework..." progress state). Don't make it a separate step.

c. **Session creation**: POST to `/test-prep/sessions` with pre-filled course_id, assessment_id, and concept list from Mastery data. The student goes directly into Phase 1 (Diagnostic).

d. **URL structure**: Either `/mastery/session/{id}` or keep `/test-prep/sessions/{id}` but remove `/test-prep` as a standalone nav destination. The entry point is always Mastery.

**Files:** `mitty/api/routers/test_prep.py`, `mitty/api/templates/test_prep.html`, `mitty/api/templates/mastery_dashboard.html`

### 4. Session completion → Mastery return

When a session completes:

a. **Calibration report** renders as the final screen (already exists in Phase 5).

b. **"Back to Mastery" CTA** replaces "Start New Session." When clicked, navigates to `/mastery` with the updated concept heat map reflecting the session's results.

c. **Mastery data refresh**: The session completion endpoint should trigger `update_mastery()` for all concepts practiced, so the Mastery view is immediately current when the student returns.

d. **Next suggestion**: On the Mastery view after returning, show: "Nice work. You improved on [concept] (+12%). Next focus: [next weakest concept]."

**Files:** `mitty/api/templates/test_prep.html` (completion view), `mitty/api/routers/test_prep.py` (session complete endpoint), `mitty/api/routers/mastery_dashboard.py`

### 5. Revise session phase timing

Update the session engine to use revised phase durations:

| Phase | Duration | Problems |
|-------|----------|----------|
| Diagnostic | 5 min | 6 quick problems (1 per concept) + confidence scan |
| Focused Practice | 8 min | Worked example → 3-4 independent on weakest concept |
| Error Analysis | 12 min | 3 find-the-mistake + 2 review-own-errors problems |
| Mixed Test | 15 min | 8-10 interleaved across all concepts, no hints |
| Calibration | 5 min | Per-concept confidence vs. reality comparison |

The session engine's `advance_phase()` logic uses these durations. Also add an "extend phase" option — if the student wants more time on Error Analysis or Mixed Test, let them add 5 minutes.

**Files:** `mitty/prep/session.py` (phase timing constants), `mitty/api/templates/test_prep.html` (extend button)

### 6. Shorten default feedback (R4)

After answer submission, the feedback should be:
- **One line**: Error type + location (e.g., "Sign error in step 3" or "Used wrong theorem")
- **Correct answer**: Always shown
- **Expandable**: "Show worked solution" reveals step-by-step explanation

This means the evaluator prompt or post-processing needs to produce:
- `error_summary`: One sentence (required)
- `correct_answer`: The answer (required)
- `worked_solution`: Step-by-step (optional, shown on expand)

Update the answer submission response schema and the frontend rendering.

**Files:** `mitty/prep/evaluator.py` (if response schema changes), `mitty/api/routers/test_prep.py` (answer endpoint response), `mitty/api/templates/test_prep.html` (feedback rendering)

### 7. Running calibration throughout session (R5)

Currently, confidence is only collected in Phase 1 (Diagnostic). Add micro-calibration checkpoints:

a. **Before Focused Practice (Phase 2)**: "How confident are you on [focus concept]?" (1-5 scale)
b. **After Focused Practice**: Show the gap: "You rated X/5, you scored Y/Z."
c. **Before Mixed Test (Phase 4)**: Brief confidence check across all concepts
d. **Phase 5 Calibration**: Full comparison table with trend from this session AND previous sessions

Store confidence ratings in `test_prep_results` or session state for longitudinal tracking.

**Files:** `mitty/prep/session.py` (calibration checkpoints in phase transitions), `mitty/api/templates/test_prep.html` (confidence UI at phase transitions), `mitty/api/schemas.py` (if new fields needed)

### 8. Hide difficulty indicators (R2)

Remove visible difficulty labels from the session UI:
- Remove "Difficulty: 50%" from the session header
- Remove any difficulty numbers from problem cards
- Keep the adaptive difficulty engine running silently in the backend
- The only visible progress indicator is the concept heat map updating

**Files:** `mitty/api/templates/test_prep.html`

### 9. Upcoming assessment detection endpoint

New endpoint or logic to identify the next upcoming test:

```python
async def get_upcoming_assessment(client, user_id, course_ids) -> dict | None:
    """Find the nearest future assessment across the student's courses.

    Queries assessments table for:
    - is_assessment = true
    - due_at > now()
    - course_id in student's active courses
    - ORDER BY due_at ASC LIMIT 1

    Returns: {assessment_id, course_id, name, due_at, concepts}
    Or None if nothing upcoming.
    """
```

The concepts for an assessment come from the homework analyses for that course — the concepts extracted from the relevant chapter's homework assignments.

**Files:** `mitty/api/routers/mastery_dashboard.py` (or new util), potentially `mitty/storage.py`

### 10. Error analysis phase improvements (R6)

Enhance Phase 3 (Error Analysis) with two problem types:

a. **Find-the-mistake**: Show a worked solution with a deliberate error. Student identifies and corrects it. Generate these via the problem generator with `problem_type="error_analysis"` and a `error_variant` field.

b. **Review own errors**: Pull the student's incorrect answers from Phases 1-2 of the current session. Present them back: "Here's your answer to problem 3. You got it wrong. What went wrong?" The student explains the error in their own words.

Type (b) is the higher-value activity per the research — self-explanation of own errors produces the strongest transfer.

**Files:** `mitty/prep/engine.py` (error analysis phase logic), `mitty/prep/generator.py` (error_analysis problem type), `mitty/api/templates/test_prep.html` (review-own-errors UI)

### 11. Quick review mode

Add a "Quick Review" session type (15 minutes) that skips Phases 1-3 and goes straight to interleaved practice (Phase 4) + brief calibration (Phase 5). This is for:

- Day-before-test cramming
- Students who've already done a full session and want more interleaved practice
- Students with limited time

The quick review uses the existing mastery data to set initial difficulty and concept weighting — no diagnostic needed.

**Files:** `mitty/prep/session.py` (session type parameter), `mitty/api/routers/test_prep.py` (session creation with type), `mitty/api/templates/mastery_dashboard.html` (quick review CTA)

## Acceptance criteria

- [ ] Study Plan removed from navigation bar
- [ ] Mastery view defaults to upcoming test's concepts (smart detection from assessments table)
- [ ] Concept heat map shows per-concept mastery sorted by weakness
- [ ] Calibration callout displayed when overconfidence detected (>20% gap)
- [ ] "Start Practice" button on Mastery pre-selects weakest concept and goes directly to session
- [ ] "Full session" and "Quick review" options available as secondary CTAs
- [ ] Session history displayed on Mastery with accuracy, duration, calibration quality per session
- [ ] Session completion navigates back to Mastery with updated heat map
- [ ] Post-session suggestion: "Next focus: [weakest concept]"
- [ ] Phase timing revised: Diagnostic 5min, Focused 8min, Error Analysis 12min, Mixed 15min, Calibration 5min
- [ ] Default feedback is one sentence + correct answer, with expandable worked solution
- [ ] Running calibration checkpoints before and after Focused Practice and before Mixed Test
- [ ] Difficulty indicators hidden from student view
- [ ] Find-the-mistake problems in Error Analysis phase
- [ ] Review-own-errors problems in Error Analysis phase (pull from earlier phases)
- [ ] Quick Review mode (15 min, Phase 4+5 only) available from Mastery
- [ ] Test Prep removed as standalone nav item
- [ ] Mobile-responsive: heat map collapses to progress bar on small screens
- [ ] Quality gates pass

## Risks & open questions

- **Upcoming assessment detection**: Relies on `is_assessment` flag being accurate in the assessments table. May need a heuristic (assignment name contains "Test", "Exam", "Quiz" + high point value) as a fallback. Also needs a way for the student to manually select which test to prep for if the auto-detection is wrong.
- **Concept-to-assessment mapping**: How do we know which concepts belong to Chapter 4 vs. Chapter 5? Currently driven by which homework assignments were analyzed. If the student only analyzed 3 of 6 Chapter 4 homeworks, the concept map is incomplete. May need a "Analyze all Chapter 4 homework" batch action.
- **Cold start**: A student who hasn't analyzed any homework sees an empty Mastery view. The onboarding flow needs to guide them: "Select a course → We'll analyze your homework → Then you can start practicing." This should be as close to one-click as possible.
- **Study Plan removal**: Some students might have bookmarked or rely on the Study Plan. The redirect notice should be clear about where the functionality moved. Consider keeping the route alive for one release cycle.
- **Session length flexibility**: 45 minutes is the new default. Students should be able to choose 30, 45, or 60 minutes, with phase durations scaling proportionally.
- **Multi-test prep**: What if a student has two tests in the same week (Pre-Calc + Chemistry)? The Mastery hub should allow switching between upcoming tests, not just show the nearest one. A tab or dropdown for "Pre-Calc Ch 4 Test (Mar 16) | Chem Ch 12 Test (Mar 18)" would work.

## Dependencies

- Phase 7 (Test Prep Engine) — all existing test prep infrastructure
- Phase 4 — mastery tracking, practice generator
- Phase 2 — Canvas fetchers, homework analysis pipeline
- Assessments table with `is_assessment` flag and `due_at` populated

## Non-goals

- Building a new Study Plan (the old one is removed, not replaced)
- Gamification (badges, streaks, XP)
- Parent or teacher dashboards
- Multi-student views
- Collaborative study sessions
