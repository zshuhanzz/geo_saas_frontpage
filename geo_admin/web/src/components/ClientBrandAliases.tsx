import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Building2, CheckCircle2, Loader2, Plus, RefreshCw, Save, Warehouse, X } from "lucide-react";

import {
    getClientBrands,
    updateClientBrandAliases,
    type ClientBrand,
} from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

interface ClientBrandAliasesProps {
    clientId: string;
}

interface BrandAliasCardProps {
    brand: ClientBrand;
    refreshVersion: number;
    onSave: (brandId: string, aliases: string[]) => Promise<void>;
}

type SaveStatus = "idle" | "saving" | "success" | "error";

function aliasKey(value: string): string {
    return value.trim().toLowerCase();
}

function normalizeDraftAliases(values: string[]): string[] {
    const seen = new Set<string>();
    const normalized: string[] = [];
    for (const value of values) {
        const alias = value.trim();
        const key = aliasKey(alias);
        if (!alias || seen.has(key)) continue;
        seen.add(key);
        normalized.push(alias);
    }
    return normalized;
}

function BrandAliasCard({ brand, refreshVersion, onSave }: BrandAliasCardProps) {
    const canonicalSignature = JSON.stringify(brand.aliases || []);
    const [aliases, setAliases] = useState<string[]>(() => [...(brand.aliases || [])]);
    const [aliasInput, setAliasInput] = useState("");
    const [status, setStatus] = useState<SaveStatus>("idle");
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setAliases([...(brand.aliases || [])]);
        setAliasInput("");
        setStatus("idle");
        setError(null);
    }, [brand.id, canonicalSignature, refreshVersion]);

    const normalizedAliases = useMemo(() => normalizeDraftAliases(aliases), [aliases]);
    const isDirty = JSON.stringify(normalizedAliases) !== canonicalSignature;
    const saving = status === "saving";

    function addAlias(): void {
        const alias = aliasInput.trim();
        if (!alias) return;
        if (!aliases.some((current) => aliasKey(current) === aliasKey(alias))) {
            setAliases((current) => [...current, alias]);
        }
        setAliasInput("");
        setStatus("idle");
        setError(null);
    }

    async function save(): Promise<void> {
        setStatus("saving");
        setError(null);
        try {
            await onSave(brand.id, normalizedAliases);
            setStatus("success");
        } catch (err) {
            setStatus("error");
            setError((err as Error).message || "Unable to save aliases.");
        }
    }

    return (
        <Card className="border bg-card/60 p-4 shadow-none">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div className="font-semibold">{brand.brand_name}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                        {brand.is_shadow ? "Shadow Brand" : "Own Brand"}
                    </div>
                </div>
                <Button size="sm" onClick={save} disabled={saving || !isDirty}>
                    {saving ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                        <Save className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    {saving ? "Saving" : "Save Aliases"}
                </Button>
            </div>

            <div className="mt-3 flex min-h-7 flex-wrap items-center gap-1.5">
                {aliases.map((alias) => (
                    <Badge key={aliasKey(alias)} variant="outline" className="gap-1 py-0.5 pl-2 pr-1 text-xs">
                        {alias}
                        <button
                            type="button"
                            aria-label={`Remove ${alias}`}
                            className="rounded-full p-0.5 transition-colors hover:bg-muted hover:text-destructive"
                            disabled={saving}
                            onClick={() => {
                                setAliases((current) => current.filter((value) => value !== alias));
                                setStatus("idle");
                                setError(null);
                            }}
                        >
                            <X className="h-3 w-3" />
                        </button>
                    </Badge>
                ))}
                {aliases.length === 0 && (
                    <span className="text-xs italic text-muted-foreground">No aliases configured</span>
                )}
            </div>

            <div className="mt-2 flex max-w-lg gap-2">
                <Input
                    className="h-8 text-sm"
                    value={aliasInput}
                    disabled={saving}
                    placeholder="Type an alias and press Enter"
                    onChange={(event) => setAliasInput(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === "Enter") {
                            event.preventDefault();
                            addAlias();
                        }
                    }}
                />
                <Button type="button" size="sm" variant="secondary" className="h-8" disabled={saving} onClick={addAlias}>
                    <Plus className="mr-1 h-3.5 w-3.5" /> Add
                </Button>
            </div>

            {status === "success" && (
                <div className="mt-2 flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Saved to the canonical brand record.
                </div>
            )}
            {status === "error" && error && (
                <div className="mt-2 text-xs text-destructive" role="alert">{error}</div>
            )}
        </Card>
    );
}

