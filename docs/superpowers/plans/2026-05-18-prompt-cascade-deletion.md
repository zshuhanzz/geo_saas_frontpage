# Prompt Cascade Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Git commit steps are intentionally omitted because the user will commit manually later.

**Goal:** Make SaaS Prompt deletion fully clean Collector and Analyzer fact data while preventing late async Collector/Analyzer writes from recreating deleted Prompt data.

**Architecture:** Add a shared `PromptCascadeDeletionService` in `geo_common` and route both single and batch SaaS Prompt deletion through it. The service deletes analyzer fact tables first, then collector result/task tables, then the prompt rows, all inside one transaction. Add writer-side guards in Collector and Analyzer so async callbacks or analyzer jobs skip rows whose `client_prompt_id` no longer exists for the tenant.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, shared `geo_common` services, existing SaaS/Collector/Analyzer database pools, pytest.

---

## File Structure

- Create: `geo_common/src/geo_common/services/prompt_deletion.py`
  - Owns all cascade delete SQL and returns structured deletion counts.
- Modify: `geo_common/src/geo_common/services/__init__.py`
  - Exports the new service for SaaS imports.
- Modify: `geo_saas/src/routers/prompts.py`
  - Replaces `PromptRepository.delete/delete_many` calls with `PromptCascadeDeletionService`.
- Modify: `geo_collector/src/result_ingestor.py`
  - Adds a transactional existence check before inserting `geo_results`.
- Modify: `geo_analyzer/src/pipeline/phase3_write.py`
  - Skips mention/citation writes when the Prompt has been deleted.
- Modify: `geo_analyzer/src/parsers/sentiment_parser.py`
  - Skips sentiment writes when the Prompt has been deleted.
- Create: `geo_common/tests/test_prompt_cascade_deletion.py`
  - Unit tests SQL ordering and count parsing with fake asyncpg connection.
- Modify/Create: `geo_saas/tests/test_prompts_cascade_delete.py`
  - Router-level tests for single and batch delete using a fake service.
- Modify/Create: `geo_collector/tests/test_result_ingestor_deleted_prompt.py`
  - Tests Collector skips writing results when Prompt no longer exists.
- Modify/Create: `geo_analyzer/tests/test_deleted_prompt_write_guards.py`
  - Tests Analyzer skips mention/citation/sentiment writes when Prompt no longer exists.
- Create: `migrations/063_prompt_cascade_delete_indexes.sql`
  - Adds indexes that make cascade deletion and writer guards fast. User runs manually.

---

## Task 1: Add Prompt Cascade Deletion Service

**Files:**
- Create: `geo_common/src/geo_common/services/prompt_deletion.py`
- Modify: `geo_common/src/geo_common/services/__init__.py`
- Test: `geo_common/tests/test_prompt_cascade_deletion.py`

- [ ] **Step 1: Write the failing tests**

Create `geo_common/tests/test_prompt_cascade_deletion.py` with fake asyncpg-style objects. Cover:

```python
import pytest

from geo_common.services.prompt_deletion import PromptCascadeDeletionService


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, prompt_rows):
        self.prompt_rows = prompt_rows
        self.fetch_calls = []
        self.execute_calls = []

    def transaction(self):
        return FakeTransaction()

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        if "FROM geo_client_prompts" in sql:
            return self.prompt_rows
        return []

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        if "geo_sentiment_themes" in sql:
            return "DELETE 2"
        if "geo_sentiment_results" in sql:
            return "DELETE 3"
        if "geo_citations" in sql:
            return "DELETE 4"
        if "geo_product_mentions" in sql:
            return "DELETE 5"
        if "geo_brand_mentions" in sql:
            return "DELETE 6"
        if "geo_results" in sql:
            return "DELETE 7"
        if "geo_tasks" in sql:
            return "DELETE 8"
        if "geo_client_prompts" in sql:
            return "DELETE 1"
        return "DELETE 0"


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_cascade_delete_deletes_downstream_before_prompts():
    conn = FakeConn(prompt_rows=[{"id": "11111111-1111-1111-1111-111111111111"}])
    service = PromptCascadeDeletionService(FakePool(conn))

    result = await service.delete_many(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ["11111111-1111-1111-1111-111111111111"],
    )

    tables = [call[0] for call in conn.execute_calls]
    assert "DELETE FROM geo_sentiment_themes" in tables[0]
    assert "DELETE FROM geo_sentiment_results" in tables[1]
    assert "DELETE FROM geo_citations" in tables[2]
    assert "DELETE FROM geo_product_mentions" in tables[3]
    assert "DELETE FROM geo_brand_mentions" in tables[4]
    assert "DELETE FROM geo_results" in tables[5]
    assert "DELETE FROM geo_tasks" in tables[6]
    assert "DELETE FROM geo_client_prompts" in tables[7]
    assert result.deleted_prompts == 1
    assert result.deleted_results == 7
    assert result.deleted_tasks == 8


@pytest.mark.asyncio
async def test_cascade_delete_ignores_prompt_ids_outside_client():
    conn = FakeConn(prompt_rows=[])
    service = PromptCascadeDeletionService(FakePool(conn))

    result = await service.delete_many(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ["22222222-2222-2222-2222-222222222222"],
    )

    assert result.deleted_prompts == 0
    assert conn.execute_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=geo_common/src python -m pytest geo_common/tests/test_prompt_cascade_deletion.py -q
```

