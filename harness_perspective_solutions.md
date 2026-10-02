# Harness Perspective: 广告行业 Agent Solutions

---

## 1. 什么是 Harness

"Harness" 直译是"线束"或"马具"。在软件工程中，它指的是一个包裹层，把一个核心引擎的输入输出接管过来，做统一的预处理、事件翻译、错误兜底和后处理。

最常见的用法是 "test harness"（测试线束）—— 测试代码不直接调 `main()`，而是通过一个 harness 来注入输入、捕获输出、判断结果。Harness 不是被测对象本身，而是围绕它的控制结构。

在 Agent 语境下：

```
Agent = LLM（大脑） + Harness（身体）
```

LLM 只做一件事：接收文本，生成文本。它不知道数据库长什么样，不知道前端需要什么格式，不知道哪个用户在问问题。它是一个很聪明但没有手脚的大脑。

Harness 是除 LLM 之外的一切 —— 让 LLM 能查数据、画图表、调 API、记住上下文、跟前端通信、遵守安全规则。没有 LLM，Harness 就是一堆管道，不知道该做什么决策；没有 Harness，LLM 就是一个只能聊天的文本框，做不了任何实际操作。两者合在一起才是一个 Agent。

---

## 2. Harness 的两大组成：基础设施 vs 方法论

Harness 不是铁板一块。它包含两个本质不同的部分：

### 2.1 基础设施层（通用，可跨行业复用）

| 组件 | 说明 |
|------|------|
| 流式传输（SSE） | 把 Agent 内部事件翻译为前端可消费的流式协议，实现打字机效果、图表推送、交互表单 |
| 持久化 | 消息存 DB、会话管理、历史记录 |
| 安全边界 | 限流（RPM / 每日 token 配额）、多租户隔离、权限控制 |
| 上下文管理 | 记忆加载、上下文压缩、会话摘要 |
| 后处理 | 标题生成、token 计量、审计日志 |

这些组件换到任何行业的 Agent 产品里都基本适用。

### 2.2 方法论层（业务特定，体现 Domain Know-how）

方法论层是 Domain Agent 区别于 Generic Agent 的核心。它分布在五个维度：

| 维度 | 含义 | 示例 |
|------|------|------|
| **图结构** | 做事的顺序 | "先检测异常，再分析原因，再给建议"是一个不可打乱的流程 |
| **工具编排** | 做事的能力 | 为特定场景配备特定工具，而非把所有工具都塞给 LLM |
| **Prompt 约束** | 做事的标准 | "所有百分比变化必须标注绝对值"是行业质量标准 |
| **State Schema** | 做事的中间产物 | 定义一次分析需要经过哪些中间态（异常列表、归因结果、机会评分） |
| **数据边界** | 做事的范围 | "只能访问当前广告主的数据"是安全约束，也是业务边界 |

```
Domain Harness 的方法论 =
    图结构（做事的顺序）
  + 工具编排（做事的能力）
  + Prompt 约束（做事的标准）
  + State Schema（做事的中间产物）
  + 数据边界（做事的范围）
```

---

## 3. Domain Agent vs Generic Agent：两种产品设计模式

这里讨论的 Agent Product 不是 AutoGPT、OpenAI Operator 那种通用的、业务无关的产品，而是面向具体行业的业务 Agent。

### 3.1 核心区别：谁掌握方法论

```
Domain Agent:  Harness 编码了方法论 → LLM 在方法论框架内决策
Generic Agent: Harness 提供能力目录 → LLM 自己决定方法论
```

关键区别不在工具多少，在于谁掌握方法论。

| 维度 | Domain Agent | Generic Agent |
|------|-------------|--------------|
| 方法论载体 | Harness（图结构 + 工具 + Prompt + State + 边界） | LLM（Prompt + ReAct 推理） |
| 质量上限 | 高，路径经过验证 | 取决于 LLM 能力 |
| 质量下限 | 也高，不会走歪 | 低，LLM 可能乱调工具 |
| 扩展新领域 | 要写新的子图和工具链 | 加工具就行 |
| Token 消耗 | 低，LLM 只在关键节点决策 | 高，每步都要推理下一步 |
| 可预测性 | 强，流程固定 | 弱，每次可能不同路径 |

### 3.2 Generic Agent 的方法论问题

**能不能也用 Harness 体现方法论？**

能，但会遇到一个根本性矛盾。一旦你在 Harness 里固化了流程，它就不再 Generic 了。比如给一个"通用数字员工"写了一个子图 `收集需求 → 查数据 → 生成报告`，对分析类任务好用，但用户说"帮我写一封邮件"时就不适用了。

Generic Agent 能定义的是**元方法论** —— 不是"怎么做分析"，而是"怎么决定怎么做任何事"。这就是 ReAct、Plan-and-Execute、Reflexion 这些框架在做的事。

**能不能定义确定性的方法论？**

