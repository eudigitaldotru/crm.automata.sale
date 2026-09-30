---
tags: [deal, active]
client: "[[{{client_name}}]]"
period: "{{YYYY-MM}}"
deal_type: "monthly_support" # monthly_support | one_time | project
base_amount: {{base_amount}}
included_hours: {{included_hours}}
status: "in_progress"  # in_progress | ready_to_bill | billed | closed

# Отслеживание времени
hours_spent: 0
extra_hours: 0
extra_amount: 0

# Связанные документы
invoice: ""  # Будет заполнено при создании
act: ""
gdrive_folder: "{{gdrive_link}}"
---

# Сделка: {{Month}} {{Year}} — {{Client}}

## 📊 Статус
🟡 В работе | Потрачено: `dv.current().hours_spent`ч из `dv.current().included_hours`ч

## ✅ Задачи по базовому тарифу

```dataview
TABLE
  status as "Статус",
  hours as "Время"
FROM "40_Tasks"
WHERE deal = this.file.link AND task_type = "included"
```


## 📌 Дополнительные задачи

```dataview
TABLE
  status as "Статус",
  hours as "Время"
FROM "40_Tasks"
WHERE deal = this.file.link AND task_type = "extra"
```


## 💰 Итого к оплате

- Базовый тариф: `dv.current().base_amount`₽
- Доп.работы: `dv.current().extra_amount`₽
- **ВСЕГО: `dv.current().base_amount + dv.current().extra_amount`₽**
