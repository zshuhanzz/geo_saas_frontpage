# GEO Collector：技术设计文档 (v3.0)

**文档状态**: Final  
**适用场景**: AI 辅助开发 (Gemini Code Assistant / Cursor)  
**最后更新**: 2026-02-07

---

## 1. 项目概述 (Project Overview)

### 1.1 项目定义

GEO Collector 是一个高吞吐量、异步、事件驱动的 **GEO (Generative Engine Optimization) 数据采集基础设施**。

**核心能力**：
- 通过 Cloro.dev API 大规模并发采集 AI 搜索引擎（ChatGPT, Gemini, AI Mode）的回答数据
- 基于业务输入自动生成多样化 Prompt（Prompt Expansion）
- 将原始响应持久化存储，同时解包为结构化字段供 BI 分析

### 1.2 核心设计原则

| 原则 | 描述 |
|------|------|
| **ELT 架构** | 先抓取、原样存储、后解析。Collector 只负责搬运数据，严禁在抓取阶段解析深层字段 |
| **策略模式** | 针对多平台特性，动态选择 API Endpoint 和 JSON 解包器，不硬编码 |
| **异步与削峰** | 发送端使用 asyncio 高并发，接收端采用 Pub/Sub 解耦，防止数据库过载 |
| **无服务器优先** | 完全适配 Cloud Run + Cloud SQL，实现自动扩缩容和按需计费 |
| **三层数据模型** | Request → Task → Result 层级关系，支持 N prompts × M calls 的灵活配置 |

---

## 2. 技术栈约束 (Strict Tech Stack)

生成代码时必须严格遵守以下选型：

| 类别 | 技术 |
|------|------|
| **编程语言** | Python 3.11+ |
| **Web 框架** | FastAPI |
| **HTTP 客户端** | httpx (必须使用 AsyncClient) |
| **数据库** | PostgreSQL 15+ (Cloud SQL) |
| **数据库驱动** | asyncpg + databases 库 |
| **数据层** | SQLAlchemy Core 2.0+ (不使用 ORM Session) |
| **消息队列** | Google Cloud Pub/Sub |
| **LLM 客户端** | google-genai (Vertex AI Gemini) |
| **配置管理** | pydantic-settings |
| **容器化** | Docker (多阶段构建) |
| **IaC** | Terraform |

---

## 3. 系统架构 (System Architecture)

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GEO Collector Pipeline                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────┐     ┌───────────────┐     ┌──────────────┐                   │
│   │ geo_admin│────▶│  geo_requests │     │   Gemini AI  │                   │
│   │  (UI)    │     │   (PENDING)   │     │  (Prompt Gen)│                   │
│   └──────────┘     └───────┬───────┘     └──────┬───────┘                   │
│                            │                     │                           │
│                            ▼                     ▼                           │
│                    ┌───────────────────────────────────┐                    │
│                    │      Prompt Expander (Job)        │                    │
│                    │  1. Read PENDING requests         │                    │
│                    │  2. Generate N prompts via LLM    │                    │
│                    │  3. Create N geo_tasks            │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                         │
│                                    ▼                                         │
│                    ┌───────────────────────────────────┐                    │
│                    │      Cloro Dispatcher (Job)       │                    │
│                    │  1. Read PENDING tasks            │                    │
│                    │  2. Call Cloro API × M times      │                    │
│                    │  3. Update task status            │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                         │
│                                    ▼                                         │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │                         Cloro.dev API                               │   │
│   │  /v1/monitor/chatgpt  │  /v1/monitor/gemini  │  /v1/monitor/aimode  │   │
│   └────────────────────────────────┬───────────────────────────────────┘   │
│                                    │ Webhook Callback                       │
│                                    ▼                                         │
│                    ┌───────────────────────────────────┐                    │
│                    │    Cloro Callback (Service)       │                    │
│                    │  1. Receive JSON payload          │                    │
│                    │  2. Query task metadata           │                    │
│                    │  3. Publish to Pub/Sub            │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                         │
│                                    ▼                                         │
│                    ┌───────────────────────────────────┐                    │
│                    │        Cloud Pub/Sub              │                    │
│                    │    Topic: geo-raw-responses       │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │ Push Subscription                      │
│                                    ▼                                         │
│                    ┌───────────────────────────────────┐                    │
│                    │     Result Ingestor (Service)     │                    │
│                    │  1. Consume Pub/Sub messages      │                    │
│                    │  2. Unpack JSON (Strategy)        │                    │
│                    │  3. INSERT into geo_results       │                    │
│                    │  4. UPDATE task completed_count   │                    │
│                    └───────────────┬───────────────────┘                    │
│                                    │                                         │
│                                    ▼                                         │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │                        PostgreSQL (Cloud SQL)                       │   │
│   │  geo_requests  ──1:N──▶  geo_tasks  ──1:M──▶  geo_results          │   │
│   └────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 运行流程详解

