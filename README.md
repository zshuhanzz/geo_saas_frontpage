# AnswerX GEO

<p align="center">
  <img src="logo.png" alt="AnswerX Logo" width="120" />
</p>

<p align="center">
  <strong>高吞吐量 · 异步 · 事件驱动</strong><br>
  <em>Generative Engine Optimization (GEO) 数据采集与分析平台</em>
</p>

---

## 🎯 项目愿景

随着 AI 搜索引擎（ChatGPT, Gemini, AI Mode 等）逐渐成为用户获取信息的主要入口，品牌在这些平台上的"**可见性**"变得至关重要。

**AnswerX GEO** 致力于解决一个核心问题：

> *"当用户向 AI 提问时，你的品牌是否被推荐？在什么场景下被提及？竞品表现如何？"*

通过大规模采集 AI 引擎的回答数据，AnswerX GEO 帮助企业：
- 📊 **监测品牌可见性** — 追踪品牌在 AI 回答中的出现频率与位置
- 🔍 **分析竞争格局** — 对比竞品在不同场景下的表现
- 📈 **优化内容策略** — 基于数据洞察指导 SEO/GEO 优化方向

---

## 🏗️ 系统架构 (V2 SaaS)

> **当前版本**: Collector v27 / Admin API v35 + Web v50 / Analyzer v23 / SaaS API v41 + Web v56 / Agent v28 (2026-05-24)
>
> **2026-04-26 Phase 1-8 大重构**：抽出 [`geo_common/`](geo_common/README.md) 共享基础层（`BaseConfig` / `asyncpg pool` / `@tenant_scoped` / `Repository` 基类），全模块拆除 `databases` 库 + sync SQLAlchemy，统一为 raw asyncpg；前端引入 `openapi-typescript` 自动生成 API 类型（详见 [docs/openapi-codegen.md](docs/openapi-codegen.md)）。
>
> **2026-04-27 Anthony Chat 数据驱动改造**：chat 引导步骤从硬编码改为读 `geo_workflow_config` 表，与 admin Wizard UI 对齐（详见 [WIZARD_ALIGNMENT_PLAN.md](WIZARD_ALIGNMENT_PLAN.md)）。
>
> **2026-05-24 Citation-grounded Content Generation**：内容 Agent 新增 Citation Analysis preflight、Reddit / Official Website AI Citable 模板、Quality Gate + 最多两轮 Revise + post-revision recheck。Citation 页面新增“最常引用域名 / 页面”的分页与全量搜索，支持从 citation data 反推 AI 可引用内容策略。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          GEO SaaS Web (客户端)                              │
│              React + TypeScript + shadcn/ui + Recharts + Vite               │
│    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│    │ Prompt Editor│  │   Insights   │  │   Settings   │  │ Brainstorming│  │
│    │              │  │ Visibility   │  │              │  │              │  │
│    │              │  │ Citations    │  │              │  │              │  │
│    │              │  │ Prompts 下钻 │  │              │  │              │  │
│    │              │  │ Fanouts      │  │              │  │              │  │
│    │              │  ├──────────────┤  │              │  │              │  │
│    │              │  │全局筛选栏:    │  │              │  │              │  │
│    │              │  │ Date/Topic/  │  │              │  │              │  │
│    │              │  │ Platform/    │  │              │  │              │  │
│    │              │  │ Prompt Type  │  │              │  │              │  │
│    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
└───────────┴─────────────────┴─────────────────┴─────────────────┴──────────┘
                                    │ REST API
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          GEO SaaS API (FastAPI)                             │
│    ┌───────────────────────┐  ┌───────────────┐  ┌───────────────────────┐  │
│    │ insights/             │  │   prompts     │  │   brainstorming       │  │
│    │  ├── visibility.py    │  │               │  │                       │  │
│    │  ├── citations.py     │  ├───────────────┤  ├───────────────────────┤  │
│    │  ├── fanouts.py       │  │   settings    │  │   globals.py          │  │
│    │  └── prompt_metrics.py│  │               │  │  (intents/platforms/  │  │
│    └───────────────────────┘  └───────────────┘  │   languages)          │  │
│                                                  └───────────────────────┘  │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ READ / WRITE
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PostgreSQL (Cloud SQL)                                │
│                                                                             │
│  ┌─────────────┐  ┌─────────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ geo_clients │  │geo_client_topics│  │geo_client_   │  │ geo_global_  │  │
│  │             │  │  (+ products)   │  │  prompts     │  │  platforms   │  │
│  └──────┬──────┘  └────────┬────────┘  └──────┬───────┘  │  languages   │  │
│         │                  │                   │          │  intents     │  │
│         └──────────────────┴───────────────────┘          └──────────────┘  │
│                            │                                                │
│                   ┌────────┴────────┐                                       │
│                   │   geo_tasks     │ (Query Fanouts)                       │
│                   └────────┬────────┘                                       │
│                   ┌────────┴────────┐                                       │
│                   │  geo_results    │ (原始 AI 采集结果)                     │
│                   └────────┬────────┘                                       │
│           ┌────────────────┴────────────────┐                               │
│           │  geo_brand_mentions *            │ (v1.2: 原 geo_company_mentions)│
│           │  geo_product_mentions *          │ (v1.2 新: own/shadow/peer)   │
│           │  geo_citations                  │ (Analyzer 产出)               │
│           │  geo_client_brands *             │ (v1.2 新: Own + Shadow)      │
│           │  geo_client_topic_products *     │ (v1.2 新: product role 分类) │
│           │  geo_product_tracked_urls *      │ (v1.2 新: URL → product 映射)│
│           │  geo_client_domains             │ (brand_id / peer_id 归属)    │
│           │  geo_product_sales_channels *    │ (v1.2 新: OEM 销售渠道声明)  │
│           │  geo_domain_categories          │ (域名分类映射)               │
│           │  geo_settings_candidates *       │ (AI 自动发现候选, Phase 6)   │
│           │  geo_sentiment_results +themes  │ (情感分析 + 主题归一化)       │
│           │  geo_analysis_metrics           │ (NL2SQL metric 字典)          │
│           │  geo_workflow_config            │ (wizard 配置驱动)             │
│           └─────────────────────────────────┘                               │
│           * 标记为 v1.2 新增或改名(Dual-Mode Tracking for OEM/ODM)          │
└──────────────────────┬──────────────────────────────────────────────────────┘
                       │ READ / WRITE
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐     ┌──────────────────┐
│  GEO Collector   │     │  GEO Analyzer    │
│   Pipeline       │     │  (Cloud Run Job) │
│                  │     │                  │
│ ┌──────────────┐ │     │ ┌──────────────┐ │
│ │Prompt Expand │ │     │ │Context Loader│ │
│ │  (Gemini AI) │ │     │ │ Peers+Domain │ │
│ └──────┬───────┘ │     │ └──────┬───────┘ │
│        ▼         │     │        ▼         │
│ ┌──────────────┐ │     │ ┌──────────────┐ │
│ │Cloro Dispatch│ │     │ │ Batch Reader │ │
│ │  (API calls) │ │     │ │ (100条/批)   │ │
│ └──────┬───────┘ │     │ └──────┬───────┘ │
│        ▼         │     │        ▼         │
│ ┌──────────────┐ │     │ ┌──────────────┐ │
│ │Callback +    │ │     │ │BrandParser   │ │
│ │Pub/Sub +     │ │     │ │CitationParser│ │
│ │Ingestor      │ │     │ └──────┬───────┘ │
│ └──────────────┘ │     │        ▼         │
│                  │     │  Mentions +      │
│                  │     │  Citations       │
└──────────────────┘     └──────────────────┘

                    ┌──────────────────┐      ┌──────────────────────────┐
                    │  GEO Admin       │      │  GEO Agent               │
                    │  (内部管理后台)   │      │  (Anthony AI 助手)        │
                    │                  │      │                          │
                    │ 客户/Topic 管理   │      │ LangGraph Multi-agent    │
                    │ 全局配置管理      │      │ Supervisor→Analyze/      │
                    │ Job 触发 & 调度   │      │   Action/Chat sub-graphs │
                    │ 任务监控 (Tasks) │      │ Wizard 驱动 Analysis +   │
                    │  服务端排序     │      │   Content Generation     │
                    │  冻结列布局     │      │ Citation Analysis +      │
                    │ 分析结果查看      │      │   Quality Gate / Revise  │
                    │                  │      │ SSE 流式 + PG checkpoint │
                    │                  │      │ (v1.2+) Mode Gate + RAFT │
                    └──────────────────┘      └──────────────────────────┘
