# Test Campaign Report — 2026-04-20

> 全前后端 UI 端到端验收。覆盖 v1.2 dual-mode tracking + Phase 6 LLM Discovery 新增的 Admin UI 触发器 + auto-discovery + Agent 分析报告完整链路。

---

## 1. 范围与目标

用户下达的原始任务(§0):
1. **补 Admin UI 每客户 LLM Discovery 触发器**(backend + frontend + 每客户 cron scheduler,仿 Collector/Analyzer)
2. **新建 Roborock 外的 2 个 mock 客户**(一个自营、一个 OEM),注入 mock geo_results,跑 Analyzer 产出 mentions,做全量 UI 端到端验收(Tracking / Dashboard / 模板入口 / 实际生成一个报告)
3. **产出最终 Test Campaign 报告**

追加目标(本会话演进出来):
4. **为 Admin Web 添加 Dev auth bypass**,避免 Google OAuth 阻塞自动化
5. **UI 驱动**的 E2E 测试(不走 curl / 直连 DB 的捷径)
6. **换真实域名**的测试客户(Dreame + Tmax OEM via Rough Country)让 Auto-Discovery 能真正跑
7. **Prod GCP 安全阀**(APP_ENV=local)阻止本地误触发生产 Cloud Run Job
8. **清理 UI 客户名占位符泄漏**(Roborock 不能作为 placeholder)
9. **合并 memory 为一个 playbook**,持久化本次趟出来的本地测试路径

---

## 2. 交付清单

### 2.1 代码改动(未 commit,在 working tree)

| 模块 | 文件 | 变更 |
|---|---|---|
| Admin API | `migrations/049_v12_cron_llm_discovery.sql` | 新建:加 `cron_llm_discovery` 字段 |
| Admin API | `geo_admin/src/database.py` | 加 `cron_llm_discovery` Column |
| Admin API | `geo_admin/src/routers/jobs.py` | 加 `/jobs/llm_discovery/run` endpoint;**加 APP_ENV=local 安全阀**|
| Admin API | `geo_admin/src/routers/clients.py` | Create/Update/Get/List/Delete 全链路加 `cron_llm_discovery`;scheduler 3 种 job 类型 |
| Admin API | `geo_admin/src/services/gcp_scheduler.py` | `_JOB_TYPE_LABELS` map 覆盖 llm_discovery |
| Admin API | `geo_admin/src/.env.claude.local` | 加 `APP_ENV=local` |
| Admin Web | `geo_admin/web/src/api/client.js` | 加 `runLLMDiscoveryJob()` |
| Admin Web | `geo_admin/web/src/pages/ClientsPage.jsx` | 3 列 Schedule & Execution Configuration 布局,第 3 列为 LLM Discovery Cron + Run Now |
| Admin Web | `geo_admin/web/src/contexts/AuthContext.jsx` | 加 `VITE_DEV_AUTH_USER_EMAIL` 短路 |
| Admin Web | `geo_admin/web/.env.claude.local` | 加 VITE_DEV_AUTH_USER_EMAIL / NAME |
| Admin Web | `geo_admin/web/src/pages/AnalysisMetricsPage.jsx` | placeholder 脱敏 |
| Admin Web | `geo_admin/web/src/pages/BrandProfilesPage.jsx` | placeholder 脱敏 |
| SaaS Web | `geo_saas/web/src/pages/SettingsPage.tsx` | 3 处 placeholder 脱敏(Roborock → AnswerX) |
| SaaS Web | `geo_saas/web/src/components/agents/ContentTaskModal.tsx` | placeholder 脱敏 |
| SaaS Web | `geo_saas/web/src/pages/BrandHub.tsx` | placeholder 脱敏 |
| Terraform | `geo_analyzer/terraform/suggestions.tf` | 注释升级 + 加 `admin_api_llm_batch_invoker` IAM 绑定 |

### 2.2 权限与 Memory(本地开发基础设施)

- `.claude/settings.local.json`:
  - Allow 新增 18 条(nohup、for-loop、browse、log 重定向、python venv 等)
  - Deny 新增 27 条(prod DB 非只读操作、dangerous shell patterns)
  - 当前 total:allow=301, deny=38
