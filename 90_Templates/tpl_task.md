---
type: task
status: todo
client: "[[Название Клиента]]"
created: <% tp.date.now("YYYY-MM-DD") %>
date: ""
date_completed: ""
hours: 0
invoice: ""
tags:
  - task
---
# <% tp.file.title %>

## Описание задачи
[Что необходимо сделать]

<!--
Для матрицы Эйзенхауэра (дашборд → «Сегодня»):
  type: task | dev_task | meeting   — meeting = встреча/созвон
  date: YYYY-MM-DD                  — дата встречи (бейдж 📅 в матрице)
  тег urgent в tags                 — срочно
  тег important в tags              — важно
Пример встречи: type: meeting, date: 2026-09-15, tags: [task, meeting, important, urgent]
-->
