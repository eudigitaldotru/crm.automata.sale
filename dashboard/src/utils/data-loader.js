/**
 * data-loader.js
 * Loads dashboard data.json from the local data directory.
 * In development: Vite serves /data/data.json as static asset.
 */

let _cachedData = null;

export async function loadData() {
    const response = await fetch('/data/data.json?t=' + Date.now());
    if (!response.ok) throw new Error(`Failed to load data.json: ${response.status}`);
    _cachedData = await response.json();
    return _cachedData;
}

export function formatRub(value) {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat('ru-RU', {
        style: 'currency',
        currency: 'RUB',
        maximumFractionDigits: 0,
    }).format(value);
}

export function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const [y, m, d] = dateStr.split('-');
        return `${d}.${m}.${y}`;
    } catch {
        return dateStr;
    }
}

export function daysUntil(dateStr) {
    if (!dateStr) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(dateStr);
    target.setHours(0, 0, 0, 0);
    return Math.round((target - today) / 86400000);
}
