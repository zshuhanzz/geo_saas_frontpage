/**
 * PeerPicker — schema-driven replacement for the peer pill selector in
 * Step2_Data. Registered under the custom field type `peer_picker`.
 *
 * v1.2 rewrite:
 *   - "Own brands" now live in `geo_client_brands` (is_shadow=false) — fetched
 *     via `/settings/brands?is_shadow=false`.
 *   - "Competitors" continue to live in `geo_client_peers` (the `is_own_brand`
 *     column is gone — peers are never own brands).
 *   - Both are merged into a single pill list; the form-state shape stays
 *     `string[]` of selected ids. Since brand ids and peer ids are both UUIDs
 *     they cannot collide.
 *
 * UX: own brands render in primary (green), competitors in amber. Keeps the
 * visual language identical to pre-v1.2 so the wizard feels unchanged.
 */
import { useEffect, useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { fetchJSON, API_BASE, getBrands, type Brand } from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

// Unified pill item — merges own-brand rows (from geo_client_brands) and
// competitor rows (from geo_client_peers) into a single selection space.
interface PickableItem {
    id: string;
    primary_name: string;
    is_own_brand: boolean;
}

interface PeerRow {
    id: string;
    primary_name: string;
}

function PeerPicker({ value, onChange, context, disabled }: CustomFieldProps) {
    const [peers, setPeers] = useState<PickableItem[] | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!context.clientId) return;
        let cancelled = false;
        const clientId = context.clientId;

        // Fetch own brands and peers in parallel; merge on success. If one
        // call fails we still render the other (degraded — the wizard should
        // not block on a missing brand list).
        Promise.allSettled([
            getBrands(clientId, false),
            fetchJSON(`${API_BASE}/settings/peers?client_id=${clientId}`) as Promise<PeerRow[]>,
        ])
            .then(([brandsRes, peersRes]) => {
                if (cancelled) return;
                const items: PickableItem[] = [];
                if (brandsRes.status === "fulfilled" && Array.isArray(brandsRes.value)) {
                    for (const b of brandsRes.value as Brand[]) {
                        items.push({ id: b.id, primary_name: b.brand_name, is_own_brand: true });
                    }
                }
                if (peersRes.status === "fulfilled" && Array.isArray(peersRes.value)) {
                    for (const p of peersRes.value as PeerRow[]) {
                        items.push({ id: p.id, primary_name: p.primary_name, is_own_brand: false });
                    }
                }
                // Surface an error only if both calls failed — otherwise the
                // partial list is preferable to a blocking error state.
                if (brandsRes.status === "rejected" && peersRes.status === "rejected") {
                    setError("Failed to load brands and competitors");
                    setPeers([]);
                    return;
                }
                setPeers(items);
            });

        return () => {
            cancelled = true;
        };
    }, [context.clientId]);

    const selected: string[] = Array.isArray(value) ? (value as string[]) : [];
    const toggle = (id: string) => {
        const next = selected.includes(id)
            ? selected.filter((p) => p !== id)
            : [...selected, id];
        onChange(next, true);
    };

    if (peers === null) {
        return (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-3">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading brands and competitors…
            </div>
        );
    }
    if (error) {
        return (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                Failed to load peers: {error}
            </div>
        );
    }
    if (peers.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border/60 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                No brands or competitors configured — add them in Client Settings → Brands & Competitors
            </div>
        );
    }

    const own = peers.filter((p) => p.is_own_brand);
    const comp = peers.filter((p) => !p.is_own_brand);

    // Description rendered by outer FieldWrapper.
    return (
        <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
                {own.map((peer) => {
                    const on = selected.includes(peer.id);
                    return (
                        <button
                            key={peer.id}
                            type="button"
                            onClick={() => toggle(peer.id)}
                            disabled={disabled}
                            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 text-xs font-medium transition-all ${
                                on
                                    ? "border-primary bg-primary/10 text-primary"
                                    : "border-border hover:border-primary/40 text-foreground"
                            } disabled:opacity-50`}
                        >
                            <span className="w-2 h-2 rounded-full bg-primary shrink-0" />
                            {peer.primary_name}
                            {on && <CheckCircle2 className="h-3 w-3" />}
                        </button>
                    );
                })}
                {comp.length > 0 && own.length > 0 && (
                    <div className="w-px h-6 bg-border self-center mx-1" />
                )}
                {comp.map((peer) => {
                    const on = selected.includes(peer.id);
                    return (
                        <button
                            key={peer.id}
                            type="button"
                            onClick={() => toggle(peer.id)}
                            disabled={disabled}
                            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 text-xs font-medium transition-all ${
                                on
                                    ? "border-amber-500 bg-amber-500/10 text-amber-500"
                                    : "border-border hover:border-amber-500/40 text-muted-foreground"
                            } disabled:opacity-50`}
                        >
                            <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
                            {peer.primary_name}
                            {on && <CheckCircle2 className="h-3 w-3" />}
                        </button>
                    );
                })}
            </div>
            {selected.length === 0 && (
                <p className="text-[11px] text-muted-foreground/70">
                    None selected — analysis will include all brands and competitors
                </p>
            )}
        </div>
    );
}

registerCustomField("peer_picker", PeerPicker);

export default PeerPicker;
