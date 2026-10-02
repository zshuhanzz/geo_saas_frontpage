import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Lock, RefreshCw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_BASE, fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

type RedditDiscoverySource = "p0_web_search" | "p1_reddit_api";
type RedditDiscoveryStatus = "idle" | "loading" | "ready" | "error";

interface RedditDiscoveryValue {
    source: RedditDiscoverySource;
    reddit_urls: string;
    subreddits: string;
    keywords: string;
    status: RedditDiscoveryStatus;
    data: Record<string, any> | null;
    error: string | null;
}

const DEFAULT_VALUE: RedditDiscoveryValue = {
    source: "p0_web_search",
    reddit_urls: "",
    subreddits: "",
    keywords: "",
    status: "idle",
    data: null,
    error: null,
};

function toValue(value: unknown): RedditDiscoveryValue {
    if (!value || typeof value !== "object") return { ...DEFAULT_VALUE };
    const obj = value as Partial<RedditDiscoveryValue>;
    return {
        source: obj.source === "p1_reddit_api" ? "p1_reddit_api" : "p0_web_search",
        reddit_urls: obj.reddit_urls || "",
        subreddits: obj.subreddits || "",
        keywords: obj.keywords || "",
        status: obj.status || "idle",
        data: obj.data || null,
        error: obj.error || null,
    };
}

