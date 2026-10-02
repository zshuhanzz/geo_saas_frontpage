import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_BASE, fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

type OfficialWebsiteDiscoverySource = "p0_web_search";
type OfficialWebsiteDiscoveryStatus = "idle" | "loading" | "ready" | "error";

interface OfficialWebsiteDiscoveryValue {
    source: OfficialWebsiteDiscoverySource;
    official_website_urls: string;
    status: OfficialWebsiteDiscoveryStatus;
    data: Record<string, any> | null;
    error: string | null;
}

const DEFAULT_VALUE: OfficialWebsiteDiscoveryValue = {
    source: "p0_web_search",
    official_website_urls: "",
    status: "idle",
    data: null,
    error: null,
};

function toValue(value: unknown): OfficialWebsiteDiscoveryValue {
    if (!value || typeof value !== "object") return { ...DEFAULT_VALUE };
    const obj = value as Partial<OfficialWebsiteDiscoveryValue>;
    return {
        source: "p0_web_search",
        official_website_urls: obj.official_website_urls || "",
        status: obj.status || "idle",
        data: obj.data || null,
        error: obj.error || null,
    };
}

function OfficialWebsiteDiscoveryConfig({
    value,
    onChange,
    formState,
    context,
    disabled,
}: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const current = useMemo(() => toValue(value), [value]);
    const [loading, setLoading] = useState(false);

    const update = (patch: Partial<OfficialWebsiteDiscoveryValue>, userEdited = true) => {
        onChange({ ...current, ...patch }, userEdited);
    };

    const runDiscover = async () => {
        if (!context.clientId || !current.official_website_urls.trim()) return;
        setLoading(true);
        update({ status: "loading", error: null }, true);
        try {
            const data = await fetchJSON(`${AGENT_BASE}/tasks/official-website/discover`, {
                method: "POST",
                body: JSON.stringify({
                    client_id: context.clientId,
                    source: current.source,
                    official_website_urls: current.official_website_urls,
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

    const ready = current.status === "ready" && current.data;
    const summary = typeof current.data?.summary === "string" ? current.data.summary : "";
    const gaps = Array.isArray(current.data?.content_gaps)
        ? current.data.content_gaps.slice(0, 4)
        : [];
    const useCases = Array.isArray(current.data?.missing_use_cases)
        ? current.data.missing_use_cases.slice(0, 3)
        : [];
    const angles = Array.isArray(current.data?.recommended_article_angles)
        ? current.data.recommended_article_angles.slice(0, 3)
        : [];

    return (
        <div className="space-y-4">
            <div className="rounded-xl border border-primary/25 bg-primary/[0.03] p-4">
                <div className="flex items-start gap-3">
                    <Search className="h-4 w-4 mt-0.5 text-primary" />
                    <div>
                        <div className="text-sm font-medium">{t("officialWebsiteDiscovery.source.title")}</div>
                        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                            {t("officialWebsiteDiscovery.source.description")}
                        </p>
                    </div>
                </div>
            </div>

            <div className="space-y-1.5">
                <label className="text-xs font-medium">{t("officialWebsiteDiscovery.inputs.urls")}</label>
                <Textarea
                    rows={5}
                    value={current.official_website_urls}
                    disabled={disabled || loading}
                    onChange={(e) => update({ official_website_urls: e.target.value, status: "idle" })}
                    placeholder={t("officialWebsiteDiscovery.placeholders.urls")}
                />
            </div>

            <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    {t("officialWebsiteDiscovery.hint")}
                </p>
                <Button
                    type="button"
                    size="sm"
                    onClick={runDiscover}
                    disabled={disabled || loading || !context.clientId || !current.official_website_urls.trim()}
                    className="shrink-0"
                >
                    {loading ? (
                        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    ) : (
                        <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    {t("officialWebsiteDiscovery.run")}
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
                            <div className="text-sm font-medium">{t("officialWebsiteDiscovery.ready")}</div>
                            {summary && (
                                <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                                    {summary}
                                </p>
                            )}
                        </div>
                    </div>

                    {(gaps.length > 0 || useCases.length > 0 || angles.length > 0) && (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                            {gaps.length > 0 && (
                                <InsightList title={t("officialWebsiteDiscovery.preview.gaps")} items={gaps} />
                            )}
                            {useCases.length > 0 && (
                                <InsightList title={t("officialWebsiteDiscovery.preview.useCases")} items={useCases} />
                            )}
                            {angles.length > 0 && (
                                <InsightList
                                    title={t("officialWebsiteDiscovery.preview.angles")}
                                    items={angles.map((a) => a?.angle || JSON.stringify(a))}
                                />
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

registerCustomField("official_website_discovery_config", OfficialWebsiteDiscoveryConfig);

export default OfficialWebsiteDiscoveryConfig;
