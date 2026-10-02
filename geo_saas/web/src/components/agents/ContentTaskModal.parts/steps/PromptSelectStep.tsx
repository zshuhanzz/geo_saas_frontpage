import { CheckCircle2, Loader2, Search, ArrowUpDown, Sparkles } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { SORT_KEYS } from "../constants";
import type { ContentGoalDef, RankedPrompt } from "../types";

// ── Step 4: Prompt Selection ──

interface PromptSelectStepProps {
  goalMeta: ContentGoalDef | undefined;
  goalLabel: string;
  promptSearch: string;
  setPromptSearch: (s: string) => void;
  promptSortBy: string;
  setPromptSortBy: (s: string) => void;
  loadingPrompts: boolean;
  filteredPrompts: RankedPrompt[];
  selectedPromptIds: string[];
  togglePrompt: (id: string) => void;
}

export function PromptSelectStep({
  goalMeta,
  goalLabel,
  promptSearch,
  setPromptSearch,
  promptSortBy,
  setPromptSortBy,
  loadingPrompts,
  filteredPrompts,
  selectedPromptIds,
  togglePrompt,
}: PromptSelectStepProps) {
  const { t } = useTranslation("content");

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold mb-1">{t("taskModal.promptSelect.title")}</h3>
        <p className="text-xs text-muted-foreground mb-3">
          {t("taskModal.promptSelect.hint")}
        </p>
      </div>

      {/* Goal-based sort hint */}
      {goalMeta && (
        <div className="flex items-center gap-2 p-3 rounded-lg border border-primary/20 bg-primary/[0.02]">
          <Sparkles className="h-3.5 w-3.5 text-primary shrink-0" />
          <span className="text-xs text-muted-foreground">
            <Trans
              i18nKey="taskModal.promptSelect.goalHint"
              ns="content"
              values={{ label: goalLabel, sort: goalMeta.defaultSort }}
              components={{ 1: <strong /> }}
            />
          </span>
        </div>
      )}

      {/* Sort + Search controls */}
      <div className="flex gap-2">
        <div className="flex items-center gap-1.5 flex-1">
          <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <input
            type="text"
            value={promptSearch}
            onChange={(e) => setPromptSearch(e.target.value)}
            placeholder={t("taskModal.promptSelect.searchPlaceholder")}
            className="flex-1 rounded-lg border px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
        </div>
        <div className="flex items-center gap-1.5">
          <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          {SORT_KEYS.map((id) => (
            <button
              key={id}
              onClick={() => setPromptSortBy(id)}
              className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-colors ${
                promptSortBy === id
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted hover:bg-muted/80 text-muted-foreground"
              }`}
            >
              {t(`taskModal.worstSort.${id}`)}
            </button>
          ))}
        </div>
      </div>

      {/* Prompt list */}
      <div className="max-h-[300px] overflow-auto space-y-1.5 rounded-lg border p-2">
        {loadingPrompts ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : filteredPrompts.length === 0 ? (
          <div className="text-center py-8 text-xs text-muted-foreground">{t("taskModal.promptSelect.empty")}</div>
        ) : (
          filteredPrompts.map((p) => {
            const selected = selectedPromptIds.includes(p.id);
            return (
              <button
                key={p.id}
                onClick={() => togglePrompt(p.id)}
                className={`w-full text-left p-3 rounded-lg border transition-all duration-150 ${
                  selected ? "border-primary bg-primary/5" : "border-transparent hover:bg-muted/30"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className={`w-4 h-4 mt-0.5 rounded border-2 shrink-0 flex items-center justify-center transition-colors ${
                    selected ? "border-primary bg-primary" : "border-muted-foreground/30"
                  }`}>
                    {selected && <CheckCircle2 className="h-3 w-3 text-primary-foreground" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-foreground leading-relaxed line-clamp-2">
                      {p.prompt_text}
                    </p>
                    <div className="flex items-center gap-3 mt-1.5">
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">{p.platform}</Badge>
                      <span className="text-[10px] text-muted-foreground">{p.topic_name}</span>
                      <span className="text-[10px] text-muted-foreground ml-auto flex gap-3">
                        <span className={p.mention_count === 0 ? "text-red-400 font-medium" : ""}>{t("taskModal.promptSelect.mentionLabel", { count: p.mention_count })}</span>
                        <span className={p.citation_count === 0 ? "text-red-400 font-medium" : ""}>{t("taskModal.promptSelect.citationLabel", { count: p.citation_count })}</span>
                        <span className={p.negative_count > 0 ? "text-red-400 font-medium" : ""}>{t("taskModal.promptSelect.negativeLabel", { count: p.negative_count })}</span>
                      </span>
                    </div>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>

      {selectedPromptIds.length > 0 && (
        <p className="text-xs text-primary font-medium">{t("taskModal.promptSelect.selectedSummary", { count: selectedPromptIds.length })}</p>
      )}
    </div>
  );
}
