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

    return response.json();
}

// Stats
export async function getStats() {
    return fetchJSON(`${API_BASE}/stats`);
}

// Requests
export async function getRequests(page = 1, limit = 20, status = null) {
    let url = `${API_BASE}/requests?page=${page}&limit=${limit}`;
    if (status) url += `&status=${status}`;
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
