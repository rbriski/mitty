# Test Prep Engine: Homework Vision Analysis + Adaptive Sessions

## Context

The current study system is too generic. It generates multi-subject daily plans with protocol-based steps ("Close your notes", "Free recall: write everything you remember") that don't help a student prepare for a specific test. The Chapter 4 Test (Polynomial & Rational Functions, 100 pts) is March 16. The student has a B (86.27%). The system knows almost nothing about what she actually understands — mastery tracking is empty, resource chunks are empty, and the 8 generated practice items are shallow (difficulty 0.1-0.2) because they were generated without source material.

Meanwhile, a goldmine of data sits untouched: **6 graded homework submissions and a graded quiz** for Chapter 4, all handwritten PDFs uploaded to Canvas. These contain exactly the signal we need — which problems the student got right, which she got wrong, what mistakes she made, and what DePalma's problems look like. The review guide PDFs (`CH4 Review` and `Solutions: CH4 Review`) are also on Canvas but were never extracted.

This phase builds two things: a **homework vision analysis pipeline** that extracts structured learning data from handwritten submissions using Claude's vision capabilities, and an **adaptive test prep session** grounded in learning science research that uses that data to run a focused, self-guided study experience.

The research is clear on what works for math test prep:
- **Retrieval practice** outperforms re-studying (Karpicke & Roediger)
- **Interleaving** problem types beats blocked practice (MIT Open Learning)
- **Calibration training** fixes the overconfidence problem prevalent in math students
- **Error analysis** (finding mistakes in worked solutions) produces better transfer than correct-only practice
- **Adaptive difficulty** in the zone of proximal development (~70-80% success rate) doubles learning gains vs. static difficulty (Harvard AI tutoring study, 2024)
- **Immediate feedback with brief explanation** on errors, not lengthy re-teaching (Cognitive Tutor research, CMU)

## Goals

- Extract structured per-problem performance data from graded handwritten homework using Claude vision
- Build a concept map for Chapter 4 sections from real homework problems
- Create an adaptive test prep session that a student can work through independently
- Use real homework/quiz data to identify weak concepts and generate targeted practice
- Implement the research-backed 5-phase session structure (diagnostic → focused practice → error analysis → mixed test → calibration check)
- Make problems that look like DePalma's problems — same style, same difficulty, same format

## The pipeline

```
Canvas API                     Vision Analysis                 Test Prep Session
──────────                     ───────────────                 ─────────────────

GET /submissions/self          Claude vision                   Phase 1: Diagnostic
  → attachment URLs       →    per PDF page          →         (confidence + quick problems)
  → download PDFs              extracts:                            ↓
  → pymupdf page→image         • problem number                Phase 2: Focused Practice
                               • student work                  (weakest concept, adaptive)
GET /files/{review_id}         • correct/incorrect                  ↓
  → download review PDF        • error type                    Phase 3: Error Analysis
  → pymupdf page→image        • concept classification        (find-the-error + own mistakes)
                               • problem style                      ↓
                                      ↓                        Phase 4: Mixed Test
                               Per-concept mastery profile     (interleaved, timed, no hints)
                               + problem style templates            ↓
                               + misconception inventory       Phase 5: Calibration
                                      ↓                        (compare prediction vs reality)
                               Practice generation
                               (problems in DePalma's style,
                                targeting weak concepts)
```

## Chapter 4 concept map

From the homework assignments (sections 4.1, 4.3-4.7):

| Section | Topic | Key concepts |
|---------|-------|-------------|
| 4.1 | Polynomial Functions & Models | End behavior, leading coefficient test, turning points, degree vs. shape |
| 4.3 | Dividing Polynomials | Long division, synthetic division, remainder theorem, factor theorem |
| 4.4 | Zeros of Polynomial Functions | Rational Root Theorem, Descartes' Rule of Signs, upper/lower bounds, complex zeros |
| 4.5 | Rational Functions | Vertical/horizontal/oblique asymptotes, holes, domain restrictions, graphing |
| 4.6 | Polynomial & Rational Inequalities | Sign analysis, test intervals, critical values, interval notation |
| 4.7 | Variation | Direct variation, inverse variation, joint variation, combined variation |