Expected: import failure because `geo_common.services.prompt_deletion` does not exist.

- [ ] **Step 3: Implement the service**

Create `geo_common/src/geo_common/services/prompt_deletion.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .tenant import tenant_scoped


def _affected(status: str) -> int:
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (AttributeError, ValueError):
        return 0


@dataclass(frozen=True)
class PromptCascadeDeleteResult:
    requested_prompts: int
    matched_prompts: int
    deleted_sentiment_themes: int = 0
    deleted_sentiment_results: int = 0
    deleted_citations: int = 0
    deleted_product_mentions: int = 0
    deleted_brand_mentions: int = 0
    deleted_results: int = 0
    deleted_tasks: int = 0
    deleted_prompts: int = 0


class PromptCascadeDeletionService:
    """Deletes prompt-owned Collector and Analyzer fact data before prompt rows."""

    def __init__(self, pool):
        self._pool = pool

    @tenant_scoped
    async def delete_one(self, client_id: str, prompt_id: str) -> PromptCascadeDeleteResult:
        return await self.delete_many(client_id, [prompt_id])

    @tenant_scoped
    async def delete_many(self, client_id: str, prompt_ids: Iterable[str]) -> PromptCascadeDeleteResult:
        requested = [str(pid) for pid in prompt_ids]
        if not requested:
            return PromptCascadeDeleteResult(requested_prompts=0, matched_prompts=0)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT id
                    FROM geo_client_prompts
                    WHERE client_id = $1::uuid
                      AND id = ANY($2::uuid[])
                    """,
                    client_id,
                    requested,
                )
                matched = [str(row["id"]) for row in rows]
                if not matched:
                    return PromptCascadeDeleteResult(
                        requested_prompts=len(requested),
                        matched_prompts=0,
                    )

                counts = {
                    "deleted_sentiment_themes": _affected(await conn.execute(
                        "DELETE FROM geo_sentiment_themes",
                        matched,
                        client_id,
                    )),
                }
```

Then replace the placeholder-style first execute above with the actual SQL statements in this exact order:

```python
                deleted_sentiment_themes = _affected(await conn.execute(
                    """
                    DELETE FROM geo_sentiment_themes
                    WHERE client_id = $2::uuid
                      AND client_prompt_id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))
                deleted_sentiment_results = _affected(await conn.execute(
                    """
                    DELETE FROM geo_sentiment_results
                    WHERE client_id = $2::uuid
                      AND client_prompt_id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))
                deleted_citations = _affected(await conn.execute(
                    """
                    DELETE FROM geo_citations
                    WHERE client_id = $2::uuid
                      AND client_prompt_id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))
                deleted_product_mentions = _affected(await conn.execute(
                    """
                    DELETE FROM geo_product_mentions
                    WHERE client_id = $2::uuid
                      AND client_prompt_id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))
                deleted_brand_mentions = _affected(await conn.execute(
                    """
                    DELETE FROM geo_brand_mentions
                    WHERE client_id = $2::uuid
                      AND client_prompt_id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))
                deleted_results = _affected(await conn.execute(
                    """
                    DELETE FROM geo_results
                    WHERE client_id = $2::uuid
                      AND client_prompt_id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))
                deleted_tasks = _affected(await conn.execute(
                    """
                    DELETE FROM geo_tasks
                    WHERE client_id = $2::uuid
                      AND client_prompt_id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))
                deleted_prompts = _affected(await conn.execute(
                    """
                    DELETE FROM geo_client_prompts
                    WHERE client_id = $2::uuid
                      AND id = ANY($1::uuid[])
                    """,
                    matched,
                    client_id,
                ))

                return PromptCascadeDeleteResult(
                    requested_prompts=len(requested),
                    matched_prompts=len(matched),
                    deleted_sentiment_themes=deleted_sentiment_themes,
                    deleted_sentiment_results=deleted_sentiment_results,
                    deleted_citations=deleted_citations,
                    deleted_product_mentions=deleted_product_mentions,
                    deleted_brand_mentions=deleted_brand_mentions,
                    deleted_results=deleted_results,
                    deleted_tasks=deleted_tasks,
                    deleted_prompts=deleted_prompts,
                )
```

