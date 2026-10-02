# Static Report Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a SaaS static report snapshot layer that lets authorized users view one durable daily GEO report per client without triggering Collector, Analyzer, or live dashboard refreshes.

**Architecture:** Add a new `geo_static_reports` table, then implement a SaaS-only read/materialization API that reads existing analyzed data and stores a JSON snapshot. Add a Reports page and static report detail page in the SaaS frontend; report detail renders snapshot data only and never calls live dashboard endpoints.

**Admin Extension:** Add an Admin-only read-management surface for static report snapshots. Admin can list and inspect reports across clients, but cannot trigger Collector, Analyzer, scheduler jobs, or snapshot rebuilds in this release.

**Tech Stack:** PostgreSQL migrations, FastAPI, asyncpg, Pydantic, React 19, TypeScript, Vite, Tailwind, shadcn/Radix components, Recharts, react-i18next.

---

## No-Git Rule

The project owner asked not to run Git commands for this work. Do not include `git add`, `git commit`, branch creation, reset, checkout, stash, or push steps during execution.

Use these checkpoints instead:

- Run the verification command listed in each task.
- Report the changed files and test output in the chat.
- Leave all changes unstaged in the working tree.

## Scope Guard

This plan implements only the static report snapshot layer.

Do not modify:

- `geo_collector/`
- `geo_analyzer/`
- Admin scheduler behavior
- Existing Collector or Analyzer manual trigger behavior
- Existing live dashboard endpoint behavior
- Snapshot materialization from Admin UI

Allowed live-dashboard contact points:

- Read existing router response shapes for compatibility.
- Reuse presentational frontend components only after separating them from live fetching.

The report snapshot builder must not import Collector or Analyzer code and must not call LLMs in the first release.

## File Map

### Database

- Create: `migrations/093_static_report_snapshots.sql`
- Modify: `geo_saas/src/database.py`

### SaaS Backend

- Create: `geo_saas/src/routers/static_reports/__init__.py`
- Create: `geo_saas/src/routers/static_reports/models.py`
- Create: `geo_saas/src/routers/static_reports/repository.py`
- Create: `geo_saas/src/routers/static_reports/readiness.py`
- Create: `geo_saas/src/routers/static_reports/snapshot_builder.py`
- Create: `geo_saas/src/routers/static_reports/router.py`
- Modify: `geo_saas/src/main.py`

### SaaS Backend Tests

- Create: `geo_saas/tests/test_static_reports_models.py`
- Create: `geo_saas/tests/test_static_reports_readiness.py`
- Create: `geo_saas/tests/test_static_reports_snapshot_builder.py`
- Create: `geo_saas/tests/test_static_reports_router.py`

### SaaS Frontend API and Types

- Create: `geo_saas/web/src/lib/api/staticReports.ts`
- Modify: `geo_saas/web/src/lib/api/index.ts`

### SaaS Frontend Pages and Components

- Create: `geo_saas/web/src/pages/reports/ReportsListPage.tsx`
- Create: `geo_saas/web/src/pages/reports/StaticReportPage.tsx`
- Create: `geo_saas/web/src/pages/reports/components/ReportStatusBadge.tsx`
- Create: `geo_saas/web/src/pages/reports/components/DataCompletenessBanner.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticVisibilitySection.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticCitationSection.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticSentimentSection.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticPromptTopicSection.tsx`
- Modify: `geo_saas/web/src/App.tsx`
- Modify: `geo_saas/web/src/components/layout/Sidebar.tsx`

### SaaS Frontend i18n

- Create: `geo_saas/web/src/i18n/locales/zh-CN/reports.json`
- Create: `geo_saas/web/src/i18n/locales/en-US/reports.json`
- Modify: `geo_saas/web/src/i18n/index.ts`
- Modify: `geo_saas/web/src/i18n/types.ts`
- Modify: `geo_saas/web/src/i18n/locales/zh-CN/sidebar.json`
- Modify: `geo_saas/web/src/i18n/locales/en-US/sidebar.json`

### Admin Backend

- Create: `geo_admin/src/routers/static_reports.py`
- Modify: `geo_admin/src/main.py`
- Create: `geo_admin/tests/test_static_reports_router.py`

### Admin Frontend

- Modify: `geo_admin/web/src/api/client.ts`
- Create: `geo_admin/web/src/pages/StaticReportsPage.tsx`
- Modify: `geo_admin/web/src/App.tsx`
- Modify: `geo_admin/web/src/components/layout/Sidebar.tsx`

## Task 1: Add Static Report Schema

**Files:**

- Create: `migrations/093_static_report_snapshots.sql`
- Modify: `geo_saas/src/database.py`

- [ ] **Step 1: Create the migration file**

Create `migrations/093_static_report_snapshots.sql`:

```sql
-- ============================================================
-- Migration 093: Static Report Snapshots
-- ============================================================
-- Spec: docs/superpowers/specs/2026-05-27-static-report-snapshot-design.md
--
-- Purpose:
--   - Store one immutable static report snapshot per client per Shanghai date.
--   - Persist JSON report data generated from existing Analyzer outputs.
--   - Keep static reports decoupled from Collector and Analyzer execution.
--
-- Execution:
--   - Run manually in Cloud SQL.
--   - This migration creates schema objects only.
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS geo_static_reports (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id                UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    report_date              DATE NOT NULL,
    timezone                 TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    status                   TEXT NOT NULL,
    snapshot_version         TEXT NOT NULL,
    snapshot_json            JSONB,
    data_window_start        DATE NOT NULL,
    data_window_end          DATE NOT NULL,
    rendering_mode           TEXT NOT NULL,
    data_completeness        JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message            TEXT,
    materialized_by_user_id  UUID REFERENCES geo_users(id) ON DELETE SET NULL,
    materialized_at          TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT geo_static_reports_unique_day UNIQUE (client_id, report_date),
    CONSTRAINT geo_static_reports_status_check CHECK (
        status IN ('PENDING', 'MATERIALIZING', 'COMPLETED', 'NOT_READY', 'FAILED')
    ),
    CONSTRAINT geo_static_reports_rendering_mode_check CHECK (
        rendering_mode IN ('single_day', 'multi_day')
    ),
    CONSTRAINT geo_static_reports_timezone_check CHECK (btrim(timezone) <> ''),
    CONSTRAINT geo_static_reports_snapshot_version_check CHECK (btrim(snapshot_version) <> ''),
    CONSTRAINT geo_static_reports_window_check CHECK (data_window_start <= data_window_end)
);

CREATE INDEX IF NOT EXISTS idx_geo_static_reports_client_date
    ON geo_static_reports (client_id, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_geo_static_reports_client_status
    ON geo_static_reports (client_id, status);

CREATE OR REPLACE FUNCTION set_geo_static_reports_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_geo_static_reports_updated_at ON geo_static_reports;
CREATE TRIGGER trg_geo_static_reports_updated_at
    BEFORE UPDATE ON geo_static_reports
    FOR EACH ROW EXECUTE FUNCTION set_geo_static_reports_updated_at();

COMMENT ON TABLE geo_static_reports IS 'One daily static GEO report snapshot per client, materialized from existing analyzed data.';
COMMENT ON COLUMN geo_static_reports.snapshot_json IS 'Canonical static report JSON. Report detail pages render this payload without calling live dashboard endpoints.';
COMMENT ON COLUMN geo_static_reports.report_date IS 'Shanghai local calendar date represented by the report.';

COMMIT;

-- Manual verification after execution:
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'geo_static_reports'
-- ORDER BY ordinal_position;
```

