import { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import {
    getFeatureCatalog,
    getWorkspaceContext,
    getWorkspaces,
    type FeatureCatalogItem,
    type WorkspaceTopic,
} from '../lib/api';
import type { FeatureCapability, FeatureKey, WorkspaceRole } from '@/generated/featureRegistry.generated';

interface ClientData {
    id: string;
    name: string;
    topics: WorkspaceTopic[];
    config_platforms: string[];
    config_countries: string[];
    config_languages: string[];
    role: WorkspaceRole;
    enabled_features: FeatureKey[];
    feature_capabilities: Partial<Record<FeatureKey, FeatureCapability[]>>;
    entitlement_override: boolean;
}

interface SaaSContextType {
    clients: ClientData[];
    clientId: string;
    setClientId: (id: string) => void;
    activeClientName: string;
    platform: string;
    setPlatform: (platform: string) => void;
    country: string;
    setCountry: (country: string) => void;
    loadingClients: boolean;
    loadingWorkspaceContext: boolean;
    refreshClients: () => Promise<void>;
    activeClient: ClientData | null;
    featureCatalog: Partial<Record<FeatureKey, FeatureCatalogItem>>;
    can: (featureKey: FeatureKey, capability?: FeatureCapability) => boolean;
    isEntitled: (featureKey: FeatureKey) => boolean;
}

const SaaSContext = createContext<SaaSContextType | undefined>(undefined);

function normalizeClients(data: Awaited<ReturnType<typeof getWorkspaces>>): ClientData[] {
    return (data || []).map((client) => ({
        ...client,
        topics: [],
        config_platforms: [],
        config_countries: [],
        config_languages: [],
        role: client.role as WorkspaceRole,
        enabled_features: client.enabled_features as FeatureKey[],
        feature_capabilities: Object.fromEntries(
            Object.entries(client.feature_capabilities || {}).map(
                ([featureKey, capabilities]) => [
                    featureKey,
                    capabilities as FeatureCapability[],
                ],
            ),
        ) as Partial<Record<FeatureKey, FeatureCapability[]>>,
    }));
}

export function SaaSProvider({ children }: { children: ReactNode }) {
    const [clients, setClients] = useState<ClientData[]>([]);
    const [clientId, setClientIdState] = useState('');
    const [loadingClients, setLoadingClients] = useState(true);
    const [loadingWorkspaceContext, setLoadingWorkspaceContext] = useState(false);
    const [featureCatalog, setFeatureCatalog] = useState<
        Partial<Record<FeatureKey, FeatureCatalogItem>>
    >({});

    const [platform, setPlatform] = useState('');
    const [country, setCountry] = useState('');
    const selectedWorkspaceCanLoadContext = (
        clients.find((client) => client.id === clientId)
            ?.enabled_features.includes('actions.configuration')
        ?? false
    );

    useEffect(() => {
        void loadClientsData();
    }, []);

    useEffect(() => {
        if (!clientId || !selectedWorkspaceCanLoadContext) {
            setLoadingWorkspaceContext(false);
            if (clientId) {
                setClients((current) => current.map((client) => (
                    client.id === clientId
                        ? {
                            ...client,
                            topics: [],
                            config_platforms: [],
                            config_countries: [],
                            config_languages: [],
                        }
                        : client
                )));
            }
            return;
        }
        let active = true;
        setLoadingWorkspaceContext(true);
        void getWorkspaceContext(clientId)
            .then((context) => {
                if (!active) return;
                setClients((current) => current.map((client) => (
                    client.id === clientId
                        ? { ...client, ...context }
                        : client
                )));
            })
            .catch((err) => {
                if (active) console.error('Failed to load Workspace context:', err);
            })
            .finally(() => {
                if (active) setLoadingWorkspaceContext(false);
            });
        return () => {
            active = false;
        };
    }, [clientId, selectedWorkspaceCanLoadContext]);

    async function loadClientsData() {
        // DEV BYPASS: inject a mock client so the workspace check passes without a backend
        if (import.meta.env.VITE_DEV_AUTH_USER_EMAIL) {
            const mockClient: ClientData = {
                id: 'dev-client-001',
                name: 'AnswerX Demo',
                topics: [],
                config_platforms: [],
                config_countries: [],
                config_languages: [],
                role: 'admin' as WorkspaceRole,
                enabled_features: [
                    'insights.visibility',
                    'insights.citation',
                    'insights.sentiment',
                    'insights.prompts',
                    'insights.fanouts',
                    'dashboards.overview',
                    'dashboards.citation',
                    'dashboards.sentiment',
                    'actions.configuration',
                    'agents.analysis',
                    'agents.content',
                    'agents.chat',
                    'reports',
                ] as FeatureKey[],
                feature_capabilities: {} as Partial<Record<FeatureKey, FeatureCapability[]>>,
                entitlement_override: true,
            };
            setClients([mockClient]);
            setClientIdState(mockClient.id);
            localStorage.setItem('geo_saas_client_id', mockClient.id);
            setLoadingClients(false);
            return;
        }

        try {
            const [workspaceData, catalogData] = await Promise.all([
                getWorkspaces(),
                getFeatureCatalog().catch(() => []),
            ]);
            const data = normalizeClients(workspaceData);
            setClients(data);
            setFeatureCatalog(Object.fromEntries(
                catalogData.map((feature) => [feature.feature_key, feature]),
            ) as Partial<Record<FeatureKey, FeatureCatalogItem>>);

            // Auto select first client if none selected
            const requestedClientId = new URLSearchParams(window.location.search).get('client_id');
            const requestedClient = data?.find((c: ClientData) => c.id === requestedClientId);
            const savedClientId = localStorage.getItem('geo_saas_client_id');
            const validSaved = data?.find((c: ClientData) => c.id === savedClientId);

            let activeId = "";
            if (requestedClient) {
                activeId = requestedClient.id;
            } else if (validSaved) {
                activeId = validSaved.id;
            } else if (data && data.length > 0) {
                activeId = data[0].id;
            }

            if (activeId) {
                setClientIdState(activeId);
                localStorage.setItem('geo_saas_client_id', activeId);
            } else {
                setClientIdState('');
                localStorage.removeItem('geo_saas_client_id');
            }
        } catch (err) {
            console.error('Failed to load clients:', err);
        } finally {
            setLoadingClients(false);
        }
    }

    async function refreshClients() {
        const data = normalizeClients(await getWorkspaces());
        setClients((current) => data.map((workspace) => {
            const existing = current.find((client) => client.id === workspace.id);
            return existing ? { ...existing, ...workspace } : workspace;
        }));
        if (!data?.some((client: ClientData) => client.id === clientId)) {
            const nextId = data?.[0]?.id || "";
            setClientIdState(nextId);
            if (nextId) {
                localStorage.setItem('geo_saas_client_id', nextId);
            } else {
                localStorage.removeItem('geo_saas_client_id');
            }
        }
    }

    const setClientId = (id: string) => {
        setClientIdState(id);
        localStorage.setItem('geo_saas_client_id', id);
    };

    const activeClientName = clients.find(c => c.id === clientId)?.name || (clients.length ? 'Select Workspace' : 'No Authorized Workspace');
    const activeClient = clients.find(c => c.id === clientId) || null;
    const isEntitled = (featureKey: FeatureKey) => (
        activeClient?.enabled_features.includes(featureKey) ?? false
    );
    const can = (
        featureKey: FeatureKey,
        capability: FeatureCapability = 'view',
    ) => (
        isEntitled(featureKey)
        && (activeClient?.feature_capabilities[featureKey]?.includes(capability) ?? false)
    );

    return (
        <SaaSContext.Provider value={{
            clients,
            clientId,
            setClientId,
            activeClientName,
            platform,
            setPlatform,
            country,
            setCountry,
            loadingClients,
            loadingWorkspaceContext,
            refreshClients,
            activeClient,
            featureCatalog,
            can,
            isEntitled,
        }}>
            {children}
        </SaaSContext.Provider>
    );
}

export function useSaaS() {
    const context = useContext(SaaSContext);
    if (context === undefined) {
        throw new Error('useSaaS must be used within a SaaSProvider');
    }
    return context;
}
