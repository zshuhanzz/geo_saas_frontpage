# AnswerX GEO Platform — Roadmap

> **Purpose**: single source of truth for **future plans and active refactors** only.
> Completed iterations go to `## Completed Log` as brief entries; detailed historical design docs live under `docs/archive/`.
>
> **Owner**: lancelot (CTO)

## Iteration status snapshot (latest first)

| Iteration | Status | Shipped |
|---|---|---|
| **Code Structure Refactor** | 🟡 **In Progress** | Phase 0 + Phase 1 done 2026-04-25 (see §3) |
| **i18n zh-CN / en-US 双语化收尾** | ✅ **Done** | SaaS Web v25 @ 2026-04-25 |
| **v1.2 — Dual-Mode Tracking + Phase 1/2/3** | ✅ **Done** | 2026-04-20 (design doc archived: `docs/archive/v1.2_design_doc.md`) |

## Next-iteration backlog (unprioritized — pick by ROI when starting next session)

**Active Refactor** (details in §3):
- 🟡 **Code Structure Refactor (2026-04-25)** — Phase 0 cleanup + Phase 1-8 (目录统一 / geo_common / 大文件拆分 / services 层 / admin TS / OpenAPI). Phase 0-1 done, Phase 2 in progress.

**Feature Backlog** (details in §1):
- 🔴 **Admin Web TypeScript 迁移 + UI 升级**（全面 TS + shadcn/ui 对齐 SaaS）— 与 §3 Phase 5 捆绑
- 🔴 **geo_agent PG MCP 迁移 + P0 租户隔离测试**（捆绑执行）— 独立 workstream，不在本次 refactor
- 🔶 Vertex AI SDK 迁移（截止 2026-06-24）
- 🔶 Content Generation Quality Loop 强化（Citation Alignment / 二轮 Revise 覆盖 / 人工复核状态）
- 🔶 Agent Context 管理与压缩（P1/P2/P3 分层）
- 🔶 Agent Memory（跨会话记忆）
- 🔶 Evaluation Sub-Agent（质量评审独立 Agent）
- 🔶 Reddit Citation 正文抓取稳定性升级（OAuth API / PRAW fallback）

**Infrastructure**:
- [ ] Cloud SQL → Terraform import（~30 min：写 `google_sql_database_instance` + `terraform import`，当前 drift 记录于 `geo_collector/terraform/cloud_sql_manual_config.md`）

---

## 1. Task Backlog（详细）

> 本章 = 当前待办的详细计划。每条含优先级 / 背景 / 迁移步骤。

### 🔴 Admin Web TypeScript 迁移 + UI 升级

**优先级：** 高（长期维护必需）

**目标：** 将 `geo_admin/web` 从 JSX 全面迁移到 TypeScript (.tsx)，并将 UI 风格全面对标 SaaS，达到商业级 SaaS UI 标准。

涉及文件：`geo_admin/web/src/` 下所有 `.jsx` 文件

**迁移步骤：**
- [ ] 配置 TypeScript（添加 `tsconfig.json`，安装 `typescript` 依赖）
- [ ] 逐页面迁移 `.jsx` → `.tsx`，添加类型定义
- [ ] 对标 SaaS Web 的 shadcn/ui + Tailwind 设计系统
- [ ] 统一组件风格（颜色、排版、动画、响应式布局）
- [ ] 添加 API 响应类型定义（共享 types 目录）

**与 §3 关联：** 此任务作为 §3 Phase 5 执行，与 Code Structure Refactor 捆绑。

---

### 🔴 geo_agent PG MCP 迁移 + P0 租户隔离测试（捆绑执行）

**优先级：** 高（架构一致性 + 安全基线）

**背景：** `geo_agent/src/tools/data_tools.py` 当前手写 `list_tables` / `list_columns` / SQL 执行。这违反"复用现成 harness、不造轮子"的原则。同时 `@tenant_scoped` 虽然作为 P0 red line 但**零测试覆盖**，SQL 注入防护也没有测试验证。

