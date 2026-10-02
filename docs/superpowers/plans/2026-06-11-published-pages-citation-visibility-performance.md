# Published Pages and Citation/Visibility Performance Implementation Plan

Date: 2026-06-11
Spec: `docs/superpowers/specs/2026-06-11-published-pages-citation-visibility-performance-design.md`
Scope: SaaS Citation Published Pages, Published URL Tracking, Citation timing instrumentation, Visibility endpoint split, Visibility matrix lazy loading and prompt-concept aggregation
Git: no git commands or commits in this implementation flow

## Implementation Contract

This plan implements the full scope from the spec and the product discussion. The implementation must preserve current Citation, Visibility, and Sentiment metric definitions. Database DDL is delivered as a migration SQL file only; Codex does not execute schema changes.

The highest-risk change is the Visibility split. It must improve loading behavior without changing existing first-screen chart values, ranking values, full ranking dialogs, or static report compatibility.

## Step 1: Published Pages Migration SQL

Create `migrations/116_published_urls.sql`.

The migration defines:

- `geo_published_urls`
- `geo_published_url_topics`
- constraints and indexes needed for tenant-safe listing, filtering, upsert, and tracking

`geo_published_urls` columns:

- `id uuid primary key default gen_random_uuid()`
- `client_id uuid not null`
- `title text not null`
- `published_url text not null`
- `normalized_url text not null`
- `published_at date not null`
- `channel text not null`
- `review_status text not null default 'approved'`
- `publish_status text not null default 'published'`
- `draft_doc_url text`
- `owner_name text`
- `notes text`
- `is_active boolean not null default true`
- `created_by uuid`
- `updated_by uuid`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

`geo_published_url_topics` columns:

- `published_url_id uuid not null references geo_published_urls(id) on delete cascade`
- `client_id uuid not null`
- `topic_id uuid not null`
- `created_at timestamptz not null default now()`

Indexes and constraints:

- unique index on `geo_published_urls(client_id, normalized_url)`
- `geo_published_urls(client_id, published_at desc)`
- `geo_published_urls(client_id, channel)`
- `geo_published_urls(client_id, publish_status)`
- `geo_published_urls(client_id, is_active, publish_status, published_at desc)`
- `geo_published_urls(client_id, is_active)`
- `geo_published_url_topics(client_id, topic_id, published_url_id)`
- `geo_published_url_topics(published_url_id)`
- unique relation index on `geo_published_url_topics(published_url_id, topic_id)`

The migration uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. Because these are new tables, regular index creation is acceptable inside the migration. Existing high-volume tables are not altered in this migration.

## Step 2: Backend URL Normalization Utility

Add a shared backend utility under `geo_saas/src/routers/insights/` or `geo_saas/src/utils/` for Published URL and citation source URL normalization.

Required behavior:

- trim whitespace
- lowercase scheme and host
- remove default ports
- remove URL fragment
- remove trailing slash except root
- remove tracking query params: `utm_*`, `fbclid`, `gclid`, `yclid`, `msclkid`
- sort remaining query params deterministically
- preserve meaningful path and non-tracking query params
- reject invalid or unsupported URLs during Published Pages create/import validation

Add unit tests for:

- equivalent URLs with different casing
- trailing slash normalization
- tracking parameter stripping
- meaningful query parameter preservation
- invalid URL rejection

## Step 3: Published Pages Backend Router

Create a SaaS backend router, for example `geo_saas/src/routers/published_urls.py`, and register it in the FastAPI app.

Endpoints:

- `GET /api/published-urls`
- `POST /api/published-urls`
- `PATCH /api/published-urls/{id}`
- `DELETE /api/published-urls/{id}`
- `GET /api/published-urls/channels`
- `GET /api/published-urls/csv-template`
- `POST /api/published-urls/import/preview`
- `POST /api/published-urls/import/commit`

Tenant and permission rules:

- every query includes `client_id`
- `client_id` is derived from the authenticated SaaS request context or validated against accessible clients in the same pattern as existing SaaS routers
- no cross-client Published URL reads, writes, preview commits, or channel lists

List behavior:

