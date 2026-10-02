# GEO Collector and Analyzer Throughput Optimization Design

## Goal

Reduce GEO Collector prompt expansion overhead and materially shorten GEO Analyzer runtime for large customer batches while preserving existing dashboard semantics, report semantics, Sentiment completeness, and SaaS user simplicity.

This design covers the complete implementation scope for the current iteration. It intentionally keeps the architecture within the existing Cloud Run Job model and does not introduce Pub/Sub Analyzer workers, Vertex Batch Prediction, new Analyzer services, or run-level schema identifiers.

## Current Constraints

The current Collector writes `batch_id` as a date string:

```text
YYYY-MM-DD
```

For example:

```text
2026-06-03
```

This `batch_id` is a business-date batch, not a unique Collector run id. Multiple Collector runs on the same local business date share the same `batch_id`.

Analyzer currently processes rows from `geo_results` by `client_id` and `analyzed_at IS NULL`. It does not yet support explicit batch selection or Cloud Run Job task sharding. Analyzer also wraps some LLM work and writes in a long transaction, which can hold database resources while waiting for Gemini.

## Batch Semantics

This iteration keeps the existing `batch_id` date format and does not add `collector_run_id`.

The Analyzer isolation rule is:

```sql
client_id = :client_id
AND batch_id = :batch_id
AND analyzed_at IS NULL
```

This is sufficient for the intended same-day rerun workflow:

1. The first Collector run writes `geo_results` for today's `batch_id`.
2. The first Analyzer run stamps those rows with `analyzed_at`.
3. A second Collector run on the same date writes new rows with the same `batch_id`.
4. Those new rows have `analyzed_at IS NULL`.
5. A second Analyzer run for the same `batch_id` processes only the newly unanalyzed rows.

If the second Collector finishes today but Analyzer is triggered tomorrow before the next day's Collector has produced results, the latest pending batch still resolves to today's `batch_id`, and Analyzer can process those unanalyzed rows.

If multiple Collector runs overlap on the same date and both have unanalyzed callbacks arriving together, Analyzer processes all unanalyzed rows in that date batch. This is acceptable for the current iteration because dashboards and reports are date-batch oriented. Run-level audit and exact same-day rerun separation remain outside this iteration.

## Analyzer Batch Selection

Analyzer supports an optional environment variable:

```text
ANALYZER_BATCH_ID
```

When `ANALYZER_BATCH_ID` is provided, Analyzer processes only that date batch:

```sql
WHERE client_id = :client_id
  AND batch_id = :batch_id
  AND analyzed_at IS NULL
```

When `ANALYZER_BATCH_ID` is not provided, Analyzer automatically resolves the earliest pending batch:

```sql
SELECT batch_id
FROM geo_results
WHERE client_id = :client_id
  AND analyzed_at IS NULL
  AND batch_id IS NOT NULL
GROUP BY batch_id
ORDER BY batch_id ASC
LIMIT 1
```

This earliest-pending rule prevents older backlog from being starved by newer Collector data. It is safer than selecting the latest batch when cross-day backlog exists.

If no pending batch exists, Analyzer exits cleanly unless `FORCE_RUN` is set.

## Admin Manual Analyzer Behavior

Admin manual Analyzer triggering shows a batch picker.

The batch list includes every batch with `geo_results` for the client, with enough counts to explain readiness:

- `batch_id`
- unanalyzed result count
- analyzed result count
- total result count
- `geo_tasks` status counts for the same `client_id` and `batch_id`, including `COMPLETED`, `DISPATCHED`, and `DISPATCH_FAILED`
- latest `geo_results.ingested_at`
- latest `geo_results.analyzed_at`

The default selection is the earliest batch that still has unanalyzed results. Admin may select another batch explicitly.

SaaS users do not see batch controls. SaaS dashboards continue to read analyzed data by date and filters.

## Scheduled Analyzer Behavior

Scheduled Analyzer jobs do not need user interaction.

The scheduled job may pass `ANALYZER_BATCH_ID` if the scheduler or Admin backend knows the intended batch date. If it does not pass `ANALYZER_BATCH_ID`, the Analyzer resolves the earliest pending batch by the rule above.

This means scheduled Analyzer does not depend on wall-clock assumptions such as "run date minus one day." If a previous date has pending results, that older pending batch is processed first. If only the latest date has pending results, that batch is processed.

## Analyzer Cloud Run Job Parallel Sharding

Analyzer uses Cloud Run Job task parallelism.

It reads:

```text
CLOUD_RUN_TASK_INDEX
CLOUD_RUN_TASK_COUNT
```

Each task processes only its shard of the resolved batch. The shard predicate uses a deterministic hash/modulo of `result_id`, equivalent to:

```sql
MOD(hash(result_id), task_count) = task_index
```

The exact SQL implementation must be stable and PostgreSQL-compatible for UUID values.

Default Terraform values:

