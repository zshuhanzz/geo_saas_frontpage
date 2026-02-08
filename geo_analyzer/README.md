# GEO Analyzer

GEO Analyzer 是一个基于 Cloud Run Job 的批处理分析引擎。它负责从 `geo_results` 表中提取非结构化的 AI 回答数据，通过规则解析和 NLP 技术，转换为结构化的分析数据（如公司提及、引用来源等），供 Admin 后台展示和 BI 分析。

## 🚀 快速开始 (Quick Start)

### 1. 环境准备

确保您的系统已安装 Python 3.11+。

```bash
# 进入项目目录
cd geo_analyzer

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
*   `DATABASE_URL`: PostgreSQL 连接字符串 (Cloud SQL)
*   `DB_INSTANCE_CONNECTION_NAME`: Cloud SQL 实例连接名
*   `DB_USER`: 数据库用户名
*   `DB_PASS`: 数据库密码
*   `DB_NAME`: 数据库名称

### 3. 本地运行

Analyzer 设计为 Job 运行，一次性处理所有待分析的任务。

```bash
# 运行分析任务
python main.py
```

### 4. 运行测试

```bash
# 运行单元测试
pytest tests/
```

---

## 🏗️ 系统架构 (System Architecture)

### 核心流程

1.  **输入 (Input)**: 读取 `geo_results` 表中 `analyzed_at IS NULL` 的记录。
2.  **处理 (Process)**:
    *   **提取**: 解析 `cloro_response` JSON 中的 `sources`, `entities`, `citation_pills` 等字段。
    *   **转换**: 将提取的数据转换为结构化的 `CompanyMention` 和 `Citation` 对象。
    *   **清洗**: 规范化公司名称，分类域名类型 (Owned/Earned)。
3.  **输出 (Output)**:
    *   写入 `geo_company_mentions` 表。
    *   写入 `geo_citations` 表。
    *   更新 `geo_results.analyzed_at` 时间戳。
4.  **状态更新**: 若某 Report 下的所有 Result 都已分析，更新 `geo_reports.status = 'completed'`。

### 5. 分批处理 & 断点续传 (Batch Processing & Resume)

Analyzer 针对大规模数据（如 10w+ Results）进行了深度优化：

1.  **分批循环 (Batch Loop)**:
    *   主进程采用 `while True` 循环。
    *   每次仅从 DB 读取 **100 条** 未分析记录 (`LIMIT 100`)。
2.  **原子提交 (Atomic Commit)**:
    *   每处理完 100 条数据，立即执行 `conn.commit()`。
    *   确保即使 Job 在第 N 批超时被杀，前 N-1 批的数据已安全入库。
3.  **自动续传 (Auto Resume)**:
    *   Job 启动时查询 `analyzed_at IS NULL`。
    *   天然支持断点续传，无需人工干预。
4.  **智能状态管理**:
    *   仅当所有 Results 都被标记为已分析后，Report 状态才更新为 `completed`。

### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                       GEO Analyzer                          │
│                     (Cloud Run Job)                         │
└─────────────────────────────┬───────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │    Batch Reader   │
                    │ (Read Unanalyzed) │
                    └─────────┬─────────┘
                              │ items
                              ▼
                    ┌───────────────────┐
                    │   Core Analyzer   │
                    │ (Parse & Extract) │
                    └─────────┬─────────┘
                              │ models
            ┌─────────────────┴──────────────────┐
            ▼                                    ▼
┌───────────────────────┐            ┌───────────────────────┐
│ geo_company_mentions  │            │     geo_citations     │
│ (Brand Visibility)    │            │   (Source Analysis)   │
└───────────────────────┘            └───────────────────────┘
```

---

## 💾 数据库 Schema (输出)

### 1. geo_company_mentions (公司提及)
| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `report_id` | UUID | 关联报告 |
| `company_name` | VARCHAR | 公司/品牌名称 |
| `mention_position` | INT | 提及排名 (1=首位) |
| `is_client` | BOOL |是否为客户品牌 |
| `is_peer` | BOOL | 是否为竞品 |

### 2. geo_citations (引用来源)
| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `report_id` | UUID | 关联报告 |
| `source_url` | TEXT | 引用链接 |
| `source_domain` | VARCHAR | 域名 |
| `domain_category` | VARCHAR | 域名分类 (Owned/Earned) |
| `is_citation_pill` | BOOL | 是否为高优引用源 |

---

## ☁️ 部署 (Deployment)

使用 Cloud Run Job 部署，需配置 VPC Connector 以连接 Cloud SQL。

```bash
# 构建镜像
gcloud builds submit --tag us-central1-docker.pkg.dev/$PROJECT_ID/geo-analyzer-repo/geo-analyzer:v5 .

# Terraform 部署
cd terraform
terraform apply
```
