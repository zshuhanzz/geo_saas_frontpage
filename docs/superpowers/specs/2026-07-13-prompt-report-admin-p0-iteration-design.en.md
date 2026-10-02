# Prompt, Report, and Admin P0 Iteration — Technical Specification

**Date:** 2026-07-13  
**Status:** Final / Implementation and Code Review Verified  
**Scope:** Original requirements 16–20, restructured into eight independently testable features  
**Modules:** `geo_saas`, `geo_admin`, `geo_common`, and Cloud SQL migrations  
**Chinese mirror:** `2026-07-13-prompt-report-admin-p0-iteration-design.md`

## 1. Background and Goal

The original input grouped the work under requirements 16–20. Those numbers combine several independently
implementable capabilities. To prevent partial delivery, this specification uses the eight features below as the
only authoritative scope and acceptance units.

| Feature ID | Final capability | Original source | Independent completion criterion |
|---|---|---|---|
| F1 | Move Prompt to the Sidebar | 16.1 | Remove the Prompt tab from Visibility; complete Sidebar order, bilingual naming, active state, and route compatibility |
| F2 | Complete Topic/Product/Prompt drilldowns with V/C/S | 16.1 | All three entry points compose the existing dynamic Visibility, Citation, and Sentiment dashboards, with every subquery receiving the same target filter |
| F3 | Prompt Intent Filter | 16.2 | Options come from active Global Config plus tenant historical values; no hardcoded three-value enum |
| F4 | Prompt CSV batch import | 17 | Template, Allowed Values, Preview, validation, transactional Commit, audit, and Undo all work end to end |
| F5 | Fully dynamic fixed-date reports with previous-period comparison | 18.1 | Persist only tenant, date range, and filter metadata; reuse dynamic Dashboard V/C/S APIs for current, previous, and delta |
| F6 | Global metric-column sorting for every list | 18.2 | Dynamic, drilldown, and online dynamic-report lists sort the full filtered result before pagination; dimension columns do not sort; offline HTML does not sort |
| F7 | Align Admin Brand Alias data source | 19 | Admin reads and writes `geo_client_brands.aliases` by brand ID; SaaS, Analyzer, and the brand schema remain unchanged |
| F8 | Guided Workspace cleanup and protected deletion | 20 | Readiness, schedule stop, bounded cascading Prompt cleanup, Topic cleanup, typed-name confirmation, and final deletion protection all work |

A feature is complete only when its UI, API, data semantics, error handling, tenant isolation, tests, and acceptance
criteria are all satisfied. F1–F3 and F5–F6 are not optional subparts merely because the original numbering grouped them.

This specification is based on the current workspace code and read-only Cloud SQL inspection performed on
2026-07-13. Git HEAD and older design documents do not override the observed implementation.

### 1.1 Document Precedence and Implementation Constraints

If descriptions conflict, use this precedence order:

1. The explicit contract and acceptance criteria for each feature in this document.
2. The final product decisions in Section 2.
3. Existing dynamic Dashboard metric definitions and response structures.
4. The short original descriptions for requirements 16–20.

Do not infer requirements from the old Prompt tab, static-report query code, or the legacy Alias column when this
document records a different final decision. Deliver all DDL as migration files. Do not modify Cloud SQL schema
directly during implementation or verification.

## 2. Confirmed Product Decisions

### 2.1 Prompt Information Architecture

- Remove Prompt from the tab strip inside Visibility.
- Sidebar order is Visibility → Citation → Sentiment → Prompt → Report.
- Both `zh-CN` and `en-US` display the label `Prompt`.
- Reuse the existing `/insights/prompts` body and Insights filter context.
- Keep the legacy `/prompts` redirect so old links remain valid.

### 2.2 Dynamic Drilldown Source

- Drilldowns reuse only dynamic Dashboard APIs, metric definitions, response models, charts, and lists.
- Static reports are neither a data source nor an implementation reference for dynamic drilldowns.
- Topic, Product, and Prompt drilldowns each compose complete dynamic Visibility, Citation, and Sentiment sections.

### 2.3 Intent Filtering

- Filter `geo_client_prompts.intent`, not the Visibility/Citation/Sentiment category field.
- Primary options come from active `geo_global_intents` rows; the frontend must not hardcode names.
- Tenant data values that are no longer configured appear under Unconfigured Intents and remain filterable.
- New and imported Prompts may use only active Intent values. Historical unconfigured values are read-only.

### 2.4 CSV Input

- V1 accepts local CSV files only.
- Users may export CSV from Feishu Sheets, but the product does not read Feishu links or request Feishu authorization.
- All CSV headers remain English regardless of UI locale.
- The import Dialog contains `Import CSV` and `Allowed Values` tabs.
- Provide separate Import Template CSV and Workspace Allowed Values CSV downloads. V1 does not accept XLSX.

### 2.5 Report Comparison Semantics

- Compare the selected interval with the immediately preceding interval of equal length.
- One day compares with the previous day; seven days with the previous seven days; thirty days with the previous thirty days.
- Data contracts and code use `previous_period` / period-over-period.
- This iteration does not implement a true prior-year YoY comparison.

### 2.6 Online and Offline Static Reports

- Online Snapshot reports opened by `report_id` support list sorting.
- Sorting reads only the immutable data materialized for that report ID, never current live Dashboard data.
- Exported offline HTML has no interactive sorting and keeps the export-time default order.

