import { useTranslation } from "react-i18next";
import { Loader2, RotateCcw, Trash2, Clock, Eye, Sparkles, Pencil, Type } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { PaginationMeta, RunRecord } from "./types";
import { DOMAIN_META } from "./utils";
import { StatusIcon } from "./StatusIcon";

export function TaskList({
    runs,
    loadingRuns,
    onOpenDetail,
    onRename,
    onEdit,
    onRerun,
    onDelete,
    onCreateNew,
    pagination,
    loadingPage,
    onPageChange,
    readOnly = false,
}: {
    runs: RunRecord[];
    loadingRuns: boolean;
    onOpenDetail: (run: RunRecord) => void;
    onRename: (run: RunRecord) => void;
    onEdit: (run: RunRecord) => void;
    onRerun: (run: RunRecord) => void;
    onDelete: (runId: string) => void;
    onCreateNew: () => void;
    pagination?: PaginationMeta | null;
    loadingPage?: boolean;
    onPageChange?: (page: number) => void;
    readOnly?: boolean;
}) {
    const { t } = useTranslation("agents");
    return (
        <div className="flex-1 overflow-auto p-6">
            {loadingRuns ? (
                <div className="flex items-center justify-center py-20">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
            ) : runs.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-3">
                    <div className="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center">
                        <Clock className="h-7 w-7 text-muted-foreground/50" />
                    </div>
                    <p className="text-sm">{t("analysis.emptyTasks")}</p>
                    {!readOnly && <Button variant="outline" size="sm" className="gap-1.5 rounded-lg" onClick={onCreateNew}>
                        <Sparkles className="h-3.5 w-3.5" />
                        {t("analysis.createFirstTask")}
                    </Button>}
                </div>
            ) : (
                <div className="max-w-3xl mx-auto space-y-3">
                    {runs.map(run => (
                        <Card
                            key={run.id}
                            className="p-4 hover:border-primary/20 hover:shadow-md transition-all duration-200 cursor-pointer group rounded-xl"
                            onClick={() => onOpenDetail(run)}
                        >
                            <div className="flex items-start gap-3">
                                <StatusIcon status={run.status} />
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className="font-medium text-sm text-foreground">{run.task_name}</span>
                                        {run.triggered_by === "cron" && (
                                            <Badge variant="outline" className="text-[10px]">Auto</Badge>
                                        )}
                                    </div>
                                    <div className="flex flex-wrap gap-1 mb-2">
                                        {(run.domains || []).map(d => {
                                            const meta = DOMAIN_META[d];
                                            return meta ? (
                                                <span key={d} className={`text-[10px] px-1.5 py-0.5 rounded-md border font-medium ${meta.color}`}>
                                                    {t(`analysis.domains.${meta.labelKey}`)}
                                                </span>
                                            ) : null;
                                        })}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                        {new Date(run.started_at || run.created_at || "").toLocaleString("en-US")}
                                        {run.completed_at && run.started_at && ` · ${Math.round((new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000)}s elapsed`}
                                    </div>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                    <Badge
                                        variant="outline"
                                        className={cn("text-[11px]",
                                            run.status === "COMPLETED" ? "text-emerald-500 border-emerald-500/30 bg-emerald-500/5" :
                                            run.status === "FAILED" ? "text-destructive border-destructive/30 bg-destructive/5" :
                                            run.status === "RUNNING" ? "text-primary border-primary/30 bg-primary/5" :
                                            ""
                                        )}
                                    >
                                        {run.status === "COMPLETED" ? t("common.statusCompleted") : run.status === "FAILED" ? t("common.statusFailed") : run.status === "DRAFT" ? t("common.statusDraft") : t("common.statusRunning")}
                                    </Badge>
                                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                                        <Button size="icon" variant="ghost" className="h-7 w-7" title={t("analysis.actionTitles.viewDetail")} onClick={() => onOpenDetail(run)}>
                                            <Eye className="h-3.5 w-3.5" />
                                        </Button>
                                        {!readOnly && <Button size="icon" variant="ghost" className="h-7 w-7" title={t("analysis.actionTitles.rename")} onClick={() => onRename(run)}>
                                            <Type className="h-3.5 w-3.5" />
                                        </Button>}
                                        {!readOnly && <Button size="icon" variant="ghost" className="h-7 w-7" title={t("analysis.actionTitles.edit")} onClick={() => onEdit(run)}>
                                            <Pencil className="h-3.5 w-3.5" />
                                        </Button>}
                                        {!readOnly && (run.status === "FAILED" || run.status === "DRAFT" || (
                                            run.status === "RUNNING" && run.started_at &&
                                            Date.now() - new Date(run.started_at).getTime() > 10 * 60 * 1000
                                        )) && (
                                            <Button size="icon" variant="ghost" className="h-7 w-7" title={run.status === "DRAFT" ? t("common.execute") : t("common.rerun")} onClick={() => onRerun(run)}>
                                                <RotateCcw className="h-3.5 w-3.5" />
                                            </Button>
                                        )}
                                        {!readOnly && <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive" title={t("common.delete")} onClick={() => onDelete(run.id)}>
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </Button>}
                                    </div>
                                </div>
                            </div>
                        </Card>
                    ))}
                    {pagination && pagination.total > pagination.page_size && (
                        <div className="flex items-center justify-between rounded-xl border border-border bg-card/60 px-4 py-3 text-xs text-muted-foreground">
                            <span>
                                {t("pagination.summary", {
                                    page: pagination.page,
                                    pages: pagination.pages,
                                    total: pagination.total,
                                })}
                            </span>
                            <div className="flex items-center gap-2">
                                <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-8 rounded-lg"
                                    disabled={pagination.page <= 1 || loadingPage}
                                    onClick={() => onPageChange?.(Math.max(1, pagination.page - 1))}
                                >
                                    {t("pagination.previous")}
                                </Button>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-8 rounded-lg"
                                    disabled={pagination.page >= pagination.pages || loadingPage}
                                    onClick={() => onPageChange?.(pagination.page + 1)}
                                >
                                    {t("pagination.next")}
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
