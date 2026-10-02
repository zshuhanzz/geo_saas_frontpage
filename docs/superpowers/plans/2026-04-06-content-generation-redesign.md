# Content Generation Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Analyzer→Content pipeline with a three-layer optimization framework (Metrics→Sub-goals→Strategy), upgrade "优化机会发现" Analyzer template with 4-step structured output, and rebuild the Content pipeline as a 7-node slot-filling wizard.

**Architecture:** The three-layer framework (Layer 1: Metrics, Layer 2: Sub-goals, Layer 3: Strategy) is the shared backbone. Analyzer's upgraded "优化机会发现" template produces structured JSON (topic quadrants, content_opportunities, platform_recommendations) that flows into Content Node 0. Content's 7-node pipeline (Node 0–6) replaces the current 5-step content generation workflow. Strategy generation in Node 3 combines user selections + Analyzer context + brand profile to produce structured strategy JSON that drives content generation.

**Tech Stack:** Python 3.11+ / FastAPI / asyncpg (backend), React + TypeScript + Tailwind + shadcn/ui (frontend), Gemini Pro/Flash via google-genai SDK, PostgreSQL (Cloud SQL)

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `migrations/023_content_redesign_framework.sql` | DDL for `geo_optimization_metrics`, `geo_optimization_subgoals`, `geo_strategies`, `geo_content_assets` tables + seed data |
| `geo_agent/src/pipelines/opportunity_pipeline.py` | "优化机会发现" upgraded 4-step pipeline (Topic Quadrant → Content Opportunities → Platform Analysis → Output) |
| `geo_saas/web/src/components/agents/ContentPipelineModal.tsx` | Redesigned 7-node Content pipeline wizard (replaces ContentTaskModal) |
| `geo_saas/web/src/components/agents/nodes/NodeAnalyzerImport.tsx` | Node 0: Analyzer report import |
| `geo_saas/web/src/components/agents/nodes/NodeContentGoals.tsx` | Node 1: Metrics + Sub-goals selection |
| `geo_saas/web/src/components/agents/nodes/NodeContentType.tsx` | Node 2: Content type selection |
| `geo_saas/web/src/components/agents/nodes/NodeStrategy.tsx` | Node 3: Strategy display + user confirmation |
| `geo_saas/web/src/components/agents/nodes/NodeGenConfig.tsx` | Node 4: Generation config (platforms, language, count, brand info) |
| `geo_saas/web/src/components/agents/nodes/NodePromptLink.tsx` | Node 5: Prompt association (locked vs open mode) |
| `geo_saas/web/src/components/agents/nodes/NodeConfirm.tsx` | Node 6: Confirmation + execute |

### Modified Files

| File | Changes |
|------|---------|
| `geo_agent/src/pipelines/content_pipeline.py` | Rewrite pipeline to use new 7-node inputs (metrics, sub-goals, strategy JSON, content_type, analyzer context) |
| `geo_agent/src/routers/tasks.py` | Add `CONTENT_V2_WORKFLOW_STEPS`, new `opportunity_discovery` task type, new API endpoints for framework data |
| `geo_saas/web/src/pages/agents/AgentContent.tsx` | Wire new ContentPipelineModal, pass analyzer task selection |
| `geo_saas/web/src/pages/agents/AgentAnalysis.tsx` | Add CTA button on opportunity reports to jump to Content |
| `geo_saas/web/src/components/insights/TemplateConfigModal.tsx` | Add "情感分析" template entry |
| `geo_saas/web/src/lib/api.ts` | Add API functions for framework endpoints (metrics, subgoals, strategies, opportunity tasks) |
| `geo_agent/src/pipelines/analysis_pipeline.py` | Add ALLOWED_TABLES entries if needed for new queries |

---

## Task 1: Database Schema — Three-Layer Framework + Content Assets

**Files:**
- Create: `migrations/023_content_redesign_framework.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- migrations/023_content_redesign_framework.sql
-- Three-layer optimization framework + content assets for feedback loop

BEGIN;

-- ─── Layer 1 + 2: Optimization Metrics and Sub-goals ────────────────

CREATE TABLE IF NOT EXISTS geo_optimization_metrics (
    id          TEXT PRIMARY KEY,           -- 'readability', 'answerability', 'trustworthy', 'freshness'
    name_zh     TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    description TEXT NOT NULL,
    icon        TEXT DEFAULT '📊',
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS geo_optimization_subgoals (
    id          TEXT PRIMARY KEY,           -- 'content_understandability', 'machine_readability', etc.
    metric_id   TEXT NOT NULL REFERENCES geo_optimization_metrics(id),
    name_zh     TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    description TEXT NOT NULL,
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Layer 3: Strategy definitions ──────────────────────────────────

CREATE TABLE IF NOT EXISTS geo_strategies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT,
    dimensions      JSONB NOT NULL DEFAULT '{}',   -- {instruction, format, tone, constraints, enhancement_rules}
    source_metrics  TEXT[] DEFAULT '{}',            -- metric ids
    source_subgoals TEXT[] DEFAULT '{}',            -- subgoal ids
    content_type    TEXT,                           -- 'faq', 'aeo_article', etc. NULL = any
    generation_method TEXT DEFAULT 'llm_with_postprocess',
    is_seed         BOOLEAN DEFAULT true,          -- seed vs evolved
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Content Assets (feedback loop reservation) ─────────────────────

CREATE TABLE IF NOT EXISTS geo_content_assets (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    content_task_id   UUID REFERENCES geo_agent_tasks(id) ON DELETE SET NULL,
    published_url     TEXT,
    published_platform TEXT,                        -- 'reddit', 'official_site', 'wiki', etc.
    published_at      TIMESTAMPTZ,
    tracking_status   TEXT DEFAULT 'pending',       -- 'pending', 'tracking', 'completed'
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_assets_client ON geo_content_assets(client_id);
CREATE INDEX IF NOT EXISTS idx_content_assets_task ON geo_content_assets(content_task_id);

-- ─── Add analyzer_task_id to geo_agent_tasks for Content→Analyzer link ──

ALTER TABLE geo_agent_tasks ADD COLUMN IF NOT EXISTS analyzer_task_id UUID REFERENCES geo_agent_tasks(id);

-- ─── Seed Layer 1: Metrics ──────────────────────────────────────────

INSERT INTO geo_optimization_metrics (id, name_zh, name_en, description, icon, sort_order)
VALUES
    ('readability',    '可读性',     'Readability',    '内容是否容易被人类理解、被 AI 引擎解析', '📖', 1),
    ('answerability',  '可做答案性', 'Answerability',  '内容是否能直接成为 AI 回答的素材',       '🎯', 2),
    ('trustworthy',    '可信赖性',   'Trustworthy',    '内容是否具备权威性和可验证性',           '🛡️', 3),
    ('freshness',      '时效性',     'Freshness',      '内容是否紧跟热点且保持时效',             '⏰', 4)
ON CONFLICT (id) DO NOTHING;

-- ─── Seed Layer 2: Sub-goals ────────────────────────────────────────

INSERT INTO geo_optimization_subgoals (id, metric_id, name_zh, name_en, description, sort_order)
VALUES
    ('content_understandability', 'readability',   '内容可理解度', 'Content Understandability', '语言清晰、用词精准、目标受众能读懂', 1),
    ('machine_readability',      'readability',   '机器可读性',   'Machine Readability',       '结构清晰（heading hierarchy）、schema markup、AI 能提取干净的答案', 2),
    ('information_presentation', 'answerability', '信息呈现',     'Information Presentation',  '页面上是否直接呈现了 AI 需要的答案信息', 1),
    ('audience_fit',             'answerability', '受众贴合度',   'Audience Fit',              '内容的目的、调性、key message 是否匹配目标受众', 2),
    ('platform_fit',             'answerability', '平台贴合度',   'Platform Fit',              '内容格式/风格是否匹配发布平台（Wiki、Reddit、测评站等）', 3),
    ('authority_eeat',           'trustworthy',   '权威性 (E-E-A-T)', 'Authority (E-E-A-T)', '专业凭证、第一手经验、权威背书', 1),
    ('verifiability',            'trustworthy',   '可验证性',     'Verifiability',             '引用来源、数据有出处、claims 可被第三方验证', 2),
    ('trending_relevance',       'freshness',     '热点相关度',   'Trending Relevance',        '内容是否紧扣当下与品牌/产品相关的热点话题', 1),
    ('publish_timeliness',       'freshness',     '发布时效',     'Publish Timeliness',        '内容的发布/更新时间，用于评价存量内容', 2)
ON CONFLICT (id) DO NOTHING;

-- ─── Add "情感分析" template to geo_report_templates ────────────────

INSERT INTO geo_report_templates (id, name, description, icon, data_domains, default_prompt, is_builtin, is_active, sort_order, task_type)
VALUES (
    gen_random_uuid(),
    '情感分析',
    '专门针对品牌情感维度的深度分析，识别正面和负面情感主题',
    '💬',
    ARRAY['sentiment'],
    '你是一位品牌情感分析专家。请基于以下品牌在 AI 搜索引擎中的情感数据，进行深度分析。

## 分析要求

1. **情感概览**：正面/中性/负面比例分布
2. **主题拆解**：按情感主题（theme）分析，找出正面主题和负面主题的 Top 5
3. **平台差异**：不同 AI 平台（ChatGPT / Gemini / AI Mode）的情感表现差异
4. **趋势判断**：情感变化趋势，是否有恶化或改善信号
5. **可执行建议**：针对负面情感主题，给出具体的内容优化建议

## 数据指标
- 情绪正面率: {{sentiment_positive_ratio}}
- 情绪负面率: {{sentiment_negative_ratio}}
- 主要正面主题: {{sentiment_positive_themes}}
- 主要负面主题: {{sentiment_negative_themes}}

请用 Markdown 格式输出分析报告。',
    true,
    true,
    5,
    'analysis'
)
ON CONFLICT DO NOTHING;

-- ─── Seed recommended charts for 情感分析 via geo_workflow_config ────

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order)
VALUES
    ('recommended_chart', 'analysis', 'sentiment_distribution', 'sentiment',
     '{"nl_query": "各 AI 平台的情绪分布（正面/中性/负面占比）", "chart_type": "bar"}'::jsonb, 1),
    ('recommended_chart', 'analysis', 'sentiment_themes_pos', 'sentiment',
     '{"nl_query": "品牌正面情绪主题 Top 10", "chart_type": "bar"}'::jsonb, 2),
    ('recommended_chart', 'analysis', 'sentiment_themes_neg', 'sentiment',
     '{"nl_query": "品牌负面情绪主题 Top 10", "chart_type": "bar"}'::jsonb, 3),
    ('recommended_chart', 'analysis', 'sentiment_trend', 'sentiment',
     '{"nl_query": "品牌情绪评分随时间变化趋势", "chart_type": "line"}'::jsonb, 4)
ON CONFLICT DO NOTHING;

-- ─── Seed Layer 3: Strategies (from AgenticGEO paper 9 seed strategies + AnswerX additions) ──

INSERT INTO geo_strategies (name, description, dimensions, source_metrics, source_subgoals, content_type, generation_method, is_seed)
VALUES
    ('结构化问答优化', '以FAQ问答形式组织内容，优化标题层级和 schema markup',
     '{"instruction": "以FAQ问答形式组织，每个问题直接给出答案", "format": {"structure": "Q&A pairs with H2/H3 heading hierarchy", "schema_markup": "FAQPage JSON-LD", "word_count": "每条FAQ 80-150字"}, "tone": "权威但易读，避免行话", "constraints": ["答案首句必须直接回答问题", "每条FAQ包含至少一个可验证的数据点", "不使用模糊表述"], "enhancement_rules": ["生成后自动注入 JSON-LD structured data", "自动添加 internal linking 建议"]}'::jsonb,
     ARRAY['readability', 'answerability'], ARRAY['machine_readability', 'information_presentation'], 'faq', 'llm_with_postprocess', true),

    ('权威性强化', '采用权威专业语调，引用可信来源和数据',
     '{"instruction": "以行业专家视角撰写，强调第一手测试数据和专业分析", "format": {"structure": "论点→证据→结论", "schema_markup": "Article", "word_count": "800-1200字"}, "tone": "专业、权威、数据驱动", "constraints": ["每个核心论点必须有数据支撑", "引用至少2个权威第三方来源", "包含作者专业背景说明"], "enhancement_rules": ["自动补充引用标注格式", "检查数据点的完整性"]}'::jsonb,
     ARRAY['trustworthy'], ARRAY['authority_eeat', 'verifiability'], NULL, 'llm_with_postprocess', true),

    ('易懂性优化', '简化句子结构和用词，提高内容可读性',
     '{"instruction": "用清晰简单的语言解释复杂概念，面向非专业读者", "format": {"structure": "短段落，每段一个核心概念", "word_count": "段落不超过100字"}, "tone": "亲切、易懂、口语化", "constraints": ["避免专业术语或必须解释", "句子长度不超过25字", "使用类比和具体例子"], "enhancement_rules": ["自动检测复杂术语并添加解释"]}'::jsonb,
     ARRAY['readability'], ARRAY['content_understandability'], NULL, 'llm_with_postprocess', true),

    ('引用来源注入', '系统性地注入可信来源引用，提升内容可验证性',
     '{"instruction": "在内容中自然融入权威来源引用，增强可信度", "format": {"structure": "论述+引用穿插"}, "tone": "客观、可验证", "constraints": ["每200字至少一个来源引用", "优先引用行业报告和学术来源", "数据必须标注出处"], "enhancement_rules": ["自动格式化引用标注", "验证引用链接有效性"]}'::jsonb,
     ARRAY['trustworthy'], ARRAY['verifiability'], NULL, 'llm_with_postprocess', true),

    ('数据充实', '用具体数据和统计数字充实内容，提升说服力',
     '{"instruction": "在内容中嵌入具体的数据点、统计数字和对比数据", "format": {"structure": "数据驱动的论述结构"}, "tone": "精准、量化", "constraints": ["关键论点必须有数据支撑", "使用对比数据增强说服力", "标注数据时效性"], "enhancement_rules": ["检查数据点完整性", "建议补充缺失的关键数据"]}'::jsonb,
     ARRAY['trustworthy', 'answerability'], ARRAY['verifiability', 'information_presentation'], NULL, 'llm_with_postprocess', true),

    ('热点关联', '将内容与当前热点话题关联，提升时效性',
     '{"instruction": "在内容中自然关联当前热点事件和趋势", "format": {"structure": "热点引入→品牌关联→核心内容"}, "tone": "紧跟时事、有洞察", "constraints": ["热点必须与品牌/产品有自然关联", "避免强行蹭热点", "注明时间背景"], "enhancement_rules": ["标注内容时效性提醒"]}'::jsonb,
     ARRAY['freshness'], ARRAY['trending_relevance'], NULL, 'llm_with_postprocess', true),

    ('平台适配-Reddit', '针对Reddit平台特点优化内容格式和语调',
     '{"instruction": "以Reddit社区用户视角撰写，强调个人体验和真实评价", "format": {"structure": "故事开头→体验分享→对比总结", "word_count": "300-800字"}, "tone": "口语化、真实、社区感", "constraints": ["使用第一人称", "包含具体使用场景", "加入upvote-friendly的对比表格"], "enhancement_rules": ["检查Reddit格式规范", "优化标题吸引力"]}'::jsonb,
     ARRAY['answerability'], ARRAY['platform_fit'], 'platform_post', 'llm_with_postprocess', true),

    ('平台适配-官网', '针对品牌官网内容特点优化结构和SEO',
     '{"instruction": "以品牌官方视角撰写，专业严谨，含structured data", "format": {"structure": "H1→H2→H3层级清晰", "schema_markup": "Article + Product", "word_count": "800-1500字"}, "tone": "专业、品牌调性一致", "constraints": ["符合品牌voice guidelines", "包含内链建议", "SEO标题优化"], "enhancement_rules": ["自动注入schema markup", "生成meta description", "添加canonical URL建议"]}'::jsonb,
     ARRAY['readability', 'answerability'], ARRAY['machine_readability', 'platform_fit'], 'aeo_article', 'llm_with_postprocess', true),

    ('竞品差异化', '在内容中自然融入品牌与竞品的差异化优势',
     '{"instruction": "通过客观对比突出品牌独特优势，避免直接贬低竞品", "format": {"structure": "需求场景→多品牌对比→推荐结论"}, "tone": "客观、有理有据", "constraints": ["对比维度至少3个", "数据来源必须标注", "结论要有说服力"], "enhancement_rules": ["检查竞品信息准确性", "优化对比表格可读性"]}'::jsonb,
     ARRAY['answerability', 'trustworthy'], ARRAY['information_presentation', 'authority_eeat'], 'comparison', 'llm_with_postprocess', true);

COMMIT;
```

