/**
 * main.js
 * Main entry point for the Vite dashboard app
 */
import { automataApi, API_BASE } from './apiClient';
import { loadData, formatRub, formatDate, daysUntil } from './utils/data-loader';
import { showToast } from './utils/toast';
import { initMailTab } from './mail.js';
import { renderRevenueChart } from './charts/revenue.js?v=20260914c';
import { renderTariffsChart } from './charts/tariffs.js?v=20260914c';
import { renderForecastChart } from './charts/forecast.js?v=20260914c';
import { renderLeadSources } from './charts/lead-sources.js?v=20260914c';
import { renderLeadFunnel } from './charts/lead-funnel';
import { renderPipeline } from './charts/pipeline';
import { renderCreditChart } from './charts/credit';
import { renderTopClientsChart } from './charts/top-clients.js?v=20260914c';
import { renderInboxChart } from './charts/inbox.js?v=20260914c';
import { renderMonitoringView } from './charts/monitoring';
import { renderGeoView } from './charts/geo';
import { renderExpensesChart } from './charts/expenses';
import { initTeamBoard } from './teamBoard';
import { initHologram } from './hologram/hologram.js';

async function init() {
    const refreshBtn = document.getElementById('refreshBtn');
    const lastUpdated = document.getElementById('lastUpdated');

    refreshBtn.addEventListener('click', () => {
        refreshBtn.style.pointerEvents = 'none';
        refreshBtn.style.opacity = '0.5';
        fetchData();
    });

    const syncTasksBtn = document.getElementById('syncTasksBtn');
    if (syncTasksBtn) {
        syncTasksBtn.addEventListener('click', syncTasks);
    }

    setupHelpModals();
    setupKpiPayers();
    setupTabs();
    setupSystemTab();
    setupPdSafe();
    initSlaInvoiceButton();
    initTemplatesButton();
    initChatUI();
    initIntegrationsStatus();
    initSiteAudit();
    initCreateEntityButtons();
    initClientsDirectory();
    initTeamBoard();
    initMailTab();
    initHologram();

    await fetchData();
}

