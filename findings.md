# 当前迭代调研发现

## 2026-07-16 AI Brainstorming Prompt 保存失败

- Cloud Run `geo-saas-api-00047-58z` 日志显示 `/api/brainstorming/generate` 本身返回 200；失败发生在随后保存生成结果的 `POST /api/prompts/batch`，多次在 59–84 ms 内返回 500。
- 完整栈定位到 `PromptRepository.owned_topic_ids_on_connection()`：Topic 租户归属校验查询 `geo_client_topics` 时附加了 `AND is_active IS DISTINCT FROM FALSE`。
- Cloud SQL `information_schema` 只读核对确认 `geo_client_topics` 仅有 `id/client_id/topic_name/created_at/topic_type` 五列，从未存在 `is_active`；可停用状态属于 `geo_client_prompts.is_active`，产品启用状态属于 `geo_client_topic_products.is_active`。
- 因此根因不是 Brainstorming LLM，也不是 Prompt 展示 SQL本身，而是 active-only 语义被错误扩散到 Topic ownership helper。该 helper 被 `/prompts/batch` 共用，所以同时影响 Brainstorming 保存和通用批量创建。
- 正确边界：Topic ownership 仅按 `client_id + topic_id` 校验；Prompt 展示、Quota、Dashboard 和事实统计仍继续使用 `geo_client_prompts.is_active = TRUE`，不应撤销。

## 2026-07-15 浏览器与性能补充

- Dreamina Prompt 列表超时不是 SQL 执行慢：`geo_client_prompts` 的 14,400 行查询在数据库内约 5 ms，瓶颈是把全部物理变体跨代理传输并在前端合并。逻辑 concepts + 对齐 variants 能显著减小重复字段，同时不牺牲平台/国家联合筛选语义。
- Dreamina Citation 的线上式默认排序可用 current 全量聚合先分页、仅对候选 20 URL 聚合 previous 的 fast path；`change_pct` 全局排序仍保留完整 previous 聚合。真实页面从 60 秒失败恢复到 Domains 约 8 秒、Pages 约 6 秒。
- 浏览器 abort 不能作为数据库取消保证；前端分阶段释放重查询比扩大 pool/timeout 更可靠。pool 当前运行配置为 1–10，不是先前讨论的 8，因此代码仍按“每 Dashboard 最多 2 个重查询”控制自身压力。
- 新版方案 C 的 50k 行/16 MiB retained payload guard 与 asyncpg cursor prefetch 是两个独立维度。`prefetch=1` 不会显著降低 retained memory，却会让 Cloud SQL Proxy 承受数万网络往返；512 行有界批次约只增加一个小型传输缓冲，不改变最终硬上限。

## Migration 124–126 后历史报告兼容性（2026-07-14）

- 当前 Cloud SQL 有 17 份 `static-report-v2 / COMPLETED` 历史报告，`geo_static_report_lists` 当前为 0 行、0 份报告；AnswerX (Demo) 有 1 份 v2 历史报告。
- 历史 v2 报告仍通过原有 snapshot section API 渲染，不依赖 `geo_static_report_lists`，因此 Migration 后不会整体失效。
- 前端仅对 `static-report-v5` 显示新版排序控件；旧报告显示“历史报告不支持排序/比较”的提示。冻结列表 API 在旧版本缺少 Blob 时返回 `sorting_unavailable_for_snapshot_version`，客户端回退 snapshot 内已有的截断列表。
- 仅把旧 snapshot 的现有列表复制到新表不安全：旧 v2 缺完整 17 list-type 全量集合和 previous-period 数据，且列表曾被 20/50/100 Top-N 截断，不能伪装成 v5。
- 现有 `/materialize-date` 对已 `COMPLETED` 的相同 client/date/window 直接返回旧报告，不会自动升级；若要回填必须新增显式、幂等、受限并发的 re-materialize/backfill 工具。

## 静态报告存储方案性能复核（2026-07-14）

