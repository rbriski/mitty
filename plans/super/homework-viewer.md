# Super Plan: Homework Viewer — Upcoming Assignments by Class

## Meta
- **Ticket:** tickets/homework-viewer.md
- **Phase:** detailing
- **Branch:** feature/homework-viewer
- **Created:** 2026-03-10
- **Sessions:** 1

---

## Phase 1: Discovery

### Ticket Summary
Add a homework viewer to the grades dashboard (`web/index.html`) that shows upcoming assignments (next 7 days) grouped by class. Users click a grade card to see a class detail view with assignments, submission status, and links back to Canvas.

**Key goals:**
- Grade cards become clickable → class detail view
- Show overdue/missing assignments section above "This Week"
- Show upcoming 7-day assignments sorted by due date
- Status indicators: graded (green), submitted (blue), missing (red), unsubmitted (gray), late (orange)
- Homework count badge on grade cards on main dashboard
- Link each assignment to Canvas via `html_url`
- Back navigation to dashboard

### Codebase Findings

**Single file to modify:** `web/index.html` (495 lines)
- Alpine.js `app()` with `x-data`/`x-init` pattern
- Supabase JS for auth + queries
- Tailwind CSS via CDN
- Current view: login → dashboard (privilege scoreboard + grade cards)
- No routing yet — need to add `x-show` view toggling

**Data available in Supabase:**
- `assignments` table: `id, course_id, name, due_at, points_possible, html_url`
- `submissions` table: `assignment_id (PK/FK), score, grade, workflow_state, late, missing`
- `courses` table: `id, name, course_code, term_name, workflow_state`
- FK relationships enable Supabase join queries

**Supabase query from ticket:**
```js
const { data } = await supabase
  .from('assignments')
  .select(`
    id, name, due_at, points_possible, html_url, course_id,
    courses!inner (name, course_code, term_name, workflow_state),
    submissions (score, grade, workflow_state, late, missing)
  `)
  .eq('courses.term_name', '2025-2026 Second Semester')
  .gte('due_at', now)
  .lte('due_at', weekLater)
  .order('due_at', { ascending: true });
```

### Proposed Scope
- Extend `web/index.html` with Alpine.js view toggling (dashboard vs class detail)
- Add `fetchAssignments()` method for Supabase query
- Add assignment list UI with status indicators
- Add overdue section (past due, unsubmitted/missing)
- Add homework count badge on grade cards
- No backend changes needed

### Scoping Questions

**A. Assignment fetching strategy:**
1. **Eager** — Fetch all assignments for all classes on dashboard load, filter client-side per class
2. **Lazy** — Fetch assignments only when clicking into a class (one query per click)
3. **Hybrid** — Fetch counts for badges eagerly, full details lazily

**B. Overdue assignments — how far back?**
1. 7 days back (matching the forward lookahead)
2. 14 days back
3. All overdue this semester (could be many)
4. Configurable / user preference

**C. "Later" section — show assignments beyond 7 days?**
The ticket mockup shows a "Later" section. Should we:
1. Show next 7 days only, no "Later" section
2. Show 7-day detail + a "Later" preview (next 7-14 days)
3. Show all future assignments for the semester

**D. Navigation pattern:**
1. **Replace view** — clicking a card replaces the entire dashboard with class detail (with back button)
2. **Slide-in panel** — class detail slides in from the right as an overlay
3. **Expand in-place** — card expands to show assignments below it

**E. Badge on grade cards — what to count?**
1. All upcoming assignments (next 7 days)
2. Only unsubmitted assignments (actionable items)
3. Only overdue/missing assignments (urgency-focused)

---

## Phase 2: Architecture Review

| Area | Rating | Key Finding |
|------|--------|-------------|
| Security | **pass** | `x-text` prevents XSS, anon key is publishable, auth session enforced. RLS is a concern for multi-user but OK for single-user now. |
| Performance | **pass** | ~100-200ms per query at current scale (50 assignments/course). No N+1 risk with Supabase joins. |
| Data Model | **pass** | FKs correct. 1:1 assignments→submissions via PK. LEFT JOIN handles missing submission rows. Filter `due_at IS NOT NULL`. |
| API Design | **pass** | Read-only Supabase queries, no new endpoints. Existing auth flow covers access control. |
| Testing | **pass** | Frontend-only change, no backend modifications. Manual browser testing sufficient. |

