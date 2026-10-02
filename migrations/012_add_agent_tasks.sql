-- 012_add_agent_tasks.sql
-- Unified background task table for Analysis & Content Generation workflows.
-- Both task types use the same table, differentiated by task_type.
-- Follows the fire-and-forget pattern from geo_report_runs.

CREATE TABLE IF NOT EXISTS geo_agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    task_type TEXT NOT NULL,              -- 'analysis' | 'content_generation'
    task_name TEXT,
    status TEXT DEFAULT 'DRAFT',          -- DRAFT | RUNNING | COMPLETED | FAILED

    -- Workflow tracking
    workflow_steps JSONB,                 -- [{step:1, name:"strategy", label:"策略分析", status:"pending|running|done|failed"}]
    current_step INTEGER DEFAULT 0,

    -- Inputs (collected via form or conversation)
    inputs JSONB NOT NULL DEFAULT '{}',
    template_id TEXT,

    -- Outputs
    output JSONB,                         -- {content, charts, insights_markdown, raft_scores, ...}
    status_logs JSONB DEFAULT '[]',       -- [{step, event, label, ts}]
    error_message TEXT,

    -- Scheduling & linking
    thread_id TEXT,                        -- Link to agent_sessions if created via chat
    triggered_by TEXT DEFAULT 'manual',    -- manual | chat | cron
    model_used TEXT,

    -- Timestamps
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_client
    ON geo_agent_tasks(client_id, task_type, created_at DESC);