- page and page size, default page size `20`
- search matches title, published URL, channel, and topic names
- filters: publish status, channel, topic
- channel list comes from distinct client data, not a hardcoded enum
- topics are workspace topics, matched by `topic_id`

Write behavior:

- create and patch validate required fields
- URL fields are normalized server-side
- delete is implemented as soft delete by setting `is_active = false`
- update and delete preserve tenant isolation

CSV template:

```csv
title,published_url,published_at,topics,channel,review_status,publish_status,draft_doc_url,owner_name,notes
```

CSV import preview:

- accepts UTF-8 CSV only
- file size limit `1 MB`
- row limit `100`
- validates required fields: `title`, `published_url`, `published_at`, `channel`, `publish_status`
- validates `review_status` against `not_submitted`, `in_review`, `approved`, `changes_requested`, and `rejected`
- validates `publish_status` against `draft`, `scheduled`, `published`, and `offline`
- validates URL and date formats
- maps topics by normalized name to existing workspace topics
- rejects unmatched topics without auto-creating topics
- detects duplicate rows in the uploaded CSV
- determines create vs update by `(client_id, normalized_url)`
- returns row-level validation results and aggregate counts

CSV import commit:

- accepts the preview payload or an import token/payload generated by preview
- revalidates input before write
- upserts by `(client_id, normalized_url)`
- updates topic relations for valid rows
- returns inserted, updated, skipped, and invalid counts

Backend tests:

- router import smoke test
- URL normalization tests
- create/edit/disable/delete tenant-scoped behavior
- channel distinct list
- list pagination and filters
- CSV template contents
- CSV preview valid file
- CSV preview missing required fields
- CSV preview invalid URL
- CSV preview unmatched topic
- CSV preview over 100 rows
- CSV commit create and update by normalized URL

## Step 4: Published URL Tracking Backend

Add `GET /api/insights/published-url-tracking`.

Inputs mirror Citation Monitor filters:

- `client_id`
- `date_from`
- `date_to`
- `interval`
- topics
- platforms
- countries
- prompt intent filters
- page and page size

The endpoint:

- reads active Published URLs for the current client
- normalizes citation `source_url` with the same normalization utility
- matches exact normalized URL
- computes tracking metrics using the same date/topic/platform/country/intent filter semantics as Citation
- paginates table rows, default page size `20`

Metrics:

- citation count
- citation share
- citation rank among cited pages under the same filters
- period-over-period citation count change
- period-over-period citation share change
- derived citation category from matched `geo_citations.domain_category`
- last cited time
- platform breakdown
- country breakdown
- triggering Client Prompts
- response contexts for the detail drawer
- 7/14/30-day trend data for the drawer

The tracking endpoint must not call or block the existing Citation endpoints. It uses its own SQL path and indexes from the new Published URLs tables plus existing `geo_citations` indexes.

Tests:

- exact normalized URL match
- no match for unrelated URLs
- date filter behavior
- topic/platform/country filter behavior
- pagination
- metrics align with Top Cited Pages semantics for the same matched URLs
- detail drawer payload handles optional empty fields

## Step 5: Citation Endpoint Timing Logs

Instrument existing endpoints without changing their response shapes:

- `geo_saas/src/routers/insights/citations.py`
- `geo_saas/src/routers/insights/cited_domains.py`
- `geo_saas/src/routers/insights/cited_pages.py`

Each endpoint logs structured timings:

- request parameter summary
- filter construction
- every SQL query duration
- aggregation and response shaping duration
- serialization preparation duration
- total endpoint duration
- row counts

Log fields:

- endpoint name
- phase name
- duration milliseconds
- `client_id`
- date range
- topic count
- platform count
- country count
- intent filter count
- row count when applicable

Safety requirements:

- do not log raw AI response text
- do not log secrets, keys, tokens, or full payloads
- do not add cache in this iteration
- do not change Citation endpoint response schemas

Validation:

- call or import endpoints and confirm logs are emitted around the expected phases
- compare response schema before and after instrumentation for unchanged keys

## Step 6: Visibility Backend Split

Refactor `geo_saas/src/routers/insights/visibility.py` and shared helpers so Visibility data can be served through split endpoints:

- `GET /api/insights/visibility/overview`
- `GET /api/insights/visibility/ranking-groups`
- `GET /api/insights/visibility/ranking-prompts`

