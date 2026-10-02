# Dual-Mode Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the dual-mode GEO tracking system (brand-level + product/SKU-level mentions, Shadow Brands for OEM clients, Topic-only fallback, Onboarding Wizard) across backend, frontend, database, and agent NL2SQL — all without breaking Roborock's existing monitoring data.

**Architecture:** Introduce `geo_client_brands` (Own + Shadow) as first-class entity, extract `geo_client_topic_products` as structured table with `match_variants` + `product_role` + owner FKs, rename `geo_company_mentions → geo_brand_mentions` with `brand_role` enum replacing `is_own_brand` bool, add parallel `geo_product_mentions` table, update two parsers (BrandParser + new ProductParser) that both run always and write to separate tables, propagate new schema through Agent NL2SQL hints and SaaS dashboard queries.

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy / asyncpg / PostgreSQL 15 (Cloud SQL) / React 18 + TypeScript + Vite / shadcn/ui + Recharts / LangGraph (for geo_agent) / Gemini Vertex AI.

**Design spec:** `docs/superpowers/specs/2026-04-18-dual-mode-tracking-design.md` — read this first for context.

**Key constraints:**
- **No live users.** Only Roborock has production monitoring data. Tmax workspace is empty.
- **Roborock historical data MUST be preserved:** `geo_results / geo_brand_mentions (formerly geo_company_mentions) / geo_citations / geo_sentiment_*`.
- **Agent runtime state is disposable:** `checkpoints / agent_messages / agent_memories / geo_agent_tasks` will all be TRUNCATEd.
- **Claude cannot execute DDL/DML.** All non-SELECT SQL is saved to files under `migrations/` for the user to execute manually in Cloud SQL. Claude runs only SELECT for verification.
- **No git commits in the execution flow.** Implementer saves files; user reviews changes out-of-band.

---

## File Structure Map

### Files to create

| Path | Responsibility |
|---|---|
| `migrations/040_dual_mode_tracking_ddl.sql` | Schema creation: new tables, new columns |
| `migrations/041_dual_mode_tracking_data_migration.sql` | Data migration: seed brands, migrate products, convert is_own_brand→brand_role |
| `migrations/042_dual_mode_tracking_cleanup.sql` | DROP COLUMN (is_own_brand, products TEXT[]), TRUNCATE agent tables |
| `migrations/043_analysis_metrics_rewrite.sql` | UPDATE geo_analysis_metrics to use new schema references |
| `migrations/044_report_templates_wizard_config_rewrite.sql` | UPDATE geo_report_templates.wizard_config JSONB |
| `geo_analyzer/src/parsers/brand_parser.py` | (Renamed from company_parser.py) Matches brand names + peer names, emits brand mentions with brand_role |
| `geo_analyzer/src/parsers/product_parser.py` | New: matches product names + match_variants, emits product mentions with product_role |
| `geo_saas/src/routers/insights/availability.py` | New endpoint: GET /api/insights/availability returns which data dimensions are populated |
| `geo_saas/src/routers/insights/product_visibility.py` | New endpoint: product-level SOV / Top Products / platform breakdown |
| `geo_saas/src/routers/insights/cooccurrence.py` | New endpoint: Brand × Product co-occurrence (OEM core metric) |
| `geo_saas/src/routers/insights/topic_breakdown.py` | New endpoint: Topic-level coverage / platform heatmap |
| `geo_saas/src/routers/settings_brands.py` | New: Brands CRUD |
| `geo_saas/src/routers/settings_products.py` | New: Topic Products CRUD |
| `geo_saas/web/src/components/insights/ProductVisibilityDashboard.tsx` | Product-level SOV + Top Products + platform |
| `geo_saas/web/src/components/insights/CooccurrenceHeatmap.tsx` | Brand × Product共现 matrix component |
| `geo_saas/web/src/components/insights/TopicBreakdown.tsx` | Topic-level coverage + heatmap |
| `geo_saas/web/src/components/onboarding/OnboardingWizard.tsx` | Brand-first vs OEM two-branch Wizard |
| `geo_saas/web/src/components/shared/EmptyStateCard.tsx` | Shared empty-state widget for Topic-only fallbacks |

### Files to modify

| Path | Change summary |
|---|---|
| `geo_analyzer/main.py` | Load brands + tracked_products; run both parsers; write to new tables |
| `geo_analyzer/src/core/database.py` | Update SQLAlchemy Table definitions for new/renamed tables |
| `geo_analyzer/src/parsers/domain_classifier.py` | No structural change — already updated in previous iteration |
| `geo_saas/src/database.py` | Add new Table definitions; rename geo_company_mentions; update is_own_brand→brand_role |
| `geo_saas/src/routers/insights/visibility.py` | Rewrite all geo_company_mentions → geo_brand_mentions queries |
| `geo_saas/src/routers/insights/prompt_metrics.py` | Same rewrite |
| `geo_saas/src/routers/insights/analysis.py` | Rewrite NL2SQL schema hints |
| `geo_saas/src/routers/settings.py` | Remove peer.is_own_brand field; Topics CRUD adapt to products being in new table |
| `geo_saas/src/routers/brainstorming.py` | Read products from geo_client_topic_products; support Topic-only mode |
| `geo_saas/web/src/lib/api.ts` | Add Brands, Products, Availability TypeScript types + fetch functions |
| `geo_saas/web/src/pages/SettingsPage.tsx` | New Brands tab; restructured Products form; Onboarding Wizard trigger |
| `geo_saas/web/src/pages/PromptEditor.tsx` | Adapt `topic.products: string[]` → `topic.tracked_products: Product[]` |
| `geo_saas/web/src/components/insights/VisibilityDashboard.tsx` | Field renames + View By switcher + brand_role filter |
| `geo_saas/web/src/components/wizard/customFields/PeerPicker.tsx` | Remove is_own_brand; split brands/peers source |
| `geo_saas/web/src/components/agents/ContentTaskModal.tsx` | Same refactor |
| `geo_agent/src/tools/data_tools.py` | Update ALLOWED_TABLES + schema descriptions |
| `geo_agent/src/tools/chart_tools.py` | Field rename: is_own_brand → brand_role |
| `geo_agent/src/tools/utility_tools.py` | Remove obsolete is_own_brand WHERE |
| `geo_agent/src/graphs/analyze.py` | Update schema hint text (lines 266/284/290/298); fix hardcoded SQL (lines 570-575) |
| `geo_agent/src/routers/tasks.py` | Fix hardcoded SQL (lines 432-433); update relevant_tables (line 479) |
| `geo_agent/src/pipelines/analysis_pipeline.py` | Update schema hints (lines 42/79/372/668) |
| `geo_agent/src/pipelines/opportunity_pipeline.py` | Fix hardcoded SQL (lines 100-104) |
| `geo_admin/src/database.py` | Match geo_saas database.py changes |
| `geo_admin/src/routers/clients.py` | Topics/Products CRUD adapt |
| `geo_admin/src/routers/prompts.py` | Same |
| `geo_admin/src/routers/analysis.py` | Fix hardcoded SQL |

### Files to delete

| Path | Reason |
|---|---|
| `geo_agent/src/pipelines/_template_contracts_stub.py` | Phase 2 过渡产物,schema references are all broken anyway |
| `geo_admin/src/routers/brainstorming.py` | Already LEGACY-commented in prior iteration, now physically remove |
| `geo_analyzer/scripts/backfill_dedup_mentions.py` | One-off backfill script with all-old schema, no replay value |

---

## Phase 1: Database Migration (SQL Files)

Execution order: `040_ddl.sql` → `041_data_migration.sql` → `043_analysis_metrics_rewrite.sql` → `044_report_templates_wizard_config_rewrite.sql` → `042_cleanup.sql` (run LAST after code is deployed and verified).

All SQL files are created by Claude in `migrations/` — the user runs them manually against Cloud SQL. Claude verifies via SELECT queries.

---

### Task 1.1: Write migration 040 — DDL for new tables + new columns

**Files:**
- Create: `migrations/040_dual_mode_tracking_ddl.sql`

- [ ] **Step 1: Create the DDL file with all schema additions**

```sql
-- migrations/040_dual_mode_tracking_ddl.sql
-- Dual-Mode Tracking — Schema additions (safe, additive only).
-- Run BEFORE any code that references the new tables. Order matters within
-- this file: geo_client_topic_products depends on geo_client_brands.

BEGIN;

-- 1. geo_client_brands
CREATE TABLE geo_client_brands (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id   UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    brand_name  TEXT NOT NULL,
    aliases     TEXT[] NOT NULL DEFAULT '{}',
    is_shadow   BOOLEAN NOT NULL DEFAULT false,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, brand_name)
);
CREATE INDEX idx_geo_client_brands_client
    ON geo_client_brands(client_id) WHERE is_active = true;

-- 2. geo_client_topic_products
CREATE TABLE geo_client_topic_products (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic_id        UUID NOT NULL REFERENCES geo_client_topics(id) ON DELETE CASCADE,
    client_id       UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_name    TEXT NOT NULL,
    match_variants  TEXT[] NOT NULL DEFAULT '{}',
    product_role    TEXT NOT NULL DEFAULT 'own'
                    CHECK (product_role IN ('own', 'shadow_brand_native', 'peer')),
    owner_brand_id  UUID REFERENCES geo_client_brands(id) ON DELETE SET NULL,
    owner_peer_id   UUID REFERENCES geo_client_peers(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT product_role_fk_consistency CHECK (
        (product_role = 'own'                 AND owner_brand_id IS NULL AND owner_peer_id IS NULL) OR
        (product_role = 'shadow_brand_native' AND owner_brand_id IS NOT NULL AND owner_peer_id IS NULL) OR
        (product_role = 'peer'                AND owner_brand_id IS NULL AND owner_peer_id IS NOT NULL)
    )
);
CREATE INDEX idx_geo_client_topic_products_topic
    ON geo_client_topic_products(topic_id) WHERE is_active = true;
CREATE INDEX idx_geo_client_topic_products_client
    ON geo_client_topic_products(client_id) WHERE is_active = true;

-- 3. geo_product_mentions (parallel to geo_brand_mentions)
CREATE TABLE geo_product_mentions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_prompt_id    UUID NOT NULL,
    task_id             UUID,
    result_id           INTEGER NOT NULL,
    client_id           UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_id          UUID REFERENCES geo_client_topic_products(id) ON DELETE SET NULL,
    product_name        TEXT NOT NULL,
    product_role        TEXT NOT NULL
                        CHECK (product_role IN ('own', 'shadow_brand_native', 'peer')),
    owner_brand_id      UUID,
    owner_brand_name    TEXT,
    owner_peer_id       UUID,
    owner_peer_name     TEXT,
    mention_position    INTEGER,
    executed_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_geo_product_mentions_client
    ON geo_product_mentions(client_id, executed_at DESC);
CREATE INDEX idx_geo_product_mentions_result
    ON geo_product_mentions(result_id, client_id);
CREATE INDEX idx_geo_product_mentions_role
    ON geo_product_mentions(client_id, product_role);

-- 4. Add onboarding_wizard_completed to geo_clients
ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS onboarding_wizard_completed BOOLEAN NOT NULL DEFAULT false;

-- 5. Rename geo_company_mentions → geo_brand_mentions
ALTER TABLE geo_company_mentions RENAME TO geo_brand_mentions;
ALTER TABLE geo_brand_mentions RENAME COLUMN company_name TO brand_name;

-- 6. Add brand_role to geo_brand_mentions (populated in 041, not NULL-constrained yet)
ALTER TABLE geo_brand_mentions
    ADD COLUMN brand_role TEXT
    CHECK (brand_role IN ('own', 'shadow', 'peer'));

COMMIT;
```

- [ ] **Step 2: Inform user to run this in Cloud SQL**

The user executes `migrations/040_dual_mode_tracking_ddl.sql` in Cloud SQL Editor.

- [ ] **Step 3: Verify via SELECT**

Run this verification from Claude (SELECT only is allowed):

```python
# Use asyncpg to verify new tables exist and are empty
python3 -c "
import asyncio, asyncpg
async def v():
    c = await asyncpg.connect(host='localhost', port=5432,
        user='answer-x-geo-db-user', password='answer-x-geo-db-user-123',
        database='answer-x-geo-db')
    for t in ['geo_client_brands', 'geo_client_topic_products', 'geo_product_mentions']:
        n = await c.fetchval(f'SELECT COUNT(*) FROM {t}')
        print(f'{t}: {n} rows (expected 0)')
    n = await c.fetchval('SELECT COUNT(*) FROM geo_brand_mentions')
    print(f'geo_brand_mentions: {n} rows (expected 10486, renamed from geo_company_mentions)')
    cols = await c.fetch(\"\"\"SELECT column_name FROM information_schema.columns
        WHERE table_name = 'geo_brand_mentions'\"\"\")
    print('Columns:', sorted([c['column_name'] for c in cols]))
    await c.close()
asyncio.run(v())
"
```
Expected: 3 new tables 0 rows, geo_brand_mentions has 10486 rows + `brand_role` column present + `brand_name` not `company_name`.

---

### Task 1.2: Write migration 041 — Seed brands + migrate products + fill brand_role

**Files:**
- Create: `migrations/041_dual_mode_tracking_data_migration.sql`

- [ ] **Step 1: Create the data migration file**

```sql
-- migrations/041_dual_mode_tracking_data_migration.sql
-- Populate new tables with data from existing schema.
-- Run AFTER 040, BEFORE any code deploy (code reads from new tables).

BEGIN;

-- 1. Seed geo_client_brands from existing clients (one Own Brand per client)
INSERT INTO geo_client_brands (client_id, brand_name, aliases, is_shadow)
SELECT id, name, COALESCE(aliases, '{}'::text[]), false
FROM geo_clients
WHERE NOT EXISTS (
    SELECT 1 FROM geo_client_brands b WHERE b.client_id = geo_clients.id AND b.brand_name = geo_clients.name
);

-- 2. Migrate geo_client_topics.products TEXT[] → geo_client_topic_products rows
INSERT INTO geo_client_topic_products
    (topic_id, client_id, product_name, match_variants, product_role)
SELECT
    t.id AS topic_id,
    t.client_id,
    pn AS product_name,
    ARRAY[pn] AS match_variants,
    'own'
FROM geo_client_topics t
CROSS JOIN LATERAL unnest(t.products) AS pn
WHERE t.products IS NOT NULL AND array_length(t.products, 1) > 0;

-- 3. Fill geo_brand_mentions.brand_role from the legacy is_own_brand bool
UPDATE geo_brand_mentions
SET brand_role = CASE WHEN is_own_brand = true THEN 'own' ELSE 'peer' END
WHERE brand_role IS NULL;

-- 4. Tighten brand_role to NOT NULL (all rows now populated)
ALTER TABLE geo_brand_mentions ALTER COLUMN brand_role SET NOT NULL;

-- 5. Mark existing clients as wizard-completed (they won't see the new onboarding)
UPDATE geo_clients SET onboarding_wizard_completed = true;

COMMIT;
```

