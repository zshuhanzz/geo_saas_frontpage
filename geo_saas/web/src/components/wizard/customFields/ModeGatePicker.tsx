/**
 * ModeGatePicker — renders the two generation-mode options as large radio
 * cards (icon + title + description) instead of the default single_ref
 * combobox. This is step 0 of the content_generation wizard: it lets the
 * user pick whether they want to configure the task manually, or have
 * AI preselect the worst-performing content_type / topic / prompts for
 * them.
 *
 * The ref rows come from the `mode_option` config_type in
 * `geo_workflow_config` — see migration 051. Currently two rows:
 *   manual      → "我来定"
 *   ai_discover → "AI 帮我发现"
 *
 * The value stored under `mode_choice` is consumed by downstream steps:
 * when `ai_discover`, the form triggers the B-5 preselect endpoint and
 * bulk-fills content_type / topic_ids / prompt_ids / publish_platform.
 */
import { useMemo, useEffect, useState, useRef } from "react";
import { Sparkles, Hand, Loader2, AlertTriangle, Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import { preselectContent } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

interface ModeOption {
    key: string;
    label: string;
    description: string;
    icon?: string;
}

const ICON_MAP: Record<string, typeof Sparkles> = {
    "✨": Sparkles,
    "✍️": Hand,
};

interface PreselectResponse {
    mode: string;
    status: "ok" | "no_data" | "no_active_prompts";
    message?: string;
    sort_dimension?: string;
    target_topic_id?: string;
    target_topic_name?: string;
    target_prompt_ids?: string[];
    content_type?: string;
    publish_platform?: string;
    recommended_sub_goals?: string[];
    reasoning?: string;
}

/** Map preselect response → wizard form field keys. Keys here must match
 *  the field.key strings declared in geo_workflow_config for the content
 *  generation wizard. */
function preselectToFormValues(r: PreselectResponse): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    if (r.target_prompt_ids) out.prompt_ids = r.target_prompt_ids;
    if (r.target_topic_id) out.topic_ids = [r.target_topic_id];
    if (r.content_type) {
        out.default = r.content_type;
        out.content_type = r.content_type;
    }
    if (r.publish_platform) out.default_publish_platform = r.publish_platform;
    if (r.recommended_sub_goals && r.recommended_sub_goals.length > 0) {
        out.default_sub_goals = r.recommended_sub_goals;
    }
    return out;
}

