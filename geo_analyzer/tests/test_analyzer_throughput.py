import os

from main import (
    ShardConfig,
    build_shard_predicate,
    resolve_shard_config,
    stable_advisory_lock_keys,
)


def test_resolve_shard_config_defaults_to_single_local_task(monkeypatch):
    monkeypatch.delenv("CLOUD_RUN_TASK_INDEX", raising=False)
    monkeypatch.delenv("CLOUD_RUN_TASK_COUNT", raising=False)

    assert resolve_shard_config(os.environ) == ShardConfig(task_index=0, task_count=1)


def test_resolve_shard_config_reads_cloud_run_task_env(monkeypatch):
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "3")
    monkeypatch.setenv("CLOUD_RUN_TASK_COUNT", "8")

    assert resolve_shard_config(os.environ) == ShardConfig(task_index=3, task_count=8)


def test_build_shard_predicate_uses_hashtext_and_modulo():
    predicate = build_shard_predicate("result_id", task_count_param="$3", task_index_param="$4")

    assert "hashtext(result_id::text)" in predicate
    assert "MOD(" in predicate
    assert "$3" in predicate
    assert "$4" in predicate


def test_stable_advisory_lock_keys_are_stable_and_32_bit_signed():
    first = stable_advisory_lock_keys("client-a", "2026-06-03", 2, 8)
    second = stable_advisory_lock_keys("client-a", "2026-06-03", 2, 8)
    different = stable_advisory_lock_keys("client-a", "2026-06-04", 2, 8)

    assert first == second
    assert first != different
    assert all(-(2**31) <= key < 2**31 for key in first)
