import { useTranslation } from "react-i18next";

// ── Step 6: Model + Cron ──

interface ModelScheduleStepProps {
  contentModelIds: string[];
  modelId: string;
  setModelId: (s: string) => void;
  cronExpression: string;
  setCronExpression: (s: string) => void;
}

export function ModelScheduleStep({
  contentModelIds,
  modelId,
  setModelId,
  cronExpression,
  setCronExpression,
}: ModelScheduleStepProps) {
  const { t } = useTranslation("content");

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold mb-1">{t("taskModal.modelSchedule.title")}</h3>
        <p className="text-xs text-muted-foreground mb-4">{t("taskModal.modelSchedule.subtitle")}</p>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-xs font-medium text-muted-foreground">{t("taskModal.modelSchedule.modelLabel")}</span>
        <div className="flex items-center gap-2">
          {contentModelIds.map((m) => (
            <button
              key={m}
              onClick={() => setModelId(m)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-all ${
                modelId === m
                  ? "bg-primary/10 border-primary/40 text-primary"
                  : "bg-muted/30 border-border text-muted-foreground hover:border-primary/20"
              }`}
            >
              {m.replace("gemini-", "Gemini ").replace("-preview", "")}
            </button>
          ))}
        </div>
      </div>

      <div className="border border-border/60 rounded-lg p-4 bg-muted/10 space-y-3">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="content-enable-cron"
            className="rounded"
            checked={!!cronExpression}
            onChange={(e) => setCronExpression(e.target.checked ? "0 9 * * 1" : "")}
          />
          <label htmlFor="content-enable-cron" className="text-sm font-semibold cursor-pointer select-none">
            {t("taskModal.modelSchedule.scheduleToggle")}
          </label>
        </div>
        {!!cronExpression && (
          <div className="pl-6 space-y-2 mt-2">
            <label className="text-xs text-muted-foreground block">{t("taskModal.modelSchedule.cronLabel")}</label>
            <input
              type="text"
              value={cronExpression}
              onChange={(e) => setCronExpression(e.target.value)}
              placeholder="e.g. 0 9 * * 1"
              className="w-full max-w-sm rounded-md border border-input bg-background px-3 py-1.5 text-sm font-mono h-9 focus:outline-none focus:ring-2 focus:ring-ring/30"
            />
            <p className="text-[11px] text-muted-foreground mt-1">{t("taskModal.modelSchedule.cronHint")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
