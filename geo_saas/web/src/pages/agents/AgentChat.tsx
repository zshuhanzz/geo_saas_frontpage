import { useState, useEffect, useRef, useCallback } from "react";
import { flushSync } from "react-dom";
import { useTranslation } from "react-i18next";
import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSaaS } from "@/contexts/SaaSContext";
import { useAuth } from "@/contexts/AuthContext";
import {
  getAgentSessions,
  getAgentMessages,
  sendAgentChat,
  sendWidgetResponse,
  parseSSEStream,
  deleteAgentSession,
  renameAgentSession,
  submitActionReview,
  compressAgentChat,
} from "@/lib/api";
import type { WidgetResponse } from "@/components/agents/ChatWidgetRenderer";
import {
  Sidebar,
  EmptyState,
  HitlReviewPanel,
  ChatInput,
  ChatTaskCard,
  UserMessage,
  AssistantMessage,
} from "./AgentChat.parts";
import type { ChatSession, ChatMessage, ThinkingStep, WidgetEntry } from "./AgentChat.parts";

// ── Main Component ───────────────────────────────────────────

export default function AgentChat() {
  const { t } = useTranslation("agents");
  const { clientId } = useSaaS();
  const { user } = useAuth();
  const userId = user?.sub ? `google:${user.sub}` : "";
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeThread, setActiveThread] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sending, setSending] = useState(false);
  const [intentLabel, setIntentLabel] = useState<string | null>(null);
  const [hitlPending, setHitlPending] = useState(false);
  const [, setDraftContent] = useState<any>(null);
  const [feedbackInput, setFeedbackInput] = useState("");
  const [contextUsage, setContextUsage] = useState<{ tokens_used: number; tokens_max: number; turns: number; compressed: boolean; percentage: number } | null>(null);
  const [compressing, setCompressing] = useState(false);
  const [isComposing, setIsComposing] = useState(false);
  const [modelOverride, setModelOverride] = useState<string | null>(null);
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashFilter, setSlashFilter] = useState("");
  const [slashIndex, setSlashIndex] = useState(0);
  const [forceMemoryOpen, setForceMemoryOpen] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [dailyQuota, setDailyQuota] = useState<any>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activeThreadRef = useRef<string | null>(null);
  const skipNextLoadRef = useRef(false);
  /**
   * Forward-declared ref for handleWidgetRespond so handleSend (defined
   * earlier) can call it via the ref without violating "used before
   * declaration". Set in the effect right after handleWidgetRespond is built.
   */
  const handleWidgetRespondRef = useRef<((resp: WidgetResponse, msgIdx: number, widgetIdx: number) => Promise<void>) | null>(null);

  /** Auto-resize textarea to fit content */
  const autoResize = useCallback((el: HTMLTextAreaElement | null) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, []);

  // Keep ref in sync with state
  useEffect(() => {
    activeThreadRef.current = activeThread;
  }, [activeThread]);

  // Auto-scroll on new messages
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Load sessions on mount / clientId change
  useEffect(() => {
    if (!clientId) return;
    getAgentSessions(clientId, userId)
      .then((data) => setSessions(data || []))
      .catch(() => setSessions([]));
  }, [clientId]);

  // Load messages when a session is selected from sidebar.
  // Skip when activeThread was set by handleSend (messages already in state).
  useEffect(() => {
    if (skipNextLoadRef.current) {
      skipNextLoadRef.current = false;
      return;
    }
    if (!activeThread || !clientId) {
      setMessages([]);
      return;
    }
    getAgentMessages(clientId, activeThread, userId)
      .then((data) => {
        const msgs: ChatMessage[] = (data || []).map((m: any) => {
          const toolResults = m.tool_results || [];
          const charts = toolResults.filter(
            (item: any) => item?.type && item.type !== "draft_content" && item.type !== "thinking" && item.type !== "widgets",
          );
          const thinkingItem = toolResults.find((item: any) => item?.type === "thinking");
          const thinking = thinkingItem?.steps || undefined;
          const widgetsItem = toolResults.find((item: any) => item?.type === "widgets");
          const widgetsList: WidgetEntry[] | undefined = widgetsItem?.items?.map((w: any) => ({
            ...w,
            resolved: true,  // All persisted widgets are already resolved
          }));
          return {
            role: m.role,
            content: m.content,
            charts: charts.length > 0 ? charts : undefined,
            thinking,
            widgets: widgetsList && widgetsList.length > 0 ? widgetsList : undefined,
          };
        });
        setMessages(msgs);
      })
      .catch(() => setMessages([]));
  }, [activeThread, clientId]);

  // ── Send message ────────────────────────────────────────

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending || !clientId) return;

    // ── Conversational text-prompt fast path ──
    // If the most recent assistant message has an unresolved chat_text_prompt
    // widget, the user's reply IS the value for that widget — not a new chat
    // turn. Forward through the widget response handler so the agent sees a
    // structured response and continues the slot-filling flow.
    {
      let pendingChatPromptIdx: { msgIdx: number; widgetIdx: number; widget: WidgetEntry } | null = null;
      for (let mi = messages.length - 1; mi >= 0; mi--) {
        const m = messages[mi];
        if (m.role !== "ai" || !m.widgets || m.widgets.length === 0) continue;
        // Only consider the most recent AI turn that still has any widgets.
        const wi = m.widgets.findIndex(
          (w) => w.widget_type === "chat_text_prompt" && !w.resolved,
        );
        if (wi >= 0) {
          pendingChatPromptIdx = { msgIdx: mi, widgetIdx: wi, widget: m.widgets[wi] };
        }
        break;
      }
      if (pendingChatPromptIdx && activeThreadRef.current && handleWidgetRespondRef.current) {
        // Echo the user's text into the chat thread so they see what they sent.
        const echo: ChatMessage = { role: "human", content: text };
        setMessages((prev) => [...prev, echo]);
        setInput("");
        if (inputRef.current) inputRef.current.style.height = "auto";
        const w = pendingChatPromptIdx.widget;
        await handleWidgetRespondRef.current(
          { widget_id: w.widget_id, field: w.field, value: text },
          pendingChatPromptIdx.msgIdx,
          pendingChatPromptIdx.widgetIdx,
        );
        return;
      }
    }

    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    setSending(true);
    setIntentLabel(null);

    // Add user message immediately
    const userMsg: ChatMessage = { role: "human", content: text };
    setMessages((prev) => [...prev, userMsg]);

    // Add placeholder AI message (streaming)
    const aiPlaceholder: ChatMessage = { role: "ai", content: "", streaming: true, charts: [] };
    setMessages((prev) => [...prev, aiPlaceholder]);

    try {
      const currentThread = activeThreadRef.current;
      const response = await sendAgentChat(clientId, userId, text, currentThread || undefined, "chat");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      let accumulatedText = "";
      const charts: any[] = [];
      const thinkingSteps: ThinkingStep[] = [];
      const widgets: WidgetEntry[] = [];
      let threadId = currentThread;

      for await (const event of parseSSEStream(response)) {
        switch (event.type) {
          case "session_created":
            // Session exists in DB — add to sidebar immediately
            threadId = event.thread_id;
            activeThreadRef.current = threadId;
            skipNextLoadRef.current = true;
            setActiveThread(threadId);
            setSessions((prev) => {
              // Avoid duplicates
              if (prev.some((s) => s.thread_id === event.thread_id)) return prev;
              return [
                {
                  thread_id: event.thread_id,
                  title: event.title,
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                },
                ...prev,
              ];
            });
            break;

          case "intent":
            setIntentLabel(event.value);
            break;

          case "thinking":
            thinkingSteps.push(event.step);
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = { ...last, thinking: [...thinkingSteps] };
              }
              return copy;
            });
            break;

          case "tool_result":
            break;

          case "chart":
            charts.push(event.data);
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = { ...last, charts: [...charts] };
              }
              return copy;
            });
            break;

          case "widget":
            widgets.push({
              widget_id: event.widget_id,
              widget_type: event.widget_type,
              field: event.field,
              label: event.label,
              description: event.description,
              options: event.options,
              default_value: event.default_value,
              placeholder: event.placeholder,
              config: event.config,
              summary: event.summary,
              step_key: event.step_key,
              step_num: event.step_num,
              step_label: event.step_label,
              step_description: event.step_description,
              required: event.required,
              steps: event.steps,
            });
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = { ...last, widgets: [...widgets] };
              }
              return copy;
            });
            break;

          case "token":
            accumulatedText += event.text;
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = { ...last, content: accumulatedText };
              }
              return copy;
            });
            break;

          case "task_ready":
            // Agent collected all inputs — show task confirmation card
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = { ...last, content: accumulatedText, streaming: false, thinking: thinkingSteps.length > 0 ? thinkingSteps : undefined };
              }
              // Inject task_type from SSE event into inputs so ChatTaskCard can use it directly
              const taskInputs = { ...event.inputs, task_type: event.task_type };
              copy.push({
                role: "task_card" as const,
                content: "",
                taskInputs,
                summaryDisplay: event.summary_display || undefined,
              });
              return copy;
            });
            break;

          case "draft_content":
            setDraftContent(event.data);
            break;

          case "hitl_pending":
            setHitlPending(true);
            break;

          case "session_title":
            // Update sidebar title in real-time (no refresh needed)
            if (event.thread_id && event.title) {
              setSessions((prev) =>
                prev.map((s) =>
                  s.thread_id === event.thread_id ? { ...s, title: event.title } : s,
                ),
              );
            }
            break;

          case "export_ready":
            // Finalize current AI message with export button data
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = {
                  ...last,
                  content: accumulatedText,
                  streaming: false,
                  exportReady: {
                    threadId: event.thread_id,
                    turnCount: event.turn_count || 0,
                    chartCount: event.chart_count || 0,
                  },
                };
              }
              return copy;
            });
            break;

          case "done":
            // Finalize AI message — unlock input
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = {
                  ...last,
                  content: accumulatedText,
                  charts: charts.length > 0 ? charts : undefined,
                  thinking: thinkingSteps.length > 0 ? thinkingSteps : undefined,
                  widgets: widgets.length > 0 ? widgets : undefined,
                  streaming: false,
                };
              }
              return copy;
            });
            if (event.context_usage) setContextUsage(event.context_usage);
            if (event.memory_count != null) setMemoryCount(event.memory_count);
            if (event.daily_quota) setDailyQuota(event.daily_quota);
            setSending(false);
            setIntentLabel(null);
            break;

          case "error":
            accumulatedText += `\n\n⚠️ ${event.message}`;
            break;
        }
      }

      // Note: message finalization, thread update, and sidebar refresh
      // are handled in the "done" event handler above so they don't
      // wait for post-done events (like session_title) to complete.
    } catch (err: any) {
      // Replace streaming placeholder with error
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.streaming) {
          copy[copy.length - 1] = {
            role: "ai",
            content: `Sorry, an error occurred: ${err.message}`,
            streaming: false,
          };
        }
        return copy;
      });
    } finally {
      // Ensure last streaming message is finalized (handles broken SSE streams)
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.streaming) {
          copy[copy.length - 1] = { ...last, content: last.content || "Connection lost, please retry.", streaming: false };
        }
        return copy;
      });
      setSending(false);
      setIntentLabel(null);
    }
  }, [input, sending, clientId, userId, messages]);

  // ── Widget Response Handler ─────────────────────────────

  const handleWidgetRespond = useCallback(async (resp: WidgetResponse, msgIdx: number, widgetIdx: number) => {
    // Mark widget as resolved, check if all widgets in the group are done
    let allResolved = false;
    let allResponses: WidgetResponse[] = [];

    flushSync(() => {
      setMessages((prev) => {
        const copy = [...prev];
        const msg = copy[msgIdx];
        if (msg?.widgets?.[widgetIdx]) {
          const updatedWidgets = [...msg.widgets];
          updatedWidgets[widgetIdx] = { ...updatedWidgets[widgetIdx], resolved: true, resolvedValue: resp.value };
          copy[msgIdx] = { ...msg, widgets: updatedWidgets };

          allResolved = updatedWidgets.every((w) => w.resolved);
          if (allResolved) {
            allResponses = updatedWidgets.map((w) => ({
              widget_id: w.widget_id,
              field: w.field,
              value: w.resolvedValue,
            }));
          }
        }
        return copy;
      });
    });

    if (!allResolved || !clientId || !activeThreadRef.current) return;

    // All widgets resolved — send batch response and process SSE stream
    try {
      const sseResponse = await sendWidgetResponse(clientId, userId, activeThreadRef.current, allResponses.length === 1 ? allResponses[0] : allResponses, "chat");
      if (!sseResponse.ok) {
        const errText = await sseResponse.text().catch(() => `HTTP ${sseResponse.status}`);
        setMessages((prev) => [...prev, { role: "ai" as const, content: `⚠️ Request failed: ${errText}`, streaming: false }]);
        return;
      }

      setSending(true);
      setMessages((prev) => [...prev, { role: "ai" as const, content: "", streaming: true, charts: [] }]);

      let accText = "";
      const charts: any[] = [];
      const thinkSteps: ThinkingStep[] = [];
      const newWidgets: WidgetEntry[] = [];

      for await (const event of parseSSEStream(sseResponse)) {
        switch (event.type) {
          case "thinking":
            thinkSteps.push(event.step);
            setMessages((prev) => {
              const copy = [...prev]; const last = copy[copy.length - 1];
              if (last?.streaming) copy[copy.length - 1] = { ...last, thinking: [...thinkSteps] };
              return copy;
            });
            break;
          case "token":
            accText += event.text;
            setMessages((prev) => {
              const copy = [...prev]; const last = copy[copy.length - 1];
              if (last?.streaming) copy[copy.length - 1] = { ...last, content: accText };
              return copy;
            });
            break;
          case "chart":
            charts.push(event.data);
            setMessages((prev) => {
              const copy = [...prev]; const last = copy[copy.length - 1];
              if (last?.streaming) copy[copy.length - 1] = { ...last, charts: [...charts] };
              return copy;
            });
            break;
          case "widget":
            newWidgets.push({
              widget_id: event.widget_id, widget_type: event.widget_type, field: event.field,
              label: event.label, description: event.description, options: event.options,
              default_value: event.default_value, placeholder: event.placeholder,
              config: event.config, summary: event.summary,
              step_key: event.step_key, step_num: event.step_num,
              step_label: event.step_label, step_description: event.step_description,
              required: event.required, steps: event.steps,
            });
            setMessages((prev) => {
              const copy = [...prev]; const last = copy[copy.length - 1];
              if (last?.streaming) copy[copy.length - 1] = { ...last, widgets: [...newWidgets] };
              return copy;
            });
            break;
          case "task_ready": {
            const trInputs = { ...event.inputs, task_type: event.task_type };
            const trSummary = event.summary_display || undefined;
            setMessages((prev) => {
              const copy = [...prev]; const last = copy[copy.length - 1];
              if (last?.streaming) copy[copy.length - 1] = { ...last, content: accText, streaming: false, thinking: thinkSteps.length > 0 ? thinkSteps : undefined };
              copy.push({
                role: "task_card" as const,
                content: "",
                taskInputs: trInputs,
                summaryDisplay: trSummary,
              });
              return copy;
            });
            break;
          }
          case "draft_content":
            setDraftContent(event.data);
            break;
          case "hitl_pending":
            setHitlPending(true);
            break;
          case "session_title":
            if (event.thread_id && event.title) {
              setSessions((prev) => prev.map((s) => s.thread_id === event.thread_id ? { ...s, title: event.title } : s));
            }
            break;
          case "done":
            setMessages((prev) => {
              const copy = [...prev]; const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = {
                  ...last, content: accText,
                  charts: charts.length > 0 ? charts : undefined,
                  thinking: thinkSteps.length > 0 ? thinkSteps : undefined,
                  widgets: newWidgets.length > 0 ? newWidgets : undefined,
                  streaming: false,
                };
              }
              return copy;
            });
            if (event.context_usage) setContextUsage(event.context_usage);
            if (event.memory_count != null) setMemoryCount(event.memory_count);
            if (event.daily_quota) setDailyQuota(event.daily_quota);
            setSending(false);
            break;
          case "error":
            accText += `\n\n⚠️ ${event.message}`;
            break;
        }
      }
    } catch (err: any) {
      setMessages((prev) => {
        const copy = [...prev]; const last = copy[copy.length - 1];
        if (last?.streaming) copy[copy.length - 1] = { role: "ai", content: `Sorry, an error occurred: ${err.message}`, streaming: false };
        return copy;
      });
    } finally {
      setMessages((prev) => {
        const copy = [...prev]; const last = copy[copy.length - 1];
        if (last?.streaming) copy[copy.length - 1] = { ...last, content: last.content || "Connection lost, please retry.", streaming: false };
        return copy;
      });
      setSending(false);
    }
  }, [clientId, userId]);

  // Keep the forward-declared ref in sync so handleSend's chat_text_prompt
  // fast path can call into the latest closure.
  useEffect(() => {
    handleWidgetRespondRef.current = handleWidgetRespond;
  }, [handleWidgetRespond]);

  // ── HITL Review ─────────────────────────────────────────

  const handleReview = useCallback(async (approved: boolean) => {
    if (!clientId || !activeThread) return;
    setSending(true);
    setHitlPending(false);

    if (approved) {
      // Add approval message
      setMessages((prev) => [
        ...prev,
        { role: "human", content: "✅ Content approved" },
        { role: "ai", content: "", streaming: true },
      ]);
    } else {
      const fb = feedbackInput.trim() || "Please improve content quality";
      setMessages((prev) => [
        ...prev,
        { role: "human", content: `🔄 Please regenerate: ${fb}` },
        { role: "ai", content: "", streaming: true },
      ]);
    }

    try {
      const response = await submitActionReview(
        clientId,
        userId,
        activeThread,
        approved,
        approved ? undefined : feedbackInput.trim() || undefined,
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      let accumulatedText = "";
      setFeedbackInput("");

      for await (const event of parseSSEStream(response)) {
        switch (event.type) {
          case "draft_content":
            setDraftContent(event.data);
            break;

          case "hitl_pending":
            setHitlPending(true);
            break;

          case "token":
            accumulatedText += event.text;
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.streaming) {
                copy[copy.length - 1] = { ...last, content: accumulatedText };
              }
              return copy;
            });
            break;

          case "error":
            accumulatedText += `\n\n⚠️ ${event.message}`;
            break;
        }
      }

      // Finalize
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.streaming) {
          copy[copy.length - 1] = { ...last, content: accumulatedText, streaming: false };
        }
        return copy;
      });
    } catch (err: any) {
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.streaming) {
          copy[copy.length - 1] = { role: "ai", content: `Review failed: ${err.message}`, streaming: false };
        }
        return copy;
      });
    } finally {
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last?.streaming) {
          copy[copy.length - 1] = { ...last, content: last.content || "Connection lost, please retry.", streaming: false };
        }
        return copy;
      });
      setSending(false);
    }
  }, [clientId, userId, activeThread, feedbackInput]);

  // ── New chat ────────────────────────────────────────────

  const handleNewChat = () => {
    activeThreadRef.current = null;
    setActiveThread(null);
    setMessages([]);
    setIntentLabel(null);
    setHitlPending(false);
    setDraftContent(null);
    setFeedbackInput("");
    setContextUsage(null);
    setMemoryCount(null);
    setDailyQuota(null);
  };

  const handleCompress = useCallback(async () => {
    if (!clientId || !activeThreadRef.current || compressing) return;
    setCompressing(true);
    try {
      const res = await compressAgentChat(clientId, userId, activeThreadRef.current);
      if (res.context_usage) setContextUsage(res.context_usage);
      if (res.compressed) {
        // Reload messages to reflect compressed state
        const msgs = await getAgentMessages(clientId, activeThreadRef.current, userId);
        setMessages(msgs.map((m: any) => ({ role: m.role, content: m.content })));
      }
    } catch (err) {
      console.error("Compress failed:", err);
    } finally {
      setCompressing(false);
    }
  }, [clientId, userId, compressing]);

  /** Handle slash command execution (from toolbar menu or typed input) */
  const handleSlashCommand = useCallback((command: string) => {
    setSlashMenuOpen(false);
    setSlashFilter("");
    setInput("");

    if (command === "/compress") {
      if (!activeThreadRef.current) {
        setMessages((prev) => [...prev, { role: "ai" as const, content: "No conversation context, compression not needed." }]);
      } else {
        handleCompress();
      }
    } else if (command.startsWith("/model ")) {
      const tier = command.replace("/model ", "").trim();
      setModelOverride(tier === "auto" ? null : tier);
      // Show feedback as a system message
      const label = tier === "pro" ? "Pro" : tier === "flash" ? "Flash" : "Auto";
      setMessages((prev) => [...prev, {
        role: "ai" as const,
        content: `✅ Switched to **${label}** model${tier === "auto" ? " (auto-selected by system)" : ""}`,
      }]);
    } else if (command === "/memories") {
      setForceMemoryOpen(true);
    }
  }, [handleCompress]);

  const handleDeleteSession = useCallback(async (threadId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!clientId) return;
    try {
      await deleteAgentSession(clientId, threadId, userId);
      setSessions((prev) => prev.filter((s) => s.thread_id !== threadId));
      if (activeThread === threadId) {
        setActiveThread(null);
        setMessages([]);
      }
    } catch {
      // silent fail
    }
  }, [clientId, activeThread]);

  // ── Session Rename ─────────────────────────────────────
  const [renamingThread, setRenamingThread] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

  const handleStartRename = useCallback((threadId: string, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setRenamingThread(threadId);
    setRenameValue(currentTitle || "");
    setTimeout(() => renameInputRef.current?.select(), 50);
  }, []);

  const handleConfirmRename = useCallback(async () => {
    if (!renamingThread || !clientId || !renameValue.trim()) {
      setRenamingThread(null);
      return;
    }
    try {
      await renameAgentSession(clientId, renamingThread, userId, renameValue.trim());
      setSessions((prev) =>
        prev.map((s) =>
          s.thread_id === renamingThread ? { ...s, title: renameValue.trim() } : s,
        ),
      );
    } catch {
      // silent fail
    }
    setRenamingThread(null);
  }, [renamingThread, renameValue, clientId, userId]);

  const handleCancelRename = useCallback(() => {
    setRenamingThread(null);
  }, []);

  // ── Render ──────────────────────────────────────────────

  const activeSessionTitle = sessions.find((s) => s.thread_id === activeThread)?.title;

  return (
    <div className="h-full flex overflow-hidden -m-6">
      {/* History Sidebar */}
      {sidebarOpen && (
        <Sidebar
          sessions={sessions}
          activeThread={activeThread}
          renamingThread={renamingThread}
          renameValue={renameValue}
          renameInputRef={renameInputRef}
          onNewChat={handleNewChat}
          onSelectSession={(threadId) => { setMemoryCount(null); setDailyQuota(null); setActiveThread(threadId); }}
          onRenameValueChange={setRenameValue}
          onConfirmRename={handleConfirmRename}
          onCancelRename={handleCancelRename}
          onStartRename={handleStartRename}
          onDeleteSession={handleDeleteSession}
        />
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="h-13 border-b border-border/50 flex items-center px-4 shrink-0 bg-card/80 backdrop-blur-xl relative">
          <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/15 to-transparent" />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            <MessageSquare className="h-4 w-4" />
          </Button>
          {activeSessionTitle && (
            <span className="ml-3 text-sm font-medium text-foreground">{activeSessionTitle}</span>
          )}
          {intentLabel && (
            <span className="ml-auto text-xs bg-primary/10 text-primary px-3 py-1 rounded-full font-medium">
              {intentLabel === "analyze" ? t("chat.modeAnalyze") : intentLabel === "action" ? t("chat.modeAction") : t("chat.modeChat")}
            </span>
          )}
        </div>

        {/* Chat content */}
        <div ref={scrollRef} className="flex-1 overflow-auto flex flex-col items-center px-4">
          {messages.length === 0 && !activeThread ? (
            <EmptyState onPickSuggestion={(text) => setInput(text)} />
          ) : (
            /* Message list — Gemini-style flat AI layout */
            <div className="max-w-4xl w-full py-8 space-y-8">
              {messages.map((msg, idx) => (
                <div key={idx}>
                  {msg.role === "human" ? (
                    <UserMessage content={msg.content} />
                  ) : msg.role === "task_card" ? (
                    <ChatTaskCard
                      inputs={msg.taskInputs || {}}
                      summaryDisplay={msg.summaryDisplay}
                      clientId={clientId}
                      userId={userId}
                      threadId={activeThreadRef.current}
                    />
                  ) : (
                    <AssistantMessage
                      msg={msg}
                      msgIdx={idx}
                      clientId={clientId}
                      onWidgetRespond={handleWidgetRespond}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* HITL Review Panel */}
        {hitlPending && (
          <HitlReviewPanel
            feedbackInput={feedbackInput}
            sending={sending}
            onFeedbackChange={setFeedbackInput}
            onReview={handleReview}
          />
        )}

        {/* Bottom input + toolbar */}
        {!hitlPending && (
          <ChatInput
            inputRef={inputRef}
            input={input}
            sending={sending}
            isComposing={isComposing}
            slashMenuOpen={slashMenuOpen}
            slashFilter={slashFilter}
            slashIndex={slashIndex}
            clientId={clientId}
            userId={userId}
            threadId={activeThreadRef.current}
            intentLabel={intentLabel}
            modelOverride={modelOverride}
            contextUsage={contextUsage}
            memoryCount={memoryCount}
            dailyQuota={dailyQuota}
            forceMemoryOpen={forceMemoryOpen}
            autoResize={autoResize}
            onInputChange={setInput}
            onSlashMenuOpenChange={setSlashMenuOpen}
            onSlashFilterChange={setSlashFilter}
            onSlashIndexChange={setSlashIndex}
            onCompositionStart={() => setIsComposing(true)}
            onCompositionEnd={() => setIsComposing(false)}
            onSend={handleSend}
            onSlashCommand={handleSlashCommand}
            onModelChange={setModelOverride}
            onForceMemoryOpenChange={setForceMemoryOpen}
          />
        )}
      </div>
    </div>
  );
}
