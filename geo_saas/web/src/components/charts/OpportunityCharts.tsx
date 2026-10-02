/**
 * OpportunityCharts — Scatter + Bar charts for opportunity discovery reports.
 *
 * TopicQuadrantScatter: bubble chart with quadrant background zones
 * PlatformCitationBar: stacked bar chart by engine per platform
 */
import { useState, useEffect } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, ReferenceArea, Cell,
  BarChart, Bar, Legend,
} from "recharts";
import { useTranslation } from "react-i18next";

// Canonical quadrant keys — used as BG color lookup AND as translation key
// suffixes (analysis.opportunity.quadrantLabels.{strong,weak,untapped,emerging}).
type QuadrantKey = "strong" | "weak" | "untapped" | "emerging";
const QUADRANT_FROM_SERVER: Record<string, QuadrantKey> = {
  "Strong": "strong", "Weak": "weak", "Untapped": "untapped", "Emerging": "emerging",
  "强势": "strong", "薄弱": "weak", "待挖掘": "untapped", "新兴": "emerging",
};

// ── Theme ──────────────────────────────────────────────────────────────

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

// ── Colors ─────────────────────────────────────────────────────────────

// Color map keyed by canonical QuadrantKey (server values normalize via
// QUADRANT_FROM_SERVER before lookup).
const QUADRANT_COLORS_BY_KEY: Record<QuadrantKey, { bg: string; fill: string; stroke: string }> = {
  strong:   { bg: "rgba(16,185,129,0.08)", fill: "#10b981", stroke: "#059669" },
  weak:     { bg: "rgba(239,68,68,0.08)",  fill: "#ef4444", stroke: "#dc2626" },
  untapped: { bg: "rgba(245,158,11,0.08)", fill: "#f59e0b", stroke: "#d97706" },
  emerging: { bg: "rgba(59,130,246,0.08)", fill: "#3b82f6", stroke: "#2563eb" },
};
const colorsFor = (raw: string) => QUADRANT_COLORS_BY_KEY[QUADRANT_FROM_SERVER[raw]] ?? null;

const ENGINE_COLORS: Record<string, string> = {
  chatgpt: "#10b981",
  gemini: "#6366f1",
  aimode: "#f59e0b",
  ai_mode: "#f59e0b",
  perplexity: "#8b5cf6",
  aioverview: "#0ea5e9",
  ai_overview: "#0ea5e9",
  google_ai_overview: "#0ea5e9",
};
const ENGINE_PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

// ── TopicQuadrantScatter ───────────────────────────────────────────────

interface TopicQuadrant {
  topic: string;
  primary_quadrant: string;
  secondary_quadrant?: string | null;
  action?: string;
  metrics?: {
    visibility_score?: number;
    citation_rate?: number;
    competitor_citation_rate?: number;
    own_mention_count?: number;
    total_prompts?: number;
    trend_direction?: string;
  };
}

interface TopicQuadrantScatterProps {
  data: TopicQuadrant[];
}

function ScatterTooltip({ active, payload }: any) {
  const { t } = useTranslation("agents");
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const canonicalKey = QUADRANT_FROM_SERVER[d.quadrant];
  const quadrantLabel = canonicalKey ? t(`analysis.opportunity.quadrantLabels.${canonicalKey}`) : d.quadrant;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 shadow-lg text-xs space-y-1">
      <div className="font-semibold text-foreground">{d.topic}</div>
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">{t("analysis.opportunity.chart.tooltipQuadrant")}:</span>
        <span className="font-medium">{quadrantLabel}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">{t("analysis.opportunity.chart.tooltipVisibility")}:</span>
        <span>{Math.round((d.visibility ?? 0) * 100)}%</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">{t("analysis.opportunity.chart.tooltipCitation")}:</span>
        <span>{Math.round((d.citation ?? 0) * 100)}%</span>
      </div>
      {d.mentions != null && (
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">{t("analysis.opportunity.chart.tooltipMentions")}:</span>
          <span>{d.mentions}</span>
        </div>
      )}
    </div>
  );
}

