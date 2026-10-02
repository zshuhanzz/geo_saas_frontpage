# GEO Agent — Anthony AI Assistant (v1.2+)

LangGraph-based multi-agent service running alongside the SaaS. Powers the **分析 Agents** + **内容 Agents** wizard-driven flows and the **Chat with Anthony** conversational surface.

> **Current production focus (2026-05)**: Citation-grounded content generation, Reddit / Official Website AI Citable templates, Quality Gate + up to two Revise attempts, and visible workflow progress for Citation / Gate / Revise.

---

## 🧠 Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       GEO Agent API (FastAPI)                     │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Supervisor (Gemini Flash)                                  │ │
│  │   └─ Intent classification → routes to:                    │ │
│  │      ├─ Analyze sub-graph  (Gemini Pro)                    │ │
│  │      ├─ Action  sub-graph  (Gemini Pro, Content Gen)       │ │
│  │      └─ General Chat        (Gemini Flash)                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐      │
│  │ Wizard Task  │  │ NL2SQL Metric│  │ Citation Analysis +│      │
│  │ Pipelines    │  │   Generation │  │ Quality Gate /     │      │
│  │ (analysis /  │  │  + Chart SQL │  │ Revise + HTML      │      │
│  │  content)    │  │              │  │ export             │      │
│  └──────────────┘  └──────────────┘  └────────────────────┘      │
│                                                                   │
│  @tenant_scoped decorator — enforces `WHERE client_id = $1` on   │
│  every data tool (P0 multi-tenant red line, Spec §P0).           │
└──────────────────────────────────────────────────────────────────┘
          │                                  │
          │ Vertex AI                        │ asyncpg + AsyncPostgresSaver
          ▼                                  ▼
     Gemini 3.1-pro-preview /           ┌────────────────────────────┐
     Gemini 3-flash-preview             │  Cloud SQL (shared w/ SaaS)│
                                        │  + agent_sessions          │
                                        │  + agent state checkpoints │
                                        └────────────────────────────┘
