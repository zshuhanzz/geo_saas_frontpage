/**
 * SettingsPage — v1.2 dual-mode tracking Settings.
 *
 * Spec §8.2 restructures Settings into three primary Tabs:
 *
 *   品牌 (Brands)
 *     ├── 我的品牌 (Own Brands — is_shadow=false)
 *     │    aliases + domains attached to this brand
 *     └── 经销渠道品牌 (Shadow Brands — is_shadow=true)
 *         aliases + domains + products with shadow_sub_role + peer banner
 *
 *   竞品 (Peers)
 *     ├── Peer aliases + domains
 *     └── Peer products (product_role='peer')
 *     Inline banner when Peer name also exists as a Shadow Brand.
 *
 *   追踪话题 (Topics)
 *     └── Each Topic → Own products (product_role='own')
 *         Per Own product: match_variants + Tracked URLs + Sales Channels
 *
 * Auto-Discovery modal moved into the 追踪话题 Tab (it's always been a
 * Topics/Products feature). Onboarding Wizard pops on first load when the
 * server flag says it hasn't been completed.
 *
 * Phase 5 scope: Own Brand domain editing inline is minimal (aliases + list
 * view) — a full domain-per-brand editor is V2. The existing standalone
 * Domains management lives under the 品牌 Tab as a per-brand subsection for
 * now; a global Domains tab could be added later if users ask.
 *
 * Phase 3B.2 (2026-04-25): the page body has been extracted into
 * co-located parts under `./SettingsPage.parts/*`. This file is the
 * orchestrator — it owns top-level data + state and wires callbacks
 * through to the parts. See parts/types.ts for shared types and
 * parts/utils.ts for pure helpers.
 */
import { useState, useEffect, useMemo, useRef } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { useSaaS } from "../contexts/SaaSContext";
import {
    // Topics
    getTopics, addTopic, removeTopic,
    // Domains
    getDomains, addDomain, removeDomain, updateDomain,
    // Peers
    getPeers, addPeer, removePeer, updatePeer,
    // Personas
    getPersonas, addPersona, removePersona,
    // v1.2 Brands + Products + URLs + channels
    getBrands, addBrand, removeBrand, updateBrand,
    listOwnProducts, addOwnProduct, updateOwnProduct, removeOwnProduct,
    listShadowBrandProducts, addShadowBrandProduct, updateShadowBrandProduct, removeShadowBrandProduct,
    listPeerProducts, addPeerProduct, updatePeerProduct, removePeerProduct,
    addSalesChannel, removeSalesChannel,
    // Onboarding + Auto-discovery
    getOnboardingStatus,
    autoDiscoverStream, bulkAddTopics,
} from "../lib/api";
import type {
    Brand,
    TopicProduct,
    AutoDiscoverResult,
    DiscoveredTopic,
    AutoDiscoverEvent,
    TopicType,
} from "../lib/api";
import {
    Card,
    CardContent,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tag, Users, UserSquare2, Loader2, Building2 } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import { useConfirm } from "@/components/ui/confirm-dialog";
import OnboardingWizard from "@/components/onboarding/OnboardingWizard";
// Phase 6 — Suggestions counts API is optional; fetched alongside the page
// data so the "AI 建议" chip can show totals per tab without round-tripping.
import { getCandidateCounts } from "@/lib/api";
import type { CandidateType } from "@/lib/api";

// Co-located parts (extracted in Phase 3B.2).
import {
    OTHER_BRAND_SENTINEL,
    OTHER_URL_SENTINEL,
    type ProgressEntry,
    type TabKey,
} from "./SettingsPage.parts/types";
import { domainToUrl } from "./SettingsPage.parts/utils";
import BrandsTab from "./SettingsPage.parts/BrandsTab";
import PeersTab from "./SettingsPage.parts/PeersTab";
import TopicsTab from "./SettingsPage.parts/TopicsTab";
import PersonasTab from "./SettingsPage.parts/PersonasTab";
import SuggestionsBanner from "./SettingsPage.parts/SuggestionsBanner";
import AutoDiscoveryDialog from "./SettingsPage.parts/AutoDiscoveryDialog";