function ModeGatePicker({
    field,
    value,
    onChange,
    setFields,
    context,
    disabled,
}: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const strValue = typeof value === "string" ? value : "";

    // AI preselect state. Fires a backend call when user flips from manual→
    // ai_discover, then bulk-sets the returned defaults into form state.
    const [aiLoading, setAiLoading] = useState(false);
    const [aiResult, setAiResult] = useState<PreselectResponse | null>(null);
    const [aiError, setAiError] = useState<string | null>(null);
    const lastAIClientRef = useRef<string | null>(null);

    // Pull the mode_option rows out of the dictionary the wizard shell
    // loaded for us. Falls back to an inline list if the dictionary is
    // missing (shouldn't happen after migration 051 runs).
    const options = useMemo<ModeOption[]>(() => {
        const configType = field.ref_config_type || "mode_option";
        const rows = context.dictionary?.[configType] || [];
        if (rows.length > 0) {
            return rows.map((r) => {
                const raw = (r.raw || {}) as { icon?: string };
                return {
                    key: r.key,
                    label: r.label || r.key,
                    description: r.description || "",
                    icon: raw.icon || r.icon,
                };
            });
        }
        return [
            { key: "manual", label: t("modeGatePicker.items.manual.label"), description: t("modeGatePicker.items.manual.description"), icon: "✍️" },
            { key: "ai_discover", label: t("modeGatePicker.items.ai_discover.label"), description: t("modeGatePicker.items.ai_discover.description"), icon: "✨" },
        ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [field.ref_config_type, context.dictionary, t]);

    // Lock in a default when the form first mounts without a value.
    // Reads from the template override wizard_config.steps.mode_gate.default_mode_choice,
    // otherwise falls back to "manual" (the spec-mandated default).
    useEffect(() => {
        if (strValue) return;
        const stepOverride =
            (context.template?.wizard_config?.steps as
                | Record<string, { default_mode_choice?: string }>
                | undefined)?.["mode_gate"];
        const stepDefault = stepOverride?.default_mode_choice || "manual";
        if (options.some((o) => o.key === stepDefault)) {
            onChange(stepDefault, false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [options.length]);

    // When the user selects AI mode, fetch the preselect bundle and
    // bulk-fill the downstream form fields. We gate on clientId so the
    // call only fires once per client+AI activation, and clear the result
    // when the user switches back to manual.
    useEffect(() => {
        if (strValue !== "ai_discover") {
            // Reset transient AI state so the next ai_discover fresh-fires.
            if (aiResult || aiError) {
                setAiResult(null);
                setAiError(null);
            }
            lastAIClientRef.current = null;
            return;
        }
        if (!context.clientId) return;
        if (!setFields) return;  // wizard shell didn't pass the helper; no-op
        // Debounce re-fires for the same client — user flipping back and
        // forth shouldn't re-spam the backend.
        if (lastAIClientRef.current === context.clientId && aiResult?.status === "ok") return;
        lastAIClientRef.current = context.clientId;

        let cancelled = false;
        setAiLoading(true);
        setAiError(null);

        preselectContent({
            client_id: context.clientId,
            sort_dimension: "visibility",
            template_id: context.templateId,
        })
            .then((r: PreselectResponse) => {
                if (cancelled) return;
                setAiResult(r);
                if (r.status === "ok") {
                    setFields(preselectToFormValues(r), false);
                }
            })
            .catch((e: Error) => {
                if (!cancelled) setAiError(e.message || "AI preselect failed");
            })
            .finally(() => {
                if (!cancelled) setAiLoading(false);
            });

        return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [strValue, context.clientId, context.templateId]);

    // Label + description are rendered by FieldWrapper (the parent in
    // FieldRenderer). This component owns only the mode-picker UI itself
    // so we don't double-render the step's label header.
    return (
        <div className="space-y-3">
            {strValue === "ai_discover" && (
                <div className="rounded-xl border border-primary/20 bg-primary/[0.03] p-4">
                    {aiLoading && (
                        <div className="flex items-center gap-2 text-sm text-primary">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            {t("modeGatePicker.aiAnalyzing")}
                        </div>
                    )}
                    {!aiLoading && aiError && (
                        <div className="flex items-start gap-2 text-sm text-destructive">
                            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                            <div>
                                {t("modeGatePicker.aiFailed", { error: aiError })}
                                <div className="mt-0.5 text-xs opacity-80">
                                    {t("modeGatePicker.aiFailedFallback")}
                                </div>
                            </div>
                        </div>
                    )}
                    {!aiLoading && !aiError && aiResult && aiResult.status !== "ok" && (
                        <div className="flex items-start gap-2 text-sm text-amber-500">
                            <Info className="h-4 w-4 shrink-0 mt-0.5" />
                            <div>
                                {aiResult.message || t("modeGatePicker.aiEmpty")}
                                <div className="mt-0.5 text-xs opacity-80">
                                    {t("modeGatePicker.aiEmptyHint")}
                                </div>
                            </div>
                        </div>
                    )}
                    {!aiLoading && !aiError && aiResult && aiResult.status === "ok" && (
                        <div className="flex items-start gap-2 text-sm">
                            <Sparkles className="h-4 w-4 shrink-0 mt-0.5 text-primary" />
                            <div className="text-foreground leading-relaxed">
                                {aiResult.reasoning}
                                <div className="mt-1 text-xs text-muted-foreground">
                                    {t("modeGatePicker.aiAutofilled")}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {options.map((opt) => {
                    const selected = strValue === opt.key;
                    const Icon = opt.icon && ICON_MAP[opt.icon]
                        ? ICON_MAP[opt.icon]
                        : opt.key === "ai_discover" ? Sparkles : Hand;
                    return (
                        <button
                            key={opt.key}
                            type="button"
                            onClick={() => { if (!disabled) onChange(opt.key, true); }}
                            disabled={disabled}
                            className={`group text-left p-5 rounded-2xl border-2 transition-all duration-200 ${
                                selected
                                    ? "border-primary bg-primary/5 shadow-md shadow-primary/10"
                                    : "border-border bg-card hover:border-primary/40 hover:bg-primary/[0.02]"
                            } ${disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
                        >
                            <div className="flex items-start gap-4">
                                <div
                                    className={`shrink-0 w-12 h-12 rounded-xl flex items-center justify-center transition-colors ${
                                        selected
                                            ? "bg-primary/15 text-primary"
                                            : "bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary"
                                    }`}
                                >
                                    <Icon className="h-6 w-6" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className="text-base font-semibold text-foreground">
                                            {opt.label}
                                        </span>
                                        <span
                                            className={`text-[10px] shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors ${
                                                selected
                                                    ? "border-primary bg-primary"
                                                    : "border-muted-foreground/40"
                                            }`}
                                        >
                                            {selected && (
                                                <span className="w-1.5 h-1.5 rounded-full bg-primary-foreground" />
                                            )}
                                        </span>
                                    </div>
                                    <p className="text-xs text-muted-foreground leading-relaxed mt-1.5">
                                        {opt.description}
                                    </p>
                                </div>
                            </div>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}

registerCustomField("mode_gate_picker", ModeGatePicker);

export default ModeGatePicker;