可以定义**结构层面**的确定性，但不能定义**语义层面**的确定性：

- 结构确定性（可以写进 Generic Harness）：
  - "所有任务必须先 plan 再 execute 再 review"（Plan-and-Execute 架构）
  - "每次 tool call 之后必须 reflect 结果是否符合预期"（Reflexion）
  - "超过 3 次 tool call 失败就停下来问用户"（兜底策略）

- 语义确定性（只有 Domain Agent 能做）：
  - "做广告数据分析必须先检测异常再分析原因"
  - "所有素材必须经过合规审查才能发布"
  - "预算变更必须经过影响模拟才能执行"

结构确定性约束的是"做事的节奏"，语义确定性约束的是"做什么事"。

**Generic Agent 的精髓是什么？**

主流理解是 "Tools 多 + ReAct 探索"，但更准确的说法是 **LLM 的 few-shot 迁移能力**。

假设给 Generic Agent 100 个 tools，用户问"帮我分析上周各广告组的 ROAS 变化"。LLM 需要自己想出来：先用 `list_metrics` 看有哪些指标，再用 `query_data` 拉数据，然后用 `chart_generator` 画图，最后总结洞察。

这个能力不来自 tools 的数量，来自 LLM 在预训练中见过类似的分析流程，能 few-shot 迁移到新场景。Tools 只是手段，LLM 的推理才是引擎。

**Generic Agent 的真正赌注是：LLM 够聪明，聪明到不需要人类在 Harness 里编码方法论。**

---

## 4. 场景一：广告素材生成 Agent

### 4.1 业务背景

广告投放团队需要为不同渠道（Meta、Google、TikTok）、不同受众、不同商品批量生成广告素材（文案 + 图片描述 + CTA）。传统做法是人工写、人工审、人工适配多尺寸多语言，效率瓶颈明显。

### 4.2 为什么选 Domain Agent

一条生成出来的广告文案如果违反了广告法或平台政策，轻则下架、重则封户。这个错误成本决定了不能让 LLM 自由发挥 —— 必须在 Harness 里编码"合规审查"这个强制步骤。

### 4.3 Harness 方法论设计

#### 图结构 —— 做事的顺序

```
brief_parser → audience_profiler → copy_generator → compliance_checker → variant_expander → human_review
```

这条链编码了广告素材生成的行业方法论：

1. **brief_parser**：解析投放 brief（商品、卖点、预算、渠道）
2. **audience_profiler**：根据受众标签生成 persona 画像，决定语言风格
3. **copy_generator**：LLM 生成主文案、标题、描述、CTA
4. **compliance_checker**：审查广告法规合规（如医疗声称、对比广告限制、平台政策）
5. **variant_expander**：自动扩展为多尺寸、多语言、多渠道适配版本
6. **human_review**：HITL 审核，人工确认或修改后才能进入投放系统

如果换成 Generic Agent 做同样的事，LLM 需要在每一步自己决定"下一步该干什么"。它可能跳过合规审查直接生成，或者在没有受众画像的情况下就开始写文案。图结构消除了这种不确定性。

#### 一次请求的完整流程：LLM vs Harness

用户说："帮我给这款扫地机器人生成一组 Meta 投放的广告文案，目标受众是北美年轻家庭。"

| 步骤 | 执行者 | 具体操作 |
|------|--------|----------|
| 1 | **Harness** | 检查 rate limit、创建会话、存用户消息 |
| 2 | **Harness** | brief_parser 提取结构化信息：产品=扫地机器人、渠道=Meta、受众=北美年轻家庭 |
| 3 | **LLM** | audience_profiler 生成 persona 画像（25-35 岁、双职工、重视清洁效率） |
| 4 | **Harness** | brand_asset_loader 加载品牌素材库（Logo、配色、品牌声音指南） |
| 5 | **Harness** | platform_spec_tool 查 Meta 规格（主文案 125 字符、标题 40 字符、图片 1080x1080） |
| 6 | **LLM** | copy_generator 生成 5 组文案变体 |
| 7 | **Harness** | compliance_checker 审查合规（标记"最强吸力"为绝对化用语） |
| 8 | **LLM** | 根据合规反馈修正文案 |
| 9 | **Harness** | variant_expander 生成多尺寸适配版本 |
| 10 | **Harness** | 推送给人工审核、存 DB、计量 token |

**10 步里，LLM 参与了 3 步，Harness 做了 7 步。**

#### 工具编排 —— 做事的能力

| 工具 | 职责 | 为什么不能省 |
|------|------|-------------|
| `brand_asset_loader` | 加载品牌素材库（Logo、配色、字体规范） | 素材必须 on-brand |
| `platform_spec_tool` | 查询各渠道的文案长度限制、图片尺寸要求 | Meta 标题 40 字符，Google RSA 30 字符 |
| `compliance_rule_engine` | 检查行业法规和平台政策 | 医疗广告不能说"治愈"，FB 禁止 before/after 图 |
| `translation_tool` | 多语言翻译 + 本地化适配 | "促销"在日本市场要用"セール"而不是直译 |
| `ab_test_scorer` | 基于历史数据预估文案点击率 | 从过往 A/B 测试数据中学习什么表达更有效 |

