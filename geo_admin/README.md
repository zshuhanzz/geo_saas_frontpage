# GEO Admin

GEO Admin 是内部管理后台，提供客户管理、全局配置、定时任务调度、数据分析管理等功能。

> **当前版本**: API v35 / Web v50 (2026-03-08) — v1.2 OEM/ODM 适配后即将发布 v36 / v51

## 🔀 v1.2 Dual-Mode Tracking (OEM/ODM 适配)

Admin 侧 v1.2 增量:

### 客户配置
- **Clients 页**新增第 3 列 Scheduler: **LLM Discovery**（与 Collector / Analyzer 并列），控制 `geo_clients.cron_llm_discovery`（migration 049）。
- `POST /api/clients/{id}/jobs/llm_discovery/run` — 手动触发 LLM Batch Discovery Cloud Run Job。
- **APP_ENV=local 安全阀**: 本地跑时 job trigger 返 stub 不触发 prod Cloud Run Job（避免 prod blast radius）。生产 Cloud Run 必须 *不设* `APP_ENV` 或设 `production`。

### Brand / Peer / Product / URL CRUD
- 新增 Admin Brand/Peer/Product/Tracked URL 管理 UI（对应 `geo_client_brands` / `geo_client_peers` / `geo_client_topic_products` / `geo_product_tracked_urls`）。
- 支持 shadow_sub_role 配置（`native` / `resale` / NULL）。

### v1.2 入口表管理
- Analysis Metrics 页（对应 `geo_analysis_metrics` NL2SQL 字典）
- Brand Profiles 页（对应 `geo_brand_profiles`，给 Agent 注入系统 prompt 的 tonality / positioning 数据）

详细设计见 [docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md](../docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md)。

## 📂 目录结构

```
geo_admin/
├── api/                # FastAPI 后端
│   ├── main.py         # 入口 & 路由注册
│   ├── database.py     # 数据库连接 & ORM 模型
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── routers/        # API 路由模块
│   │   ├── clients.py       # 客户管理 (CRUD + Cloud Scheduler 联动)
│   │   ├── prompts.py       # Prompt 管理 (列表/状态/详情)
│   │   ├── tasks.py         # Task 管理 (列表/结果/统计)
│   │   ├── stats.py         # 概览统计面板
│   │   ├── analysis.py      # 分析结果查看 (Mentions/Citations)
│   │   ├── brainstorming.py # (已废弃 deprecated - 详见代码注释，SaaS 版替代)
│   │   ├── global_configs.py# 全局平台/Intent 配置
│   │   ├── languages.py     # 全局语言管理 (CRUD)
│   │   └── jobs.py          # Cloud Run Job 触发 (Expander/Dispatcher/Analyzer)
│   └── services/
│       └── gcp_scheduler.py # Cloud Scheduler 同步工具
├── web/                # React 前端
│   └── src/pages/      # 页面组件
├── terraform/          # Cloud Run 部署配置
│   ├── main.tf
│   └── terraform.tfvars
└── README.md
```

---

## 🚀 本地开发

### 前置条件

- Python 3.12+
- Node.js 18+
- Cloud SQL Proxy 运行中 (连接 localhost:5432)

### 1. 配置环境变量

```bash
# 编辑 web/.env，填入 Google OAuth Client ID
cd geo_admin/web
# 文件内容: VITE_GOOGLE_CLIENT_ID=你的CLIENT_ID
```

### 2. 启动 API 后端

```bash
cd geo_admin/src
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API 运行在: http://localhost:8000

### 3. 启动 Web 前端

```bash
cd geo_admin/web
npm install && npm run dev
```

前端运行在: http://localhost:5173

---

## 🔐 用户认证（Google OAuth + Admin Session）

### GCP 配置

1. 打开 [GCP Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. **Create Credentials** → **OAuth client ID** → **Web application**
3. 添加 Authorized JavaScript origins:
   - `https://geo-admin-web-xxx.us-central1.run.app`
   - `http://localhost:5174`
