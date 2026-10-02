import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { batchCreatePrompts, batchDeletePrompts } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select as UISelect, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Search, Check, X, MoreHorizontal, Copy, Trash2, Pause } from "lucide-react";
import type { GlobalLanguage, GlobalPlatform } from "./types";
import { getManualPromptDeleteBatchSize } from "@/lib/workspaceCleanup";
import {
    buildLogicalPromptKey,
    canRemoveLogicalPromptDimensionVariants,
    resolveCanonicalIntent,
} from "../insights/promptIntentFilter";

interface PromptTableProps {
    prompts: any[];
    showNewRows?: boolean;
    newRows: any[];
    setNewRows: React.Dispatch<React.SetStateAction<any[]>>;
    selectedRows: string[];
    setSelectedRows: React.Dispatch<React.SetStateAction<string[]>>;
    pendingEdits: Record<string, Record<string, any>>;
    activeClient: any;
    availableCountries: string[];
    availableLanguages: GlobalLanguage[];
    availablePlatforms: GlobalPlatform[];
    activeIntents: string[];
    validateIntentForWrite: (intent: string | null | undefined) => boolean;
    ensureWorkspaceStateOwned: () => boolean;
    isWorkspaceStateOwned: () => boolean;
    clientId: string;
    load: () => void;
    editField: (id: string, field: string, value: any) => void;
    getEditValue: (prompt: any, field: string) => any;
    toggleAll: (prompts: any[]) => void;
    handleDuplicatePrompt: (prompt: any) => void;
    handleBulkSetStatus: (ids: string[], isActive: boolean) => void | Promise<void>;
    confirmDialog: (message: string, title?: string) => Promise<boolean>;
}

