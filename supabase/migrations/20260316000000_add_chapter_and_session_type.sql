-- Phase 8a: US-001 — Add chapter column to assignments, session_type to test_prep_sessions
-- DEC-001: nullable chapter text on assignments for upcoming assessment detection
-- DEC-004: session_type on test_prep_sessions for quick vs full session support

-- =========================================================================
-- 1. assignments.chapter (nullable text)
-- =========================================================================

ALTER TABLE assignments
    ADD COLUMN IF NOT EXISTS chapter text;

-- =========================================================================
-- 2. test_prep_sessions.session_type (NOT NULL, default 'full', CHECK)
-- =========================================================================

ALTER TABLE test_prep_sessions
    ADD COLUMN IF NOT EXISTS session_type text NOT NULL DEFAULT 'full'
        CHECK (session_type IN ('full', 'quick'));
