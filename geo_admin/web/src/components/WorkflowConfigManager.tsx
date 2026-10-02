/**
 * WorkflowConfigManager
 *
 * Section embedded at the bottom of Report/Content Templates pages. This is the
 * system-wide option dictionary for `geo_workflow_config` — it drives every
 * template's wizard form (goal / platform / depth / content_type / depth /
 * analysis_lens / content_metric / content_sub_goal / ...). Adding an item
 * here makes it immediately visible in every template's dropdown in the
 * SaaS wizard.
 *
 * Design notes vs. the old inline-form version:
 *
 *  1. Per-config-type form schemas (CONFIG_TYPE_META below). The previous
 *     version only knew about {label, icon, description} and silently dropped
 *     every other field on save/edit. That caused data-loss bugs for goals
 *     (recommended_types, recommended_domains, default_sort), workflow_steps
 *     (num), domains (color, label_zh), etc. Now each config_type declares
 *     its own field list and we render + save only those fields.
 *
 *  2. Dialog-based CRUD instead of an inline form. Matches the direction of
 *     the Templates pages (Task #24) and keeps the list uncluttered.
 *
 *  3. Scope resolution is implicit. Each config_type declares which scopes it
 *     belongs in (shared / analysis / content_generation); we derive the
 *     correct scope automatically based on the config_type + parent page.
 *
 *  4. Two-level dictionaries (config_types with `hasParentKey: true`, e.g.
 *     content_sub_goal under content_metric) store their parent link in the
 *     `parent_key` top-level column, not inside `value`.
 */
import { useState, useEffect, useMemo } from "react";
import { useConfirm } from "@/components/Toast";
import {
    getWorkflowConfig,
    createWorkflowConfig,
    updateWorkflowConfig,
    deleteWorkflowConfig,
} from "../api/client";
import {
    parseWorkflowConfigValue,
    type WorkflowConfigGroupedOut,
    type WorkflowConfigItem,
} from "../lib/workflowConfig";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from "@/components/ui/dialog";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import {
    Library,
    Plus,
    Pencil,
    Trash2,
    Save,
    X,
    Loader2,
    PowerOff,
    Power,
} from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────
// Schemas
//
// Ordered list of config_types we know how to render. Any config_type the
// backend returns that is not in this map falls through to a minimal
// {label} schema so admins can still edit legacy data without crashing.
// ─────────────────────────────────────────────────────────────────────────

type FieldType = "text" | "number" | "textarea" | "json" | "list";

interface FieldDef {
    key: string;
    label: string;
    type: FieldType;
    required?: boolean;
    rows?: number;
    placeholder?: string;
    description?: string;
}

interface ConfigTypeMeta {
    label_en: string;
    label_zh: string;
    description: string;
    scopes: string[];
    fields: FieldDef[];
    hasParentKey?: boolean;
}

