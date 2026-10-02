import { useCallback } from "react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import { flushSync } from "react-dom";
import {
  sendAgentChat,
  sendWidgetResponse,
  parseSSEStream,
  submitActionReview,
} from "@/lib/api";
import type { WidgetResponse } from "@/components/agents/ChatWidgetRenderer";
import type { ChatSession, ChatMessage, ThinkingStep, WidgetEntry } from "./types";

/**
 * SSE state-machine hook for AgentChat.
 *
 * Encapsulates `handleSend`, `handleWidgetRespond`, and `handleReview`. All state
 * setters and refs are passed in, so this hook is purely a logic carrier — no
 * behavioral change vs. inline definitions in AgentChat.tsx.
 */
export interface UseAgentChatStreamArgs {
  // Inputs
  input: string;
  sending: boolean;
  clientId: string | null | undefined;
  userId: string;
  activeThread: string | null;
  feedbackInput: string;

  // Refs
  inputRef: RefObject<HTMLTextAreaElement>;
  activeThreadRef: RefObject<string | null>;
  skipNextLoadRef: RefObject<boolean>;

  // Setters
  setInput: Dispatch<SetStateAction<string>>;
  setSending: Dispatch<SetStateAction<boolean>>;
  setIntentLabel: Dispatch<SetStateAction<string | null>>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setSessions: Dispatch<SetStateAction<ChatSession[]>>;
  setActiveThread: Dispatch<SetStateAction<string | null>>;
  setDraftContent: Dispatch<SetStateAction<any>>;
  setHitlPending: Dispatch<SetStateAction<boolean>>;
  setContextUsage: Dispatch<SetStateAction<{ tokens_used: number; tokens_max: number; turns: number; compressed: boolean; percentage: number } | null>>;
  setMemoryCount: Dispatch<SetStateAction<number | null>>;
  setDailyQuota: Dispatch<SetStateAction<any>>;
  setFeedbackInput: Dispatch<SetStateAction<string>>;
}

export function useAgentChatStream(args: UseAgentChatStreamArgs) {
  const {
    input, sending, clientId, userId, activeThread, feedbackInput,
    inputRef, activeThreadRef, skipNextLoadRef,
    setInput, setSending, setIntentLabel, setMessages, setSessions,
    setActiveThread, setDraftContent, setHitlPending, setContextUsage,
    setMemoryCount, setDailyQuota, setFeedbackInput,
  } = args;

  // ── Send message ────────────────────────────────────────

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending || !clientId) return;

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
            (activeThreadRef as { current: string | null }).current = threadId;
            (skipNextLoadRef as { current: boolean }).current = true;
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
  }, [input, sending, clientId, userId]); // eslint-disable-line react-hooks/exhaustive-deps

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
              label: event.label, description: event.description,
              options: event.options, default_value: event.default_value,
              placeholder: event.placeholder, config: event.config, summary: event.summary,
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
  }, [clientId, userId]); // eslint-disable-line react-hooks/exhaustive-deps

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
  }, [clientId, userId, activeThread, feedbackInput]); // eslint-disable-line react-hooks/exhaustive-deps

  return { handleSend, handleWidgetRespond, handleReview };
}