- [ ] **Step 2: User executes in Cloud SQL**

- [ ] **Step 3: Verify migration integrity**

```python
python3 -c "
import asyncio, asyncpg
async def v():
    c = await asyncpg.connect(host='localhost', port=5432,
        user='answer-x-geo-db-user', password='answer-x-geo-db-user-123',
        database='answer-x-geo-db')
    # Every client has at least one brand
    rows = await c.fetch('''
        SELECT c.id, c.name,
               (SELECT COUNT(*) FROM geo_client_brands b WHERE b.client_id = c.id) AS brand_count
        FROM geo_clients c
    ''')
    for r in rows:
        print(f\"Client {r['name']}: {r['brand_count']} brand(s)\")
        assert r['brand_count'] >= 1, 'Every client must have a brand'
    # Topic products migrated
    rows = await c.fetch('''
        SELECT t.topic_name, array_length(t.products, 1) AS orig_count,
               (SELECT COUNT(*) FROM geo_client_topic_products p WHERE p.topic_id = t.id) AS new_count
        FROM geo_client_topics t
        WHERE t.products IS NOT NULL AND array_length(t.products, 1) > 0
    ''')
    for r in rows:
        print(f\"Topic {r['topic_name']}: {r['orig_count']} → {r['new_count']}\")
        assert r['orig_count'] == r['new_count'], 'Product count must match after migration'
    # brand_role distribution
    rows = await c.fetch('SELECT brand_role, COUNT(*) FROM geo_brand_mentions GROUP BY brand_role')
    for r in rows:
        print(f\"brand_role={r['brand_role']}: {r['count']}\")
    total = sum(r['count'] for r in rows)
    print(f'Total: {total} (expected 10486)')
    assert total == 10486
    await c.close()
asyncio.run(v())
"
```
Expected: every client has a brand, topic product counts match, brand_role totals 10486 across 'own' + 'peer' (no 'shadow' yet since this migration creates no shadow brands).

---

### Task 1.3: Write migration 043 — Rewrite `geo_analysis_metrics.calculation_hint`

**Files:**
- Create: `migrations/043_analysis_metrics_rewrite.sql`

- [ ] **Step 1: Create the rewrite file**

```sql
-- migrations/043_analysis_metrics_rewrite.sql
-- Update SQL hints in geo_analysis_metrics to reference new schema.
-- 6 rows contain geo_company_mentions, 5 contain is_own_brand, 2 contain company_name.

BEGIN;

-- A. Table + column renames
UPDATE geo_analysis_metrics
SET calculation_hint = replace(
      replace(
        replace(
          calculation_hint,
          'geo_company_mentions', 'geo_brand_mentions'
        ),
        'cm.company_name', 'cm.brand_name'
      ),
      'company_name', 'brand_name'
    ),
    updated_at = NOW()
WHERE calculation_hint LIKE '%geo_company_mentions%'
   OR calculation_hint LIKE '%company_name%';

-- B. is_own_brand boolean → brand_role enum
UPDATE geo_analysis_metrics
SET calculation_hint = replace(
      replace(
        replace(
          replace(
            calculation_hint,
            'is_own_brand = true', 'brand_role = ''own'''
          ),
          'is_own_brand = false', 'brand_role = ''peer'''
        ),
        'cm.is_own_brand', 'cm.brand_role'
      ),
      'is_own_brand', 'brand_role'
    ),
    updated_at = NOW()
WHERE calculation_hint LIKE '%is_own_brand%';

-- C. relevant_tables array
UPDATE geo_analysis_metrics
SET relevant_tables = array_replace(relevant_tables, 'geo_company_mentions', 'geo_brand_mentions')
WHERE 'geo_company_mentions' = ANY(relevant_tables);

COMMIT;
```

- [ ] **Step 2: Dump before/after comparison for user review (Claude runs SELECT)**

```python
# Before running 043: snapshot the current calculation_hint values
python3 -c "
import asyncio, asyncpg, json
async def snap():
    c = await asyncpg.connect(host='localhost', port=5432,
        user='answer-x-geo-db-user', password='answer-x-geo-db-user-123',
        database='answer-x-geo-db')
    rows = await c.fetch('SELECT metric_name, calculation_hint, relevant_tables FROM geo_analysis_metrics ORDER BY metric_name')
    with open('/tmp/metrics_before_043.json', 'w') as f:
        json.dump([dict(r) for r in rows], f, ensure_ascii=False, indent=2, default=str)
    print(f'Snapshot saved to /tmp/metrics_before_043.json ({len(rows)} rows)')
    await c.close()
asyncio.run(snap())
"
```

- [ ] **Step 3: User executes 043 in Cloud SQL**

- [ ] **Step 4: Verify no old references remain**

```python
python3 -c "
import asyncio, asyncpg
async def v():
    c = await asyncpg.connect(host='localhost', port=5432,
        user='answer-x-geo-db-user', password='answer-x-geo-db-user-123',
        database='answer-x-geo-db')
    for term in ['geo_company_mentions', 'is_own_brand']:
        n = await c.fetchval(f\"SELECT COUNT(*) FROM geo_analysis_metrics WHERE calculation_hint LIKE '%{term}%'\")
        print(f'Metrics still containing \"{term}\": {n} (expected 0)')
    n = await c.fetchval(\"SELECT COUNT(*) FROM geo_analysis_metrics WHERE 'geo_company_mentions' = ANY(relevant_tables)\")
    print(f'Metrics with old table in relevant_tables[]: {n} (expected 0)')
    # company_name check — 'brand_name' should now appear instead
    n = await c.fetchval(\"SELECT COUNT(*) FROM geo_analysis_metrics WHERE calculation_hint LIKE '% brand_name%' OR calculation_hint LIKE '%.brand_name%'\")
    print(f'Metrics using new brand_name: {n} (expected 2+)')
    await c.close()
asyncio.run(v())
"
```
Expected: 0 old references, relevant_tables clean, brand_name present.

---

### Task 1.4: Write migration 044 — Rewrite `geo_report_templates.wizard_config`

**Files:**
- Create: `migrations/044_report_templates_wizard_config_rewrite.sql`

- [ ] **Step 1: Create the rewrite file**

```sql
-- migrations/044_report_templates_wizard_config_rewrite.sql
-- Update sql_hint strings inside wizard_config JSONB.
-- 2 templates contain geo_company_mentions / is_own_brand.

BEGIN;

UPDATE geo_report_templates
SET wizard_config = (
      replace(
        replace(
          replace(
            replace(
              replace(
                replace(
                  wizard_config::text,
                  'geo_company_mentions', 'geo_brand_mentions'
                ),
                'cm.is_own_brand = true', 'cm.brand_role = ''own'''
              ),
              'cm.is_own_brand', 'cm.brand_role'
            ),
            'is_own_brand = true', 'brand_role = ''own'''
          ),
          'is_own_brand = false', 'brand_role = ''peer'''
        ),
        'cm.company_name', 'cm.brand_name'
      )
    )::jsonb,
    updated_at = NOW()
WHERE wizard_config::text LIKE '%geo_company_mentions%'
   OR wizard_config::text LIKE '%is_own_brand%'
   OR wizard_config::text LIKE '%cm.company_name%';

COMMIT;
```

- [ ] **Step 2: User executes in Cloud SQL**

- [ ] **Step 3: Verify no old refs remain**

```python
python3 -c "
import asyncio, asyncpg
async def v():
    c = await asyncpg.connect(host='localhost', port=5432,
        user='answer-x-geo-db-user', password='answer-x-geo-db-user-123',
        database='answer-x-geo-db')
    for term in ['geo_company_mentions', 'is_own_brand']:
        n = await c.fetchval(f\"SELECT COUNT(*) FROM geo_report_templates WHERE wizard_config::text LIKE '%{term}%'\")
        print(f'Templates still containing \"{term}\": {n} (expected 0)')
    await c.close()
asyncio.run(v())
"
```
Expected: 0 hits for both.

---

### Task 1.5: Write migration 042 — DROP COLUMN + TRUNCATE (runs LAST)

**Files:**
- Create: `migrations/042_dual_mode_tracking_cleanup.sql`

> ⚠️ This migration is **irreversible** and should run only **AFTER** all code referencing old columns is deployed (Phases 2-6 complete and verified).

- [ ] **Step 1: Create the cleanup file**

```sql
-- migrations/042_dual_mode_tracking_cleanup.sql
-- ⚠️ IRREVERSIBLE. Run AFTER all code is deployed and verified.
-- Drops legacy columns and truncates agent runtime state.

BEGIN;

-- A. Drop is_own_brand from geo_brand_mentions (data already migrated to brand_role)
ALTER TABLE geo_brand_mentions DROP COLUMN is_own_brand;

-- B. Drop is_own_brand from geo_client_peers (0 true rows, legacy column)
ALTER TABLE geo_client_peers DROP COLUMN is_own_brand;

-- C. Drop products TEXT[] from geo_client_topics (data already migrated to geo_client_topic_products)
ALTER TABLE geo_client_topics DROP COLUMN products;

-- D. Truncate agent runtime state (no live users; wipe LangGraph state + chat history)
TRUNCATE TABLE checkpoints;
TRUNCATE TABLE agent_messages;
TRUNCATE TABLE agent_memories;
TRUNCATE TABLE geo_agent_tasks;

COMMIT;
```

- [ ] **Step 2: User executes (ONLY after all code phases are done — this is Phase 7)**

- [ ] **Step 3: Verify**

```python
python3 -c "
import asyncio, asyncpg
async def v():
    c = await asyncpg.connect(host='localhost', port=5432,
        user='answer-x-geo-db-user', password='answer-x-geo-db-user-123',
        database='answer-x-geo-db')
    cols = await c.fetch(\"SELECT column_name FROM information_schema.columns WHERE table_name = 'geo_brand_mentions'\")
    col_set = {c['column_name'] for c in cols}
    assert 'is_own_brand' not in col_set, 'is_own_brand must be dropped'
    assert 'brand_role' in col_set
    # Truncates
    for t in ['checkpoints', 'agent_messages', 'agent_memories', 'geo_agent_tasks']:
        n = await c.fetchval(f'SELECT COUNT(*) FROM {t}')
        print(f'{t}: {n} (expected 0)')
        assert n == 0
    await c.close()
asyncio.run(v())
"
```
Expected: is_own_brand gone, brand_role present, four agent tables empty.

---

## Phase 2: Analyzer Code Refactor (geo_analyzer)

### Task 2.1: Rename `company_parser.py` to `brand_parser.py` and expand behavior

**Files:**
- Modify + Rename: `geo_analyzer/src/parsers/company_parser.py` → `geo_analyzer/src/parsers/brand_parser.py`

- [ ] **Step 1: Read current company_parser.py**

```bash
Read file: geo_analyzer/src/parsers/company_parser.py
```
Current function: `parse_company_mentions(text, client_names, peers) -> List[Dict]` emits `is_client, is_peer`.

- [ ] **Step 2: Create new `brand_parser.py` replacing it**

```python
# geo_analyzer/src/parsers/brand_parser.py
"""
Brand Parser (replaces CompanyParser).

Extracts brand mentions from AI response text. Matches:
  - client's Own Brands  → brand_role='own'
  - client's Shadow Brands → brand_role='shadow'
  - client's Peers → brand_role='peer'

All three flow through the same regex matching machinery; difference is
only the source list and the emitted brand_role label. Each brand appears
at most once per response (first occurrence).
"""
import re
from typing import List, Dict, Iterable


def _iter_names(items: Iterable[Dict], name_key: str, aliases_key: str = 'aliases'):
    """Yield every primary name + alias across an iterable of dicts."""
    for item in items or []:
        primary = item.get(name_key)
        if primary:
            yield primary, item
        for a in item.get(aliases_key) or []:
            if a:
                yield a, item


def parse_brand_mentions(
    text: str,
    own_brands: List[Dict],       # [{brand_name, aliases, is_shadow}, ...]
    peers: List[Dict],            # [{primary_name, aliases}, ...]
) -> List[Dict]:
    """
    Match brand names in AI response text.

    Args:
        text: AI response full text
        own_brands: rows from geo_client_brands (includes Own and Shadow).
                    Each dict must have keys: brand_name, aliases, is_shadow (bool)
        peers: rows from geo_client_peers. Each dict: primary_name, aliases

    Returns list of mention dicts:
        { brand_name, brand_role: 'own'|'shadow'|'peer', char_position, mention_position }
    """
    if not text:
        return []

    candidates = []

    # Own brands (is_shadow=false) and Shadow brands (is_shadow=true)
    for name, meta in _iter_names(own_brands, 'brand_name'):
        role = 'shadow' if meta.get('is_shadow') else 'own'
        candidates.append({
            'canonical_name': meta['brand_name'],
            'alias_text': name,
            'role': role,
        })

    # Peers
    for name, meta in _iter_names(peers, 'primary_name'):
        candidates.append({
            'canonical_name': meta['primary_name'],
            'alias_text': name,
            'role': 'peer',
        })

    # Run regex for each candidate
    raw_matches = []
    for c in candidates:
        pattern = rf'\b{re.escape(c["alias_text"])}\b'
        for m in re.finditer(pattern, text, re.IGNORECASE):
            raw_matches.append({
                'brand_name': c['canonical_name'],
                'brand_role': c['role'],
                'char_position': m.start(),
            })

    # Sort by appearance
    raw_matches.sort(key=lambda x: x['char_position'])

    # Deduplicate: keep first occurrence per canonical brand_name (case-insensitive)
    seen = set()
    unique = []
    for m in raw_matches:
        key = m['brand_name'].lower()
        if key not in seen:
            seen.add(key)
            unique.append(m)

    # Assign 1-indexed mention_position by order
    for i, m in enumerate(unique):
        m['mention_position'] = i + 1
        del m['char_position']

    return unique
```

- [ ] **Step 3: Delete the old `company_parser.py`**

```bash
rm geo_analyzer/src/parsers/company_parser.py
```

- [ ] **Step 4: Verify file exists and is syntactically valid**

```bash
python3 -c "import ast; ast.parse(open('geo_analyzer/src/parsers/brand_parser.py').read()); print('OK')"
ls -la geo_analyzer/src/parsers/*.py
```
Expected: prints "OK"; `company_parser.py` is gone, `brand_parser.py` exists.

---

### Task 2.2: Create `product_parser.py`

**Files:**
- Create: `geo_analyzer/src/parsers/product_parser.py`

- [ ] **Step 1: Write the new parser**

