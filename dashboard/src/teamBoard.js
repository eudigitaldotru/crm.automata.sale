/**
 * teamBoard.js — вкладка «Совет» (Команда Автомата)
 * KPI-полоса (цели/дебиторка/красный список), очередь решений «❓» с кнопками а/б/в,
 * лента вердиктов ролей из company/journal. Данные: GET /api/company/board.
 */
import { fetchApi } from './apiClient';
import { formatRub } from './utils/data-loader';
import { showToast } from './utils/toast';
import { renderOrg, initOrg } from './teamOrg';

const ROLE_EMOJI = { gendir: '🎯', findir: '💰', komdir: '📞', marketing: '📝', lawyer: '⚖️', cycle: '⚙️' };
const ROLE_NAME = { gendir: 'Гендир', findir: 'Финдир', komdir: 'Комдир', marketing: 'Маркетолог', lawyer: 'Юрист', cycle: 'Цикл' };

let boardTimer = null;

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function roleBadge(role) {
    return `<span class="board-role-badge">${ROLE_EMOJI[role] || '🤖'} ${esc(ROLE_NAME[role] || role || 'роль')}</span>`;
}

async function loadBoard() {
    const root = document.getElementById('boardRoot');
    if (!root) return;
    let data;
    try {
        data = await fetchApi('/company/board');
    } catch (e) {
        root.innerHTML = `<div class="board-error">⚠️ Совет недоступен: ${esc(e.message)}</div>`;
        return;
    }
    if (!data || data.ok === false) {
        root.innerHTML = '<div class="board-error">⚠️ Пустой ответ API</div>';
        return;
    }
    updateBadge(data.questions_open || 0);
    renderBoard(root, data);
}

function updateBadge(n) {
    const b = document.getElementById('boardQBadge');
    if (!b) return;
    b.style.display = n > 0 ? '' : 'none';
    b.textContent = String(n);
}

