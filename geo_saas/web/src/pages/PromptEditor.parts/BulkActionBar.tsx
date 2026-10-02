import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Copy, Pause, Play, Globe, Monitor, Trash2, X } from "lucide-react";
import type { GlobalPlatform } from "./types";

interface BulkActionBarProps {
    selectedRows: string[];
    setSelectedRows: (rows: string[]) => void;
    availableCountries: string[];
    availablePlatforms: GlobalPlatform[];
    statusAction: "disable" | "activate";
    handleBulkDuplicate: () => void;
    handleBulkStatusChange: () => void;
    handleBulkDelete: () => void;
    handleBulkEditField: (field: string, value: string) => void;
}

export function BulkActionBar({
    selectedRows,
    setSelectedRows,
    availableCountries,
    availablePlatforms,
    statusAction,
    handleBulkDuplicate,
    handleBulkStatusChange,
    handleBulkDelete,
    handleBulkEditField,
}: BulkActionBarProps) {
    const { t } = useTranslation("insights");
    const StatusIcon = statusAction === "activate" ? Play : Pause;

    return (
        <div className="fixed bottom-0 left-[15.5rem] right-0 bg-card border-t shadow-lg z-50 px-6 py-3 flex items-center justify-between animate-in slide-in-from-bottom">
            <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={handleBulkDuplicate}>
                    <Copy className="h-3.5 w-3.5" /> {t("promptEditor.bulkActions.duplicate")}
                </Button>
                <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={handleBulkStatusChange}>
                    <StatusIcon className="h-3.5 w-3.5" /> {t(`promptEditor.bulkActions.${statusAction}`)}
                </Button>

                {/* Edit Countries */}
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5">
                            <Globe className="h-3.5 w-3.5" /> {t("promptEditor.bulkActions.editCountries")}
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="max-h-60 overflow-y-auto">
                        {availableCountries.map(c => (
                            <DropdownMenuItem key={c} onClick={() => handleBulkEditField('country', c)}>{c}</DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>

                {/* Edit Platforms */}
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5">
                            <Monitor className="h-3.5 w-3.5" /> {t("promptEditor.bulkActions.editPlatforms")}
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="max-h-60 overflow-y-auto">
                        {availablePlatforms.map(pl => (
                            <DropdownMenuItem key={pl.platform_id} onClick={() => handleBulkEditField('platform', pl.platform_id)}>{pl.display_name}</DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>

                <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5 text-destructive border-destructive/30 hover:bg-destructive/10" onClick={handleBulkDelete}>
                    <Trash2 className="h-3.5 w-3.5" /> {t("promptEditor.bulkActions.delete")}
                </Button>
            </div>

            <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground">{t("promptEditor.bulkActions.promptsSelected", { count: selectedRows.length })}</span>
                <Button variant="ghost" size="sm" className="h-8 text-xs gap-1" onClick={() => setSelectedRows([])}>
                    <X className="h-3.5 w-3.5" /> {t("promptEditor.bulkActions.clear")}
                </Button>
            </div>
        </div>
    );
}