const CONFIG_TYPE_META: Record<string, ConfigTypeMeta> = {
    workflow_step: {
        label_en: "Workflow Step",
        label_zh: "向导步骤",
        description:
            "SaaS 向导里的步骤（按 num 排序）。每个步骤通过 fields[] 声明它感知的表单字段 —— 模板只负责 enable/disable + 填默认值。",
        scopes: ["analysis", "content_generation"],
        fields: [
            { key: "num", label: "Step Number", type: "number", required: true },
            { key: "label", label: "Display Name (中文)", type: "text", required: true },
            { key: "description", label: "Description", type: "text" },
            {
                key: "fields",
                label: "Sensed Field Schema",
                type: "json",
                rows: 14,
                placeholder:
                    '[\n  {\n    "key": "default_domains",\n    "label": "默认数据领域",\n    "type": "multi_ref",\n    "ref_config_type": "domain",\n    "ref_scope": "shared"\n  }\n]',
                description:
                    "每个元素描述这一步感知的一个字段。支持 text / textarea / number / single_ref / multi_ref / list。这里存的是 schema-of-schema，所以仍需手写 JSON（workflow_config 里剩下的唯一一处 JSON）。",
            },
        ],
    },
    domain: {
        label_en: "Data Domain",
        label_zh: "数据领域",
        description: "Visibility / Citation / Sentiment 三个核心领域的展示元数据。",
        scopes: ["shared"],
        fields: [
            { key: "icon", label: "Icon (emoji)", type: "text" },
            {
                key: "color",
                label: "Color (Tailwind classes)",
                type: "text",
                placeholder:
                    "e.g. bg-blue-500/10 text-blue-400 border-blue-500/30",
            },
            { key: "label", label: "Label (EN)", type: "text", required: true },
            { key: "label_zh", label: "Label (ZH)", type: "text" },
        ],
    },
    platform: {
        label_en: "AI Platform",
        label_zh: "AI 平台",
        description: "可配置 AI 平台的注册表。",
        scopes: ["shared"],
        fields: [
            { key: "icon", label: "Icon (emoji)", type: "text" },
            { key: "color", label: "Color (Tailwind classes)", type: "text" },
            { key: "label", label: "Label", type: "text", required: true },
        ],
    },
    depth: {
        label_en: "Depth",
        label_zh: "深度",
        description: "快速 / 标准 / 深度运行档位。",
        scopes: ["analysis", "content_generation"],
        fields: [
            { key: "icon", label: "Icon (emoji)", type: "text" },
            { key: "label", label: "Label", type: "text", required: true },
            { key: "description", label: "Description", type: "text" },
        ],
    },
    goal: {
        label_en: "Goal",
        label_zh: "目标",
        description:
            "业务目标。Analysis 下是分析视角（竞品对标 / 趋势诊断 ...）；Content 下是内容目标（可见度提升 / 引用优化 ...）。",
        scopes: ["analysis", "content_generation"],
        fields: [
            { key: "icon", label: "Icon (emoji)", type: "text" },
            { key: "color", label: "Color (Tailwind classes)", type: "text" },
            { key: "label", label: "Label", type: "text", required: true },
            { key: "description", label: "Description", type: "textarea", rows: 3 },
            {
                key: "default_sort",
                label: "Default Sort Key",
                type: "text",
                placeholder: "e.g. visibility",
            },
            {
                key: "recommended_types",
                label: "Recommended Content Types",
                type: "list",
                placeholder: "comma-separated, e.g. faq, aeo_article",
            },
            {
                key: "recommended_domains",
                label: "Recommended Data Domains",
                type: "list",
                placeholder: "comma-separated, e.g. visibility, citation",
            },
        ],
    },
    content_type: {
        label_en: "Content Type",
        label_zh: "内容类型",
        description: "FAQ / Article / Brief / Recommendations 等内容形态。",
        scopes: ["content_generation"],
        fields: [
            { key: "icon", label: "Icon (emoji)", type: "text" },
            { key: "label", label: "Label", type: "text", required: true },
            { key: "description", label: "Description", type: "text" },
        ],
    },
    sort_option: {
        label_en: "Sort Option",
        label_zh: "排序选项",
        description: "Content 列表页可选的排序维度。",
        scopes: ["content_generation"],
        fields: [{ key: "label", label: "Label", type: "text", required: true }],
    },
    chart_type: {
        label_en: "Chart Type",
        label_zh: "图表类型",
        description:
            "NL Query 生成图表时可选的图表形态。被 analysis 向导的 chart_config 步骤引用。",
        scopes: ["shared"],
        fields: [
            { key: "icon", label: "Icon (emoji)", type: "text" },
            { key: "label", label: "Label", type: "text", required: true },
            { key: "description", label: "Description", type: "text" },
        ],
    },
    date_range: {
        label_en: "Date Range",
        label_zh: "时间范围",
        description:
            "向导 data_selection 步骤的时间窗口选项（例如 last_7d / last_30d）。",
        scopes: ["shared"],
        fields: [
            { key: "label", label: "Label", type: "text", required: true },
            { key: "description", label: "Description", type: "text" },
        ],
    },
    analysis_lens: {
        label_en: "Analysis Lens (Gartner DDPP)",
        label_zh: "分析视角 (DDPP)",
        description:
            "Gartner 四级分析法：Descriptive / Diagnostic / Predictive / Prescriptive。被 analysis 向导的 analysis_framework 步骤引用，pipeline 把选中的 lens 作为硬约束注入报告生成 prompt。",
        scopes: ["analysis"],
        fields: [
            { key: "icon", label: "Icon (Lucide name)", type: "text" },
            { key: "color", label: "Color (Tailwind classes)", type: "text" },
            {
                key: "label",
                label: "Label (中文 + English)",
                type: "text",
                required: true,
                placeholder: "e.g. 描述性分析 (Descriptive)",
            },
            {
                key: "description",
                label: "Description",
                type: "textarea",
                rows: 3,
            },
        ],
    },
    content_metric: {
        label_en: "Content Metric (RATF)",
        label_zh: "内容质量维度 (RATF)",
        description:
            "内容质量顶层维度：Readability / Answerability / Trustworthy / Freshness。被 content 向导的 content_framework 步骤引用，pipeline 把选中的 metric 作为硬约束注入内容生成 prompt。",
        scopes: ["content_generation"],
        fields: [
            { key: "icon", label: "Icon (Lucide name)", type: "text" },
            { key: "color", label: "Color (Tailwind classes)", type: "text" },
            {
                key: "label",
                label: "Label (中文 + English)",
                type: "text",
                required: true,
                placeholder: "e.g. 可读性 (Readability)",
            },
            {
                key: "description",
                label: "Description",
                type: "textarea",
                rows: 3,
            },
        ],
    },
    content_sub_goal: {
        label_en: "Content Sub-Goal",
        label_zh: "内容质量子目标",
        description:
            "RATF 子目标（二级）。每个子目标通过 parent_key 绑定到一个 content_metric。e.g. content_understandability 的 parent_key 是 readability。",
        scopes: ["content_generation"],
        hasParentKey: true,
        fields: [
            {
                key: "label",
                label: "Label (中文 + English)",
                type: "text",
                required: true,
                placeholder: "e.g. 机器可读性 (Machine Readability)",
            },
            {
                key: "description",
                label: "Description",
                type: "textarea",
                rows: 3,
            },
        ],
    },
};

