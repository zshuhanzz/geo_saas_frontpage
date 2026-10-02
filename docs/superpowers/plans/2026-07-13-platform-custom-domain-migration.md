# SaaS Custom Domain Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将 SaaS Web 平滑接入 `https://platform.answer-x.ai`，保持现有 Cloud Run URL 全程可用，并提供 canary 验证、监控、回滚和中国大陆访问验收。

**Architecture:** 使用 Global External Application Load Balancer、`us-central1` Serverless NEG、Certificate Manager DNS authorization、全局静态 IPv4 和 GoDaddy DNS。正式切换仅修改 `platform.answer-x.ai` 的 A 记录；第一阶段不收紧 Cloud Run ingress、不禁用默认 URL、不改变 SaaS API/Agent/Cloud SQL。

**Tech Stack:** Google Cloud Run、Global External Application Load Balancer、Serverless NEG、Certificate Manager、Terraform、gcloud CLI、GoDaddy DNS、Google OAuth Web Client。

**Spec:** `docs/superpowers/specs/2026-07-13-platform-custom-domain-migration-design.md`

---

## 0. 实施原则与变更边界

### 必须遵守

- [ ] 所有 GCP 命令使用 `lancelot.chen@answer-x.ai`。
- [ ] 所有资源操作限定在 `project-90d7849c-de16-4c15-a0a`。
- [ ] GCP 资源以 Terraform 为事实源；Console 只用于查看，OAuth 与 GoDaddy DNS 除外。
- [ ] 每个 `terraform apply` 必须使用人工审阅过的 saved plan；禁止 `-auto-approve`。
- [ ] 不运行根目录 `deploy_all.sh`。它会重建 SaaS 镜像并自动 apply，超出域名迁移范围。
- [ ] 不删除或替换 `geo-saas-web`、`geo-saas-api`、`geo-agent`。
- [ ] 不修改 Cloud SQL。
- [ ] 不修改 SaaS API/Agent ingress。
- [ ] 不禁用任何 Cloud Run default URL。
- [ ] 正式 A 记录上线前，托管证书必须为 `ACTIVE`，canary 必须通过。
- [ ] 发生异常时优先停止 DNS 切换；不要在事故中销毁 LB 或证书资源。

### 明确不在本次范围

- Cloud Armor、Cloud CDN、IAP。
- 多地域 Cloud Run、Cloud SQL regional HA。
- IPv6。
- 根域 `answer-x.ai` 或 Admin UI 域名迁移。
- 第三方 CDN/反向代理。
- 产品代码、数据库 schema、租户权限逻辑。

## 1. 固定命名与负责人

| 项目 | 值 | 执行者 |
|---|---|---|
| 正式域名 | `platform.answer-x.ai` | GoDaddy + GCP |
| Canary 域名 | `platform-canary.answer-x.ai` | GoDaddy + GCP |
| Cloud Run service | `geo-saas-web` | Terraform |
| Region | `us-central1` | Terraform |
| Global IP | `answerx-platform-ip` | Terraform |
| Serverless NEG | `answerx-platform-web-neg` | Terraform |
| Backend service | `answerx-platform-web-backend` | Terraform |
| URL map | `answerx-platform-url-map` | Terraform |
| HTTPS proxy | `answerx-platform-https-proxy` | Terraform |
| HTTP proxy | `answerx-platform-http-proxy` | Terraform |
| Certificate map | `answerx-platform-cert-map` | Terraform |
| DNS 记录 | GoDaddy | 用户或经用户授权的浏览器操作 |
| OAuth origins | Google Auth Platform/Credentials | 用户或经用户授权的浏览器操作 |

## 2. Task 1 — 变更前基线与 Go/No-Go

**Files:**

- Read: `geo_saas/terraform/main.tf`
- Read: `geo_saas/terraform/variables.tf`
- Read: `geo_saas/terraform/terraform.tfvars`
- Read: `geo_saas/web/nginx.conf`
- Read: `geo_saas/web/entrypoint.sh`
- Read: `geo_saas/web/src/lib/api/_base.ts`

### Step 1.1：固定本地执行上下文

- [ ] 在新终端设置：

```bash
export PROJECT_ID="project-90d7849c-de16-4c15-a0a"
export REGION="us-central1"
export SERVICE="geo-saas-web"
export TF_DIR="/Users/lancelot/Desktop/GEO_Demo/geo_saas/terraform"
gcloud config set project "$PROJECT_ID"
```

Expected: 当前 project 为 `project-90d7849c-de16-4c15-a0a`。

- [ ] 核对 CLI 与 ADC：

