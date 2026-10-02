import { useState, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getRequests, triggerExpander } from '../api/client';

function StatusBadge({ status }) {
    const styles = {
        'PENDING': 'status-pending',
        'EXPANDING': 'status-running',
        'EXPANDED': 'status-running',
        'COMPLETED': 'status-completed',
        'EXPAND_FAILED': 'status-failed',
    };

    return (
        <span className={`px-2 py-1 text-xs font-medium rounded-full ${styles[status] || 'bg-dark-700 text-dark-300'}`}>
            {status}
        </span>
    );
}

export default function RequestsPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const [requests, setRequests] = useState([]);
    const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
    const [loading, setLoading] = useState(true);
    const [triggering, setTriggering] = useState(false);
    const [message, setMessage] = useState(null);

    const currentPage = parseInt(searchParams.get('page') || '1');
    const statusFilter = searchParams.get('status') || '';

    useEffect(() => {
        loadRequests();
    }, [currentPage, statusFilter]);

    async function loadRequests() {
        setLoading(true);
        try {
            const data = await getRequests(currentPage, 20, statusFilter || null);
            setRequests(data.data);
            setPagination(data.pagination);
        } catch (err) {
            console.error('Failed to load requests:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleTrigger() {
        setTriggering(true);
        setMessage(null);
        try {
            const result = await triggerExpander();
            setMessage({ type: 'success', text: result.message || 'Pipeline triggered successfully!' });
            loadRequests();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setTriggering(false);
        }
    }

    function setPage(page) {
        const params = new URLSearchParams(searchParams);
        params.set('page', page.toString());
        setSearchParams(params);
    }

    // Count pending requests
    const hasPending = requests.some(r => r.status === 'PENDING');

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Requests</h1>
                    <p className="text-dark-400 mt-1">
                        {pagination.total} total requests
                    </p>
                </div>
                <div className="flex gap-3">
                    <Link to="/requests/new" className="btn-secondary">
                        + New Request
                    </Link>
                    <button
                        onClick={handleTrigger}
                        disabled={triggering || !hasPending}
                        className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        {triggering ? (
                            <>
                                <span className="animate-spin">⏳</span>
                                Running...
                            </>
                        ) : (
                            <>▶ Run Pipeline</>
                        )}
                    </button>
                </div>
            </div>

            {/* Message */}
            {message && (
                <div className={`p-4 rounded-lg ${message.type === 'success'
                    ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                    : 'bg-red-500/20 text-red-400 border border-red-500/30'
                    }`}>
                    {message.text}
                </div>
            )}

            {/* Filters */}
            <div className="flex gap-2">
                {['', 'PENDING', 'EXPANDED', 'COMPLETED'].map((status) => (
                    <button
                        key={status}
                        onClick={() => {
                            const params = new URLSearchParams();
                            if (status) params.set('status', status);
                            setSearchParams(params);
                        }}
                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${statusFilter === status
                            ? 'bg-primary-600 text-white'
                            : 'bg-dark-800 text-dark-400 hover:text-white'
                            }`}
                    >
                        {status || 'All'}
                    </button>
                ))}
            </div>

            {/* Table */}
            <div className="glass-card overflow-hidden">
                {loading ? (
                    <div className="flex items-center justify-center h-48">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
                    </div>
                ) : (
                    <div className="table-scroll-container" id="tableScrollContainer">
                        <div
                            className="table-scroll-wrapper"
                            onScroll={(e) => {
                                const container = document.getElementById('tableScrollContainer');
                                const { scrollLeft, scrollWidth, clientWidth } = e.target;
                                const canScrollLeft = scrollLeft > 0;
                                const canScrollRight = scrollLeft < scrollWidth - clientWidth - 1;

                                container.classList.toggle('scroll-left', canScrollLeft);
                                container.classList.toggle('scroll-right', canScrollRight);
                            }}
                            ref={(el) => {
                                if (el) {
                                    const container = document.getElementById('tableScrollContainer');
                                    const canScrollRight = el.scrollWidth > el.clientWidth;
                                    container?.classList.toggle('scroll-right', canScrollRight);
                                }
                            }}
                        >
                            <table className="admin-table min-w-max">
                                <thead>
                                    <tr>
                                        <th className="sticky-col">Client</th>
                                        <th>Batch ID</th>
                                        <th>Peers</th>
                                        <th>Topic</th>
                                        <th>Product</th>
                                        <th>Platform</th>
                                        <th>Country</th>
                                        <th>Intent</th>
                                        <th>Status</th>
                                        <th>Tasks</th>
                                        <th>Created</th>
                                        <th></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {requests.map((req) => (
                                        <tr key={req.request_id}>
                                            <td className="sticky-col font-medium text-white whitespace-nowrap">
                                                {req.client_name}
                                            </td>
                                            <td className="text-dark-400 text-xs font-mono">
                                                {req.batch_id ? req.batch_id.slice(0, 8) : '-'}
                                            </td>
                                            <td className="text-dark-400 text-sm max-w-[150px] truncate" title={req.peers}>
                                                {req.peers || '-'}
                                            </td>
                                            <td className="whitespace-nowrap">{req.topic || '-'}</td>
                                            <td className="whitespace-nowrap">{req.product || '-'}</td>
                                            <td>
                                                <span className="px-2 py-1 bg-dark-800 rounded text-xs whitespace-nowrap">
                                                    {req.platform}
                                                </span>
                                            </td>
                                            <td>
                                                <span className="px-2 py-1 bg-dark-800 rounded text-xs">
                                                    {req.country || '-'}
                                                </span>
                                            </td>
                                            <td className="text-dark-400 text-sm whitespace-nowrap">{req.intent || '-'}</td>
                                            <td><StatusBadge status={req.status} /></td>
                                            <td>{req.task_count || 0}</td>
                                            <td className="text-dark-400 text-sm whitespace-nowrap">
                                                {new Date(req.created_at).toLocaleString('zh-CN', {
                                                    year: 'numeric',
                                                    month: '2-digit',
                                                    day: '2-digit',
                                                    hour: '2-digit',
                                                    minute: '2-digit',
                                                    second: '2-digit',
                                                    hour12: false
                                                })}
                                            </td>
                                            <td>
                                                <Link
                                                    to={`/requests/${req.request_id}`}
                                                    className="text-primary-400 hover:text-primary-300 whitespace-nowrap"
                                                >
                                                    View →
                                                </Link>
                                            </td>
                                        </tr>
                                    ))}
                                    {requests.length === 0 && (
                                        <tr>
                                            <td colSpan="12" className="text-center py-8 text-dark-400">
                                                No requests found
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </div>

            {/* Pagination */}
            {pagination.pages > 1 && (
                <div className="flex items-center justify-center gap-2">
                    <button
                        onClick={() => setPage(currentPage - 1)}
                        disabled={currentPage <= 1}
                        className="btn-secondary disabled:opacity-50"
                    >
                        ←
                    </button>
                    <span className="text-dark-400 px-4">
                        Page {currentPage} of {pagination.pages}
                    </span>
                    <button
                        onClick={() => setPage(currentPage + 1)}
                        disabled={currentPage >= pagination.pages}
                        className="btn-secondary disabled:opacity-50"
                    >
                        →
                    </button>
                </div>
            )}
        </div>
    );
}
