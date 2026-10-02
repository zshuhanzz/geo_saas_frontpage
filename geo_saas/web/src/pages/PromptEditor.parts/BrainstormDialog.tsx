import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select as UISelect, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sparkles, Loader2, ChevronDown, ChevronRight, Globe, Monitor } from "lucide-react";
import { SearchableMultiSelect } from "./SearchableMultiSelect";
import type { CandidatePrompt, GlobalLanguage, GlobalPlatform } from "./types";
import { resolveCanonicalIntent } from "../insights/promptIntentFilter";

interface BrainstormDialogProps {
    brainstormOpen: boolean;
    setBrainstormOpen: (v: boolean) => void;
    activeClient: any;
    bsTopicSelections: Record<string, string[]>;
    bsExpandedTopics: Set<string>;
    toggleTopicSelection: (topicId: string) => void;
    toggleProductSelection: (topicId: string, product: string) => void;
    toggleTopicExpand: (topicId: string) => void;
    selectedTopicCount: number;
    bsCount: string;
    setBsCount: (v: string) => void;
    bsCountries: string[];
    setBsCountries: (v: string[]) => void;
    bsLanguage: string;
    setBsLanguage: (v: string) => void;
    bsPlatforms: string[];
    setBsPlatforms: (v: string[]) => void;
    availableCountries: string[];
    availableLanguages: GlobalLanguage[];
    availablePlatforms: GlobalPlatform[];
    isGenerating: boolean;
    candidates: CandidatePrompt[];
    activeIntents: string[];
    selectedCandidateIntentsValid: boolean;
    selectAllCandidates: (select: boolean) => void;
    toggleCandidate: (index: number) => void;
    updateCandidateIntent: (index: number, intent: string) => void;
    handleStartBrainstorm: () => void;
    handleSaveBrainstorms: () => void;
}