- [ ] **Step 2: Add the table-name constant**

Modify `geo_saas/src/database.py`:

```python
# Static reports
GEO_STATIC_REPORTS = "geo_static_reports"
```

Also add `"GEO_STATIC_REPORTS"` to `__all__`.

- [ ] **Step 3: Verify migration syntax by inspection**

Run:

```bash
sed -n '1,220p' migrations/093_static_report_snapshots.sql
```

Expected:

- The file starts at migration 093.
- It contains no destructive DDL.
- It does not seed customer data.
- It creates `geo_static_reports` only.

## Task 2: Define Backend Models and Date Helpers

**Files:**

- Create: `geo_saas/src/routers/static_reports/__init__.py`
- Create: `geo_saas/src/routers/static_reports/models.py`
- Test: `geo_saas/tests/test_static_reports_models.py`

- [ ] **Step 1: Write model tests**

Create `geo_saas/tests/test_static_reports_models.py`:

```python
from datetime import date, datetime, timezone

from routers.static_reports.models import (
    SHANGHAI_TZ,
    StaticReportStatus,
    compute_report_dates,
    serialize_record_value,
)


def test_compute_report_dates_uses_shanghai_day():
    now_utc = datetime(2026, 5, 26, 18, 30, tzinfo=timezone.utc)
    dates = compute_report_dates(now_utc)
    assert dates.report_date == date(2026, 5, 27)
    assert dates.window_start == date(2026, 5, 21)
    assert dates.window_end == date(2026, 5, 27)
    assert dates.timezone == SHANGHAI_TZ


def test_static_report_status_values_are_fixed():
    assert StaticReportStatus.COMPLETED == "COMPLETED"
    assert StaticReportStatus.NOT_READY == "NOT_READY"


def test_serialize_record_value_handles_dates_and_decimals():
    from decimal import Decimal

    assert serialize_record_value(date(2026, 5, 27)) == "2026-05-27"
    assert serialize_record_value(Decimal("12.30")) == 12.3
```

- [ ] **Step 2: Run model tests and confirm failure**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_models.py -q
```

Expected: failure because `routers.static_reports.models` does not exist.

- [ ] **Step 3: Create the package and models**

Create `geo_saas/src/routers/static_reports/__init__.py`:

```python
"""Static report snapshot API package."""
```

Create `geo_saas/src/routers/static_reports/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

SHANGHAI_TZ = "Asia/Shanghai"
SNAPSHOT_VERSION = "static-report-v1"


class StaticReportStatus(str, Enum):
    PENDING = "PENDING"
    MATERIALIZING = "MATERIALIZING"
    COMPLETED = "COMPLETED"
    NOT_READY = "NOT_READY"
    FAILED = "FAILED"


class RenderingMode(str, Enum):
    SINGLE_DAY = "single_day"
    MULTI_DAY = "multi_day"


@dataclass(frozen=True)
class ReportDates:
    report_date: date
    window_start: date
    window_end: date
    timezone: str = SHANGHAI_TZ


def compute_report_dates(now: datetime | None = None, window_days: int = 7) -> ReportDates:
    current = now or datetime.now(tz=ZoneInfo(SHANGHAI_TZ))
    shanghai_now = current.astimezone(ZoneInfo(SHANGHAI_TZ))
    report_date = shanghai_now.date()
    return ReportDates(
        report_date=report_date,
        window_start=date.fromordinal(report_date.toordinal() - window_days + 1),
        window_end=report_date,
    )


def serialize_record_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return str(value)
    return value


def serialize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        out.append({key: serialize_record_value(value) for key, value in item.items()})
    return out


class StaticReportMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    client_id: str
    report_date: date
    timezone: str = SHANGHAI_TZ
    status: StaticReportStatus
    snapshot_version: str
    data_window_start: date
    data_window_end: date
    rendering_mode: RenderingMode
    data_completeness: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any] | str] = Field(default_factory=list)
    error_message: str | None = None
    materialized_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StaticReportDetail(StaticReportMeta):
    snapshot_json: dict[str, Any] | None = None


class StaticReportListOut(BaseModel):
    data: list[StaticReportMeta] = Field(default_factory=list)


class TodayReportStatusOut(BaseModel):
    status: StaticReportStatus
    report_id: str | None = None
    report_date: date
    ready: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_completeness: dict[str, Any] = Field(default_factory=dict)


class MaterializeTodayRequest(BaseModel):
    client_id: str


class MaterializeTodayOut(BaseModel):
    status: StaticReportStatus
    report_id: str | None = None
    ready: bool = False
    reasons: list[str] = Field(default_factory=list)
    report: StaticReportDetail | None = None
```

- [ ] **Step 4: Run model tests and confirm pass**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_models.py -q
```

Expected: all tests pass.

## Task 3: Add Repository for Daily Report Rows

**Files:**

- Create: `geo_saas/src/routers/static_reports/repository.py`
- Test: `geo_saas/tests/test_static_reports_snapshot_builder.py`

- [ ] **Step 1: Add repository helpers**

Create `geo_saas/src/routers/static_reports/repository.py`:

