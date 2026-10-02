# Dual-Mode Tracking Implementation Plan v1.2

> **Spec 基线**:[2026-04-20-dual-mode-tracking-design-v1.2-finalized.md](../specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md)
> **执行模式**:subagent-driven autonomous execution
> **交付节奏**:MVP + V2 全量合并上线(一次 release)
> **开工日期**:2026-04-20
> **预计完成**:一次连续 sub-agent execution(时长视 agent 吞吐)

---

## 执行原则

1. **自主执行**:sub-agent 自测 + hand-off,无需用户中途 review
2. **Migration SQL 不执行**:所有 DDL/DML 先写文件,所有代码写完后用户手动执行
3. **Phase 间并行化**:依赖链允许并行的 Phase 同时启动
4. **Blocker 记录**:遇阻的 task 写进 `progress/blockers.md`,不阻塞其他 Phase
5. **历史数据保护**:所有 Phase 对 Roborock 历史数据 read-only(schema 改动通过 migration,不直接 DML)

---

## 依赖图

```
              Phase 1 (Migration SQL + Plan) [主 Claude 自写]
                              │
                              ▼
                         Phase 2
                         Analyzer Parser 改造
                         [sub-agent A]
                         (产出 Analyzer 侧 schema adapter 作为后续 Phase 参考)
                              │
                              ▼
                ┌─────────────┴─────────────┐
                ▼                           ▼
           Phase 3                     Phase 4
           SaaS API 后端                Agent NL2SQL 适配
           [sub-agent B]               [sub-agent C]
                │                           │
                └─────────────┬─────────────┘
                              ▼
                         Phase 5
                         SaaS UI 前端核心
                         [sub-agent D]
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
           Phase 6                     Phase 7
           Suggestions 系统             Tooltip + i18n
           [sub-agent E]               [sub-agent F]
                │                           │
                └─────────────┬─────────────┘
                              ▼
                  Phase 8: 用户手动部署 + 验证
                  (醒来后执行 Migration SQL + deploy)
```

---

## Phase 1: Migration SQL + Plan(主 Claude 自写,不走 sub-agent)

### 目标
产出全部 DDL/DML 文件和本 Plan 文件,不执行任何 SQL。

### 产出
- 本 Plan 文件
- `migrations/040_v12_new_tables.sql` —— 新建 7 张表 + 1 trigger
- `migrations/041_v12_extend_existing.sql` —— 扩展 geo_client_domains / geo_citations / geo_clients
- `migrations/042_v12_rename_mentions.sql` —— geo_company_mentions → geo_brand_mentions
- `migrations/043_v12_data_migration.sql` —— 存量数据迁移(brands seed / topic_products / domain 回填)
- `migrations/044_v12_drop_legacy.sql` —— 删除旧列(peers.is_own_brand、topics.products)
- `migrations/045_v12_truncate_agent_state.sql` —— 清 agent 运行态
- `migrations/046_v12_metrics_templates_rewrite.sql` —— 重写 metrics / wizard_config + seed 6 新 metrics
- `PHASE_EXECUTION_SUMMARY.md` 初始占位(sub-agent 完成后逐 Phase 追加)

### 验证
- SQL 文件 lint(psql --dry-run 可选)
- 文件数、顺序、依赖无循环

---

## Phase 2: Analyzer Parser 改造(sub-agent A)

### 目标
重构 Analyzer 的 Parser 层,支持 Brand / Product / Citation 的新 schema。**不执行 SQL**,代码按未来 schema 写。

### Tasks

**2.1 BrandParser**(重命名 + 去重规则)
- 文件:`geo_analyzer/src/parsers/company_parser.py` → `brand_parser.py`(git mv)
- 接口改:输入改为 `brands: List[{brand_name, aliases, is_shadow}]` + `peers: List[{primary_name, aliases}]`
- 输出改:`brand_role` enum('own' / 'shadow' / 'peer')替代 `is_client` / `is_peer`
- 去重规则:同字符串同时在 brands+peers,**brands 优先**产出 brand_role='shadow',不产 'peer' 重复记录
- 单测:`geo_analyzer/tests/test_brand_parser.py`

