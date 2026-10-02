# Harness Perspective: GEO Agent 案例剖析

> Agent = LLM + Harness
> LLM 是大脑，Harness 是除大脑之外的一切。

本文以 AnswerX GEO Agent 为具体案例，深入探讨 Domain Agent 架构中 Harness 的角色、组成与设计哲学。

---

## 1. 什么是 Harness

"Harness" 直译是"线束"或"马具"。在软件工程中，它指的是一个包裹层，把一个核心引擎的输入输出接管过来，做统一的预处理、事件翻译、错误兜底和后处理。

最常见的用法是 "test harness"（测试线束）—— 测试代码不直接调 `main()`，而是通过一个 harness 来注入输入、捕获输出、判断结果。Harness 不是被测对象本身，而是围绕它的控制结构。

在 Agent 语境下：

```
Agent = LLM（大脑） + Harness（身体）
```

LLM 只做一件事：接收文本，生成文本。它不知道数据库长什么样，不知道前端需要什么格式，不知道哪个用户在问问题。Harness 给了 LLM 手脚，让它能查数据、画图表、记住上下文、跟前端通信、遵守安全规则。

没有 LLM，Harness 就是一堆管道，不知道该做什么决策。没有 Harness，LLM 就是一个只能聊天的文本框，做不了任何实际操作。

---

## 2. GEO Agent 中的 Harness 全景

以 GEO 项目的 `geo_agent/src/main.py` 中的 `event_stream()` 函数（约 390 行代码）为核心，Harness 的架构如下：

```
浏览器 ←→ SSE Harness ←→ LangGraph 图引擎 ←→ LLM (Gemini)
```

核心引擎是 LangGraph 的 `_graph.astream()`。它执行 Supervisor → Analyze/Action/Chat 子图，产出 LangGraph 内部格式的 `(namespace, event)` 元组。Harness 围绕这个引擎，负责四个阶段的工作：

### 2.1 Pre-graph（图执行前）

- **Rate limit 检查**：双层限流（RPM + 每日 token 配额）
- **Session 管理**：upsert 会话、持久化人类消息（保证页面刷新不丢数据）
- **意图短路检测**：如导出意图，不进图直接返回
- **上下文加载**：加载 client context、brand profile、user memories、system context

### 2.2 During graph（图执行中）

- **事件翻译**：把 LangGraph 内部的 node-level state diff 翻译成前端约定的 SSE 协议（`token`、`chart`、`widget`、`thinking`、`intent`、`task_ready`）
- **路径分发**：不同 node 的输出走不同翻译路径 —— classify 发 intent、chart_builder 发 chart、synthesizer 发 token
- **事件过滤**：只处理父图的 classify/off_topic，其余只处理子图事件

### 2.3 Post-graph（图执行后）

- **持久化**：AI 消息存 DB（含 charts、thinking steps、widgets）
- **异步标题生成**：后台调 LLM 生成 session title
- **Token 计量**：记录 input/output tokens，写入 usage 表用于配额追踪
- **Toolbar 聚合**：一次性推送 memory count、daily quota 等 UI 数据
- **上下文压缩**：评估是否需要压缩历史消息
- **记忆评估**：评估用户消息是否触发 memory/profile 更新

### 2.4 Error boundary

- 整个流程的异常兜底，确保前端总能收到一个 `error` SSE 事件而不是连接断开

### 为什么不直接把 astream() 的输出丢给前端？

因为 LangGraph 的输出格式是面向图执行的（node name + state diff），不是面向 UI 的。前端需要的是 `token`（打字机效果）、`chart`（渲染图表）、`widget`（交互表单）这些语义化事件。Harness 就是翻译层 + 控制层。

而且，很多逻辑根本不在图里 —— rate limit、session 管理、title 生成、token 计量、memory 评估。这些都是 Harness 的职责，不应该塞进 LangGraph 的 node 里。

---

## 3. 一次请求的完整流程：LLM vs Harness

用户问："Roborock 上个月在 ChatGPT 的可见度趋势"

