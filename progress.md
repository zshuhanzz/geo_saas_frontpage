# 当前迭代调研进度

## 2026-07-15：全列表序号列排序约束补充

- 用户明确：不仅 Citation，所有动态 Dashboard、Prompt 下钻和页面内静态报告列表的序号 / ID / `#` 展示列都不可排序；只有真正的数值指标列可以触发全局排序。
- 代码审计确认：`SortableMetricHeader` 统一调用 `isBusinessMetricSortKey`，会把 `rank/id/index/order/sequence/row_number/row_no/ordinal/no/number/serial/display_order/*_id` 等展示字段降级为纯文本；全部 42 个调用点只使用业务指标或经过该统一守卫。
- Visibility Ranking 的后端/静态快照内部仍按 `rank` 读取固定 #1–#10 品牌顺序；这不是可点击的用户排序。前端矩阵没有 `SortableMetricHeader` 或 `data-sort-list`，列结构为 Topic/Product + #1–#10，并分别渲染 Group 与 Prompt 的品牌身份、高亮。
- 定向与全量前端验证：4 个排序契约脚本 + 124 个后端排序/静态报告测试通过；SaaS Web 19/19 Node tests 通过；`npm run build` 通过（仅保留既有 chunk-size warning）。
- in-app Browser 插件连接层本轮返回 `Browser is not available: iab`，浏览器列表为空。遵守既定 E2E 约束，没有切换 Chrome、无头浏览器或直接 API 伪装可见验证；待插件实例恢复后补 6174 可见 E2E。
- 两路独立只读复审确认序号列约束本身无遗漏，但发现局部刷新仍有 5 个缺口：静态 Citation 排名侧卡与域名表共享可变结果；Published URL 详情四个子列表共享请求身份并整抽屉 loading；动态 Citation ranking 排序会重新触发 Category；静态 Category 排序无局部 loading；Citation Page 首次加载被严格串在 Domain 之后。另有既知 `change_pct` 全量 URL 聚合 60 秒风险，已交回主实现流程统一修订，避免并发修改同一组件。

## 2026-07-15：Migration 后真实浏览器回归与性能修复

- Prompt Import 浏览器 Preview 已确认两种语义：非法 CSV 的 HTTP Preview 成功但 3 行/3 variants 全部 `invalid`，不等于可提交；合法 CSV 为 1 logical / 4 physical variants，Quota 20 → 21。前后端均以 invalid/conflict=0 作为 Commit 门，Commit 事务内重新 Preview 并拒绝 stale/non-committable 数据。
- 已生成并用 artifact-tool 解析核验 `answerx-prompt-import-150.csv`：150 个唯一 logical Prompts，每行 2 platforms × 2 countries，共 600 physical variants，预期 Quota 20 → 170；文件 34,274 bytes / 151 CSV lines，等待浏览器 Preview 性能与 Commit/Undo E2E。
- 静态报告详情后端已具备 report-id 级租户授权：summary/full/part/view/export 均在同一 SQL 的 `geo_static_reports sr` 查询内通过 client/admin access 子查询过滤，未授权与不存在统一 404；前端只有 summary 授权成功后才启动 V/C/S/PromptTopic 内容请求。左上角 Workspace 名称异步渲染不代表内容绕过鉴权。
- Citation `change_pct` 超时已从本地 API 日志定位到单条数据库查询：`database.fetch_all()` 在 60 秒触发 `TimeoutError`，尚未进入 Python shape/sort；默认 citation_count 路径只对当前 20 个候选 URL 聚合 previous，约 4.8 秒，而 change_pct 为全量排序必须聚合并连接前后两个周期的全部 URL，当前 SQL 超过 60 秒。

