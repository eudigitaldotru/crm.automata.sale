"""
Универсальная фабрика создания сущностей CRM.

Obsidian Vault остаётся единственной базой данных: этот модуль ничего не пишет
в sidecar-хранилища, он только создаёт .md-файл в нужной папке Vault и
перегенерирует data.json дашборда. Один и тот же механизм доступен из трёх точек:
  1. Дашборд (POST /api/entities/{type} в scripts/api_server.py)
  2. CLI:  python3 scripts/create_entity.py task --title "..." --client "..." --urgent
  3. Импорт из других скриптов:  from create_entity import create_entity

Добавление новой сущности (счёт, акт, договор, клиент, контакт...) — одна запись
в ENTITY_REGISTRY: folder + fields (схема полей для формы дашборда) + render().
"""
from sec_guard import guard_open


import argparse
import datetime
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Русский → латиница, для имён файлов вида 2026-09-07_dobavit_knopku.md
TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def slugify(text, max_len=60):
    """Транслитерировать строку в slug для имени файла: 'Добавить кнопку' → 'dobavit_knopku'."""
    text = text.lower()
    translit_chars = []
    for ch in text:
        if ch in TRANSLIT:
            translit_chars.append(TRANSLIT[ch])
        elif ch.isascii() and (ch.isalnum() or ch in '_-'):
            translit_chars.append(ch)
        elif ch.isspace() or ch in '.,;:!?/\\+&()[]{}#"\'`*<>|=':
            translit_chars.append('_')
    slug = re.sub(r'_+', '_', ''.join(translit_chars)).strip('_')
    return slug[:max_len].rstrip('_') or 'untitled'


def safe_filename(name):
    """Убрать из имени файла символы, запрещённые ФС и Obsidian wiki-ссылками."""
    cleaned = re.sub(r'[\\/*?:"<>|#^\[\]]', '', str(name)).strip().strip('.')
    return cleaned or 'untitled'


class EntityError(Exception):
    """Ошибка валидации/создания сущности. message — человекочитаемый текст."""


def _ru_date(iso_date):
    """'2026-09-07' → '07.09.2026' (формат имён файлов счетов/актов)."""
    try:
        d = datetime.date.fromisoformat(str(iso_date)[:10])
        return d.strftime("%d.%m.%Y")
    except ValueError:
        return _ru_date(datetime.date.today().isoformat())


