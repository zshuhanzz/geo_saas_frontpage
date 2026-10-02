import { useState } from "react";
import { Send, X, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface AgentTaskPageProps {
  /** Page title shown in the top banner */
  title: string;
  /** Description text for the banner */
  description: string;
  /** Placeholder text for the input box */
  inputPlaceholder: string;
  /** Template cards config */
  templates: {
    iconUrl?: string;
    iconEmoji?: string;
    title: string;
    desc: string;
  }[];
}

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 6) return "Late night";
  if (h < 12) return "Good morning";
  if (h < 14) return "Good afternoon";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * Shared Agent Task page layout used by both AgentAnalysis and AgentContent.
 * Matches the reference UI with "New Agent Task / All Tasks" tabs, banner,
 * greeting with logo, chat input, and template cards with branded icons.
 */
export default function AgentTaskPage({
  title,
  description,
  inputPlaceholder,
  templates,
}: AgentTaskPageProps) {
  const [activeTab, setActiveTab] = useState<"new" | "all">("new");
  const [showBanner, setShowBanner] = useState(true);
  const [input, setInput] = useState("");

  return (
    <div className="h-full flex flex-col">
      {/* Page header with title + tabs */}
      <div className="shrink-0 px-4">
        <h1 className="text-2xl font-bold tracking-tight pt-1 pb-3">{title}</h1>
        <div className="flex border-b">
          <button
            onClick={() => setActiveTab("new")}
            className={`pb-2.5 px-1 mr-6 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "new"
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            New Agent Task
          </button>
          <button
            onClick={() => setActiveTab("all")}
            className={`pb-2.5 px-1 mr-6 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "all"
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            All Tasks
          </button>
        </div>
      </div>

      {activeTab === "new" ? (
        <div className="flex-1 flex flex-col overflow-auto">
          {/* Banner */}
          {showBanner && (
            <div className="mx-auto w-full max-w-4xl mt-5 mb-2 px-2">
              <Card className="flex items-center gap-4 p-5 bg-muted/30 border relative group">
                <img
                  src="/Anthony_Chat.png"
                  alt="Anthony"
                  className="w-16 h-16 rounded-full object-contain bg-gradient-to-br from-primary/10 to-muted shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-sm">{title}</h3>
                  <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">
                    {description}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute top-2 right-2 h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => setShowBanner(false)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </Card>
            </div>
          )}

          {/* Center greeting */}
          <div className="flex-1 flex flex-col items-center justify-center px-4 -mt-2">
            <div className="flex items-center gap-4 mb-10">
              <img src="/logo.png" alt="AnswerX" className="h-[4.5rem] w-auto" />
              <h1 className="text-4xl md:text-5xl font-semibold text-foreground tracking-tight">
                {getGreeting()}
              </h1>
            </div>

            {/* Chat input */}
            <div className="w-full max-w-3xl">
              <div className="relative rounded-2xl border bg-background shadow-sm hover:shadow-md transition-shadow">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={inputPlaceholder}
                  rows={3}
                  className="w-full resize-none rounded-2xl bg-transparent px-5 py-4 pr-14 text-sm focus:outline-none placeholder:text-muted-foreground/60"
                />
                <Button
                  size="icon"
                  variant="ghost"
                  className="absolute bottom-3 right-3 h-8 w-8 rounded-full bg-muted hover:bg-primary hover:text-primary-foreground transition-colors"
                  disabled={!input.trim()}
                >
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* Template cards */}
            <div className="mt-10 w-full max-w-4xl">
              <p className="text-sm font-medium text-muted-foreground mb-4">
                Start from a template
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {templates.map((t) => (
                  <button
                    key={t.title}
                    className="group text-left p-5 rounded-xl border bg-background hover:bg-muted/40 hover:border-primary/20 hover:shadow-sm transition-all duration-200"
                    onClick={() => setInput(t.desc)}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      {t.iconUrl ? (
                        <div className="w-9 h-9 rounded-lg bg-muted/60 flex items-center justify-center p-1">
                          <img src={t.iconUrl} alt="" className="w-5 h-5 object-contain" />
                        </div>
                      ) : (
                        <div className="w-9 h-9 rounded-lg bg-foreground flex items-center justify-center">
                          <ArrowRight className="w-4 h-4 text-background" />
                        </div>
                      )}
                    </div>
                    <p className="text-sm font-medium text-foreground leading-snug group-hover:text-primary transition-colors">
                      {t.title}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* All Tasks tab — placeholder */
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
          <p className="text-sm">All Tasks view coming soon</p>
        </div>
      )}
    </div>
  );
}