| 步骤 | 执行者 | 具体操作 |
|------|--------|----------|
| 1 | **Harness** | 检查 rate limit、创建 session、存人类消息 |
| 2 | **Harness** | 加载 brand profile、memories、system context |
| 3 | **LLM** | Supervisor classify → 识别意图为 "analyze" |
| 4 | **Harness** | 路由到 Analyze 子图 |
| 5 | **LLM** | NL2SQL generator → 生成 SQL 查询 |
| 6 | **Harness** | 执行 SQL、拿到数据行 |
| 7 | **Harness** | chart_builder 把数据转成图表配置 |
| 8 | **LLM** | synthesizer → 生成分析文本 |
| 9 | **Harness** | 切成 6 字符 chunk，以 SSE token 事件推给前端 |
| 10 | **Harness** | 存消息、生成标题、计算 token 用量、评估记忆 |

**10 步里，LLM 参与了 3 步，Harness 做了 7 步。**

---

## 4. Harness 的两大组成：基础设施 vs 方法论

Harness 不是铁板一块。它包含两个本质不同的部分：

### 4.1 基础设施层（通用，可跨行业复用）

| 组件 | GEO 中的实现 | 说明 |
|------|-------------|------|
| SSE 流式传输 | `event_stream()` | 事件翻译、打字机效果 |
| 持久化 | `_save_message()`, `_upsert_session()` | 消息存 DB、会话管理 |
| 安全边界 | `rate_limiter.py`, `tenant.py` | 限流、多租户隔离 |
| 上下文管理 | `_compress_context()`, `load_memories()` | 记忆加载、上下文压缩 |
| 后处理 | `_generate_session_title()`, `_evaluate_memory()` | 标题生成、记忆提取 |

这些组件换到任何行业的 Agent 产品里都基本适用。

### 4.2 方法论层（业务特定，体现 Domain Know-how）

这是 Domain Agent 区别于 Generic Agent 的核心。方法论不仅仅体现在图结构和工具编排上，而是分布在五个维度：

#### (1) 图结构 —— 做事的顺序

```
intent_router → nl2sql_generator → query_executor → chart_builder → synthesizer
```

这条链本身就是方法论的编码。它表达了一个判断："做 GEO 数据分析，正确的步骤是先理解意图、再转 SQL、再查数据、再可视化、最后出洞察。" 这不是 LLM 在运行时自己发现的，而是 GEO 领域专家把 know-how 写死在图结构里。

同样，Action Agent 的 `slot-filling → RAFT 四支柱 → HITL review` 流程，编码的是"做内容优化，应该先收集参数、再按四个维度生成、再让人审核"。

#### (2) 工具编排 —— 做事的能力

Analyze Agent 配备 NL2SQL 工具、chart builder、data tools。Action Agent 配备 content generator、export tools。这些工具的选择和组合反映了"GEO 需要做哪些事"的领域判断。

#### (3) Prompt 约束 —— 做事的标准

`SYNTHESIZER_SYSTEM_TEMPLATE` 里写了 "Compare own brand vs competitors when applicable"、"Highlight actionable insights"。这不是通用的文本生成指令，而是 GEO 领域对"什么算好的分析"的质量标准定义。

#### (4) State Schema —— 做事的中间产物

`AnalyzeState` 有 `nl2sql_plan`、`query_results`、`charts`、`insights`。这些字段的存在本身就是方法论 —— 它定义了"做一次分析需要经过哪些中间产物"。Generic Agent 的 state 通常只有 `messages` 和 `tool_results`，没有领域中间态。

#### (5) 数据边界 —— 做事的范围

`@tenant_scoped` decorator、`ALLOWED_TABLES`、`SAFE_SQL_RE`。这些不只是"安全基础设施"。`ALLOWED_TABLES` 定义了"GEO 分析只应该碰哪些表"，这是领域边界的编码。一个通用 Agent 做不了这个判断。

```
Domain Harness 的方法论 =
    图结构（做事的顺序）
  + 工具编排（做事的能力）
  + Prompt 约束（做事的标准）
  + State Schema（做事的中间产物）
  + 数据边界（做事的范围）
```

---

## 5. Domain Agent vs Generic Agent：两种产品设计模式

这里讨论的 Agent Product 不是 AutoGPT、OpenAI Operator 那种通用的、业务无关的产品，而是面向具体行业的业务 Agent。

### 5.1 核心区别：谁掌握方法论

```
Domain Agent:  Harness 编码了方法论 → LLM 在方法论框架内决策
Generic Agent: Harness 提供能力目录 → LLM 自己决定方法论
```

关键区别不在工具多少，在于谁掌握方法论。

### 5.2 对比表

