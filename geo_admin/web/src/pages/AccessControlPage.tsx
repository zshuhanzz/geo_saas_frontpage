import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { createPortal } from "react-dom";
import type { components } from "../api/openapi";
import {
    type AccessControlUser,
    type AdminAccessGrant,
    type ClientAccessGrant,
    type UserAuditEvent,
    getAccessControlUsers,
    getAdminAccessGrants,
    getClientAccessGrants,
    getClients,
    getUserAuditEvents,
    removeAdminAccessGrant,
    removeClientAccessGrant,
    updateAccessControlUser,
    updateAdminAccessGrant,
    updateClientAccessGrant,
    upsertAccessControlUser,
    upsertAdminAccessGrant,
    upsertClientAccessGrant,
} from "../api/client";
import { useConfirm, useToast } from "../components/Toast";
import { SearchableEntitySelect, type SearchableEntityOption } from "../components/access-control/SearchableEntitySelect";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Check, ChevronLeft, ChevronRight, KeyRound, Loader2, Plus, Search, ShieldCheck, ShieldOff, UserPlus, Users, X } from "lucide-react";

type ClientOut = components["schemas"]["ClientOut"];

type ClientRole = "admin" | "viewer" | "account_manager";
type AdminRole = "super_admin" | "viewer";

function StatusBadge({ active }: { active: boolean }) {
    return (
        <Badge variant={active ? "default" : "secondary"}>
            {active ? "Active" : "Inactive"}
        </Badge>
    );
}

function personOption(user: AccessControlUser): SearchableEntityOption {
    return {
        value: user.id,
        label: user.name || user.email,
        description: user.email,
        avatarUrl: user.avatar_url,
    };
}

function clientOption(client: ClientOut): SearchableEntityOption {
    return {
        value: client.id,
        label: client.name,
        description: client.id,
    };
}

function FilterCombobox({
    value,
    onChange,
    options,
    placeholder,
}: {
    value: string;
    onChange: (value: string) => void;
    options: SearchableEntityOption[];
    placeholder: string;
}) {
    const [open, setOpen] = useState(false);
    const anchorRef = useRef<HTMLDivElement | null>(null);
    const menuRef = useRef<HTMLDivElement | null>(null);
    const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
    const filtered = useMemo(() => {
        const q = value.trim().toLowerCase();
        if (!q) return options.slice(0, 20);
        return options
            .filter((option) => {
                return (
                    option.label.toLowerCase().includes(q) ||
                    (option.description || "").toLowerCase().includes(q)
                );
            })
            .slice(0, 20);
    }, [options, value]);

    function updateMenuPosition() {
        const anchor = anchorRef.current;
        if (!anchor) return;
        const rect = anchor.getBoundingClientRect();
        setMenuStyle({
            position: "fixed",
            top: rect.bottom + 8,
            left: rect.left,
            width: rect.width,
        });
    }

    useEffect(() => {
        if (!open) return;
        updateMenuPosition();

        function handlePointerDown(event: MouseEvent) {
            const target = event.target as Node;
            if (anchorRef.current?.contains(target) || menuRef.current?.contains(target)) {
                return;
            }
            setOpen(false);
        }

        window.addEventListener("resize", updateMenuPosition);
        window.addEventListener("scroll", updateMenuPosition, true);
        document.addEventListener("mousedown", handlePointerDown);
        return () => {
            window.removeEventListener("resize", updateMenuPosition);
            window.removeEventListener("scroll", updateMenuPosition, true);
            document.removeEventListener("mousedown", handlePointerDown);
        };
    }, [open]);

    return (
        <div ref={anchorRef} className="relative w-full sm:w-72">
            <Search className="absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
                value={value}
                onFocus={() => {
                    setOpen(true);
                    updateMenuPosition();
                }}
                onChange={(event) => {
                    onChange(event.target.value);
                    setOpen(true);
                    updateMenuPosition();
                }}
                placeholder={placeholder}
                className="h-10 pl-9 pr-8"
            />
            {value && (
                <button
                    type="button"
                    className="absolute right-2 top-1/2 z-10 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() => onChange("")}
                >
                    <X className="h-4 w-4" />
                </button>
            )}
            {open && createPortal(
                <Card
                    ref={menuRef}
                    style={menuStyle}
                    className="z-[1000] max-h-72 overflow-y-auto border bg-background shadow-xl"
                >
                    {filtered.length === 0 ? (
                        <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                            Type to search manually
                        </div>
                    ) : (
                        <div className="p-1">
                            {filtered.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent/60"
                                    onClick={() => {
                                        onChange(option.label);
                                        setOpen(false);
                                    }}
                                >
                                    <div className="min-w-0 flex-1">
                                        <div className="truncate font-medium">{option.label}</div>
                                        {option.description && (
                                            <div className="truncate text-xs text-muted-foreground">{option.description}</div>
                                        )}
                                    </div>
                                </button>
                            ))}
                        </div>
                    )}
                </Card>,
                document.body,
            )}
        </div>
    );
}

