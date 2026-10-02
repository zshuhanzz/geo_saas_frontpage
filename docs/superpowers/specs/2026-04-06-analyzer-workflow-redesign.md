# Analyzer Workflow Redesign — 产品设计文档

**文档版本**：v1.0
**日期**：2026-04-06
**参与者**：lancelot Chen × Claude（AI）
**状态**：待实施

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [设计概述：双模式分析](#2-设计概述双模式分析)
3. [Mode A：优化机会发现](#3-mode-a优化机会发现)
4. [Mode B：专项分析](#4-mode-b专项分析)
5. [AgentAnalysis 页面布局](#5-agentanalysis-页面布局)
6. [文件变更清单](#6-文件变更清单)

---

## 1. 背景与动机

### 问题

当前 AgentAnalysis 页面的 "New Agent Task" tab 展示所有模板卡片在一个扁平网格中（`grid-cols-5`），没有区分分析类型。`TemplateConfigModal` 的 Step 1（分析目标）包含 "优化机会发现" 选项，但它的用途与其他分析模板完全不同：

- **优化机会发现** 是一个**行动导向**的全量诊断流程，输出结构化数据（Topic 四象限、选题机会、平台引用关系），并桥接到 Content Pipeline。
- **其他分析模板**（竞品对标、趋势诊断、情感分析、全面检查、自定义）是**理解导向**的专项分析，输出 Markdown 报告。

把两种完全不同的分析混在同一个入口造成用户困惑，且优化机会发现不应经过通用模板配置流程。

### 改造目标

1. 将分析入口拆为两个明确区域：Mode A（优化机会发现）和 Mode B（专项分析）。
2. Mode A 获得独立的专属 Modal，展示 3 步诊断方法论，无需选 Metrics/Sub-goals。
3. Mode B 的 TemplateConfigModal 增加可选的 "优化维度" 步骤（Metrics + Sub-goals），移除 "opportunity" 选项。
4. Mode A 完成后展示 CTA 按钮，将结构化数据传递给 Content Pipeline。

---

## 2. 设计概述：双模式分析

```
AgentAnalysis → New Agent Task tab
├── Mode A: 优化机会发现 (单独大卡片，置顶)
│   └── OpportunityAnalysisModal.tsx (专属 Modal)
│       ├── 展示 3 步诊断方法论（只读展示，非选择）
│       │   ① Topic 四象限定位
│       │   ② 选题机会挖掘
│       │   ③ 平台-AI引擎引用关系
│       ├── 可选配置：日期范围、平台筛选
│       └── 确认执行 → opportunity_discovery pipeline
│
├── Mode B: 专项分析 (5 个模板卡片，下方网格)
│   └── TemplateConfigModal.tsx (现有 Modal，改造)
│       ├── Step 1: 分析视角 (重命名，移除 opportunity)
│       ├── Step 2: 优化维度 (新增，可选 Metrics + Sub-goals)
│       ├── Step 3: 数据域 (原 Step 2)
│       ├── Step 4: 图表 (原 Step 3)
│       ├── Step 5: Prompt 编辑 (原 Step 4)
│       └── Step 6: 确认 (原 Step 5)
```

---

## 3. Mode A：优化机会发现

### 3.1 入口

AgentAnalysis "New Agent Task" tab 顶部，一个宽幅 CTA 卡片：

```
┌─────────────────────────────────────────────────────┐
│  🔍  优化机会发现                                      │
│  全量诊断品牌在 AI 搜索中的优化机会                        │
│  Topic定位 · 选题挖掘 · 平台引用关系 → 内容优化行动方案      │
│                                        [开始分析 →]    │
└─────────────────────────────────────────────────────┘
```

### 3.2 OpportunityAnalysisModal

一个轻量 Dialog，**不是**多步 wizard。展示诊断方法论 + 可选配置 + 确认执行。

**布局：**

```
┌─ 优化机会发现 ─────────────────────────────────────┐
│                                                    │
│  本次分析将执行以下三步诊断：                           │
│                                                    │
│  ① Topic 四象限定位                                  │
│     根据品牌内容覆盖度、AI引用模式、趋势方向             │
│     将 Topic 分类为：强势(维护)、薄弱(修复)、            │
│     待挖掘(进攻)、新兴(抢占)                           │
│                                                    │
│  ② 选题机会挖掘                                      │
│     分析引用数据，发现具体的内容切入角度                   │
│     评估每个机会的优先级和可行性                         │
│                                                    │
│  ③ 平台-AI引擎引用关系                                │
│     分析哪些发布平台被哪些AI引擎引用                     │
│     生成平台×引擎的引用矩阵和分发建议                    │
│                                                    │
│  ─────────────────────────────────────              │
│  可选配置：                                          │
│  日期范围: [最近30天 ▾]                               │
│  平台筛选: [全部] [ChatGPT] [Gemini] [AI Mode]       │
│                                                    │
│  [取消]                            [开始分析 →]      │
└────────────────────────────────────────────────────┘
```

**关键设计决策：**

- 3 步诊断方法论是**只读展示**，不是用户选择。用户看到的是 "这是我们要做什么"，而非 "请你选择"。
- Metrics/Sub-goals **不在此展示**。它们隐含在 pipeline 输出的 `recommended_metrics` 和 `recommended_subgoals` 中，自动流入 Content Pipeline Node 1。
- 点击 "开始分析" 调用 `createAgentTask({ task_type: "opportunity_discovery", ... })`。

### 3.3 完成后 CTA

opportunity_discovery 报告完成后，AgentAnalysis 的详情面板中已有 CTA 按钮（已实现），点击跳转到 Content Pipeline 并预填充 analyzer context。

---

## 4. Mode B：专项分析

### 4.1 入口

Mode A 卡片下方，5 个模板卡片网格：

```
选择分析模板：

[竞品对标] [趋势诊断] [情感分析] [全面检查] [自定义]
```

- "优化机会发现" 从此列表中**移除**（它已是 Mode A 独立入口）。
- 点击任意卡片打开 `TemplateConfigModal`。

### 4.2 TemplateConfigModal 改造

**Step 数从 5 → 6（插入新 Step 2）：**

| 新编号 | 名称 | 说明 | 对应旧编号 |
|--------|------|------|-----------|
| Step 1 | 分析视角 | 原 "分析目标"，重命名。移除 `opportunity`。从模板卡片进入时自动选中对应目标。 | 旧 Step 1 |
| Step 2 | 优化维度（新增） | 可选。展示 Metrics + Sub-goals 两级选择。作为分析的额外视角注入 prompt。 | 无 |
| Step 3 | 数据域 | 不变。 | 旧 Step 2 |
| Step 4 | 图表配置 | 不变。 | 旧 Step 3 |
| Step 5 | Prompt 编辑 | 不变。将已选 Metrics/Sub-goals 作为上下文附加到 prompt。 | 旧 Step 4 |
| Step 6 | 确认执行 | 不变。 | 旧 Step 5 |

### 4.3 新 Step 2：优化维度

```
┌─ Step 2: 优化维度（可选）─────────────────────────┐
│                                                  │
│  选择优化维度可以让分析聚焦特定方向                    │
│  不选择则进行通用分析                               │
│                                                  │
│  成功指标 (Metrics):                              │
│  [✓ 可读性] [✓ 可做答案性] [ 可信赖性] [ 时效性]    │
│                                                  │
│  子目标 (Sub-goals):    — 基于已选 Metrics 过滤 —   │
│  [✓ 内容可理解度] [✓ 机器可读性]                    │
│  [✓ 信息呈现] [ 受众适配] [ 平台适配]              │
│                                                  │
│  [上一步]                           [下一步]      │
└──────────────────────────────────────────────────┘
```

**行为：**
- 从 API `/api/agent/tasks/framework/metrics` 和 `/framework/subgoals` 获取数据。
- Sub-goals 列表根据已选 Metrics 动态过滤（通过 `metric_id` 关联）。
- 完全可选：用户可以不选任何 Metrics，直接下一步。
- 已选的 Metrics/Sub-goals 在 Step 5 (Prompt 编辑) 注入为结构化上下文。

### 4.4 Prompt 注入格式

当用户在 Step 2 选择了 Metrics/Sub-goals，Step 5 的 prompt 末尾追加：

```
---
优化维度上下文：
- 关注的成功指标：可读性、可做答案性
- 关注的子目标：内容可理解度、机器可读性、信息呈现
请在分析中重点关注以上维度的表现。
```

---

## 5. AgentAnalysis 页面布局

### 当前（改造前）

```
New Agent Task tab:
  [Anthony Banner]
  [Greeting + Logo]
  "选择分析模板"
  [竞品对标] [趋势诊断] [优化机会] [全面检查] [情感分析]  ← 5列网格
  [Chat Input]
```

### 改造后

```
New Agent Task tab:
  [Anthony Banner]
  [Greeting + Logo]
  
  ┌── 优化机会发现 (Mode A 大卡片) ──────────────────┐
  │  全量诊断 · Topic定位 · 选题挖掘 · 平台引用关系     │
  └────────────────────────────────── [开始分析 →] ──┘
  
  "选择分析模板"
  [竞品对标] [趋势诊断] [情感分析] [全面检查] [自定义]  ← 5列 (无 opportunity)
  
  [Chat Input]
```

---

## 6. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `geo_saas/web/src/pages/agents/AgentAnalysis.tsx` | 修改 | 拆分模板展示为 Mode A + Mode B 两区域 |
| `geo_saas/web/src/components/insights/TemplateConfigModal.tsx` | 修改 | Step 1 重命名，移除 opportunity，插入新 Step 2 |
| `geo_saas/web/src/components/insights/OpportunityAnalysisModal.tsx` | 新建 | Mode A 专属 Modal |
| `geo_saas/web/src/lib/api.ts` | 可能修改 | 确认 `getOptimizationMetrics`/`getOptimizationSubgoals` API 已存在 |

**无后端变更**：`opportunity_discovery` pipeline、framework 端点、task 创建 API 均已实现。