| 维度 | Domain Agent | Generic Agent |
|------|-------------|--------------|
| 方法论载体 | Harness（图结构 + 工具编排 + Prompt + State + 数据边界） | LLM（Prompt + ReAct 推理） |
| 质量上限 | 高，路径经过验证 | 取决于 LLM 能力 |
| 质量下限 | 也高，不会走歪 | 低，LLM 可能乱调工具 |
| 扩展新领域 | 要写新的子图和工具链 | 加工具就行 |
| Token 消耗 | 低，LLM 只在关键节点决策 | 高，每步都要推理下一步 |
| 可预测性 | 强，流程固定 | 弱，每次可能不同路径 |

### 5.3 Generic Agent 的方法论问题

**能不能也用 Harness 体现方法论？**

能，但会遇到一个根本性矛盾。一旦你在 Harness 里固化了流程，它就不再 Generic 了。比如给一个"通用数字员工"写了一个子图 `收集需求 → 查数据 → 生成报告`，对分析类任务好用，但用户说"帮我写一封邮件"时就不适用了。

Generic Agent 能定义的是**元方法论** —— 不是"怎么做分析"，而是"怎么决定怎么做任何事"。这就是 ReAct、Plan-and-Execute、Reflexion 这些框架在做的事。

**能不能定义确定性的方法论？**

可以定义**结构层面**的确定性，但不能定义**语义层面**的确定性：

- 结构确定性："所有任务必须先 plan 再 execute 再 review"（Plan-and-Execute 架构）
- 结构确定性："每次 tool call 之后必须 reflect 结果是否符合预期"（Reflexion）
- 结构确定性："超过 3 次 tool call 失败就停下来问用户"（兜底策略）

但你不能在 Generic Agent 的 Harness 里写 `query_executor → chart_builder`，因为不是每个任务都需要查 SQL 再画图。这种语义编排只有 Domain Agent 能做。

**Generic Agent 的精髓是什么？**

主流理解是 "Tools 多 + ReAct 探索"，但更准确的说法是 **LLM 的 few-shot 迁移能力**。

假设给 Generic Agent 100 个 tools，用户问"分析竞品在 AI 搜索引擎的曝光趋势"。LLM 需要自己想出来：先用 `list_tables` 看有哪些表，再用 `describe_table` 看结构，然后用 `sql_query` 查数据，最后用 `chart_generator` 画图。

这个能力不来自 tools 的数量，来自 LLM 在预训练中见过类似的分析流程，能 few-shot 迁移到新场景。Tools 只是手段，LLM 的推理才是引擎。

**Generic Agent 的真正赌注是：LLM 够聪明，聪明到不需要人类在 Harness 里编码方法论。**

### 5.4 为什么 GEO 选择 Domain Agent

1. **NL2SQL 的正确性要求高** —— 查错表、写错 SQL 会返回错误数据，用户看不出来。把 `ALLOWED_TABLES` 和 SQL 验证写进 Harness，比让 LLM 自己判断安全得多。
2. **分析的质量标准是专业的** —— "什么算好的 GEO 分析"不是 LLM 预训练能学到的。RAFT 四支柱、品牌调性注入，这些是行业 know-how。
3. **多租户隔离是零容忍的** —— 让 LLM 自己记住"每个 SQL 都要加 WHERE client_id = ..."是不可接受的风险。

---

## 6. 未来演进：分层混合

两种模式不是非此即彼。GEO 项目的架构恰好是分层混合的：

```
Supervisor（相对通用的意图路由） → Domain 子图（高度业务特定的编排）
```

如果未来要服务多个行业，合理的演进不是把 Harness 变通用，而是：

- **通用层保持不变**：SSE harness、持久化、安全边界、上下文管理、Supervisor 路由
- **Domain 层按行业替换**：不同行业有不同的子图、不同的工具链、不同的方法论编码

要复用的是 Harness 的基础设施部分，要替换的是 Harness 的方法论部分。

通用 Agent 平台的问题是它试图把方法论也变通用，结果方法论就只能交给 LLM 自己去猜了。

---

## 7. Harness 的所有权：谁写 Harness，谁定义 Agent

### 7.1 四层选型粒度

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

GEO Agent 工作在 Layer 2 的低抽象端（LangGraph）：用纯图编排能力，自己写了全部 Harness 逻辑（SSE 流式传输、持久化、多租户隔离、NL2SQL 工具链、图结构、State Schema），最终交付的是一个完整的 SaaS 产品。

像 Gemini CLI 这样的成品 Agent 产品工作在 Layer 1：它自带完整的 Harness（文件读取、命令执行、上下文管理、ReAct 工具调用循环），绑定 Gemini 模型，开箱即用。