```

---

## 💡 设计理念

### 1. ELT 优先 (Extract-Load-Transform)

```
先抓取 → 原样存储 → 后解析
```

采集阶段只负责"搬运数据"，将 AI 引擎的原始 JSON 响应完整存储。解析和分析作为独立阶段，支持后续迭代优化而无需重新采集。

### 2. 事件驱动 + 削峰填谷

```
Pub/Sub 解耦 → 异步处理 → 自动扩缩容
```

通过 Google Cloud Pub/Sub 实现组件间解耦，避免数据库过载，支持 Cloud Run 弹性伸缩。

### 3. 策略模式 (Strategy Pattern)

```
多平台适配 → 动态选择解包器 → 统一输出格式
```

针对 ChatGPT、Gemini、Perplexity 等不同平台的响应结构，采用策略模式进行 JSON 解包，新增平台只需添加新策略类。

### 4. SaaS 多租户数据模型 (V2)

```
Client (租户) → Topic (主题分组) → Client Prompt (Prompt Editor 池) → Task (Query Fanout) → Result (采集结果)
                  1:N                       1:N                            1:N                    1:M
```

以 `Client` 为租户根节点，通过 `Topic` 组织 Prompt，Prompt Expander 将用户配置的 Prompt 扩展为多条  `Task` (Query Fanout)，每条 Task 可被调用 M 次生成 `Result`。

### 5. 模块化解析器与数据提取

针对 "引用来源分析 (Citations)" 与 "内容可见性评估 (Mentions)" 需求，Analyzer 使用两个独立的 Parser：
- **BrandParser** (原 CompanyParser，2026-04 重命名): 基于 Peers 列表（含别名）正则匹配品牌提及位置，标记 `is_own_brand`
- **CitationParser**: 解析 `sources` 和 `citation_pills` 中的 URL，提取域名并匹配 Owned Domains

### 6. 分批处理 & 断点续传 (Batch Processing & Resume)

```
分批读取 (100条/批) → 原子提交 (Commit) → 自动续传 (Resume)
```

针对大规模数据分析任务，Analyzer 采用分批处理模式。每批处理完成后立即 commit，若任务被中断，重启后自动从上次中断处继续。

---

## 📦 项目结构

```
GEO_Demo/
│
├── geo_common/             # 🧱 共享基础层 (Phase 2 抽出, 不部署 — pip install -e)
│   └── src/geo_common/
│       ├── config/         # BaseConfig (Pydantic v2 Settings 基类, DB_*/GCP_* 字段)
│       ├── db/             # create_asyncpg_pool() + @tenant_scoped 装饰器
│       └── services/       # BaseRepository + 8 个 Repository
│                           #   (Brand / Topic / TopicProduct / Peer /
│                           #    Domain / Persona / Prompt / Client)
│
├── geo_collector/          # 🔧 数据采集引擎 (asyncpg, alembic 已拆除)
│   ├── src/                # 核心业务代码
│   │   ├── clients/        # 外部服务客户端 (Cloro, Gemini, Pub/Sub)
│   │   ├── services/       # 业务逻辑层 (PromptExpander, Unpackers)
│   │   └── core/           # 配置与数据库 (asyncpg pool)
│   └── terraform/          # GCP 基础设施配置
│
├── geo_analyzer/           # 🧠 数据分析引擎 (async asyncpg, sync SQLAlchemy 已拆除)
│   ├── main.py             # 入口 (批处理循环)
│   ├── src/                # Core Logic
│   │   ├── core/           # 配置 & 数据库 (asyncpg, Pydantic v2)
│   │   └── parsers/        # BrandParser + CitationParser (+ 异步 Gemini)
│   └── terraform/          # Cloud Run Job Config
│
├── geo_admin/              # 🖥️ 内部管理后台
│   ├── src/                # FastAPI 后端 (db.py: :name → $N shim 适配 asyncpg)
│   │   ├── routers/        # 路由模块 (v1.2: LLM Discovery / Workflow Config / 等)
│   │   └── services/       # GCP Scheduler 工具
│   ├── web/                # React + TypeScript + shadcn (v1.2: Clients 3 列 Scheduler)
│   ├── terraform/          # Cloud Run 部署配置
│   └── tests/              # pytest (含 db_adapter 回归测试: ::TYPE cast lookbehind)
│
├── geo_agent/              # 🤖 Anthony AI 助手 (v1.2 独立模块, 数据驱动 chat)
│   ├── src/                # FastAPI + SSE + LangGraph 多 agent
│   │   ├── routers/        # tasks (metrics discovery / preselect / ranked 等)
│   │   ├── pipelines/      # analysis_pipeline.py + content_pipeline.py
│   │   ├── graphs/         # Supervisor / Analyze / Action / Chat sub-graphs
│   │   ├── services/       # workflow_config.py — wizard-aligned slot-fill engine
│   │   ├── context/        # message pruner (LLM 调用点裁剪)
│   │   └── tools/          # @tool 原子工具
│   ├── sql/                # Agent state migrations (AsyncPostgresSaver)
│   └── terraform/          # 独立 Cloud Run service
│
├── geo_saas/               # 🌐 客户 SaaS 平台
│   ├── src/                # FastAPI 后端 (db.py: :name → $N shim 适配 asyncpg)
│   │   └── routers/        # API 路由
│   │       ├── insights/   # 拆分式子模块 (v1.2: citation_role / product_visibility /
│   │       │               #   shadow_cooccurrence)
│   │       ├── onboarding/ # Auto-discovery + Onboarding Wizard (v1.2)
│   │       ├── globals.py  # 合并全局字典 Router
│   │       └── ...         # prompts / settings / brainstorming / clients
│   ├── web/                # React + TypeScript + shadcn/ui + Recharts (Vite)
│   │   └── src/
│   │       ├── pages/agents/         # Analyze / Content / Chat (Wizard-driven)
│   │       ├── components/agents/    # ChatWidgetRenderer (16 widget 类型)
│   │       ├── components/wizard/    # Schema-driven wizard shell + custom fields
│   │       ├── pages/insights/       # Visibility / Citations / Sentiment
│   │       └── i18n/locales/{zh-CN,en-US}/  # 双语 namespace JSON
│   └── terraform/          # Cloud Run 部署配置
│
├── migrations/             # PostgreSQL 迁移脚本 (000-091 + consolidated_v1.2/)
├── docs/                   # roadmap / SCHEMA / openapi-codegen / local-dev / specs
│   ├── roadmap.md          # Phase 1-8 真相源 + backlog
│   ├── SCHEMA.md           # migrations 管理规范 (禁止 terraform 写 DDL / 禁止跳号)
│   ├── content-generation-quality-playbook.md # 内容生成质量评估 playbook
│   ├── local-dev/codex-visible-e2e.md # Codex 可视化 E2E 测试指南
│   └── openapi-codegen.md  # backend openapi.json → frontend .d.ts 自动化流程
├── WIZARD_ALIGNMENT_PLAN.md # Anthony Chat 数据驱动改造的 plan + 端到端验证报告
├── deploy_all.sh           # 🚀 全量部署脚本 (改顶部 VERSION 变量, 自动 sync tfvars)
└── deploy_iteration.sh     # 🚀 迭代部署脚本 (仅变更的模块)
```

---

## 🧱 共享基础层 (geo_common)

`geo_common/` 是**纯 Python 源码包**，不部署成 Cloud Run image —— 各模块的 Dockerfile 把 `geo_common/` 拷进镜像后 `pip install -e ../geo_common`。

| 子包 | 作用 |
|---|---|
| `geo_common.config.BaseConfig` | Pydantic v2 Settings 基类，统一 `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `DB_NAME` / `GCP_PROJECT_ID` / `GCP_REGION` 等环境变量约定，提供 `build_database_url()` |
| `geo_common.db.create_asyncpg_pool` | 标准化 asyncpg pool 构造（替代各模块手写） |
| `geo_common.db.tenant_scoped` | `@tenant_scoped` 装饰器 — **P0 多租户隔离的最后防线**。检测 `client_id` 参数（含 instance method 路径），强制非空 + 长度 >= 8。所有 8 个 Repository 的 tenant-scoped 方法都装饰它 |
| `geo_common.services.BaseRepository` | Repository 基类。子类拥有 SQL，路由层组合 Repository。Routers 不直接写 SQL |

