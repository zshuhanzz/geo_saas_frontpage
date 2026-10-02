import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, CheckCircle, XCircle, RotateCcw, Trash2, Eye, Sparkles, Pencil, FileDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { getAgentTask, getAgentTaskProgress, exportAgentTaskHTML, getReportURL } from "@/lib/api";
import { ChartCard } from "@/components/insights/TemplateConfigModal";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import type { RunRecord } from "./types";
import { DOMAIN_META, formatSql, getStepOutputs, mergeWorkflowSteps } from "./utils";
import { StepOutputDisplay } from "./StepOutputDisplay";
import { OpportunityDiscoveryView } from "./OpportunityDiscoveryView";

// ─── Run Detail Sheet (right-side drawer) ─────────────────────────────────────
export function RunDetailModal({
    run: initialRun,
    clientId,
    onClose,
    onRerun,
    onEdit,
    onDelete,
    readOnly = false,
}: {
    run: RunRecord | null;
    clientId: string;
    onClose: () => void;
    onRerun: (run: RunRecord) => void;
    onEdit: (run: RunRecord) => void;
    onDelete: (runId: string) => void;
    readOnly?: boolean;
}) {
    const { t } = useTranslation("agents");
    // Local mutable copy so we can update it without touching parent state
    const [run, setRun] = useState<RunRecord | null>(initialRun);
    const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Sync when parent passes a new run (e.g. opening a different record)
    useEffect(() => {
        setRun(initialRun);
    }, [initialRun]);

    // Auto-poll when run is RUNNING
    useEffect(() => {
        if (!run || run.status !== "RUNNING") {
            if (pollTimerRef.current !== null) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
            return;
        }

        const runId = run.id;
        const stopPolling = () => {
            if (pollTimerRef.current !== null) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
        };

        const doPoll = async () => {
            try {
                const data = await getAgentTaskProgress(runId, clientId);
                if (!data) return;
                setRun(prev => {
                    if (!prev) return prev;
                    return {
                        ...prev,
                        status: data.status,
                        status_logs: data.status_logs || prev.status_logs,
                        workflow_steps: data.workflow_steps || prev.workflow_steps,
                        error_message: data.error_message || prev.error_message,
                        completed_at: data.completed_at || prev.completed_at,
                    };
                });
                if (data.status === "COMPLETED" || data.status === "FAILED") {
                    stopPolling();
                    // Fetch full detail (progress endpoint omits output)
                    if (data.status === "COMPLETED") {
                        try {
                            const detail = await getAgentTask(runId, clientId);
                            let reportOut = detail?.output;
                            if (typeof reportOut === "string") {
                                try { reportOut = JSON.parse(reportOut); } catch { reportOut = null; }
                            }
                            // Update ALL fields from full detail, not just report_output
                            setRun(prev => {
                                if (!prev) return prev;
                                return {
                                    ...prev,
                                    report_output: reportOut || prev.report_output,
                                    workflow_steps: detail?.workflow_steps || prev.workflow_steps,
                                    status_logs: detail?.status_logs || prev.status_logs,
                                    status: detail?.status || prev.status,
                                    completed_at: detail?.completed_at || prev.completed_at,
                                };
                            });
                        } catch { /* silent */ }
                    }
                }
            } catch {
                // Network error — retry next tick
            }
        };

        doPoll();
        pollTimerRef.current = setInterval(doPoll, 8000);

        return () => stopPolling();
    }, [run?.id, run?.status, clientId]);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (pollTimerRef.current !== null) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
        };
    }, []);

    if (!run) return null;

    const report = run.report_output;
    let statusLogs: Array<{ label?: string; event?: string; step?: number; sqls?: Record<string, string>; prompt?: string }> = [];
    if (typeof run.status_logs === "string") {
        try { statusLogs = JSON.parse(run.status_logs); } catch { statusLogs = []; }
    } else if (Array.isArray(run.status_logs)) {
        statusLogs = run.status_logs;
    }
    const progressLabels = statusLogs.map(l => l.label || "").filter(Boolean);

    // Extract SQL logs for display (Step 2: metrics, Step 3: charts)
    const sqlEntry = statusLogs.find(l => l.event === "sql_generated" && l.sqls && (l as any).step === 2);
    const sqlLogs: Record<string, string> = sqlEntry?.sqls || {};
    const chartSqlEntry = statusLogs.find(l => l.event === "sql_generated" && l.sqls && (l as any).step === 3);
    const chartSqlLogs: Record<string, string> = chartSqlEntry?.sqls || {};
    const hydratedPromptEntry = statusLogs.find(l => (l as any).event === "hydrated_prompt" && (l as any).step === 4);
    const hydratedPrompt: string = (hydratedPromptEntry as any)?.prompt || "";
    const isRunning = run.status === "RUNNING";

    // Merge DB workflow steps with canonical (handles old 3-step tasks)
    const rawSteps = typeof run.workflow_steps === "string"
        ? JSON.parse(run.workflow_steps)
        : run.workflow_steps;
    const workflowSteps = mergeWorkflowSteps(rawSteps, run.task_type);

    // Extract per-step outputs from status_logs
    const stepOutputs = getStepOutputs(run.status_logs);

    return (
        <Sheet open={!!run} onOpenChange={o => { if (!o) onClose(); }}>
            <SheetContent side="right" className="sm:max-w-[75vw] w-[75vw] p-0 flex flex-col overflow-hidden [&>button:first-child]:hidden">
                <SheetTitle className="sr-only">Run Details: {run.task_name}</SheetTitle>
                <SheetDescription className="hidden">Details for {run.task_name}</SheetDescription>
                {/* Header */}
                <div className="flex items-center gap-3 px-6 pt-5 pb-4 border-b shrink-0">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center shrink-0">
                        <img src="/Anthony_Chat_Online.png" alt="Anthony" className="w-7 h-7 object-contain" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-sm">{run.task_name}</span>
                            <Badge
                                variant="outline"
                                className={cn("text-[11px]",
                                    run.status === "COMPLETED"
                                        ? "text-emerald-500 border-emerald-500/30 bg-emerald-500/5"
                                        : run.status === "FAILED"
                                            ? "text-destructive border-destructive/30 bg-destructive/5"
                                            : run.status === "RUNNING"
                                                ? "text-primary border-primary/30 bg-primary/5"
                                                : "text-muted-foreground border-border"
                                )}
                            >
                                {run.status === "COMPLETED" ? t("common.statusCompleted") : run.status === "FAILED" ? t("common.statusFailed") : run.status === "DRAFT" ? t("common.statusDraft") : t("common.statusRunning")}
                                {isRunning && <Loader2 className="h-3 w-3 ml-1 animate-spin" />}
                            </Badge>
                            {run.triggered_by === "cron" && <Badge variant="outline" className="text-[10px]">{t("common.triggerAuto")}</Badge>}
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5">
                            {new Date(run.started_at).toLocaleString("en-US")}
                            {run.completed_at &&
                                ` · ${Math.round(
                                    (new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000
                                )}s elapsed`}
                        </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        {!readOnly && <Button
                            size="sm"
                            variant="outline"
                            onClick={() => onEdit(run)}
                            className="gap-1.5 h-8 rounded-lg"
                            disabled={isRunning}
                        >
                            <Pencil className="h-3.5 w-3.5" />
                            {t("common.edit")}
                        </Button>}
                        {!readOnly && (run.status === "DRAFT" || run.status === "FAILED" || (
                            isRunning && run.started_at &&
                            Date.now() - new Date(run.started_at).getTime() > 10 * 60 * 1000
                        )) && (
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => onRerun(run)}
                                className="gap-1.5 h-8 rounded-lg"
                            >
                                <RotateCcw className="h-3.5 w-3.5" />
                                {run.status === "DRAFT" ? t("common.execute") : t("common.rerun")}
                            </Button>
                        )}
                        {!readOnly && <Button
                            size="sm"
                            variant="outline"
                            className="gap-1.5 h-8 rounded-lg text-destructive border-destructive/30 hover:bg-destructive/5"
                            onClick={() => { onDelete(run.id); onClose(); }}
                            disabled={isRunning}
                        >
                            <Trash2 className="h-3.5 w-3.5" />
                        </Button>}
                    </div>
                </div>

                {/* Domains */}
                {(run.domains || []).length > 0 && (
                    <div className="flex gap-1.5 px-6 py-2.5 border-b border-border/50 shrink-0 flex-wrap">
                        {(run.domains || []).map(d => {
                            const meta = DOMAIN_META[d];
                            return meta ? (
                                <Badge key={d} variant="outline" className={`text-[11px] ${meta.color}`}>
                                    {t(`analysis.domains.${meta.labelKey}`)}
                                </Badge>
                            ) : null;
                        })}
                    </div>
                )}

                {/* Content */}
                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

                    {/* Workflow Steps Progress */}
                    {(isRunning || workflowSteps.length > 0 || progressLabels.length > 0) && (
                        <div className="rounded-xl border bg-primary/[0.02] p-5 space-y-2.5">
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                                <Sparkles className="h-3.5 w-3.5 text-primary" />
                                {t("common.anthonyProgress")}
                                {isRunning && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
                            </div>
                            {workflowSteps.length > 0 ? (
                                workflowSteps.map((s, i) => {
                                    const showMetricSql = s.name === "hydrate_metrics" && s.status === "done" && Object.keys(sqlLogs).length > 0;
                                    const showChartSql = s.name === "generate_charts" && s.status === "done" && Object.keys(chartSqlLogs).length > 0;
                                    const showHydratedPrompt = s.name === "synthesize_report" && s.status === "done" && hydratedPrompt;
                                    // Hide generic expandable for steps that have specific expandable or render content below
                                    const suppressExpand = s.name === "generate_charts" || s.name === "synthesize_report";
                                    const hasStepOutput = s.status === "done" && stepOutputs[s.step] && !showMetricSql && !showChartSql && !showHydratedPrompt && !suppressExpand;
                                    return (
                                        <div key={i} className="ml-1">
                                            <div className="flex items-start gap-2.5 text-xs">
                                                <div className="mt-0.5">
                                                    {s.status === "done" ? (
                                                        <CheckCircle className="h-4 w-4 text-emerald-500 flex-shrink-0" />
                                                    ) : s.status === "running" ? (
                                                        <Loader2 className="h-4 w-4 animate-spin text-primary flex-shrink-0" />
                                                    ) : s.status === "failed" ? (
                                                        <XCircle className="h-4 w-4 text-destructive flex-shrink-0" />
                                                    ) : (
                                                        <div className="h-4 w-4 rounded-full border border-border flex-shrink-0" />
                                                    )}
                                                </div>
                                                <div className="flex-1 min-w-0">
                                                    <span className={cn(
                                                        s.status === "done" ? "text-foreground/80" :
                                                        s.status === "running" ? "text-primary font-medium" :
                                                        s.status === "failed" ? "text-destructive" :
                                                        "text-muted-foreground"
                                                    )}>
                                                        {t("common.stepLabel", {
                                                            step: s.step,
                                                            label: t(`analysis.steps.${s.name}`, { defaultValue: s.label }),
                                                        })}
                                                    </span>
                                                    {showMetricSql && (
                                                        <details className="mt-1.5">
                                                            <summary className="cursor-pointer text-primary/70 hover:text-primary text-[11px] select-none">
                                                                {t("analysis.viewSql", { count: Object.keys(sqlLogs).length })}
                                                            </summary>
                                                            <div className="mt-1 space-y-1.5 max-h-48 overflow-y-auto">
                                                                {Object.entries(sqlLogs).map(([name, sql]) => (
                                                                    <div key={name} className="rounded border bg-background/50 p-2">
                                                                        <div className="font-mono text-[10px] text-primary/80 mb-0.5">{name}</div>
                                                                        <pre className="font-mono text-[10px] text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">{formatSql(String(sql))}</pre>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        </details>
                                                    )}
                                                    {showChartSql && (
                                                        <details className="mt-1.5">
                                                            <summary className="cursor-pointer text-primary/70 hover:text-primary text-[11px] select-none">
                                                                {t("analysis.viewChartSql", { count: Object.keys(chartSqlLogs).length })}
                                                            </summary>
                                                            <div className="mt-1 space-y-1.5 max-h-48 overflow-y-auto">
                                                                {Object.entries(chartSqlLogs).map(([name, sql]) => (
                                                                    <div key={name} className="rounded border bg-background/50 p-2">
                                                                        <div className="font-mono text-[10px] text-primary/80 mb-0.5">{name}</div>
                                                                        <pre className="font-mono text-[10px] text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">{formatSql(String(sql))}</pre>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        </details>
                                                    )}
                                                    {showHydratedPrompt && (
                                                        <details className="mt-1.5">
                                                            <summary className="cursor-pointer text-primary/70 hover:text-primary text-[11px] select-none">
                                                                {t("analysis.viewFinalPrompt")}
                                                            </summary>
                                                            <div className="mt-1 rounded border bg-background/50 p-2 max-h-60 overflow-y-auto">
                                                                <pre className="font-mono text-[10px] text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">{hydratedPrompt}</pre>
                                                            </div>
                                                        </details>
                                                    )}
                                                    {hasStepOutput && (
                                                        <details className="mt-1.5">
                                                            <summary className="cursor-pointer text-primary/70 hover:text-primary text-[11px] select-none">
                                                                {t("common.viewOutput")}
                                                            </summary>
                                                            <StepOutputDisplay data={stepOutputs[s.step]} />
                                                        </details>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })
                            ) : progressLabels.length > 0 ? (
                                progressLabels.map((label, i) => {
                                    const isSqlEntry = (label.includes("已生成") || label.includes("Generated")) && label.includes("SQL") && Object.keys(sqlLogs).length > 0;
                                    return (
                                        <div key={i} className="flex items-start gap-2.5 text-xs text-muted-foreground ml-1">
                                            {i < progressLabels.length - 1 || !isRunning
                                                ? <CheckCircle className="h-4 w-4 text-emerald-500 flex-shrink-0 mt-0.5" />
                                                : <Loader2 className="h-4 w-4 animate-spin text-primary flex-shrink-0 mt-0.5" />
                                            }
                                            <div className="flex-1 min-w-0">
                                                <span className="text-foreground/80">{label}</span>
                                                {isSqlEntry && (
                                                    <details className="mt-1.5">
                                                        <summary className="cursor-pointer text-primary/70 hover:text-primary text-[11px] select-none">
                                                            {t("analysis.viewSql", { count: Object.keys(sqlLogs).length })}
                                                        </summary>
                                                        <div className="mt-1 space-y-1.5 max-h-48 overflow-y-auto">
                                                            {Object.entries(sqlLogs).map(([name, sql]) => (
                                                                <div key={name} className="rounded border bg-background/50 p-2">
                                                                    <div className="font-mono text-[10px] text-primary/80 mb-0.5">{name}</div>
                                                                    <pre className="font-mono text-[10px] text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">{formatSql(String(sql))}</pre>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </details>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })
                            ) : (
                                <div className="flex items-center gap-2.5 text-xs text-muted-foreground ml-1">
                                    <Loader2 className="h-4 w-4 animate-spin text-primary flex-shrink-0" />
                                    <span>{t("common.loadingTaskProgress")}</span>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Error */}
                    {run.status === "FAILED" && run.error_message && (
                        <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4">
                            <div className="text-sm font-medium text-destructive mb-1">{t("common.executionFailed")}</div>
                            <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-words">
                                {run.error_message}
                            </pre>
                        </div>
                    )}

                    {/* Prompt used */}
                    {(run.inputs?.prompt) && (
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t("analysis.usedPrompt")}</div>
                            <pre className="text-xs bg-slate-50 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-700/50 rounded-xl p-4 whitespace-pre-wrap break-words max-h-40 overflow-y-auto font-mono text-slate-700 dark:text-slate-300 leading-relaxed">
                                {typeof run.inputs === "string" ? JSON.parse(run.inputs).prompt : run.inputs.prompt}
                            </pre>
                        </div>
                    )}

                    {/* Quality Review */}
                    {report?.quality_score && (
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">{t("analysis.qualityReport")}</div>
                            <div className="rounded-xl border bg-card p-5 space-y-4">
                                {/* Score grid */}
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                                    {[
                                        { key: "data_accuracy_score", labelKey: "data_accuracy_score" as const },
                                        { key: "consistency_score", labelKey: "consistency_score" as const },
                                        { key: "completeness_score", labelKey: "completeness_score" as const },
                                        { key: "overall_score", labelKey: "overall_score" as const },
                                    ].map(({ key, labelKey }) => {
                                        const score = (report.quality_score as any)?.[key];
                                        if (score == null) return null;
                                        const color = score >= 4 ? "text-emerald-500" : score >= 3 ? "text-yellow-500" : "text-destructive";
                                        return (
                                            <div key={key} className="rounded-lg border bg-muted/30 p-3 text-center">
                                                <div className="text-[10px] text-muted-foreground mb-1">{t(`analysis.qualityData.${labelKey}`)}</div>
                                                <div className={`text-xl font-bold ${color}`}>{score}<span className="text-xs font-normal text-muted-foreground">/5</span></div>
                                            </div>
                                        );
                                    })}
                                </div>
                                {/* Summary */}
                                {report.quality_score.summary && (
                                    <p className="text-xs text-muted-foreground">{report.quality_score.summary}</p>
                                )}
                                {/* Issues */}
                                {report.quality_score.issues && report.quality_score.issues.length > 0 && (
                                    <div>
                                        <div className="text-[11px] font-medium text-muted-foreground mb-1.5">{t("analysis.qualityIssuesFound")}</div>
                                        <ul className="space-y-1">
                                            {report.quality_score.issues.map((issue: string, idx: number) => (
                                                <li key={idx} className="text-xs text-muted-foreground flex items-start gap-1.5">
                                                    <span className="text-yellow-500 mt-0.5 shrink-0">!</span>
                                                    <span>{issue}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Charts */}
                    {report && report.charts && report.charts.length > 0 && (
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Data Charts ({report.charts.length})</div>
                            <div className="space-y-3">
                                {report.charts.map((chart: any, i: number) => (
                                    <ChartCard key={i} chart={chart} />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Opportunity Discovery: Structured Output */}
                    <OpportunityDiscoveryView run={run} />

                    {/* Insights */}
                    {report?.insights_markdown && (
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">{t("analysis.insightReport")}</div>
                            <div className="rounded-xl border bg-card p-6 prose prose-sm dark:prose-invert max-w-none prose-headings:font-semibold prose-a:text-primary prose-table:w-full prose-table:border prose-th:bg-muted/50 prose-th:p-2 prose-td:p-2 prose-td:border-t prose-pre:bg-slate-50 prose-pre:dark:bg-slate-900/80 prose-pre:border prose-pre:border-slate-200 prose-pre:dark:border-slate-700/50 prose-pre:rounded-xl">
                                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{report.insights_markdown}</ReactMarkdown>
                            </div>
                        </div>
                    )}

                    {!run.error_message && !report?.insights_markdown && !isRunning && (
                        <div className="text-center text-sm text-muted-foreground py-10">{t("common.noReportContent")}</div>
                    )}

                    {/* CTA: Jump to Content from opportunity analysis */}
                    {!readOnly && (run.task_type === "opportunity_discovery" || run.inputs?.analysis_goal === "opportunity") && run.status === "COMPLETED" && (
                        <div className="mt-6 p-4 border border-amber-500/20 rounded-lg bg-amber-500/5">
                            <p className="text-sm text-amber-300 mb-3">
                                {t("analysis.continueToContent")}
                            </p>
                            <Button
                                onClick={() => {
                                    window.location.href = `/agents/content?analyzer_task_id=${run.id}`;
                                }}
                                className="bg-amber-600 hover:bg-amber-700 text-white"
                            >
                                <Sparkles className="w-4 h-4 mr-2" />
                                {t("analysis.startContentGen")}
                            </Button>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="shrink-0 flex items-center justify-between px-6 pb-5 pt-3 border-t">
                    <div>
                        {run && run.status === "COMPLETED" && (
                            <div className="flex items-center gap-2">
                                <Button
                                    size="sm"
                                    variant="outline"
                                    className="rounded-lg gap-1.5 text-primary border-primary/30 hover:bg-primary/5"
                                    onClick={() => window.open(getReportURL(run.id, clientId), "_blank")}
                                >
                                    <Eye className="h-3.5 w-3.5" />
                                    {t("common.viewFullReport")}
                                </Button>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    className="rounded-lg gap-1.5 text-primary border-primary/30 hover:bg-primary/5"
                                    onClick={() => exportAgentTaskHTML(run.id, clientId)}
                                >
                                    <FileDown className="h-3.5 w-3.5" />
                                    {t("common.exportHtml")}
                                </Button>
                            </div>
                        )}
                    </div>
                    <Button size="sm" variant="outline" onClick={onClose} className="rounded-lg">{t("common.close")}</Button>
                </div>
            </SheetContent>
        </Sheet>
    );
}
