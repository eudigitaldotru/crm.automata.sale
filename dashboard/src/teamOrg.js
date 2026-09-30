/**
 * teamOrg.js — структура «Команды Автомата» для вкладки «Совет».
 * Дерево подчинённости (владелец → гендир → финдир/комдир/маркетолог/юрист),
 * исполнительный контур 15-мин цикла и цепочка «как течёт решение».
 * Карточка роли раскрывается кликом: что делает / читает / выдаёт / границы.
 */

const ORG_OWNER = {
    emoji: '👑',
    name: 'Евгений — владелец',
    tag: 'центр решений',
    short: 'Утверждает цены, работы, сроки и деньги («ок»). Отвечает на ❓-вопросы кнопками.',
    does: [
        'Единственный, кто говорит «ок» на цены, скидки, сроки, новые работы (CHARTER §4 «никогда»).',
        'Утвердил прайс-флор 22.09 — гейт в цикле блокирует цены ниже флора.',
        'Отвечает на вопросы команды кнопками а/б/в на вкладке «Совет» (или в чате).',
        'Ставит цели квартала — планка гендира читает их как единственный источник.'
    ],
    reads: ['company/CHARTER.md', 'вкладка «Совет»: KPI + решения', 'сводки цикла в ленте'],
    gives: ['«ок» / вето', 'ответы на ❓ (answers.json)', 'корректировка целей и флора'],
    call: '— просто ответить на вопрос кнопкой выше'
};

const ORG_TREE = [
    {
        id: 'gendir', emoji: '🎯', name: 'Гендир', tag: 'пн 08:00 · планка недели',
        short: 'Держит цель 450 тыс ₽/мес. Приоритеты недели и красный список дня.',
        does: [
            'Планка недели: 3 приоритета + красный список дня из открытых задач.',
            'Сверка «проектировал → принесло деньги»: что из работ недели закрылось в выручку.',
            'Правило «сначала КП — потом код»: разработка без утверждённого КП — стоп.',
            'Эскалация оттока: кто из клиентов «на паузе» — план возврата.'
        ],
        reads: ['CHARTER (цели, «никогда»)', '55_Goals/*.md', '15_Leads/_kanban_pipeline.md', '45_Tickets + 30_Tasks'],
        gives: ['journal/<дата>_gendir.md', 'приоритеты для комдира и маркетолога', '❓-вопросы владельцу'],
        call: '/gendir'
    },
    {
        id: 'findir', emoji: '💰', name: 'Финдир', tag: 'пт 16:30 · цифры недели',
        short: 'Касса, дебиторка, юнит-экономика. Гейт прайс-флора — цены ниже пола не проходят.',
        does: [
            'Выручка месяца vs цель (оплаченные счета + сверки транзакций).',
            'Дебиторка по эскалации D+7 / D+14 / D+30 (CHARTER §3).',
            'Топ-расходы и юнит-экономика тарифов — где течёт маржа.',
            'ГЕЙТ: любое КП/счёт/скидка ниже флора или скидка >10% → стоп, вопрос владельцу.'
        ],
        reads: ['30_Invoices/*.md', 'crm_state.db.matched_transactions', 'CHARTER §2 (флор)', '55_Goals (обновляет current_value)'],
        gives: ['journal/<дата>_findir.md', 'стоп-гейт для цикла (шаг 5.6)', 'график эскалации должников для комдира'],
        call: '/findir'
    },
    {
        id: 'komdir', emoji: '📞', name: 'Комдир', tag: 'будни 09:45 · касания дня',
        short: 'Живой контакт: спящие клиенты, лиды, должники. Черновики — владельцу на «ок».',
        does: [
            'Спящие клиенты: без касания >30 дней → черновик реактивации под новые тарифы.',
            'Лиды: без касания 3+ дня → следующий шаг по воронке.',
            'Должники: по графику эскалации финдира (вежливо → требование → юрист).',
            'Чувствительное (долги, конфликты) — только черновиком, владелец утверждает.'
        ],
        reads: ['10_Clients (last_contact_date)', '15_Leads', '30_Invoices unpaid', 'последний journal/*_findir.md'],
        gives: ['journal/<дата>_komdir.md', 'черновики сообщений в тикеты', 'last_contact_date в карточках'],
        call: '/komdir'
    },
    {
        id: 'marketing', emoji: '📝', name: 'Маркетолог', tag: 'пн 11:00 · чётные недели',
        short: 'Двухнедельные спринты: контент под /tariffs/, AEO/GEO, кросспосты. Лиды на цель.',
        does: [
            'Контент-спринт: статья под продуктовые страницы /tariffs/ → smm-crosspost.',
            'AEO/GEO-проход: llms.txt, JSON-LD — оптимизация под ChatGPT/Perplexity/Нейро.',
            'Метрики публикаций → что приводит лиды, что нет.',
            'Пайплайн лидов в связке с комдиром (кто дозрев — тому касание).'
        ],
        reads: ['блог-конвейер (статьи, кросспосты)', 'скиллы aeo / llm-seo-optimize / smm-crosspost', 'метрики трафика'],
        gives: ['journal/<дата>_marketing.md', 'опубликованные статьи + кросспосты', 'контент-план спринта'],
        call: '/marketing'
    },
    {
        id: 'lawyer', emoji: '⚖️', name: 'Юрист', tag: 'по гейту · без слота',
        short: 'Договоры до подписи и претензии должникам. Вызывается финдиром (D+30) и флоу договоров.',
        does: [
            'Чек-лист договора перед подписью: реквизиты, предоплата, приложения.',
            'Досудебные претензии — комплект из кейса Загреба как шаблон.',
            'Фиксация переписки как доказательств (что сохранять, чем заверить).',
            'Вето на рискованные формулировки до отправки клиенту.'
        ],
        reads: ['90_Templates/contract_appendices', '50_Legal (претензионные комплекты)', 'переписка из 20_Inbox/20_Outbox'],
        gives: ['вердикт по договору (подписать / правки / стоп)', 'претензии и отзывы претензий', 'journal/<дата>_lawyer.md'],
        call: '/lawyer'
    }
];

