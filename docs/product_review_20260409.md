# AnswerX GEO 产品反馈与迭代计划

> 基于 2026-04-09 飞书群讨论整理 (Wentao + lancelot)
> 整理时间: 2026-04-10

---

## 一、讨论背景

Wentao 对当前 Analyze Agent 进行了全面试用，提出了多个产品层面的反馈。lancelot 逐一做了回应。双方大方向一致，部分细节待 meeting 细化。

以下分析结合了代码实现和设计决策的历史背景。

---

## 二、逐项反馈深度分析

### 2.1 Success Metrics（RAFT）不应出现在分析阶段

**Wentao 的反馈:**
> "优化的 success metrics（可读性、可作答案性、可信赖性、时效性）是针对 action 而言的。在分析阶段不应该引入这个优化维度。"

**lancelot 的回应:**
> "content success metric 我在 analysis 里面是故意放的，我晚点给你解释为什么"

**代码现状:**
RAFT 四维指标定义在 `geo_optimization_metrics` 表（migration 023），包含 Readability / Answerability / Trustworthiness / Freshness 四项，下挂 9 个 sub-goals（`geo_optimization_subgoals`）。

这些指标在 Analyze Agent 中出现的位置是 **Mode C（全面分析任务）的 Node 2 "优化维度选择"**（`analyze.py` 的 slot-filling 第 2 步）。同时在 `opportunity_pipeline.py` Step 2 中，每个内容机会都会带 `recommended_metrics` 和 `recommended_subgoals`。

**设计背景:**
lancelot 当初把 RAFT 放进分析流程，是因为 Opportunity Pipeline 的设计逻辑是"分析完现状 → 直接给出优化方向"，即分析和行动建议是一体的。RAFT 指标在 Step 2（选题机会挖掘）中作为每个 content angle 的 `recommended_metrics` 输出，目的是让分析报告不仅告诉你"哪里弱"，还告诉你"用什么方法论去优化"。

这个设计源自 `project_action_agent_methodology.md` 中记录的 RAFT 方法论决策——四柱框架不仅是内容生成的评判标准，也被设计为贯穿分析→行动的完整链路。

**我的分析:**
双方都有道理，但适用场景不同：

- **Wentao 的视角（用户/客户侧）是对的**: 客户进入"分析"入口时，心智是"我的 GEO 表现怎么样？"——他期望看到 Visibility / Citation / Sentiment 这些"结果指标"。RAFT 维度（可读性/可做答案性）是"过程指标"，属于"怎么优化"而非"表现如何"。混在一起会让报告看起来不聚焦。
- **lancelot 的设计（系统侧）也是合理的**: Opportunity Pipeline 是"分析+推荐"一体化的，分析完象限定位后立刻推荐优化方向，RAFT 作为推荐依据是自然的。

**建议方案:**
不需要删除 RAFT，而是做**层级分离**：
1. 分析报告的**主体**聚焦 Visibility / Citation / Sentiment（"结果指标"）
2. RAFT 指标下沉到 Opportunity 报告中的**行动建议**部分（"这个弱点建议用什么方法优化"）
3. Mode C 的 Node 2 slot-filling 中，把 RAFT 维度从"分析维度选择"移到"优化建议偏好"或直接隐藏（由系统自动决定）

这样客户感知到的是"诊断 → 发现 → 建议"的清晰链路，RAFT 不消失但不再让用户困惑。

---

### 2.2 分析模板定位不清晰

**Wentao 的反馈:**
> "5 种分析模板定位不清晰（自定义分析、竞品对标、趋势诊断、全面检查、情感分析）。这 5 个不是一个维度的，尤其是趋势诊断 vs 全面检查。"
> "可以先 start from 一个模版，就叫'全面诊断分析'。"

**lancelot 的回应:**
> "不用特别在意，去 admin 后台里把不需要的模版点 inactive 就行了"
> "模版的多与少、是什么，可以灵活调整"

**代码现状:**
实际代码中是 **4 个结构化模板**（不是 5 个），定义在 `geo_workflow_config` 表（migration 016）：

| Key | 中文名 | 推荐 domains | 定位 |
|-----|--------|-------------|------|
| `benchmark` | 竞品对标 | visibility, citation | 品牌 vs 竞品对比 |
| `trend` | 趋势诊断 | visibility, citation, sentiment | 时间维度趋势变化 |
| `health` | 全面健康检查 | visibility, citation, sentiment | 全维度扫描 |
| `sentiment` | 情感分析 | sentiment | 专注情感维度 |

第 5 个"自定义分析"应该是 **Mode A（Direct Query / NL2SQL）**，即用户直接提问，不走模板。

