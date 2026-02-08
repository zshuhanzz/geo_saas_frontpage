import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getReport, getAnalysisStatus, getMentions, getCitations, getFilterOptions } from '../api/client';

function Pagination({ page, pages, onPageChange }) {
    if (pages <= 1) return null;

    return (
        <div className="flex items-center justify-center gap-2 mt-4">
            <button
                onClick={() => onPageChange(page - 1)}
                disabled={page <= 1}
                className="px-3 py-1 bg-dark-700 text-dark-300 rounded disabled:opacity-50"
            >
                ← Prev
            </button>
            <span className="text-dark-400">
                Page {page} of {pages}
            </span>
            <button
                onClick={() => onPageChange(page + 1)}
                disabled={page >= pages}
                className="px-3 py-1 bg-dark-700 text-dark-300 rounded disabled:opacity-50"
            >
                Next →
            </button>
        </div>
    );
}

function FilterBar({ options, filters, onFilterChange }) {
    return (
        <div className="flex flex-wrap gap-3 mb-4 p-4 bg-dark-800/50 rounded-lg">
            <select
                value={filters.platform || ''}
                onChange={(e) => onFilterChange({ ...filters, platform: e.target.value })}
                className="px-3 py-1.5 bg-dark-700 border border-dark-600 rounded text-sm text-white"
            >
                <option value="">All Platforms</option>
                {options.platforms?.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <select
                value={filters.intent || ''}
                onChange={(e) => onFilterChange({ ...filters, intent: e.target.value })}
                className="px-3 py-1.5 bg-dark-700 border border-dark-600 rounded text-sm text-white"
            >
                <option value="">All Intents</option>
                {options.intents?.map(i => <option key={i} value={i}>{i}</option>)}
            </select>
            <select
                value={filters.topic || ''}
                onChange={(e) => onFilterChange({ ...filters, topic: e.target.value })}
                className="px-3 py-1.5 bg-dark-700 border border-dark-600 rounded text-sm text-white"
            >
                <option value="">All Topics</option>
                {options.topics?.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select
                value={filters.product || ''}
                onChange={(e) => onFilterChange({ ...filters, product: e.target.value })}
                className="px-3 py-1.5 bg-dark-700 border border-dark-600 rounded text-sm text-white"
            >
                <option value="">All Products</option>
                {options.products?.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <select
                value={filters.country || ''}
                onChange={(e) => onFilterChange({ ...filters, country: e.target.value })}
                className="px-3 py-1.5 bg-dark-700 border border-dark-600 rounded text-sm text-white"
            >
                <option value="">All Countries</option>
                {options.countries?.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            {Object.values(filters).some(v => v) && (
                <button
                    onClick={() => onFilterChange({})}
                    className="text-sm text-dark-400 hover:text-white"
                >
                    Clear Filters
                </button>
            )}
        </div>
    );
}

export default function ReportDetailPage() {
    const { id: reportId } = useParams();
    const [report, setReport] = useState(null);
    const [analysisStatus, setAnalysisStatus] = useState(null);
    const [filterOptions, setFilterOptions] = useState({});
    const [activeTab, setActiveTab] = useState('mentions');
    const [loading, setLoading] = useState(true);

    // Mentions state
    const [mentions, setMentions] = useState([]);
    const [mentionsPage, setMentionsPage] = useState(1);
    const [mentionsPagination, setMentionsPagination] = useState({});
    const [mentionsFilters, setMentionsFilters] = useState({});
    const [mentionsLoading, setMentionsLoading] = useState(false);

    // Citations state
    const [citations, setCitations] = useState([]);
    const [citationsPage, setCitationsPage] = useState(1);
    const [citationsPagination, setCitationsPagination] = useState({});
    const [citationsFilters, setCitationsFilters] = useState({});
    const [citationsLoading, setCitationsLoading] = useState(false);

    useEffect(() => {
        loadReportData();
    }, [reportId]);

    useEffect(() => {
        if (reportId) loadMentions();
    }, [reportId, mentionsPage, mentionsFilters]);

    useEffect(() => {
        if (reportId) loadCitations();
    }, [reportId, citationsPage, citationsFilters]);

    async function loadReportData() {
        setLoading(true);
        try {
            const [reportData, statusData, optionsData] = await Promise.all([
                getReport(reportId),
                getAnalysisStatus(reportId),
                getFilterOptions(reportId),
            ]);
            setReport(reportData);
            setAnalysisStatus(statusData);
            setFilterOptions(optionsData);
        } catch (err) {
            console.error('Failed to load report:', err);
        } finally {
            setLoading(false);
        }
    }

    async function loadMentions() {
        setMentionsLoading(true);
        try {
            const result = await getMentions(reportId, mentionsPage, 50, mentionsFilters);
            setMentions(result.data || []);
            setMentionsPagination(result.pagination || {});
        } catch (err) {
            console.error('Failed to load mentions:', err);
        } finally {
            setMentionsLoading(false);
        }
    }

    async function loadCitations() {
        setCitationsLoading(true);
        try {
            const result = await getCitations(reportId, citationsPage, 50, citationsFilters);
            setCitations(result.data || []);
            setCitationsPagination(result.pagination || {});
        } catch (err) {
            console.error('Failed to load citations:', err);
        } finally {
            setCitationsLoading(false);
        }
    }

    function handleMentionsFilterChange(newFilters) {
        setMentionsFilters(newFilters);
        setMentionsPage(1);
    }

    function handleCitationsFilterChange(newFilters) {
        setCitationsFilters(newFilters);
        setCitationsPage(1);
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
        );
    }

    if (!report) {
        return (
            <div className="text-center py-12 text-dark-400">
                <p>Report not found</p>
                <Link to="/reports" className="text-primary-400 hover:text-primary-300 mt-4 inline-block">
                    ← Back to Reports
                </Link>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <div className="flex items-center gap-3">
                        <Link to="/reports" className="text-dark-400 hover:text-white">
                            ← Reports
                        </Link>
                    </div>
                    <h1 className="text-2xl font-bold text-white mt-2">{report.name}</h1>
                    <p className="text-dark-400 mt-1">
                        Client: {report.client_name}
                    </p>
                </div>
            </div>

            {/* Stats */}
            {analysisStatus && (
                <div className="grid grid-cols-3 gap-4">
                    <div className="glass-card p-4">
                        <p className="text-dark-400 text-sm">Total Results</p>
                        <p className="text-2xl font-bold text-white">{analysisStatus.total_results}</p>
                    </div>
                    <div className="glass-card p-4">
                        <p className="text-dark-400 text-sm">Analyzed</p>
                        <p className="text-2xl font-bold text-green-400">{analysisStatus.analyzed_results}</p>
                    </div>
                    <div className="glass-card p-4">
                        <p className="text-dark-400 text-sm">Pending</p>
                        <p className="text-2xl font-bold text-yellow-400">{analysisStatus.pending_results}</p>
                    </div>
                </div>
            )}

            {/* Tabs */}
            <div className="border-b border-dark-700">
                <div className="flex gap-6">
                    <button
                        onClick={() => setActiveTab('mentions')}
                        className={`py-3 border-b-2 transition-colors ${activeTab === 'mentions'
                                ? 'border-primary-500 text-white'
                                : 'border-transparent text-dark-400 hover:text-white'
                            }`}
                    >
                        Company Mentions
                        {mentionsPagination.total > 0 && (
                            <span className="ml-2 text-xs bg-dark-700 px-2 py-0.5 rounded-full">
                                {mentionsPagination.total}
                            </span>
                        )}
                    </button>
                    <button
                        onClick={() => setActiveTab('citations')}
                        className={`py-3 border-b-2 transition-colors ${activeTab === 'citations'
                                ? 'border-primary-500 text-white'
                                : 'border-transparent text-dark-400 hover:text-white'
                            }`}
                    >
                        Citations
                        {citationsPagination.total > 0 && (
                            <span className="ml-2 text-xs bg-dark-700 px-2 py-0.5 rounded-full">
                                {citationsPagination.total}
                            </span>
                        )}
                    </button>
                </div>
            </div>

            {/* Content */}
            {activeTab === 'mentions' && (
                <div>
                    <FilterBar
                        options={filterOptions}
                        filters={mentionsFilters}
                        onFilterChange={handleMentionsFilterChange}
                    />

                    <div className="glass-card overflow-hidden">
                        {mentionsLoading ? (
                            <div className="flex items-center justify-center h-32">
                                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-500"></div>
                            </div>
                        ) : mentions.length === 0 ? (
                            <div className="text-center py-12 text-dark-400">
                                No company mentions found
                            </div>
                        ) : (
                            <>
                                <table className="w-full text-sm">
                                    <thead className="bg-dark-800/50">
                                        <tr>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Company</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Position</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Type</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Platform</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Intent</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Topic</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Product</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-dark-700">
                                        {mentions.map((m, idx) => (
                                            <tr key={m.id || idx} className="hover:bg-dark-800/30">
                                                <td className="px-3 py-2 text-white font-medium">{m.company_name}</td>
                                                <td className="px-3 py-2 text-dark-300">#{m.mention_position}</td>
                                                <td className="px-3 py-2">
                                                    {m.is_client && <span className="text-green-400">Client</span>}
                                                    {m.is_peer && <span className="text-yellow-400">Peer</span>}
                                                    {!m.is_client && !m.is_peer && <span className="text-dark-500">Other</span>}
                                                </td>
                                                <td className="px-3 py-2 text-dark-300">{m.platform}</td>
                                                <td className="px-3 py-2 text-dark-300">{m.intent}</td>
                                                <td className="px-3 py-2 text-dark-300">{m.topic}</td>
                                                <td className="px-3 py-2 text-dark-300">{m.product}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                <Pagination
                                    page={mentionsPage}
                                    pages={mentionsPagination.pages}
                                    onPageChange={setMentionsPage}
                                />
                            </>
                        )}
                    </div>
                </div>
            )}

            {activeTab === 'citations' && (
                <div>
                    <FilterBar
                        options={filterOptions}
                        filters={citationsFilters}
                        onFilterChange={handleCitationsFilterChange}
                    />

                    <div className="glass-card overflow-hidden">
                        {citationsLoading ? (
                            <div className="flex items-center justify-center h-32">
                                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-500"></div>
                            </div>
                        ) : citations.length === 0 ? (
                            <div className="text-center py-12 text-dark-400">
                                No citations found
                            </div>
                        ) : (
                            <>
                                <table className="w-full text-sm">
                                    <thead className="bg-dark-800/50">
                                        <tr>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Domain</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Category</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Pill</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Platform</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">Intent</th>
                                            <th className="px-3 py-2 text-left text-xs font-medium text-dark-400 uppercase">URL</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-dark-700">
                                        {citations.map((c, idx) => (
                                            <tr key={c.id || idx} className="hover:bg-dark-800/30">
                                                <td className="px-3 py-2 text-white font-medium">{c.source_domain}</td>
                                                <td className="px-3 py-2">
                                                    <span className={c.domain_category === 'Owned' ? 'text-green-400' : 'text-dark-300'}>
                                                        {c.domain_category}
                                                    </span>
                                                </td>
                                                <td className="px-3 py-2">
                                                    {c.is_citation_pill ? (
                                                        <span className="text-primary-400">Yes</span>
                                                    ) : (
                                                        <span className="text-dark-500">No</span>
                                                    )}
                                                </td>
                                                <td className="px-3 py-2 text-dark-300">{c.platform}</td>
                                                <td className="px-3 py-2 text-dark-300">{c.intent}</td>
                                                <td className="px-3 py-2">
                                                    <a
                                                        href={c.source_url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="text-primary-400 hover:text-primary-300 truncate block max-w-xs"
                                                        title={c.source_url}
                                                    >
                                                        {c.source_url?.slice(0, 40)}...
                                                    </a>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                <Pagination
                                    page={citationsPage}
                                    pages={citationsPagination.pages}
                                    onPageChange={setCitationsPage}
                                />
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
