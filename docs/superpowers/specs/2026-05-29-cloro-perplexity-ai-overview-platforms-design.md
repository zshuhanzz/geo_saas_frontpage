# Cloro Perplexity and AI Overview Platform Support Design

## Goal

Extend AnswerX GEO platform support from ChatGPT, Gemini, and Google AI Mode to include Cloro Perplexity and Google AI Overview, while preserving the existing Collector strategy pattern and keeping Admin/SaaS platform configuration tenant-scoped and database-driven.

## Schema Decision

This version does not require a `geo_results` schema change.

The current `geo_results` columns already cover the core data needed by Visibility, Citation, Sentiment, and static reports:

- `text`
- `markdown`
- `sources`
- `citation_pills`
- `shopping_cards`
- `places`
- `entities`
- `search_queries`
- `cloro_response`

The phrase "first version does not change schema" does not mean a second version must change schema. It means the current feature scope can be implemented by normalizing new Cloro payloads into existing fields. A later schema change is only justified if the product wants first-class analytics over data that is currently only auxiliary, such as:

- Google Search organic results and People Also Ask items outside AI Overview.
- AI Overview `videos` and `ads` as filterable/reportable objects.
- Perplexity `videos`, `images`, `hotels`, or richer travel/media result types as dashboard entities.
- Per-platform raw feature tables for replay/debugging, for example `geo_result_media_assets` or `geo_result_serp_items`.

For this release, those fields can remain in `cloro_response` and, where useful, be lightly copied into existing JSONB columns such as `entities` or `places`.

## Product Behavior

Admin Global Platforms gains two active platform definitions:

| Platform ID | Display Name | Meaning |
| --- | --- | --- |
| `perplexity` | Perplexity | Perplexity AI answer extraction via Cloro. |
| `aioverview` | AI Overview | Google Search AI Overview answer extraction via Cloro. This is distinct from Google AI Mode. |

Existing customers are not automatically enabled for these platforms. Admins opt a customer in by editing the customer's `config_platforms`. This avoids silently increasing Cloro cost and changing scheduled task volume.

SaaS UI platform filters and prompt configuration should show only the active platforms enabled for the current customer. Admin template/workflow platform pickers should show the expanded platform registry.

## Cloro API Mapping

Perplexity is a direct Cloro monitor endpoint:

- Sync endpoint: `/v1/monitor/perplexity`
- Async task type: `PERPLEXITY`
- Request body uses `prompt`.
- Relevant response fields include `result.text`, `result.markdown`, `result.sources`, `result.shopping_cards` or `result.shoppingCards`, `result.places`, `result.hotels`, `result.videos`, and `result.images`.

AI Overview is returned by the Google Search endpoint, not by AI Mode:

- Sync endpoint: `/v1/monitor/google`
- Async task type should use Cloro's Google Search task type.
- Request body uses `query`, not `prompt`.
- Request must set `include.aioverview`, for example:

```json
{
  "query": "best laptops for programming",
  "country": "US",
  "include": {
    "aioverview": {
      "markdown": true
    }
  }
}
```

The ingestor must treat `result.aioverview` as the AI answer payload and must not mix ordinary Google organic results into GEO answer text.

## Collector Architecture

The Collector already has a dispatch strategy interface in `geo_collector/src/clients/cloro.py`. Keep that shape and add one capability: strategies can build their own Cloro payload because AI Overview uses `query` instead of `prompt`.

Recommended strategy shape:

- `get_platform_key()`
- `get_sync_endpoint_suffix()`
- `get_async_task_type()`
- `get_default_include_options()`
- `build_payload(task)`

Existing platforms keep the default payload shape:

```json
{
  "prompt": "...",
  "country": "US",
  "include": {}
}
```

AI Overview overrides it:

```json
{
  "query": "...",
  "country": "US",
  "include": {
    "aioverview": {
      "markdown": true
    }
  }
}
```

## Unpacker Architecture

Collector result ingestion uses a separate strategy/factory pattern under `geo_collector/src/services/unpackers`. This layer is incomplete today because only ChatGPT, Gemini, and AI Mode are registered.

Add:

- `PerplexityUnpacker`
- `AIOverviewUnpacker`

Perplexity should normalize:

- `text`: `result.text`
- `markdown`: `result.markdown`
- `sources`: `result.sources`
- `citation_pills`: `result.citationPills` when present
- `shopping_cards`: `result.shopping_cards` or `result.shoppingCards`
- `places`: combine `result.places` and `result.hotels` if both exist
- `entities`: keep media and related query metadata that is not first-class in the current schema
- `search_queries`: `result.search_model_queries`, `result.searchModelQueries`, or `result.related_queries`

AI Overview should normalize:

- `text`: `result.aioverview.text`
- `markdown`: `result.aioverview.markdown`
- `sources`: `result.aioverview.sources`
- `citation_pills`: `result.aioverview.citationPills`
- `entities`: videos, ads, and optional Google organic context when useful for debugging

If `result.aioverview` is `null`, the result should still ingest successfully with empty text/sources so the task completes without poisoning downstream processing.

## Admin and SaaS UI

Platform display logic should be centralized where practical. The goal is not a broad UI refactor, but hardcoded three-platform lists should be updated so new platforms are visible and consistently styled.

Required UI touchpoints:

- Admin customer platform configuration: already database-driven.
- Admin global platform table: already database-driven.
- Admin report/content template platform pickers: currently hardcoded and should include the two new platforms.
- SaaS prompt editor: already uses `/api/platforms` and customer `config_platforms`.
- SaaS Visibility/Citation/Sentiment filters: mostly customer-config-driven; ensure labels and colors work.
- Agent/content workflow platform controls: update hardcoded constants and color maps.
- i18n/help text mentioning only "ChatGPT/Gemini/AI Mode" should become "configured AI platforms" or include all five where explicit.

## Migration

Create a SQL migration that upserts:

- `geo_global_platforms.perplexity`
- `geo_global_platforms.aioverview`
- shared workflow platform config rows for both platforms, if the workflow config table exists.

The migration must not auto-append these platforms to existing customers. Admins enable them per customer.

The `geo_global_platforms.system_instructions` value for both new platforms should stay empty in the seed migration. The Collector prompt expander injects this field into final prompts, so implementation-facing notes about Cloro endpoints must not be stored there.

For supported countries, use conservative defaults:

- Perplexity: broad country support matching existing general AI platforms unless Cloro country lookup says otherwise.
- AI Overview: start with `US` only unless verified via Cloro countries endpoint for `model=aioverview`.

## Non-Goals

- No new dashboard chart types.
- No new static report behavior.
- No automatic client opt-in.
- No table split for media, ads, organic search results, or SERP objects in this release.

## Verification

The change is complete when:

- Collector unit tests prove platform strategy routing for all five platforms.
- Collector unit tests prove AI Overview uses `query` and `include.aioverview`.
- Unpacker tests prove Perplexity and AI Overview normalize sources, citation pills, shopping cards, places, and null AI Overview responses correctly.
- Admin and SaaS hardcoded platform controls include `perplexity` and `aioverview`.
- New SQL migration can be applied manually by the user and does not modify existing clients' enabled platform arrays.