const FALLBACK_META: ConfigTypeMeta = {
    label_en: "", // filled in dynamically from the key itself
    label_zh: "",
    description: "未知 config_type — 使用最小编辑器，所有字段以 JSON 文本形式编辑。",
    scopes: ["analysis", "content_generation", "shared"],
    fields: [{ key: "label", label: "Label", type: "text", required: true }],
};

function getMeta(configType: string): ConfigTypeMeta {
    if (CONFIG_TYPE_META[configType]) return CONFIG_TYPE_META[configType];
    return {
        ...FALLBACK_META,
        label_en: configType || "Unknown",
        label_zh: configType || "未知",
    };
}

// Order in which config_type groups are rendered. Known types first (in this
// order), then any unknown types at the bottom.
const KNOWN_TYPE_ORDER: string[] = [
    "workflow_step",
    "domain",
    "platform",
    "depth",
    "goal",
    "analysis_lens",
    "content_metric",
    "content_sub_goal",
    "content_type",
    "sort_option",
    "chart_type",
    "date_range",
];

// ─────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────

type ValueDict = Record<string, unknown>;

/** Build the initial form state for a given config_type + existing value. */
function buildFormValue(meta: ConfigTypeMeta, existing: ValueDict = {}): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const f of meta.fields) {
        const cur = existing[f.key];
        if (f.type === "list") {
            out[f.key] = Array.isArray(cur) ? (cur as unknown[]).join(", ") : cur || "";
        } else if (f.type === "json") {
            // JSON fields store their data as a parsed object/array in the DB
            // but the form holds a pretty-printed text for editing.
            if (cur === undefined || cur === null) {
                out[f.key] = "";
            } else if (typeof cur === "string") {
                out[f.key] = cur;
            } else {
                out[f.key] = JSON.stringify(cur, null, 2);
            }
        } else if (f.type === "number") {
            out[f.key] = cur ?? "";
        } else {
            out[f.key] = cur ?? "";
        }
    }
    return out;
}

/**
 * Serialize a form value map back into the DB `value` dict.
 * Returns { value, errors } where errors is a map of field_key → message
 * for any field that failed serialization (e.g. invalid JSON).
 */
