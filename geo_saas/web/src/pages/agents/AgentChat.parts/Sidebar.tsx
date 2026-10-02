import type { RefObject } from "react";
import { useTranslation } from "react-i18next";
import { Plus, MessageSquare, Clock, Trash2, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AgentsTFn, ChatSession } from "./types";
import { timeAgo } from "./utils";

export interface SidebarProps {
  sessions: ChatSession[];
  activeThread: string | null;
  renamingThread: string | null;
  renameValue: string;
  renameInputRef: RefObject<HTMLInputElement | null>;
  onNewChat: () => void;
  onSelectSession: (threadId: string) => void;
  onRenameValueChange: (val: string) => void;
  onConfirmRename: () => void;
  onCancelRename: () => void;
  onStartRename: (threadId: string, currentTitle: string, e: React.MouseEvent) => void;
  onDeleteSession: (threadId: string, e: React.MouseEvent) => void;
}

export function Sidebar({
  sessions,
  activeThread,
  renamingThread,
  renameValue,
  renameInputRef,
  onNewChat,
  onSelectSession,
  onRenameValueChange,
  onConfirmRename,
  onCancelRename,
  onStartRename,
  onDeleteSession,
}: SidebarProps) {
  const { t } = useTranslation("agents");
  return (
    <div className="w-72 border-r border-border/50 bg-card/80 backdrop-blur-xl flex flex-col shrink-0">
      <div className="p-3 border-b">
        <Button
          className="w-full justify-start gap-2 h-10 text-sm rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 hover:shadow-glow-md"
          onClick={onNewChat}
        >
          <Plus className="h-4 w-4" />
          {t("chat.newChat")}
        </Button>
      </div>

      <div className="flex-1 overflow-auto py-2">
        <div className="px-3 mb-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 px-2">
            {t("chat.recentChats")}
          </p>
        </div>
        {sessions.length === 0 && (
          <p className="px-5 text-xs text-muted-foreground">{t("chat.emptyChats")}</p>
        )}
        {sessions.map((session) => (
          <div
            key={session.thread_id}
            role="button"
            tabIndex={0}
            className={cn(
              "w-full text-left px-4 py-3 mx-1 rounded-lg transition-colors group relative cursor-pointer",
              activeThread === session.thread_id
                ? "bg-primary/5 border border-primary/10"
                : "hover:bg-accent/50",
            )}
            onClick={() => { if (renamingThread !== session.thread_id) { onSelectSession(session.thread_id); } }}
            onKeyDown={(e) => { if (e.key === "Enter" && renamingThread !== session.thread_id) { onSelectSession(session.thread_id); } }}
          >
            <div className="flex items-start gap-3">
              <MessageSquare className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
              <div className="flex-1 min-w-0">
                {renamingThread === session.thread_id ? (
                  <input
                    ref={renameInputRef}
                    type="text"
                    value={renameValue}
                    onChange={(e) => onRenameValueChange(e.target.value)}
                    onKeyDown={(e) => {
                      e.stopPropagation();
                      if (e.key === "Enter") onConfirmRename();
                      if (e.key === "Escape") onCancelRename();
                    }}
                    onBlur={onConfirmRename}
                    onClick={(e) => e.stopPropagation()}
                    className="w-full text-sm font-medium bg-background border border-primary/30 rounded px-1.5 py-0.5 outline-none focus:ring-1 focus:ring-primary/50"
                    autoFocus
                  />
                ) : (
                  <p className="text-sm font-medium truncate text-foreground">
                    {session.title}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center justify-between mt-1 ml-7">
              <span className="text-[10px] text-muted-foreground/60 flex items-center gap-1">
                <Clock className="h-2.5 w-2.5" />
                {timeAgo(session.updated_at, t as unknown as AgentsTFn)}
              </span>
              <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-0.5">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5 text-muted-foreground hover:text-foreground"
                  onClick={(e) => onStartRename(session.thread_id, session.title, e)}
                >
                  <Pencil className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5 text-destructive/70 hover:text-destructive"
                  onClick={(e) => onDeleteSession(session.thread_id, e)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