```python
from __future__ import annotations

import json
from datetime import date
from typing import Any

from database import GEO_STATIC_REPORTS

from .models import (
    SNAPSHOT_VERSION,
    RenderingMode,
    ReportDates,
    StaticReportStatus,
)


def row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


class StaticReportRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def list_for_client(self, client_id: str, limit: int = 50) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id::text, client_id::text, report_date, timezone, status,
                       snapshot_version, data_window_start, data_window_end,
                       rendering_mode, data_completeness, warnings, error_message,
                       materialized_at, created_at, updated_at
                FROM {GEO_STATIC_REPORTS}
                WHERE client_id = $1::uuid
                ORDER BY report_date DESC
                LIMIT $2
                """,
                client_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def get_by_id(self, report_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id::text, client_id::text, report_date, timezone, status,
                       snapshot_version, snapshot_json, data_window_start, data_window_end,
                       rendering_mode, data_completeness, warnings, error_message,
                       materialized_at, created_at, updated_at
                FROM {GEO_STATIC_REPORTS}
                WHERE id = $1::uuid
                """,
                report_id,
            )
        return row_to_dict(row)

    async def get_for_date(self, client_id: str, report_date: date) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id::text, client_id::text, report_date, timezone, status,
                       snapshot_version, snapshot_json, data_window_start, data_window_end,
                       rendering_mode, data_completeness, warnings, error_message,
                       materialized_at, created_at, updated_at
                FROM {GEO_STATIC_REPORTS}
                WHERE client_id = $1::uuid AND report_date = $2
                """,
                client_id,
                report_date,
            )
        return row_to_dict(row)

    async def upsert_materializing(
        self,
        client_id: str,
        dates: ReportDates,
        user_id: str,
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {GEO_STATIC_REPORTS} (
                        client_id, report_date, timezone, status, snapshot_version,
                        data_window_start, data_window_end, rendering_mode,
                        materialized_by_user_id
                    )
                    VALUES (
                        $1::uuid, $2, $3, $4, $5,
                        $6, $7, $8, $9::uuid
                    )
                    ON CONFLICT (client_id, report_date) DO UPDATE SET
                        status = CASE
                            WHEN {GEO_STATIC_REPORTS}.status IN ('COMPLETED', 'MATERIALIZING')
                            THEN {GEO_STATIC_REPORTS}.status
                            ELSE EXCLUDED.status
                        END,
                        error_message = CASE
                            WHEN {GEO_STATIC_REPORTS}.status IN ('COMPLETED', 'MATERIALIZING')
                            THEN {GEO_STATIC_REPORTS}.error_message
                            ELSE NULL
                        END,
                        updated_at = NOW()
                    RETURNING id::text, client_id::text, report_date, timezone, status,
                              snapshot_version, snapshot_json, data_window_start,
                              data_window_end, rendering_mode, data_completeness,
                              warnings, error_message, materialized_at, created_at, updated_at
                    """,
                    client_id,
                    dates.report_date,
                    dates.timezone,
                    StaticReportStatus.MATERIALIZING.value,
                    SNAPSHOT_VERSION,
                    dates.window_start,
                    dates.window_end,
                    RenderingMode.SINGLE_DAY.value,
                    user_id,
                )
        return dict(row)

    async def mark_not_ready(
        self,
        report_id: str,
        reasons: list[str],
        data_completeness: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE {GEO_STATIC_REPORTS}
                SET status = $2,
                    warnings = $3::jsonb,
                    data_completeness = $4::jsonb,
                    updated_at = NOW()
                WHERE id = $1::uuid
                RETURNING id::text, client_id::text, report_date, timezone, status,
                          snapshot_version, snapshot_json, data_window_start,
                          data_window_end, rendering_mode, data_completeness,
                          warnings, error_message, materialized_at, created_at, updated_at
                """,
                report_id,
                StaticReportStatus.NOT_READY.value,
                json.dumps(reasons, ensure_ascii=False),
                json.dumps(data_completeness, ensure_ascii=False),
            )
        return dict(row)

    async def complete(
        self,
        report_id: str,
        snapshot: dict[str, Any],
        rendering_mode: RenderingMode,
        data_completeness: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE {GEO_STATIC_REPORTS}
                SET status = $2,
                    snapshot_json = $3::jsonb,
                    rendering_mode = $4,
                    data_completeness = $5::jsonb,
                    warnings = $6::jsonb,
                    materialized_at = NOW(),
                    error_message = NULL,
                    updated_at = NOW()
                WHERE id = $1::uuid
                RETURNING id::text, client_id::text, report_date, timezone, status,
                          snapshot_version, snapshot_json, data_window_start,
                          data_window_end, rendering_mode, data_completeness,
                          warnings, error_message, materialized_at, created_at, updated_at
                """,
                report_id,
                StaticReportStatus.COMPLETED.value,
                json.dumps(snapshot, ensure_ascii=False, default=str),
                rendering_mode.value,
                json.dumps(data_completeness, ensure_ascii=False),
                json.dumps(warnings, ensure_ascii=False),
            )
        return dict(row)

    async def fail(self, report_id: str, message: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE {GEO_STATIC_REPORTS}
                SET status = $2,
                    error_message = $3,
                    updated_at = NOW()
                WHERE id = $1::uuid
                RETURNING id::text, client_id::text, report_date, timezone, status,
                          snapshot_version, snapshot_json, data_window_start,
                          data_window_end, rendering_mode, data_completeness,
                          warnings, error_message, materialized_at, created_at, updated_at
                """,
                report_id,
                StaticReportStatus.FAILED.value,
                message[:2000],
            )
        return dict(row)
```

- [ ] **Step 2: Verify import safety**

Run:

```bash
cd geo_saas && python - <<'PY'
import sys
sys.path.insert(0, "src")
from routers.static_reports.repository import StaticReportRepository
print(StaticReportRepository.__name__)
PY
```

Expected: prints `StaticReportRepository`.

## Task 4: Implement Readiness Checks

**Files:**

- Create: `geo_saas/src/routers/static_reports/readiness.py`
- Test: `geo_saas/tests/test_static_reports_readiness.py`

- [ ] **Step 1: Write pure readiness result tests**

Create `geo_saas/tests/test_static_reports_readiness.py`:

```python
from routers.static_reports.readiness import ReadinessResult


def test_readiness_result_ready_requires_no_reasons():
    assert ReadinessResult(reasons=[]).ready is True
    assert ReadinessResult(reasons=["sentiment_missing"]).ready is False


def test_readiness_result_preserves_counts():
    result = ReadinessResult(
        reasons=["citation_missing"],
        data_completeness={"raw_results": 10, "analyzed_results": 9},
    )
    assert result.ready is False
    assert result.data_completeness["analyzed_results"] == 9
```

- [ ] **Step 2: Run readiness tests and confirm failure**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_readiness.py -q
```

Expected: failure because `readiness.py` does not exist.

- [ ] **Step 3: Implement readiness checker**

Create `geo_saas/src/routers/static_reports/readiness.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from .models import ReportDates


@dataclass
class ReadinessResult:
    reasons: list[str] = field(default_factory=list)
    data_completeness: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return len(self.reasons) == 0