```bash
gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud config get-value account
gcloud auth application-default print-access-token >/dev/null
```

Expected: 前两条均为 `lancelot.chen@answer-x.ai`；ADC 命令退出码 0，终端不打印 token。

### Step 1.2：保存 Cloud Run 与 Terraform 基线

- [ ] 保存只读证据到 `/tmp`：

```bash
gcloud run services describe "$SERVICE" \
  --region="$REGION" \
  --format=export > /tmp/geo-saas-web-before-domain.yaml

terraform -chdir="$TF_DIR" state list > /tmp/geo-saas-terraform-state-before-domain.txt
```

- [ ] 确认旧 URL：

```bash
gcloud run services describe "$SERVICE" \
  --region="$REGION" \
  --format='yaml(metadata.annotations,status.url,status.address.url,status.address.audiences)'
```

Expected: 输出包含当前 `run.app` URL，且 ingress 仍为 `all`。

- [ ] 连续验证两个旧入口：

```bash
for url in \
  "https://geo-saas-web-414105678919.us-central1.run.app/health" \
  "https://geo-saas-web-uj5wohdjgq-uc.a.run.app/health"; do
  curl --fail --silent --show-error "$url"
done
```

Expected: 两次均输出 `ok`。

### Step 1.3：记录 30 天运行基线

- [ ] 查询 request/response byte 和状态码基线，保存查询结果：

```bash
SINCE_30D="$(date -u -v-30d '+%Y-%m-%dT%H:%M:%SZ')"
gcloud logging read \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"geo-saas-web\" AND timestamp>=\"${SINCE_30D}\"" \
  --limit=50000 \
  --format=json > /tmp/geo-saas-web-30d-requests.json
```

- [ ] 记录已核实的当前基线：request 约 69.7 MiB、response 约 295 MiB、2xx 28,658、4xx 1,589、5xx 210。实施当天重新计算，旧数字只作比较，不替代实时数据。

### Step 1.4：权限与外部依赖检查

- [ ] 确认可以管理：Compute Load Balancer、Certificate Manager、Service Usage。
- [ ] 确认拥有 GoDaddy `answer-x.ai` DNS 编辑权限。
- [ ] 确认拥有当前 Google OAuth Web Client 的编辑权限。
- [ ] 确认 `platform.answer-x.ai` 和 `platform-canary.answer-x.ai` 没有现存 A/AAAA/CNAME 冲突。

```bash
dig +short platform.answer-x.ai A
dig +short platform.answer-x.ai AAAA
dig +short platform.answer-x.ai CNAME
dig +short platform-canary.answer-x.ai A
```

Expected: 当前均为空。若存在任何记录，停止并确认记录归属，不覆盖。

### Task 1 Gate

- [ ] 只有账号、权限、旧 URL、DNS 所有权和 Terraform state 都确认后才进入 Task 2。

## 3. Task 2 — 先准备 OAuth 与 CORS，不创建 LB

此任务单独执行，避免把 API revision 更新和网络资源首次创建混在同一个 apply 中。

**Files:**

- Modify: `geo_saas/terraform/terraform.tfvars`（本地忽略文件，不提交，不打印 secret）
- Modify: `geo_saas/terraform/terraform.tfvars.example`

### Step 2.1：Google OAuth Web Client

- [ ] 在 Google Auth Platform / Credentials 找到 SaaS 当前使用的 Web application client。
- [ ] 保留所有现有 Authorized JavaScript origins。
- [ ] 添加：

```text
https://platform-canary.answer-x.ai
https://platform.answer-x.ai
```

- [ ] 检查 OAuth consent screen 的 Authorized domains 中包含 `answer-x.ai`；若不存在则添加。
- [ ] 当前前端使用 `@react-oauth/google` callback，不新增 redirect URI；不要猜测或添加路径型 redirect URI。

### Step 2.2：CORS allowlist

- [ ] 在真实 `terraform.tfvars` 的 `allowed_origins` 末尾追加两个 HTTPS origin，保留现有 `run.app` 和 localhost 值。
- [ ] 在 `terraform.tfvars.example` 增加安全示例，不写真实 secret：

```hcl
allowed_origins = "http://localhost:5173,https://platform-canary.example.com,https://platform.example.com"
```

### Step 2.3：只计划 CORS 更新

- [ ] 运行：

```bash
terraform -chdir="$TF_DIR" init -input=false
terraform -chdir="$TF_DIR" fmt -check
terraform -chdir="$TF_DIR" validate
terraform -chdir="$TF_DIR" plan -out=/tmp/geo-saas-cors.tfplan
terraform -chdir="$TF_DIR" show -no-color /tmp/geo-saas-cors.tfplan
```

