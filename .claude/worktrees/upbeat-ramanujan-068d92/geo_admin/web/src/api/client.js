/**
 * API client for GEO Admin backend
 */
// In production, use VITE_API_URL; in dev, use local proxy (empty string)
const API_BASE = (import.meta.env.VITE_API_URL || '') + '/api';

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }

    // Handle 204 No Content
    if (response.status === 204) {
        return null;
    }

    return response.json();
}

// Stats
export async function getStats() {
    return fetchJSON(`${API_BASE}/stats`);
}

// ============== Clients ==============
export async function getClients(search = '') {
    let url = `${API_BASE}/clients`;
    if (search) url += `?search=${encodeURIComponent(search)}`;
    return fetchJSON(url);
}

export async function getClient(clientId) {
    return fetchJSON(`${API_BASE}/clients/${clientId}`);
}

export async function createClient(data) {
    return fetchJSON(`${API_BASE}/clients`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function deleteClient(clientId) {
    return fetchJSON(`${API_BASE}/clients/${clientId}`, {
        method: 'DELETE',
    });
}

export async function addPeer(clientId, peerName) {
    return fetchJSON(`${API_BASE}/clients/${clientId}/peers`, {
        method: 'POST',
        body: JSON.stringify({ peer_name: peerName }),
    });
}

export async function removePeer(clientId, peerName) {
    return fetchJSON(`${API_BASE}/clients/${clientId}/peers/${encodeURIComponent(peerName)}`, {
        method: 'DELETE',
    });
}

export async function addDomain(clientId, domain) {
    return fetchJSON(`${API_BASE}/clients/${clientId}/domains`, {
        method: 'POST',
        body: JSON.stringify({ domain, is_primary: false }),
    });
}

export async function removeDomain(clientId, domain) {
    return fetchJSON(`${API_BASE}/clients/${clientId}/domains/${encodeURIComponent(domain)}`, {
        method: 'DELETE',
    });
}

// ============== Reports ==============
export async function getReports(clientId = null, status = null) {
    let url = `${API_BASE}/reports`;
    const params = [];
    if (clientId) params.push(`client_id=${clientId}`);
    if (status) params.push(`status=${status}`);
    if (params.length) url += `?${params.join('&')}`;
    return fetchJSON(url);
}

export async function getReport(reportId) {
    return fetchJSON(`${API_BASE}/reports/${reportId}`);
}

export async function createReport(data) {
    return fetchJSON(`${API_BASE}/reports`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function deleteReport(reportId) {
    return fetchJSON(`${API_BASE}/reports/${reportId}`, {
        method: 'DELETE',
    });
}

export async function analyzeReport(reportId) {
    return fetchJSON(`${API_BASE}/reports/${reportId}/analyze`, {
        method: 'POST',
    });
}

// ============== Requests ==============
export async function getRequests(page = 1, limit = 20, status = null, reportId = null, clientId = null) {
    let url = `${API_BASE}/requests?page=${page}&limit=${limit}`;
    if (status) url += `&status=${status}`;
    if (reportId) url += `&report_id=${reportId}`;
    if (clientId) url += `&client_id=${clientId}`;
    return fetchJSON(url);
}

export async function getRequest(requestId) {
    return fetchJSON(`${API_BASE}/requests/${requestId}`);
}

export async function createRequest(data) {
    return fetchJSON(`${API_BASE}/requests`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function triggerExpander() {
    return fetchJSON(`${API_BASE}/requests/trigger`, {
        method: 'POST',
    });
}

// Tasks
export async function getTasks(requestId, page = 1, limit = 20) {
    return fetchJSON(`${API_BASE}/requests/${requestId}/tasks?page=${page}&limit=${limit}`);
}

export async function getTask(taskId) {
    return fetchJSON(`${API_BASE}/tasks/${taskId}`);
}

// Results
export async function getResults(taskId, page = 1, limit = 20) {
    return fetchJSON(`${API_BASE}/tasks/${taskId}/results?page=${page}&limit=${limit}`);
}

export async function getResult(resultId) {
    return fetchJSON(`${API_BASE}/results/${resultId}`);
}

// ============== Analysis ==============
export async function getAnalysisStatus(reportId) {
    return fetchJSON(`${API_BASE}/analysis/status/${reportId}`);
}

export async function getMentions(reportId, page = 1, limit = 50, filters = {}) {
    let url = `${API_BASE}/analysis/mentions?report_id=${reportId}&page=${page}&limit=${limit}`;
    if (filters.platform) url += `&platform=${encodeURIComponent(filters.platform)}`;
    if (filters.intent) url += `&intent=${encodeURIComponent(filters.intent)}`;
    if (filters.topic) url += `&topic=${encodeURIComponent(filters.topic)}`;
    if (filters.product) url += `&product=${encodeURIComponent(filters.product)}`;
    if (filters.country) url += `&country=${encodeURIComponent(filters.country)}`;
    return fetchJSON(url);
}

export async function getCitations(reportId, page = 1, limit = 50, filters = {}) {
    let url = `${API_BASE}/analysis/citations?report_id=${reportId}&page=${page}&limit=${limit}`;
    if (filters.platform) url += `&platform=${encodeURIComponent(filters.platform)}`;
    if (filters.intent) url += `&intent=${encodeURIComponent(filters.intent)}`;
    if (filters.topic) url += `&topic=${encodeURIComponent(filters.topic)}`;
    if (filters.product) url += `&product=${encodeURIComponent(filters.product)}`;
    if (filters.country) url += `&country=${encodeURIComponent(filters.country)}`;
    return fetchJSON(url);
}

export async function getFilterOptions(reportId) {
    return fetchJSON(`${API_BASE}/analysis/filter-options/${reportId}`);
}

