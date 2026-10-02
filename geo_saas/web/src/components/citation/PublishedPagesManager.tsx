import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Download,
  Eye,
  FileUp,
  Loader2,
  Pencil,
  Plus,
  Power,
  Search,
  Trash2,
} from "lucide-react";

import { useSaaS } from "@/contexts/SaaSContext";
import {
  commitPublishedUrlImport,
  createPublishedUrl,
  deletePublishedUrl,
  disablePublishedUrl,
  downloadPublishedUrlCsvTemplate,
  listPublishedUrlChannels,
  listPublishedUrls,
  previewPublishedUrlImport,
  updatePublishedUrl,
  type PublishedUrlImportPreviewOut,
  type PublishedUrlPayload,
  type PublishedUrlRow,
} from "@/lib/api/insights";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { parseDateOnlyString, todayDateOnlyString, toDateOnlyString } from "@/lib/dateOnly";

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;
const REVIEW_STATUS_OPTIONS = ["not_submitted", "in_review", "approved", "changes_requested", "rejected"] as const;
const PUBLISH_STATUS_OPTIONS = ["draft", "scheduled", "published", "offline"] as const;

type PublishedPageFormState = {
  title: string;
  published_url: string;
  published_at: string;
  channel: string;
  review_status: string;
  publish_status: string;
  draft_doc_url: string;
  owner_name: string;
  notes: string;
  topics: string[];
  is_active: boolean;
};

function todayISO() {
  return todayDateOnlyString();
}

function parseISODate(value: string): Date | undefined {
  return parseDateOnlyString(value);
}

function toISODate(value: Date): string {
  return toDateOnlyString(value);
}