Modify `geo_common/src/geo_common/services/__init__.py`:

```python
from .prompt_deletion import PromptCascadeDeletionService, PromptCascadeDeleteResult
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=geo_common/src python -m pytest geo_common/tests/test_prompt_cascade_deletion.py -q
```

Expected: 2 passed.

---

## Task 2: Route SaaS Prompt Deletion Through Cascade Service

**Files:**
- Modify: `geo_saas/src/routers/prompts.py`
- Test: `geo_saas/tests/test_prompts_cascade_delete.py`

- [ ] **Step 1: Write router tests**

Create or extend `geo_saas/tests/test_prompts_cascade_delete.py` to assert the router uses the cascade service for both routes. Use monkeypatch to replace `PromptCascadeDeletionService` with a fake class.

```python
from dataclasses import dataclass

import pytest


@dataclass
class FakeDeleteResult:
    deleted_prompts: int


class FakeCascadeService:
    calls = []

    def __init__(self, pool):
        self.pool = pool

    async def delete_many(self, client_id, prompt_ids):
        self.calls.append(("many", str(client_id), [str(pid) for pid in prompt_ids]))
        return FakeDeleteResult(deleted_prompts=len(prompt_ids))

    async def delete_one(self, client_id, prompt_id):
        self.calls.append(("one", str(client_id), str(prompt_id)))
        return FakeDeleteResult(deleted_prompts=1)
```

The test should call `batch_delete_prompts(...)` and `delete_prompt(...)` directly with a fake pool and assert `FakeCascadeService.calls`.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=geo_saas/src:geo_common/src geo_saas/src/venv/bin/python -m pytest geo_saas/tests/test_prompts_cascade_delete.py -q
```

Expected: fail because router still imports and uses `PromptRepository`.

- [ ] **Step 3: Update router**

In `geo_saas/src/routers/prompts.py`, add:

```python
from geo_common.services import PromptCascadeDeletionService
```

Replace batch delete body:

```python
    service = PromptCascadeDeletionService(pool)
    result = await service.delete_many(str(client_id), prompt_ids)
    return BatchDeleteOut(deleted=result.deleted_prompts)
```

Replace single delete body:

```python
    service = PromptCascadeDeletionService(pool)
    await service.delete_one(str(client_id), str(prompt_id))
    return StatusOkOut(status="ok")
```

- [ ] **Step 4: Run SaaS router tests**

Run:

```bash
PYTHONPATH=geo_saas/src:geo_common/src geo_saas/src/venv/bin/python -m pytest geo_saas/tests/test_router_import_smoke.py geo_saas/tests/test_prompts_cascade_delete.py -q
```

Expected: all pass.

---

## Task 3: Add Collector Deleted-Prompt Guard

**Files:**
- Modify: `geo_collector/src/result_ingestor.py`
- Test: `geo_collector/tests/test_result_ingestor_deleted_prompt.py`

- [ ] **Step 1: Add a focused helper test**

Create `geo_collector/tests/test_result_ingestor_deleted_prompt.py`:

```python
import pytest

from src.result_ingestor import _prompt_exists_for_client


class FakeConn:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self.value


@pytest.mark.asyncio
async def test_prompt_exists_for_client_returns_true():
    conn = FakeConn(True)
    ok = await _prompt_exists_for_client(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )
    assert ok is True
    assert "geo_client_prompts" in conn.calls[0][0]


@pytest.mark.asyncio
async def test_prompt_exists_for_client_returns_false():
    conn = FakeConn(None)
    ok = await _prompt_exists_for_client(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )
    assert ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=geo_collector/src python -m pytest geo_collector/tests/test_result_ingestor_deleted_prompt.py -q
