import { useState, useEffect } from 'react';
import type { components } from '../api/openapi';
import { useToast, useConfirm } from '../components/Toast';
import {
    getGlobalSettings, upsertGlobalSetting, deleteGlobalSetting,
    getGlobalPlatforms, createGlobalPlatform, updateGlobalPlatform, deleteGlobalPlatform,
    getGlobalIntents, createGlobalIntent, updateGlobalIntent, deleteGlobalIntent,
    getDomainCategories, getDomainCategoryEnums, createDomainCategory, updateDomainCategory, deleteDomainCategory,
    getSentimentThemes, createSentimentTheme, updateSentimentTheme, deleteSentimentTheme
} from '../api/client';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type SettingOut = components["schemas"]["SettingOut"];
type PlatformOut = components["schemas"]["PlatformOut"];
type IntentOut = components["schemas"]["IntentOut"];
type DomainCategoryOut = components["schemas"]["DomainCategoryOut"];
type SentimentThemeOut = components["schemas"]["SentimentThemeOut"];

interface SimplePagination {
    page: number;
    total: number;
    pages: number;
}

type TabKey = 'settings' | 'platforms' | 'intents' | 'domainCategories' | 'sentimentThemes';

const SECRET_SETTING_KEYS = new Set([
    'reddit_api_client_secret',
]);

function isSecretSetting(key: string): boolean {
    return SECRET_SETTING_KEYS.has(key) || /(_secret|_password|_token|api_key)$/i.test(key);
}