- Dreamina Prompt 从传输 14,400 条物理展开行改为 120 条逻辑 Prompt；后端返回对齐的 physical variant id/platform/country，前端联合筛选后只聚合命中 IDs，保留平台/国家指标语义并补齐全局国家筛选。
- Prompt inventory 与 metrics 完全分阶段，metrics 等待最新 `clientId + importRefreshKey` inventory revision 完成；日期变化立即失效旧周期指标，失败不再伪装成空列表。
- Dreamina 浏览器实测 Prompt 120 条及完整指标成功显示，无 TimeoutError；Topic 与单 Prompt 下钻的 Visibility/Citation/Sentiment 全部渲染，Citation Domain/Page 均成功返回。
- 可见度排名恢复 `#1`–`#10` 品牌矩阵，无指标列与排序按钮；品牌 Logo、名称和 Dreamina 自家品牌绿色高亮均由 DOM 证据确认。
- Citation 默认 Pages fast path 真实耗时约 5.4–5.7 秒，Domains 约 8.1–8.5 秒；全量 57,762 Page / 10,605 Domain 成功渲染，不再触发 60 秒超时。
- Citation 请求按 Share+Ranking → Category → Domain → Page → Published URL 分阶段，单 Dashboard 重查询并发最多 2；所有阶段门按 base filter 持久化，任一列表的排序/搜索/翻页只刷新自身。
- Citation fast/slow path 的 change 统一为旧线上口径：`round(current_share,2) - round(previous_share,2)`；序号列在所有动态/静态列表均不可排序。
- 首轮 Dreamina 7 天报告真实生成暴露 `STATIC_REPORT_AGGREGATE_CURSOR_PREFETCH=1`：两个只读事务持续约 9 分钟并停在 ClientRead，根因是经 Cloud SQL Proxy 一行一次往返，而非 SQL 长时间执行。
- 已安全取消该次生成并把唯一测试报告行从 MATERIALIZING 精确标为 FAILED；将 cursor prefetch 调整为 512，同时保留 SQL LIMIT 50001、50k 行和累计 16 MiB 硬上限。静态报告专项 68 tests passed。
- 最终纯代码回归：`geo_saas 431 passed`、`geo_common 114 passed`、SaaS Node 19/19、production build 通过；后续定向回归 149 Python + build + contract tests 再次通过，无新增 TODO/FIXME。
- 浏览器运行时随后明确拒绝继续操作 `localhost:6174`，并禁止其他浏览器/API 绕过；因此尚未用修复后的 prefetch 重跑报告，也尚未执行 AnswerX CSV Commit/Undo，等待用户重新允许 localhost。

## 2026-07-14：Migration 后受控写入 E2E

- 用户已手工执行 Migration 124、125、126，并授权在 AnswerX Workspace 验证 CSV 批量导入和静态报告生成。
- 本阶段的数据安全边界：不写入其他 Workspace；CSV 导入必须记录 batch 并在验证后 Undo；静态报告只生成 AnswerX 测试报告；不执行任何 DDL。
- 将从代码和真实数据库同时确认历史静态报告是否需要回填，以及不回填时的兼容表现。
- 已确认 gcloud 当前账号为 `lancelot.chen@answer-x.ai`；只读 Cloud SQL 查询显示 17 份 v2 历史报告、新 Blob 表当前 0 行，AnswerX (Demo) 有 1 份 v2 报告。
- 已确认历史 v2 页面仍可查看，但新版同环比、全量冻结筛选和排序受限；不应把截断的旧 snapshot 列表直接伪装回填成 v5。
- 浏览器运行时已恢复，可创建本地 6174 标签页；已进入 `/reports`，当前登录账号为 `gotyechen@gmail.com`，Sidebar 当前 Workspace 显示 AnswerX。
- AnswerX 普通空间在 2026-07-13/14 均显示数据未完成，无法生成报告；Workspace 菜单确认同时存在 `AnswerX (Demo)`，后者是有历史分析数据的 AnswerX 自有演示空间。
- 测试分工确定：CSV Commit/Undo 使用 `AnswerX`；静态报告 v5 生成使用 `AnswerX (Demo)`，不进入任何正式客户空间。
- 切换 `AnswerX (Demo)` 后首次列表状态短暂沿用旧空间；点击“刷新”后正确显示 2026-05-27 的 v2 历史报告。当前 2026-07-13 仅“待生成”且按钮 disabled，说明 UI 对数据就绪条件做了保护。
- 准备切回 AnswerX 执行 CSV 写入时，Browser runtime 再次以安全策略拒绝 `localhost:6174`，且明确禁止替代浏览器或直接 API 绕过。本轮未发生 CSV Commit、Undo 或新报告写入。
- 追加的 Migration 126 只读索引核验因权限自动审批流断开被拒；遵守禁止绕过/重复执行的要求停止。此前查询已证实 124/125 新表存在且可查询，但 126 的七个索引本轮未能重新独立核验。

## 2026-07-13

- 已完成 SaaS 自定义域名独立工作流的现状核对：Cloud Run 默认 URL、ingress、Terraform state、LB/证书资源空白、GoDaddy DNS、OAuth/CORS 和 Web Nginx 代理链路。
- 已确认采用 Global External Application Load Balancer + Serverless NEG + Certificate Manager DNS authorization，并保留 `run.app` 作为稳定期应急入口。
- 已创建 `docs/superpowers/specs/2026-07-13-platform-custom-domain-migration-design.md`。
- 已创建 `docs/superpowers/plans/2026-07-13-platform-custom-domain-migration.md`，覆盖 Terraform、证书 CNAME、canary、正式 A 记录、OAuth/CORS、中国大陆三网测试、监控、成本和回滚矩阵。
- 本轮没有创建或修改任何 GCP、GoDaddy、OAuth 或 Cloud Run 资源；等待用户审阅方案。

