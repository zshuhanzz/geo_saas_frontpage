import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, FileText, Loader2, MoreHorizontal, RefreshCcw, RotateCcw, Search, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { deleteStaticReport, getClients, getStaticReport, getStaticReports, regenerateStaticReport } from "@/api/client";
import type { StaticReportDetail, StaticReportListRow } from "@/api/client";
import { useConfirm, useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

type ClientOption = { id: string; name?: string | null };

const STATUS_OPTIONS = ["COMPLETED", "NOT_READY", "FAILED", "MATERIALIZING", "PENDING"];
const SAAS_WEB_URL = ((import.meta.env.VITE_SAAS_WEB_URL as string | undefined) || "http://localhost:6174").replace(/\/$/, "");

const STATUS_CLASS: Record<string, string> = {
    COMPLETED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500",
    NOT_READY: "border-amber-500/30 bg-amber-500/10 text-amber-500",
    FAILED: "border-red-500/30 bg-red-500/10 text-red-500",
    MATERIALIZING: "border-blue-500/30 bg-blue-500/10 text-blue-500",
    PENDING: "border-slate-500/30 bg-slate-500/10 text-slate-400",
};

function formatDate(value?: string | null): string {
    if (!value) return "-";
    const d = new Date(value.includes("T") ? value : `${value}T00:00:00`);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleDateString();
}

function formatDateTime(value?: string | null): string {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
}

function numberValue(value: unknown): string {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString() : "-";
}

function snapshotSectionCount(snapshot: Record<string, unknown> | null | undefined, section: string): number {
    const value = snapshot?.[section];
    if (!value || typeof value !== "object" || Array.isArray(value)) return 0;
    return Object.values(value as Record<string, unknown>).reduce<number>((total, item) => {
        if (Array.isArray(item)) return total + item.length;
        return total;
    }, 0);
}

function StatusBadge({ status }: { status: string }) {
    return (
        <Badge variant="outline" className={cn("whitespace-nowrap", STATUS_CLASS[status] || STATUS_CLASS.PENDING)}>
            {status}
        </Badge>
    );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-md border bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="mt-1 text-lg font-semibold">{value}</div>
        </div>
    );
}

