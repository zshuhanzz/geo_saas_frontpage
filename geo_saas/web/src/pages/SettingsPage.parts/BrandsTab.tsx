import {
    Building2, ChevronDown, ChevronRight, Plus, Warehouse,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TabsContent } from "@/components/ui/tabs";
import HelpTooltip from "@/components/ui/HelpTooltip";
import type { Brand, TopicProduct } from "@/lib/api";
import BrandCard from "./BrandCard";

interface BrandsTabProps {
    ownBrands: Brand[];
    shadowBrands: Brand[];
    topics: any[];
    peers: any[];
    domainsForBrand: (brandId: string) => any[];
    shadowProductsByBrand: Record<string, TopicProduct[]>;
    ownProductsForLink: Record<string, TopicProduct[]>;
    expandedBrandId: string | null;
    setExpandedBrandId: (id: string | null) => void;
    brandAliasInputs: Record<string, string>;
    setBrandAliasInputs: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    newDomainPerBrand: Record<string, string>;
    setNewDomainPerBrand: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    newBrandProductOpen: string | null;
    setNewBrandProductOpen: (id: string | null) => void;
    newBrandProductTopic: Record<string, string>;
    setNewBrandProductTopic: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    newOwnBrand: string;
    setNewOwnBrand: (v: string) => void;
    newShadowBrand: string;
    setNewShadowBrand: (v: string) => void;
    shadowBrandsCollapsed: boolean;
    setShadowBrandsCollapsed: React.Dispatch<React.SetStateAction<boolean>>;
    handleAddBrand: (isShadow: boolean, name: string) => void;
    handleRemoveBrand: (brandId: string) => void;
    handleAddBrandAlias: (brand: Brand) => void;
    handleRemoveBrandAlias: (brand: Brand, alias: string) => void;
    handleAddDomainToBrand: (brandId: string) => void;
    handleRemoveDomain: (domainId: string) => void;
    loadShadowBrandProducts: (brandId: string) => void;
    handleLoadOwnProductsForLink: (brandId: string, topicId: string) => void;
    handleLinkExistingProductToBrand: (brandId: string, productId: string) => Promise<void>;
    handleCreateShadowProduct: (
        brandId: string,
        topicId: string,
        v: { product_name: string; match_variants: string[]; shadow_sub_role?: any; owner_peer_id?: string | null },
    ) => Promise<void>;
    handleDeleteShadowProduct: (brandId: string, product: TopicProduct) => void;
    handleSetShadowProductActive: (brandId: string, product: TopicProduct, isActive: boolean) => void;
    updatingProductId: string | null;
}

