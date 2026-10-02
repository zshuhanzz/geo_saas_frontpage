import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useSaaS } from "@/contexts/SaaSContext";
import { useAuth } from "@/contexts/AuthContext";
import { API_BASE, fetchJSON, listAgentTasks, getAgentTask, deleteAgentTask, runAgentTask, listAgentTaskTemplates, renameAgentTask, getAvailability, type AvailabilityFlags } from "@/lib/api";
import TemplateConfigModal from "@/components/insights/TemplateConfigModal";
import OpportunityAnalysisModal from "@/components/insights/OpportunityAnalysisModal";
import type { PaginationMeta, Template, RunRecord } from "./AgentAnalysis.parts/types";
import { ALL_DOMAINS } from "./AgentAnalysis.parts/utils";
import { TemplateGallery } from "./AgentAnalysis.parts/TemplateGallery";
import { TaskList } from "./AgentAnalysis.parts/TaskList";
import { RunDetailModal } from "./AgentAnalysis.parts/RunDetailModal";
import { RenameDialog } from "./AgentAnalysis.parts/RenameDialog";

export default function AgentAnalysis() {
    const { t } = useTranslation("agents");
    const { clientId, can } = useSaaS();
    const canExecute = can("actions.analysis", "execute");
    const { user } = useAuth();
    const userId = user?.sub ? `google:${user.sub}` : "";
    const [activeTab, setActiveTab] = useState<"new" | "all">("new");

    // Template list
    const [templates, setTemplates] = useState<Template[]>([]);
    const [loadingTemplates, setLoadingTemplates] = useState(true);
    const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
    const [modelIds, setModelIds] = useState<string[]>(["gemini-3.1-pro-preview"]);
    const [opportunityModalOpen, setOpportunityModalOpen] = useState(false);
    const [availability, setAvailability] = useState<AvailabilityFlags | null>(null);

    // All Tasks tab
    const [runs, setRuns] = useState<RunRecord[]>([]);
    const [loadingRuns, setLoadingRuns] = useState(false);
    const [runsPage, setRunsPage] = useState(1);
    const [runsPagination, setRunsPagination] = useState<PaginationMeta | null>(null);
    const [selectedRun, setSelectedRun] = useState<RunRecord | null>(null);
    const [renameDialogOpen, setRenameDialogOpen] = useState(false);
    const [renameTarget, setRenameTarget] = useState<RunRecord | null>(null);
    const [renameValue, setRenameValue] = useState("");

    useEffect(() => {
        if (!canExecute) setActiveTab("all");
    }, [canExecute]);

    useEffect(() => {
        if (!clientId) return;
        setLoadingTemplates(true);
        listAgentTaskTemplates("analysis", clientId)
            .then(data => setTemplates(data || []))
            .catch(() => setTemplates([]))
            .finally(() => setLoadingTemplates(false));

        // Also fetch allowed model IDs
        fetchJSON(`${API_BASE}/settings/config?key=report_model_id_list`)
            .then(d => {
                if (d?.value) {
                    setModelIds(d.value.split(",").map((m: string) => m.trim()).filter(Boolean));
                }
            })
            .catch(() => { });

        // Load availability flags for data-driven template visibility gating
        // (e.g. hide "渠道表现分析" from non-OEM clients).
        getAvailability(clientId)
            .then(setAvailability)
            .catch(() => setAvailability(null));
    }, [clientId]);

    const initialLoadDone = useRef(false);
    const RUNS_PAGE_SIZE = 20;

    function fetchRuns(showSpinner = false, page = runsPage) {
        if (!clientId) return Promise.resolve();
        if (showSpinner) setLoadingRuns(true);
        return listAgentTasks(clientId, undefined, {
            page,
            pageSize: RUNS_PAGE_SIZE,
            taskTypes: ["analysis", "opportunity_discovery"],
        })
            .then(d => {
                const tasks = (d?.data || []).filter((t: any) =>
                    !t.task_type || t.task_type === "analysis" || t.task_type === "opportunity_discovery"
                ).map((t: any) => {
                    const inputs = typeof t.inputs === "string" ? JSON.parse(t.inputs) : (t.inputs || {});
                    return { ...t, domains: inputs.domains || [] };
                });
                setRuns(tasks);
                setRunsPagination(d?.pagination || null);
            })
            .catch(() => {
                setRuns([]);
                setRunsPagination(null);
            })
            .finally(() => setLoadingRuns(false));
    }

    useEffect(() => {
        if (activeTab === "all") {
            const needSpinner = !initialLoadDone.current;
            fetchRuns(needSpinner, runsPage);
            initialLoadDone.current = true;
        }
    }, [clientId, activeTab, runsPage]);

    useEffect(() => {
        initialLoadDone.current = false;
        setRunsPage(1);
    }, [clientId]);

    // Background list refresh every 10s while on All Tasks tab — only if any task is RUNNING
    const hasRunningTask = runs.some(r => r.status === "RUNNING");
    useEffect(() => {
        if (activeTab !== "all" || !hasRunningTask) return;
        const timer = setInterval(() => fetchRuns(false), 10000);
        return () => clearInterval(timer);
    }, [activeTab, clientId, hasRunningTask]);

    function openTemplate(t: Template) {
        // For templates with empty data_domains, expose all 3 domains
        const enriched = t.data_domains.length === 0
            ? { ...t, data_domains: ALL_DOMAINS }
            : t;
        // For custom (blank-style) template, start with empty prompt if no default
        setSelectedTemplate(enriched);
    }

    async function openRunDetail(run: RunRecord) {
        try {
            const detail = await getAgentTask(run.id, clientId);
            if (detail?.output) {
                detail.report_output = typeof detail.output === "string" ? JSON.parse(detail.output) : detail.output;
            }
            const inputs = typeof detail?.inputs === "string" ? JSON.parse(detail.inputs) : (detail?.inputs || {});
            detail.domains = inputs.domains || [];
            setSelectedRun(detail || run);
        } catch {
            setSelectedRun(run);
        }
    }

    async function deleteRun(runId: string) {
        try {
            await deleteAgentTask(runId, clientId);
            if (runs.length === 1 && runsPage > 1) {
                setRunsPage(prev => Math.max(1, prev - 1));
            } else {
                fetchRuns(false, runsPage);
            }
        } catch {
            fetchRuns();
        }
    }

    function handleRenameRun(run: RunRecord) {
        setRenameTarget(run);
        setRenameValue(run.task_name);
        setRenameDialogOpen(true);
    }

    async function submitRename() {
        if (!renameTarget || !renameValue.trim() || renameValue === renameTarget.task_name) return;
        try {
            await renameAgentTask(renameTarget.id, clientId, renameValue.trim());
            setRuns(prev => prev.map(r => r.id === renameTarget.id ? { ...r, task_name: renameValue.trim() } : r));
        } catch { /* silent */ }
        setRenameDialogOpen(false);
    }

    async function rerunFromRun(run: RunRecord) {
        // DRAFT tasks: execute directly without opening the editor
        if (run.status === "DRAFT" && clientId) {
            try {
                await runAgentTask(run.id, clientId, userId);
                fetchRuns();
            } catch { /* silent */ }
            return;
        }

        // Non-DRAFT (FAILED/COMPLETED): also execute directly for re-run
        if (clientId) {
            try {
                await runAgentTask(run.id, clientId, userId);
                fetchRuns();
            } catch { /* silent */ }
        }
    }

    function editRunInTemplate(run: RunRecord) {
        // Open template editor with the run's inputs for editing
        const inputs = typeof run.inputs === "string" ? JSON.parse(run.inputs) : (run.inputs || {});

        const t: Template = {
            id: run.template_id || "",
            run_id: run.id,
            name: run.task_name.replace(" (Saved Task)", "").replace(" (Cron Scheduled)", ""),
            description: "Run Task",
            icon: "🔄",
            data_domains: inputs.domains || [],
            default_prompt: inputs.prompt || "",
            is_builtin: false,
            is_active: true,
            sort_order: 0,
            cron_expression: inputs.cron_expression || "",
            chart_requests: inputs.chart_requests || [],
            filters: { dateFrom: inputs.date_from, dateTo: inputs.date_to },
        };

        setSelectedRun(null);
        setActiveTab("new");
        openTemplate(t);
    }

    return (
        <div className="h-full flex flex-col">
            {/* Page header */}
            <div className="shrink-0 px-6">
                <h1 className="text-2xl font-bold tracking-tight pt-2 pb-4">{t("analysis.pageTitle")}</h1>
                <div className="flex border-b">
                    {(canExecute ? (["new", "all"] as const) : (["all"] as const)).map(tab => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={cn(
                                "pb-3 px-1 mr-8 text-sm font-medium border-b-2 transition-colors",
                                activeTab === tab
                                    ? "border-primary text-foreground"
                                    : "border-transparent text-muted-foreground hover:text-foreground"
                            )}
                        >
                            {tab === "new" ? t("analysis.tabNew") : t("analysis.tabAll")}
                        </button>
                    ))}
                </div>
            </div>

            {activeTab === "new" ? (
                <TemplateGallery
                    templates={templates}
                    loadingTemplates={loadingTemplates}
                    availability={availability}
                    onPickTemplate={openTemplate}
                    onOpenOpportunity={() => setOpportunityModalOpen(true)}
                />
            ) : (
                /* All Tasks tab */
                <TaskList
                    runs={runs}
                    loadingRuns={loadingRuns}
                    onOpenDetail={openRunDetail}
                    onRename={handleRenameRun}
                    onEdit={editRunInTemplate}
                    onRerun={rerunFromRun}
                    onDelete={deleteRun}
                    onCreateNew={() => setActiveTab("new")}
                    pagination={runsPagination}
                    loadingPage={loadingRuns}
                    onPageChange={setRunsPage}
                    readOnly={!canExecute}
                />
            )}

            {/* Template config modal */}
            <TemplateConfigModal
                open={!!selectedTemplate}
                template={selectedTemplate}
                clientId={clientId}
                userId={userId}
                modelIds={modelIds}
                onClose={() => setSelectedTemplate(null)}
                onTaskCreated={fetchRuns}
            />

            {/* Opportunity analysis modal */}
            <OpportunityAnalysisModal
                open={opportunityModalOpen}
                clientId={clientId}
                userId={userId}
                onClose={() => setOpportunityModalOpen(false)}
                onTaskCreated={() => {
                    setOpportunityModalOpen(false);
                    setActiveTab("all");
                    fetchRuns(true);
                }}
            />

            {/* Run Detail Modal */}
            <RunDetailModal
                run={selectedRun}
                clientId={clientId}
                onClose={() => setSelectedRun(null)}
                onRerun={rerunFromRun}
                onEdit={editRunInTemplate}
                onDelete={deleteRun}
                readOnly={!canExecute}
            />

            {/* Rename Dialog */}
            {canExecute && <RenameDialog
                open={renameDialogOpen}
                target={renameTarget}
                value={renameValue}
                onOpenChange={setRenameDialogOpen}
                onValueChange={setRenameValue}
                onSubmit={submitRename}
            />}
        </div>
    );
}