### 2.7 Brand Alias

- SaaS and Analyzer continue using `geo_client_brands.aliases` as the runtime source of truth.
- Change only Admin UI/API so they read and write the same brand rows.
- Do not change SaaS UI, Analyzer, brand schema, or the legacy `geo_clients.aliases` column.

### 2.8 Workspace Deletion

- V1 uses guided cleanup plus deletion guards; it does not add a persistent asynchronous Workspace deletion worker.
- Cleanup order is Stop Scheduling → batch-delete Prompts → delete Topics → return to Admin for final deletion.
- Prompt deletion reuses `PromptCascadeDeletionService`.
- Final deletion requires the full Workspace name and disables the button while the request is running.

## 3. Cloud SQL Fact Baseline

### 3.1 Intent

Active Intent values are:

- `Solution Discovery`
- `Specifics Inquiry`
- `Competitive Evaluation`

Prompt data also contains historical `general`: four physical rows and one logical concept in Pandaaa. No current
Prompt has a null/blank Intent, and no Prompt-to-Topic tenant ownership mismatch was found.

### 3.2 Prompt Duplicates

- Eight exact duplicate Prompt-variant groups exist.
- They contain ten extra physical rows.
- The duplicates are in AnswerX and Pandaaa.

Import Preview must distinguish file duplicates, existing exact variants, an existing logical concept missing some
platform/country variants, and metadata conflicts involving Intent/Product.

### 3.3 Alias Divergence

Production data contains Workspaces where canonical aliases exist but legacy aliases are empty, Workspaces where the
two values differ, and only a small set where both match. Continuing to edit `geo_clients.aliases` in Admin is
misleading and does not affect Analyzer behavior.

### 3.4 Static Reports

- Seventeen `static-report-v2` snapshots are currently COMPLETED.
- Their core Visibility, Citation, and Sentiment change fields are null.
- Visibility and Citation previous series contain zero points.
- Current lists are capped at values such as 20, 50, and 100 rows.
- Snapshot size ranges from roughly 53 KB to 4 MB.

### 3.5 Workspace Scale

Dreamina currently has approximately 14,400 Prompt rows, 326,520 Tasks, 313,989 Results, 3,492,352 Citations,
and 777,471 Brand Mentions. Major fact tables are about 5.3 GB for `geo_results`, 3.3 GB for `geo_citations`,
403 MB for `geo_tasks`, and 317 MB for `geo_brand_mentions`.

Deleting every Prompt in one request would still create a long transaction. Cleanup must be bounded and serial.

## 4. F1 — Move Prompt to the Sidebar

### 4.1 Sidebar and Route Contract

- Remove the Prompt tab from Visibility.
- Add Prompt between Sentiment and Report in the Sidebar.
- Display `Prompt` in both locales.
- Link to the existing Prompt page route and preserve the `/prompts` redirect.
- Continue using the Insights Date, Topic, Platform, and Country filter context.

### 4.2 UI State and Compatibility

- On a Prompt route, only the Prompt Sidebar item is active; Visibility must not remain highlighted.
- Old URLs, bookmarks, and internal links redirect without a 404 or duplicate page.
- Removing the tab does not remove Prompt APIs, exports, management actions, or filter state.
- Compatible filter state is preserved while switching among Insights pages.
- Collapsed, expanded, mobile, and permission-filtered Sidebar modes follow existing item behavior.

### 4.3 F1 Non-goals

- Do not redesign the Prompt page body.
- Do not change Visibility or Query Refine content.
- Do not remove the legacy route compatibility layer.
- Do not move Prompt under Report or Settings.

## 5. F2 — Complete Topic, Product, and Prompt Drilldowns with Visibility, Citation, and Sentiment

### 5.1 Logical Prompt Semantics

Each `geo_client_prompts` physical row stores one Platform + Country + Language combination. The UI and repository
group related rows into one logical Prompt.

The logical key is:

```text
client_id + topic_id + normalized_prompt_text + normalized_product
+ normalized_intent + normalized_language
```

- `normalized_prompt_text = lower(trim(collapse_whitespace(text)))`
- `normalized_product = lower(trim(product or ""))`
- Active Intent uses the canonical Global Config name; historical Intent uses its trimmed stored value.
- Language uses the canonical Workspace configuration value.

Prompt drilldown must include every physical ID in the logical concept. Different Intent or Language values produce
different logical Prompts. Platform and Country variants remain separate database rows but one UI concept.

### 5.2 Dynamic API Capability Matrix

| Target | Visibility | Citation | Sentiment |
|---|---|---|---|
| Topic | Supported | Supported | Supported |
| Product | Supported | Add filter | Main aggregate supported; add filter to detail APIs |
| Prompt IDs | Supported | Add filter | Add filter |

Do not create a separate Prompt-only metrics API family.

Citation endpoints for share, ranking, categories, domain lists, and page lists accept optional `products`,
`prompt_id`, and `prompt_ids`. The unified Citation filter applies to current/previous periods, KPIs, series,
domain/page ranking, categories, and expandable details. Product semantics use `geo_client_prompts.product`.

The main Sentiment endpoint keeps its existing Product filter and adds `prompt_id/prompt_ids`. Theme results and all
expandable/detail APIs add Product and Prompt filters so summary, series, themes, and occurrences share one predicate.

Visibility continues using its existing Topic, Product, and Prompt-ID capabilities and existing formulas.

