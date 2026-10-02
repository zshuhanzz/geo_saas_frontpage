"""Tests for admin task/result response models."""
from uuid import uuid4

from routers.tasks import RESULT_UUID_FIELDS, ResultRow, _build_task_where, serialize_row


def test_result_row_allows_legacy_missing_prompt_metadata():
    row = ResultRow(
        result_id=1,
        task_id=None,
        client_prompt_id=None,
        text_preview="Legacy result row",
    )

    assert row.task_id is None
    assert row.client_prompt_id is None


def test_task_status_filter_is_case_insensitive():
    where_sql, params = _build_task_where(
        alias="t",
        base=["t.client_id = :client_id"],
        base_params={"client_id": "client-1"},
        status="completed",
    )

    assert "UPPER(TRIM(t.status)) = :status" in where_sql
    assert params["status"] == "COMPLETED"


def test_result_serialization_converts_topic_id_uuid():
    topic_id = uuid4()

    row = serialize_row(
        {
            "result_id": 1,
            "task_id": uuid4(),
            "client_prompt_id": uuid4(),
            "client_id": uuid4(),
            "topic_id": topic_id,
        },
        RESULT_UUID_FIELDS,
        [],
    )

    result = ResultRow(**row)

    assert result.topic_id == str(topic_id)
