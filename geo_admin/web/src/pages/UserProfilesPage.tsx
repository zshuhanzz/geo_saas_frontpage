import { useState, useEffect } from "react";
import { getUserProfiles, updateUserProfile, getClients } from "../api/client";
import type { components } from "@/api/openapi";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UserCircle, Search, ChevronLeft, ChevronRight, Loader2, Save, CheckCircle2, Clock } from "lucide-react";

// Phase 7c (2026-04-25): replaced hand-written ``UserProfileRow`` /
// ``ClientRow`` / ``ProfilesResponse`` with the generated OpenAPI schemas.
type UserProfileRow = components["schemas"]["ProfileOut"];
type ClientRow = components["schemas"]["ClientOut"];
type ProfilesResponse = components["schemas"]["ProfileListOut"];

interface ProfileFilters {
    client_id: string;
    search: string;
    limit: number;
    offset: number;
    // Index signature so this can be passed straight to ``getUserProfiles``
    // which is typed as ``(params: Record<string, unknown>)``.
    [k: string]: unknown;
}

function formatDate(d?: string | null): string {
    if (!d) return "—";
    return new Date(d).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function UserProfilesPage() {
    const [profiles, setProfiles] = useState<UserProfileRow[]>([]);
    const [total, setTotal] = useState<number>(0);
    const [loading, setLoading] = useState<boolean>(true);
    const [clients, setClients] = useState<ClientRow[]>([]);
    const [filters, setFilters] = useState<ProfileFilters>({ client_id: "", search: "", limit: 20, offset: 0 });

    // Edit dialog
    const [editProfile, setEditProfile] = useState<UserProfileRow | null>(null);
    const [editMd, setEditMd] = useState<string>("");
    const [saving, setSaving] = useState<boolean>(false);

    useEffect(() => {
        getClients().then(setClients).catch(() => {});
    }, []);

    useEffect(() => {
        loadProfiles();
    }, [filters.client_id, filters.offset]);

    async function loadProfiles(): Promise<void> {
        setLoading(true);
        try {
            const res = await getUserProfiles(filters);
            setProfiles(res.data || []);
            setTotal(res.total || 0);
        } catch {
            setProfiles([]);
        } finally {
            setLoading(false);
        }
    }

    function openEdit(p: UserProfileRow) {
        setEditProfile(p);
        setEditMd(p.profile_md || "");
    }

    async function handleSave(): Promise<void> {
        if (!editProfile) return;
        setSaving(true);
        try {
            await updateUserProfile(editProfile.id, { profile_md: editMd });
            setEditProfile(null);
            loadProfiles();
        } catch {
            // silent
        } finally {
            setSaving(false);
        }
    }

    const page = Math.floor(filters.offset / filters.limit) + 1;
    const totalPages = Math.ceil(total / filters.limit);

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">User Profiles</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                    View and edit agent user profiles (Markdown documents).
                </p>
            </div>

            {/* Filters */}
            <div className="flex gap-3 items-center">
                <Select value={filters.client_id || "__all__"} onValueChange={(v) => setFilters({ ...filters, client_id: v === "__all__" ? "" : v, offset: 0 })}>
                    <SelectTrigger className="w-[200px] h-10">
                        <SelectValue placeholder="All Clients" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="__all__">All Clients</SelectItem>
                        {clients.map((c) => (
                            <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <div className="relative flex-1 max-w-xs">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                        placeholder="Search by user or content..."
                        className="pl-10"
                        value={filters.search}
                        onChange={(e) => setFilters({ ...filters, search: e.target.value })}
                        onKeyDown={(e) => e.key === "Enter" && loadProfiles()}
                    />
                </div>
                <Button variant="outline" onClick={loadProfiles}>Search</Button>
            </div>

            {/* Profiles Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {loading ? (
                    <div className="col-span-full flex h-32 items-center justify-center">
                        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                ) : profiles.length === 0 ? (
                    <div className="col-span-full p-8 text-center text-sm text-muted-foreground">No profiles found</div>
                ) : (
                    profiles.map((p) => (
                        <Card
                            key={p.id}
                            className="cursor-pointer hover:border-primary/30 transition-colors"
                            onClick={() => openEdit(p)}
                        >
                            <CardContent className="pt-5 pb-4">
                                <div className="flex items-start gap-3">
                                    <div className="p-2 rounded-lg bg-primary/10 shrink-0">
                                        <UserCircle className="h-5 w-5 text-primary" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="text-sm font-medium truncate">{p.user_identifier}</span>
                                            {p.onboarded ? (
                                                <Badge variant="default" className="text-[10px] h-4 gap-0.5">
                                                    <CheckCircle2 className="h-2.5 w-2.5" /> Onboarded
                                                </Badge>
                                            ) : (
                                                <Badge variant="secondary" className="text-[10px] h-4 gap-0.5">
                                                    <Clock className="h-2.5 w-2.5" /> New
                                                </Badge>
                                            )}
                                        </div>
                                        <p className="text-xs text-muted-foreground mb-1">{p.client_name || "—"}</p>
                                        <p className="text-xs text-foreground/70 line-clamp-3 whitespace-pre-wrap">
                                            {p.profile_md || "No profile content yet"}
                                        </p>
                                        <p className="text-[10px] text-muted-foreground/60 mt-2">
                                            Updated: {formatDate(p.updated_at)}
                                        </p>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    ))
                )}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-3">
                    <Button
                        variant="outline" size="sm"
                        disabled={page <= 1}
                        onClick={() => setFilters({ ...filters, offset: filters.offset - filters.limit })}
                    >
                        <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-sm text-muted-foreground">
                        Page {page} of {totalPages}
                    </span>
                    <Button
                        variant="outline" size="sm"
                        disabled={page >= totalPages}
                        onClick={() => setFilters({ ...filters, offset: filters.offset + filters.limit })}
                    >
                        <ChevronRight className="h-4 w-4" />
                    </Button>
                </div>
            )}

            {/* Edit Dialog */}
            <Dialog open={!!editProfile} onOpenChange={() => setEditProfile(null)}>
                <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
                    <DialogHeader>
                        <DialogTitle>
                            Edit Profile: {editProfile?.user_identifier}
                        </DialogTitle>
                    </DialogHeader>
                    <div className="flex-1 overflow-y-auto space-y-4 py-2">
                        <div className="flex items-center gap-3 text-sm text-muted-foreground">
                            <span>Client: {editProfile?.client_name}</span>
                            <Badge variant={editProfile?.onboarded ? "default" : "secondary"} className="text-xs">
                                {editProfile?.onboarded ? "Onboarded" : "Not Onboarded"}
                            </Badge>
                        </div>
                        <div className="space-y-2">
                            <Label>Profile (Markdown)</Label>
                            <Textarea
                                className="min-h-[300px] font-mono text-sm"
                                value={editMd}
                                onChange={(e) => setEditMd(e.target.value)}
                                placeholder="# User Profile&#10;&#10;## Language Preference&#10;..."
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditProfile(null)}>Cancel</Button>
                        <Button onClick={handleSave} disabled={saving}>
                            {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
                            Save
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
