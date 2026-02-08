import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { createRequest, getClients, getClient, getReports } from '../api/client';

export default function NewRequest() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Data for dropdowns
    const [clients, setClients] = useState([]);
    const [availablePeers, setAvailablePeers] = useState([]);
    const [reports, setReports] = useState([]);
    const [loadingData, setLoadingData] = useState(true);

    const [form, setForm] = useState({
        client_id: '',
        peers: [],
        report_id: searchParams.get('report_id') || '',
        topic: '',
        product: '',
        country: 'US',
        platform: 'chatgpt',
        intent: 'Solution Discovery',
        prompts_per_request: '5',
        calls_per_prompt: '10',
    });

    // Load clients and reports on mount
    useEffect(() => {
        loadData();
    }, []);

    async function loadData() {
        setLoadingData(true);
        try {
            const [clientsData, reportsData] = await Promise.all([
                getClients(),
                getReports()
            ]);
            setClients(clientsData);
            setReports(reportsData);

            // If report_id from URL, pre-select client from report
            const reportIdFromUrl = searchParams.get('report_id');
            if (reportIdFromUrl) {
                const report = reportsData.find(r => r.id === reportIdFromUrl);
                if (report && report.client_id) {
                    setForm(prev => ({ ...prev, client_id: report.client_id }));
                    // Fetch client peers
                    const client = clientsData.find(c => c.id === report.client_id);
                    if (client) {
                        setAvailablePeers(client.peers);
                    }
                }
            }
        } catch (err) {
            console.error('Failed to load data:', err);
        } finally {
            setLoadingData(false);
        }
    }

    // Update available peers when client changes
    async function handleClientChange(clientId) {
        setForm(prev => ({ ...prev, client_id: clientId, peers: [] }));

        if (clientId) {
            const client = clients.find(c => c.id === clientId);
            if (client) {
                setAvailablePeers(client.peers);
            }
        } else {
            setAvailablePeers([]);
        }
    }

    function handleChange(e) {
        const { name, value } = e.target;
        setForm(prev => ({
            ...prev,
            [name]: value,
        }));
    }

    function togglePeer(peer) {
        setForm(prev => ({
            ...prev,
            peers: prev.peers.includes(peer)
                ? prev.peers.filter(p => p !== peer)
                : [...prev.peers, peer]
        }));
    }

    function selectAllPeers() {
        setForm(prev => ({ ...prev, peers: [...availablePeers] }));
    }

    function clearPeers() {
        setForm(prev => ({ ...prev, peers: [] }));
    }

    // Parse number fields for submission
    function getSubmitData() {
        return {
            client_id: form.client_id,
            peers: form.peers,
            report_id: form.report_id || null,
            topic: form.topic || null,
            product: form.product || null,
            country: form.country,
            platform: form.platform,
            intent: form.intent,
            prompts_per_request: parseInt(form.prompts_per_request) || 5,
            calls_per_prompt: parseInt(form.calls_per_prompt) || 10,
        };
    }

    async function handleSubmit(e) {
        e.preventDefault();

        if (!form.client_id) {
            setError('Please select a client');
            return;
        }

        setLoading(true);
        setError(null);

        try {
            const result = await createRequest(getSubmitData());
            navigate(`/requests/${result.request_id}`);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    if (loadingData) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
        );
    }

    return (
        <div className="max-w-2xl mx-auto">
            <h1 className="text-2xl font-bold text-white mb-6">Create New Request</h1>

            <form onSubmit={handleSubmit} className="glass-card p-6 space-y-6">
                {error && (
                    <div className="p-4 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400">
                        {error}
                    </div>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Client Selection */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Client *
                        </label>
                        <select
                            value={form.client_id}
                            onChange={(e) => handleClientChange(e.target.value)}
                            className="input-field"
                            required
                        >
                            <option value="">Select a client...</option>
                            {clients.map((client) => (
                                <option key={client.id} value={client.id}>
                                    {client.name}
                                </option>
                            ))}
                        </select>
                        {clients.length === 0 && (
                            <p className="text-xs text-dark-400 mt-1">
                                No clients available. <a href="/clients" className="text-primary-400 hover:underline">Create one first</a>
                            </p>
                        )}
                    </div>

                    {/* Report Association */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Report (Optional)
                        </label>
                        <select
                            name="report_id"
                            value={form.report_id}
                            onChange={handleChange}
                            className="input-field"
                        >
                            <option value="">No report (standalone)</option>
                            {reports.filter(r => !form.client_id || r.client_id === form.client_id).map((report) => (
                                <option key={report.id} value={report.id}>
                                    {report.name}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* Peers Selection */}
                    <div className="md:col-span-2">
                        <div className="flex justify-between items-center mb-2">
                            <label className="block text-sm font-medium text-dark-300">
                                Competitors (Peers)
                            </label>
                            {availablePeers.length > 0 && (
                                <div className="flex gap-2">
                                    <button
                                        type="button"
                                        onClick={selectAllPeers}
                                        className="text-xs text-primary-400 hover:text-primary-300"
                                    >
                                        Select All
                                    </button>
                                    <button
                                        type="button"
                                        onClick={clearPeers}
                                        className="text-xs text-dark-400 hover:text-white"
                                    >
                                        Clear
                                    </button>
                                </div>
                            )}
                        </div>
                        {form.client_id ? (
                            availablePeers.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                    {availablePeers.map((peer) => (
                                        <button
                                            key={peer}
                                            type="button"
                                            onClick={() => togglePeer(peer)}
                                            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${form.peers.includes(peer)
                                                    ? 'bg-primary-600 text-white'
                                                    : 'bg-dark-700 text-dark-300 hover:bg-dark-600'
                                                }`}
                                        >
                                            {peer}
                                        </button>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-dark-400 text-sm">
                                    No peers configured for this client.{' '}
                                    <a href="/clients" className="text-primary-400 hover:underline">Add peers</a>
                                </p>
                            )
                        ) : (
                            <p className="text-dark-400 text-sm">Select a client first</p>
                        )}
                    </div>

                    {/* Topic */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Topic / Category
                        </label>
                        <input
                            type="text"
                            name="topic"
                            value={form.topic}
                            onChange={handleChange}
                            placeholder="e.g., Smart Home"
                            className="input-field"
                        />
                    </div>

                    {/* Product */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Product
                        </label>
                        <input
                            type="text"
                            name="product"
                            value={form.product}
                            onChange={handleChange}
                            placeholder="e.g., robot vacuums"
                            className="input-field"
                        />
                    </div>

                    {/* Country */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Country
                        </label>
                        <select
                            name="country"
                            value={form.country}
                            onChange={handleChange}
                            className="input-field"
                        >
                            <option value="US">United States</option>
                            <option value="GB">United Kingdom</option>
                            <option value="DE">Germany</option>
                            <option value="FR">France</option>
                            <option value="JP">Japan</option>
                            <option value="CN">China</option>
                        </select>
                    </div>

                    {/* Platform */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Platform
                        </label>
                        <select
                            name="platform"
                            value={form.platform}
                            onChange={handleChange}
                            className="input-field"
                        >
                            <option value="chatgpt">ChatGPT</option>
                            <option value="gemini">Gemini</option>
                            <option value="aimode">AI Mode</option>
                        </select>
                    </div>

                    {/* Intent */}
                    <div className="md:col-span-2">
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Intent
                        </label>
                        <select
                            name="intent"
                            value={form.intent}
                            onChange={handleChange}
                            className="input-field"
                        >
                            <option value="Solution Discovery">Solution Discovery</option>
                            <option value="Competitive Evaluation">Competitive Evaluation</option>
                            <option value="Specifics Inquiry">Specifics Inquiry</option>
                        </select>
                    </div>

                    {/* Prompts per Request */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Prompts per Request (N)
                        </label>
                        <input
                            type="number"
                            name="prompts_per_request"
                            value={form.prompts_per_request}
                            onChange={handleChange}
                            min="1"
                            max="100"
                            className="input-field"
                        />
                        <p className="text-xs text-dark-500 mt-1">How many prompts to generate</p>
                    </div>

                    {/* Calls per Prompt */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Calls per Prompt (M)
                        </label>
                        <input
                            type="number"
                            name="calls_per_prompt"
                            value={form.calls_per_prompt}
                            onChange={handleChange}
                            min="1"
                            max="10"
                            className="input-field"
                        />
                        <p className="text-xs text-dark-500 mt-1">How many API calls per prompt</p>
                    </div>
                </div>

                {/* Summary */}
                <div className="bg-dark-800 rounded-lg p-4">
                    <p className="text-dark-400 text-sm">
                        This will generate <span className="text-white font-medium">{form.prompts_per_request}</span> prompts,
                        each called <span className="text-white font-medium">{form.calls_per_prompt}</span> times =
                        <span className="text-primary-400 font-medium"> {form.prompts_per_request * form.calls_per_prompt} total results</span>
                    </p>
                </div>

                {/* Submit */}
                <div className="flex justify-end gap-4">
                    <button
                        type="button"
                        onClick={() => navigate('/requests')}
                        className="btn-secondary"
                    >
                        Cancel
                    </button>
                    <button
                        type="submit"
                        disabled={loading || !form.client_id}
                        className="btn-primary disabled:opacity-50"
                    >
                        {loading ? 'Creating...' : 'Create Request'}
                    </button>
                </div>
            </form>
        </div>
    );
}