- [ ] **Step 2: Verify migration syntax**

Run: `psql -f migrations/023_content_redesign_framework.sql --echo-errors` (or provide to user for review)
Expected: All statements execute without errors

- [ ] **Step 3: Commit**

```bash
git add migrations/023_content_redesign_framework.sql
git commit -m "feat: add three-layer framework DDL + sentiment template + content assets"
```

---

## Task 2: Backend — Framework Data API Endpoints

**Files:**
- Modify: `geo_agent/src/routers/tasks.py`

Add endpoints for the frontend to fetch Metrics, Sub-goals, and completed opportunity analysis tasks.

- [ ] **Step 1: Add framework data endpoints to tasks.py**

Add these endpoints after the existing template endpoints:

```python
# ─── Framework Data Endpoints ────────────────────────────────────────

@router.get("/framework/metrics")
async def list_metrics():
    """Return all active optimization metrics (Layer 1)."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, name_zh, name_en, description, icon, sort_order
           FROM geo_optimization_metrics
           WHERE is_active = true
           ORDER BY sort_order"""
    )
    return [dict(r) for r in rows]


@router.get("/framework/subgoals")
async def list_subgoals(metric_id: Optional[str] = None):
    """Return active sub-goals (Layer 2), optionally filtered by metric."""
    pool = await get_pool()
    if metric_id:
        rows = await pool.fetch(
            """SELECT id, metric_id, name_zh, name_en, description, sort_order
               FROM geo_optimization_subgoals
               WHERE is_active = true AND metric_id = $1
               ORDER BY sort_order""",
            metric_id,
        )
    else:
        rows = await pool.fetch(
            """SELECT id, metric_id, name_zh, name_en, description, sort_order
               FROM geo_optimization_subgoals
               WHERE is_active = true
               ORDER BY metric_id, sort_order"""
        )
    return [dict(r) for r in rows]


@router.get("/framework/opportunity-tasks")
async def list_opportunity_tasks(client_id: str):
    """List completed opportunity discovery analysis tasks for a client.
    Used by Content Node 0 to import Analyzer results."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT t.id, t.task_name, t.completed_at, t.output,
                  t.inputs->>'topic' AS topic_scope
           FROM geo_agent_tasks t
           WHERE t.client_id = $1::uuid
             AND t.task_type = 'opportunity_discovery'
             AND t.status = 'COMPLETED'
           ORDER BY t.completed_at DESC
           LIMIT 20""",
        client_id,
    )
    results = []
    for r in rows:
        output = r["output"] if r["output"] else {}
        if isinstance(output, str):
            import json
            output = json.loads(output)
        results.append({
            "id": str(r["id"]),
            "task_name": r["task_name"],
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "topic_scope": r["topic_scope"],
            "summary": {
                "topic_count": len(output.get("topic_quadrants", [])),
                "opportunity_count": len(output.get("content_opportunities", [])),
                "platform_count": len(output.get("platform_recommendations", [])),
            },
        })
    return results
```

- [ ] **Step 2: Add `opportunity_discovery` task type to workflow steps**

Add after the existing ANALYSIS_WORKFLOW_STEPS:

```python
OPPORTUNITY_WORKFLOW_STEPS = [
    {"step": 1, "name": "topic_quadrant", "label": "Topic 四象限定位", "status": "pending"},
    {"step": 2, "name": "content_opportunities", "label": "选题机会挖掘", "status": "pending"},
    {"step": 3, "name": "platform_analysis", "label": "平台引用关系分析", "status": "pending"},
    {"step": 4, "name": "synthesize_output", "label": "综合输出", "status": "pending"},
]

CONTENT_V2_WORKFLOW_STEPS = [
    {"step": 1, "name": "strategy_generation", "label": "策略生成", "status": "pending"},
    {"step": 2, "name": "content_generation", "label": "内容生成", "status": "pending"},
    {"step": 3, "name": "quality_review", "label": "质量评审", "status": "pending"},
]
```

Update `_get_workflow_steps`:

```python
def _get_workflow_steps(task_type: str) -> list[dict]:
    if task_type == "content_generation":
        return [dict(s) for s in CONTENT_V2_WORKFLOW_STEPS]
    elif task_type == "analysis":
        return [dict(s) for s in ANALYSIS_WORKFLOW_STEPS]
    elif task_type == "opportunity_discovery":
        return [dict(s) for s in OPPORTUNITY_WORKFLOW_STEPS]
    return []
```

- [ ] **Step 3: Verify endpoints respond**

Run: `curl http://localhost:8001/api/agent/tasks/framework/metrics`
Expected: JSON array of 4 metrics

- [ ] **Step 4: Commit**

```bash
git add geo_agent/src/routers/tasks.py
git commit -m "feat: add framework data API + opportunity_discovery task type"
```

---

## Task 3: Backend — "优化机会发现" Upgraded Pipeline

**Files:**
- Create: `geo_agent/src/pipelines/opportunity_pipeline.py`
- Modify: `geo_agent/src/pipelines/analysis_pipeline.py` (add ALLOWED_TABLES for new queries)

This is the core Analyzer upgrade. The pipeline has 4 steps that produce structured JSON output (topic_quadrants, content_opportunities, platform_recommendations).

- [ ] **Step 1: Create opportunity_pipeline.py**