**决策：** 这两件事捆绑执行。原因是 MCP 迁移会改变 tenant 隔离的实现点（从 decorator 包住手写 SQL → wrapper MCP 注入 `client_id` 过滤），现在为老代码写测试会大部分作废。P0 测试直接作为 **MCP 迁移的验收标准**。

**涉及文件：**
- `geo_agent/src/tools/data_tools.py`（替换）
- 新增 wrapper MCP 服务或 DB role-level `SET app.client_id`
- 新增 `geo_agent/tests/test_tenant_isolation.py`、`test_mcp_wrapper_sql_safety.py`、`test_rate_limiter_mounted.py`

**迁移步骤：**
- [ ] 安装 `@modelcontextprotocol/server-postgres`
- [ ] 设计多租户 wrapper：请求前注入 `client_id = $1` 过滤 或 DB 角色层面做
- [ ] 替换 `data_tools.py` 里 `list_tables` / `list_columns` / 执行 SQL 三个函数
- [ ] 更新所有引用（Analyze Agent、Content Agent 模板 pipeline、General Chat NL2SQL）
- [ ] **验收（与迁移同批次）**：
  - [ ] `test_tenant_isolation.py` — 两个 client_id 并发跑所有 tool，确认 0 串扰
  - [ ] `test_mcp_wrapper_sql_safety.py` — prompt injection 测试，确认 non-ALLOWED_TABLES / DDL 被拒绝
  - [ ] `test_rate_limiter_mounted.py` — 现在 `rate_limiter.py` 只 import 没 mount，先确认 mount 状态再测生效

**新项目同步：** AnswerX_employees 项目也走 PG MCP，这次迁移后主仓库与新项目架构对齐。

**与 §3 关联：** 此任务**不在** §3 本次 refactor 范围内，单独作为独立 workstream 推进。

---

### 🔶 Vertex AI SDK 迁移（截止时间：2026年6月24日）

当前项目使用旧版 `vertexai` + `vertexai.generative_models` SDK，Google 已在 2025年6月24日 将其标记为 deprecated，将在 **2026年6月24日** 移除。

**需要迁移到 `google-genai` 统一 SDK**，仍然走 Vertex AI 通道（非开发者免费版）。

涉及文件：
- `geo_collector/src/clients/gemini.py`
- `geo_saas/src/routers/brainstorming.py`

迁移示例：
```python
# 旧方式
import vertexai
from vertexai.generative_models import GenerativeModel
vertexai.init(project="xxx", location="us-central1")
model = GenerativeModel("gemini-3-flash-preview")
response = await model.generate_content_async(...)

# 新方式（同样走 Vertex AI）
from google import genai
client = genai.Client(vertexai=True, project="xxx", location="us-central1")
response = client.models.generate_content(model="gemini-3-flash-preview", contents="...")
```

---

### 🔶 Agent Context 管理与压缩

**优先级：** 中（对话质量和成本控制的关键基础设施）

**现状问题：** 当前 LangGraph checkpointer 存完整 messages 列表，每轮 LLM 调用都传全部历史消息。没有裁剪、没有压缩、没有摘要。Token 成本线性增长，历史中的分析结果/图表 JSON/slot-filling 中间态会干扰 LLM。

#### 层次 1：Message Pruning（消息裁剪）— P1
- [ ] 在 `chat_node`、`analyze` sub-graph、`action` sub-graph 的每个 LLM 调用前加 `prune_messages(messages, max_turns=10)`
- [ ] Checkpoint 仍存完整历史（UI 回显），但发给 LLM 的是裁剪后的
- [ ] 预期效果：降低 token 消耗，避免长对话中历史内容干扰 LLM

#### 层次 2：Sliding Window + Summary（滑动窗口 + 摘要压缩）— P2
- [ ] 消息超过阈值时，用 Gemini Flash 生成一段摘要替代旧消息
- [ ] 最终传给 LLM 的结构：`[System Prompt] + [历史摘要] + [最近 5 轮完整对话] + [当前用户消息]`
- [ ] 参考：Claude Code 的 context 压缩机制
- [ ] 注意：摘要生成本身也消耗 token，需权衡触发频率