4. 复制 Client ID

### 环境变量配置

| 文件 | 用途 |
|------|------|
| `web/.env` | 本地开发 |
| `terraform/terraform.tfvars` | 生产构建 |

Google credential 只在 `POST /api/auth/session` 登录交换时由后端验证一次。
登录用户还必须在 `geo_admin_user_access` 中拥有有效 Admin 权限。验证成功后，
后端签发独立的 `answerx_admin_session` HttpOnly Cookie，有效期 12 小时；
前端不保存 Google token，SaaS Cookie 也不能用于 Admin API。

用户注销、过期、停用或撤销 Admin 权限时，会话会结束并通过现有异步
User Audit 队列记录生命周期事件。

---

## 📡 API 端点

### 客户管理
| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/clients` | 客户列表 |
| POST | `/api/clients` | 创建客户 |
| PUT | `/api/clients/{id}` | 更新客户 |
| DELETE | `/api/clients/{id}` | 删除客户 |

### Prompt & Task 管理
| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/prompts` | Prompt 列表 (分页/筛选) |
| GET | `/api/prompts/quota-status` | Prompt 配额状态 |
| GET | `/api/tasks` | Task 列表 (分页/筛选/排序) |
| GET | `/api/tasks/{id}/results` | 结果详情 |

#### Tasks 列表增强字段

Tasks 页面提供全面的任务监控能力，返回以下关键字段：

| 字段 | 说明 |
|------|------|
| `task_id` | 任务唯一标识 (冻结在最左列) |
| `batch_id` | 批次 ID |
| `topic` | 所属 Topic |
| `prompt` | 关联 Prompt 文本 |
| `intent` | Intent 类型 |
| `platform` | 采集平台 |
| `country` | 国家 |
| `language` | 语言 |
| `status` | 任务状态 (PENDING/DISPATCHED/COMPLETED/ERROR) |
| `result_count` | 结果数量 |
| `dispatched_at` | 分发时间 |
| `completed_at` | 完成时间 |
| `error_message` | 错误信息 |
| `actions` | 操作按钮 (冻结在最右列) |

**UI 特性**:
- 支持所有字段的**服务端升序/降序排序** (`sort_by` + `sort_order` 参数)
- `task_id` 冻结在最左列，`actions` 冻结在最右列 (背景不透明)
- 表格支持水平滚动，每列保留充足宽度
- 对齐商业级 SaaS UI 样式

### 数据分析
| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/stats` | 概览统计 |
| GET | `/api/analysis/mentions` | 公司提及分析列表 |
| GET | `/api/analysis/citations` | 引用来源分析列表 |

### 全局配置
| Method | Path | 说明 |
|--------|------|------|
| GET/POST | `/api/global-platforms` | 全局平台管理 |
| GET/POST | `/api/global-intents` | 全局 Intent 管理 |
| GET/POST/PUT/DELETE | `/api/languages` | 全局语言管理 |

### Job 触发 & 调度
| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/jobs/expander` | 触发 Prompt Expander Job |
| POST | `/api/jobs/dispatcher` | 触发 Cloro Dispatcher Job |
| POST | `/api/jobs/analyzer` | 触发 Analyzer Job |
| ~~POST~~ | ~~`/api/brainstorming/generate`~~ | ~~AI 概念头脑风暴~~ (已废弃 deprecated - 详见代码注释，SaaS 版替代) |

---

## ☁️ 云端部署 (Cloud Run)

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"

# 构建 API 镜像
gcloud builds submit ./api \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/geo-admin-repo/geo-admin-api:v35

# 构建 Web 镜像
gcloud builds submit ./web \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/geo-admin-repo/geo-admin-web:v50

# Terraform 部署
cd terraform && terraform init && terraform apply
```

---
*Last Updated: 2026-03-08*
