// src/apiClient.js

// Using Vite environment variables or fallback to localhost
export const API_BASE = import.meta.env?.VITE_API_URL || 'http://localhost:8001/api';

/**
 * Universal client for interacting with the AUTOMATA-OS FastAPI backend.
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
            let errorMsg = 'API HTTP Error';
            try {
                const errorData = await res.json();
                errorMsg = errorData.message || errorData.detail || errorMsg;
            } catch(e) {}
            throw new Error(`[${res.status}] ${errorMsg}`);
        }

        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            const json = await res.json();
            // Handle custom ApiError / ApiSuccess wrapper
            if (json.ok === false) {
                throw new Error(`${json.message || json.code || 'Unknown API Error'}`);
            }
            // If it's the unified format, return data
            if (json.ok === true && json.data !== undefined) {
                return json.data;
            }
            return json;
        } else {
            return await res.text();
        }
    } catch (err) {
        console.warn(`[API Call Failed] ${endpoint}`, err);
        
        // Fallback for /data endpoint
        if (endpoint === '/data' && (!options.method || options.method === 'GET')) {
            console.warn('API server down, falling back to data.json');
            try {
                const fallbackRes = await fetch('/data/data.json');
                if (fallbackRes.ok) {
                    return await fallbackRes.json();
                }
            } catch (fallbackErr) {
                console.error('[Fallback Failed]', fallbackErr);
            }
        }
        
        throw err;
    }
}

export const automataApi = {
    getData: () => fetchApi('/data'),
    refreshSystem: () => fetchApi('/system/refresh', { method: 'POST' }),
    refreshDashboard: () => fetchApi('/refresh', { method: 'POST' }),
    remindInvoice: (id) => fetchApi(`/invoice/${id}/remind`, { method: 'POST' }),
    closeTask: (id, hours) => fetchApi(`/tasks/${encodeURIComponent(id)}/close`, { method: 'POST', body: JSON.stringify({ hours }) }),
    getEntitySchemas: () => fetchApi('/entities/schema'),
    createEntity: (type, data) => fetchApi(`/entities/${encodeURIComponent(type)}`, { method: 'POST', body: JSON.stringify({ data }) }),
    generateContract: (payload) => fetchApi('/contracts/generate', { method: 'POST', body: JSON.stringify(payload) }),
    getContractAppendices: () => fetchApi('/contracts/appendices'),
    exportContract: (file) => fetchApi('/contracts/export', { method: 'POST', body: JSON.stringify({ file }) }),
    getInvoicePdfUrl: (number, doc) => `${API_BASE}/invoice/${number}/pdf?doc=${doc}`,
    generateInvoiceDoc: (number, doc) => fetchApi(`/invoice/${number}/generate?doc=${doc}`, { method: 'POST' }),
    emailPreview: (number) => fetchApi(`/invoice/${number}/email-preview`),
    sendInvoiceEmail: (number) => fetchApi(`/invoice/${number}/send-email`, { method: 'POST' }),
    regenerateInvoicePdf: (number, doc) => fetchApi(`/invoice/${number}/regenerate?doc=${doc}`, { method: 'POST' }),
    getTemplate: (name) => fetchApi(`/templates/${name}`),
    saveTemplate: (name, content) => fetchApi(`/templates/${name}`, { method: 'POST', body: JSON.stringify({ content }) }),
    tgPreview: (number) => fetchApi(`/invoice/${number}/tg-preview`),
    sendInvoiceTelegram: (number) => fetchApi(`/invoice/${number}/send-telegram`, { method: 'POST' }),
    syncTasks: () => fetchApi('/sync-tasks', { method: 'POST' }),
    getSystemStatus: () => fetchApi('/system/status'),
    getSystemLogs: () => fetchApi('/system/logs'),
    runAction: (action) => fetchApi(`/actions/run?action=${action}`, { method: 'POST' }),
    getStatus: () => fetchApi('/status'),
    getIntegrationsStatus: () => fetchApi('/integrations/status'),
    startService: (service) => fetchApi('/start-service', { method: 'POST', body: JSON.stringify({ service }) }),
    refreshMonitoring: () => fetchApi('/refresh-monitoring', { method: 'POST' }),
    refreshGeo: () => fetchApi('/refresh-geo', { method: 'POST' })
};
