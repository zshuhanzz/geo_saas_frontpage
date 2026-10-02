/**
 * TrackedUrlsEditor — v1.2 Product-level URL bindings.
 *
 * For a given Product (Own / Shadow / Peer), list its `geo_product_tracked_urls`
 * rows and allow add / delete. A "new URL" form surfaces:
 *
 *   - URL input (text)
 *   - url_scope radio: 精确 URL | 路径前缀 (Spec §4.2.6)
 *   - Front-end URL-host validation: the host must match a registered domain
 *     for this client (see the `_infer_url_owner` helper in the backend
 *     settings router). This is a UX nicety — the DB trigger is the actual
 *     source of truth, but failing fast here gives a friendly error before
 *     the POST round-trip.
 *
 * Deliberately does NOT implement "triggers auto-discovery" here — that's a
 * Phase 6 concern (Suggestions pipeline). The spec calls for a hook; for
 * Phase 5 we leave the comment + an empty button stub out so the placeholder
 * is clearly visible when Phase 6 ships.
 */
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Link2, Plus, Trash2, AlertCircle, Loader2, ExternalLink } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import HelpTooltip from "@/components/ui/HelpTooltip";
import {
    addTrackedUrl,
    listTrackedUrls,
    removeTrackedUrl,
    type TrackedUrl,
    type UrlScope,
} from "@/lib/api";

interface TrackedUrlsEditorProps {
    clientId: string;
    productId: string;
    /** Domains registered for this client, used for host validation hints. */
    registeredDomains: { id: string; domain: string }[];
}

