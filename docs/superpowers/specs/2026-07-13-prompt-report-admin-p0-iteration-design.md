# Prompt、Report 与 Admin P0 迭代技术规格

**日期：** 2026-07-13  
**状态：** Final / Implementation and Code Review Verified  
**需求范围：** 原始需求 16–20，按最终确认的 8 个可独立验收 Feature 重构  
**涉及模块：** `geo_saas`、`geo_admin`、`geo_common`、Cloud SQL migration  

## 1. 背景与目标

原始输入以需求 16–20 编号，但该编号把多个可独立实施和验收的能力合并在一起。为避免实现阶段
“完成主功能但遗漏附属功能”，本规格以最终讨论确认的 8 个 Feature 作为唯一 Scope 与验收单元。

| Feature ID | 最终功能点 | 原始来源 | 独立完成标准 |
|---|---|---|---|
| F1 | Prompt 拆分到 Sidebar | 16.1 | Visibility 不再包含 Prompt Tab；Sidebar 顺序、双语名称、路由兼容完整 |
| F2 | Topic/Product/Prompt 动态下钻补齐 V/C/S | 16.1 | 三种入口均组合现有动态 Visibility、Citation、Sentiment，全部子查询应用相同 target filter |
| F3 | Prompt Intent Filter | 16.2 | 筛选项由 active Global Config 和当前租户历史值实时生成，不硬编码三种名称 |
| F4 | Prompt CSV 批量上传 | 17 | Template、Allowed Values、Preview、校验、事务 Commit、审计和 Undo 全链路可用 |
| F5 | 固定日期范围的动态报告与上一等长周期比较 | 18.1 | 报告只固化 client、日期范围和筛选元数据；页面完全复用动态 Dashboard V/C/S API，current、previous 与 delta 均动态计算 |
| F6 | 所有列表的指标列全局排序 | 18.2 | 动态、下钻、在线动态报告的 Metric 列先全量排序再分页；维度列不排序；离线 HTML 不排序 |
| F7 | Admin Brand Alias 数据源对齐 | 19 | Admin 按 brand_id 读写 `geo_client_brands.aliases`；SaaS、Analyzer、Schema 均不改 |
| F8 | Workspace 引导式清理与安全删除 | 20 | Readiness、停止调度、分批级联清理、Topic 清理、名称确认和最终删除保护完整 |

任何 Feature 只有在其 UI、API、数据语义、异常处理、租户隔离、测试和验收条件全部满足时才算完成。
不得因为原始编号把 F1–F3 或 F5–F6 合并在同一需求中，就将其中任何一项视为可选或隐含范围。

本规格基于当前工作区代码和 2026-07-13 Cloud SQL 只读核查结果，不以 Git HEAD 或历史文档代替真实实现。

### 1.1 文档优先级与实现约束

后续发生描述冲突时，优先级依次为：

1. 本文各 Feature 的“明确契约”和“验收条件”。
2. 第 2 节记录的最终产品决策。
3. 当前动态 Dashboard 的既有指标定义和数据结构。
4. 原始需求 16–20 的简写描述。

实现不得从旧 Prompt Tab、静态报告查询代码或 legacy Alias 字段反向推导并覆盖本文已经确认的决策。
数据库 DDL 只通过 migration 文件交付；不在开发或验证过程中直接修改 Cloud SQL Schema。

## 2. 已确认的产品决策

### 2.1 Prompt 信息架构

- 从 Visibility 页顶部移除 Prompt Tab。
- Sidebar 顺序为：Visibility → Citation → Sentiment → Prompt → Report。
- zh-CN 与 en-US 均显示 `Prompt`。
- Prompt 页面主体沿用现有 `/insights/prompts` 页面；路由继续复用现有 Insights filter context。
- `/prompts` 兼容跳转保留，避免旧链接失效。

### 2.2 动态下钻数据来源

- 动态下钻只复用动态 Dashboard 的 API、指标定义和图表组件。
- 静态报告不是动态下钻的数据来源，也不是其查询实现参考。
- Topic、Product、Prompt 下钻均组合完整的动态 Visibility、Citation、Sentiment 区块。

### 2.3 Intent 筛选

- 筛选依据是 `geo_client_prompts.intent` 的实际值，不是 Visibility/Citation/Sentiment category。
- 筛选项以 `geo_global_intents` 中 `is_active=true` 的配置为主，禁止前端硬编码枚举。
- 数据中仍存在但不在启用 Global Config 中的值，显示在“未配置 Intent”分组中，仍允许筛选历史数据。
- 新建与导入 Prompt 只能使用启用的 Global Config Intent；历史未配置值不得作为新写入值。

### 2.4 CSV 输入方式

- 第一版只支持本地 CSV 文件上传。
- 用户可以从飞书表格导出 CSV，但系统不直接读取飞书表格链接，也不引入飞书授权依赖。
- 所有 CSV Header 使用英文。
- 导入 Dialog 提供 `Import CSV` 与 `Allowed Values` 两个 Tab。
- 分别提供 Import Template CSV 和当前 Workspace Allowed Values CSV 两个下载入口；第一版不增加 XLSX 上传。

### 2.5 报告比较口径

- 本轮实现“当前选择区间 vs 紧邻的等长上一周期”。
- 1 天对前 1 天，7 天对前 7 天，30 天对前 30 天。
- 规格和代码中使用 `previous_period` / period-over-period，避免将其误写成严格意义的上一年同期 YoY。
- 若未来需要真正的去年同期比较，应另开需求，不复用本轮 previous-period 字段表达不同语义。

### 2.6 在线与离线静态报告

- SaaS 内通过 report_id 打开的在线 Snapshot 报告支持列表排序。
- 排序 API 只能读取该 report_id 已冻结的 Snapshot 数据，不能回退到当前动态 Dashboard 数据。
- 导出的离线 HTML 不提供交互排序；按导出时的默认顺序呈现。

### 2.7 Brand Alias

- SaaS 与 Analyzer 继续以 `geo_client_brands.aliases` 为事实源。
- 只修改 Admin UI/API，使其读写同一品牌表。
- 不修改 SaaS UI、Analyzer、现有表结构或 legacy `geo_clients.aliases` column。

### 2.8 Workspace 删除

- 第一版采用“引导式清理 + 删除保护”，不建设持久化异步 Workspace 删除任务系统。
- 清理顺序为：停止调度 → 分批删除 Prompts → 删除 Topics → 返回 Admin 最终删除 Workspace。
- Prompt 删除复用现有 `PromptCascadeDeletionService`。
- 最终删除要求输入 Workspace 名称，并在请求期间禁用按钮。

## 3. Cloud SQL 事实基线

### 3.1 Intent

当前启用 Intent：

- `Solution Discovery`
- `Specifics Inquiry`
- `Competitive Evaluation`

Prompt 数据另有历史值 `general`：Pandaaa 共 4 条物理行、1 个 logical concept。

全库没有 NULL/空 Intent；Prompt 与 Topic 的 tenant 归属错误为 0。

### 3.2 Prompt 重复数据

- 全库存在 8 组 exact duplicate Prompt variant。
- 共存在 10 条额外重复物理行。
- 重复集中在 AnswerX 与 Pandaaa。

因此导入 Preview 必须同时识别：

- CSV 文件内部重复。
- 数据库已有 exact variant。
- 数据库已有 logical concept 但缺少部分平台/国家组合。
- 相同 variant 的 Intent/Product 冲突。

### 3.3 Alias 分叉

真实数据已出现以下情况：

- canonical aliases 有值但 legacy aliases 为空。
- canonical 与 legacy 内容不完全相同。
- 仅少数 Workspace 两边完全一致。

因此 Admin 继续编辑 `geo_clients.aliases` 会产生误导，且不会影响 Analyzer。

### 3.4 静态报告

- 当前有 17 份 `static-report-v2` COMPLETED Snapshot。
- 所有 Snapshot 的 `visibility_score_change`、`avg_position_change`、`own_domain_share_change`、`positive_pct_change` 均为空。
- Visibility/Citation previous series 均为 0 点。
- 当前 Snapshot 列表存在 20/50/100 等 materialization 上限。
- Snapshot 大小从约 53 KB 到约 4 MB。

