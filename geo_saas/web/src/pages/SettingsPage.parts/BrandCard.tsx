import { useState } from "react";
import {
    ChevronDown, ChevronRight, Globe, Package, Plus, Trash2, X,
} from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import HelpTooltip from "@/components/ui/HelpTooltip";
import ProductEditor from "@/components/settings/ProductEditor";
import type { Brand, TopicProduct } from "@/lib/api";
import ProductRow from "./ProductRow";

interface BrandCardProps {
    brand: Brand;
    expanded: boolean;
    onToggle: () => void;
    onRemove: () => void;
    aliasInput: string;
    setAliasInput: (v: string) => void;
    onAddAlias: () => void;
    onRemoveAlias: (alias: string) => void;
    domains: any[];
    domainInput: string;
    setDomainInput: (v: string) => void;
    onAddDomain: () => void;
    onRemoveDomain: (domainId: string) => void;
    // Shadow-only
    showShadowProducts?: boolean;
    shadowProducts?: TopicProduct[];
    topics?: any[];
    peers?: any[];
    newProductOpen?: boolean;
    onOpenNewProduct?: () => void;
    onCancelNewProduct?: () => void;
    newProductTopic?: string;
    setNewProductTopic?: (v: string) => void;
    onSubmitShadowProduct?: (topicId: string, v: { product_name: string; match_variants: string[]; shadow_sub_role?: any; owner_peer_id?: string | null }) => Promise<void>;
    onDeleteShadowProduct?: (product: TopicProduct) => void;
    onSetShadowProductActive?: (product: TopicProduct, isActive: boolean) => void;
    updatingProductId?: string | null;
    // D2 fix (2026-04-21): support linking an EXISTING own product to this
    // brand as a sales channel (writes geo_product_sales_channels), instead
    // of only the "create new shadow_brand_product" path.
    ownProductsInTopic?: TopicProduct[];   // lazily loaded per-topic by parent
    onSelectLinkTopic?: (topicId: string) => void;  // parent fetches own products
    onLinkExistingProduct?: (productId: string) => Promise<void>;
}

