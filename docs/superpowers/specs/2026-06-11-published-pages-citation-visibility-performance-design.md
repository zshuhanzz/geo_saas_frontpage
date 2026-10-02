# Published Pages and Citation/Visibility Performance Design

Date: 2026-06-11
Status: Draft for user review
Scope: SaaS Citation published page management, Published URL tracking, Citation performance instrumentation, and Visibility endpoint decomposition

## Goal

Add a customer-facing Published Pages capability to the SaaS Citation module and improve Citation/Visibility dashboard performance without changing metric semantics.

This design covers the complete implementation scope for the current iteration:

- Add a SaaS UI `Published Pages / 发布页面管理` tab under the Citation page.
- Add first-class Published URL asset management with create, edit, disable, delete, list, search, filters, CSV template download, CSV preview, CSV validation, and confirmed CSV import.
- Add `Published URL Tracking / 已发布页面追踪` to the existing Citation Monitor page.
- Add backend data model and APIs for Published URL assets and their Citation tracking metrics.
- Add Citation endpoint internal timing logs for diagnosis, while keeping the existing Citation endpoint response shape and behavior unchanged in this iteration.
- Split the Visibility API so the first screen loads core charts and rankings independently from the heavy topic/product ranking matrix.
- Change the Visibility ranking matrix drill-down semantics so prompt rows aggregate by Client Prompt text, not by `geo_client_prompts.id`.
- Preserve all existing dashboard metric definitions, chart semantics, ranking semantics, filters, and full ranking dialogs.

The iteration must not execute database DDL automatically. All database schema changes are delivered as migration SQL for manual execution.

## Product Decisions

### Citation Page Navigation

The SaaS Citation page becomes a two-tab page:

- `Citation Monitor / 引用监控`: the existing Citation dashboard.
- `Published Pages / 发布页面管理`: the new Published URL asset management area.

`Focus URL` is an internal discussion term only. User-facing English should use `Published Pages` for the management tab and `Published URL Tracking` for the Citation Monitor tracking section.

### Published Pages Role

Published Pages are customer-facing tracked assets. They represent URLs that AnswerX or the customer has published and wants to track in AI citations, including customer official websites, Reddit, Medium, owned media, social media, agency-published pages, and other channels.

The system owns the structured asset list. CSV import is supported in this iteration. Feishu Sheets live integration and Agent-driven asset maintenance are not part of this iteration.

### Citation Monitor Integration

The existing Citation Monitor page adds a new section below `Top Cited Pages / 被引用最多的页面`:

- Chinese section name: `已发布页面追踪`
- English section name: `Published URL Tracking`

This section displays the Citation performance of the managed Published URLs under the same dashboard filters currently applied to Citation Monitor:

- date range
- interval
- topics
- platforms
- countries
- prompt intent filters

The tracking section is read-only. Asset creation and editing happen in the `Published Pages / 发布页面管理` tab.

## Published Pages UI Design

### Visual Style

The Published Pages tab follows the current Citation page design language:

- dark SaaS dashboard background
- compact toolbar
- shadcn/Radix Select-style filters
- table-first operational layout
- no native browser prompts, confirms, alerts, or native selects
- bilingual i18n using the existing `react-i18next` namespace discipline

The toolbar layout should visually align with Citation Monitor controls rather than introducing a separate page style.

### Toolbar

The Published Pages toolbar includes:

- Search input.
- Publish status filter.
- Channel filter.
- Topics filter.
- `Download CSV Template` action.
- `Import CSV` action.
- `Add Published Page` action.

Search matches:

- published URL
- page title
- channel
- topic names

The publish status filter is retained because tracking and lifecycle behavior depend on `publish_status`. The supported publication states are `draft`, `scheduled`, `published`, and `offline`. Review state is shown in the table and form as `review_status`, but it is not the primary lifecycle filter for Citation Monitor tracking.

The channel filter is not a hardcoded enum. It is populated from distinct `channel` values within the current client’s Published Pages data.

`channel` is separate from Citation Category. Channel describes where AnswerX or the customer published the page, such as `Official Website`, `Reddit`, `Medium`, or a customer-defined value. Citation Category describes how the citation source is classified in the Citation dashboard, such as `Owned Media`, `Social Media`, `Agency`, or `Earned Media`.

The Topics filter is based on the current workspace’s configured topics. CSV import accepts topic names and maps them to existing topics using normalized matching:

- trim leading and trailing whitespace
- collapse repeated internal whitespace
- compare case-insensitively

