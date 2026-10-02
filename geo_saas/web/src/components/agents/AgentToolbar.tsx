/**
 * AgentToolbar — event-driven status indicators + quick actions.
 *
 * No polling. All data pushed from parent via SSE done events:
 *   - contextUsage: from SSE done event
 *   - memoryCount: from SSE done event
 *   - dailyQuota: from SSE done event
 *
 * Initial load: one fetch on mount. Then all updates via props.
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Brain,
  Zap,
  Sparkles,
  Minimize2,
  Loader2,
  ChevronDown,
  MessageSquare,
  Gauge,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { getToolbarStatus, getUserMemories, compressAgentChat } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────

export interface ContextUsage {
  tokens_used: number;
  tokens_max: number;
  turns: number;
  compressed: boolean;
  percentage: number;
}

export interface DailyQuota {
  used: number;
  limit: number;
  reset_at: string;
  percentage: number;
}

export interface SlashCommand {
  command: string;
  label: string;
  description: string;
  icon: React.ReactNode;
}

// Slash command definitions use key pointers; labels/descriptions resolve via t()
// in the component so both zh and en modes get the right copy.
type SlashKey = "compress" | "flash" | "pro" | "memories";
const SLASH_COMMAND_DEFS: { command: string; key: SlashKey; icon: React.ReactNode }[] = [
  { command: "/compress", key: "compress", icon: <Minimize2 className="h-3.5 w-3.5" /> },
  { command: "/model flash", key: "flash", icon: <Zap className="h-3.5 w-3.5" /> },
  { command: "/model pro", key: "pro", icon: <Sparkles className="h-3.5 w-3.5" /> },
  { command: "/memories", key: "memories", icon: <Brain className="h-3.5 w-3.5" /> },
];

// ── Helpers ──────────────────────────────────────────────────

function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function progressColor(pct: number): string {
  if (pct >= 80) return "bg-destructive";
  if (pct >= 50) return "bg-amber-500";
  return "bg-primary";
}

function textColor(pct: number): string {
  if (pct >= 80) return "text-destructive";
  return "text-muted-foreground/60";
}

// ── Component ────────────────────────────────────────────────

interface AgentToolbarProps {
  clientId: string;
  userId: string;
  threadId: string | null;
  sending: boolean;
  intentLabel: string | null;
  modelOverride: string | null;
  onModelChange: (tier: string | null) => void;
  onSlashCommand: (command: string) => void;
  // Event-driven data (pushed from SSE done events by parent)
  contextUsage: ContextUsage | null;
  memoryCount: number | null;
  dailyQuota: DailyQuota | null;
  // Slash command menu
  slashMenuOpen: boolean;
  onSlashMenuClose: () => void;
  slashFilter: string;
  slashIndex?: number;
  // Controlled memory popover
  forceMemoryOpen?: boolean;
  onForceMemoryOpenChange?: (open: boolean) => void;
}

export default function AgentToolbar({
  clientId,
  userId,
  threadId,
  sending,
  intentLabel,
  modelOverride,
  onModelChange,
  onSlashCommand,
  contextUsage,
  memoryCount: memCountProp,
  dailyQuota: dailyQuotaProp,
  slashMenuOpen,
  onSlashMenuClose,
  slashFilter,
  slashIndex: slashIdxProp = 0,
  forceMemoryOpen,
  onForceMemoryOpenChange,
}: AgentToolbarProps) {
  const { t } = useTranslation("agents");
  // Materialize slash commands with localized label/description. useMemo so we
  // only regenerate when the language changes.
  const SLASH_COMMANDS: SlashCommand[] = useMemo(
    () =>
      SLASH_COMMAND_DEFS.map((d) => ({
        command: d.command,
        label: t(`toolbar.slash.${d.key}Label`),
        description: t(`toolbar.slash.${d.key}Desc`),
        icon: d.icon,
      })),
    [t],
  );
  // Local state for initial fetch + model list
  const [initMemCount, setInitMemCount] = useState(0);
  const [initDailyQuota, setInitDailyQuota] = useState<DailyQuota | null>(null);
  const [initCtx, setInitCtx] = useState<ContextUsage | null>(null);
  const [models, setModels] = useState<{ id: string; tier: string; label: string }[]>([]);
  const [memories, setMemories] = useState<any[]>([]);
  const [internalMemoryOpen, setInternalMemoryOpen] = useState(false);
  const memoryOpen = forceMemoryOpen ?? internalMemoryOpen;
  const setMemoryOpen = (open: boolean) => {
    setInternalMemoryOpen(open);
    onForceMemoryOpenChange?.(open);
  };
  const [modelOpen, setModelOpen] = useState(false);
  const [compressing, setCompressing] = useState(false);

  // Use SSE-pushed data if available, otherwise fall back to initial fetch
  const memCount = memCountProp ?? initMemCount;
  const dailyQuota = dailyQuotaProp ?? initDailyQuota;
  const ctx = contextUsage ?? initCtx;

  // ── One-time initial fetch (no polling) ────────────────────
  useEffect(() => {
    if (!clientId || !userId) return;
    getToolbarStatus(clientId, userId, threadId || undefined)
      .then((data) => {
        setInitMemCount(data.memory_count ?? 0);
        if (data.quota?.daily_quota) setInitDailyQuota(data.quota.daily_quota);
        if (data.context_usage) setInitCtx(data.context_usage);
        if (data.models?.available) setModels(data.models.available);
      })
      .catch(() => {});
  }, [clientId, userId, threadId]);

  // ── Memory popover ──────────────────────────────────────────
  const loadMemories = useCallback(async () => {
    if (!clientId || !userId) return;
    try {
      const data = await getUserMemories(clientId, userId);
      setMemories(data);
    } catch {
      setMemories([]);
    }
  }, [clientId, userId]);

  useEffect(() => {
    if (memoryOpen) loadMemories();
  }, [memoryOpen, loadMemories]);

  // ── Compress handler ────────────────────────────────────────
  const handleCompress = useCallback(async () => {
    if (!clientId || !userId || !threadId || compressing) return;
    setCompressing(true);
    try {
      const res = await compressAgentChat(clientId, userId, threadId);
      if (res.context_usage) setInitCtx(res.context_usage);
    } catch (err) {
      console.error("Compress failed:", err);
    } finally {
      setCompressing(false);
    }
  }, [clientId, userId, threadId, compressing]);

  // ── Slash command filtering ─────────────────────────────────
  const filteredCommands = SLASH_COMMANDS.filter((cmd) => {
    if (!slashFilter || slashFilter === "/") return true;
    return cmd.command.startsWith(slashFilter) || cmd.label.includes(slashFilter.slice(1));
  });

  // ── Derived values ──────────────────────────────────────────
  const currentModel = modelOverride || "auto";
  const modelLabel =
    currentModel === "pro" ? t("toolbar.model.pro") :
    currentModel === "flash" ? t("toolbar.model.flash") :
    t("toolbar.model.auto");
  const modelIcon = currentModel === "pro" ? <Sparkles className="h-3 w-3" /> : <Zap className="h-3 w-3" />;

  const memoryTypeLabel = (type: string): string =>
    t(`toolbar.memoryType.${type}`, { defaultValue: type });

  return (
    <div className="flex items-center gap-1 px-1 py-1 select-none relative">
      {/* ── Memory Badge ── */}
      <Popover open={memoryOpen} onOpenChange={setMemoryOpen}>
        <PopoverTrigger asChild>
          <button
            className={cn(
              "flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] transition-colors",
              "hover:bg-accent/50",
              memCount > 0 ? "text-primary" : "text-muted-foreground/50"
            )}
          >
            <Brain className="h-3 w-3" />
            <span className="tabular-nums">{memCount}</span>
          </button>
        </PopoverTrigger>
        <PopoverContent side="top" align="start" className="w-72 p-0 max-h-64 overflow-hidden">
          <div className="px-3 py-2 border-b text-xs font-medium text-muted-foreground">
            {t("toolbar.memoryTitle", { count: memories.length })}
          </div>
          <div className="overflow-y-auto max-h-48 divide-y divide-border">
            {memories.length === 0 ? (
              <div className="px-3 py-4 text-xs text-muted-foreground/60 text-center">
                {t("toolbar.memoryEmpty")}
              </div>
            ) : (
              memories.map((m: any) => (
                <div key={m.id} className="px-3 py-2">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className={cn(
                      "text-[10px] font-medium px-1.5 py-0.5 rounded",
                      m.memory_type === "preference" ? "bg-blue-500/10 text-blue-400" :
                      m.memory_type === "fact" ? "bg-emerald-500/10 text-emerald-400" :
                      "bg-amber-500/10 text-amber-400"
                    )}>
                      {memoryTypeLabel(m.memory_type)}
                    </span>
                    {m.shared && (
                      <span className="text-[10px] text-muted-foreground/50">{t("toolbar.memoryShared")}</span>
                    )}
                  </div>
                  <p className="text-xs text-foreground/80 line-clamp-2">{m.content}</p>
                </div>
              ))
            )}
          </div>
        </PopoverContent>
      </Popover>

      <div className="w-px h-3 bg-border/50" />

      {/* ── Model Selector ── */}
      <Popover open={modelOpen} onOpenChange={setModelOpen}>
        <PopoverTrigger asChild>
          <button className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-muted-foreground/70 hover:bg-accent/50 transition-colors">
            {modelIcon}
            <span>{modelLabel}</span>
            <ChevronDown className="h-2.5 w-2.5 opacity-50" />
          </button>
        </PopoverTrigger>
        <PopoverContent side="top" align="start" className="w-52 p-1">
          <button
            onClick={() => { onModelChange(null); setModelOpen(false); }}
            className={cn(
              "w-full flex items-center gap-2 px-3 py-2 rounded-md text-xs transition-colors",
              currentModel === "auto" ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
            )}
          >
            <Gauge className="h-3.5 w-3.5" />
            <div className="text-left">
              <div className="font-medium">{t("toolbar.model.auto")}</div>
              <div className="text-[10px] text-muted-foreground">{t("toolbar.model.autoDesc")}</div>
            </div>
          </button>
          {models.map((m) => (
            <button
              key={m.tier}
              onClick={() => { onModelChange(m.tier); setModelOpen(false); }}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-2 rounded-md text-xs transition-colors",
                currentModel === m.tier ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
              )}
            >
              {m.tier === "pro" ? <Sparkles className="h-3.5 w-3.5" /> : <Zap className="h-3.5 w-3.5" />}
              <div className="text-left">
                <div className="font-medium">{m.label}</div>
                <div className="text-[10px] text-muted-foreground">
                  {m.tier === "pro" ? t("toolbar.model.proDesc") : t("toolbar.model.flashDesc")}
                </div>
              </div>
            </button>
          ))}
        </PopoverContent>
      </Popover>

      <div className="w-px h-3 bg-border/50" />

      {/* ── Context Progress ── */}
      {ctx && (
        <div className="flex items-center gap-1.5 px-1.5">
          <MessageSquare className="h-3 w-3 text-muted-foreground/40" />
          <div className="w-12 h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all duration-500", progressColor(ctx.percentage))}
              style={{ width: `${Math.min(ctx.percentage, 100)}%` }}
            />
          </div>
          <span className={cn("text-[10px] tabular-nums w-7 text-right", textColor(ctx.percentage))}>
            {ctx.percentage}%
          </span>
          {ctx.percentage >= 30 && threadId && (
            <button
              onClick={handleCompress}
              disabled={compressing}
              className="text-[10px] text-muted-foreground/50 hover:text-primary transition-colors disabled:opacity-50"
              title={t("toolbar.compressTitle")}
            >
              {compressing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Minimize2 className="h-3 w-3" />}
            </button>
          )}
        </div>
      )}

      {/* ── Daily Token Quota (always visible text) ── */}
      {dailyQuota && (
        <>
          <div className="w-px h-3 bg-border/50" />
          <div className="flex items-center gap-1 px-1.5">
            <span className={cn(
              "text-[10px] tabular-nums",
              dailyQuota.percentage >= 80 ? "text-destructive" : "text-muted-foreground/60"
            )}>
              {formatTokenCount(dailyQuota.used)} / {formatTokenCount(dailyQuota.limit)} {t("toolbar.tokensSuffix")}
            </span>
            <span className="text-[10px] text-muted-foreground/40">
              · {t("toolbar.todayLabel")}
            </span>
          </div>
        </>
      )}

      {/* ── Active Agent Badge ── */}
      {sending && intentLabel && (
        <>
          <div className="flex-1" />
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/5 border border-primary/10">
            <Loader2 className="h-3 w-3 animate-spin text-primary" />
            <span className="text-[10px] text-primary font-medium">{intentLabel}</span>
          </div>
        </>
      )}

      {/* ── Slash Command Menu ── */}
      {slashMenuOpen && filteredCommands.length > 0 && (
        <div className="absolute bottom-full left-0 right-0 mb-1 z-50">
          <div className="mx-auto max-w-4xl">
            <div className="rounded-xl border bg-popover shadow-lg p-1 animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-200">
              {filteredCommands.map((cmd, idx) => (
                <button
                  key={cmd.command}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs transition-colors text-left",
                    idx === slashIdxProp ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
                  )}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onSlashCommand(cmd.command);
                    onSlashMenuClose();
                  }}
                >
                  <span className="text-muted-foreground">{cmd.icon}</span>
                  <div>
                    <div className="font-medium text-foreground">{cmd.label}</div>
                    <div className="text-[10px] text-muted-foreground">{cmd.description}</div>
                  </div>
                  <span className="ml-auto text-[10px] text-muted-foreground/50 font-mono">{cmd.command}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