function setupTabs() {
    const tabs = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');

    // URL-маршрутизация: #tab-id или #tab-id/element-id (открывает вкладку
    // и прокручивает к блоку — на это ведут редиректы из мокапа Заметки/index.html)
    if (!activateFromHash()) {
        const savedTab = localStorage.getItem('activeTab') || 'tab-chat';
        activateTab(savedTab);
    }
    window.addEventListener('hashchange', activateFromHash);

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabId = tab.getAttribute('data-tab');
            activateTab(tabId);
            localStorage.setItem('activeTab', tabId);
            history.replaceState(null, '', `#${tabId}`);
        });
    });

    function activateFromHash() {
        const hash = decodeURIComponent(location.hash.slice(1));
        if (!hash) return false;
        const [tabId, anchorId] = hash.split('/');
        const tabBtn = document.querySelector(`.tab-btn[data-tab="${CSS.escape(tabId)}"]`);
        if (!tabBtn || !document.getElementById(tabId)) return false;
        activateTab(tabId);
        localStorage.setItem('activeTab', tabId);
        if (anchorId) {
            setTimeout(() => {
                document.getElementById(anchorId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 80);
        }
        return true;
    }

    function activateTab(tabId) {
        tabs.forEach(t => t.classList.remove('active'));
        contents.forEach(c => c.classList.remove('active'));
        
        const targetTab = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
        const targetContent = document.getElementById(tabId);
        
        if (targetTab && targetContent) {
            targetTab.classList.add('active');
            targetContent.classList.add('active');
        } else {
            document.querySelector('.tab-btn[data-tab="tab-today"]')?.classList.add('active');
            document.getElementById('tab-today')?.classList.add('active');
        }
    }
}

function setupSystemTab() {
    const btnSystemStatus = document.getElementById('btnSystemStatus');
    if (btnSystemStatus) {
        btnSystemStatus.addEventListener('click', async () => {
            const list = document.getElementById('systemStatusList');
            list.innerHTML = 'Обновление...';
            await renderIntegrationsStatus();
        });
        // Auto-load on init
        setTimeout(() => btnSystemStatus.click(), 1000);
    }
    
    const btnSystemLogs = document.getElementById('btnSystemLogs');
    if (btnSystemLogs) {
        btnSystemLogs.addEventListener('click', async () => {
            const box = document.getElementById('systemLogsBox');
            box.innerHTML = 'Загрузка логов...';
            try {
                const text = await automataApi.getSystemLogs();
                box.innerHTML = text.replace(/\\n/g, '<br>');
                box.scrollTop = box.scrollHeight;
            } catch(e) {
                box.innerHTML = '<span style="color:var(--danger)">Ошибка загрузки логов</span>';
            }
        });
        // Auto-load on init
        setTimeout(() => btnSystemLogs.click(), 1500);
    }
}

async function fetchData() {
    const refreshBtn = document.getElementById('refreshBtn');
    const lastUpdated = document.getElementById('lastUpdated');

    try {
        console.log('🔄 Fetching dashboard data...');
        lastUpdated.textContent = 'Обновление данных...';

        const data = await automataApi.getData();
        lastDashboardData = data;
        console.log('✅ Data loaded successfully');

        populateKPIs(data.meta);
        renderRevenueChart(data.meta.revenue_monthly_series);
        renderTariffsChart(data.meta.support_plan_distribution);
        renderForecastChart(data.meta.forecast);
        renderCreditChart(data.meta.credit_summary);
        renderTopClientsChart(data.meta.top_clients_revenue);
        renderInboxChart(data.inbox);
        renderExpensesChart(data.expenses);



        let monitoringData = [];
        try {
            // Using time query to bust cache
            const monRes = await fetch('/data/monitoring.json?t=' + Date.now());
            if (monRes.ok) monitoringData = await monRes.json();
        } catch(e) { console.error('Failed to load monitoring data', e); }

        let geoData = [];
        try {
            const geoRes = await fetch('/data/geo.json?t=' + Date.now());
            if (geoRes.ok) geoData = await geoRes.json();
        } catch(e) { console.error('Failed to load geo data', e); }

        populateUnpaidTable(data.meta.unpaid_invoices);
        populateRenewalsTable(data.meta.upcoming_renewals);
        populateCreditsTable(data.credits, data.meta.credit_summary);
        populateSLASupportMatrix(data.clients, data.invoices);
        
        // Stage 5 Charts
        renderLeadSources(data.meta.lead_sources);
        renderLeadFunnel(data.meta.lead_funnel);
        renderPipeline(data.meta.pipeline);

        populateSupportMatrix(data.meta.support_matrix, 'supportMatrix');
        populateSupportMatrix(data.meta.not_regular_matrix, 'notRegularMatrix');
        populateAllClientsTable(data.clients);
        populateEisenhowerMatrix(data.meta.tasks_matrix);
        renderMonitoringView(monitoringData);
        renderGeoView(geoData);
        if (data.goals) {
            renderGoals(data.goals);
        }

        setupManagementButtons();

        if (data.meta.tickets) {
            populateSlaTimers(data.meta.tickets);
        }

        // Новые лиды (из TG-Gateway и др.)
        if (data.leads) {
            populateLeadsTable(data.leads);
        }
        
        // 3. Update Service Statuses
        await updateServiceStatus();

        lastUpdated.textContent = `Обновлено: ${new Date().toLocaleTimeString('ru-RU')}`;
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        lastUpdated.textContent = 'Ошибка загрузки данных';
    } finally {
        refreshBtn.style.pointerEvents = 'auto';
        refreshBtn.style.opacity = '1';
    }
}

function renderGoals(goals) {
    const container = document.getElementById('goalsContainer');
    if (!container) return;
    
    if (!goals || goals.length === 0) {
        container.innerHTML = '<div class="empty-state">Нет активных целей 🎯</div>';
        return;
    }
    
    let html = '';
    goals.forEach(g => {
        let pct = 0;
        let colorClass = 'bg-primary';
        
        if (g.direction === 'decrease') {
            // For decrease: progress = (target / current) or similar? 
            // Usually, progress is what % of the gap is covered.
            // Simplified: if current <= target it's 100%. 
            // If current is double target, it's 0%.
            // Or just current value relative to starting value. Since we don't have start value, let's just do a simple ratio.
            if (g.current_value <= g.target_value) {
                pct = 100;
                colorClass = 'bg-success';
            } else {
                // mock logic for decrease: target / current
                pct = Math.max(0, Math.min(100, Math.round((g.target_value / g.current_value) * 100)));
            }
        } else {
            if (g.current_value >= g.target_value) {
                pct = 100;
                colorClass = 'bg-success';
            } else {
                pct = Math.max(0, Math.min(100, Math.round((g.current_value / g.target_value) * 100)));
            }
        }
        
        const formatVal = (v) => {
            if (g.unit === '₽') return new Intl.NumberFormat('ru-RU').format(v) + ' ₽';
            if (g.unit === '%') return v + '%';
            return v + ' ' + g.unit;
        };

        const goalPath = encodeURIComponent(g.file_path || '55_Goals/' + g.id + '.md');
        
        html += `
            <div class="kpi-card" style="align-items: flex-start; cursor: pointer;" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${goalPath}')">
                <div style="width: 100%;">
                    <div style="display:flex; justify-content:space-between; margin-bottom: 8px;">
                        <span style="font-weight: 600;">${g.title}</span>
                        <span style="font-size: 0.9em; color: var(--text-muted);">${formatVal(g.current_value)} / ${formatVal(g.target_value)}</span>
                    </div>
                    <div style="width: 100%; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; width: ${pct}%; background: ${colorClass === 'bg-success' ? 'var(--success)' : 'var(--primary)'}; border-radius: 4px; transition: width 0.5s ease;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-top: 8px; font-size: 0.8em; color: var(--text-muted);">
                        <span>Дедлайн: ${g.deadline}</span>
                        <span>${pct}%</span>
                    </div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

// Global scope for onclick
window.runSystemAction = async function(action) {
    const resDiv = document.getElementById('actionResult');
    resDiv.style.display = 'block';
    resDiv.innerHTML = 'Выполняется... ⏳';
    resDiv.style.color = 'var(--text-primary)';

    try {
        const text = await automataApi.runAction(action);
        resDiv.innerHTML = text;
        resDiv.style.color = 'var(--success)';
    } catch(e) {
        resDiv.innerHTML = e.message || 'Ошибка сети / Сервер недоступен';
        resDiv.style.color = 'var(--danger)';
    }
}

/**
 * Streaming-выполнение действия: читает SSE-поток stdout скрипта построчно
 * и выводит в лог-бокс в реальном времени.
 * Используется для генерации счетов в блоке Матрицы Техподдержки (SLA).
 */
window.runStreamingAction = async function(action, logBoxId, extraQuery = '') {
    const logBox = document.getElementById(logBoxId);
    if (!logBox) return;

    // Подготовка бокса
    logBox.style.display = 'block';
    logBox.innerHTML = '';
    const colorOk = '#00ff00';
    const colorErr = '#ff6b6b';
    const colorDim = '#888';

    const append = (text, color = colorOk) => {
        const div = document.createElement('div');
        div.textContent = text;
        div.style.color = color;
        logBox.appendChild(div);
        logBox.scrollTop = logBox.scrollHeight;
    };

    append('▶ Запуск... (' + new Date().toLocaleTimeString() + ')', colorDim);

    try {
        const resp = await fetch(`${API_BASE}/actions/run-stream?action=${action}${extraQuery}`, { method: 'POST' });
        if (!resp.ok || !resp.body) {
            append('❌ Сервер вернул ошибку: ' + resp.status, colorErr);
            return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // SSE-формат: строки "data: ...\n\n"
            const parts = buffer.split('\n\n');
            buffer = parts.pop(); // последний (возможно неполный) кусок оставляем в буфере

            for (const part of parts) {
                const line = part.replace(/^data:\s*/, '').trim();
                if (!line) continue;
                if (line === '✅__DONE__') {
                    append('════════════════════════════════', colorDim);
                    append('✅ Завершено успешно', colorOk);
                } else if (line.startsWith('❌__DONE__')) {
                    append('════════════════════════════════', colorDim);
                    append(line.replace('❌__DONE__', '❌ Завершено с ошибкой '), colorErr);
                } else if (line.startsWith('❌')) {
                    append(line, colorErr);
                } else if (line.startsWith('⚠') || line.startsWith('⏭')) {
                    append(line, '#ffd166');
                } else if (line.startsWith('✓') || line.startsWith('✅') || line.startsWith('📊') || line.startsWith('📤')) {
                    append(line, colorOk);
                } else {
                    append(line, colorOk);
                }
            }
        }
        append('────────────────────────────────', colorDim);
    } catch (e) {
        append('❌ Ошибка соединения: ' + (e.message || e), colorErr);
    }
};

// Кнопка в Матрице Техподдержки (SLA) — генерация счетов с real-time логом
function initSlaInvoiceButton() {
    const btn = document.getElementById('slaInvoiceBtn');
    const sendAllBtn = document.getElementById('slaSendAllBtn');
    const periodSelect = document.getElementById('slaPeriodSelect');

    // Заполняем select периодами: текущий месяц + 2 следующих (для досрочных счетов)
    if (periodSelect && !periodSelect.options.length) {
        const ruMonths = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
        const now = new Date();
        const opts = [];
        for (let i = 0; i < 3; i++) {
            const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
            opts.push(`${ruMonths[d.getMonth()]} ${d.getFullYear()}`);
        }
        periodSelect.innerHTML = opts.map(p => `<option value="${p}">${p}</option>`).join('');
        periodSelect.value = opts[0]; // текущий по умолчанию
    }

    if (btn && !btn.dataset.bound) {
        btn.dataset.bound = 'true';
        btn.addEventListener('click', async () => {
            if (btn.dataset.running === 'true') return;
            btn.dataset.running = 'true';
            const previewChecked = document.getElementById('slaPreviewMode')?.checked;
            const action = previewChecked ? 'auto_invoice_preview' : 'auto_invoice';
            const period = periodSelect?.value || '';
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '⏳ Генерация...';
            btn.style.opacity = '0.6';
            try {
                const periodQ = period ? `&period=${encodeURIComponent(period)}` : '';
                await window.runStreamingAction(action, 'slaInvoiceLog', periodQ);
                await fetchData();
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
                btn.style.opacity = '1';
                btn.dataset.running = 'false';
            }
        });
    }

    // Кнопка «Отправить всем» — рассылает email по счетам текущего периода без отправки
    if (sendAllBtn && !sendAllBtn.dataset.bound) {
        sendAllBtn.dataset.bound = 'true';
        sendAllBtn.addEventListener('click', () => sendAllInvoices());
    }
}

/**
 * Отправляет email по всем счетам текущего периода, у которых email_status != sent.
 * Выводит прогресс в slaInvoiceLog.
 */
async function sendAllInvoices() {
    const logBox = document.getElementById('slaInvoiceLog');
    const btn = document.getElementById('slaSendAllBtn');
    if (!logBox || !btn || btn.dataset.running === 'true') return;

    const data = await automataApi.getData();
    const invoices = data.invoices || [];
    const ruMonths = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
    const curPeriod = ruMonths[new Date().getMonth()] + ' ' + new Date().getFullYear();

    // Счета текущего периода, не отправленные
    const toSend = invoices.filter(i =>
        i.period === curPeriod &&
        i.status === 'unpaid' &&
        i.email_status !== 'sent' &&
        i.invoice_pdf
    );

    if (toSend.length === 0) {
        logBox.style.display = 'block';
        logBox.innerHTML = '<div style="color:#ffd166">Нет счетов для отправки (все уже отправлены или нет счетов за текущий период).</div>';
        return;
    }

    btn.dataset.running = 'true';
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ Отправка...';
    btn.style.opacity = '0.6';

    logBox.style.display = 'block';
    logBox.innerHTML = '';
    const append = (text, color = '#00ff00') => {
        const div = document.createElement('div');
        div.textContent = text;
        div.style.color = color;
        logBox.appendChild(div);
        logBox.scrollTop = logBox.scrollHeight;
    };

    append(`📤 Отправка ${toSend.length} счетов за ${curPeriod}...`, '#888');
    let ok = 0, fail = 0;
    for (const inv of toSend) {
        append(`→ ${inv.number} (${inv.client})...`);
        try {
            await automataApi.sendInvoiceEmail(inv.number);
            append(`  ✅ отправлен`);
            ok++;
        } catch (e) {
            append(`  ❌ ошибка: ${e.message || e}`, '#ff6b6b');
            fail++;
        }
    }
    append('════════════════════════════════', '#888');
    append(`✅ Отправлено: ${ok}  |  ❌ Ошибок: ${fail}`, ok > 0 ? '#00ff00' : '#ff6b6b');

    btn.disabled = false;
    btn.textContent = originalText;
    btn.style.opacity = '1';
    btn.dataset.running = 'false';

    await fetchData();
}


async function updateServiceStatus() {
    const tgStatus = document.getElementById('tgStatus');

    // Клик по пилюле TG — обновить статус (пинг gateway), а не запускать локальный скрипт.
    // tg_listener.py сломан (Telegram заблокирован), заменён на VPS-gateway.
    if (!tgStatus.dataset.listenerAdded) {
        tgStatus.addEventListener('click', () => updateServiceStatus());
        tgStatus.style.cursor = 'pointer';
        tgStatus.dataset.listenerAdded = 'true';
    }

    try {
        const status = await automataApi.getStatus();

        // 1. TG-статус: пинг зарубежного gateway (userbot жив?)
        const tg = status.telegram_listener || {};
        if (tg.active) {
            tgStatus.className = 'status-pill active';
            const me = tg.me || {};
            const who = me.name ? `@${me.name}` : 'Active';
            tgStatus.querySelector('.status-label').textContent = `TG: ${who}`;
            tgStatus.title = `Telegram-gateway активен. Авторизован: ${me.name || '?'} (id ${me.id || '?'})`;
        } else {
            tgStatus.className = 'status-pill error';
            tgStatus.querySelector('.status-label').textContent = 'TG: Нет связи';
            tgStatus.title = 'Нет связи с Telegram-gateway на VPS. Проверьте интернет и статус сервиса tg-userbot на сервере.';
        }


        // 3. Update Monitor Status
        const monitorStatus = document.getElementById('monitorStatus');
        if (monitorStatus && status.monitoring) {
            if (!status.monitoring.active) {
                monitorStatus.className = 'status-pill error';
                monitorStatus.querySelector('.status-label').textContent = 'Monitor: Сбой/Старо';
            } else if (status.monitoring.status === 'issues') {
                monitorStatus.className = 'status-pill error';
                monitorStatus.querySelector('.status-label').textContent = `Monitor: ${status.monitoring.issues} Ошибок`;
            } else {
                monitorStatus.className = 'status-pill active';
                monitorStatus.querySelector('.status-label').textContent = 'Monitor: OK (Zzz)';
            }
        }

    } catch (error) {
        console.error('Error fetching service status:', error);
    }
}

async function startService(name) {
    console.log(`🚀 Requesting start for ${name}...`);
    const pillId = name === 'tg_listener' ? 'tgStatus' : 'none';
    if (pillId === 'none') return;
    const pill = document.getElementById(pillId);
    const label = pill.querySelector('.status-label');
    const originalText = label.textContent;

    // Loading state
    pill.style.opacity = '0.6';
    pill.style.pointerEvents = 'none';
    label.textContent = 'Starting...';

    try {
        await automataApi.startService(name);
        
        // Wait a bit and refresh status
        setTimeout(() => {
            updateServiceStatus();
            pill.style.opacity = '1';
            pill.style.pointerEvents = 'auto';
        }, 2000);

    } catch (error) {
        console.error(`Error starting ${name}:`, error);
        label.textContent = 'Error!';
        setTimeout(() => {
            label.textContent = originalText;
            pill.style.opacity = '1';
            pill.style.pointerEvents = 'auto';
        }, 3000);
    }
}

function populateKPIs(meta) {
    document.getElementById('kpiMrrValue').textContent = formatRub(meta.mrr);
    document.getElementById('kpiDebtValue').textContent = formatRub(meta.total_debt);
    document.getElementById('kpiDebtSub').textContent = `${meta.overdue_count} просрочено`;
    document.getElementById('kpiClientsValue').textContent = meta.active_clients_count;
    document.getElementById('kpiClientsSub').innerHTML = `<span style="color:var(--success)">${meta.support_clients_count}</span> на поддержке`;
    document.getElementById('kpiRevMonthValue').textContent = formatRub(meta.revenue_this_month);

    // Раскрывашка «кто оплатил в этом месяце» (владелец 14.09.2026)
    const detail = document.getElementById('kpiRevMonthDetail');
    const payers = meta.paid_this_month || [];
    if (detail) {
        detail.innerHTML = payers.length
            ? `<div class="kpi-detail-title">Оплатили в этом месяце · ${payers.length}</div>` +
              payers.map(p => `
                <div class="kpi-detail-row">
                    <span class="kpi-detail-client">${escapeHtml(p.client || '—')}</span>
                    <span class="kpi-detail-num">${escapeHtml(p.number || '')}</span>
                    <b class="kpi-detail-amount">${formatRub(p.amount)}</b>
                </div>`).join('') +
              `<div class="kpi-detail-total">Итого ${formatRub(meta.revenue_this_month)}</div>`
            : '<div class="kpi-detail-title">Оплат в этом месяце пока нет</div>';
    }
}

// Клик по карточке вешаем сразу при старте, не дожидаясь данных API —
// иначе первые ~8 сек (пока /api/data собирается) карточка «мёртвая» (фикс 14.09.2026)
function setupKpiPayers() {
    const card = document.getElementById('kpiRevMonth');
    const detail = document.getElementById('kpiRevMonthDetail');
    if (!card || !detail || card.dataset.wired) return;
    card.dataset.wired = '1';
    detail.innerHTML = '<div class="kpi-detail-title">Загрузка…</div>';
    card.addEventListener('click', e => {
        e.stopPropagation();
        detail.hidden = !detail.hidden;
        card.classList.toggle('open', !detail.hidden);
    });
    document.addEventListener('click', ev => {
        if (!card.contains(ev.target)) { detail.hidden = true; card.classList.remove('open'); }
    });
}

function populateUnpaidTable(unpaid) {
    const wrapper = document.getElementById('tableUnpaid');
    if (!unpaid || unpaid.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет неоплаченных счетов 🎉</div>';
        return;
    }

    // Sort by date oldest first
    unpaid.sort((a, b) => new Date(a.invoice_date) - new Date(b.invoice_date));

    let html = '<table class="dash-table"><thead><tr><th>Счёт</th><th>Клиент</th><th>Дата</th><th>Сумма</th><th>Статус</th><th>Документы (Точка)</th><th>Действия</th></tr></thead><tbody>';

    unpaid.forEach(inv => {
        const isSent = inv.sent;
        const badgeHtml = isSent ? '<span class="badge badge--success">Отправлен</span>' : '<span class="badge badge--warn">Черновик</span>';

        const days = daysUntil(inv.invoice_date);
        let dateColor = 'inherit';
        if (days !== null && days < -14) dateColor = 'var(--danger)';
        else if (days !== null && days < -7) dateColor = 'var(--warning)';

        const invoicePath = encodeURIComponent('30_Invoices/' + inv.id);
        const invNum = inv.number;

        // Блок документов: PDF-ссылки (obsidian:// primary + HTTP fallback) или кнопки генерации в Точке
        const docsHtml = buildDocCell(inv, 'invoice') + buildDocCell(inv, 'act');

        // Иконки действий (как в SLA-матрице): напомнить письмом, TG, превью, перегенерировать
        let actionsHtml = `<div style="display:flex; gap:6px; font-size:1.05em; align-items:center;">`;
        actionsHtml += `<span style="cursor:pointer" title="Превью письма" onclick="openInvoiceEmailModal('${invNum}')">👁</span>`;
        if (inv.invoice_pdf) {
            actionsHtml += `<span style="cursor:pointer" title="Открыть PDF" onclick="openInvoicePdfModal('${invNum}')">📄</span>`;
        }
        actionsHtml += `<span style="cursor:pointer" title="Отправить/напомнить по email" onclick="sendSingleInvoice('${invNum}', this)">📤</span>`;
        actionsHtml += `<span style="cursor:pointer" title="Напомнить в Telegram" onclick="openInvoiceTgModal('${invNum}')">💬</span>`;
        actionsHtml += `<span style="cursor:pointer" title="Перегенерировать PDF" onclick="regenerateInvoice('${invNum}', this)">🔄</span>`;
        actionsHtml += `</div>`;

        html += `
      <tr>
        <td style="cursor: pointer; color: var(--primary);" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${invoicePath}')"><strong>${inv.number}</strong></td>
        <td>${inv.client}</td>
        <td style="color:${dateColor}">${formatDate(inv.invoice_date)}</td>
        <td><strong>${formatRub(inv.amount)}</strong></td>
        <td>${badgeHtml}</td>
        <td><div class="doc-cell">${docsHtml}</div></td>
        <td>${actionsHtml}</td>
      </tr>
    `;
    });

    html += '</tbody></table>';
    wrapper.innerHTML = html;

    // Attach listeners for generate-in-Tochka buttons
    wrapper.querySelectorAll('.gen-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            const number = btn.getAttribute('data-number');
            const doc = btn.getAttribute('data-doc');
            const originalHTML = btn.innerHTML;

            btn.innerHTML = '⌛';
            btn.disabled = true;
            btn.style.opacity = '0.7';

            try {
                const res = await automataApi.generateInvoiceDoc(number, doc);
                if (res && res.skipped) {
                    showToast(`ℹ️ ${res.message}`, 'info');
                } else {
                    showToast(`✅ ${res.message}`, 'success');
                }
                // Перерисовать таблицу с обновлёнными PDF
                await fetchData();
            } catch (err) {
                showToast(`❌ ${err.message}`, 'error');
                btn.innerHTML = originalHTML;
                btn.disabled = false;
                btn.style.opacity = '1';
            }
        });
    });
}

/**
 * Построить ячейку документа (счёт/акт): PDF-ссылки если есть, иначе кнопка генерации в Точке.
 * @param {Object} inv — объект счёта из data.json
 * @param {'invoice'|'act'} doc
 */
function buildDocCell(inv, doc) {
    const pdfName = doc === 'invoice' ? inv.invoice_pdf : inv.act_pdf;
    const label = doc === 'invoice' ? 'Счёт' : 'Акт';
    const obsidianUrl = `obsidian://open?vault=AUTOMATA-CRM&file=60_Documents/${encodeURIComponent(pdfName)}`;
    const httpUrl = automataApi.getInvoicePdfUrl(inv.number, doc);

    if (pdfName) {
        // PDF уже сгенерирован: primary = obsidian://, fallback = HTTP (⬇)
        return `
            <div class="doc-item doc-item--ready">
                <span class="doc-label">${label}</span>
                <a href="${obsidianUrl}" class="pdf-link" title="Открыть в Obsidian">📄</a>
                <a href="${httpUrl}" target="_blank" rel="noopener" class="pdf-link pdf-link--alt" title="Открыть через сервер">⬇</a>
            </div>`;
    }
    // PDF нет — кнопка генерации в Точке
    return `
        <div class="doc-item">
            <span class="doc-label">${label}</span>
            <button class="gen-btn" data-number="${inv.number}" data-doc="${doc}" title="Сгенерировать в банке Точка">🏦</button>
        </div>`;
}

function populateSlaTimers(tickets) {
    const wrapper = document.getElementById('tableSlaTimers');
    if (!wrapper) return;
    
    // Filter only open tickets with deadlines
    let slaTickets = tickets.filter(t => t.status === 'open' && t.sla_deadline);
    slaTickets.sort((a, b) => a.hours_remaining - b.hours_remaining);
    
    if (slaTickets.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет горящих SLA таймеров 🟢</div>';
        return;
    }
    
    let html = '<table class="dash-table"><thead><tr><th>Срок</th><th>Тикет</th><th>Клиент</th></tr></thead><tbody>';
    
    slaTickets.forEach(t => {
        let badgeHtml = '';
        if (t.hours_remaining < 0) badgeHtml = '<span class="badge badge--danger">ПРОСРОЧЕН</span>';
        else if (t.hours_remaining <= 1) badgeHtml = '<span class="badge badge--warning">Менее часа</span>';
        else badgeHtml = `<span class="badge badge--info">${t.hours_remaining} ч</span>`;
        
        const ticketPath = encodeURIComponent('45_Tickets/' + t.id);
        html += `
        <tr>
            <td>${badgeHtml}</td>
            <td style="cursor: pointer; color: var(--primary);" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${ticketPath}')"><b>${t.title}</b></td>
            <td>${t.client}</td>
        </tr>
        `;
    });
    
    html += '</tbody></table>';
    wrapper.innerHTML = html;
}

function populateLeadsTable(leads) {
    const wrapper = document.getElementById('newLeadsTable');
    const countSpan = document.getElementById('leadsCount');
    if (!wrapper) return;

    if (!leads || leads.length === 0) {
        if (countSpan) countSpan.textContent = '';
        wrapper.innerHTML = '<div class="empty-state">Нет новых лидов 🟢</div>';
        return;
    }

    // Показываем только новые (status=new) — максимум 15;
    // scan_alert_2bldesk — технические уведомления мониторинга, не лиды (владелец 14.09.2026)
    const newLeads = leads
        .filter(l => (l.status || 'new') === 'new')
        .filter(l => !String(l.name || '').toLowerCase().includes('scan_alert_2bldesk'))
        .slice(0, 15);
    if (countSpan) countSpan.textContent = `(${newLeads.length})`;

    let html = '<table class="dash-table"><thead><tr><th>Имя</th><th>Контакт</th><th>Источник</th><th>Дата</th><th>Сообщение</th></tr></thead><tbody>';
    newLeads.forEach(l => {
        const leadPath = encodeURIComponent('15_Leads/' + l.id);
        // Контакт: приоритет telegram, потом phone, потом email
        let contact = '';
        if (l.telegram) contact = `💬 @${l.telegram}`;
        else if (l.phone) contact = `📞 ${l.phone}`;
        else if (l.email) contact = `✉ ${l.email}`;
        else contact = '—';

        // Бейдж источника
        const src = String(l.source || '').toLowerCase();
        let srcBadge = 'badge--info';
        let srcLabel = l.source || '—';
        if (src.includes('telegram') || src.includes('tg')) { srcBadge = 'badge--success'; srcLabel = 'Telegram'; }
        else if (src.includes('mail') || src.includes('email')) { srcBadge = 'badge--info'; srcLabel = 'Email'; }

        const msg = (l.message || '').slice(0, 80);
        const date = l.created ? formatDate(l.created) : '—';

        html += `
          <tr>
            <td style="cursor:pointer; color: var(--primary);" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${leadPath}')"><strong>${l.name || 'Без имени'}</strong></td>
            <td style="font-size:0.85em">${contact}</td>
            <td><span class="badge ${srcBadge}" style="font-size:0.75em">${srcLabel}</span></td>
            <td style="font-size:0.85em; color: var(--text-muted)">${date}</td>
            <td style="font-size:0.85em; max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="${(l.message||'').replace(/"/g,'&quot;')}">${msg || '—'}</td>
          </tr>
        `;
    });
    html += '</tbody></table>';
    wrapper.innerHTML = html;
}

function populateRenewalsTable(renewals) {
    const wrapper = document.getElementById('tableRenewals');
    if (!renewals || renewals.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет ближайших продлений 🟢</div>';
        return;
    }

    renewals.sort((a, b) => new Date(a.renewal_date) - new Date(b.renewal_date));

    let html = '<table class="dash-table"><thead><tr><th>Услуга / Провайдер</th><th>Клиент</th><th>Дата</th><th>Сумма</th></tr></thead><tbody>';

    renewals.forEach(r => {
        const days = daysUntil(r.renewal_date);
        let badgeHtml = '';
        if (days !== null && days <= 7) badgeHtml = '<span class="badge badge--danger" style="margin-left:8px">Скоро</span>';

        const renewalPath = encodeURIComponent('40_Infrastructure/' + r.id);
        html += `
      <tr>
        <td style="cursor: pointer; color: var(--primary);" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${renewalPath}')">
          <div style="font-weight:600">${r.service_type || r.id} ${badgeHtml}</div>
          <div style="font-size:0.7em;color:var(--text-muted)">${r.provider}</div>
        </td>
        <td>${r.client}</td>
        <td>${formatDate(r.renewal_date)}</td>
        <td><strong>${formatRub(r.amount)}</strong></td>
      </tr>
    `;
    });

    html += '</tbody></table>';
    wrapper.innerHTML = html;
}

function populateCreditsTable(credits, summary) {
    const wrapper = document.getElementById('tableCredits');
    const statsDiv = document.getElementById('creditStats');

    statsDiv.innerHTML = `
    <div class="credit-stat">
      <span class="credit-stat-label">Остаток долга</span>
      <span class="credit-stat-value">${formatRub(summary.total_remaining)}</span>
    </div>
    <div class="credit-stat">
      <span class="credit-stat-label">Платежи в месяц</span>
      <span class="credit-stat-value">${formatRub(summary.total_monthly)}</span>
    </div>
  `;

    if (!credits || credits.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет активных кредитов 🎉</div>';
        return;
    }

    let html = '<table class="dash-table"><thead><tr><th>Банк / Тип</th><th>Сумма (Ставка)</th><th>Остаток</th><th>Платёж/мес</th><th>Срок</th></tr></thead><tbody>';

    credits.forEach(cr => {
        const creditPath = encodeURIComponent('50_Credits/' + cr.id);
        html += `
      <tr>
        <td style="cursor: pointer; color: var(--primary);" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${creditPath}')">
          <div style="font-weight:600">${cr.bank}</div>
          <div style="font-size:0.7em;color:var(--text-muted)">${cr.loan_type} • ${cr.purpose}</div>
        </td>
        <td>
          <div>${formatRub(cr.amount)}</div>
          <div style="font-size:0.7em;color:var(--success)">${cr.rate}% годовых</div>
        </td>
        <td><strong style="color:var(--text-primary)">${formatRub(cr.remaining)}</strong></td>
        <td><strong style="color:var(--warning)">${formatRub(cr.monthly_payment)}</strong></td>
        <td>${formatDate(cr.end_date)}</td>
      </tr>
    `;
    });

    html += '</tbody></table>';
    wrapper.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Модалки превью счетов (переиспользуют #helpModal)
// ---------------------------------------------------------------------------
async function openInvoiceEmailModal(number) {
    const modal = document.getElementById('helpModal');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');
    if (!modal || !title || !body) return;

    title.textContent = `Письмо по счёту №${number}`;
    body.innerHTML = '<div style="padding:20px; color:var(--text-muted)">Загрузка превью...</div>';
    modal.classList.add('active');

    try {
        const data = await automataApi.emailPreview(number);
        const sent = data.sent ? '<span style="color:var(--success)">уже отправлен</span>' : '<span style="color:var(--warning)">не отправлен</span>';
        body.innerHTML = `
            <div style="padding:16px; display:flex; flex-direction:column; gap:12px;">
                <div style="font-size:0.85em; color:var(--text-muted)">
                    <strong>Кому:</strong> ${data.client_email || '—'} (${data.client_name || ''})<br>
                    <strong>Статус:</strong> ${sent}
                </div>
                <div style="background:var(--bg-dark); padding:12px; border-radius:6px;">
                    <div style="color:#00ff00; font-size:0.85em; margin-bottom:4px;">ТЕМА:</div>
                    <div style="color:var(--text-primary); font-size:0.9em;">${data.subject || ''}</div>
                </div>
                <div style="background:var(--bg-dark); padding:12px; border-radius:6px; max-height:300px; overflow-y:auto;">
                    <div style="color:#00ff00; font-size:0.85em; margin-bottom:8px;">ТЕКСТ ПИСЬМА:</div>
                    <pre style="white-space:pre-wrap; font-family:inherit; color:var(--text-primary); font-size:0.85em; margin:0;">${(data.body || '').replace(/</g, '&lt;')}</pre>
                </div>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    ${data.pdf_url ? `<button class="btn btn--secondary btn--sm" onclick="openInvoicePdfModal('${number}')">📄 Открыть PDF</button>` : '<span style="color:var(--danger); font-size:0.85em">⚠️ PDF не сгенерирован</span>'}
                    ${!data.sent ? `<button class="btn btn--success btn--sm" onclick="sendSingleInvoice('${number}', null); document.getElementById('helpModal').classList.remove('active');">📤 Отправить</button>` : ''}
                    <button class="btn btn--secondary btn--sm" onclick="document.getElementById('helpModal').classList.remove('active')">✕ Закрыть</button>
                </div>
            </div>
        `;
    } catch (e) {
        body.innerHTML = `<div style="padding:20px; color:var(--danger)">❌ Ошибка: ${e.message || e}</div>`;
    }
}

function openInvoicePdfModal(number) {
    const modal = document.getElementById('helpModal');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');
    if (!modal) return;
    title.textContent = `PDF счёта №${number}`;
    const pdfUrl = automataApi.getInvoicePdfUrl(number, 'invoice');
    body.innerHTML = `
        <div style="padding:8px;">
            <iframe src="${pdfUrl}" style="width:100%; height:60vh; border:1px solid var(--border); border-radius:6px;" title="PDF ${number}"></iframe>
            <div style="margin-top:8px; display:flex; gap:8px;">
                <a href="${pdfUrl}" target="_blank" class="btn btn--secondary btn--sm">↗ Открыть в новой вкладке</a>
                <button class="btn btn--secondary btn--sm" onclick="document.getElementById('helpModal').classList.remove('active')">✕ Закрыть</button>
            </div>
        </div>
    `;
    modal.classList.add('active');
}

async function sendSingleInvoice(number, el) {
    if (el) { el.style.opacity = '0.5'; el.textContent = '⏳'; }
    if (!confirm(`Отправить счёт №${number} на email?`)) {
        if (el) { el.style.opacity = '1'; el.textContent = '📤'; }
        return;
    }
    try {
        await automataApi.sendInvoiceEmail(number);
        if (typeof showToast === 'function') showToast(`✅ Счёт №${number} отправлен`, 'success');
        else alert(`✅ Счёт №${number} отправлен`);
        await fetchData();
    } catch (e) {
        if (typeof showToast === 'function') showToast(`❌ Ошибка: ${e.message || e}`, 'error');
        else alert(`❌ ${e.message || e}`);
    } finally {
        if (el) { el.style.opacity = '1'; el.textContent = '📤'; }
    }
}

async function regenerateInvoice(number, el) {
    if (el) { el.style.opacity = '0.5'; el.textContent = '⏳'; }
    if (!confirm(`Перегенерировать PDF счёта №${number} в Точке?`)) {
        if (el) { el.style.opacity = '1'; el.textContent = '🔄'; }
        return;
    }
    try {
        await automataApi.regenerateInvoicePdf(number, 'invoice');
        if (typeof showToast === 'function') showToast(`✅ PDF счёта №${number} перегенерирован`, 'success');
        else alert(`✅ PDF перегенерирован`);
        await fetchData();
    } catch (e) {
        if (typeof showToast === 'function') showToast(`❌ Ошибка: ${e.message || e}`, 'error');
        else alert(`❌ ${e.message || e}`);
    } finally {
        if (el) { el.style.opacity = '1'; el.textContent = '🔄'; }
    }
}

// Глобальный экспорт для onclick из HTML
window.openInvoiceEmailModal = openInvoiceEmailModal;
window.openInvoicePdfModal = openInvoicePdfModal;
window.sendSingleInvoice = sendSingleInvoice;
window.regenerateInvoice = regenerateInvoice;
window.openInvoiceTgModal = openInvoiceTgModal;

// ---------------------------------------------------------------------------
// ⚡ Экспресс-аудит сайта (лид-магнит)
// ---------------------------------------------------------------------------
let _lastAuditResult = null;

function initSiteAudit() {
    const runBtn = document.getElementById('auditRunBtn');
    const saveBtn = document.getElementById('auditSaveLeadBtn');
    const input = document.getElementById('auditUrlInput');

    if (runBtn && !runBtn.dataset.bound) {
        runBtn.dataset.bound = 'true';
        runBtn.addEventListener('click', () => runSiteAudit());
        input?.addEventListener('keydown', (e) => { if (e.key === 'Enter') runSiteAudit(); });
    }
    if (saveBtn && !saveBtn.dataset.bound) {
        saveBtn.dataset.bound = 'true';
        saveBtn.addEventListener('click', () => saveAuditLead());
    }
}

async function runSiteAudit() {
    const url = document.getElementById('auditUrlInput')?.value.trim();
    const btn = document.getElementById('auditRunBtn');
    const resultDiv = document.getElementById('auditResult');
    if (!url) { alert('Введите адрес сайта'); return; }

    btn.disabled = true;
    btn.textContent = '⏳ Проверяем...';
    btn.style.opacity = '0.6';
    resultDiv.style.display = 'none';

    try {
        const data = await fetchApi('/site-audit', {
            method: 'POST',
            body: JSON.stringify({ url })
        });
        _lastAuditResult = data;
        renderAuditResult(data);
    } catch (e) {
        alert('❌ ' + (e.message || e));
    } finally {
        btn.disabled = false;
        btn.textContent = '🚀 Проверить';
        btn.style.opacity = '1';
    }
}

function renderAuditResult(data) {
    const resultDiv = document.getElementById('auditResult');
    const scoreDiv = document.getElementById('auditOverallScore');
    const domainDiv = document.getElementById('auditDomain');
    const barsDiv = document.getElementById('auditBars');
    if (!resultDiv) return;

    const overall = data.overall || 0;
    const scoreColor = overall >= 75 ? 'var(--success)' : overall >= 45 ? '#ffcc00' : 'var(--danger)';
    scoreDiv.textContent = overall;
    scoreDiv.style.color = scoreColor;
    domainDiv.textContent = data.domain || data.url;

    let html = '';
    const labels = { uptime: '🌐', speed: '⚡', ssl: '🔒', seo: '🔍', geo: '🤖' };
    for (const [key, chk] of Object.entries(data.checks || {})) {
        const s = chk.score || 0;
        const color = s >= 75 ? 'var(--success)' : s >= 45 ? '#ffcc00' : 'var(--danger)';
        const icon = s >= 75 ? '✅' : s >= 45 ? '⚠️' : '❌';
        html += `
        <div style="margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between; font-size:0.85em; margin-bottom:3px;">
                <span>${labels[key] || '•'} ${chk.label} ${icon}</span>
                <span style="color:${color}; font-weight:700;">${s}/100</span>
            </div>
            <div style="background:var(--bg-dark); border-radius:6px; height:10px; overflow:hidden;">
                <div style="width:${s}%; height:100%; background:${color}; border-radius:6px; transition: width 0.8s ease;"></div>
            </div>
            <div style="font-size:0.72em; color:var(--text-muted); margin-top:2px;">${chk.detail || ''}</div>
        </div>`;
    }
    barsDiv.innerHTML = html;
    resultDiv.style.display = 'block';
    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function saveAuditLead() {
    const contact = document.getElementById('auditContactInput')?.value.trim();
    if (!contact) { alert('Укажите email или телефон клиента'); return; }
    if (!_lastAuditResult) { alert('Сначала выполните аудит'); return; }

    const btn = document.getElementById('auditSaveLeadBtn');
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        await fetchApi('/site-audit/save-lead', {
            method: 'POST',
            body: JSON.stringify({
                url: _lastAuditResult.url,
                contact,
                name: _lastAuditResult.domain,
                results: _lastAuditResult,
            })
        });
        if (typeof showToast === 'function') showToast('✅ Лид сохранён в 15_Leads/', 'success');
        else alert('✅ Лид сохранён в 15_Leads/');
        await fetchData();
    } catch (e) {
        alert('❌ ' + (e.message || e));
    } finally {
        btn.disabled = false;
        btn.textContent = '💾 Сохранить как лид';
    }
}
window.openTemplatesModal = openTemplatesModal;

/**
 * Превью TG-сообщения по счёту + кнопка отправки через gateway.
 */
async function openInvoiceTgModal(number) {
    const modal = document.getElementById('helpModal');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');
    if (!modal) return;

    title.textContent = `Telegram по счёту №${number}`;
    body.innerHTML = '<div style="padding:20px; color:var(--text-muted)">Загрузка...</div>';
    modal.classList.add('active');

    try {
        const data = await automataApi.tgPreview(number);
        const hasChat = data.has_chat_id;
        body.innerHTML = `
            <div style="padding:16px; display:flex; flex-direction:column; gap:12px;">
                <div style="font-size:0.85em; color:var(--text-muted)">
                    <strong>Клиент:</strong> ${data.client_name || '—'}<br>
                    <strong>Диалог в TG:</strong> ${hasChat
                        ? '<span style="color:var(--success)">есть (можно отправить)</span>'
                        : '<span style="color:var(--danger)">нет — клиент не писал в Telegram. Отправка невозможна (userbot не пишет первым).</span>'}
                </div>
                <div style="background:var(--bg-dark); padding:12px; border-radius:6px; max-height:300px; overflow-y:auto;">
                    <div style="color:#00ff00; font-size:0.85em; margin-bottom:8px;">ТЕКСТ ДЛЯ TELEGRAM:</div>
                    <pre style="white-space:pre-wrap; font-family:inherit; color:var(--text-primary); font-size:0.85em; margin:0;">${(data.text || '').replace(/</g, '&lt;')}</pre>
                </div>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    ${hasChat
                        ? `<button class="btn btn--success btn--sm" onclick="sendSingleTelegram('${number}', this)">💬 Отправить в Telegram</button>`
                        : '<span style="color:var(--text-muted); font-size:0.85em">Отправка недоступна</span>'}
                    <button class="btn btn--secondary btn--sm" onclick="document.getElementById('helpModal').classList.remove('active')">✕ Закрыть</button>
                </div>
            </div>
        `;
    } catch (e) {
        body.innerHTML = `<div style="padding:20px; color:var(--danger)">❌ ${e.message || e}</div>`;
    }
}

async function sendSingleTelegram(number, el) {
    if (el) { el.style.opacity = '0.5'; el.textContent = '⏳'; }
    try {
        await automataApi.sendInvoiceTelegram(number);
        if (typeof showToast === 'function') showToast(`✅ Счёт №${number} отправлен в Telegram (через gateway)`, 'success');
        document.getElementById('helpModal')?.classList.remove('active');
    } catch (e) {
        if (typeof showToast === 'function') showToast(`❌ ${e.message || e}`, 'error');
        else alert(`❌ ${e.message || e}`);
    } finally {
        if (el) { el.style.opacity = '1'; el.textContent = '💬 Отправить в Telegram'; }
    }
}
window.sendSingleTelegram = sendSingleTelegram;

/**
 * Редактор шаблонов писем/TG (3 таба: Email счёт / Email акт / Telegram).
 */
async function openTemplatesModal() {
    const modal = document.getElementById('helpModal');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');
    if (!modal) return;

    title.textContent = '📝 Шаблоны сообщений';
    body.innerHTML = '<div style="padding:20px; color:var(--text-muted)">Загрузка шаблонов...</div>';
    modal.classList.add('active');

    const tabs = [
        { id: 'invoice_email', label: '📧 Email: счёт', vars: '{{invoice_number}}, {{amount}}, {{period}}, {{client_name}}, {{contact_name}}, {{custom_message}}, {{items}}' },
        { id: 'act_email', label: '📧 Email: акт', vars: '{{invoice_number}}, {{amount}}, {{period}}, {{client_name}}, {{contact_name}}' },
        { id: 'invoice_tg', label: '💬 Telegram', vars: '{{invoice_number}}, {{amount}}, {{period}}, {{client_name}}, {{contact_name}}, {{custom_message}}' },
        { id: 'contract_support', label: '📄 Договор: тело', vars: 'Тело договора (разделы 1–12). Плейсхолдеры: {{contract_number}}, {{contract_date}}, {{company_full_name}}, {{ogrn}}, {{inn}}, {{kpp}}, {{legal_address}}, {{email}}, {{phone}}, {{director_phrase}}, {{contractor_bank_details}}. Приложения собираются отдельно — табы ниже.' },
        { id: 'contract_app_sla', label: 'Прил: SLA', vars: '{{tariff_section}} = пункты 3.1–3.4 выбранного тарифа клиента' },
        { id: 'contract_app_tm', label: 'Прил: T&M', vars: 'Статичный прейскурант почасовых ставок' },
        { id: 'contract_app_act_form', label: 'Прил: Акт', vars: 'Форма Акта сдачи-приёмки' },
        { id: 'contract_app_nda', label: 'Прил: NDA', vars: 'Соглашение о конфиденциальности' },
        { id: 'contract_app_security', label: 'Прил: Доступы', vars: 'Регламент передачи доступов' },
        { id: 'contract_app_tariffs', label: 'Прил: Тарифы', vars: '{{tariff_name}}, {{hours_phrase}}, {{fee_phrase}}, {{rate_phrase}} — параметры выбранного тарифа' },
    ];

    // Загружаем все шаблоны параллельно
    const loaded = {};
    for (const t of tabs) {
        try {
            const data = await automataApi.getTemplate(t.id);
            loaded[t.id] = data.content;
        } catch (e) {
            loaded[t.id] = `[ошибка загрузки: ${e.message}]`;
        }
    }

    body.innerHTML = `
        <div style="padding:12px;">
            <div style="display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap;">
                ${tabs.map((t, i) => `<button class="btn btn--${i===0?'primary':'secondary'} btn--sm tpl-tab-btn" data-tab="${t.id}">${t.label}</button>`).join('')}
            </div>
            ${tabs.map((t, i) => `
                <div class="tpl-tab-content" data-tab="${t.id}" style="display:${i===0?'block':'none'};">
                    <div style="font-size:0.75em; color:var(--text-muted); margin-bottom:6px;">
                        ${t.vars}
                    </div>
                    <textarea class="tpl-editor" data-tab="${t.id}" style="width:100%; min-height:300px; background:var(--bg-dark); color:var(--text-primary); border:1px solid var(--border); border-radius:6px; padding:10px; font-family:monospace; font-size:0.85em; resize:vertical;">${(loaded[t.id]||'').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</textarea>
                    <div style="margin-top:8px; display:flex; gap:8px;">
                        <button class="btn btn--success btn--sm" onclick="saveTemplateFromEditor('${t.id}')">💾 Сохранить</button>
                        <span class="tpl-save-status" data-tab="${t.id}" style="font-size:0.85em; color:var(--text-muted); align-self:center;"></span>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    // Переключение табов
    body.querySelectorAll('.tpl-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            body.querySelectorAll('.tpl-tab-btn').forEach(b => b.className = 'btn btn--secondary btn--sm tpl-tab-btn');
            btn.className = 'btn btn--primary btn--sm tpl-tab-btn';
            body.querySelectorAll('.tpl-tab-content').forEach(c => c.style.display = c.dataset.tab === tabId ? 'block' : 'none');
        });
    });
}

async function saveTemplateFromEditor(tabId) {
    const editor = document.querySelector(`.tpl-editor[data-tab="${tabId}"]`);
    const status = document.querySelector(`.tpl-save-status[data-tab="${tabId}"]`);
    if (!editor || !status) return;
    status.textContent = '⏳ Сохранение...';
    status.style.color = 'var(--text-muted)';
    try {
        await automataApi.saveTemplate(tabId, editor.value);
        status.textContent = '✅ Сохранено';
        status.style.color = 'var(--success)';
    } catch (e) {
        status.textContent = `❌ ${e.message || e}`;
        status.style.color = 'var(--danger)';
    }
}
window.saveTemplateFromEditor = saveTemplateFromEditor;

// Привязка кнопки «Шаблоны»
function initTemplatesButton() {
    const btn = document.getElementById('templatesBtn');
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = 'true';
    btn.addEventListener('click', () => openTemplatesModal());
}

function populateSLASupportMatrix(clients, invoices) {
    const wrapper = document.getElementById('slaSupportMatrix');
    if (!wrapper) return;

    // Filter only retainer clients
    const retainers = clients.filter(c => c.support_type === 'retainer');

    if (retainers.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет клиентов на поддержке</div>';
        return;
    }

    // Текущий период для поиска счёта (например «Июль 2026»)
    const ruMonths = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
    const curPeriod = ruMonths[new Date().getMonth()] + ' ' + new Date().getFullYear();
    const invs = invoices || [];

    let html = '<table class="dash-table"><thead><tr><th>Клиент</th><th>План</th><th>Квота (ч)</th><th>Исп-но (ч)</th><th>Остаток (ч)</th><th>📧 Email</th><th>💬 TG</th><th>📤 Счёт</th><th>⚙️ Действия</th></tr></thead><tbody>';

    retainers.forEach(c => {
        // Универсальный парсинг квоты из support_Xh
        let quota = 0;
        const planMatch = String(c.support_plan || '').match(/(\d+)\s*h/i);
        if (planMatch) quota = parseInt(planMatch[1], 10);

        const used = c.hours_used_current_month || 0;
        const remaining = quota - used;

        let remColor = 'inherit';
        if (remaining < 0) remColor = 'var(--danger)';
        else if (remaining === 0) remColor = 'var(--warning)';
        else if (used > 0) remColor = 'var(--success)';

        // Поиск счёта клиента за текущий период
        const cid = String(c.id || '');
        const cname = String(c.name || '');
        const periodInv = invs.find(i =>
            curPeriod === String(i.period || '') &&
            (cname === String(i.client || '') || cid === String(i.client || '') ||
             String(i.client || '').includes(cid) || String(i.client || '').includes(cname))
        );

        // Email клиента
        const email = c.email || '—';
        const emailHtml = email !== '—'
            ? `<a href="mailto:${email}" style="color:var(--text-muted); font-size:0.85em; text-decoration:none">${email}</a>`
            : '<span style="color:var(--danger); font-size:0.85em">нет email</span>';

        // Telegram аккаунт клиента
        const tgRaw = String(c.telegram || '').trim();
        let tgHtml = '<span style="color:var(--text-muted); font-size:0.85em">—</span>';
        if (tgRaw) {
            if (tgRaw.startsWith('@')) {
                tgHtml = `<a href="https://t.me/${tgRaw.slice(1)}" target="_blank" style="color:var(--text-muted); font-size:0.85em; text-decoration:none">${tgRaw}</a>`;
            } else {
                tgHtml = `<span style="color:var(--text-muted); font-size:0.85em">📞 ${tgRaw}</span>`;
            }
        }

        // Статус отправки счёта
        let sendHtml = '';
        let actionsHtml = '';
        if (!periodInv) {
            sendHtml = '<span class="badge badge--warning" style="font-size:0.75em">не выставлен</span>';
        } else {
            const eStatus = String(periodInv.email_status || 'unknown');
            const sentCount = periodInv.sent_count || 0;
            const invNum = periodInv.number || '';
            const invPath = encodeURIComponent('30_Invoices/' + (periodInv.id || ''));
            let badge = 'badge--info';
            let label = eStatus;
            if (eStatus === 'sent' || eStatus === 'delivered') { badge = 'badge--success'; label = 'отправлен'; }
            else if (eStatus === 'failed' || eStatus === 'bounced') { badge = 'badge--danger'; label = 'ошибка'; }
            else if (eStatus === 'unknown' || !eStatus) { badge = 'badge--info'; label = sentCount > 0 ? `отправлен (?)` : 'не отправлен'; }
            sendHtml = `<span class="badge ${badge}" style="font-size:0.75em; cursor:pointer" title="${invNum} · отправок: ${sentCount}" onclick="event.stopPropagation(); window.open('obsidian://open?vault=AUTOMATA-CRM&file=${invPath}')">${label}</span>`;

            // Иконки действий (только если счёт существует)
            const hasPdf = periodInv.invoice_pdf ? '1' : '0';
            actionsHtml = `<div style="display:flex; gap:6px; font-size:1.1em;">`;
            actionsHtml += `<span style="cursor:pointer" title="Превью письма" onclick="openInvoiceEmailModal('${invNum}')">👁</span>`;
            if (hasPdf === '1') {
                actionsHtml += `<span style="cursor:pointer" title="Открыть PDF" onclick="openInvoicePdfModal('${invNum}')">📄</span>`;
            }
            if (eStatus !== 'sent' && eStatus !== 'delivered') {
                actionsHtml += `<span style="cursor:pointer" title="Отправить email" onclick="sendSingleInvoice('${invNum}', this)">📤</span>`;
            }
            actionsHtml += `<span style="cursor:pointer" title="Отправить в Telegram" onclick="openInvoiceTgModal('${invNum}')">💬</span>`;
            actionsHtml += `<span style="cursor:pointer" title="Перегенерировать PDF" onclick="regenerateInvoice('${invNum}', this)">🔄</span>`;
            actionsHtml += `</div>`;
        }

        html += `
          <tr>
            <td style="cursor: pointer; color: var(--primary);" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${encodeURIComponent('10_Clients/' + c.id)}')"><strong>${c.name}</strong></td>
            <td><span class="badge badge--info">${c.support_plan || 'Не задан'}</span></td>
            <td>${quota}</td>
            <td>${used}</td>
            <td><strong style="color:${remColor}">${remaining}</strong></td>
            <td>${emailHtml}</td>
            <td>${tgHtml}</td>
            <td>${sendHtml}</td>
            <td>${actionsHtml}</td>
          </tr>
        `;
    });

    html += '</tbody></table>';
    wrapper.innerHTML = html;
}

function populateSupportMatrix(matrix, wrapperId = 'supportMatrix') {
    const wrapper = document.getElementById(wrapperId);
    if (!matrix || Object.keys(matrix).length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Нет релевантных счетов 📂</div>';
        return;
    }

    const year = new Date().getFullYear();
    const monthNames = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
    const monthKeys = Array.from({ length: 12 }, (_, i) => `${year}-${(i + 1).toString().padStart(2, '0')}`);
    const clientIds = Object.keys(matrix);

    let html = `
    <table class="matrix-table">
      <thead>
        <tr>
          <th class="sticky-col">Месяц</th>
          ${clientIds.map(id => `<th>${matrix[id].name}</th>`).join('')}
        </tr>
      </thead>
      <tbody>
  `;

    monthKeys.forEach((mKey, idx) => {
        html += `<tr><td class="sticky-col">${monthNames[idx]}</td>`;

        clientIds.forEach(clientId => {
            const invoicesData = matrix[clientId].months[mKey];
            if (!invoicesData || invoicesData.length === 0) {
                html += `<td><div class="month-cell-inner"><div class="cell-part cell-missing">—</div><div class="cell-part cell-missing">—</div></div></td>`;
            } else {
                html += `<td><div class="multi-invoice-container">`;
                invoicesData.forEach(data => {
                    const invStatus = data.invoice_status === 'paid' ? 'cell-paid' : 'cell-unpaid';
                    const actStatus = data.act_status === 'paid' ? 'cell-paid' : 'cell-unpaid';
                    const edoCss = data.edo_status ? 'cell-paid' : 'cell-missing';
                    const sentCount = data.sent_count > 0 ? `<span class="sent-badge">${data.sent_count}x</span>` : '';

                    const invObsidianURL = `obsidian://open?vault=AUTOMATA-CRM&file=30_Invoices/${encodeURIComponent(data.id)}`;
                    const invPdfURL = data.invoice_pdf ? `obsidian://open?vault=AUTOMATA-CRM&file=60_Documents/${encodeURIComponent(data.invoice_pdf)}` : null;
                    const actPdfURL = data.act_pdf ? `obsidian://open?vault=AUTOMATA-CRM&file=60_Documents/${encodeURIComponent(data.act_pdf)}` : null;

                    html += `
            <div class="invoice-block" style="cursor: pointer;" onclick="window.open('${invObsidianURL}')">
                <div class="invoice-title" title="${data.service_name}">
                    ${data.service_name}
                </div>
                <div class="month-cell-inner">
                  <div class="cell-part ${invStatus}">
                    <span class="cell-label-link">Счёт</span>
                    ${invPdfURL ? `<a href="${invPdfURL}" class="cell-value-link" title="Открыть PDF" onclick="event.stopPropagation()">📄 PDF</a>` : `<div class="cell-value-dummy">₽</div>`}
                  </div>
                  <div class="cell-part ${actStatus}">
                    <span class="cell-label-link">Акт</span>
                    ${actPdfURL ? `<a href="${actPdfURL}" class="cell-value-link" title="Открыть PDF" onclick="event.stopPropagation()">📄 PDF</a>` : `<div class="cell-value-dummy">✓</div>`}
                  </div>
                  <div class="cell-part ${edoCss}">
                    <span class="cell-label-link">ЭДО</span>
                    <div class="cell-value-dummy">${data.edo_status ? '✓' : '—'}</div>
                  </div>
                </div>
                <div class="cell-info">
                  ${data.payment_date ? formatDate(data.payment_date) : (data.amount ? formatRub(data.amount) : '')}
                  ${sentCount}
                </div>
            </div>
          `;
                });
                html += `</div></td>`;
            }
        });

        html += '</tr>';
    });

    html += '</tbody></table>';
    wrapper.innerHTML = html;
}

function setupManagementButtons() {
    const reconcileBtn = document.getElementById('reconcileBankBtn');
    const sendBtn = document.getElementById('sendUnpaidBtn');
    const refreshMonBtn = document.getElementById('refreshMonitoringBtn');

    if (reconcileBtn) {
        reconcileBtn.onclick = () => {
            alert('🔄 Запущена сверка в банке. Результат появится после обновления данных.\n(Running: python3 scripts/reconcile.py)');
        };
    }

    if (sendBtn) {
        sendBtn.onclick = () => {
            alert('✉ Запущена отправка неоплаченных счетов.\n(Running: python3 scripts/mass_resend_emails.py)');
        };
    }

    if (refreshMonBtn) {
        refreshMonBtn.onclick = async () => {
            const originalText = refreshMonBtn.textContent;
            refreshMonBtn.textContent = '⌛ Обновление...';
            refreshMonBtn.disabled = true;
            try {
                await automataApi.refreshMonitoring();

                const monRes = await fetch('/data/monitoring.json?t=' + Date.now());
                if (monRes.ok) {
                    const data = await monRes.json();
                    renderMonitoringView(data);
                }
            } catch (e) {
                console.error(e);
                alert(e.message);
            } finally {
                refreshMonBtn.textContent = originalText;
                refreshMonBtn.disabled = false;
            }
        };
    }

    const refreshGeoBtn = document.getElementById('refreshGeoBtn');
    if (refreshGeoBtn) {
        refreshGeoBtn.onclick = async () => {
            const originalText = refreshGeoBtn.textContent;
            refreshGeoBtn.textContent = '⌛ Аудит...';
            refreshGeoBtn.disabled = true;
            try {
                await automataApi.refreshGeo();

                const geoRes = await fetch('/data/geo.json?t=' + Date.now());
                if (geoRes.ok) {
                    const data = await geoRes.json();
                    renderGeoView(data);
                }
            } catch (e) {
                console.error(e);
                alert(e.message);
            } finally {
                refreshGeoBtn.textContent = originalText;
                refreshGeoBtn.disabled = false;
            }
        };
    }
}

// ─────────────────────────────────────────────────────────────────
// Все клиенты и тарифы (полный справочник: активные, переговоры, лиды)
// ─────────────────────────────────────────────────────────────────
const LIFECYCLE_BADGES = {
    active:      { label: 'Активный', cls: 'badge--success' },
    negotiation: { label: 'Переговоры', cls: 'badge--warn' },
    prospect:    { label: 'Лид', cls: 'badge--purple' },
    lost:        { label: 'Потерян', cls: 'badge--danger' },
    former:      { label: 'Неактивный', cls: 'badge--gray' },
    inactive:    { label: 'Неактивный', cls: 'badge--gray' }
};

function clientPlanLabel(c) {
    if (c.support_plan) return c.support_plan;
    if (c.support_type && c.support_type !== 'none') return c.support_type;
    return '—';
}

function populateAllClientsTable(clients) {
    const wrapper = document.getElementById('allClientsTable');
    if (!wrapper) return;
    if (!clients || clients.length === 0) {
        wrapper.innerHTML = '<div class="empty-state">Клиенты не найдены</div>';
        return;
    }

    const query = (document.getElementById('clientsSearch')?.value || '').trim().toLowerCase();
    const filtered = !query ? clients : clients.filter(c => {
        const haystack = [c.id, c.name, c.email, c.inn, c.telegram, clientPlanLabel(c)]
            .join(' ').toLowerCase();
        return haystack.includes(query);
    });

    const order = { active: 0, negotiation: 1, prospect: 2 };
    const sorted = filtered.slice().sort((a, b) => {
        const ka = order[a.lifecycle] ?? 3, kb = order[b.lifecycle] ?? 3;
        return ka !== kb ? ka - kb : a.id.localeCompare(b.id, 'ru');
    });

    const planStats = {};
    clients.forEach(c => {
        const p = clientPlanLabel(c);
        if (p !== '—') planStats[p] = (planStats[p] || 0) + 1;
    });

    let html = `
        <div style="padding: 8px 12px; font-size: 0.78rem; color: var(--text-muted);">
            Всего: <strong style="color:var(--text-primary)">${clients.length}</strong>
            ${query ? ` · найдено: <strong style="color:var(--text-primary)">${sorted.length}</strong>` : ''}
            · активных: <strong style="color:var(--success)">${clients.filter(c => c.lifecycle === 'active').length}</strong>
            · тарифы: ${Object.entries(planStats).map(([p, n]) => `${p}×${n}`).join(', ') || '—'}
        </div>
        <table class="dash-table"><thead><tr>
            <th>Клиент</th><th>Статус</th><th>Тариф</th><th>Ставка, ₽/ч</th>
            <th>Абонплата, ₽/мес</th><th>Часы (мес.)</th><th>Доход, ₽</th><th>Договор</th><th>Контакты</th>
        </tr></thead><tbody>`;

    sorted.forEach(c => {
        const badge = LIFECYCLE_BADGES[c.lifecycle]
            || { label: c.lifecycle || '—', cls: 'badge--gray' };
        const clientPath = encodeURIComponent('10_Clients/' + c.id);
        const contacts = [];
        if (c.email) contacts.push(`<a href="mailto:${escapeHtml(c.email)}" title="${escapeHtml(c.email)}">✉</a>`);
        if (c.telegram) contacts.push(`<span title="Telegram: ${escapeHtml(String(c.telegram))}">💬</span>`);
        const hours = c.hours_used_current_month || 0;
        const plan = clientPlanLabel(c);
        const hoursWarn = plan !== '—' && hours > 0 ? 'style="color:var(--warning)"' : '';

        // Договоры клиента: ссылка на карточку (md/txt) и скан (pdf), иначе кнопка создания
        const contracts = c.contracts || [];
        const contractPath = f => encodeURIComponent('60_Documents/Contracts/' + f);
        const pdfStems = new Set(contracts.filter(k => k.ext === 'pdf')
            .map(k => k.file.replace(/\.pdf$/i, '')));
        const contractLinks = contracts.map(k => {
            let html = `<span style="cursor:pointer" title="${escapeHtml(k.file)}"
                onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${contractPath(k.file)}')">${k.ext === 'pdf' ? '📎' : '📄'}</span>`;
            // У md/txt без одноимённого pdf — кнопка сборки DOCX+PDF
            if (k.ext !== 'pdf' && !pdfStems.has(k.file.replace(/\.(md|txt)$/i, ''))) {
                html += `<span class="contract-add" title="Собрать DOCX + PDF (pandoc + LibreOffice)"
                    onclick="exportContractFiles('${escapeHtml(c.id)}', '${escapeHtml(k.file)}', this)">📑</span>`;
            }
            return html;
        }).join(' ');
        const contractCell = contracts.length
            ? `${contractLinks} <span class="contract-add" title="Создать ещё договор"
                onclick="openCreateContractModal('${escapeHtml(c.id)}')">＋</span>`
            : `<button class="btn btn--primary btn--sm" onclick="openCreateContractModal('${escapeHtml(c.id)}')"
                title="Сгенерировать договор на сопровождение">＋ Договор</button>`;

        html += `
      <tr>
        <td style="cursor:pointer;color:var(--primary)" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${clientPath}')" title="${escapeHtml(c.name || '')}">
            <strong>${escapeHtml(c.id)}</strong>
        </td>
        <td><span class="badge ${badge.cls}">${badge.label}</span></td>
        <td>${plan !== '—' ? `<code>${plan}</code>` : '<span style="opacity:0.4">—</span>'}</td>
        <td>${c.rate ? formatRub(c.rate) : '—'}</td>
        <td>${c.monthly_retainer_fee ? formatRub(c.monthly_retainer_fee) : '—'}</td>
        <td ${hoursWarn}>${hours || '—'}</td>
        <td>${c.total_revenue ? formatRub(c.total_revenue) : '—'}</td>
        <td style="white-space:nowrap;">${contractCell}</td>
        <td>${contacts.join(' ') || '<span style="opacity:0.4">—</span>'}</td>
      </tr>`;
    });

    html += '</tbody></table>';
    wrapper.innerHTML = html;
}

// Шаблоны договоров для генерации (id → подпись). Файл шаблона — 90_Templates/,
// редактируется в модалке «📝 Шаблоны» (имя таба = id).
const CONTRACT_TEMPLATES = [
    { id: 'contract_support', label: 'Рамочный договор на сопровождение' }
];

/** Модалка генерации договора клиенту (кнопка «＋ Договор» в списке клиентов). */
async function openCreateContractModal(clientId) {
    const modal = document.getElementById('helpModal');
    const body = document.getElementById('modalBody');
    const title = document.getElementById('modalTitle');

    title.textContent = `📄 Договор — ${clientId}`;

    // Реестр приложений (кэшируется на сессию)
    let appendices = [];
    try {
        appendices = await (appendixRegistryCache ??= automataApi.getContractAppendices());
    } catch (e) {
        showToast('❌ Не удалось загрузить список приложений: ' + e.message, 'error');
        return;
    }

    body.innerHTML = `
        <form id="contractGenerateForm" class="entity-form">
            <div class="form-field">
                <label>Клиент</label>
                <input type="text" class="modal-field-input" value="${escapeHtml(clientId)}" disabled>
            </div>
            <div class="form-field">
                <label>Шаблон</label>
                <select id="contractTemplateSelect" class="modal-field-input">
                    ${CONTRACT_TEMPLATES.map(t => `<option value="${t.id}">${t.label}</option>`).join('')}
                </select>
                <div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px;">
                    Данные клиента (ИНН, директор, тариф) подставятся из карточки 10_Clients/.
                    Редактировать шаблон: «📝 Шаблоны» → «📄 Договор».
                </div>
            </div>
            <div class="form-field">
                <label>Номер договора (необязательно)</label>
                <input type="text" id="contractNumberInput" class="modal-field-input" placeholder="Например: 07092026-1">
                <div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px;">
                    Пусто — номер ДДММГГГГ-1 от сегодняшней даты. Если файл уже существует, добавится суффикс _v2, _v3…
                </div>
            </div>
            <div class="form-field">
                <label>Приложения (нумеруются автоматически)</label>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px 16px;">
                    ${appendices.map(a => `
                        <label style="display:flex; align-items:center; gap:7px; font-size:0.85rem; cursor:pointer;">
                            <input type="checkbox" class="contract-appendix-check" value="${a.id}"
                                ${a.default ? 'checked' : ''} style="cursor:pointer;">
                            <span>${escapeHtml(a.title)}</span>
                        </label>`).join('')}
                </div>
            </div>
            <div class="form-checks">
                <label style="display:flex; align-items:center; gap:8px; font-size:0.9rem; cursor:pointer;">
                    <input type="checkbox" id="contractExportCheck" checked style="cursor:pointer;">
                    <span>Сразу собрать DOCX + PDF (pandoc → LibreOffice)</span>
                </label>
            </div>
            <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:6px;">
                <button type="button" class="btn btn--secondary" id="cancelContractBtn">Отмена</button>
                <button type="submit" class="btn btn--success" id="submitContractBtn">Сгенерировать</button>
            </div>
        </form>
    `;
    modal.classList.add('active');

    const form = document.getElementById('contractGenerateForm');
    const submitBtn = document.getElementById('submitContractBtn');
    const cancelBtn = document.getElementById('cancelContractBtn');
    document.getElementById('contractNumberInput').focus();

    const cleanup = () => {
        submitBtn.replaceWith(submitBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    };
    cancelBtn.onclick = () => { modal.classList.remove('active'); cleanup(); };

    form.onsubmit = async (e) => {
        e.preventDefault();
        const selected = [...body.querySelectorAll('.contract-appendix-check:checked')].map(c => c.value);
        submitBtn.innerHTML = '⌛ Генерация...';
        submitBtn.disabled = true;
        cancelBtn.disabled = true;
        try {
            const result = await automataApi.generateContract({
                client: clientId,
                template: document.getElementById('contractTemplateSelect').value,
                number: document.getElementById('contractNumberInput').value.trim() || null,
                export: document.getElementById('contractExportCheck').checked,
                appendices: selected,
            });
            modal.classList.remove('active');
            cleanup();
            showToast(`✅ ${result.message}`, 'success');
            await fetchData();
        } catch (err) {
            showToast(`❌ ${err.message}`, 'error');
            submitBtn.innerHTML = 'Сгенерировать';
            submitBtn.disabled = false;
            cancelBtn.disabled = false;
        }
    };
}

let appendixRegistryCache = null;

window.openCreateContractModal = openCreateContractModal;

/** Собрать DOCX + PDF из существующего .md договора (кнопка «📑» у ссылки). */
window.exportContractFiles = async function(clientId, fileName, el) {
    if (el) { el.textContent = '⌛'; el.style.pointerEvents = 'none'; }
    showToast('⏳ Собираю DOCX + PDF…', 'info');
    try {
        const res = await automataApi.exportContract(fileName);
        showToast(`✅ ${res.message}: ${res.pdf.split('/').pop()}`, 'success');
        await fetchData(); // перерисует ячейку: у договора появится 📎 pdf
    } catch (err) {
        showToast(`❌ ${err.message}`, 'error');
        if (el) { el.textContent = '📑'; el.style.pointerEvents = 'auto'; }
    }
};

function populateEisenhowerMatrix(matrix) {
    if (!matrix) return;

    const quadrants = ['q1', 'q2', 'q3', 'q4'];
    quadrants.forEach(q => {
        const container = document.querySelector(`#quadrant-${q} .task-list`);
        if (!container) return;

        let tasks = matrix[q] || [];
        if (tasks.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding:10px;font-size:0.75rem;">Задач нет</div>';
            return;
        }

        // Встречи (type=meeting) — первыми, по дате; обычные задачи — после
        tasks = [...tasks].sort((a, b) => {
            const am = a.type === 'meeting', bm = b.type === 'meeting';
            if (am !== bm) return am ? -1 : 1;
            if (am && bm) return String(a.date || '9999').localeCompare(String(b.date || '9999'));
            return 0;
        });

        container.innerHTML = tasks.map(t => {
            const taskPath = encodeURIComponent('30_Tasks/' + t.id);
            const dateBadge = (t.type === 'meeting' && t.date)
                ? `<span style="background:var(--primary);color:#fff;border-radius:6px;padding:1px 6px;font-size:0.68rem;font-weight:600;">📅 ${t.date}</span>` : '';
            const meetIcon = t.type === 'meeting' ? '🤝 ' : '';
            return `
            <div class="task-item" style="cursor: pointer; position: relative;" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${taskPath}')">
                <div class="task-project">${t.project} ${dateBadge}</div>
                <div class="task-title" style="color: var(--primary); font-weight: 500;">${meetIcon}${t.title}</div>
                <button class="task-close-btn" data-id="${t.id}" data-title="${escapeHtml(t.title)}" title="Завершить задачу">✓</button>
            </div>
        `}).join('');
    });

    // Привязать обработчики к кнопкам «Завершить»
    document.querySelectorAll('.task-close-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const taskId = btn.getAttribute('data-id');
            const taskTitle = btn.getAttribute('data-title');
            openCloseTaskModal(taskId, taskTitle);
        });
    });
}

/** Экранировать HTML для безопасной вставки в data-атрибут. */
function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

/** Открыть модалку завершения задачи с полем ввода часов. Переиспользует #helpModal. */
function openCloseTaskModal(taskId, taskTitle) {
    const modal = document.getElementById('helpModal');
    const body = document.getElementById('modalBody');
    const title = document.getElementById('modalTitle');

    title.textContent = '✓ Завершить задачу';
    body.innerHTML = `
        <div style="margin-bottom: 16px;">
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">Задача:</div>
            <div style="color: var(--primary); font-weight: 500; line-height: 1.4;">${escapeHtml(taskTitle)}</div>
        </div>
        <div style="margin-bottom: 20px;">
            <label for="hoursInput" style="display:block; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">
                Затрачено часов:
            </label>
            <input type="number" id="hoursInput" class="modal-hours-input" step="0.5" min="0" value="0.5" />
        </div>
        <div style="display:flex; gap:10px; justify-content:flex-end;">
            <button class="btn btn--secondary" id="cancelCloseTask">Отмена</button>
            <button class="btn btn--success" id="confirmCloseTask">✓ Завершить</button>
        </div>
    `;
    modal.classList.add('active');

    const input = document.getElementById('hoursInput');
    const confirmBtn = document.getElementById('confirmCloseTask');
    const cancelBtn = document.getElementById('cancelCloseTask');
    input.focus();
    input.select();

    const cleanup = () => {
        confirmBtn.replaceWith(confirmBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    };

    cancelBtn.onclick = () => { modal.classList.remove('active'); cleanup(); };

    input.onkeydown = (e) => {
        if (e.key === 'Enter') confirmBtn.click();
        if (e.key === 'Escape') { modal.classList.remove('active'); cleanup(); }
    };

    confirmBtn.onclick = async () => {
        const hours = parseFloat(input.value);
        if (isNaN(hours) || hours < 0) {
            showToast('❌ Введите корректное число часов', 'error');
            return;
        }
        confirmBtn.innerHTML = '⌛...';
        confirmBtn.disabled = true;
        cancelBtn.disabled = true;

        try {
            await automataApi.closeTask(taskId, hours);
            modal.classList.remove('active');
            showToast(`✅ Задача завершена, списано ${hours} ч.`, 'success');
            await fetchData();
        } catch (err) {
            showToast(`❌ ${err.message}`, 'error');
            confirmBtn.innerHTML = '✓ Завершить';
            confirmBtn.disabled = false;
            cancelBtn.disabled = false;
        }
    };
}

// ─────────────────────────────────────────────────────────────────
// Универсальное создание сущностей (задачи; далее — счета, акты, клиенты).
// Форма строится по схеме из GET /api/entities/schema (scripts/create_entity.py),
// Obsidian Vault остаётся единственной базой данных.
// ─────────────────────────────────────────────────────────────────
let entitySchemasCache = null;
let lastDashboardData = null;

async function getEntitySchemas() {
    if (!entitySchemasCache) {
        entitySchemasCache = await automataApi.getEntitySchemas();
    }
    return entitySchemasCache;
}

function initCreateEntityButtons() {
    const bind = (id, entityType) => {
        const btn = document.getElementById(id);
        if (btn && !btn.dataset.bound) {
            btn.dataset.bound = 'true';
            btn.addEventListener('click', () => openCreateEntityModal(entityType));
        }
    };
    bind('createTaskBtn', 'task');
    bind('createInvoiceBtn', 'invoice');
    bind('createActBtn', 'act');
}

function initClientsDirectory() {
    const search = document.getElementById('clientsSearch');
    if (search && !search.dataset.bound) {
        search.dataset.bound = 'true';
        search.addEventListener('input', () => populateAllClientsTable(lastDashboardData?.clients || []));
    }
}

const QUADRANT_INFO = {
    q1: { name: '🔥 Q1 — Срочно & Важно (Do First)', color: 'var(--danger)' },
    q2: { name: '📅 Q2 — Важно, запланировать (Schedule)', color: 'var(--warning)' },
    q3: { name: '💡 Q3 — Срочно, делегировать (Delegate)', color: 'var(--accent)' },
    q4: { name: '☕ Q4 — Бэклог (Eliminate)', color: 'var(--text-muted)' }
};

function taskQuadrant(urgent, important) {
    if (urgent && important) return 'q1';
    if (important) return 'q2';
    if (urgent) return 'q3';
    return 'q4';
}

/** Универсальная модалка создания сущности: поля генерируются по схеме реестра. */
async function openCreateEntityModal(entityType) {
    const modal = document.getElementById('helpModal');
    const body = document.getElementById('modalBody');
    const title = document.getElementById('modalTitle');

    let schema;
    try {
        schema = (await getEntitySchemas())[entityType];
    } catch (e) {
        showToast('❌ Не удалось загрузить схему сущностей: ' + e.message, 'error');
        return;
    }
    if (!schema) {
        showToast(`❌ Неизвестный тип сущности: ${entityType}`, 'error');
        return;
    }

    title.textContent = `${schema.icon || ''} Создать: ${schema.label}`;

    const renderField = (f) => {
        const req = f.required ? ' <span class="req" style="color:var(--danger);">*</span>' : '';
        const help = f.help ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px;">${f.help}</div>` : '';
        const commonAttrs = `data-field="${f.name}" class="modal-field-input"`;

        let control = '';
        switch (f.type) {
            case 'textarea':
                control = `<textarea ${commonAttrs} rows="4" placeholder="${f.placeholder || ''}">${f.default || ''}</textarea>`;
                break;
            case 'number':
                control = `<input type="number" step="0.5" ${commonAttrs} value="${f.default ?? 0}">`;
                break;
            case 'date': {
                const today = new Date().toISOString().slice(0, 10);
                control = `<input type="date" ${commonAttrs} value="${f.default === 'today' ? today : (f.default || today)}">`;
                break;
            }
            case 'checkbox':
                control = `<label style="display:flex; align-items:center; gap:8px; font-size:0.9rem; cursor:pointer;">
                    <input type="checkbox" data-field="${f.name}" style="cursor:pointer;" ${f.default ? 'checked' : ''}>
                    <span>${f.label}</span>
                </label>`;
                break;
            case 'client': {
                const clients = (lastDashboardData?.clients || [])
                    .slice().sort((a, b) => a.id.localeCompare(b.id, 'ru'));
                const options = clients.map(c =>
                    `<option value="${escapeHtml(c.id)}">${escapeHtml(c.id)}</option>`).join('');
                control = `<select ${commonAttrs}>
                    <option value="">— без клиента (внутренняя задача) —</option>${options}
                </select>`;
                break;
            }
            default:
                control = `<input type="text" ${commonAttrs} placeholder="${f.placeholder || ''}" value="${f.default || ''}">`;
        }

        if (f.type === 'checkbox') {
            return `<div class="form-field">${control}</div>`;
        }
        return `<div class="form-field">
            <label>${f.label}${req}</label>
            ${control}
            ${help}
        </div>`;
    };

    const checkboxes = schema.fields.filter(f => f.type === 'checkbox');
    const regularFields = schema.fields.filter(f => f.type !== 'checkbox');
    const previewHtml = schema.preview === 'eisenhower' ? `
        <div class="form-field">
            <label>Квадрант матрицы</label>
            <div id="quadrantPreview" class="quadrant-preview"></div>
        </div>` : '';

    body.innerHTML = `
        <form id="entityCreateForm" class="entity-form">
            ${regularFields.map(renderField).join('')}
            ${checkboxes.length ? `<div class="form-checks">${checkboxes.map(renderField).join('')}</div>` : ''}
            ${previewHtml}
            <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:6px;">
                <button type="button" class="btn btn--secondary" id="cancelCreateEntity">Отмена</button>
                <button type="submit" class="btn btn--success" id="confirmCreateEntity">Создать</button>
            </div>
        </form>
    `;
    modal.classList.add('active');

    const form = document.getElementById('entityCreateForm');
    const confirmBtn = document.getElementById('confirmCreateEntity');
    const cancelBtn = document.getElementById('cancelCreateEntity');
    const firstInput = body.querySelector('.modal-field-input:not(select)');
    if (firstInput) firstInput.focus();

    const updatePreview = () => {
        if (!previewHtml) return;
        const box = document.getElementById('quadrantPreview');
        const checked = {};
        checkboxes.forEach(f => {
            checked[f.name] = body.querySelector(`[data-field="${f.name}"]`)?.checked || false;
        });
        const q = taskQuadrant(checked.urgent, checked.important);
        const info = QUADRANT_INFO[q];
        box.textContent = info.name;
        box.style.borderLeftColor = info.color;
        box.style.color = info.color;
    };
    checkboxes.forEach(f => {
        body.querySelector(`[data-field="${f.name}"]`)?.addEventListener('change', updatePreview);
    });
    updatePreview();

    const cleanup = () => {
        confirmBtn.replaceWith(confirmBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    };

    cancelBtn.onclick = () => { modal.classList.remove('active'); cleanup(); };

    form.onsubmit = async (e) => {
        e.preventDefault();

        const payload = {};
        schema.fields.forEach(f => {
            const el = body.querySelector(`[data-field="${f.name}"]`);
            if (!el) return;
            payload[f.name] = f.type === 'checkbox' ? el.checked : el.value;
        });

        const missing = schema.fields
            .filter(f => f.required && !String(payload[f.name] || '').trim())
            .map(f => f.label);
        if (missing.length) {
            showToast('❌ Заполните: ' + missing.join(', '), 'error');
            return;
        }

        confirmBtn.innerHTML = '⌛ Создание...';
        confirmBtn.disabled = true;
        cancelBtn.disabled = true;

        try {
            const result = await automataApi.createEntity(entityType, payload);
            modal.classList.remove('active');
            cleanup();
            showToast(`✅ Создано: ${result.folder}/${result.file}`, 'success');
            await fetchData();
        } catch (err) {
            showToast(`❌ ${err.message}`, 'error');
            confirmBtn.innerHTML = 'Создать';
            confirmBtn.disabled = false;
            cancelBtn.disabled = false;
        }
    };
}

async function syncTasks() {
    const btn = document.getElementById('syncTasksBtn');
    if (!btn) return;

    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '⌛ Синхронизация...';
    btn.style.opacity = '0.7';

    try {
        const result = await automataApi.syncTasks();
        console.log('✅ Task sync complete:', result);

        // Refresh the whole dashboard data to show new statuses
        await fetchData();
        
        btn.innerHTML = '✅ Готово';
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
            btn.style.opacity = '1';
        }, 3000);
    } catch (error) {
        console.error('Error syncing tasks:', error);
        btn.innerHTML = '❌ Ошибка';
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
            btn.style.opacity = '1';
        }, 5000);
    }
}

