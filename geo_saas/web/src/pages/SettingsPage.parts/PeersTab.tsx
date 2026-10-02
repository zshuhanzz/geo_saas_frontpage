import {
    ChevronDown, ChevronRight, Globe, Info, Package, Plus, Trash2, Users, X,
} from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { TabsContent } from "@/components/ui/tabs";
import HelpTooltip from "@/components/ui/HelpTooltip";
import ProductEditor from "@/components/settings/ProductEditor";
import type { Brand, TopicProduct } from "@/lib/api";
import ProductRow from "./ProductRow";
import type { TabKey } from "./types";

interface PeersTabProps {
    peers: any[];
    topics: any[];
    peerProductsByPeer: Record<string, TopicProduct[]>;
    shadowBrandNames: Map<string, Brand>;
    domainsForPeer: (peerId: string) => any[];
    expandedPeerId: string | null;
    setExpandedPeerId: (id: string | null) => void;
    newAliases: Record<string, string>;
    setNewAliases: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    newPeer: string;
    setNewPeer: (v: string) => void;
    newPeerProductOpen: string | null;
    setNewPeerProductOpen: (id: string | null) => void;
    newPeerProductTopic: Record<string, string>;
    setNewPeerProductTopic: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    handleAddPeer: () => void;
    handleRemovePeer: (peerId: string) => void;
    handleAddPeerAlias: (peer: any) => void;
    handleRemovePeerAlias: (peer: any, alias: string) => void;
    handleRemoveDomain: (domainId: string) => void;
    loadPeerProducts: (peerId: string) => void;
    handleCreatePeerProduct: (
        peerId: string,
        topicId: string,
        v: { product_name: string; match_variants: string[] },
    ) => Promise<void>;
    handleDeletePeerProduct: (peerId: string, productId: string) => void;
    handleSetPeerProductActive: (peerId: string, productId: string, isActive: boolean) => void;
    updatingProductId: string | null;
    switchTab: (tab: TabKey) => void;
    setExpandedBrandId: (id: string | null) => void;
}