- 已读取用户提供的项目约束和需求 16–20。
- 已加载 brainstorming 与 planning-with-files-zh 流程；本阶段只做项目审计和需求澄清，不实施。
- 已检查工作区状态与近期提交，确认存在大量用户未提交工作，需要严格只读保护。
- 已创建调研计划与记录文件。
- 已阅读根 README 的架构、数据模型、模块职责和产品演进说明，并阅读两份 Agent 战略文档；确认本轮需求的主范围是确定性 SaaS/Admin 数据产品，Agent 仅构成相邻依赖。
- 已定位静态报告、Prompt、Visibility、Citation、Sentiment、Workspace Settings 和 Admin Clients/Brand Profile 等候选代码区域。
- 已完整阅读原静态报告设计，并阅读查询性能原则及 Visibility 拆分方案的相关章节；识别出不可变快照、动态分页和排序同步之间的设计冲突。
- 已先读 Sidebar / Insights / Settings 的中英 i18n 真相源，再进入 TSX；确认 Prompt 目前仍从属于 Insights 信息架构，但已经具备独立页面文案和分析表格概念。
- 已追踪 Prompt 页面到后端指标 API：确认当前仅支持 Visibility，下钻缺少 Citation/Sentiment，Citation 列是空兼容字段，聚合和排序主要由前端承担。
- 已识别 Prompt intent filter 的数据建模问题：`intent_name` 与 V/C/S `categories` 不应混为同一个筛选值，正式设计前必须和用户确认想按哪一层筛选。
- 已完成 Prompt 批量上传现状追踪：前端按钮是空壳；后端只有 Brainstorm 用 JSON batch create。仓库内 Published Pages 已提供可复用的 CSV 模板、预览、校验和确认导入模式。
- 已完成静态报告主要链路审计：确认 v2 section 化、筛选时回退 live API、同环比字段为空、Prompt 静态/动态聚合语义不一致、通用表格没有排序能力。
- 已完成 Alias 端到端追踪：确认 SaaS、Analyzer 和 Agent 使用 `geo_client_brands.aliases`，而 Admin Clients 仍独立编辑无运行时作用的 `geo_clients.aliases`，且没有同步机制。
- 已按系统化调试流程完成 Workspace 删除静态证据链：确认同步 CASCADE、共享 10 连接池、无 timeout/并发控制/任务状态，以及创建请求被阻塞在名称查询前的具体机制。
- 用户已确认 Prompt 的 Sidebar 位置、页面复用、三类下钻补齐 V/C/S、全局列表排序范围，以及静态报告采用紧邻等长上一周期对比。
- 已复核用户补充的 Prompt batch 代码与 Migration 118：确认现有接口具备平台×国家展开、quota 与事务批量写入基础，但缺少可安全开放的租户关系、allowlist、审计、导入预览和补偿契约。
- 已再次确认品牌 Alias 的当前事实源：Analyzer/Agent/SaaS 均读取 `geo_client_brands.aliases`；Admin Client Info 仍读写 `geo_clients.aliases`。
- 已检查 Prompt/Topic 删除链路：Prompt 批量删除已有显式事务清理 sentiment/citation/mentions/results/tasks；Topic 删除依赖 DB CASCADE。手工先删 Prompt 的确可显著缩小最终 Workspace 删除，但不能覆盖全部 Workspace 级实体。
- Visual Companion 用户侧反馈黑屏后，已将审计地图调整为强制浅色高对比主题；浏览器 DOM 与 computed style 验证内容、尺寸和可见性均正常。
- 已接受并记录用户对动态下钻架构的纠正：复用动态 V/C/S Dashboard，不引用静态报告实现。
- 已确认 Admin 目前不存在可直接复用的 `geo_client_brands` Alias API；需求 19 的最小改动边界是 Admin 前端 + 极薄 Admin API 适配，底层直接复用共享 BrandRepository，不改 SaaS、Analyzer、表结构或 schema。
- 已确认 PromptCascadeDeletionService 及单条/批量路由均已实现，并记录用户认可的 Workspace 引导式清理顺序和最终确认交互。
- 已记录 Intent filter 改为数据库驱动的 Prompt intent 值；等待用户提供 ADC 登录账号后再查 Cloud SQL 真实数据，不在代码中写死枚举。
- 已用 `lancelot.chen@answer-x.ai` 重新完成 ADC OAuth 登录；凭据为 `authorized_user`，Quota Project 为 `project-90d7849c-de16-4c15-a0a`。
- 已通过 Google UserInfo 验证 ADC email 与 email_verified，并通过 Resource Manager 验证项目处于 ACTIVE、该账号实际拥有 `roles/owner`。
- 已通过同一 ADC 成功读取 Cloud SQL Admin API：`answer-x-geo-instance` 位于 `us-central1`，状态 RUNNABLE，数据库版本 POSTGRES_18。尚未连接数据库执行 SQL；下一步按需求查询真实 intent/brand 数据。
- 已完成 `gcloud auth login`，并将默认 `core/account` 固定为 `lancelot.chen@answer-x.ai`；当前项目保持 `project-90d7849c-de16-4c15-a0a`。
- 已分别通过 UserInfo 验证 gcloud CLI token 与 ADC token，二者 email 均为 `lancelot.chen@answer-x.ai`；并用默认 CLI 凭据成功读取 Cloud SQL 实例。
- 已检查当前进程环境与 gcloud 配置：`GOOGLE_APPLICATION_CREDENTIALS`、`CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE`、`CLOUDSDK_CORE_ACCOUNT` 均未设置，不存在其他凭据覆盖当前 CLI/ADC 的情况。
- 已使用 Lancelot ADC 启动隔离 Cloud SQL Proxy（15433）并建立只读 PostgreSQL 会话；未执行任何写入或 DDL。
- 已完成 Intent 真实数据核对：3 个启用配置值 + 1 个历史 `general`；定位到 Prompt Editor 的 hardcoded general fallback。
- 已完成 Prompt 数据质量核对：0 个 topic tenant mismatch、0 个空 intent，但存在 8 组 exact duplicate variant / 10 条额外重复行。
- 已完成 Alias 真实数据差异核对，确认多个 workspace 仅 canonical 品牌表有 Alias，Admin legacy 字段已经明显过时。
- 已完成静态快照真实数据核对：17 份 v2 COMPLETED 快照的核心 change 字段和 previous series 全部缺失。
- 已完成 Workspace 关联量级和删除索引核对：Dreamina 事实数据达数百万行，现有 PromptCascadeDeletionService 已实现但“全量一次删除”仍有长事务风险。
- 已完成动态下钻 API filter 能力矩阵：Visibility 覆盖 Topic/Product/Prompt，Sentiment 缺 Prompt，Citation 缺 Product/Prompt；后续设计为扩展并复用现有动态 API。
- 已复核 Published Pages CSV 的真实后端/前端流程，确认可复用 template/preview/commit 与自定义 Dialog 模式。
- 已通过 Cloud SQL 验证 Result 与 Prompt 的 Product 字段完全一致，并读取 5 个启用平台及各 workspace 的平台/国家/语言配置，为 CSV 展开规则提供依据。
- 已按“Spec 先于 Plan”的 superpowers 流程创建需求 16–20 综合技术规格草稿，覆盖动态 API 扩展、CSV 字段/展开/审计/Undo、静态比较与在线/离线排序、Admin Alias 和 Workspace 引导删除。
- 已完成 Spec 首轮自检并补充 Intent facet API、无 Topic 模板行为、Workspace can_finalize 严格条件，以及在线 Snapshot 仅对冻结 materialized rows 排序的边界。
- 已根据用户第二轮审阅修正 CSV/Prompt 语义：数据库每个 Platform/Country/Language 组合一条物理行；多值与多行输入归一到同一 variant 集合；Logical Prompt key 补入 Intent 与 Language。
- 已把多值解析扩展为英文半角逗号、分号、竖线，包含 trim、canonicalization、去重、CSV quoting 与全角符号拒绝规则。
- 已将排序范围收紧为仅指标列，并明确动态列表必须对当前筛选的全量数据先服务端排序再分页。
- 已因用户要求 Snapshot 全量排序，调整为报告生成时完整 list-row materialization；不再只对现有 20/50/100 Top N 快照排序，也不回退 live data。
- 用户已确认 CSV Template + Allowed Values UI Tab；中文版 Spec 已补充两个 Tab、两个 CSV 下载、tenant-scoped 单一枚举 service、Allowed Values CSV schema、canonical Value/locale Label 边界及验收条件。
- 已按用户最终拆分将原需求 16–20 重构为 F1–F8 八个独立 Feature，并扩写中文版 Spec 至 UI、API、数据语义、错误、租户隔离、测试和非目标层级。
- 已增加强制排序列表清单、稳定下钻 identity、CSV/import 具体上限与 schema、完整 Snapshot list-row schema、Alias 归一化规则、Workspace cleanup 页面职责与具体批次上限。
- 已生成章节与 Feature ID 对应的英文镜像 Spec，并完成双语关键契约覆盖检查；两份文档均无未完成占位。
- 已使用 writing-plans 生成英文实施计划：16 个 TDD 任务、3 个 migration、逐任务文件/命令/提交边界和 F1–F8 最终覆盖矩阵。

