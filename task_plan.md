# Prompt / Report / Admin P0 迭代执行状态

## 目标

严格按已确认的中英文 Spec 和 16 项 Plan 完成 F1–F8，实现后执行纯代码全量回归与独立双重审查；按用户要求，在浏览器自动化前停下汇报。

## 阶段

| 阶段 | 状态 | 内容 |
|---|---|---|
| 1. 调研、澄清与双语 Spec | complete | 原需求 16–20 已重构为 F1–F8 八个独立验收单元 |
| 2. Implementation Tasks 1–8 | complete | Migration、Intent、Sidebar、动态下钻与动态指标排序 |
| 3. Implementation Tasks 9–12 | complete | CSV 导入、Snapshot 上一周期比较与冻结列表全局排序 |
| 4. Implementation Tasks 13–15 | complete | Admin Alias、Workspace 删除后端保护与引导式清理 UI |
| 5. Task 16 最终缺口修复 | complete | PromptEditor 入口、OpenAPI 类型与新增 Dashboard 定向 lint 已完成 |
| 6. Task 16 全量回归 | complete | 871 个 Python 测试、26 个 Node 测试、两端 build/typecheck、compile 与 diff hygiene 已通过 |
| 7. Task 16 独立双重审查 | complete | 首轮发现 5 个 Important，修复后由两位未参与实现的 reviewer 复审为 Ready，0 Critical / 0 Important / 0 Minor |
| 8. 代码阶段交付 | complete | 当前汇报证据并停下；浏览器自动化须下一阶段单独确认 |
| 9. 静态报告存储方案性能复核 | complete | 已完成 Dreamina 7 天快照、Cloud Run/Cloud SQL 日志、内存排序与 JSONB 解压实测；新版方案 C（每 List Type 一个 Blob）已获确认，明确否决当前 row-per-item Migration 125 |
| 10. 新版方案 C 与报告生成性能设计 | complete | 已确认 Blob 原子持久化、分窗口聚合、事务级 work_mem、连接预算、跨实例全局并发控制；当前低频阶段明确不引入 Cloud Tasks |
| 11. 新版方案 C 与性能优化实现 | complete | TDD 改写 Migration 125、Repository/API、canonical rows 管线与查询/并发优化；未执行 DDL |
| 12. 完整回归与独立双重审查 | complete | 六模块 897 个 Python 测试、26 个 Node 测试、两端构建与静态检查通过；Scope/Security 最终均 Ready，0 Critical/Important/Minor |
| 13. 受控浏览器自动化 | complete | 已完成 Sidebar、Intent、V/C/S 下钻、指标排序、CSV Template/Allowed Values 等非 Migration 主链路验证；未操作正式客户写入 |
| 14. Migration 124–126 后写入 E2E | complete | Migration 后主链路已验证；Dreamina 30 天 v5 报告成功生成并渲染冻结 V/C/S 数据；AnswerX 写入测试全部回滚 |
| 15. Prompt 大批量导入性能与 Quota E2E | complete | 150 logical / 600 physical Preview、Quota 20→170、单条 UNNEST 集合式 INSERT、Commit 与 Undo 均通过；最终恢复 20 logical / 174 physical，E2E 残留 0 |
| 16. 静态报告末尾列表与租户授权审计 | complete | 前端报告在 Sentiment 结束；summary/section/list/export 均先按 report.client_id 服务端鉴权，未授权不返回快照 |
| 17. Citation change_pct 全局排序性能修复 | complete | Pages/Domains 改为 current+previous 单扫描 conditional aggregate；Dreamina 7 天实测分别 9.70s / 4.32s，均 200 且无高基数 period join |
| 18. 本轮定向回归与浏览器复验 | complete | 287 个后端专项、25 个 geo_common、19 个 Node、production build 与 compileall 通过；浏览器运行时末段不可用，已保留此前可见 E2E 与最终 API/DB 实测证据 |
| 19. 全列表序号列排序审计与 UI 纠偏 | complete | 序号/ID/# 全部禁排；Visibility Ranking 保持品牌矩阵；Published URL、Static Citation 和普通 V/C/S 排序均局部 loading/更新 |
| 20. 30 天报告大列表与跨实例缓存 | complete | 165,739 行 Citation Page 使用 68.35 MiB 紧凑内存缓存；另持久化 3.64 MiB 排序位置索引，热路径 1.79s、冷实例首次 8.11s、后续 2.14s；不新增 schema/表 |
| 21. Admin Scheduler 无损恢复与线上验证 | complete | 根因锁定为无关重建导致 gRPC 传输依赖漂移；v30 恢复短名原地更新、REST 稳定传输和同步确认，LensLogTest 创建/更新/Pause/NOT_FOUND Enable 全部通过，拓腾已对账，飞书通知已发送 |
| 22. AI Brainstorming Prompt 生成 is_active 回归修复 | complete | GCP 日志与真实 schema 已锁定 Topic ownership 错误；最小修复保留 Prompt active-only；AnswerX 生成→保存→回滚 E2E、580 项回归、SaaS API v68 部署与飞书汇报均完成 |
| 23. Dreamina Prompt 平台/国家配置迁移 | in_progress | 先以 Lancelot ADC 实时只读核对 client_id、当前 120 logical Prompt 展开、canonical country/platform code 与历史数据依赖；用户确认设计后才生成 migration SQL，不直接执行 |

## 独立工作流：SaaS 自定义域名迁移

