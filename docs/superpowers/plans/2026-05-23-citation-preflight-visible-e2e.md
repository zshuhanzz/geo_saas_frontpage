# Citation Preflight Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Citation Analysis from an opaque final execution step into a visible wizard preflight while keeping the pipeline fallback safe.

**Architecture:** Add a content Citation Analysis preview endpoint in `geo_agent`, reuse the existing citation service, and pass the preflight result through the content wizard form state into strategy/content generation. The background pipeline will reuse a valid preflight result and only run Citation Analysis when the wizard did not provide one.

**Tech Stack:** FastAPI, asyncpg, React/TypeScript, schema-driven Wizard, pytest, Vite.

---

### Task 1: Backend Preflight Endpoint

**Files:**
- Modify: `geo_agent/src/services/citation_analysis.py`
- Modify: `geo_agent/src/routers/tasks.py`
- Test: `geo_agent/tests/test_citation_analysis.py`

- [ ] Add a deterministic `build_citation_analysis_fingerprint(inputs, template_runtime_config)` helper that hashes only the Citation-relevant form inputs and template defaults.
- [ ] Add `fingerprint` and `generated_at` fields to enabled Citation Analysis results.
- [ ] Add `POST /api/agent/tasks/content/citation-analysis/preview`, guarded by the authenticated user and `client_id`.
- [ ] The endpoint loads template runtime config from `template_id`, loads brand context, runs `run_citation_analysis`, and returns the same result shape used by the pipeline.

### Task 2: Pipeline Reuse And Workflow Visibility

**Files:**
- Modify: `geo_agent/src/pipelines/content_pipeline.py`
- Modify: `geo_agent/src/routers/tasks.py`
- Test: `geo_agent/tests/test_content_pipeline_options.py`

- [ ] Teach `step_citation_analysis` to reuse `inputs.citation_analysis_result` when it is enabled and fingerprint-compatible.
- [ ] Append a status log saying Citation Analysis was reused from wizard preflight.
- [ ] Update content task workflow steps to include `citation_analysis` as step 1, followed by strategy, content, quality review, and revise.

### Task 3: Wizard Citation Analysis Preflight UI

**Files:**
- Create: `geo_saas/web/src/components/wizard/customFields/CitationAnalysisPreflight.tsx`
- Modify: `geo_saas/web/src/components/wizard/customFields/index.ts`
- Modify: `geo_saas/web/src/components/agents/ContentPipelineModal.tsx`
- Modify: `geo_saas/web/src/components/wizard/customFields/StrategyGenerator.tsx`
- Modify: `geo_saas/web/src/i18n/locales/zh-CN/wizard.json`
- Modify: `geo_saas/web/src/i18n/locales/en-US/wizard.json`
- Migration: add `migrations/085_citation_preflight_wizard_field.sql`

- [ ] Add a custom field that renders existing Citation Analysis config controls plus a run button and summary cards.
- [ ] Store the preview result in `formState.citation_analysis_result`.
- [ ] Include `citation_analysis_result` in final task inputs and strategy generation requests.
- [ ] Disable final execute for templates that require preflight until the result is ready.

### Task 4: E2E Documentation

**Files:**
- Create: `docs/local-dev/codex-visible-e2e.md`
- Modify: `docs/local-dev/claude-ports.md`

- [ ] Document the Codex visible E2E ports: SaaS API `9101`, Agent API `9102`, Admin UI `6173`, SaaS UI `6174`.
- [ ] Document `.env.e2e.local`, startup commands, Chrome/Computer Use flow, and content-generation checklist.
- [ ] Mark `claude-ports.md` as the legacy Claude isolation port reference.

### Verification

- [ ] Run backend tests for Citation Analysis and content pipeline options.
- [ ] Run Python compile checks for changed backend modules.
- [ ] Run frontend TypeScript build.
- [ ] Run visible browser E2E through `http://localhost:6174/agents/content` for both AI-citable templates.
