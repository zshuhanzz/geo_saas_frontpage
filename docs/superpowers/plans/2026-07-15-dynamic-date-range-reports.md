# Dynamic Date-Range Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace newly generated frozen web snapshots with access-controlled reports that persist only a fixed date range and render through the existing dynamic Dashboard APIs.

**Architecture:** Reports with `snapshot_version=dynamic-report-v1` store only tenant, report-window, current filter-label metadata, and authorization/audit metadata in `geo_static_reports`. The web page renders the existing dynamic Visibility, Citation, and Sentiment dashboards with that fixed window. Legacy snapshot versions remain readable until their test reports are removed. Offline HTML freezes the currently rendered DOM at export time.

**Tech Stack:** FastAPI, asyncpg, React, TypeScript, existing Dashboard components, PostgreSQL migrations.

---

### Task 1: Lightweight dynamic report creation

**Files:**
- Modify: `geo_saas/src/routers/static_reports/models.py`
- Modify: `geo_saas/src/routers/static_reports/repository.py`
- Modify: `geo_saas/src/routers/static_reports/router.py`
- Test: `geo_saas/tests/test_static_reports_router.py`
- Test: `geo_saas/tests/test_static_report_list_rows.py`

- [ ] Add failing tests proving new reports complete without `build_snapshot`, global generation capacity, or `geo_static_report_lists` writes.
- [ ] Add `dynamic-report-v1` and a minimal descriptor containing client, fixed report window, and saved filter labels.
- [ ] Add a fenced transactional repository completion method that updates only `geo_static_reports`.
- [ ] Preserve the existing authorized legacy-read endpoints for old snapshot versions.
- [ ] Run the static-report backend suites.

### Task 2: Dynamic report rendering

**Files:**
- Modify: `geo_saas/web/src/pages/reports/StaticReportPage.tsx`
- Create: `geo_saas/web/src/pages/reports/components/DynamicDateRangeReport.tsx`
- Modify: `geo_saas/web/src/pages/insights/Visibility.tsx`
- Modify: `geo_saas/web/src/lib/api/staticReports.ts`
- Test: `geo_saas/web/tests/staticReportFilters.test.mjs`
- Test: `geo_saas/web/tests/staticReportComparison.test.mjs`
- Test: `geo_saas/web/tests/staticReportDynamicMode.test.mjs`

- [ ] Add failing contract tests proving `dynamic-report-v1` does not load snapshot section/list endpoints.
- [ ] Build a fixed-window `InsightsFilterContext` using the report client and report dates.
- [ ] Render existing dynamic Visibility, Citation, and Sentiment components so their API, sorting, loading, comparison, and pagination behavior is reused unchanged.
- [ ] Keep Topic/platform selections interactive and use saved report options plus currently configured options.
- [ ] Keep legacy snapshot rendering for older versions and freeze the current DOM only when the user exports HTML.
- [ ] Run Node contract tests and the production build.

### Task 3: Alias consistency gap

**Files:**
- Modify: `geo_analyzer/src/jobs/_llm_batch/loaders.py`
- Test: `geo_analyzer/tests/test_llm_batch_loaders.py`

- [ ] Add a failing test proving configured brand aliases are part of the LLM candidate-discovery known-name set.
- [ ] Load and normalize `geo_client_brands.aliases` alongside primary own/shadow names.
- [ ] Run the analyzer loader and parser suites.

### Task 4: Retire frozen-list storage

**Files:**
- Create: `migrations/127_drop_static_report_lists.sql`
- Modify: `docs/superpowers/specs/2026-07-13-prompt-report-admin-p0-iteration-design.md`
- Modify: `docs/superpowers/specs/2026-07-13-prompt-report-admin-p0-iteration-design.en.md`

- [ ] Add a guarded migration that refuses to drop the table while dependent rows remain.
- [ ] Drop `geo_static_report_lists` only after the seven Dreamina v5 test reports have been deleted and cascade cleanup leaves zero rows.
- [ ] Document that new reports are saved date-range queries, not immutable data snapshots.

### Task 5: Verification and review

- [ ] Generate the Dreamina report for `2026-06-15..2026-07-14` and confirm creation is lightweight.
- [ ] Compare report metrics against the dynamic Dashboard using the same date range.
- [ ] Benchmark Visibility, Citation, Sentiment, Prompt, and Citation `change_pct` asc/desc endpoints.
- [ ] Browser-test Topic/platform filters, all dashboard charts, list-local loading, comparisons, ranking logos, and removed pagination rows.
- [ ] Re-run backend, frontend, analyzer, import, deletion, and alias regression suites.
- [ ] Perform independent code review and resolve every verified P0/P1/P2 finding.
