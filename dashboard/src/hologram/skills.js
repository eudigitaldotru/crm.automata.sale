// skills.js — голосовые навыки Джарвиса.
// Два уровня полномочий (правило автономии владельца):
//   ЧТЕНИЕ (почта/чаты/задачи/акты/борда/сводки) — выполняется сразу;
//   ДЕНЬГИ (счёт) — только ЧЕРНОВИК + явное подтверждение (кнопка/«подтверждаю»).
// Голос ничего не отправляет клиентам напрямую.

import { automataApi, fetchApi } from '../apiClient.js';
import { formatRub } from '../utils/data-loader.js';

const TABS = [
    { re: /чат|лент|сообщен/, id: 'tab-chat', name: 'Чат' },
    { re: /почт|мыл|письм/, id: 'tab-mail', name: 'Почта' },
    { re: /сегодня|день|календар|план/, id: 'tab-today', name: 'Сегодня' },
    { re: /клиент|карточк/, id: 'tab-clients', name: 'Клиенты' },
    { re: /бизнес|выручк|тариф/, id: 'tab-business', name: 'Бизнес' },
    { re: /финанс|счет|деньг|дебитор/, id: 'tab-finances', name: 'Финансы' },
    { re: /систем|монитор|сервер|голограмм/, id: 'tab-system', name: 'Система' },
    { re: /совет|команд|директ/, id: 'tab-tip', name: 'Совет' },
];

