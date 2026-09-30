import { formatDate } from '../utils/data-loader';

/**
 * Рендерит секцию GEO/SEO-аудитов.
 * @param {Array} geoData — массив объектов из /data/geo.json (по домену)
 */
export function renderGeoView(geoData) {
    const wrapper = document.getElementById('tableGeo');
    if (!wrapper) return;

    if (!geoData || geoData.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет данных GEO-аудитов 🔍</div>';
        return;
    }

    // Только домены с метриками аудита (остальные — «не аудировались»)
    const audited = geoData.filter(d => d.overallScore !== null && d.overallScore !== undefined);
    const notAudited = geoData.filter(d => d.overallScore === null || d.overallScore === undefined);

    // KPI-сводка (только по аудированным)
    let kpiHtml = '';
    if (audited.length > 0) {
        const avgVisibility = audited.reduce((s, d) => s + (d.honestVisibility ?? 0), 0) / audited.length;
        const avgScore = audited.reduce((s, d) => s + (d.overallScore ?? 0), 0) / audited.length;
        const totalMentions = audited.reduce((s, d) => s + (d.mentionedCount ?? 0), 0);
        const totalThirdParty = audited.reduce((s, d) => s + (d.thirdPartyMentioned ?? 0), 0);

        const visColor = avgVisibility >= 30 ? 'var(--success)' : avgVisibility >= 10 ? 'var(--warning)' : 'var(--danger)';
        const scoreColor = avgScore >= 50 ? 'var(--success)' : avgScore >= 25 ? 'var(--warning)' : 'var(--danger)';

        kpiHtml = `
        <section class="kpi-row" style="margin-bottom: 16px;">
            <div class="kpi-card">
                <div class="kpi-label">Visibility (честный)</div>
                <div class="kpi-value" style="color:${visColor}">${avgVisibility.toFixed(1)}%</div>
                <div class="kpi-sub" style="color:var(--text-muted)">среднее по ${audited.length} проектам</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Overall Score</div>
                <div class="kpi-value" style="color:${scoreColor}">${avgScore.toFixed(1)}<span style="font-size:0.6em;color:var(--text-muted)">/100</span></div>
                <div class="kpi-sub" style="color:var(--text-muted)">взвешенная оценка</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Сторонних упоминаний</div>
                <div class="kpi-value" style="color:${totalThirdParty > 0 ? 'var(--success)' : 'var(--danger)'}">${totalThirdParty}</div>
                <div class="kpi-sub" style="color:var(--text-muted)">из ${totalMentions} всего</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Проектов с аудитом</div>
                <div class="kpi-value" style="color:var(--accent)">${audited.length}<span style="font-size:0.6em;color:var(--text-muted)">/${geoData.length}</span></div>
                <div class="kpi-sub" style="color:var(--text-muted)">${notAudited.length} ожидают</div>
            </div>
        </section>`;
    }

    // Таблица проектов
    let tableHtml = '<table class="dash-table"><thead><tr><th>Проект / Бренд</th><th>Домен</th><th>Visibility</th><th>Score</th><th>SoV</th><th>Топ-конкуренты</th><th>Аудит</th></tr></thead><tbody>';

    // Сортировка: аудированные сначала (по score), потом остальные
    const sorted = [...audited].sort((a, b) => (b.overallScore ?? 0) - (a.overallScore ?? 0));
    for (const d of sorted) {
        const vis = d.honestVisibility ?? 0;
        const score = d.overallScore ?? 0;
        const sov = d.honestShareOfVoice ?? d.shareOfVoice ?? 0;
        const visColor = vis >= 30 ? 'var(--success)' : vis >= 10 ? 'var(--warning)' : 'var(--danger)';
        const scoreColor = score >= 50 ? 'var(--success)' : score >= 25 ? 'var(--warning)' : 'var(--danger)';

        const competitors = (d.topCompetitors || []).slice(0, 3)
            .map(c => `<span style="color:var(--text-secondary); font-size:0.85em;">${c.name} <strong style="color:var(--accent)">${c.mentions}</strong></span>`)
            .join(', ');

        const auditDate = d.analyzedAt ? formatDate(d.analyzedAt) : '—';

        tableHtml += `
            <tr>
                <td><strong>${d.brand || d.name}</strong></td>
                <td><a href="${d.url}" target="_blank" style="color:var(--text-primary); text-decoration:none;">${d.domain}</a></td>
                <td><strong style="color:${visColor}">${vis}%</strong></td>
                <td><strong style="color:${scoreColor}">${score}</strong></td>
                <td>${sov}%</td>
                <td>${competitors || '<span style="color:var(--text-muted)">—</span>'}</td>
                <td style="color:var(--text-muted); font-size:0.85em;">${auditDate}</td>
            </tr>`;
    }
    for (const d of notAudited) {
        tableHtml += `
            <tr style="opacity:0.5;">
                <td>${d.brand || d.name}</td>
                <td><a href="${d.url}" target="_blank" style="color:var(--text-secondary); text-decoration:none;">${d.domain}</a></td>
                <td colspan="5" style="color:var(--text-muted); font-style:italic;">Аудит не проводился</td>
            </tr>`;
    }
    tableHtml += '</tbody></table>';

    // Чеклисты (по проектам, у которых есть задачи)
    const withChecklists = geoData.filter(d => d.checklist && d.checklist.length > 0);
    let checklistHtml = '';
    if (withChecklists.length > 0) {
        checklistHtml = '<h3 style="margin-top:24px; color:var(--text-secondary); text-transform:uppercase; font-size:0.9rem;">📋 Чеклисты GEO-задач</h3>';
        for (const d of withChecklists) {
            const tasks = d.checklist;
            const done = tasks.filter(t => t.status === 'done').length;
            const total = tasks.length;
            const progress = total > 0 ? Math.round((done / total) * 100) : 0;
            const progressColor = progress >= 50 ? 'var(--success)' : progress >= 25 ? 'var(--warning)' : 'var(--danger)';

            checklistHtml += `
                <div style="margin-top:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <strong style="color:var(--text-primary);">${d.brand || d.name}</strong>
                        <span style="color:${progressColor}; font-weight:600; font-size:0.85em;">${done}/${total} (${progress}%)</span>
                    </div>
                    <div style="background:var(--bg-glass); border-radius:8px; height:6px; overflow:hidden; margin-bottom:8px;">
                        <div style="background:${progressColor}; height:100%; width:${progress}%; transition:width 0.3s;"></div>
                    </div>
                    <table class="dash-table" style="font-size:0.85em;">
                        <tbody>`;

            for (const t of tasks) {
                const statusIcon = t.status === 'done'
                    ? '<span style="color:var(--success); font-weight:700;">✓</span>'
                    : t.status === 'in_progress'
                    ? '<span style="color:var(--warning);">◐</span>'
                    : '<span style="color:var(--text-muted);">○</span>';
                const prioBadge = t.priority === 'P0'
                    ? '<span class="badge badge--danger" style="font-size:0.75em;">P0</span>'
                    : t.priority === 'P1'
                    ? '<span class="badge badge--warning" style="font-size:0.75em;">P1</span>'
                    : '<span class="badge badge--gray" style="font-size:0.75em;">P2</span>';
                const rowStyle = t.status === 'done' ? 'opacity:0.5; text-decoration:line-through;' : '';

                checklistHtml += `
                    <tr style="${rowStyle}">
                        <td style="width:30px;">${statusIcon}</td>
                        <td style="width:40px;">${prioBadge}</td>
                        <td>${t.name || t.id}</td>
                    </tr>`;
            }
            checklistHtml += '</tbody></table></div>';
        }
    }

    wrapper.innerHTML = kpiHtml + tableHtml + checklistHtml;
}