```text
task_count = 8
parallelism = 8
timeout = 10800 seconds
```

Each Cloud Run task still processes rows in batches. The per-task loop stays serial within that task. The iteration does not add a second layer of asyncio workers inside each task, so database and Vertex AI pressure do not increase unpredictably.

## Analyzer Advisory Lock

Each Analyzer task attempts to acquire a PostgreSQL advisory lock for its shard before processing.

The lock key is derived from:

```text
client_id
resolved_batch_id
task_index
task_count
```

If the lock is unavailable, the task logs that the shard is already being processed and exits cleanly.

The advisory lock prevents accidentally double-running the same batch shard when a manual trigger overlaps with a scheduled trigger or a retry.

## Analyzer Transaction Boundary

Analyzer LLM calls must not run inside long database transactions.

The per-batch flow becomes:

1. Fetch a batch of `geo_results` rows with a short query.
2. Run Phase 1 parsing in memory.
3. Run domain classification Gemini calls outside any write transaction.
4. Run Sentiment Gemini calls outside any write transaction.
5. Open a short write transaction for Phase 3 inserts and `geo_results.analyzed_at` stamping.
6. Run theme normalization as a short final transaction or a separate short stage after per-result writes.

This reduces database connection and transaction hold time while preserving rollback behavior for writes.

## Analyzer Idempotency

Analyzer continues to treat `geo_results.analyzed_at` as the completion marker.

Rows are selected only when:

```sql
analyzed_at IS NULL
```

Rows are stamped only after their analysis writes finish successfully:

```sql
UPDATE geo_results
SET analyzed_at = NOW()
WHERE result_id = :result_id
```

If a task fails after fetching rows but before stamping them, those rows remain eligible for the next Analyzer run. If a row is already stamped, it is not reprocessed by normal runs.

The iteration does not change existing metric table structures.

## Sentiment Scope

Analyzer keeps Sentiment processing complete.

It does not skip Sentiment based on prompt intent, even if current customer dashboards only show Sentiment for selected intent types. This preserves the ability to use historical analyzed data when Sentiment display configuration changes later.

Dashboard visibility for Sentiment remains controlled by existing configuration.

## Client-Level Prompt Expansion Settings

Admin Client configuration gains a `Prompt Expansion Settings` section.

The UI uses typed controls:

- switches for booleans
- dropdowns for enumerated modes
- numeric inputs for counts

Users do not type boolean strings or internal config key names.

The new Client-level settings are:

| Setting | UI Control | Meaning |
| --- | --- | --- |
| `reuse_latest_final_prompt` | Switch | Reuse the latest historical Final Prompt for the same prompt key instead of calling Gemini on every Collector run. |
| `country_localization_mode` | Dropdown | Controls whether country participates in Final Prompt reuse and generation. |
| `final_prompt_per_client_prompt` | Numeric input | Client override for how many Final Prompts to generate per Client Prompt. |
| `default_calls_per_prompt` | Numeric input | Client override for how many Cloro calls to make per Final Prompt. |

`country_localization_mode` has exactly two options:

```text
generic
localized_by_country
```

`generic` means the same Client Prompt can reuse the same Final Prompt across countries.

`localized_by_country` means different countries generate and reuse separate Final Prompts.

The lookup priority is:

```text
Client setting > Global Config > code default
```

Global Config keeps existing `default_calls_per_prompt` and `final_prompt_per_client_prompt` values as fallback defaults.

Default behavior when Client settings are empty:

- `reuse_latest_final_prompt`: disabled.
- `country_localization_mode`: `generic`.
- `final_prompt_per_client_prompt`: inherit Global Config; if Global Config is missing or invalid, use `1`.
- `default_calls_per_prompt`: inherit Global Config; if Global Config is missing or invalid, use `1`.

## Collector Final Prompt Reuse

When `reuse_latest_final_prompt` is disabled, Collector behaves as it does today: each run calls Gemini to generate the requested Final Prompt variants.

When `reuse_latest_final_prompt` is enabled, Collector first looks for reusable historical Final Prompts.

For `country_localization_mode = generic`, the reuse key is:

```text
client_id
logical_prompt_identity
language
```

For `country_localization_mode = localized_by_country`, the reuse key is:

```text
client_id
logical_prompt_identity
language
country
```

`logical_prompt_identity` is the normalized Client Prompt text. If a prompt row has no text, the row id is used as a fallback identity. This preserves reuse across the current storage shape where one logical Client Prompt may be represented by multiple prompt rows for different countries or platforms.

If enough reusable Final Prompts exist for the configured `final_prompt_per_client_prompt`, Collector reuses them and skips Gemini expansion for that Client Prompt key.

If reusable Final Prompts are missing or insufficient, Collector calls Gemini to generate the missing Final Prompts. Newly generated Final Prompts are written through the normal `geo_tasks` creation flow and become available for future reuse.

