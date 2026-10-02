# Prompt, Report, and Admin P0 Iteration Implementation Plan

**Execution status:** Tasks 1–16 code phase complete. Full regression and two independent re-reviews are verified. Visible browser E2E is intentionally deferred to a separately approved follow-up after this code-review handoff.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver all eight P0 features F1–F8 in the Chinese and English specifications without partial scope, metric drift, cross-tenant access, or live-data fallback in snapshots.

**Architecture:** Keep dynamic drilldowns on the existing dynamic Visibility/Citation/Sentiment stack, centralize Prompt Intent and CSV canonicalization, and add 17 report-scoped immutable list blobs for frozen global sorting. Static generation is globally serialized without Cloud Tasks, uses one guard + one coordinator + at most one worker from the eight-connection pool, applies bounded transaction-local work memory, and enforces row/byte ceilings. Admin changes are thin adapters over shared repositories; Workspace deletion remains guided and bounded rather than becoming an asynchronous deletion system.

Static aggregate server-side cursors stop at 50,001 grouped rows or 16 MiB of retained serialized data and fail closed
above either contract, using `prefetch=1`; bounded display cursors preserve the 700/700/50 snapshot-only truncations.
Frozen-list reads are limited to two concurrent decode/filter/sort operations per SaaS instance; immutable Blob ceilings
are 16 MiB per list and 48 MiB per report, and the full `snapshot_json` ceiling is 32 MiB before transaction entry.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, PostgreSQL/Cloud SQL migrations, React 19, TypeScript, Vite, Tailwind, shadcn/radix, react-i18next, pytest, Node test runner.

**Authoritative specs:**

- `docs/superpowers/specs/2026-07-13-prompt-report-admin-p0-iteration-design.md`
- `docs/superpowers/specs/2026-07-13-prompt-report-admin-p0-iteration-design.en.md`

---

## Implementation Boundaries

- Implement directly in the current `main` checkout, as explicitly approved by the user. Preserve all unrelated uncommitted user changes; do not stage, commit, push, or rewrite history.
- Do not execute migrations against Cloud SQL. Create migration files with manual verification queries for the CTO.
- Do not modify fallback model IDs.
- Do not use native browser alert/confirm/prompt/select controls.
- Preserve JWT-derived tenant scope on every Prompt, Brand, Report, and deletion query.
- Treat F1–F8 as one release gate even though tasks are committed independently.

## File Responsibility Map

### Shared backend

- `geo_common/src/geo_common/services/prompt.py`: logical Prompt reads and true bulk insert primitives.
- `geo_common/src/geo_common/services/prompt_intent.py`: active/historical Intent resolution and canonical validation.
- `geo_common/src/geo_common/services/prompt_deletion.py`: bounded tenant-scoped Prompt cascade deletion.
- `geo_common/src/geo_common/services/brand.py`: canonical brand Alias reads/writes.

### SaaS backend

- `geo_saas/src/routers/prompts.py`: Prompt CRUD, facets, concept resolution, and bounded deletion contract.
- `geo_saas/src/routers/prompt_import.py`: CSV template, Allowed Values, Preview, Commit, and Undo HTTP contract.
- `geo_saas/src/routers/insights/citations.py`, `cited_domains.py`, `cited_pages.py`: Product/Prompt filters and sortable queries.
- `geo_saas/src/routers/sentiment.py`: Prompt/Product filters across aggregate and theme details.
- `geo_saas/src/routers/insights/sorting.py`: validated sort descriptors and SQL whitelist mapping.
- `geo_saas/src/routers/static_reports/snapshot_builder.py`: previous-period and complete list materialization.
- `geo_saas/src/routers/static_reports/repository.py`: immutable report-list pagination and sorting.
- `geo_saas/src/routers/static_reports/models.py`, `router.py`: versioned response models and list endpoint.

### SaaS frontend

- `geo_saas/web/src/components/layout/Sidebar.tsx`, `pages/Insights.tsx`, `App.tsx`: F1 navigation and redirects.
- `geo_saas/web/src/pages/insights/Prompts.tsx`: Prompt filters, grouping, hover entries, and import launch.
- `geo_saas/web/src/pages/insights/PromptDrilldown.tsx`: shared Topic/Product/Prompt drilldown shell.
- `geo_saas/web/src/components/insights/CitationDashboard.tsx`, `SentimentDashboard.tsx`: reusable dynamic domains extracted without formula changes.
- `geo_saas/web/src/components/ui/SortableMetricHeader.tsx`: metric-only sorting interaction.
- `geo_saas/web/src/components/prompts/PromptImportDialog.tsx`: Import CSV and Allowed Values tabs.
- `geo_saas/web/src/lib/api/{prompts,insights,sentiment,staticReports}.ts`: typed API contracts.
- `geo_saas/web/src/pages/reports/components/*`: static comparison and immutable list sorting.
- `geo_saas/web/src/i18n/locales/{zh-CN,en-US}/{sidebar,insights,reports,common}.json`: bilingual copy.

### Admin backend/frontend

- `geo_admin/src/routers/clients.py`: Brand Alias adapter, deletion readiness, schedule stop, and guarded final deletion.
- `geo_admin/src/services/gcp_scheduler.py`: reuse existing scheduler disable operations.
- `geo_admin/web/src/pages/ClientsPage.tsx`: per-brand Alias editor and deletion readiness Dialog.
- `geo_admin/web/src/api/{client,types}.ts`: typed Admin contracts.

### Migrations

- `migrations/124_prompt_import_batches.sql`
- `migrations/125_static_report_list_rows.sql`
- `migrations/126_prompt_cascade_delete_indexes_concurrently.sql`

## Task 1: Create Migration Contracts

**Files:**
- Create: `migrations/124_prompt_import_batches.sql`
- Create: `migrations/125_static_report_list_rows.sql`
- Create: `migrations/126_prompt_cascade_delete_indexes_concurrently.sql`
- Test: manual verification queries embedded at the bottom of each migration

- [ ] **Step 1: Write schema-contract tests as SQL verification blocks**

Add non-mutating verification queries for exact columns, constraints, indexes, and foreign keys. The Prompt batch query must verify the status check contains `COMMITTED`, `REVERTING`, and `REVERTED`. The report-list query must verify the composite primary/foreign keys, JSON-array check, and row-count check.

