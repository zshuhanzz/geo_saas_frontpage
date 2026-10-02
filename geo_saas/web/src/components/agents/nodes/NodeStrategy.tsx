import { useState } from "react";
import { Sparkles, Loader2, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface StrategyData {
  strategies: Array<{
    name: string;
    description: string;
    dimensions: {
      instruction: string;
      format: { structure: string; schema_markup?: string; word_count?: string };
      tone: string;
      constraints: string[];
      enhancement_rules: string[];
    };
    source_metrics: string[];
    source_subgoals: string[];
  }>;
  strategy_summary: string;
}

interface PlatformRec {
  platform_type: string;
  engines: string[];
  citation_share: number;
  priority: string;
  engine_breakdown: Record<string, number>;
}

interface NodeStrategyProps {
  strategy: StrategyData | null;
  loading: boolean;
  onRegenerate: () => void;
  onEdit: (edits: string) => void;
  platformRecommendations?: PlatformRec[];
}

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

export default function NodeStrategy({ strategy, loading, onRegenerate, onEdit, platformRecommendations }: NodeStrategyProps) {
  const { t } = useTranslation("content");
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="w-6 h-6 animate-spin mb-3" />
        <p className="text-sm">{t("nodes.strategy.generating")}</p>
      </div>
    );
  }

  if (!strategy) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <p>{t("nodes.strategy.needPrior")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-yellow-400" />
          <h3 className="text-lg font-semibold text-foreground">{t("nodes.strategy.title")}</h3>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => setEditing(!editing)}>
            <Pencil className="w-3 h-3 mr-1" />
            {t("nodes.strategy.tweak")}
          </Button>
          <Button variant="ghost" size="sm" onClick={onRegenerate}>
            {t("nodes.strategy.regenerate")}
          </Button>
        </div>
      </div>

      {/* Strategy summary */}
      <p className="text-sm text-foreground/80 bg-muted/50 border border-border rounded-lg p-3">
        {strategy.strategy_summary}
      </p>

      {/* AI Engine Breakdown */}
      {platformRecommendations && platformRecommendations.length > 0 && (
        <div className="border border-border rounded-lg p-3 bg-muted/30">
          <h4 className="text-sm font-medium text-foreground mb-2">{t("nodes.strategy.engineDistribution")}</h4>
          <div className="space-y-2">
            {platformRecommendations.map((rec, i) => {
              const total = Object.values(rec.engine_breakdown || {}).reduce((a, b) => a + b, 0) || 1;
              return (
                <div key={i} className="flex items-center gap-3">
                  <span className="text-xs font-medium text-foreground w-24 shrink-0 truncate">{rec.platform_type}</span>
                  <div className="flex-1 h-4 rounded-full overflow-hidden bg-muted flex">
                    {Object.entries(rec.engine_breakdown || {}).map(([eng, count]) => {
                      const pct = Math.round((count / total) * 100);
                      return (
                        <div
                          key={eng}
                          style={{ width: `${pct}%`, backgroundColor: ENGINE_COLORS[eng.toLowerCase()] || "#8b5cf6" }}
                          className="h-full"
                          title={`${eng} ${pct}%`}
                        />
                      );
                    })}
                  </div>
                  <div className="flex gap-2 shrink-0">
                    {Object.entries(rec.engine_breakdown || {}).map(([eng, count]) => {
                      const pct = Math.round((count / total) * 100);
                      return (
                        <span key={eng} className="text-[10px] text-muted-foreground flex items-center gap-1">
                          <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: ENGINE_COLORS[eng.toLowerCase()] || "#8b5cf6" }} />
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
        {strategy.strategies.map((s, i) => (
          <div key={i} className="border border-border rounded-lg p-3 bg-muted/30">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono text-muted-foreground">#{i + 1}</span>
              <span className="font-medium text-sm text-foreground">{s.name}</span>
            </div>
            <p className="text-xs text-muted-foreground mb-2">{s.description}</p>
            <div className="flex flex-wrap gap-1">
              <Badge variant="outline" className="text-xs">{s.dimensions.tone}</Badge>
              {s.dimensions.constraints.slice(0, 2).map((c, j) => (
                <Badge key={j} variant="outline" className="text-xs text-muted-foreground">{c}</Badge>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Edit panel */}
      {editing && (
        <div className="border border-border rounded-lg p-3 bg-muted/50">
          <p className="text-xs text-muted-foreground mb-2">{t("nodes.strategy.tweakHint")}</p>
          <textarea
            className="w-full bg-muted border border-border rounded p-2 text-sm text-foreground resize-none"
            rows={3}
            placeholder={t("nodes.strategy.tweakPlaceholder")}
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
          />
          <div className="flex justify-end mt-2">
            <Button
              size="sm"
              onClick={() => { onEdit(editText); setEditing(false); setEditText(""); }}
              disabled={!editText.trim()}
            >
              {t("nodes.strategy.applyTweak")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