### 3.5 Workspace 数据量

Dreamina 当前约有：

- 14,400 Prompt rows
- 326,520 Tasks
- 313,989 Results
- 3,492,352 Citations
- 777,471 Brand Mentions

全库主要事实表体量约为：

- `geo_results`：5.3 GB
- `geo_citations`：3.3 GB
- `geo_tasks`：403 MB
- `geo_brand_mentions`：317 MB

这意味着“在一个请求中删除全部 Prompt”仍会形成长事务，必须有界分批。

## 4. F1：Prompt 拆分到 Sidebar

### 4.1 Sidebar 与路由契约

前端改动：

- 从 Visibility 页面 Tab 配置中移除 Prompt。
- 在 Sidebar 的 Sentiment 和 Report 之间增加 Prompt item。
- zh-CN/en-US 的 Sidebar 文案均为 `Prompt`。
- Sidebar 链接指向现有 Prompt 页面路由；现有 `/prompts` redirect 保留。
- Prompt 页面继续使用 Insights 的 Date、Topic、Platform、Country filter context。

### 4.2 UI 状态与兼容行为

- 选中 Prompt 路由时，Sidebar 的 Prompt item 必须处于 active 状态，Visibility 不得继续高亮。
- 用户从旧 `/prompts` URL、书签或站内旧链接进入时，必须无损跳转到正式 Prompt 路由；不得出现 404 或双重页面。
- 从 Visibility 删除的只是 Prompt Tab 入口，不删除 Prompt 页面、Prompt API、导出能力或现有筛选状态。
- Prompt 页面使用既有 Insights Date、Topic、Platform、Country filter context；从其他 Insights 页面切换到 Prompt 时保留兼容筛选状态。
- Sidebar 收起、展开、移动端布局和权限过滤均沿用现有 Sidebar item 行为，不为 Prompt 创建第二套导航状态。

### 4.3 F1 明确非目标

- 不重新设计 Prompt 页面主体视觉结构。
- 不改变 Visibility 页面现有 Visibility 与 Query Refine 内容。
- 不删除旧路由兼容层。
- 不把 Prompt 移到 Report 或 Settings 分组。

## 5. F2：Topic、Product、Prompt 动态下钻补齐 Visibility、Citation、Sentiment

### 5.1 Logical Prompt 语义

一个 UI Prompt 可以代表多个 `geo_client_prompts.id`。数据库中每个物理行只保存一个
`platform + country + language` 组合；UI/Repository 再把同一逻辑 Prompt 的物理行聚合展示。

Logical Prompt key 统一为：

```text
client_id + topic_id + normalized_prompt_text + normalized_product
+ normalized_intent + normalized_language
```

其中：

- `normalized_prompt_text = lower(trim(collapse_whitespace(text)))`
- `normalized_product = lower(trim(product or ""))`
- `normalized_intent` 使用 active Global Config 的 canonical intent name；历史行使用 trim 后原值
- `normalized_language` 使用 client config_languages 的 canonical value

Prompt 下钻必须传入该 logical Prompt 包含的全部 `prompt_ids`，不能只传第一条物理记录。
相同 Prompt 文本在不同 Language 或 Intent 下是不同 logical Prompt；相同 logical Prompt 的
Platform/Country variants 聚合显示，但数据库仍保留为多条物理记录。

### 5.2 动态 API 能力矩阵

当前与目标能力：

| 目标 | Visibility | Citation | Sentiment |
|---|---|---|---|
| Topic | 已支持 | 已支持 | 已支持 |
| Product | 已支持 | 增加 filter | 主聚合已支持；明细接口补齐 filter |
| Prompt IDs | 已支持 | 增加 filter | 增加 filter |

不新增一套独立的“Prompt Analysis metrics API”。优先扩展现有动态端点：

#### Citation

以下现有端点增加可选参数：

```text
products: comma-separated product names
prompt_id: UUID
prompt_ids: comma-separated UUIDs
```

适用端点：

- `/api/insights/citations/share`
- `/api/insights/citations/ranking`
- `/api/insights/citations/categories`
- Citation Dashboard 使用的 domain/page list APIs

参数进入统一 citation filter context，并同时作用于：

- current period
- previous period
- KPI
- time series
- domain ranking
- page ranking
- category breakdown
- expandable/detail list

Product filter 以 `geo_client_prompts.product` 为语义来源。Cloud SQL 已验证 344,974 条 Result 与 Prompt Product 0 条不一致。

#### Sentiment

主 `/api/sentiment` 已支持 `products`，增加：

```text
prompt_id: UUID
prompt_ids: comma-separated UUIDs
```

以下关联端点也必须接受并应用相同 filter：

- `/api/sentiment/theme-results`：补齐现有主接口已经支持的 `products`，并新增 `prompt_id/prompt_ids`
- Sentiment expandable/detail list APIs

Filter 同时作用于 current、previous、summary、series、themes 和展开结果。

#### Visibility

继续复用现有 `topic_ids`、`product`、`prompt_id/prompt_ids` 能力，不另建 SQL 或指标口径。

### 5.3 下钻入口与页面编排

三种 target 的稳定 identity：

| Target | Route identity | Server-side resolution |
|---|---|---|
| Topic | `topic_id` | 校验 topic 属于 JWT client_id |
| Product | canonical product value + 当前 Topic filter scope | 在 client scope 内按 `geo_client_prompts.product` 过滤；空 Product 不生成下钻入口 |
| Prompt | 一个 representative physical `prompt_id` | 先按 client_id 读取该行，再按第 5.1 节 logical key 解析全部 variant IDs |

Prompt route 不把 Prompt 原文或任意长度的全部 UUID 列表放入 URL。新增 tenant-scoped concept resolution
能力，使 representative prompt_id 在刷新/复制链接后仍能恢复 logical Prompt 和全部 variant IDs；若代表行已删除，
返回 404 和可返回 Prompt 列表的 empty state，不退化成跨 concept 查询。

下钻页面按以下顺序展示：

1. Target header 与返回入口。
2. Visibility 动态 Dashboard。
3. Citation 动态 Dashboard。
4. Sentiment 动态 Dashboard。

三部分共享：

- date_from/date_to
- interval
- selected platforms
- selected countries
- 下钻 target filter

Topic 下钻时 target Topic 替代全局 Topic selection；Product/Prompt 下钻继续叠加全局 Topic filter，前提是二者不冲突。

所有请求必须携带 JWT 派生的 client_id；前端 query string 中的 client_id 不能成为授权依据。

### 5.4 Filter 传播与页面状态

- Topic、Product、Prompt 三种下钻入口都从对应列表行的 hover action icon 进入；点击行内其他交互不得误触发下钻。
- URL/route state 必须显式保存 target type 和稳定 target identity，使刷新、后退和复制链接后仍能恢复同一分析对象。
- Header 显示 target type、canonical display name、所属 Topic/Product 上下文和返回入口；Prompt Header 显示 logical Prompt 文本而非任一随机 physical ID。
- Visibility、Citation、Sentiment 三个区块分别管理 loading/error/empty state；某一域失败不得阻止其他已成功域渲染。
- 全局 Date、Platform、Country 变化后，三域必须使用同一份 filter snapshot 重新请求，不能出现一部分使用旧筛选、一部分使用新筛选。
- target filter 是强制约束：用户不能通过全局筛选把下钻页面扩大到其他 Topic/Product/Prompt。
- 如果全局筛选与 target 无交集，显示 target-scoped empty state，不静默移除 target filter。
- 页面卸载或 filter 变化时取消旧请求，防止慢响应覆盖新 target 的数据。

### 5.5 F2 数据来源红线

- 只复用动态 Dashboard 的指标函数、响应模型、图表与列表组件。
- 不调用 Static Report section API，不读取 `snapshot_json`，不复制 Snapshot builder 的 SQL。
- Citation/Sentiment 缺失能力通过扩展现有动态 filter context 实现，不创建平行的 Prompt-only metric definitions。
- current/previous、summary/series/ranking/detail 必须共享同一个 target predicate builder，禁止只给首屏聚合加 filter。