#### 阶段一：业务输入 (Request Creation)
1. 用户通过 `geo_admin` UI 或直接 API 创建 `geo_requests` 记录
2. 配置参数包括：`client_name`, `product`, `platform`, `country`, `prompts_per_request (N)`, `calls_per_prompt (M)`

#### 阶段二：Prompt 扩展 (Prompt Expansion)
1. **Prompt Expander Job** (Cloud Run Job) 定时或手动触发
2. 从 DB 读取 `status=PENDING` 的 requests
3. 调用 **Gemini AI** 生成 N 个多样化 Prompt
4. 将每个 Prompt 写入 `geo_tasks` 表，关联 `request_id`
5. 更新 request `status=EXPANDED`

#### 阶段三：任务分发 (Task Dispatch)
1. **Cloro Dispatcher Job** (Cloud Run Job) 定时触发
2. 从 DB 读取 `status=PENDING` 的 tasks
3. 对每个 task 调用 Cloro API `M` 次（`calls_per_prompt` 次）
4. 附带 `webhook_url` (含 `task_id` 和 `call_index`) 和 `idempotencyKey`
5. 更新 task `status=DISPATCHING`, `dispatched_count++`

#### 阶段四：回调接收 (Webhook Callback)
1. Cloro 完成抓取后，POST JSON 到 **Cloro Callback Service**
2. 从 URL Query Param 提取 `task_id` 和 `call_index`
3. 查询 `geo_tasks` 获取元数据 (platform, client_name 等)
4. 将 `{task_id, call_index, payload, task_meta}` 推送到 Pub/Sub
5. 立即返回 HTTP 200

#### 阶段五：数据入库 (Result Ingestion)
1. **Result Ingestor Service** 被 Pub/Sub Push 触发
2. 解析消息，使用 **Unpacker 策略模式** 解包 JSON
3. INSERT into `geo_results` (幂等，基于 `task_id + call_index` 唯一约束)
4. UPDATE `geo_tasks.completed_count++`
5. 若 `completed_count >= calls_per_prompt`，标记 task `status=COMPLETED`

---

## 4. 数据 Schema 设计 (Database Schema)

### 4.1 三层数据模型

```
geo_requests (业务输入层)
    │
    │ 1 : N
    ▼
geo_tasks (调用实例层)
    │
    │ 1 : M
    ▼
geo_results (结果层)
```

### 4.2 表结构定义

#### geo_requests (业务输入层)

| 列名 | 类型 | 说明 |
|------|------|------|
| `request_id` | UUID (PK) | 主键 |
| `batch_id` | VARCHAR(50) | 批次号 |
| `client_name` | VARCHAR(100) | 客户名称 (必填) |
| `peers` | VARCHAR(500) | 竞品列表 |
| `topic` | VARCHAR(100) | 业务类目 |
| `product` | VARCHAR(100) | 产品名称 |
| `country` | VARCHAR(10) | 国家代码 (US/CN 等) |
| `platform` | VARCHAR(50) | 平台 (chatgpt/gemini/aimode) |
| `intent` | VARCHAR(50) | 意图类型 |
| `target_user` | JSONB | 用户画像 |
| `prompts_per_request` | INTEGER | 生成 Prompt 数量 (N) |
| `calls_per_prompt` | INTEGER | 每 Prompt 调用次数 (M) |
| `status` | VARCHAR(20) | PENDING → EXPANDING → EXPANDED → COMPLETED |
| `created_at` | TIMESTAMPTZ | 创建时间 |
| `updated_at` | TIMESTAMPTZ | 更新时间 |

