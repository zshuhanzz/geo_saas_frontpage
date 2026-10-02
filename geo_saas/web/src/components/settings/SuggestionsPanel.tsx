/**
 * SuggestionsPanel — Phase 6 AI-discovered candidate triage UI.
 *
 * The per-tab banner ("💡 AI 发现 N 条候选") expands into this panel. Users
 * see each candidate's string, frequency, source, sample response_ids, and
 * can either:
 *   - Accept → opens a target-picker Dialog (Topic / Brand / Peer / Product
 *     depending on candidate_type) and POSTs `/candidates/:id/accept`.
 *   - Reject / Ignore → simple status-update POST.
 *
 * Props support two modes:
 *   - `candidateType` set → filter to a single type (per-tab embedding).
 *   - `candidateType` unset → show everything (global "AI 建议" entry).
 *
 * The component refetches on mount and after every successful mutation. The
 * parent Tab / page can pass an `onDelta` callback to refresh its own pending
 * counts.
 */
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Sparkles, Loader2, CheckCircle2, X, Ban, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import HelpTooltip from "@/components/ui/HelpTooltip";
import {
    listCandidates,
    acceptCandidate,
    rejectCandidate,
    ignoreCandidate,
    getTopics,
    getBrands,
    getPeers,
    listOwnProducts,
    listShadowBrandProducts,
    listPeerProducts,
    type SettingsCandidate,
    type CandidateType,
    type CandidateAcceptBody,
    type Brand,
    type TopicProduct,
    type UrlScope,
} from "@/lib/api";

// Picker required fields by candidate_type.
const PICKER_REQUIREMENTS: Record<CandidateType, {
    needTopic: boolean;
    needBrand: boolean;
    needPeer: boolean;
    needProduct: boolean;
    needUrlScope: boolean;
}> = {
    brand: { needTopic: false, needBrand: false, needPeer: false, needProduct: false, needUrlScope: false },
    shadow_brand: { needTopic: false, needBrand: false, needPeer: false, needProduct: false, needUrlScope: false },
    peer: { needTopic: false, needBrand: false, needPeer: false, needProduct: false, needUrlScope: false },
    own_product: { needTopic: true, needBrand: true, needPeer: false, needProduct: false, needUrlScope: false },
    shadow_product: { needTopic: true, needBrand: true, needPeer: false, needProduct: false, needUrlScope: false },
    peer_product: { needTopic: true, needBrand: false, needPeer: true, needProduct: false, needUrlScope: false },
    tracked_url: { needTopic: false, needBrand: false, needPeer: false, needProduct: true, needUrlScope: true },
};

interface SuggestionsPanelProps {
    clientId: string;
    /** Allow candidate browsing while disabling accept/reject/ignore writes. */
    readOnly?: boolean;
    /** Filter to a single candidate_type, or leave undefined for all. */
    candidateType?: CandidateType;
    /** Filter to an arbitrary set of candidate_types (per-tab banner passes
     *  every type the tab is responsible for). Takes precedence over
     *  `candidateType` when non-empty. Fetches without a server-side type
     *  filter and narrows client-side so the backend contract stays
     *  single-type. */
    candidateTypes?: CandidateType[];
    /** Called after any mutation (accept / reject / ignore) so the parent
     *  can refresh its per-tab pending count. */
    onDelta?: () => void;
    /** Optional className for container wrapping. */
    className?: string;
}

interface TopicOption { id: string; topic_name: string }
interface PeerOption { id: string; primary_name: string }
interface ProductOption { id: string; product_name: string }

