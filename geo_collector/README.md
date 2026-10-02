# GEO Collector

GEO Collector 是一个高吞吐量、异步、基于事件驱动的 GEO (Generative Engine Optimization) 数据采集引擎。它负责从各大 AI 搜索引擎（如 ChatGPT, Gemini, Perplexity）采集数据并持久化存储。

> **当前版本**: v27 (2026-03-08)

## 🚀 快速开始 (Quick Start)

### 1. 环境准备

确保您的系统已安装 Python 3.11+。

```bash
cd geo_collector
python3 -m venv venv && source venv/bin/activate
pip install --no-cache-dir -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下关键信息：
*   `CLORO_API_KEY`: 您的 Cloro.dev API Key
*   `DATABASE_URL`: PostgreSQL 连接字符串
*   `PUBSUB_PROJECT_ID`: GCP 项目 ID
*   `GCP_PROJECT_ID`: GCP 项目 ID (用于 Vertex AI)

### 3. 运行测试

```bash
pip install pytest pytest-asyncio
pytest tests/
```

---

## 🏗️ 系统架构 (V2 SaaS)

### 核心设计原则

| 原则 | 描述 |
|------|------|
| **ELT 架构** | 先抓取、原样存储、后解析。Collector 只负责搬运数据，严禁在抓取阶段解析深层字段 |
| **策略模式** | 针对多平台特性，动态选择 API Endpoint 和 JSON 解包器，不硬编码 |
| **异步与削峰** | 发送端使用 asyncio 高并发，接收端采用 Pub/Sub 解耦，防止数据库过载 |
| **无服务器优先** | 完全适配 Cloud Run + Cloud SQL，实现自动扩缩容和按需计费 |

### 数据模型 (V2 SaaS)

```
geo_clients (租户)
  └── geo_client_topics (Topic 分组)
        └── geo_client_prompts (Prompt Editor 池)
              └── geo_tasks (Query Fanout 扩展)
                    └── geo_results (多次 API 调用结果)
```

### 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GEO Collector Pipeline                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────┐     ┌───────────────────────┐   ┌──────────────┐             │
│   │ SaaS Web │────▶│ geo_client_prompts    │   │   Gemini AI  │             │
│   │  (UI)    │     │ (Prompt Editor 池)    │   │  (Prompt Gen)│             │
│   └──────────┘     └───────┬───────────────┘   └──────┬───────┘             │
│                            │                          │                     │
│                            ▼                          ▼                     │
│                    ┌───────────────────────────────────────┐                │
│                    │        Prompt Expander (Job)          │                │
│                    │  1. Read active client_prompts        │                │
│                    │  2. Generate N query fanouts via LLM  │                │
│                    │  3. Create N geo_tasks                │                │
│                    └───────────────┬───────────────────────┘                │
│                                    │                                        │
│                                    ▼                                        │
│                    ┌───────────────────────────────────────┐                │
│                    │        Cloro Dispatcher (Job)         │                │
│                    │  1. Read PENDING tasks                │                │
│                    │  2. Call Cloro API × M times          │                │
│                    │  3. Update task status                │                │
│                    └───────────────┬───────────────────────┘                │
│                                    │                                        │
│                                    ▼                                        │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │                         Cloro.dev API                              │    │
│   │ chatgpt │ gemini │ aimode │ perplexity │ google+aioverview       │    │
│   └────────────────────────────────┬───────────────────────────────────┘    │
│                                    │ Webhook Callback                       │
│                                    ▼                                        │
│                    ┌───────────────────────────────────────┐                │
│                    │      Cloro Callback (Service)         │                │
│                    │  1. Receive JSON payload              │                │
│                    │  2. Publish to Pub/Sub                │                │
│                    └───────────────┬───────────────────────┘                │
│                                    │                                        │
│                                    ▼                                        │
│                    ┌───────────────────────────────────────┐                │
│                    │            Cloud Pub/Sub              │                │
│                    │        Topic: geo-raw-responses       │                │
│                    └───────────────┬───────────────────────┘                │
│                                    │ Push Subscription                      │
│                                    ▼                                        │
│                    ┌───────────────────────────────────────┐                │
│                    │       Result Ingestor (Service)       │                │
│                    │  1. Consume Pub/Sub messages          │                │
│                    │  2. UnpackerFactory 提取结构化字段    │                │
│                    │  3. INSERT into geo_results           │                │
│                    │  4. UPDATE task completed_count       │                │
│                    └───────────────────────────────────────┘                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 运行流程详解

1.  **业务输入**: 用户在 SaaS 前端的 Prompt Editor 中配置 Topic、Product 和 Prompt 供采集。
2.  **Prompt 扩展**: `expander.py` 读取活跃的 `geo_client_prompts`，调用 Gemini 扩写成多样化 Query Fanout，写入 `geo_tasks`。
3.  **任务分发**: `cloro_dispatcher.py` 读取待执行任务，根据 `calls_per_prompt` 调用 Cloro API 进行采集。
4.  **回调接收**: `cloro_callback.py` 接收 Cloro 的异步 webhook 回调，推送到 Pub/Sub。
5.  **数据入库**: `result_ingestor.py` 消费 Pub/Sub 消息，利用 `UnpackerFactory` 解析原始 JSON，存入 `geo_results` 表。

---

## 📂 代码结构

```
geo_collector/
├── Dockerfile                  # 多阶段构建
├── requirements.txt            # Python 依赖
├── alembic/                    # 数据库迁移
├── terraform/                  # GCP 基础设施配置
├── tests/                      # 单元测试
├── src/
│   ├── core/                   # 配置与数据库
│   │   ├── config.py           # Settings (inherits from geo_common.config.BaseConfig)
│   │   └── database.py         # asyncpg pool lifecycle (uses geo_common.db.create_asyncpg_pool)
│   ├── clients/                # 外部服务客户端
│   │   ├── cloro.py            # Cloro API 客户端
│   │   ├── gemini.py           # Vertex AI Gemini 客户端
│   │   └── pubsub.py           # Cloud Pub/Sub 客户端
│   ├── services/
│   │   ├── prompt_expander.py  # Prompt 扩展核心逻辑
│   │   └── unpackers/          # 解包器模块 (策略模式)
│   │       ├── factory.py      # UnpackerFactory
│   │       ├── base.py         # 基类
│   │       ├── chatgpt.py      # ChatGPT 解包器
│   │       ├── gemini.py       # Gemini 解包器
│   │       ├── aimode.py       # AI Mode 解包器
│   │       ├── perplexity.py   # Perplexity 解包器
│   │       └── aioverview.py   # Google AI Overview 解包器
│   ├── expander.py             # [Job] Prompt Expander 入口
│   ├── cloro_dispatcher.py     # [Job] Cloro Dispatcher 入口
│   ├── cloro_callback.py       # [Service] Webhook 接收器
│   └── result_ingestor.py      # [Service] 结果入库 Worker
```

---

## 🔍 日志格式

所有模块使用结构化日志格式，便于 Cloud Logging 搜索：

| 模块 | 日志标签 | 示例 |
|------|----------|------|
| `expander.py` | `[EXPANDER-S0~S3]` | `[EXPANDER-S1] 找到 5 条待扩展的 prompts` |
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
cd terraform && terraform init && terraform apply
```

---
*Last Updated: 2026-03-08*