export default function BrandsTab(props: BrandsTabProps) {
    const { t } = useTranslation("settings");
    const {
        ownBrands, shadowBrands, topics, peers,
        domainsForBrand, shadowProductsByBrand, ownProductsForLink,
        expandedBrandId, setExpandedBrandId,
        brandAliasInputs, setBrandAliasInputs,
        newDomainPerBrand, setNewDomainPerBrand,
        newBrandProductOpen, setNewBrandProductOpen,
        newBrandProductTopic, setNewBrandProductTopic,
        newOwnBrand, setNewOwnBrand,
        newShadowBrand, setNewShadowBrand,
        shadowBrandsCollapsed, setShadowBrandsCollapsed,
        handleAddBrand, handleRemoveBrand,
        handleAddBrandAlias, handleRemoveBrandAlias,
        handleAddDomainToBrand, handleRemoveDomain,
        loadShadowBrandProducts,
        handleLoadOwnProductsForLink,
        handleLinkExistingProductToBrand,
        handleCreateShadowProduct,
        handleDeleteShadowProduct,
        handleSetShadowProductActive,
        updatingProductId,
    } = props;

    return (
        <TabsContent value="brands" className="space-y-8 mt-0 animate-in fade-in-50 duration-500">
            {/* Own Brands section */}
            <section className="space-y-4">
                <div className="border-b pb-2 flex items-center gap-2">
                    <Building2 className="h-4 w-4 text-primary" />
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                        <HelpTooltip content={t("tooltips.ownBrandSection")}>
                            {t("brands.ownSection")}
                        </HelpTooltip>
                    </h3>
                    <Badge variant="outline" className="text-[10px] ml-auto">
                        {ownBrands.length}
                    </Badge>
                </div>

                <div className="flex gap-2 max-w-md">
                    <Input
                        placeholder={t("brands.addOwnPlaceholder")}
                        value={newOwnBrand}
                        onChange={(e) => setNewOwnBrand(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleAddBrand(false, newOwnBrand)}
                    />
                    <Button onClick={() => handleAddBrand(false, newOwnBrand)}>
                        <Plus className="h-3.5 w-3.5 mr-1" /> {t("brands.addButton")}
                    </Button>
                </div>

                <div className="grid grid-cols-1 gap-3">
                    {ownBrands.map((brand) => (
                        <BrandCard
                            key={brand.id}
                            brand={brand}
                            expanded={expandedBrandId === brand.id}
                            onToggle={() =>
                                setExpandedBrandId(
                                    expandedBrandId === brand.id ? null : brand.id,
                                )
                            }
                            onRemove={() => handleRemoveBrand(brand.id)}
                            aliasInput={brandAliasInputs[brand.id] || ""}
                            setAliasInput={(v) =>
                                setBrandAliasInputs((p) => ({ ...p, [brand.id]: v }))
                            }
                            onAddAlias={() => handleAddBrandAlias(brand)}
                            onRemoveAlias={(a) => handleRemoveBrandAlias(brand, a)}
                            domains={domainsForBrand(brand.id)}
                            domainInput={newDomainPerBrand[brand.id] || ""}
                            setDomainInput={(v) =>
                                setNewDomainPerBrand((p) => ({ ...p, [brand.id]: v }))
                            }
                            onAddDomain={() => handleAddDomainToBrand(brand.id)}
                            onRemoveDomain={(id) => handleRemoveDomain(id)}
                        />
                    ))}
                    {ownBrands.length === 0 && (
                        <div className="text-center py-6 text-muted-foreground border border-dashed rounded-lg text-sm">
                            {t("brands.emptyOwn")}
                        </div>
                    )}
                </div>
            </section>

            {/* Shadow Brands section */}
            <section className="space-y-4">
                <button
                    type="button"
                    onClick={() => setShadowBrandsCollapsed((v) => !v)}
                    className="w-full border-b pb-2 flex items-center gap-2 hover:text-foreground transition-colors"
                >
                    <Warehouse className="h-4 w-4 text-primary" />
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                        <HelpTooltip content={t("tooltips.shadowBrandSection")}>
                            {t("brands.shadowSection")}
                        </HelpTooltip>
                    </h3>
                    <Badge variant="outline" className="text-[10px]">
                        {shadowBrands.length}
                    </Badge>
                    <div className="ml-auto text-muted-foreground">
                        {shadowBrandsCollapsed ? (
                            <ChevronRight className="h-4 w-4" />
                        ) : (
                            <ChevronDown className="h-4 w-4" />
                        )}
                    </div>
                </button>

                {!shadowBrandsCollapsed && (
                    <>
                        <p className="text-xs text-muted-foreground max-w-2xl">
                            {t("brands.shadowSectionHint")}
                        </p>

                        <div className="flex gap-2 max-w-md">
                            <Input
                                placeholder={t("brands.addShadowPlaceholder")}
                                value={newShadowBrand}
                                onChange={(e) => setNewShadowBrand(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && handleAddBrand(true, newShadowBrand)}
                            />
                            <Button onClick={() => handleAddBrand(true, newShadowBrand)}>
                                <Plus className="h-3.5 w-3.5 mr-1" /> {t("brands.addButton")}
                            </Button>
                        </div>

                        <div className="grid grid-cols-1 gap-3">
                            {shadowBrands.map((brand) => {
                                const isExpanded = expandedBrandId === brand.id;
                                const products = shadowProductsByBrand[brand.id] || [];
                                return (
                                    <BrandCard
                                        key={brand.id}
                                        brand={brand}
                                        expanded={isExpanded}
                                        onToggle={() => {
                                            const next =
                                                expandedBrandId === brand.id
                                                    ? null
                                                    : brand.id;
                                            setExpandedBrandId(next);
                                            if (next === brand.id && !shadowProductsByBrand[brand.id]) {
                                                loadShadowBrandProducts(brand.id);
                                            }
                                        }}
                                        onRemove={() => handleRemoveBrand(brand.id)}
                                        aliasInput={brandAliasInputs[brand.id] || ""}
                                        setAliasInput={(v) =>
                                            setBrandAliasInputs((p) => ({ ...p, [brand.id]: v }))
                                        }
                                        onAddAlias={() => handleAddBrandAlias(brand)}
                                        onRemoveAlias={(a) => handleRemoveBrandAlias(brand, a)}
                                        domains={domainsForBrand(brand.id)}
                                        domainInput={newDomainPerBrand[brand.id] || ""}
                                        setDomainInput={(v) =>
                                            setNewDomainPerBrand((p) => ({ ...p, [brand.id]: v }))
                                        }
                                        onAddDomain={() => handleAddDomainToBrand(brand.id)}
                                        onRemoveDomain={(id) => handleRemoveDomain(id)}
                                        // Shadow-only: products section
                                        showShadowProducts
                                        shadowProducts={products}
                                        topics={topics}
                                        peers={peers}
                                        newProductOpen={newBrandProductOpen === brand.id}
                                        onOpenNewProduct={() =>
                                            setNewBrandProductOpen(brand.id)
                                        }
                                        onCancelNewProduct={() =>
                                            setNewBrandProductOpen(null)
                                        }
                                        newProductTopic={newBrandProductTopic[brand.id] || ""}
                                        setNewProductTopic={(v) =>
                                            setNewBrandProductTopic((p) => ({
                                                ...p,
                                                [brand.id]: v,
                                            }))
                                        }
                                        onSubmitShadowProduct={(topicId, v) =>
                                            handleCreateShadowProduct(brand.id, topicId, v)
                                        }
                                        onDeleteShadowProduct={(product) =>
                                            handleDeleteShadowProduct(brand.id, product)
                                        }
                                        onSetShadowProductActive={(product, isActive) =>
                                            handleSetShadowProductActive(brand.id, product, isActive)
                                        }
                                        updatingProductId={updatingProductId}
                                        ownProductsInTopic={
                                            ownProductsForLink[
                                            `${brand.id}:${newBrandProductTopic[brand.id] || ""}`
                                            ] || []
                                        }
                                        onSelectLinkTopic={(topicId) =>
                                            handleLoadOwnProductsForLink(brand.id, topicId)
                                        }
                                        onLinkExistingProduct={(productId) =>
                                            handleLinkExistingProductToBrand(brand.id, productId)
                                        }
                                    />
                                );
                            })}
                            {shadowBrands.length === 0 && (
                                <div className="text-center py-6 text-muted-foreground border border-dashed rounded-lg text-sm">
                                    {t("brands.emptyShadow")}
                                </div>
                            )}
                        </div>
                    </>
                )}
            </section>
        </TabsContent>
    );
}
