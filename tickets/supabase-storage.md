# Supabase Storage — Replace JSON Output with Database

## Context

The Canvas scraper currently outputs all data (courses, assignments, enrollments) as JSON to stdout. Instead, we want to persist this data into Supabase (hosted Postgres) so it can be queried, tracked over time, and consumed by other tools.

## Goals

- Store scraped Canvas data in Supabase tables instead of dumping JSON to stdout
- Enable incremental updates (upsert on scrape, not full replace)
- Track grade/score changes over time (historical snapshots)
- Keep the existing JSON output as an optional `--json` flag for debugging

## Proposed Schema

### `courses`
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | Canvas course ID |
| name | text | |
| course_code | text | |
| workflow_state | text | |
| term_name | text | Denormalized from term object |
| term_id | bigint | |
| updated_at | timestamptz | Last scraped |

### `assignments`
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | Canvas assignment ID |
| course_id | bigint (FK) | |
| name | text | |
| due_at | timestamptz | Nullable |
| points_possible | float | |
| html_url | text | |
| updated_at | timestamptz | Last scraped |

### `submissions`
| Column | Type | Notes |
|--------|------|-------|
| assignment_id | bigint (PK) | Canvas assignment ID |
| score | float | Nullable |
| grade | text | Nullable |
| submitted_at | timestamptz | Nullable |
| workflow_state | text | |
| late | boolean | |
| missing | boolean | |
| updated_at | timestamptz | Last scraped |

### `enrollments`
| Column | Type | Notes |
|--------|------|-------|
| id | bigint (PK) | Canvas enrollment ID |
| course_id | bigint (FK) | |
| type | text | e.g. StudentEnrollment |
| enrollment_state | text | |
| current_score | float | Nullable |
| current_grade | text | Nullable |
| final_score | float | Nullable |
| final_grade | text | Nullable |
| updated_at | timestamptz | Last scraped |

### `grade_snapshots` (historical tracking)
| Column | Type | Notes |
|--------|------|-------|
| id | bigserial (PK) | |
| course_id | bigint (FK) | |
| current_score | float | Nullable |
| current_grade | text | Nullable |
| final_score | float | Nullable |
| final_grade | text | Nullable |
| scraped_at | timestamptz | When this snapshot was taken |

## Implementation Notes

- Add `supabase` Python SDK as a dependency (or use raw `httpx` + Supabase REST API)
- New env vars: `SUPABASE_URL`, `SUPABASE_KEY` (anon or service role key)
- New module: `mitty/storage.py` (or `mitty/supabase.py`) with upsert functions
- Use Supabase upsert (`on_conflict`) for idempotent writes
- Insert a `grade_snapshots` row on each scrape for historical tracking
- Default behavior changes from JSON stdout to Supabase write; add `--json` flag to preserve old behavior
- Migrations: SQL files in `migrations/` or use Supabase dashboard

## Open Questions

- Should we use the Supabase Python SDK or raw REST API via httpx (already a dep)?
- Row-level security (RLS) — needed if this stays single-user?
- How frequently will scrapes run? (affects snapshot table growth)
