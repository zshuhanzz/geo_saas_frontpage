import { FileDown, Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { exportAgentTaskHTML, getReportURL } from "@/lib/api";
import TaskProgressCard from "../../TaskProgressCard";

interface ResultViewProps {
  taskId: string | null;
  taskOutput: any;
  clientId: string;
  onClose: () => void;
}

export function ResultView({ taskId, taskOutput, clientId, onClose }: ResultViewProps) {
  const { t } = useTranslation("content");

  return (
    <div className="flex-1 overflow-auto p-6 space-y-4">
      {taskId && (
        <TaskProgressCard taskId={taskId} initialStatus="COMPLETED" compact />
      )}

      {/* RAFT Scores */}
      {taskOutput.raft_scores && (
        <div className="rounded-xl border p-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">{t("taskModal.resultCard.raftQuality")}</h4>
          <div className="grid grid-cols-2 gap-2">
            {["readability", "answerability", "trustworthiness", "timeliness"].map((dim) => {
              const s = taskOutput.raft_scores[dim];
              if (!s) return null;
              return (
                <div key={dim} className="flex items-center justify-between rounded-lg bg-muted/30 px-3 py-2">
                  <span className="text-xs font-medium capitalize">{dim}</span>
                  <span className="text-sm font-bold text-primary">{s.score}/5</span>
                </div>
              );
            })}
          </div>
          {taskOutput.raft_scores.overall && (
            <div className="mt-2 pt-2 border-t text-center text-sm">
              {t("taskModal.resultCard.overall")}: <span className="font-bold text-primary">{taskOutput.raft_scores.overall}/5</span>
            </div>
          )}
        </div>
      )}

      {/* FAQ Content */}
      {taskOutput.faqs && taskOutput.faqs.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("taskModal.resultCard.generatedContent")}</h4>
          {taskOutput.faqs.map((faq: any, i: number) => (
            <div key={i} className="rounded-xl border p-4">
              <p className="text-sm font-medium mb-1">Q{i + 1}: {faq.question}</p>
              <p className="text-sm text-muted-foreground">{faq.answer}</p>
            </div>
          ))}
        </div>
      )}

      {taskOutput.citation_analysis_summary_markdown && (
        <div className="rounded-xl border p-5">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            {t("taskModal.resultCard.citationAnalysis")}
          </h4>
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
              {taskOutput.citation_analysis_summary_markdown}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* Article / Brief Content */}
      {taskOutput.content_markdown && (
        <div className="rounded-xl border p-5 prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{taskOutput.content_markdown}</ReactMarkdown>
        </div>
      )}

      {/* Recommendations */}
      {taskOutput.recommendations && taskOutput.recommendations.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("taskModal.resultCard.recommendations")}</h4>
          {taskOutput.recommendations.map((rec: any, i: number) => (
            <div key={i} className="rounded-xl border p-3 flex items-start gap-3">
              <Badge
                variant="outline"
                className={
                  rec.priority === "high" ? "text-red-500 border-red-500/30" :
                  rec.priority === "medium" ? "text-amber-500 border-amber-500/30" :
                  "text-green-500 border-green-500/30"
                }
              >
                {rec.priority}
              </Badge>
              <div>
                <p className="text-sm font-medium">{rec.title}</p>
                <p className="text-xs text-muted-foreground">{rec.description}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Improvement Suggestions */}
      {taskOutput.improvement_suggestions && taskOutput.improvement_suggestions.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">{t("taskModal.resultCard.improvements")}</h4>
          <ul className="text-xs text-muted-foreground space-y-1">
            {taskOutput.improvement_suggestions.map((s: string, i: number) => (
              <li key={i}>- {s}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-2">
        {taskId && (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open(getReportURL(taskId, clientId), "_blank")}
              className="gap-1.5"
            >
              <Eye className="h-3.5 w-3.5" />
              {t("taskModal.resultCard.viewReportDetail")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => exportAgentTaskHTML(taskId, clientId)}
              className="gap-1.5"
            >
              <FileDown className="h-3.5 w-3.5" />
              {t("taskModal.resultCard.exportHtml")}
            </Button>
          </>
        )}
        <Button variant="outline" size="sm" onClick={onClose}>{t("taskModal.resultCard.close")}</Button>
      </div>
    </div>
  );
}
