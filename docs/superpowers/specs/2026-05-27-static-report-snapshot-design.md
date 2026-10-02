# Static Report Snapshot Design

Date: 2026-05-27
Status: Draft for user review
Scope: AnswerX GEO SaaS static reports, snapshot materialization, and read-only report viewing

## Goal

Add a customer-facing static report feature for AnswerX GEO.

The report lets a client view a durable daily snapshot of GEO Visibility, Citation, and Sentiment performance after the existing Collector and Analyzer pipelines have produced data.

The first release must support:

- One static report snapshot per client per Shanghai calendar day.
- SaaS UI entry for viewing today's report and historical reports.
- On-demand materialization from existing analyzed data when the user first opens a report.
- Persistent JSON snapshot storage in PostgreSQL.
- Report detail rendering that reuses the existing SaaS visual language and chart style.
- Frontend-only interactions against the snapshot data, without live metric API calls.
- Backend authorization so only users with access to the report's client can view it.

The feature must be a sidecar read model. It must not change how Collector, Analyzer, scheduled jobs, or the current dynamic dashboards work.

## Non-Goals

The first release will not:

- Trigger GEO Collector.
- Trigger GEO Analyzer.
- Add a new Admin button for "run today's collection and analysis".
- Change existing Admin scheduled task configuration.
- Change existing Visibility, Citation, Site Engine, or Sentiment dashboard APIs.
- Add public sharing links.
- Generate downloadable static HTML as the primary storage format.
- Rebuild historical reports automatically when later data arrives.

Admin can continue using the existing manual and scheduled mechanisms to run Collector and Analyzer. Static reports only consume their outputs.

## Current State

AnswerX already has the upstream data pipeline:

1. Admin configures client-level quota, schedule, and operational settings.
2. SaaS configures brands, topics, peers, products, prompts, domains, and other tenant data.
3. Collector expands prompts, dispatches Cloro jobs, receives callbacks, and stores raw results in `geo_results`.
4. Analyzer processes `geo_results` and writes structured outputs such as brand mentions, product mentions, citations, and sentiment.
5. Existing SaaS dashboards query those tables dynamically.

The static report feature should sit after step 4 and read the same analyzed tables that the dynamic dashboards already use.

## Product Decision Summary

### Entry Point

SaaS UI gets a dedicated Reports page.

Recommended navigation:

- Sidebar item: `Reports / 报告`
- Reports list route: `/reports`
- Report detail route: `/reports/static/:reportId`

The Insights pages may include a lightweight "View today's report" CTA, but the Reports page is the canonical place for current and historical reports.

Admin UI gets an internal report management page for cross-client troubleshooting. It must not introduce a new "run today's collection and analysis" button. Existing Admin manual triggers and cron configuration remain the source of truth for data pipeline execution.

### Button Semantics

The SaaS primary action should be phrased as "View today's report" rather than "Run today's task".

Behavior:

- If today's snapshot exists, open it.
- If today's snapshot does not exist but analyzed data is ready, materialize the snapshot and open it.
- If today's data is not ready, show a clear waiting state.
- Never trigger Collector or Analyzer from SaaS.

Suggested status-specific labels:

- Completed: `View report`
- Ready to materialize: `Generate and view`
- In progress or not ready: `Waiting for data`
- Failed snapshot: `Retry snapshot generation` if retry is allowed for SaaS users, otherwise `Contact support`

For the first release, SaaS users should not have a force-rerun data action.

## Data Freshness and Date Rules

Report dates are based on Asia/Shanghai local dates.

For a request made at any time on `YYYY-MM-DD` Shanghai time, the system looks for:

- `client_id`
- `report_date = YYYY-MM-DD`

There is a unique report per `(client_id, report_date)`.

The default report window is the last 7 Shanghai calendar days ending on `report_date`.

However, the report renderer must treat single-day data as a first-class case. Many Pitch workflows happen immediately after onboarding, so only one day of data may exist.

Rendering modes:

- `multi_day`: at least two dates have usable data. Trend charts can be shown.
- `single_day`: only one date has usable data. Replace weak one-point trend charts with rankings, distributions, platform breakdowns, topic/prompt summaries, and completion metrics.

## Materialization Strategy

### Recommended Strategy

Use on-demand materialization when the SaaS user first opens or requests today's report.

This is intentionally more decoupled than automatic materialization after Analyzer completion.

Flow:

1. User opens Reports or clicks "View today's report".
2. Backend checks whether a completed snapshot exists for `(client_id, Shanghai today)`.
3. If it exists, return the report.
4. If it does not exist, backend checks whether today's analyzed data is ready.
5. If data is ready, backend creates a snapshot row and returns it.
6. If data is not ready, backend returns a structured not-ready response.

This approach avoids any dependency from Analyzer into the report system and keeps all existing scheduled jobs untouched.

### Tradeoff

On-demand materialization means the first user to open the report may wait longer than later users. This is acceptable for the first release because the main requirement is decoupling and operational safety.

If report opening latency becomes a problem, a later release can add a separate background job that materializes snapshots after data readiness. That future job must still remain outside the Collector and Analyzer critical path.

## Readiness Gate

The report system should not create a permanent daily snapshot until the analyzed data is complete enough.

Readiness is evaluated from existing database state only. It does not start new upstream work.

### Required Conditions

For the selected client and report date:

1. There are `geo_results` rows in the report window.
2. At least one analyzed result belongs to the Shanghai report date itself. A "today" report must not be materialized from stale data that only exists on previous days in the 7-day window.
3. Relevant `geo_results` rows have `analyzed_at IS NOT NULL`, or the system can otherwise determine Analyzer has processed them.
4. Visibility data is available from brand or product mention tables.
5. Citation data is available from `geo_citations`.
6. Sentiment data is available from `geo_sentiment_results`, unless the client has no active Sentiment-scope prompts for the window.

If Sentiment is expected but not ready, the system must not materialize the snapshot.

This keeps the one-per-day snapshot stable and avoids permanently saving a report that lacks Sentiment only because the user opened it too early.

### Partial Collector Failures

Partial Collector failure should not block report generation if enough analyzed data exists.

The snapshot should store data completeness metadata:

- raw result count
- analyzed result count
- analyzed percentage
- expected prompt/task coverage when available
- warnings for missing platforms, empty modules, or low coverage

The minimum viable threshold is at least one analyzed result on the report date plus the required module data above. Low coverage beyond that threshold should produce warnings, not block the report.

If there is no usable same-day analyzed data, the system should not create a report.

## Report Lifecycle

Status values:

- `PENDING`: row created but snapshot not built.
- `MATERIALIZING`: snapshot build is running.
- `COMPLETED`: snapshot JSON is available.
- `NOT_READY`: latest attempt found upstream data incomplete.
- `FAILED`: snapshot generation failed.

The normal first-release lifecycle is:

```text
No row
  -> user requests today's report
  -> readiness check
  -> NOT_READY or MATERIALIZING
  -> COMPLETED or FAILED
```

A completed report is immutable from the SaaS user's perspective.

Admin may later get an internal "rebuild snapshot" action, but that action must rebuild only the snapshot from existing data. It must not rerun Collector or Analyzer.

## Data Model

Create a new table: `geo_static_reports`.

Columns:

- `id uuid primary key`
- `client_id uuid not null references geo_clients(id)`
- `report_date date not null`
- `timezone text not null default 'Asia/Shanghai'`
- `status text not null`
- `snapshot_version text not null`
- `snapshot_json jsonb`
- `data_window_start date not null`
- `data_window_end date not null`
- `rendering_mode text not null`
- `data_completeness jsonb not null default '{}'::jsonb`
- `warnings jsonb not null default '[]'::jsonb`
- `error_message text`
- `materialized_by_user_id uuid references geo_users(id)`
- `materialized_at timestamptz`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Constraints:

- `UNIQUE(client_id, report_date)`
- `status IN ('PENDING', 'MATERIALIZING', 'COMPLETED', 'NOT_READY', 'FAILED')`
- `rendering_mode IN ('single_day', 'multi_day')`

Indexes:

- `(client_id, report_date desc)`
- `(client_id, status)`

Schema changes must be delivered as a numbered migration file under `migrations/`. No DDL should be executed directly.

## Snapshot Shape

The snapshot stores canonical report data, not rendered HTML.

Top-level shape:

```json
{
  "version": "static-report-v1",
  "client": {
    "id": "...",
    "name": "..."
  },
  "report": {
    "date": "2026-05-27",
    "timezone": "Asia/Shanghai",
    "window_start": "2026-05-21",
    "window_end": "2026-05-27",
    "rendering_mode": "single_day"
  },
  "data_completeness": {
    "raw_results": 120,
    "analyzed_results": 118,
    "analyzed_pct": 98.3,
    "warnings": []
  },
  "visibility": {},
  "citations": {},
  "sentiment": {},
  "prompts": {},
  "topics": {},
  "narrative": {
    "zh-CN": {},
    "en-US": {}
  }
}
```