```python
"""
Opportunity Discovery Pipeline — upgraded 4-step workflow.

Steps:
  1. Topic 四象限定位 — Classify each Topic into quadrants (强势/薄弱/待挖掘/新兴)
  2. 选题机会挖掘     — Discover content angles with opportunity scores
  3. 平台引用关系分析  — Analyze platform-engine citation relationships
  4. 综合输出         — Synthesize structured JSON + markdown report

Output: structured JSON with topic_quadrants, content_opportunities, platform_recommendations
plus an insights_markdown for display.
"""
import json
import logging
import asyncio
from typing import Any
from datetime import datetime, timezone

from google.genai import types

from llm.client import get_genai_client, get_model_id
from pipelines.base import WorkflowStep, run_pipeline, append_status_log
from database import get_pool
from routers.tasks import register_pipeline

logger = logging.getLogger(__name__)


# ─── LLM helper ─────────────────────────────────────────────────────

async def _llm_json(client, model_id: str, prompt: str, label: str = "llm") -> dict:
    """Call Gemini and parse JSON from response. Retries up to 3 times."""
    for attempt in range(1, 4):
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as e:
            logger.warning(f"[OPPORTUNITY] {label} attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    raise RuntimeError(f"{label} failed after 3 attempts")


async def _llm_text(client, model_id: str, prompt: str, label: str = "llm") -> str:
    """Call Gemini and return text. Retries up to 3 times."""
    for attempt in range(1, 4):
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
            )
            return response.text or ""
        except Exception as e:
            logger.warning(f"[OPPORTUNITY] {label} attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    raise RuntimeError(f"{label} failed after 3 attempts")


# ─── Step 1: Topic Quadrant Classification ───────────────────────────

async def step_topic_quadrant(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Classify each Topic into quadrants based on visibility, citation, and trend data."""
    await append_status_log(pool, task_id, {"step": 1, "event": "detail", "label": "正在查询 Topic 数据..."})

    # Fetch all active topics for client
    topics = await pool.fetch(
        """SELECT ct.id, ct.name, ct.product
           FROM geo_client_topics ct
           WHERE ct.client_id = $1::uuid AND ct.is_active = true""",
        client_id,
    )
    if not topics:
        return {"topic_quadrants": [], "_topic_data": {}}

    # For each topic, compute: own brand visibility, competitor citations, trend
    topic_data = {}
    for t in topics:
        topic_name = t["name"]

        # Own brand mention rate
        own_mentions = await pool.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE cm.is_own_brand = true) AS own_count,
                 COUNT(*) AS total_prompts,
                 AVG(cm.mention_position) FILTER (WHERE cm.is_own_brand = true) AS avg_pos
               FROM geo_client_prompts cp
               LEFT JOIN geo_company_mentions cm ON cm.client_prompt_id = cp.id
               WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid AND cp.is_active = true""",
            client_id, t["id"],
        )

        # Competitor citation rate
        competitor_cites = await pool.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE gcd.is_own = false) AS competitor_cite_count,
                 COUNT(*) FILTER (WHERE gcd.is_own = true) AS own_cite_count,
                 COUNT(*) AS total_citations
               FROM geo_citations gc
               JOIN geo_client_prompts cp ON gc.client_prompt_id = cp.id
               LEFT JOIN geo_client_domains gcd ON gc.source_domain = gcd.domain AND gcd.client_id = cp.client_id
               WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid""",
            client_id, t["id"],
        )

        # Trend: compare recent 2 weeks vs prior 2 weeks
        trend_data = await pool.fetchrow(
            """WITH recent AS (
                 SELECT COUNT(*) AS cnt FROM geo_results gr
                 JOIN geo_client_prompts cp ON gr.client_prompt_id = cp.id
                 WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid
                   AND gr.ingested_at >= NOW() - INTERVAL '14 days'
               ), prior AS (
                 SELECT COUNT(*) AS cnt FROM geo_results gr
                 JOIN geo_client_prompts cp ON gr.client_prompt_id = cp.id
                 WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid
                   AND gr.ingested_at >= NOW() - INTERVAL '28 days'
                   AND gr.ingested_at < NOW() - INTERVAL '14 days'
               )
               SELECT recent.cnt AS recent_cnt, prior.cnt AS prior_cnt
               FROM recent, prior""",
            client_id, t["id"],
        )

        own_count = own_mentions["own_count"] or 0 if own_mentions else 0
        total_prompts = own_mentions["total_prompts"] or 0 if own_mentions else 0
        comp_cite = competitor_cites["competitor_cite_count"] or 0 if competitor_cites else 0
        own_cite = competitor_cites["own_cite_count"] or 0 if competitor_cites else 0
        recent_cnt = trend_data["recent_cnt"] or 0 if trend_data else 0
        prior_cnt = trend_data["prior_cnt"] or 0 if trend_data else 0

        has_content = own_count > 0
        ai_cites_brand = own_cite > 0
        trend_rising = recent_cnt > prior_cnt * 1.2 if prior_cnt > 0 else recent_cnt > 5

        # Decision tree for primary quadrant
        if trend_rising:
            primary = "新兴"
            action = "抢占"
        elif has_content and ai_cites_brand:
            primary = "强势"
            action = "维护"
        elif has_content and not ai_cites_brand:
            primary = "薄弱"
            action = "修复"
        else:
            primary = "待挖掘"
            action = "进攻"

        # Optional secondary tag
        secondary = None
        if primary != "新兴" and trend_rising:
            secondary = "新兴"
        elif primary == "待挖掘" and trend_rising:
            secondary = "趋势上升"

        visibility_score = round(own_count / total_prompts, 2) if total_prompts > 0 else 0
        total_cites = (competitor_cites["total_citations"] or 0) if competitor_cites else 0
        citation_rate = round(own_cite / total_cites, 2) if total_cites > 0 else 0
        comp_citation_rate = round(comp_cite / total_cites, 2) if total_cites > 0 else 0

        topic_data[topic_name] = {
            "topic": topic_name,
            "product": t["product"] or "",
            "topic_id": str(t["id"]),
            "primary_quadrant": primary,
            "secondary_quadrant": secondary,
            "action": action,
            "metrics": {
                "visibility_score": visibility_score,
                "citation_rate": citation_rate,
                "competitor_citation_rate": comp_citation_rate,
                "trend_direction": "rising" if trend_rising else "stable",
                "own_mention_count": own_count,
                "total_prompts": total_prompts,
            },
        }

    quadrants = list(topic_data.values())
    await append_status_log(pool, task_id, {
        "step": 1, "event": "detail",
        "label": f"已分析 {len(quadrants)} 个 Topic 的四象限定位",
    })

    return {"topic_quadrants": quadrants, "_topic_data": topic_data}


# ─── Step 2: Content Opportunity Discovery ───────────────────────────

async def step_content_opportunities(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Use LLM to discover content angles based on quadrant data and citation analysis."""
    topic_quadrants = inputs.get("topic_quadrants", [])
    if not topic_quadrants:
        return {"content_opportunities": []}

    await append_status_log(pool, task_id, {"step": 2, "event": "detail", "label": "正在分析引用内容，挖掘选题机会..."})

    # Gather citation data for actionable topics (not 强势)
    actionable = [t for t in topic_quadrants if t["primary_quadrant"] != "强势"]
    if not actionable:
        actionable = topic_quadrants[:3]  # fallback: analyze top 3

    citation_context = []
    for t in actionable:
        topic_id = t.get("topic_id", "")
        if not topic_id:
            continue
        # Get competitor cited URLs and content
        comp_cites = await pool.fetch(
            """SELECT gc.source_url, gc.source_domain, gc.source_label, gc.domain_category,
                      cp.text AS prompt_text
               FROM geo_citations gc
               JOIN geo_client_prompts cp ON gc.client_prompt_id = cp.id
               LEFT JOIN geo_client_domains gcd ON gc.source_domain = gcd.domain AND gcd.client_id = cp.client_id
               WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid
                 AND (gcd.is_own IS NULL OR gcd.is_own = false)
               ORDER BY gc.source_position ASC
               LIMIT 20""",
            client_id, topic_id,
        )
        citation_context.append({
            "topic": t["topic"],
            "quadrant": t["primary_quadrant"],
            "action": t["action"],
            "competitor_citations": [
                {"url": r["source_url"], "domain": r["source_domain"],
                 "label": r["source_label"], "category": r["domain_category"],
                 "prompt": r["prompt_text"]}
                for r in comp_cites
            ],
        })

    # Also gather prompts related to these topics for linking
    prompt_map = {}
    for t in actionable:
        topic_id = t.get("topic_id", "")
        if not topic_id:
            continue
        prompts = await pool.fetch(
            """SELECT id, text, platform, intent
               FROM geo_client_prompts
               WHERE client_id = $1::uuid AND topic_id = $2::uuid AND is_active = true
               LIMIT 30""",
            client_id, topic_id,
        )
        prompt_map[t["topic"]] = [{"id": str(p["id"]), "text": p["text"], "platform": p["platform"]} for p in prompts]

    # Brand profile for context
    bp_row = await pool.fetchrow(
        "SELECT brand_name, target_audience, key_messages FROM geo_brand_profiles WHERE client_id = $1::uuid",
        client_id,
    )
    brand_name = bp_row["brand_name"] if bp_row else "品牌"

    # LLM call to discover content opportunities
    client_llm = get_genai_client()
    model_id = get_model_id("pro")

    prompt = f"""你是 GEO（Generative Engine Optimization）内容策略专家。
基于以下品牌 "{brand_name}" 的 Topic 四象限诊断和竞品引用数据，挖掘具体的内容选题机会。

## Topic 四象限诊断

{json.dumps(topic_quadrants, ensure_ascii=False, indent=2)}

## 竞品引用数据

{json.dumps(citation_context, ensure_ascii=False, indent=2)}

## 任务

对每个可行动的 Topic（非"强势"的 Topic），产出 2-3 个内容选题机会。每个选题机会包含：
1. angle: 推荐的内容切入角度（一句话标题）
2. opportunity_score: 机会评分 1-10（搜索量 × 品牌覆盖缺口）
3. competitor_refs: 竞品在这个角度的引用参考（1-2句话描述）
4. recommended_metrics: 推荐优化的 metrics（从 readability/answerability/trustworthy/freshness 中选）
5. recommended_subgoals: 推荐的 sub-goals（从 content_understandability/machine_readability/information_presentation/audience_fit/platform_fit/authority_eeat/verifiability/trending_relevance/publish_timeliness 中选）
6. source_quadrant: 来自哪个象限

输出 JSON 数组，每个元素包含上述字段和 topic（Topic 名称）。按 opportunity_score 降序排列。"""

    opportunities_raw = await _llm_json(client_llm, model_id, prompt, "content_opportunities")

    # Attach related_prompts from DB data
    opportunities = opportunities_raw if isinstance(opportunities_raw, list) else opportunities_raw.get("opportunities", [])
    for opp in opportunities:
        topic = opp.get("topic", "")
        related = prompt_map.get(topic, [])
        opp["related_prompts"] = [p["id"] for p in related[:10]]

    await append_status_log(pool, task_id, {
        "step": 2, "event": "detail",
        "label": f"已发现 {len(opportunities)} 个内容选题机会",
    })

    return {"content_opportunities": opportunities}


# ─── Step 3: Platform-Engine Citation Analysis ───────────────────────

async def step_platform_analysis(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Analyze which publishing platforms get cited by which AI engines."""
    await append_status_log(pool, task_id, {"step": 3, "event": "detail", "label": "正在分析平台-AI引擎引用关系..."})

    # Aggregate citation data by domain_category × platform
    rows = await pool.fetch(
        """SELECT
             COALESCE(gc.domain_category, '其他') AS platform_type,
             gr.platform AS ai_engine,
             COUNT(*) AS cite_count
           FROM geo_citations gc
           JOIN geo_client_prompts cp ON gc.client_prompt_id = cp.id
           JOIN geo_results gr ON gc.result_id = gr.result_id
           WHERE cp.client_id = $1::uuid
           GROUP BY COALESCE(gc.domain_category, '其他'), gr.platform
           ORDER BY cite_count DESC""",
        client_id,
    )

    if not rows:
        return {"platform_recommendations": []}

    # Build platform × engine matrix
    from collections import defaultdict
    platform_engine = defaultdict(lambda: defaultdict(int))
    platform_total = defaultdict(int)
    engine_total = defaultdict(int)

    for r in rows:
        pt = r["platform_type"]
        engine = r["ai_engine"]
        cnt = r["cite_count"]
        platform_engine[pt][engine] += cnt
        platform_total[pt] += cnt
        engine_total[engine] += cnt

    grand_total = sum(platform_total.values()) or 1

    recommendations = []
    for pt in sorted(platform_total.keys(), key=lambda k: platform_total[k], reverse=True):
        engines_sorted = sorted(platform_engine[pt].items(), key=lambda x: x[1], reverse=True)
        top_engines = [e[0] for e in engines_sorted[:3]]
        citation_share = round(platform_total[pt] / grand_total, 2)
        priority = "high" if citation_share >= 0.2 else ("medium" if citation_share >= 0.1 else "low")
        recommendations.append({
            "platform_type": pt,
            "engines": top_engines,
            "citation_share": citation_share,
            "priority": priority,
            "engine_breakdown": {e: c for e, c in engines_sorted},
        })

    await append_status_log(pool, task_id, {
        "step": 3, "event": "detail",
        "label": f"已分析 {len(recommendations)} 个发布平台的引用关系",
    })

    return {"platform_recommendations": recommendations}


# ─── Step 4: Synthesize Output ───────────────────────────────────────

async def step_synthesize_output(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Generate markdown report + combine structured JSON output."""
    topic_quadrants = inputs.get("topic_quadrants", [])
    content_opportunities = inputs.get("content_opportunities", [])
    platform_recommendations = inputs.get("platform_recommendations", [])

    await append_status_log(pool, task_id, {"step": 4, "event": "detail", "label": "正在生成综合分析报告..."})

    # Brand name
    bp_row = await pool.fetchrow(
        "SELECT brand_name FROM geo_brand_profiles WHERE client_id = $1::uuid", client_id,
    )
    brand_name = bp_row["brand_name"] if bp_row else "品牌"

    # LLM: generate insights markdown
    client_llm = get_genai_client()
    model_id = get_model_id("pro")

    prompt = f"""你是 GEO 分析报告撰写专家。基于以下结构化分析数据，为品牌 "{brand_name}" 生成一份优化机会分析报告。

## Topic 四象限诊断
{json.dumps(topic_quadrants, ensure_ascii=False, indent=2)}

## 选题机会
{json.dumps(content_opportunities, ensure_ascii=False, indent=2)}

## 平台引用关系
{json.dumps(platform_recommendations, ensure_ascii=False, indent=2)}

## 报告要求
1. 用 Markdown 格式输出
2. 包含四象限诊断总结（每个象限有多少 Topic，重点关注哪些）
3. 选题机会优先级排序和行动建议
4. 平台分发策略建议
5. 语言：简洁商业风格，数据驱动
6. 在报告末尾添加一句引导语：「点击下方按钮，基于本次分析结果直接进入内容生成」"""

    insights_md = await _llm_text(client_llm, model_id, prompt, "synthesize_report")

    # Build final structured output
    output = {
        "analysis_task_id": task_id,
        "client_id": client_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic_quadrants": topic_quadrants,
        "content_opportunities": content_opportunities,
        "platform_recommendations": platform_recommendations,
        "insights_markdown": insights_md,
        "model_used": model_id,
    }

    return {"_output": output, "model_used": model_id}


# ─── Pipeline Registration ───────────────────────────────────────────

OPPORTUNITY_STEPS = [
    WorkflowStep(1, "topic_quadrant", "Topic 四象限定位", step_topic_quadrant),
    WorkflowStep(2, "content_opportunities", "选题机会挖掘", step_content_opportunities),
    WorkflowStep(3, "platform_analysis", "平台引用关系分析", step_platform_analysis),
    WorkflowStep(4, "synthesize_output", "综合输出", step_synthesize_output),
]


async def run_opportunity_pipeline(task_id: str, inputs: dict, client_id: str):
    await run_pipeline(task_id, OPPORTUNITY_STEPS, inputs, client_id)


register_pipeline("opportunity_discovery", run_opportunity_pipeline)
```

- [ ] **Step 2: Import the new pipeline in geo_agent/src/main.py**

Find the existing pipeline imports and add:

```python
import pipelines.opportunity_pipeline  # noqa: F401 — registers pipeline
```

- [ ] **Step 3: Verify pipeline registers**

Run the geo_agent service and check logs for: `[TASKS] Registered pipeline: opportunity_discovery`

- [ ] **Step 4: Commit**

```bash
git add geo_agent/src/pipelines/opportunity_pipeline.py geo_agent/src/main.py
git commit -m "feat: add opportunity discovery 4-step pipeline"
```

---

## Task 4: Backend — Redesigned Content Pipeline (Strategy-Driven)

**Files:**
- Modify: `geo_agent/src/pipelines/content_pipeline.py`

The new pipeline takes structured inputs from the 7-node frontend wizard (selected metrics, sub-goals, content type, strategy JSON, analyzer context, prompts) and runs 3 backend steps: strategy generation → content generation → quality review.

- [ ] **Step 1: Rewrite content_pipeline.py**

Replace the existing 5-step pipeline with the new 3-step strategy-driven pipeline:

```python
"""
Content Generation Pipeline v2 — strategy-driven 3-step workflow.

Steps:
  1. 策略生成 (Strategy Generation) — Generate structured strategy from user selections + analyzer context
  2. 内容生成 (Content Generation)   — Generate content using strategy + brand profile
  3. 质量评审 (Quality Review)       — Score content against selected Metrics/Sub-goals

Inputs come from the 7-node frontend wizard:
  - selected_metrics, selected_subgoals (from Node 1)
  - content_type (from Node 2)
  - analyzer_context (from Node 0, optional)
  - ai_platforms, publish_platform, language, count, product_facts (from Node 4)
  - target_prompt_ids (from Node 5)
  - user_strategy_edits (from Node 3, optional user tweaks)
"""
import asyncio
import json
import logging
from typing import Any

from google.genai import types

from llm.client import get_genai_client, get_model_id
from tools.content_tools import _build_brand_context, FAQ_SYSTEM_PROMPT
from pipelines.base import WorkflowStep, run_pipeline, append_status_log
from database import get_pool
from routers.tasks import register_pipeline

logger = logging.getLogger(__name__)

_LLM_RETRIES = 3


async def _llm_generate(client, model_id: str, contents: str, config, label: str = "llm") -> str:
    """Call Gemini with retry. Returns raw text."""
    last_err = None
    for attempt in range(1, _LLM_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=contents, config=config,
            )
            return response.text or ""
        except Exception as e:
            last_err = str(e) or f"{type(e).__name__}: {repr(e)}"
            logger.warning(f"[CONTENT-V2] {label} error attempt {attempt}/{_LLM_RETRIES}: {last_err}")
            if attempt < _LLM_RETRIES:
                await asyncio.sleep(2)
    raise RuntimeError(f"{label} failed after {_LLM_RETRIES} attempts: {last_err}")


async def _llm_json(client, model_id: str, prompt: str, label: str = "llm") -> dict:
    """Call Gemini and parse JSON response."""
    for attempt in range(1, 4):
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2, max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as e:
            logger.warning(f"[CONTENT-V2] {label} attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    raise RuntimeError(f"{label} failed after 3 attempts")


# ─── Step 1: Strategy Generation ─────────────────────────────────────

async def step_strategy_generation(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Generate strategy combination from user selections + analyzer context."""
    selected_metrics = inputs.get("selected_metrics", [])
    selected_subgoals = inputs.get("selected_subgoals", [])
    content_type = inputs.get("content_type", "faq")
    analyzer_context = inputs.get("analyzer_context")  # from Node 0 import
    user_strategy_edits = inputs.get("user_strategy_edits")  # from Node 3 tweaks

    await append_status_log(pool, task_id, {"step": 1, "event": "detail", "label": "正在加载品牌信息..."})

    # Load brand profile
    bp_row = await pool.fetchrow(
        """SELECT brand_name, tone_of_voice, target_audience,
                  key_messages, brand_values, language
           FROM geo_brand_profiles WHERE client_id = $1::uuid""",
        client_id,
    )
    brand_context = dict(bp_row) if bp_row else {}

    # Load sub-goal descriptions for prompt
    sg_rows = await pool.fetch(
        """SELECT sg.id, sg.name_zh, sg.description, m.name_zh AS metric_name
           FROM geo_optimization_subgoals sg
           JOIN geo_optimization_metrics m ON sg.metric_id = m.id
           WHERE sg.id = ANY($1::text[])""",
        selected_subgoals,
    )
    subgoal_descriptions = [
        f"- {r['metric_name']} > {r['name_zh']}: {r['description']}" for r in sg_rows
    ]

    # Build analyzer context snippet
    analyzer_snippet = ""
    if analyzer_context:
        quadrants = analyzer_context.get("topic_quadrants", [])
        opportunities = analyzer_context.get("content_opportunities", [])
        platforms = analyzer_context.get("platform_recommendations", [])
        analyzer_snippet = f"""
## Analyzer 上下文（来自优化机会发现）

### Topic 四象限诊断
{json.dumps(quadrants[:5], ensure_ascii=False, indent=2)}

### 选题机会
{json.dumps(opportunities[:5], ensure_ascii=False, indent=2)}

### 平台推荐
{json.dumps(platforms[:5], ensure_ascii=False, indent=2)}
"""

    await append_status_log(pool, task_id, {"step": 1, "event": "detail", "label": "正在生成内容策略..."})

    # LLM generates strategy
    client_llm = get_genai_client()
    model_id = get_model_id("pro")

    prompt = f"""你是 GEO 内容策略专家。请基于以下输入，生成一组内容策略组合。

## 用户选择
- 内容类型: {content_type}
- 优化 Metrics: {', '.join(selected_metrics)}
- 优化 Sub-goals:
{chr(10).join(subgoal_descriptions)}

## 品牌画像
{json.dumps(brand_context, ensure_ascii=False, indent=2)}

{analyzer_snippet}

{f"## 用户策略调整{chr(10)}{user_strategy_edits}" if user_strategy_edits else ""}

## 输出要求

输出 JSON 对象，包含以下字段：
{{
  "strategies": [
    {{
      "name": "策略名称",
      "description": "一句话描述",
      "dimensions": {{
        "instruction": "内容目标和范围描述",
        "format": {{
          "structure": "内容结构要求",
          "schema_markup": "推荐的 schema 类型",
          "word_count": "字数要求"
        }},
        "tone": "写作调性",
        "constraints": ["约束1", "约束2"],
        "enhancement_rules": ["增强规则1", "增强规则2"]
      }},
      "source_metrics": ["metric_id"],
      "source_subgoals": ["subgoal_id"]
    }}
  ],
  "strategy_summary": "用自然语言概述策略组合（给用户确认用）"
}}

生成 2-4 个互补策略，覆盖用户选择的所有 Sub-goals。"""

    strategy_result = await _llm_json(client_llm, model_id, prompt, "strategy_generation")

    return {
        "strategy": strategy_result,
        "brand_context": brand_context,
        "model_used": model_id,
    }


# ─── Step 2: Content Generation ──────────────────────────────────────

async def step_content_generation(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Generate content using strategy + brand profile + prompt targets."""
    strategy = inputs.get("strategy", {})
    brand_context = inputs.get("brand_context", {})
    content_type = inputs.get("content_type", "faq")
    language = inputs.get("language", "zh-CN")
    count = inputs.get("count", 5)
    publish_platform = inputs.get("publish_platform", "official_site")
    product_facts = inputs.get("product_facts", {})
    target_prompt_ids = inputs.get("target_prompt_ids", [])
    analyzer_context = inputs.get("analyzer_context")

    await append_status_log(pool, task_id, {"step": 2, "event": "detail", "label": "正在加载目标 Prompts..."})

    # Load target prompts
    prompt_texts = []
    if target_prompt_ids:
        rows = await pool.fetch(
            """SELECT text, platform, intent FROM geo_client_prompts
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            target_prompt_ids, client_id,
        )
        prompt_texts = [{"text": r["text"], "platform": r["platform"], "intent": r["intent"]} for r in rows]

    # Build brand context string
    brand_str = _build_brand_context(brand_context) if brand_context else ""

    # Compose generation prompt
    strategies_json = json.dumps(strategy.get("strategies", []), ensure_ascii=False, indent=2)
    strategy_summary = strategy.get("strategy_summary", "")

    content_type_labels = {
        "faq": "FAQ 问答内容",
        "aeo_article": "AEO 优化文章（800-1200字）",
        "article": "SEO 文章",
        "brief": "Content Brief（内容大纲）",
        "comparison": "产品对比/测评文",
        "platform_post": "平台定制帖",
        "howto": "How-to 教程",
        "listicle": "Listicle 列表文章",
        "recommendations": "优化建议报告",
    }

    await append_status_log(pool, task_id, {"step": 2, "event": "detail", "label": f"正在生成 {content_type_labels.get(content_type, content_type)}..."})

    client_llm = get_genai_client()
    model_id = get_model_id("pro")

    opp_context = ""
    if analyzer_context:
        opps = analyzer_context.get("content_opportunities", [])
        if opps:
            opp_context = f"\n## 选题机会参考\n{json.dumps(opps[:3], ensure_ascii=False, indent=2)}"

    # Extract strategy dimensions for explicit injection
    strategies_list = strategy.get("strategies", [])
    dimension_instructions = []
    all_constraints = []
    all_enhancements = []
    for s in strategies_list:
        dims = s.get("dimensions", {})
        dimension_instructions.append(f"### 策略: {s.get('name', '')}\n- 指导: {dims.get('instruction', '')}\n- 格式: {json.dumps(dims.get('format', {}), ensure_ascii=False)}\n- 调性: {dims.get('tone', '')}")
        all_constraints.extend(dims.get("constraints", []))
        all_enhancements.extend(dims.get("enhancement_rules", []))

    # Content Brief produces structured outline, not full article
    is_brief = content_type == "brief"
    output_instruction = (
        "输出详细的内容大纲（Content Brief），包含：\n"
        "1. 内容目标和受众定位\n"
        "2. 章节结构（H2/H3 层级）及每节要点\n"
        "3. 每节推荐的关键数据点和引用来源\n"
        "4. 目标关键词列表\n"
        "5. 竞品差异化要点\n"
        "6. RAFT 评分目标\n"
        "注意：这是大纲，不是完整文章。"
    ) if is_brief else (
        f"{'生成 ' + str(count) + ' 条' if content_type == 'faq' else '���成完整文章'}\n"
        "输�� Markdown 格式的可发布内容。"
    )

    prompt = f"""你是一位专业的 GEO 内容创作者。请严格按照以下策略维度生成内���。

## 内容类型
{content_type_labels.get(content_type, content_type)}

## 策略维度（必须遵循每条策略的 5 个维度）

{chr(10).join(dimension_instructions)}

## 硬性约束（Constraints）— 所有策略的约束合集
{chr(10).join(f"- {c}" for c in all_constraints) if all_constraints else "无特殊约束"}

## 后处理增强规则（Enhancement Rules）— 生成后自检
{chr(10).join(f"- {e}" for e in all_enhancements) if all_enhancements else "无特殊规则"}

## 品牌信息
{brand_str}

## 产品核���事实
{json.dumps(product_facts, ensure_ascii=False) if product_facts else "未提供"}

## 目��� AI 搜索 Prompts
{json.dumps(prompt_texts, ensure_ascii=False, indent=2) if prompt_texts else "未指定"}

## 发布平台
{publish_platform}

## 语言
{language}
{opp_context}

## 输出要求
{output_instruction}"""

    config = types.GenerateContentConfig(
        temperature=0.4,
        max_output_tokens=16384,
    )

    generated_content = await _llm_generate(client_llm, model_id, prompt, config, "content_generation")

    return {"generated_content": generated_content}


# ─── Step 3: Quality Review ──────────────────────────────────────────

async def step_quality_review(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Score generated content against selected Metrics/Sub-goals."""
    generated_content = inputs.get("generated_content", "")
    selected_metrics = inputs.get("selected_metrics", [])
    selected_subgoals = inputs.get("selected_subgoals", [])
    strategy = inputs.get("strategy", {})

    await append_status_log(pool, task_id, {"step": 3, "event": "detail", "label": "正在评审内容质量..."})

    # Load sub-goal definitions
    sg_rows = await pool.fetch(
        """SELECT sg.id, sg.name_zh, sg.description, m.id AS metric_id, m.name_zh AS metric_name
           FROM geo_optimization_subgoals sg
           JOIN geo_optimization_metrics m ON sg.metric_id = m.id
           WHERE sg.id = ANY($1::text[])""",
        selected_subgoals,
    )
    scoring_criteria = [
        f"- {r['metric_name']} > {r['name_zh']}: {r['description']}" for r in sg_rows
    ]

    client_llm = get_genai_client()
    model_id = get_model_id("pro")

    prompt = f"""你是 GEO 内容质量评审专家。请对以下生成内容进行评分和评审。

## 评分维度（每个 Sub-goal 打 1-10 分）
{chr(10).join(scoring_criteria)}

## 生成的内容
{generated_content[:8000]}

## 输出要求（JSON）
{{
  "scores": [
    {{
      "subgoal_id": "xxx",
      "subgoal_name": "xxx",
      "metric_name": "xxx",
      "score": 8,
      "comment": "评语"
    }}
  ],
  "overall_score": 7.5,
  "improvement_suggestions": ["建议1", "建议2"],
  "summary": "一段话总结"
}}"""

    review_result = await _llm_json(client_llm, model_id, prompt, "quality_review")

    # Build final output
    output = {
        "content": generated_content,
        "content_type": inputs.get("content_type"),
        "strategy": strategy,
        "quality_review": review_result,
        "selected_metrics": selected_metrics,
        "selected_subgoals": selected_subgoals,
        "model_used": model_id,
    }

    return {"_output": output, "model_used": model_id}


# ─── Pipeline Registration ───────────────────────────────────────────

CONTENT_V2_STEPS = [
    WorkflowStep(1, "strategy_generation", "策略生成", step_strategy_generation),
    WorkflowStep(2, "content_generation", "内容生成", step_content_generation),
    WorkflowStep(3, "quality_review", "质量评审", step_quality_review),
]


async def run_content_v2_pipeline(task_id: str, inputs: dict, client_id: str):
    await run_pipeline(task_id, CONTENT_V2_STEPS, inputs, client_id)


# Override the existing content_generation registration
register_pipeline("content_generation", run_content_v2_pipeline)
```

