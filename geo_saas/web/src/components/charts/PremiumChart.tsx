/**
 * PremiumChart — Unified commercial-grade chart component.
 *
 * Used by:
 * - AgentChat (pre-processed data: {data, xKey, yKeys, type, title})
 * - TemplateConfigModal / AgentAnalysis (raw SQL data: {columns, rows, chart_type, nl_query})
 *
 * Features: dark/light theme, gradient fills, glass-morphism tooltip, hover animations,
 * auto chart-type detection, multi-series pivot, data table toggle.
 */
import { useState, useEffect } from "react";
import {
    BarChart, Bar,
    AreaChart, Area,
    PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid,
    Tooltip as RechartsTooltip,
    ResponsiveContainer, Legend,
} from "recharts";
import { BarChart3, TrendingUp, PieChart as PieChartIcon, Table } from "lucide-react";

// ── Theme ────────────────────────────────────────────────────────────────

function useIsDark(): boolean {
    const [isDark, setIsDark] = useState(
        () => typeof document !== "undefined" && document.documentElement.classList.contains("dark")
    );
    useEffect(() => {
        const el = document.documentElement;
        const obs = new MutationObserver(() => setIsDark(el.classList.contains("dark")));
        obs.observe(el, { attributes: true, attributeFilter: ["class"] });
        return () => obs.disconnect();
    }, []);
    return isDark;
}

// ── Colors ───────────────────────────────────────────────────────────────

const PLATFORM_COLORS: Record<string, string> = {
    chatgpt: "#10b981",
    gemini: "#6366f1",
    aimode: "#f59e0b",
    ai_mode: "#f59e0b",
    perplexity: "#8b5cf6",
    aioverview: "#0ea5e9",
    ai_overview: "#0ea5e9",
    google_ai_overview: "#0ea5e9",
};
const SERIES_PALETTE = [
    "#6366f1", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#ec4899", "#14b8a6", "#3b82f6",
];

function seriesColor(key: string, idx: number): string {
    const lk = key.toLowerCase().replace(/[\s_-]/g, "");
    for (const [p, c] of Object.entries(PLATFORM_COLORS)) {
        if (lk.includes(p.replace("_", ""))) return c;
    }
    return SERIES_PALETTE[idx % SERIES_PALETTE.length];
}

function fmtValue(v: any): string {
    if (v === null || v === undefined) return "–";
    if (typeof v === "number") return v % 1 === 0 ? v.toLocaleString() : v.toFixed(2);
    return String(v);
}

// ── Tooltip ──────────────────────────────────────────────────────────────

function PremiumTooltip({ active, payload, label }: any) {
    if (!active || !payload?.length) return null;
    const dark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");
    return (
        <div style={{
            background: dark ? "rgba(15,15,20,0.92)" : "rgba(255,255,255,0.96)",
            border: dark ? "1px solid rgba(99,102,241,0.25)" : "1px solid rgba(0,0,0,0.08)",
            borderRadius: 12,
            padding: "10px 14px",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            boxShadow: dark
                ? "0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04)"
                : "0 8px 32px rgba(0,0,0,0.12), 0 0 0 1px rgba(255,255,255,0.8)",
            minWidth: 150,
        }}>
            {label && (
                <p style={{
                    color: dark ? "#a1a1aa" : "#6b7280",
                    fontSize: 11, marginBottom: 7, fontWeight: 500,
                    letterSpacing: "0.02em",
                }}>
                    {String(label)}
                </p>
            )}
            {payload.map((entry: any, i: number) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: i < payload.length - 1 ? 4 : 0 }}>
                    <span style={{
                        width: 8, height: 8, borderRadius: 4,
                        background: entry.color, flexShrink: 0,
                        boxShadow: `0 0 6px ${entry.color}44`,
                    }} />
                    <span style={{ color: dark ? "#e4e4e7" : "#111827", fontSize: 12, fontWeight: 600 }}>
                        {fmtValue(entry.value)}
                    </span>
                    <span style={{ color: dark ? "#71717a" : "#9ca3af", fontSize: 11 }}>
                        {entry.name}
                    </span>
                </div>
            ))}
        </div>
    );
}