| 阶段 | 状态 | 内容 |
|---|---|---|
| 1. GCP、DNS 与代码基线核对 | complete | 已确认 Cloud Run、Terraform、GoDaddy DNS、OAuth/CORS 和现有 URL |
| 2. 架构选型与平滑迁移设计 | complete | 采用 Global External Application Load Balancer + Serverless NEG + Certificate Manager DNS authorization |
| 3. 编写迁移 Spec | complete | 已写入自定义域名迁移设计文档 |
| 4. 编写完整实施与回滚 Plan | complete | 已写入 canary、正式切换、回滚、中国大陆验证、费用与验收步骤 |
| 5. 用户审阅 | in_progress | 等待用户确认方案后再进行任何 GCP、DNS 或 OAuth 变更 |
| 6. 分阶段实施 | pending | 本轮不执行 |

## 已知约束

- 用户已明确授权直接在当前 `main` 工作区实施，不创建隔离 worktree，不提交、不推送。
- 尊重 AGENTS.md 中锁定架构、租户隔离、模型管理、NL2SQL、DDL、UI 与 i18n 规则。
- 工作区存在大量用户未提交改动；不得回退、覆盖或整理无关文件。
- 数据库结构变更只提供 migration 文件，不直接执行 DDL。
- 需求可能跨 Admin、SaaS、静态报告和公共数据库模型，需要追踪端到端链路。
- 用户已授权在代码与双重审查完成后运行浏览器自动化；写入测试仅限 AnswerX Workspace 且必须回滚，绝不修改正式客户数据或执行 DDL。

## 遇到的错误

| 错误 | 尝试次数 | 处理 |
|---|---:|---|
| Visual Companion 本地服务首次启动时报 `EPERM: operation not permitted, listen 127.0.0.1:60029` | 1 | 确认为沙箱监听限制；经授权后重新启动成功，当前地址为 `http://localhost:51329` |
| 审计地图在用户侧显示黑屏；自动截图先遇到 stale tab，重连后截图能力仍返回 unavailable | 2 | 通过 DOM 与 computed style 验证内容实际已渲染；将地图改为强制浅色高对比主题并刷新页面 |
| 沙箱内执行 `ps -ef` 被系统拒绝（operation not permitted） | 1 | 以只读提权重试，确认已有旧 Proxy 在 15432；为保证使用新 ADC，另起 Lancelot 专用代理 15433 |
| 静态报告 JSON 完整性查询最初使用了 `status='ready'`，与数据库真实大写 `COMPLETED` 不一致 | 1 | 查询返回 0 后立即核对状态分布，改为 `COMPLETED` 重跑并获得 17 份真实快照结果 |
| Global Platforms 查询错误假设列名为 `platform_name` | 1 | 先读取 information_schema，确认真实列为 `platform_id` / `display_name`，修正后成功获取 5 个启用平台 |
| Snapshot 尺寸查询首次被 zsh 将 JSON path 花括号解析为 glob，第二次又对 object 调用了 array length | 2 | 改用经过验证的 SQL 转义构造，先读取 JSON shape，再按 `{prompts,ranking}` / `{topics,ranking}` 等真实 array path 重跑成功 |
| 沙箱内 `gcloud auth list` 无法写入 `~/.config/gcloud/credentials.db` | 1 | `gcloud config get-value` 已确认目标账号/项目；认证与日志查询改为按既有授权在沙箱外只读执行 |
| 浏览器运行时一度拒绝操作 `localhost:6174` | 1 | 未绕过策略；用户完成 Migration 后重新明确授权本地浏览器 E2E，本阶段重新连接现有 in-app browser |
| Migration 后切换 Workspace 时浏览器再次拒绝 `localhost:6174` | 1 | 运行时明确禁止替代浏览器、直接 API 或其他绕过；立即停止所有写入 E2E，不执行 CSV Commit 或报告 materialize |
| Migration 126 最终只读索引核验的权限审批流断开 | 1 | 自动审批明确禁止绕过或重复执行；保留已确认的 124/125 表与报告版本证据，不再重试索引查询 |
| 本地 SaaS venv 缺少 requirements 已声明的 `python-multipart`，Prompt router 测试收集失败 | 1 | 定向测试未执行到代码；补齐本地开发依赖后重跑同一测试集，不修改产品依赖清单 |
| 全量 geo_common 测试缺 `pytest-asyncio`，48 个 async 测试未被执行 | 1 | 这是测试运行环境缺口；补齐本地测试插件后全量重跑，不修改生产 requirements |
| SaaS 全量回归发现旧参数化断言不允许固定 `cp.is_active = TRUE` | 1 | 测试与已确认 active-only 设计冲突；收紧为仅用户输入条件必须参数化，并显式保护固定 active predicate，不改变生产代码 |
| 本机尝试运行 v26 镜像读取依赖时报 `docker: command not found` | 1 | 不安装新运行时、不重复；改用 Cloud Build 日志或 Registry layer 只读取证 |
| Dreamina 7 天静态报告生成超过 9 分钟 | 1 | 定位为 server-side cursor `prefetch=1` 导致数万次 Cloud SQL Proxy 往返；保留 50,000 行/16 MiB guard，将有界预取调为 512，取消的测试报告精确标记 FAILED，68 个静态报告专项测试通过 |
| 前后端定向测试误用同一个 `geo_saas/` workdir | 1 | Python 128 tests 已通过；Node/build 因 package.json 位于 `geo_saas/web` 未执行，改用正确 web workdir 单独重跑，不重复错误命令 |