每个工具的存在都对应一个领域判断。`compliance_rule_engine` 的存在说明"合规不能靠 LLM 自由发挥"；`platform_spec_tool` 的存在说明"渠道规格不能靠 LLM 记忆"。

#### Prompt 约束 —— 做事的标准

```
你是一个资深广告文案，遵循以下原则：
- 每条文案必须包含一个明确的 CTA（Call to Action）
- 避免使用绝对化用语（"最好"、"第一"、"唯一"）
- 针对不同受众调整语气：Z 世代用口语化，商务人群用专业术语
- 所有数字声称必须有数据来源标注
- 标题优先使用疑问句或数字（"3 个理由让你告别手动清洁"优于"我们的扫地机很好用"）
```

这些 Prompt 约束编码了"什么算好的广告文案"的行业标准。这不是 LLM 从预训练中能可靠学到的 —— 它可能写出文学性很高但转化率很低的文案。

#### State Schema —— 做事的中间产物

```python
class CreativeState(TypedDict):
    brief: dict                # 解析后的投放 brief
    audience_persona: dict     # 受众画像
    brand_guidelines: dict     # 品牌规范
    platform_specs: dict       # 渠道规格限制
    draft_copies: list[dict]   # LLM 生成的初稿
    compliance_issues: list    # 合规检查结果
    final_variants: list[dict] # 最终多版本素材
    review_status: str         # HITL 审核状态
```

每个字段都是方法论的体现。`compliance_issues` 作为独立中间产物存在，意味着"合规检查是一个必须显式执行的步骤，不能跳过"。`platform_specs` 的存在意味着"渠道规格必须在生成之前查询，不能事后裁剪"。

Generic Agent 的 state 通常只有 `messages` 和 `tool_results`，没有这些领域中间态。

#### 数据边界 —— 做事的范围

- 只能访问当前广告主的素材库和历史数据
- 不能跨账户引用其他品牌的文案（竞品参考只能用公开数据）
- 合规规则按市场区分：中国大陆适用《广告法》，海外适用各平台 Advertising Policies
- 品牌素材库的访问权限按团队角色控制

---

## 5. 场景二：广告数据洞察 Agent（Agentic Reporting）

### 5.1 业务背景

广告优化师每天面对大量投放数据（花费、展示、点击、转化、ROAS），需要从中发现：
- **Insights**：什么在涨、什么在跌、异常波动的原因
- **Opportunities**：哪些广告组有提升空间、预算应该怎么重新分配
- **Actions**：基于洞察给出具体的操作建议（调价、扩量、暂停）

### 5.2 为什么选 Domain Agent

广告数据分析有两个特征决定了它需要 Domain Agent：

1. **异常检测是确定性计算**，不需要也不应该让 LLM 做。Z-score 计算、环比变化率、统计显著性检验 —— 这些是纯数学，LLM 做数学不可靠。
2. **错误洞察的成本高** —— 如果 Agent 说"广告组 A 的 ROAS 在涨"但实际在跌，优化师可能据此增加预算，直接烧钱。

### 5.3 Harness 方法论设计

#### 图结构 —— 做事的顺序

```
data_ingestion → anomaly_detection → root_cause_analysis → opportunity_scoring → action_recommendation → human_approval
```

这条链编码了广告优化的核心方法论：先检测异常，再分析原因，再量化机会，最后给建议。顺序不能乱 —— 如果先给建议再分析原因，建议就没有数据支撑。

两个关键节点值得注意：

1. **anomaly_detection**：不是等用户问"什么在跌"，而是主动扫描所有指标的异常波动。这是一个确定性的统计计算步骤（Z-score、环比变化率），不需要 LLM 参与。
2. **opportunity_scoring**：用规则引擎（不是 LLM）对每个广告组打分，评估"如果多给 20% 预算，预期 ROAS 变化"。

这是 Domain Agent 的一个重要特征：**不是所有节点都需要 LLM**。方法论中有些步骤是纯计算、纯规则的，把它们放在 Harness 里比让 LLM 做数学更可靠。

#### 一次请求的完整流程：LLM vs Harness

用户问："帮我看看上周各广告组的表现，有没有异常？"