Expected: 只允许 `geo-saas-api` 的 `ALLOWED_ORIGINS` 环境变量发生 in-place update，并生成一个新 API revision；不得替换服务、修改镜像、数据库、scaling 或 IAM。若出现额外变更，停止。

### Step 2.4：应用并验证旧入口

- [ ] 用户审阅 saved plan 后执行：

```bash
terraform -chdir="$TF_DIR" apply /tmp/geo-saas-cors.tfplan
```

- [ ] 重复 Task 1 的两个旧 URL `/health` 检查，并用旧 URL完成一次 Google 登录。

### Task 2 Rollback

- [ ] 若 API revision 异常，将 `allowed_origins` 恢复为原值，重新 `plan`、审阅、`apply`；OAuth 新增 origin 可以保留，不影响旧入口。

## 4. Task 3 — 编写自定义域名 Terraform

**Files:**

- Create: `geo_saas/terraform/domain.tf`
- Modify: `geo_saas/terraform/variables.tf`
- Modify: `geo_saas/terraform/terraform.tfvars.example`
- Modify: `geo_saas/terraform/terraform.tfvars`（仅域名和日志采样率）
- Modify: `geo_saas/terraform/main.tf`（只在现有 provider/resource 依赖确有需要时；默认不改 Cloud Run）

### Step 3.1：新增变量

- [ ] 在 `variables.tf` 新增：

```hcl
variable "platform_domain" {
  description = "Production custom domain for GEO SaaS Web"
  type        = string
  default     = "platform.answer-x.ai"
}

variable "platform_canary_domain" {
  description = "Canary custom domain used before production DNS cutover"
  type        = string
  default     = "platform-canary.answer-x.ai"
}

variable "lb_log_sample_rate" {
  description = "External Application Load Balancer log sampling rate"
  type        = number
  default     = 1.0

  validation {
    condition     = var.lb_log_sample_rate >= 0 && var.lb_log_sample_rate <= 1
    error_message = "lb_log_sample_rate must be between 0 and 1."
  }
}
```

- [ ] `terraform.tfvars.example` 使用相同正式/canary 名称作为部署示例；真实 tfvars 不包含新的 secret。

### Step 3.2：启用 API，且 destroy 不反向禁用

- [ ] 在 `domain.tf` 创建：

```hcl
resource "google_project_service" "compute" {
  project            = var.project_id
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "certificate_manager" {
  project            = var.project_id
  service            = "certificatemanager.googleapis.com"
  disable_on_destroy = false
}
```

### Step 3.3：Global IP、Serverless NEG、Backend

- [ ] 创建 `google_compute_global_address.answerx_platform`，名称 `answerx-platform-ip`，IPv4。
- [ ] 创建 `google_compute_region_network_endpoint_group.answerx_platform_web`：
  - region：`var.region`
  - `network_endpoint_type = "SERVERLESS"`
  - `cloud_run.service = google_cloud_run_v2_service.geo_saas_web.name`
  - 显式依赖 Compute API。
- [ ] 创建 `google_compute_backend_service.answerx_platform_web`：
  - `load_balancing_scheme = "EXTERNAL_MANAGED"`
  - `protocol = "HTTP"`
  - `timeout_sec = 300`
  - backend group 指向 Serverless NEG id
  - `log_config.enable = true`
  - `log_config.sample_rate = var.lb_log_sample_rate`
  - 不配置 health check。

300 秒必须与 Nginx `/api/agent/` 当前 `proxy_read_timeout 300s` 对齐，避免 LB 比 Web proxy 更早切断 Anthony SSE。若未来要支持超过 300 秒的单连接，需同时评估 LB、Nginx、Cloud Run 和 Agent，不在本次单独提高。

### Step 3.4：URL maps 与 HTTP→HTTPS

- [ ] 创建 `google_compute_url_map.answerx_platform`，default service 指向 backend service。
- [ ] 创建 `google_compute_url_map.answerx_platform_http_redirect`：

```hcl
default_url_redirect {
  https_redirect         = true
  strip_query            = false
  redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
}
```

### Step 3.5：TLS policy 与 Certificate Manager

- [ ] 创建 `google_compute_ssl_policy.answerx_platform`：
  - `profile = "MODERN"`
  - `min_tls_version = "TLS_1_2"`
- [ ] 分别创建 production/canary `google_certificate_manager_dns_authorization`。
- [ ] 分别创建 production/canary `google_certificate_manager_certificate`：
  - `managed.domains` 只包含对应 FQDN
  - `managed.dns_authorizations` 指向对应 authorization id