#### 层次 3：Gemini Context Caching — P3
- [ ] Gemini API 已支持 Context Caching（`google-genai` SDK 支持），可缓存 system prompt + 早期消息，后续请求只传增量
- [ ] 前提条件：需要 >32k tokens 才能触发缓存，且有存储费用
- [ ] 适用时机：用户量大了、单次对话 context 经常超过 32k tokens 时再考虑

---

### 🔶 Agent Memory（跨会话记忆）

**优先级：** 中（提升用户体验的差异化功能）

**现状问题：** 没有任何跨会话记忆。每个 thread_id 独立，切换 thread 后之前聊的内容不可见。Brand profile 是唯一的"持久化上下文"，但那是用户手动配置的，不是 Agent 自己学习的。

#### 方案 A：Brand Profile 增强（最简单）
- [ ] 把 `geo_brand_profiles` 当作 Memory 载体
- [ ] Agent 在对话中学到的信息（用户偏好、常用分析维度、关注的竞品）写回 JSONB 字段
- 优点：改动极小，已有读写链路
- 缺点：只有品牌维度的记忆，没有用户个人记忆

#### 方案 B：Session Summary 表（推荐，中等复杂度）
- [ ] 新建 `agent_memory` 表（memory_type: preference / insight / session_summary）
- [ ] 每次对话结束时用 Flash 生成一句话摘要存入
- [ ] 新对话开始时拉最近 5 条 memory 注入 system prompt
- SQL 参考：
  ```sql
  CREATE TABLE agent_memory (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      client_id UUID NOT NULL,
      user_id TEXT,
      memory_type TEXT,  -- 'preference' | 'insight' | 'session_summary'
      content TEXT,
      metadata JSONB,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      expires_at TIMESTAMPTZ
  );
  ```

#### 方案 C：RAG-based Memory（复杂，Phase 2+）
- [ ] 用 Embedding + 向量搜索检索相关记忆
- [ ] 前提条件：引入 pgvector 或外部向量服务
- [ ] 适用时机：记忆条数多到关键词/时间排序不够用时

---

### 🔶 Evaluation Sub-Agent（质量评审独立 Agent）

**优先级：** 中（demo 后迭代，但架构现在预留）

**灵感来源：** Agentic Reporting 产品案例——在多 Agent 架构中引入独立的 Evaluation Sub-Agent，作为客观第三方以 fresh eyes 视角评审生成结果。

**现状问题：** 当前 Content Generation 和 Analysis 两个 pipeline 各自有一个质量评审 step，但评审逻辑是同一个 pipeline 内的顺序步骤，存在 self-serving bias（生成者自评倾向宽容），且两个 pipeline 的评审逻辑各写一份，无法复用。

#### 核心设计：生成者与评审者关注点分离

| 维度 | 当前设计（Pipeline Step） | Evaluation Sub-Agent |
|------|--------------------------|---------------------|
| 调用方式 | 同 pipeline 内顺序执行 | 独立 sub-graph，可被多个 pipeline 复用 |
| Prompt 上下文 | 继承前序 step 的全部 context | 只拿到 input + output，不知道中间推理过程 |
| Model | 跟 pipeline 共用同一个 model | 可以用不同 model（如生成用 Pro，评审用 Flash） |
| 可复用性 | 每个 pipeline 各写一份评审逻辑 | 统一评审框架，按 task_type 加载不同 rubric |

#### 架构演进目标

```
Supervisor
├── Analyze Sub-graph
│   └── steps: hydrate → charts → insights → [call Evaluator]
├── Action Sub-graph (Content Gen)
│   └── steps: strategy → discovery → planning → generation → [call Evaluator]
├── Chat Sub-graph
└── Evaluator Sub-graph  ← 共享，被 Analyze / Action 在最后一步调用
    ├── input:  { task_type, original_input, output, rubric }
    └── output: { scores, issues, suggestions, pass_fail }
```

Evaluator **不是** Supervisor 直接路由的一级 Agent，而是 Analyze 和 Action 在最后一步内部调用的 sub-graph。

