# Dual-Mode Tracking:Brand-level 与 Product/SKU-level GEO 追踪统一设计

> **日期**:2026-04-18
> **作者**:lancelot × Claude
> **目标读者**:CTO(开发与部署)、产品团队(客户对接)
> **状态**:待评审(Design Phase)

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [产品设计:面向品牌客户与 ODM/OEM 客户的统一实体模型](#2-产品设计面向品牌客户与-odmoem-客户的统一实体模型)
3. [技术设计:数据模型变更](#3-技术设计数据模型变更)
4. [技术设计:Parser 架构与 Analyzer Pipeline](#4-技术设计parser-架构与-analyzer-pipeline)
5. [技术设计:Agent NL2SQL 与配置类 SQL 适配 + 全局影响面审计](#5-技术设计agent-nl2sql-与配置类-sql-适配)
6. [技术设计:SaaS Insights 可视化 + 前端 UI + Onboarding Wizard](#6-技术设计saas-insights-与前端适配)
   - 6.0 整体可视化策略
   - 6.1 Visibility Dashboard(含 Brand/Product/Topic 多视角 + Brand×Product 共现)
   - 6.2 Citation Dashboard
   - 6.3 Sentiment Dashboard(含 entity-level 归因)
   - 6.4 Sentiment 精细归因的概念澄清
   - 6.5 后端 API 改动清单(含新增端点)
   - 6.6 前端组件改动清单(含新增组件)
   - 6.7 UI 渐进披露(Progressive Disclosure)策略
   - 6.8 Topic-only / 数据稀疏场景的 Fallback 逻辑(空数据 Empty State + Availability API)
   - 6.9 Onboarding Wizard:Brand-first vs OEM 两分支引导
7. [技术设计:Prompt Expander 与 Topic-only 模式](#7-技术设计prompt-expander-与-topic-only-模式)
8. [Migration Plan(所有 DDL/DML 由用户手动执行)](#8-migration-plan所有-ddldml-由用户手动执行)
9. [数据库操作规范(永久性规定)](#9-数据库操作规范永久性规定)
10. [Open Items 与后续迭代](#10-open-items-与后续迭代)
    - 10.1 本次不做的项
    - 10.2 本次不做、可能未来需要的项
    - 10.3 本次顺带清理的技术债
    - 10.4 `geo_client_prompts.product` 的讨论(保留 TEXT,不改 FK)

---

## 1. 背景与动机

### 1.1 我们现在的位置

AnswerX GEO 平台目前假设"**客户 = 品牌**"的隐式契约:

- `geo_clients.name` 默认被当作品牌名使用
- `company_parser.py` 用 client.name + aliases 在 AI 回答里做正则匹配,识别"自有品牌 mentions"
- `geo_client_peers` 存储竞品品牌,同一个 parser 识别"竞品 mentions"
- Visibility / SOV / Sentiment 全部建立在这个品牌层 mention 基础上

这套模型对**自有品牌出海客户**(Roborock 类)完美适用。

### 1.2 为什么现在这套模型对 ODM/OEM 客户失效

以客户**杭州天铭科技(Tmax)**为例:

- Tmax 在中国是一家**代工/ODM 厂商**,生产越野车电动踏板等配件
- 在美国市场,Tmax 没有独立品牌站,**全部通过 Rough Country(RC)这一家经销商贴牌销售**
- RC 不在产品页透出 "Tmax" 品牌;终端消费者看到的永远是 "Rough Country" 品牌
- AI 搜索引擎的训练语料里**从来没有 "Tmax" 这个名字**——AI 不可能在回答里说 "Tmax 的 HT-Series 怎么样"

**结论**:传统的"品牌层 mention 追踪"在 Tmax 这种 ODM/OEM 客户身上**信号为零**。Tmax 如果用当前系统,Visibility 永远是 0,SOV 无意义,Sentiment 没有附着对象。

### 1.3 中国 OEM/ODM 出海体量的战略意义

基于公开行业数据(China 2024 exports $3.4T+):

- **自有品牌出海**(Roborock / Anker / DJI 等)估算企业数:~1 万家
- **OEM/ODM 出海**(按较有规模的工厂计)估算:**>10 万家**,是自有品牌的 10 倍以上

细分品类里 OEM 占比:
- 汽车/越野配件(Tmax 所在):>60%
- 消费电子:>60%
- 电动工具:>70%
- 户外装备:中偏高
- 专业美妆:中

**产品/SKU 级追踪的真实可行性**(联网验证):AI 搜索引擎(ChatGPT / Perplexity)**会在回答里引用具体的型号/SKU**,例如跑鞋场景返回 "Nike Air Zoom Pegasus 41 / Brooks Ghost 16 / Hoka Clifton 9",耳机返回 "Sony WH-1000XM5"。只要产品本身有**独特的型号命名空间**(SKU 编码、型号系列、连字符模型名等),字面正则匹配就能可靠提取 mentions。

并非所有 OEM 都适合——**汽配/电子/工具/户外等"有技术含量、有型号规范"的品类约占 OEM 总量的 30-40%**,这部分是本次扩展的**目标客户**。纯通用商品 OEM(如白标马克杯、基础服装)的产品命名空间太弱,GEO 本身对他们就没有价值。

### 1.4 本次迭代目标

1. **引入 Brand 作为一等实体**,使客户可以追踪自有品牌 + 多个"Shadow Brand"(如经销商品牌)
2. **把 Products 提升为可匹配实体**,支持 SKU/型号级别的 mention 追踪
3. **Visibility / Citation / Sentiment 三大维度都支持品牌层 + 产品层双视角**
4. **对存量 Roborock 类客户完全兼容**——默认行为等价于今天,产品级信号作为增量"免费赠送"
5. **对 Tmax 类 ODM/OEM 客户开箱即用**——通过合理配置即可追踪完整的 Shadow Brand + SKU 组合

---

## 2. 产品设计:面向品牌客户与 ODM/OEM 客户的统一实体模型

> **本章只描述产品概念和用户心智,不涉及数据库表结构或字段名**。技术实现细节见第 3 章之后。

### 2.1 核心概念:五类实体

AnswerX 的 tracking 配置由五类实体组成,客户填什么就追踪什么:

| 实体 | 含义 | 对自有品牌客户(Roborock) | 对 ODM/OEM 客户(Tmax) |
|---|---|---|---|
| **Client(工作空间)** | 工作空间标识,等同于租户 | Roborock | Tmax Technology / 杭州天铭科技 |
| **Brands(关注的品牌)** | 客户想追踪的品牌名列表。可以是自有,也可以是 Shadow(经销商) | `[Roborock]` | `[Rough Country]`(Shadow)或 `[Rough Country, Other Distributor]` |
| **Peers(竞争品牌)** | 独立竞品的品牌名列表 | `[Dreame, Ecovacs, iRobot, …]` | `[ARB, WARN, Smittybilt, …]` |
| **Topics(追踪话题)→ Products(产品 SKU)** | Topic 是语义分类(品类或场景);Products 是 Topic 下可选的具体 SKU 列表 | Topics: `Smart Home / Pet Friendly`;Products: `S8 Pro Ultra / Q7 Max` | Topics: `Off-Road Running Boards`;Products: `HT-Series / HT-70911 / …` |
| **Domains(自有/渠道域名)** | 标识客户拥有或合作的域名(含 URL 路径前缀) | `[roborock.com, us.roborock.com]` | `[roughcountry.com/product/ht-series-]` |

### 2.2 Brand 实体:Own vs Shadow

**Brand 是本次迭代新增的一等实体**。每个 Client 可以维护一个或多个 Brand,每个 Brand 有一个简单的"类型"标签:

| Brand 类型 | 含义 | 举例 |
|---|---|---|
| **Own Brand(自有品牌)** | 客户自己注册、拥有、对外售卖的品牌 | Roborock 的 "Roborock";如果 Tmax 将来在美国建立独立品牌,那也是 Own |
| **Shadow Brand(影子品牌)** | 客户借助的外部品牌(通常是经销商/合作渠道),产品实际透出的就是这个品牌名 | Tmax 的 "Rough Country";任何走 OEM 的工厂在经销商那里的品牌 |

对系统而言,Own 和 Shadow 在 mention 匹配时处理逻辑**完全一样**——都是"我关心的 brand,当 AI 提到它就算自有品牌层 mention"。两者的区别只在**客户心智和报表分区展示**上。

### 2.3 完整的配置范例:三种典型客户形态

#### 形态 A:自有品牌客户(Roborock)

```
┌────────────────────────────────────────────────────────────────┐
│ Client:  Roborock                                              │
├────────────────────────────────────────────────────────────────┤
│ Brands:                                                        │
│   • Roborock                                   (Own Brand)     │
│     aliases: [Roborock, ROBOROCK, Roborock Technology]         │
├────────────────────────────────────────────────────────────────┤
│ Peers:                                                         │
│   • iRobot         aliases: [iRobot, Roomba, iRobot Roomba]    │
│   • Dyson          aliases: [Dyson]                            │
│   • Ecovacs        aliases: [Ecovacs, ECOVACS, Deebot]         │
│   • Dreame         aliases: [Dreame, DreameBot]                │
│   • Narwal         aliases: [Narwal]                           │
├────────────────────────────────────────────────────────────────┤
│ Topics:                                                        │
│   ┌────────────────────────────────────────────────┐           │
│   │ "Smart Home" (semantic_topic)                  │           │
│   │   Products:                                    │           │
│   │     • "S8 Pro Ultra"                           │           │
│   │         match_variants: [S8 Pro Ultra,         │           │
│   │                         Roborock S8 Pro Ultra] │           │
│   │         product_role: own                      │           │
│   │     • "Q7 Max"                                 │           │
│   │         match_variants: [Q7 Max, Q7Max]        │           │
│   │         product_role: own                      │           │
│   └────────────────────────────────────────────────┘           │
│   ┌────────────────────────────────────────────────┐           │
│   │ "Pet Hair Cleaning" (semantic_topic)           │           │
│   │   Products:                                    │           │
│   │     • "S8 MaxV Ultra"                          │           │
│   │         match_variants: [S8 MaxV Ultra]        │           │
│   │         product_role: own                      │           │
│   └────────────────────────────────────────────────┘           │
├────────────────────────────────────────────────────────────────┤
│ Domains:                                                       │
│   • roborock.com              (whole-domain own)               │
│   • us.roborock.com           (whole-domain own)               │
│   • global.roborock.com       (whole-domain own)               │
└────────────────────────────────────────────────────────────────┘
```

**追踪效果**:
- 品牌层:Roborock 自有 mentions vs Dreame/Ecovacs/iRobot 等 peer mentions
- 产品层(新增):S8 Pro Ultra / Q7 Max 等产品名直接 mention,可看单品表现
- Citation:所有 roborock.com 的 URL 算 Owned Media
- Sentiment:品牌级 + 产品级均可细分

**对 Roborock 用户侵蚀**:**零侵蚀**。Products 现在必须至少有 `name`(原来已有),`match_variants` 可选(不填默认使用 name 做匹配)。`product_role` 默认 own,UI 层可对普通用户隐藏。

#### 形态 B:纯 ODM/OEM 客户(Tmax)

```
┌────────────────────────────────────────────────────────────────┐
│ Client:  Tmax Technology (杭州天铭科技)                         │
│          (workspace 标识,不参与任何 mention 匹配)               │
├────────────────────────────────────────────────────────────────┤
│ Brands:                                                        │
│   • Rough Country                              (Shadow Brand)  │
│     aliases: [Rough Country, RoughCountry, RC]                 │
│   • Other Distributor Brand                    (Shadow Brand)  │
│     aliases: […]                                               │
│     (可选,多个 Shadow Brand 并列)                              │
├────────────────────────────────────────────────────────────────┤
│ Peers:                                                         │
│   • ARB            aliases: [ARB, ARB 4x4]                     │
│   • WARN           aliases: [WARN, WARN Industries]            │
│   • Smittybilt     aliases: [Smittybilt]                       │
│   • Bushwacker     aliases: [Bushwacker]                       │
├────────────────────────────────────────────────────────────────┤
│ Topics:                                                        │
│   ┌────────────────────────────────────────────────┐           │
│   │ "Off-Road Running Boards" (semantic_topic)     │           │
│   │   Products:                                    │           │
│   │     • "HT-Series Power Running Boards"         │           │
│   │         match_variants:                        │           │
│   │           - HT-Series                          │           │
│   │           - HT Series                          │           │
│   │           - HT-Series Power Running Boards     │           │
│   │           - Power Running Boards HT            │           │
│   │           - HT-70911                           │           │
│   │           - ESR70911                           │           │
│   │         product_role: own                      │           │
│   └────────────────────────────────────────────────┘           │
│   ┌────────────────────────────────────────────────┐           │
│   │ "Off-Road Bumpers" (semantic_topic)            │           │
│   │   Products:                                    │           │
│   │     • "TM-Bumper-Series"                       │           │
│   │         match_variants: [TM-Bumper, TM-B-1024] │           │
│   │         product_role: own                      │           │
│   └────────────────────────────────────────────────┘           │
├────────────────────────────────────────────────────────────────┤
│ Domains:                                                       │
│   • roughcountry.com/product/ht-series-   (URL path-prefix)    │
│   • roughcountry.com/product/tm-bumper-   (URL path-prefix)    │
└────────────────────────────────────────────────────────────────┘
```

**追踪效果**:
- 品牌层:Rough Country 作为 Shadow Brand 的 mention 数 + Peer(ARB/WARN/等)的 mention 数
- 产品层:HT-Series / HT-70911 等具体 SKU 的 mention 数(Tmax 实际关心的核心指标)
- **关键组合指标**:"我的产品在 Shadow Brand 上的表现" = 同一条 AI response 里**共现** "Rough Country" brand mention + "HT-Series" product mention 的次数(见第 2.5 节)
- Citation:`roughcountry.com/product/ht-series-*` 的 URL 算 Owned Media(上一轮 URL 前缀 own 机制);其他 `roughcountry.com` 的 URL 算 Channel(由 domain_classifier 判定)
- Sentiment:可以分别看"RC 品牌 sentiment"、"HT-Series 产品 sentiment"、"HT-Series 出现在 RC 语境里的 sentiment"

#### 形态 C:高级 ODM/OEM 追踪(通过 UI 折叠区暴露的可选配置)

Tmax 如果想追踪"同一渠道(RC)上的竞品 SKU"或"RC 自营非 OEM 产品线",可以通过 Products 的 `product_role` 字段扩展配置。

**请注意以下三层一次性到位,不分阶段发布**:
- **数据库 schema**:`product_role` 三值枚举 + `owner_brand_id` / `owner_peer_id` 两个 FK 本次全部建好
- **后端代码**:Parser 能识别并写入所有三种 role 的产品 mention,Insights API 支持按 role 过滤
- **前端 UI**:同一次上线包含这些字段的配置入口,但**高级字段默认折叠在 "Advanced" 区域**。普通客户(Roborock、默认 Tmax)进入 Settings 看不到这些,只看到简化的 `name + match_variants`;有需要的客户点击 "Show advanced product options" 即可展开,**不需要等下一个版本**。

这是 **UX 渐进披露(progressive disclosure)**,不是 **功能分版本发布**。高级用法举例:

```
┌────────────────────────────────────────────────────────────────┐
│ Topics (extended):                                             │
│   ┌────────────────────────────────────────────────┐           │
│   │ "Off-Road Running Boards"                      │           │
│   │   Products:                                    │           │
│   │     • "HT-Series"                              │           │
│   │         product_role: own                      │           │
│   │     • "Nitro II Lift Kit"  (RC 自家非 OEM)      │           │
│   │         product_role: shadow_brand_native      │           │
│   │         owner_brand → "Rough Country"          │           │
│   │     • "ARB Bull Bar Deluxe"  (渠道上的竞品 SKU) │           │
│   │         product_role: peer                     │           │
│   │         owner_peer → "ARB"                     │           │
│   └────────────────────────────────────────────────┘           │
└────────────────────────────────────────────────────────────────┘
```

对应的三值枚举 `product_role`:

| `product_role` | 含义 | 举例 |
|---|---|---|
| `own` | 客户自己供货或拥有的产品(默认) | Tmax 的 HT-Series;Roborock 的 S8 Pro Ultra |
| `shadow_brand_native` | 某个 Shadow Brand 自己做的、非 OEM 的产品 | RC 自家的 Nitro II Lift Kit(不是 Tmax 供货的) |
| `peer` | 在同一话题下追踪的竞品 SKU | ARB 的 Bull Bar Deluxe(即使它也在 RC 上卖) |

### 2.4 Topic 的建模定位

Topic 在系统里是一个**语义分组字符串**。客户可以选择两种等价的命名风格:

| 命名风格 | 举例 | 适用场景 |
|---|---|---|
| **按业务品类** | `Off-Road Running Boards`、`Robot Vacuums` | Tmax 类 ODM/OEM,业务粒度清晰 |
| **按用户痛点/场景** | `Pet Hair Cleaning`、`Large House Quick Cleaning` | Roborock 类自有品牌,用户心智驱动 |

**反对的用法**:Topic = 渠道名(如 Topic = "Rough Country")。理由:
- Topic 驱动 Prompt Expander 生成 client prompts,AI 用户不会问"What is Rough Country?"——他们问 "What's the best running board for Ford F-150?"
- 渠道的可见度已经由 Domain + Citation 的 Channel category 机制覆盖,不需要在 Topic 层再造一套

### 2.5 三种观察诉求的满足方式

对 ODM/OEM 客户(Tmax),本设计覆盖三种核心观察诉求:

| 诉求 | 怎么实现 |
|---|---|
| **诉求 1:我的产品在 AI 里整体可见度** | 产品层 mentions 按 `product.name` 聚合,筛选 `product_role=own` |
| **诉求 2:Shadow Brand 本身在 AI 里的可见度** | 品牌层 mentions 按 `brand_name` 聚合,筛选 "shadow" 分类 |
| **诉求 3:我的产品在 Shadow Brand 上的表现**(核心 OEM 诉求) | **同一条 AI response 里**:brand mention(Shadow)∩ product mention(Own)的交集 —— 比如 AI 同时提到 "Rough Country" 和 "HT-Series",即算一次 Tmax 在 RC 上的精准命中 |

典型的 Tmax 使用场景:

- **场景 i:Discovery prompt** —— 用户问 `"In Rough Country, which side step is best for Ford?"`,AI 答 `"...the HT-Series running boards from Rough Country are a popular choice..."`
  - 识别为:Shadow Brand mention("Rough Country")+ Own Product mention("HT-Series")共现
  - Tmax 看到:一次 Discovery 场景命中

- **场景 ii:Comparison prompt** —— 用户问 `"Compare Rough Country's HT Series Step vs Smittybilt's"`,AI 答 `"HT-Series from Rough Country has XX, while Smittybilt's YY offers ZZ..."`
  - 识别为:Shadow Brand("Rough Country")、Own Product("HT-Series")、Peer("Smittybilt")共现
  - Tmax 看到:一次 Comparison 场景命中,且可追踪 HT-Series 附近文本的 Sentiment

### 2.6 Parser 运行策略:纯数据驱动,无用户开关

系统**永远并行跑所有 Parser**(Brand + Product),无需用户显式开关:

- 客户填了 Brands → BrandParser 有对象可匹配,产出 brand mentions
- 客户填了 Products(含 match_variants) → ProductParser 有对象可匹配,产出 product mentions
- 客户只填 Topic 没填 Products → ProductParser 空 list 直接跳过(零开销)
- 两边都填 → 都跑,互不干扰

Insights UI 层**纯数据驱动**:
- 有 brand 数据时展示 brand 视图
- 有 product 数据时展示 product 视图
- 两边都有时并列展示
- **不提供用户偏好开关**

### 2.7 同一个名字在 Brands 与 Peers 表中互斥

**禁止**同一个字符串(如 "Rough Country")同时出现在 `geo_client_brands` 和 `geo_client_peers`——这会导致匹配时双重计数、语义混乱。

客户必须做语义选择:
- RC 是 **Shadow Brand**(我在这渠道有货) → 放 Brands
- RC 是 **Peer**(纯竞品,我没有合作) → 放 Peers

对于**"RC 既是 Shadow Brand 又有自营竞品线"**这种边界情况,通过 **Product 层的 `product_role='shadow_brand_native'`** 精细化表达,而非在 Brand 层混放。

### 2.8 Topic-only 宽松模式

允许客户建 Topic **不配置任何 Products**。此时:

- Prompt Expander 仍然基于 Topic name 生成 client prompts(例如 "Best running shoes for trail" 不需要具体型号也能出 prompts)
- Analyzer 的 ProductParser 对该 Topic 无事可做,跳过
- BrandParser 和 Peer 匹配正常运行
- Insights 展示品牌/peer 层数据,产品层空白自动隐藏

这是**合理的 degraded 模式**,不需要特殊处理。

---

## 3. 技术设计:数据模型变更

### 3.1 变更概览

| 操作 | 对象 | 说明 |
|---|---|---|
| 🆕 新建 | `geo_client_brands` | 客户维护的品牌列表(Own + Shadow) |
| 🆕 新建 | `geo_client_topic_products` | 从 `geo_client_topics.products` TEXT[] 迁移出的结构化产品表 |
| 🆕 新建 | `geo_product_mentions` | 产品级 mention 结果表 |
| ♻️ 重命名 | `geo_company_mentions` → `geo_brand_mentions` | 表意更准确;同时升级字段 |
| ♻️ 改字段 | `geo_company_mentions.is_own_brand` → `geo_brand_mentions.brand_role` | BOOLEAN → ENUM(`own` / `shadow` / `peer`) |
| 🗑️ 删列 | `geo_client_peers.is_own_brand` | 验证确认全库 0 行 true,纯遗留列 |
| 🗑️ 删列 | `geo_client_topics.products` TEXT[] | 数据已迁移到 `geo_client_topic_products`,删除源列 |

所有 DDL 放在第 8 章,由用户手动在 Cloud SQL 执行。

### 3.2 新表详细定义

#### 3.2.1 `geo_client_brands`

```sql
CREATE TABLE geo_client_brands (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id   UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    brand_name  TEXT NOT NULL,
    aliases     TEXT[] NOT NULL DEFAULT '{}',
    is_shadow   BOOLEAN NOT NULL DEFAULT false,
        -- false = 客户自营品牌(Own,Roborock 场景默认)
        -- true  = 客户借用的 Shadow Brand(Tmax 的 Rough Country 场景)
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, brand_name)
);

CREATE INDEX idx_geo_client_brands_client ON geo_client_brands(client_id) WHERE is_active = true;
```

**与 `geo_clients.name` 的关系**:
- `geo_clients.name` 继续存在,作为 **workspace 显示名**,不再承担"客户自有品牌"的语义
- 对自有品牌客户(Roborock):migration 阶段会自动为每个现有 client 在 `geo_client_brands` 插入一条 `brand_name = client.name, is_shadow = false` 的行,确保老行为无缝延续
- 对 ODM/OEM 客户(Tmax):`geo_clients.name` 可能就是 "Tmax Technology",但 `geo_client_brands` 里只有 Shadow 行

#### 3.2.2 `geo_client_topic_products`

```sql
CREATE TABLE geo_client_topic_products (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic_id        UUID NOT NULL REFERENCES geo_client_topics(id) ON DELETE CASCADE,
    client_id       UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_name    TEXT NOT NULL,
        -- 主产品名,UI 上作为"产品标识"展示,也作为 match_variants 的默认第一项
    match_variants  TEXT[] NOT NULL DEFAULT '{}',
        -- 用于正则匹配 AI 回答的字符串变体集合
        -- 典型内容:SKU 编码、型号名、品牌+型号组合、空格/连字符变体
        -- 若此列为空,则使用 product_name 本身做匹配
    product_role    TEXT NOT NULL DEFAULT 'own'
                    CHECK (product_role IN ('own', 'shadow_brand_native', 'peer')),
    owner_brand_id  UUID REFERENCES geo_client_brands(id) ON DELETE SET NULL,
        -- 仅在 product_role='shadow_brand_native' 时使用
        -- 指向 geo_client_brands 中某个 Shadow Brand,表达"这是 X 牌自营非 OEM 产品"
    owner_peer_id   UUID REFERENCES geo_client_peers(id) ON DELETE SET NULL,
        -- 仅在 product_role='peer' 时使用
        -- 指向 geo_client_peers 中某个 peer,表达"这是 X 竞品的 SKU"
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT product_role_fk_consistency CHECK (
        (product_role = 'own'                 AND owner_brand_id IS NULL AND owner_peer_id IS NULL) OR
        (product_role = 'shadow_brand_native' AND owner_brand_id IS NOT NULL AND owner_peer_id IS NULL) OR
        (product_role = 'peer'                AND owner_brand_id IS NULL AND owner_peer_id IS NOT NULL)
    )
);

CREATE INDEX idx_geo_client_topic_products_topic ON geo_client_topic_products(topic_id) WHERE is_active = true;
CREATE INDEX idx_geo_client_topic_products_client ON geo_client_topic_products(client_id) WHERE is_active = true;
```

**迁移说明**:`geo_client_topics.products` 是一个 TEXT[] 列,当前两个 topic 有值(`['Robot Vacuum', 'Wet Dry Vacuum']` 等)。数据迁移时把每个元素拆成一行新表记录,`product_name = 元素值`,`match_variants = ARRAY[元素值]`(即以主名做默认匹配),`product_role = 'own'`。详见第 8 章 migration SQL。

#### 3.2.3 `geo_brand_mentions`(重命名自 `geo_company_mentions`)

```sql
-- 重命名表
ALTER TABLE geo_company_mentions RENAME TO geo_brand_mentions;

-- 新字段:brand_role(替代 is_own_brand)
ALTER TABLE geo_brand_mentions
    ADD COLUMN brand_role TEXT
    CHECK (brand_role IN ('own', 'shadow', 'peer'));

-- 数据迁移:is_own_brand=true -> 'own',is_own_brand=false -> 'peer'
UPDATE geo_brand_mentions
SET brand_role = CASE
    WHEN is_own_brand = true THEN 'own'
    ELSE 'peer'
END;

-- 收紧为 NOT NULL
ALTER TABLE geo_brand_mentions ALTER COLUMN brand_role SET NOT NULL;

-- 删除 is_own_brand 列
ALTER TABLE geo_brand_mentions DROP COLUMN is_own_brand;

-- company_name 列建议也改名为 brand_name(可选但推荐)
ALTER TABLE geo_brand_mentions RENAME COLUMN company_name TO brand_name;
```

注意:历史数据没有 `shadow` 类别,迁移后只有 `own` 和 `peer`。新数据开始后,如果客户配置了 Shadow Brand,新产生的 mentions 会正确写 `shadow`。

新表最终结构:

| 列名 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| client_prompt_id | UUID | FK |
| task_id | UUID | FK |
| result_id | INTEGER | FK |
| client_id | UUID | FK |
| **brand_name** | TEXT | (重命名自 company_name)匹配到的品牌名 |
| mention_position | INTEGER | 在 response 里的出现顺序 |
| **brand_role** | TEXT | (新增)`own` / `shadow` / `peer` |
| executed_at | TIMESTAMPTZ | - |
| created_at | TIMESTAMPTZ | - |

> **关于两个 role enum 的命名不对称**:`geo_brand_mentions.brand_role` 的 `shadow` 表示 "**这个品牌**是客户借用的 Shadow";`geo_client_topic_products.product_role` / `geo_product_mentions.product_role` 的 `shadow_brand_native` 表示 "**这个产品**是某个 Shadow Brand 自家(非 OEM)的产品"。语义不同,所以用了不同的 enum 名。两个 enum 对应的现实概念请参考第 2.2 节和第 2.3 节形态 C。

#### 3.2.4 `geo_product_mentions`(全新)

```sql
CREATE TABLE geo_product_mentions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_prompt_id    UUID NOT NULL,
    task_id             UUID,
    result_id           INTEGER NOT NULL,
    client_id           UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_id          UUID REFERENCES geo_client_topic_products(id) ON DELETE SET NULL,
    product_name        TEXT NOT NULL,
        -- denormalized,便于 product 删除后仍能查询历史
    product_role        TEXT NOT NULL
                        CHECK (product_role IN ('own', 'shadow_brand_native', 'peer')),
    owner_brand_id      UUID,
        -- denormalized 副本,避免聚合时 join
    owner_brand_name    TEXT,
    owner_peer_id       UUID,
    owner_peer_name     TEXT,
    mention_position    INTEGER,
    executed_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_geo_product_mentions_client ON geo_product_mentions(client_id, executed_at DESC);
CREATE INDEX idx_geo_product_mentions_result ON geo_product_mentions(result_id, client_id);
CREATE INDEX idx_geo_product_mentions_role ON geo_product_mentions(client_id, product_role);
```

**为什么 denormalize `owner_brand_name` / `owner_peer_name`**:Dashboard 的聚合查询(SOV、Top-N 产品等)频繁按这些字段分组;如果每次 JOIN 三张表会拖慢查询。denormalized 副本在 Parser 写入时一次固化。

### 3.3 `geo_client_peers` 字段清理

```sql
-- is_own_brand 全库 0 个 true(已验证),纯遗留列,安全删除
ALTER TABLE geo_client_peers DROP COLUMN is_own_brand;
```

### 3.4 `geo_client_topics.products` 字段删除(迁移后)

```sql
-- 在完成 geo_client_topic_products 数据迁移并验证后执行
ALTER TABLE geo_client_topics DROP COLUMN products;
```

---

## 4. 技术设计:Parser 架构与 Analyzer Pipeline

### 4.1 Parser 设计:两个 Parser,一张 Brand 表 + 一张 Product 表

原有的 `company_parser.py` 承担了"匹配 client 自有品牌 + 匹配 peers"两个职责。新架构合并 + 拆分后:

| Parser | 新文件名 | 职责 |
|---|---|---|
| **BrandParser** | `geo_analyzer/src/parsers/brand_parser.py`(重命名自 `company_parser.py`) | 匹配 `geo_client_brands`(own + shadow) + `geo_client_peers`。产出 `geo_brand_mentions`,字段 `brand_role` 区分三类 |
| **ProductParser** | `geo_analyzer/src/parsers/product_parser.py`(新建) | 匹配 `geo_client_topic_products` 所有 is_active 产品的 `match_variants`。产出 `geo_product_mentions` |
| CitationParser | `geo_analyzer/src/parsers/citation_parser.py`(已在上一轮升级,不动) | URL 级 own 判定(whole-domain 和 path-prefix 双模式) |
| SentimentParser | `geo_analyzer/src/parsers/sentiment_parser.py`(不动) | 按 response 级情感 + 主题 |
| DomainClassifier | `geo_analyzer/src/parsers/domain_classifier.py`(已升级支持 Channel 枚举,不动) | 域名全局分类 |

### 4.2 BrandParser 的匹配逻辑

```
输入:
  - response_text (AI 回答全文)
  - brands:        [{brand_name, aliases, is_shadow}, ...] from geo_client_brands
  - peers:         [{primary_name, aliases}, ...] from geo_client_peers

步骤:
  1. 对每个 Brand(own + shadow)构造规范化名字列表,用 \b...\b word-boundary 正则匹配
  2. 对每个 Peer 同样匹配
  3. 去重:同一个品牌在一条 response 里只取第一次出现
  4. 写入 geo_brand_mentions:
     - brand_role = 'own'    if 来自 geo_client_brands 且 is_shadow=false
     - brand_role = 'shadow' if 来自 geo_client_brands 且 is_shadow=true
     - brand_role = 'peer'   if 来自 geo_client_peers
```

### 4.3 ProductParser 的匹配逻辑

```
输入:
  - response_text
  - tracked_products: [{id, product_name, match_variants, product_role,
                        owner_brand_id, owner_brand_name,
                        owner_peer_id, owner_peer_name}, ...]
                      from geo_client_topic_products

步骤:
  1. 对每个 product,取 match_variants(若为空回退到 product_name)
  2. 对每个 variant 做 \b...\b word-boundary 正则匹配
  3. variant 规范化:小写、去连字符变体、空格变体
  4. 长度约束:variant <= 3 字符的拒绝(太短易误伤),记 warning
  5. 去重:同一个 product 在一条 response 里只取第一次
  6. 写入 geo_product_mentions,带 product_role 和 owner 字段的 denormalized 副本
```

### 4.4 Analyzer `main.py` Pipeline 变更

当前 pipeline(简化版):
```
Phase 1: 批量 parse mentions + citations (per result)
Phase 2a: 批量 domain_classifier (batch-level domain set)
Phase 2b: 批量 sentiment_parser (SENTIMENT_BATCH_SIZE 条/批)
Phase 3: 写库 (per result)
Phase B: normalize sentiment themes
```

新 pipeline:
```
Phase 0 (新): 加载 brands (geo_client_brands)、peers、domains、tracked_products

Phase 1: 批量 parse
  - BrandParser   → brand mentions (写 geo_brand_mentions)
  - ProductParser → product mentions (写 geo_product_mentions)
  - CitationParser → citations
Phase 2a/2b/3/B 保持不变(只是 Phase 3 要 INSERT 两张 mention 表)
```

代码改动范围(`geo_analyzer/main.py`):

```python
# Phase 0 新增
brands_rows = conn.execute(text("""
    SELECT brand_name, aliases, is_shadow
    FROM geo_client_brands
    WHERE client_id = :client_id AND is_active = true
"""), {"client_id": client_id}).fetchall()

tracked_products_rows = conn.execute(text("""
    SELECT tp.id, tp.product_name, tp.match_variants, tp.product_role,
           tp.owner_brand_id, cb.brand_name AS owner_brand_name,
           tp.owner_peer_id,  cp.primary_name AS owner_peer_name
    FROM geo_client_topic_products tp
    LEFT JOIN geo_client_brands cb ON cb.id = tp.owner_brand_id
    LEFT JOIN geo_client_peers cp ON cp.id = tp.owner_peer_id
    WHERE tp.client_id = :client_id AND tp.is_active = true
"""), {"client_id": client_id}).fetchall()

# Phase 1 里 parse_company_mentions 换成 parse_brand_mentions
# 新增 parse_product_mentions

# Phase 3 INSERT 要写新的两张表(表名/字段名已重命名)
```

### 4.5 兼容性处理

**关于 `geo_clients.aliases` 字段**:当前 BrandParser 从 `geo_clients.name + aliases` 构造"自有品牌"列表。新架构下,这个字段**依然保留但不再被 Analyzer 使用**——Analyzer 只读 `geo_client_brands`。

Migration 脚本会为每个现存 client 把 `(name, aliases)` 初始化写入 `geo_client_brands` 一行(`is_shadow=false`),确保迁移当晚 BrandParser 无需客户干预就能正常运行。

---

## 5. 技术设计:Agent NL2SQL 与配置类 SQL 适配

### 5.1 影响范围审计结果

基于对代码库和数据库的全量审计:

#### 5.1.1 数据库内 SQL 片段(由 Agent 动态使用)

| 表 | 字段 | 包含 `geo_company_mentions` 的行数 | 包含 `is_own_brand` 的行数 |
|---|---|---|---|
| `geo_analysis_metrics` | `calculation_hint` | **6 / 11** | **5 / 11** |
| `geo_report_templates` | `wizard_config` (JSON) | **2** 个模板 | **2** 个模板 |

这些数据库内的 SQL 片段全部需要 rewrite,**由用户手动执行 UPDATE 语句**(第 8 章)。

#### 5.1.2 代码中的 SQL 片段和 schema hints(后端 Python)

| 文件 | 引用内容 | 改动规模 |
|---|---|---|
| `geo_agent/src/tools/data_tools.py` | `ALLOWED_TABLES` 列表 + sample_info notes | 中 |
| `geo_agent/src/tools/chart_tools.py` | `isOwn: c["is_own_brand"]` 字段转换 | 小 |
| `geo_agent/src/tools/utility_tools.py` | `SELECT ... FROM geo_client_peers WHERE is_own_brand = false` → 直接去掉 WHERE(列已删) | 小 |
| `geo_agent/src/graphs/analyze.py` | schema hint 文本(行 266/284/290/298);硬编码 SQL(行 570-575) | 中 |
| `geo_agent/src/routers/tasks.py` | 行 432-433 硬编码 SQL;行 479 relevant_tables 列表 | 小 |
| `geo_agent/src/pipelines/analysis_pipeline.py` | 行 42/79/372/668 schema hint 和 relevant_tables | 中 |
| `geo_agent/src/pipelines/opportunity_pipeline.py` | 行 100-104 硬编码 SQL | 小 |
| `geo_agent/src/pipelines/_template_contracts_stub.py` | 整文件都是旧 schema 的 SQL。**Phase 2 之后的过渡 stub,本次直接整体删除** | 删除 |
| `geo_saas/src/database.py` | SQLAlchemy Table 定义(`geo_company_mentions` Table + `is_own_brand` Column)+ 新增 `geo_client_brands` / `geo_client_topic_products` / `geo_product_mentions` / `geo_brand_mentions` Table 定义 | 中 |
| `geo_saas/src/routers/settings.py` | peer 相关的 `is_own_brand` 字段(请求 schema 移除);Topics CRUD 改为用 products 子表;新增 Brands CRUD;新增 Products CRUD | 大 |
| `geo_saas/src/routers/insights/visibility.py` | 所有 `geo_company_mentions.c.is_own_brand` / `.company_name` 的引用 | 大 |
| `geo_saas/src/routers/insights/prompt_metrics.py` | 同上 | 中 |
| `geo_saas/src/routers/insights/analysis.py` | NL2SQL schema hint + 硬编码 SQL 片段 | 中 |
| `geo_saas/src/routers/insights/` 新增 API | product-visibility / product-sentiment / brand-product-cooccurrence / topic-breakdown / brand-topic-contribution 等新端点 | 大(新增) |
| `geo_admin/src/database.py` | 同 saas,Table 定义 + 新表定义 | 中 |
| `geo_admin/src/routers/clients.py` / `prompts.py` / `analysis.py` | Topics/Products CRUD 适配 + 硬编码 SQL 重写 | 中 |
| `geo_analyzer/src/core/database.py` | Table 定义 + 新表定义 | 中 |
| `geo_analyzer/main.py` | Phase 0 加载 brands / tracked_products;Phase 1 跑两个 Parser;Phase 3 写两张 mention 表 | 大 |
| `geo_analyzer/src/parsers/company_parser.py` → `brand_parser.py` | 重命名 + 升级接收 brands 参数(含 is_shadow) | 中 |
| `geo_analyzer/src/parsers/product_parser.py` | 新建 | 新增 |
| `geo_analyzer/scripts/backfill_dedup_mentions.py` | **历史一次性脚本**,全部引用旧 schema。建议直接删除(已无再执行意义) | 删除 |
| `geo_collector/src/services/prompt_expander.py` | **不需要改**(只读 client_prompts,无 topics.products 依赖) | 无 |
| `geo_saas/src/routers/brainstorming.py` | `topic_map[tid]["products"]` 来源改为查 `geo_client_topic_products` | 小 |
| `geo_admin/src/routers/brainstorming.py` | 已标记 LEGACY 注释掉,**可本次物理删除** | 删除 |

#### 5.1.3 前端代码(React / TypeScript)

| 文件 | 引用内容 | 改动 |
|---|---|---|
| `geo_saas/web/src/pages/SettingsPage.tsx` | `addPeer({ is_own_brand: false })`——因为字段被删,移除 | 小 |
| `geo_saas/web/src/pages/SettingsPage.tsx` | 🆕 新增 Brands Tab + Topics 结构化表单改造 + Peers Tab 清理 | 大 |
| `geo_saas/web/src/pages/PromptEditor.tsx` | ~10 处 `topic.products: string[]` 引用,全部改为 `topic.tracked_products: Product[]` 结构化消费 | 大 |
| `geo_saas/web/src/components/insights/VisibilityDashboard.tsx` | ~15 处 `company_name` 引用改为 `brand_name`;`is_own` 的 boolean 改为从 `brand_role` 派生;新增 View By 切换 + brand_role filter | 大 |
| `geo_saas/web/src/components/wizard/customFields/PeerPicker.tsx` | 原本用 `is_own_brand` 在 peers 内部二分自有/竞品,现在改为:brand 来自 `geo_client_brands`(含 own + shadow),peer 来自 `geo_client_peers`,前端拼两组数据展示 | 中 |
| `geo_saas/web/src/components/agents/ContentTaskModal.tsx` | 同上,peers.filter(p => p.is_own_brand) 逻辑改写 | 中 |
| `geo_saas/web/src/lib/api.ts`(如有) | 新增 Brands / Products 的 TypeScript 类型和 API 包装函数 | 中 |
| 🆕 `geo_saas/web/src/components/insights/ProductVisibilityDashboard.tsx` | 新建 | 新增 |
| 🆕 `geo_saas/web/src/components/insights/CooccurrenceHeatmap.tsx` | 新建(Brand × Product 共现矩阵) | 新增 |
| 🆕 `geo_saas/web/src/components/insights/TopicBreakdown.tsx` | 新建 | 新增 |
| 🆕 `geo_saas/web/src/components/onboarding/OnboardingWizard.tsx` | 新建(Brand-first vs OEM 二分支引导) | 新增 |
| `geo_admin/web/src/` | 目前 grep 未发现对 `is_own_brand` / `company_name` / `topic.products` 的消费(Admin 侧基本不碰这些字段),**风险极低**,确认后无需修改 | 无 |

#### 5.1.4 DB-persisted 配置的全库彻底扫描结果

对 `public` schema 所有表的所有 text / jsonb / ARRAY 列,搜索 `geo_company_mentions` / `is_own_brand` / `company_name` 三个关键词,扫描结果 **22 个表×列×pattern 组合命中**,涉及 **5 张表**:

**✅ 必须更新(配置类,Agent / Dashboard 会重新执行)**:

| 表.字段 | 命中情况 | 改动方式 |
|---|---|---|
| `geo_analysis_metrics.calculation_hint` | 6 行含 `geo_company_mentions`,5 行含 `is_own_brand`,2 行含 `company_name` | 批量 `replace()` UPDATE(见 §8 Step 3) |
| `geo_analysis_metrics.relevant_tables` (TEXT[]) | **9 行**含 `geo_company_mentions`(比之前的认知多,之前只统计了部分) | `array_replace()` UPDATE |
| `geo_report_templates.wizard_config` (JSONB) | 2 模板各含 `geo_company_mentions` / `is_own_brand`,1 含 `company_name` | JSON text UPDATE(见 §8 Step 4) |

**🗑️ 全部 TRUNCATE(产品无线上用户,无保留价值)**:

| 表.字段 | 命中情况 | 决策 |
|---|---|---|
| `checkpoints.checkpoint` (JSONB) | 2023 行表;38 行含 `geo_company_mentions`,27 行含 `company_name`,14 行含 `is_own_brand` | **TRUNCATE**(§8.2.11)——LangGraph state,无长对话需要续 |
| `agent_messages.tool_results` / `.content` (JSONB+text) | 190 行;2 行 tool_results 含旧 SQL 文本 | **TRUNCATE**——聊天历史,无线上用户 |
| `agent_memories.metadata` | 6 行,0 旧 schema 命中 | **TRUNCATE**——跨会话记忆,无价值 |
| `geo_agent_tasks.inputs` / `output` / `status_logs` | 历史 agent 任务产出;各字段 7-8 行含旧 SQL 文本 | **TRUNCATE**——历史任务,含旧 schema 污染 |

**📘 确认干净 / 不涉及旧 schema(保留不动)**:

| 表.字段 | 命中情况 | 说明 |
|---|---|---|
| `geo_brand_profiles.key_messages` / `brand_values` | 0 命中 | 确认干净 |
| `geo_workflow_config.value` | 0 SQL 命中(有 `peer_picker` widget 引用但无 SQL) | 仅 UI 定义,无需改 |
| `geo_optimization_metrics` / `geo_optimization_subgoals` | 0 命中 | RAFT 四柱框架,和可见度 metric 体系无交集 |
| `geo_strategies.dimensions` | 0 命中 | Content 生成策略,无关 |
| `geo_results.cloro_response` / `sources` / `citation_pills` / `entities` | 0 命中(这些是 Cloro 原始响应,不含 SQL) | **Roborock 历史分析数据,严格保留** |

#### 5.1.5 Agent 运行时状态:全部 TRUNCATE

产品无线上用户,没有需要保留的对话历史或 agent 运行态。以下四张表 **一律 TRUNCATE**:

- `checkpoints`(2023 行)—— LangGraph AsyncPostgresSaver 的 state snapshots
- `agent_messages`(190 行)—— 聊天历史 text,2 行含旧 SQL
- `agent_memories`(6 行)—— 跨会话记忆
- `geo_agent_tasks`(若干历史产出)—— 历史 agent 任务记录

这样保证:
- 迁移后没有任何 agent 状态残留
- 不会有 thread resume 时执行旧 SQL 的风险
- 下一个 agent 对话从零开始,使用新 schema 的 NL2SQL hints

具体 SQL 见 §8.2.11。

### 5.2 `geo_analysis_metrics` 重写策略

每个 metric 的 `calculation_hint` 字段里包含完整的"示例 SQL"字符串,这是 Agent 做 NL2SQL 时的 few-shot 样本。必须同步重写:

- 所有 `geo_company_mentions` → `geo_brand_mentions`
- 所有 `cm.is_own_brand = true` → `cm.brand_role = 'own'`
- 所有 `cm.is_own_brand = false` → `cm.brand_role IN ('peer', 'shadow')`(取决于上下文;SOV 分母通常是 total 不需要 filter)
- 所有 `cm.company_name` → `cm.brand_name`
- `relevant_tables` 数组里的 `geo_company_mentions` → `geo_brand_mentions`

**新增 metrics 建议**(Phase 2 之后):
- `product_visibility_sov`:产品层 SOV,基于 `geo_product_mentions` where `product_role='own'`
- `product_shadow_brand_cooccurrence`:用户产品与 Shadow Brand 共现频次(Tmax 核心指标)
- `brand_sentiment_by_role`:按 brand_role 拆分 sentiment 分布

这些新 metrics 的 UPSERT SQL 在第 8 章提供。

### 5.3 `geo_report_templates.wizard_config` 重写

2 个模板的 `wizard_config.steps.chart_config.default_charts[].sql_hint` 内有旧 schema。需要 `jsonb_set` 或整条 UPDATE 重写。由于 JSONB 结构复杂,建议以**整条 UPDATE 的形式替换完整的 `wizard_config` 值**——SQL 在第 8 章提供。

### 5.4 Agent 代码中 schema hints 的重写

`analysis_pipeline.py` 有一个常量 `TABLE_HINTS`(简化版):
```python
TABLE_HINTS = {
    "visibility": "...geo_company_mentions: id, ..., is_own_brand (bool)...",
    ...
}
```

这些字符串直接由 LLM 读取用于 NL2SQL,必须完整重写。具体行号见上表。

---

## 6. 技术设计:SaaS Insights 与前端适配

> **本章重点说明 Visibility / Citation / Sentiment 三大可视化模块的具体改动,包括新增的筛选项、视图切换、以及新图表设计**。不是简单的字段改名——这是产品侧的实质增量。

### 6.0 整体可视化策略:维度切换 + 筛选器 + 新图表

三个 Insights 模块共享一套通用的"维度切换(View By)+ 筛选器(Filters)"机制,对 ODM/OEM 和自营品牌客户统一适用,数据存在就自动展示对应视图:

| 全局视图维度 | 值域 | 适用场景 |
|---|---|---|
| **View By** | Brand / Product / Topic / Brand × Topic / Topic × Product | 用户主动切换想看的聚合粒度 |
| **Filter: brand_role** | own / shadow / peer / all | 默认 all;ODM/OEM 客户可以只看 shadow 或只看 peer |
| **Filter: product_role** | own / shadow_brand_native / peer / all | 同上,控制产品视图 |
| **Filter: Topic** | 多选 topics(已有,保留) | 不变 |
| **Filter: Platform / Date Range** | 已有,保留 | 不变 |

### 6.1 Visibility Dashboard:新增的视图与图表

当前 Visibility 只有一种视角——"品牌(通过 `geo_company_mentions.company_name + is_own_brand` 聚合)"。新设计增加以下视图:

#### 6.1.1 Brand 视图(默认,兼容现存 Roborock 行为)

- **SOV Trend**(已有):改用 `geo_brand_mentions.brand_role = 'own'` 作为分子,`brand_role IN ('own','shadow','peer')` 作为分母。对 Shadow Brand 客户,`own` 可以替换成 `own OR shadow`(通过 filter 让用户选)
- **Brand Mention Breakdown by Platform**(已有):增加一列展示 `brand_role`,用颜色区分 own / shadow / peer
- **🆕 Shadow Brand 专属 panel**:只在客户配置了至少一个 `is_shadow=true` 的 brand 时显示,展示 Shadow Brand 自身的 mention trend + 平台分布。Tmax 类客户这是他们的主视图

#### 6.1.2 Product 视图(新增)

- **🆕 Product SOV**:按 `product_name` 聚合,分母可选 `product_role='own'` only 或 `all products`
- **🆕 Top Products by Mention**:排序展示 mention 最多的 Top-N 产品,每条标注 product_role(颜色区分)
- **🆕 Product Platform Breakdown**:按平台看每个 SKU 的 mention 分布
- **🆕 Product Position**:延用 `mention_position` 字段,展示每个 SKU 的平均位置(在 AI 回答里排第几)

#### 6.1.3 Topic 视图(部分新增)

- **🆕 Topic Coverage**:每个 Topic 下 own brand mention 出现过的 prompt 占比(`prompt_coverage_rate` 按 topic 拆分)
- **🆕 Topic × Platform Heatmap**:Topic 在各 AI 平台的表现矩阵

#### 6.1.4 Brand × Topic 交叉视图(新增)

- **🆕 Topic Contribution to Brand SOV**:stacked bar,每个 topic 对品牌总 mention 的贡献占比
- 回答的问题:"我的品牌在哪个话题下表现最好?"

#### 6.1.5 Topic × Product 交叉视图(新增)

- **🆕 Product Heatmap within Topics**:每个 Topic 下各 SKU 的 mention 强度
- 回答的问题:"在 Off-Road Running Boards 这个话题下,我的哪款 SKU 被 AI 最常提起?"

#### 6.1.6 Brand × Product 共现视图(OEM 核心指标,新增)

**这是 Tmax 类客户最关心的唯一指标**——"我的产品在 Shadow Brand 上下文里被提及的次数"。实现方式:

```sql
-- 伪 SQL:同一条 AI response 同时出现 Shadow Brand 和 Own Product
SELECT DATE(bm.executed_at) AS date,
       pm.product_name,
       bm.brand_name AS shadow_brand,
       COUNT(DISTINCT bm.result_id) AS cooccurrence_count
FROM geo_brand_mentions bm
JOIN geo_product_mentions pm
     ON pm.result_id = bm.result_id AND pm.client_id = bm.client_id
WHERE bm.client_id = $1
  AND bm.brand_role = 'shadow'
  AND pm.product_role = 'own'
  AND bm.executed_at BETWEEN $2 AND $3
GROUP BY DATE(bm.executed_at), pm.product_name, bm.brand_name
ORDER BY 1, cooccurrence_count DESC;
```

**UI 展示**:
- **Co-occurrence Matrix**:横轴 Shadow Brand,纵轴 Own Product,单元格显示共现次数
- **Co-occurrence Trend**:按日期折线,展示"HT-Series 在 RC 语境下被提及"的趋势

### 6.2 Citation Dashboard:扩展,非颠覆

上一轮已经完成了 Channel category + URL 前缀 own 的核心工作。本轮对 Citation 的改动较小:

- **🆕 Citation by Domain Category**(已存在,增强):新增 `Channel` 类别的专属视图,让 Tmax 类客户能单独看 "RC 渠道贡献"
- **🆕 Citation by URL Ownership**:`url_is_owned=true` vs `false` 的对比,展示"我在别人渠道上的 URL 占比"
- **🆕 Citation × Product 共现**(需新表 join):citation 和 product_mention 在同一 response 中共现时,可以算"这个 URL 被引用的时候,我的哪款产品也被提到"

不需要新增数据字段,都是 UI 层查询的新 slice。

### 6.3 Sentiment Dashboard:新增维度归因

当前 Sentiment 是 response 级的(整条 AI 答案的情感)。本轮**不做 sentence-level 归因**(那是 Phase 2 的事,见第 6.4 节),而是通过 **response 级 join 做实体归因**:

- **🆕 Sentiment by Brand**:把一条 response 的情感归到该 response 里出现的所有 brand mentions 上。若 response mentions `Roborock` + `Dreame`,两者都各记一次情感
  - 实现:`geo_sentiment_results JOIN geo_brand_mentions ON result_id`
- **🆕 Sentiment by Product**:同理,归因到 response 里的 product mentions
  - 实现:`geo_sentiment_results JOIN geo_product_mentions ON result_id`
- **🆕 Brand × Product 共现 Sentiment**:response 同时 mention Shadow Brand + Own Product 时的情感分布——Tmax 的核心情感指标
  - "HT-Series 在 RC 语境下被讨论时,83% 是正面"

### 6.4 "Sentiment 精细归因"的概念澄清

我之前在文档里用 "Sentiment 精细归因" 这个说法,你问我具体指什么。明确一下分层:

| 归因粒度 | 含义 | 实现方式 | 本轮是否做 |
|---|---|---|---|
| **Response-level(整条答案)** | 一条 AI 回答整体是正面还是负面 | 现有 `geo_sentiment_results`,无改动 | ✅ 一直都有 |
| **Entity-level via join(实体归因)** | 一条 response 的情感归到其中出现的每个 brand/product。不区分句子 | `JOIN sentiment_results × brand_mentions / product_mentions ON result_id`,SQL 层就能算 | ✅ **本轮做**,见 §6.3 |
| **Sentence-level(句子级精细归因)** | AI 答:"HT-Series is excellent but Smittybilt overpriced" → HT-Series 正面,Smittybilt 负面 | 需要 LLM 对每个句子单独分类 + 实体识别 + 情感绑定 | ❌ **本轮不做**,列为未来项(成本+难度都高) |

所以"精细归因"在本轮指的是**第二层**(Entity-level via response join),**不是句子级**。这个通过现有数据 + 新的 join SQL 就能实现,不需要新的 NLP 能力。

### 6.5 后端 API 改动清单

**改造现有端点**(`geo_saas/src/routers/insights/` 下):

| 文件 | 改动范围 |
|---|---|
| `visibility.py` | ~30 处引用。全部按新 schema 重写:`geo_company_mentions` → `geo_brand_mentions`,`is_own_brand` → `brand_role`,`company_name` → `brand_name`。新增 `View By` 参数支持维度切换 |
| `prompt_metrics.py` | ~10 处引用,同样重写 |
| `analysis.py` | NL2SQL schema hint 重写 + 硬编码 SQL 片段更新 |
| `citations.py` / `fanouts.py` / `cited_pages.py` | 确认无 mentions 表隐式引用;增加 url_is_owned 切片查询 |
| `sentiment.py`(若存在,否则在 insights 下新建) | 加入 entity-level 归因的 join 查询逻辑 |

**新增 API 端点**(产品层 + 共现 Insights):

| 端点 | 用途 |
|---|---|
| `GET /api/insights/product-visibility` | 产品层 SOV / mention trend / 平台分布 |
| `GET /api/insights/product-sentiment` | 按 product 聚合的 sentiment(via response-level join) |
| `GET /api/insights/brand-product-cooccurrence` | **核心 OEM 指标**:brand × product 共现矩阵 + 趋势 |
| `GET /api/insights/topic-breakdown` | Topic 层视图(coverage / platform heatmap) |
| `GET /api/insights/brand-topic-contribution` | Brand × Topic 交叉分析 |

### 6.6 前端组件改动清单

**Settings 页面(`SettingsPage.tsx`)**:

| 改动 | 描述 |
|---|---|
| 🆕 新 `Brands` Tab | Brands CRUD;Own Brand 区域默认展开,Shadow Brand 区域默认折叠(Onboarding Wizard 选 OEM 时反转) |
| ✏️ `Topics` Tab | Products 改为结构化表单(`name + match_variants[]`),高级选项(`product_role` / `owner_brand` / `owner_peer`)折叠在 "Show advanced product options" 后面 |
| ✏️ `Peers` Tab | 移除 `is_own_brand` 字段相关的勾选和筛选(废弃列) |

**Insights 组件**:

| 组件 | 改动 |
|---|---|
| `VisibilityDashboard.tsx` | 加入 View By 切换 + brand_role filter;`company_name` 改为 `brand_name`;`is_own` 改为 `brand_role === 'own' \|\| brand_role === 'shadow'` 的派生布尔 |
| 🆕 `ProductVisibilityDashboard.tsx` | 产品层 SOV、Top Products、平台分布 |
| 🆕 `CooccurrenceHeatmap.tsx` | Brand × Product 共现矩阵(OEM 核心指标组件) |
| 🆕 `TopicBreakdown.tsx` | Topic 层 coverage + platform heatmap |
| `PeerPicker.tsx` | 移除对 `is_own_brand` 的依赖;改为从 `geo_client_brands` + `geo_client_peers` 两张表分别读数据,分开展示 Brand / Peer 两组 |
| `ContentTaskModal.tsx` | 同上,peer/brand 来源拆开 |
| `PromptEditor.tsx` | 把所有 `topic.products: string[]` 的消费路径改为 `topic.tracked_products: Product[]`(结构化对象),涉及约 10 处渲染改动 |


### 6.7 UI 渐进披露(Progressive Disclosure)策略

**核心原则**:所有字段都在本次上线里出现,但**默认折叠高级字段**让普通用户看不到复杂度,高级用户点开即用。不需要分版本发布。

具体表现:

- **Brands Tab**:
  - 默认展开 "Own Brand" 区域(Roborock 类客户一眼看完即可)
  - "Shadow Brand" 区域默认折叠,标签写 "Add a distributor or reseller brand (OEM / white-label scenarios)",点一下就展开
  - 两个区域的新增/编辑表单字段完全一样,折叠只是为了减少初屏认知负担
  - **Onboarding Wizard 选了 OEM 分支时**,这两个区域的默认折叠状态反转(Shadow 默认展开,Own 默认折叠)

- **Topics → Products Tab**:
  - 默认的 Product 编辑表单只有 **`name` + `match_variants[]`** 两个字段,完全不显示 `product_role`
  - 表单底部有一个小链接 "Show advanced product options"
  - 点开后展示 `product_role` 下拉(三选),选择 `shadow_brand_native` 时自动显示 `owner_brand` 选择器,选择 `peer` 时显示 `owner_peer` 选择器
  - 退回折叠后,已填写的 advanced 值仍然保留(不清空)

- **Peers Tab**:
  - 移除废弃的 `is_own_brand` 勾选框
  - 表单保持最简(primary_name + aliases)

### 6.8 Topic-only / 数据稀疏场景的 Fallback 逻辑

三种实体(Brands / Topics / Products)的**必配程度不同**,Insights 可视化必须优雅处理缺失情况:

| 实体 | 必配吗? | 缺失后果 |
|---|---|---|
| **Brand** | ✅ 强烈建议必配(Onboarding Wizard 保证至少一条) | 若空:品牌层可见度/情感/SOV 全部无数据 |
| **Peers** | 建议配 | 若空:SOV 分母只有自有品牌,可见度仍可展示 |
| **Topic** | ✅ 必配(现状,不变) | Prompt Expander 依赖 Topic 生成 client_prompts;无 Topic 系统基本不能工作 |
| **Products** | ❌ **可选** | 若空:产品层视图全部无数据,**但不应破坏整体 UI**,品牌/主题层视图正常 |

#### 6.8.1 新增 Availability API 端点

Insights 页面加载前先调一次,一次拿到"这个客户有哪些数据维度可用":

```
GET /api/insights/availability?client_id=<uuid>
Response:
{
  "has_own_brands": true,
  "has_shadow_brands": true,     // 至少一条 geo_client_brands where is_shadow=true
  "has_peers": true,
  "has_topics": true,
  "has_products": false,         // geo_client_topic_products 行数 = 0
  "has_mentions_data": true,     // geo_brand_mentions 近 30 天有数据
  "has_product_mentions_data": false
}
```

#### 6.8.2 视图切换器(View By)的条件呈现

```
- has_products = false AND has_product_mentions_data = false:
    → View By 切换器只显示 Brand / Topic 两个选项(不显示 Product / Product×Topic / Brand×Product 共现)
    → 默认 Brand 视图
    → 如果用户在 Settings 加了 Products,下次进页面 View By 会多出 Product 等选项

- has_products = true AND has_product_mentions_data = false:
    → View By 切换器显示所有选项
    → 但 Product 相关视图显示 "Your products are being tracked but no mentions yet — check back after tomorrow's Collector run"

- 全部维度都有:
    → 默认视图按"哪个数据量大"自动决策:
      - has_own_brands=true 且 own brand mentions 多 → Brand view
      - has_own_brands=false(纯 Shadow Brand 客户如 Tmax)且 product mentions 多 → Product view
```

#### 6.8.3 Visibility / Sentiment 各 widget 的 fallback 行为

| 组件 | 没 product 数据时 | 没 shadow brand 时 | 没 own brand 数据时 |
|---|---|---|---|
| **SOV Trend** | 正常(只用 brand mentions) | 正常(shadow 为 0 不影响 own vs peer) | 图上只显示 peer 线,own 线为 0 |
| **Top Products** | **Empty state card**:"No products configured. Go to Settings → Topics to add product-level tracking" + 按钮 | 不受影响 | 不受影响 |
| **Product SOV** | 同上 Empty state | 同上 | 不受影响 |
| **Brand × Product Co-occurrence(OEM 核心)** | **Empty state card**:"This view requires both Shadow Brands and Products. Configure in Settings" | 同上 | 若 Shadow Brand 存在但 Product 不存在,依然显示 empty state |
| **Topic Coverage** | 正常(基于 brand mention ∩ topic 的 prompt) | 不受影响 | 为 0 |
| **Topic × Platform Heatmap** | 正常 | 不受影响 | 为 0 |
| **Sentiment Distribution** | 正常(response 级情感) | 不受影响 | 正常 |
| **Sentiment by Product** | Empty state | 不受影响 | 不受影响 |
| **Sentiment by Brand** | 正常 | 不受影响 | 为 0 |
| **Brand×Product Sentiment 共现** | Empty state | Empty state | Empty state |

#### 6.8.4 Empty State UI 规范

所有"空数据 + 需要配置"的场景共用一个组件:

```tsx
<EmptyStateCard
  icon={<Package />}                  // 或 TrendingUp / Users 等
  title="No product data yet"
  description="Product-level insights require configuring SKUs under each Topic."
  ctaLabel="Configure Products"
  ctaHref="/settings/topics"
  secondaryInfo="Tip: Your brand-level insights continue to work without this."
/>
```

不要在 dashboard 上显示"空白图表"或"0 条数据的柱状图"——明确告诉用户为什么没数据 + 下一步做什么。

#### 6.8.5 后端 API 的 Defensive 实现

所有新的 Insights API 端点必须:
- 在 `geo_client_topic_products` 为空时返回空数组 `[]`,**不报错**
- 在 `geo_product_mentions` 为空时返回 `{"data": [], "reason": "no_products_configured"}`,让前端可以区分"空因为没配置" vs "空因为没 mention 但配了"
- 使用 `COALESCE(..., 0)` 处理 aggregation 结果,避免 NULL 导致渲染错误

### 6.9 Onboarding Wizard:Brand-first vs OEM 两分支引导

新 client 第一次进入 SaaS Settings 时触发的一次性向导(本次上线):

```
┌────────────────────────────────────────────────────────────┐
│  Welcome to AnswerX GEO                                    │
│                                                            │
│  Before we set up your tracking, one quick question:       │
│                                                            │
│  Does your brand appear directly in AI search results      │
│  (e.g. ChatGPT mentions your brand name to end users)?     │
│                                                            │
│   ○ Yes — we have our own brand customers see               │
│   ○ No — we're an OEM / white-label supplier,               │
│          our products are sold under distributor brands     │
│   ○ Both — we have our own brand and also OEM partnerships  │
│                                                            │
│  [ Skip, I'll configure manually ]  [ Continue ]           │
└────────────────────────────────────────────────────────────┘
```

根据选择驱动的默认配置和 UI 状态:

| 用户选择 | 自动操作 | UI 默认状态 |
|---|---|---|
| **"Yes"(自营品牌,Roborock 类)** | 在 `geo_client_brands` 自动写一行 `{brand_name = client.name, is_shadow = false}` | Brands Tab 的 "Own Brand" 区域展开,Shadow Brand 折叠;Topics Tab 正常展示 |
| **"No"(OEM / 白标,Tmax 类)** | 不自动写 Own Brand,光标自动聚焦到 Shadow Brand 输入框;弹 helper text "Enter the brand(s) your products are sold under" | Brands Tab "Shadow Brand" 区域展开,"Own Brand" 折叠(但不隐藏);Topics Tab 给 tooltip 提示"Enter your SKU/model names — AI will only see your product names, not your company name" |
| **"Both"(混合)** | 自动写 Own Brand = client.name,引导填 Shadow Brand | 两个区域都展开 |
| **"Skip"** | 不做任何自动操作 | 全部默认折叠状态,等用户自己配 |

**技术实现**:
- Wizard 状态存在 `geo_clients.onboarding_wizard_completed BOOLEAN DEFAULT false`(新列)
- 首次登录 SaaS 且该字段 false 时弹 Wizard
- 用户选完后设为 true,不再弹
- 可通过 Admin 或 SaaS 设置页手动重置(用于测试)

新加字段的 Migration SQL:

```sql
ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS onboarding_wizard_completed BOOLEAN NOT NULL DEFAULT false;

-- 已存在的客户视为已完成,避免误弹 wizard
UPDATE geo_clients SET onboarding_wizard_completed = true WHERE created_at < NOW();
```

---

## 7. 技术设计:Prompt Expander 与 Topic-only 模式

### 7.1 现状审查结果

`geo_collector/src/services/prompt_expander.py` 的当前逻辑:

- 不直接遍历 `geo_client_topics.products` TEXT[]
- 读的是 **`geo_client_prompts`**(active 状态的用户配置 prompt),每条已经包含 `topic_id + product`(product 作为 denormalized TEXT 列)
- 对这些 client_prompts 做 1:N 扩展(同一个 client_prompt 生成多个 final_prompts 的变体)

**含义**:Prompt Expander **不需要大改**——它不依赖 `geo_client_topics.products` 列,也不依赖新的 `geo_client_topic_products` 表。`client_prompts.product` TEXT 列继续承担现有职责。

### 7.2 需要改动的地方

只有一个:**创建 client_prompts 的路径**(无论通过 Admin UI / SaaS UI / Brainstorming 生成)需要改成从新的 `geo_client_topic_products` 读产品列表,而不是从 `geo_client_topics.products` TEXT[]:

| 文件 | 改动 |
|---|---|
| `geo_saas/src/routers/brainstorming.py` | `topic_map[tid]["products"]` 来源改为查 `geo_client_topic_products` |
| `geo_admin/src/routers/brainstorming.py` | 同上(虽然在上一轮已经标记为 LEGACY 注释掉) |
| `geo_saas/src/routers/settings.py` | Topics CRUD 改为关联表操作(topics 本身不再有 products 列);Products CRUD 新建为独立 endpoints |
| `geo_admin/src/routers/prompts.py` | 同上 |

### 7.3 Topic-only 模式支持

以上改动自然支持 Topic-only 模式:
- 用户建 Topic 不建 Products → `geo_client_topic_products` 表里该 topic 无关联行
- Brainstorming 生成 client_prompts 时:
  - 若 Products 为空,生成策略改为 "仅基于 Topic name + Peers/Brands/Personas" 而不是 "Topic + 每个 Product"
  - Prompt 文本里不 reference 具体产品

对应代码改动约 20-30 行,需要 Brainstorming 的 `_build_brainstorm_prompt` 函数加一个"products 为空时的 fallback prompt 模板"。

---

## 8. Migration Plan(所有 DDL/DML 由用户手动执行)

### 8.0 数据保留 vs 数据清洗清单

**产品现状**:没有线上用户,只有 Roborock 作为内部日常监控客户 + Tmax 刚建 workspace(无数据)。

**迁移的数据保护目标**(必须完整保留):

| 表 | Roborock 数据 | 迁移处理 |
|---|---|---|
| `geo_results` | 2,128 行 AI 回答原始数据 | **不动**(列不变) |
| `geo_company_mentions` → `geo_brand_mentions` | 10,486 行历史 mentions | **重命名表 + 升级字段**,行数据完整保留(见 §8.2.5-6) |
| `geo_citations` | 42,607 行 | **不动** |
| `geo_sentiment_results` | 不变 | **不动** |
| `geo_sentiment_themes` | 不变 | **不动** |
| `geo_client_prompts` | 76 行 | **不动**(含 `product` TEXT 列,见 §10.4) |
| `geo_tasks` | 不变 | **不动** |
| `geo_client_topics` | 2 行 | `products` TEXT[] 列的数据迁移到新表(§8.2.4),然后删该列 |
| `geo_client_topic_products` | 新表 | 从 topics.products 迁移数据(§8.2.4) |
| `geo_client_peers` | 17 行 | 删除遗留 `is_own_brand` 列(§8.2.8),主数据保留 |
| `geo_client_domains` | 6 行 | **不动** |
| `geo_clients` | 2 行 | 加 `onboarding_wizard_completed` 列,值全部置 true |

**允许清空的数据**(没有保留价值):

| 表 | 说明 | 迁移处理 |
|---|---|---|
| `checkpoints` | 2023 行 LangGraph 运行时状态,没有长对话需要续 | **TRUNCATE**(§8.2.11) |
| `agent_messages` | 190 行聊天历史,没有实际用户,本身也包含大量旧 SQL 文本 | **TRUNCATE**(§8.2.11) |
| `agent_memories` | 6 行跨会话记忆,没有用户价值 | **TRUNCATE**(§8.2.11) |
| `geo_agent_tasks` | 历史 agent 任务产出(含旧 schema 的 SQL text) | **TRUNCATE**(§8.2.11) |

**必须更新的配置表**(不能清空,但必须重写 SQL 片段):

| 表 | 操作 |
|---|---|
| `geo_analysis_metrics` | 11 行,按 §8 Step 3 批量 `replace()` 重写 `calculation_hint` + `array_replace()` 更新 `relevant_tables` |
| `geo_report_templates` | 2 个 analysis templates + 6 个 content templates 的 `wizard_config` 按 §8 Step 4 重写 |
| `geo_workflow_config` | 无 SQL,只有 UI widget 配置,无需改 |
| `geo_global_settings` | 无 SQL,不动 |
| `geo_global_platforms` / `geo_global_intents` / `geo_global_languages` | 全局字典,不动 |

**新增表的 seed / 数据**:
- `geo_client_brands`:为每个 client 自动插入一行 `is_shadow=false`,brand_name = client.name,aliases 复制自 client.aliases(§8.2.2)
- `geo_client_topic_products`:从 `geo_client_topics.products` TEXT[] 迁出(§8.2.4),每个元素一行 `product_role='own'`

### 8.1 执行顺序

**Step 1 — 准备阶段(用户手动)**:

> **背景**:当前产品没有上线用户,只有 Roborock 作为内部客户在跑日常监控。迁移期间**不需要考虑停机协调、用户通知、SLA 等顾虑**。唯一的数据保护目标是 **Roborock 的历史分析数据**(见 §8.0)。

1. **备份 Cloud SQL 快照**(保留一份,防止需要整库回滚)
2. 暂停 Analyzer 和 Collector Cloud Run Job(避免迁移过程中新数据写入旧表)——不需要对外通知
3. geo_agent 服务可以继续运行,但**它的 checkpoints / agent_tasks / agent_messages 会在 §8.2.11 被清空**,用户下次开对话是全新线程

**Step 2 — Schema 变更(用户执行以下 SQL,按编号顺序)**:

```sql
-- ============================================================
-- 8.2.1 新建 geo_client_brands 表
-- ============================================================
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


-- ============================================================
-- 8.2.2 初始化 geo_client_brands(为每个 client 写一行 Own Brand)
-- ============================================================
INSERT INTO geo_client_brands (client_id, brand_name, aliases, is_shadow)
SELECT id, name, COALESCE(aliases, '{}'::text[]), false
FROM geo_clients;

-- 验证:每个 client 都应有一个 Own Brand 行
SELECT c.id, c.name,
       (SELECT COUNT(*) FROM geo_client_brands b WHERE b.client_id = c.id) AS brand_count
FROM geo_clients c;
-- 期望:每行 brand_count = 1


-- ============================================================
-- 8.2.3 新建 geo_client_topic_products 表
-- ============================================================
CREATE TABLE geo_client_topic_products (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic_id        UUID NOT NULL REFERENCES geo_client_topics(id) ON DELETE CASCADE,
    client_id       UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_name    TEXT NOT NULL,
    match_variants  TEXT[] NOT NULL DEFAULT '{}',
    product_role    TEXT NOT NULL DEFAULT 'own'
                    CHECK (product_role IN ('own', 'shadow_brand_native', 'peer')),
    owner_brand_id  UUID REFERENCES geo_client_brands(id) ON DELETE SET NULL,
    owner_peer_id   UUID REFERENCES geo_client_peers(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT product_role_fk_consistency CHECK (
        (product_role = 'own'                 AND owner_brand_id IS NULL AND owner_peer_id IS NULL) OR
        (product_role = 'shadow_brand_native' AND owner_brand_id IS NOT NULL AND owner_peer_id IS NULL) OR
        (product_role = 'peer'                AND owner_brand_id IS NULL AND owner_peer_id IS NOT NULL)
    )
);

CREATE INDEX idx_geo_client_topic_products_topic
    ON geo_client_topic_products(topic_id) WHERE is_active = true;
CREATE INDEX idx_geo_client_topic_products_client
    ON geo_client_topic_products(client_id) WHERE is_active = true;


-- ============================================================
-- 8.2.4 数据迁移:从 geo_client_topics.products TEXT[] 迁入新表
-- ============================================================
INSERT INTO geo_client_topic_products
    (topic_id, client_id, product_name, match_variants, product_role)
SELECT
    t.id AS topic_id,
    t.client_id,
    unnest(t.products) AS product_name,
    ARRAY[unnest(t.products)] AS match_variants,
    'own'
FROM geo_client_topics t
WHERE t.products IS NOT NULL AND array_length(t.products, 1) > 0;

-- 验证:所有原 products 数组都应迁移
SELECT t.topic_name, array_length(t.products, 1) AS orig_count,
       (SELECT COUNT(*) FROM geo_client_topic_products p WHERE p.topic_id = t.id) AS migrated_count
FROM geo_client_topics t
WHERE t.products IS NOT NULL AND array_length(t.products, 1) > 0;
-- 期望:每一行 orig_count = migrated_count


-- ============================================================
-- 8.2.5 重命名 geo_company_mentions -> geo_brand_mentions
-- ============================================================
ALTER TABLE geo_company_mentions RENAME TO geo_brand_mentions;

-- 重命名字段 company_name -> brand_name
ALTER TABLE geo_brand_mentions RENAME COLUMN company_name TO brand_name;


-- ============================================================
-- 8.2.6 geo_brand_mentions 字段升级:is_own_brand (BOOL) -> brand_role (ENUM)
-- ============================================================
ALTER TABLE geo_brand_mentions
    ADD COLUMN brand_role TEXT
    CHECK (brand_role IN ('own', 'shadow', 'peer'));

UPDATE geo_brand_mentions
SET brand_role = CASE
    WHEN is_own_brand = true THEN 'own'
    ELSE 'peer'
END;

ALTER TABLE geo_brand_mentions ALTER COLUMN brand_role SET NOT NULL;

ALTER TABLE geo_brand_mentions DROP COLUMN is_own_brand;

-- 验证:所有历史 mentions 都应该有 brand_role 值,且只能是 own 或 peer(历史没有 shadow)
SELECT brand_role, COUNT(*) FROM geo_brand_mentions GROUP BY brand_role;
-- 期望:只出现 'own' 和 'peer' 两类;各自的总和 = 原 geo_company_mentions 总行数 10,486


-- ============================================================
-- 8.2.7 新建 geo_product_mentions 表
-- ============================================================
CREATE TABLE geo_product_mentions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_prompt_id    UUID NOT NULL,
    task_id             UUID,
    result_id           INTEGER NOT NULL,
    client_id           UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_id          UUID REFERENCES geo_client_topic_products(id) ON DELETE SET NULL,
    product_name        TEXT NOT NULL,
    product_role        TEXT NOT NULL
                        CHECK (product_role IN ('own', 'shadow_brand_native', 'peer')),
    owner_brand_id      UUID,
    owner_brand_name    TEXT,
    owner_peer_id       UUID,
    owner_peer_name     TEXT,
    mention_position    INTEGER,
    executed_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_geo_product_mentions_client
    ON geo_product_mentions(client_id, executed_at DESC);
CREATE INDEX idx_geo_product_mentions_result
    ON geo_product_mentions(result_id, client_id);
CREATE INDEX idx_geo_product_mentions_role
    ON geo_product_mentions(client_id, product_role);


-- ============================================================
-- 8.2.8 清理 geo_client_peers.is_own_brand(遗留列,全库 0 true)
-- ============================================================
ALTER TABLE geo_client_peers DROP COLUMN is_own_brand;


-- ============================================================
-- 8.2.9 删除 geo_client_topics.products TEXT[](迁移完成后执行)
-- ============================================================
-- ⚠️ 警告:执行前务必先验证 8.2.4 的迁移完整性
ALTER TABLE geo_client_topics DROP COLUMN products;


-- ============================================================
-- 8.2.10 Onboarding Wizard 状态字段
-- ============================================================
ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS onboarding_wizard_completed BOOLEAN NOT NULL DEFAULT false;

-- 已存在客户视为已完成,避免老客户弹 wizard
UPDATE geo_clients SET onboarding_wizard_completed = true;


-- ============================================================
-- 8.2.11 清空所有 Agent 运行时状态和历史对话
-- ============================================================
-- 背景:产品无线上用户,没有需要保留的对话历史或未完成 agent 状态。
-- 一次性全部清空,避免旧 schema 的 SQL 文本残留在 checkpoint / message 里引发问题。

TRUNCATE TABLE checkpoints;        -- 2023 行 LangGraph state snapshots
TRUNCATE TABLE agent_messages;     -- 190 行聊天历史
TRUNCATE TABLE agent_memories;     -- 6 行跨会话记忆
TRUNCATE TABLE geo_agent_tasks;    -- 历史 agent 任务产出

-- 验证:
SELECT 'checkpoints' AS t, COUNT(*) FROM checkpoints
UNION ALL SELECT 'agent_messages', COUNT(*) FROM agent_messages
UNION ALL SELECT 'agent_memories', COUNT(*) FROM agent_memories
UNION ALL SELECT 'geo_agent_tasks', COUNT(*) FROM geo_agent_tasks;
-- 期望:全部为 0
```

**Step 3 — 重写 `geo_analysis_metrics` 的 `calculation_hint`**:

需要 UPDATE 11 行(由于每行的 calculation_hint 内容很长,会在单独的 SQL 文件里列出)。此处给一个**模板替换脚本**的示例:

```sql
-- 批量替换 geo_analysis_metrics.calculation_hint 中的旧表名/字段名
UPDATE geo_analysis_metrics
SET calculation_hint = replace(
      replace(
        replace(
          calculation_hint,
          'geo_company_mentions', 'geo_brand_mentions'
        ),
        'is_own_brand = true', 'brand_role = ''own'''
      ),
      'is_own_brand = false', 'brand_role = ''peer'''
    ),
    updated_at = NOW();

UPDATE geo_analysis_metrics
SET calculation_hint = replace(
      replace(
        calculation_hint,
        'cm.company_name', 'cm.brand_name'
      ),
      'company_name', 'brand_name'
    )
WHERE calculation_hint LIKE '%company_name%';

-- 同步更新 relevant_tables 数组
UPDATE geo_analysis_metrics
SET relevant_tables = array_replace(relevant_tables, 'geo_company_mentions', 'geo_brand_mentions')
WHERE 'geo_company_mentions' = ANY(relevant_tables);
```

> **建议**:执行此批量替换前,先做一次 `SELECT id, metric_name, calculation_hint FROM geo_analysis_metrics;` 的快照到本地文件,便于事后 diff 核对。

**Step 4 — 重写 `geo_report_templates.wizard_config`**:

这 2 个模板的 JSONB 较复杂,需要**整条替换**。由于内容长,这里给出**替换模式**而非完整值——在执行前,Claude 会先 SELECT 现有 JSON,生成新版 JSON,交给用户手动 UPDATE。

```sql
-- 方案 A: 类似 metrics 的 replace 法(注意 JSONB cast)
UPDATE geo_report_templates
SET wizard_config = (replace(
      replace(
        replace(
          wizard_config::text,
          'geo_company_mentions', 'geo_brand_mentions'
        ),
        'is_own_brand = true', 'brand_role = ''own'''
      ),
      'cm.is_own_brand', 'cm.brand_role'
    ))::jsonb,
    updated_at = NOW()
WHERE wizard_config::text LIKE '%geo_company_mentions%'
   OR wizard_config::text LIKE '%is_own_brand%';
```

**Step 5 — 部署代码改动**:

建议顺序(从下游到上游):
1. **Analyzer**(geo_analyzer):部署新 parsers + 修改后的 main.py。这时会开始写新表。
2. **Collector**(geo_collector):部署 prompt_expander 的 topic-only 兼容改动
3. **SaaS API**(geo_saas/src):部署 insights / settings 路由的新 SQL
4. **Agent**(geo_agent):部署 NL2SQL 的 schema hint 更新
5. **Admin API/Web 和 SaaS Web**:部署 UI 改动(Brands Tab + Products 结构化表单)

**Step 6 — 重启 Job,开始新数据采集**

### 8.2 数据迁移的回滚策略

- Schema 变更本身**不可逆**(rename 后的表可以再 rename 回去,但删除的列无法恢复)
- 因此**必须先做 Cloud SQL 快照**
- 如果发现迁移后数据异常,唯一可靠的回滚方式是:**从快照恢复整个数据库**

### 8.3 新 metrics 的 seed(可选,Phase 后续)

产品层新 metrics 的 INSERT 在实施阶段单独给出 SQL,建议在主迁移完成、稳定运行 2-3 天后再上。

---

## 9. 数据库操作规范(永久性规定)

以下规定**永久适用**于本项目的所有工作,写入此文档以供后续 session 参考:

### 9.1 Claude 可以自主执行的 SQL

```
✅ SELECT 查询(任意复杂度)
✅ EXPLAIN / EXPLAIN ANALYZE(只读性质)
✅ \d / information_schema / pg_catalog 读取(schema 描述类)
```

### 9.2 Claude 严格禁止自主执行,必须给用户 SQL 交由用户手动执行

```
❌ DDL:CREATE TABLE / ALTER TABLE / DROP TABLE / RENAME TABLE
❌ DDL:CREATE INDEX / DROP INDEX / CREATE CONSTRAINT / DROP CONSTRAINT
❌ DDL:CREATE TYPE / DROP TYPE / CREATE EXTENSION / DROP EXTENSION
❌ DML 写入:INSERT / UPDATE / DELETE / UPSERT / TRUNCATE / MERGE
❌ 事务控制:COMMIT / ROLLBACK(在 SELECT 会话以外的场合)
❌ 权限/角色:GRANT / REVOKE / ALTER USER / CREATE ROLE
❌ 数据库配置:ALTER DATABASE / ALTER SYSTEM / SET PERSISTENT
```

### 9.3 流程要求

所有非 SELECT 的 SQL,由 Claude 在设计/计划文档或对话中以**命名代码块**形式列出,标注:

1. **执行顺序**(如有依赖)
2. **预期影响**(影响多少行、影响哪些表)
3. **验证查询**(执行后如何 SELECT 验证结果)
4. **回滚方法**(如果可逆)或 **备份前提**(如果不可逆)

由用户在 **Cloud SQL 控制台或 `gcloud sql execute`** 手动执行。执行结果可以截图或文本粘贴回对话让 Claude 验证。

### 9.4 连接凭证

Cloud SQL 连接信息(用户已授权 Claude 读):
- Instance:`project-90d7849c-de16-4c15-a0a:us-central1:answer-x-geo-instance`
- User:`answer-x-geo-db-user`
- 本地连接通过 Cloud SQL Auth Proxy 监听 `localhost:5432`
- Database:`answer-x-geo-db`

若连接中断,Claude 应及时告知用户,不要反复重试。

---

## 10. Open Items 与后续迭代

### 10.1 本次不做的项(真正延后)

- **Sentence-level 情感归因**:当前和本次只做 response-level + entity-level join 归因(见 §6.4)。句子级需要 LLM 对每句子做实体+情感绑定,成本和难度都高,Phase 2 再议
- **竞品产品数据可视化的专用 Compare View**:数据模型本次已支持 `product_role='peer'`,Parser 也会识别,Insights API 可以查——但专门的 "我的 SKU × 竞品 SKU" 对比图表本次不做。用户可以在 Product Visibility 视图下通过 filter 看到同一张表里的 own vs peer 产品分布,但没有专属的并排对比组件

> **说明**:先前列在这里的"UI 渐进披露 / Onboarding Wizard / 高级字段不开放"已从"未来项"中移除——它们已在本次上线的 UX 设计里(见 §6.7 和 §6.8)。

### 10.2 本次不做、可能未来需要的项

- **产品层 peer 的可见度 SOV 专用视图**:当前设计支持 `product_role='peer'` 存储,但 Insights UI 暂不提供"竞品 SKU vs 我的 SKU"的专用对比图
- **Brand / Product / Topic 维度切换器的配置化**:Insights 的 "View By" 选项(Brand / Product / Topic / Brand×Topic / Topic×Product / Brand×Product 共现)在本次实现时**硬编码在 UI 组件里**。未来在 Agent 单独迭代时可能把这些维度迁移到 `geo_workflow_config`,让模板可以各自声明支持哪些 View By——不阻塞本次,留作 Agent 后续 iteration 的事项
- **`geo_workflow_config` 的 3 行 inactive 历史遗留**(`goal / analysis` 的 `benchmark` / `opportunity` / `sentiment_deep`):保留原样。用户可能通过 UI 把某一条重新激活(is_active → true);而且它们已经被查询时的 `WHERE is_active = true` 过滤掉,不影响现有功能。虽然 `sort_order` 上和 active 行有重号(benchmark/competitive 都是 2,opportunity/trend 都是 4),但只要前端查询用 `WHERE is_active = true` 就没有实际冲突;如果未来用户在 UI 上同时开启两行,再处理排序冲突即可
- **Sentiment 按 mention 句子级归因**:目前 sentiment 是 response 级的,未来可以做"具体是哪句话讲 HT-Series 讲负面"的精细归因
- **自动 alias 生成**:Auto-Discover 现在只返回 product 主名,未来可让 Gemini 一并生成候选 match_variants
- **Brand-aliases 冲突检测**:如果多个 client 的 brand 同名(比如两个做"Smart Home"产品的 client),需要 UI 提醒;目前靠 UNIQUE(client_id, brand_name) 只在 client 内保证唯一

### 10.3 本次顺带清理的技术债 + 数据清洗

以下技术债在本次 migration 路径上,顺手清理:

**代码清理**:
- ✅ **删除文件** `geo_agent/src/pipelines/_template_contracts_stub.py`(Phase 2 过渡产物)
- ✅ **删除文件** `geo_admin/src/routers/brainstorming.py`(已在上一轮 LEGACY 注释,本次物理删除)
- ✅ **删除文件** `geo_analyzer/scripts/backfill_dedup_mentions.py`(一次性脚本,含旧 schema)

**Schema 清理**:
- ✅ **删除列** `geo_client_peers.is_own_brand`(全库 0 true,纯遗留)
- ✅ **删除列** `geo_client_topics.products` TEXT[](数据迁移到新表后删除)

**运行时数据清洗**(无线上用户,直接清):
- ✅ **TRUNCATE** `checkpoints`(2023 行 LangGraph state,无保留价值)
- ✅ **TRUNCATE** `agent_messages`(190 行聊天历史,含旧 SQL text)
- ✅ **TRUNCATE** `agent_memories`(6 行跨会话记忆,无价值)
- ✅ **TRUNCATE** `geo_agent_tasks`(历史 agent 任务产出,含旧 SQL text)

**明确保留**(Roborock 日常监控数据):
- 🔒 `geo_results` / `geo_company_mentions → geo_brand_mentions` / `geo_citations` / `geo_sentiment_results` / `geo_sentiment_themes` / `geo_client_prompts` / `geo_tasks`——所有 Roborock 历史分析数据完整保留,不 truncate

### 10.4 关于 `geo_client_prompts.product` 的讨论(保留 TEXT,不改 FK)

**问题**:本次既然在重构 Products 到独立表,要不要把 `geo_client_prompts.product` 从 TEXT 改成 `product_id UUID REFERENCES geo_client_topic_products(id)`?

**分析**:

| 维度 | 保留 TEXT(现状) | 改为 FK |
|---|---|---|
| 历史快照完整性 | ✅ 客户改产品名 / 删产品后,老 prompt 保留当时产品名 | ❌ 客户删产品 → prompt 的 product_id 空;改名 → 老 prompt 也跟着改 |
| 引用完整性 | ❌ 没有 DB 级强约束 | ✅ 有 FK 保证 |
| 分析查询便利性 | 按文本 group by 可用 | 按 product_id join 更干净 |
| 当前数据 | 76 行全有值,功能正常 | 需要数据迁移 + 多处代码改动 |
| 迁移成本 | 0 | 中(产品名 → product_id lookup + 容错处理) |

**决定:保留 TEXT,不改 FK**。理由:

1. **历史快照是一个 feature,不是 bug**:prompts 是发出去跑过 AI、产出了 results 的,保留当时的产品名是审计需要
2. 不是"技术债":这是**合理的 denormalization**,把 denormalization 叫技术债是标签错误
3. 如果未来真要 FK,可以**并存**(ADD COLUMN product_id UUID,既有 TEXT 保留),但本次无此需要

**结论**:`geo_client_prompts.product` 列**本次不动**,语义上它是"这条 prompt 当时问的是哪个产品(文本快照)"。

---

## 附录 A:关键数据量快照(迁移时影响面)

当前数据库状态(2026-04-18 审计):

| 表 | 行数 | 备注 |
|---|---|---|
| `geo_clients` | 2 | Roborock + Tmax |
| `geo_client_topics` | 2 | 都属于 Roborock;Tmax 未配置 |
| `geo_client_peers` | 17 | |
| `geo_client_domains` | 6 | |
| `geo_company_mentions` | 10,486 | 需要重命名为 geo_brand_mentions |
| `geo_citations` | 42,607 | 不受本次迁移影响 |
| `geo_client_prompts` | 76 | 全部有 `product` 值,不受影响 |
| `geo_results` | 2,128 | 不受影响 |

## 附录 B:当前配置类 SQL 片段的引用面统计

| 位置 | 引用 `geo_company_mentions` | 引用 `is_own_brand` |
|---|---|---|
| `geo_analysis_metrics.calculation_hint` | 6 / 11 rows | 5 / 11 rows |
| `geo_report_templates.wizard_config` | 2 templates | 2 templates |
| `geo_agent/*` 代码文件 | 8 文件多处 | 8 文件多处 |
| `geo_saas/src/routers/insights/*` 代码文件 | 3 文件多处 | 3 文件多处 |
| `geo_analyzer/main.py` | INSERT 语句 | 多处 |

---

## 附录 C:决策澄清备忘

为避免后续实施时反复翻历史对话,这里记录几个关键决策及其理由:

| 决策 | 结论 | 理由 |
|---|---|---|
| Topic = 渠道名(如 Topic = "Rough Country")? | ❌ 否决 | 污染 Topic 语义;Prompt Expander 会生成无意义的 prompt;渠道表现由 Domain + Channel category 覆盖 |
| 把 RC 既放 Brands 又放 Peers? | ❌ 禁止 | DB 层建议加约束(UNIQUE(client_id, name) 跨表);用 Product 层的 `product_role` 表达边界情况 |
| 用户切换 Brand-only / Product-only / Hybrid 追踪? | ❌ 不做 | 纯数据驱动:填什么追什么。UI 层根据存在数据自动展示 |
| `is_own_brand` boolean vs `brand_role` enum? | ✅ 选 enum | Shadow 不等于 Own 也不等于 Peer,三值 enum 更准确 |
| `is_own` boolean on Products vs `product_role` enum? | ✅ 选 enum + FK | 支持 own / shadow_brand_native / peer 三种,含 owner FK |
| 分开 geo_brand_mentions 和 geo_peer_mentions 两张表? | ❌ 合并 | 匹配逻辑相同,用一张表 + enum 区分 |
| 本次同时支持竞品产品追踪(product_role='peer')? | ✅ 一次到位:schema / 代码 / UI 都在本次上线;UI 用渐进披露(Advanced 折叠)降低普通用户的认知负担 | 数据模型一次到位;Advanced 折叠是 UX pattern,不是 release 分期 |
| Prompt Expander 大改? | ❌ 小改 | 现在读 client_prompts 不读 topics.products,基本无感;只改 brainstorming 的 prompt 生成逻辑 |
| `geo_client_prompts.product` TEXT 改 FK? | ❌ 保留 TEXT | 这是故意的 denormalization:历史 prompt 保留当时的产品名,不被客户改名/删除影响 |
| Onboarding Wizard 做不做? | ✅ 本次做 | 用"Own brand or OEM supplier?"两分支引导填充默认值,配合 UI 渐进披露使用;见 §6.8 |
| Sentiment 实体归因(brand/product level)是本次做吗? | ✅ 本次做 **response-level join 归因**,❌ 不做 sentence-level | response-level via join 是纯 SQL 能力,无需新 NLP;sentence-level 需要 LLM,Phase 2 再议 |
| Agent 历史 `geo_agent_tasks.output` / `agent_messages` / `checkpoints` / `agent_memories` 怎么处理? | ✅ 全部 TRUNCATE | 产品无线上用户,没有需要保留的对话历史;TRUNCATE 比 backfill 简单,也避免旧 SQL text 残留 |
| Roborock 历史监控数据(geo_results / geo_company_mentions 等)保留吗? | ✅ 完整保留 | 这是唯一的生产数据,迁移必须保证历史 dashboard 能继续展示 |
| 迁移时停机协调 / 用户通知? | ❌ 不需要 | 产品无线上用户,只需暂停 Analyzer/Collector Job 防止写入冲突 |

---

**— 文档结束 —**