- [ ] 创建一个 `google_certificate_manager_certificate_map.answerx_platform`。
- [ ] 创建两个 map entry，hostname 分别为 production/canary，并指向各自 certificate。

### Step 3.6：Target proxies 与 Forwarding rules

- [ ] 创建 HTTPS proxy：URL map + SSL policy + certificate map。
- [ ] certificate map 引用使用 Certificate Manager 完整资源路径；不要把 Certificate Manager certificate 错当成 Compute SSL certificate。
- [ ] 创建 HTTP proxy 指向 redirect URL map。
- [ ] 创建两个 global forwarding rule：
  - HTTPS：同一 global address，TCP 443，`EXTERNAL_MANAGED`
  - HTTP：同一 global address，TCP 80，`EXTERNAL_MANAGED`

### Step 3.7：Outputs

- [ ] 输出以下非敏感值：

```text
platform_global_ip
platform_domain
platform_canary_domain
platform_dns_authorization_record
platform_canary_dns_authorization_record
```

DNS authorization record output 必须包含 `name`、`type`、`data`，避免人工转抄时猜测 `_acme-challenge` hostname。

### Step 3.8：静态验证

- [ ] 运行：

```bash
terraform -chdir="$TF_DIR" fmt
terraform -chdir="$TF_DIR" fmt -check
terraform -chdir="$TF_DIR" validate
terraform -chdir="$TF_DIR" providers
```

- [ ] 若当前 Google provider 不认识某资源或字段，先查官方 provider 文档，做最小版本升级并审阅 `.terraform.lock.hcl`；不得盲目升级到未经测试的大版本。

## 5. Task 4 — Terraform Plan 安全审阅

### Step 4.1：生成 saved plan

- [ ] 运行：

```bash
terraform -chdir="$TF_DIR" plan -out=/tmp/platform-domain-infra.tfplan
terraform -chdir="$TF_DIR" show -no-color /tmp/platform-domain-infra.tfplan \
  > /tmp/platform-domain-infra.plan.txt
sed -n '1,260p' /tmp/platform-domain-infra.plan.txt
```

### Step 4.2：逐项核对

- [ ] Plan 只能新增以下类别：2 个 project services（若 Compute 已在 state 外启用，可能无远端变化）、1 global address、1 NEG、1 backend、2 URL maps、1 SSL policy、2 DNS auth、2 cert、1 cert map、2 entries、2 proxies、2 forwarding rules、outputs。
- [ ] `google_cloud_run_v2_service.geo_saas_web` 不得 replace/delete。
- [ ] `geo-saas-api`、Artifact Registry、IAM 不得变化。
- [ ] 不得修改 image、Cloud SQL connection、scaling、service account 或 environment variables。
- [ ] Terraform summary 不得包含 destroy。

Expected: 仅 additive infrastructure changes。

### Step 4.3：应用

- [ ] 用户确认 plan 文本后执行：

```bash
terraform -chdir="$TF_DIR" apply /tmp/platform-domain-infra.tfplan
```

- [ ] 立即读取输出：

```bash
terraform -chdir="$TF_DIR" output platform_global_ip
terraform -chdir="$TF_DIR" output -json platform_dns_authorization_record
terraform -chdir="$TF_DIR" output -json platform_canary_dns_authorization_record
```

- [ ] 将输出保存到受控的变更记录；它们不包含私钥或 token。

### Task 4 Gate

- [ ] 此时不要添加正式或 canary A 记录。先完成 DNS authorization CNAME。

## 6. Task 5 — GoDaddy 证书授权 CNAME

### Step 5.1：添加两条 CNAME

- [ ] 在 GoDaddy DNS 中，严格按 Terraform output 添加 production CNAME。
- [ ] 严格按 Terraform output 添加 canary CNAME。
- [ ] TTL 设置为 600 秒或 GoDaddy 可选的最小安全值。
- [ ] 不手工拼接 `_acme-challenge`；不同授权模式返回的 hostname 可能不同。
- [ ] 不删除这两条记录，上线后证书续期仍需要它们。

### Step 5.2：验证权威与公共 DNS

- [ ] 使用输出的 record name 执行：

```bash
dig @ns45.domaincontrol.com +short "$(terraform -chdir="$TF_DIR" output -json platform_dns_authorization_record | jq -r .name)" CNAME
dig @8.8.8.8 +short "$(terraform -chdir="$TF_DIR" output -json platform_dns_authorization_record | jq -r .name)" CNAME
dig @1.1.1.1 +short "$(terraform -chdir="$TF_DIR" output -json platform_canary_dns_authorization_record | jq -r .name)" CNAME
```