#### Content Generation 评审维度（Rubric）
- [ ] RAFT 四维评分（Relevance / Authority / Freshness / Thoroughness，各 1-5 分）
- [ ] 品牌调性一致性（对比 `geo_brand_profiles`）
- [ ] AI 引擎可引用性（结构化程度、FAQ schema 合规性）
- [ ] 事实性校验（有没有编造数据/引用）

#### Analysis 评审维度（Rubric）
- [ ] SQL 正确性（生成的 SQL 是否真正回答了用户问题）
- [ ] 数据一致性（图表数据和文字洞察是否自洽）
- [ ] 指标合理性（数值是否在合理范围，有没有明显的聚合错误）
- [ ] 归因逻辑（insight 的因果推断是否 justified by data）

#### 分阶段落地

**P1（当前迭代）：抽象统一评审函数**
- [ ] 把质量评审 step 实现为独立函数 `evaluate(task_type, inputs, output, rubric) → EvalResult`
- [ ] 保持在各自 pipeline 内调用，但逻辑已解耦、接口统一
- [ ] 定义 `EvalResult` schema：`{ scores: dict, issues: list[str], suggestions: list[str], pass: bool, summary: str }`

**P2（demo 之后）：升级为独立 Evaluator Sub-graph**
- [ ] 将 `evaluate()` 函数升级为独立的 LangGraph sub-graph
- [ ] 支持 Generator-Critic Loop：评分不达标 → 反馈给生成 Agent → 重新生成 → 再评
- [ ] 评审 Agent 可使用不同 model（如 Flash 评审 Pro 的输出，降低成本）
- [ ] 评审结果写入 `geo_agent_tasks.output.quality_score`，前端展示评分卡片

**P3（规模化）：评审持久化与趋势分析**
- [ ] 评审结果存入 `agent_evaluations` 表，积累质量趋势数据
- [ ] 基于历史评审数据优化 rubric 权重和阈值
- [ ] 前端增加质量趋势 dashboard（各 pipeline 的平均评分、通过率）

---

### 🔶 Reddit Citation 正文抓取稳定性升级（OAuth API / PRAW fallback）

**优先级：** 中高（Citation Analysis 质量关键依赖）

**背景：** Citation Analysis 需要读取被 AI 引用的 Reddit URL，并从帖子正文与评论中学习结构、论证方式、社区问题和品牌提及状态。当前已实现 P1 fallback：当 Reddit 页面抓到 `Please wait for verification` / blocked shell 时，自动尝试 `.json?raw_json=1`、`api.reddit.com`、`old.reddit.com`。这能显著减少 verification shell 对正文质量的污染，但不能承诺 95%+ 成功率，因为仍会遇到删帖、私密/封禁 subreddit、NSFW/age gate、风控、rate limit、评论删除等情况。

**目标：** 将 Reddit citation fetch 升级为更稳定的多层抓取链路，优先使用合规 API 读取公开帖子内容，再降级到现有公共 JSON / old Reddit / Web 摘要方案。

**建议抓取优先级：**
- [ ] 1. 先读本地缓存 / 已存 citation metadata，避免重复请求 Reddit。
- [ ] 2. 接入 Reddit OAuth API 或 PRAW read-only：通过 Reddit URL / submission id 获取 title、selftext、subreddit、score、num_comments、top comments。
- [ ] 3. 当前 fallback：`.json?raw_json=1`、`api.reddit.com`、`old.reddit.com`。
- [ ] 4. Web Search / Search Grounding 只作为发现和摘要补充，不作为 Reddit 正文抓取主来源。
- [ ] 5. 对无法读取的 URL 输出明确 `fetch_status`，在 Citation Analysis Summary 中提示证据质量不足。