const ORG_CYCLE = {
    emoji: '⚙️', name: '15-минутный цикл — исполнительный контур', tag: 'пн–пт 9:00–19:45',
    short: 'Операционка Джарвиса: собирает всё, общается свободно, исполняет «ок» владельца.',
    does: [
        'Сбор: почта + MAX + Telegram → индекс → триаж → LLM-разбор.',
        'Автокоммуникация: ответы клиентам свободны 24/7; работы/цены — только по «ок».',
        'Гейты: прайс-флор финдира (шаг 5.6), красный список вечера (8.5), вопросы → журнал и «Совет» (8.6).',
        'Единая лента + сводка дня; вердикты ролей проецируются каналом «Совет».'
    ],
    gives: ['сводки в ленту', '❓-вопросы дня на «Совет»', 'тикет-эскалации']
};

const FLOW_STEPS = [
    { icon: '🧠', title: 'Роль готовит вердикт', text: 'гендир/финдир/… по ритуалу или по запросу' },
    { icon: '📜', title: 'Журнал', text: 'company/journal → лента «Совет»' },
    { icon: '❓', title: 'Вопрос с кнопками', text: 'на «Совете» + пуш (макс 1/ритуал)' },
    { icon: '👑', title: 'Твоё «ок»', text: 'кнопка а/б/в или ответ в чате' },
    { icon: '⚙️', title: 'Исполнение', text: 'цикл/Джарвис; чувствительное — черновиком' }
];

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function orgDetailsBlock(r) {
    return `
        <div class="org-details">
            <div class="org-details-sec"><span class="org-details-h">Что делает</span>
                <ul>${(r.does || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
            <div class="org-details-sec"><span class="org-details-h">Читает</span>
                <div class="org-chips">${(r.reads || []).map(x => `<span class="org-chip">${esc(x)}</span>`).join('') || '<span class="org-chip">—</span>'}</div></div>
            <div class="org-details-sec"><span class="org-details-h">Выдаёт</span>
                <div class="org-chips">${(r.gives || []).map(x => `<span class="org-chip org-chip--out">${esc(x)}</span>`).join('') || '<span class="org-chip">—</span>'}</div></div>
            <div class="org-call">Спросить напрямую: <code>${esc(r.call)}</code></div>
        </div>`;
}

function orgCard(r, extraClass = '') {
    return `
    <div class="org-card ${extraClass}" data-role="${esc(r.id || '')}" tabindex="0" role="button" aria-expanded="false">
        <div class="org-card-top"><span class="org-emoji">${r.emoji}</span><span class="org-name">${esc(r.name)}</span></div>
        <div class="org-tag">${esc(r.tag)}</div>
        <div class="org-short">${esc(r.short)}</div>
        <div class="org-more">подробнее ▾</div>
        ${orgDetailsBlock(r)}
    </div>`;
}

/** HTML дерева команды + контура цикла + потока решения. */
export function renderOrg() {
    const staff = ORG_TREE.filter(r => r.id !== 'lawyer');
    const lawyer = ORG_TREE.find(r => r.id === 'lawyer');
    return `
    <details class="board-org" open>
        <summary class="board-org-summary">🏛 Структура команды — кто что делает и как взаимодействует</summary>
        <div class="org-scroll">
            <div class="org-tree">
                <div class="org-node">${orgCard(ORG_OWNER, 'org-card--owner')}</div>
                <ul class="org-children">
                    <li class="org-branch">
                        <div class="org-node">${orgCard(staff[0])}</div>
                        <ul class="org-children">
                            ${staff.slice(1).map(r => `<li class="org-branch"><div class="org-node">${orgCard(r)}</div></li>`).join('')}
                            <li class="org-branch"><div class="org-node">${orgCard(lawyer, 'org-card--gate')}</div></li>
                        </ul>
                    </li>
                </ul>
                <div class="org-cycle">${orgCard(ORG_CYCLE, 'org-card--cycle')}</div>
            </div>
        </div>
        <div class="org-flow">
            <div class="org-flow-title">Как течёт решение</div>
            <div class="org-flow-steps">
                ${FLOW_STEPS.map((s, i) => `
                    <div class="org-flow-step">
                        <div class="org-flow-icon">${s.icon}</div>
                        <div class="org-flow-h">${esc(s.title)}</div>
                        <div class="org-flow-t">${esc(s.text)}</div>
                    </div>${i < FLOW_STEPS.length - 1 ? '<div class="org-flow-arrow">→</div>' : ''}`).join('')}
            </div>
        </div>
        <div class="org-legend">
            <span class="org-leg"><span class="org-dot org-dot--gate"></span> вызывается по гейту (нет своего слота)</span>
            <span class="org-leg"><span class="org-dot org-dot--cycle"></span> исполнительный контур — подчинён всем ролям и владельцу</span>
            <span class="org-leg">карточка кликабельна — раскрывает полное описание роли</span>
        </div>
    </details>`;
}

/** Разворачивание/сворачивание карточек ролей внутри контейнера. */
export function initOrg(root) {
    root.querySelectorAll('.org-card').forEach(card => {
        card.addEventListener('click', () => {
            const open = card.classList.toggle('org-card--open');
            card.setAttribute('aria-expanded', open ? 'true' : 'false');
            const more = card.querySelector('.org-more');
            if (more) more.textContent = open ? 'свернуть ▴' : 'подробнее ▾';
        });
        card.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
        });
    });
}
