import { useState, useEffect } from "react";
import type { components } from "../api/openapi";
import { getAgentSessions, getSessionMessages, getClients } from "../api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MessageSquare, Search, ChevronLeft, ChevronRight, User, Bot, Wrench, Loader2 } from "lucide-react";

type AgentSessionRow = components["schemas"]["AgentSessionRow"];
type AgentSessionListOut = components["schemas"]["AgentSessionListOut"];
type AgentMessageOut = components["schemas"]["AgentMessageOut"];
type ClientOut = components["schemas"]["ClientOut"];

interface SessionFilters {
    client_id: string;
    search: string;
    limit: number;
    offset: number;
    [key: string]: unknown;
}

function formatDate(d: string | null | undefined): string {
    if (!d) return "—";
    return new Date(d).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const ENTRY_COLORS: Record<string, string> = {
    chat: "bg-blue-500/10 text-blue-400",
    analyze: "bg-emerald-500/10 text-emerald-400",
    content: "bg-amber-500/10 text-amber-400",
};

export default function AgentSessionsPage() {
    const [sessions, setSessions] = useState<AgentSessionRow[]>([]);
    const [total, setTotal] = useState<number>(0);
    const [loading, setLoading] = useState<boolean>(true);
    const [clients, setClients] = useState<ClientOut[]>([]);
    const [filters, setFilters] = useState<SessionFilters>({ client_id: "", search: "", limit: 20, offset: 0 });

    // Message viewer
    const [viewThread, setViewThread] = useState<AgentSessionRow | null>(null);
    const [messages, setMessages] = useState<AgentMessageOut[]>([]);
    const [loadingMsgs, setLoadingMsgs] = useState<boolean>(false);

    useEffect(() => {
        getClients()
            .then((res) => setClients((res as ClientOut[]) || []))
            .catch(() => {});
    }, []);

    useEffect(() => {
        loadSessions();
    }, [filters.client_id, filters.offset]);

    async function loadSessions(): Promise<void> {
        setLoading(true);
        try {
            const res = (await getAgentSessions(filters)) as AgentSessionListOut;
            setSessions(res.data || []);
            setTotal(res.total || 0);
        } catch {
            setSessions([]);
        } finally {
            setLoading(false);
        }
    }

    async function openThread(session: AgentSessionRow): Promise<void> {
        setViewThread(session);
        setLoadingMsgs(true);
        try {
            const msgs = (await getSessionMessages(session.thread_id)) as AgentMessageOut[];
            setMessages(msgs);
        } catch {
            setMessages([]);
        } finally {
            setLoadingMsgs(false);
        }
    }

    const page = Math.floor(filters.offset / filters.limit) + 1;
    const totalPages = Math.ceil(total / filters.limit);

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">Agent Sessions</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                    Audit all agent conversations across clients and users.
                </p>
            </div>

            {/* Filters */}
            <div className="flex gap-3 items-center">
                <Select value={filters.client_id || "__all__"} onValueChange={(v: string) => setFilters({ ...filters, client_id: v === "__all__" ? "" : v, offset: 0 })}>
                    <SelectTrigger className="w-[200px] h-10">
                        <SelectValue placeholder="All Clients" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="__all__">All Clients</SelectItem>
                        {clients.map((c) => (
                            <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <div className="relative flex-1 max-w-xs">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                        placeholder="Search by title..."
                        className="pl-10"
                        value={filters.search}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFilters({ ...filters, search: e.target.value })}
                        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && loadSessions()}
                    />
                </div>
                <Button variant="outline" onClick={loadSessions}>Search</Button>
            </div>

            {/* Sessions Table */}
            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg flex items-center gap-2">
                        <MessageSquare className="h-5 w-5 text-primary" />
                        Sessions
                        <Badge variant="secondary" className="ml-2">{total}</Badge>
                    </CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                    {loading ? (
                        <div className="flex h-32 items-center justify-center">
                            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                        </div>
                    ) : sessions.length === 0 ? (
                        <div className="p-8 text-center text-sm text-muted-foreground">No sessions found</div>
                    ) : (
                        <div className="divide-y">
                            {sessions.map((s) => (
                                <button
                                    key={s.id}
                                    className="w-full flex items-center gap-4 px-5 py-3 text-left hover:bg-accent/50 transition-colors"
                                    onClick={() => openThread(s)}
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5">
                                            <span className="font-medium text-sm truncate">
                                                {s.title || "Untitled Session"}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-3 text-xs text-muted-foreground">
                                            <span>{s.client_name || "—"}</span>
                                            <span className="truncate max-w-[200px]">{s.user_id || "—"}</span>
                                        </div>
                                    </div>
                                    <div className="text-right shrink-0">
                                        <div className="text-xs text-muted-foreground">{formatDate(s.updated_at)}</div>
                                        <div className="text-xs text-muted-foreground/60">{s.message_count} msgs</div>
                                    </div>
                                </button>
                            ))}
                        </div>
                    )}
                </CardContent>
            </Card>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-3">
                    <Button
                        variant="outline" size="sm"
                        disabled={page <= 1}
                        onClick={() => setFilters({ ...filters, offset: filters.offset - filters.limit })}
                    >
                        <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-sm text-muted-foreground">
                        Page {page} of {totalPages}
                    </span>
                    <Button
                        variant="outline" size="sm"
                        disabled={page >= totalPages}
                        onClick={() => setFilters({ ...filters, offset: filters.offset + filters.limit })}
                    >
                        <ChevronRight className="h-4 w-4" />
                    </Button>
                </div>
            )}

            {/* Message Viewer Dialog */}
            <Dialog open={!!viewThread} onOpenChange={() => setViewThread(null)}>
                <DialogContent className="max-w-3xl max-h-[80vh] overflow-hidden flex flex-col">
                    <DialogHeader>
                        <DialogTitle className="text-lg">
                            {viewThread?.title || "Session Messages"}
                            <span className="text-xs text-muted-foreground font-normal ml-3">
                                {viewThread?.thread_id}
                            </span>
                        </DialogTitle>
                    </DialogHeader>
                    <div className="flex-1 overflow-y-auto space-y-3 pr-2">
                        {loadingMsgs ? (
                            <div className="flex h-32 items-center justify-center">
                                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                            </div>
                        ) : messages.length === 0 ? (
                            <div className="text-center text-sm text-muted-foreground py-8">No messages</div>
                        ) : (
                            messages.map((m) => (
                                <div
                                    key={m.id}
                                    className={`rounded-lg p-3 text-sm ${
                                        m.role === "user"
                                            ? "bg-primary/5 border border-primary/10 ml-8"
                                            : m.role === "tool"
                                            ? "bg-amber-500/5 border border-amber-500/10 mx-4"
                                            : "bg-muted/50 mr-8"
                                    }`}
                                >
                                    <div className="flex items-center gap-1.5 mb-1.5 text-xs text-muted-foreground">
                                        {m.role === "user" ? (
                                            <User className="h-3 w-3" />
                                        ) : m.role === "tool" ? (
                                            <Wrench className="h-3 w-3" />
                                        ) : (
                                            <Bot className="h-3 w-3" />
                                        )}
                                        <span className="font-medium">{m.role}</span>
                                        <span className="ml-auto">{formatDate(m.created_at)}</span>
                                    </div>
                                    <div className="whitespace-pre-wrap text-foreground/90 text-xs leading-relaxed">
                                        {m.content ? String(m.content) : (m.tool_results ? JSON.stringify(m.tool_results, null, 2) : "—")}
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
}