export function TopicQuadrantScatter({ data }: TopicQuadrantScatterProps) {
  const isDark = useIsDark();
  const { t } = useTranslation("agents");

  if (!data || data.length === 0) return null;

  // Transform data for scatter chart
  const scatterData = data.map((tq) => ({
    topic: tq.topic,
    quadrant: tq.primary_quadrant,
    visibility: tq.metrics?.visibility_score ?? 0,
    citation: tq.metrics?.citation_rate ?? 0,
    mentions: tq.metrics?.own_mention_count ?? 1,
  }));

  // Determine axis ranges (values are 0-1 ratios, don't clamp to 1)
  const maxVis = Math.max(0.01, ...scatterData.map((d) => d.visibility));
  const maxCit = Math.max(0.01, ...scatterData.map((d) => d.citation));

  // Midpoints for quadrant zones
  const midX = maxVis * 0.5;
  const midY = maxCit * 0.5;

  const axisColor = isDark ? "#4b5563" : "#d1d5db";
  const textColor = isDark ? "#9ca3af" : "#6b7280";

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 16, right: 16, bottom: 24, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={axisColor} opacity={0.3} />

          {/* Quadrant background zones */}
          <ReferenceArea x1={midX} x2={maxVis * 1.1} y1={midY} y2={maxCit * 1.1}
            fill={QUADRANT_COLORS_BY_KEY.strong.bg} fillOpacity={1} label={{ value: t("analysis.opportunity.quadrantLabels.strong"), position: "insideTopRight", fill: textColor, fontSize: 11 }} />
          <ReferenceArea x1={0} x2={midX} y1={midY} y2={maxCit * 1.1}
            fill={QUADRANT_COLORS_BY_KEY.emerging.bg} fillOpacity={1} label={{ value: t("analysis.opportunity.quadrantLabels.emerging"), position: "insideTopLeft", fill: textColor, fontSize: 11 }} />
          <ReferenceArea x1={midX} x2={maxVis * 1.1} y1={0} y2={midY}
            fill={QUADRANT_COLORS_BY_KEY.weak.bg} fillOpacity={1} label={{ value: t("analysis.opportunity.quadrantLabels.weak"), position: "insideBottomRight", fill: textColor, fontSize: 11 }} />
          <ReferenceArea x1={0} x2={midX} y1={0} y2={midY}
            fill={QUADRANT_COLORS_BY_KEY.untapped.bg} fillOpacity={1} label={{ value: t("analysis.opportunity.quadrantLabels.untapped"), position: "insideBottomLeft", fill: textColor, fontSize: 11 }} />

          <XAxis
            type="number" dataKey="visibility" name={t("analysis.opportunity.chart.axisVisibility")}
            domain={[0, maxVis * 1.1]}
            tick={{ fill: textColor, fontSize: 11 }}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            label={{ value: t("analysis.opportunity.chart.axisVisibility"), position: "bottom", offset: 4, fill: textColor, fontSize: 11 }}
          />
          <YAxis
            type="number" dataKey="citation" name={t("analysis.opportunity.chart.axisCitation")}
            domain={[0, maxCit * 1.1]}
            tick={{ fill: textColor, fontSize: 11 }}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            label={{ value: t("analysis.opportunity.chart.axisCitation"), angle: -90, position: "insideLeft", offset: 10, fill: textColor, fontSize: 11 }}
          />
          <ZAxis type="number" dataKey="mentions" range={[40, 200]} />
          <RechartsTooltip content={<ScatterTooltip />} />
          <Scatter data={scatterData} name="Topics">
            {scatterData.map((entry, i) => {
              const colors = colorsFor(entry.quadrant);
              return (
                <Cell
                  key={i}
                  fill={colors?.fill ?? "#6b7280"}
                  stroke={colors?.stroke ?? "#4b5563"}
                  strokeWidth={1.5}
                  fillOpacity={0.8}
                />
              );
            })}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── PlatformCitationBar ────────────────────────────────────────────────

interface PlatformRecommendation {
  platform_type: string;
  engines: string[];
  citation_share: number;
  priority: string;
  engine_breakdown?: Record<string, number>;
}

interface PlatformCitationBarProps {
  data: PlatformRecommendation[];
}

function BarTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 shadow-lg text-xs space-y-1">
      <div className="font-semibold text-foreground mb-1">{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.fill }} />
          <span className="text-muted-foreground">{p.dataKey}:</span>
          <span>{Math.round((p.value ?? 0) * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

export function PlatformCitationBar({ data }: PlatformCitationBarProps) {
  const isDark = useIsDark();

  if (!data || data.length === 0) return null;

  // Collect all engines across all platforms
  const allEngines = new Set<string>();
  data.forEach((rec) => {
    if (rec.engine_breakdown) {
      Object.keys(rec.engine_breakdown).forEach((e) => allEngines.add(e));
    } else {
      rec.engines?.forEach((e) => allEngines.add(e));
    }
  });
  const engines = Array.from(allEngines);

  // Transform data for stacked bar
  // engine_breakdown values are raw counts — normalize to percentages per platform
  const barData = data.map((rec) => {
    const point: Record<string, any> = { platform: rec.platform_type };
    if (rec.engine_breakdown) {
      const total = Object.values(rec.engine_breakdown).reduce((a, b) => a + b, 0) || 1;
      for (const e of engines) {
        point[e] = (rec.engine_breakdown[e] ?? 0) / total;
      }
    } else {
      // Fallback: split citation_share evenly across engines
      const share = rec.citation_share / (rec.engines?.length || 1);
      for (const e of engines) {
        point[e] = rec.engines?.includes(e) ? share : 0;
      }
    }
    return point;
  });

  const axisColor = isDark ? "#4b5563" : "#d1d5db";
  const textColor = isDark ? "#9ca3af" : "#6b7280";

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={barData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={axisColor} opacity={0.3} />
          <XAxis
            dataKey="platform"
            tick={{ fill: textColor, fontSize: 11 }}
            axisLine={{ stroke: axisColor }}
          />
          <YAxis
            tick={{ fill: textColor, fontSize: 11 }}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            axisLine={{ stroke: axisColor }}
          />
          <RechartsTooltip content={<BarTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 11, color: textColor }}
          />
          {engines.map((engine, i) => (
            <Bar
              key={engine}
              dataKey={engine}
              stackId="engines"
              fill={ENGINE_COLORS[engine.toLowerCase()] ?? ENGINE_PALETTE[i % ENGINE_PALETTE.length]}
              radius={i === engines.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
