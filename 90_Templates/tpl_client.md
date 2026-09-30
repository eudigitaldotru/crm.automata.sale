---
created: <% tp.file.creation_date("YYYY-MM-DD") %>
modified: <% tp.file.last_modified_date("YYYY-MM-DD") %>
tags: [client, active]
lifecycle: active
support_type: retainer
support_plan: support_1h
hours_used_current_month: 0
bitrix_id: 
type: ООО
company_name: 
company_short_name: 
inn: 
kpp: 
ogrn: 
legal_address: 
bank_name: 
bank_bik: 
bank_account: 
bank_corr_account: 
contact_name: 
contact_role: 
phone: 
email: 
telegram: 
tg_id: 
# Рабочие группы Telegram, привязанные к клиенту (их может быть несколько).
# Формат: список id (число) или словарей {id, title}; id берёт AI из inbox-файла (chat_id).
tg_chats: []
gitactive_path: 
rate: 3000
last_invoice_date: 
invoice_amount: 0
total_revenue: 0
domains:
contacts: []
---

# `= this.company_name | this.file.name`

> **Жизненный цикл:** `= this.lifecycle` | **Тип:** `= this.support_type` | **План:** `= this.support_plan` | **Ставка:** `= this.rate` ₽/ч

## 🧠 Когнитивный профиль (Karpathy State)
> [!NOTE] Данный блок является системным промптом для AI-агентов при обработке `20_Inbox`.

**Паттерн переговоров (Negotiation_Style):** 
[Опишите стиль общения и ведения переговоров]

**Триггеры и Возражения (Objection_Patterns):**
[Опишите типичные возражения или триггеры клиента]

**Оптимальная стратегия (Optimal_Response_Strategy):**
[Опишите оптимальную стратегию для AI при формировании ответа]

## 🖥 Технические данные и Доступы
**CMS/Платформа:** 
**Сервер (IP):** 
**SSH-доступ:** [Ссылка на KeePass]
**Админка:** 
**Хостинг:** 

### Инфраструктура
```dataview
TABLE WITHOUT ID
  file.link as "Услуга", amount + " ₽" as "Сумма", renewal_date as "Продление"
FROM "40_Infrastructure"
WHERE client = this.file.link OR contains(string(client), this.file.name)
```

## 📝 Технический лог (AI Задачи)
> Автоматические выжимки из коммитов GITACTIVE и выполненные задачи
```dataview
TABLE status as "Статус", date_completed as "Сделано", invoice as "Счёт"
FROM "30_Tasks"
WHERE project.client = this.file.link OR client = this.file.link
SORT date_completed DESC
```

## 📄 Счета и Акты
```dataview
TABLE status as "Статус", amount + " ₽" as "Сумма", payment_date as "Оплачен"
FROM "30_Invoices"
WHERE client = this.file.link OR contains(string(client), this.file.name)
SORT invoice_date DESC
```

## 🚀 Быстрые действия
> [!success] Автоматизация
> [📄 Сгенерировать договор (3 часа)](obsidian://shell-commands/?vault=AUTOMATA-CRM&execute=generate_contract)

---
## 📌 Заметки
*(Особенности клиента: предпочитает связь в Telegram, подписывает акты только через ЭДО и т.п.)*