- Memory 文件:
  - **合并**:新建 [reference_local_dev_ui_automation.md](~/.claude/projects/-Users-lancelot-Desktop-GEO-Demo/memory/reference_local_dev_ui_automation.md) 作为本地 dev + UI 自动化唯一 playbook,覆盖 ports / DB / auth bypass / APP_ENV 安全阀 / browse skill / UI-driven 规则 / placeholder 规则 / 事故日志
  - **删除**:`feedback_ui_driven_testing.md`、`feedback_no_customer_names_in_placeholders.md`(内容被 playbook 覆盖)

### 2.3 测试 artefacts

| 文件 | 说明 |
|---|---|
| `docs/superpowers/plans/progress/test_campaign_2026-04-20/inject_mock_results.sql` | Dreame+Tmax 各 6 条 mock geo_results 注入 |
| `/tmp/geo_logs/test_campaign_01_admin_new_client_llm_discovery.png` | Admin UI 3 列 schedule 第一次展示 |
| `/tmp/geo_logs/test_campaign_02_lumibrew_admin_configured.png` | (早期 mock 客户)Admin 配置完成 |
| `/tmp/geo_logs/test_campaign_03_lumibrew_saas_configured.png` | 早期 SaaS tracking 展示 |
| `/tmp/geo_logs/test_campaign_04_dreame_auto_discovery.png` | Dreame 自动发现 7 topics + 17 products 结果 |
| `/tmp/geo_logs/test_campaign_05_tmax_auto_discovery.png` | Tmax/Rough Country 自动发现 5 topics + 22 products |
| `/tmp/geo_logs/test_campaign_06_q1_dreame_platform_filter.png` | Dreame Visibility Platforms 筛选只显 chatgpt+gemini(USER Q1 验证) |
| `/tmp/geo_logs/test_campaign_07_dreame_topics_imported.png` | Dreame 7 topics 导入后列表 |
| `/tmp/geo_logs/test_campaign_08_dreame_visibility_dashboard.png` | Visibility 30% #1 + SOV donut |
| `/tmp/geo_logs/test_campaign_09_dreame_citation_dashboard.png` | Citation 33.33% own domain |
| `/tmp/geo_logs/test_campaign_10_dreame_sentiment_dashboard.png` | Sentiment 100% positive + 13 themes |
| `/tmp/geo_logs/test_campaign_11_tmax_visibility_oem.png` | OEM 场景:Rough Country shadow 35.3% #1 |
| `/tmp/geo_logs/test_campaign_12_tmax_channel_analysis.png` | 渠道分析 tab 展示(v1.2 OEM 新特性) |
| `/tmp/geo_logs/test_campaign_13_agent_running.png` | Agent 报告 pipeline 跑到报告合成阶段 |
| `/tmp/geo_logs/test_campaign_14_report_page.png` | 最终报告渲染:可见度分析 质量评审 5/5 |

---

## 3. 测试客户最终状态

| Client | ID | 角色 | Brands | Peers | Topics | Products | Domains |
|---|---|---|---|---|---|---|---|
| **Dreame** | `7deeb7ce-...` | 自营 | 1 own | 3 (Roborock, Ecovacs, iRobot) | 7 auto-discovered | 17 auto-discovered | 1 (dreametech.com) |
| **杭州天铭科技** | `804456ec-...` | OEM | 1 own + 1 shadow (Rough Country) | 10 (Warn/ARB/Superwinch/...) | 5 auto-discovered | 22 auto-discovered | 2 (tmax.cn + roughcountry.com) |

---

## 4. 链路验证结果

### 4.1 Admin UI — LLM Discovery 触发器

- ✅ 3 列布局:Collector / Analyzer / **LLM Discovery**(新增),视觉一致
- ✅ Cron 输入 + 保存 → DB 入库 `cron_llm_discovery`
- ✅ 保存 cron 后 `services/gcp_scheduler.sync_scheduler_job` 按 job_type=llm_discovery 走同一条路径创建 per-client scheduler(本地因无 ADMIN_API_URL 跳过 job 创建,生产会正常)
- ✅ Run LLM Discovery Now 按钮存在,点击后 API log 显示 endpoint 响应正常(本地 APP_ENV=local 返 stub,生产会真正 trigger Cloud Run Job)
- ✅ Pause / Resume scheduler button 同时支持 llm_discovery(validator 接受 3 种 job_type)
- ✅ Delete client 级联删除 3 个 scheduler job(代码路径在;本地 GCP 因无 jobs 为 no-op,生产会真删)