Expected: 返回值与 output 的 `data` 一致。

### Step 5.3：等待证书 ACTIVE

- [ ] 每 5–10 分钟查看一次，最多等待数小时；不要用阻塞脚本连续轮询：

```bash
gcloud certificate-manager certificates describe answerx-platform-cert \
  --location=global \
  --format='yaml(managed.state,managed.authorizationAttemptInfo,expireTime)'

gcloud certificate-manager certificates describe answerx-platform-canary-cert \
  --location=global \
  --format='yaml(managed.state,managed.authorizationAttemptInfo,expireTime)'
```

Expected: 两张均 `managed.state: ACTIVE`，每个 domain authorization 为 authorized。

### Task 5 Rollback / Troubleshooting

- [ ] 若数小时后不是 ACTIVE：核对 CNAME name/data、是否有同名冲突、公共 DNS 是否可解析、Certificate Manager API 和 certificate event；不要添加 A 记录碰运气。
- [ ] 若 CNAME 配错，修正 CNAME。无需重建 Cloud Run 或 LB。

## 7. Task 6 — 正式 DNS 前的负载均衡验证

### Step 6.1：检查 GCP 组件

- [ ] 运行：

```bash
gcloud compute addresses describe answerx-platform-ip --global
gcloud compute network-endpoint-groups describe answerx-platform-web-neg --region="$REGION"
gcloud compute backend-services describe answerx-platform-web-backend --global
gcloud compute url-maps describe answerx-platform-url-map
gcloud compute forwarding-rules describe answerx-platform-https-fr --global
gcloud compute forwarding-rules describe answerx-platform-http-fr --global
gcloud certificate-manager maps entries list --map=answerx-platform-cert-map --location=global
```

Expected: IP/NEG/backend/proxies/rules 均存在；NEG 指向 `geo-saas-web`；端口为 80/443。

### Step 6.2：使用 curl --resolve 绕过公共 A 记录

- [ ] 设置 IP：

```bash
GLOBAL_IP="$(terraform -chdir="$TF_DIR" output -raw platform_global_ip)"
```

- [ ] 验证 production hostname 的 TLS 和 Web health：

```bash
curl --fail --silent --show-error \
  --resolve "platform.answer-x.ai:443:${GLOBAL_IP}" \
  "https://platform.answer-x.ai/health"
```

Expected: `ok`，证书 hostname 校验通过。

- [ ] 验证 canary：

```bash
curl --fail --silent --show-error \
  --resolve "platform-canary.answer-x.ai:443:${GLOBAL_IP}" \
  "https://platform-canary.answer-x.ai/health"
```

- [ ] 验证 HTTP 重定向：

```bash
curl --head \
  --resolve "platform.answer-x.ai:80:${GLOBAL_IP}" \
  "http://platform.answer-x.ai/health"
```

Expected: 301，`Location` 为 `https://platform.answer-x.ai/health`，query string 不丢失。

### Step 6.3：验证 SPA 与代理链路

- [ ] 使用 `--resolve` 或临时本机 hosts 打开 Login 页面和一个深层 SPA route，刷新后仍返回应用而非 404。
- [ ] 验证 `/api` 由 Web Nginx 代理到 SaaS API。
- [ ] 验证 `/api/agent` 由 Web Nginx 代理到 Agent。
- [ ] 检查后端 redirect 的 Location 使用 `platform.answer-x.ai`，不泄漏内部 run.app hostname。
- [ ] 再次检查两个旧 run.app `/health`，Expected 仍为 200。

### Task 6 Gate

- [ ] 任何 `--resolve` TLS、health、SPA 或代理失败都阻断 canary A 记录。

## 8. Task 7 — Canary DNS 与中国大陆验证

### Step 7.1：发布 canary

- [ ] 在 GoDaddy 添加：

```text
Type: A
Host: platform-canary
Value: terraform output -raw platform_global_ip 的真实输出值
TTL: 300
```

- [ ] 不添加 AAAA。
- [ ] 等待公共解析：

```bash
dig @8.8.8.8 +short platform-canary.answer-x.ai A
dig @1.1.1.1 +short platform-canary.answer-x.ai A
curl --fail --silent --show-error https://platform-canary.answer-x.ai/health
```

Expected: 两个 resolver 返回同一 global IP，health 输出 `ok`。

### Step 7.2：全球功能验收

