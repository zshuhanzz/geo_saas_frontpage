# GEO SaaS

GEO SaaS 是面向客户的 SaaS 前端与 API 平台，独立于内部管理后台 (Admin)，提供品牌可见性洞察、Prompt 编辑、AI 概念头脑风暴、Onboarding Wizard、自动发现 (Auto-Discovery) 及与 Agent 的 wizard-driven 分析/内容生成流程。

> **当前版本**: API v41 / Web v56 (2026-05-24) — Citation ranking pagination + AI Citable Content Wizard visibility + Quality Gate/Revise 状态展示

## 🔐 用户认证

Google credential 只在 `POST /api/auth/session` 登录交换时验证一次。用户必须
拥有有效 Workspace 权限（或启用了 `support_all_clients` 的 Super Admin 权限），
后端才会签发 `answerx_saas_session` HttpOnly Cookie。该 Session 有效期 24 小时，
同时供同源代理后的 SaaS API 和 Agent API 使用；Admin 使用另一枚独立的 12 小时
Cookie。前端不再把 Google token 写入 localStorage。

Session 只解决“当前是谁”；Workspace Entitlement、角色能力和租户隔离仍在每个
业务请求中实时检查。Cloud Scheduler/System Job 继续使用严格限定入口的服务账号
OIDC Bearer，不使用浏览器 Session。

## 🔀 v1.2 Dual-Mode Tracking (OEM/ODM 适配)

SaaS 侧 v1.2 的增量:

### Insights 新增 endpoint 与 Dashboard
- `GET /api/insights/citation-by-role` — citation 按 12 值 role 分桶 + NULL 归为 `unclassified`（避免 OEM 客户看到的引用总数 "缩水"）。孤儿 citation (result_id 无对应 geo_results) 已过滤，保持与 Agent pipeline 一致。
- `GET /api/insights/product-visibility` — 产品级 SOV 排名
- `GET /api/insights/shadow-product-cooccurrence` — OEM 客户的 own-product × shadow-brand 共现
- `GET /api/insights/shadow-peer-product-cooccurrence` — OEM 客户的 peer-product × shadow-brand 共现（channel-penetration 图）
- `GET /api/insights/product-sentiment-by-role` — 产品 role × sentiment 分布
- `GET /api/insights/availability` — 返回 `has_own_brands / has_shadow_brands / has_peers` 等 flag，前端用于 Tab / 模板 visibility gating
- `GET /api/insights/peer-sov-via-list` — peer SOV 使用 `geo_client_peers` EXISTS 成员检查（而非 brand_role='peer'），解决 Shadow + Peer 双重身份 brand（如 RC 同时是 Roborock 的竞品）的 SOV 漏算。**孤儿 mention 已过滤**，与 `/visibility` 保持一致。

### Citation Insights (2026-05 更新)

- “被引用最多的域名”与“被引用最多的页面”拆分为两个 ranking 语义：
  - Domain ranking：按 domain 聚合 citation count。
  - Page ranking：按 canonical URL / page URL 聚合 citation count。
- 两个 ranking 均支持后端分页，每页最多 50 条。
- 搜索范围覆盖全量结果，而不是只搜当前页。
- 前端避免“显示 50 个页面但只渲染 30 个”的截断问题。
- 该设计允许出现：`youtube.com` 在 domain Top 50 中排名很高，但其单页 URL 排在 page Top 50 之外；用户仍可通过全量搜索或翻页定位。

### Onboarding Wizard + Auto-Discovery
- `POST /api/onboarding/auto-discover(/stream)` — 4-layer fallback 爬取 + Gemini Flash 合成 topics/products
- v2-late 追加 `seed_urls` 参数 + `seed_products` 响应字段: 用户提供列表页 URL，Layer 0 抓取真实 anchor URL，**完全 bypass LLM 防 URL 幻觉**。
- Onboarding Wizard 支持 "自有品牌 / OEM 分叉"，自动引导 Shadow Brand 创建

### Wizard (Schema-driven) 驱动的 Agent 前端
- `src/components/wizard/` — FieldRenderer + custom field 组件（TopicRefPicker / PromptRefPicker / ModeGatePicker / AnalyzerImport / ChartBuilder / PromptEditor / PeerPicker / ProductFactsForm / StrategyGenerator / Reddit Discover / Official Website Discover / Citation Analysis Preflight）
- `src/pages/agents/AgentAnalysis.tsx` + `AgentContent.tsx` — 模板画廊 + 任务列表 + 报告查看 (v1.2 chat scaffolding 已剥离)
- Settings 加 Brands (Own/Shadow) / Peers / Products / Tracked URLs / Sales Channels 全套管理 UI

### AI Citable Content Wizard (2026-05 更新)