function setupHelpModals() {
    const modal = document.getElementById('helpModal');
    const body = document.getElementById('modalBody');
    const title = document.getElementById('modalTitle');
    const triggers = document.querySelectorAll('.help-trigger');
    const closeBtn = document.querySelector('.close-modal');

    const content = {
        globalHelpTrigger: {
            title: "🚀 Логика работы CRM",
            html: `
                <p>Система AUTOMATA-CRM построена на гибридной модели:</p>
                <ul>
                    <li><strong>Obsidian Vault</strong> — основное хранилище данных (Клиенты, Счета, Акты).</li>
                    <li><strong>GITACTIVE</strong> — папка с активными проектами, где ведется разработка и управление задачами.</li>
                    <li><strong>Python Engine</strong> — набор скриптов, которые связывают всё воедино (синхронизация банков, парсинг задач, генерация документов).</li>
                </ul>
                <p>Данные на этом дашборде обновляются автоматически раз в минуту или вручную при нажатии кнопки Refresh.</p>
            `
        },
        eisenhowerHelpTrigger: {
            title: "⚖️ Матрица Эйзенхауэра",
            html: `
                <div style="margin-bottom: 12px; font-size: 0.85rem; color: var(--accent); background: rgba(0, 162, 232, 0.1); padding: 10px; border-radius: 6px; border-left: 4px solid var(--accent);">
                    <strong>🖱️ Интерактивность дашборда:</strong><br>
                    Все карточки задач полностью интерактивны. <b>Кликните по любой задаче</b> — протокол <code>obsidian://</code> автоматически откроет соответствующую карточку <code>.md</code> в Obsidian. Кнопка <b>✓</b> в углу карточки завершает задачу (ставит <code>status: done</code>, дату и часы). Кнопка <b>＋ Задача</b> в шапке блока создаёт новую задачу прямо из дашборда: файл появится в <code>30_Tasks/</code>, матрица перегенерируется автоматически. Тот же механизм (<code>scripts/create_entity.py</code>) используется и для других сущностей — счетов, актов, договоров, клиентов.
                </div>
                
                <div style="margin-bottom: 15px;">
                    <strong style="color: var(--warning);">🏷️ Правила распределения по квадрантам (YAML теги):</strong>
                    <p style="margin-top: 5px; font-size: 0.9em; opacity: 0.9;">Квадранты определяются по тегам в блоке frontmatter (шапке) файла задачи в папке <code>30_Tasks/</code>:</p>
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 8px;">
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                            <th style="text-align: left; padding: 6px 0;">Квадрант</th>
                            <th style="text-align: left; padding: 6px 0;">Необходимые теги в YAML</th>
                        </tr>
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 6px 0;">🔥 <b>Q1</b> (Срочно & Важно)</td>
                            <td style="padding: 6px 0;"><code>urgent</code> и <code>important</code></td>
                        </tr>
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 6px 0;">📅 <b>Q2</b> (Важно / Запланировать)</td>
                            <td style="padding: 6px 0;"><code>important</code> <span style="font-size:0.8em; opacity:0.7;">(Задачи <i>Мягкая кровля</i> попадают в Q2 автоматически)</span></td>
                        </tr>
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 6px 0;">💡 <b>Q3</b> (Срочно / Делегировать)</td>
                            <td style="padding: 6px 0;"><code>urgent</code></td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0;">☕ <b>Q4</b> (Бэклог / Отложить)</td>
                            <td style="padding: 6px 0;">Без тегов <code>urgent</code> и <code>important</code></td>
                        </tr>
                    </table>
                </div>

                <div style="margin-bottom: 15px; background: rgba(255,255,255,0.02); padding: 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                    <strong style="color: var(--success);">🤖 Работа через ИИ-агентов (Воркфлоу):</strong>
                    <ul style="font-size: 0.85rem; padding-left: 20px; margin-top: 5px; line-height: 1.4;">
                        <li style="margin-bottom: 6px;"><b>Добавление задачи (<code>/create_task</code>):</b> Агент находит клиента, сверяет лимит поддержки, <i>подсчитывает потраченные часы за текущий месяц по файлам в 30_Tasks/</i> и предупреждает при превышении лимита перед созданием.</li>
                        <li style="margin-bottom: 6px;"><b>Закрытие задачи (<code>/close_task</code>):</b> Агент запрашивает часы, меняет статус задачи на <code>done</code>, записывает <code>date_completed</code> и запускает перегенерацию дашборда.</li>
                        <li><b>Оценка по архиву (<code>estimate_task.py</code>):</b> Запросите в чате: <i>"Оцени задачу: [описание]"</i>. Агент выполнит поиск по 12 000+ задачам из архива 2012–2026 гг. и рассчитает среднее и медианное время.</li>
                    </ul>
                </div>
            `
        },
        clientsHelpTrigger: {
            title: "👥 Все клиенты и тарифы",
            html: `
                <p>Полный справочник клиентов из карточек <code>10_Clients/</code> — и активные, и ведущиеся переговоры, и лиды.</p>
                <ul style="font-size:0.9rem; line-height:1.5;">
                    <li><b>Статус</b> — поле <code>lifecycle</code>: <code>active</code> (Активный), <code>negotiation</code> (Переговоры), <code>prospect</code> (Лид), <code>lost</code>/<code>former</code> (Неактивный).</li>
                    <li><b>Тариф</b> — поле <code>support_plan</code> (например <code>support_3h</code> = 3 часа/мес), либо <code>support_type</code> (retainer / license / project), либо «—».</li>
                    <li><b>Ставка</b> — <code>rate</code> ₽/час; <b>Абонплата</b> — <code>monthly_retainer_fee</code> ₽/мес (это и есть MRR).</li>
                    <li><b>Часы (мес.)</b> — <code>hours_used_current_month</code>: израсходовано часов поддержки в текущем месяце (подсвечивается, если уже вели работы).</li>
                    <li>Клик по имени открывает карточку клиента в Obsidian. Поиск фильтрует по имени, email, ИНН, Telegram и тарифу.</li>
                </ul>
            `
        },
        paymentHelpTrigger: {
            title: "💳 Матрица оплат",
            html: `
                <p>Мониторинг платежей техподдержки.</p>
                <div style="margin-bottom: 15px;">
                    <strong>📄 Правила Obsidian:</strong>
                    <ul style="font-size: 0.85rem; padding-left: 20px; line-height: 1.4; margin-top: 5px;">
                        <li><strong>Клиенты:</strong> Требуется <code>status: active</code> и <code>inn</code> в карточке клиента (папка <code>10_Clients</code>).</li>
                        <li><strong>Счета:</strong> Файл в папке <code>30_Invoices</code> с полем <code>client</code> в виде ссылки <code>"[[Имя Клиента]]"</code>.</li>
                        <li><strong>Месяц (Строка):</strong> Определяется автоматически по первым 7 символам поля <code>invoice_date</code> (например, <code>2026-06</code>).</li>
                    </ul>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>🚥 Статусы и поля в файле счёта:</strong>
                    <ul style="font-size: 0.85rem; padding-left: 20px; line-height: 1.4; margin-top: 5px;">
                        <li><strong>Счёт:</strong> 
                            <ul>
                                <li>🟢 <strong>Paid</strong> — если в фронтматтере прописано <code>status: paid</code>.</li>
                                <li>🔴 <strong>Unpaid</strong> — если <code>status: unpaid</code>, <code>sent</code>, <code>new</code> или <code>awaiting_payment</code>.</li>
                                <li>📄 <strong>PDF Ссылка:</strong> подтягивается из поля <code>invoice_pdf</code> (файл из папки <code>60_Documents</code>), иначе отображается символ <code>₽</code>.</li>
                            </ul>
                        </li>
                        <li style="margin-top: 5px;"><strong>Акт:</strong> 
                            <ul>
                                <li>🟢 <strong>Paid/Signed</strong> — если в фронтматтере <code>act_status</code> равен <code>paid</code> или <code>signed</code> (или в тексте отмечено <code>- [x] Акт выполненных работ</code>).</li>
                                <li>🔴 <strong>Unpaid</strong> — во всех остальных случаях.</li>
                                <li>📄 <strong>PDF Ссылка:</strong> подтягивается из поля <code>act_pdf</code>, иначе отображается <code>✓</code>.</li>
                            </ul>
                        </li>
                        <li style="margin-top: 5px;"><strong>ЭДО:</strong> 
                            <ul>
                                <li>🟢 <strong>Подписано/Отправлено:</strong> если в <code>tags</code> есть тег <code>edo</code>, либо в фронтматтере <code>edo_status</code> равен <code>true</code>, <code>"true"</code>, <code>"sent"</code> или <code>"signed"</code>, либо в тексте отмечено <code>- [x] Подписанные документы</code>.</li>
                                <li>⚪ <strong>— (Missing):</strong> если ни одно из условий не выполнено.</li>
                            </ul>
                        </li>
                    </ul>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>🔄 Инфо-строка (под кнопками):</strong>
                    <ul style="font-size: 0.85rem; padding-left: 20px; line-height: 1.4; margin-top: 5px;">
                        <li>Отображает дату оплаты из поля <code>payment_date</code> (если статус <code>paid</code>), либо сумму счета из поля <code>amount</code>.</li>
                        <li>Если счет был отправлен клиенту (поле <code>sent_count</code> > 0), рядом выводится индикатор количества отправок (например, <code>1x</code>, <code>3x</code>).</li>
                    </ul>
                </div>
                <div style="font-size: 0.85rem; background: var(--bg-card); padding: 8px 12px; border-radius: 6px; border-left: 3px solid var(--primary); margin-top: 10px;">
                    ℹ️ <strong>Интеграция:</strong> Клик по карточке счета открывает соответствующий markdown-файл в Obsidian, а клик по ссылкам <b>📄 PDF</b> открывает файлы документов из папки <code>60_Documents</code>.
                </div>
            `
        },
        geoHelpTrigger: {
            title: "🔍 GEO/SEO-аудиты: видимость в нейросетях",
            html: `
                <div style="margin-bottom: 14px; font-size: 0.85rem; color: var(--accent); background: rgba(0, 162, 232, 0.1); padding: 10px; border-radius: 6px; border-left: 4px solid var(--accent);">
                    <strong>Зачем это нужно:</strong> блок показывает, упоминают ли нейросети (ChatGPT, Perplexity, Claude, Gemini) бренд клиента, когда пользователь спрашивает их о «лучших подрядчиках». Например: <i>«Какие веб-студии на 1С-Битрикс лучшие в 2026?»</i> Если ИИ нас не называет — клиент к нам не приходит. Задача менеджера: видеть слабые метрики, вести чеклист работ и периодически перезапускать аудит.
                </div>

                <div style="margin-bottom: 14px;">
                    <strong style="color: var(--warning);">📊 Что означают колонки таблицы:</strong>
                    <ul style="font-size: 0.85rem; padding-left: 20px; line-height: 1.5; margin-top: 5px;">
                        <li><b>Visibility (честный)</b> — % ответов ИИ, где бренд упомянут <i>посторонними</i> источниками (самопрезентация самого сайта не считается — отсюда «честный»). Ориентиры: 🟢 ≥ 30%, 🟡 10–29%, 🔴 &lt; 10%.</li>
                        <li><b>Score</b> — общий балл 0–100: Visibility × 0.3 + SoV × 0.3 + Позиция × 0.4. Позиция — насколько близко к началу ответа упомянут бренд (в начале = лучше). 🟢 ≥ 50, 🟡 25–49, 🔴 &lt; 25.</li>
                        <li><b>SoV (Share of Voice)</b> — доля упоминаний бренда среди всех упоминаний niche (бренд + конкуренты), %.</li>
                        <li><b>Топ-конкуренты</b> — кого ИИ называет вместо нас и рядом с нами (с числом упоминаний в ответах).</li>
                        <li><b>Аудит</b> — дата последней проверки. Если старше 1–2 месяцев — данные устарели, пора повторять.</li>
                        <li>Серые строки («Аудит не проводился») — домены клиентов/проектов, которые ещё ни разу не проверяли.</li>
                    </ul>
                </div>

                <div style="margin-bottom: 14px;">
                    <strong style="color: var(--warning);">⚙️ Как работает конвейер (откуда данные):</strong>
                    <ol style="font-size: 0.85rem; padding-left: 20px; line-height: 1.5; margin-top: 5px;">
                        <li><b>Список доменов</b> берётся автоматически из vault: клиенты — карточки <code>10_Clients/*.md</code>, собственные проекты — файлы <code>50_Projects_Wiki/*-geo-plan.md</code> (поле <code>domain:</code> в шапке файла).</li>
                        <li><b>Проверка</b> (скрипт <code>geo-check.mjs</code> в репозитории AUTOMATASALE2026, по мотивам FireGEO): генерируются ~12 покупательских промптов 4 типов — «топ-10 лучших…», «сравни Бренд и Конкурента», «альтернативы Бренду», «что посоветуешь для бизнеса?» — и отправляются в AI-провайдеры (Perplexity, OpenAI, Anthropic, Gemini). В ответах ищутся упоминания бренда и конкурентов.</li>
                        <li><b>Отчёт</b> сохраняется в <code>reports/geo/geo-&lt;бренд&gt;-&lt;дата&gt;.json</code> (+ .md-версия для чтения).</li>
                        <li><b>Кнопка «↻ Обновить»</b> перечитывает vault и подтягивает свежие отчёты из <code>reports/geo/</code> в <code>dashboard/public/data/geo.json</code>, откуда их читает эта страница. <u>Важно:</u> кнопка сама новый AI-аудит не запускает — только импортирует уже готовые отчёты.</li>
                    </ol>
                </div>

                <div style="margin-bottom: 14px;">
                    <strong style="color: var(--success);">📋 Чеклисты GEO-задач (нижняя часть блока):</strong>
                    <ul style="font-size: 0.85rem; padding-left: 20px; line-height: 1.5; margin-top: 5px;">
                        <li>Это план работ по росту видимости: регистрации в рейтингах и каталогах, статьи на VC.ru / Habr, отзывы, llms.txt и т.п.</li>
                        <li>Хранятся в файле <code>50_Projects_Wiki/&lt;проект&gt;-geo-plan.md</code> в шапке: <code>tasks:</code> с полями <code>name</code>, <code>priority</code> (P0 — срочно / P1 / P2) и <code>status</code> (planned / in_progress / done).</li>
                        <li>Менеджеру: брать верхние невыполненные P0 → P1, выполнять, отмечать статус — прогресс-бар обновится после «↻ Обновить».</li>
                    </ul>
                </div>

                <div style="font-size: 0.85rem; background: var(--bg-card); padding: 10px 12px; border-radius: 6px; border-left: 3px solid var(--primary);">
                    🚀 <strong>Запустить новый аудит проекта:</strong> в репозитории проекта выполнить <code>node scripts/geo-check.mjs --brand "Бренд" --url домен.ru --competitors "Конкурент1,Конкурент2"</code> (нужны API-ключи в .env), затем нажать «↻ Обновить» здесь. Чтобы добавить проект в таблицу — создайте <code>50_Projects_Wiki/&lt;имя&gt;-geo-plan.md</code> с <code>domain:</code> в шапке; бренд/конкурентов можно задать в карточке клиента блоком <code>geo:</code> (brand, industry, competitors).
                </div>
            `
        }
    };

    triggers.forEach(t => {
        t.onclick = (e) => {
            const data = content[e.target.id];
            if (data) {
                title.textContent = data.title;
                body.innerHTML = data.html;
                modal.classList.add('active');
            }
        };
    });

    closeBtn.onclick = () => modal.classList.remove('active');
    
    window.onclick = (e) => {
        if (e.target === modal) modal.classList.remove('active');
    };

    document.onkeydown = (e) => {
        if (e.key === "Escape" && modal.classList.contains('active')) {
            modal.classList.remove('active');
        }
    };
}