详见 [geo_common/README.md](geo_common/README.md)。

---

## 🗄️ DB Migrations 管理

PostgreSQL schema 变更 100% 走 [migrations/](migrations/) 下编号 SQL 文件。**绝不直接执行 DDL** —— 即使 Cloud SQL 也通过 migration file。

- 当前最新 **091**（`091_template_specific_revision_guidance.sql` — 将 Reddit / 官网模板的两轮 Revise 重点迁移到 `geo_report_templates.wizard_config.quality_gate.revision_guidance`，由模板配置动态注入）
- **Terraform 不写 DDL** — schema 演进与基础设施分离
- 详细规范见 [docs/SCHEMA.md](docs/SCHEMA.md)

---

## 🔧 OpenAPI Codegen（前端类型）

`geo_saas/web` + `geo_admin/web` 用 **`openapi-typescript`** 从 backend `/openapi.json` 自动生成 TS 类型定义文件，避免手写 interface 与后端漂移。完整流程 + 触发节奏见 [docs/openapi-codegen.md](docs/openapi-codegen.md)。

---

## 🧩 核心组件

| 组件 | 类型 | 职责 |
|------|------|------|
| **Prompt Expander** | Cloud Run Job | 读取 Client Prompts，调用 Gemini 生成 Query Fanout |
| **Cloro Dispatcher** | Cloud Run Job | 将 Task 发送至 Cloro API，触发 AI 引擎采集 |
| **Cloro Callback** | Cloud Run Service | 接收 Cloro 异步回调，推送至 Pub/Sub |
| **Result Ingestor** | Cloud Run Service | 消费 Pub/Sub 消息，解包并入库 |
| **GEO Analyzer** | Cloud Run Job | 批处理分析引擎，提取 Mentions / Citations |
| **GEO Admin API** | Cloud Run Service | 内部管理 REST API (服务端排序/分页) |
| **GEO Admin Web** | Cloud Run Service | 内部管理 UI (客户管理 / 全局配置 / Job 触发 / 任务监控) |
| **GEO SaaS API** | Cloud Run Service | 客户端 SaaS REST API (Insights / Prompts / Settings / Auto-Discovery) |
| **GEO SaaS Web** | Cloud Run Service | 客户端 SaaS UI (Insights + Prompt Type 筛选 / Prompt Editor / Wizard) |
| **GEO Agent API** | Cloud Run Service | Anthony 多 agent (Supervisor / Analyze / Action / Chat)，Wizard 驱动 Analysis / Content Generation，SSE 流式输出 (v1.2) |
| **LLM Batch Discovery Job** | Cloud Run Job | 周期性扫 geo_results，基于 Gemini 合成 Brand/Shadow/Peer/Product 候选写 `geo_settings_candidates`，UI "AI 建议"面板展示 (v1.2 Phase 6) |
| **N-gram Discovery Job** | Cloud Run Job | 互补的统计型候选发现，不依赖 LLM (v1.2 Phase 6) |

