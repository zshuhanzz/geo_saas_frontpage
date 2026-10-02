/**
 * SalesChannelsEditor — declares which Shadow Brand(s) a given Own product
 * is sold through. Writes to `geo_product_sales_channels` (product_id,
 * brand_id).
 *
 * The Shadow brand dropdown is fed by the parent (we don't fetch brands
 * internally) so the SettingsPage keeps a single source-of-truth for brand
 * lists and cache invalidation stays straightforward.
 */
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Loader2, Store, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import HelpTooltip from "@/components/ui/HelpTooltip";
import {
    addSalesChannel,
    listSalesChannels,
    removeSalesChannel,
    type Brand,
    type SalesChannel,
} from "@/lib/api";

interface SalesChannelsEditorProps {
    clientId: string;
    productId: string;
    shadowBrands: Brand[]; // is_shadow=true only — we don't render Own brands here
}

export function SalesChannelsEditor({
    clientId,
    productId,
    shadowBrands,
}: SalesChannelsEditorProps) {
    const { t } = useTranslation("settings");
    const [channels, setChannels] = useState<SalesChannel[]>([]);
    const [loading, setLoading] = useState(false);
    const [adding, setAdding] = useState(false);

    const brandById = new Map(shadowBrands.map((b) => [b.id, b]));
    const available = shadowBrands.filter(
        (b) => !channels.some((c) => c.brand_id === b.id),
    );

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clientId, productId]);

    async function load() {
        setLoading(true);
        try {
            setChannels(await listSalesChannels(clientId, productId));
        } catch (e: any) {
            toast.error(`${t("salesChannels.loadFailedToast")}: ${e?.message || t("toasts.unknownError")}`);
        } finally {
            setLoading(false);
        }
    }

    async function handleAdd(brandId: string) {
        if (!brandId) return;
        setAdding(true);
        try {
            await addSalesChannel(clientId, productId, { brand_id: brandId });
            await load();
        } catch (e: any) {
            toast.error(e?.message || t("salesChannels.addFailedToast"));
        } finally {
            setAdding(false);
        }
    }

    async function handleRemove(brandId: string) {
        try {
            await removeSalesChannel(clientId, productId, brandId);
            await load();
        } catch (e: any) {
            toast.error(e?.message || t("salesChannels.deleteFailedToast"));
        }
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                <Store className="h-3.5 w-3.5" />
                <HelpTooltip content={t("tooltips.salesChannels")}>{t("salesChannels.title")}</HelpTooltip>
            </div>

            {loading ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                    <Loader2 className="h-3 w-3 animate-spin" /> {t("salesChannels.loading")}
                </div>
            ) : (
                <div className="flex flex-wrap items-center gap-1.5">
                    {channels.map((c) => {
                        const b = brandById.get(c.brand_id);
                        return (
                            <Badge
                                key={c.brand_id}
                                variant="outline"
                                className="text-xs pl-2 pr-1 py-0.5"
                            >
                                {b?.brand_name || c.brand_id.slice(0, 8)}
                                <button
                                    type="button"
                                    onClick={() => handleRemove(c.brand_id)}
                                    className="ml-1 rounded-full hover:bg-destructive/10 hover:text-destructive p-0.5"
                                    aria-label={t("salesChannels.removeAria")}
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </Badge>
                        );
                    })}

                    {available.length > 0 ? (
                        <Select
                            value=""
                            onValueChange={(v) => handleAdd(v)}
                            disabled={adding}
                        >
                            <SelectTrigger className="h-7 w-[180px] text-xs">
                                <SelectValue placeholder={t("salesChannels.addPlaceholder")} />
                            </SelectTrigger>
                            <SelectContent>
                                {available.map((b) => (
                                    <SelectItem key={b.id} value={b.id}>
                                        {b.brand_name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    ) : channels.length === 0 ? (
                        <span className="text-xs text-muted-foreground/70 italic">
                            {t("salesChannels.empty")}
                        </span>
                    ) : null}
                </div>
            )}
        </div>
    );
}

export default SalesChannelsEditor;