### 5.3 Entry Points, Stable Identity, and Page Composition

| Target | Route identity | Server-side resolution |
|---|---|---|
| Topic | `topic_id` | Verify ownership by JWT-derived client ID |
| Product | Canonical product plus current Topic scope | Filter `geo_client_prompts.product`; no drilldown for blank Product |
| Prompt | One representative physical `prompt_id` | Load it tenant-scoped, derive the logical key, then resolve every variant ID |

Do not put Prompt text or an arbitrary-length UUID list in the URL. Add tenant-scoped concept resolution so refresh,
back navigation, and copied links restore the same logical Prompt. A deleted representative row returns 404 with a
safe route back to the Prompt list; it must not broaden the query.

The drilldown page order is target header/back action, Visibility, Citation, and Sentiment. All sections share
`date_from/date_to`, interval, selected platforms, selected countries, and the mandatory target predicate.

Topic target replaces the global Topic selection. Product and Prompt targets are intersected with compatible global
Topic selection. Query-string client IDs are never authorization evidence.

### 5.4 Filter Propagation and Page State

- Topic, Product, and Prompt rows expose drilldown through their hover action icon only.
- Route state explicitly stores target type and stable identity.
- Header shows target type, canonical label, Topic/Product context, and back action.
- V/C/S sections own independent loading, error, and empty states.
- A failure in one domain does not hide successful domains.
- Filter changes trigger all three domains from the same immutable filter snapshot.
- A global filter cannot remove the mandatory target predicate.
- An empty intersection renders a target-scoped empty state.
- Cancel stale requests when the target or filters change.

### 5.5 Data-source Red Lines

- Reuse dynamic Dashboard metric functions, response models, charts, and lists only.
- Do not call static-report APIs, read `snapshot_json`, or copy Snapshot-builder SQL.
- Extend existing Citation/Sentiment filter contexts instead of defining parallel metrics.
- Current, previous, summary, series, ranking, and detail paths use one shared target predicate builder.

### 5.6 F2 Non-goals

- The mandatory complete drilldowns are Topic, Product, and Prompt only.
- Keep the existing Country group/list and apply F6 to its metric columns, but do not add a complete Country V/C/S drilldown.
- Do not duplicate the dynamic Dashboard component tree; a composition shell and adapters are allowed.
- Do not alter existing dynamic metric formulas, brand definitions, or previous-period semantics.

## 6. F3 — Prompt Intent Filter

### 6.1 Facet API and UI

Provide a tenant-scoped Intent facet endpoint that returns active Global Config values and tenant historical values
that are not active. The current database response is equivalent to:

```json
{
  "active": ["Solution Discovery", "Specifics Inquiry", "Competitive Evaluation"],
  "unconfigured": ["general"]
}
```

The UI renders Active Intents and, only when non-empty, Unconfigured Intents. Requests carry literal canonical values,
not Visibility/Citation/Sentiment categories. Remove every `|| "general"` write fallback from Prompt Editor.

### 6.2 Filter and Write Semantics

- Place Intent alongside existing Prompt filters.
- Selected Intents are OR-ed together and AND-ed with other filters.
- Clearing Intent means no Intent restriction and must not hide historical rows.
- Labels may be localized; API values remain canonical literals.
- Global Config changes appear on the next request without a frontend release.
- Create, duplicate, and CSV import accept active values only.
- Historical unconfigured values are readable and filterable but cannot be newly written.

### 6.3 Error and Empty States

- If Global Config lookup fails, do not fall back to hardcoded names; show retry state while keeping the Prompt list usable.
- Hide the Unconfigured group when the tenant has no such values.
- If future data contains null/blank Intent, display it in an Unconfigured bucket but reject new blank writes.
- If a selected Intent is disabled before submission, return a clear stale-value validation error.

## 7. F4 — Prompt CSV Batch Import

### 7.1 Reused Interaction Pattern and Limits

Reuse the Published Pages flow: template download, hidden CSV file input, UTF-8 BOM support, server Preview,
Create/Skip/Conflict/Invalid summary, row numbers and errors, Commit disabled on invalid/conflict, Commit-time re-preview,
and custom Dialogs instead of native alert/confirm/prompt.

Fixed limits are 10 MB raw CSV, 2,000 non-empty input rows, 100 physical variants from one row, and 20,000 physical
variants per Preview/Commit. Exceeding a limit rejects the entire file with actual and allowed counts; never truncate.

### 7.2 CSV Schema

```csv
Customer Name,Topic,Product,Prompt,AI Platforms,Countries,Language,Intent
```

Customer Name, Topic, Prompt, AI Platforms, Countries, Language, and Intent are required. Product is optional.
Customer Name must exactly match the canonical current Workspace name. Topic and Product resolve only within that
Workspace. Intent must be active. Platform/Country/Language must be permitted by both Global and Workspace config.

The file never contains Customer ID. JWT/current Workspace supplies immutable client ID, and the CSV Customer Name
provides a second human-readable match.

### 7.3 Multi-value and Expansion Rules

AI Platforms and Countries accept ASCII comma, semicolon, or pipe delimiters. Trim tokens, drop empty tokens,
case-insensitively resolve to canonical values, and deduplicate. Reject full-width Chinese commas/semicolons.
Comma-delimited values inside CSV cells must be quoted.