**实现步骤：**
- [ ] 增加 Reddit API/PRAW 配置项：`REDDIT_CLIENT_ID`、`REDDIT_CLIENT_SECRET`、`REDDIT_USER_AGENT`，保持可选。
- [ ] 在 `citation_analysis.py` 中新增 Reddit API fetcher，作为公共 JSON fallback 之前的高优先级分支。
- [ ] 增加缓存与 rate-limit/backoff，避免批量 Citation Analysis 触发 Reddit 限流。
- [ ] 将 `fetch_status`、正文来源层级、失败原因展示到 Citation Analysis 预运行结果里。
- [ ] 增加单元测试：成功 API 抽取、删帖/私密帖 fallback、verification shell fallback、rate limit fallback。

---

### 🔶 Content Generation Quality Loop 强化

**优先级：** 中高（官网 / Reddit 内容质量稳定性的关键闭环）

**背景：** 当前内容生成已经具备 Citation Analysis、Quality Gate、最多两轮 Revise、post-revision review、`skipped` 状态展示和模板级 `revision_guidance`。但长期要让生成质量稳定提升，需要继续补齐更强的回归测试、证据型评价和人工复核路径。

**目标：** 将内容生成从“LLM 自评 + 局部规则”升级为更可验证的质量闭环：Citation 输入必须被正文响应；Revise 后的质量结果必须对应最终正文；二轮 Revise 后仍失败时必须明确进入人工复核。

**待办：**
- [ ] 增加 mock/integration test，强制第一轮 Revise 后仍失败，从而覆盖第二轮 Revise 实际执行与第二轮后复查。
- [ ] 将 Citation Alignment 从关键词检测升级为 evidence-based 判断：Reviewer 必须指出正文中哪些段落响应了 citation gap，哪些没有响应。
- [ ] 将 Framework Coverage 从关键词检测升级为 evidence-based coverage，避免为了过 Gate 强行露出内部术语。
- [ ] 明确二轮 Revise 后仍未通过时的最终状态：`Needs Human Review`，并在前端报告中解释原因。
- [ ] 将官网 `Related Resources` 进一步自然化为读者资源区，避免出现后台编辑指南或裸露 SEO 操作说明。
- [ ] 将策略生成 raw JSON 回归问题纳入自动化测试：所有策略 UI 输出必须是人类可读策略文本。
- [ ] 增加可视化 E2E checklist 自动化覆盖：等待 Data Scope / Prompt / Discover / Citation / Strategy 完成后才能进入下一步。

---

## 2. Completed Log

> 简要成就单 —— Claude Code 看这里知道"这些做过了别重复"。详细历史设计文档见 `docs/archive/`。

### ✅ i18n zh-CN / en-US 双语化收尾（SaaS Web v25）

**完成** — 2026-04-25

- [x] LoginPage.tsx / Prompts.tsx / PromptEditor.tsx / ContentPipelineModal.tsx / WizardShell.tsx 全部双向覆盖
- [x] 字典 namespace `common / wizard / content / insights` zh-CN 与 en-US 键数对等（32 / 38 / 261 / 437）
- [x] 部署到 Cloud Run `geo-saas-web:v25`

涉及文件：`geo_saas/web/src/{pages, components, i18n/locales}/...`

---

### ✅ v1.2 — Dual-Mode Tracking + Phase 1/2/3

**完成** — 2026-04-20

涵盖可信度修复、Template × Wizard 2D 配置、Content 契约对等、Topic 语义化、Auto-Discovery 4-Layer Fallback。
详细设计文档见 `docs/archive/v1.2_design_doc.md`。

---

### ✅ Fanouts 页面优化

页面：`/insights/fanouts`

- [x] 合并相同 client prompt 的多行（不同 country/platform）为一行
- [x] Platforms 和 Countries 在 cell 内多值展示
- [x] Region (Countries) 和 Language 拆成两列单独展示
- [x] 点击 client prompt 行展开该 prompt 下所有 country × platform 的 final prompts
- [x] Derived Query Variants 表格增加 country、platform 两列（单值），按一定顺序排列

---

### ✅ Analyzer 域名分类性能优化（Analyzer v24）

**完成** — 2026-03-09

- [x] 将 `classify_domains` 从 per-result 改为 per-batch（100 条一次性去重分类）
- [x] vertexai init 缓存（避免每次调用都重新初始化）
- [x] 增加缓存命中率日志
- [x] Cloud Job `task-timeout` 从 3600s 调至 7200s