- 新增 `Reddit AI Citable Post Generator` 与 `Official Website AI Citable Article`。
- Citation Analysis step 支持预运行，并在页面展示 triage、content action、source patterns、GEO gaps 与 fetch status。
- Confirm / task detail 显示 8 步执行流程：Citation Analysis、Strategy、Content、Quality Gate、第一轮 Revise、复查、第二轮 Revise、第二轮后复查。
- 未执行的第二轮 Revise / recheck 显示 `skipped`，避免误以为实际执行。
- 详情页展示 `pre_revision_quality_review` 与最终 `quality_review` 的区别，避免“最终通过但报告残留旧问题”。

### Settings API 补强
- `/brands/{brand_id}/products` **v1.2 修复**: 返回 (a) `owner_brand_id=brand_id AND role='shadow_brand_product'` + (b) JOIN `geo_product_sales_channels` 关联进来的 own 产品（对 OEM 场景至关重要）。每行标注 `channel_source='owned' | 'sales_channel'`。

### 多租户 gating
- 所有 `/insights/*` endpoint 及模板 wizard_config 的 `visibility_condition` 基于 `availability` flag。"渠道分析" Tab + "渠道表现分析" 模板仅 `has_shadow_brands=true` 客户可见。

详细设计见 [docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md](../docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md)。

## 📂 目录结构

```
geo_saas/
├── src/                  # FastAPI 后端 (Python)
│   ├── main.py           # 入口 & 路由注册
│   ├── database.py       # asyncpg 连接池 + DB adapter
│   ├── requirements.txt
│   ├── Dockerfile
│   └── routers/          # API 路由模块
│       ├── insights/            # Insights 子模块 (拆分式架构)
│       │   ├── __init__.py      # 路由汇聚
│       │   ├── _helpers.py      # 共享工具 (日期解析)
│       │   ├── visibility.py    # 品牌可见性 (SOV + 时序 + 排名)
│       │   ├── citations.py     # 引用来源总览 / 趋势
│       │   ├── cited_domains.py # Top cited domains 分页 + 全量搜索
│       │   ├── cited_pages.py   # Top cited pages 分页 + 全量搜索
│       │   ├── fanouts.py       # Query Fanout 列表 (分页)
│       │   └── prompt_metrics.py# Prompt 级指标聚合
│       ├── prompts.py           # Prompt CRUD & 批量操作
│       ├── brainstorming.py     # AI 概念头脑风暴 (Gemini)
│       ├── clients.py           # 客户管理 & Topic/Product CRUD
│       ├── settings.py          # 品牌设置 (Peers/Domains/Personas)
│       └── globals.py           # 全局字典 (Intents/Platforms/Languages)
├── web/                  # React 前端 (TypeScript + Vite)
│   └── src/
│       ├── pages/
│       │   ├── PromptEditor.tsx     # Prompt 管理 (核心页面)
│       │   ├── Insights.tsx         # 品牌洞察入口 (筛选 Context)
│       │   ├── SettingsPage.tsx     # 品牌设置
│       │   └── insights/            # 洞察子页面
│       │       ├── Visibility.tsx   # 品牌可见性
│       │       ├── Citations.tsx    # 引用来源
│       │       ├── Prompts.tsx      # Prompt 分析 + 下钻
│       │       └── Fanouts.tsx      # Query Fanout 列表
│       ├── contexts/
│       │   └── SaaSContext.tsx      # 全局状态 (客户/筛选)
│       ├── components/ui/           # shadcn/ui 组件库
│       ├── components/wizard/       # Schema-driven wizard + customFields
│       ├── components/agents/       # Task cards / progress / nodes
│       └── lib/
│           └── api.ts               # API 调用封装
└── terraform/            # Cloud Run 部署配置
    ├── main.tf
    └── terraform.tfvars
```

---

## 🚀 本地开发

### 前置条件

- Python 3.12+
- Node.js 18+
- Cloud SQL Proxy 运行中 (连接 localhost:5432)

### 1. 启动 API 后端

