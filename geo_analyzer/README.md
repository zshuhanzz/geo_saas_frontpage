# GEO Analyzer

GEO Analyzer 是一个基于 Cloud Run Job 的批处理分析引擎。它按客户 (`CLIENT_ID`) 从 `geo_results` 表中读取未分析的 AI 回答数据，通过规则解析和 NLP 技术，提取结构化的分析数据（品牌提及、产品提及、引用来源、情感），供 SaaS 前端 Insights 页面 + Agent 报告展示。

> **当前版本**: v23 (2026-03-08) — v1.2 Dual-Mode Tracking (OEM/ODM) 适配后即将发布 v24

## 🔀 v1.2 Dual-Mode Tracking (OEM/ODM 适配)

Analyzer 的 Parser 架构在 v1.2 重构为三路并行:

| Parser | 职责 | 输出表 |
|---|---|---|
| `BrandParser` | Own + Shadow brand + Peer 的 primary_name + **aliases** 正则匹配（< 3 字符 alias 过滤避免噪音）。**brands 优先去重**（同 term 在 brand + peer 重复时归 brand）| `geo_brand_mentions` (原 `geo_company_mentions` rename) |
| `ProductParser` | `geo_client_topic_products.match_variants` 匹配；`product_role` 来自 product 配置；同时 denormalize owner_brand_id / owner_peer_id 到 mention 行 | `geo_product_mentions` (v1.2 新) |
| `CitationParser` | **两阶段**: (Stage 1) `geo_product_tracked_urls` exact > path-prefix 最长匹配；(Stage 2) `geo_client_domains` whole > path-prefix。miss 则 `citation_role=NULL`，独立 `domain_category` 列做 site-nature 分类 | `geo_citations` (增 12 值 `citation_role` + `matched_product_id` / `matched_brand_id` / `matched_peer_id`) |

详细契约见 [docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md](../docs/superpowers/plans/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md) §3-5。Parser 侧 pytest 共 44/44 绿。

## 🚀 快速开始 (Quick Start)

### 1. 环境准备

确保您的系统已安装 Python 3.11+。

```bash
cd geo_analyzer
python3 -m venv venv && source venv/bin/activate
pip install --no-cache-dir -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下关键信息：
*   `DATABASE_URL`: PostgreSQL 连接字符串 (Cloud SQL)
*   `DB_INSTANCE_CONNECTION_NAME`: Cloud SQL 实例连接名
*   `DB_USER` / `DB_PASS` / `DB_NAME`: 数据库凭证

### 3. 本地运行

Analyzer 设计为 Cloud Run Job，按客户维度一次性处理所有待分析的数据。

```bash
CLIENT_ID=your-client-uuid python main.py
```

---

## 🏗️ 系统架构 (V2.5 SaaS)

### 核心流程

1.  **输入 (Input)**: 读取 `geo_results` 表中该客户 (`client_id`) 下 `analyzed_at IS NULL` 的记录。
2.  **上下文加载**: 从 `geo_client_peers` 加载竞品品牌列表（含别名），从 `geo_client_domains` 加载品牌官网域名列表。
3.  **处理 (Process)**:
    *   **提取 Mentions**: 使用 `company_parser.py` 基于 Peers 列表，用正则提取品牌/公司提及位置及频次，标记 `is_own_brand`。
    *   **提取 Citations**: 使用 `citation_parser.py` 解析 `sources` 和 `citation_pills` 字段，提取 URL 和域名，标记 Owned Domain。
4.  **输出 (Output)**:
    *   写入 `geo_company_mentions` 表。
    *   写入 `geo_citations` 表。
    *   更新 `geo_results.analyzed_at` 时间戳。

### 分批处理 & 断点续传 (Batch Processing & Resume)

Analyzer 针对大规模数据（如 10w+ Results）进行了深度优化：

1.  **分批循环 (Batch Loop)**: 每次仅从 DB 读取 **100 条** 未分析记录 (`LIMIT 100`)。
2.  **原子提交 (Atomic Commit)**: 每处理完 100 条数据，立即执行 `conn.commit()`。
3.  **自动续传 (Auto Resume)**: Job 启动时查询 `analyzed_at IS NULL`，天然支持断点续传。
4.  **智能退出**: 当没有更多未分析记录时自动退出。

### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                       GEO Analyzer V2.5                      │
│                     (Cloud Run Job)                          │
│                  CLIENT_ID=xxx python main.py                │
└─────────────────────────────┬───────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Context Loader  │
                    │  Peers + Domains  │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Batch Reader    │
                    │  (100条/批, Loop) │
                    └─────────┬─────────┘
                              │ results
                              ▼
                    ┌───────────────────┐
                    │   Core Analyzer   │
                    │ company_parser.py │
                    │ citation_parser.py│
                    └─────────┬─────────┘
                              │ output
            ┌─────────────────┴──────────────────┐
            ▼                                    ▼
┌───────────────────────┐            ┌───────────────────────┐
│ geo_company_mentions  │            │    geo_citations      │
│ (Brand Visibility)    │            │  (Source Analysis)    │
└───────────────────────┘            └───────────────────────┘
```

