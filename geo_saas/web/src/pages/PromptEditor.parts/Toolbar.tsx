import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sparkles, Upload, FileDown, Plus, Loader2, ChevronDown, Monitor, Save } from "lucide-react";
import { countUniquePrompts } from "./utils";

interface ToolbarProps {
    activePrompts: any[];
    inactivePrompts: any[];
    activeClient: any;
    filterTopicId: string | null;
    setFilterTopicId: (v: string | null) => void;
    filterPlatform: string | null;
    setFilterPlatform: (v: string | null) => void;
    uniquePlatforms: string[];
    handleAddRow: () => void;
    setBrainstormOpen: (v: boolean) => void;
    handleSaveAll: () => void;
    hasPendingChanges: boolean;
    savingAll: boolean;
    pendingCount: number;
}

export function Toolbar({
    activePrompts,
    inactivePrompts,
    activeClient,
    filterTopicId,
    setFilterTopicId,
    filterPlatform,
    setFilterPlatform,
    uniquePlatforms,
    handleAddRow,
    setBrainstormOpen,
    handleSaveAll,
    hasPendingChanges,
    savingAll,
    pendingCount,
}: ToolbarProps) {
    const { t } = useTranslation("insights");
    return (
        <div className="flex justify-between items-center mb-4">
            <div className="flex items-center gap-3">
                <TabsList>
                    <TabsTrigger value="active">{t("promptEditor.tabs.active")} <Badge variant="secondary" className="ml-2 bg-background">{countUniquePrompts(activePrompts)}</Badge></TabsTrigger>
                    <TabsTrigger value="inactive">{t("promptEditor.tabs.inactive")} <Badge variant="secondary" className="ml-2 bg-background">{countUniquePrompts(inactivePrompts)}</Badge></TabsTrigger>
                </TabsList>

                {/* Topic Filter Dropdown */}
                <Popover>
                    <PopoverTrigger asChild>
                        <Button variant="outline" size="sm" className="gap-1.5 h-8 text-xs">
                            <span className="text-muted-foreground">#</span>
                            {filterTopicId ? (activeClient?.topics.find((tp: any) => tp.id === filterTopicId)?.topic_name || t("promptEditor.filterTopicAll")) : t("promptEditor.filterTopicAll")}
                            <ChevronDown className="h-3 w-3 ml-1 text-muted-foreground" />
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-48 p-1" align="start">
                        <button
                            className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 ${!filterTopicId ? 'font-semibold' : ''}`}
                            onClick={() => setFilterTopicId(null)}
                        >{t("promptEditor.allTopics")}</button>
                        {(activeClient?.topics || []).map((tp: any) => (
                            <button
                                key={tp.id}
                                className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 truncate ${filterTopicId === tp.id ? 'font-semibold bg-accent/30' : ''}`}
                                onClick={() => setFilterTopicId(tp.id)}
                            >{tp.topic_name}</button>
                        ))}
                    </PopoverContent>
                </Popover>

                {/* Platform Filter Dropdown */}
                <Popover>
                    <PopoverTrigger asChild>
                        <Button variant="outline" size="sm" className="gap-1.5 h-8 text-xs">
                            <Monitor className="h-3.5 w-3.5 text-muted-foreground" />
                            {filterPlatform || t("promptEditor.filterPlatformAll")}
                            <ChevronDown className="h-3 w-3 ml-1 text-muted-foreground" />
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-44 p-1" align="start">
                        <button
                            className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 ${!filterPlatform ? 'font-semibold' : ''}`}
                            onClick={() => setFilterPlatform(null)}
                        >{t("prompts.filters.allPlatforms")}</button>
                        {uniquePlatforms.map(p => (
                            <button
                                key={p}
                                className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 ${filterPlatform === p ? 'font-semibold bg-accent/30' : ''}`}
                                onClick={() => setFilterPlatform(p)}
                            >{p}</button>
                        ))}
                    </PopoverContent>
                </Popover>
            </div>

            <div className="flex gap-2">
                <Button variant="outline"><Upload className="h-4 w-4 mr-2" /> {t("promptEditor.batchUpload")}</Button>
                <Button variant="outline"><FileDown className="h-4 w-4 mr-2" /> {t("promptEditor.exportBtn")}</Button>
                <Button variant="outline" onClick={handleAddRow}><Plus className="h-4 w-4 mr-2" /> {t("promptEditor.addPromptBtn")}</Button>
                <Button onClick={() => setBrainstormOpen(true)}>
                    <Sparkles className="h-4 w-4 mr-2" /> {t("promptEditor.generate")}
                </Button>
                <Button
                    onClick={handleSaveAll}
                    disabled={!hasPendingChanges || savingAll}
                    className="min-w-[150px]"
                >
                    {savingAll ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
                    {t("promptEditor.saveAllChanges")}
                    {pendingCount > 0 && (
                        <Badge variant="secondary" className="ml-2 bg-primary-foreground/20 text-[10px] h-4 px-1.5">
                            {pendingCount}
                        </Badge>
                    )}
                </Button>
            </div>
        </div>
    );
}
