/**
 * ChartBuilder — schema-driven replacement for Step3_Charts.
 *
 * Renders inside a single workflow_step field with type `chart_builder`. The
 * shape written to FormState under `field.key` is:
 *
 *     Array<{ nl_query: string; chart_type: "auto"|"line"|"bar"|"pie" }>
 *
 * The companion fields `default_threshold` and `default_baseline` (declared
 * as `number` / `text` in the same step) are NOT owned by this component —
 * they render as regular primitive fields alongside. Threshold and baseline
 * date state was pulled out of the old Step3_Charts into top-level FormState
 * keys so custom-field isolation stays clean.
 *
 * Registers itself under the `chart_builder` key at module-init time.
 */
import { useState, useMemo } from "react";
import { Plus, Sparkles, X } from "lucide-react";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

interface ChartReq {
    nl_query: string;
    chart_type: string;
    sql_hint?: string;
}

const CHART_TYPE_LABELS: Record<string, string> = {
    auto: "Auto",
    line: "Line",
    bar: "Bar",
    pie: "Pie",
};
const CHART_TYPE_ORDER: ReadonlyArray<"auto" | "line" | "bar" | "pie"> = [
    "auto",
    "line",
    "bar",
    "pie",
];

function chartTypeIcon(t: string): string {
    if (t === "bar") return "📊";
    if (t === "pie") return "🥧";
    return "📈";
}

