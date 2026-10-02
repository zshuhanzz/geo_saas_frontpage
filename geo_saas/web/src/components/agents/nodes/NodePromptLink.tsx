import { useState, useEffect } from "react";
import { Link, Lock, ArrowUpDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { getRankedPrompts } from "@/lib/api";

interface PromptItem {
  id: string;
  prompt_text: string;
  platform: string;
  topic_name: string;
  mention_count?: number;
  avg_position?: number;
  citation_count?: number;
  negative_count?: number;
}

type SortMode = "visibility" | "citation" | "sentiment";

const SORT_OPTIONS: SortMode[] = ["visibility", "citation", "sentiment"];

function ScoreBadges({ prompt, sortBy }: { prompt: PromptItem; sortBy: SortMode }) {
  const { t } = useTranslation("content");
  const mentions = prompt.mention_count ?? 0;
  const citations = prompt.citation_count ?? 0;
  const negatives = prompt.negative_count ?? 0;

  return (
    <div className="flex items-center gap-1.5 mt-1">
      <span className={`text-[10px] px-1.5 py-0.5 rounded ${sortBy === "visibility" ? "bg-blue-500/10 text-blue-400 font-medium" : "text-muted-foreground"}`}>
        {t("nodes.promptLink.mentionLabel", { count: mentions })}
      </span>
      <span className={`text-[10px] px-1.5 py-0.5 rounded ${sortBy === "citation" ? "bg-green-500/10 text-green-400 font-medium" : "text-muted-foreground"}`}>
        {t("nodes.promptLink.citationLabel", { count: citations })}
      </span>
      <span className={`text-[10px] px-1.5 py-0.5 rounded ${sortBy === "sentiment" ? "bg-red-500/10 text-red-400 font-medium" : "text-muted-foreground"}`}>
        {t("nodes.promptLink.negativeLabel", { count: negatives })}
      </span>
    </div>
  );
}

interface NodePromptLinkProps {
  clientId: string;
  value: { promptIds: string[]; locked: boolean };
  onChange: (data: { promptIds: string[]; locked: boolean }) => void;
  analyzerContext?: any;
}

export default function NodePromptLink({ clientId, value, onChange, analyzerContext }: NodePromptLinkProps) {
  const { t } = useTranslation("content");
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<SortMode>("visibility");
  const isLocked = !!analyzerContext;

  useEffect(() => {
    if (analyzerContext) {
      // Locked mode: prompts come from analyzer content_opportunities
      const opps = analyzerContext.content_opportunities || [];
      const ids = new Set<string>();
      opps.forEach((o: any) => (o.related_prompts || []).forEach((id: string) => ids.add(id)));
      onChange({ promptIds: Array.from(ids), locked: true });
      // Fetch prompt details for display
      if (ids.size > 0) {
        getRankedPrompts(clientId, "visibility", 100).then((all) => {
          setPrompts(all.filter((p: any) => ids.has(p.id)));
          setLoading(false);
        }).catch(() => setLoading(false));
      } else {
        setLoading(false);
      }
    } else {
      // Open mode: fetch ranked prompts with current sort
      setLoading(true);
      getRankedPrompts(clientId, sortBy, 50)
        .then((data) => {
          setPrompts(data);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    }
  }, [clientId, analyzerContext, sortBy]);

  const togglePrompt = (id: string) => {
    if (isLocked) return;
    const next = value.promptIds.includes(id)
      ? value.promptIds.filter((p) => p !== id)
      : [...value.promptIds, id];
    onChange({ promptIds: next, locked: false });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Link className="w-5 h-5 text-orange-400" />
        <h3 className="text-lg font-semibold text-foreground">{t("nodes.promptLink.title")}</h3>
        {isLocked && (
          <Badge variant="outline" className="text-xs text-amber-400 border-amber-500/30">
            <Lock className="w-3 h-3 mr-1" />
            {t("nodes.promptLink.lockedBadge")}
          </Badge>
        )}
      </div>

      {isLocked ? (
        <p className="text-sm text-amber-400/80">
          {t("nodes.promptLink.lockedHint", { count: value.promptIds.length })}
        </p>
      ) : (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {t("nodes.promptLink.manualHint")}
          </p>
          <div className="flex items-center gap-1.5">
            <ArrowUpDown className="w-3.5 h-3.5 text-muted-foreground" />
            {SORT_OPTIONS.map((id) => (
              <button
                key={id}
                onClick={() => setSortBy(id)}
                className={`text-[11px] px-2 py-1 rounded-md border transition-colors ${
                  sortBy === id
                    ? "border-primary bg-primary/10 text-primary font-medium"
                    : "border-border text-muted-foreground hover:border-primary/30"
                }`}
              >
                {t(`domains.${id}`)}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-muted-foreground text-sm py-4">{t("nodes.promptLink.loading")}</div>
      ) : (
        <div className="space-y-1 max-h-[300px] overflow-y-auto">
          {prompts.map((p) => (
            <button
              key={p.id}
              onClick={() => togglePrompt(p.id)}
              disabled={isLocked}
              className={`w-full text-left p-2.5 rounded-lg border text-sm transition-colors ${
                value.promptIds.includes(p.id)
                  ? "border-orange-500/30 bg-orange-500/5 text-foreground"
                  : "border-border text-muted-foreground hover:border-border/80"
              } ${isLocked ? "cursor-default opacity-80" : "cursor-pointer"}`}
            >
              <div className="flex items-center justify-between">
                <span className="truncate flex-1">{p.prompt_text}</span>
                <Badge variant="outline" className="text-xs ml-2 shrink-0">{p.platform}</Badge>
              </div>
              <ScoreBadges prompt={p} sortBy={sortBy} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
