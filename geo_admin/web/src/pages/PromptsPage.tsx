import { useEffect, useState, useMemo, Fragment } from "react";
import type { components } from "../api/openapi";
import {
    getBatchIds,
    getClients,
    getPromptConcepts,
    getPromptTasksByPromptIds,
    type PromptConceptOut,
    type PromptConceptListOut,
} from "../api/client";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
    ChevronRight,
    ChevronDown,
    Network,
    Loader2,
    Sparkles,
    Search,
    FileDown,
} from "lucide-react";

type ClientOut = components["schemas"]["ClientOut"];
type TaskRow = components["schemas"]["TaskRow"];
type TaskListOut = components["schemas"]["TaskListOut"];
type ClientTopicRow = { id?: unknown; topic_name?: unknown; name?: unknown };

export default function PromptsPage() {
    // Client selector
    const [clients, setClients] = useState<ClientOut[]>([]);
    const [selectedClientId, setSelectedClientId] = useState<string>("");

    // Data
    const [data, setData] = useState<PromptConceptOut[]>([]);
    const [loading, setLoading] = useState<boolean>(false);
    const [error, setError] = useState<string>("");
    const [page, setPage] = useState<number>(1);
    const [pagination, setPagination] = useState<PromptConceptListOut["pagination"]>({
        page: 1,
        limit: 10,
        total: 0,
        pages: 1,
    });

    // Expanded Row State (Fanouts)
    const [expandedKey, setExpandedKey] = useState<string | null>(null);
    const [expandLoading, setExpandLoading] = useState<boolean>(false);
    const [expandTaskData, setExpandTaskData] = useState<TaskRow[]>([]);
    const [expandPagination, setExpandPagination] = useState<TaskListOut["pagination"]>({
        page: 1,
        limit: 20,
        total: 0,
        pages: 1,
    });

    // Filters
    const [searchQuery, setSearchQuery] = useState<string>("");
    const [filterTopic, setFilterTopic] = useState<string>("all");
    const [filterProduct, setFilterProduct] = useState<string>("all");
    const [filterPlatform, setFilterPlatform] = useState<string>("all");
    const [filterCountry, setFilterCountry] = useState<string>("all");
    const [filterLanguage, setFilterLanguage] = useState<string>("all");
    const [filterBatchId, setFilterBatchId] = useState<string>("all");
    const [batchIds, setBatchIds] = useState<string[]>([]);
    const pageSize = 10;
    const expandPageSize = 20;

    // Load clients on mount
    useEffect(() => {
        getClients().then((res) => {
            // Admin getClients may return array directly or { data: [] }
            // (transitional shape; backend route varies)
            const arr = Array.isArray(res) ? res : ((res as { data?: ClientOut[] } | null)?.data || res || []);
            setClients((arr as ClientOut[]) || []);
        }).catch(console.error);
    }, []);

    // Load batch IDs when client changes
    useEffect(() => {
        if (selectedClientId) {
            getBatchIds(selectedClientId)
                .then((ids) => setBatchIds(((ids as string[] | null) || [])))
                .catch(() => setBatchIds([]));
        } else {
            setData([]);
            setBatchIds([]);
            setPagination({ page: 1, limit: pageSize, total: 0, pages: 1 });
        }
    }, [selectedClientId]);

    useEffect(() => {
        setExpandedKey(null);
        setExpandTaskData([]);
        setExpandPagination({ page: 1, limit: expandPageSize, total: 0, pages: 1 });
    }, [filterBatchId]);

    // Server-side concept pagination/filtering. The paging unit is a logical
    // Client Prompt, while each row still carries all physical prompt ids.
    useEffect(() => {
        if (selectedClientId) {
            loadPrompts();
        }
    }, [
        selectedClientId,
        page,
        searchQuery,
        filterTopic,
        filterProduct,
        filterPlatform,
        filterCountry,
        filterLanguage,
    ]);

    async function loadPrompts(): Promise<void> {
        setLoading(true);
        setError("");
        setExpandedKey(null);
        setExpandTaskData([]);
        try {
            const res = await getPromptConcepts(selectedClientId, {
                page,
                limit: pageSize,
                is_active: true,
                search: searchQuery.trim(),
                topic_id: filterTopic,
                product: filterProduct,
                platform: filterPlatform,
                country: filterCountry,
                language: filterLanguage,
            });
            setData(res.data || []);
            setPagination(res.pagination || { page, limit: pageSize, total: 0, pages: 1 });
        } catch (err) {
            setError((err as Error).message);
        } finally {
            setLoading(false);
        }
    }

    const resetPage = (setter: (value: string) => void, value: string): void => {
        setter(value);
        setPage(1);
    };

    const selectedClient = useMemo(
        () => clients.find((client) => client.id === selectedClientId) || null,
        [clients, selectedClientId],
    );

    const conceptKey = (p: PromptConceptOut): string => (
        `${p.topic_id}::${p.language || ""}::${p.product || ""}::${p.intent || ""}::${p.text}`
    );

    // Unique filter options derived from raw data
    const topics = useMemo<Array<[string, string]>>(() => {
        const map = new Map<string, string>();
        ((selectedClient?.topics || []) as ClientTopicRow[]).forEach((topic) => {
            const id = topic.id ? String(topic.id) : "";
            const name = topic.topic_name || topic.name;
            if (id && name) map.set(id, String(name));
        });
        data.forEach((p) => { if (p.topic_id && p.topic_name) map.set(p.topic_id, p.topic_name); });
        return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]));
    }, [data, selectedClient]);

    const products = useMemo<string[]>(() => {
        const set = new Set(data.map((p) => p.product).filter((x): x is string => !!x));
        return Array.from(set).sort();
    }, [data]);

    const platforms = useMemo<string[]>(() => {
        const set = new Set([
            ...((selectedClient?.config_platforms || []) as string[]),
            ...data.flatMap((p) => p.platforms || []),
        ].filter((x): x is string => !!x));
        return Array.from(set).sort();
    }, [data, selectedClient]);

    const countries = useMemo<string[]>(() => {
        const set = new Set([
            ...((selectedClient?.config_countries || []) as string[]),
            ...data.flatMap((p) => p.countries || []),
        ].filter((x): x is string => !!x));
        return Array.from(set).sort();
    }, [data, selectedClient]);

    const languages = useMemo<string[]>(() => {
        const set = new Set([
            ...((selectedClient?.config_languages || []) as string[]),
            ...data.map((p) => p.language || ""),
        ].map((x) => x.toUpperCase()).filter((x): x is string => !!x));
        return Array.from(set).sort();
    }, [data, selectedClient]);

    // Expand handler — load tasks for ALL prompt IDs in merged group
    async function loadPromptTaskPage(rowKey: string, promptIds: string[], nextPage: number): Promise<void> {
        if (!selectedClientId) return;

        setExpandedKey(rowKey);
        setExpandLoading(true);
        try {
            const response = await getPromptTasksByPromptIds(selectedClientId, promptIds, {
                batch_id: filterBatchId,
                page: nextPage,
                limit: expandPageSize,
            });
            let combinedTasks: TaskRow[] = (response as TaskListOut | null)?.data || [];
            // Sort by batch_id descending, then platform, then country within the current page.
            combinedTasks.sort((a, b) => {
                const batchCmp = (b.batch_id || "").localeCompare(a.batch_id || "");
                if (batchCmp !== 0) return batchCmp;
                const platformCmp = (a.platform || "").localeCompare(b.platform || "");
                if (platformCmp !== 0) return platformCmp;
                return (a.country || "").localeCompare(b.country || "");
            });
            setExpandTaskData(combinedTasks);
            setExpandPagination(response.pagination || {
                page: nextPage,
                limit: expandPageSize,
                total: combinedTasks.length,
                pages: 1,
            });
        } catch (e) {
            console.error("Failed to load tasks:", e);
            setExpandTaskData([]);
            setExpandPagination({ page: nextPage, limit: expandPageSize, total: 0, pages: 1 });
        } finally {
            setExpandLoading(false);
        }
    }

    async function handleExpandRow(rowKey: string, promptIds: string[]): Promise<void> {
        if (expandedKey === rowKey) {
            setExpandedKey(null);
            setExpandTaskData([]);
            setExpandPagination({ page: 1, limit: expandPageSize, total: 0, pages: 1 });
            return;
        }
        await loadPromptTaskPage(rowKey, promptIds, 1);
    }

    // CSV Export
    function handleExportCSV(): void {
        const escapeCsv = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
        const headers = ["Prompt Text", "Topic", "Product", "Platforms", "Countries", "Language"];
        const rows = data.map((p) => {
            return [p.text, p.topic_name, p.product, p.platforms.join("; "), p.countries.join("; "), p.language];
        });
        const csv = [headers.map(escapeCsv).join(","), ...rows.map((r) => r.map(escapeCsv).join(","))].join("\r\n");
        const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `prompts_${new Date().toISOString().slice(0, 10)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight text-foreground">Prompts</h1>
                <p className="text-sm text-muted-foreground mt-2">
                    Expand each client prompt to see its detailed query variants (final prompts) derived for specific platforms and countries.
                </p>
            </div>

            {/* Filter Bar */}
            <Card>
                <CardContent className="p-4">
                    <div className="flex gap-3 items-end flex-wrap">
                        {/* Client selector */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Client</Label>
                            <Select
                                value={selectedClientId || "__all__"}
                                onValueChange={(v: string) => {
                                    setSelectedClientId(v === "__all__" ? "" : v);
                                    setPage(1);
                                }}
                            >
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

                        {/* Search */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Search</Label>
                            <div className="relative">
                                <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                                <Input
                                    placeholder="Search prompts..."
                                    value={searchQuery}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                                        setSearchQuery(e.target.value);
                                        setPage(1);
                                    }}
                                    className="pl-9 h-9 w-[200px]"
                                />
                            </div>
                        </div>

                        {/* Topic */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Topic</Label>
                            <Select value={filterTopic} onValueChange={(v: string) => resetPage(setFilterTopic, v)}>
                                <SelectTrigger className="w-[160px] h-9">
                                    <SelectValue placeholder="All Topics" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All Topics</SelectItem>
                                    {topics.map(([id, name]) => (
                                        <SelectItem key={id} value={id}>{name}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Product */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Product</Label>
                            <Select value={filterProduct} onValueChange={(v: string) => resetPage(setFilterProduct, v)}>
                                <SelectTrigger className="w-[140px] h-9">
                                    <SelectValue placeholder="All Products" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All Products</SelectItem>
                                    {products.map((p) => (
                                        <SelectItem key={p} value={p}>{p}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Platform */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Platform</Label>
                            <Select value={filterPlatform} onValueChange={(v: string) => resetPage(setFilterPlatform, v)}>
                                <SelectTrigger className="w-[140px] h-9">
                                    <SelectValue placeholder="All Platforms" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All Platforms</SelectItem>
                                    {platforms.map((p) => (
                                        <SelectItem key={p} value={p}>{p}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Country */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Country</Label>
                            <Select value={filterCountry} onValueChange={(v: string) => resetPage(setFilterCountry, v)}>
                                <SelectTrigger className="w-[120px] h-9">
                                    <SelectValue placeholder="All" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All</SelectItem>
                                    {countries.map((c) => (
                                        <SelectItem key={c} value={c}>{c}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Language */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Language</Label>
                            <Select value={filterLanguage} onValueChange={(v: string) => resetPage(setFilterLanguage, v)}>
                                <SelectTrigger className="w-[120px] h-9">
                                    <SelectValue placeholder="All" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All</SelectItem>
                                    {languages.map((l) => (
                                        <SelectItem key={l} value={l}>{l}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Batch ID */}
                        <div className="space-y-1">
                            <Label className="text-xs text-muted-foreground">Batch ID</Label>
                            <Select value={filterBatchId} onValueChange={(v: string) => setFilterBatchId(v)}>
                                <SelectTrigger className="w-[200px] h-9">
                                    <SelectValue placeholder="All Batches" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All Batches</SelectItem>
                                    {batchIds.map((b) => (
                                        <SelectItem key={b} value={b}>{b}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Export */}
                        <Button variant="outline" size="sm" className="h-9" onClick={handleExportCSV} disabled={!selectedClientId}>
                            <FileDown className="h-4 w-4 mr-1" /> Export CSV
                        </Button>

                        {/* Count */}
                        <div className="text-xs text-muted-foreground ml-auto self-end pb-1">
                            {pagination.total} unique prompt{pagination.total !== 1 ? "s" : ""}
                        </div>
                    </div>
                </CardContent>
            </Card>

            {/* Table */}
            {!selectedClientId ? (
                <div className="text-center py-12 text-muted-foreground text-sm">Select a client to view prompts.</div>
            ) : loading ? (
                <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
            ) : error ? (
                <div className="text-center py-12 text-red-500 text-sm">Failed to load data: {error}</div>
            ) : (
                <div className="rounded-md border bg-card">
                    <Table>
                        <TableHeader>
                            <TableRow className="bg-muted/20">
                                <TableHead className="w-[40px] px-4"></TableHead>
                                <TableHead className="w-[35%]">Client Prompt</TableHead>
                                <TableHead>Topic</TableHead>
                                <TableHead>Product</TableHead>
                                <TableHead>Countries</TableHead>
                                <TableHead>Language</TableHead>
                                <TableHead>Platforms</TableHead>
                                <TableHead className="text-right">Fanouts</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((p) => {
                                const rowKey = conceptKey(p);
                                const isExpanded = expandedKey === rowKey;

                                return (
                                    <Fragment key={rowKey}>
                                        <TableRow
                                            className={`hover:bg-muted/50 transition-colors cursor-pointer ${isExpanded ? "bg-muted/30 border-b-0" : ""}`}
                                            onClick={() => handleExpandRow(rowKey, p.prompt_ids)}
                                        >
                                            <TableCell className="px-4">
                                                <Button variant="ghost" size="icon" className="h-6 w-6 pointer-events-none">
                                                    {isExpanded ? <ChevronDown className="h-4 w-4 text-primary" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                                                </Button>
                                            </TableCell>
                                            <TableCell className="font-medium max-w-[400px] truncate">{p.text}</TableCell>
                                            <TableCell><span className="text-muted-foreground">{p.topic_name || "Unknown"}</span></TableCell>
                                            <TableCell><span className="text-xs text-muted-foreground">{p.product || "—"}</span></TableCell>
                                            <TableCell>
                                                <div className="flex flex-wrap gap-1">
                                                    {p.countries.map((c) => (
                                                        <Badge key={c} variant="outline" className="text-[10px] font-normal">{c}</Badge>
                                                    ))}
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <span className="text-xs text-muted-foreground">{(p.language || "").toUpperCase()}</span>
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex flex-wrap gap-1">
                                                    {p.platforms.map((pl) => (
                                                        <Badge key={pl} variant="secondary" className="text-[10px] font-normal">{pl}</Badge>
                                                    ))}
                                                </div>
                                            </TableCell>
                                            <TableCell className="text-right text-muted-foreground text-sm">
                                                {isExpanded ? "Loaded" : `${p.final_prompt_count} Variants`}
                                            </TableCell>
                                        </TableRow>

                                        {/* Expanded Area (Fanouts) */}
                                        {isExpanded && (
                                            <TableRow className="bg-muted/10 border-t-0 shadow-inner">
                                                <TableCell colSpan={8} className="p-0 border-b">
                                                    <div className="bg-background m-4 ml-14 mr-4 rounded-md border shadow-sm overflow-hidden animate-in fade-in slide-in-from-top-2 duration-200">
                                                        <div className="bg-muted/30 px-4 py-3 flex items-center justify-between border-b">
                                                            <div className="flex items-center gap-2">
                                                                <Network className="h-4 w-4 text-primary" />
                                                                <span className="text-sm font-semibold">Derived Query Variants (Final Prompts)</span>
                                                            </div>
                                                            <Badge variant="secondary">{expandPagination.total} Variants</Badge>
                                                        </div>
                                                        <div className="p-0">
                                                            {expandLoading ? (
                                                                <div className="flex items-center justify-center p-8">
                                                                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                                                                    <span className="ml-2 text-sm text-muted-foreground">Loading variants from geo_tasks...</span>
                                                                </div>
                                                            ) : expandTaskData.length === 0 ? (
                                                                <div className="text-center p-8 bg-muted/5 flex flex-col items-center justify-center">
                                                                    <Sparkles className="h-8 w-8 text-muted-foreground/30 mb-3" />
                                                                    <span className="text-sm text-muted-foreground font-medium">No Fanouts generated yet.</span>
                                                                    <p className="text-xs text-muted-foreground mt-1 max-w-[400px]">
                                                                        The background Scheduler will automatically expand this prompt into variants during its next run.
                                                                    </p>
                                                                </div>
                                                            ) : (
                                                                <>
                                                                    <Table>
                                                                        <TableHeader className="bg-background">
                                                                            <TableRow className="hover:bg-transparent">
                                                                                <TableHead className="pl-6">Batch ID</TableHead>
                                                                                <TableHead>Platform</TableHead>
                                                                                <TableHead>Country</TableHead>
                                                                                <TableHead className="w-[45%]">Final Instructions / Prompts</TableHead>
                                                                                <TableHead>Tasks Executed</TableHead>
                                                                                <TableHead>Status</TableHead>
                                                                            </TableRow>
                                                                        </TableHeader>
                                                                        <TableBody>
                                                                            {expandTaskData.map((task) => (
                                                                                <TableRow key={task.task_id} className="text-sm hover:bg-muted/50">
                                                                                    <TableCell className="pl-6">
                                                                                        <span className="font-mono text-[10px] text-muted-foreground" title={task.batch_id}>{(task.batch_id || "—").slice(0, 12)}</span>
                                                                                    </TableCell>
                                                                                    <TableCell>
                                                                                        <Badge variant="secondary" className="text-[10px] font-normal">{task.platform || "—"}</Badge>
                                                                                    </TableCell>
                                                                                    <TableCell>
                                                                                        <Badge variant="outline" className="text-[10px] font-normal">{task.country || "—"}</Badge>
                                                                                    </TableCell>
                                                                                    <TableCell className="font-mono text-xs whitespace-pre-wrap leading-relaxed text-muted-foreground py-4">
                                                                                        {task.final_prompt}
                                                                                    </TableCell>
                                                                                    <TableCell>
                                                                                        <span className="font-medium">{task.completed_count}</span>
                                                                                        <span className="text-muted-foreground text-xs"> / {task.calls_per_prompt} Calls</span>
                                                                                    </TableCell>
                                                                                    <TableCell>
                                                                                        <Badge variant={task.status === "COMPLETED" ? "default" : "secondary"} className="text-[10px] font-medium">
                                                                                            {task.status || "PENDING"}
                                                                                        </Badge>
                                                                                    </TableCell>
                                                                                </TableRow>
                                                                            ))}
                                                                        </TableBody>
                                                                    </Table>
                                                                    {expandPagination.total > 0 && (
                                                                        <div className="flex items-center justify-between border-t px-4 py-3 text-xs text-muted-foreground">
                                                                            <span>
                                                                                Page {expandPagination.page} of {expandPagination.pages} · {expandPagination.limit} variants per page
                                                                            </span>
                                                                            <div className="flex gap-2">
                                                                                <Button
                                                                                    variant="outline"
                                                                                    size="sm"
                                                                                    disabled={expandLoading || expandPagination.page <= 1}
                                                                                    onClick={() => loadPromptTaskPage(rowKey, p.prompt_ids, Math.max(1, expandPagination.page - 1))}
                                                                                >
                                                                                    Previous
                                                                                </Button>
                                                                                <Button
                                                                                    variant="outline"
                                                                                    size="sm"
                                                                                    disabled={expandLoading || expandPagination.page >= expandPagination.pages}
                                                                                    onClick={() => loadPromptTaskPage(rowKey, p.prompt_ids, Math.min(expandPagination.pages, expandPagination.page + 1))}
                                                                                >
                                                                                    Next
                                                                                </Button>
                                                                            </div>
                                                                        </div>
                                                                    )}
                                                                </>
                                                            )}
                                                        </div>
                                                    </div>
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </Fragment>
                                );
                            })}
                            {data.length === 0 && (
                                <TableRow>
                                    <TableCell colSpan={8} className="h-32 text-center text-muted-foreground">
                                        {data.length === 0
                                            ? "No active prompts match the current filters."
                                            : "No prompts match the current filters."}
                                    </TableCell>
                                </TableRow>
                            )}
                        </TableBody>
                    </Table>
                    {pagination.total > 0 && (
                        <div className="flex items-center justify-between border-t px-4 py-3 text-sm text-muted-foreground">
                            <span>
                                Page {pagination.page} of {pagination.pages} · {pagination.limit} Client Prompts per page
                            </span>
                            <div className="flex gap-2">
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={loading || page <= 1}
                                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                                >
                                    Previous
                                </Button>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={loading || page >= pagination.pages}
                                    onClick={() => setPage((current) => Math.min(pagination.pages, current + 1))}
                                >
                                    Next
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