Language, Intent, Topic, Product, and Prompt are single-valued per row. Language stays single-valued to avoid an
ambiguous Country-to-Language pairing. Multiple rows may represent different languages.

One input row expands Platforms × Countries × one Language into physical variants. Multi-value and equivalent
multi-row inputs normalize to the same canonical variant set. Database columns remain scalar; variants are not stored
as arrays in one row.

### 7.4 Import Dialog and Allowed Values

The Dialog contains:

1. `Import CSV`: template download, file selection/drop, counts and quota impact, row Preview, and confirmation.
2. `Allowed Values`: searchable Topic, Product, Platform, Country, Language, and Intent values with copy and CSV download.

Product values show their parent Topic. Platforms are the intersection of active Global platforms and Workspace config.
Country/Language come from Workspace config, and Intent comes from active Global Config. UI, downloads, and Preview
share one tenant-scoped canonical resolver.

Endpoints:

```text
GET /api/prompts/import/template.csv
GET /api/prompts/import/allowed-values
GET /api/prompts/import/allowed-values.csv
```

Allowed Values CSV headers are:

```csv
Type,Value,Label,Parent Type,Parent Value,Notes
```

Import parses `Value`, never translated `Label`. Product rows set Topic as parent. Prevent cross-Workspace response caching.

### 7.5 Template Samples

The template is generated from authenticated Workspace context. It uses the canonical Customer Name, an existing
Topic/Product, allowed Platform/Country/Language values, and active Intent. It contains exactly two sample rows: one
single-value row and one pipe-delimited row. Prompt cells contain `[REPLACE WITH YOUR PROMPT]`, which Preview rejects
until changed. A Workspace with no Topic receives headers only plus guidance to create a Topic.

### 7.6 Preview Validation Order

Validate encoding/header/size/count, Customer Name, tenant Topic, Topic-owned Product, non-empty normalized Prompt,
active Intent, active and Workspace-allowed Platform, Workspace Country, Workspace Language, supported platform-country
combinations, expansion limits/quota, file duplicates, and database logical/exact variants, in that order.

Any unsupported combination makes the whole input row invalid. Do not partially accept a row.

### 7.7 Duplicate and Conflict Semantics

Exact variant key:

```text
client_id + topic_id + normalized_prompt_text + normalized_product
+ platform + country + language
```

- `create`: missing variant.
- `skip`: exact variant exists with compatible metadata.
- `conflict`: exact variant exists with different Intent/Product metadata.
- `invalid`: format, ownership, allowlist, quota, or file-duplicate failure.

Skip is idempotent. Conflict blocks the entire Commit and never overwrites. The same normalized Prompt in different
Topics is allowed with a warning. Commit writes only `create` variants.

### 7.8 Commit, Audit, and Undo

Commit reparses and re-previews the original file, acquires a tenant advisory transaction lock, rechecks quota and
existing variants, bulk-inserts create variants, verifies inserted count, writes the batch record, and commits once.
Use a true bulk operation, not per-row acquire/commit loops. Any failure rolls back Prompts and batch metadata.

Audit stores raw and normalized SHA-256 hashes, source filename, client/user IDs, row and variant counts, action counts,
created Prompt IDs, lifecycle status, and timestamps. Do not store raw Prompt text in generic audit metadata.

Undo deletes only IDs created by that batch through `PromptCascadeDeletionService`, warns about cascading generated
facts, is idempotent, and marks the batch reverted.

### 7.9 Import API and Persistence Contract

```text
POST /api/prompts/import/preview              multipart file
POST /api/prompts/import/commit               multipart file + expected_manifest_sha256
POST /api/prompts/import/{batch_id}/undo      JSON confirmation
```

Preview returns hashes, row/variant counts, quota before/after, action totals, and normalized row details. It writes no
business tables. Commit returns 409 `preview_stale` with a new Preview if hash, config, quota, or existing data changed.

Migration `geo_prompt_import_batches` contains UUID ID, tenant and actor IDs, source filename, both hashes, input and
expanded counts, action counts, UUID array of created Prompt IDs, `COMMITTED/REVERTING/REVERTED` status, and created/
reverted timestamps and actor. Undo transitions under a tenant lock. A failed Undo leaves `COMMITTED` and is retryable.
A failed Commit creates no fake Undo-capable batch row.

## 8. F5 — Fully Dynamic Fixed-Date Reports and Equal-length Previous-period Comparison

> Final architecture decision (2026-07-15): this paragraph supersedes every later reference to full metric materialization in `snapshot_json`, `geo_static_report_lists`, frozen-list caches, or online Snapshot sorting. A report persists only tenant identity, a fixed date range, filter-option metadata, status, and audit fields. After report-level authorization, the page calls the existing dynamic Visibility, Citation, and Sentiment APIs with the report's authorized `client_id` and fixed `window_start/window_end`. Topic/platform filtering, comparison metrics, metric definitions, global sorting, and pagination reuse the dynamic Dashboard implementation; no second calculation path is maintained. Legacy reports retain their prior read path. Migration 127 safely deletes the seven v5 test reports and retires `geo_static_report_lists`.

### 8.1 Previous-period Materialization

```text
current_start = data_window_start
current_end = data_window_end
period_days = current_end - current_start + 1
previous_end = current_start - 1 day
previous_start = previous_end - period_days + 1 day
```

Snapshot generation materializes current summaries/series/rankings, previous-period lookup data, and delta/change fields.

