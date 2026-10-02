import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import type { StaticReportStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_CLASS: Record<StaticReportStatus, string> = {
  COMPLETED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  MATERIALIZING: "border-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-400",
  PENDING: "border-slate-500/30 bg-slate-500/10 text-slate-600 dark:text-slate-300",
  NOT_READY: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  FAILED: "border-destructive/30 bg-destructive/10 text-destructive",
};

export function ReportStatusBadge({ status, className }: { status: StaticReportStatus; className?: string }) {
  const { t } = useTranslation("reports");
  return (
    <Badge variant="outline" className={cn("whitespace-nowrap", STATUS_CLASS[status], className)}>
      {t(`status.${status}`)}
    </Badge>
  );
}
