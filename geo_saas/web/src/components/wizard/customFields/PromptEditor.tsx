/**
 * PromptEditor — schema-driven replacement for Step4_Prompt's prompt block.
 *
 * Registered under the custom field type `prompt_editor`. Owns three things:
 *
 *   1. A variable catalog — auto-fetched from
 *      `/tasks/metrics/discover?domains=...` based on the current
 *      `default_domains` value in FormState. Click-to-insert into textarea.
 *   2. Methodology snippets (RAFT / Competitor / Trend) — click-to-insert.
 *   3. A textarea + expand-dialog overlay for editing the prompt body.
 *
 * The value stored in FormState under `field.key` is a plain string (the
 * prompt text). When the user has not yet typed anything, we fall back to
 * `context.template.default_prompt`.
 *
 * The dependency on `default_metrics` is wired in the field-computer
 * registry — see `prompt_template_with_metrics` in fieldComputers.ts.
 */
import { useRef, useState, useEffect, useMemo } from "react";
import { Database, Sparkles, Maximize2, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogDescription,
} from "@/components/ui/dialog";
import { fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

const AGENT_BASE = (import.meta.env.VITE_AGENT_API_URL || "") + "/api/agent";

// ─── Domain metadata ─────────────────────────────────────────────────

const DOMAIN_META: Record<string, { label: string; icon: string }> = {
    visibility: { label: "Visibility", icon: "👁️" },
    citation: { label: "Citation", icon: "🔗" },
    sentiment: { label: "Sentiment", icon: "💬" },
};

// ─── Methodology snippets (ported 1:1 from TemplateConfigModal) ──────

const METHODOLOGY_SNIPPETS: {
    category: string;
    items: { label: string; snippet: string }[];
}[] = [
    {
        category: "RAFT Framework",
        items: [
            {
                label: "Retrievability",
                snippet:
                    "Analyze the brand's retrievability in AI search engines, including mention frequency, position ranking, and prompt coverage.",
            },
            {
                label: "Accuracy",
                snippet:
                    "Evaluate the accuracy of brand information described by AI engines, identifying incorrect or outdated brand descriptions.",
            },
            {
                label: "Fluency",
                snippet:
                    "Analyze the language fluency and naturalness when AI engines recommend the brand, evaluating how well the brand integrates into responses.",
            },
            {
                label: "Trustworthiness",
                snippet:
                    "Evaluate the trustworthiness of AI engine brand citations, including citation source quality and recommendation tone strength.",
            },
        ],
    },
    {
        category: "Competitor Analysis",
        items: [
            {
                label: "SOV Comparison",
                snippet:
                    "Compare the brand's Share of Voice against competitors, analyzing differences in voice share across AI search results.",
            },
            {
                label: "Competitor Advantage Detection",
                snippet:
                    "Identify which prompts and platforms competitors outperform the brand on, and analyze the reasons behind their advantages.",
            },
        ],
    },
    {
        category: "Trend Insights",
        items: [
            {
                label: "Inflection Point Detection",
                snippet:
                    "Identify key inflection points in brand visibility and citation rate trends, and analyze possible causes of the changes.",
            },
            {
                label: "Platform Comparison",
                snippet:
                    "Compare brand performance across configured AI platforms and identify platform-specific preferences.",
            },
        ],
    },
];

interface MetricVar {
    variable_name: string;
    display_name: string;
    description?: string;
    unit?: string;
    chart_type?: string;
}
type VariableGroup = Record<string, MetricVar[]>;

// ─── Main component ──────────────────────────────────────────────────

function PromptEditor({
    value,
    onChange,
    context,
    formState,
    disabled,
}: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const [expandOpen, setExpandOpen] = useState(false);
    const [showMethodology, setShowMethodology] = useState(false);
    const [variables, setVariables] = useState<VariableGroup>({});

    // When admin locks editing via template override, treat as disabled
    const isLocked = disabled || Boolean(formState.disable_user_edit);

    // Required metrics from template — used to filter variable catalog
    const requiredMetrics = useMemo<string[] | null>(() => {
        const rm = context.template?.wizard_config?.required_metrics;
        return Array.isArray(rm) && rm.length > 0 ? (rm as string[]) : null;
    }, [context.template]);

    // Resolve the current prompt — fall back to template.default_prompt if
    // the user hasn't typed anything yet.
    const prompt = useMemo(() => {
        if (typeof value === "string" && value.length > 0) return value;
        return (context.template?.default_prompt as string) || "";
    }, [value, context.template]);

    // ─── Fetch variables when domains change ─────────────────────────
    // Reads the selected domains out of FormState (owned by the data_selection
    // step's default_domains multi_ref field). Falls back to the template's
    // data_domains list if the user hasn't interacted with that step yet.
    const selectedDomains = useMemo<string[]>(() => {
        const fromState = formState.default_domains;
        if (Array.isArray(fromState)) return fromState as string[];
        return (context.template?.data_domains as string[]) || [];
    }, [formState.default_domains, context.template]);

    const domainKey = selectedDomains.slice().sort().join(",");
    // When the template declares required_metrics, use /metrics/list (backed
    // by geo_analysis_metrics — same slug namespace as required_metrics).
    // Otherwise fall back to /metrics/discover (LLM-generated from schema).
    const metricsEndpoint = requiredMetrics
        ? `${AGENT_BASE}/tasks/metrics/list?domains=${domainKey}`
        : `${AGENT_BASE}/tasks/metrics/discover?domains=${domainKey}`;
    useEffect(() => {
        if (!domainKey) {
            setVariables({});
            return;
        }
        let cancelled = false;
        fetchJSON(metricsEndpoint)
            .then((data: VariableGroup) => {
                if (!cancelled) setVariables(data || {});
            })
            .catch(() => {
                if (!cancelled) setVariables({});
            });
        return () => {
            cancelled = true;
        };
    }, [metricsEndpoint]);

    // ─── Filter variables by required_metrics (if template sets them) ──
    const filteredVariables = useMemo<VariableGroup>(() => {
        if (!requiredMetrics) return variables;
        const out: VariableGroup = {};
        for (const [domain, vars] of Object.entries(variables)) {
            const filtered = vars.filter((v) =>
                requiredMetrics.includes(v.variable_name),
            );
            if (filtered.length > 0) out[domain] = filtered;
        }
        return out;
    }, [variables, requiredMetrics]);

    // ─── Textarea insertion helpers ──────────────────────────────────
    function setPromptValue(next: string) {
        onChange(next, true);
    }

    function insertVariable(displayName: string, variableName: string) {
        const el = textareaRef.current;
        const insertion = `[${displayName}(${variableName})]`;
        if (!el) {
            setPromptValue(prompt + insertion);
            return;
        }
        const start = el.selectionStart;
        const end = el.selectionEnd;
        const next = prompt.slice(0, start) + insertion + prompt.slice(end);
        setPromptValue(next);
        setTimeout(() => {
            el.focus();
            el.setSelectionRange(
                start + insertion.length,
                start + insertion.length,
            );
        }, 0);
    }

    function insertSnippet(snippet: string) {
        const el = textareaRef.current;
        if (el) {
            const start = el.selectionStart;
            const next =
                prompt.slice(0, start) + "\n" + snippet + "\n" + prompt.slice(start);
            setPromptValue(next);
            setTimeout(() => el.focus(), 0);
        } else {
            setPromptValue(prompt + "\n" + snippet);
        }
    }

    function insertAllVariables() {
        const domainReplacements: Record<string, string> = {};
        Object.entries(filteredVariables).forEach(([domain, vars]) => {
            domainReplacements[domain] = vars
                .map((v) => `[${v.display_name}(${v.variable_name})]`)
                .join(", ");
        });
        let next = prompt;
        const placeholderMap: Record<string, string> = {
            visibility: "visibility",
            citation: "citation",
            sentiment: "sentiment",
        };
        let replaced = false;
        for (const [label, domain] of Object.entries(placeholderMap)) {
            const pattern = `[click to insert ${label} metrics]`;
            if (next.includes(pattern) && domainReplacements[domain]) {
                next = next.replace(pattern, domainReplacements[domain]);
                replaced = true;
            }
        }
        if (!replaced) {
            const lines: string[] = [];
            Object.entries(filteredVariables).forEach(([domain, vars]) => {
                const meta = DOMAIN_META[domain];
                lines.push(`\n## ${meta?.label || domain}`);
                vars.forEach((v) =>
                    lines.push(`- [${v.display_name}(${v.variable_name})]`),
                );
            });
            next = next.trimEnd() + "\n" + lines.join("\n") + "\n";
        }
        setPromptValue(next);
    }

    // Label + description rendered by outer FieldWrapper.
    return (
        <div className="space-y-4">
            <div className="flex items-center justify-end">
                <button
                    type="button"
                    onClick={() => setShowMethodology((s) => !s)}
                    disabled={isLocked}
                    className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
                        showMethodology
                            ? "bg-primary/10 text-primary"
                            : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
                    }`}
                >
                    {showMethodology ? t("promptEditor.methodToggleClose") : t("promptEditor.methodToggleOpen")}
                </button>
            </div>

            {showMethodology && (
                <div className="rounded-xl border border-primary/15 bg-primary/[0.02] p-4 space-y-3">
                    <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        <Sparkles className="h-3.5 w-3.5 text-primary" />
                        {t("promptEditor.methodHeader")}
                    </div>
                    {METHODOLOGY_SNIPPETS.map((cat) => (
                        <div key={cat.category}>
                            <div className="text-[11px] font-semibold text-muted-foreground mb-1.5">
                                {cat.category}
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                                {cat.items.map((item) => (
                                    <button
                                        key={item.label}
                                        type="button"
                                        onClick={() => insertSnippet(item.snippet)}
                                        disabled={isLocked}
                                        title={item.snippet}
                                        className="px-2.5 py-1.5 rounded-md text-[11px] bg-background border hover:border-primary/40 hover:bg-primary/5 transition-all text-left disabled:opacity-50"
                                    >
                                        <span className="font-medium text-foreground">
                                            {item.label}
                                        </span>
                                    </button>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <VariableCatalog
                variables={filteredVariables}
                onInsert={insertVariable}
                onInsertAll={insertAllVariables}
                disabled={isLocked}
                requiredMode={!!requiredMetrics}
            />

            <div className="relative">
                <textarea
                    ref={textareaRef}
                    value={prompt}
                    onChange={(e) => setPromptValue(e.target.value)}
                    disabled={isLocked}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono text-foreground placeholder:text-muted-foreground pr-10 min-h-[160px] focus:outline-none focus:ring-2 focus:ring-ring/30 disabled:opacity-70 disabled:cursor-not-allowed"
                    placeholder={t("promptEditor.promptPlaceholder")}
                />
                <button
                    type="button"
                    onClick={() => setExpandOpen(true)}
                    disabled={isLocked}
                    title={t("promptEditor.expandTitle")}
                    className="absolute top-2 right-2 z-20 p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors disabled:opacity-50"
                >
                    <Maximize2 className="h-3.5 w-3.5" />
                </button>
            </div>

            <Dialog open={expandOpen} onOpenChange={setExpandOpen}>
                <DialogContent className="max-w-4xl w-[90vw] max-h-[90vh] flex flex-col overflow-hidden p-0 gap-0 sm:rounded-2xl">
                    <DialogTitle className="sr-only">{t("promptEditor.dialogTitle")}</DialogTitle>
                    <DialogDescription className="hidden">
                        {t("promptEditor.dialogDescription")}
                    </DialogDescription>
                    <div className="flex items-center justify-between px-5 py-3.5 border-b shrink-0">
                        <span className="text-sm font-semibold">{t("promptEditor.dialogHeader")}</span>
                    </div>
                    <div className="flex-1 flex flex-col overflow-hidden p-5 gap-4">
                        <VariableCatalog
                            variables={filteredVariables}
                            onInsert={insertVariable}
                            onInsertAll={insertAllVariables}
                            disabled={isLocked}
                            requiredMode={!!requiredMetrics}
                        />
                        <textarea
                            ref={textareaRef}
                            value={prompt}
                            onChange={(e) => setPromptValue(e.target.value)}
                            disabled={isLocked}
                            className="flex-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono text-foreground placeholder:text-muted-foreground min-h-[50vh] focus:outline-none focus:ring-2 focus:ring-ring/30 disabled:opacity-70 disabled:cursor-not-allowed"
                            placeholder={
                                "输入分析指令…\n\n点击上方数据指标插入到 Prompt"
                            }
                        />
                    </div>
                    <div className="shrink-0 flex justify-end px-5 pb-5">
                        <button
                            type="button"
                            onClick={() => setExpandOpen(false)}
                            className="px-4 py-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                        >
                            {t("promptEditor.dialogConfirm")}
                        </button>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
}

// ─── Variable catalog sub-component ──────────────────────────────────

function VariableCatalog({
    variables,
    onInsert,
    onInsertAll,
    disabled,
    requiredMode,
}: {
    variables: VariableGroup;
    onInsert: (displayName: string, variableName: string) => void;
    onInsertAll: () => void;
    disabled?: boolean;
    /** When true, the catalog is showing template-required metrics only. */
    requiredMode?: boolean;
}) {
    const { t } = useTranslation("wizard");
    const [expanded, setExpanded] = useState(true);
    const allVars = Object.values(variables).flat();

    return (
        <div className="rounded-lg border bg-muted/10">
            <button
                type="button"
                onClick={() => setExpanded((e) => !e)}
                className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider hover:bg-muted/20 transition-colors rounded-lg"
            >
                <span className="flex items-center gap-1.5">
                    <Database className="h-3.5 w-3.5" />
                    {requiredMode ? t("promptEditor.metricsSectionPreset") : t("promptEditor.metricsSectionAvailable")}
                    {allVars.length > 0 && (
                        <span className="text-[10px] font-normal normal-case text-muted-foreground/50">
                            ({allVars.length})
                        </span>
                    )}
                </span>
                <span className="flex items-center gap-2">
                    <span className="text-[10px] font-normal normal-case tracking-normal text-muted-foreground/60">
                        {t("promptEditor.metricsHint")}
                    </span>
                    <ChevronRight
                        className={`h-3.5 w-3.5 transition-transform ${
                            expanded ? "rotate-90" : ""
                        }`}
                    />
                </span>
            </button>
            {expanded && (
                <div className="px-4 pb-4 space-y-3">
                    {allVars.length > 0 && (
                        <button
                            type="button"
                            onClick={(e) => {
                                e.preventDefault();
                                onInsertAll();
                            }}
                            disabled={disabled}
                            className="w-full px-3 py-2 rounded-md text-xs border border-primary/30 bg-primary/5 text-primary hover:bg-primary/10 transition-colors font-medium disabled:opacity-50"
                        >
                            {t("promptEditor.insertAll", { count: allVars.length })}
                        </button>
                    )}
                    {Object.entries(variables).map(([domain, vars]) => {
                        const meta = DOMAIN_META[domain];
                        return (
                            <div key={domain}>
                                <div className="flex items-center gap-1.5 mb-2">
                                    <span>{meta?.icon || "📊"}</span>
                                    <span className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wide">
                                        {meta?.label || domain}
                                    </span>
                                </div>
                                <div className="flex flex-wrap gap-1.5">
                                    {vars.map((v) => (
                                        <button
                                            key={v.variable_name}
                                            type="button"
                                            onClick={() =>
                                                onInsert(v.display_name, v.variable_name)
                                            }
                                            disabled={disabled}
                                            title={v.description || v.variable_name}
                                            className="px-2.5 py-1.5 rounded-md text-xs bg-background border hover:border-primary/40 hover:bg-primary/5 transition-all flex flex-col items-start gap-0.5 text-left disabled:opacity-50"
                                        >
                                            <span className="font-medium text-foreground">
                                                {v.display_name}
                                            </span>
                                            <span className="font-mono text-[10px] text-muted-foreground">
                                                {v.variable_name}
                                            </span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        );
                    })}
                    {Object.keys(variables).length === 0 && (
                        <p className="text-xs text-muted-foreground">
                            {t("promptEditor.metricsEmpty")}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}

registerCustomField("prompt_editor", PromptEditor);

export default PromptEditor;