- [ ] **Step 2: Create migration 124**

Define `geo_prompt_import_batches` exactly as Spec 7.9, including nonnegative count checks, empty UUID-array default, tenant/reporting indexes, `ON DELETE CASCADE` for client ownership, and `ON DELETE SET NULL` for actor IDs.

- [ ] **Step 3: Create migration 125**

Define `geo_static_report_lists` exactly as Spec 9.3: 17 required canonical list types with bounded contiguous JSONB shards, optional compact Citation sort-position index shards, composite tenant key, payload/count checks, and no metric expression indexes.

- [ ] **Step 4: Create migration 126**

Use `CREATE INDEX CONCURRENTLY IF NOT EXISTS` for `(client_id, client_prompt_id)` on the seven fact tables. Do not wrap concurrent index creation in a transaction block.

- [ ] **Step 5: Validate migration syntax without applying it**

Run:

```bash
rg -n "BEGIN|CREATE TABLE|CREATE INDEX|COMMIT|Manual verification" migrations/124_prompt_import_batches.sql migrations/125_static_report_list_rows.sql migrations/126_prompt_cascade_delete_indexes_concurrently.sql
```

Expected: migrations 124/125 are transactional; migration 126 has concurrent indexes and no surrounding transaction.

- [ ] **Step 6: Commit**

```bash
git add migrations/124_prompt_import_batches.sql migrations/125_static_report_list_rows.sql migrations/126_prompt_cascade_delete_indexes_concurrently.sql
git commit -m "feat(db): add prompt import report list and deletion indexes"
```

## Task 2: Implement Database-driven Intent Resolution (F3 Backend)

**Files:**
- Create: `geo_common/src/geo_common/services/prompt_intent.py`
- Create: `geo_common/tests/test_prompt_intent.py`
- Modify: `geo_saas/src/routers/prompts.py`
- Create: `geo_saas/tests/test_prompt_intent_facets.py`

- [ ] **Step 1: Write failing repository tests**

Cover active values, tenant historical unconfigured values, null/blank normalization, canonical case-insensitive input, disabled value rejection, and two-client isolation.

```python
async def test_intent_facets_separate_active_and_tenant_history(intent_service):
    facets = await intent_service.facets("client-a")
    assert facets.active == ["Competitive Evaluation", "Solution Discovery", "Specifics Inquiry"]
    assert facets.unconfigured == ["general"]
```

- [ ] **Step 2: Run the tests and verify failure**

```bash
pytest geo_common/tests/test_prompt_intent.py -q
```

Expected: import failure for `prompt_intent`.

- [ ] **Step 3: Implement the shared service**

Create immutable `IntentFacets(active: list[str], unconfigured: list[str])` and methods `facets(client_id)` and
`require_active(value)`. Queries must scope historical distinct values by client ID and order canonical values
deterministically. `require_active` returns the stored canonical name or raises a typed validation error.

- [ ] **Step 4: Add the facet route and write validation**

Expose `GET /prompts/intent-facets`, derive/validate tenant context using the existing route pattern, and call
`require_active` from single and batch Prompt create paths. Keep historical values readable.

- [ ] **Step 5: Run focused tests**

```bash
pytest geo_common/tests/test_prompt_intent.py geo_saas/tests/test_prompt_intent_facets.py -q
```

Expected: all pass, including cross-client denial.

- [ ] **Step 6: Commit**

```bash
git add geo_common/src/geo_common/services/prompt_intent.py geo_common/tests/test_prompt_intent.py geo_saas/src/routers/prompts.py geo_saas/tests/test_prompt_intent_facets.py
git commit -m "feat(prompts): resolve intent facets from database"
```

## Task 3: Add Intent Filter and Remove General Fallbacks (F3 Frontend)

**Files:**
- Modify: `geo_saas/web/src/pages/insights/Prompts.tsx`
- Modify: `geo_saas/web/src/pages/PromptEditor.tsx`
- Modify: `geo_saas/web/src/lib/api/prompts.ts`
- Modify: `geo_saas/web/src/i18n/locales/zh-CN/insights.json`
- Modify: `geo_saas/web/src/i18n/locales/en-US/insights.json`
- Create: `geo_saas/web/src/pages/insights/promptIntentFilter.ts`
- Create: `geo_saas/web/tests/promptIntentFilter.test.mjs`

- [ ] **Step 1: Write failing pure-state tests**

Test OR within Intent, AND with Topic/Product filters, clearing, Unconfigured grouping, and no fallback write value.

```javascript
test("selected intents are ORed while topic remains an AND constraint", () => {
  const row = { topic_id: "t1", intent: "general" };
  assert.equal(matchesPromptFilters(row, { topicIds: ["t1"], intents: ["general", "Solution Discovery"] }), true);
});
```

- [ ] **Step 2: Run and verify failure**

```bash
node --test geo_saas/web/tests/promptIntentFilter.test.mjs
```

Expected: module/function missing.

- [ ] **Step 3: Implement filter helpers and API types**

Define `IntentFacetsOut`, `getPromptIntentFacets`, grouped option mapping, and a pure `matchesPromptFilters` helper.
Never embed the three current database names in the frontend module.

- [ ] **Step 4: Update Prompt list and editor**

Add a custom multi-select to Prompt filters. Display Active and Unconfigured groups. Remove all three observed
`prompt.intent || "general"` paths from `PromptEditor.tsx`; require an active value and render a localized validation error.

- [ ] **Step 5: Verify tests and production build**

```bash
node --test geo_saas/web/tests/promptIntentFilter.test.mjs
npm --prefix geo_saas/web run build
```

Expected: test pass and Vite build succeeds with no missing i18n keys.

- [ ] **Step 6: Commit**

```bash
git add geo_saas/web/src/pages/insights/Prompts.tsx geo_saas/web/src/pages/PromptEditor.tsx geo_saas/web/src/lib/api/prompts.ts geo_saas/web/src/pages/insights/promptIntentFilter.ts geo_saas/web/tests/promptIntentFilter.test.mjs geo_saas/web/src/i18n/locales/zh-CN/insights.json geo_saas/web/src/i18n/locales/en-US/insights.json
git commit -m "feat(prompts): add database-driven intent filter"
```