```

---

## 🔑 Architecture Constraints (LOCKED)

Per project AGENTS.md / CLAUDE.md, the following are **non-negotiable**:

1. **LangGraph Sub-graph** pattern. Tool functions must be framework-independent (pure async + `@tool` decorator).
2. **Standalone service**. Shares Cloud SQL with `geo_saas/` but has its own FastAPI, Dockerfile, Terraform.
3. **Multi-Agent**: Supervisor (Flash) routes to Analyze (Pro), Action (Pro), Chat (Flash) as separate sub-graphs.
4. **State**: AsyncPostgresSaver on existing Cloud SQL. Message pruning + TTL cron. **No Redis**.
5. **SDK**: `google-genai` (`from google import genai`). Never `vertexai.generative_models`.
6. **Streaming**: SSE for all chat / pipeline progress events.
7. **Entry point**: Chat (Anthony) main UI; Supervisor embedded. Sidebar links to direct Analyze / Action / Chat pages.
8. **Brand Tonality**: `geo_brand_profiles` DB table injected into every sub-graph's system prompt.

### P0 Multi-Tenant Isolation

Three defense layers:
1. **State injection** — `client_id` extracted from JWT at API boundary, immutable in AgentState throughout execution.
2. **`@tenant_scoped` decorator** — every data query tool MUST include `WHERE client_id = $1`.
3. **PostgreSQL RLS** — planned; layers 1 + 2 solid from day 1.

---

## 📁 Module Structure

```
geo_agent/
├── src/
│   ├── main.py                  # FastAPI app + SSE endpoints + startup/shutdown
│   ├── database.py              # asyncpg shared pool
│   ├── routers/
│   │   ├── tasks.py             # Wizard task CRUD + workflow progress + HTML export
│   │   ├── templates.py         # Template listing / contract surface
│   │   ├── strategy.py          # Strategy generation + JSON-envelope normalization
│   │   ├── content_preselect.py # AI-mode topic/prompt/content preselection
│   │   ├── framework.py         # Content framework / RATF helpers
│   │   └── export.py            # Report export helpers
│   ├── graphs/
│   │   ├── supervisor.py        # Intent classification + routing
│   │   ├── analyze.py           # Analyze Agent Sub-graph
│   │   ├── action.py            # Action Agent Sub-graph (Content Gen)
│   │   └── chat.py              # General Chat Sub-graph
│   ├── pipelines/
│   │   ├── analysis_pipeline.py # validate → hydrate → charts → synthesize → QA
│   │   ├── content_pipeline.py  # Citation → strategy → content → gate/revise loop
│   │   ├── opportunity_pipeline.py # Opportunity discovery
│   │   ├── template_contracts.py # Template/runtime contract helpers
│   │   └── base.py              # Pipeline runner + workflow step status
│   ├── services/
│   │   ├── citation_analysis.py # Citation source fetch + triage + grounded brief
│   │   └── workflow_config.py   # Wizard-aligned slot-fill config
│   ├── context/                 # memory / pruner / compressor / user profile
│   ├── tools/                   # Atomic @tool functions (NL2SQL helpers)
│   ├── middleware/tenant.py     # @tenant_scoped decorator
│   └── llm/client.py            # google-genai client + _resolve_region
├── sql/                         # Agent state migrations (AsyncPostgresSaver schema)
├── terraform/main.tf            # Cloud Run service config
├── Dockerfile
└── requirements.txt
```

---

## 🔌 SSE Protocol (client ↔ server)

```
data: {"type": "intent", "value": "analyze"}
data: {"type": "tool_start", "name": "visibility_query", "args": {...}}
data: {"type": "tool_result", "name": "visibility_query", "status": "done"}
data: {"type": "chart", "data": {"type": "line", "title": "SOV Trend", "data": [...]}}
data: {"type": "token", "text": "..."}
data: {"type": "done", "thread_id": "xxx"}
```

---

## 🧩 Key Routes (v1.2 incremental)

| Route | Purpose |
|---|---|
| `POST /api/agent/tasks` | Create + (optionally) fire a wizard task (analysis / content_generation) |
| `POST /api/agent/tasks/{id}/run` | Run a saved DRAFT task |
| `GET  /api/agent/tasks/{id}/progress` | Poll workflow_steps progress |
| `GET  /api/agent/tasks/{id}/export?view=true` | HTML report export |
| `GET  /api/agent/tasks/templates?type=analysis\|content_generation` | List templates (filtered by client availability) |
| `GET  /api/agent/tasks/workflow-config?scope=content_generation` | Wizard schema + dictionary |
| `GET  /api/agent/tasks/prompts/ranked?client_id=…&sort_by=visibility` | Worst-prompt ranking for Wizard (B-1) |
| `GET  /api/agent/tasks/topics/ranked?client_id=…&sort_by=visibility` | Worst-topic ranking (v2 new, B-1b) |
| `POST /api/agent/tasks/content/preselect` | AI-mode 预选 topic + prompts + content_type |
| `POST /api/agent/tasks/metrics/discover?domains=visibility,citation` | Agent-ized metric catalog |

---

## 🏃 Local Dev

```bash
cd geo_agent/src
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Env:
#   DATABASE_URL=postgresql+asyncpg://...:5433/answer-x-geo-db  (local pg18)
#   或 @localhost:5432 (Cloud SQL Auth Proxy)
#   GCP_PROJECT_ID=...  GCP_REGION=us-central1
#   VITE_DEV_AUTH_USER_EMAIL=... (仅 Claude mode, 见 docs/local-dev)