function renderBoard(root, d) {
    const openQ = (d.questions || []).filter(q => !q.answered);
    const doneQ = (d.questions || []).filter(q => q.answered);

    const goalsHtml = (d.goals || []).map(g => {
        const cur = g.current ?? 0, tgt = g.target ?? 1;
        let pct, pctLabel;
        if (g.direction === 'decrease') {
            // цели на снижение: чем ближе cur к tgt, тем ближе к 100%
            pct = cur > 0 ? Math.max(0, Math.min(100, Math.round(tgt / cur * 100))) : 100;
            pctLabel = `↓ ${fmtNum(cur)}${esc(g.unit)} → ${fmtNum(tgt)}`;
        } else {
            pct = Math.max(0, Math.min(100, tgt ? Math.round(cur / tgt * 100) : 0));
            pctLabel = `${pct}%`;
        }
        const dl = (g.deadline || '').split('-').reverse().join('.');
        return `
        <div class="board-goal">
            <div class="board-goal-name">${esc(g.title)}</div>
            <div class="board-goal-row">
                <span class="board-goal-num">${fmtNum(cur)} <i>/ ${fmtNum(tgt)} ${esc(g.unit)}</i></span>
                <span class="board-goal-pct">${pctLabel}</span>
            </div>
            <div class="board-bar"><div class="board-bar-fill" style="width:${pct}%"></div></div>
            ${dl ? `<div class="board-goal-meta">до ${dl}</div>` : ''}
        </div>`;
    }).join('');

    const debt = d.debt || {};
    const red = d.red_list || [];

    const qHtml = openQ.length ? openQ.map(q => `
        <div class="board-q" data-qid="${esc(q.id)}">
            <div class="board-q-head">${roleBadge(q.role)} <span class="board-q-date">${esc(q.date)}</span></div>
            <div class="board-q-text">${esc(q.question)}</div>
            <div class="board-q-opts">
                ${q.options.map(o => `<button class="board-q-btn" data-qid="${esc(q.id)}" data-choice="${esc(o.key)}"><span class="board-q-key">${esc(o.key)})</span><span>${esc(o.text)}</span></button>`).join('')}
            </div>
        </div>`).join('')
        : '<div class="board-empty">✅ Открытых вопросов нет — совет ждёт ритуалов.</div>';

    const doneHtml = doneQ.length ? `
        <div class="board-done">
            <div class="board-done-title">✅ Принятые решения</div>
            ${doneQ.slice(0, 5).map(q => `<div class="board-done-item"><span class="board-done-ico">✓</span><span>${esc(q.question)} → <span class="board-done-chip">${esc(q.answer.choice)}) ${esc(q.answer.text || '')}</span> <span class="muted">(${esc((q.answer.answered_at || '').replace('T', ' ').slice(0, 16))})</span></span></div>`).join('')}
        </div>` : '';

    const journalHtml = (d.journal || []).map(j => `
        <details class="board-j-entry">
            <summary>${roleBadge(j.role)} <span class="board-j-title">${esc(j.title)}</span> <span class="board-j-date">${esc(j.date)}</span></summary>
            <div class="board-j-body">${esc(j.excerpt)}…</div>
        </details>`).join('') || '<div class="board-empty">Журнал пуст.</div>';

    root.innerHTML = `
    <div class="board-kpis">
        <div class="board-kpi board-kpi--goals">
            <div class="board-kpi-title">🎯 Цели</div>${goalsHtml || '<div class="board-empty">нет активных</div>'}
        </div>
        <div class="board-kpi ${debt.total > 0 ? 'board-kpi--warn' : ''}">
            <div class="board-kpi-title">📥 Дебиторка</div>
            <div class="board-kpi-big">${formatRub(debt.total || 0)}</div>
            <div class="board-kpi-meta">${debt.count || 0} счетов · старейший ${esc(debt.oldest || '—')}</div>
        </div>
        <div class="board-kpi ${red.length ? 'board-kpi--warn' : ''}">
            <div class="board-kpi-title">🔴 Красный список дня</div>
            <div class="board-kpi-big">${red.length}</div>
            <div class="board-kpi-meta">${red.slice(0, 3).map(esc).join('<br>')}${red.length > 3 ? '<br>…' : ''}</div>
        </div>
        <div class="board-kpi ${openQ.length ? 'board-kpi--hot' : ''}">
            <div class="board-kpi-title">❓ Ждут решения</div>
            <div class="board-kpi-big">${openQ.length}</div>
            <div class="board-kpi-meta">кнопки ниже · ответ = один клик</div>
        </div>
    </div>
    ${renderOrg()}
    <div class="board-main">
        <section class="board-questions">
            <div class="board-section-title">❓ Решения — ответь одной кнопкой</div>
            ${qHtml}${doneHtml}
        </section>
        <section class="board-journal">
            <div class="board-section-title">📜 Вердикты команды <button class="board-refresh" id="boardRefresh">⟳ Обновить</button></div>
            ${journalHtml}
        </section>
    </div>`;

    root.querySelectorAll('.board-q-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const qid = btn.dataset.qid, choice = btn.dataset.choice;
            btn.disabled = true;
            try {
                const r = await fetchApi('/company/answer', {
                    method: 'POST',
                    body: JSON.stringify({ id: qid, choice })
                });
                if (r && r.ok) {
                    showToast(`✅ Решение принято: ${choice}) ${r.answer.text || ''}`, 'success');
                    await loadBoard();
                } else {
                    showToast('⚠️ Не записалось: ' + ((r && r.error) || 'ошибка'), 'error');
                    btn.disabled = false;
                }
            } catch (e) {
                showToast('⚠️ ' + e.message, 'error');
                btn.disabled = false;
            }
        });
    });
    const refresh = root.querySelector('#boardRefresh');
    if (refresh) refresh.addEventListener('click', loadBoard);
    initOrg(root);
}

function fmtNum(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString('ru-RU');
}

function isBoardActive() {
    const el = document.getElementById('tab-board');
    return el && el.classList.contains('active');
}

export function initTeamBoard() {
    const hook = () => { if (isBoardActive()) loadBoard(); };
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => setTimeout(hook, 50)));
    window.addEventListener('hashchange', hook);
    setTimeout(hook, 300);            // прямой заход по #tab-board
    if (!boardTimer) boardTimer = setInterval(() => { if (isBoardActive()) loadBoard(); }, 90000);
}