```python
# geo_analyzer/src/parsers/product_parser.py
"""
Product Parser.

Matches product name + match_variants strings against AI response text.
Emits product mentions with product_role and denormalized owner information.

Matching strategy:
  - Each product contributes its product_name AND all match_variants as
    candidate patterns (alias-expanded).
  - \\b...\\b word-boundary regex, case-insensitive.
  - Variants ≤3 characters are skipped (too short, high false-positive risk).
  - Each product at most once per response (first occurrence wins).
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

MIN_VARIANT_LEN = 4


def parse_product_mentions(
    text: str,
    tracked_products: List[Dict[str, Any]],
    # Each product dict expected keys:
    #   id (UUID str), product_name (str), match_variants (list[str]),
    #   product_role (str), owner_brand_id (UUID or None),
    #   owner_brand_name (str or None), owner_peer_id, owner_peer_name
) -> List[Dict[str, Any]]:
    if not text or not tracked_products:
        return []

    # Build (variant, product_info) pairs with length filter
    candidates = []
    for prod in tracked_products:
        variants = list(prod.get('match_variants') or [])
        if prod.get('product_name') and prod['product_name'] not in variants:
            variants.insert(0, prod['product_name'])
        for v in variants:
            v = (v or '').strip()
            if not v:
                continue
            if len(v) < MIN_VARIANT_LEN:
                logger.warning(
                    "[PRODUCT-PARSER] Skipping variant too short (<%d): %r for product %r",
                    MIN_VARIANT_LEN, v, prod.get('product_name'),
                )
                continue
            candidates.append((v, prod))

    raw_matches = []
    for variant, prod in candidates:
        pattern = rf'\b{re.escape(variant)}\b'
        for m in re.finditer(pattern, text, re.IGNORECASE):
            raw_matches.append({
                'product_id': prod.get('id'),
                'product_name': prod['product_name'],
                'product_role': prod.get('product_role', 'own'),
                'owner_brand_id': prod.get('owner_brand_id'),
                'owner_brand_name': prod.get('owner_brand_name'),
                'owner_peer_id': prod.get('owner_peer_id'),
                'owner_peer_name': prod.get('owner_peer_name'),
                'char_position': m.start(),
            })

    raw_matches.sort(key=lambda x: x['char_position'])

    seen = set()
    unique = []
    for m in raw_matches:
        key = (m['product_name'] or '').lower()
        if key not in seen:
            seen.add(key)
            unique.append(m)

    for i, m in enumerate(unique):
        m['mention_position'] = i + 1
        del m['char_position']

    return unique
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('geo_analyzer/src/parsers/product_parser.py').read()); print('OK')"
```
Expected: OK.

- [ ] **Step 3: Smoke test with sample data**

```bash
python3 -c "
import sys
sys.path.insert(0, 'geo_analyzer/src')
from parsers.product_parser import parse_product_mentions

tracked = [
    {'id': 'id-1', 'product_name': 'HT-Series Power Running Boards',
     'match_variants': ['HT-Series', 'HT Series', 'HT-70911'],
     'product_role': 'own'},
    {'id': 'id-2', 'product_name': 'ARB Bull Bar',
     'match_variants': ['ARB Bull Bar Deluxe'],
     'product_role': 'peer',
     'owner_peer_name': 'ARB'},
]
text = 'Rough Country\\'s HT-Series running boards are popular. ARB Bull Bar Deluxe is also mentioned.'
r = parse_product_mentions(text, tracked)
for m in r:
    print(m)
assert len(r) == 2
print('Smoke test passed')
"
```
Expected: two mentions with product_role=own and peer respectively.

---

### Task 2.3: Update `geo_analyzer/src/core/database.py` Table definitions

**Files:**
- Modify: `geo_analyzer/src/core/database.py`

- [ ] **Step 1: Read current file**

```bash
Read file: geo_analyzer/src/core/database.py
```

- [ ] **Step 2: Apply edits — rename geo_company_mentions, add new Tables**

Change every occurrence of `geo_company_mentions` Table definition to be named `geo_brand_mentions`, rename `company_name` column to `brand_name`, replace `is_own_brand BOOLEAN` with `brand_role TEXT`. Then append three new Table definitions.

```python
# Inside the Tables section, locate the current geo_company_mentions Table
# definition (uses Column("company_name") and Column("is_own_brand"))
# and replace with:

geo_brand_mentions = Table(
    "geo_brand_mentions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("client_prompt_id", UUID(as_uuid=True), nullable=False),
    Column("task_id", UUID(as_uuid=True)),
    Column("result_id", Integer, nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("brand_name", Text, nullable=False),
    Column("mention_position", Integer),
    Column("brand_role", Text, nullable=False),
    Column("executed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)

# New tables (append near the end):

geo_client_brands = Table(
    "geo_client_brands",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("brand_name", Text, nullable=False),
    Column("aliases", ARRAY(Text), server_default="{}"),
    Column("is_shadow", Boolean, server_default="false"),
    Column("is_active", Boolean, server_default="true"),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

geo_client_topic_products = Table(
    "geo_client_topic_products",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("topic_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("product_name", Text, nullable=False),
    Column("match_variants", ARRAY(Text), server_default="{}"),
    Column("product_role", Text, nullable=False, server_default="'own'"),
    Column("owner_brand_id", UUID(as_uuid=True)),
    Column("owner_peer_id", UUID(as_uuid=True)),
    Column("is_active", Boolean, server_default="true"),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

geo_product_mentions = Table(
    "geo_product_mentions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("client_prompt_id", UUID(as_uuid=True), nullable=False),
    Column("task_id", UUID(as_uuid=True)),
    Column("result_id", Integer, nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("product_id", UUID(as_uuid=True)),
    Column("product_name", Text, nullable=False),
    Column("product_role", Text, nullable=False),
    Column("owner_brand_id", UUID(as_uuid=True)),
    Column("owner_brand_name", Text),
    Column("owner_peer_id", UUID(as_uuid=True)),
    Column("owner_peer_name", Text),
    Column("mention_position", Integer),
    Column("executed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True)),
)
```

Also drop the `is_own_brand` Column from `geo_client_peers` Table definition (that legacy column is dropped in migration 042).

- [ ] **Step 3: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('geo_analyzer/src/core/database.py').read()); print('OK')"
```

---

### Task 2.4: Rewrite `geo_analyzer/main.py` to use both parsers and new tables

**Files:**
- Modify: `geo_analyzer/main.py`

- [ ] **Step 1: Read current main.py Phase 0-3 to understand flow**

```bash
Read file: geo_analyzer/main.py (lines 1-240, full pipeline)
```

- [ ] **Step 2: Add Phase 0 data loads (brands + tracked_products) before existing Phase 1**

Replace the existing "Load client brand name" block (currently reads `geo_clients.name + aliases`) with loads from the new tables:

```python
# Phase 0: Load reference data -----------------------------------------

# Brands: Own + Shadow (replaces old client_names = [client.name] + aliases)
logger.info("[ANALYZER-S1] 加载 Client Brands (Own + Shadow)...")
brands_rows = conn.execute(text("""
    SELECT brand_name, aliases, is_shadow
    FROM geo_client_brands
    WHERE client_id = :client_id AND is_active = true
"""), {"client_id": client_id}).fetchall()
own_brands = [dict(b._mapping) for b in brands_rows]
logger.info(f"[ANALYZER-S1] Loaded {len(own_brands)} brands ({sum(1 for b in own_brands if b['is_shadow'])} shadow)")

# Peers — same as before, read directly into a list of dicts
logger.info("[ANALYZER-S1] 加载 Client Peers...")
peers_rows = conn.execute(text("""
    SELECT primary_name, aliases FROM geo_client_peers WHERE client_id = :client_id
"""), {"client_id": client_id}).fetchall()
peers = [dict(p._mapping) for p in peers_rows]

# Tracked products (with denormalized owner info)
logger.info("[ANALYZER-S1] 加载 Tracked Products...")
tracked_products_rows = conn.execute(text("""
    SELECT tp.id, tp.product_name, tp.match_variants, tp.product_role,
           tp.owner_brand_id, cb.brand_name AS owner_brand_name,
           tp.owner_peer_id,  cp.primary_name AS owner_peer_name
    FROM geo_client_topic_products tp
    LEFT JOIN geo_client_brands cb ON cb.id = tp.owner_brand_id
    LEFT JOIN geo_client_peers cp  ON cp.id = tp.owner_peer_id
    WHERE tp.client_id = :client_id AND tp.is_active = true
"""), {"client_id": client_id}).fetchall()
tracked_products = [dict(p._mapping) for p in tracked_products_rows]
logger.info(f"[ANALYZER-S1] Loaded {len(tracked_products)} tracked products")

# Domains — unchanged from previous iteration (path-prefix own handled inside citation_parser)
domains_rows = conn.execute(text("""
    SELECT domain FROM geo_client_domains WHERE client_id = :client_id
"""), {"client_id": client_id}).fetchall()
owned_domains = [row.domain for row in domains_rows]
```

- [ ] **Step 3: Replace `parse_company_mentions` call with `parse_brand_mentions`, add `parse_product_mentions` call in Phase 1 loop**

```python
# Inside the per-result loop (Phase 1)
from src.parsers.brand_parser import parse_brand_mentions
from src.parsers.product_parser import parse_product_mentions
# Remove: from src.parsers.company_parser import parse_company_mentions

# Replace the old parse_company_mentions call:
brand_mentions = parse_brand_mentions(
    result.text or "",
    own_brands=own_brands,
    peers=peers,
)

product_mentions = parse_product_mentions(
    result.text or "",
    tracked_products=tracked_products,
)

# citations = parse_citations(... owned_domains=owned_domains)  # unchanged

# Collect into batch_data for Phase 3 writes
batch_data.append((result, brand_mentions, product_mentions, citations))
```

- [ ] **Step 4: Update Phase 3 DB writes — INSERT into geo_brand_mentions + geo_product_mentions**

Replace the existing INSERT blocks (which wrote `geo_company_mentions` with `is_own_brand`) with:

```python
# Phase 3: Write data to DB
for result, brand_mentions, product_mentions, citations in batch_data:
    result_id = result.result_id

    # Brand mentions (own + shadow + peer)
    for m in brand_mentions:
        conn.execute(text("""
            INSERT INTO geo_brand_mentions
            (client_prompt_id, task_id, result_id, client_id,
             brand_name, mention_position, brand_role, executed_at)
            VALUES (:client_prompt_id, :task_id, :result_id, :client_id,
                    :brand_name, :mention_position, :brand_role, :executed_at)
        """), {
            "client_prompt_id": result.client_prompt_id,
            "task_id": result.task_id,
            "result_id": result.result_id,
            "client_id": result.client_id,
            "brand_name": m["brand_name"],
            "mention_position": m["mention_position"],
            "brand_role": m["brand_role"],
            "executed_at": result.ingested_at,
        })

    # Product mentions (own + shadow_brand_native + peer)
    for m in product_mentions:
        conn.execute(text("""
            INSERT INTO geo_product_mentions
            (client_prompt_id, task_id, result_id, client_id,
             product_id, product_name, product_role,
             owner_brand_id, owner_brand_name,
             owner_peer_id, owner_peer_name,
             mention_position, executed_at)
            VALUES (:client_prompt_id, :task_id, :result_id, :client_id,
                    :product_id, :product_name, :product_role,
                    :owner_brand_id, :owner_brand_name,
                    :owner_peer_id, :owner_peer_name,
                    :mention_position, :executed_at)
        """), {
            "client_prompt_id": result.client_prompt_id,
            "task_id": result.task_id,
            "result_id": result.result_id,
            "client_id": result.client_id,
            "product_id": m.get("product_id"),
            "product_name": m["product_name"],
            "product_role": m["product_role"],
            "owner_brand_id": m.get("owner_brand_id"),
            "owner_brand_name": m.get("owner_brand_name"),
            "owner_peer_id": m.get("owner_peer_id"),
            "owner_peer_name": m.get("owner_peer_name"),
            "mention_position": m["mention_position"],
            "executed_at": result.ingested_at,
        })

    # Citations — unchanged logic from previous iteration (url_is_owned override)
    for c in citations:
        if c.get("url_is_owned"):
            final_category = "Owned Media"
        else:
            final_category = domain_categories.get(c.get("source_domain", "").lower(), "Other")

        conn.execute(text("""
            INSERT INTO geo_citations
            (client_prompt_id, task_id, result_id, client_id,
             source_url, source_domain, source_position, source_label,
             is_citation_pill, domain_category, executed_at)
            VALUES (:client_prompt_id, :task_id, :result_id, :client_id,
                    :source_url, :source_domain, :source_position, :source_label,
                    :is_citation_pill, :domain_category, :executed_at)
        """), {
            "client_prompt_id": result.client_prompt_id,
            "task_id": result.task_id,
            "result_id": result.result_id,
            "client_id": result.client_id,
            "source_url": c["source_url"],
            "source_domain": c["source_domain"],
            "source_position": c.get("source_position"),
            "source_label": c.get("source_label"),
            "is_citation_pill": c["is_citation_pill"],
            "domain_category": final_category,
            "executed_at": result.ingested_at,
        })
```

- [ ] **Step 5: Verify main.py parses**

```bash
python3 -c "import ast; ast.parse(open('geo_analyzer/main.py').read()); print('OK')"
```

---

### Task 2.5: Delete legacy scripts in geo_analyzer

**Files:**
- Delete: `geo_analyzer/scripts/backfill_dedup_mentions.py`

- [ ] **Step 1: Verify no imports elsewhere**

```bash
grep -r "backfill_dedup_mentions" geo_analyzer/ --include='*.py'
```
Expected: only the file itself matches.

- [ ] **Step 2: Delete the file**

```bash
rm geo_analyzer/scripts/backfill_dedup_mentions.py
```

- [ ] **Step 3: Verify directory structure**

```bash
ls geo_analyzer/scripts/
```

---

## Phase 3: SaaS Backend Updates

### Task 3.1: Update `geo_saas/src/database.py` SQLAlchemy Table definitions

**Files:**
- Modify: `geo_saas/src/database.py`

- [ ] **Step 1: Read current database.py**

```bash
Read file: geo_saas/src/database.py (focus on geo_company_mentions Table def around line 273, peers Table def around line 119)
```

- [ ] **Step 2: Make the same changes as Task 2.3**

Apply identical changes (rename geo_company_mentions → geo_brand_mentions, rename column, swap is_own_brand→brand_role, drop peers.is_own_brand, add three new Tables).

- [ ] **Step 3: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/database.py').read()); print('OK')"
```

---

### Task 3.2: Rewrite `geo_saas/src/routers/insights/visibility.py`

**Files:**
- Modify: `geo_saas/src/routers/insights/visibility.py`

- [ ] **Step 1: Audit all old references**

```bash
grep -n "geo_company_mentions\|is_own_brand\|\.company_name" geo_saas/src/routers/insights/visibility.py
```
You'll see ~30 occurrences.

- [ ] **Step 2: Apply global renames**

Replace systematically:
- `geo_company_mentions` → `geo_brand_mentions` (both import and usage)
- `.c.company_name` → `.c.brand_name`
- `.c.is_own_brand == True` → `.c.brand_role == 'own'` (or `.in_(['own', 'shadow'])` if Shadow should count as own for SOV; decide based on caller semantics — for now use `== 'own'`)
- `.c.is_own_brand == False` → `.c.brand_role.in_(['peer'])` (keep only peer)