- 对比边界固定为两种都不读取 live Dashboard 事实表、两种都在 Cloud Run 应用内存中完成筛选/全局排序/分页；差异仅在冻结列表的持久化粒度与每次读取/解压范围。
- Dreamina 目前有两份 COMPLETED 7 天报告：2026-05-27 报告 `snapshot_json` 为 2,149,820 bytes stored / 19,991,802 bytes JSON text；2026-06-19 报告为 163,578 / 832,639 bytes。7 天窗口本身不是尺寸决定因素，实际由当期嵌套矩阵和数据完整度决定。
- 2026-05-27 的现存 Snapshot 内嵌可排序项合计 14,829；单个最大 list type 是 Topic/Prompt/Brand 与 Product/Prompt/Brand，各 6,219 行。2026-06-19 合计 5,245；两个最大 list type 各 2,249 行。一次排序请求只处理一个 list type/作用域，而不是同时排序全部 14,829 行。
- 主要 JSON item 的实际大小：Prompt/Brand 行约 74–83 bytes；Prompt 嵌套行约 616–1,043 bytes；Citation Domain 约 149–160 bytes；Citation Page 约 236–315 bytes。旧 Snapshot 的 Prompt 对象因内嵌 Brands 而较大，规范化后的 list blob 会显著小于完整嵌套对象。
- Cloud Run/Cloud SQL 证据确认 Dreamina 7 天物化慢点主要在聚合查询：2026-06-19 总请求 25.921s，stage 日志为 prompt_topic 24.705s、citations 21.180s、visibility 9.596s、sentiment 1.050s；这些阶段并行，最终 JSONB 写入在 stage 完成后约 60ms 内结束。2026-05-27 大报告 DB `created_at → materialized_at` 为 59.798s；2026-06-19 为 25.833s。
- 全库 COMPLETED 报告的现存样本：1 天 6 份，平均 4.265s/max 7.545s；7 天 10 份，平均 9.127s/中位 0.688s/max 59.798s；Dreamina 是显著大租户，报告窗口不是唯一变量。
- 本地标准库基准（代表性 JSON 行、Cloud Run 同类 Python 路径）：6,219 行 payload 0.568MB，JSON parse p50 2.97ms、排序 p50 1.16ms、峰值 Python 分配 2.77MB；14,829 行为 7.23ms + 3.21ms、6.61MB；100,000 行仍约 52ms + 39ms、44.6MB。Dreamina 当前列表规模的应用内存排序不是主要瓶颈。
- Cloud SQL 当前使用默认 PGLZ TOAST。对 Dreamina 2026-05-27 7 天大 Snapshot（2.15MB stored / 19.99MB text）只读解压并序列化完整 JSONB 约 75ms，提取并序列化 Visibility section 约 38ms；2026-06-19 小 Snapshot分别约 3.4ms/2.3ms。单次不大，但页面并行读取多个 section 时会重复 detoast 同一大值。
- Cloud SQL 日志给出更直接的数据库压力证据：Dreamina 2026-06-19 7 天物化的 40 秒窗口内产生 11 个 PostgreSQL temporary files，合计 288.63 MiB，最大单文件 80.40 MiB；实例 `work_mem=16MB`。慢点是 Citation/Prompt 聚合的 GROUP BY/ORDER BY 溢写临时磁盘，不是 Snapshot JSONB 写入。
- 源表已经存在按 `client_id + Shanghai date + prompt + domain/url` 的 Citation expression indexes，以及相似 Result/Brand Mention 索引；因此当前 spill 不能简单归因于完全缺索引，主要是 Dreamina 数十万 Citation 上的多组聚合、排序和重复 current/previous 查询。
- 实际 SaaS API Cloud Run 为 1 CPU/1GiB、container concurrency 80、maxScale 20；每实例 DB pool 配置为 8，单次 Snapshot 默认同时占用 coordinator + 3 worker connections。两次同实例并发物化即可占满 pool，交互请求可能等待连接；多客户同一时点日/周/月生成比内存排序更值得限流。
- Cloud SQL 为 `db-perf-optimized-N-4`、Enterprise Plus、100GB PD SSD。4-vCPU 级实例上同时运行多组可能溢写临时文件的聚合，会直接与在线 Dashboard 查询竞争 CPU/临时 I/O。
- 当前线上 `geo_static_reports` 17 行总大小约 14MB，其中 heap 16KB、索引 80KB，其余主要是 TOAST Snapshot；表索引数量本身不是当前压力来源。
- 必须区分两个“方案 C”：当前尚未执行的 Migration 125 是一条列表项一行，并用 `executemany` 插入成千上万行、数据库 ORDER BY 排序；本轮讨论推荐的 C 是每 Report/List Type 一个 JSONB blob（当前约 17 行/报告）并在 Cloud Run 内存排序。后者才是本次对比对象，当前 row-per-item 实现不应直接上线。
- 最终建议采用新版方案 C：主 `snapshot_json` 只保留 KPI、图表、比较数据、筛选元数据和离线/首屏所需的 bounded rows；完整列表按 `(client_id, report_id, list_type)` 存在约 17 个 JSONB blobs。列表 API 点查一个 blob，在 Cloud Run 内完成冻结筛选、稳定指标排序和分页。
- 新版 C 只需一个租户完整性唯一索引/主键（推荐 `(client_id, report_id, list_type)`）和 `(report_id, client_id)` composite FK；不建立 metric JSON expression indexes，不在 PostgreSQL 排序，不生成一行一列表项的 WAL/index/autovacuum 压力。
- C 的主要劣势：新增 schema/Repository 生命周期；完整列表与 Snapshot 首屏存在少量重复；17 个独立 JSONB 可能比单一大 JSONB 的跨列表压缩略差；必须单事务写入并在 blobs 全部成功后才标记 COMPLETED；每个 blob 仍需行数/字节上限防止未来超大列表占用 Cloud Run 内存。
- 一致性方案：Canonical full rows 只在构建器中生成一次；Snapshot 的默认首屏、frozen metadata、每个 list blob 都由同一 canonical rows 派生，并在同一事务落库。这样避免“两套计算逻辑”漂移。
- 用户给出的频率约为每客户每月 30 日报 + 4 周报 + 1 月报，即约 35 reports；新版 C 约 595 blob rows/client/month。即使 100 客户也约 59,500 rows/month，行数和 B-tree 索引压力很低，主要成本仍是 JSONB payload 本身。
- 存储方案不会解决现有 25–60 秒生成慢点。单独的稳定性要求应包括：定时任务错峰、全局物化并发限制、避免同一 API 实例同时跑两份大报告，以及后续针对 Prompt/Citation current+previous 聚合和 temp spill 做查询级优化。

## 独立工作流：SaaS 自定义域名迁移（2026-07-13）

- `geo-saas-web` 当前位于 `us-central1`，ingress 为 `all`，两个 `run.app` URL 的 `/health` 均返回 200；自定义域名迁移可以作为新增入口完成，不需要替换 Cloud Run 服务。
- 当前 SaaS Terraform 只管理 Artifact Registry、`geo-saas-api`、`geo-saas-web` 和 public invoker IAM，没有 Load Balancer、Serverless NEG 或 Certificate Manager 资源。
- SaaS Web 是 Vite 静态构建 + Nginx；浏览器默认同源调用 `/api` 和 `/api/agent`，Nginx 再代理到 API/Agent Cloud Run。域名接入不需要改前端 API base。
- DNS 由 GoDaddy 托管，`platform.answer-x.ai` 当前没有记录；Certificate Manager 与 Cloud DNS API 当前未启用。Cloud DNS 不属于本次需要，因为权威 DNS 继续保留在 GoDaddy。
- 采用 Certificate Manager DNS authorization 可以在正式 A 记录前签发证书；正式切换点仅是 GoDaddy 的 `platform` A 记录。
- Cloud Run 默认 URL 在迁移和稳定期继续开启。只有后续明确选择强制流量走 LB 时才收紧 ingress；本次不设置 `default_uri_disabled`，也不改变 SaaS API/Agent ingress 或 Scheduler audience。
- 最近 30 天 `geo-saas-web` 日志约为 0.068 GiB request、0.288 GiB response；按当前量级 LB data processing 费用近似可忽略，主要增量是前 5 条 global forwarding rules 合计约 18.25 美元/月。
- 中国大陆可达性不能由 Global LB 配置本身保证；正式切换前使用 `platform-canary.answer-x.ai` 做 48–72 小时电信/联通/移动真实网络验证。
- 当前 Cloud SQL 是 ZONAL、后端只有一个 `us-central1` Cloud Run 区域；域名迁移提供入口连续性和回滚能力，但不等于多区域或数据库高可用。

## 仓库状态

- 2026-07-13：工作区相对 `main` 有大量修改、删除和未跟踪文件；本轮按用户进行中的真实代码读取，不假定 `HEAD` 代表当前产品。
- 当前提交：`b0852d4 feat: auto-reset report status to analyzing on new data & fix syntax error`。

## 文档与架构

- 当前真实代码已明显超过 Git `HEAD`：SaaS、Admin、Agent 和公共层大部分为未跟踪或重构后文件，因此后续判断以工作区代码为准，并用测试补证。
- 主数据链路是 `Client → Topic → Client Prompt → Task(Query Fanout) → Result → Mentions/Citations/Sentiment`；需求 16–18 会横跨 Prompt 配置、Insights 聚合和静态快照三个读模型。
- 客户侧产品坚持“GEO 包 Agent”：Visibility / Citation / Sentiment 等确定性 SaaS 页面仍是核心，不应因为 Agent 层而改变本轮信息架构判断。
- `geo_common` 已承担共享 asyncpg pool、租户装饰器和 Repository；SaaS 与 Admin 各有自己的 FastAPI API 与 React 前端，但共享 Cloud SQL。
- README 明确现有 Insights 已包含全局 Date / Topic / Platform / Prompt Type 筛选，以及 Prompt 下钻；需要以当前源码确认 UI 是否与文档一致。
- 静态报告已有 SaaS 与 Admin 两侧路由、页面和测试，说明需求 18 是在既有 snapshot/readiness 体系上扩展，不是新建报告系统。

