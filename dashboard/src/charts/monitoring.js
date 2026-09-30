import { formatDate } from '../utils/data-loader';

export function renderMonitoringView(monitoringData) {
    const wrapper = document.getElementById('tableSiteMonitoring');
    if (!wrapper) return;

    if (!monitoringData || monitoringData.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет данных для мониторинга 🌍</div>';
        return;
    }

    // Sort by status (down first) and then by expiry date (soonest first)
    monitoringData.sort((a, b) => {
        if (a.status !== b.status) return a.status === 'down' ? -1 : 1;
        
        const timeA = a.expiryDate && a.expiryDate !== 'Unknown' && a.expiryDate !== 'Error' ? new Date(a.expiryDate).getTime() : Infinity;
        const timeB = b.expiryDate && b.expiryDate !== 'Unknown' && b.expiryDate !== 'Error' ? new Date(b.expiryDate).getTime() : Infinity;
        
        return timeA - timeB;
    });

    let html = '<table class="dash-table"><thead><tr><th>Сайт / Клиент</th><th>Домен</th><th>Статус</th><th>Окончание домена / SSL</th><th>PageSpeed (M/D)</th><th>Обновлено</th></tr></thead><tbody>';

    monitoringData.forEach(site => {
        const isUp = site.status === 'up';
        const pingBadge = isUp 
            ? '<span class="badge badge--success" title="200 OK">UP 🟢</span>' 
            : '<span class="badge badge--danger" title="Недоступен">DOWN 🔴</span>';
        
        // Format Domain Expiration
        let domainDisplay = 'Unknown';
        let domainColor = 'var(--text-muted)';
        if (site.domainExpiryDate && site.domainExpiryDate !== 'Unknown' && site.domainExpiryDate !== 'Error') {
            const expDate = new Date(site.domainExpiryDate);
            const daysObj = Math.floor((expDate - new Date()) / (1000 * 60 * 60 * 24));
            
            if (daysObj < 7) {
                domainColor = 'var(--danger)';
                domainDisplay = `${formatDate(site.domainExpiryDate)} (${daysObj} дн.)`;
            } else if (daysObj < 30) {
                domainColor = 'var(--warning)';
                domainDisplay = `${formatDate(site.domainExpiryDate)} (${daysObj} дн.)`;
            } else {
                domainColor = 'var(--success)';
                domainDisplay = formatDate(site.domainExpiryDate);
            }
        } else if (site.domainExpiryDate === 'Error') {
            domainColor = 'var(--danger)';
            domainDisplay = 'Ошибка WHOIS';
        }

        // Format SSL Expiration (legacy field 'expiryDate')
        let sslDisplay = 'Unknown';
        let sslColor = 'var(--text-muted)';
        if (site.expiryDate && site.expiryDate !== 'Unknown' && site.expiryDate !== 'Error') {
            const expDate = new Date(site.expiryDate);
            const daysObj = Math.floor((expDate - new Date()) / (1000 * 60 * 60 * 24));
            
            if (daysObj < 7) {
                sslColor = 'var(--danger)';
                sslDisplay = `${formatDate(site.expiryDate)} (${daysObj} дн.)`;
            } else if (daysObj < 30) {
                sslColor = 'var(--warning)';
                sslDisplay = `${formatDate(site.expiryDate)} (${daysObj} дн.)`;
            } else {
                sslColor = 'var(--success)';
                sslDisplay = formatDate(site.expiryDate);
            }
        } else if (site.expiryDate === 'Error') {
            sslColor = 'var(--danger)';
            sslDisplay = 'Ошибка SSL';
        }

        const updatedDate = new Date(site.lastChecked);
        const timeString = updatedDate.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });

        // PageSpeed Indicator
        let pageSpeedHtml = '<span style="color:var(--text-muted); font-size:0.85em;">N/A</span>';
        if (site.pageSpeed && (site.pageSpeed.mobile || site.pageSpeed.desktop)) {
            const mScore = site.pageSpeed.mobile || '-';
            const dScore = site.pageSpeed.desktop || '-';
            
            const getColor = (score) => {
                if (score === '-') return 'var(--text-muted)';
                if (score >= 90) return 'var(--success)';
                if (score >= 50) return 'var(--warning)';
                return 'var(--danger)';
            };

            pageSpeedHtml = `
                <div style="display:flex; gap: 8px; align-items:center;">
                    <div style="display:flex; align-items:center; gap:4px; font-weight:600; color:${getColor(mScore)}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line></svg>
                        ${mScore}
                    </div>
                    <div style="display:flex; align-items:center; gap:4px; font-weight:600; color:${getColor(dScore)}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
                        ${dScore}
                    </div>
                </div>
            `;
        }

        let domainColHtml = `<a href="${site.url}" target="_blank" style="color:var(--text-primary); text-decoration:none;">${site.domain}</a>`;
        if (site.exposedFiles && site.exposedFiles.length > 0) {
            domainColHtml += `
                <div style="color:var(--danger); font-size:0.75em; margin-top:4px; font-weight:600; display:flex; align-items:center; gap:4px;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                    Уязвимость: открыт ${site.exposedFiles.join(', ')}
                </div>
            `;
        }

        html += `
            <tr>
                <td><strong>${site.name}</strong></td>
                <td>${domainColHtml}</td>
                <td>${pingBadge}</td>
                <td>
                    <div style="font-size:0.85em; line-height: 1.4;">
                        <div>🌐 Домен: <strong style="color:${domainColor}">${domainDisplay}</strong></div>
                        <div style="margin-top: 2px;">🔐 SSL: <strong style="color:${sslColor}">${sslDisplay}</strong></div>
                    </div>
                </td>
                <td>${pageSpeedHtml}</td>
                <td style="color:var(--text-muted); font-size:0.85em;">${timeString}</td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    wrapper.innerHTML = html;
}
