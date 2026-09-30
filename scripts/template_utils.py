"""
template_utils.py — Рендеринг шаблонов писем/TG с плейсхолдерами {{var}}.

Шаблоны хранятся в 90_Templates/tpl_*.md с frontmatter (subject:) + телом.
Функция render_template() читает файл, подставляет переменные, возвращает (subject, body).
"""
import os
import re
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = VAULT_DIR / "90_Templates"

# Карта имён шаблонов → файлы
TEMPLATE_FILES = {
    "invoice_email": "tpl_invoice_email.md",
    "act_email": "tpl_act_email.md",
    "invoice_tg": "tpl_invoice_tg.md",
    # Тело генератора договоров ({{плейсхолдеры}} + данные клиента из 10_Clients/).
    "contract_support": "tpl_contract_support.md",
    # Приложения договора (собираются генератором, нумерация автоматическая)
    "contract_app_sla": "contract_appendices/app_sla.md",
    "contract_app_tm": "contract_appendices/app_tm.md",
    "contract_app_act_form": "contract_appendices/app_act_form.md",
    "contract_app_nda": "contract_appendices/app_nda.md",
    "contract_app_security": "contract_appendices/app_security.md",
    "contract_app_tariffs": "contract_appendices/app_tariffs.md",
}


def get_template_path(name: str) -> Path:
    """Возвращает путь к файлу шаблона по имени. None если не существует."""
    fname = TEMPLATE_FILES.get(name)
    if not fname:
        return None
    p = TEMPLATES_DIR / fname
    return p if p.exists() else None


def render_template(name_or_path, variables: dict):
    """
    Рендерит шаблон с подстановкой переменных.

    Args:
        name_or_path: имя шаблона ('invoice_email') или путь к файлу.
        variables: dict с переменными {invoice_number, amount, client_name, ...}

    Returns:
        (subject, body) — subject из frontmatter, body — текст после ---.
        Если frontmatter нет — subject='', body=весь файл.
    """
    # Определяем путь
    if name_or_path in TEMPLATE_FILES:
        tpl_path = get_template_path(name_or_path)
    else:
        tpl_path = Path(name_or_path)
        if not tpl_path.exists():
            return "", f"[шаблон не найден: {name_or_path}]"

    if not tpl_path:
        return "", f"[шаблон не найден: {name_or_path}]"

    content = tpl_path.read_text(encoding="utf-8")

    # Извлекаем frontmatter
    subject = ""
    body = content
    fm_match = re.match(r"^\s*---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        body = fm_match.group(2)
        # Ищем subject: в frontmatter
        subj_match = re.search(r"^subject:\s*(.+)$", fm, re.MULTILINE)
        if subj_match:
            subject = subj_match.group(1).strip().strip('"').strip("'")

    # Подстановка переменных {{var}}
    def replace_var(match):
        var = match.group(1).strip()
        val = variables.get(var, "")
        return str(val) if val is not None else ""

    subject = re.sub(r"\{\{(\w+)\}\}", replace_var, subject)
    body = re.sub(r"\{\{(\w+)\}\}", replace_var, body)

    return subject, body.strip()


def save_template(name: str, content: str) -> bool:
    """Сохраняет отредактированный шаблон в файл."""
    fname = TEMPLATE_FILES.get(name)
    if not fname:
        return False
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    (TEMPLATES_DIR / fname).write_text(content, encoding="utf-8")
    return True


def read_template_raw(name: str) -> str:
    """Возвращает сырое содержимое шаблона (для редактора)."""
    tpl_path = get_template_path(name)
    if not tpl_path:
        return ""
    return tpl_path.read_text(encoding="utf-8")