def _yaml_escape(text):
    """Однострочная строка, безопасная для двойных кавычек в YAML."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "; ")


def _next_b24_number():
    """Следующий номер счёта B24-XXXX: максимум по 30_Invoices + 1."""
    folder = os.path.join(BASE_DIR, "30_Invoices")
    max_num = None
    if os.path.isdir(folder):
        for fname in os.listdir(folder):
            m = re.search(r"B24-(\d+)", fname)
            if m:
                n = int(m.group(1))
                max_num = n if max_num is None else max(max_num, n)
    return f"B24-{(max_num if max_num is not None else 9399) + 1}"


def _next_act_number():
    """Номер автономного акта АКТ-ГГГГ-NN (для актов без привязки к счёту)."""
    folder = os.path.join(BASE_DIR, "35_Acts")
    year = datetime.date.today().year
    max_seq = 0
    if os.path.isdir(folder):
        for fname in os.listdir(folder):
            m = re.search(rf"АКТ-{year}-(\d+)", fname)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
    return f"АКТ-{year}-{max_seq + 1:02d}"


def _prepare_invoice(values):
    """Вычислить автономер счёта до рендера имени и тела."""
    values["invoice_number"] = _next_b24_number()


def _prepare_act(values):
    """Акт без номера счёта получает собственный автономер АКТ-ГГГГ-NN."""
    if not values.get("invoice_number"):
        values["invoice_number"] = _next_act_number()


# ---------------------------------------------------------------------------
# Реестр сущностей
# ---------------------------------------------------------------------------
# Типы полей схемы (используются и бэкендом, и генератором формы на дашборде):
#   text      — однострочный ввод
#   textarea  — многострочный текст
#   number    — число (float)
#   date      — дата YYYY-MM-DD
#   checkbox  — булево
#   client    — выбор клиента из 10_Clients/ (опции дашборд берёт из data.json)
ENTITY_REGISTRY = {
    "task": {
        "label": "Задача",
        "icon": "✓",
        "folder": "30_Tasks",
        "description": "Карточка задачи в 30_Tasks/. Квадрант матрицы Эйзенхауэра "
                       "определяется тегами urgent/important.",
        "preview": "eisenhower",
        "fields": [
            {"name": "title", "label": "Название задачи", "type": "text",
             "required": True, "placeholder": "Например: Продлить лицензию Битрикс"},
            {"name": "client", "label": "Клиент", "type": "client",
             "help": "Ссылка на карточку клиента. Пусто — внутренняя задача AUTOMATA."},
            {"name": "urgent", "label": "🔥 Срочно", "type": "checkbox"},
            {"name": "important", "label": "⭐ Важно", "type": "checkbox"},
            {"name": "hours", "label": "Часы (оценка)", "type": "number", "default": 0},
            {"name": "created", "label": "Дата создания", "type": "date",
             "default": "today"},
            {"name": "description", "label": "Описание задачи", "type": "textarea",
             "placeholder": "Что необходимо сделать"},
        ],
    },
    "invoice": {
        "label": "Счёт (разовая услуга)",
        "icon": "💸",
        "folder": "30_Invoices",
        "description": "Простой счёт за разовые работы вне тарифа поддержки. "
                       "Номер B24-XXXX присваивается автоматически; счёт появится "
                       "в блоке «Неоплаченные счета» с кнопками PDF/Email/TG.",
        "prepare": _prepare_invoice,
        "fields": [
            {"name": "client", "label": "Клиент", "type": "client", "required": True},
            {"name": "amount", "label": "Сумма, ₽", "type": "number", "required": True,
             "placeholder": "15000"},
            {"name": "message", "label": "Назначение (услуги по счёту)", "type": "textarea",
             "required": True, "placeholder": "Например: Доработка формы оформления заказа"},
            {"name": "invoice_date", "label": "Дата счёта", "type": "date", "default": "today"},
            {"name": "period", "label": "Период работ (необязательно)", "type": "text",
             "placeholder": "Например: Сентябрь 2026"},
        ],
    },
    "act": {
        "label": "Акт выполненных работ",
        "icon": "📄",
        "folder": "35_Acts",
        "description": "Акт для разовых работ. Если указать № счёта — акт привяжется к нему, "
                       "иначе получит собственный номер АКТ-ГГГГ-NN.",
        "prepare": _prepare_act,
        "fields": [
            {"name": "client", "label": "Клиент", "type": "client", "required": True},
            {"name": "amount", "label": "Сумма, ₽", "type": "number", "required": True,
             "placeholder": "15000"},
            {"name": "services", "label": "Выполненные работы", "type": "textarea",
             "required": True, "placeholder": "Перечень выполненных работ"},
            {"name": "act_date", "label": "Дата акта", "type": "date", "default": "today"},
            {"name": "invoice_number", "label": "№ счёта (необязательно)", "type": "text",
             "placeholder": "B24-9334"},
        ],
    },
}


def _field(cfg, name):
    return next((f for f in cfg["fields"] if f["name"] == name), None)


def _coerce(field, raw):
    """Привести значение поля к типу схемы. Пустая строка → значение по умолчанию/None."""
    ftype = field["type"]
    if ftype == "checkbox":
        return bool(raw) if raw is not None else False
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if field.get("default") == "today":
            return datetime.date.today().isoformat()
        if "default" in field:
            return field["default"]
        return None
    if ftype == "number":
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise EntityError(f"Поле «{field['label']}»: ожидается число, получено «{raw}»")
    return str(raw).strip()


def _validate(cfg, payload):
    """Проверить payload по схеме. Возвращает dict значений по всем полям схемы."""
    values = {}
    missing = []
    for field in cfg["fields"]:
        val = _coerce(field, payload.get(field["name"]))
        if field.get("required") and (val is None or val == ""):
            missing.append(field["label"])
        values[field["name"]] = val
    if missing:
        raise EntityError("Не заполнены обязательные поля: " + ", ".join(missing))
    unknown = set(payload) - {f["name"] for f in cfg["fields"]}
    if unknown:
        raise EntityError("Неизвестные поля для «%s»: %s" % (cfg["label"], ", ".join(sorted(unknown))))
    return values


def _build_task(values):
    """Рендер .md задачи — формат из .agent/workflows/create_task.md и 90_Templates/tpl_task.md."""
    client_link = f'[[{values["client"]}]]' if values.get("client") else ""
    tags = ["task"]
    if values.get("urgent"):
        tags.append("urgent")
    if values.get("important"):
        tags.append("important")
    tag_lines = "".join(f"  - {t}\n" for t in tags)
    hours = f'{values.get("hours"):g}' if values.get("hours") is not None else "0"
    description = values.get("description") or "[Что необходимо сделать]"

    return f"""---
