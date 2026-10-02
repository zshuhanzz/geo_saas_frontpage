import { useEffect, useMemo, useRef, useState } from "react";
import { Boxes, Loader2, PackageCheck, Pencil, Save, ShieldCheck } from "lucide-react";

import {
    type FeatureDefinition,
    type FeaturePackage,
    type FeatureRegistryResponse,
    type WorkspaceOption,
    getFeaturePackages,
    getFeatureRegistry,
    getFeatureWorkspaceOptions,
    getWorkspaceEntitlements,
    saveFeaturePackage,
    saveWorkspaceEntitlements,
    updateFeatureMetadata,
} from "../api/client";
import { useToast } from "../components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const MODULE_ORDER = ["analytics", "actions"];

function FeatureToggleList({
    features,
    selected,
    lockedKeys = [],
    disabled = false,
    onChange,
}: {
    features: FeatureDefinition[];
    selected: string[];
    lockedKeys?: string[];
    disabled?: boolean;
    onChange: (keys: string[]) => void;
}) {
    return (
        <div className="divide-y rounded-lg border">
            {features.map((feature) => {
                const enabled = selected.includes(feature.key);
                const locked = lockedKeys.includes(feature.key);
                return (
                    <div key={feature.key} className="flex items-start justify-between gap-4 p-4">
                        <div>
                            <div className="flex items-center gap-2">
                                <span className="font-medium">{feature.display_name_zh}</span>
                                <code className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                                    {feature.key}
                                </code>
                                {locked && <Badge variant="outline">Required</Badge>}
                            </div>
                            <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                {feature.description_zh}
                            </p>
                        </div>
                        <Switch
                            checked={enabled}
                            disabled={locked || disabled}
                            onCheckedChange={(checked) => onChange(
                                checked
                                    ? [...selected, feature.key]
                                    : selected.filter((key) => key !== feature.key),
                            )}
                        />
                    </div>
                );
            })}
        </div>
    );
}

function WorkspaceEntitlementsSkeleton({ workspaceName }: { workspaceName: string }) {
    return (
        <div
            className="space-y-4"
            aria-label={`Loading entitlements for ${workspaceName}`}
            data-testid="workspace-entitlements-skeleton"
        >
            <p className="text-sm text-muted-foreground">
                Loading grants for <span className="font-medium text-foreground">{workspaceName}</span>…
            </p>
            <div className="divide-y overflow-hidden rounded-lg border">
                {Array.from({ length: 6 }, (_, index) => (
                    <div key={index} className="flex items-center justify-between gap-4 p-4">
                        <div className="w-full max-w-md space-y-2">
                            <div className="h-4 w-40 animate-pulse rounded bg-muted" />
                            <div className="h-3 w-full animate-pulse rounded bg-muted" />
                        </div>
                        <div className="h-5 w-9 shrink-0 animate-pulse rounded-full bg-muted" />
                    </div>
                ))}
            </div>
        </div>
    );
}