### 5.6 F2 明确非目标

- 本轮强制新增的完整下钻 target 只有 Topic、Product、Prompt。
- 现有 Country group/list 保留，F6 仍覆盖其中的 Metric 列排序；本轮不为 Country 新建完整 V/C/S 下钻。
- 不为下钻复制一份独立的 Dashboard component tree；允许增加组合 shell 和 filter adapter。
- 不改变动态 Dashboard 既有指标公式、品牌定义或 previous-period 口径。

## 6. F3：Prompt Intent Filter

### 6.1 Facet API 与 UI

新增 tenant-scoped facet endpoint：

```text
GET /api/prompts/intent-facets?client_id={client_id}
```

返回：

```json
{
  "active": ["Solution Discovery", "Specifics Inquiry", "Competitive Evaluation"],
  "unconfigured": ["general"]
}
```

其中 `unconfigured` 只包含当前 client Prompt 实际存在、但不在 active Global Config 中的 distinct 值。Prompt 页面加载时获取：

1. `geo_global_intents` 中 active Intent。
2. 当前 client Prompt 中 distinct historical Intent。

渲染分组：

- Active Intents
- Unconfigured Intents（仅在存在时显示）

筛选参数直接传 literal intent names；不再复用旧 `prompt_type` category 语义。

移除 Prompt Editor 中所有 `|| "general"` 默认值。创建时 Intent 必选，或由后端返回明确 validation error。

### 6.2 筛选与写入语义

- Intent Filter 位于 Prompt 页面现有 Filter 区，与 Topic/Product/Platform/Country 等筛选共同生效。
- Filter 可以选择 active Intent，也可以选择“Unconfigured Intents”分组中的历史 literal value。
- 多选 Intent 时采用 OR；与其他 Filter 之间采用 AND。
- 清空 Intent Filter 表示不限制 Intent；不得默认只显示三个 active Intent 而隐藏历史数据。
- Facet 返回 canonical literal values；UI Label 可本地化，但请求参数必须传原始 value。
- Global Config 增删或停用 Intent 后，下次请求立即反映，无需前端发版。
- 新建、复制和 CSV 导入只允许 active Intent；历史 unconfigured value 只读、可筛选、不可作为新写入值。

### 6.3 错误与空状态

- Global Config 查询失败时不得回退到前端硬编码三项；显示可重试错误，同时保留 Prompt 主列表可用性。
- 当前租户没有历史值时不显示 Unconfigured 分组。
- Prompt 数据中出现 NULL/空值时统一归入 Unconfigured display bucket，但新写入仍拒绝空值。
- 选择的 Intent 被管理员停用后，下一次提交或刷新应返回明确失效提示，不静默改写成其他 Intent。

## 7. F4：Prompt CSV 批量上传

### 7.1 复用 Published Pages 交互骨架

直接复用以下模式：

- Download Template action
- 隐藏 file input，接受 `.csv,text/csv`
- UTF-8 BOM
- 服务端文件大小和行数限制
- Preview Dialog
- Total/Create/Skip/Conflict/Invalid 统计卡片
- 行号、展开数量、action、errors 列表
- invalid/conflict > 0 时禁用 Commit
- Commit 前服务端重新构建 Preview
- 自定义 Dialog，不使用原生 browser dialog

导入安全上限固定为：

- 原始 CSV 最大 10 MB。
- 单次最多 2,000 个非空输入行，不含 Header 和完全空行。
- 单行 Platform × Country 展开后最多 100 个 physical variants。
- 单次 Preview/Commit 展开后最多 20,000 个 physical variants。
- 超出任一上限时整批拒绝并返回具体 limit、actual count 和建议拆分批次；不得截断后部分导入。

### 7.2 CSV Header

固定 Header 顺序：

```csv
Customer Name,Topic,Product,Prompt,AI Platforms,Countries,Language,Intent
```

字段定义：

| Header | 必填 | 规则 |
|---|---:|---|
| Customer Name | 是 | 必须与当前 JWT workspace 的 canonical client name 完全匹配 |
| Topic | 是 | 当前 workspace 中已存在的 Topic；不自动创建 |
| Product | 否 | 若有值，必须属于该 Topic 的 active Product |
| Prompt | 是 | trim 后非空；参与 logical concept normalization |
| AI Platforms | 是 | 支持英文半角 `,`、`;`、`\|` 分隔多值；值必须同时属于 Global active platforms 与 client allowlist |
| Countries | 是 | 支持英文半角 `,`、`;`、`\|` 分隔多值；使用 client allowlist 中的 canonical country code |
| Language | 是 | 每行单值；必须属于 client config_languages |
| Intent | 是 | 必须精确匹配 active Global Config Intent |

不在 CSV 中增加 Customer ID。安全双重匹配由以下两层完成：

1. JWT/current workspace 提供不可由 CSV 覆盖的 client_id。
2. CSV `Customer Name` 必须与该 client_id 对应的 canonical name 匹配。

### 7.3 多值与展开规则

每一行代表一个 logical Prompt 定义。

支持多值：

- AI Platforms
- Countries

每行单值：

- Language
- Intent
- Topic
- Product
- Prompt

多值解析规则：

- 支持英文半角逗号 `,`、分号 `;` 和竖线 `|`。
- 自动 trim 每个 token、忽略空 token、按 canonical value 去重。
- 允许值按大小写不敏感匹配配置，Preview 和持久化统一转换为 canonical value。
- 不支持中文全角 `，`、`；`；检测到时整行 invalid，并提示使用英文半角符号。
- 由于逗号同时是 CSV 列分隔符，单元格内使用英文逗号多值时必须由标准 CSV writer 加双引号，
  例如 `"chatgpt,gemini"`。分号和竖线不需要额外 quoting。

示例：

```csv
Customer Name,Topic,Product,Prompt,AI Platforms,Countries,Language,Intent
Example Workspace,Robot Vacuum,S8,"What is the best robot vacuum?",chatgpt|gemini,US|GB,en-US,Solution Discovery
```

展开为：

```text
chatgpt × US × en-US
chatgpt × GB × en-US
gemini × US × en-US
gemini × GB × en-US
```

Language 不支持同一行多值，因为多语言与多国家之间没有无歧义的一一映射。若同一 Prompt 需要不同 language/country 组合，用户拆成多行。

多行输入完全支持。Preview 先把每一行展开成物理 variant，再以 exact variant key 全文件归一化：

- 相同 logical Prompt、不同 Platform/Country：生成不同物理行，UI 聚合为同一 logical Prompt。
- 相同 Platform/Country、不同 Language：生成不同物理行，并按现有语义显示为不同 logical Prompt。
- 同一物理 variant 被多行重复声明：只保留第一次作为候选，其余行标记 file duplicate 并指向首次出现行。
- CSV 多值写法与多行写法最终得到相同的 canonical physical variants；不把多个组合存入单条数据库记录。

### 7.4 Import Dialog 与 Allowed Values

Prompt 批量上传继续使用自定义 Dialog；本地文件选择使用标准 file input/系统文件选择器，
但确认、错误和结果反馈不得使用 `window.alert`、`window.confirm` 或 `window.prompt`。Dialog 包含：

1. `Import CSV` Tab
   - 下载 Import Template CSV。
   - 选择或拖入本地 CSV。
   - 展示文件名、大小、输入行数、展开后的 variant 数量与 quota impact。
   - 展示 Preview 表格、行级 action/error/warning，并在 commit 前二次确认。
2. `Allowed Values` Tab
   - 在页面内按类型列出当前 Workspace 可用的 Topic、Product、AI Platform、Country、Language 和 Intent。
   - Product 必须显示所属 Topic，避免同名 Product 产生歧义。
   - AI Platform 只显示 Global active 与 Workspace config_platforms 的交集。
   - Country/Language 显示 Workspace config 中允许的 canonical value；Intent 只显示 active Global Config。
   - 提供搜索、复制单个 canonical value，以及下载 Allowed Values CSV。

两个 Tab 读取同一个 tenant-scoped allowed-values service，Preview 也复用相同的 canonical resolver，
避免 UI 展示值、下载枚举和后端校验出现三套口径。client_id 必须来自认证后的当前 Workspace context，
且每次查询都执行 tenant ownership 校验，不能信任 CSV 内容或可被用户任意覆盖的 client_id。

