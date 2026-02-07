import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getStats, triggerExpander } from '../api/client';

function StatCard({ title, value, icon, color }) {
    return (
        <div className="glass-card p-6">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-dark-400 text-sm font-medium">{title}</p>
                    <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
                </div>
                <div className={`text-4xl ${color} opacity-50`}>{icon}</div>
            </div>
        </div>
    );
}

export default function Dashboard() {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [triggering, setTriggering] = useState(false);
    const [message, setMessage] = useState(null);

    useEffect(() => {
        loadStats();
    }, []);

    async function loadStats() {
        try {
            const data = await getStats();
            setStats(data);
        } catch (err) {
            console.error('Failed to load stats:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleTrigger() {
        setTriggering(true);
        setMessage(null);
        try {
            const result = await triggerExpander();
            setMessage({ type: 'success', text: result.message || 'Expander triggered successfully!' });
            // Refresh stats after trigger
            loadStats();
        } catch (err) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setTriggering(false);
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
        );
    }

    return (
        <div className="space-y-8">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-white">Dashboard</h1>
                    <p className="text-dark-400 mt-1">GEO Collector pipeline overview</p>
                </div>
                <div className="flex gap-3">
                    <Link to="/requests/new" className="btn-secondary">
                        + New Request
                    </Link>
                    <button
                        onClick={handleTrigger}
                        disabled={triggering || (stats?.requests?.pending === 0)}
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

            {/* Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                <StatCard
                    title="Total Requests"
                    value={stats?.requests?.total || 0}
                    icon="📋"
                    color="text-white"
                />
                <StatCard
                    title="Pending"
                    value={stats?.requests?.pending || 0}
                    icon="⏳"
                    color="text-yellow-400"
                />
                <StatCard
                    title="Tasks"
                    value={stats?.tasks || 0}
                    icon="📦"
                    color="text-blue-400"
                />
                <StatCard
                    title="Results"
                    value={stats?.results || 0}
                    icon="✅"
                    color="text-green-400"
                />
            </div>

            {/* Quick Links */}
            <div className="glass-card p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Quick Actions</h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Link
                        to="/requests"
                        className="p-4 bg-dark-800 rounded-lg hover:bg-dark-700 transition-colors group"
                    >
                        <div className="text-2xl mb-2">📋</div>
                        <h3 className="font-medium text-white group-hover:text-primary-400 transition-colors">
                            View All Requests
                        </h3>
                        <p className="text-dark-400 text-sm mt-1">Manage and monitor requests</p>
                    </Link>

                    <Link
                        to="/requests/new"
                        className="p-4 bg-dark-800 rounded-lg hover:bg-dark-700 transition-colors group"
                    >
                        <div className="text-2xl mb-2">➕</div>
                        <h3 className="font-medium text-white group-hover:text-primary-400 transition-colors">
                            Create Request
                        </h3>
                        <p className="text-dark-400 text-sm mt-1">Add a new GEO request</p>
                    </Link>

                    <Link
                        to="/requests?status=PENDING"
                        className="p-4 bg-dark-800 rounded-lg hover:bg-dark-700 transition-colors group"
                    >
                        <div className="text-2xl mb-2">⏳</div>
                        <h3 className="font-medium text-white group-hover:text-primary-400 transition-colors">
                            Pending Requests
                        </h3>
                        <p className="text-dark-400 text-sm mt-1">View requests awaiting processing</p>
                    </Link>
                </div>
            </div>
        </div>
    );
}