**2.2 ProductParser**(新建)
- 文件:`geo_analyzer/src/parsers/product_parser.py`
- 接口:输入 `tracked_products: List[{id, product_name, match_variants, product_role, shadow_sub_role, owner_brand_id, owner_brand_name, owner_peer_id, owner_peer_name}]`
- 匹配规则:`\b...\b` word-boundary,case-insensitive;variant <= 3 字符拒绝 + warning
- 去重:同一 product 在一 response 只取第一次
- 输出:List[mention dict] 含 product_role / shadow_sub_role / owner_*_name(denormalized)
- 单测:`geo_analyzer/tests/test_product_parser.py`

**2.3 CitationParser 方案 B**
- 文件:`geo_analyzer/src/parsers/citation_parser.py`(大改)
- 输出升级:从单布尔 `url_is_owned` 改为 `citation_role` enum + `matched_brand_id` + `matched_product_id`
- 两阶段匹配:
  - Stage 1:查 `geo_product_tracked_urls`(最长匹配 exact > path-prefix)
  - Stage 2:查 `geo_client_domains`(最长匹配 whole > path-prefix)
  - Stage 3:fallback 到 domain_classifier
- `citation_role` 推导逻辑(按 §6.2 表)
- 单测:`geo_analyzer/tests/test_citation_parser.py`

**2.4 Analyzer main.py Pipeline**
- 文件:`geo_analyzer/main.py`
- Phase 0 加载:brands / peers / tracked_products / domains / tracked_urls
- Phase 1 调三个 Parser
- Phase 3 写库到 `geo_brand_mentions` + `geo_product_mentions` + `geo_citations` 新字段
- 保持原 Phase 2a/2b/B(domain_classifier / sentiment)不变

**2.5 schema adapter**
- 文件:`geo_analyzer/src/core/database.py`
- SQLAlchemy Table 定义:新建 `geo_client_brands`、`geo_client_topic_products`、`geo_product_mentions`、`geo_product_sales_channels`、`geo_product_tracked_urls`、`geo_settings_candidates`
- 扩展 Table 定义:`geo_brand_mentions`(rename + brand_role)、`geo_client_domains`、`geo_citations`

### 自测
- `pytest geo_analyzer/tests/`(全绿)
- 手动 integration test:mock Roborock 数据跑一遍 Analyzer,验证 mentions 产出

### Hand-off 信号
- commit message: `feat(analyzer): v1.2 parser refactor — brand/product/citation new schema`
- Progress file: `docs/superpowers/plans/progress/phase-2-done.md`

### 依赖
Phase 1(Plan + migration SQL 存在,code 对齐新 schema 字段)

---

## Phase 3: SaaS API 后端(sub-agent B,与 Phase 2/4 并行)

### 目标
geo_saas/src 适配新 schema + 新增 endpoints + Settings CRUD 扩充。

### Tasks

**3.1 database.py 适配**
- `geo_saas/src/database.py`:新/改 Table 定义(同 Phase 2.5 结构,但此处是 geo_saas 侧)

**3.2 Settings 路由扩充**
- 文件:`geo_saas/src/routers/settings.py`
- 新 CRUD endpoints:
  - `GET/POST/PUT/DELETE /api/settings/brands`(Own + Shadow 管理)
  - `GET/POST/PUT/DELETE /api/settings/brand/{brand_id}/products`(Shadow 下 Products)
  - `GET/POST/PUT/DELETE /api/settings/peer/{peer_id}/products`(Peer 下 Products)
  - `GET/POST/PUT/DELETE /api/settings/topic_products`(Own Products)
  - `GET/POST/PUT/DELETE /api/settings/products/{product_id}/tracked_urls`
  - `GET/POST/PUT/DELETE /api/settings/products/{product_id}/sales_channels`
  - `GET/POST/PUT/DELETE /api/settings/domains`(含 brand_id/peer_id/scope)
- Onboarding 状态:
  - `GET /api/settings/onboarding_status`(返回 `onboarding_wizard_completed`)
  - `POST /api/settings/complete_onboarding`(含分支选择)

