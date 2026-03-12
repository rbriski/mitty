# Phase 5: Bounded AI Roles + Conversational Coach

## Context

Phase 4 introduced lightweight LLM integration — a simple Claude API client powering concept extraction, practice generation, and answer evaluation. This phase upgrades that foundation into a production-grade AI system with proper infrastructure, adds the conversational coach, and builds the safety/trust layer.

The key insight from the research: AI should generate practice, hints, explanations, and summaries. It should NOT control the planning logic, the evidence model, or the accountability loop. OECD's warning is direct — AI that improves task performance without improving learning creates "metacognitive laziness."

The tutor should ask more than it tells.

## Goals

- Upgrade LLM infrastructure with prompt versioning, audit logging, cost tracking, and rate limiting
- Build source retriever (RAG) for grounded AI outputs
- Ship a conversational coach that follows pedagogical rules
- Add escalation detection for patterns suggesting human help is needed
- Implement source trust controls and citation requirements
- Harden AI security (prompt injection defense, output validation)

## The AI architecture

```
┌─────────────────────────────────────────────────┐
│                  Study Plan (deterministic)       │
│                        │                         │
│         ┌──────────────┼──────────────┐          │
│         ▼              ▼              ▼          │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│   │ Practice  │  │  Coach   │  │ Evaluator│     │
│   │ Generator │  │  (chat)  │  │ (scoring)│     │
│   │ (Phase 4) │  │  (NEW)   │  │ (Phase 4)│     │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘     │
│        │              │              │           │
│        └──────────────┼──────────────┘           │
│                       ▼                          │
│              ┌──────────────┐                    │
│              │   Retriever  │                    │
│              │ (source RAG) │                    │
│              └──────┬───────┘                    │
│                     ▼                            │
│            resource_chunks                       │
│          (approved sources)                      │
│                                                  │
│   ┌──────────────┐                              │
│   │  Escalation  │ ← monitors all interactions  │
│   │  Detector    │                              │
│   └──────────────┘                              │
└─────────────────────────────────────────────────┘
```

Key constraint: **all AI tools go through the retriever**. No AI output without source grounding.

## What exists from Phase 4

Phase 4 shipped:
- `mitty/ai/client.py` — minimal Claude API wrapper (async, structured output, retry, simple cost logging)
- `mitty/practice/generator.py` — LLM-powered practice item generation with caching
- `mitty/practice/evaluator.py` — LLM-powered answer scoring with exact-match fast path
- `mitty/mastery/concepts.py` — LLM-powered concept extraction with pattern-matching fallback

This phase upgrades the client and adds new AI roles on top of the existing practice infrastructure.

## Work items

### 1. LLM infrastructure upgrade

Upgrade `mitty/ai/client.py` and create `mitty/ai/prompts.py`.

**Client upgrades:**
- Token counting and cost tracking per call → `ai_audit_log` table (add migration)
- Rate limiting (requests per minute, tokens per minute)
- Cost budgeting — configurable per-session and per-day limits with alerts

**Prompt management (new):**
- System prompts per AI role (practice_generator, coach, evaluator, explainer)
- Template system for injecting context (concept, resource chunks, student history)
- Prompt versioning — store which prompt version produced each output
- Config: model selection, temperature, max_tokens per role

**Security hardening:**
- Student inputs sanitized before inclusion in prompts (prompt injection defense)
- Outputs validated before returning to frontend
- Provider API keys server-side only — never in frontend bundles (verify Phase 4 compliance)

### 2. AI retriever (source-grounded context)

Create `mitty/ai/retriever.py`.

Given a concept/question, find the most relevant `resource_chunks`:

| Retrieval method | Implementation |
|-----------------|----------------|
| Keyword/BM25 | Text search against chunk content — start here |
| Embedding similarity | Generate embeddings for chunks, use vector similarity — upgrade path |

Returns: top-k chunks with source attribution (`resource_id`, `chunk_index`, `resource.title`).

**Critical rule**: If retriever returns insufficient results (< threshold), the AI tool must say "I don't have enough source material for this topic" rather than hallucinate. Surface this as "No study materials" in the UI with a prompt to add resources.

**Integration**: Wire the retriever into Phase 4's practice generator and evaluator so they use grounded retrieval instead of directly-passed chunks.

### 3. Conversational coach

Create `mitty/ai/coach.py` + chat API endpoints + chat UI.

The coach is conversational but strictly bounded:

**Scope restrictions:**
- Only discusses the current study block's topic
- Only uses approved resource_chunks as context (via retriever)
- Chat session scoped to the block — no free-form open-ended chatting
- Cannot access or discuss other students' data

**Pedagogical rules (enforced in system prompt):**
1. Ask for recall before showing help ("What do you remember about this?")
2. Give hints before solutions ("Think about what happens when...")
3. Use worked examples, then fade scaffolding
4. Ask for explanation in student's own words ("Can you explain that back to me?")
5. Check understanding unassisted ("Try this one without any help")
6. Log what was missed for later spacing (update mastery)

**Anti-patterns the coach must avoid:**
- Giving the answer immediately
- Doing the homework for her
- Making up facts not in the source material
- Being overly verbose or lecture-like
- Letting the conversation drift off-topic

**Chat storage:**
- Store per study_block: messages (role, content, timestamp), sources cited
- Accessible for audit but NOT shown to parents (privacy — Phase 7)

### 4. Escalation detector