function serializeFormValue(
    meta: ConfigTypeMeta,
    formValue: Record<string, unknown>,
): { value: ValueDict; errors: Record<string, string> } {
    const out: ValueDict = {};
    const errors: Record<string, string> = {};
    for (const f of meta.fields) {
        const v = formValue[f.key];
        if (f.type === "list") {
            const arr = ((v as string) || "")
                .split(",")
                .map((s: string) => s.trim())
                .filter(Boolean);
            if (arr.length > 0) out[f.key] = arr;
        } else if (f.type === "json") {
            const s = (v ?? "").toString().trim();
            if (!s) {
                // Empty string → omit, unless required
                if (f.required) errors[f.key] = "Required.";
                continue;
            }
            try {
                out[f.key] = JSON.parse(s);
            } catch (err) {
                errors[f.key] = `Invalid JSON: ${(err as Error).message}`;
            }
        } else if (f.type === "number") {
            if (v !== "" && v !== null && v !== undefined) {
                const n = Number(v);
                if (!Number.isNaN(n)) out[f.key] = n;
            }
        } else {
            const s = (v ?? "").toString().trim();
            if (s) out[f.key] = s;
        }
    }
    return { value: out, errors };
}

function scopeBadgeClass(scope: string): string {
    if (scope === "shared")
        return "bg-slate-500/10 text-slate-400 border-slate-500/30";
    if (scope === "analysis")
        return "bg-blue-500/10 text-blue-400 border-blue-500/30";
    if (scope === "content_generation")
        return "bg-purple-500/10 text-purple-400 border-purple-500/30";
    return "bg-muted text-muted-foreground border-border";
}

// ─────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────

interface WorkflowConfigManagerProps {
    scope: string;
    onConfigChange?: () => void;
}

