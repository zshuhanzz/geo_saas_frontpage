import {
    ChevronDown, ChevronRight, Package, PauseCircle, PlayCircle, Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import TrackedUrlsEditor from "@/components/settings/TrackedUrlsEditor";
import SalesChannelsEditor from "@/components/settings/SalesChannelsEditor";
import type { Brand, TopicProduct } from "@/lib/api";

interface OwnProductCardProps {
    clientId: string;
    product: TopicProduct;
    expanded: boolean;
    onToggle: () => void;
    domains: any[];
    shadowBrands: Brand[];
    ownBrands: Brand[];
    onDelete: () => void;
    onSetActive: (isActive: boolean) => void;
    onSetOwner: (ownerBrandId: string | null) => void;
    statusUpdating?: boolean;
}

export default function OwnProductCard({
    clientId,
    product,
    expanded,
    onToggle,
    domains,
    shadowBrands,
    ownBrands,
    onDelete,
    onSetActive,
    onSetOwner,
    statusUpdating = false,
}: OwnProductCardProps) {
    const { t } = useTranslation("settings");
    const ownerIsActive = Boolean(
        product.owner_brand_id
        && ownBrands.some((brand) => brand.id === product.owner_brand_id && brand.is_active),
    );
    return (
        <div className={`rounded-md border bg-background ${product.is_active ? "" : "opacity-70"}`}>
            <div
                className="flex items-center gap-2 px-3 py-2 cursor-pointer"
                onClick={onToggle}
            >
                {expanded ? (
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                )}
                <Package className="h-3.5 w-3.5 text-primary" />
                <span className="text-sm font-medium flex-1 truncate">
                    {product.product_name}
                </span>
                {(product.match_variants?.length ?? 0) > 0 && (
                    <Badge variant="outline" className="text-[10px] font-normal">
                        {t("ownProductCard.variantCount", { count: product.match_variants.length })}
                    </Badge>
                )}
                {!product.is_active && (
                    <Badge variant="secondary" className="text-[10px] font-normal">
                        {t("products.statusInactive")}
                    </Badge>
                )}
                <Badge variant={ownerIsActive ? "outline" : "secondary"} className="text-[10px] font-normal">
                    {ownerIsActive
                        ? t("products.sentimentEligible")
                        : t("products.ownerBrandUnverified")}
                </Badge>
                <Button
                    variant="ghost"
                    size="sm"
                    disabled={statusUpdating}
                    className="h-7 px-2 text-xs text-muted-foreground"
                    onClick={(e) => {
                        e.stopPropagation();
                        onSetActive(!product.is_active);
                    }}
                    aria-label={product.is_active ? t("products.deactivate") : t("products.reactivate")}
                >
                    {product.is_active ? (
                        <PauseCircle className="h-3.5 w-3.5 mr-1" />
                    ) : (
                        <PlayCircle className="h-3.5 w-3.5 mr-1" />
                    )}
                    {product.is_active ? t("products.deactivate") : t("products.reactivate")}
                </Button>
                <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                        e.stopPropagation();
                        onDelete();
                    }}
                    aria-label={t("products.deletePermanently")}
                >
                    <Trash2 className="h-3.5 w-3.5" />
                </Button>
            </div>
            {expanded && (
                <div className="border-t px-3 py-3 space-y-4">
                    <div className="space-y-1.5">
                        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                            {t("products.ownerBrand")}
                        </div>
                        <Select
                            value={product.owner_brand_id ?? "__unverified__"}
                            onValueChange={(value) => onSetOwner(
                                value === "__unverified__" ? null : value,
                            )}
                            disabled={statusUpdating}
                        >
                            <SelectTrigger className="max-w-sm" onClick={(event) => event.stopPropagation()}>
                                <SelectValue placeholder={t("products.ownerBrandPlaceholder")} />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="__unverified__">
                                    {t("products.ownerBrandUnverified")}
                                </SelectItem>
                                {ownBrands.map((brand) => (
                                    <SelectItem key={brand.id} value={brand.id}>
                                        {brand.brand_name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <p className="text-[11px] text-muted-foreground">
                            {t("products.ownerBrandHint")}
                        </p>
                    </div>
                    {(product.match_variants?.length ?? 0) > 0 && (
                        <div>
                            <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                                {t("ownProductCard.matchVariants")}
                            </div>
                            <div className="flex flex-wrap gap-1">
                                {product.match_variants.map((v) => (
                                    <Badge
                                        key={v}
                                        variant="outline"
                                        className="text-[10px] font-normal"
                                    >
                                        {v}
                                    </Badge>
                                ))}
                            </div>
                        </div>
                    )}
                    <TrackedUrlsEditor
                        clientId={clientId}
                        productId={product.id}
                        registeredDomains={domains}
                    />
                    <SalesChannelsEditor
                        clientId={clientId}
                        productId={product.id}
                        shadowBrands={shadowBrands}
                    />
                </div>
            )}
        </div>
    );
}