// ─────────────────────────────────────────────────────────────────
// Unanswered Leads Table
// ─────────────────────────────────────────────────────────────────
// Start app
document.addEventListener('DOMContentLoaded', init);

// ─────────────────────────────────────────────────────────────────
// 💬 ЧАТ — основа CRM (редизайн 14.09.2026: единая лента по мокапу Заметки/index.html)
// Один клиент = одна лента: TG/MAX/почта вперемешку, карточка клиента справа.
// ─────────────────────────────────────────────────────────────────
const chatState = { client: null, chatId: null, filter: 'all', author: 'me', seg: 'all', query: '', threads: [], chats: [] };

const ROLE_LABELS = { gendir: '🎯 Гендир', findir: '💰 Финдир', komdir: '📞 Комдир', marketing: '📝 Маркетолог', lawyer: '⚖️ Юрист', cycle: '⚙️ Цикл' };

const CH_ICON = { telegram: 'i-tg', max: 'i-max', email: 'i-mail', webchat: 'i-grid' };
const CH_NAME = { telegram: 'Telegram', max: 'MAX', email: 'Почта', webchat: 'Web' };
const KNOWN_CHATS = { /* 'chat_id': 'Название чата' — свои известные чаты */ };

async function chatApi(path, opts) {
    const res = await fetch(`${API_BASE.replace('/api', '')}${path}`, opts);
    if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
    return res.json();
}

