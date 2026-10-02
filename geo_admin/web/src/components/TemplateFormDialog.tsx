/**
 * TemplateFormDialog
 *
 * Shared create/edit dialog for Report (analysis) and Content Templates.
 * Replaces the 300-line inline forms that used to live at the top of
 * ReportTemplatesPage.jsx and ContentTemplatesPage.jsx.
 *
 * Why one component with a mode switch:
 *   - 90% of the form is identical (name/icon/sort, description, data_domains,
 *     wizard_config editor, prompt, flags).
 *   - Only the "Workflow Defaults" block and a few labels differ between the
 *     two task types.
 *   - Keeping one component eliminates the drift bug where a fix landed in
 *     one page but not the other (already happened with DOMAIN_META).
 *
 * Props:
 *   open / onOpenChange — Dialog open state
 *   mode                — "analysis" | "content"
 *   template            — existing row when editing, null when creating
 *   goalOptions / platformOptions / depthOptions / contentTypeOptions
 *                       — workflow_config dictionaries loaded by the parent
 *   onSaved             — called after a successful create/update
 */
import { useEffect, useState, type ReactNode } from "react";
import type { components } from "../api/openapi";
import { useToast } from "./Toast";
import {
    createReportTemplate,
    updateReportTemplate,
} from "../api/client";
import WizardConfigEditor from "./WizardConfigEditor";
import { getDomainMeta, PRIMARY_DOMAIN_KEYS } from "../lib/domainMeta";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, Save, X } from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────
// Defaults
// ─────────────────────────────────────────────────────────────────────────

type Mode = "analysis" | "content";
type TemplateCreate = components["schemas"]["TemplateCreate"];
type TemplateUpdate = components["schemas"]["TemplateUpdate"];
type TemplateRow = components["schemas"]["TemplateOut"];

interface AnalysisDefaults {
    goal: string;
    platforms: string[];
    depth: string;
    baseline_type: string;
}

interface ContentDefaults {
    goal: string;
    content_type: string;
    platforms: string[];
    depth: string;
    count: number;
}

type WorkflowDefaults = AnalysisDefaults | ContentDefaults;

interface WizardConfigShape {
    version: number;
    steps: Record<string, Record<string, unknown>>;
    required_metrics: string[];
    required_chapters?: string[];
    required_subgoals?: string[];
    [key: string]: unknown;
}

interface FormState {
    name: string;
    icon: string;
    description: string;
    data_domains: string[];
    default_prompt: string;
    is_builtin: boolean;
    is_active: boolean;
    sort_order: number | string;
    defaults: WorkflowDefaults;
    wizard_config: WizardConfigShape;
}

interface DictOption {
    key: string;
    label: string;
    icon?: string;
    [k: string]: unknown;
}

const ANALYSIS_ICON_OPTIONS = [
    "📊", "🔍", "📎", "💬", "📈", "🏆", "✨", "🎯", "📋", "🧠", "🛡️",
];
const CONTENT_ICON_OPTIONS = [
    "📋", "🤖", "✍️", "💡", "📝", "🎯", "📈", "🧠", "✨", "🏆",
];

const ANALYSIS_EMPTY_DEFAULTS: AnalysisDefaults = {
    goal: "",
    platforms: [],
    depth: "standard",
    baseline_type: "none",
};
const CONTENT_EMPTY_DEFAULTS: ContentDefaults = {
    goal: "",
    content_type: "",
    platforms: [],
    depth: "standard",
    count: 1,
};

const ANALYSIS_EMPTY_WIZARD: WizardConfigShape = {
    version: 1,
    steps: {},
    required_metrics: [],
    required_chapters: [],
};
const CONTENT_EMPTY_WIZARD: WizardConfigShape = {
    version: 1,
    steps: {},
    required_metrics: [],
    required_subgoals: [],
};