export function SuggestionsPanel({
    clientId,
    readOnly = false,
    candidateType,
    candidateTypes,
    onDelta,
    className,
}: SuggestionsPanelProps) {
    const { t } = useTranslation("settings");
    const [items, setItems] = useState<SettingsCandidate[]>([]);
    const [loading, setLoading] = useState(false);
    const [busyId, setBusyId] = useState<string | null>(null);

    // Picker options loaded lazily on Dialog open.
    const [topics, setTopics] = useState<TopicOption[]>([]);
    const [brands, setBrands] = useState<Brand[]>([]);
    const [peers, setPeers] = useState<PeerOption[]>([]);
    const [products, setProducts] = useState<ProductOption[]>([]);
    const [pickerLoading, setPickerLoading] = useState(false);

    // Dialog state
    const [openItem, setOpenItem] = useState<SettingsCandidate | null>(null);
    const [pickerTopicId, setPickerTopicId] = useState<string>("");
    const [pickerBrandId, setPickerBrandId] = useState<string>("");
    const [pickerPeerId, setPickerPeerId] = useState<string>("");
    const [pickerProductId, setPickerProductId] = useState<string>("");
    const [pickerUrlScope, setPickerUrlScope] = useState<UrlScope>("exact");
    const [overrideString, setOverrideString] = useState<string>("");

    const typesKey = (candidateTypes || []).join(",");
    const reload = async () => {
        setLoading(true);
        try {
            // When a multi-type filter is supplied, drop the server-side
            // type filter and narrow client-side — the REST endpoint only
            // accepts a single `type=` param.
            const serverType = (candidateTypes && candidateTypes.length > 0) ? undefined : candidateType;
            const list = await listCandidates(clientId, serverType, "pending");
            const filtered = (candidateTypes && candidateTypes.length > 0)
                ? list.filter((c) => candidateTypes.includes(c.candidate_type))
                : list;
            setItems(filtered);
        } catch (err: any) {
            toast.error(err?.message || t("suggestions.toasts.loadFailed"));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (clientId) reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clientId, candidateType, typesKey]);

    const loadPickerOptionsFor = async (item: SettingsCandidate) => {
        setPickerLoading(true);
        try {
            const req = PICKER_REQUIREMENTS[item.candidate_type];
            const jobs: Promise<unknown>[] = [];
            if (req.needTopic) jobs.push(getTopics(clientId).then(setTopics));
            if (req.needBrand) {
                const isShadow = item.candidate_type === "own_product" ? false : true;
                jobs.push(getBrands(clientId, isShadow).then((rows) => {
                    setBrands(rows.filter((brand) => brand.is_active));
                }));
            }
            if (req.needPeer) jobs.push(getPeers(clientId).then(setPeers));
            if (req.needProduct) {
                // Tracked URL must attach to a product — load all three roles
                // and let the user pick. Keep the three lists flat.
                const brandsAll = await getBrands(clientId);
                const peersAll = await getPeers(clientId) as PeerOption[];
                const topicsAll = await getTopics(clientId) as TopicOption[];
                const productLists: TopicProduct[][] = await Promise.all([
                    ...topicsAll.map((t) => listOwnProducts(clientId, t.id).catch(() => [])),
                    ...brandsAll.filter((b) => b.is_shadow).map((b) => listShadowBrandProducts(clientId, b.id).catch(() => [])),
                    ...peersAll.map((p) => listPeerProducts(clientId, p.id).catch(() => [])),
                ]);
                const flat = productLists.flat().map((p) => ({ id: p.id, product_name: p.product_name }));
                setProducts(flat);
            }
            await Promise.all(jobs);
        } catch (err: any) {
            toast.error(err?.message || t("suggestions.toasts.optionLoadFailed"));
        } finally {
            setPickerLoading(false);
        }
    };

    const openAccept = (item: SettingsCandidate) => {
        setOpenItem(item);
        setPickerTopicId(item.suggested_target_topic_id || "");
        setPickerBrandId(item.suggested_target_brand_id || "");
        setPickerPeerId(item.suggested_target_peer_id || "");
        setPickerProductId("");
        setPickerUrlScope("exact");
        setOverrideString(item.candidate_string);
        void loadPickerOptionsFor(item);
    };

    const closeDialog = () => {
        setOpenItem(null);
        setPickerTopicId("");
        setPickerBrandId("");
        setPickerPeerId("");
        setPickerProductId("");
        setOverrideString("");
    };

    const submitAccept = async () => {
        if (!openItem) return;
        const req = PICKER_REQUIREMENTS[openItem.candidate_type];
        if (req.needTopic && !pickerTopicId) {
            toast.error(t("suggestions.toasts.needTopic"));
            return;
        }
        if (req.needBrand && !pickerBrandId) {
            toast.error(t(openItem.candidate_type === "own_product"
                ? "suggestions.toasts.needOwnBrand"
                : "suggestions.toasts.needShadow"));
            return;
        }
        if (req.needPeer && !pickerPeerId) {
            toast.error(t("suggestions.toasts.needPeer"));
            return;
        }
        if (req.needProduct && !pickerProductId) {
            toast.error(t("suggestions.toasts.needProduct"));
            return;
        }
        const body: CandidateAcceptBody = {};
        if (req.needTopic) body.target_topic_id = pickerTopicId;
        if (req.needBrand) body.target_brand_id = pickerBrandId;
        if (req.needPeer) body.target_peer_id = pickerPeerId;
        if (req.needProduct) body.target_product_id = pickerProductId;
        if (req.needUrlScope) body.url_scope = pickerUrlScope;
        const trimmed = overrideString.trim();
        if (trimmed && trimmed !== openItem.candidate_string) {
            body.override_string = trimmed;
        }

        setBusyId(openItem.id);
        try {
            await acceptCandidate(clientId, openItem.id, body);
            toast.success(t("suggestions.toasts.accepted"));
            closeDialog();
            await reload();
            onDelta?.();
        } catch (err: any) {
            toast.error(err?.message || t("suggestions.toasts.acceptFailed"));
        } finally {
            setBusyId(null);
        }
    };

    const doReject = async (item: SettingsCandidate) => {
        setBusyId(item.id);
        try {
            await rejectCandidate(clientId, item.id);
            toast.success(t("suggestions.toasts.rejected"));
            await reload();
            onDelta?.();
        } catch (err: any) {
            toast.error(err?.message || t("suggestions.toasts.rejectFailed"));
        } finally {
            setBusyId(null);
        }
    };

    const doIgnore = async (item: SettingsCandidate) => {
        setBusyId(item.id);
        try {
            await ignoreCandidate(clientId, item.id);
            toast.success(t("suggestions.toasts.ignored"));
            await reload();
            onDelta?.();
        } catch (err: any) {
            toast.error(err?.message || t("suggestions.toasts.ignoreFailed"));
        } finally {
            setBusyId(null);
        }
    };

    const header = useMemo(() => {
        const label = (ct: CandidateType) => t(`suggestions.candidateTypes.${ct}`);
        if (candidateTypes && candidateTypes.length > 0) {
            return candidateTypes.map(label).join(" / ");
        }
        return candidateType ? label(candidateType) : t("suggestions.allCandidates");
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [candidateType, typesKey, t]);

    return (
        <div className={className}>
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Sparkles className="h-4 w-4 text-primary" />
                    <HelpTooltip content={t("tooltips.suggestionsPanelHeader")}>
                        <span>{t("suggestions.panelHeaderPrefix")}{header}</span>
                    </HelpTooltip>
                    <Badge variant="outline" className="text-[10px]">{items.length}</Badge>
                </div>
                <Button variant="ghost" size="sm" onClick={() => void reload()} disabled={loading}>
                    <RefreshCw className={`h-3.5 w-3.5 mr-1 ${loading ? "animate-spin" : ""}`} />
                    {t("suggestions.panelRefresh")}
                </Button>
            </div>

            {loading ? (
                <div className="flex py-6 items-center justify-center text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("suggestions.panelLoading")}
                </div>
            ) : items.length === 0 ? (
                <Card className="border-dashed bg-muted/20">
                    <CardContent className="py-8 text-center text-xs text-muted-foreground">
                        {t("suggestions.empty")}
                    </CardContent>
                </Card>
            ) : (
                <div className="space-y-2">
                    {items.map((item) => (
                        <Card key={item.id} className="border-muted/60">
                            <CardContent className="py-3 px-4 flex items-center gap-3">
                                <div className="flex-1 min-w-0 space-y-1">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-mono text-sm text-foreground truncate">
                                            {item.candidate_string}
                                        </span>
                                        <Badge variant="secondary" className="text-[10px]">
                                            {t(`suggestions.candidateTypes.${item.candidate_type}`)}
                                        </Badge>
                                        <Badge variant="outline" className="text-[10px]">
                                            {t("suggestions.candidateFrequency", { count: item.frequency })}
                                        </Badge>
                                        <Badge variant="outline" className="text-[10px]">
                                            {t("suggestions.candidateSource", { source: item.source })}
                                        </Badge>
                                    </div>
                                    <div className="text-[11px] text-muted-foreground">
                                        {item.sample_response_ids && item.sample_response_ids.length > 0 && (
                                            <span>
                                                {t("suggestions.candidateSamplePrefix")}{" "}
                                                {item.sample_response_ids.slice(0, 3).map((rid) => (
                                                    <span key={rid} className="font-mono mr-1">#{rid}</span>
                                                ))}
                                            </span>
                                        )}
                                        <span className="ml-2">{t("suggestions.candidateLastSeen", { date: new Date(item.last_seen).toLocaleDateString() })}</span>
                                    </div>
                                </div>
                                <div className="flex items-center gap-1.5 shrink-0">
                                    <Button
                                        size="sm"
                                        variant="default"
                                        disabled={readOnly || busyId === item.id}
                                        onClick={() => openAccept(item)}
                                    >
                                        <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> {t("suggestions.actions.accept")}
                                    </Button>
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={readOnly || busyId === item.id}
                                        onClick={() => void doReject(item)}
                                    >
                                        <X className="h-3.5 w-3.5 mr-1" /> {t("suggestions.actions.reject")}
                                    </Button>
                                    <Button
                                        size="sm"
                                        variant="ghost"
                                        disabled={readOnly || busyId === item.id}
                                        onClick={() => void doIgnore(item)}
                                    >
                                        <Ban className="h-3.5 w-3.5 mr-1" /> {t("suggestions.actions.ignore")}
                                    </Button>
                                </div>
                            </CardContent>
                        </Card>
                    ))}
                </div>
            )}

            {/* Accept Dialog — picker depends on candidate_type */}
            <Dialog open={openItem !== null} onOpenChange={(v) => { if (!v) closeDialog(); }}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>{t("suggestions.dialog.title")}</DialogTitle>
                        <DialogDescription>
                            {openItem && (
                                <>
                                    {t("suggestions.dialog.candidateLabel")}<span className="font-mono">{openItem.candidate_string}</span>{" "}
                                    {t("suggestions.dialog.typeLabel")}{t(`suggestions.candidateTypes.${openItem.candidate_type}`)}
                                </>
                            )}
                        </DialogDescription>
                    </DialogHeader>

                    {openItem && (
                        <div className="space-y-4 py-2">
                            <div className="space-y-1.5">
                                <Label>{t("suggestions.dialog.nameLabel")}</Label>
                                <Input
                                    value={overrideString}
                                    onChange={(e) => setOverrideString(e.target.value)}
                                />
                            </div>

                            {PICKER_REQUIREMENTS[openItem.candidate_type].needTopic && (
                                <div className="space-y-1.5">
                                    <Label>{t("suggestions.dialog.topicLabel")}</Label>
                                    <Select value={pickerTopicId} onValueChange={setPickerTopicId}>
                                        <SelectTrigger>
                                            <SelectValue placeholder={pickerLoading ? t("suggestions.dialog.pickerLoading") : t("suggestions.dialog.topicPlaceholder")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {topics.map((t) => (
                                                <SelectItem key={t.id} value={t.id}>{t.topic_name}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}

                            {PICKER_REQUIREMENTS[openItem.candidate_type].needBrand && (
                                <div className="space-y-1.5">
                                    <Label>{t(openItem.candidate_type === "own_product"
                                        ? "suggestions.dialog.ownBrandLabel"
                                        : "suggestions.dialog.shadowLabel")}</Label>
                                    <Select value={pickerBrandId} onValueChange={setPickerBrandId}>
                                        <SelectTrigger>
                                            <SelectValue placeholder={pickerLoading
                                                ? t("suggestions.dialog.pickerLoading")
                                                : t(openItem.candidate_type === "own_product"
                                                    ? "suggestions.dialog.ownBrandPlaceholder"
                                                    : "suggestions.dialog.shadowPlaceholder")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {brands.map((b) => (
                                                <SelectItem key={b.id} value={b.id}>{b.brand_name}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}

                            {PICKER_REQUIREMENTS[openItem.candidate_type].needPeer && (
                                <div className="space-y-1.5">
                                    <Label>{t("suggestions.dialog.peerLabel")}</Label>
                                    <Select value={pickerPeerId} onValueChange={setPickerPeerId}>
                                        <SelectTrigger>
                                            <SelectValue placeholder={pickerLoading ? t("suggestions.dialog.pickerLoading") : t("suggestions.dialog.peerPlaceholder")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {peers.map((p) => (
                                                <SelectItem key={p.id} value={p.id}>{p.primary_name}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}

                            {PICKER_REQUIREMENTS[openItem.candidate_type].needProduct && (
                                <div className="space-y-1.5">
                                    <Label>{t("suggestions.dialog.productLabel")}</Label>
                                    <Select value={pickerProductId} onValueChange={setPickerProductId}>
                                        <SelectTrigger>
                                            <SelectValue placeholder={pickerLoading ? t("suggestions.dialog.pickerLoading") : t("suggestions.dialog.productPlaceholder")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {products.map((p) => (
                                                <SelectItem key={p.id} value={p.id}>{p.product_name}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}

                            {PICKER_REQUIREMENTS[openItem.candidate_type].needUrlScope && (
                                <div className="space-y-1.5">
                                    <Label>{t("suggestions.dialog.urlScopeLabel")}</Label>
                                    <Select value={pickerUrlScope} onValueChange={(v) => setPickerUrlScope(v as UrlScope)}>
                                        <SelectTrigger>
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="exact">{t("suggestions.dialog.scopeExact")}</SelectItem>
                                            <SelectItem value="path-prefix">{t("suggestions.dialog.scopePathPrefix")}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}
                        </div>
                    )}

                    <DialogFooter>
                        <Button variant="outline" onClick={closeDialog} disabled={busyId !== null}>{t("suggestions.dialog.cancel")}</Button>
                        <Button onClick={() => void submitAccept()} disabled={busyId !== null}>
                            {busyId !== null ? (
                                <><Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> {t("suggestions.dialog.saving")}</>
                            ) : (
                                <>{t("suggestions.dialog.confirmAccept")}</>
                            )}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

export default SuggestionsPanel;