## 需求 16：Prompt 拆到 Sidebar

- `insights.json` 已把 Prompts 作为 Insights 系列页的一部分，且现有 Sidebar 只有 Overview / Visibility / Citation / Sentiment / Reports，没有一级 Prompt。
- 现有 Prompt 分析页已经声明 Topic / Product / Platform / Country / Prompt 等筛选、Topic/Product/Country 分组，以及 Visibility Score、Visibility Rank、Brand Rank、Mention、Total Query、Avg Position、Citation Count 等列；需要确认 API 实际返回与详情下钻范围。
- 现有 Visibility ranking matrix 已采用 group 懒加载 + Prompt 概念分页，Prompt 按规范化文本聚合而不是按 `geo_client_prompts.id`，这一语义应与独立 Prompt 页面保持一致。
- 全局 Insights filter bar 当前有名为 `Prompt Type` 的筛选；文档与性能方案称其为 `prompt intent filters`。需求中的“三种 intent filter”需确认是三个具体 intent 值，还是三组筛选维度。
- 路由层已有 `/prompts → /insights/prompts` 兼容跳转，新增 Sidebar 一级入口不一定要改最终 URL；但 Prompt 当前依赖 `InsightsLayout` 提供的日期、Topic、Platform、Country 等 Context。若真正“拆出 Insights Layout”，必须抽出共享 filter shell/context，而不能只搬路由。
- 当前 `AnalysisView` 对 Topic / Product / Country / Prompt 四种 target 都只请求 `getVisibilityComposed()` 并渲染 `VisibilityDashboard`，且没有把 Country、Prompt intent 等全部全局筛选一致传递；需求 16.1 需要新的跨 V/C/S 下钻契约。
- `GET /prompts/metrics` 只计算 Visibility-scope 的 response mention、score、brand rank、average position；`citation_count` 是兼容字段但始终写死为 0，Sentiment 完全没有进入 Prompt metrics。
- Prompt 列表在前端按 `text + topic_id + product` 合并多平台/国家行，再在浏览器合计各 ID 的指标。此方案没有服务端分页/排序，且“概念键”与 Visibility matrix 的规范化文本键未完全统一。
- `geo_global_intents` 的 `intent_name` 与 `categories` 是两层概念：一个业务 intent 可同时归属 Visibility / Citation / Sentiment 指标类别。当前全局 filter UI 却把 `PROMPT_TYPES = [Visibility, Sentiment]` 硬编码为可直接发送给 `cp.intent` 的值，Citation 代码又把请求值当 intent name；这既漏掉 Citation，也存在类别与 intent 名混淆风险。

## 需求 17：Prompt 批量上传

- Prompt Editor 已显示“批量上传”和“导出”按钮，但两个按钮都没有 handler；拆分出的 `Toolbar.tsx` 也同样只是无行为按钮，说明功能是明确占位而非隐藏实现。
- 后端已有 `POST /prompts/batch`，但这是 Brainstorm 保存接口：接收结构化 JSON，将每条概念按 platforms × countries 展开，并原子插入；它没有 CSV template / preview / commit，也没有完整校验 topic 归属、intent 合法性、product 与 topic 关系、platform/country/language 配置集合。
- `PromptRepository.add_many()` 在单事务中逐行插入，具备 all-or-nothing 基础；quota 以 `(text, topic_id)` 唯一概念计数，但当前没有统一规范化空白/大小写。
- 仓库已有成熟的 Published Pages CSV 模式：后端生成模板、限制文件大小/行数、服务端解析、逐行 preview、租户内 Topic 名称解析、重复检测、commit 前再次校验；前端用自定义 Dialog 显示 create/update/invalid。这是 Prompt 上传最适合复用的交互与测试范式。
- Prompt 的重复处理不能直接照搬 Published URL upsert：同一概念会展开为多个 platform × country row，且已存在组合可能需要 skip / update / reject 的明确产品决策。

## 需求 18：静态报告

- 既有静态报告是每租户每天一份、Asia/Shanghai 日期、默认最近 7 天、完成后对 SaaS 用户不可变的 JSON snapshot；详情页禁止调用动态 dashboard API。
- Snapshot 已预留 `visibility`、`citations`、`sentiment`、`prompts`、`topics` 等分区和 schema version，因此同环比与排序必须在 materialization 时固化，或明确作为 snapshot 内的本地排序，而不能静默取动态数据。
- 动态 Citation 已存在 period-over-period count/share change；Sentiment 已存在上一周期对比；Visibility 也返回 previous series。需要复用统一周期语义，避免静态报告另造口径。
- 性能规范明确：snapshot 只保存 summary/chart 和列表首屏；长列表后续页可以由 live paginated API 拉取。但这与原始静态报告“详情页不调用 live metric API”存在张力，是本轮必须显式解决的设计点。
- 当前实现已升级为 `static-report-v2` 和分 section API，但静态页面一旦选择 Topic/Platform filter，就直接调用 live Visibility/Citation/Sentiment API；未筛选时才读取 snapshot section。这已经偏离原始“完全静态”定义，也会让同一报告随底层数据变化。
- Snapshot builder 中多数同环比字段目前明确为 `None`：Visibility score / avg position，Citation own share 与 domain/page change，Sentiment positive % 与 theme occurrence change；rank change 字段也未完整生成。需求 18.1 是后端 materialization 口径缺失，不只是 UI 未展示。
- 现有 snapshot 已包含当前窗口内的逐日 series，但没有为“上一对等周期”保存数据；严格环比需要额外查询 `[window_start - window_days, window_start - 1]` 并把 current/previous/delta 固化进 snapshot。
- 通用 `SnapshotTable` 只支持搜索、展开与 show all，没有排序状态；Prompt/Topic 表分别只有 mention_count 与 citation_count，Prompt 还按物理 `prompt_id` 行展示，和动态 Prompt 页面按概念合并的语义不一致。
- 静态 V/C/S 组件大量使用各自表格，而不是统一 `SnapshotTable`；因此“所有列表按各指标排序”需要先建立列表清单和统一 sort descriptor/可排序表头组件，否则静态、动态容易再次分叉。
- Snapshot builder 当前硬限制 Visibility ranking 20、Citation domain/page 20、Prompt/Topic 100；如果只在前端对已截断集合排序，得到的不是全量排名。需要区分“对当前载入页排序”与“全量服务端排序”。

## 需求 19：Admin 品牌 Alias

