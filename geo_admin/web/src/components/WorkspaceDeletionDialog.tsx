import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowUpRight, CheckCircle2, Loader2, RefreshCw, ShieldAlert, StopCircle, Trash2 } from "lucide-react";

import {
    deleteClient,
    getWorkspaceDeletionReadiness,
    stopAllWorkspaceScheduling,
    type WorkspaceDeletionReadiness,
} from "../api/client";
import { ApiError } from "../api/types";
import {
    buildWorkspaceSaaSLink,
    canSubmitWorkspaceDelete,
    createWorkspaceActionEpoch,
    getWorkspaceDeletionStep,
    type WorkspaceActionToken,
} from "../lib/workspaceDeletion";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

interface WorkspaceDeletionDialogProps {
    client: { id: string; name: string } | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onDeleted: (clientId: string) => void | Promise<void>;
}

const SAAS_WEB_URL = (import.meta.env.VITE_SAAS_WEB_URL as string | undefined) || "";

const COUNT_LABELS: Array<[keyof WorkspaceDeletionReadiness["counts"], string]> = [
    ["topics", "Topics"],
    ["logical_prompts", "Logical Prompts"],
    ["physical_prompts", "Physical Prompt rows"],
    ["tasks", "Tasks"],
    ["results", "Results"],
    ["citations", "Citations"],
    ["brand_mentions", "Brand mentions"],
    ["product_mentions", "Product mentions"],
    ["sentiment_results", "Sentiment results"],
    ["sentiment_themes", "Sentiment themes"],
    ["static_reports", "Static reports"],
    ["agent_tasks", "Agent tasks"],
    ["published_urls", "Published URLs"],
];

function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        return error.code ? `${error.message} (${error.code})` : error.message;
    }
    return error instanceof Error ? error.message : "Request failed";
}

function isAbortError(error: unknown): boolean {
    return error instanceof DOMException
        ? error.name === "AbortError"
        : error instanceof Error && error.name === "AbortError";
}