function ChartBuilder({ value, onChange, context, disabled }: CustomFieldProps) {
    const [showRecommended, setShowRecommended] = useState(true);

    // Default charts come from the template's wizard_config.steps.chart_config
    // .default_charts (legacy key) OR from the template's top-level
    // `chart_requests` array (older seeds). We read both.
    const defaultCharts = useMemo<ChartReq[]>(() => {
        const tpl = context.template;
        if (!tpl) return [];
        const wc = (tpl.wizard_config || {}) as Record<string, unknown>;
        const steps = (wc.steps as Record<string, unknown>) || {};
        const chartCfg = (steps.chart_config as Record<string, unknown>) || {};
        const fromWizard = chartCfg.default_charts;
        if (Array.isArray(fromWizard)) {
            return fromWizard
                .filter((c): c is ChartReq =>
                    Boolean(c && typeof c === "object" && "nl_query" in (c as object)),
                )
                .map((c) => ({
                    nl_query: String((c as ChartReq).nl_query || ""),
                    chart_type: String((c as ChartReq).chart_type || "bar"),
                    ...((c as ChartReq).sql_hint ? { sql_hint: String((c as ChartReq).sql_hint) } : {}),
                }))
                .filter((c) => c.nl_query.trim());
        }
        const fromField = (tpl as unknown as { chart_requests?: unknown[] })
            .chart_requests;
        if (Array.isArray(fromField)) {
            return fromField
                .filter(
                    (c): c is ChartReq =>
                        Boolean(
                            c && typeof c === "object" && "nl_query" in (c as object),
                        ),
                )
                .map((c) => ({
                    nl_query: String((c as ChartReq).nl_query || ""),
                    chart_type: String((c as ChartReq).chart_type || "bar"),
                    ...((c as ChartReq).sql_hint ? { sql_hint: String((c as ChartReq).sql_hint) } : {}),
                }))
                .filter((c) => c.nl_query.trim());
        }
        return [];
    }, [context.template]);

    const charts: ChartReq[] = Array.isArray(value) ? (value as ChartReq[]) : [];
    const templateLabel = context.template?.name || "";

    function update(next: ChartReq[]) {
        onChange(next, true);
    }
    function addChart() {
        update([...charts, { nl_query: "", chart_type: "auto" }]);
    }
    function removeChart(i: number) {
        update(charts.filter((_, idx) => idx !== i));
    }
    function patchChart(i: number, patch: Partial<ChartReq>) {
        update(charts.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
    }
    function applyRecommended() {
        update([...defaultCharts]);
        setShowRecommended(false);
    }
    function appendRecommended() {
        update([...charts, ...defaultCharts]);
        setShowRecommended(false);
    }

    return (
        <div className="space-y-4">
            {defaultCharts.length > 0 && showRecommended && (
                <div className="rounded-2xl border-2 border-primary/30 bg-gradient-to-br from-primary/[0.06] to-primary/[0.02] p-5 space-y-4 relative overflow-hidden">
                    <div className="absolute -top-8 -right-8 w-24 h-24 bg-primary/10 rounded-full blur-2xl pointer-events-none" />
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg bg-primary/15 flex items-center justify-center">
                                <Sparkles className="h-4 w-4 text-primary" />
                            </div>
                            <div>
                                <span className="text-sm font-bold text-foreground">
                                    Recommended Charts
                                </span>
                                {templateLabel && (
                                    <span className="text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded-full font-medium ml-2">
                                        {templateLabel}
                                    </span>
                                )}
                            </div>
                        </div>
                        <button
                            onClick={() => setShowRecommended(false)}
                            className="text-muted-foreground/50 hover:text-muted-foreground transition-colors"
                            disabled={disabled}
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                        Anthony has curated the following charts based on this template.
                    </p>
                    <div className="space-y-2">
                        {defaultCharts.map((r, i) => (
                            <div
                                key={i}
                                className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl bg-background/80 border border-border/50"
                            >
                                <span className="text-base shrink-0">
                                    {chartTypeIcon(r.chart_type)}
                                </span>
                                <span className="text-xs font-medium text-foreground flex-1">
                                    {r.nl_query}
                                </span>
                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground font-medium shrink-0">
                                    {CHART_TYPE_LABELS[r.chart_type] || r.chart_type}
                                </span>
                            </div>
                        ))}
                    </div>
                    <div className="flex gap-3 pt-1">
                        {charts.length === 0 ? (
                            <button
                                onClick={applyRecommended}
                                disabled={disabled}
                                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-primary text-primary-foreground hover:bg-primary/90 transition-all shadow-sm disabled:opacity-50"
                            >
                                <Sparkles className="h-4 w-4" />
                                Apply All Recommended Charts
                            </button>
                        ) : (
                            <>
                                <button
                                    onClick={appendRecommended}
                                    disabled={disabled}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-primary text-primary-foreground hover:bg-primary/90 transition-all shadow-sm disabled:opacity-50"
                                >
                                    <Plus className="h-4 w-4" />
                                    Append Recommended Charts
                                </button>
                                <button
                                    onClick={applyRecommended}
                                    disabled={disabled}
                                    className="px-4 py-2.5 rounded-xl text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-primary/30 transition-all disabled:opacity-50"
                                >
                                    Replace Current
                                </button>
                            </>
                        )}
                    </div>
                </div>
            )}

            {/* Label + description rendered by outer FieldWrapper. */}

            <div className="space-y-3">
                {charts.map((req, i) => (
                    <div
                        key={i}
                        className="flex gap-2 items-start p-3 rounded-lg border bg-muted/20"
                    >
                        <div className="flex-1 space-y-2">
                            <textarea
                                value={req.nl_query}
                                onChange={(e) => {
                                    e.target.style.height = "auto";
                                    e.target.style.height = `${e.target.scrollHeight}px`;
                                    patchChart(i, { nl_query: e.target.value });
                                }}
                                onFocus={(e) => {
                                    e.target.style.height = "auto";
                                    e.target.style.height = `${e.target.scrollHeight}px`;
                                }}
                                placeholder="e.g., Daily visibility mention count trend over the past 30 days"
                                rows={2}
                                disabled={disabled}
                                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm overflow-hidden resize-none focus:outline-none focus:ring-2 focus:ring-ring/30 min-h-[40px]"
                            />
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-xs text-muted-foreground">
                                    Chart type:
                                </span>
                                {CHART_TYPE_ORDER.map((t) => (
                                    <button
                                        key={t}
                                        onClick={() => patchChart(i, { chart_type: t })}
                                        disabled={disabled}
                                        className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                                            req.chart_type === t
                                                ? "bg-primary text-primary-foreground"
                                                : "bg-muted hover:bg-muted/80"
                                        }`}
                                    >
                                        {CHART_TYPE_LABELS[t]}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <button
                            onClick={() => removeChart(i)}
                            disabled={disabled}
                            className="text-muted-foreground hover:text-destructive transition-colors mt-1"
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                ))}
            </div>

            <button
                onClick={addChart}
                disabled={disabled}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg border-2 border-dashed border-border hover:border-primary/40 hover:bg-muted/20 text-sm text-muted-foreground hover:text-foreground transition-all disabled:opacity-50"
            >
                <Plus className="h-4 w-4" />
                Add Chart Request
            </button>

            {charts.length === 0 && (
                <p className="text-xs text-center text-muted-foreground">
                    Skipping chart configuration will produce a text-only insights report
                </p>
            )}
        </div>
    );
}

registerCustomField("chart_builder", ChartBuilder);

export default ChartBuilder;
