# GEO Collector and Analyzer Throughput Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Collector prompt expansion overhead and shorten Analyzer runtime by adding Client-level expansion controls, Final Prompt reuse, Analyzer batch isolation, Cloud Run Job sharding, short write transactions, and Admin batch selection.

**Architecture:** Keep the existing Collector and Analyzer Cloud Run Job architecture. Collector resolves Client-level settings before Global Config, reuses Final Prompts when configured, and keeps `batch_id` as an Asia/Shanghai date string. Analyzer resolves one pending date batch, processes it through Cloud Run Job task shards, performs LLM calls outside long write transactions, and stamps rows only after successful writes.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, pytest, PostgreSQL SQL migrations, Google Cloud Run Jobs, Terraform, React, TypeScript, Vite.

---

## Scope Rules

Do not run Git commands.

Do not execute database DDL directly. Create migration SQL for the user to review and execute manually.

Do not add `collector_run_id` in this iteration.

Do not introduce Pub/Sub Analyzer workers, Vertex Batch Prediction, Analyzer claim tables, Sentiment Enricher services, Citation Enricher services, prompt-level expansion policy controls, or platform-level Final Prompt policies.

Do not skip Sentiment based on intent.

## File Map

### Database Migration

- Create: `migrations/112_geo_throughput_client_settings.sql`
- Create: `migrations/113_geo_results_unanalyzed_index_concurrently.sql`
  - Add nullable Client-level prompt expansion settings columns to `geo_clients`.
  - Add an idempotent Analyzer lookup index.

### Collector

- Modify: `geo_collector/src/services/prompt_expander.py`
  - Resolve Client overrides before Global Config.
  - Compute `batch_id` in Asia/Shanghai.
  - Implement Final Prompt reuse.
  - Add effective setting and reuse/generation logs.
- Create: `geo_collector/tests/test_prompt_expander_throughput.py`
  - Cover setting fallback, reuse keys, reuse behavior, and Shanghai batch date.

### Analyzer

- Modify: `geo_analyzer/main.py`
  - Resolve `ANALYZER_BATCH_ID` or earliest pending batch.
  - Read `CLOUD_RUN_TASK_INDEX` and `CLOUD_RUN_TASK_COUNT`.
  - Apply shard predicate.
  - Acquire shard advisory lock.
  - Move LLM calls outside long write transactions.
  - Add per-phase timing logs.
- Modify: `geo_analyzer/src/pipeline/phase2a_domain_classify.py`
  - Keep domain classification callable outside the write transaction.
- Modify: `geo_analyzer/src/pipeline/phase2b_sentiment.py`
  - Keep Sentiment extraction callable outside the write transaction.
- Modify: `geo_analyzer/src/pipeline/phase3_write.py`
  - Keep writes and `analyzed_at` stamping inside a short transaction controlled by the main loop.
- Modify: `geo_analyzer/src/pipeline/phase_b_normalize_themes.py`
  - Run theme normalization in a short final stage after shard processing.
- Create: `geo_analyzer/tests/test_analyzer_throughput.py`
  - Cover batch resolution, shard predicate, advisory lock behavior, and write-stamp idempotency.

### Analyzer Terraform

- Modify: `geo_analyzer/terraform/main.tf`
  - Set Cloud Run Job `task_count = 8`.
  - Set Cloud Run Job `parallelism = 8`.
  - Keep timeout `10800s`.
  - Keep conservative retry behavior.

### Admin API

- Modify: `geo_admin/src/routers/clients.py`
  - Include Client prompt expansion settings in Client read/update models.
  - Validate typed values.
- Modify: `geo_admin/src/routers/jobs.py`
  - Allow Analyzer manual trigger to pass selected `batch_id`.
  - Preserve existing Collector and Analyzer trigger behavior when batch is omitted.
- Modify: `geo_admin/src/routers/tasks.py`
  - Replace or extend simple batch id list with batch summary records for Analyzer selection.
- Create: `geo_admin/tests/test_geo_throughput_admin.py`
  - Cover Client settings persistence, batch summary output, and Analyzer run payload.

### Admin Web

- Modify: `geo_admin/web/src/pages/ClientsPage.tsx`
  - Add `Prompt Expansion Settings` to Client edit UI.
  - Use a switch for `reuse_latest_final_prompt`.
  - Use a dropdown for `country_localization_mode`.
  - Use numeric inputs for `final_prompt_per_client_prompt` and `default_calls_per_prompt`.
  - Display Global Config fallback behavior in helper text.
- Modify: `geo_admin/web/src/pages/ClientsPage.tsx`
  - Add Analyzer batch picker for manual Analyzer runs.
  - Default to earliest pending batch.
  - Show analyzed/unanalyzed counts, task status counts, and latest timestamps.
