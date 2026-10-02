import { CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CONTENT_TYPE_DEFS } from "../constants";
import type { ContentGoalDef } from "../types";

// ── Step 2: Content Type ──

interface ContentTypeStepProps {
  contentType: string;
  setContentType: (ct: string) => void;
  topic: string;
  setTopic: (s: string) => void;
  goalMeta: ContentGoalDef | undefined;
}

export function ContentTypeStep({
  contentType,
  setContentType,
  topic,
  setTopic,
  goalMeta,
}: ContentTypeStepProps) {
  const { t } = useTranslation("content");

  return (
    <>
      <div>
        <h3 className="text-sm font-semibold mb-1">{t("taskModal.contentTypes.title")}</h3>
        <p className="text-xs text-muted-foreground mb-3">{t("taskModal.contentTypes.subtitle")}</p>
        <div className="grid grid-cols-2 gap-3">
          {CONTENT_TYPE_DEFS.map((ct) => {
            const isRecommended = goalMeta?.recommendedTypes.includes(ct.id);
            return (
              <button
                key={ct.id}
                onClick={() => setContentType(ct.id)}
                className={`text-left p-4 rounded-xl border-2 transition-all duration-200 relative ${
                  contentType === ct.id
                    ? "border-primary bg-primary/5 shadow-sm"
                    : "border-border hover:border-primary/40 hover:bg-muted/30"
                }`}
              >
                {isRecommended && (
                  <span className="absolute top-2 right-2 text-[9px] px-1.5 py-0.5 rounded-full bg-primary/15 text-primary font-semibold">
                    {t("taskModal.contentTypes.recommended")}
                  </span>
                )}
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{ct.icon}</span>
                  <span className="text-sm font-semibold">{t(`taskModal.contentTypes.items.${ct.id}.label`)}</span>
                  {contentType === ct.id && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">{t(`taskModal.contentTypes.items.${ct.id}.desc`)}</p>
              </button>
            );
          })}
        </div>
      </div>
      <div>
        <label className="text-sm font-medium mb-2 block">{t("taskModal.targetConfig.topicLabel")}</label>
        <p className="text-[11px] text-muted-foreground mb-2">{t("taskModal.targetConfig.topicHint")}</p>
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={t("taskModal.targetConfig.topicPlaceholder")}
          rows={3}
          className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
      </div>
    </>
  );
}
