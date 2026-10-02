# GEO Collector - GCP Deployment Guide

本指南将指导您将 GEO Collector 系统部署到 Google Cloud Platform (GCP)。
架构采用微服务模式，由以下组件构成：

| 组件 | 类型 | Terraform 资源名 | 说明 |
|------|------|------------------|------|
| **Cloro Callback** | Cloud Run Service | `geo-cloro-callback` | 接收 Cloro 异步回调 |
| **Cloro Dispatcher** | Cloud Run Service | `geo-cloro-dispatcher` | 分发任务到 Cloro API |
| **Result Ingestor** | Cloud Run Service | `geo-result-ingestor` | 入库回调数据 |
| **Prompt Expander** | Cloud Run Job | `geo-prompt-expander` | 生成 Prompt (Job) |

## 1. 前置准备 (Prerequisites)

确保您已安装并配置好 `gcloud` CLI，并且已登录到您的 GCP 项目。

### 1.1 设置 GCP 项目与配额

为了确保所有操作都在正确的项目中执行，请运行以下命令：

```bash
# 设置项目 ID
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"

# 切换当前工作项目
gcloud config set project $PROJECT_ID

# 设置配额项目 (用于本地 ADC 调用 API)
gcloud auth application-default set-quota-project $PROJECT_ID
```

### 1.2 启用必要的 API

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  pubsub.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  aiplatform.googleapis.com
```

### 1.3 配置 Cloud Run 服务账号权限 (重要)

Cloud Run 默认使用 Compute Engine 默认服务账号 (`[PROJECT_NUMBER]-compute@developer.gserviceaccount.com`)。
为了让 Cloud Run 能连接 Cloud SQL 和调用 Vertex AI，必须赋予相应权限。

```bash
# 获取项目编号
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

# 赋予权限
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/aiplatform.user"
```

### 1.4 创建 Artifact Registry 并推送镜像

```bash
# 创建仓库
gcloud artifacts repositories create answer-x-geo-repo \
  --repository-format=docker \
  --location=$REGION \
  --description="Docker repository for GEO Collector"