// ── Props ────────────────────────────────────────────────────────────────

export interface PremiumChartProps {
    /** Pre-processed data format (from AgentChat) */
    data?: any[];
    xKey?: string;
    yKeys?: string[];
    type?: "bar" | "line" | "area" | "pie";
    title?: string;
    nameKey?: string;
    valueKey?: string;
    meta?: Record<string, any>;

    /** Raw SQL format (from TemplateConfigModal) */
    columns?: string[];
    rows?: any[][];
    chart_type?: string;
    nl_query?: string;
    error?: string;
    warning?: string;

    /** Layout */
    height?: number;
    compact?: boolean;
}

// ── Component ────────────────────────────────────────────────────────────

export function PremiumChart(props: PremiumChartProps) {
    const isDark = useIsDark();
    const [showTable, setShowTable] = useState(false);
    const [hovered, setHovered] = useState(false);

    // Theme tokens
    const t = isDark ? {
        cardBg: "linear-gradient(145deg, rgba(24,24,27,0.95) 0%, rgba(15,15,18,0.98) 100%)",
        cardBorder: "1px solid rgba(99,102,241,0.15)",
        cardShadow: "0 4px 24px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04)",
        cardHoverShadow: "0 8px 40px rgba(99,102,241,0.15), inset 0 1px 0 rgba(255,255,255,0.06)",
        glowOpacity: "22",
        labelColor: "#a1a1aa",
        titleColor: "#f4f4f5",
        axisTick: "#71717a",
        axisStroke: "#3f3f46",
        grid: "rgba(255,255,255,0.04)",
        legend: "#a1a1aa",
        dotStroke: "#18181b",
        tableBg: "rgba(24,24,27,0.6)",
        tableHeaderBg: "rgba(255,255,255,0.03)",
        tableHoverBg: "rgba(255,255,255,0.04)",
        tableBorder: "rgba(255,255,255,0.06)",
        toggleBg: "rgba(255,255,255,0.06)",
        toggleHoverBg: "rgba(255,255,255,0.1)",
    } : {
        cardBg: "linear-gradient(145deg, rgba(255,255,255,0.92) 0%, rgba(248,250,252,0.96) 100%)",
        cardBorder: "1px solid rgba(0,0,0,0.06)",
        cardShadow: "0 4px 20px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.9)",
        cardHoverShadow: "0 12px 40px rgba(0,0,0,0.1), inset 0 1px 0 rgba(255,255,255,0.9)",
        glowOpacity: "15",
        labelColor: "#9ca3af",
        titleColor: "#111827",
        axisTick: "#9ca3af",
        axisStroke: "#e5e7eb",
        grid: "rgba(0,0,0,0.04)",
        legend: "#6b7280",
        dotStroke: "#ffffff",
        tableBg: "rgba(248,250,252,0.8)",
        tableHeaderBg: "rgba(0,0,0,0.02)",
        tableHoverBg: "rgba(0,0,0,0.03)",
        tableBorder: "rgba(0,0,0,0.06)",
        toggleBg: "rgba(0,0,0,0.04)",
        toggleHoverBg: "rgba(0,0,0,0.08)",
    };

    // ── Error/Warning/Empty states ──
    if (props.error) {
        return (
            <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 my-3">
                <div className="flex items-center gap-2 text-sm text-destructive mb-1">
                    <BarChart3 className="h-4 w-4" /> Chart generation failed
                </div>
                <p className="text-xs text-muted-foreground">{props.error}</p>
            </div>
        );
    }
    if (props.warning) {
        return (
            <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/5 p-4 my-3">
                <div className="text-xs text-yellow-500">{props.warning}</div>
            </div>
        );
    }

    // ── Normalize data ──
    // Support both pre-processed (AgentChat) and raw SQL (TemplateConfigModal) formats
    let chartData: any[] = [];
    let seriesKeys: string[] = [];
    let xKey = props.xKey || "name";
    let title = props.title || props.nl_query || "";
    const chartHeight = props.height || (props.compact ? 180 : 220);

    if (props.columns && props.rows) {
        // Raw SQL format — pivot detection (same as TemplateConfigModal)
        const cols = props.columns;
        const rows = props.rows;

        if (rows.length === 0) {
            return (
                <div style={{
                    background: t.cardBg, border: t.cardBorder, borderRadius: 16,
                    padding: "24px 20px", textAlign: "center",
                }}>
                    <BarChart3 style={{ width: 32, height: 32, color: t.labelColor, opacity: 0.4, margin: "0 auto 8px" }} />
                    <p style={{ color: t.labelColor, fontSize: 12 }}>{title}</p>
                    <p style={{ color: t.labelColor, fontSize: 11, opacity: 0.6, marginTop: 4 }}>No data</p>
                </div>
            );
        }

        xKey = cols[0];

        // Multi-series pivot
        const col1IsCategory = (
            cols.length >= 3 &&
            rows.every(r => typeof r[1] === "string") &&
            rows.some(r => isNaN(Number(r[1])))
        );
        const isMultiSeries = (
            col1IsCategory &&
            rows.some(r => typeof r[2] === "number" || !isNaN(Number(r[2])))
        );

        if (isMultiSeries) {
            const groups = Array.from(new Set(rows.map(r => String(r[1]))));
            const xValues = Array.from(new Set(rows.map(r => String(r[0]))));
            xValues.sort((a, b) => {
                if (/^\d{4}-\d{2}/.test(a) && /^\d{4}-\d{2}/.test(b)) return a.localeCompare(b);
                const na = Number(a), nb = Number(b);
                if (!isNaN(na) && !isNaN(nb)) return na - nb;
                return 0;
            });
            const valueColCount = cols.length - 2;
            chartData = xValues.map(xVal => {
                const obj: any = { [xKey]: xVal };
                groups.forEach(group => {
                    const match = rows.find(r => String(r[0]) === xVal && String(r[1]) === group);
                    if (match) {
                        for (let vi = 0; vi < valueColCount; vi++) {
                            const colName = valueColCount === 1 ? group : `${group}_${cols[2 + vi]}`;
                            const raw = match[2 + vi];
                            obj[colName] = raw !== null && raw !== undefined ? Number(raw) : null;
                        }
                    }
                });
                return obj;
            });
            seriesKeys = valueColCount === 1 ? groups : groups.flatMap(g => cols.slice(2).map(vc => `${g}_${vc}`));
        } else {
            chartData = rows.map(row => {
                const obj: any = {};
                cols.forEach((col, i) => { obj[col] = row[i]; });
                return obj;
            });
            const xSample = chartData[0]?.[xKey];
            if (typeof xSample === "string" && /^\d{4}-\d{2}/.test(xSample)) {
                chartData.sort((a, b) => String(a[xKey]).localeCompare(String(b[xKey])));
            }
            seriesKeys = cols.slice(1).filter(k => {
                const sample = chartData[0]?.[k];
                return typeof sample === "number" || !isNaN(Number(sample));
            });
            if (seriesKeys.length > 0) {
                chartData = chartData.map(obj => {
                    const newObj = { ...obj };
                    for (const key of seriesKeys) {
                        if (typeof newObj[key] === "string") {
                            const n = Number(newObj[key]);
                            if (!isNaN(n)) newObj[key] = n;
                        }
                    }
                    return newObj;
                });
            }
            if (seriesKeys.length === 0) seriesKeys = cols.slice(1);
        }
    } else if (props.data) {
        // Pre-processed format (AgentChat)
        chartData = props.data;
        xKey = props.xKey || "name";
        seriesKeys = props.yKeys || [];
        if (seriesKeys.length === 0 && chartData.length > 0) {
            seriesKeys = Object.keys(chartData[0]).filter(k => k !== xKey && typeof chartData[0][k] === "number");
        }
    }

    if (chartData.length === 0) return null;

    // ── Auto chart type detection ──
    const autoChartType = (() => {
        const explicit = props.type || props.chart_type;
        if (explicit === "pie" || explicit === "donut") return "pie" as const;
        if (explicit === "bar") return "bar" as const;
        if (explicit === "area" || explicit === "line") return "area" as const;
        const xSample = chartData[0]?.[xKey];
        const xIsDate = typeof xSample === "string" && /^\d{4}-\d{2}/.test(xSample);
        const xIsNumeric = typeof xSample === "number" || (!isNaN(Number(xSample)) && typeof xSample === "string" && /^\d+$/.test(xSample));
        if (xIsDate || xIsNumeric) return "area" as const;
        if (chartData.length <= 8) return "bar" as const;
        return "area" as const;
    })();

    const isPie = autoChartType === "pie";

    const TypeIcon = isPie ? PieChartIcon : autoChartType === "area" ? TrendingUp : BarChart3;
    const primaryColor = seriesColor(seriesKeys[0] || "", 0);

    const fmtTick = (v: any) => {
        if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return v.slice(5);
        if (typeof v === "string" && v.length > 12) return v.slice(0, 10) + "…";
        return String(v);
    };

    // Build table data for toggle
    const tableColumns = props.columns || (chartData.length > 0 ? Object.keys(chartData[0]).filter(k => k !== "isOwn") : []);
    const tableRows = props.rows || chartData.map(row => tableColumns.map(col => row[col]));

    return (
        <div
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            style={{
                background: t.cardBg,
                border: t.cardBorder,
                borderRadius: 16,
                padding: props.compact ? "16px 16px 12px" : "20px 20px 16px",
                boxShadow: hovered ? t.cardHoverShadow : t.cardShadow,
                backdropFilter: "blur(16px)",
                WebkitBackdropFilter: "blur(16px)",
                position: "relative",
                overflow: "hidden",
                transition: "box-shadow 0.3s ease, transform 0.3s ease",
                transform: hovered ? "translateY(-2px)" : "translateY(0)",
                margin: "12px 0",
            }}
        >
            {/* Glow accent */}
            <div style={{
                position: "absolute", top: -50, right: -50, width: 140, height: 140,
                background: `radial-gradient(circle, ${primaryColor}${t.glowOpacity} 0%, transparent 70%)`,
                pointerEvents: "none",
                transition: "opacity 0.3s ease",
                opacity: hovered ? 1 : 0.6,
            }} />

            {/* Header */}
            <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                marginBottom: props.compact ? 12 : 16, position: "relative",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
                    <div style={{
                        width: 32, height: 32, borderRadius: 10,
                        background: `${primaryColor}18`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        flexShrink: 0, transition: "background 0.2s ease",
                        ...(hovered ? { background: `${primaryColor}28` } : {}),
                    }}>
                        <TypeIcon style={{ width: 16, height: 16, color: primaryColor }} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                        {!props.compact && (
                            <p style={{
                                color: t.labelColor, fontSize: 10, fontWeight: 600,
                                textTransform: "uppercase", letterSpacing: "0.06em",
                                marginBottom: 2,
                            }}>
                                {isPie ? "Distribution" : autoChartType === "area" ? "Trend Analysis" : "Comparative Analysis"}
                            </p>
                        )}
                        <h4 style={{
                            color: t.titleColor, fontSize: props.compact ? 12 : 13,
                            fontWeight: 600, lineHeight: 1.4, margin: 0,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                            {title}
                        </h4>
                    </div>
                </div>

                {/* Table toggle */}
                <button
                    onClick={() => setShowTable(!showTable)}
                    style={{
                        display: "flex", alignItems: "center", gap: 5,
                        padding: "5px 10px", borderRadius: 8, border: "none",
                        background: showTable ? `${primaryColor}18` : t.toggleBg,
                        color: showTable ? primaryColor : t.labelColor,
                        fontSize: 10, fontWeight: 600, cursor: "pointer",
                        transition: "all 0.2s ease",
                        letterSpacing: "0.02em",
                    }}
                    onMouseEnter={(e) => {
                        if (!showTable) (e.currentTarget.style.background = t.toggleHoverBg);
                    }}
                    onMouseLeave={(e) => {
                        if (!showTable) (e.currentTarget.style.background = t.toggleBg);
                    }}
                >
                    <Table style={{ width: 12, height: 12 }} />
                    {showTable ? "Chart" : "Data"}
                </button>
            </div>

            {/* Content */}
            {showTable ? (
                <div style={{
                    overflow: "auto", maxHeight: 240, borderRadius: 10,
                    border: `1px solid ${t.tableBorder}`,
                }}>
                    <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                        <thead>
                            <tr>
                                {tableColumns.map((col) => (
                                    <th key={col} style={{
                                        textAlign: "left", padding: "8px 12px",
                                        color: t.labelColor, fontWeight: 600, fontSize: 10,
                                        background: t.tableHeaderBg,
                                        borderBottom: `1px solid ${t.tableBorder}`,
                                        textTransform: "uppercase", letterSpacing: "0.04em",
                                        position: "sticky", top: 0,
                                    }}>
                                        {col}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {tableRows.slice(0, 15).map((row: any, i: number) => {
                                const cells = Array.isArray(row) ? row : tableColumns.map(col => row[col]);
                                return (
                                    <tr key={i} style={{
                                        borderBottom: i < Math.min(tableRows.length, 15) - 1 ? `1px solid ${t.tableBorder}` : "none",
                                        transition: "background 0.15s ease",
                                    }}
                                        onMouseEnter={(e) => (e.currentTarget.style.background = t.tableHoverBg)}
                                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                    >
                                        {cells.map((v: any, j: number) => (
                                            <td key={j} style={{
                                                padding: "7px 12px",
                                                color: t.titleColor,
                                                fontVariantNumeric: typeof v === "number" ? "tabular-nums" : undefined,
                                            }}>
                                                {typeof v === "number" ? v.toLocaleString() : String(v ?? "–")}
                                            </td>
                                        ))}
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            ) : (
                <ResponsiveContainer width="100%" height={chartHeight}>
                    {isPie ? (
                        <PieChart>
                            <defs>
                                {seriesKeys.map((key, i) => (
                                    <radialGradient key={key} id={`pc-pie-${i}`} cx="50%" cy="50%" r="50%">
                                        <stop offset="0%" stopColor={seriesColor(key, i)} stopOpacity={1} />
                                        <stop offset="100%" stopColor={seriesColor(key, i)} stopOpacity={0.7} />
                                    </radialGradient>
                                ))}
                            </defs>
                            <Pie
                                data={chartData}
                                dataKey={seriesKeys[0] || (props.columns ? props.columns[1] : props.valueKey) || "value"}
                                nameKey={props.nameKey || xKey}
                                cx="50%" cy="50%"
                                innerRadius={chartHeight * 0.22}
                                outerRadius={chartHeight * 0.36}
                                paddingAngle={3}
                                animationDuration={800}
                                animationEasing="ease-out"
                            >
                                {chartData.map((_: any, i: number) => (
                                    <Cell
                                        key={i}
                                        fill={seriesColor(String(Object.values(chartData[i])[0]), i)}
                                        stroke="none"
                                        style={{ filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.15))", cursor: "pointer" }}
                                    />
                                ))}
                            </Pie>
                            <RechartsTooltip content={<PremiumTooltip />} />
                            <Legend
                                wrapperStyle={{ fontSize: 11, color: t.legend, paddingTop: 8 }}
                                iconSize={8}
                            />
                        </PieChart>
                    ) : autoChartType === "area" ? (
                        <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                            <defs>
                                {seriesKeys.map((key, i) => (
                                    <linearGradient key={key} id={`pc-area-${i}`} x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor={seriesColor(key, i)} stopOpacity={isDark ? 0.3 : 0.2} />
                                        <stop offset="95%" stopColor={seriesColor(key, i)} stopOpacity={0.02} />
                                    </linearGradient>
                                ))}
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke={t.grid} vertical={false} />
                            <XAxis
                                dataKey={xKey} tickFormatter={fmtTick}
                                stroke={t.axisStroke} fontSize={10} tickLine={false} axisLine={false}
                                tick={{ fill: t.axisTick }}
                            />
                            <YAxis
                                stroke={t.axisStroke} fontSize={10} tickLine={false} axisLine={false}
                                tick={{ fill: t.axisTick }} tickFormatter={fmtValue}
                            />
                            <RechartsTooltip content={<PremiumTooltip />} />
                            {seriesKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: t.legend }} iconSize={8} />}
                            {seriesKeys.map((key, i) => (
                                <Area
                                    key={key} type="monotone" dataKey={key}
                                    stroke={seriesColor(key, i)} strokeWidth={2.5}
                                    fill={`url(#pc-area-${i})`}
                                    dot={{ r: 3, fill: seriesColor(key, i), strokeWidth: 0 }}
                                    activeDot={{
                                        r: 6, fill: seriesColor(key, i),
                                        strokeWidth: 3, stroke: t.dotStroke,
                                        style: { filter: `drop-shadow(0 0 6px ${seriesColor(key, i)}66)`, cursor: "pointer" },
                                    }}
                                    connectNulls
                                    animationDuration={1000}
                                    animationEasing="ease-out"
                                />
                            ))}
                        </AreaChart>
                    ) : (
                        <BarChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                            <defs>
                                {seriesKeys.map((key, i) => (
                                    <linearGradient key={key} id={`pc-bar-${i}`} x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="0%" stopColor={seriesColor(key, i)} stopOpacity={isDark ? 0.95 : 0.9} />
                                        <stop offset="100%" stopColor={seriesColor(key, i)} stopOpacity={isDark ? 0.55 : 0.45} />
                                    </linearGradient>
                                ))}
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke={t.grid} vertical={false} />
                            <XAxis
                                dataKey={xKey} tickFormatter={fmtTick}
                                stroke={t.axisStroke} fontSize={10} tickLine={false} axisLine={false}
                                tick={{ fill: t.axisTick }}
                            />
                            <YAxis
                                stroke={t.axisStroke} fontSize={10} tickLine={false} axisLine={false}
                                tick={{ fill: t.axisTick }} tickFormatter={fmtValue}
                            />
                            <RechartsTooltip content={<PremiumTooltip />} cursor={{ fill: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)", radius: 4 }} />
                            {seriesKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: t.legend }} iconSize={8} />}
                            {seriesKeys.map((key, i) => (
                                <Bar
                                    key={key} dataKey={key}
                                    fill={`url(#pc-bar-${i})`}
                                    radius={[6, 6, 0, 0]}
                                    maxBarSize={seriesKeys.length > 2 ? 28 : 40}
                                    animationDuration={800}
                                    animationEasing="ease-out"
                                />
                            ))}
                        </BarChart>
                    )}
                </ResponsiveContainer>
            )}

            {/* Meta footer */}
            {props.meta && Object.keys(props.meta).length > 0 && (
                <div style={{
                    display: "flex", gap: 16, marginTop: 12, paddingTop: 12,
                    borderTop: `1px solid ${t.tableBorder}`,
                }}>
                    {Object.entries(props.meta).map(([k, v]) => (
                        <span key={k} style={{ fontSize: 10, color: t.labelColor }}>
                            {k}: <strong style={{ color: t.titleColor, fontWeight: 600 }}>{String(v)}</strong>
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}

export default PremiumChart;