uvicorn main:app --reload --port 8002 --env-file .env.local
# Claude-isolated stack:
uvicorn main:app --reload --port 9002 --env-file .env.claude.local
```

**Dependencies**: the Agent depends on the same Cloud SQL as `geo_saas/`. Auth bypass + tenant isolation work the same way via the shared `clients` DB model.

---

## 🧪 Wizard Pipelines

### Analysis Pipeline (5 steps)
1. **validate_inputs** — date-range anchor shift fallback (handles stale ranges post-midnight)
2. **hydrate_metrics** — load `geo_analysis_metrics`, schedule concurrent NL2SQL per metric (enum-guardrail + post-processor `normalize_enum_literals()` for LLM hallucination)
3. **generate_charts** — chart request SQL → data rows
4. **synthesize_report** — Gemini Pro writes 8-section report (含 Prescriptive / Diagnostic / Predictive lenses)
5. **quality_check** — dimension scoring; flags hallucination risk

### Content Wizard (configuration steps)

The SaaS wizard remains schema-driven via `geo_workflow_config` and template-level `wizard_config`:

1. **mode_gate** — 我来定 / AI 帮我发现
2. **content_type** — FAQ / AEO / SEO / Brief / Recommendations / AI Citable article/post
3. **data_scope** — topic + prompt + sort dimension + optional analyzer report
4. **reddit_discovery / official_website_discovery** — optional platform-specific discovery nodes
5. **citation_analysis** — optional preflight; enabled by default for AI Citable templates
6. **content_goal** — RATF metrics + sub_goals
7. **content_strategy** — Gemini synthesizes strategy from user selections + Discover + Citation
8. **generation_config** — count / depth / model / grounding / product facts
9. **confirm_execute** — fire pipeline

### Content Pipeline Runtime (8 semantic steps)

Once the user confirms execution, `content_pipeline.py` writes visible workflow progress:

1. **Citation Analysis** — reuses preflight result when available, otherwise runs configured citation analysis.
2. **Strategy Generation** — generates human-readable strategy; JSON envelopes are normalized before display/storage.
3. **Content Generation** — segmented long-form generation for article-style outputs.
4. **Quality Gate** — deterministic + LLM review. Checks score thresholds, duplicate headings/FAQ/conclusion, truncation, brand density, platform fit, citation alignment, and configured blockers.
5. **第一轮 Revise** — template-driven repair, usually structural / major blocker fixes.
6. **修订后复查** — post-revision Quality Gate review.
7. **第二轮 Revise** — optional cleanup for residual duplicate FAQ/conclusion, unfinished sentences, brand density, etc.
8. **第二轮后复查** — final recheck. Skipped branches are marked `skipped`.

Pre-revision issues are stored in `pre_revision_quality_review`; final `quality_review` always describes the final content. Template-specific revise guidance lives in `geo_report_templates.wizard_config.quality_gate.revision_guidance`.

### Citation Analysis

`services/citation_analysis.py` powers Citation-grounded generation:

- Reads existing citation data and optional discovered URLs.
- Fetches citation pages with status metadata.
- For Reddit, uses public JSON / API / old.reddit fallbacks to avoid `Please wait for verification` where possible.
- Produces Brand Mention Triage, Content Action Decision, Citation Grounded Brief, source patterns, and GEO visibility gaps.
- New citable templates use this as a source of truth; existing templates can enable it through Wizard Stack config.

### Opportunity Pipeline (4 steps)
1. `topic_quadrant` — topic quadrant analysis (SOV × Citation)
2. `content_opportunities` — gap detection
3. `platform_analysis` — per-AI-platform citation breakdown
4. `synthesize_output` — structured opportunity list + action plan

---

## 📚 References

- [specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md](../docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md) — Agent-level impact of v1.2
- [progress/DEPLOY_PLAYBOOK_v1.2.md](../docs/superpowers/plans/progress/DEPLOY_PLAYBOOK_v1.2.md) — How the Agent is deployed alongside v1.2
- [docs/local-dev/codex-visible-e2e.md](../docs/local-dev/codex-visible-e2e.md) — visible E2E runbook for Content Agent flows
- [docs/content-generation-quality-playbook.md](../docs/content-generation-quality-playbook.md) — manual article/process quality evaluation standard
- Project AGENTS.md / CLAUDE.md — locked architecture decisions