- [ ] Google 登录成功。
- [ ] Workspace 列表和租户选择正确。
- [ ] Overview、Visibility、Citation、Sentiment、Prompt、Reports 加载。
- [ ] 图表、静态资源、字体正常。
- [ ] 任一 SPA 深层 URL 直接打开和刷新正常。
- [ ] Anthony Chat SSE 能开始、持续输出并正常结束。
- [ ] 内容生成的长请求不在 60/300 秒边界被 LB 提前断开。
- [ ] 上传、下载和 HTML report view 正常。
- [ ] Browser Console 无 CORS、mixed content、OAuth origin、redirect URI 或 CSP 错误。
- [ ] 旧 run.app 登录与核心页面仍正常。

### Step 7.3：中国大陆三网验证

- [ ] 使用不连接 VPN 的中国电信真实网络测试。
- [ ] 使用不连接 VPN 的中国联通真实网络测试。
- [ ] 使用不连接 VPN 的中国移动真实网络测试。
- [ ] 每类网络至少测试：DNS、TLS、登录、Dashboard、图表、SSE、文章生成、上传/下载。
- [ ] 分别在工作日白天和晚高峰测试一次。
- [ ] 连续观察 48–72 小时。

验收要求：

- DNS 能解析到 global IP。
- TLS 无证书或 SNI 错误。
- 不需要 VPN 才能建立连接。
- 20 次 `/health` 探测全部成功。
- 核心人工流程全部成功。
- LB 5xx 比率不高于 1%，且没有连续 5 分钟每分钟超过 3 个新增 5xx 的迁移相关突发。
- p95 首屏/API 延迟不高于旧 URL 同时段基线的 125%。
- SSE 不出现可复现的中途断流。

### Step 7.4：Canary 监控命令

- [ ] LB 日志：

```bash
gcloud logging read \
  'resource.type="http_load_balancer" AND httpRequest.requestUrl:"platform-canary.answer-x.ai"' \
  --freshness=2h \
  --limit=200 \
  --format='table(timestamp,httpRequest.status,httpRequest.requestMethod,httpRequest.requestUrl,httpRequest.latency)'
```

- [ ] Cloud Run 后端日志：

```bash
SINCE_2H="$(date -u -v-2H '+%Y-%m-%dT%H:%M:%SZ')"
gcloud logging read \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"geo-saas-web\" AND timestamp>=\"${SINCE_2H}\"" \
  --limit=200 \
  --format='table(timestamp,httpRequest.status,httpRequest.requestMethod,httpRequest.requestUrl,httpRequest.latency)'
```

### Task 7 Rollback

- [ ] Canary 失败时只删除 `platform-canary` A 记录，保留 LB、global IP、DNS authorization CNAME 和证书用于排障。
- [ ] 旧 run.app 入口不受影响。
- [ ] 未满足全部验收时禁止进入正式切换。

## 9. Task 8 — 正式域名切换

### Step 8.1：切换前 30 分钟冻结

- [ ] 暂停 SaaS Web/API/Agent 镜像发布和无关 Terraform apply。
- [ ] 再次确认 production certificate `ACTIVE`。
- [ ] 再次执行 production `curl --resolve`。
- [ ] 再次确认 OAuth origin 和 CORS 中存在正式域名。
- [ ] 再次确认两个 run.app `/health` 返回 200。
- [ ] 导出当前 Terraform state list 和 LB describe 到 `/tmp`。
- [ ] 准备面向内部团队的旧 URL 应急入口说明。

### Step 8.2：添加正式 A 记录

- [ ] 在 GoDaddy 添加：

```text
Type: A
Host: platform
Value: 与 canary 相同的 terraform output -raw platform_global_ip 真实输出值
TTL: 300
```

- [ ] 不删除证书验证 CNAME。
- [ ] 不创建 CNAME 指向 `run.app`；Cloud Run 默认 hostname 不能作为任意自定义 Host 的透明别名。

### Step 8.3：DNS/TLS 验证

- [ ] 运行：