- SaaS Workspace Settings 的 Brands Tab 通过 `/api/settings/brands` 和 `BrandRepository` 直接读写 `geo_client_brands.aliases`，同时支持多个 Own / Shadow brand；Analyzer phase 0、BrandParser、n-gram discovery、Agent content/citation context 都以该表为品牌 source of truth。
- Admin Clients 页面仍把 `geo_clients.aliases` 和 quota / Agent limits / expansion settings 混在同一个“Edit Info”表单里，保存时调用 Admin `PUT /clients/{id}` 更新 legacy aliases；它不会同步 `geo_client_brands`，因此 UI 会显示“保存成功”但不影响 Analyzer 品牌匹配。
- `geo_clients.aliases` 是 v1.2 以前的遗留字段。Migration 043 只在迁移时将旧 aliases 复制到新的 own brand 行；之后没有双写或数据库同步机制。
- 需求中的“让 Admin 直接编辑对应行”有一个真实建模问题：一个 workspace 可有多个 Own brand，不能再默认 `geo_clients.name` 唯一对应某个品牌。Admin 若保留编辑能力，应展示 `geo_client_brands` 列表并以 `brand_id` 更新，而不是继续在 Client Info 中放一个扁平 aliases 数组。
- 最小风险方案是从 Admin UI 的 Client Info 中移除 legacy alias 编辑/展示，并从该表单 payload 去掉 `aliases`；是否连 Admin API schema / `geo_clients.aliases` 字段一起弃用属于单独兼容与 migration 决策。

## 需求 20：Workspace 删除报错

- 根因链已由代码支持：Admin `DELETE /clients/{id}` 先 `get_by_id()`，随后同步执行单条 `DELETE FROM geo_clients WHERE id=$1`；大量子表通过 `ON DELETE CASCADE` 清理，整个级联期间独占一条共享连接。
- Admin 的单一 asyncpg pool 默认 `min=1, max=10`，没有 SaaS 已有的 query timeout、statement timeout、pool acquire timeout，也不能通过配置调整 pool size。10 个并行长删除即可耗尽池。
- 创建 workspace 的第一步是 `ClientRepository.get_by_name()`，它也必须先从同一 pool acquire；池耗尽时请求卡在获取连接之前/期间，确实不会运行到名称重复 SQL，更不会返回预期 400。
- 前端删除按钮没有 `deletingClientId`、disabled 或重复提交保护；API 没有同 workspace 幂等锁、全局删除并发上限、删除任务状态或 202 Accepted 模式。
- Admin 与 SaaS 形成鲜明差异：SaaS adapter 已有 60s query/statement timeout、10s acquire timeout和环境化 pool size；Admin adapter 仍是旧的无限等待实现。但把这些 timeout 简单复制到 Admin 只能让请求更快失败，并不能完成大 workspace 删除。
- 数据库存在多层 CASCADE（client → prompt/topic/brand/static reports/agent/published URL 等，再到结果、mentions、citations 等）。生产级修复应把删除从请求连接池的同步事务移出，做持久化、幂等、有限并发的后台删除；前端返回可跟踪状态。连接池 timeout、按钮禁用和数据库索引应作为防御层而不是根治。
- 当前没有 Workspace 删除的路由/Repository/前端并发测试，也没有删除任务模型；任何异步方案若需新表必须以 migration SQL 提交，不能直接 DDL。

## 待澄清问题

### 用户已确认（2026-07-13）

- 需求 16 的信息架构已确认：从 Visibility 顶部移除 Prompt Tab，在 Sidebar 的 Sentiment 与 Report 之间新增一级 `Prompt`；中英文均叫 `Prompt`；内容沿用当前 Prompt 页面。
- Prompt 的 Topic / Product / 单 Prompt 三个 Hover 下钻入口都要展示完整 Visibility / Citation / Sentiment 图表，并参考静态报告的完整图表组合。
- 排序覆盖所有指标型列表：Prompt 三类下钻里的列表、现有动态 Visibility/Citation/Sentiment 列表以及静态报告列表；交互为列头升/降序箭头。
- 静态报告比较周期需对齐动态 Dashboard：1 天对前 1 天、7 天对前 7 天，即“当前选择区间 vs 紧邻的等长上一周期”。
- 需求 17 明确不是“没有 batch API”，而是“没有安全、通用的表格批量导入体验”。用户指出 Migration 118 的校验与事务思路可复用，但固定客户/Topic/7200 行/60 组合及 DELETE rollback 不可复用。
- 需求 19 的原则是 Admin 完全对齐 SaaS 的品牌表；代码复核确认当前运行时事实源确为 `geo_client_brands.aliases`，Admin Clients 仍在编辑 legacy `geo_clients.aliases`。
- 需求 20 优先考虑低改造的产品引导，不默认上持久化异步删除系统；用户提出先手工删除 Prompt、Topic 等关联实体再删除 Workspace 的候选路径。
- 用户纠正动态下钻的数据来源：必须直接复用现有动态 Visibility / Citation / Sentiment Dashboard 的指标、API 和数据结构；静态报告不是动态下钻的实现参考，只是最终需要保持指标口径一致的另一个消费者。
- Intent filter 按 Prompt 的真实 `intent` 字段取值生成选项，不按 V/C/S category。候选值必须实时来自数据库（优先受管控的 Global Config，并结合实际 Prompt 数据验证），禁止在前端写死三种枚举。
- 需求 19 的范围进一步收紧：SaaS UI、Analyzer、数据库 schema 均不改；只修复 Admin 的 Alias 读写，使其操作与 SaaS 相同的 `geo_client_brands.aliases`。
- 需求 20 的产品方案已获认可：删除准备情况对话框 → 停止调度 → 批量删除 Prompts → 删除 Topics → 回到 Admin 执行最终 Workspace 删除；最终确认输入 Workspace 名称，请求期间禁用按钮。

### 代码复核补充

- Admin 当前没有现成的 `geo_client_brands` CRUD/alias router；只有 Clients router 的 legacy `geo_clients.aliases` 和不相关的 Brand Profile router。因此“只改 Admin”仍需要极小的 Admin API 适配层（使用共享 `BrandRepository`），不能让浏览器前端直接访问数据库，也不应改 SaaS API/schema。
- Prompt 的显式级联删除服务已经实现：`PromptCascadeDeletionService.delete_many()` 在同一事务内按 tenant + prompt IDs 锁定目标，并依次删除 sentiment themes/results、citations、product/brand mentions、results、tasks、prompts；SaaS 单条与批量删除路由已经调用该服务。

### Cloud SQL 真实数据复核（Lancelot ADC，只读，2026-07-13）

