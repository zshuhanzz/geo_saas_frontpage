import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

/* HITL Review Panel */
export function HitlReviewPanel({
  feedbackInput,
  sending,
  onFeedbackChange,
  onReview,
}: {
  feedbackInput: string;
  sending: boolean;
  onFeedbackChange: (val: string) => void;
  onReview: (approved: boolean) => void;
}) {
  const { t } = useTranslation("agents");
  return (
    <div className="shrink-0 border-t bg-amber-50/50 dark:bg-amber-950/20 px-4 py-4">
      <div className="max-w-4xl mx-auto space-y-3">
        <div className="flex items-center gap-2 text-sm font-medium text-amber-700 dark:text-amber-400">
          <span>⚡</span>
          <span>{t("chat.contentReady")}</span>
        </div>
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <textarea
              value={feedbackInput}
              onChange={(e) => onFeedbackChange(e.target.value)}
              placeholder={t("chat.regenFeedbackPlaceholder")}
              rows={2}
              className="w-full resize-none rounded-xl border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/50"
              disabled={sending}
            />
          </div>
          <div className="flex gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              disabled={sending}
              onClick={() => onReview(false)}
              className="h-9 rounded-lg"
            >
              {sending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
              {t("chat.regenerate")}
            </Button>
            <Button
              size="sm"
              disabled={sending}
              onClick={() => onReview(true)}
              className="h-9 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground"
            >
              {sending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
              {t("chat.approve")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