function normalizeUrlPreview(value: string): string {
  const text = value.trim();
  if (!text) return "";
  try {
    const url = new URL(/^https?:\/\//i.test(text) ? text : `https://${text}`);
    url.hash = "";
    url.hostname = url.hostname.toLowerCase().replace(/^www\./, "");
    Array.from(url.searchParams.keys()).forEach((key) => {
      if (/^utm_/i.test(key) || ["fbclid", "gclid", "yclid", "mc_cid", "mc_eid"].includes(key.toLowerCase())) {
        url.searchParams.delete(key);
      }
    });
    let normalized = url.toString();
    normalized = normalized.replace(/\/$/, "");
    return normalized;
  } catch {
    return "";
  }
}

function emptyForm(): PublishedPageFormState {
  return {
    title: "",
    published_url: "",
    published_at: todayISO(),
    channel: "",
    review_status: "approved",
    publish_status: "published",
    draft_doc_url: "",
    owner_name: "",
    notes: "",
    topics: [],
    is_active: true,
  };
}

function formFromRow(row: PublishedUrlRow): PublishedPageFormState {
  return {
    title: row.title || "",
    published_url: row.published_url || "",
    published_at: row.published_at || todayISO(),
    channel: row.channel || "",
    review_status: row.review_status || "approved",
    publish_status: row.publish_status || "published",
    draft_doc_url: row.draft_doc_url || "",
    owner_name: row.owner_name || "",
    notes: row.notes || "",
    topics: (row.topics || []).map((topic) => topic.id),
    is_active: row.is_active,
  };
}

function toPayload(clientId: string, form: PublishedPageFormState): PublishedUrlPayload {
  return {
    client_id: clientId,
    title: form.title.trim(),
    published_url: form.published_url.trim(),
    published_at: form.published_at,
    channel: form.channel.trim(),
    topics: form.topics,
    review_status: form.review_status.trim() || null,
    publish_status: form.publish_status.trim() || null,
    draft_doc_url: form.draft_doc_url.trim() || null,
    owner_name: form.owner_name.trim() || null,
    notes: form.notes.trim() || null,
    is_active: form.is_active,
  };
}

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function PublishedPagesManager() {
  const { t } = useTranslation("insights");
  const { clients, clientId } = useSaaS();
  const confirm = useConfirm();
  const activeClient = clients.find((client) => client.id === clientId);
  const topics: { id: string; topic_name: string }[] = (activeClient as any)?.topics || [];

  const [items, setItems] = useState<PublishedUrlRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [channelFilter, setChannelFilter] = useState("all");
  const [topicFilter, setTopicFilter] = useState("all");
  const [channels, setChannels] = useState<string[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRow, setEditingRow] = useState<PublishedUrlRow | null>(null);
  const [detailRow, setDetailRow] = useState<PublishedUrlRow | null>(null);
  const [form, setForm] = useState<PublishedPageFormState>(() => emptyForm());
  const [saving, setSaving] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importPreview, setImportPreview] = useState<PublishedUrlImportPreviewOut | null>(null);
  const [importCsvText, setImportCsvText] = useState("");
  const [importing, setImporting] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const requestSeq = useRef(0);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const normalizedUrlPreview = useMemo(() => normalizeUrlPreview(form.published_url), [form.published_url]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    setPage(0);
  }, [debouncedSearch, statusFilter, channelFilter, topicFilter, clientId]);

  useEffect(() => {
    if (!clientId) return;
    const controller = new AbortController();
    const requestId = ++requestSeq.current;
    setLoading(true);
    const params: Record<string, string> = {
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    };
    if (debouncedSearch.trim()) params.search = debouncedSearch.trim();
    if (statusFilter !== "all") params.publish_status = statusFilter;
    if (channelFilter !== "all") params.channel = channelFilter;
    if (topicFilter !== "all") params.topic_id = topicFilter;
    listPublishedUrls(clientId, params, { signal: controller.signal })
      .then((res) => {
        if (requestId !== requestSeq.current) return;
        setItems(res.items || []);
        setTotal(res.total || 0);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (requestId === requestSeq.current) {
          setItems([]);
          setTotal(0);
          toast.error(t("publishedPages.toasts.loadFailed", { message: err?.message || String(err) }));
        }
      })
      .finally(() => {
        if (requestId === requestSeq.current) setLoading(false);
      });
    return () => controller.abort();
  }, [clientId, debouncedSearch, statusFilter, channelFilter, topicFilter, page, reloadNonce, t]);

  useEffect(() => {
    if (!clientId) return;
    const controller = new AbortController();
    listPublishedUrlChannels(clientId, { signal: controller.signal })
      .then((res) => setChannels(res || []))
      .catch(() => setChannels([]));
    return () => controller.abort();
  }, [clientId, reloadNonce]);

  const reload = () => {
    setReloadNonce((prev) => prev + 1);
  };

  const openCreate = () => {
    setEditingRow(null);
    setForm(emptyForm());
    setFormOpen(true);
  };

  const openEdit = (row: PublishedUrlRow) => {
    setEditingRow(row);
    setForm(formFromRow(row));
    setFormOpen(true);
  };

  const openDetail = (row: PublishedUrlRow) => {
    setDetailRow(row);
  };

  const handleSave = async () => {
    if (!clientId) return;
    if (!form.title.trim() || !form.published_url.trim() || !form.published_at || !form.channel.trim() || !form.publish_status.trim()) {
      toast.error(t("publishedPages.toasts.requiredFields"));
      return;
    }
    setSaving(true);
    try {
      const payload = toPayload(clientId, form);
      if (editingRow) {
        await updatePublishedUrl(editingRow.id, payload);
      } else {
        await createPublishedUrl(payload);
      }
      toast.success(t("publishedPages.toasts.saved"));
      setFormOpen(false);
      reload();
    } catch (err: any) {
      toast.error(t("publishedPages.toasts.saveFailed", { message: err?.message || String(err) }));
    } finally {
      setSaving(false);
    }
  };

  const handleDisable = async (row: PublishedUrlRow) => {
    if (!clientId) return;
    const ok = await confirm(
      t("publishedPages.confirm.disableMessage", { title: row.title }),
      t("publishedPages.confirm.disableTitle"),
    );
    if (!ok) return;
    await disablePublishedUrl(clientId, row.id);
    toast.success(t("publishedPages.toasts.disabled"));
    reload();
  };

  const handleDelete = async (row: PublishedUrlRow) => {
    if (!clientId) return;
    const ok = await confirm(
      t("publishedPages.confirm.deleteMessage", { title: row.title }),
      t("publishedPages.confirm.deleteTitle"),
    );
    if (!ok) return;
    await deletePublishedUrl(clientId, row.id);
    toast.success(t("publishedPages.toasts.deleted"));
    reload();
  };

  const handleDownloadTemplate = async () => {
    try {
      const csv = await downloadPublishedUrlCsvTemplate();
      downloadText("published_pages_template.csv", csv);
    } catch (err: any) {
      toast.error(t("publishedPages.toasts.templateFailed", { message: err?.message || String(err) }));
    }
  };

  const handleFileSelected = async (file: File | undefined) => {
    if (!clientId || !file) return;
    const text = await file.text();
    setImportCsvText(text);
    setImporting(true);
    try {
      const preview = await previewPublishedUrlImport(clientId, text);
      setImportPreview(preview);
      setImportOpen(true);
    } catch (err: any) {
      toast.error(t("publishedPages.toasts.previewFailed", { message: err?.message || String(err) }));
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleCommitImport = async () => {
    if (!clientId || !importCsvText) return;
    setImporting(true);
    try {
      const result = await commitPublishedUrlImport(clientId, importCsvText);
      toast.success(
        t("publishedPages.toasts.imported", {
          create: result.create_count,
          update: result.update_count,
        }),
      );
      setImportOpen(false);
      setImportPreview(null);
      setImportCsvText("");
      reload();
    } catch (err: any) {
      toast.error(t("publishedPages.toasts.importFailed", { message: err?.message || String(err) }));
    } finally {
      setImporting(false);
    }
  };

  const toggleTopic = (topicId: string) => {
    setForm((prev) => ({
      ...prev,
      topics: prev.topics.includes(topicId)
        ? prev.topics.filter((id) => id !== topicId)
        : [...prev.topics, topicId],
    }));
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">{t("publishedPages.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("publishedPages.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={handleDownloadTemplate}>
            <Download className="mr-2 h-4 w-4" />
            {t("publishedPages.actions.downloadTemplate")}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(event) => void handleFileSelected(event.target.files?.[0])}
          />
          <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()} disabled={importing}>
            {importing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileUp className="mr-2 h-4 w-4" />}
            {t("publishedPages.actions.importCsv")}
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" />
            {t("publishedPages.actions.new")}
          </Button>
        </div>
      </div>

      <div className="rounded-xl border bg-card/50 p-4">
        <div className="grid gap-3 md:grid-cols-[minmax(220px,1fr)_160px_180px_180px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("publishedPages.filters.search")}
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger>
              <SelectValue placeholder={t("publishedPages.filters.status")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("publishedPages.filters.allStatuses")}</SelectItem>
              {PUBLISH_STATUS_OPTIONS.map((status) => (
                <SelectItem key={status} value={status}>
                  {t(`publishedPages.publishStatuses.${status}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={channelFilter} onValueChange={setChannelFilter}>
            <SelectTrigger>
              <SelectValue placeholder={t("publishedPages.filters.channel")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("publishedPages.filters.allChannels")}</SelectItem>
              {channels.map((channel) => (
                <SelectItem key={channel} value={channel}>{channel}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={topicFilter} onValueChange={setTopicFilter}>
            <SelectTrigger>
              <SelectValue placeholder={t("publishedPages.filters.topic")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("publishedPages.filters.allTopics")}</SelectItem>
              {topics.map((topic) => (
                <SelectItem key={topic.id} value={topic.id}>{topic.topic_name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="isolate overflow-hidden rounded-xl border">
        <div className="overflow-x-auto">
        <Table className="min-w-[1180px]">
          <TableHeader>
            <TableRow>
              <TableHead className="sticky left-0 z-30 w-[420px] min-w-[420px] bg-card shadow-[1px_0_0_hsl(var(--border)),8px_0_18px_hsl(var(--background)/0.75)]">
                {t("publishedPages.table.page")}
              </TableHead>
              <TableHead className="w-[140px] min-w-[140px]">{t("publishedPages.table.publishedAt")}</TableHead>
              <TableHead className="w-[260px] min-w-[260px]">{t("publishedPages.table.topics")}</TableHead>
              <TableHead className="w-[180px] min-w-[180px]">{t("publishedPages.table.channel")}</TableHead>
              <TableHead className="w-[140px] min-w-[140px]">{t("publishedPages.table.status")}</TableHead>
              <TableHead className="sticky right-0 z-30 w-[140px] min-w-[140px] bg-card text-right shadow-[-1px_0_0_hsl(var(--border)),-8px_0_18px_hsl(var(--background)/0.75)]">
                {t("publishedPages.table.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-sm text-muted-foreground">
                  {t("publishedPages.empty")}
                </TableCell>
              </TableRow>
            ) : (
              items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="sticky left-0 z-20 w-[420px] min-w-[420px] bg-card shadow-[1px_0_0_hsl(var(--border)),8px_0_18px_hsl(var(--background)/0.75)]">
                    <div className="max-w-[380px]">
                      <div className="font-medium text-foreground">{item.title}</div>
                      <a
                        href={item.published_url}
                        target="_blank"
                        rel="noreferrer"
                        className="line-clamp-1 text-xs text-primary hover:underline"
                      >
                        {item.normalized_url}
                      </a>
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{item.published_at}</TableCell>
                  <TableCell>
                    <div className="flex max-w-[260px] flex-wrap gap-1">
                      {item.topics.length ? item.topics.map((topic) => (
                        <Badge key={topic.id} variant="secondary" className="text-[11px]">{topic.topic_name}</Badge>
                      )) : <span className="text-xs text-muted-foreground">—</span>}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm">{item.channel}</TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <Badge variant={item.is_active && item.publish_status === "published" ? "default" : "secondary"}>
                        {t(`publishedPages.publishStatuses.${item.publish_status}`, { defaultValue: item.publish_status })}
                      </Badge>
                      <div className="text-[11px] text-muted-foreground">
                        {t(`publishedPages.reviewStatuses.${item.review_status}`, { defaultValue: item.review_status })}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="sticky right-0 z-20 w-[140px] min-w-[140px] bg-card text-right shadow-[-1px_0_0_hsl(var(--border)),-8px_0_18px_hsl(var(--background)/0.75)]">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon" onClick={() => openDetail(item)} title={t("publishedPages.actions.detail")}>
                        <Eye className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => openEdit(item)} title={t("publishedPages.actions.edit")}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => void handleDisable(item)} title={t("publishedPages.actions.disable")}>
                        <Power className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => void handleDelete(item)} title={t("publishedPages.actions.delete")}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>{t("publishedPages.pagination.summary", { total, page: page + 1, pages: pageCount })}</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((prev) => Math.max(0, prev - 1))}>
            {t("publishedPages.pagination.previous")}
          </Button>
          <Button variant="outline" size="sm" disabled={page + 1 >= pageCount} onClick={() => setPage((prev) => prev + 1)}>
            {t("publishedPages.pagination.next")}
          </Button>
        </div>
      </div>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {editingRow ? t("publishedPages.form.editTitle") : t("publishedPages.form.createTitle")}
            </DialogTitle>
            <DialogDescription>{t("publishedPages.form.description")}</DialogDescription>
          </DialogHeader>
          <div className="grid max-h-[68vh] gap-4 overflow-y-auto pr-1 md:grid-cols-2">
            <label className="space-y-1.5 md:col-span-2">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.title")}</span>
              <Input value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} />
            </label>
            <label className="space-y-1.5 md:col-span-2">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.url")}</span>
              <Input value={form.published_url} onChange={(event) => setForm((prev) => ({ ...prev, published_url: event.target.value }))} />
            </label>
            <div className="space-y-1.5 md:col-span-2">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.normalizedUrlPreview")}</span>
              <div className="min-h-10 rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                {normalizedUrlPreview || t("publishedPages.form.fields.normalizedUrlEmpty")}
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.publishedAt")}</span>
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="outline" className="h-10 w-full justify-start gap-2">
                    <CalendarDays className="h-4 w-4 text-muted-foreground" />
                    <span>{form.published_at || t("publishedPages.form.fields.selectDate")}</span>
                    <ChevronDown className="ml-auto h-3.5 w-3.5 text-muted-foreground" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={parseISODate(form.published_at)}
                    onSelect={(value) => {
                      if (value) {
                        setForm((prev) => ({ ...prev, published_at: toISODate(value) }));
                      }
                    }}
                    disabled={{ after: new Date() }}
                  />
                </PopoverContent>
              </Popover>
            </div>
            <label className="space-y-1.5">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.channel")}</span>
              <Input value={form.channel} onChange={(event) => setForm((prev) => ({ ...prev, channel: event.target.value }))} />
            </label>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.reviewStatus")}</span>
              <Select value={form.review_status} onValueChange={(value) => setForm((prev) => ({ ...prev, review_status: value }))}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {REVIEW_STATUS_OPTIONS.map((status) => (
                    <SelectItem key={status} value={status}>
                      {t(`publishedPages.reviewStatuses.${status}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.publishStatus")}</span>
              <Select value={form.publish_status} onValueChange={(value) => setForm((prev) => ({ ...prev, publish_status: value }))}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PUBLISH_STATUS_OPTIONS.map((status) => (
                    <SelectItem key={status} value={status}>
                      {t(`publishedPages.publishStatuses.${status}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <label className="space-y-1.5">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.owner")}</span>
              <Input value={form.owner_name} onChange={(event) => setForm((prev) => ({ ...prev, owner_name: event.target.value }))} />
            </label>
            <label className="space-y-1.5 md:col-span-2">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.draftDocUrl")}</span>
              <Input value={form.draft_doc_url} onChange={(event) => setForm((prev) => ({ ...prev, draft_doc_url: event.target.value }))} />
            </label>
            <div className="space-y-2 md:col-span-2">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.topics")}</span>
              <div className="grid gap-2 rounded-lg border p-3 md:grid-cols-2">
                {topics.map((topic) => (
                  <button
                    key={topic.id}
                    type="button"
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                    onClick={() => toggleTopic(topic.id)}
                  >
                    <Checkbox checked={form.topics.includes(topic.id)} className="pointer-events-none" />
                    <span>{topic.topic_name}</span>
                  </button>
                ))}
              </div>
            </div>
            <label className="space-y-1.5 md:col-span-2">
              <span className="text-sm font-medium">{t("publishedPages.form.fields.notes")}</span>
              <Textarea value={form.notes} onChange={(event) => setForm((prev) => ({ ...prev, notes: event.target.value }))} />
            </label>
            <button
              type="button"
              className="flex items-center gap-2 text-sm md:col-span-2"
              onClick={() => setForm((prev) => ({ ...prev, is_active: !prev.is_active }))}
            >
              <Checkbox checked={form.is_active} className="pointer-events-none" />
              {t("publishedPages.form.fields.active")}
            </button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)}>{t("publishedPages.actions.cancel")}</Button>
            <Button onClick={() => void handleSave()} disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
              {t("publishedPages.actions.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Sheet open={Boolean(detailRow)} onOpenChange={(open) => !open && setDetailRow(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>{detailRow?.title || t("publishedPages.detail.title")}</SheetTitle>
            <SheetDescription>{detailRow?.normalized_url || t("publishedPages.detail.description")}</SheetDescription>
          </SheetHeader>
          {detailRow && (
            <div className="mt-6 space-y-5">
              <div className="grid gap-3 rounded-lg border p-4 text-sm md:grid-cols-2">
                <DetailItem label={t("publishedPages.form.fields.url")} value={detailRow.published_url} href={detailRow.published_url} />
                <DetailItem label={t("publishedPages.form.fields.normalizedUrlPreview")} value={detailRow.normalized_url} />
                <DetailItem label={t("publishedPages.form.fields.publishedAt")} value={detailRow.published_at} />
                <DetailItem label={t("publishedPages.form.fields.channel")} value={detailRow.channel} />
                <DetailItem
                  label={t("publishedPages.form.fields.publishStatus")}
                  value={t(`publishedPages.publishStatuses.${detailRow.publish_status}`, { defaultValue: detailRow.publish_status })}
                />
                <DetailItem
                  label={t("publishedPages.form.fields.reviewStatus")}
                  value={t(`publishedPages.reviewStatuses.${detailRow.review_status}`, { defaultValue: detailRow.review_status })}
                />
                <DetailItem label={t("publishedPages.form.fields.owner")} value={detailRow.owner_name || "—"} />
                <DetailItem label={t("publishedPages.form.fields.draftDocUrl")} value={detailRow.draft_doc_url || "—"} href={detailRow.draft_doc_url || undefined} />
              </div>
              <div className="space-y-2">
                <div className="text-sm font-medium">{t("publishedPages.form.fields.topics")}</div>
                <div className="flex flex-wrap gap-1">
                  {detailRow.topics.length ? detailRow.topics.map((topic) => (
                    <Badge key={topic.id} variant="secondary">{topic.topic_name}</Badge>
                  )) : <span className="text-sm text-muted-foreground">—</span>}
                </div>
              </div>
              <div className="space-y-2">
                <div className="text-sm font-medium">{t("publishedPages.form.fields.notes")}</div>
                <div className="min-h-16 rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
                  {detailRow.notes || "—"}
                </div>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>

      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>{t("publishedPages.import.title")}</DialogTitle>
            <DialogDescription>{t("publishedPages.import.description")}</DialogDescription>
          </DialogHeader>
          {importPreview && (
            <div className="space-y-3">
              <div className="grid gap-2 md:grid-cols-4">
                <div className="rounded-lg border p-3">
                  <div className="text-xs text-muted-foreground">{t("publishedPages.import.total")}</div>
                  <div className="text-2xl font-semibold">{importPreview.total_rows}</div>
                </div>
                <div className="rounded-lg border p-3">
                  <div className="text-xs text-muted-foreground">{t("publishedPages.import.create")}</div>
                  <div className="text-2xl font-semibold">{importPreview.create_count}</div>
                </div>
                <div className="rounded-lg border p-3">
                  <div className="text-xs text-muted-foreground">{t("publishedPages.import.update")}</div>
                  <div className="text-2xl font-semibold">{importPreview.update_count}</div>
                </div>
                <div className="rounded-lg border p-3">
                  <div className="text-xs text-muted-foreground">{t("publishedPages.import.invalid")}</div>
                  <div className="text-2xl font-semibold">{importPreview.invalid_count}</div>
                </div>
              </div>
              <div className="max-h-[360px] overflow-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("publishedPages.import.row")}</TableHead>
                      <TableHead>{t("publishedPages.table.page")}</TableHead>
                      <TableHead>{t("publishedPages.import.action")}</TableHead>
                      <TableHead>{t("publishedPages.import.errors")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {importPreview.rows.map((row) => (
                      <TableRow key={row.row_number}>
                        <TableCell>{row.row_number}</TableCell>
                        <TableCell>
                          <div className="font-medium">{row.title || "—"}</div>
                          <div className="text-xs text-muted-foreground">{row.normalized_url || row.published_url || "—"}</div>
                        </TableCell>
                        <TableCell><Badge variant={row.action === "invalid" ? "destructive" : "secondary"}>{row.action}</Badge></TableCell>
                        <TableCell className="text-xs text-muted-foreground">{row.errors.join("; ") || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setImportOpen(false)}>{t("publishedPages.actions.cancel")}</Button>
            <Button onClick={() => void handleCommitImport()} disabled={importing || !importPreview || importPreview.invalid_count > 0}>
              {importing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
              {t("publishedPages.import.commit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DetailItem({ label, value, href }: { label: string; value: string; href?: string }) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted-foreground">{label}</div>
      {href && value !== "—" ? (
        <a href={href} target="_blank" rel="noreferrer" className="break-all text-primary hover:underline">
          {value}
        </a>
      ) : (
        <div className="break-all text-foreground">{value}</div>
      )}
    </div>
  );
}
