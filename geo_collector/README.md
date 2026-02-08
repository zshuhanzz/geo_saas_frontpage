# GEO Collector

GEO Collector 是一个高吞吐量、异步、基于事件驱动的 GEO (Generative Engine Optimization) 数据采集引擎。它负责从各大 AI 搜索引擎（如 ChatGPT, Gemini, Perplexity）采集数据并持久化存储。

## 🚀 快速开始 (Quick Start)

### 1. 环境准备

确保您的系统已安装 Python 3.11+。

```bash
# 进入项目目录
cd geo_collector

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
# macOS / Linux:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# 安装依赖
pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 配置环境变量

复制示例配置文件并填入您的真实信息：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下关键信息：
*   `CLORO_API_KEY`: 您的 Cloro.dev API Key
*   `DATABASE_URL`: PostgreSQL 连接字符串
*   `PUBSUB_PROJECT_ID`: GCP 项目 ID
*   `GCP_PROJECT_ID`: GCP 项目 ID (用于 Vertex AI)

### 3. 本地调试 (Cloro Client)

在不依赖数据库和 Webhook 的情况下，测试 Cloro API 的连通性：

```bash
# 确保已设置 CLORO_API_KEY
export CLORO_API_KEY="your_real_key"

# 运行调试脚本 (使用同步模式)
python debug_cloro.py
```

### 4. 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行单元测试
pytest tests/
```

---

## 🏗️ 系统架构 (System Architecture)

### 核心设计原则

| 原则 | 描述 |
|------|------|
| **ELT 架构** | 先抓取、原样存储、后解析。Collector 只负责搬运数据，严禁在抓取阶段解析深层字段 |
| **策略模式** | 针对多平台特性，动态选择 API Endpoint 和 JSON 解包器，不硬编码 |
| **异步与削峰** | 发送端使用 asyncio 高并发，接收端采用 Pub/Sub 解耦，防止数据库过载 |
| **无服务器优先** | 完全适配 Cloud Run + Cloud SQL，实现自动扩缩容和按需计费 |
| **三层数据模型** | Request → Task → Result 层级关系，支持 N prompts × M calls 的灵活配置 |

### 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GEO Collector Pipeline                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────┐     ┌───────────────┐     ┌──────────────┐                   │
│   │ geo_admin│────▶│  geo_requests │     │   Gemini AI  │                   │
│   │  (UI)    │     │   (PENDING)   │     │  (Prompt Gen)│                   │
│   └──────────┘     └───────┬───────┘     └──────┬───────┘                   │
│                            │                     │                          │
│                            ▼                     ▼                          │
│                    ┌───────────────────────────────────┐                    │
│                    │      Prompt Expander (Job)        │                    │
│                    │  1. Read PENDING requests         │                    │
│                    │  2. Generate N prompts via LLM    │                    │
│                    │  3. Create N geo_tasks            │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                        │
│                                    ▼                                        │
│                    ┌───────────────────────────────────┐                    │
│                    │      Cloro Dispatcher (Job)       │                    │
│                    │  1. Read PENDING tasks            │                    │
│                    │  2. Call Cloro API × M times      │                    │
│                    │  3. Update task status            │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                        │
│                                    ▼                                        │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │                         Cloro.dev API                              │    │
│   │  /v1/monitor/chatgpt  │  /v1/monitor/gemini  │  /v1/monitor/aimode │    │
│   └────────────────────────────────┬───────────────────────────────────┘    │
│                                    │ Webhook Callback                       │
│                                    ▼                                        │
│                    ┌───────────────────────────────────┐                    │
│                    │    Cloro Callback (Service)       │                    │
│                    │  1. Receive JSON payload          │                    │
│                    │  2. Query task metadata           │                    │
│                    │  3. Publish to Pub/Sub            │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                        │
│                                    ▼                                        │
│                    ┌───────────────────────────────────┐                    │
│                    │        Cloud Pub/Sub              │                    │
│                    │    Topic: geo-raw-responses       │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │ Push Subscription                      │
│                                    ▼                                        │
│                    ┌───────────────────────────────────┐                    │
│                    │     Result Ingestor (Service)     │                    │
│                    │  1. Consume Pub/Sub messages      │                    │
│                    │  2. Unpack JSON (Strategy)        │                    │
│                    │  3. INSERT into geo_results       │                    │
│                    │  4. UPDATE task completed_count   │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                        │
│                                    ▼                                        │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │                        PostgreSQL (Cloud SQL)                      │    │
│   │  geo_requests  ──1:N──▶  geo_tasks  ──1:M──▶  geo_results          │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 运行流程详解

