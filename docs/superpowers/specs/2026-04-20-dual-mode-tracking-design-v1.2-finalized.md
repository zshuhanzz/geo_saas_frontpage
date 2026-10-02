# Dual-Mode Tracking — Spec v1.2 Finalized

> **日期**:2026-04-20
> **作者**:lancelot × Wentao × Claude
> **基线**:此文档**自包含**,不依赖 v1.0/v1.1。历史演进见附录 E。
> **状态**:**Finalized,进入实施阶段**
> **参考**:
> - v1.0 (2026-04-18):[2026-04-18-dual-mode-tracking-design.md](./2026-04-18-dual-mode-tracking-design.md)
> - v1.1 (2026-04-20 上午):[2026-04-20-dual-mode-tracking-design-v1.1.md](./2026-04-20-dual-mode-tracking-design-v1.1.md)
> - Profound 对标分析:[飞书版](https://www.feishu.cn/docx/Cdbnd3PQRoPTDRxWXyZc9Jjnn1d)
> - 群内纪要:[CPO 机器人 04-20 发送](https://www.feishu.cn/)

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [产品设计总览](#2-产品设计总览)
3. [核心设计哲学](#3-核心设计哲学)
4. [数据模型](#4-数据模型)
5. [Parser 架构](#5-parser-架构)
6. [Citation 分析与 URL 匹配](#6-citation-分析与-url-匹配)
7. [Agent NL2SQL 与配置 SQL 适配](#7-agent-nl2sql-与配置-sql-适配)
8. [SaaS Insights 与前端适配](#8-saas-insights-与前端适配)
9. [Suggestions 系统](#9-suggestions-系统)
10. [Tooltip 与用户引导](#10-tooltip-与用户引导)
11. [Migration Plan](#11-migration-plan)
12. [MVP vs V2 Scope 标签](#12-mvp-vs-v2-scope-标签)
13. [DB 操作规范](#13-db-操作规范)
14. [Open Items 与 Roadmap](#14-open-items-与-roadmap)
15. [附录](#15-附录)

---

## 1. 背景与动机

### 1.1 现状

AnswerX GEO 平台当前假设"客户 = 品牌"的隐式契约。`geo_clients.name` 被当作品牌名,`company_parser.py` 用客户名 + aliases 在 AI 回答里做正则匹配识别"自有品牌 mentions",`geo_client_peers` 存储竞品。这套模型对 **自有品牌出海客户**(Roborock 等)适用,但对 **ODM/OEM 客户**(如杭州天铭科技 Tmax)完全失效 —— AI 搜索引擎语料里从来没有 "Tmax" 这个名字,因为 Tmax 的产品全部通过 Rough Country(RC)贴牌销售。

### 1.2 战略意义

- **OEM/ODM 出海企业** 估算 >10 万家,是自营品牌出海(约 1 万家)的 10 倍+
- 汽车配件、消费电子、电动工具、户外装备等"有型号规范"的品类,OEM 占 >60%
- AI 搜索引擎**会**引用具体 SKU/型号(已联网验证),字面正则匹配可靠

### 1.3 本次迭代目标

1. 引入 **Brand** 为一等实体,支持 **Own Brand** + 多个 **Shadow Brand**(如经销商品牌)
2. 把 **Products** 提升为可匹配实体,支持 SKU/型号级 mention 追踪
3. **Visibility / Citation / Sentiment** 三大维度都支持品牌层 + 产品层双视角
4. **对存量 Roborock 类客户完全兼容** —— 默认行为等价今天,产品级信号"免费赠送"
5. **对 Tmax 类 OEM/ODM 客户开箱即用** —— 合理配置即可追踪完整 Shadow Brand + SKU 组合
6. 为中期切 LLM 识别留干净语义基础(Alias 语义纯净原则)

---

## 2. 产品设计总览

### 2.1 五类实体

AnswerX 的 tracking 配置由五类实体组成:

| 实体 | 含义 | 数据库表 |
|---|---|---|
| **Client(工作空间)** | 租户标识 | `geo_clients` |
| **Brands** | 客户追踪的品牌名,含 Own + Shadow | `geo_client_brands` |
| **Peers** | 独立竞品品牌 | `geo_client_peers` |
| **Topics → Products** | Topic 是语义分类,Products 是 Topic 下的具体 SKU 列表 | `geo_client_topics` + `geo_client_topic_products` |
| **Domains + Tracked URLs** | 整域归属 + SKU 精确 URL | `geo_client_domains` + `geo_product_tracked_urls` |

### 2.2 Brand:Own vs Shadow

| Brand 类型 | 含义 | 举例 |
|---|---|---|
| **Own Brand(自营品牌)** | 客户自己注册、拥有、对外售卖的品牌 | Roborock 的 "Roborock";Stanley 的 "Stanley" |
| **Shadow Brand(经销渠道品牌,UI 中文统一称"经销渠道品牌")** | 客户借助的外部品牌(通常是经销商/代理商/大平台),产品实际透出这个品牌名 | Tmax 的 "Rough Country";Stanley 在亚马逊上挂 "Amazon" 渠道 |

对系统而言,Own 和 Shadow 在 mention 匹配时逻辑**完全一样**(都是"客户关心的品牌,AI 提到就算 mention"),区别只在**报表分区**和**配置 UX**。

### 2.3 三类 Peer 场景(KFC / McDonald's 比喻)

以 Tmax 举例,配合"踏板 ≈ 炸鸡"的比喻:

- **天铭** = 国内做越野踏板的 OEM 工厂
- **Rough Country(RC)≈ KFC** = 天铭在美国的代理;同时卖:天铭、ABC、DEF 三家 OEM 的产品 + 自家品牌 SKU
- **McDonald's** = 另一家代理,只卖 ABC / DEF(不卖天铭)
- **ABC / DEF** = 其他国内 OEM 工厂

**三类 Peer 策略**:

| Peer 类型 | 含义 | 建模 | 本轮是否做 |
|---|---|---|---|
| **Type 1:其他国内 OEM** | 和天铭类似的 OEM,品牌在互联网上"匿名" | 理论可,但追不到流量 | ❌ 不做,成本高收益极低 |
| **Type 2:纯竞争 Shadow Brand(McDonald's)** | 不卖天铭产品的独立代理 | 作为 Peer 实体,可挂 Peer Products | ✅ **本轮做** |
| **Type 3:同渠道的非 HT 流量(RC 作为竞品身份)** | 自己的代理商 RC,语义是"RC 品牌 + 非 HT 型号" | RC 同时在 brands 和 peers;Products 用 `shadow_brand_product` 挂 `owner_brand=RC` | ✅ **本轮做**(可选 sub_role 细分 native/resale) |

### 2.4 Products 的 product_role 与 shadow_sub_role

```
product_role (3 值,必填):
  - own                      = 客户自己的产品
  - shadow_brand_product     = 经销渠道上的非客户产品
  - peer                     = 独立 Peer 渠道上的产品

shadow_sub_role (NULLABLE,仅 shadow_brand_product 可用):
  - native   = 经销渠道自家品牌线的产品(如 RC 自营 Nitro II)
  - resale   = 经销渠道代理其他 OEM 的产品(如 RC 代理 ABC OEM 的 SKU)
  - NULL     = 用户不确定 / 不需要区分(默认)
```

UI 层**不直接暴露** `product_role` 字段。用户通过**录入位置**隐式选择:
- 在 Topics Tab 下录 → `product_role='own'`
- 在 Brands Tab 展开某 Shadow Brand 下录 → `product_role='shadow_brand_product'`,可选 sub_role
- 在 Peers Tab 展开某 Peer 下录 → `product_role='peer'`

### 2.5 Topics

**不变**。Topic = 语义分组字符串,支持按业务品类("越野踏板")或按用户痛点("宠物清洁")命名。禁止 Topic = 渠道名。

Peer 下录入的 Peer Products 必须选 Topic(与 Own Products 一致)。Topic 的作用是 Insights 聚合 + Prompt Expander 生成,不进入 Parser。

### 2.6 Domains + Tracked URLs(双层)

**两个层次,两张表**:

```
Domain 级(geo_client_domains):Brand/Peer 的"领地边界"
  - scope = 'whole'        整域:tmax.cn / roughcountry.com
  - scope = 'path-prefix'  路径前缀:roughcountry.com/step-series/(Brand 领地的子目录)

Product 级(geo_product_tracked_urls):URL 指向特定 SKU
  - scope = 'exact'        精确 URL:roughcountry.com/product/ht-70911
  - scope = 'path-prefix'  路径前缀匹配 SKU 变体:roughcountry.com/product/ht-70911(覆盖 -black/-chrome 等)
```

设计理念:**Domain 稳定、Tracked URL 易变**(SKU 上下架)。生命周期解耦。

### 2.7 三种典型客户范例

详细 UI + 数据卡片见 **附录 D**。此处仅列概要:

| 范例 | 客户 | Brands | Shadow Brands | Peers | Products |
|---|---|---|---|---|---|
| **A:纯自营品牌** | Roborock | Roborock (Own) | 无 | iRobot / Dyson / Ecovacs / Dreame / Narwal | S8 Pro Ultra 等 (own) |
| **B:自营 + 第三方平台** | Stanley | Stanley (Own) | Amazon, Walmart | YETI / Hydro Flask / Owala | Quencher H2.0 (own,多 tracked URL) |
| **C:纯 OEM/ODM** | Tmax(基础)| Tmax(可选 Own 不建)| Rough Country | ARB / WARN / RC(作为竞品)/ McDonald's | HT-70911 (own),RC 上 Nitro II (shadow_brand_product) 等 |
| **D:OEM + Case 3 激活** | Tmax(深度)| 同 C | 同 C | 同 C | 同 C,但 shadow_sub_role 标 native/resale 做深细分 |

### 2.8 四种观察诉求

| 诉求 | 描述 | 实现 |
|---|---|---|
| **诉求 1** | 自家产品整体可见度 | `product_mentions WHERE product_role='own'` |
| **诉求 2** | Shadow Brand 本身可见度 | `brand_mentions WHERE brand_role='shadow'` |
| **诉求 3** | 自家产品在 Shadow Brand 上的表现(OEM 核心)| Response 级共现:`brand(shadow) × product(own)` |
| **诉求 4** | Shadow Brand 上非我产品的流量 | Response 级共现:`brand(shadow) × product(shadow_brand_product)`;或 `brand(shadow) - own Product` |

### 2.9 破互斥规则

**规则变更**(相对 v1.0):

同一字符串(如 "Rough Country")**允许**同时出现在 `geo_client_brands`(Shadow)和 `geo_client_peers`(直接竞争身份)两张表。

**理由**:Tmax 场景确认:RC 既是代理商,也是自营产品线的直接竞争对手。两种身份必须都能表达。

**代价**:BrandParser 需要去重(见 §5.1),Insights SQL 需要基于"成员身份"而非 brand_role 过滤(见 §7.3)。

---

## 3. 核心设计哲学

本轮迭代确立 3 条**永久性架构原则**,供未来所有 schema 讨论引用。

### 3.1 Alias 语义纯净原则(架构红线)

> **Alias 字段只装"同一实体类型的命名变体"。任何跨类型扁平化的需求,通过新增实体或字段表达,不塞 alias。**

具体:
- `Brand.aliases` = 品牌名的大小写、缩写、连写变体
- `Peer.aliases` = 竞品名变体
- `Product.match_variants` = SKU/型号变体

**严禁**把 "代理商名 + 产品型号 + 品牌变体" 混装进同一个 alias 字段。

**为什么**:
1. **NL2SQL 需要清晰的 schema 语义**,alias 混装会让聚合查询错误(SOV by brand 会把 SKU 贡献算进去)
2. **未来切 LLM 识别需要干净的语义基础** —— Profound 能用 LLM 正是因为它们的 alias 纯净;我们现在塞混,未来切 LLM 时 prompt 无法写
3. **UX 失焦** —— 一个字段塞多类实体,admin UI 和 CRUD 会变混乱

### 3.2 业务关系与物理证据分离

> **业务关系(Product↔Brand)独立于物理证据(URL 是否存在)**。业务关系用专门的关联表表达,URL 是可选的物理佐证。

体现:
- `geo_product_sales_channels` 表示 "Product 通过 Brand 销售"(业务事实)
- `geo_client_tracked_urls` / `geo_client_domains` 表示 "这些 URL 可用于 Citation 匹配"(物理层)
- 两者可独立存在:可以声明渠道但暂无 URL;可以有 URL 但暂无声明关系

### 3.3 数据驱动可见性,不打客户类型标签

> **UI 的可见性由"数据是否存在"驱动,不由"客户类型"标签驱动**。

体现:
- 没有 `client_type = 'oem' / 'brand'` 枚举字段
- 用 `has_shadow_brands`、`has_own_products`、`has_peer_products` 等运行时判定函数
- Roborock 无 Shadow Brand → OEM 相关 UI 自动隐藏,不需要"客户类型"判断
- 客户的配置随时间演化(如 Stanley 今天加了 Amazon 渠道),UI 自然跟上

---

## 4. 数据模型

### 4.1 变更概览

| 操作 | 对象 | 说明 |
|---|---|---|
| 🆕 新建 | `geo_client_brands` | Own + Shadow 统一管理 |
| 🆕 新建 | `geo_client_topic_products` | 从 `geo_client_topics.products TEXT[]` 迁出 |
| 🆕 新建 | `geo_product_mentions` | 产品级 mention |
| 🆕 新建 | `geo_product_sales_channels` | Product↔Brand 业务关系 |
| 🆕 新建 | `geo_product_tracked_urls` | Product 精确/前缀 URL 绑定 |
| 🆕 新建 | `geo_settings_candidates` | AI 发现的配置候选 |
| ♻️ 重命名 | `geo_company_mentions` → `geo_brand_mentions` + 字段升级 | 语义对齐 |
| ✏️ 扩展 | `geo_client_domains` | 加 `domain_scope` / `brand_id` / `peer_id` |
| ✏️ 扩展 | `geo_citations` | 加 `citation_role` + `matched_brand_id` + `matched_product_id` |
| ✏️ 扩展 | `geo_client_topic_products`(新表)| 含 `product_role` + `shadow_sub_role` + 双 FK |
| ✏️ 扩展 | `geo_clients` | 加 `onboarding_wizard_completed` |
| 🗑️ 删列 | `geo_client_peers.is_own_brand` | 遗留列全库 false |
| 🗑️ 删列 | `geo_client_topics.products TEXT[]` | 数据迁移后删除 |

### 4.2 新表完整定义

#### 4.2.1 `geo_client_brands`

```sql
CREATE TABLE geo_client_brands (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id   UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    brand_name  TEXT NOT NULL,
    aliases     TEXT[] NOT NULL DEFAULT '{}',
    is_shadow   BOOLEAN NOT NULL DEFAULT false,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, brand_name)
);

CREATE INDEX idx_geo_client_brands_client
    ON geo_client_brands(client_id) WHERE is_active = true;
```

#### 4.2.2 `geo_client_topic_products`

```sql
CREATE TABLE geo_client_topic_products (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic_id         UUID NOT NULL REFERENCES geo_client_topics(id) ON DELETE CASCADE,
    client_id        UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_name     TEXT NOT NULL,
    match_variants   TEXT[] NOT NULL DEFAULT '{}',
    product_role     TEXT NOT NULL DEFAULT 'own'
                     CHECK (product_role IN ('own','shadow_brand_product','peer')),
    shadow_sub_role  TEXT 
                     CHECK (shadow_sub_role IS NULL 
                            OR shadow_sub_role IN ('native','resale')),
    owner_brand_id   UUID REFERENCES geo_client_brands(id) ON DELETE SET NULL,
    owner_peer_id    UUID REFERENCES geo_client_peers(id) ON DELETE SET NULL,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT product_role_owner_consistency CHECK (
        (product_role = 'own' 
         AND owner_brand_id IS NULL 
         AND owner_peer_id IS NULL 
         AND shadow_sub_role IS NULL) 
     OR (product_role = 'shadow_brand_product' 
         AND owner_brand_id IS NOT NULL)
        -- shadow_sub_role 可 NULL / 'native' / 'resale'
        -- owner_peer_id 可 NULL(不指定代理谁)或非 NULL(sub_role='resale' 时指向被代理方)
     OR (product_role = 'peer' 
         AND owner_peer_id IS NOT NULL 
         AND owner_brand_id IS NULL 
         AND shadow_sub_role IS NULL)
    )
);

CREATE INDEX idx_geo_ctp_topic ON geo_client_topic_products(topic_id) WHERE is_active = true;
CREATE INDEX idx_geo_ctp_client ON geo_client_topic_products(client_id) WHERE is_active = true;
CREATE INDEX idx_geo_ctp_role ON geo_client_topic_products(client_id, product_role) WHERE is_active = true;
```

#### 4.2.3 `geo_brand_mentions`(从 `geo_company_mentions` 重命名 + 字段升级)

```sql
-- 执行顺序:
ALTER TABLE geo_company_mentions RENAME TO geo_brand_mentions;
ALTER TABLE geo_brand_mentions RENAME COLUMN company_name TO brand_name;

ALTER TABLE geo_brand_mentions 
    ADD COLUMN brand_role TEXT
    CHECK (brand_role IN ('own','shadow','peer'));

UPDATE geo_brand_mentions SET brand_role = CASE 
    WHEN is_own_brand = true THEN 'own' 
    ELSE 'peer' 
END;

ALTER TABLE geo_brand_mentions ALTER COLUMN brand_role SET NOT NULL;
ALTER TABLE geo_brand_mentions DROP COLUMN is_own_brand;
```

最终结构:

| 列名 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| client_prompt_id | UUID | FK |
| task_id | UUID | FK |
| result_id | INTEGER | FK |
| client_id | UUID | FK |
| brand_name | TEXT | 匹配到的品牌名 |
| brand_role | TEXT | `own` / `shadow` / `peer` |
| mention_position | INTEGER | 出现顺序 |
| executed_at | TIMESTAMPTZ | - |
| created_at | TIMESTAMPTZ | - |

#### 4.2.4 `geo_product_mentions`

```sql
CREATE TABLE geo_product_mentions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_prompt_id    UUID NOT NULL,
    task_id             UUID,
    result_id           INTEGER NOT NULL,
    client_id           UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_id          UUID REFERENCES geo_client_topic_products(id) ON DELETE SET NULL,
    product_name        TEXT NOT NULL,
    product_role        TEXT NOT NULL 
                        CHECK (product_role IN ('own','shadow_brand_product','peer')),
    shadow_sub_role     TEXT 
                        CHECK (shadow_sub_role IS NULL OR shadow_sub_role IN ('native','resale')),
    owner_brand_id      UUID,
    owner_brand_name    TEXT,
    owner_peer_id       UUID,
    owner_peer_name     TEXT,
    mention_position    INTEGER,
    executed_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_geo_pm_client ON geo_product_mentions(client_id, executed_at DESC);
CREATE INDEX idx_geo_pm_result ON geo_product_mentions(result_id, client_id);
CREATE INDEX idx_geo_pm_role ON geo_product_mentions(client_id, product_role);
CREATE INDEX idx_geo_pm_sub_role ON geo_product_mentions(client_id, shadow_sub_role) 
    WHERE shadow_sub_role IS NOT NULL;
```

denormalized `owner_*_name` 和 `shadow_sub_role` 在 Parser 写入时固化,避免 Dashboard 聚合时多次 JOIN。

#### 4.2.5 `geo_product_sales_channels`

```sql
CREATE TABLE geo_product_sales_channels (
    product_id  UUID NOT NULL REFERENCES geo_client_topic_products(id) ON DELETE CASCADE,
    brand_id    UUID NOT NULL REFERENCES geo_client_brands(id) ON DELETE CASCADE,
    client_id   UUID NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (product_id, brand_id)
);

CREATE INDEX idx_geo_psc_client ON geo_product_sales_channels(client_id);
CREATE INDEX idx_geo_psc_brand ON geo_product_sales_channels(brand_id);
```

**语义**:"Product X 通过 Brand Y 销售"。独立于 URL 是否存在。

#### 4.2.6 `geo_product_tracked_urls`

```sql
CREATE TABLE geo_product_tracked_urls (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id   UUID NOT NULL,
    product_id  UUID NOT NULL REFERENCES geo_client_topic_products(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    url_scope   TEXT NOT NULL DEFAULT 'exact' 
                CHECK (url_scope IN ('exact','path-prefix')),
    brand_id    UUID REFERENCES geo_client_brands(id),
    peer_id     UUID REFERENCES geo_client_peers(id),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, url, product_id),
    CONSTRAINT tracked_url_owner_exclusive CHECK (
        NOT (brand_id IS NOT NULL AND peer_id IS NOT NULL)
    )
);

CREATE INDEX idx_geo_ptu_product ON geo_product_tracked_urls(product_id);
CREATE INDEX idx_geo_ptu_client_url ON geo_product_tracked_urls(client_id, url);
```

注意:不含 `url_scope = 'whole'`(整域概念归 `geo_client_domains`)。

#### 4.2.7 `geo_client_domains` 扩展

```sql
ALTER TABLE geo_client_domains 
    ADD COLUMN domain_scope TEXT NOT NULL DEFAULT 'whole'
        CHECK (domain_scope IN ('whole','path-prefix')),
    ADD COLUMN brand_id UUID REFERENCES geo_client_brands(id) ON DELETE CASCADE,
    ADD COLUMN peer_id  UUID REFERENCES geo_client_peers(id)  ON DELETE CASCADE;

ALTER TABLE geo_client_domains
    ADD CONSTRAINT domain_owner_exclusive CHECK (
        NOT (brand_id IS NOT NULL AND peer_id IS NOT NULL)
    );

-- 存量 6 行 domains 挂到 Own Brand
UPDATE geo_client_domains d
SET brand_id = (SELECT id FROM geo_client_brands b
                WHERE b.client_id = d.client_id AND b.is_shadow = false 
                LIMIT 1);
```

#### 4.2.8 `geo_citations` 扩展

```sql
ALTER TABLE geo_citations
    ADD COLUMN citation_role TEXT CHECK (citation_role IN (
        'own_domain', 'own_product',
        'shadow_product_native', 'shadow_product_resale', 
        'shadow_product', 'shadow_other',
        'peer_product', 'peer_channel',
        'earned', 'social', 'agency', 'other'
    )),
    ADD COLUMN matched_brand_id UUID REFERENCES geo_client_brands(id),
    ADD COLUMN matched_product_id UUID REFERENCES geo_client_topic_products(id);

CREATE INDEX idx_geo_citations_role ON geo_citations(client_id, citation_role);
```

#### 4.2.9 `geo_settings_candidates`

```sql
CREATE TABLE geo_settings_candidates (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id        UUID NOT NULL,
    candidate_string TEXT NOT NULL,
    candidate_type   TEXT NOT NULL CHECK (candidate_type IN (
        'brand', 'shadow_brand', 'peer',
        'own_product', 'shadow_product', 'peer_product',
        'tracked_url'
    )),
    suggested_target_topic_id  UUID,
    suggested_target_brand_id  UUID,
    suggested_target_peer_id   UUID,
    source TEXT NOT NULL CHECK (source IN (
        'n_gram', 'llm_batch', 'auto_discovery'
    )),
    frequency   INT DEFAULT 1,
    first_seen  TIMESTAMPTZ DEFAULT NOW(),
    last_seen   TIMESTAMPTZ DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'pending' 
        CHECK (status IN ('pending','accepted','rejected','ignored')),
    sample_response_ids INT[],
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, candidate_string, candidate_type)
);

CREATE INDEX idx_geo_sc_client_status ON geo_settings_candidates(client_id, status);
CREATE INDEX idx_geo_sc_type ON geo_settings_candidates(client_id, candidate_type) WHERE status = 'pending';
```

#### 4.2.10 `geo_clients` 扩展

```sql
ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS onboarding_wizard_completed BOOLEAN NOT NULL DEFAULT false;

UPDATE geo_clients SET onboarding_wizard_completed = true WHERE created_at < NOW();
```

### 4.3 删除项

```sql
-- 删列:geo_client_peers.is_own_brand(全库 false,遗留)
ALTER TABLE geo_client_peers DROP COLUMN is_own_brand;

-- 删列:geo_client_topics.products(数据迁移完成后)
ALTER TABLE geo_client_topics DROP COLUMN products;
```

### 4.4 URL 归属校验 Trigger(防御配置错误)

```sql
CREATE OR REPLACE FUNCTION validate_tracked_url_ownership()
RETURNS TRIGGER AS $$
DECLARE
    host_from_url TEXT;
    owner_brand_from_domains UUID;
    owner_peer_from_domains UUID;
BEGIN
    host_from_url := regexp_replace(
        regexp_replace(NEW.url, '^https?://', ''),
        '/.*$', ''
    );
    host_from_url := regexp_replace(host_from_url, '^www\.', '');

    SELECT brand_id, peer_id 
    INTO owner_brand_from_domains, owner_peer_from_domains
    FROM geo_client_domains
    WHERE client_id = NEW.client_id 
      AND domain_scope = 'whole' 
      AND LOWER(domain) = LOWER(host_from_url)
    LIMIT 1;

    IF owner_brand_from_domains IS NOT NULL OR owner_peer_from_domains IS NOT NULL THEN
        IF NEW.brand_id IS NOT NULL AND NEW.brand_id != owner_brand_from_domains THEN
            RAISE EXCEPTION 'URL host % is registered to a different brand. Check URL correctness.', 
                host_from_url;
        END IF;
        IF NEW.peer_id IS NOT NULL AND NEW.peer_id != owner_peer_from_domains THEN
            RAISE EXCEPTION 'URL host % is registered to a different peer. Check URL correctness.', 
                host_from_url;
        END IF;
        IF NEW.brand_id IS NULL AND NEW.peer_id IS NULL THEN
            NEW.brand_id := owner_brand_from_domains;
            NEW.peer_id := owner_peer_from_domains;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_validate_tracked_url_ownership
    BEFORE INSERT OR UPDATE ON geo_product_tracked_urls
    FOR EACH ROW EXECUTE FUNCTION validate_tracked_url_ownership();
```

---

## 5. Parser 架构

### 5.1 BrandParser(重命名自 `company_parser.py`)

```
File: geo_analyzer/src/parsers/brand_parser.py

输入:
  - response_text
  - brands: [{brand_name, aliases, is_shadow}, ...] from geo_client_brands
  - peers:  [{primary_name, aliases}, ...] from geo_client_peers

步骤:
  1. 对每个 Brand(own + shadow)构造 \b...\b word-boundary 正则
  2. 对每个 Peer 同样匹配
  3. 去重规则(**同字符串跨两表的关键**):
     - 对同一个匹配到的字符串,若同时命中 brands 和 peers:
       * brand_role = 'shadow'(brands 优先,避免双重计数)
       * 不额外产出 brand_role='peer' 的记录
     - 仅在 peers 命中:brand_role = 'peer'
     - 仅在 brands 命中:brand_role = 'own' 或 'shadow'(按 is_shadow)
  4. 同一品牌在一条 response 里只取第一次出现(位置去重)
  5. 写入 geo_brand_mentions(brand_name, brand_role, position, ...)
```

### 5.2 ProductParser(新建)

```
File: geo_analyzer/src/parsers/product_parser.py

输入:
  - response_text
  - tracked_products: 全部 active products(不筛 product_role)
    {id, product_name, match_variants, product_role, shadow_sub_role,
     owner_brand_id, owner_brand_name, owner_peer_id, owner_peer_name}

步骤:
  1. 对每个 product 的每个 match_variant(若为空回退到 product_name):
     - \b...\b word-boundary 匹配(case-insensitive)
     - 跳过长度 <= 3 字符的 variant(防误伤,记 warning)
  2. 同一个 product 在一条 response 里只取第一次
  3. 写入 geo_product_mentions with denormalized owner_*_name + shadow_sub_role
```

### 5.3 Analyzer Pipeline 变更

```
geo_analyzer/main.py:

Phase 0(新增):加载配置
  - brands (含 is_shadow)
  - peers
  - tracked_products (含 role/sub_role/owner)
  - domains + tracked_urls
  
Phase 1(改造):批量 parse per result
  - BrandParser  → brand mentions → geo_brand_mentions
  - ProductParser → product mentions → geo_product_mentions
  - CitationParser → citations → geo_citations(含 citation_role + matched_*_id)

Phase 2a(不变):批量 domain_classifier
Phase 2b(不变):批量 sentiment_parser
Phase 3(改造):写库 - 新 schema 两张 mention 表
Phase B(不变):sentiment theme normalize
```

---

## 6. Citation 分析与 URL 匹配

### 6.1 两表两阶段匹配

```python
def classify_citation(citation_url, client_id):
    normalized = normalize_url(citation_url)  # strip scheme/www
    
    # Stage 1: Product-level 匹配(geo_product_tracked_urls,longest match wins)
    hit = db.query("""
        SELECT ptu.*, p.product_role, p.shadow_sub_role
        FROM geo_product_tracked_urls ptu
        JOIN geo_client_topic_products p ON p.id = ptu.product_id
        WHERE ptu.client_id = $1 AND (
            (ptu.url_scope = 'exact' AND LOWER(ptu.url) = LOWER($2))
            OR (ptu.url_scope = 'path-prefix' AND LOWER($2) LIKE LOWER(ptu.url) || '%')
        )
        ORDER BY LENGTH(ptu.url) DESC
        LIMIT 1
    """, client_id, normalized)
    
    if hit:
        citation_role = derive_from_product(hit.product_role, hit.shadow_sub_role)
        return {
            citation_role, 
            matched_brand_id: hit.brand_id,
            matched_product_id: hit.product_id
        }
    
    # Stage 2: Domain-level 匹配(geo_client_domains,longest match wins)
    hit = db.query("""
        SELECT d.*, b.is_shadow
        FROM geo_client_domains d
        LEFT JOIN geo_client_brands b ON b.id = d.brand_id
        WHERE d.client_id = $1 AND (
            (d.domain_scope = 'whole' AND LOWER(d.domain) = host($2))
            OR (d.domain_scope = 'path-prefix' AND LOWER($2) LIKE LOWER(d.domain) || '%')
        )
        ORDER BY LENGTH(d.domain) DESC
        LIMIT 1
    """, client_id, normalized)
    
    if hit:
        if hit.brand_id and not hit.is_shadow:
            return {citation_role: 'own_domain', matched_brand_id: hit.brand_id}
        elif hit.brand_id and hit.is_shadow:
            return {citation_role: 'shadow_other', matched_brand_id: hit.brand_id}
        elif hit.peer_id:
            return {citation_role: 'peer_channel', matched_peer_id: hit.peer_id}
    
    # Stage 3: Fallback to domain_classifier (earned / social / agency / other)
    global_cat = domain_classifier.classify(host(normalized))
    return {citation_role: global_cat}
```

### 6.2 `citation_role` 推导表

| product_role | shadow_sub_role | citation_role |
|---|---|---|
| own | - | `own_product` |
| shadow_brand_product | native | `shadow_product_native` |
| shadow_brand_product | resale | `shadow_product_resale` |
| shadow_brand_product | NULL | `shadow_product` |
| peer | - | `peer_product` |

Domain-level hits:
- Own Brand 整域 → `own_domain`
- Shadow Brand 站但非 tracked SKU → `shadow_other`
- Peer 域 → `peer_channel`

Fallback: `earned` / `social` / `agency` / `other`。

---

## 7. Agent NL2SQL 与配置 SQL 适配

### 7.1 Phase 1 模板与指标审阅节点(新增工作节点)

在实施 Plan 的 Phase 1(地基阶段)最后、进入 Phase 2 代码重写之前,插入一个**审阅节点**:

**审阅清单**:

| 对象 | 审阅动作 |
|---|---|
| `geo_analysis_metrics` 全部 11 行 | 每行过一遍 SQL,适配新 schema;识别需新增的 metric |
| `geo_report_templates.wizard_config`(2 分析模板 + 6 内容模板)| 每个 default_charts 的 sql_hint 重写 + 新增 chart 建议 |
| `analysis_pipeline.py` 的 `TABLE_HINTS` | 按新 schema 重写 |
| `data_tools.py` / `chart_tools.py` / `utility_tools.py` | 字段引用适配 |

**产出**:所有新旧 metrics 的完整 SQL(migration 文件),模板 wizard_config 的 UPDATE SQL,Agent 代码 diff。

**预计工作量**:2-3 天

### 7.2 新增 Metrics(本轮建议 6 个)

| Metric Name | UI 显示名(中文) | 数据源 | 可见性依赖 |
|---|---|---|---|
| `product_sov_own` | 自家产品声量占比 | `geo_product_mentions WHERE product_role='own'` | `has_own_products` |
| `shadow_cooccurrence_own_product` | 经销渠道 × 自家产品共现 | brand×product JOIN on result_id | `has_shadow_brands AND has_own_products` |
| `shadow_cooccurrence_peer_product` | 经销渠道 × 非我产品共现 | 同上,filter shadow_brand_product | `has_shadow_brands AND has_shadow_products` |
| `peer_sov_via_peers_list` | 竞品声量分析(**正确性修复**)| 基于 peers 成员身份,不筛 brand_role | 永远可见 |
| `citation_by_citation_role` | 引用分布(按类型) | `geo_citations.citation_role` 聚合 | 永远可见 |
| `product_sentiment_by_role` | 产品情感分析 | `sentiment_results JOIN product_mentions` | `has_product_mentions` |

### 7.3 Peer SOV 的正确性修复(§5 迁移规则)

**问题**:RC 同时在 brands(shadow)+ peers,BrandParser 只产出 `brand_role='shadow'` 的 mention。若 Dashboard SQL 是 `WHERE brand_role='peer'`,会**漏掉 RC**。

**机械化替换规则**(calculation_hint / wizard_config / 代码):

```
旧:
  WHERE brand_role = 'peer'
  WHERE is_own_brand = false
  
新(基于 peers 列表成员身份):
  WHERE EXISTS (
    SELECT 1 FROM geo_client_peers p
    WHERE p.client_id = bm.client_id
      AND (p.primary_name ILIKE bm.brand_name 
           OR bm.brand_name = ANY(p.aliases))
  )
```

这个替换适用于所有 Peer 相关 SQL,放进 §11 migration Step 3 批量 UPDATE。

### 7.4 新建"渠道表现分析"模板(OEM 专属)

**触发条件**:`has_shadow_brands=true` 时在 Agent 模板选择器可见,名称使用中文"**渠道表现分析**"(UI 不出现 "OEM" 字样)。

**默认 charts**(写入 `geo_report_templates.wizard_config`):

1. 经销渠道 × 自家产品共现趋势(折线图)
2. 经销渠道上产品分布矩阵(热图,含 native/resale/NULL 三层)
3. 自家产品在不同经销渠道的声量对比(柱状图)
4. 渠道 Citation 分布(按 citation_role)

### 7.5 Agent 代码 schema hint 重写

所有提到 `geo_company_mentions` / `is_own_brand` / `company_name` 的字符串按新 schema 重写。详细涉及文件清单见附录 E(v1.0 §5.1 全部继承)。

---

## 8. SaaS Insights 与前端适配

### 8.1 UI 改动原则(红线 + 允许)

**绝对不动**:
- ❌ 不破坏 Visibility / Citation / Sentiment 三大 Dashboard 现有布局
- ❌ 不删除任何现有 chart
- ❌ 不删除 Citation 的点击详情侧滑抽屉
- ❌ 不改 global filter bar(Date/Topic/Platform/Prompt Type)位置行为
- ❌ 不改 Profound 风格视觉语言

**允许改动(增量)**:
- ✅ filter bar **追加** "View By" 切换器(品牌/产品/交叉),默认"品牌"= 现状
- ✅ 在现有 chart 之后 **追加** 新 chart 组件(产品维度 section 等)
- ✅ OEM 专属图表开 **新 Tab**"**渠道分析**",并列于 Visibility 等
- ✅ Dashboard SQL 按新 schema 适配,Roborock 可视化输出无感
- ✅ Settings 新增 Brands / Shadow Brand Products / Peer Products / Tracked URLs 子结构
- ✅ 全局"AI 建议"入口(汇总 Suggestions)

### 8.2 Settings 页面改造

```
Settings 整体 Tab 结构:

├── 品牌 (Brands)
│     ├── 我的品牌 (Own Brands)
│     │    └── 每个 Own Brand 卡片:名字 / 别名 / 该品牌下的域名
│     └── 经销渠道品牌 (Shadow Brands)
│          └── 每个 Shadow Brand 卡片:
│              ├── 名字 / 别名
│              ├── 该品牌下的域名(geo_client_domains WHERE brand_id=X)
│              └── 该渠道下的产品(geo_client_topic_products 
│                                  WHERE owner_brand_id=X)
│                  └── 子类型选择器(不确定/自家品牌线/代理他人)
│
├── 竞品 (Peers)
│     └── 每个 Peer 卡片:
│         ├── 名字 / 别名
│         ├── 该竞品的域名(geo_client_domains WHERE peer_id=X)
│         └── 该竞品下的产品(geo_client_topic_products 
│                              WHERE owner_peer_id=X)
│
├── 追踪话题 (Topics)
│     └── 每个 Topic 展开:
│         └── 自家产品(product_role='own')
│             └── 每个 Product 卡片:
│                 ├── 产品名 / 匹配变体
│                 ├── 🔗 追踪 URL(geo_product_tracked_urls)
│                 └── 🏪 销售渠道(geo_product_sales_channels)
│
└── 域名 (Domains,可选的汇总入口,大多操作在 Brands/Peers Tab 内完成)
```

### 8.3 新 Tab "渠道分析"(OEM 专属)

**可见性条件**:`has_shadow_brands=true`(数据驱动,无客户类型判断)

**内容**:
- 经销渠道 × 自家产品共现矩阵(核心)
- 经销渠道上产品分布(按 sub_role 细分)
- 自家产品多渠道分布对比(Stanley on Amazon vs Walmart)
- 渠道 Citation 分类占比

### 8.4 View By 切换(在 global filter bar 里)

```
[日期] [话题] [平台] [Prompt 类型] [视图维度 ▼]
                                    ├ 品牌(默认)
                                    ├ 产品(has_own_products=true 时可选)
                                    ├ 话题
                                    └ 交叉(has_shadow_brands + 相关数据时)
```

### 8.5 Empty state + 数据驱动可见性

所有新图表遵守:

```
可见性判定(运行时 SQL):
  has_own_brands = EXISTS(brands WHERE is_shadow=false)
  has_shadow_brands = EXISTS(brands WHERE is_shadow=true)
  has_own_products = EXISTS(topic_products WHERE product_role='own')
  has_shadow_products = EXISTS(topic_products WHERE product_role='shadow_brand_product')
  has_peer_products = EXISTS(topic_products WHERE product_role='peer')
  has_mentions_data = EXISTS(brand_mentions / product_mentions 近 30 天)
  has_shadow_sub_role_distinction = EXISTS(topic_products WHERE shadow_sub_role IS NOT NULL)
```

`/api/insights/availability?client_id=X` 端点返回全部 availability flag,前端据此决定 UI 层级。

**Empty state 标准组件**(中文):

```tsx
<EmptyStateCard
  icon={<Package />}
  title="暂无产品数据"
  description="产品级洞察需要在"追踪话题"下配置具体 SKU。"
  ctaLabel="配置产品"
  ctaHref="/settings/topics"
  secondaryInfo="提示:不影响品牌级洞察的正常显示。"
/>
```

### 8.6 Onboarding Wizard

首次登录弹出(`onboarding_wizard_completed = false`):

```
欢迎来到 AnswerX GEO

在开始追踪前,我们想快速了解一下您的业务:

您的品牌是如何出现在市场上的?

  ○ 自营品牌   —— AI 会直接提到我们的品牌名(如小米、华为)
  ○ OEM / 贴牌供应商 —— 我们的产品挂在代理商品牌下销售
  ○ 两者都有 —— 自营品牌 + 同时通过代理商销售
  ○ 稍后再配置

[跳过]  [下一步]
```

根据选择驱动默认 UI 状态:

| 选择 | 默认动作 | UI 状态 |
|---|---|---|
| 自营品牌 | 自动创建 Own Brand(brand_name=client.name) | "我的品牌"展开;"经销渠道品牌"折叠 |
| OEM | 聚焦"经销渠道品牌"输入;tooltip 提示 | "我的品牌"折叠;"经销渠道品牌"展开 |
| 两者都有 | 创建 Own Brand + 引导加 Shadow | 两区都展开 |
| 跳过 | 无动作 | 默认折叠 |

OEM 完成 Shadow Brand 录入后,追加一步:"**可选:添加在同一渠道上销售的竞争 SKU**",引导进入 Peers Tab。

---

## 9. Suggestions 系统

### 9.1 三路产出,一张表汇总

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│  N-gram Fallback    │    │  Phase 2 LLM Batch  │    │ Auto-discovery      │
│  (~20 行算法)       │    │  (Gemini Flash Batch)│    │ (Onboarding 触发)   │
└─────────┬───────────┘    └──────────┬──────────┘    └──────────┬──────────┘
          │                           │                           │
          └───────────────────────────┼───────────────────────────┘
                                      │ UPSERT(dedup on unique constraint)
                                      ▼
                         ┌────────────────────────┐
                         │ geo_settings_candidates│
                         └────────────┬───────────┘
                                      │ UI 消费
                                      ▼
                         ┌────────────────────────┐
                         │ Per-Tab AI 建议面板     │
                         │ 全局 AI 建议汇总入口     │
                         └────────────────────────┘
```

### 9.2 Phase 2 LLM Batch(本轮主力)

**工作流**:
- Cloud Scheduler 定时触发(建议每日一次)
- 读取近期 AI response(比如 24 小时内,按客户分批)
- Vertex AI Batch Prediction(Gemini 2.5 Flash Batch,$0.075/1M input)
- Prompt:"从以下 AI 回答中抽取出未在已配置列表里的品牌/产品/SKU 候选,输出 JSON"
- 去重:UPSERT 到 `geo_settings_candidates`(candidate_string + type 唯一)

**成本预估**(Flash Batch):
- 2 客户:~$1-2/月
- 10 客户:~$7-10/月
- 100 客户:~$80/月

### 9.3 N-gram Fallback(MVP 备份)

~20 行简单算法,LLM 不可用时或预算吃紧时启用:
- 抽出连续 2-5 字符/词子串
- 过滤:长度 >= 4、含数字或连字符、大写单词等 heuristic
- 排除已在 match_variants / aliases 的
- UPSERT 到 `geo_settings_candidates`(source='n_gram')

### 9.4 Auto-discovery(本轮纳入)

**Onboarding / 定期刷新时触发**:

工作流:
1. 用户提供 URL(Own 官网 / Shadow Brand 站 / Peer 官网)+ 可选 instruction("含 HT 的是客户产品")
2. 多层爬取 fallback:robots.txt → sitemap → 导航栏 → LLM 兜底(grounding + web search)
3. LLM 识别 + 分类:Products / Brands / Peers / URLs
4. 写入 `geo_settings_candidates`,source='auto_discovery'
5. **副产品**:grounding 返回的 URLs 写入 `tracked_url` 候选,辅助 Citation Domain 初始化

### 9.5 Per-Tab Suggestions UI

```
每个 Tab 顶部 banner:
  💡 AI 发现 8 条可能未录入的品牌/产品  [查看]

点开后:
  ┌─────────────────────────────────────────────────┐
  │ 候选: ESR-70911-BLK (出现 12 次,AI 发现于 3 天前)│
  │ 样例引用: [answer_xxx]                            │
  │ [加入到: HT-70911 的匹配变体 ▼]  [忽略]          │
  └─────────────────────────────────────────────────┘
```

分类:heuristic 初分发到各 Tab,用户可覆写。

全局汇总入口:Settings 顶部"**AI 建议**"按钮,聚合所有 pending candidates。

---

## 10. Tooltip 与用户引导

### 10.1 系统设计

- 每个新概念字段 / 按钮 / 图表标题旁加 **灰色 ⓘ 图标**(14px)
- 悬停显示 tooltip(简短,2-3 行),点击展开更详细的侧抽屉 / 链接到 help docs
- 所有 tooltip 文案集中在 i18n dictionary,为多语言留路径
- 用 shadcn 的 `<Tooltip>` 组件保持视觉一致

### 10.2 完整 Tooltip 文案清单(本轮必做)

**Settings 页面**:

| 位置 | 文案 |
|---|---|
| "自营品牌" 区域 | "您自己拥有并对外销售的品牌,AI 答案里会直接提到这个名字(如 Roborock、Stanley)。" |
| "经销渠道品牌" 区域 | "您通过代理商/零售平台销售时,产品实际挂出的品牌名(如 Amazon、Rough Country)。AI 答案里会提到这些渠道品牌,而不是您的公司名。" |
| 经销渠道品牌 → 该渠道下的产品 | "这个渠道上销售的产品,包括该渠道自家品牌线的产品 / 该渠道代理其他供应商的产品。追踪这些可看出您的产品在该渠道上和哪些其他产品一起被推荐。" |
| Peer 同时是 Shadow 时 | "Rough Country 同时是您的经销渠道和直接竞争对手。它作为竞品时的产品管理,请在 **品牌 → Rough Country** 下查看。" |
| Products → 子类型选择器 | "如果您知道这款产品在 [Rough Country] 上的归属关系,可以细分;如果不确定,保持默认「不需要区分」即可。" |
| Tracked URLs → 输入框 | "精确 URL 匹配该详情页;路径前缀可匹配所有以该路径开头的 URL(例如 /product/ht-70911 可匹配该产品的黑色、银色等所有变体页)。" |
| Onboarding → "OEM/贴牌" 选项 | "您的产品在终端市场上不以您的公司名销售,而是挂在经销商/代理商的品牌下(典型如 ODM 代工厂通过 Amazon/Walmart/RC 销售)。" |
| AI 建议面板 | "我们的 AI 离线扫描 AI 搜索引擎的回答,发现这些可能未录入的品牌/产品/URL 候选。请 Review 后选择采纳或忽略。" |

**Dashboard 新逻辑**:

| 位置 | 文案 |
|---|---|
| View By 切换器 | "切换数据聚合维度:品牌 / 产品 / 话题 / 交叉。产品维度需要配置了 Topic 下的 Product 才会显示。" |
| 经销渠道 × 自家产品共现(核心图)| "同一条 AI 答案里同时提到 [渠道品牌] 和您自家产品的次数。这是 OEM/代理销售模式下最核心的指标,反映您的产品在渠道语境中的可见度。" |
| 经销渠道上的非我产品分布 | "Rough Country 渠道上被 AI 推荐的其他产品(非您自己的)。可细分:渠道自家品牌线 / 渠道代理他人。帮您评估在该渠道的竞争格局。" |
| Citation 分类(citation_role)| "引用的来源类型:您自家官网引用 / 您在经销渠道上的产品页引用 / 经销渠道其他页面 / 独立竞品渠道 / 第三方媒体评测等。" |
| 竞品声量分析(强化版)| "所有您标记为竞品的品牌的声量对比,**包括同时也是您经销渠道的品牌**(如 Rough Country 既是渠道又是竞品时都纳入)。" |

### 10.3 Roadmap 补充(用户引导系统升级)

dual-mode v1.2 稳定后:
- 新用户 onboarding 页面内导览(interactive tour)
- Help docs 站点:详细解释 Brand / Peer / Shadow / Product Role 等概念
- 常见场景操作手册(自营/OEM/混合三种 playbook)

---

## 11. Migration Plan

### 11.1 执行顺序

**Step 0 — 准备**
1. Cloud SQL 快照备份
2. 暂停 Analyzer / Collector Cloud Run Job

**Step 1 — Schema 变更**(全部 DDL,按编号顺序在 Cloud SQL 执行)

详见 §4 各节的 CREATE/ALTER SQL。执行顺序:

```
1. 新建 geo_client_brands
2. Seed:为每个存量 client 插 (name, aliases, is_shadow=false) 一行
3. 新建 geo_client_topic_products
4. 迁移数据:FROM geo_client_topics.products TEXT[] → 新表
5. Rename geo_company_mentions → geo_brand_mentions + brand_role 迁移
6. 新建 geo_product_mentions
7. 新建 geo_product_sales_channels
8. 新建 geo_product_tracked_urls
9. 新建 geo_settings_candidates
10. 扩展 geo_client_domains(domain_scope / brand_id / peer_id)
11. 回填 geo_client_domains.brand_id(挂 Own Brand)
12. 扩展 geo_citations(citation_role / matched_*_id,全 NULL 初始)
13. 删除 geo_client_peers.is_own_brand
14. 删除 geo_client_topics.products TEXT[](迁移验证后)
15. geo_clients.onboarding_wizard_completed(全 true)
16. 创建 validate_tracked_url_ownership trigger
17. TRUNCATE agent 运行态表(checkpoints / agent_messages / agent_memories / geo_agent_tasks)
```

**Step 2 — 重写配置 SQL**(批量 UPDATE)

- `geo_analysis_metrics.calculation_hint` 批量 replace:
  - `geo_company_mentions` → `geo_brand_mentions`
  - `cm.is_own_brand = true` → `cm.brand_role = 'own'`
  - `cm.is_own_brand = false` → `EXISTS peers_list_check`(见 §7.3)
  - `cm.company_name` → `cm.brand_name`
- `geo_analysis_metrics.relevant_tables` array_replace
- `geo_report_templates.wizard_config` JSON 内批量 replace
- Seed 新 6 个 metrics(§7.2)

**Step 3 — 代码部署**(按依赖顺序)

1. Analyzer(含新 Parsers)
2. Collector(prompt_expander 的 include_products 参数支持)
3. SaaS API(insights 新端点 / settings CRUD)
4. Agent(TABLE_HINTS 更新)
5. Admin UI + SaaS UI(新组件)

**Step 4 — 重启 Job + 监控**

### 11.2 回滚策略

- DDL 不可逆(删列无法恢复)→ 必须依赖快照
- 异常情况:从快照整库恢复

### 11.3 数据保护清单

**完整保留(Roborock 历史)**:
- geo_results (2,128 行)
- geo_brand_mentions (10,486 行,重命名后)
- geo_citations (42,607 行)
- geo_sentiment_results / geo_sentiment_themes
- geo_client_prompts (76 行)
- geo_tasks

**TRUNCATE**(无线上用户,无保留价值):
- checkpoints / agent_messages / agent_memories / geo_agent_tasks

---

## 12. MVP vs V2 Scope 标签

**使用说明**:此表给出本轮每个交付项的 MVP / V2 标签。**MVP 必做** = v1.2 release blocker;**V2 可延** = 若时间压力大可砍,保持向后兼容。

### 12.1 MVP 必做(release blocker)

| 项 | 说明 |
|---|---|
| Brand Own/Shadow 一等实体 + schema | Tmax 能配置 RC 为 Shadow |
| Products 3 值 product_role + NULL sub_role | Case 3 语义可表达 |
| geo_brand_mentions 重命名 + brand_role enum | Parser 产出新 schema |
| geo_product_mentions 新表 | Product-level mention 记录 |
| BrandParser 去重规则(brands 优先) | RC 同时在两表不双算 |
| ProductParser 新建 | Product 级匹配 |
| 破 Brand/Peer 互斥规则 | Tmax 场景必需 |
| Citation 方案 B(2 张 URL 表 + citation_role) | 精确归因 |
| URL 归属校验 trigger | 防错配 |
| geo_product_sales_channels | 业务关系声明 |
| geo_client_domains 扩展(brand_id/peer_id/scope) | 配合方案 B |
| Peer SOV 正确性修复(§7.3 替换规则) | Dashboard 不漏 RC |
| Settings UI 基础(Brands/Peers/Topics 三 Tab 升级 + Shadow 产品子面板) | 用户可配置 |
| Tracked URLs UI 基础(Product 卡片下的 URL 管理)| 用户可配 URL |
| Onboarding Wizard(4 选 1 分支)| 新客户首次引导 |
| `geo_analysis_metrics` / `wizard_config` 字段迁移(字段改名,不加新 metric) | 存量 Dashboard 不断 |
| 存量 Dashboard SQL 适配(输出视觉不变) | Roborock 无感 |
| Tooltip 系统(§10.2 最小集:15 条核心文案) | 新概念教学 |
| Migration SQL 全套 | 上线必需 |
| 本轮新增 UI 文案全中文(§2.7、§10.2 等)| 汉化原则启动 |

### 12.2 V2 可延(优先级次于 MVP)

| 项 | 说明 | 砍掉影响 |
|---|---|---|
| Phase 2 LLM Batch Discovery | N-gram 主力替代 | 砍:只用 N-gram fallback,召回率差但能跑 |
| Auto-discovery(Own + Shadow + Peer Products)| Onboarding 省力 | 砍:用户全手动录入 |
| N-gram fallback(~20 行算法) | LLM 不可用兜底 | 砍:完全依赖 LLM Batch |
| Per-Tab Suggestions UI 完整版(含分类、预填)| AI 建议交互 | 砍:基础列表 + 手工加入 |
| 新 Tab "渠道分析"(OEM 专属) | 独立 OEM Dashboard | 砍:OEM 图表插到 Visibility 底部 |
| 新增 6 个 metrics 全部 | Phase 1 审阅产出 | 砍:只做必要的 2 个(peer_sov_via_peers_list + citation_by_citation_role) |
| Case 3 sub_role 深化 UI(native/resale 选项)| Tmax 深度追踪 | 砍:shadow_sub_role 永远 NULL,用户只能模糊看 |
| View By 切换器多维度 | 产品维度可视化 | 砍:保持品牌维度单一视图 |
| 完整 Tooltip 清单(15 条之外的)| 辅助引导 | 砍:只保留核心 5 条 |
| sales_channels 手动管理 UI | 用户声明渠道关系 | 砍:只依靠 tracked_urls 隐式推导 |
| 渠道表现分析 Agent 模板 | OEM 专属 Analysis 模板 | 砍:用现有综合分析模板 |
| Brainstorming `include_products` 参数 | 生成 topic-only prompts 的选项 | 砍:用户生成后手动删除产品名 |

### 12.3 Roadmap 后续(非本轮)

| 项 | 触发 |
|---|---|
| PG MCP Migration | v1.2 稳定后紧跟 sprint |
| 全站前端汉化专项 | v1.2 稳定后 |
| Phase 3 实时 LLM 抽取 | MRR ≥ $10k 或客户付费要求"自由指引" |
| 中国 AI 平台采集双轨 | 中国市场客户承诺 |
| 独立"产品维度分析" Tab(完整版)| 用户反馈产品维度使用频率高 |
| Peer Match Mode 开关 | Phase 3 切换时重新评估 |
| User Guide / Interactive Tour | Onboarding 复杂度升高 |

### 12.4 工作量分布(MVP only)

| 模块 | 工作量 |
|---|---|
| Schema 设计 + Migration SQL | 2-3 天 |
| Analyzer Parser 改造 | 4-5 天 |
| Citation Parser 方案 B | 3-5 天 |
| SaaS API 适配 + 新端点 | 5-7 天 |
| Admin UI 适配 | 3-5 天 |
| SaaS UI 改造(Settings + Tabs + 最小 Tooltip) | 8-12 天 |
| Agent schema hint 重写 + 基础 metrics | 3-4 天 |
| 测试 + 验收 | 3-5 天 |
| **MVP 小计** | **~30-45 天 / 6-9 周** |
| **+ V2 全量** | **+10-20 天 / 合计 40-65 天 / 8-13 周** |

**建议交付节奏**:
- **MVP 优先**(6-9 周):稳定上线 → 验证 Roborock 无感 + Tmax 基本可用
- **V2 增量发布**(后续 2-4 周):按优先级补 Phase 2 / Auto-discovery / 完整 Tooltip / 新 Tab 等

---

## 13. DB 操作规范(永久规则)

### 13.1 Claude 可自主执行

- ✅ SELECT 查询(任意复杂度)
- ✅ EXPLAIN / EXPLAIN ANALYZE
- ✅ information_schema / pg_catalog 读取

### 13.2 严禁自主执行

- ❌ DDL:CREATE / ALTER / DROP / RENAME TABLE
- ❌ DDL:CREATE / DROP INDEX / CONSTRAINT / TYPE / EXTENSION
- ❌ DML 写入:INSERT / UPDATE / DELETE / UPSERT / TRUNCATE / MERGE
- ❌ 事务控制(SELECT 会话外)
- ❌ GRANT / REVOKE / ALTER USER
- ❌ ALTER DATABASE / SYSTEM

### 13.3 流程

所有非 SELECT SQL,Claude 在文档或对话中以代码块列出,标注:
1. 执行顺序
2. 预期影响(影响行数 / 表)
3. 验证查询
4. 回滚方法或备份前提

由用户在 Cloud SQL 控制台或 `gcloud sql execute` 手动执行。

### 13.4 连接凭证

- Instance:`project-90d7849c-de16-4c15-a0a:us-central1:answer-x-geo-instance`
- User:`answer-x-geo-db-user`
- 本地连接:Cloud SQL Auth Proxy,localhost:5432
- Database:`answer-x-geo-db`

---

## 14. Open Items 与 Roadmap

### 14.1 本轮不做(确认延后)

- **Sentence-level 情感归因**:sentence 级 NLP 成本高,Phase 2 再议
- **Peer Products SOV 专用视图**(独立于 Own Products 的完整 Dashboard 模块):本轮只做嵌入式子视图
- **"独立产品维度分析" Tab**(全站级):本轮在 Visibility 内做增量,独立 Tab 延后
- **Topic↔URL 直接关联**:通过 Product→Topic 间接推导足够,不做直接关联

### 14.2 Roadmap(按优先级)

| 优先级 | 条目 | 触发条件 | 预计 |
|---|---|---|---|
| 🔴 紧接 v1.2 | Vertex AI SDK 迁移(硬截止 2026-06-24)| 6 月前任意空档 | 2-3 天 |
| 🔴 紧接 v1.2 | **PG MCP Migration** | v1.2 稳定后 | 5-8 天 |
| 🟠 高 | **全站前端汉化专项** | v1.2 稳定后 | 3-5 天 |
| 🟠 高 | Admin Web TypeScript 迁移 | 任意时段 | 5-7 天 |
| 🟠 高 | User Guide + Interactive Tour | v1.2 上线后 2-4 周 | 3-5 天 |
| 🟡 中 | Agent Context 管理与压缩 | 对话成本上升 | 5-10 天 |
| 🟡 中 | Agent 跨会话 Memory(Session Summary)| 用户反馈 | 3-5 天 |
| 🟡 中 | Evaluation Sub-Agent | rubric 成熟 | 5-7 天 |
| 🟡 中 | 独立"产品维度分析" Tab | 产品维度使用频率高 | 5-7 天 |
| 🟡 中 | Peer Products SOV 专用视图 | Tmax 深度使用 | 3-5 天 |
| 🟢 触发性 | Phase 3 实时 LLM 抽取 | MRR ≥ $10k | ~2 周 |
| 🟢 触发性 | 中国 AI 平台采集双轨 | 中国市场客户承诺 | 10-16 天 |
| 🟢 触发性 | Product-level Quadrant 分析升级 | Opportunity 产品迭代 | 3-5 天 |
| 🟢 触发性 | Report & HTML 导出升级 | 客户反馈 | 5-7 天 |

### 14.3 架构红线(永久,未来讨论引用)

1. **Alias 语义纯净原则**(§3.1)
2. **业务关系与物理证据分离**(§3.2)
3. **数据驱动可见性**(§3.3)

---

## 15. 附录

### 附录 A:数据量快照(迁移时影响面)

| 表 | 行数 | 处理 |
|---|---|---|
| `geo_clients` | 2 | 加 onboarding_wizard_completed |
| `geo_client_topics` | 2 | 迁 products TEXT[],然后删列 |
| `geo_client_peers` | 17 | 删 is_own_brand |
| `geo_client_domains` | 6 | 扩展列,回填 brand_id |
| `geo_company_mentions` | 10,486 | Rename + brand_role |
| `geo_citations` | 42,607 | 加 3 列,全 NULL |
| `geo_client_prompts` | 76 | 不变 |
| `geo_results` | 2,128 | 不变 |
| `checkpoints` | 2023 | TRUNCATE |
| `agent_messages` | 190 | TRUNCATE |
| `agent_memories` | 6 | TRUNCATE |
| `geo_agent_tasks` | ~N | TRUNCATE |

### 附录 B:决策澄清备忘

完整历史决策(含 v1.0 + v1.1 + 本版):

| 决策 | 结论 | 来源 |
|---|---|---|
| Brand 一等实体(Own + Shadow) | ✅ 采用 | v1.0 |
| Products 结构化表 | ✅ 采用 | v1.0 |
| product_role ENUM vs BOOLEAN | ✅ ENUM | v1.0 |
| brand_role ENUM vs BOOLEAN | ✅ ENUM | v1.0 |
| 分 geo_brand_mentions + geo_peer_mentions 两张表 | ❌ 合并 | v1.0 |
| Topic = 渠道名 | ❌ 否决 | v1.0 |
| Prompt Expander 大改 | ❌ 小改 | v1.0 |
| Case 3 本轮做 | ✅ 做(shadow_sub_role NULLABLE)| v1.2 |
| 用 alias 扁平化替代 Shadow Brand | ❌ 否决(违反 Alias 纯净)| v1.1 |
| Peer 可录 Peer Products | ✅ 支持 | v1.1 |
| Alias 纯净为架构红线 | ✅ 是 | v1.1 |
| Brand/Peer 互斥 | ❌ **破除**(v1.0 定互斥,v1.2 破,BrandParser 去重)| v1.2 |
| Citation + Domain 重构 | ✅ 本轮做(方案 B + Product tracked URLs 拆表)| v1.2 |
| URL 归属校验 trigger | ✅ 本轮做 | v1.2 |
| Product↔Brand 关系建模 | ✅ 独立表 `geo_product_sales_channels` | v1.2 |
| Tracked URLs 含 path-prefix scope | ✅ 支持(Product 变体集合语义)| v1.2 |
| Topic↔URL 直接关联 | ❌ 不做(通过 Product 间接)| v1.2 |
| Phase 2 LLM Batch 本轮做替代 N-gram 主力 | ✅ | v1.2 |
| N-gram 保留为 fallback | ✅ | v1.2 |
| Auto-discovery 本轮做 | ✅ | v1.2 |
| Phase 3 实时 LLM 抽取 | ❌ 本轮不做(触发 MRR ≥ $10k)| v1.2 |
| peer_match_mode 字段预留 | ❌ 本轮否决(YAGNI + 与 Alias 纯净冲突)| v1.2 |
| PG MCP 本轮迁移 | ❌ 下一轮 sprint | v1.2 |
| UI 大改 Visibility 等 Dashboard | ❌ 红线,本轮只做增量 | v1.2 |
| Citation 点击侧抽屉保留 | ✅ 必须保留 | v1.2 |
| Tooltip 系统 | ✅ 本轮做(MVP 最小 15 条 + V2 完整)| v1.2 |
| 新 UI 文案汉化 | ✅ 本轮全部中文 | v1.2 |
| 全站汉化专项 | ⏳ Roadmap 条目 | v1.2 |
| client_type 枚举字段 | ❌ 不加(数据驱动可见性原则)| v1.2 |
| UI 暴露 product_role | ❌ 不暴露(按 Owner 导航隐式推导)| v1.2 |
| shadow_sub_role 默认 | ✅ NULL(不确定)为 UX 默认 | v1.2 |
| Peer SOV 查询基础 | brand_role='peer' → peers 成员身份(正确性修复)| v1.2 |
| product_sales_channels 对 Peer Products 适用? | ❌ 本轮不用(Peer Products 渠道=自己,冗余)| v1.2 |
| Own Product 多 Shadow 渠道支持 | ✅ sales_channels 多行 + tracked_urls 多行 | v1.2 |

### 附录 C:术语中英对照表

| 英文(schema/code) | 中文(UI 显示)|
|---|---|
| Brand (Own) | 自营品牌 / 我的品牌 |
| Shadow Brand | 经销渠道品牌 |
| Peer | 竞品 |
| Own Product | 自家产品 |
| Shadow Brand Product | 渠道上的产品 / 经销渠道产品 |
| Peer Product | 竞品的产品 |
| shadow_sub_role='native' | 渠道自家品牌线 |
| shadow_sub_role='resale' | 渠道代理他人 |
| shadow_sub_role=NULL | 不确定 / 不需要区分 |
| Topic | 追踪话题 |
| Tracked URL | 追踪 URL |
| Domain | 域名 |
| Sales Channel | 销售渠道 |
| Mention | 提及 |
| Citation | 引用 |
| Visibility | 可见度 |
| Share of Voice (SOV) | 声量占比 |
| Co-occurrence | 共现 |
| SKU | SKU(保留英文)|
| Agent | Agent(保留英文)|
| AI | AI(保留英文)|
| URL | URL(保留英文)|
| API | API(保留英文)|

### 附录 D:场景卡片(4 个完整范例)

**场景 A:Roborock 纯自营品牌**

UI 卡片:
```
┌────────────────────────────────────────────────────┐
│ 工作空间:Roborock                                 │
│                                                    │
│ 品牌                                               │
│   我的品牌                                         │
│     • Roborock  [自营品牌]                         │
│       别名:Roborock, ROBOROCK                     │
│       域名:roborock.com 等 3 个                   │
│   经销渠道品牌(0 个)                              │
│                                                    │
│ 追踪话题                                           │
│   • 智能家居清洁                                   │
│     • S8 Pro Ultra  [自家产品]                     │
│       匹配变体:S8 Pro Ultra, Roborock S8 Pro Ultra│
│                                                    │
│ 竞品                                               │
│   • iRobot, Dyson, Ecovacs, Dreame, Narwal         │
└────────────────────────────────────────────────────┘
```

数据:
```
geo_client_brands:
  (Roborock, is_shadow=false, aliases=[Roborock, ROBOROCK, ...])

geo_client_peers:
  (iRobot), (Dyson), (Ecovacs), (Dreame), (Narwal)

geo_client_topics: (Smart Home Cleaning)

geo_client_topic_products:
  (S8 Pro Ultra, product_role='own', match_variants=[S8 Pro Ultra, Roborock S8 Pro Ultra])

geo_client_domains:
  (roborock.com,      scope='whole', brand_id=Roborock)
  (us.roborock.com,   scope='whole', brand_id=Roborock)
  (global.roborock.com, scope='whole', brand_id=Roborock)

geo_product_tracked_urls: (可选)
  (url='us.roborock.com/products/s8-pro-ultra', scope='exact', 
   product=S8 Pro Ultra, brand=Roborock)
```

**场景 B:Stanley 自营 + 第三方平台**

UI 卡片(关键差异):
```
品牌
  我的品牌
    • Stanley  [自营品牌]
      域名:stanley1913.com
  经销渠道品牌
    • Amazon  [经销渠道]
      域名:amazon.com/stores/stanley1913/(路径前缀)
    • Walmart  [经销渠道]
      域名:walmart.com/ip/stanley/(路径前缀)

追踪话题
  • 保温杯
    • Stanley Quencher H2.0 40oz  [自家产品]
      匹配变体:Quencher 40oz, H2.0 40oz, Adventure Quencher
      🔗 追踪 URL(3):
        - stanley1913.com/.../adventure-quencher... (精确)
        - amazon.com/dp/B07L8XHJMS (精确)
        - walmart.com/ip/.../12345 (精确)
      🏪 销售渠道:Stanley · Amazon · Walmart
```

数据:
```
geo_client_brands:
  (Stanley, is_shadow=false)
  (Amazon,  is_shadow=true)
  (Walmart, is_shadow=true)

geo_client_peers: (YETI, Hydro Flask, Owala)

geo_client_topic_products:
  (Quencher H2.0 40oz, product_role='own', match_variants=[...])

geo_client_domains:
  (stanley1913.com,                  scope='whole',       brand=Stanley)
  (amazon.com/stores/stanley1913/,   scope='path-prefix', brand=Amazon)
  (walmart.com/ip/stanley/,          scope='path-prefix', brand=Walmart)

geo_product_tracked_urls:
  (stanley1913.com/.../adventure-quencher-40oz, exact, Quencher, Stanley)
  (amazon.com/dp/B07L8XHJMS,                    exact, Quencher, Amazon)
  (walmart.com/ip/stanley-quencher/12345,       exact, Quencher, Walmart)

geo_product_sales_channels:
  (Quencher, Stanley), (Quencher, Amazon), (Quencher, Walmart)
```

**场景 C:Tmax 纯 OEM/ODM(不激活 Case 3)**

UI 卡片(关键差异):
```
品牌
  我的品牌(0 个) ← OEM 分支下折叠
  经销渠道品牌
    • Rough Country  [经销渠道]
      别名:Rough Country, RoughCountry, RC
      域名:roughcountry.com, roughcountry.com/step-series/
      该渠道下的产品:
        • Nitro II Lift Kit
        • XYZ-Bar
竞品
  • ARB, WARN, Smittybilt
  • Rough Country(作为竞品身份) 
    ℹ️ 产品管理请在"品牌 → Rough Country"下查看
追踪话题
  • 越野踏板
    • HT-70911 踏板  [自家产品]
      匹配变体:HT-70911, HT Series, ESR70911
      🔗 追踪 URL:roughcountry.com/product/ht-70911
      🏪 销售渠道:Rough Country
```

数据:
```
geo_client_brands:
  (Rough Country, is_shadow=true)
  -- 没有 Own Brand

geo_client_peers:
  (ARB), (WARN), (Smittybilt),
  (Rough Country)  -- 🆕 破互斥

geo_client_topic_products:
  (HT-70911,            product_role='own')
  (Nitro II Lift Kit,   product_role='shadow_brand_product', 
                        shadow_sub_role=NULL, owner_brand=RC)
  (XYZ-Bar,             product_role='shadow_brand_product',
                        shadow_sub_role=NULL, owner_brand=RC)

geo_client_domains:
  (roughcountry.com,                scope='whole',       brand=RC)
  (roughcountry.com/step-series/,   scope='path-prefix', brand=RC)

geo_product_tracked_urls:
  (roughcountry.com/product/ht-70911, exact, HT-70911, RC)

geo_product_sales_channels:
  (HT-70911, RC)
```

**场景 D:Tmax OEM + Case 3 激活(深度追踪)**

相对场景 C 的差异(仅 shadow_sub_role 值):
```
geo_client_topic_products:
  (Nitro II Lift Kit, shadow_sub_role='native',  owner_brand=RC)
  (XYZ-Bar,           shadow_sub_role='resale', owner_brand=RC, owner_peer=某 OEM)
```

UI 额外解锁:
- 渠道上产品分布(按 sub_role 细分)chart
- Shadow × Peer Product 共现(Case 3 核心指标)

### 附录 E:本版更新索引(传统 spec 读者)

相对 v1.0/v1.1 的实质变化:

- **schema**:新增 `geo_product_sales_channels`、`geo_product_tracked_urls`、`geo_settings_candidates`;扩展 `geo_client_domains`、`geo_citations`
- **product_role**:从 3 值(own / shadow_brand_native / peer)改为 3 值 + nullable sub_role(own / shadow_brand_product[+sub_role] / peer)
- **互斥**:破除 Brand/Peer 互斥(新增 BrandParser 去重规则)
- **Parser**:CitationParser 方案 B(双表两阶段 + citation_role enum)
- **Phase 2 / Auto-discovery**:从 Roadmap 延后项 → 本轮纳入(替代 N-gram 主力)
- **UI 原则**:明确红线(不动现有 Dashboard)+ 允许增量
- **Tooltip**:系统设计 + 完整文案清单(15 条核心)
- **Scope 标签**:MVP vs V2 完整映射(§12)
- **架构红线**:Alias 纯净 / 业务-物理分离 / 数据驱动可见性(三条永久原则)

---

## 下一步

1. **Plan 更新**:基于 MVP scope 更新 [2026-04-18-dual-mode-tracking-plan.md](../plans/2026-04-18-dual-mode-tracking-plan.md) 或新建 v1.2 Plan,按 MVP 55-65 task 拆分
2. **Migration SQL 文件**:按 §11.1 顺序拆分为多个 migration `.sql` 文件,供用户手动执行
3. **Phase 1 审阅节点**:开始对 11 行 metrics + 8 个模板 wizard_config 做 Gap 审阅,产出具体新 SQL
4. **实施启动**:subagent-driven execution,按 MVP scope 推进

---

*本文件是 dual-mode tracking 迭代的 Finalized 版本,基于 2026-04-18~20 思聪与 Wentao Li 的深度对话纪要、Profound 对标分析、以及 v1.0 / v1.1 的全部决策整合而成。*

*架构红线(§3)的三条原则永久适用于后续所有 schema 讨论。未来若需突破,必须显式在 Spec 文档中记录破例理由。*