## Task 4: Move Prompt to Sidebar with Route Compatibility (F1)

**Files:**
- Modify: `geo_saas/web/src/components/layout/Sidebar.tsx`
- Modify: `geo_saas/web/src/pages/Insights.tsx`
- Modify: `geo_saas/web/src/App.tsx`
- Modify: `geo_saas/web/src/i18n/locales/zh-CN/sidebar.json`
- Modify: `geo_saas/web/src/i18n/locales/en-US/sidebar.json`
- Create: `geo_saas/web/tests/promptNavigation.test.mjs`

- [ ] **Step 1: Write failing navigation-contract tests**

Test the normalized item order, Prompt active-route matcher, and `/prompts` redirect target in a small exported route
configuration module rather than asserting DOM implementation details.

- [ ] **Step 2: Run and verify failure**

```bash
node --test geo_saas/web/tests/promptNavigation.test.mjs
```

Expected: Prompt is absent from the standalone Sidebar configuration.

- [ ] **Step 3: Implement Sidebar and route changes**

Move Prompt between Sentiment and Report, remove only the old Visibility Prompt tab, preserve `/insights/prompts`, and
redirect `/prompts` to the canonical route. Ensure only Prompt is active on that route.

- [ ] **Step 4: Add bilingual keys**

Add semantic Sidebar keys with value `Prompt` in both locales. Do not duplicate shared navigation copy into Insights.

- [ ] **Step 5: Verify navigation tests and build**

```bash
node --test geo_saas/web/tests/promptNavigation.test.mjs
npm --prefix geo_saas/web run build
```

Expected: correct order and successful production build.

- [ ] **Step 6: Commit**

```bash
git add geo_saas/web/src/components/layout/Sidebar.tsx geo_saas/web/src/pages/Insights.tsx geo_saas/web/src/App.tsx geo_saas/web/src/i18n/locales/zh-CN/sidebar.json geo_saas/web/src/i18n/locales/en-US/sidebar.json geo_saas/web/tests/promptNavigation.test.mjs
git commit -m "feat(navigation): promote Prompt to Sidebar"
```

## Task 5: Resolve Logical Prompt Targets and Extend Dynamic Filters (F2 Backend)

**Files:**
- Modify: `geo_common/src/geo_common/services/prompt.py`
- Modify: `geo_common/tests/test_prompt_repository.py`
- Modify: `geo_saas/src/routers/prompts.py`
- Modify: `geo_saas/src/routers/insights/citations.py`
- Modify: `geo_saas/src/routers/insights/cited_domains.py`
- Modify: `geo_saas/src/routers/insights/cited_pages.py`
- Modify: `geo_saas/src/routers/sentiment.py`
- Create: `geo_saas/tests/test_dynamic_drilldown_filters.py`

- [ ] **Step 1: Write failing logical-concept tests**

Assert that representative ID resolution returns every Platform/Country variant with matching tenant, Topic, normalized
text, Product, Intent, and Language, while excluding a different Intent or Language and rejecting another tenant.

- [ ] **Step 2: Write failing filter-propagation tests**

Instrument database calls and assert Product/Prompt predicates appear in Citation current, previous, ranking, domain,
page, and category queries and in Sentiment summary, series, themes, and theme-result queries.

- [ ] **Step 3: Run and verify failure**

```bash
pytest geo_common/tests/test_prompt_repository.py geo_saas/tests/test_dynamic_drilldown_filters.py -q
```

Expected: missing concept resolver and unsupported Citation/Sentiment parameters.

- [ ] **Step 4: Implement concept resolution**

Add `resolve_concept_by_prompt_id(client_id, prompt_id)` returning representative metadata and ordered `prompt_ids`.
Every query includes both `client_id` and the representative ID before deriving the logical key.

- [ ] **Step 5: Implement shared target predicates**

Parse Product and Prompt IDs once per request. Add bound placeholders only; reject invalid UUIDs before SQL. Reuse the
same clause/params object in all current/previous/list/detail branches.

- [ ] **Step 6: Run focused backend tests**

```bash
pytest geo_common/tests/test_prompt_repository.py geo_saas/tests/test_dynamic_drilldown_filters.py geo_saas/tests/test_citation_rankings.py geo_saas/tests/test_sentiment_config_filter.py -q
```

Expected: all pass with no metric-definition changes.

- [ ] **Step 7: Commit**

```bash
git add geo_common/src/geo_common/services/prompt.py geo_common/tests/test_prompt_repository.py geo_saas/src/routers/prompts.py geo_saas/src/routers/insights/citations.py geo_saas/src/routers/insights/cited_domains.py geo_saas/src/routers/insights/cited_pages.py geo_saas/src/routers/sentiment.py geo_saas/tests/test_dynamic_drilldown_filters.py
git commit -m "feat(insights): add product and prompt drilldown filters"
```

## Task 6: Compose Reusable Dynamic Drilldown UI (F2 Frontend)

**Files:**
- Create: `geo_saas/web/src/pages/insights/PromptDrilldown.tsx`
- Create: `geo_saas/web/src/components/insights/CitationDashboard.tsx`
- Create: `geo_saas/web/src/components/insights/SentimentDashboard.tsx`
- Modify: `geo_saas/web/src/pages/insights/Citations.tsx`
- Modify: `geo_saas/web/src/pages/insights/Sentiment.tsx`
- Modify: `geo_saas/web/src/pages/insights/Prompts.tsx`
- Modify: `geo_saas/web/src/lib/api/{prompts,insights,sentiment}.ts`
- Create: `geo_saas/web/tests/promptDrilldownTarget.test.mjs`

- [ ] **Step 1: Write failing target-state tests**

Test Topic, Product, and representative Prompt route serialization; mandatory target intersection; empty intersection;
and that Country remains a list group without complete V/C/S drilldown.

- [ ] **Step 2: Run and verify failure**

```bash
node --test geo_saas/web/tests/promptDrilldownTarget.test.mjs
```

Expected: target adapter module missing.

- [ ] **Step 3: Extract reusable Citation and Sentiment dashboards**

Move rendering/data-loading bodies behind typed props containing the immutable filter snapshot and target predicate.
Keep existing page wrappers as consumers so Sidebar dashboards do not change formulas or presentation.