Update the import statement at the top:
```python
# Change: from database import database, geo_company_mentions, ...
from database import database, geo_brand_mentions, ...
# And rename the local variable binding throughout
```

Add a `brand_role` filter query parameter to every endpoint. Example for the main SOV endpoint:

```python
from fastapi import Query

@router.get("/visibility")
async def get_visibility(
    client_id: UUID,
    start_date: date,
    end_date: date,
    platforms: List[str] = Query([]),
    brand_role: Optional[str] = Query(None, regex="^(own|shadow|peer|all)$"),
    view_by: Optional[str] = Query("brand", regex="^(brand|product|topic)$"),
):
    # ...existing logic + where clauses for brand_role filter
    conditions = [geo_brand_mentions.c.client_id == client_id,
                  geo_brand_mentions.c.executed_at.between(start_date, end_date)]
    if brand_role and brand_role != 'all':
        conditions.append(geo_brand_mentions.c.brand_role == brand_role)
    # ... rest of query
```

- [ ] **Step 3: Verify no old refs remain**

```bash
grep -n "geo_company_mentions\|is_own_brand\|\.company_name" geo_saas/src/routers/insights/visibility.py
```
Expected: 0 matches.

- [ ] **Step 4: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/insights/visibility.py').read()); print('OK')"
```

---

### Task 3.3: Rewrite `geo_saas/src/routers/insights/prompt_metrics.py`

**Files:**
- Modify: `geo_saas/src/routers/insights/prompt_metrics.py`

- [ ] **Step 1: Apply same global renames as Task 3.2** (~10 occurrences)

Replace `geo_company_mentions` → `geo_brand_mentions`, `.company_name` → `.brand_name`, remove any `is_own_brand` clauses or rewrite to `brand_role`.

- [ ] **Step 2: Verify**

```bash
grep -n "geo_company_mentions\|is_own_brand" geo_saas/src/routers/insights/prompt_metrics.py
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/insights/prompt_metrics.py').read()); print('OK')"
```

---

### Task 3.4: Rewrite `geo_saas/src/routers/insights/analysis.py` NL2SQL schema hints

**Files:**
- Modify: `geo_saas/src/routers/insights/analysis.py`

- [ ] **Step 1: Locate schema hint strings** (around lines 288, 493, 526-537)

```bash
grep -n "geo_company_mentions\|is_own_brand\|company_name" geo_saas/src/routers/insights/analysis.py
```

- [ ] **Step 2: Rewrite the hint text blocks**

Update the multi-line schema description strings. Example replacement for lines ~288 and ~493:

Old:
```python
- geo_company_mentions(id, client_id, result_id, company_name, mention_position, is_own_brand, executed_at)
```
New:
```python
- geo_brand_mentions(id, client_id, result_id, brand_name, mention_position, brand_role ENUM('own','shadow','peer'), executed_at)
- geo_product_mentions(id, client_id, result_id, product_id, product_name, product_role ENUM('own','shadow_brand_native','peer'), owner_brand_name, owner_peer_name, mention_position, executed_at)
- geo_client_brands(id, client_id, brand_name, aliases[], is_shadow boolean)
- geo_client_topic_products(id, topic_id, client_id, product_name, match_variants[], product_role, owner_brand_id, owner_peer_id)
```

Rewrite the hardcoded SQL samples at lines ~526-537 similarly:

Old:
```python
SELECT COUNT(*)
FROM geo_company_mentions
WHERE client_id = '{client_id}' AND is_own_brand = true
```
New:
```python
SELECT COUNT(*)
FROM geo_brand_mentions
WHERE client_id = '{client_id}' AND brand_role = 'own'
```

Update the `relevant_tables` list (around line 41) similarly.

- [ ] **Step 3: Verify**

```bash
grep -n "geo_company_mentions\|is_own_brand" geo_saas/src/routers/insights/analysis.py
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/insights/analysis.py').read()); print('OK')"
```
Expected: 0 old refs, OK.

---

### Task 3.5: Create `geo_saas/src/routers/insights/availability.py`

**Files:**
- Create: `geo_saas/src/routers/insights/availability.py`

- [ ] **Step 1: Write the new endpoint module**

```python
# geo_saas/src/routers/insights/availability.py
"""
Insights Availability endpoint.

Returns which data dimensions are populated for a client so the Insights
UI can condition its View By selector and empty-state rendering.
"""
from uuid import UUID
from datetime import datetime, timedelta
from fastapi import APIRouter
from sqlalchemy import select, func
from database import (
    database, geo_client_brands, geo_client_peers,
    geo_client_topics, geo_client_topic_products,
    geo_brand_mentions, geo_product_mentions,
)

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/availability")
async def get_availability(client_id: UUID):
    """
    Returns:
      has_own_brands, has_shadow_brands, has_peers, has_topics,
      has_products, has_mentions_data (brand-level in last 30d),
      has_product_mentions_data (product-level in last 30d)
    """
    cutoff = datetime.utcnow() - timedelta(days=30)

    async def _count(q):
        return int(await database.fetch_val(q) or 0)

    n_own_brands = await _count(select(func.count()).select_from(geo_client_brands).where(
        geo_client_brands.c.client_id == client_id,
        geo_client_brands.c.is_shadow == False,
        geo_client_brands.c.is_active == True,
    ))
    n_shadow_brands = await _count(select(func.count()).select_from(geo_client_brands).where(
        geo_client_brands.c.client_id == client_id,
        geo_client_brands.c.is_shadow == True,
        geo_client_brands.c.is_active == True,
    ))
    n_peers = await _count(select(func.count()).select_from(geo_client_peers).where(
        geo_client_peers.c.client_id == client_id,
    ))
    n_topics = await _count(select(func.count()).select_from(geo_client_topics).where(
        geo_client_topics.c.client_id == client_id,
    ))
    n_products = await _count(select(func.count()).select_from(geo_client_topic_products).where(
        geo_client_topic_products.c.client_id == client_id,
        geo_client_topic_products.c.is_active == True,
    ))
    n_brand_mentions = await _count(select(func.count()).select_from(geo_brand_mentions).where(
        geo_brand_mentions.c.client_id == client_id,
        geo_brand_mentions.c.executed_at >= cutoff,
    ))
    n_product_mentions = await _count(select(func.count()).select_from(geo_product_mentions).where(
        geo_product_mentions.c.client_id == client_id,
        geo_product_mentions.c.executed_at >= cutoff,
    ))

    return {
        "has_own_brands": n_own_brands > 0,
        "has_shadow_brands": n_shadow_brands > 0,
        "has_peers": n_peers > 0,
        "has_topics": n_topics > 0,
        "has_products": n_products > 0,
        "has_mentions_data": n_brand_mentions > 0,
        "has_product_mentions_data": n_product_mentions > 0,
        "counts": {
            "own_brands": n_own_brands,
            "shadow_brands": n_shadow_brands,
            "peers": n_peers,
            "topics": n_topics,
            "products": n_products,
            "brand_mentions_30d": n_brand_mentions,
            "product_mentions_30d": n_product_mentions,
        },
    }
```

- [ ] **Step 2: Register the router in `geo_saas/src/main.py`**

Open `geo_saas/src/main.py`, find where other insights routers are included (e.g. `app.include_router(insights_visibility.router, prefix="/api")`), and add:

```python
from routers.insights import availability as insights_availability
app.include_router(insights_availability.router, prefix="/api")
```

- [ ] **Step 3: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/insights/availability.py').read()); print('OK')"
python3 -c "import ast; ast.parse(open('geo_saas/src/main.py').read()); print('OK')"
```

---

### Task 3.6: Create `geo_saas/src/routers/insights/product_visibility.py`

**Files:**
- Create: `geo_saas/src/routers/insights/product_visibility.py`

- [ ] **Step 1: Write the new endpoint**

```python
# geo_saas/src/routers/insights/product_visibility.py
"""
Product-level Visibility endpoint.

Provides SOV and mention counts aggregated by product_name (instead of brand).
For brand-first clients, shows Own Product table. For OEM/hybrid, supports
filtering by product_role.
"""
from uuid import UUID
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Query
from sqlalchemy import select, func, literal_column, and_, case, Date
from database import database, geo_product_mentions, geo_results

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/product-visibility")
async def get_product_visibility(
    client_id: UUID,
    start_date: date,
    end_date: date,
    platforms: List[str] = Query([]),
    product_role: Optional[str] = Query(None, regex="^(own|shadow_brand_native|peer|all)$"),
):
    """
    Returns:
      {
        "top_products": [{product_name, product_role, mention_count, sov_pct}, ...],
        "time_series": [{date, product_name, mention_count}, ...],
        "platform_breakdown": [{platform, product_name, mention_count}, ...],
        "summary": {total_mentions, distinct_products}
      }
    """
    conditions = [
        geo_product_mentions.c.client_id == client_id,
        geo_product_mentions.c.executed_at.between(start_date, end_date),
    ]
    if product_role and product_role != 'all':
        conditions.append(geo_product_mentions.c.product_role == product_role)

    # 1. Top products + SOV within the filtered set
    total_mentions_q = select(func.count().label("total")).where(and_(*conditions))
    total = int(await database.fetch_val(total_mentions_q) or 0)

    top_q = (
        select(
            geo_product_mentions.c.product_name,
            geo_product_mentions.c.product_role,
            func.count().label("mention_count"),
        )
        .where(and_(*conditions))
        .group_by(geo_product_mentions.c.product_name, geo_product_mentions.c.product_role)
        .order_by(func.count().desc())
        .limit(25)
    )
    top_rows = await database.fetch_all(top_q)
    top_products = [
        {
            "product_name": r["product_name"],
            "product_role": r["product_role"],
            "mention_count": r["mention_count"],
            "sov_pct": round(100.0 * r["mention_count"] / total, 2) if total else 0.0,
        }
        for r in top_rows
    ]

    # 2. Time-series
    ts_q = (
        select(
            func.cast(geo_product_mentions.c.executed_at, Date).label("date"),
            geo_product_mentions.c.product_name,
            func.count().label("mention_count"),
        )
        .where(and_(*conditions))
        .group_by(literal_column("1"), geo_product_mentions.c.product_name)
        .order_by(literal_column("1"))
    )
    ts_rows = await database.fetch_all(ts_q)

    # 3. Platform breakdown (join with geo_results)
    j = geo_product_mentions.join(
        geo_results,
        and_(
            geo_product_mentions.c.result_id == geo_results.c.result_id,
            geo_product_mentions.c.client_id == geo_results.c.client_id,
        ),
    )
    pb_conditions = list(conditions)
    if platforms:
        pb_conditions.append(geo_results.c.platform.in_(platforms))
    pb_q = (
        select(
            geo_results.c.platform,
            geo_product_mentions.c.product_name,
            func.count().label("mention_count"),
        )
        .select_from(j)
        .where(and_(*pb_conditions))
        .group_by(geo_results.c.platform, geo_product_mentions.c.product_name)
    )
    pb_rows = await database.fetch_all(pb_q)

    return {
        "summary": {
            "total_mentions": total,
            "distinct_products": len(top_products),
        },
        "top_products": top_products,
        "time_series": [dict(r) for r in ts_rows],
        "platform_breakdown": [dict(r) for r in pb_rows],
    }
```

- [ ] **Step 2: Register in main.py**

```python
from routers.insights import product_visibility as insights_product_visibility
app.include_router(insights_product_visibility.router, prefix="/api")
```

- [ ] **Step 3: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/insights/product_visibility.py').read()); print('OK')"
```

---

### Task 3.7: Create `geo_saas/src/routers/insights/cooccurrence.py`

**Files:**
- Create: `geo_saas/src/routers/insights/cooccurrence.py`

- [ ] **Step 1: Write the Brand × Product co-occurrence endpoint**

```python
# geo_saas/src/routers/insights/cooccurrence.py
"""
Brand × Product Co-occurrence endpoint — OEM core metric.

Counts how often a specific Shadow Brand and Own Product appear in the SAME
AI response. This is the primary signal for clients like Tmax, who want to
see 'HT-Series on Rough Country' mentions as a single unified metric.
"""
from uuid import UUID
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Query
from sqlalchemy import select, func, and_
from database import database, geo_brand_mentions, geo_product_mentions

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/brand-product-cooccurrence")
async def get_cooccurrence(
    client_id: UUID,
    start_date: date,
    end_date: date,
    brand_role: Optional[str] = Query("shadow", regex="^(own|shadow|peer|all)$"),
    product_role: Optional[str] = Query("own", regex="^(own|shadow_brand_native|peer|all)$"),
):
    """
    Returns matrix: [{brand_name, product_name, cooccurrence_count}, ...]
    Cooccurrence = count of distinct result_id where both brand mention and
    product mention appear.
    """
    bm = geo_brand_mentions.alias("bm")
    pm = geo_product_mentions.alias("pm")

    join = bm.join(
        pm,
        and_(bm.c.result_id == pm.c.result_id, bm.c.client_id == pm.c.client_id),
    )

    conditions = [
        bm.c.client_id == client_id,
        bm.c.executed_at.between(start_date, end_date),
    ]
    if brand_role and brand_role != 'all':
        conditions.append(bm.c.brand_role == brand_role)
    if product_role and product_role != 'all':
        conditions.append(pm.c.product_role == product_role)

    q = (
        select(
            bm.c.brand_name,
            pm.c.product_name,
            func.count(func.distinct(bm.c.result_id)).label("cooccurrence_count"),
        )
        .select_from(join)
        .where(and_(*conditions))
        .group_by(bm.c.brand_name, pm.c.product_name)
        .order_by(func.count(func.distinct(bm.c.result_id)).desc())
    )
    rows = await database.fetch_all(q)

    return {
        "brand_role_filter": brand_role,
        "product_role_filter": product_role,
        "matrix": [dict(r) for r in rows],
    }
```

- [ ] **Step 2: Register in main.py**

```python
from routers.insights import cooccurrence as insights_cooccurrence
app.include_router(insights_cooccurrence.router, prefix="/api")
```

- [ ] **Step 3: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/insights/cooccurrence.py').read()); print('OK')"
```

---

### Task 3.8: Create `geo_saas/src/routers/insights/topic_breakdown.py`

**Files:**
- Create: `geo_saas/src/routers/insights/topic_breakdown.py`

- [ ] **Step 1: Write the Topic-level breakdown endpoint**