接口边界固定为：

```text
GET /api/prompts/import/template.csv
GET /api/prompts/import/allowed-values
GET /api/prompts/import/allowed-values.csv
```

- JSON allowed-values endpoint 服务 UI Tab。
- CSV endpoint 与 JSON endpoint 调用同一 service，只负责序列化格式差异。
- Template/Allowed Values 响应禁止缓存跨 Workspace 数据；客户端切换 Workspace 后必须重新请求。

Allowed Values CSV 固定使用英文 Header：

```csv
Type,Value,Label,Parent Type,Parent Value,Notes
```

其中：

- `Type` 取 `Topic`、`Product`、`AI Platform`、`Country`、`Language`、`Intent`。
- `Value` 是 CSV 导入时应填写的 canonical value。
- `Label` 是当前 UI locale 下的展示名；导入只解析 `Value`，不解析翻译后的 Label。
- Product 行使用 `Parent Type=Topic`、`Parent Value=<canonical topic name>` 表达归属。
- Platform 如存在国家限制，可在 `Notes` 中列出 supported country codes；Preview 仍以后端配置为准。

### 7.5 Template Sample Data

Template endpoint 必须从认证后的当前 Workspace context 解析并校验 client_id，因此模板是 workspace-aware 的。

Sample rows：

- `Customer Name` 使用当前 canonical client name。
- Topic/Product 使用当前 workspace 已存在的 canonical 值。
- Platform/Country/Language 使用该 workspace 真实 allowlist。
- Intent 使用当前 active Global Config 值。
- 固定提供两行 Sample：第一行展示单值，第二行展示 `|` 多值。
- Prompt 使用明确占位符 `[REPLACE WITH YOUR PROMPT]`。

Preview 把未替换的 Prompt placeholder 标记为 invalid，防止用户直接提交模板示例数据。

若当前 Workspace 尚无 Topic，模板只返回 Header；下载动作同时提示用户先创建 Topic，不自动为导入创建 Topic。

### 7.6 Preview 校验顺序

1. UTF-8/BOM、Header、文件大小、最大行数。
2. Customer Name 与 current client 匹配。
3. Topic 属于 current client。
4. Product 为空或属于该 Topic。
5. Prompt normalization 后非空。
6. Intent 属于 active Global Config。
7. Platform 属于 active Global platform 且属于 client config_platforms。
8. Country 属于 client config_countries。
9. Language 属于 client config_languages。
10. 每个 platform-country 组合满足 Global platform supported_countries。
11. 单行展开数量、文件总展开数量与 quota。
12. 文件内 logical/exact duplicate。
13. 数据库已有 logical/exact variants。

任何单行出现不支持的组合时，该 CSV row 整体 invalid，不做部分写入。

### 7.7 Duplicate 与 Conflict 语义

定义 exact variant key：

```text
client_id + topic_id + normalized_prompt_text + normalized_product
+ platform + country + language
```

Preview action：

- `create`：variant 不存在。
- `skip`：exact variant 已存在，且 Intent/Product 元数据一致。
- `conflict`：exact variant 已存在，但 Intent/Product 不一致。
- `invalid`：字段、归属、allowlist、quota 或文件内重复错误。

行为：

- Skip 是幂等成功，不重复插入。
- Conflict 阻止整个 commit，不自动覆盖现有 Prompt。
- 同一 normalized Prompt 出现在不同 Topic 时允许，但 Preview 显示 warning；当前 quota 语义本来就是 `(text, topic_id)`。
- Commit 只写 create variants。

### 7.8 Commit、审计和回滚

Commit 流程：

1. 重新解析原始 CSV。
2. 重新运行完整 Preview。
3. 获取 client-scoped advisory transaction lock。
4. 在同一事务中重新检查 quota/existing variants。
5. 批量写入 create variants。
6. 校验实际插入数等于 expected create count。
7. 写入 import batch audit record。
8. 提交事务。

Repository 必须使用真正的批量参数写入策略，不能对 20,000 个 variants 在应用层逐条 acquire/commit；
同一个 Import Commit 只有一个数据库事务。任何异常回滚 prompts 和 audit record，不能留下半个 batch。

不执行 CSV 中的 SQL，不生成 SQL hash。审计保存：

- raw CSV SHA-256
- normalized expansion manifest SHA-256
- source filename
- client_id/user_id
- input row count
- expanded variant count
- create/skip/conflict/invalid counts
- created prompt IDs
- status/created_at/reverted_at

新增一张 `geo_prompt_import_batches` 表即可保存 batch metadata 和 created UUID array；DDL 只通过 migration 文件交付，不直接在 Cloud SQL 执行。

Commit 成功后显示 Import Result Dialog，并提供 Undo Import：

- 仅删除该 batch 创建的 prompt IDs。
- 使用现有 PromptCascadeDeletionService。
- 二次确认会说明若 Prompt 已产生结果，Undo 会级联删除相关事实数据。
- Undo 幂等；已删除 ID 忽略，batch 标记为 reverted。

### 7.9 Import API 与持久化契约

导入端点固定为：

```text
POST /api/prompts/import/preview              multipart/form-data: file
POST /api/prompts/import/commit               multipart/form-data: file + expected_manifest_sha256
POST /api/prompts/import/{batch_id}/undo      JSON confirmation payload
```

Preview 必须包含：`raw_csv_sha256`、`normalized_manifest_sha256`、`input_row_count`、
`expanded_variant_count`、quota before/after、create/skip/conflict/invalid counts，以及按 CSV row number
排列的 normalized values、expanded count、action、errors、warnings。Preview 不写业务表。

Commit 要求客户端回传 Preview 得到的 `expected_manifest_sha256`。服务端重新解析文件后若 manifest hash、
配置、quota 或 existing variants 与 Preview 不一致，返回 409 `preview_stale` 和新的 Preview，不继续写入。

Migration 新增 `geo_prompt_import_batches`，字段契约为：

| Column | Type/constraint | Purpose |
|---|---|---|
| id | UUID PK | batch_id |
| client_id | UUID FK, not null | tenant scope，Workspace 删除时 cascade |
| created_by_user_id | UUID nullable FK | commit actor |
| source_filename | TEXT not null | 原文件名，不包含文件内容 |
| raw_csv_sha256 | CHAR(64) not null | 原始字节审计 hash |
| normalized_manifest_sha256 | CHAR(64) not null | canonical variants hash |
| input_row_count | INTEGER >= 0 | 非空输入行数 |
| expanded_variant_count | INTEGER >= 0 | 展开后总 variants |
| create_count/skip_count/conflict_count/invalid_count | INTEGER >= 0 | Preview/commit result |
| created_prompt_ids | UUID[] not null default empty | Undo 的唯一目标集合 |
| status | TEXT check `COMMITTED/REVERTING/REVERTED` | batch lifecycle |
| created_at/reverted_at | TIMESTAMPTZ | audit timestamps |
| reverted_by_user_id | UUID nullable FK | Undo actor |

Undo 在 client-scoped lock 下把 `COMMITTED → REVERTING → REVERTED`；若级联删除失败，事务回滚后 status
仍为 `COMMITTED`，允许用户重试。已经 `REVERTED` 的 batch 再次 Undo 返回幂等成功。未成功 Commit 的文件
不创建 batch row；失败原因写入现有应用 audit/log，不伪造一个可 Undo 的 import batch。

## 8. F5：固定日期范围的完全动态报告与上一等长周期比较

> 最终架构决策（2026-07-15）：本节以及下文所有关于 `snapshot_json` 完整指标物化、`geo_static_report_lists`、冻结列表缓存或在线 Snapshot 排序的旧描述，均由本段取代。报告只持久化租户、固定日期范围、筛选项元数据、状态和审计字段；页面通过报告权限校验后，使用报告所属 `client_id` 与固定 `window_start/window_end` 调用现有动态 Visibility、Citation、Sentiment API。Topic/平台筛选、同环比、指标定义、全量排序和分页全部复用动态 Dashboard 实现，不维护第二套计算逻辑。历史报告继续走旧读取兼容路径；本轮测试产生的七份 v5 报告和 `geo_static_report_lists` 由 migration 127 安全删除。

