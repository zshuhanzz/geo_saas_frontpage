import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createRequest } from '../api/client';

export default function NewRequest() {
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const [form, setForm] = useState({
        client_name: '',
        peers: '',
        topic: '',
        product: '',
        country: 'US',
        platform: 'chatgpt',
        intent: 'Solution Discovery',
        prompts_per_request: '5',
        calls_per_prompt: '10',
    });

    function handleChange(e) {
        const { name, value } = e.target;
        setForm(prev => ({
            ...prev,
            [name]: value,
        }));
    }

    // Parse number fields for submission
    function getSubmitData() {
        return {
            ...form,
            prompts_per_request: parseInt(form.prompts_per_request) || 5,
            calls_per_prompt: parseInt(form.calls_per_prompt) || 10,
        };
    }

    async function handleSubmit(e) {
        e.preventDefault();

        if (!form.client_name.trim()) {
            setError('Client name is required');
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
                    {/* Client Name */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Client Name *
                        </label>
                        <input
                            type="text"
                            name="client_name"
                            value={form.client_name}
                            onChange={handleChange}
                            placeholder="e.g., RoboRock"
                            className="input-field"
                            required
                        />
                    </div>

                    {/* Peers */}
                    <div>
                        <label className="block text-sm font-medium text-dark-300 mb-2">
                            Competitors
                        </label>
                        <input
                            type="text"
                            name="peers"
                            value={form.peers}
                            onChange={handleChange}
                            placeholder="e.g., Eufy, iRobot"
                            className="input-field"
                        />
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
                        disabled={loading}
                        className="btn-primary disabled:opacity-50"
                    >
                        {loading ? 'Creating...' : 'Create Request'}
                    </button>
                </div>
            </form>
        </div>
    );
}