- 使用新启动的隔离 Cloud SQL Proxy（15433）连接 `answer-x-geo-db`；Proxy 明确以 Application Default Credentials 授权，数据库会话强制 `transaction_read_only=on`。
- `geo_global_intents` 当前恰有 3 个启用值：`Solution Discovery`、`Specifics Inquiry`、`Competitive Evaluation`。注意实际值是 `Specifics Inquiry`，不是用户口述的复数形式。
- Prompt 实际还有一个不在启用 Global Config 中的历史值：Pandaaa workspace 的 `general` 共 4 条物理行/1 个 concept。代码追踪发现 Prompt Editor 的新增、复制路径仍硬编码 `p.intent || "general"`，这正是数据库驱动筛选/写入必须消除的漂移源。
- 17 个有 Prompt 的 workspace 均无 NULL/空 intent；全库分布为 Solution Discovery 16,863 行、Competitive Evaluation 529 行、Specifics Inquiry 523 行、general 4 行。
- 所有 Prompt 的 `topic_id + client_id` 归属均正确（0 条跨租户/悬空 Topic），说明现存数据干净，但 batch API 仍需显式校验，不能依赖当前数据碰巧正确。
- 全库存在 8 组 exact duplicate Prompt variant（同 client/topic/normalized text/platform/country/language），共 10 条额外重复行；AnswerX 4 组、Pandaaa 4 组。通用导入 Preview 必须把历史重复与本次上传重复分别报告。
- Alias 真实数据验证了 canonical/legacy 已分叉：CometAPI、OpenJobs、Pandaaa 的 canonical aliases 有值而 legacy 为空；HYP 两边内容不完全一致；只有 AnswerX (Demo) 示例完全一致。运行时只读 canonical 品牌表是必要修复。
- Cloud SQL 当前有 17 份 `static-report-v2` COMPLETED 快照（1/7/30 天窗口）。17 份的 `visibility_score_change`、`avg_position_change`、`own_domain_share_change`、`positive_pct_change` 全部为空，Visibility/Citation previous series 也全部为 0 点，确认需求 18 是 snapshot materialization 缺口。
- Workspace 数据量差异极大：Dreamina 有 14,400 Prompt、326,520 Task、313,989 Result、3,492,352 Citation、777,471 Brand Mention；AnswerX Demo 也有 63,737 Citation。引导式清理不能一次把全部 Prompt IDs 放进单个长事务。
- Prompt 级联相关表总量约为：geo_results 5.3 GB、geo_citations 3.3 GB、geo_tasks 403 MB、geo_brand_mentions 317 MB。多个大表没有直接以 `(client_id, client_prompt_id)` 开头的删除友好索引；现有索引常把日期放在 prompt 前，删除扫描可能仍然昂贵。
- 动态 API 契约并未完全支持三种下钻：Visibility 已支持 topic/product/prompt_ids；Sentiment 支持 topic 和 product names，但不支持 prompt_ids；Citation 只支持 topic（以及平台/国家/日期/旧 prompt_type），不支持 product 或 prompt_ids。实现时应扩展现有动态端点的 filter 参数并复用其计算逻辑，不另建静态报告式计算。
- Cloud SQL 中 344,974 条 Result 与所属 Prompt 的 Product 字段 0 条不一致，因此 Product 下钻可以把 `geo_client_prompts.product` 作为统一筛选语义；但 316,127 条 Result 所属 Prompt 的 Product 为空，空 Product 需要排除在 Product 分组外而不是显示成一个伪产品。
- 当前 Global Config 启用 5 个平台；不同 workspace 的 config_platforms/config_countries/config_languages 差异显著。CSV 模板必须按当前 workspace 动态生成/校验，不能用全局全集作为该客户的 allowlist。
- Published Pages CSV 现有模式可直接复用交互骨架：UTF-8 BOM、英文 header、多行 sample data、文件大小/行数限制、服务端 Preview、行号/action/errors、invalid 阻止 commit、commit 前重新 Preview。
- 17 份现有 Snapshot 大小约 53 KB–4 MB；Prompt/Domain/Page 等列表普遍 cap 在 100 行，Theme cap 50，Visibility cap 20/21。在线 Snapshot 排序若不新增全量 list materialization，只能对 report_id 已冻结的 materialized rows 排序，不能宣称覆盖 cap 之外的数据。

### 新版方案 C 与生成性能复核（2026-07-14）

- 新版方案 C 不是“每份报告 17 个业务 item”，而是 17 个注册 `list_type`：品牌 Visibility/SOV/Position、Topic/Product 及其 Prompt/Brand 下钻、Citation Domain/Page/Category、Sentiment Theme、Prompt/Topic ranking。每个 type 一个 JSONB blob，因此每份完成报告固定 17 行。
- Dreamina 最大已生成 7 天报告约有 14,829 个可排序 item，最大单列表 6,219 行；Python 解析约 7 ms、排序约 3 ms、峰值约 6.6 MB。瓶颈不是 Blob 内存排序，而是事实表聚合。
- Dreamina 30 天月报只读实测（报告日 2026-07-14）：current + previous 两个相邻 30 天周期按 URL 聚合后共有 220,036 行，其中 current 167,629 行、previous 107,456 行，未压缩聚合行 JSON 约 44 MB。单个 16 MiB Blob 必然不足，但 v5 将 16 MiB 作为物理分片上限；当前周期页面列表按 25,000 行上限约拆为 7 个连续分片，仍低于聚合保护 300,000 行/96 MiB 和整份冻结列表保护 300,000 行/128 MiB。
- 代表性生成阶段中 Prompt/Topic 约 24.7 s、Citation 约 21.2 s、Visibility 约 9.6 s；同窗口 Cloud SQL 产生 11 个临时文件、合计约 288.63 MiB，确认应优化聚合形态和并发，而不是为 Blob 内部字段建大量数据库索引。
- 把 current/previous 强行合并为更大 14 天扫描在 Dreamina 只读实测超过 60 s，已撤回。最终使用两个较小窗口分别预聚合，减少查询形态和 cross product，但不以“扫描次数最少”压倒稳定性。
- Cloud SQL 全局 `work_mem=16MB` 保持不变；报告事务使用 bounded `SET LOCAL 32MB`（16–64 MB），因为 `work_mem` 是每个 sort/hash 节点、会话及 parallel worker 的预算，不能按“一条 query 只用一次”理解。
- pool max 8 下，每份报告固定 coordinator 1 + worker 最多 2，预留至少 5 个连接；单实例 semaphore=1、跨实例 transaction advisory lock=1。抢不到全局容量时释放 fenced lease 并返回 PENDING，不等待连接池。
- 当前报告生成低频且分散，本轮不引入 Cloud Tasks。未来若添加 scheduler，可按 client_id hash 错峰，但仍必须服从相同全局锁。
- AnswerX Demo 2026-07-14 真实只读 smoke：Citation 477 个 aggregate rows 约 2.15 s；Sentiment 2 个 summary rows、165 个 theme rows、50 examples 约 2.59 s。新 asyncpg SQL 参数契约已在真实 PostgreSQL 验证。

### 2026-07-15 补充：Import、报告授权与 Citation change 排序