### 8.1 Previous-period materialization

生成报告时定义：

```text
current_start = data_window_start
current_end = data_window_end
period_days = current_end - current_start + 1
previous_end = current_start - 1 day
previous_start = previous_end - period_days + 1 day
```

Snapshot 同时写入：

- current summary/series/ranking
- previous summary/series/ranking lookup
- delta/change fields

最少补齐：

#### Visibility

- visibility_score_change
- visibility_rank_change
- sov_pct_change
- sov_rank_change
- avg_position_change
- avg_position_rank_change
- prev_time_series
- prev_avg_position_series

#### Citation

- own_domain_share_change
- own_rank_change
- domain/page change_pct
- prev_time_series

#### Sentiment

- positive_pct_change
- previous summary series
- theme occurrence change

Change 计算复用动态 Dashboard 现有公式和 null/zero 处理规则，但在 Snapshot generation 时独立执行并冻结结果。

### 8.2 Snapshot 不得回退 live data

- “冻结数据”是指：报告生成时，系统把当时的数据窗口、筛选条件、指标结果和列表行复制并
  materialize 到 `report_id` 对应的报告快照中。以后打开这份报告时，即使新的 Analyzer 数据进入、
  Alias 被修改或 Dashboard 指标发生变化，该报告仍呈现生成时的历史版本。
- report_id 对应 Snapshot 是报告事实源。
- 在线页面 Topic/Platform filter 不能改为查询当前动态 Dashboard。
- 若 Snapshot 不包含某个 filter 维度，UI 应禁用该 filter 或显示“该报告未物化此维度”，不得静默回退实时数据。

### 8.3 比较语义、显示与异常规则

- 本轮业务口头称“同比/环比”，正式数据语义统一为 previous-period：当前选择区间对紧邻的等长上一周期。
- 1 天对前 1 天、7 天对前 7 天、30 天对前 30 天；不实现“去年同期”或自然月同比。
- 百分比指标使用 percentage-point 或 relative-percent 的哪一种必须严格复用对应动态 Dashboard 当前字段定义，不能因 Static UI 文案自行换算。
- Rank/Position 的正负方向与普通百分比相反时，UI 的颜色和箭头必须表达“排名改善/恶化”，不能只按数值正负套用通用颜色。
- previous 分母为 0 或缺失时复用动态 Dashboard 的 null 规则，显示 `—`，不得显示 Infinity、NaN 或伪造 0%。
- previous window 无数据时仍生成成功 Snapshot，但在 data_completeness/warnings 标记该域缺少比较基线。
- 既有 17 份历史 Snapshot 不原地回填；只有新生成或显式重新生成的新版 Snapshot 包含完整比较数据。
- Snapshot version 必须升级，前端按 version 兼容旧报告的 null comparison fields。

## 9. F6：所有列表的指标列支持全局排序

在线报告的排序等同动态 Dashboard 排序：数据库对当前固定日期和筛选条件下的完整结果集排序后再分页。不得读取或维护冻结 list-row/blob；序号、名称、Topic、Product、Prompt、品牌排名矩阵等非指标列不提供排序。

### 9.1 统一排序交互

只有 Metric column header 显示排序控件；Topic、Product、Prompt、Brand、Domain、Page、Theme、
Platform、Country 等维度/字符串列不提供排序控件。

Metric 排序交互：

- 未激活：上下箭头。
- 激活降序：向下箭头高亮。
- 激活升序：向上箭头高亮。
- 点击激活列在 asc/desc 间切换。
- 切换列时使用该指标推荐默认方向，通常数值指标 desc，position/rank asc。
- NULL 永远排在最后。
- 相同指标值使用稳定 text/id tie-breaker。

### 9.2 动态列表排序

排序清单是强制范围，不以组件当前是否分页或是否默认只显示 Top N 为豁免：

| 页面/域 | 必须支持排序的列表 | 可排序 Metric 示例 |
|---|---|---|
| Visibility Sidebar | Brand Visibility、SOV、Average Position、Topic ranking、Product ranking 及其展开表 | score、share、mentions、total queries、average position、rank、change |
| Citation Sidebar | Domain ranking、Page ranking、Category breakdown、Published Page tracking 及其展开表 | citations、share、change、rank、trigger count |
| Sentiment Sidebar | Theme 列表及其带指标的聚合/展开表 | occurrence、occurrence change、positive/negative count、sentiment percentage |
| Prompt Sidebar | Topic group、Product group、Prompt rows | visibility score、brand rank、mentioned、total query、average position，以及本轮补齐后实际展示的 Citation/Sentiment metrics |
| Topic 下钻 | 下钻页内全部 Visibility/Citation/Sentiment 指标列表 | 与对应动态 Dashboard 相同 |
| Product 下钻 | 下钻页内全部 Visibility/Citation/Sentiment 指标列表 | 与对应动态 Dashboard 相同 |
| Prompt 下钻 | 下钻页内全部 Visibility/Citation/Sentiment 指标列表 | 与对应动态 Dashboard 相同 |

没有 Metric 的纯文本详情、Prompt/Response 原文列表、操作列、日期文本和维度列不增加排序控件。
如果实现过程中发现表格未列在上表中，判断规则不是“默认不做”，而是：只要它是本系统动态页面或
下钻页面中的聚合列表并含数值 Metric column，就必须纳入 F6。

规则：

- 有 pagination/limit 的列表必须由服务端在 pagination 前排序。
- 排序范围是当前 tenant 与当前筛选条件命中的全部数据库结果，不是浏览器已加载的当前页。
- 只有 API 明确返回无分页全集且 `items.length == total` 的小型 chart table 才允许前端排序，并必须使用共享 comparator/null 规则；其他列表全部服务端排序。
- API 使用白名单 `sort_by` + `sort_order=asc|desc`，禁止把客户端值直接拼入 SQL。
- 排序、筛选、分页参数变化后重置到第一页。

### 9.3 在线 Snapshot 排序

在线报告 section API 增加：

```text
sort_by
sort_order
limit
offset
```

排序对象是该 report_id 在报告生成时已 materialize 的全量冻结列表，不是当前 live metrics，
也不是前端当前页已经加载的 20/50 条数据。

当前 Snapshot 的部分列表只有 20/50/100 行 cap，无法满足全局排序。本轮必须移除“只保存默认 Top N”
作为在线排序数据源的限制，并增加 report-scoped list-blob materialization：

- 报告生成时，继续把首屏默认顺序写入 `snapshot_json`，保证报告首屏与离线 HTML 的快速渲染。
- 同时把 17 个注册 list type 的完整 canonical 列表分别写入 `geo_static_report_lists`；列表按 25,000 行/
  16 MiB 上限切成连续 JSONB 分片，而不是每个业务 item 一行。
- 对超过 16 MiB 展开对象树的 Citation Page/Domain，materialization 从同一 canonical rows 生成六组紧凑
  排序位置索引并写入同一张表；索引只保存整数位置，不复制完整列表，也不新增 schema。
- 在线 list API 热路径使用 128 MiB 全实例 LRU 中的逐行紧凑 JSON + `array('I')` 排序索引；冷实例读取
  持久化位置索引后，只从原始 JSONB 分片精准提取当前页，禁止重新查询 live fact tables。
- Snapshot 列表的 `total` 是报告生成时的完整行数；翻页和排序都只在这个历史全集中进行。
- 新表及索引只通过 migration 文件交付，由 CTO 手工执行，不直接修改 Cloud SQL schema。

`geo_static_report_lists` 字段契约为：

| Column | Type/constraint | Purpose |
|---|---|---|
| report_id | UUID not null | frozen report scope |
| client_id | UUID not null | tenant defense-in-depth |
| list_type | TEXT not null | whitelisted list identifier |
| list_version | TEXT not null | reader/writer contract version |
| row_count | INTEGER not null | payload 完整性检查和响应 total |
| rows_payload | JSONB array not null | 完整 canonical rows；包含维度、冻结 metric、row_key 和 default_position |
| materialized_at | TIMESTAMPTZ not null | snapshot generation time |