export function PromptTable({
    prompts,
    showNewRows = false,
    newRows,
    setNewRows,
    selectedRows,
    setSelectedRows,
    pendingEdits,
    activeClient,
    availableCountries,
    availableLanguages,
    availablePlatforms,
    activeIntents,
    validateIntentForWrite,
    ensureWorkspaceStateOwned,
    isWorkspaceStateOwned,
    clientId,
    load,
    editField,
    getEditValue,
    toggleAll,
    handleDuplicatePrompt,
    handleBulkSetStatus,
    confirmDialog,
}: PromptTableProps) {
    const { t } = useTranslation("insights");

    async function deleteOrdinaryPromptBatch(promptIds: string[]): Promise<boolean> {
        const batchSize = getManualPromptDeleteBatchSize(promptIds.length);
        if (batchSize == null) {
            toast.warning(t("promptEditor.toasts.bulkDeleteTooLarge", { max: 100 }));
            return false;
        }
        await batchDeletePrompts(clientId, promptIds, batchSize);
        return true;
    }
    const allRows = showNewRows ? [...newRows, ...prompts] : prompts;
    return (
        <div className="rounded-md border bg-card overflow-x-auto">
            <Table>
                <TableHeader>
                    <TableRow className="bg-muted/20">
                        <TableHead className="w-[40px] px-4">
                            <Checkbox
                                checked={prompts.length > 0 && selectedRows.length === prompts.length}
                                onCheckedChange={() => toggleAll(prompts)}
                            />
                        </TableHead>
                        <TableHead className="min-w-[250px]">{t("promptEditor.columns.promptText")}</TableHead>
                        <TableHead className="w-[120px]">{t("promptEditor.columns.topic")}</TableHead>
                        <TableHead className="w-[100px]">{t("promptEditor.columns.product")}</TableHead>
                        <TableHead className="w-[100px]">{t("promptEditor.columns.country")}</TableHead>
                        <TableHead className="w-[120px]">{t("promptEditor.columns.language")}</TableHead>
                        <TableHead className="w-[120px]">{t("promptEditor.columns.platform")}</TableHead>
                        <TableHead className="w-[100px]">{t("promptEditor.columns.intent")}</TableHead>
                        <TableHead className="text-right w-[60px]"></TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {/* New Rows (unsaved) */}
                    {showNewRows && newRows.map((nr, idx) => {
                        const selectedTopic = (activeClient?.topics as any[])?.find((tp: any) => tp.id === nr.topic_id);
                        const productOptions: string[] = selectedTopic?.products || [];
                        return (
                            <TableRow key={nr._tempId} className="border-l-4 border-l-amber-400 bg-amber-50/30 dark:bg-amber-950/10">
                                <TableCell className="px-4">
                                    <Badge variant="outline" className="text-[9px] px-1 py-0 bg-amber-100 text-amber-700 border-amber-300">{t("promptEditor.newBadge")}</Badge>
                                </TableCell>
                                <TableCell>
                                    <Input
                                        className="h-8 text-sm"
                                        placeholder={t("promptEditor.enterPrompt")}
                                        value={nr.text}
                                        autoFocus={idx === 0}
                                        onChange={(e) => setNewRows(prev => prev.map(r => r._tempId === nr._tempId ? { ...r, text: e.target.value } : r))}
                                    />
                                </TableCell>
                                <TableCell>
                                    <UISelect value={nr.topic_id || ""} onValueChange={(v) => setNewRows(prev => prev.map(r => r._tempId === nr._tempId ? { ...r, topic_id: v, product: "" } : r))}>
                                        <SelectTrigger className="h-7 text-xs w-full"><SelectValue placeholder={t("promptEditor.selectPlaceholder")} /></SelectTrigger>
                                        <SelectContent>
                                            {(activeClient?.topics as any[] || []).map((tp: any) => <SelectItem key={tp.id} value={tp.id}>{tp.topic_name}</SelectItem>)}
                                        </SelectContent>
                                    </UISelect>
                                </TableCell>
                                <TableCell>
                                    <UISelect value={nr.product || ""} onValueChange={(v) => setNewRows(prev => prev.map(r => r._tempId === nr._tempId ? { ...r, product: v } : r))}>
                                        <SelectTrigger className="h-7 text-xs w-full"><SelectValue placeholder={t("promptEditor.selectPlaceholder")} /></SelectTrigger>
                                        <SelectContent>
                                            {productOptions.map(prod => <SelectItem key={prod} value={prod}>{prod}</SelectItem>)}
                                        </SelectContent>
                                    </UISelect>
                                </TableCell>
                                <TableCell>
                                    <Popover>
                                        <PopoverTrigger asChild>
                                            <button className="flex flex-wrap gap-1 items-center min-h-[28px] px-1 py-0.5 rounded-md border border-input transition-colors cursor-pointer w-full text-left">
                                                {(nr.countries || []).length === 0
                                                    ? <span className="text-xs text-muted-foreground">{t("promptEditor.selectPlaceholder")}</span>
                                                    : (nr.countries || []).map((c: string) => <Badge key={c} variant="secondary" className="text-[10px] h-5 px-1.5">{c}</Badge>)
                                                }
                                            </button>
                                        </PopoverTrigger>
                                        <PopoverContent className="w-56 p-2" align="start">
                                            <div className="space-y-1">
                                                <div className="flex items-center gap-2 px-2 py-1.5 border-b mb-1">
                                                    <Search className="h-3.5 w-3.5 text-muted-foreground" />
                                                    <input className="text-sm bg-transparent outline-none w-full" placeholder={t("promptEditor.searchCountries")} />
                                                </div>
                                                {availableCountries.map(c => {
                                                    const checked = (nr.countries || []).includes(c);
                                                    return (
                                                        <button key={c} className="flex items-center gap-2 w-full px-2 py-1.5 text-sm rounded-sm hover:bg-muted/50 transition-colors" onClick={() => {
                                                            setNewRows(prev => prev.map(r => r._tempId === nr._tempId ? { ...r, countries: checked ? r.countries.filter((x: string) => x !== c) : [...(r.countries || []), c] } : r));
                                                        }}>
                                                            <div className={`h-4 w-4 rounded border flex items-center justify-center ${checked ? 'bg-primary border-primary text-primary-foreground' : 'border-input'}`}>
                                                                {checked && <Check className="h-3 w-3" />}
                                                            </div>
                                                            {c}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </PopoverContent>
                                    </Popover>
                                </TableCell>
                                <TableCell>
                                    <UISelect value={nr.language} onValueChange={(v) => setNewRows(prev => prev.map(r => r._tempId === nr._tempId ? { ...r, language: v } : r))}>
                                        <SelectTrigger className="h-7 text-xs w-full"><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            {availableLanguages.map(l => <SelectItem key={l.language_code} value={l.language_code}>{l.language}</SelectItem>)}
                                        </SelectContent>
                                    </UISelect>
                                </TableCell>
                                <TableCell>
                                    <Popover>
                                        <PopoverTrigger asChild>
                                            <button className="flex flex-wrap gap-1 items-center min-h-[28px] px-1 py-0.5 rounded-md border border-input transition-colors cursor-pointer w-full text-left">
                                                {(nr.platforms || []).length === 0
                                                    ? <span className="text-xs text-muted-foreground">{t("promptEditor.selectPlaceholder")}</span>
                                                    : (nr.platforms || []).map((pl: string) => {
                                                        const plObj = availablePlatforms.find(p => p.platform_id === pl);
                                                        return <Badge key={pl} variant="secondary" className="text-[10px] h-5 px-1.5">{plObj?.display_name || pl}</Badge>;
                                                    })
                                                }
                                            </button>
                                        </PopoverTrigger>
                                        <PopoverContent className="w-56 p-2" align="start">
                                            <div className="space-y-1">
                                                <div className="flex items-center gap-2 px-2 py-1.5 border-b mb-1">
                                                    <Search className="h-3.5 w-3.5 text-muted-foreground" />
                                                    <input className="text-sm bg-transparent outline-none w-full" placeholder={t("promptEditor.searchPlatforms")} />
                                                </div>
                                                {availablePlatforms.map(pl => {
                                                    const checked = (nr.platforms || []).includes(pl.platform_id);
                                                    return (
                                                        <button key={pl.platform_id} className="flex items-center gap-2 w-full px-2 py-1.5 text-sm rounded-sm hover:bg-muted/50 transition-colors" onClick={() => {
                                                            setNewRows(prev => prev.map(r => r._tempId === nr._tempId ? { ...r, platforms: checked ? r.platforms.filter((x: string) => x !== pl.platform_id) : [...(r.platforms || []), pl.platform_id] } : r));
                                                        }}>
                                                            <div className={`h-4 w-4 rounded border flex items-center justify-center ${checked ? 'bg-primary border-primary text-primary-foreground' : 'border-input'}`}>
                                                                {checked && <Check className="h-3 w-3" />}
                                                            </div>
                                                            {pl.display_name}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        </PopoverContent>
                                    </Popover>
                                </TableCell>
                                <TableCell>
                                    <UISelect value={nr.intent || ""} onValueChange={(v) => setNewRows(prev => prev.map(r => r._tempId === nr._tempId ? { ...r, intent: v } : r))}>
                                        <SelectTrigger className="h-7 text-xs w-full"><SelectValue placeholder={t("promptEditor.selectPlaceholder")} /></SelectTrigger>
                                        <SelectContent>
                                            {activeIntents.map((intent) => <SelectItem key={intent} value={intent}>{intent}</SelectItem>)}
                                        </SelectContent>
                                    </UISelect>
                                </TableCell>
                                <TableCell className="text-right">
                                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setNewRows(prev => prev.filter(r => r._tempId !== nr._tempId))}>
                                        <X className="h-3.5 w-3.5" />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        );
                    })}

                    {/* Existing Rows (merged by text+topic) */}
                    {(() => {
                        // Group prompts by text + topic_id
                        const groups: Record<string, any[]> = {};
                        for (const p of prompts) {
                            const key = buildLogicalPromptKey(p, clientId, activeIntents);
                            if (!groups[key]) groups[key] = [];
                            groups[key].push(p);
                        }
                        return Object.entries(groups).map(([groupKey, groupPrompts]) => {
                            const first = groupPrompts[0];
                            const groupCountries = [...new Set(groupPrompts.map(p => p.country))];
                            const groupPlatforms = [...new Set(groupPrompts.map(p => p.platform))];
                            const allIds = groupPrompts.map(p => p.id);
                            const isChecked = allIds.some(id => selectedRows.includes(id));
                            const hasEdits = allIds.some(id => !!pendingEdits[id]);

                            // Toggle country: add or remove a prompt record
                            const toggleCountry = async (country: string) => {
                                if (!ensureWorkspaceStateOwned()) return;
                                const existing = groupPrompts.filter(p => p.country === country);
                                if (existing.length > 0) {
                                    // Remove all variants for this country in one request.
                                    if (!canRemoveLogicalPromptDimensionVariants(groupCountries.length, existing.length, groupPrompts.length)) {
                                        toast.warning(t("promptEditor.rowActions.cannotRemoveLastCountry"));
                                        return;
                                    }
                                    if (!await confirmDialog(
                                        t("promptEditor.rowActions.removeCountryVariantsMessage", { country, count: existing.length }),
                                        t("promptEditor.rowActions.removeCountryVariantsTitle"),
                                    )) return;
                                    if (!isWorkspaceStateOwned()) return;
                                    try {
                                        if (!await deleteOrdinaryPromptBatch(existing.map(p => p.id))) return;
                                        if (!isWorkspaceStateOwned()) return;
                                        load();
                                    } catch (err: any) { if (isWorkspaceStateOwned()) toast.error(err.message); }
                                } else {
                                    // Add – clone from first prompt with the new country
                                    if (!validateIntentForWrite(first.intent)) return;
                                    const canonicalIntent = resolveCanonicalIntent(first.intent, activeIntents);
                                    if (!canonicalIntent) return;
                                    try {
                                        await batchCreatePrompts(clientId, [{
                                            text: first.text,
                                            topic_id: first.topic_id,
                                            product: first.product || "",
                                            countries: [country],
                                            language: first.language,
                                            platforms: groupPlatforms,
                                            intent: canonicalIntent,
                                        }]);
                                        if (!isWorkspaceStateOwned()) return;
                                        load();
                                    } catch (err: any) { if (isWorkspaceStateOwned()) toast.error(err.message); }
                                }
                            };

                            // Toggle platform: add or remove prompt records
                            const togglePlatform = async (platform: string) => {
                                if (!ensureWorkspaceStateOwned()) return;
                                const existing = groupPrompts.filter(p => p.platform === platform);
                                if (existing.length > 0) {
                                    // Remove all with this platform
                                    if (!canRemoveLogicalPromptDimensionVariants(groupPlatforms.length, existing.length, groupPrompts.length)) {
                                        toast.warning(t("promptEditor.rowActions.cannotRemoveLastPlatform"));
                                        return;
                                    }
                                    if (!await confirmDialog(
                                        t("promptEditor.rowActions.removePlatformVariantsMessage", { platform, count: existing.length }),
                                        t("promptEditor.rowActions.removePlatformVariantsTitle"),
                                    )) return;
                                    if (!isWorkspaceStateOwned()) return;
                                    try {
                                        if (!await deleteOrdinaryPromptBatch(existing.map(p => p.id))) return;
                                        if (!isWorkspaceStateOwned()) return;
                                        load();
                                    } catch (err: any) { if (isWorkspaceStateOwned()) toast.error(err.message); }
                                } else {
                                    // Add one record for each country
                                    if (!validateIntentForWrite(first.intent)) return;
                                    const canonicalIntent = resolveCanonicalIntent(first.intent, activeIntents);
                                    if (!canonicalIntent) return;
                                    try {
                                        await batchCreatePrompts(clientId, [{
                                            text: first.text,
                                            topic_id: first.topic_id,
                                            product: first.product || "",
                                            countries: groupCountries,
                                            language: first.language,
                                            platforms: [platform],
                                            intent: canonicalIntent,
                                        }]);
                                        if (!isWorkspaceStateOwned()) return;
                                        load();
                                    } catch (err: any) { if (isWorkspaceStateOwned()) toast.error(err.message); }
                                }
                            };

                            return (
                                <TableRow key={groupKey} className={hasEdits ? 'border-l-4 border-l-amber-400 bg-amber-50/20 dark:bg-amber-950/5' : ''}>
                                    <TableCell className="px-4">
                                        <Checkbox
                                            checked={isChecked}
                                            onCheckedChange={() => {
                                                setSelectedRows(prev => {
                                                    const allSelected = allIds.every(id => prev.includes(id));
                                                    return allSelected
                                                        ? prev.filter(id => !allIds.includes(id))
                                                        : [...new Set([...prev, ...allIds])];
                                                });
                                            }}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        <Input
                                            className="h-8 text-sm border-transparent hover:border-input focus:border-input transition-colors bg-transparent"
                                            value={getEditValue(first, 'text')}
                                            onChange={(e) => {
                                                // Edit text on all group members
                                                for (const gp of groupPrompts) editField(gp.id, 'text', e.target.value);
                                            }}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        <Badge variant="outline" className="text-xs">
                                            {(activeClient?.topics as any[])?.find((tp: any) => tp.id === first.topic_id)?.topic_name || "—"}
                                        </Badge>
                                    </TableCell>
                                    <TableCell>
                                        <span className="text-xs text-muted-foreground">{first.product || "—"}</span>
                                    </TableCell>
                                    {/* Country multi-select popover */}
                                    <TableCell>
                                        <Popover>
                                            <PopoverTrigger asChild>
                                                <button className="flex flex-wrap gap-1 items-center min-h-[28px] px-1 py-0.5 rounded-md border border-transparent hover:border-input transition-colors cursor-pointer w-full text-left">
                                                    {groupCountries.map(c => (
                                                        <Badge key={c} variant="secondary" className="text-[10px] h-5 px-1.5">{c}</Badge>
                                                    ))}
                                                </button>
                                            </PopoverTrigger>
                                            <PopoverContent className="w-56 p-2" align="start">
                                                <div className="space-y-1">
                                                    <div className="flex items-center gap-2 px-2 py-1.5 border-b mb-1">
                                                        <Search className="h-3.5 w-3.5 text-muted-foreground" />
                                                        <input className="text-sm bg-transparent outline-none w-full" placeholder={t("promptEditor.searchCountries")} />
                                                    </div>
                                                    {availableCountries.map(c => {
                                                        const checked = groupCountries.includes(c);
                                                        return (
                                                            <button key={c} className="flex items-center gap-2 w-full px-2 py-1.5 text-sm rounded-sm hover:bg-muted/50 transition-colors" onClick={() => toggleCountry(c)}>
                                                                <div className={`h-4 w-4 rounded border flex items-center justify-center ${checked ? 'bg-primary border-primary text-primary-foreground' : 'border-input'}`}>
                                                                    {checked && <Check className="h-3 w-3" />}
                                                                </div>
                                                                {c}
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            </PopoverContent>
                                        </Popover>
                                    </TableCell>
                                    <TableCell>
                                        <span className="text-xs text-muted-foreground">{first.language}</span>
                                    </TableCell>
                                    {/* Platform multi-select popover */}
                                    <TableCell>
                                        <Popover>
                                            <PopoverTrigger asChild>
                                                <button className="flex flex-wrap gap-1 items-center min-h-[28px] px-1 py-0.5 rounded-md border border-transparent hover:border-input transition-colors cursor-pointer w-full text-left">
                                                    {groupPlatforms.map(pl => {
                                                        const plObj = availablePlatforms.find(p => p.platform_id === pl);
                                                        return <Badge key={pl} variant="secondary" className="text-[10px] h-5 px-1.5">{plObj?.display_name || pl}</Badge>;
                                                    })}
                                                </button>
                                            </PopoverTrigger>
                                            <PopoverContent className="w-56 p-2" align="start">
                                                <div className="space-y-1">
                                                    <div className="flex items-center gap-2 px-2 py-1.5 border-b mb-1">
                                                        <Search className="h-3.5 w-3.5 text-muted-foreground" />
                                                        <input className="text-sm bg-transparent outline-none w-full" placeholder={t("promptEditor.searchPlatforms")} />
                                                    </div>
                                                    {availablePlatforms.map(pl => {
                                                        const checked = groupPlatforms.includes(pl.platform_id);
                                                        return (
                                                            <button key={pl.platform_id} className="flex items-center gap-2 w-full px-2 py-1.5 text-sm rounded-sm hover:bg-muted/50 transition-colors" onClick={() => togglePlatform(pl.platform_id)}>
                                                                <div className={`h-4 w-4 rounded border flex items-center justify-center ${checked ? 'bg-primary border-primary text-primary-foreground' : 'border-input'}`}>
                                                                    {checked && <Check className="h-3 w-3" />}
                                                                </div>
                                                                {pl.display_name}
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            </PopoverContent>
                                        </Popover>
                                    </TableCell>
                                    <TableCell>
                                        {(() => {
                                            const currentIntent = getEditValue(first, "intent") as string | null | undefined;
                                            const canonicalIntent = resolveCanonicalIntent(currentIntent, activeIntents);
                                            return (
                                                <div className="space-y-1">
                                                    <UISelect
                                                        value={canonicalIntent ?? ""}
                                                        onValueChange={(intent) => {
                                                            if (!ensureWorkspaceStateOwned()) return;
                                                            allIds.forEach((id) => editField(id, "intent", intent));
                                                        }}
                                                    >
                                                        <SelectTrigger className="h-7 w-full text-xs" aria-label={t("promptEditor.intentConfig.selectActiveLabel")}>
                                                            <SelectValue placeholder={t("promptEditor.intentConfig.selectActivePlaceholder")} />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            {activeIntents.map((intent) => (
                                                                <SelectItem key={intent} value={intent}>{intent}</SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </UISelect>
                                                    {!canonicalIntent && (
                                                        <div className="flex flex-wrap gap-1">
                                                            <Badge variant="outline" className="text-[10px] h-5 px-1.5 text-muted-foreground">
                                                                {currentIntent?.trim() || t("promptEditor.intentConfig.blankValue")}
                                                            </Badge>
                                                            <Badge variant="destructive" className="text-[10px] h-5 px-1.5">
                                                                {t("promptEditor.intentConfig.needsActiveSelection")}
                                                            </Badge>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })()}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <DropdownMenu>
                                            <DropdownMenuTrigger asChild>
                                                <Button variant="ghost" size="icon" className="h-7 w-7">
                                                    <MoreHorizontal className="h-4 w-4" />
                                                </Button>
                                            </DropdownMenuTrigger>
                                            <DropdownMenuContent align="end" className="w-40">
                                                <DropdownMenuItem onClick={() => handleDuplicatePrompt(first)}>
                                                    <Copy className="h-3.5 w-3.5 mr-2" /> {t("promptEditor.rowActions.duplicate")}
                                                </DropdownMenuItem>
                                                <DropdownMenuItem onClick={() => handleBulkSetStatus(allIds, !first.is_active)}>
                                                    <Pause className="h-3.5 w-3.5 mr-2" /> {first.is_active ? t("promptEditor.rowActions.pause") : t("promptEditor.rowActions.activate")}
                                                </DropdownMenuItem>
                                                <DropdownMenuSeparator />
                                                <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={async () => {
                                                    if (!ensureWorkspaceStateOwned()) return;
                                                    if (!await confirmDialog(t("promptEditor.rowActions.deleteConfirmMessage"), t("promptEditor.rowActions.deleteConfirmTitle"))) return;
                                                    if (!isWorkspaceStateOwned()) return;
                                                    if (!await deleteOrdinaryPromptBatch(allIds)) return;
                                                    if (!isWorkspaceStateOwned()) return;
                                                    load();
                                                }}>
                                                    <Trash2 className="h-3.5 w-3.5 mr-2" /> {t("promptEditor.rowActions.deleteAll")}
                                                </DropdownMenuItem>
                                            </DropdownMenuContent>
                                        </DropdownMenu>
                                    </TableCell>
                                </TableRow>
                            );
                        });
                    })()}
                    {allRows.length === 0 && (
                        <TableRow>
                            <TableCell colSpan={10} className="h-32 text-center text-muted-foreground">
                                {t("promptEditor.noInStatus")}
                            </TableCell>
                        </TableRow>
                    )}
                </TableBody>
            </Table>
        </div>
    );
}