function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function initials(name) {
    const w = String(name || '?').trim().split(/\s+/).filter(Boolean);
    return (((w[0] || '?')[0]) + (w[1] ? w[1][0] : '')).toUpperCase();
}
function fmtTime(ts) { return String(ts || '').slice(11, 16); }
function fmtThreadTime(ts) {
    const s = String(ts || '');
    const today = new Date().toISOString().slice(0, 10);
    const yest = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    if (s.slice(0, 10) === today) return s.slice(11, 16);
    if (s.slice(0, 10) === yest) return 'вчера';
    return s.slice(8, 10) + '.' + s.slice(5, 7);
}
function fmtDay(ts) {
    const d = String(ts || '').slice(0, 10);
    const today = new Date().toISOString().slice(0, 10);
    const yest = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    if (d === today) return 'Сегодня';
    if (d === yest) return 'Вчера';
    const months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
    return (+d.slice(8, 10)) + ' ' + (months[+d.slice(5, 7) - 1] || '');
}
function chIconSvg(channel, size = 9) {
    return `<svg width="${size}" height="${size}"><use href="#${CH_ICON[channel] || 'i-grid'}"/></svg>`;
}

function renderThreads() {
    const box = document.getElementById('chatThreads');
    if (!box) return;
    let list = chatState.threads;
    if (chatState.query) list = list.filter(t => t.client.toLowerCase().includes(chatState.query));
    if (chatState.seg === 'unread') list = list.filter(t => (t.unread || 0) > 0);
    if (chatState.seg === 'leads') {
        const leads = ((window.__dashData || lastDashboardData)?.leads || [])
            .map(l => String(l.name || l.client || l.id || '').toLowerCase()).filter(Boolean);
        list = list.filter(t => leads.some(n => t.client.toLowerCase().includes(n) || n.includes(t.client.toLowerCase())));
    }
    const chChip = document.getElementById('chatChannelsChip');
    if (chChip) {
        const set = new Set(chatState.threads.flatMap(t => t.channels || []));
        chChip.textContent = set.size ? `${set.size} канал${set.size === 1 ? '' : 'ов'} активны` : '— каналов';
    }
    box.innerHTML = list.map(t => {
        const lastCh = (t.channels || [])[0] || 'telegram';
        const chips = (t.channels || []).map(ch =>
            `<span class="chip ${ch}"><i></i>${CH_NAME[ch] || ch}</span>`).join('');
        return `
        <div class="dlg ${chatState.client === t.client ? 'active' : ''}" data-client="${esc(t.client)}">
            <div class="dlg-av">${esc(initials(t.client))}<span class="ch ${lastCh}">${chIconSvg(lastCh)}</span></div>
            <div class="dlg-body">
                <div class="dlg-row">
                    <div class="dlg-name">${esc(t.client)}</div>
                    <div class="dlg-time">${fmtThreadTime(t.last_ts)}</div>
                </div>
                <div class="dlg-prev">${t.last_direction === 'outgoing' ? '→ ' : ''}${esc(t.last_text || '')}</div>
                <div class="dlg-meta">${chips}${t.unread ? `<span class="badge-n">${t.unread}</span>` : ''}</div>
            </div>
        </div>`;
    }).join('') || `<div class="chat-empty">${chatState.seg === 'leads' ? 'Лидов в чатах нет' : 'Нет диалогов'}</div>`;
    box.querySelectorAll('.dlg').forEach(el =>
        el.addEventListener('click', () => openChatThread(el.dataset.client)));
}