- [ ] **Step 2: Verify pipeline compiles**

Run: `python -c "import pipelines.content_pipeline"` from `geo_agent/src/`
Expected: No import errors

- [ ] **Step 3: Commit**

```bash
git add geo_agent/src/pipelines/content_pipeline.py
git commit -m "feat: rewrite content pipeline with strategy-driven 3-step workflow"
```

---

## Task 5: Frontend — API Client Functions

**Files:**
- Modify: `geo_saas/web/src/lib/api.ts`

Add API functions for framework data, opportunity tasks, and new content pipeline.

- [ ] **Step 1: Add framework API functions**

Add to the end of `api.ts`:

```typescript
// ─── Three-Layer Framework APIs ─────────────────────────────────────

export interface OptimizationMetric {
  id: string;
  name_zh: string;
  name_en: string;
  description: string;
  icon: string;
  sort_order: number;
}

export interface OptimizationSubgoal {
  id: string;
  metric_id: string;
  name_zh: string;
  name_en: string;
  description: string;
  sort_order: number;
}

export interface OpportunityTaskSummary {
  id: string;
  task_name: string;
  completed_at: string | null;
  topic_scope: string | null;
  summary: {
    topic_count: number;
    opportunity_count: number;
    platform_count: number;
  };
}

export async function getOptimizationMetrics(): Promise<OptimizationMetric[]> {
  return fetchJSON(`${AGENT_API_BASE}/api/agent/tasks/framework/metrics`);
}

export async function getOptimizationSubgoals(metricId?: string): Promise<OptimizationSubgoal[]> {
  const params = metricId ? `?metric_id=${metricId}` : "";
  return fetchJSON(`${AGENT_API_BASE}/api/agent/tasks/framework/subgoals${params}`);
}

export async function getOpportunityTasks(clientId: string): Promise<OpportunityTaskSummary[]> {
  return fetchJSON(`${AGENT_API_BASE}/api/agent/tasks/framework/opportunity-tasks?client_id=${clientId}`);
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd geo_saas/web && npx tsc --noEmit`
Expected: No type errors in api.ts

- [ ] **Step 3: Commit**

```bash
git add geo_saas/web/src/lib/api.ts
git commit -m "feat: add framework API client functions"
```

---

## Task 6: Frontend — Node Components for Content Pipeline

**Files:**
- Create: `geo_saas/web/src/components/agents/nodes/NodeAnalyzerImport.tsx`
- Create: `geo_saas/web/src/components/agents/nodes/NodeContentGoals.tsx`
- Create: `geo_saas/web/src/components/agents/nodes/NodeContentType.tsx`
- Create: `geo_saas/web/src/components/agents/nodes/NodeStrategy.tsx`
- Create: `geo_saas/web/src/components/agents/nodes/NodeGenConfig.tsx`
- Create: `geo_saas/web/src/components/agents/nodes/NodePromptLink.tsx`
- Create: `geo_saas/web/src/components/agents/nodes/NodeConfirm.tsx`

Each node is a self-contained React component that renders its UI and calls `onChange(data)` to update parent state. This task creates all 7 node components.

- [ ] **Step 1: Create directory**

```bash
mkdir -p geo_saas/web/src/components/agents/nodes
```

- [ ] **Step 2: Create NodeAnalyzerImport.tsx (Node 0)**

```tsx
import { useState, useEffect } from "react";
import { FileSearch, ArrowRight, SkipForward } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getOpportunityTasks, type OpportunityTaskSummary } from "@/lib/api";

interface NodeAnalyzerImportProps {
  clientId: string;
  value: { analyzerTaskId: string | null; analyzerContext: any | null };
  onChange: (data: { analyzerTaskId: string | null; analyzerContext: any | null }) => void;
}

export default function NodeAnalyzerImport({ clientId, value, onChange }: NodeAnalyzerImportProps) {
  const [tasks, setTasks] = useState<OpportunityTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getOpportunityTasks(clientId).then(setTasks).catch(() => setTasks([])).finally(() => setLoading(false));
  }, [clientId]);

  const handleSelect = async (taskId: string) => {
    // Fetch full task output for analyzer context
    const res = await fetch(`${import.meta.env.VITE_AGENT_API_BASE || ""}/api/agent/tasks/${taskId}?client_id=${clientId}`);
    const task = await res.json();
    onChange({ analyzerTaskId: taskId, analyzerContext: task.output || null });
  };

  const handleSkip = () => {
    onChange({ analyzerTaskId: null, analyzerContext: null });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <FileSearch className="w-5 h-5 text-amber-400" />
        <h3 className="text-lg font-semibold text-white">引入分析报告</h3>
        <Badge variant="outline" className="text-xs text-zinc-400 border-zinc-700">可选</Badge>
      </div>

      <p className="text-sm text-zinc-400">
        选择一个已完成的「优化机会发现」分析任务，其结果将自动填充后续步骤。
      </p>

      {loading ? (
        <div className="text-zinc-500 text-sm py-4">正在加载分析任务...</div>
      ) : tasks.length === 0 ? (
        <div className="text-zinc-500 text-sm py-4 border border-dashed border-zinc-700 rounded-lg p-4 text-center">
          暂无已完成的「优化机会发现」分析任务。
          <br />
          <span className="text-xs">建议先运行一次「优化机会发现」分析，获取数据驱动的推荐。</span>
        </div>
      ) : (
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {tasks.map((t) => (
            <Card
              key={t.id}
              className={`p-3 cursor-pointer border transition-colors ${
                value.analyzerTaskId === t.id
                  ? "border-amber-500/50 bg-amber-500/5"
                  : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-600"
              }`}
              onClick={() => handleSelect(t.id)}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white">{t.task_name || "优化机会发现"}</p>
                  <p className="text-xs text-zinc-400 mt-1">
                    {t.completed_at ? new Date(t.completed_at).toLocaleDateString("zh-CN") : ""}
                    {t.topic_scope ? ` · ${t.topic_scope}` : ""}
                  </p>
                </div>
                <div className="flex gap-2 text-xs">
                  <Badge variant="secondary">{t.summary.topic_count} Topics</Badge>
                  <Badge variant="secondary">{t.summary.opportunity_count} 机会</Badge>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <div className="flex justify-end pt-2">
        <Button variant="ghost" size="sm" className="text-zinc-400 hover:text-white" onClick={handleSkip}>
          <SkipForward className="w-4 h-4 mr-1" />
          跳过，手动配置
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create NodeContentGoals.tsx (Node 1)**

```tsx
import { useState, useEffect } from "react";
import { Target } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getOptimizationMetrics, getOptimizationSubgoals, type OptimizationMetric, type OptimizationSubgoal } from "@/lib/api";

interface NodeContentGoalsProps {
  value: { selectedMetrics: string[]; selectedSubgoals: string[] };
  onChange: (data: { selectedMetrics: string[]; selectedSubgoals: string[] }) => void;
  analyzerContext?: any;
}