export default function ClientBrandAliases({ clientId }: ClientBrandAliasesProps) {
    const [brands, setBrands] = useState<ClientBrand[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [refreshVersion, setRefreshVersion] = useState(0);
    const requestSequence = useRef(0);

    const refresh = useCallback(async (showLoading: boolean, resetDrafts: boolean): Promise<void> => {
        const requestId = ++requestSequence.current;
        if (showLoading) setLoading(true);
        setLoadError(null);
        try {
            const rows = await getClientBrands(clientId);
            if (requestId !== requestSequence.current) return;
            setBrands(rows);
            if (resetDrafts) setRefreshVersion((value) => value + 1);
        } catch (err) {
            if (requestId !== requestSequence.current) return;
            setLoadError((err as Error).message || "Unable to load brand aliases.");
        } finally {
            if (requestId === requestSequence.current) setLoading(false);
        }
    }, [clientId]);

    useEffect(() => {
        void refresh(true, true);
        return () => {
            requestSequence.current += 1;
        };
    }, [refresh]);

    async function saveAliases(brandId: string, aliases: string[]): Promise<void> {
        await updateClientBrandAliases(clientId, brandId, aliases);
        await refresh(false, false);
    }

    const ownBrands = brands.filter((brand) => !brand.is_shadow);
    const shadowBrands = brands.filter((brand) => brand.is_shadow);

    if (loading) {
        return (
            <div className="flex items-center gap-2 rounded-lg border bg-muted/20 p-4 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading brand aliases…
            </div>
        );
    }

    return (
        <section className="space-y-5" aria-labelledby="client-brand-aliases-title">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-3">
                <div>
                    <h3 id="client-brand-aliases-title" className="font-semibold">Brand Aliases</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                        Canonical aliases used by SaaS and Geo Analyzer. Each brand is saved independently.
                    </p>
                </div>
                <Button type="button" size="sm" variant="outline" onClick={() => void refresh(true, true)}>
                    <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
                </Button>
            </div>

            {loadError && (
                <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
                    {loadError}
                </div>
            )}

            <BrandGroup
                title="Own Brands"
                icon={<Building2 className="h-4 w-4 text-primary" />}
                emptyText="No active Own Brands"
                brands={ownBrands}
                refreshVersion={refreshVersion}
                onSave={saveAliases}
            />
            <BrandGroup
                title="Shadow Brands"
                icon={<Warehouse className="h-4 w-4 text-primary" />}
                emptyText="No active Shadow Brands"
                brands={shadowBrands}
                refreshVersion={refreshVersion}
                onSave={saveAliases}
            />
        </section>
    );
}

interface BrandGroupProps {
    title: string;
    icon: React.ReactNode;
    emptyText: string;
    brands: ClientBrand[];
    refreshVersion: number;
    onSave: (brandId: string, aliases: string[]) => Promise<void>;
}

function BrandGroup({ title, icon, emptyText, brands, refreshVersion, onSave }: BrandGroupProps) {
    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {icon} {title}
                <Badge variant="outline" className="ml-auto text-[10px]">{brands.length}</Badge>
            </div>
            {brands.length === 0 ? (
                <div className="rounded-lg border border-dashed py-5 text-center text-sm text-muted-foreground">{emptyText}</div>
            ) : (
                <div className="grid grid-cols-1 gap-3">
                    {brands.map((brand) => (
                        <BrandAliasCard
                            key={brand.id}
                            brand={brand}
                            refreshVersion={refreshVersion}
                            onSave={onSave}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
