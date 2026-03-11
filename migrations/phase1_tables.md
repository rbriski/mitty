# Phase 1 Supabase Migrations

Applied via Supabase MCP `apply_migration` tool.

## Extension

- **pgvector** (`vector` type in `extensions` schema) -- enables embedding storage

## Tables Created (9)

| Table | RLS | Key relationships |
|-------|-----|-------------------|
| `app_config` | Yes (public read, auth update) | Singleton (CHECK id=1) |
| `assessments` | Yes (auth required) | FK courses, optional FK assignments |
| `resources` | Yes (auth required) | FK courses |
| `resource_chunks` | Yes (auth required) | FK resources (CASCADE delete), vector(1536) column |
| `student_signals` | Yes (user_id scoped) | FK auth.users |
| `study_plans` | Yes (user_id scoped) | FK auth.users, UNIQUE(user_id, plan_date) |
| `study_blocks` | Yes (join-based via plan) | FK study_plans (CASCADE), optional FK courses, assessments |
| `mastery_states` | Yes (user_id scoped) | FK auth.users, FK courses, UNIQUE(user_id, course_id, concept) |
| `practice_results` | Yes (user_id scoped) | FK auth.users, FK courses, optional FK study_blocks (SET NULL) |

## Indexes (10)

- `ix_assessments_course_scheduled` -- (course_id, scheduled_date)
- `ix_assessments_scheduled_date` -- (scheduled_date)
- `ix_resources_course_type` -- (course_id, resource_type)
- `ix_student_signals_user_recorded` -- (user_id, recorded_at DESC)
- `ix_study_plans_user_date` -- (user_id, plan_date DESC)
- `ix_study_blocks_plan_sort` -- (plan_id, sort_order)
- `ix_mastery_states_user_course` -- (user_id, course_id)
- `ix_mastery_states_user_review` -- (user_id, next_review_at)
- `ix_practice_results_user_created` -- (user_id, created_at DESC)
- `ix_practice_results_user_course` -- (user_id, course_id)

Note: IVFFlat index on `resource_chunks.embedding_vector` deferred until data exists.

## RLS Policies

- **User-scoped tables** (student_signals, study_plans, mastery_states, practice_results): `auth.uid() = user_id` for all operations
- **study_blocks**: join-based via study_plans to verify ownership
- **Course-level tables** (assessments, resources, resource_chunks): any authenticated user
- **app_config**: public SELECT, authenticated UPDATE only

## Seed Data

- `app_config` row: term "2025-2026 Second Semester", privilege thresholds [8, 10, 11, 12], privilege names ["Phone", "Car", "Snapchat", "Homework in Bedroom"]
