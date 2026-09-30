// hologram.js — оркестратор голограммы Джарвиса: state-machine, субтитры,
// звуки, wake word, хоткеи. three.js и голос грузятся лениво при первой активации.

import { showToast } from '../utils/toast.js';
import { automataApi, fetchApi } from '../apiClient.js';

const IDLE_TIMEOUT_MS = 45000; // тишина в активной сессии → авто-гашение

let figure = null;
let voice = null;
let skillFn = null;
let root = null;
let els = null;
let loaded = false;
let loading = null;

const S = {
    active: false,      // голограмма на экране
    state: 'off',       // off | idle | listening | thinking | speaking
    wakeOn: false,      // фоновый wake-режим
    idleTimer: null,
    navGuard: null,
};

const BADGES = {
    idle: { label: 'НА СВЯЗИ', cls: 'idle' },
    listening: { label: 'СЛУШАЮ', cls: 'listening' },
    thinking: { label: 'ДУМАЮ', cls: 'thinking' },
    speaking: { label: 'ГОВОРЮ', cls: 'speaking' },
};

export function initHologram() {
    const btn = document.getElementById('holoBtn');
    if (btn) {
        btn.addEventListener('click', () => {
            if (S.active) dismiss();
            else activate();
        });
        btn.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            toggleWake();
        });
    }
    document.addEventListener('keydown', (e) => {
        // Escape гасит голограмму всегда, даже из поля ввода
        if (e.key === 'Escape' && S.active) {
            dismiss();
            return;
        }
        if (e.target?.closest?.('input, textarea, select, [contenteditable="true"]')) return;
        if (e.code === 'KeyJ' && !S.active && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            activate();
        }
    });
    document.addEventListener('visibilitychange', () => {
        if (!voice) return;
        if (document.hidden && S.wakeOn && !S.active) voice.stopWake();
        else if (!document.hidden && S.wakeOn && !S.active) startWakeListening();
    });

    // вкладка «Система»: выбор модели голограммы
    initSystemPicker();

    // API для отладки и browser-use-тестов
    window.__holo = {
        activate,
        dismiss,
        ask: (t) => (S.active ? route(t) : activate(t)),
        toggleWake,
        // переключение модели голограммы: 'michelle' | 'kira' | 'xbot'
        useModel: (name) => {
            localStorage.setItem('holo-model', name);
            location.reload();
        },
        state: S,
    };
}

// ------------------------------------------------------------------
// вкладка «Система»: карточки моделей + кнопки вызова/wake
// ------------------------------------------------------------------

const MODEL_LABELS = { michelle: 'Michelle', xbot: 'Xbot', '2b': '2B (NieR)', face: 'Голова (мимика)' };

function initSystemPicker() {
    const wrap = document.getElementById('holoModels');
    if (!wrap) return;

    const sync = () => {
        const cur = localStorage.getItem('holo-model') || 'michelle';
        wrap.querySelectorAll('.holo-model-card').forEach((c) => {
            c.classList.toggle('active', c.dataset.model === cur);
        });
        const note = document.getElementById('holoModelNote');
        if (note) {
            note.innerHTML = `Текущая модель: <b>${MODEL_LABELS[cur] || cur}</b> · переключение перезагружает страницу · J — вызвать, Esc — погасить`;
        }
    };
    sync();

    wrap.querySelectorAll('.holo-model-card').forEach((card) => {
        card.addEventListener('click', () => {
            const cur = localStorage.getItem('holo-model') || 'michelle';
            if (card.dataset.model !== cur) window.__holo.useModel(card.dataset.model);
        });
    });

    const callBtn = document.getElementById('holoCallBtn');
    if (callBtn) callBtn.addEventListener('click', () => (S.active ? dismiss() : activate()));
    const wakeBtn = document.getElementById('holoWakeBtn');
    if (wakeBtn) wakeBtn.addEventListener('click', () => toggleWake());
}

// ------------------------------------------------------------------
// wake-режим (фоновое прослушивание слова «Джарвис»)
// ------------------------------------------------------------------

async function toggleWake() {
    if (S.wakeOn) {
        S.wakeOn = false;
        voice?.stopWake();
        setDot('off');
        showToast('Голосовая активация выключена', 'info');
        return true;
    }
    await ensureLoaded();
    const ok = await voice.ensureMic();
    if (!ok) {
        showToast('Нет доступа к микрофону — активируйте кнопкой J или кликом', 'error');
        return false;
    }
    if (!voice.sttAvailable) {
        showToast('Браузер без распознавания речи — работаем по кнопке J и текстом', 'error');
        return false;
    }
    S.wakeOn = true;
    startWakeListening();
    setDot('wake');
    showToast('Слушаю слово «Джарвис»', 'success');
    return true;
}