export function BrainstormDialog({
    brainstormOpen,
    setBrainstormOpen,
    activeClient,
    bsTopicSelections,
    bsExpandedTopics,
    toggleTopicSelection,
    toggleProductSelection,
    toggleTopicExpand,
    selectedTopicCount,
    bsCount,
    setBsCount,
    bsCountries,
    setBsCountries,
    bsLanguage,
    setBsLanguage,
    bsPlatforms,
    setBsPlatforms,
    availableCountries,
    availableLanguages,
    availablePlatforms,
    isGenerating,
    candidates,
    activeIntents,
    selectedCandidateIntentsValid,
    selectAllCandidates,
    toggleCandidate,
    updateCandidateIntent,
    handleStartBrainstorm,
    handleSaveBrainstorms,
}: BrainstormDialogProps) {
    const { t } = useTranslation("insights");
    const { t: tCommon } = useTranslation("common");

    return (
        <Dialog open={brainstormOpen} onOpenChange={setBrainstormOpen}>
            <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle className="flex items-center text-xl">
                        <Sparkles className="h-5 w-5 mr-2 text-primary" />
                        {t("promptEditor.brainstorm.dialogTitle")}
                    </DialogTitle>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto pr-2 space-y-5 py-4">
                    <Card className="p-4 shadow-sm border-muted">
                        <h3 className="text-sm font-semibold mb-3">{t("promptEditor.configuration")}</h3>

                        {/* --- Topics & Products Tree --- */}
                        <div className="space-y-2 mb-4">
                            <Label>{t("promptEditor.sidebarTitle")} <span className="text-muted-foreground text-xs ml-1">{t("promptEditor.brainstorm.topicsSelected", { count: selectedTopicCount })}</span></Label>
                            <div className="border rounded-md max-h-[200px] overflow-y-auto divide-y">
                                {(activeClient?.topics || []).map((topic: any) => {
                                    const tid = topic.id;
                                    const isSelected = !!bsTopicSelections[tid];
                                    const isExpanded = bsExpandedTopics.has(tid);
                                    const products: string[] = topic.products || [];
                                    const selectedProducts = bsTopicSelections[tid] || [];
                                    return (
                                        <div key={tid}>
                                            <div className="flex items-center gap-2 px-3 py-2 hover:bg-muted/30 cursor-pointer">
                                                {products.length > 0 && (
                                                    <button onClick={(e) => { e.stopPropagation(); toggleTopicExpand(tid); }} className="p-0.5 hover:bg-muted rounded">
                                                        {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                                                    </button>
                                                )}
                                                {products.length === 0 && <div className="w-[22px]" />}
                                                <Checkbox
                                                    checked={isSelected}
                                                    onCheckedChange={() => toggleTopicSelection(tid)}
                                                />
                                                <span className="text-sm flex-1">{topic.topic_name}</span>
                                                {products.length > 0 && (
                                                    <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                                                        {selectedProducts.length}/{products.length}
                                                    </Badge>
                                                )}
                                            </div>
                                            {isExpanded && products.length > 0 && (
                                                <div className="pl-16 pb-2 space-y-1">
                                                    {products.map((prod: string) => (
                                                        <div key={prod} className="flex items-center gap-2 py-0.5">
                                                            <Checkbox
                                                                checked={selectedProducts.includes(prod)}
                                                                onCheckedChange={() => toggleProductSelection(tid, prod)}
                                                            />
                                                            <span className="text-sm text-muted-foreground">{prod}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                                {(activeClient?.topics || []).length === 0 && (
                                    <div className="p-4 text-center text-sm text-muted-foreground">{t("promptEditor.brainstorm.noTopicsCreated")}</div>
                                )}
                            </div>
                        </div>

                        {/* --- Prompts per Product --- */}
                        <div className="grid grid-cols-1 gap-4 mb-4">
                            <div className="space-y-2">
                                <Label>{t("promptEditor.brainstorm.promptsPerProduct")}</Label>
                                <Input
                                    type="number"
                                    value={bsCount}
                                    onChange={(e) => setBsCount(e.target.value)}
                                    min={1}
                                    max={50}
                                    className="w-40"
                                />
                                <p className="text-[11px] text-muted-foreground">
                                    {t("promptEditor.brainstorm.promptsPerProductHint", { count: bsCount })}
                                </p>
                            </div>
                        </div>

                        {/* --- Countries (Searchable Combobox) --- */}
                        <div className="space-y-2 mb-4">
                            <Label>{t("promptEditor.brainstorm.countries")} {availableCountries.length === 0 && <span className="text-xs text-destructive font-normal ml-1">{t("promptEditor.brainstorm.noneConfigured")}</span>}</Label>
                            <SearchableMultiSelect
                                label={t("promptEditor.brainstorm.labelCountries")}
                                icon={<Globe className="h-4 w-4" />}
                                options={availableCountries.map(c => ({ code: c, name: c }))}
                                selected={bsCountries}
                                onChange={setBsCountries}
                                getOptionLabel={(opt) => opt.name}
                                getOptionValue={(opt) => opt.code}
                                placeholder={availableCountries.length === 0 ? t("promptEditor.brainstorm.noCountriesAvailable") : t("promptEditor.brainstorm.selectCountries")}
                            />
                        </div>

                        {/* --- Language (Single Select) --- */}
                        <div className="space-y-2 mb-4">
                            <Label>{t("promptEditor.brainstorm.language")} {availableLanguages.length === 0 && <span className="text-xs text-destructive font-normal ml-1">{t("promptEditor.brainstorm.noneConfigured")}</span>}</Label>
                            <UISelect value={bsLanguage} onValueChange={setBsLanguage}>
                                <SelectTrigger className="w-full">
                                    <SelectValue placeholder={availableLanguages.length === 0 ? t("promptEditor.brainstorm.noLanguagesAvailable") : t("promptEditor.brainstorm.selectLanguage")} />
                                </SelectTrigger>
                                <SelectContent>
                                    {availableLanguages.map((l) => (
                                        <SelectItem key={l.language_code} value={l.language_code}>
                                            {l.language} ({l.language_code})
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </UISelect>
                        </div>

                        {/* --- Platforms (Searchable Combobox) --- */}
                        <div className="space-y-2">
                            <Label>{t("promptEditor.brainstorm.targetPlatforms")} {availablePlatforms.length === 0 && <span className="text-xs text-destructive font-normal ml-1">{t("promptEditor.brainstorm.noneConfigured")}</span>}</Label>
                            <SearchableMultiSelect
                                label={t("promptEditor.brainstorm.labelPlatforms")}
                                icon={<Monitor className="h-4 w-4" />}
                                options={availablePlatforms}
                                selected={bsPlatforms}
                                onChange={setBsPlatforms}
                                getOptionLabel={(opt) => opt.display_name}
                                getOptionValue={(opt) => opt.platform_id}
                                placeholder={availablePlatforms.length === 0 ? t("promptEditor.brainstorm.noPlatformsAvailable") : t("promptEditor.brainstorm.selectPlatforms")}
                            />
                        </div>

                        <div className="mt-4 flex justify-end">
                            <Button onClick={handleStartBrainstorm} disabled={isGenerating || selectedTopicCount === 0}>
                                {isGenerating ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Sparkles className="h-4 w-4 mr-2" />}
                                {t("promptEditor.generate")}
                            </Button>
                        </div>
                    </Card>

                    {/* --- Candidates Section --- */}
                    {(candidates.length > 0 || isGenerating) && (
                        <div className="space-y-3">
                            <div className="flex justify-between items-center bg-muted/50 p-2 px-3 rounded-md">
                                <span className="text-sm font-semibold">{t("promptEditor.brainstorm.promptsGenerated", { count: candidates.length })}</span>
                                <div className="space-x-2">
                                    <Button variant="link" size="sm" onClick={() => selectAllCandidates(true)}>{t("promptEditor.brainstorm.selectAll")}</Button>
                                    <Button variant="link" size="sm" onClick={() => selectAllCandidates(false)} className="text-muted-foreground">{t("promptEditor.brainstorm.clear")}</Button>
                                </div>
                            </div>

                            <div className="space-y-2 max-h-[40vh] overflow-y-auto pr-2">
                                {candidates.map((c, i) => {
                                    const canonicalIntent = resolveCanonicalIntent(c.intent, activeIntents);
                                    return (
                                    <div
                                        key={i}
                                        className={`p-3 rounded-md border flex items-start gap-3 cursor-pointer hover:border-primary transition-colors ${c.selected ? 'bg-primary/5 border-primary' : 'bg-background'}`}
                                        onClick={() => toggleCandidate(i)}
                                    >
                                        <div className="mt-0.5">
                                            <Checkbox checked={c.selected} />
                                        </div>
                                        <div className="flex-1 space-y-1">
                                            <p className="text-sm leading-snug">{c.text}</p>
                                            <div className="flex gap-1.5 flex-wrap">
                                                <div
                                                    className="flex items-center gap-1.5"
                                                    onClick={(event) => event.stopPropagation()}
                                                    onPointerDown={(event) => event.stopPropagation()}
                                                >
                                                    <UISelect
                                                        value={canonicalIntent ?? ""}
                                                        onValueChange={(intent) => updateCandidateIntent(i, intent)}
                                                    >
                                                        <SelectTrigger
                                                            className="h-7 w-48 text-xs"
                                                            aria-label={t("promptEditor.brainstorm.candidateIntentLabel")}
                                                        >
                                                            <SelectValue placeholder={t("promptEditor.brainstorm.selectActiveIntent")} />
                                                        </SelectTrigger>
                                                        <SelectContent onClick={(event) => event.stopPropagation()}>
                                                            {activeIntents.map((intent) => (
                                                                <SelectItem key={intent} value={intent}>{intent}</SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </UISelect>
                                                    {!canonicalIntent && (
                                                        <>
                                                            <Badge variant="outline" className="text-[10px] h-5 px-1.5 text-muted-foreground">
                                                                {c.intent?.trim() || t("promptEditor.brainstorm.blankIntent")}
                                                            </Badge>
                                                            <Badge variant="destructive" className="text-[10px] h-5 px-1.5">
                                                                {t("promptEditor.brainstorm.intentNeedsSelection")}
                                                            </Badge>
                                                        </>
                                                    )}
                                                </div>
                                                {c.topic_name && <Badge variant="secondary" className="text-[10px] h-4 px-1">{c.topic_name}</Badge>}
                                                {c.product && <Badge variant="secondary" className="text-[10px] h-4 px-1 bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">{c.product}</Badge>}
                                                {c.platforms && c.platforms.map((p: string) => (
                                                    <Badge key={p} variant="secondary" className="text-[10px] h-4 px-1 bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">{p}</Badge>
                                                ))}
                                                {c.countries && c.countries.map((ct: string) => (
                                                    <Badge key={ct} variant="secondary" className="text-[10px] h-4 px-1">{ct}</Badge>
                                                ))}
                                                {c.language && <Badge variant="secondary" className="text-[10px] h-4 px-1">{c.language}</Badge>}
                                            </div>
                                        </div>
                                    </div>
                                    );
                                })}
                                {isGenerating && (
                                    <div className="p-8 text-center text-sm text-muted-foreground animate-pulse border border-dashed rounded-md">
                                        {t("promptEditor.brainstorm.generatingInParallel")}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                <DialogFooter className="mt-4 pt-4 border-t">
                    <Button variant="outline" onClick={() => setBrainstormOpen(false)}>{tCommon("actions.cancel")}</Button>
                    <Button
                        onClick={handleSaveBrainstorms}
                        disabled={isGenerating || candidates.filter(c => c.selected).length === 0 || !selectedCandidateIntentsValid}
                    >
                        {t("promptEditor.brainstorm.saveSelected", { count: candidates.filter(c => c.selected).length })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
