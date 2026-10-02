# 本地开发:端口隔离 + 环境切换

> 历史说明：本文档记录的是 Claude Code 迁移前使用的隔离端口方案。Codex 可视化 E2E 测试请优先参考 [docs/local-dev/codex-visible-e2e.md](codex-visible-e2e.md)，当前推荐端口为 SaaS API `9101`、Agent API `9102`、Admin UI `6173`, SaaS UI `6174`。

> 两种本地开发模式共存:**用户手动起服务**(默认端口)和 **Claude 自动化测试起服务**(+1000 offset 端口)。
> 同一台机器可以同时跑两套,互不干扰。

## 端口映射总览

| 服务 | 用户默认 | Claude 隔离 | 差 |
|---|---|---|---|
| Postgres DB | **5432** (via Cloud SQL Auth Proxy) | **5433** (本地 pg18) | +1 |
| geo_admin/src | 8000 | **9000** | +1000 |
| geo_saas/src | 8001 | **9001** | +1000 |
| geo_agent/src | 8002 | **9002** | +1000 |
| geo_saas/web | 5173 | **6173** | +1000 |
| geo_admin/web | 5174 | **6174** | +1000 |

## 配置文件矩阵

每个模块都有对称的两个 env 文件:

| 模块 | 用户文件 | Claude 文件 |
|---|---|---|
| `geo_saas/src/` | `.env.local` | `.env.claude.local` |
| `geo_admin/src/` | `.env.local` | `.env.claude.local` |
| `geo_agent/src/` | `.env.local` | `.env.claude.local` |
| `geo_analyzer/` | `.env.local` | `.env.claude.local` |
| `geo_saas/web/` | `.env.local` | `.env.claude.local` |
| `geo_admin/web/` | `.env.local` | `.env.claude.local` |

全部 git-ignored(符合现有 `.gitignore` 规则 `.env.local` / `.env.local.*`)。

## 用户如何切换数据库(Cloud SQL vs 本地)

**只需改一个文件的一行**。以 `geo_saas/src/.env.local` 为例:

```bash
# [默认] Cloud SQL via Auth Proxy (5432)
DATABASE_URL=postgresql+asyncpg://.../localhost:5432/answer-x-geo-db

# [切换] 本地 Postgres (5433)
# DATABASE_URL=postgresql+asyncpg://.../localhost:5433/answer-x-geo-db
```

把上面那行注释掉,打开下面那行即可。所有 api 模块都是同构切换。

`geo_analyzer` 是改 `DB_PORT=5432 ↔ 5433`。

**切换数据库时记得重启对应服务**(env 变量在进程启动时读取)。

## 用户启动命令(默认端口)

```bash
# 一个终端一个服务,保持可见日志

# --- 0. Cloud SQL Auth Proxy(连 Cloud SQL 时必需,所有后端服务依赖它监听 5432)---
cd ~
./cloud-sql-proxy project-90d7849c-de16-4c15-a0a:us-central1:answer-x-geo-instance --port=5432

# 如果用本地 PG 而不是 Cloud SQL,跳过这一步,参见下面 "本地 Postgres 管理"

# --- 后端 ---
cd geo_saas/src    && uvicorn main:app --reload --port 8001 --env-file .env.local
cd geo_admin/src   && uvicorn main:app --reload --port 8000 --env-file .env.local
cd geo_agent/src   && uvicorn main:app --reload --port 8002 --env-file .env.local

# --- 前端 ---
cd geo_saas/web    && npm run dev          # 5173
cd geo_admin/web   && npm run dev          # 5174

# --- Analyzer(批处理 Job,按需运行)---
cd geo_analyzer
set -a; source .env.local; set +a
CLIENT_ID=<uuid> python main.py
```

## Claude 启动命令(隔离 +1000 端口)

```bash
# --- 后端 ---
cd geo_saas/src    && uvicorn main:app --reload --port 9001 --env-file .env.claude.local
cd geo_admin/src   && uvicorn main:app --reload --port 9000 --env-file .env.claude.local
cd geo_agent/src   && uvicorn main:app --reload --port 9002 --env-file .env.claude.local

# --- 前端(Vite --mode 读对应 env 文件)---
cd geo_saas/web    && npm run dev -- --mode claude    # 6173
cd geo_admin/web   && npm run dev -- --mode claude    # 6174

# --- Analyzer ---
cd geo_analyzer
set -a; source .env.claude.local; set +a
CLIENT_ID=<uuid> python main.py
```

## 本地 Postgres 管理(Claude 测试数据库)

首次搭建已完成(见 Phase 2 进度文档)。常用操作:

```bash
# 状态
PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH" pg_isready -h localhost -p 5433

# 启动 / 停止
PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH" pg_ctl -D /opt/homebrew/var/postgresql@18 -o "-p 5433" -l /tmp/geo_local_pg18.log start
PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH" pg_ctl -D /opt/homebrew/var/postgresql@18 stop -m fast

# 连接(凭证和 prod 一致,方便切换无感)
PGPASSWORD='answer-x-geo-db-user-123' \
  psql -h localhost -p 5433 -U "answer-x-geo-db-user" -d "answer-x-geo-db"
```

## 重置本地 test 数据库(dev 迭代用)

如果迭代过程中想回到干净的 prod snapshot + migrations 起点:

```bash
# 1. Drop + re-create
export PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH"
psql -p 5433 -d postgres -c 'DROP DATABASE "answer-x-geo-db";'
psql -p 5433 -d postgres -c 'CREATE DATABASE "answer-x-geo-db" OWNER "answer-x-geo-db-user";'

# 2. Re-dump prod + restore(Cloud SQL Auth Proxy 需在 5432 跑着)
PGPASSWORD='answer-x-geo-db-user-123' pg_dump \
  -h localhost -p 5432 -U answer-x-geo-db-user -d answer-x-geo-db \
  --format=custom --no-owner --no-acl --file=/tmp/geo_prod_dump.pgcustom

PGPASSWORD='answer-x-geo-db-user-123' pg_restore \
  -h localhost -p 5433 -U answer-x-geo-db-user -d answer-x-geo-db \
  --no-owner --no-acl /tmp/geo_prod_dump.pgcustom

# 3. Apply migrations in order
for f in 040_v12_new_tables 041_v12_extend_existing 042_v12_rename_mentions \
         043_v12_data_migration 044_v12_drop_legacy 045_v12_truncate_agent_state \
         046_v12_metrics_templates_rewrite 046b_v12_brand_sentiment_breakdown_fix \
         047_v12_url_trigger_regex_hardening; do
  PGPASSWORD='answer-x-geo-db-user-123' psql -h localhost -p 5433 \
    -U answer-x-geo-db-user -d answer-x-geo-db \
    -v ON_ERROR_STOP=1 \
    -f "migrations/$f.sql"
done
```

## 端口冲突排查

```bash
# 查端口占用
lsof -iTCP:5432 -sTCP:LISTEN       # Cloud SQL Auth Proxy
lsof -iTCP:5433 -sTCP:LISTEN       # 本地 pg18
lsof -iTCP:8001 -sTCP:LISTEN       # 用户 saas api
lsof -iTCP:9001 -sTCP:LISTEN       # Claude saas api
```

## CORS 提示

- 用户后端的 `ALLOWED_ORIGINS` 含 5173/5174(用户前端)
- Claude 后端的 `ALLOWED_ORIGINS` 含 6173/6174(Claude 前端)
- 前端必须连**同级**的后端:用户前端 5173 → 用户后端 8001;Claude 前端 6173 → Claude 后端 9001
- 跨级连接会因为 CORS 被拒,这是 feature 不是 bug
