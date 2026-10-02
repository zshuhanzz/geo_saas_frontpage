import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getResult } from '../api/client';

function InfoCard({ label, value, fullWidth = false }) {
    return (
        <div className={fullWidth ? 'col-span-full' : ''}>
            <p className="text-dark-400 text-sm">{label}</p>
            <p className="text-white font-medium whitespace-pre-wrap">{value || '-'}</p>
        </div>
    );
}

function CollapsibleSection({ title, count, children, defaultOpen = false }) {
    const [open, setOpen] = useState(defaultOpen);

    return (
        <div className="border border-dark-700 rounded-lg overflow-hidden">
            <button
                onClick={() => setOpen(!open)}
                className="w-full px-4 py-3 bg-dark-800 flex items-center justify-between hover:bg-dark-700 transition-colors"
            >
                <span className="font-medium text-white">{title}</span>
                <div className="flex items-center gap-2">
                    <span className="text-primary-400 text-sm">{count} items</span>
                    <span className="text-dark-400">{open ? '▼' : '▶'}</span>
                </div>
            </button>
            {open && (
                <div className="p-4 bg-dark-900">
                    {children}
                </div>
            )}
        </div>
    );
}

function SourceItem({ source, index }) {
    return (
        <div className="bg-dark-800 rounded-lg p-3 space-y-2">
            <div className="flex items-start justify-between gap-2">
                <span className="text-primary-400 text-sm font-medium">[{index + 1}]</span>
                <a
                    href={source.url || source.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary-400 hover:text-primary-300 text-sm truncate flex-1"
                >
                    {source.url || source.link || 'No URL'}
                </a>
            </div>
            {source.title && (
                <p className="text-white text-sm font-medium">{source.title}</p>
            )}
            {source.snippet && (
                <p className="text-dark-300 text-sm">{source.snippet}</p>
            )}
        </div>
    );
}

function ShoppingCard({ card, index }) {
    return (
        <div className="bg-dark-800 rounded-lg p-3 space-y-2">
            <div className="flex items-center gap-2">
                <span className="text-green-400 text-sm">🛒</span>
                <span className="text-white font-medium">{card.title || card.name || `Product ${index + 1}`}</span>
            </div>
            {card.price && (
                <p className="text-green-400 font-bold">{card.price}</p>
            )}
            {card.description && (
                <p className="text-dark-300 text-sm">{card.description}</p>
            )}
            {card.url && (
                <a
                    href={card.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary-400 hover:text-primary-300 text-sm"
                >
                    View Product →
                </a>
            )}
        </div>
    );
}

export default function ResultDetail() {
    const { resultId } = useParams();
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadResult();
    }, [resultId]);

    async function loadResult() {
        try {
            const data = await getResult(resultId);
            setResult(data);
        } catch (err) {
            console.error('Failed to load result:', err);
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

    if (!result) {
        return (
            <div className="text-center py-12">
                <h2 className="text-xl text-white">Result not found</h2>
                <Link to="/requests" className="text-primary-400 mt-4 inline-block">← Back to Requests</Link>
            </div>
        );
    }

    const sources = Array.isArray(result.sources) ? result.sources : [];
    const shoppingCards = Array.isArray(result.shopping_cards) ? result.shopping_cards : [];
    const searchQueries = Array.isArray(result.search_queries) ? result.search_queries : [];
    const entities = Array.isArray(result.entities) ? result.entities : [];
    const places = Array.isArray(result.places) ? result.places : [];
    const citationPills = Array.isArray(result.citation_pills) ? result.citation_pills : [];

    return (
        <div className="space-y-6">
            {/* Breadcrumb */}
            <div className="flex items-center gap-2 text-sm">
                <Link to="/requests" className="text-dark-400 hover:text-white">Requests</Link>
                <span className="text-dark-600">/</span>
                <Link to={`/tasks/${result.task_id}`} className="text-dark-400 hover:text-white">
                    Task
                </Link>
                <span className="text-dark-600">/</span>
                <span className="text-white">Result #{result.call_index}</span>
            </div>

            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold text-white">Result #{result.result_id}</h1>
                <p className="text-dark-400 mt-1">Call {result.call_index} • {result.platform}</p>
            </div>

            {/* Metadata */}
            <div className="glass-card p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Metadata</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                    <InfoCard label="Task ID" value={result.task_id} />
                    <InfoCard label="Cloro Task ID" value={result.cloro_task_id} />
                    <InfoCard label="Platform" value={result.platform} />
                    <InfoCard label="Call Index" value={result.call_index} />
                    <InfoCard label="Client" value={result.client_name} />
                    <InfoCard label="Country" value={result.country} />
                    <InfoCard label="HTTP Status" value={result.http_status_code} />
                    <InfoCard label="Latency" value={result.latency_ms ? `${result.latency_ms}ms` : '-'} />
                </div>
            </div>

            {/* Text Content */}
            <div className="glass-card p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Response Text</h2>
                <div className="bg-dark-800 rounded-lg p-4 max-h-96 overflow-y-auto">
                    <p className="text-white whitespace-pre-wrap">{result.text || 'No text content'}</p>
                </div>
            </div>

            {/* Prompt */}
            {result.prompt_text && (
                <div className="glass-card p-6">
                    <h2 className="text-lg font-semibold text-white mb-4">Original Prompt</h2>
                    <div className="bg-dark-800 rounded-lg p-4">
                        <p className="text-dark-200">{result.prompt_text}</p>
                    </div>
                </div>
            )}

            {/* Structured Data */}
            <div className="glass-card p-6 space-y-4">
                <h2 className="text-lg font-semibold text-white mb-4">Structured Data</h2>

                {/* Sources */}
                <CollapsibleSection title="Sources" count={sources.length} defaultOpen={sources.length > 0 && sources.length <= 5}>
                    {sources.length > 0 ? (
                        <div className="space-y-3">
                            {sources.map((source, idx) => (
                                <SourceItem key={idx} source={source} index={idx} />
                            ))}
                        </div>
                    ) : (
                        <p className="text-dark-400">No sources</p>
                    )}
                </CollapsibleSection>

                {/* Shopping Cards */}
                <CollapsibleSection title="Shopping Cards" count={shoppingCards.length}>
                    {shoppingCards.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {shoppingCards.map((card, idx) => (
                                <ShoppingCard key={idx} card={card} index={idx} />
                            ))}
                        </div>
                    ) : (
                        <p className="text-dark-400">No shopping cards</p>
                    )}
                </CollapsibleSection>

                {/* Search Queries */}
                <CollapsibleSection title="Search Queries" count={searchQueries.length}>
                    {searchQueries.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                            {searchQueries.map((query, idx) => (
                                <span key={idx} className="px-3 py-1 bg-dark-800 rounded-full text-sm text-white">
                                    {typeof query === 'string' ? query : query.query || JSON.stringify(query)}
                                </span>
                            ))}
                        </div>
                    ) : (
                        <p className="text-dark-400">No search queries</p>
                    )}
                </CollapsibleSection>

                {/* Entities */}
                <CollapsibleSection title="Entities" count={entities.length}>
                    {entities.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                            {entities.map((entity, idx) => (
                                <span key={idx} className="px-3 py-1 bg-primary-600/20 border border-primary-500/30 rounded-full text-sm text-primary-300">
                                    {typeof entity === 'string' ? entity : entity.name || JSON.stringify(entity)}
                                </span>
                            ))}
                        </div>
                    ) : (
                        <p className="text-dark-400">No entities</p>
                    )}
                </CollapsibleSection>

                {/* Places */}
                <CollapsibleSection title="Places" count={places.length}>
                    {places.length > 0 ? (
                        <div className="space-y-2">
                            {places.map((place, idx) => (
                                <div key={idx} className="bg-dark-800 rounded-lg p-3">
                                    <p className="text-white font-medium">{place.name || `Place ${idx + 1}`}</p>
                                    {place.address && <p className="text-dark-400 text-sm">{place.address}</p>}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-dark-400">No places</p>
                    )}
                </CollapsibleSection>

                {/* Citation Pills */}
                <CollapsibleSection title="Citation Pills" count={citationPills.length}>
                    {citationPills.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                            {citationPills.map((pill, idx) => (
                                <span key={idx} className="px-2 py-1 bg-yellow-500/20 border border-yellow-500/30 rounded text-xs text-yellow-300">
                                    {typeof pill === 'string' ? pill : pill.text || JSON.stringify(pill)}
                                </span>
                            ))}
                        </div>
                    ) : (
                        <p className="text-dark-400">No citation pills</p>
                    )}
                </CollapsibleSection>
            </div>

            {/* Raw Response (collapsible) */}
            <div className="glass-card p-6">
                <CollapsibleSection title="Raw Cloro Response" count={1}>
                    <pre className="text-xs text-dark-300 overflow-x-auto max-h-96 overflow-y-auto">
                        {JSON.stringify(result.cloro_response, null, 2)}
                    </pre>
                </CollapsibleSection>
            </div>
        </div>
    );
}
