import { useState, useEffect } from 'react';
import type { components } from '../api/openapi';
import { useToast } from '../components/Toast';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getAgentTasks, toggleAgentTaskSchedule } from '../api/client';

type AgentTaskListRow = components["schemas"]["AgentTaskListRow"];
type AgentTaskListOut = components["schemas"]["AgentTaskListOut"];

interface WorkflowStep {
    status?: string;
    label?: string;
}

interface AgentTaskListParams {
    page: string;
    limit: string;
    task_type: string;
    status?: string;
    [key: string]: string | undefined;
}

interface AgentTasksPageProps {
    taskType?: "analysis" | "content_generation";
    title?: string;
    description?: string;
}

const AGENT_API: string = (import.meta.env.VITE_AGENT_API_URL || '') + '/api/agent';

const STATUS_COLORS: Record<string, string> = {
    'DRAFT': 'bg-gray-500/10 text-gray-400 border-gray-500/20',
    'RUNNING': 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    'COMPLETED': 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    'FAILED': 'bg-red-500/10 text-red-400 border-red-500/20',
};

const DOMAIN_META: Record<string, { label: string; color: string }> = {
    visibility: { label: 'Visibility', color: 'bg-blue-500/10 text-blue-400' },
    citation:   { label: 'Citation',   color: 'bg-indigo-500/10 text-indigo-400' },
    sentiment:  { label: 'Sentiment',  color: 'bg-emerald-500/10 text-emerald-400' },
};

/**
 * Reusable admin task list page.
 */