export default function GlobalConfigPage() {
    const toast = useToast();
    const confirm = useConfirm();
    const [activeTab, setActiveTab] = useState<TabKey>('settings');

    // States
    const [settings, setSettings] = useState<SettingOut[]>([]);
    const [platforms, setPlatforms] = useState<PlatformOut[]>([]);
    const [intents, setIntents] = useState<IntentOut[]>([]);
    const [domainCats, setDomainCats] = useState<DomainCategoryOut[]>([]);
    const [catEnums, setCatEnums] = useState<string[]>([]);
    const [dcSearch, setDcSearch] = useState<string>('');
    const [dcCategoryFilter, setDcCategoryFilter] = useState<string>('');
    const [dcPage, setDcPage] = useState<number>(1);
    const [dcPagination, setDcPagination] = useState<SimplePagination>({ page: 1, total: 0, pages: 1 });
    // Sentiment Theme Dictionary states
    const [sentimentThemes, setSentimentThemes] = useState<SentimentThemeOut[]>([]);
    const [stSearch, setStSearch] = useState<string>('');
    const [stIndustryFilter, setStIndustryFilter] = useState<string>('');
    const [stCreatedByFilter, setStCreatedByFilter] = useState<string>('');
    const [stPage, setStPage] = useState<number>(1);
    const [stPagination, setStPagination] = useState<SimplePagination>({ page: 1, total: 0, pages: 1 });
    const [stIndustries, setStIndustries] = useState<string[]>([]);
    const [loading, setLoading] = useState<boolean>(true);

    useEffect(() => {
        loadData();
    }, [activeTab]);

    async function loadData(): Promise<void> {
        setLoading(true);
        try {
            if (activeTab === 'settings') {
                setSettings(await getGlobalSettings());
            } else if (activeTab === 'platforms') {
                setPlatforms(await getGlobalPlatforms());
            } else if (activeTab === 'intents') {
                setIntents(await getGlobalIntents());
            } else if (activeTab === 'domainCategories') {
                const [result, enums] = await Promise.all([getDomainCategories(dcSearch, dcCategoryFilter, dcPage), getDomainCategoryEnums()]);
                setDomainCats(result.data || []);
                const p = result.pagination;
                setDcPagination(p ? { page: p.page, total: p.total, pages: p.pages } : { page: 1, total: 0, pages: 1 });
                setCatEnums(enums);
            } else if (activeTab === 'sentimentThemes') {
                const result = await getSentimentThemes(stSearch, stIndustryFilter, stCreatedByFilter, stPage);
                setSentimentThemes(result.data || []);
                const p = result.pagination;
                setStPagination(p ? { page: p.page, total: p.total, pages: p.pages } : { page: 1, total: 0, pages: 1 });
                setStIndustries(result.industries || []);
            }
        } catch (err) {
            console.error('Failed to load global config:', err);
        } finally {
            setLoading(false);
        }
    }

    // --- Settings UI ---
    function SettingsSection() {
        const [newKey, setNewKey] = useState<string>('');
        const [newValue, setNewValue] = useState<string>('');
        const [newDesc, setNewDesc] = useState<string>('');

        async function handleSave(e: React.FormEvent<HTMLFormElement>): Promise<void> {
            e.preventDefault();
            if (!newKey || !newValue) return;
            try {
                await upsertGlobalSetting(newKey, newValue, newDesc);
                setNewKey(''); setNewValue(''); setNewDesc('');
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        async function handleDelete(key: string): Promise<void> {
            if (!await confirm('Are you sure you want to delete this setting?', 'Delete Setting')) return;
            try {
                await deleteGlobalSetting(key);
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        return (
            <div className="space-y-6">
                <div className="bg-card text-card-foreground border rounded-xl shadow-sm p-6">
                    <h3 className="text-lg font-bold text-foreground mb-4">Add / Edit Setting</h3>
                    <form onSubmit={handleSave} className="flex gap-4 items-end">
                        <div className="flex-1">
                            <label className="text-muted-foreground text-xs uppercase mb-1 block">Key</label>
                            <input type="text" value={newKey} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewKey(e.target.value)} required placeholder="e.g. brainstorming_model_id" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                        </div>
                        <div className="flex-1">
                            <label className="text-muted-foreground text-xs uppercase mb-1 block">Value</label>
                            <input type={isSecretSetting(newKey) ? "password" : "text"} value={newValue} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewValue(e.target.value)} required placeholder={isSecretSetting(newKey) ? "Enter a new secret value" : "e.g. gemini-3-flash-preview"} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                            {isSecretSetting(newKey) && (
                                <p className="mt-1 text-[11px] text-muted-foreground">Secret values are masked on read. Enter a value only when rotating/updating it.</p>
                            )}
                        </div>
                        <div className="flex-1">
                            <label className="text-muted-foreground text-xs uppercase mb-1 block">Description</label>
                            <input type="text" value={newDesc} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewDesc(e.target.value)} placeholder="Optional description" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                        </div>
                        <button type="submit" className="btn-primary">Save</button>
                    </form>
                </div>

                <div className="bg-card text-card-foreground border rounded-xl shadow-sm">
                    <table className="w-full text-left text-sm text-muted-foreground">
                        <thead className="bg-muted/50 text-muted-foreground uppercase">
                            <tr>
                                <th className="px-6 py-4 font-medium">Key</th>
                                <th className="px-6 py-4 font-medium">Value</th>
                                <th className="px-6 py-4 font-medium">Description</th>
                                <th className="px-6 py-4 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-dark-800">
                            {settings.map((s) => (
                                <tr key={s.key} className="hover:bg-muted/30 transition-colors">
                                    <td className="px-6 py-4 font-medium text-foreground">{s.key}</td>
                                    <td className="px-6 py-4 font-mono text-primary">
                                        {isSecretSetting(s.key) && s.value ? '••••••••' : s.value}
                                    </td>
                                    <td className="px-6 py-4">{s.description}</td>
                                    <td className="px-6 py-4 text-right">
                                        <button onClick={() => { setNewKey(s.key); setNewValue(isSecretSetting(s.key) ? '' : s.value); setNewDesc(s.description || ''); }} className="text-blue-400 hover:text-blue-300 mr-4">Edit</button>
                                        <button onClick={() => handleDelete(s.key)} className="text-red-400 hover:text-red-300">Delete</button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    }

    // --- Platforms UI ---
    function PlatformsSection() {
        interface PlatformForm {
            platform_id: string;
            display_name: string;
            supported_countries: string;
            system_instructions: string;
        }
        const [form, setForm] = useState<PlatformForm>({ platform_id: '', display_name: '', supported_countries: '', system_instructions: '' });

        async function handleSave(e: React.FormEvent<HTMLFormElement>): Promise<void> {
            e.preventDefault();
            try {
                const payload = {
                    ...form,
                    supported_countries: form.supported_countries.split(',').map((s) => s.trim()).filter(Boolean)
                };

                // If it already exists, update instead of create (simple check based on matching ID in list)
                const exists = platforms.find((p) => p.platform_id === form.platform_id);
                if (exists) {
                    await updateGlobalPlatform(String(exists.id), {
                        display_name: payload.display_name,
                        supported_countries: payload.supported_countries,
                        system_instructions: payload.system_instructions
                    });
                } else {
                    await createGlobalPlatform(payload);
                }
                setForm({ platform_id: '', display_name: '', supported_countries: '', system_instructions: '' });
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        async function handleDelete(uuid: string): Promise<void> {
            if (!await confirm('Are you sure you want to delete this platform?', 'Delete Platform')) return;
            try { await deleteGlobalPlatform(uuid); loadData(); } catch (err) { toast.error((err as Error).message); }
        }

        async function toggleActive(uuid: string, currentStatus: boolean | null | undefined): Promise<void> {
            try { await updateGlobalPlatform(uuid, { is_active: !currentStatus }); loadData(); } catch (err) { toast.error((err as Error).message); }
        }

        return (
            <div className="space-y-6">
                <div className="bg-card text-card-foreground border rounded-xl shadow-sm p-6">
                    <h3 className="text-lg font-bold text-foreground mb-4">Add / Edit Platform</h3>
                    <form onSubmit={handleSave} className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="text-muted-foreground text-sm block mb-1">Platform ID *</label>
                                <input type="text" value={form.platform_id} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, platform_id: e.target.value })} required placeholder="e.g. chatgpt" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                                <p className="text-xs text-muted-foreground/70 mt-1">Must precisely match Cloro API required strings.</p>
                            </div>
                            <div>
                                <label className="text-muted-foreground text-sm block mb-1">Display Name *</label>
                                <input type="text" value={form.display_name} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, display_name: e.target.value })} required placeholder="e.g. ChatGPT" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                            </div>
                            <div>
                                <label className="text-muted-foreground text-sm block mb-1">Supported Countries (comma-separated)</label>
                                <input type="text" value={form.supported_countries} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, supported_countries: e.target.value })} placeholder="US, GB, DE" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                            </div>
                        </div>
                        <div>
                            <label className="text-muted-foreground text-sm block mb-1">System Instructions</label>
                            <textarea value={form.system_instructions} onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setForm({ ...form, system_instructions: e.target.value })} placeholder="Optional platform-specific instructions" className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"></textarea>
                        </div>
                        <div className="flex justify-end">
                            <button type="submit" className="btn-primary">Save Platform</button>
                        </div>
                    </form>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {platforms.map((p) => (
                        <div key={String(p.id)} className={`bg-card text-card-foreground border rounded-xl shadow-sm p-5 border-l-4 ${p.is_active ? 'border-primary' : 'border-border'}`}>
                            <div className="flex justify-between items-start mb-2">
                                <div>
                                    <h4 className="text-foreground font-bold text-lg flex items-center gap-2">
                                        {p.display_name}
                                        {!p.is_active && <span className="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground">Inactive</span>}
                                    </h4>
                                    <span className="text-xs text-primary font-mono">{p.platform_id}</span>
                                </div>
                                <div className="text-xs flex gap-3 text-muted-foreground">
                                    <button onClick={() => { setForm({ platform_id: p.platform_id, display_name: p.display_name, supported_countries: (p.supported_countries || []).join(', '), system_instructions: p.system_instructions || '' }) }} className="hover:text-foreground">Edit</button>
                                    <button onClick={() => toggleActive(String(p.id), p.is_active)} className="hover:text-foreground">{p.is_active ? 'Disable' : 'Enable'}</button>
                                    <button onClick={() => handleDelete(String(p.id))} className="text-red-400 hover:text-red-300">Delete</button>
                                </div>
                            </div>
                            <div className="mt-4 text-sm text-muted-foreground space-y-1">
                                <p><span className="text-muted-foreground/70">Countries:</span> {(p.supported_countries || []).join(', ') || 'None'}</p>
                                {p.system_instructions && <p className="mt-2 text-xs opacity-70 line-clamp-2">"{p.system_instructions}"</p>}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        );
    }

    // --- Intents UI ---
    function IntentsSection() {
        interface IntentForm {
            intent_name: string;
            allocation_ratio: number | string;  // input field allows string while typing
            description: string;
            categories: string[];
        }
        const [form, setForm] = useState<IntentForm>({ intent_name: '', allocation_ratio: 0.5, description: '', categories: [] });

        const CATEGORY_OPTIONS: string[] = ['Visibility', 'Citation', 'Sentiment'];

        function parseCategories(val: unknown): string[] {
            if (Array.isArray(val)) return val.filter((item): item is string => typeof item === 'string');
            if (typeof val === 'string') {
                try {
                    const parsed: unknown = JSON.parse(val);
                    return Array.isArray(parsed)
                        ? parsed.filter((item): item is string => typeof item === 'string')
                        : [];
                } catch {
                    return [];
                }
            }
            return [];
        }

        function toggleCategory(cat: string): void {
            setForm((prev) => ({
                ...prev,
                categories: prev.categories.includes(cat)
                    ? prev.categories.filter((c) => c !== cat)
                    : [...prev.categories, cat]
            }));
        }

        async function handleSave(e: React.FormEvent<HTMLFormElement>): Promise<void> {
            e.preventDefault();
            try {
                const payload = {
                    intent_name: form.intent_name,
                    allocation_ratio: typeof form.allocation_ratio === 'string' ? parseFloat(form.allocation_ratio) : form.allocation_ratio,
                    description: form.description,
                    categories: form.categories
                };

                const exists = intents.find((i) => i.intent_name === form.intent_name);
                if (exists) {
                    await updateGlobalIntent(String(exists.id), {
                        allocation_ratio: payload.allocation_ratio,
                        description: payload.description,
                        categories: payload.categories
                    });
                } else {
                    await createGlobalIntent(payload);
                }
                setForm({ intent_name: '', allocation_ratio: 0.5, description: '', categories: [] });
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        async function handleDelete(uuid: string): Promise<void> {
            if (!await confirm('Are you sure you want to delete this intent?', 'Delete Intent')) return;
            try { await deleteGlobalIntent(uuid); loadData(); } catch (err) { toast.error((err as Error).message); }
        }

        async function toggleActive(uuid: string, currentStatus: boolean | null | undefined): Promise<void> {
            try { await updateGlobalIntent(uuid, { is_active: !currentStatus }); loadData(); } catch (err) { toast.error((err as Error).message); }
        }

        return (
            <div className="space-y-6">
                <div className="bg-card text-card-foreground border rounded-xl shadow-sm p-6">
                    <h3 className="text-lg font-bold text-foreground mb-4">Add / Edit Intent</h3>
                    <form onSubmit={handleSave} className="space-y-4">
                        <div className="flex gap-4 items-end">
                            <div className="flex-1">
                                <label className="text-muted-foreground text-xs uppercase mb-1 block">Intent Name *</label>
                                <input type="text" value={form.intent_name} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, intent_name: e.target.value })} required placeholder="e.g. Solution Discovery" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                            </div>
                            <div className="w-32">
                                <label className="text-muted-foreground text-xs uppercase mb-1 block">Ratio (0-1) *</label>
                                <input type="number" step="0.01" min="0" max="1" value={form.allocation_ratio} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, allocation_ratio: e.target.value })} required className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                            </div>
                            <div className="flex-1">
                                <label className="text-muted-foreground text-xs uppercase mb-1 block">Description</label>
                                <input type="text" value={form.description} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, description: e.target.value })} placeholder="Optional description" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                            </div>
                        </div>
                        <div className="flex items-center gap-6">
                            <label className="text-muted-foreground text-xs uppercase">Categories</label>
                            {CATEGORY_OPTIONS.map((cat) => (
                                <label key={cat} className="flex items-center gap-2 cursor-pointer select-none">
                                    <input
                                        type="checkbox"
                                        checked={form.categories.includes(cat)}
                                        onChange={() => toggleCategory(cat)}
                                        className="rounded border-input"
                                    />
                                    <span className="text-sm text-foreground">{cat}</span>
                                </label>
                            ))}
                            <div className="flex-1" />
                            <button type="submit" className="btn-primary">Save</button>
                        </div>
                    </form>
                </div>

                <div className="bg-card text-card-foreground border rounded-xl shadow-sm">
                    <table className="w-full text-left text-sm text-muted-foreground">
                        <thead className="bg-muted/50 text-muted-foreground uppercase">
                            <tr>
                                <th className="px-6 py-4 font-medium">Intent Name</th>
                                <th className="px-6 py-4 font-medium">Categories</th>
                                <th className="px-6 py-4 font-medium">Allocation Ratio</th>
                                <th className="px-6 py-4 font-medium">Status</th>
                                <th className="px-6 py-4 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-dark-800">
                            {intents.map((i) => (
                                <tr key={String(i.id)} className="hover:bg-muted/30 transition-colors">
                                    <td className="px-6 py-4 font-medium text-foreground">
                                        {i.intent_name}
                                        {i.description && <div className="text-xs text-muted-foreground/70 font-normal mt-1">{i.description}</div>}
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex flex-wrap gap-1">
                                            {parseCategories(i.categories).map((cat) => {
                                                const colors: Record<string, string> = { Visibility: 'bg-green-500/10 text-green-400', Citation: 'bg-blue-500/10 text-blue-400', Sentiment: 'bg-purple-500/10 text-purple-400' };
                                                return <span key={cat} className={`px-2 py-0.5 rounded-full text-xs ${colors[cat] || 'bg-muted text-muted-foreground'}`}>{cat}</span>;
                                            })}
                                            {parseCategories(i.categories).length === 0 && <span className="text-xs text-muted-foreground/50">—</span>}
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex items-center gap-2">
                                            <span className="text-primary">{(i.allocation_ratio * 100).toFixed(0)}%</span>
                                            <div className="w-24 bg-muted h-1.5 rounded-full overflow-hidden">
                                                <div className="bg-primary h-full" style={{ width: `${i.allocation_ratio * 100}%` }}></div>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <span className={`px-2 py-1 rounded-full text-xs ${i.is_active ? 'bg-green-500/10 text-green-400' : 'bg-muted text-muted-foreground'}`}>
                                            {i.is_active ? 'Active' : 'Inactive'}
                                        </span>
                                    </td>
                                    <td className="px-6 py-4 text-right">
                                        <button onClick={() => setForm({ intent_name: i.intent_name, allocation_ratio: i.allocation_ratio, description: i.description || '', categories: parseCategories(i.categories) })} className="text-blue-400 hover:text-blue-300 mr-4">Edit</button>
                                        <button onClick={() => toggleActive(String(i.id), i.is_active)} className="text-muted-foreground hover:text-foreground mr-4">{i.is_active ? 'Disable' : 'Enable'}</button>
                                        <button onClick={() => handleDelete(String(i.id))} className="text-red-400 hover:text-red-300">Delete</button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    }

    // --- Domain Categories UI ---
    function DomainCategoriesSection() {
        const [newDomain, setNewDomain] = useState<string>('');
        const [newCategory, setNewCategory] = useState<string>('');
        const [editId, setEditId] = useState<string | null>(null);
        const [editDomain, setEditDomain] = useState<string>('');
        const [editCategory, setEditCategory] = useState<string>('');

        const catColors: Record<string, string> = {
            'Earned Media': 'bg-blue-500/20 text-blue-400',
            'Agency': 'bg-green-500/20 text-green-400',
            'Social Media': 'bg-purple-500/20 text-purple-400',
            'Owned Media': 'bg-emerald-500/20 text-emerald-400',
            'Other': 'bg-gray-500/20 text-gray-400',
        };

        async function handleAdd(e: React.FormEvent<HTMLFormElement>): Promise<void> {
            e.preventDefault();
            if (!newDomain || !newCategory) return;
            try {
                await createDomainCategory({
                    domain: newDomain,
                    category: newCategory,
                    classified_by: "manual",
                });
                toast.success('Domain category added');
                setNewDomain(''); setNewCategory('');
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        async function handleUpdate(id: string): Promise<void> {
            try {
                await updateDomainCategory(id, { domain: editDomain, category: editCategory });
                toast.success('Domain category updated');
                setEditId(null);
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        async function handleDelete(id: string): Promise<void> {
            if (!await confirm('Delete this domain category?')) return;
            try {
                await deleteDomainCategory(id);
                toast.success('Deleted');
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        return (
            <div className="space-y-4">
                {/* Search & Filter Bar */}
                <div className="flex gap-3">
                    <input
                        type="text" placeholder="Search domain..."
                        value={dcSearch}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => { setDcSearch(e.target.value); }}
                        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === 'Enter') { setDcPage(1); setTimeout(loadData, 0); } }}
                        className="flex-1 bg-input border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground"
                    />
                    <Select value={dcCategoryFilter || "__all__"} onValueChange={(v: string) => { setDcCategoryFilter(v === "__all__" ? "" : v); setDcPage(1); setTimeout(loadData, 0); }}>
                        <SelectTrigger className="w-[180px] h-9">
                            <SelectValue placeholder="All Categories" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">All Categories</SelectItem>
                            {catEnums.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                        </SelectContent>
                    </Select>
                    <button onClick={() => { setDcPage(1); setTimeout(loadData, 0); }} className="bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/80">Search</button>
                </div>

                {/* Add Form */}
                <form onSubmit={handleAdd} className="flex gap-3">
                    <input
                        type="text" placeholder="e.g. tomsguide.com" value={newDomain}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewDomain(e.target.value)}
                        className="flex-1 bg-input border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground"
                    />
                    <Select value={newCategory || "__all__"} onValueChange={(v: string) => setNewCategory(v === "__all__" ? "" : v)}>
                        <SelectTrigger className="w-[180px] h-9">
                            <SelectValue placeholder="Select Category" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">Select Category</SelectItem>
                            {catEnums.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                        </SelectContent>
                    </Select>
                    <button type="submit" disabled={!newDomain || !newCategory}
                        className="bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/80 disabled:opacity-50">Add</button>
                </form>

                {/* Table */}
                <div className="bg-card rounded-xl border border-border">
                    <div className="p-4 border-b border-border flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">{dcPagination.total} domain(s) total — Page {dcPagination.page} of {dcPagination.pages}</span>
                    </div>
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-border text-left text-sm text-muted-foreground">
                                <th className="px-4 py-3">#</th>
                                <th className="px-4 py-3">Domain</th>
                                <th className="px-4 py-3">Category</th>
                                <th className="px-4 py-3">Classified By</th>
                                <th className="px-4 py-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {domainCats.map((dc, idx) => {
                                const dcId = String(dc.id);
                                return (
                                <tr key={dcId} className="border-b border-border last:border-0 hover:bg-muted/30">
                                    <td className="px-4 py-3 text-xs text-muted-foreground font-mono">{(dcPagination.page - 1) * 50 + idx + 1}</td>
                                    <td className="px-4 py-3 font-mono text-sm">
                                        {editId === dcId ? (
                                            <input value={editDomain} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditDomain(e.target.value)}
                                                className="bg-input border border-border rounded px-2 py-1 text-foreground w-full" />
                                        ) : dc.domain}
                                    </td>
                                    <td className="px-4 py-3">
                                        {editId === dcId ? (
                                            <Select value={editCategory} onValueChange={(v: string) => setEditCategory(v)}>
                                                <SelectTrigger className="w-[160px] h-8">
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {catEnums.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                                                </SelectContent>
                                            </Select>
                                        ) : (
                                            <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${catColors[dc.category] || catColors['Other']}`}>
                                                {dc.category}
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-muted-foreground">{dc.classified_by || 'manual'}</td>
                                    <td className="px-4 py-3 text-sm">
                                        {editId === dcId ? (
                                            <>
                                                <button onClick={() => handleUpdate(dcId)} className="text-primary hover:underline mr-3">Save</button>
                                                <button onClick={() => setEditId(null)} className="text-muted-foreground hover:text-foreground">Cancel</button>
                                            </>
                                        ) : (
                                            <>
                                                <button onClick={() => { setEditId(dcId); setEditDomain(dc.domain); setEditCategory(dc.category); }}
                                                    className="text-primary hover:underline mr-3">Edit</button>
                                                <button onClick={() => handleDelete(dcId)} className="text-red-400 hover:text-red-300">Delete</button>
                                            </>
                                        )}
                                    </td>
                                </tr>
                                );
                            })}
                        </tbody>
                    </table>

                    {/* Pagination Controls */}
                    {dcPagination.pages > 1 && (
                        <div className="p-4 border-t border-border flex justify-center items-center gap-2">
                            <button
                                onClick={() => { setDcPage((p: number) => Math.max(1, p - 1)); setTimeout(loadData, 0); }}
                                disabled={dcPagination.page <= 1}
                                className="px-3 py-1.5 rounded border border-border text-sm hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                            >← Prev</button>
                            {(() => {
                                const pages = dcPagination.pages;
                                const current = dcPagination.page;
                                let range: Array<number | "..."> = [];
                                if (pages <= 7) {
                                    range = Array.from({ length: pages }, (_, i) => i + 1);
                                } else {
                                    range = [1];
                                    const start = Math.max(2, current - 1);
                                    const end = Math.min(pages - 1, current + 1);
                                    if (start > 2) range.push('...');
                                    for (let i = start; i <= end; i++) range.push(i);
                                    if (end < pages - 1) range.push('...');
                                    range.push(pages);
                                }
                                return range.map((p, i) => (
                                    p === '...' ? <span key={'e' + i} className="px-1 text-muted-foreground">…</span> : (
                                        <button key={p} onClick={() => { setDcPage(p as number); setTimeout(loadData, 0); }}
                                            className={`px-3 py-1.5 rounded border text-sm ${p === current ? 'bg-primary text-primary-foreground border-primary' : 'border-border hover:bg-muted'}`}
                                        >{p}</button>
                                    )
                                ));
                            })()}
                            <button
                                onClick={() => { setDcPage((p: number) => Math.min(dcPagination.pages, p + 1)); setTimeout(loadData, 0); }}
                                disabled={dcPagination.page >= dcPagination.pages}
                                className="px-3 py-1.5 rounded border border-border text-sm hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
                            >Next →</button>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // --- Sentiment Theme Dictionary UI ---
    function SentimentThemesSection() {
        interface ThemeForm {
            theme_name: string;
            industry: string;
            description: string;
            [key: string]: unknown;
        }
        const [newForm, setNewForm] = useState<ThemeForm>({ theme_name: '', industry: '', description: '' });
        const [editId, setEditId] = useState<string | null>(null);
        const [editForm, setEditForm] = useState<ThemeForm>({ theme_name: '', industry: '', description: '' });

        const industryColors: Record<string, string> = {
            'Consumer Electronics': 'bg-blue-500/20 text-blue-400',
            'Retail': 'bg-green-500/20 text-green-400',
            'SaaS': 'bg-purple-500/20 text-purple-400',
            'Automotive': 'bg-orange-500/20 text-orange-400',
            'Healthcare': 'bg-red-500/20 text-red-400',
            'Finance': 'bg-yellow-500/20 text-yellow-400',
        };

        async function handleAdd(e: React.FormEvent<HTMLFormElement>): Promise<void> {
            e.preventDefault();
            if (!newForm.theme_name) return;
            try {
                await createSentimentTheme({ ...newForm, created_by: 'manual' });
                toast.success('Theme added to dictionary');
                setNewForm({ theme_name: '', industry: '', description: '' });
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        async function handleUpdate(id: string): Promise<void> {
            try {
                await updateSentimentTheme(id, editForm);
                toast.success('Theme updated');
                setEditId(null);
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        async function handleDelete(id: string): Promise<void> {
            if (!await confirm('Delete this theme from the dictionary?', 'Delete Theme')) return;
            try {
                await deleteSentimentTheme(id);
                toast.success('Deleted');
                loadData();
            } catch (err) { toast.error((err as Error).message); }
        }

        return (
            <div className="space-y-4">
                {/* Filter Bar */}
                <div className="flex gap-3 flex-wrap">
                    <input
                        type="text" placeholder="Search theme name..."
                        value={stSearch}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setStSearch(e.target.value)}
                        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === 'Enter') { setStPage(1); setTimeout(loadData, 0); } }}
                        className="flex-1 min-w-[200px] bg-input border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground"
                    />
                    <Select value={stIndustryFilter || "__all__"} onValueChange={(v: string) => { setStIndustryFilter(v === "__all__" ? "" : v); setStPage(1); setTimeout(loadData, 0); }}>
                        <SelectTrigger className="w-[180px] h-9">
                            <SelectValue placeholder="All Industries" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">All Industries</SelectItem>
                            {stIndustries.map((ind) => <SelectItem key={ind} value={ind}>{ind}</SelectItem>)}
                        </SelectContent>
                    </Select>
                    <Select value={stCreatedByFilter || "__all__"} onValueChange={(v: string) => { setStCreatedByFilter(v === "__all__" ? "" : v); setStPage(1); setTimeout(loadData, 0); }}>
                        <SelectTrigger className="w-[160px] h-9">
                            <SelectValue placeholder="All Sources" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">All Sources</SelectItem>
                            <SelectItem value="gemini">AI Generated</SelectItem>
                            <SelectItem value="manual">Manual</SelectItem>
                        </SelectContent>
                    </Select>
                    <button
                        onClick={() => { setStPage(1); setTimeout(loadData, 0); }}
                        className="bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/80 transition-colors"
                    >Search</button>
                </div>

                {/* Add Form */}
                <form onSubmit={handleAdd} className="bg-card border border-border rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-foreground mb-3">Add Theme Manually</h3>
                    <div className="flex gap-3 flex-wrap">
                        <input type="text" placeholder="Theme name (e.g. Manual Setup Required)" value={newForm.theme_name}
                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewForm({ ...newForm, theme_name: e.target.value })} required
                            className="flex-1 min-w-[200px] bg-input border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground" />
                        <input type="text" placeholder="Industry (e.g. Consumer Electronics)" value={newForm.industry}
                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewForm({ ...newForm, industry: e.target.value })}
                            className="w-56 bg-input border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground" />
                        <input type="text" placeholder="Description (optional)" value={newForm.description}
                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewForm({ ...newForm, description: e.target.value })}
                            className="flex-1 min-w-[200px] bg-input border border-border rounded-lg px-3 py-2 text-foreground placeholder:text-muted-foreground" />
                        <button type="submit" disabled={!newForm.theme_name}
                            className="bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/80 disabled:opacity-50 transition-colors whitespace-nowrap"
                        >+ Add Theme</button>
                    </div>
                </form>

                {/* Table */}
                <div className="bg-card rounded-xl border border-border">
                    <div className="p-4 border-b border-border flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">{stPagination.total} theme(s) — Page {stPagination.page} of {stPagination.pages}</span>
                        <span className="text-xs text-muted-foreground/60">Themes shared across all clients. AI themes auto-normalized per Analyzer run.</span>
                    </div>
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-border text-left text-sm text-muted-foreground">
                                <th className="px-4 py-3">#</th>
                                <th className="px-4 py-3">Theme Name</th>
                                <th className="px-4 py-3">Industry</th>
                                <th className="px-4 py-3">Description</th>
                                <th className="px-4 py-3">Source</th>
                                <th className="px-4 py-3 text-right">Usage</th>
                                <th className="px-4 py-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sentimentThemes.map((theme, idx) => {
                                const themeId = String(theme.id);
                                return (
                                <tr key={themeId} className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors">
                                    <td className="px-4 py-3 text-xs text-muted-foreground font-mono">{(stPagination.page - 1) * 50 + idx + 1}</td>
                                    <td className="px-4 py-3 font-medium text-sm">
                                        {editId === themeId
                                            ? <input value={editForm.theme_name} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditForm({ ...editForm, theme_name: e.target.value })} className="bg-input border border-border rounded px-2 py-1 text-foreground w-full" />
                                            : theme.theme_name}
                                    </td>
                                    <td className="px-4 py-3">
                                        {editId === themeId
                                            ? <input value={editForm.industry || ''} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditForm({ ...editForm, industry: e.target.value })} className="bg-input border border-border rounded px-2 py-1 text-foreground w-full" />
                                            : theme.industry
                                                ? <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${industryColors[theme.industry] || 'bg-gray-500/20 text-gray-400'}`}>{theme.industry}</span>
                                                : <span className="text-muted-foreground/40 text-xs">—</span>}
                                    </td>
                                    <td className="px-4 py-3 text-sm text-muted-foreground max-w-[200px] truncate">
                                        {editId === themeId
                                            ? <input value={editForm.description || ''} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditForm({ ...editForm, description: e.target.value })} className="bg-input border border-border rounded px-2 py-1 text-foreground w-full" />
                                            : (theme.description || <span className="text-muted-foreground/40">—</span>)}
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${theme.created_by === 'manual' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-violet-500/20 text-violet-400'}`}>
                                            {theme.created_by === 'manual' ? '✏️ Manual' : '✨ AI'}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-right">
                                        <span className="text-sm font-mono text-primary">{theme.usage_count || 0}</span>
                                    </td>
                                    <td className="px-4 py-3 text-sm">
                                        {editId === themeId ? (
                                            <>
                                                <button onClick={() => handleUpdate(themeId)} className="text-primary hover:underline mr-3">Save</button>
                                                <button onClick={() => setEditId(null)} className="text-muted-foreground hover:text-foreground">Cancel</button>
                                            </>
                                        ) : (
                                            <>
                                                <button onClick={() => { setEditId(themeId); setEditForm({ theme_name: theme.theme_name, industry: theme.industry || '', description: theme.description || '' }); }} className="text-primary hover:underline mr-3">Edit</button>
                                                <button onClick={() => handleDelete(themeId)} className="text-red-400 hover:text-red-300">Delete</button>
                                            </>
                                        )}
                                    </td>
                                </tr>
                                );
                            })}
                            {sentimentThemes.length === 0 && (
                                <tr><td colSpan={7} className="px-4 py-12 text-center text-muted-foreground text-sm">
                                    No themes yet. Run the Analyzer to auto-populate, or add manually above.
                                </td></tr>
                            )}
                        </tbody>
                    </table>
                    {stPagination.pages > 1 && (
                        <div className="p-4 border-t border-border flex justify-center items-center gap-2">
                            <button onClick={() => { setStPage((p: number) => Math.max(1, p - 1)); setTimeout(loadData, 0); }} disabled={stPagination.page <= 1} className="px-3 py-1.5 rounded border border-border text-sm hover:bg-muted disabled:opacity-40">← Prev</button>
                            <span className="text-sm text-muted-foreground">Page {stPagination.page} / {stPagination.pages}</span>
                            <button onClick={() => { setStPage((p: number) => Math.min(stPagination.pages, p + 1)); setTimeout(loadData, 0); }} disabled={stPagination.page >= stPagination.pages} className="px-3 py-1.5 rounded border border-border text-sm hover:bg-muted disabled:opacity-40">Next →</button>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    return (

        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold text-foreground">Global Configurations</h1>
                <p className="text-muted-foreground mt-1">Manage system-wide settings, platforms, intents, and AI dictionaries</p>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-border overflow-x-auto">
                {([
                    { key: 'settings', label: 'Settings' },
                    { key: 'platforms', label: 'Platforms' },
                    { key: 'intents', label: 'Intents' },
                    { key: 'domainCategories', label: 'Domain Categories' },
                    { key: 'sentimentThemes', label: 'Sentiment Themes' },
                ] as { key: TabKey; label: string }[]).map((tab) => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={`px-6 py-3 font-medium whitespace-nowrap transition-colors border-b-2 ${
                            activeTab === tab.key
                                ? 'border-primary text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-accent'
                        }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Content */}
            {loading ? (
                <div className="flex items-center justify-center p-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                </div>
            ) : (
                <div className="mt-6">
                    {activeTab === 'settings' && <SettingsSection />}
                    {activeTab === 'platforms' && <PlatformsSection />}
                    {activeTab === 'intents' && <IntentsSection />}
                    {activeTab === 'domainCategories' && <DomainCategoriesSection />}
                    {activeTab === 'sentimentThemes' && <SentimentThemesSection />}
                </div>
            )}
        </div>
    );
}