export default function NodeContentGoals({ value, onChange, analyzerContext }: NodeContentGoalsProps) {
  const [metrics, setMetrics] = useState<OptimizationMetric[]>([]);
  const [subgoals, setSubgoals] = useState<OptimizationSubgoal[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([getOptimizationMetrics(), getOptimizationSubgoals()])
      .then(([m, sg]) => {
        setMetrics(m);
        setSubgoals(sg);
        // Pre-fill from analyzer context if available and not yet selected
        if (analyzerContext && !loaded) {
          const opps = analyzerContext.content_opportunities || [];
          const recMetrics = new Set<string>();
          const recSubgoals = new Set<string>();
          opps.forEach((o: any) => {
            (o.recommended_metrics || []).forEach((m: string) => recMetrics.add(m));
            (o.recommended_subgoals || []).forEach((s: string) => recSubgoals.add(s));
          });
          if (recMetrics.size > 0 || recSubgoals.size > 0) {
            onChange({
              selectedMetrics: Array.from(recMetrics),
              selectedSubgoals: Array.from(recSubgoals),
            });
          }
        }
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [analyzerContext]);

  const toggleMetric = (id: string) => {
    const next = value.selectedMetrics.includes(id)
      ? value.selectedMetrics.filter((m) => m !== id)
      : [...value.selectedMetrics, id];
    // Remove subgoals of unselected metrics
    const validSubgoals = value.selectedSubgoals.filter((sg) => {
      const sub = subgoals.find((s) => s.id === sg);
      return sub && next.includes(sub.metric_id);
    });
    onChange({ selectedMetrics: next, selectedSubgoals: validSubgoals });
  };

  const toggleSubgoal = (id: string) => {
    const next = value.selectedSubgoals.includes(id)
      ? value.selectedSubgoals.filter((s) => s !== id)
      : [...value.selectedSubgoals, id];
    onChange({ ...value, selectedSubgoals: next });
  };

  const visibleSubgoals = subgoals.filter((sg) => value.selectedMetrics.includes(sg.metric_id));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Target className="w-5 h-5 text-blue-400" />
        <h3 className="text-lg font-semibold text-white">内容目标</h3>
      </div>

      <p className="text-sm text-zinc-400">选择本次内容生成要优化的指标和子目标。</p>

      {/* Layer 1: Metrics */}
      <div>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Success Metrics</p>
        <div className="grid grid-cols-2 gap-2">
          {metrics.map((m) => (
            <button
              key={m.id}
              onClick={() => toggleMetric(m.id)}
              className={`p-3 rounded-lg border text-left transition-colors ${
                value.selectedMetrics.includes(m.id)
                  ? "border-blue-500/50 bg-blue-500/10 text-white"
                  : "border-zinc-800 bg-zinc-900/50 text-zinc-400 hover:border-zinc-600"
              }`}
            >
              <div className="flex items-center gap-2">
                <span>{m.icon}</span>
                <span className="font-medium text-sm">{m.name_zh}</span>
              </div>
              <p className="text-xs mt-1 opacity-70">{m.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Layer 2: Sub-goals */}
      {visibleSubgoals.length > 0 && (
        <div>
          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Sub-goals</p>
          <div className="flex flex-wrap gap-2">
            {visibleSubgoals.map((sg) => (
              <button
                key={sg.id}
                onClick={() => toggleSubgoal(sg.id)}
                className={`px-3 py-1.5 rounded-full border text-sm transition-colors ${
                  value.selectedSubgoals.includes(sg.id)
                    ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                    : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                }`}
              >
                {sg.name_zh}
              </button>
            ))}
          </div>
        </div>
      )}

      {analyzerContext && (
        <p className="text-xs text-amber-400/70">
          已从分析报告预填推荐目标，你可以自由调整。
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create NodeContentType.tsx (Node 2)**

```tsx
import { FileText } from "lucide-react";

const CONTENT_TYPES = [
  { id: "faq", label: "FAQ", desc: "结构化问答，AI 引擎高度偏好", icon: "📋" },
  { id: "aeo_article", label: "AEO 文章", desc: "AI Engine Optimized 长文，800-1200 字", icon: "🤖" },
  { id: "article", label: "SEO 文章", desc: "传统 SEO 优化文章", icon: "✍️" },
  { id: "brief", label: "Content Brief", desc: "详细内容大纲，适合交给内容团队", icon: "📝" },
  { id: "comparison", label: "产品对比/测评", desc: "品牌 vs 竞品对比分析内容", icon: "⚖️" },
  { id: "platform_post", label: "平台定制帖", desc: "针对特定发布平台的格式化内容", icon: "📱" },
  { id: "howto", label: "How-to 教程", desc: "操作指南、使用教程", icon: "📖" },
  { id: "listicle", label: "Listicle", desc: "「Top N」类列表文章", icon: "📋" },
];

interface NodeContentTypeProps {
  value: string;
  onChange: (contentType: string) => void;
}

export default function NodeContentType({ value, onChange }: NodeContentTypeProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-5 h-5 text-purple-400" />
        <h3 className="text-lg font-semibold text-white">内容类型</h3>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {CONTENT_TYPES.map((ct) => (
          <button
            key={ct.id}
            onClick={() => onChange(ct.id)}
            className={`p-3 rounded-lg border text-left transition-colors ${
              value === ct.id
                ? "border-purple-500/50 bg-purple-500/10 text-white"
                : "border-zinc-800 bg-zinc-900/50 text-zinc-400 hover:border-zinc-600"
            }`}
          >
            <div className="flex items-center gap-2">
              <span>{ct.icon}</span>
              <span className="font-medium text-sm">{ct.label}</span>
            </div>
            <p className="text-xs mt-1 opacity-70">{ct.desc}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create NodeStrategy.tsx (Node 3)**

```tsx
import { useState } from "react";
import { Sparkles, Loader2, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface StrategyData {
  strategies: Array<{
    name: string;
    description: string;
    dimensions: {
      instruction: string;
      format: { structure: string; schema_markup?: string; word_count?: string };
      tone: string;
      constraints: string[];
      enhancement_rules: string[];
    };
    source_metrics: string[];
    source_subgoals: string[];
  }>;
  strategy_summary: string;
}

interface NodeStrategyProps {
  strategy: StrategyData | null;
  loading: boolean;
  onRegenerate: () => void;
  onEdit: (edits: string) => void;
}

export default function NodeStrategy({ strategy, loading, onRegenerate, onEdit }: NodeStrategyProps) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-zinc-400">
        <Loader2 className="w-6 h-6 animate-spin mb-3" />
        <p className="text-sm">正在生成策略组合...</p>
      </div>
    );
  }

  if (!strategy) {
    return (
      <div className="text-center py-8 text-zinc-500">
        <p>请先完成前序步骤以生成策略。</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-yellow-400" />
          <h3 className="text-lg font-semibold text-white">内容策略</h3>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => setEditing(!editing)}>
            <Pencil className="w-3 h-3 mr-1" />
            微调
          </Button>
          <Button variant="ghost" size="sm" onClick={onRegenerate}>
            重新生成
          </Button>
        </div>
      </div>

      {/* Strategy summary */}
      <p className="text-sm text-zinc-300 bg-zinc-900/50 border border-zinc-800 rounded-lg p-3">
        {strategy.strategy_summary}
      </p>

      {/* Strategy list */}
      <div className="space-y-3">
        {strategy.strategies.map((s, i) => (
          <div key={i} className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/30">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono text-zinc-500">#{i + 1}</span>
              <span className="font-medium text-sm text-white">{s.name}</span>
            </div>
            <p className="text-xs text-zinc-400 mb-2">{s.description}</p>
            <div className="flex flex-wrap gap-1">
              <Badge variant="outline" className="text-xs">{s.dimensions.tone}</Badge>
              {s.dimensions.constraints.slice(0, 2).map((c, j) => (
                <Badge key={j} variant="outline" className="text-xs text-zinc-500">{c}</Badge>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Edit panel */}
      {editing && (
        <div className="border border-zinc-700 rounded-lg p-3 bg-zinc-900/50">
          <p className="text-xs text-zinc-400 mb-2">输入你的调整建议，系统会据此重新生成策略：</p>
          <textarea
            className="w-full bg-zinc-800 border border-zinc-700 rounded p-2 text-sm text-white resize-none"
            rows={3}
            placeholder="例如：去掉第2条策略、增加口语化的调性..."
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
          />
          <div className="flex justify-end mt-2">
            <Button
              size="sm"
              onClick={() => { onEdit(editText); setEditing(false); setEditText(""); }}
              disabled={!editText.trim()}
            >
              应用调整
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Create NodeGenConfig.tsx (Node 4)**

```tsx
import { useState, useEffect } from "react";
import { Settings, ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";

const AI_PLATFORMS = [
  { id: "chatgpt", label: "ChatGPT", icon: "🤖" },
  { id: "gemini", label: "Gemini", icon: "✨" },
  { id: "aimode", label: "AI Mode", icon: "🔍" },
];

const PUBLISH_PLATFORMS = [
  { id: "official_site", label: "官网 FAQ/Blog" },
  { id: "reddit", label: "Reddit" },
  { id: "wiki", label: "Wikipedia" },
  { id: "review_site", label: "测评站" },
  { id: "youtube", label: "YouTube" },
  { id: "media", label: "媒体" },
];

const LANGUAGES = [
  { id: "en-US", label: "English" },
  { id: "zh-CN", label: "中文" },
  { id: "ja-JP", label: "日本語" },
  { id: "de-DE", label: "Deutsch" },
];

interface GenConfigData {
  aiPlatforms: string[];
  publishPlatform: string;
  language: string;
  count: number;
  productFacts: { specs: string; features: string; differentiators: string };
}

interface NodeGenConfigProps {
  value: GenConfigData;
  onChange: (data: GenConfigData) => void;
  analyzerContext?: any;
  clientPlatforms: string[];
}

export default function NodeGenConfig({ value, onChange, analyzerContext, clientPlatforms }: NodeGenConfigProps) {
  const [brandExpanded, setBrandExpanded] = useState(false);

  // Pre-fill from analyzer
  useEffect(() => {
    if (analyzerContext?.platform_recommendations && !value.publishPlatform) {
      const recs = analyzerContext.platform_recommendations;
      const topPlatform = recs[0]?.platform_type || "";
      const platformMap: Record<string, string> = {
        "官网FAQ": "official_site", "官网 FAQ/Blog": "official_site",
        "Reddit": "reddit", "Wikipedia": "wiki", "测评站": "review_site",
      };
      const mapped = platformMap[topPlatform] || "official_site";
      onChange({ ...value, publishPlatform: mapped });
    }
  }, [analyzerContext]);

  const toggleAiPlatform = (id: string) => {
    const next = value.aiPlatforms.includes(id)
      ? value.aiPlatforms.filter((p) => p !== id)
      : [...value.aiPlatforms, id];
    onChange({ ...value, aiPlatforms: next });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Settings className="w-5 h-5 text-cyan-400" />
        <h3 className="text-lg font-semibold text-white">生成配置</h3>
      </div>

      {/* AI Platforms */}
      <div>
        <p className="text-xs text-zinc-500 mb-2">目标 AI 平台</p>
        <div className="flex gap-2">
          {AI_PLATFORMS.filter((p) => clientPlatforms.includes(p.id)).map((p) => (
            <button
              key={p.id}
              onClick={() => toggleAiPlatform(p.id)}
              className={`px-3 py-1.5 rounded-lg border text-sm transition-colors ${
                value.aiPlatforms.includes(p.id)
                  ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
                  : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
              }`}
            >
              {p.icon} {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Publish Platform */}
      <div>
        <p className="text-xs text-zinc-500 mb-2">发布平台</p>
        <div className="flex flex-wrap gap-2">
          {PUBLISH_PLATFORMS.map((p) => (
            <button
              key={p.id}
              onClick={() => onChange({ ...value, publishPlatform: p.id })}
              className={`px-3 py-1.5 rounded-lg border text-sm transition-colors ${
                value.publishPlatform === p.id
                  ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
                  : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Language + Count */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-zinc-500 mb-2">语言</p>
          <select
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-sm text-white"
            value={value.language}
            onChange={(e) => onChange({ ...value, language: e.target.value })}
          >
            {LANGUAGES.map((l) => (
              <option key={l.id} value={l.id}>{l.label}</option>
            ))}
          </select>
        </div>
        <div>
          <p className="text-xs text-zinc-500 mb-2">生成数量</p>
          <input
            type="number"
            min={1}
            max={20}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-sm text-white"
            value={value.count}
            onChange={(e) => onChange({ ...value, count: parseInt(e.target.value) || 1 })}
          />
        </div>
      </div>

      {/* Brand info expandable */}
      <div className="border border-zinc-800 rounded-lg">
        <button
          className="w-full flex items-center justify-between p-3 text-sm text-zinc-400 hover:text-white"
          onClick={() => setBrandExpanded(!brandExpanded)}
        >
          <span>查看/补充品牌信息</span>
          {brandExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {brandExpanded && (
          <div className="px-3 pb-3 space-y-3">
            <div>
              <label className="text-xs text-zinc-500">产品规格</label>
              <textarea
                className="w-full bg-zinc-800 border border-zinc-700 rounded p-2 text-sm text-white resize-none mt-1"
                rows={2}
                placeholder="核心参数、技术指标..."
                value={value.productFacts.specs}
                onChange={(e) => onChange({ ...value, productFacts: { ...value.productFacts, specs: e.target.value } })}
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500">核心特性</label>
              <textarea
                className="w-full bg-zinc-800 border border-zinc-700 rounded p-2 text-sm text-white resize-none mt-1"
                rows={2}
                placeholder="产品卖点、独特功能..."
                value={value.productFacts.features}
                onChange={(e) => onChange({ ...value, productFacts: { ...value.productFacts, features: e.target.value } })}
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500">差异化优势</label>
              <textarea
                className="w-full bg-zinc-800 border border-zinc-700 rounded p-2 text-sm text-white resize-none mt-1"
                rows={2}
                placeholder="相比竞品的核心优势..."
                value={value.productFacts.differentiators}
                onChange={(e) => onChange({ ...value, productFacts: { ...value.productFacts, differentiators: e.target.value } })}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Create NodePromptLink.tsx (Node 5)**

```tsx
import { useState, useEffect } from "react";
import { Link, Lock, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getRankedPrompts } from "@/lib/api";

interface PromptItem {
  id: string;
  prompt_text: string;
  platform: string;
  topic_name: string;
}

interface NodePromptLinkProps {
  clientId: string;
  value: { promptIds: string[]; locked: boolean };
  onChange: (data: { promptIds: string[]; locked: boolean }) => void;
  analyzerContext?: any;
}

export default function NodePromptLink({ clientId, value, onChange, analyzerContext }: NodePromptLinkProps) {
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [loading, setLoading] = useState(true);
  const isLocked = !!analyzerContext;

  useEffect(() => {
    if (analyzerContext) {
      // Locked mode: prompts come from analyzer content_opportunities
      const opps = analyzerContext.content_opportunities || [];
      const ids = new Set<string>();
      opps.forEach((o: any) => (o.related_prompts || []).forEach((id: string) => ids.add(id)));
      onChange({ promptIds: Array.from(ids), locked: true });
      // Fetch prompt details for display
      if (ids.size > 0) {
        getRankedPrompts(clientId, "visibility", 100).then((all) => {
          setPrompts(all.filter((p: any) => ids.has(p.id)));
          setLoading(false);
        }).catch(() => setLoading(false));
      } else {
        setLoading(false);
      }
    } else {
      // Open mode: fetch ranked prompts
      getRankedPrompts(clientId, "visibility", 50)
        .then((data) => {
          setPrompts(data);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    }
  }, [clientId, analyzerContext]);

  const togglePrompt = (id: string) => {
    if (isLocked) return;
    const next = value.promptIds.includes(id)
      ? value.promptIds.filter((p) => p !== id)
      : [...value.promptIds, id];
    onChange({ promptIds: next, locked: false });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Link className="w-5 h-5 text-orange-400" />
        <h3 className="text-lg font-semibold text-white">Prompt 关联</h3>
        {isLocked && (
          <Badge variant="outline" className="text-xs text-amber-400 border-amber-500/30">
            <Lock className="w-3 h-3 mr-1" />
            锁定模式
          </Badge>
        )}
      </div>

      {isLocked ? (
        <p className="text-sm text-amber-400/80">
          已关联 {value.promptIds.length} 个 Prompts（来自分析报告）。如需修改，请回到第一步更换分析报告或跳过。
        </p>
      ) : (
        <p className="text-sm text-zinc-400">
          选择本次内容生成要针对的 AI 搜索 Prompts。
        </p>
      )}

      {loading ? (
        <div className="text-zinc-500 text-sm py-4">加载中...</div>
      ) : (
        <div className="space-y-1 max-h-[300px] overflow-y-auto">
          {prompts.map((p) => (
            <button
              key={p.id}
              onClick={() => togglePrompt(p.id)}
              disabled={isLocked}
              className={`w-full text-left p-2 rounded-lg border text-sm transition-colors ${
                value.promptIds.includes(p.id)
                  ? "border-orange-500/30 bg-orange-500/5 text-white"
                  : "border-zinc-800 text-zinc-400 hover:border-zinc-600"
              } ${isLocked ? "cursor-default opacity-80" : "cursor-pointer"}`}
            >
              <div className="flex items-center justify-between">
                <span className="truncate">{p.prompt_text}</span>
                <Badge variant="outline" className="text-xs ml-2 shrink-0">{p.platform}</Badge>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8: Create NodeConfirm.tsx (Node 6)**

```tsx
import { CheckCircle2, Play, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface NodeConfirmProps {
  summary: {
    analyzerTask: string | null;
    metrics: string[];
    subgoals: string[];
    contentType: string;
    strategyCount: number;
    aiPlatforms: string[];
    publishPlatform: string;
    language: string;
    count: number;
    promptCount: number;
  };
  onExecute: () => void;
  onSaveDraft: () => void;
  executing: boolean;
}

const CONTENT_TYPE_LABELS: Record<string, string> = {
  faq: "FAQ", aeo_article: "AEO 文章", article: "SEO 文章", brief: "Content Brief",
  comparison: "产品对比/测评", platform_post: "平台定制帖", howto: "How-to 教程", listicle: "Listicle",
};

export default function NodeConfirm({ summary, onExecute, onSaveDraft, executing }: NodeConfirmProps) {
  const rows = [
    { label: "来源分析报告", value: summary.analyzerTask || "无（手动配置）" },
    { label: "优化指标", value: summary.metrics.join(", ") || "未选择" },
    { label: "子目标", value: summary.subgoals.join(", ") || "未选择" },
    { label: "内容类型", value: CONTENT_TYPE_LABELS[summary.contentType] || summary.contentType },
    { label: "策略数量", value: `${summary.strategyCount} 条` },
    { label: "AI 平台", value: summary.aiPlatforms.join(", ") || "未选择" },
    { label: "发布平台", value: summary.publishPlatform || "未选择" },
    { label: "语言", value: summary.language },
    { label: "生成数量", value: String(summary.count) },
    { label: "关联 Prompts", value: `${summary.promptCount} 个` },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <CheckCircle2 className="w-5 h-5 text-green-400" />
        <h3 className="text-lg font-semibold text-white">确认执行</h3>
      </div>

      <div className="border border-zinc-800 rounded-lg divide-y divide-zinc-800">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between px-4 py-2.5">
            <span className="text-sm text-zinc-400">{r.label}</span>
            <span className="text-sm text-white">{r.value}</span>
          </div>
        ))}
      </div>

      <div className="flex gap-3 pt-2">
        <Button variant="outline" onClick={onSaveDraft} className="flex-1" disabled={executing}>
          <Save className="w-4 h-4 mr-2" />
          保存草稿
        </Button>
        <Button onClick={onExecute} className="flex-1 bg-green-600 hover:bg-green-700" disabled={executing}>
          <Play className="w-4 h-4 mr-2" />
          {executing ? "执行中..." : "确认并执行"}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 9: Commit all node components**

```bash
git add geo_saas/web/src/components/agents/nodes/
git commit -m "feat: add 7 node components for content pipeline wizard"
```

---

## Task 7: Frontend — ContentPipelineModal (Orchestrator)

**Files:**
- Create: `geo_saas/web/src/components/agents/ContentPipelineModal.tsx`

This modal orchestrates the 7 nodes as a step-by-step wizard, manages shared state, handles strategy generation, and submits the task.

- [ ] **Step 1: Create ContentPipelineModal.tsx**

```tsx
import { useState, useCallback, useEffect } from "react";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, X, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { createAgentTask, updateAgentTask, getAgentTask } from "@/lib/api";

import NodeAnalyzerImport from "./nodes/NodeAnalyzerImport";
import NodeContentGoals from "./nodes/NodeContentGoals";
import NodeContentType from "./nodes/NodeContentType";
import NodeStrategy from "./nodes/NodeStrategy";
import NodeGenConfig from "./nodes/NodeGenConfig";
import NodePromptLink from "./nodes/NodePromptLink";
import NodeConfirm from "./nodes/NodeConfirm";

interface ContentPipelineModalProps {
  open: boolean;
  clientId: string;
  userId: string;
  clientPlatforms: string[];
  preselectedAnalyzerTaskId?: string | null;
  existingTaskId?: string | null;
  onClose: () => void;
  onTaskCreated?: () => void;
}

interface PipelineState {
  // Node 0
  analyzerTaskId: string | null;
  analyzerContext: any | null;
  // Node 1
  selectedMetrics: string[];
  selectedSubgoals: string[];
  // Node 2
  contentType: string;
  // Node 3
  strategy: any | null;
  userStrategyEdits: string | null;
  // Node 4
  aiPlatforms: string[];
  publishPlatform: string;
  language: string;
  count: number;
  productFacts: { specs: string; features: string; differentiators: string };
  // Node 5
  promptIds: string[];
  promptsLocked: boolean;
}

const INITIAL_STATE: PipelineState = {
  analyzerTaskId: null,
  analyzerContext: null,
  selectedMetrics: [],
  selectedSubgoals: [],
  contentType: "faq",
  strategy: null,
  userStrategyEdits: null,
  aiPlatforms: [],
  publishPlatform: "",
  language: "en-US",
  count: 5,
  productFacts: { specs: "", features: "", differentiators: "" },
  promptIds: [],
  promptsLocked: false,
};

const NODE_LABELS = [
  "分析报告引入",
  "内容目标",
  "内容类型",
  "内容策略",
  "生成配置",
  "Prompt 关联",
  "确认执行",
];

export default function ContentPipelineModal({
  open, clientId, userId, clientPlatforms,
  preselectedAnalyzerTaskId, existingTaskId,
  onClose, onTaskCreated,
}: ContentPipelineModalProps) {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<PipelineState>(INITIAL_STATE);
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(existingTaskId || null);

  // Reset on open
  useEffect(() => {
    if (open) {
      setState(INITIAL_STATE);
      setStep(0);
      setTaskId(existingTaskId || null);
    }
  }, [open, existingTaskId]);

  // Pre-select analyzer task if provided (e.g., from CTA button)
  useEffect(() => {
    if (preselectedAnalyzerTaskId && open) {
      // Auto-load this analyzer task
      getAgentTask(preselectedAnalyzerTaskId, clientId)
        .then((task: any) => {
          setState((s) => ({
            ...s,
            analyzerTaskId: preselectedAnalyzerTaskId,
            analyzerContext: task.output || null,
          }));
          setStep(1); // Skip to Node 1
        })
        .catch(() => toast.error("无法加载分析报告"));
    }
  }, [preselectedAnalyzerTaskId, open, clientId]);

  // Auto-generate strategy when entering Node 3
  const generateStrategy = useCallback(async () => {
    if (state.selectedMetrics.length === 0) {
      toast.error("请先选择优化指标");
      return;
    }
    setStrategyLoading(true);
    try {
      // Create or update draft task to trigger strategy generation on backend
      const inputs = buildInputs();
      if (!taskId) {
        const res = await createAgentTask({
          client_id: clientId,
          user_id: userId,
          task_type: "content_generation",
          task_name: `内容生成 - ${new Date().toLocaleDateString("zh-CN")}`,
          inputs,
          save_only: true,
        });
        setTaskId(res.id);
      }

      // For now, generate strategy client-side via a dedicated endpoint
      const agentBase = import.meta.env.VITE_AGENT_API_BASE || "";
      const res = await fetch(`${agentBase}/api/agent/tasks/generate-strategy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          selected_metrics: state.selectedMetrics,
          selected_subgoals: state.selectedSubgoals,
          content_type: state.contentType,
          analyzer_context: state.analyzerContext,
          user_strategy_edits: state.userStrategyEdits,
        }),
      });
      const data = await res.json();
      setState((s) => ({ ...s, strategy: data }));
    } catch (e) {
      toast.error("策略生成失败");
    } finally {
      setStrategyLoading(false);
    }
  }, [state, clientId, userId, taskId]);

  useEffect(() => {
    if (step === 3 && !state.strategy && !strategyLoading) {
      generateStrategy();
    }
  }, [step]);

  const buildInputs = () => ({
    selected_metrics: state.selectedMetrics,
    selected_subgoals: state.selectedSubgoals,
    content_type: state.contentType,
    analyzer_context: state.analyzerContext,
    analyzer_task_id: state.analyzerTaskId,
    user_strategy_edits: state.userStrategyEdits,
    ai_platforms: state.aiPlatforms,
    publish_platform: state.publishPlatform,
    language: state.language,
    count: state.count,
    product_facts: state.productFacts,
    target_prompt_ids: state.promptIds,
  });

  const handleExecute = async () => {
    setExecuting(true);
    try {
      const inputs = buildInputs();
      if (taskId) {
        await updateAgentTask(taskId, {
          client_id: clientId,
          user_id: userId,
          inputs,
          save_only: false,
        });
      } else {
        await createAgentTask({
          client_id: clientId,
          user_id: userId,
          task_type: "content_generation",
          task_name: `内容生成 - ${new Date().toLocaleDateString("zh-CN")}`,
          inputs,
          save_only: false,
        });
      }
      toast.success("内容生成任务已启动");
      onTaskCreated?.();
      onClose();
    } catch (e) {
      toast.error("任务创建失败");
    } finally {
      setExecuting(false);
    }
  };

  const handleSaveDraft = async () => {
    try {
      const inputs = buildInputs();
      if (taskId) {
        await updateAgentTask(taskId, {
          client_id: clientId,
          user_id: userId,
          inputs,
          save_only: true,
        });
      } else {
        const res = await createAgentTask({
          client_id: clientId,
          user_id: userId,
          task_type: "content_generation",
          task_name: `内容生成草稿 - ${new Date().toLocaleDateString("zh-CN")}`,
          inputs,
          save_only: true,
        });
        setTaskId(res.id);
      }
      toast.success("草稿已保存");
    } catch (e) {
      toast.error("保存失败");
    }
  };

  const canNext = () => {
    switch (step) {
      case 0: return true; // Optional
      case 1: return state.selectedMetrics.length > 0;
      case 2: return !!state.contentType;
      case 3: return !!state.strategy;
      case 4: return state.aiPlatforms.length > 0 && !!state.publishPlatform;
      case 5: return state.promptIds.length > 0 || !!state.analyzerContext;
      default: return true;
    }
  };

  const renderNode = () => {
    switch (step) {
      case 0:
        return (
          <NodeAnalyzerImport
            clientId={clientId}
            value={{ analyzerTaskId: state.analyzerTaskId, analyzerContext: state.analyzerContext }}
            onChange={(d) => setState((s) => ({ ...s, ...d }))}
          />
        );
      case 1:
        return (
          <NodeContentGoals
            value={{ selectedMetrics: state.selectedMetrics, selectedSubgoals: state.selectedSubgoals }}
            onChange={(d) => setState((s) => ({ ...s, ...d }))}
            analyzerContext={state.analyzerContext}
          />
        );
      case 2:
        return (
          <NodeContentType
            value={state.contentType}
            onChange={(ct) => setState((s) => ({ ...s, contentType: ct }))}
          />
        );
      case 3:
        return (
          <NodeStrategy
            strategy={state.strategy}
            loading={strategyLoading}
            onRegenerate={generateStrategy}
            onEdit={(edits) => {
              setState((s) => ({ ...s, userStrategyEdits: edits, strategy: null }));
              generateStrategy();
            }}
          />
        );
      case 4:
        return (
          <NodeGenConfig
            value={{
              aiPlatforms: state.aiPlatforms,
              publishPlatform: state.publishPlatform,
              language: state.language,
              count: state.count,
              productFacts: state.productFacts,
            }}
            onChange={(d) => setState((s) => ({ ...s, ...d }))}
            analyzerContext={state.analyzerContext}
            clientPlatforms={clientPlatforms}
          />
        );
      case 5:
        return (
          <NodePromptLink
            clientId={clientId}
            value={{ promptIds: state.promptIds, locked: state.promptsLocked }}
            onChange={(d) => setState((s) => ({ ...s, promptIds: d.promptIds, promptsLocked: d.locked }))}
            analyzerContext={state.analyzerContext}
          />
        );
      case 6:
        return (
          <NodeConfirm
            summary={{
              analyzerTask: state.analyzerTaskId ? "已关联" : null,
              metrics: state.selectedMetrics,
              subgoals: state.selectedSubgoals,
              contentType: state.contentType,
              strategyCount: state.strategy?.strategies?.length || 0,
              aiPlatforms: state.aiPlatforms,
              publishPlatform: state.publishPlatform,
              language: state.language,
              count: state.count,
              promptCount: state.promptIds.length,
            }}
            onExecute={handleExecute}
            onSaveDraft={handleSaveDraft}
            executing={executing}
          />
        );
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col bg-zinc-950 border-zinc-800">
        <DialogTitle className="sr-only">内容生成 Pipeline</DialogTitle>
        <DialogDescription className="sr-only">7 步内容生成配置向导</DialogDescription>

        {/* Step indicator */}
        <div className="flex items-center gap-1 px-1 pt-1 pb-3 border-b border-zinc-800">
          {NODE_LABELS.map((label, i) => (
            <button
              key={i}
              onClick={() => i <= step && setStep(i)}
              className={`flex-1 text-center py-1.5 rounded text-xs transition-colors ${
                i === step
                  ? "bg-zinc-800 text-white font-medium"
                  : i < step
                  ? "text-zinc-400 hover:text-white cursor-pointer"
                  : "text-zinc-600 cursor-default"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Node content */}
        <div className="flex-1 overflow-y-auto py-4 px-1">
          {renderNode()}
        </div>

        {/* Navigation */}
        {step < 6 && (
          <div className="flex justify-between pt-3 border-t border-zinc-800">
            <Button
              variant="ghost"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
            >
              <ChevronLeft className="w-4 h-4 mr-1" />
              上一步
            </Button>
            <Button
              onClick={() => setStep((s) => Math.min(6, s + 1))}
              disabled={!canNext()}
            >
              下一步
              <ChevronRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add geo_saas/web/src/components/agents/ContentPipelineModal.tsx
git commit -m "feat: add ContentPipelineModal orchestrator for 7-node wizard"
```

---

## Task 8: Backend — Strategy Generation Endpoint

**Files:**
- Modify: `geo_agent/src/routers/tasks.py`

Add a dedicated endpoint for on-demand strategy generation (used by Node 3 in the frontend).

- [ ] **Step 1: Add strategy generation endpoint**

```python
@router.post("/generate-strategy")
async def generate_strategy(request: dict):
    """Generate strategy combination from user selections + analyzer context.
    Called by Content Node 3 for real-time strategy preview."""
    import json as _json
    from google.genai import types
    from llm.client import get_genai_client, get_model_id

    client_id = request.get("client_id", "")
    selected_metrics = request.get("selected_metrics", [])
    selected_subgoals = request.get("selected_subgoals", [])
    content_type = request.get("content_type", "faq")
    analyzer_context = request.get("analyzer_context")
    user_edits = request.get("user_strategy_edits")

    pool = await get_pool()

    # Load sub-goal descriptions
    sg_rows = await pool.fetch(
        """SELECT sg.id, sg.name_zh, sg.description, m.name_zh AS metric_name
           FROM geo_optimization_subgoals sg
           JOIN geo_optimization_metrics m ON sg.metric_id = m.id
           WHERE sg.id = ANY($1::text[])""",
        selected_subgoals,
    )
    sg_descriptions = [f"- {r['metric_name']} > {r['name_zh']}: {r['description']}" for r in sg_rows]

    # Brand profile
    bp_row = await pool.fetchrow(
        """SELECT brand_name, tone_of_voice, target_audience, key_messages, brand_values
           FROM geo_brand_profiles WHERE client_id = $1::uuid""",
        client_id,
    )
    brand = dict(bp_row) if bp_row else {}

    analyzer_snippet = ""
    if analyzer_context:
        analyzer_snippet = f"""
## Analyzer 上下文
{_json.dumps(analyzer_context.get("topic_quadrants", [])[:3], ensure_ascii=False, indent=2)}
{_json.dumps(analyzer_context.get("content_opportunities", [])[:3], ensure_ascii=False, indent=2)}
"""

    client_llm = get_genai_client()
    model_id = get_model_id("flash")  # Flash for speed in interactive preview

    prompt = f"""你是 GEO 内容策略专家。请基于以下输入生成策略组合。

## 输入
- 内容类型: {content_type}
- 优化 Metrics: {', '.join(selected_metrics)}
- Sub-goals:
{chr(10).join(sg_descriptions)}

## 品牌画像
{_json.dumps(brand, ensure_ascii=False, indent=2)}
{analyzer_snippet}
{f"## 用户调整要求{chr(10)}{user_edits}" if user_edits else ""}

## 输出 JSON
{{"strategies": [{{"name": "...", "description": "...", "dimensions": {{"instruction": "...", "format": {{"structure": "...", "schema_markup": "...", "word_count": "..."}}, "tone": "...", "constraints": ["..."], "enhancement_rules": ["..."]}}, "source_metrics": ["..."], "source_subgoals": ["..."]}}], "strategy_summary": "..."}}

生成 2-4 个互补策略。"""

    for attempt in range(1, 4):
        try:
            response = await client_llm.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3, max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return _json.loads(text)
        except Exception as e:
            logger.warning(f"[STRATEGY] attempt {attempt}/3 failed: {e}")
            if attempt == 3:
                raise HTTPException(status_code=500, detail=f"Strategy generation failed: {e}")
            import asyncio
            await asyncio.sleep(1)
```

- [ ] **Step 2: Verify endpoint works**

Run: `curl -X POST http://localhost:8001/api/agent/tasks/generate-strategy -H 'Content-Type: application/json' -d '{"client_id":"<test-id>","selected_metrics":["readability"],"selected_subgoals":["machine_readability"],"content_type":"faq"}'`
Expected: JSON with strategies array

- [ ] **Step 3: Commit**

```bash
git add geo_agent/src/routers/tasks.py
git commit -m "feat: add /generate-strategy endpoint for interactive strategy preview"
```

---

## Task 9: Frontend — Wire AgentContent to New Pipeline Modal

**Files:**
- Modify: `geo_saas/web/src/pages/agents/AgentContent.tsx`

Replace `ContentTaskModal` usage with `ContentPipelineModal`.

- [ ] **Step 1: Update imports and modal usage**

In `AgentContent.tsx`, replace the ContentTaskModal import and usage:

```typescript
// Replace this import:
// import ContentTaskModal from "@/components/agents/ContentTaskModal";
// With:
import ContentPipelineModal from "@/components/agents/ContentPipelineModal";
```

Then replace all `<ContentTaskModal .../>` JSX with:

```tsx
<ContentPipelineModal
  open={taskModalOpen}
  clientId={selectedClient?.id || ""}
  userId={user?.sub || ""}
  clientPlatforms={clientPlatforms}
  preselectedAnalyzerTaskId={preselectedAnalyzerTaskId}
  existingTaskId={editingTaskId}
  onClose={() => {
    setTaskModalOpen(false);
    setPreselectedAnalyzerTaskId(null);
    setEditingTaskId(null);
  }}
  onTaskCreated={() => refreshTasks()}
/>
```

Add state for preselected analyzer task:

```typescript
const [preselectedAnalyzerTaskId, setPreselectedAnalyzerTaskId] = useState<string | null>(null);
```

- [ ] **Step 2: Verify the page renders without errors**

Run: `cd geo_saas/web && npm run dev` and navigate to the Content page.
Expected: The new ContentPipelineModal opens with the 7-node wizard.

- [ ] **Step 3: Commit**

```bash
git add geo_saas/web/src/pages/agents/AgentContent.tsx
git commit -m "feat: wire AgentContent to new ContentPipelineModal"
```

---

## Task 10: Frontend — Add "情感分析" Template + CTA Button on Analyzer

**Files:**
- Modify: `geo_saas/web/src/components/insights/TemplateConfigModal.tsx`
- Modify: `geo_saas/web/src/pages/agents/AgentAnalysis.tsx`

- [ ] **Step 1: Add 情感分析 to ANALYSIS_GOALS in TemplateConfigModal.tsx**

Find the `ANALYSIS_GOALS` array and add:

```typescript
{
  id: "sentiment",
  label: "情感分析",
  description: "专门针对品牌情感维度的深度分析，识别正面和负面情感主题",
  icon: MessageSquare,
  recommendedDomains: ["sentiment"],
  color: "text-pink-400 border-pink-500/30 bg-pink-500/5",
},
```

Also add `"sentiment"` to the `AnalysisGoal` type:

```typescript
type AnalysisGoal = "benchmark" | "trend" | "opportunity" | "health" | "sentiment";
```

And add recommended charts for sentiment in `RECOMMENDED_CHARTS`:

```typescript
sentiment: [
  { nl_query: "各 AI 平台的情绪分布（正面/中性/负面占比）", chart_type: "bar" },
  { nl_query: "品牌正面情绪主题 Top 10", chart_type: "bar" },
  { nl_query: "品牌负面情绪主题 Top 10", chart_type: "bar" },
  { nl_query: "品牌情绪评分随时间变化趋势", chart_type: "line" },
],
```

- [ ] **Step 2: Add CTA button on opportunity analysis report in AgentAnalysis.tsx**

In the report output rendering section, after the insights markdown, add a CTA button that navigates to Content with the analyzer task pre-selected:

```tsx
{/* CTA: Jump to Content from opportunity analysis */}
{selectedRun?.inputs?.goal === "opportunity" && selectedRun?.status === "COMPLETED" && (
  <div className="mt-6 p-4 border border-amber-500/20 rounded-lg bg-amber-500/5">
    <p className="text-sm text-amber-300 mb-3">
      基于本次分析结果，直接进入内容生成
    </p>
    <Button
      onClick={() => {
        // Navigate to Content page with this analyzer task pre-selected
        window.location.href = `/agents/content?analyzer_task_id=${selectedRun.id}`;
      }}
      className="bg-amber-600 hover:bg-amber-700 text-white"
    >
      <Sparkles className="w-4 h-4 mr-2" />
      开始生成内容
    </Button>
  </div>
)}
```

- [ ] **Step 3: In AgentContent.tsx, read analyzer_task_id from URL params**

```typescript
// In AgentContent component, add:
useEffect(() => {
  const params = new URLSearchParams(window.location.search);
  const analyzerTaskId = params.get("analyzer_task_id");
  if (analyzerTaskId) {
    setPreselectedAnalyzerTaskId(analyzerTaskId);
    setTaskModalOpen(true);
    // Clean up URL
    window.history.replaceState({}, "", window.location.pathname);
  }
}, []);
```

- [ ] **Step 4: Commit**

```bash
git add geo_saas/web/src/components/insights/TemplateConfigModal.tsx geo_saas/web/src/pages/agents/AgentAnalysis.tsx geo_saas/web/src/pages/agents/AgentContent.tsx
git commit -m "feat: add sentiment template + CTA button for Analyzer→Content handoff"
```

---

## Task 11: Integration — Opportunity Discovery Template in Frontend

**Files:**
- Modify: `geo_saas/web/src/components/insights/TemplateConfigModal.tsx`
- Modify: `geo_saas/web/src/pages/agents/AgentAnalysis.tsx`

The "opportunity" goal already exists in the frontend, but it currently runs the generic analysis pipeline. We need to route it to the new `opportunity_discovery` task type so it uses the 4-step pipeline from Task 3.

- [ ] **Step 1: Update task creation for opportunity goal**

In the analysis run creation flow (TemplateConfigModal or wherever the analysis task is submitted), detect when `goal === "opportunity"` and set `task_type: "opportunity_discovery"` instead of `"analysis"`:

Find the task creation logic and add:

```typescript
// When submitting an analysis task with goal "opportunity",
// use the new opportunity_discovery task type
const taskType = currentGoal === "opportunity" ? "opportunity_discovery" : "analysis";
```

This ensures the backend routes to `opportunity_pipeline.py` instead of `analysis_pipeline.py`.

- [ ] **Step 2: Update report rendering for opportunity discovery output**

In `AgentAnalysis.tsx`, add rendering for the structured opportunity output (topic quadrants, content opportunities, platform recommendations) alongside the insights markdown.

The output JSON includes `topic_quadrants`, `content_opportunities`, `platform_recommendations`, and `insights_markdown`. The markdown already covers the narrative, but add a visual summary section:

```tsx
{/* Opportunity Discovery structured output */}
{selectedRun?.task_type === "opportunity_discovery" && selectedRun?.output && (
  <div className="space-y-4 mb-6">
    {/* Topic quadrant badges */}
    <div>
      <h4 className="text-sm font-medium text-zinc-400 mb-2">Topic 四象限</h4>
      <div className="flex flex-wrap gap-2">
        {(selectedRun.output.topic_quadrants || []).map((t: any, i: number) => {
          const colors: Record<string, string> = {
            "强势": "bg-green-500/10 text-green-400 border-green-500/20",
            "薄弱": "bg-red-500/10 text-red-400 border-red-500/20",
            "待挖掘": "bg-amber-500/10 text-amber-400 border-amber-500/20",
            "新兴": "bg-blue-500/10 text-blue-400 border-blue-500/20",
          };
          return (
            <Badge key={i} variant="outline" className={colors[t.primary_quadrant] || ""}>
              {t.topic}: {t.primary_quadrant}{t.secondary_quadrant ? ` (${t.secondary_quadrant})` : ""}
            </Badge>
          );
        })}
      </div>
    </div>

    {/* Top opportunities */}
    <div>
      <h4 className="text-sm font-medium text-zinc-400 mb-2">
        选题机会 Top {Math.min(5, (selectedRun.output.content_opportunities || []).length)}
      </h4>
      <div className="space-y-2">
        {(selectedRun.output.content_opportunities || []).slice(0, 5).map((o: any, i: number) => (
          <div key={i} className="flex items-center justify-between p-2 border border-zinc-800 rounded-lg">
            <div>
              <p className="text-sm text-white">{o.angle}</p>
              <p className="text-xs text-zinc-500">{o.source_quadrant} · {(o.recommended_metrics || []).join(", ")}</p>
            </div>
            <Badge variant="secondary">{o.opportunity_score}/10</Badge>
          </div>
        ))}
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 3: Commit**

```bash
git add geo_saas/web/src/components/insights/TemplateConfigModal.tsx geo_saas/web/src/pages/agents/AgentAnalysis.tsx
git commit -m "feat: route opportunity goal to new pipeline + render structured output"
```

---

## Task 12: End-to-End Verification

- [ ] **Step 1: Run database migration**

Provide the SQL file to the user for execution:
```bash
# User runs:
psql -h <host> -d <db> -f migrations/023_content_redesign_framework.sql
```
Expected: All tables created, seed data inserted

- [ ] **Step 2: Verify backend starts**

```bash
cd geo_agent/src && python main.py
```
Expected: All pipelines registered (opportunity_discovery, content_generation, analysis)

- [ ] **Step 3: Verify frontend builds**

```bash
cd geo_saas/web && npm run build
```
Expected: No TypeScript or build errors

- [ ] **Step 4: Test Analyzer → Content flow**

1. Open Analyzer page, select "优化机会发现" template
2. Run the analysis → verify 4-step progress
3. After completion, verify structured output (quadrant badges, opportunity list)
4. Click "开始生成内容" CTA button
5. Verify Content page opens with ContentPipelineModal pre-filled from Analyzer

- [ ] **Step 5: Test manual Content flow**

1. Open Content page, create new task
2. Skip Node 0 (no Analyzer import)
3. Walk through all 7 nodes
4. Verify strategy generation at Node 3
5. Execute and verify 3-step backend pipeline runs

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: content generation redesign — three-layer framework, opportunity pipeline, 7-node wizard"
```

---

## Scope Notes

**In scope:** Three-layer framework (DB + API + 9 seed strategies), upgraded opportunity discovery pipeline, sentiment analysis template, redesigned 7-node Content wizard with strategy-driven generation, Content Brief differentiation, Analyzer→Content handoff CTA, strategy generation endpoint.

**Out of scope (per spec "概念预留"):** Feedback loop automation (content_assets table created but tracking logic deferred), MAP-Elites strategy evolution, strategy admin UI, post-processing enhancement rule engine (currently LLM self-checks constraints/enhancements in prompt).

**Deferred but ready:** The `geo_content_assets` table and `geo_strategies` table are created and seeded, ready for the feedback loop and strategy admin features when those phases begin.
