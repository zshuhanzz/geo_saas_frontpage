"""Non-blocking, bounded, batched audit writer.

Audit is operational telemetry, not a transactional business record. Queue
overflow or database errors deliberately drop events so audit can never
reduce API availability.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

_STOP = object()


class AsyncAuditWriter:
    def __init__(
        self,
        pool: Any,
        *,
        queue_size: int = 5000,
        batch_size: int = 100,
        flush_interval_seconds: float = 0.25,
    ) -> None:
        self._pool = pool
        self._queue: asyncio.Queue[Mapping[str, Any] | object] = asyncio.Queue(
            maxsize=queue_size
        )
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self.dropped_events = 0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="geo-user-audit-writer",
            )

    def enqueue(self, event: Mapping[str, Any]) -> bool:
        try:
            self._queue.put_nowait(dict(event))
            return True
        except asyncio.QueueFull:
            self.dropped_events += 1
            if self.dropped_events == 1 or self.dropped_events % 100 == 0:
                logger.warning(
                    "Dropping SaaS audit events because queue is full; dropped=%s",
                    self.dropped_events,
                )
            return False

    async def close(self, timeout_seconds: float = 2.0) -> None:
        task = self._task
        if task is None:
            return
        try:
            self._queue.put_nowait(_STOP)
        except asyncio.QueueFull:
            # The worker will continue draining; make room without blocking.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(_STOP)
        try:
            await asyncio.wait_for(task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            logger.warning("Audit writer shutdown timed out; remaining events dropped")
        finally:
            self._task = None

    async def _run(self) -> None:
        stopping = False
        while not stopping:
            item = await self._queue.get()
            if item is _STOP:
                self._queue.task_done()
                break

            batch: list[Mapping[str, Any]] = [item]
            deadline = asyncio.get_running_loop().time() + self._flush_interval_seconds
            while len(batch) < self._batch_size:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    break
                if next_item is _STOP:
                    self._queue.task_done()
                    stopping = True
                    break
                batch.append(next_item)

            await self._write_batch(batch)
            for _ in batch:
                self._queue.task_done()

        # A bounded best-effort final drain. The close() timeout remains the
        # ultimate availability guard.
        final_batch: list[Mapping[str, Any]] = []
        while len(final_batch) < self._batch_size:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is not _STOP:
                final_batch.append(item)
            self._queue.task_done()
        if final_batch:
            await self._write_batch(final_batch)

    async def _write_batch(self, batch: list[Mapping[str, Any]]) -> None:
        if not batch:
            return
        values = [
            (
                event.get("user_id"),
                event.get("client_id"),
                event.get("event_type", "api_action"),
                event.get("action_key"),
                event.get("action_label"),
                event.get("route"),
                event.get("method"),
                event.get("status_code"),
                event.get("target_type"),
                event.get("target_id"),
                json.dumps(
                    event.get("metadata") or {},
                    ensure_ascii=False,
                    default=str,
                ),
                event.get("ip_address"),
                event.get("user_agent"),
            )
            for event in batch
        ]
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO geo_user_audit_events (
                        user_id, client_id, event_type, action_key, action_label,
                        route, method, status_code, target_type, target_id,
                        metadata, ip_address, user_agent
                    )
                    VALUES (
                        $1::uuid, $2::uuid, $3, $4, $5,
                        $6, $7, $8, $9, $10, $11::jsonb, $12, $13
                    )
                    """,
                    values,
                )
        except Exception:
            self.dropped_events += len(batch)
            logger.warning(
                "Best-effort audit batch write failed; dropped=%s batch_size=%s",
                self.dropped_events,
                len(batch),
                exc_info=True,
            )
