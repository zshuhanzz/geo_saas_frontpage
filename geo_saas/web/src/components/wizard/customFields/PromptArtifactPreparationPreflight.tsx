import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, FileText, Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_BASE, fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";
import { promptArtifactInputFingerprint, redditRulesReviewComplete } from "./redditResearchUtils";

interface State {
    status?: "idle" | "loading" | "ready" | "stale" | "error";
    error?: string | null;
}

function toState(value: unknown): State {
    return value && typeof value === "object" ? (value as State) : { status: "idle" };
}

function PromptArtifactPreparationPreflight({ value, onChange, setFields, formState, context, disabled }: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const current = useMemo(() => toState(value), [value]);
    const [loading, setLoading] = useState(false);
    const [editText, setEditText] = useState("");
    const discovery = formState.reddit_discovery as Record<string, any> | undefined;
    const result = formState.derived_prompt_artifacts as Record<string, any> | undefined;
    const expectedFingerprint = promptArtifactInputFingerprint(formState);
    const discoveryReady = Boolean(discovery?.status === "ready" && redditRulesReviewComplete(discovery));
    const canRun = discoveryReady;
    const isStale = Boolean(result?.input_fingerprint && result.input_fingerprint !== expectedFingerprint);
    const rendered = typeof result?.rendered_sections === "string" ? result.rendered_sections : "";

    useEffect(() => {
        setEditText(rendered);
    }, [rendered]);

    const run = async () => {
        if (!context.clientId || !context.templateId || !canRun) return;
        setLoading(true);
        onChange({ ...current, status: "loading", error: null }, true);
        try {
            const data = await fetchJSON<Record<string, unknown>>(
                `${AGENT_BASE}/tasks/content/prompt-artifacts/preview`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        client_id: context.clientId,
                        template_id: context.templateId,
                        subreddit_targeting: formState.subreddit_targeting || null,
                        reddit_discovery: discovery,
                        citation_analysis_result: null,
                        strategy: null,
                        inputs: formState,
                    }),
                },
            );
            const next: Record<string, unknown> = {
                ...data,
                status: "ready",
                source: "wizard_confirmed",
                edited: false,
                input_fingerprint: expectedFingerprint,
            };
            setEditText(String(next.rendered_sections || ""));
            setFields?.({
                derived_prompt_artifacts: next,
                derived_prompt_artifacts_source: "wizard_confirmed",
                derived_prompt_artifacts_edited: false,
                prompt_artifact_preparation: { status: "ready", error: null },
            }, true);
        } catch (e) {
            const error = e instanceof Error ? e.message : String(e);
            onChange({ status: "error", error }, true);
        } finally {
            setLoading(false);
        }
    };

    const confirmEdit = () => {
        const next = {
            ...(result || {}),
            status: "ready",
            source: "wizard_confirmed",
            edited: true,
            rendered_sections: editText,
            input_fingerprint: expectedFingerprint,
        };
        setFields?.({
            derived_prompt_artifacts: next,
            derived_prompt_artifacts_source: "wizard_confirmed",
            derived_prompt_artifacts_edited: true,
            prompt_artifact_preparation: { status: "ready", error: null },
        }, true);
    };

    return (
        <div className="space-y-4">
            <div className="rounded-xl border border-primary/20 bg-primary/[0.03] p-4">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                        <FileText className="mt-0.5 h-4 w-4 text-primary" />
                        <div>
                            <div className="text-sm font-medium">{t("promptArtifactPreparation.title")}</div>
                            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                                {t("promptArtifactPreparation.description")}
                            </p>
                        </div>
                    </div>
                    <StatusBadge status={loading ? "loading" : isStale ? "stale" : current.status || (result ? "ready" : "idle")} />
                </div>
            </div>

            {!canRun && (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{discovery?.status === "ready" ? t("promptArtifactPreparation.rulesBlocked") : t("promptArtifactPreparation.blocked")}</span>
                </div>
            )}

            <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                    {t("promptArtifactPreparation.hint")}
                </p>
                <Button type="button" size="sm" onClick={run} disabled={disabled || loading || !canRun}>
                    {loading ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                    {result ? t("promptArtifactPreparation.regenerate") : t("promptArtifactPreparation.run")}
                </Button>
            </div>

            {current.status === "error" && current.error && (
                <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{current.error}</span>
                </div>
            )}

            {isStale && (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{t("promptArtifactPreparation.stale")}</span>
                </div>
            )}

            {result && (
                <div className="space-y-3 rounded-xl border border-border bg-card p-4">
                    <div className="flex items-center gap-2 text-sm font-medium">
                        <CheckCircle2 className="h-4 w-4 text-primary" />
                        {t("promptArtifactPreparation.ready")}
                    </div>
                    <Textarea
                        rows={12}
                        value={editText}
                        disabled={disabled}
                        onChange={(e) => setEditText(e.target.value)}
                    />
                    <div className="flex justify-end">
                        <Button type="button" size="sm" variant="outline" onClick={confirmEdit} disabled={disabled}>
                            {t("promptArtifactPreparation.confirmEdit")}
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}

function StatusBadge({ status }: { status: string }) {
    const { t } = useTranslation("wizard");
    const variant = status === "ready" ? "default" : status === "error" ? "destructive" : "outline";
    return <Badge variant={variant as any}>{t(`promptArtifactPreparation.status.${status}`, status)}</Badge>;
}

registerCustomField("prompt_artifact_preparation_preflight", PromptArtifactPreparationPreflight);

export default PromptArtifactPreparationPreflight;
