"""
Sentiment Parser — Phase A (extraction) + Phase B (normalization)

Phase A: Called per batch of geo_results. Uses Gemini to extract raw
         sentiment label and themes from each AI response text.

Phase B: Called once per Analyzer run. Normalizes newly extracted
         theme names against the persistent theme dictionary, merging
         synonyms and persisting genuinely new themes.

Phase 2.5b: every public function is now async. Gemini calls go through
``client.aio.models.generate_content`` so the event loop is never blocked
on a remote API call. DB I/O is asyncpg with $-placeholders.

File-size note (Phase 2.5b audit)
---------------------------------
At ~390 lines this module sits at the high end of the codebase's comfort
zone, but the seams aren't clean: the two public functions
(``parse_sentiment_batch`` / ``normalize_themes``) share the
``_get_gemini_client_and_model`` cache, the Gemini-call helpers are tightly
coupled to their phase's prompt template, and most of the line count is the
prompt strings themselves. Splitting would create 3-4 files mostly full of
re-imports without improving readability. Left intentionally as one file.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from geo_common.llm import resolve_model_region

logger = logging.getLogger(__name__)

SENTIMENT_VALUES = [
    "Positive",
    "Mixed/Neutral",
    "Negative",
    "Insufficient Evidence",
]
THEME_SENTIMENT_VALUES = ["Positive", "Mixed/Neutral", "Negative"]
SENTIMENT_CLASSIFIER_VERSION = "sentiment-v2"
SENTIMENT_CONTEXT_MAX_CHARS = 5000
_TARGET_WINDOW_BEFORE = 700
_TARGET_WINDOW_AFTER = 900
_FINAL_CONTEXT_CHARS = 1400
_REASON_CODES = {
    "POSITIVE_RECOMMENDATION",
    "NEGATIVE_CORE_FIT",
    "MIXED_TRADEOFF",
    "NEUTRAL_INFORMATIONAL",
    "NO_SUBSTANTIVE_EVIDENCE",
}
_DEFAULT_REASON_CODE = {
    "Positive": "POSITIVE_RECOMMENDATION",
    "Mixed/Neutral": "MIXED_TRADEOFF",
    "Negative": "NEGATIVE_CORE_FIT",
    "Insufficient Evidence": "NO_SUBSTANTIVE_EVIDENCE",
}


def _target_entity_terms(target_entities: Dict[str, List[str]]) -> List[str]:
    """Expand formatted target labels into names and aliases for text matching."""
    terms: List[str] = []
    seen: set[str] = set()
    for label in [
        *(target_entities.get("brands") or []),
        *(target_entities.get("products") or []),
    ]:
        value = (label or "").strip()
        if not value:
            continue
        base, marker, aliases_text = value.partition(" (aliases:")
        candidates = [base.strip()]
        if marker and aliases_text.endswith(")"):
            candidates.extend(alias.strip() for alias in aliases_text[:-1].split(","))
        for candidate in candidates:
            key = candidate.casefold()
            if candidate and key not in seen:
                seen.add(key)
                terms.append(candidate)
    return terms


def _entity_term_pattern(term: str) -> re.Pattern[str]:
    """Build a target matcher that works for both Latin and CJK names.

    ``\\w`` includes CJK characters in Python, so ASCII-style word boundaries
    reject normal Chinese prose such as ``即梦在...``.  CJK/mixed names are
    matched literally; Latin-only names retain boundaries to avoid matching a
    longer identifier such as ``DreaminaPro``.
    """
    escaped = re.escape(term)
    if any(ord(char) > 127 for char in term):
        return re.compile(escaped, re.IGNORECASE)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def strip_entity_citation_markers(text: str, entity_terms: List[str]) -> str:
    """Remove target labels used only as ``Source+N`` citation markers.

    The removal is target-aware and deliberately narrow: a normal prose mention
    remains untouched, while ``Dreamina+1`` cannot create customer sentiment.
    """
    cleaned = text or ""
    for term in sorted({t.strip() for t in entity_terms if t and t.strip()}, key=len, reverse=True):
        left_boundary = "" if any(ord(char) > 127 for char in term) else r"(?<!\w)"
        right_boundary = "" if any(ord(char) > 127 for char in term) else r"(?!\w)"
        cleaned = re.sub(
            rf"{left_boundary}{re.escape(term)}\s*\+\d+{right_boundary}",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def _select_sentiment_context(
    text: str,
    target_entities: Dict[str, List[str]],
) -> str:
    """Select target evidence windows plus the answer's final conclusion.

    This replaces the old first-3,000-character truncation, which could retain
    setup prose while dropping the decisive comparison verdict.
    """
    terms = _target_entity_terms(target_entities)
    cleaned = strip_entity_citation_markers(text or "", terms).strip()
    if len(cleaned) <= SENTIMENT_CONTEXT_MAX_CHARS:
        return cleaned

    windows: List[Tuple[int, int]] = []
    for term in terms:
        try:
            pattern = _entity_term_pattern(term)
        except re.error:
            continue
        for match in pattern.finditer(cleaned):
            windows.append((
                max(0, match.start() - _TARGET_WINDOW_BEFORE),
                min(len(cleaned), match.end() + _TARGET_WINDOW_AFTER),
            ))

    merged: List[Tuple[int, int]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    target_context = "\n…\n".join(cleaned[start:end].strip() for start, end in merged)
    final_context = cleaned[-_FINAL_CONTEXT_CHARS:].strip()
    if not target_context:
        return final_context

    target_budget = SENTIMENT_CONTEXT_MAX_CHARS - len(final_context) - 3
    selected = f"{target_context[:max(0, target_budget)]}\n…\n{final_context}"
    return selected[-SENTIMENT_CONTEXT_MAX_CHARS:]


def _validated_evidence(value: Any, context_text: str) -> List[str]:
    """Keep short, verbatim evidence excerpts that exist in the supplied text."""
    candidates = value if isinstance(value, list) else []
    context_folded = " ".join((context_text or "").split()).casefold()
    evidence: List[str] = []
    for raw in candidates[:3]:
        excerpt = raw.get("excerpt") if isinstance(raw, dict) else raw
        excerpt = " ".join(str(excerpt or "").split()).strip()
        if not excerpt or len(excerpt) > 600:
            continue
        if excerpt.casefold() not in context_folded:
            continue
        evidence.append(excerpt)
    return evidence


def _has_target_scoped_evidence(
    evidence: List[str],
    context_text: str,
    target_entities: Dict[str, List[str]],
) -> bool:
    """Require at least one evidence excerpt to share a sentence with a target.

    This is a deterministic guard for Negative labels. Gemini may quote a
    competitor-only sentence verbatim; verbatim presence alone is not enough
    to attribute that statement to the customer.
    """
    target_terms = _target_entity_terms(target_entities)
    if not evidence or not target_terms:
        return False

    sentence_fragments = [
        " ".join(fragment.split()).strip()
        for fragment in re.split(r"(?<=[.!?。！？])|[\r\n]+", context_text or "")
        if fragment.strip()
    ]
    for excerpt in evidence:
        excerpt_key = " ".join(excerpt.split()).strip().casefold().rstrip(".!?。！？")
        if not excerpt_key:
            continue
        for sentence in sentence_fragments:
            sentence_key = sentence.casefold().rstrip(".!?。！？")
            if excerpt_key not in sentence_key:
                continue
            for term in target_terms:
                if _entity_term_pattern(term).search(sentence):
                    return True
    return False


def _normalize_extraction_item(
    item: Any,
    *,
    model_id: str,
    context_text: str,
    target_entities: Optional[Dict[str, List[str]]] = None,
) -> Optional[dict]:
    """Validate the V2 JSON contract before any value reaches Postgres."""
    if not isinstance(item, dict) or item.get("sentiment") not in SENTIMENT_VALUES:
        return None

    sentiment = item["sentiment"]
    evidence = _validated_evidence(item.get("evidence"), context_text)
    if (
        sentiment == "Negative"
        and target_entities
        and not _has_target_scoped_evidence(evidence, context_text, target_entities)
    ):
        sentiment = "Insufficient Evidence"
        evidence = []
    if sentiment != "Insufficient Evidence" and not evidence:
        sentiment = "Insufficient Evidence"

    try:
        confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    reason_code = item.get("reason_code")
    if reason_code not in _REASON_CODES or sentiment == "Insufficient Evidence":
        reason_code = _DEFAULT_REASON_CODE[sentiment]

    themes: List[dict] = []
    if sentiment != "Insufficient Evidence":
        for theme in item.get("themes", []):
            if not isinstance(theme, dict):
                continue
            theme_name = " ".join(str(theme.get("theme") or "").split()).strip()
            theme_sentiment = theme.get("sentiment")
            excerpt = " ".join(str(theme.get("excerpt") or "").split()).strip()
            if (
                theme_name
                and theme_sentiment in THEME_SENTIMENT_VALUES
                and excerpt
                and excerpt.casefold() in " ".join(context_text.split()).casefold()
                and (
                    not target_entities
                    or _has_target_scoped_evidence(
                        [excerpt], context_text, target_entities
                    )
                )
            ):
                themes.append({
                    "theme": theme_name,
                    "sentiment": theme_sentiment,
                    "excerpt": excerpt[:1000],
                })

    return {
        **item,
        "sentiment": sentiment,
        "confidence": confidence,
        "themes": themes[:5],
        "classifier_version": SENTIMENT_CLASSIFIER_VERSION,
        "model_id": model_id,
        "reason_code": reason_code,
        "evidence": evidence,
    }


async def _prompt_exists_for_client(
    conn, client_id: str, client_prompt_id: str
) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
            FROM geo_client_prompts
            WHERE client_id = $1::uuid
              AND id = $2::uuid
            FOR KEY SHARE
            """,
            client_id,
            client_prompt_id,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE A — Per-batch extraction