| 步骤 | 执行者 | 具体操作 |
|------|--------|----------|
| 1 | **Harness** | 检查 rate limit、创建会话、存用户消息 |
| 2 | **Harness** | data_ingestion：从 Meta/Google Ads API 拉取上周数据 |
| 3 | **Harness** | anomaly_detection：Z-score 统计检测，发现 3 个广告组异常 |
| 4 | **LLM** | root_cause_analysis：分析异常原因（"广告组 B 的 CPC 上涨 35%，可能因为竞品加大投放"） |
| 5 | **Harness** | opportunity_scoring：边际递减模型计算预算重分配方案 |
| 6 | **LLM** | action_recommendation：生成建议（"广告组 A 增加 ¥2000/天，广告组 C 暂停"） |
| 7 | **Harness** | 可视化：生成趋势图 + 异常标注图 |
| 8 | **Harness** | 推送给用户审核、存 DB、计量 token |

**8 步里，LLM 参与了 2 步，Harness 做了 6 步。** 而且最关键的异常检测和机会评分都是 Harness 做的，不依赖 LLM 的推理。

#### 工具编排 —— 做事的能力

| 工具 | 职责 | Domain 特性 |
|------|------|------------|
| `metrics_aggregator` | 按维度（日期、渠道、广告组）聚合投放数据 | 知道 CPC = Cost / Clicks，ROAS = Revenue / Cost |
| `anomaly_detector` | 统计异常检测（Z-score、环比、同比） | 知道周末流量波动不算异常 |
| `attribution_tool` | 多触点归因模型查询 | 知道 7-day click attribution vs 1-day view |
| `budget_simulator` | 预算变动影响模拟（边际递减模型） | 知道广告花费和回报不是线性关系 |
| `platform_api_tool` | 读取 Meta/Google Ads API 的实时数据 | 知道各平台的指标定义差异（如 Google 的 conversions 包含 view-through） |
| `benchmark_tool` | 行业基准对标 | 知道 SaaS 的 CPC 基准和电商的完全不同 |

注意 `anomaly_detector` 和 `budget_simulator` 是**确定性工具**，不调 LLM。方法论中有些步骤是纯计算、纯规则的，Harness 做比 LLM 做更可靠。

#### Prompt 约束 —— 做事的标准

```
你是一个资深广告优化师，分析投放数据时遵循以下原则：
- 先说结论，再给数据支撑（"ROAS 下降 15%，主要原因是..."）
- 所有百分比变化必须标注绝对值（"CTR 下降 20%，从 2.5% 降至 2.0%"）
- 区分"统计显著"和"随机波动"（样本量 < 100 的变化标注"数据量不足"）
- 建议必须可执行（不说"优化素材"，说"广告组 A 的标题建议从 X 改为 Y"）
- 预算建议必须给出预期影响（"增加 ¥2000/天 预计多获得 50 个转化"）
```

这些约束编码了广告分析的专业标准，是资深优化师多年经验的提炼。LLM 预训练中见过无数分析报告，但大多是模糊的"建议优化"、"可以提升"。Prompt 约束强制它产出可执行的、有数据支撑的结论。

#### State Schema —— 做事的中间产物

```python
class ReportingState(TypedDict):
    raw_metrics: list[dict]         # 原始投放数据
    anomalies: list[dict]           # 检测到的异常列表
    root_causes: list[dict]         # 归因分析结果
    opportunities: list[dict]       # 评分后的机会列表
    recommendations: list[dict]     # 带预期影响的操作建议
    confidence_scores: dict         # 各结论的置信度
```

`confidence_scores` 的存在是方法论的体现 —— 数据分析必须标注置信度，不能让 LLM 用"可能"、"大概"这种模糊措辞。当样本量不足或数据时间跨度太短时，置信度应该明确标注为"低"。

#### 数据边界 —— 做事的范围

- 只能访问当前广告主授权的广告账户数据
- 跨账户聚合分析需要显式授权
- 归因数据按平台的归因窗口返回，不做跨平台归因混算
- 竞品数据只能用公开的 Auction Insights，不能交叉泄露客户数据

---

## 6. 场景三：广告账户优化 Agent

### 6.1 业务背景

从"洞察"到"行动"的闭环。不只是告诉优化师"应该怎么做"，而是帮他执行：调整出价、暂停低效广告、重新分配预算、创建新的广告组。这是所有广告 Agent 场景中风险最高的 —— 错误的操作会直接烧钱。

### 6.2 为什么选 Domain Agent

这个场景的错误成本极高。如果 LLM 在某次 ReAct 推理中跳过了风险评估直接调 API 把出价翻倍，后果不堪设想。方法论中的 HITL（Human-in-the-Loop）必须是图结构的一部分，而不是 LLM 自行决定要不要做的可选步骤。

### 6.3 Harness 方法论设计

#### 图结构 —— 做事的顺序

```
change_proposal → impact_simulation → risk_assessment → human_approval → execution → verification
```

这条链编码了一个关键方法论：**任何账户变更都必须经过模拟和审核才能执行**。

