---
created: <% tp.file.creation_date("YYYY-MM-DD") %>
type: infrastructure
client: [[<% tp.file.cursor(1) %>]]
service_type: "Хостинг" # Хостинг / Домен / Лицензия Битрикс / Решение (Маркет)
provider: "Timeweb"
invoice_number: ""
invoice_date: <% tp.date.now("YYYY-MM-DD") %>
amount: 0
agency_fee_percent: 10
agency_fee_amount: 0
renewal_date: <% tp.date.now("YYYY-MM-DD", "P1Y") %>
status: "pending" # pending / paid / upcoming
reminder: false # Напомнить о продлении
---

# 🖥 Инфраструктура: <% tp.file.title %>

> **Клиент:** [[<% tp.file.cursor(1) %>]] | **Тип:** <% tp.file.cursor(2) %> | **Дата продления:** <% tp.date.now("DD.MM.YYYY", "P1Y") %>

---

## 📋 Детали платежа

- **Провайдер:** <% tp.file.cursor(3) %>
- **Номер счета:** <% tp.file.cursor(4) %>
- **Сумма:** <% tp.file.cursor(5) %> ₽
- **Агентские (<% tp.file.cursor(6) %>%):** `= round(this.amount * this.agency_fee_percent / 100, 2)` ₽

---

## 📎 Файлы
- [ ] Оригинал счета
- [ ] Подтверждение оплаты

---
## 📌 Заметки
<% tp.file.cursor(0) %>
