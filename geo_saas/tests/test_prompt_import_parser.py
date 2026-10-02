from __future__ import annotations

import csv
import io

import pytest

from routers.prompt_import_service import (
    CSV_HEADERS,
    ImportLimits,
    ImportValidationError,
    PromptImportParser,
    ResolverValues,
)


def _resolver() -> ResolverValues:
    return ResolverValues(
        customer_name="AnswerX",
        topics={"robot vacuum": ("topic-1", "Robot Vacuum")},
        products={"topic-1": {"s8 maxv": "S8 MaxV"}},
        platforms={"chatgpt": "chatgpt", "gemini": "gemini"},
        countries={"us": "US", "de": "DE"},
        languages={"en-us": "en-US", "de-de": "de-DE"},
        intents={"solution discovery": "Solution Discovery"},
        platform_countries={"chatgpt": frozenset({"US", "DE"}), "gemini": frozenset({"US"})},
    )


def _csv(rows: list[list[str]], *, bom: bool = False) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(CSV_HEADERS)
    writer.writerows(rows)
    value = stream.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + value) if bom else value


def _row(**overrides: str) -> list[str]:
    values = {
        "Customer Name": "AnswerX",
        "Topic": "Robot Vacuum",
        "Product": "S8 MaxV",
        "Prompt": "Best robot vacuum?",
        "AI Platforms": "chatgpt",
        "Countries": "US",
        "Language": "en-US",
        "Intent": "Solution Discovery",
    }
    values.update(overrides)
    return [values[column] for column in CSV_HEADERS]


def test_parser_accepts_bom_csv_quoting_and_all_ascii_delimiters() -> None:
    parsed = PromptImportParser(_resolver()).parse(
        _csv(
            [_row(**{"AI Platforms": " ChatGPT, gemini;CHATGPT| ", "Countries": " US | DE;US "})],
            bom=True,
        )
    )

    row = parsed.rows[0]
    assert row.platforms == ("chatgpt", "gemini")
    assert row.countries == ("US", "DE")
    assert len(parsed.variants) == 4
    assert parsed.raw_csv_sha256
    assert parsed.normalized_manifest_sha256


def test_parser_rejects_unquoted_comma_inside_multi_value_cell() -> None:
    raw = (
        ",".join(CSV_HEADERS)
        + "\nAnswerX,Robot Vacuum,S8 MaxV,Best robot vacuum?,chatgpt,gemini,US,en-US,Solution Discovery\n"
    ).encode()
    with pytest.raises(ImportValidationError, match="quoted"):
        PromptImportParser(_resolver()).parse(raw)


@pytest.mark.parametrize("delimiter", ["，", "；"])
def test_parser_rejects_full_width_multi_value_punctuation(delimiter: str) -> None:
    with pytest.raises(ImportValidationError, match="ASCII"):
        PromptImportParser(_resolver()).parse(
            _csv([_row(**{"AI Platforms": f"chatgpt{delimiter}gemini"})])
        )


def test_parser_requires_exact_header_order() -> None:
    raw = _csv([_row()]).replace(b"Customer Name,Topic", b"Topic,Customer Name", 1)
    with pytest.raises(ImportValidationError, match="headers"):
        PromptImportParser(_resolver()).parse(raw)


def test_parser_rejects_header_only_upload() -> None:
    with pytest.raises(ImportValidationError, match="non-empty data row"):
        PromptImportParser(_resolver()).parse(_csv([]))


def test_customer_name_requires_exact_canonical_workspace_name() -> None:
    with pytest.raises(ImportValidationError, match="exactly match"):
        PromptImportParser(_resolver()).parse(_csv([_row(**{"Customer Name": " AnswerX "})]))


def test_validation_precedence_checks_intent_before_platform_country_and_language() -> None:
    parsed = PromptImportParser(_resolver()).parse(
        _csv([_row(Intent="Disabled Intent", **{
            "AI Platforms": "unknown", "Countries": "ZZ", "Language": "xx-XX"
        })]),
        collect_invalid=True,
    )
    assert parsed.invalid_rows[0]["errors"][0]["code"] == "intent_not_allowed"
    assert parsed.invalid_rows[0]["errors"][0]["details"] == {
        "field": "Intent",
        "value": "Disabled Intent",
    }


def test_language_is_single_value_and_template_placeholder_is_rejected() -> None:
    parser = PromptImportParser(_resolver())
    with pytest.raises(ImportValidationError, match="Language"):
        parser.parse(_csv([_row(Language="en-US|de-DE")]))
    with pytest.raises(ImportValidationError, match="replace"):
        parser.parse(_csv([_row(Prompt="[REPLACE WITH YOUR PROMPT]")]))