#### geo_tasks (调用实例层)

| 列名 | 类型 | 说明 |
|------|------|------|
| `task_id` | UUID (PK) | 主键，也是 idempotencyKey |
| `request_id` | UUID (FK) | 关联 geo_requests |
| `prompt_text` | TEXT | Gemini 生成的 Prompt |
| `prompt_index` | INTEGER | Prompt 序号 (1~N) |
| `calls_per_prompt` | INTEGER | 该 task 的调用次数 (M) |
| `dispatched_count` | INTEGER | 已分发次数 |
| `completed_count` | INTEGER | 已完成次数 |
| `status` | VARCHAR(20) | PENDING → DISPATCHING → COMPLETED |
| *(冗余字段)* | | client_name, platform, country 等 |

#### geo_results (结果层 - 宽表)

| 分类 | 列名 | 类型 | 说明 |
|------|------|------|------|
| **主键** | `result_id` | SERIAL | 自增主键 |
| **关联** | `task_id` | UUID (FK) | 关联 geo_tasks |
| **唯一标识** | `call_index` | INTEGER | 调用序号 (1~M) |
| **原始数据** | `cloro_response` | JSONB | 完整 Cloro JSON |
| **解包字段** | `text` | TEXT | 核心文本回答 |
| | `html` | TEXT | 快照 URL |
| | `markdown` | TEXT | Markdown 格式 |
| | `sources` | JSONB | 引用源列表 |
| | `shopping_cards` | JSONB | 购物卡片 |
| | `places` | JSONB | 地点数据 |
| | `entities` | JSONB | 实体识别 |
| | `search_queries` | JSONB | 相关搜索 |
| | `citation_pills` | JSONB | GPT 引用片段 |
| **元数据冗余** | `platform` | VARCHAR | 平台 |
| | `client_name` | VARCHAR | 客户名 |
| | ... | | 其他业务字段 |

**唯一约束**: `UNIQUE (task_id, call_index)` - 保证幂等性

---

## 5. 代码模块目录架构 (Code Structure)

```
geo_collector/
├── Dockerfile                  # 多阶段构建
├── requirements.txt            # Python 依赖
├── alembic/                    # 数据库迁移
│   ├── alembic.ini
│   └── versions/
│       └── three_tier_model.py # 三层模型迁移
├── terraform/                  # 基础设施即代码
│   ├── main.tf
│   ├── variables.tf
│   └── terraform.tfvars
├── src/
│   ├── __init__.py
│   ├── core/
│   │   ├── config.py           # Pydantic Settings
│   │   └── database.py         # 连接池与 Table 定义
│   ├── clients/
│   │   ├── cloro.py            # Cloro API 客户端
│   │   ├── gemini.py           # Gemini AI 客户端 (Prompt 生成)
│   │   └── pubsub.py           # Pub/Sub 服务封装
│   ├── services/
│   │   └── unpackers/          # 解包器模块 (策略模式)
│   │       ├── base.py         # BaseUnpacker 抽象类
│   │       ├── chatgpt.py      # ChatGPT 解包器
│   │       ├── gemini.py       # Gemini 解包器
│   │       ├── aimode.py       # AI Mode 解包器
│   │       └── factory.py      # UnpackerFactory
│   ├── expander.py             # [Job] Prompt Expander
│   ├── cloro_dispatcher.py     # [Job] Cloro Dispatcher
│   ├── cloro_callback.py       # [Service] Webhook 接收器
│   └── result_ingestor.py      # [Service] 结果入库 Worker
```

### 5.1 核心模块说明

| 模块 | 入口 | 运行方式 | 职责 |
|------|------|----------|------|
| `expander.py` | `__main__` | Cloud Run Job | 读取 PENDING requests，调用 Gemini 生成 Prompts |
| `cloro_dispatcher.py` | `__main__` | Cloud Run Job | 读取 PENDING tasks，调用 Cloro API |
| `cloro_callback.py` | FastAPI | Cloud Run Service | 接收 Cloro 回调，推送 Pub/Sub |
| `result_ingestor.py` | FastAPI | Cloud Run Service | 消费 Pub/Sub，写入数据库 |