### Concerns (non-blocking)
1. **RLS policies** — `assignments` and `submissions` tables may lack RLS read policies for authenticated users. Currently OK (single-user), but should add before multi-user support. Track as follow-up.
2. **Missing submissions** — Some assignments may not have a submission row yet. Use LEFT JOIN behavior (Supabase returns `null` for missing relation). Treat as "unsubmitted".
3. **Index on due_at** — No index on `assignments.due_at`. Fine at current scale (<500 rows), add composite `(course_id, due_at)` index if performance degrades later.

---

## Phase 3: Refinement

No blockers from architecture review. Remaining concerns resolved below.

---

## Phase 4: Detailing

### US-001: Add view toggling and assignment state to Alpine.js app

**Description:** Add Alpine.js state properties and methods for view navigation (dashboard ↔ class detail) and assignment data. Wire up `selectClass()` to set the selected class and trigger assignment fetch.

**Traces to:** DEC-004 (replace view), DEC-001 (hybrid fetch), DEC-007 (single badge query)

**Acceptance criteria:**
- `currentView` property toggles between `'dashboard'` and `'classDetail'`
- `selectedClass` holds the clicked grade item
- `assignments`, `overdueAssignments` arrays populated from Supabase
- `assignmentCounts` map holds per-course unsubmitted counts for badges
- `selectClass(item)` sets view to `'classDetail'` and calls `fetchAssignments(courseId)`
- `goBack()` returns to dashboard view
- `fetchAssignmentCounts()` runs on dashboard load alongside `fetchGrades()`

**Done when:** View toggling works (no UI yet), assignment data is fetched and logged to console.

**Files:** `web/index.html` — Alpine.js `app()` return object + new methods

**Depends on:** none

---

### US-002: Badge counts on grade cards

**Description:** Show a badge on each grade card with the count of unsubmitted assignments due in the next 7 days. Uses the eagerly-fetched `assignmentCounts` from US-001.

**Traces to:** DEC-005 (badge = unsubmitted), DEC-007 (single query, client-side count)

**Acceptance criteria:**
- Each grade card shows a pill/badge with unsubmitted count (e.g., "3 due")
- Badge hidden when count is 0
- Badge uses attention color (amber/red) to draw the eye
- Grade cards have `cursor-pointer` and click handler `@click="selectClass(item)"`

**Done when:** Dashboard grade cards show accurate unsubmitted counts and are clickable.

**Files:** `web/index.html` — grade card template (lines 225-256)

**Depends on:** US-001

---

### US-003: Class detail view — header and back navigation

**Description:** Add the class detail view template that replaces the dashboard when a class is selected. Includes back button, class name, current grade/score display.

**Traces to:** DEC-004 (replace view navigation)

**Acceptance criteria:**
- Dashboard hidden when `currentView === 'classDetail'`
- Class detail view shows: back arrow, class name, course code, current grade bubble, current score %
- Back button calls `goBack()` and returns to dashboard
- Loading spinner while assignments are fetching
- Error state if fetch fails

**Done when:** Clicking a grade card shows class detail header with back navigation; clicking back returns to dashboard with scoreboard intact.

**Files:** `web/index.html` — new template section after the dashboard `</template>`

**Depends on:** US-001

---

### US-004: Assignment list — overdue, this week, later sections

**Description:** Render the assignment list within the class detail view, grouped into three sections: Overdue (past due, unsubmitted/missing), This Week (next 7 days), and Later (7-14 days). Each assignment shows date, name, points, and a link to Canvas.

**Traces to:** DEC-002 (all overdue), DEC-003 (7+7 window), DEC-008 (overdue most recent first), DEC-006 (hide no-submission)

**Acceptance criteria:**
- "Overdue" section: past-due assignments with `workflow_state != 'graded'` and `missing: true` or `workflow_state: 'unsubmitted'`, sorted most recent first
- "This Week" section: assignments due in next 7 days, sorted by due date ascending
- "Later" section: assignments due 7-14 days out, sorted by due date ascending
- Each assignment row: day-of-week + date, assignment name (truncated on mobile), points possible (or "—"), link icon to Canvas `html_url`
- Sections hidden when empty
- Assignments without a submission row are hidden (DEC-006)

