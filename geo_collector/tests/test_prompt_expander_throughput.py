from datetime import datetime, timezone
import sys
import types
from zoneinfo import ZoneInfo

google_cloud = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
google_cloud.pubsub_v1 = types.SimpleNamespace(PublisherClient=object)
sys.modules.setdefault("google.cloud.pubsub_v1", google_cloud.pubsub_v1)

from src.services.prompt_expander import (
    EffectivePromptExpansionSettings,
    build_final_prompt_reuse_key,
    resolve_prompt_expansion_settings,
    shanghai_batch_id,
)


def test_resolve_prompt_expansion_settings_prefers_client_values():
    settings = resolve_prompt_expansion_settings(
        client={
            "reuse_latest_final_prompt": True,
            "country_localization_mode": "localized_by_country",
            "final_prompt_per_client_prompt": 3,
            "default_calls_per_prompt": 7,
        },
        global_configs={
            "final_prompt_per_client_prompt": "1",
            "default_calls_per_prompt": "1",
        },
    )

    assert settings == EffectivePromptExpansionSettings(
        reuse_latest_final_prompt=True,
        country_localization_mode="localized_by_country",
        final_prompt_per_client_prompt=3,
        default_calls_per_prompt=7,
    )


def test_resolve_prompt_expansion_settings_falls_back_to_global_then_one():
    settings = resolve_prompt_expansion_settings(
        client={
            "reuse_latest_final_prompt": None,
            "country_localization_mode": None,
            "final_prompt_per_client_prompt": None,
            "default_calls_per_prompt": None,
        },
        global_configs={
            "final_prompt_per_client_prompt": "4",
            "default_calls_per_prompt": "not-an-int",
        },
    )

    assert settings.reuse_latest_final_prompt is False
    assert settings.country_localization_mode == "generic"
    assert settings.final_prompt_per_client_prompt == 4
    assert settings.default_calls_per_prompt == 1


def test_build_final_prompt_reuse_key_generic_ignores_country_and_platform():
    prompt = {
        "client_id": "client-1",
        "id": "prompt-1",
        "text": "",
        "language": "en",
        "country": "US",
        "platform": "chatgpt",
    }

    assert build_final_prompt_reuse_key(prompt, "generic") == (
        "client-1",
        "prompt-1",
        "en",
    )


def test_build_final_prompt_reuse_key_localized_includes_country_not_platform():
    prompt = {
        "client_id": "client-1",
        "id": "prompt-1",
        "text": "",
        "language": "en",
        "country": "JP",
        "platform": "perplexity",
    }

    assert build_final_prompt_reuse_key(prompt, "localized_by_country") == (
        "client-1",
        "prompt-1",
        "en",
        "JP",
    )


def test_build_final_prompt_reuse_key_uses_prompt_text_as_logical_identity():
    first = {
        "client_id": "client-1",
        "id": "row-chatgpt-us",
        "text": "  What is the best robot vacuum for pet hair? ",
        "language": "en-US",
        "country": "US",
        "platform": "chatgpt",
    }
    second = {
        "client_id": "client-1",
        "id": "row-perplexity-jp",
        "text": "What is the best robot vacuum for pet hair?",
        "language": "en-US",
        "country": "JP",
        "platform": "perplexity",
    }

    assert build_final_prompt_reuse_key(first, "generic") == build_final_prompt_reuse_key(second, "generic")


def test_shanghai_batch_id_uses_business_date_not_utc_date():
    utc_now = datetime(2026, 6, 3, 16, 30, tzinfo=timezone.utc)

    assert utc_now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() == "2026-06-04"
    assert shanghai_batch_id(utc_now) == "2026-06-04"