Visibility includes visibility score/rank change, SOV percentage/rank change, average position/rank change,
previous time series, and previous average-position series. Citation includes own-domain share/rank change,
domain/page change percentages, and previous series. Sentiment includes positive-percentage change, previous summary
series, and theme occurrence change.

Reuse the formulas and null/zero semantics of the corresponding dynamic Dashboard fields, but compute and freeze them
inside Snapshot generation rather than calling dynamic endpoints from the report page.

### 8.2 Snapshot Immutability

Frozen data means that the report stores the data window, filters, metrics, and rows as they existed at generation time.
Later Analyzer data, Alias edits, or Dashboard changes must not change that report ID.

The Snapshot is the only source for an online report. Topic/Platform filtering must not query current dynamic data.
When a dimension was not materialized, disable the filter or explain that it is unavailable; never silently fall back.

### 8.3 Comparison Display and Edge Cases

- Although the business request informally uses “同比/环比”, the formal contract is previous-period, not prior-year YoY.
- Support 1 vs previous 1, 7 vs previous 7, and 30 vs previous 30 days.
- Preserve each dynamic field's percentage-point versus relative-percent definition.
- Rank and Position colors/arrows communicate improvement versus deterioration, not generic positive/negative numbers.
- A zero or missing previous denominator follows dynamic null semantics and displays `—`, never Infinity, NaN, or fake 0%.
- Missing previous data does not fail materialization; record a completeness warning.
- Do not mutate the existing seventeen snapshots. New or explicitly regenerated snapshots use a bumped version.
- The frontend opens old versions safely with null comparison fields.

## 9. F6 — Global Sorting for Metric Columns in Every List

Online report sorting is identical to dynamic Dashboard sorting: the database sorts the complete result set for the fixed report dates and active filters before pagination. No frozen list-row/blob is read or maintained. Sequence, name, Topic, Product, Prompt, and brand-ranking-matrix columns are dimensions and must not expose sorting.

### 9.1 Shared Interaction Contract

Only Metric column headers display sorting controls. Dimension/string columns such as Topic, Product, Prompt, Brand,
Domain, Page, Theme, Platform, and Country do not sort.

Inactive headers show both arrows. Active descending highlights down; active ascending highlights up. Clicking the same
column toggles direction. New numeric metrics normally default descending; rank/position default ascending. Null is
always last. Equal metric values use a stable text/ID tie-breaker.

### 9.2 Mandatory Dynamic and Drilldown Inventory

| Page/domain | Required sortable lists | Metric examples |
|---|---|---|
| Visibility Sidebar | Brand Visibility, SOV, Average Position, Topic ranking, Product ranking, expanded tables | score, share, mentions, total queries, average position, rank, change |
| Citation Sidebar | Domain ranking, Page ranking, Category breakdown, Published Page tracking, expanded tables | citations, share, change, rank, trigger count |
| Sentiment Sidebar | Theme lists and metric-bearing aggregate/expanded tables | occurrence, occurrence change, positive/negative count, sentiment percentage |
| Prompt Sidebar | Topic groups, Product groups, Prompt rows, retained Country groups | Visibility metrics plus Citation/Sentiment metrics added in this iteration |
| Topic drilldown | Every V/C/S metric list | Same as the corresponding dynamic Dashboard |
| Product drilldown | Every V/C/S metric list | Same as the corresponding dynamic Dashboard |
| Prompt drilldown | Every V/C/S metric list | Same as the corresponding dynamic Dashboard |

Pure text details, Prompt/Response content lists without metrics, action columns, dates, and dimensions do not sort.
Any omitted aggregate list that contains a numeric Metric is still in scope.

For paginated/limited lists, the server sorts the full tenant-scoped filtered result before `LIMIT/OFFSET`. Browser-only
sorting is allowed only when the API explicitly returns the complete set and `items.length == total`. APIs accept
whitelisted `sort_by` and `sort_order=asc|desc`; request values never become raw SQL identifiers. Filter or sort changes
reset pagination to page one.

### 9.3 Online Snapshot Sorting

Online sorting operates on complete frozen lists materialized for the report ID, not live metrics and not the 20/50
rows currently loaded in the browser. Keep default first-page rows in `snapshot_json` for fast initial and offline
rendering, and store all canonical rows for the 17 registered list types in `geo_static_report_lists`. Split large
lists into contiguous JSONB shards bounded by 25,000 rows and 16 MiB; never create one database row per business item.
For Citation Page/Domain lists whose expanded object tree exceeds 16 MiB, derive six compact integer position indexes
from the same canonical rows and persist them in the same table. These indexes do not duplicate full row payloads and
require no additional schema.

Schema contract:

| Column | Contract |
|---|---|
| report_id | UUID, not null |
| client_id | UUID, not null |
| list_type | Whitelisted text identifier |
| list_version | Reader/writer contract version |
| row_count | Integrity count and response total |
| rows_payload | Complete canonical JSON array with dimensions, metrics, row key, and default position |
| materialized_at | Snapshot generation timestamp |

Use primary key `(report_id, client_id,list_type)` and a composite cascading foreign key to the report. Require a JSON
array and `row_count = jsonb_array_length(rows_payload)`. Every read remains scoped by report ID and client ID; do not
create JSON metric expression indexes. Canonical shards use `list_type::000001`; derived indexes use
`citation.page|domain@sort.{metric}.{order}` with optional contiguous shard suffixes. Validate version, continuity,
unique positions, and capacity. The server owns the list-type-to-sort-key whitelist, default direction, and stable tie-breakers.

