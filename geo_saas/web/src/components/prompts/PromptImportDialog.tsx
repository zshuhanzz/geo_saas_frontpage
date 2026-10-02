import { useCallback, useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, Download, FileText, FileUp, Loader2, RotateCcw, UploadCloud } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AllowedValuesTable } from "@/components/prompts/AllowedValuesTable";
import { ImportPreviewTable } from "@/components/prompts/ImportPreviewTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    commitPromptImport,
    downloadPromptImportAllowedValues,
    downloadPromptImportTemplate,
    getPromptImportAllowedValues,
    previewPromptImport,
    PromptImportApiError,
    undoPromptImport,
    type PromptAllowedValuesOut,
    type PromptImportDownload,
} from "@/lib/api/prompts";
import {
    applyCommittedImport,
    applyPreview,
    applyStalePreview,
    applyUndoResult,
    canCommitPromptImportForClient,
    createPromptImportState,
    getOwnedPromptImportState,
    isPromptImportStateOwned,
    resetPromptImportForWorkspace,
    selectPromptImportFile,
    summarizePromptImport,
} from "./promptImportViewModel";
import {
    allowedValuesWorkspaceKey,
    describePromptImportIssue,
    getOwnedAllowedValues,
    getTemplateDownloadReadiness,
    normalizePromptImportLocale,
} from "@/lib/promptImport";

interface PromptImportDialogProps {
    clientId: string;
    workspaceName: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onImported: () => void;
}