Unmatched topic names are reported as validation errors in CSV preview and are not auto-created.

### Main Table

The Published Pages table includes:

- Publish date
- Page title
- Published URL
- Topics
- Channel
- Review status
- Publish status
- Normalized URL preview
- Actions

Citation metrics are not editable Published Pages management fields. Citation count, citation share, citation rank, period-over-period change, last cited time, and citation category appear in Citation Monitor’s Published URL Tracking table. Citation category is derived from matched `geo_citations.domain_category` records and is never entered manually by the user.

Actions:

- View details
- Edit
- Disable
- Delete

Disable sets the asset inactive while keeping it recoverable and auditable. Delete is implemented as a soft delete or inactive state in this iteration so historical tracking data is not orphaned.

The table should support pagination. The default page size is 20. The table must not eagerly render all rows for clients with large Published URL inventories.

### Required and Optional Fields

Required for manual creation and confirmed CSV import:

- `title`
- `published_url`
- `published_at`
- `channel`
- `publish_status`

Required for Citation metric matching:

- `published_url`

Optional fields:

- `topics`
- `review_status`
- `draft_doc_url`
- `owner_name`
- `notes`

Although only URL is strictly required for metric matching, title, publish date, channel, and publish status are required for SaaS usability and operational clarity.

The system does not expose a manual Canonical URL field. The backend derives a normalized URL from `published_url` and uses that value as the deterministic matching key against normalized citation source URLs. This avoids asking users to understand canonicalization details.

The system does not expose a manual Citation Category field. Citation category is derived from the Analyzer-produced `geo_citations.domain_category` values for matched citation records.

There is no separate generic `status` field. Workflow state is represented by the two explicit fields `review_status` and `publish_status`.

### Detail Drawer

`View details` opens a side drawer.

The drawer includes:

- Basic information:
  - title
  - published URL
  - normalized URL
  - channel
  - review status
  - publish status
  - publish date
  - owner name
  - notes
- Associated topics.
- Draft document URL when present.
- Citation metric summary:
  - citation count
  - citation share
  - citation rank
  - period-over-period change
  - last cited time
- Citation trend for 7, 14, and 30 days.
- AI platform breakdown.
- Country breakdown.
- Prompts that triggered citations.
- AI responses where the URL appeared.
- Citation source context.

The normalized URL field explains how the system matches the URL against citation data. It is the canonicalized form produced by URL normalization and is used for exact matching against normalized citation source URLs.

## CSV Import Design

### Template Download

The Published Pages toolbar includes `Download CSV Template`.

The template uses English headers. It includes the supported column names and one example row that users can replace.

Template headers:

```csv
title,published_url,published_at,topics,channel,review_status,publish_status,draft_doc_url,owner_name,notes
```

Field rules:

- `title`: required page title.
- `published_url`: required published page URL.
- `published_at`: required date in `YYYY-MM-DD`.
- `topics`: optional topic names separated by semicolons.
- `channel`: required client-defined channel, such as `Official Website`, `Reddit`, `Medium`, `AAA`, or another uploaded value.
- `review_status`: optional review state. Allowed values are `not_submitted`, `in_review`, `approved`, `changes_requested`, and `rejected`. If omitted, it defaults to `approved`.
- `publish_status`: required publication workflow state. Allowed values are `draft`, `scheduled`, `published`, and `offline`.
- `draft_doc_url`: optional Feishu draft or review document link.
- `owner_name`: optional owner.
- `notes`: optional notes.

The CSV template includes examples and inline guidance that make the finite enum values clear before upload. Preview validation rejects unsupported enum values with row-level errors.

### Import Limit

Single CSV import is capped at 100 rows.

CSV files must be UTF-8 encoded and no larger than 1 MB. The backend rejects files that exceed the row or size limit before validation.

This cap keeps browser parsing, backend preview validation, URL normalization, topic matching, and database upsert predictable. Larger customer migrations are handled by splitting data into multiple CSV files under the same template protocol.

### Import Flow

CSV import is a two-step flow:

1. Upload and preview.
2. Confirm and commit.

Preview behavior:

- The backend parses CSV content.
- The backend validates required fields, URL format, date format, duplicate rows, topic name matches, and import row count.
- The backend normalizes URLs.
- The backend determines whether each row will create a new Published URL or update an existing Published URL.
- The UI displays:
  - number of new rows
  - number of updated rows
  - number of invalid rows
  - row-level validation messages

Commit behavior:

- The user explicitly confirms the preview.
- The backend performs upsert by `(client_id, normalized_url)`.
- Rows with validation errors are not committed.
- The response returns final inserted, updated, and skipped counts.