1.  **业务输入 (Request Creation)**: 用户在 Admin 后台创建请求，定义产品、平台、国家等参数。
2.  **Prompt 扩展 (Prompt Expansion)**: `expander.py` (Job) 读取请求，调用 Gemini 生成多样化 Prompt，写入 `geo_tasks`。
3.  **任务分发 (Task Dispatch)**: `cloro_dispatcher.py` (Job) 读取任务，调用 Cloro API 进行采集。
4.  **回调接收 (Webhook Callback)**: `cloro_callback.py` (Service) 接收 Cloro 的异步 webhook 回调，推送到 Pub/Sub。
5.  **数据入库 (Result Ingestion)**: `result_ingestor.py` (Service) 消费 Pub/Sub 消息，解包 JSON 并存入 `geo_results` 表。

---

## 💾 数据库 Schema

### 三层数据模型

```
geo_requests (业务输入层) 1:N geo_tasks (调用实例层) 1:M geo_results (结果层)
```

### 表结构定义

#### 1. geo_requests (业务输入)
| 列名 | 类型 | 说明 |
|------|------|------|
| `request_id` | UUID (PK) | 主键 |
| `client_name` | VARCHAR | 客户名称 |
| `product` | VARCHAR | 产品名称 |
| `platform` | VARCHAR | 平台 (chatgpt/gemini/aimode) |
| `country` | VARCHAR | 国家代码 |
| `prompts_per_request` | INT | 生成 Prompt 数量 (N) |
| `calls_per_prompt` | INT | 每 Prompt 调用次数 (M) |
| `status` | VARCHAR | PENDING → EXPANDED → COMPLETED |

#### 2. geo_tasks (调用实例)
| 列名 | 类型 | 说明 |
|------|------|------|
| `task_id` | UUID (PK) | 主键，也是 idempotencyKey |
| `request_id` | UUID (FK) | 关联 geo_requests |
| `prompt_text` | TEXT | Gemini 生成的 Prompt |
| `calls_per_prompt` | INT | 该 task 的调用次数 (M) |
| `completed_count` | INT | 已完成次数 |
| `status` | VARCHAR | PENDING → DISPATCHING → COMPLETED |

#### 3. geo_results (结果层 - 宽表)
| 列名 | 类型 | 说明 |
|------|------|------|
| `result_id` | SERIAL (PK) | 主键 |
| `task_id` | UUID (FK) | 关联 geo_tasks |
| `call_index` | INT | 调用序号 (1~M) |
| `text` | TEXT | AI 回答文本 |
| `sources` | JSONB | 引用源列表 |
| `shopping_cards` | JSONB | 购物卡片 |
| `cloro_response` | JSONB | 原始完整 JSON |

---

## 📂 代码结构

```
geo_collector/
├── Dockerfile                  # 多阶段构建
├── requirements.txt            # Python 依赖
├── alembic/                    # 数据库迁移
├── terraform/                  # 基础设施配置
├── src/
│   ├── core/                   # 配置与数据库
│   ├── clients/                # 外部服务客户端 (Cloro, Gemini, Pub/Sub)
│   ├── services/
│   │   └── unpackers/          # 解包器模块 (策略模式)
│   ├── expander.py             # [Job] Prompt Expander
│   ├── cloro_dispatcher.py     # [Job] Cloro Dispatcher
│   ├── cloro_callback.py       # [Service] Webhook 接收器
│   └── result_ingestor.py      # [Service] 结果入库 Worker
```

---

## 🔍 日志格式

所有模块使用结构化日志格式，便于 Cloud Logging 搜索：

| 模块 | 日志标签 | 示例 |
|------|----------|------|
| `expander.py` | `[EXPANDER-S0~S3]` | `[EXPANDER-S1] 找到 5 条待扩展的 requests` |
| `prompt_expander.py` | `[EXPAND-S1~S6]` | `[EXPAND-S3] Gemini 生成完成 \| prompts=20` |
| `cloro_dispatcher.py` | `[DISPATCHER-S0~S5]` | `[DISPATCHER-S4] Cloro 调用成功 \| call=1/3` |
| `cloro_callback.py` | `[CALLBACK-S0~S3]` | `[CALLBACK-S2] 元数据已加载 \| task_id=xxx` |
| `result_ingestor.py` | `[INGESTOR-S0~S6]` | `[INGESTOR-S4] geo_results 写入成功` |

---

## ☁️ 部署 (Deployment)

详细部署指南请参考项目根目录的 README.md 或 [DEPLOY.md](DEPLOY.md)。

```bash
# Docker 构建
docker build -t geo-collector .

# Terraform 部署
cd terraform
terraform apply
```

---
*Last Updated: 2026-02-09*
