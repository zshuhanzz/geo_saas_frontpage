"""
Prompt Expander Service (V2.5 SaaS) — Client-based FinalPromptBuilder

In V2.5, client_prompts are pre-configured with their specific platform, country,
and language. They belong to a Topic, which belongs to a Client.
This service reads ACTIVE client_prompts and assemblies final_prompts by fusing:
  - client_prompt text
  - Persona (round-robin selection)
  - Platform system instructions

Then creates geo_tasks and publishes dispatch messages to Pub/Sub.

Phase 2.5a: rewritten on top of `geo_common.db` asyncpg pool — replaces the
previous `databases` lib + SQLAlchemy ``Table`` constructs with raw SQL.
"""
import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo

from google.genai import types
from geo_common.llm import MODEL_REGION_OVERRIDES_KEY

from src.clients.gemini import get_gemini_client
from src.clients.pubsub import PubSubService
from src.core import database as db
from src.services.fusion_prompt import build_fusion_instruction, simple_concat

logger = logging.getLogger(__name__)


CountryLocalizationMode = Literal["generic", "localized_by_country"]


@dataclass(frozen=True)
class EffectivePromptExpansionSettings:
    reuse_latest_final_prompt: bool
    country_localization_mode: CountryLocalizationMode
    final_prompt_per_client_prompt: int
    default_calls_per_prompt: int


def shanghai_batch_id(now: datetime | None = None) -> str:
    """Return the Collector business-date batch id in Asia/Shanghai."""
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return current.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _coerce_bool(value, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "f", "0", "no", "n", "off"}:
        return False
    return default