## Published Pages Backend Design

### Data Model

Create a new table:

```text
geo_published_urls
```

Recommended columns:

- `id uuid primary key`
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

Create a topic relation table:

```text
geo_published_url_topics
```

Recommended columns:

- `published_url_id uuid not null`
- `client_id uuid not null`
- `topic_id uuid not null`
- `created_at timestamptz not null default now()`

### Constraints and Indexes

Indexes and constraints:

- Unique index on `(client_id, normalized_url)`.
- Index on `(client_id, published_at)`.
- Index on `(client_id, channel)`.
- Index on `(client_id, publish_status)`.
- Index on `(client_id, is_active, publish_status, published_at)`.
- Index on `(client_id, is_active)`.
- Index on `geo_published_url_topics(client_id, topic_id, published_url_id)`.
- Index on `geo_published_url_topics(published_url_id)`.

These indexes are required so Published URL listing, filtering, and tracking queries do not create a new slow dashboard path.

### URL Normalization

Published URL normalization and citation source URL normalization use the same logic.

Normalization rules:

- trim whitespace
- lowercase scheme and host
- remove default ports
- remove URL fragment
- remove trailing slash from path except root
- remove common tracking query parameters such as `utm_*`, `fbclid`, `gclid`, `yclid`, `msclkid`
- sort remaining query parameters deterministically
- preserve meaningful path and query parameters

The initial match mode is exact normalized URL match.

Prefix, directory-level, and domain-level match modes are not included in this iteration because they can over-count unrelated pages.

### APIs

Published URL management APIs:

- `GET /api/published-urls`
- `POST /api/published-urls`
- `PATCH /api/published-urls/{id}`
- `DELETE /api/published-urls/{id}`
- `GET /api/published-urls/channels`
- `GET /api/published-urls/csv-template`
- `POST /api/published-urls/import/preview`
- `POST /api/published-urls/import/commit`

Tracking API:

- `GET /api/insights/published-url-tracking`

All APIs derive authorization from the current authenticated SaaS user and enforce `client_id` isolation. All queries include tenant-scoped predicates equivalent to:

```sql
WHERE client_id = :client_id
```

### Published URL Tracking Metrics

The tracking API computes metrics from `geo_citations` joined to Published URLs by normalized source URL.

It inherits Citation Monitor filters:

- date range
- interval
- topics
- platforms
- countries
- prompt intent filters

Metrics:

- citation count
- citation share
- citation rank among cited pages under the same filters
- period-over-period citation count change
- period-over-period citation share change
- citation category
- last cited time
- platform breakdown
- country breakdown
- triggering Client Prompts
- response contexts for detail drawer

The tracking API must paginate table rows. Default page size is 20.

Metric semantics must align with `Top Cited Pages / 被引用最多的页面`. Published URL tracking may include additional fields, but it must not omit metrics that the Top Cited Pages table already provides.

## Citation Performance Instrumentation

### Scope

This iteration does not change the existing `/api/insights/citations`, `/api/insights/cited-domains`, or `/api/insights/cited-pages` response shape or dashboard behavior.

The purpose is to add internal timing logs so slow requests can be attributed to specific phases and SQL blocks.

### Timing Logs

Each Citation endpoint logs structured timing for:

- request parameters summary
- filter construction
- each SQL query
- aggregation and response shaping
- serialization preparation
- total endpoint time
- response row counts

Logs include:

- `client_id`
- date range
- topic count
- platform count
- country count
- prompt intent filter count
- endpoint name
- phase name
- duration in milliseconds
- row count when applicable

Logs must not include sensitive secrets or raw long response text.

### SQL Optimization Evaluation

After timing logs exist, the slowest SQL blocks are evaluated with `EXPLAIN` and existing index coverage.

Optimization should address root causes before introducing cache. Short-lived caching may be considered only after SQL shape and indexes have been reviewed.

Short-lived caching is not implemented in this iteration. The current iteration uses instrumentation to identify the real SQL or response-shaping bottleneck before any cache layer is introduced.

## Visibility Performance Design

## Current Visibility Behavior

The current `/api/insights/visibility` endpoint returns all of the following in one response:

- visibility score summary
- visibility score trend
- previous period visibility trend
- average position trend
- previous period average position trend
- competitive series
- SOV ranking
- visibility ranking
- position ranking
- topic SOV ranking matrix
- product SOV ranking matrix
- filters metadata