export default function WorkflowConfigManager({ scope, onConfigChange }: WorkflowConfigManagerProps) {
    const confirm = useConfirm();
    const [config, setConfig] = useState<WorkflowConfigGroupedOut>({});
    const [loading, setLoading] = useState<boolean>(false);

    // Dialog state
    const [dialogOpen, setDialogOpen] = useState<boolean>(false);
    const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
    const [editItemId, setEditItemId] = useState<string | null>(null);
    const [saving, setSaving] = useState<boolean>(false);

    // Form fields
    const [formType, setFormType] = useState<string>(""); // config_type
    const [formKey, setFormKey] = useState<string>("");
    const [formParentKey, setFormParentKey] = useState<string>("");
    const [formOrder, setFormOrder] = useState<number>(0);
    const [formValue, setFormValue] = useState<Record<string, unknown>>({}); // dynamic per-type
    const [formErrors, setFormErrors] = useState<Record<string, string>>({}); // field_key → error message

    const currentMeta = useMemo(() => getMeta(formType), [formType]);

    useEffect(() => {
        loadConfig();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [scope]);

    async function loadConfig(): Promise<void> {
        setLoading(true);
        try {
            const data = await getWorkflowConfig(scope);
            setConfig(data);
            if (onConfigChange) onConfigChange();
        } catch {
            setConfig({});
        } finally {
            setLoading(false);
        }
    }

    function openCreate(configType: string) {
        const meta = getMeta(configType);
        setDialogMode("create");
        setEditItemId(null);
        setFormType(configType);
        setFormKey("");
        setFormParentKey("");
        setFormOrder(0);
        setFormValue(buildFormValue(meta, {}));
        setFormErrors({});
        setDialogOpen(true);
    }

    function openEdit(item: WorkflowConfigItem) {
        const meta = getMeta(item.config_type);
        if (!item.id) return;
        const v = parseWorkflowConfigValue(item.value);
        setDialogMode("edit");
        setEditItemId(item.id);
        setFormType(item.config_type);
        setFormKey(item.key);
        setFormParentKey(item.parent_key || "");
        setFormOrder(item.sort_order || 0);
        setFormValue(buildFormValue(meta, v));
        setFormErrors({});
        setDialogOpen(true);
    }

    function closeDialog() {
        setDialogOpen(false);
        setEditItemId(null);
        setFormErrors({});
    }

    function setField(key: string, v: unknown) {
        setFormValue((prev) => ({ ...prev, [key]: v }));
        // Clear an error for this field as soon as the user edits it — it'll
        // be re-validated on the next save attempt.
        if (formErrors[key]) {
            setFormErrors((prev) => {
                const next = { ...prev };
                delete next[key];
                return next;
            });
        }
    }

    /** Resolve the scope for a new item given its config_type. */
    function resolveScope(configType: string): string {
        const meta = getMeta(configType);
        if (meta.scopes.includes(scope)) return scope;
        if (meta.scopes.includes("shared")) return "shared";
        return meta.scopes[0] || scope;
    }

    async function handleSave(): Promise<void> {
        // Validate required fields (text / number / list)
        const nextErrors: Record<string, string> = {};
        for (const f of currentMeta.fields) {
            if (f.required && f.type !== "json" && !formValue[f.key]) {
                nextErrors[f.key] = "Required.";
            }
        }
        if (dialogMode === "create" && !formKey.trim()) {
            nextErrors.__key__ = "Key is required.";
        }

        const { value: serialized, errors: serializeErrors } =
            serializeFormValue(currentMeta, formValue);
        Object.assign(nextErrors, serializeErrors);

        if (Object.keys(nextErrors).length > 0) {
            setFormErrors(nextErrors);
            return;
        }

        setSaving(true);
        try {
            if (dialogMode === "create") {
                await createWorkflowConfig({
                    config_type: formType,
                    scope: resolveScope(formType),
                    key: formKey.trim(),
                    parent_key: currentMeta.hasParentKey
                        ? formParentKey.trim() || null
                        : null,
                    value: serialized,
                    sort_order: Number(formOrder) || 0,
                });
            } else if (editItemId) {
                const payload: Record<string, unknown> = {
                    value: serialized,
                    sort_order: Number(formOrder) || 0,
                };
                if (currentMeta.hasParentKey) {
                    payload.parent_key = formParentKey.trim() || null;
                }
                await updateWorkflowConfig(editItemId, payload);
            }
            closeDialog();
            loadConfig();
        } catch (err) {
            setFormErrors({ __save__: (err as Error)?.message || "Save failed" });
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete(item: WorkflowConfigItem): Promise<void> {
        const meta = getMeta(item.config_type);
        if (!item.id) return;
        const v = parseWorkflowConfigValue(item.value);
        const label = (v.label as string) || item.key;
        const ok = await confirm(
            `Delete "${label}" from ${meta.label_en}?`,
            "Delete Config Item",
        );
        if (!ok) return;
        try {
            await deleteWorkflowConfig(item.id);
            loadConfig();
        } catch {
            // silent
        }
    }

    async function handleToggle(item: WorkflowConfigItem): Promise<void> {
        if (!item.id) return;
        try {
            await updateWorkflowConfig(item.id, { is_active: !item.is_active });
            loadConfig();
        } catch {
            // silent
        }
    }

    // Ordered list of config_types to render: known types in declared order,
    // then any extra (legacy / unknown) types at the bottom.
    const renderOrder = useMemo<string[]>(() => {
        const present = Object.keys(config);
        const known = KNOWN_TYPE_ORDER.filter((k) => present.includes(k));
        const unknown = present.filter((k) => !KNOWN_TYPE_ORDER.includes(k));
        // Always include known types even if empty — admins still need the "Add"
        // button for types that have no rows yet (e.g. a brand-new sort_option).
        for (const k of KNOWN_TYPE_ORDER) {
            if (!known.includes(k)) {
                const meta = getMeta(k);
                if (meta.scopes.includes(scope) || meta.scopes.includes("shared")) {
                    known.push(k);
                }
            }
        }
        // Preserve original order
        const finalOrder: string[] = [];
        for (const k of KNOWN_TYPE_ORDER) {
            if (known.includes(k)) finalOrder.push(k);
        }
        return [...finalOrder, ...unknown];
    }, [config, scope]);

    return (
        <div className="bg-card border rounded-xl shadow-sm">
            {/* Section header */}
            <div className="px-6 py-5 border-b border-border">
                <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5 p-2 rounded-lg bg-primary/10">
                        <Library className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <h3 className="text-lg font-bold text-foreground">
                                工作流配置字典
                            </h3>
                            <span className="text-xs text-muted-foreground">
                                (Workflow Config · System-wide Option Registry)
                            </span>
                            <span
                                className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${scopeBadgeClass(
                                    scope,
                                )}`}
                            >
                                scope: {scope}
                            </span>
                        </div>
                        <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
                            这是系统里所有模板共用的选项字典。在这里新增的
                            <strong className="text-foreground"> goal / platform / depth </strong>
                            会立刻被所有模板的表单 dropdown 看到 ——
                            不需要改代码，也不需要重新部署。<br />
                            按 <code className="text-[11px] bg-muted px-1 rounded">config_type</code> 分组展示，支持增删改 + 启停切换。
                        </p>
                    </div>
                </div>
            </div>

            {/* Groups */}
            <div className="p-6 space-y-6">
                {loading ? (
                    <div className="flex items-center justify-center py-8">
                        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                    </div>
                ) : renderOrder.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-4">
                        No config items found for scope "{scope}".
                    </p>
                ) : (
                    renderOrder.map((ct) => {
                        const meta = getMeta(ct);
                        const items = config[ct] || [];
                        return (
                            <div key={ct} className="space-y-2">
                                {/* Group header */}
                                <div className="flex items-center justify-between gap-3">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <h4 className="text-sm font-semibold text-foreground">
                                                {meta.label_zh}
                                            </h4>
                                            <span className="text-[11px] text-muted-foreground uppercase tracking-wider">
                                                {meta.label_en}
                                            </span>
                                            <code className="text-[10px] bg-muted text-muted-foreground px-1.5 py-0.5 rounded font-mono">
                                                {ct}
                                            </code>
                                            {items.length > 0 && (
                                                <span className="text-[10px] text-muted-foreground">
                                                    {items.length} item
                                                    {items.length > 1 ? "s" : ""}
                                                </span>
                                            )}
                                        </div>
                                        {meta.description && (
                                            <p className="text-xs text-muted-foreground mt-0.5">
                                                {meta.description}
                                            </p>
                                        )}
                                    </div>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="h-8 gap-1 flex-shrink-0"
                                        onClick={() => openCreate(ct)}
                                    >
                                        <Plus className="h-3.5 w-3.5" />
                                        Add
                                    </Button>
                                </div>

                                {/* Rows */}
                                {items.length === 0 ? (
                                    <div className="text-xs text-muted-foreground italic px-3 py-3 border border-dashed border-border rounded-md">
                                        No {meta.label_en.toLowerCase()} items yet — click Add to create one.
                                    </div>
                                ) : (
                                    <div className="border border-border/60 rounded-md divide-y divide-border/60 bg-background">
                                        {[...items]
                                            .sort((a, b) => {
                                                // workflow_step rows sort by value.num, everything else by sort_order
                                                if (ct === "workflow_step") {
                                                    const na = (parseWorkflowConfigValue(a.value).num as number) ?? 0;
                                                    const nb = (parseWorkflowConfigValue(b.value).num as number) ?? 0;
                                                    if (na !== nb) return na - nb;
                                                }
                                                return (a.sort_order || 0) - (b.sort_order || 0);
                                            })
                                            .map((item) => {
                                            const v = parseWorkflowConfigValue(item.value);
                                            const fieldCount = Array.isArray(v.fields) ? (v.fields as unknown[]).length : 0;
                                            return (
                                                <div
                                                    key={item.id || `${item.config_type}:${item.key}`}
                                                    className="flex items-center gap-3 px-3 py-2 hover:bg-accent/20 group"
                                                >
                                                    {ct === "workflow_step" && v.num != null ? (
                                                        <Badge
                                                            variant="outline"
                                                            className="text-[11px] font-mono tabular-nums min-w-[2rem] justify-center flex-shrink-0 border-primary/40 text-primary"
                                                        >
                                                            #{v.num as number}
                                                        </Badge>
                                                    ) : v.icon ? (
                                                        <span className="text-base flex-shrink-0">
                                                            {v.icon as string}
                                                        </span>
                                                    ) : null}
                                                    <div className="flex-1 min-w-0">
                                                        <div className="flex items-center gap-2 flex-wrap">
                                                            <span className="text-sm font-medium text-foreground">
                                                                {(v.label as string) || item.key}
                                                            </span>
                                                            <Badge
                                                                variant="outline"
                                                                className="text-[10px] font-mono"
                                                            >
                                                                {item.key}
                                                            </Badge>
                                                            {item.parent_key && (
                                                                <span className="text-[10px] text-muted-foreground">
                                                                    parent: <code>{item.parent_key}</code>
                                                                </span>
                                                            )}
                                                            <span
                                                                className={`text-[9px] px-1 py-0.5 rounded border ${scopeBadgeClass(item.scope)}`}
                                                            >
                                                                {item.scope}
                                                            </span>
                                                            {ct === "workflow_step" && (
                                                                <Badge
                                                                    variant="secondary"
                                                                    className="text-[10px]"
                                                                >
                                                                    {fieldCount} field
                                                                    {fieldCount === 1 ? "" : "s"}
                                                                </Badge>
                                                            )}
                                                            {!item.is_active && (
                                                                <Badge
                                                                    variant="secondary"
                                                                    className="text-[10px]"
                                                                >
                                                                    inactive
                                                                </Badge>
                                                            )}
                                                        </div>
                                                        {v.description != null && (
                                                            <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-1">
                                                                {v.description as string}
                                                            </p>
                                                        )}
                                                        {v.snippet != null && (
                                                            <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-1 font-mono">
                                                                {v.snippet as string}
                                                            </p>
                                                        )}
                                                    </div>
                                                    <span className="text-[10px] text-muted-foreground tabular-nums flex-shrink-0">
                                                        #{item.sort_order}
                                                    </span>
                                                    <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-0.5 flex-shrink-0">
                                                        <button
                                                            type="button"
                                                            className="p-1.5 rounded hover:bg-primary/10 hover:text-primary"
                                                            title="Edit"
                                                            onClick={() => openEdit(item)}
                                                        >
                                                            <Pencil className="h-3.5 w-3.5" />
                                                        </button>
                                                        <button
                                                            type="button"
                                                            className="p-1.5 rounded hover:bg-amber-500/10 hover:text-amber-500"
                                                            title={item.is_active ? "Disable" : "Enable"}
                                                            onClick={() => handleToggle(item)}
                                                        >
                                                            {item.is_active ? (
                                                                <PowerOff className="h-3.5 w-3.5" />
                                                            ) : (
                                                                <Power className="h-3.5 w-3.5" />
                                                            )}
                                                        </button>
                                                        <button
                                                            type="button"
                                                            className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive"
                                                            title="Delete"
                                                            onClick={() => handleDelete(item)}
                                                        >
                                                            <Trash2 className="h-3.5 w-3.5" />
                                                        </button>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        );
                    })
                )}
            </div>

            {/* Create / Edit Dialog */}
            <Dialog
                open={dialogOpen}
                onOpenChange={(o) => {
                    if (!o) closeDialog();
                }}
            >
                <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>
                            {dialogMode === "create"
                                ? `New ${currentMeta.label_en} Item`
                                : `Edit ${currentMeta.label_en} Item`}
                        </DialogTitle>
                        <DialogDescription>
                            {currentMeta.label_zh} · {currentMeta.description}
                        </DialogDescription>
                    </DialogHeader>

                    <div className="space-y-4 py-2">
                        {/* Top row: config_type (locked on edit) + key + sort_order */}
                        <div className="grid grid-cols-12 gap-3">
                            <div className="col-span-5 space-y-1.5">
                                <Label className="text-xs">Config Type</Label>
                                {dialogMode === "create" ? (
                                    <Select
                                        value={formType}
                                        onValueChange={(v) => {
                                            setFormType(v);
                                            setFormValue(buildFormValue(getMeta(v), {}));
                                        }}
                                    >
                                        <SelectTrigger className="h-9">
                                            <SelectValue placeholder="Choose a config type..." />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {KNOWN_TYPE_ORDER.filter((k) => {
                                                const m = getMeta(k);
                                                return (
                                                    m.scopes.includes(scope) ||
                                                    m.scopes.includes("shared")
                                                );
                                            }).map((k) => {
                                                const m = getMeta(k);
                                                return (
                                                    <SelectItem key={k} value={k}>
                                                        {m.label_zh} · {m.label_en}
                                                    </SelectItem>
                                                );
                                            })}
                                        </SelectContent>
                                    </Select>
                                ) : (
                                    <Input
                                        value={formType}
                                        disabled
                                        className="h-9 font-mono text-xs"
                                    />
                                )}
                            </div>
                            <div className="col-span-5 space-y-1.5">
                                <Label className="text-xs">
                                    Key {dialogMode === "create" && <span className="text-destructive">*</span>}
                                </Label>
                                <Input
                                    className="h-9 font-mono text-sm"
                                    value={formKey}
                                    onChange={(e) => setFormKey(e.target.value)}
                                    placeholder="e.g. visibility_boost"
                                    disabled={dialogMode === "edit"}
                                />
                            </div>
                            <div className="col-span-2 space-y-1.5">
                                <Label className="text-xs">Sort</Label>
                                <Input
                                    type="number"
                                    className="h-9"
                                    value={formOrder}
                                    onChange={(e) =>
                                        setFormOrder(parseInt(e.target.value, 10) || 0)
                                    }
                                />
                            </div>
                        </div>

                        {/* Parent key (for 2-level dictionaries like content_sub_goal) */}
                        {currentMeta.hasParentKey && (
                            <div className="space-y-1.5">
                                <Label className="text-xs">
                                    Parent Key{" "}
                                    <span className="text-muted-foreground normal-case">
                                        (key of the parent row this item groups under)
                                    </span>
                                </Label>
                                <Input
                                    className="h-9 font-mono text-sm"
                                    value={formParentKey}
                                    onChange={(e) => setFormParentKey(e.target.value)}
                                    placeholder="e.g. readability (for content_sub_goal)"
                                />
                            </div>
                        )}

                        {/* Dynamic fields */}
                        {formType && (
                            <div className="border-t border-border/60 pt-4 space-y-3">
                                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                                    Value Fields
                                </div>
                                {currentMeta.fields.map((f) => {
                                    const val = (formValue[f.key] ?? "") as string | number;
                                    const err = formErrors[f.key];
                                    const labelNode = (
                                        <Label className="text-xs">
                                            {f.label}
                                            {f.required && (
                                                <span className="text-destructive ml-1">*</span>
                                            )}
                                        </Label>
                                    );
                                    const errNode = err && (
                                        <p className="text-[11px] text-destructive mt-1">
                                            {err}
                                        </p>
                                    );
                                    if (f.type === "textarea") {
                                        return (
                                            <div key={f.key} className="space-y-1.5">
                                                {labelNode}
                                                <Textarea
                                                    rows={f.rows || 4}
                                                    value={val}
                                                    onChange={(e) => setField(f.key, e.target.value)}
                                                    placeholder={f.placeholder}
                                                    className={`text-sm font-mono resize-y ${err ? "border-destructive" : ""}`}
                                                />
                                                {errNode}
                                            </div>
                                        );
                                    }
                                    if (f.type === "json") {
                                        return (
                                            <div key={f.key} className="space-y-1.5">
                                                {labelNode}
                                                {f.description && (
                                                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                                                        {f.description}
                                                    </p>
                                                )}
                                                <Textarea
                                                    rows={f.rows || 10}
                                                    value={val}
                                                    onChange={(e) => setField(f.key, e.target.value)}
                                                    placeholder={f.placeholder}
                                                    className={`text-[11px] font-mono resize-y leading-relaxed ${err ? "border-destructive" : ""}`}
                                                    spellCheck={false}
                                                />
                                                {errNode}
                                            </div>
                                        );
                                    }
                                    if (f.type === "number") {
                                        return (
                                            <div key={f.key} className="space-y-1.5">
                                                {labelNode}
                                                <Input
                                                    type="number"
                                                    className={`h-9 ${err ? "border-destructive" : ""}`}
                                                    value={val}
                                                    onChange={(e) => setField(f.key, e.target.value)}
                                                    placeholder={f.placeholder}
                                                />
                                                {errNode}
                                            </div>
                                        );
                                    }
                                    // text or list
                                    return (
                                        <div key={f.key} className="space-y-1.5">
                                            {labelNode}
                                            <Input
                                                className={`h-9 text-sm ${err ? "border-destructive" : ""}`}
                                                value={val}
                                                onChange={(e) => setField(f.key, e.target.value)}
                                                placeholder={f.placeholder}
                                            />
                                            {errNode}
                                        </div>
                                    );
                                })}
                            </div>
                        )}

                        {formErrors.__save__ && (
                            <p className="text-xs text-destructive">
                                {formErrors.__save__}
                            </p>
                        )}
                    </div>

                    <DialogFooter>
                        <Button variant="outline" onClick={closeDialog} disabled={saving}>
                            <X className="mr-1.5 h-3.5 w-3.5" /> Cancel
                        </Button>
                        <Button
                            onClick={handleSave}
                            disabled={
                                saving ||
                                !formType ||
                                (dialogMode === "create" && !formKey.trim())
                            }
                        >
                            {saving ? (
                                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <Save className="mr-1.5 h-3.5 w-3.5" />
                            )}
                            {dialogMode === "create" ? "Create" : "Update"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