export default function BrandCard(props: BrandCardProps) {
    const { t } = useTranslation("settings");
    const { brand, expanded, onToggle, onRemove, aliasInput, setAliasInput, onAddAlias, onRemoveAlias,
        domains, domainInput, setDomainInput, onAddDomain, onRemoveDomain } = props;
    return (
        <Card className="overflow-hidden shadow-none border bg-card/50">
            <div
                className="border-b bg-muted/20 px-4 py-3 flex items-center justify-between cursor-pointer"
                onClick={onToggle}
            >
                <div className="flex items-center gap-2">
                    {expanded ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="font-semibold">{brand.brand_name}</span>
                    {brand.is_shadow && (
                        <Badge variant="secondary" className="text-[10px] font-normal">
                            {t("brands.channelBadge")}
                        </Badge>
                    )}
                    {brand.aliases && brand.aliases.length > 0 && (
                        <span className="text-xs text-muted-foreground">
                            ({t("brands.aliasCount", { count: brand.aliases.length })})
                        </span>
                    )}
                </div>
                <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                        e.stopPropagation();
                        onRemove();
                    }}
                >
                    <Trash2 className="h-4 w-4" />
                </Button>
            </div>

            {expanded && (
                <div className="p-4 space-y-4">
                    {/* Aliases */}
                    <div className="space-y-2">
                        <div className="flex flex-wrap gap-2 items-center">
                            <span className="text-xs font-medium text-muted-foreground mr-1">
                                {t("brands.aliasesSection")}
                            </span>
                            {(brand.aliases || []).map((alias: string, idx: number) => (
                                <Badge key={idx} variant="outline" className="text-xs py-0.5 pl-2 pr-1">
                                    {alias}
                                    <button
                                        onClick={() => onRemoveAlias(alias)}
                                        className="ml-1.5 rounded-full p-0.5 hover:bg-muted hover:text-destructive transition-colors"
                                    >
                                        <X className="h-3 w-3" />
                                    </button>
                                </Badge>
                            ))}
                            {(!brand.aliases || brand.aliases.length === 0) && (
                                <span className="text-xs text-muted-foreground/70 italic">
                                    {t("brands.aliasesEmpty")}
                                </span>
                            )}
                        </div>
                        <div className="flex gap-2 max-w-sm">
                            <Input
                                placeholder={t("brands.aliasAddPlaceholder")}
                                value={aliasInput}
                                onChange={(e) => setAliasInput(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && onAddAlias()}
                                className="h-8 text-sm"
                            />
                            <Button size="sm" variant="secondary" onClick={onAddAlias} className="h-8">
                                <Plus className="h-3 w-3 mr-1" /> {t("brands.aliasAddButton")}
                            </Button>
                        </div>
                    </div>

                    {/* Domains */}
                    <div className="space-y-2 pt-3 border-t">
                        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            <Globe className="h-3.5 w-3.5" /> {t("brands.domainsSection")}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                            {domains.map((d: any) => (
                                <Badge
                                    key={d.id}
                                    variant="outline"
                                    className="text-xs pl-2 pr-1 py-0.5 font-mono"
                                >
                                    {d.domain}
                                    {d.is_primary && (
                                        <span className="ml-1 text-[9px] text-primary">Primary</span>
                                    )}
                                    <button
                                        onClick={() => onRemoveDomain(d.id)}
                                        className="ml-1.5 rounded-full p-0.5 hover:bg-destructive/10 hover:text-destructive transition-colors"
                                    >
                                        <X className="h-3 w-3" />
                                    </button>
                                </Badge>
                            ))}
                            {domains.length === 0 && (
                                <span className="text-xs text-muted-foreground/70 italic">{t("brands.domainsEmpty")}</span>
                            )}
                        </div>
                        <div className="flex gap-2 max-w-sm">
                            <Input
                                placeholder={t("brands.domainAddPlaceholder")}
                                value={domainInput}
                                onChange={(e) => setDomainInput(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && onAddDomain()}
                                className="h-8 text-sm"
                            />
                            <Button size="sm" variant="secondary" onClick={onAddDomain} className="h-8">
                                <Plus className="h-3 w-3 mr-1" /> {t("brands.domainAddButton")}
                            </Button>
                        </div>
                    </div>

                    {/* Shadow products */}
                    {props.showShadowProducts && (
                        <div className="space-y-2 pt-3 border-t">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                    <Package className="h-3.5 w-3.5" />
                                    <HelpTooltip content={t("tooltips.shadowChannelProducts")}>
                                        {t("brands.shadowProductsTitle")}
                                    </HelpTooltip>
                                </div>
                                {!props.newProductOpen && (
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="h-7 text-xs"
                                        onClick={props.onOpenNewProduct}
                                        disabled={(props.topics?.length ?? 0) === 0}
                                    >
                                        <Plus className="h-3 w-3 mr-1" /> {t("brands.shadowProductsAdd")}
                                    </Button>
                                )}
                            </div>

                            {(props.topics?.length ?? 0) === 0 && (
                                <div className="text-xs text-muted-foreground/80 italic">
                                    {t("brands.shadowProductsNoTopics")}
                                </div>
                            )}

                            {(props.shadowProducts?.length ?? 0) === 0 && !props.newProductOpen && (props.topics?.length ?? 0) > 0 && (
                                <div className="text-xs text-muted-foreground/80 italic">
                                    {t("brands.shadowProductsEmpty")}
                                </div>
                            )}

                            <div className="space-y-2">
                                {(props.shadowProducts || []).map((prod) => (
                                    <ProductRow
                                        key={prod.id}
                                        product={prod}
                                        topicName={
                                            props.topics?.find((t: any) => t.id === prod.topic_id)?.topic_name
                                        }
                                        onDelete={() => props.onDeleteShadowProduct?.(prod)}
                                        onSetActive={(isActive) =>
                                            props.onSetShadowProductActive?.(prod, isActive)
                                        }
                                        statusUpdating={props.updatingProductId === prod.id}
                                        deleteLabel={
                                            prod.channel_source === "sales_channel"
                                                ? t("salesChannels.removeAria")
                                                : t("products.deletePermanently")
                                        }
                                    />
                                ))}
                            </div>

                            {props.newProductOpen && (
                                <NewShadowProductPanel
                                    topics={props.topics || []}
                                    peers={props.peers || []}
                                    newProductTopic={props.newProductTopic}
                                    setNewProductTopic={(v) => {
                                        props.setNewProductTopic?.(v);
                                        props.onSelectLinkTopic?.(v);
                                    }}
                                    ownProductsInTopic={props.ownProductsInTopic || []}
                                    onSubmitShadowProduct={props.onSubmitShadowProduct}
                                    onLinkExistingProduct={props.onLinkExistingProduct}
                                    onCancelNewProduct={props.onCancelNewProduct}
                                />
                            )}
                        </div>
                    )}
                </div>
            )}
        </Card>
    );
}

// D2 (2026-04-21): 2-tab panel for adding a product to a Shadow/channel brand.
//   Tab A — 关联已有产品: Select an existing own-brand product and write a
//           geo_product_sales_channels row (does NOT create a new product).
//   Tab B — 新建渠道专属产品: Create a brand-new shadow_brand_product row
//           (the original flow — kept as the escape hatch for OEM-specific
//           SKUs that don't exist under any own topic yet).
// Wraps the existing ProductEditor. Keep in the same file so the Brand tab's
// state flows through props without bringing up another module.
function NewShadowProductPanel(props: {
    topics: any[];
    peers: any[];
    newProductTopic?: string;
    setNewProductTopic: (v: string) => void;
    ownProductsInTopic: TopicProduct[];
    onSubmitShadowProduct?: (topicId: string, v: { product_name: string; match_variants: string[]; shadow_sub_role?: any; owner_peer_id?: string | null }) => Promise<void>;
    onLinkExistingProduct?: (productId: string) => Promise<void>;
    onCancelNewProduct?: () => void;
}) {
    const { t } = useTranslation("settings");
    const [mode, setMode] = useState<"link" | "create">("link");
    const [selectedProductId, setSelectedProductId] = useState<string>("");
    const topicId = props.newProductTopic;

    return (
        <div className="space-y-3 rounded-md border border-dashed p-3 bg-muted/10">
            <div className="space-y-1.5">
                <Label className="text-xs">{t("newShadowProduct.topicLabel")}</Label>
                <Select
                    value={topicId || ""}
                    onValueChange={(v) => {
                        props.setNewProductTopic(v);
                        setSelectedProductId("");
                    }}
                >
                    <SelectTrigger>
                        <SelectValue placeholder={t("newShadowProduct.topicPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                        {props.topics.map((topic: any) => (
                            <SelectItem key={topic.id} value={topic.id}>
                                {topic.topic_name}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>

            <div className="flex gap-1 rounded-md bg-muted/40 p-1">
                <button
                    type="button"
                    className={`flex-1 text-xs font-medium py-1.5 rounded ${mode === "link"
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                        }`}
                    onClick={() => setMode("link")}
                >
                    {t("newShadowProduct.tabLink")}
                </button>
                <button
                    type="button"
                    className={`flex-1 text-xs font-medium py-1.5 rounded ${mode === "create"
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                        }`}
                    onClick={() => setMode("create")}
                >
                    {t("newShadowProduct.tabCreate")}
                </button>
            </div>

            {mode === "link" ? (
                <div className="space-y-3">
                    <div className="space-y-1.5">
                        <Label className="text-xs">{t("newShadowProduct.productLabel")}</Label>
                        <Select
                            value={selectedProductId}
                            onValueChange={setSelectedProductId}
                            disabled={!topicId}
                        >
                            <SelectTrigger>
                                <SelectValue placeholder={topicId ? t("newShadowProduct.productSelectPlaceholder") : t("newShadowProduct.productSelectNeedTopic")} />
                            </SelectTrigger>
                            <SelectContent>
                                {props.ownProductsInTopic.length === 0 && topicId && (
                                    <SelectItem value="__none__" disabled>
                                        {t("newShadowProduct.emptyInTopic")}
                                    </SelectItem>
                                )}
                                {props.ownProductsInTopic.map((p) => (
                                    <SelectItem key={p.id} value={p.id}>
                                        {p.product_name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <p className="text-[11px] text-muted-foreground">
                            {t("newShadowProduct.writeIntro")} <code>geo_product_sales_channels</code> {t("newShadowProduct.writeOutro")}
                        </p>
                    </div>
                    <div className="flex justify-end gap-2">
                        <Button variant="ghost" size="sm" onClick={props.onCancelNewProduct}>
                            {t("newShadowProduct.cancel")}
                        </Button>
                        <Button
                            size="sm"
                            disabled={!selectedProductId || selectedProductId === "__none__"}
                            onClick={async () => {
                                if (selectedProductId && selectedProductId !== "__none__") {
                                    await props.onLinkExistingProduct?.(selectedProductId);
                                }
                            }}
                        >
                            {t("newShadowProduct.linkButton")}
                        </Button>
                    </div>
                </div>
            ) : (
                <ProductEditor
                    role="shadow_brand_product"
                    peers={props.peers.map((p: any) => ({
                        id: p.id,
                        primary_name: p.primary_name,
                    }))}
                    onCancel={props.onCancelNewProduct}
                    onSubmit={(v) => {
                        if (!topicId) {
                            toast.error(t("newShadowProduct.needTopicToast"));
                            return;
                        }
                        return props.onSubmitShadowProduct?.(topicId, v) ?? Promise.resolve();
                    }}
                />
            )}
        </div>
    );
}