async function loadChatThreads() {
    try {
        const d = await chatApi('/api/chat/threads');
        chatState.threads = d.threads || [];
        renderThreads();
    } catch (e) { console.warn('threads:', e); }
}

async function openChatThread(client) {
    chatState.client = client;
    chatApi('/api/chat/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client })
    }).catch(() => {});
    const th = chatState.threads.find(t => t.client === client);
    document.getElementById('chatTitle').textContent = client;
    document.getElementById('chatSub').textContent = th
        ? `${(th.channels || []).map(c => CH_NAME[c] || c).join(' + ')} · ${th.messages} сообщений`
        : 'единая лента коммуникаций';
    renderThreads();
    await renderChatFeed();
    renderChatCard();
    loadChatThreads();
}

function chatSourceLabel(m) {
    if (m.channel === 'team') return `<b>Совет</b> · ${esc(ROLE_LABELS[m.author] || m.author || 'роль')}`;
    if (m.channel === 'email') return `<b>Почта</b> · ${esc(m.contact || m.author || '')}`;
    const cid = String(m.chat_id || '');
    if (m.channel === 'max') return cid.startsWith('-') ? '<b>Группа MAX</b>' : `<b>Личка MAX</b> · ${esc(m.author || '')}`;
    if (cid.startsWith('-')) return `<b>Группа</b>${KNOWN_CHATS[cid] ? ` «${esc(KNOWN_CHATS[cid])}»` : ''}`;
    return `<b>Личка</b> · ${esc(m.author || '')}`;
}