**3.3 Insights 存量适配**
- 文件:`geo_saas/src/routers/insights/visibility.py` / `citations.py` / `sentiment.py` / `prompt_metrics.py` / `analysis.py`
- 所有 `geo_company_mentions` → `geo_brand_mentions`
- 所有 `is_own_brand=true` → `brand_role='own'`
- 所有 `is_own_brand=false` → `EXISTS peers_list_check`(Peer SOV 正确性修复)
- 所有 `company_name` → `brand_name`

**3.4 Insights 新 endpoints**
- `GET /api/insights/availability?client_id=X` —— 返回 9 个 availability flag
- `GET /api/insights/product-visibility` —— 产品层 SOV + trend
- `GET /api/insights/shadow-product-cooccurrence` —— 诉求 3 量化
- `GET /api/insights/shadow-peer-product-cooccurrence` —— 诉求 4 量化
- `GET /api/insights/citation-by-role` —— citation_role 分布
- `GET /api/insights/product-sentiment-by-role` —— 产品情感
- `GET /api/insights/peer-sov-via-list` —— 竞品声量(正确性修复版)

**3.5 Brainstorming include_products 参数**
- 文件:`geo_saas/src/routers/brainstorming.py`
- `POST /api/brainstorming/generate` body 加 `include_products: bool`(默认 true)
- include_products=false 时,生成的 client_prompts.product = NULL
- Brainstorm prompt 分支:走 topic-only fallback 模板

### 自测
- `pytest geo_saas/src/tests/`
- 手动 curl 测关键 endpoint

### Hand-off 信号
- commit: `feat(saas-api): v1.2 settings CRUD + new insights endpoints`
- Progress file: `docs/superpowers/plans/progress/phase-3-done.md`

### 依赖
Phase 1(schema 契约)。**与 Phase 2/4 并行**。

---

## Phase 4: Agent NL2SQL 适配(sub-agent C,与 Phase 2/3 并行)

### 目标
Agent 模板、calculation_hint、TABLE_HINTS 全部适配新 schema;新增 6 个 metrics 和"渠道表现分析"模板。

### Tasks

**4.1 Phase 1 审阅节点(代码形式)**
- 审阅 `geo_analysis_metrics` 11 行 calculation_hint,产出 UPDATE SQL 到 `migrations/046_v12_metrics_templates_rewrite.sql`
- 审阅 `geo_report_templates.wizard_config` 2 分析模板 + 6 内容模板,产出 UPDATE SQL
- 写进 046 migration 文件

**4.2 Agent 代码适配**
- `geo_agent/src/tools/data_tools.py`:`ALLOWED_TABLES` 列表 + sample_info 更新
- `geo_agent/src/tools/chart_tools.py`:`isOwn: c["is_own_brand"]` 改为 `isOwn: c["brand_role"] == 'own'`
- `geo_agent/src/tools/utility_tools.py`:去掉 `WHERE is_own_brand=false`(列已删)
- `geo_agent/src/graphs/analyze.py`:schema hint 文本 + 硬编码 SQL 重写
- `geo_agent/src/routers/tasks.py`:硬编码 SQL + relevant_tables
- `geo_agent/src/pipelines/analysis_pipeline.py`:`TABLE_HINTS` 常量 + schema hint
- `geo_agent/src/pipelines/opportunity_pipeline.py`:硬编码 SQL
- 删除:`geo_agent/src/pipelines/_template_contracts_stub.py`(Phase 2 过渡产物)

**4.3 6 个新 metrics SQL 草稿**
- `product_sov_own`
- `shadow_cooccurrence_own_product`
- `shadow_cooccurrence_peer_product`
- `peer_sov_via_peers_list`(正确性修复)
- `citation_by_citation_role`
- `product_sentiment_by_role`
- 每个 metric 的完整 calculation_hint + relevant_tables + wizard_config 片段写进 046 migration

**4.4 "渠道表现分析"模板**
- 新建模板 JSON,写进 046 migration
- 模板 wizard_config 含 4 个 default_charts(§7.4)
- 可见性条件:`has_shadow_brands=true`

**4.5 Admin 侧同步**
- `geo_admin/src/database.py`:Table 定义同步
- `geo_admin/src/routers/clients.py` / `prompts.py` / `analysis.py`:硬编码 SQL 重写
- `geo_admin/src/routers/brainstorming.py`:**物理删除**(LEGACY 标注已久)