async def has_sentiment_scope(conn, client_id: str, dates: ReportDates) -> bool:
    value = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM geo_client_prompts cp
            JOIN geo_global_intents gi
              ON gi.intent_name = cp.intent
             AND gi.is_active = true
            WHERE cp.client_id = $1::uuid
              AND cp.is_active = true
              AND gi.categories @> '["Sentiment"]'::jsonb
        )
        """,
        client_id,
    )
    return bool(value)


async def check_report_readiness(pool, client_id: str, dates: ReportDates) -> ReadinessResult:
    reasons: list[str] = []
    async with pool.acquire() as conn:
        raw_results = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_results
            WHERE client_id = $1::uuid
              AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        analyzed_results = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_results
            WHERE client_id = $1::uuid
              AND analyzed_at IS NOT NULL
              AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        same_day_analyzed = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_results
            WHERE client_id = $1::uuid
              AND analyzed_at IS NOT NULL
              AND (ingested_at AT TIME ZONE $3)::date = $2
            """,
            client_id,
            dates.report_date,
            dates.timezone,
        ) or 0)

        visibility_rows = int(await conn.fetchval(
            """
            SELECT COUNT(*) FROM (
                SELECT result_id
                FROM geo_brand_mentions
                WHERE client_id = $1::uuid
                  AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
                UNION
                SELECT result_id
                FROM geo_product_mentions
                WHERE client_id = $1::uuid
                  AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            ) visibility
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        citation_rows = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_citations
            WHERE client_id = $1::uuid
              AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        sentiment_expected = await has_sentiment_scope(conn, client_id, dates)
        sentiment_rows = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_sentiment_results
            WHERE client_id = $1::uuid
              AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

    if raw_results == 0:
        reasons.append("raw_results_missing")
    if analyzed_results == 0:
        reasons.append("analyzed_results_missing")
    if same_day_analyzed == 0:
        reasons.append("same_day_analyzed_results_missing")
    if visibility_rows == 0:
        reasons.append("visibility_missing")
    if citation_rows == 0:
        reasons.append("citation_missing")
    if sentiment_expected and sentiment_rows == 0:
        reasons.append("sentiment_missing")

    analyzed_pct = round((analyzed_results / raw_results) * 100, 1) if raw_results else 0
    return ReadinessResult(
        reasons=reasons,
        data_completeness={
            "raw_results": raw_results,
            "analyzed_results": analyzed_results,
            "same_day_analyzed_results": same_day_analyzed,
            "analyzed_pct": analyzed_pct,
            "visibility_rows": visibility_rows,
            "citation_rows": citation_rows,
            "sentiment_expected": sentiment_expected,
            "sentiment_rows": sentiment_rows,
        },
    )
```

- [ ] **Step 4: Run readiness tests and confirm pass**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_readiness.py -q
```

Expected: all tests pass.

## Task 5: Build Snapshot JSON from Existing Analyzer Tables

**Files:**

- Create: `geo_saas/src/routers/static_reports/snapshot_builder.py`
- Test: `geo_saas/tests/test_static_reports_snapshot_builder.py`

- [ ] **Step 1: Write rendering-mode and shape tests**

Create `geo_saas/tests/test_static_reports_snapshot_builder.py`:

```python
from datetime import date

from routers.static_reports.models import ReportDates, RenderingMode
from routers.static_reports.snapshot_builder import choose_rendering_mode, empty_snapshot


def test_choose_rendering_mode_single_day():
    assert choose_rendering_mode(["2026-05-27"]) == RenderingMode.SINGLE_DAY


def test_choose_rendering_mode_multi_day():
    assert choose_rendering_mode(["2026-05-26", "2026-05-27"]) == RenderingMode.MULTI_DAY


def test_empty_snapshot_has_required_sections():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 21),
        window_end=date(2026, 5, 27),
    )
    snapshot = empty_snapshot("client-1", "Roborock", dates, RenderingMode.SINGLE_DAY, {})
    assert snapshot["version"] == "static-report-v1"
    assert snapshot["client"]["name"] == "Roborock"
    assert "visibility" in snapshot
    assert "citations" in snapshot
    assert "sentiment" in snapshot
```

- [ ] **Step 2: Run snapshot tests and confirm failure**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_snapshot_builder.py -q
```

Expected: failure because `snapshot_builder.py` does not exist.

- [ ] **Step 3: Implement deterministic snapshot builder**

Create `geo_saas/src/routers/static_reports/snapshot_builder.py`.

Use this structure:

```python
from __future__ import annotations

from typing import Any

from .models import SNAPSHOT_VERSION, RenderingMode, ReportDates, serialize_rows


def choose_rendering_mode(date_values: list[str]) -> RenderingMode:
    unique_days = {value for value in date_values if value}
    return RenderingMode.MULTI_DAY if len(unique_days) >= 2 else RenderingMode.SINGLE_DAY


def empty_snapshot(
    client_id: str,
    client_name: str,
    dates: ReportDates,
    rendering_mode: RenderingMode,
    data_completeness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": SNAPSHOT_VERSION,
        "client": {"id": client_id, "name": client_name},
        "report": {
            "date": dates.report_date.isoformat(),
            "timezone": dates.timezone,
            "window_start": dates.window_start.isoformat(),
            "window_end": dates.window_end.isoformat(),
            "rendering_mode": rendering_mode.value,
        },
        "data_completeness": data_completeness,
        "visibility": {"summary": {}, "ranking": [], "time_series": []},
        "citations": {"summary": {}, "domains": [], "pages": [], "categories": []},
        "sentiment": {"summary": {}, "themes": [], "examples": []},
        "prompts": {"ranking": []},
        "topics": {"ranking": []},
        "narrative": {"zh-CN": {}, "en-US": {}},
    }
```

Then add async query helpers in the same file:

```python
async def load_client_name(conn, client_id: str) -> str:
    return await conn.fetchval(
        "SELECT name FROM geo_clients WHERE id = $1::uuid",
        client_id,
    ) or ""
```

Add query functions with narrow, read-only SQL:

- `load_visibility_snapshot(conn, client_id, dates)`
- `load_citation_snapshot(conn, client_id, dates)`
- `load_sentiment_snapshot(conn, client_id, dates)`
- `load_prompt_topic_snapshot(conn, client_id, dates)`

Each function must:

- Filter by `client_id = $1::uuid`.
- Filter dates using `(executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3`.
- Return plain JSON-compatible dicts using `serialize_rows`.
- Avoid modifying existing live dashboard routers.

Use these initial query surfaces:

```python
async def load_visibility_snapshot(conn, client_id: str, dates: ReportDates) -> dict[str, Any]:
    ranking = await conn.fetch(
        """
        SELECT brand_name, brand_role, COUNT(*)::int AS mention_count,
               ROUND(AVG(mention_position)::numeric, 2) AS avg_position
        FROM geo_brand_mentions
        WHERE client_id = $1::uuid
          AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        GROUP BY brand_name, brand_role
        ORDER BY mention_count DESC, brand_name ASC
        LIMIT 100
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
    )
    series = await conn.fetch(
        """
        SELECT (executed_at AT TIME ZONE $4)::date AS date,
               brand_role,
               COUNT(*)::int AS mention_count
        FROM geo_brand_mentions
        WHERE client_id = $1::uuid
          AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        GROUP BY date, brand_role
        ORDER BY date ASC, brand_role ASC
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
    )
    return {
        "summary": {
            "total_mentions": sum(row["mention_count"] for row in ranking),
        },
        "ranking": serialize_rows(ranking),
        "time_series": serialize_rows(series),
    }
```

Implement analogous citation and sentiment queries with these outputs:

- Citation domains: `source_domain`, `domain_category`, `citation_role`, `citation_count`.
- Citation pages: `source_url`, `source_domain`, `citation_count`.
- Sentiment summary: `sentiment`, `count`, `avg_confidence`.
- Sentiment themes: `theme_name`, `sentiment`, `count`.
- Prompt ranking: prompt text, topic, platform, mention/citation counts where practical.

Finally add:

```python
async def build_snapshot(pool, client_id: str, dates: ReportDates, data_completeness: dict[str, Any]) -> tuple[dict[str, Any], RenderingMode, list[str]]:
    async with pool.acquire() as conn:
        client_name = await load_client_name(conn, client_id)
        visibility = await load_visibility_snapshot(conn, client_id, dates)
        citations = await load_citation_snapshot(conn, client_id, dates)
        sentiment = await load_sentiment_snapshot(conn, client_id, dates)
        prompt_topic = await load_prompt_topic_snapshot(conn, client_id, dates)
        date_rows = await conn.fetch(
            """
            SELECT DISTINCT (ingested_at AT TIME ZONE $4)::date::text AS date
            FROM geo_results
            WHERE client_id = $1::uuid
              AND analyzed_at IS NOT NULL
              AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            ORDER BY date
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        )

    rendering_mode = choose_rendering_mode([row["date"] for row in date_rows])
    snapshot = empty_snapshot(client_id, client_name, dates, rendering_mode, data_completeness)
    snapshot["visibility"] = visibility
    snapshot["citations"] = citations
    snapshot["sentiment"] = sentiment
    snapshot["prompts"] = prompt_topic["prompts"]
    snapshot["topics"] = prompt_topic["topics"]
    warnings: list[str] = []
    if rendering_mode == RenderingMode.SINGLE_DAY:
        warnings.append("single_day_report")
    return snapshot, rendering_mode, warnings
```

- [ ] **Step 4: Run snapshot tests and confirm pass**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_snapshot_builder.py -q
```

Expected: all tests pass.

## Task 6: Add Static Report API Router

**Files:**

- Create: `geo_saas/src/routers/static_reports/router.py`
- Modify: `geo_saas/src/main.py`
- Test: `geo_saas/tests/test_static_reports_router.py`

- [ ] **Step 1: Write router tests with dependency overrides**

Create `geo_saas/tests/test_static_reports_router.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.static_reports.router import router


def test_static_reports_router_mounts():
    app = FastAPI()
    app.include_router(router)
    paths = {route.path for route in app.routes}
    assert "/api/static-reports" in paths
    assert "/api/static-reports/today" in paths
    assert "/api/static-reports/today/materialize" in paths
    assert "/api/static-reports/{report_id}" in paths
```

- [ ] **Step 2: Run router tests and confirm failure**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_router.py -q
```

Expected: failure because `router.py` does not exist.

- [ ] **Step 3: Implement router**

Create `geo_saas/src/routers/static_reports/router.py`:

```python
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from geo_common.auth import has_client_access

from dependencies.auth import AuthenticatedUser, require_client_access_if_present
from pool import get_pool

from .models import (
    MaterializeTodayOut,
    MaterializeTodayRequest,
    StaticReportDetail,
    StaticReportListOut,
    StaticReportStatus,
    TodayReportStatusOut,
    compute_report_dates,
)
from .readiness import check_report_readiness
from .repository import StaticReportRepository
from .snapshot_builder import build_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/static-reports", tags=["Static Reports"])


def _authorized_client_id(request: Request, client_id: str) -> None:
    authorized = getattr(request.state, "authorized_client_id", None)
    if authorized and str(authorized) != str(client_id):
        raise HTTPException(status_code=403, detail="No access to this client")


@router.get("", response_model=StaticReportListOut)
async def list_static_reports(
    client_id: str,
    request: Request,
    _user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, client_id)
    repo = StaticReportRepository(pool)
    return {"data": await repo.list_for_client(client_id)}


@router.get("/today", response_model=TodayReportStatusOut)
async def today_static_report_status(
    client_id: str,
    request: Request,
    _user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, client_id)
    dates = compute_report_dates()
    repo = StaticReportRepository(pool)
    existing = await repo.get_for_date(client_id, dates.report_date)
    if existing and existing["status"] == StaticReportStatus.COMPLETED.value:
        return {
            "status": StaticReportStatus.COMPLETED,
            "report_id": existing["id"],
            "report_date": dates.report_date,
            "ready": True,
            "reasons": [],
            "data_completeness": existing.get("data_completeness") or {},
        }
    readiness = await check_report_readiness(pool, client_id, dates)
    return {
        "status": StaticReportStatus.PENDING if readiness.ready else StaticReportStatus.NOT_READY,
        "report_id": existing["id"] if existing else None,
        "report_date": dates.report_date,
        "ready": readiness.ready,
        "reasons": readiness.reasons,
        "data_completeness": readiness.data_completeness,
    }


@router.post("/today/materialize", response_model=MaterializeTodayOut)
async def materialize_today_static_report(
    payload: MaterializeTodayRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, payload.client_id)
    dates = compute_report_dates()
    repo = StaticReportRepository(pool)
    existing = await repo.get_for_date(payload.client_id, dates.report_date)
    if existing and existing["status"] == StaticReportStatus.COMPLETED.value:
        return {
            "status": StaticReportStatus.COMPLETED,
            "report_id": existing["id"],
            "ready": True,
            "reasons": [],
            "report": existing,
        }

    row = await repo.upsert_materializing(payload.client_id, dates, user.id)
    if row["status"] == StaticReportStatus.COMPLETED.value:
        return {
            "status": StaticReportStatus.COMPLETED,
            "report_id": row["id"],
            "ready": True,
            "reasons": [],
            "report": row,
        }
    if row["status"] == StaticReportStatus.MATERIALIZING.value and existing and existing["status"] == StaticReportStatus.MATERIALIZING.value:
        return {
            "status": StaticReportStatus.MATERIALIZING,
            "report_id": row["id"],
            "ready": False,
            "reasons": ["materialization_in_progress"],
            "report": row,
        }

    readiness = await check_report_readiness(pool, payload.client_id, dates)
    if not readiness.ready:
        report = await repo.mark_not_ready(row["id"], readiness.reasons, readiness.data_completeness)
        return {
            "status": StaticReportStatus.NOT_READY,
            "report_id": report["id"],
            "ready": False,
            "reasons": readiness.reasons,
            "report": report,
        }

    try:
        snapshot, rendering_mode, warnings = await build_snapshot(
            pool,
            payload.client_id,
            dates,
            readiness.data_completeness,
        )
        report = await repo.complete(
            row["id"],
            snapshot,
            rendering_mode,
            readiness.data_completeness,
            warnings,
        )
        return {
            "status": StaticReportStatus.COMPLETED,
            "report_id": report["id"],
            "ready": True,
            "reasons": [],
            "report": report,
        }
    except Exception as exc:
        logger.exception("[STATIC_REPORT] materialization failed")
        report = await repo.fail(row["id"], str(exc))
        return {
            "status": StaticReportStatus.FAILED,
            "report_id": report["id"],
            "ready": False,
            "reasons": ["snapshot_materialization_failed"],
            "report": report,
        }


@router.get("/{report_id}", response_model=StaticReportDetail)
async def get_static_report(
    report_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    report = await repo.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    client_id = str(report["client_id"])
    allowed = await has_client_access(pool, user.id, client_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="No access to this client")
    return report
```

- [ ] **Step 4: Wire router into SaaS app**

Modify `geo_saas/src/main.py`:

```python
from routers.static_reports.router import router as static_reports_router
```

Register it with standard SaaS auth dependencies:

```python
app.include_router(static_reports_router, tags=["Static Reports"], dependencies=auth_dependencies)
```

- [ ] **Step 5: Run router tests**

Run:

```bash
cd geo_saas && pytest tests/test_static_reports_router.py -q
```

Expected: all tests pass.

## Task 7: Add Frontend API Wrapper

**Files:**

- Create: `geo_saas/web/src/lib/api/staticReports.ts`
- Modify: `geo_saas/web/src/lib/api/index.ts`

- [ ] **Step 1: Add API wrapper**

Create `geo_saas/web/src/lib/api/staticReports.ts`:

```typescript
import { API_BASE, fetchJSON } from "./_base";

export type StaticReportStatus =
  | "PENDING"
  | "MATERIALIZING"
  | "COMPLETED"
  | "NOT_READY"
  | "FAILED";

export interface StaticReportMeta {
  id: string;
  client_id: string;
  report_date: string;
  timezone: string;
  status: StaticReportStatus;
  snapshot_version: string;
  data_window_start: string;
  data_window_end: string;
  rendering_mode: "single_day" | "multi_day";
  data_completeness: Record<string, any>;
  warnings: Array<string | Record<string, any>>;
  error_message?: string | null;
  materialized_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface StaticReportDetail extends StaticReportMeta {
  snapshot_json?: StaticReportSnapshot | null;
}

export interface StaticReportSnapshot {
  version: string;
  client: { id: string; name: string };
  report: {
    date: string;
    timezone: string;
    window_start: string;
    window_end: string;
    rendering_mode: "single_day" | "multi_day";
  };
  data_completeness: Record<string, any>;
  visibility: Record<string, any>;
  citations: Record<string, any>;
  sentiment: Record<string, any>;
  prompts: Record<string, any>;
  topics: Record<string, any>;
  narrative?: Record<string, Record<string, any>>;
}

export interface StaticReportListOut {
  data: StaticReportMeta[];
}

export interface TodayReportStatusOut {
  status: StaticReportStatus;
  report_id?: string | null;
  report_date: string;
  ready: boolean;
  reasons: string[];
  data_completeness: Record<string, any>;
}

export interface MaterializeTodayOut {
  status: StaticReportStatus;
  report_id?: string | null;
  ready: boolean;
  reasons: string[];
  report?: StaticReportDetail | null;
}

export async function listStaticReports(clientId: string): Promise<StaticReportListOut> {
  return fetchJSON<StaticReportListOut>(`${API_BASE}/static-reports?client_id=${clientId}`);
}

export async function getTodayStaticReportStatus(clientId: string): Promise<TodayReportStatusOut> {
  return fetchJSON<TodayReportStatusOut>(`${API_BASE}/static-reports/today?client_id=${clientId}`);
}

export async function materializeTodayStaticReport(clientId: string): Promise<MaterializeTodayOut> {
  return fetchJSON<MaterializeTodayOut>(`${API_BASE}/static-reports/today/materialize`, {
    method: "POST",
    body: JSON.stringify({ client_id: clientId }),
  });
}

export async function getStaticReport(reportId: string): Promise<StaticReportDetail> {
  return fetchJSON<StaticReportDetail>(`${API_BASE}/static-reports/${reportId}`);
}
```

- [ ] **Step 2: Re-export API wrapper**

Modify `geo_saas/web/src/lib/api/index.ts`:

```typescript
export * from "./staticReports";
```

- [ ] **Step 3: Typecheck API module**

Run:

```bash
cd geo_saas/web && npm run build
```

Expected: TypeScript build progresses past API imports. It may fail later if report pages are not added yet; that is acceptable at this step only if the error references missing future report page files.

## Task 8: Add Reports i18n Namespace and Sidebar Entry

**Files:**

- Create: `geo_saas/web/src/i18n/locales/zh-CN/reports.json`
- Create: `geo_saas/web/src/i18n/locales/en-US/reports.json`
- Modify: `geo_saas/web/src/i18n/index.ts`
- Modify: `geo_saas/web/src/i18n/types.ts`
- Modify: `geo_saas/web/src/i18n/locales/zh-CN/sidebar.json`
- Modify: `geo_saas/web/src/i18n/locales/en-US/sidebar.json`
- Modify: `geo_saas/web/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Add reports locale files**

Create `geo_saas/web/src/i18n/locales/zh-CN/reports.json`:

```json
{
  "__doc": "静态报告列表页与详情页。包含今日报告状态、历史报告、快照渲染、数据完整度和本地交互文案。",
  "list": {
    "title": "报告",
    "subtitle": "查看每日静态 GEO 报告快照。",
    "todayTitle": "今日报告",
    "historyTitle": "历史报告",
    "emptyHistory": "暂无历史报告",
    "loading": "正在加载报告...",
    "view": "查看报告",
    "generateAndView": "生成并查看",
    "waitingForData": "等待数据完成",
    "retrySnapshot": "重试快照生成"
  },
  "status": {
    "PENDING": "待生成",
    "MATERIALIZING": "生成中",
    "COMPLETED": "已完成",
    "NOT_READY": "数据未完成",
    "FAILED": "生成失败"
  },
  "detail": {
    "loading": "正在加载报告...",
    "notFound": "报告不存在",
    "back": "返回报告列表",
    "singleDayNotice": "当前报告基于单日数据生成，趋势图已切换为排名和分布视图。",
    "window": "数据窗口",
    "materializedAt": "生成时间",
    "sections": {
      "visibility": "可见度",
      "citation": "引用",
      "sentiment": "情感",
      "promptTopic": "Prompt 与 Topic",
      "appendix": "附录"
    }
  },
  "readiness": {
    "raw_results_missing": "今日尚未采集到原始结果。",
    "analyzed_results_missing": "今日数据尚未完成分析。",
    "same_day_analyzed_results_missing": "今日尚无已分析结果。",
    "visibility_missing": "可见度数据尚未生成。",
    "citation_missing": "引用数据尚未生成。",
    "sentiment_missing": "情感数据尚未生成。",
    "snapshot_materialization_failed": "报告快照生成失败。",
    "materialization_in_progress": "报告快照正在生成中。"
  },
  "completeness": {
    "title": "数据完整度",
    "rawResults": "原始结果",
    "analyzedResults": "已分析结果",
    "sameDayAnalyzed": "今日已分析",
    "analyzedPct": "分析完成率"
  }
}
```

Create `geo_saas/web/src/i18n/locales/en-US/reports.json` with matching keys:

```json
{
  "__doc": "Static report list and detail pages. Covers today's report state, historical reports, snapshot rendering, data completeness, and local interactions.",
  "list": {
    "title": "Reports",
    "subtitle": "View daily static GEO report snapshots.",
    "todayTitle": "Today's report",
    "historyTitle": "Report history",
    "emptyHistory": "No historical reports yet",
    "loading": "Loading reports...",
    "view": "View report",
    "generateAndView": "Generate and view",
    "waitingForData": "Waiting for data",
    "retrySnapshot": "Retry snapshot"
  },
  "status": {
    "PENDING": "Pending",
    "MATERIALIZING": "Generating",
    "COMPLETED": "Completed",
    "NOT_READY": "Data not ready",
    "FAILED": "Failed"
  },
  "detail": {
    "loading": "Loading report...",
    "notFound": "Report not found",
    "back": "Back to reports",
    "singleDayNotice": "This report is based on single-day data, so trend charts are replaced with rankings and distributions.",
    "window": "Data window",
    "materializedAt": "Generated at",
    "sections": {
      "visibility": "Visibility",
      "citation": "Citation",
      "sentiment": "Sentiment",
      "promptTopic": "Prompts and Topics",
      "appendix": "Appendix"
    }
  },
  "readiness": {
    "raw_results_missing": "No raw results have been collected for today.",
    "analyzed_results_missing": "Today's data has not finished analysis.",
    "same_day_analyzed_results_missing": "No analyzed results exist for today yet.",
    "visibility_missing": "Visibility data is not ready yet.",
    "citation_missing": "Citation data is not ready yet.",
    "sentiment_missing": "Sentiment data is not ready yet.",
    "snapshot_materialization_failed": "Report snapshot generation failed.",
    "materialization_in_progress": "Report snapshot generation is in progress."
  },
  "completeness": {
    "title": "Data completeness",
    "rawResults": "Raw results",
    "analyzedResults": "Analyzed results",
    "sameDayAnalyzed": "Analyzed today",
    "analyzedPct": "Analyzed percentage"
  }
}
```

- [ ] **Step 2: Register reports namespace**

Modify `geo_saas/web/src/i18n/index.ts`:

```typescript
import zhReports from "./locales/zh-CN/reports.json";
import enReports from "./locales/en-US/reports.json";
```

Add `"reports"` to `NAMESPACES`.

Add `reports: zhReports` and `reports: enReports` to the resources object.

- [ ] **Step 3: Register reports types**

Modify `geo_saas/web/src/i18n/types.ts`:

```typescript
import type reports from "./locales/zh-CN/reports.json";
```

Add:

```typescript
reports: typeof reports;
```

- [ ] **Step 4: Add sidebar key**

Modify both sidebar locale files:

```json
"reports": "报告"
```

and:

```json
"reports": "Reports"
```

- [ ] **Step 5: Add sidebar nav item**

Modify `geo_saas/web/src/components/layout/Sidebar.tsx`:

- Import `FileText` from `lucide-react`.
- Add `"reports"` to `NavItemKey`.
- Add `{ labelKey: "reports", path: "/reports", icon: FileText }` under the dashboards group.

- [ ] **Step 6: Run frontend build**

Run:

```bash
cd geo_saas/web && npm run build
```

Expected: no i18n namespace/type errors.

## Task 9: Add Reports List Page

**Files:**

- Create: `geo_saas/web/src/pages/reports/components/ReportStatusBadge.tsx`
- Create: `geo_saas/web/src/pages/reports/ReportsListPage.tsx`
- Modify: `geo_saas/web/src/App.tsx`

- [ ] **Step 1: Create status badge component**

Create `geo_saas/web/src/pages/reports/components/ReportStatusBadge.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import type { StaticReportStatus } from "@/lib/api/staticReports";

const STATUS_VARIANT: Record<StaticReportStatus, "default" | "secondary" | "destructive" | "outline"> = {
  PENDING: "outline",
  MATERIALIZING: "secondary",
  COMPLETED: "default",
  NOT_READY: "outline",
  FAILED: "destructive",
};

export function ReportStatusBadge({ status }: { status: StaticReportStatus }) {
  const { t } = useTranslation("reports");
  return <Badge variant={STATUS_VARIANT[status]}>{t(`status.${status}`)}</Badge>;
}
```

- [ ] **Step 2: Create reports list page**

Create `geo_saas/web/src/pages/reports/ReportsListPage.tsx`.

Implement:

- Load `clientId` from `useSaaS()`.
- Call `getTodayStaticReportStatus(clientId)` and `listStaticReports(clientId)`.
- If today's status is completed and has `report_id`, navigate to `/reports/static/${report_id}` when clicking view.
- If today's status is ready but no completed report exists, call `materializeTodayStaticReport(clientId)`, then navigate to returned report id.
- If not ready, show translated readiness reasons.

Use these imports:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Loader2, FileText, CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSaaS } from "@/contexts/SaaSContext";
import {
  getTodayStaticReportStatus,
  listStaticReports,
  materializeTodayStaticReport,
  type StaticReportMeta,
  type TodayReportStatusOut,
} from "@/lib/api/staticReports";
import { ReportStatusBadge } from "./components/ReportStatusBadge";
```

Use a local reason renderer:

```tsx
function reasonLabel(t: ReturnType<typeof useTranslation<"reports">>["t"], reason: string) {
  return t(`readiness.${reason}`, { defaultValue: reason });
}
```

Avoid native dialogs.

- [ ] **Step 3: Add routes**

Modify `geo_saas/web/src/App.tsx`:

```typescript
import ReportsListPage from "./pages/reports/ReportsListPage";
import StaticReportPage from "./pages/reports/StaticReportPage";
```

Add under the layout route:

```tsx
<Route path="reports" element={<ReportsListPage />} />
<Route path="reports/static/:reportId" element={<StaticReportPage />} />
```

StaticReportPage is created in the next task. If building after this task alone, create a temporary minimal component in Task 10 before running full build.

## Task 10: Add Static Report Detail Page

**Files:**

- Create: `geo_saas/web/src/pages/reports/components/DataCompletenessBanner.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticVisibilitySection.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticCitationSection.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticSentimentSection.tsx`
- Create: `geo_saas/web/src/pages/reports/components/StaticPromptTopicSection.tsx`
- Create: `geo_saas/web/src/pages/reports/StaticReportPage.tsx`

- [ ] **Step 1: Add data completeness banner**

Create `geo_saas/web/src/pages/reports/components/DataCompletenessBanner.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";

export function DataCompletenessBanner({ data }: { data: Record<string, any> }) {
  const { t } = useTranslation("reports");
  return (
    <Card className="border-border/60">
      <CardContent className="p-4 grid gap-3 sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">{t("completeness.rawResults")}</p>
          <p className="text-lg font-semibold">{data.raw_results ?? 0}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t("completeness.analyzedResults")}</p>
          <p className="text-lg font-semibold">{data.analyzed_results ?? 0}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t("completeness.sameDayAnalyzed")}</p>
          <p className="text-lg font-semibold">{data.same_day_analyzed_results ?? 0}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t("completeness.analyzedPct")}</p>
          <p className="text-lg font-semibold">{data.analyzed_pct ?? 0}%</p>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Add static section components**

Each section receives snapshot arrays and renders only local data.

`StaticVisibilitySection.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function StaticVisibilitySection({ data }: { data: any }) {
  const { t } = useTranslation("reports");
  const ranking = Array.isArray(data?.ranking) ? data.ranking : [];
  return (
    <section className="space-y-3">
      <h2 className="text-xl font-semibold">{t("detail.sections.visibility")}</h2>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("detail.sections.visibility")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {ranking.slice(0, 20).map((row: any, index: number) => (
            <div key={`${row.brand_name}-${index}`} className="flex items-center justify-between border-b py-2 last:border-0">
              <div>
                <p className="font-medium">{row.brand_name}</p>
                <p className="text-xs text-muted-foreground">{row.brand_role}</p>
              </div>
              <p className="text-sm font-semibold">{row.mention_count}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}
```

Create the citation, sentiment, and prompt/topic components with the same pattern:

- Citation rows use `source_domain` and `citation_count`.
- Sentiment rows use `sentiment`, `count`, and `avg_confidence`.
- Prompt/topic rows use `prompts.ranking` and `topics.ranking`.

- [ ] **Step 3: Add report detail page**

Create `geo_saas/web/src/pages/reports/StaticReportPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getStaticReport, type StaticReportDetail } from "@/lib/api/staticReports";
import { DataCompletenessBanner } from "./components/DataCompletenessBanner";
import { ReportStatusBadge } from "./components/ReportStatusBadge";
import { StaticVisibilitySection } from "./components/StaticVisibilitySection";
import { StaticCitationSection } from "./components/StaticCitationSection";
import { StaticSentimentSection } from "./components/StaticSentimentSection";
import { StaticPromptTopicSection } from "./components/StaticPromptTopicSection";

export default function StaticReportPage() {
  const { reportId } = useParams();
  const { t } = useTranslation("reports");
  const [report, setReport] = useState<StaticReportDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!reportId) return;
    setLoading(true);
    getStaticReport(reportId)
      .then(setReport)
      .catch(() => setReport(null))
      .finally(() => setLoading(false));
  }, [reportId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-muted-foreground">{t("detail.loading")}</span>
      </div>
    );
  }

  if (!report || !report.snapshot_json) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" asChild>
          <Link to="/reports"><ArrowLeft className="mr-2 h-4 w-4" />{t("detail.back")}</Link>
        </Button>
        <p className="text-muted-foreground">{t("detail.notFound")}</p>
      </div>
    );
  }

  const snapshot = report.snapshot_json;

  return (
    <div className="space-y-6 pb-10">
      <Button variant="ghost" asChild>
        <Link to="/reports"><ArrowLeft className="mr-2 h-4 w-4" />{t("detail.back")}</Link>
      </Button>

      <header className="space-y-3">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight">{snapshot.client?.name || t("list.title")}</h1>
          <ReportStatusBadge status={report.status} />
        </div>
        <p className="text-muted-foreground">
          {t("detail.window")}: {snapshot.report.window_start} – {snapshot.report.window_end}
        </p>
        {snapshot.report.rendering_mode === "single_day" && (
          <p className="rounded-md border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
            {t("detail.singleDayNotice")}
          </p>
        )}
      </header>

      <DataCompletenessBanner data={snapshot.data_completeness || {}} />
      <StaticVisibilitySection data={snapshot.visibility} />
      <StaticCitationSection data={snapshot.citations} />
      <StaticSentimentSection data={snapshot.sentiment} />
      <StaticPromptTopicSection prompts={snapshot.prompts} topics={snapshot.topics} />
    </div>
  );
}
```

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd geo_saas/web && npm run build
```

Expected: build succeeds with no TypeScript errors.

## Task 11: Add Admin Static Report Management

**Files:**

- Create: `geo_admin/src/routers/static_reports.py`
- Modify: `geo_admin/src/main.py`
- Create: `geo_admin/tests/test_static_reports_router.py`
- Modify: `geo_admin/web/src/api/client.ts`
- Create: `geo_admin/web/src/pages/StaticReportsPage.tsx`
- Modify: `geo_admin/web/src/App.tsx`
- Modify: `geo_admin/web/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Add Admin backend tests**

Create focused router tests that assert:

- Admin static report routes mount at `/static-reports` and `/static-reports/{report_id}` under the existing `/api` prefix.
- The list endpoint response model contains report rows plus pagination metadata.

- [ ] **Step 2: Add Admin read-only API**

Create `geo_admin/src/routers/static_reports.py`.

Requirements:

- `GET /static-reports` supports `page`, `limit`, `client_id`, `status`, `date_from`, and `date_to`.
- `GET /static-reports/{report_id}` returns metadata and `snapshot_json`.
- Queries read only from `geo_static_reports` and `geo_clients`.
- The router does not import Collector, Analyzer, SaaS snapshot builder, scheduler services, or LLM clients.
- The router is registered in `geo_admin/src/main.py` with `admin_auth_dependencies`.

- [ ] **Step 3: Add Admin frontend API helpers**

Modify `geo_admin/web/src/api/client.ts`:

- Add `StaticReportListRow`, `StaticReportDetail`, and pagination interfaces.
- Add `getStaticReports(params)` and `getStaticReport(reportId)`.

- [ ] **Step 4: Add Admin management page**

Create `geo_admin/web/src/pages/StaticReportsPage.tsx`.

UI behavior:

- Page title: `Static Reports`.
- Filters: client text/id filter, status dropdown, date-from/date-to inputs.
- Table columns: customer, report date, status, data window, rendering mode, generated time, error, actions.
- Detail action opens a custom Dialog showing metadata, warnings, data completeness, and section counts.
- Completed reports may show a rendered-report link if `snapshot_json` exists.
- No action triggers Collector, Analyzer, scheduler, or snapshot rebuild.

- [ ] **Step 5: Add Admin route and navigation**

Modify:

- `geo_admin/web/src/App.tsx`: add route `/static-reports`.
- `geo_admin/web/src/components/layout/Sidebar.tsx`: add `Static Reports` under the Analysis group.

- [ ] **Step 6: Verify Admin implementation**

Run:

```bash
cd geo_admin && src/venv/bin/python -m pytest tests/test_static_reports_router.py -q
cd geo_admin/web && npm run build
```

Expected:

- Admin backend tests pass.
- Admin frontend build passes.

## Task 12: Backend Integration Verification

**Files:**

- All backend files from Tasks 1-6.

- [ ] **Step 1: Run focused static report tests**

Run:

```bash
cd geo_saas && pytest \
  tests/test_static_reports_models.py \
  tests/test_static_reports_readiness.py \
  tests/test_static_reports_snapshot_builder.py \
  tests/test_static_reports_router.py \
  -q
```

Expected: all static report tests pass.

- [ ] **Step 2: Run SaaS router smoke tests**

Run:

```bash
cd geo_saas && pytest tests/test_router_import_smoke.py -q
```

Expected: router imports still pass.

- [ ] **Step 3: Run selected existing dashboard tests**

Run:

```bash
cd geo_saas && pytest \
  tests/test_visibility_prompt_metrics.py \
  tests/test_citation_rankings.py \
  tests/test_sentiment_config_filter.py \
  -q
```

Expected: existing dynamic dashboard tests still pass.

## Task 13: Frontend Integration Verification

**Files:**

- All frontend files from Tasks 7-10.

- [ ] **Step 1: Run frontend build**

Run:

```bash
cd geo_saas/web && npm run build
```

Expected: build succeeds.

- [ ] **Step 2: Run visible E2E only after implementation is complete**

Before visible E2E, read:

```bash
sed -n '1,220p' docs/local-dev/codex-visible-e2e.md
```

Then use the prescribed local stack:

- Admin UI: `http://localhost:6173`
- SaaS UI: `http://localhost:6174`
- Do not use port `6175`.

Manual checks:

- Reports sidebar entry appears in both languages.
- `/reports` loads for an authorized client.
- Today's card shows completed, not-ready, or materialize-ready state.
- Report detail renders without live dashboard API calls.
- Existing `/citation`, `/sentiment`, and `/insights/visibility` still render as before.

## Spec Coverage Review

This plan covers:

- Daily unique report table: Task 1.
- Shanghai date handling: Task 2.
- On-demand materialization: Tasks 3, 4, 5, 6.
- Sentiment readiness gate: Task 4.
- JSON snapshot storage: Tasks 1 and 5.
- SaaS Reports entry and pages: Tasks 8, 9, 10.
- Client authorization: Task 6.
- No Collector/Analyzer coupling: Scope Guard, Tasks 4-6.
- Admin read-only report management: Task 11.
- No dynamic dashboard behavior changes: Scope Guard and Tasks 12-13.
- i18n in zh-CN and en-US: Task 8.

## Execution Handoff

Plan complete. When implementation starts, use either:

1. **Subagent-Driven**: fresh implementation worker per task, with review between tasks.
2. **Inline Execution**: execute tasks in this session with checkpoints after each backend/frontend boundary.

Because the owner asked for no Git commands, both modes must leave changes unstaged and report file/test status in chat.