function renderMsg(m) {
    const out = m.direction === 'outgoing';
    const jarvis = out && m.author === 'jarvis';
    const ch = m.channel || 'webchat';
    const time = fmtTime(m.ts);
    if (jarvis) {
        return `
        <div class="msg">
            <div class="msg-av ai"><svg width="17" height="17"><use href="#i-robot"/></svg><span class="ch ${ch}">${chIconSvg(ch)}</span></div>
            <div>
                <div class="msg-top">
                    <span class="msg-who">Automata CRM assist</span>
                    <span class="chip" style="color:var(--accent);border-color:rgba(45,212,191,.28);background:rgba(45,212,191,.08)">ИИ-ассистент</span>
                    <span class="msg-src">${chatSourceLabel(m)}</span>
                    <span class="msg-time">${time}</span>
                </div>
                <div class="bub ai"><div class="ai-tag"><svg width="12" height="12"><use href="#i-robot"/></svg>Automata CRM assist · ИИ-ассистент Евгения</div>${esc(m.text)}</div>
            </div>
        </div>`;
    }
    if (out) { // от Евгения — прижато вправо
        return `
        <div class="msg">
            <div class="msg-av me">ЕУ</div>
            <div class="feed-right">
                <div class="msg-top">
                    <span class="msg-who">Евгений</span>
                    <span class="chip">вы</span>
                    <span class="msg-src">${chatSourceLabel(m)}</span>
                    <span class="msg-time">${time}</span>
                </div>
                <div class="bub out">${esc(m.text)}</div>
            </div>
        </div>`;
    }
    const who = m.author || m.contact || 'Клиент';
    return `
        <div class="msg">
            <div class="msg-av">${esc(initials(who))}<span class="ch ${ch}">${chIconSvg(ch)}</span></div>
            <div>
                <div class="msg-top">
                    <span class="msg-who">${esc(who)}</span>
                    <span class="msg-src">${chatSourceLabel(m)}</span>
                    <span class="msg-time">${time}</span>
                </div>
                <div class="bub">${m.channel === 'email' && m.contact ? `<div class="bub-mail"><b>От:</b> ${esc(m.contact)}</div>` : ''}${esc(m.text)}</div>
            </div>
        </div>`;
}

async function renderChatFeed() {
    const feed = document.getElementById('chatFeed');
    if (!chatState.client) return;
    feed.innerHTML = '<div class="chat-empty">Загрузка…</div>';
    try {
        let url = `/api/chat/messages?client=${encodeURIComponent(chatState.client)}&limit=300`;
        if (chatState.filter !== 'all') url += `&channel=${chatState.filter}`;
        const d = await chatApi(url);
        const msgs = (d.messages || []).slice().sort((a, b) => String(a.ts).localeCompare(String(b.ts))); // хронология: новые внизу
        // TG-адресаты клиента: группы (по словарю) + лички (по автору)
        const targets = [];
        const seen = new Set();
        const chatCount = {};
        const seenChat = new Set();
        const chatItems = [];
        for (const m of msgs) {
            const cid = String(m.chat_id || '');
            const key = `${m.channel}:${cid || m.contact || m.author || ''}`;
            chatCount[key] = (chatCount[key] || 0) + 1;
            if (seenChat.has(key)) continue;
            seenChat.add(key);
            let title, type;
            if (m.channel === 'email') { title = m.contact || 'Почта'; type = 'Почта · ' + (m.contact || 'почта'); }
            else if (m.channel === 'max') { title = cid.startsWith('-') ? 'Группа MAX' : (m.author || 'MAX'); type = 'MAX · ' + (cid.startsWith('-') ? 'группа' : 'личка'); }
            else {
                const who = (m.contact && m.contact !== 'me' && m.contact !== 'jarvis') ? m.contact
                    : (m.author && m.author !== 'me' && m.author !== 'jarvis' ? m.author : '');
                title = KNOWN_CHATS[cid] || (cid.startsWith('-') ? `Группа ${cid}` : (who || 'Личка'));
                type = 'Telegram · ' + (cid.startsWith('-') ? 'группа' : 'личка');
            }
            chatItems.push({ channel: m.channel, title, type, key });
            if (m.channel !== 'telegram' || !/^-?\d{5,}$/.test(cid) || seen.has(cid)) continue;
            seen.add(cid);
            targets.push({ cid, title, ts: m.ts });
        }
        targets.sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
        chatItems.forEach(c => { c.count = chatCount[c.key]; });
        chatState.chats = chatItems;

        const sel = document.getElementById('chatTarget');
        if (sel) {
            sel.innerHTML = targets.map(x => `<option value="${x.cid}">→ ${x.title}</option>`).join('') ||
                '<option value="">нет TG-чатов</option>';
            chatState.chatId = targets.length ? targets[0].cid : null;
        }
        const composer = document.getElementById('chatComposer');
        composer.style.display = targets.length ? 'block' : 'none';

        // лента + разделители дней
        let html = '', lastDay = '';
        for (const m of msgs) {
            const day = fmtDay(m.ts);
            if (day !== lastDay) { html += `<div class="divider"><span>${day}</span></div>`; lastDay = day; }
            if (m.direction === 'event') {
                html += `<div class="m-event"><svg width="12" height="12" style="color:var(--accent)"><use href="#i-robot"/></svg>${esc(m.author)}: ${esc(String(m.text).slice(0, 180))}</div>`;
            } else {
                html += renderMsg(m);
            }
        }
        feed.innerHTML = html || '<div class="chat-empty">Нет сообщений по фильтру</div>';
        const scroller = feed.closest('.scroll');
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
    } catch (e) {
        feed.innerHTML = `<div class="chat-empty">Ошибка: ${esc(e.message)}</div>`;
    }
}

async function chatSendMessage() {
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    const sel = document.getElementById('chatTarget');
    if (sel && sel.value) chatState.chatId = sel.value;
    if (!text || !chatState.chatId) return;
    input.value = '';
    input.style.height = 'auto';
    try {
        await chatApi('/api/chat/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_id: chatState.chatId, text, author: chatState.author })
        });
        setTimeout(renderChatFeed, 1500);
    } catch (e) { alert('Не отправилось: ' + e.message); }
}

function fmtMoney(n) { return new Intl.NumberFormat('ru-RU').format(Math.round(n || 0)) + ' ₽'; }