---

## 🔀 v1.2 Dual-Mode Tracking (OEM/ODM 支持, 2026-04)

v1.2 大迭代解决**自有品牌出海(如 Dreame)** vs **OEM/ODM(如杭州天铭→贴 Rough Country 销售)**的双模追踪需求。核心架构增量:

### 数据模型
- **Brand 角色分化**: `geo_client_brands.is_shadow` 标记 shadow 品牌 (渠道品牌)。新增 `geo_client_topic_products.product_role ∈ {own, shadow_brand_product, peer}` + `shadow_sub_role ∈ {native, resale, NULL}`。
- **URL-level tracking**: 新表 `geo_product_tracked_urls` (exact / path-prefix 两阶段匹配) + `geo_product_sales_channels` (声明 "这个 own 产品也通过这个 shadow brand 销售")。
- **Citation role 12 值 + 未分类**: `geo_citations.citation_role` 12 桶 + NULL (Dashboard + 模板显示为 `unclassified`)。

### 功能
- **Onboarding Wizard**: 自有品牌 / OEM 分叉引导；自动发现从 robots.txt/sitemap/nav 爬取话题 + 产品。
- **用户可提供 seed URLs**(v2-late): 列表页/类目页 URL 由 Layer 0 HTTP 抓取真实 anchor 产品，**bypass LLM 防幻觉**，URL 原样返回。
- **Wizard schema-driven**: workflow_step / content_metric / content_sub_goal / sort_option 字典表驱动，前端 `FieldRenderer` + 9 个 custom fields (ModeGate / TopicRef / PromptRef / AnalyzerImport / ChartBuilder / PromptEditor / PeerPicker / ProductFacts / StrategyGenerator)。
- **Content Generation Mode Gate (B-3)**: 用户选"我来定"/"AI 帮我发现"，后者调用 `/content/preselect` 自动预填 topic + prompts + content_type + publish_platform + sub_goals(继承模板)。
- **Analysis Template: 渠道表现分析**: OEM-only (`has_shadow_brands=true` 可见)。四指标: product_sov_own / citation_by_citation_role / shadow_cooccurrence_own_product / shadow_cooccurrence_peer_product。
- **RAFT 四象限全选**: Readability / Answerability / Trustworthy / Freshness + 9 sub-goals，所有 content 模板默认全选 (migration 054)。

