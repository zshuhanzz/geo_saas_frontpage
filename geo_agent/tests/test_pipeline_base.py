from pipelines import base


def test_update_step_status_never_moves_current_step_backward():
    sql_consts = [
        const
        for const in base.update_step_status.__code__.co_consts
        if isinstance(const, str)
    ]

    assert any("GREATEST(COALESCE(current_step, 0), $2)" in sql for sql in sql_consts)