Final Prompt reuse reduces Gemini Prompt Expander cost and duration. It does not reduce Cloro task count because Cloro calls still multiply by platform, country, Final Prompt count, and calls per prompt.

## Collector Country and Platform Semantics

Cross-platform Final Prompt reuse is intentional. It improves comparability because ChatGPT, Perplexity, AI Overview, and other platforms answer the same query text.

Cross-country reuse is controlled by `country_localization_mode`.

If a customer needs country-specific query wording while the Client setting is `generic`, the operational workaround is to create separate Client Prompts for those countries. Platform-specific wording can be handled the same way by creating separate prompt records when necessary.

This iteration does not add prompt-level or platform-level expansion policy controls.

## Client Settings Persistence

Client-level prompt expansion settings are stored on `geo_clients` as nullable configuration columns. This matches existing `geo_clients` usage for per-client quota, scheduler, platform, country, and language configuration.

The configuration must be accessible to:

- Admin API for reading and saving Client settings.
- Admin UI for editing settings.
- Collector prompt expander for resolving effective values.

SaaS UI does not expose these controls.

## Timezone Rule

Collector should compute `batch_id` using the intended business date in Asia/Shanghai.

This avoids UTC date drift when jobs run around midnight Shanghai time.

`batch_id` remains formatted as:

```text
YYYY-MM-DD
```

## Logging and Observability

Collector logs include:

- `client_id`
- `batch_id`
- effective `reuse_latest_final_prompt`
- effective `country_localization_mode`
- effective `final_prompt_per_client_prompt`
- effective `default_calls_per_prompt`
- Final Prompt reuse hits
- Final Prompt Gemini generations
- total `geo_tasks` created
- platform and country distribution when available

Analyzer logs include:

- `client_id`
- resolved `batch_id`
- `task_index`
- `task_count`
- current shard pending count
- batch fetch count
- Phase 1 parse duration
- domain classifier duration
- Sentiment duration
- Phase 3 write duration
- per-task processed count
- advisory lock acquisition outcome
- clean completion or failure reason

These logs make it possible to identify whether bottlenecks are in parsing, domain classification, Sentiment, writes, or external quotas.

## Database Changes

This iteration does not add `collector_run_id`.

Expected database changes are limited to Client-level prompt expansion settings on `geo_clients` and the Analyzer lookup index described below.

The migrations must be provided as SQL for manual execution by the user. The implementation must not execute DDL directly. The transaction-safe Client setting changes live in migration 112. The concurrent `geo_results` partial index lives in migration 113 because PostgreSQL does not allow `CREATE INDEX CONCURRENTLY` inside a transaction block.

Recommended indexes should be added only if current schema lacks an efficient path for the new Analyzer filters and per-shard ordered batch reads:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_results_client_batch_unanalyzed
ON geo_results (client_id, batch_id, result_id)
WHERE analyzed_at IS NULL;
```

The index is partial on `analyzed_at IS NULL`, supports `client_id + batch_id` filtering, and keeps `result_id` in key order for the Analyzer batch loop. It is created concurrently in migration 113 because `geo_results` receives Collector callback writes. Migration 113 must be executed through a SQL path that does not wrap the script in an explicit transaction. If the existing schema already has a suitable equivalent index, no additional index is needed.

## Deployment Scope

The expected code modules are:

- `geo_collector`: effective Client settings, Final Prompt reuse, Shanghai `batch_id`, logging.
- `geo_analyzer`: batch selection, sharding, advisory lock, transaction boundary, logging, Terraform parallelism.
- `geo_admin`: Admin API, Admin UI, and job trigger changes for Client settings and Analyzer batch selection.

Deployment scripts should keep build and Terraform commands active only for modules changed by the implementation.

## Verification

The implementation is complete when:

- Collector resolves Client-level overrides before Global Config fallback.
- Collector reuses historical Final Prompts when configured to do so.
- Collector generates new Final Prompts when reuse is disabled.
- Collector distinguishes `generic` and `localized_by_country` reuse keys.
- Collector keeps Cloro fanout behavior unchanged except for reduced Gemini expansion calls.
- Analyzer can process an explicit `ANALYZER_BATCH_ID`.
- Analyzer auto-resolves the earliest pending batch when no batch id is supplied.
- Analyzer shards work across Cloud Run Job task indexes without overlap.
- Analyzer advisory lock prevents duplicate shard execution.
- Analyzer LLM calls occur outside long write transactions.
- Analyzer only stamps `analyzed_at` after successful writes.
- Sentiment remains complete and is not skipped by intent.
- Admin UI exposes Client prompt expansion settings as typed controls.
- Admin manual Analyzer trigger shows batch options and defaults to the earliest pending batch.
- Tests cover Collector settings resolution, Final Prompt reuse keys, Analyzer batch resolution, Analyzer shard predicates, and Admin batch list behavior.
- Frontend build succeeds for touched Admin/SaaS web modules.
- Python tests or compile checks succeed for touched backend modules.