另外这些模板是 **admin 可配置的**（通过 `geo_admin/src/routers/content_framework.py`），可以设 `is_active=false` 来隐藏。

**设计背景:**
这 4 个模板是参考 Profound 的 Weekly Health Workflow 设计的，最初 Wentao 觉得 Profound 的流程太复杂要简化，所以从 Profound 的更多步骤简化到了当前的 6 步 slot-filling。模板的目的是在 Analyze & Insight 入口帮用户做"预选"——把 Node 3（数据域选择）的信息提前通过模板卡片透出。

**我的分析:**
Wentao 说的"趋势诊断 vs 全面检查区分不清"确实是问题：
- `trend` 推荐的 domains = visibility + citation + sentiment
- `health` 推荐的 domains = visibility + citation + sentiment
- 两者推荐域完全相同，唯一区别是语义定位（"趋势"侧重时间变化 vs "全面"侧重覆盖面），但这个区别在最终执行时并没有落地到不同的 pipeline 逻辑——都是同一个分析流程，只是 prompt 中的 goal 描述不同。

**建议方案:**
1. 短期（admin 操作即可）：保留 **2 个模板** —— "全面诊断分析"（合并 trend + health）+ "竞品对标"。情感分析作为全面诊断的子维度而非独立模板
2. 中期：如果要增加模板，应该确保每个模板对应**不同的执行逻辑或输出结构**，而不仅仅是 prompt 描述不同

---

### 2.3 报告质量不可信

**Wentao 的反馈:**
> "Agent 产出的报告有很多错误：Roborock 在行业里表现很好，是行业领先 #1，但是报告里 Agent 认为 roborock 不好；分析行动建议时提到'知乎'，认为'perplexity/bing'属于 AI mode。"

**代码现状:**
报告生成有三个环节可能产生错误：

1. **Synthesizer prompt**（`analyze.py` 的 `_build_synthesizer_prompt()`）：注入了 brand_profile，但 brand_profile 中可能缺少**行业定位信息**（如"Roborock 是扫地机器人品类全球市场份额第一"）
2. **NL2SQL 查询结果**：数据层面可能是准确的（Roborock visibility 确实最高），但 LLM 在解读时缺乏"行业基准"上下文
3. **Opportunity Pipeline Step 4 的 synthesizer**：LLM 自由发挥 insights，缺少事实约束

关于"知乎"和"perplexity/bing 属于 AI mode"：
- 数据采集的 AI 平台定义在 `geo_client_prompts.platform` 字段，值包括 chatgpt / gemini / aimode
- LLM 可能在生成建议时引入了自己的训练知识（知乎、perplexity），而非基于实际数据
- 这是典型的 **hallucination 问题** — agent 在给建议时脱离了数据约束

**设计背景:**
当前的 brand_profile（`geo_brand_profiles` 表）存储了 brand_name / tone_of_voice / target_audience / key_messages / brand_values，但**没有**存储行业定位、市场份额、竞争排名等事实性信息。这些信息对 LLM 正确解读数据至关重要——如果 LLM 不知道 Roborock 是 #1，看到 30% 的 visibility score 可能会说"表现一般"，但实际上这已经是行业最高了。

**我的分析:**
这是**最高优先级的问题**。报告的事实性错误是信任杀手——客户看到一次错误就会质疑整个产品的价值。

根因有三层：
1. **Brand Profile 信息不全**: 缺少行业定位、市场份额、竞品格局等 context
2. **Synthesizer prompt 缺少事实约束**: 没有明确告诉 LLM "只基于查询结果数据作答，不要引入外部知识"
3. **缺少 platform 定义注入**: LLM 不知道我们系统中的"AI platforms"特指 chatgpt / gemini / aimode，可能会混入 perplexity / bing

**建议方案:**
1. **扩展 brand_profile**: 增加 `industry_position`（行业定位）、`market_context`（市场背景）字段，或在现有 key_messages 中补充
2. **Synthesizer prompt 加约束**: 添加 "你只能基于以下查询结果进行分析，不得引入外部知识或提及数据中未出现的平台/渠道" 类约束
3. **平台白名单注入**: 在分析 prompt 中明确 "本系统监测的 AI 平台包括且仅包括：ChatGPT、Gemini、AiMode"
4. **数据驱动结论**: 在 synthesizer prompt 中要求 LLM 在每个结论后附上支撑数据（如 "Visibility Score: 35%，高于第二名 Dyson 的 18%"）

---

### 2.4 GEO 评判指标应聚焦三个核心