const MONTHS = ['январ', 'феврал', 'март', 'апре', 'ма', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр'];

const norm = (s) => s.toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim();

const HELP_REPLY = 'Умею: сводка, деньги, лента, почта, задачи, чаты, акты в Точке, спроси у комдиректора, что делали агенты — сессии, передай агенту — директива с подтверждением, выстави счёт — с подтверждением, открой вкладку.';

export async function handle(rawText) {
    const t = norm(rawText || '');
    if (!t) return { text: 'Не расслышала. ' + HELP_REPLY, speak: 'Не расслышала. Скажите, например, сводка.' };

    // --- управление голограммой ---
    if (/^(отбой|погаси|спуск|до связи|усни|гасни)/.test(t)) {
        return { text: 'До связи.', speak: 'До связи.', action: { type: 'dismiss' } };
    }

    // --- счёт: черновик + подтверждение (исполнение в hologram.js) ---
    if (/выстави счет|выставить счет|сделай счет|созда(й|ть) счет|подготовь счет/.test(t)) {
        return await draftInvoice(t);
    }

    // --- директива агентству (задача в 30_Tasks через подтверждение) ---
    if (/передай агент|директив.*агент|поставь задачу агент|задание агент/.test(t)) {
        return draftDirective(t);
    }

    // --- сессии ZCode ---
    if (/сесси|зкод|zcode|что делали агент|чем занят агент|чем заняты агент|очередь зкод|работу агент|агентств/.test(t)) {
        return await skillSessions(t);
    }

    // --- акты, не ушедшие в Точку ---
    if (/акт/.test(t) && /точк|подпис|ушл|не ушли/.test(t)) {
        return await skillActsTochka();
    }

    // --- задачи ---
    if (/провер(ить|ь) задач|задачи|что по задач|мои задач/.test(t)) {
        return await skillTasks(rawText);
    }

    // --- почта ---
    if (/провер(ить|ь) почт|почт|письм|емейл|mail/.test(t) && !/открой/.test(t)) {
        return await skillMail();
    }

    // --- чаты ---
    if (/провер(ить|ь) чат|провер(ить|ь) сообщен|новые сообщен|что в чатах|непрочит/.test(t)) {
        return await skillFeed(true);
    }

    // --- коммерческий директор / борда ---
    if (/ком(мерческого)?\s*дир|борд|совет команд/.test(t) || (/спроси|статус/.test(t) && /дир/.test(t))) {
        return await skillBoard(t);
    }

    // --- кто ты / помощь ---
    if (/кто ты|ты человек|ты бот|ты робот|как тебя зовут/.test(t)) {
        return {
            text: 'Я Джарвис — ИИ-ассистент Евгения. Слежу за клиентами, каналами и деньгами.',
            speak: 'Я Джарвис, ИИ ассистент Евгения. Слежу за клиентами, каналами и деньгами.',
        };
    }
    if (/помощь|что умеешь|команды|как польз/.test(t)) {
        return { text: HELP_REPLY.replace(/«|»/g, '"'), speak: HELP_REPLY };
    }
    if (/спасибо|благодар/.test(t)) {
        return { text: 'Всегда пожалуйста.', speak: 'Всегда пожалуйста.' };
    }

    // --- открой вкладку ---
    if (/открой|перейди|покажи вкладку|включи вкладку/.test(t)) {
        const tab = TABS.find((x) => x.re.test(t));
        if (tab) {
            const btn = document.querySelector(`.tab-btn[data-tab="${tab.id}"]`);
            if (btn) btn.click();
            return { text: `Открыла — ${tab.name}.`, speak: `Открыла, ${tab.name}.` };
        }
        return { text: 'Не поняла, какую вкладку. Есть: Чат, Почта, Сегодня, Клиенты, Бизнес, Финансы, Система, Совет.', speak: 'Не поняла, какую вкладку открыть.' };
    }

    // --- здоровье / каналы ---
    if (/здоров|каналы|мониторинг|интеграц|статус канал/.test(t)) {
        return await skillHealth();
    }

    // --- дайджест клиента: «как дела у X», «что по X», «статус X» —
    //     ДО общих сводок, иначе MRR затирает вопрос про конкретного клиента
    if (/как дела|что |статус|как там|новост|прогресс|обстановк|задач|дела по|по клиенту/.test(t)) {
        const digest = await skillClientDigest(t);
        if (digest) return digest;
    }

    // --- деньги / дебиторка ---
    if (/дебитор|деньг|счет|долг|оплат|финанс|выручк/.test(t)) {
        return await skillMoney();
    }

    // --- лента ---
    if (/лент|последние сообщ|что в чате|входящ|кто писал/.test(t)) {
        return await skillFeed(false);
    }

    // --- сводка ---
    if (/сводк|что нового|как дела|положен|обнови|расскажи|статус|итог/.test(t)) {
        return await skillSummary();
    }

    // --- абстрактный вопрос → LLM-мозг (ответ собирает hologram.js) ---
    return {
        ask: rawText,
        text: 'Думаю…',
        speak: '',
    };
}

// ------------------------------------------------------------------
// ЧТЕНИЕ
// ------------------------------------------------------------------

async function skillSummary() {
    const data = await automataApi.getData();
    const m = data?.meta || {};
    const lines = [];
    if (m.mrr != null) lines.push(`MRR ${formatRub(m.mrr)}`);
    if (m.revenue_this_month != null) lines.push(`выручка за месяц ${formatRub(m.revenue_this_month)}`);
    if (m.total_debt != null) {
        const overdue = m.overdue_count ? `, просроченных ${m.overdue_count}` : '';
        lines.push(`дебиторка ${formatRub(m.total_debt)}${overdue}`);
    }
    if (m.active_clients_count != null) lines.push(`активных клиентов ${m.active_clients_count}`);
    if (!lines.length) return { text: 'Данные пока не собраны.', speak: 'Данные пока не собраны.' };
    return { text: lines.join(' · '), speak: lines.join(', ') };
}

async function skillMoney() {
    const data = await automataApi.getData();
    const unpaid = (data?.invoices || []).filter((i) => ['unpaid', 'sent'].includes(i.status));
    const total = unpaid.reduce((s, i) => s + (i.amount || 0), 0);
    const head = unpaid.length
        ? `Непогашено ${unpaid.length} ${plural(unpaid.length, 'счёт', 'счёта', 'счетов')} на ${formatRub(total)}:`
        : 'Все счета погашены, дебиторки нет.';
    const list = unpaid.slice(0, 4).map((i) => `• ${i.client} — ${formatRub(i.amount)} (${i.number})`).join('\n');
    return {
        text: head + (list ? '\n' + list : ''),
        speak: unpaid.length
            ? `Должники: ${unpaid.slice(0, 3).map((i) => `${i.client}, ${formatRub(i.amount)}`).join('. ')}`
            : 'Все счета погашены.',
        action: { type: 'switchTab', id: 'tab-finances' },
    };
}

async function skillFeed(onlyUnread) {
    const res = await fetchApi('/chat/threads');
    const all = res?.threads || res?.data?.threads || [];
    const threads = onlyUnread ? all.filter((th) => th.unread > 0) : all;
    const list = (threads.length ? threads : all).slice(0, onlyUnread ? 5 : 3);
    if (!list.length) return { text: onlyUnread ? 'Непрочитанных нет — все каналы чистые.' : 'Лента пуста.', speak: onlyUnread ? 'Непрочитанных нет' : 'Лента пуста' };
    const lines = list.map((th) => {
        const un = th.unread ? ` · ${th.unread} непроч.` : '';
        return `• ${th.client}: ${(th.last_text || '').slice(0, 60)}${un}`;
    });
    return {
        text: (onlyUnread ? `Непрочитанные (${list.length}):\n` : '') + lines.join('\n'),
        speak: list.map((th) => `${th.client}${th.unread ? `, ${th.unread} новых` : ''}`).join('. '),
        action: { type: 'switchTab', id: 'tab-chat' },
    };
}

async function skillMail() {
    const res = await fetchApi('/mail/messages?direction=incoming&limit=5');
    const msgs = res?.messages || res?.data?.messages || [];
    if (!msgs.length) return { text: 'Входящих писем нет.', speak: 'Входящих писем нет' };
    const lines = msgs.map((m) => `• ${(m.from || '').slice(0, 34)} — ${(m.subject || '(без темы)').slice(0, 60)}`);
    return {
        text: `Последние входящие (${Math.min(5, msgs.length)}):\n` + lines.join('\n'),
        speak: msgs.slice(0, 3).map((m) => `от ${String(m.from || '').split('@')[0]}`).join(', '),
        action: { type: 'switchTab', id: 'tab-mail' },
    };
}

async function skillTasks(text) {
    const res = await fetchApi('/tasks');
    let tasks = (res?.tasks || res?.data?.tasks || []).filter((x) => !x.done);
    // «задачи по мягкой кровле» — фильтруем по клиенту
    const mentioned = await mentionedClientName(text);
    if (mentioned) {
        tasks = tasks.filter((x) => sameClient(x.client, mentioned));
        if (!tasks.length) {
            return { text: `Открытых задач по «${mentioned}» нет.`, speak: `По ${mentioned} открытых задач нет.` };
        }
    }
    if (!tasks.length) return { text: 'Открытых задач нет.', speak: 'Открытых задач нет' };
    tasks.sort((a, b) => (b.urgent - a.urgent) || (b.important - a.important));
    const top = tasks.slice(0, 5);
    const lines = top.map((x) => `• ${x.title}${x.client ? ` — ${x.client}` : ''}${x.urgent ? ' ⚡' : ''}`);
    return {
        text: (mentioned ? `Задачи по «${mentioned}» (${tasks.length}):\n` : `Открытых задач ${tasks.length}, срочные сверху:\n`) + lines.join('\n'),
        speak: (mentioned ? `По ${mentioned} задач ${tasks.length}. ` : `Открытых задач ${tasks.length}. Самые важные: `) + top.slice(0, 3).map((x) => x.title).join('. '),
    };
}

async function skillActsTochka() {
    const data = await automataApi.getData();
    let acts = (data?.invoices || []).filter((i) => i.act_pdf && i.owner_signed === false);
    // старые данные без поля — обновим один раз и перечитаем
    if (!('owner_signed' in (data?.invoices?.[0] || {}))) {
        try { await automataApi.refreshDashboard(); } catch (e) {}
        const fresh = await automataApi.getData();
        acts = (fresh?.invoices || []).filter((i) => i.act_pdf && i.owner_signed === false);
    }
    if (!acts.length) {
        return { text: 'Все акты подписаны в Точке — страж чист.', speak: 'Все акты подписаны в Точке.' };
    }
    const lines = acts.map((i) => `• ${i.client} — ${i.number} (${formatRub(i.amount)})`);
    return {
        text: `Ждут твоей подписи в Точке — ${acts.length} ${plural(acts.length, 'акт', 'акта', 'актов')}:\n` + lines.join('\n'),
        speak: `В Точке ждут подписи ${acts.length} актов: ` + acts.slice(0, 3).map((i) => i.client).join(', '),
        action: { type: 'switchTab', id: 'tab-finances' },
    };
}

async function skillBoard(text) {
    // «спроси у комдиректора статус по Сталь Штамп» → вопрос на борде + ответ
    let res;
    try {
        res = await fetchApi('/company/board');
    } catch (e) {
        return { text: 'Борда команды недоступна.', speak: 'Борда команды недоступна.' };
    }
    const questions = res?.questions || res?.data?.questions || [];
    if (!questions.length) {
        return { text: 'На борде сейчас нет открытых вопросов.', speak: 'На борде нет открытых вопросов.' };
    }
    // ищем клиента в тексте команды (карточки + имена из счетов)
    const data = await automataApi.getData().catch(() => null);
    const names = [...new Set([
        ...(data?.clients || []).map((c) => c.name),
        ...(data?.invoices || []).map((i) => i.client),
    ])];
    const mentioned = matchClient(norm(text), names);
    let noQuestionFor = null;
    let pick = [];
    if (mentioned) {
        const tokens = norm(mentioned).split(/[^а-яa-z0-9]+/)
            .filter((w) => w.length >= 4 && !LEGAL_JUNK.has(w));
        pick = questions.filter((q) => {
            const ql = (q.question || '').toLowerCase();
            return tokens.some((w) => ql.includes(w));
        });
    }
    if (!pick.length && mentioned) {
        pick = questions.filter((q) => /ком/.test(String(q.role || '').toLowerCase()));
        noQuestionFor = mentioned;
    }
    if (!pick.length) pick = questions.filter((q) => /ком/.test(String(q.role || '').toLowerCase()));
    if (!pick.length) pick = questions.filter((q) => !q.answered);
    const q = pick[0] || questions[0];
    const opts = (q.options || []).map((o) => `${o.key}) ${o.text}`).join('  ');
    const status = q.answered
        ? `Отвечено: ${q.answer.choice}) ${q.answer.text || ''}`
        : `Ждёт твоего ответа на борде (вкладка «Совет»).`;
    const prefix = noQuestionFor ? `Про «${noQuestionFor}» у комдиректора вопросов нет. Ближайшее:\n` : '';
    return {
        text: prefix + `${q.role || 'роль'}: ${q.question}\n${opts}\n${status}`,
        speak: `${noQuestionFor ? 'По этому клиенту вопросов нет. ' : ''}${q.role}. ${q.question}. ${q.answered ? 'Ответ уже дан.' : 'Ждёт твоего ответа.'}`,
        action: { type: 'switchTab', id: 'tab-tip' },
    };
}

function t_includes(hay, needle) {
    return norm(hay).includes(norm(needle).split(' ')[0] || needle);
}

// ------------------------------------------------------------------
// СЧЁТ: черновик (исполнение — только после подтверждения)
// ------------------------------------------------------------------

// Подбор карточки клиента по словам: «ромашка» → ООО "РОМАШКА".
// Юр-префиксы (ООО/ИП/АО…) игнорируем, матчим самое длинное совпавшее слово.
const LEGAL_JUNK = new Set(['ооо', 'оао', 'зао', 'пао', 'ао', 'ип', 'компания', 'фирма', 'торговый', 'дом']);

// усечение окончания: «кровля»→«кров», чтобы падежи («кровле», «мягкой») матчились
function stem(w) {
    return w.slice(0, Math.max(4, w.length - 2));
}

function matchClient(tn, clients) {
    let best = null, bestScore = 0;
    for (const c of clients) {
        const tokens = norm(c).split(/[^а-яa-z0-9]+/)
            .filter((w) => w.length >= 4 && !LEGAL_JUNK.has(w));
        for (const w of tokens) {
            if (tn.includes(stem(w)) && w.length > bestScore) {
                bestScore = w.length;
                best = c;
            }
        }
    }
    return best;
}

function clientTokens(name) {
    return norm(String(name || '')).split(/[^а-яa-z0-9]+/)
        .filter((w) => w.length >= 4 && !LEGAL_JUNK.has(w));
}

// «ООО "РОМАШКА"» ≈ «Ромашка» ≈ «Ромашке» — совпадение по стемам
function sameClient(a, b) {
    const ta = clientTokens(a), tb = clientTokens(b);
    return ta.some((x) => tb.some((y) => y.includes(stem(x)) || x.includes(stem(y))));
}

// Все известные имена клиентов (карточки + имена из счетов/ленты)
async function clientUniverse() {
    const data = await automataApi.getData().catch(() => null);
    return {
        data,
        names: [...new Set([
            ...(data?.clients || []).map((c) => c.name),
            ...(data?.invoices || []).map((i) => i.client),
        ])],
    };
}

async function mentionedClientName(text) {
    const { names } = await clientUniverse();
    return matchClient(norm(text || ''), names);
}

// ------------------------------------------------------------------
// ДАЙДЖЕСТ КЛИЕНТА: деньги + переписка + задачи + акты + борда
// ------------------------------------------------------------------

async function skillClientDigest(text) {
    const { data, names } = await clientUniverse();
    const mentioned = matchClient(norm(text), names);
    if (!mentioned) return null;

    const lines = [];
    const speakParts = [];

    // деньги
    const unpaid = (data?.invoices || []).filter((i) =>
        ['unpaid', 'sent'].includes(i.status) && sameClient(i.client, mentioned));
    const invClient = unpaid[0]?.client || (data?.invoices || []).find((i) => sameClient(i.client, mentioned))?.client;
    if (unpaid.length) {
        const total = unpaid.reduce((s, i) => s + (i.amount || 0), 0);
        lines.push(`• Деньги: непогашено ${unpaid.length} ${plural(unpaid.length, 'счёт', 'счёта', 'счетов')} на ${formatRub(total)} — ${unpaid.map((i) => i.number).join(', ')}`);
        speakParts.push(`непогашено ${formatRub(total)}`);
    } else {
        lines.push('• Деньги: всё погашено, долгов нет');
        speakParts.push('долгов нет');
    }

    // переписка
    try {
        const res = await fetchApi('/chat/threads');
        const th = (res?.threads || res?.data?.threads || [])
            .find((x) => sameClient(x.client, mentioned));
        if (th) {
            lines.push(`• Переписка (${(th.channels || []).join(', ')}): «${(th.last_text || '').slice(0, 70)}»${th.unread ? ` · ${th.unread} непроч.` : ''}`);
            speakParts.push(`${th.unread ? 'есть непрочитанные' : 'нового нет'}`);
        }
    } catch (e) { /* лента недоступна — пропускаем блок */ }

    // задачи
    try {
        const res = await fetchApi('/tasks');
        const tasks = (res?.tasks || res?.data?.tasks || [])
            .filter((x) => !x.done && sameClient(x.client, mentioned));
        if (tasks.length) {
            lines.push(`• Задачи (${tasks.length}): ${tasks.slice(0, 3).map((x) => x.title).join('; ')}`);
            speakParts.push(`задач ${tasks.length}`);
        } else {
            lines.push('• Задачи: открытых нет');
        }
    } catch (e) { /* пропускаем */ }

    // акты в Точке
    const acts = (data?.invoices || []).filter((i) =>
        i.act_pdf && i.owner_signed === false && sameClient(i.client, mentioned));
    if (acts.length) {
        lines.push(`• Акты: ждут твоей подписи в Точке (${acts.map((i) => i.number).join(', ')})`);
        speakParts.push('есть акт без подписи');
    }

    // борда
    try {
        const res = await fetchApi('/company/board');
        const qs = (res?.questions || res?.data?.questions || []).filter((q) => {
            const ql = norm(q.question || '');
            return clientTokens(mentioned).some((w) => ql.includes(w));
        });
        if (qs.length) {
            const q = qs[0];
            lines.push(`• Борда: ${q.role}: ${q.question} ${q.answered ? `(отвечено: ${q.answer.choice})` : '— ждёт ответа'}`);
        }
    } catch (e) { /* пропускаем */ }

    return {
        text: `«${invClient || mentioned}» — срез:\n` + lines.join('\n'),
        speak: `${invClient || mentioned}: ` + speakParts.join(', '),
    };
}

async function draftInvoice(text) {
    const data = await automataApi.getData();
    const clients = (data?.clients || []).map((c) => c.name);

    // клиент: «для Ромашки» → карточка ООО "РОМАШКА"
    const tn = norm(text);
    const found = matchClient(tn, clients);

    // сумма: «100 000», «100000», «100 тысяч»
    let amount = null;
    const mAmt = tn.match(/(\d[\d\s]{1,})(\s*(тыс|тысяч\w*))?/);
    if (mAmt) {
        amount = parseInt(mAmt[1].replace(/\s/g, ''), 10);
        if (mAmt[2]) amount *= 1000;
    }

    // срок: «до 20.10», «до 20 октября»
    let dueStr = '';
    const mD = tn.match(/до\s*(\d{1,2})(?:[.\s]*(\d{1,2}))?/);
    const mMonth = tn.match(/до\s*\d{1,2}\s*([а-я]+)/);
    let day = mD ? +mD[1] : null;
    let month = mD && mD[2] ? +mD[2] : null;
    if (day && !month && mMonth) {
        const word = norm(mMonth[1]);
        const idx = MONTHS.findIndex((mm) => word.startsWith(mm));
        if (idx >= 0) month = idx + 1;
    }
    if (day && month) {
        const now = new Date();
        let year = now.getFullYear();
        if (new Date(year, month - 1, day) < now) year += 1;
        dueStr = `${String(day).padStart(2, '0')}.${String(month).padStart(2, '0')}.${year}`;
    }

    if (!found) {
        return {
            text: 'Не нашла такого клиента в карточках. Проверьте имя: ' + clients.slice(0, 6).join(', ') + '…',
            speak: 'Такого клиента нет в карточках. Продиктуйте точнее.',
        };
    }
    if (!amount || amount < 1000) {
        return { text: 'Не расслышала сумму. Скажите, например: выстави счёт для Ромашки на 100 000.', speak: 'Не расслышала сумму счёта.' };
    }

    const message = 'Разовые работы' + (dueStr ? ` до ${dueStr}` : '');
    return {
        text: `Черновик счёта:\n• Клиент: ${found}\n• Сумма: ${formatRub(amount)}\n• Назначение: ${message}\n\nСкажите «подтверждаю» или нажмите кнопку — и я оформлю счёт. «Отмена» — стираю.`,
        speak: `Готова выставить счёт: ${found}, ${formatRub(amount)}, ${message}. Подтвердите?`,
        draft: { entity: 'invoice', client: found, amount, message },
    };
}

// ------------------------------------------------------------------
// ZCODE-СЕССИИ: чем занято агентство
// ------------------------------------------------------------------

async function skillSessions(text) {
    const res = await fetchApi('/sessions');
    const sessions = res?.sessions || res?.data?.sessions || [];
    if (!sessions.length) {
        return { text: 'Очередь ZCode-сессий пуста.', speak: 'Сессий пока нет.' };
    }
    // упомянут клиент/проект? показываем его сессии + хвост последнего вывода
    const data = await automataApi.getData().catch(() => null);
    const names = [...new Set([
        ...(data?.clients || []).map((c) => c.name),
        ...(data?.invoices || []).map((i) => i.client),
    ])];
    const mentioned = matchClient(text, names)
        || (/автомат|automata/.test(text) ? 'AUTOMATA-CRM' : null);

    let pick = sessions;
    let scoped = false;
    if (mentioned) {
        const key = norm(mentioned).split(/[^а-яa-z0-9]+/).find((w) => w.length >= 4) || norm(mentioned);
        pick = sessions.filter((s) => norm(String(s.project_name || '')).includes(key));
        scoped = pick.length > 0;
        if (!scoped) pick = sessions;
    }
    const list = pick.slice(0, 4);
    const ago = (s) => {
        const mins = Math.max(1, Math.round((Date.now() / 1000 - (s.last_ts || 0)) / 60));
        return mins < 60 ? `${mins} мин назад` : `${Math.round(mins / 60)} ч назад`;
    };
    let out = (scoped ? `Сессии по «${mentioned}»:\n` : 'Последние сессии агентства:\n')
        + list.map((s) => `• ${s.project_name} — ${s.turns} ходов, ${ago(s)}`).join('\n');
    if (scoped) {
        const tailLines = (pick[0].tail || '').split('\n').filter((x) => x.trim()).slice(-4);
        if (tailLines.length) out += `\n\nПоследний вывод агента:\n…${tailLines.join('\n').slice(-380)}`;
    }
    return {
        text: out,
        speak: list.slice(0, 3).map((s) => `${s.project_name}, ${s.turns} ходов`).join('. ')
            + (scoped ? '. Последний вывод продиктовать?' : ''),
    };
}

// ------------------------------------------------------------------
// ДИРЕКТИВА АГЕНТСТВУ: задача в 30_Tasks через подтверждение
// ------------------------------------------------------------------

function draftDirective(t) {
    const m = t.match(/(?:передай агенту|передай агентству|директива агент\w*|директива агентству|поставь задачу агент\w*|задание агент\w*)\s*[:,—-]?\s*(.+)/);
    const text = (m?.[1] || '').replace(/\s+/g, ' ').trim();
    if (text.length < 5) {
        return {
            text: 'Продиктуйте директиву после слов «передай агенту» — например: передай агенту, собери сводку по Загребу до вечера.',
            speak: 'Продиктуйте текст директивы.',
        };
    }
    return {
        text: `Черновик директивы агентству:\n«${text}»\n\nСкажите «подтверждаю» — создам задачу в 30_Tasks, агенты подберут на следующем тике. «Отмена» — стираю.`,
        speak: `Директива: ${text.slice(0, 120)}. Подтвердить?`,
        draft: { entity: 'task', title: `Директива (голос): ${text.slice(0, 80)}`, important: true },
    };
}

function plural(n, one, few, many) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
}
