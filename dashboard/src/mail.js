/**
 * mail.js — вкладка «Почта»: простой почтовый клиент поверх 20_Inbox/20_Outbox.
 * Список писем (все ящики) → просмотр: текст, вложения, связи в CRM
 * (клиент, счета/акты, задачи, сессии, тред) → ответ (POST /api/mail/send).
 */
import { fetchApi, API_BASE } from './apiClient';
import { showToast } from './utils/toast';

const state = {
    messages: [],
    mailboxes: [],
    current: null,
    filter: { direction: '', mailbox: '', q: '' },
    loadedOnce: false,
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const fmtDate = (d) => {
    if (!d) return '';
    const dt = new Date(d.replace(' ', 'T'));
    if (isNaN(dt)) return d;
    return dt.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
        + ' ' + dt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
};

const INVOICE_STATUS = {
    paid: '🟢 оплачен', sent: '🔵 отправлен', overdue: '🔴 просрочен',
    partially_paid: '🟡 частично', draft: '⚪ черновик',
};

export function initMailTab() {
    const btn = document.querySelector('.tab-btn[data-tab="tab-mail"]');
    if (!btn) return;

    const openHandler = () => { loadMailboxes(); refreshList(); };
    btn.addEventListener('click', openHandler);
    if (btn.classList.contains('active')) setTimeout(openHandler, 60);

    let debounce;
    document.getElementById('mailSearch')?.addEventListener('input', (e) => {
        clearTimeout(debounce);
        debounce = setTimeout(() => { state.filter.q = e.target.value.trim(); renderList(); }, 250);
    });
    document.getElementById('mailDirFilter')?.addEventListener('change', (e) => {
        state.filter.direction = e.target.value; renderList();
    });
    document.getElementById('mailBoxFilter')?.addEventListener('change', (e) => {
        state.filter.mailbox = e.target.value; renderList();
    });
    document.getElementById('mailRefreshBtn')?.addEventListener('click', () => {
        state.loadedOnce = false; openHandler();
    });
}

async function loadMailboxes() {
    try {
        const res = await fetchApi('/mail/mailboxes');
        const boxes = res?.data?.mailboxes || res?.mailboxes || [];
        state.mailboxes = boxes;
        const sel = document.getElementById('mailBoxFilter');
        if (sel && sel.options.length <= 1) {
            boxes.forEach((b) => {
                const o = document.createElement('option');
                o.value = b.id;
                o.textContent = `${b.name}${b.default ? ' ★' : ''} (${b.email})`;
                sel.appendChild(o);
            });
        }
    } catch { /* ящики не критичны для списка */ }
}

async function refreshList() {
    const listEl = document.getElementById('mailList');
    if (!listEl) return;
    try {
        const params = new URLSearchParams({ limit: '400' });
        const res = await fetchApi(`/mail/messages?${params}`);
        state.messages = res?.data?.messages || res?.messages || [];
        state.loadedOnce = true;
        renderList();
    } catch (e) {
        listEl.innerHTML = `<div class="mail-empty">❌ ${esc(e.message)}</div>`;
    }
}

function filteredMessages() {
    const { direction, mailbox, q } = state.filter;
    const qn = q.toLowerCase();
    return state.messages.filter((m) =>
        (!direction || m.direction === direction)
        && (!mailbox || m.mailbox === mailbox)
        && (!qn || (m.subject + ' ' + m.preview + ' ' + (m.from || '') + ' ' + (m.to || '')).toLowerCase().includes(qn)));
}

function renderList() {
    const listEl = document.getElementById('mailList');
    const countEl = document.getElementById('mailCount');
    if (!listEl) return;
    const msgs = filteredMessages();
    if (countEl) countEl.textContent = `${msgs.length} из ${state.messages.length}`;

    if (!msgs.length) {
        listEl.innerHTML = '<div class="mail-empty">Ничего не найдено</div>';
        return;
    }
    listEl.innerHTML = msgs.map((m) => {
        const who = m.direction === 'in' ? (m.from || '?') : (m.to || '?');
        const active = state.current?.file === m.file ? ' mail-item--active' : '';
        return `
        <div class="mail-item${active}" data-file="${esc(m.file)}">
            <div class="mail-item-top">
                <span class="mail-dir mail-dir--${m.direction}">${m.direction === 'in' ? '←' : '→'}</span>
                <span class="mail-who" title="${esc(who)}">${esc(who)}</span>
                <span class="mail-date">${fmtDate(m.date)}</span>
            </div>
            <div class="mail-subj">${m.unmatched ? '<span class="mail-tag mail-tag--new">лид?</span>' : ''}${esc(m.subject || '(без темы)')}</div>
            <div class="mail-prev">${m.attachments?.length ? '📎' : ''} ${esc(m.preview)}</div>
        </div>`;
    }).join('');

    listEl.querySelectorAll('.mail-item').forEach((el) => {
        el.addEventListener('click', () => openLetter(el.dataset.file));
    });
}

async function openLetter(file) {
    const viewEl = document.getElementById('mailView');
    if (!viewEl) return;
    viewEl.innerHTML = '<div class="mail-empty">Загрузка письма…</div>';
    renderList(); // подсветка выбора
    try {
        const res = await fetchApi(`/mail/message?file=${encodeURIComponent(file)}`);
        const data = res?.data || res;
        state.current = data.letter;
        renderLetter(data.letter, data.links || {});
        // на узком экране (одна колонка) — прокручиваем к открытому письму
        if (window.innerWidth < 900) {
            viewEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    } catch (e) {
        viewEl.innerHTML = `<div class="mail-empty">❌ ${esc(e.message)}</div>`;
    }
}

function renderLetter(L, links) {
    const viewEl = document.getElementById('mailView');
    const who = L.direction === 'in'
        ? `От: <b>${esc(L.from)}</b>` : `Кому: <b>${esc(L.to)}</b>`;
    const clientChip = links.client
        ? `<span class="mail-tag mail-tag--client" title="${esc(links.card || '')}">👤 ${esc(links.client)}</span>`
        : (L.unmatched ? '<span class="mail-tag mail-tag--new">не сопоставлен</span>' : '');

    const atts = (L.attachments || []).map((a) =>
        `<a class="mail-att" href="${API_BASE}/mail/attachment?path=${encodeURIComponent(a.path)}" target="_blank" rel="noopener">📎 ${esc(a.name)}</a>`
    ).join('');

    const invoices = (links.invoices || []).map((i) => `
        <div class="mail-link-row">
            <span class="mail-link-ico">🧾</span>
            <b>${esc(i.number)}</b> · ${esc(i.amount)} ₽ · ${esc(i.period || '')}
            <span class="mail-tag">${INVOICE_STATUS[i.status] || esc(i.status || '')}</span>
            ${i.act_status ? `<span class="mail-tag">акт: ${esc(i.act_status)}</span>` : ''}
        </div>`).join('');

    const mentioned = (links.mentioned_invoices || []).length
        ? `<div class="mail-links-sub">Упомянуты в тексте:</div>` +
          links.mentioned_invoices.map((i) => `
            <div class="mail-link-row"><span class="mail-link-ico">🧾</span>
                <b>${esc(i.number)}</b> · ${esc(i.amount)} ₽
                <span class="mail-tag">${INVOICE_STATUS[i.status] || esc(i.status || '')}</span></div>`).join('')
        : '';

    const tasks = (links.tasks || []).map((t) => `
        <div class="mail-link-row">
            <span class="mail-link-ico">${t.status === 'done' ? '✅' : '📋'}</span>
            ${esc(t.title)} ${t.completed ? `<span class="mail-tag">закрыта ${esc(t.completed)}</span>` : ''}
        </div>`).join('');

    const sessions = (links.sessions || []).map((s) =>
        `<span class="mail-tag" title="${esc(s)}">⌨️ ${esc(s.slice(5, 17))}…</span>`).join('');

    const thread = (links.thread || []).map((t) => `
        <div class="mail-link-row mail-thread-row" data-file="${esc(t.file)}" style="cursor:pointer">
            <span class="mail-link-ico">${t.direction === 'in' ? '←' : '→'}</span>
            ${esc(t.subject || '(без темы)')} <span class="mail-date">${fmtDate(t.date)}</span>
        </div>`).join('');

    viewEl.innerHTML = `
        <div class="mail-letter">
            <div class="mail-letter-head">
                <div class="mail-letter-subj">${esc(L.subject || '(без темы)')}</div>
                <div class="mail-letter-meta">
                    ${who} · ${fmtDate(L.date)} ${L.mailbox ? `· ящик <b>${esc(L.mailbox)}</b>` : ''}
                    ${clientChip}
                </div>
                ${atts ? `<div class="mail-atts">${atts}</div>` : ''}
                <div class="mail-letter-actions">
                    <button class="btn btn--primary btn--sm" id="mailReplyBtn">↩ Ответить</button>
                </div>
            </div>
            <div class="mail-letter-body">${esc(L.body || '(пустое письмо)')}</div>
            <div class="mail-links">
                <h3>🔗 Связи в CRM</h3>
                ${links.card ? `<div class="mail-link-row"><span class="mail-link-ico">👤</span> Карточка: <b>${esc(links.client)}</b></div>` : ''}
                ${sessions ? `<div class="mail-link-row"><span class="mail-link-ico">⌨️</span> Сессии проекта: ${sessions}</div>` : ''}
                ${invoices ? `<div class="mail-links-sub">Счета и акты клиента:</div>${invoices}` : ''}
                ${mentioned}
                ${tasks ? `<div class="mail-links-sub">Задачи клиента:</div>${tasks}` : ''}
                ${thread ? `<div class="mail-links-sub">Тред (${links.thread.length}):</div>${thread}` : ''}
                ${!links.client && !invoices && !tasks && !thread && !sessions
                    ? '<div class="mail-links-sub">Связей не найдено</div>' : ''}
            </div>
            <div class="mail-reply" id="mailReplyForm" style="display:none">
                <input class="mail-input" id="mailReplyTo" placeholder="Кому">
                <input class="mail-input" id="mailReplySubject" placeholder="Тема">
                <textarea class="mail-textarea" id="mailReplyText" placeholder="Текст ответа…"></textarea>
                <div class="mail-reply-actions">
                    <button class="btn btn--primary btn--sm" id="mailReplySend">📨 Отправить</button>
                    <button class="btn btn--secondary btn--sm" id="mailReplyCancel">Отмена</button>
                    <span class="mail-reply-note">подпись ассистента добавится автоматически</span>
                </div>
            </div>
        </div>`;

    document.getElementById('mailReplyBtn')?.addEventListener('click', () => {
        const form = document.getElementById('mailReplyForm');
        form.style.display = form.style.display === 'none' ? 'block' : 'none';
        document.getElementById('mailReplyTo').value =
            L.direction === 'in' ? (L.from || '') : (L.to || '');
        document.getElementById('mailReplySubject').value =
            (L.subject || '').toLowerCase().startsWith('re:') ? L.subject : `Re: ${L.subject || ''}`;
        document.getElementById('mailReplyText').focus();
    });
    document.getElementById('mailReplyCancel')?.addEventListener('click', () => {
        document.getElementById('mailReplyForm').style.display = 'none';
    });
    document.getElementById('mailReplySend')?.addEventListener('click', sendReply);
    viewEl.querySelectorAll('.mail-thread-row').forEach((el) => {
        el.addEventListener('click', () => openLetter(el.dataset.file));
    });
}

async function sendReply() {
    const to = document.getElementById('mailReplyTo')?.value.trim();
    const subject = document.getElementById('mailReplySubject')?.value.trim();
    const text = document.getElementById('mailReplyText')?.value.trim();
    const sendBtn = document.getElementById('mailReplySend');
    if (!to || !subject || !text) {
        showToast('Заполните кому, тему и текст', 'warn');
        return;
    }
    sendBtn.disabled = true;
    try {
        const payload = {
            to, subject, text,
            mailbox: state.current?.mailbox || null,
            reply_file: state.current?.file || null,
        };
        const res = await fetchApi('/mail/send', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        showToast('📨 Письмо отправлено', 'ok');
        document.getElementById('mailReplyForm').style.display = 'none';
        document.getElementById('mailReplyText').value = '';
        state.loadedOnce = false;
        refreshList();
    } catch (e) {
        showToast('Отправка не удалась: ' + e.message, 'err');
    } finally {
        sendBtn.disabled = false;
    }
}
