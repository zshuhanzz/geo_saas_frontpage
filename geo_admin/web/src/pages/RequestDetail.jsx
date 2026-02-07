import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getRequest, getTasks, getResults } from '../api/client';

function StatusBadge({ status }) {
    const styles = {
        'PENDING': 'status-pending',
        'DISPATCHING': 'status-running',
        'COMPLETED': 'status-completed',
        'DISPATCH_FAILED': 'status-failed',
        'EXPANDING': 'status-running',
        'EXPANDED': 'status-running',
    };

    return (
        <span className={`px-2 py-1 text-xs font-medium rounded-full ${styles[status] || 'bg-dark-700 text-dark-300'}`}>
            {status}
        </span>
    );
}

function InfoCard({ label, value }) {
    return (
        <div>
            <p className="text-dark-400 text-sm">{label}</p>
            <p className="text-white font-medium">{value || '-'}</p>
        </div>
    );
}

export default function RequestDetail() {
    const { id } = useParams();
    const [request, setRequest] = useState(null);
    const [tasks, setTasks] = useState([]);
    const [selectedTask, setSelectedTask] = useState(null);
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(true);
    const [taskPage, setTaskPage] = useState(1);
    const [taskPagination, setTaskPagination] = useState({ pages: 1 });

    useEffect(() => {
        loadRequest();
    }, [id]);

    useEffect(() => {
        if (id) loadTasks();
    }, [id, taskPage]);

    useEffect(() => {
        if (selectedTask) loadResults(selectedTask);
    }, [selectedTask]);

    async function loadRequest() {
        try {
            const data = await getRequest(id);
            setRequest(data);
        } catch (err) {
            console.error('Failed to load request:', err);
        } finally {
            setLoading(false);
        }
    }

    async function loadTasks() {
        try {
            const data = await getTasks(id, taskPage, 10);
            setTasks(data.data);
            setTaskPagination(data.pagination);
            // Auto-select first task
            if (data.data.length > 0 && !selectedTask) {
                setSelectedTask(data.data[0].task_id);
            }
        } catch (err) {
            console.error('Failed to load tasks:', err);
        }
    }

    async function loadResults(taskId) {
        try {
            const data = await getResults(taskId, 1, 10);
            setResults(data.data);
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

    if (!request) {
        return (
            <div className="text-center py-12">
                <h2 className="text-xl text-white">Request not found</h2>
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
                <span className="text-white">{request.client_name}</span>
            </div>

            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">{request.client_name}</h1>
                    <p className="text-dark-400 mt-1 font-mono text-sm">{request.request_id}</p>
                </div>
                <StatusBadge status={request.status} />
            </div>

            {/* Request Info */}
            <div className="glass-card p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Request Details</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                    <InfoCard label="Product" value={request.product} />
                    <InfoCard label="Peers" value={request.peers} />
                    <InfoCard label="Topic" value={request.topic} />
                    <InfoCard label="Platform" value={request.platform} />
                    <InfoCard label="Country" value={request.country} />
                    <InfoCard label="Intent" value={request.intent} />
                    <InfoCard label="Prompts/Request" value={request.prompts_per_request} />
                    <InfoCard label="Calls/Prompt" value={request.calls_per_prompt} />
                </div>
            </div>

            {/* Tasks & Results */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Tasks Panel */}
                <div className="glass-card p-6">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-lg font-semibold text-white">
                            Tasks ({taskPagination.total || tasks.length})
                        </h2>
                    </div>

                    <div className="space-y-2 max-h-96 overflow-y-auto">
                        {tasks.map((task) => (
                            <div
                                key={task.task_id}
                                onClick={() => setSelectedTask(task.task_id)}
                                className={`w-full text-left p-3 rounded-lg transition-colors cursor-pointer ${selectedTask === task.task_id
                                    ? 'bg-primary-600/20 border border-primary-500/30'
                                    : 'bg-dark-800 hover:bg-dark-700'
                                    }`}
                            >
                                <div className="flex items-center justify-between">
                                    <span className="text-sm text-dark-400">Task #{task.prompt_index}</span>
                                    <div className="flex items-center gap-2">
                                        <StatusBadge status={task.status} />
                                        <Link
                                            to={`/tasks/${task.task_id}`}
                                            onClick={(e) => e.stopPropagation()}
                                            className="text-primary-400 hover:text-primary-300 text-xs"
                                        >
                                            View →
                                        </Link>
                                    </div>
                                </div>
                                <p className="text-white text-sm mt-1 line-clamp-2">
                                    {task.prompt_text}
                                </p>
                                <div className="flex items-center gap-4 mt-2 text-xs text-dark-400">
                                    <span>✓ {task.completed_count}/{task.calls_per_prompt}</span>
                                </div>
                            </div>
                        ))}
                        {tasks.length === 0 && (
                            <p className="text-dark-400 text-center py-8">No tasks yet</p>
                        )}
                    </div>

                    {/* Task Pagination */}
                    {taskPagination.pages > 1 && (
                        <div className="flex items-center justify-center gap-2 mt-4">
                            <button
                                onClick={() => setTaskPage(p => p - 1)}
                                disabled={taskPage <= 1}
                                className="btn-secondary text-sm disabled:opacity-50"
                            >
                                ←
                            </button>
                            <span className="text-dark-400 text-sm">
                                {taskPage} / {taskPagination.pages}
                            </span>
                            <button
                                onClick={() => setTaskPage(p => p + 1)}
                                disabled={taskPage >= taskPagination.pages}
                                className="btn-secondary text-sm disabled:opacity-50"
                            >
                                →
                            </button>
                        </div>
                    )}
                </div>

                {/* Results Panel */}
                <div className="glass-card p-6">
                    <h2 className="text-lg font-semibold text-white mb-4">
                        Results {selectedTask && `(Task #${tasks.find(t => t.task_id === selectedTask)?.prompt_index || ''})`}
                    </h2>

                    <div className="overflow-x-auto max-h-96">
                        <table className="admin-table">
                            <thead>
                                <tr>
                                    <th>Call #</th>
                                    <th>Text Preview</th>
                                    <th>Sources</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {results.map((result) => (
                                    <tr key={result.result_id}>
                                        <td className="font-medium text-white">{result.call_index}</td>
                                        <td className="max-w-xs">
                                            <p className="text-sm text-dark-200 line-clamp-2">
                                                {result.text_preview || result.text?.slice(0, 80) || '-'}
                                            </p>
                                        </td>
                                        <td>
                                            {Array.isArray(result.sources) ? result.sources.length : 0}
                                        </td>
                                        <td>
                                            <Link
                                                to={`/results/${result.result_id}`}
                                                className="text-primary-400 hover:text-primary-300 text-sm"
                                            >
                                                View →
                                            </Link>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {results.length === 0 && (
                            <p className="text-dark-400 text-center py-8">
                                {selectedTask ? 'No results for this task' : 'Select a task to view results'}
                            </p>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
