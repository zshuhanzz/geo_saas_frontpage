# Cloro Perplexity and AI Overview Platform Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Perplexity and AI Overview as supported Cloro collection platforms across Collector, Admin configuration, SaaS platform controls, and seed data.

**Architecture:** Reuse the existing Cloro strategy pattern for dispatch and the existing unpacker factory for ingestion. Keep platform availability database-driven through `geo_global_platforms`, with only small UI registry updates where hardcoded platform lists still exist.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, pytest, React, TypeScript, Vite, PostgreSQL migrations.

---

## Schema Policy

Do not change `geo_results` schema in this implementation. Normalize Perplexity and AI Overview responses into existing fields. Keep raw unsupported fields in `cloro_response` and optionally mirror them into `entities` when useful.

Do not execute migrations directly. Create migration SQL only; the user will run it manually.

Do not run git commands.

## Files

- Modify: `geo_collector/src/clients/cloro.py`
- Modify: `geo_collector/src/services/unpackers/base.py`
- Create: `geo_collector/src/services/unpackers/perplexity.py`
- Create: `geo_collector/src/services/unpackers/aioverview.py`
- Modify: `geo_collector/src/services/unpackers/factory.py`
- Modify: `geo_collector/tests/test_cloro_client.py`
- Create: `geo_collector/tests/test_unpackers.py`
- Modify: `geo_collector/README.md`
- Create: `migrations/098_add_perplexity_ai_overview_platforms.sql`
- Modify: `geo_admin/web/src/pages/ReportTemplatesPage.tsx`
- Modify: `geo_admin/web/src/pages/ContentTemplatesPage.tsx`
- Modify: `geo_admin/web/src/components/WorkflowConfigManager.tsx`
- Modify: `geo_saas/web/src/components/agents/ContentTaskModal.parts/constants.ts`
- Modify: `geo_saas/web/src/components/agents/nodes/NodeGenConfig.tsx`
- Modify: `geo_saas/web/src/components/agents/nodes/NodeStrategy.tsx`
- Modify: `geo_saas/web/src/components/charts/OpportunityCharts.tsx`
- Modify: `geo_saas/web/src/components/charts/PremiumChart.tsx`
- Modify: `geo_saas/web/src/pages/agents/AgentAnalysis.parts/OpportunityDiscoveryView.tsx`
- Modify: `geo_saas/web/src/components/insights/OpportunityAnalysisModal.tsx`
- Modify: `geo_saas/web/src/components/wizard/customFields/PromptEditor.tsx`
- Modify: `geo_saas/web/src/components/wizard/customFields/StrategyGenerator.tsx`

## Task 1: Collector Dispatch Strategy

- [ ] Add `build_payload(task)` to `CloroPlatformStrategy`.
- [ ] Keep default payload as `prompt/country/include` for existing platforms.
- [ ] Add `GoogleAIOverviewStrategy` with platform key `aioverview`, sync endpoint `/v1/monitor/google`, Google Search async task type, and payload using `query` plus `include.aioverview.markdown`.
- [ ] Register `GoogleAIOverviewStrategy`.
- [ ] Update tests to assert all five platforms route correctly and AI Overview payload shape is correct.

## Task 2: Collector Unpackers

- [ ] Add shared helper methods in `BaseUnpacker` for extracting nested `response.result` payloads and getting camelCase/snake_case aliases.
- [ ] Create `PerplexityUnpacker`.
- [ ] Create `AIOverviewUnpacker`.
- [ ] Register `perplexity`, `aioverview`, `ai_overview`, and `google_ai_overview` aliases in `UnpackerFactory`.
- [ ] Add unpacker tests for normal Perplexity, normal AI Overview, and `aioverview: null`.

## Task 3: Seed Migration

- [ ] Create migration `098_add_perplexity_ai_overview_platforms.sql`.
- [ ] Upsert rows into `geo_global_platforms`.
- [ ] Upsert rows into `geo_workflow_config` only when the table exists.
- [ ] Do not mutate `geo_clients.config_platforms`.

## Task 4: Admin UI Platform Awareness

- [ ] Update template platform option arrays to include Perplexity and AI Overview.
- [ ] Update workflow manager copy from "ChatGPT / Gemini / AI Mode" to "configured AI platforms" or five-platform copy.
- [ ] Keep existing Admin Global Platforms and Clients pages unchanged unless they contain hardcoded platform labels.

## Task 5: SaaS UI Platform Awareness

- [ ] Update content task platform constants to include Perplexity and AI Overview.
- [ ] Update agent node platform registry, aliases, and color maps.
- [ ] Update Opportunity/Strategy/Premium chart platform colors.
- [ ] Update static copy that names only ChatGPT/Gemini/AI Mode.
- [ ] Preserve existing dashboard and report data fetching behavior.

## Task 6: Verification

- [ ] Run Collector unit tests for Cloro client and unpackers.
- [ ] Run focused TypeScript/build or lint checks for touched web modules if available.
- [ ] Run `rg` for old three-platform-only copy and confirm remaining matches are either historical docs/tests or intentional.
- [ ] Review migration to confirm it is idempotent and does not enable platforms for existing clients.