export default function StaticReportsPage() {
    const toast = useToast();
    const confirm = useConfirm();
    const [reports, setReports] = useState<StaticReportListRow[]>([]);
    const [clients, setClients] = useState<ClientOption[]>([]);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [loading, setLoading] = useState(true);
    const [detailLoading, setDetailLoading] = useState(false);
    const [selectedReport, setSelectedReport] = useState<StaticReportDetail | null>(null);
    const [clientId, setClientId] = useState("");
    const [status, setStatus] = useState("");
    const [dateFrom, setDateFrom] = useState("");
    const [dateTo, setDateTo] = useState("");

    const selectedClientName = useMemo(
        () => clients.find((client) => client.id === clientId)?.name || "",
        [clientId, clients],
    );

    useEffect(() => {
        void loadClients();
    }, []);

    useEffect(() => {
        void loadReports();
    }, [page, clientId, status, dateFrom, dateTo]);

    async function loadClients(): Promise<void> {
        try {
            const data = await getClients();
            setClients(data.map((client) => ({ id: client.id, name: client.name })));
        } catch (err) {
            toast.error((err as Error).message);
        }
    }

    async function loadReports(): Promise<void> {
        setLoading(true);
        try {
            const response = await getStaticReports({
                page,
                limit: 30,
                client_id: clientId,
                status,
                date_from: dateFrom,
                date_to: dateTo,
            });
            setReports(response.data || []);
            setTotalPages(response.pagination?.pages || 1);
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setLoading(false);
        }
    }

    async function openDetail(reportId: string): Promise<void> {
        setDetailLoading(true);
        try {
            setSelectedReport(await getStaticReport(reportId));
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setDetailLoading(false);
        }
    }

    async function deleteReport(report: Pick<StaticReportListRow, "id" | "client_name" | "report_date">): Promise<void> {
        const ok = await confirm(
            `Delete the static report for ${report.client_name || "this client"} on ${formatDate(report.report_date)}? This only removes the saved snapshot and does not delete dashboard data.`,
            "Delete Static Report",
        );
        if (!ok) return;
        try {
            const result = await deleteStaticReport(report.id);
            toast.success(result.message);
            if (selectedReport?.id === report.id) setSelectedReport(null);
            await loadReports();
        } catch (err) {
            toast.error((err as Error).message);
        }
    }

    async function regenerateReport(report: Pick<StaticReportListRow, "id" | "client_name" | "report_date">): Promise<void> {
        const ok = await confirm(
            `Reset the static report for ${report.client_name || "this client"} on ${formatDate(report.report_date)}? The report will be removed so it can be generated again from the SaaS report entry.`,
            "Regenerate Static Report",
        );
        if (!ok) return;
        try {
            const result = await regenerateStaticReport(report.id);
            toast.success(result.message);
            if (selectedReport?.id === report.id) setSelectedReport(null);
            await loadReports();
        } catch (err) {
            toast.error((err as Error).message);
        }
    }

    function resetFilters(): void {
        setClientId("");
        setStatus("");
        setDateFrom("");
        setDateTo("");
        setPage(1);
    }

    const detail = selectedReport;
    const completeness = detail?.data_completeness || {};
    const snapshot = detail?.snapshot_json || null;

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-foreground">Static Reports</h1>
                    <p className="mt-1 text-muted-foreground">
                        Cross-client management and troubleshooting for static report snapshots.
                    </p>
                </div>
                <Button variant="outline" onClick={() => loadReports()}>
                    <RefreshCcw className="mr-2 h-4 w-4" />
                    Refresh
                </Button>
            </div>

            <Card className="shadow-sm">
                <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                        <Search className="h-4 w-4 text-primary" />
                        Filters
                    </CardTitle>
                </CardHeader>
                <CardContent className="grid gap-3 md:grid-cols-5">
                    <Select value={clientId || "__all__"} onValueChange={(value) => { setClientId(value === "__all__" ? "" : value); setPage(1); }}>
                        <SelectTrigger>
                            <SelectValue placeholder="All clients" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">All clients</SelectItem>
                            {clients.map((client) => (
                                <SelectItem key={client.id} value={client.id}>
                                    {client.name || client.id}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Select value={status || "__all__"} onValueChange={(value) => { setStatus(value === "__all__" ? "" : value); setPage(1); }}>
                        <SelectTrigger>
                            <SelectValue placeholder="All statuses" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">All statuses</SelectItem>
                            {STATUS_OPTIONS.map((option) => (
                                <SelectItem key={option} value={option}>
                                    {option}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setPage(1); }} />
                    <Input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setPage(1); }} />
                    <Button variant="ghost" onClick={resetFilters}>Reset</Button>
                </CardContent>
            </Card>

            <Card className="overflow-hidden shadow-sm">
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead className="border-b bg-muted/50 text-xs uppercase text-muted-foreground">
                            <tr>
                                <th className="px-5 py-3 font-medium">Customer</th>
                                <th className="px-5 py-3 font-medium">Report Date</th>
                                <th className="px-5 py-3 font-medium">Status</th>
                                <th className="px-5 py-3 font-medium">Data Window</th>
                                <th className="px-5 py-3 font-medium">Window</th>
                                <th className="px-5 py-3 font-medium">Mode</th>
                                <th className="px-5 py-3 font-medium">Generated</th>
                                <th className="px-5 py-3 font-medium">Error</th>
                                <th className="px-5 py-3 text-right font-medium">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {loading && reports.length === 0 ? (
                                <tr>
                                    <td colSpan={9} className="px-5 py-12 text-center text-muted-foreground">
                                        <Loader2 className="mx-auto mb-2 h-6 w-6 animate-spin" />
                                        Loading reports...
                                    </td>
                                </tr>
                            ) : reports.length === 0 ? (
                                <tr>
                                    <td colSpan={9} className="px-5 py-12 text-center text-muted-foreground">
                                        No static reports found.
                                    </td>
                                </tr>
                            ) : (
                                reports.map((report) => (
                                    <tr key={report.id} className="transition-colors hover:bg-muted/20">
                                        <td className="px-5 py-4 align-top">
                                            <div className="font-medium">{report.client_name || selectedClientName || "Unassigned"}</div>
                                            <div className="mt-1 max-w-[160px] truncate font-mono text-[11px] text-muted-foreground">
                                                {report.client_id}
                                            </div>
                                        </td>
                                        <td className="px-5 py-4 align-top font-medium">{formatDate(report.report_date)}</td>
                                        <td className="px-5 py-4 align-top"><StatusBadge status={report.status} /></td>
                                        <td className="px-5 py-4 align-top text-muted-foreground">
                                            {formatDate(report.data_window_start)} - {formatDate(report.data_window_end)}
                                        </td>
                                        <td className="px-5 py-4 align-top text-muted-foreground">{report.window_days || 7} days</td>
                                        <td className="px-5 py-4 align-top">
                                            <Badge variant="secondary">{report.rendering_mode}</Badge>
                                        </td>
                                        <td className="px-5 py-4 align-top text-muted-foreground">{formatDateTime(report.materialized_at)}</td>
                                        <td className="max-w-[220px] px-5 py-4 align-top text-muted-foreground">
                                            <span className="line-clamp-2">{report.error_message || "-"}</span>
                                        </td>
                                        <td className="px-5 py-4 align-top text-right">
                                            <ReportActions
                                                report={report}
                                                detailLoading={detailLoading}
                                                onOpenDetail={() => openDetail(report.id)}
                                                onDelete={() => deleteReport(report)}
                                                onRegenerate={() => regenerateReport(report)}
                                            />
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </Card>

            {totalPages > 1 && (
                <div className="flex items-center justify-between">
                    <Button variant="outline" disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                        Previous
                    </Button>
                    <span className="text-sm text-muted-foreground">Page {page} of {totalPages}</span>
                    <Button variant="outline" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
                        Next
                    </Button>
                </div>
            )}

            <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setSelectedReport(null)}>
                <DialogContent className="max-h-[86vh] max-w-4xl overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>Static Report Detail</DialogTitle>
                        <DialogDescription>
                            {detail?.client_name || "Client"} · {detail ? formatDate(detail.report_date) : ""}
                        </DialogDescription>
                    </DialogHeader>
                    {detail && (
                        <div className="space-y-5">
                            <div className="grid gap-3 md:grid-cols-4">
                                <DetailMetric label="Raw results" value={numberValue(completeness.raw_results)} />
                                <DetailMetric label="Analyzed results" value={numberValue(completeness.analyzed_results)} />
                                <DetailMetric label="Same-day analyzed" value={numberValue(completeness.same_day_analyzed_results)} />
                                <DetailMetric label="Analyzed %" value={numberValue(completeness.analyzed_pct)} />
                            </div>

                            <div className="grid gap-3 md:grid-cols-5">
                                {["visibility", "citations", "sentiment", "prompts", "topics"].map((section) => (
                                    <DetailMetric
                                        key={section}
                                        label={section}
                                        value={numberValue(snapshotSectionCount(snapshot, section))}
                                    />
                                ))}
                            </div>

                            <div className="rounded-md border p-4">
                                <div className="mb-2 text-sm font-semibold">Warnings</div>
                                {detail.warnings.length === 0 ? (
                                    <div className="text-sm text-muted-foreground">No warnings.</div>
                                ) : (
                                    <pre className="max-h-40 overflow-auto rounded bg-muted/40 p-3 text-xs">
                                        {JSON.stringify(detail.warnings, null, 2)}
                                    </pre>
                                )}
                            </div>

                            <div className="rounded-md border p-4">
                                <div className="mb-2 text-sm font-semibold">Metadata</div>
                                <div className="grid gap-2 text-sm md:grid-cols-2">
                                    <div>Report ID: <span className="font-mono text-xs">{detail.id}</span></div>
                                    <div>Client ID: <span className="font-mono text-xs">{detail.client_id}</span></div>
                                    <div>Status: {detail.status}</div>
                                    <div>Snapshot version: {detail.snapshot_version}</div>
                                    <div>Timezone: {detail.timezone}</div>
                                    <div>Rendering mode: {detail.rendering_mode}</div>
                                    <div>Window: {detail.window_days || 7} days</div>
                                    <div>Created: {formatDateTime(detail.created_at)}</div>
                                    <div>Updated: {formatDateTime(detail.updated_at)}</div>
                                </div>
                            </div>

                            <div className="rounded-md border p-4">
                                <div className="mb-3 text-sm font-semibold">Admin actions</div>
                                <div className="flex flex-wrap gap-2">
                                    {detail.status === "COMPLETED" && (
                                        <Button asChild variant="outline" size="sm">
                                            <a href={`${SAAS_WEB_URL}/share/reports/${detail.id}`} target="_blank" rel="noreferrer">
                                                <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                                                Presentation
                                            </a>
                                        </Button>
                                    )}
                                    <Button variant="outline" size="sm" onClick={() => regenerateReport(detail)}>
                                        <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                                        Regenerate
                                    </Button>
                                    <Button variant="destructive" size="sm" onClick={() => deleteReport(detail)}>
                                        <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                                        Delete
                                    </Button>
                                </div>
                                <p className="mt-2 text-xs text-muted-foreground">
                                    Regenerate resets the saved snapshot only. It does not trigger Collector or Analyzer.
                                </p>
                            </div>
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}

function ReportActions({
    report,
    detailLoading,
    onOpenDetail,
    onDelete,
    onRegenerate,
}: {
    report: StaticReportListRow;
    detailLoading: boolean;
    onOpenDetail: () => void;
    onDelete: () => void;
    onRegenerate: () => void;
}) {
    const [open, setOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement | null>(null);
    const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);
    const closeAndRun = (action: () => void) => {
        setOpen(false);
        action();
    };
    const toggleMenu = () => {
        if (open) {
            setOpen(false);
            return;
        }
        const rect = triggerRef.current?.getBoundingClientRect();
        if (rect) {
            setMenuPosition({
                top: rect.bottom + 8,
                right: Math.max(12, window.innerWidth - rect.right),
            });
        }
        setOpen(true);
    };

    return (
        <div className="flex justify-end gap-2">
            {report.status === "COMPLETED" && (
                <Button asChild variant="outline" size="sm">
                    <a href={`${SAAS_WEB_URL}/share/reports/${report.id}`} target="_blank" rel="noreferrer">
                        <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                        Presentation
                    </a>
                </Button>
            )}
            <div className="relative">
                <Button
                    ref={triggerRef}
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 px-0"
                    onClick={toggleMenu}
                    aria-label="More report actions"
                >
                    <MoreHorizontal className="h-4 w-4" />
                </Button>
                {open && (
                    <>
                        <button
                            type="button"
                            aria-label="Close report actions"
                            className="fixed inset-0 z-20 cursor-default"
                            onClick={() => setOpen(false)}
                        />
                        <div
                            className="fixed z-50 w-48 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-lg"
                            style={{
                                top: menuPosition?.top ?? 0,
                                right: menuPosition?.right ?? 12,
                            }}
                        >
                            <button
                                type="button"
                                className="flex w-full items-center rounded-sm px-3 py-2 text-left text-sm hover:bg-muted"
                                onClick={() => closeAndRun(onOpenDetail)}
                                disabled={detailLoading}
                            >
                                <FileText className="mr-2 h-3.5 w-3.5" />
                                Detail
                            </button>
                            <button
                                type="button"
                                className="flex w-full items-center rounded-sm px-3 py-2 text-left text-sm hover:bg-muted"
                                onClick={() => closeAndRun(onRegenerate)}
                            >
                                <RotateCcw className="mr-2 h-3.5 w-3.5" />
                                Regenerate
                            </button>
                            <button
                                type="button"
                                className="flex w-full items-center rounded-sm px-3 py-2 text-left text-sm text-destructive hover:bg-destructive/10"
                                onClick={() => closeAndRun(onDelete)}
                            >
                                <Trash2 className="mr-2 h-3.5 w-3.5" />
                                Delete
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
