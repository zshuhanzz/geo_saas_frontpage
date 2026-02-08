# GEO Admin

GEO Collector 内部管理后台。

## 目录结构

```
geo_admin/
├── api/          # FastAPI 后端
├── web/          # React 前端
└── terraform/    # Cloud Run 部署配置
```

---

## 本地开发

### 前置条件

- Python 3.12+
- Node.js 18+
- Cloud SQL Proxy 运行中 (连接 localhost:5432)

### 1. 配置环境变量

```bash
# 编辑 web/.env，填入 Google OAuth Client ID
cd /Users/sicong/Desktop/GEO_Demo/geo_admin/web
# 文件内容: VITE_GOOGLE_CLIENT_ID=你的CLIENT_ID
```

### 2. 启动 API 后端

```bash
cd /Users/sicong/Desktop/GEO_Demo/geo_admin/api

# 创建虚拟环境 (首次)
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务 (开发模式，自动重载)
uvicorn main:app --reload --port 8000
```

API 运行在: http://localhost:8000

### 3. 启动 Web 前端

```bash
cd /Users/sicong/Desktop/GEO_Demo/geo_admin/web

# 安装依赖 (首次)
npm install

# 启动开发服务器
npm run dev
```

前端运行在: http://localhost:5173

---

## 用户认证 (Google OAuth)

### GCP 配置

1. 打开 [GCP Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. **Create Credentials** → **OAuth client ID** → **Web application**
3. 添加 Authorized JavaScript origins:
   - `https://geo-admin-web-353184850178.us-central1.run.app`
   - `http://localhost:5173`
4. 复制 Client ID

### 环境变量配置

| 文件 | 用途 |
|------|------|
| `web/.env` | 本地开发 |
| `terraform/terraform.tfvars` | 生产构建 |

生产构建时需要传入环境变量：
```bash
VITE_GOOGLE_CLIENT_ID=你的CLIENT_ID npm run build
```

### 邮箱白名单 (可选)

编辑 `web/src/contexts/AuthContext.jsx`：
```js
const ALLOWED_EMAILS = ['user@example.com'];
// 或限制域名
const ALLOWED_DOMAINS = ['@yourcompany.com'];
```

> **不配置白名单** = 任何 Google 账号都能登录

---

## 云端部署 (Cloud Run)

### 1. 设置环境变量

```bash
export PROJECT_ID="project-24092938-79c2-4d0a-b9d"
export REGION="us-central1"
export ADMIN_REPO_NAME="geo-admin-repo"

gcloud config set project $PROJECT_ID
gcloud auth application-default set-quota-project $PROJECT_ID
```

### 2. 创建 Artifact Registry (仅首次)

```bash
gcloud artifacts repositories create $ADMIN_REPO_NAME \
  --repository-format=docker \
  --location=$REGION \
  --description="Docker repository for GEO Admin"
```

### 3. 构建并推送镜像

```bash
cd /Users/sicong/Desktop/GEO_Demo/geo_admin

# 构建 API 镜像
gcloud builds submit ./api \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/$ADMIN_REPO_NAME/geo-admin-api:v2

# 构建 Web 镜像 (确保 web/.env 已配置 VITE_GOOGLE_CLIENT_ID)
cd web
npm run build
cd ..
gcloud builds submit ./web \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/$ADMIN_REPO_NAME/geo-admin-web:v2
```

### 4. Terraform 部署

```bash
cd /Users/sicong/Desktop/GEO_Demo/geo_admin/terraform

# 初始化
terraform init

# 预览
terraform plan

# 部署
terraform apply
```

### 5. 更新版本

```bash
# 1. 构建新版本镜像
cd /Users/sicong/Desktop/GEO_Demo/geo_admin

gcloud builds submit ./api \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/$ADMIN_REPO_NAME/geo-admin-api:v2

cd web && VITE_GOOGLE_CLIENT_ID=你的CLIENT_ID npm run build && cd ..
gcloud builds submit ./web \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/$ADMIN_REPO_NAME/geo-admin-web:v2

# 2. 更新 terraform.tfvars 中的版本号
# api_image_tag = "...geo-admin-api:v2"
# web_image_tag = "...geo-admin-web:v2"

# 3. 重新部署
cd terraform && terraform apply
```

---

## API 端点

| Method | Path | 说明 |
|--------|------|------|
| GET | /api/stats | 概览统计 |
| GET | /api/requests | 请求列表 (分页) |
| POST | /api/requests | 创建请求 |
| POST | /api/requests/trigger | 触发 Pipeline |
| GET | /api/requests/{id} | 请求详情 |
| GET | /api/requests/{id}/tasks | 任务列表 |
| GET | /api/tasks/{id}/results | 结果列表 |
| POST | /api/reports/{id}/analyze | 触发分析任务 |
| GET | /api/analysis/status/{id} | 分析状态 |
| GET | /api/analysis/mentions | 公司提及分析 |
| GET | /api/analysis/citations | 引用来源分析 |
