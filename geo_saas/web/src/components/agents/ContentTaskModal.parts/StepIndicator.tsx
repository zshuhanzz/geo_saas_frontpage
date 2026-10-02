import { CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";

// ─── Step Indicator ─────────────────────────────────────────────────

export function StepIndicator({ currentStep }: { currentStep: number }) {
  const { t } = useTranslation("content");
  const STEP_KEYS = ["goal", "type", "targetConfig", "promptSelect", "dataStrategy", "modelSchedule", "confirm"] as const;
  const steps = STEP_KEYS.map((key, i) => ({ num: i + 1, label: t(`taskModal.steps.${key}`) }));

  return (
    <div className="flex items-center justify-between">
      {steps.map((s, i) => (
        <div key={s.num} className="flex items-center gap-1">
          <div className="flex flex-col items-center gap-1">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center border-2 transition-all duration-300 ${
              currentStep > s.num
                ? "bg-primary border-primary text-primary-foreground"
                : currentStep === s.num
                ? "border-primary text-primary"
                : "border-muted-foreground/30 text-muted-foreground/50"
            }`}>
              {currentStep > s.num
                ? <CheckCircle2 className="h-3.5 w-3.5" />
                : <span className="text-[10px] font-semibold">{s.num}</span>
              }
            </div>
            <span className={`text-[10px] font-medium whitespace-nowrap ${
              currentStep === s.num ? "text-foreground" : "text-muted-foreground/60"
            }`}>{s.label}</span>
          </div>
          {i < steps.length - 1 && (
            <div className={`h-px w-3 mx-0.5 mb-4 transition-colors ${currentStep > s.num ? "bg-primary" : "bg-border"}`} />
          )}
        </div>
      ))}
    </div>
  );
}