## 2026-07-14：F1–F8 实施与纯代码回归

- 已按 16 项实施计划完成 Tasks 1–15；Task 15 的 Workspace 引导式清理 UI 已由状态测试和两端构建复核确认完成。
- 已完成 Task 16 的最终缺口修复：PromptEditor 原有 Batch Upload 按钮复用统一 CSV Import Dialog；SaaS OpenAPI 类型从当前 139 条路由重新生成并加入契约测试；Citation、Sentiment、Prompt Drilldown 三个关键文件定向 ESLint 为 0 error / 0 warning。
- 已完成最终六模块全量 Python 回归：`geo_common 114`、`geo_admin 88`、`geo_saas 383`、`geo_agent 189`、`geo_analyzer 73`、`geo_collector 24`，合计 871 passed；Analyzer 仅有第三方 Python 3.14 deprecation warning。
- 已完成最终前端回归：SaaS Node 19/19、Admin Node 7/7；SaaS production build、Admin typecheck/build 全部成功。两端仅保留既有 bundle chunk-size / Browserslist warning。
- 已系统化处理历史红灯：SaaS 的 timeout fake、多值 country、旧 Overview monkeypatch 与两位小数断言均为测试漂移；Analyzer fake 缺少 Prompt 存在响应；Agent Reddit Global Config timeout 被旧模板覆盖是真实存量缺陷，已修复且未更改任何 fallback/model ID。
- 已完成 Python compileall、`git diff --check`、migration 124–126 结构与只读验证块检查；migration 未执行、未连接 Cloud SQL、未操作浏览器或线上数据。
- SaaS 全仓 lint 仍有历史基线 571 errors / 37 warnings，分布于 87 个既有文件；本轮最终审查要求的三个动态下钻文件已全部清零，不以扩大 F1–F8 范围的方式重构全部历史 lint 债务。
- 首轮独立审查发现并修复 5 个 Important：大批 Prompt Import 无法 Undo、Citation Rank 假排序、Static Report 先读后鉴权、final delete session lock 取消泄漏、Stop All 被延迟 Scheduler sync 重建。
- 修复后由两位未参与实现的新 reviewer 分别完成 Scope 与 Security/Data-integrity 复审；最终结论均为 Ready，`0 Critical / 0 Important / 0 Minor`。
- Task 16 纯代码阶段完成。按用户要求在此停下汇报，不进入浏览器自动化；migrations 124–126 仍待 CTO 手工执行。