- [ ] **Step 4: Implement PromptDrilldown**

Render header/back action followed by Visibility, Citation, and Sentiment. Give each domain independent loading/error/
empty state and an AbortController keyed by target plus filters. Resolve representative Prompt ID before domain requests.

- [ ] **Step 5: Wire hover actions and persistent route identity**

Topic/Product/Prompt hover buttons navigate with stable identities. Clicking other row controls must not navigate.

- [ ] **Step 6: Verify unit state and build**

```bash
node --test geo_saas/web/tests/promptDrilldownTarget.test.mjs
npm --prefix geo_saas/web run build
```

Expected: tests pass and extracted pages compile without duplicated metric implementations.

- [ ] **Step 7: Commit**

```bash
git add geo_saas/web/src/pages/insights/PromptDrilldown.tsx geo_saas/web/src/components/insights/CitationDashboard.tsx geo_saas/web/src/components/insights/SentimentDashboard.tsx geo_saas/web/src/pages/insights/Citations.tsx geo_saas/web/src/pages/insights/Sentiment.tsx geo_saas/web/src/pages/insights/Prompts.tsx geo_saas/web/src/lib/api/prompts.ts geo_saas/web/src/lib/api/insights.ts geo_saas/web/src/lib/api/sentiment.ts geo_saas/web/tests/promptDrilldownTarget.test.mjs
git commit -m "feat(prompts): compose complete dynamic drilldowns"
```

## Task 7: Add Validated Full-result Sorting to Dynamic APIs (F6 Backend)

**Files:**
- Create: `geo_saas/src/routers/insights/sorting.py`
- Create: `geo_saas/tests/test_metric_sorting.py`
- Modify: `geo_saas/src/routers/insights/visibility.py`
- Modify: `geo_saas/src/routers/insights/topic_visibility.py`
- Modify: `geo_saas/src/routers/insights/product_visibility.py`
- Modify: `geo_saas/src/routers/insights/citations.py`
- Modify: `geo_saas/src/routers/insights/cited_domains.py`
- Modify: `geo_saas/src/routers/insights/cited_pages.py`
- Modify: `geo_saas/src/routers/insights/published_url_tracking.py`
- Modify: `geo_saas/src/routers/insights/prompt_metrics.py`
- Modify: `geo_saas/src/routers/sentiment.py`

- [ ] **Step 1: Write failing whitelist and pagination tests**

For each list family, test one ascending and descending metric, null-last, stable tie-break, invalid key rejection, and
that `ORDER BY` occurs before `LIMIT/OFFSET`. Include tenant and active filter parameters in every assertion.

```python
def test_domain_sort_rejects_dimension_key():
    with pytest.raises(InvalidSortKey):
        resolve_sort("citation_domains", "domain", "asc")
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest geo_saas/tests/test_metric_sorting.py -q
```

Expected: `sorting` module missing.

- [ ] **Step 3: Implement sort descriptors**

Define immutable descriptors with SQL expression, allowed directions, default direction, null policy, and stable
tie-break expression. Expose `resolve_sort(list_type, sort_by, sort_order)` that returns only server-owned SQL fragments.

- [ ] **Step 4: Apply sorting to every Section 9.2 query**

Add optional parameters without changing current defaults. Move any existing Python slicing after complete sorting, or
replace it with SQL aggregation + sort + pagination. Return `total` from the same filtered universe.

- [ ] **Step 5: Run all insight backend tests**

```bash
pytest geo_saas/tests/test_metric_sorting.py geo_saas/tests/test_visibility_prompt_metrics.py geo_saas/tests/test_visibility_matrix_prompt_aggregation.py geo_saas/tests/test_citation_rankings.py geo_saas/tests/test_published_url_tracking.py geo_saas/tests/test_sentiment_config_filter.py -q
```

Expected: all pass; invalid sort values return validation errors before SQL execution.

- [ ] **Step 6: Commit**

```bash
git add geo_saas/src/routers/insights/sorting.py geo_saas/src/routers/insights/visibility.py geo_saas/src/routers/insights/topic_visibility.py geo_saas/src/routers/insights/product_visibility.py geo_saas/src/routers/insights/citations.py geo_saas/src/routers/insights/cited_domains.py geo_saas/src/routers/insights/cited_pages.py geo_saas/src/routers/insights/published_url_tracking.py geo_saas/src/routers/insights/prompt_metrics.py geo_saas/src/routers/sentiment.py geo_saas/tests/test_metric_sorting.py
git commit -m "feat(insights): sort metric lists before pagination"
```

## Task 8: Add Shared Metric-only Sort Controls (F6 Frontend)

**Files:**
- Create: `geo_saas/web/src/components/ui/SortableMetricHeader.tsx`
- Create: `geo_saas/web/src/lib/metricSort.ts`
- Create: `geo_saas/web/tests/metricSort.test.mjs`
- Modify: `geo_saas/web/src/pages/insights/{Visibility,Citations,Sentiment,Prompts}.tsx`
- Modify: `geo_saas/web/src/components/insights/{VisibilityDashboard,CitationDashboard,SentimentDashboard}.tsx`
- Modify: `geo_saas/web/src/lib/api/{insights,sentiment,prompts}.ts`
- Modify: `geo_saas/web/src/i18n/locales/{zh-CN,en-US}/insights.json`

- [ ] **Step 1: Write failing sort-state tests**

Test inactive/ascending/descending transitions, rank default ascending, ordinary metric default descending, null-last
client comparator for complete small datasets, and page reset on sort/filter change.

- [ ] **Step 2: Run and verify failure**

```bash
node --test geo_saas/web/tests/metricSort.test.mjs
```

Expected: metric sort module missing.

- [ ] **Step 3: Implement shared state and header**

`SortableMetricHeader` accepts `metricKey`, `direction`, `defaultDirection`, and `onChange`. It renders no API-specific
logic. Dimension headers remain ordinary `TableHead` and never receive this component.

- [ ] **Step 4: Wire every mandatory dynamic list**

Pass sort parameters to APIs for all paginated lists. Reset offset/page to zero when sort changes. Use the client
comparator only when the response explicitly proves `items.length === total`.

- [ ] **Step 5: Verify helper tests, lint, and build**