```text
GET /api/static-reports/{report_id}/lists/{list_type}
    ?sort_by={metric_key}&sort_order=asc|desc&limit=20&offset=0
```

Default limit is 20 and maximum is 100. Return items, total, pagination, and effective sort. The hot path uses a bounded
128 MiB per-instance LRU of compact per-row JSON plus `array('I')` order indexes. A cold instance reads the persisted
position index and extracts only the requested rows from the canonical shards. Replace `snapshot_json`, all canonical
shards, and optional derived indexes in the same report materialization transaction, and reject incomplete, duplicate,
or version-mismatched data. Every Snapshot Visibility, Citation, Sentiment,
Topic, Product, and Prompt metric list declares allowed keys, default order, stable tie-breaker, and total.

Do not refill lists from live fact tables. Legacy snapshots without list blobs remain readable in default order without
sorting controls and instruct the user to explicitly Regenerate for complete comparison and sorting.

### 9.3.1 Generation Performance and Concurrency Budget

- Keep Cloud SQL global `work_mem` at 16 MB. Apply transaction-local 32 MB only to static-report read transactions,
  clamped to 16–64 MB.
- Keep pool max at 8. A cross-instance advisory-lock guard uses one connection and the Snapshot uses one coordinator
  plus at most one worker, for three total and at least five reserved for ordinary API traffic. The worker setting has
  a hard maximum of two and may use the second worker only with a larger pool that still preserves the reserve.
- Serialize generation with a per-instance semaphore of one and a PostgreSQL transaction advisory lock across
  instances. A capacity loser releases its fenced lease and returns retryable PENDING instead of waiting on a pool slot.
- Do not introduce Cloud Tasks at the current low and dispersed generation frequency. A future scheduler may hash
  client IDs into staggered windows, but it must still obey the same global lock.
- Aggregate Citation and Sentiment current/previous periods in two smaller windows. Do not force a wider combined scan;
  Dreamina measurements showed materially worse grouping and temporary-file pressure.
- Derive `snapshot_json` and all blobs from one canonical metric-row pipeline. `snapshot_json` retains charts,
  comparisons, default pages, and offline HTML; blobs only retain complete sortable lists.
- Cap each list at 25,000 rows, all lists at 100,000 rows, each uncompressed JSON blob at 16 MiB, and all blobs at
  48 MiB. Enforce limits during construction, before persistence, and before a stored payload is transferred/decoded.
- High-cardinality Visibility, Citation, Sentiment, and Prompt/Topic aggregates use server-side cursors and may retain
  at most 50,000 grouped rows or 16 MiB of cumulative serialized data. Cursors use `prefetch=1`; each SQL query reads
  one guard row and aborts materialization on either overflow instead of allocating an unbounded application result
  first. Prompt-by-day, Topic-by-day, and Sentiment examples use the same byte-bounded cursor while preserving their
  existing 700/700/50-row display truncation.
- Serialize and enforce a 32 MiB ceiling for the complete `snapshot_json` before opening the completion transaction.
  An oversized snapshot fails closed without writing either the snapshot or any list blob.
- Each SaaS instance may decode, filter, and sort at most two frozen list blobs concurrently. The budget covers the
  point read, JSONB decode, full-list filtering, stable sort, and pagination slice.
- Every embedded default list is exactly the API's first 20-row page, so offset 20 never overlaps fallback rows.
- Determine missing previous windows from fact denominators such as total queries/citations/count, not from a synthetic
  zero percentage. A real window with facts and a 0% metric remains a valid comparison baseline.
- Persist only stable public failure codes; raw database and SQL diagnostics remain in service logs.

### 9.4 Offline HTML

- Render no sorting buttons.
- Do not require API or JavaScript sorting.
- Use export-time default order and exported rows.
- Remain a single file that opens without network access.

## 10. F7 — Align Admin Brand Alias Data Source

### 10.1 Source of Truth

The only runtime Alias source is `geo_client_brands.aliases`. SaaS and Analyzer remain unchanged.

### 10.2 Minimal Admin API Adapter

```text
GET /api/clients/{client_id}/brands
PUT /api/clients/{client_id}/brands/{brand_id}/aliases
```

Reuse `geo_common.services.BrandRepository`. GET returns active Own and Shadow brands with `id`, `brand_name`,
`aliases`, and `is_shadow`. PUT accepts only aliases and scopes every lookup by both client ID and brand ID.
Do not proxy SaaS HTTP or duplicate brand SQL.

Trim aliases, remove empty values, and deduplicate case-insensitively while preserving first-entry order. An empty array
means clear aliases. Return 404 for a brand outside the client so the endpoint does not reveal another tenant's data.

### 10.3 Admin UI

- Remove legacy aliases from Client Info form and update payload.
- Render each brand and aliases using the SaaS Brands interaction pattern.
- Save by brand ID.
- Do not change quotas, Agent limits, cron, or other Client Info behavior.
- Keep the legacy column but never edit it from Admin UI/API.
- Each brand has independent loading/success/error state.
- Distinguish Own and Shadow brands.
- Refresh aliases from `geo_client_brands`, never the legacy Client payload.

### 10.4 Non-goals

- No legacy-column migration or deletion.
- No dual-write.
- No SaaS UI or Analyzer changes.
- No brand-schema changes.

