# Homework Viewer — Upcoming Assignments by Class

## Context

The grades dashboard (`web/index.html`) currently shows overall grades and the privilege scoreboard. Parents also need to see **what's due this week** so they can check whether homework is getting done. All assignment data is already in Supabase — we just need a new view.

## Goals

- Show upcoming assignments (next 7 days) grouped by class
- Click into a class from the grades dashboard to see its assignments
- Show submission status for each assignment (submitted, graded, missing, unsubmitted)
- Link each assignment back to Canvas for details

## Data Available (Supabase)

### `assignments` table
| Column | Type | Example |
|--------|------|---------|
| id | int (PK) | 269377 |
| course_id | int (FK) | 4127 |
| name | text | "(14.4) Homework" |
| due_at | timestamp (nullable) | "2026-03-25T22:00:00" |
| points_possible | float (nullable) | 5.0 |
| html_url | text | "https://mitty.instructure.com/courses/..." |

### `submissions` table (1:1 with assignments via `assignment_id`)
| Column | Type | Example |
|--------|------|---------|
| assignment_id | int (PK/FK) | 269377 |
| score | float (nullable) | 48.0 |
| grade | text (nullable) | "48" |
| workflow_state | text | "graded" / "unsubmitted" |
| late | bool | false |
| missing | bool | true |

### Data observations
- Many assignments have `due_at = null` (undated or past) — filter these out
- `points_possible` can also be null — display "—" when missing
- Submission `workflow_state` values: `"unsubmitted"`, `"graded"`, `"submitted"`, `"pending_review"`
- `late` and `missing` flags are independent of workflow_state
- `html_url` always present — links to Canvas assignment page
- Courses: Pre-Calc (4127), Spanish (4204), Chemistry (4214), AP US History (4220), American Lit (4222)

### Supabase query

```js
const now = new Date().toISOString();
const weekLater = new Date(Date.now() + 7 * 86400000).toISOString();

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

## UX Design

### Navigation
- Grade cards on the dashboard become clickable
- Clicking a class card navigates to a detail view for that class
- Back button returns to the dashboard
- Alternatively: a new "Homework" tab/section below the scoreboard

### Class Detail View (recommended approach)
When clicking a class card:

```
  ← Back to Grades

  AP US History                          Current: 72.3%  C
  ─────────────────────────────────────────────────────────

  THIS WEEK
  ┌─────────────────────────────────────────────────────┐
  │ Mon 3/10  Read AMSCO "Topics 7.11"          —  pts  │
  │           ○ Not submitted                           │
  │                                                     │
  │ Wed 3/12  Great Depression Deliberation    20  pts  │
  │           ○ Not submitted                           │
  │                                                     │
  │ Wed 3/12  1920s Film Clip Review           10  pts  │
  │           ○ Not submitted                           │
  │                                                     │
  │ Sat 3/14  AP Poetry Prompt Impromptu      100  pts  │
  │           ✓ Graded: 85/100                          │
  └─────────────────────────────────────────────────────┘

  LATER
  ┌─────────────────────────────────────────────────────┐
  │ Mon 3/16  Read AMSCO "Topics 7.12"          —  pts  │
  │           ○ Not submitted                           │
  └─────────────────────────────────────────────────────┘
```

### Assignment status indicators
| State | Display |
|-------|---------|
| `workflow_state: "graded"` | Green checkmark, show score/points |
| `workflow_state: "submitted"` | Blue dot, "Submitted" |
| `workflow_state: "unsubmitted"` + `missing: true` | Red warning, "Missing" |
| `workflow_state: "unsubmitted"` + `missing: false` | Gray circle, "Not submitted" |
| `late: true` | Orange "Late" tag alongside status |

### Mobile considerations
- Cards should stack vertically on mobile
- Assignment names can be long — truncate with ellipsis on small screens
- Due date should be prominent (day of week + date)

## Implementation

### Approach: Alpine.js routing within single HTML file
- Use Alpine.js `x-show` to toggle between dashboard and class detail views
- No new files needed — extend `web/index.html`
- Store selected class in Alpine state, filter assignments client-side
- Add a "Homework" summary section on the main dashboard showing total upcoming count

### Changes to `web/index.html`
1. Make grade cards clickable (`@click="selectClass(item)"`)
2. Add class detail view template (hidden by default)
3. Fetch assignments + submissions alongside grades in `fetchGrades()` (or lazy-load on click)
4. Add status indicator helper functions
5. Add back navigation

### Supabase RLS
If RLS is enabled on `assignments` and `submissions`, add read policies:
```sql
CREATE POLICY "Authenticated read" ON assignments FOR SELECT TO authenticated USING (true);
CREATE POLICY "Authenticated read" ON submissions FOR SELECT TO authenticated USING (true);
```

## Out of scope
- Editing/submitting assignments (read-only view)
- Push notifications for upcoming due dates
- Calendar view (consider for future iteration)
- Overdue assignments (past due, not submitted) — could add later as "Missing" section

## Decisions
- **Show overdue/missing assignments**: Yes — add an "Overdue" section above "This Week" showing assignments past due that are unsubmitted or missing
- **Lookahead window**: 7 days
- **Homework count badge**: Yes — show a badge on each grade card on the main dashboard with the count of upcoming assignments due in the next 7 days
