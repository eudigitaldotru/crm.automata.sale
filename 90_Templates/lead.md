---
id: lead-<% tp.date.now("YYYY-MM-DD") %>-<% tp.date.now("x").slice(-4) %>
created: <% tp.date.now("YYYY-MM-DDTHH:mm:ss") %>
source: telegram
contact_name: 
contact_tg: 
contact_email: 
contact_phone: 
status: new
quality: cold
estimated_amount: 
project_type: 
notes: 
last_contact: <% tp.date.now("YYYY-MM-DDTHH:mm:ss") %>
next_action: 
deal_link: 
client_link: 
tags:
  - lead
---
# Лид: <% tp.file.title %>

> **Источник:** `= this.source` | **Качество:** `= this.quality` | **Сумма:** `= this.estimated_amount` ₽

## Описание
`= this.notes`

## Следующий шаг
`= this.next_action`
