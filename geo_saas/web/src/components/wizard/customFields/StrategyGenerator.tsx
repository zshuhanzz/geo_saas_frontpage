/**
 * StrategyGenerator — schema-driven replacement for NodeStrategy.
 *
 * Registered under the custom field type `strategy_generator`. Owns three
 * things:
 *
 *   1. Self-triggered LLM call to `POST /agent/tasks/generate-strategy`
 *      using the currently selected metrics / sub-goals / content_type /
 *      analyzer_context as inputs. Fires automatically the first time the
 *      user lands on this step once the required deps are present, and
 *      re-fires when the user clicks "重新生成" or applies free-text edits.
 *
 *   2. Renders the returned strategy array + a brand AI-engine breakdown
 *      bar chart (pulled out of the analyzer context's
 *      platform_recommendations — same as the old NodeStrategy).
 *
 *   3. Captures user edits — a textarea that collects free-form
 *      "adjust this strategy" text. On apply, we stash it alongside the
 *      strategy in the form value so the host modal can pass it through
 *      to the actual content_generation pipeline as `strategy` and
 *      `user_strategy_edits`, so final execution can reuse the confirmed
 *      strategy instead of silently generating a different one.
 *
 * Form value shape stored under field.key (typically `strategy`):
 *
 *     {
 *       data:              StrategyData | null,
 *       user_strategy_edits: string | null,
 *       status:            "idle" | "loading" | "ready" | "error",
 *     }
 *
 * Host modals map `data` + `user_strategy_edits` into their buildInputs
 * payload as `strategy` and `user_strategy_edits`.
 */
import { useEffect, useMemo, useState, useRef } from "react";
import { Loader2, Pencil, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AGENT_BASE, fetchJSON } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";
import {
    buildCitationAnalysisConfig,
    getCitationAnalysisResult,
    isCitationAnalysisEnabled,
} from "./citationAnalysisUtils";

interface StrategyData {
    strategies: Array<{
        name: string;
        description: string;
        dimensions: {
            instruction?: string;
            format?: {
                structure?: string;
                schema_markup?: string;
                word_count?: string;
            };
            tone?: string;
            constraints?: string[];
            enhancement_rules?: string[];
        };
        source_metrics?: string[];
        source_subgoals?: string[];
    }>;
    strategy_summary?: string;
}

interface PlatformRec {
    platform_type: string;
    engines: string[];
    citation_share: number;
    priority: string;
    engine_breakdown: Record<string, number>;
}

export interface StrategyGeneratorValue {
    data: StrategyData | null;
    user_strategy_edits: string | null;
    status: "idle" | "loading" | "ready" | "error";
}

const DEFAULT_VALUE: StrategyGeneratorValue = {
    data: null,
    user_strategy_edits: null,
    status: "idle",
};

const ENGINE_COLORS: Record<string, string> = {
    chatgpt: "#10a37f",
    gemini: "#4285f4",
    aimode: "#f97316",
    ai_mode: "#f97316",
    perplexity: "#8b5cf6",
    aioverview: "#0ea5e9",
    ai_overview: "#0ea5e9",
    google_ai_overview: "#0ea5e9",
    copilot: "#0078d4",
};

function tryParseJSON(value: string): unknown | null {
    const trimmed = value.trim();
    if (!trimmed || !["{", "["].includes(trimmed[0])) return null;
    try {
        return JSON.parse(trimmed);
    } catch {
        return null;
    }
}

function textFromStrategyObject(item: Record<string, unknown>): string {
    for (const key of ["description", "instruction", "strategy", "summary", "rationale", "content_strategy", "approach"]) {
        const value = item[key];
        if (typeof value === "string" && value.trim()) return value.trim();
    }
    const dimensions = item.dimensions;
    if (dimensions && typeof dimensions === "object") {
        const d = dimensions as Record<string, unknown>;
        for (const key of ["instruction", "format", "tone", "constraints", "enhancement_rules"]) {
            const value = d[key];
            if (typeof value === "string" && value.trim()) return value.trim();
            if (value && typeof value === "object") return JSON.stringify(value);
        }
    }
    return JSON.stringify(item);
}

