import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getReports, createReport, deleteReport, analyzeReport, getClients, getAnalysisStatus } from '../api/client';

function StatusBadge({ status }) {
    const styles = {
        'draft': 'bg-dark-600 text-dark-300',
        'analyzing': 'status-running',
        'analyzing': 'status-running',
        'completed': 'status-completed',
        'new_data': 'bg-primary-900/50 text-primary-300 border border-primary-500/30',
    };

    return (
        <span className={`px-2 py-1 text-xs font-medium rounded-full ${styles[status] || 'bg-dark-700 text-dark-300'}`}>
            {status}
        </span>
    );
}

// Message bar component (similar to RequestsPage)
function MessageBar({ message, type, onClose }) {
    if (!message) return null;

    const styles = {
        success: 'bg-green-900/50 border-green-500 text-green-300',
        error: 'bg-red-900/50 border-red-500 text-red-300',
        info: 'bg-blue-900/50 border-blue-500 text-blue-300',
    };

    return (
        <div className={`mb-4 p-4 rounded-lg border ${styles[type]} flex justify-between items-center`}>
            <span>{message}</span>
            <button onClick={onClose} className="text-current opacity-70 hover:opacity-100">✕</button>
        </div>
    );
}

export default function ReportsPage() {
    const navigate = useNavigate();
    const [reports, setReports] = useState([]);
    const [clients, setClients] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showNewReport, setShowNewReport] = useState(false);
    const [newReportName, setNewReportName] = useState('');
    const [selectedClientId, setSelectedClientId] = useState('');

    // Analysis state
    const [analyzingReportId, setAnalyzingReportId] = useState(null);
    const [analysisStatus, setAnalysisStatus] = useState({}); // { reportId: { pending, total } }

    // Message bar
    const [message, setMessage] = useState('');
    const [messageType, setMessageType] = useState('info');

    useEffect(() => {
        loadData();
    }, []);

    async function loadData() {
        setLoading(true);
        try {
            const [reportsData, clientsData] = await Promise.all([
                getReports(),
                getClients()
            ]);
            setReports(reportsData);
            setClients(clientsData);

            // Load analysis status for each report
            const statusPromises = reportsData.map(async (r) => {
                try {
                    const status = await getAnalysisStatus(r.id);
                    return { id: r.id, status };
                } catch {
                    return { id: r.id, status: null };
                }
            });
            const statuses = await Promise.all(statusPromises);
            const statusMap = {};
            statuses.forEach(s => { statusMap[s.id] = s.status; });
            setAnalysisStatus(statusMap);
        } catch (err) {
            console.error('Failed to load data:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleCreateReport(e) {
        e.preventDefault();
        if (!newReportName.trim() || !selectedClientId) return;
        try {
            const newReport = await createReport({ name: newReportName, client_id: selectedClientId });
            setNewReportName('');
            setSelectedClientId('');
            setShowNewReport(false);
            // Redirect to create request for this report
            if (newReport?.id) {
                navigate(`/requests/new?report_id=${newReport.id}`);
            } else {
                loadData();
            }
        } catch (err) {
            console.error('Failed to create report:', err);
            setMessage('Failed to create report: ' + err.message);
            setMessageType('error');
        }
    }

    async function handleDeleteReport(reportId) {
        if (!confirm('Are you sure you want to delete this report?')) return;
        try {
            await deleteReport(reportId);
            loadData();
        } catch (err) {
            console.error('Failed to delete report:', err);
        }
    }

    async function handleAnalyze(reportId) {
        // Check if already analyzing
        if (analyzingReportId === reportId) return;

        // Check if has pending results
        const status = analysisStatus[reportId];
        if (!status || status.pending_results === 0) {
            setMessage('No pending results to analyze. Collect more data first.');
            setMessageType('info');
            return;
        }

        setAnalyzingReportId(reportId);
        setMessage('');

        try {
            await analyzeReport(reportId);
            setMessage(`Analysis job started! Processing ${status.pending_results} pending results.`);
            setMessageType('success');
            loadData();
        } catch (err) {
            console.error('Failed to trigger analysis:', err);
            setMessage('Failed to trigger analysis: ' + err.message);
            setMessageType('error');
        } finally {
            setAnalyzingReportId(null);
        }
    }

    async function refreshProgress(reportId) {
        try {
            const status = await getAnalysisStatus(reportId);
            setAnalysisStatus(prev => ({
                ...prev,
                [reportId]: status
            }));
        } catch (err) {
            console.error('Failed to refresh progress:', err);
        }
    }

    function canAnalyze(reportId) {
        const status = analysisStatus[reportId];
        return status && status.pending_results > 0;
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Reports</h1>
                    <p className="text-dark-400 mt-1">
                        Manage GEO analysis reports
                    </p>
                </div>
                <button
                    onClick={() => setShowNewReport(true)}
                    className="btn-primary"
                >
                    + New Report
                </button>
            </div>

            {/* Message Bar */}
            <MessageBar
                message={message}
                type={messageType}
                onClose={() => setMessage('')}
            />

            {/* New Report Modal */}
            {showNewReport && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
                    <div className="bg-dark-800 rounded-xl p-6 w-full max-w-md">
                        <h2 className="text-xl font-bold text-white mb-4">New Report</h2>
                        <form onSubmit={handleCreateReport} className="space-y-4">
                            <div>
                                <label className="block text-sm text-dark-300 mb-1">Report Name</label>
                                <input
                                    type="text"
                                    placeholder="e.g., Eufy Robot Vacuum GEO Report 2026Q1"
                                    value={newReportName}
                                    onChange={(e) => setNewReportName(e.target.value)}
                                    className="w-full px-4 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
                                    autoFocus
                                />
                            </div>
                            <div>
                                <label className="block text-sm text-dark-300 mb-1">Client</label>
                                <select
                                    value={selectedClientId}
                                    onChange={(e) => setSelectedClientId(e.target.value)}
                                    className="w-full px-4 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                                >
                                    <option value="">Select a client...</option>
                                    {clients.map((client) => (
                                        <option key={client.id} value={client.id}>
                                            {client.name}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="flex justify-end gap-3 mt-4">
                                <button
                                    type="button"
                                    onClick={() => setShowNewReport(false)}
                                    className="btn-secondary"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="btn-primary"
                                    disabled={!newReportName.trim() || !selectedClientId}
                                >
                                    Create
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Reports Table */}
            <div className="glass-card overflow-hidden">
                {loading ? (
                    <div className="flex items-center justify-center h-48">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
                    </div>
                ) : reports.length === 0 ? (
                    <div className="text-center py-12 text-dark-400">
                        <p>No reports yet</p>
                        <button
                            onClick={() => setShowNewReport(true)}
                            className="mt-4 text-primary-400 hover:text-primary-300"
                        >
                            Create your first report
                        </button>
                    </div>
                ) : (
                    <table className="w-full">
                        <thead className="bg-dark-800/50">
                            <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-dark-400 uppercase tracking-wider">
                                    Report Name
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-dark-400 uppercase tracking-wider">
                                    Client
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-dark-400 uppercase tracking-wider">
                                    Status
                                </th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-dark-400 uppercase tracking-wider">
                                    Analysis Progress
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-dark-400 uppercase tracking-wider">
                                    Actions
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-dark-700">
                            {reports.map((report) => {
                                const status = analysisStatus[report.id];
                                const isAnalyzing = analyzingReportId === report.id;
                                const hasPending = status && status.pending_results > 0;

                                return (
                                    <tr key={report.id} className="hover:bg-dark-800/30">
                                        <td className="px-4 py-4">
                                            <Link
                                                to={`/reports/${report.id}`}
                                                className="text-white font-medium hover:text-primary-400"
                                            >
                                                {report.name}
                                            </Link>
                                        </td>
                                        <td className="px-4 py-4 text-dark-300">
                                            {report.client_name}
                                        </td>
                                        <td className="px-4 py-4">
                                            <StatusBadge status={report.status === 'completed' && hasPending ? 'new_data' : report.status} />
                                        </td>
                                        <td className="px-4 py-4">
                                            {status ? (
                                                <div className="flex items-center text-sm">
                                                    <span className="text-dark-300">
                                                        {status.analyzed_results} / {status.total_results} analyzed
                                                    </span>
                                                    <button
                                                        onClick={(e) => {
                                                            e.preventDefault();
                                                            refreshProgress(report.id);
                                                        }}
                                                        className="ml-2 p-1 text-dark-500 hover:text-primary-400 rounded transition-colors"
                                                        title="Refresh progress"
                                                    >
                                                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                                        </svg>
                                                    </button>
                                                </div>
                                            ) : (
                                                <span className="text-dark-500">-</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-4 text-right">
                                            <div className="flex justify-end gap-2">
                                                {/* Analyze Button */}
                                                <button
                                                    onClick={() => handleAnalyze(report.id)}
                                                    disabled={isAnalyzing || (status && status.total_results === 0) || (!hasPending && report.status === 'completed')}
                                                    className={`h-8 px-3 text-xs font-medium rounded-lg transition-colors flex items-center justify-center border border-transparent ${isAnalyzing
                                                        ? 'bg-dark-700 text-dark-300 cursor-wait'
                                                        : (!hasPending && report.status === 'completed') || (status && status.total_results === 0)
                                                            ? 'bg-dark-700 text-dark-500 cursor-not-allowed'
                                                            : 'bg-primary-600 hover:bg-primary-500 text-white shadow-lg shadow-primary-500/20'
                                                        }`}
                                                    title={!hasPending && report.status === 'completed' ? 'Analysis completed' : 'Run analysis'}
                                                >
                                                    {isAnalyzing ? (
                                                        <>
                                                            <span className="animate-spin h-3 w-3 border-2 border-white/30 border-t-white rounded-full mr-2"></span>
                                                            Analyzing
                                                        </>
                                                    ) : (
                                                        hasPending && report.status === 'completed' ? 'Update' : 'Analyze'
                                                    )}
                                                </button>

                                                {/* View Results Link */}
                                                <Link
                                                    to={`/reports/${report.id}`}
                                                    className={`h-8 px-3 text-xs font-medium rounded-lg transition-colors flex items-center justify-center border ${status && status.analyzed_results > 0
                                                        ? 'bg-dark-700 hover:bg-dark-600 text-white border-dark-600'
                                                        : 'bg-dark-800 text-dark-500 border-transparent cursor-not-allowed'
                                                        }`}
                                                    style={{ pointerEvents: status && status.analyzed_results > 0 ? 'auto' : 'none' }}
                                                >
                                                    Results
                                                </Link>

                                                {/* View Requests */}
                                                <Link
                                                    to={`/requests?report_id=${report.id}`}
                                                    className="h-8 px-3 text-xs font-medium rounded-lg transition-colors flex items-center justify-center bg-dark-700 hover:bg-dark-600 text-white border border-dark-600"
                                                >
                                                    Requests
                                                </Link>

                                                {/* Delete */}
                                                <button
                                                    onClick={() => handleDeleteReport(report.id)}
                                                    className="h-8 px-3 text-xs font-medium rounded-lg transition-colors flex items-center justify-center bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20"
                                                >
                                                    Delete
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