## 2026-07-14：静态报告存储方案性能复核

- 用户要求基于 Dreamina 已生成的 7 天静态报告和真实 Cloud Run 日志，对比“方案 C：每 Report/List Type 一个 JSONB Blob”与“完整列表全部保存在 snapshot_json”两种冻结存储方案。
- 本阶段采用架构讨论与系统化性能诊断流程，只执行 GCP/Cloud SQL 只读查询；重点核对完整列表规模、内存排序成本、报告生成 45–60 秒的阶段归因、JSONB 解压开销、数据库写入/索引压力及租户隔离边界。
- 已确认当前 gcloud CLI 活动账号为 `lancelot.chen@answer-x.ai`，并通过现有 15432 Proxy 以 READ ONLY transaction 查询 Cloud SQL。
- 已完成 Dreamina 两份 7 天 Snapshot 的压缩尺寸、各 list type 数量和主要 JSON item 字节分布统计；未输出客户内容，未执行写入。
- 已从 Cloud Run 阶段日志定位 25.9 秒生成的实际分布，并完成代表性内存排序基准与 Cloud SQL JSONB PGLZ 解压 EXPLAIN；证据均指向事实表聚合而非应用排序或最终 JSONB 写入为首要瓶颈。
- 已汇总同一生成窗口的 Cloud SQL temporary-file spill（288.63 MiB），并核对实际 Cloud Run/Cloud SQL 规格、连接池并发与源表索引；已形成方案 C 的主要风险边界。
- 性能复核完成：推荐每 Report/List Type 一个 JSONB blob 的新版方案 C；明确当前 row-per-item Migration 125 不应执行。尚未修改实现或迁移，等待用户确认设计后再更新 Spec/Plan 与代码。

## 2026-07-14：新版方案 C 实施、性能优化与回归

- 用户确认当前低频阶段不引入 Cloud Tasks；方案收敛为每份 v5 报告固定 17 个 versioned list blobs，`snapshot_json` 与 blobs 从同一 canonical rows 管线派生，并在 fenced materialization 的同一事务完成。
- Migration 125 已改为 `geo_static_report_lists` 复合租户主键/外键、JSON array 与 row_count 完整性约束；只交付 SQL 文件，未执行 DDL。
- Static list API 改为 `report_id + client_id + list_type` 主键点查，在应用内对完整冻结全集筛选、NULL-last 稳定排序后分页；成功完成前强制校验 17 个 type 完整、唯一、同版本且 count 匹配。
- 生成连接预算改为 coordinator 1 + worker 最多 2、至少预留 pool 5/8；加入单实例 semaphore、跨实例 transaction advisory lock、capacity-busy lease release，以及 16–64 MB bounded transaction-local `work_mem`（默认 32 MB）。
- Prompt/Topic 聚合移除 Mention×Citation cross product；Citation/Sentiment 改为小窗口预聚合。合并 current/previous 的 14 天查询因 Dreamina 只读实测超过 60 秒被撤回，最终保留两个较小窗口。
- 复核中修正：Sentiment asyncpg 跳号参数；17 Blob 完整契约；首屏外 Topic/Product scope；Visibility 完整列表同比；同名 Theme 按 Theme+Sentiment 复合键比较。
- 第二轮安全复审继续收紧取消与内存边界：readiness/失败处理被取消时以 shielded cleanup 释放 fenced lease；高基数聚合改用 server-side cursor，超过 50,000 行或累计 16 MiB 即拒绝；Blob 上限收紧为单表 16 MiB/单报告 48 MiB；在线列表每实例最多并行解码和排序 2 个 Blob。
- 最终资源复审把 cursor `prefetch` 收紧为 1，并将 Prompt/Topic daily rows 与 Sentiment examples 纳入相同的流式字节预算；`snapshot_json` 增加事务前 32 MiB 硬上限，避免离线 HTML/图表载荷绕过 Blob 预算。
- 最终 fresh regression：`geo_common 114`、`geo_admin 88`、`geo_saas 409`、`geo_agent 189`、`geo_analyzer 73`、`geo_collector 24`，合计 897 passed；SaaS Node 19、Admin Node 7；两端 production build、Admin typecheck、compileall、Terraform fmt 与 git diff check 通过。
- 两位独立 reviewer 最终结论均为 Ready，`0 Critical / 0 Important / 0 Minor`。