def _coerce_positive_int(value, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def _coerce_client_positive_int(
    value,
    *,
    default: int,
    setting_name: str,
    client_id: str | None,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "[FPB-S5] Invalid %s=%r for client_id=%s; falling back to Global Config/default",
            setting_name,
            value,
            client_id,
        )
        return default
    if parsed < 1:
        logger.warning(
            "[FPB-S5] Invalid %s=%r for client_id=%s; falling back to Global Config/default",
            setting_name,
            value,
            client_id,
        )
        return default
    return parsed


def resolve_prompt_expansion_settings(
    *,
    client,
    global_configs: dict,
) -> EffectivePromptExpansionSettings:
    """Resolve Client prompt expansion controls with Global Config fallback."""
    global_final_prompt_count = _coerce_positive_int(
        global_configs.get("final_prompt_per_client_prompt"),
        default=1,
    )
    global_calls_per_prompt = _coerce_positive_int(
        global_configs.get("default_calls_per_prompt"),
        default=1,
    )

    mode = (client.get("country_localization_mode") if client else None) or "generic"
    if mode not in ("generic", "localized_by_country"):
        logger.warning(
            "[FPB-S5] Invalid country_localization_mode=%r for client_id=%s; falling back to generic",
            mode,
            client.get("id") if client else None,
        )
        mode = "generic"
    client_id = str(client.get("id")) if client and client.get("id") else None

    return EffectivePromptExpansionSettings(
        reuse_latest_final_prompt=_coerce_bool(
            client.get("reuse_latest_final_prompt") if client else None,
            default=False,
        ),
        country_localization_mode=mode,
        final_prompt_per_client_prompt=_coerce_client_positive_int(
            client.get("final_prompt_per_client_prompt") if client else None,
            default=global_final_prompt_count,
            setting_name="final_prompt_per_client_prompt",
            client_id=client_id,
        ),
        default_calls_per_prompt=_coerce_client_positive_int(
            client.get("default_calls_per_prompt") if client else None,
            default=global_calls_per_prompt,
            setting_name="default_calls_per_prompt",
            client_id=client_id,
        ),
    )


def _prompt_reuse_identity(prompt_row) -> str:
    """Return the stable prompt identity used for Final Prompt reuse.

    Current prompt storage expands one logical prompt into multiple rows across
    platform/country. The text is therefore the most useful existing identity
    for cross-platform/cross-country reuse. Tests that pass only an id still
    get deterministic behavior.
    """
    text = prompt_row.get("text") if hasattr(prompt_row, "get") else prompt_row["text"]
    if text:
        return " ".join(str(text).split())
    prompt_id = prompt_row.get("id") if hasattr(prompt_row, "get") else prompt_row["id"]
    return str(prompt_id)


def build_final_prompt_reuse_key(
    prompt_row,
    country_localization_mode: CountryLocalizationMode,
) -> tuple[str, ...]:
    client_id = str(prompt_row["client_id"])
    prompt_identity = _prompt_reuse_identity(prompt_row)
    language = str(prompt_row["language"] or "")
    if country_localization_mode == "localized_by_country":
        return (client_id, prompt_identity, language, str(prompt_row["country"] or ""))
    return (client_id, prompt_identity, language)


# Columns written into geo_tasks per generated final_prompt. Kept aligned with
# the SQL string in `_insert_tasks`. Add columns here AND in the INSERT body.
_TASK_INSERT_COLUMNS = (
    "task_id",
    "client_prompt_id",
    "client_id",
    "topic_id",
    "final_prompt",
    "calls_per_prompt",
    "batch_id",
    "status",
    "client_name",
    "topic",
    "product",
    "platform",
    "country",
    "language",
    "intent",
    "client_prompt_text",
    "persona_used",
    "peers",
    "owned_domains",
)

_TASK_INSERT_SQL = (
    f"INSERT INTO {db.GEO_TASKS} ("
    + ", ".join(_TASK_INSERT_COLUMNS)
    + ") VALUES ("
    + ", ".join(f"${i + 1}" for i in range(len(_TASK_INSERT_COLUMNS)))
    + ")"
)


class FinalPromptBuilder:
    """
    Client-based Final Prompt Builder (V2.5 SaaS).

    For a given Client (and optionally a Topic):
    1. Load client config (peers, domains, personas)
    2. Load ACTIVE client_prompts (with their pre-bound platform/country)
    3. For each active prompt (with batch_id idempotency check):
       a. Pick one persona (round-robin)
       b. Call Gemini to generate N diverse query variants (1:N expansion)
       c. Create N geo_tasks per client_prompt
    4. Publish dispatch messages to Pub/Sub
    """

    def __init__(self):
        self.gemini = get_gemini_client()
        self.pubsub = PubSubService()

    async def expand_client(self, client_id: str, topic_id: Optional[str] = None) -> int:
        """
        Expand active Prompts for a Client into geo_tasks.

        Returns:
            int: Number of tasks created
        """
        pool = db.get_pool()

        # ------------------------------------------------------------------ S1
        logger.info(f"[FPB-S1] 加载 Client 信息 | client_id={client_id}")
        async with pool.acquire() as conn:
            client = await conn.fetchrow(
                f"SELECT * FROM {db.GEO_CLIENTS} WHERE id = $1",
                client_id,
            )
            if not client:
                raise ValueError(f"Client {client_id} not found")
            client_dict = dict(client)

            peers_rows = await conn.fetch(
                f"SELECT primary_name FROM {db.GEO_CLIENT_PEERS} WHERE client_id = $1",
                client_id,
            )
            peers = [p["primary_name"] for p in peers_rows]

            # Load client domains for denormalization
            domains_rows = await conn.fetch(
                f"SELECT domain FROM {db.GEO_CLIENT_DOMAINS} WHERE client_id = $1",
                client_id,
            )
            owned_domains = [d["domain"] for d in domains_rows]

            # Load topic names for denormalization
            topic_rows = await conn.fetch(
                f"SELECT id, topic_name FROM {db.GEO_CLIENT_TOPICS} WHERE client_id = $1",
                client_id,
            )
            topic_name_map = {str(t["id"]): t["topic_name"] for t in topic_rows}

            # ------------------------------------------------------------- S2
            logger.info(f"[FPB-S2] 加载 Client Prompts | client_id={client_id}")
            if topic_id:
                prompts = await conn.fetch(
                    f"""
                    SELECT *
                      FROM {db.GEO_CLIENT_PROMPTS}
                     WHERE client_id = $1
                       AND is_active = TRUE
                       AND topic_id = $2
                     ORDER BY created_at
                    """,
                    client_id,
                    topic_id,
                )
            else:
                prompts = await conn.fetch(
                    f"""
                    SELECT *
                      FROM {db.GEO_CLIENT_PROMPTS}
                     WHERE client_id = $1
                       AND is_active = TRUE
                     ORDER BY created_at
                    """,
                    client_id,
                )

            if not prompts:
                logger.warning(
                    f"[FPB-S2] 没有活跃的 Client Prompts | client_id={client_id}"
                )
                return 0
            logger.info(f"[FPB-S2] 加载了 {len(prompts)} 条 Client Prompts")

            # ------------------------------------------------------------- S3
            personas = await conn.fetch(
                f"""
                SELECT persona_name, persona_description
                  FROM {db.GEO_CLIENT_PERSONAS}
                 WHERE client_id = $1
                """,
                client_id,
            )
            logger.info(f"[FPB-S3] 加载 {len(personas)} 个 Personas")

            # ------------------------------------------------------------- S4
            platforms_needed = {p["platform"] for p in prompts}
            platform_configs: dict[str, dict] = {}
            for pid in platforms_needed:
                pc = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {db.GEO_GLOBAL_PLATFORMS}
                     WHERE platform_id = $1
                    """,
                    pid,
                )
                if pc:
                    platform_configs[pid] = dict(pc)
            logger.info(f"[FPB-S4] 加载 {len(platform_configs)} 个 Platform 配置")

            # ------------------------------------------------------------- S5
            settings_rows = await conn.fetch(
                f"""
                SELECT key, value
                  FROM {db.GEO_GLOBAL_SETTINGS}
                 WHERE key = ANY($1::text[])
                """,
                [
                    "expander_model_id",
                    "default_calls_per_prompt",
                    "final_prompt_per_client_prompt",
                    MODEL_REGION_OVERRIDES_KEY,
                ],
            )
        global_configs = {row["key"]: row["value"] for row in settings_rows}

        expander_model_id = global_configs.get("expander_model_id")
        self.gemini.set_model_region_overrides(global_configs.get(MODEL_REGION_OVERRIDES_KEY))
        logger.info(f"[FPB-S5] Expander model: {expander_model_id or 'default'}")

        effective_settings = resolve_prompt_expansion_settings(
            client=client_dict,
            global_configs=global_configs,
        )
        default_m = effective_settings.default_calls_per_prompt
        n_variants = effective_settings.final_prompt_per_client_prompt
        logger.info(
            "[FPB-S5] Effective settings | client_id=%s | "
            "reuse_latest_final_prompt=%s | country_localization_mode=%s | "
            "default_calls_per_prompt=%s | final_prompt_per_client_prompt=%s",
            client_id,
            effective_settings.reuse_latest_final_prompt,
            effective_settings.country_localization_mode,
            default_m,
            n_variants,
        )

        # ------------------------------------------------------------------ S6
        batch_id = shanghai_batch_id()

        work_items: list[dict] = []
        prompt_ids_to_clean: list = []
        for index, prompt in enumerate(prompts):
            platform_id = prompt["platform"]
            pc = platform_configs.get(platform_id)
            if not pc:
                logger.warning(
                    f"[FPB-S6] Platform {platform_id} 配置缺失，跳过 Prompt {prompt['id']}"
                )
                continue

            prompt_ids_to_clean.append(prompt["id"])

            persona_text: Optional[str] = None
            if personas:
                persona = personas[index % len(personas)]
                persona_text = persona["persona_name"]
                if persona["persona_description"]:
                    persona_text += f" ({persona['persona_description']})"

            work_items.append({
                "prompt": prompt,
                "pc": pc,
                "persona_text": persona_text,
            })
        logger.info(
            f"[FPB-S6] 准备处理 {len(work_items)} 个工作项 | "
            f"N={n_variants} variants/prompt | 并发 LLM (semaphore=15)"
        )

        semaphore = asyncio.Semaphore(15)
        reuse_cache: dict[tuple[str, ...], list[str]] = {}
        reuse_locks: dict[tuple[str, ...], asyncio.Lock] = {}
        completed_count = 0

        async def expand_one(item: dict) -> list:
            """Generate N variant tasks for a single client_prompt."""
            nonlocal completed_count
            async with semaphore:
                prompt_row = item["prompt"]
                reuse_key = build_final_prompt_reuse_key(
                    prompt_row,
                    effective_settings.country_localization_mode,
                )
                lock = reuse_locks.setdefault(reuse_key, asyncio.Lock())
                async with lock:
                    final_prompts = list(reuse_cache.get(reuse_key) or [])
                    generated_count = 0
                    reusable_count = len(final_prompts)

                    if effective_settings.reuse_latest_final_prompt and not final_prompts:
                        final_prompts = await self._load_reusable_final_prompts(
                            pool=pool,
                            prompt_row=prompt_row,
                            mode=effective_settings.country_localization_mode,
                            limit=n_variants,
                        )
                        reusable_count = len(final_prompts)

                    missing_count = max(0, n_variants - len(final_prompts))
                    if missing_count:
                        generated = await self._build_final_prompts(
                            client_prompt_text=prompt_row["text"],
                            persona=item["persona_text"],
                            platform_instructions=item["pc"]["system_instructions"],
                            intent=prompt_row["intent"] or "",
                            expander_model_id=expander_model_id,
                            n=missing_count,
                        )
                        generated_count = len(generated)
                        final_prompts.extend(generated)

                    final_prompts = final_prompts[:n_variants]
                    reuse_cache[reuse_key] = final_prompts
                    logger.info(
                        "[FPB-S6] Final Prompt resolved | client_id=%s | "
                        "batch_id=%s | reuse_key=%s | reuse_hit_count=%d | "
                        "generated_final_prompt_count=%d",
                        client_id,
                        batch_id,
                        reuse_key,
                        reusable_count,
                        generated_count,
                    )
                completed_count += 1
                if completed_count % 50 == 0 or completed_count == len(work_items):
                    logger.info(
                        f"[FPB-S6] LLM fusion 进度: {completed_count}/{len(work_items)}"
                    )

                topic_id_str = str(prompt_row["topic_id"])
                tasks: list[dict] = []
                for fp in final_prompts:
                    tasks.append({
                        "task_id": str(uuid.uuid4()),
                        "client_prompt_id": str(prompt_row["id"]),
                        "client_id": str(client_id),
                        "topic_id": topic_id_str,
                        "final_prompt": fp,
                        "calls_per_prompt": default_m,
                        "batch_id": batch_id,
                        "status": "PENDING",
                        # Denormalized fields for downstream use
                        "client_name": client_dict["name"],
                        "topic": topic_name_map.get(topic_id_str, ""),
                        "product": prompt_row["product"] or "",
                        "platform": prompt_row["platform"],
                        "country": prompt_row["country"] or "",
                        "language": prompt_row["language"] or "",
                        "intent": prompt_row["intent"] or "",
                        "client_prompt_text": prompt_row["text"],
                        "persona_used": item["persona_text"] or "",
                        "peers": peers,
                        "owned_domains": owned_domains,
                    })
                return tasks

        nested_results = await asyncio.gather(
            *[expand_one(item) for item in work_items]
        )
        tasks_to_insert = [task for sublist in nested_results for task in sublist]
        task_ids = [t["task_id"] for t in tasks_to_insert]

        logger.info(
            f"[FPB-S6] 准备创建 {len(tasks_to_insert)} 条 geo_tasks | batch_id={batch_id}"
        )

        # ------------------------------------------------------------------ S7
        if tasks_to_insert:
            await self._atomic_replace_pending_tasks(
                pool, prompt_ids_to_clean, tasks_to_insert
            )
            logger.info(f"[FPB-S7] geo_tasks 创建完成 | count={len(tasks_to_insert)}")

        # ------------------------------------------------------------------ S8
        if task_ids:
            logger.info(f"[FPB-S8] 发布 dispatch 消息到 Pub/Sub | count={len(task_ids)}")
            try:
                published = self.pubsub.publish_dispatch_batch(task_ids)
                logger.info(f"[FPB-S8] Pub/Sub 发布成功 | published={published}")
            except Exception as e:
                logger.error(f"[FPB-S8] Pub/Sub 发布失败 | error={e}")

        return len(tasks_to_insert)

    @staticmethod
    async def _load_reusable_final_prompts(
        *,
        pool,
        prompt_row,
        mode: CountryLocalizationMode,
        limit: int,
    ) -> list[str]:
        """Load newest distinct Final Prompts for the prompt reuse key."""
        if limit <= 0:
            return []

        prompt_identity = _prompt_reuse_identity(prompt_row)
        params: list = [
            str(prompt_row["client_id"]),
            prompt_identity,
            str(prompt_row["language"] or ""),
            limit,
        ]
        country_filter = ""
        if mode == "localized_by_country":
            params.insert(3, str(prompt_row["country"] or ""))
            country_filter = "AND COALESCE(country, '') = $4"
            limit_param = "$5"
        else:
            limit_param = "$4"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT final_prompt, MAX(created_at) AS latest_created_at
                  FROM {db.GEO_TASKS}
                 WHERE client_id = $1::uuid
                   AND client_prompt_text = $2
                   AND COALESCE(language, '') = $3
                   {country_filter}
                   AND final_prompt IS NOT NULL
                   AND TRIM(final_prompt) <> ''
                 GROUP BY final_prompt
                 ORDER BY latest_created_at DESC NULLS LAST
                 LIMIT {limit_param}
                """,
                *params,
            )
        return [row["final_prompt"] for row in rows if row["final_prompt"]]

    @staticmethod
    async def _atomic_replace_pending_tasks(
        pool,
        prompt_ids_to_clean: list,
        tasks_to_insert: list[dict],
    ) -> None:
        """
        Atomically: delete any PENDING geo_tasks for the given client_prompt_ids,
        then bulk-insert the freshly built tasks. Both operations share one
        transaction so a downstream Pub/Sub publish never observes a half-cleaned
        task table.
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                if prompt_ids_to_clean:
                    delete_status = await conn.execute(
                        f"""
                        DELETE FROM {db.GEO_TASKS}
                         WHERE client_prompt_id = ANY($1::uuid[])
                           AND status = 'PENDING'
                        """,
                        prompt_ids_to_clean,
                    )
                    affected = _parse_affected(delete_status)
                    if affected:
                        logger.info(f"[FPB-S7] 清理 PENDING 旧任务 | affected={affected}")

                rows_to_copy = [
                    tuple(task[col] for col in _TASK_INSERT_COLUMNS)
                    for task in tasks_to_insert
                ]
                # `executemany` is cheaper than per-row `execute` and matches the
                # previous `databases.execute_many` semantics.
                await conn.executemany(_TASK_INSERT_SQL, rows_to_copy)

    async def _build_final_prompts(
        self,
        client_prompt_text: str,
        persona: Optional[str] = None,
        platform_instructions: Optional[str] = None,
        intent: Optional[str] = None,
        expander_model_id: Optional[str] = None,
        n: int = 1,
        max_retries: int = 3,
    ) -> List[str]:
        """
        Use LLM (Gemini) to generate N diverse query variants from a client_prompt.

        One Gemini call returns a JSON array of N variants.
        Falls back to N copies of simple string concatenation when Gemini is unavailable.
        """
        if expander_model_id and self.gemini and n > 0:
            fusion_prompt = build_fusion_instruction(
                client_prompt_text, persona, platform_instructions, intent=intent, n=n
            )
            gen_config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.9,
                max_output_tokens=4096,
            )
            for attempt in range(max_retries):
                try:
                    response = await self.gemini.generate_content_async(
                        contents=fusion_prompt,
                        model=expander_model_id,
                        config=gen_config,
                    )
                    raw = response.text.strip()
                    if raw:
                        result = json.loads(raw)
                        variants = (
                            result if isinstance(result, list)
                            else result.get("variants", [])
                        )
                        variants = [
                            v.strip() for v in variants if isinstance(v, str) and v.strip()
                        ]
                        if len(variants) >= n:
                            return variants[:n]
                        if variants:
                            logger.warning(
                                f"[FPB] Gemini 返回 {len(variants)}/{n} 条变体，用原文补齐"
                            )
                            while len(variants) < n:
                                variants.append(simple_concat(
                                    client_prompt_text, persona, platform_instructions
                                ))
                            return variants
                except Exception as e:
                    err_str = str(e).lower()
                    is_retryable = (
                        "429" in err_str
                        or "500" in err_str
                        or "503" in err_str
                        or "resource" in err_str
                    )
                    if is_retryable and attempt < max_retries - 1:
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"[FPB] LLM fusion 重试 {attempt + 1}/{max_retries} | "
                            f"等待 {wait:.1f}s | error={e}"
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.warning(
                            f"[FPB] LLM fusion 失败，回退到字符串拼接 | error={e}"
                        )
                        break

        # Fallback: return single copy to avoid N*M identical Cloro API calls
        fallback = simple_concat(client_prompt_text, persona, platform_instructions)
        logger.warning(
            f"[FPB] LLM fallback: returning 1 task instead of {n} to avoid duplicate API calls"
        )
        return [fallback]


def _parse_affected(status_string: str) -> int:
    """Parse asyncpg's command-status string (e.g. ``"DELETE 3"``) into a row count."""
    if not status_string:
        return 0
    parts = status_string.strip().split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0


# Global singleton
_builder_service: Optional[FinalPromptBuilder] = None


def get_builder_service() -> FinalPromptBuilder:
    """Get FinalPromptBuilder service singleton"""
    global _builder_service
    if _builder_service is None:
        _builder_service = FinalPromptBuilder()
    return _builder_service