约束与访问规则：

- 主键为 `(report_id, client_id, list_type)`，并通过 `(report_id, client_id)` 复合外键级联到报告。
- `rows_payload` 必须为 JSON array，且 `row_count = jsonb_array_length(rows_payload)`。
- 每次读取都带 `report_id + client_id`；不为 payload 内 metric 建 JSON 表达式索引，也不把请求值拼接进 SQL。
- Canonical 分片使用 `list_type` / `list_type::000001...`；派生位置索引使用
  `citation.page|domain@sort.{metric}.{order}[::part]`，版本、分片连续性、唯一位置和容量均由 reader 校验。
- `list_type → allowed sort keys`、默认方向和稳定 tie-breaker 全由服务端常量白名单定义。

在线列表端点固定为：

```text
GET /api/static-reports/{report_id}/lists/{list_type}
    ?sort_by={metric_key}&sort_order=asc|desc&limit=20&offset=0
```

`limit` 默认 20、最大 100；响应返回 `items/total/limit/offset/sort_by/sort_order`。materialization 必须在
同一报告生成事务中同时替换 snapshot_json、17 个 canonical lists 的全部分片和可选派生排序索引，避免首屏与排序 API 属于不同版本。
成功完成前必须校验 17 个 list type 完整、唯一、同版本且 row_count 与 payload 一致。

在线 Snapshot 的强制列表范围与该 Snapshot 内呈现的 Visibility、Citation、Sentiment、Topic、Product、
Prompt 指标列表一致。每个 list_type 必须声明允许的 metric sort key、默认 sort、稳定 tie-breaker 和 total。
不得因列表首屏仍从 `snapshot_json` 快速渲染，就让翻页/排序使用另一套 metric definition。

旧 Snapshot version 没有 list blobs 时仍可按原默认顺序只读打开，但不显示排序控件；UI 提示该历史报告
需要显式 Regenerate 才能获得完整比较和全量排序。禁止从 live data 临时补齐旧报告。

不能用重新查询 live fact tables 的方式补全报告列表，因为 late-arriving data、数据修正或配置变化会让
同一个 report_id 在不同日期打开时出现不同结果，破坏 Snapshot 的历史可复现性。

### 9.3.1 生成性能与并发预算

- Cloud SQL 全局 `work_mem` 继续保持 16 MB；仅在报告只读事务中 `SET LOCAL work_mem = 32MB`，配置硬限制
  为 16–64 MB，避免影响普通 API 或多个排序/Hash 节点叠加放大内存。
- pool max 仍为 8。跨实例 advisory-lock guard 持有 1 个连接，Snapshot 使用 1 个 coordinator + 最多
  1 个 worker，共最多 3 个连接，并硬性为普通 API 预留至少 5 个连接。worker 配置硬上限为 2，只有
  更大 pool 在满足同一预留规则时才可使用第 2 个 worker。
- 单个 Cloud Run 实例用容量为 1 的 semaphore；跨实例使用 PostgreSQL transaction advisory lock，任一时刻
  全局只生成一份报告。抢不到容量时释放 materialization lease，返回可重试的 PENDING，不占连接等待。
- 当前生成量低且分散，本轮不引入 Cloud Tasks。未来存在定时器时，可按 client_id hash 分散触发窗口；仍必须
  服从相同全局锁，不允许通过扩大连接池来换取并发。
- Citation/Sentiment current 与 previous 使用两个较小窗口分别预聚合；不得为了减少扫描次数强行合成更大的
  时间窗。Dreamina 实测表明合并窗口会形成更重的 Group/临时文件压力。
- `snapshot_json` 与 17 个 list blobs 只能从同一批 canonical metric rows 派生，不允许维护两套计算逻辑；
  前者保留图表、比较字段、默认页和离线 HTML，后者只承载完整可排序列表。
- 每个 list 最多 25,000 行、全部 17 个 list 合计最多 100,000 行；单 Blob 未压缩 JSON 最多 16 MiB、
  全部 Blob 合计最多 48 MiB。生成阶段、持久化前和读取阶段均检查上限；读取 SQL 用 CASE 在数据库侧
  先检查 row_count/文本字节数，超限 payload 不传输到应用。
- Visibility、Citation、Sentiment、Prompt/Topic 的高基数聚合查询使用 server-side cursor 分批读取，最多保留
  50,000 个聚合结果行或 16 MiB 累计序列化数据；cursor `prefetch=1`，SQL 额外读取 1 个 guard row，任一
  上限超出即中止本次生成，不允许把无界 `fetch()` 结果先装入应用内存。Prompt-by-day、Topic-by-day 和
  Sentiment examples 同样使用字节受限 cursor，同时保留原有 700/700/50 行展示截断。
- 完整 `snapshot_json` 在进入完成事务前完成一次序列化并检查 32 MiB 上限；超限报告 fail closed，不写入
  任一 Blob 或 Snapshot，避免 list blobs 有上限而离线 HTML/图表载荷无上限。
- 在线冻结列表查询在每个 SaaS 实例最多同时解码、筛选和排序 2 个 Blob；并发预算覆盖数据库 point read、
  JSONB 解码、全量筛选、稳定排序和分页切片的完整生命周期。
- `snapshot_json` 内所有在线默认列表统一只保留 list API 的第一页 20 行，避免默认页与 offset=20 重叠。
- 空 previous window 必须依据事实分母（total_query/total_citations/total_count 等）判定为 missing；
  不能把无数据产生的 0 当成有效 0% 基线。存在事实但比例恰为 0 仍是合法 comparison baseline。
- materialization 失败只向报告记录持久化稳定公开错误码；数据库/SQL 原始异常仅进入服务日志。

### 9.4 离线 HTML

- 不渲染排序按钮。
- 不依赖 JavaScript/API 执行排序。
- 使用导出时的默认排序和已导出行。
- 保持单文件可离线打开。

## 10. F7：Admin Brand Alias 数据源对齐

### 10.1 Source of truth

唯一运行时事实源：

```text
geo_client_brands.aliases
```

SaaS 与 Analyzer 不变。

### 10.2 Admin API 最小适配

Admin 当前没有 `geo_client_brands` Alias endpoint。新增极薄的 Admin router：

```text
GET /api/clients/{client_id}/brands
PUT /api/clients/{client_id}/brands/{brand_id}/aliases
```

实现要求：

- 直接复用 `geo_common.services.BrandRepository`。
- GET 返回该 client 的 active Own/Shadow brands，固定包含 id、brand_name、aliases、is_shadow。
- PUT body 只包含 aliases。
- Repository query 同时带 client_id + brand_id，防止跨租户更新。
- 不代理调用 SaaS HTTP API，不复制 Brand SQL。
- Alias 输入先 trim、移除空值，并按 case-insensitive canonical form 去重；保存顺序保持用户首次输入顺序。
- 空数组表示清空该品牌 Alias，不能被解释成“不更新”。
- brand_id 不属于 client_id 时返回 404，避免泄漏其他 Workspace 品牌是否存在。

### 10.3 Admin UI

- 从 Client Info form 和 `ClientUpdate` payload 中移除 legacy aliases。
- 按 SaaS Brands UI 的模式显示每个品牌及 aliases。
- Alias 更新按 brand_id 提交。
- 不改变 quota、Agent limits、cron 和其他 Client Info 逻辑。
- legacy `geo_clients.aliases` column 保留但不再由 Admin UI/API 编辑。
- 每个品牌独立保存并显示 loading/success/error；一个品牌失败不得回滚另一个已成功品牌，也不得显示全局假成功。
- UI 清楚区分 Own Brand 与 Shadow Brand，并沿用 SaaS Brands UI 的 Alias tag/input 行为，不重做品牌增删或其他设置。
- 刷新 Admin 页面后必须以 `geo_client_brands.aliases` 重新加载，不能继续从旧 Client payload hydrate Alias。

### 10.4 非目标

- 不迁移或删除 legacy column。
- 不双写。
- 不修改 SaaS UI。
- 不修改 Analyzer。
- 不修改品牌 Schema。

