import { useState, useEffect } from "react";
import { FileSearch, SkipForward } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getOpportunityTasks, getAgentTask, type OpportunityTaskSummary } from "@/lib/api";

interface NodeAnalyzerImportProps {
  clientId: string;
  value: { analyzerTaskId: string | null; analyzerContext: any | null };
  onChange: (data: { analyzerTaskId: string | null; analyzerContext: any | null }) => void;
  onSkip?: () => void;
}

export default function NodeAnalyzerImport({ clientId, value, onChange, onSkip }: NodeAnalyzerImportProps) {
  const { t } = useTranslation("content");
  const [tasks, setTasks] = useState<OpportunityTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getOpportunityTasks(clientId).then(setTasks).catch(() => setTasks([])).finally(() => setLoading(false));
  }, [clientId]);

  const handleSelect = async (taskId: string) => {
    const task = await getAgentTask(taskId, clientId);
    onChange({ analyzerTaskId: taskId, analyzerContext: task.output || null });
  };

  const handleSkip = () => {
    onChange({ analyzerTaskId: null, analyzerContext: null });
    onSkip?.();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <FileSearch className="w-5 h-5 text-amber-400" />
        <h3 className="text-lg font-semibold text-foreground">{t("nodes.analyzerImport.title")}</h3>
        <Badge variant="outline" className="text-xs text-muted-foreground border-border">{t("nodes.analyzerImport.optionalBadge")}</Badge>
      </div>

      <p className="text-sm text-muted-foreground">
        {t("nodes.analyzerImport.intro")}
      </p>

      {loading ? (
        <div className="text-muted-foreground text-sm py-4">{t("nodes.analyzerImport.loading")}</div>
      ) : tasks.length === 0 ? (
        <div className="text-muted-foreground text-sm py-4 border border-dashed border-border rounded-lg p-4 text-center">
          {t("nodes.analyzerImport.empty")}
          <br />
          <span className="text-xs">{t("nodes.analyzerImport.emptyHint")}</span>
        </div>
      ) : (
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {tasks.map((task) => (
            <Card
              key={task.id}
              className={`p-3 cursor-pointer border transition-colors ${
                value.analyzerTaskId === task.id
                  ? "border-amber-500/50 bg-amber-500/5"
                  : "border-border bg-muted/50 hover:border-border/80"
              }`}
              onClick={() => handleSelect(task.id)}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">{task.task_name || t("nodes.analyzerImport.defaultTaskName")}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {task.completed_at ? new Date(task.completed_at).toLocaleDateString() : ""}
                    {task.topic_scope ? ` · ${task.topic_scope}` : ""}
                  </p>
                </div>
                <div className="flex gap-2 text-xs">
                  <Badge variant="secondary">{task.summary.topic_count} Topics</Badge>
                  <Badge variant="secondary">{t("nodes.analyzerImport.opportunityCount", { count: task.summary.opportunity_count })}</Badge>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <div className="flex justify-end pt-2">
        <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground" onClick={handleSkip}>
          <SkipForward className="w-4 h-4 mr-1" />
          {t("nodes.analyzerImport.skipButton")}
        </Button>
      </div>
    </div>
  );
}