function RedditDiscoveryConfig({
    value,
    onChange,
    formState,
    context,
    disabled,
}: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const current = useMemo(() => toValue(value), [value]);
    const [loading, setLoading] = useState(false);

    const update = (patch: Partial<RedditDiscoveryValue>, userEdited = true) => {
        onChange({ ...current, ...patch }, userEdited);
    };

    const runDiscover = async () => {
        if (!context.clientId || current.source !== "p0_web_search") return;
        setLoading(true);
        update({ status: "loading", error: null }, true);
        try {
            const data = await fetchJSON(`${AGENT_BASE}/tasks/reddit/discover`, {
                method: "POST",
                body: JSON.stringify({
                    client_id: context.clientId,
                    source: current.source,
                    reddit_urls: current.reddit_urls,
                    subreddits: current.subreddits,
                    keywords: current.keywords,
                    topic_ids: (formState.topic_ids as string[] | undefined) || [],
                    prompt_ids: (formState.prompt_ids as string[] | undefined) || [],
                    content_type:
                        (formState.default as string | undefined) ||
                        (formState.content_type as string | undefined) ||
                        "",
                }),
            });
            onChange({ ...current, status: "ready", data, error: null }, true);
        } catch (e) {
            const error = e instanceof Error ? e.message : String(e);
            onChange({ ...current, status: "error", error }, true);
        } finally {
            setLoading(false);
        }
    };

    const p1Selected = current.source === "p1_reddit_api";
    const ready = current.status === "ready" && current.data;
    const summary = typeof current.data?.summary === "string" ? current.data.summary : "";
    const questions = Array.isArray(current.data?.community_questions)
        ? current.data.community_questions.slice(0, 4)
        : [];
    const angles = Array.isArray(current.data?.content_angles)
        ? current.data.content_angles.slice(0, 3)
        : [];
    const risks = Array.isArray(current.data?.risks)
        ? current.data.risks.slice(0, 3)
        : [];

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <button
                    type="button"
                    disabled={disabled || loading}
                    onClick={() => update({ source: "p0_web_search" })}
                    className={`text-left rounded-xl border p-4 transition-colors ${
                        current.source === "p0_web_search"
                            ? "border-primary bg-primary/5"
                            : "border-border bg-card hover:border-primary/30"
                    }`}
                >
                    <div className="flex items-start gap-3">
                        <Search className="h-4 w-4 mt-0.5 text-primary" />
                        <div>
                            <div className="text-sm font-medium">{t("redditDiscovery.sources.p0.title")}</div>
                            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                                {t("redditDiscovery.sources.p0.description")}
                            </p>
                        </div>
                    </div>
                </button>

                <button
                    type="button"
                    disabled={disabled || loading}
                    onClick={() => update({ source: "p1_reddit_api" })}
                    className={`text-left rounded-xl border p-4 transition-colors ${
                        p1Selected ? "border-primary bg-primary/5" : "border-border bg-muted/20"
                    }`}
                    title={t("redditDiscovery.sources.p1.todo")}
                >
                    <div className="flex items-start gap-3">
                        <Lock className="h-4 w-4 mt-0.5 text-muted-foreground" />
                        <div>
                            <div className="text-sm font-medium">{t("redditDiscovery.sources.p1.title")}</div>
                            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                                {t("redditDiscovery.sources.p1.description")}
                            </p>
                            <span className="inline-flex mt-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-500">
                                {t("redditDiscovery.sources.p1.todo")}
                            </span>
                        </div>
                    </div>
                </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="space-y-1.5">
                    <label className="text-xs font-medium">{t("redditDiscovery.inputs.urls")}</label>
                    <Textarea
                        rows={4}
                        value={current.reddit_urls}
                        disabled={disabled || loading || p1Selected}
                        onChange={(e) => update({ reddit_urls: e.target.value, status: "idle" })}
                        placeholder={t("redditDiscovery.placeholders.urls")}
                    />
                </div>
                <div className="space-y-1.5">
                    <label className="text-xs font-medium">{t("redditDiscovery.inputs.subreddits")}</label>
                    <Textarea
                        rows={4}
                        value={current.subreddits}
                        disabled={disabled || loading || p1Selected}
                        onChange={(e) => update({ subreddits: e.target.value, status: "idle" })}
                        placeholder={t("redditDiscovery.placeholders.subreddits")}
                    />
                </div>
                <div className="space-y-1.5">
                    <label className="text-xs font-medium">{t("redditDiscovery.inputs.keywords")}</label>
                    <Textarea
                        rows={4}
                        value={current.keywords}
                        disabled={disabled || loading || p1Selected}
                        onChange={(e) => update({ keywords: e.target.value, status: "idle" })}
                        placeholder={t("redditDiscovery.placeholders.keywords")}
                    />
                </div>
            </div>

            <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    {t("redditDiscovery.hint")}
                </p>
                <Button
                    type="button"
                    size="sm"
                    onClick={runDiscover}
                    disabled={disabled || loading || p1Selected || !context.clientId}
                    className="shrink-0"
                >
                    {loading ? (
                        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    ) : (
                        <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    {t("redditDiscovery.run")}
                </Button>
            </div>

            {current.status === "error" && current.error && (
                <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span>{current.error}</span>
                </div>
            )}

            {ready && (
                <div className="rounded-xl border border-primary/20 bg-primary/[0.03] p-4 space-y-3">
                    <div className="flex items-start gap-2">
                        <CheckCircle2 className="h-4 w-4 text-primary mt-0.5 shrink-0" />
                        <div>
                            <div className="text-sm font-medium">{t("redditDiscovery.ready")}</div>
                            {summary && (
                                <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                                    {summary}
                                </p>
                            )}
                        </div>
                    </div>

                    {(questions.length > 0 || angles.length > 0 || risks.length > 0) && (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                            {questions.length > 0 && (
                                <InsightList title={t("redditDiscovery.preview.questions")} items={questions} />
                            )}
                            {angles.length > 0 && (
                                <InsightList
                                    title={t("redditDiscovery.preview.angles")}
                                    items={angles.map((a) => a?.angle || JSON.stringify(a))}
                                />
                            )}
                            {risks.length > 0 && (
                                <InsightList title={t("redditDiscovery.preview.risks")} items={risks} />
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function InsightList({ title, items }: { title: string; items: string[] }) {
    return (
        <div className="rounded-lg border border-border/60 bg-background/50 p-3">
            <div className="text-[11px] font-medium text-foreground mb-2">{title}</div>
            <ul className="space-y-1.5">
                {items.map((item, idx) => (
                    <li key={idx} className="text-[11px] text-muted-foreground leading-relaxed">
                        {item}
                    </li>
                ))}
            </ul>
        </div>
    );
}

registerCustomField("reddit_discovery_config", RedditDiscoveryConfig);

export default RedditDiscoveryConfig;
