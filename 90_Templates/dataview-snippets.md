# Сниппеты Dataview для Дашборда и Карточек

## 1. Новые активные лиды

```dataview
TABLE WITHOUT ID
  file.link AS "Лид",
  source AS "Источник",
  quality AS "Качество",
  estimated_amount AS "Сумма",
  next_action AS "Следующий шаг"
FROM "15_Leads"
WHERE status != "won" AND status != "lost"
SORT quality DESC, created DESC
```

## 2. Открытые тикеты с истекающим SLA

```dataview
TABLE WITHOUT ID
  file.link AS "Тикет",
  client AS "Клиент",
  priority AS "Приоритет",
  (date(sla_deadline) - date(now)).hours AS "Часов до SLA"
FROM "45_Tickets"
WHERE status != "closed" AND status != "resolved"
SORT sla_deadline ASC
```

## 3. Прогресс целей

```dataview
TABLE WITHOUT ID
  file.link AS "Цель",
  current_value + " " + unit AS "Сейчас",
  target_value + " " + unit AS "Цель",
  round(((current_value - target_value) / target_value) * 100, 1) + "%" AS "Отклонение"
FROM "55_Goals"
WHERE status = "active"
```
