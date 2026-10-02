import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { CalendarDays, FileText, Loader2, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useSaaS } from "@/contexts/SaaSContext";
import {
  getStaticReportStatusForDate,
  getTodayStaticReportStatusForWindow,
  listStaticReports,
  materializeStaticReportForDate,
  materializeTodayStaticReport,
  type StaticReportMeta,
  type TodayReportStatusOut,
} from "@/lib/api";
import { ReportStatusBadge } from "./components/ReportStatusBadge";
import { formatDate, formatDateTime } from "./components/reportUtils";

function readinessLabel(t: any, reason: string): string {
  const key = `readiness.${reason}`;
  const translated = t(key);
  return translated === key ? reason : translated;
}

type ReportDay = "today" | "yesterday";
type WindowDays = 1 | 7 | 14 | 30;
const WINDOW_OPTIONS: WindowDays[] = [1, 7, 14, 30];

function shanghaiDateString(offsetDays = 0): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const base = new Date(Number(values.year), Number(values.month) - 1, Number(values.day));
  base.setDate(base.getDate() + offsetDays);
  const year = base.getFullYear();
  const month = String(base.getMonth() + 1).padStart(2, "0");
  const day = String(base.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function ReportsListPage() {
  const { t } = useTranslation("reports");
  const navigate = useNavigate();
  const { clientId, activeClientName, loadingClients } = useSaaS();
  const [reports, setReports] = useState<StaticReportMeta[]>([]);
  const [today, setToday] = useState<TodayReportStatusOut | null>(null);
  const [yesterday, setYesterday] = useState<TodayReportStatusOut | null>(null);
  const [selectedDay, setSelectedDay] = useState<ReportDay>("today");
  const [windowDays, setWindowDays] = useState<WindowDays>(7);
  const [loading, setLoading] = useState(true);
  const [actioning, setActioning] = useState<ReportDay | null>(null);
  const [error, setError] = useState<string | null>(null);

  const yesterdayDate = useMemo(() => shanghaiDateString(-1), []);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const [history, todayStatus, yesterdayStatus] = await Promise.all([
        listStaticReports(clientId),
        getTodayStaticReportStatusForWindow(clientId, windowDays),
        getStaticReportStatusForDate(clientId, yesterdayDate, windowDays),
      ]);
      setReports(history.data || []);
      setToday(todayStatus);
      setYesterday(yesterdayStatus);
    } catch (err: any) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  }, [clientId, yesterdayDate, windowDays]);

  useEffect(() => {
    if (!loadingClients && clientId) void load();
  }, [clientId, load, loadingClients]);

  const selectedStatus = selectedDay === "today" ? today : yesterday;
  const selectedReport = useMemo(
    () => reports.find((report) => report.id === selectedStatus?.report_id)
      || reports.find((report) => report.report_date === selectedStatus?.report_date && Number(report.window_days || 7) === windowDays),
    [reports, selectedStatus, windowDays],
  );

  async function handleReportAction(day: ReportDay) {
    const status = day === "today" ? today : yesterday;
    if (!clientId || !status) return;
    if (status.status === "COMPLETED" && status.report_id) {
      navigate(`/reports/static/${status.report_id}`);
      return;
    }

    setActioning(day);
    try {
      const result = day === "today"
        ? await materializeTodayStaticReport(clientId, windowDays)
        : await materializeStaticReportForDate(clientId, status.report_date, windowDays);
      if (result.status === "COMPLETED" && result.report_id) {
        navigate(`/reports/static/${result.report_id}`);
        return;
      }
      if (result.status === "NOT_READY") {
        toast.warning(result.reasons.map((reason) => readinessLabel(t, reason)).join(" "));
      } else if (result.status === "MATERIALIZING") {
        toast.message(readinessLabel(t, "materialization_in_progress"));
      } else if (result.status === "PENDING" && result.reasons.includes("materialization_capacity_busy")) {
        toast.message(readinessLabel(t, "materialization_capacity_busy"));
      }
      await load();
    } catch (err: any) {
      toast.error(err?.message || String(err));
    } finally {
      setActioning(null);
    }
  }

  const actionLabel = selectedStatus?.status === "COMPLETED"
    ? t("list.view")
    : selectedStatus?.status === "FAILED"
      ? t("list.retrySnapshot")
      : t("list.generateAndView");
  const actionDisabled = loading || !selectedStatus || selectedStatus.status === "NOT_READY" || selectedStatus.status === "MATERIALIZING" || Boolean(actioning);
  const showYesterdayFallback = selectedDay === "today" && today?.status === "NOT_READY" && yesterday?.status !== "MATERIALIZING";
  const initialLoading = loadingClients || (loading && reports.length === 0 && !today && !yesterday);
  const refreshing = loading && !initialLoading;

  if (initialLoading) {
    return (
      <div className="flex h-full items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">{t("list.loading")}</span>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t("list.title")}</h1>
          <p className="mt-2 text-muted-foreground">{t("list.subtitle")}</p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCcw className="mr-2 h-4 w-4" />
          {t("list.refresh")}
        </Button>
      </div>

      {error && (
        <Card className="border-destructive/30 bg-destructive/5 shadow-none">
          <CardContent className="p-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      <Card className="shadow-none">
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarDays className="h-4 w-4 text-primary" />
              {t("list.snapshotTitle")}
              {refreshing && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
            </CardTitle>
            <div className="flex flex-wrap gap-2">
              <div className="flex rounded-md border p-1">
                {(["today", "yesterday"] as const).map((day) => (
                  <button
                    key={day}
                    type="button"
                    onClick={() => setSelectedDay(day)}
                    className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                      selectedDay === day
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                  >
                    {t(`list.day.${day}`)}
                  </button>
                ))}
              </div>
              <div className="flex rounded-md border p-1">
                {WINDOW_OPTIONS.map((days) => (
                  <button
                    key={days}
                    type="button"
                    onClick={() => setWindowDays(days)}
                    className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                      windowDays === days
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                  >
                    {t("list.windowOption", { count: days })}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className={`flex flex-col gap-5 transition-opacity lg:flex-row lg:items-center lg:justify-between ${refreshing ? "opacity-60" : ""}`}>
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-lg font-semibold">{activeClientName}</span>
              {selectedStatus && <ReportStatusBadge status={selectedStatus.status} />}
            </div>
            <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
              <span>{selectedStatus?.report_date ? formatDate(selectedStatus.report_date) : "-"}</span>
              <span>{t("list.windowOption", { count: selectedStatus?.window_days || windowDays })}</span>
              {selectedReport?.materialized_at && (
                <span>
                  {t("list.lastGenerated")}: {formatDateTime(selectedReport.materialized_at)}
                </span>
              )}
            </div>
            {selectedStatus?.reasons?.length ? (
              <div className="space-y-1 text-sm text-amber-600 dark:text-amber-400">
                {selectedStatus.reasons.map((reason) => (
                  <div key={reason}>{readinessLabel(t, reason)}</div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
            {showYesterdayFallback && (
              <Button
                variant="outline"
                onClick={() => handleReportAction("yesterday")}
                disabled={loading || !yesterday || yesterday.status === "NOT_READY" || Boolean(actioning)}
                className="w-full lg:w-auto"
              >
                {actioning === "yesterday" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileText className="mr-2 h-4 w-4" />}
                {t("list.useYesterday")}
              </Button>
            )}
            <Button onClick={() => handleReportAction(selectedDay)} disabled={actionDisabled} className="w-full lg:w-auto">
              {actioning === selectedDay || selectedStatus?.status === "MATERIALIZING" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileText className="mr-2 h-4 w-4" />}
              {selectedStatus?.status === "NOT_READY" ? t("list.waitingForData") : actionLabel}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {t("list.historyTitle")}
            {refreshing && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          </CardTitle>
        </CardHeader>
        <CardContent className={`transition-opacity ${refreshing ? "opacity-60" : ""}`}>
          {reports.length === 0 ? (
            <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
              {t("list.emptyHistory")}
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("fields.date")}</TableHead>
                    <TableHead>{t("fields.status")}</TableHead>
                    <TableHead>{t("list.dataWindow")}</TableHead>
                    <TableHead>{t("fields.window")}</TableHead>
                    <TableHead>{t("list.lastGenerated")}</TableHead>
                    <TableHead className="text-right">{t("fields.action")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reports.map((report) => (
                    <TableRow key={report.id}>
                      <TableCell className="font-medium">{formatDate(report.report_date)}</TableCell>
                      <TableCell><ReportStatusBadge status={report.status} /></TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(report.data_window_start)} - {formatDate(report.data_window_end)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{t("list.windowOption", { count: report.window_days || 7 })}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(report.materialized_at)}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={report.status !== "COMPLETED"}
                          onClick={() => navigate(`/reports/static/${report.id}`)}
                        >
                          {t("list.open")}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