- Prompt Import quota 按 logical concept `(topic_id, canonical prompt text)` 计算，不按 platform × country 物理展开数计算。Preview 返回 quota_before/quota_after/limit；超限会把所有待 create variants 标为 `quota_exceeded` invalid。Commit 在事务和 workspace lifecycle shared lock 内重新 Preview，并同时校验 manifest/state hash，所以 Preview 后 quota/config/data 变化会 stale/拦截，不能绕过。
- 静态报告 URL 直接访问具备服务端硬鉴权：report payload 与 access predicate 在同一 SQL 中执行，未授权时数据库不返回 snapshot/section；所有详情 section 和 HTML export 采用 authorized repository 方法。前端 summary 成功之前不启动图表 section loaders。
- 静态报告底部 Prompt/Topic/Product 三张表来自额外 `promptTopic` section，并不是 Visibility/Citation/Sentiment 完整报告所必需；用户已明确报告应在 Sentiment 结束，后续应移除该 section 的前端加载与渲染。是否保留 v5 内部冻结 blobs 需以筛选/兼容依赖为准，避免为纯 UI 删除破坏 canonical snapshot。
- Dreamina 7 天 cited-pages `change_pct` 失败点在 PostgreSQL 查询而非 Python 内存排序：API 日志显示 asyncpg `fetch_all` 60 秒 TimeoutError；默认 citation_count fast path约 4.82 秒。差异是默认路径先分页 current 再只聚合 20 个 previous candidates，而 change 全局排序必须计算所有 current URL 的 previous share，当前 full previous aggregate + join + window sort 过重。
- 静态报告的进程内缓存不改变冻结语义，也不会重新查询动态数据；它只避免重复从 JSONB 解码完整冻结列表。原始 61 MiB payload 无论是否缓存都存在。
- 仅使用进程内缓存不足以覆盖 Cloud Run 多实例。最终方案在同一 `geo_static_report_lists` 表中保存约 3.64 MiB 的排序位置索引；冷实例读取单个约 0.63 MiB index，并按 global position 从 25,000 行分片精准抽取 20 个 JSONB 元素。
- 30 天报告无需把内存预算抬到 256 MiB：逐行 bytes + `array('I')` 排序索引实际为 68.35 MiB，128 MiB 全实例 LRU 足以保留一个最大热列表并自然淘汰旧条目。
- 持久化排序索引与 snapshot/list blobs 在 fenced materialization 的同一数据库事务写入；报告只有在完整数据和索引都成功后才变为 COMPLETED，不存在报告完成但索引半写入状态。
- 历史 v5 报告没有排序位置索引时仍走旧兼容读取；不会影响查看。新报告使用跨实例快路径。历史 v2 报告继续保持原先可查看、但无新版全量排序/上一周期能力的兼容边界，无需批量回填。
- Dynamic cited-pages/cited-domains 的 change 全局排序已改为单次 prev_start..end_date 扫描，并用 `COUNT(*) FILTER` 同时计算 current/previous；消除了 planner 对两个高基数聚合结果 join 的错误膨胀估算和对应 spill 风险。

### 仍需确认

- “Prompt filter 增加三种 intent filter”中的三种到底是 V/C/S 三个 category，还是三个具体 `intent_name`；当前数据模型两者不同。
- 列表排序是否要求对全量结果做服务端全局排序，还是允许对当前已加载/快照截断的数据做本地排序；两者对 API 和快照结构影响很大。
- 静态报告对比口径只描述了等长上一周期，需求文字中的“同比”是否还要求 1 年前同期；目前用户给出的例子实际是环比。
- Prompt 通用批量导入的输入载体与重复策略：CSV/Excel/飞书导出表格，以及对已存在 concept × platform × country 组合采用 skip、update 还是整批拒绝。
- Admin Alias 是移除 legacy UI 后跳转 SaaS 管理，还是在 Admin 中新增真正按 `brand_id` 编辑 `geo_client_brands` 的品牌列表。
- Workspace 引导式清理必须界定哪些实体由用户手工清理；仅删除 Prompt/Topic 可以通过现有 PromptCascadeDeletionService 清理大部分事实数据，但 Workspace 仍有静态报告、Agent、Published URLs、权限等其他级联实体，不适合要求用户逐一寻找。
- 等用户提供指定账号后，重新完成 ADC 登录验证并连接 Cloud SQL，以真实 Global Config 与 Prompt distinct intent、品牌行和 Workspace 关联数据量验证设计；在此之前所有结论仅为代码级确认。
- 需求 17 第一版上传载体仍需确认：本地 CSV（可从飞书表格导出）还是直接读取飞书表格链接；两者认证、审计和实施范围完全不同。
- Workspace 引导清理的实现必须决定是否接受一个轻量索引 migration + 分批级联删除；纯 UI 引导无法消除 Dreamina 级数据量下的长事务风险。
# Admin Scheduler 无损恢复证据（2026-07-15）

