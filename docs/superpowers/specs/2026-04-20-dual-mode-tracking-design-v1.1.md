# Dual-Mode Tracking — Spec v1.1 (Finalized Working Draft)

> **日期**:2026-04-20
> **作者**:lancelot × Wentao × Claude
> **基线**:[Spec v1.0 (2026-04-18)](./2026-04-18-dual-mode-tracking-design.md)
> **状态**:待最终定稿(Review Phase 2)
> **参考**:Profound 对标分析([飞书版](https://www.feishu.cn/docx/Cdbnd3PQRoPTDRxWXyZc9Jjnn1d))、CPO 机器人 04-20 群内纪要

---

## 0. 本版相对 v1.0 的变更概览

| 类别 | 变更 | 驱动 |
|---|---|---|
| **架构大方向** | ✅ 不变 — Shadow Brand 一等实体 + Products 结构化 + 两张 mention 表 | 04-20 Wentao 确认 |
| **新增产品语义** | 🆕 Peer 也可录入 Peer Products + SKU 变体(显式 UI,v1.0 仅 schema 暗藏) | KFC/McDonald's 三类 Peer 场景 |
| **新增设计原则** | 🆕 Alias 语义纯净原则 + 未来 LLM 切换可行性论证 | 04-20 思聪 vs 文韬 alias 扁平化之争 |
| **新增产品场景** | 🆕 KFC / McDonald's 三类 Peer 决策依据 | 讨论中建立的共识比喻 |
| **新增决策点** | 🆕 Decision #4:Citation + Domain 重构(3 方案待决) | 思聪反思:Brand 升级后 Own Domain 语义耦合 |
| **Schema 变更** | ❌ 无增量 DDL — v1.0 schema 已完全支持 v1.1 所有产品语义 | 确认 |
| **Parser** | ✏️ 明确 ProductParser 同时跑 Peer Products(v1.0 schema 已支持,代码实现需显式) | |
| **Open Items** | 🔁 原 3 个决策(Phase 1 n-gram Queue / peer_match_mode 字段 / Phase 2-3 时机)保留 | 04-19/20 讨论未触达,仍待决 |
| **附录 C** | 🆕 补 6 条新决策记录 | |

---

## 1. 背景 — 承接 v1.0

v1.0 §1 的核心论据(品牌=客户的隐式契约在 OEM 场景失效、OEM 体量是自营品牌 10 倍、产品命名空间可字面匹配)**全部成立,不改写**。

v1.0 以降,围绕 Peer 维度的设计做了深入讨论。核心新增是下面 §2 的"**三类 Peer 场景**"框架 —— 在 v1.0 里这部分只有抽象论述("可以通过 product_role='peer' 表达"),v1.1 把它明确为**产品级决策要求**。

---

## 2. 产品设计 — 新增与明确

### 2.1 三类 Peer 场景:KFC / McDonald's 比喻

**承接 v1.0 §2.3 形态 B(Tmax)**,v1.1 明确"OEM 客户的 Peer"究竟如何建模。

举例设定:
- **天铭** = 国内做越野踏板的 OEM 工厂(Client)
- **Rough Country(RC)≈ KFC** = 天铭在美国的代理;RC 同时卖:天铭、ABC、DEF 三家 OEM 的产品 + 自家品牌 SKU
- **McDonald's** = 另一家代理,只卖 ABC / DEF(不卖天铭)
- **ABC / DEF** = 其他国内 OEM 工厂

**三类 Peer 对应策略**:

| Peer 类型 | 含义 | 建模方案 | 本轮是否做 |
|---|---|---|---|
| **Type 1:其他国内 OEM**(ABC / DEF) | 和天铭类似的 OEM,品牌在互联网上"匿名" | 理论上可作为 Peers 维护,但追不到流量 | ❌ 不做,成本高收益极低 |
| **Type 2:纯竞争 Shadow Brand**(McDonald's) | 不卖天铭产品的独立代理 | 作为 Peer 实体;可选挂 Peer Products(McDonald's 卖的 ABC / DEF 型号) | ✅ **本轮做** |
| **Type 3:同渠道 Shadow Brand 的非 HT 流量**(RC = KFC) | 自己的代理商 RC,但语义是"RC 品牌 + 非 HT 型号"这个组合 | 通过 `product_role='peer'` 的 Product 条目(挂 owner_peer_id → RC 的 Peer 记录),追踪 RC 卖的**非天铭** SKU | ✅ **本轮做**(仅 series 级,不区分 RC 自营 vs 代理他人) |

**典型 AI 回答场景(论证为何必须支持 SKU 级识别)**:

用户问 `"In Rough Country, which side step is best for Ford?"`

| AI 回答 | 当前行为 | v1.1 目标行为 |
|---|---|---|
| "the XXX-Series and YYY-Series from Rough Country are a popular choice" | 只要 "Rough Country" 被提到 → 天铭 visibility +1(**错误**) | 识别 XXX/YYY 是**非 HT SKU**,不给天铭 +1;给 RC Peer +1(上下文:RC 卖非天铭产品) |
| "HT-Series running boards, XXX-Series from Rough Country" | HT +1 正确,但 XXX 未识别成竞品 SKU,RC 作为 Peer 可见度丢失 | HT 作为 Own Product +1,XXX 作为 Peer Product +1,RC 作为 Peer 品牌 +1 |
| "HT-Series, XXX-Series, YYY-Series from Rough Country" 且 XXX 是 RC 自营、YYY 是 RC 代理他人 | 同上,两者都算 Peer | **本轮不区分 RC 自营 vs 代理**;两者都标为 `product_role='peer'` 挂 RC 这个 Peer,子分类延后 |

### 2.2 Alias 语义纯净原则(核心设计哲学)

**问题起源(04-19 讨论)**:文韬提议用现有 alias 机制扁平化:【天铭 = HT】、【Peer A alias = AS/AT 系列】,避免新表。

**拒绝该方案的理由**:

1. **Alias 的语义契约**:
   - `Client.aliases` / `Brand.aliases` = "这个品牌名的变体"(大小写、缩写、连写)
   - `Peer.aliases` = "这个竞品品牌名的变体"
   - `Product.match_variants` = "这个具体 SKU/型号的变体"

2. **为何不能塞混**(论证):
   - **Profound 能用 LLM 开放式抽取**,**是因为**它们的 alias 语义纯净:客户 alias 只装客户名变体,Peer alias 只装 Peer 名变体。LLM 可以把抽到的字符串直接对上去。
   - **我们如果 alias 里塞混"品牌名 + 代理商名 + SKU 型号"**,未来从正则切 LLM 识别时,prompt 无法区分"这个 alias 对应的实体类型是什么"。语义混乱。
   - 即便继续用正则,维护体验也会退化(一个客户的 alias 列表里混着品牌、代理商、型号,UI 和 CRUD 都失焦)。

3. **设计原则(本次确立,供未来所有 schema 讨论引用)**:
   > **Alias 字段只装"同一实体类型的命名变体"。任何跨类型扁平化的需求,通过新增实体或字段表达,不塞 alias。**
   
   这是 v1.1 的**架构红线**。为未来切 LLM 识别保留干净的语义基础。

4. **对 Wentao 的 extendability 顾虑的回应**:
   - 承认不应不断"加层"作为通用模式
   - 但本轮加 Shadow Brand(一等实体)+ Peer Products 子层,是为消除 alias 语义污染所必需的**结构化投资**
   - 一旦结构化,未来扩展不需要再堆字段 —— 真正的 extendability 来自"干净的语义 + 可替换的识别策略",不是"少加字段"

### 2.3 Peers 层扩展:Peer 也可录 Peer Products

**v1.0 schema 已支持**(§3.2.2 中 `geo_client_topic_products.product_role='peer'` + `owner_peer_id` FK),但 UI/UX 层在 v1.0 仅作"Advanced 折叠选项"一笔带过。

**v1.1 明确纳入产品主流程**:

- **Peers Tab** 下每个 Peer 卡片可展开 **"Peer Products"** 子管理面板,直接录入该 Peer 卖的产品(主名 + match_variants)
- 对 OEM 客户(Tmax)来说,McDonald's 的 ABC/DEF SKU、RC 的非 HT SKU 都通过此处维护
- 对自营品牌客户(Roborock)来说,**默认折叠**,不展示(保持 UX 简洁)

写入的 Product 条目:
- `product_role = 'peer'`
- `owner_peer_id = <该 Peer 的 id>`
- `topic_id = <对应 topic>`(复用现有 Topic → Products 结构)

### 2.4 Topic 建模(承接 v1.0 §2.4)

**不变**。Topic = 语义分组字符串,支持按业务品类(`Off-Road Running Boards`)或按用户痛点(`Pet Hair Cleaning`)命名。禁止 Topic = 渠道名。

### 2.5 三种观察诉求(承接 v1.0 §2.5,新增一条)

| 诉求 | 实现 |
|---|---|
| **诉求 1**:我的产品在 AI 里整体可见度 | 产品层 mentions,按 `product.name` 聚合,筛选 `product_role='own'` |
| **诉求 2**:Shadow Brand 本身可见度 | 品牌层 mentions,按 `brand_name` 聚合,筛选 `brand_role='shadow'` |
| **诉求 3**:我的产品在 Shadow Brand 上的表现 | 同一条 response 里 Brand(Shadow)∩ Product(own)共现 |
| **🆕 诉求 4**:Shadow Brand 上**非我**的流量 | 同一条 response 里 Brand(Shadow)∩ Product(`peer`, `owner_peer_id=<该 Shadow 对应的 Peer 镜像>`)共现;或 Brand(Shadow)但无 own Product mention |

诉求 4 是 KFC Type 3 场景的量化指标 —— 天铭核心 OEM 竞争情报之一。

### 2.6 Parser 运行策略(承接 v1.0 §2.6,明确 Peer Products 归属)

系统**永远并行跑所有 Parser**:
- **BrandParser** 匹配 Brands(Own + Shadow)+ Peers → `geo_brand_mentions` with `brand_role`
- **ProductParser** 匹配所有 active Products,**无论 `product_role` 是 own / shadow_brand_native / peer** → `geo_product_mentions` with `product_role` 和 denormalized owner 信息

客户配置什么就追踪什么,Insights UI 按数据存在与否自动呈现视图。

### 2.7 Brand 与 Peer 名互斥(承接 v1.0 §2.7)

**不变**。同一字符串不能同时在 `geo_client_brands` 和 `geo_client_peers`。

### 2.8 Topic-only 宽松模式(承接 v1.0 §2.8)

**不变**。允许 Topic 下不配 Products,Parser 跳过该 Topic,Insights UI 优雅处理空数据。

---

## 3. 数据模型变更 — 确认不变

**v1.0 §3 的 schema 完全适配 v1.1 的所有产品语义**。包括:
- `geo_client_brands`(Own + Shadow)✅
- `geo_client_topic_products`(`product_role` enum + `owner_peer_id` FK)✅ — v1.1 的 Peer Products 就是在这张表
- `geo_brand_mentions`(重命名 + `brand_role` ENUM)✅
- `geo_product_mentions`(含 denormalized owner 信息)✅

**无新 DDL**。v1.0 §3 的 SQL 迁移计划全部继承到 v1.1,见 §8。

---

## 4. Parser 架构 — 微调

### 4.1 ProductParser 明确拿到 Peer Products

```
Phase 0:加载 brands / peers / domains
        + tracked_products(全部 product_role,不筛选)
```

**SQL**(承接 v1.0 §4.4):

```python
tracked_products_rows = conn.execute(text("""
    SELECT tp.id, tp.product_name, tp.match_variants, tp.product_role,
           tp.owner_brand_id, cb.brand_name AS owner_brand_name,
           tp.owner_peer_id,  cp.primary_name AS owner_peer_name
    FROM geo_client_topic_products tp
    LEFT JOIN geo_client_brands cb ON cb.id = tp.owner_brand_id
    LEFT JOIN geo_client_peers  cp ON cp.id = tp.owner_peer_id
    WHERE tp.client_id = :client_id AND tp.is_active = true
    -- v1.1 强调:无 product_role 筛选,own / shadow_brand_native / peer 全部跑
"""), {"client_id": client_id}).fetchall()
```

写入 `geo_product_mentions` 时,`product_role` 与 `owner_*_name`(denormalized)固化。

### 4.2 BrandParser 不变

承接 v1.0 §4.2。匹配 Brands(Own + Shadow)+ Peers,写入 `geo_brand_mentions`,`brand_role` 三值区分。

### 4.3 兼容性(承接 v1.0 §4.5)

**不变**。迁移脚本为每个存量 client 在 `geo_client_brands` 插 `(name, aliases, is_shadow=false)`。

---

## 5. Agent NL2SQL 与配置类 SQL 适配

**承接 v1.0 §5 全部审计结果和重写策略,无增量改动**。包括:
- `geo_analysis_metrics.calculation_hint` 批量 replace
- `geo_report_templates.wizard_config` JSONB 重写
- Agent 代码中 `ALLOWED_TABLES` / `TABLE_HINTS` / 硬编码 SQL 的文件清单
- 运行态表 TRUNCATE(checkpoints / agent_messages / agent_memories / geo_agent_tasks)

**v1.1 额外建议的 metrics**(本次不做,Phase 2+):
- `peer_product_cooccurrence_shadow`:Shadow Brand ∩ Peer Product 共现次数(诉求 4)
- `peer_product_sov_in_shadow`:Shadow Brand 内 Peer Products 的 SOV 占比

---

## 6. SaaS Insights 与前端适配

### 6.0-6.5 承接 v1.0 § 6.0-6.5,不变

- View By 切换(Brand / Product / Topic / Brand×Topic / Topic×Product / Brand×Product 共现)
- brand_role / product_role 筛选
- Sentiment 做 response-level entity join 归因(不做句子级)
- Visibility / Citation / Sentiment 三大 Dashboard 改造 API 清单

### 6.6 前端组件改动 — 新增 Peer Products UI

承接 v1.0 §6.6,以下为 v1.1 增量:

**Settings 页面**:
| 位置 | v1.0 | v1.1 新增 |
|---|---|---|
| **Peers Tab** | 只有 `primary_name + aliases` | 🆕 每个 Peer 卡片可展开 "Peer Products" 子面板,录入 `product_name + match_variants`(结构同 Own Products) |
| **Topics Tab** | Products 录入 + advanced 折叠 `product_role / owner_*` | 不变,但对于 OEM 客户 Onboarding 流后会有新引导 |
| **Onboarding Wizard**(v1.0 §6.9)| "OEM" 分支引导填 Shadow Brand | 🆕 完成 Shadow Brand 后,下一步引导"配置代理商上的竞争 SKU"(进入 Peers → Peer Products) |

**Insights 组件**:
- **VisibilityDashboard**:在 Peer 维度增加 Peer Products 统计子视图(默认折叠)
- **CooccurrenceHeatmap**:除 Shadow ∩ Own Product,新增**Shadow ∩ Peer Product**视图(诉求 4)
- 其他组件不变

### 6.7 Progressive Disclosure — 扩展

承接 v1.0 §6.7,新增:
- **Peer 卡片的 "Peer Products" 子面板**:默认折叠,标签"This peer's products sold on this or other channels"
- 只在 Wizard 选 OEM / Both 分支时,Peers Tab 打开时默认展开首个 Peer 的 Products 区域

### 6.8 Fallback 逻辑 — 补一条

承接 v1.0 §6.8,加入:

| 组件 | 没 Peer Products 数据时 |
|---|---|
| Shadow ∩ Peer Product 共现视图 | Empty state:"Track your competitors' SKUs on this distributor — configure in Settings → Peers → [peer] → Peer Products" |
| Peer Product SOV | 同上 |

### 6.9 Onboarding Wizard — OEM 分支扩展

承接 v1.0 §6.9 的四分支:
- **"No"(OEM)** 分支完成 Shadow Brand 录入后,追加一步:"**Optional: add competing SKUs sold on the same channel**",引导进入 Peers → Peer Products 页面
- Tooltip:"Skip if you only care about your own products. Add later in Settings."

---

## 7. Prompt Expander 与 Topic-only 模式

**承接 v1.0 §7,不变**。`geo_client_prompts.product` 列保留 TEXT 不改 FK。Brainstorming 的 prompt 生成逻辑在 products 为空时走 Topic-only fallback 模板。

---

## 8. Migration Plan — 承接 v1.0 §8

v1.0 §8 的所有 DDL/DML 完整继承:
- §8.2.1~8.2.11 全部 SQL 不变(`geo_client_brands` / `geo_client_topic_products` / `geo_brand_mentions` 重命名 / `geo_product_mentions` 新建 / `geo_client_peers.is_own_brand` 删 / `geo_client_topics.products` 删 / Onboarding 字段 / TRUNCATE agent 运行态)
- Step 3/4/5 的 metrics / templates / 代码部署顺序不变

**v1.1 无额外 DDL**。

---

## 9. 数据库操作规范

**承接 v1.0 §9,永久规则。Claude 不自主执行 DDL/DML 写入,全部交用户手动执行**。

---

## 10. Open Items — 更新后的待决清单

### 10.0 决策状态一览

| 编号 | 决策 | v1.0 状态 | v1.1 状态 |
|---|---|---|---|
| #1 | Unmapped Candidates n-gram Review Queue(Profound 风格低成本版)是否纳入本轮? | 待决 | **04-19/20 讨论未触达,仍待决**。Wentao 倾向"了解 Profound 即可,不 copy",可能自动倾向**延后**,但需显式确认 |
| #2 | `peer_match_mode` ENUM workspace 级开关是否预留? | 待决 | **仍待决**。可能与 Alias 语义纯净原则冲突 —— 如果开关意味着 alias 会变扁平,应否决 |
| #3 | Phase 2 / 3 时机(LLM Discovery Pass / 实时 LLM 抽取) | 待决 | **仍待决**。建议:第 3-5 客户时评估 Phase 2,MRR≥$10k 评估 Phase 3 |
| #4 | **(新)**Citation + Domain 重构 —— Own Domain 拆分为 Own / Shadow / Product URL | 未列 | **新纳入待决**,见 §10.4 |

### 10.1 本次不做(确认延后)

承接 v1.0 §10.1,**新增一条**:
- **Case 3 子区分(RC 自营 vs RC 代理他人 SKU)**:本轮不做,所有 Peer Products 统一标记 `product_role='peer'`,owner_peer_id 指向对应 Shadow Brand 的 Peer 镜像。子分类留给 Content Agent 迭代

### 10.2 未来可能需要的项

承接 v1.0 §10.2,**新增**:
- **Peer Products SOV 专用视图**(区别于 Own Products)
- **Shadow Brand 内非我流量监控**(诉求 4 量化)
- **Peer Product Auto-discovery**:基于 Shadow Brand 网站结构化 crawl 获取他们自家和代理的 SKU

### 10.3 技术债清理

承接 v1.0 §10.3,**不变**。

### 10.4 Decision #4(新):Citation + Domain 重构

**背景**:v1.0 的 `geo_client_domains` 是单列 TEXT,`url_is_owned` 单布尔值,所有匹配 URL 都归为"Owned Media"。引入 Brand(Own / Shadow)后出现语义耦合:

- `tmax.com` 的 citation 和 `roughcountry.com/product/ht-70911` 的 citation 现在都是"Owned Media",但前者是 Tmax 自家官网,后者是 Tmax SKU **在 Shadow Brand 上的具体页面**,两者应该可区分
- Shadow Brand 站上**非** Tmax 的 SKU 页(ARB bull bar)不应被 Tmax 视为自家 citation
- 当前架构无法做 **Product-level citation 归因**(无 FK 回 `geo_client_topic_products`)

**Profound 做法对照**:Profound 有 Citation Tags(Owned / Competitor / Social / Custom 纯手动 4 类,支持 URL subpath),**无 Shadow Brand 概念**。我们要做的比 Profound 更细(role + FK 到 brand/product),是 OEM 垂直差异化。

**三个候选方案**:

| 方案 | 改动 | 优点 | 缺点 |
|---|---|---|---|
| **A. 最小增量** | `geo_client_domains` 加 `domain_role` enum(own/shadow/channel/custom)+ `owner_brand_id FK` + `owner_product_id FK` | 一张表,改动最小,向后兼容(默认 own) | 语义上仍把"自家官网"和"Shadow 上 SKU URL"混在一张表 |
| **B. 拆表** | `geo_client_domains`(只装 Own 官网)+ 新增 `geo_client_tracked_urls`(Shadow 上的 SKU/系列页,带 brand_id + product_id FK) | 语义最清晰,承接 auto-discovery 自动写入 | 要迁数据(但 Roborock 只有 3 条 whole-domain,无痛) |
| **C. 挂在 Product 上** | `geo_client_topic_products` 加 `tracking_urls TEXT[]` | Product-citation 归因天然 | Own brand domain 仍独立,两套逻辑并存 |

**Citation Parser 产出升级(无论哪个方案)**:

从单布尔 `url_is_owned` → **`citation_role` enum**:
```
'own'            — URL host = Own Brand domain (tmax.com)
'shadow_product' — URL 在 Shadow Brand 站,且匹配我们 Product 的 URL 模式
'shadow_other'   — URL 在 Shadow Brand 站,但不是我们的 product
'peer_channel'   — URL 在 Peer 域名
'earned' / 'social' / 'agency' / 'other'  (来自 domain_classifier)
```

同时 `geo_citations` 加 `matched_brand_id` / `matched_product_id` 两个可空 FK,支持 "Citation by Product" 视图。

**当前状态**:**暂缓,作为 Decision #4 候选**。下轮讨论决定(a)是否本轮做;(b)做的话选哪个方案。

**若决定做,影响**:
- 工作量:+3-5 天
- 迁移:若选 B 需要迁 Roborock 现 6 条 domain
- UI:Settings 增加 "Tracked URLs" 子面板
- Insights:Citation Dashboard 新增 "Citation by citation_role" 视图

### 10.5 关于 `geo_client_prompts.product`(v1.0 §10.4)

**不变**,保留 TEXT 不改 FK。

---

## 附录 A:关键数据量快照(不变)

承接 v1.0 附录 A,数据量引用不变。

---

## 附录 B:配置 SQL 引用面统计(不变)

承接 v1.0 附录 B。

---

## 附录 C:决策澄清备忘 — 新增

v1.0 附录 C 全部保留,**v1.1 新增以下决策记录**:

| 决策 | 结论 | 理由 | 来源 |
|---|---|---|---|
| 用 alias 扁平化替代 Shadow Brand 新实体? | ❌ 否决 | 违反 alias 语义纯净原则;未来切 LLM 识别时 prompt 无法定位实体类型 | 04-19/20 讨论 |
| Peer 是否可录入 Peer 的 Products 与 SKU? | ✅ 明确支持 | v1.0 schema 已支持(`product_role='peer'` + `owner_peer_id`),v1.1 UI/UX 显式纳入 | 04-19/20 KFC/McDonald's 场景 |
| Peer Products 的 UI 是否默认展开? | ❌ 默认折叠 | Roborock 类无感;OEM Onboarding 分支下首个 Peer 默认展开作为引导 | 渐进披露原则 |
| RC 自营 vs RC 代理他人的 SKU 子区分? | ❌ 本轮不做 | `product_role='peer'` 已够用,子分类 ROI 低,延后 Content Agent 迭代 | 04-19 KFC 讨论 Case 3 |
| Alias 语义纯净是否要写入架构红线? | ✅ 是,作为设计哲学 | 论证见 §2.2,未来所有 schema 讨论的评估基线 | 04-20 讨论收尾 |
| Citation + Domain 重构(Own Domain 拆分)是否本轮做? | 🟡 待决,作为 Decision #4 | Brand 升级后 Own Domain 语义耦合;3 方案各有 trade-off | 04-20 反思 |

---

## 附录 D:本版更新索引(for Spec readers)

相较 v1.0,以下 §号有实质增量或覆写:
- §2.1(新):KFC/McDonald's 三类 Peer 场景
- §2.2(新):Alias 语义纯净原则 + 架构红线
- §2.3(新):Peer Products 显式纳入产品主流程
- §2.5(新):诉求 4 — Shadow Brand 内非我流量
- §4.1(明确):ProductParser 不筛 product_role
- §6.6(新增):Peer Products 子面板 UI
- §6.9(扩展):OEM Onboarding 追加 Peer Products 步骤
- §10.0(更新):决策状态一览
- §10.1(新增):Case 3 子区分延后
- §10.4(新):Decision #4 Citation + Domain 重构
- 附录 C(新增):6 条 v1.1 决策记录

**以下 §号继承 v1.0 不变**(提 v1.1 时可直接引用 v1.0 对应章节):
- §1 背景动机 / §2.4 Topic 建模 / §2.6 Parser 并行策略 / §2.7 互斥规则 / §2.8 Topic-only
- §3 整个数据模型变更(schema)
- §4.2 BrandParser / §4.3 Analyzer Pipeline / §4.5 兼容性
- §5 整个 NL2SQL / 配置 SQL 适配审计
- §6.0-6.5 / §6.7 / §6.8 大部分 Insights 改动
- §7 Prompt Expander
- §8 整个 Migration Plan(SQL 序列)
- §9 DB 操作规范
- §10.2 / §10.3 / §10.5 未做项与技术债
- 附录 A / B

---

## 下一步

1. **本文档 review**:用户 + Wentao 看 v1.1,focus §2.1-2.3、§10.0、§10.4
2. **定 Decision #1 / #2 / #3**:Wentao 提供意见后拍板(v1.1 里仍标待决)
3. **定 Decision #4**:Citation + Domain 重构的 3 方案讨论收口
4. **v1.1 finalize**:上述决策合入后,本文件升级为 v1.2 Final(或并入 v1.0 做原地 amendment)
5. **进入实施阶段**:Plan 文件([2026-04-18-dual-mode-tracking-plan.md](../plans/2026-04-18-dual-mode-tracking-plan.md))增量更新 task 清单;Migration SQL 文件起草;subagent-driven 执行

---

*本文件基于 04-19 21:50 - 04-20 00:35 陈思聪与 Wentao Li 47 条消息纪要,Profound 对标分析,以及 v1.0 设计文档整合而成。待再一次 review 后定稿。*
