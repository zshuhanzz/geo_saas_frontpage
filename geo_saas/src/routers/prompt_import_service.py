"""Tenant-safe Prompt CSV import parsing, Preview, Commit, and Undo services."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import re
from dataclasses import asdict, dataclass, field
from contextlib import asynccontextmanager
from typing import Any, Iterable
from uuid import UUID, uuid4

from geo_common.db import tenant_scoped
from geo_common.services import (
    BaseRepository,
    PromptCascadeDeletionService,
    PromptRepository,
    PromptWriteCoordinator,
    canonical_prompt_text,
)
from geo_common.services.prompt_intent import canonicalize_configured_values


CSV_HEADERS = (
    "Customer Name",
    "Topic",
    "Product",
    "Prompt",
    "AI Platforms",
    "Countries",
    "Language",
    "Intent",
)
ALLOWED_VALUES_HEADERS = ("Type", "Value", "Label", "Parent Type", "Parent Value", "Notes")
PROMPT_PLACEHOLDER = "[REPLACE WITH YOUR PROMPT]"
_MULTI_DELIMITER = re.compile(r"[,;|]")
_FULL_WIDTH_DELIMITERS = ("，", "；")


class ImportValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_csv",
        actual: int | None = None,
        allowed: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.actual = actual
        self.allowed = allowed
        self.details = details or {}


class PreviewStaleError(RuntimeError):
    def __init__(self, preview: "ImportPreview") -> None:
        super().__init__("Preview is stale; review the refreshed Preview before committing")
        self.preview = preview


def _bounded_env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.environ.get(name, str(default)))
    except ValueError:
        configured = default
    return max(minimum, min(configured, maximum))


class PromptImportUndoLimiter:
    """Bound Undo requests before they can reserve a database connection."""

    def __init__(self, *, limit: int) -> None:
        self.limit = max(1, min(int(limit), 4))
        self._slots = asyncio.BoundedSemaphore(self.limit)

    @asynccontextmanager
    async def slot(self):
        await self._slots.acquire()
        try:
            yield
        finally:
            self._slots.release()


_UNDO_LIMITER = PromptImportUndoLimiter(
    limit=_bounded_env_int(
        "PROMPT_IMPORT_UNDO_CONCURRENCY",
        default=1,
        minimum=1,
        maximum=4,
    )
)
_UNDO_LARGE_FOOTPRINT_WARNING = _bounded_env_int(
    "PROMPT_IMPORT_UNDO_MAX_FOOTPRINT",
    default=10_000,
    minimum=100,
    maximum=100_000,
)
_UNDO_LOCK_TIMEOUT_MS = _bounded_env_int(
    "PROMPT_IMPORT_UNDO_LOCK_TIMEOUT_MS",
    default=5_000,
    minimum=100,
    maximum=30_000,
)
_UNDO_STATEMENT_TIMEOUT_MS = _bounded_env_int(
    "PROMPT_IMPORT_UNDO_STATEMENT_TIMEOUT_MS",
    default=30_000,
    minimum=1_000,
    maximum=120_000,
)


@dataclass(frozen=True)
class ImportLimits:
    max_bytes: int = 10 * 1024 * 1024
    max_rows: int = 2_000
    max_variants_per_row: int = 100
    max_variants: int = 20_000


@dataclass(frozen=True)
class ResolverValues:
    customer_name: str
    topics: dict[str, tuple[str, str]]
    products: dict[str, dict[str, str]]
    platforms: dict[str, str]
    countries: dict[str, str]
    languages: dict[str, str]
    intents: dict[str, str]
    platform_countries: dict[str, frozenset[str]]
    ambiguous_topics: frozenset[str] = field(default_factory=frozenset)
    quota: int = 0
    display_labels: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedImportRow:
    row_number: int
    customer_name: str
    topic_id: str
    topic: str
    product: str | None
    prompt: str
    platforms: tuple[str, ...]
    countries: tuple[str, ...]
    language: str
    intent: str


@dataclass(frozen=True)
class PromptVariant:
    topic_id: str
    topic: str
    product: str | None
    prompt: str
    platform: str
    country: str
    language: str
    intent: str
    source_rows: tuple[int, ...] = field(compare=False)

    @property
    def exact_key(self) -> tuple[str, ...]:
        return (
            self.topic_id,
            canonical_prompt_text(self.prompt),
            normalize_scalar(self.product or "").lower(),
            self.platform.lower(),
            self.country.lower(),
            self.language.lower(),
        )

    @property
    def logical_key(self) -> tuple[str, ...]:
        return (self.topic_id, canonical_prompt_text(self.prompt))

    @property
    def declaration_key(self) -> tuple[str, ...]:
        """Physical scalar storage coordinates, excluding mutable metadata."""
        return (
            self.topic_id,
            canonical_prompt_text(self.prompt),
            self.platform.lower(),
            self.country.lower(),
            self.language.lower(),
        )

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "product": self.product or "",
            "prompt": self.prompt,
            "platform": self.platform,
            "country": self.country,
            "language": self.language,
            "intent": self.intent,
        }


@dataclass(frozen=True)
class ParsedImport:
    raw_csv_sha256: str
    normalized_manifest_sha256: str
    rows: tuple[NormalizedImportRow, ...]
    variants: tuple[PromptVariant, ...]
    invalid_rows: tuple[dict[str, Any], ...]
    row_variants: dict[int, tuple[PromptVariant, ...]]
    declared_expanded_variant_count: int


@dataclass(frozen=True)
class ImportPreview:
    raw_csv_sha256: str
    normalized_manifest_sha256: str
    preview_state_sha256: str
    input_row_count: int
    expanded_variant_count: int
    unique_physical_variant_count: int
    action_counts: dict[str, int]
    quota_before: int
    quota_after: int
    quota_limit: int
    rows: tuple[dict[str, Any], ...]
    physical_variants: tuple[dict[str, Any], ...]

    @property
    def can_commit(self) -> bool:
        return self.action_counts["invalid"] == 0 and self.action_counts["conflict"] == 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_scalar(value: str) -> str:
    return str(value).strip()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _canonical(value: str, choices: dict[str, Any], label: str) -> Any:
    normalized = normalize_scalar(value)
    if not normalized:
        raise ImportValidationError(
            f"{label} is required",
            code=f"{label.lower().replace(' ', '_')}_required",
            details={"field": label},
        )
    resolved = choices.get(normalized.lower())
    if resolved is None:
        raise ImportValidationError(
            f"{label} '{normalized}' is not allowed",
            code=f"{label.lower().replace(' ', '_')}_not_allowed",
            details={"field": label, "value": normalized},
        )
    return resolved


def _multi_values(value: str, choices: dict[str, str], label: str) -> tuple[str, ...]:
    if any(delimiter in value for delimiter in _FULL_WIDTH_DELIMITERS):
        raise ImportValidationError(
            f"{label} supports ASCII comma, semicolon, or pipe only",
            code="full_width_delimiter",
            details={"field": label},
        )
    resolved: list[str] = []
    seen: set[str] = set()
    for token in _MULTI_DELIMITER.split(value):
        normalized = normalize_scalar(token)
        if not normalized:
            continue
        canonical = _canonical(normalized, choices, label)
        key = canonical.lower()
        if key not in seen:
            seen.add(key)
            resolved.append(canonical)
    if not resolved:
        raise ImportValidationError(
            f"{label} is required",
            code=f"{label.lower().replace(' ', '_')}_required",
            details={"field": label},
        )
    return tuple(resolved)


class PromptImportParser:
    def __init__(self, resolver: ResolverValues, *, limits: ImportLimits | None = None) -> None:
        self.resolver = resolver
        self.limits = limits or ImportLimits()

    def parse(self, raw: bytes, *, collect_invalid: bool = False) -> ParsedImport:
        if len(raw) > self.limits.max_bytes:
            raise ImportValidationError(
                f"CSV has {len(raw)} bytes; allowed maximum is {self.limits.max_bytes} bytes",
                code="file_too_large", actual=len(raw), allowed=self.limits.max_bytes,
            )
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ImportValidationError("CSV must use UTF-8 encoding", code="encoding_invalid") from exc
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""))
            if tuple(reader.fieldnames or ()) != CSV_HEADERS:
                raise ImportValidationError(
                    f"CSV headers must exactly match: {', '.join(CSV_HEADERS)}",
                    code="headers_invalid",
                )
            source_rows: list[tuple[int, dict[str | None, Any]]] = []
            for row in reader:
                if any(normalize_scalar(value or "") for value in row.values()):
                    source_rows.append((reader.line_num, row))
        except csv.Error as exc:
            raise ImportValidationError(f"Malformed CSV: {exc}", code="csv_malformed") from exc
        if len(source_rows) > self.limits.max_rows:
            raise ImportValidationError(
                f"CSV has {len(source_rows)} non-empty rows; allowed maximum is {self.limits.max_rows} rows",
                code="row_limit_exceeded", actual=len(source_rows), allowed=self.limits.max_rows,
            )
        if not source_rows:
            raise ImportValidationError(
                "CSV must contain at least one non-empty data row",
                code="empty_csv",
                actual=0,
            )

        normalized_rows: list[NormalizedImportRow] = []
        invalid_rows: list[dict[str, Any]] = []
        variants_by_key: dict[tuple[str, ...], PromptVariant] = {}
        first_declaration_row: dict[tuple[str, ...], int] = {}
        row_variants: dict[int, tuple[PromptVariant, ...]] = {}
        expanded_count = 0
        for row_number, raw_row in source_rows:
            try:
                row = self._normalize_row(row_number, raw_row)
            except ImportValidationError as exc:
                if not collect_invalid:
                    raise
                invalid_rows.append({
                    **self._raw_row_payload(row_number, raw_row),
                    "action": "invalid",
                    "errors": [{"code": exc.code, "message": str(exc), "details": exc.details}],
                    "warnings": [],
                    "variants": [],
                })
                continue
            row_variant_count = len(row.platforms) * len(row.countries)
            if row_variant_count > self.limits.max_variants_per_row:
                raise ImportValidationError(
                    f"CSV row {row_number} expands to {row_variant_count} physical variants; one row allows at most {self.limits.max_variants_per_row}",
                    code="row_variant_limit_exceeded", actual=row_variant_count, allowed=self.limits.max_variants_per_row,
                )
            expanded_count += row_variant_count
            if expanded_count > self.limits.max_variants:
                raise ImportValidationError(
                    f"CSV expands to {expanded_count} physical variants; allowed maximum is {self.limits.max_variants} variants",
                    code="variant_limit_exceeded", actual=expanded_count, allowed=self.limits.max_variants,
                )
            normalized_rows.append(row)
            candidates: list[PromptVariant] = []
            for platform in row.platforms:
                for country in row.countries:
                    candidates.append(PromptVariant(
                        topic_id=row.topic_id, topic=row.topic, product=row.product,
                        prompt=row.prompt, platform=platform, country=country,
                        language=row.language, intent=row.intent, source_rows=(row_number,),
                    ))
            row_variants[row_number] = tuple(candidates)
            duplicate_keys = [
                candidate.declaration_key
                for candidate in candidates
                if candidate.declaration_key in first_declaration_row
            ]
            if duplicate_keys:
                first_rows = sorted({
                    first_declaration_row[key] for key in duplicate_keys
                })
                first_row = first_rows[0]
                row_label = "row" if len(first_rows) == 1 else "rows"
                row_references = ", ".join(str(value) for value in first_rows)
                invalid_rows.append({
                    "row_number": row_number,
                    "action": "invalid",
                    "errors": [{
                        "code": "file_duplicate",
                        "message": (
                            "CSV row overlaps physical Prompt variants first declared "
                            f"on {row_label} {row_references}"
                        ),
                        "first_row_number": first_row,
                        "first_row_numbers": first_rows,
                        "details": {"first_row_numbers": first_rows},
                    }],
                    "warnings": [],
                })
                for candidate in candidates:
                    key = candidate.declaration_key
                    if key not in first_declaration_row:
                        variants_by_key[key] = candidate
                        first_declaration_row[key] = row_number
                continue
            for candidate in candidates:
                key = candidate.declaration_key
                variants_by_key[key] = candidate
                first_declaration_row[key] = row_number

        variants = tuple(
            sorted(
                variants_by_key.values(),
                key=lambda value: value.exact_key + (value.intent.lower(),),
            )
        )
        manifest_json = json.dumps(
            [variant.manifest_dict() for variant in variants],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return ParsedImport(
            raw_csv_sha256=hashlib.sha256(raw).hexdigest(),
            normalized_manifest_sha256=hashlib.sha256(manifest_json).hexdigest(),
            rows=tuple(normalized_rows), variants=variants,
            invalid_rows=tuple(invalid_rows), row_variants=row_variants,
            declared_expanded_variant_count=expanded_count,
        )

    @staticmethod
    def _raw_row_payload(row_number: int, raw: dict[str | None, Any]) -> dict[str, Any]:
        def value(column: str) -> str:
            return normalize_scalar(raw.get(column) or "")

        def multi(column: str) -> list[str]:
            cell = value(column)
            if any(delimiter in cell for delimiter in _FULL_WIDTH_DELIMITERS):
                return [cell] if cell else []
            return [normalize_scalar(token) for token in _MULTI_DELIMITER.split(cell) if normalize_scalar(token)]

        return {
            "row_number": row_number,
            "customer_name": value("Customer Name"),
            "topic_id": None,
            "topic": value("Topic"),
            "product": value("Product") or None,
            "prompt": normalize_text(value("Prompt")),
            "platforms": multi("AI Platforms"),
            "countries": multi("Countries"),
            "language": value("Language"),
            "intent": value("Intent"),
            "expanded_count": 0,
        }

    def _normalize_row(self, row_number: int, raw: dict[str, str | None]) -> NormalizedImportRow:
        if None in raw:
            raise ImportValidationError(
                f"CSV row {row_number} has extra columns; comma-delimited cell values must be quoted",
                code="csv_row_extra_columns",
                details={"row_number": row_number},
            )
        customer_name = raw.get("Customer Name") or ""
        if customer_name != self.resolver.customer_name:
            raise ImportValidationError(
                f"Customer Name on row {row_number} must exactly match '{self.resolver.customer_name}'",
                code="customer_mismatch",
                details={"row_number": row_number, "expected": self.resolver.customer_name, "value": customer_name},
            )
        topic_value = raw.get("Topic") or ""
        if normalize_scalar(topic_value).lower() in self.resolver.ambiguous_topics:
            raise ImportValidationError(
                f"Topic '{normalize_scalar(topic_value)}' matches multiple active Topics; rename the duplicates before import",
                code="topic_ambiguous",
                details={"value": normalize_scalar(topic_value)},
            )
        topic_id, topic = _canonical(topic_value, self.resolver.topics, "Topic")
        product_value = normalize_scalar(raw.get("Product") or "")
        product = None
        if product_value:
            product = _canonical(product_value, self.resolver.products.get(topic_id, {}), "Product")
        prompt = normalize_text(raw.get("Prompt") or "")
        if not prompt:
            raise ImportValidationError(
                f"Prompt is required on row {row_number}",
                code="prompt_required",
                details={"row_number": row_number},
            )
        if prompt.lower() == PROMPT_PLACEHOLDER.lower():
            raise ImportValidationError(
                "replace the template Prompt placeholder before Preview",
                code="prompt_placeholder",
                details={"row_number": row_number},
            )
        intent = _canonical(raw.get("Intent") or "", self.resolver.intents, "Intent")
        platforms = _multi_values(
            raw.get("AI Platforms") or "", self.resolver.platforms, "AI Platforms"
        )
        countries = _multi_values(
            raw.get("Countries") or "", self.resolver.countries, "Countries"
        )
        language_raw = raw.get("Language") or ""
        if _MULTI_DELIMITER.search(language_raw) or any(
            value in language_raw for value in _FULL_WIDTH_DELIMITERS
        ):
            raise ImportValidationError(
                "Language must contain exactly one value per row",
                code="language_multiple",
                details={"value": normalize_scalar(language_raw)},
            )
        language = _canonical(language_raw, self.resolver.languages, "Language")
        return NormalizedImportRow(
            row_number=row_number, customer_name=customer_name, topic_id=topic_id, topic=topic,
            product=product, prompt=prompt,
            platforms=platforms, countries=countries,
            language=language, intent=intent,
        )


def _choice_map(values: Iterable[str]) -> dict[str, str]:
    return {value.lower(): value for value in canonicalize_configured_values(values)}


def _localized_language_label(value: str, configured_label: str | None, locale: str) -> str:
    label = normalize_scalar(configured_label or "")
    if not label:
        return value
    contains_cjk = re.search(r"[\u3400-\u9fff]", label) is not None
    if locale == "zh-CN" and contains_cjk:
        return label
    if locale == "en-US" and not contains_cjk:
        return label
    return value


def _identity_key(row: dict[str, Any] | PromptVariant) -> tuple[str, ...]:
    getter = row.get if isinstance(row, dict) else lambda name: getattr(row, name)
    return (
        str(getter("topic_id")),
        canonical_prompt_text(str(getter("text") if isinstance(row, dict) else getter("prompt"))),
        normalize_scalar(str(getter("platform") or "")).lower(),
        normalize_scalar(str(getter("country") or "")).lower(),
        normalize_scalar(str(getter("language") or "")).lower(),
    )


class PromptImportService(BaseRepository):
    """Owns tenant resolution and the Preview/Commit/Undo transaction contract."""

    def __init__(
        self,
        pool,
        *,
        limits: ImportLimits | None = None,
        undo_limiter: PromptImportUndoLimiter | None = None,
        undo_max_footprint: int | None = None,
    ) -> None:
        super().__init__(pool)
        self.limits = limits or ImportLimits()
        self.undo_limiter = undo_limiter or _UNDO_LIMITER
        self.undo_large_footprint_warning = (
            _UNDO_LARGE_FOOTPRINT_WARNING
            if undo_max_footprint is None
            else max(1, min(int(undo_max_footprint), 100_000))
        )

    async def _resolver(self, conn, client_id: str) -> ResolverValues:
        client = await conn.fetchrow(
            "SELECT id, name, client_prompt_quota, config_platforms, config_countries, config_languages "
            "FROM geo_clients WHERE id = $1::uuid",
            client_id,
        )
        if not client:
            raise ImportValidationError("Workspace not found", code="workspace_not_found")

        topics_rows = await conn.fetch(
            "SELECT id, topic_name FROM geo_client_topics "
            "WHERE client_id = $1::uuid "
            "ORDER BY LOWER(TRIM(topic_name)), id",
            client_id,
        )
        topic_groups: dict[str, list[tuple[str, str]]] = {}
        topic_ids: set[str] = set()
        for row in topics_rows:
            name = normalize_scalar(row["topic_name"])
            if name:
                topic_groups.setdefault(normalize_scalar(name).lower(), []).append(
                    (str(row["id"]), name)
                )
                topic_ids.add(str(row["id"]))
        ambiguous_topics = frozenset(
            key for key, values in topic_groups.items() if len(values) > 1
        )
        topics = {
            key: values[0]
            for key, values in topic_groups.items()
            if len(values) == 1
        }

        product_rows = await conn.fetch(
            "SELECT topic_id, product_name FROM geo_client_topic_products "
            "WHERE client_id = $1::uuid AND is_active = TRUE "
            "ORDER BY topic_id, LOWER(TRIM(product_name)), id",
            client_id,
        )
        products: dict[str, dict[str, str]] = {topic_id: {} for topic_id in topic_ids}
        for row in product_rows:
            topic_id = str(row["topic_id"])
            name = normalize_scalar(row["product_name"])
            if topic_id in products and name:
                products[topic_id].setdefault(name.lower(), name)

        global_platform_rows = await conn.fetch(
            "SELECT platform_id, display_name, supported_countries FROM geo_global_platforms "
            "WHERE is_active = TRUE ORDER BY LOWER(TRIM(platform_id))"
        )
        configured_platforms = _choice_map(str(value) for value in (client["config_platforms"] or []))
        platforms: dict[str, str] = {}
        platform_countries: dict[str, frozenset[str]] = {}
        platform_labels: dict[str, str] = {}
        workspace_countries = _choice_map(str(value) for value in (client["config_countries"] or []))
        for row in global_platform_rows:
            platform_id = normalize_scalar(row["platform_id"])
            configured = configured_platforms.get(platform_id.lower())
            if not configured:
                continue
            platforms[platform_id.lower()] = platform_id
            platform_labels[platform_id] = normalize_scalar(row["display_name"]) or platform_id
            supported = {
                workspace_countries[value.lower()]
                for value in (row["supported_countries"] or [])
                if str(value).lower() in workspace_countries
            }
            platform_countries[platform_id] = frozenset(supported)

        intent_rows = await conn.fetch(
            "SELECT intent_name FROM geo_global_intents "
            "WHERE is_active = TRUE AND NULLIF(TRIM(intent_name), '') IS NOT NULL "
            "ORDER BY LOWER(TRIM(intent_name)), TRIM(intent_name)"
        )
        language_rows = await conn.fetch(
            "SELECT language_code, language FROM geo_global_languages "
            "WHERE is_active = TRUE ORDER BY LOWER(TRIM(language_code))"
        )
        global_languages = _choice_map(str(row["language_code"]) for row in language_rows)
        global_language_labels = {
            normalize_scalar(row["language_code"]).lower(): normalize_scalar(row["language"])
            for row in language_rows
        }
        workspace_languages = _choice_map(str(value) for value in (client["config_languages"] or []))
        languages = {key: global_languages[key] for key in workspace_languages if key in global_languages}
        return ResolverValues(
            customer_name=str(client["name"]), topics=topics, products=products,
            platforms=platforms, countries=workspace_countries, languages=languages,
            intents=_choice_map(str(row["intent_name"]) for row in intent_rows),
            platform_countries=platform_countries,
            ambiguous_topics=ambiguous_topics,
            quota=int(client["client_prompt_quota"] or 0),
            display_labels={
                "AI Platform": platform_labels,
                "Language": {
                    value: global_language_labels.get(key) or value
                    for key, value in languages.items()
                },
            },
        )

    @tenant_scoped
    async def allowed_values(self, client_id: str, *, locale: str = "zh-CN") -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            resolver = await self._resolver(conn, client_id)
        rows: list[dict[str, str]] = []
        def add(kind: str, value: str, *, label: str | None = None, parent_type: str = "", parent_value: str = "", notes: str = ""):
            rows.append({"type": kind, "value": value, "label": label or value,
                         "parent_type": parent_type, "parent_value": parent_value, "notes": notes})
        for _, (topic_id, topic) in sorted(resolver.topics.items()):
            add("Topic", topic)
            for product in resolver.products.get(topic_id, {}).values():
                add("Product", product, parent_type="Topic", parent_value=topic)
        for value in resolver.platforms.values():
            add("AI Platform", value, label=resolver.display_labels.get("AI Platform", {}).get(value))
        for value in resolver.countries.values(): add("Country", value)
        for value in resolver.languages.values():
            language_label = _localized_language_label(
                value,
                resolver.display_labels.get("Language", {}).get(value),
                locale,
            )
            add("Language", value, label=language_label)
        for value in resolver.intents.values(): add("Intent", value)
        return {"customer_name": resolver.customer_name, "rows": rows}

    @tenant_scoped
    async def template_csv(self, client_id: str) -> bytes:
        async with self.pool.acquire() as conn:
            resolver = await self._resolver(conn, client_id)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(CSV_HEADERS)
        if resolver.topics:
            _, (topic_id, topic) = next(iter(sorted(resolver.topics.items())))
            product = next(iter(resolver.products.get(topic_id, {}).values()), "")
            platforms = list(resolver.platforms.values())
            language = next(iter(resolver.languages.values()), "")
            intent = next(iter(resolver.intents.values()), "")
            first_platform = next(
                (value for value in platforms if resolver.platform_countries.get(value)),
                platforms[0] if platforms else "",
            )
            first_supported = sorted(resolver.platform_countries.get(first_platform, ()))
            first_country = first_supported[0] if first_supported else ""
            sample_platforms = [first_platform] if first_platform else []
            common_countries = set(first_supported)
            for candidate in platforms:
                if candidate == first_platform:
                    continue
                shared = common_countries.intersection(
                    resolver.platform_countries.get(candidate, frozenset())
                )
                if shared:
                    sample_platforms.append(candidate)
                    common_countries = shared
                    break
            sample_countries = sorted(common_countries)[:2]
            if len(sample_platforms) == 1:
                sample_countries = sorted(
                    resolver.platform_countries.get(first_platform, frozenset())
                )[:2]
            writer.writerow([resolver.customer_name, topic, product, PROMPT_PLACEHOLDER,
                             first_platform, first_country, language, intent])
            writer.writerow([resolver.customer_name, topic, product, PROMPT_PLACEHOLDER,
                             "|".join(sample_platforms), "|".join(sample_countries), language, intent])
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    @tenant_scoped
    async def preview(self, client_id: str, raw: bytes) -> ImportPreview:
        async with self.pool.acquire() as conn:
            return await self._preview_on_connection(conn, client_id, raw)

    async def _preview_on_connection(self, conn, client_id: str, raw: bytes) -> ImportPreview:
        resolver = await self._resolver(conn, client_id)
        parsed = PromptImportParser(resolver, limits=self.limits).parse(raw, collect_invalid=True)
        topic_ids = sorted({variant.topic_id for variant in parsed.variants})
        prompt_keys = sorted({canonical_prompt_text(variant.prompt) for variant in parsed.variants})
        existing = await conn.fetch(
            "SELECT id, topic_id, text, product, intent, platform, country, language, is_active "
            "FROM geo_client_prompts WHERE client_id = $1::uuid "
            "AND topic_id = ANY($2::uuid[]) "
            "AND LOWER(REGEXP_REPLACE(TRIM(text), '\\s+', ' ', 'g')) = ANY($3::text[]) "
            "ORDER BY id",
            client_id, [UUID(value) for value in topic_ids], prompt_keys,
        ) if parsed.variants else []
        active_rows = await conn.fetch(
            "SELECT DISTINCT topic_id, LOWER(REGEXP_REPLACE(TRIM(text), '\\s+', ' ', 'g')) AS normalized_text "
            "FROM geo_client_prompts WHERE client_id = $1::uuid AND is_active = TRUE",
            client_id,
        )
        active_logical = {(str(row["topic_id"]), str(row["normalized_text"] if "normalized_text" in row else canonical_prompt_text(row["text"]))) for row in active_rows}
        active_topics_by_text: dict[str, set[str]] = {}
        for topic_id, normalized_text in active_logical:
            active_topics_by_text.setdefault(normalized_text, set()).add(topic_id)
        existing_by_identity: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for record in existing:
            existing_by_identity.setdefault(_identity_key(dict(record)), []).append(dict(record))

        all_declared_variants = [
            variant
            for variants in parsed.row_variants.values()
            for variant in variants
        ]
        unsupported_rows: set[int] = set()
        file_metadata: dict[tuple[str, ...], set[tuple[str, str]]] = {}
        incoming_topics_by_text: dict[str, set[str]] = {}
        for variant in all_declared_variants:
            incoming_topics_by_text.setdefault(
                canonical_prompt_text(variant.prompt), set()
            ).add(variant.topic_id)
            if variant.country not in resolver.platform_countries.get(
                variant.platform, frozenset()
            ):
                unsupported_rows.add(variant.source_rows[0])
        for variant in parsed.variants:
            file_metadata.setdefault(_identity_key(variant), set()).add(
                (
                    normalize_scalar(variant.product or "").lower(),
                    variant.intent.lower(),
                )
            )

        physical_variants: list[dict[str, Any]] = []
        new_logical: set[tuple[str, str]] = set()
        for variant in parsed.variants:
            row_number = variant.source_rows[0]
            action = "create"
            errors: list[dict[str, Any]] = []
            inactive_compatible = False
            if row_number in unsupported_rows:
                action = "invalid"
                errors.append({
                    "code": "platform_country_unsupported",
                    "message": "At least one Platform/Country combination in this input row is unsupported",
                    "details": {"row_number": row_number},
                })
            elif len(file_metadata.get(_identity_key(variant), set())) > 1:
                action = "conflict"
                errors.append({
                    "code": "file_metadata_conflict",
                    "message": "CSV rows define the same physical Prompt variant with different Product or Intent metadata",
                    "details": {"row_number": row_number},
                })
            else:
                matches = existing_by_identity.get(_identity_key(variant), [])
                if matches:
                    incompatible = any(
                        normalize_scalar(row.get("product") or "").lower()
                        != normalize_scalar(variant.product or "").lower()
                        or normalize_scalar(row.get("intent") or "").lower()
                        != variant.intent.lower()
                        for row in matches
                    )
                    if incompatible:
                        action = "conflict"
                        errors.append({
                            "code": "metadata_conflict",
                            "message": "Existing physical variant has different Product or Intent metadata",
                            "details": {"row_number": row_number},
                        })
                    else:
                        action = "skip"
                        active_match = next(
                            (row for row in matches if row.get("is_active") is not False),
                            None,
                        )
                        inactive_compatible = active_match is None
                else:
                    new_logical.add(
                        (variant.topic_id, canonical_prompt_text(variant.prompt))
                    )
            warnings: list[dict[str, str]] = []
            normalized_prompt = canonical_prompt_text(variant.prompt)
            other_topics = (
                active_topics_by_text.get(normalized_prompt, set())
                | incoming_topics_by_text.get(normalized_prompt, set())
            ) - {variant.topic_id}
            if other_topics:
                warnings.append({
                    "code": "prompt_exists_in_other_topic",
                    "message": "The same normalized Prompt exists in another Topic; this is allowed",
                    "details": {"other_topic_count": len(other_topics)},
                })
            if inactive_compatible:
                warnings.append({
                    "code": "inactive_variant_remains_inactive",
                    "message": "Compatible inactive Prompt variant already exists and will remain inactive",
                    "details": {},
                })
            physical_row = {
                **variant.manifest_dict(),
                "row_number": row_number,
                "action": action,
                "errors": errors,
                "warnings": warnings,
            }
            physical_variants.append(physical_row)

        quota_before = len(active_logical)
        quota_after = quota_before + len(new_logical - active_logical)
        if quota_after > resolver.quota:
            for variant in physical_variants:
                if variant["action"] == "create":
                    variant["action"] = "invalid"
                    variant["errors"].append({
                        "code": "quota_exceeded",
                        "message": f"Prompt quota would be {quota_after}; allowed maximum is {resolver.quota}",
                        "actual": quota_after,
                        "allowed": resolver.quota,
                        "details": {"actual": quota_after, "allowed": resolver.quota},
                    })

        parse_issues = {
            int(row["row_number"]): row for row in parsed.invalid_rows
        }
        for variant in physical_variants:
            issue = parse_issues.get(int(variant["row_number"]))
            if not issue:
                continue
            issue_errors = list(issue.get("errors", []))
            early_errors = [
                error
                for error in variant["errors"]
                if error.get("code") in {"platform_country_unsupported", "quota_exceeded"}
            ]
            remaining_errors = [
                error
                for error in variant["errors"]
                if error.get("code") not in {"platform_country_unsupported", "quota_exceeded"}
            ]
            variant["action"] = "invalid"
            variant["errors"] = early_errors + issue_errors + remaining_errors

        physical_by_key = {
            (
                str(row["topic_id"]), canonical_prompt_text(row["prompt"]),
                normalize_scalar(row["product"] or "").lower(),
                normalize_scalar(row["platform"]).lower(),
                normalize_scalar(row["country"]).lower(),
                normalize_scalar(row["language"]).lower(),
                normalize_scalar(row["intent"]).lower(),
            ): row
            for row in physical_variants
        }
        preview_rows: list[dict[str, Any]] = []
        normalized_by_number = {row.row_number: row for row in parsed.rows}
        all_row_numbers = sorted(set(normalized_by_number) | set(parse_issues))
        for row_number in all_row_numbers:
            normalized = normalized_by_number.get(row_number)
            issue = parse_issues.get(row_number)
            if normalized is None:
                preview_rows.append(dict(issue or {}))
                continue
            declared = parsed.row_variants.get(row_number, ())
            variant_rows: list[dict[str, Any]] = []
            for variant in declared:
                key = variant.exact_key + (variant.intent.lower(),)
                source = physical_by_key.get(key)
                variant_rows.append(
                    {**dict(source), "row_number": row_number}
                    if source is not None
                    else {
                        **variant.manifest_dict(),
                        "row_number": row_number,
                        "action": "invalid"
                        if issue or row_number in unsupported_rows
                        else "create",
                        "errors": (
                            [{
                                "code": "platform_country_unsupported",
                                "message": "At least one Platform/Country combination in this input row is unsupported",
                                "details": {"row_number": row_number},
                            }]
                            if row_number in unsupported_rows
                            else list((issue or {}).get("errors", []))
                        ),
                        "warnings": [],
                    }
                )
            issue_errors = list((issue or {}).get("errors", []))
            variant_errors: list[dict[str, Any]] = []
            warnings: list[dict[str, Any]] = []
            for variant in variant_rows:
                variant_errors.extend(variant.get("errors", []))
                warnings.extend(variant.get("warnings", []))
            early_codes = {"platform_country_unsupported", "quota_exceeded"}
            early_errors = [
                error for error in variant_errors if error.get("code") in early_codes
            ]
            remaining_errors = [
                error for error in variant_errors if error.get("code") not in early_codes
            ]
            errors = early_errors + issue_errors + remaining_errors
            errors = list({json.dumps(value, sort_keys=True): value for value in errors}.values())
            warnings = list({json.dumps(value, sort_keys=True): value for value in warnings}.values())
            actions = {variant["action"] for variant in variant_rows}
            if issue or "invalid" in actions:
                row_action = "invalid"
                if issue:
                    for variant in variant_rows:
                        variant["action"] = "invalid"
                        variant["errors"] = list(errors)
            elif "conflict" in actions:
                row_action = "conflict"
            elif "create" in actions:
                row_action = "create"
            else:
                row_action = "skip"
            preview_rows.append({
                "row_number": row_number,
                "customer_name": normalized.customer_name,
                "topic_id": normalized.topic_id,
                "topic": normalized.topic,
                "product": normalized.product,
                "prompt": normalized.prompt,
                "platforms": list(normalized.platforms),
                "countries": list(normalized.countries),
                "language": normalized.language,
                "intent": normalized.intent,
                "expanded_count": len(declared),
                "action": row_action,
                "errors": errors,
                "warnings": warnings,
                "variants": variant_rows,
            })

        counts = {action: 0 for action in ("create", "skip", "conflict", "invalid")}
        for row in preview_rows:
            variants = row.get("variants", [])
            if not variants:
                counts[row["action"]] += 1
                continue
            for variant in variants:
                counts[variant["action"]] += 1

        manifest_rows = [
            {
                key: value
                for key, value in row.items()
                if key not in {"row_number", "warnings"}
            }
            for row in physical_variants
        ]
        state = {
            "input": parsed.normalized_manifest_sha256,
            "resolver": asdict(resolver),
            "active_logical": sorted(active_logical),
            "quota_before": quota_before,
            "quota_after": quota_after,
            "physical_variants": manifest_rows,
            "rows": [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"row_number", "warnings", "variants"}
                }
                for row in preview_rows
            ],
        }
        state_json = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=sorted).encode("utf-8")
        return ImportPreview(
            raw_csv_sha256=parsed.raw_csv_sha256,
            normalized_manifest_sha256=parsed.normalized_manifest_sha256,
            preview_state_sha256=hashlib.sha256(state_json).hexdigest(),
            input_row_count=len(all_row_numbers),
            expanded_variant_count=parsed.declared_expanded_variant_count,
            unique_physical_variant_count=len(parsed.variants),
            action_counts=counts, quota_before=quota_before, quota_after=quota_after,
            quota_limit=resolver.quota, rows=tuple(preview_rows),
            physical_variants=tuple(physical_variants),
        )

    @tenant_scoped
    async def commit(
        self,
        client_id: str,
        user_id: str,
        filename: str,
        raw: bytes,
        expected_manifest_sha256: str,
        expected_preview_state_sha256: str,
    ) -> dict[str, Any]:
        async def operation(conn):
            preview = await self._preview_on_connection(conn, client_id, raw)
            if (
                preview.normalized_manifest_sha256 != expected_manifest_sha256
                or preview.preview_state_sha256 != expected_preview_state_sha256
            ):
                raise PreviewStaleError(preview)
            if not preview.can_commit:
                raise ImportValidationError("Preview contains conflicts or invalid rows", code="preview_not_committable")
            create_rows = [
                row
                for row in preview.physical_variants
                if row["action"] == "create"
            ]
            prompt_ids = [str(uuid4()) for _ in create_rows]
            repository_rows = [
                {"topic_id": row["topic_id"], "text": row["prompt"], "product": row["product"] or None,
                 "intent": row["intent"], "platform": row["platform"], "country": row["country"],
                 "language": row["language"], "is_active": True}
                for row in create_rows
            ]
            inserted_ids = await PromptRepository(self.pool).bulk_insert_on_connection(
                client_id, conn, repository_rows, prompt_ids=prompt_ids,
            )
            if len(inserted_ids) != len(create_rows):
                raise RuntimeError("Prompt import inserted-count assertion failed")
            batch = await conn.fetchrow(
                "INSERT INTO geo_prompt_import_batches "
                "(client_id, created_by_user_id, source_filename, raw_csv_sha256, normalized_manifest_sha256, "
                "input_row_count, expanded_variant_count, create_count, skip_count, conflict_count, invalid_count, created_prompt_ids, status) "
                "VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::uuid[], 'COMMITTED') RETURNING id",
                client_id, user_id, filename, preview.raw_csv_sha256, preview.normalized_manifest_sha256,
                preview.input_row_count, preview.expanded_variant_count,
                preview.action_counts["create"], preview.action_counts["skip"],
                preview.action_counts["conflict"], preview.action_counts["invalid"],
                [UUID(value) for value in inserted_ids],
            )
            return {
                "batch_id": str(batch["id"]),
                "created": len(inserted_ids),
                "ids": inserted_ids,
                "preview": preview.as_dict(),
            }

        return await PromptWriteCoordinator(self.pool).execute(client_id, operation)

    @tenant_scoped
    async def undo(self, client_id: str, user_id: str, batch_id: str, *, confirmation: bool) -> dict[str, Any]:
        if not confirmation:
            raise ImportValidationError("Undo confirmation is required", code="undo_confirmation_required")

        async def transaction_setup(conn):
            await conn.execute(
                f"SET LOCAL lock_timeout = '{_UNDO_LOCK_TIMEOUT_MS}ms'"
            )
            await conn.execute(
                f"SET LOCAL statement_timeout = '{_UNDO_STATEMENT_TIMEOUT_MS}ms'"
            )

        async def operation(conn):
            batch = await conn.fetchrow(
                "SELECT id, client_id, created_prompt_ids, status FROM geo_prompt_import_batches "
                "WHERE client_id = $1::uuid AND id = $2::uuid FOR UPDATE",
                client_id, batch_id,
            )
            if not batch:
                raise ImportValidationError("Import batch not found", code="batch_not_found")
            if batch["status"] == "REVERTED":
                return {"batch_id": str(batch["id"]), "status": "REVERTED", "already_reverted": True, "deleted": 0}
            if batch["status"] != "COMMITTED":
                raise ImportValidationError("Import batch is already reverting", code="batch_reverting")
            created_prompt_ids = [str(value) for value in (batch["created_prompt_ids"] or [])]
            footprint = await conn.fetchval(
                """
                SELECT /* prompt_undo_footprint */
                    (SELECT COUNT(*) FROM geo_client_prompts
                     WHERE client_id = $1::uuid AND id = ANY($2::uuid[]))
                  + (SELECT COUNT(*) FROM geo_sentiment_themes
                     WHERE client_id = $1::uuid AND client_prompt_id = ANY($2::uuid[]))
                  + (SELECT COUNT(*) FROM geo_sentiment_results
                     WHERE client_id = $1::uuid AND client_prompt_id = ANY($2::uuid[]))
                  + (SELECT COUNT(*) FROM geo_citations
                     WHERE client_id = $1::uuid AND client_prompt_id = ANY($2::uuid[]))
                  + (SELECT COUNT(*) FROM geo_product_mentions
                     WHERE client_id = $1::uuid AND client_prompt_id = ANY($2::uuid[]))
                  + (SELECT COUNT(*) FROM geo_brand_mentions
                     WHERE client_id = $1::uuid AND client_prompt_id = ANY($2::uuid[]))
                  + (SELECT COUNT(*) FROM geo_results
                     WHERE client_id = $1::uuid AND client_prompt_id = ANY($2::uuid[]))
                  + (SELECT COUNT(*) FROM geo_tasks
                     WHERE client_id = $1::uuid AND client_prompt_id = ANY($2::uuid[]))
                """,
                client_id,
                created_prompt_ids,
            ) or 0
            footprint = int(footprint)
            large_footprint_warning = (
                footprint > self.undo_large_footprint_warning
            )
            await conn.execute(
                "UPDATE geo_prompt_import_batches SET status = 'REVERTING' "
                "WHERE client_id = $1::uuid AND id = $2::uuid AND status = 'COMMITTED'",
                client_id, batch_id,
            )
            result = await PromptCascadeDeletionService(self.pool).delete_many_on_connection(
                client_id, conn, created_prompt_ids,
            )
            await conn.execute(
                "UPDATE geo_prompt_import_batches SET status = 'REVERTED', reverted_at = NOW(), reverted_by_user_id = $3::uuid "
                "WHERE client_id = $1::uuid AND id = $2::uuid AND status = 'REVERTING'",
                client_id, batch_id, user_id,
            )
            return {
                "batch_id": str(batch["id"]),
                "status": "REVERTED",
                "already_reverted": False,
                "deleted": result.deleted_prompts,
                "cascade": asdict(result),
                "footprint": footprint,
                "large_footprint_warning": large_footprint_warning,
            }

        async with self.undo_limiter.slot():
            return await PromptWriteCoordinator(self.pool).execute(
                client_id,
                operation,
                transaction_setup=transaction_setup,
            )