The heavy part is the topic/product ranking matrix. It is rendered as the bottom `可见度排名（按话题 / 按产品）` table. It includes group rows and prompt drill-down rows.

Current backend grouping for matrix prompt rows uses `geo_client_prompts.id`. For Dreamina, one unique prompt text can exist as many `geo_client_prompts` rows because prompts are expanded across countries and platforms. Example:

- AI Video: 30 distinct prompt texts, 1800 `geo_client_prompts` rows.
- AI Image: 80 distinct prompt texts, 4800 `geo_client_prompts` rows.
- AI Design: 10 distinct prompt texts, 600 `geo_client_prompts` rows.

This causes the drill-down matrix to show repeated prompt concepts and increases response size.

## Visibility Split API Design

The Visibility API is split into three backend surfaces.

### 1. Visibility Overview

Endpoint:

```text
GET /api/insights/visibility/overview
```

Returns the first-screen dashboard data:

- summary
- time series
- previous time series
- average position series
- previous average position series
- competitive series
- SOV ranking
- visibility ranking
- position ranking
- filters metadata

This endpoint must preserve the current calculation logic and response values for all existing first-screen charts and ranking cards.

### 2. Visibility Ranking Groups

Endpoint:

```text
GET /api/insights/visibility/ranking-groups
```

Returns group-level ranking matrix data only:

- group mode: `topic` or `product`
- group id or product key
- group display name
- group-level top brands
- prompt concept count
- total mentions
- own mention indicators

It does not return prompt drill-down rows.

The UI calls this endpoint when the ranking matrix section becomes visible or when the user switches between topic and product grouping.

### 3. Visibility Ranking Prompts

Endpoint:

```text
GET /api/insights/visibility/ranking-prompts
```

Called only when a user expands a specific topic or product group.

Parameters:

- group mode: `topic` or `product`
- topic id or product key
- page
- page size
- optional prompt search
- current dashboard filters

Returns:

- paginated prompt concept rows
- each prompt row’s top brand ranking
- total prompt concept count
- current page metadata

Default page size is 20.

### Backward Compatibility

The existing `/api/insights/visibility` endpoint may remain as a compatibility wrapper during rollout. It must continue to support current consumers until the SaaS UI is fully migrated.

No existing chart, ranking card, export path, static report path, or full ranking dialog may lose data because of the split.

## Visibility Prompt Aggregation Semantics

Matrix prompt rows aggregate by Client Prompt text, not by `geo_client_prompts.id`.

Grouping key:

- normalized `cp.text`
- scoped by client
- scoped by matrix group, such as topic or product

Prompt text normalization for grouping:

- trim whitespace
- collapse repeated whitespace
- compare case-sensitively for display but use normalized text for grouping

The display text uses a representative Client Prompt text from the group.

Aggregation respects active dashboard filters. If the user selects specific countries or platforms, the matrix only aggregates data from those selected countries and platforms. Country and platform filters reduce the underlying data set; they do not create separate prompt rows.

Example:

If a customer has one Client Prompt text applied to `US`, `JP`, and `GB`, and the user filters to `US` only, the prompt row aggregates only `US` results. If the user filters to `US` and `JP`, the same prompt row aggregates `US + JP` results. It is still one prompt row.

## Visibility UI Behavior

### First-Screen Load

When the user enters Visibility, the UI first loads:

- visibility score trend
- visibility ranking card
- SOV trend
- SOV ranking card
- average position trend
- position ranking card

The bottom ranking matrix is not included in this first request.

### Ranking Matrix Lazy Load

The bottom ranking matrix loads when:

- the matrix section scrolls into view
- the user explicitly interacts with the matrix area
- the user changes matrix mode between topic and product

While loading, it displays skeleton rows.

### Group Rows

The matrix first shows topic or product group rows:

- group name
- prompt concept count
- top brand ranking columns

Groups are collapsed by default.

### Prompt Drill-Down Rows

When the user expands a topic or product:

- the UI calls `visibility/ranking-prompts`
- prompt rows are loaded for that group only
- prompt rows are paginated
- prompt rows aggregate by Client Prompt text
- platform and country filters are applied to aggregation, not displayed as duplicated prompt rows

Pagination controls appear inside the expanded group. Page size defaults to 20.

### Zero-Difference Requirement

The split must not change the meaning or values of existing Visibility metrics.

The following must match the current endpoint for the same filters:

- visibility score
- visibility score change
- visibility rank
- SOV percentage
- SOV rank
- total mentions
- own mentions
- average position
- average position rank
- time series values
- previous period values
- competitive series
- top 20 ranking lists
- full ranking dialog contents

