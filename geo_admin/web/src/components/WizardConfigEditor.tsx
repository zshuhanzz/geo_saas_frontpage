/**
 * WizardConfigEditor
 *
 * Visual editor for `geo_report_templates.wizard_config` JSONB column.
 *
 * The wizard_config is the Phase 2 two-dimensional template × wizard contract:
 *   - `required_metrics` — list of metric_name slugs (from geo_analysis_metrics)
 *     that the Analyze/Content pipeline MUST compute no matter what the user
 *     selected in the wizard.
 *   - `required_chapters` — list of domains (visibility/citation/sentiment) the
 *     synthesis step MUST include. Analysis templates only.
 *   - `required_subgoals` — list of optimization subgoal slugs the Content
 *     pipeline MUST cover. Content templates only.
 *   - `steps` — per-step wizard enablement + defaults. Kept as raw JSON (too
 *     structurally varied for visual editing at this stage).
 *
 * This component intentionally exposes the critical contract fields with visual
 * controls, and leaves `steps` as a JSON textarea. That is the split that hurts
 * when wrong and has the most stable schema.
 *
 * Usage:
 *   <WizardConfigEditor
 *     value={form.wizard_config}
 *     onChange={(next) => setForm({ ...form, wizard_config: next })}
 *     mode="analysis"  // or "content"
 *   />
 */
import { useState, useEffect, useMemo } from "react";
import {
    getAnalysisMetrics,
    getSubgoals,
    getWorkflowConfig,
} from "../api/client";
import {
    parseWorkflowConfigValue,
    type WorkflowConfigGroupedOut,
} from "../lib/workflowConfig";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import * as LucideIcons from "lucide-react";
import {
    AlertTriangle,
    Ruler,
    Target,
    FileText,
    Layers,
    ChevronDown,
    ChevronRight,
    Plus,
    Trash2,
} from "lucide-react";

type LucideMap = Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>>;

/**
 * Resolve a lucide-react icon by its component name (e.g. "BarChart3",
 * "BookOpen") into an actual React element. Dictionary rows in
 * geo_workflow_config store icons as string names in value.icon — without
 * this helper those strings were being rendered as literal text next to
 * option labels (e.g. "BarChart3 描述性分析"). Returns null if the name is
 * missing or does not resolve to a valid component.
 */
function IconFromName({ name, className = "h-3.5 w-3.5" }: { name?: string | null; className?: string }) {
    if (!name || typeof name !== "string") return null;
    const Cmp = (LucideIcons as unknown as LucideMap)[name];
    if (!Cmp) return null;
    return <Cmp className={className} aria-hidden />;
}

interface ChapterOption {
    key: string;
    label: string;
    color: string;
}