function startWakeListening() {
    voice.startWake((rest) => {
        if (!S.active) activate(rest || null);
    });
}

function setDot(state) {
    const dot = document.getElementById('holoDot');
    if (dot) dot.dataset.state = state;
}

// ------------------------------------------------------------------
// активация / гашение
// ------------------------------------------------------------------

async function ensureLoaded() {
    if (loaded) return;
    if (!loading) {
        loading = (async () => {
            const [{ createFigure }, { VoiceIO }, { handle }] = await Promise.all([
                import('./figure.js'),
                import('./voice.js'),
                import('./skills.js'),
            ]);
            figure = createFigure(getRoot());
            voice = new VoiceIO({ onAmp: (v) => figure?.setAmp(v) });
            skillFn = handle;
            window.__holoFig = figure; // отладка/тесты
            loaded = true;
        })().catch((e) => {
            loading = null;
            throw e;
        });
    }
    await loading;
}

function getRoot() {
    if (!root) root = document.getElementById('holo-root');
    return root;
}

export async function activate(initialText = null) {
    if (S.active) return;
    try {
        await ensureLoaded();
    } catch (e) {
        showToast('Голограмма не загрузилась: ' + (e?.message || e), 'error');
        return;
    }

    S.active = true;
    setDot('active');
    buildDom();
    root.classList.add('active');
    root.setAttribute('aria-hidden', 'false');

    voice?.stopWake(); // во время сессии wake не нужен
    figure.start();
    chime('on');
    await figure.show();

    resetIdle();
    if (initialText) route(initialText);
    else {
        caption('На связи. Слушаю.', 'system');
        await listen();
    }
}

export async function dismiss() {
    if (!S.active) return;
    S.active = false;
    clearDraftUi();
    stopBrainPoller();
    clearTimeout(S.idleTimer);
    voice?.stopSpeaking();
    setState('off');
    chime('off');
    await figure.hide();
    root.classList.remove('active');
    root.setAttribute('aria-hidden', 'true');
    if (els) els.wrap.remove();
    els = null;
    setDot(S.wakeOn ? 'wake' : 'off');
    if (S.wakeOn && !document.hidden) startWakeListening();
}

// ------------------------------------------------------------------
// диалоговый цикл
// ------------------------------------------------------------------

async function listen() {
    if (!S.active) return;
    resetIdle();
    const micOk = await voice.ensureMic();
    if (voice.sttAvailable && micOk) {
        setState('listening');
        captionHint('говорите…');
        const text = await voice.listenOnce({
            onPartial: (p) => caption(p, 'live'),
        });
        if (!S.active) return;
        if (text) route(text);
        else {
            // тишину слышали раз — остаёмся на связи; реплику не затираем
            captionHint('молчание — скажите команду, напишите или нажмите Esc');
            listen();
        }
    } else {
        setState('idle');
        caption('Микрофон недоступен — напишите команду.', 'system');
        els?.input.focus();
    }
}

