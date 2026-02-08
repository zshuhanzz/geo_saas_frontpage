import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getReports, createReport, deleteReport, analyzeReport, getClients, getAnalysisStatus } from '../api/client';

function StatusBadge({ status }) {
    const styles = {
        'draft': 'bg-dark-600 text-dark-300',
        'analyzing': 'status-running',
        'completed': 'status-completed',
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
                                    Analysis Status
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
                                            {status ? (
                                                <div className="text-sm">
                                                    <span className="text-dark-300">
                                                        {status.analyzed_results} / {status.total_results} analyzed
                                                    </span>
                                                    {status.pending_results > 0 && (
                                                        <span className="ml-2 text-yellow-400">
                                                            ({status.pending_results} pending)
                                                        </span>
                                                    )}
                                                </div>
                                            ) : (
                                                <span className="text-dark-500">-</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-4 text-right">
                                            <div className="flex justify-end gap-3">
                                                {/* Analyze Button */}
                                                <button
                                                    onClick={() => handleAnalyze(report.id)}
                                                    disabled={isAnalyzing || !hasPending}
                                                    className={`text-sm px-3 py-1 rounded-lg transition-colors ${isAnalyzing
                                                            ? 'bg-green-900/50 text-green-300 cursor-wait'
                                                            : hasPending
                                                                ? 'bg-green-600 hover:bg-green-500 text-white'
                                                                : 'bg-dark-700 text-dark-500 cursor-not-allowed'
                                                        }`}
                                                    title={!hasPending ? 'No pending results to analyze' : ''}
                                                >
                                                    {isAnalyzing ? (
                                                        <span className="flex items-center gap-2">
                                                            <span className="animate-spin h-3 w-3 border-2 border-white/30 border-t-white rounded-full"></span>
                                                            Analyzing...
                                                        </span>
                                                    ) : (
                                                        'Analyze'
                                                    )}
                                                </button>

                                                {/* View Results Link */}
                                                {status && status.analyzed_results > 0 && (
                                                    <Link
                                                        to={`/reports/${report.id}`}
                                                        className="text-primary-400 hover:text-primary-300 text-sm"
                                                    >
                                                        View Results
                                                    </Link>
                                                )}

                                                {/* View Requests */}
                                                <Link
                                                    to={`/requests?report_id=${report.id}`}
                                                    className="text-dark-400 hover:text-dark-300 text-sm"
                                                >
                                                    Requests
                                                </Link>

                                                {/* Delete */}
                                                <button
                                                    onClick={() => handleDeleteReport(report.id)}
                                                    className="text-red-400 hover:text-red-300 text-sm"
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