Keep existing `GET /api/insights/visibility` as a compatibility endpoint. It may internally compose the new functions or preserve the old response path until the UI is migrated. Existing static reports, exports, and any other old consumers must continue to work.

Overview endpoint returns:

- summary
- visibility score trend
- previous period visibility trend
- average position trend
- previous period average position trend
- competitive series
- SOV ranking
- visibility ranking
- position ranking
- filters metadata

Ranking groups endpoint returns:

- topic/product group rows only
- group display names
- prompt concept counts
- group-level brand columns and summary metrics needed by the collapsed matrix
- no prompt drill-down rows

Ranking prompts endpoint returns:

- prompt-concept rows for one topic or product group
- page metadata
- default page size `20`
- optional prompt search
- current dashboard filters

Prompt-concept aggregation:

- group by normalized Client Prompt text, not `geo_client_prompts.id`
- normalization is trim plus repeated whitespace collapse
- display representative original Client Prompt text
- respect selected topic/product group
- respect selected countries and platforms as filters over underlying data
- never duplicate prompt rows by country or platform

Parity requirements:

- overview values match old endpoint for the same filters
- ranking card values and full ranking dialog data match old endpoint
- matrix group values match old matrix group semantics
- only intended matrix drill-down change is prompt text aggregation instead of `geo_client_prompts.id` duplication

Backend tests:

- old endpoint still imports and returns existing top-level keys
- overview parity for first-screen metrics using fixture or monkeypatched data
- ranking groups returns no prompt drill-down payload
- ranking prompts paginates
- ranking prompts aggregates duplicate prompt texts across country/platform-expanded `geo_client_prompts`
- platform and country filters reduce data while preserving one row per prompt text
- AI Video-like fixture with 30 prompt texts and expanded rows returns 30 prompt concepts across pages

## Step 7: Frontend Request Stability

Update dashboard request logic in SaaS web pages/components:

- `geo_saas/web/src/pages/insights/Visibility.tsx`
- `geo_saas/web/src/pages/insights/Citations.tsx`
- related hooks or components used by Citation/Visibility/Sentiment filters

Required behavior:

- filter-ready gate: no dashboard requests until client id, topics, platforms, countries, and date range are initialized
- debounce filter key for topics/platforms/countries/date by 150-300ms
- state setters for selected arrays return the old reference when values are semantically identical
- keep AbortController and request-sequence guards so stale responses cannot update the UI

Validation:

- entering Visibility and Citation no longer fires an empty-filter request immediately followed by hydrated request
- toggling topics/platforms/countries quickly keeps the latest response only
- no visual regression in filter controls

## Step 8: Citation Frontend Published Pages Tab

Update `geo_saas/web/src/pages/insights/Citations.tsx` and create supporting components as needed.

Citation page tabs:

- `Citation Monitor / 引用监控`
- `Published Pages / 发布页面管理`

Published Pages tab includes:

- toolbar aligned to Citation visual style
- search input
- publish status filter
- dynamic channel filter
- topics filter
- `Download CSV Template`
- `Import CSV`
- `Add Published Page`
- paginated table, default page size `20`

Table columns:

- publish date
- title
- published URL
- topics
- channel
- review status
- publish status
- citation count
- citation share
- citation rank
- period-over-period change
- last cited time
- actions

Actions:

- view details
- edit
- disable
- delete

Forms and dialogs:

- use shadcn/Radix dialogs, selects, popovers, and buttons
- no native `window.alert`, `window.confirm`, `window.prompt`, or native `<select>`
- validation errors are shown inline or with existing toast pattern

CSV import UI:

- upload file through custom UI
- preview step shows create/update/invalid counts
- row-level errors are visible
- commit button is disabled until preview has valid rows
- commit calls backend import commit endpoint
- successful commit refreshes list and tracking data

Detail drawer:

- basic information
- normalized URL
- associated topics
- draft document URL when present
- citation metric summary
- 7/14/30-day trend
- platform and country breakdown
- prompts that triggered citations
- AI response contexts
- citation source context

i18n:

