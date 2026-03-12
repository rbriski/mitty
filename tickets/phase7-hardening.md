# Phase 7: Privacy, Permissions, Hardening, and Polish

## Context

This is the final phase. The study OS works end-to-end: ingestion, planning, practice, mastery tracking, AI coaching, evaluation, and parent visibility. Now make it sustainable, safe, and ready for daily use across school terms.

This phase combines the privacy/permissions work with production polish — because they're both about making the system trustworthy and durable.

## Goals

- Implement role-based access (student vs. parent)
- Add audit trails for AI interactions
- Handle data retention and the 18th birthday transition
- Add content rights awareness
- Harden the API (rate limiting, input validation)
- Support multiple school terms
- Optimize for mobile daily use
- Build onboarding and notification systems
- Add study streaks and feedback loops

## Work items

### Privacy & Permissions

#### 1. Role-based access control
- **Student role**: full access to study plans, practice, coach, their own data
- **Parent role**: read access to grades, metrics, progress reports, escalation alerts
- Parents should NOT see: individual chat logs, specific practice answers, detailed emotional check-in data
- Use Supabase Auth roles or a `user_roles` table
- Enforce at API middleware layer + Supabase RLS policies

#### 2. AI interaction audit trail
- Log every AI call: prompt sent, response received, model, tokens, cost, timestamp, study block context
- `ai_audit_log` table — append-only, not deletable by student
- Parent-accessible: high-level "AI activity summary" (X coach sessions, Y practice items generated this week) but NOT full conversation logs
- Used for: debugging, cost tracking, safety review, compliance

#### 3. Data retention policies

| Data type | Retention | Rationale |
|-----------|-----------|-----------|
| practice_results | Indefinite | Needed for mastery tracking |
| chat_logs | 90 days detail, then summarize | Privacy, storage |
| student_signals | 30 days detail, then aggregate | Privacy |
| ai_audit_log | 1 year | Compliance |
| grade_snapshots | Indefinite | Historical trend analysis |
| metric_snapshots | Indefinite | Trend reporting |

Add a cleanup job on schedule. Include "download my data" export.

#### 4. 18th birthday transition
Under FERPA, educational record rights transfer from parent to student at age 18.

- Add student birthdate field
- Calculate transition date
- When triggered: notify both, change parent to requires-student-consent, student can grant/revoke parent access per category
- Design now, build the framework, activate when relevant

#### 5. Content rights awareness
- Track provenance per resource: `source_type` (canvas_official, textbook_scan, student_notes, web_link), `is_copyrighted`, `usage_rights`
- Warning in resource upload: "Uploading copyrighted material is for personal study use only"
- Do NOT ingest copyrighted textbook content into embeddings without flagging the rights question
- Guardrail, not legal solution

#### 6. API hardening
- Rate limiting: per-user limits, especially on AI endpoints
- Input size limits on chat messages and practice answers
- Prompt injection detection on inputs going to LLM
- Prevent coach from being used as general-purpose chatbot
- Request logging for anomaly detection
- Supabase RLS policies for ALL new tables
- Verify frontend anon key can only access what it should

### Production Polish

#### 7. Multi-term support
- Remove hardcoded `'2025-2026 Second Semester'` filter
- Auto-detect current term from Canvas enrollment data
- Term selector in UI for viewing historical data
- Archive old term data, carry forward mastery data across terms (concepts persist)
- Handle summer breaks: no active courses, but spaced review can continue

#### 8. Mobile optimization
The student will primarily use this on her phone.

Optimize:
- Check-in flow: thumb-friendly, fast, big tap targets
- Study plan: swipeable blocks, clear actions
- Practice session: readable questions, large answer areas
- Coach chat: standard mobile chat UX
- Test on iOS Safari and Android Chrome
- The check-in → plan → practice flow should feel native-app smooth

#### 9. Onboarding flow
First-time experience:
1. Connect Canvas account (enter token or OAuth)
2. Set up student profile (name, grade level, birthday)
3. Enter available study time preferences (weekday vs. weekend defaults)
4. Add first assessments (upcoming tests this week)
5. Do first check-in
6. Generate first study plan

Walk through each step. Show the privilege scoreboard as a motivating hook.

#### 10. Notification system

| Notification | Trigger | Channel |
|-------------|---------|---------|
| Study reminder | Configured time (e.g., 4pm school days) | In-app, optional push |
| Test approaching | 3 days and 1 day before | In-app, optional email |
| Grade change | Improvement or decline detected | In-app |
| Escalation | Metrics engine flags concern | In-app + parent email |
| Weekly report | Sunday evening | In-app + optional email |

All configurable: on/off per type, quiet hours.

#### 11. Study streaks and motivation
- Track daily study completion streaks
- Celebrate milestones (7-day, 30-day streaks)
- Acknowledge completed blocks positively
- Highlight mastery improvements
- If she misses a day, streak resets quietly — no guilt messaging
- The system should be encouraging, never punitive

#### 12. Plan feedback loop
After each study session, quick feedback:
- "Was tonight's plan helpful?" (thumbs up/down)
- "What would you change?" (optional text)
- "Was anything too easy or too hard?" (optional per-block)

Use feedback to tune block durations, difficulty calibration, priority weights over time. This is how the deterministic planner gets smarter without needing AI to drive it.

#### 13. Data export and calendar integration
- Download grades/mastery report as PDF
- Export study plan to Google Calendar / Apple Calendar (iCal)
- Export practice history and mastery data as CSV
- Calendar integration: auto-add study blocks so they show alongside other commitments

## Acceptance criteria

- [ ] Role-based access enforced: parent cannot see chat logs or detailed check-in data
- [ ] AI audit log captures all LLM interactions with cost tracking
- [ ] Data retention cleanup job runs and respects retention policies
- [ ] 18th birthday transition framework exists (even if not yet triggered)
- [ ] Content rights metadata tracked per resource
- [ ] API rate-limited, input-validated, prompt injection defended
- [ ] RLS policies cover all tables
- [ ] Multi-term support works: current term auto-detected, historical terms viewable
- [ ] App usable on mobile for the full check-in → plan → practice flow
- [ ] Onboarding walks through setup in a clear sequence
- [ ] Notifications work for at least: study reminder, test approaching, weekly report
- [ ] Study streaks tracked and displayed
- [ ] Plan feedback collected and stored
- [ ] Data export works (at least CSV for practice/mastery)
- [ ] Quality gates pass

## Risks & open questions

- **Scope** — This phase is large. It could be split into 7a (privacy/hardening) and 7b (polish/mobile) if needed.
- **Mobile PWA vs. native** — PWA is simpler but push notifications are limited on iOS. Evaluate whether PWA is sufficient or if a native wrapper (Capacitor, React Native) is needed.
- **FERPA compliance** — The 18th birthday transition is the right framework, but actual compliance may need legal review if this ever goes beyond personal family use.
- **Notification fatigue** — Start with fewer notifications, let the student configure up. Default to quiet.
- **Feedback loop convergence** — The plan feedback system needs enough data to be useful. Start collecting feedback early, but don't tune weights until there's a meaningful sample.

## Dependencies

- All previous phases (1-6) complete
- This phase can start partially in parallel with Phase 6 (especially mobile optimization and multi-term support)
