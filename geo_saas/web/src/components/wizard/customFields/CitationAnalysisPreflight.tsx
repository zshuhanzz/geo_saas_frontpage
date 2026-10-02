import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_BASE, fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";
import type { WizardDictionaryRow } from "../schema";
import {
    buildCitationAnalysisConfig,
    buildCitationAnalysisInputs,
    getCitationAnalysisResult,
} from "./citationAnalysisUtils";

type PreflightStatus = "idle" | "loading" | "ready" | "stale" | "error";

interface PreflightValue {
    status?: PreflightStatus;
    error?: string | null;
    fingerprint?: string | null;
    generated_at?: string | null;
}

function toValue(value: unknown): PreflightValue {
    return value && typeof value === "object" ? (value as PreflightValue) : {};
}

function CitationAnalysisPreflight({
    value,
    setFields,
    context,
    formState,
    disabled,
}: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const current = useMemo(() => toValue(value), [value]);
    const [loading, setLoading] = useState(false);
    const result = getCitationAnalysisResult(formState);
    const config = buildCitationAnalysisConfig(formState, context.template);
    const enabled = Boolean(config.enabled);

    const updateField = (key: string, next: unknown) => {
        setFields?.(
            {
                [key]: next,
                citation_analysis_result: undefined,
                citation_analysis_preflight: {
                    status: result ? "stale" : "idle",
                    error: null,
                    fingerprint: result?.fingerprint || null,
                    generated_at: result?.generated_at || null,
                },
            },
            true,
        );
    };

    const runPreview = async () => {
        if (!context.clientId || !context.templateId) return;
        setLoading(true);
        setFields?.({
            citation_analysis_preflight: {
                ...current,
                status: "loading",
                error: null,
            },
        }, true);
        try {
            const data = await fetchJSON<Record<string, unknown>>(
                `${AGENT_BASE}/tasks/content/citation-analysis/preview`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        client_id: context.clientId,
                        template_id: context.templateId,
                        inputs: buildCitationAnalysisInputs(formState, context.template),
                    }),
                },
            );
            setFields?.({
                citation_analysis_result: data,
                citation_analysis_preflight: {
                    status: data.enabled ? "ready" : "idle",
                    error: null,
                    fingerprint: data.fingerprint || null,
                    generated_at: data.generated_at || new Date().toISOString(),
                },
            }, true);
        } catch (e) {
            const error = e instanceof Error ? e.message : String(e);
            setFields?.({
                citation_analysis_preflight: {
                    status: "error",
                    error,
                    fingerprint: null,
                    generated_at: null,
                },
            }, true);
        } finally {
            setLoading(false);
        }
    };

    const sourceRows = context.dictionary.citation_source_scope || [];
    const policyRows = context.dictionary.citation_brand_mention_policy || [];
    const actionRows = context.dictionary.citation_action_strategy || [];
    const status = (current.status || (result ? "ready" : "idle")) as PreflightStatus;

    return (
        <div className="space-y-4">
            <div className="rounded-xl border border-primary/20 bg-primary/[0.03] p-4">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                        <Search className="h-4 w-4 mt-0.5 text-primary" />
                        <div>
                            <div className="text-sm font-medium">{t("citationAnalysis.title")}</div>
                            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                                {t("citationAnalysis.description")}
                            </p>
                        </div>
                    </div>
                    <StatusBadge status={status} />
                </div>
            </div>

            {!enabled && (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span>{t("citationAnalysis.disabled")}</span>
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <RefSelect
                    label={t("citationAnalysis.fields.sourceScope")}
                    value={String(config.citation_source_scope || "auto_by_template")}
                    rows={sourceRows}
                    disabled={disabled || loading || !enabled}
                    onChange={(v) => updateField("citation_source_scope", v)}
                />
                <RefSelect
                    label={t("citationAnalysis.fields.brandPolicy")}
                    value={String(config.citation_brand_mention_policy || "triage_all")}
                    rows={policyRows}
                    disabled={disabled || loading || !enabled}
                    onChange={(v) => updateField("citation_brand_mention_policy", v)}
                />
                <RefSelect
                    label={t("citationAnalysis.fields.actionStrategy")}
                    value={String(config.citation_action_strategy || "auto")}
                    rows={actionRows}
                    disabled={disabled || loading || !enabled}
                    onChange={(v) => updateField("citation_action_strategy", v)}
                />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div className="space-y-1.5">
                    <label className="text-xs font-medium">{t("citationAnalysis.fields.maxSources")}</label>
                    <Input
                        type="number"
                        min={1}
                        max={30}
                        value={Number(config.citation_max_sources || 10)}
                        disabled={disabled || loading || !enabled}
                        onChange={(e) => updateField("citation_max_sources", Number(e.target.value) || 10)}
                    />
                </div>
                <div className="flex items-center justify-between gap-3 rounded-md border border-border/60 px-3 py-2 md:col-span-3">
                    <div>
                        <div className="text-xs font-medium">{t("citationAnalysis.fields.fetchPages")}</div>
                        <p className="text-[11px] text-muted-foreground">{t("citationAnalysis.fetchHint")}</p>
                    </div>
                    <Switch
                        checked={Boolean(config.citation_fetch_full_pages)}
                        disabled={disabled || loading || !enabled}
                        onCheckedChange={(v) => updateField("citation_fetch_full_pages", v)}
                    />
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <LabeledInput
                    label={t("citationAnalysis.fields.includeDomains")}
                    value={String(config.citation_include_domains || "")}
                    disabled={disabled || loading || !enabled}
                    onChange={(v) => updateField("citation_include_domains", v)}
                />
                <LabeledInput
                    label={t("citationAnalysis.fields.excludeDomains")}
                    value={String(config.citation_exclude_domains || "")}
                    disabled={disabled || loading || !enabled}
                    onChange={(v) => updateField("citation_exclude_domains", v)}
                />
            </div>

            <div className="space-y-1.5">
                <label className="text-xs font-medium">{t("citationAnalysis.fields.queryOverride")}</label>
                <Textarea
                    rows={3}
                    value={String(config.citation_query_override || "")}
                    disabled={disabled || loading || !enabled}
                    onChange={(e) => updateField("citation_query_override", e.target.value)}
                    placeholder={t("citationAnalysis.queryPlaceholder")}
                />
            </div>

            <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    {t("citationAnalysis.runHint")}
                </p>
                <Button
                    type="button"
                    size="sm"
                    onClick={runPreview}
                    disabled={disabled || loading || !enabled || !context.clientId || !context.templateId}
                    className="shrink-0"
                >
                    {loading ? (
                        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    ) : (
                        <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    {t("citationAnalysis.run")}
                </Button>
            </div>

            {status === "error" && current.error && (
                <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span>{current.error}</span>
                </div>
            )}

            {result && <CitationResult result={result} />}
        </div>
    );
}

function StatusBadge({ status }: { status: PreflightStatus }) {
    const { t } = useTranslation("wizard");
    const variant = status === "ready" ? "default" : status === "error" ? "destructive" : "outline";
    return <Badge variant={variant}>{t(`citationAnalysis.status.${status}`)}</Badge>;
}

function RefSelect({
    label,
    value,
    rows,
    disabled,
    onChange,
}: {
    label: string;
    value: string;
    rows: WizardDictionaryRow[];
    disabled?: boolean;
    onChange: (value: string) => void;
}) {
    return (
        <div className="space-y-1.5">
            <label className="text-xs font-medium">{label}</label>
            <Select value={value} onValueChange={onChange} disabled={disabled || rows.length === 0}>
                <SelectTrigger className="h-9 text-xs">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {rows.map((row) => (
                        <SelectItem key={row.key} value={row.key}>
                            <span className="inline-flex items-center gap-1.5">
                                <span>{row.label}</span>
                                <code className="text-[9px] text-muted-foreground font-mono">{row.key}</code>
                            </span>
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    );
}

function LabeledInput({
    label,
    value,
    disabled,
    onChange,
}: {
    label: string;
    value: string;
    disabled?: boolean;
    onChange: (value: string) => void;
}) {
    return (
        <div className="space-y-1.5">
            <label className="text-xs font-medium">{label}</label>
            <Input value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
        </div>
    );
}

function CitationResult({ result }: { result: Record<string, unknown> }) {
    const { t } = useTranslation("wizard");
    const decision = (result.content_action_decision as Record<string, unknown> | undefined) || {};
    const summary = (result.brand_mention_summary as Record<string, number> | undefined) || {};
    const sourcePatterns =
        (result.citation_source_patterns as Record<string, unknown> | undefined) || {};
    const learnableStrengths = asStringArray(sourcePatterns.learnable_strengths);
    const visibilityGaps = asStringArray(sourcePatterns.visibility_gaps);
    const sources = Array.isArray(result.citation_sources)
        ? (result.citation_sources as Array<Record<string, unknown>>).slice(0, 6)
        : [];
    return (
        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.03] p-4 space-y-4">
            <div className="flex items-start gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-500 mt-0.5 shrink-0" />
                <div>
                    <div className="text-sm font-medium">{t("citationAnalysis.ready")}</div>
                    <p className="text-xs text-muted-foreground mt-1">
                        {t("citationAnalysis.primaryAction")}:{" "}
                        <code className="text-[11px]">{String(decision.primary_action || "n/a")}</code>
                    </p>
                </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {[
                    ["unmentioned", t("citationAnalysis.mentionStates.unmentioned")],
                    ["positive_neutral", t("citationAnalysis.mentionStates.positiveNeutral")],
                    ["negative_misleading", t("citationAnalysis.mentionStates.negativeMisleading")],
                    ["ambiguous", t("citationAnalysis.mentionStates.ambiguous")],
                ].map(([key, label]) => (
                    <div key={key} className="rounded-lg border border-border/60 bg-background/50 p-3">
                        <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
                        <div className="text-lg font-semibold mt-1">{summary[key] ?? 0}</div>
                    </div>
                ))}
            </div>

            {(learnableStrengths.length > 0 || visibilityGaps.length > 0) && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    <PatternList
                        title={t("citationAnalysis.learnableStrengths")}
                        description={t("citationAnalysis.learnableStrengthsDesc")}
                        items={learnableStrengths}
                    />
                    <PatternList
                        title={t("citationAnalysis.visibilityGaps")}
                        description={t("citationAnalysis.visibilityGapsDesc")}
                        items={visibilityGaps}
                    />
                </div>
            )}

            {sources.length > 0 && (
                <div className="space-y-2">
                    <div className="text-[11px] font-medium text-foreground">{t("citationAnalysis.topSources")}</div>
                    <div className="rounded-lg border border-border/60 divide-y divide-border/50 overflow-hidden">
                        {sources.map((source, idx) => (
                            <div key={`${source.url}-${idx}`} className="px-3 py-2 text-xs">
                                <div className="flex items-center justify-between gap-3">
                                    <span className="font-medium truncate">{String(source.domain || "unknown")}</span>
                                    <span className="text-[11px] text-muted-foreground">
                                        {String(source.citation_count || 0)} citations
                                    </span>
                                </div>
                                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                    <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                                        {String(source.fetch_status || "not_fetched")}
                                    </Badge>
                                    {Boolean(source.triage && typeof source.triage === "object") && (
                                        <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                                            {String((source.triage as Record<string, unknown>).mention_state || "unknown")}
                                        </Badge>
                                    )}
                                </div>
                                <div className="truncate text-[11px] text-primary mt-0.5">
                                    {String(source.url || "")}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

function asStringArray(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return value.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 8);
}

function PatternList({
    title,
    description,
    items,
}: {
    title: string;
    description: string;
    items: string[];
}) {
    return (
        <div className="rounded-lg border border-border/60 bg-background/50 p-3">
            <div className="text-[11px] font-medium text-foreground">{title}</div>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{description}</p>
            {items.length > 0 ? (
                <ul className="mt-2 space-y-1.5 text-xs text-foreground">
                    {items.map((item) => (
                        <li key={item} className="flex gap-2 leading-relaxed">
                            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                            <span>{item}</span>
                        </li>
                    ))}
                </ul>
            ) : (
                <div className="mt-2 text-xs text-muted-foreground">—</div>
            )}
        </div>
    );
}

registerCustomField("citation_analysis_preflight", CitationAnalysisPreflight);

export default CitationAnalysisPreflight;