### 5.2 解包器策略模式

```python
# 抽象基类
class BaseUnpacker(ABC):
    @abstractmethod
    def unpack(self, payload: dict) -> dict:
        """从 Cloro 响应中提取结构化字段"""
        pass

# 工厂类
class UnpackerFactory:
    @staticmethod
    def get_unpacker(platform: str) -> BaseUnpacker:
        mapping = {
            "chatgpt": ChatGPTUnpacker(),
            "gemini": GeminiUnpacker(),
            "aimode": AIModeUnpacker(),
        }
        return mapping.get(platform, DefaultUnpacker())
```

**字段映射示例 (ChatGPT)**:
| Cloro JSON Path | DB Column |
|-----------------|-----------|
| `response.text` | `text` |
| `response.shoppingCards` | `shopping_cards` |
| `response.sources` | `sources` |

---

## 6. GCP 基础设施配置 (Infrastructure)

### 6.1 服务清单

| 服务 | GCP 资源 | 说明 |
|------|----------|------|
| **Prompt Expander** | Cloud Run Job | 定时或手动触发 |
| **Cloro Dispatcher** | Cloud Run Job | 定时触发 (每 10 分钟) |
| **Cloro Callback** | Cloud Run Service | HTTP Server，公网可访问 |
| **Result Ingestor** | Cloud Run Service | HTTP Server，Pub/Sub Push 触发 |
| **数据库** | Cloud SQL PostgreSQL | 单实例，支持 Cloud SQL Auth Proxy |
| **消息队列** | Cloud Pub/Sub | Topic: geo-raw-responses |
| **镜像仓库** | Artifact Registry | answer-x-geo-repo |

### 6.2 关键环境变量

| 变量名 | 说明 |
|--------|------|
| `DATABASE_URL` | 数据库连接字符串 |
| `DB_INSTANCE_CONNECTION_NAME` | Cloud SQL 连接名 (PROJECT:REGION:INSTANCE) |
| `CLORO_API_KEY` | Cloro API 密钥 |
| `WEBHOOK_PUBLIC_URL` | Callback Service 公网地址 |
| `PUBSUB_PROJECT_ID` | GCP 项目 ID |
| `PUBSUB_TOPIC_NAME` | Pub/Sub Topic 名称 |
| `GEMINI_MODEL_ID` | Gemini 模型 ID (gemini-2.5-flash) |

### 6.3 Terraform 管理资源

- Artifact Registry Repository
- Cloud Run Services & Jobs
- Cloud Pub/Sub Topic & Subscription
- Cloud Scheduler (定时触发)
- IAM Bindings

---

## 7. 部署与运维 (Deployment & Operations)

### 7.1 部署流程

```bash
# 1. 构建镜像
gcloud builds submit --tag us-central1-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v5 .

# 2. 更新 terraform.tfvars 中的 image_tag

# 3. 应用 Terraform
cd terraform
terraform apply
```

### 7.2 版本更新流程

1. 修改代码
2. 构建新版本镜像 (`:v6`)
3. 更新 `terraform.tfvars` 中的 `image_tag`
4. 运行 `terraform apply`

### 7.3 故障排查

| 问题 | 检查点 |
|------|--------|
| Cloud Run 启动失败 | Cloud SQL Client 权限、环境变量 |
| Webhook 无响应 | WEBHOOK_PUBLIC_URL 是否正确 |
| Pub/Sub 消息堆积 | Worker 日志、数据库连接 |
| 重复数据 | UNIQUE 约束、幂等性检查 |

---

## 8. 实施建议与优化 (Best Practices)

### 8.1 安全性

- **Webhook 签名校验**: 可选实现 HMAC 签名验证
- **IAP 保护**: 内部管理界面使用 Identity-Aware Proxy

### 8.2 性能优化

- **连接池**: `min_size=1, max_size=5` (适配 Cloud Run 冷启动)
- **批处理**: Dispatcher 每批次处理 100 个 tasks
- **并发控制**: 使用 `asyncio.Semaphore` 限制并发

### 8.3 可观测性

#### 日志格式规范

所有模块使用结构化日志格式：`[MODULE-SX] 描述 | key=value`

