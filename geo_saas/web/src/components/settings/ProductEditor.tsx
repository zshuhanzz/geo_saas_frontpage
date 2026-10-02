/**
 * ProductEditor — v1.2 compact form for a single Product row.
 *
 * Handles all three product_roles with a single UI:
 *   - own                    (under a Topic in the 追踪话题 Tab)
 *   - shadow_brand_product   (under a Shadow Brand in the 品牌 Tab)
 *   - peer                   (under a Peer in the 竞品 Tab)
 *
 * The Shadow-brand variant surfaces an "advanced options" section where the
 * user can pick `shadow_sub_role` (Spec §2.4): NULL (default, "不需要区分") /
 * 'native' (渠道自家品牌线) / 'resale' (渠道代理他人). When set to 'resale',
 * we optionally pin the SKU back to its Peer owner so Action Agent reports
 * can thread the channel attribution properly.
 *
 * The component is deliberately stateless (no list rendering) — the parent
 * SettingsPage owns the list + CRUD plumbing. Keeps this component easy to
 * reuse from the OnboardingWizard OEM flow too.
 */
import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import HelpTooltip from "@/components/ui/HelpTooltip";
import type { ShadowSubRole, ProductRole } from "@/lib/api";

// Radix Select can't bind to `null`, so we use a sentinel for "not set".
const SUB_ROLE_UNSET = "__unset__";
const OWNER_BRAND_UNVERIFIED = "__unverified__";

interface PeerOption {
    id: string;
    primary_name: string;
}

interface BrandOption {
    id: string;
    brand_name: string;
}

export interface ProductEditorValue {
    product_name: string;
    match_variants: string[];
    shadow_sub_role?: ShadowSubRole;
    owner_peer_id?: string | null;
    owner_brand_id?: string | null;
}

interface ProductEditorProps {
    role: ProductRole;
    initialValue?: Partial<ProductEditorValue>;
    /** Peer options needed only when role='shadow_brand_product' + sub_role='resale'. */
    peers?: PeerOption[];
    /** Active Own Brand options required when role='own'. */
    brands?: BrandOption[];
    onSubmit: (v: ProductEditorValue) => Promise<void> | void;
    onCancel?: () => void;
    submitLabel?: string;
    disabled?: boolean;
}