### Migrations
v1.2 累计 040-054 + 046b 共 16 个 SQL 文件。已整合到 `migrations/consolidated_v1.2/{part1,part2,part3}.sql` 三个文件，配合 `docs/superpowers/plans/progress/DEPLOY_PLAYBOOK_v1.2.md` 执行。详细设计见 [specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md](docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md)。

---

## 🧠 Citation-Grounded Content Generation (2026-05)

2026-05 迭代将内容生成从“模板驱动”升级为“Citation data + 模板配置 + Quality Gate 闭环”驱动，目标是生成更容易被 AI 引用、同时适合目标平台发布的 GEO 内容。

### 新增模板

| 模板 | 目标平台 | 设计目标 |
|---|---|---|
| `Reddit AI Citable Post Generator` | Reddit | 学习已被 AI 引用的 Reddit 讨论结构，补足客户品牌缺席，同时保持社区原生、非硬广、可讨论 |
| `Official Website AI Citable Article` | 官网 | 学习已被 AI 引用的官网/第三方页面结构，生成可发布、可抽取、可转化的官网长文 |

存量 `Reddit Article`、`Reddit Insight then Generate`、`Official Website Insight then Generate` 继续保留，并支持可配置的 Citation Analysis 节点。新增模板默认开启 Citation Analysis；存量模板可按 Wizard Stack 配置启用。

