/**
 * TopicRefPicker — topic-level analogue of PromptRefPicker.
 *
 * Registered under the custom field type `topic_ref_picker`. The wizard
 * step displays the client's topics ranked worst-first along one of three
 * underperformance dimensions (visibility / citation / sentiment), each
 * tagged with a tier badge (🔴 表现差 / 🟡 待优化) so the user can spot
 * which topic needs content work the most. A one-click "auto-prefill"
 * button selects the N worst-performing topics.
 *
 * Backing endpoint: `GET /api/agent/tasks/topics/ranked?...` — aggregates
 * own-brand mentions / own-domain citations / negative sentiment per
 * topic by rolling up all active prompts under that topic. See
 * `geo_agent/src/routers/tasks.py::get_ranked_topics`.
 *
 * Form value: either `string` (single topic id) when field.config.single,
 * or `string[]` (multi-select) otherwise. Default is multi-select since
 * content templates may target several adjacent topics.
 */
import { useEffect, useMemo, useState } from "react";
import { ArrowUpDown, Loader2, AlertTriangle, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getRankedTopics } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

interface TopicItem {
    id: string;
    topic_name: string;
    prompt_count: number;
    mention_count: number;
    citation_count: number;
    negative_count: number;
}

type SortMode = "visibility" | "citation" | "sentiment";

const SORT_OPTIONS: { id: SortMode; label: string }[] = [
    { id: "visibility", label: "Visibility" },
    { id: "citation", label: "Citation" },
    { id: "sentiment", label: "Sentiment" },
];

/** Same tier classifier as PromptRefPicker. Backend sorts worst→best,
 *  so the list index IS the rank. */
type PerfTier = "critical" | "attention" | "healthy";
function classifyPerformanceTier(index: number, total: number): PerfTier {
    if (total < 6) {
        return index < Math.ceil(total / 3) ? "critical" : "attention";
    }
    if (index < 3) return "critical";   // bottom 3 topics = critical
    if (index < 8) return "attention";
    return "healthy";
}