Structured numeric data is stored once. UI labels, table headings, buttons, and chart legends should continue using existing frontend i18n keys.

If the snapshot includes generated prose, that prose should be stored in both `zh-CN` and `en-US` under `narrative`.

The first release does not require LLM-generated narrative. It can ship with structured metrics, charts, rankings, deterministic status copy, and bilingual UI labels. If narrative generation is added, it must use configured model IDs and store both languages in the snapshot.

## Static JSON vs Static HTML

The primary persistence format should be JSON.

Reasons:

- Existing React and Recharts components can be reused.
- Frontend interactions such as expanding rankings and filtering local rows are easier against JSON.
- The report can follow the current SaaS language without duplicating the full page.
- UI and visual style changes do not require rewriting stored HTML.
- Snapshot schema versioning is cleaner than storing opaque HTML.

Static HTML export can be added later as a derived artifact for downloads, email attachments, or public share links.

## Frontend Experience

### Reports List

SaaS route: `/reports`

The page shows:

- Today's report card.
- Historical report list ordered by report date descending.
- Status badge.
- Report date.
- Materialized time.
- Data completeness summary.
- Action button.

Today's card should guide the user:

- Completed: open the report.
- Data ready but no snapshot: generate and open.
- Data not ready: explain that Collector/Analyzer data is not ready yet.
- Failed: show the failure message and support path.

### Report Detail

SaaS route: `/reports/static/:reportId`

The page loads one snapshot payload and renders a vertical report:

1. Cover and metadata.
2. Data completeness banner.
3. Visibility section.
4. Citation section.
5. Sentiment section.
6. Prompt and topic breakdown.
7. Appendix with platform, country, language, and prompt coverage.

The detail page must not call live dashboard endpoints for metrics.

Allowed interactions:

- Expand ranking lists.
- Filter included rows locally.
- Switch chart grouping if all required rows are already present in the snapshot.
- Switch language using global SaaS language or a local report language control.

Disallowed interactions:

- Fetching fresh metric data from dynamic dashboard endpoints.
- Triggering Collector or Analyzer.
- Mutating prompts, settings, or report source data.

### Language Behavior

The report detail follows the current SaaS language by default.

If the user switches SaaS language:

- Structural UI labels change through i18n.
- Structured data remains the same.
- Generated narrative uses the matching language if present.

A local language switch on the report page is allowed but not required for the first release.

## Backend API

Add SaaS API routes under `/api/static-reports`.

Proposed endpoints:

### `GET /api/static-reports?client_id=...`

Returns reports for the authorized client.

Response includes metadata only, not full `snapshot_json`.

### `GET /api/static-reports/today?client_id=...`

Returns today's report status.

If completed, includes the report id.

If not ready, includes readiness reasons and any known schedule hints if available.

### `POST /api/static-reports/today/materialize`

Request body:

```json
{
  "client_id": "..."
}
```

Behavior:

- Check authorization.
- Compute Shanghai report date.
- If completed snapshot exists, return it.
- If a materialization is already running, return running status.
- Check readiness.
- If not ready, return `NOT_READY` and reasons.
- If ready, build snapshot and mark completed.

This endpoint must not trigger Collector or Analyzer.

### `GET /api/static-reports/{report_id}`

Returns report metadata and `snapshot_json`.

Authorization is resolved by looking up the report's `client_id` and applying existing client access checks.

## Authorization

All SaaS static report endpoints require Google OAuth.

Rules:

- A user can list reports only for clients they can access.
- A user can view a report only if they can access that report's client.
- A user can materialize today's snapshot only for a client they can access.
- Admin internal access uses Admin authorization, not SaaS client access. Admin users may list reports across clients for troubleshooting, but the Admin API must still run behind `require_admin_request_access`.

Frontend route protection is not sufficient. Backend checks are required.

## Admin Report Management

Admin UI should include a read-only management surface for static report snapshots.

Routes:

- Admin Web route: `/static-reports`
- Admin API list route: `GET /api/static-reports`
- Admin API detail route: `GET /api/static-reports/{report_id}`

Capabilities:

- List report snapshots across all clients.
- Filter by client, status, and report date range.
- Show customer name, report date, status, data window, rendering mode, materialized time, and error message.
- Open a detail dialog showing metadata, warnings, data completeness, and a compact summary of snapshot sections.
- Provide a rendered-report link for completed reports so Admin can inspect the customer-facing SaaS view when useful.