### 自测
- `pytest geo_agent/tests/`
- `pytest geo_admin/src/tests/`
- mock 一次 Agent Chat:"最近 Roborock 的 SOV",检查返回合理

### Hand-off 信号
- commit: `feat(agent): v1.2 NL2SQL schema adapter + 6 new metrics + shadow channel template`
- Progress file: `docs/superpowers/plans/progress/phase-4-done.md`

### 依赖
Phase 1。**与 Phase 2/3 并行**。

---

## Phase 5: SaaS UI 前端核心(sub-agent D)

### 目标
Settings 三 Tab 升级 + Onboarding Wizard + View By 切换 + 新 Tab "渠道分析" + Empty state。

### Tasks

**5.1 Settings 三 Tab 升级**
- `geo_saas/web/src/pages/SettingsPage.tsx`
- Tab 结构(§8.2):
  - 品牌 Tab:我的品牌(Own)+ 经销渠道品牌(Shadow)两区,后者默认折叠
    - Shadow 卡片展开:管理该渠道下的产品(Shadow Brand Products)
    - Shadow 卡片下:domains 子列表(scope='whole' / 'path-prefix')
  - 竞品 Tab:Peer 卡片展开 → 该竞品下的产品 + 域名
  - 追踪话题 Tab:Topic → Own Products,每 Product 卡片含 Tracked URLs + Sales Channels

**5.2 Products 表单**
- 新建 `geo_saas/web/src/components/settings/ProductEditor.tsx`
- 字段:product_name + match_variants + (Shadow 下)shadow_sub_role 选择器
- shadow_sub_role 选择器用 custom `<Select>` 三值 + 默认"不需要区分 / 不确定"

**5.3 Tracked URLs 管理**
- 新建 `geo_saas/web/src/components/settings/TrackedUrlsEditor.tsx`
- 字段:url + url_scope(radio: 精确 URL / 路径前缀)+ 自动推导的 brand_id
- 前端实时校验:URL host 必须在已配置 domains 中,不在就 warning
- "触发 Auto-discovery" 按钮

**5.4 Sales Channels 管理**
- 新建 `geo_saas/web/src/components/settings/SalesChannelsEditor.tsx`
- 在 Product 卡片上展示"销售渠道"标签列表 + 多选添加

**5.5 Onboarding Wizard**
- 新建 `geo_saas/web/src/components/onboarding/OnboardingWizard.tsx`
- 首次登录(`onboarding_wizard_completed=false`)触发 Dialog
- 4 分支(§8.6):自营 / OEM / 两者 / 跳过
- OEM 分支完成后追加步骤:"添加在同一渠道上销售的竞争 SKU"(引导 Peers Tab)
- 完成后调 `/api/settings/complete_onboarding` 写 true

**5.6 View By 切换器**
- 修改 `geo_saas/web/src/components/insights/GlobalFilterBar.tsx`(或等价组件)
- 加入 "视图维度" 下拉:品牌 / 产品 / 话题 / 交叉
- 默认 "品牌"(向后兼容 Roborock 无感)
- 条件显示:`has_own_products=false` 时不显示产品维度

**5.7 新 Tab "渠道分析"**
- 新建 `geo_saas/web/src/pages/insights/ChannelAnalysisPage.tsx`
- 路由注册:`/insights/channel-analysis`
- 可见性:`has_shadow_brands=true` 才显示导航入口
- 4 个核心 chart:
  - 经销渠道 × 自家产品共现趋势(折线)
  - 经销渠道产品分布矩阵(热图,native/resale/NULL)
  - 自家产品多渠道分布对比(柱状)
  - 渠道 Citation 分布(按 citation_role)

**5.8 存量 Dashboard SQL 结果适配**
- `VisibilityDashboard.tsx`:`company_name` → `brand_name`,`is_own` 从 `brand_role==='own'` 派生
- 其他存量 chart 同理
- 视觉保持不变(Roborock 无感)

**5.9 Empty State + 数据驱动可见性**
- 新建 `geo_saas/web/src/components/EmptyStateCard.tsx`(§8.5 结构)
- 全前端接入 `/api/insights/availability` 驱动 chart 显示/隐藏
- 所有 chart 在对应 availability flag 为 false 时返回 EmptyStateCard