**Wentao 的反馈:**
> "评判 GEO 表现的标准应该是：Visibility Score, Citation Score, Sentiment Score"
> "Agent 在分析的时候应该就看这些 score，进行分析趋势、分析变化、分析现状。然后再按照这 3 个 score 去 deep dive"
> "现有指标太多了，中间有 overlap，要精简，很多维度不重要（如 pill_coverage），每个的定义要清晰"

**代码现状:**
分析系统实际涉及的指标分布在多个层面：

**NL2SQL 可查询的指标**（取决于 `geo_company_mentions` / `geo_citations` / `geo_sentiment_results` 等表的列）：
- Visibility: mention_position, is_own_brand, company_name 等
- Citation: source_url, source_domain, domain_category, source_position 等
- Sentiment: sentiment (Positive/Negative), confidence 等

**Opportunity Pipeline 的象限指标**（`opportunity_pipeline.py` Step 1）：
- visibility_score = own_mentions / total_prompts
- citation_rate = own_citations / total_citations
- trend_direction = recent_2w vs prior_2w

**Mode C slot-filling 中的 "data_domains"**：
- visibility / citation / sentiment — 这三个就是 Wentao 说的三个核心维度

**设计背景:**
lancelot 在回应中提到 "指标在 dash 前台不是枚举全的"——意思是有些深度指标需要在 Looker Studio 后台配置才能展示，NL2SQL agent 能查到的指标比 dashboard 展示的更多，所以 agent 生成指标有其存在理由。

**我的分析:**
Wentao 和 lancelot 说的其实不矛盾：
- Wentao 要的是"用户感知层"的简洁 — 客户只需要理解 3 个维度
- lancelot 说的是"数据能力层"的丰富 — agent 可以查到更细粒度的指标

问题不在于 agent 内部能分析多少指标，而在于**呈现给用户的报告应该以三个核心维度为骨架**。

**建议方案:**
- 报告结构固定为 **Visibility → Citation → Sentiment** 三大章节
- 每个章节下可以有 deep dive 子项（by-prompt, by-platform, by-topic），但层级关系要清晰
- Agent 内部仍然用 NL2SQL 查任何需要的指标，但 synthesizer 的输出模板要按三维度组织

---

### 2.5 Topic 定义重构

**Wentao 的反馈:**
> "Topic 定义应该不是'产品线'了，而是'话题'或者'语义群'。Roborock 的 topic 不应该是 'robot vacuum'，而应该是'话题'。"
> "Setup 时要有 AI 生成推荐话题的过程"
> "这个是 P0，因为 onboard 一个客户，一开始就要定 topic x prompt 的分布"

**代码现状:**
`geo_client_topics` 表结构：
```
id          UUID PK
client_id   UUID (FK)
topic_name  TEXT        -- 当前存的是产品线名称如 "robot vacuum"
products    TEXT[]      -- 关联产品列表
```

Topic 向下关联 `geo_client_prompts`（每个 prompt 属于一个 topic），向上影响 Opportunity Pipeline 的象限分类（以 topic 为单位做四象限定位）。

**设计背景:**
Auto-Discovery 功能（`project_auto_discovery_design.md`）已经设计了四层 fallback 方案来自动抽取 Topics/Products。当前的 topic_name 字段本身是自由文本，技术上已经支持存"话题"而非"产品线"。

**我的分析:**
这个改动技术上不大（数据模型不需要改 schema），但**语义上是重要的产品决策**：

- 对于 Roborock 这种品类单一的客户，"robot vacuum" 作为唯一 Topic 等于没有 Topic，所有 prompt 都在一个桶里，象限分析失去意义
- 如果 Topic = 话题（如 "pet hair cleaning" / "mopping vs vacuuming" / "smart home integration"），同一品牌下可以有多个有意义的分析维度
- 这直接影响 Auto-Discovery 的实现方向：从"爬产品目录"变成"分析用户搜索意图聚类"

**建议方案:**
1. `geo_client_topics` schema 不需要改，`topic_name` 字段语义从"产品线"扩展为"话题/语义群"
2. Auto-Discovery 的 LLM 提取逻辑（Layer 4）需要调整 prompt：从"提取产品分类"改为"提取品牌相关的用户关注话题"
3. 这和 lancelot 已规划的 Auto-Discovery 可以合并推进

---

### 2.6 Analyze Agent vs General Chat 的定位

**Wentao 的观点:**
> 类比 Gemini 的 Gems — 用户进入 Analyze & Insight 带有明确预设心智，期望"我要个周报"
> "核心是便捷性和确定性预期，不是灵活度"
> 步骤 3/4/5 都可以保留，4 和 5 是高级选项，90% 客户不会动