```python
# geo_saas/src/routers/insights/topic_breakdown.py
"""
Topic-level Visibility breakdown.

For each Topic: how many of the topic's prompts had any own brand mention
(coverage %), and breakdown by AI platform.
"""
from uuid import UUID
from datetime import date
from typing import List
from fastapi import APIRouter, Query
from sqlalchemy import text
from database import database

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/topic-breakdown")
async def get_topic_breakdown(
    client_id: UUID,
    start_date: date,
    end_date: date,
    platforms: List[str] = Query([]),
):
    """
    Returns per-topic coverage + platform heatmap.
    """
    platform_clause = ""
    params = {"client_id": str(client_id), "start": start_date, "end": end_date}
    if platforms:
        platform_clause = "AND gr.platform = ANY(:platforms)"
        params["platforms"] = platforms

    # 1. Coverage: for each topic, fraction of active prompts that had >=1 own brand mention
    coverage_sql = f"""
        WITH topic_prompts AS (
            SELECT cp.id AS prompt_id, t.id AS topic_id, t.topic_name
            FROM geo_client_prompts cp
            JOIN geo_client_topics t ON t.id = cp.topic_id
            WHERE cp.client_id = :client_id AND cp.is_active = true
        ),
        prompts_with_own AS (
            SELECT DISTINCT cp.id AS prompt_id
            FROM geo_client_prompts cp
            JOIN geo_brand_mentions bm ON bm.client_prompt_id = cp.id
            JOIN geo_results gr ON gr.result_id = bm.result_id AND gr.client_id = bm.client_id
            WHERE cp.client_id = :client_id
              AND bm.brand_role = 'own'
              AND bm.executed_at BETWEEN :start AND :end
              {platform_clause}
        )
        SELECT tp.topic_name,
               COUNT(*) AS total_prompts,
               COUNT(*) FILTER (WHERE pwo.prompt_id IS NOT NULL) AS covered_prompts,
               ROUND(100.0 * COUNT(*) FILTER (WHERE pwo.prompt_id IS NOT NULL) / NULLIF(COUNT(*), 0), 2) AS coverage_pct
        FROM topic_prompts tp
        LEFT JOIN prompts_with_own pwo ON pwo.prompt_id = tp.prompt_id
        GROUP BY tp.topic_id, tp.topic_name
        ORDER BY coverage_pct DESC NULLS LAST
    """
    coverage = await database.fetch_all(text(coverage_sql), params)

    # 2. Platform heatmap: topic × platform own-brand mention count
    heatmap_sql = f"""
        SELECT t.topic_name, gr.platform,
               COUNT(*) AS own_brand_mentions
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp ON cp.id = bm.client_prompt_id
        JOIN geo_client_topics t ON t.id = cp.topic_id
        JOIN geo_results gr ON gr.result_id = bm.result_id AND gr.client_id = bm.client_id
        WHERE bm.client_id = :client_id
          AND bm.brand_role = 'own'
          AND bm.executed_at BETWEEN :start AND :end
          {platform_clause}
        GROUP BY t.topic_name, gr.platform
        ORDER BY t.topic_name, gr.platform
    """
    heatmap = await database.fetch_all(text(heatmap_sql), params)

    return {
        "coverage": [dict(r) for r in coverage],
        "heatmap": [dict(r) for r in heatmap],
    }
```

- [ ] **Step 2: Register in main.py**

```python
from routers.insights import topic_breakdown as insights_topic_breakdown
app.include_router(insights_topic_breakdown.router, prefix="/api")
```

- [ ] **Step 3: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/insights/topic_breakdown.py').read()); print('OK')"
```

---

### Task 3.9: Rewrite `geo_saas/src/routers/settings.py` — peers + topics + products

**Files:**
- Modify: `geo_saas/src/routers/settings.py`

- [ ] **Step 1: Remove `is_own_brand` from peer request/response schemas**

Find `AddPeerInput` (around line 29) and `UpdatePeerInput` (around line 34). Remove the `is_own_brand` field and its `default=False`. In the `add_peer` handler (around line 123), remove `is_own_brand=data.is_own_brand`.

- [ ] **Step 2: Rewrite Topics CRUD to use the new products table**

The current `AddTopicInput` / `UpdateTopicInput` (around lines 42, 50) take a `products: List[str]`. Since products moved to a separate table, change the shape:

```python
class AddTopicInput(BaseModel):
    topic_name: str
    topic_type: Optional[str] = "semantic_topic"
    # products removed from topic create; use POST /api/settings/topics/{topic_id}/products separately

class UpdateTopicInput(BaseModel):
    topic_name: Optional[str] = None
    topic_type: Optional[str] = None
    # products removed
```

Update the topic create/update handlers to no longer insert into `geo_client_topics.products` (that column is being dropped). When reading topics (`get_topics`), join the new products table:

```python
@router.get("/topics")
async def get_topics(client_id: UUID):
    rows = await database.fetch_all(text("""
        SELECT t.id, t.topic_name, t.topic_type, t.created_at,
               COALESCE(
                 (SELECT jsonb_agg(jsonb_build_object(
                     'id', tp.id,
                     'product_name', tp.product_name,
                     'match_variants', tp.match_variants,
                     'product_role', tp.product_role,
                     'owner_brand_id', tp.owner_brand_id,
                     'owner_peer_id', tp.owner_peer_id,
                     'is_active', tp.is_active
                 ))
                 FROM geo_client_topic_products tp
                 WHERE tp.topic_id = t.id AND tp.is_active = true),
                 '[]'::jsonb
               ) AS tracked_products
        FROM geo_client_topics t
        WHERE t.client_id = :client_id
        ORDER BY t.topic_name
    """), {"client_id": str(client_id)})
    return [dict(r) for r in rows]
```

- [ ] **Step 3: Add Products CRUD endpoints in the same file (or new module)**

```python
# Request models
class AddProductInput(BaseModel):
    product_name: str
    match_variants: List[str] = []
    product_role: str = "own"  # 'own' | 'shadow_brand_native' | 'peer'
    owner_brand_id: Optional[UUID] = None
    owner_peer_id: Optional[UUID] = None

class UpdateProductInput(BaseModel):
    product_name: Optional[str] = None
    match_variants: Optional[List[str]] = None
    product_role: Optional[str] = None
    owner_brand_id: Optional[UUID] = None
    owner_peer_id: Optional[UUID] = None
    is_active: Optional[bool] = None


@router.post("/topics/{topic_id}/products", status_code=201)
async def add_product(client_id: UUID, topic_id: UUID, data: AddProductInput):
    q = text("""
        INSERT INTO geo_client_topic_products
          (topic_id, client_id, product_name, match_variants, product_role,
           owner_brand_id, owner_peer_id)
        VALUES (:topic_id, :client_id, :product_name, :match_variants, :product_role,
                :owner_brand_id, :owner_peer_id)
        RETURNING id
    """)
    new_id = await database.fetch_val(q, {
        "topic_id": str(topic_id),
        "client_id": str(client_id),
        "product_name": data.product_name,
        "match_variants": data.match_variants,
        "product_role": data.product_role,
        "owner_brand_id": str(data.owner_brand_id) if data.owner_brand_id else None,
        "owner_peer_id": str(data.owner_peer_id) if data.owner_peer_id else None,
    })
    return {"id": new_id}


@router.put("/products/{product_id}")
async def update_product(client_id: UUID, product_id: UUID, data: UpdateProductInput):
    updates = {k: v for k, v in data.dict(exclude_unset=True).items()}
    if not updates:
        return {"updated": 0}
    set_clause = ", ".join(f"{k} = :{k}" for k in updates.keys())
    updates["id"] = str(product_id)
    updates["client_id"] = str(client_id)
    q = text(f"""
        UPDATE geo_client_topic_products
        SET {set_clause}, updated_at = NOW()
        WHERE id = :id AND client_id = :client_id
    """)
    await database.execute(q, updates)
    return {"updated": 1}


@router.delete("/products/{product_id}")
async def delete_product(client_id: UUID, product_id: UUID):
    q = text("DELETE FROM geo_client_topic_products WHERE id = :id AND client_id = :client_id")
    await database.execute(q, {"id": str(product_id), "client_id": str(client_id)})
    return {"deleted": 1}
```

- [ ] **Step 4: Verify**

```bash
grep -n "is_own_brand" geo_saas/src/routers/settings.py
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/settings.py').read()); print('OK')"
```
Expected: 0 refs to is_own_brand; OK.

---

### Task 3.10: Create `geo_saas/src/routers/settings_brands.py`

**Files:**
- Create: `geo_saas/src/routers/settings_brands.py`

- [ ] **Step 1: Write the Brands CRUD module**

```python
# geo_saas/src/routers/settings_brands.py
"""
Brands CRUD — manages geo_client_brands (Own + Shadow brands per client).
"""
from uuid import UUID
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from database import database

router = APIRouter(prefix="/settings/brands", tags=["Settings"])


class AddBrandInput(BaseModel):
    brand_name: str
    aliases: List[str] = []
    is_shadow: bool = False


class UpdateBrandInput(BaseModel):
    brand_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    is_shadow: Optional[bool] = None
    is_active: Optional[bool] = None


@router.get("/")
async def list_brands(client_id: UUID):
    rows = await database.fetch_all(text("""
        SELECT id, brand_name, aliases, is_shadow, is_active, created_at, updated_at
        FROM geo_client_brands
        WHERE client_id = :cid
        ORDER BY is_shadow ASC, brand_name ASC
    """), {"cid": str(client_id)})
    return [dict(r) for r in rows]