## 2026-07-15：F1–F8 最终性能修订与真实 E2E

- Prompt CSV 已完成两轮 AnswerX 150 logical / 600 physical 真实 Commit→Undo；最终数据库为 20 logical / 174 physical，测试前缀残留 0，两条 ImportBatch 均为 REVERTED。
- Prompt persistence 已从 asyncpg `executemany` 改为单条 `UNNEST(... WITH ORDINALITY) INSERT ... SELECT ... RETURNING`；Preview 重算、Quota、allowlist/duplicate 校验、600 行插入及 ImportBatch 审计处于同一 tenant-serialized transaction。
- Dreamina 30 天报告真实生成成功。Visibility granular 为 77,225 行 / 29.44 MiB，保护阈值按真实数据校准为 100,000 行 / 48 MiB；最终 snapshot_json 约 0.87 MiB。
- 30 天 Citation Page 为 165,739 行。生成时构建 68,345,599 bytes 的紧凑逐行 JSON + 六组排序索引内存缓存；全实例 LRU 上限 128 MiB，不保留完整 Python dict 树。
- 为覆盖 Cloud Run 最多 5 个实例，六组排序位置索引同时原子写入现有 `geo_static_report_lists`，总存储约 3.64 MiB；冷实例只读索引并精准提取当前 20 行，不新增表/schema、不复制完整列表。
- 实测：旧冷路径 79.37s/500；新报告生成实例热路径 1.79s/200；清空实例缓存后的首次冷索引 8.11s/200；同实例后续分页 2.14s/200。
- 静态报告全局容量锁由长时间 idle transaction advisory lock 改为 session advisory lock，避免 2 分钟月报触发数据库 idle-in-transaction 连接关闭；最终 30 天报告 149.97s 完成。
- Dynamic Citation Pages/Domains change_pct 均改为一次 combined-period conditional aggregate，保留两阶段 ROUND 口径。Dreamina 7 天真实 API 为 9.70s / 4.32s，均 200。
- 修复 Static Visibility 尾部错误三行分页；外层矩阵折叠时不显示分页，三个品牌指标列表一次最多读取 100 行。修复 Static Citation 侧卡被域名表改写、Category 局部 loading/i18n，以及 Published URL 详情排序整抽屉刷新。
- 最终回归：SaaS 后端专项 289 passed、geo_common Prompt 25 passed、SaaS Node 19/19、production build、Python compileall 全部通过。
- 可视浏览器 E2E 按 runbook 启动时，当前 Browser 插件在自身 `browser-client.mjs:33` 初始化稳定报 `TypeError: Cannot redefine property: process`，重置自动化会话后仍复现；未绕过规范改用外部无头工具。本地 SaaS API `/health` 只读 smoke 返回正常。
- 全量 fresh regression：`geo_common 114`、`geo_admin 88`、`geo_saas 393`、`geo_agent 189`、`geo_analyzer 73`、`geo_collector 24`，合计 881 passed；SaaS Node 19、Admin Node 7；两端 production build、Admin typecheck、compileall、Terraform fmt、git diff check 全部通过。
- AnswerX Demo 的 2026-07-14 单日 Cloud SQL 只读 smoke 已通过：Citation ~2.15 s，Sentiment ~2.59 s；未写数据。
# 2026-07-15 Admin Scheduler 无损恢复

