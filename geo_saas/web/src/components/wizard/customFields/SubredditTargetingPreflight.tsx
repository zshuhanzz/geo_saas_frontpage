import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AGENT_BASE, fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";
import { RedditLinkedText, SubredditNameLink, SubredditQuickLinks } from "./RedditLinks";
import { normalizeSubredditKey, subredditTargetingInputFingerprint } from "./redditResearchUtils";

type Mode = "reddit_api" | "ai_recommend" | "manual";

interface State {
    mode?: Mode;
    keywords?: string;
    manual_subreddits?: string;
    status?: "idle" | "loading" | "ready" | "error";
    error?: string | null;
}

function toState(value: unknown): State {
    return value && typeof value === "object" ? (value as State) : { mode: "ai_recommend", status: "idle" };
}

function SubredditTargetingPreflight({ value, onChange, setFields, formState, context, disabled }: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const current = useMemo(() => toState(value), [value]);
    const [loading, setLoading] = useState(false);
    const result = formState.subreddit_targeting as Record<string, any> | undefined;
    const mode = current.mode || "ai_recommend";
    const expectedFingerprint = subredditTargetingInputFingerprint(
        formState,
        mode,
        current.keywords || "",
        current.manual_subreddits || "",
    );
    const isStale = Boolean(result?.input_fingerprint && result.input_fingerprint !== expectedFingerprint);

    const update = (patch: Partial<State>, userEdited = true) => {
        onChange({ ...current, ...patch }, userEdited);
    };

    const run = async () => {
        if (!context.clientId || !context.templateId) return;
        setLoading(true);
        update({ status: "loading", error: null }, true);
        try {
            const data = await fetchJSON<Record<string, unknown>>(
                `${AGENT_BASE}/tasks/content/subreddit-targeting/preview`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        client_id: context.clientId,
                        template_id: context.templateId,
                        mode,
                        manual_subreddits: current.manual_subreddits || "",
                        keywords: current.keywords || "",
                        inputs: {
                            ...formState,
                            citation_analysis_result: null,
                            content_type: formState.default || formState.content_type,
                        },
                    }),
                },
            );
            const candidateSubreddits = Array.isArray(data.candidate_subreddits) ? data.candidate_subreddits : [];
            const nextStatus = data.status === "ready" && candidateSubreddits.length > 0 ? "ready" : "error";
            const selectedSubreddits = Array.isArray(data.selected_subreddits) && data.selected_subreddits.length > 0
                ? [data.selected_subreddits[0]]
                : candidateSubreddits.length > 0
                  ? [candidateSubreddits[0]]
                  : [];
            const nextError =
                nextStatus === "ready"
                    ? null
                    : typeof data.error === "string" && data.error
                      ? data.error
                      : t("subredditTargeting.errors.noCandidates");
            setFields?.({
                subreddit_targeting: {
                    ...data,
                    status: nextStatus,
                    candidate_subreddits: candidateSubreddits,
                    selected_subreddits: nextStatus === "ready" ? selectedSubreddits : [],
                    input_fingerprint: expectedFingerprint,
                },
                subreddit_targeting_preflight: { ...current, status: nextStatus, error: nextError, input_fingerprint: expectedFingerprint },
                reddit_discovery: undefined,
                reddit_discovery_preflight: { status: "stale" },
                derived_prompt_artifacts: undefined,
                prompt_artifact_preparation: { status: "stale" },
            }, true);
        } catch (e) {
            const error = e instanceof Error ? e.message : String(e);
            update({ status: "error", error }, true);
        } finally {
            setLoading(false);
        }
    };

    const candidates = Array.isArray(result?.candidate_subreddits) ? result.candidate_subreddits : [];
    const selected = Array.isArray(result?.selected_subreddits) ? result.selected_subreddits.slice(0, 1) : [];
    const selectedKeys = new Set(selected.map(normalizeSubredditKey));
    const selectCandidate = (item: any) => {
        const next = [item];
        setFields?.({
            subreddit_targeting: {
                ...(result || {}),
                status: "ready",
                candidate_subreddits: candidates,
                selected_subreddits: next,
                input_fingerprint: expectedFingerprint,
            },
            subreddit_targeting_preflight: {
                ...current,
                status: "ready",
                error: null,
                input_fingerprint: expectedFingerprint,
            },
            reddit_discovery: undefined,
            reddit_discovery_preflight: { status: "stale" },
            derived_prompt_artifacts: undefined,
            prompt_artifact_preparation: { status: "stale" },
        }, true);
    };
    const resultStatus = result?.status === "error" ? "error" : result ? "ready" : "idle";
    const status = loading ? "loading" : isStale ? "stale" : current.status || resultStatus;

    return (
        <div className="space-y-4">
            <div className="rounded-xl border border-primary/20 bg-primary/[0.03] p-4">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                        <Search className="mt-0.5 h-4 w-4 text-primary" />
                        <div>
                            <div className="text-sm font-medium">{t("subredditTargeting.title")}</div>
                            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                                {t("subredditTargeting.description")}
                            </p>
                        </div>
                    </div>
                    <StatusBadge status={status} />
                </div>
            </div>

            <Tabs value={mode} onValueChange={(v) => update({ mode: v as Mode })}>
                <TabsList>
                    <TabsTrigger value="reddit_api" disabled={disabled || loading}>
                        {t("subredditTargeting.modes.redditApi")}
                    </TabsTrigger>
                    <TabsTrigger value="ai_recommend" disabled={disabled || loading}>
                        {t("subredditTargeting.modes.ai")}
                    </TabsTrigger>
                    <TabsTrigger value="manual" disabled={disabled || loading}>
                        {t("subredditTargeting.modes.manual")}
                    </TabsTrigger>
                </TabsList>
            </Tabs>

            {mode === "reddit_api" && (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{t("subredditTargeting.redditApiPending")}</span>
                </div>
            )}

            {mode === "ai_recommend" || mode === "reddit_api" ? (
                <div className="space-y-1.5">
                    <label className="text-xs font-medium">{t("subredditTargeting.keywords")}</label>
                    <Textarea
                        rows={3}
                        value={current.keywords || ""}
                        disabled={disabled || loading}
                        onChange={(e) => update({ keywords: e.target.value, status: "idle" })}
                        placeholder={t("subredditTargeting.keywordsPlaceholder")}
                    />
                </div>
            ) : (
                <div className="space-y-1.5">
                    <label className="text-xs font-medium">{t("subredditTargeting.manual")}</label>
                    <Textarea
                        rows={4}
                        value={current.manual_subreddits || ""}
                        disabled={disabled || loading}
                        onChange={(e) => update({ manual_subreddits: e.target.value, status: "idle" })}
                        placeholder={t("subredditTargeting.manualPlaceholder")}
                    />
                </div>
            )}

            <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                    {t("subredditTargeting.hint")}
                </p>
                <Button type="button" size="sm" onClick={run} disabled={disabled || loading || !context.clientId}>
                    {loading ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                    {t("subredditTargeting.run")}
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
                    <span>{t("subredditTargeting.stale")}</span>
                </div>
            )}

            {candidates.length > 0 && (
                <div className="rounded-xl border border-border bg-background/50 p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                        <CheckCircle2 className="h-4 w-4 text-primary" />
                        {t("subredditTargeting.selected", { count: selected.length })}
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                        {candidates.map((item: any, idx: number) => {
                            const checked = selectedKeys.has(normalizeSubredditKey(item));
                            return (
                            <div key={`${item.name || idx}`} className="rounded-lg border border-border/70 bg-card p-3">
                                <div className="flex items-center justify-between gap-2">
                                    <label className="flex min-w-0 items-center gap-2 text-sm font-medium">
                                        <Checkbox checked={checked} disabled={disabled || loading} onCheckedChange={() => selectCandidate(item)} />
                                        <SubredditNameLink item={item} className="truncate" />
                                    </label>
                                    <Badge variant="outline">{item.source || result?.provider || "web_grounded"}</Badge>
                                </div>
                                <SubredditQuickLinks item={item} />
                                {item.relevance_reason && (
                                    <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                                        <RedditLinkedText>{item.relevance_reason}</RedditLinkedText>
                                    </p>
                                )}
                                {item.posting_risk && (
                                    <p className="mt-2 text-[11px] leading-relaxed text-amber-500">
                                        <RedditLinkedText>{item.posting_risk}</RedditLinkedText>
                                    </p>
                                )}
                            </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}

function StatusBadge({ status }: { status: string }) {
    const { t } = useTranslation("wizard");
    const variant = status === "ready" ? "default" : status === "error" ? "destructive" : "outline";
    return <Badge variant={variant as any}>{t(`subredditTargeting.status.${status}`, status)}</Badge>;
}

registerCustomField("subreddit_targeting_preflight", SubredditTargetingPreflight);

export default SubredditTargetingPreflight;
