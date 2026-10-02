import { Package, PauseCircle, PlayCircle, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { TopicProduct } from "@/lib/api";

interface ProductRowProps {
    product: TopicProduct;
    topicName?: string;
    onDelete: () => void;
    onSetActive: (isActive: boolean) => void;
    statusUpdating?: boolean;
    deleteLabel?: string;
}

export default function ProductRow({
    product,
    topicName,
    onDelete,
    onSetActive,
    statusUpdating = false,
    deleteLabel,
}: ProductRowProps) {
    const { t } = useTranslation("settings");
    return (
        <div className={`flex items-center gap-2 px-3 py-2 rounded-md border bg-background ${product.is_active ? "" : "opacity-70"}`}>
            <Package className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <span className="text-sm font-medium truncate flex-1">{product.product_name}</span>
            {!product.is_active && (
                <Badge variant="secondary" className="text-[10px] font-normal shrink-0">
                    {t("products.statusInactive")}
                </Badge>
            )}
            {topicName && (
                <Badge variant="outline" className="text-[10px] font-normal shrink-0">
                    {topicName}
                </Badge>
            )}
            {product.shadow_sub_role && (
                <Badge variant="secondary" className="text-[10px] font-normal shrink-0">
                    {product.shadow_sub_role === "native" ? t("ownProductCard.subRoleNative") : t("ownProductCard.subRoleResale")}
                </Badge>
            )}
            <Button
                variant="ghost"
                size="sm"
                disabled={statusUpdating}
                className="h-7 px-2 text-xs text-muted-foreground"
                onClick={() => onSetActive(!product.is_active)}
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
                onClick={onDelete}
                aria-label={deleteLabel || t("products.deletePermanently")}
                title={deleteLabel || t("products.deletePermanently")}
            >
                <Trash2 className="h-3.5 w-3.5" />
            </Button>
        </div>
    );
}
