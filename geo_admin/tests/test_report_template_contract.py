from routers.report_templates import TemplateOut


def test_template_output_exposes_uuid_and_json_object_contracts() -> None:
    schema = TemplateOut.model_json_schema()

    assert schema["properties"]["id"] == {
        "format": "uuid",
        "title": "Id",
        "type": "string",
    }
    for field_name in ("defaults", "wizard_config"):
        field_schema = schema["properties"][field_name]
        object_schema = next(
            candidate
            for candidate in field_schema["anyOf"]
            if candidate.get("type") == "object"
        )
        assert object_schema["additionalProperties"] is True