1. **change_proposal**：LLM 基于洞察生成变更方案（如"广告组 A 出价从 ¥3.5 调至 ¥4.2"）
2. **impact_simulation**：确定性工具，用历史数据模拟变更影响（"预计 CPA 下降 8%，日花费增加 ¥500"）
3. **risk_assessment**：评估变更风险（"当前日预算已用 85%，加价可能导致超预算"）
4. **human_approval**：HITL 审核，展示变更方案 + 模拟结果 + 风险提示
5. **execution**：调用平台 API 执行变更
6. **verification**：执行后监控，确认实际效果与模拟预期一致

HITL（Human-in-the-Loop）是图结构的一部分，不是可选的。在高风险场景下，"人工审核"不是锦上添花，而是方法论的核心环节。这是 Harness 编码方法论最重要的体现之一 —— 通过图结构强制流程经过人工审核节点，LLM 无法绕过。

#### 工具编排 —— 做事的能力

| 工具 | 职责 | 为什么必须在 Harness 里 |
|------|------|----------------------|
| `change_validator` | 校验变更参数是否在安全范围内 | 出价不能超过历史最高值的 2 倍 |
| `impact_simulator` | 基于历史数据模拟变更影响 | 确定性计算，不能让 LLM 估算 |
| `risk_scorer` | 评估变更风险等级（低/中/高/极高） | 极高风险自动阻断，不进入人工审核 |
| `platform_api_executor` | 调用 Meta/Google Ads API 执行变更 | 加 dry-run 模式和回滚能力 |
| `post_change_monitor` | 执行后 1h/6h/24h 自动检查效果 | 发现偏差自动告警并建议回滚 |
| `audit_logger` | 写审计日志（谁、何时、改了什么、审批人） | 合规和问责要求 |

#### State Schema —— 做事的中间产物

```python
class OptimizationState(TypedDict):
    proposed_changes: list[dict]    # 变更方案列表
    simulation_results: list[dict]  # 模拟影响结果
    risk_level: str                 # 风险等级
    approval_status: str            # 审批状态
    execution_results: list[dict]   # API 执行结果
    verification_checks: list[dict] # 执行后监控数据
    rollback_available: bool        # 是否可回滚
```

`risk_level` 和 `approval_status` 作为显式 state 字段存在，意味着流程的每一步都能被审计和回溯。

#### 数据边界 —— 做事的范围

这个场景的数据边界约束尤其严格：

- 只能操作当前广告主授权的账户
- 单次预算调整不能超过当前值的 ±30%（防止误操作）
- 批量暂停广告组时需二次确认
- 所有变更操作必须写入审计日志（谁在什么时间改了什么）
- 高风险变更（日预算 > ¥10,000 的调整）需要高级权限

这些规则写在 Harness 里，不依赖 LLM 的"判断"。

---

## 7. 并非所有场景都需要 Domain Agent

有些广告场景更适合 Generic Agent：

### 7.1 广告运营助手（偏通用）

优化师的日常杂活：查排期、看报表、导数据、发周报、回复客户邮件。

- 任务种类繁多，每种都建子图不值得
- 方法论简单，LLM 自己能搞定
- 容错率相对高（发错一封内部邮件不会烧钱）

这种场景给 LLM 一堆工具（日历、邮件、报表生成器、文档编辑器），让它 ReAct 自由发挥就好。Harness 只需要提供基础设施层（限流、持久化、安全边界），不需要编码方法论。

### 7.2 什么时候选 Domain，什么时候选 Generic

| 维度 | Domain Agent 更合适 | Generic Agent 更合适 |
|------|-------------------|---------------------|
| 错误成本 | 高（烧钱、合规风险、数据泄露） | 低（内部沟通、格式调整） |
| 方法论复杂度 | 高（多步骤、有行业标准、有确定性计算） | 低（LLM 常识就够） |
| 任务种类 | 少而深（3-5 种核心流程） | 多而浅（几十种日常杂活） |
| 流程可预测性要求 | 高（客户/合规要求流程一致） | 低（允许每次路径不同） |

---

## 8. 跨场景复用架构

当一个服务商同时服务素材生成、数据洞察、账户优化这三个场景时，架构应该是：

```
┌──────────────────────────────────────────────────────────┐
│                    通用 Harness 基础设施                    │
│  SSE 流式传输 · 持久化 · 多租户隔离 · 上下文管理 · 限流    │
├──────────────────────────────────────────────────────────┤
│                    通用 Supervisor 路由                     │
│           意图分类 → 路由到对应 Domain 子图                 │
├──────────┬──────────────┬──────────────┬─────────────────┤
│  素材生成  │  数据洞察     │  账户优化     │  运营助手       │
│  子图      │  子图         │  子图         │ (Generic ReAct) │
│ Domain A  │  Domain B    │  Domain C    │  Generic        │
├──────────┴──────────────┴──────────────┴─────────────────┤
│                    共享工具层                               │
│  platform_api · brand_assets · metrics · compliance       │
└──────────────────────────────────────────────────────────┘
```

关键设计原则：