function saveDownload(download: PromptImportDownload) {
    const url = URL.createObjectURL(download.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = download.filename;
    anchor.click();
    URL.revokeObjectURL(url);
}

export function PromptImportDialog({ clientId, workspaceName, open, onOpenChange, onImported }: PromptImportDialogProps) {
    const { t, i18n } = useTranslation(["insights", "common"]);
    const locale = normalizePromptImportLocale(i18n.resolvedLanguage);
    const inputId = useId();
    const inputRef = useRef<HTMLInputElement>(null);
    const previewController = useRef<AbortController | null>(null);
    const allowedController = useRef<AbortController | null>(null);
    const miscControllers = useRef<Set<AbortController>>(new Set());
    const requestSequence = useRef(0);

    const [state, setState] = useState(() => createPromptImportState(clientId));
    const [tab, setTab] = useState("import");
    const [previewing, setPreviewing] = useState(false);
    const [committing, setCommitting] = useState(false);
    const [confirmCommitOpen, setConfirmCommitOpen] = useState(false);
    const [resultOpen, setResultOpen] = useState(false);
    const [undoConfirmOpen, setUndoConfirmOpen] = useState(false);
    const [undoing, setUndoing] = useState(false);
    const [requestError, setRequestError] = useState("");
    const [dragActive, setDragActive] = useState(false);
    const [allowed, setAllowed] = useState<PromptAllowedValuesOut | null>(null);
    const [allowedOwnerClientId, setAllowedOwnerClientId] = useState<string | null>(null);
    const [allowedOwnerLocale, setAllowedOwnerLocale] = useState<"zh-CN" | "en-US" | null>(null);
    const [allowedLoading, setAllowedLoading] = useState(false);
    const [allowedError, setAllowedError] = useState("");
    const [allowedReload, setAllowedReload] = useState(0);
    const [downloadingTemplate, setDownloadingTemplate] = useState(false);
    const [downloadingAllowed, setDownloadingAllowed] = useState(false);
    const [previewPage, setPreviewPage] = useState(0);
    const [expandedPreviewRow, setExpandedPreviewRow] = useState<number | null>(null);

    const localizedErrorMessage = useCallback((error: unknown, fallback: string): string => {
        if (error instanceof PromptImportApiError) {
            const descriptor = describePromptImportIssue({
                code: error.code,
                message: error.message,
                actual: error.actual,
                allowed: error.allowed,
                details: error.details,
            });
            return t(descriptor.key, descriptor.values);
        }
        return fallback;
    }, [t]);

    function abortEverything() {
        previewController.current?.abort();
        allowedController.current?.abort();
        for (const controller of miscControllers.current) controller.abort();
        miscControllers.current.clear();
    }

    useEffect(() => {
        abortEverything();
        requestSequence.current += 1;
        setState((current) => resetPromptImportForWorkspace(current, clientId));
        setAllowed(null);
        setAllowedOwnerClientId(null);
        setAllowedOwnerLocale(null);
        setAllowedError("");
        setRequestError("");
        setPreviewing(false);
        setCommitting(false);
        setUndoing(false);
        setDownloadingTemplate(false);
        setDownloadingAllowed(false);
        setConfirmCommitOpen(false);
        setResultOpen(false);
        setUndoConfirmOpen(false);
        setTab("import");
        setPreviewPage(0);
        setExpandedPreviewRow(null);
        if (inputRef.current) inputRef.current.value = "";
        return abortEverything;
    }, [clientId]);

    useEffect(() => {
        if (!open || !clientId) return;
        allowedController.current?.abort();
        const controller = new AbortController();
        allowedController.current = controller;
        const ownerClientId = clientId;
        const ownerLocale = locale;
        setAllowed(null);
        setAllowedOwnerClientId(ownerClientId);
        setAllowedOwnerLocale(ownerLocale);
        setAllowedLoading(true);
        setAllowedError("");
        getPromptImportAllowedValues(clientId, locale, { signal: controller.signal })
            .then((response) => {
                if (!controller.signal.aborted) setAllowed(response);
            })
            .catch((error) => {
                if (!controller.signal.aborted) setAllowedError(localizedErrorMessage(error, t("prompts.import.errors.allowedValues")));
            })
            .finally(() => {
                if (!controller.signal.aborted) setAllowedLoading(false);
            });
        return () => controller.abort();
    }, [allowedReload, clientId, locale, localizedErrorMessage, open, t]);

    function handleOpenChange(nextOpen: boolean) {
        if (!nextOpen) {
            abortEverything();
            requestSequence.current += 1;
            setPreviewing(false);
            setCommitting(false);
            setUndoing(false);
            setDownloadingTemplate(false);
            setDownloadingAllowed(false);
            setState(createPromptImportState(clientId));
            setRequestError("");
            setConfirmCommitOpen(false);
            setPreviewPage(0);
            setExpandedPreviewRow(null);
            if (inputRef.current) inputRef.current.value = "";
        }
        onOpenChange(nextOpen);
    }

    async function selectFile(file: File | null) {
        if (!isPromptImportStateOwned(state, clientId)) return;
        previewController.current?.abort();
        requestSequence.current += 1;
        setPreviewing(false);
        setCommitting(false);
        setState((current) => selectPromptImportFile(current, file));
        setRequestError("");
        setConfirmCommitOpen(false);
        setResultOpen(false);
        setPreviewPage(0);
        setExpandedPreviewRow(null);
        if (!file) return;
        const sequence = requestSequence.current;
        const controller = new AbortController();
        previewController.current = controller;
        setPreviewing(true);
        try {
            const preview = await previewPromptImport(clientId, file, { signal: controller.signal });
            if (!controller.signal.aborted && sequence === requestSequence.current) {
                setState((current) => isPromptImportStateOwned(current, clientId) ? applyPreview(current, preview) : current);
                setPreviewPage(0);
                setExpandedPreviewRow(null);
            }
        } catch (error) {
            if (!controller.signal.aborted && sequence === requestSequence.current) {
                setRequestError(localizedErrorMessage(error, t("prompts.import.errors.preview")));
            }
        } finally {
            if (!controller.signal.aborted && sequence === requestSequence.current) setPreviewing(false);
        }
    }

    async function handleCommit() {
        if (!canCommitPromptImportForClient(state, clientId) || !state.file || !state.preview) return;
        previewController.current?.abort();
        const sequence = ++requestSequence.current;
        const controller = new AbortController();
        previewController.current = controller;
        setCommitting(true);
        setRequestError("");
        try {
            const result = await commitPromptImport(clientId, state.file, state.preview, { signal: controller.signal });
            if (controller.signal.aborted || sequence !== requestSequence.current) return;
            setState((current) => isPromptImportStateOwned(current, clientId) ? applyCommittedImport(current, result) : current);
            setConfirmCommitOpen(false);
            setResultOpen(true);
            onImported();
        } catch (error) {
            if (controller.signal.aborted || sequence !== requestSequence.current) return;
            setConfirmCommitOpen(false);
            if (error instanceof PromptImportApiError && error.status === 409 && error.preview) {
                setState((current) => isPromptImportStateOwned(current, clientId) ? applyStalePreview(current, error.preview!) : current);
                setPreviewPage(0);
                setExpandedPreviewRow(null);
                setRequestError(t("prompts.import.stale.message"));
                toast.warning(t("prompts.import.stale.toast"));
            } else {
                setRequestError(localizedErrorMessage(error, t("prompts.import.errors.commit")));
            }
        } finally {
            if (!controller.signal.aborted && sequence === requestSequence.current) setCommitting(false);
        }
    }

    async function handleUndo() {
        if (!isPromptImportStateOwned(state, clientId) || !state.committed) return;
        const controller = new AbortController();
        miscControllers.current.add(controller);
        setUndoing(true);
        try {
            const result = await undoPromptImport(clientId, state.committed.batch_id, { signal: controller.signal });
            if (controller.signal.aborted) return;
            setState((current) => isPromptImportStateOwned(current, clientId) ? applyUndoResult(current, result) : current);
            setUndoConfirmOpen(false);
            onImported();
            toast.success(t("prompts.import.result.undoSuccess", { count: result.deleted }));
        } catch (error) {
            if (!controller.signal.aborted) toast.error(localizedErrorMessage(error, t("prompts.import.errors.undo")));
        } finally {
            miscControllers.current.delete(controller);
            if (!controller.signal.aborted) setUndoing(false);
        }
    }

    async function downloadTemplate() {
        const readiness = getTemplateDownloadReadiness({
            ownerClientId: allowedOwnerClientId,
            locale: allowedOwnerLocale,
            loading: allowedLoading,
            error: allowedError,
            allowed,
        }, clientId, locale);
        if (readiness === "wait" || readiness === "stale") return;
        if (readiness === "error") {
            toast.error(allowedError || t("prompts.import.errors.allowedValues"));
            return;
        }
        const controller = new AbortController();
        miscControllers.current.add(controller);
        setDownloadingTemplate(true);
        try {
            saveDownload(await downloadPromptImportTemplate(clientId, { signal: controller.signal }));
            if (readiness === "ready-empty") {
                toast.warning(t("prompts.import.template.noTopic"));
            }
        } catch (error) {
            if (!controller.signal.aborted) toast.error(localizedErrorMessage(error, t("prompts.import.errors.download")));
        } finally {
            miscControllers.current.delete(controller);
            if (!controller.signal.aborted) setDownloadingTemplate(false);
        }
    }

    async function downloadAllowedValues() {
        if (allowedOwnerClientId !== clientId || allowedOwnerLocale !== locale || !allowed) return;
        const controller = new AbortController();
        miscControllers.current.add(controller);
        setDownloadingAllowed(true);
        try {
            saveDownload(await downloadPromptImportAllowedValues(clientId, locale, { signal: controller.signal }));
        } catch (error) {
            if (!controller.signal.aborted) toast.error(localizedErrorMessage(error, t("prompts.import.errors.download")));
        } finally {
            miscControllers.current.delete(controller);
            if (!controller.signal.aborted) setDownloadingAllowed(false);
        }
    }

    const stateOwned = isPromptImportStateOwned(state, clientId);
    const ownedState = getOwnedPromptImportState(state, clientId);
    const allowedOwned = allowedOwnerClientId === clientId && allowedOwnerLocale === locale;
    const visibleAllowed = getOwnedAllowedValues({
        ownerClientId: allowedOwnerClientId,
        locale: allowedOwnerLocale,
        allowed,
    }, clientId, locale);
    const visibleAllowedError = allowedOwned ? allowedError : "";
    const visibleAllowedLoading = allowedOwned ? allowedLoading : true;
    const templateReadiness = getTemplateDownloadReadiness({
        ownerClientId: allowedOwnerClientId,
        locale: allowedOwnerLocale,
        loading: allowedLoading,
        error: allowedError,
        allowed,
    }, clientId, locale);
    const summary = ownedState.preview ? summarizePromptImport(ownedState.preview) : null;
    const commitEnabled = canCommitPromptImportForClient(state, clientId) && !previewing && !committing;

    return (
        <>
            <Dialog open={open} onOpenChange={handleOpenChange}>
                <DialogContent className="max-h-[92vh] max-w-6xl overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>{t("prompts.import.title")}</DialogTitle>
                        <DialogDescription>{t("prompts.import.description")}</DialogDescription>
                        <p className="text-sm font-medium text-foreground">
                            {t("prompts.import.workspace", { workspace: workspaceName })}
                        </p>
                    </DialogHeader>

                    <Tabs value={tab} onValueChange={setTab}>
                        <TabsList>
                            <TabsTrigger value="import">{t("prompts.import.tabs.import")}</TabsTrigger>
                            <TabsTrigger value="allowed">{t("prompts.import.tabs.allowed")}</TabsTrigger>
                        </TabsList>
                        <TabsContent value="import" className="space-y-4">
                            <div className="flex flex-wrap gap-2">
                                <Button
                                    variant="outline"
                                    onClick={() => void downloadTemplate()}
                                    disabled={downloadingTemplate || templateReadiness === "wait" || templateReadiness === "stale"}
                                >
                                    {downloadingTemplate ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
                                    {t("prompts.import.template.download")}
                                </Button>
                                <Button variant="ghost" onClick={() => setTab("allowed")}>{t("prompts.import.template.viewAllowed")}</Button>
                            </div>

                            <input
                                ref={inputRef}
                                id={inputId}
                                type="file"
                                accept=".csv,text/csv"
                                className="sr-only"
                                onChange={(event) => {
                                    const file = event.target.files?.[0] || null;
                                    void selectFile(file);
                                    event.target.value = "";
                                }}
                            />
                            <label
                                htmlFor={inputId}
                                className={`flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-5 text-center transition-colors ${dragActive ? "border-primary bg-primary/5" : "border-muted-foreground/30 hover:border-primary/60"}`}
                                onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }}
                                onDragOver={(event) => event.preventDefault()}
                                onDragLeave={(event) => { event.preventDefault(); setDragActive(false); }}
                                onDrop={(event) => {
                                    event.preventDefault();
                                    setDragActive(false);
                                    void selectFile(event.dataTransfer.files?.[0] || null);
                                }}
                            >
                                <UploadCloud className="mb-2 h-7 w-7 text-muted-foreground" />
                                <span className="text-sm font-medium">{t("prompts.import.file.drop")}</span>
                                <span className="mt-1 text-xs text-muted-foreground">{t("prompts.import.file.limits")}</span>
                            </label>

                            {ownedState.file && (
                                <div className="flex items-center gap-3 rounded-md border bg-muted/20 px-3 py-2">
                                    <FileText className="h-5 w-5 text-primary" />
                                    <div className="min-w-0 flex-1">
                                        <div className="truncate text-sm font-medium">{ownedState.file.name}</div>
                                        <div className="text-xs text-muted-foreground">{t("prompts.import.file.size", { size: (ownedState.file.size / 1024).toFixed(1) })}</div>
                                    </div>
                                    <Button variant="ghost" size="sm" onClick={() => void selectFile(null)}>{t("prompts.import.file.remove")}</Button>
                                </div>
                            )}

                            {stateOwned && previewing && <div className="flex items-center justify-center gap-2 rounded-md border p-5 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t("prompts.import.preview.loading")}</div>}
                            {stateOwned && requestError && (
                                <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                                    <span>{requestError}</span>
                                </div>
                            )}

                            {ownedState.preview && summary && (
                                <div className="space-y-4">
                                    {ownedState.previewStale && (
                                        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                                            <span className="text-sm">{t("prompts.import.stale.review")}</span>
                                            <Button size="sm" variant="outline" onClick={() => {
                                                setState((current) => isPromptImportStateOwned(current, clientId) && current.preview ? applyPreview(current, current.preview) : current);
                                                setRequestError("");
                                            }}>
                                                <RotateCcw className="mr-2 h-4 w-4" />{t("prompts.import.stale.confirm")}
                                            </Button>
                                        </div>
                                    )}
                                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
                                        {([
                                            ["inputRows", summary.inputRows],
                                            ["expanded", summary.expandedVariants],
                                            ["create", summary.create],
                                            ["skip", summary.skip],
                                            ["conflict", summary.conflict],
                                            ["invalid", summary.invalid],
                                            ["quota", `${summary.quotaBefore} → ${summary.quotaAfter} / ${summary.quotaLimit}`],
                                        ] as const).map(([key, value]) => (
                                            <div key={key} className="rounded-md border bg-card p-3">
                                                <div className="text-xs text-muted-foreground">{t(`prompts.import.summary.${key}`)}</div>
                                                <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
                                            </div>
                                        ))}
                                    </div>
                                    <ImportPreviewTable
                                        rows={ownedState.preview.rows}
                                        page={previewPage}
                                        onPageChange={(page) => {
                                            setPreviewPage(page);
                                            setExpandedPreviewRow(null);
                                        }}
                                        expandedRowNumber={expandedPreviewRow}
                                        onExpandedRowChange={setExpandedPreviewRow}
                                    />
                                </div>
                            )}
                        </TabsContent>
                        <TabsContent value="allowed">
                            <AllowedValuesTable
                                key={allowedValuesWorkspaceKey(clientId)}
                                rows={visibleAllowed?.rows || []}
                                loading={visibleAllowedLoading}
                                error={visibleAllowedError}
                                downloading={downloadingAllowed}
                                onRetry={() => setAllowedReload((value) => value + 1)}
                                onDownload={() => void downloadAllowedValues()}
                            />
                        </TabsContent>
                    </Tabs>

                    <DialogFooter>
                        <Button variant="outline" onClick={() => handleOpenChange(false)}>{t("common:actions.close")}</Button>
                        <Button onClick={() => setConfirmCommitOpen(true)} disabled={!commitEnabled}>
                            {committing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileUp className="mr-2 h-4 w-4" />}
                            {t("prompts.import.commit.button")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={stateOwned && confirmCommitOpen} onOpenChange={(next) => !committing && setConfirmCommitOpen(next)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t("prompts.import.commit.confirmTitle")}</DialogTitle>
                        <DialogDescription>{t("prompts.import.commit.confirmDescription", { count: summary?.create || 0 })}</DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setConfirmCommitOpen(false)} disabled={committing}>{t("common:actions.cancel")}</Button>
                        <Button onClick={() => void handleCommit()} disabled={committing}>
                            {committing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t("common:actions.confirm")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={stateOwned && resultOpen} onOpenChange={setResultOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t("prompts.import.result.title")}</DialogTitle>
                        <DialogDescription>{t("prompts.import.result.description", { count: ownedState.committed?.created || 0 })}</DialogDescription>
                    </DialogHeader>
                    {ownedState.committed && (
                        <div className="space-y-3 rounded-md border p-4">
                            <div className="flex justify-between gap-3 text-sm"><span className="text-muted-foreground">{t("prompts.import.result.batch")}</span><code className="break-all text-right">{ownedState.committed.batch_id}</code></div>
                            <div className="flex justify-between gap-3 text-sm"><span className="text-muted-foreground">{t("prompts.import.result.created")}</span><strong>{ownedState.committed.created}</strong></div>
                            <div className="flex justify-between gap-3 text-sm"><span className="text-muted-foreground">{t("prompts.import.result.skipped")}</span><strong>{ownedState.committed.preview.action_counts.skip}</strong></div>
                            {ownedState.undoResult && <Badge variant="secondary">{t("prompts.import.result.reverted", { count: ownedState.undoResult.deleted })}</Badge>}
                        </div>
                    )}
                    <DialogFooter>
                        {!ownedState.undoResult && ownedState.committed && (
                            <Button variant="destructive" onClick={() => setUndoConfirmOpen(true)}>{t("prompts.import.result.undo")}</Button>
                        )}
                        <Button variant="outline" onClick={() => setResultOpen(false)}>{t("common:actions.close")}</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={stateOwned && undoConfirmOpen} onOpenChange={(next) => !undoing && setUndoConfirmOpen(next)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t("prompts.import.undo.title")}</DialogTitle>
                        <DialogDescription>{t("prompts.import.undo.description")}</DialogDescription>
                    </DialogHeader>
                    <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{t("prompts.import.undo.cascadeWarning")}
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setUndoConfirmOpen(false)} disabled={undoing}>{t("common:actions.cancel")}</Button>
                        <Button variant="destructive" onClick={() => void handleUndo()} disabled={undoing}>
                            {undoing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t("prompts.import.undo.confirm")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}