async function route(text) {
    if (!S.active) return;

    // эхо-гейт: во время собственной речи микрофон ловит её же слова,
    // и повторы последней озвученной реплики — это не команда владельца
    const lowEcho = String(text).toLowerCase().replace(/ё/g, 'е').replace(/[«»".,!?]/g, '').trim();
    if (S.state === 'speaking' && lowEcho.length < 90) return;
    if (S._lastSpoken && lowEcho.length >= 8
        && S._lastSpoken.includes(lowEcho.slice(0, Math.min(30, lowEcho.length)))) return;

    clearTimeout(S.idleTimer);

    // активный черновик (счёт): голосовое подтверждение / отмена
    const low = String(text).toLowerCase().replace(/ё/g, 'е').trim();
    if (S.pendingDraft) {
        if (/^(подтвержда|давай|согласен|ок|да)[\s,.!?]*$/.test(low) || /^(подтвержда|да, |ок, )/.test(low)) {
            return executeDraft();
        }
        if (/^(отмен|нет|стоп|не надо|не нужно|выходи)/.test(low)) {
            return cancelDraft('Отменила — счёт не создан.');
        }
    }

    caption(text, 'user');
    setState('thinking');

    let res;
    try {
        res = await skillFn(text);
        (window.__holoTrace = window.__holoTrace || []).push('skill ok: ' + (res?.text || '').slice(0, 60));
    } catch (e) {
        (window.__holoTrace = window.__holoTrace || []).push('skill err: ' + (e?.message || e));
        figure.glitch(0.9, 300);
        res = { text: 'Сбой навыка: ' + (e?.message || e), speak: 'Сбой навыка.' };
    }
    if (!S.active) return;

    if (res.action?.type === 'switchTab') {
        const btn = document.querySelector(`.tab-btn[data-tab="${res.action.id}"]`);
        if (btn) btn.click();
    }
    if (res.action?.type === 'dismiss') {
        caption(res.text, 'system');
        setState('speaking');
        await speakLine(res.speak || res.text);
        dismiss();
        return;
    }
    // черновик действия с деньгами: показываем и ждём явное подтверждение
    if (res.draft) {
        showDraft(res);
        return;
    }
    // абстрактный вопрос → мозг: с ключом GLM — сразу, без ключа — мост
    // на подписке ZCode (автоматизация ответит ~2 мин, ответ озвучим по прибытии)
    if (res.ask) {
        caption(res.ask, 'user');
        setState('thinking');
        caption('Думаю над вопросом…', 'system');
        try {
            const r = await fetchApi('/voice/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: res.ask }),
            });
            if (r?.queued) {
                caption('Вопрос ушел в мозг на подписке ZCode — отвечу, как мысль придёт (обычно до пары минут).', 'system');
                setState('idle');
                pollBrainAnswer(r.id);
                listen();
                return;
            }
            const answer = (r?.answer || '').trim();
            if (!answer) throw new Error('пустой ответ');
            await deliverBrainAnswer(answer);
        } catch (e) {
            const msg = String(e?.message || e);
            caption('Не смогла подумать: ' + msg, 'system');
            figure?.glitch(0.6, 250);
        }
        if (!S.active) return;
        setState('idle');
        listen();
        return;
    }

    caption(res.text, 'jarvis');
    S._lastSpoken = String(res.speak || res.text).toLowerCase().replace(/ё/g, 'е').replace(/[«»".,!?]/g, '').slice(0, 260);
    setState('speaking');
    await speakLine(res.speak || res.text);
    if (!S.active) return;
    setState('idle');
    listen();
}

async function speakLine(text) {
    await voice.speak(text, { onAmp: (v) => figure?.setAmp(v) });
    figure?.setAmp(0);
}

function resetIdle() {
    clearTimeout(S.idleTimer);
    S.idleTimer = setTimeout(() => {
        if (S.active) dismiss();
    }, IDLE_TIMEOUT_MS);
}

// ------------------------------------------------------------------
// DOM оверлея (субтитры, бейдж, ввод, закрытие)
// ------------------------------------------------------------------

function buildDom() {
    if (els) return;
    els = {};
    els.wrap = document.createElement('div');
    els.wrap.className = 'holo-ui';
    els.wrap.innerHTML = `
        <button class="holo-close" title="Погасить (Esc)">×</button>
        <div class="holo-caption">
            <div class="holo-caption-head">
                <span class="holo-caption-name">ДЖАРВИС</span>
                <span class="holo-badge" data-cls="idle"><i></i><b>НА СВЯЗИ</b></span>
            </div>
            <div class="holo-caption-text">…</div>
            <div class="holo-caption-hint">Esc — погасить · J — вызвать · «отбой» голосом</div>
            <div class="holo-input-row">
                <input class="holo-input" type="text" placeholder="или напишите команду: сводка, лента, деньги, открой почту…">
                <button class="holo-send" title="Отправить">
                    <svg width="15" height="15"><use href="#i-send"/></svg>
                </button>
            </div>
        </div>
    `;
    getRoot().appendChild(els.wrap);
    els.badge = els.wrap.querySelector('.holo-badge');
    els.text = els.wrap.querySelector('.holo-caption-text');
    els.hint = els.wrap.querySelector('.holo-caption-hint');
    els.input = els.wrap.querySelector('.holo-input');
    els.close = els.wrap.querySelector('.holo-close');
    els.send = els.wrap.querySelector('.holo-send');

    els.close.addEventListener('click', dismiss);
    const submit = () => {
        const v = els.input.value.trim();
        if (!v) return;
        els.input.value = '';
        route(v);
    };
    els.send.addEventListener('click', submit);
    els.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') submit();
        e.stopPropagation();
    });
}

function setState(name) {
    S.state = name;
    if (figure && name !== 'off') figure.setState(name === 'idle' ? 'idle' : name);
    if (!els) return;
    const b = BADGES[name];
    if (b) {
        els.badge.dataset.cls = b.cls;
        els.badge.querySelector('b').textContent = b.label;
    }
}

function caption(text, kind = 'jarvis') {
    if (!els) return;
    els.text.dataset.kind = kind;
    els.text.textContent = text;
}

function captionHint(t) {
    if (els) els.hint.textContent = `говорите… · Esc — погасить`;
}

// ------------------------------------------------------------------
// мост «мозг на подписке»: опрос ответа автоматизации ZCode
// ------------------------------------------------------------------

let _brainPoller = null;

function stopBrainPoller() {
    clearInterval(_brainPoller);
    _brainPoller = null;
}

function pollBrainAnswer(qid) {
    stopBrainPoller();
    const started = Date.now();
    _brainPoller = setInterval(async () => {
        if (!S.active || Date.now() - started > 8 * 60 * 1000) {
            stopBrainPoller();
            return;
        }
        try {
            const r = await fetchApi(`/voice/answer?id=${encodeURIComponent(qid)}`);
            if (r?.ready) {
                stopBrainPoller();
                await deliverBrainAnswer(r.answer);
            }
        } catch (e) { /* сеть моргнула — попробуем на следующем тике */ }
    }, 5000);
}

async function deliverBrainAnswer(answer) {
    if (!S.active || !answer) return;
    caption(String(answer).slice(0, 900), 'jarvis');
    S._lastSpoken = String(answer).toLowerCase().replace(/ё/g, 'е').replace(/[«»".,!?]/g, '').slice(0, 260);
    setState('speaking');
    await speakLine(String(answer).slice(0, 600));
    setState('idle');
    listen();
}

// ------------------------------------------------------------------
// черновики действий с деньгами: подтверждение голосом или кнопкой
// ------------------------------------------------------------------

function clearDraftUi() {
    S.pendingDraft = null;
    els?.wrap?.querySelector('.holo-confirm')?.remove();
}

function showDraft(res) {
    S.pendingDraft = res.draft;
    caption(res.text, 'jarvis');
    els.hint.textContent = 'скажите «подтверждаю» или «отмена» — или нажмите кнопку · Esc — погасить';
    setState('idle');
    const row = document.createElement('div');
    row.className = 'holo-confirm';
    row.innerHTML = `
        <button class="holo-btn holo-btn-yes">✔ Подтвердить</button>
        <button class="holo-btn holo-btn-no">✖ Отмена</button>`;
    row.querySelector('.holo-btn-yes').addEventListener('click', () => executeDraft());
    row.querySelector('.holo-btn-no').addEventListener('click', () => cancelDraft('Отменила — счёт не создан.'));
    els.inputRow = els.input.parentNode;
    els.wrap.querySelector('.holo-caption').insertBefore(row, els.inputRow);
    listen(); // ждём голосовое подтверждение
}

async function executeDraft() {
    const d = S.pendingDraft;
    if (!d) return;
    clearDraftUi();
    setState('thinking');
    caption(d.entity === 'invoice' ? 'Оформляю счёт…' : 'Создаю задачу…', 'system');
    try {
        const payload = { ...d };
        delete payload.entity;
        const r = await automataApi.createEntity(d.entity, payload);
        let label, tailMsg;
        if (d.entity === 'invoice') {
            const num = r?.invoice_number || r?.values?.invoice_number || '';
            label = num ? `счёт №${num}` : 'счёт';
            tailMsg = `Счёт в блоке неоплаченных — PDF, email и телеграм на вкладке «Финансы».`;
        } else {
            label = 'задача';
            tailMsg = `Задача в 30_Tasks — агенты подберут её на следующем 15-минутном тике.`;
        }
        figure?.glitch(0.4, 200);
        caption(`Готово: ${label} создан.\n${tailMsg}`, 'jarvis');
        setState('speaking');
        await speakLine(`Готово, ${label} создан.`);
    } catch (e) {
        figure?.glitch(0.9, 300);
        caption('Не получилось: ' + (e?.message || e), 'system');
        setState('idle');
    }
    if (!S.active) return;
    setState('idle');
    listen();
}

function cancelDraft(msg) {
    clearDraftUi();
    caption(msg || 'Отменено.', 'system');
    setState('idle');
    listen();
}

// ------------------------------------------------------------------
// звуки (WebAudio-осцилляторы, без аудиофайлов)
// ------------------------------------------------------------------

function chime(kind) {
    try {
        const AC = window.AudioContext || window.webkitAudioContext;
        const ctx = voice?.audioCtx || new AC();
        if (ctx.state === 'suspended') ctx.resume().catch(() => {});
        const t0 = ctx.currentTime;
        const o1 = ctx.createOscillator();
        const o2 = ctx.createOscillator();
        const g = ctx.createGain();
        o1.type = 'sine';
        o2.type = 'sine';
        // появление — восходящий двутон, гашение — нисходящий
        const f = kind === 'on' ? [520, 780] : [760, 480];
        o1.frequency.setValueAtTime(f[0], t0);
        o1.frequency.exponentialRampToValueAtTime(f[0], t0 + 0.28);
        o2.frequency.setValueAtTime(f[1], t0 + 0.06);
        o2.frequency.exponentialRampToValueAtTime(f[1], t0 + 0.34);
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(0.07, t0 + 0.03);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.38);
        o1.connect(g);
        o2.connect(g);
        g.connect(ctx.destination);
        o1.start(t0);
        o2.start(t0);
        o1.stop(t0 + 0.4);
        o2.stop(t0 + 0.4);
    } catch (e) { /* звук не критичен */ }
}
