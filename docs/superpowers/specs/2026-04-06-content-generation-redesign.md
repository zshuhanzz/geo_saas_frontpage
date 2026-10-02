# GEO 内容生成优化架构重设计 — 产品设计文档

**文档版本**：v1.0
**日期**：2026-04-06
**参与者**：lancelot Chen × Claude（AI）
**状态**：待 Wentao 评审

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [三层优化框架](#2-三层优化框架)
3. [三节点链路架构](#3-三节点链路架构)
4. [Analyzer 节点：模板体系设计](#4-analyzer-节点模板体系设计)
5. [「优化机会发现」模板：详细 Workflow](#5-优化机会发现模板详细-workflow)
6. [Content 节点：Revised Pipeline](#6-content-节点revised-pipeline)
7. [策略层（Layer 3）详细设计](#7-策略层layer-3详细设计)
8. [反馈闭环（概念设计）](#8-反馈闭环概念设计)
9. [设计原则总结](#9-设计原则总结)
10. [论文对接：AgenticGEO MAP-Elites](#10-论文对接agenticgeo-map-elites)
11. [附录：术语表](#11-附录术语表)

---

## 1. 背景与动机

### 产品核心问题

GEO 产品要回答用户一个核心问题：**「我的品牌在 AI 搜索里是什么形象，我该怎么改变它？」**

这个问题拆开是三层：

| 层 | 问题 | 产品现状 |
|----|------|---------|
| 我在哪里 | 监测品牌在 AI 引擎中的可见度、引用、情感 | 做得不错（Visibility 模块） |
| 为什么是这样 | 理解 AI 的内容偏好和引用逻辑 | 有雏形（Analyzer 模板） |
| 我能做什么 | 生成能被 AI 引用的内容，选择正确的分发渠道 | **未闭环**（Content Pipeline 需要重设计） |

### 改造动机

1. **现有内容生成缺乏方法论指导**：Content Pipeline 的第一步是自由文本的「内容目标」，没有结构化的优化框架。
2. **上游数据准备不足**：内容生成缺少 Topic 定位、选题发现、平台引用关系等前置分析。
3. **链路断裂**：Analyzer 的分析结果无法自动流入 Content 节点。
4. **论文可对接**：AgenticGEO 论文（arXiv:2603.20213）的 MAP-Elites 策略进化机制可以直接对接到策略层。

### 改造范围

不只是改内容生成，而是设计完整链路：Visibility → Analyzer → Content → 反馈闭环。

---

## 2. 三层优化框架

### 框架概述

基于 AgenticGEO 论文研读，结合现有 RAFT 方法论，提出三层优化体系：

| 层 | 名称 | 特点 | 变化频率 |
|----|------|------|---------|
| Layer 1 | **Success Metrics（成功指标）** | 4 大衡量体系，产品核心主轴 | 稳定，基本不变 |
| Layer 2 | **Sub-goals（子目标）** | 每个 Metric 下的细分目标 | 中等，随产品迭代逐步增加 |
| Layer 3 | **Strategy（策略）** | 实现 Sub-goals 的具体执行方法 | 最动态，持续进化 |

### Layer 1：Success Metrics（4 个）

| Metric | 中文 | 定义 |
|--------|------|------|
| **Readability** | 可读性 | 内容是否容易被人类理解、被 AI 引擎解析 |
| **Answerability** | 可做答案性 | 内容是否能直接成为 AI 回答的素材 |
| **Trustworthy** | 可信赖性 | 内容是否具备权威性和可验证性 |
| **Freshness** | 时效性 | 内容是否紧跟热点且保持时效 |

### Layer 2：Sub-goals（9 个，可扩展）

| Metric | Sub-goal | 定义 |
|--------|----------|------|
| **可读性** | 内容可理解度 | 语言清晰、用词精准、目标受众能读懂 |
| | 机器可读性 | 结构清晰（heading hierarchy）、schema markup、AI 能提取干净的答案 |
| **可做答案性** | 信息呈现 | 页面上是否直接呈现了 AI 需要的答案信息 |
| | 受众贴合度 | 内容的目的、调性、key message 是否匹配目标受众 |
| | 平台贴合度 | 内容格式/风格是否匹配发布平台（Wiki、Reddit、测评站等）。注意：这里的「平台」指内容发布平台，不是 AI Platform（ChatGPT/Gemini 等） |
| **可信赖性** | 权威性 (E-E-A-T) | 专业凭证、第一手经验、权威背书 |
| | 可验证性 | 引用来源、数据有出处、claims 可被第三方验证 |
| **时效性** | 热点相关度 | 内容是否紧扣当下与品牌/产品相关的热点话题。在实时生成内容时，这是主要考量维度 |
| | 发布时效 | 内容的发布/更新时间。主要用于评价存量内容或客户过往生成的内容 |

Sub-goals 的设计原则：
- 每个 Metric 下至少 1 个 Sub-goal，可以有多个
- Sub-goals 可随产品迭代逐步新增
- Content 节点中 Metrics 和 Sub-goals 均支持多选

### Layer 3：Strategy（动态策略）

Strategy 是三层中最动态的一层。详见 [第 7 节](#7-策略层layer-3详细设计)。

### 与论文的对接

AgenticGEO 论文的 MAP-Elites Archive 直接对应 Layer 3 Strategy。Archive 存储和进化的是策略库，不涉及 Layer 1 和 Layer 2。论文的技术方案可以直接接入 Strategy 层，不需要改动 Metrics 和 Sub-goals 的定义。

---

## 3. 三节点链路架构

### 架构概述

```
┌─────────────────────────────────────────────────────────┐
│                    Visibility（数据层）                    │
│  SOV 仪表盘 · Citation 仪表盘 · Sentiment 仪表盘          │
│  数据采集 + 可视化，不做分析判断                            │
│  ➜ 不变                                                  │
└──────────────────────────┬──────────────────────────────┘
                           │ 原始数据
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Analyzer（分析层）                      │
│  基于 Visibility 数据做各种维度的分析                       │
│  模板体系：5 个模板（含 1 个升级 + 1 个新增）               │
│  核心新增：「优化机会发现」升级版                            │
│  输出结构化分析报告 + 可视化 + CTA 按钮                     │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │  自动衔接                │  手动进入
              │ 「开始生成内容」按钮       │  可选带入分析结果
              ▼                         ▼
┌─────────────────────────────────────────────────────────┐
│                    Content（生成层）                       │
│  7 个 Node 的 Slot-filling Pipeline                      │
│  Node 0 → 6（详见第 6 节）                                │
│  兜底：无 Analyzer 结果时不阻塞，支持全手动操作              │
└──────────────────────────┬──────────────────────────────┘
                           │ 内容发布后
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 反馈闭环（概念预留）                        │
│  发布回填 → 效果追踪 → 归因分析 → Topic 健康度更新          │
└─────────────────────────────────────────────────────────┘
```

### 节点职责划分

| 节点 | 职责 | 改动 |
|------|------|------|
| **Visibility** | 数据采集和可视化。SOV、Citation、Sentiment 仪表盘。只负责展示数据，不做分析判断 | 不变 |
| **Analyzer** | 基于 Visibility 数据做各种维度的分析。通过模板体系承载不同分析需求 | 新增「情感分析」模板，升级「优化机会发现」模板 |
| **Content** | 内容生成。从目标选定到策略生成到内容产出的完整 Pipeline | 重设计 Pipeline（7 个 Node） |
| **反馈闭环** | 追踪生成内容的效果，归因分析，反馈回 Topic 健康度 | 概念预留 |

### 关键设计原则

1. **数据单向流动**：Visibility → Analyzer → Content。Content 不反向写 Visibility 数据。反馈闭环是独立的异步流程。
2. **Analyzer 结果是 context，不是前置条件**：Content 节点始终可独立工作，Analyzer 结果只做上下文增强。如果用户未运行 Analyzer，Content 提供软提示但不阻塞。
3. **三层框架贯穿全链路**：Metrics/Sub-goals 在 Analyzer 里是分析维度，在 Content 里是用户选择项，在反馈闭环里是衡量标准。同一棵树，不同节点不同视角。

---

## 4. Analyzer 节点：模板体系设计

### 模板总览

| 模板名称 | 数据域 | 定位 | 状态 |
|---------|--------|------|------|
| **全面健康检查** | Visibility + Citation + Sentiment | 品牌在 AI 引擎中的整体健康度评估 | 现有保留 |
| **竞品对标分析** | Visibility + Citation | 品牌与竞品在 AI 引擎中的对比分析 | 现有保留 |
| **情感分析** | Sentiment | 专门针对品牌情感维度的深度分析 | **新增** |
| **趋势诊断分析** | Visibility + Citation + Sentiment | 相对 general 的全域趋势分析 | 现有保留 |
| **优化机会发现** | Visibility + Citation + Sentiment | 串联上游到下游的完整分析链路，为内容生成做前置数据准备 | **升级** ⭐ |

### 「优化机会发现」模板的特殊定位

「优化机会发现」是唯一一个产出结构化数据、可自动衔接到 Content 节点的模板。其他模板产出的是分析报告（文本 + 图表），供用户参考。

「优化机会发现」这个名字语义上天然连接 Analyzer → Content：发现完机会然后去行动。它承担了 Topic 定位、选题挖掘、平台分析三项前置工作，是内容生成的数据基础。

详细 Workflow 见 [第 5 节](#5-优化机会发现模板详细-workflow)。

---

## 5. 「优化机会发现」模板：详细 Workflow

### Workflow 总览

```
Step 1: Topic 四象限定位（诊断）
  ↓
Step 2: 选题机会挖掘（content_opportunities）
  ↓
Step 3: 平台-AI 引擎引用关系分析
  ↓
Step 4: 综合输出（结构化 JSON + 可视化报告 + CTA 按钮）
```

### Step 1：Topic 四象限定位

基于客户的 Topic + Product，从 Visibility/Citation 数据中计算每个 Topic 的象限位置。

**四象限定义：**

| 象限 | 品牌有内容吗？ | AI 在引用谁？ | 趋势 | 直白解释 | 对应行动 |
|------|-------------|-------------|------|---------|---------|
| **强势** | 有 | 引用品牌 | 稳定/上升 | 我们做得好，AI 在引用我们 | 维护 |
| **薄弱** | 有 | 不引用品牌 | 稳定 | 我们有内容但 AI 不买账，内容需要优化 | 修复 |
| **待挖掘** | 没有/少 | 引用竞品 | 稳定 | 有市场需求，竞品在吃这块蛋糕，我们没布局 | 进攻 |
| **新兴** | 没有 | 谁都没怎么被引用 | **上升** | 新趋势冒出来了，大家都还没布局，先到先得 | 抢占 |

**三维度判定：**

四象限不是简单的 2×2 矩阵，而是基于三个维度的综合判定：
1. **品牌内容覆盖**：该 Topic 下品牌有没有对应内容
2. **AI 引用表现**：品牌/竞品是否在被 AI 引用
3. **趋势方向**：该 Topic 的 AI 搜索量是稳定还是上升

「待挖掘」和「新兴」的核心区别：
- **待挖掘**：成熟话题，竞品已经在被引用了，品牌需要去竞争
- **新兴**：新兴话题，连竞品都还没站稳，是先发优势的窗口

**主标签 + 次标签机制：**

每个 Topic 有一个主标签（基于优先级决策树），可以有一个可选的次标签。

主标签决策树：
```
Topic AI 搜索量近期上升？
  → 是 → 主标签：新兴
  → 否 → 品牌有对应内容？
           → 有 → AI 在引用品牌？
                   → 是 → 主标签：强势
                   → 否 → 主标签：薄弱
           → 无/少 → 主标签：待挖掘
```

次标签示例：「待挖掘（趋势上升）」表示主要是品牌缺位需要进攻，但同时这个话题还在增长。

**关键设计决策：四象限是「诊断」，不是「处方」。**
- 四象限只回答「现状是什么」，不回答「该做什么」
- 行动建议（处方）在 Step 2 选题机会挖掘中产出
- 四象限展示丰富（主次标签），行动指引清晰（基于主标签）

**输出**：每个 Topic 的主标签 + 可选次标签 + 关键数据指标

### Step 2：选题机会挖掘

在 Step 1 确定了各 Topic 的象限定位后，进一步挖掘具体的内容切入角度。

**Topic vs 选题的层级关系：**

```
Topic（品类方向）
  例：Smart Home / 扫地机器人
  └─ 这是用户在管理的东西，有四象限状态

选题（内容角度/机会）
  例：「宠物家庭的扫地机器人选购指南」
      「扫地机器人噪音对比测评」
      「2026年最值得买的扫地机器人」
  └─ 这是在某个 Topic 下，AI 引擎当前偏爱引用的具体内容切入点
```

选题发现回答的核心问题：**在这个 Topic 下，现在写什么角度最容易被 AI 引用？**

**三层数据分析：**

| 层 | 分析内容 | 数据来源 |
|----|---------|---------|
| **自有内容** | 哪些已有 URL 正在被 AI 引用？这些内容有什么共性（格式、角度、深度）？ | Citation 数据中品牌域名的被引用 URL |
| **竞品内容** | 竞品被引用的内容在讨论什么角度？切入方式有何不同？ | Citation 数据中竞品域名的引用内容 |
| **AI 偏好信号** | AI 回答里反复出现的内容结构/主题模式 | Visibility 数据中 AI 回答文本的结构分析 |

**输出**：一组 content_opportunities，每个包含：
- **推荐的内容角度/切入点**（如「宠物家庭扫地机器人选购指南」）
- **机会评分**（AI 搜索量 × 品牌覆盖缺口）
- **竞品参考**（谁在这个角度被引用、怎么切入的）
- **关联的 Prompts**（这个角度对应哪些具体的 AI 搜索 Prompt）
- **推荐的 Metrics + Sub-goals**（这个机会应该重点优化哪些维度）

**可视化 — 机会地图（Bubble Chart）：**
- 横轴：AI 搜索量（该角度相关 Prompt 的搜索频率）
- 纵轴：品牌内容覆盖度（品牌在该角度是否有对应内容）
- 气泡大小：竞品被引用密度
- **右下角 = 最大机会**：AI 大量讨论，品牌还没有对应内容
- 点击气泡 → 展开推荐切入角度 + 竞品内容参考

### Step 3：平台-AI 引擎引用关系分析

分析不同内容发布平台在各 AI 引擎中的被引用情况，为后续分发推荐提供数据基础。

**分析维度：**
- 按 AI 引擎分组（ChatGPT / Gemini / AI Mode），统计各 source domain 的被引用频率
- 识别平台类型（官网、Wiki、Reddit、测评站、YouTube、媒体等）
- 结合客户的 Topic/Product，看特定领域下哪些平台被引用更多

**输出**：平台-引擎引用矩阵（示意）

| 发布平台类型 | ChatGPT 引用占比 | Gemini 引用占比 | AI Mode 引用占比 | 推荐度 |
|------------|----------------|----------------|-----------------|-------|
| 官网 FAQ/Blog | 35% | 20% | 25% | ⭐⭐⭐ |
| Reddit | 25% | 15% | 30% | ⭐⭐⭐ |
| 测评站 | 20% | 10% | 20% | ⭐⭐ |
| YouTube | 5% | 30% | 10% | ⭐⭐ |
| Wikipedia | 15% | 25% | 15% | ⭐⭐ |

### Step 4：综合输出

汇总前 3 步的分析，生成结构化推荐数据。这是 Analyzer → Content 自动衔接的数据桥梁。

**输出结构（JSON）：**

```json
{
  "analysis_task_id": "uuid",
  "client_id": "uuid",
  "generated_at": "2026-04-06T10:00:00Z",

  "topic_quadrants": [
    {
      "topic": "Smart Home",
      "product": "扫地机器人",
      "primary_quadrant": "待挖掘",
      "secondary_quadrant": "新兴",
      "action": "进攻",
      "metrics": {
        "visibility_score": 0.3,
        "citation_rate": 0.15,
        "competitor_citation_rate": 0.65,
        "trend_direction": "rising"
      }
    }
  ],

  "content_opportunities": [
    {
      "angle": "宠物家庭扫地机器人选购指南",
      "opportunity_score": 8.5,
      "related_prompts": ["prompt_id_1", "prompt_id_2"],
      "competitor_refs": [
        "竞品A在Reddit发布了对比帖，被ChatGPT引用"
      ],
      "recommended_metrics": ["answerability", "trustworthy"],
      "recommended_subgoals": ["信息呈现", "平台贴合度", "权威性"],
      "source_quadrant": "待挖掘"
    }
  ],

  "platform_recommendations": [
    {
      "platform_type": "官网FAQ",
      "engines": ["chatgpt", "ai_mode"],
      "citation_share": 0.35,
      "priority": "high"
    },
    {
      "platform_type": "Reddit",
      "engines": ["ai_mode", "chatgpt"],
      "citation_share": 0.25,
      "priority": "high"
    }
  ]
}
```

**用户在 Analyzer 看到的报告**包含：
1. Topic 四象限可视化（散点图/矩阵图，含主次标签）
2. 选题机会地图（Bubble Chart）
3. 平台引用关系矩阵
4. LLM 生成的文字洞察和建议
5. **「开始生成内容」CTA 按钮** → 带着结构化 JSON 跳转 Content 节点

---

## 6. Content 节点：Revised Pipeline

### Pipeline 总览

```
Node 0: 分析报告引入（可选）
  ↓
Node 1: 内容目标（Metrics + Sub-goals 多选）
  ↓
Node 2: 内容类型
  ↓
Node 3: 内容策略（自动生成策略组合）
  ↓
Node 4: 生成配置（AI平台 + 发布平台 + 语言 + 数量 + 品牌信息）
  ↓
Node 5: Prompt 关联
  ↓
Node 6: 确认执行
```

### Node 0：分析报告引入（可选）

**目的**：让用户选择一个已完成的「优化机会发现」Analyzer Task，将其结构化结果引入 Content 节点。

**设计：**
- 展示该客户所有「优化机会发现」类型的已完成 Task 列表
- 按时间倒序排列，显示：运行时间 / Topic 范围 / 关键发现摘要
- 用户选择一个 → 后续节点自动预填
- 用户跳过 → 全手动模式，软提示「建议先运行"优化机会发现"分析，获取数据驱动的推荐」
- 一旦选定，Analyzer Task ID 绑定到本次 Content Task

**选定后的影响链：**

| 后续节点 | 影响 |
|---------|------|
| Node 1 内容目标 | 预填推荐的 Metrics + Sub-goals（来自 `content_opportunities[].recommended_metrics/subgoals`） |
| Node 3 内容策略 | 注入 Analyzer 上下文（四象限诊断、选题机会、平台数据）用于策略生成 |
| Node 4 生成配置 | 预填发布平台推荐 + AI 平台推荐 |
| Node 5 Prompt 关联 | 锁定关联 Prompts，不可修改 |

### Node 1：内容目标

**目的**：让用户选择本次内容生成要优化的 Metrics 和 Sub-goals。

**设计：**
- 第一层：选择 Metrics（多选）

  □ 可读性 · □ 可做答案性 · □ 可信赖性 · □ 时效性

- 第二层：选择 Sub-goals（多选，基于所选 Metrics 动态展示）

  | 如选了... | 展示 Sub-goals |
  |----------|---------------|
  | 可读性 | □ 内容可理解度 · □ 机器可读性 |
  | 可做答案性 | □ 信息呈现 · □ 受众贴合度 · □ 平台贴合度 |
  | 可信赖性 | □ 权威性(E-E-A-T) · □ 可验证性 |
  | 时效性 | □ 热点相关度 · □ 发布时效 |

- 如有 Analyzer 结果 → Metrics/Sub-goals 预填推荐值，用户可修改
- 无 Analyzer 结果 → 空白，用户手动选择

### Node 2：内容类型

**目的**：选择要生成的具体内容类型。

**内容类型体系：**

| 类型 | 说明 | 适用场景 |
|------|------|---------|
| **FAQ** | 结构化问答，AI 引擎高度偏好 | AI 搜索中最常被引用的格式 |
| **AEO 文章** | AI Engine Optimized 长文，800-1200 字 | 深度内容，覆盖复杂话题 |
| **SEO 文章** | 传统 SEO 优化文章 | 客户仍有 SEO 需求，且 SEO 内容也被 AI 抓取 |
| **Content Brief** | 详细内容大纲（章节结构 + 要点 + 关键词 + 受众定位） | 客户有自己的内容团队，需要专业 GEO 优化大纲交给人去写 |
| **产品对比/测评文** | 品牌 vs 竞品的对比分析内容 | AI 引擎高频引用对比类内容 |
| **平台定制帖** | 针对特定发布平台（Reddit / Wiki / 测评站）的格式化内容 | 直接对应「平台贴合度」Sub-goal |
| **How-to / 教程** | 操作指南、使用教程 | AI 搜索中教程类内容被大量引用 |
| **Listicle** | 「Top N」类列表文章 | 高 Answerability，AI 偏爱结构化列表 |

**Content Brief 的定位**（与 Analyzer 选题机会挖掘的区别）：

```
选题机会挖掘（Analyzer 产出）       Content Brief（Content 产出）        完整文章（Content 产出）
  推荐切入角度                       详细内容大纲                        可发布的成品
  一句话描述                         章节结构 + 每节要点                  全文 800-1200 字
  机会评分                           关键数据点 + 引用建议                含 schema markup
  竞品参考                           目标关键词 + 受众定位                RAFT 质量评分
```

Content Brief 比选题机会挖掘更充实、更细致、更丰满，但不是最终可发布的文章。

**可扩展性**：Node 2 设计为可扩展，新增内容类型只需要加一个选项 + 对应的策略模板。

### Node 3：内容策略

**目的**：基于 Node 1（Metrics/Sub-goals）+ Node 2（内容类型）+ Analyzer 上下文（如有），自动生成第三层策略组合。

**策略生成逻辑：**

```
输入：
  ├─ Node 1 选定的 Metrics × Sub-goals
  ├─ Node 2 选定的内容类型
  ├─ Analyzer 上下文（如有）：
  │   ├─ Topic 四象限诊断（哪个象限 → 什么行动方向）
  │   ├─ 选题机会详情（切入角度、竞品参考）
  │   └─ 平台引用关系数据
  └─ 品牌画像（Brand Profile，全局 context）

输出：
  └─ 一组策略组合（结构化 JSON + 自然语言展示）
```

**策略展示给用户**时，是自然语言的清单，用户可以确认或微调（去掉某条、调整侧重）。底层是结构化 JSON，传给后续的内容生成 pipeline。

**示例**（基于 Analyzer 上下文）：

```
输入：
  content_opportunity: "宠物家庭扫地机器人选购指南"
  quadrant: 待挖掘（进攻）
  selected_metrics: [可做答案性, 可信赖性]
  selected_subgoals: [信息呈现, 平台贴合度, 权威性]
  content_type: AEO文章
  platform_recommendation: Reddit + 官网Blog
  competitor_refs: "竞品A在Reddit发了对比帖，被ChatGPT引用"

生成的策略组合：
  1. 信息呈现策略：首段直接回答「哪款扫地机最适合养宠物的家庭」
  2. 平台贴合度策略：
     - Reddit版本：口语化、个人体验视角、包含 upvote-friendly 对比表
     - 官网Blog版本：专业测评风格、技术参数对比、含 schema markup
  3. 权威性策略：引用第三方测评数据、包含具体参数对比、注明测试条件
  4. 进攻型策略附加：针对竞品A被引用的角度，提供更完整的数据和更好的结构
```

策略的完整结构化定义见 [第 7 节](#7-策略层layer-3详细设计)。

### Node 4：生成配置

**目的**：配置内容生成的目标参数。

**配置项：**

| 配置项 | 说明 | Analyzer 影响 |
|-------|------|--------------|
| **AI 平台** | 目标 AI 引擎（ChatGPT / Gemini / AI Mode） | 有 Analyzer 时，基于平台引用关系推荐最适合的 AI 平台 |
| **发布平台** | 内容发布平台（官网 / Reddit / Wiki / 测评站等） | 有 Analyzer 时，预填推荐的发布平台 |
| **语言** | 内容语言 | — |
| **数量** | 生成数量（如 FAQ 条数） | — |
| **品牌信息查看/补充** | 展开面板：查看当前 Brand Profile，可临时补充产品核心事实 | — |

**关于品牌信息和产品核心事实：**

- 产品核心事实（产品参数、特性、卖点、差异化优势）本质上是 Brand Profile 的一部分
- 现有 `geo_brand_profiles` 表已有 `key_messages` 和 `brand_values` 字段
- Content 节点里提供一个「查看/补充品牌信息」展开面板，让用户在需要时微调
- 不作为必经步骤，不是必填项
- 补充的信息作为 context 注入策略生成和内容生成，确保内容包含品牌想传达的信息

**关于竞品范围：**

- 竞品（Peers）从数据库自动拉取，展示给用户确认
- 作为内容生成的 context 而非用户手动输入
- 用途：生成对比类内容时知道跟谁比，进攻型策略时知道竞品在什么角度被引用

### Node 5：Prompt 关联

**目的**：确定本次内容生成要针对的 AI 搜索 Prompts。

**两种模式：**

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| **锁定模式** | Node 0 引入了 Analyzer 结果 | Prompts 由 `content_opportunities[].related_prompts` 预填，**不可修改**。因为这些 Prompt 是四象限诊断的直接产物，修改会违背分析结论。UI 展示为「已关联 N 个 Prompts（来自分析报告）」，可查看但不可编辑 |
| **开放模式** | Node 0 跳过（无 Analyzer 结果） | Prompt 选择完全开放，用户手动选择或系统自动发现低表现 Prompt |

如果用户在锁定模式下想改 Prompt，应该回到 Node 0 换一个 Analyzer 结果，或者跳过 Node 0 走全手动模式。

### Node 6：确认执行

**目的**：汇总所有前序节点的选择，让用户确认后触发内容生成 pipeline。

**展示内容：**
- 来源分析报告（如有）
- 内容目标：已选 Metrics + Sub-goals
- 内容类型
- 内容策略摘要
- 生成配置：AI 平台、发布平台、语言、数量
- 关联 Prompts 数量
- 确认按钮 → 触发后台 pipeline

---

## 7. 策略层（Layer 3）详细设计

### 策略的本质

策略不只是一个 prompt。它是一个**结构化的组合体**，包含多个维度，指导内容生成 pipeline 如何产出符合目标 Metrics/Sub-goals 的内容。

### 策略结构（JSON Schema）

```json
{
  "strategy_id": "str-001",
  "name": "提升机器可读性 × FAQ",
  "description": "针对FAQ内容，优化结构化标记和标题层级",

  "dimensions": {
    "instruction": "以FAQ问答形式组织，每个问题直接给出答案",
    "format": {
      "structure": "Q&A pairs with H2/H3 heading hierarchy",
      "schema_markup": "FAQPage JSON-LD",
      "word_count": "每条FAQ 80-150字"
    },
    "tone": "权威但易读，避免行话",
    "constraints": [
      "答案首句必须直接回答问题",
      "每条FAQ包含至少一个可验证的数据点",
      "不使用模糊表述（如'可能'、'或许'）"
    ],
    "enhancement_rules": [
      "生成后自动注入 JSON-LD structured data",
      "自动添加 internal linking 建议",
      "检查并补充缺失的产品核心事实"
    ]
  },

  "source_metrics": ["可读性"],
  "source_subgoals": ["机器可读性"],
  "content_type": "faq",
  "generation_method": "llm_with_postprocess"
}
```

### 策略的 5 个维度

对应 AgenticGEO 论文的策略基因型，加上 AnswerX 特有的增强规则：

| 维度 | 控制什么 | 示例 |
|------|---------|------|
| **Instruction** | 目标和范围 | 目标受众、核心事实、重点强调、专家角色 |
| **Format** | 输出格式 | 标题层级、schema markup、字数限制、段落结构 |
| **Tone** | 写作风格 | 权威/口语化、技术深度、正式程度 |
| **Constraints** | 严格边界 | 首句必须直接回答、必须包含数据点、禁止模糊表述 |
| **Enhancement Rules** | 后处理规则 | 生成后注入 schema、添加引用标注、补充链接 |

### 策略的实现方式

策略的落地不只是「调 LLM」，可以组合多种实现方式：

| 实现方式 | 说明 | 示例 |
|---------|------|------|
| **LLM 生成** | 核心内容由大语言模型生成 | 文章正文、FAQ 回答 |
| **后处理规则** | 生成后自动增强 | 注入 JSON-LD schema、添加 citation 标注 |
| **模板填充** | 结构化模板 + 数据填入 | FAQ schema markup、产品对比表格 |
| **多步 pipeline** | 多轮 LLM 调用，逐步增强 | 生成草稿 → 补充数据点 → 添加引用 → 格式化 |

### 策略与三层框架的关系

```
用户选择 Metrics + Sub-goals（Layer 1 + 2）
         ↓
系统匹配/生成策略组合（Layer 3）
         ↓
策略指导内容生成 pipeline
         ↓
质量评审在 Metrics/Sub-goals 维度上打分
```

### 策略层的演进路径

| 阶段 | 实现方式 | 说明 |
|------|---------|------|
| **当前（薄版本）** | 基于 Metrics × Sub-goals × 内容类型，从预定义规则中匹配策略 + LLM 辅助生成 | 够用，快速上线 |
| **中期** | 策略库管理界面，可在 Admin 中维护策略模板 | 运营可配置 |
| **远期** | 对接 MAP-Elites 进化机制，策略自动进化和优化 | 论文技术落地 |

---

## 8. 反馈闭环（概念设计）

### 设计概述

反馈闭环概念上必须有，实现上可以先预留。

```
内容生成完成
    ↓
内容发布（用户在外部平台发布，回填发布 URL + 平台 + 时间）
    ↓
效果追踪（系统自动）
    ├─ 将发布 URL 标记为「AnswerX 生成内容」
    ├─ 在后续 Visibility/Citation 采集中，识别该 URL 是否被 AI 引用
    └─ 持续监测：发布后 7天 / 14天 / 30天 的可见度变化
    ↓
归因分析（三层对比）
    ├─ 品牌整体 AI 表现（所有内容）
    ├─ 品牌自有内容表现（已知的品牌 URL）
    └─ AnswerX 生成内容表现（标记过的 URL）
    ↓
反馈回 Topic 健康度
    └─ 该 Topic 的四象限定位是否因为新内容发生了变化
       例：「宠物清洁」从「待挖掘」→「强势」
```

### 关键前置条件

1. 用户需要回填发布 URL，系统才能追踪
2. Citation 采集需要能匹配到这些 URL
3. 需要一个「内容资产」的概念，关联：Content Task → 发布 URL → Citation 数据

### 数据模型预留

```
content_assets:
  - content_task_id    关联到生成任务
  - published_url      发布地址
  - published_platform 发布平台（Reddit / 官网 / Wiki 等）
  - published_at       发布时间
  - tracking_status    追踪状态
```

### 归因的重要区分

在反馈分析时，需要区分三层表现：
1. **品牌整体表现**：所有与品牌相关的 AI 可见度
2. **品牌自有内容表现**：已知品牌域名的内容被引用情况
3. **AnswerX 生成内容表现**：通过本平台生成并发布的内容被引用情况

这个区分的目的是证明 AnswerX 的价值：用户能看到「经过我们平台生成的内容，相比品牌整体表现，带来了哪些增量贡献」。

---

## 9. 设计原则总结

| # | 原则 | 说明 |
|---|------|------|
| 1 | **数据单向流动** | Visibility → Analyzer → Content。反馈闭环是独立的异步流程 |
| 2 | **Analyzer 是 context 不是前置条件** | Content 始终可独立工作，Analyzer 结果只做上下文增强 |
| 3 | **三层框架贯穿全链路** | Metrics/Sub-goals 在 Analyzer 是分析维度，在 Content 是选择项，在反馈闭环是衡量标准 |
| 4 | **四象限是诊断不是处方** | 定位和展示（主次标签），行动在选题挖掘层产出 |
| 5 | **策略是结构化组合体** | 不只是 prompt，包含 format/constraints/enhancement rules/多种实现方式 |
| 6 | **品牌信息全局维护** | Brand Profile 全局维护一次，Content 节点可查看/补充 |
| 7 | **Prompt 锁定机制** | 引入 Analyzer 结果时，关联 Prompts 不可修改，保持分析一致性 |
| 8 | **可扩展设计** | Sub-goals 可新增、内容类型可扩展、策略库可进化 |

---

## 10. 论文对接：AgenticGEO MAP-Elites

### 论文信息

- **标题**：AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization
- **作者**：Jiaqi Yuan, Jialu Wang, Zihan Wang 等（北京航空航天大学）
- **发布**：2026-03-02 | arXiv: 2603.20213
- **代码**：https://github.com/AIcling/agentic_geo

### 论文核心发现

1. **没有万能策略**：几乎一半的测试样本无法被任何单一策略优化，策略效果高度依赖内容上下文
2. **策略需要进化**：静态的策略库不够，需要持续进化机制

### 论文的 9 个种子策略

| 策略 | 说明 |
|------|------|
| Keyword Stuffing | 注入查询关键词提高词频 |
| Unique Words | 插入稀有词汇提高信息熵 |
| Easy-To-Understand | 简化句子结构提高可读性 |
| Authoritative | 采用权威、专业的专家语调 |
| Technical Words | 注入领域专业术语 |
| Fluency Optimization | 润色语法但不增加信息 |
| Cite Sources | 注入权威来源引用 |
| Quotation Addition | 嵌入相关实体的直接引用 |
| Statistics Addition | 用数据充实文本 |

### 策略基因型（5 维度）

| 维度 | 控制什么 |
|------|---------|
| Instruction | 目标和范围 |
| Constraints | 严格边界 |
| Reasoning | 逻辑步骤 |
| Format | 输出格式 |
| Tone | 写作风格 |

### MAP-Elites Archive 机制

- 质量-多样性档案库，维护 25-35 个策略的多维网格
- 12 个描述维度定义网格（策略类型、输出格式、语调、约束强度等）
- 准入门控：新颖性门控（n-gram Jaccard < 0.9）+ 价值门控（必须优于现有最差策略）
- PND 评分用于全局维护：`S_PND = impression_score + 0.3 * (Novelty + Diversity)`

### 与 AnswerX 的对接方案

| 论文概念 | AnswerX 对应 |
|---------|-------------|
| MAP-Elites Archive | Layer 3 策略库 |
| 策略基因型 5 维度 | 策略结构的 5 维度（Instruction/Format/Tone/Constraints + Enhancement Rules） |
| 9 个种子策略 | 初始策略模板 |
| 策略进化 | 远期目标：基于内容生成效果反馈，自动进化策略 |

对接不影响 Layer 1（Metrics）和 Layer 2（Sub-goals），只作用于 Layer 3。这是三层架构的设计优势：上层稳定，底层可独立进化。

---

## 11. 附录：术语表

| 术语 | 定义 |
|------|------|
| **Metrics（成功指标）** | 三层框架的第一层，4 大衡量体系：可读性、可做答案性、可信赖性、时效性 |
| **Sub-goals（子目标）** | 三层框架的第二层，每个 Metric 下的细分目标，共 9 个 |
| **Strategy（策略）** | 三层框架的第三层，实现 Sub-goals 的具体执行方法 |
| **Topic** | 品类方向。用户管理的品牌议题，如「Smart Home」「扫地机器人」 |
| **选题** | 内容角度/机会。Topic 下具体的内容切入点，如「宠物家庭扫地机器人选购指南」 |
| **四象限** | Topic 的诊断标签：强势 / 薄弱 / 待挖掘 / 新兴 |
| **AI 平台** | AI 搜索引擎：ChatGPT、Gemini、AI Mode |
| **发布平台** | 内容发布渠道：官网、Reddit、Wiki、测评站、YouTube 等 |
| **content_opportunities** | 选题机会挖掘的结构化输出，包含切入角度、机会评分、关联 Prompts |
| **Brand Profile** | 品牌画像，包含品牌名、调性、目标受众、核心信息、品牌价值观 |
| **RAFT** | 现有方法论（Readability, Answerability, Trustworthiness, Timeliness），已演进为三层框架 |
| **MAP-Elites** | 论文的策略进化机制，质量-多样性档案库 |
| **Content Brief** | 内容大纲，比选题挖掘更详细但不是完整文章，适合交给人工团队执行 |

---

*本文档基于 2026-04-06 lancelot Chen × Claude 的设计讨论整理。所有设计决策均经讨论确认。待 Wentao 评审后进入实现规划阶段。*
