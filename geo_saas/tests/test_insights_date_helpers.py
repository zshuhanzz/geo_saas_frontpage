from routers.insights._helpers import SHANGHAI_TZ, date_bucket_expr, date_range_filter_expr, local_date_expr


def test_local_date_expr_uses_shanghai_timezone():
    assert local_date_expr("bm.executed_at") == "(bm.executed_at AT TIME ZONE 'Asia/Shanghai')::date"


def test_date_bucket_expr_can_bucket_in_shanghai_timezone():
    assert date_bucket_expr("gr.ingested_at", "daily", timezone=SHANGHAI_TZ) == "(gr.ingested_at AT TIME ZONE 'Asia/Shanghai')::date"
    assert date_bucket_expr("gr.ingested_at", "weekly", timezone=SHANGHAI_TZ) == "date_trunc('week', gr.ingested_at AT TIME ZONE 'Asia/Shanghai')::date"
    assert date_bucket_expr("gr.ingested_at", "monthly", timezone=SHANGHAI_TZ) == "date_trunc('month', gr.ingested_at AT TIME ZONE 'Asia/Shanghai')::date"


def test_date_range_filter_expr_uses_local_date_bounds():
    assert date_range_filter_expr("gr.ingested_at", "start_date", "end_date") == (
        "(gr.ingested_at AT TIME ZONE 'Asia/Shanghai')::date >= :start_date "
        "AND (gr.ingested_at AT TIME ZONE 'Asia/Shanghai')::date <= :end_date"
    )