```bash
node --test geo_saas/web/tests/metricSort.test.mjs
npm --prefix geo_saas/web run lint
npm --prefix geo_saas/web run build
```

Expected: pass with sort controls only on Metric columns.

- [ ] **Step 6: Commit**

```bash
git add geo_saas/web/src/components/ui/SortableMetricHeader.tsx geo_saas/web/src/lib/metricSort.ts geo_saas/web/tests/metricSort.test.mjs geo_saas/web/src/pages/insights/Visibility.tsx geo_saas/web/src/pages/insights/Citations.tsx geo_saas/web/src/pages/insights/Sentiment.tsx geo_saas/web/src/pages/insights/Prompts.tsx geo_saas/web/src/components/insights/VisibilityDashboard.tsx geo_saas/web/src/components/insights/CitationDashboard.tsx geo_saas/web/src/components/insights/SentimentDashboard.tsx geo_saas/web/src/lib/api/insights.ts geo_saas/web/src/lib/api/sentiment.ts geo_saas/web/src/lib/api/prompts.ts geo_saas/web/src/i18n/locales/zh-CN/insights.json geo_saas/web/src/i18n/locales/en-US/insights.json
git commit -m "feat(ui): add metric-only global sorting"
```

## Task 9: Implement Prompt Import Parser, Preview, Commit, and Undo (F4 Backend)

**Files:**
- Create: `geo_saas/src/routers/prompt_import.py`
- Create: `geo_saas/src/routers/prompt_import_service.py`
- Modify: `geo_saas/src/routers/__init__.py`
- Modify: `geo_saas/src/main.py`
- Modify: `geo_common/src/geo_common/services/prompt.py`
- Modify: `geo_common/src/geo_common/services/prompt_deletion.py`
- Create: `geo_saas/tests/test_prompt_import_parser.py`
- Create: `geo_saas/tests/test_prompt_import_router.py`
- Modify: `geo_common/tests/test_prompt_repository.py`

- [ ] **Step 1: Write failing parser table tests**

Cover BOM, exact English header order, quoted comma, semicolon, pipe, trim, empty-token removal, case canonicalization,
deduplication, full-width punctuation rejection, single Language, multi-row equivalence, all four limits, and placeholder rejection.

- [ ] **Step 2: Write failing Preview/Commit tests**

Cover tenant Customer/Topic/Product checks, Global/Workspace allowlists, platform-country support, quota by logical
concept, create/skip/conflict/invalid, stale manifest 409, concurrent tenant lock, inserted-count mismatch rollback,
audit row, and Undo idempotency.

- [ ] **Step 3: Run and verify failure**

```bash
pytest geo_saas/tests/test_prompt_import_parser.py geo_saas/tests/test_prompt_import_router.py -q
```

Expected: import router/service missing.

- [ ] **Step 4: Implement canonical parser and Allowed Values service**

Use Python's `csv` module, never split the raw line manually. Normalize only multi-value cells with the three ASCII
delimiters. Produce immutable normalized rows and sorted physical variants so identical inputs produce the same manifest hash.

- [ ] **Step 5: Implement true bulk repository insert**

Add an asyncpg bulk operation inside a caller-owned transaction using ordered UUIDs and records. Do not acquire or
commit per row. Return IDs in manifest order and assert count equality.

- [ ] **Step 6: Implement all import endpoints**

Return Workspace-aware template and Allowed Values JSON/CSV, multipart Preview and Commit, and tenant-scoped Undo.
Commit holds the advisory lock through re-preview, insert, and audit write. Undo uses the cascade service and batch lifecycle.

- [ ] **Step 7: Run backend suites**

```bash
pytest geo_saas/tests/test_prompt_import_parser.py geo_saas/tests/test_prompt_import_router.py geo_common/tests/test_prompt_repository.py geo_common/tests/test_prompt_cascade_deletion.py -q
```

Expected: all pass, including rollback and two-client tests.

- [ ] **Step 8: Commit**

```bash
git add geo_saas/src/routers/prompt_import.py geo_saas/src/routers/prompt_import_service.py geo_saas/src/routers/__init__.py geo_saas/src/main.py geo_common/src/geo_common/services/prompt.py geo_common/src/geo_common/services/prompt_deletion.py geo_saas/tests/test_prompt_import_parser.py geo_saas/tests/test_prompt_import_router.py geo_common/tests/test_prompt_repository.py
git commit -m "feat(prompts): add safe CSV import workflow"
```

## Task 10: Build Prompt Import Dialog and Allowed Values Tab (F4 Frontend)

**Files:**
- Create: `geo_saas/web/src/components/prompts/PromptImportDialog.tsx`
- Create: `geo_saas/web/src/components/prompts/AllowedValuesTable.tsx`
- Create: `geo_saas/web/src/components/prompts/ImportPreviewTable.tsx`
- Modify: `geo_saas/web/src/pages/insights/Prompts.tsx`
- Modify: `geo_saas/web/src/lib/api/prompts.ts`
- Modify: `geo_saas/web/src/i18n/locales/{zh-CN,en-US}/insights.json`
- Create: `geo_saas/web/tests/promptImportViewModel.test.mjs`

- [ ] **Step 1: Write failing view-model tests**

Test file selection reset, Preview summary, Commit-disabled rules, stale Preview replacement, Allowed Values grouping,
Product parent display, canonical Value copy, Workspace switch reset, and Undo result state.

- [ ] **Step 2: Run and verify failure**

```bash
node --test geo_saas/web/tests/promptImportViewModel.test.mjs
```

Expected: view-model module missing.

- [ ] **Step 3: Add typed API functions**

Implement template/allowed-values downloads, multipart Preview/Commit, and Undo. Preserve UTF-8 BOM downloads and
server filenames. Abort requests when Workspace or file changes.

- [ ] **Step 4: Implement the custom Dialog**

Build `Import CSV` and `Allowed Values` radix Tabs. Show exact counts, quota impact, row actions/errors/warnings,
search/copy/download controls, stale Preview state, result Dialog, and explicit Undo confirmation. Use no native dialogs.

- [ ] **Step 5: Wire the Prompt page entry point**

Add the batch-upload action beside existing management/export actions without removing current export behavior.

- [ ] **Step 6: Verify unit state and build**

