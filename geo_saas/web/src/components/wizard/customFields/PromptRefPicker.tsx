/**
 * PromptRefPicker — schema-driven replacement for NodePromptLink.
 *
 * Registered under the custom field type `prompt_ref_picker`. Two modes:
 *
 *   1. **Locked mode** — triggered when FormState has a non-empty
 *      analyzer_task_id.context.content_opportunities[].related_prompts.
 *      Prompts are pre-filled from the analyzer output and the user
 *      cannot toggle (they can only see which prompts are linked). This
 *      preserves the ground-truth link between the imported analyzer
 *      report and the content being generated.
 *
 *   2. **Open mode** — no analyzer context. We fetch ranked prompts via
 *      `getRankedPrompts(clientId, sortBy, limit)` and let the user
 *      pick which ones to target. Sort is driven by another field in
 *      the same step (`default_sort`, single_ref on sort_option).
 *
 * The form value stored under field.key (typically `prompt_ids`) is a
 * plain `string[]` of prompt ids. The host modal's buildInputs maps
 * this directly to `target_prompt_ids` in the content_generation inputs
 * contract.
 */
import { useEffect, useMemo, useState } from "react";
import { Lock, ArrowUpDown, Loader2, AlertTriangle, Sparkles, Search, Globe2, ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getRankedPrompts, getRankedPromptsPage } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

interface PromptItem {
    id: string;
    ids?: string[];
    prompt_text: string;
    platform: string;
    platforms?: string[];
    country?: string;
    countries?: string[];
    topic_name?: string;
    mention_count?: number;
    avg_position?: number;
    citation_count?: number;
    negative_count?: number;
}

type SortMode = "visibility" | "citation" | "sentiment";
type ViewMode = "detail" | "aggregate";

const SORT_OPTIONS: { id: SortMode; label: string }[] = [
    { id: "visibility", label: "Visibility" },
    { id: "citation", label: "Citation" },
    { id: "sentiment", label: "Sentiment" },
];

/** Classify a prompt's rank-position into a performance tier.
 *
 *  B-1 (2026-04-20) — Since the backend already sorts worst→best, the
 *  index IS the rank. We surface the tier to the user so they know which
 *  prompts need the most attention. Also drives B-2's "auto-pick
 *  underperformers" action. */
type PerfTier = "critical" | "attention" | "healthy";
function classifyPerformanceTier(index: number, total: number): PerfTier {
    if (total < 6) {
        // Tiny lists — top third is "critical", rest "attention".
        return index < Math.ceil(total / 3) ? "critical" : "attention";
    }
    if (index < 5) return "critical";   // bottom 5 = critical
    if (index < 15) return "attention"; // next 10 = worth looking at
    return "healthy";
}