```bash
dig @ns45.domaincontrol.com +short platform.answer-x.ai A
dig @8.8.8.8 +short platform.answer-x.ai A
dig @1.1.1.1 +short platform.answer-x.ai A
curl --fail --silent --show-error https://platform.answer-x.ai/health
curl --head http://platform.answer-x.ai/health
openssl s_client -connect platform.answer-x.ai:443 -servername platform.answer-x.ai </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

Expected:

- 权威和公共 resolver 返回 global IP。
- HTTPS 输出 `ok`。
- HTTP 重定向到 HTTPS。
- SAN 包含 `platform.answer-x.ai`，证书未过期。

### Step 8.4：正式功能验证

- [ ] 重复 canary 的完整功能清单。
- [ ] 重点检查 OAuth 登录、租户隔离、API mutation、Agent SSE、生成文章和报告下载。
- [ ] 使用中国大陆三网至少各复测一次关键链路。
- [ ] 同时验证旧 `run.app` URL 仍可登录、访问 `/health` 和核心页面。

### Step 8.5：观察窗口

- [ ] 上线后前 2 小时持续看 LB/Cloud Run 4xx、5xx、latency、SSE 中断。
- [ ] 24 小时复核一次。
- [ ] 72 小时复核一次。
- [ ] 7 天稳定后关闭变更窗口。

## 10. Task 9 — 回滚矩阵与演练

### 10.1 不同阶段的回滚动作

| 阶段 | 故障 | 回滚动作 | 旧 run.app |
|---|---|---|---|
| A 记录前 | 证书/TF/LB 失败 | 不添加 A；修复新资源 | 始终可用 |
| Canary | 大陆不可达/功能失败 | 删除 canary A，保留证书和 LB | 始终可用 |
| 正式切换 | DNS/TLS/LB 严重失败 | 删除正式 A；通知用户暂时使用旧 URL | 始终可用 |
| OAuth | 新域名登录失败 | 修复 Authorized origin；旧 URL 登录继续 | 始终可用 |
| CORS | API 被浏览器阻断 | 修复 allowlist，reviewed Terraform apply | 始终可用 |
| 错误收紧 ingress | run.app 被拒绝 | 紧急恢复 ingress `all`，再回写 Terraform | 恢复后可用 |
| 错误禁用 default URL | run.app 消失 | 重新启用 default URL | 恢复后可用 |

### 10.2 必须理解的回滚限制

- [ ] 当前 `platform.answer-x.ai` 没有旧系统目标，因此“删除正式 A”会让自定义域名暂时不可解析，并不会自动跳回 Cloud Run URL。
- [ ] DNS cache 使回滚最多延迟到 TTL/运营商缓存过期。
- [ ] 旧 `run.app` 是独立的应急入口，而不是 `platform.answer-x.ai` 的自动后备。
- [ ] 不把 `platform` CNAME 到 `run.app`，因为证书和 Host routing 不匹配。
- [ ] 事故中不删除 global IP、certificate CNAME 或 LB；删除会增加恢复时间并可能导致 IP 变化。

### 10.3 紧急恢复命令（仅当错误配置确实发生）

- [ ] 恢复 Web ingress：

```bash
gcloud run services update geo-saas-web \
  --region=us-central1 \
  --ingress=all
```

- [ ] 恢复 default URL：

```bash
gcloud run services update geo-saas-web \
  --region=us-central1 \
  --default-url
