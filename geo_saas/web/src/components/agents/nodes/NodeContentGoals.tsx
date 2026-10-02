import { useState, useEffect } from "react";
import { Target } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getOptimizationMetrics, getOptimizationSubgoals, type OptimizationMetric, type OptimizationSubgoal } from "@/lib/api";

interface NodeContentGoalsProps {
  value: { selectedMetrics: string[]; selectedSubgoals: string[] };
  onChange: (data: { selectedMetrics: string[]; selectedSubgoals: string[] }) => void;
  analyzerContext?: any;
}

export default function NodeContentGoals({ value, onChange, analyzerContext }: NodeContentGoalsProps) {
  const { t } = useTranslation("content");
  const [metrics, setMetrics] = useState<OptimizationMetric[]>([]);
  const [subgoals, setSubgoals] = useState<OptimizationSubgoal[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([getOptimizationMetrics(), getOptimizationSubgoals()])
      .then(([m, sg]) => {
        setMetrics(m);
        setSubgoals(sg);
        // Pre-fill from analyzer context if available and not yet selected
        if (analyzerContext && !loaded) {
          const opps = analyzerContext.content_opportunities || [];
          const recMetrics = new Set<string>();
          const recSubgoals = new Set<string>();
          opps.forEach((o: any) => {
            (o.recommended_metrics || []).forEach((m: string) => recMetrics.add(m));
            (o.recommended_subgoals || []).forEach((s: string) => recSubgoals.add(s));
          });
          if (recMetrics.size > 0 || recSubgoals.size > 0) {
            onChange({
              selectedMetrics: Array.from(recMetrics),
              selectedSubgoals: Array.from(recSubgoals),
            });
          }
        }
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [analyzerContext]);

  const toggleMetric = (id: string) => {
    const next = value.selectedMetrics.includes(id)
      ? value.selectedMetrics.filter((m) => m !== id)
      : [...value.selectedMetrics, id];
    // Remove subgoals of unselected metrics
    const validSubgoals = value.selectedSubgoals.filter((sg) => {
      const sub = subgoals.find((s) => s.id === sg);
      return sub && next.includes(sub.metric_id);
    });
    onChange({ selectedMetrics: next, selectedSubgoals: validSubgoals });
  };

  const toggleSubgoal = (id: string) => {
    const next = value.selectedSubgoals.includes(id)
      ? value.selectedSubgoals.filter((s) => s !== id)
      : [...value.selectedSubgoals, id];
    onChange({ ...value, selectedSubgoals: next });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Target className="w-5 h-5 text-blue-400" />
        <h3 className="text-lg font-semibold text-foreground">{t("nodes.contentGoals.title")}</h3>
      </div>

      <p className="text-sm text-muted-foreground">{t("nodes.contentGoals.subtitle")}</p>

      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        {t("nodes.contentGoals.sectionTitle")}
      </p>

      <div className="space-y-3">
        {metrics.map((m) => {
          const metricSelected = value.selectedMetrics.includes(m.id);
          const children = subgoals.filter((sg) => sg.metric_id === m.id);

          return (
            <div key={m.id} className="group">
              {/* Metric card */}
              <button
                onClick={() => toggleMetric(m.id)}
                className={`w-full text-left p-4 rounded-xl border-2 transition-all duration-200 ${
                  metricSelected
                    ? "border-blue-500/50 bg-blue-500/10 ring-1 ring-blue-500/20"
                    : "border-border bg-muted/30 hover:border-blue-500/30 hover:bg-muted/50"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 ${
                    metricSelected ? "border-blue-500 bg-blue-500" : "border-muted-foreground/30"
                  }`}>
                    {metricSelected && (
                      <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </div>
                  {m.icon && <span className="text-lg">{m.icon}</span>}
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-semibold">{m.name_zh}</span>
                    <span className="text-xs text-muted-foreground ml-1.5">({m.name_en})</span>
                  </div>
                </div>
                <p className="text-[11px] text-muted-foreground mt-1.5 ml-8 leading-relaxed">{m.description}</p>
              </button>

              {/* Tree-connected subgoals */}
              {children.length > 0 && (
                <div className="ml-6 mt-0">
                  {children.map((sg, idx) => {
                    const sgSelected = value.selectedSubgoals.includes(sg.id);
                    const isLast = idx === children.length - 1;
                    return (
                      <div key={sg.id} className="flex items-stretch">
                        {/* Tree connector line */}
                        <div className="flex flex-col items-center w-6 shrink-0">
                          <div className={`w-px flex-1 ${isLast ? "h-1/2" : ""} ${metricSelected ? "bg-blue-500/30" : "bg-border"}`} />
                          <div className={`w-3 h-px ${metricSelected ? "bg-blue-500/30" : "bg-border"}`} style={{ alignSelf: "flex-start", marginTop: "14px", marginLeft: "50%" }} />
                          {!isLast && <div className={`w-px flex-1 ${metricSelected ? "bg-blue-500/30" : "bg-border"}`} />}
                        </div>
                        <button
                          onClick={() => {
                            if (!metricSelected) toggleMetric(m.id);
                            toggleSubgoal(sg.id);
                          }}
                          className={`flex-1 text-left px-3 py-2 my-0.5 rounded-lg border text-xs transition-colors ${
                            sgSelected
                              ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300 font-medium"
                              : metricSelected
                              ? "border-border/60 text-muted-foreground hover:border-emerald-500/30 hover:bg-muted/20"
                              : "border-transparent text-muted-foreground/60"
                          }`}
                        >
                          <span>{sg.name_zh}</span>
                          <span className="text-muted-foreground/50 ml-1">({sg.name_en})</span>
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {analyzerContext && (
        <p className="text-xs text-amber-400/70">
          {t("nodes.contentGoals.autofillHint")}
        </p>
      )}
    </div>
  );
}