涉及文件：`geo_analyzer/main.py`、`geo_analyzer/src/parsers/domain_classifier.py`、`geo_analyzer/terraform/main.tf`

---

### ✅ Ingestor 幂等性与容错加固（Collector v29）

**完成** — 2026-03-09

- [x] 修复 duplicate key 无限重试（`asyncpg` 异常未被 `sqlalchemy.IntegrityError` 捕获）
- [x] 添加 not-null constraint 幂等处理
- [x] 添加 task_meta 缺失时从 `geo_tasks` 自动恢复的防御逻辑

涉及文件：`geo_collector/src/result_ingestor.py`

---

## 3. Code Structure Refactor Plan (2026-04-25)

> 跨 5 个模块的结构性 refactor，来自 2026-04-25 的全量代码 review。基于 50+ 次 GCP 部署但几乎无 git commit 的历史，做一次性结构整理。

### 3.1 背景与证据

50+ 次部署无 commit 带来的累积债务：

| 问题 | 证据 |
|---|---|
| `schema.sql` 滞后 45 个 migration | 自述"到 migration 009"，实际 migrations 已到 054（已删除） |
| `geo_collector/alembic/` 死代码 | 最后更新 2026-02-07，之后 schema 演进全走根 `/migrations/`（已删除） |
| 5 个模块 `database.py` / `config.py` 各自实现且已分化 | collector: Pydantic v2 + 异步 `databases`；analyzer: v1 + 同步 SQLAlchemy ORM |
| 三座大山 god-files | `geo_agent/src/routers/tasks.py` 3404 行 / `geo_saas/web/src/pages/SettingsPage.tsx` 2899 行 / `geo_saas/src/routers/settings.py` 1793 行 |
| 无 service / repository 层 | 158 个端点中只有 2 个有 `response_model=`，routers 直接调 DB |
| `lib/api.ts` 单文件 1219 LOC / 141 exports | 前端所有端点堆一处 |
| `geo_admin` TS 迁移半成品 | `tsconfig.json` 存在但不 strict，UI 层 `.tsx` 而 pages 层 `.jsx` |

### 3.2 依赖关系图

```
Phase 0 (清理)         —— 无依赖，最先 ✅ Done 2026-04-25
  ↓
Phase 1 (目录 api/→src/) —— 早做省重复 ✅ Done 2026-04-25
  ↓
Phase 2 (geo_common)   —— 基建，含 deploy_all.sh + Dockerfile 改造 🟡 In Progress
  ↓
  ├─ Phase 3 (大文件拆分)      —— 前后端可并行
  └─ Phase 5 (admin TS 迁移)   —— 独立，可插入任何时候
  ↓
Phase 4 (services refactor)   —— 依赖 Phase 2+3
  ↓
Phase 7 (OpenAPI 生成)        —— 依赖 Phase 4 的 response_model
  ↓
Phase 8 (.gitignore 审查)     —— 收尾

Phase 6 (PG MCP + P0 测试) —— ✂️ 本次不做，见 §1 独立 workstream
```

### 3.3 各 Phase 内容

#### Phase 0 — 清理 ✅ Done (2026-04-25)

- [x] 删 `schema.sql`（滞后 45 个 migration）
- [x] 删 `geo_collector/alembic/` + `alembic.ini`（停在 2026-02-07）
- [x] 删 `geo_agent/sql/` 空目录
- [x] 删 `geo_saas/test_db.py` 孤儿文件
- [x] 删 `.gstack/browse-console.log` + `browse-network.log`
- [x] 修 `geo_collector/Dockerfile`（删错误的 `CMD ["uvicorn", "src.main:app"...]`，加注释说明 terraform override entrypoint）
- [x] 写 `docs/SCHEMA.md`（单源声明 + 禁止 Terraform 写 DDL）
- [x] `TODO.md` 合并进本 roadmap + 删 `TODO.md`
- [x] memory `feedback_allow_list_discipline.md`：Allow List 管理原则
- [x] `.claude/settings.local.json` 删除违规 `"Bash(rm:*)"` entry