function extractNestedStrategyPayload(item: unknown): unknown | null {
    if (typeof item === "string") {
        const parsed = tryParseJSON(item);
        if (
            parsed &&
            typeof parsed === "object" &&
            !Array.isArray(parsed) &&
            Array.isArray((parsed as Record<string, unknown>).strategies)
        ) {
            return parsed;
        }
        return null;
    }
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const obj = item as Record<string, unknown>;
    const candidates: unknown[] = [
        obj.description,
        obj.instruction,
        obj.strategy,
        obj.content_strategy,
    ];
    const dimensions = obj.dimensions;
    if (dimensions && typeof dimensions === "object" && !Array.isArray(dimensions)) {
        const d = dimensions as Record<string, unknown>;
        candidates.push(d.instruction, d.description);
    }
    for (const candidate of candidates) {
        if (typeof candidate !== "string") continue;
        const parsed = tryParseJSON(candidate);
        if (
            parsed &&
            typeof parsed === "object" &&
            !Array.isArray(parsed) &&
            Array.isArray((parsed as Record<string, unknown>).strategies)
        ) {
            return parsed;
        }
    }
    return null;
}

function normalizeStrategyEntry(item: unknown, index: number): StrategyData["strategies"][number] {
    if (typeof item === "string") {
        const parsed = tryParseJSON(item);
        if (parsed && !(typeof parsed === "object" && !Array.isArray(parsed) && Array.isArray((parsed as Record<string, unknown>).strategies))) {
            return normalizeStrategyEntry(parsed, index);
        }
        const text = item.trim();
        return {
            name: `Strategy ${index + 1}`,
            description: text,
            dimensions: { instruction: text },
        };
    }
    if (!item || typeof item !== "object" || Array.isArray(item)) {
        const text = JSON.stringify(item);
        return {
            name: `Strategy ${index + 1}`,
            description: text,
            dimensions: { instruction: text },
        };
    }
    const obj = item as Record<string, unknown>;
    const name =
        typeof obj.name === "string" && obj.name.trim()
            ? obj.name.trim()
            : typeof obj.title === "string" && obj.title.trim()
              ? obj.title.trim()
              : `Strategy ${index + 1}`;
    const description =
        typeof obj.description === "string" && obj.description.trim()
            ? obj.description.trim()
            : textFromStrategyObject(obj);
    const rawDimensions = obj.dimensions;
    const dimensions =
        rawDimensions && typeof rawDimensions === "object" && !Array.isArray(rawDimensions)
            ? { ...(rawDimensions as StrategyData["strategies"][number]["dimensions"]) }
            : {};
    if (!dimensions.instruction && description) dimensions.instruction = description;
    return {
        ...(obj as StrategyData["strategies"][number]),
        name,
        description,
        dimensions,
    };
}

function normalizeStrategyData(value: unknown): StrategyData | null {
    if (!value) return null;
    if (typeof value === "string") {
        const parsed = tryParseJSON(value);
        return parsed ? normalizeStrategyData(parsed) : null;
    }
    if (Array.isArray(value)) {
        if (value.length === 1 && typeof value[0] === "string") {
            const parsed = tryParseJSON(value[0]);
            if (parsed) return normalizeStrategyData(parsed);
        }
        return {
            strategies: value.map((item, index) => normalizeStrategyEntry(item, index)),
            strategy_summary: `Generated ${value.length} strategy option${value.length === 1 ? "" : "s"}.`,
        };
    }
    if (typeof value !== "object") return null;
    const obj = value as Record<string, unknown>;
    const rawStrategies = Array.isArray(obj.strategies)
        ? obj.strategies
        : obj.strategies
          ? [obj.strategies]
          : [];
    if (rawStrategies.length === 1) {
        const nested = extractNestedStrategyPayload(rawStrategies[0]);
        if (nested) return normalizeStrategyData(nested);
    }
    return {
        ...(obj as unknown as StrategyData),
        strategies: rawStrategies.map((item, index) => normalizeStrategyEntry(item, index)),
        strategy_summary:
            typeof obj.strategy_summary === "string" && obj.strategy_summary.trim()
                ? obj.strategy_summary
                : `Generated ${rawStrategies.length} strategy option${rawStrategies.length === 1 ? "" : "s"}.`,
    };
}

