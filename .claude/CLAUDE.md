# AnswerX GEO Platform

## Project Context

AnswerX GEO is a SaaS platform for Chinese overseas brands (出海品牌) doing Generative Engine Optimization.
The platform monitors brand visibility, citations, and sentiment across AI search engines (ChatGPT, Gemini, AiMode).

2-person startup: CTO (lancelot, writes all code) + partner (sales/BD).
First target vertical: 出海小家电 (Roborock as demo data).

## Architecture Overview

The platform consists of four Cloud Run services sharing one Cloud SQL instance:

| Module | Role |
|--------|------|
| `geo_collector/` | Data collection: Cloro scraping, Gemini expansion, PubSub ingestion |
| `geo_analyzer/` | Batch analysis: company parsing, source classification |
| `geo_saas/` | Main SaaS: FastAPI backend + React/TypeScript frontend (Vite) |
| `geo_agent/` | Agent layer: Anthony AI assistant (LangGraph multi-agent) |

## Architecture Constraints (locked decisions)

1. **Framework**: LangGraph with Sub-graph multi-agent pattern. Tool functions must be framework-independent (pure async functions with @tool decorator).
2. **Module**: `geo_agent/` is a standalone Cloud Run service. It shares Cloud SQL with `geo_saas/` but has its own FastAPI app, Dockerfile, and requirements.txt.
3. **Multi-Agent**: Supervisor (Gemini Flash) routes to Analyze Agent (Gemini Pro), Action Agent (Gemini Pro), or General Chat (Gemini Flash) as separate Sub-graphs.
4. **State Persistence**: AsyncPostgresSaver on existing Cloud SQL. Message pruning + TTL cleanup cron. No Redis.
5. **SDK**: `google-genai` (unified SDK). Do NOT use deprecated `vertexai.generative_models`. Import: `from google import genai`.
6. **Streaming**: SSE (Server-Sent Events) for chat streaming.
7. **Entry Point**: Chat (Anthony) is the main UI entry. Supervisor is embedded inside Chat. Sidebar also has direct Analyze and Action entries.
8. **Brand Tonality**: `geo_brand_profiles` DB table injected into system prompts.

## P0 Red Line: Multi-Tenant Isolation

Cross-tenant data leakage is catastrophic. Three defense layers:
1. **State injection**: `client_id` extracted from JWT at API boundary, injected into AgentState, immutable throughout execution.
2. **@tenant_scoped decorator**: Every data query tool MUST include `WHERE client_id = $1`. The decorator enforces this.
3. **PostgreSQL RLS**: Planned for later, but the first two layers must be solid from Day 1.

Manual verification: After each data tool is built, test with two different client_ids and confirm zero cross-contamination.

## Development Rules

These rules apply to ALL development work. Do not deviate without explicit user approval.

### LLM & Model Management
- **Model IDs must come from database** — never hardcode. Use `get_model_id("flash")` or equivalent DB lookup. Filter by "flash" for lightweight tasks.
- **Never change fallback model IDs without asking** — always ask user before modifying any fallback/default model ID values in code.
- **Flash preview token budget** — Flash preview models consume thinking tokens from `max_output_tokens`. Minimums: >= 256 for classification, >= 512 for short generation, >= 4096 for conversational. Pro model does NOT have this issue.

### Data & SQL
- **NL2SQL architecture** — never hardcode SQL in tools. Use schema introspection + LLM generation. User explicitly rejected hardcoded SQL approach.
- **DB schema changes** — never execute DDL directly. Provide SQL migration files for user to run manually. CTO wants full control over Cloud SQL schema changes.

### Frontend & UI
- **No native browser dialogs** — never use `window.prompt`, `window.confirm`, `window.alert`, or native `<select>`. Always use custom UI components (Dialog, AlertDialog, Select from shadcn/radix).
- **Production-grade standard** — never frame code as "acceptable for demo." This is commercial SaaS. UI must match or exceed existing SaaS GEO module quality.

### i18n Discipline (geo_saas/web — zh-CN / en-US bilingual)

SaaS web uses `react-i18next`. UI copy truth lives in `geo_saas/web/src/i18n/locales/{zh-CN,en-US}/{ns}.json`; tsx files only reference keys via `t('ns:path.to.key')`. Namespaces: `common`, `sidebar`, `settings`, `onboarding`, `insights`, `dashboards`, `agents`, `content`, `wizard`, `validation`. Five rules — must follow:

1. **Keys must be semantic**, never ordinal. Use `{area}.{section}.{item}` (e.g. `settings.brands.ownSection`). Never `settings.label1`, never `t1/t2/t3`.
2. **One namespace per page area**. Shared words (`Save`, `Cancel`, `Delete`, `Loading`) live ONLY in `common`. Do not duplicate a term across namespaces — it will drift.
3. **Each namespace JSON opens with a `__doc` key** describing what page/flow it covers. When an agent opens a JSON, the first line tells it the scope; do not need to grep around.
4. **Separate concerns in commits**: editing UI copy → change JSON files only (both zh and en). Editing UI structure / component logic → change tsx only. Do not mix in one commit unless genuinely coupled.
5. **Page-level titles may use "中文 · English" bilingual form in `zh-CN`** (e.g. `可见度 · Visibility`). Body copy / labels / tooltips stay full Chinese in `zh-CN` and full English in `en-US`. The term table for what stays pure English (AI, RAFT, LLM, NL2SQL, Embedding, Prompt-as-concept, Framework, SKU, platform brand names) is the only cross-mode exception.