1. **基础设施层 100% 复用**：不同 Domain 共享同一套 SSE harness、持久化、安全边界
2. **Supervisor 路由层 90% 复用**：只需扩展意图分类的类别
3. **Domain 子图层 0% 复用**：每个场景有自己的图结构、工具编排、Prompt 约束、State Schema
4. **工具层部分复用**：`platform_api_tool` 可以跨场景共享，但 `compliance_rule_engine` 可能需要按场景定制

核心原则：**复用 Harness 的基础设施部分，替换 Harness 的方法论部分**。

注意图中有一个 Generic 模块（运营助手）和三个 Domain 子图共存。两种模式不是非此即彼的 —— 在同一个产品中，高风险、强方法论的场景用 Domain Agent，低风险、碎片化的场景用 Generic Agent。Supervisor 层做统一路由。

---

## 9. Harness 的所有权：谁写 Harness，谁定义 Agent

### 9.1 四层选型粒度

在选择"怎么构建 Agent"之前，需要先理清市面上方案的层级关系：

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: 成品 Agent 产品                                 │
│  Gemini CLI / Claude Code / Cursor                       │
│  Harness 全部由平台方写好，你不能改核心逻辑                 │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Agent 框架（内部有抽象度光谱）                    │
│                                                          │
│  ┌─ 高抽象 ─────────────────────── 低抽象 ─┐             │
│  │  ADK          CrewAI        LangGraph   │             │
│  │  (更多内置约定)  (角色+任务)  (纯图编排)   │             │
│  └─────────────────────────────────────────┘             │
│  你写 Harness 的方法论层，框架提供不同程度的基础设施        │
├─────────────────────────────────────────────────────────┤
│  Layer 3: 工具协议                                        │
│  MCP / OpenAPI Tool Schema / Function Calling             │
│  定义 Agent 如何发现和调用工具                              │
├─────────────────────────────────────────────────────────┤
│  Layer 4: LLM API                                        │
│  Gemini API / Claude API / OpenAI API                     │
│  纯模型调用，无 Agent 逻辑                                 │
└─────────────────────────────────────────────────────────┘
```

上文的三个广告场景（素材生成、数据洞察、账户优化）如果要做成生产级 SaaS 产品，工作在 Layer 2：用 Agent 框架自建 Harness。

成品 Agent 产品（如 Gemini CLI）工作在 Layer 1：自带完整的 Harness，绑定特定 LLM，开箱即用，但 Harness 逻辑不可定制。

**成品 Agent 和 Agent 框架不是同一层的选型。** 区别就像买一辆车和买一个底盘自己组装。

### 9.2 框架层的抽象度光谱

Layer 2 不是一个点，而是一个从低抽象到高抽象的连续区间。ADK、CrewAI、LangGraph 都在这一层，但位置不同：

| 维度 | LangGraph（低抽象） | ADK（高抽象） | Gemini CLI（Layer 1 成品） |
|------|-------------------|-------------|-------------------------|
| 你写什么 | 图结构 + 节点函数 + State + 工具 + SSE + 持久化 | 图结构 + 节点函数 + State + 工具 | 只写 Prompt 和加工具 |
| 框架给你什么 | 图编排引擎，其余自己搞 | 图编排 + Session 管理 + 工具调用协议 + Artifact 管理 | 全部 Harness |
| 能定义图结构吗 | 能 | 能 | 不能 |
| 能定义 State Schema 吗 | 能 | 能 | 不能 |
| 能写代码级 Verifier 吗 | 能 | 能 | 不能 |
| 基础设施自己写多少 | 多（SSE、持久化、限流都自己写） | 少（Session、Artifact、回调都内置） | 零 |

ADK 和 LangGraph 的核心共同点是：**方法论层都由你定义**。两者都能做 Domain Agent。区别只在于你需要自己写多少基础设施代码。

从 Harness 视角看：

```
Gemini CLI:  基础设施层 ✗ 不可改    方法论层 ✗ 不可改
ADK:         基础设施层 △ 大部分内置  方法论层 ✓ 你定义
LangGraph:   基础设施层 ✓ 全部自写   方法论层 ✓ 你定义
```

以广告数据洞察 Agent 为例：如果用 LangGraph 构建，`data_ingestion → anomaly_detection → root_cause_analysis → opportunity_scoring → action_recommendation → human_approval` 这条图结构是你写的，SSE 流式传输、session 持久化也是你写的。如果换成 ADK，图结构和工具不变（那是方法论），但 session 管理、streaming、回调机制由框架内置。

**选 LangGraph 还是 ADK，本质上是在选"基础设施层自己写多少"。方法论层的工作量不会因此减少。** `anomaly_detector` 的统计算法、`compliance_rule_engine` 的规则库、`ReportingState` 的字段设计 —— 这些都是领域方法论，无论用哪个框架都要自己写。

### 9.3 Harness 所有权决定 Agent 上限

| | LangGraph 自建 | ADK 自建 | Gemini CLI (成品) |
|---|---|---|---|
| Harness 来源 | 全部自写 | 方法论自写 + 基础设施内置 | 全部由平台方写好 |
| 图编排 | 自定义图结构 | 自定义图结构 | 内置 ReAct 循环，不可控 |
| 工具 | 自定义哪些工具、怎么编排 | 自定义哪些工具、怎么编排 | 可通过 MCP 加工具，不控制调用顺序 |
| 状态管理 | 自定义 State Schema | 自定义 State Schema | 只有 messages，无领域中间态 |
| 安全边界 | 代码级强制 | 代码级强制 | Prompt 级建议 |
| 基础设施工作量 | 大 | 小 | 零 |

核心原则：**谁写 Harness 的方法论层，谁定义这个 Agent 能做什么、不能做什么。** 用成品 Agent，方法论是别人的（通用 ReAct），你只能在它划定的框架内工作；用框架自建 Agent（无论 LangGraph 还是 ADK），方法论是你写的，图结构、安全边界、流程步骤全由你决定。

以广告账户优化场景为例：你需要 `change_proposal → impact_simulation → risk_assessment → human_approval → execution → verification` 这条确定性链路。无论用 LangGraph 还是 ADK 构建，这条链路都写在自建的 Harness 里，LLM 无法绕过 `human_approval` 节点。但在成品 Agent 里，HITL 审核只能靠 prompt 说"重要操作前请确认" —— LLM 可能遵守，也可能跳过。

### 9.3 Generic Agent 的 Harness 悖论

一个关键的概念辨析：**Generic Agent 并非没有 Harness，只是 Harness 由平台方写好了。**

Gemini CLI 有自己的 Harness —— ReAct 循环、工具调用协议、上下文窗口管理、safety filter、用户确认机制。这些都是 Google 工程师写的 Harness 逻辑。用户不能改。

那如果想在 Generic Agent 的基础上加入自定义 Harness 逻辑呢？技术上可以 —— 比如写一个中间层，在输出上做后处理、加规则检查。但这里有一个悖论：

**一旦你为 Generic Agent 定义了业务相关的 Harness 逻辑，它在业务意义上就不再 Generic 了。**

比如你给 Gemini CLI 加了一层"所有广告变更必须经过 HITL 审核"的中间件 —— 这一刻，它就变成了一个 Ad Optimization Domain Agent。你给它加了"异常检测必须用统计方法而非 LLM" —— 它就变成了一个 Agentic Reporting Domain Agent。

```
Generic Agent + 自定义 Harness 逻辑 = Domain Agent（本质上）
```

所以 Domain Agent 和 Generic Agent 的区别不是"有没有 Harness"（都有），而是"谁写的 Harness，里面有没有业务方法论"：

| | Generic Agent | Domain Agent |
|---|---|---|
| 有 Harness 吗 | 有（平台方写的） | 有（你自己写的） |
| Harness 包含业务方法论吗 | 不包含 | 包含 |
| 你能修改 Harness 吗 | 不能（或受限） | 完全控制 |
| 加了业务逻辑后还是 Generic 吗 | 不是了 | 本来就不是 |

---

## 10. 流程中心 vs 大脑中心：一个被过度简化的二元对立

### 10.1 两种范式

在 AI Agent 工业界，有一个正在发生的辩论：

- **流程中心（Flow-Centric）**：以 LangGraph、Google ADK 为代表。开发者像画流程图一样定义状态机，每一步在代码预设之中。
- **大脑中心（Brain-Centric）**：以 Gemini CLI、Claude Code 为代表。假设 LLM 具备足够的推理能力，给它工具和目标，让它自主规划。

### 10.2 "可控不等于可靠"—— 这个观点是对的

一个硬编码的流程，如果某个节点的 API 返回了意料之外的格式，整个流程会直接崩溃。LLM 在 ReAct 模式下确实有"容错性" —— 它看到错误可以换个方法重试。这是连接主义相对于符号主义的真实优势。

流程的脆弱性是真实的。但解决方案不是扔掉流程。

### 10.3 这不是二选一

把"全流程"和"全大脑"对立起来是一个假命题。实际的最优解是**逐节点混合**。

以广告数据洞察 Agent 为例：

```
data_ingestion (Harness 确定性拉取数据)
  → anomaly_detection (Harness 确定性统计计算，不需要 LLM)
    → root_cause_analysis (LLM 灵活归因分析)
      → opportunity_scoring (Harness 确定性评分模型)
        → action_recommendation (LLM 灵活生成建议)
          → human_approval (Harness 强制 HITL，不可跳过)
