import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ChevronDown, ChevronRight, PlusCircle } from "lucide-react";
import { countUniquePrompts } from "./utils";

interface TopicSidebarProps {
    data: any[];
    activeClient: any;
    filterTopicId: string | null;
    setFilterTopicId: (id: string | null) => void;
    filterProduct: string | null;
    setFilterProduct: (p: string | null) => void;
    sidebarExpandedTopics: Set<string>;
    setSidebarExpandedTopics: React.Dispatch<React.SetStateAction<Set<string>>>;
    topicPromptCounts: Record<string, number>;
    addingTopic: boolean;
    setAddingTopic: (v: boolean) => void;
    newTopicName: string;
    setNewTopicName: (v: string) => void;
    handleAddTopicSubmit: () => void;
    addingProductForTopic: string | null;
    setAddingProductForTopic: (v: string | null) => void;
    newProductName: string;
    setNewProductName: (v: string) => void;
    handleAddProductSubmit: (topicId: string) => void;
}

export function TopicSidebar({
    data,
    activeClient,
    filterTopicId,
    setFilterTopicId,
    filterProduct,
    setFilterProduct,
    sidebarExpandedTopics,
    setSidebarExpandedTopics,
    topicPromptCounts,
    addingTopic,
    setAddingTopic,
    newTopicName,
    setNewTopicName,
    handleAddTopicSubmit,
    addingProductForTopic,
    setAddingProductForTopic,
    newProductName,
    setNewProductName,
    handleAddProductSubmit,
}: TopicSidebarProps) {
    const { t } = useTranslation("insights");

    return (
        <div className="w-56 shrink-0 space-y-1 overflow-y-auto">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-2">{t("promptEditor.sidebarTitle")}</div>
            <button
                onClick={() => { setFilterTopicId(null); setFilterProduct(null); }}
                className={`w-full text-left px-3 py-2 rounded-md text-sm flex justify-between items-center transition-colors ${filterTopicId === null && filterProduct === null ? 'bg-accent text-accent-foreground font-semibold' : 'hover:bg-muted/50 text-muted-foreground'
                    }`}
            >
                <span>{t("promptEditor.allTopics")}</span>
                <Badge variant="secondary" className="text-[10px] h-4 px-1.5">{countUniquePrompts(data)}</Badge>
            </button>
            {(activeClient?.topics || []).map((tp: any) => {
                const products: string[] = tp.products || [];
                const isExpanded = sidebarExpandedTopics.has(tp.id);
                const topicActive = filterTopicId === tp.id && !filterProduct;
                return (
                    <div key={tp.id}>
                        <div className="flex items-center">
                            {products.length > 0 && (
                                <button
                                    onClick={() => setSidebarExpandedTopics(prev => {
                                        const next = new Set(prev);
                                        next.has(tp.id) ? next.delete(tp.id) : next.add(tp.id);
                                        return next;
                                    })}
                                    className="p-0.5 hover:bg-muted rounded ml-1"
                                >
                                    {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                                </button>
                            )}
                            {products.length === 0 && <div className="w-[18px] ml-1" />}
                            <button
                                onClick={() => { setFilterTopicId(tp.id); setFilterProduct(null); }}
                                className={`flex-1 text-left px-2 py-2 rounded-md text-sm flex justify-between items-center transition-colors ${topicActive ? 'bg-accent text-accent-foreground font-semibold' : 'hover:bg-muted/50 text-muted-foreground'}`}
                            >
                                <span className="truncate">{tp.topic_name}</span>
                                <Badge variant="secondary" className="text-[10px] h-4 px-1.5">{topicPromptCounts[tp.id] || 0}</Badge>
                            </button>
                        </div>
                        {isExpanded && products.map((prod: string) => {
                            const prodActive = filterTopicId === tp.id && filterProduct === prod;
                            const prodCount = countUniquePrompts(data.filter(p => p.topic_id === tp.id && p.product === prod));
                            return (
                                <button
                                    key={prod}
                                    onClick={() => { setFilterTopicId(tp.id); setFilterProduct(prod); }}
                                    className={`w-full text-left pl-10 pr-3 py-1.5 rounded-md text-xs flex justify-between items-center transition-colors ${prodActive ? 'bg-accent text-accent-foreground font-semibold' : 'hover:bg-muted/50 text-muted-foreground'}`}
                                >
                                    <span className="truncate">{prod}</span>
                                    <Badge variant="secondary" className="text-[10px] h-4 px-1">{prodCount}</Badge>
                                </button>
                            );
                        })}
                        {isExpanded && (
                            addingProductForTopic === tp.id ? (
                                <div className="pl-10 pr-3 py-1">
                                    <Input
                                        className="h-6 text-xs"
                                        placeholder={t("promptEditor.productPlaceholder")}
                                        value={newProductName}
                                        autoFocus
                                        onChange={(e) => setNewProductName(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleAddProductSubmit(tp.id);
                                            if (e.key === 'Escape') { setAddingProductForTopic(null); setNewProductName(""); }
                                        }}
                                        onBlur={() => handleAddProductSubmit(tp.id)}
                                    />
                                </div>
                            ) : (
                                <button
                                    onClick={() => { setAddingProductForTopic(tp.id); setNewProductName(""); }}
                                    className="w-full text-left pl-10 pr-3 py-1.5 rounded-md text-xs flex items-center gap-1 text-muted-foreground hover:bg-muted/50 hover:text-primary transition-colors"
                                >
                                    <PlusCircle className="h-3 w-3" /> {t("promptEditor.addProduct")}
                                </button>
                            )
                        )}
                    </div>
                );
            })}
            {addingTopic ? (
                <div className="mt-2 px-1">
                    <Input
                        className="h-8 text-sm"
                        placeholder={t("promptEditor.topicPlaceholder")}
                        value={newTopicName}
                        autoFocus
                        onChange={(e) => setNewTopicName(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') handleAddTopicSubmit();
                            if (e.key === 'Escape') { setAddingTopic(false); setNewTopicName(""); }
                        }}
                        onBlur={() => handleAddTopicSubmit()}
                    />
                </div>
            ) : (
                <button
                    onClick={() => { setAddingTopic(true); setNewTopicName(""); }}
                    className="w-full text-left px-3 py-2 rounded-md text-sm flex items-center gap-2 text-muted-foreground hover:bg-muted/50 hover:text-primary transition-colors mt-2 border border-dashed border-muted-foreground/30"
                >
                    <PlusCircle className="h-3.5 w-3.5" /> {t("promptEditor.addTopic")}
                </button>
            )}
        </div>
    );
}
