# AnswerX GEO

<p align="center">
  <img src="logo.png" alt="AnswerX Logo" width="120" />
</p>

<p align="center">
  <strong>高吞吐量 · 异步 · 事件驱动</strong><br>
  <em>Generative Engine Optimization (GEO) 数据采集与分析平台</em>
</p>

---

## 🎯 项目愿景

随着 AI 搜索引擎（ChatGPT, Gemini, Perplexity 等）逐渐成为用户获取信息的主要入口，品牌在这些平台上的"**可见性**"变得至关重要。

**AnswerX GEO** 致力于解决一个核心问题：

> *"当用户向 AI 提问时，你的品牌是否被推荐？在什么场景下被提及？竞品表现如何？"*

通过大规模采集 AI 引擎的回答数据，AnswerX GEO 帮助企业：
- 📊 **监测品牌可见性** — 追踪品牌在 AI 回答中的出现频率与位置
- 🔍 **分析竞争格局** — 对比竞品在不同场景下的表现
- 📈 **优化内容策略** — 基于数据洞察指导 SEO/GEO 优化方向

---

## 🏗️ 系统架构

```
┌────────────────────────────────────────────────────────────────────────┐
│                           GEO Admin UI                                 │
│                     (React + Google OAuth)                             │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ REST API / Trigger Analysis
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          GEO Admin API                                 │
│                     (FastAPI + Cloud SQL)                              │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ CREATE geo_requests / TRIGGER analyzer
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      GEO Collector Pipeline                            │
│   ┌────────────────┐   ┌────────────────┐   ┌────────────────────┐     │
│   │    Prompt      │   │     Cloro      │   │    Callback +      │     │
│   │    Expander    │──▶│   Dispatcher   │──▶│  Result Ingestor   │     │
│   │    (Job)       │   │   (Service)    │   │    (Services)      │     │
│   └───────┬────────┘   └───────┬────────┘   └─────────┬──────────┘     │
│           │                    │                      │                │
│           ▼                    ▼                      ▼                │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                   PostgreSQL (Cloud SQL)                       │   │
│   │ requests ──▶ tasks ──▶ results ──▶ mentions / citations        │   │
│   └───────────────────────────┬────────────────────────────────────┘   │
│                               │ READ Unanalyzed Results                │
│                               ▼                                        │
│                     ┌────────────────────┐                             │
│                     │    GEO Analyzer    │                             │
│                     │  (Cloud Run Job)   │                             │
│                     └────────────────────┘                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 💡 设计理念

### 1. ELT 优先 (Extract-Load-Transform)

```
先抓取 → 原样存储 → 后解析
```

采集阶段只负责"搬运数据"，将 AI 引擎的原始 JSON 响应完整存储。解析和分析作为独立阶段，支持后续迭代优化而无需重新采集。

### 2. 事件驱动 + 削峰填谷

```
Pub/Sub 解耦 → 异步处理 → 自动扩缩容
```

通过 Google Cloud Pub/Sub 实现组件间解耦，避免数据库过载，支持 Cloud Run 弹性伸缩。

### 3. 策略模式 (Strategy Pattern)

```
多平台适配 → 动态选择解包器 → 统一输出格式
```

针对 ChatGPT、Gemini、Perplexity 等不同平台的响应结构，采用策略模式进行 JSON 解包，新增平台只需添加新策略类。

### 4. 三层数据模型

```
Request (业务输入) → Task (调用实例) → Result (采集结果)
                1:N                1:M
```

支持 `N prompts × M calls` 的灵活配置，一次业务请求可生成多个多样化 Prompt，每个 Prompt 可发起多次采集以获取更多样本。

---

## 📦 项目结构

```
GEO_Demo/
│
├── geo_collector/          # 🔧 数据采集引擎
│   ├── src/                # 核心业务代码
│   │   ├── clients/        # 外部服务客户端 (Cloro, Gemini, Pub/Sub)
│   │   ├── services/       # 业务逻辑层
│   │   └── core/           # 配置与数据库
│   ├── terraform/          # GCP 基础设施配置
│   └── alembic/            # 数据库迁移
│
└── geo_admin/              # 🖥️ 管理后台
    ├── api/                # FastAPI 后端
    ├── web/                # React 前端 (TailwindCSS)
    └── terraform/          # Cloud Run 部署配置