- 拓腾 `89b03a38-b49f-469f-80c4-8740113372fe`：Admin `PUT /api/clients/{id}` 在 2026-07-15 05:22:13Z 以 200/0.13s 返回，数据库已更新为 Collector `37 13 * * *`、Analyzer `37 14 * * *`；随后两个后台 `UpdateJob` 均返回 `504 Operation deadline exceeded`，所以 UI 的“保存成功”只代表 DB commit，不代表 Scheduler 同步成功。
- Cloud Audit 证明请求确实到达 Scheduler，`cloudscheduler.jobs.update` 权限为 granted=true，update mask 已是 `schedule,time_zone`；不是漏调 SDK，也不是 IAM 缺失。
- EaseUS `6087dc15-bb68-47ab-82d7-cf2a7a11719f` 数据库有 Collector `17 1 * * *`、Analyzer `17 3 * * *`，但实际 Job 不存在。05:21:05–10Z 的 Enable 请求实际调用了 `CreateJob`，`cloudscheduler.jobs.create` 同样 granted=true，但多次返回 504，前端因此持续显示 NOT_FOUND。
- 当前 v29 的有限 SDK 重试并未解决 GCP Scheduler 写调用失败；下一步必须与迭代前成功写入路径逐项对比，尤其是调用方式、请求载荷、timeout 和运行身份，而不是继续延长 timeout。
- 历史审计确认 2026-07-01 的线上 Admin API 曾以同一个运行服务账号通过 Python gRPC SDK 成功 UpdateJob；当时 user-agent 为 `grpc-python/1.81.0`。当前 v29 镜像构建日志安装了未锁定的最新版 `google-cloud-scheduler 2.20.0` + `grpcio 1.82.1`，失败审计 user-agent 正是 `grpc-python/1.82.1`。仓库 requirements 仅写 `google-cloud-scheduler>=2.13.0`，因此一次与 Scheduler 需求无关的镜像重建也会静默升级传输依赖。
- 尝试以本地用户 impersonate Cloud Run 服务账号做 REST 隔离实验被 IAM `iam.serviceAccounts.getAccessToken` 拒绝；没有修改 Scheduler。该失败只说明当前用户没有 TokenCreator，不能据此判断 REST/服务账号组合。
- Admin Dockerfile 虽安装 gcloud CLI，但 Workspace Scheduler 的历史/当前实现均使用 Python SDK；本轮应优先恢复已知成功的 SDK 版本组合，而不是把业务逻辑改写为 subprocess gcloud。
- Cloud Run 修订史确认：7 月 1 日成功更新运行在 `v26` 镜像（2026-06-05 构建，直到 7 月 15 日 04:21Z 前未重建）；本轮首次部署产生 `v27`，随后 `v28/v29`。因此“代码需求未涉及 Scheduler 但功能回归”的时间边界与镜像重建/依赖重新解析完全吻合。
- 实际 Job 对账：拓腾短名 Collector/Analyzer 均存在且 ENABLED，但仍为 `30 13` / `30 14`；EaseUS 正式与 Deprecated 均无匹配 Job。当前 Revision 是 `geo-admin-api-00030-6n7`、镜像 v29、运行身份仍为原 compute service account。
- 传输隔离实验成功：使用同一个官方 `google-cloud-scheduler` Python SDK，仅将 transport 从默认 gRPC 改为 `rest`，`UpdateJob(schedule,time_zone)` 在约 10 秒内成功把拓腾 Collector 原地更新为数据库目标 `37 13 * * *`。这证明 Job、Cron、API、Python SDK 高层模型均有效；当前回归集中在未锁定的新 gRPC 传输组合，而非业务参数。
- 该实验只修改了用户本来要求同步的拓腾 Collector 时间；Analyzer 尚保持旧值，等待修复后的服务链路统一验证。
- 修复实现已把 Workspace Scheduler 客户端固定为官方 SDK REST transport，并将已实测组合锁定为 `google-cloud-scheduler 2.19.0`、`google-api-core 2.30.3`、`grpcio 1.80.0`，避免无关镜像重建再次漂移。
- 外部 Job identity 已恢复为迭代前短名 `geo-{type}-{workspace_uuid前8位}`；历史回归期间可能创建的全 UUID 名称仅保留兼容更新/删除，不再作为新建目标。短名操作仍以 description + target URI/body 中的完整 Workspace UUID 做归属校验，防止极小概率前缀碰撞造成跨租户操作。
- Cron 更新现在在 Workspace lifecycle fence 内等待 Scheduler create/update/delete 成功后才返回；失败返回 502 `SCHEDULER_SYNC_FAILED`，不再出现 DB/UI 200 但外部任务未同步的假成功。NOT_FOUND Enable 复用同一确认链路。
- Admin 后端全量测试 91 passed，Scheduler 控件 Node 契约 1 passed，Python compileall 通过；待部署后以 LensLogTest 做真实创建/更新/Pause/Enable 验证。
- `deploy_all.sh` 仅构建并部署 Admin API `v30`；Terraform 计划为 0 add / 1 in-place change / 0 destroy，Admin Web `v31` 与其他模块均未构建。Cloud Run 修订 `geo-admin-api-00031-km5` 已承接 100% 流量，启动后 ERROR 日志为 0。
- LensLogTest `d4e26b3f-b11d-43fe-88b2-85bed3241a4b` 真实 E2E：创建短名 Collector/Analyzer（15:11/15:21）成功；同名原地更新到 15:12/15:22 成功；Collector Pause 成功；人工删除 Collector 后页面显示 NOT_FOUND 且 Enable 可用，点击后按保存 Cron 重建成功。最终两条测试任务均 PAUSED，避免自动运行。
- 拓腾已通过修复后的 Admin 保存链路对账：数据库与 Scheduler 最终一致为 Collector `37 13 * * *`、Analyzer `37 14 * * *`，两条均为既有短名且 ENABLED；没有创建全 UUID 重复任务。
- EaseUS 只读 UI 验证：已保存 Cron 的 Collector/Analyzer 在 Job 缺失时均显示可用 Enable；未配置 Cron 的 LLM Discovery Enable 正确禁用。为避免真实客户任务被意外创建，本次未点击 EaseUS Enable。

# AI Brainstorming Prompt 保存 is_active 根因与修复（2026-07-16）

- GCP 日志中的失败发生在 Brainstorming 生成完成后的 `/api/prompts/batch` 保存阶段，`/api/brainstorming/generate` 本身为 200；调用栈落到 `PromptRepository.owned_topic_ids_on_connection`。
- 错误 SQL 对 `geo_client_topics` 加了 `is_active IS DISTINCT FROM FALSE`，但真实 schema 的 Topic 表没有 `is_active`；active 状态属于 `geo_client_prompts`（以及产品配置表），不能泄漏到 Topic tenant-ownership 校验。
- 最小修复仅从 Topic ownership SQL 删除错误 predicate，仍保留 `client_id + topic_id` 双重所属校验；Prompt 展示、配额、variant 解析和动态指标中的 `geo_client_prompts.is_active = TRUE` 均未改变，并有回归断言保护。
- AnswerX 本地浏览器验证了完整 Generate→Save→Reload 链路，`/api/prompts/batch` 返回 200；随后经应用级联删除 API 精确回滚，测试数据残留为 0。

# Dreamina Prompt 平台/国家迁移事实（2026-07-21）