function renderChatCard() {
    const card = document.getElementById('chatCard');
    if (!card || !chatState.client) return;
    const data = lastDashboardData || {};
    const cl = (data.clients || []).find(c => c.name === chatState.client)
        || (data.clients || []).find(c => (c.name || '').toLowerCase().includes(chatState.client.toLowerCase()));
    const unpaid = (data.meta?.unpaid_invoices || [])
        .filter(i => (i.client || '').toLowerCase().includes(chatState.client.toLowerCase()));
    const debt = unpaid.reduce((s, i) => s + (i.amount || 0), 0);
    const allTasks = Object.values(data.meta?.tasks_matrix || {}).flat();
    const tasks = allTasks.filter(t => (t.client || '').toLowerCase().includes(chatState.client.toLowerCase())).slice(0, 5);
    const chats = chatState.chats || [];
    const th = chatState.threads.find(t => t.client === chatState.client);
    let answers = '—';
    if (th?.last_ts) {
        const iso = String(th.last_ts).replace(' ', 'T');
        const h = (Date.now() - new Date(iso).getTime()) / 36e5;
        if (!isNaN(h)) answers = h >= 24 ? Math.round(h / 24) + ' д' : Math.max(1, Math.round(h)) + ' ч';
    }
    const chatIco = c => c.channel === 'email' ? 'i-mail'
        : (c.type.includes('группа') ? 'i-grp' : 'i-person');
    card.innerHTML = `
        <div class="cc-head">
            <div>
                <div class="cc-name">${esc(chatState.client)}</div>
                <div class="cc-status"><i class="dot ${cl?.lifecycle === 'active' ? 'ok' : 'warn'}"></i>${cl?.lifecycle === 'active' ? 'активен' : (cl?.lifecycle || 'клиент')} · отвечает ${answers}</div>
            </div>
        </div>
        <div class="scroll">
            <div class="cc-stats">
                <div class="cc-stat"><b>${esc(cl ? (cl.support_plan || (cl.support_type && cl.support_type !== 'none' ? cl.support_type : '') || '—') : '—')}</b><span>тариф</span></div>
                <div class="cc-stat"><b class="${debt > 0 ? 'warn' : ''}">${fmtMoney(debt)}</b><span>к оплате</span></div>
                <div class="cc-stat"><b>${cl?.hours_used_current_month != null ? cl.hours_used_current_month + ' ч' : '—'}</b><span>часы / мес</span></div>
            </div>

            <div class="sec">
                <div class="sec-title"><svg width="13" height="13"><use href="#i-chat"/></svg>Чаты клиента<span class="n">${chats.length}</span></div>
                <div class="chat-list">
                    ${chats.map((c, i) => `
                    <div class="chat-item ${i === 0 ? 'on' : ''}" title="${esc(c.type)}">
                        <div class="chat-ico ${c.channel}"><svg width="14" height="14"><use href="#${chatIco(c)}"/></svg></div>
                        <div class="chat-txt">
                            <div class="chat-nm">${esc(c.title)}</div>
                            <div class="chat-tp">${esc(c.type)}</div>
                        </div>
                        <div class="chat-ct">${c.count}</div>
                    </div>`).join('') || '<div class="task-empty">Нет чатов</div>'}
                </div>
            </div>

            <div class="sec">
                <div class="sec-title"><svg width="13" height="13"><use href="#i-grid"/></svg>Действия</div>
                <div class="acts">
                    <button class="act" data-goto="tab-clients"><svg width="14" height="14"><use href="#i-users"/></svg>Клиенты</button>
                    <button class="act" data-jump="#tab-today/eisenhowerMatrix"><svg width="14" height="14"><use href="#i-eye"/></svg>Матрица</button>
                    <button class="act" data-jump="#tab-today/tableUnpaid"><svg width="14" height="14"><use href="#i-card"/></svg>Счета</button>
                    <button class="act" data-obsidian="60_Documents"><svg width="14" height="14"><use href="#i-doc"/></svg>Документы</button>
                </div>
            </div>

            <div class="sec">
                <div class="sec-title"><svg width="13" height="13"><use href="#i-robot"/></svg>Участники<span class="n">3</span></div>
                <div class="people">
                    <div class="person"><div class="p-av ai"><svg width="15" height="15"><use href="#i-robot"/></svg></div>
                        <div class="p-txt"><div class="p-nm">Automata CRM assist</div><div class="p-role">ИИ-ассистент Евгения · отвечает во всех чатах</div></div></div>
                    <div class="person"><div class="p-av" style="color:var(--accent);border-color:rgba(45,212,191,.3)">ЕУ</div>
                        <div class="p-txt"><div class="p-nm">Евгений</div><div class="p-role">владелец · решения и «ок»</div></div></div>
                    <div class="person"><div class="p-av">${esc(initials(chatState.client))}</div>
                        <div class="p-txt"><div class="p-nm">${esc(chatState.client)}</div><div class="p-role">клиент${cl?.telegram ? ' · TG ' + esc(cl.telegram) : ''}</div></div></div>
                </div>
            </div>

            <div class="sec">
                <div class="sec-title"><svg width="13" height="13"><use href="#i-check"/></svg>Задачи<span class="n">${tasks.length}</span></div>
                <div class="tasks">
                    ${tasks.map(t => {
                        const taskPath = encodeURIComponent('30_Tasks/' + t.id);
                        return `<div class="task" onclick="window.open('obsidian://open?vault=AUTOMATA-CRM&file=${taskPath}')">
                            <i class="cb"></i>${esc(t.title)}<span class="due">${esc(t.date || '')}</span></div>`;
                    }).join('') || '<div class="task-empty">Задач по клиенту нет — <span style="color:var(--accent);cursor:pointer" data-jump="#tab-today/eisenhowerMatrix">вся матрица →</span></div>'}
                </div>
            </div>

            <div class="health" id="chatHealth">
                <div class="health-h"><i class="dot ok"></i>Здоровье интеграций
                    <svg width="13" height="13" style="margin-left:auto;color:var(--text-muted)" data-jump="#tab-system"><use href="#i-chev"/></svg>
                </div>
                <div class="hgrid" id="chatHealthGrid"><div class="hrow"><span>Загрузка…</span></div></div>
            </div>
        </div>`;
    card.querySelectorAll('[data-goto]').forEach(b =>
        b.addEventListener('click', () => document.querySelector(`.tab-btn[data-tab="${b.dataset.goto}"]`)?.click()));
    card.querySelectorAll('[data-jump]').forEach(b =>
        b.addEventListener('click', () => {
            const [tabId, anchor] = b.dataset.jump.slice(1).split('/');
            document.querySelector(`.tab-btn[data-tab="${tabId}"]`)?.click();
            if (anchor) setTimeout(() => document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120);
        }));
    card.querySelectorAll('[data-obsidian]').forEach(b =>
        b.addEventListener('click', () => window.open(`obsidian://open?vault=AUTOMATA-CRM&file=${encodeURIComponent(b.dataset.obsidian)}`)));
    fillChatHealth();
}

async function fillChatHealth() {
    const grid = document.getElementById('chatHealthGrid');
    if (!grid) return;
    let d = window.__integrStatus;
    if (!d) {
        try { d = await automataApi.getIntegrationsStatus(); window.__integrStatus = d; }
        catch (e) { grid.innerHTML = '<div class="hrow"><span>Статус недоступен</span></div>'; return; }
    }
    const tg = d.tg_gateway || {}, poller = d.tg_poller || {}, mx = d.max || {}, mail = d.mail || {}, mk = d.mk_site || {};
    const rows = [
        ['Telegram', !!tg.ok, tg.ok ? 'OK' : 'сбой'],
        ['userbot-сессия', !!tg.userbot_alive, tg.userbot_alive ? 'OK' : 'мёртв'],
        ['MAX', !!mx.ok, mx.ok ? `${mx.groups ?? '—'} гр.` : 'сбой'],
        ['Очередь', true, tg.ms != null ? tg.ms + 'мс' : '—'],
        ['Почта', !!mail.ok, mail.ok ? 'OK' : 'ошибка'],
        ['IMAP', true, mail.imap_ms ? mail.imap_ms + 'мс' : '—'],
        ['Мониторинг', mk.ok !== undefined ? !!mk.ok : true, mk.ok ? 'OK' : (mk.ok === undefined ? '—' : 'сбой')],
        ['Агенты CRM', !!poller.ok, poller.ok ? 'OK' : 'стоп'],
        ['Последняя отправка', true, mail.last_send ? String(mail.last_send).slice(11, 16) : '—'],
    ];
    grid.innerHTML = rows.map(([n, ok, v]) =>
        `<div class="hrow"><i class="dot ${ok ? 'ok' : 'err'}" style="width:5px;height:5px"></i><span>${n}</span><b>${esc(v)}</b></div>`).join('');
    const h = document.getElementById('chatHealth');
    if (h) h.querySelector('.health-h .dot').className = `dot ${rows.every(r => r[1]) ? 'ok' : 'err'}`;
}

function initChatUI() {
    loadChatThreads();
    document.getElementById('chatSendBtn')?.addEventListener('click', chatSendMessage);
    const input = document.getElementById('chatInput');
    input?.addEventListener('keydown', e => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || !e.shiftKey)) {
            e.preventDefault();
            chatSendMessage();
        }
    });
    input?.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 110) + 'px';
    });
    document.querySelectorAll('#chatFilters button').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('#chatFilters button').forEach(c => c.classList.remove('on'));
            chip.classList.add('on');
            chatState.filter = chip.dataset.ch;
            renderChatFeed();
        });
    });
    document.querySelectorAll('#chatSeg button').forEach(seg => {
        seg.addEventListener('click', () => {
            document.querySelectorAll('#chatSeg button').forEach(s => s.classList.remove('on'));
            seg.classList.add('on');
            chatState.seg = seg.dataset.seg;
            renderThreads();
        });
    });
    document.getElementById('chatSearch')?.addEventListener('input', e => {
        chatState.query = e.target.value.trim().toLowerCase();
        renderThreads();
    });
    document.querySelectorAll('#chatAuthorSeg button').forEach(b => {
        b.addEventListener('click', () => {
            document.querySelectorAll('#chatAuthorSeg button').forEach(x => x.classList.remove('on'));
            b.classList.add('on');
            chatState.author = b.dataset.author;
        });
    });
    // чип «N/N канала» в топбаре → вкладка «Система»
    document.getElementById('chipIntegrations')?.addEventListener('click', () => {
        document.querySelector('.tab-btn[data-tab="tab-system"]')?.click();
    });
    // глобальный поиск в топбаре → поиск по диалогам чата
    document.getElementById('topSearch')?.addEventListener('click', () => {
        document.querySelector('.tab-btn[data-tab="tab-chat"]')?.click();
        setTimeout(() => document.getElementById('chatSearch')?.focus(), 120);
    });
}

// ─────────────────────────────────────────────────────────────────
// ⚙️ Статусы интеграций в реальном времени (шапка + вкладка Система)
// ─────────────────────────────────────────────────────────────────
async function renderIntegrationsStatus() {
    let d;
    try {
        d = await automataApi.getIntegrationsStatus();
    } catch (e) { return; }

    const setPill = (id, ok, label, title) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.className = `status-pill ${ok ? 'active' : 'error'}`;
        el.querySelector('.status-label').textContent = label;
        el.title = title;
    };

    const tg = d.tg_gateway || {}, poller = d.tg_poller || {}, mx = d.max || {},
          mail = d.mail || {}, act = d.activity || {}, mk = d.mk_site || {};
    const tgOk = tg.ok && tg.userbot_alive && poller.ok;
    const mxOk = mx.ok && mx.listener_alive;

    // чип в топбаре + блок «Здоровье» в карточке клиента (редизайн 14.09.2026)
    window.__integrStatus = d;
    const chip = document.getElementById('chipIntegrations');
    if (chip) {
        const okCount = [tgOk, mxOk, mail.ok, mk.ok !== false].filter(Boolean).length;
        const ms = [tg.ms, mx.ms, mail.imap_ms].filter(x => x != null);
        chip.classList.toggle('err', okCount < 4);
        chip.querySelector('.dot').className = `dot ${okCount >= 4 ? 'ok' : 'err'}`;
        const okEl = document.getElementById('chipOkCount');
        if (okEl) okEl.textContent = `${okCount}/4`;
        const msEl = document.getElementById('chipMs');
        if (msEl) msEl.textContent = ms.length ? `· ${Math.min(...ms)}мс` : '';
        chip.title = `TG: ${tg.userbot_alive ? 'жив' : 'мёртв'} · MAX: ${mx.listener_alive ? 'жив' : 'мёртв'} · Почта: ${mail.ok ? 'ок' : 'ошибка ' + (mail.error || '')} · Monitor: ${mk.ok ? 'ок' : '—'}\nПодробнее — вкладка «Система»`;
    }
    fillChatHealth();

    // Шапка: TG / MAX / Почта
    setPill('tgStatus', tgOk,
        `TG: ${tg.userbot || '—'}${poller.lag > 20 ? ' ⚠отст.' + poller.lag : ''}`,
        `Шлюз: ${tg.ms ?? '—'} мс · userbot: ${tg.userbot_alive ? 'жив' : 'МЁРТВ'} · очередь: ${tg.queue_events ?? '—'} · dead-letter: ${poller.dead_letter ?? 0}`);
    setPill('maxStatus', mxOk,
        `MAX: ${mx.groups || 0} гр.${mx.ms ? ' · ' + mx.ms + 'мс' : ''}`,
        `Bot API: ${mx.ok ? 'ок (' + mx.ms + 'мс, ' + (mx.bot || '?') + ')' : 'недоступен'} · слушатель: ${mx.listener_alive ? 'жив' : 'МЁРТВ'}`);
    setPill('mailStatus', mail.ok,
        `✉ Почта${mail.imap_ms ? ' · ' + mail.imap_ms + 'мс' : ''}`,
        `IMAP: ${mail.ok ? 'ок' : 'ОШИБКА ' + (mail.error || '')} · SMTP: ${mail.smtp_ms ? mail.smtp_ms + 'мс' : '—'} · последняя отправка: ${mail.last_send || '—'}`);

    // Вкладка «Система»: карточки
    const box = document.getElementById('systemStatusList');
    if (!box) return;
    const card = (icon, name, ok, detail, warn) => `
        <div class="integr-card" style="border-left: 3px solid ${warn ? '#facc15' : ok ? '#4ade80' : '#ef4444'};">
            <div class="integr-head"><span>${icon} <strong>${name}</strong></span>
                <span style="color:${warn ? '#facc15' : ok ? '#4ade80' : '#ef4444'}">${warn ? '🟡 внимание' : ok ? '🟢 ок' : '🔴 сбой'}</span></div>
            <div class="integr-detail">${detail}</div>
        </div>`;
    box.innerHTML = `
        <div class="integr-grid">
        ${card('🟢', 'TG-шлюз (VPS)', tg.ok, `${tg.ms ?? '—'} мс · очередь: ${tg.queue_events ?? '—'} соб, pending outbox: ${tg.pending_outbox ?? '—'}`)}
        ${card('🤖', 'TG Userbot', tg.userbot_alive, tg.userbot_alive ? `heartbeat жив · аккаунт: ${tg.userbot || '—'}` : 'heartbeat пропал (&gt;90с) — проверить systemctl status tg-userbot на VPS')}
        ${card('📥', 'TG-поллер', poller.ok, `курсор: ${poller.cursor ?? '—'} · отставание: ${poller.lag ?? '—'} · dead-letter: ${poller.dead_letter ?? 0}`)}
        ${card('🟣', 'MAX Bot API', mx.ok, `${mx.bot || '—'} · ${mx.ms ?? '—'} мс · слушатель: ${mx.listener_alive ? 'жив' : 'МЁРТВ'} · групп: ${mx.groups ?? '—'}`)}
        ${card('✉️', 'Почта IMAP', mail.ok, `${mail.imap_ms ?? '—'} мс ${mail.error ? '· ' + esc(mail.error) : ''}`)}
        ${card('📤', 'Почта SMTP', !!mail.smtp_ms, `${mail.smtp_ms ? mail.smtp_ms + ' мс' : 'недоступен'} · последняя отправка: ${mail.last_send || '—'}`)}
        ${card('⏱', 'Активность конвейера', !!act.last_activity, `последнее сообщение: ${act.last_activity || '—'}${act.age_min != null ? ' (' + act.age_min + ' мин назад)' : ''}`, act.age_min != null && act.age_min > 180)}
        ${card('🌐', 'Health-check сайта', mk.ok, mk.ok ? `${mk.ms} мс` : 'недоступен')}
        ${card('🔄', 'Проверено', true, `в ${d.checked_at} · автообновление 60с`)}
        </div>`;
    document.querySelectorAll('#maxStatus, #mailStatus').forEach(el => {
        el.onclick = () => document.querySelector('.tab-btn[data-tab="tab-system"]')?.click();
    });
}

function initIntegrationsStatus() {
    renderIntegrationsStatus();
    setInterval(renderIntegrationsStatus, 60000);
}

/* ---------- Сейф ПД: замок в шапке (зелёный — открыто, красный — закрыто) ---------- */
async function setupPdSafe() {
    const btn = document.getElementById('pdSafeBtn');
    if (!btn) return;

    const paint = (st) => {
        if (!st || st.daemon === false || st.open === null || st.open === undefined) {
            btn.style.color = '#9ca3af';
            btn.title = 'Сейф ПД: демон не запущен — пароль не введён (автозапуск при входе в систему)';
            return;
        }
        if (st.open) {
            btn.style.color = '#22c55e';
            btn.title = 'Сейф ПД: база ОТКРЫТА · нажать — зашифровать';
        } else {
            btn.style.color = '#ef4444';
            btn.title = 'Сейф ПД: база ЗАКРЫТА · нажать — расшифровать';
        }
    };

    const refresh = async () => {
        try { paint(await fetchApi('/pd_safe/status')); }
        catch { paint(null); }
    };

    btn.addEventListener('click', async () => {
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.5';
        try {
            const st = await fetchApi('/pd_safe/status');
            if (st.daemon === false) {
                showToast('Сейф ПД: демон не запущен — пароль не введён', 'warn');
                paint(st);
                return;
            }
            const action = st.open ? 'lock' : 'unlock';
            const res = await fetchApi(`/pd_safe/${action}`, { method: 'POST' });
            paint(res);
            showToast(res.open
                ? '🔓 База персональных данных расшифрована'
                : '🔒 База персональных данных зашифрована', 'ok');
        } catch (e) {
            showToast('Сейф ПД: ошибка — ' + e.message, 'err');
        } finally {
            btn.style.pointerEvents = '';
            btn.style.opacity = '';
            refresh();
        }
    });

    refresh();
    setInterval(refresh, 30000); // цвет остаётся актуальным при ручных lock/unlock из консоли
}
