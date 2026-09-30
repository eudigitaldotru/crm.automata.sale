
from sec_guard import guard_open
import os
import sys
import re
import yaml
import datetime
import argparse
import subprocess
import smtplib
from email.message import EmailMessage
from email.utils import formatdate
from dotenv import load_dotenv

# --- CONFIGURATION ---
BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(BASE_PATH, "10_Clients")
TEMPLATES_DIR = os.path.join(BASE_PATH, "90_Templates")
DOCUMENTS_DIR = os.path.join(BASE_PATH, "60_Documents")
CONTRACTS_DIR = os.path.join(DOCUMENTS_DIR, "Contracts")

# Ensure directories exist
if not os.path.exists(CONTRACTS_DIR):
    os.makedirs(CONTRACTS_DIR)

# Load environment variables
dotenv_path = os.path.join(BASE_PATH, ".env")
load_dotenv(dotenv_path)

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
SMTP_SERVER = "smtp.timeweb.ru"
SMTP_PORT = 465

HOURS_MAP = {
    1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять",
    6: "шесть", 7: "семь", 8: "восемь", 9: "девять", 10: "десять"
}

# Шаблон рамочного договора на сопровождение (редактируется в дашборде: «📝 Шаблоны»).
# Тело — разделы 1–12; приложения живут отдельно в contract_appendices/ и собираются
# генератором (автонумерация + список приложений в теле).
SUPPORT_CONTRACT_TEMPLATE = os.path.join(TEMPLATES_DIR, "tpl_contract_support.md")
APPENDICES_DIR = os.path.join(TEMPLATES_DIR, "contract_appendices")

# Реестр приложений: порядок = порядок нумерации в документе.
APPENDIX_REGISTRY = [
    {"id": "sla", "file": "app_sla.md",
     "title": "Регламент технического сопровождения (SLA)", "default": True},
    {"id": "tm", "file": "app_tm.md",
     "title": "Прейскурант почасовых ставок (Time & Materials)", "default": True},
    {"id": "act_form", "file": "app_act_form.md",
     "title": "Форма Акта сдачи-приёмки", "default": True},
    {"id": "nda", "file": "app_nda.md",
     "title": "Соглашение о конфиденциальности (NDA)", "default": True},
    {"id": "security", "file": "app_security.md",
     "title": "Регламент передачи доступов и информационной безопасности", "default": True},
    {"id": "tariffs", "file": "app_tariffs.md",
     "title": "Перечень услуг и тарифов", "default": True},
]


def get_appendix_registry():
    """Реестр приложений для дашборда (JSON-копия)."""
    return [dict(a) for a in APPENDIX_REGISTRY]


def load_appendices(selected_ids=None):
    """Загрузить выбранные приложения. None → все с default=True.
    Возвращает список (title, content) в порядке нумерации."""
    if selected_ids is None:
        chosen = [a for a in APPENDIX_REGISTRY if a.get("default")]
    else:
        known = {a["id"]: a for a in APPENDIX_REGISTRY}
        unknown = [i for i in selected_ids if i not in known]
        if unknown:
            raise ValueError("Неизвестные приложения договора: " + ", ".join(unknown))
        chosen = [known[i] for i in selected_ids]
    result = []
    for a in chosen:
        path = os.path.join(APPENDICES_DIR, a["file"])
        if not os.path.exists(path):
            raise FileNotFoundError(f"Файл приложения не найден: {path}")
        with guard_open(path, 'r', encoding='utf-8') as f:
            result.append((a["title"], f.read().strip()))
    return result


def load_contract_template(template_path=None):
    """Прочитать тело договора с {{плейсхолдерами}} (90_Templates/tpl_contract_support.md)."""
    path = template_path or SUPPORT_CONTRACT_TEMPLATE
    if not os.path.exists(path):
        raise FileNotFoundError(f"Шаблон договора не найден: {path}")
    with guard_open(path, 'r', encoding='utf-8') as f:
        return f.read()

# Маркеры реальных данных исторической базы (ПАРИТЕТ СТРОЙ). Если после подстановки
# они появились в тексте — шаблон протух/испорчен, генерация падает, а не выдаёт
# документ с чужими реквизитами.
PARANOID_MARKERS = [
    "ПАРИТЕТ", "Паритет", "Тарасенко", "1176451022758", "6452129988",
    "645201001", "vsepromangal64", "04052026", "Пугачева",
]

# Реквизиты Исполнителя для таблицы раздела 12
CONTRACTOR_BANK_DETAILS = ('ООО "БАНК ТОЧКА" г. Москва, БИК 044525104, '
                           'К/с 30101810745374525104, Р/с 40802810314500002795')


