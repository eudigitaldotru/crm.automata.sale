---
id: ticket-<% tp.date.now("x").slice(-4) %>
created: <% tp.date.now("YYYY-MM-DDTHH:mm:ss") %>
client: 
title: "<% tp.file.title %>"
description: 
status: open
priority: normal
sla_hours: 8
sla_deadline: 
resolved_at: 
time_spent_hours: 
tags:
  - ticket
---
# Тикет: `= this.title`

> **Клиент:** `= this.client` | **Приоритет:** `= this.priority` | **Статус:** `= this.status`
> **SLA дедлайн:** `= this.sla_deadline`

## Описание проблемы
`= this.description`

## Решение