Create `mitty/ai/escalation.py`.

Monitor for patterns suggesting human help is needed:

| Signal | Threshold | Action |
|--------|-----------|--------|
| Repeated failures | 3+ incorrect on same concept | Flag for teacher/tutor help |
| High stress | Stress 4-5 in check-in + low completion | Suggest break or lighter plan |
| Avoidance | Skipping blocks repeatedly (3+ days) | Surface gently: "noticed you've been skipping Bio" |
| Frustration in chat | Sentiment analysis or explicit signals | Offer break, suggest human help |
| Grade dropping despite practice | Practice happening but grades still falling | "This topic might need a different approach — consider asking your teacher" |
| Confidence crash | Confidence drops significantly session-over-session | Positive reinforcement + lighter load |

Escalation outputs:
- In-app notification to student (gentle, not alarming)
- Optional parent notification (configurable)
- Escalation log with context (which concept, evidence, suggested action)
- Never auto-contacts teachers — that's a parent decision

### 5. Source trust controls

Every AI-generated output must include citations. Add trust infrastructure:

**Source trust scoring:**

| Source type | Trust level |
|-------------|------------|
| Verified textbook | High |
| Canvas official page | High |
| Canvas assignment/quiz | Medium |
| Student notes | Low |
| Web link | Low |
| No source | Not allowed for factual claims |

**Enforcement:**
- AI outputs must cite source chunks
- When generating from low-trust sources, disclose it ("Based on your notes, which may be incomplete...")
- When no sources exist for a concept, refuse to generate practice and say so
- Source coverage metric: what % of mastery_states concepts have adequate resource backing?
- Surface gaps in mastery dashboard: "No study materials for: Topic X — add resources to enable practice"

### 6. Coach chat UI

The chat interface within a study block:

```
┌──────────────────────────────────────────┐
│  Coach: Biology Ch.7 — Cellular Resp.    │
│  Sources: Bio textbook Ch.7, Class notes │
│                                          │
│  ┌─────────────────────────────────────┐ │
│  │ 🤖 Before we start, what do you    │ │
│  │    remember about how cells make    │ │
│  │    energy?                          │ │
│  └─────────────────────────────────────┘ │
│  ┌─────────────────────────────────────┐ │
│  │ 👩 um mitochondria? and glucose     │ │
│  │    gets broken down                 │ │
│  └─────────────────────────────────────┘ │
│  ┌─────────────────────────────────────┐ │
│  │ 🤖 Good start! You got the key     │ │
│  │    organelle. Can you walk me       │ │
│  │    through the steps of how glucose │ │
│  │    actually becomes ATP?            │ │
│  │    📖 Ch.7, p.142                   │ │
│  └─────────────────────────────────────┘ │
│                                          │
│  [Type your answer...]          [Send]   │
│                                          │
│  [🚩 Flag this response]                │
└──────────────────────────────────────────┘
```

UI features:
- Current topic + sources sidebar (or top bar on mobile)
- Chat messages with source citations inline
- "Try to answer first" prompt before AI helps
- "Explain in your own words" checkpoints
- Summary at block end (what was covered, what to review)
- "Flag this response" button for student/parent to report bad output
- Chat history persistent per block

## Acceptance criteria

- [ ] LLM client upgraded with audit logging to `ai_audit_log` table, prompt versioning, cost tracking
- [ ] Rate limiting and cost budgeting enforced
- [ ] Retriever returns relevant chunks with source attribution, refuses when sources insufficient
- [ ] Practice generator and evaluator (Phase 4) wired through retriever for source grounding
- [ ] Conversational coach follows pedagogical rules (ask before tell, hints before answers)
- [ ] Coach is scoped to current block topic and approved sources only
- [ ] Escalation detector flags repeated failure, high stress, avoidance patterns
- [ ] Source trust scoring works, low-trust sources are disclosed, no-source gaps are surfaced
- [ ] Chat UI works on mobile with block context and source display
- [ ] "Flag this response" mechanism works
- [ ] All AI calls logged to audit table with prompt version, tokens, cost
- [ ] API keys are server-side only, prompt injection defenses in place
- [ ] Quality gates pass

## Risks & open questions

- **LLM cost** — Coach conversations are the biggest cost driver (multi-turn). Track cost per session and set budget alerts. Consider streaming to reduce perceived latency.
- **Prompt injection** — Student inputs go into LLM prompts. Sanitize inputs, use structured prompts, validate outputs.
- **Pedagogical rule enforcement** — System prompts can be ignored by the model. Need output validation: did the coach actually ask a question before giving an answer? Test with adversarial inputs.
- **"Do my homework" risk** — The coach must not do homework for the student. Scope restrictions + system prompt + output validation. Consider: if the current study block is "urgent deliverable" (homework), should the coach be available at all? Maybe only for "retrieval" and "explanation" blocks.
- **Response quality** — LLM explanations may be wrong or misleading. Source grounding reduces but doesn't eliminate this. The "flag" button and audit log are safety nets.
- **Latency** — Coach chat needs to feel responsive. Stream responses. Cache retriever results within a session.

## Dependencies

- Phase 1: backend API, schema (for ai_audit_log table — add migration)
- Phase 2: resources + resource_chunks (content for retrieval)
- Phase 3: planner + study blocks (coach scoped to blocks)
- Phase 4: practice system + mastery tracking + lightweight LLM client (this phase upgrades and extends)
