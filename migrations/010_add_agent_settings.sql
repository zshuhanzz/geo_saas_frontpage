-- ============================================================
-- Migration 010: Add Agent timeout & rate limit settings
-- ============================================================
-- Adds 4 new keys to geo_global_settings for the Agent module:
--   - agent_timeout_pro_seconds     (default 60)
--   - agent_timeout_flash_seconds   (default 30)
--   - agent_rate_limit_max_requests (default 20)
--   - agent_rate_limit_window_seconds (default 300 = 5 min)
--
-- Safe to re-run: uses ON CONFLICT DO NOTHING.
-- These values are editable via Admin UI → Global Settings.
-- ============================================================

-- Timeout: Gemini Pro (Analyze Agent, Action Agent)
INSERT INTO geo_global_settings (key, value, description)
VALUES ('agent_timeout_pro_seconds', '60', 'Agent Pro 模型调用超时（秒），适用于 Analyze/Action')
ON CONFLICT (key) DO NOTHING;

-- Timeout: Gemini Flash (Supervisor, Chat, title generation)
INSERT INTO geo_global_settings (key, value, description)
VALUES ('agent_timeout_flash_seconds', '30', 'Agent Flash 模型调用超时（秒），适用于 Supervisor/Chat')
ON CONFLICT (key) DO NOTHING;

-- Rate limit: max requests per client in sliding window
INSERT INTO geo_global_settings (key, value, description)
VALUES ('agent_rate_limit_max_requests', '20', 'Agent 每个 client 在窗口期内最大请求次数')
ON CONFLICT (key) DO NOTHING;

-- Rate limit: sliding window duration (seconds)
INSERT INTO geo_global_settings (key, value, description)
VALUES ('agent_rate_limit_window_seconds', '300', 'Agent 滑动窗口时长（秒），默认 5 分钟')
ON CONFLICT (key) DO NOTHING;