| 模块 | 标签前缀 | 步骤说明 |
|------|----------|----------|
| `expander.py` | `[EXPANDER-S0~S3]` | S0=启动/关闭, S1=查询requests, S2=处理单个, S3=汇总 |
| `prompt_expander.py` | `[EXPAND-S1~S6]` | S1=读取, S2=锁定, S3=Gemini调用, S4=创建tasks, S5=状态更新, S6=Pub/Sub |
| `cloro_dispatcher.py` | `[DISPATCHER-S0~S5]` | S0=启动, S1=消息接收, S2=锁定, S3=读取task, S4=Cloro调用, S5=状态更新 |
| `cloro_callback.py` | `[CALLBACK-S0~S3]` | S0=启动, S1=接收回调, S2=查询元数据, S3=Pub/Sub发布 |
| `result_ingestor.py` | `[INGESTOR-S0~S6]` | S0=启动, S1=消息解析, S2=识别平台, S3=解包, S4=写入DB, S5=检查task完成, S6=检查request完成 |
| `cloro.py` | `[CLORO-S1~S2]` | S1=发送请求, S2=接收响应 |
| `gemini.py` | `[GEMINI-S0~S3]` | S0=初始化, S1=构建prompt, S2=API调用, S3=解析响应 |

**Cloud Logging 搜索示例**：
```
# 搜索特定模块的所有日志
textPayload:"[DISPATCHER"

# 搜索特定 task_id
textPayload:"task_id=abc-123"

# 搜索特定 request_id
textPayload:"request_id=xyz-456"

# 搜索所有错误
textPayload:"ERR]"

# 搜索特定步骤
textPayload:"[EXPAND-S3]"
```

- **监控**: Cloud Monitoring 仪表盘
- **追踪**: 可接入 Cloud Trace

---

## 9. Analyzer 架构设计规划 (Future Evolution)

### 9.1 目标

将 `geo_results` 宽表中的半结构化数据（JSONB）进一步分析，产出结构化的分析结论。

### 9.2 拟新增表

| 表名 | 用途 |
|------|------|
| `geo_citations` | 引用来源分析 (URL, Domain, Rank) |
| `geo_visibility_metrics` | 品牌/产品可见性 (Brand, Visibility Type, Rank) |
| `geo_sentiment_scores` | 情感分析 (Sentiment Score, Label) |

### 9.3 分析流程

1. **Extract**: 从 `geo_results` 读取未分析记录
2. **Transform**: 
   - 使用策略模式解析 sources/entities
   - 调用 LLM 进行情感分析
3. **Load**: 写入结构化分析表

### 9.4 可视化

基于分析表，接入 Metabase 或 Looker Studio：
- 竞品 SOV (Share of Voice) 趋势
- 品牌情感评分变化
- 高频引用来源排行

---

## 附录 A: Alembic 迁移清单

| 文件名 | 版本 | 说明 |
|--------|------|------|
| `initial_tables.py` | bb915c6eb8a9 | 创建原始 geo_tasks/geo_results |
| `add_task_metadata_columns.py` | 下一版本 | 添加元数据列 |
| `three_tier_model.py` | three_tier_model | 重构为三层模型 |

---

## 附录 B: API 端点清单

### Cloro Callback Service

| Method | Path | 说明 |
|--------|------|------|
| POST | `/webhook/cloro` | 接收 Cloro 回调 |

### Result Ingestor Service

| Method | Path | 说明 |
|--------|------|------|
| POST | `/ingest` | 接收 Pub/Sub Push |

---

## 附录 C: 待办事项 (TODO)

| 优先级 | 模块 | 描述 |
|--------|------|------|
| P2 | `cloro_dispatcher.py` | 当 request 的所有 tasks 完成/失败后，同步更新 `geo_requests.status` 为 `COMPLETED` / `FAILED`，目前 task 失败后 request 状态仍保持 `EXPANDED` |
| P3 | Analyzer | 实现 Analyzer Worker，从 `geo_results` 提取结构化数据到分析表 |
| P3 | 可视化 | 接入 Metabase / Looker Studio 构建 BI 仪表盘 |

---

*文档版本: v3.0 | 最后更新: 2026-02-07*