**Done when:** All three sections render correctly with real Supabase data, grouped and sorted per spec.

**Files:** `web/index.html` — class detail view template

**Depends on:** US-003

---

### US-005: Submission status indicators

**Description:** Add status indicators to each assignment row showing submission state with color-coded icons and labels.

**Traces to:** DEC-006 (hide no-submission), ticket spec (status indicator table)

**Acceptance criteria:**
- `workflow_state: "graded"` → green checkmark + "Graded: score/points"
- `workflow_state: "submitted"` → blue dot + "Submitted"
- `workflow_state: "unsubmitted"` + `missing: true` → red warning + "Missing"
- `workflow_state: "unsubmitted"` + `missing: false` → gray circle + "Not submitted"
- `late: true` → orange "Late" tag alongside any status
- Helper method `assignmentStatus(submission)` returns `{ icon, label, colorClass }`

**Done when:** Each assignment shows correct status indicator matching its submission data.

**Files:** `web/index.html` — assignment row template + helper method in `app()`

**Depends on:** US-004

---

### US-006: Empty state and encouraging message

**Description:** When a class has zero upcoming or overdue assignments, show an "All caught up!" message with a checkmark.

**Traces to:** DEC-009 (encouraging empty state)

**Acceptance criteria:**
- When `assignments.length === 0` and `overdueAssignments.length === 0`, show centered "All caught up!" with green checkmark
- Friendly, encouraging tone
- Consistent styling with dashboard empty state

**Done when:** Clicking into a class with no assignments shows the encouraging empty state.

**Files:** `web/index.html` — class detail view template

**Depends on:** US-004

---

### US-007: Quality Gate — code review + validation

**Description:** Run code reviewer across the full changeset, fix all real bugs. Run quality gates.

**Acceptance criteria:**
- 4 passes of code review across all changes, fixing real bugs each pass
- CodeRabbit review if available
- All quality gates pass: `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`
- Manual browser test: login → dashboard with badges → click class → see assignments → back → verify scoreboard intact

**Done when:** All reviews complete, all gates green, manual test passes.

**Files:** `web/index.html`

**Depends on:** US-001, US-002, US-003, US-004, US-005, US-006

---

### US-008: Patterns & Memory — update conventions and docs

**Description:** Update memory files with new patterns learned from this feature (view toggling, Supabase joins, badge pattern).

**Acceptance criteria:**
- Memory updated with frontend patterns if any new conventions emerged
- Any gotchas documented

**Done when:** Memory files reflect lessons learned.

**Files:** `~/.claude/projects/-Users-bbriski-dev-mitty/memory/MEMORY.md`

**Depends on:** US-007

---

## Phase 5: Publish PR
*(Pending Phase 4)*

---

## Decisions Log

- **DEC-001: Hybrid fetch** — Fetch assignment counts eagerly on dashboard load (for badges), full assignment details lazily on class click. Balances UX responsiveness with minimal initial load.
- **DEC-002: All overdue this semester** — Show all overdue unsubmitted/missing assignments, not just recent ones. Parents need full visibility into what's been missed.
- **DEC-003: 7+7 day window** — Show "This Week" (next 7 days) in detail, plus a "Later" preview (7-14 days). Gives enough forward visibility without overwhelming.
- **DEC-004: Replace view navigation** — Clicking a grade card replaces the dashboard with a class detail view + back button. Simple, mobile-friendly, no complex overlays.
- **DEC-005: Badge = unsubmitted count** — Badge on grade cards shows count of unsubmitted assignments (next 7 days). Focuses on actionable items parents care about.
- **DEC-006: Hide assignments without submissions** — If an assignment has no submission row, hide it entirely rather than showing "Not submitted". Avoids noise from unsynced data.
- **DEC-007: Single query for badge counts** — Fetch all assignments for all courses in next 7 days with submissions in one Supabase query, count unsubmitted client-side. No migration/RPC needed.
- **DEC-008: Overdue sorted most recent first** — Overdue section shows assignments closest to today at top. Most actionable items surface first.
- **DEC-009: Encouraging empty state** — When a class has zero assignments, show "All caught up!" with a checkmark. Positive reinforcement.

---

## Beads Manifest
*(Populated on devolve)*