function makeEmptyForm(mode: Mode): FormState {
    return {
        name: "",
        icon: mode === "content" ? "📋" : "📊",
        description: "",
        data_domains:
            mode === "content" ? ["visibility", "citation"] : ["visibility"],
        default_prompt: "",
        is_builtin: false,
        is_active: true,
        sort_order: 0,
        defaults:
            mode === "content"
                ? { ...CONTENT_EMPTY_DEFAULTS }
                : { ...ANALYSIS_EMPTY_DEFAULTS },
        wizard_config:
            mode === "content"
                ? { ...CONTENT_EMPTY_WIZARD }
                : { ...ANALYSIS_EMPTY_WIZARD },
    };
}

function parseRecord(raw: unknown): Record<string, unknown> {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
        return raw as Record<string, unknown>;
    }
    if (typeof raw === "string") return safeJson(raw);
    return {};
}

function parseDefaults(raw: unknown, mode: Mode): WorkflowDefaults {
    const base: WorkflowDefaults =
        mode === "content"
            ? { ...CONTENT_EMPTY_DEFAULTS }
            : { ...ANALYSIS_EMPTY_DEFAULTS };
    const parsed = parseRecord(raw);
    return { ...base, ...(parsed as Partial<WorkflowDefaults>) };
}

function parseWizard(raw: unknown, mode: Mode): WizardConfigShape {
    const base: WizardConfigShape =
        mode === "content" ? CONTENT_EMPTY_WIZARD : ANALYSIS_EMPTY_WIZARD;
    return { ...base, ...parseRecord(raw) };
}

