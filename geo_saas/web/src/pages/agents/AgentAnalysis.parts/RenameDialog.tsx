import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { RunRecord } from "./types";

export function RenameDialog({
    open,
    target,
    value,
    onOpenChange,
    onValueChange,
    onSubmit,
}: {
    open: boolean;
    target: RunRecord | null;
    value: string;
    onOpenChange: (open: boolean) => void;
    onValueChange: (v: string) => void;
    onSubmit: () => void;
}) {
    const { t } = useTranslation("agents");
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-md">
                <DialogHeader>
                    <DialogTitle>{t("analysis.renameDialog.title")}</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 py-2">
                    <div className="space-y-2">
                        <Label htmlFor="rename-input">{t("analysis.renameDialog.nameLabel")}</Label>
                        <Input id="rename-input" value={value} onChange={e => onValueChange(e.target.value)} placeholder={t("analysis.renameDialog.placeholder")} autoFocus />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
                    <Button disabled={!value.trim() || value === target?.task_name} onClick={onSubmit}>{t("common.confirm")}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