- Modify: `geo_admin/web/src/api/client.ts`
  - Add typed API helpers for Client settings and batch summaries.
- Modify: `geo_admin/web/src/api/openapi.d.ts`
  - Regenerate or update types after backend schema changes.

### Deployment

- Modify: `deploy_all.sh`
  - Increment versions only for changed modules.
  - Keep image build and Terraform commands active only for changed modules.

## Task 1: Database Migration for Client Settings and Analyzer Lookup

- [ ] Create `migrations/112_geo_throughput_client_settings.sql` for transaction-safe `geo_clients` column and constraint changes.
- [ ] Create `migrations/113_geo_results_unanalyzed_index_concurrently.sql` for the concurrent `geo_results` partial index.

The migration stores Client-level settings on `geo_clients` without changing Global Config semantics. It uses nullable Client values so missing Client settings fall back to Global Config.

Required settings:

```text
reuse_latest_final_prompt boolean
country_localization_mode text
final_prompt_per_client_prompt integer
default_calls_per_prompt integer
```

Valid `country_localization_mode` values:

```text
generic
localized_by_country
```

The migration must be idempotent and use `ALTER TABLE geo_clients ADD COLUMN IF NOT EXISTS` for:

```text
reuse_latest_final_prompt boolean
country_localization_mode text
final_prompt_per_client_prompt integer
default_calls_per_prompt integer
```

The `country_localization_mode` check constraint accepts null, `generic`, and `localized_by_country`. Numeric check constraints accept null or values greater than or equal to 1.

- [ ] Add an efficient Analyzer lookup index when no equivalent exists in the migration logic.

The target lookup is:

```sql
WHERE client_id = $1
  AND batch_id = $2
  AND analyzed_at IS NULL
```

The preferred index shape is:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_results_client_batch_unanalyzed
ON geo_results (client_id, batch_id, result_id)
WHERE analyzed_at IS NULL;
```

- [ ] Keep the concurrent index in migration 113, outside the migration 112 transaction, so Collector callback writes are not blocked while the index is built.
- [ ] Execute migration 113 only through a SQL path that does not wrap the script in an explicit transaction.
- [ ] Add SQL comments explaining that `batch_id` remains a business-date string and no run-level id is introduced.

## Task 2: Collector Client Settings Resolution

- [ ] Add a small settings resolver in `geo_collector/src/services/prompt_expander.py` or a focused helper module used by it.

It returns:

```python
@dataclass(frozen=True)
class EffectivePromptExpansionSettings:
    reuse_latest_final_prompt: bool
    country_localization_mode: Literal["generic", "localized_by_country"]
    final_prompt_per_client_prompt: int
    default_calls_per_prompt: int
```

Resolution order:

```text
Client setting > Global Config > code default
```

Code defaults:

```text
reuse_latest_final_prompt = false
country_localization_mode = generic
final_prompt_per_client_prompt = 1
default_calls_per_prompt = 1
```

- [ ] Validate numeric settings.

Accepted values:

```text
final_prompt_per_client_prompt >= 1
default_calls_per_prompt >= 1
```

Invalid Client values fall back to Global Config and log a warning with `client_id`, setting name, and invalid value.

- [ ] Add tests proving Client settings override Global Config and missing Client settings fall back to Global Config.

## Task 3: Collector Asia/Shanghai Batch Date

- [ ] Change Collector `batch_id` computation from process-local `date.today()` to Asia/Shanghai business date.

Use Python timezone-aware date logic:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

batch_id = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
```

- [ ] Add a test that freezes or injects time around UTC/Shanghai midnight and proves `batch_id` uses Asia/Shanghai.

- [ ] Keep the format exactly:

```text
YYYY-MM-DD
```

## Task 4: Collector Final Prompt Reuse

- [ ] Add a function that loads reusable Final Prompts from existing historical tasks.

For `country_localization_mode = generic`, lookup key:

```text
client_id
logical_prompt_identity
language
```

For `country_localization_mode = localized_by_country`, lookup key:

```text
client_id
logical_prompt_identity
language
country
```

`logical_prompt_identity` is the normalized Client Prompt text, with prompt row id as a fallback only when text is missing. The lookup returns the newest distinct Final Prompt values from previous `geo_tasks` rows for that key, ordered by recent task creation time when available.

- [ ] When `reuse_latest_final_prompt = true`, use reusable Final Prompts until `final_prompt_per_client_prompt` is satisfied.

If reusable count is lower than requested count, call Gemini only for the missing count.

- [ ] When `reuse_latest_final_prompt = false`, call Gemini for the full `final_prompt_per_client_prompt` count.

- [ ] Keep Cloro fanout unchanged.

After Final Prompts are resolved, Collector still creates `geo_tasks` across prompt/platform/country with effective `default_calls_per_prompt`.

- [ ] Add logs:

```text
client_id
batch_id
reuse_latest_final_prompt
country_localization_mode
final_prompt_per_client_prompt
default_calls_per_prompt
reuse_hit_count
generated_final_prompt_count
geo_tasks_created
```

- [ ] Add tests:

```text
reuse disabled always calls Gemini
reuse enabled generic key ignores country
reuse enabled localized key includes country
partial reuse calls Gemini only for missing variants
Cloro task count remains based on effective calls_per_prompt
```

## Task 5: Analyzer Batch Resolution

- [ ] Add Analyzer batch resolution in `geo_analyzer/main.py`.

If `ANALYZER_BATCH_ID` is set, validate there are pending rows for:

```sql
client_id = $1
batch_id = $2
analyzed_at IS NULL
```

If `ANALYZER_BATCH_ID` is not set, resolve earliest pending batch:

```sql
SELECT batch_id
FROM geo_results
WHERE client_id = $1
  AND analyzed_at IS NULL
  AND batch_id IS NOT NULL
GROUP BY batch_id
ORDER BY batch_id ASC
LIMIT 1;
```

- [ ] If no pending batch is found and `FORCE_RUN` is not set, log and exit cleanly.

- [ ] Log the resolved batch:

```text
[ANALYZER-S1] Resolved batch_id=...
```

- [ ] Add tests for explicit batch, automatic earliest pending batch, and no pending batch.

## Task 6: Analyzer Cloud Run Task Sharding

- [ ] Read task env vars:

```text
CLOUD_RUN_TASK_INDEX
CLOUD_RUN_TASK_COUNT
```

Defaults for local runs:

```text
CLOUD_RUN_TASK_INDEX = 0
CLOUD_RUN_TASK_COUNT = 1
```

- [ ] Add PostgreSQL shard predicate for UUID `result_id`.

Use one deterministic expression consistently in pending count and fetch queries:

```sql
MOD(ABS(hashtext(result_id::text)), $task_count) = $task_index
```

- [ ] Apply the shard predicate to both pending count and fetch queries.

- [ ] Add tests proving two or more shards do not overlap and together cover all test result ids.

## Task 7: Analyzer Advisory Lock

- [ ] Add advisory lock acquisition before processing a shard.

Lock identity components:

```text
client_id
resolved_batch_id
task_index
task_count
```

Use PostgreSQL transaction-independent advisory lock for job lifetime:

```sql
SELECT pg_try_advisory_lock($1, $2);
```

Derive the two integer keys from stable hashes of the lock identity components. Use the same helper in tests and implementation.

- [ ] If lock acquisition fails, log the occupied shard and exit cleanly.

- [ ] Release the lock in `finally`.

- [ ] Add tests with mocked connection responses for acquired and unavailable locks.

## Task 8: Analyzer Transaction Boundary Refactor

- [ ] Refactor the batch loop so fetch and LLM phases are outside write transactions.

The loop order is:

```text
fetch batch
parse_batch
classify_batch_domains
extract_sentiment_for_batch
short transaction:
  write_batch
```

- [ ] Adjust domain classification helper usage so Gemini calls do not require an open write transaction.

Cache reads and cache writes can use short database operations. Gemini calls happen after cache misses are known and before the final write transaction.

- [ ] Adjust Sentiment helper usage so Gemini calls happen before the final write transaction.

Sentiment result writes happen in the short write transaction or through a helper that is explicitly invoked inside the write transaction after Gemini response parsing is complete.

- [ ] Keep `write_batch` responsible for structured writes and `analyzed_at` stamping.

- [ ] Add timing logs for:

```text
fetch
parse
domain_classify
sentiment
write
```

- [ ] Add tests proving the refactored batch loop executes phases in the required order, and run compile checks proving the modified modules import without syntax errors.

## Task 9: Analyzer Terraform Parallelism

- [ ] Modify `geo_analyzer/terraform/main.tf`.

Add Cloud Run Job task settings:

```hcl
template {
  task_count  = 8
  parallelism = 8

  template {
    ...
  }
}
```

Keep:

```hcl
timeout = "10800s"
```

Keep conservative retry behavior.

- [ ] Run Terraform syntax validation command for the analyzer directory:

```bash
terraform -chdir=geo_analyzer/terraform validate
```

Expected result: Terraform reports the configuration is valid after providers are initialized in the local environment.

## Task 10: Admin API Client Settings

- [ ] Update `geo_admin/src/routers/clients.py` request and response models to include prompt expansion settings.

Fields:

```text
reuse_latest_final_prompt: bool | null
country_localization_mode: "generic" | "localized_by_country" | null
final_prompt_per_client_prompt: int | null
default_calls_per_prompt: int | null
```

- [ ] Validate Admin updates:

```text
country_localization_mode must be generic or localized_by_country
final_prompt_per_client_prompt must be null or >= 1
default_calls_per_prompt must be null or >= 1
```

- [ ] Persist null values as null so Global Config fallback remains active.

- [ ] Add tests for read/update validation and fallback-preserving null values.

## Task 11: Admin API Analyzer Batch Summaries and Trigger

- [ ] Add or extend an Admin batch summary endpoint.

Response fields:

```text
batch_id
total_results
analyzed_results
unanalyzed_results
completed_tasks
dispatched_tasks
dispatch_failed_tasks
latest_ingested_at
latest_analyzed_at
is_default_selection
```

Default selection rule:

```text
the earliest batch with unanalyzed_results > 0
```

- [ ] Update Analyzer manual trigger endpoint to accept optional `batch_id`.

When `batch_id` is supplied, pass it to Cloud Run Job as:

```text
ANALYZER_BATCH_ID=<selected batch>
```

When `batch_id` is omitted, preserve current compatibility and let Analyzer resolve earliest pending batch.

- [ ] Add tests for batch summary ordering, default selection, and Analyzer trigger payload.

## Task 12: Admin Web Client Settings UI

- [ ] Update the Client edit form in `geo_admin/web/src/pages/ClientsPage.tsx`.

Add a section:

```text
Prompt Expansion Settings
```

Controls:

```text
reuse_latest_final_prompt -> Switch
country_localization_mode -> Select with Generic and Localized by country
final_prompt_per_client_prompt -> number input
default_calls_per_prompt -> number input
```

- [ ] Display helper text explaining fallback:

```text
Leave blank to use Global Config.
```

- [ ] Do not ask users to type `true`, `false`, `generic`, or `localized_by_country` manually.

- [ ] Add frontend validation for positive integer inputs.

- [ ] Ensure form save/load maps UI values to API fields correctly.

## Task 13: Admin Web Analyzer Batch Picker

- [ ] Update the manual Analyzer action UI in `geo_admin/web/src/pages/ClientsPage.tsx`.

Before triggering Analyzer, show available batch summaries for the selected client.

- [ ] Default to the earliest pending batch.

- [ ] Show:

```text
batch_id
unanalyzed result count
analyzed result count
completed/dispatched/dispatch_failed task counts
latest ingest time
latest analysis time
```

- [ ] Trigger Analyzer with selected `batch_id`.

- [ ] Keep Collector manual trigger unchanged.

## Task 14: Verification Commands

- [ ] Run Collector focused tests:

```bash
python -m pytest geo_collector/tests/test_fusion_prompt.py geo_collector/tests/test_cloro_client.py -q
```

Include the new Collector test file in this command.

- [ ] Run Analyzer focused tests:

```bash
python -m pytest geo_analyzer/tests -q
```

- [ ] Run Admin focused tests:

```bash
python -m pytest geo_admin/tests -q
```

- [ ] Run Python compile checks for touched backend modules:

```bash
python -m compileall geo_collector/src geo_analyzer geo_admin/src
```

- [ ] Run Admin web build:

```bash
cd geo_admin/web
npm run build
```

- [ ] Run SaaS web build only if SaaS web files are touched:

```bash
cd geo_saas/web
npm run build
```

- [ ] Run deploy script shell validation:

```bash
bash -n deploy_all.sh
```

## Task 15: Deployment Script Update

- [ ] Update `deploy_all.sh`.

Rules:

```text
increment versions for changed modules only
keep image build commands active for changed modules only
keep Terraform commands active for changed modules only
comment image build and Terraform commands for unchanged modules
```

Expected changed modules after this implementation:

```text
geo_collector
geo_analyzer
geo_admin API
geo_admin Web
```

## Self-Review Checklist

- [ ] Spec and plan explicitly keep `collector_run_id` out of this implementation.
- [ ] Plan includes `batch_id + analyzed_at IS NULL` as the primary isolation rule.
- [ ] Plan includes explicit `ANALYZER_BATCH_ID`.
- [ ] Plan includes automatic earliest pending batch selection.
- [ ] Plan includes Admin batch picker and typed Client settings controls.
- [ ] Plan includes Client override of `default_calls_per_prompt` and `final_prompt_per_client_prompt`.
- [ ] Plan includes `reuse_latest_final_prompt`.
- [ ] Plan includes `country_localization_mode` with exactly `generic` and `localized_by_country`.
- [ ] Plan includes Asia/Shanghai `batch_id`.
- [ ] Plan includes Cloud Run Job task sharding and Terraform `task_count` / `parallelism`.
- [ ] Plan includes advisory lock.
- [ ] Plan includes moving LLM calls outside long transactions.
- [ ] Plan keeps Sentiment complete and does not skip by intent.
- [ ] Plan includes logging and verification.
- [ ] Plan avoids Git commands.