def substitute_placeholders(template, variables):
    """Подставить {{var}} и проверить, что чужих данных/дырок в тексте не осталось."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", str(value))

    leftover = sorted(set(re.findall(r"\{\{[^}]*\}\}", result)))
    if leftover:
        raise ValueError("В шаблоне договора остались незамещённые плейсхолдеры: "
                         + ", ".join(leftover)
                         + ". Проверьте шаблон или сообщите о новой переменной.")

    found = [m for m in PARANOID_MARKERS if m in result]
    if found:
        raise ValueError("ОБНАРУЖЕНЫ ДАННЫЕ СТАРОЙ БАЗЫ (ПАРИТЕТ) в договоре: "
                         + ", ".join(found)
                         + ". Генерация прервана — проверьте шаблон tpl_contract_support.md.")
    return result

PRICE_MAP = {
    3000: "три тысячи",
    4500: "четыре тысячи пятьсот",
    6000: "шесть тысяч",
    9000: "девять тысяч",
    12000: "двенадцать тысяч",
    15000: "пятнадцать тысяч",
    18000: "восемнадцать тысяч",
    20000: "двадцать тысяч",
    30000: "тридцать тысяч",
    50000: "пятьдесят тысяч",
    250000: "двести пятьдесят тысяч",
}

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

def parse_frontmatter(file_path):
    with guard_open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if match:
        meta = yaml.safe_load(match.group(1))
        body = content[match.end():]
        return meta, body
    return {}, content

def declense_director_genitive(name):
    if not name:
        return "_________________"
    parts = name.strip().split()
    res_parts = []
    for part in parts:
        part_lower = part.lower()
        if part_lower.endswith("а") and not part_lower.endswith("ова") and not part_lower.endswith("ева") and not part_lower.endswith("ина"):
            # e.g. Ильмира -> Ильмиры
            res_parts.append(part[:-1] + "ы")
        elif part_lower.endswith("ова") or part_lower.endswith("ева") or part_lower.endswith("ина") or part_lower.endswith("ая"):
            if part_lower.endswith("ая"):
                # e.g. Красная -> Красной
                res_parts.append(part[:-2] + "кой" if part_lower.endswith("кая") else part[:-2] + "ой")
            else:
                # e.g. Замалиева -> Замалиевой, Смирнова -> Смирновой
                res_parts.append(part[:-1] + "ой")
        elif part_lower.endswith("ей"):
            # e.g. Алексей -> Алексея, Андрей -> Андрея
            res_parts.append(part[:-2] + "ея")
        elif part_lower.endswith("ий") or part_lower.endswith("ый"):
            # e.g. Евгений -> Евгения, Дмитрий -> Дмитрия
            if part_lower.endswith("ий"):
                res_parts.append(part[:-2] + "ия")
            else:
                res_parts.append(part[:-2] + "ого")
        elif part_lower.endswith("ич") or part_lower.endswith("ов") or part_lower.endswith("ев") or part_lower.endswith("ин"):
            # e.g. Александрович -> Александровича, Иванов -> Иванова
            res_parts.append(part + "а")
        elif part_lower.endswith("я") and part_lower.endswith("ья"):
            # e.g. Илья -> Ильи
            res_parts.append(part[:-1] + "и")
        elif part_lower.endswith("я"):
            # e.g. Мария -> Марии
            res_parts.append(part[:-1] + "и")
        elif part_lower.endswith("ь"):
            # e.g. Игорь -> Игоря, Любовь -> Любови
            if part_lower == "любовь":
                res_parts.append("Любови")
            else:
                res_parts.append(part[:-1] + "я")
        else:
            res_parts.append(part)
    return " ".join(res_parts)

def declense_position_genitive(pos):
    if not pos:
        return "Директора"
    pos = pos.strip()
    pos_lower = pos.lower()
    if pos_lower == "директор":
        return "Директора"
    elif pos_lower == "генеральный директор":
        return "Генерального директора"
    elif pos_lower == "индивидуальный предприниматель":
        return "Индивидуального предпринимателя"
    parts = pos.split()
    res = []
    for part in parts:
        p_lower = part.lower()
        if p_lower.endswith("ый"):
            res.append(part[:-2] + "ого")
        elif p_lower.endswith("ий"):
            res.append(part[:-2] + "его")
        elif p_lower.endswith("ор") or p_lower.endswith("ель") or p_lower.endswith("ент") or p_lower.endswith("арь"):
            res.append(part + "а")
        else:
            res.append(part)
    return " ".join(res)

def guess_gender(name):
    if not name:
        return "male"
    parts = name.strip().split()
    if len(parts) >= 2:
        first_name = parts[1].lower()
        last_name = parts[0].lower()
        if first_name.endswith("а") or first_name.endswith("я") or first_name.endswith("и") or last_name.endswith("ва") or last_name.endswith("на"):
            return "female"
    return "male"

def get_hours_declension(n):
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    elif n % 10 in [2, 3, 4] and n % 100 not in [12, 13, 14]:
        return "часа"
    else:
        return "часов"

def send_contract_email(to_email, client_name, file_path):
    if not EMAIL_USER or not EMAIL_PASS:
        print("❌ Error: EMAIL_USER or EMAIL_PASS not found in .env file.")
        return False
        
    msg = EmailMessage()
    msg['Subject'] = f"Договор на сопровождение сайта — {client_name}"
    msg['From'] = EMAIL_USER
    msg['To'] = to_email
    msg['Date'] = formatdate(localtime=True)
    
    body = (f"Здравствуйте!\n\n"
            f"Направляем Вам проект договора на сопровождение сайта в соответствии с нашими договорённостями.\n\n"
            f"Документ во вложении.\n\n"
            f"С уважением,\nКоманда Automata CRM")
    
    msg.set_content(body)
    
    if os.path.exists(file_path):
        filename = os.path.basename(file_path)
        try:
            with guard_open(file_path, 'rb') as f:
                file_data = f.read()
            import mimetypes
            ctype, encoding = mimetypes.guess_type(file_path)
            if ctype is None or encoding is not None:
                ctype = 'application/octet-stream'
            maintype, subtype = ctype.split('/', 1)
            
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=filename)
            print(f"📎 Attached: {filename} as {ctype}")
        except Exception as e:
            print(f"❌ Failed to attach {file_path}: {e}")
            return False

    try:
        print(f"Connecting to {SMTP_SERVER}...")
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print(f"✅ Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

def generate_framework_contract(client_file, doc_number=None, send=False,
                                template_path=None, appendices=None):
    if not os.path.exists(client_file):
        print(f"❌ Client file not found: {client_file}")
        return

    meta, content = parse_frontmatter(client_file)
    client_name = os.path.basename(client_file).replace(".md", "")

    # Шаблон договора (по умолчанию 90_Templates/tpl_contract_support.md)
    template = load_contract_template(template_path)

    # Formulate date & number
    today = datetime.date.today()
    if not doc_number:
        doc_number = today.strftime("%d%m%Y") + "-1"
        
    doc_day = str(today.day).zfill(2)
    doc_month_text = MONTHS_RU.get(today.month, "июня")
    doc_year = str(today.year)
    
    # Client metadata variables
    company_name = meta.get('company_short_name') or meta.get('company_name') or client_name
    if not company_name.startswith("ООО") and not company_name.startswith("ИП") and not company_name.startswith("АО"):
        # Default to ООО if not specified
        company_full_name = f"ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ \"{company_name}\" (ООО \"{company_name}\")"
    else:
        company_full_name = company_name

    inn = str(meta.get('inn', '_________________'))
    kpp = str(meta.get('kpp', '_________________'))
    ogrn = str(meta.get('ogrn', '_________________'))
    legal_address = str(meta.get('legal_address', '_________________'))
    email = str(meta.get('email', '_________________'))
    phone = str(meta.get('phone', '_________________'))
    director_name = meta.get('director_name') or meta.get('director') or '_________________'
    director_pos = meta.get('director_pos', 'Директор')

    # Банковские реквизиты Заказчика одной строкой (раздел 12, {{client_bank_details}})
    if meta.get('bank_account'):
        client_bank_details = (
            f"{meta.get('bank_name', '')}, БИК {meta.get('bank_bik', '')}, "
            f"К/с {meta.get('bank_corr_account', '')}, Р/с {meta.get('bank_account', '')}"
        ).strip()
    else:
        client_bank_details = "_______________ (заполнить при подписании)"
    
    director_genitive = declense_director_genitive(director_name)
    gender = guess_gender(director_name)
    gender_action = "действующей" if gender == "female" else "действующего"
    # «в лице Директора Иванова Ивана Ивановича, действующего на основании Устава»
    director_phrase = f"{declense_position_genitive(director_pos)} {director_genitive}, {gender_action}"

    # Support settings
    incl_hours = meta.get('included_hours', 5)
    incl_hours_text = HOURS_MAP.get(incl_hours, str(incl_hours))
    hours_phrase = f"{incl_hours} ({incl_hours_text}) {get_hours_declension(incl_hours)}"
    
    rate = meta.get('rate', 3000)
    rate_text = PRICE_MAP.get(rate, str(rate))
    rate_phrase = f"{rate} ({rate_text})"
    
    monthly_fee = meta.get('monthly_retainer_fee', 15000)
    fee_text = PRICE_MAP.get(monthly_fee, str(monthly_fee))
    fee_phrase = f"{monthly_fee} ({fee_text})"
    
    tariff_name = meta.get('tariff', 'Поддержка 5 часов')

    # Переменные шаблона (90_Templates/tpl_contract_support.md использует {{...}})
    variables = {
        "contract_number": doc_number,
        "contract_date": f"«{doc_day}» {doc_month_text} {doc_year} г.",
        "company_full_name": company_full_name,
        "ogrn": ogrn,
        "inn": inn,
        "kpp": kpp,
        "legal_address": legal_address,
        "email": email,
        "phone": phone,
        "director_phrase": director_phrase,
        "client_bank_details": client_bank_details,
        "contractor_bank_details": CONTRACTOR_BANK_DETAILS,
        # Гранулярные переменные тарифа (приложение «Перечень услуг и тарифов»)
        "tariff_name": tariff_name,
        "hours_phrase": hours_phrase,
        "fee_phrase": fee_phrase,
        "rate_phrase": rate_phrase,
        # 3.1–3.4 тарифного приложения; заголовки 3 и 3.5 — статика в шаблоне
        "tariff_section": (
            f"3.1. Заказчик выбрал тарифный план: **{tariff_name}**.\n"
            f"3.2. Лимит включённого времени: **{hours_phrase} в месяц**.\n"
            f"3.3. Стоимость абонентского обслуживания: **{fee_phrase} рублей в месяц**, НДС не облагается.\n"
            f"3.4. Стоимость превышения лимита (почасовая ставка T&M): **{rate_phrase} рублей в час**, НДС не облагается."
        ),
    }

    # Сборка документа: тело + выбранные приложения.
    # Нумерация приложений и их список в теле строятся автоматически.
    appendix_data = load_appendices(appendices)
    parts = [template.rstrip() + "\n"]
    if appendix_data:
        list_lines = [f"- **Приложение № {i}** — {title}."
                      for i, (title, _) in enumerate(appendix_data, 1)]
        blocks = [f"### Приложение № {i}. {title}\n{content}"
                  for i, (title, content) in enumerate(appendix_data, 1)]
        parts.append("### ПРИЛОЖЕНИЯ К ДОГОВОРУ:\n" + "\n".join(list_lines)
                     + "\n\n---\n\n\n" + "\n\n\n---\n\n\n".join(blocks))
    raw = "\n\n".join(parts)
    result = substitute_placeholders(raw, variables)

    # Output file path; при коллизии — суффикс _v2, _v3 (как «…ВАЙН ГУРМЭ_v2.md»)
    clean_company_name = company_name.replace('"', '').replace("'", "")
    output_filename = f"Договор на сопровождение — {clean_company_name}.md"
    stem = output_filename[:-3]
    output_path = os.path.join(CONTRACTS_DIR, output_filename)
    version = 2
    while os.path.exists(output_path):
        output_path = os.path.join(CONTRACTS_DIR, f"{stem}_v{version}.md")
        version += 1
    
    with guard_open(output_path, 'w', encoding='utf-8') as f:
        f.write(result.rstrip() + "\n")
        
    print(f"✅ Contract generated successfully: {output_path}")
    
    if send:
        client_email = meta.get('email')
        if client_email:
            send_contract_email(client_email, company_name, output_path)
        else:
            print("⚠️ Cannot send email: client email not found in metadata.")
            
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Framework contract for client")
    parser.add_argument("client_file", help="Path to client .md file")
    parser.add_argument("--number", help="Contract number")
    parser.add_argument("--template", help="Path to contract template .md (по умолчанию 90_Templates/tpl_contract_support.md)")
    parser.add_argument("--appendices", help="Comma-separated appendix ids (по умолчанию — все с default=True). Список: --appendices-list")
    parser.add_argument("--appendices-list", action="store_true", help="Показать реестр приложений")
    parser.add_argument("--send", action="store_true", help="Send the contract via email")
    args = parser.parse_args()

    if args.appendices_list:
        for a in APPENDIX_REGISTRY:
            print(f"{a['id']}: {a['title']} (default={a['default']})")
        sys.exit(0)

    selected = [s.strip() for s in args.appendices.split(",") if s.strip()] if args.appendices else None

    client_path = args.client_file
    if not os.path.isabs(client_path):
        client_path = os.path.join(CLIENTS_DIR, client_path)
    # «Медгард» → 10_Clients/Медгард.md
    if not os.path.exists(client_path) and not client_path.endswith(".md"):
        client_path += ".md"

    try:
        generate_framework_contract(client_path, args.number, args.send, args.template,
                                    appendices=selected)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f"❌ {e}")