def test_non_overlapping_multi_row_expansions_remain_distinct_physical_variants() -> None:
    parsed = PromptImportParser(_resolver()).parse(
        _csv(
            [
                _row(**{"AI Platforms": "ChatGPT", "Countries": "us"}),
                _row(**{"AI Platforms": "gemini", "Countries": "US", "Prompt": " Best   robot vacuum? "}),
            ]
        )
    )
    assert len(parsed.rows) == 2
    assert len(parsed.variants) == 2
    assert parsed.declared_expanded_variant_count == 2


def test_overlapping_duplicate_row_is_invalid_and_references_first_source_row() -> None:
    parsed = PromptImportParser(_resolver()).parse(
        _csv([_row(), _row(Prompt=" Best   robot vacuum? ")]),
        collect_invalid=True,
    )
    assert parsed.declared_expanded_variant_count == 2
    assert len(parsed.variants) == 1
    duplicate = next(row for row in parsed.invalid_rows if row["row_number"] == 3)
    assert duplicate["errors"][0]["code"] == "file_duplicate"
    assert duplicate["errors"][0]["first_row_number"] == 2


def test_partially_overlapping_expansion_invalidates_entire_later_row() -> None:
    parsed = PromptImportParser(_resolver()).parse(
        _csv([
            _row(**{"AI Platforms": "chatgpt"}),
            _row(**{"AI Platforms": "chatgpt|gemini"}),
        ]),
        collect_invalid=True,
    )
    assert parsed.declared_expanded_variant_count == 3
    assert len(parsed.variants) == 2
    assert parsed.invalid_rows[0]["row_number"] == 3
    assert parsed.invalid_rows[0]["errors"][0]["first_row_number"] == 2


def test_overlap_with_multiple_earlier_rows_reports_every_first_declaration() -> None:
    parsed = PromptImportParser(_resolver()).parse(
        _csv([
            _row(**{"AI Platforms": "chatgpt"}),
            _row(**{"AI Platforms": "gemini"}),
            _row(**{"AI Platforms": "chatgpt|gemini"}),
        ]),
        collect_invalid=True,
    )

    duplicate = next(row for row in parsed.invalid_rows if row["row_number"] == 4)
    error = duplicate["errors"][0]
    assert error["code"] == "file_duplicate"
    assert error["first_row_number"] == 2
    assert error["first_row_numbers"] == [2, 3]
    assert "rows 2, 3" in error["message"]


def test_same_physical_variant_with_different_intent_is_invalid_overlap() -> None:
    base = _resolver()
    resolver = ResolverValues(
        **{
            **base.__dict__,
            "intents": {
                "solution discovery": "Solution Discovery",
                "specifics inquiry": "Specifics Inquiry",
            },
        }
    )
    parsed = PromptImportParser(resolver).parse(
        _csv([_row(), _row(Intent="Specifics Inquiry")]),
        collect_invalid=True,
    )
    assert len(parsed.variants) == 1
    assert parsed.invalid_rows[0]["errors"][0]["code"] == "file_duplicate"
    assert parsed.invalid_rows[0]["errors"][0]["first_row_number"] == 2


@pytest.mark.parametrize(
    ("limits", "raw", "message"),
    [
        (ImportLimits(max_bytes=5), b"123456", "bytes"),
        (ImportLimits(max_rows=1), _csv([_row(), _row(Prompt="Another")]), "rows"),
        (ImportLimits(max_variants_per_row=1), _csv([_row(**{"AI Platforms": "chatgpt|gemini"})]), "one row"),
        (ImportLimits(max_variants=1), _csv([_row(**{"AI Platforms": "chatgpt|gemini"})]), "variants"),
    ],
)
def test_parser_enforces_every_fixed_limit(limits: ImportLimits, raw: bytes, message: str) -> None:
    with pytest.raises(ImportValidationError, match=message):
        PromptImportParser(_resolver(), limits=limits).parse(raw)


def test_manifest_is_deterministic_across_row_and_delimiter_order() -> None:
    parser = PromptImportParser(_resolver())
    first = parser.parse(_csv([_row(**{"AI Platforms": "gemini|chatgpt"})]))
    second = parser.parse(_csv([_row(**{"AI Platforms": "chatgpt;gemini"})]))
    assert first.normalized_manifest_sha256 == second.normalized_manifest_sha256


def test_single_row_multi_values_and_split_rows_share_canonical_manifest() -> None:
    parser = PromptImportParser(_resolver())
    multi_value = parser.parse(
        _csv([_row(**{"AI Platforms": "chatgpt|gemini", "Countries": "US|DE"})])
    )
    split_rows = parser.parse(
        _csv(
            [
                _row(**{"AI Platforms": "chatgpt", "Countries": "US|DE"}),
                _row(**{"AI Platforms": "gemini", "Countries": "US|DE"}),
            ]
        )
    )

    assert len(multi_value.variants) == len(split_rows.variants) == 4
    assert multi_value.normalized_manifest_sha256 == split_rows.normalized_manifest_sha256
