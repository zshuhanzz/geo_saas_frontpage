from routers.strategy import normalize_strategy_payload


def test_normalize_strategy_payload_wraps_root_array():
    payload = [
        {
            "name": "Reddit-native tradeoff post",
            "description": "Use citation patterns without turning promotional.",
            "dimensions": {"tone": "practical"},
        }
    ]

    normalized = normalize_strategy_payload(payload)

    assert normalized["strategies"] == payload
    assert normalized["strategy_summary"] == "Generated 1 strategy option."


def test_normalize_strategy_payload_wraps_single_strategy_object():
    normalized = normalize_strategy_payload(
        {
            "strategies": {
                "name": "Citation-grounded answer",
                "dimensions": {"format": {"structure": "direct answer"}},
            }
        }
    )

    assert len(normalized["strategies"]) == 1
    assert normalized["strategies"][0]["name"] == "Citation-grounded answer"
    assert normalized["strategy_summary"] == "Generated 1 strategy option."


def test_normalize_strategy_payload_converts_string_strategy_to_displayable_entry():
    normalized = normalize_strategy_payload([
        "Use Reddit citation patterns, then write a practical tradeoff post."
    ])

    assert normalized["strategies"][0]["name"] == "Strategy 1"
    assert normalized["strategies"][0]["description"] == (
        "Use Reddit citation patterns, then write a practical tradeoff post."
    )
    assert normalized["strategies"][0]["dimensions"]["instruction"] == (
        "Use Reddit citation patterns, then write a practical tradeoff post."
    )


def test_normalize_strategy_payload_fills_missing_strategy_display_fields():
    normalized = normalize_strategy_payload({
        "strategies": [{
            "title": "Reddit-native citation post",
            "instruction": "Answer the community question with tradeoffs and citeable evidence.",
        }]
    })

    strategy = normalized["strategies"][0]
    assert strategy["name"] == "Reddit-native citation post"
    assert strategy["description"] == "Answer the community question with tradeoffs and citeable evidence."
    assert strategy["dimensions"]["instruction"] == "Answer the community question with tradeoffs and citeable evidence."


def test_normalize_strategy_payload_unwraps_nested_json_string_envelope():
    normalized = normalize_strategy_payload([
        '{"strategies":[{"name":"Hybrid workflow","description":"Use AI as a production assistant.","dimensions":{"tone":"candid"}}],"strategy_summary":"Use a realistic workflow angle."}'
    ])

    assert normalized["strategy_summary"] == "Use a realistic workflow angle."
    assert len(normalized["strategies"]) == 1
    assert normalized["strategies"][0]["name"] == "Hybrid workflow"
    assert normalized["strategies"][0]["description"] == "Use AI as a production assistant."


def test_normalize_strategy_payload_unwraps_nested_json_string_inside_strategies_key():
    normalized = normalize_strategy_payload({
        "strategies": [
            '{"strategies":[{"name":"Anti-slop workflow","description":"Use citation patterns without hard selling.","dimensions":{"tone":"candid"}}],"strategy_summary":"Prefer a Reddit-native workflow angle."}'
        ]
    })

    assert normalized["strategy_summary"] == "Prefer a Reddit-native workflow angle."
    assert len(normalized["strategies"]) == 1
    assert normalized["strategies"][0]["name"] == "Anti-slop workflow"
    assert normalized["strategies"][0]["description"] == "Use citation patterns without hard selling."


def test_normalize_strategy_payload_unwraps_json_envelope_inside_strategy_description():
    normalized = normalize_strategy_payload({
        "strategies": [
            {
                "name": "Strategy 1",
                "description": '{"strategies":[{"name":"Evaluation strategy","description":"Use comparison structure and fill the brand gap.","dimensions":{"tone":"official"}}],"strategy_summary":"Use citation patterns."}',
                "dimensions": {
                    "instruction": '{"strategies":[{"name":"Evaluation strategy","description":"Use comparison structure and fill the brand gap.","dimensions":{"tone":"official"}}],"strategy_summary":"Use citation patterns."}',
                },
            }
        ]
    })

    assert normalized["strategy_summary"] == "Use citation patterns."
    assert len(normalized["strategies"]) == 1
    assert normalized["strategies"][0]["name"] == "Evaluation strategy"
    assert normalized["strategies"][0]["description"] == "Use comparison structure and fill the brand gap."