### Citation Analysis Preflight

Content Wizard 可在生成前运行 Citation Analysis，基于 `geo_citations` 与 citation page 内容产出：

- Brand Mention Triage：未提及、正面/中立、负面/误导、模糊提及
- Content Action Decision：例如 `new_content_gap`、`refresh_existing_asset`、`clarification_or_rebuttal`
- Citation Grounded Brief：作为策略生成和正文生成的 source of truth
- Why AI likely cites these sources：学习已被 AI 引用来源的结构优势
- Gaps to fill for customer GEO visibility：补齐客户品牌、事实边界、对比信息或 FAQ 缺口
- Fetch status：显示来源抓取质量，Reddit 当前已支持 `.json?raw_json=1` / `api.reddit.com` / `old.reddit.com` fallback

### Quality Gate + Revise Loop

内容 pipeline 当前执行语义为 8 步：

1. Citation Analysis
2. Strategy Generation
3. Content Generation
4. Quality Gate
5. 第一轮 Revise
6. 修订后复查
7. 第二轮 Revise
8. 第二轮后复查

Quality Gate 会检查低分、重复 FAQ、重复 Conclusion、残缺句、结构性错误、品牌密度、Citation Alignment、平台适配等问题。Revise 后，旧 review 存入 `pre_revision_quality_review`，最终 `quality_review` 对应修订后的内容；未执行的第二轮步骤显示为 `skipped`。

Reddit / 官网使用同一套 Gate/Revise 引擎，但规则、阈值、阻断项和两轮修订重点从模板配置动态注入，具体配置位于 `geo_report_templates.wizard_config.quality_gate`。

### Citation Ranking UI

SaaS Citation Insights 中“被引用最多的域名”和“被引用最多的页面”已支持：

- 后端分页，每页最多 50 条
- 搜索范围覆盖全量分页结果，而不是仅当前页
- 域名聚合排名与页面级排名分开：域名排名按 domain aggregate，页面排名按 URL aggregate

这解决了 YouTube、LinkedIn 等域名在 Top domains 中靠前，但单个页面可能排到 Top pages 50 名之外而搜不到的问题。

---

## 🛠️ 技术栈

| 类别 | 技术选型 |
|------|----------|
| **后端语言** | Python 3.11+ |
| **Web 框架** | FastAPI |
| **前端框架** | React 18 + Vite + TypeScript |
| **UI 组件** | shadcn/ui + Tailwind CSS |
| **图表可视化** | Recharts |
| **数据库** | PostgreSQL 15+ (Google Cloud SQL) |
| **消息队列** | Google Cloud Pub/Sub |
| **AI/LLM** | Vertex AI Gemini (Prompt 生成 & Brainstorming & Agent 多 sub-graph) |
| **Agent 框架** | LangGraph 0.2+ (Sub-graph 多 agent 模式) + AsyncPostgresSaver (checkpoint) |
| **SSE 流式** | FastAPI + StreamingResponse (geo_agent / onboarding auto-discover) |
| **采集服务** | Cloro.dev API |
| **容器化** | Docker (多阶段构建) |
| **基础设施** | Terraform + Cloud Run |
| **认证** | Google OAuth 2.0 登录 + 数据库可撤销 HttpOnly Session（SaaS/Agent 24h，Admin 12h） |

---

## 🚀 快速开始(本地开发)

### 0. 先起 Cloud SQL Auth Proxy(所有后端服务依赖)

所有后端服务通过 **Cloud SQL Auth Proxy** 连 Cloud SQL。proxy 要独立一个 terminal 跑,**服务启动前必须保证它已在 5432 端口监听**。

```bash
# 在 ~ 目录执行(binary 位置:/Users/lancelot/cloud-sql-proxy)
cd ~
./cloud-sql-proxy project-90d7849c-de16-4c15-a0a:us-central1:answer-x-geo-instance --port=5432
```