export default function AgentTasksPage({ taskType = 'analysis', title, description }: AgentTasksPageProps) {
    const toast = useToast();

    const [tasks, setTasks] = useState<AgentTaskListRow[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [page, setPage] = useState<number>(1);
    const [totalPages, setTotalPages] = useState<number>(1);
    const [statusFilter, setStatusFilter] = useState<string>('');

    const pageTitle = title || (taskType === 'analysis' ? 'GEO Analysis Tasks' : 'GEO Content Tasks');
    const pageDesc = description || (taskType === 'analysis'
        ? 'Global management for analysis tasks created by SaaS users.'
        : 'Global management for content generation tasks created by SaaS users.');

    useEffect(() => {
        loadTasks();
    }, [page, statusFilter, taskType]);

    async function loadTasks(): Promise<void> {
        setLoading(true);
        try {
            const params: AgentTaskListParams = { page: String(page), limit: "30", task_type: taskType };
            if (statusFilter) params.status = statusFilter;
            const resp = (await getAgentTasks(params)) as AgentTaskListOut;
            setTasks(resp?.data || []);
            setTotalPages(resp?.pagination?.pages || 1);
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setLoading(false);
        }
    }

    async function handleToggleSchedule(task: AgentTaskListRow): Promise<void> {
        try {
            const newState = !task.schedule_enabled;
            await toggleAgentTaskSchedule(task.id, newState);
            toast.success(`Schedule ${newState ? 'Enabled' : 'Disabled'} for ${task.task_name}`);
            loadTasks();
        } catch (err) {
            toast.error((err as Error).message);
        }
    }

    // Parse workflow_steps to show a brief progress summary
    function getProgressSummary(task: AgentTaskListRow): string | null {
        const steps = task.workflow_steps as WorkflowStep[] | null | undefined;
        if (!steps || !Array.isArray(steps) || steps.length === 0) return null;
        const done = steps.filter((s) => s.status === 'done').length;
        const running = steps.find((s) => s.status === 'running');
        if (running) return `${done}/${steps.length} — ${running.label}`;
        if (done === steps.length) return `${done}/${steps.length} ✓`;
        return `${done}/${steps.length}`;
    }

    return (
        <div className="space-y-6">
            <div className="flex items-end justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-foreground">{pageTitle}</h1>
                    <p className="text-muted-foreground mt-1">{pageDesc}</p>
                </div>
            </div>

            {/* Filters */}
            <div className="flex items-center gap-4 bg-card border rounded-xl p-4 shadow-sm">
                <div>
                    <label className="text-xs font-semibold text-muted-foreground uppercase block mb-1">Filter by Status</label>
                    <Select value={statusFilter || "__all__"} onValueChange={(v: string) => { setStatusFilter(v === "__all__" ? "" : v); setPage(1); }}>
                        <SelectTrigger className="w-[180px] h-9">
                            <SelectValue placeholder="All Statuses" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">All Statuses</SelectItem>
                            <SelectItem value="DRAFT">Saved (Draft)</SelectItem>
                            <SelectItem value="RUNNING">Running</SelectItem>
                            <SelectItem value="COMPLETED">Completed</SelectItem>
                            <SelectItem value="FAILED">Failed</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>

            {/* List */}
            {loading && tasks.length === 0 ? (
                <div className="flex justify-center py-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
            ) : tasks.length === 0 ? (
                <div className="bg-card border border-dashed rounded-xl py-12 text-center text-muted-foreground">
                    No {taskType === 'analysis' ? 'analysis' : 'content'} tasks found.
                </div>
            ) : (
                <div className="bg-card border rounded-xl overflow-hidden shadow-sm">
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                            <thead className="text-xs text-muted-foreground uppercase bg-muted/50 border-b">
                                <tr>
                                    <th className="px-5 py-3 font-medium">Task Name</th>
                                    <th className="px-5 py-3 font-medium">Customer</th>
                                    <th className="px-5 py-3 font-medium">Status</th>
                                    <th className="px-5 py-3 font-medium">Progress</th>
                                    <th className="px-5 py-3 font-medium">Cron Schedule</th>
                                    <th className="px-5 py-3 font-medium">Created / Updated</th>
                                    <th className="px-5 py-3 font-medium text-center">Report</th>
                                    <th className="px-5 py-3 font-medium text-right">Scheduler Action</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {tasks.map((t) => (
                                    <tr key={t.id} className="hover:bg-muted/20 transition-colors">
                                        <td className="px-5 py-4 align-top">
                                            <div className="font-medium text-foreground mb-1">{t.task_name || '(Unnamed)'}</div>
                                            <div className="flex gap-1.5 flex-wrap">
                                                {((t.domains as string[] | null | undefined) || []).map((d: string) => {
                                                    const meta = DOMAIN_META[d] || { label: d, color: 'border-border' };
                                                    return (
                                                        <span key={d} className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${meta.color}`}>
                                                            {meta.label}
                                                        </span>
                                                    );
                                                })}
                                            </div>
                                        </td>
                                        <td className="px-5 py-4 align-top text-muted-foreground font-medium">
                                            {t.customer_name || 'Unassigned'}
                                        </td>
                                        <td className="px-5 py-4 align-top">
                                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold border uppercase tracking-wider ${(t.status && STATUS_COLORS[t.status]) || STATUS_COLORS['FAILED']}`}>
                                                {t.status === 'DRAFT' ? 'SAVED' : t.status}
                                            </span>
                                        </td>
                                        <td className="px-5 py-4 align-top text-xs text-muted-foreground">
                                            {getProgressSummary(t) || '—'}
                                        </td>
                                        <td className="px-5 py-4 align-top font-mono text-xs">
                                            {t.cron_expression ? (
                                                <div className="flex flex-col gap-1">
                                                    <span>⏱ {t.cron_expression}</span>
                                                    <span className="text-muted-foreground opacity-80">{t.cron_timezone || 'Asia/Shanghai'}</span>
                                                </div>
                                            ) : (
                                                <span className="text-muted-foreground">—</span>
                                            )}
                                        </td>
                                        <td className="px-5 py-4 align-top text-xs text-muted-foreground whitespace-nowrap">
                                            <div>{t.created_at ? new Date(t.created_at).toLocaleString() : '—'}</div>
                                            {t.completed_at && (
                                                <div className="mt-1 flex items-center gap-1">
                                                    <span className="text-[10px] opacity-70">✔</span>
                                                    {new Date(t.completed_at).toLocaleString()}
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-5 py-4 align-top text-center">
                                            {t.status === 'COMPLETED' ? (
                                                <button
                                                    onClick={() => window.open(`${AGENT_API}/tasks/${t.id}/export?client_id=${t.client_id}&view=true`, '_blank')}
                                                    className="px-3 py-1.5 text-xs font-semibold rounded-md border transition-colors bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20"
                                                >
                                                    View Report
                                                </button>
                                            ) : (
                                                <button
                                                    disabled
                                                    className="px-3 py-1.5 text-xs font-semibold rounded-md border bg-muted/50 text-muted-foreground/50 border-border cursor-not-allowed"
                                                >
                                                    View Report
                                                </button>
                                            )}
                                        </td>
                                        <td className="px-5 py-4 align-top text-right">
                                            {t.cron_expression ? (
                                                <button
                                                    onClick={() => handleToggleSchedule(t)}
                                                    className={`px-3 py-1.5 text-xs font-semibold rounded-md border transition-colors ${
                                                        t.schedule_enabled
                                                            ? 'bg-red-500/10 text-red-400 border-red-500/30 hover:bg-red-500/20'
                                                            : 'bg-green-500/10 text-green-400 border-green-500/30 hover:bg-green-500/20'
                                                    }`}
                                                >
                                                    {t.schedule_enabled ? 'Disable Schedule' : 'Enable Schedule'}
                                                </button>
                                            ) : (
                                                <button
                                                    disabled
                                                    title="No Cron Expression Pattern Configured"
                                                    className="px-3 py-1.5 text-xs font-semibold rounded-md border bg-muted/50 text-muted-foreground/50 border-border cursor-not-allowed"
                                                >
                                                    Enable Schedule
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between pt-4">
                    <button
                        onClick={() => setPage((p: number) => Math.max(1, p - 1))}
                        disabled={page === 1}
                        className="px-4 py-2 text-sm font-medium border rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
                    >
                        Previous
                    </button>
                    <span className="text-sm font-medium text-muted-foreground">
                        Page {page} of {totalPages}
                    </span>
                    <button
                        onClick={() => setPage((p: number) => Math.min(totalPages, p + 1))}
                        disabled={page === totalPages}
                        className="px-4 py-2 text-sm font-medium border rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
                    >
                        Next
                    </button>
                </div>
            )}
        </div>
    );
}