export function ProductEditor({
    role,
    initialValue,
    peers = [],
    brands = [],
    onSubmit,
    onCancel,
    submitLabel,
    disabled = false,
}: ProductEditorProps) {
    const { t } = useTranslation("settings");
    const effectiveSubmitLabel = submitLabel ?? t("products.submitDefault");
    const [productName, setProductName] = useState(initialValue?.product_name ?? "");
    const [variants, setVariants] = useState<string[]>(initialValue?.match_variants ?? []);
    const [newVariant, setNewVariant] = useState("");
    const [subRole, setSubRole] = useState<ShadowSubRole>(
        (initialValue?.shadow_sub_role as ShadowSubRole) ?? null,
    );
    const [ownerPeerId, setOwnerPeerId] = useState<string | null>(
        initialValue?.owner_peer_id ?? null,
    );
    const [ownerBrandId, setOwnerBrandId] = useState<string | null>(
        initialValue?.owner_brand_id ?? null,
    );
    const [advancedOpen, setAdvancedOpen] = useState(
        !!(initialValue?.shadow_sub_role || initialValue?.owner_peer_id),
    );
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (subRole !== "resale") setOwnerPeerId(null);
    }, [subRole]);

    function addVariant() {
        const v = newVariant.trim();
        if (!v) return;
        // Spec §5.2: variants under 3 chars emit warning; here we simply block
        // the add since the backend parser would log a warning for it.
        if (v.length < 3) return;
        if (variants.some((x) => x.toLowerCase() === v.toLowerCase())) {
            setNewVariant("");
            return;
        }
        setVariants([...variants, v]);
        setNewVariant("");
    }

    function removeVariant(v: string) {
        setVariants(variants.filter((x) => x !== v));
    }

    async function handleSubmit() {
        if (!productName.trim() || (role === "own" && !ownerBrandId)) return;
        setSaving(true);
        try {
            await onSubmit({
                product_name: productName.trim(),
                match_variants: variants,
                ...(role === "own" ? { owner_brand_id: ownerBrandId } : {}),
                ...(role === "shadow_brand_product"
                    ? {
                          shadow_sub_role: subRole,
                          owner_peer_id: subRole === "resale" ? ownerPeerId : null,
                      }
                    : {}),
            });
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="space-y-4 rounded-lg border bg-background/60 p-4">
            <div className="grid grid-cols-1 gap-3">
                <div className="space-y-1.5">
                    <Label className="text-xs">
                        <HelpTooltip content={t("tooltips.productName")}>{t("products.name")}</HelpTooltip>
                    </Label>
                    <Input
                        placeholder={t("products.namePlaceholder")}
                        value={productName}
                        onChange={(e) => setProductName(e.target.value)}
                        disabled={disabled || saving}
                    />
                </div>

                {role === "own" && (
                    <div className="space-y-1.5">
                        <Label className="text-xs">
                            <HelpTooltip content={t("products.ownerBrandHint")}>
                                {t("products.ownerBrand")}
                            </HelpTooltip>
                        </Label>
                        <Select
                            value={ownerBrandId ?? OWNER_BRAND_UNVERIFIED}
                            onValueChange={(value) => setOwnerBrandId(
                                value === OWNER_BRAND_UNVERIFIED ? null : value,
                            )}
                            disabled={disabled || saving}
                        >
                            <SelectTrigger className="max-w-sm">
                                <SelectValue placeholder={t("products.ownerBrandPlaceholder")} />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value={OWNER_BRAND_UNVERIFIED}>
                                    {t("products.ownerBrandUnverified")}
                                </SelectItem>
                                {brands.map((brand) => (
                                    <SelectItem key={brand.id} value={brand.id}>
                                        {brand.brand_name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                )}

                <div className="space-y-1.5">
                    <Label className="text-xs">
                        <HelpTooltip content={t("tooltips.matchVariants")}>{t("products.matchVariants")}</HelpTooltip>
                    </Label>
                    <div className="flex flex-wrap gap-1.5">
                        {variants.map((v) => (
                            <Badge key={v} variant="outline" className="pl-2 pr-1 py-0.5 text-xs">
                                {v}
                                <button
                                    type="button"
                                    onClick={() => removeVariant(v)}
                                    className="ml-1 rounded-full hover:bg-destructive/10 hover:text-destructive p-0.5"
                                    aria-label={t("products.matchVariantsRemoveAria", { variant: v })}
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </Badge>
                        ))}
                        {variants.length === 0 && (
                            <span className="text-xs text-muted-foreground/70 italic py-0.5">
                                {t("products.matchVariantsEmpty")}
                            </span>
                        )}
                    </div>
                    <div className="flex gap-2 max-w-sm">
                        <Input
                            placeholder={t("products.matchVariantsPlaceholder")}
                            value={newVariant}
                            onChange={(e) => setNewVariant(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                    e.preventDefault();
                                    addVariant();
                                }
                            }}
                            disabled={disabled || saving}
                            className="h-8 text-sm"
                        />
                        <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            onClick={addVariant}
                            disabled={disabled || saving || newVariant.trim().length < 3}
                            className="h-8"
                        >
                            <Plus className="h-3 w-3 mr-1" /> {t("products.matchVariantsAdd")}
                        </Button>
                    </div>
                    <p className="text-[11px] text-muted-foreground/80">
                        {t("products.matchVariantsHint")}
                    </p>
                </div>
            </div>

            {role === "shadow_brand_product" && (
                <div className="border-t pt-3">
                    <button
                        type="button"
                        onClick={() => setAdvancedOpen((v) => !v)}
                        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                        {advancedOpen ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                            <ChevronRight className="h-3.5 w-3.5" />
                        )}
                        <span>{t("products.advancedOptions")}</span>
                        <HelpTooltip content={t("tooltips.advancedOptions")} />
                    </button>

                    {advancedOpen && (
                        <div className="space-y-3 mt-3 pl-5">
                            <div className="space-y-1.5">
                                <Label className="text-xs">
                                    <HelpTooltip content={t("tooltips.productSubRole")}>
                                        {t("products.subRole")}
                                    </HelpTooltip>
                                </Label>
                                <Select
                                    value={subRole ?? SUB_ROLE_UNSET}
                                    onValueChange={(v) =>
                                        setSubRole(
                                            v === SUB_ROLE_UNSET
                                                ? null
                                                : (v as "native" | "resale"),
                                        )
                                    }
                                    disabled={disabled || saving}
                                >
                                    <SelectTrigger className="max-w-sm">
                                        <SelectValue placeholder={t("products.subRolePlaceholder")} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value={SUB_ROLE_UNSET}>
                                            {t("products.subRoleUnset")}
                                        </SelectItem>
                                        <SelectItem value="native">
                                            {t("products.subRoleNative")}
                                        </SelectItem>
                                        <SelectItem value="resale">
                                            {t("products.subRoleResale")}
                                        </SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>

                            {subRole === "resale" && peers.length > 0 && (
                                <div className="space-y-1.5">
                                    <Label className="text-xs">
                                        <HelpTooltip content={t("tooltips.ownerPeer")}>
                                            {t("products.ownerPeer")}
                                        </HelpTooltip>
                                    </Label>
                                    <Select
                                        value={ownerPeerId ?? ""}
                                        onValueChange={(v) =>
                                            setOwnerPeerId(v === "" ? null : v)
                                        }
                                        disabled={disabled || saving}
                                    >
                                        <SelectTrigger className="max-w-sm">
                                            <SelectValue placeholder={t("products.ownerPeerPlaceholder")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {peers.map((p) => (
                                                <SelectItem key={p.id} value={p.id}>
                                                    {p.primary_name}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t">
                {onCancel && (
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={onCancel}
                        disabled={saving}
                    >
                        {t("products.cancel")}
                    </Button>
                )}
                <Button
                    type="button"
                    size="sm"
                    onClick={handleSubmit}
                    disabled={saving || disabled || !productName.trim() || (role === "own" && !ownerBrandId)}
                >
                    {saving ? t("products.saving") : effectiveSubmitLabel}
                </Button>
            </div>
        </div>
    );
}

export default ProductEditor;
