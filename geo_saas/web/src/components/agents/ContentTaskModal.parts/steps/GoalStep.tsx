import { CheckCircle2, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CONTENT_GOAL_DEFS, GOAL_DICT_KEY, DOMAIN_META } from "../constants";
import type { ContentGoal, ContentGoalDef, DomainKey } from "../types";

// ── Step 1: Content Goal ──

interface GoalStepProps {
  contentGoal: ContentGoal | null;
  setContentGoal: (g: ContentGoal | null) => void;
  setSelectedDomains: (domains: string[]) => void;
  setPromptSortBy: (sort: string) => void;
  setContentType: (ct: string) => void;
  goalMeta: ContentGoalDef | undefined;
  goalLabel: string;
  contentTypeLabel: (id: string) => string;
  domainLabel: (id: string) => string;
}

export function GoalStep({
  contentGoal,
  setContentGoal,
  setSelectedDomains,
  setPromptSortBy,
  setContentType,
  goalMeta,
  goalLabel,
  contentTypeLabel,
  domainLabel,
}: GoalStepProps) {
  const { t } = useTranslation("content");

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold mb-1">{t("taskModal.goals.selectTitle")}</h3>
        <p className="text-xs text-muted-foreground mb-4">
          {t("taskModal.goals.selectHint")}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {CONTENT_GOAL_DEFS.map(goal => {
          const Icon = goal.icon;
          const selected = contentGoal === goal.id;
          const dictKey = GOAL_DICT_KEY[goal.id];
          return (
            <button
              key={goal.id}
              onClick={() => {
                const isSame = contentGoal === goal.id;
                setContentGoal(isSame ? null : goal.id);
                if (!isSame) {
                  // Auto-recommend domains and sort
                  setSelectedDomains([...goal.recommendedDomains]);
                  setPromptSortBy(goal.defaultSort);
                  // Auto-recommend content type (first recommended)
                  if (goal.recommendedTypes[0]) setContentType(goal.recommendedTypes[0]);
                }
              }}
              className={`flex items-start gap-3.5 p-5 rounded-xl border-2 transition-all duration-200 text-left ${
                selected
                  ? "border-primary bg-primary/5 shadow-md ring-1 ring-primary/20"
                  : "border-border hover:border-primary/40 hover:bg-muted/30"
              }`}
            >
              <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 border ${goal.color}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold">{t(`taskModal.goals.items.${dictKey}.label`)}</span>
                  {selected && <CheckCircle2 className="h-4 w-4 text-primary" />}
                </div>
                <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{t(`taskModal.goals.items.${dictKey}.desc`)}</p>
                <div className="flex items-center gap-1.5 mt-2.5">
                  {goal.recommendedDomains.map(d => {
                    const meta = DOMAIN_META[d as DomainKey];
                    return meta ? (
                      <span key={d} className={`text-[10px] px-1.5 py-0.5 rounded-md border font-medium ${meta.color}`}>
                        {meta.icon} {domainLabel(d)}
                      </span>
                    ) : null;
                  })}
                  <span className="text-[10px] text-muted-foreground/50 ml-1">
                    {t("taskModal.goals.recommendedTypes", { count: goal.recommendedTypes.length })}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {goalMeta && (
        <div className="rounded-xl border border-primary/20 bg-primary/[0.03] p-4 space-y-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">{t("taskModal.goals.activatedBadge", { label: goalLabel })}</span>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {t("taskModal.goals.activatedDesc", {
              type: contentTypeLabel(goalMeta.recommendedTypes[0]),
              domains: goalMeta.recommendedDomains.map(d => domainLabel(d)).join(", "),
              sort: goalMeta.defaultSort,
            })}
          </p>
        </div>
      )}

      {!contentGoal && (
        <p className="text-xs text-center text-muted-foreground/60 pt-2">
          {t("taskModal.goals.skipHint")}
        </p>
      )}
    </div>
  );
}
