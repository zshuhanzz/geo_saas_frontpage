import type { RefObject } from "react";
import { useTranslation } from "react-i18next";
import { Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import AgentToolbar from "@/components/agents/AgentToolbar";

export interface ChatInputProps {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  input: string;
  sending: boolean;
  isComposing: boolean;
  slashMenuOpen: boolean;
  slashFilter: string;
  slashIndex: number;
  clientId: string | null | undefined;
  userId: string;
  threadId: string | null;
  intentLabel: string | null;
  modelOverride: string | null;
  contextUsage: { tokens_used: number; tokens_max: number; turns: number; compressed: boolean; percentage: number } | null;
  memoryCount: number | null;
  dailyQuota: any;
  forceMemoryOpen: boolean;
  autoResize: (el: HTMLTextAreaElement | null) => void;
  onInputChange: (val: string) => void;
  onSlashMenuOpenChange: (open: boolean) => void;
  onSlashFilterChange: (val: string) => void;
  onSlashIndexChange: (idx: number | ((prev: number) => number)) => void;
  onCompositionStart: () => void;
  onCompositionEnd: () => void;
  onSend: () => void;
  onSlashCommand: (cmd: string) => void;
  onModelChange: (model: string | null) => void;
  onForceMemoryOpenChange: (open: boolean) => void;
}

export function ChatInput({
  inputRef,
  input,
  sending,
  isComposing,
  slashMenuOpen,
  slashFilter,
  slashIndex,
  clientId,
  userId,
  threadId,
  intentLabel,
  modelOverride,
  contextUsage,
  memoryCount,
  dailyQuota,
  forceMemoryOpen,
  autoResize,
  onInputChange,
  onSlashMenuOpenChange,
  onSlashFilterChange,
  onSlashIndexChange,
  onCompositionStart,
  onCompositionEnd,
  onSend,
  onSlashCommand,
  onModelChange,
  onForceMemoryOpenChange,
}: ChatInputProps) {
  const { t } = useTranslation("agents");
  return (
    <div className="shrink-0 bg-card/80 backdrop-blur-xl border-t border-border/50 px-4 py-3">
      <div className="max-w-4xl mx-auto relative">
        <div className="relative rounded-2xl border bg-card shadow-sm hover:shadow-md hover:border-primary/20 focus-within:border-primary/30 focus-within:shadow-glow-sm transition-all duration-200">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => {
              const val = e.target.value;
              onInputChange(val);
              autoResize(e.target);
              // Slash command detection
              if (val.startsWith("/")) {
                onSlashMenuOpenChange(true);
                onSlashFilterChange(val);
                onSlashIndexChange(0);
              } else {
                onSlashMenuOpenChange(false);
                onSlashFilterChange("");
              }
            }}
            placeholder={t("chat.inputPlaceholder")}
            rows={1}
            style={{ minHeight: 52, maxHeight: 200 }}
            className="w-full resize-none rounded-2xl bg-transparent px-5 py-3.5 pr-14 text-sm focus:outline-none placeholder:text-muted-foreground/50"
            onCompositionStart={onCompositionStart}
            onCompositionEnd={onCompositionEnd}
            onKeyDown={(e) => {
              if (e.key === "Escape" && slashMenuOpen) {
                onSlashMenuOpenChange(false);
                return;
              }
              // Arrow key navigation for slash menu
              if (slashMenuOpen && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
                e.preventDefault();
                const COMMANDS = ["/compress", "/model flash", "/model pro", "/memories"];
                const filter = slashFilter || "/";
                const filtered = COMMANDS.filter((c) => filter === "/" || c.startsWith(filter));
                if (filtered.length === 0) return;
                onSlashIndexChange((prev) => {
                  if (e.key === "ArrowUp") return prev <= 0 ? filtered.length - 1 : prev - 1;
                  return prev >= filtered.length - 1 ? 0 : prev + 1;
                });
                return;
              }
              if (e.key === "Enter" && !e.shiftKey && !isComposing) {
                e.preventDefault();
                // Slash menu open — select highlighted command
                if (slashMenuOpen && input.startsWith("/")) {
                  const COMMANDS = ["/compress", "/model flash", "/model pro", "/memories"];
                  const filter = slashFilter || "/";
                  const filtered = COMMANDS.filter((c) => filter === "/" || c.startsWith(filter));
                  const selected = filtered[slashIndex] || filtered[0];
                  if (selected) onSlashCommand(selected);
                  return;
                }
                if (input.startsWith("/")) {
                  onSlashCommand(input.trim());
                  return;
                }
                onSend();
              }
            }}
            onBlur={() => setTimeout(() => onSlashMenuOpenChange(false), 200)}
            disabled={sending}
          />
          <Button
            size="icon"
            className={cn(
              "absolute bottom-3 right-3 h-9 w-9 rounded-xl transition-all duration-200",
              input.trim() && !sending
                ? "bg-primary hover:bg-primary/90 text-primary-foreground shadow-sm"
                : "bg-muted text-muted-foreground"
            )}
            disabled={!input.trim() || sending}
            onClick={() => {
              if (input.startsWith("/")) {
                onSlashCommand(input.trim());
                return;
              }
              onSend();
            }}
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
        {/* Agent Toolbar */}
        <AgentToolbar
          clientId={clientId || ""}
          userId={userId}
          threadId={threadId}
          sending={sending}
          intentLabel={intentLabel}
          modelOverride={modelOverride}
          onModelChange={onModelChange}
          onSlashCommand={onSlashCommand}
          contextUsage={contextUsage}
          memoryCount={memoryCount}
          dailyQuota={dailyQuota}
          slashMenuOpen={slashMenuOpen}
          onSlashMenuClose={() => onSlashMenuOpenChange(false)}
          slashFilter={slashFilter}
          slashIndex={slashIndex}
          forceMemoryOpen={forceMemoryOpen}
          onForceMemoryOpenChange={onForceMemoryOpenChange}
        />
        <p className="text-[10px] text-center text-muted-foreground/40 mt-0.5">
          {t("chat.disclaimer")}
        </p>
      </div>
    </div>
  );
}