```

这些命令会产生 Terraform drift，只用于事故恢复。恢复后必须把 Terraform 配置调整为真实期望值并执行 reviewed plan，不能长期保留 drift。

### 10.4 回滚演练

- [ ] 在 canary 阶段实际演练一次：删除 canary A → 确认 canary 解析消失 → 确认旧 run.app 正常 → 恢复 canary A → 确认恢复。
- [ ] 记录 GoDaddy 实际传播耗时，作为正式切换的真实 rollback time estimate。

## 11. Task 10 — 监控、成本与上线记录

### Step 11.1：成本预估

- [ ] 记录增量固定成本：项目内前 5 条 global forwarding rules 合计 `$0.025/小时`，约 `$18.25/月`。HTTP/HTTPS 两条仍在该档位。
- [ ] 记录流量成本：`us-central1` inbound 与 outbound 各 `$0.008/GiB`。
- [ ] 按最近 30 天约 0.356 GiB 总 LB data processing，预计约 `$0.003/月`；正式账单以 Billing export 为准。
- [ ] 记录 internet data transfer out 另计，但当前 response 约 0.288 GiB/月，量级很小。
- [ ] 记录 Certificate Manager 两张证书在项目最初 100 张免费额度内。
- [ ] Cloud Armor/CDN 第一阶段为 disabled，费用为 0。

### Step 11.2：监控与告警

- [ ] 为 `platform.answer-x.ai/health` 创建独立外部 uptime check；若 GCP synthetic monitor 依赖 default URL，保留 default URL。
- [ ] 为 LB 5xx rate、p95 latency 建立 dashboard/alert。
- [ ] 为证书到期时间和 managed state 建立定期检查。
- [ ] 为 global forwarding rule 数量建立月度成本复核，避免额外规则超过前 5 条档位。
- [ ] 初始 7 天 `lb_log_sample_rate=1.0`；稳定后可通过 reviewed Terraform plan 降至 `0.1`，但不能在上线窗口同时调整。

### Step 11.3：变更记录

- [ ] 记录 Terraform apply 时间、plan 文件摘要和资源列表。
- [ ] 记录两条 CNAME、canary A、production A 的 GoDaddy 变更时间和 TTL。
- [ ] 记录 OAuth origin 变更。
- [ ] 记录中国大陆三网测试人、时间、网络、结果。
- [ ] 记录 2h/24h/72h/7d 观察结果。

## 12. Task 11 — 7 天后的安全决策

### 选项 A：继续保留旧 URL（当前推荐）

- [ ] 保持 `geo-saas-web` ingress 为 `all`。
- [ ] 保持 default URL enabled。
- [ ] 优点：随时可通过旧 URL应急。
- [ ] 风险：外部请求可以绕过 LB；未来启用 Cloud Armor 时这一点尤其重要。

### 选项 B：强制所有公网流量走 LB

- [ ] 只有在用户明确批准失去公网 run.app 回退后才执行。
- [ ] 在 Terraform 中为 `geo-saas-web` 显式设置 `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER` 或等价 provider 值。
- [ ] `terraform plan` 只允许 Web service ingress 更新，不改变镜像或其他配置。
- [ ] apply 后验证 `platform` 正常且公网 run.app 被拒绝。
- [ ] 保留 `default_uri_disabled = false`，因为内部 Google 服务仍可能使用默认 URI。

这一步是独立安全变更，不属于域名“切换成功”的必要条件。

## 13. 最终验收清单

### 基础设施

- [ ] Global IP 为 RESERVED/IN_USE，且与两条 forwarding rule 一致。
- [ ] HTTPS 443 与 HTTP 80 均可访问。
- [ ] HTTP 永久重定向到 HTTPS，保留 path/query。
- [ ] Serverless NEG 指向 `us-central1/geo-saas-web`。
- [ ] Backend timeout 300 秒，日志启用。
- [ ] 两张 certificate 为 ACTIVE，CNAME 保留。
- [ ] Terraform state 包含全部新资源，无 Console-only drift。

### 应用

- [ ] `https://platform.answer-x.ai/health` 返回 200 `ok`。
- [ ] Google OAuth 登录正常。
- [ ] SPA deep link 与刷新正常。
- [ ] `/api` 与 `/api/agent` 代理正常。
- [ ] Dashboard、图表、报告、上传/下载正常。
- [ ] Anthony SSE 长连接正常。
- [ ] 租户身份和数据隔离行为未变化。

### 连续性

- [ ] 两个现有 run.app `/health` 仍返回 200。
- [ ] 旧 URL 登录与核心路径仍可用。
- [ ] 已完成 canary DNS 回滚演练。
- [ ] 2h/24h/72h 观察没有迁移引入的异常。

### 中国大陆

- [ ] 电信、联通、移动均无需 VPN 完成关键路径。
- [ ] 48–72 小时 canary 验证完成。
- [ ] 若任何运营商持续失败，正式切换必须保持 No-Go。

## 14. 完成后的资源状态

完成后应形成以下稳定状态：

```text
platform.answer-x.ai          A      terraform output platform_global_ip
platform-canary.answer-x.ai   A      同一个 platform_global_ip
production auth hostname      CNAME  production authorization output data
canary auth hostname          CNAME  canary authorization output data

HTTPS :443 -> certificate map -> URL map -> backend -> serverless NEG -> geo-saas-web
HTTP  :80  -> HTTPS redirect
run.app URLs -> geo-saas-web (仍可直接访问)
```

Canary A 可在 7 天稳定后删除；对应 certificate/map entry 是否删除应通过 Terraform 单独计划。证书授权 CNAME 只有在对应证书资源也永久移除后才能删除。

## 15. 官方参考

- [Set up a global external Application Load Balancer with Cloud Run](https://docs.cloud.google.com/load-balancing/docs/https/setup-global-ext-https-serverless)
- [Certificate Manager domain authorization](https://docs.cloud.google.com/certificate-manager/docs/domain-authorization)
- [Deploy a global Google-managed certificate with DNS authorization](https://docs.cloud.google.com/certificate-manager/docs/deploy-google-managed-dns-auth)
- [Cloud Run ingress and default URL](https://docs.cloud.google.com/run/docs/securing/ingress)
- [Cloud Load Balancing pricing](https://cloud.google.com/load-balancing/pricing)
- [Certificate Manager pricing](https://cloud.google.com/certificate-manager/pricing)
- [Google Identity Web Client origins](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid)