- add keys to `geo_saas/web/src/i18n/locales/zh-CN/insights.json`
- add matching keys to `geo_saas/web/src/i18n/locales/en-US/insights.json`
- TSX uses semantic `t('insights:...')` keys only

## Step 9: Citation Monitor Published URL Tracking Block

In the existing Citation Monitor tab, add `Published URL Tracking / 已发布页面追踪` below `Top Cited Pages / 被引用最多的页面`.

Behavior:

- inherits Citation Monitor filters
- calls `GET /api/insights/published-url-tracking`
- paginated table, default page size `20`
- view details opens the same drawer pattern as the Published Pages tab
- loading and empty states match existing Citation dashboard style

Tracking table fields:

- rank
- published URL
- title
- channel
- derived citation category
- citation count
- citation share
- period-over-period change
- last cited time

This block must not delay initial rendering of the existing Citation charts. It can load after existing core Citation requests begin and must show its own loading state.

## Step 10: Visibility Frontend Split and Lazy Matrix

Update Visibility page and dashboard components:

- call `GET /api/insights/visibility/overview` for first-screen charts and ranking cards
- call `GET /api/insights/visibility/ranking-groups` when the bottom ranking matrix section becomes visible or the user interacts with it
- call `GET /api/insights/visibility/ranking-prompts` only when a topic/product group is expanded

First-screen charts remain visually unchanged:

- visibility score trend
- visibility ranking card
- SOV trend
- SOV ranking card
- average position trend
- position ranking card

Matrix behavior:

- collapsed group rows load independently
- skeleton rows while loading
- prompt rows lazy-load on group expansion
- prompt rows are paginated inside the expanded group
- page size defaults to `20`
- optional prompt search if it fits the existing UI pattern without visual clutter

Zero-difference requirements:

- no missing charts
- no ranking card behavior changes
- no full ranking dialog behavior changes
- no metric value changes caused by frontend mapping
- only prompt drill-down row de-duplication by Client Prompt text changes the visible matrix row count

## Step 11: Backend and Frontend Verification

Backend verification commands:

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_saas
PYTHONPATH=src pytest tests/test_router_import_smoke.py tests/test_citation_rankings.py tests/test_visibility_prompt_metrics.py -q
```

Add new focused tests and include them in the verification command once created:

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_saas
PYTHONPATH=src pytest tests/test_published_urls.py tests/test_published_url_tracking.py tests/test_visibility_split.py -q
```

Frontend verification commands:

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web
npm run build
npm run lint
```

Manual browser verification after local server is available:

- Citation tab switch works
- Published Pages list, search, filters, create, edit, disable, delete work
- CSV template downloads
- CSV preview and commit work with valid and invalid data
- Published URL Tracking respects Citation filters
- Visibility overview charts load first
- Visibility matrix lazy-loads after scroll/interaction
- expanding topic/product loads prompt rows with pagination
- quickly toggling filters does not show stale data

## Step 12: Deploy Script Update After Implementation

After code changes are complete, update `deploy_all.sh` according to the actual changed modules.

Expected changed module:

- `geo_saas`

Expected deployment behavior:

- bump SaaS API and SaaS Web versions if those version variables are present in the script
- keep only SaaS API/SaaS Web image build and Terraform commands active
- comment out unchanged modules’ image build and Terraform commands
- do not include Agent, Collector, Analyzer, or Admin deployment commands unless the implementation actually changes those modules

## Step 13: Final Review Checklist

Before reporting completion, review the implementation against this list:

- migration SQL exists and has not been executed by Codex
- Published Pages APIs are tenant-scoped
- Published Pages UI uses i18n keys and no native browser dialogs/selects
- CSV import uses preview before commit
- CSV import enforces row and size limits
- URL normalization is shared by management and tracking paths
- Published URL Tracking does not slow existing Citation sections
- Citation endpoint responses are unchanged except internal logs
- Citation logs do not leak raw response text or secrets
- Visibility split preserves first-screen values
- old `/api/insights/visibility` compatibility remains available
- Visibility matrix prompt rows aggregate by Client Prompt text
- Visibility matrix prompt rows paginate
- filter-ready gate and debounce reduce duplicate requests
- request race protection remains in place
- build and targeted tests have been run or any inability to run them is documented