export default function SettingsPage() {
    const { t } = useTranslation("settings");
    const confirmDialog = useConfirm();
    const { clientId, activeClientName, can } = useSaaS();
    const configurationReadOnly = !can("actions.configuration", "manage");
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const [loading, setLoading] = useState(false);

    // Top-level data
    const [brands, setBrands] = useState<Brand[]>([]);
    const [topics, setTopics] = useState<any[]>([]);
    const [domains, setDomains] = useState<any[]>([]);
    const [peers, setPeers] = useState<any[]>([]);
    const [personas, setPersonas] = useState<any[]>([]);

    // Products keyed by owner scope (brand/peer/topic) → product list
    const [ownProductsByTopic, setOwnProductsByTopic] = useState<Record<string, TopicProduct[]>>({});
    const [shadowProductsByBrand, setShadowProductsByBrand] = useState<Record<string, TopicProduct[]>>({});
    const [peerProductsByPeer, setPeerProductsByPeer] = useState<Record<string, TopicProduct[]>>({});

    const initialTab = (searchParams.get("tab") as TabKey) || "brands";
    const [activeTab, setActiveTab] = useState<TabKey>(initialTab);

    // Phase 6 — Suggestions panel state. `candidateCounts` is a small summary
    // used to render the tab-scoped banner pill. `suggestionsOpen` controls
    // the collapsible panel above the Tabs content area.
    const [candidateCounts, setCandidateCounts] = useState<Partial<Record<CandidateType, number>>>({});
    const [suggestionsOpen, setSuggestionsOpen] = useState(false);
    const [suggestionsScope, setSuggestionsScope] = useState<CandidateType | "all" | "tab">("all");

    async function reloadCandidateCounts() {
        if (!clientId) return;
        try {
            const c = await getCandidateCounts(clientId);
            setCandidateCounts(c as Partial<Record<CandidateType, number>>);
        } catch (err) {
            // Non-fatal — if the endpoint is unavailable the banner simply
            // stays collapsed / shows "0".
            console.warn("Candidate counts fetch failed", err);
        }
    }

    // Onboarding wizard
    const [wizardOpen, setWizardOpen] = useState(false);
    const [wizardClientName, setWizardClientName] = useState("");
    const wizardCheckedFor = useRef<string | null>(null);

    // Form inputs (brands tab)
    const [newOwnBrand, setNewOwnBrand] = useState("");
    const [newShadowBrand, setNewShadowBrand] = useState("");
    const [shadowBrandsCollapsed, setShadowBrandsCollapsed] = useState(true);
    const [expandedBrandId, setExpandedBrandId] = useState<string | null>(null);
    const [brandAliasInputs, setBrandAliasInputs] = useState<Record<string, string>>({});
    const [newBrandProductOpen, setNewBrandProductOpen] = useState<string | null>(null);
    const [newBrandProductTopic, setNewBrandProductTopic] = useState<Record<string, string>>({});

    // Form inputs (topics tab)
    const [newTopic, setNewTopic] = useState("");
    const [expandedTopicId, setExpandedTopicId] = useState<string | null>(null);
    const [newOwnProductOpen, setNewOwnProductOpen] = useState<string | null>(null);
    const [expandedOwnProductId, setExpandedOwnProductId] = useState<string | null>(null);

    // Form inputs (peers tab)
    const [newPeer, setNewPeer] = useState("");
    const [newAliases, setNewAliases] = useState<Record<string, string>>({});
    const [expandedPeerId, setExpandedPeerId] = useState<string | null>(null);
    const [newPeerProductOpen, setNewPeerProductOpen] = useState<string | null>(null);
    const [newPeerProductTopic, setNewPeerProductTopic] = useState<Record<string, string>>({});

    // Form inputs (personas tab)
    const [newPersonaName, setNewPersonaName] = useState("");
    const [newPersonaDesc, setNewPersonaDesc] = useState("");

    // Domains (separate per-brand management — lightweight for Phase 5)
    const [newDomainPerBrand, setNewDomainPerBrand] = useState<Record<string, string>>({});

    // Auto-discovery modal
    const [discoverOpen, setDiscoverOpen] = useState(false);
    const [discoverBrand, setDiscoverBrand] = useState("");
    const [discoverBrandChoice, setDiscoverBrandChoice] = useState<string>("");
    const [discoverUrlChoice, setDiscoverUrlChoice] = useState<string>("");
    const [discoverUrl, setDiscoverUrl] = useState("");
    const [discoverInstruction, setDiscoverInstruction] = useState("");
    // Optional listing / category URLs the user wants us to scrape directly.
    // Runtime-only (not persisted). Each URL gets Layer-0 anchor extraction,
    // then the real product URLs bypass the LLM in auto-discover's response
    // (→ AutoDiscoverResult.seed_products).
    const [discoverSeedUrls, setDiscoverSeedUrls] = useState<string[]>([""]);
    const [discoverLoading, setDiscoverLoading] = useState(false);
    const [discoverResult, setDiscoverResult] = useState<AutoDiscoverResult | null>(null);
    const [discoverSelection, setDiscoverSelection] = useState<Record<string, boolean>>({});
    const [discoverImporting, setDiscoverImporting] = useState(false);

    const [discoverProgress, setDiscoverProgress] = useState<ProgressEntry[]>([]);
    const [discoverDraft, setDiscoverDraft] = useState<DiscoveredTopic[]>([]);
    const [updatingProductId, setUpdatingProductId] = useState<string | null>(null);
    /**
     * Maps lowercased LLM product name → list of Layer-0 real URLs whose
     * anchor text contains that product name (case-insensitive substring).
     * Rebuilt whenever `discoverResult.seed_products` changes. Used both for
     * the per-chip URL-count badge and for enriching the import payload so
     * URLs land in `geo_product_tracked_urls` as exact-scope bindings.
     */
    const [seedUrlIndex, setSeedUrlIndex] = useState<Record<string, string[]>>({});

    // ── Lifecycle ────────────────────────────────────────────────────────
    useEffect(() => {
        if (clientId) {
            loadAllData();
            checkOnboardingStatus();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clientId]);

    // Keep the active tab in sync with the URL search param so deep-links
    // (e.g. ?tab=topics from the Onboarding wizard) land on the right tab.
    useEffect(() => {
        const t = (searchParams.get("tab") as TabKey) || "brands";
        if (t !== activeTab) setActiveTab(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchParams]);

    async function loadAllData() {
        if (!clientId) return;
        setLoading(true);
        try {
            const [b, t, d, p, pers] = await Promise.all([
                getBrands(clientId),
                getTopics(clientId),
                getDomains(clientId),
                getPeers(clientId),
                getPersonas(clientId),
            ]);
            setBrands(b);
            setTopics(t);
            setDomains(d);
            setPeers(p);
            setPersonas(pers);
            // Phase 6 — fire-and-forget: suggestions counts drive the banner.
            void reloadCandidateCounts();
        } catch (err: any) {
            console.error("Failed to load settings data", err);
            toast.error(`${t("toasts.loadFailed")}: ${err?.message || t("toasts.unknownError")}`);
        } finally {
            setLoading(false);
        }
    }

    async function checkOnboardingStatus() {
        if (!clientId) return;
        // Only pop once per clientId switch.
        if (wizardCheckedFor.current === clientId) return;
        wizardCheckedFor.current = clientId;
        try {
            const status = await getOnboardingStatus(clientId);
            if (!status.onboarding_wizard_completed) {
                setWizardClientName(status.client_name || activeClientName || "");
                setWizardOpen(true);
            }
        } catch (err) {
            // Non-fatal — don't interrupt the Settings UX over a status probe.
            console.warn("Onboarding status probe failed", err);
        }
    }

    function switchTab(tab: TabKey) {
        setActiveTab(tab);
        const next = new URLSearchParams(searchParams);
        next.set("tab", tab);
        setSearchParams(next, { replace: true });
    }

    // ── Brands (Own + Shadow) ────────────────────────────────────────────
    const ownBrands = useMemo(() => brands.filter((b) => !b.is_shadow), [brands]);
    const shadowBrands = useMemo(() => brands.filter((b) => b.is_shadow), [brands]);
    const activeOwnBrands = useMemo(
        () => brands.filter((b) => !b.is_shadow && b.is_active),
        [brands],
    );
    const activeShadowBrands = useMemo(
        () => brands.filter((b) => b.is_shadow && b.is_active),
        [brands],
    );
    // Fast lookup: does this peer-name collide with a shadow brand?
    const shadowBrandNames = useMemo(
        () => new Map(shadowBrands.map((b) => [b.brand_name.toLowerCase(), b])),
        [shadowBrands],
    );

    async function handleAddBrand(isShadow: boolean, name: string) {
        if (!name.trim() || !clientId) return;
        try {
            await addBrand(clientId, { brand_name: name.trim(), is_shadow: isShadow, aliases: [] });
            if (isShadow) setNewShadowBrand("");
            else setNewOwnBrand("");
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.brandAddFailed"));
        }
    }

    async function handleRemoveBrand(brandId: string) {
        if (!clientId) return;
        try {
            await removeBrand(clientId, brandId);
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.brandDeleteFailed"));
        }
    }

    async function handleAddBrandAlias(brand: Brand) {
        const alias = (brandAliasInputs[brand.id] || "").trim();
        if (!alias || !clientId) return;
        try {
            await updateBrand(clientId, brand.id, {
                aliases: [...(brand.aliases || []), alias],
            });
            setBrandAliasInputs((prev) => ({ ...prev, [brand.id]: "" }));
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.aliasAddFailed"));
        }
    }

    async function handleRemoveBrandAlias(brand: Brand, alias: string) {
        if (!clientId) return;
        try {
            await updateBrand(clientId, brand.id, {
                aliases: (brand.aliases || []).filter((a) => a !== alias),
            });
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.aliasDeleteFailed"));
        }
    }

    async function loadShadowBrandProducts(brandId: string) {
        if (!clientId) return;
        try {
            const products = await listShadowBrandProducts(clientId, brandId);
            setShadowProductsByBrand((prev) => ({ ...prev, [brandId]: products }));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.channelProductsLoadFailed"));
        }
    }

    // D2: per-(brand, topic) cache of own products available to link as a
    // sales channel. Keyed "brandId:topicId".
    const [ownProductsForLink, setOwnProductsForLink] = useState<
        Record<string, TopicProduct[]>
    >({});

    async function handleLoadOwnProductsForLink(brandId: string, topicId: string) {
        if (!clientId || !topicId) return;
        const key = `${brandId}:${topicId}`;
        if (ownProductsForLink[key]) return;  // cached
        try {
            const products = await listOwnProducts(clientId, topicId);
            setOwnProductsForLink((prev) => ({ ...prev, [key]: products }));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.topicProductsLoadFailed"));
        }
    }

    async function handleLinkExistingProductToBrand(brandId: string, productId: string) {
        if (!clientId) return;
        try {
            await addSalesChannel(clientId, productId, { brand_id: brandId });
            setNewBrandProductOpen(null);
            await loadShadowBrandProducts(brandId);
            toast.success(t("toasts.channelLinked"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.channelLinkFailed"));
        }
    }

    async function handleCreateShadowProduct(
        brandId: string,
        topicId: string,
        v: { product_name: string; match_variants: string[]; shadow_sub_role?: any; owner_peer_id?: string | null },
    ) {
        if (!clientId) return;
        try {
            await addShadowBrandProduct(clientId, brandId, {
                topic_id: topicId,
                product_name: v.product_name,
                match_variants: v.match_variants,
                shadow_sub_role: v.shadow_sub_role ?? null,
                owner_peer_id: v.owner_peer_id ?? null,
            });
            setNewBrandProductOpen(null);
            await loadShadowBrandProducts(brandId);
            toast.success(t("toasts.channelProductAdded"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productCreateFailed"));
        }
    }

    async function handleDeleteShadowProduct(brandId: string, product: TopicProduct) {
        if (!clientId) return;
        if (product.channel_source === "sales_channel") {
            try {
                await removeSalesChannel(clientId, product.id, brandId);
                await loadShadowBrandProducts(brandId);
                toast.success(t("toasts.channelUnlinked"));
            } catch (e: any) {
                toast.error(e?.message || t("toasts.channelUnlinkFailed"));
            }
            return;
        }
        const confirmed = await confirmDialog(
            t("products.deleteConfirmDescription"),
            t("products.deleteConfirmTitle"),
        );
        if (!confirmed) return;
        try {
            await removeShadowBrandProduct(clientId, brandId, product.id);
            await loadShadowBrandProducts(brandId);
            toast.success(t("toasts.productDeleted"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.deleteFailed"));
        }
    }

    async function handleSetShadowProductActive(
        brandId: string,
        product: TopicProduct,
        isActive: boolean,
    ) {
        if (!clientId) return;
        setUpdatingProductId(product.id);
        try {
            if (product.channel_source === "sales_channel") {
                await updateOwnProduct(clientId, product.topic_id, product.id, {
                    is_active: isActive,
                });
            } else {
                await updateShadowBrandProduct(clientId, brandId, product.id, {
                    is_active: isActive,
                });
            }
            await loadShadowBrandProducts(brandId);
            toast.success(t(isActive ? "toasts.productReactivated" : "toasts.productDeactivated"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productStatusUpdateFailed"));
        } finally {
            setUpdatingProductId(null);
        }
    }

    // Domain add (per-brand). Attaches to the brand_id directly — mirrors v1.2
    // `geo_client_domains.brand_id` FK. For Phase 5 we only wire the common
    // case (new domain inline), leaving scope editing to Settings V2.
    async function handleAddDomainToBrand(brandId: string) {
        const domain = (newDomainPerBrand[brandId] || "").trim();
        if (!domain || !clientId) return;
        try {
            await addDomain(clientId, { domain, is_primary: false } as any);
            // Attach brand_id in a follow-up PUT — addDomain() does not accept
            // it in the legacy signature. We update the domain we just created.
            const fresh = await getDomains(clientId);
            const just = fresh.find((d: any) => d.domain === domain && !d.brand_id && !d.peer_id);
            if (just) {
                await updateDomain(clientId, just.id, { brand_id: brandId } as any);
            }
            setNewDomainPerBrand((prev) => ({ ...prev, [brandId]: "" }));
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.domainAddFailed"));
        }
    }

    async function handleRemoveDomain(domainId: string) {
        if (!clientId) return;
        try {
            await removeDomain(clientId, domainId);
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.domainDeleteFailed"));
        }
    }

    // ── Topics + Own Products ────────────────────────────────────────────
    async function handleAddTopic() {
        if (!newTopic.trim() || !clientId) return;
        try {
            await addTopic(clientId, { topic_name: newTopic.trim(), products: [] });
            setNewTopic("");
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.topicAddFailed"));
        }
    }

    async function handleRemoveTopic(topicId: string) {
        if (!clientId) return;
        try {
            await removeTopic(clientId, topicId);
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.topicDeleteFailed"));
        }
    }

    async function loadOwnProducts(topicId: string) {
        if (!clientId) return;
        try {
            const products = await listOwnProducts(clientId, topicId);
            setOwnProductsByTopic((prev) => ({ ...prev, [topicId]: products }));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productLoadFailed"));
        }
    }

    async function handleCreateOwnProduct(
        topicId: string,
        v: { product_name: string; match_variants: string[]; owner_brand_id: string },
    ) {
        if (!clientId) return;
        try {
            await addOwnProduct(clientId, topicId, {
                product_name: v.product_name,
                match_variants: v.match_variants,
                owner_brand_id: v.owner_brand_id,
            });
            setNewOwnProductOpen(null);
            await loadOwnProducts(topicId);
            toast.success(t("toasts.productAdded"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productCreateFailed"));
        }
    }

    async function handleDeleteOwnProduct(topicId: string, productId: string) {
        if (!clientId) return;
        const confirmed = await confirmDialog(
            t("products.deleteConfirmDescription"),
            t("products.deleteConfirmTitle"),
        );
        if (!confirmed) return;
        try {
            await removeOwnProduct(clientId, topicId, productId);
            await loadOwnProducts(topicId);
            toast.success(t("toasts.productDeleted"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.deleteFailed"));
        }
    }

    async function handleSetOwnProductActive(
        topicId: string,
        productId: string,
        isActive: boolean,
    ) {
        if (!clientId) return;
        setUpdatingProductId(productId);
        try {
            await updateOwnProduct(clientId, topicId, productId, {
                is_active: isActive,
            });
            await loadOwnProducts(topicId);
            toast.success(t(isActive ? "toasts.productReactivated" : "toasts.productDeactivated"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productStatusUpdateFailed"));
        } finally {
            setUpdatingProductId(null);
        }
    }

    async function handleSetOwnProductOwner(
        topicId: string,
        productId: string,
        ownerBrandId: string | null,
    ) {
        if (!clientId) return;
        setUpdatingProductId(productId);
        try {
            await updateOwnProduct(clientId, topicId, productId, {
                owner_brand_id: ownerBrandId,
            });
            await loadOwnProducts(topicId);
            toast.success(t("toasts.productOwnerUpdated"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productOwnerUpdateFailed"));
        } finally {
            setUpdatingProductId(null);
        }
    }

    // ── Peers ─────────────────────────────────────────────────────────────
    async function handleAddPeer() {
        if (!newPeer.trim() || !clientId) return;
        try {
            await addPeer(clientId, { primary_name: newPeer.trim(), aliases: [] });
            setNewPeer("");
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.peerAddFailed"));
        }
    }

    async function handleRemovePeer(peerId: string) {
        if (!clientId) return;
        try {
            await removePeer(clientId, peerId);
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.peerDeleteFailed"));
        }
    }

    async function handleAddPeerAlias(peer: any) {
        const alias = (newAliases[peer.id] || "").trim();
        if (!alias || !clientId) return;
        try {
            await updatePeer(clientId, peer.id, {
                aliases: [...(peer.aliases || []), alias],
            });
            setNewAliases((prev) => ({ ...prev, [peer.id]: "" }));
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.aliasAddFailed"));
        }
    }

    async function handleRemovePeerAlias(peer: any, alias: string) {
        if (!clientId) return;
        try {
            await updatePeer(clientId, peer.id, {
                aliases: (peer.aliases || []).filter((a: string) => a !== alias),
            });
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.aliasDeleteFailed"));
        }
    }

    async function loadPeerProducts(peerId: string) {
        if (!clientId) return;
        try {
            const products = await listPeerProducts(clientId, peerId);
            setPeerProductsByPeer((prev) => ({ ...prev, [peerId]: products }));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.peerProductsLoadFailed"));
        }
    }

    async function handleCreatePeerProduct(
        peerId: string,
        topicId: string,
        v: { product_name: string; match_variants: string[] },
    ) {
        if (!clientId) return;
        try {
            await addPeerProduct(clientId, peerId, {
                topic_id: topicId,
                product_name: v.product_name,
                match_variants: v.match_variants,
            });
            setNewPeerProductOpen(null);
            await loadPeerProducts(peerId);
            toast.success(t("toasts.peerProductAdded"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productCreateFailed"));
        }
    }

    async function handleDeletePeerProduct(peerId: string, productId: string) {
        if (!clientId) return;
        const confirmed = await confirmDialog(
            t("products.deleteConfirmDescription"),
            t("products.deleteConfirmTitle"),
        );
        if (!confirmed) return;
        try {
            await removePeerProduct(clientId, peerId, productId);
            await loadPeerProducts(peerId);
            toast.success(t("toasts.productDeleted"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.deleteFailed"));
        }
    }

    async function handleSetPeerProductActive(
        peerId: string,
        productId: string,
        isActive: boolean,
    ) {
        if (!clientId) return;
        setUpdatingProductId(productId);
        try {
            await updatePeerProduct(clientId, peerId, productId, {
                is_active: isActive,
            });
            await loadPeerProducts(peerId);
            toast.success(t(isActive ? "toasts.productReactivated" : "toasts.productDeactivated"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.productStatusUpdateFailed"));
        } finally {
            setUpdatingProductId(null);
        }
    }

    // ── Personas ──────────────────────────────────────────────────────────
    async function handleAddPersona() {
        if (!newPersonaName.trim() || !clientId) return;
        try {
            await addPersona(clientId, {
                persona_name: newPersonaName.trim(),
                persona_description: newPersonaDesc.trim(),
            });
            setNewPersonaName("");
            setNewPersonaDesc("");
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.personaAddFailed"));
        }
    }

    async function handleRemovePersona(personaId: string) {
        if (!clientId) return;
        try {
            await removePersona(clientId, personaId);
            loadAllData();
        } catch (e: any) {
            toast.error(e?.message || t("toasts.personaDeleteFailed"));
        }
    }

    // ── Auto-Discovery ────────────────────────────────────────────────────
    function openAutoDiscover() {
        // 默认选第一个 Own Brand,没有就选第一个 Shadow Brand,否则 "其他品牌"
        const defaultBrand = activeOwnBrands[0] || activeShadowBrands[0];
        if (defaultBrand) {
            setDiscoverBrandChoice(defaultBrand.brand_name);
            setDiscoverBrand(defaultBrand.brand_name);
        } else {
            setDiscoverBrandChoice(OTHER_BRAND_SENTINEL);
            setDiscoverBrand(activeClientName || "");
        }

        // URL 默认:选中品牌下的第一个域名(优先 primary);否则 "其他 URL"
        const brandId = defaultBrand?.id;
        const brandDomains = brandId
            ? domains.filter((d: any) => d.brand_id === brandId)
            : domains.filter((d: any) => !d.peer_id); // 全部非 peer 域名(own + shadow)
        const primary = brandDomains.find((d: any) => d.is_primary) || brandDomains[0];
        if (primary?.domain) {
            setDiscoverUrlChoice(primary.domain);
            setDiscoverUrl(domainToUrl(primary.domain));
        } else {
            setDiscoverUrlChoice(OTHER_URL_SENTINEL);
            setDiscoverUrl("");
        }
        setDiscoverResult(null);
        setDiscoverSelection({});
        setDiscoverProgress([]);
        setDiscoverDraft([]);
        setSeedUrlIndex({});
        setDiscoverInstruction("");
        setDiscoverOpen(true);
    }

    function handleDiscoverBrandChoiceChange(value: string) {
        setDiscoverBrandChoice(value);
        if (value === OTHER_BRAND_SENTINEL) {
            setDiscoverBrand("");
            // 品牌切到"其他"时,URL 保持用户已选;如果 URL 还没选/是空,提示用户填
        } else {
            // Find brand by name and auto-select its first domain
            const selectedBrand = [...activeOwnBrands, ...activeShadowBrands].find(
                (b) => b.brand_name === value,
            );
            setDiscoverBrand(value);
            if (selectedBrand) {
                const brandDomains = domains.filter(
                    (d: any) => d.brand_id === selectedBrand.id,
                );
                const primary =
                    brandDomains.find((d: any) => d.is_primary) || brandDomains[0];
                if (primary?.domain) {
                    setDiscoverUrlChoice(primary.domain);
                    setDiscoverUrl(domainToUrl(primary.domain));
                } else {
                    // 该品牌还没有域名 → 切到 其他 URL
                    setDiscoverUrlChoice(OTHER_URL_SENTINEL);
                    setDiscoverUrl("");
                }
            }
        }
    }

    function handleDomainChoiceChange(value: string) {
        setDiscoverUrlChoice(value);
        if (value === OTHER_URL_SENTINEL) setDiscoverUrl("");
        else setDiscoverUrl(domainToUrl(value));
    }

    // 过滤出"我的品牌 + 经销渠道品牌"关联的域名(排除 peer 域名)
    const brandOwnedDomains = useMemo(
        () => domains.filter((d: any) => d.brand_id && !d.peer_id),
        [domains],
    );

    function appendProgress(entry: Omit<ProgressEntry, "ts">) {
        setDiscoverProgress((prev) => [...prev, { ...entry, ts: Date.now() }]);
    }

    async function handleRunAutoDiscover() {
        if (!discoverBrand.trim() || !discoverUrl.trim()) {
            toast.error(t("toasts.brandNameAndUrlRequired"));
            return;
        }
        setDiscoverLoading(true);
        setDiscoverResult(null);
        setDiscoverProgress([]);
        setDiscoverDraft([]);
        setDiscoverSelection({});
        setSeedUrlIndex({});

        try {
            const cleanedSeedUrls = discoverSeedUrls
                .map((u) => u.trim())
                .filter((u) => u.length > 0);
            for await (const event of autoDiscoverStream(
                discoverBrand.trim(),
                discoverUrl.trim(),
                discoverInstruction.trim() || undefined,
                cleanedSeedUrls.length > 0 ? cleanedSeedUrls : undefined,
            ) as AsyncGenerator<AutoDiscoverEvent>) {
                if (event.type === "stage") {
                    appendProgress({ kind: "stage", stage: event.stage, message: event.message });
                } else if (event.type === "progress") {
                    appendProgress({
                        kind: "progress", stage: event.stage, message: event.message, count: event.count,
                    });
                } else if (event.type === "warn") {
                    appendProgress({ kind: "warn", stage: event.stage, message: event.message });
                } else if (event.type === "error") {
                    appendProgress({ kind: "error", stage: "error", message: event.message });
                    toast.error(t("toasts.autoDiscoveryError", { message: event.message }));
                } else if (event.type === "final") {
                    const result = event.result;
                    setDiscoverResult(result);

                    const seedList = result.seed_products || [];
                    // Option A — when the user supplied seed URLs, trust the
                    // Layer-0 anchor text as product names (preserves SKU
                    // granularity like "Rough Country 4-Inch Drop Steps for
                    // Ford F-150 Crew Cab" instead of the LLM's abstracted
                    // "Drop Steps") and keep the 1:1 anchor↔URL mapping
                    // intact. LLM's per-topic product list is used only as
                    // routing keywords to decide which topic each anchor
                    // belongs under.
                    if (seedList.length > 0) {
                        const dedupSeed = new Map<string, string>();
                        for (const sp of seedList) {
                            const nm = (sp.name || "").trim();
                            const url = (sp.url || "").trim();
                            if (!nm || !url) continue;
                            if (!dedupSeed.has(nm)) dedupSeed.set(nm, url);
                        }
                        const draft: DiscoveredTopic[] = result.topics.map((t) => ({
                            topic_name: t.topic_name,
                            products: [] as string[],
                        }));
                        const seedUrls: Record<string, string[]> = {};
                        const unmatched: Array<{ name: string; url: string }> = [];
                        for (const [anchorName, anchorUrl] of dedupSeed) {
                            const anchorLower = anchorName.toLowerCase();
                            let matchedTopicIdx = -1;
                            for (let i = 0; i < result.topics.length; i++) {
                                const cats = result.topics[i].products || [];
                                if (
                                    cats.some((cat) => {
                                        const c = (cat || "").trim().toLowerCase();
                                        return c.length >= 3 && anchorLower.includes(c);
                                    })
                                ) {
                                    matchedTopicIdx = i;
                                    break;
                                }
                            }
                            if (matchedTopicIdx >= 0) {
                                draft[matchedTopicIdx].products.push(anchorName);
                                seedUrls[anchorName.toLowerCase()] = [anchorUrl];
                            } else {
                                unmatched.push({ name: anchorName, url: anchorUrl });
                            }
                        }
                        if (unmatched.length > 0) {
                            draft.push({
                                topic_name: t("autoDiscover.unclassifiedBucket"),
                                products: unmatched.map((u) => u.name),
                            });
                            unmatched.forEach((u) => {
                                seedUrls[u.name.toLowerCase()] = [u.url];
                            });
                        }
                        setDiscoverDraft(draft);
                        setSeedUrlIndex(seedUrls);
                        const initial: Record<string, boolean> = {};
                        draft.forEach((_d, i) => (initial[String(i)] = true));
                        setDiscoverSelection(initial);
                    } else {
                        // Legacy flow — no seed URLs: keep LLM products as-is,
                        // no URL attachments.
                        setDiscoverDraft(
                            result.topics.map((t) => ({
                                topic_name: t.topic_name,
                                products: [...(t.products || [])],
                            })),
                        );
                        setSeedUrlIndex({});
                        const initial: Record<string, boolean> = {};
                        result.topics.forEach((_t, idx) => (initial[String(idx)] = true));
                        setDiscoverSelection(initial);
                    }
                    if (result.source_layer === "failed" || result.topics.length === 0) {
                        toast.warning(t("toasts.autoDiscoveryTopicsMissing"));
                    } else {
                        toast.success(t("toasts.autoDiscoveryTopicsFound", { count: result.topics.length, layer: result.source_layer }));
                    }
                }
            }
        } catch (e: any) {
            appendProgress({ kind: "error", stage: "error", message: e?.message || t("toasts.unknownError") });
            toast.error(t("toasts.autoDiscoveryFailed", { message: e?.message || t("toasts.unknownError") }));
        } finally {
            setDiscoverLoading(false);
        }
    }

    async function handleImportDiscovered() {
        if (!clientId || discoverDraft.length === 0) return;
        const selected = discoverDraft
            .map((t, idx) => ({ t, idx }))
            .filter(({ idx }) => discoverSelection[String(idx)])
            .map(({ t }) => ({
                topic_name: t.topic_name.trim(),
                // Send products as {name, urls} objects so the backend can
                // auto-attach Layer-0 URLs as exact-scope tracked URLs.
                // Cap raised to 200 because Option A routes individual SKU
                // anchors (one topic can easily have 30-50 products).
                products: (t.products || [])
                    .map((p) => p.trim())
                    .filter((p) => p.length > 0)
                    .slice(0, 200)
                    .map((name) => ({
                        name,
                        urls: seedUrlIndex[name.toLowerCase()] || [],
                    })),
                topic_type: "semantic_topic" as TopicType,
            }))
            .filter((t) => t.topic_name.length > 0);

        if (selected.length === 0) {
            toast.error(t("toasts.importTopicsRequired"));
            return;
        }

        // Precompute plan counts so the toast + button can reflect scope.
        const planProductCount = selected.reduce((acc, t) => acc + t.products.length, 0);
        const planUrlCount = selected.reduce(
            (acc, t) => acc + t.products.reduce((a, p) => a + (p.urls?.length || 0), 0),
            0,
        );

        setDiscoverImporting(true);
        const pendingToastId = toast.loading(
            t("toasts.importInProgress", {
                topics: selected.length,
                products: planProductCount,
                urls: planUrlCount,
            }),
        );
        try {
            const resp = await bulkAddTopics(clientId, selected);
            toast.dismiss(pendingToastId);
            const urlsCreated = (resp as { tracked_urls_created?: number }).tracked_urls_created ?? planUrlCount;
            if (resp.created > 0) {
                toast.success(
                    resp.skipped > 0
                        ? t("toasts.importSuccessSkipped", {
                              created: resp.created,
                              products: planProductCount,
                              urls: urlsCreated,
                              skipped: resp.skipped,
                          })
                        : t("toasts.importSuccess", {
                              created: resp.created,
                              products: planProductCount,
                              urls: urlsCreated,
                          }),
                );
                setDiscoverOpen(false);
                loadAllData();
            } else if (resp.skipped > 0) {
                toast.warning(t("toasts.importAllSkipped", { skipped: resp.skipped }));
            } else {
                toast.warning(t("toasts.importNothing"));
            }
        } catch (e: any) {
            toast.dismiss(pendingToastId);
            toast.error(t("toasts.importFailed", { message: e?.message || t("toasts.unknownError") }));
        } finally {
            setDiscoverImporting(false);
        }
    }

    function toggleDiscoverTopic(key: string) {
        setDiscoverSelection((prev) => ({ ...prev, [key]: !prev[key] }));
    }
    function updateDraftTopicName(idx: number, newName: string) {
        setDiscoverDraft((prev) => {
            const next = [...prev];
            next[idx] = { ...next[idx], topic_name: newName };
            return next;
        });
    }
    function removeDraftProduct(topicIdx: number, prodIdx: number) {
        setDiscoverDraft((prev) => {
            const next = [...prev];
            const products = [...(next[topicIdx].products || [])];
            products.splice(prodIdx, 1);
            next[topicIdx] = { ...next[topicIdx], products };
            return next;
        });
    }
    function addDraftProduct(topicIdx: number, value: string) {
        const trimmed = value.trim();
        if (!trimmed) return;
        setDiscoverDraft((prev) => {
            const next = [...prev];
            const products = [...(next[topicIdx].products || []), trimmed];
            next[topicIdx] = { ...next[topicIdx], products };
            return next;
        });
    }
    function removeDraftTopic(topicIdx: number) {
        setDiscoverDraft((prev) => prev.filter((_, i) => i !== topicIdx));
        setDiscoverSelection((prev) => {
            const next: Record<string, boolean> = {};
            Object.entries(prev).forEach(([k, v]) => {
                const idx = Number(k);
                if (Number.isNaN(idx)) return;
                if (idx < topicIdx) next[String(idx)] = v;
                else if (idx > topicIdx) next[String(idx - 1)] = v;
            });
            return next;
        });
    }

    // ── Render ───────────────────────────────────────────────────────────
    if (!clientId) {
        return (
            <div className="h-full flex flex-col items-center justify-center space-y-2">
                <h2 className="text-xl font-medium text-foreground">Settings & Configuration</h2>
                <p className="text-sm text-muted-foreground">
                    {t("page.noClient")}
                </p>
            </div>
        );
    }

    // Filter domains for display under a specific brand/peer
    const domainsForBrand = (brandId: string) =>
        domains.filter((d: any) => d.brand_id === brandId);
    const domainsForPeer = (peerId: string) =>
        domains.filter((d: any) => d.peer_id === peerId);

    return (
        <div className="max-w-6xl mx-auto space-y-6">
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col gap-2">
                    <h1 className="text-3xl font-bold tracking-tight">{t("page.title")}</h1>
                    <p className="text-muted-foreground">
                        <Trans
                            i18nKey="page.description"
                            ns="settings"
                            values={{ clientName: activeClientName }}
                            components={{ 1: <span className="font-semibold text-foreground" /> }}
                        />
                    </p>
                </div>
            </div>

            <Card className="shadow-sm border-muted/50">
                <CardContent className="p-6">
                    {loading ? (
                        <div className="flex py-12 items-center justify-center text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin mr-2" /> {t("suggestions.panelLoading")}
                        </div>
                    ) : (
                        <Tabs value={activeTab} onValueChange={(v) => switchTab(v as TabKey)} className="w-full">
                            <SuggestionsBanner
                                clientId={clientId}
                                activeTab={activeTab}
                                readOnly={configurationReadOnly}
                                candidateCounts={candidateCounts}
                                suggestionsOpen={suggestionsOpen}
                                setSuggestionsOpen={setSuggestionsOpen}
                                suggestionsScope={suggestionsScope}
                                setSuggestionsScope={setSuggestionsScope}
                                reloadCandidateCounts={reloadCandidateCounts}
                            />

                            <TabsList className="grid w-full grid-cols-4 mb-8">
                                <TabsTrigger value="brands" className="flex items-center gap-2">
                                    <Building2 className="h-4 w-4" /> {t("tabs.brands")}
                                </TabsTrigger>
                                <TabsTrigger value="peers" className="flex items-center gap-2">
                                    <Users className="h-4 w-4" /> {t("tabs.peers")}
                                </TabsTrigger>
                                <TabsTrigger value="topics" className="flex items-center gap-2">
                                    <Tag className="h-4 w-4" /> {t("tabs.topics")}
                                </TabsTrigger>
                                <TabsTrigger value="personas" className="flex items-center gap-2">
                                    <UserSquare2 className="h-4 w-4" /> {t("tabs.personas")}
                                </TabsTrigger>
                            </TabsList>

                            <fieldset
                                disabled={configurationReadOnly}
                                className="min-w-0 border-0 p-0"
                            >
                            {/* ============================================== */}
                            {/* Tab: 品牌 (Brands) */}
                            {/* ============================================== */}
                            <BrandsTab
                                ownBrands={ownBrands}
                                shadowBrands={shadowBrands}
                                topics={topics}
                                peers={peers}
                                domainsForBrand={domainsForBrand}
                                shadowProductsByBrand={shadowProductsByBrand}
                                ownProductsForLink={ownProductsForLink}
                                expandedBrandId={expandedBrandId}
                                setExpandedBrandId={setExpandedBrandId}
                                brandAliasInputs={brandAliasInputs}
                                setBrandAliasInputs={setBrandAliasInputs}
                                newDomainPerBrand={newDomainPerBrand}
                                setNewDomainPerBrand={setNewDomainPerBrand}
                                newBrandProductOpen={newBrandProductOpen}
                                setNewBrandProductOpen={setNewBrandProductOpen}
                                newBrandProductTopic={newBrandProductTopic}
                                setNewBrandProductTopic={setNewBrandProductTopic}
                                newOwnBrand={newOwnBrand}
                                setNewOwnBrand={setNewOwnBrand}
                                newShadowBrand={newShadowBrand}
                                setNewShadowBrand={setNewShadowBrand}
                                shadowBrandsCollapsed={shadowBrandsCollapsed}
                                setShadowBrandsCollapsed={setShadowBrandsCollapsed}
                                handleAddBrand={handleAddBrand}
                                handleRemoveBrand={handleRemoveBrand}
                                handleAddBrandAlias={handleAddBrandAlias}
                                handleRemoveBrandAlias={handleRemoveBrandAlias}
                                handleAddDomainToBrand={handleAddDomainToBrand}
                                handleRemoveDomain={handleRemoveDomain}
                                loadShadowBrandProducts={loadShadowBrandProducts}
                                handleLoadOwnProductsForLink={handleLoadOwnProductsForLink}
                                handleLinkExistingProductToBrand={handleLinkExistingProductToBrand}
                                handleCreateShadowProduct={handleCreateShadowProduct}
                                handleDeleteShadowProduct={handleDeleteShadowProduct}
                                handleSetShadowProductActive={handleSetShadowProductActive}
                                updatingProductId={updatingProductId}
                            />

                            {/* ============================================== */}
                            {/* Tab: 竞品 (Peers) */}
                            {/* ============================================== */}
                            <PeersTab
                                peers={peers}
                                topics={topics}
                                peerProductsByPeer={peerProductsByPeer}
                                shadowBrandNames={shadowBrandNames}
                                domainsForPeer={domainsForPeer}
                                expandedPeerId={expandedPeerId}
                                setExpandedPeerId={setExpandedPeerId}
                                newAliases={newAliases}
                                setNewAliases={setNewAliases}
                                newPeer={newPeer}
                                setNewPeer={setNewPeer}
                                newPeerProductOpen={newPeerProductOpen}
                                setNewPeerProductOpen={setNewPeerProductOpen}
                                newPeerProductTopic={newPeerProductTopic}
                                setNewPeerProductTopic={setNewPeerProductTopic}
                                handleAddPeer={handleAddPeer}
                                handleRemovePeer={handleRemovePeer}
                                handleAddPeerAlias={handleAddPeerAlias}
                                handleRemovePeerAlias={handleRemovePeerAlias}
                                handleRemoveDomain={handleRemoveDomain}
                                loadPeerProducts={loadPeerProducts}
                                handleCreatePeerProduct={handleCreatePeerProduct}
                                handleDeletePeerProduct={handleDeletePeerProduct}
                                handleSetPeerProductActive={handleSetPeerProductActive}
                                updatingProductId={updatingProductId}
                                switchTab={switchTab}
                                setExpandedBrandId={setExpandedBrandId}
                            />

                            {/* ============================================== */}
                            {/* Tab: 追踪话题 (Topics + Own Products) */}
                            {/* ============================================== */}
                            <TopicsTab
                                clientId={clientId}
                                topics={topics}
                                domains={domains}
                                shadowBrands={activeShadowBrands}
                                ownBrands={activeOwnBrands}
                                ownProductsByTopic={ownProductsByTopic}
                                expandedTopicId={expandedTopicId}
                                setExpandedTopicId={setExpandedTopicId}
                                expandedOwnProductId={expandedOwnProductId}
                                setExpandedOwnProductId={setExpandedOwnProductId}
                                newTopic={newTopic}
                                setNewTopic={setNewTopic}
                                newOwnProductOpen={newOwnProductOpen}
                                setNewOwnProductOpen={setNewOwnProductOpen}
                                handleAddTopic={handleAddTopic}
                                handleRemoveTopic={handleRemoveTopic}
                                loadOwnProducts={loadOwnProducts}
                                handleCreateOwnProduct={handleCreateOwnProduct}
                                handleDeleteOwnProduct={handleDeleteOwnProduct}
                                handleSetOwnProductActive={handleSetOwnProductActive}
                                handleSetOwnProductOwner={handleSetOwnProductOwner}
                                updatingProductId={updatingProductId}
                                openAutoDiscover={openAutoDiscover}
                            />

                            {/* ============================================== */}
                            {/* Tab: Personas */}
                            {/* ============================================== */}
                            <PersonasTab
                                personas={personas}
                                newPersonaName={newPersonaName}
                                setNewPersonaName={setNewPersonaName}
                                newPersonaDesc={newPersonaDesc}
                                setNewPersonaDesc={setNewPersonaDesc}
                                handleAddPersona={handleAddPersona}
                                handleRemovePersona={handleRemovePersona}
                            />
                            </fieldset>
                        </Tabs>
                    )}
                </CardContent>
            </Card>

            {/* Onboarding Wizard */}
            <OnboardingWizard
                open={wizardOpen}
                clientId={clientId}
                clientName={wizardClientName || activeClientName}
                onClose={(opts) => {
                    setWizardOpen(false);
                    if (opts?.tab) {
                        switchTab(opts.tab);
                    }
                    // Reload data so any seeded brand shows up immediately.
                    loadAllData();
                    if (opts?.navigateTo && location.pathname !== opts.navigateTo) {
                        navigate(opts.navigateTo);
                    }
                }}
            />

            {/* Auto-Discovery Dialog */}
            <AutoDiscoveryDialog
                open={discoverOpen}
                onOpenChange={setDiscoverOpen}
                ownBrands={activeOwnBrands}
                shadowBrands={activeShadowBrands}
                brandOwnedDomains={brandOwnedDomains}
                discoverBrandChoice={discoverBrandChoice}
                discoverBrand={discoverBrand}
                setDiscoverBrand={setDiscoverBrand}
                handleDiscoverBrandChoiceChange={handleDiscoverBrandChoiceChange}
                discoverUrlChoice={discoverUrlChoice}
                discoverUrl={discoverUrl}
                setDiscoverUrl={setDiscoverUrl}
                handleDomainChoiceChange={handleDomainChoiceChange}
                discoverSeedUrls={discoverSeedUrls}
                setDiscoverSeedUrls={setDiscoverSeedUrls}
                discoverInstruction={discoverInstruction}
                setDiscoverInstruction={setDiscoverInstruction}
                discoverLoading={discoverLoading}
                discoverImporting={discoverImporting}
                discoverProgress={discoverProgress}
                discoverResult={discoverResult}
                discoverDraft={discoverDraft}
                discoverSelection={discoverSelection}
                seedUrlIndex={seedUrlIndex}
                handleRunAutoDiscover={handleRunAutoDiscover}
                handleImportDiscovered={handleImportDiscovered}
                toggleDiscoverTopic={toggleDiscoverTopic}
                updateDraftTopicName={updateDraftTopicName}
                removeDraftProduct={removeDraftProduct}
                addDraftProduct={addDraftProduct}
                removeDraftTopic={removeDraftTopic}
            />
        </div>
    );
}
