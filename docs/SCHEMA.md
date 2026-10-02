# GEO Platform — Database Schema Management

> **Single source of truth** for all database schema evolution.
> Last updated: 2026-04-25.

## 事实源层级

| 层 | 位置 | 作用 |
|---|---|---|
| 1 | `/migrations/*.sql` | **唯一真源**。所有 schema 演进（CREATE / ALTER / INDEX / DROP / seed INSERT）只写入这个目录。当前最新到 `054_v12_content_raft_defaults_all.sql`（2026-04-20）。 |
| 2 | Cloud SQL 生产实例 | 当前运行状态。实例配置见 `geo_collector/terraform/cloud_sql_manual_config.md`（当前不在 Terraform 管理下，roadmap 项）。 |

## 命名规范

```
NNN_<short_description>.sql         # 主线 migration，NNN = 3 位连续整数
NNNx_<description>.sql              # fix / hotfix（x = b/c/d...），挂在原 NNN 之后
```

例：`046_v12_metrics_templates_rewrite.sql` → 后续 hotfix `046b_v12_brand_sentiment_breakdown_fix.sql`。

## 变更流程（当前人工）

1. 写新的 migration file `migrations/NNN_xxx.sql`（NNN 递增，不跳号）。
2. 在 Cloud SQL 上手动执行 SQL（目前无自动化 runner，每次由 CTO 手动 `psql`）。
3. 把 migration file commit 进仓库。
4. 如果 schema 变更影响某个 Cloud Run service 的代码，**同批次**更新那个 service 的代码并 deploy（避免 schema 和 code 脱节）。

## ⚠️ 禁止

- **不要在 `*/terraform/*.tf` 里写 DDL**（`CREATE TABLE` / `ALTER` / `INDEX` / `TRUNCATE` / `INSERT INTO` 等全部禁止）。Terraform 管理 Cloud Run / IAM / Pub/Sub / Artifact Registry；数据库 schema 归 `/migrations/`。
- **不要手动修改 Cloud SQL schema 不经 migration file**。所有变更必须先落文件再执行，方便 review 和历史追溯。
- **不要跳号写 migration**（`053` → `055` 中间没有 `054` 不允许）。如果是 hotfix，用 `NNNb / NNNc` 挂在已有编号下。

## 历史

- **2026-04-25** — 根目录 `schema.sql` 已删除。该文件自述"包含到 migration 009"，但实际 migrations 已到 054，滞后 45 个 migration（整个 v1.2 schema 重构都不在它里面），远偏离生产现状。以后建库用 `/migrations/` 顺序回放，不再维护集成 snapshot。
- **2026-04-25** — `geo_collector/alembic/` + `alembic.ini` 已删除。三个 Alembic 迁移文件最后更新于 2026-02-07，此后所有 schema 演进改走根 `/migrations/`，Alembic 事实废弃。
- **2026-04-25** — `geo_agent/sql/` 空目录已删除。

## 新建数据库回放

```bash
export PGPASSWORD='xxx'
for f in migrations/*.sql; do
  echo "→ $(basename $f)"
  psql -h <host> -U answer-x-geo-db-user -d answer-x-geo-db -f "$f" || break
done
```

如未来需要更严谨的 migration 管理（CI 里跑、幂等检查、回滚支持），可引入 `sqitch` / `golang-migrate` / `atlas`。列入 roadmap。