The vision analysis will refine this map based on actual problems assigned.

## Work items

### 1. Canvas submission attachment fetcher

Extend `mitty/canvas/fetcher.py`.

The existing `fetch_assignments()` uses `include[]=submission` which gets scores but not file attachments. We need the actual submitted PDFs.

**New function:**
```python
async def fetch_submission_attachments(
    client: CanvasClient,
    course_id: int,
    assignment_id: int,
) -> list[dict]:
    """Fetch the authenticated user's submission with file attachments.

    Returns attachment dicts with download URLs, content type, filename.
    Canvas API: GET /courses/:id/assignments/:id/submissions/self
    """
```

**Also fetch:**
- Teacher-annotated/graded versions if available (Canvas returns `preview_url` and sometimes annotated PDFs)
- Submission comments (teacher feedback text)
- Score and grade

For Chapter 4, target these assignment IDs:
- 269348 (4.1), 269349 (4.3), 269350 (4.4), 269351 (4.5), 269352 (4.6), 269353 (4.7)
- 269369 (CH4 Quiz: 4.1, 4.6-4.7)
- 269375 (Chapter 4 Test — after it's taken, for future review)

Also fetch the review guide file resources:
- CH4 Review (file resource in Chapter 4 module)
- Solutions: CH4 Review (file resource in Chapter 4 module)

### 2. PDF-to-image conversion

Extend `mitty/canvas/extract.py`.

pymupdf already has `page.get_pixmap()` which converts PDF pages to raster images. Add:

```python
def pdf_pages_to_images(
    content: bytes,
    *,
    dpi: int = 200,
    max_pages: int = 10,
) -> list[bytes]:
    """Convert PDF pages to PNG image bytes for vision analysis.

    Args:
        content: Raw PDF file bytes.
        dpi: Resolution for rendering (200 is good balance of quality vs size).
        max_pages: Safety limit.

    Returns:
        List of PNG bytes, one per page.
    """
    import pymupdf

    doc = pymupdf.open(stream=content, filetype="pdf")
    images = []
    for page in doc[:max_pages]:
        pix = page.get_pixmap(dpi=dpi)
        images.append(pix.tobytes("png"))
    doc.close()
    return images
```

Keep images at 200 DPI — enough for handwriting recognition, small enough for API limits. A typical homework page at 200 DPI is ~500KB PNG, well within Claude's 5MB/image limit.

### 3. Vision support in AI client

Extend `mitty/ai/client.py` to accept image content blocks.

```python
async def call_vision(
    self,
    *,
    system: str,
    user_prompt: str,
    images: list[bytes],
    response_model: type[BaseModel],
    role: str = "vision",
    image_media_type: str = "image/png",
) -> BaseModel:
    """Call Claude with text + image content for vision analysis.

    Constructs a multi-modal message with text and base64-encoded images.
    Uses the same audit logging, rate limiting, and cost tracking as
    call_structured().
    """
```

The message format for the Anthropic API:
```python
{
    "role": "user",
    "content": [
        {"type": "text", "text": user_prompt},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(image_bytes).decode(),
            },
        },
        # ... additional images
    ],
}
```

**Cost awareness:** Vision tokens are expensive. A 200 DPI homework page is roughly 1000-1500 image tokens. With 7 submissions averaging 2 pages each, that's ~14 vision calls ≈ 20K-30K input tokens. Budget ~$0.50-1.00 for a full homework analysis run. This is a one-time cost per assignment set, not per session.

### 4. Homework vision analysis pipeline

Create `mitty/prep/homework_analyzer.py`.

The core analysis function that processes a single homework page:

```python
class ProblemAnalysis(BaseModel):
    """Structured extraction from a single homework problem."""
    problem_number: str           # "4a", "7", "12b"
    section: str                  # "4.3", "4.5"
    problem_type: str             # "find_zeros", "graph_rational", "simplify", etc.
    concept: str                  # "synthetic_division", "vertical_asymptotes"
    student_answer: str           # What the student wrote as final answer
    is_correct: bool | None       # True/False from teacher marks, None if unclear
    score: float | None           # Partial credit if visible (0.0-1.0)
    error_type: str | None        # "computation", "conceptual", "setup", "sign", None if correct
    error_description: str | None # "Forgot to flip inequality when multiplying by negative"
    problem_statement: str        # The actual problem text (for generating similar problems)
    difficulty: float             # Estimated difficulty 0.0-1.0

class PageAnalysis(BaseModel):
    """All problems extracted from a single homework page."""
    problems: list[ProblemAnalysis]
    page_notes: str | None        # Any general observations (teacher comments, etc.)

async def analyze_homework_page(
    ai_client: AIClient,
    image: bytes,
    *,
    assignment_name: str,
    section_hint: str,         # "4.3" from assignment name parsing
) -> PageAnalysis:
    """Analyze a single page of handwritten homework using Claude vision."""
```

The system prompt instructs Claude to:
1. Identify each problem on the page (number, what it asks)
2. Read the student's handwritten work and final answer
3. Look for teacher marks (check marks, X marks, point deductions, corrections)
4. Classify the mathematical concept being tested
5. If the problem is wrong, identify the specific error type and explain the misconception
6. Estimate the problem's difficulty level
7. Transcribe the problem statement so we can generate similar problems later

**Batch orchestrator:**
```python
async def analyze_assignment_submissions(
    ai_client: AIClient,
    canvas_client: CanvasClient,
    course_id: int,
    assignment_ids: list[int],
) -> HomeworkAnalysisResult:
    """Analyze all homework submissions for a set of assignments.

    Downloads PDFs, converts to images, runs vision analysis on each page,
    aggregates into per-concept mastery profile.

    Returns:
        HomeworkAnalysisResult with:
        - per_concept: dict mapping concept → {correct, total, errors, problems}
        - all_problems: flat list of all ProblemAnalysis objects
        - misconceptions: list of identified misconception patterns
        - problem_templates: representative problems per concept (for generation)
    """
```

**Caching:** Store analysis results in a new `homework_analyses` table keyed by `(assignment_id, user_id)`. Re-analysis only if submission is re-uploaded. This avoids re-running expensive vision calls.

### 5. Review guide extraction

Same pipeline as homework, but for the teacher's review guide:

```python
async def analyze_review_guide(
    ai_client: AIClient,
    images: list[bytes],
) -> ReviewGuideAnalysis:
    """Extract problems and topics from a teacher's review guide.

    Returns:
        - problems: list of review problems with solutions
        - topic_coverage: which concepts appear and how many problems each
        - difficulty_distribution: how hard the problems are
    """
```

The review guide is the closest proxy for what the test will look like. Extract every problem with its solution so we can:
- Generate similar problems
- Use the solutions as worked examples
- Understand the difficulty level DePalma targets

### 6. Concept mastery profiler

Create `mitty/prep/mastery_profile.py`.

Aggregates homework analysis into a per-concept mastery profile:

```python
@dataclass
class ConceptProfile:
    concept: str                    # "synthetic_division"
    section: str                    # "4.3"
    problems_attempted: int
    problems_correct: int
    accuracy: float                 # correct / attempted
    common_errors: list[str]        # ["sign error in final step", "forgot remainder"]
    misconceptions: list[str]       # Higher-level patterns
    example_problems: list[str]     # Problem statements for reference
    difficulty_range: tuple[float, float]  # (min, max) difficulty seen
    confidence: float | None        # Student's self-rated confidence (from diagnostic)
    priority: float                 # Computed: lower accuracy + overconfidence = higher priority

def build_mastery_profile(
    analysis: HomeworkAnalysisResult,
) -> list[ConceptProfile]:
    """Build per-concept mastery profiles from homework analysis.

    Also identifies cross-concept patterns:
    - Computation errors across multiple sections (systemic issue)
    - Setup errors (doesn't understand what to do)
    - Conceptual gaps (understands procedure but not why)
    """
```

### 7. Adaptive problem generator

Create `mitty/prep/problem_generator.py`.

Generates practice problems that match DePalma's style, targeting specific concepts at appropriate difficulty:

```python
class GeneratedProblem(BaseModel):
    problem_text: str               # The problem statement (LaTeX-compatible)
    concept: str                    # Target concept
    section: str                    # Textbook section
    difficulty: float               # 0.0-1.0
    solution_steps: list[str]       # Step-by-step worked solution
    final_answer: str               # The correct answer
    common_mistakes: list[str]      # What students typically get wrong
    hints: list[str]                # Progressive hints (hint 1 = gentle, hint 3 = almost gives it away)
    error_variant: str | None       # A wrong solution for "find the error" exercises

async def generate_problems(
    ai_client: AIClient,
    concept: str,
    *,
    difficulty: float,
    count: int = 4,
    style_examples: list[str],      # Real problems from homework/review guide
    avoid_duplicates: list[str],    # Problems already seen this session
) -> list[GeneratedProblem]:
    """Generate practice problems matching the teacher's style.

    The style_examples parameter is critical — it contains actual problems
    from DePalma's homework and review guide. Claude uses these as style
    templates to generate problems that look and feel like the real test.
    """
```

**Difficulty adaptation within session:**
- Start at estimated mastery level
- 2 correct in a row → increase difficulty by 0.15
- 2 wrong in a row → decrease difficulty by 0.15, offer worked example
- Stay within [0.1, 0.9] range
- Target ~70-80% success rate (zone of proximal development)

### 8. Session engine

Create `mitty/prep/session.py`.

The orchestrator that manages the 5-phase session flow:

```python
class SessionPhase(str, Enum):
    DIAGNOSTIC = "diagnostic"
    FOCUSED = "focused"
    ERROR_ANALYSIS = "error_analysis"
    MIXED_TEST = "mixed_test"
    CALIBRATION = "calibration"

class SessionState(BaseModel):
    """Tracks session progress — stored in browser, synced to server."""
    session_id: str
    phase: SessionPhase
    phase_start_time: datetime
    total_elapsed_seconds: int

    # Diagnostic results
    confidence_ratings: dict[str, int]     # concept → 1-5
    diagnostic_results: dict[str, list]    # concept → [correct, total]

    # Per-concept running mastery (updated in real-time)
    running_mastery: dict[str, float]      # concept → accuracy this session

    # Problem history (for avoiding duplicates, tracking errors)
    problems_attempted: list[dict]
    problems_correct: int
    problems_total: int

    # Current focus
    focus_concept: str | None
    current_difficulty: float
    consecutive_correct: int
    consecutive_wrong: int

class SessionEngine:
    """Manages the adaptive session flow."""

    def get_next_action(self, state: SessionState) -> SessionAction:
        """Determine what to show next based on current state.

        Returns one of:
        - ShowProblem (with problem, hints available, timer)
        - ShowWorkedExample (with step-by-step solution)
        - ShowErrorAnalysis (with wrong solution to critique)
        - ShowFeedback (after answer submitted)
        - ShowPhaseTransition (moving to next phase)
        - ShowCalibrationReport (end of session)
        """

    def process_answer(self, state: SessionState, answer: str) -> AnswerResult:
        """Evaluate an answer and update session state.

        Updates running mastery, adjusts difficulty, determines
        whether to continue current phase or transition.
        """
```

**Phase timing (60 min default, configurable):**

| Phase | Duration | Purpose |
|-------|----------|---------|
| Diagnostic | 8 min | Confidence scan + 8-10 quick problems (1-2 per concept) |
| Focused Practice | 18 min | Weakest concept: worked example → faded → independent → adaptive |
| Error Analysis | 10 min | Find-the-error problems + review own mistakes from earlier phases |
| Mixed Test | 15 min | 8-10 interleaved problems, no hints, timed, simulates test conditions |
| Calibration | 4 min | Compare confidence predictions to actual performance, identify gaps |
| Buffer | 5 min | Overflow / early finish |

**Phase transition rules:**
- Diagnostic → Focused: after all concepts scanned, pick lowest-mastery concept
- Focused → Error Analysis: after 18 min OR after 6+ independent problems attempted
- Error Analysis → Mixed Test: after 10 min OR after 3 error analysis problems completed
- Mixed Test → Calibration: after all problems attempted OR time expires
- The student can always skip ahead or extend a phase

### 9. Test prep API endpoints

Create `mitty/api/routers/test_prep.py`.

```
POST /test-prep/analyze-homework
    Body: { course_id, assignment_ids[] }
    → Triggers homework vision analysis pipeline
    → Returns job_id (analysis may take 30-60 seconds)

GET  /test-prep/analysis-status/{job_id}
    → Returns progress (X/Y pages analyzed) and result when complete

GET  /test-prep/mastery-profile/{course_id}
    → Returns per-concept mastery profile from homework analysis

POST /test-prep/sessions
    Body: { course_id, assessment_id?, duration_minutes? }
    → Creates a new test prep session, returns session state + first action

POST /test-prep/sessions/{session_id}/answer
    Body: { problem_id, answer, time_spent_seconds }
    → Evaluates answer, updates state, returns feedback + next action

POST /test-prep/sessions/{session_id}/skip-phase
    → Advance to next phase

GET  /test-prep/sessions/{session_id}
    → Current session state (for resume)

POST /test-prep/sessions/{session_id}/complete
    → Finalize session, store results, update mastery states
```

### 10. Test prep session UI

A single-page experience at `/test-prep/{course_id}`. HTMX + Alpine.js.

**Layout:**
```
┌────────────────────────────────────────────────────────┐
│  Chapter 4 Test Prep    ██████████░░░░░ Phase 2/5      │
│  Pre-Calculus H S2      18:32 elapsed  ·  42 min left  │
├────────────────────────────────────────────────────────┤
│                                                        │
│  ┌─ Concept Heat Map ───────────────────────────────┐  │
│  │ Poly Division   ████████████████░░ 82%  ✓        │  │
│  │ Finding Zeros   ████████░░░░░░░░░░ 45%  ⚠ focus  │  │
│  │ Rational Fns    ██████████████░░░░ 70%           │  │
│  │ Inequalities    ████████████░░░░░░ 60%           │  │
│  │ Variation       ██████████████████ 90%  ✓        │  │
│  │ End Behavior    ████████████████░░ 75%           │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ── Focused Practice: Finding Zeros ──                 │
│                                                        │
│  Q5 of ~8  ·  Difficulty: ●●●○○  ·  Streak: ✓✓✗      │
│                                                        │
│  Find all real zeros of f(x) = 2x³ - 5x² - 4x + 3    │
│  List the possible rational zeros first, then find     │
│  the actual zeros.                                     │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │                                                  │  │
│  │  [Student types or selects answer here]          │  │
│  │                                                  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  [💡 Hint (2 left)]  [📝 Show worked example]  [Skip] │
│                                                        │
│  [Submit Answer]                                       │
│                                                        │
├────────────────────────────────────────────────────────┤
│  Recent: ✓ Q4 (synthetic div) ✗ Q3 (zeros) ✓ Q2 ...  │
└────────────────────────────────────────────────────────┘
```

**After submitting an answer:**
```
┌────────────────────────────────────────────────────────┐
│  ✗ Not quite.                                          │
│                                                        │
│  You listed the possible rational zeros correctly      │
│  (±1, ±3, ±1/2, ±3/2) but made a sign error in the   │
│  synthetic division for x = 3.                         │
│                                                        │
│  The remainder is 0, so x = 3 IS a zero.              │
│  After dividing out (x - 3), you get 2x² + x - 1.    │
│  Factor that to find the other two zeros.              │
│                                                        │
│  [Try Again]  [Show Full Solution]  [Next Problem →]   │
└────────────────────────────────────────────────────────┘
```

**Diagnostic phase (Phase 1):**
```
┌────────────────────────────────────────────────────────┐
│  How confident are you on each topic?                  │
│                                                        │
│  Polynomial Division     ○ 1  ○ 2  ● 3  ○ 4  ○ 5     │
│  Finding Zeros           ○ 1  ○ 2  ○ 3  ● 4  ○ 5     │
│  Rational Functions      ○ 1  ● 2  ○ 3  ○ 4  ○ 5     │
│  Inequalities            ○ 1  ○ 2  ○ 3  ● 4  ○ 5     │
│  Variation               ○ 1  ○ 2  ○ 3  ○ 4  ● 5     │
│  End Behavior            ○ 1  ○ 2  ● 3  ○ 4  ○ 5     │
│                                                        │
│  [Start Diagnostic →]                                  │
│                                                        │
│  Then: 8-10 quick problems, ~45 seconds each.          │
│  Don't overthink — this finds your starting point.     │
└────────────────────────────────────────────────────────┘
```

**Calibration report (Phase 5):**
```
┌────────────────────────────────────────────────────────┐
│  Session Complete — Calibration Report                 │
│                                                        │
│  Overall: 23/31 correct (74%)                          │
│  Session time: 58 minutes                              │
│                                                        │
│  Concept         Confidence  Actual   Gap              │
│  ─────────────   ──────────  ──────   ────             │
│  Poly Division      3/5       82%     ✓ calibrated     │
│  Finding Zeros      4/5       45%     ⚠ overconfident  │
│  Rational Fns       2/5       70%     ↑ underconfident │
│  Inequalities       4/5       60%     ⚠ overconfident  │
│  Variation          5/5       90%     ✓ calibrated     │
│  End Behavior       3/5       75%     ✓ calibrated     │
│                                                        │
│  🔑 Key takeaway: Focus on Finding Zeros — you think  │
│  you know it but homework shows sign errors in         │
│  synthetic division and missed complex zeros.          │
│                                                        │
│  📋 Your mistakes today:                               │
│  • Synthetic division: sign error on 2 problems        │
│  • Forgot to check upper/lower bounds                  │
│  • Rational function: missed a hole at x=2             │
│                                                        │
│  [Start Another Session]  [Review Mistakes]            │
└────────────────────────────────────────────────────────┘
```

**Key UI principles:**
- Single page, no navigation. Everything happens in one view.
- Concept heat map always visible — student sees mastery updating in real-time
- Timer visible but not stressful (shows elapsed and remaining)
- Progressive hint system: first hint is gentle ("Think about what theorem applies"), third hint nearly gives the approach
- "Show worked example" always available as an escape hatch (but tracked — frequent use lowers mastery estimate)
- Problems rendered with proper math notation (KaTeX or MathJax for LaTeX)
- Mobile-responsive — student might use this on an iPad

### 11. Math rendering

Add KaTeX for rendering mathematical notation in problems and solutions.

Problems from the generator will use LaTeX notation (`\frac{1}{2}`, `x^2 + 3x - 4`, `\sqrt{x}`) which KaTeX renders inline. This is essential for a math prep tool — plain text math is unreadable for anything beyond basic algebra.

Include KaTeX CSS + JS via CDN in the base template. Use a custom Alpine.js directive or component to auto-render math content.

### 12. Schema additions

New tables:

```sql
-- Homework vision analysis results (cached, expensive to regenerate)
CREATE TABLE homework_analyses (
    id              bigint PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
    user_id         uuid NOT NULL REFERENCES auth.users(id),
    assignment_id   bigint NOT NULL,
    course_id       bigint NOT NULL,
    page_number     int NOT NULL,
    analysis_json   jsonb NOT NULL,          -- PageAnalysis structured output
    image_tokens    int,                     -- Vision tokens used
    analyzed_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, assignment_id, page_number)
);

-- Test prep sessions
CREATE TABLE test_prep_sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES auth.users(id),
    course_id       bigint NOT NULL,
    assessment_id   bigint,                  -- Optional: which test we're prepping for
    state_json      jsonb NOT NULL,          -- Full SessionState
    started_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz,
    total_problems  int DEFAULT 0,
    total_correct   int DEFAULT 0,
    duration_seconds int,
    phase_reached   text                     -- How far the student got
);

-- Per-problem results within a session
CREATE TABLE test_prep_results (
    id              bigint PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
    session_id      uuid NOT NULL REFERENCES test_prep_sessions(id) ON DELETE CASCADE,
    concept         text NOT NULL,
    problem_json    jsonb NOT NULL,          -- The generated problem
    student_answer  text,
    is_correct      boolean,
    score           float,                   -- Partial credit
    feedback        text,
    hints_used      int DEFAULT 0,
    worked_example_shown boolean DEFAULT false,
    time_spent_seconds int,
    difficulty      float,
    created_at      timestamptz NOT NULL DEFAULT now()
);
```

## Acceptance criteria

- [ ] Canvas submission attachments fetched for specific assignments (PDFs downloaded)
- [ ] PDF pages converted to images via pymupdf at sufficient quality for handwriting recognition
- [ ] AI client supports vision calls with base64-encoded images and structured output
- [ ] Homework vision analysis extracts per-problem data: problem statement, student answer, correct/incorrect, error type, concept
- [ ] Analysis results cached in `homework_analyses` table — no re-analysis of already-processed submissions
- [ ] Review guide PDFs analyzed and problems extracted with solutions
- [ ] Per-concept mastery profile computed from homework data (accuracy, common errors, misconceptions)
- [ ] Adaptive problem generator creates problems matching DePalma's style using real homework as templates
- [ ] Problems include step-by-step solutions, progressive hints, and common mistake variants
- [ ] Diagnostic phase: confidence scan + quick-fire problems per concept, results drive session focus
- [ ] Focused practice phase: worked example → faded → independent → adaptive difficulty (70-80% target)
- [ ] Error analysis phase: find-the-error problems + review of session mistakes
- [ ] Mixed test phase: interleaved problems, no hints, timed, simulates test conditions
- [ ] Calibration report: compare confidence to actual performance, highlight overconfidence gaps
- [ ] Session state persisted — student can resume if interrupted
- [ ] Concept heat map updates in real-time as student completes problems
- [ ] Math notation rendered properly (KaTeX)
- [ ] Session engine adapts difficulty within each phase (2 right → harder, 2 wrong → easier)
- [ ] Hint system is progressive (gentle → medium → strong) and tracked
- [ ] All AI calls logged with token counts and costs
- [ ] Quality gates pass

## Risks & open questions

- **Vision accuracy on handwriting** — Claude's handwriting recognition is good but not perfect, especially for messy math notation. Mitigation: the analysis is one-time and cached; inaccuracies in a few problems won't break the overall mastery profile. Could add a "review analysis" step where the student confirms/corrects the extracted data.
- **Vision API cost** — ~14 pages × 1500 tokens/page ≈ 21K input tokens for the full homework set. At current Sonnet pricing this is <$1. Acceptable as a one-time cost per assignment set.
- **Problem generation quality** — Generated problems need to actually look like DePalma's problems. The style_examples parameter is key — by feeding real homework problems as templates, Claude should match the format. May need iteration on the generation prompt.
- **Math input** — Students need to type math answers. For this first version, accept plain text ("x = 3, x = -1/2") and have the evaluator be flexible. LaTeX input is a future upgrade. Alternatively, could use multiple choice for some problem types.
- **Session length flexibility** — 60 minutes is the research-optimal default but students may want shorter (30 min) or longer (90 min) sessions. The phase durations should scale proportionally.
- **Cold start without homework** — If a student hasn't done the homework (or it's not graded yet), the system should still work using the review guide + generic concept-based problems. Homework analysis enriches but shouldn't be required.
- **Scope creep** — This ticket is specifically for Pre-Calculus Chapter 4. The architecture should generalize to any course/test, but the first implementation should be laser-focused on making Chapter 4 prep excellent.

## Dependencies

- Phase 1: FastAPI backend, Supabase schema, auth
- Phase 2: Canvas API fetcher (extends existing `fetcher.py`)
- Phase 4: AI client (extends with vision support), practice infrastructure
- Phase 5: AI audit logging, rate limiting, cost tracking
- `CANVAS_TOKEN` and `ANTHROPIC_API_KEY` environment variables
- pymupdf (already installed — provides `page.get_pixmap()`)
- KaTeX CDN (no install needed)

## Non-goals (explicitly out of scope)

- Multi-subject planning (this is Pre-Calc only)
- Generic daily planner integration
- Parent dashboard
- Teacher notifications
- Semester-long study scheduling
- Mobile app (responsive web is sufficient)