function safeJson(s: string): Record<string, unknown> {
    try {
        return JSON.parse(s) as Record<string, unknown>;
    } catch {
        return {};
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────

interface TemplateFormDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    mode: Mode;
    template: TemplateRow | null;
    goalOptions?: DictOption[];
    platformOptions?: DictOption[];
    depthOptions?: DictOption[];
    contentTypeOptions?: DictOption[];
    onSaved?: () => void;
}

export default function TemplateFormDialog({
    open,
    onOpenChange,
    mode,
    template,
    goalOptions = [],
    platformOptions = [],
    depthOptions = [],
    contentTypeOptions = [],
    onSaved,
}: TemplateFormDialogProps) {
    const toast = useToast();
    const isContent = mode === "content";
    const editId = template?.id || null;
    const iconOptions = isContent ? CONTENT_ICON_OPTIONS : ANALYSIS_ICON_OPTIONS;

    const [form, setForm] = useState<FormState>(() => makeEmptyForm(mode));
    const [saving, setSaving] = useState<boolean>(false);
    const [jsonMode, setJsonMode] = useState<boolean>(false);
    const [jsonText, setJsonText] = useState<string>("{}");
    const [jsonError, setJsonError] = useState<string>("");

    // Re-initialize form whenever the dialog opens or the edit target changes.
    useEffect(() => {
        if (!open) return;
        if (template) {
            const d = parseDefaults(template.defaults, mode);
            setForm({
                name: template.name,
                icon: template.icon || (isContent ? "📋" : "📊"),
                description: template.description || "",
                data_domains:
                    template.data_domains || (isContent ? ["visibility", "citation"] : ["visibility"]),
                default_prompt: template.default_prompt || "",
                is_builtin: !!template.is_builtin,
                is_active: template.is_active !== false,
                sort_order: template.sort_order || 0,
                defaults: d,
                wizard_config: parseWizard(template.wizard_config, mode),
            });
            setJsonText(JSON.stringify(d, null, 2));
        } else {
            setForm(makeEmptyForm(mode));
            setJsonText("{}");
        }
        setJsonMode(false);
        setJsonError("");
    }, [open, template, mode, isContent]);

    // ─── Field updaters ───
    function updateForm(patch: Partial<FormState>) {
        setForm((prev) => ({ ...prev, ...patch }));
    }
    function setDefault(key: string, value: unknown) {
        setForm((prev) => ({
            ...prev,
            defaults: { ...prev.defaults, [key]: value } as WorkflowDefaults,
        }));
    }
    function toggleDomain(d: string) {
        setForm((prev) => ({
            ...prev,
            data_domains: prev.data_domains.includes(d)
                ? prev.data_domains.filter((x) => x !== d)
                : [...prev.data_domains, d],
        }));
    }
    function togglePlatform(p: string) {
        setForm((prev) => ({
            ...prev,
            defaults: {
                ...prev.defaults,
                platforms: prev.defaults.platforms.includes(p)
                    ? prev.defaults.platforms.filter((x: string) => x !== p)
                    : [...prev.defaults.platforms, p],
            } as WorkflowDefaults,
        }));
    }

    // ─── JSON toggle for Defaults ───
    function handleJsonToggle() {
        if (!jsonMode) {
            const clean = Object.fromEntries(
                Object.entries(form.defaults).filter(
                    ([, v]) =>
                        v !== "" &&
                        v !== null &&
                        !(Array.isArray(v) && v.length === 0),
                ),
            );
            setJsonText(JSON.stringify(clean, null, 2));
            setJsonMode(true);
            return;
        }
        try {
            const parsed = JSON.parse(jsonText) as Record<string, unknown>;
            setForm((prev) => ({
                ...prev,
                defaults: isContent
                    ? {
                          goal: (parsed.goal as string) || "",
                          content_type: (parsed.content_type as string) || "",
                          platforms: (parsed.platforms as string[]) || [],
                          depth: (parsed.depth as string) || "standard",
                          count: (parsed.count as number) ?? 1,
                      }
                    : {
                          goal: (parsed.goal as string) || "",
                          platforms: (parsed.platforms as string[]) || [],
                          depth: (parsed.depth as string) || "standard",
                          baseline_type: (parsed.baseline_type as string) || "none",
                      },
            }));
            setJsonError("");
            setJsonMode(false);
        } catch {
            setJsonError("Invalid JSON — fix before switching back");
        }
    }

    // ─── Save ───
    async function handleSave(): Promise<void> {
        if (!form.name || form.data_domains.length === 0) {
            toast.error("Name and at least one domain are required");
            return;
        }
        setSaving(true);
        try {
            let finalDefaults: Record<string, unknown> | null;
            if (jsonMode) {
                try {
                    finalDefaults = JSON.parse(jsonText);
                } catch {
                    toast.error("Invalid JSON in defaults");
                    setSaving(false);
                    return;
                }
            } else {
                const filtered = Object.fromEntries(
                    Object.entries(form.defaults).filter(([k, v]) => {
                        if (v === "" || v === null) return false;
                        if (Array.isArray(v) && v.length === 0) return false;
                        // count=0 is meaningless, but count=1 is the default and
                        // should still be sent
                        if (k === "count" && v === 0) return false;
                        return true;
                    }),
                );
                finalDefaults =
                    Object.keys(filtered).length > 0 ? filtered : null;
            }
            const payload = {
                ...form,
                defaults: finalDefaults,
                wizard_config: form.wizard_config || {},
                sort_order: parseInt(String(form.sort_order), 10) || 0,
                description: form.description.trim() || null,
                task_type: isContent ? "content_generation" : "analysis",
            } satisfies TemplateUpdate;
            if (editId) {
                await updateReportTemplate(editId, payload);
                toast.success("Template updated");
            } else {
                const createPayload: TemplateCreate = {
                    ...payload,
                    cron_timezone: "Asia/Shanghai",
                    schedule_enabled: false,
                };
                await createReportTemplate(createPayload);
                toast.success("Template created");
            }
            onOpenChange(false);
            if (onSaved) onSaved();
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setSaving(false);
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-4xl max-h-[92vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="text-xl">
                        {editId
                            ? `Edit ${isContent ? "Content" : "Report"} Template`
                            : `New ${isContent ? "Content" : "Report"} Template`}
                    </DialogTitle>
                    <DialogDescription>
                        {isContent
                            ? "配置一个内容生成模板 —— 这里设置的默认值会在 SaaS 向导里作为初始选项，用户仍可修改。"
                            : "配置一个分析模板 —— 这里设置的默认值会在 SaaS 向导里作为初始选项，用户仍可修改。"}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-5 py-2">
                    {/* Name / Icon / Sort */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="col-span-2 space-y-1.5">
                            <Label className="text-xs uppercase text-muted-foreground">
                                Name <span className="text-destructive">*</span>
                            </Label>
                            <Input
                                value={form.name}
                                onChange={(e) => updateForm({ name: e.target.value })}
                                placeholder={
                                    isContent
                                        ? "e.g. AEO Optimized Article"
                                        : "e.g. Weekly GEO Briefing"
                                }
                                className="h-10"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-xs uppercase text-muted-foreground">
                                Icon
                            </Label>
                            <Select
                                value={form.icon}
                                onValueChange={(v) => updateForm({ icon: v })}
                            >
                                <SelectTrigger className="h-10 text-lg">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {iconOptions.map((ic) => (
                                        <SelectItem key={ic} value={ic}>
                                            {ic}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-xs uppercase text-muted-foreground">
                                Sort Order
                            </Label>
                            <Input
                                type="number"
                                min="0"
                                value={form.sort_order}
                                onChange={(e) =>
                                    updateForm({ sort_order: e.target.value })
                                }
                                className="h-10"
                            />
                        </div>
                    </div>

                    {/* Description */}
                    <div className="space-y-1.5">
                        <Label className="text-xs uppercase text-muted-foreground">
                            Description
                        </Label>
                        <Input
                            value={form.description}
                            onChange={(e) => updateForm({ description: e.target.value })}
                            placeholder="Short description shown in the template picker"
                            className="h-10"
                        />
                    </div>

                    {/* Data Domains */}
                    <div className="space-y-2">
                        <Label className="text-xs uppercase text-muted-foreground">
                            Data Domains <span className="text-destructive">*</span>
                        </Label>
                        <div className="flex gap-2 flex-wrap">
                            {PRIMARY_DOMAIN_KEYS.map((d) => {
                                const meta = getDomainMeta(d);
                                const selected = form.data_domains.includes(d);
                                return (
                                    <button
                                        type="button"
                                        key={d}
                                        onClick={() => toggleDomain(d)}
                                        className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors inline-flex items-center gap-1.5 ${
                                            selected
                                                ? meta.color
                                                : "border-border text-muted-foreground hover:border-primary/40"
                                        }`}
                                    >
                                        <span>{meta.icon}</span>
                                        {meta.label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Workflow Defaults */}
                    <div className="border border-border/50 rounded-xl p-5 space-y-4 bg-muted/5">
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-foreground">
                                Workflow Defaults
                            </span>
                            <span className="text-xs text-muted-foreground">
                                (pre-selected when a user opens this template)
                            </span>
                            <button
                                type="button"
                                onClick={handleJsonToggle}
                                className="ml-auto text-xs text-primary hover:underline"
                            >
                                {jsonMode ? "Visual Editor" : "JSON Editor"}
                            </button>
                        </div>

                        {jsonMode ? (
                            <div>
                                <Textarea
                                    rows={8}
                                    value={jsonText}
                                    onChange={(e) => {
                                        setJsonText(e.target.value);
                                        try {
                                            JSON.parse(e.target.value);
                                            setJsonError("");
                                        } catch {
                                            setJsonError("Invalid JSON");
                                        }
                                    }}
                                    className={`font-mono text-sm ${
                                        jsonError ? "border-red-500" : ""
                                    }`}
                                    placeholder={
                                        isContent
                                            ? '{"goal":"visibility_boost","content_type":"faq","platforms":["chatgpt"],"count":5}'
                                            : '{"goal":"benchmark","platforms":["chatgpt"],"depth":"standard"}'
                                    }
                                />
                                {jsonError && (
                                    <p className="text-xs text-red-400 mt-1">
                                        {jsonError}
                                    </p>
                                )}
                            </div>
                        ) : (
                            <DefaultsEditor
                                isContent={isContent}
                                form={form}
                                setDefault={setDefault}
                                togglePlatform={togglePlatform}
                                goalOptions={goalOptions}
                                platformOptions={platformOptions}
                                depthOptions={depthOptions}
                                contentTypeOptions={contentTypeOptions}
                            />
                        )}
                    </div>

                    {/* Wizard Config */}
                    <WizardConfigEditor
                        mode={isContent ? "content" : "analysis"}
                        value={form.wizard_config}
                        onChange={(next) =>
                            updateForm({ wizard_config: next })
                        }
                    />

                    {/* Prompt */}
                    <div className="space-y-1.5">
                        <Label className="text-xs uppercase text-muted-foreground">
                            {isContent ? "Strategy Prompt" : "Default Prompt"}
                            <span className="ml-2 normal-case font-normal text-muted-foreground">
                                {isContent
                                    ? "(system prompt — will be constrained by content_framework RATF metrics + sub-goals at runtime)"
                                    : "(use {{variable_name}} for metric variables — will be constrained by analysis_framework DDPP lenses at runtime)"}
                            </span>
                        </Label>
                        <Textarea
                            value={form.default_prompt}
                            onChange={(e) =>
                                updateForm({ default_prompt: e.target.value })
                            }
                            rows={isContent ? 10 : 8}
                            placeholder={
                                isContent
                                    ? "你是一位专业的 GEO 内容策略师。请基于以下品牌数据..."
                                    : "请根据以下 GEO 数据，生成一份详细的分析报告：\n\n品牌提及率：{{mention_rate}}\n引用分数：{{citation_score}}\n..."
                            }
                            className="font-mono text-sm min-h-[180px]"
                        />
                    </div>

                    {/* Flags */}
                    <div className="flex items-center gap-6 pt-1">
                        <label className="flex items-center gap-2 cursor-pointer text-sm">
                            <Checkbox
                                checked={form.is_builtin}
                                onCheckedChange={(v) =>
                                    updateForm({ is_builtin: !!v })
                                }
                            />
                            Built-in template
                        </label>
                        <label className="flex items-center gap-2 cursor-pointer text-sm">
                            <Checkbox
                                checked={form.is_active}
                                onCheckedChange={(v) =>
                                    updateForm({ is_active: !!v })
                                }
                            />
                            Active (visible to users)
                        </label>
                    </div>
                </div>

                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        disabled={saving}
                    >
                        <X className="mr-1.5 h-3.5 w-3.5" /> Cancel
                    </Button>
                    <Button onClick={handleSave} disabled={saving}>
                        {saving ? (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        ) : (
                            <Save className="mr-1.5 h-3.5 w-3.5" />
                        )}
                        {editId ? "Update Template" : "Create Template"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

// ─────────────────────────────────────────────────────────────────────────
// Inner component: the Defaults visual editor (branches by mode)
// Kept separate to make the main component readable.
// ─────────────────────────────────────────────────────────────────────────

interface DefaultsEditorProps {
    isContent: boolean;
    form: FormState;
    setDefault: (key: string, value: unknown) => void;
    togglePlatform: (p: string) => void;
    goalOptions: DictOption[];
    platformOptions: DictOption[];
    depthOptions: DictOption[];
    contentTypeOptions: DictOption[];
}

function DefaultsEditor({
    isContent,
    form,
    setDefault,
    togglePlatform,
    goalOptions,
    platformOptions,
    depthOptions,
    contentTypeOptions,
}: DefaultsEditorProps) {
    const Pill = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) => (
        <button
            type="button"
            onClick={onClick}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors inline-flex items-center gap-1 ${
                active
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/40"
            }`}
        >
            {children}
        </button>
    );

    const defaultsAsContent = form.defaults as ContentDefaults;
    const defaultsAsAnalysis = form.defaults as AnalysisDefaults;

    return (
        <div className="space-y-4">
            {/* Goal */}
            <div>
                <Label className="text-xs uppercase text-muted-foreground mb-2 block">
                    {isContent ? "Content Goal" : "Analysis Goal"}
                </Label>
                <div className="flex flex-wrap gap-2">
                    <Pill
                        active={!form.defaults.goal}
                        onClick={() => setDefault("goal", "")}
                    >
                        None
                    </Pill>
                    {goalOptions.map((g) => (
                        <Pill
                            key={g.key}
                            active={form.defaults.goal === g.key}
                            onClick={() => setDefault("goal", g.key)}
                        >
                            {g.icon && <span>{g.icon}</span>}
                            {g.label}
                        </Pill>
                    ))}
                </div>
            </div>

            {/* Content Type (content mode only) */}
            {isContent && (
                <div>
                    <Label className="text-xs uppercase text-muted-foreground mb-2 block">
                        Content Type
                    </Label>
                    <div className="flex flex-wrap gap-2">
                        <Pill
                            active={!defaultsAsContent.content_type}
                            onClick={() => setDefault("content_type", "")}
                        >
                            None
                        </Pill>
                        {contentTypeOptions.map((c) => (
                            <Pill
                                key={c.key}
                                active={defaultsAsContent.content_type === c.key}
                                onClick={() => setDefault("content_type", c.key)}
                            >
                                {c.icon && <span>{c.icon}</span>}
                                {c.label}
                            </Pill>
                        ))}
                    </div>
                </div>
            )}

            {/* Platforms */}
            <div>
                <Label className="text-xs uppercase text-muted-foreground mb-2 block">
                    Default Platforms
                </Label>
                <div className="flex flex-wrap gap-2">
                    {platformOptions.map((p) => (
                        <Pill
                            key={p.key}
                            active={form.defaults.platforms.includes(p.key)}
                            onClick={() => togglePlatform(p.key)}
                        >
                            {p.icon && <span>{p.icon}</span>}
                            {p.label}
                        </Pill>
                    ))}
                </div>
            </div>

            {/* Depth + (Baseline | Count) */}
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <Label className="text-xs uppercase text-muted-foreground mb-2 block">
                        {isContent ? "Content Depth" : "Analysis Depth"}
                    </Label>
                    <Select
                        value={form.defaults.depth}
                        onValueChange={(v) => setDefault("depth", v)}
                    >
                        <SelectTrigger className="h-9">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {depthOptions.map((d) => (
                                <SelectItem key={d.key} value={d.key}>
                                    {d.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div>
                    <Label className="text-xs uppercase text-muted-foreground mb-2 block">
                        {isContent ? "Default Count" : "Comparison Baseline"}
                    </Label>
                    {isContent ? (
                        <Input
                            type="number"
                            min="1"
                            max="20"
                            value={defaultsAsContent.count}
                            onChange={(e) =>
                                setDefault(
                                    "count",
                                    parseInt(e.target.value, 10) || 1,
                                )
                            }
                            className="h-9"
                        />
                    ) : (
                        <Select
                            value={defaultsAsAnalysis.baseline_type}
                            onValueChange={(v) => setDefault("baseline_type", v)}
                        >
                            <SelectTrigger className="h-9">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="none">None</SelectItem>
                                <SelectItem value="previous_period">
                                    Previous Period
                                </SelectItem>
                                <SelectItem value="custom">
                                    Custom Date Range
                                </SelectItem>
                            </SelectContent>
                        </Select>
                    )}
                </div>
            </div>
        </div>
    );
}