```

LLM 在该灵活的地方灵活（归因分析、生成建议），确定性步骤在该固定的地方固定（数据拉取、异常检测、机会评分、HITL 审核）。每个节点按需选择灵活性或确定性。

强行把 Agent 拆解成死板的 Flow，确实会"阉割 LLM 的泛化能力"。但不是所有节点都应该交给 LLM —— anomaly_detection 用 Z-score 比让 LLM 做数学更可靠，human_approval 写在图结构里比靠 LLM "记住要问人"更安全。

**真正的工程成熟度，不是在两种范式之间选一个，而是逐节点判断：这个步骤需要灵活性还是确定性？**

### 10.4 Proposer-Verifier 模式：理想很好，落地要看实现

一种被提出的混合方案是 Proposer-Verifier 模式：

```
Proposer（LLM，灵活）→ Verifier（规则引擎，死板）
```

LLM 天马行空地生成方案，Verifier 检查是否越过红线。灵活性寻找上限，鲁棒性兜住下限。

这个思路是正确的。但关键问题是：**Verifier 必须是代码级的，不能是 Prompt 级的。**

Prompt 约束和代码约束有本质区别：

```
Prompt 级 Verifier:
  "请不要修改超过当前预算 30% 的出价"
  → LLM 99% 会遵守，但 1% 的 hallucination 或 jailbreak 可能绕过