export default function AccessControlPage() {
    const toast = useToast();
    const confirm = useConfirm();
    const [loading, setLoading] = useState(true);
    const [tabRefreshing, setTabRefreshing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [activeTab, setActiveTab] = useState("users");
    const [search, setSearch] = useState("");
    const [activeOnly, setActiveOnly] = useState(false);
    const [users, setUsers] = useState<AccessControlUser[]>([]);
    const [clients, setClients] = useState<ClientOut[]>([]);
    const [clientAccess, setClientAccess] = useState<ClientAccessGrant[]>([]);
    const [adminAccess, setAdminAccess] = useState<AdminAccessGrant[]>([]);
    const [auditEvents, setAuditEvents] = useState<UserAuditEvent[]>([]);
    const [auditTotal, setAuditTotal] = useState(0);
    const [auditPage, setAuditPage] = useState(1);
    const [auditClientSearch, setAuditClientSearch] = useState("");
    const [auditUserSearch, setAuditUserSearch] = useState("");
    const [auditLoading, setAuditLoading] = useState(false);
    const [quotaDrafts, setQuotaDrafts] = useState<Record<string, string>>({});
    const auditPageSize = 25;

    const [userDialogOpen, setUserDialogOpen] = useState(false);
    const [editingUser, setEditingUser] = useState<AccessControlUser | null>(null);
    const [userForm, setUserForm] = useState({
        email: "",
        name: "",
        quota_limit: "",
        is_active: true,
    });

    const [clientGrantOpen, setClientGrantOpen] = useState(false);
    const [clientGrantForm, setClientGrantForm] = useState<{
        user_id: string;
        client_id: string;
        role: ClientRole;
        is_active: boolean;
    }>({ user_id: "", client_id: "", role: "admin", is_active: true });

    const [adminGrantOpen, setAdminGrantOpen] = useState(false);
    const [adminGrantForm, setAdminGrantForm] = useState<{
        user_id: string;
        role: AdminRole;
        support_all_clients: boolean;
        is_active: boolean;
    }>({ user_id: "", role: "viewer", support_all_clients: false, is_active: true });

    useEffect(() => {
        void loadAll();
        void loadAudit();
    }, []);

    useEffect(() => {
        setQuotaDrafts((previous) => {
            const next: Record<string, string> = {};
            for (const user of users) {
                next[user.id] = previous[user.id] ?? (user.quota_limit == null ? "" : String(user.quota_limit));
            }
            return next;
        });
    }, [users]);

    async function loadAll(nextSearch = search, nextActiveOnly = activeOnly) {
        setLoading(true);
        try {
            const [usersData, clientsData, clientAccessData, adminAccessData] = await Promise.all([
                getAccessControlUsers(nextSearch, nextActiveOnly),
                getClients(),
                getClientAccessGrants(nextSearch, "", nextActiveOnly),
                getAdminAccessGrants(nextSearch, nextActiveOnly),
            ]);
            setUsers(usersData);
            setClients(clientsData);
            setClientAccess(clientAccessData);
            setAdminAccess(adminAccessData);
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setLoading(false);
        }
    }

    const userOptions = useMemo(() => users.map(personOption), [users]);
    const clientOptions = useMemo(() => clients.map(clientOption), [clients]);

    async function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        await loadAll(search, activeOnly);
    }

    async function loadAudit(
        nextClientSearch = auditClientSearch,
        nextUserSearch = auditUserSearch,
        nextPage = auditPage,
    ) {
        setAuditLoading(true);
        try {
            const data = await getUserAuditEvents(nextClientSearch, nextUserSearch, nextPage, auditPageSize);
            setAuditEvents(data.items);
            setAuditTotal(data.total);
            setAuditPage(data.page);
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setAuditLoading(false);
        }
    }

    async function handleAuditSearchSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setAuditPage(1);
        await loadAudit(auditClientSearch, auditUserSearch, 1);
    }

    async function handleTabChange(value: string) {
        setActiveTab(value);
        setTabRefreshing(true);
        try {
            if (value === "user-audit") {
                await loadAudit(auditClientSearch, auditUserSearch, auditPage);
            } else {
                await loadAll(search, activeOnly);
            }
        } finally {
            setTabRefreshing(false);
        }
    }

    async function handleUpdateUserQuota(user: AccessControlUser) {
        const draft = quotaDrafts[user.id] ?? "";
        setSaving(true);
        try {
            await updateAccessControlUser(user.id, {
                email: user.email,
                name: user.name || null,
                quota_limit: draft.trim() ? Number(draft) : null,
                is_active: user.is_active,
            });
            await loadAll();
            toast.success("Quota limit updated");
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!userForm.email.trim()) return;
        setSaving(true);
        try {
            const payload = {
                email: userForm.email.trim(),
                name: userForm.name.trim() || null,
                quota_limit: userForm.quota_limit ? Number(userForm.quota_limit) : null,
                is_active: userForm.is_active,
            };
            if (editingUser) {
                await updateAccessControlUser(editingUser.id, payload);
            } else {
                await upsertAccessControlUser(payload);
            }
            setUserDialogOpen(false);
            resetUserDialog();
            await loadAll();
            toast.success("User saved");
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function handleCreateClientGrant(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!clientGrantForm.user_id || !clientGrantForm.client_id) return;
        setSaving(true);
        try {
            await upsertClientAccessGrant(clientGrantForm);
            setClientGrantOpen(false);
            setClientGrantForm({ user_id: "", client_id: "", role: "admin", is_active: true });
            await loadAll();
            toast.success("Client access saved");
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function handleCreateAdminGrant(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!adminGrantForm.user_id) return;
        setSaving(true);
        try {
            await upsertAdminAccessGrant(adminGrantForm);
            setAdminGrantOpen(false);
            setAdminGrantForm({ user_id: "", role: "viewer", support_all_clients: false, is_active: true });
            await loadAll();
            toast.success("Admin access saved");
        } catch (error) {
            toast.error((error as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function toggleClientGrant(grant: ClientAccessGrant, is_active: boolean) {
        try {
            await updateClientAccessGrant(grant.id, { is_active });
            await loadAll();
        } catch (error) {
            toast.error((error as Error).message);
        }
    }

    async function toggleAdminGrant(grant: AdminAccessGrant, changes: Partial<AdminAccessGrant>) {
        const previous = adminAccess;
        const optimisticGrant = { ...grant, ...changes };
        setAdminAccess((rows) => rows.map((row) => (row.id === grant.id ? optimisticGrant : row)));
        try {
            const updated = await updateAdminAccessGrant(grant.id, {
                role: changes.role,
                support_all_clients: changes.support_all_clients,
                is_active: changes.is_active,
            });
            setAdminAccess((rows) => rows.map((row) => (row.id === grant.id ? updated : row)));
        } catch (error) {
            setAdminAccess(previous);
            toast.error((error as Error).message);
        }
    }

    function openAddUserDialog() {
        setEditingUser(null);
        setUserForm({ email: "", name: "", quota_limit: "", is_active: true });
        setUserDialogOpen(true);
    }

    function openEditUserDialog(user: AccessControlUser) {
        setEditingUser(user);
        setUserForm({
            email: user.email,
            name: user.name || "",
            quota_limit: user.quota_limit == null ? "" : String(user.quota_limit),
            is_active: user.is_active,
        });
        setUserDialogOpen(true);
    }

    function resetUserDialog() {
        setEditingUser(null);
        setUserForm({ email: "", name: "", quota_limit: "", is_active: true });
    }

    async function removeClientGrantWithConfirm(grant: ClientAccessGrant) {
        if (!(await confirm(`Remove ${grant.email}'s access to ${grant.client_name}?`, "Remove Client Access"))) return;
        try {
            await removeClientAccessGrant(grant.id);
            await loadAll();
        } catch (error) {
            toast.error((error as Error).message);
        }
    }

    async function removeAdminGrantWithConfirm(grant: AdminAccessGrant) {
        if (!(await confirm(`Remove Admin access for ${grant.email}?`, "Remove Admin Access"))) return;
        try {
            await removeAdminAccessGrant(grant.id);
            await loadAll();
        } catch (error) {
            toast.error((error as Error).message);
        }
    }

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Access Control</h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                        Manage Google users, client-level SaaS access, and Admin system roles.
                    </p>
                </div>
                <form onSubmit={handleSearchSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <div className="relative w-full sm:w-80">
                        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                        <Input
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder="Search users, emails, or clients..."
                            className="h-10 pl-9"
                        />
                    </div>
                    <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                        <Switch
                            checked={activeOnly}
                            onCheckedChange={(checked) => {
                                setActiveOnly(checked);
                                void loadAll(search, checked);
                            }}
                        />
                        <span className="text-sm text-muted-foreground">Active only</span>
                    </div>
                    <Button type="submit" disabled={loading}>
                        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                        Search
                    </Button>
                </form>
            </div>

            <Tabs value={activeTab} onValueChange={(value) => void handleTabChange(value)} className="space-y-4">
                <TabsList>
                    <TabsTrigger value="users">Users</TabsTrigger>
                    <TabsTrigger value="client-access">Client Access</TabsTrigger>
                    <TabsTrigger value="admin-access">Super Admin</TabsTrigger>
                    <TabsTrigger value="user-audit">User Audit</TabsTrigger>
                </TabsList>
                {tabRefreshing && (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Refreshing tab data...
                    </div>
                )}

                <TabsContent value="users">
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0">
                            <CardTitle className="flex items-center gap-2">
                                <Users className="h-5 w-5" />
                                Registered Users
                            </CardTitle>
                            <Button onClick={openAddUserDialog}>
                                <UserPlus className="mr-2 h-4 w-4" />
                                Add User
                            </Button>
                        </CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>User</TableHead>
                                        <TableHead>Quota Limit</TableHead>
                                        <TableHead>Joined</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {users.map((user) => (
                                        <TableRow key={user.id}>
                                            <TableCell>
                                                <div className="flex items-center gap-3">
                                                    <div className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-full bg-muted text-sm font-semibold">
                                                        {user.avatar_url ? <img src={user.avatar_url} alt="" className="h-full w-full object-cover" /> : (user.name || user.email).slice(0, 1).toUpperCase()}
                                                    </div>
                                                    <div>
                                                        <div className="font-medium">{user.name || user.email}</div>
                                                        <div className="text-xs text-muted-foreground">{user.email}</div>
                                                    </div>
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex items-center gap-2">
                                                    <Input
                                                        type="number"
                                                        min={0}
                                                        value={quotaDrafts[user.id] ?? ""}
                                                        onChange={(event) => setQuotaDrafts((drafts) => ({ ...drafts, [user.id]: event.target.value }))}
                                                        placeholder="Not set"
                                                        className="h-8 w-28"
                                                    />
                                                    {(quotaDrafts[user.id] ?? "") !== (user.quota_limit == null ? "" : String(user.quota_limit)) && (
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            disabled={saving}
                                                            onClick={() => void handleUpdateUserQuota(user)}
                                                        >
                                                            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                                        </Button>
                                                    )}
                                                </div>
                                            </TableCell>
                                            <TableCell>{user.joined_at ? new Date(user.joined_at).toLocaleDateString() : "-"}</TableCell>
                                            <TableCell><StatusBadge active={user.is_active} /></TableCell>
                                            <TableCell className="text-right">
                                                <Button variant="outline" size="sm" onClick={() => openEditUserDialog(user)}>
                                                    Edit
                                                </Button>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="client-access">
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0">
                            <CardTitle className="flex items-center gap-2">
                                <KeyRound className="h-5 w-5" />
                                Client Access
                            </CardTitle>
                            <Button onClick={() => setClientGrantOpen(true)}>
                                <Plus className="mr-2 h-4 w-4" />
                                Grant Access
                            </Button>
                        </CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>User</TableHead>
                                        <TableHead>Client</TableHead>
                                        <TableHead>Role</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {clientAccess.map((grant) => (
                                        <TableRow key={grant.id}>
                                            <TableCell>
                                                <div className="font-medium">{grant.name || grant.email}</div>
                                                <div className="text-xs text-muted-foreground">{grant.email}</div>
                                            </TableCell>
                                            <TableCell>{grant.client_name}</TableCell>
                                            <TableCell>
                                                <Select
                                                    value={grant.role}
                                                    onValueChange={(role: ClientRole) => void updateClientAccessGrant(grant.id, { role }).then(() => loadAll()).catch((error) => toast.error((error as Error).message))}
                                                >
                                                    <SelectTrigger className="h-8 w-32">
                                                        <SelectValue />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        <SelectItem value="admin">Admin</SelectItem>
                                                        <SelectItem value="viewer">Viewer</SelectItem>
                                                        <SelectItem value="account_manager">Account Manager</SelectItem>
                                                    </SelectContent>
                                                </Select>
                                            </TableCell>
                                            <TableCell><StatusBadge active={grant.is_active} /></TableCell>
                                            <TableCell className="text-right">
                                                <div className="flex justify-end gap-2">
                                                    <Button variant="outline" size="sm" onClick={() => void toggleClientGrant(grant, !grant.is_active)}>
                                                        {grant.is_active ? <ShieldOff className="mr-2 h-4 w-4" /> : <ShieldCheck className="mr-2 h-4 w-4" />}
                                                        {grant.is_active ? "Disable" : "Enable"}
                                                    </Button>
                                                    <Button variant="ghost" size="sm" onClick={() => void removeClientGrantWithConfirm(grant)}>
                                                        Remove
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="admin-access">
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0">
                            <CardTitle className="flex items-center gap-2">
                                <ShieldCheck className="h-5 w-5" />
                                Super Admin
                            </CardTitle>
                            <Button onClick={() => setAdminGrantOpen(true)}>
                                <Plus className="mr-2 h-4 w-4" />
                                Grant Admin Role
                            </Button>
                        </CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>User</TableHead>
                                        <TableHead>Admin Role</TableHead>
                                        <TableHead>SaaS All Clients</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {adminAccess.map((grant) => (
                                        <TableRow key={grant.id}>
                                            <TableCell>
                                                <div className="font-medium">{grant.name || grant.email}</div>
                                                <div className="text-xs text-muted-foreground">{grant.email}</div>
                                            </TableCell>
                                            <TableCell>
                                                <Select
                                                    value={grant.role}
                                                    onValueChange={(role: AdminRole) => void toggleAdminGrant(grant, {
                                                        role,
                                                        support_all_clients: role === "super_admin" ? grant.support_all_clients : false,
                                                    })}
                                                >
                                                    <SelectTrigger className="h-8 w-40">
                                                        <SelectValue />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        <SelectItem value="super_admin">Super Admin</SelectItem>
                                                        <SelectItem value="viewer">Viewer</SelectItem>
                                                    </SelectContent>
                                                </Select>
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex items-center gap-2">
                                                    <Switch
                                                        checked={grant.support_all_clients}
                                                        disabled={grant.role !== "super_admin" || !grant.is_active}
                                                        onCheckedChange={(checked) => void toggleAdminGrant(grant, { support_all_clients: checked })}
                                                    />
                                                    <span className="text-sm text-muted-foreground">
                                                        {grant.support_all_clients ? "Enabled" : "Disabled"}
                                                    </span>
                                                </div>
                                            </TableCell>
                                            <TableCell><StatusBadge active={grant.is_active} /></TableCell>
                                            <TableCell className="text-right">
                                                <div className="flex justify-end gap-2">
                                                    <Button variant="outline" size="sm" onClick={() => void toggleAdminGrant(grant, { is_active: !grant.is_active })}>
                                                        {grant.is_active ? <ShieldOff className="mr-2 h-4 w-4" /> : <ShieldCheck className="mr-2 h-4 w-4" />}
                                                        {grant.is_active ? "Disable" : "Enable"}
                                                    </Button>
                                                    <Button variant="ghost" size="sm" onClick={() => void removeAdminGrantWithConfirm(grant)}>
                                                        Remove
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="user-audit">
                    <Card>
                        <CardHeader className="flex flex-col gap-4 space-y-0 lg:flex-row lg:items-center lg:justify-between">
                            <CardTitle className="flex items-center gap-2">
                                <ShieldCheck className="h-5 w-5" />
                                User Audit
                            </CardTitle>
                            <form onSubmit={handleAuditSearchSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-center">
                                <FilterCombobox
                                    value={auditClientSearch}
                                    onChange={setAuditClientSearch}
                                    options={clientOptions}
                                    placeholder="Search or select workspace..."
                                />
                                <FilterCombobox
                                    value={auditUserSearch}
                                    onChange={setAuditUserSearch}
                                    options={userOptions}
                                    placeholder="Search or select user..."
                                />
                                <Button type="submit">
                                    {auditLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                                    Search
                                </Button>
                            </form>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            {auditLoading && (
                                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                    Loading audit events...
                                </div>
                            )}
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Time</TableHead>
                                        <TableHead>User</TableHead>
                                        <TableHead>Workspace</TableHead>
                                        <TableHead>Type</TableHead>
                                        <TableHead>Action</TableHead>
                                        <TableHead>Route</TableHead>
                                        <TableHead>Status</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {auditEvents.map((event) => (
                                        <TableRow key={event.id}>
                                            <TableCell className="whitespace-nowrap text-sm">
                                                {event.created_at ? new Date(event.created_at).toLocaleString() : "-"}
                                            </TableCell>
                                            <TableCell>
                                                <div className="font-medium">{event.name || event.email}</div>
                                                <div className="text-xs text-muted-foreground">{event.email}</div>
                                            </TableCell>
                                            <TableCell>{event.client_name || "-"}</TableCell>
                                            <TableCell>
                                                <Badge variant={event.event_type === "page_view" ? "secondary" : "default"}>
                                                    {event.event_type === "page_view" ? "PageView" : "API Action"}
                                                </Badge>
                                            </TableCell>
                                            <TableCell>
                                                <div className="font-medium">{event.action_label || event.action_key}</div>
                                                <div className="text-xs text-muted-foreground">{event.action_key}</div>
                                            </TableCell>
                                            <TableCell className="max-w-[260px] truncate">{event.route || "-"}</TableCell>
                                            <TableCell>{event.status_code ?? "-"}</TableCell>
                                        </TableRow>
                                    ))}
                                    {auditEvents.length === 0 && (
                                        <TableRow>
                                            <TableCell colSpan={7} className="py-8 text-center text-sm text-muted-foreground">
                                                No audit events found.
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </TableBody>
                            </Table>
                            <div className="flex items-center justify-between">
                                <div className="text-sm text-muted-foreground">
                                    Page {auditPage} · {auditTotal} events
                                </div>
                                <div className="flex gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={auditPage <= 1}
                                        onClick={() => {
                                            const nextPage = Math.max(auditPage - 1, 1);
                                            setAuditPage(nextPage);
                                            void loadAudit(auditClientSearch, auditUserSearch, nextPage);
                                        }}
                                    >
                                        <ChevronLeft className="mr-2 h-4 w-4" />
                                        Previous
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={auditPage * auditPageSize >= auditTotal}
                                        onClick={() => {
                                            const nextPage = auditPage + 1;
                                            setAuditPage(nextPage);
                                            void loadAudit(auditClientSearch, auditUserSearch, nextPage);
                                        }}
                                    >
                                        Next
                                        <ChevronRight className="ml-2 h-4 w-4" />
                                    </Button>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>

            <Dialog open={userDialogOpen} onOpenChange={(open) => {
                setUserDialogOpen(open);
                if (!open) resetUserDialog();
            }}>
                <DialogContent>
                    <DialogHeader><DialogTitle>{editingUser ? "Edit User" : "Add User"}</DialogTitle></DialogHeader>
                    <form onSubmit={handleCreateUser} className="space-y-4">
                        <div className="space-y-2">
                            <Label>Email</Label>
                            <Input
                                value={userForm.email}
                                onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
                                placeholder="name@example.com"
                                disabled={Boolean(editingUser)}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Name</Label>
                            <Input value={userForm.name} onChange={(e) => setUserForm({ ...userForm, name: e.target.value })} placeholder="Display name" />
                        </div>
                        <div className="space-y-2">
                            <Label>Quota Limit</Label>
                            <Input type="number" min={0} value={userForm.quota_limit} onChange={(e) => setUserForm({ ...userForm, quota_limit: e.target.value })} placeholder="Optional" />
                        </div>
                        <div className="flex items-center justify-between rounded-md border p-3">
                            <Label>Active</Label>
                            <Switch checked={userForm.is_active} onCheckedChange={(checked) => setUserForm({ ...userForm, is_active: checked })} />
                        </div>
                        <DialogFooter>
                            <Button type="button" variant="outline" onClick={() => setUserDialogOpen(false)}>Cancel</Button>
                            <Button type="submit" disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save</Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>

            <Dialog open={clientGrantOpen} onOpenChange={setClientGrantOpen}>
                <DialogContent>
                    <DialogHeader><DialogTitle>Grant Client Access</DialogTitle></DialogHeader>
                    <form onSubmit={handleCreateClientGrant} className="space-y-4">
                        <div className="space-y-2">
                            <Label>User</Label>
                            <SearchableEntitySelect value={clientGrantForm.user_id} options={userOptions} onChange={(user_id) => setClientGrantForm({ ...clientGrantForm, user_id })} placeholder="Select user" searchPlaceholder="Search users..." />
                        </div>
                        <div className="space-y-2">
                            <Label>Client</Label>
                            <SearchableEntitySelect value={clientGrantForm.client_id} options={clientOptions} onChange={(client_id) => setClientGrantForm({ ...clientGrantForm, client_id })} placeholder="Select client" searchPlaceholder="Search clients..." />
                        </div>
                        <div className="space-y-2">
                            <Label>Role</Label>
                            <Select value={clientGrantForm.role} onValueChange={(role: ClientRole) => setClientGrantForm({ ...clientGrantForm, role })}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="admin">Admin</SelectItem>
                                    <SelectItem value="viewer">Viewer</SelectItem>
                                    <SelectItem value="account_manager">Account Manager</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <DialogFooter>
                            <Button type="button" variant="outline" onClick={() => setClientGrantOpen(false)}>Cancel</Button>
                            <Button type="submit" disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save</Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>

            <Dialog open={adminGrantOpen} onOpenChange={setAdminGrantOpen}>
                <DialogContent>
                    <DialogHeader><DialogTitle>Grant Admin Role</DialogTitle></DialogHeader>
                    <form onSubmit={handleCreateAdminGrant} className="space-y-4">
                        <div className="space-y-2">
                            <Label>User</Label>
                            <SearchableEntitySelect value={adminGrantForm.user_id} options={userOptions} onChange={(user_id) => setAdminGrantForm({ ...adminGrantForm, user_id })} placeholder="Select user" searchPlaceholder="Search users..." />
                        </div>
                        <div className="space-y-2">
                            <Label>Role</Label>
                            <Select value={adminGrantForm.role} onValueChange={(role: AdminRole) => setAdminGrantForm({ ...adminGrantForm, role, support_all_clients: role === "super_admin" ? adminGrantForm.support_all_clients : false })}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="super_admin">Super Admin</SelectItem>
                                    <SelectItem value="viewer">Viewer</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="flex items-center justify-between rounded-md border p-3">
                            <Label>SaaS All Clients</Label>
                            <Switch
                                checked={adminGrantForm.support_all_clients}
                                disabled={adminGrantForm.role !== "super_admin"}
                                onCheckedChange={(checked) => setAdminGrantForm({ ...adminGrantForm, support_all_clients: checked })}
                            />
                        </div>
                        <DialogFooter>
                            <Button type="button" variant="outline" onClick={() => setAdminGrantOpen(false)}>Cancel</Button>
                            <Button type="submit" disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save</Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>
        </div>
    );
}
