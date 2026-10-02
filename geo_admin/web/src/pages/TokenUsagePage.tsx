import { useState, useEffect } from "react";
import { getTokenUsageSummary, getTokenUsageByUser, getTokenUsageByModel, getClients } from "../api/client";
import type { components } from "@/api/openapi";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Zap, Users, Cpu, Calendar } from "lucide-react";

// Phase 7c (2026-04-25): replaced hand-written row interfaces with the
// generated OpenAPI schemas (``UsageSummaryRow`` / ``UsageByUserRow`` /
// ``UsageByModelRow`` / ``ClientOut``).
type ClientRow = components["schemas"]["ClientOut"];
type SummaryRow = components["schemas"]["UsageSummaryRow"];
type UserUsageRow = components["schemas"]["UsageByUserRow"];
type ModelUsageRow = components["schemas"]["UsageByModelRow"];

interface UsageParams {
    days: number;
    client_id?: string;
    // Index signature so this can be passed straight to the
    // ``getTokenUsage*`` helpers which take ``Record<string, unknown>``.
    [k: string]: unknown;
}

function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return String(n);
}

function formatDate(d?: string | null): string {
    if (!d) return "—";
    return new Date(d).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export default function TokenUsagePage() {
    const [clients, setClients] = useState<ClientRow[]>([]);
    const [selectedClient, setSelectedClient] = useState<string>("");
    const [days, setDays] = useState<number>(7);
    const [loading, setLoading] = useState<boolean>(true);

    const [summary, setSummary] = useState<SummaryRow[]>([]);
    const [byUser, setByUser] = useState<UserUsageRow[]>([]);
    const [byModel, setByModel] = useState<ModelUsageRow[]>([]);

    useEffect(() => {
        (getClients() as Promise<ClientRow[]>).then(setClients).catch(() => {});
    }, []);

    useEffect(() => {
        loadData();
    }, [selectedClient, days]);

    async function loadData(): Promise<void> {
        setLoading(true);
        try {
            const params: UsageParams = { days };
            if (selectedClient) params.client_id = selectedClient;

            const [s, m] = await Promise.all([
                getTokenUsageSummary(params) as Promise<SummaryRow[]>,
                getTokenUsageByModel(params) as Promise<ModelUsageRow[]>,
            ]);
            setSummary(s);
            setByModel(m);

            if (selectedClient) {
                const u = (await getTokenUsageByUser(selectedClient, days)) as UserUsageRow[];
                setByUser(u);
            } else {
                setByUser([]);
            }
        } catch {
            setSummary([]);
            setByUser([]);
            setByModel([]);
        } finally {
            setLoading(false);
        }
    }

    // Aggregate totals
    const totalTokens = summary.reduce((acc, r) => acc + (r.total_tokens || 0), 0);
    const totalRequests = summary.reduce((acc, r) => acc + (r.request_count || 0), 0);

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">Token Usage</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                    Monitor agent token consumption across clients, users, and models.
                </p>
            </div>

            {/* Filters */}
            <div className="flex gap-3 items-center">
                <Select value={selectedClient || "__all__"} onValueChange={(v) => setSelectedClient(v === "__all__" ? "" : v)}>
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
                <Select value={String(days)} onValueChange={(v) => setDays(parseInt(v))}>
                    <SelectTrigger className="w-[180px] h-10">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="1">Today</SelectItem>
                        <SelectItem value="7">Last 7 days</SelectItem>
                        <SelectItem value="14">Last 14 days</SelectItem>
                        <SelectItem value="30">Last 30 days</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            {loading ? (
                <div className="flex h-32 items-center justify-center">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
            ) : (
                <>
                    {/* Summary Cards */}
                    <div className="grid grid-cols-3 gap-4">
                        <Card>
                            <CardContent className="pt-6">
                                <div className="flex items-center gap-3">
                                    <div className="p-2 rounded-lg bg-primary/10">
                                        <Zap className="h-5 w-5 text-primary" />
                                    </div>
                                    <div>
                                        <p className="text-2xl font-bold">{formatTokens(totalTokens)}</p>
                                        <p className="text-xs text-muted-foreground">Total Tokens</p>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardContent className="pt-6">
                                <div className="flex items-center gap-3">
                                    <div className="p-2 rounded-lg bg-emerald-500/10">
                                        <Calendar className="h-5 w-5 text-emerald-500" />
                                    </div>
                                    <div>
                                        <p className="text-2xl font-bold">{totalRequests}</p>
                                        <p className="text-xs text-muted-foreground">Total Requests</p>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardContent className="pt-6">
                                <div className="flex items-center gap-3">
                                    <div className="p-2 rounded-lg bg-amber-500/10">
                                        <Cpu className="h-5 w-5 text-amber-500" />
                                    </div>
                                    <div>
                                        <p className="text-2xl font-bold">{byModel.length}</p>
                                        <p className="text-xs text-muted-foreground">Models Used</p>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    </div>

                    {/* Daily Breakdown */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-lg flex items-center gap-2">
                                <Calendar className="h-5 w-5 text-primary" /> Daily Breakdown
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="p-0">
                            {summary.length === 0 ? (
                                <div className="p-8 text-center text-sm text-muted-foreground">No usage data</div>
                            ) : (
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b text-xs text-muted-foreground">
                                            <th className="text-left px-5 py-2 font-medium">Date</th>
                                            <th className="text-left px-5 py-2 font-medium">Client</th>
                                            <th className="text-right px-5 py-2 font-medium">Input</th>
                                            <th className="text-right px-5 py-2 font-medium">Output</th>
                                            <th className="text-right px-5 py-2 font-medium">Total</th>
                                            <th className="text-right px-5 py-2 font-medium">Requests</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y">
                                        {summary.map((r, i) => (
                                            <tr key={i} className="hover:bg-accent/30">
                                                <td className="px-5 py-2.5 font-mono text-xs">{formatDate(r.day)}</td>
                                                <td className="px-5 py-2.5">{r.client_name || "—"}</td>
                                                <td className="px-5 py-2.5 text-right tabular-nums">{formatTokens(r.total_input)}</td>
                                                <td className="px-5 py-2.5 text-right tabular-nums">{formatTokens(r.total_output)}</td>
                                                <td className="px-5 py-2.5 text-right tabular-nums font-medium">{formatTokens(r.total_tokens)}</td>
                                                <td className="px-5 py-2.5 text-right tabular-nums">{r.request_count}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </CardContent>
                    </Card>

                    {/* By Model */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-lg flex items-center gap-2">
                                <Cpu className="h-5 w-5 text-primary" /> By Model
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="p-0">
                            {byModel.length === 0 ? (
                                <div className="p-8 text-center text-sm text-muted-foreground">No data</div>
                            ) : (
                                <div className="divide-y">
                                    {byModel.map((r) => (
                                        <div key={r.model_id} className="flex items-center justify-between px-5 py-3">
                                            <div className="flex items-center gap-2">
                                                <Badge variant="outline" className="font-mono text-xs">{r.model_id}</Badge>
                                                <span className="text-xs text-muted-foreground">{r.request_count} requests</span>
                                            </div>
                                            <div className="text-sm font-medium tabular-nums">{formatTokens(r.total_tokens)}</div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </CardContent>
                    </Card>

                    {/* By User (only when client selected) */}
                    {selectedClient && (
                        <Card>
                            <CardHeader className="pb-3">
                                <CardTitle className="text-lg flex items-center gap-2">
                                    <Users className="h-5 w-5 text-primary" /> By User
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="p-0">
                                {byUser.length === 0 ? (
                                    <div className="p-8 text-center text-sm text-muted-foreground">No data</div>
                                ) : (
                                    <table className="w-full text-sm">
                                        <thead>
                                            <tr className="border-b text-xs text-muted-foreground">
                                                <th className="text-left px-5 py-2 font-medium">User</th>
                                                <th className="text-right px-5 py-2 font-medium">Input</th>
                                                <th className="text-right px-5 py-2 font-medium">Output</th>
                                                <th className="text-right px-5 py-2 font-medium">Total</th>
                                                <th className="text-right px-5 py-2 font-medium">Requests</th>
                                                <th className="text-right px-5 py-2 font-medium">Last Active</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y">
                                            {byUser.map((r) => (
                                                <tr key={r.user_identifier} className="hover:bg-accent/30">
                                                    <td className="px-5 py-2.5 text-xs truncate max-w-[200px]">{r.user_identifier}</td>
                                                    <td className="px-5 py-2.5 text-right tabular-nums">{formatTokens(r.total_input)}</td>
                                                    <td className="px-5 py-2.5 text-right tabular-nums">{formatTokens(r.total_output)}</td>
                                                    <td className="px-5 py-2.5 text-right tabular-nums font-medium">{formatTokens(r.total_tokens)}</td>
                                                    <td className="px-5 py-2.5 text-right tabular-nums">{r.request_count}</td>
                                                    <td className="px-5 py-2.5 text-right text-xs text-muted-foreground">{formatDate(r.last_active)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}
                            </CardContent>
                        </Card>
                    )}
                </>
            )}
        </div>
    );
}