The only intended matrix change is prompt drill-down aggregation by Client Prompt text instead of repeated `geo_client_prompts.id`.

## Frontend Dashboard Request Stability

Dashboard pages must avoid duplicate or stale requests.

### Filter Ready Gate

Dashboard metric requests do not fire until required filter state is ready:

- client id
- topics
- platforms
- countries
- date range

This prevents initial empty-filter requests followed immediately by hydrated-filter requests.

### Filter Key Debounce

Dashboard requests use a debounced filter key for high-churn controls:

- topics
- platforms
- countries
- date range

The debounce window is 150 to 300 milliseconds.

This prevents intermediate multi-select states from producing unnecessary backend requests.

### Stable State Updates

Filter state setters must not create new arrays when the semantic selection is unchanged.

For example, country option hydration should compare old and new selected country arrays. If the contents are equal, it returns the previous array reference.

This avoids unnecessary React re-renders and duplicate API effects.

### Request Race Safety

Existing `AbortController` and request sequence guards remain in place.

AbortController stops stale browser fetches when possible. Request sequence validation ensures that only the latest response can update page state, even if older requests finish later.

## Risks and Safeguards

## Visibility Split Risk

Visibility splitting is the highest-risk part of this iteration because it touches the core dashboard.

Safeguards:

- Keep existing `/api/insights/visibility` available during migration.
- Add endpoint-level parity checks during local or staging validation.
- Compare old endpoint values against new overview endpoint values for the same client and filters.
- Compare old matrix group output against new group endpoint output.
- Validate prompt drill-down aggregation for clients with one prompt text expanded across many countries/platforms.
- Keep all existing chart components visually unchanged except for matrix lazy loading and pagination.

## Published URL Tracking Risk

Published URL tracking must not slow down the existing Citation Monitor.

Safeguards:

- Use a separate tracking endpoint.
- Paginate the tracking table.
- Add indexes before production use.
- Match by normalized exact URL only in this iteration.
- Avoid live Feishu reads in dashboard paths.

## Citation Instrumentation Risk

Timing logs must not leak sensitive data.

Safeguards:

- Log counts, timings, client id, and filter dimensions.
- Do not log raw AI response text.
- Do not log secrets, API keys, or full request payloads.

## Validation Requirements

### Published Pages

Validate:

- Create Published URL.
- Edit Published URL.
- Disable Published URL.
- Delete Published URL.
- List with pagination.
- Search by title, URL, channel, and topic.
- Filter by publish status, channel, and topic.
- Download CSV template.
- Preview valid CSV.
- Preview CSV with missing required fields.
- Preview CSV with invalid URL.
- Preview CSV with unmatched topic.
- Preview CSV over 100 rows.
- Confirm import.
- Upsert duplicate normalized URL.
- Published URL Tracking follows Citation Monitor filters.
- Published URL Tracking metrics align with Top Cited Pages semantics.
- Detail drawer shows all specified data when available and gracefully handles optional empty fields.

### Citation Performance Logs

Validate:

- `/citations` logs per-phase timings.
- `/cited-domains` logs per-phase timings.
- `/cited-pages` logs per-phase timings.
- Logs include row counts and total time.
- Logs do not include raw response text or secrets.
- Existing endpoint responses remain unchanged.

### Visibility Split

Validate:

- New overview endpoint matches old endpoint for first-screen metrics.
- Existing first-screen charts render with no visual regression.
- Ranking cards and full ranking dialogs keep current behavior and row limits.
- Matrix section lazy-loads only when needed.
- Topic group rows render before prompt drill-down rows.
- Product group rows render before prompt drill-down rows.
- Expanding a group loads prompt rows.
- Prompt rows are paginated.
- Prompt rows aggregate by Client Prompt text.
- Country and platform filters affect aggregation data but do not create duplicate prompt rows.
- AI Video with 30 distinct prompt texts displays 30 prompt concepts across all pages, not 1800 `geo_client_prompts` rows.
- Static reports and any other consumers of the old visibility response are not broken by the rollout.

## Out of Scope

This iteration does not include:

- Feishu Sheets live sync.
- Agent-driven Published URL maintenance.
- Directory-level or domain-level Published URL matching.
- Automatic creation of workspace topics from CSV import.
- Replacing Citation endpoints with cached responses.
- Removing the existing `/api/insights/visibility` compatibility endpoint during rollout.
- Changing Collector or Analyzer behavior.
- Changing existing Citation, Visibility, or Sentiment metric definitions.