const CHAPTER_OPTIONS: ChapterOption[] = [
    { key: "visibility", label: "Visibility 可见度", color: "bg-blue-500/10 text-blue-400 border-blue-500/30" },
    { key: "citation", label: "Citation 引用", color: "bg-purple-500/10 text-purple-400 border-purple-500/30" },
    { key: "sentiment", label: "Sentiment 情感", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" },
];

interface WizardConfig {
    version: number;
    steps: Record<string, Record<string, unknown>>;
    required_metrics: string[];
    required_chapters?: string[];
    required_subgoals?: string[];
    [key: string]: unknown;
}

const EMPTY_ANALYSIS: WizardConfig = {
    version: 1,
    steps: {},
    required_metrics: [],
    required_chapters: [],
};

const EMPTY_CONTENT: WizardConfig = {
    version: 1,
    steps: {},
    required_metrics: [],
    required_subgoals: [],
};

const VISUAL_CONFIG_KEYS = new Set([
    "version",
    "steps",
    "required_metrics",
    "required_chapters",
    "required_subgoals",
]);

const ADVANCED_CONFIG_FIELDS = [
    {
        key: "platform_playbook",
        label: "Platform Playbook",
        description: "平台叙事、禁用项、品牌露出、数据使用等模板级规则。",
        rows: 10,
    },
    {
        key: "generation_requirements",
        label: "Generation Requirements",
        description: "输出形态、must include / must not include、策略冲突解决规则。",
        rows: 8,
    },
    {
        key: "depth_profiles",
        label: "Depth Profiles",
        description: "quick / standard / deep / authority 对应的字数、结构和深度约束。",
        rows: 8,
    },
    {
        key: "ratf_metric_jobs",
        label: "RATF Metric Jobs",
        description: "RATF 顶层指标的执行要求。Reddit 可在这里禁用表格/矩阵。",
        rows: 7,
    },
    {
        key: "ratf_rendering",
        label: "RATF Rendering",
        description: "RATF 子目标描述是否透出、子目标文案覆盖等模板级渲染策略。",
        rows: 8,
    },
    {
        key: "prompt_input_policy",
        label: "Prompt Input Policy",
        description: "最终 Prompt 输入策略，例如 Reddit Native 模式下隐藏原始 Strategy/Citation/RATF 明细。",
        rows: 8,
    },
    {
        key: "derived_prompt_artifacts",
        label: "Derived Prompt Artifacts",
        description: "是否生成并注入 Community Brief / Experience Style Notes 等派生 Prompt 素材。",
        rows: 8,
    },
    {
        key: "experience_style_notes",
        label: "Experience Style Notes",
        description: "经验感写作素材配置。用于把 Discover/Citation 信号转成写作视角，不作为事实声明。",
        rows: 8,
    },
    {
        key: "community_brief",
        label: "Community Brief",
        description: "社区摘要配置。Reddit 模板用它承接上游策略、Citation 与 Discover 的压缩输入。",
        rows: 8,
    },
    {
        key: "reddit_native_contract",
        label: "Reddit Native Contract",
        description: "Reddit 叙事、开头、品牌露出、结构和禁用表达的硬约束。",
        rows: 10,
    },
    {
        key: "segmented_generation",
        label: "Segmented Generation",
        description: "Deep / Authority 长文分段生成的大纲、章节和审阅规则。",
        rows: 8,
    },
    {
        key: "quality_gate",
        label: "Quality Gate",
        description: "确定性检查、Revise 触发规则和 revision_guidance。",
        rows: 10,
    },
    {
        key: "resource_link_policy",
        label: "Resource Link Policy",
        description: "Helpful Resources / Related Resources 的可用 URL 池与校验规则。",
        rows: 8,
    },
    {
        key: "reddit_research",
        label: "Reddit Research",
        description: "Subreddit Targeting、Reddit Discovery、Artifact Preparation 的模板级配置。",
        rows: 8,
    },
    {
        key: "citation_analysis",
        label: "Citation Analysis",
        description: "Citation Analysis 的启用方式、模式和数据使用策略。",
        rows: 7,
    },
] as const;

interface FieldSchema {
    key: string;
    label?: string;
    type: string;
    description?: string;
    rows?: number;
    ref_config_type?: string;
    item_fields?: FieldSchema[];
}

interface WorkflowStepLib {
    key: string;
    num: number | null;
    label: string;
    description: string;
    fields: FieldSchema[];
    sort_order?: number;
    orphan?: boolean;
}

interface RefOption {
    key: string;
    label: string;
    icon?: string;
    description?: string;
    scope?: string;
    sort_order?: number;
    _raw: Record<string, unknown>;
}

type RefLookup = Record<string, RefOption[]>;

interface MetricRow {
    id: string;
    metric_name: string;
    domain: string;
    display_name_zh?: string;
    display_name_en?: string;
    description?: string;
}

interface SubgoalRow {
    id: string;
    name_zh?: string;
    name_en?: string;
    description?: string;
}

interface WizardConfigEditorProps {
    value: WizardConfig | string | null | undefined;
    onChange: (next: WizardConfig) => void;
    mode?: "analysis" | "content";
}

export default function WizardConfigEditor({ value, onChange, mode = "analysis" }: WizardConfigEditorProps) {
    const [metricsLib, setMetricsLib] = useState<MetricRow[]>([]);
    const [subgoalsLib, setSubgoalsLib] = useState<SubgoalRow[]>([]);
    const [stepsLib, setStepsLib] = useState<WorkflowStepLib[]>([]); // workflow_step dictionary
    // refLookup: { [config_type]: [{key, label, icon, description, ...}] }
    // Populated from the same getWorkflowConfig call that loads stepsLib, so
    // schema-driven single_ref / multi_ref fields can render dropdowns for any
    // scoped or shared config_type without extra network calls.
    const [refLookup, setRefLookup] = useState<RefLookup>({});
    const [loading, setLoading] = useState<boolean>(true);
    const [stepsJsonText, setStepsJsonText] = useState<string>("{}");
    const [stepsJsonError, setStepsJsonError] = useState<string>("");
    const [stepsJsonMode, setStepsJsonMode] = useState<boolean>(false);
    const [expandedStepKey, setExpandedStepKey] = useState<string | null>(null);
    const [metricSearch, setMetricSearch] = useState<string>("");

    // Normalize the incoming value so the rest of the component works on a
    // stable shape. JSONB can arrive as null, undefined, string, or object.
    const config = useMemo<WizardConfig>(() => {
        const base = mode === "content" ? EMPTY_CONTENT : EMPTY_ANALYSIS;
        if (!value) return { ...base };
        if (typeof value === "string") {
            try {
                return { ...base, ...JSON.parse(value) };
            } catch {
                return { ...base };
            }
        }
        return { ...base, ...(value as WizardConfig) };
    }, [value, mode]);

    const requiredMetrics = Array.isArray(config.required_metrics) ? config.required_metrics : [];
    const requiredChapters = Array.isArray(config.required_chapters) ? config.required_chapters : [];
    const requiredSubgoals = Array.isArray(config.required_subgoals) ? config.required_subgoals : [];

    // Load lookup data once on mount
    useEffect(() => {
        let cancelled = false;
        (async () => {
            setLoading(true);
            try {
                const scope = mode === "content" ? "content_generation" : "analysis";
                const [metricsResp, subgoalsResp, workflowCfg] = await Promise.all([
                    getAnalysisMetrics({ is_active: true, limit: 200 }).catch(() => ({
                        data: [],
                        pagination: { page: 1, total: 0, pages: 0 },
                    })),
                    mode === "content"
                        ? getSubgoals("", true).catch(() => [])
                        : Promise.resolve([]),
                    getWorkflowConfig(scope).catch(
                        (): WorkflowConfigGroupedOut => ({}),
                    ),
                ]);
                if (cancelled) return;
                setMetricsLib(metricsResp.data.map((metric) => ({
                    id: metric.id,
                    metric_name: metric.metric_name,
                    domain: metric.domain,
                    display_name_zh: metric.display_name_zh,
                    display_name_en: metric.display_name_en || undefined,
                    description: metric.description,
                })));
                setSubgoalsLib(subgoalsResp);

                // Build refLookup: flatten every config_type returned by the
                // backend (scoped rows + shared rows) into a normalized option
                // list. The schema-driven field renderer consumes this map for
                // single_ref / multi_ref dropdowns.
                const lookup: RefLookup = {};
                for (const [ct, rows] of Object.entries(workflowCfg || {})) {
                    if (!Array.isArray(rows)) continue;
                    lookup[ct] = rows.map((r) => {
                        const v = parseWorkflowConfigValue(r.value);
                        return {
                            key: r.key,
                            label: (v.label as string) || r.key,
                            icon: v.icon as string | undefined,
                            description: v.description as string | undefined,
                            scope: r.scope,
                            sort_order: r.sort_order || 0,
                            _raw: v,
                        };
                    });
                    lookup[ct].sort(
                        (a, b) => (a.sort_order || 0) - (b.sort_order || 0),
                    );
                }
                setRefLookup(lookup);

                // Normalize workflow_step entries into a sorted lib we can
                // render as cards. value schema:
                //   {num, label, description, fields: [<field schema>]}.
                const rawSteps: WorkflowStepLib[] = (workflowCfg?.workflow_step || []).map((s) => {
                    const v = parseWorkflowConfigValue(s.value);
                    return {
                        key: s.key,
                        num: (v.num as number) ?? 0,
                        label: (v.label as string) || s.key,
                        description: (v.description as string) || "",
                        fields: Array.isArray(v.fields) ? (v.fields as FieldSchema[]) : [],
                        sort_order: s.sort_order || 0,
                    };
                });
                rawSteps.sort((a, b) => {
                    if ((a.num || 0) !== (b.num || 0)) return (a.num || 0) - (b.num || 0);
                    return (a.sort_order || 0) - (b.sort_order || 0);
                });
                setStepsLib(rawSteps);
            } finally {
                if (cancelled) return;
                setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [mode]);

    // Keep the JSON editor text in sync with the incoming steps value.
    useEffect(() => {
        setStepsJsonText(JSON.stringify(config.steps || {}, null, 2));
        setStepsJsonError("");
    }, [config.steps]);

    function emit(patch: Partial<WizardConfig>): void {
        onChange({ ...config, ...patch });
    }

    function setConfigKey(key: string, value: unknown): void {
        const next: WizardConfig = { ...config };
        if (value === undefined) {
            delete next[key];
        } else {
            next[key] = value;
        }
        onChange(next);
    }

    function replaceConfig(nextConfig: Record<string, unknown>): void {
        onChange({ ...(mode === "content" ? EMPTY_CONTENT : EMPTY_ANALYSIS), ...nextConfig });
    }

    function toggleMetric(name: string) {
        const next = requiredMetrics.includes(name)
            ? requiredMetrics.filter((m) => m !== name)
            : [...requiredMetrics, name];
        emit({ required_metrics: next });
    }

    function toggleChapter(key: string) {
        const next = requiredChapters.includes(key)
            ? requiredChapters.filter((c) => c !== key)
            : [...requiredChapters, key];
        emit({ required_chapters: next });
    }

    function toggleSubgoal(id: string) {
        const next = requiredSubgoals.includes(id)
            ? requiredSubgoals.filter((s) => s !== id)
            : [...requiredSubgoals, id];
        emit({ required_subgoals: next });
    }

    function handleStepsJsonChange(text: string) {
        setStepsJsonText(text);
        if (!text.trim()) {
            setStepsJsonError("");
            emit({ steps: {} });
            return;
        }
        try {
            const parsed = JSON.parse(text);
            if (typeof parsed !== "object" || Array.isArray(parsed)) {
                setStepsJsonError("steps must be a JSON object");
                return;
            }
            setStepsJsonError("");
            emit({ steps: parsed });
        } catch (err) {
            setStepsJsonError((err as Error).message);
        }
    }

    // ─── Step manipulation (visual mode) ───
    const stepsObj: Record<string, Record<string, unknown>> =
        config.steps && typeof config.steps === "object" ? config.steps : {};

    // Replace a step's inner defaults (everything except `enabled`) in one
    // shot. Unlike updateStep's merge semantics, this supports *removal* of
    // keys — which the schema-driven form needs when a user clears a field.
    function setStepInner(key: string, innerObj: Record<string, unknown>) {
        const cur = stepsObj[key] || {};
        const next = {
            ...stepsObj,
            [key]: { enabled: cur.enabled !== false, ...innerObj },
        };
        emit({ steps: next });
    }

    function toggleStepEnabled(key: string) {
        const cur = stepsObj[key] || {};
        const wasEnabled = cur.enabled !== false;
        const nowEnabled = !wasEnabled;
        const next = {
            ...stepsObj,
            [key]: { ...cur, enabled: nowEnabled },
        };
        emit({ steps: next });
    }

    function removeStep(key: string) {
        const next = { ...stepsObj };
        delete next[key];
        emit({ steps: next });
    }

    function toggleStepsJsonMode() {
        if (!stepsJsonMode) {
            // Going from visual → JSON: sync current stepsObj to text
            setStepsJsonText(JSON.stringify(stepsObj, null, 2));
            setStepsJsonError("");
            setStepsJsonMode(true);
            return;
        }
        // Going from JSON → visual: re-parse the latest text, then bail out if
        // the user has introduced a syntax error they need to fix first.
        try {
            const parsed = JSON.parse(stepsJsonText || "{}");
            if (typeof parsed !== "object" || Array.isArray(parsed)) {
                setStepsJsonError("steps must be a JSON object");
                return;
            }
            setStepsJsonError("");
            emit({ steps: parsed });
            setStepsJsonMode(false);
        } catch (err) {
            setStepsJsonError((err as Error).message);
        }
    }

    // Unresolved metric names (in config but not in current library) — surface
    // these so admins notice if a metric has been removed from geo_analysis_metrics.
    const unknownMetrics = useMemo(() => {
        const known = new Set(metricsLib.map((m) => m.metric_name));
        return requiredMetrics.filter((name) => !known.has(name));
    }, [metricsLib, requiredMetrics]);

    const unknownSubgoals = useMemo(() => {
        if (mode !== "content") return [] as string[];
        const known = new Set(subgoalsLib.map((s) => s.id));
        return requiredSubgoals.filter((id) => !known.has(id));
    }, [subgoalsLib, requiredSubgoals, mode]);

    const filteredMetrics = useMemo(() => {
        const q = metricSearch.trim().toLowerCase();
        if (!q) return metricsLib;
        return metricsLib.filter(
            (m) =>
                m.metric_name?.toLowerCase().includes(q) ||
                (m.display_name_zh || "").toLowerCase().includes(q) ||
                (m.display_name_en || "").toLowerCase().includes(q),
        );
    }, [metricsLib, metricSearch]);

    return (
        <div className="border border-border/60 rounded-xl p-5 space-y-5 bg-muted/5">
            <div className="flex items-start gap-2">
                <Target className="h-5 w-5 text-primary mt-0.5" />
                <div>
                    <div className="text-sm font-semibold text-foreground">Wizard Config (契约模式)</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                        这里定义的指标 / 章节 / 子目标是 <strong>模板级强制项</strong>，
                        不管用户在 SaaS 向导里怎么勾选，Pipeline 都会先把这些补齐。
                    </div>
                </div>
            </div>

            {/* ─── Required Metrics ─── */}
            <div>
                <div className="flex items-center gap-2 mb-2">
                    <Ruler className="h-4 w-4 text-primary" />
                    <span className="text-xs font-semibold text-foreground uppercase tracking-wider">
                        Required Metrics
                    </span>
                    <Badge variant="secondary" className="ml-1 text-[10px]">
                        {requiredMetrics.length}
                    </Badge>
                    <Input
                        placeholder="搜索 metric..."
                        value={metricSearch}
                        onChange={(e) => setMetricSearch(e.target.value)}
                        className="ml-auto h-7 w-48 text-xs"
                    />
                </div>

                {loading ? (
                    <div className="text-xs text-muted-foreground py-3">Loading metrics library…</div>
                ) : metricsLib.length === 0 ? (
                    <div className="text-xs text-yellow-500 py-3 flex items-center gap-2">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        <span>
                            geo_analysis_metrics 为空。先去{" "}
                            <a href="/analysis/metrics" className="underline">
                                Analysis Metrics
                            </a>{" "}
                            配置指标，或运行 migration 026 种子数据。
                        </span>
                    </div>
                ) : (
                    <div className="border rounded-md max-h-56 overflow-y-auto bg-background">
                        {filteredMetrics.map((m) => {
                            const on = requiredMetrics.includes(m.metric_name);
                            return (
                                <label
                                    key={m.id}
                                    className="flex items-start gap-2 px-3 py-2 border-b border-border/40 last:border-b-0 cursor-pointer hover:bg-accent/30"
                                >
                                    <Checkbox
                                        checked={on}
                                        onCheckedChange={() => toggleMetric(m.metric_name)}
                                        className="mt-0.5"
                                    />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-xs font-mono text-primary">
                                                {m.metric_name}
                                            </span>
                                            <Badge variant="outline" className="text-[9px] py-0 px-1">
                                                {m.domain}
                                            </Badge>
                                            <span className="text-xs text-foreground">
                                                {m.display_name_zh}
                                            </span>
                                        </div>
                                        {m.description && (
                                            <div className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">
                                                {m.description}
                                            </div>
                                        )}
                                    </div>
                                </label>
                            );
                        })}
                        {filteredMetrics.length === 0 && (
                            <div className="text-xs text-muted-foreground text-center py-4">
                                No metrics matched "{metricSearch}"
                            </div>
                        )}
                    </div>
                )}

                {unknownMetrics.length > 0 && (
                    <div className="mt-2 flex items-start gap-2 text-xs text-yellow-500">
                        <AlertTriangle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
                        <div>
                            以下 metric_name 在当前 library 中找不到，但仍保留在契约里。
                            可能已经被禁用或删除：
                            <div className="mt-1 flex flex-wrap gap-1">
                                {unknownMetrics.map((name) => (
                                    <Badge
                                        key={name}
                                        variant="outline"
                                        className="font-mono text-[10px] border-yellow-500/50"
                                    >
                                        {name}
                                    </Badge>
                                ))}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* ─── Required Chapters (analysis only) ─── */}
            {mode === "analysis" && (
                <div>
                    <div className="text-xs font-semibold text-foreground uppercase tracking-wider mb-2">
                        Required Chapters
                        <span className="ml-2 normal-case font-normal text-muted-foreground">
                            (Synthesis 阶段必须覆盖的章节)
                        </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {CHAPTER_OPTIONS.map((opt) => {
                            const on = requiredChapters.includes(opt.key);
                            return (
                                <button
                                    type="button"
                                    key={opt.key}
                                    onClick={() => toggleChapter(opt.key)}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                                        on
                                            ? opt.color
                                            : "border-border text-muted-foreground hover:border-primary/40"
                                    }`}
                                >
                                    {opt.label}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* ─── Required Subgoals (content only) ─── */}
            {mode === "content" && (
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <FileText className="h-4 w-4 text-primary" />
                        <span className="text-xs font-semibold text-foreground uppercase tracking-wider">
                            Required Subgoals
                        </span>
                        <Badge variant="secondary" className="ml-1 text-[10px]">
                            {requiredSubgoals.length}
                        </Badge>
                    </div>
                    {loading ? (
                        <div className="text-xs text-muted-foreground py-3">
                            Loading subgoals library…
                        </div>
                    ) : subgoalsLib.length === 0 ? (
                        <div className="text-xs text-yellow-500 py-3 flex items-center gap-2">
                            <AlertTriangle className="h-3.5 w-3.5" />
                            <span>
                                geo_optimization_subgoals 为空。去{" "}
                                <a href="/framework/subgoals" className="underline">
                                    Subgoals
                                </a>{" "}
                                页面配置。
                            </span>
                        </div>
                    ) : (
                        <div className="border rounded-md max-h-56 overflow-y-auto bg-background">
                            {subgoalsLib.map((sg) => {
                                const on = requiredSubgoals.includes(sg.id);
                                return (
                                    <label
                                        key={sg.id}
                                        className="flex items-start gap-2 px-3 py-2 border-b border-border/40 last:border-b-0 cursor-pointer hover:bg-accent/30"
                                    >
                                        <Checkbox
                                            checked={on}
                                            onCheckedChange={() => toggleSubgoal(sg.id)}
                                            className="mt-0.5"
                                        />
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className="text-xs font-mono text-primary">{sg.id}</span>
                                                <span className="text-xs text-foreground">
                                                    {sg.name_zh || sg.name_en}
                                                </span>
                                            </div>
                                            {sg.description && (
                                                <div className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">
                                                    {sg.description}
                                                </div>
                                            )}
                                        </div>
                                    </label>
                                );
                            })}
                        </div>
                    )}

                    {unknownSubgoals.length > 0 && (
                        <div className="mt-2 flex items-start gap-2 text-xs text-yellow-500">
                            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
                            <div>
                                以下 subgoal_id 在当前 library 中找不到：
                                <div className="mt-1 flex flex-wrap gap-1">
                                    {unknownSubgoals.map((id) => (
                                        <Badge
                                            key={id}
                                            variant="outline"
                                            className="font-mono text-[10px] border-yellow-500/50"
                                        >
                                            {id}
                                        </Badge>
                                    ))}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* ─── Wizard Steps (visual + JSON toggle) ─── */}
            <div>
                <div className="flex items-center gap-2 mb-2">
                    <Layers className="h-4 w-4 text-primary" />
                    <span className="text-xs font-semibold text-foreground uppercase tracking-wider">
                        Wizard Steps
                    </span>
                    <span className="text-[10px] text-muted-foreground normal-case">
                        (每一步对应 SaaS wizard 的一屏 — 启用状态 + defaults)
                    </span>
                    <button
                        type="button"
                        onClick={toggleStepsJsonMode}
                        className="ml-auto text-xs text-primary hover:underline"
                    >
                        {stepsJsonMode ? "Visual Editor" : "JSON Editor"}
                    </button>
                </div>

                {stepsJsonMode ? (
                    <div>
                        <Textarea
                            rows={12}
                            value={stepsJsonText}
                            onChange={(e) => handleStepsJsonChange(e.target.value)}
                            className={`text-xs font-mono resize-y ${
                                stepsJsonError ? "border-red-500" : ""
                            }`}
                            placeholder='{"analysis_goal":{"enabled":true,"default_goal":"benchmark"},"analysis_framework":{"enabled":true,"default_lenses":["descriptive","diagnostic"]}}'
                        />
                        {stepsJsonError && (
                            <p className="text-xs text-red-400 mt-1">
                                Invalid JSON: {stepsJsonError}
                            </p>
                        )}
                        <p className="text-[10px] text-muted-foreground mt-1">
                            Shape: {"{ <step_key>: { enabled: bool, default_*: ... } }"}
                        </p>
                    </div>
                ) : (
                    <VisualStepsEditor
                        loading={loading}
                        stepsLib={stepsLib}
                        stepsObj={stepsObj}
                        refLookup={refLookup}
                        expandedKey={expandedStepKey}
                        setExpandedKey={setExpandedStepKey}
                        onToggleEnabled={toggleStepEnabled}
                        onSetStepInner={setStepInner}
                        onRemoveStep={removeStep}
                    />
                )}
            </div>

            <AdvancedTemplateConfigEditor
                config={config}
                fields={ADVANCED_CONFIG_FIELDS}
                onSetKey={setConfigKey}
                onReplaceConfig={replaceConfig}
            />
        </div>
    );
}

interface AdvancedTemplateConfigEditorProps {
    config: WizardConfig;
    fields: typeof ADVANCED_CONFIG_FIELDS;
    onSetKey: (key: string, value: unknown) => void;
    onReplaceConfig: (nextConfig: Record<string, unknown>) => void;
}

function AdvancedTemplateConfigEditor({
    config,
    fields,
    onSetKey,
    onReplaceConfig,
}: AdvancedTemplateConfigEditorProps) {
    const advancedKeys: ReadonlySet<string> = new Set(fields.map((field) => field.key));
    const otherKeys = Object.keys(config)
        .filter((key) => !VISUAL_CONFIG_KEYS.has(key) && !advancedKeys.has(key))
        .sort();

    return (
        <div className="border border-border/60 rounded-xl p-5 space-y-5 bg-muted/5">
            <div className="flex items-start gap-2">
                <FileText className="h-5 w-5 text-primary mt-0.5" />
                <div>
                    <div className="text-sm font-semibold text-foreground">
                        Advanced Template Config
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                        这些字段会直接进入最终 Prompt / Quality Gate。所有 JSON 字段都可在这里查看和编辑。
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-4">
                {fields.map((field) => (
                    <AdvancedJsonField
                        key={field.key}
                        field={field}
                        value={config[field.key]}
                        onChange={(value) => onSetKey(field.key, value)}
                    />
                ))}
            </div>

            {otherKeys.length > 0 && (
                <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3">
                    <div className="flex items-start gap-2 text-xs text-yellow-500">
                        <AlertTriangle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
                        <div>
                            还有 {otherKeys.length} 个未建模的顶层字段：
                            <span className="ml-1 font-mono">
                                {otherKeys.join(", ")}
                            </span>
                            。请在下面的完整 JSON 中查看和编辑。
                        </div>
                    </div>
                </div>
            )}

            <FullWizardConfigJsonEditor
                value={config}
                onChange={onReplaceConfig}
            />
        </div>
    );
}

interface AdvancedJsonFieldProps {
    field: (typeof ADVANCED_CONFIG_FIELDS)[number];
    value: unknown;
    onChange: (value: unknown) => void;
}

function AdvancedJsonField({ field, value, onChange }: AdvancedJsonFieldProps) {
    const [text, setText] = useState<string>(() =>
        value === undefined ? "" : JSON.stringify(value, null, 2),
    );
    const [err, setErr] = useState<string>("");

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        setText(value === undefined ? "" : JSON.stringify(value, null, 2));
        setErr("");
    }, [JSON.stringify(value)]);

    function handle(next: string) {
        setText(next);
        if (!next.trim()) {
            setErr("");
            onChange(undefined);
            return;
        }
        try {
            const parsed = JSON.parse(next);
            setErr("");
            onChange(parsed);
        } catch (e) {
            setErr((e as Error).message);
        }
    }

    return (
        <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-xs font-semibold text-foreground">
                        {field.label}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                        <span className="font-mono">{field.key}</span>
                        <span className="mx-1">·</span>
                        {field.description}
                    </div>
                </div>
            </div>
            <Textarea
                rows={field.rows}
                value={text}
                onChange={(e) => handle(e.target.value)}
                className={`text-[11px] font-mono resize-y ${
                    err ? "border-red-500" : ""
                }`}
                placeholder="{}"
            />
            {err && (
                <p className="text-[10px] text-red-400">
                    Invalid JSON: {err}
                </p>
            )}
        </div>
    );
}

interface FullWizardConfigJsonEditorProps {
    value: WizardConfig;
    onChange: (value: Record<string, unknown>) => void;
}

function FullWizardConfigJsonEditor({ value, onChange }: FullWizardConfigJsonEditorProps) {
    const [text, setText] = useState<string>(() =>
        JSON.stringify(value || {}, null, 2),
    );
    const [err, setErr] = useState<string>("");

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        setText(JSON.stringify(value || {}, null, 2));
        setErr("");
    }, [JSON.stringify(value)]);

    function handle(next: string) {
        setText(next);
        try {
            const parsed = JSON.parse(next || "{}");
            if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
                setErr("wizard_config must be a JSON object");
                return;
            }
            setErr("");
            onChange(parsed as Record<string, unknown>);
        } catch (e) {
            setErr((e as Error).message);
        }
    }

    return (
        <div className="space-y-1.5">
            <div>
                <div className="text-xs font-semibold text-foreground">
                    Full Wizard Config JSON
                </div>
                <div className="text-[10px] text-muted-foreground">
                    完整 wizard_config。用于查看和编辑没有单独建模的模板字段。
                </div>
            </div>
            <Textarea
                rows={14}
                value={text}
                onChange={(e) => handle(e.target.value)}
                className={`text-[11px] font-mono resize-y ${
                    err ? "border-red-500" : ""
                }`}
                placeholder="{}"
            />
            {err && (
                <p className="text-[10px] text-red-400">
                    Invalid JSON: {err}
                </p>
            )}
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────
// VisualStepsEditor — renders one card per workflow_step, plus any "orphan"
// keys the template has that are not in the current library. Each card
// exposes an Enabled switch and an inline JSON textarea for the step's
// default_* fields. This keeps the critical contract (enabled vs disabled)
// one click away while still allowing per-step defaults without forcing us
// to model every step's config shape up front.
// ─────────────────────────────────────────────────────────────────────────

interface VisualStepsEditorProps {
    loading: boolean;
    stepsLib: WorkflowStepLib[];
    stepsObj: Record<string, Record<string, unknown>>;
    refLookup: RefLookup;
    expandedKey: string | null;
    setExpandedKey: (key: string | null) => void;
    onToggleEnabled: (key: string) => void;
    onSetStepInner: (key: string, innerObj: Record<string, unknown>) => void;
    onRemoveStep: (key: string) => void;
}

function VisualStepsEditor({
    loading,
    stepsLib,
    stepsObj,
    refLookup,
    expandedKey,
    setExpandedKey,
    onToggleEnabled,
    onSetStepInner,
    onRemoveStep,
}: VisualStepsEditorProps) {
    if (loading) {
        return (
            <div className="text-xs text-muted-foreground py-3">
                Loading workflow steps…
            </div>
        );
    }

    // Merge library + template's current steps. Library order is authoritative
    // for known steps; orphan step_keys (present in template but not in lib)
    // trail at the bottom so the admin can remove them.
    const libKeys = new Set(stepsLib.map((s) => s.key));
    const orphans: WorkflowStepLib[] = Object.keys(stepsObj)
        .filter((k) => !libKeys.has(k))
        .map((k) => ({
            key: k,
            num: null,
            label: k,
            description: "",
            fields: [],
            orphan: true,
        }));
    const merged: WorkflowStepLib[] = [...stepsLib, ...orphans];

    if (merged.length === 0) {
        return (
            <div className="text-xs text-yellow-500 py-3 flex items-center gap-2 border border-dashed rounded-md px-3">
                <AlertTriangle className="h-3.5 w-3.5" />
                <span>
                    workflow_step config 为空。先在页面底部的 Workflow Config
                    字典里添加步骤，然后回来这里选中。
                </span>
            </div>
        );
    }

    return (
        <div className="border rounded-md bg-background divide-y divide-border/60">
            {merged.map((lib) => {
                const key = lib.key;
                const step = stepsObj[key] || {};
                const enabled = step.enabled !== false;
                const expanded = expandedKey === key;
                // Inner defaults = everything except the enabled flag
                const innerDefaults = Object.fromEntries(
                    Object.entries(step).filter(([k]) => k !== "enabled"),
                );
                const innerCount = Object.keys(innerDefaults).length;
                return (
                    <div key={key} className={lib.orphan ? "bg-yellow-500/5" : ""}>
                        {/*
                          Entire header row is a clickable region that toggles
                          expand — clicking just the tiny chevron was the bug.
                          We keep the chevron as a visual indicator, and wrap
                          the Switch area in a stopPropagation guard so
                          toggling Enable/Disable does not also collapse or
                          expand the card.
                        */}
                        <div
                            role="button"
                            tabIndex={0}
                            aria-expanded={expanded}
                            onClick={() =>
                                setExpandedKey(expanded ? null : key)
                            }
                            onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    setExpandedKey(expanded ? null : key);
                                }
                            }}
                            className="flex items-center gap-3 px-3 py-2.5 cursor-pointer select-none hover:bg-accent/20 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-inset"
                        >
                            <span
                                className="p-0.5 rounded flex-shrink-0"
                                aria-hidden="true"
                            >
                                {expanded ? (
                                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                                ) : (
                                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                                )}
                            </span>
                            {lib.num !== null && (
                                <Badge
                                    variant="outline"
                                    className="text-[10px] font-mono tabular-nums min-w-[1.75rem] justify-center"
                                >
                                    #{lib.num}
                                </Badge>
                            )}
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-sm font-medium text-foreground">
                                        {lib.label}
                                    </span>
                                    <code className="text-[10px] bg-muted text-muted-foreground px-1.5 py-0.5 rounded font-mono">
                                        {key}
                                    </code>
                                    {lib.orphan && (
                                        <Badge
                                            variant="outline"
                                            className="text-[10px] border-yellow-500/50 text-yellow-500"
                                        >
                                            orphan (not in workflow_step lib)
                                        </Badge>
                                    )}
                                    {!lib.orphan && (lib.fields?.length || 0) > 0 && (
                                        <Badge
                                            variant="outline"
                                            className="text-[10px]"
                                        >
                                            {lib.fields.length} field
                                            {lib.fields.length > 1 ? "s" : ""}
                                        </Badge>
                                    )}
                                    {innerCount > 0 && (
                                        <Badge
                                            variant="secondary"
                                            className="text-[10px]"
                                        >
                                            {innerCount} set
                                        </Badge>
                                    )}
                                </div>
                                {lib.description && !lib.orphan && (
                                    <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">
                                        {lib.description}
                                    </p>
                                )}
                            </div>
                            <div
                                className="flex items-center gap-3 flex-shrink-0"
                                onClick={(e) => e.stopPropagation()}
                                onKeyDown={(e) => e.stopPropagation()}
                            >
                                <label className="flex items-center gap-1.5 cursor-pointer text-[11px] text-muted-foreground">
                                    <Switch
                                        checked={enabled}
                                        onCheckedChange={() => onToggleEnabled(key)}
                                    />
                                    <span>
                                        {enabled ? "Enabled" : "Disabled"}
                                    </span>
                                </label>
                            </div>
                        </div>

                        {expanded && (
                            <div className="px-4 pb-4 pt-2 space-y-3 bg-muted/20">
                                <div className="flex items-center justify-between">
                                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
                                        Step Defaults
                                    </div>
                                    {Object.prototype.hasOwnProperty.call(
                                        stepsObj,
                                        key,
                                    ) && (
                                        <button
                                            type="button"
                                            onClick={() => onRemoveStep(key)}
                                            className="text-[10px] text-destructive hover:underline"
                                        >
                                            Remove step override
                                        </button>
                                    )}
                                </div>
                                <StepDefaultsEditor
                                    stepKey={key}
                                    fields={lib.fields}
                                    innerDefaults={innerDefaults}
                                    refLookup={refLookup}
                                    orphan={!!lib.orphan}
                                    onSetStepInner={onSetStepInner}
                                />
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────
// StepDefaultsEditor — schema-driven form renderer for ONE step's default_*
// fields. Reads `fields[]` from the workflow_step's value JSONB (seeded by
// migration 028) and renders a real typed control per field. No more raw
// JSON textarea for the common case; only orphan steps or unknown field
// types fall back to a compact JSON editor.
// ─────────────────────────────────────────────────────────────────────────
interface StepDefaultsEditorProps {
    stepKey: string;
    fields: FieldSchema[];
    innerDefaults: Record<string, unknown>;
    refLookup: RefLookup;
    orphan: boolean;
    onSetStepInner: (stepKey: string, innerObj: Record<string, unknown>) => void;
}

function StepDefaultsEditor({
    stepKey,
    fields,
    innerDefaults,
    refLookup,
    orphan,
    onSetStepInner,
}: StepDefaultsEditorProps) {
    // Orphan steps have no schema — give the admin a raw JSON escape hatch
    // so they can still clean up legacy data.
    if (orphan) {
        return (
            <OrphanJsonEditor
                stepKey={stepKey}
                innerDefaults={innerDefaults}
                onSetStepInner={onSetStepInner}
            />
        );
    }

    if (!Array.isArray(fields) || fields.length === 0) {
        return (
            <div className="text-[11px] text-muted-foreground italic px-1">
                This step has no default fields declared in its schema.
            </div>
        );
    }

    function updateField(fieldKey: string, value: unknown) {
        const next: Record<string, unknown> = { ...(innerDefaults || {}) };
        if (isBlankValue(value)) {
            delete next[fieldKey];
        } else {
            next[fieldKey] = value;
        }
        onSetStepInner(stepKey, next);
    }

    return (
        <div className="space-y-4">
            {fields.map((f) => (
                <FieldRenderer
                    key={f.key}
                    field={f}
                    value={innerDefaults?.[f.key]}
                    onChange={(v) => updateField(f.key, v)}
                    refLookup={refLookup}
                />
            ))}
        </div>
    );
}

function isBlankValue(v: unknown): boolean {
    if (v === undefined || v === null || v === "") return true;
    if (Array.isArray(v) && v.length === 0) return true;
    if (
        typeof v === "object" &&
        !Array.isArray(v) &&
        Object.keys(v as object).length === 0
    )
        return true;
    return false;
}

// ─────────────────────────────────────────────────────────────────────────
// FieldRenderer — dispatches to the correct control for a single field
// schema entry. Supported types: text, textarea, number, boolean,
// single_ref, multi_ref, list, json.
// ─────────────────────────────────────────────────────────────────────────
interface FieldRendererProps {
    field: FieldSchema;
    value: unknown;
    onChange: (v: unknown) => void;
    refLookup: RefLookup;
}

function FieldRenderer({ field, value, onChange, refLookup }: FieldRendererProps) {
    const labelBlock = (
        <div className="mb-1.5">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-semibold text-foreground">
                    {field.label || field.key}
                </span>
                <code className="text-[9px] bg-muted text-muted-foreground px-1 py-0.5 rounded font-mono">
                    {field.key}
                </code>
                <Badge
                    variant="outline"
                    className="text-[9px] font-mono py-0 px-1 text-muted-foreground"
                >
                    {field.type}
                </Badge>
            </div>
            {field.description && (
                <p className="text-[10px] text-muted-foreground mt-0.5">
                    {field.description}
                </p>
            )}
        </div>
    );

    switch (field.type) {
        case "text":
            return (
                <div>
                    {labelBlock}
                    <Input
                        value={(value as string) ?? ""}
                        onChange={(e) => onChange(e.target.value)}
                        className="h-8 text-xs"
                    />
                </div>
            );

        case "textarea":
            return (
                <div>
                    {labelBlock}
                    <Textarea
                        rows={field.rows || 3}
                        value={(value as string) ?? ""}
                        onChange={(e) => onChange(e.target.value)}
                        className="text-xs resize-y"
                    />
                </div>
            );

        case "number":
            return (
                <div>
                    {labelBlock}
                    <Input
                        type="number"
                        value={(value as number) ?? ""}
                        onChange={(e) => {
                            const raw = e.target.value;
                            if (raw === "") {
                                onChange(undefined);
                            } else {
                                const n = Number(raw);
                                onChange(Number.isNaN(n) ? undefined : n);
                            }
                        }}
                        className="h-8 text-xs w-36"
                    />
                </div>
            );

        case "boolean":
            return (
                <div className="flex items-start gap-3">
                    <Switch
                        checked={value === true}
                        onCheckedChange={(v) => onChange(v)}
                        className="mt-0.5"
                    />
                    <div className="flex-1">{labelBlock}</div>
                </div>
            );

        case "single_ref": {
            const opts = (field.ref_config_type ? refLookup?.[field.ref_config_type] : []) || [];
            const selectValue = (value as string) ?? "__unset__";
            return (
                <div>
                    {labelBlock}
                    {opts.length === 0 ? (
                        <div className="text-[10px] text-yellow-500 flex items-center gap-1.5 border border-yellow-500/30 bg-yellow-500/5 rounded px-2 py-1.5">
                            <AlertTriangle className="h-3 w-3" />
                            No options for config_type "{field.ref_config_type}"
                            — seed it in the Workflow Config dictionary first.
                        </div>
                    ) : (
                        <Select
                            value={selectValue}
                            onValueChange={(v) =>
                                onChange(v === "__unset__" ? undefined : v)
                            }
                        >
                            <SelectTrigger className="h-8 text-xs">
                                <SelectValue placeholder="未设置" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="__unset__">
                                    <span className="italic text-muted-foreground">
                                        未设置
                                    </span>
                                </SelectItem>
                                {opts.map((o) => (
                                    <SelectItem key={o.key} value={o.key}>
                                        <span className="inline-flex items-center gap-1.5">
                                            <IconFromName name={o.icon} />
                                            <span>{o.label || o.key}</span>
                                            <code className="text-[9px] text-muted-foreground font-mono">
                                                {o.key}
                                            </code>
                                        </span>
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    )}
                </div>
            );
        }

        case "multi_ref": {
            const opts = (field.ref_config_type ? refLookup?.[field.ref_config_type] : []) || [];
            const cur = Array.isArray(value) ? (value as string[]) : [];
            return (
                <div>
                    {labelBlock}
                    {opts.length === 0 ? (
                        <div className="text-[10px] text-yellow-500 flex items-center gap-1.5 border border-yellow-500/30 bg-yellow-500/5 rounded px-2 py-1.5">
                            <AlertTriangle className="h-3 w-3" />
                            No options for config_type "{field.ref_config_type}"
                            — seed it in the Workflow Config dictionary first.
                        </div>
                    ) : (
                        <div className="border rounded-md bg-background max-h-48 overflow-y-auto">
                            {opts.map((o) => {
                                const on = cur.includes(o.key);
                                return (
                                    <label
                                        key={o.key}
                                        className="flex items-start gap-2 px-2.5 py-1.5 border-b border-border/40 last:border-b-0 cursor-pointer hover:bg-accent/30"
                                    >
                                        <Checkbox
                                            checked={on}
                                            onCheckedChange={() => {
                                                const next = on
                                                    ? cur.filter(
                                                          (x) => x !== o.key,
                                                      )
                                                    : [...cur, o.key];
                                                onChange(next);
                                            }}
                                            className="mt-0.5"
                                        />
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-1.5 flex-wrap">
                                                <IconFromName
                                                    name={o.icon}
                                                    className="h-3 w-3 text-muted-foreground"
                                                />
                                                <span className="text-xs font-medium text-foreground">
                                                    {o.label || o.key}
                                                </span>
                                                <code className="text-[9px] text-muted-foreground font-mono">
                                                    {o.key}
                                                </code>
                                            </div>
                                            {o.description && (
                                                <p className="text-[10px] text-muted-foreground line-clamp-1 mt-0.5">
                                                    {o.description}
                                                </p>
                                            )}
                                        </div>
                                    </label>
                                );
                            })}
                        </div>
                    )}
                    {cur.length > 0 && (
                        <div className="text-[10px] text-muted-foreground mt-1">
                            {cur.length} selected
                        </div>
                    )}
                    {/* Surface any selected keys not present in the current
                        library so admins notice if an option was removed. */}
                    {(() => {
                        const known = new Set(opts.map((o) => o.key));
                        const unknown = cur.filter((k) => !known.has(k));
                        if (unknown.length === 0) return null;
                        return (
                            <div className="mt-1.5 flex flex-wrap gap-1 items-center">
                                <AlertTriangle className="h-3 w-3 text-yellow-500" />
                                <span className="text-[10px] text-yellow-500">
                                    unknown:
                                </span>
                                {unknown.map((k) => (
                                    <Badge
                                        key={k}
                                        variant="outline"
                                        className="font-mono text-[9px] border-yellow-500/50"
                                    >
                                        {k}
                                    </Badge>
                                ))}
                            </div>
                        );
                    })()}
                </div>
            );
        }

        case "list":
            return (
                <ListFieldEditor
                    field={field}
                    value={value}
                    onChange={onChange}
                    refLookup={refLookup}
                    labelBlock={labelBlock}
                />
            );

        case "json":
            return (
                <InlineJsonEditor
                    field={field}
                    value={value}
                    onChange={onChange}
                    labelBlock={labelBlock}
                />
            );

        // ── Custom field types ──────────────────────────────────
        // These render rich widgets in the SaaS wizard but here in the
        // admin we just show the type badge + an inline JSON editor so
        // admins can tweak default values when needed.
        case "chart_builder":
        case "prompt_editor":
        case "peer_picker":
        case "analyzer_import":
        case "strategy_generator":
        case "product_facts_form":
        case "prompt_ref_picker":
        case "reddit_discovery_config":
        case "official_website_discovery_config":
        case "citation_analysis_preflight":
        case "subreddit_targeting_preflight":
        case "reddit_discovery_preflight":
        case "prompt_artifact_preparation_preflight":
        case "metric_ref_multi":
        case "platform_picker":
            return (
                <InlineJsonEditor
                    field={field}
                    value={value}
                    onChange={onChange}
                    labelBlock={labelBlock}
                />
            );

        default:
            return (
                <div className="text-[11px] text-red-400 border border-red-500/30 bg-red-500/5 rounded px-2 py-1.5">
                    Unknown field type <code className="font-mono">{field.type}</code>
                    {" "}for key <code className="font-mono">{field.key}</code>
                </div>
            );
    }
}

// ─────────────────────────────────────────────────────────────────────────
// ListFieldEditor — renders an array of objects where each item follows
// `field.item_fields[]`. Supports add / remove / reorder-free editing.
// ─────────────────────────────────────────────────────────────────────────
interface ListFieldEditorProps {
    field: FieldSchema;
    value: unknown;
    onChange: (v: unknown) => void;
    refLookup: RefLookup;
    labelBlock: React.ReactNode;
}

function ListFieldEditor({ field, value, onChange, refLookup, labelBlock }: ListFieldEditorProps) {
    const items: Record<string, unknown>[] = Array.isArray(value)
        ? (value as Record<string, unknown>[])
        : [];
    const itemFields: FieldSchema[] = Array.isArray(field.item_fields) ? field.item_fields : [];

    function addItem() {
        onChange([...items, {}]);
    }
    function updateItem(idx: number, fieldKey: string, fieldValue: unknown) {
        const next = items.map((it, i) => {
            if (i !== idx) return it;
            const copy: Record<string, unknown> = { ...(it || {}) };
            if (isBlankValue(fieldValue)) {
                delete copy[fieldKey];
            } else {
                copy[fieldKey] = fieldValue;
            }
            return copy;
        });
        onChange(next);
    }
    function removeItem(idx: number) {
        onChange(items.filter((_, i) => i !== idx));
    }

    return (
        <div>
            <div className="flex items-center gap-2 mb-1.5">
                {labelBlock}
                <Badge variant="secondary" className="text-[9px] ml-auto">
                    {items.length} item{items.length === 1 ? "" : "s"}
                </Badge>
            </div>

            {itemFields.length === 0 && (
                <div className="text-[10px] text-yellow-500 flex items-center gap-1.5 border border-yellow-500/30 bg-yellow-500/5 rounded px-2 py-1.5 mb-2">
                    <AlertTriangle className="h-3 w-3" />
                    No item_fields declared in schema — cannot edit list items.
                </div>
            )}

            <div className="space-y-2">
                {items.map((item, idx) => (
                    <div
                        key={idx}
                        className="border rounded-md p-3 bg-background space-y-3"
                    >
                        <div className="flex items-center justify-between">
                            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                                Item #{idx + 1}
                            </div>
                            <button
                                type="button"
                                onClick={() => removeItem(idx)}
                                className="p-1 rounded hover:bg-destructive/10 text-red-400 hover:text-red-300"
                                title="Remove item"
                            >
                                <Trash2 className="h-3 w-3" />
                            </button>
                        </div>
                        {itemFields.map((sub) => (
                            <FieldRenderer
                                key={sub.key}
                                field={sub}
                                value={item?.[sub.key]}
                                onChange={(v) => updateItem(idx, sub.key, v)}
                                refLookup={refLookup}
                            />
                        ))}
                    </div>
                ))}

                {itemFields.length > 0 && (
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={addItem}
                        className="w-full gap-1.5 h-8 text-[11px]"
                    >
                        <Plus className="h-3 w-3" /> Add item
                    </Button>
                )}
            </div>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────
// InlineJsonEditor — escape hatch for fields declared as type:"json".
// Local text state + live-validate; only pushes up when valid.
// ─────────────────────────────────────────────────────────────────────────
interface InlineJsonEditorProps {
    field: FieldSchema;
    value: unknown;
    onChange: (v: unknown) => void;
    labelBlock: React.ReactNode;
}

function InlineJsonEditor({ field, value, onChange, labelBlock }: InlineJsonEditorProps) {
    const [text, setText] = useState<string>(() =>
        value === undefined ? "" : JSON.stringify(value, null, 2),
    );
    const [err, setErr] = useState<string>("");

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        setText(value === undefined ? "" : JSON.stringify(value, null, 2));
        setErr("");
    }, [JSON.stringify(value)]);

    function handle(next: string) {
        setText(next);
        if (!next.trim()) {
            setErr("");
            onChange(undefined);
            return;
        }
        try {
            const parsed = JSON.parse(next);
            setErr("");
            onChange(parsed);
        } catch (e) {
            setErr((e as Error).message);
        }
    }

    return (
        <div>
            {labelBlock}
            <Textarea
                rows={field.rows || 4}
                value={text}
                onChange={(e) => handle(e.target.value)}
                className={`text-[11px] font-mono resize-y ${
                    err ? "border-red-500" : ""
                }`}
                placeholder="{}"
            />
            {err && (
                <p className="text-[10px] text-red-400 mt-1">
                    Invalid JSON: {err}
                </p>
            )}
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────
// OrphanJsonEditor — raw JSON editor used only for "orphan" steps (keys
// present in the template's wizard_config but not in the workflow_step
// library). These have no schema to drive a form, so JSON is the only way
// to clean up legacy data before removing the override.
// ─────────────────────────────────────────────────────────────────────────
interface OrphanJsonEditorProps {
    stepKey: string;
    innerDefaults: Record<string, unknown>;
    onSetStepInner: (stepKey: string, innerObj: Record<string, unknown>) => void;
}

function OrphanJsonEditor({ stepKey, innerDefaults, onSetStepInner }: OrphanJsonEditorProps) {
    const [text, setText] = useState<string>(() =>
        JSON.stringify(innerDefaults || {}, null, 2),
    );
    const [err, setErr] = useState<string>("");

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        setText(JSON.stringify(innerDefaults || {}, null, 2));
        setErr("");
    }, [stepKey, JSON.stringify(innerDefaults)]);

    function handle(next: string) {
        setText(next);
        if (!next.trim()) {
            setErr("");
            onSetStepInner(stepKey, {});
            return;
        }
        try {
            const parsed = JSON.parse(next);
            if (typeof parsed !== "object" || Array.isArray(parsed)) {
                setErr("must be a JSON object");
                return;
            }
            if ("enabled" in parsed) delete parsed.enabled;
            setErr("");
            onSetStepInner(stepKey, parsed);
        } catch (e) {
            setErr((e as Error).message);
        }
    }

    return (
        <div>
            <div className="text-[10px] text-yellow-500 flex items-center gap-1.5 mb-1.5">
                <AlertTriangle className="h-3 w-3" />
                Orphan step — raw JSON only. Consider removing this override.
            </div>
            <Textarea
                rows={5}
                value={text}
                onChange={(e) => handle(e.target.value)}
                className={`text-[11px] font-mono resize-y ${
                    err ? "border-red-500" : ""
                }`}
                placeholder="{}"
            />
            {err && (
                <p className="text-[10px] text-red-400 mt-1">
                    Invalid JSON: {err}
                </p>
            )}
        </div>
    );
}
