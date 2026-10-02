"""
UPSERT discovered candidates into ``geo_settings_candidates``.

Each row is keyed by ``(client_id, candidate_string, candidate_type)``.
On conflict we:
- bump ``frequency``
- merge ``source`` so a candidate that came from both ``llm_batch`` and
  ``n_gram`` ends up with ``"llm_batch+n_gram"``
- union ``sample_response_ids`` (capped at 10 distinct IDs)
- shallow-merge metadata JSON

Phase 2.5b: ``upsert_candidates`` is now async and uses asyncpg's
``$``-placeholder syntax. Metadata is sent as a Python dict thanks to the
JSONB codec registered on the pool — no manual ``json.dumps`` needed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Set


logger = logging.getLogger("LLMBatchDiscovery.upsert")


VALID_CANDIDATE_TYPES = {
    "brand", "shadow_brand", "peer",
    "own_product", "shadow_product", "peer_product",
}


_UPSERT_SQL = """
    INSERT INTO geo_settings_candidates (
        client_id, candidate_string, candidate_type, source,
        frequency, first_seen, last_seen, status,
        sample_response_ids, metadata
    ) VALUES (
        $1, $2, $3, 'llm_batch',
        1, NOW(), NOW(), 'pending',
        $4, $5
    )
    ON CONFLICT (client_id, candidate_string, candidate_type) DO UPDATE SET
        frequency = geo_settings_candidates.frequency + 1,
        last_seen = NOW(),
        source = CASE
            WHEN geo_settings_candidates.source = EXCLUDED.source
                THEN geo_settings_candidates.source
            WHEN position(EXCLUDED.source in geo_settings_candidates.source) > 0
                THEN geo_settings_candidates.source
            ELSE geo_settings_candidates.source || '+' || EXCLUDED.source
        END,
        sample_response_ids = (
            SELECT ARRAY(
                SELECT DISTINCT unnest(
                    COALESCE(geo_settings_candidates.sample_response_ids, ARRAY[]::int[])
                    || COALESCE(EXCLUDED.sample_response_ids, ARRAY[]::int[])
                )
                LIMIT 10
            )
        ),
        metadata = COALESCE(geo_settings_candidates.metadata, '{}'::jsonb) || EXCLUDED.metadata
"""


async def upsert_candidates(
    conn,
    client_id: str,
    candidates: List[Dict[str, Any]],
    known_lc: Set[str],
    sample_response_ids: List[int],
) -> int:
    """UPSERT the candidates list, return the number of rows actually touched.

    Skips:
    - Empty ``string`` or unknown ``type``.
    - Candidates whose lowercased string is already in ``known_lc`` (defensive
      — Gemini occasionally re-emits known items).
    """
    if not candidates:
        return 0

    touched = 0
    async with conn.transaction():
        for c in candidates:
            cstr = (c.get("string") or "").strip()
            ctype = (c.get("type") or "").strip()
            if not cstr or ctype not in VALID_CANDIDATE_TYPES:
                continue
            if cstr.lower() in known_lc:
                continue
            reasoning = (c.get("reasoning") or "")[:500]
            meta = {
                "reasoning": reasoning,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                "via": "llm_batch",
            }
            await conn.execute(
                _UPSERT_SQL,
                client_id,
                cstr,
                ctype,
                list(sample_response_ids[:3]),
                meta,
            )
            touched += 1
    return touched