**lancelot 的回应:**
> "如果只保留节点 3，那确实不需要模板了，模板存在是为了把节点 3 的信息通过模板提前透出来"
> "Analyze and Insights 这个入口需要和 general chat 有多大差异化？"

**代码现状:**
- Analyze & Insight 入口：走 Mode B（Opportunity，3 步 slot-filling）或 Mode C（Full Analysis，6 步 slot-filling）
- General Chat 入口：经 Supervisor 路由到 analyze sub-graph，走 Mode A（Direct Query / NL2SQL）
- 两者共享同一套 data tools 和 NL2SQL 能力

**设计背景:**
lancelot 设计 Mode C 的 6 步 slot-filling，是为了让 Analyze & Insight 成为一个**结构化的、可配置的分析流程**（对标 Profound 的 Weekly Health），与 General Chat 的自由提问形成差异。模板（benchmark/trend/health/sentiment）是 Node 1（goal 选择）的前置快捷入口。

**我的分析:**
双方的理解其实一致，区分点在于**复杂度的把控**：
- Wentao 认为对客户来说步骤太多、选项太多，核心价值是"一键出报告"
- lancelot 认为灵活性是差异化价值，但也同意大部分客户不会改高级选项

**建议方案:**
- 模板卡片保留，但精简到 1-2 个
- 点击模板后，Node 1/2 的选择用模板预设值自动填充（不再让用户选）
- Node 3（数据域）保留但用 toggle 而非多步问答
- Node 4（图表配置）/ Node 5（prompt）折叠为"高级设置"，默认不展开
- 整体效果：客户选模板 → 选日期 → 确认 → 出报告（3 步完成）

---

### 2.7 指标固定配置 vs Agent 动态生成

**Wentao:**
> "Agent 不用自己再生成指标，重要指标都在 dash 上。Agent 要做的是知道这些现有指标的定义、逻辑、以及该 query 哪些 table 去 deep dive。"

**lancelot:**
> "方向一: agent 根据 context 动态给；方向二: 模板固定配置" → Wentao 倾向方向二

**代码现状:**
当前 Mode C 的 Node 2 是让 agent 基于用户选择的 goal 动态推荐 metrics。这些 metrics 从 `geo_optimization_metrics` 表读取。

**我的分析:**
结合 2.1 的结论（RAFT 不应在分析主体中），这个问题可以简化：
- 分析维度固定为 Visibility / Citation / Sentiment（不需要用户选也不需要 agent 推荐）
- 优化指标（RAFT）在行动建议部分由系统根据象限结果自动匹配（也不需要用户选）
- 最终效果：用户不需要面对任何指标选择，全部由系统预设

---

## 三、待确认项

| # | 项目 | 说明 | 建议 |
|---|------|------|------|
| 1 | lancelot 保留 RAFT 在分析中的具体理由 | 群里说"晚点解释"但未展开 | 建议层级分离而非删除 |
| 2 | 最终保留哪几个分析模板 | 约了 meeting | 建议 1-2 个，admin 后台操作即可 |
| 3 | Brand Profile 需要补充哪些行业信息 | 影响报告准确性 | 增加 industry_position 字段 |
| 4 | Topic 从"产品线"到"话题"的转变标准 | 影响 Auto-Discovery 方向 | 需定义"好的 Topic"的标准 |
| 5 | Analyze 流程简化到几步 | 影响前端改动量 | 建议 3 步（模板→日期→确认） |

---

## 四、迭代计划建议

### Phase 1: 报告可信度修复（最紧急）

- [ ] 扩展 brand_profile：补充行业定位和竞争格局信息
- [ ] Synthesizer prompt 加事实约束：只基于查询数据，不引入外部知识
- [ ] 注入平台白名单：明确系统只监测 ChatGPT / Gemini / AiMode
- [ ] 要求数据支撑：每个结论必须附上具体数据

### Phase 2: 分析流程精简

- [ ] Admin 后台：inactive 掉 trend 和 health，保留 "全面诊断"（合并）+ "竞品对标"
- [ ] RAFT 指标从分析主体移到行动建议部分
- [ ] Mode C slot-filling 简化：模板预填 → 日期 → 确认（3 步）
- [ ] 报告输出结构固定为 Visibility → Citation → Sentiment 三章节

### Phase 3: Topic 重构 + Auto-Discovery

- [ ] Topic 语义从"产品线"扩展为"话题/语义群"
- [ ] Auto-Discovery LLM prompt 调整：提取"用户关注话题"而非"产品目录"
- [ ] Setup 流程中集成 AI 推荐话题

### Phase 4: Content Generation（后续）

- [ ] 分析基础稳固后再推进
- [ ] RAFT 指标在此阶段作为内容质量评判标准正式发挥作用
