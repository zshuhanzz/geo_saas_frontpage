# Citation Analysis Code Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Citation Analysis into the content generation runtime so new AI-citable templates can use citation data as a source of truth.

**Architecture:** Add a focused `services.citation_analysis` module for config resolution, source selection, brand mention triage, optional page fetching, aggregate brief generation, and conservative action decisions. The content pipeline gets a new optional runtime step before strategy generation, then injects the aggregate brief into strategy, content generation, and quality review. The SaaS wizard submits citation analysis config from DB-driven fields.

**Tech Stack:** Python 3.11, FastAPI/asyncpg, google-genai, React/TypeScript, pytest, Vite.

---

### Task 1: Citation Analysis Service

**Files:**
- Create: `/Users/lancelot/Desktop/GEO_Demo/geo_agent/src/services/citation_analysis.py`
- Test: `/Users/lancelot/Desktop/GEO_Demo/geo_agent/tests/test_citation_analysis.py`

- [ ] Write failing tests for config resolution, brand triage, action aggregation, and prompt-scoped source query behavior.
- [ ] Implement deterministic config resolution, brand alias matching, source SQL builder, page fetch fallback, triage aggregation, and citation-grounded brief formatting.
- [ ] Run targeted tests.

### Task 2: Content Pipeline Integration

**Files:**
- Modify: `/Users/lancelot/Desktop/GEO_Demo/geo_agent/src/pipelines/content_pipeline.py`
- Test: `/Users/lancelot/Desktop/GEO_Demo/geo_agent/tests/test_content_pipeline_options.py`

- [ ] Add `_build_citation_analysis_instruction` tests.
- [ ] Add optional `citation_analysis` pipeline step before strategy generation.
- [ ] Inject citation brief into strategy prompt, content prompt, quality review prompt, and final output metadata.
- [ ] Run targeted pipeline tests.

### Task 3: Strategy Preview and SaaS Wizard Input Mapping

**Files:**
- Modify: `/Users/lancelot/Desktop/GEO_Demo/geo_agent/src/routers/strategy.py`
- Modify: `/Users/lancelot/Desktop/GEO_Demo/geo_saas/web/src/components/agents/ContentPipelineModal.tsx`
- Modify: `/Users/lancelot/Desktop/GEO_Demo/geo_saas/web/src/components/wizard/schema.ts`

- [ ] Forward citation analysis config from Wizard form state into task inputs.
- [ ] Preserve citation config when editing existing tasks.
- [ ] Let strategy preview include Citation Analysis config/summary if present.
- [ ] Run TypeScript build.

### Task 4: Verification

**Commands:**
- `geo_agent/src/venv/bin/pytest geo_agent/tests -q`
- `python3 -m py_compile geo_agent/src/services/citation_analysis.py geo_agent/src/pipelines/content_pipeline.py geo_agent/src/routers/strategy.py`
- `npm run build` in `/Users/lancelot/Desktop/GEO_Demo/geo_saas/web`

