import { useState, useEffect, useCallback } from "react";
import type { components } from "../api/openapi";
import { useToast, useConfirm } from "../components/Toast";
import {
  getClients,
  getMemories,
  getMemoryUsers,
  createMemory,
  updateMemory,
  toggleMemoryShared,
  deleteMemory,
  bulkDeleteExpiredMemories,
} from "../api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Brain,
  Plus,
  Trash2,
  Share2,
  Search,
  Loader2,
  Save,
  X,
  Filter,
  Users,
  Clock,
} from "lucide-react";

type ClientOut = components["schemas"]["ClientOut"];
type MemoryOut = components["schemas"]["MemoryOut"];
type MemoryListOut = components["schemas"]["MemoryListOut"];
type MemoryUserRow = components["schemas"]["MemoryUserRow"];

interface MemoryTypeConfig {
  value: string;
  label: string;
  color: string;
}

interface MemoryFormData {
  user_identifier: string;
  memory_type: string;
  content: string;
  shared: boolean;
}

interface MemoryListParams {
  search?: string;
  memory_type?: string;
  user_identifier?: string;
  shared_only?: string;
  limit?: string;
  [key: string]: string | undefined;
}

const MEMORY_TYPES: MemoryTypeConfig[] = [
  { value: "preference", label: "Preference", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  { value: "fact", label: "Fact", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
  { value: "context", label: "Context", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  { value: "brand", label: "Brand", color: "bg-purple-500/10 text-purple-400 border-purple-500/20" },
];

interface MemoryTypeBadgeProps {
  type: string | null | undefined;
}

function MemoryTypeBadge({ type }: MemoryTypeBadgeProps) {
  const config = MEMORY_TYPES.find((t) => t.value === type) || MEMORY_TYPES[2];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-md border ${config.color}`}>
      {config.label}
    </span>
  );
}

export default function MemoriesPage() {
  const toast = useToast();
  const confirm = useConfirm();
  const [clients, setClients] = useState<ClientOut[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [memories, setMemories] = useState<MemoryOut[]>([]);
  const [memoryUsers, setMemoryUsers] = useState<MemoryUserRow[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);

  // Filters
  const [search, setSearch] = useState<string>("");
  const [filterType, setFilterType] = useState<string>("");
  const [filterUser, setFilterUser] = useState<string>("");
  const [filterShared, setFilterShared] = useState<boolean>(false);

  // Create/Edit modal
  const [showModal, setShowModal] = useState<boolean>(false);
  const [editingMemory, setEditingMemory] = useState<MemoryOut | null>(null);
  const [formData, setFormData] = useState<MemoryFormData>({
    user_identifier: "",
    memory_type: "fact",
    content: "",
    shared: false,
  });
  const [saving, setSaving] = useState<boolean>(false);

  useEffect(() => {
    getClients()
      .then((res) => setClients((res as ClientOut[]) || []))
      .catch(() => setClients([]));
  }, []);

  const loadMemories = useCallback(async (): Promise<void> => {
    if (!selectedClientId) return;
    setLoading(true);
    try {
      const params: MemoryListParams = {};
      if (search) params.search = search;
      if (filterType) params.memory_type = filterType;
      if (filterUser) params.user_identifier = filterUser;
      if (filterShared) params.shared_only = "true";
      params.limit = "100";

      const result = (await getMemories(selectedClientId, params)) as MemoryListOut;
      setMemories(result.data || []);
      setTotal(result.total || 0);
    } catch {
      toast.error("Failed to load memories");
    } finally {
      setLoading(false);
    }
  }, [selectedClientId, search, filterType, filterUser, filterShared]);

  const loadUsers = useCallback(async (): Promise<void> => {
    if (!selectedClientId) return;
    try {
      const users = (await getMemoryUsers(selectedClientId)) as MemoryUserRow[];
      setMemoryUsers(users || []);
    } catch {
      setMemoryUsers([]);
    }
  }, [selectedClientId]);

  useEffect(() => {
    if (selectedClientId) {
      loadMemories();
      loadUsers();
    }
  }, [selectedClientId, loadMemories, loadUsers]);

  function openCreate(): void {
    setEditingMemory(null);
    setFormData({ user_identifier: "", memory_type: "fact", content: "", shared: false });
    setShowModal(true);
  }

  function openEdit(mem: MemoryOut): void {
    setEditingMemory(mem);
    setFormData({
      user_identifier: mem.user_identifier ?? "",
      memory_type: mem.memory_type ?? "fact",
      content: mem.content ?? "",
      shared: !!mem.shared,
    });
    setShowModal(true);
  }

  async function handleSave(): Promise<void> {
    if (!formData.content.trim()) {
      toast.error("Content is required");
      return;
    }
    setSaving(true);
    try {
      if (editingMemory) {
        await updateMemory(editingMemory.id, {
          content: formData.content,
          memory_type: formData.memory_type,
          shared: formData.shared,
        });
        toast.success("Memory updated");
      } else {
        if (!formData.user_identifier.trim()) {
          toast.error("User identifier is required");
          setSaving(false);
          return;
        }
        await createMemory({
          client_id: selectedClientId,
          user_identifier: formData.user_identifier,
          memory_type: formData.memory_type,
          content: formData.content,
          shared: formData.shared,
        });
        toast.success("Memory created");
      }
      setShowModal(false);
      loadMemories();
    } catch (err) {
      toast.error("Save failed: " + (err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleShared(memoryId: string): Promise<void> {
    try {
      await toggleMemoryShared(memoryId);
      loadMemories();
    } catch (err) {
      toast.error("Toggle failed: " + (err as Error).message);
    }
  }

  async function handleDelete(memoryId: string): Promise<void> {
    if (!await confirm("Delete this memory?", "Delete Memory")) return;
    try {
      await deleteMemory(memoryId);
      toast.success("Memory deleted");
      loadMemories();
    } catch (err) {
      toast.error("Delete failed: " + (err as Error).message);
    }
  }

  async function handleBulkDeleteExpired(): Promise<void> {
    if (!await confirm("Delete all expired memories for this client?", "Clear Expired")) return;
    try {
      await bulkDeleteExpiredMemories(selectedClientId);
      toast.success("Expired memories deleted");
      loadMemories();
    } catch (err) {
      toast.error("Bulk delete failed: " + (err as Error).message);
    }
  }

  const selectedClient = clients.find((c) => c.id === selectedClientId);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-primary" />
            Agent Memories
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage cross-session memories for Agent conversations
          </p>
        </div>
      </div>

      {/* Client Selector */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-4">
            <Label className="text-sm font-medium whitespace-nowrap">Client Workspace</Label>
            <Select value={selectedClientId || "__all__"} onValueChange={(v: string) => {
                const val = v === "__all__" ? "" : v;
                setSelectedClientId(val);
                setMemories([]);
                setFilterUser("");
              }}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder="Select a client..." />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Select a client...</SelectItem>
                {clients.map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {selectedClientId && (
        <>
          {/* Stats Bar */}
          <div className="grid grid-cols-3 gap-4">
            <Card>
              <CardContent className="pt-4 pb-4 flex items-center gap-3">
                <Brain className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">{total}</p>
                  <p className="text-xs text-muted-foreground">Total Memories</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4 pb-4 flex items-center gap-3">
                <Users className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">{memoryUsers.length}</p>
                  <p className="text-xs text-muted-foreground">Users with Memories</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4 pb-4 flex items-center gap-3">
                <Share2 className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-2xl font-bold">{memories.filter((m) => m.shared).length}</p>
                  <p className="text-xs text-muted-foreground">Shared Memories</p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Filters + Actions */}
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-3 flex-wrap">
                <div className="relative flex-1 min-w-[200px]">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Search memory content..."
                    className="pl-9"
                    value={search}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                    onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && loadMemories()}
                  />
                </div>
                <Select value={filterType || "__all__"} onValueChange={(v: string) => setFilterType(v === "__all__" ? "" : v)}>
                  <SelectTrigger className="w-[160px] h-9">
                    <SelectValue placeholder="All Types" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__all__">All Types</SelectItem>
                    {MEMORY_TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={filterUser || "__all__"} onValueChange={(v: string) => setFilterUser(v === "__all__" ? "" : v)}>
                  <SelectTrigger className="w-[200px] h-9">
                    <SelectValue placeholder="All Users" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__all__">All Users</SelectItem>
                    {memoryUsers.map((u) => (
                      <SelectItem key={u.user_identifier ?? "_unknown"} value={u.user_identifier ?? "_unknown"}>
                        {u.user_identifier} ({u.memory_count})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant={filterShared ? "default" : "outline"}
                  size="sm"
                  onClick={() => setFilterShared(!filterShared)}
                >
                  <Share2 className="h-3.5 w-3.5 mr-1" />
                  Shared Only
                </Button>
                <Button size="sm" onClick={loadMemories}>
                  <Filter className="h-3.5 w-3.5 mr-1" />
                  Apply
                </Button>
                <div className="flex-1" />
                <Button variant="outline" size="sm" onClick={handleBulkDeleteExpired}>
                  <Clock className="h-3.5 w-3.5 mr-1" />
                  Clean Expired
                </Button>
                <Button size="sm" onClick={openCreate}>
                  <Plus className="h-3.5 w-3.5 mr-1" />
                  Add Memory
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Memory List */}
          <div className="space-y-3">
            {loading ? (
              <Card>
                <CardContent className="py-12 flex justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </CardContent>
              </Card>
            ) : memories.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground">
                  No memories found. Memories are automatically extracted from Agent conversations,
                  or you can create them manually.
                </CardContent>
              </Card>
            ) : (
              memories.map((mem) => (
                <Card key={mem.id} className="group hover:border-primary/30 transition-colors">
                  <CardContent className="pt-4 pb-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <MemoryTypeBadge type={mem.memory_type} />
                          {mem.shared && (
                            <Badge variant="outline" className="text-xs border-primary/30 text-primary">
                              <Share2 className="h-3 w-3 mr-1" />
                              Shared
                            </Badge>
                          )}
                          <span className="text-xs text-muted-foreground ml-auto">
                            {mem.user_identifier}
                          </span>
                        </div>
                        <p className="text-sm text-foreground leading-relaxed">{mem.content}</p>
                        <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                          <span>Created: {mem.created_at ? new Date(mem.created_at).toLocaleString() : "—"}</span>
                          {(mem.metadata as { importance?: string } | null)?.importance && (
                            <span>Importance: {(mem.metadata as { importance?: string }).importance}</span>
                          )}
                          {(mem.metadata as { source?: string } | null)?.source === "admin" && (
                            <Badge variant="outline" className="text-xs">Admin Created</Badge>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleToggleShared(mem.id)}
                          title={mem.shared ? "Unshare" : "Share"}
                        >
                          <Share2 className={`h-4 w-4 ${mem.shared ? "text-primary" : ""}`} />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => openEdit(mem)}>
                          <Save className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(mem.id)}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </>
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <Card className="w-full max-w-lg mx-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Brain className="h-5 w-5 text-primary" />
                {editingMemory ? "Edit Memory" : "Create Memory"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {!editingMemory && (
                <div className="space-y-2">
                  <Label>User Identifier</Label>
                  <Input
                    placeholder="e.g. google:abc123"
                    value={formData.user_identifier}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, user_identifier: e.target.value })}
                  />
                  <p className="text-xs text-muted-foreground">
                    Format: provider:id (e.g. google:abc123)
                  </p>
                </div>
              )}

              <div className="space-y-2">
                <Label>Memory Type</Label>
                <Select value={formData.memory_type} onValueChange={(v: string) => setFormData({ ...formData, memory_type: v })}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MEMORY_TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Content</Label>
                <Textarea
                  rows={4}
                  placeholder="What should the Agent remember about this user?"
                  value={formData.content}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setFormData({ ...formData, content: e.target.value })}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="shared"
                  checked={formData.shared}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, shared: e.target.checked })}
                  className="rounded border-border"
                />
                <Label htmlFor="shared" className="text-sm cursor-pointer">
                  Shared — visible to all users in this workspace
                </Label>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setShowModal(false)}>
                  <X className="h-4 w-4 mr-1" />
                  Cancel
                </Button>
                <Button onClick={handleSave} disabled={saving}>
                  {saving ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4 mr-1" />
                  )}
                  {editingMemory ? "Update" : "Create"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
