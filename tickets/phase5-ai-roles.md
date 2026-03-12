# Phase 5: Bounded AI Roles + Conversational Coach

## Context

By this phase, the study OS has a working planner, practice system, and mastery tracking — all without AI. Now the LLM enters, but as bounded tools inside the existing system, not as an autonomous agent. Every AI role has a specific job, uses approved sources, and includes citations.

The key insight from the research: AI should generate practice, hints, explanations, and summaries. It should NOT control the planning logic, the evidence model, or the accountability loop. OECD's warning is direct — AI that improves task performance without improving learning creates "metacognitive laziness."

The tutor should ask more than it tells.

## Goals

- Add LLM client infrastructure with prompt management, cost tracking, and audit logging
- Build 5 bounded AI roles: practice generator, evaluator, retriever, coach, escalation detector
- Implement source trust controls and citation requirements
- Ship a conversational coach that follows pedagogical rules
- Ensure every AI output is grounded in approved sources

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

## Work items

### 1. LLM client infrastructure

Create `mitty/ai/client.py` and `mitty/ai/prompts.py`.

**Client:**
- Claude API integration (via anthropic SDK)
- Structured output parsing (tool use / JSON mode)
- Token counting and cost tracking per call
- Rate limiting (requests per minute, tokens per minute)
- Retry logic for transient errors
- All calls logged to `ai_audit_log` table (prompt, response, model, tokens, cost, timestamp, context)

**Prompt management:**
- System prompts per AI role (practice_generator, coach, evaluator, explainer)
- Template system for injecting context (concept, resource chunks, student history)
- Prompt versioning — store which prompt version produced each output
- Config: model selection, temperature, max_tokens per role

**Security:**
- Provider API keys server-side only — never in frontend bundles
- Student inputs sanitized before inclusion in prompts (prompt injection defense)
- Outputs validated before returning to frontend

### 2. AI retriever (source-grounded context)

Create `mitty/ai/retriever.py`.

Given a concept/question, find the most relevant `resource_chunks`:

| Retrieval method | Implementation |
|-----------------|----------------|
| Keyword/BM25 | Text search against chunk content — start here |
| Embedding similarity | Generate embeddings for chunks, use vector similarity — upgrade path |

Returns: top-k chunks with source attribution (`resource_id`, `chunk_index`, `resource.title`).

**Critical rule**: If retriever returns insufficient results (< threshold), the AI tool must say "I don't have enough source material for this topic" rather than hallucinate. Surface this as "No study materials" in the UI with a prompt to add resources.

### 3. AI practice generator

Create `mitty/ai/practice_generator.py`.

Replaces/augments the template generator from Phase 4.

Given `(concept, resource_chunks[])`, generate:
- Quiz questions (multiple choice, fill-in-blank, short answer)
- Flashcards (term/definition, concept/explanation)
- Worked examples (step-by-step solution + similar problem)
- Explanation prompts (why/how/compare/what-if questions)

Requirements:
- Every generated question must cite its source chunk
- Vary question difficulty based on mastery_level (low mastery = easier, scaffolded)
- Vary question format to avoid pattern matching
- Include the correct answer and a brief explanation
- **Source trust check**: if resource coverage is low for this concept, fall back to template-based generation or flag for resource addition

### 4. AI evaluator (answer scoring)

Create `mitty/ai/evaluator.py`.

Score student answers beyond simple keyword matching:

| Input | Evaluation |
|-------|-----------|
| Quiz answer | Exact/partial match, accept reasonable variations |
| Explanation | Assess completeness, accuracy, depth of understanding |
| Worked example steps | Check each step for correctness and method |
| Reflection | Assess metacognitive quality (specific vs. vague) |

Returns:
- `is_correct` (bool)
- `score` (0.0 - 1.0, for partial credit)
- `feedback` (text — what was right, what was missed, what to review)
- `misconceptions_detected` (list — "You confused X with Y")

Feed results into `mastery_state` updates. The evaluator should detect false confidence: "the answer is partially right but misses the key concept."

### 5. Conversational coach

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

### 6. Escalation detector

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

### 7. Source trust controls

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

### 8. Coach chat UI

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

- [ ] LLM client infrastructure works with Claude API, includes cost tracking and audit logging
- [ ] Retriever returns relevant chunks with source attribution, refuses when sources insufficient
- [ ] AI practice generator produces better questions than templates, with citations
- [ ] AI evaluator scores explanations and worked examples beyond keyword matching
- [ ] Conversational coach follows pedagogical rules (ask before tell, hints before answers)
- [ ] Coach is scoped to current block topic and approved sources only
- [ ] Escalation detector flags repeated failure, high stress, avoidance patterns
- [ ] Source trust scoring works, low-trust sources are disclosed, no-source gaps are surfaced
- [ ] Chat UI works on mobile with block context and source display
- [ ] "Flag this response" mechanism works
- [ ] All AI calls logged to audit table with prompt version, tokens, cost
- [ ] API keys are server-side only
- [ ] Quality gates pass

## Risks & open questions

- **LLM cost** — Practice generation + evaluation + coaching per session adds up. Track cost per session and set budget alerts. Consider caching generated practice items.
- **Prompt injection** — Student inputs go into LLM prompts. Sanitize inputs, use structured prompts, validate outputs.
- **Pedagogical rule enforcement** — System prompts can be ignored by the model. Need output validation: did the coach actually ask a question before giving an answer? Test with adversarial inputs.
- **"Do my homework" risk** — The coach must not do homework for the student. Scope restrictions + system prompt + output validation. Consider: if the current study block is "urgent deliverable" (homework), should the coach be available at all? Maybe only for "retrieval" and "explanation" blocks.
- **Response quality** — LLM explanations may be wrong or misleading. Source grounding reduces but doesn't eliminate this. The "flag" button and audit log are safety nets.
- **Latency** — LLM calls add latency to practice and chat. Cache practice items, stream chat responses.

## Dependencies

- Phase 1: backend API, schema (for ai_audit_log table — add migration)
- Phase 2: resources + resource_chunks (content for retrieval)
- Phase 3: planner + study blocks (coach scoped to blocks)
- Phase 4: practice system + mastery tracking (AI augments, doesn't replace)