export default function WorkspaceDeletionDialog({
    client,
    open,
    onOpenChange,
    onDeleted,
}: WorkspaceDeletionDialogProps) {
    const [readiness, setReadiness] = useState<WorkspaceDeletionReadiness | null>(null);
    const [loading, setLoading] = useState(false);
    const [stopping, setStopping] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [confirmation, setConfirmation] = useState("");
    const [error, setError] = useState("");
    const requestSequence = useRef(0);
    const actionEpoch = useRef(createWorkspaceActionEpoch());
    const stopInFlight = useRef<WorkspaceActionToken | null>(null);
    const deleteInFlight = useRef<WorkspaceActionToken | null>(null);
    const openRef = useRef(open);
    const clientIdRef = useRef<string | null>(client?.id || null);
    openRef.current = open;
    clientIdRef.current = client?.id || null;

    const isCurrentAction = useCallback((token: WorkspaceActionToken): boolean => (
        openRef.current
        && clientIdRef.current === token.clientId
        && actionEpoch.current.isCurrent(token)
    ), []);

    const loadReadiness = useCallback(async (clientId: string, preserveError = false) => {
        const token = actionEpoch.current.begin(clientId);
        if (!token) return;
        const sequence = ++requestSequence.current;
        if (isCurrentAction(token)) {
            setLoading(true);
            if (!preserveError) setError("");
        }
        try {
            const next = await getWorkspaceDeletionReadiness(clientId, { signal: token.signal });
            if (isCurrentAction(token) && sequence === requestSequence.current) setReadiness(next);
        } catch (loadError) {
            if (!isAbortError(loadError) && isCurrentAction(token) && sequence === requestSequence.current) {
                setReadiness(null);
                setError(errorMessage(loadError));
            }
        } finally {
            if (isCurrentAction(token) && sequence === requestSequence.current) setLoading(false);
            actionEpoch.current.finish(token);
        }
    }, [isCurrentAction]);

    useLayoutEffect(() => {
        const clientId = client?.id || null;
        actionEpoch.current.setOwner(open, clientId);
        requestSequence.current += 1;
        stopInFlight.current = null;
        deleteInFlight.current = null;
        setLoading(Boolean(open && clientId));
        setStopping(false);
        setDeleting(false);
        setReadiness(null);
        setConfirmation("");
        setError("");
        if (open && clientId) void loadReadiness(clientId);
    }, [client?.id, loadReadiness, open]);

    useEffect(() => {
        if (!open) return;
        const refreshOnReturn = () => {
            const clientId = clientIdRef.current;
            if (clientId) void loadReadiness(clientId);
        };
        window.addEventListener("focus", refreshOnReturn);
        return () => window.removeEventListener("focus", refreshOnReturn);
    }, [loadReadiness, open]);

    const promptLink = useMemo(() => client
        ? buildWorkspaceSaaSLink(SAAS_WEB_URL, "/prompt-editor", client.id, { workspace_cleanup: "prompts" })
        : null, [client]);
    const topicLink = useMemo(() => client
        ? buildWorkspaceSaaSLink(SAAS_WEB_URL, "/settings", client.id, { tab: "topics" })
        : null, [client]);

    async function handleStopAllScheduling(): Promise<void> {
        if (!client || stopInFlight.current) return;
        const token = actionEpoch.current.begin(client.id);
        if (!token) return;
        stopInFlight.current = token;
        if (isCurrentAction(token)) {
            setStopping(true);
            setError("");
        }
        try {
            await stopAllWorkspaceScheduling(token.clientId, { signal: token.signal });
            if (isCurrentAction(token)) await loadReadiness(token.clientId);
        } catch (stopError) {
            if (!isAbortError(stopError) && isCurrentAction(token)) {
                setError(errorMessage(stopError));
            }
        } finally {
            if (stopInFlight.current === token) stopInFlight.current = null;
            if (isCurrentAction(token)) setStopping(false);
            actionEpoch.current.finish(token);
        }
    }

    async function handleFinalDelete(): Promise<void> {
        if (!client || !readiness || deleteInFlight.current) return;
        if (!canSubmitWorkspaceDelete(readiness, confirmation, deleting)) return;
        const token = actionEpoch.current.begin(client.id);
        if (!token) return;
        deleteInFlight.current = token;
        if (isCurrentAction(token)) {
            setDeleting(true);
            setError("");
        }
        try {
            await deleteClient(token.clientId, confirmation, { signal: token.signal });
            if (!isCurrentAction(token)) return;
            await onDeleted(token.clientId);
            if (!isCurrentAction(token)) return;
            actionEpoch.current.setOwner(false, null);
            onOpenChange(false);
        } catch (deleteError) {
            if (isAbortError(deleteError) || !isCurrentAction(token)) return;
            const message = errorMessage(deleteError);
            setError(message);
            await loadReadiness(token.clientId, true);
            if (isCurrentAction(token)) setError(message);
        } finally {
            if (deleteInFlight.current === token) deleteInFlight.current = null;
            if (isCurrentAction(token)) setDeleting(false);
            actionEpoch.current.finish(token);
        }
    }

    function handleOpenChange(nextOpen: boolean): void {
        if (nextOpen || deleting) return;
        actionEpoch.current.setOwner(false, null);
        requestSequence.current += 1;
        stopInFlight.current = null;
        setLoading(false);
        setStopping(false);
        onOpenChange(false);
    }

    const step = readiness ? getWorkspaceDeletionStep(readiness) : null;
    const canDelete = readiness ? canSubmitWorkspaceDelete(readiness, confirmation, deleting) : false;
    const risk = step === "FINALIZE_DELETE"
        ? { label: "Low", variant: "secondary" as const }
        : step === "INTERNAL_DATA_REPAIR"
            ? { label: "Critical", variant: "destructive" as const }
            : { label: "High", variant: "destructive" as const };

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <ShieldAlert className="h-5 w-5 text-destructive" /> Workspace deletion readiness
                    </DialogTitle>
                    <DialogDescription>
                        Clean up high-volume data in bounded steps before permanently deleting {client?.name || "this Workspace"}.
                    </DialogDescription>
                </DialogHeader>

                {loading && !readiness ? (
                    <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" /> Checking deletion readiness…
                    </div>
                ) : readiness ? (
                    <div className="space-y-5">
                        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm">
                            <div>
                                Recommended next action: <strong>{step?.replace(/_/g, " ")}</strong>
                                <div className="mt-1 text-xs text-muted-foreground">
                                    Final cascade footprint: {readiness.cascade_footprint.total_rows.toLocaleString()} / {readiness.cascade_footprint.max_rows.toLocaleString()} rows · Active work: {readiness.active_work.total_items.toLocaleString()}
                                </div>
                            </div>
                            <Badge variant={risk.variant}>Risk: {risk.label}</Badge>
                        </div>
                        <div className="rounded-lg border bg-muted/30 p-4">
                            <div className="mb-3 flex items-center justify-between">
                                <h3 className="font-semibold">1. Stop scheduling</h3>
                                {Object.values(readiness.schedulers).every((scheduler) => scheduler.stopped) ? (
                                    <Badge className="bg-emerald-600"><CheckCircle2 className="mr-1 h-3 w-3" />Stopped</Badge>
                                ) : (
                                    <Badge variant="destructive"><AlertTriangle className="mr-1 h-3 w-3" />Action required</Badge>
                                )}
                            </div>
                            <div className="grid gap-2 sm:grid-cols-3">
                                {Object.entries(readiness.schedulers).map(([name, scheduler]) => (
                                    <div key={name} className="rounded border bg-background px-3 py-2 text-xs">
                                        <div className="font-medium capitalize">{name.replace("_", " ")}</div>
                                        <div className={scheduler.stopped ? "text-emerald-600" : "text-amber-600"}>{scheduler.state}</div>
                                        {scheduler.error && <div className="mt-1 text-destructive">{scheduler.error}</div>}
                                    </div>
                                ))}
                            </div>
                            {step === "STOP_SCHEDULING" && (
                                <Button className="mt-3" variant="outline" onClick={handleStopAllScheduling} disabled={stopping}>
                                    {stopping ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <StopCircle className="mr-2 h-4 w-4" />}
                                    Stop All Scheduling
                                </Button>
                            )}
                        </div>

                        <div className="rounded-lg border p-4">
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <h3 className="font-semibold">2. Clear Prompts, then Topics</h3>
                                <Badge variant={readiness.counts.physical_prompts || readiness.counts.topics ? "destructive" : "secondary"}>
                                    {readiness.counts.physical_prompts + readiness.counts.topics} blocking rows
                                </Badge>
                            </div>
                            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                                {COUNT_LABELS.map(([key, label]) => (
                                    <div key={key} className="rounded border bg-muted/20 px-3 py-2">
                                        <div className="text-xs text-muted-foreground">{label}</div>
                                        <div className="text-lg font-semibold tabular-nums">{readiness.counts[key].toLocaleString()}</div>
                                    </div>
                                ))}
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2">
                                {promptLink && readiness.counts.physical_prompts > 0 ? (
                                    <Button asChild variant={step === "DELETE_PROMPTS" ? "default" : "outline"}>
                                        <a href={promptLink} target="_blank" rel="noreferrer">Open Prompt Management <ArrowUpRight className="ml-2 h-4 w-4" /></a>
                                    </Button>
                                ) : !promptLink ? (
                                    <p className="text-sm text-destructive">VITE_SAAS_WEB_URL is not configured; the SaaS cleanup links are unavailable.</p>
                                ) : null}
                                {topicLink && readiness.counts.physical_prompts === 0 && readiness.counts.topics > 0 && (
                                    <Button asChild variant={step === "DELETE_TOPICS" ? "default" : "outline"}>
                                        <a href={topicLink} target="_blank" rel="noreferrer">Open Topic Settings <ArrowUpRight className="ml-2 h-4 w-4" /></a>
                                    </Button>
                                )}
                                <Button variant="ghost" onClick={() => client && void loadReadiness(client.id)} disabled={loading}>
                                    <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
                                </Button>
                            </div>
                        </div>

                        {readiness.blockers.length > 0 && (
                            <div className={`rounded-lg border p-4 ${step === "INTERNAL_DATA_REPAIR" ? "border-destructive/50 bg-destructive/5" : "bg-amber-50/50 dark:bg-amber-950/10"}`}>
                                <h3 className="mb-2 font-semibold">Deletion blockers</h3>
                                <ul className="space-y-1 text-sm">
                                    {readiness.blockers.map((blocker) => (
                                        <li key={`${blocker.code}-${blocker.count ?? ""}`}>
                                            <span className="font-medium">{blocker.code}:</span> {blocker.message}
                                            {blocker.count != null ? ` (${blocker.count.toLocaleString()})` : ""}
                                        </li>
                                    ))}
                                </ul>
                                {step === "INTERNAL_DATA_REPAIR" && (
                                    <p className="mt-3 text-sm font-medium text-destructive">
                                        This is an internal data condition. Do not retry final deletion; engineering must repair the orphaned or oversized residual data first.
                                    </p>
                                )}
                            </div>
                        )}

                        <div className="rounded-lg border border-destructive/30 p-4">
                            <h3 className="font-semibold">3. Permanently delete Workspace</h3>
                            <p className="mt-1 text-sm text-muted-foreground">
                                Enter the exact Workspace name <strong className="text-foreground">{readiness.workspace.name}</strong>. This cannot be undone.
                            </p>
                            <div className="mt-3 space-y-2">
                                <Label htmlFor="workspace-delete-confirmation">Workspace name</Label>
                                <Input
                                    id="workspace-delete-confirmation"
                                    value={confirmation}
                                    onChange={(event) => setConfirmation(event.target.value)}
                                    disabled={!readiness.can_finalize || deleting}
                                    autoComplete="off"
                                />
                            </div>
                            {!readiness.can_finalize && (
                                <p className="mt-2 text-xs text-muted-foreground">Complete the recommended cleanup action before final deletion.</p>
                            )}
                        </div>
                    </div>
                ) : null}

                {error && (
                    <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                        {error}
                    </div>
                )}

                <DialogFooter>
                    <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={deleting}>Cancel</Button>
                    <Button variant="destructive" onClick={handleFinalDelete} disabled={!canDelete}>
                        {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                        Delete Workspace Permanently
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
