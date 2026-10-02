import { useState, useEffect } from 'react';
import { getClients, createClient, deleteClient, addPeer, removePeer, addDomain, removeDomain } from '../api/client';

export default function ClientsPage() {
    const [clients, setClients] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showNewClient, setShowNewClient] = useState(false);
    const [newClientName, setNewClientName] = useState('');
    const [selectedClient, setSelectedClient] = useState(null);
    const [newPeer, setNewPeer] = useState('');
    const [newDomain, setNewDomain] = useState('');
    const [searchTerm, setSearchTerm] = useState('');

    useEffect(() => {
        loadClients();
    }, []);

    async function loadClients() {
        setLoading(true);
        try {
            const data = await getClients(searchTerm);
            setClients(data);
        } catch (err) {
            console.error('Failed to load clients:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleCreateClient(e) {
        e.preventDefault();
        if (!newClientName.trim()) return;
        try {
            await createClient({ name: newClientName, peers: [], domains: [] });
            setNewClientName('');
            setShowNewClient(false);
            loadClients();
        } catch (err) {
            console.error('Failed to create client:', err);
            alert('Failed to create client: ' + err.message);
        }
    }

    async function handleDeleteClient(clientId) {
        if (!confirm('Are you sure you want to delete this client?')) return;
        try {
            await deleteClient(clientId);
            setSelectedClient(null);
            loadClients();
        } catch (err) {
            console.error('Failed to delete client:', err);
        }
    }

    async function handleAddPeer(clientId) {
        if (!newPeer.trim()) return;
        try {
            await addPeer(clientId, newPeer);
            setNewPeer('');
            loadClients();
            // Update selected client
            const updated = clients.find(c => c.id === clientId);
            if (updated) setSelectedClient({ ...updated, peers: [...updated.peers, newPeer] });
        } catch (err) {
            console.error('Failed to add peer:', err);
            alert('Failed to add peer: ' + err.message);
        }
    }

    async function handleRemovePeer(clientId, peerName) {
        try {
            await removePeer(clientId, peerName);
            loadClients();
        } catch (err) {
            console.error('Failed to remove peer:', err);
        }
    }

    async function handleAddDomain(clientId) {
        if (!newDomain.trim()) return;
        try {
            await addDomain(clientId, newDomain);
            setNewDomain('');
            loadClients();
        } catch (err) {
            console.error('Failed to add domain:', err);
            alert('Failed to add domain: ' + err.message);
        }
    }

    async function handleRemoveDomain(clientId, domain) {
        try {
            await removeDomain(clientId, domain);
            loadClients();
        } catch (err) {
            console.error('Failed to remove domain:', err);
        }
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Clients</h1>
                    <p className="text-dark-400 mt-1">
                        Manage clients, their competitors, and owned domains
                    </p>
                </div>
                <button
                    onClick={() => setShowNewClient(true)}
                    className="btn-primary"
                >
                    + New Client
                </button>
            </div>

            {/* Search */}
            <div className="flex gap-4">
                <input
                    type="text"
                    placeholder="Search clients..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && loadClients()}
                    className="flex-1 px-4 py-2 bg-dark-800 border border-dark-700 rounded-lg text-white placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
                <button onClick={loadClients} className="btn-secondary">
                    Search
                </button>
            </div>

            {/* New Client Modal */}
            {showNewClient && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
                    <div className="bg-dark-800 rounded-xl p-6 w-full max-w-md">
                        <h2 className="text-xl font-bold text-white mb-4">New Client</h2>
                        <form onSubmit={handleCreateClient}>
                            <input
                                type="text"
                                placeholder="Client name (e.g., Eufy)"
                                value={newClientName}
                                onChange={(e) => setNewClientName(e.target.value)}
                                className="w-full px-4 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
                                autoFocus
                            />
                            <div className="flex justify-end gap-3 mt-4">
                                <button
                                    type="button"
                                    onClick={() => setShowNewClient(false)}
                                    className="btn-secondary"
                                >
                                    Cancel
                                </button>
                                <button type="submit" className="btn-primary">
                                    Create
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Clients Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Clients List */}
                <div className="glass-card">
                    <h2 className="text-lg font-semibold text-white mb-4">All Clients</h2>
                    {loading ? (
                        <div className="flex items-center justify-center h-32">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
                        </div>
                    ) : clients.length === 0 ? (
                        <p className="text-dark-400 text-center py-8">No clients found</p>
                    ) : (
                        <div className="space-y-2">
                            {clients.map((client) => (
                                <div
                                    key={client.id}
                                    onClick={() => setSelectedClient(client)}
                                    className={`p-4 rounded-lg cursor-pointer transition-colors ${selectedClient?.id === client.id
                                            ? 'bg-primary-600/20 border border-primary-500'
                                            : 'bg-dark-700/50 hover:bg-dark-700 border border-transparent'
                                        }`}
                                >
                                    <div className="flex justify-between items-center">
                                        <span className="text-white font-medium">{client.name}</span>
                                        <div className="flex gap-2 text-xs text-dark-400">
                                            <span>{client.peers.length} peers</span>
                                            <span>{client.domains.length} domains</span>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Client Detail */}
                <div className="glass-card">
                    {selectedClient ? (
                        <div className="space-y-6">
                            <div className="flex justify-between items-start">
                                <div>
                                    <h2 className="text-xl font-bold text-white">{selectedClient.name}</h2>
                                    <p className="text-dark-400 text-sm mt-1">Client ID: {selectedClient.id}</p>
                                </div>
                                <button
                                    onClick={() => handleDeleteClient(selectedClient.id)}
                                    className="text-red-400 hover:text-red-300 text-sm"
                                >
                                    Delete
                                </button>
                            </div>

                            {/* Peers Section */}
                            <div>
                                <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wider mb-3">
                                    Competitors (Peers)
                                </h3>
                                <div className="flex flex-wrap gap-2 mb-3">
                                    {selectedClient.peers.map((peer) => (
                                        <span
                                            key={peer}
                                            className="inline-flex items-center gap-1 px-3 py-1 bg-dark-700 rounded-full text-sm text-white"
                                        >
                                            {peer}
                                            <button
                                                onClick={() => handleRemovePeer(selectedClient.id, peer)}
                                                className="ml-1 text-dark-400 hover:text-red-400"
                                            >
                                                ×
                                            </button>
                                        </span>
                                    ))}
                                    {selectedClient.peers.length === 0 && (
                                        <span className="text-dark-400 text-sm">No peers added</span>
                                    )}
                                </div>
                                <div className="flex gap-2">
                                    <input
                                        type="text"
                                        placeholder="Add peer name..."
                                        value={newPeer}
                                        onChange={(e) => setNewPeer(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleAddPeer(selectedClient.id)}
                                        className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white text-sm placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
                                    />
                                    <button
                                        onClick={() => handleAddPeer(selectedClient.id)}
                                        className="btn-secondary text-sm"
                                    >
                                        Add
                                    </button>
                                </div>
                            </div>

                            {/* Domains Section */}
                            <div>
                                <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wider mb-3">
                                    Owned Domains
                                </h3>
                                <div className="flex flex-wrap gap-2 mb-3">
                                    {selectedClient.domains.map((d) => (
                                        <span
                                            key={d.domain}
                                            className="inline-flex items-center gap-1 px-3 py-1 bg-dark-700 rounded-full text-sm text-white"
                                        >
                                            {d.domain}
                                            <button
                                                onClick={() => handleRemoveDomain(selectedClient.id, d.domain)}
                                                className="ml-1 text-dark-400 hover:text-red-400"
                                            >
                                                ×
                                            </button>
                                        </span>
                                    ))}
                                    {selectedClient.domains.length === 0 && (
                                        <span className="text-dark-400 text-sm">No domains added</span>
                                    )}
                                </div>
                                <div className="flex gap-2">
                                    <input
                                        type="text"
                                        placeholder="Add domain (e.g., eufy.com)..."
                                        value={newDomain}
                                        onChange={(e) => setNewDomain(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleAddDomain(selectedClient.id)}
                                        className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white text-sm placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
                                    />
                                    <button
                                        onClick={() => handleAddDomain(selectedClient.id)}
                                        className="btn-secondary text-sm"
                                    >
                                        Add
                                    </button>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="flex items-center justify-center h-64 text-dark-400">
                            Select a client to view details
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