**5.10 Admin Web 同步**
- `geo_admin/web/src`:如有引用 `is_own_brand` / `company_name` / `topic.products` 的地方同步适配(grep 检查)

### 自测
- `npm run build`(全绿)
- `npm run lint`
- 视觉回归:用开发服务器跑 Roborock 数据,截图对比

### Hand-off 信号
- commit: `feat(saas-ui): v1.2 settings + onboarding wizard + view-by + channel analysis tab`
- Progress file: `docs/superpowers/plans/progress/phase-5-done.md`

### 依赖
Phase 3(API contracts 出来)

---

## Phase 6: Suggestions 系统(sub-agent E)

### 目标
三路(N-gram / LLM Batch / Auto-discovery)产出 Suggestions,UI 统一消费。

### Tasks

**6.1 N-gram Fallback**(MVP 备份)
- 新建 `geo_analyzer/src/parsers/ngram_extractor.py`
- 算法:
  - 对 response text 抽 2-5 字符/词子串
  - Heuristic filter(长度 >= 4,含数字或连字符,大写开头)
  - 排除已在 match_variants / aliases
  - UPSERT 到 `geo_settings_candidates`(source='n_gram')
- 可选 main.py 集成为 Phase 1.5(可跳过)

**6.2 Phase 2 LLM Batch**(本轮主力)
- 新模块:`geo_analyzer/src/jobs/llm_batch_discovery.py`
- Cloud Scheduler job(Terraform 配置新建)
- 读取近 24 小时 `geo_results.cloro_response`
- 按客户分批 → Vertex AI Batch Prediction(Gemini Flash Batch)
- Prompt:提取 response 里未在配置中的 Brand/Product/SKU 候选
- UPSERT 到 `geo_settings_candidates`(source='llm_batch')
- Terraform 文件:`geo_analyzer/terraform/main.tf` 新建 Cloud Scheduler + Cloud Run Job

**6.3 Auto-discovery**(Onboarding 触发)
- 新建 `geo_saas/src/routers/auto_discovery.py`
- `POST /api/auto_discovery/run` body: `{target_url, target_type(own/shadow/peer), instruction}`
- 实现:
  - 多层爬取:robots.txt → sitemap.xml → HTML nav → LLM grounding fallback
  - LLM 分类 Products / Brands / Peers / URLs
  - Grounding sources 作为 tracked_url 候选
- 结果写 `geo_settings_candidates`(source='auto_discovery')

**6.4 Suggestions UI**
- 新建 `geo_saas/web/src/components/settings/SuggestionsPanel.tsx`
- Per-Tab banner:每 Tab 顶部显示"💡 AI 发现 N 条候选"
- 点击展开列表:候选字符串 / 频次 / 样例 response 链接 / [加入到...] 下拉 / [忽略]
- 全局入口:Settings 顶部"AI 建议"按钮,聚合所有 status='pending'

**6.5 Settings CRUD for candidates**
- `geo_saas/src/routers/settings.py` 追加:
  - `GET /api/settings/candidates?type=X&status=pending`
  - `POST /api/settings/candidates/{id}/accept`(连带 INSERT 到目标表)
  - `POST /api/settings/candidates/{id}/reject`
  - `POST /api/settings/candidates/{id}/ignore`

### 自测
- pytest(新 job + endpoints)
- UI dev 模拟 candidates 数据,验证挑入流程

### Hand-off 信号
- commit: `feat(suggestions): n-gram + llm batch + auto-discovery unified pipeline`
- Progress file: `docs/superpowers/plans/progress/phase-6-done.md`

### 依赖
Phase 3(candidates CRUD)+ Phase 5(UI 基础设施)

---

## Phase 7: Tooltip 系统 + 前端汉化(sub-agent F)

### 目标
接入 Tooltip 组件 + 15 条核心文案 + 本轮新增 UI 全中文。

### Tasks