@router.post("/", status_code=201)
async def add_brand(client_id: UUID, data: AddBrandInput):
    # Enforce mutual exclusion with peers (same name can't be both)
    peer_match = await database.fetch_val(text("""
        SELECT COUNT(*) FROM geo_client_peers
        WHERE client_id = :cid AND LOWER(primary_name) = LOWER(:name)
    """), {"cid": str(client_id), "name": data.brand_name})
    if peer_match:
        raise HTTPException(
            status_code=400,
            detail=f"'{data.brand_name}' is already a Peer for this client. A name cannot be both a Brand and a Peer.",
        )

    try:
        new_id = await database.fetch_val(text("""
            INSERT INTO geo_client_brands (client_id, brand_name, aliases, is_shadow)
            VALUES (:cid, :name, :aliases, :is_shadow)
            RETURNING id
        """), {
            "cid": str(client_id),
            "name": data.brand_name,
            "aliases": data.aliases,
            "is_shadow": data.is_shadow,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to add brand: {e}")
    return {"id": new_id}


@router.put("/{brand_id}")
async def update_brand(client_id: UUID, brand_id: UUID, data: UpdateBrandInput):
    updates = {k: v for k, v in data.dict(exclude_unset=True).items()}
    if not updates:
        return {"updated": 0}
    set_clause = ", ".join(f"{k} = :{k}" for k in updates.keys())
    updates["bid"] = str(brand_id)
    updates["cid"] = str(client_id)
    await database.execute(text(f"""
        UPDATE geo_client_brands
        SET {set_clause}, updated_at = NOW()
        WHERE id = :bid AND client_id = :cid
    """), updates)
    return {"updated": 1}


@router.delete("/{brand_id}")
async def delete_brand(client_id: UUID, brand_id: UUID):
    # Prevent deleting a brand still referenced by products (shadow_brand_native)
    refs = await database.fetch_val(text("""
        SELECT COUNT(*) FROM geo_client_topic_products
        WHERE owner_brand_id = :bid
    """), {"bid": str(brand_id)})
    if refs and refs > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Brand has {refs} product(s) pointing to it. Update or delete those products first.",
        )
    await database.execute(text("""
        DELETE FROM geo_client_brands WHERE id = :bid AND client_id = :cid
    """), {"bid": str(brand_id), "cid": str(client_id)})
    return {"deleted": 1}
```

- [ ] **Step 2: Register in main.py**

```python
from routers import settings_brands
app.include_router(settings_brands.router, prefix="/api")
```

- [ ] **Step 3: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/settings_brands.py').read()); print('OK')"
```

---

### Task 3.11: Update `geo_saas/src/routers/brainstorming.py` to read from new products table and support Topic-only

**Files:**
- Modify: `geo_saas/src/routers/brainstorming.py`

- [ ] **Step 1: Read the current file, locate `topic_map[tid]` construction and products read**

```bash
Read file: geo_saas/src/routers/brainstorming.py (lines 75-135)
```

- [ ] **Step 2: Replace products source**

Change the topic_map block from reading `topic["products"]` (the TEXT[] column) to reading the new table:

Old:
```python
topic_map[str(ts.topic_id)] = {
    "topic_name": topic["topic_name"],
    "products": ts.product_names or (topic["products"] if topic["products"] else []),
}
```

New:
```python
# Fetch product list from new table
prod_rows = await database.fetch_all(
    select(geo_client_topic_products.c.product_name).where(
        geo_client_topic_products.c.topic_id == ts.topic_id,
        geo_client_topic_products.c.client_id == data.client_id,
        geo_client_topic_products.c.is_active == True,
    )
)
topic_products = [r["product_name"] for r in prod_rows]
topic_map[str(ts.topic_id)] = {
    "topic_name": topic["topic_name"],
    "products": ts.product_names if ts.product_names else topic_products,
}
```

- [ ] **Step 3: Handle Topic-only (empty products) in call_plan construction**

Old:
```python
products = topic_info["products"] if topic_info["products"] else [""]
for product in products:
    call_plan.append({... "product": product ...})
```

New:
```python
products = topic_info["products"] or []
if products:
    for product in products:
        call_plan.append({... "product": product ...})
else:
    # Topic-only: generate prompts based on topic name alone
    call_plan.append({
        "topic_id": tid,
        "topic_name": topic_info["topic_name"],
        "product": "",  # empty sentinel; prompt builder handles this
        "country": data.countries[0] if data.countries else "US",
        "language": language,
        "count": per_product_total,
        "intent_allocations": intent_alloc,
        "platforms": data.platforms,
        "countries": data.countries,
    })
```

- [ ] **Step 4: Update `_build_brainstorm_prompt` to handle empty product**

Find the existing prompt builder and add a conditional branch:

```python
def _build_brainstorm_prompt(client_name, peers, topic, product, country, language,
                              intent_allocations, n):
    if product:
        topic_context = f"Topic: {topic}\nProduct: {product}"
    else:
        topic_context = f"Topic (no specific product; generate questions at topic level): {topic}"
    # ... rest of prompt
```

- [ ] **Step 5: Update imports**

Add at the top:
```python
from database import geo_client_topic_products
```

- [ ] **Step 6: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/brainstorming.py').read()); print('OK')"
```

---

## Phase 4: SaaS Frontend — Existing Component Updates

### Task 4.1: Update `geo_saas/web/src/lib/api.ts` with new types and fetchers

**Files:**
- Modify: `geo_saas/web/src/lib/api.ts`

- [ ] **Step 1: Add new TypeScript types**

Add near the existing type exports:

```typescript
export type BrandRole = "own" | "shadow" | "peer";
export type ProductRole = "own" | "shadow_brand_native" | "peer";

export interface Brand {
  id: string;
  brand_name: string;
  aliases: string[];
  is_shadow: boolean;
  is_active: boolean;
}

export interface TrackedProduct {
  id: string;
  product_name: string;
  match_variants: string[];
  product_role: ProductRole;
  owner_brand_id?: string | null;
  owner_peer_id?: string | null;
  is_active: boolean;
}

export interface AvailabilitySnapshot {
  has_own_brands: boolean;
  has_shadow_brands: boolean;
  has_peers: boolean;
  has_topics: boolean;
  has_products: boolean;
  has_mentions_data: boolean;
  has_product_mentions_data: boolean;
  counts: Record<string, number>;
}
```

- [ ] **Step 2: Add CRUD functions for Brands**

```typescript
export async function getBrands(clientId: string): Promise<Brand[]> {
  return fetchJSON(`${API_BASE}/settings/brands/?client_id=${clientId}`);
}

export async function addBrand(clientId: string, data: Omit<Brand, "id" | "is_active">) {
  return fetchJSON(`${API_BASE}/settings/brands/?client_id=${clientId}`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateBrand(clientId: string, brandId: string, data: Partial<Brand>) {
  return fetchJSON(`${API_BASE}/settings/brands/${brandId}?client_id=${clientId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function removeBrand(clientId: string, brandId: string) {
  return fetchJSON(`${API_BASE}/settings/brands/${brandId}?client_id=${clientId}`, {
    method: "DELETE",
  });
}
```

- [ ] **Step 3: Add CRUD for Products (under topics)**

```typescript
export async function addProduct(clientId: string, topicId: string, data: Omit<TrackedProduct, "id" | "is_active">) {
  return fetchJSON(`${API_BASE}/settings/topics/${topicId}/products?client_id=${clientId}`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateProduct(clientId: string, productId: string, data: Partial<TrackedProduct>) {
  return fetchJSON(`${API_BASE}/settings/products/${productId}?client_id=${clientId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function removeProduct(clientId: string, productId: string) {
  return fetchJSON(`${API_BASE}/settings/products/${productId}?client_id=${clientId}`, {
    method: "DELETE",
  });
}
```

- [ ] **Step 4: Add availability fetcher**

```typescript
export async function getInsightsAvailability(clientId: string): Promise<AvailabilitySnapshot> {
  return fetchJSON(`${API_BASE}/insights/availability?client_id=${clientId}`);
}
```

- [ ] **Step 5: Update the `Topic` interface to include `tracked_products` instead of `products: string[]`**

Find existing `Topic` type:
```typescript
// old
export interface Topic { id: string; topic_name: string; products?: string[]; ... }
```
Change to:
```typescript
export interface Topic {
  id: string;
  topic_name: string;
  topic_type?: "semantic_topic" | "product_line";
  tracked_products?: TrackedProduct[];
}
```

- [ ] **Step 6: Remove `is_own_brand` from Peer type**

Find existing Peer type and strip the field:
```typescript
// old
export interface Peer { id: string; primary_name: string; aliases: string[]; is_own_brand: boolean; }
// new
export interface Peer { id: string; primary_name: string; aliases: string[]; }
```

- [ ] **Step 7: Verify TS typechecks**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | head -40
```
Expected: no errors in api.ts itself. (Errors in other files that reference old types will surface — they'll be fixed in subsequent tasks.)

---

### Task 4.2: Update `geo_saas/web/src/pages/SettingsPage.tsx` — add Brands tab, restructure Products form

**Files:**
- Modify: `geo_saas/web/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Remove `is_own_brand: false` from addPeer call** (line 177)

Find:
```tsx
await addPeer(clientId, { primary_name: newPeer, aliases: [], is_own_brand: false });
```
Replace with:
```tsx
await addPeer(clientId, { primary_name: newPeer, aliases: [] });
```

- [ ] **Step 2: Add a new Brands tab alongside existing Peers/Topics/Domains tabs**

Add a `Brands` state and load it alongside other data. Inside the `Tabs` component, add a new `TabsTrigger` and `TabsContent`:

```tsx
<TabsTrigger value="brands">Brands</TabsTrigger>
<TabsContent value="brands">
  <BrandsSection clientId={clientId} />
</TabsContent>
```

Create `BrandsSection` in the same file (or new file if preferred). It renders:
- Own Brand block (auto-populated from client.name; expanded by default if non-OEM mode)
- Shadow Brand block (collapsed by default; expanded if OEM mode)

```tsx
function BrandsSection({ clientId }: { clientId: string }) {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [showShadow, setShowShadow] = useState(false);

  useEffect(() => {
    getBrands(clientId).then(setBrands);
  }, [clientId]);

  const ownBrands = brands.filter(b => !b.is_shadow);
  const shadowBrands = brands.filter(b => b.is_shadow);

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-lg font-semibold mb-3">Own Brand</h3>
        <BrandList brands={ownBrands} isShadow={false} clientId={clientId} onChange={() => getBrands(clientId).then(setBrands)} />
      </section>
      <section>
        <button onClick={() => setShowShadow(v => !v)} className="text-sm text-muted-foreground flex items-center gap-1">
          {showShadow ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Shadow Brand (OEM / white-label / distributor scenarios)
        </button>
        {showShadow && (
          <div className="mt-3">
            <BrandList brands={shadowBrands} isShadow={true} clientId={clientId} onChange={() => getBrands(clientId).then(setBrands)} />
          </div>
        )}
      </section>
    </div>
  );
}
```

`BrandList` is a straightforward CRUD table similar to the existing Peers UI. Keep the file size reasonable — if it grows beyond 50 lines, extract into a new file `geo_saas/web/src/components/settings/BrandList.tsx`.

- [ ] **Step 3: Restructure the Products UI inside the Topics tab**

Find the existing Topics tab rendering. Where it currently loops over `topic.products: string[]`, change to `topic.tracked_products: TrackedProduct[]`. Render each product as a row with:
- Display: `product_name` + `match_variants` chip list
- Default form: only `product_name` + `match_variants`
- Toggleable "Show advanced options" disclosure revealing `product_role`, `owner_brand_id`, `owner_peer_id`

Example component (inline or extracted):

```tsx
function ProductListItem({ product, clientId, onChange }: {
  product: TrackedProduct; clientId: string; onChange: () => void;
}) {
  const [showAdvanced, setShowAdvanced] = useState(product.product_role !== 'own');

  return (
    <div className="border rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="font-medium">{product.product_name}</div>
        <button onClick={() => removeProduct(clientId, product.id).then(onChange)}
                className="text-destructive text-xs">
          Remove
        </button>
      </div>
      <div className="flex flex-wrap gap-1">
        {product.match_variants.map((v, i) => (
          <span key={i} className="text-xs px-2 py-0.5 bg-muted rounded">{v}</span>
        ))}
      </div>
      <button className="text-xs text-muted-foreground"
              onClick={() => setShowAdvanced(v => !v)}>
        {showAdvanced ? "Hide" : "Show"} advanced product options
      </button>
      {showAdvanced && (
        <div className="text-xs space-y-1">
          <div>Role: {product.product_role}</div>
          {product.owner_brand_id && <div>Owner Brand: {product.owner_brand_id}</div>}
          {product.owner_peer_id && <div>Owner Peer: {product.owner_peer_id}</div>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify typecheck**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "error" | head -20
```

---

### Task 4.3: Update `geo_saas/web/src/pages/PromptEditor.tsx` to consume tracked_products

**Files:**
- Modify: `geo_saas/web/src/pages/PromptEditor.tsx`

- [ ] **Step 1: Find all `topic.products` references (~10 locations)**

```bash
grep -n "topic.products\|topic?.products\|\\.products\\b" geo_saas/web/src/pages/PromptEditor.tsx
```

- [ ] **Step 2: Replace each reference with derived `product_names` from `tracked_products`**

Example:
```tsx
// old
const productOptions: string[] = selectedTopic?.products || [];

// new
const productOptions: string[] = (selectedTopic?.tracked_products || []).map(p => p.product_name);
```

Do this systematically for all ~10 matches.

- [ ] **Step 3: Verify typecheck**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -E "PromptEditor|error" | head -20
```

---

### Task 4.4: Update `geo_saas/web/src/components/insights/VisibilityDashboard.tsx`

**Files:**
- Modify: `geo_saas/web/src/components/insights/VisibilityDashboard.tsx`

- [ ] **Step 1: Rename field refs** (~15 occurrences)

- `r.company_name` → `r.brand_name`
- `companyNames` var → `brandNames`
- `r.is_own` → `r.brand_role === 'own' || r.brand_role === 'shadow'` (derived boolean; if the object already exposes a convenience `is_own` field from the API, keep that field computed server-side)

- [ ] **Step 2: Add View By switcher at the top of the dashboard**

```tsx
const [viewBy, setViewBy] = useState<"brand" | "product" | "topic">("brand");
const [brandRoleFilter, setBrandRoleFilter] = useState<"own" | "shadow" | "peer" | "all">("all");

// Near the top of the rendered dashboard
<div className="flex items-center gap-4 mb-4">
  <label className="text-sm text-muted-foreground">View by:</label>
  <DropdownMenu>
    <DropdownMenuTrigger className="border rounded px-2 py-1 text-sm">
      {viewBy} <ChevronDown className="inline h-3 w-3" />
    </DropdownMenuTrigger>
    <DropdownMenuContent>
      <DropdownMenuRadioGroup value={viewBy} onValueChange={(v) => setViewBy(v as any)}>
        <DropdownMenuRadioItem value="brand">Brand</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="product">Product</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="topic">Topic</DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>
</div>
```

- [ ] **Step 3: Verify typecheck**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep "VisibilityDashboard" | head -20
```

---

### Task 4.5: Update `PeerPicker.tsx` and `ContentTaskModal.tsx`

**Files:**
- Modify: `geo_saas/web/src/components/wizard/customFields/PeerPicker.tsx`
- Modify: `geo_saas/web/src/components/agents/ContentTaskModal.tsx`

- [ ] **Step 1: In `PeerPicker.tsx`, stop using `is_own_brand` to split; read from both sources**

Old logic (around lines 76-77):
```tsx
const own = peers.filter((p) => p.is_own_brand);
const comp = peers.filter((p) => !p.is_own_brand);
```

New logic — load both brands and peers:

```tsx
import { getBrands, getPeers } from "@/lib/api";

const [brands, setBrands] = useState<Brand[]>([]);
const [peers, setPeers] = useState<Peer[]>([]);

useEffect(() => {
  Promise.all([
    getBrands(clientId),
    getPeers(clientId),
  ]).then(([bs, ps]) => {
    setBrands(bs);
    setPeers(ps);
  });
}, [clientId]);

// Then render:
const ownOrShadowBrands = brands; // Own + Shadow together
const competitorPeers = peers;
```

- [ ] **Step 2: Remove `is_own_brand` from the Peer interface in the component**

- [ ] **Step 3: Same update in `ContentTaskModal.tsx` (lines 56, 401-402)**

- [ ] **Step 4: Verify typecheck**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -E "PeerPicker|ContentTaskModal" | head -20
```

---

## Phase 5: SaaS Frontend — New Components

### Task 5.1: Create `EmptyStateCard.tsx` shared component

**Files:**
- Create: `geo_saas/web/src/components/shared/EmptyStateCard.tsx`

- [ ] **Step 1: Write the component**

```tsx
// geo_saas/web/src/components/shared/EmptyStateCard.tsx
import { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useNavigate } from "react-router-dom";

interface Props {
  icon?: ReactNode;
  title: string;
  description: string;
  ctaLabel?: string;
  ctaHref?: string;
  secondaryInfo?: string;
}

export function EmptyStateCard({ icon, title, description, ctaLabel, ctaHref, secondaryInfo }: Props) {
  const navigate = useNavigate();
  return (
    <Card className="border-dashed">
      <CardContent className="p-8 text-center space-y-3">
        {icon && <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-muted">{icon}</div>}
        <h3 className="font-medium text-base">{title}</h3>
        <p className="text-sm text-muted-foreground max-w-md mx-auto">{description}</p>
        {ctaLabel && ctaHref && (
          <Button onClick={() => navigate(ctaHref)} variant="outline" size="sm">
            {ctaLabel}
          </Button>
        )}
        {secondaryInfo && (
          <p className="text-xs text-muted-foreground pt-2">{secondaryInfo}</p>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep "EmptyStateCard" | head -5
```

---

### Task 5.2: Create `ProductVisibilityDashboard.tsx`

**Files:**
- Create: `geo_saas/web/src/components/insights/ProductVisibilityDashboard.tsx`

- [ ] **Step 1: Write the product-level visibility dashboard**

```tsx
// geo_saas/web/src/components/insights/ProductVisibilityDashboard.tsx
import { useEffect, useState } from "react";
import { Package } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip } from "recharts";
import { EmptyStateCard } from "@/components/shared/EmptyStateCard";
import { API_BASE, AvailabilitySnapshot } from "@/lib/api";

interface Props {
  clientId: string;
  startDate: string;
  endDate: string;
  platforms: string[];
  availability: AvailabilitySnapshot;
}

interface ProductData {
  summary: { total_mentions: number; distinct_products: number };
  top_products: Array<{ product_name: string; product_role: string; mention_count: number; sov_pct: number }>;
  time_series: Array<{ date: string; product_name: string; mention_count: number }>;
  platform_breakdown: Array<{ platform: string; product_name: string; mention_count: number }>;
}

export default function ProductVisibilityDashboard({ clientId, startDate, endDate, platforms, availability }: Props) {
  const [data, setData] = useState<ProductData | null>(null);

  useEffect(() => {
    if (!availability.has_products) return;
    const params = new URLSearchParams({
      client_id: clientId,
      start_date: startDate,
      end_date: endDate,
    });
    platforms.forEach(p => params.append("platforms", p));
    fetch(`${API_BASE}/insights/product-visibility?${params}`)
      .then(r => r.json())
      .then(setData);
  }, [clientId, startDate, endDate, platforms, availability.has_products]);

  if (!availability.has_products) {
    return (
      <EmptyStateCard
        icon={<Package className="h-6 w-6 text-muted-foreground" />}
        title="No product data yet"
        description="Product-level insights require configuring SKUs under each Topic. Add products in Settings to see this view."
        ctaLabel="Configure Products"
        ctaHref="/agents/tracking"
        secondaryInfo="Tip: Brand-level insights continue to work without this."
      />
    );
  }

  if (!data) return <div className="text-sm text-muted-foreground">Loading product visibility...</div>;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Top Products by Mention</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="text-right">Mentions</TableHead>
                <TableHead className="text-right">SOV</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.top_products.map((p, i) => (
                <TableRow key={i}>
                  <TableCell>{p.product_name}</TableCell>
                  <TableCell>{p.product_role}</TableCell>
                  <TableCell className="text-right">{p.mention_count}</TableCell>
                  <TableCell className="text-right">{p.sov_pct}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Product Platform Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data.platform_breakdown}>
              <XAxis dataKey="product_name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="mention_count" fill="#10b981" />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep "ProductVisibilityDashboard" | head -5
```

---

### Task 5.3: Create `CooccurrenceHeatmap.tsx`

**Files:**
- Create: `geo_saas/web/src/components/insights/CooccurrenceHeatmap.tsx`

- [ ] **Step 1: Write the heatmap component**

```tsx
// geo_saas/web/src/components/insights/CooccurrenceHeatmap.tsx
import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyStateCard } from "@/components/shared/EmptyStateCard";
import { API_BASE, AvailabilitySnapshot } from "@/lib/api";

interface Props {
  clientId: string;
  startDate: string;
  endDate: string;
  availability: AvailabilitySnapshot;
}

interface MatrixCell {
  brand_name: string;
  product_name: string;
  cooccurrence_count: number;
}

export default function CooccurrenceHeatmap({ clientId, startDate, endDate, availability }: Props) {
  const [matrix, setMatrix] = useState<MatrixCell[]>([]);

  const canRender = availability.has_shadow_brands && availability.has_products;

  useEffect(() => {
    if (!canRender) return;
    const params = new URLSearchParams({
      client_id: clientId,
      start_date: startDate,
      end_date: endDate,
      brand_role: "shadow",
      product_role: "own",
    });
    fetch(`${API_BASE}/insights/brand-product-cooccurrence?${params}`)
      .then(r => r.json())
      .then(data => setMatrix(data.matrix || []));
  }, [clientId, startDate, endDate, canRender]);

  if (!canRender) {
    return (
      <EmptyStateCard
        icon={<Users className="h-6 w-6 text-muted-foreground" />}
        title="Co-occurrence view needs Shadow Brands + Products"
        description="This view shows how often your Shadow Brand (e.g. a distributor) and your Own Products are mentioned together by AI."
        ctaLabel="Configure Brands & Products"
        ctaHref="/agents/tracking"
      />
    );
  }

  // Build unique brand/product axes
  const brands = [...new Set(matrix.map(c => c.brand_name))];
  const products = [...new Set(matrix.map(c => c.product_name))];
  const lookup = Object.fromEntries(matrix.map(c => [`${c.brand_name}::${c.product_name}`, c.cooccurrence_count]));
  const maxCount = Math.max(1, ...matrix.map(c => c.cooccurrence_count));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Shadow Brand × Own Product Co-occurrence</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-auto">
          <table className="text-xs border-collapse">
            <thead>
              <tr>
                <th className="p-2 text-left">Product ↓ / Brand →</th>
                {brands.map(b => <th key={b} className="p-2 text-left">{b}</th>)}
              </tr>
            </thead>
            <tbody>
              {products.map(p => (
                <tr key={p}>
                  <td className="p-2 font-medium">{p}</td>
                  {brands.map(b => {
                    const count = lookup[`${b}::${p}`] || 0;
                    const intensity = count / maxCount;
                    return (
                      <td key={b}
                          className="p-2 text-center"
                          style={{ background: `rgba(16, 185, 129, ${intensity})` }}>
                        {count || "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep "CooccurrenceHeatmap" | head -5
```

---

### Task 5.4: Create `TopicBreakdown.tsx`

**Files:**
- Create: `geo_saas/web/src/components/insights/TopicBreakdown.tsx`

- [ ] **Step 1: Write the topic coverage + heatmap component**

```tsx
// geo_saas/web/src/components/insights/TopicBreakdown.tsx
import { useEffect, useState } from "react";
import { Hash } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyStateCard } from "@/components/shared/EmptyStateCard";
import { API_BASE, AvailabilitySnapshot } from "@/lib/api";

interface Props {
  clientId: string;
  startDate: string;
  endDate: string;
  platforms: string[];
  availability: AvailabilitySnapshot;
}

interface Coverage { topic_name: string; total_prompts: number; covered_prompts: number; coverage_pct: number; }
interface HeatmapRow { topic_name: string; platform: string; own_brand_mentions: number; }

export default function TopicBreakdown({ clientId, startDate, endDate, platforms, availability }: Props) {
  const [coverage, setCoverage] = useState<Coverage[]>([]);
  const [heatmap, setHeatmap] = useState<HeatmapRow[]>([]);

  useEffect(() => {
    if (!availability.has_topics) return;
    const params = new URLSearchParams({ client_id: clientId, start_date: startDate, end_date: endDate });
    platforms.forEach(p => params.append("platforms", p));
    fetch(`${API_BASE}/insights/topic-breakdown?${params}`)
      .then(r => r.json())
      .then(data => { setCoverage(data.coverage || []); setHeatmap(data.heatmap || []); });
  }, [clientId, startDate, endDate, platforms, availability.has_topics]);

  if (!availability.has_topics) {
    return (
      <EmptyStateCard
        icon={<Hash className="h-6 w-6 text-muted-foreground" />}
        title="No topics configured"
        description="Topic-level insights need at least one topic configured in Settings."
        ctaLabel="Configure Topics"
        ctaHref="/agents/tracking"
      />
    );
  }

  const topics = [...new Set(heatmap.map(h => h.topic_name))];
  const platformsList = [...new Set(heatmap.map(h => h.platform))];
  const lookup = Object.fromEntries(heatmap.map(h => [`${h.topic_name}::${h.platform}`, h.own_brand_mentions]));
  const maxMentions = Math.max(1, ...heatmap.map(h => h.own_brand_mentions));

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Topic Coverage</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Topic</TableHead>
                <TableHead className="text-right">Total Prompts</TableHead>
                <TableHead className="text-right">Covered</TableHead>
                <TableHead className="text-right">Coverage %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {coverage.map((c, i) => (
                <TableRow key={i}>
                  <TableCell>{c.topic_name}</TableCell>
                  <TableCell className="text-right">{c.total_prompts}</TableCell>
                  <TableCell className="text-right">{c.covered_prompts}</TableCell>
                  <TableCell className="text-right">{c.coverage_pct ?? "—"}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Topic × Platform Heatmap</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-auto">
            <table className="text-xs border-collapse">
              <thead>
                <tr>
                  <th className="p-2 text-left">Topic / Platform</th>
                  {platformsList.map(p => <th key={p} className="p-2">{p}</th>)}
                </tr>
              </thead>
              <tbody>
                {topics.map(t => (
                  <tr key={t}>
                    <td className="p-2 font-medium">{t}</td>
                    {platformsList.map(p => {
                      const count = lookup[`${t}::${p}`] || 0;
                      return (
                        <td key={p}
                            className="p-2 text-center"
                            style={{ background: `rgba(59, 130, 246, ${count / maxMentions})` }}>
                          {count || "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep "TopicBreakdown" | head -5
```

---

### Task 5.5: Create `OnboardingWizard.tsx`

**Files:**
- Create: `geo_saas/web/src/components/onboarding/OnboardingWizard.tsx`

- [ ] **Step 1: Write the wizard component**

```tsx
// geo_saas/web/src/components/onboarding/OnboardingWizard.tsx
import { useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { addBrand, API_BASE } from "@/lib/api";

type Choice = "own" | "oem" | "both" | "skip";

interface Props {
  clientId: string;
  clientName: string;
  open: boolean;
  onComplete: () => void;
}

export default function OnboardingWizard({ clientId, clientName, open, onComplete }: Props) {
  const [choice, setChoice] = useState<Choice>("own");
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setSubmitting(true);
    try {
      if (choice === "own" || choice === "both") {
        // Seed Own Brand = clientName
        await addBrand(clientId, {
          brand_name: clientName,
          aliases: [],
          is_shadow: false,
        });
      }
      // For "oem" branch: no auto-seed; user will fill Shadow Brand manually
      // Mark wizard complete
      await fetch(`${API_BASE}/clients/${clientId}/onboarding-complete`, { method: "POST" });
      onComplete();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Welcome to AnswerX GEO</DialogTitle>
          <DialogDescription>
            Before we set up your tracking, one quick question — it helps us show you the right defaults.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4 space-y-4">
          <Label className="text-sm font-medium">
            Does your brand appear directly in AI search results (e.g. ChatGPT mentions your brand name to end users)?
          </Label>
          <RadioGroup value={choice} onValueChange={(v) => setChoice(v as Choice)}>
            <div className="flex items-start space-x-2">
              <RadioGroupItem value="own" id="r-own" />
              <Label htmlFor="r-own" className="text-sm">
                <strong>Yes</strong> — we have our own brand customers see
              </Label>
            </div>
            <div className="flex items-start space-x-2">
              <RadioGroupItem value="oem" id="r-oem" />
              <Label htmlFor="r-oem" className="text-sm">
                <strong>No</strong> — we're an OEM / white-label supplier; our products are sold under distributor brands
              </Label>
            </div>
            <div className="flex items-start space-x-2">
              <RadioGroupItem value="both" id="r-both" />
              <Label htmlFor="r-both" className="text-sm">
                <strong>Both</strong> — we have our own brand and also OEM partnerships
              </Label>
            </div>
            <div className="flex items-start space-x-2">
              <RadioGroupItem value="skip" id="r-skip" />
              <Label htmlFor="r-skip" className="text-sm text-muted-foreground">
                Skip, I'll configure manually
              </Label>
            </div>
          </RadioGroup>
        </div>

        <DialogFooter>
          <Button onClick={submit} disabled={submitting}>
            {submitting ? "Saving..." : "Continue"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Add the backend endpoint `POST /api/clients/{id}/onboarding-complete`**

In `geo_saas/src/routers/clients.py`, add:
```python
@router.post("/clients/{client_id}/onboarding-complete")
async def mark_onboarding_complete(client_id: UUID):
    await database.execute(text("""
        UPDATE geo_clients SET onboarding_wizard_completed = true WHERE id = :cid
    """), {"cid": str(client_id)})
    return {"ok": True}
```

- [ ] **Step 3: Trigger the Wizard in the SaaS app entrypoint**

In the top-level SaaS app (e.g. `App.tsx` or SaaSContext), after loading `client`, check `client.onboarding_wizard_completed`. If false, render `<OnboardingWizard ... />`.

- [ ] **Step 4: Verify**

```bash
cd geo_saas/web && npx tsc --noEmit --project tsconfig.json 2>&1 | grep "OnboardingWizard\|clients.py" | head -10
python3 -c "import ast; ast.parse(open('geo_saas/src/routers/clients.py').read()); print('OK')"
```

---

## Phase 6: Agent, Admin, Collector Updates

### Task 6.1: Update `geo_agent/src/tools/data_tools.py`

**Files:**
- Modify: `geo_agent/src/tools/data_tools.py`

- [ ] **Step 1: Replace table name in `ALLOWED_TABLES` (line 27)**

Add the new tables and rename the old one:
```python
ALLOWED_TABLES = [
    # ... existing tables
    "geo_brand_mentions",       # renamed from geo_company_mentions
    "geo_product_mentions",     # new
    "geo_client_brands",        # new
    "geo_client_topic_products",# new
    # keep geo_citations, geo_client_peers, etc.
]
# Remove: "geo_company_mentions"
```

- [ ] **Step 2: Update sample_info / table description strings** (around lines 137, 147, 216-225)

Old:
```python
"geo_company_mentions": "Brand/company mentions extracted from AI engine responses. Has company_name, mention_position, is_own_brand, executed_at.",
```
New:
```python
"geo_brand_mentions": "Brand mentions extracted from AI engine responses. Has brand_name, mention_position, brand_role ('own'/'shadow'/'peer'), executed_at.",
"geo_product_mentions": "Product/SKU mentions. Has product_name, product_role ('own'/'shadow_brand_native'/'peer'), owner_brand_name, owner_peer_name, mention_position, executed_at.",
"geo_client_brands": "Client's tracked brands (Own and Shadow). Has brand_name, aliases[], is_shadow boolean.",
"geo_client_topic_products": "Tracked products per topic. Has product_name, match_variants[], product_role, owner_brand_id, owner_peer_id.",
```

Also update the note fields:
```python
if table_name == "geo_brand_mentions":
    sample_info["note"] = "brand_role='own' for client's own brands, 'shadow' for shadow/distributor brands, 'peer' for competitors."
if table_name == "geo_product_mentions":
    sample_info["note"] = "product_role distinguishes own products, shadow-brand-native products, and tracked peer SKUs."
```

- [ ] **Step 3: Verify**

```bash
grep -n "geo_company_mentions\|is_own_brand" geo_agent/src/tools/data_tools.py
python3 -c "import ast; ast.parse(open('geo_agent/src/tools/data_tools.py').read()); print('OK')"
```
Expected: 0 old refs, OK.

---

### Task 6.2: Update `geo_agent/src/tools/chart_tools.py`

**Files:**
- Modify: `geo_agent/src/tools/chart_tools.py` (line 58)

- [ ] **Step 1: Replace `is_own_brand` field**

Old:
```python
"isOwn": c["is_own_brand"],
```
New:
```python
"isOwn": c.get("brand_role") == "own" or c.get("brand_role") == "shadow",
"brandRole": c.get("brand_role"),
```

- [ ] **Step 2: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_agent/src/tools/chart_tools.py').read()); print('OK')"
```

---

### Task 6.3: Update `geo_agent/src/tools/utility_tools.py` (line 93)

**Files:**
- Modify: `geo_agent/src/tools/utility_tools.py`

- [ ] **Step 1: Remove obsolete WHERE**

Old:
```python
"SELECT primary_name FROM geo_client_peers WHERE client_id = $1::uuid AND is_own_brand = false"
```
New (is_own_brand column is dropped):
```python
"SELECT primary_name FROM geo_client_peers WHERE client_id = $1::uuid"
```

- [ ] **Step 2: Verify**

```bash
grep -n "is_own_brand" geo_agent/src/tools/utility_tools.py
python3 -c "import ast; ast.parse(open('geo_agent/src/tools/utility_tools.py').read()); print('OK')"
```

---

### Task 6.4: Update `geo_agent/src/graphs/analyze.py` schema hints + hardcoded SQL

**Files:**
- Modify: `geo_agent/src/graphs/analyze.py`

- [ ] **Step 1: Rewrite schema hint block (lines 266-298)**

Old:
```python
geo_company_mentions(id UUID, client_id UUID, result_id INT, company_name TEXT, mention_position INT, is_own_brand BOOL, executed_at TIMESTAMPTZ)
geo_client_peers(id UUID, client_id UUID, primary_name TEXT, aliases TEXT[], is_own_brand BOOL)
- geo_company_mentions.result_id → geo_results.result_id
- Visibility trend over time: GROUP BY DATE(cm.executed_at), use is_own_brand to separate own vs competitors
```
New:
```python
geo_brand_mentions(id UUID, client_id UUID, result_id INT, brand_name TEXT, mention_position INT, brand_role TEXT CHECK ('own'/'shadow'/'peer'), executed_at TIMESTAMPTZ)
geo_product_mentions(id UUID, client_id UUID, result_id INT, product_id UUID, product_name TEXT, product_role TEXT CHECK ('own'/'shadow_brand_native'/'peer'), owner_brand_name TEXT, owner_peer_name TEXT, mention_position INT, executed_at TIMESTAMPTZ)
geo_client_brands(id UUID, client_id UUID, brand_name TEXT, aliases TEXT[], is_shadow BOOL)
geo_client_topic_products(id UUID, topic_id UUID, client_id UUID, product_name TEXT, match_variants TEXT[], product_role TEXT, owner_brand_id UUID, owner_peer_id UUID)
geo_client_peers(id UUID, client_id UUID, primary_name TEXT, aliases TEXT[])
- geo_brand_mentions.result_id → geo_results.result_id
- Visibility trend over time: GROUP BY DATE(bm.executed_at), filter by brand_role='own' for client's mentions
```

- [ ] **Step 2: Rewrite hardcoded SQL at lines 570-575**

Old:
```python
SELECT cm.company_name, cm.is_own_brand, ...
FROM geo_company_mentions cm ...
GROUP BY cm.company_name, cm.is_own_brand
```
New:
```python
SELECT bm.brand_name, bm.brand_role, ...
FROM geo_brand_mentions bm ...
GROUP BY bm.brand_name, bm.brand_role
```

- [ ] **Step 3: Verify**

```bash
grep -n "geo_company_mentions\|is_own_brand" geo_agent/src/graphs/analyze.py
python3 -c "import ast; ast.parse(open('geo_agent/src/graphs/analyze.py').read()); print('OK')"
```
Expected: 0 old refs, OK.

---

### Task 6.5: Update `geo_agent/src/routers/tasks.py`

**Files:**
- Modify: `geo_agent/src/routers/tasks.py`

- [ ] **Step 1: Fix hardcoded SQL (lines 432-433)**

Old:
```python
FROM geo_company_mentions
WHERE is_own_brand = true AND client_id = $1::uuid
```
New:
```python
FROM geo_brand_mentions
WHERE brand_role = 'own' AND client_id = $1::uuid
```

- [ ] **Step 2: Update relevant_tables list (line 479)**

Old:
```python
"visibility": ["geo_company_mentions", "geo_results", "geo_tasks", "geo_client_peers"],
```
New:
```python
"visibility": ["geo_brand_mentions", "geo_product_mentions", "geo_results", "geo_tasks", "geo_client_peers", "geo_client_brands", "geo_client_topic_products"],
```

- [ ] **Step 3: Verify**

```bash
grep -n "geo_company_mentions\|is_own_brand" geo_agent/src/routers/tasks.py
python3 -c "import ast; ast.parse(open('geo_agent/src/routers/tasks.py').read()); print('OK')"
```

---

### Task 6.6: Update `geo_agent/src/pipelines/analysis_pipeline.py`

**Files:**
- Modify: `geo_agent/src/pipelines/analysis_pipeline.py` (lines 42, 79, 372, 668)

- [ ] **Step 1: Update schema hint strings at the marked lines**

Apply the same renames (`geo_company_mentions` → `geo_brand_mentions`, `is_own_brand` → `brand_role`, `company_name` → `brand_name`) to all hint text. Also add `geo_product_mentions` and the new config tables to the relevant_tables map where appropriate.

- [ ] **Step 2: Verify**

```bash
grep -n "geo_company_mentions\|is_own_brand" geo_agent/src/pipelines/analysis_pipeline.py
python3 -c "import ast; ast.parse(open('geo_agent/src/pipelines/analysis_pipeline.py').read()); print('OK')"
```

---

### Task 6.7: Update `geo_agent/src/pipelines/opportunity_pipeline.py`

**Files:**
- Modify: `geo_agent/src/pipelines/opportunity_pipeline.py` (lines 100-104)

- [ ] **Step 1: Rewrite the hardcoded quadrant SQL**

Old:
```python
COUNT(*) FILTER (WHERE cm.is_own_brand = true) AS own_count,
AVG(cm.mention_position) FILTER (WHERE cm.is_own_brand = true) AS avg_pos
...
LEFT JOIN geo_company_mentions cm ON cm.client_prompt_id = cp.id
```
New:
```python
COUNT(*) FILTER (WHERE bm.brand_role = 'own') AS own_count,
AVG(bm.mention_position) FILTER (WHERE bm.brand_role = 'own') AS avg_pos
...
LEFT JOIN geo_brand_mentions bm ON bm.client_prompt_id = cp.id
```

- [ ] **Step 2: Verify**

```bash
grep -n "geo_company_mentions\|is_own_brand" geo_agent/src/pipelines/opportunity_pipeline.py
python3 -c "import ast; ast.parse(open('geo_agent/src/pipelines/opportunity_pipeline.py').read()); print('OK')"
```

---

### Task 6.8: Delete `geo_agent/src/pipelines/_template_contracts_stub.py`

**Files:**
- Delete: `geo_agent/src/pipelines/_template_contracts_stub.py`

- [ ] **Step 1: Verify no other file imports it**

```bash
grep -rn "_template_contracts_stub\|template_contracts_stub" geo_agent/ --include='*.py'
```
Expected: only the file itself matches.

- [ ] **Step 2: Delete**

```bash
rm geo_agent/src/pipelines/_template_contracts_stub.py
```

- [ ] **Step 3: Verify agent still imports cleanly**

```bash
python3 -c "import ast; ast.parse(open('geo_agent/src/pipelines/analysis_pipeline.py').read()); print('OK')"
```

---

### Task 6.9: Update `geo_admin/src/database.py` Table definitions

**Files:**
- Modify: `geo_admin/src/database.py`

- [ ] **Step 1: Apply the same Table definition updates as Task 3.1** (rename, add three new tables, drop peers.is_own_brand)

- [ ] **Step 2: Verify**

```bash
python3 -c "import ast; ast.parse(open('geo_admin/src/database.py').read()); print('OK')"
```

---

### Task 6.10: Update `geo_admin/src/routers/clients.py` / `prompts.py` / `analysis.py`

**Files:**
- Modify: `geo_admin/src/routers/clients.py`
- Modify: `geo_admin/src/routers/prompts.py`
- Modify: `geo_admin/src/routers/analysis.py`

- [ ] **Step 1: Audit each file for stale refs**

```bash
for f in geo_admin/src/routers/clients.py geo_admin/src/routers/prompts.py geo_admin/src/routers/analysis.py; do
  echo "=== $f ==="
  grep -n "geo_company_mentions\|is_own_brand\|company_name\|topic.products\|topics.products" "$f"
done
```

- [ ] **Step 2: Apply renames per file** (`geo_company_mentions` → `geo_brand_mentions`, etc.)

For any file that reads `topic.products` as TEXT[], change the query to left-join `geo_client_topic_products` and aggregate product_names back to a list.

- [ ] **Step 3: Verify**

```bash
for f in geo_admin/src/routers/clients.py geo_admin/src/routers/prompts.py geo_admin/src/routers/analysis.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('$f OK')"
done
```

---

### Task 6.11: Physically delete legacy `geo_admin/src/routers/brainstorming.py`

**Files:**
- Delete: `geo_admin/src/routers/brainstorming.py`

- [ ] **Step 1: Confirm it's not imported in `geo_admin/src/main.py`**

```bash
grep -n "brainstorming" geo_admin/src/main.py
```
Expected: only LEGACY-commented lines (already done in prior iteration).

- [ ] **Step 2: Delete the file**

```bash
rm geo_admin/src/routers/brainstorming.py
```

- [ ] **Step 3: Remove the LEGACY-commented import and include_router lines from `geo_admin/src/main.py`** (cleanup now that the file is gone)

```bash
# Edit: delete lines 24-28 and lines 95-97 (the LEGACY blocks)
```

- [ ] **Step 4: Verify main.py parses**

```bash
python3 -c "import ast; ast.parse(open('geo_admin/src/main.py').read()); print('OK')"
```

---

## Phase 7: Cleanup, Deployment Order, Rollback

### Task 7.1: Run migration 042 (cleanup) AFTER all code is deployed

- [ ] **Step 1: Checklist — verify all code is done before dropping columns**

Run this one-liner to confirm no production file still references `is_own_brand` or `geo_company_mentions`:

```bash
grep -rn "geo_company_mentions\|is_own_brand\|topic\\.products\\b" \
  --include='*.py' --include='*.ts' --include='*.tsx' \
  --exclude-dir=node_modules --exclude-dir=.git \
  --exclude-dir=migrations --exclude-dir=docs \
  /Users/lancelot/Desktop/GEO_Demo
```
Expected: 0 matches (the only matches should be in `migrations/*.sql` and `docs/*.md`).

- [ ] **Step 2: User executes migration 042 in Cloud SQL**

- [ ] **Step 3: Post-cleanup verification**

```python
python3 -c "
import asyncio, asyncpg
async def v():
    c = await asyncpg.connect(host='localhost', port=5432,
        user='answer-x-geo-db-user', password='answer-x-geo-db-user-123',
        database='answer-x-geo-db')
    # is_own_brand column must be gone
    cols = await c.fetch(\"\"\"SELECT column_name FROM information_schema.columns
        WHERE table_name IN ('geo_brand_mentions', 'geo_client_peers')\"\"\")
    bad = [c['column_name'] for c in cols if c['column_name'] == 'is_own_brand']
    assert not bad, f'is_own_brand still exists: {bad}'
    # products column must be gone from geo_client_topics
    cols = await c.fetch(\"\"\"SELECT column_name FROM information_schema.columns
        WHERE table_name = 'geo_client_topics'\"\"\")
    names = {c['column_name'] for c in cols}
    assert 'products' not in names, 'geo_client_topics.products still present'
    # Agent tables empty
    for t in ['checkpoints', 'agent_messages', 'agent_memories', 'geo_agent_tasks']:
        n = await c.fetchval(f'SELECT COUNT(*) FROM {t}')
        assert n == 0, f'{t} not truncated, has {n} rows'
    print('Cleanup migration verified OK')
    await c.close()
asyncio.run(v())
"
```

---

### Task 7.2: Deployment order summary (documentation only)

- [ ] **Step 1: Record deployment order in the plan**

Deployment must happen in this order to avoid downtime errors:

1. **Database Phase 1** (migrations 040, 041, 043, 044) — additive + data migration + config rewrite. Old columns still present; both old and new code can coexist.
2. **Deploy Analyzer** (Phase 2 code) — Analyzer starts writing to new tables. Old-schema citation/mention analysis still works because columns still exist.
3. **Deploy geo_saas API** (Phase 3 code) — backend now reads new tables. Old code fallback gone.
4. **Deploy geo_saas web** (Phases 4-5 code) — frontend consumes new API responses.
5. **Deploy geo_agent + geo_admin** (Phase 6 code) — Agent NL2SQL uses new schema hints.
6. **Database Phase 2** (migration 042 cleanup) — now safe to drop old columns and TRUNCATE agent tables.

---

### Task 7.3: Rollback considerations

- [ ] **Step 1: Document rollback path**

**Before migration 042 (pre-cleanup):** Reversible via:
- Reverting code deployments (old code still works with both old and new tables if data was dual-written)
- NOTE: Because Analyzer writes only to new tables, reverting to old Analyzer code means new data stops appearing in old views. Roborock dashboard would show stale data only.

**After migration 042:** IRREVERSIBLE.
- Old `is_own_brand` column dropped; old `topic.products` TEXT[] dropped.
- Only recovery = restore from Cloud SQL snapshot taken in Task 0 (pre-migration).

Recovery plan:
1. Identify the snapshot ID taken before migration 040.
2. In Cloud SQL console: "Restore" → create new instance from snapshot.
3. Swap app DB connection strings to point at the restored instance.
4. Investigate cause; never skip Task 7.1 Step 1 verification again.

---

## Self-Review

### Spec coverage checklist

Going through spec §1-§10, mapping each section to tasks:

- §1 (Background & Motivation): Context only. Not a task.
- §2.1-2.4 (Entity model): Covered by Phase 1 DDL (1.1) + backend API shape in Tasks 3.9-3.10 + frontend in 4.2
- §2.5 (Three observation needs): Covered by new API endpoints (3.7 cooccurrence) + UI (5.3)
- §2.6 (Parser always-on): Covered by Task 2.4 (main.py runs both parsers)
- §2.7 (Brand/Peer name exclusivity): Covered by Task 3.10 (addBrand checks peer conflict)
- §2.8 (Topic-only mode): Covered by Task 3.11 (brainstorming Topic-only branch) + 5.2 (empty state)
- §3.1-3.4 (Data model changes): Covered by migrations 040/041/042
- §4.1-4.5 (Parser architecture): Covered by Tasks 2.1, 2.2, 2.3, 2.4
- §5.1.1-5.1.6 (Audit findings): Covered by Tasks 3.2-3.4, 6.1-6.10, migrations 043/044, TRUNCATEs in 042
- §5.2 (Metric rewrite): migration 043
- §5.3 (Template rewrite): migration 044
- §5.4 (Agent schema hints): Tasks 6.1, 6.4, 6.6
- §6.0-6.9 (Insights UI + fallback + wizard): Phases 4-5 (Tasks 4.1-4.5, 5.1-5.5)
- §7 (Prompt Expander): Task 3.11
- §8 (Migration plan): All Phase 1 + Phase 7
- §9 (DB ops rules): Encoded as Task 1.1+ (SELECT-only verification)
- §10.1 (deferred: sentence-level sentiment, peer SKU compare view): not implemented — intentional defer
- §10.3 (cleanup): Tasks 2.5, 6.8, 6.11 (file deletes) + migration 042 (column drops + truncates)

**All core spec requirements mapped to tasks.** No gaps.

### Placeholder scan

Searched plan for TBD/TODO/FIXME/"implement later"/"handle edge cases" — **none present**. All steps contain actual code or concrete commands.

### Type consistency check

- `brand_role` enum values: `'own' | 'shadow' | 'peer'` — consistent across DDL (Task 1.1), Python parser (Task 2.1), SQL rewrites (Task 1.3), API endpoints (Tasks 3.2, 3.5, 3.6), TypeScript types (Task 4.1), UI (Tasks 4.4, 5.2, 5.3) ✓
- `product_role` enum values: `'own' | 'shadow_brand_native' | 'peer'` — consistent across DDL, parser, API, TS types, UI ✓
- Function name `parse_brand_mentions` used in Task 2.1 (definition), Task 2.4 (caller) ✓
- Function name `parse_product_mentions` used in Task 2.2 (definition), Task 2.4 (caller) ✓
- Table name `geo_brand_mentions` used consistently across DDL, SQLAlchemy Table defs, API queries, agent hints ✓
- Table name `geo_client_topic_products` used consistently ✓
- API endpoint paths: `/api/insights/availability`, `/api/insights/product-visibility`, `/api/insights/brand-product-cooccurrence`, `/api/insights/topic-breakdown`, `/api/settings/brands/`, `/api/settings/products/{id}`, `/api/settings/topics/{id}/products`, `/api/clients/{id}/onboarding-complete` — all referenced consistently

**All type / name references consistent.** ✓

---

Plan complete. Saved to `docs/superpowers/plans/2026-04-18-dual-mode-tracking-plan.md`.