export default function PeersTab(props: PeersTabProps) {
    const { t } = useTranslation("settings");
    const {
        peers, topics, peerProductsByPeer, shadowBrandNames, domainsForPeer,
        expandedPeerId, setExpandedPeerId,
        newAliases, setNewAliases,
        newPeer, setNewPeer,
        newPeerProductOpen, setNewPeerProductOpen,
        newPeerProductTopic, setNewPeerProductTopic,
        handleAddPeer, handleRemovePeer,
        handleAddPeerAlias, handleRemovePeerAlias,
        handleRemoveDomain,
        loadPeerProducts,
        handleCreatePeerProduct,
        handleDeletePeerProduct,
        handleSetPeerProductActive,
        updatingProductId,
        switchTab, setExpandedBrandId,
    } = props;

    return (
        <TabsContent value="peers" className="space-y-6 mt-0 animate-in fade-in-50 duration-500">
            <div className="flex items-center gap-2 border-b pb-2">
                <Users className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    <HelpTooltip content={t("tooltips.peersSection")}>
                        {t("peers.title")}
                    </HelpTooltip>
                </h3>
            </div>
            <p className="text-sm text-muted-foreground max-w-2xl">
                {t("peers.description")}
            </p>

            <div className="flex gap-2 max-w-md">
                <Input
                    placeholder={t("peers.addPlaceholder")}
                    value={newPeer}
                    onChange={(e) => setNewPeer(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAddPeer()}
                />
                <Button onClick={handleAddPeer}>
                    <Plus className="h-3.5 w-3.5 mr-1" /> {t("peers.addButton")}
                </Button>
            </div>

            <div className="grid grid-cols-1 gap-3">
                {peers.map((peer) => {
                    const isExpanded = expandedPeerId === peer.id;
                    const collision = shadowBrandNames.get(
                        (peer.primary_name || "").toLowerCase(),
                    );
                    const products = peerProductsByPeer[peer.id] || [];
                    return (
                        <Card
                            key={peer.id}
                            className="overflow-hidden shadow-none border bg-card/50"
                        >
                            <div
                                className="border-b bg-muted/20 px-4 py-3 flex items-center justify-between cursor-pointer"
                                onClick={() => {
                                    const next = isExpanded ? null : peer.id;
                                    setExpandedPeerId(next);
                                    if (next === peer.id && !peerProductsByPeer[peer.id]) {
                                        loadPeerProducts(peer.id);
                                    }
                                }}
                            >
                                <div className="flex items-center gap-2">
                                    {isExpanded ? (
                                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                                    ) : (
                                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                    )}
                                    <span className="font-semibold text-foreground">
                                        {peer.primary_name}
                                    </span>
                                    {peer.aliases && peer.aliases.length > 0 && (
                                        <span className="text-xs text-muted-foreground">
                                            ({t("brands.aliasCount", { count: peer.aliases.length })})
                                        </span>
                                    )}
                                </div>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleRemovePeer(peer.id);
                                    }}
                                    className="h-8 text-muted-foreground hover:text-destructive"
                                >
                                    <Trash2 className="h-4 w-4" />
                                </Button>
                            </div>
                            {isExpanded && (
                                <div className="p-4 space-y-4">
                                    {/* Banner: Peer also exists as Shadow Brand */}
                                    {collision && (
                                        <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 flex items-start gap-2 text-xs">
                                            <Info className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                                            <div className="flex-1 leading-relaxed">
                                                <div className="font-medium text-amber-700 dark:text-amber-300 mb-0.5">
                                                    <HelpTooltip content={t("tooltips.peerIsAlsoShadow")}>
                                                        <span>{t("peers.alsoShadow")}</span>
                                                    </HelpTooltip>
                                                </div>
                                                <div className="text-muted-foreground">
                                                    <strong>{peer.primary_name}</strong>{" "}
                                                    {t("peers.collisionIntro")}{" "}
                                                    <button
                                                        type="button"
                                                        className="underline text-primary hover:text-primary/80"
                                                        onClick={() => {
                                                            switchTab("brands");
                                                            setExpandedBrandId(collision.id);
                                                        }}
                                                    >
                                                        {t("peers.collisionLinkPrefix")}{collision.brand_name}
                                                    </button>
                                                    {t("peers.collisionOutro")}
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {/* Aliases */}
                                    <div className="flex flex-wrap gap-2 items-center">
                                        <span className="text-xs font-medium text-muted-foreground mr-1">
                                            {t("brands.aliasesSection")}
                                        </span>
                                        {(peer.aliases || []).map(
                                            (alias: string, idx: number) => (
                                                <Badge
                                                    key={idx}
                                                    variant="outline"
                                                    className="text-xs py-0.5 pl-2 pr-1"
                                                >
                                                    {alias}
                                                    <button
                                                        onClick={() =>
                                                            handleRemovePeerAlias(peer, alias)
                                                        }
                                                        className="ml-1.5 rounded-full p-0.5 hover:bg-muted hover:text-destructive transition-colors"
                                                    >
                                                        <X className="h-3 w-3" />
                                                    </button>
                                                </Badge>
                                            ),
                                        )}
                                        {(!peer.aliases || peer.aliases.length === 0) && (
                                            <span className="text-xs text-muted-foreground/70 italic">
                                                {t("brands.aliasesEmpty")}
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex gap-2 max-w-sm">
                                        <Input
                                            placeholder={t("brands.aliasAddPlaceholder")}
                                            value={newAliases[peer.id] || ""}
                                            onChange={(e) =>
                                                setNewAliases({
                                                    ...newAliases,
                                                    [peer.id]: e.target.value,
                                                })
                                            }
                                            onKeyDown={(e) =>
                                                e.key === "Enter" && handleAddPeerAlias(peer)
                                            }
                                            className="h-8 text-sm"
                                        />
                                        <Button
                                            size="sm"
                                            variant="secondary"
                                            onClick={() => handleAddPeerAlias(peer)}
                                            className="h-8"
                                        >
                                            <Plus className="h-3 w-3 mr-1" /> {t("brands.aliasAddButton")}
                                        </Button>
                                    </div>

                                    {/* Domains for peer */}
                                    <div className="space-y-2 pt-3 border-t">
                                        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                            <Globe className="h-3.5 w-3.5" /> {t("brands.domainsSection")}
                                        </div>
                                        <div className="flex flex-wrap gap-1.5">
                                            {domainsForPeer(peer.id).map((d: any) => (
                                                <Badge
                                                    key={d.id}
                                                    variant="outline"
                                                    className="text-xs pl-2 pr-1 py-0.5 font-mono"
                                                >
                                                    {d.domain}
                                                    <button
                                                        onClick={() =>
                                                            handleRemoveDomain(d.id)
                                                        }
                                                        className="ml-1.5 rounded-full p-0.5 hover:bg-destructive/10 hover:text-destructive transition-colors"
                                                    >
                                                        <X className="h-3 w-3" />
                                                    </button>
                                                </Badge>
                                            ))}
                                            {domainsForPeer(peer.id).length === 0 && (
                                                <span className="text-xs text-muted-foreground/70 italic">
                                                    {t("brands.domainsEmpty")}
                                                </span>
                                            )}
                                        </div>
                                    </div>

                                    {/* Peer products */}
                                    <div className="space-y-2 pt-3 border-t">
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                                <Package className="h-3.5 w-3.5" />
                                                <HelpTooltip content={t("tooltips.peerProductsSection")}>
                                                    {t("peers.peerProductsTitle")}
                                                </HelpTooltip>
                                            </div>
                                            {newPeerProductOpen !== peer.id && (
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    className="h-7 text-xs"
                                                    onClick={() =>
                                                        setNewPeerProductOpen(peer.id)
                                                    }
                                                    disabled={topics.length === 0}
                                                >
                                                    <Plus className="h-3 w-3 mr-1" /> {t("peers.peerProductsAdd")}
                                                </Button>
                                            )}
                                        </div>

                                        {topics.length === 0 && (
                                            <div className="text-xs text-muted-foreground/80 italic">
                                                {t("peers.peerProductsNoTopics")}
                                            </div>
                                        )}

                                        {products.length === 0 && newPeerProductOpen !== peer.id && (
                                            <div className="text-xs text-muted-foreground/80 italic">
                                                {t("peers.peerProductsEmpty")}
                                            </div>
                                        )}

                                        <div className="space-y-2">
                                            {products.map((prod) => (
                                                <ProductRow
                                                    key={prod.id}
                                                    product={prod}
                                                    topicName={
                                                        topics.find((t: any) => t.id === prod.topic_id)
                                                            ?.topic_name
                                                    }
                                                    onDelete={() =>
                                                        handleDeletePeerProduct(peer.id, prod.id)
                                                    }
                                                    onSetActive={(isActive) =>
                                                        handleSetPeerProductActive(peer.id, prod.id, isActive)
                                                    }
                                                    statusUpdating={updatingProductId === prod.id}
                                                />
                                            ))}
                                        </div>

                                        {newPeerProductOpen === peer.id && (
                                            <div className="space-y-3 rounded-md border border-dashed p-3 bg-muted/10">
                                                <div className="space-y-1.5">
                                                    <Label className="text-xs">
                                                        {t("peers.topicBelongs")}
                                                    </Label>
                                                    <Select
                                                        value={newPeerProductTopic[peer.id] || ""}
                                                        onValueChange={(v) =>
                                                            setNewPeerProductTopic((p) => ({
                                                                ...p,
                                                                [peer.id]: v,
                                                            }))
                                                        }
                                                    >
                                                        <SelectTrigger>
                                                            <SelectValue placeholder={t("peers.topicPlaceholder")} />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            {topics.map((topic: any) => (
                                                                <SelectItem key={topic.id} value={topic.id}>
                                                                    {topic.topic_name}
                                                                </SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </Select>
                                                </div>

                                                <ProductEditor
                                                    role="peer"
                                                    onCancel={() => setNewPeerProductOpen(null)}
                                                    onSubmit={(v) => {
                                                        const topicId =
                                                            newPeerProductTopic[peer.id];
                                                        if (!topicId) {
                                                            toast.error(t("peers.selectTopicFirst"));
                                                            return;
                                                        }
                                                        return handleCreatePeerProduct(
                                                            peer.id,
                                                            topicId,
                                                            v,
                                                        );
                                                    }}
                                                />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </Card>
                    );
                })}
                {peers.length === 0 && (
                    <div className="text-center py-6 text-muted-foreground border border-dashed rounded-lg text-sm">
                        {t("peers.empty")}
                    </div>
                )}
            </div>
        </TabsContent>
    );
}