#### Phase 1 — 目录结构统一 ✅ Done (2026-04-25)

- [x] `geo_saas/api/` → `geo_saas/src/`
- [x] `geo_agent/api/` → `geo_agent/src/`
- [x] `geo_admin/api/` → `geo_admin/src/`
- [x] geo_collector `src/` / geo_analyzer `src/` 已对齐
- [x] 测试目录全部移到模块根 `tests/`（geo_saas/src/tests → geo_saas/tests；新建 geo_agent/tests/ + geo_admin/tests/ + conftest.py）
- [x] `geo_agent/Dockerfile` 的 `COPY api/` → `COPY src/`
- [x] `deploy_all.sh` 2 处 `./api` → `./src`
- [x] `geo_saas/tests/conftest.py` sys.path 指向新 src/
- [x] CLAUDE.md / AGENTS.md / docs/local-dev/claude-ports.md / geo_collector/src/core/database.py 注释 / geo_analyzer/terraform/suggestions.tf 注释的所有 `api/` 引用更新
- [x] 29 个 `__pycache__` 污染清理完

#### Phase 2 — 引入 `geo_common/` 共享层 🟡 In Progress

```
geo_common/
├── pyproject.toml                     # 可本地 pip install -e
├── src/geo_common/
│   ├── config/base.py                 # Pydantic v2 BaseSettings 基类
│   ├── db/pool.py                     # 统一 asyncpg pool
│   ├── db/tenant.py                   # @tenant_scoped decorator（从 geo_agent 抽出）
│   ├── schemas/{brand,topic,client}.py   # 跨模块共享 Pydantic models
│   ├── services/{clients,topics,prompts,brands}.py   # DAL / Repositories
│   └── middleware/{request_id,cors}.py
└── tests/
    └── test_tenant_decorator.py
```

**MVP 范围（本 Phase 落地）：**
- [ ] geo_common 骨架 + pyproject.toml
- [ ] 抽取 config base class（Pydantic v2 基类，统一环境变量别名 `DB_PASSWORD` ↔ `DB_PASS`）
- [ ] 抽取 `@tenant_scoped` decorator（从 `geo_agent/src/middleware/tenant.py` 搬出）

**配套部署改动（方案 A：Cloud Build context 改仓库根）：**
- [ ] 每个模块 Dockerfile 改 `COPY geo_common /geo_common` + `COPY <module>/src /app` + `pip install -e /geo_common`
- [ ] `deploy_all.sh` 里每条 `gcloud builds submit` 改成从仓库根提交
- [ ] 加 `.gcloudignore`（排除 `venv/` / `node_modules/` / `.git/` / `dist/`）
- [ ] **geo_common 本身不是部署目标**，没有 VERSION / tfvars / terraform

**留到 Phase 2.5（后续小迭代）：**
- [ ] db pool 统一（geo_collector 用 `databases` lib、geo_analyzer 用同步 SQLAlchemy 两个异类要单独重构）
- [ ] geo_analyzer Pydantic v1 → v2 升级

#### Phase 3 — 大文件拆分

**后端**：
- [ ] `geo_agent/src/routers/tasks.py` (3404) → `tasks` (~400) + `templates.py` + `framework.py` + `content_preselect.py` + `export.py` + `strategy.py`；HTML 渲染抽出到 `services/report_renderer/`
- [ ] `geo_saas/src/routers/settings.py` (1793) → `routers/settings/{brands, peers, topics, products, domains}.py`
- [ ] `geo_saas/src/database.py` (591 LOC 50+ 表) → `models/{clients, brands, topics, prompts, metrics, analysis, content}.py`
- [ ] `geo_saas/src/routers/insights/analysis.py` (1160) → NL2SQL / chart / hydration 三文件
- [ ] `geo_saas/src/routers/onboarding/auto_discovery.py` (1156) → candidates / discovery 分离

