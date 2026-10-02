#!/bin/bash

# ======================================================
# GEO Platform - 完整发布与部署脚本
# ======================================================
# 此脚本会：
#   1. 自动更新各模块 terraform.tfvars 中的 image_tag 版本号
#   2. 构建指定服务的 Docker 镜像并推送至 Artifact Registry
#   3. 执行指定模块的 Terraform Apply 完成 Cloud Run 部署
#
# 使用方法：
#   cd /path/to/GEO_Demo && bash deploy_all.sh
#
# 版本升级只需修改下面的 VERSION 变量，运行脚本即可。
# tfvars 文件会被自动更新，无需手动修改。
#
# 前提条件：
#   1. 已安装 Google Cloud CLI (gcloud) 和 Terraform
#   2. 具有目标 GCP 项目的权限
# ======================================================

set -e

# ==============================
# 配置区（每次发布只需改这里）
# ==============================
export PROJECT_ID="project-90d7849c-de16-4c15-a0a"
export REGION="us-central1"

export COLLECTOR_VERSION="v25"
export ADMIN_API_VERSION="v31"
export ADMIN_WEB_VERSION="v32"
export ANALYZER_VERSION="v27"
export SAAS_API_VERSION="v76"
export SAAS_WEB_VERSION="v104"
export AGENT_VERSION="v55"

# ==============================
# 自动派生变量（无需修改）
# ==============================
export REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

COLLECTOR_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/answer-x-geo-repo/geo-collector:$COLLECTOR_VERSION"
ADMIN_API_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/geo-admin-repo/geo-admin-api:$ADMIN_API_VERSION"
ADMIN_WEB_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/geo-admin-repo/geo-admin-web:$ADMIN_WEB_VERSION"
ANALYZER_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/geo-analyzer-repo/geo-analyzer:$ANALYZER_VERSION"
SAAS_API_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/geo-saas-repo/geo-saas-api:$SAAS_API_VERSION"
SAAS_WEB_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/geo-saas-repo/geo-saas-web:$SAAS_WEB_VERSION"
AGENT_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/geo-agent-repo/geo-agent:$AGENT_VERSION"

# ==============================
# 自动同步 tfvars 版本号
# ==============================
echo ">> 同步本次部署模块 terraform.tfvars image_tag..."
# sed -i.bak "s#image_tag                   = \".*geo-collector:.*\"#image_tag                   = \"$COLLECTOR_IMAGE\"#" "$REPO_ROOT/geo_collector/terraform/terraform.tfvars"
# sed -i.bak "s#api_image_tag = \".*geo-admin-api:.*\"#api_image_tag = \"$ADMIN_API_IMAGE\"#" "$REPO_ROOT/geo_admin/terraform/terraform.tfvars"
# sed -i.bak "s#web_image_tag = \".*geo-admin-web:.*\"#web_image_tag = \"$ADMIN_WEB_IMAGE\"#" "$REPO_ROOT/geo_admin/terraform/terraform.tfvars"
# sed -i.bak "s#image_tag = \".*geo-analyzer:.*\"#image_tag = \"$ANALYZER_IMAGE\"#" "$REPO_ROOT/geo_analyzer/terraform/terraform.tfvars"
# sed -i.bak "s#api_image_tag = \".*geo-saas-api:.*\"#api_image_tag = \"$SAAS_API_IMAGE\"#" "$REPO_ROOT/geo_saas/terraform/terraform.tfvars"
sed -i.bak "s#web_image_tag = \".*geo-saas-web:.*\"#web_image_tag = \"$SAAS_WEB_IMAGE\"#" "$REPO_ROOT/geo_saas/terraform/terraform.tfvars"
# sed -i.bak "s#image_tag = \".*geo-agent:.*\"#image_tag = \"$AGENT_IMAGE\"#" "$REPO_ROOT/geo_agent/terraform/terraform.tfvars"

# ==============================
# 开始部署
# ==============================
echo ""
echo "======================================================"
echo "准备部署 GEO Platform..."
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo ""
echo "当前镜像版本:"
echo "  Collector:  $COLLECTOR_VERSION"
echo "  Analyzer:   $ANALYZER_VERSION"
echo "  Admin API:  $ADMIN_API_VERSION"
echo "  Admin Web:  $ADMIN_WEB_VERSION"
echo "  SaaS API:   $SAAS_API_VERSION"
echo "  SaaS Web:   $SAAS_WEB_VERSION"
echo "  Agent:      $AGENT_VERSION"
echo "  Skipped:    Collector / Admin / Analyzer / Agent"
echo ""
echo "本次启用模块:"
echo "  SaaS Web: 强化 URL 变体与待确认操作按钮的视觉层级"
echo "  其他模块: Collector / Admin / Analyzer / Agent 未修改，构建和 Terraform 命令保留为注释"
echo "======================================================"