```

---

## 🧩 核心组件

| 组件 | 类型 | 职责 |
|------|------|------|
| **Prompt Expander** | Cloud Run Job | 读取业务请求，调用 Gemini 生成多样化 Prompt |
| **Cloro Dispatcher** | Cloud Run Service | 将 Prompt 发送至 Cloro API，触发 AI 引擎采集 |
| **Cloro Callback** | Cloud Run Service | 接收 Cloro 异步回调，推送至 Pub/Sub |
| **Result Ingestor** | Cloud Run Service | 消费 Pub/Sub 消息，解包并入库 |
| **GEO Analyzer** | Cloud Run Job | 批处理分析引擎，提取结构化数据 |
| **GEO Admin API** | Cloud Run Service | 管理后台 REST API |
| **GEO Admin Web** | Cloud Run Service | React 可视化界面 |

---

## 🛠️ 技术栈

| 类别 | 技术选型 |
|------|----------|
| **后端语言** | Python 3.11+ |
| **Web 框架** | FastAPI |
| **前端框架** | React 18 + Vite + TailwindCSS |
| **数据库** | PostgreSQL 15+ (Google Cloud SQL) |
| **消息队列** | Google Cloud Pub/Sub |
| **AI/LLM** | Vertex AI Gemini (Prompt 生成) |
| **采集服务** | Cloro.dev API |
| **容器化** | Docker (多阶段构建) |
| **基础设施** | Terraform + Cloud Run |
| **认证** | Google OAuth 2.0 |

---

## 🚀 快速开始

### 1. GEO Collector (后端采集引擎)

```bash
cd geo_collector
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# 详细说明见 geo_collector/README.md
```

### 2. GEO Admin (管理后台)

```bash
# 启动 API
cd geo_admin/api
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 启动 Web
cd geo_admin/web
npm install && npm run dev
```

### 3. GEO Analyzer (分析引擎)

```bash
cd geo_analyzer
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# 运行分析
python main.py
```

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [geo_collector/README.md](geo_collector/README.md) | Collector 架构设计与快速开始 |
| [geo_collector/DEPLOY.md](geo_collector/DEPLOY.md) | GCP 部署完整指南 |
| [geo_admin/README.md](geo_admin/README.md) | Admin 本地开发与云端部署 |
| [geo_analyzer/README.md](geo_analyzer/README.md) | Analyzer 架构与本地运行 |

---

## ☁️ 云端部署 (GCP)

完整的一键部署脚本，构建所有镜像并通过 Terraform 部署到 Cloud Run：

```bash
# ======================================================
# GEO Demo - 完整部署脚本
# ======================================================

# 设置环境变量
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"

# 版本号 (每次发布时更新这里)
export COLLECTOR_VERSION="v7"
export ADMIN_API_VERSION="v7"
export ADMIN_WEB_VERSION="v11"
export ANALYZER_VERSION="v5"

# 确保 GCP 配置正确
gcloud config set project $PROJECT_ID
gcloud auth application-default set-quota-project $PROJECT_ID

# ------------------------------------------------------
# 1. 构建 GEO Collector 后端镜像
# ------------------------------------------------------
cd /path/to/GEO_Demo/geo_collector

gcloud builds submit \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:$COLLECTOR_VERSION .

# ------------------------------------------------------
# 2. 部署 GEO Collector (Terraform)
# 注意: 需先更新 terraform.tfvars 中的 image_tag
# ------------------------------------------------------
cd terraform
terraform init
terraform plan    # 先预览变更
terraform apply   # 确认后执行

# ------------------------------------------------------
# 3. 构建 GEO Admin API 镜像
# ------------------------------------------------------
cd /path/to/GEO_Demo/geo_admin

gcloud builds submit ./api \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/geo-admin-repo/geo-admin-api:$ADMIN_API_VERSION

# ------------------------------------------------------
# 4. 构建 GEO Admin Web 镜像
# ------------------------------------------------------
gcloud builds submit ./web \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/geo-admin-repo/geo-admin-web:$ADMIN_WEB_VERSION

# ------------------------------------------------------
# 5. 部署 GEO Admin (Terraform)
# 注意: 需先更新 terraform.tfvars 中的 api_image_tag 和 web_image_tag
# ------------------------------------------------------
cd terraform
terraform init
terraform plan    # 先预览变更
terraform apply   # 确认后执行

# ------------------------------------------------------
# 6. 构建 GEO Analyzer 镜像 (新模块)
# ------------------------------------------------------
cd /path/to/GEO_Demo/geo_analyzer

gcloud builds submit \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/geo-analyzer-repo/geo-analyzer:$ANALYZER_VERSION .

# ------------------------------------------------------
# 7. 部署 GEO Analyzer (Terraform)
# 注意: 需先更新 terraform.tfvars 中的 image_tag
# ------------------------------------------------------
cd terraform
terraform init
terraform plan    # 先预览变更
terraform apply   # 确认后执行

# ======================================================
# 完成！查看部署状态
# ======================================================
gcloud run services list --filter="geo-" --format="table(name,region,status)"
gcloud run jobs list --filter="geo-" --format="table(name,region,status)"
```

> **注意**: 
> - 部署前需先配置 `terraform.tfvars` 文件（参考 `terraform.tfvars.example`）
> - 首次部署需要先创建 Artifact Registry 仓库
> - 详细说明见 [geo_collector/DEPLOY.md](geo_collector/DEPLOY.md)

---

## 📄 License

Private / Internal Use Only

---

<p align="center">
  <em>最后更新: 2026-02-08</em>
</p>