```bash
cd geo_saas/src
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

API 运行在: http://localhost:8001

### 2. 启动 Web 前端

```bash
cd geo_saas/web
npm install && npm run dev
```

前端运行在: http://localhost:5173 (Vite proxy → :8001)

---

## 🎯 核心功能

### Insights 全局筛选栏

Insights 页面顶部提供统一的全局筛选栏，所有子页面共享筛选上下文：

| 筛选项 | 说明 |
|--------|------|
| **Date Range** | 预设 7d/14d/28d 或自定义日期范围 |
| **Interval** | daily / weekly / monthly |
| **Topics** | 多选 Topic 筛选 |
| **Platforms** | 多选平台筛选 |
| **Prompt Type** | 多选 Intent 类型 (Visibility / Sentiment) |
| **Reset** | 重置所有筛选条件 |

`Prompt Type` 筛选逻辑：
1. 查询 `geo_global_intents` 表，找到 `categories` 字段包含所选类型的 Intent
2. 用这些 Intent 的 `intent_name` 筛选 `geo_client_prompts`
3. 通过 `client_prompt_id` JOIN 到最终数据表 (Citations / Visibility 等)

### 1. Prompt Editor (`/prompt-editor`)

- **Topic 侧边栏**: 左侧展示 Topic/Product 树形结构，支持筛选与新增
- **Inline 编辑**: 双击任一字段即可编辑 (Text/Topic/Product/Country/Language/Platform/Intent)
- **批量操作**: 选中多行后，底部悬浮操作栏提供 Duplicate/Disable/Delete/Edit Countries/Edit Platforms
- **3-dot 菜单**: 每行右侧提供 Duplicate/Pause/Delete 操作
- **AI Brainstorming**: 点击 Generate 按钮可通过 Gemini AI 批量生成 Prompt 候选

### 2. Insights

#### Visibility (`/insights/visibility`)
- **Summary 卡片**: Visibility Score, Rank, Total Mentions
- **SOV 排名**: 品牌 Share of Voice 排名 (Top 15)
- **时序图**: 品牌可见性趋势 (支持 daily/weekly/monthly 切换)
- **竞品对比**: 多品牌时序对比

#### Citations (`/insights/citations`)
- **Summary 卡片**: Total Citations, Own Domain Share
- **域名排名**: 引用源域名排名 (Top 20)
- **时序图**: 域名引用趋势
- **Prompt Type 筛选**: 通过全局筛选栏的 Prompt Type 按 Visibility/Sentiment 类型过滤数据

#### Prompts (`/insights/prompts`)
- **分组视图**: 支持按 Topic/Product/Country 分组查看
- **指标列**: Rank/Score/Avg Position/Citations
- **下钻分析**: 点击分组条目进入 Visibility + Citations 下钻面板

### 3. Settings (`/settings`)

- **Peers 管理**: 配置竞品品牌 (含别名)
- **Domains 管理**: 配置品牌官网域名
- **平台/国家/语言**: 按客户配置可用选项
- **Schedule & Execution**: 定时任务配置 (Cron)

### 4. AI Concept Brainstorming

- 基于 Topics/Products 级联多选
- 支持 Countries/Languages/Platforms 多选筛选
- 调用 Gemini AI 生成 Prompt 候选池
- 支持勾选并一键保存至 Prompt 库

---

## 📡 API 端点

### Insights
| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/insights/visibility` | 品牌可见性 (SOV + 时序 + 竞品) |
| GET | `/api/insights/citations` | 引用来源 (域名排名 + 时序), 支持 `prompt_type` 参数 |
| GET | `/api/insights/cited-domains` | 最常引用域名 ranking，支持分页与全量搜索 |
| GET | `/api/insights/cited-pages` | 最常引用页面 ranking，支持分页与全量搜索 |
| GET | `/api/insights/fanouts` | Query Fanout 列表 (分页) |
| GET | `/api/insights/prompts/metrics` | Prompt 级聚合指标 |

### Prompts
| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/prompts` | Prompt 列表 |
| POST | `/api/prompts` | 创建 Prompt |
| PUT | `/api/prompts/{id}` | 更新 Prompt |
| DELETE | `/api/prompts/{id}` | 删除 Prompt |
| POST | `/api/prompts/batch` | 批量创建 |

### 品牌设置
| Method | Path | 说明 |
|--------|------|------|
| GET/POST | `/api/settings/peers` | Peers 管理 |
| GET/POST | `/api/settings/domains` | Domains 管理 |
| GET/POST | `/api/settings/topics` | Topics 管理 |
| GET/POST | `/api/settings/personas` | Personas 管理 |
| GET | `/api/settings/info` | 客户配置信息 |

### 其他
| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/brainstorming/generate` | AI 生成 Prompt 候选 |
| GET | `/api/clients` | 客户列表 (含 Topics) |
| GET | `/api/intents` | 全局 Intent 列表 |
| GET | `/api/platforms` | 全局平台列表 |
| GET | `/api/languages` | 全局语言列表 |

---

## 🛠️ 技术栈

| 类别 | 技术选型 |
|------|----------|
| **后端** | FastAPI + asyncpg |
| **前端** | React 18 + TypeScript + Vite |
| **UI 组件** | shadcn/ui + Tailwind CSS |
| **图表** | Recharts |
| **状态管理** | React Context |
| **AI/LLM** | Vertex AI Gemini (Brainstorming) |
| **部署** | Docker + Cloud Run + Terraform |

---

## ☁️ 云端部署

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"

# 构建 API 镜像
gcloud builds submit ./src \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/geo-saas-repo/geo-saas-api:v41

# 构建 Web 镜像
gcloud builds submit ./web \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/geo-saas-repo/geo-saas-web:v56

# Terraform 部署
cd terraform && terraform init && terraform apply
```

---
*Last Updated: 2026-05-24*