function TopicScoreBadges({
    topic,
    sortBy,
}: {
    topic: TopicItem;
    sortBy: SortMode;
}) {
    return (
        <div className="flex items-center gap-1.5 mt-1">
            <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                    sortBy === "visibility"
                        ? "bg-blue-500/10 text-blue-400 font-medium"
                        : "text-muted-foreground"
                }`}
            >
                Mentions {topic.mention_count}
            </span>
            <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                    sortBy === "citation"
                        ? "bg-green-500/10 text-green-400 font-medium"
                        : "text-muted-foreground"
                }`}
            >
                Citations {topic.citation_count}
            </span>
            <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                    sortBy === "sentiment"
                        ? "bg-red-500/10 text-red-400 font-medium"
                        : "text-muted-foreground"
                }`}
            >
                Negative {topic.negative_count}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded text-muted-foreground">
                {topic.prompt_count} prompt{topic.prompt_count !== 1 ? "s" : ""}
            </span>
        </div>
    );
}

function TopicRefPicker({
    field,
    value,
    onChange,
    context,
    formState,
    disabled,
}: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const clientId = context.clientId;
    const isSingle = field.config?.single === true;
    const autoPrefillCount = typeof field.config?.auto_prefill_count === "number"
        ? field.config.auto_prefill_count
        : 3;

    const current: string[] = useMemo(() => {
        if (isSingle) {
            return typeof value === "string" && value ? [value] : [];
        }
        return Array.isArray(value) ? (value as string[]) : [];
    }, [value, isSingle]);

    const [topics, setTopics] = useState<TopicItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Reads sort preference from the companion single_ref field in the
    // same step if present, otherwise defaults to visibility.
    const sortByRaw = (formState.default_sort as string | undefined) || "visibility";
    const sortBy: SortMode = useMemo(() => {
        const s = String(sortByRaw).toLowerCase();
        if (s.includes("citation")) return "citation";
        if (s.includes("sentiment") || s.includes("negative")) return "sentiment";
        return "visibility";
    }, [sortByRaw]);

    useEffect(() => {
        if (!clientId) return;
        let cancelled = false;
        setLoading(true);
        setError(null);

        getRankedTopics(clientId, sortBy, 30)
            .then((data: TopicItem[]) => {
                if (!cancelled) setTopics(data || []);
            })
            .catch((e: Error) => {
                if (!cancelled) setError(e.message || "failed to load topics");
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        return () => { cancelled = true; };
    }, [clientId, sortBy]);

    function toggle(id: string) {
        if (disabled) return;
        if (isSingle) {
            onChange(current[0] === id ? "" : id, true);
            return;
        }
        const next = current.includes(id)
            ? current.filter((t) => t !== id)
            : [...current, id];
        onChange(next, true);
    }

    function autoPrefill() {
        if (disabled || topics.length === 0) return;
        const n = Math.min(autoPrefillCount, topics.length);
        const top = topics.slice(0, n).map((tp) => tp.id);
        onChange(isSingle ? top[0] : top, true);
    }

    function clearSelection() {
        if (disabled) return;
        onChange(isSingle ? "" : [], true);
    }

    // Label + description are rendered by the outer FieldWrapper (see
    // FieldRenderer) — skip inline to avoid double-rendering.
    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <div className="flex items-center justify-end gap-1.5 flex-wrap">
                    <div className="flex items-center gap-1.5">
                        <ArrowUpDown className="w-3 h-3 text-muted-foreground" />
                        {SORT_OPTIONS.map((opt) => (
                            <span
                                key={opt.id}
                                className={`text-[10px] px-2 py-0.5 rounded-md border ${
                                    sortBy === opt.id
                                        ? "border-primary/50 bg-primary/10 text-primary font-medium"
                                        : "border-border text-muted-foreground"
                                }`}
                            >
                                {opt.label}
                            </span>
                        ))}
                    </div>
                </div>
                {topics.length > 0 && (
                    <div className="flex items-center gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 gap-1.5 text-xs"
                            onClick={autoPrefill}
                            disabled={disabled}
                        >
                            <Sparkles className="h-3 w-3 text-amber-500" />
                            {isSingle
                                ? t("topicRefPicker.autoSelectOne")
                                : t("topicRefPicker.autoSelectN", { count: Math.min(autoPrefillCount, topics.length) })}
                        </Button>
                        {current.length > 0 && (
                            <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-7 text-xs text-muted-foreground"
                                onClick={clearSelection}
                                disabled={disabled}
                            >
                                {t("topicRefPicker.clear")}
                            </Button>
                        )}
                    </div>
                )}
            </div>

            {loading ? (
                <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Loading…
                </div>
            ) : error ? (
                <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    Failed to load topics: {error}
                </div>
            ) : topics.length === 0 ? (
                <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-4 text-center text-xs text-muted-foreground">
                    No topics with active prompts — configure some on the Prompts page first.
                </div>
            ) : (
                <div className="space-y-1 max-h-[320px] overflow-y-auto">
                    {topics.map((tp, idx) => {
                        const on = current.includes(tp.id);
                        const tier = classifyPerformanceTier(idx, topics.length);
                        return (
                            <button
                                key={tp.id}
                                type="button"
                                onClick={() => toggle(tp.id)}
                                disabled={disabled}
                                className={`w-full text-left p-2.5 rounded-lg border text-sm transition-colors ${
                                    on
                                        ? "border-primary/40 bg-primary/5 text-foreground"
                                        : "border-border text-muted-foreground hover:border-primary/30"
                                } cursor-pointer`}
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <span className="truncate flex-1 text-sm font-medium">
                                        {tp.topic_name}
                                    </span>
                                    <div className="flex items-center gap-1 shrink-0">
                                        {tier === "critical" && (
                                            <Badge
                                                variant="outline"
                                                className="text-[9px] font-semibold gap-0.5 bg-red-500/10 text-red-400 border-red-500/30"
                                            >
                                                <AlertTriangle className="h-2.5 w-2.5" />
                                                {t("topicRefPicker.tierBad")}
                                            </Badge>
                                        )}
                                        {tier === "attention" && (
                                            <Badge
                                                variant="outline"
                                                className="text-[9px] font-medium bg-amber-500/10 text-amber-400 border-amber-500/30"
                                            >
                                                {t("topicRefPicker.tierOptimize")}
                                            </Badge>
                                        )}
                                    </div>
                                </div>
                                <TopicScoreBadges topic={tp} sortBy={sortBy} />
                            </button>
                        );
                    })}
                </div>
            )}

            {current.length > 0 && (
                <p className="text-[11px] text-muted-foreground">
                    {current.length} topic{current.length !== 1 ? "s" : ""} selected
                </p>
            )}
        </div>
    );
}

registerCustomField("topic_ref_picker", TopicRefPicker);

export default TopicRefPicker;
