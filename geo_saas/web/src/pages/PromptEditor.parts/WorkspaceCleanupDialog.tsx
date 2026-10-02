import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import {
    isWorkspaceCleanupComplete,
    WorkspaceCleanupError,
    type WorkspaceCleanupProgress,
} from "@/lib/workspaceCleanup";

interface WorkspaceCleanupDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    workspaceName: string;
    currentPhysicalCount: number;
    runCleanup: (onProgress: (progress: WorkspaceCleanupProgress) => void) => Promise<WorkspaceCleanupProgress>;
}

function cleanupErrorMessage(
    error: unknown,
    partialDeleteMessage: string,
    concurrentPromptsMessage: string,
): string {
    if (error instanceof WorkspaceCleanupError) {
        if (error.code === "PARTIAL_DELETE") return partialDeleteMessage;
        if (error.code === "CONCURRENT_PROMPTS_REMAIN") return concurrentPromptsMessage;
    }
    return error instanceof Error ? error.message : String(error || "");
}

export function WorkspaceCleanupDialog({
    open,
    onOpenChange,
    workspaceName,
    currentPhysicalCount,
    runCleanup,
}: WorkspaceCleanupDialogProps) {
    const { t } = useTranslation(["insights", "common"]);
    const [confirmed, setConfirmed] = useState(false);
    const [running, setRunning] = useState(false);
    const [progress, setProgress] = useState<WorkspaceCleanupProgress | null>(null);

    useEffect(() => {
        if (!open) return;
        setConfirmed(false);
        setProgress(null);
    }, [open]);

    async function handleRun(): Promise<void> {
        if (!confirmed || running) return;
        setRunning(true);
        try {
            const finalProgress = await runCleanup(setProgress);
            setProgress(finalProgress);
        } finally {
            setRunning(false);
        }
    }

    const initialRefreshFailed = progress?.status === "failed" && progress.total === 0 && progress.deleted === 0;
    const deleted = progress?.deleted ?? 0;
    const remaining = initialRefreshFailed
        ? currentPhysicalCount
        : progress?.status === "complete" && currentPhysicalCount > 0
            ? currentPhysicalCount
            : (progress?.remaining ?? currentPhysicalCount);
    const total = progress ? Math.max(progress.total, deleted + remaining) : currentPhysicalCount;
    const cleanupComplete = isWorkspaceCleanupComplete(progress, currentPhysicalCount);
    const displayStatus = progress?.status === "complete" && !cleanupComplete
        ? "failed"
        : progress?.status;
    const percentage = total === 0 ? (progress?.status === "complete" ? 100 : 0) : Math.min(100, (deleted / total) * 100);

    return (
        <Dialog open={open} onOpenChange={(nextOpen) => {
            if (!running) onOpenChange(nextOpen);
        }}>
            <DialogContent className="max-w-xl">
                <DialogHeader>
                    <DialogTitle>{t("promptEditor.cleanup.dialogTitle")}</DialogTitle>
                    <DialogDescription>
                        {t("promptEditor.cleanup.dialogDescription", { workspace: workspaceName })}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                    <div className="rounded-md border bg-muted/30 p-4 text-sm">
                        <div className="flex items-center justify-between">
                            <span>{t("promptEditor.cleanup.physicalRows")}</span>
                            <strong className="tabular-nums">{currentPhysicalCount.toLocaleString()}</strong>
                        </div>
                        <p className="mt-2 text-muted-foreground">{t("promptEditor.cleanup.batchExplanation")}</p>
                    </div>

                    <label className="flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm">
                        <Checkbox
                            checked={confirmed}
                            onCheckedChange={(checked) => setConfirmed(checked === true)}
                            disabled={running}
                        />
                        <span>{t("promptEditor.cleanup.confirmation")}</span>
                    </label>

                    {progress && (
                        <div className="space-y-2 rounded-md border p-4" role={displayStatus === "failed" ? "alert" : "status"}>
                            <div className="flex items-center justify-between text-sm">
                                <span className="flex items-center gap-2 font-medium">
                                    {displayStatus === "running" && <Loader2 className="h-4 w-4 animate-spin" />}
                                    {displayStatus === "complete" && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
                                    {displayStatus === "failed" && <AlertTriangle className="h-4 w-4 text-destructive" />}
                                    {displayStatus && t(`promptEditor.cleanup.status.${displayStatus}`)}
                                </span>
                                <span className="tabular-nums">{Math.round(percentage)}%</span>
                            </div>
                            <div className="h-2 overflow-hidden rounded-full bg-muted">
                                <div className="h-full bg-primary transition-all" style={{ width: `${percentage}%` }} />
                            </div>
                            <div className="grid grid-cols-3 gap-2 text-center text-xs">
                                <div><strong className="block text-base">{total}</strong>{t("promptEditor.cleanup.total")}</div>
                                <div><strong className="block text-base text-emerald-600">{deleted}</strong>{t("promptEditor.cleanup.deleted")}</div>
                                <div><strong className="block text-base text-amber-600">{remaining}</strong>{t("promptEditor.cleanup.remaining")}</div>
                            </div>
                            {displayStatus === "failed" && (
                                <p className="text-sm text-destructive">
                                    {progress.status === "failed"
                                        ? t("promptEditor.cleanup.failedMessage", {
                                            message: cleanupErrorMessage(
                                                progress.error,
                                                t("promptEditor.cleanup.partialDelete"),
                                                t("promptEditor.cleanup.concurrentPrompts"),
                                            ),
                                        })
                                        : t("promptEditor.cleanup.remainingAfterRefresh")}
                                </p>
                            )}
                            {cleanupComplete && (
                                <p className="text-sm text-emerald-700 dark:text-emerald-400">{t("promptEditor.cleanup.completeMessage")}</p>
                            )}
                        </div>
                    )}
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={running}>
                        {cleanupComplete ? t("common:actions.close") : t("common:actions.cancel")}
                    </Button>
                    {!cleanupComplete && (
                        <Button variant="destructive" onClick={handleRun} disabled={!confirmed || running}>
                            {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                            {progress ? t("promptEditor.cleanup.resume") : t("promptEditor.cleanup.start")}
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