## 11. F8：Workspace 引导式清理与删除保护

### 11.1 Deletion Readiness API

新增只读 Admin endpoint：

```text
GET /api/clients/{client_id}/deletion-readiness
```

返回：

- workspace name/id
- collector/analyzer/llm discovery scheduler state
- topic count
- logical prompt count / physical prompt row count
- task/result/citation/brand mention/product mention/sentiment counts
- static report/agent task/published URL counts
- recommended next action
- can_finalize boolean

该 endpoint 不删除数据。

`can_finalize=true` 的条件为：

- 三类 scheduler 均已停止。
- Prompt 与 Topic 数量均为 0。
- 由 PromptCascadeDeletionService 应清理的 Task/Result/Citation/Mention/Sentiment 数量均为 0。

若 Prompt/Topic 已为 0 但仍有高体量孤立事实数据，Readiness 返回内部数据修复 blocker，不要求用户在 UI 中逐表手动删除。

### 11.2 Admin Dialog

Delete Workspace 点击后打开自定义 Dialog：

1. 展示关联数据数量和风险等级。
2. 若 scheduler 仍启用，第一步提供 Stop All Scheduling 操作；复用现有 Admin Client scheduler update 能力，
   将 collector、analyzer、LLM discovery 三类 schedule 全部关闭，成功后重新读取 readiness。
3. 若 Prompt > 0，提供 Open Prompt Management 链接。
4. 若 Topic > 0，Prompt 清空后提供 Open Topic Settings 链接。
5. can_finalize=true 后显示最终删除入口。

不要求用户逐一手动删除内部 Task/Result/Citation；PromptCascadeDeletionService 负责这些事实数据。

Open Prompt Management 使用配置化 SaaS base URL 和目标 Workspace context，打开现有 Prompt 管理页；
不得把 localhost、生产域名或 client_id 硬编码在前端。用户返回 Admin Dialog 后，Dialog 重新 fetch readiness，
不依赖离开页面前的旧 count。

### 11.3 Prompt 分批清理

现有 batch-delete API 和 PromptCascadeDeletionService 继续作为删除执行核心。

增加有界限制：

- 服务端单次默认处理 25 个、硬上限 100 个 physical prompt IDs；超过硬上限返回 422，不静默截断。
- Prompt Management 增加 Workspace Cleanup 模式：用户明确确认后，按服务端上限自动串行提交下一批，
  显示 deleted/remaining/progress；普通手动勾选删除仍保留现有行为。
- 任一批失败时停止，可从 readiness 重新读取剩余数量后继续。
- 不并行发送多个删除批次。
- 每批仍保持单事务 all-or-nothing。

为避免 Dreamina 级别数据每批扫描数百万行，提供 migration，为级联表补齐删除友好索引：

```text
(client_id, client_prompt_id)
```

至少覆盖：

- geo_tasks
- geo_results
- geo_citations
- geo_brand_mentions
- geo_product_mentions
- geo_sentiment_results
- geo_sentiment_themes

Migration 使用适合线上大表的并发建索引方式，并由 CTO 手工执行；本任务不直接执行 DDL。

### 11.4 最终 Workspace 删除

最终确认：

- 输入完整 Workspace name。
- 前端严格比较后才启用 Delete。
- 请求期间按钮 disabled + loading。
- 关闭 Dialog 不会重复发送。

服务端：

- 删除前重新运行 readiness。
- 若 Prompts/Topics 仍存在，返回 409 和结构化 blocker，不进入 CASCADE。
- 获取全局 Workspace deletion single-flight lock；已有删除时快速返回 409/423，不等待占满 pool。
- 停止/删除 scheduler jobs。
- 执行最终 `DELETE FROM geo_clients`。
- 连接获取和 statement timeout 返回可解释错误，不无限等待。

最终 CASCADE 只负责清理由 Workspace 自身管理、且不需要用户单独理解的低体量剩余实体，例如权限关系、
静态报告、Published URL 和 Agent metadata。若 readiness 识别到异常高体量或孤立事实数据，必须阻止最终删除，
而不是让最终请求重新退化成长时间占用 Admin pool 的大事务。

### 11.5 F8 明确非目标

- 本轮不建设持久化异步 Workspace deletion job/worker。
- 不要求用户逐表删除 Task、Result、Citation、Mention 或 Sentiment。
- 不通过扩大 Admin connection pool 掩盖长事务。
- 不允许多个 Workspace 删除请求并发占用全部连接。
- 不在应用启动时自动执行索引 DDL。

## 12. 多租户与安全要求

- client_id 由 JWT/Admin route scope 决定，CSV 内容不能覆盖。
- 所有 Prompt、Brand、Report、Readiness queries 必须同时包含 client_id。
- Prompt ID list 必须先按 client_id 过滤，再执行查询或删除。
- Topic/Product mapping 只在 current client 内解析。
- Preview 和 Commit 均重复 tenant validation。
- 任何导入、Undo、Brand update、Workspace delete 均写 audit event。
- 不记录原始 Prompt 文本到通用 audit metadata；只保存 hash、count、batch_id 等非内容信息。

## 13. i18n 与 UI 约束

- SaaS 文案放入 `geo_saas/web/src/i18n/locales/{zh-CN,en-US}/insights.json` 或对应 namespace。
- Sidebar `Prompt` 两种语言相同。
- Shared Save/Cancel/Delete/Loading 使用 common namespace。
- Admin 若尚未使用同一 i18n 架构，保持现有 Admin 文案模式，但不得引入原生 dialog。
- CSV Header 固定英文，不随 UI 语言变化。
- 所有确认使用 shadcn/radix Dialog/AlertDialog。

## 14. API 兼容性

- 所有新增 filter/sort 参数均 optional；未提供时保持现有响应和默认排序。
- `/prompts/batch` 继续服务现有 Brainstorm save flow。
- CSV 使用独立 template/preview/commit endpoints，不改变现有 batch request body。
- `/prompts` redirect 保留。
- legacy Admin ClientOut 保留只读 aliases 响应字段以维持兼容，但 `ClientUpdate` 不再接受 aliases，Admin UI 也不展示或提交；该字段不参与本轮任何写入。

## 15. 测试与验收

### 15.1 F1 Prompt Sidebar

- Visibility 顶部不再显示 Prompt Tab。
- Sidebar 顺序与文案正确。
- 旧 `/prompts` URL 可打开新入口页面。
- Prompt route active 时只有 Prompt Sidebar item 高亮；刷新、后退、Sidebar 收起/展开行为正确。
- 从其他 Insights 页面切换后保留兼容的 Date/Topic/Platform/Country filter state。
- zh-CN/en-US 均无缺失 key。

### 15.2 F2 动态下钻

对 Topic、Product、Prompt 各验证：

- V/C/S 三组 Dashboard 均加载。
- Current/previous period filter 一致。
- 三种 hover icon 只在预期交互触发；刷新和复制链接能恢复同一 target。
- Product filter 不混入其他 Product。
- Prompt filter 使用全部 variant IDs。
- Theme/domain/page expandable rows 不泄漏其他 target 数据。
- 任一 V/C/S domain 失败时另两域仍渲染；filter 快速切换不会显示旧请求结果。
- 全局筛选与 target 无交集时显示 scoped empty，不移除 target predicate。
- 两个不同 client_id 人工验证零交叉数据。

### 15.3 F3 Intent

- Active Intent 来自 Global Config。
- `general` 显示为 Unconfigured，且可筛选历史行。
- 多选 Intent 内部 OR、与其他 Prompt Filter 之间 AND；清空后不过滤 Intent。
- 新建/导入 `general` 被拒绝。
- Prompt Editor 不再使用 `general` fallback；Intent 缺失返回明确 validation error。
- Facet API 失败时不回退硬编码枚举，Prompt 主列表仍可使用并显示 retry state。
- Global Config 增删 Intent 后无需前端发布即可更新筛选项。

### 15.4 F4 CSV

