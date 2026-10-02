import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect } from "react";
import { toast, Toaster } from "sonner";
import { useTranslation } from "react-i18next";
import { Layout } from "./components/layout/Layout";
import InsightsLayout from "./pages/Insights";
import Visibility from "./pages/insights/Visibility";
import Prompts from "./pages/insights/Prompts";
import PromptDrilldown from "./pages/insights/PromptDrilldown";
import Fanouts from "./pages/insights/Fanouts";
import Citations from "./pages/insights/Citations";
import ChannelAnalysisPage from "./pages/insights/ChannelAnalysisPage";
import SentimentDashboard from "./pages/SentimentDashboard";
import CitationDashboard from "./pages/CitationDashboard";
import OverviewDashboard from "./pages/OverviewDashboard";
import { SaaSProvider } from "./contexts/SaaSContext";
import { useAuth } from "./contexts/AuthContext";
import LoginPage from "./pages/LoginPage";
import SettingsPage from "./pages/SettingsPage";
import PromptEditor from "./pages/PromptEditor";
import AgentAnalysis from "./pages/agents/AgentAnalysis";
import AgentContent from "./pages/agents/AgentContent";
import AgentTraining from "./pages/agents/AgentTraining";
import AgentChat from "./pages/agents/AgentChat";
import BrandHub from "./pages/BrandHub";
import ReportPage from "./pages/ReportPage";
import ReportsListPage from "./pages/reports/ReportsListPage";
import StaticReportPage from "./pages/reports/StaticReportPage";
import { ConfirmProvider } from "./components/ui/confirm-dialog";
import { SaaSAuditTracker } from "./components/audit/SaaSAuditTracker";
import { AUTH_EXPIRED_EVENT, SESSION_EXPIRED_MESSAGE } from "./lib/api/_base";
import { PROMPT_ROUTE_CONTRACT } from "./components/layout/sidebarNavigation";

function Placeholder({ titleKey }: { titleKey: "overview" | "knowledge" }) {
  const { t } = useTranslation(["sidebar", "common"]);
  return (
    <div className="h-full flex flex-col items-center justify-center space-y-3">
      <h2 className="text-2xl font-semibold text-foreground">{t(`nav.${titleKey}`)}</h2>
      <p className="text-muted-foreground">{t("common:states.comingSoon")}</p>
    </div>
  );
}

function SessionExpiryToaster() {
  useEffect(() => {
    function handleAuthExpired(event: Event) {
      const message = (event as CustomEvent<string>).detail || SESSION_EXPIRED_MESSAGE;
      toast.error(message, { id: "geo-saas-auth-expired" });
    }

    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
  }, []);

  return null;
}

function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Toaster position="top-right" richColors closeButton />
        <SessionExpiryToaster />
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!user) {
    return (
      <>
        <Toaster position="top-right" richColors closeButton />
        <SessionExpiryToaster />
        <LoginPage />
      </>
    );
  }

  return (
    <SaaSProvider>
      <ConfirmProvider>
      <Toaster position="top-right" richColors closeButton />
      <SessionExpiryToaster />
      <BrowserRouter>
        <SaaSAuditTracker />
        <Routes>
          {/* Full-screen report page — no sidebar */}
          <Route path="report/:taskId" element={<ReportPage />} />
          <Route path="share/reports/:reportId" element={<StaticReportPage presentation />} />

          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/overview" replace />} />
            <Route path="overview" element={<OverviewDashboard />} />

            <Route path="insights" element={<InsightsLayout />}>
              <Route index element={<Navigate to="visibility" replace />} />
              <Route path="visibility" element={<Visibility />} />
              <Route path={PROMPT_ROUTE_CONTRACT.childSegment} element={<Prompts />} />
              <Route path={`${PROMPT_ROUTE_CONTRACT.childSegment}/topic/:topicId`} element={<PromptDrilldown />} />
              <Route path={`${PROMPT_ROUTE_CONTRACT.childSegment}/product`} element={<PromptDrilldown />} />
              <Route path={`${PROMPT_ROUTE_CONTRACT.childSegment}/prompt/:promptId`} element={<PromptDrilldown />} />
              <Route path="fanouts" element={<Fanouts />} />
              <Route path="citations" element={<Citations />} />
              <Route path="channel-analysis" element={<ChannelAnalysisPage />} />
            </Route>

            {/* Dashboards — standalone */}
            <Route path="citation" element={<CitationDashboard />} />
            <Route path="sentiment" element={<SentimentDashboard />} />

            <Route
              path={PROMPT_ROUTE_CONTRACT.legacyPath}
              element={(
                <Navigate
                  to={PROMPT_ROUTE_CONTRACT.redirectTarget}
                  replace={PROMPT_ROUTE_CONTRACT.replace}
                />
              )}
            />
            <Route path="prompt-editor" element={<PromptEditor />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="reports" element={<ReportsListPage />} />
            <Route path="reports/static/:reportId" element={<StaticReportPage />} />

            {/* Agents */}
            <Route path="agents/tracking" element={<SettingsPage />} />
            <Route path="agents/analysis" element={<AgentAnalysis />} />
            <Route path="agents/content" element={<AgentContent />} />
            <Route path="agents/training" element={<AgentTraining />} />
            <Route path="agents/chat" element={<AgentChat />} />

            {/* Context (Coming Soon) */}
            <Route path="knowledge" element={<Placeholder titleKey="knowledge" />} />
            <Route path="brand-hub" element={<BrandHub />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </ConfirmProvider>
    </SaaSProvider>
  );
}

export default App;
