<%*
// Начальные значения
let selectedClient = "Unknown";
let invoiceNumber = "DRAFT";
let amount = 0;
let period = "";
let message = "";
let itemsYaml = "";

try {
    // БЛОК 1: Получаем список клиентов
    const clients = app.vault.getMarkdownFiles()
      .filter(f => f.path.startsWith("10_Clients/") && !f.path.includes("Contacts"))
      .map(f => f.basename)
      .sort();

    // БЛОК 2: Показываем выбор клиента
    const selected = await tp.system.suggester(clients, clients, false, "Выберите клиента:");
    if (!selected) throw new Error("Клиент не выбран (нажата отмена)");
    selectedClient = selected;

    // БЛОК 3: Тип счёта (Услуга или Лицензия)
    const invType = await tp.system.suggester(["🛠️ Услуги (Сопровождение)", "📦 Лицензии (Битрикс)"], ["service", "license"], false, "Тип счёта?");
    if (!invType) throw new Error("Тип счёта не выбран");

    if (invType === "service") {
        const p = await tp.system.prompt("Период работ (например: март 2026):");
        if (p) period = p;
    }

    // БЛОК 4.1: Сообщение для клиента (Пояснение к счёту)
    const msg = await tp.system.prompt("Пояснение для клиента (необязательно, например: 'дизайн сайта'):");
    if (msg) message = msg;

    // БЛОК 5: Товары и услуги (Фильтрация)
    const productsFiles = app.vault.getMarkdownFiles()
      .filter(f => f.path.startsWith("70_Products/"));
    
    let products = [];
    if (invType === "service") {
        products = productsFiles.filter(f => f.basename.startsWith("Service_")).map(f => f.basename).sort();
    } else {
        products = productsFiles.filter(f => f.basename.startsWith("Lic_")).map(f => f.basename).sort();
    }
    
    // Если список пуст, покажем все
    if (products.length === 0) {
        products = productsFiles.map(f => f.basename).sort();
    }

    let items = [];
    let totalAmount = 0;
    
    let addMore = true;
    // Сразу предлагаем выбрать первый товар
    while (addMore) {
        const product = await tp.system.suggester(products, products, false, "Выберите товар/услугу:");
        if (product) {
            const quantityStr = await tp.system.prompt(`Количество для ${product}:`, "1");
            const quantity = parseFloat(quantityStr) || 1;
            
            // Находим цену товара
            const pFile = productsFiles.find(f => f.basename === product);
            let price = 0;
            if (pFile) {
                 const cache = app.metadataCache.getFileCache(pFile);
                 if (cache && cache.frontmatter && cache.frontmatter.price) {
                     price = parseFloat(cache.frontmatter.price);
                 }
            }
            
            totalAmount += price * quantity;
            items.push({ product: product, quantity: quantity });
        } else {
            // Если нажали Esc при выборе товара, выходим из цикла
            break;
        }
        
        // Спрашиваем про еще один товар только если уже выбрали что-то
        if (items.length > 0) {
            addMore = await tp.system.suggester(["Добавить ещё позицию", "Готово"], [true, false], false, "Продолжить?");
        } else {
             addMore = false;
        }
    }

    // БЛОК 6: Авто-нумерация (B24-9255+)
    const invoices = app.vault.getMarkdownFiles().filter(f => f.path.startsWith("30_Invoices/"));
    let maxNum = 9254; 
    const regex = /B24-(\d+)/;
    invoices.forEach(f => {
        const match = f.basename.match(regex);
        if (match) {
            const num = parseInt(match[1]);
            if (num > maxNum) maxNum = num;
        }
    });
    invoiceNumber = `B24-${maxNum + 1}`;
    amount = totalAmount;

    // Fallback сумма
    if (amount === 0 && items.length === 0) {
        const manualsAmt = await tp.system.prompt("Сумма (без пробелов):", "0");
        amount = parseFloat(manualsAmt) || 0;
    }

    // Формируем имя файла
    const fileName = `Счёт №${invoiceNumber} от ${tp.date.now("DD.MM.YYYY")} — ${selectedClient}`;
    await tp.file.rename(fileName);

    // Подготовка YAML для items
    if (items.length > 0) {
        // Формируем блок items как список строк (для читаемости в Obsidian)
        itemsYaml = "items:";
        items.forEach(item => {
            // Формат: "[[Product]] xQuantity"
            itemsYaml += `\n  - "[[${item.product}]] x ${item.quantity}"`;
        });
    }

    // === ГЕНЕРАЦИЯ FRONTMATTER ===
    tR += "---\n";
    tR += `created: ${tp.file.creation_date("YYYY-MM-DD")}\n`;
    tR += "tags:\n";
    tR += "  - unpaid_invoice\n";
    tR += `client: "[[${selectedClient}]]"\n`;
    tR += `invoice_number: ${invoiceNumber}\n`;
    tR += `invoice_date: ${tp.date.now("YYYY-MM-DD")}\n`;
    tR += `amount: ${amount}\n`;
    tR += "status: unpaid\n";
    tR += "payment_date: \n";
    tR += "payment_method: \n";
    if (period) tR += `period: ${period}\n`;
    if (message) tR += `message: "${message}"\n`;
    if (itemsYaml) tR += `${itemsYaml}\n`;
    tR += "---\n\n";

    // === ГЕНЕРАЦИЯ ТЕЛА ЗАМЕТКИ ===
    tR += `# Счёт №${invoiceNumber} от ${tp.date.now("DD.MM.YYYY")} — ${selectedClient}\n\n`;
    tR += `> **Статус:** 🟡 Не оплачен | **Сумма:** ${amount} ₽ | **Дата выставления:** ${tp.date.now("DD.MM.YYYY")}\n\n`;
    tR += "---\n\n";
    tR += "## 📋 Детали счёта\n\n";
    tR += `**Клиент:** [[${selectedClient}]]\n`;
    if (period) tR += `**Период работ:** ${period}\n`;
    tR += `**Дата выставления:** ${tp.date.now("DD.MM.YYYY")}\n`;
    tR += `**Срок оплаты:** ${tp.date.now("DD.MM.YYYY", 7)} (7 дней)\n`;
    tR += `**Сумма:** ${amount} ₽\n\n`;
    tR += "---\n\n";
    tR += "## 📝 Работы по счёту\n\n";
    if (invType === "service") {
        tR += "*(Скопируйте сюда лог работ из карточки клиента)*\n\n";
    } else {
        // Для лицензий перечислим товары
        items.forEach(item => {
            tR += `- [[${item.product}]] x ${item.quantity}\n`;
        });
        tR += "\n";
    }
    tR += "---\n\n";
    tR += "## 💳 Оплата\n\n";
    tR += "**Дата оплаты:** \n";
    tR += "**Способ оплаты:** Точка Банк / СБП / Наличные\n";
    tR += "**Комментарий:** \n\n";
    tR += "---\n\n";
    tR += "## 📎 Файлы и Действия\n\n";
    tR += "> [!success] Автоматизация\n";
    tR += "> [🚀 Сгенерировать и Отправить Счёт (Email + Telegram)](obsidian://shell-commands/?vault=AUTOMATA-CRM&execute=generate_and_send_all)\n";
    tR += "> [📝 Сгенерировать Акт выполненных работ](obsidian://shell-commands/?vault=AUTOMATA-CRM&execute=u3u3h7ze7w)\n\n";
    tR += "- [ ] Счёт (PDF)\n";
    tR += "- [ ] Акт выполненных работ\n";
    tR += "- [ ] Подписанные документы\n";

} catch (e) {
    new Notice("Ошибка шаблона: " + e.message, 5000);
    tR += `⚠️ **Ошибка при создании счёта:** ${e.message}`;
}
%>