- Cloud SQL 连接已以 `lancelot.chen@answer-x.ai` ADC 和本地 Proxy 15432 实时验证；显式 `BEGIN READ ONLY` 会话显示 `transaction_read_only=on`。Dreamina 当前 `client_id` 实时查询为 `b0e10518-5f70-426f-b09e-dbe025984ba1`。
- `geo_clients` 当前配置：平台 `{chatgpt,gemini,aimode,aioverview,perplexity}`，国家 `{US,GB,CA,FR,DE,IT,ES,BR,MX,SG,MY,JP}`，语言 `{en-US}`，Prompt quota 300。
- Dreamina `geo_client_prompts` 当前 14,400 物理行：7,200 active + 7,200 inactive；active 侧为 120 个 `(topic_id,text)` logical Prompt，每个完整展开为 5 平台 × 12 国家 × 1 语言 = 60 行。
- 120 个启用 logical Prompt 的 Topic 构成为 `AI Image=80`、`AI Video=30`、`AI Design=10`；`AI Creative Tools=120` 全部为 inactive，本次目标迁移不会将它们重新启用或纳入新的国家/平台展开。
- 用户指定的 canonical ISO country code 与 Admin UI 实际 code 对应为：美国 `US`、巴西 `BR`、墨西哥 `MX`、新加坡 `SG`、马来西亚 `MY`、印度尼西亚 `ID`、菲律宾 `PH`、泰国 `TH`。
- Admin UI 国家选项并非独立国家表，而是当前所选 `geo_global_platforms.supported_countries` 的 union；Prompt Editor 再与 `geo_clients.config_countries` 求交集。
- 当前 Global Config：ChatGPT/Gemini 包含全部 8 个目标国家；AI Mode/AI Overview 只登记 `US`。但 Dreamina 现有 active 数据是所有平台与 12 国的完整笛卡尔积，包含 AI Mode/AI Overview 的非美国组合，说明历史数据未遵循当前 platform-country allowlist。
- Cloro 当前官方 AI Overview 页面声称 Google/AI Overview 支持 any country / 250+ locations，和仓库旧的“先只启用 US”保守配置存在时间漂移；仍需用 Cloro countries endpoint 或现行接口契约核实 AI Mode/AI Overview 的精确平台国家支持，而不能只按旧 seed 值判断。
- 已通过 Cloro 当前官方 `/v1/countries?model=...` 接口逐个平台实时核对：`chatgpt`、`gemini`、`aimode`、`aioverview`、`perplexity` 均返回全部 8 个目标 ISO code（`US/BR/MX/SG/MY/ID/PH/TH`）。因此 Dreamina 目标 4 平台 × 8 国家在当前 Cloro 能力上成立；数据库中 AI Mode/AI Overview 仅登记 `US` 的 Global Config 已过时。
- 现有 7,200 inactive 行虽然也是 5 平台 × 12 国家 × 120 logical Prompt，但与当前 120 个 active logical Prompt 的 `(topic_id,text,product,intent)` 精确交集为 0，不能作为 ID 稳定的目标行复用。新增 `ID/PH/TH` 必须为当前 120 logical Prompt 新建 1,440 个物理行。
- 目标迁移的物理变化为：保留当前 4 平台 × 5 个重叠国家的 2,400 active 行；停用 Perplexity 全 12 国 1,440 行和其余 4 平台的 7 个移除国家 3,360 行，共停用 4,800 行；新增 4 平台 × `ID/PH/TH` × 120 = 1,440 行；最终 active 为 3,840 行。
- 不应原地改写旧 Prompt 行的 `platform/country`，否则旧 `geo_tasks/geo_results/geo_citations/geo_brand_mentions` 会通过原 Prompt UUID 被错误地重新解释为新国家/平台；也不应 DELETE，因 Prompt→Task→Result 为级联删除且 Citation/Mention 还有非 FK 的直接 prompt_id 关联。正确策略是保留旧 UUID 并 `is_active=FALSE`，只为新增组合创建新 UUID。
- 被停用的 4,800 Prompt 行目前关联约 250,470 Task、239,450 Result、2,546,562 Citation、572,323 Brand Mention、29,916 Sentiment Result、45,485 Sentiment Theme。`is_active` 状态更新本身不会删除这些事实行，原始历史数据仍物理保留。
- 但当前动态 Dashboard 的公共过滤器、Visibility/Citation/Prompt metrics，以及“固定日期范围动态取数”的新版静态报告均要求 `geo_client_prompts.is_active=TRUE`。因此迁移后回看过去日期时，被停用组合不会参与重算；历史页面显示值会变化。按全量事实行粗略统计，现有 active Prompt 关联 363,548 Result / 4,071,370 Citation，迁移后具有历史数据的重叠保留组合约剩 124,098 Result / 1,524,808 Citation；新增三国在历史区间自然为 0。
- Collector 也只加载 active Prompt，故只更新 `geo_clients.config_platforms/config_countries` 并不足以停止旧组合；必须同步转换 `geo_client_prompts.is_active` 与新增目标行。
- 通用 `/api/prompts/batch` 目前只校验 workspace 级 platform/country/language allowlist；CSV Import 的 resolver 还会校验 `geo_global_platforms.supported_countries`。若只改 Dreamina client config 而不修正过时的 AI Mode/AI Overview Global Config，未来 Allowed Values/CSV 导入仍会错误拒绝这些平台的非美国目标国家。
- Cloro 2026-07-21 live country lists 已固化到 Migration 128：AI Mode 212 个、AI Overview 230 个，两份列表分别保存且与 live payload 精确逐项匹配；该 migration 只更新 `geo_global_platforms.supported_countries`，不触碰 Workspace、Prompt 或历史事实。
- Dreamina 原 12 国与目标 8 国的交集为 `US/BR/MX/SG/MY`；移除的是 `GB/CA/FR/DE/IT/ES/JP`，新增的是 `ID/PH/TH`。历史动态指标变化同时来自“移除 7 国”和“移除 Perplexity”，并非只有国家变化。
- 对旧停用行执行反向 `is_active=TRUE` 可以重新把其历史事实纳入动态指标；但完整回滚还必须恢复原 `geo_clients.config_platforms/config_countries`，并停用本次新增的 1,440 行，否则配置/筛选集合与 active Prompt universe 不一致。
- 从迁移后的第一个完整采集日开始，启用物理 Prompt 从 7,200 降为 3,840，理论生成任务/结果基数减少约 46.7%（假设 calls/final-prompt 设置不变）。旧事实仍占存储和索引，跨越迁移日前的长日期查询仍可能扫描后再被 active join 排除，因此不能表述为“旧数据绝对零查询成本”；但它们不再继续产生增量任务、Result、Citation、Mention 或 Sentiment 数据。
- Prompt Editor 仍调用 physical `/api/prompts`，先按 `is_active` 分 Tab，再用 `client + topic + normalized text + product + canonical intent + language` 聚合；platform/country/physical UUID 不参与 UI logical key。因此新国家的新 UUID 会并入既有逻辑行，不会让 AI Video active 从 30 变 60。
- 只读投影模拟确认 AI Video 迁移后：active Tab 精确为 30 个 logical rows，每行 32 variants、4 平台、8 国家；inactive Tab 也为 30 个 logical rows，每行 40 variants。Inactive UI 展示的是独立的 platform/country union，而不是 pair matrix，因此会看到 5 个平台和原 12 国的集合（因为 Perplexity 在 12 国均停用，其他 4 平台在 7 个移除国家停用）。
- `geo_client_prompts.id` 是平台×国家物理变体 UUID；当前模型没有单独持久化的 logical Client Prompt UUID。Final Prompt 是 Collector 运行时写入 Task 的文本/Task identity，也不是本次新 UUID。迁移会更新旧 4,800 个物理 Prompt 的 `is_active`（及 `updated_at`），但不会改写其 UUID、文本、Topic、Product、Intent、Platform、Country 或 Language。
- Migration 129 最终实现不删除、不 relabel；首次 legacy 状态会保留 2,400 overlap UUID，新增 1,440 target UUID，停用 4,800 excluded UUID。完整矩阵、Topic 80/30/10、AI Creative Tools untouched、no-delete total、Global Config dependency 和 idempotent second run 均已由真实 PostgreSQL TEMP-table test 验证。
