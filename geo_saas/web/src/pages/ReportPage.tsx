import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router-dom";
import { useSaaS } from "../contexts/SaaSContext";
import { authHeaders, handleAuthExpiredResponse } from "../lib/api";

const AGENT_BASE = (import.meta.env.VITE_AGENT_API_URL || "") + "/api/agent";

export default function ReportPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const [searchParams] = useSearchParams();
  const { t } = useTranslation("common");
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Try SaaS context first; if unavailable (e.g. admin link), fall back to query param
  let ctxClientId = "";
  try {
    const ctx = useSaaS();
    ctxClientId = ctx.clientId || "";
  } catch {
    // SaaSProvider not available (admin or external link)
  }
  const clientId = searchParams.get("client_id") || ctxClientId;

  useEffect(() => {
    if (!taskId || !clientId) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError("");
    setHtml("");

    fetch(`${AGENT_BASE}/tasks/${taskId}/export?client_id=${clientId}&view=true`, {
      headers: authHeaders(),
    })
      .then(async (response) => {
        if (!response.ok) {
          const detail = await response
            .json()
            .then((body) => body?.detail)
            .catch(() => "");
          handleAuthExpiredResponse(response, detail || `HTTP ${response.status}`);
          throw new Error(detail || `HTTP ${response.status}`);
        }
        return response.text();
      })
      .then((text) => {
        if (!cancelled) setHtml(text);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || t("states.loadingFailed"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [clientId, taskId, t]);

  if (!taskId || !clientId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <p className="text-muted-foreground">{t("report.missingParams")}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="flex items-center gap-3 text-muted-foreground">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted border-t-primary" />
          <span>{t("report.loading")}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-6">
        <div className="max-w-md rounded-lg border bg-card p-6 text-center shadow-sm">
          <h1 className="text-lg font-semibold text-foreground">{t("states.loadingFailed")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-white">
      <iframe
        srcDoc={html}
        className="flex-1 w-full border-0 min-h-screen"
        title="Report"
      />
    </div>
  );
}
