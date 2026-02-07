
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

## 📦 系统架构

本项目设计为部署在 Google Cloud Run 上，分为四个核心组件：

### 1. Prompt Expander (Cloud Run Job)
从 `geo_requests` 读取待处理任务，调用 Gemini 生成多样化 Prompt，写入 `geo_tasks`。

*   **入口**: `src.expander`
*   **命令**: `python -m src.expander`

### 2. Cloro Dispatcher (Cloud Run Service)
被 Pub/Sub (geo-tasks-pending) 触发，读取 `geo_tasks` 并调用 Cloro API。

*   **入口**: `src.cloro_dispatcher:app`
*   **命令**: `uvicorn src.cloro_dispatcher:app --host 0.0.0.0 --port 8080`

### 3. Cloro Callback (Cloud Run Service)
接收 Cloro 的异步回调，查询元数据后推送到 Pub/Sub。

*   **入口**: `src.cloro_callback:app`
*   **命令**: `uvicorn src.cloro_callback:app --host 0.0.0.0 --port 8080`

### 4. Result Ingestor (Cloud Run Service)
消费 Pub/Sub 消息，解包 JSON 并写入 `geo_results`。

*   **入口**: `src.result_ingestor:app`
*   **命令**: `uvicorn src.result_ingestor:app --host 0.0.0.0 --port 8080`

### Docker 构建

```bash
# 在 geo_collector 目录下
docker build -t geo-collector .
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
| `cloro.py` | `[CLORO-S1~S2]` | `[CLORO-S2] 发送成功 \| cloro_id=xxx` |
| `gemini.py` | `[GEMINI-S0~S3]` | `[GEMINI-S3] 解析完成 \| generated=20` |

**Cloud Logging 搜索示例**：
```
# 搜索特定模块
textPayload:"[DISPATCHER"

# 搜索特定 task
textPayload:"task_id=your-task-id"

# 搜索错误
textPayload:"ERR]"
```

---

## 📚 详细文档

更多关于架构设计、数据库 Schema 和模块说明，请参阅 [技术设计文档 (CODE_ASSISTANT.md)](CODE_ASSISTANT.md)。

部署指南请参阅 [DEPLOY.md](DEPLOY.md)。

---

*最后更新: 2026-02-07*