Non-capabilities in the first Admin implementation:

- Do not trigger Collector.
- Do not trigger Analyzer.
- Do not add a "run today's task" shortcut.
- Do not rebuild snapshots yet.

Admin-only rebuild can be added later, but it must rebuild only `snapshot_json` from existing analyzed tables. It must not call Collector, Analyzer, scheduler, or LLM code.

## Snapshot Builder

Implement a dedicated snapshot builder module in the SaaS backend.

Responsibilities:

- Read existing analyzed tables.
- Apply the last-7-days report window.
- Compute readiness.
- Compute single-day versus multi-day rendering mode.
- Build normalized snapshot JSON.
- Store snapshot atomically.

The builder should not import Collector or Analyzer code.

The builder should not call LLMs in the first release unless narrative generation is explicitly enabled later. This keeps snapshot materialization fast and reduces the chance that opening a report fails because of model latency or quota.

It may reuse safe helper functions or query patterns from existing `insights` routers, but it must not change those router responses.

If reusing existing metric functions requires invasive changes, first release should duplicate narrowly scoped read queries inside the snapshot builder to preserve isolation.

## Concurrency and Idempotency

The unique `(client_id, report_date)` constraint is the hard guard against duplicate daily reports.

Materialization should use one of these patterns:

- Insert row with `ON CONFLICT` and lock it with `SELECT ... FOR UPDATE`.
- Or update a pre-existing row from `NOT_READY` or `FAILED` to `MATERIALIZING` only when safe.

Concurrent clicks should result in one materialization job and other requests returning the same report status.

If materialization fails, store the error and allow retrying snapshot generation from existing data.

## Error Handling

Not-ready response should distinguish:

- No raw results for today or report window.
- Raw results exist but Analyzer has not processed them.
- Visibility data missing.
- Citation data missing.
- Sentiment data expected but missing.
- Data coverage below minimum threshold.

User-facing copy should be calm and actionable, for example:

`Today's data is still being analyzed. Please check again after the scheduled collection and analysis jobs finish.`

The message should not expose internal table names to SaaS users.

## Testing Strategy

Backend tests:

- One report per client per Shanghai date.
- Existing completed report is returned without rebuilding.
- Materialization does not call Collector or Analyzer code paths.
- Not-ready when raw results are missing.
- Not-ready when analyzed outputs are incomplete.
- Sentiment blocks materialization when expected but missing.
- Sentiment does not block materialization when no active Sentiment-scope prompts exist.
- Client authorization blocks cross-tenant report access.
- Concurrent materialization requests do not create duplicate rows.

Frontend tests or manual E2E:

- Reports list renders completed, not-ready, failed, and materializing states.
- Report detail renders from snapshot JSON only.
- Single-day report uses non-trend presentation.
- Multi-day report uses trend presentation.
- Language switch updates labels and narrative without refetching live metrics.
- Admin report management lists reports across clients and opens report metadata/details without triggering materialization.

Regression checks:

- Existing Visibility dashboard still loads from live API.
- Existing Citation or Site Engine dashboard still loads from live API.
- Existing Sentiment dashboard still loads from live API.
- Existing Admin scheduler and manual Collector/Analyzer triggers are unchanged.

## Rollout Plan

1. Add database migration for `geo_static_reports`.
2. Add SaaS backend static report repository and snapshot builder.
3. Add SaaS backend static report API routes.
4. Add SaaS Reports list page and report detail page.
5. Reuse or adapt existing chart/table components for snapshot data.
6. Add i18n keys in `zh-CN` and `en-US`.
7. Add backend tests for readiness, idempotency, and authorization.
8. Add Admin static report list/detail API and Admin Web management page.
9. Run local visible E2E for Reports page, report detail, and Admin report management.

No rollout step should modify Collector, Analyzer, or dynamic dashboard behavior.

## Deferred Enhancements

These are intentionally outside the first release:

- Background auto-materialization after Analyzer completion.
- Admin-only rebuild snapshot action.
- Static HTML export.
- Public share links.
- Email delivery.
- Report template customization.
- Scheduled report notification.

## Final Design Decision

The static report feature is a read-only snapshot layer over existing analyzed data.

SaaS users view or materialize a daily report snapshot. They do not run data tasks.

Admin continues to own Collector and Analyzer execution through existing mechanisms.

The report is persisted as JSON, rendered by SaaS React components, protected by client-level authorization, and isolated from the existing dynamic dashboards.