```bash
node --test geo_saas/web/tests/promptImportViewModel.test.mjs
npm --prefix geo_saas/web run build
```

Expected: pass with both locale files complete.

- [ ] **Step 7: Commit**

```bash
git add geo_saas/web/src/components/prompts/PromptImportDialog.tsx geo_saas/web/src/components/prompts/AllowedValuesTable.tsx geo_saas/web/src/components/prompts/ImportPreviewTable.tsx geo_saas/web/src/pages/insights/Prompts.tsx geo_saas/web/src/lib/api/prompts.ts geo_saas/web/src/i18n/locales/zh-CN/insights.json geo_saas/web/src/i18n/locales/en-US/insights.json geo_saas/web/tests/promptImportViewModel.test.mjs
git commit -m "feat(prompts): add CSV import and allowed values UI"
```

## Task 11: Materialize Static Previous-period Metrics (F5)

**Files:**
- Modify: `geo_saas/src/routers/static_reports/models.py`
- Modify: `geo_saas/src/routers/static_reports/snapshot_builder.py`
- Modify: `geo_saas/src/routers/static_reports/router.py`
- Modify: `geo_saas/tests/test_static_reports_models.py`
- Modify: `geo_saas/tests/test_static_reports_snapshot_builder.py`
- Modify: `geo_saas/tests/test_static_reports_router.py`
- Modify: `geo_saas/web/src/pages/reports/StaticReportPage.tsx`
- Modify: `geo_saas/web/src/pages/reports/components/{StaticVisibilitySection,StaticCitationSection,StaticSentimentSection}.tsx`
- Modify: `geo_saas/web/src/i18n/locales/{zh-CN,en-US}/reports.json`

- [ ] **Step 1: Write failing date-window and formula tests**

Add 1/7/30-day boundary cases, month-boundary cases, zero/missing previous denominator, percentage-point versus
relative-percent parity, rank/position direction, missing-baseline warnings, and old-version deserialization.

- [ ] **Step 2: Run and verify failure**

```bash
pytest geo_saas/tests/test_static_reports_models.py geo_saas/tests/test_static_reports_snapshot_builder.py geo_saas/tests/test_static_reports_router.py -q
```

Expected: change fields remain null and previous series are absent.

- [ ] **Step 3: Bump Snapshot version and materialize both windows**

Compute previous boundaries once and pass them to Visibility, Citation, and Sentiment builders. Reuse the exact dynamic
field formulas and null rules. Store warnings instead of failing a report when only the previous baseline is missing.

- [ ] **Step 4: Update static UI**

Render frozen change fields and previous series, use improvement-aware rank/position styling, display `—` for null,
and keep legacy Snapshot rendering without live-data fallback.

- [ ] **Step 5: Run backend tests and frontend build**

```bash
pytest geo_saas/tests/test_static_reports_models.py geo_saas/tests/test_static_reports_snapshot_builder.py geo_saas/tests/test_static_reports_router.py -q
npm --prefix geo_saas/web run build
```

Expected: current/previous parity tests pass and legacy fixtures still render.

- [ ] **Step 6: Commit**

```bash
git add geo_saas/src/routers/static_reports/models.py geo_saas/src/routers/static_reports/snapshot_builder.py geo_saas/src/routers/static_reports/router.py geo_saas/tests/test_static_reports_models.py geo_saas/tests/test_static_reports_snapshot_builder.py geo_saas/tests/test_static_reports_router.py geo_saas/web/src/pages/reports/StaticReportPage.tsx geo_saas/web/src/pages/reports/components/StaticVisibilitySection.tsx geo_saas/web/src/pages/reports/components/StaticCitationSection.tsx geo_saas/web/src/pages/reports/components/StaticSentimentSection.tsx geo_saas/web/src/i18n/locales/zh-CN/reports.json geo_saas/web/src/i18n/locales/en-US/reports.json
git commit -m "feat(reports): materialize previous-period comparisons"
```

## Task 12: Materialize and Sort Complete Online Snapshot Lists (F6 Static)

**Files:**
- Modify: `geo_saas/src/routers/static_reports/snapshot_builder.py`
- Modify: `geo_saas/src/routers/static_reports/repository.py`
- Modify: `geo_saas/src/routers/static_reports/models.py`
- Modify: `geo_saas/src/routers/static_reports/router.py`
- Create: `geo_saas/tests/test_static_report_list_rows.py`
- Modify: `geo_saas/web/src/lib/api/staticReports.ts`
- Modify: `geo_saas/web/src/pages/reports/components/{StaticVisibilitySection,StaticCitationSection,StaticSentimentSection,SnapshotTable}.tsx`
- Create: `geo_saas/web/tests/staticReportListSort.test.mjs`

- [ ] **Step 1: Write failing repository/API tests**

Test exact 17-blob insertion, atomic replacement, list-type and metric whitelists, tenant/report pairing, total, default
limit 20, maximum 100, asc/desc, null-last, stable ties, and legacy reports with no list blobs.

- [ ] **Step 2: Run and verify failure**

```bash
pytest geo_saas/tests/test_static_report_list_rows.py -q
```

Expected: repository lacks report-list methods.

- [ ] **Step 3: Implement list-blob repository and materialization**

Build complete aggregate rows with the same frozen metrics used by `snapshot_json`. Replace them in the same final
materialization transaction as the Snapshot update. Group canonical rows into exactly 17 versioned blobs, keep default
20-row first pages in the initial payload, and reject incomplete or over-limit blob sets before persistence. Hold the
local and cross-instance capacity gates through Blob construction and the fenced final commit; contention returns
retryable PENDING without waiting behind another report.

- [ ] **Step 4: Implement the list endpoint**

Validate tenant ownership, list type, metric key, direction, limit, and offset. Sort the complete frozen list. Legacy
versions return `sorting_unavailable_for_snapshot_version`, never live data.

- [ ] **Step 5: Wire static Metric headers**

Use `SortableMetricHeader` only for metric columns, reset offset on sort, and hide controls for legacy snapshots and
offline rendering.

- [ ] **Step 6: Verify backend, helper, and build**

```bash
pytest geo_saas/tests/test_static_report_list_rows.py geo_saas/tests/test_static_reports_router.py -q
node --test geo_saas/web/tests/staticReportListSort.test.mjs
npm --prefix geo_saas/web run build
```