# ─────────────────────────────────────────────────────────────────────────────

async def parse_sentiment_batch(
    conn,
    batch: List[Tuple],   # [(result_id, text, client_id, client_prompt_id, task_id, executed_at), ...]
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> int:
    """
    Phase A: For each (result_id, text) in the batch, call Gemini once to
    extract: four-state overall sentiment, confidence (0-1), and rated themes
    (list of {theme, sentiment, excerpt}).

    Results are written directly to geo_sentiment_results and
    geo_sentiment_themes.  Theme names are raw at this stage — normalization
    happens in Phase B.
    """
    if not batch:
        return 0

    results = await extract_sentiment_results(
        batch,
        model_id=model_id,
        model_region_overrides=model_region_overrides,
    )
    return await write_sentiment_results(conn, batch, results)


async def extract_sentiment_results(
    batch: List[Tuple],
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> Dict[int, dict]:
    """Extract sentiment, splitting failed/partial batches down to rows.

    This helper performs Gemini calls only. Call ``write_sentiment_results``
    inside a short write transaction to persist returned data.
    """

    if model_region_overrides:
        results = await _gemini_extract_sentiment(
            batch,
            model_id=model_id,
            model_region_overrides=model_region_overrides,
        )
    else:
        results = await _gemini_extract_sentiment(batch, model_id=model_id)

    missing_rows = [row for row in batch if row[0] not in results]
    if missing_rows and len(batch) > 1:
        logger.warning(
            "[SENTIMENT-A] Sentiment extraction returned %d/%d results; "
            "retrying %d missing rows with smaller batches.",
            len(results),
            len(batch),
            len(missing_rows),
        )
        midpoint = max(1, len(missing_rows) // 2)
        results.update(await extract_sentiment_results(
            missing_rows[:midpoint],
            model_id=model_id,
            model_region_overrides=model_region_overrides,
        ))
        results.update(await extract_sentiment_results(
            missing_rows[midpoint:],
            model_id=model_id,
            model_region_overrides=model_region_overrides,
        ))
    elif missing_rows:
        logger.warning(
            "[SENTIMENT-A] Sentiment extraction returned no result for result_id=%s",
            batch[0][0],
        )

    return results


async def write_sentiment_results(
    conn,
    batch: List[Tuple],
    results: Dict[int, dict],
) -> int:
    """Persist extracted sentiment rows and themes."""
    return await _write_sentiment_results(conn, batch, results)


async def _write_sentiment_results(
    conn,
    batch: List[Tuple],
    results: Dict[int, dict],
) -> int:
    """Persist extracted sentiment rows and themes."""
    written = 0
    for row_id, sentiment_data in results.items():
        if not isinstance(sentiment_data, dict):
            continue
        # Find original row metadata
        original = next((r for r in batch if r[0] == row_id), None)
        if not original:
            continue
        _result_id, _text, client_id, client_prompt_id, task_id, executed_at = original[:6]

        sentiment = sentiment_data.get("sentiment")
        if sentiment not in SENTIMENT_VALUES:
            logger.warning(
                "[SENTIMENT-A] Skip invalid sentiment label for result_id=%s: %r",
                row_id,
                sentiment,
            )
            continue
        confidence = sentiment_data.get("confidence", 0.5)
        classifier_version = sentiment_data.get(
            "classifier_version", SENTIMENT_CLASSIFIER_VERSION
        )
        classifier_model_id = sentiment_data.get("model_id")
        reason_code = sentiment_data.get(
            "reason_code", _DEFAULT_REASON_CODE[sentiment]
        )
        evidence = sentiment_data.get("evidence")
        if not isinstance(evidence, list):
            evidence = []

        # The caller already owns the batch transaction. Use a nested
        # transaction (an asyncpg savepoint) per result so one rejected row
        # cannot poison that outer transaction and prevent later rows from
        # being processed.
        try:
            async with conn.transaction():
                if not await _prompt_exists_for_client(
                    conn, str(client_id), str(client_prompt_id)
                ):
                    logger.info(
                        "[SENTIMENT-A] Skip stale sentiment writes because prompt "
                        "was deleted | result_id=%s | client_prompt_id=%s",
                        row_id,
                        client_prompt_id,
                    )
                    continue

                inserted_id = await conn.fetchval(
                    """
                    INSERT INTO geo_sentiment_results
                    (client_prompt_id, task_id, result_id, client_id, sentiment,
                     confidence, executed_at, classifier_version, model_id,
                     reason_code, evidence)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    str(client_prompt_id),
                    str(task_id) if task_id else None,
                    row_id,
                    str(client_id),
                    sentiment,
                    confidence,
                    executed_at,
                    classifier_version,
                    classifier_model_id,
                    reason_code,
                    evidence,
                )
                if inserted_id is None:
                    logger.info(
                        "[SENTIMENT-A] Skip duplicate V2 sentiment result_id=%s",
                        row_id,
                    )
                    continue

                # Keep a result and all of its raw themes atomic. If a theme
                # write fails, the savepoint rolls the whole result back.
                for theme in sentiment_data.get("themes", []):
                    if not isinstance(theme, dict):
                        continue
                    theme_name = (theme.get("theme") or "").strip()
                    theme_sentiment = theme.get("sentiment", sentiment)
                    excerpt = theme.get("excerpt") or ""
                    if (
                        not theme_name
                        or theme_sentiment not in THEME_SENTIMENT_VALUES
                    ):
                        continue
                    await conn.execute(
                        """
                        INSERT INTO geo_sentiment_themes
                        (client_prompt_id, task_id, result_id, client_id,
                         theme_name, sentiment, excerpt, executed_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        str(client_prompt_id),
                        str(task_id) if task_id else None,
                        row_id,
                        str(client_id),
                        theme_name,
                        theme_sentiment,
                        excerpt,
                        executed_at,
                    )
            written += 1
        except Exception as e:
            logger.warning(
                "[SENTIMENT-A] Failed to persist result_id=%s atomically: %s",
                row_id,
                e,
            )

    return written


# ─────────────────────────────────────────────────────────────────────────────
# PHASE B — Per-run normalization
# ─────────────────────────────────────────────────────────────────────────────

async def normalize_themes(
    conn,
    client_id: str,
    industry: Optional[str] = None,
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> None:
    """
    Phase B: After all batches are processed for a client:
    1. Load raw theme names from geo_sentiment_themes that aren't in the dictionary yet.
    2. Load existing dictionary (filtered by industry if available).
    3. Ask Gemini to map raw themes to existing dictionary entries OR identify new ones.
    4. Persist genuinely new themes to geo_sentiment_theme_dictionary.
    5. UPDATE geo_sentiment_themes to use the normalized (canonical) theme names.
    6. If client industry is unknown, ask Gemini to infer it and store it.
    """
    # Step 1: Find raw themes not yet in the dictionary
    raw_themes_rows = await conn.fetch(
        """
        SELECT DISTINCT gst.theme_name
        FROM geo_sentiment_themes gst
        WHERE gst.client_id = $1
          AND NOT EXISTS (
              SELECT 1 FROM geo_sentiment_theme_dictionary d
              WHERE d.theme_name = gst.theme_name
          )
        """,
        client_id,
    )

    raw_themes = [r["theme_name"] for r in raw_themes_rows]
    if not raw_themes:
        logger.info("[SENTIMENT-B] No new raw themes to normalize.")
        return

    # Step 2: Load existing dictionary (scoped to industry if known)
    if industry:
        dict_rows = await conn.fetch(
            """
            SELECT theme_name FROM geo_sentiment_theme_dictionary
            WHERE industry = $1 OR industry IS NULL
            ORDER BY usage_count DESC LIMIT 200
            """,
            industry,
        )
    else:
        dict_rows = await conn.fetch(
            """
            SELECT theme_name FROM geo_sentiment_theme_dictionary
            ORDER BY usage_count DESC LIMIT 200
            """
        )

    existing_themes = [r["theme_name"] for r in dict_rows]

    logger.info(
        f"[SENTIMENT-B] Normalizing {len(raw_themes)} raw themes against "
        f"{len(existing_themes)} dictionary entries."
    )

    # Step 3: Ask Gemini to normalize
    normalization_map, new_themes, inferred_industry = await _gemini_normalize_themes(
        raw_themes=raw_themes,
        existing_themes=existing_themes,
        industry=industry,
        model_id=model_id,
        model_region_overrides=model_region_overrides,
    )

    # Step 4: Persist new themes to dictionary
    for theme_name in new_themes:
        try:
            await conn.execute(
                """
                INSERT INTO geo_sentiment_theme_dictionary (theme_name, industry, created_by)
                VALUES ($1, $2, 'gemini')
                ON CONFLICT (theme_name) DO NOTHING
                """,
                theme_name,
                inferred_industry or industry,
            )
            logger.info(f"[SENTIMENT-B] New theme added to dictionary: '{theme_name}'")
        except Exception as e:
            logger.warning(f"[SENTIMENT-B] Failed to insert theme '{theme_name}': {e}")

    # Update usage counts for all themes used
    for canonical in set(normalization_map.values()):
        try:
            await conn.execute(
                """
                UPDATE geo_sentiment_theme_dictionary
                SET usage_count = usage_count + 1, updated_at = NOW()
                WHERE theme_name = $1
                """,
                canonical,
            )
        except Exception:
            pass

    # Step 5: Update geo_sentiment_themes to use canonical names
    for raw, canonical in normalization_map.items():
        if raw != canonical:
            try:
                await conn.execute(
                    """
                    UPDATE geo_sentiment_themes
                    SET theme_name = $1
                    WHERE theme_name = $2 AND client_id = $3
                    """,
                    canonical,
                    raw,
                    client_id,
                )
            except Exception as e:
                logger.warning(f"[SENTIMENT-B] Failed to rename '{raw}' → '{canonical}': {e}")

    logger.info(f"[SENTIMENT-B] Normalization complete. {len(normalization_map)} themes processed.")


# ─────────────────────────────────────────────────────────────────────────────
# Gemini helpers
# ─────────────────────────────────────────────────────────────────────────────

# Module-level client cache
_gemini_client_cache: Dict = {}


def _get_gemini_client_and_model(
    model_id: Optional[str],
    model_region_overrides: Optional[str] = None,
):
    """Get or initialize a cached genai Client and resolve model ID."""
    from google import genai
    import os

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    effective_model = model_id or os.environ.get("GEMINI_MODEL_ID", "gemini-2.0-flash")
    region = resolve_model_region(
        effective_model,
        overrides_value=model_region_overrides,
        default_region=os.environ.get("GCP_REGION", "us-central1"),
        global_region=os.environ.get("GCP_REGION_GLOBAL", "global"),
    )

    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID not set")

    cache_key = f"{project_id}:{region}"
    if cache_key not in _gemini_client_cache:
        _gemini_client_cache[cache_key] = genai.Client(
            vertexai=True, project=project_id, location=region
        )
        logger.info(f"[SENTIMENT] Initialized GenAI client: {effective_model} ({region})")
    return _gemini_client_cache[cache_key], effective_model


async def _gemini_extract_sentiment(
    batch: List[Tuple],
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> Dict[int, dict]:
    """
    Phase A Gemini call: Given a batch of (result_id, text, ...) tuples,
    extract sentiment + themes for each.
    Returns {result_id: {sentiment, confidence, themes: [{theme, sentiment, excerpt}]}}
    """
    try:
        from google.genai import types
        if model_region_overrides:
            client, effective_model = _get_gemini_client_and_model(
                model_id,
                model_region_overrides=model_region_overrides,
            )
        else:
            client, effective_model = _get_gemini_client_and_model(model_id)

        # Build prompt with all texts in the batch. Phase 1 attaches
        # customer-owned target entities so Gemini can avoid attributing peer
        # pros/cons to the customer's sentiment.
        entries = []
        for row in batch:
            result_id, text = row[0], row[1]
            target_entities = row[6] if len(row) > 6 and isinstance(row[6], dict) else {"brands": [], "products": []}
            selected_context = _select_sentiment_context(text or "", target_entities)
            entries.append({
                "result_id": result_id,
                "text": selected_context,
                "target_entities": target_entities,
            })

        prompt = _build_extraction_prompt(entries)

        response = await client.aio.models.generate_content(
            model=effective_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        raw_text = getattr(response, "text", None)
        if not raw_text or not raw_text.strip():
            logger.error("[SENTIMENT-A] Gemini extraction returned empty response text")
            return {}

        raw = raw_text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
        # Expected: list of {result_id, sentiment, confidence, themes:[{theme, sentiment, excerpt}]}
        results = {}
        contexts_by_result_id = {int(entry["result_id"]): entry["text"] for entry in entries}
        targets_by_result_id = {
            int(entry["result_id"]): entry["target_entities"] for entry in entries
        }
        for item in (parsed if isinstance(parsed, list) else []):
            if not isinstance(item, dict):
                continue
            rid = item.get("result_id")
            if rid is not None:
                normalized = _normalize_extraction_item(
                    item,
                    model_id=effective_model,
                    context_text=contexts_by_result_id.get(int(rid), ""),
                    target_entities=targets_by_result_id.get(int(rid)),
                )
                if normalized is not None:
                    results[int(rid)] = normalized
        logger.info(f"[SENTIMENT-A] Extracted sentiment for {len(results)}/{len(batch)} results.")
        return results

    except Exception as e:
        logger.error(f"[SENTIMENT-A] Gemini extraction failed: {e}")
        # Do not synthesize sentiment on extraction failure. A fabricated
        # Positive row pollutes customer sentiment metrics more than missing
        # best-effort enrichment does.
        return {}


async def _gemini_normalize_themes(
    raw_themes: List[str],
    existing_themes: List[str],
    industry: Optional[str],
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> Tuple[Dict[str, str], List[str], Optional[str]]:
    """
    Phase B Gemini call: Normalize raw theme names against existing dictionary.
    Returns:
        normalization_map: {raw_theme: canonical_theme}
        new_themes: list of genuinely new canonical theme names to add to dictionary
        inferred_industry: if industry was None, Gemini's guess at the industry
    """
    try:
        from google.genai import types
        if model_region_overrides:
            client, effective_model = _get_gemini_client_and_model(
                model_id,
                model_region_overrides=model_region_overrides,
            )
        else:
            client, effective_model = _get_gemini_client_and_model(model_id)

        raw_list = "\n".join(f"- {t}" for t in raw_themes)
        dict_list = "\n".join(f"- {t}" for t in existing_themes) if existing_themes else "(empty)"
        industry_line = f"Industry context: {industry}" if industry else "Industry context: unknown (please infer from the theme names)"

        prompt = f"""You are normalizing sentiment theme names for a brand intelligence platform.

{industry_line}

Existing theme dictionary:
{dict_list}

Newly extracted raw themes to normalize:
{raw_list}

Task:
1. For each raw theme, map it to the best matching entry in the existing dictionary
   (e.g. "Require Manual Setup" → "Manual Setup Required").
2. If there is no good match (similarity < 80%), treat it as a genuinely new theme.
3. Use title case for all theme names.
4. If industry was unknown, infer it from the theme names (e.g. "Consumer Electronics").

Return a JSON object with:
{{
  "normalization_map": {{"raw theme": "canonical theme", ...}},
  "new_themes": ["Theme Name", ...],
  "inferred_industry": "Industry Name or null"
}}"""

        response = await client.aio.models.generate_content(
            model=effective_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
        norm_map = parsed.get("normalization_map", {t: t for t in raw_themes})
        new_themes = parsed.get("new_themes", [])
        inferred = parsed.get("inferred_industry")

        logger.info(f"[SENTIMENT-B] Normalization: {len(norm_map)} mapped, {len(new_themes)} new, industry='{inferred}'")
        return norm_map, new_themes, inferred

    except Exception as e:
        logger.error(f"[SENTIMENT-B] Gemini normalization failed: {e}")
        # Fallback: identity mapping, treat all as new
        return {t: t for t in raw_themes}, raw_themes, None


def _format_extraction_entry(entry: Any) -> str:
    """Format one response and its customer-owned sentiment targets."""
    if isinstance(entry, dict):
        result_id = entry.get("result_id")
        text = entry.get("text") or ""
        target_entities = entry.get("target_entities") or {}
        brands = target_entities.get("brands") or []
        products = target_entities.get("products") or []
        target_lines = []
        if brands:
            target_lines.append(f"- Brands: {', '.join(brands)}")
        if products:
            target_lines.append(f"- Products: {', '.join(products)}")
        target_text = "\n".join(target_lines) if target_lines else "- None"
        return (
            f"result_id: {result_id}\n"
            f"Target customer entities for this result:\n{target_text}\n"
            f'"""\n{text}\n"""'
        )
    return str(entry)


def _build_extraction_prompt(entries: List[Any]) -> str:
    """Build the Phase A extraction prompt."""
    entries_text = "\n\n---\n\n".join(_format_extraction_entry(e) for e in entries)
    return f"""You are an AI brand intelligence analyst. Analyze the following AI-generated responses for CUSTOMER-SCOPED brand sentiment.

Critical attribution rules:
- Only extract sentiment and themes about the target customer entities listed above each response.
- Do NOT extract competitor pros/cons, competitor weaknesses, competitor strengths, or generic category commentary as customer sentiment.
- If the response compares the customer's brand/product with competitors, attribute each positive or negative theme only to the target customer entity it describes.
- Excerpts must directly mention a target customer entity or clearly refer to it in the same comparison sentence. Ignore evidence that is only about peers or competitors.
- Negative requires direct negative evidence about a target customer entity and a clear failure, material risk, non-recommendation, or inability to meet the user's core need.
- If a response has no substantive target customer entity evidence, classify it as Insufficient Evidence and return an empty themes list.

Comparative recommendation rules:
- For comparative or choice-oriented responses, judge the overall sentiment toward the target customer entities primarily by the recommendation outcome and fit for the user's stated criteria.
- Final Recommendation Priority: if the response has a final conclusion section or decisive phrases such as "Short answer", "Final Verdict", "The Verdict", "My recommendation", "Choose X", "Go with X", "if you only pick one", or "Bottom line", that final recommendation has the highest priority.
- If a competitor has a slight edge, the answer depends on use case, or the target remains a reasonable choice for another meaningful scenario, classify the overall result as Mixed/Neutral rather than Negative.
- A competitor recommendation is Negative only when the response also contains direct negative evidence that the target fails the user's core requirement or is clearly not recommended.
- Positive attributes of the target may coexist with Negative or Mixed/Neutral overall sentiment; preserve those attributes as separately scoped themes.

Specific inquiry rules:
- For specific inquiry responses, judge the overall sentiment by fit for the user's core requirement, not by counting positive versus negative sentences.
- Classify as Positive when the response says the target customer entity is suitable, reliable, useful, strong, or recommended for the user's stated use case, even if it includes minor caveats.
- Classify as Negative when the response says the target customer entity is not suitable, not reliable enough, not recommended, risky for the user's stated use case, or usable only for low-stakes/non-core scenarios while failing the user's main requirement.
- Do not let minor limitations override an overall suitable/recommended conclusion, and do not let minor strengths override an overall not-suitable/not-recommended conclusion.
- When the response is positive overall but includes material caveats, lower confidence and extract negative themes for material caveats such as manual oversight required, weak final-output readiness, reliability risks, or repeated regeneration needs.
- Use Mixed/Neutral for balanced trade-offs, conditional fit, descriptive mentions without a clear recommendation, or meaningful positive and negative evidence with no decisive outcome.

For each response, extract:
1. Overall sentiment toward the target customer entities only: "Positive" | "Mixed/Neutral" | "Negative" | "Insufficient Evidence"
2. Confidence: float 0.0–1.0
3. A reason_code: POSITIVE_RECOMMENDATION, NEGATIVE_CORE_FIT, MIXED_TRADEOFF, NEUTRAL_INFORMATIONAL, or NO_SUBSTANTIVE_EVIDENCE.
4. One to three short verbatim evidence excerpts. Every non-Insufficient classification must have evidence directly grounded in the supplied text.
5. Key customer-scoped themes (0–5 per response): specific aspects mentioned about target entities (e.g. "Learning Curve", "Strong Cleaning Performance").
   - Use concise title case labels (3–5 words max)
   - For each theme, include theme sentiment: "Positive", "Mixed/Neutral", or "Negative", plus a short verbatim excerpt
   - Insufficient Evidence must return an empty themes list

Responses:
{entries_text}

Return a JSON array:
[
  {{
    "result_id": <integer>,
    "sentiment": "Positive" | "Mixed/Neutral" | "Negative" | "Insufficient Evidence",
    "confidence": 0.85,
    "reason_code": "MIXED_TRADEOFF",
    "evidence": ["short verbatim excerpt from the supplied response"],
    "themes": [
      {{
        "theme": "Learning Curve",
        "sentiment": "Mixed/Neutral",
        "excerpt": "First-time setup requires mapping zones which can take effort"
      }}
    ]
  }}
]"""
