import { useState, useEffect } from "react";
import type { CSSProperties } from "react";
import type { components } from "../api/openapi";
import { getTasks, getClients, getResults } from "../api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ListTodoIcon, Search, Loader2, Eye, ArrowUpDown, ArrowUp, ArrowDown, Copy, Check } from "lucide-react";

type ClientOut = components["schemas"]["ClientOut"];
type TaskRow = components["schemas"]["TaskRow"];
type TaskListOut = components["schemas"]["TaskListOut"];
type TaskPagination = components["schemas"]["TaskPagination"];
type ResultRow = components["schemas"]["ResultRow"];
type ResultListOut = components["schemas"]["ResultListOut"];

type BadgeVariant = "default" | "secondary" | "outline" | "destructive";
type SortDir = "asc" | "desc";

interface TaskListParams {
    page: number;
    limit: number;
    status?: string;
    batch_id?: string;
    sort_by?: string;
    sort_dir?: SortDir;
    [key: string]: unknown;
}

interface ColumnDef {
    key: string;
    label: string;
    width: string;
    frozen?: "left" | "right";
    align?: "center" | "left" | "right";
    render?: (v: unknown) => React.ReactNode;
}

const STATUS_VARIANTS: Record<string, BadgeVariant> = {
    COMPLETED: "default",
    completed: "default",
    dispatched: "secondary",
    DISPATCHED: "secondary",
    pending: "outline",
    PENDING: "outline",
    failed: "destructive",
    FAILED: "destructive",
};

interface SortableHeaderProps {
    label: string;
    field: string;
    sortField: string;
    sortDir: SortDir;
    onSort: (field: string) => void;
    className?: string;
}

function SortableHeader({ label, field, sortField, sortDir, onSort, className = "" }: SortableHeaderProps) {
    const isActive = sortField === field;
    return (
        <TableHead
            className={`cursor-pointer select-none hover:bg-muted/50 transition-colors whitespace-nowrap ${className}`}
            onClick={() => onSort(field)}
        >
            <div className="flex items-center gap-1">
                <span>{label}</span>
                {isActive ? (
                    sortDir === "asc" ? <ArrowUp className="h-3.5 w-3.5 text-primary" /> : <ArrowDown className="h-3.5 w-3.5 text-primary" />
                ) : (
                    <ArrowUpDown className="h-3 w-3 text-muted-foreground/40" />
                )}
            </div>
        </TableHead>
    );
}

interface CopyableCellProps {
    text: string | null | undefined;
    maxWidth?: string;
    mono?: boolean;
}