> 如果你想用**本地 Postgres 而不是 Cloud SQL**(例如跑 v1.2 migration 验证),跳过这一步,改为参考 [docs/local-dev/claude-ports.md](docs/local-dev/claude-ports.md) 搭本地 pg18(5433)。然后在各服务 `.env.local` 里把 `DATABASE_URL` 的 `@localhost:5432` 改成 `@localhost:5433`(文件里有 `[默认]` 和 `[切换]` 两行注释,二选一)。

### 1. 各服务 env 配置

首次 clone 或拉代码后,需要在每个模块创建 `.env.local`(git-ignored):

```bash
# 模板参考 .env.example(若存在),或照 docs/local-dev/claude-ports.md 里的样板
# 已有对照矩阵:geo_saas/src、geo_admin/src、geo_agent/src、geo_analyzer、
#   geo_saas/web、geo_admin/web — 共 6 个模块
```

### 2. GEO Admin(内部管理后台)

```bash
# 启动 API(端口 8000)
cd geo_admin/src
python3 -m venv venv && source venv/bin/activate   # 首次
pip install -r requirements.txt                      # 首次
uvicorn main:app --reload --port 8000 --env-file .env.local

# 启动 Web(端口 5174)
cd geo_admin/web
npm install    # 首次
npm run dev
```

### 3. GEO SaaS(客户 SaaS 平台)

```bash
# 启动 API(端口 8001)
cd geo_saas/src
python3 -m venv venv && source venv/bin/activate   # 首次
pip install -r requirements.txt                      # 首次
uvicorn main:app --reload --port 8001 --env-file .env.local

# 启动 Web(端口 5173)
cd geo_saas/web
npm install    # 首次
npm run dev
```

### 4. GEO Agent(Anthony AI 助手)

```bash
# 启动 API(端口 8002)
cd geo_agent/src
python3 -m venv venv && source venv/bin/activate   # 首次
pip install -r requirements.txt                      # 首次
uvicorn main:app --reload --port 8002 --env-file .env.local
```

### 5. GEO Analyzer(批处理分析 Job,按需运行)

```bash
cd geo_analyzer
python3 -m venv venv && source venv/bin/activate   # 首次
pip install -r requirements.txt                      # 首次

# 加载 env 后跑
set -a; source .env.local; set +a
CLIENT_ID=<your-client-uuid> python main.py
```

### 6. GEO Collector(数据采集 Job)

```bash
cd geo_collector
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Collector 依赖 Cloro 异步回调,本地不易验证,以 GCP 部署后验证为主
# 详细说明见 geo_collector/README.md
```

### 🔄 本地 / Cloud SQL 切换

每个后端服务的 `.env.local` 里都有这样的注释块:

```bash
# [默认] Cloud SQL via Auth Proxy(需先跑 0 步的 proxy 命令)
DATABASE_URL=postgresql+asyncpg://.../localhost:5432/answer-x-geo-db

# [切换] 本地 Postgres(5433,见 docs/local-dev/claude-ports.md)
# DATABASE_URL=postgresql+asyncpg://.../localhost:5433/answer-x-geo-db
```

切换时**两行对换注释**,重启服务即可。`geo_analyzer` 是改 `DB_PORT=5432 ↔ 5433`。

### 📋 端口总览（Two-Stack Protocol）

本机有两套**互不干扰**的本地栈：用户栈跑 `.env.local`，Claude 自动化栈跑 `.env.claude.local`（Claude 端口 = 用户端口 + 1000 offset）。**让 Claude 启动服务前必须先确认是哪一套**。

| 服务 | 用户栈（`.env.local`） | Claude 栈（`.env.claude.local`） |
|---|---|---|
| Cloud SQL Auth Proxy | 5432 | — |
| 本地 Postgres（可选） | — | **5433** |
| geo_admin/src | 8000 | 9000 |
| geo_saas/src | 8001 | 9001 |
| geo_agent/src | 8002 | 9002 |
| geo_admin/web | 5174 | 6174 |
| geo_saas/web | 5173 | 6173 |

完整协议（DB 切换、auth bypass、prod blast-radius guard 等）见 [docs/local-dev/claude-ports.md](docs/local-dev/claude-ports.md)。

### Codex 可视化 E2E 端口