function toValue(v: unknown): StrategyGeneratorValue {
    if (v && typeof v === "object" && "data" in (v as object)) {
        const obj = v as Partial<StrategyGeneratorValue>;
        return {
            data: normalizeStrategyData(obj.data) || null,
            user_strategy_edits: obj.user_strategy_edits || null,
            status: obj.status || "idle",
        };
    }
    return { ...DEFAULT_VALUE };
}

function StrategyGenerator({
    value,
    onChange,
    context,
    formState,
    disabled,
}: CustomFieldProps) {
    const current = useMemo(() => toValue(value), [value]);
    const strategyData = useMemo(() => normalizeStrategyData(current.data), [current.data]);
    const [editing, setEditing] = useState(false);
    const [editText, setEditText] = useState(current.user_strategy_edits || "");
    const [error, setError] = useState<string | null>(null);
    const inFlightRef = useRef(false);
    const normalizedWriteBackRef = useRef<string>("");

    useEffect(() => {
        if (!strategyData || !value || typeof value !== "object" || !("data" in value)) return;
        const rawData = (value as Partial<StrategyGeneratorValue>).data;
        if (!rawData) return;
        const normalized = JSON.stringify(strategyData);
        if (JSON.stringify(rawData) === normalized || normalizedWriteBackRef.current === normalized) return;
        normalizedWriteBackRef.current = normalized;
        onChange({
            ...current,
            data: strategyData,
            status: current.status || "ready",
        });
    }, [current, onChange, strategyData, value]);

    // ─── Extract deps from FormState ─────────────────────────────────
    const selectedMetrics =
        (formState.default_metrics as string[] | undefined) || [];
    const selectedSubgoals =
        (formState.default_sub_goals as string[] | undefined) || [];
    // Content type lives under `default` per migration 031 — it's the
    // single_ref field inside the content_type step.
    const contentType =
        (formState.default as string | undefined) ||
        (formState.content_type as string | undefined) ||
        "";
    const publishPlatform =
        (formState.default_publish_platform as string | undefined) || "";
    const depth = (formState.default_depth as string | undefined) || "";
    const redditDiscovery = formState.reddit_discovery as Record<string, unknown> | undefined;
    const officialWebsiteDiscovery = formState.official_website_discovery as Record<string, unknown> | undefined;
    const citationAnalysis = buildCitationAnalysisConfig(formState, context.template);
    const citationAnalysisResult = getCitationAnalysisResult(formState);
    // analyzer_task_id value is { task_id, context } (set by AnalyzerImport).
    const analyzerField = formState.analyzer_task_id as
        | { task_id?: string; context?: Record<string, unknown> | null }
        | string
        | null;
    const analyzerContext =
        analyzerField && typeof analyzerField === "object"
            ? analyzerField.context || null
            : null;
    const analyzerTaskId =
        analyzerField && typeof analyzerField === "object"
            ? analyzerField.task_id || null
            : typeof analyzerField === "string"
              ? analyzerField
              : null;

    const platformRecommendations =
        (analyzerContext as { platform_recommendations?: PlatformRec[] } | null)
            ?.platform_recommendations || [];

    // ─── Generate strategy call ──────────────────────────────────────
    async function generate(userEdits: string | null) {
        if (!context.clientId) return;
        if (selectedMetrics.length === 0) {
            setError("Please select optimization metrics first");
            return;
        }
        if (inFlightRef.current) return;
        inFlightRef.current = true;
        setError(null);
        onChange(
            {
                ...current,
                status: "loading",
                user_strategy_edits: userEdits,
            },
            true,
        );
        try {
            const data: StrategyData = await fetchJSON(`${AGENT_BASE}/tasks/generate-strategy`, {
                method: "POST",
                body: JSON.stringify({
                    client_id: context.clientId,
                    selected_metrics: selectedMetrics,
                    selected_subgoals: selectedSubgoals,
                    content_type: contentType,
                    publish_platform: publishPlatform,
                    depth,
                    template_id: context.templateId,
                    reddit_discovery: redditDiscovery || null,
                    official_website_discovery: officialWebsiteDiscovery || null,
                    citation_analysis: citationAnalysis,
                    citation_analysis_result: citationAnalysisResult,
                    analyzer_context: analyzerContext,
                    analyzer_task_id: analyzerTaskId,
                    user_strategy_edits: userEdits,
                }),
            });
            onChange(
                {
                    data: normalizeStrategyData(data),
                    user_strategy_edits: userEdits,
                    status: "ready",
                },
                true,
            );
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setError(msg);
            onChange(
                {
                    ...current,
                    status: "error",
                    user_strategy_edits: userEdits,
                },
                true,
            );
        } finally {
            inFlightRef.current = false;
        }
    }

    // ─── Auto-trigger on mount if we don't already have data ────────
    // Only runs once per mount per set of deps so we don't thrash.
    const depKey = useMemo(
        () =>
            [
                selectedMetrics.slice().sort().join(","),
                selectedSubgoals.slice().sort().join(","),
                contentType,
                publishPlatform,
                depth,
                redditDiscovery?.status ? String(redditDiscovery.status) : "",
                officialWebsiteDiscovery?.status ? String(officialWebsiteDiscovery.status) : "",
                isCitationAnalysisEnabled(context.template) ? String(citationAnalysisResult?.fingerprint || "") : "",
                analyzerTaskId || "",
            ].join("|"),
        [selectedMetrics, selectedSubgoals, contentType, publishPlatform, depth, redditDiscovery, officialWebsiteDiscovery, citationAnalysisResult, context.template, analyzerTaskId],
    );
    const autoRanRef = useRef<string | null>(null);
    useEffect(() => {
        if (current.data) return;
        if (current.status === "loading") return;
        if (selectedMetrics.length === 0) return;
        if (!contentType) return;
        if (autoRanRef.current === depKey) return;
        autoRanRef.current = depKey;
        generate(current.user_strategy_edits || null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [depKey, current.data, current.status]);

    const loading = current.status === "loading";

    // ─── Render ──────────────────────────────────────────────────────
    // Label + description rendered by outer FieldWrapper.
    return (
        <div className="space-y-4">
            <div className="flex items-center justify-end gap-2">
                <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={disabled || loading}
                    onClick={() => setEditing((e) => !e)}
                >
                    <Pencil className="w-3 h-3 mr-1" />
                    Refine
                </Button>
                <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={disabled || loading}
                    onClick={() => generate(current.user_strategy_edits)}
                >
                    <RefreshCw
                        className={`w-3 h-3 mr-1 ${loading ? "animate-spin" : ""}`}
                    />
                    Regenerate
                </Button>
            </div>

            {loading && (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                    <Loader2 className="w-6 h-6 animate-spin mb-3" />
                    <p className="text-sm">Generating strategy combination…</p>
                </div>
            )}

            {!loading && error && (
                <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    Strategy generation failed: {error}
                </div>
            )}

            {!loading && !current.data && !error && (
                <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-4 text-center text-xs text-muted-foreground">
                    {selectedMetrics.length === 0
                        ? "Please select optimization metrics in the previous step first."
                        : "Waiting to generate strategy draft…"}
                </div>
            )}

            {!loading && strategyData && (
                <>
                    {strategyData.strategy_summary && (
                        <p className="text-sm text-foreground/80 bg-muted/30 border border-border rounded-lg p-3 leading-relaxed">
                            {strategyData.strategy_summary}
                        </p>
                    )}

                    {/* AI Engine Breakdown */}
                    {platformRecommendations.length > 0 && (
                        <div className="border border-border rounded-lg p-3 bg-muted/20">
                            <h4 className="text-xs font-semibold text-foreground mb-2">
                                AI Engine Distribution
                            </h4>
                            <div className="space-y-2">
                                {platformRecommendations.map((rec, i) => {
                                    const total =
                                        Object.values(rec.engine_breakdown || {}).reduce(
                                            (a, b) => a + b,
                                            0,
                                        ) || 1;
                                    return (
                                        <div
                                            key={i}
                                            className="flex items-center gap-3"
                                        >
                                            <span className="text-[11px] font-medium text-foreground w-24 shrink-0 truncate">
                                                {rec.platform_type}
                                            </span>
                                            <div className="flex-1 h-3 rounded-full overflow-hidden bg-muted flex">
                                                {Object.entries(
                                                    rec.engine_breakdown || {},
                                                ).map(([eng, count]) => {
                                                    const pct = Math.round(
                                                        (count / total) * 100,
                                                    );
                                                    return (
                                                        <div
                                                            key={eng}
                                                            style={{
                                                                width: `${pct}%`,
                                                                backgroundColor:
                                                                    ENGINE_COLORS[
                                                                        eng.toLowerCase()
                                                                    ] || "#8b5cf6",
                                                            }}
                                                            className="h-full"
                                                            title={`${eng} ${pct}%`}
                                                        />
                                                    );
                                                })}
                                            </div>
                                            <div className="flex gap-1.5 shrink-0">
                                                {Object.entries(
                                                    rec.engine_breakdown || {},
                                                ).map(([eng, count]) => {
                                                    const pct = Math.round(
                                                        (count / total) * 100,
                                                    );
                                                    return (
                                                        <span
                                                            key={eng}
                                                            className="text-[10px] text-muted-foreground flex items-center gap-0.5"
                                                        >
                                                            <span
                                                                className="w-1.5 h-1.5 rounded-full inline-block"
                                                                style={{
                                                                    backgroundColor:
                                                                        ENGINE_COLORS[
                                                                            eng.toLowerCase()
                                                                        ] || "#8b5cf6",
                                                                }}
                                                            />
                                                            {eng} {pct}%
                                                        </span>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* Strategy list */}
                    <div className="space-y-3">
                        {strategyData.strategies.map((s, i) => (
                            <div
                                key={i}
                                className="border border-border rounded-lg p-3 bg-muted/20"
                            >
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="text-xs font-mono text-muted-foreground">
                                        #{i + 1}
                                    </span>
                                    <span className="font-medium text-sm text-foreground">
                                        {s.name}
                                    </span>
                                </div>
                                <p className="text-xs text-muted-foreground mb-2 leading-relaxed">
                                    {s.description}
                                </p>
                                <div className="flex flex-wrap gap-1">
                                    {s.dimensions?.tone && (
                                        <Badge
                                            variant="outline"
                                            className="text-[10px]"
                                        >
                                            {s.dimensions.tone}
                                        </Badge>
                                    )}
                                    {(s.dimensions?.constraints || [])
                                        .slice(0, 3)
                                        .map((c, j) => (
                                            <Badge
                                                key={j}
                                                variant="outline"
                                                className="text-[10px] text-muted-foreground"
                                            >
                                                {c}
                                            </Badge>
                                        ))}
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {editing && (
                <div className="border border-border rounded-lg p-3 bg-muted/30">
                    <p className="text-[11px] text-muted-foreground mb-2">
                        Enter your adjustments and the strategy will be regenerated:
                    </p>
                    <textarea
                        className="w-full bg-background border border-input rounded p-2 text-sm text-foreground resize-none"
                        rows={3}
                        placeholder="e.g., Remove strategy #2, add a more conversational tone…"
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        disabled={disabled || loading}
                    />
                    <div className="flex justify-end mt-2 gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => {
                                setEditing(false);
                                setEditText(current.user_strategy_edits || "");
                            }}
                            disabled={disabled || loading}
                        >
                            Cancel
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            disabled={disabled || loading || !editText.trim()}
                            onClick={() => {
                                setEditing(false);
                                generate(editText.trim());
                            }}
                        >
                            Apply Changes
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}

registerCustomField("strategy_generator", StrategyGenerator);

export default StrategyGenerator;