代码级 Verifier:
  change_validator: if abs(new_bid - old_bid) / old_bid > 0.3: raise BlockedError()
  → 100% 不会超限，因为这个约束不经过 LLM
```

对内部工具，99% 够了。对面向客户的广告优化 Agent，1% 的失控意味着可能烧掉客户的广告预算。

以广告场景为例，各机制的 Verifier 实现对比：

| 机制 | 成品 Agent (Prompt 级) | 自建 Agent (代码级) |
|------|----------------------|-------------------|
| 预算限幅 | Prompt 说 "不要超过 30%" | `change_validator` 硬编码上限，超限直接阻断 |
| 合规审查 | Prompt 说 "注意广告法规" | `compliance_rule_engine` 逐条检查，违规标记具体条款 |
| HITL 审核 | 靠 LLM 判断"重要操作前要问用户" | 图结构中 `human_approval` 是不可跳过的节点 |
| 数据隔离 | Prompt 说 "只访问当前客户数据" | API 层自动注入 `account_id` 参数，LLM 不参与 |

**真正的 Proposer-Verifier 需要架构层的物理隔离，这恰恰需要自建 Harness 来实现。** 成品 Agent 产品的 Verifier 目前主要停留在 Prompt 级和 UI 级（执行前确认），尚未达到代码级的强制性。

### 10.5 从 Unit Test 到 Eval —— 方向对，但不是全替代

Agent 系统确实不能只靠 unit test。LLM 的输出路径无法穷举。用成功率、ROI 期望值、风险加权来评估系统是合理的工程演进。

但这不意味着确定性的部分不需要 unit test：

- `anomaly_detector` 的统计检测逻辑 → 必须 unit test，100% 通过
- `change_validator` 的限幅逻辑 → 必须 unit test，100% 通过
- `compliance_rule_engine` 的规则匹配 → 必须 unit test，100% 通过
- LLM 的文案生成质量 → 用 eval（人工评分、合规通过率）
- LLM 的归因分析质量 → 用 eval（准确率、信息完整度）

**确定性的节点用 test，非确定性的节点用 eval。不是替代关系，是分工关系。**

---

## 11. 总结：Harness 视角下的产品设计决策树

```
你的 Agent 产品要不要把方法论编码进 Harness？

├── 错误成本高吗？（烧钱、合规、数据安全）
│   ├── 是 → Domain Agent，方法论进 Harness
│   └── 否 ↓
│
├── 行业有成熟的 SOP 吗？
│   ├── 是 → Domain Agent，把 SOP 编码为图结构
│   └── 否 ↓
│
├── 任务种类少而深，还是多而浅？
│   ├── 少而深 → Domain Agent
│   └── 多而浅 → Generic Agent
│
└── 最终判断：你相信 LLM 能自己发现正确路径吗？
    ├── 是 → Generic Agent（赌 LLM 智商）
    └── 否 → Domain Agent（赌你的方法论）
```

**Domain Agent vs Generic Agent 的选择，本质上是一个关于 LLM 能力边界的判断。** 如果你相信 LLM 足够聪明，能自己发现最优路径，选 Generic Agent，把方法论交给 LLM。如果你认为 LLM 还不够可靠，或者这个领域的方法论太专业，选 Domain Agent，把方法论编码进 Harness。

两者的分界线会随着 LLM 能力的提升不断移动。今天需要在 Harness 里硬编码的方法论，明天可能 LLM 自己就能推理出来。但在那一天到来之前，对容错率低、专业性强的场景，Domain Agent 用确定性换取可靠性 —— 这是正确的 tradeoff。

而对于"怎么选"这个问题，答案往往不是非此即彼，而是在同一个系统内逐节点判断、混合使用：

- 需要灵活性的节点 → 交给 LLM（大脑中心）
- 需要确定性的节点 → 写进 Harness（流程中心）
- 需要安全保障的约束 → 必须代码级，不能 Prompt 级