- UTF-8 BOM、中文 Prompt、英文 Header 正常。
- Import Dialog 同时包含 Import CSV 与 Allowed Values Tab，且不使用原生 alert/confirm/prompt。
- Allowed Values UI 与下载 CSV 均只返回当前 tenant 的 Topic/Product 和当前 Workspace 可用的平台、国家、语言及 active Intent。
- Product 枚举行包含 Topic parent；UI Label 不会被后端当作 canonical import value。
- Global/Workspace 配置变化后重新打开或刷新 Allowed Values，无需前端发布即可反映新值。
- CSV 超过 10 MB、2,000 输入行、单行 100 variants 或整批 20,000 variants 时整批拒绝且不截断。
- Customer Name 不匹配时整批阻止。
- Topic/Product tenant mismatch 阻止。
- Platform/Country/Language/Intent allowlist 阻止非法值。
- 英文半角逗号、分号、竖线多值均可解析、trim、canonicalize 和去重。
- 中文全角逗号/分号被明确拒绝；CSV 单元格内英文逗号未正确 quoting 时返回可理解的格式错误。
- 多平台×多国家展开数正确；等价的多值写法和多行写法生成相同 canonical variants。
- Language 多值被拒绝。
- 相同 Platform/Country 的不同 Language 行可同时导入，并保存为不同物理行。
- 文件内重复、existing skip、metadata conflict 分类正确。
- Quota 按 logical concept，不按展开行计数。
- Commit 前数据变化会被重新 Preview 捕获。
- 任一步失败不产生部分写入。
- Undo 只删除该 import batch 创建的数据。
- 两个并发 Commit 对同一 Workspace 不会突破 quota 或重复插入同一 variant。

### 15.5 F5 静态报告比较

- 1/7/30 天的 previous window 边界正确。
- Snapshot change 与同条件动态 Dashboard 在生成时一致。
- 17 个历史 Snapshot 不回填；新生成/重新生成报告包含 change。
- previous 数据缺失或分母为 0 时返回 null/`—`，不出现 Infinity/NaN。
- Rank/Position 改善方向的箭头和颜色与普通百分比指标不同且正确。
- 新 Snapshot version 可渲染完整 change；旧 version 仍可打开。

### 15.6 F6 全局排序

- 动态 paginated list 先排序后分页。
- 只有指标列显示排序控件，维度/字符串列不显示。
- 动态列表排序覆盖当前筛选命中的全量结果，而非当前页数据。
- NULL last、tie-break 稳定。
- 9.2 列出的每个动态/下钻列表至少验证一个 asc、一个 desc 和翻页后的全局顺序。
- 非法 sort_by 返回 422/400，不进入动态 SQL；sort_order 只接受 asc/desc。
- 在线 Snapshot 排序不调用 live metrics。
- 在线 Snapshot 对生成时 materialize 的完整列表先排序再分页，不受原 20/50/100 首屏 cap 限制。
- report list-blob API 同时校验 report_id 与 client_id，不可读取其他 tenant 的历史列表。
- 离线 HTML 无排序控件且可断网打开。

### 15.7 F7 Alias

- Admin 读取结果与 SaaS Brands 一致。
- Admin 更新后 Analyzer 下一次加载读取新 aliases。
- Admin 不再修改 `geo_clients.aliases`。
- brand_id 属于其他 client 时返回 404/403 且不更新。
- Alias trim、空值移除、case-insensitive 去重、清空数组与刷新回读行为正确。
- Own/Shadow 品牌均按各自 brand_id 独立保存，其他 Client Info 字段不回归。

### 15.8 F8 Workspace 删除

- Readiness counts 与数据库一致。
- scheduler 未停、Prompt/Topic 未清时 final delete 被阻止。
- Stop All Scheduling 同时关闭三类 schedule，并在成功后刷新 readiness。
- Prompt 清理串行分批、可中断恢复。
- 单批 25 默认、100 硬上限生效；超限不产生部分删除。
- 两次快速点击只产生一个最终删除请求。
- 并发 Workspace 删除被 single-flight 快速拒绝，不耗尽 pool。
- 删除期间普通 Client create/list 请求仍能获取连接。
- 输入名称不匹配时按钮不可用。

## 16. Scope Traceability 与完成门槛

下表是实施和 Code Review 的强制检查表。任何一行未满足，整轮 P0 不能标记完成。

| Feature | Frontend | API/Service | Persistence/Query | Required verification |
|---|---|---|---|---|
| F1 | Sidebar item、移除旧 Tab、active/redirect/filter state | 无新指标 API | 无 Schema 变化 | 路由与双语 E2E |
| F2 | 三种 hover 入口、统一下钻 shell、V/C/S 独立状态 | 扩展 Citation Product/Prompt filters；扩展 Sentiment Prompt/detail filters | target predicate 进入 current/previous/summary/list/detail | Topic/Product/Prompt × V/C/S integration + tenant isolation |
| F3 | Intent multi-filter、Active/Unconfigured 分组、Editor 必选 | tenant-scoped intent facets、写入 validation | active Global Config + tenant distinct historical values | config drift、历史值、OR/AND、无 hardcode |
| F4 | Template、Allowed Values、Preview、Result、Undo Dialog | template/facets/preview/commit/undo | transaction、advisory lock、batch audit migration、cascade undo | parser limits、duplicates、quota、rollback、concurrency |
| F5 | Static V/C/S change display、旧版兼容 | Snapshot materialization/section response | previous window queries、snapshot version、frozen data | 1/7/30 boundary + dynamic parity + missing baseline |
| F6 | 仅 Metric header sort、reset page | sort whitelist、全局 sort before pagination、report list API | 动态列表 SQL 全局排序；Snapshot list-blob 点查 + 内存全量排序 | 每张列表 asc/desc/page/null/tie + offline exclusion |
| F7 | Admin brand list/alias editor，移除 legacy field | thin Admin brand endpoints using BrandRepository | only `geo_client_brands.aliases` | SaaS/Admin parity + Analyzer read + cross-client denial |
| F8 | Readiness Dialog、Stop Scheduling、SaaS cleanup links、typed confirm | readiness、bounded cascade batches、single-flight final delete | deletion indexes migration、PromptCascadeDeletionService、final guarded cascade | Dreamina-scale behavior、pool availability、resume/idempotency |

### 16.1 全局 Definition of Done

- F1–F8 的单元、API integration、前端 component 和关键 E2E 测试全部通过。
- 每个新增/扩展数据接口都用两个不同 client_id 验证零交叉污染。
- 中英文 i18n key 完整，CSV Header/Value 规则不随 locale 改变。
- Migration 文件包含 forward SQL、必要注释和手工 verification query；不由应用自动执行。
- 旧 Prompt route、现有 `/prompts/batch` Brainstorm flow、旧 Static Snapshot 和 Admin 其他 Client 编辑能力无回归。
- 代码中不存在本文禁止的 hardcoded Intent、live Snapshot fallback、legacy Alias 写入或 current-page-only sort。
- 不允许以未完成占位、永久关闭的 feature flag、占位接口或仅前端 mock 作为任何 Feature 的完成状态。

## 17. 交付顺序

1. F3 的 Intent 数据契约、facet service 和 Prompt write validation，为 F4 导入复用 canonical resolver。
2. F1 Prompt Sidebar 信息架构与兼容路由；该阶段不能把旧 Prompt 页面能力删掉。
3. F2 Citation/Sentiment target filter 扩展、共享 drilldown context 和三类动态下钻。
4. F6 共享 sortable header/API contract，先接动态 Sidebar 与 F2 下钻列表并逐表验收。
5. F4 Prompt CSV template/allowed values/preview/commit/audit/undo，复用步骤 1 的 Intent resolver。
6. F5 Static Snapshot previous-period materialization/version/UI；随后完成 F6 在线 Snapshot 全量 list-blob 排序。
7. F7 Admin Brand Alias 最小适配，独立验证 SaaS/Analyzer 不变。
8. F8 deletion index migration、readiness、Stop Scheduling、Prompt Cleanup mode、Topic 引导和最终删除保护。

各阶段必须在合并前完成对应 Feature 的 tenant isolation 与回归测试；数据库 migration 只生成文件，由 CTO 手工执行。
F1–F8 可按上面依赖顺序分阶段提交，但产品发布门槛仍是第 16 节全部满足，不能把后续 Feature 默认为下一轮。
