// src/hooks/useApi.js

const API_BASE = 'http://localhost:8000/api';

/**
 * Universal hook for interacting with the AUTOMATA-OS FastAPI backend.
 */
export async function fetchApi(endpoint, options = {}) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {})
            }
        });

        if (!res.ok) {
            let errorMsg = 'API Error';
            try {
                const errorData = await res.json();
                errorMsg = errorData.detail || errorMsg;
            } catch(e) {}
            throw new Error(`[${res.status}] ${errorMsg}`);
        }

        return await res.json();
    } catch (err) {
        console.error(`[API Call Failed] ${endpoint}`, err);
        throw err;
    }
}

export const automataApi = {
    getData: () => fetchApi('/data'),
    refreshSystem: () => fetchApi('/system/refresh', { method: 'POST' }),
    remindInvoice: (id) => fetchApi(`/invoice/${id}/remind`, { method: 'POST' })
};