**Gemini CLI 和 LangGraph 不是同一层的选型。** Gemini CLI 是"成品"，LangGraph 是"框架"。区别就像买一辆车和买一个底盘自己组装。

### 7.2 框架层的抽象度光谱

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

GEO 项目如果用 ADK 重写，`event_stream()` 里那 390 行 SSE harness 代码会大幅减少（ADK 内置了 streaming 和 session 管理），`_save_message()`、`_upsert_session()` 这些手写的持久化逻辑也会被框架接管。但 `analyze.py` 里的图结构、`tools/` 里的工具、`AnalyzeState` 的 State Schema 基本不变 —— 因为那些是方法论，不是基础设施。

**选 LangGraph 还是 ADK，本质上是在选"基础设施层自己写多少"。方法论层的工作量不会因此减少。**

### 7.3 Harness 所有权决定了 Agent 的上限

| | GEO Agent (LangGraph 自建) | ADK 自建 | Gemini CLI (成品) |
|---|---|---|---|
| Harness 来源 | 全部自写（~5000 行） | 方法论自写 + 基础设施内置 | 全部由 Google 写好 |
| 图编排 | 自定义图结构 | 自定义图结构 | 内置 ReAct 循环，不可控 |
| 工具 | 自定义哪些工具、怎么编排 | 自定义哪些工具、怎么编排 | 可通过 MCP 加工具，但不控制调用顺序 |
| 状态管理 | 自定义 State Schema | 自定义 State Schema | 只有 messages，无领域中间态 |
| 安全边界 | 代码级强制 | 代码级强制 | Prompt 级建议 |
| 基础设施工作量 | 大 | 小 | 零 |

核心原则：**谁写 Harness 的方法论层，谁定义这个 Agent 能做什么、不能做什么。** 用成品 Agent，方法论是别人的（通用 ReAct），你只能在它划定的框架内工作；用框架自建 Agent（无论 LangGraph 还是 ADK），方法论是你写的，图结构、安全边界、流程步骤全由你决定。

### 7.3 Generic Agent 的 Harness 悖论

一个关键的概念辨析：**Generic Agent 并非没有 Harness，只是 Harness 由平台方写好了**。

Gemini CLI 有自己的 Harness —— ReAct 循环、工具调用协议、上下文窗口管理、safety filter、用户确认机制。这些都是 Google 工程师写的 Harness 逻辑。用户不能改。

那如果想在 Generic Agent 的基础上加入自定义 Harness 逻辑呢？技术上可以 —— 比如写一个中间层，在 Gemini CLI 的输出上做后处理、加规则检查。但这里有一个悖论：

**一旦你为 Generic Agent 定义了业务相关的 Harness 逻辑，它在业务意义上就不再 Generic 了。**

比如你给 Gemini CLI 加了一层"所有 SQL 必须经过白名单检查"的中间件 —— 这一刻，它就变成了一个 Data Analysis Domain Agent。你给它加了"所有广告变更必须经过 HITL 审核"—— 它就变成了一个 Ad Optimization Domain Agent。

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

## 8. 流程中心 vs 大脑中心：一个被过度简化的二元对立

### 8.1 两种范式

在 AI Agent 工业界，有一个正在发生的辩论：

- **流程中心（Flow-Centric）**：以 LangGraph、Google ADK 为代表。开发者像画流程图一样定义状态机，每一步在代码预设之中。
- **大脑中心（Brain-Centric）**：以 Gemini CLI、Claude Code 为代表。假设 LLM 具备足够的推理能力，给它工具和目标，让它自主规划。

### 8.2 "可控不等于可靠"—— 这个观点是对的

一个硬编码的 LangGraph 流程，如果某个节点的 API 返回了意料之外的格式，整个流程会直接崩溃。LLM 在 ReAct 模式下确实有"容错性" —— 它看到错误可以换个方法重试。

在 GEO 项目里也能看到这个问题：如果 NL2SQL 生成了一条执行报错的 SQL，Harness 必须专门写错误处理逻辑让 LLM 重新生成。这个容错逻辑是手动写的，而 Generic Agent 天然就有这种弹性。

流程的脆弱性是真实的。但解决方案不是扔掉流程。

### 8.3 这不是二选一

把"全流程"和"全大脑"对立起来是一个假命题。实际的最优解是**逐节点混合**。