function CopyableCell({ text, maxWidth = "200px", mono = true }: CopyableCellProps) {
    const [copied, setCopied] = useState<boolean>(false);
    if (!text) return <span className="text-muted-foreground/50">—</span>;

    const handleCopy = (e: React.MouseEvent<HTMLButtonElement>): void => {
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };

    return (
        <div className="group flex items-center gap-1" style={{ maxWidth }}>
            <span className={`truncate ${mono ? "font-mono text-[11px]" : "text-sm"}`} title={text}>
                {text}
            </span>
            <button
                onClick={handleCopy}
                className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                title="Copy"
            >
                {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3 text-muted-foreground" />}
            </button>
        </div>
    );
}

// Column definitions — order determines display order
const COLUMNS: ColumnDef[] = [
    { key: "task_id", label: "Task ID", width: "180px", frozen: "left", render: (v) => <CopyableCell text={v as string | null | undefined} maxWidth="170px" /> },
    { key: "status", label: "Status", width: "110px", render: (v) => <Badge variant={STATUS_VARIANTS[String(v ?? "")] || "outline"} className="text-[10px] font-medium uppercase tracking-wider">{(v as string | null | undefined) || "PENDING"}</Badge> },
    { key: "platform", label: "Platform", width: "110px", render: (v) => v ? <Badge variant="secondary" className="text-[10px] font-normal">{v as string}</Badge> : "—" },
    { key: "country", label: "Country", width: "90px" },
    { key: "language", label: "Lang", width: "70px" },
    { key: "topic", label: "Topic", width: "150px" },
    { key: "product", label: "Product", width: "120px" },
    { key: "client_prompt_text", label: "Client Prompt", width: "250px", render: (v) => <span className="text-xs truncate block max-w-[240px]" title={(v as string) || ""}>{(v as string) || "—"}</span> },
    { key: "final_prompt", label: "Final Prompt", width: "300px", render: (v) => <span className="text-xs truncate block max-w-[290px]" title={(v as string) || ""}>{(v as string) || "—"}</span> },
    { key: "calls_per_prompt", label: "Calls", width: "70px", align: "center" },
    { key: "dispatched_count", label: "Dispatched", width: "100px", align: "center" },
    { key: "completed_count", label: "Completed", width: "100px", align: "center" },
    { key: "batch_id", label: "Batch ID", width: "200px", render: (v) => <CopyableCell text={v as string | null | undefined} maxWidth="190px" /> },
    { key: "client_prompt_id", label: "Prompt ID", width: "180px", render: (v) => <CopyableCell text={v as string | null | undefined} maxWidth="170px" /> },
    { key: "created_at", label: "Created", width: "170px", render: (v) => v ? <span className="text-xs text-muted-foreground whitespace-nowrap">{new Date(v as string).toLocaleString()}</span> : "—" },
    { key: "updated_at", label: "Updated", width: "170px", render: (v) => v ? <span className="text-xs text-muted-foreground whitespace-nowrap">{new Date(v as string).toLocaleString()}</span> : "—" },
];

export default function TasksPage() {
    const [clients, setClients] = useState<ClientOut[]>([]);
    const [selectedClientId, setSelectedClientId] = useState<string>("");
    const [tasks, setTasks] = useState<TaskRow[]>([]);
    const [pagination, setPagination] = useState<TaskPagination>({ page: 1, limit: 50, total: 0, pages: 1 });
    const [loading, setLoading] = useState<boolean>(false);
    const [statusFilter, setStatusFilter] = useState<string>("");
    const [batchIdFilter, setBatchIdFilter] = useState<string>("");

    // Sorting — server-side
    const [sortField, setSortField] = useState<string>("");
    const [sortDir, setSortDir] = useState<SortDir>("desc");

    // Result detail
    const [selectedTask, setSelectedTask] = useState<TaskRow | null>(null);
    const [results, setResults] = useState<ResultRow[]>([]);
    const [loadingResults, setLoadingResults] = useState<boolean>(false);
    const [showResults, setShowResults] = useState<boolean>(false);

    useEffect(() => {
        getClients()
            .then((res) => setClients((res as ClientOut[]) || []))
            .catch(console.error);
    }, []);

    useEffect(() => {
        if (selectedClientId) loadTasks(1);
    }, [selectedClientId, statusFilter]);

    async function loadTasks(page: number = 1): Promise<void> {
        if (!selectedClientId) return;
        setLoading(true);
        try {
            const params: TaskListParams = {
                page,
                limit: 50,
                status: statusFilter || undefined,
                batch_id: batchIdFilter || undefined,
                sort_by: sortField || undefined,
                sort_dir: sortField ? sortDir : undefined,
            };
            const data = (await getTasks(selectedClientId, params)) as TaskListOut;
            setTasks(data.data || []);
            setPagination(data.pagination || { page: 1, limit: 50, total: 0, pages: 1 });
        } catch (err) {
            console.error("Failed to load tasks:", err);
        } finally {
            setLoading(false);
        }
    }

    function handleSort(field: string): void {
        let newDir: SortDir = "desc";
        if (sortField === field) {
            newDir = sortDir === "asc" ? "desc" : "asc";
        }
        setSortField(field);
        setSortDir(newDir);
        // Reload from API with new sort
        if (!selectedClientId) return;
        setLoading(true);
        const params: TaskListParams = {
            page: 1,
            limit: 50,
            status: statusFilter || undefined,
            batch_id: batchIdFilter || undefined,
            sort_by: field,
            sort_dir: newDir,
        };
        getTasks(selectedClientId, params).then((data) => {
            const out = data as TaskListOut;
            setTasks(out.data || []);
            setPagination(out.pagination || { page: 1, limit: 50, total: 0, pages: 1 });
        }).catch((err) => console.error("Failed to load tasks:", err))
            .finally(() => setLoading(false));
    }

    async function viewResults(task: TaskRow): Promise<void> {
        setSelectedTask(task);
        setShowResults(true);
        setLoadingResults(true);
        try {
            const data = (await getResults(task.task_id)) as ResultListOut;
            setResults(data.data || []);
        } catch (err) {
            console.error("Failed to load results:", err);
            setResults([]);
        } finally {
            setLoadingResults(false);
        }
    }

    // Frozen column styles — fully opaque backgrounds
    const frozenLeftStyle: CSSProperties = {
        position: "sticky",
        left: 0,
        zIndex: 10,
        backgroundColor: "hsl(var(--card))",
        borderRight: "2px solid hsl(var(--border))",
    };
    const frozenRightStyle: CSSProperties = {
        position: "sticky",
        right: 0,
        zIndex: 10,
        backgroundColor: "hsl(var(--card))",
        borderLeft: "2px solid hsl(var(--border))",
    };
    const frozenHeaderLeftStyle: CSSProperties = {
        ...frozenLeftStyle,
        zIndex: 20,
        backgroundColor: "hsl(var(--muted))",
    };
    const frozenHeaderRightStyle: CSSProperties = {
        ...frozenRightStyle,
        zIndex: 20,
        backgroundColor: "hsl(var(--muted))",
    };

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight text-foreground">Tasks</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                    Monitor all task executions across clients. View final prompts, dispatch status, and drill into results.
                </p>
            </div>

            {/* Filters */}
            <Card>
                <CardContent className="p-4">
                    <div className="flex flex-wrap gap-4 items-end">
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Client</Label>
                            <Select value={selectedClientId || "__all__"} onValueChange={(v: string) => setSelectedClientId(v === "__all__" ? "" : v)}>
                                <SelectTrigger className="w-[200px] h-9">
                                    <SelectValue placeholder="Select a client..." />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__all__">Select a client...</SelectItem>
                                    {clients.map((c) => (
                                        <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Status</Label>
                            <Select value={statusFilter || "__all__"} onValueChange={(v: string) => setStatusFilter(v === "__all__" ? "" : v)}>
                                <SelectTrigger className="w-[140px] h-9">
                                    <SelectValue placeholder="All" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__all__">All</SelectItem>
                                    <SelectItem value="pending">Pending</SelectItem>
                                    <SelectItem value="dispatched">Dispatched</SelectItem>
                                    <SelectItem value="completed">Completed</SelectItem>
                                    <SelectItem value="failed">Failed</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Batch ID</Label>
                            <Input
                                placeholder="Filter by batch..."
                                className="w-[200px] h-9"
                                value={batchIdFilter}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setBatchIdFilter(e.target.value)}
                            />
                        </div>
                        <Button size="sm" onClick={() => loadTasks(1)} disabled={!selectedClientId}>
                            <Search className="mr-2 h-4 w-4" /> Search
                        </Button>
                        {sortField && (
                            <Button variant="ghost" size="sm" className="text-xs" onClick={() => { setSortField(""); setSortDir("desc"); }}>
                                Clear Sort
                            </Button>
                        )}
                    </div>
                </CardContent>
            </Card>

            {/* Tasks Table */}
            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg font-semibold flex items-center">
                        <ListTodoIcon className="mr-2 h-5 w-5 text-primary" />
                        Tasks {pagination.total > 0 && <Badge variant="secondary" className="ml-2">{pagination.total}</Badge>}
                    </CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                    {loading ? (
                        <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
                    ) : tasks.length === 0 ? (
                        <div className="text-center py-12 text-muted-foreground text-sm">
                            {selectedClientId ? "No tasks found." : "Select a client to view tasks."}
                        </div>
                    ) : (
                        <>
                            <div className="border-t overflow-x-auto" style={{ maxWidth: "100%" }}>
                                <table className="w-max min-w-full text-sm" style={{ borderCollapse: "separate", borderSpacing: 0 }}>
                                    <thead>
                                        <tr className="bg-muted border-b">
                                            {/* Frozen left — Task ID */}
                                            <th
                                                className="cursor-pointer select-none hover:bg-muted/50 transition-colors px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap"
                                                style={{ ...frozenHeaderLeftStyle, minWidth: COLUMNS[0].width }}
                                                onClick={() => handleSort("task_id")}
                                            >
                                                <div className="flex items-center gap-1">
                                                    Task ID
                                                    {sortField === "task_id" ? (
                                                        sortDir === "asc" ? <ArrowUp className="h-3.5 w-3.5 text-primary" /> : <ArrowDown className="h-3.5 w-3.5 text-primary" />
                                                    ) : (
                                                        <ArrowUpDown className="h-3 w-3 text-muted-foreground/40" />
                                                    )}
                                                </div>
                                            </th>

                                            {/* Scrollable columns */}
                                            {COLUMNS.slice(1).map((col) => (
                                                <th
                                                    key={col.key}
                                                    className="cursor-pointer select-none hover:bg-muted/50 transition-colors px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap"
                                                    style={{ minWidth: col.width }}
                                                    onClick={() => handleSort(col.key)}
                                                >
                                                    <div className={`flex items-center gap-1 ${col.align === "center" ? "justify-center" : ""}`}>
                                                        {col.label}
                                                        {sortField === col.key ? (
                                                            sortDir === "asc" ? <ArrowUp className="h-3.5 w-3.5 text-primary" /> : <ArrowDown className="h-3.5 w-3.5 text-primary" />
                                                        ) : (
                                                            <ArrowUpDown className="h-3 w-3 text-muted-foreground/40" />
                                                        )}
                                                    </div>
                                                </th>
                                            ))}

                                            {/* Frozen right — Actions */}
                                            <th
                                                className="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider whitespace-nowrap"
                                                style={{ ...frozenHeaderRightStyle, minWidth: "100px" }}
                                            >
                                                Actions
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {tasks.map((t) => (
                                            <tr key={t.task_id} className="border-b hover:bg-muted/30 transition-colors">
                                                {/* Frozen left — Task ID */}
                                                <td className="px-4 py-3" style={{ ...frozenLeftStyle, minWidth: COLUMNS[0].width }}>
                                                    <CopyableCell text={t.task_id} maxWidth="170px" />
                                                </td>

                                                {/* Scrollable data cells */}
                                                {COLUMNS.slice(1).map((col) => {
                                                    const val = (t as unknown as Record<string, unknown>)[col.key];
                                                    return (
                                                        <td key={col.key} className={`px-4 py-3 ${col.align === "center" ? "text-center" : ""}`} style={{ minWidth: col.width }}>
                                                            {col.render ? col.render(val) : (
                                                                <span className="text-sm text-foreground">{(val as React.ReactNode) ?? <span className="text-muted-foreground/50">—</span>}</span>
                                                            )}
                                                        </td>
                                                    );
                                                })}

                                                {/* Frozen right — Actions */}
                                                <td className="px-4 py-3 text-right" style={{ ...frozenRightStyle, minWidth: "100px" }}>
                                                    <Button variant="ghost" size="sm" onClick={() => viewResults(t)} className="h-7 text-xs">
                                                        <Eye className="h-3.5 w-3.5 mr-1" /> Results
                                                    </Button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* Pagination */}
                            {pagination.pages > 1 && (
                                <div className="flex justify-center items-center gap-2 p-4 border-t">
                                    <Button
                                        variant="outline" size="sm"
                                        onClick={() => loadTasks(pagination.page - 1)}
                                        disabled={pagination.page <= 1}
                                    >← Prev</Button>
                                    {(() => {
                                        const pages = pagination.pages;
                                        const current = pagination.page;
                                        let range: Array<number | "..."> = [];
                                        if (pages <= 7) {
                                            range = Array.from({ length: pages }, (_, i) => i + 1);
                                        } else {
                                            range = [1];
                                            const start = Math.max(2, current - 1);
                                            const end = Math.min(pages - 1, current + 1);
                                            if (start > 2) range.push('...');
                                            for (let i = start; i <= end; i++) range.push(i);
                                            if (end < pages - 1) range.push('...');
                                            range.push(pages);
                                        }
                                        return range.map((p, i) => (
                                            p === '...' ? <span key={'e' + i} className="px-1 text-muted-foreground">…</span> : (
                                                <Button
                                                    key={p}
                                                    variant={p === current ? "default" : "outline"}
                                                    size="sm"
                                                    onClick={() => loadTasks(p as number)}
                                                >{p}</Button>
                                            )
                                        ));
                                    })()}
                                    <Button
                                        variant="outline" size="sm"
                                        onClick={() => loadTasks(pagination.page + 1)}
                                        disabled={pagination.page >= pagination.pages}
                                    >Next →</Button>
                                    <span className="ml-3 text-xs text-muted-foreground">
                                        Page {pagination.page} of {pagination.pages} ({pagination.total} total)
                                    </span>
                                </div>
                            )}
                        </>
                    )}
                </CardContent>
            </Card>

            {/* Results Detail Dialog */}
            <Dialog open={showResults} onOpenChange={setShowResults}>
                <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>Results for Task</DialogTitle>
                        <DialogDescription className="truncate">{selectedTask?.final_prompt}</DialogDescription>
                    </DialogHeader>
                    {loadingResults ? (
                        <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
                    ) : results.length === 0 ? (
                        <div className="text-center py-8 text-muted-foreground text-sm">No results yet for this task.</div>
                    ) : (
                        <div className="border rounded-lg overflow-hidden">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Call #</TableHead>
                                        <TableHead>HTTP Status</TableHead>
                                        <TableHead>Latency (ms)</TableHead>
                                        <TableHead>Text Preview</TableHead>
                                        <TableHead>Ingested</TableHead>
                                        <TableHead>Analyzed</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {results.map((r, i) => (
                                        <TableRow key={r.result_id ?? i}>
                                            <TableCell>{r.call_index ?? i + 1}</TableCell>
                                            <TableCell>
                                                <Badge variant={r.http_status_code === 200 ? 'default' : 'destructive'}>
                                                    {r.http_status_code || "—"}
                                                </Badge>
                                            </TableCell>
                                            <TableCell>{r.latency_ms || "—"}</TableCell>
                                            <TableCell className="max-w-[300px] truncate text-xs" title={r.text || r.text_preview}>
                                                {(r.text || r.text_preview || "—").slice(0, 120)}
                                            </TableCell>
                                            <TableCell className="text-xs text-muted-foreground">
                                                {r.ingested_at ? new Date(r.ingested_at).toLocaleString() : "—"}
                                            </TableCell>
                                            <TableCell className="text-xs">
                                                {r.analyzed_at ? (
                                                    <Badge variant="default" className="text-[10px]">✓</Badge>
                                                ) : (
                                                    <Badge variant="outline" className="text-[10px]">Pending</Badge>
                                                )}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}
