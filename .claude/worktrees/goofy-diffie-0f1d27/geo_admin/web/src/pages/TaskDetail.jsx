import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getTask, getResults } from '../api/client';

function StatusBadge({ status }) {
    const styles = {
        'PENDING': 'status-pending',
        'DISPATCHING': 'status-running',
        'COMPLETED': 'status-completed',
        'DISPATCH_FAILED': 'status-failed',
    };

    return (
        <span className={`px-2 py-1 text-xs font-medium rounded-full ${styles[status] || 'bg-dark-700 text-dark-300'}`}>
            {status}
        </span>
    );
}

function InfoCard({ label, value, fullWidth = false }) {
    return (
        <div className={fullWidth ? 'col-span-full' : ''}>
            <p className="text-dark-400 text-sm">{label}</p>
            <p className="text-white font-medium whitespace-pre-wrap">{value || '-'}</p>
        </div>
    );
}

export default function TaskDetail() {
    const { taskId } = useParams();
    const [task, setTask] = useState(null);
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(true);
    const [resultPage, setResultPage] = useState(1);
    const [resultPagination, setResultPagination] = useState({ pages: 1, total: 0 });

    useEffect(() => {
        loadTask();
    }, [taskId]);

    useEffect(() => {
        if (taskId) loadResults();
    }, [taskId, resultPage]);

    async function loadTask() {
        try {
            const data = await getTask(taskId);
            setTask(data);
        } catch (err) {
            console.error('Failed to load task:', err);
        } finally {
            setLoading(false);
        }
    }

    async function loadResults() {
        try {
            const data = await getResults(taskId, resultPage, 20);
            setResults(data.data);
            setResultPagination(data.pagination);
        } catch (err) {
            console.error('Failed to load results:', err);
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
        );
    }

    if (!task) {
        return (
            <div className="text-center py-12">
                <h2 className="text-xl text-white">Task not found</h2>
                <Link to="/requests" className="text-primary-400 mt-4 inline-block">← Back to Requests</Link>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Breadcrumb */}
            <div className="flex items-center gap-2 text-sm">
                <Link to="/requests" className="text-dark-400 hover:text-white">Requests</Link>
                <span className="text-dark-600">/</span>
                <Link to={`/requests/${task.request_id}`} className="text-dark-400 hover:text-white">
                    {task.client_name}
                </Link>
                <span className="text-dark-600">/</span>
                <span className="text-white">Task #{task.prompt_index}</span>
            </div>

            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Task #{task.prompt_index}</h1>
                    <p className="text-dark-400 mt-1 font-mono text-sm">{task.task_id}</p>
                </div>
                <StatusBadge status={task.status} />
            </div>

            {/* Task Info */}
            <div className="glass-card p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Task Details</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                    <InfoCard label="Client" value={task.client_name} />
                    <InfoCard label="Peers" value={task.peers} />
                    <InfoCard label="Platform" value={task.platform} />
                    <InfoCard label="Country" value={task.country} />
                    <InfoCard label="Topic" value={task.topic} />
                    <InfoCard label="Product" value={task.product} />
                    <InfoCard label="Intent" value={task.intent} />
                    <InfoCard label="Calls" value={`${task.completed_count}/${task.calls_per_prompt} completed`} />
                </div>

                {/* Prompt Text */}
                <div className="mt-6 pt-6 border-t border-dark-700">
                    <p className="text-dark-400 text-sm mb-2">Prompt Text</p>
                    <div className="bg-dark-800 rounded-lg p-4">
                        <p className="text-white">{task.prompt_text}</p>
                    </div>
                </div>
            </div>

            {/* Results Table */}
            <div className="glass-card p-6">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        Results ({resultPagination.total})
                    </h2>
                </div>

                <div className="overflow-x-auto">
                    <table className="admin-table">
                        <thead>
                            <tr>
                                <th>Call #</th>
                                <th>Platform</th>
                                <th>Text Preview</th>
                                <th>Sources</th>
                                <th>Entities</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {results.map((result) => (
                                <tr key={result.result_id}>
                                    <td className="font-medium text-white">{result.call_index}</td>
                                    <td>
                                        <span className="px-2 py-1 bg-dark-800 rounded text-xs">
                                            {result.platform || '-'}
                                        </span>
                                    </td>
                                    <td className="max-w-md">
                                        <p className="text-sm text-dark-200 line-clamp-2">
                                            {result.text_preview || result.text?.slice(0, 100) || '-'}
                                        </p>
                                    </td>
                                    <td>
                                        {Array.isArray(result.sources) ? result.sources.length : 0}
                                    </td>
                                    <td>
                                        {Array.isArray(result.entities) ? result.entities.length : 0}
                                    </td>
                                    <td>
                                        <Link
                                            to={`/results/${result.result_id}`}
                                            className="text-primary-400 hover:text-primary-300"
                                        >
                                            View →
                                        </Link>
                                    </td>
                                </tr>
                            ))}
                            {results.length === 0 && (
                                <tr>
                                    <td colSpan="6" className="text-center py-8 text-dark-400">
                                        No results yet
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>

                {/* Pagination */}
                {resultPagination.pages > 1 && (
                    <div className="flex items-center justify-center gap-2 mt-4">
                        <button
                            onClick={() => setResultPage(p => p - 1)}
                            disabled={resultPage <= 1}
                            className="btn-secondary text-sm disabled:opacity-50"
                        >
                            ←
                        </button>
                        <span className="text-dark-400 text-sm">
                            {resultPage} / {resultPagination.pages}
                        </span>
                        <button
                            onClick={() => setResultPage(p => p + 1)}
                            disabled={resultPage >= resultPagination.pages}
                            className="btn-secondary text-sm disabled:opacity-50"
                        >
                            →
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