Module-scope data (arrays / consts defined outside a component) cannot call `useTranslation`. Store `tooltipKey` / `labelKey` strings in the data and call `t(...)` at the render site — see `OnboardingWizard.tsx` `BRANCH_OPTIONS` for the canonical pattern.

To understand what a component renders, read its namespace JSON first — it's flat, sorted, and ~300 lines tops. Do NOT grep through a 2800-line tsx hunting for strings.

### Local Service Startup (load-bearing — two coexisting stacks)
- **Two isolated stacks on this machine** — user's (5173/5174 web + 8000-8002 backend) and Claude's (+1000 offset: 6173/6174 + 9000-9002), with separate `.env.local` vs `.env.claude.local` per module.
- When user says "部署 / 启动本地服务 / 本地测试 / 本地验证" **without specifying which stack**, ASK FIRST. Don't assume. Don't squat on the other side's ports.
- **Never modify user's `.env.local`**. Read-only. If DB target needs to flip, tell the user which line to comment/uncomment.
- For user's stack on default 5432, verify Cloud SQL Auth Proxy is up first (`lsof -i :5432`); flag if missing. Ask user whether they want 5432 (prod via proxy) or 5433 (local pg18) when starting.
- For Claude's stack, **always 5433 local pg18, never 5432 prod**.
- **For E2E browser automation: prefer `mcp__Claude_Preview__*` tools over gstack `/browse`.** Preview MCP doesn't go through bash sandbox (no permission popups), uses CSS selectors (more stable than gstack's @e refs), and is purpose-built for local dev servers via `.claude/launch.json`. Existing config: `geo_admin/web` on port 6174 (`name: admin-web-claude`), `geo_saas/web` on port 6173 (`name: saas-web-claude`). Use `/browse` only when Preview MCP can't reach the URL (prod sites, OAuth redirects, arbitrary external URLs). When deleting rows via UI eval, **walk up max 1-2 levels (TR scope, ~3 buttons)** to avoid grabbing other rows' delete buttons; for forms with Radix Select, fall back to direct API CRUD if state sync fails.
- Full protocol + scenarios + checklist: see `feedback_ask_which_stack_before_starting.md` + `reference_local_dev_ui_automation.md` in `~/.claude/projects/.../memory/`.

### General
- Do not run destructive git commands without asking.
- Provide complete, working code — no placeholder comments like `// TODO` or `// implement later`.

## Tech Stack

- Backend: Python 3.11+, FastAPI, LangGraph, google-genai SDK, asyncpg
- Frontend: React + TypeScript (Vite), Tailwind CSS, shadcn/ui
- Database: Cloud SQL (PostgreSQL)
- Infra: Google Cloud Run, Terraform
- LLM: Gemini Pro (Analyze/Action), Gemini Flash (Chat/Supervisor)

## Module Structure

```
geo_agent/
├── src/
│   ├── main.py              # FastAPI + SSE endpoints
│   ├── routers/tasks.py     # Task management + HTML report export
│   ├── graphs/
│   │   ├── supervisor.py    # Intent classification + routing
│   │   ├── analyze.py       # Analyze Agent Sub-graph
│   │   ├── action.py        # Action Agent Sub-graph (Content)
│   │   └── chat.py          # General Chat
│   ├── pipelines/
│   │   ├── opportunity_pipeline.py  # Opportunity discovery
│   │   └── content_pipeline.py      # Content generation (RAFT)
│   ├── tools/               # Atomic tool functions
│   ├── middleware/tenant.py  # @tenant_scoped decorator
│   ├── llm/client.py        # google-genai client wrapper + region routing
│   └── database.py          # asyncpg pool (shared Cloud SQL)
├── Dockerfile
├── requirements.txt
└── terraform/main.tf
```

## SSE Protocol

```
data: {"type": "intent", "value": "analyze"}
data: {"type": "tool_start", "name": "visibility_query", "args": {...}}
data: {"type": "tool_result", "name": "visibility_query", "status": "done"}
data: {"type": "chart", "data": {"type": "line", "title": "SOV Trend", "data": [...]}}
data: {"type": "token", "text": "..."}
data: {"type": "done", "thread_id": "xxx"}
```

## Key Patterns in Existing Code

- `geo_saas/src/routers/insights/analysis.py`: NL2SQL logic, metric hydration, chart generation, SQL safety validation (ALLOWED_TABLES, SAFE_SQL_RE).
- `geo_saas/src/routers/brainstorming.py`: SSE streaming pattern, intent classification.
- `geo_agent/src/llm/client.py`: Centralized LLM client with `_resolve_region` — "preview" in model_id routes to global region, stable routes to us-central1.

## Reference Documents

- Strategy Memo: `GEO_Agent_Strategy_Memo.md` (in repo root)
