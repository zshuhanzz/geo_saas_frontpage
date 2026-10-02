-- ============================================================
-- Migration 045: Dual-Mode Tracking v1.2 - 清空 Agent 运行态
-- ============================================================
-- Spec §11.3
--
-- 背景:产品无线上用户,agent 运行态(checkpoints / messages / memories /
-- agent_tasks)无保留价值。且历史内容含旧 schema 的 SQL 文本,
-- 若不清空,agent thread resume 时可能执行旧 SQL 报错。
--
-- ⚠️ 执行此文件前确认:Agent Cloud Run service 已停。
-- ============================================================

BEGIN;

TRUNCATE TABLE checkpoints;                       -- LangGraph state snapshots
TRUNCATE TABLE agent_messages;                     -- 聊天历史
TRUNCATE TABLE agent_memories;                     -- 跨会话记忆
TRUNCATE TABLE geo_agent_tasks CASCADE;            -- 历史 agent 任务产出(CASCADE 到 geo_content_assets 等引用表)

COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- SELECT 'checkpoints', COUNT(*) FROM checkpoints
-- UNION ALL SELECT 'agent_messages', COUNT(*) FROM agent_messages
-- UNION ALL SELECT 'agent_memories', COUNT(*) FROM agent_memories
-- UNION ALL SELECT 'geo_agent_tasks', COUNT(*) FROM geo_agent_tasks;
-- 期望:全部为 0