## 11. F8 — Guided Workspace Cleanup and Protected Deletion

### 11.1 Deletion Readiness API

```text
GET /api/clients/{client_id}/deletion-readiness
```

Return Workspace identity, collector/analyzer/LLM-discovery schedule states, Topic count, logical and physical Prompt
counts, Task/Result/Citation/Brand Mention/Product Mention/Sentiment counts, Static Report/Agent Task/Published URL
counts, recommended next action, blockers, and `can_finalize`.

`can_finalize=true` requires all three schedules stopped, zero Prompts and Topics, and zero facts that
`PromptCascadeDeletionService` should have removed. If Prompts/Topics are zero but large orphan facts remain, return an
internal-repair blocker rather than asking the user to delete internal tables manually. Readiness is read-only.

### 11.2 Admin Dialog and Guided Path

Delete Workspace opens a custom readiness Dialog:

1. Show related counts and risk.
2. If schedules run, provide Stop All Scheduling using the existing Admin client scheduler update, then refresh.
3. If Prompts remain, provide Open Prompt Management.
4. After Prompts are zero, if Topics remain, provide Open Topic Settings.
5. Only when ready, reveal final deletion.

The Prompt link uses configured SaaS base URL and Workspace context; never hardcode localhost, production host, or a
client ID. Returning to Admin triggers a new readiness request. Users never delete Tasks/Results/Citations manually.

### 11.3 Bounded Prompt Cleanup

Continue using the existing batch-delete route and `PromptCascadeDeletionService`. Default batch size is 25 physical
Prompt IDs and hard maximum is 100; excess returns 422 without truncation. Prompt Management gains an explicit
Workspace Cleanup mode that serially submits batches after confirmation and shows deleted, remaining, and progress.
Normal selected-row deletion remains unchanged.

Stop on failure and allow resume after refreshing readiness. Never send batches in parallel. Each batch is one
all-or-nothing transaction.

Deliver concurrent-index migrations for `(client_id, client_prompt_id)` on `geo_tasks`, `geo_results`, `geo_citations`,
`geo_brand_mentions`, `geo_product_mentions`, `geo_sentiment_results`, and `geo_sentiment_themes`. The CTO executes
them manually; the application never runs index DDL at startup.

### 11.4 Final Workspace Deletion

The user types the exact Workspace name. Only then is Delete enabled. Disable it and show loading during the request;
closing/reopening must not submit a duplicate.

The server reruns readiness, returns structured 409 blockers when Prompt/Topic cleanup is incomplete, acquires a global
Workspace-deletion single-flight lock, stops/removes scheduler jobs, and then deletes `geo_clients`. A concurrent
deletion fails fast with 409/423 rather than waiting on the pool. Acquire and statement timeouts return understandable
errors instead of waiting indefinitely.

Final CASCADE is only for low-volume Workspace-owned residual data such as permissions, static reports, Published URLs,
and Agent metadata. Large or orphaned fact data blocks final deletion.

### 11.5 Non-goals

- No persistent async Workspace deletion job/worker.
- No manual per-table deletion of Task/Result/Citation/Mention/Sentiment.
- No connection-pool increase as a substitute for bounded work.
- No concurrent deletions consuming all Admin connections.
- No application-startup DDL.

## 12. Multi-tenant and Security Requirements

- Derive client ID from authenticated route context; CSV content never overrides it.
- Every Prompt, Brand, Report, and Readiness query includes tenant scope.
- Tenant-filter Prompt ID lists before query or deletion.
- Resolve Topic/Product only inside the current tenant.
- Repeat tenant validation in Preview and Commit.
- Audit import, Undo, Brand update, and Workspace deletion.
- Store hashes, counts, and IDs rather than raw Prompt content in generic audit metadata.

## 13. i18n and UI Requirements

- SaaS copy belongs in the correct `zh-CN/en-US` namespace JSON files.
- Sidebar label `Prompt` is identical in both languages.
- Shared Save/Cancel/Delete/Loading terms use `common`.
- Keep Admin's existing localization pattern but use custom Dialog/AlertDialog.
- CSV headers and canonical Values remain English and locale-independent.
- Do not use native `window.alert`, `window.confirm`, `window.prompt`, or native `<select>`.

## 14. API Compatibility

- New filter/sort parameters are optional and preserve current default responses/orders when absent.
- Existing `/prompts/batch` continues serving the Brainstorm save flow.
- CSV uses separate template, facet, preview, commit, and Undo endpoints.
- Keep `/prompts` redirect.
- Keep the legacy Admin ClientOut aliases response field read-only for compatibility, but remove aliases from
  ClientUpdate and from every Admin write path.

## 15. Tests and Acceptance

### 15.1 F1

- Prompt tab is gone from Visibility; Sidebar order, active state, mobile/collapsed state, and both locales are correct.
- Old `/prompts`, refresh, back, and bookmarks work.
- Compatible Insights filter state survives navigation.

### 15.2 F2

- Topic, Product, and Prompt each render all V/C/S sections.
- Current/previous and all detail lists share the target filter.
- Product never leaks another Product; Prompt uses every variant ID.
- Hover behavior, refreshable links, independent failures, scoped empty state, and stale-request cancellation work.
- Two-client manual/integration checks show zero cross-tenant data.

### 15.3 F3