gcloud config set project "$PROJECT_ID"
gcloud auth application-default set-quota-project "$PROJECT_ID"


# ==============================
# Build helper — unified cloudbuild.yaml
# ==============================
# 从 Phase 2 (2026-04-25) 起，所有 Python 模块的镜像 build 统一从仓库根提交，
# 通过 cloudbuild.yaml + _DOCKERFILE/_IMAGE 两个 substitution 选择具体 Dockerfile。
# 这样每次 build 都能把 geo_common/ 源码一并打进镜像。
# Web 前端镜像不走这个 helper（它们是 self-contained vite build，不依赖 geo_common）。
build_python_module() {
  local dockerfile="$1"   # 如 "geo_saas/src/Dockerfile"（相对仓库根）
  local image_tag="$2"
  cd "$REPO_ROOT"
  gcloud builds submit . \
    --config=cloudbuild.yaml \
    --substitutions="_DOCKERFILE=$dockerfile,_IMAGE=$image_tag"
}

echo ""
echo ">> [1/5] === 处理 GEO Collector ==="
echo "跳过 Collector：本轮未修改 Collector。"
# echo "构建 Collector 镜像..."
# build_python_module "geo_collector/Dockerfile" "$COLLECTOR_IMAGE"
# echo "应用 Collector Terraform..."
# cd "$REPO_ROOT/geo_collector/terraform"
# terraform init -input=false
# terraform apply -auto-approve

echo ""
echo ">> [2/5] === 处理 GEO Admin ==="
echo "跳过 Admin：本轮未修改 Admin。"
# echo "构建 Admin API 镜像..."
# build_python_module "geo_admin/src/Dockerfile" "$ADMIN_API_IMAGE"
# echo "构建 Admin Web 镜像..."
# cd "$REPO_ROOT/geo_admin"
# gcloud builds submit ./web --tag "$ADMIN_WEB_IMAGE"
# echo "应用 Admin Terraform..."
# cd "$REPO_ROOT/geo_admin/terraform"
# terraform init -input=false
# terraform apply -auto-approve

echo ""
echo ">> [3/5] === 处理 GEO Analyzer ==="
echo "跳过 Analyzer：本轮未修改 Analyzer。"
# echo "构建 Analyzer 镜像..."
# build_python_module "geo_analyzer/Dockerfile" "$ANALYZER_IMAGE"
# echo "应用 Analyzer Terraform..."
# cd "$REPO_ROOT/geo_analyzer/terraform"
# terraform init -input=false
# terraform apply -auto-approve -parallelism=1

echo ""
echo ">> [4/5] === 处理 GEO SaaS ==="
# echo "构建 SaaS API 镜像..."
# build_python_module "geo_saas/src/Dockerfile" "$SAAS_API_IMAGE"
echo "构建 SaaS Web 镜像..."
cd "$REPO_ROOT/geo_saas"
gcloud builds submit ./web --tag "$SAAS_WEB_IMAGE"
echo "应用 SaaS Terraform..."
cd "$REPO_ROOT/geo_saas/terraform"
terraform init -input=false
terraform apply -auto-approve -parallelism=1

echo ""
echo ">> [5/5] === 处理 GEO Agent ==="
echo "跳过 Agent：本次热修未修改 Agent。"
# echo "构建 Agent 镜像..."
# build_python_module "geo_agent/Dockerfile" "$AGENT_IMAGE"
# echo "应用 Agent Terraform..."
# cd "$REPO_ROOT/geo_agent/terraform"
# terraform init -input=false
# terraform apply -auto-approve -parallelism=1


echo ""
echo "======================================================"
echo "✅ GEO SaaS Citation URL 操作按钮样式部署执行完毕！"
echo "  Collector:  $COLLECTOR_VERSION"
echo "  Analyzer:   $ANALYZER_VERSION"
echo "  Admin API:  $ADMIN_API_VERSION"
echo "  Admin Web:  $ADMIN_WEB_VERSION"
echo "  SaaS API:   $SAAS_API_VERSION"
echo "  SaaS Web:   $SAAS_WEB_VERSION"
echo "  Agent:      $AGENT_VERSION"
echo "  Skipped:    Collector / Admin / Analyzer / Agent"
echo "======================================================"
