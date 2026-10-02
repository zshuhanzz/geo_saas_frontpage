import { useState, useEffect, useCallback } from "react";
import type { components } from "../../api/openapi";
import { useToast, useConfirm } from "../../components/Toast";
import { getClients, getContentAssets, createContentAsset, updateContentAsset, deleteContentAsset } from "../../api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import {
  FileBox, Plus, Pencil, Trash2, Loader2, Filter, ExternalLink,
  ChevronLeft, ChevronRight,
} from "lucide-react";

type ClientOut = components["schemas"]["ClientOut"];
type ContentAssetOut = components["schemas"]["ContentAssetOut"];
type ContentAssetListOut = components["schemas"]["ContentAssetListOut"];
type ContentAssetPagination = components["schemas"]["ContentAssetPagination"];

interface TrackingStatusConfig {
  value: string;
  label: string;
  color: string;
}

interface ContentAssetForm {
  client_id: string;
  content_task_id: string;
  published_url: string;
  published_platform: string;
  published_at: string;
  tracking_status: string;
  metadata: string;
}

interface ContentAssetListParams {
  page: string;
  limit: string;
  client_id?: string;
  tracking_status?: string;
  published_platform?: string;
  [key: string]: unknown;
}

const TRACKING_STATUSES: TrackingStatusConfig[] = [
  { value: "pending", label: "Pending", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  { value: "published", label: "Published", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
  { value: "tracking", label: "Tracking", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  { value: "completed", label: "Completed", color: "bg-purple-500/10 text-purple-400 border-purple-500/20" },
];

interface StatusBadgeProps {
  status: string | null | undefined;
}

function StatusBadge({ status }: StatusBadgeProps) {
  const config = TRACKING_STATUSES.find((s) => s.value === status) || TRACKING_STATUSES[0];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-md border ${config.color}`}>
      {config.label}
    </span>
  );
}

const EMPTY_FORM: ContentAssetForm = {
  client_id: "",
  content_task_id: "",
  published_url: "",
  published_platform: "",
  published_at: "",
  tracking_status: "pending",
  metadata: "{}",
};

export default function ContentAssetsPage() {
  const [assets, setAssets] = useState<ContentAssetOut[]>([]);
  const [clients, setClients] = useState<ClientOut[]>([]);
  const [pagination, setPagination] = useState<ContentAssetPagination>({ page: 1, limit: 50, total: 0, pages: 1 });
  const [loading, setLoading] = useState<boolean>(true);
  const [showDialog, setShowDialog] = useState<boolean>(false);
  const [editing, setEditing] = useState<ContentAssetOut | null>(null);
  const [form, setForm] = useState<ContentAssetForm>(EMPTY_FORM);
  const [saving, setSaving] = useState<boolean>(false);

  // Filters
  const [filterClient, setFilterClient] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [filterPlatform, setFilterPlatform] = useState<string>("");
  const [page, setPage] = useState<number>(1);

  const toast = useToast();
  const confirm = useConfirm();

  useEffect(() => {
    getClients()
      .then((res) => setClients((res as ClientOut[]) || []))
      .catch(() => setClients([]));
  }, []);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const params: ContentAssetListParams = { page: String(page), limit: "50" };
      if (filterClient) params.client_id = filterClient;
      if (filterStatus) params.tracking_status = filterStatus;
      if (filterPlatform) params.published_platform = filterPlatform;
      const result = (await getContentAssets(params)) as ContentAssetListOut;
      setAssets(result.data || []);
      setPagination(result.pagination || { page: 1, limit: 50, total: 0, pages: 1 });
    } catch {
      toast.error("Failed to load content assets");
    } finally {
      setLoading(false);
    }
  }, [filterClient, filterStatus, filterPlatform, page]);

  useEffect(() => { load(); }, [load]);

  function clientLabel(clientId: unknown): string {
    const id = String(clientId ?? "");
    const c = clients.find((x) => x.id === id);
    // ClientOut has no `brand_name` per schema; fall back gracefully if backend ever adds one.
    return c ? (c.name || (c as ClientOut & { brand_name?: string }).brand_name || id) : id;
  }

  function openCreate(): void {
    setEditing(null);
    setForm({ ...EMPTY_FORM, client_id: filterClient || "" });
    setShowDialog(true);
  }

  function openEdit(item: ContentAssetOut): void {
    setEditing(item);
    const meta = item.metadata;
    let metaStr = "{}";
    if (meta && typeof meta === "object") {
      metaStr = JSON.stringify(meta, null, 2);
    } else if (typeof meta === "string") {
      metaStr = meta;
    }
    setForm({
      client_id: String(item.client_id ?? ""),
      content_task_id: String(item.content_task_id ?? ""),
      published_url: item.published_url || "",
      published_platform: item.published_platform || "",
      published_at: item.published_at ? item.published_at.slice(0, 16) : "",
      tracking_status: item.tracking_status || "pending",
      metadata: metaStr,
    });
    setShowDialog(true);
  }

  async function handleSave(): Promise<void> {
    if (!form.client_id) {
      toast.error("Client is required");
      return;
    }
    let metadata: Record<string, unknown>;
    try {
      metadata = JSON.parse(form.metadata) as Record<string, unknown>;
    } catch {
      toast.error("Metadata must be valid JSON");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form, metadata };
      if (editing) {
        // Don't send client_id on update (immutable)
        const { client_id: _client_id, ...updates } = payload;
        await updateContentAsset(String(editing.id), updates);
        toast.success("Asset updated");
      } else {
        await createContentAsset(payload);
        toast.success("Asset created");
      }
      setShowDialog(false);
      load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(item: ContentAssetOut): Promise<void> {
    if (!await confirm("Delete this content asset?", "Delete Asset")) return;
    try {
      await deleteContentAsset(String(item.id));
      toast.success("Deleted");
      load();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }

  // Collect platforms for filter
  const platforms: string[] = [...new Set(assets.map((a) => a.published_platform).filter((p): p is string => !!p))];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Content Assets</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Track published content assets and their performance for the feedback loop.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> Add Asset
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center gap-4 flex-wrap">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <div className="w-[220px]">
              <Select value={filterClient || "__all__"} onValueChange={(v: string) => { setFilterClient(v === "__all__" ? "" : v); setPage(1); }}>
                <SelectTrigger>
                  <SelectValue placeholder="All clients" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All clients</SelectItem>
                  {clients.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name || (c as ClientOut & { brand_name?: string }).brand_name || c.id}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[180px]">
              <Select value={filterStatus || "__all__"} onValueChange={(v: string) => { setFilterStatus(v === "__all__" ? "" : v); setPage(1); }}>
                <SelectTrigger>
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All statuses</SelectItem>
                  {TRACKING_STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[180px]">
              <Select value={filterPlatform || "__all__"} onValueChange={(v: string) => { setFilterPlatform(v === "__all__" ? "" : v); setPage(1); }}>
                <SelectTrigger>
                  <SelectValue placeholder="All platforms" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All platforms</SelectItem>
                  {platforms.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg font-semibold flex items-center">
            <FileBox className="mr-2 h-5 w-5 text-primary" />
            Content Assets
            <Badge variant="secondary" className="ml-2">{pagination.total}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <div className="border rounded-lg overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Client</TableHead>
                      <TableHead>Platform</TableHead>
                      <TableHead>URL</TableHead>
                      <TableHead>Published At</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Task ID</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {assets.map((item) => (
                      <TableRow key={String(item.id)}>
                        <TableCell className="font-medium text-sm">{clientLabel(item.client_id)}</TableCell>
                        <TableCell>
                          {item.published_platform
                            ? <Badge variant="outline">{item.published_platform}</Badge>
                            : <span className="text-muted-foreground">-</span>}
                        </TableCell>
                        <TableCell className="max-w-[200px]">
                          {item.published_url ? (
                            <a
                              href={item.published_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary hover:underline text-sm flex items-center gap-1 truncate"
                            >
                              <ExternalLink className="h-3 w-3 shrink-0" />
                              <span className="truncate">{item.published_url}</span>
                            </a>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {item.published_at ? new Date(item.published_at).toLocaleString() : "-"}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={item.tracking_status} />
                        </TableCell>
                        <TableCell className="font-mono text-xs max-w-[120px] truncate">
                          {item.content_task_id ? String(item.content_task_id) : "-"}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm" onClick={() => openEdit(item)}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => handleDelete(item)} className="text-destructive">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                    {assets.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                          No content assets found.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>

              {/* Pagination */}
              {pagination.pages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <span className="text-sm text-muted-foreground">
                    Page {pagination.page} of {pagination.pages} ({pagination.total} total)
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage(page - 1)}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= pagination.pages}
                      onClick={() => setPage(page + 1)}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit Content Asset" : "Add Content Asset"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Client</Label>
              <Select
                value={form.client_id}
                onValueChange={(v: string) => setForm({ ...form, client_id: v })}
                disabled={!!editing}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select client" />
                </SelectTrigger>
                <SelectContent>
                  {clients.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name || (c as ClientOut & { brand_name?: string }).brand_name || c.id}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Content Task ID (optional)</Label>
              <Input
                placeholder="UUID of the generating task"
                value={form.content_task_id}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, content_task_id: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Published Platform</Label>
                <Input
                  placeholder="e.g. 官网FAQ, Reddit"
                  value={form.published_platform}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, published_platform: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>Tracking Status</Label>
                <Select value={form.tracking_status} onValueChange={(v: string) => setForm({ ...form, tracking_status: v })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TRACKING_STATUSES.map((s) => (
                      <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>Published URL</Label>
              <Input
                placeholder="https://..."
                value={form.published_url}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, published_url: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Published At</Label>
              <Input
                type="datetime-local"
                value={form.published_at}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, published_at: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Metadata (JSON)</Label>
              <Textarea
                className="font-mono text-xs"
                placeholder='{"key": "value"}'
                value={form.metadata}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setForm({ ...form, metadata: e.target.value })}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDialog(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !form.client_id}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {editing ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
