import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getStats } from '../api/client';

function StatCard({ title, value, icon, color, subtitle }) {
    return (
        <div className="glass-card p-6">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-dark-400 text-sm font-medium">{title}</p>
                    <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
                    {subtitle && <p className="text-dark-500 text-xs mt-1">{subtitle}</p>}
                </div>
                <div className={`text-4xl ${color} opacity-50`}>{icon}</div>
            </div>
        </div>
    );
}

export default function Dashboard() {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);

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
                    <p className="text-dark-400 mt-1">GEO Platform overview</p>
                </div>
                <Link to="/reports" className="btn-primary">
                    + New Report
                </Link>
            </div>

            {/* Stats Grid - Row 1: Clients & Reports */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <StatCard
                    title="Clients"
                    value={stats?.clients || 0}
                    icon="🏢"
                    color="text-purple-400"
                />
                <StatCard
                    title="Reports"
                    value={stats?.reports?.total || 0}
                    icon="📊"
                    color="text-cyan-400"
                    subtitle={stats?.reports?.analyzing > 0 ? `${stats.reports.analyzing} analyzing` : null}
                />
                <StatCard
                    title="Completed Reports"
                    value={stats?.reports?.completed || 0}
                    icon="✅"
                    color="text-green-400"
                />
            </div>

            {/* Stats Grid - Row 2: Pipeline Stats */}
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
                    icon="📈"
                    color="text-green-400"
                />
            </div>

            {/* Quick Links - Following recommended flow */}
            <div className="glass-card p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Quick Actions</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    <Link
                        to="/clients"
                        className="p-4 bg-dark-800 rounded-lg hover:bg-dark-700 transition-colors group"
                    >
                        <div className="text-2xl mb-2">🏢</div>
                        <h3 className="font-medium text-white group-hover:text-primary-400 transition-colors">
                            1. Manage Clients
                        </h3>
                        <p className="text-dark-400 text-sm mt-1">Add clients, peers & domains</p>
                    </Link>

                    <Link
                        to="/reports"
                        className="p-4 bg-dark-800 rounded-lg hover:bg-dark-700 transition-colors group"
                    >
                        <div className="text-2xl mb-2">📊</div>
                        <h3 className="font-medium text-white group-hover:text-primary-400 transition-colors">
                            2. Create Reports
                        </h3>
                        <p className="text-dark-400 text-sm mt-1">Set up analysis reports</p>
                    </Link>

                    <Link
                        to="/requests"
                        className="p-4 bg-dark-800 rounded-lg hover:bg-dark-700 transition-colors group"
                    >
                        <div className="text-2xl mb-2">📋</div>
                        <h3 className="font-medium text-white group-hover:text-primary-400 transition-colors">
                            3. Collect Data
                        </h3>
                        <p className="text-dark-400 text-sm mt-1">Create requests & run pipeline</p>
                    </Link>

                    <Link
                        to="/reports"
                        className="p-4 bg-dark-800 rounded-lg hover:bg-dark-700 transition-colors group"
                    >
                        <div className="text-2xl mb-2">🔬</div>
                        <h3 className="font-medium text-white group-hover:text-primary-400 transition-colors">
                            4. Run Analysis
                        </h3>
                        <p className="text-dark-400 text-sm mt-1">Trigger analyzer for reports</p>
                    </Link>
                </div>
            </div>
        </div>
    );
}