Expected: immutable global sorting passes and offline paths contain no API dependency.

- [ ] **Step 7: Commit**

```bash
git add geo_saas/src/routers/static_reports/snapshot_builder.py geo_saas/src/routers/static_reports/repository.py geo_saas/src/routers/static_reports/models.py geo_saas/src/routers/static_reports/router.py geo_saas/tests/test_static_report_list_rows.py geo_saas/web/src/lib/api/staticReports.ts geo_saas/web/src/pages/reports/components/StaticVisibilitySection.tsx geo_saas/web/src/pages/reports/components/StaticCitationSection.tsx geo_saas/web/src/pages/reports/components/StaticSentimentSection.tsx geo_saas/web/src/pages/reports/components/SnapshotTable.tsx geo_saas/web/tests/staticReportListSort.test.mjs
git commit -m "feat(reports): sort complete frozen snapshot lists"
```

## Task 13: Align Admin Brand Alias with Canonical Brand Rows (F7)

**Files:**
- Modify: `geo_common/src/geo_common/services/brand.py`
- Create: `geo_common/tests/test_brand_repository.py`
- Modify: `geo_admin/src/routers/clients.py`
- Create: `geo_admin/tests/test_client_brand_aliases.py`
- Modify: `geo_admin/web/src/api/{client,types}.ts`
- Modify: `geo_admin/web/src/pages/ClientsPage.tsx`
- Create: `geo_admin/web/src/components/ClientBrandAliases.tsx`

- [ ] **Step 1: Write failing repository/router tests**

Test Own/Shadow listing, tenant + brand update scope, cross-tenant 404, trim, empty removal, case-insensitive dedupe with
first-order preservation, and empty-array clear. Assert `geo_clients.aliases` is never updated.

- [ ] **Step 2: Run and verify failure**

```bash
pytest geo_common/tests/test_brand_repository.py geo_admin/tests/test_client_brand_aliases.py -q
```

Expected: Admin brand endpoints are missing.

- [ ] **Step 3: Implement thin Admin endpoints**

Reuse `BrandRepository`; do not copy SQL or proxy SaaS HTTP. Remove aliases from `ClientUpdate`, retain the old response
field read-only, and scope brand lookup by both IDs.

- [ ] **Step 4: Implement per-brand Admin UI**

Remove the legacy field from Client Info. Render Own/Shadow brand cards with Alias tags/input and independent save state.
Reload from the brand endpoint after save and refresh. Keep unrelated Client editing unchanged.

- [ ] **Step 5: Verify backend and Admin typecheck/build**

```bash
pytest geo_common/tests/test_brand_repository.py geo_admin/tests/test_client_brand_aliases.py -q
npm --prefix geo_admin/web run typecheck
npm --prefix geo_admin/web run build
```

Expected: all pass and no legacy Alias write remains.

- [ ] **Step 6: Commit**

```bash
git add geo_common/src/geo_common/services/brand.py geo_common/tests/test_brand_repository.py geo_admin/src/routers/clients.py geo_admin/tests/test_client_brand_aliases.py geo_admin/web/src/api/client.ts geo_admin/web/src/api/types.ts geo_admin/web/src/pages/ClientsPage.tsx geo_admin/web/src/components/ClientBrandAliases.tsx
git commit -m "fix(admin): align brand aliases with SaaS source"
```

## Task 14: Add Workspace Readiness and Guarded Final Delete (F8 Backend)

**Files:**
- Modify: `geo_admin/src/routers/clients.py`
- Modify: `geo_admin/src/services/gcp_scheduler.py`
- Modify: `geo_common/src/geo_common/services/prompt_deletion.py`
- Create: `geo_admin/tests/test_workspace_deletion_readiness.py`
- Modify: `geo_saas/src/routers/prompts.py`
- Modify: `geo_saas/tests/test_prompts_cascade_delete.py`

- [ ] **Step 1: Write failing readiness tests**

Cover all returned counts, three scheduler states, recommended next action, zero-Prompt/Topic requirement, orphan-fact
blocker, and two-client isolation.

- [ ] **Step 2: Write failing deletion guard tests**

Cover default 25/hard 100 Prompt IDs, no truncation, transaction rollback, final-delete 409 blockers, typed single-flight
failure, fast pool-acquire timeout, and ordinary client list/create availability during simulated cleanup.

- [ ] **Step 3: Run and verify failure**

```bash
pytest geo_admin/tests/test_workspace_deletion_readiness.py geo_saas/tests/test_prompts_cascade_delete.py -q
```

Expected: readiness endpoint and bounded contract are missing.

- [ ] **Step 4: Implement readiness and Stop All Scheduling**

Build a read-only tenant-scoped aggregate response. Reuse the scheduler service to disable collector, analyzer, and
LLM-discovery schedules together, then return refreshed state.

- [ ] **Step 5: Bound Prompt cascade deletion**

Default server batch size to 25 and reject more than 100 IDs with 422. Preserve one transaction per batch and current
fact deletion order. Never parallelize inside the service.

- [ ] **Step 6: Guard final Workspace deletion**

Rerun readiness, acquire a global advisory single-flight lock, fail fast for blockers/concurrency, stop scheduler jobs,
and execute final Client deletion with acquire/statement timeouts. Do not enter CASCADE while high-volume facts remain.

- [ ] **Step 7: Run backend tests**

```bash
pytest geo_admin/tests/test_workspace_deletion_readiness.py geo_admin/tests/test_db_adapter.py geo_saas/tests/test_prompts_cascade_delete.py geo_common/tests/test_prompt_cascade_deletion.py -q
```

Expected: all pass and simulated pool availability remains intact.

- [ ] **Step 8: Commit**

```bash
git add geo_admin/src/routers/clients.py geo_admin/src/services/gcp_scheduler.py geo_common/src/geo_common/services/prompt_deletion.py geo_admin/tests/test_workspace_deletion_readiness.py geo_saas/src/routers/prompts.py geo_saas/tests/test_prompts_cascade_delete.py
git commit -m "fix(admin): guide and guard workspace deletion"
```

## Task 15: Build Guided Workspace Cleanup UI (F8 Frontend)