---

## 📂 代码结构

```
geo_analyzer/
├── main.py                     # 入口：批处理循环、上下文加载
├── requirements.txt            # Python 依赖
├── Dockerfile                  # 容器构建
├── terraform/                  # Cloud Run Job 配置
│   ├── main.tf
│   └── terraform.tfvars
└── src/
    ├── core/
    │   ├── config.py           # 环境变量配置 (Pydantic Settings)
    │   └── database.py         # 数据库连接 & ORM 表定义
    └── parsers/
        ├── company_parser.py   # Mentions 提取器 (正则匹配 Peers)
        └── citation_parser.py  # Citations 提取器 (URL/Domain 解析)
```

---

## 💾 数据库 Schema

### 输入表

| 表名 | 说明 |
|------|------|
| `geo_results` | 采集结果 (text, sources, citation_pills) |
| `geo_client_peers` | 客户竞品列表 (primary_name, aliases, is_own_brand) |
| `geo_client_domains` | 客户官网域名列表 |

### 输出表

#### 1. geo_company_mentions (公司提及)
| 列名 | 类型 | 说明 |
|------|------|------|
| `client_prompt_id` | UUID | 关联 Client Prompt |
| `task_id` | UUID | 关联 Task |
| `result_id` | INT | 关联 Result |
| `client_id` | UUID | 客户 ID |
| `company_name` | VARCHAR | 公司/品牌名称 |
| `mention_position` | INT | 提及排名 (1=首位) |
| `is_own_brand` | BOOL | 是否为客户自有品牌 |
| `executed_at` | TIMESTAMP | 采集时间 |

#### 2. geo_citations (引用来源)
| 列名 | 类型 | 说明 |
|------|------|------|
| `client_prompt_id` | UUID | 关联 Client Prompt |
| `task_id` | UUID | 关联 Task (可空) |
| `result_id` | INT | 关联 Result |
| `client_id` | UUID | 客户 ID |
| `source_url` | TEXT | 引用完整链接 |
| `source_domain` | VARCHAR | 域名 (解析出) |
| `source_position` | INT | 引用位置序号 |
| `source_label` | TEXT | 引用标签文本 |
| `is_citation_pill` | BOOL | 是否为高优引用源 |
| `domain_category` | TEXT | 域名分类 (来自 geo_domain_categories 查询) |
| `executed_at` | TIMESTAMP | 采集时间 |

#### 3. geo_domain_categories (域名分类映射)
| 列名 | 类型 | 说明 |
|------|------|------|
| `domain` | TEXT | 域名 (unique) |
| `category` | TEXT | 分类标签 (e.g. Media, E-Commerce, Brand) |

---

## ☁️ 部署 (Deployment)

使用 Cloud Run Job 部署，每个客户由独立的 Cloud Scheduler 触发，通过环境变量 `CLIENT_ID` 指定分析目标。

```bash
# 构建镜像
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/$PROJECT_ID/geo-analyzer-repo/geo-analyzer:v23 .

# Terraform 部署
cd terraform && terraform init && terraform apply
```

运行环境变量：
- `CLIENT_ID`: 必须，指定要分析的客户 UUID（由 Cloud Scheduler 传入）

---
*Last Updated: 2026-03-08*
