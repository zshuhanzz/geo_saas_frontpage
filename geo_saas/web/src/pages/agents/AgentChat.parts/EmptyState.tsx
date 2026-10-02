import { useTranslation } from "react-i18next";
import type { AgentsTFn } from "./types";
import { getGreeting, SUGGESTION_ENTRIES } from "./utils";

/* Empty state: greeting + suggested prompts */
export function EmptyState({ onPickSuggestion }: { onPickSuggestion: (text: string) => void }) {
  const { t } = useTranslation("agents");
  return (
    <div className="max-w-3xl w-full flex flex-col items-center justify-center h-full">
      <div className="mb-4">
        <div className="w-16 h-16 rounded-2xl overflow-hidden bg-gradient-to-br from-primary/20 to-primary/5 shadow-lg shadow-primary/10 ring-1 ring-primary/10 animate-pulse-glow">
          <img src="/Anthony_Chat_Online.png" alt="Anthony" className="w-full h-full object-contain" />
        </div>
      </div>
      <h2 className="text-3xl font-bold text-foreground mb-2 tracking-tight">
        {getGreeting(t as unknown as AgentsTFn)}
      </h2>
      <p className="text-base text-muted-foreground mb-10">
        {t("chat.freeChat")}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-2xl mb-8">
        {SUGGESTION_ENTRIES.map((entry) => {
          const text = (t as AgentsTFn)(`chat.suggestions.${entry.key}`);
          return (
            <button
              key={entry.key}
              className="group text-left p-5 rounded-2xl border bg-card hover:bg-primary/[0.03] hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 hover:-translate-y-0.5 transition-all duration-300"
              onClick={() => {
                onPickSuggestion(text);
              }}
            >
              <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center text-lg mb-3 group-hover:bg-primary/15 transition-colors">
                {entry.icon}
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed group-hover:text-foreground transition-colors">
                {text}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