# 构建并推送镜像 (Cloud Build)
# 在 geo_collector 目录下执行
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v1 .
```

---

# 部署方式一：Terraform 自动化部署 (推荐)

Terraform 允许您通过声明式配置文件 (`.tf`) 管理所有 GCP 资源。

### 1. 安装 Terraform
请参考 [Terraform 官方文档](https://developer.hashicorp.com/terraform/install) 安装 CLI 工具。

### 2. 准备变量文件
在 `geo_collector/terraform` 目录下创建一个 `terraform.tfvars` 文件（**不要提交到 Git**），填入您的敏感信息。

```hcl
project_id                  = "your-gcp-project-id"
region                      = "us-central1"
repo_name                   = "answer-x-geo-repo"
image_tag                   = "us-central1-docker.pkg.dev/your-project/answer-x-geo-repo/geo-collector:v1"
db_instance_connection_name = "your-project:us-central1:your-instance"
db_name                     = "geo_db"
db_user                     = "geo_user"
db_password                 = "your-db-password"
cloro_api_key               = "your-cloro-key"
gemini_model_id             = "gemini-2.5-flash"
# webhook_public_url        = "https://..."  # 第一次部署时留空，部署后填入真实 URL
```

### 3. 初始化 Terraform
进入 terraform 目录并初始化：
```bash
cd geo_collector/terraform
terraform init
```

### 4. 预览变更 (Plan)
查看 Terraform 即将创建哪些资源：
```bash
terraform plan
```

### 5. 第一次应用 (Apply - 创建基础设施)
执行第一次部署。
**注意**: 这一步可能会报错 `Image not found`，这是正常的，因为我们还没推送镜像。但 Artifact Registry 仓库会被成功创建。

```bash
terraform apply
```
*输入 `yes` 确认。*

### 6. 构建并推送镜像 (Build & Push)
现在仓库已创建，我们需要构建并推送 Docker 镜像。

```bash
cd ..
gcloud builds submit --tag us-central1-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v1 .
```

### 7. 第二次应用 (Apply - 部署服务)
镜像就绪后，再次运行 Terraform，这次 Cloud Run 服务将成功启动。

```bash
cd terraform
terraform apply
```

### 8. 部署后更新 Webhook URL (重要)
部署完成后，Terraform 会输出 `cloro_callback_url`。
1.  复制这个 URL。
2.  修改 `terraform.tfvars`，填入 `webhook_public_url`。
3.  **第三次运行** `terraform apply`。

### 9. Terraform 创建的资源清单

| 资源类型 | 名称 | 说明 |
|----------|------|------|
| Artifact Registry | `answer-x-geo-repo` | Docker 镜像仓库 |
| Pub/Sub Topic | `geo-cloro-callbacks` | Cloro 回调消息 |
| Pub/Sub Topic | `geo-tasks-pending` | 待分发任务消息 |
| Pub/Sub Subscription | `geo-callbacks-to-ingestor` | 推送到 Result Ingestor |
| Pub/Sub Subscription | `geo-tasks-to-dispatcher` | 推送到 Cloro Dispatcher |
| Cloud Run Service | `geo-cloro-callback` | 接收 Cloro 回调 |
| Cloud Run Service | `geo-result-ingestor` | 数据入库 |
| Cloud Run Service | `geo-cloro-dispatcher` | 任务分发 |
| Cloud Run Job | `geo-prompt-expander` | Prompt 扩展 |
| Cloud Scheduler | `geo-expander-cron` | 定时触发 (默认暂停) |
| Service Account | `pubsub-invoker` | Pub/Sub 调用者 |

### 10. 后续修改
如果您需要修改配置（例如增加内存），只需修改 `main.tf`，然后再次运行 `terraform apply`。

### 11. 销毁资源 (Destroy)
如果您想删除所有部署的资源（清理环境）：
```bash
terraform destroy
```

### 12. 代码更新后如何发布新版本？

如果您修改了代码并希望部署新版本，请遵循以下流程：

1.  **构建新镜像**：使用新的版本号（如 `:v2`）构建并推送镜像。
    ```bash
    gcloud builds submit --tag us-central1-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v2 .
    ```
2.  **更新 Terraform 变量**：修改 `terraform.tfvars` 中的 `image_tag`。
    ```hcl
    image_tag = "us-central1-docker.pkg.dev/your-project/answer-x-geo-repo/geo-collector:v2"
    ```
3.  **应用变更**：运行 `terraform apply`。

---

# 部署方式二：手动命令行部署 (Gcloud CLI)

> **注意**: 推荐使用 Terraform 部署。以下手动命令仅供参考和调试。

## 1. 准备环境变量

创建一个 `.env.cloud` 文件（**不要提交到 Git**），填入生产环境配置：

```ini
# 数据库配置 (Cloud Run 会自动使用 Unix Socket 连接)
DB_INSTANCE_CONNECTION_NAME=PROJECT:REGION:INSTANCE
DB_NAME=geo_db
DB_USER=geo_user
DB_PASSWORD=your_password

# 其他配置
CLORO_API_KEY=your_real_cloro_key
CLORO_BASE_URL=https://api.cloro.dev
PUBSUB_PROJECT_ID=your-gcp-project-id
PUBSUB_TOPIC_NAME=geo-cloro-callbacks
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
GEMINI_MODEL_ID=gemini-2.5-flash
LOG_LEVEL=INFO
```

## 2. 部署 Cloro Callback Service

部署负责接收 Cloro 回调的 Web 服务。

```bash
gcloud run deploy geo-cloro-callback \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v1 \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances YOUR_CONNECTION_NAME \
  --env-vars-file .env.cloud \
  --command "uvicorn" \
  --args "src.cloro_callback:app,--host,0.0.0.0,--port,8080"
