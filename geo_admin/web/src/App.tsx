import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './contexts/AuthContext';
import { AppLayout } from './components/layout/AppLayout';
import LoginPage from './pages/LoginPage';
import GlobalConfigPage from './pages/GlobalConfigPage';
import ClientsPage from './pages/ClientsPage';
import AccessControlPage from './pages/AccessControlPage';
import FeatureAccessPage from './pages/FeatureAccessPage';
import TasksPage from './pages/TasksPage';
import PromptsPage from './pages/PromptsPage';
import LanguagesPage from './pages/LanguagesPage';
import ReportTemplatesPage from './pages/ReportTemplatesPage';
import AnalysisMetricsPage from './pages/AnalysisMetricsPage';
import AgentTasksPage from './pages/GeoReportRunsPage';
import StaticReportsPage from './pages/StaticReportsPage';
import BrandProfilesPage from './pages/BrandProfilesPage';
import ContentTemplatesPage from './pages/ContentTemplatesPage';
import MemoriesPage from './pages/MemoriesPage';
import AgentSessionsPage from './pages/AgentSessionsPage';
import TokenUsagePage from './pages/TokenUsagePage';
import UserProfilesPage from './pages/UserProfilesPage';
import MetricsPage from './pages/framework/MetricsPage';
import SubgoalsPage from './pages/framework/SubgoalsPage';
import StrategiesPage from './pages/framework/StrategiesPage';
import ContentAssetsPage from './pages/framework/ContentAssetsPage';

function App() {
    const { user, loading } = useAuth();

    if (loading) {
        return (
            <div className="min-h-screen bg-background flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500 text-accent"></div>
            </div>
        );
    }

    if (!user) {
        return <LoginPage />;
    }

    return (
        <BrowserRouter>
            <Routes>
                <Route element={<AppLayout />}>
                    {/* Admin Web has been scoped down, direct them to clients view */}
                    <Route path="/" element={<Navigate to="/clients" replace />} />
                    <Route path="/clients" element={<ClientsPage />} />
                    <Route path="/access-control" element={<AccessControlPage />} />
                    <Route path="/feature-access" element={<FeatureAccessPage />} />
                    <Route path="/prompts" element={<PromptsPage />} />
                    <Route path="/tasks" element={<TasksPage />} />
                    <Route path="/languages" element={<LanguagesPage />} />
                    <Route path="/global" element={<GlobalConfigPage />} />
                    <Route path="/analysis/templates" element={<ReportTemplatesPage />} />
                    <Route path="/analysis/metrics" element={<AnalysisMetricsPage />} />
                    <Route path="/analysis/tasks" element={<AgentTasksPage taskType="analysis" />} />
                    <Route path="/static-reports" element={<StaticReportsPage />} />
                    <Route path="/content/templates" element={<ContentTemplatesPage />} />
                    <Route path="/content/tasks" element={<AgentTasksPage taskType="content_generation" />} />
                    <Route path="/brand-profiles" element={<BrandProfilesPage />} />
                    <Route path="/framework/metrics" element={<MetricsPage />} />
                    <Route path="/framework/subgoals" element={<SubgoalsPage />} />
                    <Route path="/framework/strategies" element={<StrategiesPage />} />
                    <Route path="/framework/assets" element={<ContentAssetsPage />} />
                    <Route path="/agent/memories" element={<MemoriesPage />} />
                    <Route path="/agent/sessions" element={<AgentSessionsPage />} />
                    <Route path="/agent/token-usage" element={<TokenUsagePage />} />
                    <Route path="/agent/user-profiles" element={<UserProfilesPage />} />
                    <Route path="*" element={<Navigate to="/clients" replace />} />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}

export default App;
