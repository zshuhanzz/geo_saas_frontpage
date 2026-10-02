import { Zap, Brain, Route } from "lucide-react";
import type { AgentsTFn } from "./types";

// ── Helpers ──────────────────────────────────────────────────

export function getGreeting(t: AgentsTFn): string {
  const h = new Date().getHours();
  if (h < 6) return t("chat.greetings.lateNight");
  if (h < 12) return t("chat.greetings.morning");
  if (h < 14) return t("chat.greetings.noon");
  if (h < 18) return t("chat.greetings.afternoon");
  return t("chat.greetings.evening");
}

export function timeAgo(dateStr: string, t: AgentsTFn): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return t("chat.relative.justNow");
  if (mins < 60) return t("chat.relative.minutesAgo", { mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t("chat.relative.hoursAgo", { hours });
  const days = Math.floor(hours / 24);
  if (days === 1) return t("chat.relative.yesterday");
  return t("chat.relative.daysAgo", { days });
}

/** Simple SQL formatter — adds newlines and indentation for readability */
export function formatSQL(sql: string): string {
  if (!sql) return sql;
  const keywords = /\b(SELECT|FROM|WHERE|AND|OR|JOIN|LEFT JOIN|RIGHT JOIN|INNER JOIN|ON|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|INSERT|UPDATE|DELETE|SET|VALUES|INTO|CREATE|ALTER|DROP|WITH|AS|UNION|EXCEPT|INTERSECT|CASE|WHEN|THEN|ELSE|END)\b/gi;
  return sql
    .replace(keywords, (match) => `\n${match.toUpperCase()}`)
    .replace(/^\n/, "")
    .replace(/,\s+/g, ",\n  ")
    .trim();
}

export const SUGGESTION_ENTRIES = [
  { icon: "📊", key: "s1" },
  { icon: "🔍", key: "s2" },
  { icon: "💡", key: "s3" },
  { icon: "📈", key: "s4" },
] as const;

// ── Chart rendering uses shared PremiumChart component ───────

// ── Thinking Panel Component ─────────────────────────────────

export const TIER_ICONS: Record<number, React.ReactNode> = {
  1: <Zap className="h-3.5 w-3.5" />,
  2: <Brain className="h-3.5 w-3.5" />,
  3: <Route className="h-3.5 w-3.5" />,
  4: <Route className="h-3.5 w-3.5" />,
};

export const TIER_COLORS: Record<number, string> = {
  1: "text-blue-500",
  2: "text-purple-500",
  3: "text-amber-500",
  4: "text-emerald-500",
};

export const GOAL_LABEL_KEYS = [
  "brand_visibility", "citation_analysis", "sentiment_analysis", "competitor_comparison",
  "benchmark", "trend", "health", "sentiment", "opportunity_discovery",
  "faq", "aeo_article", "article", "recommendations", "brief",
] as const;
