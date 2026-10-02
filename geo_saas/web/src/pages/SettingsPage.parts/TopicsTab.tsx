import {
    ChevronDown, ChevronRight, Package, Plus, Sparkles, Tag, Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { TabsContent } from "@/components/ui/tabs";
import HelpTooltip from "@/components/ui/HelpTooltip";
import ProductEditor from "@/components/settings/ProductEditor";
import type { Brand, TopicProduct } from "@/lib/api";
import OwnProductCard from "./OwnProductCard";

interface TopicsTabProps {
    clientId: string;
    topics: any[];
    domains: any[];
    shadowBrands: Brand[];
    ownBrands: Brand[];
    ownProductsByTopic: Record<string, TopicProduct[]>;
    expandedTopicId: string | null;
    setExpandedTopicId: (id: string | null) => void;
    expandedOwnProductId: string | null;
    setExpandedOwnProductId: (id: string | null) => void;
    newTopic: string;
    setNewTopic: (v: string) => void;
    newOwnProductOpen: string | null;
    setNewOwnProductOpen: (id: string | null) => void;
    handleAddTopic: () => void;
    handleRemoveTopic: (topicId: string) => void;
    loadOwnProducts: (topicId: string) => void;
    handleCreateOwnProduct: (
        topicId: string,
        v: { product_name: string; match_variants: string[]; owner_brand_id: string },
    ) => Promise<void>;
    handleDeleteOwnProduct: (topicId: string, productId: string) => void;
    handleSetOwnProductActive: (topicId: string, productId: string, isActive: boolean) => void;
    handleSetOwnProductOwner: (topicId: string, productId: string, ownerBrandId: string | null) => void;
    updatingProductId: string | null;
    openAutoDiscover: () => void;
}

export default function TopicsTab(props: TopicsTabProps) {
    const { t } = useTranslation("settings");
    const {
        clientId, topics, domains, shadowBrands, ownBrands,
        ownProductsByTopic,
        expandedTopicId, setExpandedTopicId,
        expandedOwnProductId, setExpandedOwnProductId,
        newTopic, setNewTopic,
        newOwnProductOpen, setNewOwnProductOpen,
        handleAddTopic, handleRemoveTopic,
        loadOwnProducts,
        handleCreateOwnProduct,
        handleDeleteOwnProduct,
        handleSetOwnProductActive,
        handleSetOwnProductOwner,
        updatingProductId,
        openAutoDiscover,
    } = props;

    return (
        <TabsContent value="topics" className="space-y-6 mt-0 animate-in fade-in-50 duration-500">
            <div className="rounded-lg border bg-gradient-to-br from-primary/5 via-background to-background p-4 space-y-2">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Tag className="h-4 w-4 text-primary" />
                    <HelpTooltip content={t("tooltips.topicsSection")}>
                        <span>{t("topics.title")}</span>
                    </HelpTooltip>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                    <strong className="text-foreground">{t("topics.descriptionBold")}</strong>{" "}
                    {t("topics.descriptionBefore")}
                    <strong>{t("topics.descriptionNot")}</strong>
                    {t("topics.descriptionAfter")}
                </p>
            </div>

            {/* Auto-discover */}
            <div className="rounded-lg border border-dashed border-primary/40 bg-primary/5 p-4 flex items-start justify-between gap-4">
                <div className="space-y-1">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                        <Sparkles className="h-4 w-4 text-primary" /> {t("topics.autoDiscoverCta")}
                    </div>
                    <p className="text-xs text-muted-foreground">
                        {t("topics.autoDiscoverDescription")}
                    </p>
                </div>
                <Button size="sm" onClick={openAutoDiscover} className="shrink-0">
                    <Sparkles className="h-3.5 w-3.5 mr-1.5" /> {t("topics.autoDiscoverButton")}
                </Button>
            </div>

            {/* Manual add */}
            <div className="flex gap-2">
                <Input
                    placeholder={t("topics.addPlaceholder")}
                    value={newTopic}
                    onChange={(e) => setNewTopic(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAddTopic()}
                />
                <Button onClick={handleAddTopic}>
                    <Plus className="h-3.5 w-3.5 mr-1" /> {t("topics.addButton")}
                </Button>
            </div>

            <div className="grid grid-cols-1 gap-4 mt-6">
                {topics.map((topic: any) => {
                    const isExpanded = expandedTopicId === topic.id;
                    const products = ownProductsByTopic[topic.id] || [];
                    return (
                        <Card
                            key={topic.id}
                            className="overflow-hidden shadow-none border bg-card"
                        >
                            <div
                                className="border-b bg-muted/30 px-4 py-3 flex items-center justify-between cursor-pointer"
                                onClick={() => {
                                    const next = isExpanded ? null : topic.id;
                                    setExpandedTopicId(next);
                                    if (next === topic.id && !ownProductsByTopic[topic.id]) {
                                        loadOwnProducts(topic.id);
                                    }
                                }}
                            >
                                <div className="flex items-center gap-2">
                                    {isExpanded ? (
                                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                                    ) : (
                                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                    )}
                                    <Tag className="h-4 w-4 text-primary" />
                                    <span className="font-semibold">{topic.topic_name}</span>
                                    <Badge
                                        variant={
                                            topic.topic_type === "product_line"
                                                ? "outline"
                                                : "secondary"
                                        }
                                        className="text-[10px] font-normal"
                                    >
                                        {topic.topic_type === "product_line"
                                            ? t("topics.productLine")
                                            : t("topics.semanticTopic")}
                                    </Badge>
                                </div>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleRemoveTopic(topic.id);
                                    }}
                                    className="h-8 text-muted-foreground hover:text-destructive"
                                >
                                    <Trash2 className="h-4 w-4" />
                                </Button>
                            </div>
                            {isExpanded && (
                                <div className="p-4 space-y-4">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                            <Package className="h-3.5 w-3.5" />
                                            <HelpTooltip content={t("tooltips.ownProductsSection")}>
                                                {t("topics.ownProductsTitle")}
                                            </HelpTooltip>
                                        </div>
                                        {newOwnProductOpen !== topic.id && (
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="h-7 text-xs"
                                                onClick={() => setNewOwnProductOpen(topic.id)}
                                            >
                                                <Plus className="h-3 w-3 mr-1" /> {t("topics.ownProductsAdd")}
                                            </Button>
                                        )}
                                    </div>

                                    {newOwnProductOpen === topic.id && (
                                        <ProductEditor
                                            role="own"
                                            brands={ownBrands}
                                            onCancel={() => setNewOwnProductOpen(null)}
                                            onSubmit={(v) =>
                                                handleCreateOwnProduct(topic.id, {
                                                    product_name: v.product_name,
                                                    match_variants: v.match_variants,
                                                    owner_brand_id: v.owner_brand_id!,
                                                })
                                            }
                                        />
                                    )}

                                    {products.length === 0 && newOwnProductOpen !== topic.id && (
                                        <div className="text-xs text-muted-foreground italic">
                                            {t("topics.ownProductsEmpty")}
                                        </div>
                                    )}

                                    <div className="space-y-3">
                                        {products.map((prod) => (
                                            <OwnProductCard
                                                key={prod.id}
                                                clientId={clientId}
                                                product={prod}
                                                expanded={expandedOwnProductId === prod.id}
                                                onToggle={() =>
                                                    setExpandedOwnProductId(
                                                        expandedOwnProductId === prod.id
                                                            ? null
                                                            : prod.id,
                                                    )
                                                }
                                                domains={domains}
                                                shadowBrands={shadowBrands}
                                                ownBrands={ownBrands}
                                                onDelete={() =>
                                                    handleDeleteOwnProduct(topic.id, prod.id)
                                                }
                                                onSetActive={(isActive) =>
                                                    handleSetOwnProductActive(topic.id, prod.id, isActive)
                                                }
                                                onSetOwner={(ownerBrandId) =>
                                                    handleSetOwnProductOwner(topic.id, prod.id, ownerBrandId)
                                                }
                                                statusUpdating={updatingProductId === prod.id}
                                            />
                                        ))}
                                    </div>
                                </div>
                            )}
                        </Card>
                    );
                })}
                {topics.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground border border-dashed rounded-lg">
                        {t("topics.empty")}
                    </div>
                )}
            </div>
        </TabsContent>
    );
}