function ScoreBadges({
    prompt,
    sortBy,
}: {
    prompt: PromptItem;
    sortBy: SortMode;
}) {
    const mentions = prompt.mention_count ?? 0;
    const citations = prompt.citation_count ?? 0;
    const negatives = prompt.negative_count ?? 0;
    return (
        <div className="flex items-center gap-1.5 mt-1">
            <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                    sortBy === "visibility"
                        ? "bg-blue-500/10 text-blue-400 font-medium"
                        : "text-muted-foreground"
                }`}
            >
                Mentions {mentions}
            </span>
            <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                    sortBy === "citation"
                        ? "bg-green-500/10 text-green-400 font-medium"
                        : "text-muted-foreground"
                }`}
            >
                Citations {citations}
            </span>
            <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                    sortBy === "sentiment"
                        ? "bg-red-500/10 text-red-400 font-medium"
                        : "text-muted-foreground"
                }`}
            >
                Negative {negatives}
            </span>
        </div>
    );
}

function PromptRefPicker({
    value,
    onChange,
    context,
    formState,
    disabled,
}: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const clientId = context.clientId;
    const current: string[] = Array.isArray(value) ? (value as string[]) : [];

    const [prompts, setPrompts] = useState<PromptItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [page, setPage] = useState(1);
    const [pageSize] = useState(10);
    const [total, setTotal] = useState(0);
    const [searchText, setSearchText] = useState("");
    const [debouncedSearch, setDebouncedSearch] = useState("");
    const [viewMode, setViewMode] = useState<ViewMode>("detail");

    // ─── Dependency extraction ───────────────────────────────────────
    // analyzer_task_id is stored as {task_id, context} (AnalyzerImport).
    const analyzerField = formState.analyzer_task_id as
        | { task_id?: string; context?: Record<string, unknown> | null }
        | null;
    const analyzerContext =
        analyzerField && typeof analyzerField === "object"
            ? analyzerField.context || null
            : null;

    const lockedPromptIds = useMemo<string[]>(() => {
        if (!analyzerContext) return [];
        const opps =
            ((analyzerContext as { content_opportunities?: unknown[] })
                .content_opportunities as
                | Array<{ related_prompts?: string[] }>
                | undefined) || [];
        const set = new Set<string>();
        for (const o of opps) {
            for (const p of o.related_prompts || []) set.add(p);
        }
        return Array.from(set);
    }, [analyzerContext]);

    const isLocked = lockedPromptIds.length > 0;

    // Read sortBy from the companion single_ref field in the same step.
    // default_sort → dictionary key of `sort_option`. We map known keys
    // to visibility/citation/sentiment, otherwise default to visibility.
    const sortByRaw = (formState.default_sort as string | undefined) || "visibility";
    const sortBy: SortMode = useMemo(() => {
        const s = String(sortByRaw).toLowerCase();
        if (s.includes("citation")) return "citation";
        if (s.includes("sentiment") || s.includes("negative")) return "sentiment";
        return "visibility";
    }, [sortByRaw]);

    useEffect(() => {
        const timer = window.setTimeout(() => setDebouncedSearch(searchText.trim()), 300);
        return () => window.clearTimeout(timer);
    }, [searchText]);

    useEffect(() => {
        setPage(1);
    }, [sortBy, debouncedSearch, viewMode, clientId, isLocked]);

    // ─── Sync locked ids into form state ─────────────────────────────
    // When locked, always reflect the analyzer-derived set so downstream
    // submit handlers get the ground-truth prompt list. We only fire
    // onChange when the set actually changes to avoid dispatch churn.
    useEffect(() => {
        if (!isLocked) return;
        const sorted = lockedPromptIds.slice().sort().join(",");
        const currentSorted = current.slice().sort().join(",");
        if (sorted !== currentSorted) {
            onChange(lockedPromptIds, false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [lockedPromptIds.join(","), isLocked]);

    // ─── Fetch prompts ────────────────────────────────────────────────
    useEffect(() => {
        if (!clientId) return;
        let cancelled = false;
        setLoading(true);
        setError(null);

        if (isLocked) {
            // Locked mode: fetch a large ranked set and filter to the
            // analyzer-derived ids for display.
            getRankedPrompts(clientId, "visibility", 200)
                .then((data: PromptItem[]) => {
                    if (cancelled) return;
                    const ids = new Set(lockedPromptIds);
                    setPrompts((data || []).filter((p) => ids.has(p.id)));
                    setTotal(lockedPromptIds.length);
                })
                .catch((e: Error) => {
                    if (!cancelled) setError(e.message || "failed to load prompts");
                })
                .finally(() => {
                    if (!cancelled) setLoading(false);
                });
        } else {
            getRankedPromptsPage({
                clientId,
                sortBy,
                page,
                pageSize,
                search: debouncedSearch,
                viewMode,
            })
                .then((data: { items?: PromptItem[]; total?: number }) => {
                    if (cancelled) return;
                    setPrompts(data.items || []);
                    setTotal(Number(data.total || 0));
                })
                .catch((e: Error) => {
                    if (!cancelled) setError(e.message || "failed to load prompts");
                })
                .finally(() => {
                    if (!cancelled) setLoading(false);
                });
        }

        return () => {
            cancelled = true;
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clientId, isLocked, sortBy, page, pageSize, debouncedSearch, viewMode, lockedPromptIds.join(",")]);

    function toggle(id: string) {
        if (isLocked) return;
        const row = prompts.find((p) => p.id === id);
        const ids = row?.ids?.length ? row.ids : [id];
        const idSet = new Set(ids);
        const allSelected = ids.every((pid) => current.includes(pid));
        const next = allSelected
            ? current.filter((p) => !idSet.has(p))
            : Array.from(new Set([...current, ...ids]));
        onChange(next, true);
    }

    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    // Label + description are rendered by the outer FieldWrapper (see
    // FieldRenderer) — skip inline to avoid double-rendering.
    return (
        <div className="space-y-4">
            {isLocked && (
                <div>
                    <Badge
                        variant="outline"
                        className="text-[10px] text-amber-400 border-amber-500/30"
                    >
                        <Lock className="w-2.5 h-2.5 mr-1" />
                        Locked
                    </Badge>
                </div>
            )}

            {isLocked ? (
                <p className="text-xs text-amber-400/80 leading-relaxed">
                    {lockedPromptIds.length} prompts linked from the analysis report.
                    To change, go back to step 1 and select a different report or skip.
                </p>
            ) : (
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
                        <div className="flex items-center gap-1 rounded-md border border-border/70 bg-muted/20 p-0.5">
                            {(["detail", "aggregate"] as ViewMode[]).map((mode) => (
                                <button
                                    key={mode}
                                    type="button"
                                    className={`h-6 px-2 rounded text-[10px] transition-colors ${
                                        viewMode === mode
                                            ? "bg-primary/15 text-primary font-medium"
                                            : "text-muted-foreground hover:text-foreground"
                                    }`}
                                    onClick={() => setViewMode(mode)}
                                >
                                    {t(`promptRefPicker.view.${mode}`)}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className="relative">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                        <Input
                            value={searchText}
                            onChange={(event) => setSearchText(event.target.value)}
                            placeholder={t("promptRefPicker.searchPlaceholder")}
                            className="h-8 pl-8 text-xs"
                            disabled={disabled}
                        />
                    </div>
                    {/* B-2 auto-preselect — 一键选前 N 个表现最差的 */}
                    {prompts.length > 0 && (
                        <div className="flex items-center gap-2">
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-7 gap-1.5 text-xs"
                                onClick={() => {
                                    const n = Math.min(5, prompts.length);
                                    const top = prompts
                                        .slice(0, n)
                                        .flatMap((p) => (p.ids?.length ? p.ids : [p.id]));
                                    onChange(top, true);
                                }}
                                disabled={disabled}
                            >
                                <Sparkles className="h-3 w-3 text-amber-500" />
                                {t("promptRefPicker.autoSelectN", { count: 5 })}
                            </Button>
                            {current.length > 0 && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 text-xs text-muted-foreground"
                                    onClick={() => onChange([], true)}
                                    disabled={disabled}
                                >
                                    {t("promptRefPicker.clear")}
                                </Button>
                            )}
                        </div>
                    )}
                </div>
            )}

            {loading ? (
                <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Loading…
                </div>
            ) : error ? (
                <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    Failed to load prompts: {error}
                </div>
            ) : prompts.length === 0 ? (
                <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-4 text-center text-xs text-muted-foreground">
                    {isLocked
                        ? "No prompts linked from the imported analysis report."
                        : "No prompts available — add some on the Prompts page first."}
                </div>
            ) : (
                <div className="space-y-1 max-h-[300px] overflow-y-auto">
                    {prompts.map((p, idx) => {
                        const ids = p.ids?.length ? p.ids : [p.id];
                        const on = ids.every((pid) => current.includes(pid));
                        const tier = classifyPerformanceTier(idx, prompts.length);
                        return (
                            <button
                                key={p.id}
                                type="button"
                                onClick={() => toggle(p.id)}
                                disabled={isLocked || disabled}
                                className={`w-full text-left p-2.5 rounded-lg border text-sm transition-colors ${
                                    on
                                        ? "border-orange-500/40 bg-orange-500/5 text-foreground"
                                        : "border-border text-muted-foreground hover:border-orange-500/30"
                                } ${isLocked ? "cursor-default opacity-85" : "cursor-pointer"}`}
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <span className="truncate flex-1 text-xs">
                                        {p.prompt_text}
                                    </span>
                                    <div className="flex items-center gap-1 shrink-0">
                                        {tier === "critical" && !isLocked && (
                                            <Badge
                                                variant="outline"
                                                className="text-[9px] font-semibold gap-0.5 bg-red-500/10 text-red-400 border-red-500/30"
                                            >
                                                <AlertTriangle className="h-2.5 w-2.5" />
                                                {t("promptRefPicker.tierBad")}
                                            </Badge>
                                        )}
                                        {tier === "attention" && !isLocked && (
                                            <Badge
                                                variant="outline"
                                                className="text-[9px] font-medium bg-amber-500/10 text-amber-400 border-amber-500/30"
                                            >
                                                {t("promptRefPicker.tierOptimize")}
                                            </Badge>
                                        )}
                                        {viewMode === "detail" && p.country && (
                                            <Badge
                                                variant="outline"
                                                className="text-[10px] gap-1"
                                            >
                                                <Globe2 className="h-2.5 w-2.5" />
                                                {p.country}
                                            </Badge>
                                        )}
                                        {viewMode === "detail" && p.platform && (
                                            <Badge
                                                variant="outline"
                                                className="text-[10px]"
                                            >
                                                {p.platform}
                                            </Badge>
                                        )}
                                    </div>
                                </div>
                                <ScoreBadges prompt={p} sortBy={sortBy} />
                            </button>
                        );
                    })}
                </div>
            )}

            {!loading && !error && !isLocked && total > pageSize && (
                <div className="flex items-center justify-between gap-2 pt-1 text-[11px] text-muted-foreground">
                    <span>
                        {t("promptRefPicker.pagination", {
                            page,
                            totalPages,
                            total,
                        })}
                    </span>
                    <div className="flex items-center gap-1">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 px-2 text-xs"
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            disabled={disabled || page <= 1}
                        >
                            <ChevronLeft className="h-3 w-3 mr-1" />
                            {t("promptRefPicker.previous")}
                        </Button>
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 px-2 text-xs"
                            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                            disabled={disabled || page >= totalPages}
                        >
                            {t("promptRefPicker.next")}
                            <ChevronRight className="h-3 w-3 ml-1" />
                        </Button>
                    </div>
                </div>
            )}

            {current.length > 0 && !isLocked && (
                <p className="text-[11px] text-muted-foreground">
                    {current.length} prompt{current.length !== 1 ? "s" : ""} selected
                </p>
            )}
        </div>
    );
}

registerCustomField("prompt_ref_picker", PromptRefPicker);

export default PromptRefPicker;
