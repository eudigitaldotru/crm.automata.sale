---
id: goal-<% tp.date.now("x").slice(-4) %>
title: "<% tp.file.title %>"
type: business
created: <% tp.date.now("YYYY-MM-DD") %>
deadline: 
metric: 
target_value: 
current_value: 0
unit: 
direction: increase
status: active
tags:
  - goal
---
# Цель: `= this.title`

> **Тип:** `= this.type` | **Дедлайн:** `= this.deadline` | **Прогресс:** `= this.current_value` / `= this.target_value` `= this.unit`