function extractHost(u: string): string | null {
    if (!u) return null;
    let raw = u.trim();
    if (!/^https?:\/\//i.test(raw)) raw = "https://" + raw;
    try {
        const host = new URL(raw).host.toLowerCase();
        return host.startsWith("www.") ? host.slice(4) : host;
    } catch {
        return null;
    }
}

export function TrackedUrlsEditor({ clientId, productId, registeredDomains }: TrackedUrlsEditorProps) {
    const { t } = useTranslation("settings");
    const [urls, setUrls] = useState<TrackedUrl[]>([]);
    const [loading, setLoading] = useState(false);
    const [adding, setAdding] = useState(false);
    const [formOpen, setFormOpen] = useState(false);

    // Form state
    const [newUrl, setNewUrl] = useState("");
    const [newScope, setNewScope] = useState<UrlScope>("exact");

    // Normalize registered domains for O(1) host lookup.
    const registeredHosts = useMemo(
        () =>
            new Set(
                registeredDomains
                    .map((d) => (d.domain || "").trim().toLowerCase())
                    .map((d) => (d.startsWith("www.") ? d.slice(4) : d))
                    .filter(Boolean),
            ),
        [registeredDomains],
    );

    const inferredHost = extractHost(newUrl);
    // We match by suffix too so `amazon.com/stores/mybrand` counts as matched
    // when only `amazon.com` is registered. This mirrors the Python trigger's
    // domain_scope='whole' semantics.
    const hostKnown = !!(
        inferredHost &&
        (registeredHosts.has(inferredHost) ||
            Array.from(registeredHosts).some((h) => inferredHost.endsWith(h)))
    );

    useEffect(() => {
        loadUrls();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clientId, productId]);

    async function loadUrls() {
        setLoading(true);
        try {
            setUrls(await listTrackedUrls(clientId, productId));
        } catch (e: any) {
            toast.error(`${t("trackedUrls.loadFailedToast")}: ${e?.message || t("toasts.unknownError")}`);
        } finally {
            setLoading(false);
        }
    }

    async function handleAdd() {
        if (!newUrl.trim()) return;
        setAdding(true);
        try {
            await addTrackedUrl(clientId, productId, {
                url: newUrl.trim(),
                url_scope: newScope,
            });
            setNewUrl("");
            setNewScope("exact");
            setFormOpen(false);
            await loadUrls();
            toast.success(t("trackedUrls.addedToast"));
        } catch (e: any) {
            toast.error(e?.message || t("trackedUrls.addFailedToast"));
        } finally {
            setAdding(false);
        }
    }

    async function handleRemove(id: string) {
        try {
            await removeTrackedUrl(clientId, productId, id);
            await loadUrls();
        } catch (e: any) {
            toast.error(e?.message || t("trackedUrls.deleteFailedToast"));
        }
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    <Link2 className="h-3.5 w-3.5" />
                    <HelpTooltip content={t("tooltips.trackedUrlsSection")}>{t("trackedUrls.title")}</HelpTooltip>
                </div>
                {!formOpen && (
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => setFormOpen(true)}
                    >
                        <Plus className="h-3 w-3 mr-1" /> {t("trackedUrls.addButton")}
                    </Button>
                )}
            </div>

            {loading ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                    <Loader2 className="h-3 w-3 animate-spin" /> {t("trackedUrls.loading")}
                </div>
            ) : urls.length === 0 ? (
                <div className="text-xs text-muted-foreground/80 italic py-2">
                    {t("trackedUrls.empty")}
                </div>
            ) : (
                <div className="space-y-1.5">
                    {urls.map((u) => (
                        <div
                            key={u.id}
                            className="flex items-center gap-2 px-3 py-2 rounded-md border bg-background"
                        >
                            <Badge
                                variant={u.url_scope === "path-prefix" ? "secondary" : "outline"}
                                className="text-[10px] font-normal shrink-0"
                            >
                                {t(u.url_scope === "path-prefix" ? "trackedUrls.scopePathPrefix" : "trackedUrls.scopeExact")}
                            </Badge>
                            <span className="text-xs font-mono truncate flex-1" title={u.url}>
                                {u.url}
                            </span>
                            <a
                                href={u.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="h-7 w-7 p-0 flex items-center justify-center rounded-md text-muted-foreground hover:text-primary hover:bg-muted transition-colors"
                                title={t("trackedUrls.openInNewTabHint")}
                            >
                                <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                                onClick={() => handleRemove(u.id)}
                                title={t("trackedUrls.deleteHint")}
                            >
                                <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                        </div>
                    ))}
                </div>
            )}

            {formOpen && (
                <div className="rounded-md border border-dashed p-3 space-y-3 bg-muted/10">
                    <div className="space-y-1.5">
                        <Label className="text-xs">
                            <HelpTooltip content={t("tooltips.trackedUrlInput")}>URL</HelpTooltip>
                        </Label>
                        <Input
                            value={newUrl}
                            onChange={(e) => setNewUrl(e.target.value)}
                            placeholder="https://amazon.com/stores/mybrand/product/ht-70911"
                            className="text-xs font-mono"
                            disabled={adding}
                        />
                        {newUrl.trim() && inferredHost && !hostKnown && (
                            <div className="flex items-start gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
                                <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" />
                                <span>
                                    <Trans
                                        i18nKey="trackedUrls.unregisteredDomainWarning"
                                        ns="settings"
                                        values={{ host: inferredHost }}
                                        components={{ 1: <code className="font-mono" /> }}
                                    />
                                </span>
                            </div>
                        )}
                    </div>

                    <div className="space-y-1.5">
                        <Label className="text-xs">
                            <HelpTooltip content={t("tooltips.urlScope")}>{t("trackedUrls.scope")}</HelpTooltip>
                        </Label>
                        <div className="flex gap-2">
                            {(
                                [
                                    { value: "exact", labelKey: "scopeExact" },
                                    { value: "path-prefix", labelKey: "scopePathPrefix" },
                                ] as const
                            ).map((opt) => (
                                <button
                                    key={opt.value}
                                    type="button"
                                    onClick={() => setNewScope(opt.value)}
                                    disabled={adding}
                                    className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                                        newScope === opt.value
                                            ? "border-primary bg-primary/10 text-primary font-medium"
                                            : "border-border hover:bg-muted text-muted-foreground"
                                    }`}
                                >
                                    {t(`trackedUrls.${opt.labelKey}`)}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="flex justify-end gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => {
                                setFormOpen(false);
                                setNewUrl("");
                            }}
                            disabled={adding}
                        >
                            {t("trackedUrls.cancel")}
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            onClick={handleAdd}
                            disabled={adding || !newUrl.trim()}
                        >
                            {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t("trackedUrls.save")}
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}

export default TrackedUrlsEditor;