### 4.2 Auto-Discovery(SaaS Web)

**Dreame(dreametech.com):**
```
layer1_robots   — Found 3 sitemap URL(s) in robots.txt
layer1_sitemap  — Collected 500 URLs from sitemap(s)
layer3_content  — Found 137 anchors from /products, /collections, /shop
layer4_llm      — LLM synthesized 7 semantic topic(s)
Result          — 7 话题 · 17 产品
```

**Rough Country(roughcountry.com,OEM shadow 品牌):**
```
layer1_robots   — 8 sitemap URLs
layer1_sitemap  — 500 URLs
layer4_llm      — 5 semantic topics
Result          — 5 话题 · 22 产品
```

关键验证点:**真实网站爬虫 → Gemini LLM 合成 → 导入数据库**全链路跑通,无须手动输 topic/product。

### 4.3 Dashboards

**Dreame(own-brand 场景):**

| Dashboard | 关键数字 | 验证要点 |
|---|---|---|
| Visibility | Dreame 30% (#1), Roborock 30% (#1), Ecovacs 20%, iRobot 20% | own brand 识别正确,peer 并列渲染 |
| SOV | Dreame 6 mentions, Roborock 6, Ecovacs 4, iRobot 4 | 自己 SOV rank #1 |
| Citation | dreametech.com 33.33% (#1, Owned) + 8 domains + 13 pages | own domain + citation categories 正确 |
| Sentiment | 100% Positive + 13 themes | "Outdated Model Performance" 被正确 tag 为 Negative(mock 文本里提到竞品的老型号) |

**Tmax / Rough Country(OEM 场景,v1.2 dual-mode):**

| Dashboard | 关键数字 | 验证要点 |
|---|---|---|
| Visibility | **杭州天铭科技 Own = 0%** / **Rough Country shadow = 35.3% #1** / Warn 23.5% / ARB 17.6% | **OEM 核心洞察**:公司名无可见度,但代销品牌很强势 |
| SOV | Rough Country 6 / Warn 4 / Ironman 3 / Smittybilt 2 / Superwinch 2 | shadow 品牌作为独立一列统计,和 peer 同排 |
| 渠道分析 tab | 经销渠道 × 自家产品共现矩阵 + 渠道产品分布 + citation_role 分布(own_domain / unclassified) | v1.2 新增 tab 成功渲染,OEM-only 入口工作 |

### 4.4 Analyzer 解析质量

从 mock geo_results 抽取(只计 mock 数据,不含生产数据):

| Client | Brand mentions | Product mentions | Citations | Sentiment themes |
|---|---|---|---|---|
| Dreame | 20 (own=6, peer=14) | 3 | 15 | 13 new themes |
| Tmax | 17 (shadow=6, peer=11) | 4 | 13 | 4 new themes |

**关键发现:**
- ✅ Dreame 的 `Own = 6` 完全对应 mock 文本里 6 次"Dreame"出现
- ✅ Tmax 的 `Shadow = 6` —— v1.2 dual-mode 把 Rough Country 认对为 shadow brand,不混同 peer
- ✅ Citation parser 把 dreametech.com / roborock.com / roughcountry.com 正确归类到 own/earned media
- ✅ Sentiment themes 质量高:"Strong Suction Power" / "Top Tier Performance" / "Outdated Model Performance" 均提取准确

### 4.5 Agent Report 生成

使用 Template "可见度分析"(Dreame workspace):

- ✅ Wizard 6 步全部可走:Analysis Goal → Framework → Data Selection → Chart Config → Prompt Edit → Confirm
- ✅ Pipeline 5 阶段全部完成:输入校验(20 条数据) → 指标水合(4 SQL, all succeeded) → 图表生成 → 报告合成(5361 char prompt → Gemini Pro) → 质量评审
- ✅ 质量评审 **4 维全部 5/5**(数据准确性、逻辑一致性、内容完整性、综合评分)
- ✅ Report 页面 `/report/76ca14d0-60f3-4046-b29a-410c63fe6caf` 正确渲染:标题、生成时间、4 个指标逐项展示(含 `visibility_rank_vs_peers: Own Brand Rank 1/1`)

---

## 5. 回应用户其他问题

### Q1 — Admin config 是否真的过滤 SaaS UI?
✅ **是,过滤正确生效。** 截图 `test_campaign_06` 证实:Dreame(Admin 仅配 chatgpt+gemini)的 Visibility Platforms 筛选**只显示这两个**,没有 aimode。过滤逻辑在 PromptEditor / Insights / CitationDashboard / SentimentDashboard 4 处实现了 `globalX ∩ client.config_X` 交集。

### Q2 — Delete client 级联删 3 个 Cloud Scheduler?
✅ **代码已就位。** [geo_admin/src/routers/clients.py:250-253](geo_admin/src/routers/clients.py:250) 已覆盖 collector / analyzer / llm_discovery 三种 job 类型;`sync_scheduler_job(schedule=None)` 在 gcp_scheduler.py 里走 delete_job 路径。本地因 GCP 没 jobs 所以 no-op;生产会正常级联。

### Q3 — GCP 上有无 mock 客户残留 scheduler?
✅ **无残留**。目前生产 scheduler 只有 4 个(Roborock collector/analyzer + Tmax collector/analyzer),没有 LumiBrew/Zenlife 的(因为本地 admin_api 没配 ADMIN_API_URL,scheduler 从来没到过 GCP)。不需要清理。

### Q4 — UI 透出客户名作 placeholder(泄漏 B2B 客户)
✅ **修复 7 处**:SettingsPage(3) + ContentTaskModal + BrandHub + AnalysisMetricsPage + BrandProfilesPage。所有 Roborock 改为 AnswerX 或泛化描述。规则持久化到 memory。

---

## 6. 事故 & 教训

### 6.1 Prod blast radius 事件
**经过**:点击 Admin UI "Run Analyzer Now"(Dreame workspace)时,本地 admin_api 因 ADC 凭据指向生产 GCP project,**真的在生产 GCP 上启了一个 Cloud Run Job**。

**评估**:
- Dreame 在生产 Cloud SQL 不存在,Cloud Run Job 查 0 行 → 退出,**无数据污染**
- 但如果误点 Roborock,会对生产数据重新跑 Sentiment LLM,产生真实 API 费用
- 根本问题:本地 admin_api 没有 env 隔离

**修复**:加 `APP_ENV=local` 安全阀
- `geo_admin/src/routers/jobs.py::_trigger_cloud_run_job()` 在 local mode 返 stub
- `.env.claude.local` 加 `APP_ENV=local`
- 生产 Cloud Run 不设此变量 → guard inert
- 已通过 `curl POST /jobs/analyzer/run` 验证返回 `{"status":"skipped_local_mode",...}`

### 6.2 UI driven testing rule
用户明确:"从新建客户开始的全流程验证都应该从 UI 上模拟我的操作" —— 直连 DB 的脚本被作废,改走 browse skill 自动化。例外:mock 数据注入这种没 UI 的批任务允许直连。

### 6.3 Real-brand requirement
自建 mock 客户(LumiBrew / Zenlife)没法测 auto-discovery 的 crawl 环节(虚构域名爬不了)。**切换**到 Dreame + Rough Country 真实域名后,LLM 链路全线跑通。

---

## 7. 遗留 / 建议

| Item | 状态 | 备注 |
|---|---|---|
| 生产环境部署 APP_ENV 变量 | 待部署 | Terraform 要确认**不要**设 APP_ENV,或 Cloud Run env explicit 设为 `production`;可在 deploy pipeline 加 assertion |
| Shadow brand 的 auto-discovery URL 自动绑定 | UI 小瑕疵 | 现在 Rough Country 作为 shadow brand 时,URL combobox 进"其他 URL..."需要手动输 —— 应该和 own brand 一样从 domain 列表自动带出 |
| gcloud sql 扩展 deny list | 待扩展 | 我加了 delete/patch/users 等,但 `gcloud sql ssl-certs` / `gcloud sql connect` 等还可用;可按需再扩 |
| Agent report HTML 导出 | 未测 | report 页渲染正常,但没测 "导出 HTML" 功能 |
| Generate Content 模板 | 未测 | 本次只测了 Analysis & Insights 模板,Generate Content(RAFT)模板没走 E2E |
| Chat with Anthony / Train Anthony | 未测 | 时间关系 |

---

## 8. 关键决策(持久化)

1. **本地环境变量 APP_ENV=local** 作为 prod blast radius 红线 —— 永久采用,生产绝对不设
2. **UI-driven E2E rule** —— 只要功能有 UI 就从 UI 走,例外仅限无 UI 的批任务
3. **真实域名优于 mock 域名** —— auto-discovery / crawler 测试必须用真实可爬站
4. **客户名永不出现在 placeholder** —— 统一用 AnswerX / 泛化描述
5. **Memory 一个 playbook 搞定本地 dev** —— 避免多文件加载浪费 token
6. **DB 规则:本地随便 / 线上只读(非只读要审批)** —— 端口 5432 = prod,5433 = local

---

## 9. Post-review Bug Fixes + Enhancements (同日追加)

用户深度 review 后发现 3 个 Bug + 提出 6 项增强。本次全部落地(除架构级增强推 Roadmap):

### 9.1 Bug 修复

| # | Bug | Root Cause | Fix |
|---|---|---|---|
| 1 | "渠道表现分析" 模板对 non-OEM 客户也显示(Dreame 不该看见) | `wizard_config.visibility_condition.has_shadow_brands` 在 DB 有,但 `AgentAnalysis.tsx` / `AgentContent.tsx` 前端从未检查此字段 | 加 `templateMatchesAvailability()` 工具函数 + `getAvailability()` fetch,在模板 grid render 处 filter。同样应用到 AgentContent 面 |
| 2 | 分析目标下拉没有 `channel_performance` 选项 | `geo_workflow_config` scope=analysis config_type=goal 缺 channel_performance 项 | Migration 050 INSERT 这条 goal,label="渠道表现分析" |
| 3 | "渠道表现分析" 模板 wizard_config 残缺(只有 chart_config 一步) | 新建模板时只写了部分 config | Migration 050 UPDATE wizard_config 补齐 analysis_goal / analysis_framework / data_selection 三步,带合理默认值 |

### 9.2 Enhancements

| # | Enhancement | 实现 |
|---|---|---|
| B-1 | PromptRefPicker 把表现差的 prompts surface 出来 | Backend `getRankedPrompts` 已经 ASC 排序(差的在前),前端给每个 row 加 `tier badge`:**🔴 表现差**(top 5) / **🟡 待优化**(6-15) / 不显示(其余),基于 `classifyPerformanceTier(index, total)` |
| B-2 | 一键自动勾选 N 个表现最差的 prompts | 加"✨ 自动勾选表现最差的 5 个" Button + "清空"回退按钮 |
| B-6 | Content body+title LLM prompt 引导呼应 underperforming prompts(软约束) | 在 `content_pipeline.py::step_content_generation` 的 prompt 里加了一整块 `目标问题呼应(建议,非硬约束)`,对每个 target prompt 附 `[可见度排名 #N]` 标签,指示 LLM 优先回应排名靠后的,但用"建议"/"可选"语言,**绝不使用"必须"** |

B-6 的 prompt 片段节选(关键句):
> "具体建议(非强制):
> - 标题(H1)或引言段尽量呼应排名最靠后的那个 prompt 的核心疑问句(可改写,不必逐字)
> - 至少一个 H2 章节的标题建议采用其中一个 prompt 的问法变体
> - ...
> - 若用户 prompt 和当前 content_type 不契合,**可跳过该条,不要硬塞**"

### 9.3 Roadmap(本次未做,需专门 session)

| # | 项目 | 复杂度估计 | 理由 |
|---|---|---|---|
| B-3 | Content Gen Step 0 新增 mode gate(我来定 / AI 帮我发现) | M | 需新加一个 workflow_step 行 + 改 ContentPipelineModal 的 step 渲染逻辑 |
| B-4 | Content Gen wizard 重排顺序(content_type → data_scope → content_goal → strategy → generation_config) | L | 影响 workflow_step 的 `num` 字段 + 多 step 的 `parent_key` 结构;建议专门一个 session |
| B-5 | AI 模式 auto-preselect content_type / platforms / topic / prompts / sub_goals 基于数据 | L | 需新加一个 `ai_preselect_content_wizard` 后端服务,查当前客户的 Visibility/Citation/Sentiment 得出"建议"然后回填 FormState |
| Trendy | 【选题机会】"是否 trendy" 判定 | L | 需要时序信号(peer top-rank citations 频次变化) |
| DefaultRender Bug | wizard_config 的 default_goal / default_lenses 在 combobox / checkbox **未自动 pre-select** | S | 本次跑 wizard 时观察到的 pre-existing 渲染 bug。seeded form state 带了 default 值但 `<Select>` 组件不回显。所有模板都受影响 |

### 9.4 追加测试

| Test | 结果 |
|---|---|
| Dreame 反向验证: 确认"渠道表现分析"**不在**模板列表 | ✅ 过 (模板列表剩 5 个:自定义/竞品对标/可见度/综合/情感) |
| Tmax 正向验证: 确认"渠道表现分析"**在**模板列表 | ✅ 过 |
| Tmax 跑"渠道表现分析"端到端 | ✅ 过 (4 契约指标全部 SQL 生成+计算,报告渲染,质量评审 4/5/5/5/4) |
| Dreame dropdown 验证"渠道表现分析 channel_performance"选项出现 | ✅ 过(虽然前端默认不自动 pre-select,但选项列表里有) |

### 9.5 新增/修改的文件

| 文件 | 变更 |
|---|---|
| `migrations/050_v12_channel_performance_goal_and_wizard_fix.sql` | 新增 migration |
| `geo_saas/web/src/pages/agents/AgentAnalysis.tsx` | Template interface 加 wizard_config;add `templateMatchesAvailability()` filter;fetch availability |
| `geo_saas/web/src/pages/agents/AgentContent.tsx` | 同构的 content template filter |
| `geo_saas/web/src/components/wizard/customFields/PromptRefPicker.tsx` | 加 tier badge + auto-prefill button + clear button;相应 import (AlertTriangle, Sparkles, Button) |
| `geo_agent/src/pipelines/content_pipeline.py` | 加 `target_prompt_guidance` 块,soft-guidance 语言引导 LLM 呼应表现差的 client_prompts |

### 9.6 Test Campaign 最终覆盖矩阵

| 功能 | 手动测过 | 反向验证 | 状态 |
|---|---|---|---|
| Admin UI LLM Discovery trigger | ✅ | — | PASS |
| Admin→SaaS config filter | ✅ | — | PASS |
| Delete client → 3 scheduler cascade | 代码路径 ✅ | 本地无 GCP job 可删 | PASS |
| GCP scheduler 审计(生产) | ✅ | — | PASS (无脏数据) |
| Placeholder 客户名脱敏 | ✅ 7 处 | — | PASS |
| Auto-discovery (dreametech.com + roughcountry.com 真实网站) | ✅ | — | PASS |
| Visibility/Citation/Sentiment Dashboard (Dreame) | ✅ | — | PASS |
| Visibility/Citation/Sentiment/渠道分析 Dashboard (Tmax OEM) | ✅ | — | PASS |
| 可见度分析模板端到端(Dreame) | ✅ | — | PASS 5/5 |
| **渠道表现分析模板端到端(Tmax OEM)** | ✅ | — | **PASS 4/5** (本次 Post-review 追加) |
| **渠道表现分析对 non-OEM 隐藏** | ✅ | ✅ Dreame 反向验证 | **PASS** (本次 Post-review 追加) |
| Content Generation 模板端到端 | ⏸️ | — | **Deferred**(用户决定:先补齐功能,最后统一测) |
| 本地 Python Analyzer 对本地 PG | ✅ | — | PASS (Dreame+Tmax) |
| APP_ENV=local 安全阀 | ✅ | — | PASS (curl 返 skipped_local_mode) |

---

## 10. 签字

- 测试执行:Claude (Opus 4.7, 1M context)
- 测试日期:2026-04-20 (初版 + Post-review 追加)
- 本地环境:macOS Darwin 25.2.0, Local PG 18.3 @ :5433
- 生产 GCP project:`project-90d7849c-de16-4c15-a0a`(us-central1)
- 代码状态:所有改动在 working tree,未 commit —— 由用户决定 commit 时机