type: task
status: todo
client: "{client_link}"
created: {values.get("created") or datetime.date.today().isoformat()}
date_completed: ""
hours: {hours}
invoice: ""
tags:
{tag_lines}---
# {values["title"]}

## Описание задачи
{description}
"""


# Рендереры контента для каждого типа сущности
def _build_invoice(values):
    """Счёт за разовые работы — формат 90_Templates/tpl_invoice.md (без Templater)."""
    num = values["invoice_number"]
    date_iso = values.get("invoice_date") or datetime.date.today().isoformat()
    date_ru = _ru_date(date_iso)
    due_ru = _ru_date((datetime.date.fromisoformat(date_iso) + datetime.timedelta(days=7)).isoformat())
    amount = values.get("amount") or 0
    client = values["client"]
    lines = [
        "---",
        f"created: {datetime.date.today().isoformat()}",
        "tags:",
        "  - unpaid_invoice",
        "  - one_off",
        f'client: "[[{client}]]"',
        f"invoice_number: {num}",
        f"invoice_date: {date_iso}",
        f"amount: {amount:g}",
        "status: unpaid",
        "payment_date: ",
        "payment_method: ",
        "sent_count: 0",
        f'message: "{_yaml_escape(values.get("message") or "")}"',
    ]
    if values.get("period"):
        lines.append(f'period: "{_yaml_escape(values["period"])}"')
    lines += [
        "---",
        "",
        f"# Счёт №{num} от {date_ru} — {client}",
        "",
        f"> **Статус:** 🟡 Не оплачен | **Сумма:** {amount:g} ₽ | **Дата выставления:** {date_ru}",
        "",
        "---",
        "",
        "## 📋 Детали счёта",
        "",
        f"**Клиент:** [[{client}]]",
        f"**Дата выставления:** {date_ru}",
        f"**Срок оплаты:** {due_ru} (7 дней)",
        f"**Сумма:** {amount:g} ₽",
        "",
        "---",
        "",
        "## 📝 Услуги по счёту",
        "",
        values.get("message") or "[Разовые работы]",
        "",
        "---",
        "",
        "## 💳 Оплата",
        "",
        "**Дата оплаты:** ",
        "**Способ оплаты:** Точка Банк / СБП / Наличные",
        "**Комментарий:** ",
        "",
        "---",
        "",
        "## 📎 Файлы и Действия",
        "",
        "- [ ] Счёт (PDF) — сгенерировать можно кнопкой в строке счёта на дашборде",
        "- [ ] Акт выполненных работ",
        "- [ ] Подписанные документы",
        "",
    ]
    return "\n".join(lines)


def _build_act(values):
    """Акт выполненных работ для разовых услуг (35_Acts/)."""
    num = values["invoice_number"]
    date_iso = values.get("act_date") or datetime.date.today().isoformat()
    date_ru = _ru_date(date_iso)
    amount = values.get("amount") or 0
    client = values["client"]
    lines = [
        "---",
        f"created: {datetime.date.today().isoformat()}",
        "tags:",
        "  - unsigned_act",
        f'client: "[[{client}]]"',
        f"invoice_number: {num}",
        f"act_date: {date_iso}",
        f"amount: {amount:g}",
        "status: unsigned",
        f'services: "{_yaml_escape(values.get("services") or "")}"',
    ]
    if values.get("period"):
        lines.append(f'period: "{_yaml_escape(values["period"])}"')
    lines += [
        "---",
        "",
        f"# Акт №{num} от {date_ru} — {client}",
        "",
        "## Реквизиты",
        "",
        "**Исполнитель:** " + os.getenv("CRM_OWNER_LEGAL", "ИП Фамилия И.О., ИНН 000000000000"),
        f"**Заказчик:** [[{client}]]",
        f"**Дата акта:** {date_ru}",
        f"**Сумма:** {amount:g} ₽",
        "",
        "## Выполненные работы",
        "",
        values.get("services") or "[Перечень работ]",
        "",
        "## Подписи",
        "",
        f"- [ ] Подписан клиентом ({date_ru})",
        "",
    ]
    return "\n".join(lines)


RENDERERS = {
    "task": _build_task,
    "invoice": _build_invoice,
    "act": _build_act,
}

# Построители имени файла (без расширения) для каждого типа сущности
FILENAME_BUILDERS = {
    "task": lambda v: f'{v.get("created") or datetime.date.today().isoformat()}_{slugify(v["title"])}',
    "invoice": lambda v: f'Счёт №{v["invoice_number"]} от {_ru_date(v.get("invoice_date"))} — {v["client"]}',
    "act": lambda v: f'Акт №{v["invoice_number"]} от {_ru_date(v.get("act_date"))} — {v["client"]}',
}


def get_schemas():
    """Схемы всех сущностей для дашборда (форма строится по этой схеме на фронте).
    Серверные хуки (prepare и др. callable) наружу не отдаются — JSON-безопасная копия."""
    return {
        name: {k: v for k, v in cfg.items() if not callable(v)}
        for name, cfg in ENTITY_REGISTRY.items()
    }


def _unique_path(folder, stem):
    """Путь к файлу без коллизий: при существовании добавляет _2, _3..."""
    path = os.path.join(folder, f"{stem}.md")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem}_{counter}.md")
        counter += 1
    return path


def create_entity(entity_type, payload):
    """Создать .md-файл сущности в Vault. Возвращает информацию о созданном файле.

    payload — плоский dict {имя_поля: значение}. Бросает EntityError при
    неизвестном типе сущности или ошибке валидации.
    """
    cfg = ENTITY_REGISTRY.get(entity_type)
    if cfg is None:
        raise EntityError(f"Неизвестный тип сущности: {entity_type}. "
                          f"Доступны: {', '.join(ENTITY_REGISTRY)}")

    values = _validate(cfg, payload)
    prepare = cfg.get("prepare")
    if prepare:
        prepare(values)
    renderer = RENDERERS.get(entity_type)
    filename_builder = FILENAME_BUILDERS.get(entity_type)
    if renderer is None or filename_builder is None:
        raise EntityError(f"Для «{entity_type}» не задан рендерер контента/имени файла")

    folder = os.path.join(BASE_DIR, cfg["folder"])
    os.makedirs(folder, exist_ok=True)
    stem = safe_filename(filename_builder(values))
    path = _unique_path(folder, stem)

    with guard_open(path, "w", encoding="utf-8") as f:
        f.write(renderer(values))

    return {
        "type": entity_type,
        "label": cfg["label"],
        "file": os.path.basename(path),
        "folder": cfg["folder"],
        "path": os.path.relpath(path, BASE_DIR),
    }


def rebuild_dashboard():
    """Перегенерировать data.json дашборда, чтобы новая сущность появилась сразу."""
    sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
    import extract_dashboard_data
    import importlib
    importlib.reload(extract_dashboard_data)
    data = extract_dashboard_data.build_dashboard_data()
    data_file = os.path.join(BASE_DIR, "dashboard", "public", "data", "data.json")
    tmp_path = data_file + ".tmp"
    with guard_open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, data_file)
    return data_file


# ---------------------------------------------------------------------------
# CLI — тот же механизм для агентов и скриптов
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--schemas", "schemas"):
        print(json.dumps(get_schemas(), ensure_ascii=False, indent=2))
        return

    entity_type = sys.argv[1] if len(sys.argv) > 1 else None
    if entity_type not in ENTITY_REGISTRY:
        types = ", ".join(ENTITY_REGISTRY)
        sys.exit(f"Использование: create_entity.py <{'|'.join(ENTITY_REGISTRY)}> [поля]\n"
                 f"Доступные типы: {types}\n"
                 f"Схемы полей: create_entity.py --schemas")

    cfg = ENTITY_REGISTRY[entity_type]
    parser = argparse.ArgumentParser(prog=f"create_entity.py {entity_type}",
                                     description=f"Создать {cfg['label']} в Vault")
    for field in cfg["fields"]:
        if field["type"] == "checkbox":
            parser.add_argument(f"--{field['name']}", action="store_true",
                                help=field["label"])
        else:
            parser.add_argument(f"--{field['name']}", default=None, help=field["label"])
    parser.add_argument("--no-refresh", action="store_true",
                        help="не перегенерировать data.json после создания")
    args = parser.parse_args(sys.argv[2:])

    payload = {f["name"]: getattr(args, f["name"]) for f in cfg["fields"]}
    try:
        result = create_entity(entity_type, payload)
    except EntityError as e:
        sys.exit(f"❌ {e}")

    print(f"✅ Создано: {result['path']}")
    if not args.no_refresh:
        try:
            rebuild_dashboard()
            print("✅ data.json перегенерирован")
        except Exception as e:
            print(f"⚠️  Не удалось перегенерировать data.json: {e}")


if __name__ == "__main__":
    main()
