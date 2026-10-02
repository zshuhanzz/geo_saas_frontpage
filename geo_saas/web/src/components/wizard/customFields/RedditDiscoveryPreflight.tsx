import { useMemo, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_BASE, fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";
import { RedditLinkedText, SubredditNameLink, SubredditQuickLinks } from "./RedditLinks";
import { normalizeSubredditKey, redditDiscoveryInputFingerprint, redditRulesReviewComplete } from "./redditResearchUtils";

interface State {
    status?: "idle" | "loading" | "ready" | "stale" | "error";
    error?: string | null;
}

function toState(value: unknown): State {
    return value && typeof value === "object" ? (value as State) : { status: "idle" };
}

function RedditDiscoveryPreflight({ value, onChange, setFields, formState, context, disabled }: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const current = useMemo(() => toState(value), [value]);
    const [loading, setLoading] = useState(false);
    const targeting = formState.subreddit_targeting as Record<string, any> | undefined;
    const result = formState.reddit_discovery as Record<string, any> | undefined;
    const selectedSubreddits = Array.isArray(targeting?.selected_subreddits) ? targeting.selected_subreddits.slice(0, 1) : [];
    const canRun = Boolean(targeting?.status === "ready" && selectedSubreddits.length > 0);
    const expectedFingerprint = redditDiscoveryInputFingerprint(formState);
    const isStale = Boolean(result?.input_fingerprint && result.input_fingerprint !== expectedFingerprint);
    const rulesReviewed = redditRulesReviewComplete(result);

    const run = async () => {
        if (!context.clientId || !context.templateId || !canRun) return;
        setLoading(true);
        onChange({ ...current, status: "loading", error: null }, true);
        try {
            const data = await fetchJSON<Record<string, unknown>>(
                `${AGENT_BASE}/tasks/content/reddit-discovery/preview`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        client_id: context.clientId,
                        template_id: context.templateId,
                        subreddit_targeting: {
                            ...(targeting || {}),
                            selected_subreddits: selectedSubreddits,
                        },
                        inputs: formState,
                    }),
                },
            );
            const reviewComplete = redditRulesReviewComplete(data);
            setFields?.({
                reddit_discovery: { ...data, input_fingerprint: expectedFingerprint, rules_review_complete: reviewComplete },
                reddit_discovery_preflight: { status: reviewComplete ? "ready" : "error", error: reviewComplete ? null : t("redditResearchDiscovery.reviewRequired"), input_fingerprint: expectedFingerprint },
                derived_prompt_artifacts: undefined,
                prompt_artifact_preparation: { status: "stale" },
            }, true);
        } catch (e) {
            const error = e instanceof Error ? e.message : String(e);
            onChange({ status: "error", error }, true);
        } finally {
            setLoading(false);
        }
    };

    const subreddits = Array.isArray(result?.subreddits) ? result.subreddits : [];
    const status = loading ? "loading" : isStale ? "stale" : current.status || (result ? (rulesReviewed ? "ready" : "error") : "idle");
    const updateSubredditReview = (item: any, patch: Record<string, unknown>) => {
        const key = normalizeSubredditKey(item);
        const nextSubreddits = subreddits.map((row: any) => (
            normalizeSubredditKey(row) === key ? { ...row, ...patch } : row
        ));
        const nextDiscovery = { ...(result || {}), subreddits: nextSubreddits, input_fingerprint: expectedFingerprint };
        const reviewComplete = redditRulesReviewComplete(nextDiscovery);
        setFields?.({
            reddit_discovery: { ...nextDiscovery, rules_review_complete: reviewComplete },
            reddit_discovery_preflight: {
                status: reviewComplete ? "ready" : "error",
                error: reviewComplete ? null : t("redditResearchDiscovery.reviewRequired"),
                input_fingerprint: expectedFingerprint,
            },
            derived_prompt_artifacts: undefined,
            prompt_artifact_preparation: { status: "stale" },
        }, true);
    };

    return (
        <div className="space-y-4">
            <div className="rounded-xl border border-primary/20 bg-primary/[0.03] p-4">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                        <ShieldCheck className="mt-0.5 h-4 w-4 text-primary" />
                        <div>
                            <div className="text-sm font-medium">{t("redditResearchDiscovery.title")}</div>
                            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                                {t("redditResearchDiscovery.description")}
                            </p>
                        </div>
                    </div>
                    <StatusBadge status={status} />
                </div>
            </div>

            {!canRun && (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{t("redditResearchDiscovery.blocked")}</span>
                </div>
            )}

            <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                    {t("redditResearchDiscovery.hint")}
                </p>
                <Button type="button" size="sm" onClick={run} disabled={disabled || loading || !canRun}>
                    {loading ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                    {t("redditResearchDiscovery.run")}
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
                    <span>{t("redditResearchDiscovery.stale")}</span>
                </div>
            )}

            {subreddits.length > 0 && (
                <div className="space-y-3">
                    {subreddits.map((item: any, idx: number) => (
                        <div key={`${item.name || idx}`} className="rounded-xl border border-border bg-card p-4">
                            <div className="mb-3 flex items-center justify-between gap-2">
                                <div className="text-sm font-semibold">
                                    <SubredditNameLink item={item} />
                                </div>
                                <Badge variant={item.rules_status === "verified" ? "default" : "outline"}>
                                    {item.rules_status || "unavailable"}
                                </Badge>
                            </div>
                            <SubredditQuickLinks item={item} rulesSourceUrl={item.rules_source_url} />
                            {item.metadata && (
                                <div className="mb-3 mt-3 grid gap-2 rounded-lg border border-border/60 bg-background/40 p-3 text-xs md:grid-cols-3">
                                    <Metric label={t("redditResearchDiscovery.metadata.subscribers")} value={formatNumber(item.metadata.subscribers)} />
                                    <Metric label={t("redditResearchDiscovery.metadata.active")} value={formatNumber(item.metadata.active_user_count)} />
                                    <Metric label={t("redditResearchDiscovery.metadata.type")} value={item.metadata.subreddit_type || "unknown"} />
                                    <Metric label={t("redditResearchDiscovery.metadata.nsfw")} value={item.metadata.over18 ? t("redditResearchDiscovery.boolean.yes") : t("redditResearchDiscovery.boolean.no")} />
                                    <Metric label={t("redditResearchDiscovery.metadata.submission")} value={item.submission_type || item.metadata.submission_type || "unknown"} />
                                    <Metric label={t("redditResearchDiscovery.metadata.source")} value={item.metadata.source || result?.provider || "unknown"} />
                                </div>
                            )}
                            {item.posting_capability && Object.keys(item.posting_capability).length > 0 && (
                                <div className="mb-3 flex flex-wrap gap-1.5">
                                    {Object.entries(item.posting_capability).map(([key, enabled]) => (
                                        <Badge key={key} variant={enabled ? "secondary" : "outline"} className="text-[10px]">
                                            {key}: {enabled ? t("redditResearchDiscovery.boolean.yes") : t("redditResearchDiscovery.boolean.no")}
                                        </Badge>
                                    ))}
                                </div>
                            )}
                            {Array.isArray(item.rules) && item.rules.length > 0 ? (
                                <ul className="space-y-2">
                                    {item.rules.slice(0, 8).map((rule: any, ruleIdx: number) => (
                                        <li key={ruleIdx} className="text-xs leading-relaxed">
                                            <span className="font-medium">{rule.short_name}</span>
                                            {rule.description && (
                                                <span className="text-muted-foreground"> — <RedditLinkedText>{rule.description}</RedditLinkedText></span>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="text-xs text-muted-foreground">{t("redditResearchDiscovery.noRules")}</p>
                            )}
                            {item.rules_status !== "verified" && (
                                <div className="mt-3 space-y-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                                    <p className="text-xs text-amber-500">{t("redditResearchDiscovery.reviewRequired")}</p>
                                    <Textarea
                                        rows={4}
                                        disabled={disabled || loading || Boolean(item.rules_skip_confirmed)}
                                        value={String(item.rules_manual_override || "")}
                                        onChange={(e) => updateSubredditReview(item, {
                                            rules_manual_override: e.target.value,
                                            rules_skip_confirmed: false,
                                        })}
                                        placeholder={t("redditResearchDiscovery.manualRulesPlaceholder")}
                                    />
                                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                                        <Checkbox
                                            checked={Boolean(item.rules_skip_confirmed)}
                                            disabled={disabled || loading}
                                            onCheckedChange={(v) => updateSubredditReview(item, {
                                                rules_skip_confirmed: Boolean(v),
                                                rules_manual_override: Boolean(v) ? "" : item.rules_manual_override,
                                            })}
                                        />
                                        <span>{t("redditResearchDiscovery.skipRules")}</span>
                                    </label>
                                </div>
                            )}
                            {item.posts && (
                                <div className="mt-4 grid gap-3 md:grid-cols-2">
                                    {(["search", "hot", "top", "new"] as const).map((kind) => {
                                        const posts = Array.isArray(item.posts?.[kind]) ? item.posts[kind] : [];
                                        if (posts.length === 0) return null;
                                        return (
                                            <div key={kind} className="rounded-lg border border-border/60 bg-background/30 p-3">
                                                <div className="mb-2 text-xs font-medium">{t(`redditResearchDiscovery.posts.${kind}`)}</div>
                                                <ul className="space-y-1.5">
                                                    {posts.slice(0, 3).map((post: any, postIdx: number) => (
                                                        <li key={`${kind}-${postIdx}`} className="text-[11px] leading-relaxed text-muted-foreground">
                                                            <span className="text-foreground">{post.title}</span>
                                                            <span className="ml-1">({formatNumber(post.score)} / {formatNumber(post.num_comments)})</span>
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                            {item.risk_signals && (
                                <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                                    <div className="mb-1 text-xs font-medium text-amber-500">{t("redditResearchDiscovery.riskSignals")}</div>
                                    <div className="space-y-1 text-[11px] text-muted-foreground">
                                        {(Array.isArray(item.risks) ? item.risks : []).slice(0, 3).map((risk: string, riskIdx: number) => (
                                            <div key={riskIdx}><RedditLinkedText>{risk}</RedditLinkedText></div>
                                        ))}
                                        {(Array.isArray(item.objections) ? item.objections : []).slice(0, 2).map((risk: string, riskIdx: number) => (
                                            <div key={`obj-${riskIdx}`}><RedditLinkedText>{risk}</RedditLinkedText></div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function StatusBadge({ status }: { status: string }) {
    const { t } = useTranslation("wizard");
    const variant = status === "ready" ? "default" : status === "error" ? "destructive" : "outline";
    return <Badge variant={variant as any}>{t(`redditResearchDiscovery.status.${status}`, status)}</Badge>;
}

function Metric({ label, value }: { label: string; value: unknown }) {
    return (
        <div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
            <div className="mt-0.5 truncate font-medium">{String(value || "--")}</div>
        </div>
    );
}

function formatNumber(value: unknown): string {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return "--";
    return new Intl.NumberFormat().format(num);
}

registerCustomField("reddit_discovery_preflight", RedditDiscoveryPreflight);

export default RedditDiscoveryPreflight;
