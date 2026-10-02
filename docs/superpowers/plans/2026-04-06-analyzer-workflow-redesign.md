# Analyzer Workflow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the AgentAnalysis page into Mode A (优化机会发现, dedicated modal) and Mode B (专项分析, redesigned TemplateConfigModal with new Step 2: 优化维度).

**Architecture:** Frontend-only changes. Mode A gets a new `OpportunityAnalysisModal.tsx`. Mode B modifies the existing `TemplateConfigModal.tsx` to add a Metrics/Sub-goals selection step and remove the `opportunity` goal. `AgentAnalysis.tsx` is updated to render two sections.

**Tech Stack:** React, TypeScript, shadcn/ui, Tailwind CSS, existing API endpoints (`/framework/metrics`, `/framework/subgoals`, `createAgentTask`)

---

### Task 1: Create OpportunityAnalysisModal component

**Files:**
- Create: `geo_saas/web/src/components/insights/OpportunityAnalysisModal.tsx`

This is the Mode A dedicated modal. It shows the 3-step diagnostic methodology as read-only content, optional date/platform config, and a "开始分析" button that creates an `opportunity_discovery` task.

- [ ] **Step 1: Create the modal file**

```tsx
import { useState } from "react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, Search, ArrowRight, Crosshair, Lightbulb, Network } from "lucide-react";
import { createAgentTask } from "@/lib/api";

interface OpportunityAnalysisModalProps {
  open: boolean;
  clientId: string;
  userId: string;
  onClose: () => void;
  onTaskCreated?: () => void;
}

const PLATFORM_OPTIONS = [
  { id: "chatgpt", label: "ChatGPT", icon: "🤖" },
  { id: "gemini", label: "Gemini", icon: "✨" },
  { id: "aimode", label: "AI Mode", icon: "🔍" },
];

const DATE_RANGE_OPTIONS = [
  { id: "7d", label: "最近 7 天", days: 7 },
  { id: "14d", label: "最近 14 天", days: 14 },
  { id: "30d", label: "最近 30 天", days: 30 },
  { id: "90d", label: "最近 90 天", days: 90 },
];

const METHODOLOGY_STEPS = [
  {
    icon: Crosshair,
    title: "Topic 四象限定位",
    description: "根据品牌内容覆盖度、AI 引用模式、趋势方向，将 Topic 分类为：强势(维护)、薄弱(修复)、待挖掘(进攻)、新兴(抢占)",
    color: "text-blue-500 bg-blue-500/10 border-blue-500/20",
  },
  {
    icon: Lightbulb,
    title: "选题机会挖掘",
    description: "分析引用数据，发现具体的内容切入角度，评估每个机会的优先级和可行性",
    color: "text-amber-500 bg-amber-500/10 border-amber-500/20",
  },
  {
    icon: Network,
    title: "平台-AI引擎引用关系",
    description: "分析哪些发布平台被哪些 AI 引擎引用，生成平台×引擎的引用矩阵和分发建议",
    color: "text-emerald-500 bg-emerald-500/10 border-emerald-500/20",
  },
];

export default function OpportunityAnalysisModal({
  open, clientId, userId, onClose, onTaskCreated,
}: OpportunityAnalysisModalProps) {
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [dateRange, setDateRange] = useState("30d");
  const [executing, setExecuting] = useState(false);

  const togglePlatform = (id: string) => {
    setSelectedPlatforms((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  };

  const handleExecute = async () => {
    setExecuting(true);
    try {
      const rangeOption = DATE_RANGE_OPTIONS.find((r) => r.id === dateRange);
      const dateTo = new Date().toISOString().split("T")[0];
      const dateFrom = new Date(Date.now() - (rangeOption?.days || 30) * 86400_000)
        .toISOString()
        .split("T")[0];

      await createAgentTask({
        client_id: clientId,
        user_id: userId,
        task_type: "opportunity_discovery",
        task_name: `优化机会发现 - ${new Date().toLocaleDateString("zh-CN")}`,
        inputs: {
          domains: ["visibility", "citation"],
          date_from: dateFrom,
          date_to: dateTo,
          platforms: selectedPlatforms.length > 0 ? selectedPlatforms : null,
          analysis_goal: "opportunity",
        },
        save_only: false,
      });
      toast.success("优化机会发现任务已启动");
      onTaskCreated?.();
      onClose();
    } catch (e: any) {
      toast.error("任务创建失败：" + (e.message || "未知错误"));
    } finally {
      setExecuting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto bg-background border-border">
        <DialogTitle className="text-lg font-semibold flex items-center gap-2">
          <Search className="h-5 w-5 text-amber-500" />
          优化机会发现
        </DialogTitle>
        <DialogDescription className="text-sm text-muted-foreground -mt-1">
          全量诊断品牌在 AI 搜索中的优化机会，生成行动方案
        </DialogDescription>

        {/* Methodology steps */}
        <div className="space-y-3 mt-2">
          <p className="text-xs font-medium text-muted-foreground">本次分析将执行以下三步诊断：</p>
          {METHODOLOGY_STEPS.map((step, i) => {
            const Icon = step.icon;
            return (
              <div
                key={i}
                className={`flex items-start gap-3 p-3.5 rounded-xl border ${step.color}`}
              >
                <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 bg-background/80">
                  <Icon className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-muted-foreground/60">0{i + 1}</span>
                    <span className="text-sm font-semibold text-foreground">{step.title}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                    {step.description}
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Optional config */}
        <div className="space-y-4 mt-4 pt-4 border-t border-border">
          <p className="text-xs font-medium text-muted-foreground">可选配置</p>

          {/* Date range */}
          <div>
            <label className="text-xs text-muted-foreground mb-1.5 block">日期范围</label>
            <div className="flex gap-2">
              {DATE_RANGE_OPTIONS.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setDateRange(r.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                    dateRange === r.id
                      ? "border-primary bg-primary/5 text-foreground font-medium"
                      : "border-border text-muted-foreground hover:border-primary/40"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          {/* Platform filter */}
          <div>
            <label className="text-xs text-muted-foreground mb-1.5 block">
              平台筛选 <span className="text-muted-foreground/50">（不选 = 全部）</span>
            </label>
            <div className="flex gap-2">
              {PLATFORM_OPTIONS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => togglePlatform(p.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                    selectedPlatforms.includes(p.id)
                      ? "border-primary bg-primary/5 text-foreground font-medium"
                      : "border-border text-muted-foreground hover:border-primary/40"
                  }`}
                >
                  <span>{p.icon}</span>
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-border">
          <Button variant="outline" onClick={onClose} size="sm" disabled={executing}>
            取消
          </Button>
          <Button onClick={handleExecute} size="sm" disabled={executing}>
            {executing ? (
              <>
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                启动中...
              </>
            ) : (
              <>
                开始分析
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Verify the file compiles**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web && npx tsc --noEmit --pretty 2>&1 | grep -i OpportunityAnalysis`
Expected: No errors related to OpportunityAnalysisModal

- [ ] **Step 3: Commit**

```bash
git add geo_saas/web/src/components/insights/OpportunityAnalysisModal.tsx
git commit -m "feat: add OpportunityAnalysisModal for Mode A analyzer entry"
```

---

### Task 2: Update AgentAnalysis page layout — Mode A card + Mode B grid

**Files:**
- Modify: `geo_saas/web/src/pages/agents/AgentAnalysis.tsx`

Split the template gallery section into two areas:
1. A prominent Mode A card at the top (opens OpportunityAnalysisModal)
2. The existing template grid below (Mode B, opens TemplateConfigModal as before)

- [ ] **Step 1: Add import and state for OpportunityAnalysisModal**

At the top of `AgentAnalysis.tsx`, add the import:

```tsx
import OpportunityAnalysisModal from "@/components/insights/OpportunityAnalysisModal";
```

In the component body (near `selectedTemplate` state around line 1066), add:

```tsx
const [opportunityModalOpen, setOpportunityModalOpen] = useState(false);
```

- [ ] **Step 2: Add Mode A card above the template gallery**

Find the template gallery section (around line 1682, the `<div className="w-full max-w-4xl mb-10">` block). Insert a Mode A card **before** the "选择分析模板" text:

```tsx
{/* Mode A: 优化机会发现 — prominent card */}
<div className="w-full max-w-4xl mb-6">
  <button
    onClick={() => setOpportunityModalOpen(true)}
    className="w-full text-left p-5 rounded-2xl border-2 border-amber-500/20 bg-amber-500/[0.03] hover:border-amber-500/40 hover:bg-amber-500/[0.06] hover:shadow-lg hover:shadow-amber-500/5 transition-all duration-300 group"
  >
    <div className="flex items-center gap-4">
      <div className="w-12 h-12 rounded-xl bg-amber-500/10 flex items-center justify-center shrink-0 group-hover:bg-amber-500/15 transition-colors">
        <Search className="h-6 w-6 text-amber-500" />
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-semibold text-foreground group-hover:text-amber-500 transition-colors">
          优化机会发现
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
          全量诊断品牌在 AI 搜索中的优化机会 — Topic 定位 · 选题挖掘 · 平台引用关系 → 内容优化行动方案
        </p>
      </div>
      <ChevronRight className="h-5 w-5 text-muted-foreground/50 group-hover:text-amber-500 group-hover:translate-x-0.5 transition-all shrink-0" />
    </div>
  </button>
</div>
```

Note: `Search` icon is from lucide-react (already imported as part of the existing icons, or add it to the import).

- [ ] **Step 3: Render OpportunityAnalysisModal and pass props**

At the bottom of the component JSX (near the existing `<TemplateConfigModal>` around line 1863), add:

```tsx
<OpportunityAnalysisModal
  open={opportunityModalOpen}
  clientId={clientId}
  userId={userId}
  onClose={() => setOpportunityModalOpen(false)}
  onTaskCreated={() => {
    setOpportunityModalOpen(false);
    setActiveTab("all");
    fetchRuns(true);
  }}
/>
```

- [ ] **Step 4: Verify imports are correct**

Ensure `Search` is in the lucide-react import. Check existing imports at the top of the file — if `Search` is not there, add it to the destructured import.

- [ ] **Step 5: Verify compilation**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add geo_saas/web/src/pages/agents/AgentAnalysis.tsx
git commit -m "feat: add Mode A opportunity card and modal to AgentAnalysis page"
```

---

### Task 3: Remove "opportunity" from TemplateConfigModal Step 1

**Files:**
- Modify: `geo_saas/web/src/components/insights/TemplateConfigModal.tsx`

Remove the `opportunity` option from `ANALYSIS_GOALS` and `RECOMMENDED_CHARTS`, and rename Step 1 label from "分析目标" to "分析视角".

- [ ] **Step 1: Remove opportunity from ANALYSIS_GOALS array**

In `TemplateConfigModal.tsx`, find the `ANALYSIS_GOALS` array (around line 102-150). Remove the entire object with `id: "opportunity"` (lines ~126-133):

```tsx
// REMOVE this block:
{
    id: "opportunity",
    label: "优化机会发现",
    description: "识别品牌在低分 Prompt 中的优化空间，聚焦 RAFT 评分提升",
    icon: Search,
    recommendedDomains: ["visibility", "citation"],
    color: "text-amber-400 border-amber-500/30 bg-amber-500/5",
},
```

Also update the `AnalysisGoal` type (line ~100):

Change:
```tsx
type AnalysisGoal = "benchmark" | "trend" | "opportunity" | "health" | "sentiment";
```
To:
```tsx
type AnalysisGoal = "benchmark" | "trend" | "health" | "sentiment";
```

- [ ] **Step 2: Remove opportunity from RECOMMENDED_CHARTS**

In the `RECOMMENDED_CHARTS` object (around line 189-217), remove the `opportunity` key and its array value.

- [ ] **Step 3: Remove opportunity task type routing**

Find the two places that check `analysisGoal === "opportunity"` (around lines 1963 and 2020):

```tsx
const taskType = analysisGoal === "opportunity" ? "opportunity_discovery" : "analysis";
```

Change both to:
```tsx
const taskType = "analysis";
```

- [ ] **Step 4: Rename Step 1 label in StepIndicator**

In the `StepIndicator` function (around line 251-288), change:

```tsx
{ num: 1, label: "分析目标" },
```
To:
```tsx
{ num: 1, label: "分析视角" },
```

Also in `Step1_Goal` (around line 321), update the heading:

Change:
```tsx
<h3 className="text-sm font-semibold mb-1">选择分析目标</h3>
```
To:
```tsx
<h3 className="text-sm font-semibold mb-1">选择分析视角</h3>
```

And the description below it:
```tsx
<p className="text-xs text-muted-foreground mb-4">
    分析视角决定了后续步骤的推荐配置 — 数据领域、推荐图表和 Prompt 策略都会根据视角自动适配
</p>
```

- [ ] **Step 5: Verify compilation**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add geo_saas/web/src/components/insights/TemplateConfigModal.tsx
git commit -m "refactor: remove opportunity from TemplateConfigModal, rename Step 1 to 分析视角"
```

---

### Task 4: Add Step 2 (优化维度) to TemplateConfigModal

**Files:**
- Modify: `geo_saas/web/src/components/insights/TemplateConfigModal.tsx`

Insert a new Step 2 between the existing Step 1 (分析视角) and Step 2 (数据选择). This shifts all subsequent steps by +1 (old Step 2→3, 3→4, 4→5, 5→6).

- [ ] **Step 1: Change step type from 5 to 6 steps**

Find the step state (line ~1692):

Change:
```tsx
const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);
```
To:
```tsx
const [step, setStep] = useState<1 | 2 | 3 | 4 | 5 | 6>(1);
```

- [ ] **Step 2: Add Metrics/Sub-goals state**

After the existing Step 1 state block (around line 1703), add:

```tsx
// Step 2 state (优化维度)
const [selectedMetricIds, setSelectedMetricIds] = useState<string[]>([]);
const [selectedSubgoalIds, setSelectedSubgoalIds] = useState<string[]>([]);
const [metricsData, setMetricsData] = useState<Array<{ id: string; name: string; display_name: string; description: string }>>([]);
const [subgoalsData, setSubgoalsData] = useState<Array<{ id: string; metric_id: string; name: string; display_name: string; description: string }>>([]);
```

- [ ] **Step 3: Fetch metrics and subgoals data**

After the existing variables useEffect (around line 1944), add:

```tsx
// Fetch metrics and subgoals for Step 2
useEffect(() => {
    if (!open) return;
    import("@/lib/api").then(({ getOptimizationMetrics, getOptimizationSubgoals }) => {
        getOptimizationMetrics().then(setMetricsData).catch(() => setMetricsData([]));
        getOptimizationSubgoals().then(setSubgoalsData).catch(() => setSubgoalsData([]));
    });
}, [open]);
```

- [ ] **Step 4: Update StepIndicator to 6 steps**

Change the `StepIndicator` function signature and steps array:

```tsx
function StepIndicator({ currentStep }: { currentStep: 1 | 2 | 3 | 4 | 5 | 6 }) {
    const steps = [
        { num: 1, label: "分析视角" },
        { num: 2, label: "优化维度" },
        { num: 3, label: "数据选择" },
        { num: 4, label: "配置图表" },
        { num: 5, label: "Prompt 编辑" },
        { num: 6, label: "确认执行" },
    ];
```

- [ ] **Step 5: Create Step2_Metrics component**

Add this new component before the main modal function (around line 290, after StepIndicator):

```tsx
// ─────────────────────────────────────────────────────────────────────────────
// Step 2: Optimization Dimensions (optional)
// ─────────────────────────────────────────────────────────────────────────────
function Step2_Metrics({
    metricsData,
    subgoalsData,
    selectedMetricIds,
    setSelectedMetricIds,
    selectedSubgoalIds,
    setSelectedSubgoalIds,
}: {
    metricsData: Array<{ id: string; name: string; display_name: string; description: string }>;
    subgoalsData: Array<{ id: string; metric_id: string; name: string; display_name: string; description: string }>;
    selectedMetricIds: string[];
    setSelectedMetricIds: (ids: string[]) => void;
    selectedSubgoalIds: string[];
    setSelectedSubgoalIds: (ids: string[]) => void;
}) {
    const toggleMetric = (id: string) => {
        const next = selectedMetricIds.includes(id)
            ? selectedMetricIds.filter((m) => m !== id)
            : [...selectedMetricIds, id];
        setSelectedMetricIds(next);
        // Remove subgoals that no longer have a selected parent metric
        const removedMetricIds = selectedMetricIds.filter((m) => !next.includes(m));
        if (removedMetricIds.length > 0) {
            const orphaned = subgoalsData
                .filter((s) => removedMetricIds.includes(s.metric_id))
                .map((s) => s.id);
            setSelectedSubgoalIds(selectedSubgoalIds.filter((s) => !orphaned.includes(s)));
        }
    };

    const toggleSubgoal = (id: string) => {
        setSelectedSubgoalIds(
            selectedSubgoalIds.includes(id)
                ? selectedSubgoalIds.filter((s) => s !== id)
                : [...selectedSubgoalIds, id]
        );
    };

    // Filter subgoals by selected metrics
    const filteredSubgoals = selectedMetricIds.length > 0
        ? subgoalsData.filter((s) => selectedMetricIds.includes(s.metric_id))
        : subgoalsData;

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-sm font-semibold mb-1">优化维度（可选）</h3>
                <p className="text-xs text-muted-foreground mb-4">
                    选择优化维度可以让分析聚焦特定方向，不选择则进行通用分析
                </p>
            </div>

            {/* Metrics */}
            <div>
                <label className="text-xs font-medium text-muted-foreground mb-2 block">
                    成功指标 (Metrics)
                </label>
                <div className="grid grid-cols-2 gap-2">
                    {metricsData.map((m) => {
                        const selected = selectedMetricIds.includes(m.id);
                        return (
                            <button
                                key={m.id}
                                onClick={() => toggleMetric(m.id)}
                                className={`text-left p-3 rounded-xl border transition-all duration-200 ${
                                    selected
                                        ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                                        : "border-border hover:border-primary/40 hover:bg-muted/30"
                                }`}
                            >
                                <div className="flex items-center gap-2">
                                    <div className={`w-4 h-4 rounded border-2 flex items-center justify-center ${
                                        selected ? "border-primary bg-primary" : "border-muted-foreground/30"
                                    }`}>
                                        {selected && (
                                            <svg className="w-3 h-3 text-primary-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                            </svg>
                                        )}
                                    </div>
                                    <span className="text-sm font-medium">{m.display_name}</span>
                                </div>
                                <p className="text-[11px] text-muted-foreground mt-1 ml-6 leading-relaxed">{m.description}</p>
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Sub-goals */}
            {filteredSubgoals.length > 0 && (
                <div>
                    <label className="text-xs font-medium text-muted-foreground mb-2 block">
                        子目标 (Sub-goals)
                        {selectedMetricIds.length > 0 && (
                            <span className="text-muted-foreground/50 ml-1">— 基于已选指标过滤</span>
                        )}
                    </label>
                    <div className="flex flex-wrap gap-2">
                        {filteredSubgoals.map((s) => {
                            const selected = selectedSubgoalIds.includes(s.id);
                            return (
                                <button
                                    key={s.id}
                                    onClick={() => toggleSubgoal(s.id)}
                                    className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                                        selected
                                            ? "border-primary bg-primary/5 text-foreground font-medium"
                                            : "border-border text-muted-foreground hover:border-primary/40"
                                    }`}
                                >
                                    {s.display_name}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Skip hint */}
            {selectedMetricIds.length === 0 && (
                <p className="text-xs text-muted-foreground/60 italic">
                    跳过此步骤将进行通用分析，不限定优化维度
                </p>
            )}
        </div>
    );
}
```

- [ ] **Step 6: Update handleNext and handleBack for 6 steps**

Change `handleNext` (around line 1951):

```tsx
function handleNext() {
    if (step === 3 && selectedDomains.length === 0) return;
    if (step < 6) setStep((step + 1) as 1 | 2 | 3 | 4 | 5 | 6);
}

function handleBack() {
    if (step > 1) setStep((step - 1) as 1 | 2 | 3 | 4 | 5 | 6);
}
```

- [ ] **Step 7: Update step rendering in JSX**

In the main modal JSX (around line 2189-2264), shift all step numbers +1 for old steps 2-5, and insert Step 2 rendering. The new rendering order:

```tsx
{step === 1 && (
    <Step1_Goal
        analysisGoal={analysisGoal}
        setAnalysisGoal={setAnalysisGoal}
        templateDomains={template.data_domains.length > 0 ? template.data_domains : ["visibility", "citation", "sentiment"]}
        setSelectedDomains={setSelectedDomains}
    />
)}
{step === 2 && (
    <Step2_Metrics
        metricsData={metricsData}
        subgoalsData={subgoalsData}
        selectedMetricIds={selectedMetricIds}
        setSelectedMetricIds={setSelectedMetricIds}
        selectedSubgoalIds={selectedSubgoalIds}
        setSelectedSubgoalIds={setSelectedSubgoalIds}
    />
)}
{step === 3 && (
    <Step2_Data
        templateDomains={template.data_domains.length > 0 ? template.data_domains : ["visibility", "citation", "sentiment"]}
        selectedDomains={selectedDomains}
        setSelectedDomains={setSelectedDomains}
        analysisGoal={analysisGoal}
        selectedPlatforms={selectedPlatforms}
        setSelectedPlatforms={setSelectedPlatforms}
        peers={peers}
        selectedPeers={selectedPeers}
        setSelectedPeers={setSelectedPeers}
        dateFrom={dateFrom}
        setDateFrom={setDateFrom}
        dateTo={dateTo}
        setDateTo={setDateTo}
    />
)}
{step === 4 && (
    <Step3_Charts
        chartRequests={chartRequests}
        setChartRequests={setChartRequests}
        analysisGoal={analysisGoal}
        baselineType={baselineType}
        setBaselineType={setBaselineType}
        baselineDateFrom={baselineDateFrom}
        setBaselineDateFrom={setBaselineDateFrom}
        baselineDateTo={baselineDateTo}
        setBaselineDateTo={setBaselineDateTo}
        thresholds={thresholds}
        setThresholds={setThresholds}
        dateFrom={dateFrom}
        dateTo={dateTo}
    />
)}
{step === 5 && (
    <Step4_Prompt
        prompt={prompt}
        setPrompt={setPrompt}
        variables={variables}
        analysisDepth={analysisDepth}
        setAnalysisDepth={setAnalysisDepth}
        focusTags={focusTags}
        setFocusTags={setFocusTags}
    />
)}
{step === 6 && (
    <Step5_Confirm
        selectedDomains={selectedDomains}
        dateFrom={dateFrom}
        dateTo={dateTo}
        chartCount={chartRequests.filter(r => r.nl_query.trim()).length}
        promptLength={prompt.length}
        modelId={modelId}
        setModelId={setModelId}
        modelIds={modelIds}
        cronExpression={cronExpression}
        setCronExpression={setCronExpression}
        analysisGoal={analysisGoal}
        selectedPlatforms={selectedPlatforms}
        selectedPeers={selectedPeers}
        peers={peers}
        baselineType={baselineType}
        thresholds={thresholds}
        analysisDepth={analysisDepth}
        focusTags={focusTags}
    />
)}
```

- [ ] **Step 8: Update navigation buttons for 6 steps**

In the footer area (around line 2267-2293), update all references from `step === 5` to `step === 6`:

```tsx
<Button variant="outline" onClick={step === 1 ? onClose : handleBack} size="sm">
    {step === 1 ? <X className="h-4 w-4 mr-1.5" /> : <ChevronLeft className="h-4 w-4 mr-1.5" />}
    {step === 1 ? "取消" : "上一步"}
</Button>
{step < 6 ? (
    <Button
        onClick={handleNext}
        size="sm"
        disabled={step === 3 && selectedDomains.length === 0}
    >
        下一步
        <ChevronRight className="h-4 w-4 ml-1.5" />
    </Button>
) : (
    <div className="flex gap-2.5">
        {/* ... save + execute buttons unchanged ... */}
    </div>
)}
```

- [ ] **Step 9: Include metrics/subgoals in task inputs**

In both `saveTemplate` and `runReport` functions, add the selected metrics/subgoals to the `inputs` object. Find the `inputs: { ... }` block in both functions and add:

```tsx
selected_metric_ids: selectedMetricIds.length > 0 ? selectedMetricIds : null,
selected_subgoal_ids: selectedSubgoalIds.length > 0 ? selectedSubgoalIds : null,
```

- [ ] **Step 10: Inject metrics context into prompt at Step 5**

In `runReport` (and `saveTemplate`), before sending the prompt, append the metrics context if selected. Alternatively, add it to the prompt in the `handleNext` transition from step 4 to step 5. The cleaner approach is to append it to the inputs and let the backend handle it, which we already do via `selected_metric_ids` / `selected_subgoal_ids`.

However, for the prompt preview in Step 5, add a readonly info block. In `Step4_Prompt` component, add a prop for the selected metrics context and render it as a hint below the prompt editor. This is optional UX polish — the backend receives the IDs directly.

- [ ] **Step 11: Reset new state on template change**

In the `useEffect` that resets state when template changes (around line 1730-1906), add:

```tsx
setSelectedMetricIds([]);
setSelectedSubgoalIds([]);
```

- [ ] **Step 12: Verify compilation**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

- [ ] **Step 13: Commit**

```bash
git add geo_saas/web/src/components/insights/TemplateConfigModal.tsx
git commit -m "feat: add Step 2 (优化维度) with Metrics/Sub-goals selection to TemplateConfigModal"
```

---

### Task 5: Filter "opportunity" template from AgentAnalysis template grid

**Files:**
- Modify: `geo_saas/web/src/pages/agents/AgentAnalysis.tsx`

Since the "优化机会发现" template still exists in the database (it was seeded), it will still appear in the Mode B template grid from the API. We need to filter it out on the frontend.

- [ ] **Step 1: Filter out opportunity template from the grid**

In `AgentAnalysis.tsx`, find where templates are rendered in the grid (around line 1689-1729). Wrap the `templates.map()` with a filter:

Change:
```tsx
{templates.map((t) => {
```
To:
```tsx
{templates.filter((t) => t.name !== "优化机会发现").map((t) => {
```

Alternatively, if the template has a known ID or data_domains signature, filter by that. Filtering by name is simplest and safe since the name is seeded.

- [ ] **Step 2: Verify compilation**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web && npx tsc --noEmit --pretty 2>&1 | head -10`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add geo_saas/web/src/pages/agents/AgentAnalysis.tsx
git commit -m "fix: filter opportunity template from Mode B template grid"
```

---

### Task 6: Visual QA and integration test

**Files:**
- No file changes — manual verification

- [ ] **Step 1: Verify Mode A card renders on AgentAnalysis page**

Navigate to the AgentAnalysis page's "New Agent Task" tab. Verify:
- The "优化机会发现" card appears prominently above the template grid
- Clicking it opens the `OpportunityAnalysisModal`
- The 3-step methodology is displayed as read-only
- Date range and platform toggles work
- "开始分析" creates an `opportunity_discovery` task

- [ ] **Step 2: Verify Mode B template grid**

Verify:
- The template grid shows 5 cards (竞品对标, 趋势诊断, 情感分析, 全面检查, 自定义) — NO "优化机会发现"
- Clicking any card opens `TemplateConfigModal`
- Step 1 is labeled "分析视角" (not "分析目标")
- The goal selection shows 4 options (no "opportunity")

- [ ] **Step 3: Verify Step 2 (优化维度) in TemplateConfigModal**

Verify:
- After selecting a goal in Step 1, clicking "下一步" goes to Step 2 (优化维度)
- Metrics are fetched and displayed as checkable cards
- Sub-goals filter by selected Metrics
- Clicking "下一步" without selecting anything works (optional step)
- Subsequent steps (3-6) still work correctly
- Selected metric/subgoal IDs are included in the task inputs

- [ ] **Step 4: Verify semantic color tokens**

Verify both modals respect light/dark theme:
- No hardcoded `bg-zinc-*` or `text-white` classes
- All colors use semantic tokens (`bg-background`, `text-foreground`, `border-border`, etc.)

- [ ] **Step 5: Commit any fixes discovered during QA**

```bash
git add -A
git commit -m "fix: visual QA fixes for analyzer workflow redesign"
```
