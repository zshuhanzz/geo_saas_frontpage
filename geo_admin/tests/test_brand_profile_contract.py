from routers.brand_profiles import BrandProfileOut


def test_brand_profile_list_fields_are_typed_arrays() -> None:
    schema = BrandProfileOut.model_json_schema()

    for field_name in ("key_messages", "brand_values"):
        field_schema = schema["properties"][field_name]
        array_schema = next(
            candidate
            for candidate in field_schema["anyOf"]
            if candidate.get("type") == "array"
        )
        assert array_schema["items"] == {"type": "string"}