```

Expected: import failure because `_prompt_exists_for_client` does not exist.

- [ ] **Step 3: Add helper and guard**

In `geo_collector/src/result_ingestor.py`, add:

```python
async def _prompt_exists_for_client(conn, client_id: str, client_prompt_id: str) -> bool:
    return bool(await conn.fetchval(
        """
        SELECT 1
        FROM geo_client_prompts
        WHERE client_id = $1::uuid
          AND id = $2::uuid
        """,
        client_id,
        client_prompt_id,
    ))
```

Inside the existing DB transaction, before inserting into `geo_results`, add:

```python
                prompt_still_exists = await _prompt_exists_for_client(
                    conn,
                    str(insert_row.get("client_id")),
                    str(insert_row.get("client_prompt_id")),
                )
                if not prompt_still_exists:
                    logger.info(
                        "[INGESTOR-SKIP] client_prompt_id no longer exists; skip stale result | "
                        "task_id=%s | client_prompt_id=%s",
                        task_id,
                        insert_row.get("client_prompt_id"),
                    )
                    return
```

- [ ] **Step 4: Run Collector tests**

Run:

```bash
PYTHONPATH=geo_collector/src python -m pytest geo_collector/tests/test_result_ingestor_deleted_prompt.py -q
```

Expected: 2 passed.

---

## Task 4: Add Analyzer Mention/Citation Deleted-Prompt Guard

**Files:**
- Modify: `geo_analyzer/src/pipeline/phase3_write.py`
- Test: `geo_analyzer/tests/test_deleted_prompt_write_guards.py`

- [ ] **Step 1: Add helper tests**

Create `geo_analyzer/tests/test_deleted_prompt_write_guards.py`:

```python
import pytest

from src.pipeline.phase3_write import _prompt_exists_for_client


class FakeConn:
    def __init__(self, value):
        self.value = value

    async def fetchval(self, sql, *args):
        return self.value


@pytest.mark.asyncio
async def test_phase3_prompt_guard_true():
    assert await _prompt_exists_for_client(
        FakeConn(True),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )


@pytest.mark.asyncio
async def test_phase3_prompt_guard_false():
    assert not await _prompt_exists_for_client(
        FakeConn(None),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=geo_analyzer/src python -m pytest geo_analyzer/tests/test_deleted_prompt_write_guards.py -q
```

Expected: import failure because helper does not exist.

- [ ] **Step 3: Add guard helper and skip stale result groups**

In `geo_analyzer/src/pipeline/phase3_write.py`, add:

```python
async def _prompt_exists_for_client(conn, client_id: str, client_prompt_id: str) -> bool:
    return bool(await conn.fetchval(
        """
        SELECT 1
        FROM geo_client_prompts
        WHERE client_id = $1::uuid
          AND id = $2::uuid
        """,
        client_id,
        client_prompt_id,
    ))
```

At the top of the `for result, brand_mentions, product_mentions, citations in parse_result.per_result:` loop, add:

```python
        if not await _prompt_exists_for_client(
            conn,
            str(result["client_id"]),
            str(result["client_prompt_id"]),
        ):
            logger.info(
                "[Phase3] Skip stale analyzer writes because prompt was deleted | result_id=%s | client_prompt_id=%s",
                result["result_id"],
                result["client_prompt_id"],
            )
            continue
```

- [ ] **Step 4: Run Analyzer tests**

Run:

```bash
PYTHONPATH=geo_analyzer/src python -m pytest geo_analyzer/tests/test_deleted_prompt_write_guards.py -q
```

Expected: 2 passed.

---

## Task 5: Add Analyzer Sentiment Deleted-Prompt Guard

**Files:**
- Modify: `geo_analyzer/src/parsers/sentiment_parser.py`
- Test: extend `geo_analyzer/tests/test_deleted_prompt_write_guards.py`

- [ ] **Step 1: Add sentiment helper tests**

Extend `geo_analyzer/tests/test_deleted_prompt_write_guards.py`:

```python
from src.parsers.sentiment_parser import _prompt_exists_for_client as sentiment_prompt_exists


@pytest.mark.asyncio
async def test_sentiment_prompt_guard_true():
    assert await sentiment_prompt_exists(
        FakeConn(True),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )


@pytest.mark.asyncio
async def test_sentiment_prompt_guard_false():
    assert not await sentiment_prompt_exists(
        FakeConn(None),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=geo_analyzer/src python -m pytest geo_analyzer/tests/test_deleted_prompt_write_guards.py -q
```

Expected: import failure from `src.parsers.sentiment_parser`.

- [ ] **Step 3: Add sentiment guard**

In `geo_analyzer/src/parsers/sentiment_parser.py`, add:

```python
async def _prompt_exists_for_client(conn, client_id: str, client_prompt_id: str) -> bool:
    return bool(await conn.fetchval(
        """
        SELECT 1
        FROM geo_client_prompts
        WHERE client_id = $1::uuid
          AND id = $2::uuid
        """,
        client_id,
        client_prompt_id,
    ))
```

Inside `process_batch`, after extracting `client_id, client_prompt_id`, add:

```python
        if not await _prompt_exists_for_client(conn, str(client_id), str(client_prompt_id)):
            logger.info(
                "[SENTIMENT-A] Skip stale sentiment writes because prompt was deleted | result_id=%s | client_prompt_id=%s",
                row_id,
                client_prompt_id,
            )
            continue
```

- [ ] **Step 4: Run Analyzer tests**

Run:

```bash
PYTHONPATH=geo_analyzer/src python -m pytest geo_analyzer/tests/test_deleted_prompt_write_guards.py -q
```

Expected: all guard tests pass.

---

## Task 6: Add Database Index Migration

**Files:**
- Create: `migrations/063_prompt_cascade_delete_indexes.sql`

- [ ] **Step 1: Create migration SQL**

Create `migrations/063_prompt_cascade_delete_indexes.sql`:

```sql
-- 063_prompt_cascade_delete_indexes.sql
-- Speeds up Prompt cascade deletion and stale async writer guards.
-- Run manually in Cloud SQL.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_geo_results_client_prompt
    ON geo_results(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_tasks_client_prompt
    ON geo_tasks(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_brand_mentions_client_prompt
    ON geo_brand_mentions(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_product_mentions_client_prompt
    ON geo_product_mentions(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_citations_client_prompt
    ON geo_citations(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_sentiment_results_client_prompt
    ON geo_sentiment_results(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_sentiment_themes_client_prompt
    ON geo_sentiment_themes(client_id, client_prompt_id);

COMMIT;
```

- [ ] **Step 2: Syntax sanity check**

Run no DB command. Manually inspect SQL for only `CREATE INDEX IF NOT EXISTS`; user will run it in Cloud SQL.

---

## Task 7: Full Verification

**Files:**
- All changed files above.

- [ ] **Step 1: Run common tests**

Run:

```bash
PYTHONPATH=geo_common/src python -m pytest geo_common/tests/test_prompt_cascade_deletion.py -q
```

Expected: pass.

- [ ] **Step 2: Run SaaS tests**

Run:

```bash
PYTHONPATH=geo_saas/src:geo_common/src geo_saas/src/venv/bin/python -m pytest geo_saas/tests/test_router_import_smoke.py geo_saas/tests/test_prompts_cascade_delete.py -q
```

Expected: pass.

- [ ] **Step 3: Run Collector tests**

Run:

```bash
PYTHONPATH=geo_collector/src python -m pytest geo_collector/tests/test_result_ingestor_deleted_prompt.py -q
```

Expected: pass.

- [ ] **Step 4: Run Analyzer tests**

Run:

```bash
PYTHONPATH=geo_analyzer/src python -m pytest geo_analyzer/tests/test_deleted_prompt_write_guards.py -q
```

Expected: pass.

- [ ] **Step 5: Run import smoke checks**

Run:

```bash
PYTHONPATH=geo_common/src python - <<'PY'
from geo_common.services import PromptCascadeDeletionService
print(PromptCascadeDeletionService.__name__)
PY
```

Expected output:

```text
PromptCascadeDeletionService
```

---

## Self-Review

- Spec coverage:
  - UI deletion triggers full cascade: Task 1 and Task 2.
  - Collector stale result guard: Task 3.
  - Analyzer mention/citation guard: Task 4.
  - Analyzer sentiment guard: Task 5.
  - Do not delete Agent Tasks or reports: no task touches `geo_agent_tasks` or report export tables.
  - Manual DB control: Task 6 creates SQL migration only.
- Placeholder scan: no `TBD`, no deferred implementation placeholders.
- Type consistency:
  - Service class is consistently named `PromptCascadeDeletionService`.
  - Result dataclass is consistently named `PromptCascadeDeleteResult`.
  - Public methods are `delete_one(client_id, prompt_id)` and `delete_many(client_id, prompt_ids)`.
