import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "./Progress";
import { formatNumber, formatPercent } from "./reportUtils";

function pick(completeness: Record<string, any>, ...keys: string[]): any {
  for (const key of keys) {
    if (completeness?.[key] !== undefined && completeness?.[key] !== null) return completeness[key];
  }
  return undefined;
}

export function DataCompletenessBanner({ completeness }: { completeness: Record<string, any> }) {
  const { t } = useTranslation("reports");
  const rawResults = pick(completeness, "raw_results", "raw_result_count", "raw_results_count");
  const analyzedResults = pick(completeness, "analyzed_results", "analyzed_result_count", "analyzed_results_count");
  const sameDay = pick(completeness, "same_day_analyzed_results", "same_day_analyzed_count");
  const pct = pick(completeness, "analyzed_pct", "analysis_complete_pct");

  const items = [
    { label: t("completeness.rawResults"), value: formatNumber(rawResults) },
    { label: t("completeness.analyzedResults"), value: formatNumber(analyzedResults) },
    { label: t("completeness.sameDayAnalyzed"), value: formatNumber(sameDay) },
    { label: t("completeness.analyzedPct"), value: formatPercent(pct) },
  ];

  return (
    <Card className="shadow-none">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("completeness.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((item) => (
            <div key={item.label} className="rounded-md border bg-muted/20 p-3">
              <div className="text-xs text-muted-foreground">{item.label}</div>
              <div className="mt-1 text-xl font-semibold">{item.value}</div>
            </div>
          ))}
        </div>
        {Number.isFinite(Number(pct)) && (
          <div className="mt-4">
            <Progress value={Math.max(0, Math.min(100, Number(pct)))} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
