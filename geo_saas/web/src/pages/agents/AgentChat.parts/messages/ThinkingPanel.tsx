import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Brain, Database, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ThinkingStep } from "../types";
import { TIER_ICONS, TIER_COLORS, formatSQL } from "../utils";

export function ThinkingPanel({ steps, streaming }: { steps: ThinkingStep[]; streaming?: boolean }) {
  const { t } = useTranslation("agents");
  const [expanded, setExpanded] = useState(false);
  if (!steps || steps.length === 0) return null;

  const maxTier = Math.max(...steps.map((s) => s.tier));

  return (
    <div className="mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors py-1.5 px-3 rounded-lg hover:bg-muted/50"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <Brain className="h-3.5 w-3.5 text-purple-500" />
        <span className="font-medium">
          {t("chat.cot.tier", { tier: maxTier })}
          {streaming && <span className="text-primary ml-1 animate-pulse">{t("chat.cot.thinking")}</span>}
        </span>
        <span className="text-muted-foreground/40">{t("chat.cot.stepsCount", { count: steps.length })}</span>
      </button>
      {expanded && (
        <div className="mt-2 ml-2 border-l-2 border-primary/20 pl-4 space-y-3">
          {steps.map((step, i) => (
            <div key={i} className="text-xs">
              <div className="flex items-center gap-2">
                <span className={cn("shrink-0", TIER_COLORS[step.tier] || "text-muted-foreground")}>
                  {TIER_ICONS[step.tier] || <Zap className="h-3.5 w-3.5" />}
                </span>
                <span className="font-semibold text-foreground">{step.label}</span>
                <span className="text-muted-foreground/70">{step.detail}</span>
              </div>
              {step.sql && (
                <div className="mt-1.5 ml-6">
                  <div className="flex items-center gap-1.5 text-muted-foreground/60 mb-1">
                    <Database className="h-3 w-3" />
                    <span className="text-[10px] uppercase tracking-widest font-semibold">SQL</span>
                  </div>
                  <pre className="text-[11px] leading-relaxed bg-slate-50 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-700/50 rounded-lg px-3 py-2.5 overflow-x-auto font-mono text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
                    {formatSQL(step.sql)}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