**Files:**
- Create: `geo_admin/web/src/components/WorkspaceDeletionDialog.tsx`
- Modify: `geo_admin/web/src/pages/ClientsPage.tsx`
- Modify: `geo_admin/web/src/api/{client,types}.ts`
- Modify: `geo_saas/web/src/pages/PromptEditor.tsx`
- Modify: `geo_saas/web/src/pages/PromptEditor.parts/BulkActionBar.tsx`
- Create: `geo_saas/web/src/pages/PromptEditor.parts/WorkspaceCleanupDialog.tsx`
- Create: `geo_saas/web/tests/workspaceCleanupState.test.mjs`

- [ ] **Step 1: Write failing cleanup-state tests**

Test readiness step selection, schedule-stop refresh, configured SaaS link construction, Prompt batch sequencing,
failure/resume, remaining progress, Topic step, exact-name enablement, request disablement, and duplicate-click prevention.

- [ ] **Step 2: Run and verify failure**

```bash
node --test geo_saas/web/tests/workspaceCleanupState.test.mjs
```

Expected: cleanup-state module is missing.

- [ ] **Step 3: Implement Admin readiness Dialog**

Render counts, blockers, Stop All Scheduling, configured Prompt/Topic links, refresh-on-focus/return, typed-name final
confirmation, and a single in-flight delete. Use custom Dialog and structured API errors.

- [ ] **Step 4: Implement SaaS Workspace Cleanup mode**

Require explicit confirmation, fetch remaining physical Prompt IDs tenant-scoped, submit batches serially within server
limits, update deleted/remaining/progress, stop on error, and resume from fresh state. Preserve ordinary bulk delete.

- [ ] **Step 5: Verify state tests and both builds**

```bash
node --test geo_saas/web/tests/workspaceCleanupState.test.mjs
npm --prefix geo_saas/web run build
npm --prefix geo_admin/web run typecheck
npm --prefix geo_admin/web run build
```

Expected: pass with no native dialogs and no hardcoded host/client ID.

- [ ] **Step 6: Commit**

```bash
git add geo_admin/web/src/components/WorkspaceDeletionDialog.tsx geo_admin/web/src/pages/ClientsPage.tsx geo_admin/web/src/api/client.ts geo_admin/web/src/api/types.ts geo_saas/web/src/pages/PromptEditor.tsx geo_saas/web/src/pages/PromptEditor.parts/BulkActionBar.tsx geo_saas/web/src/pages/PromptEditor.parts/WorkspaceCleanupDialog.tsx geo_saas/web/tests/workspaceCleanupState.test.mjs
git commit -m "feat(admin): add guided workspace cleanup UI"
```

## Task 16: Run Cross-feature Regression and Tenant Verification; Hand Off Before Visible E2E

**Files:**
- Read: `docs/local-dev/codex-visible-e2e.md`
- Modify: only scoped F1–F8 files when a failing test proves a defect
- Record: test and E2E evidence in the implementation handoff

- [ ] **Step 1: Run all backend suites**

```bash
pytest geo_common/tests geo_saas/tests geo_admin/tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend static verification**

```bash
node --test geo_saas/web/tests/*.test.mjs
npm --prefix geo_saas/web run lint
npm --prefix geo_saas/web run build
npm --prefix geo_admin/web run typecheck
npm --prefix geo_admin/web run build
```

Expected: all commands exit 0.

- [ ] **Step 3: Run two-tenant API verification**

For Prompt facets/concept/import, Citation/Sentiment drilldown, static report lists, Brand Alias, readiness, and deletion,
issue the same request with two authorized client contexts. Verify each response contains only its tenant and every
cross-tenant ID returns 404/403 without existence leakage.

- [ ] **Step 4: Hand off the completed code-review phase before visible SaaS E2E**

Stop after pure-code regression and independent double review, report the evidence, and recommend whether browser
automation is ready. Do not start browser automation in the same phase.

- [ ] **Step 5: Run visible SaaS/Admin E2E only after a separate user approval**

After approval, read `docs/local-dev/codex-visible-e2e.md`, use SaaS `6174`, Admin `6173`, and
`gotyechen@gmail.com`. Verify all F1–F8 browser paths. Never mutate production/customer data; destructive-path
success tests require an explicitly authorized disposable AnswerX Workspace.

- [ ] **Step 6: Inspect prohibited regressions**

```bash
rg -n '\|\| "general"|window\.(alert|confirm|prompt)|geo_clients\.aliases|snapshot.*live|sort.*slice' geo_saas geo_admin geo_common
```

Expected: no new Prompt fallback, native dialog, legacy Alias write, live Snapshot fallback, or page-only sort path.

- [ ] **Step 7: Verify migration handoff**

Confirm migrations 124–126 contain manual verification queries and were not applied automatically. Handoff order is
124, 125, then 126 during a low-traffic window because concurrent index creation can be long-running.

- [ ] **Step 8: Produce final scope evidence**

Create a handoff table with F1–F8, commit IDs, test commands, E2E evidence, migration status, and operational notes.
Every row must be Complete before requesting merge.

## Final Plan Coverage Matrix

| Spec feature | Implementation tasks | Release evidence |
|---|---|---|
| F1 Prompt Sidebar | 4, 16 | Navigation contract, build, visible route E2E |
| F2 Complete dynamic drilldown | 5, 6, 16 | Backend propagation tests and 3 targets × 3 domains E2E |
| F3 Intent Filter | 2, 3, 16 | DB-driven facet/write tests and historical-value UI E2E |
| F4 CSV import | 1, 9, 10, 16 | Parser/transaction/concurrency tests and full import/Undo E2E |
| F5 Static comparison | 11, 16 | 1/7/30 parity tests and Snapshot UI E2E |
| F6 Metric sorting | 1, 7, 8, 12, 16 | Dynamic/static full-result sort tests and offline exclusion |
| F7 Brand Alias | 13, 16 | Canonical DB parity, cross-tenant denial, Admin refresh E2E |
| F8 Workspace deletion | 1, 14, 15, 16 | Readiness/bounded/pool tests and guided-path E2E |

Implementation is not complete until every row has evidence and all three migrations have an explicit CTO handoff
state. If a required migration is not executed, deployment remains blocked rather than silently degrading the feature.