**7.1 Tooltip 组件封装**
- 新建 `geo_saas/web/src/components/ui/HelpTooltip.tsx`(封装 shadcn `<Tooltip>`)
- 统一视觉:14px 灰色 ⓘ 图标 + hover/click 展开
- 支持 markdown 文案 + 链接到 help docs(占位 href)

**7.2 i18n dictionary 初始化**
- 新建 `geo_saas/web/src/i18n/zh-CN.ts`
- 组织结构:按 page/component 分 key
- 本轮新增所有 UI 文案录入(Settings / Onboarding / Dashboard / Suggestions)
- 保留英文术语(SKU / Agent / AI / URL / API)

**7.3 15 条核心 Tooltip 接入**
- 按 Spec §10.2 清单,位置 + 文案对应写入
- Settings 相关 8 条
- Dashboard 相关 5 条
- Onboarding 相关 2 条

**7.4 术语表应用**
- 按 Spec 附录 C 术语表,全扫描前端代码,替换硬编码英文为 i18n key 引用
- 重点:"Shadow Brand" / "shadow_brand_native" / "resale" 等**不得**出现在前端文案

**7.5 Admin Web(如有必要)**
- 本轮 Admin Web 不做汉化(已在 Roadmap)
- 仅修改本轮新字段的 label

### 自测
- `npm run build`
- 视觉 QA:每个新 Tooltip 出现点 hover 检查

### Hand-off 信号
- commit: `feat(i18n): v1.2 tooltip system + chinese ui localization for new features`
- Progress file: `docs/superpowers/plans/progress/phase-7-done.md`

### 依赖
Phase 5(UI 主体完成)

---

## Phase 8: 部署 + 验证(用户手动,醒来后)

### 步骤(用户执行)

```
1. 审阅 sub-agent 产出的 diff(git log + git diff origin/main)

2. 执行 Migration SQL(按顺序):
   - 040_v12_new_tables.sql
   - 041_v12_extend_existing.sql
   - 042_v12_rename_mentions.sql
   - 043_v12_data_migration.sql
   - 044_v12_drop_legacy.sql
   - 045_v12_truncate_agent_state.sql
   - 046_v12_metrics_templates_rewrite.sql

3. 本地验证:
   - 跑 Analyzer 一轮,确认新 mentions 产出正常
   - 启动 SaaS API + Web,Roborock 登录看 Dashboard 无感

4. GCP 部署:
   - 版本号 bump
   - `bash deploy_all.sh`(或分模块)
   - Terraform apply

5. GCP 线上验证(Checklist):
   □ Roborock 登录 SaaS UI,Visibility / Citation / Sentiment 三页可视化等价部署前
   □ Tmax 新工作空间,Onboarding Wizard 弹出
   □ 可手动配置 Shadow Brand(RC)+ Peers + Products
   □ 新建 Tracked URL,Trigger 正确拒绝错配(arb.com URL 挂给 HT-70911)
   □ AI Suggestions 面板 24 小时后有数据(Cloud Scheduler 跑完第一轮 LLM Batch)
   □ Chat with Anthony:"最近 Roborock 的 SOV" 返回合理数
   □ 新 Tab "渠道分析" 只对 Tmax 可见,Roborock 不可见
   □ Tooltip hover 显示正确中文
```

---

## Blocker 记录协议

所有 sub-agent 遇阻时,在 `docs/superpowers/plans/progress/blockers.md` 追加一行:

```
## [Phase N] <task-id> - <short description>
- 时间:YYYY-MM-DD HH:MM
- 具体阻塞:<详细>
- 已尝试:<方案>
- 建议:<给用户醒来后决策>
```

不强推 workaround,留给用户清醒时决策。

---

## 最终产出清单

sub-agent 全部完成后,我(主 Claude)产出:

- `docs/superpowers/plans/progress/PHASE_EXECUTION_SUMMARY.md` —— 每 Phase commit / 改动文件 / 自测结果 / 剩余问题
- 本 Plan 文件更新(如有 Phase 内部调整)
- 最终 commit 给用户:"feat(dual-mode-v1.2): all phases autonomous execution complete"

---

*本 Plan 由主 Claude(ID: session-2026-04-20)起草,执行期间 sub-agent 可追加 Phase 内部 task 细化,但不得跳过 Phase 或改变依赖顺序。*