- 用户反馈 v29/v31 后拓腾 Cron 仅写入数据库、未同步 Cloud Scheduler；EaseUS 三类任务显示 NOT_FOUND，要求按迭代前线上行为无损恢复。
- 本阶段先查 Admin API 应用日志、Cloud Scheduler Data Access 审计、数据库 Cron 与实际 Job 状态；根因明确前不再叠加实现补丁。
- 验收对象限定为新建 `LensLogTest` Workspace；只维护 Cron，验证创建、原地更新、Pause/Enable，结束后记录测试资源状态。
- 已取得第一轮线上证据：DB 保存正常；Cloud Scheduler CreateJob/UpdateJob 都确实被调用且 IAM granted，但由 Scheduler 返回 504。EaseUS NOT_FOUND 是实际 Job 缺失，不是纯前端显示错误。
- 已定位高概率回归边界：部署重建时未锁定 Scheduler/gRPC 依赖，线上从 7 月 1 日成功的 grpc 1.81.0 漂移到当前失败的 1.82.1；继续从历史 Cloud Build 锁定完整版本组合。
- 已锁定镜像时间线：已知成功基线为 v26（6 月 5 日构建），本轮 v27 是 7 月 15 日首次重建；下一步直接读取两个镜像内的包版本，形成可复现的依赖差异证据。
- 本机没有 Docker/Podman/Crane/Skopeo，无法直接运行历史镜像读取 pip metadata；不重复该路径，改查 Cloud Build 历史日志与镜像 layer 元数据。
- 官方 Python SDK REST transport 已成功原地更新拓腾 Collector 至 13:37；根因假设得到最小实验支持，进入 TDD 修复阶段。
- 已完成最小实现：REST transport、短任务名主路径、长任务名只兼容、保存同步确认、NOT_FOUND Enable/Create 同链路及依赖精确锁定。
- TDD 红灯已确认 `_create_scheduler_client` 契约在旧实现缺失；实现后 Scheduler/生命周期定向测试 16 passed，Admin 全量测试 91 passed，前端 Scheduler 控件契约与 compileall 均通过。
- `deploy_all.sh` 已升级 Admin API v30 并完成发布；Cloud Build 成功，Terraform 仅原地更新 Admin API 镜像，Cloud Run `geo-admin-api-00031-km5` 100% 承流。
- 浏览器 E2E 使用本地 Admin 6173/9000、`gotyechen@gmail.com` dev 身份，同一 Cloud SQL/GCP 项目及线上任务 target。LensLogTest 的新建、首次任务创建、短名原地更新、Pause、NOT_FOUND Enable 重建全部通过；最后两条测试任务均暂停。
- 已用修复链路把拓腾 Analyzer 从旧的 `30 14 * * *` 同步到数据库目标 `37 14 * * *`；Collector 保持 `37 13 * * *`。EaseUS 仅验证两个缺失任务的 Enable 均可用，未创建真实客户任务。
- 最终 fresh verification：Admin 91 passed、Scheduler Node contract 1 passed、compileall、deploy script syntax、diff check 均通过；v30 启动后 ERROR 日志为 0。
- 已通过飞书 CLI 以 Anthony 机器人向 Lancelot Chen 发送最终通知，message_id `om_x100b6a47733c7c84b03b7cd930266da`，包含根因、修复、部署和 E2E 结果。

# 2026-07-21 Dreamina Prompt 平台/国家配置迁移调研

- 用户要求只在 `migrations/` 生成数据变更 SQL，必须先从实时 Cloud SQL 查询 Dreamina `client_id`，不得依赖记忆；本轮不直接执行数据变更。
- 目标候选状态：移除 Perplexity；国家仅保留美国、巴西、墨西哥、新加坡、马来西亚、印度尼西亚、菲律宾、泰国。需先确认 Admin/Cloro canonical code、当前 120 logical Prompt 的物理展开以及历史 Visibility/Citation 影响。
- 按 brainstorming hard gate，先完成事实调研并提交迁移策略/数据语义给用户确认；获确认前不写 migration SQL。
- Cloud SQL/ADC/Proxy/READ ONLY 会话已验证，Dreamina 实时 `client_id` 已查询；完成客户配置、Prompt active/inactive、logical/physical 展开和 Global Platform country allowlist 的首轮统计。
- 已发现 Global Config 与 Cloro 当前官方 AI Overview 文档可能存在支持范围漂移；下一步核对 Cloro countries endpoint及 Collector 实际约束，再审计历史数据查询影响。
- 已完成 Cloro live countries endpoint 复核：5 个现行平台均支持 8 个目标国家；确认 AI Mode/AI Overview 的数据库 Global Config 国家数组已陈旧。
- 已核对 inactive 数据、外键与事实表：旧 inactive 120 logical Prompt 与当前 active 120 精确交集为 0，无法复用；硬删除或原地改写平台/国家都会破坏历史语义，因此迁移必须采用“旧组合停用 + 新组合新 UUID”。
- 已量化停用范围及历史事实关联，并确认新版静态报告与动态 Dashboard 都按当前 active Prompt 集合动态重算；下一步向用户提交历史影响、方案选项与推荐，获得确认后再写 SQL。
- 已最终核对本次 120 enabled logical Prompt 的 Topic 边界：仅 AI Image 80、AI Video 30、AI Design 10；AI Creative Tools 120 全部 inactive，不进入迁移 seed。
- 已新增并静态验证 `migrations/128_refresh_ai_mode_ai_overview_supported_countries.sql`：Cloro live payload 与 SQL 内嵌数组逐项一致，AI Mode 212、AI Overview 230；未执行数据库写入。
- 已向用户澄清 Dreamina 迁移的历史影响边界：历史指标下降同时来自 7 个旧国家和 Perplexity；新增三国没有迁移前事实，不改变迁移前历史指标；完整回滚需同时恢复 client config、重新启用旧 4,800 行并停用新增 1,440 行。
- 已按 Prompt Editor 真实分组逻辑和 Cloud SQL 只读投影确认 UI 结果：AI Video active 30（每行 32 variants），inactive 30（每行 40 variants），不会在 active Tab 出现 60 个 logical Prompt；已明确 physical Prompt UUID 与 runtime Final Prompt 的区别。
- 用户批准 Dreamina 状态迁移方案后，已新增 `migrations/129_dreamina_prompt_platform_country_matrix.sql` 及 TEMP-table executable contract test。首次测试结果严格为 client_updated=1、inserted=1440、deactivated=4800、active=3840/120 logical/total=15840；同会话第二次执行为全部零变更，幂等成立。
- Migration 129 使用 Workspace lifecycle exclusive + prompt-write advisory lock，依赖 Migration 128 Global allowlist，接受且只接受当前 7200/14400 legacy 状态或 3840/15840 completed 状态；任何 partial drift 会在写入前 abort。
- 测试在 Cloud SQL 单会话中以同名 TEMP tables 遮蔽正式表；测试退出后 fresh READ ONLY 查询确认正式 Dreamina 仍为原 config、7200 active + 7200 inactive + 14400 total，未发生线上数据写入。