Codex 本地可视化浏览器 E2E 使用独立约定：Admin UI `6173`，SaaS UI `6174`，SaaS API `9101`，Agent API `9102`。测试账号使用 `gotyechen@gmail.com`，详细流程见 [docs/local-dev/codex-visible-e2e.md](docs/local-dev/codex-visible-e2e.md)。

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [geo_common/README.md](geo_common/README.md) | 共享基础层（BaseConfig / asyncpg pool / @tenant_scoped / Repository） |
| [geo_collector/README.md](geo_collector/README.md) | Collector 架构设计与快速开始 |
| [geo_collector/DEPLOY.md](geo_collector/DEPLOY.md) | GCP 部署完整指南 |
| [geo_admin/README.md](geo_admin/README.md) | Admin 本地开发与云端部署 |
| [geo_analyzer/README.md](geo_analyzer/README.md) | Analyzer 架构与本地运行 |
| [geo_saas/README.md](geo_saas/README.md) | SaaS 平台功能与 API 文档 |
| [geo_agent/README.md](geo_agent/README.md) | Anthony AI 助手: LangGraph 多 agent + Wizard 驱动 Analysis/Content |
| [WIZARD_ALIGNMENT_PLAN.md](WIZARD_ALIGNMENT_PLAN.md) | Anthony Chat 数据驱动改造（Wizard Phase A-G）plan + 端到端验证 |
| [docs/roadmap.md](docs/roadmap.md) | 全局 roadmap 真相源（Phase 1-8 重构 + backlog） |
| [docs/SCHEMA.md](docs/SCHEMA.md) | migrations 管理规范（禁止 terraform DDL / 禁止跳号） |
| [docs/openapi-codegen.md](docs/openapi-codegen.md) | backend openapi.json → frontend `.d.ts` 自动化流程 |
| [docs/local-dev/codex-visible-e2e.md](docs/local-dev/codex-visible-e2e.md) | Codex 可视化 E2E 测试指南（6173/6174 端口、内容 Agent 测试流程） |
| [docs/content-generation-quality-playbook.md](docs/content-generation-quality-playbook.md) | 内容生成质量评估基准（Citation / Quality Gate / Revise / Reddit / 官网文章评价） |
| [docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md](docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md) | v1.2 Dual-Mode Tracking 权威 Spec (OEM/ODM) |
| [docs/superpowers/plans/progress/DEPLOY_PLAYBOOK_v1.2.md](docs/superpowers/plans/progress/DEPLOY_PLAYBOOK_v1.2.md) | v1.2 整迭代 GCP 部署 runbook (migrations + services) |
| [docs/local-dev/claude-ports.md](docs/local-dev/claude-ports.md) | 本地并行开发 port 映射（Two-Stack Protocol）|
| [migrations/consolidated_v1.2/](migrations/consolidated_v1.2/) | v1.2 合并 3 段 SQL (part1 schema+backfill / part2 templates / part3 wizard+accuracy) |

---

## ☁️ 云端部署 (GCP)

**部署铁律**：用 [`deploy_all.sh`](deploy_all.sh)，**只改顶部 `VERSION` 变量**，让脚本自动 sync 各模块 `terraform.tfvars`。**不要手动改 tfvars**。

```bash
# 1. 编辑 deploy_all.sh 顶部，bump 需要发布的模块版本号
$EDITOR deploy_all.sh

# 2. 执行 — 脚本会自动:
#    a) 同步 tfvars 中的 image_tag
#    b) gcloud builds submit (Cloud Build)
#    c) terraform apply (Cloud Run service / job 部署)
./deploy_all.sh

# 3. 查看部署状态
gcloud run services list --filter="geo-" --format="table(name,region,status)"
gcloud run jobs list --filter="geo-" --format="table(name,region,status)"
```

**Schema 变更需先单独跑 migration**（Terraform 不写 DDL）：

```bash
# 通过 Cloud SQL Auth Proxy 连 prod
PGPASSWORD=$PROD_DB_PASS psql -h <PROXY_HOST> -p 5432 \
  -U answer-x-geo-db-user -d answer-x-geo-db \
  -f migrations/<NNN>_<name>.sql
```

> **注意**：
> - 首次部署需要先创建 Artifact Registry 仓库
> - 详细 GCP 部署 runbook：[geo_collector/DEPLOY.md](geo_collector/DEPLOY.md)
> - v1.2 部署 playbook：[docs/superpowers/plans/progress/DEPLOY_PLAYBOOK_v1.2.md](docs/superpowers/plans/progress/DEPLOY_PLAYBOOK_v1.2.md)

---

## 📄 License

Private / Internal Use Only

---

<p align="center">
  <em>最后更新: 2026-05-24 — Citation-grounded Content Generation + Quality Gate / Revise + Citation Ranking Pagination</em>
</p>