GEO Agent 的做法恰好体现了这一点：

```
Supervisor (LLM 灵活路由)
  → nl2sql_generator (LLM 灵活生成 SQL)
    → query_executor (确定性执行，不经过 LLM)
      → chart_builder (确定性渲染，不经过 LLM)
        → synthesizer (LLM 灵活生成洞察)
```

LLM 在该灵活的地方灵活（意图分类、SQL 生成、分析洞察），确定性步骤在该固定的地方固定（SQL 执行、图表生成、租户隔离）。没有被"阉割" —— 每个节点按需选择灵活性或确定性。

**真正的工程成熟度，不是在两种范式之间选一个，而是逐节点判断：这个步骤需要灵活性还是确定性？**

### 8.4 Proposer-Verifier 模式：理想很好，落地要看实现

一种被提出的混合方案是 Proposer-Verifier 模式：

```
Proposer（LLM，灵活）→ Verifier（规则引擎，死板）
```

LLM 天马行空地生成方案，Verifier 检查是否越过红线。灵活性寻找上限，鲁棒性兜住下限。

这个思路是正确的。但关键问题是：**Verifier 必须是代码级的，不能是 Prompt 级的。**

```
Prompt 级 Verifier:
  "请不要查其他客户的数据"
  → LLM 99% 会遵守，但 1% 的 hallucination 或 jailbreak 可能绕过

代码级 Verifier:
  WHERE client_id = $1 （@tenant_scoped 自动注入，LLM 根本不参与）
  → 100% 不会查到其他客户的数据，因为这个约束不经过 LLM
```

对内部工具，99% 够了。对多租户 SaaS，1% 的数据泄露是灾难。

GEO Agent 里的 Verifier 对比：

| 机制 | 成品 Agent (如 Gemini CLI) | GEO Agent (自建 Harness) |
|------|--------------------------|------------------------|
| 数据表白名单 | 不存在，LLM 可以查任何表 | `ALLOWED_TABLES` 写在代码里，LLM 生成的 SQL 必须过白名单 |
| 租户隔离 | 靠 prompt 说"只查当前用户数据" | `@tenant_scoped` 装饰器自动注入 `WHERE client_id = $1` |
| HITL 审核 | 靠 LLM 自己决定要不要问用户 | `human_review` 是图结构中不可跳过的节点 |
| 操作限幅 | 只能写在 prompt 里 "不要超过 20%" | `change_validator` 工具硬编码上限，超限直接阻断 |

**真正的 Proposer-Verifier 需要架构层的物理隔离，这恰恰需要自建 Harness 来实现。** 成品 Agent 产品的 Verifier 目前主要停留在 Prompt 级和 UI 级（执行前确认），尚未达到代码级的强制性。

### 8.5 从 Unit Test 到 Eval —— 方向对，但不是全替代

Agent 系统确实不能只靠 unit test。LLM 的输出路径无法穷举。用成功率、ROI 期望值、风险加权来评估系统是合理的工程演进。

但这不意味着确定性的部分不需要 unit test。在 GEO Agent 里：
- `@tenant_scoped` 的 SQL 注入逻辑 → 必须 unit test，100% 通过
- NL2SQL 生成的 SQL 质量 → 用 eval（成功率、准确率）
- synthesizer 的分析质量 → 用 eval（人工评分、信息完整度）

**确定性的节点用 test，非确定性的节点用 eval。不是替代关系，是分工关系。**

---

## 9. 本质判断

Domain Agent vs Generic Agent 的选择，本质上是一个关于 LLM 能力边界的判断：

- 如果你相信 LLM 足够聪明，能自己发现最优路径 → Generic Agent，把方法论交给 LLM
- 如果你认为 LLM 还不够可靠，或者这个领域的方法论太专业 → Domain Agent，把方法论编码进 Harness

**两者的分界线会随着 LLM 能力的提升不断移动。** 今天需要在 Harness 里硬编码的方法论，明天可能 LLM 自己就能推理出来。但在那一天到来之前，Domain Agent 用确定性换取了可靠性 —— 对 GEO 这样容错率低的场景，这是正确的 tradeoff。

而对于"怎么选"这个问题，答案往往不是非此即彼，而是在同一个系统内逐节点判断、混合使用：

- 需要灵活性的节点 → 交给 LLM（大脑中心）
- 需要确定性的节点 → 写进 Harness（流程中心）
- 需要安全保障的约束 → 必须代码级，不能 Prompt 级
