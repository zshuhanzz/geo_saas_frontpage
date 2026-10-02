import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  comparisonPresentation,
  type ImprovementDirection,
} from "./reportComparison";

export function PreviousPeriodChange({
  value,
  improvement = "higher",
  unit = "%",
  absolute = false,
}: {
  value: number | null | undefined;
  improvement?: ImprovementDirection;
  unit?: string;
  absolute?: boolean;
}) {
  const { t } = useTranslation("reports");
  const presentation = comparisonPresentation(value, improvement);
  if (value == null || !Number.isFinite(Number(value))) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const numeric = Number(value);
  const Icon = presentation.direction === "up" ? ArrowUp : presentation.direction === "down" ? ArrowDown : Minus;
  const tone = presentation.tone === "positive"
    ? "text-emerald-500"
    : presentation.tone === "negative"
      ? "text-red-400"
      : "text-muted-foreground";
  const displayed = absolute ? Math.abs(numeric) : numeric;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${tone}`}>
      <Icon className="h-3.5 w-3.5" />
      {displayed > 0 && !absolute ? "+" : ""}{displayed}{unit}
      <span className="font-normal text-muted-foreground">{t("comparison.vsPrevious")}</span>
    </span>
  );
}