```

### ⚠️ 重要：更新 Webhook URL

部署成功后，GCP 会返回一个 URL（例如 `https://geo-cloro-callback-xyz.a.run.app`）。
您需要将此 URL 更新到 `.env.cloud` 中的 `WEBHOOK_PUBLIC_URL` 变量中，并**重新部署**所有服务以生效。

## 3. 部署 Result Ingestor Service

部署负责处理 Pub/Sub 消息并写入数据库的服务。

```bash
gcloud run deploy geo-result-ingestor \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v1 \
  --region $REGION \
  --platform managed \
  --no-allow-unauthenticated \
  --add-cloudsql-instances YOUR_CONNECTION_NAME \
  --env-vars-file .env.cloud \
  --command "uvicorn" \
  --args "src.result_ingestor:app,--host,0.0.0.0,--port,8080"
```

## 4. 部署 Cloro Dispatcher Service

部署负责分发任务到 Cloro API 的服务。

```bash
gcloud run deploy geo-cloro-dispatcher \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v1 \
  --region $REGION \
  --platform managed \
  --no-allow-unauthenticated \
  --add-cloudsql-instances YOUR_CONNECTION_NAME \
  --env-vars-file .env.cloud \
  --command "uvicorn" \
  --args "src.cloro_dispatcher:app,--host,0.0.0.0,--port,8080"
```

## 5. 配置 Pub/Sub

### 5.1 创建 Topics
```bash
gcloud pubsub topics create geo-cloro-callbacks
gcloud pubsub topics create geo-tasks-pending
```

### 5.2 创建 Service Account
```bash
gcloud iam service-accounts create pubsub-invoker \
  --display-name "Pub/Sub Invoker"
```

### 5.3 创建 Push Subscriptions

```bash
# Result Ingestor URL
INGESTOR_URL=$(gcloud run services describe geo-result-ingestor --region $REGION --format 'value(status.url)')

# Dispatcher URL
DISPATCHER_URL=$(gcloud run services describe geo-cloro-dispatcher --region $REGION --format 'value(status.url)')

# 赋予调用权限
gcloud run services add-iam-policy-binding geo-result-ingestor \
  --region $REGION \
  --member="serviceAccount:pubsub-invoker@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud run services add-iam-policy-binding geo-cloro-dispatcher \
  --region $REGION \
  --member="serviceAccount:pubsub-invoker@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# 创建订阅
gcloud pubsub subscriptions create geo-callbacks-to-ingestor \
  --topic geo-cloro-callbacks \
  --push-endpoint=$INGESTOR_URL/ingest/result \
  --push-auth-service-account=pubsub-invoker@$PROJECT_ID.iam.gserviceaccount.com \
  --ack-deadline=600

gcloud pubsub subscriptions create geo-tasks-to-dispatcher \
  --topic geo-tasks-pending \
  --push-endpoint=$DISPATCHER_URL/dispatch/task \
  --push-auth-service-account=pubsub-invoker@$PROJECT_ID.iam.gserviceaccount.com \
  --ack-deadline=600
```

## 6. 部署 Prompt Expander Job

部署 Cloud Run Job，用于扩展 Prompt。

```bash
gcloud run jobs create geo-prompt-expander \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:v1 \
  --region $REGION \
  --add-cloudsql-instances YOUR_CONNECTION_NAME \
  --env-vars-file .env.cloud \
  --command "python" \
  --args "-m,src.expander"
```

### 手动触发

```bash
gcloud run jobs execute geo-prompt-expander --region $REGION
```

---

## 故障排查

| 问题 | 检查点 |
|------|--------|
| Cloud Run 启动失败 | Cloud SQL Client 权限、环境变量 |
| Webhook 无响应 | WEBHOOK_PUBLIC_URL 是否正确 |
| Pub/Sub 消息堆积 | Worker 日志、数据库连接 |
| 重复数据 | UNIQUE 约束、幂等性检查 |
| Gemini 调用失败 | aiplatform.user 权限、GCP_PROJECT_ID |

---

*最后更新: 2026-02-07*