# 2026-07-16 AI Brainstorming Prompt 生成回归

- 用户报告 AI Brainstorming 生成 Prompt 时 PostgreSQL 报 `column is_active does not exist`，要求确认是否由本轮 Prompt active-only 展示过滤误影响生成链路。
- 本阶段只修复错误查询边界：Prompt 展示/统计继续排除停用 Prompt，Brainstorming 生成不得把 `is_active` 条件应用到没有该列的数据源。
- 完成条件：GCP 日志与代码调用栈定位、TDD 红绿验证、相关模块回归、本地 AnswerX 浏览器生成验证、版本升级、`deploy_all.sh` 部署、部署后日志检查和飞书通知。
- 根因调查完成：生产日志证明 Generate 200、Batch Save 500；Cloud SQL Schema 证明 `geo_client_topics` 无 `is_active`。计划以 Repository SQL 契约红灯测试锁定正确边界，然后只删除错误 Topic 条件。
- TDD 红灯已验证：新增 ownership SQL 不得引用 `is_active` 的契约断言，旧实现按预期失败；随后只移除 `geo_client_topics` 的错误条件并修正文档，定向测试转绿（1 passed）。
- 已复核既有测试：`count_active_*`、`active_prompt_keys_*` 和 Prompt variant resolver 均明确断言 `geo_client_prompts.is_active = true/TRUE`，因此 active-only 展示/Quota 契约仍被回归测试保护。
- 第一轮定向回归：geo_common Prompt 40 passed、compileall 通过；SaaS 测试在收集阶段发现本地 venv 缺少 requirements 已声明的 `python-multipart`，属于本地依赖缺口，尚不能据此判断产品代码结果。
- 补齐 multipart 后 SaaS Prompt 定向回归 131 passed。扩大到全量时发现两个环境/测试基线问题：geo_common 缺 pytest-asyncio；SaaS 参数化测试把固定的 `cp.is_active = TRUE` 误判为用户输入内联。后者已改成显式保护 active predicate，同时继续要求所有用户控制过滤参数化。
- Fresh 全量代码回归通过：geo_common 114 passed、geo_saas 466 passed、compileall 与定向 diff check 通过；生产实现仅修改 Topic ownership SQL 一处。
- 本地 6174 使用 gotyechen@gmail.com dev identity 与 AnswerX Workspace 完成真实 E2E：AI Brainstorming 生成 2 条候选，保存调用 `POST /api/prompts/batch` 返回 200，Prompt Editor 配额水位 20→22，服务日志无 `UndefinedColumnError`。
- 两条 E2E Prompt 已按精确 UUID 通过应用层 `PromptCascadeDeletionService` 的 batch-delete API 删除；数据库确认残留 0。Prompt 物理变体总量恢复为原先 174，逻辑配额恢复为原先 20。
- 部署前 fresh 回归再次通过：geo_common 114 passed、geo_saas 466 passed；`deploy_all.sh` 语法通过，且仅启用 SaaS API build/Terraform。SaaS API 版本由 v67 升至 v68。
- Cloud Build `77479f1e-9764-4485-bbf1-ffed1aed4325` 成功；Terraform 实际计划/结果为 0 add / 1 in-place change / 0 destroy，仅把 SaaS API v67 更新到 v68。
- Cloud Run 新 Revision `geo-saas-api-00048-8f2` 已承接 100% 流量；公开 `/health` 返回 ok，新 Revision 完成 asyncpg pool 与应用启动，部署后 ERROR 与 is_active 缺列日志均为 0。
- 已通过 Feishu CLI 以 Anthony bot 向 Lancelot Chen 发送完成通知，message_id `om_x100b6abff0e1eca4b1c97c8cad1d1d5`。