**前端**：
- [ ] `pages/SettingsPage.tsx` (2899) → `pages/settings/{SettingsShell, tabs/*}.tsx`
- [ ] `pages/PromptEditor.tsx` (1509) 抽 `SearchableMultiSelect` / `BrainstormDialog` 到 `components/promptEditor/`
- [ ] `pages/agents/AgentChat.tsx` (1493) 抽 `<SessionSidebar>` / `<ChatStream>` / `<ExportPanel>`
- [ ] `pages/agents/AgentAnalysis.tsx` (1378) 抽 `<ThinkingSteps>` / `<AnalysisChartGrid>`
- [ ] `components/agents/ContentTaskModal.tsx` (1546) 拆多个 step 组件
- [ ] `lib/api.ts` (1219, 112 exports) → `lib/api/{clients, insights, settings, agents, prompts, content, onboarding}.ts` + index 聚合

**i18n 字典跟随拆分**：按 tab 子 namespace 或保持 settings namespace 内 sub-keys

#### Phase 4 — Services / Repositories 层 refactor

- [ ] `geo_saas/src/routers/*.py` 改成调 `geo_common.services.XXXRepository`，router 只保留 HTTP 壳 + 权限校验
- [ ] `geo_admin/src/routers/*.py` 同步
- [ ] 修 `geo_admin languages` router 缺 `/api` 前缀的疑似 bug
- [ ] 全面补 `response_model=`（为 Phase 7 铺路）

#### Phase 5 — `geo_admin/web` TS 迁移

见 §1 "Admin Web TypeScript 迁移 + UI 升级" checklist。作为 Phase 5 一并执行。

#### Phase 6 — （本次跳过）

geo_agent PG MCP 迁移 + P0 租户隔离测试 —— 详见 §1，独立 workstream。

#### Phase 7 — OpenAPI 类型自动生成

**依赖 Phase 4 的 response_model 规范。**

- [ ] 后端：补全 148 个端点的 `response_model=`（渐进，先 insights → settings → onboarding）
- [ ] 全局统一 `ErrorResponse` 模型
- [ ] CI 导出 `openapi.json` 到 `geo_saas/web/src/lib/api/openapi.json`
- [ ] 前端 `npm install openapi-typescript -D`，加 `scripts.gen-types`
- [ ] 生成 `lib/api/generated.ts`，逐步替换手写 types

#### Phase 8 — `.gitignore` 最终审查

**留到最后**，因为前面 phase 会改动文件分布。

- [ ] `git ls-files | grep -E '(venv|__pycache__|\.DS_Store|dist/|node_modules/)' | wc -l` 应返回 0
- [ ] `.gstack/` 全目录 ignore
- [ ] `.claude/settings.local.json` ignore（含本地敏感配置）
- [ ] 审查 `terraform/.terraform/` / `*.tfstate` 是否真没 commit 过
- [ ] 更新 `.gitignore` 到最终状态

### 3.4 执行方式分工

| Phase | 执行方式 | 说明 |
|---|---|---|
| 0 清理 | 🧍 Claude 串行 | 低风险，逐项验证 |
| 1 目录 rename | 🧍 Claude 串行 | 涉及 Dockerfile / terraform / import 链联动，必须编译通过 |
| 2 geo_common | 🧍 Claude 串行 | 目录结构是一次定型、5 模块依赖的架构决策 |
| 3 后端拆文件 | 🧍 Claude 串行 | Python import 链敏感，并行会冲突 |
| 3 前端拆文件 | 🤖🤖🤖 多 agent 并行 | 5 个文件独立，每个 agent 负责一个 |
| 4 services refactor | 🤖 per-router agent + Claude review | 模式化转换 |
| 5 admin TS 迁移 | 🤖🤖 2-3 agent 并行 | 页面独立，纯转换任务 |
| 7 OpenAPI | 🤖 per-domain agent + Claude 整合 | 批量补 response_model 模式化 |
| 8 .gitignore | 🧍 Claude 串行 | 5 分钟收尾 |

**原则**：架构决策/编译链联动/跨文件一致性 → Claude 串行；独立文件的批量转换/模式化重构 → agent 并行。