export default function FeatureAccessPage() {
    const toast = useToast();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [entitlementLoading, setEntitlementLoading] = useState(false);
    const [registry, setRegistry] = useState<FeatureRegistryResponse | null>(null);
    const [packages, setPackages] = useState<FeaturePackage[]>([]);
    const [clients, setClients] = useState<WorkspaceOption[]>([]);
    const [selectedPackageKey, setSelectedPackageKey] = useState("");
    const [packageFeatureKeys, setPackageFeatureKeys] = useState<string[]>([]);
    const [selectedClientId, setSelectedClientId] = useState("");
    const [workspaceMode, setWorkspaceMode] = useState("full_platform");
    const [workspaceFeatureKeys, setWorkspaceFeatureKeys] = useState<string[]>([]);
    const [editingFeature, setEditingFeature] = useState<FeatureDefinition | null>(null);
    const selectedClientIdRef = useRef("");
    const entitlementRequestSequence = useRef(0);

    useEffect(() => {
        void (async () => {
            try {
                const [registryData, packageData, clientData] = await Promise.all([
                    getFeatureRegistry(),
                    getFeaturePackages(),
                    getFeatureWorkspaceOptions(),
                ]);
                setRegistry(registryData);
                setPackages(packageData);
                setClients(clientData);
                const firstPackage = packageData[0];
                if (firstPackage) {
                    setSelectedPackageKey(firstPackage.package_key);
                    setPackageFeatureKeys(firstPackage.feature_keys);
                }
                if (clientData[0]) {
                    selectedClientIdRef.current = clientData[0].id;
                    setEntitlementLoading(true);
                    setSelectedClientId(clientData[0].id);
                }
            } catch (error) {
                toast.error((error as Error).message);
            } finally {
                setLoading(false);
            }
        })();
    }, []);

    useEffect(() => {
        if (!selectedClientId) {
            setEntitlementLoading(false);
            return;
        }
        const requestSequence = entitlementRequestSequence.current + 1;
        entitlementRequestSequence.current = requestSequence;
        setEntitlementLoading(true);
        setWorkspaceMode("");
        setWorkspaceFeatureKeys([]);
        void getWorkspaceEntitlements(selectedClientId)
            .then((data) => {
                if (requestSequence !== entitlementRequestSequence.current) return;
                setWorkspaceMode(data.is_custom ? "custom" : (data.applied_package_key || "custom"));
                setWorkspaceFeatureKeys(data.feature_keys);
            })
            .catch((error) => {
                if (requestSequence !== entitlementRequestSequence.current) return;
                toast.error((error as Error).message);
            })
            .finally(() => {
                if (requestSequence === entitlementRequestSequence.current) {
                    setEntitlementLoading(false);
                }
            });

        return () => {
            if (requestSequence === entitlementRequestSequence.current) {
                entitlementRequestSequence.current += 1;
            }
        };
    }, [selectedClientId]);

    const features = useMemo(
        () => [...(registry?.features || [])].sort((a, b) => (
            MODULE_ORDER.indexOf(a.module_key) - MODULE_ORDER.indexOf(b.module_key)
            || a.sort_order - b.sort_order
        )),
        [registry],
    );
    const selectedPackage = packages.find((item) => item.package_key === selectedPackageKey);
    const selectedWorkspaceName = clients.find(
        (client) => client.id === selectedClientId,
    )?.name || "Workspace";

    function chooseWorkspace(clientId: string) {
        if (clientId === selectedClientIdRef.current) return;
        entitlementRequestSequence.current += 1;
        selectedClientIdRef.current = clientId;
        setEntitlementLoading(true);
        setWorkspaceMode("");
        setWorkspaceFeatureKeys([]);
        setSelectedClientId(clientId);
    }

    function choosePackage(packageKey: string) {
        setSelectedPackageKey(packageKey);
        setPackageFeatureKeys(
            packages.find((item) => item.package_key === packageKey)?.feature_keys || [],
        );
    }

    async function handleSavePackage() {
        if (!selectedPackage) return;
        setSaving(true);
        try {
            await saveFeaturePackage({ ...selectedPackage, feature_keys: packageFeatureKeys });
            setPackages(await getFeaturePackages());
            toast.success("Feature package saved");
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function handleSaveWorkspace() {
        if (!selectedClientId || entitlementLoading || !workspaceMode) return;
        const clientId = selectedClientId;
        const requestSequence = entitlementRequestSequence.current;
        setSaving(true);
        try {
            await saveWorkspaceEntitlements(
                clientId,
                workspaceMode === "custom"
                    ? { package_key: null, feature_keys: workspaceFeatureKeys }
                    : { package_key: workspaceMode, feature_keys: null },
            );
            const refreshed = await getWorkspaceEntitlements(clientId);
            if (
                clientId !== selectedClientIdRef.current
                || requestSequence !== entitlementRequestSequence.current
            ) return;
            setWorkspaceMode(
                refreshed.is_custom
                    ? "custom"
                    : (refreshed.applied_package_key || "custom"),
            );
            setWorkspaceFeatureKeys(refreshed.feature_keys);
            toast.success("Workspace entitlements saved");
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function handleSaveFeatureMetadata() {
        if (!editingFeature) return;
        setSaving(true);
        try {
            await updateFeatureMetadata(editingFeature.key, {
                display_name_zh: editingFeature.display_name_zh,
                display_name_en: editingFeature.display_name_en,
                description_zh: editingFeature.description_zh,
                description_en: editingFeature.description_en,
                sort_order: editingFeature.sort_order,
                is_active: editingFeature.is_active,
            });
            const refreshed = await getFeatureRegistry();
            setRegistry(refreshed);
            setEditingFeature(null);
            toast.success("Feature metadata saved");
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setSaving(false);
        }
    }

    if (loading || !registry) {
        return <div className="flex h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin" /></div>;
    }

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">Feature Access</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                    Technical keys and route mappings are code-owned. Manage display metadata, packages, and effective Workspace grants here.
                </p>
            </div>

            <Tabs defaultValue="workspace" className="space-y-4">
                <TabsList>
                    <TabsTrigger value="workspace">Workspace Grants</TabsTrigger>
                    <TabsTrigger value="packages">Feature Packages</TabsTrigger>
                    <TabsTrigger value="catalog">Feature Catalog & Roles</TabsTrigger>
                </TabsList>

                <TabsContent value="workspace">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2"><ShieldCheck className="h-5 w-5" /> Workspace Entitlements</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-5">
                            <div className="grid gap-4 md:grid-cols-2">
                                <Select value={selectedClientId} onValueChange={chooseWorkspace} disabled={saving}>
                                    <SelectTrigger><SelectValue placeholder="Select Workspace" /></SelectTrigger>
                                    <SelectContent>
                                        {clients.map((client) => <SelectItem key={client.id} value={client.id}>{client.name}</SelectItem>)}
                                    </SelectContent>
                                </Select>
                                {entitlementLoading ? (
                                    <div className="h-9 animate-pulse rounded-md bg-muted" />
                                ) : (
                                    <Select
                                        value={workspaceMode}
                                        disabled={entitlementLoading || saving}
                                        onValueChange={(value) => {
                                            setWorkspaceMode(value);
                                            if (value !== "custom") {
                                                setWorkspaceFeatureKeys(packages.find((item) => item.package_key === value)?.feature_keys || []);
                                            }
                                        }}
                                    >
                                        <SelectTrigger><SelectValue placeholder="Select preset" /></SelectTrigger>
                                        <SelectContent>
                                            {packages.filter((item) => item.is_active).map((item) => (
                                                <SelectItem key={item.package_key} value={item.package_key}>{item.display_name_zh} · {item.display_name_en}</SelectItem>
                                            ))}
                                            <SelectItem value="custom">自定义 · Custom</SelectItem>
                                        </SelectContent>
                                    </Select>
                                )}
                            </div>
                            {entitlementLoading ? (
                                <WorkspaceEntitlementsSkeleton workspaceName={selectedWorkspaceName} />
                            ) : (
                                <>
                                    <FeatureToggleList
                                        features={features}
                                        selected={workspaceFeatureKeys}
                                        disabled={entitlementLoading || saving}
                                        onChange={(keys) => {
                                            setWorkspaceMode("custom");
                                            setWorkspaceFeatureKeys(keys);
                                        }}
                                    />
                                    <Button
                                        onClick={() => void handleSaveWorkspace()}
                                        disabled={saving || entitlementLoading || !selectedClientId}
                                    >
                                        {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
                                        Save Workspace Grants
                                    </Button>
                                </>
                            )}
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="packages">
                    <Card>
                        <CardHeader><CardTitle className="flex items-center gap-2"><PackageCheck className="h-5 w-5" /> Package Composition</CardTitle></CardHeader>
                        <CardContent className="space-y-5">
                            <Select value={selectedPackageKey} onValueChange={choosePackage}>
                                <SelectTrigger className="max-w-md"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    {packages.map((item) => <SelectItem key={item.package_key} value={item.package_key}>{item.display_name_zh} · {item.display_name_en}</SelectItem>)}
                                </SelectContent>
                            </Select>
                            <FeatureToggleList
                                features={features}
                                selected={packageFeatureKeys}
                                lockedKeys={
                                    selectedPackageKey === "analytics"
                                    || selectedPackageKey === "full_platform"
                                        ? ["actions.configuration"]
                                        : []
                                }
                                onChange={setPackageFeatureKeys}
                            />
                            <Button onClick={() => void handleSavePackage()} disabled={saving || !selectedPackage}>
                                {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
                                Save Package
                            </Button>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="catalog">
                    <div className="grid gap-4 lg:grid-cols-2">
                        {registry.modules.map((module) => (
                            <Card key={module.key}>
                                <CardHeader><CardTitle className="flex items-center gap-2"><Boxes className="h-5 w-5" /> {module.label_zh} · {module.label_en}</CardTitle></CardHeader>
                                <CardContent className="space-y-3">
                                    {features.filter((feature) => feature.module_key === module.key).map((feature) => (
                                        <div key={feature.key} className="rounded-lg border p-4">
                                            <div className="flex items-center justify-between gap-3">
                                                <div className="font-medium">{feature.display_name_zh} · {feature.display_name_en}</div>
                                                <div className="flex items-center gap-2">
                                                    <code className="text-[11px] text-muted-foreground">{feature.key}</code>
                                                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setEditingFeature({ ...feature })}>
                                                        <Pencil className="h-3.5 w-3.5" />
                                                    </Button>
                                                </div>
                                            </div>
                                            <p className="mt-2 text-xs leading-5 text-muted-foreground">{feature.description_zh}</p>
                                            <div className="mt-3 flex gap-2">
                                                {["super_admin", "account_manager", "admin", "viewer"].map((role) => {
                                                    const capabilities = registry.role_capabilities[role]?.[feature.key] || [];
                                                    return (
                                                        <Badge key={role} variant={capabilities.includes("view") ? "default" : "secondary"}>
                                                            {role}: {capabilities.length ? capabilities.join(" · ") : "none"}
                                                        </Badge>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    ))}
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                </TabsContent>
            </Tabs>

            <Dialog open={!!editingFeature} onOpenChange={(open) => !open && setEditingFeature(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Edit feature metadata</DialogTitle>
                    </DialogHeader>
                    {editingFeature && (
                        <div className="space-y-4 py-2">
                            <div className="rounded-md bg-muted px-3 py-2 font-mono text-xs">{editingFeature.key}</div>
                            <div className="grid gap-4 md:grid-cols-2">
                                <div className="space-y-2">
                                    <Label>中文名称</Label>
                                    <Input value={editingFeature.display_name_zh} onChange={(event) => setEditingFeature({ ...editingFeature, display_name_zh: event.target.value })} />
                                </div>
                                <div className="space-y-2">
                                    <Label>English name</Label>
                                    <Input value={editingFeature.display_name_en} onChange={(event) => setEditingFeature({ ...editingFeature, display_name_en: event.target.value })} />
                                </div>
                            </div>
                            <div className="space-y-2">
                                <Label>中文介绍</Label>
                                <Input value={editingFeature.description_zh} onChange={(event) => setEditingFeature({ ...editingFeature, description_zh: event.target.value })} />
                            </div>
                            <div className="space-y-2">
                                <Label>English description</Label>
                                <Input value={editingFeature.description_en} onChange={(event) => setEditingFeature({ ...editingFeature, description_en: event.target.value })} />
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditingFeature(null)}>Cancel</Button>
                        <Button disabled={saving} onClick={() => void handleSaveFeatureMetadata()}>
                            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                            Save
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