- Active and Unconfigured values are database-driven.
- `general` is filterable but cannot be newly written.
- Multi-select is OR internally and AND with other filters; clearing removes the restriction.
- No Prompt Editor fallback remains.
- Config failure never uses a hardcoded enum; config changes appear without frontend release.

### 15.4 F4

- Encoding, bilingual Prompt text, English headers, both UI tabs, Allowed Values ownership, Product parent, and locale-independent Value work.
- All size/row/expansion limits reject the whole input.
- Delimiters, trim, canonicalization, deduplication, full-width rejection, and CSV quoting work.
- Multi-value and equivalent multi-row input create identical variants; different Language rows remain distinct.
- Tenant mismatch, allowlist, quota, duplicates, skip/conflict, stale Preview, transaction rollback, and concurrent Commit are covered.
- Undo deletes only batch-created data and is idempotent.

### 15.5 F5

- 1/7/30-day boundaries are correct and generated values match the dynamic Dashboard at generation time.
- Missing/zero previous data produces null/`—`, never Infinity/NaN.
- Rank/Position direction is correct.
- Legacy snapshots remain readable; regenerated/new versions contain comparisons.

### 15.6 F6

- Every list in Section 9.2 is tested for ascending, descending, full-result pagination, null-last, and stable ties.
- Only Metric headers sort.
- Invalid sort keys fail validation without entering dynamic SQL.
- Online Snapshot sorting uses complete report rows, enforces tenant scope, and does not call live metrics.
- Offline HTML has no controls and works without a network.

### 15.7 F7

- Admin and SaaS read identical aliases; Analyzer reads the update on its next load.
- Admin never writes `geo_clients.aliases`.
- Cross-tenant brand IDs fail without update or disclosure.
- Trim, deduplication, clear, refresh, Own/Shadow, and independent-save states work without regressing Client Info.

### 15.8 F8

- Readiness counts match the database.
- Stop All Scheduling disables all three schedules and refreshes readiness.
- Prompt cleanup is serial, bounded, resumable, and respects 25 default/100 hard max.
- Final deletion is blocked until ready; typed-name, disabled/loading, single-flight, and timeouts work.
- Ordinary Admin create/list requests can still acquire connections while deletion work is in progress.

## 16. Scope Traceability and Completion Gate

| Feature | Frontend | API/service | Persistence/query | Required verification |
|---|---|---|---|---|
| F1 | Sidebar, old-tab removal, active/redirect/filter state | No new metric API | No schema change | Routing and bilingual E2E |
| F2 | Three hover entries, shared shell, independent V/C/S state | Citation Product/Prompt filters; Sentiment Prompt/detail filters | Target predicate in current/previous/summary/list/detail | Target × domain integration and tenant isolation |
| F3 | Intent multi-filter, grouped facets, required Editor value | Tenant facets and write validation | Active Global Config plus tenant distinct history | Config drift, history, OR/AND, no hardcode |
| F4 | Template, Allowed Values, Preview, Result, Undo | Import endpoints and canonical resolver | Transaction, lock, audit migration, cascade Undo | Limits, duplicates, quota, rollback, concurrency |
| F5 | Static comparison display and legacy compatibility | Snapshot materialization/sections | Previous-window queries, version, frozen values | Boundaries, dynamic parity, missing baseline |
| F6 | Metric-only headers and page reset | Whitelisted full sort and report-list API | Full filtered ORDER BY and report-list migration | Every list, directions, pagination, null/tie, offline exclusion |
| F7 | Admin per-brand Alias editor | Thin BrandRepository endpoints | Only `geo_client_brands.aliases` | SaaS/Admin parity, Analyzer read, cross-tenant denial |
| F8 | Readiness, schedule stop, cleanup links, typed confirmation | Readiness, bounded cascade, single-flight final delete | Index migration, cascade service, guarded final cascade | Dreamina-scale behavior, pool availability, resume/idempotency |

Global Definition of Done:

- F1–F8 unit, API integration, frontend component, and critical E2E tests pass.
- Every new/extended data endpoint is tested with two client IDs.
- Both locales are complete; CSV schema does not vary by locale.
- Migrations contain forward SQL, comments, and manual verification queries and are not auto-executed.
- Existing Prompt routes, Brainstorm batch flow, legacy snapshots, and unrelated Admin Client editing do not regress.
- No hardcoded Intent, live Snapshot fallback, legacy Alias write, current-page-only sort, unfinished placeholder, disabled stub,
  mock-only implementation, or permanently off feature flag remains.

## 17. Delivery Order

1. F3 Intent contracts, facet service, and Prompt write validation for reuse by F4.
2. F1 Sidebar and route compatibility without removing Prompt capabilities.
3. F2 Citation/Sentiment filters, shared drilldown context, and three targets.
4. F6 shared sorting contract, then dynamic Sidebar and F2 drilldown lists.
5. F4 CSV Template, Allowed Values, Preview, Commit, audit, and Undo.
6. F5 Snapshot previous-period/version/UI, then F6 full online Snapshot list sorting.
7. F7 minimal Admin Brand Alias adapter with unchanged SaaS/Analyzer.
8. F8 index migration, readiness, schedule stop, Prompt Cleanup mode, Topic guidance, and final deletion guard.

Each stage must pass the relevant tenant-isolation and regression checks before merge. Database changes are migration
files executed manually by the CTO. Staged delivery does not move any later feature to a future iteration; the release
gate remains the complete Section 16 checklist.
