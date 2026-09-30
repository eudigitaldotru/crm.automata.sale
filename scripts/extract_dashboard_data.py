#!/usr/bin/env python3
"""
extract_dashboard_data.py
Extracts all CRM data from Obsidian Vault frontmatter and generates
a unified data.json for the browser dashboard.

Usage:
    python scripts/extract_dashboard_data.py
Outputs:
    dashboard/data/data.json
"""

import os
import re
import json
import yaml
from datetime import datetime, date, timedelta
from collections import defaultdict
from database import get_personal_expenses

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
VAULT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(BASE_DIR, "dashboard", "public", "data", "data.json")

DIR_CLIENTS       = os.path.join(VAULT_DIR, "10_Clients")
DIR_INBOX         = os.path.join(BASE_DIR, "20_Inbox")
DIR_INVOICES      = os.path.join(VAULT_DIR, "30_Invoices")
DIR_DEALS         = os.path.join(VAULT_DIR, "30_Deals")
DIR_ACTS          = os.path.join(BASE_DIR, "35_Acts")
DIR_INFRA         = os.path.join(BASE_DIR, "40_Infrastructure")
DIR_TICKETS       = os.path.join(VAULT_DIR, "45_Tickets")
DIR_CREDITS       = os.path.join(BASE_DIR, "50_Credits")
DIR_PRODUCTS      = os.path.join(BASE_DIR, "70_Products")
DIR_GITACTIVE     = os.path.join(os.path.dirname(BASE_DIR), "GITACTIVE")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def parse_frontmatter(filepath):
    """Parse YAML frontmatter from a markdown file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
        if match:
            meta = yaml.safe_load(match.group(1)) or {}
            return meta, content
    except Exception as e:
        print(f"  ⚠️  Error parsing {filepath}: {e}")
    return {}, ""


def load_dir(directory, filter_tag=None):
    """Load all .md files from a directory, returning list of (meta, filename)."""
    results = []
    if not os.path.isdir(directory):
        return results
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".md") or "sync-conflict" in fname:
            continue
        meta, content = parse_frontmatter(os.path.join(directory, fname))
        tags = meta.get("tags", []) or []
        if isinstance(tags, str):
            tags = [tags]
        if filter_tag and filter_tag not in tags:
            continue
        meta["_filename"] = fname.replace(".md", "")
        meta["_content"] = content
        results.append(meta)
    return results


def safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def safe_date(v):
    """Convert various date formats to 'YYYY-MM-DD' string, or None."""
    if not v:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def month_key(date_str):
    """Extract 'YYYY-MM' from a date string."""
    if date_str:
        return date_str[:7]
    return None


def get_tag(meta, tag):
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return tag in tags


def extract_gitactive_tasks():
    """Extract tasks from all files in 30_Tasks directory."""
    projects_tasks = []
    tasks_dir = os.path.join(BASE_DIR, "30_Tasks")
    if not os.path.isdir(tasks_dir):
        return projects_tasks
        
    for fname in sorted(os.listdir(tasks_dir)):
        if not fname.endswith(".md") or "sync-conflict" in fname or fname == "README.md":
            continue
            
        filepath = os.path.join(tasks_dir, fname)
        try:
            meta, content = parse_frontmatter(filepath)
            if meta.get("type") not in ("task", "dev_task", "meeting", "family"):
                continue
                
            status = str(meta.get("status", "todo")).lower()
            
            # Clean client / project name
            client_raw = meta.get("client", "")
            if isinstance(client_raw, str):
                client_name = client_raw.replace("[[", "").replace("]]", "").strip()
            else:
                client_name = ""
                
            project_raw = meta.get("project", "")
            if isinstance(project_raw, str) and project_raw:
                project_name = project_raw.replace("[[", "").replace("]]", "").strip()
            else:
                project_name = client_name
                
            # Clean title
            title = fname.replace(".md", "")
            # We can read the first header # title or default to clean filename.
            header_match = re.search(r'^#\s+(.*?)$', content, re.MULTILINE)
            if header_match:
                title = header_match.group(1).strip()
            else:
                title = re.sub(r'^\d{4}-\d{2}-\d{2}_', '', title).replace('_', ' ')
                
            tags = meta.get("tags", []) or []
            if isinstance(tags, str):
                tags = [tags]
            tags = [t.strip().lower() for t in tags]
            
            is_done = (status == "done") or bool(meta.get("invoice")) or bool(meta.get("date_completed"))
            
            projects_tasks.append({
                "id":      fname.replace(".md", ""),
                "project": project_name or "General",
                "client":  client_name,
                "title":   title,
                "done":    is_done,
                "type":    str(meta.get("type", "task")),
                "date":    str(meta.get("date", "") or ""),
                "urgent":  "urgent" in tags,
                "important": "important" in tags or project_name == "Мягкая кровля" or client_name == "Мягкая кровля"
            })
        except Exception as e:
            print(f"  ⚠️  Error parsing task file {fname}: {e}")
            
    return projects_tasks


def build_eisenhower_matrix(tasks):
    """Categorize tasks into 4 Eisenhower quadrants."""
    matrix = {
        "q1": [], # Urgent & Important
        "q2": [], # Important (Not Urgent)
        "q3": [], # Urgent (Not Important)
        "q4": []  # Neither
    }
    
    # Only include active (not done) tasks for the matrix
    for t in tasks:
        if t["done"]:
            continue
            
        if t["urgent"] and t["important"]:
            matrix["q1"].append(t)
        elif t["important"]:
            matrix["q2"].append(t)
        elif t["urgent"]:
            matrix["q3"].append(t)
        else:
            matrix["q4"].append(t)
            
    return matrix


# ─────────────────────────────────────────────
# Data Extraction
# ─────────────────────────────────────────────
def extract_clients():
    clients = []
    raw = load_dir(DIR_CLIENTS)
    
    # Calculate hours used per client from 30_Tasks/ for the current month
    hours_used_map = defaultdict(float)
    tasks_dir = os.path.join(BASE_DIR, "30_Tasks")
    if os.path.isdir(tasks_dir):
        today = date.today()
        current_month_prefix = f"{today.year}-{today.month:02d}"
        for fname in os.listdir(tasks_dir):
            if not fname.endswith(".md") or "sync-conflict" in fname or fname == "README.md":
                continue
            filepath = os.path.join(tasks_dir, fname)
            try:
                tf_meta, _ = parse_frontmatter(filepath)
                if tf_meta.get("type") not in ("task", "dev_task"):
                    continue
                status = str(tf_meta.get("status", "todo")).lower()
                comp_date = str(tf_meta.get("date_completed") or "")
                if status in ("done", "completed") and comp_date.startswith(current_month_prefix):
                    client_raw = tf_meta.get("client", "")
                    if isinstance(client_raw, str):
                        c_name = client_raw.replace("[[", "").replace("]]", "").strip()
                        if c_name:
                            hours_used_map[c_name] += safe_float(tf_meta.get("hours", 0))
            except Exception:
                pass

    for m in raw:
        # Skip churned or contacts
        if m.get("lifecycle") in ("churned", "archive") or not m.get("lifecycle"):
            continue
        tags = m.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]

        # Calculate monthly retainer fee based on plan.
        # Универсальная ставка: 3000 ₽/час (rate по умолчанию). Любой тариф
        # support_Xh корректно посчитается — и support_5h (15000), и будущие.
        # Явный словарь остаётся для обратной совместимости/возможных скидок.
        plan_prices = {
            "support_1h": 3000,
            "support_2h": 6000,
            "support_3h": 9000,
            "support_5h": 15000,
            "support_9h": 27000,
        }
        support_plan = m.get("support_plan", "")
        support_type = m.get("support_type", "none")
        fee = plan_prices.get(support_plan, 0) if support_type == "retainer" else 0
        # Явная абонплата из карточки — приоритет (публичная линейка сайта:
        # цена за сервис, не «часы × 3000»; так же считает auto_invoice_monthly)
        card_fee = safe_float(m.get("monthly_retainer_fee"))
        if support_type == "retainer" and card_fee > 0:
            fee = card_fee
        # Fallback: если тариф не в словаре, посчитаем по часам (3000 ₽/ч)
        if not fee and support_type == "retainer":
            _h = re.match(r"support_(\d+)h", support_plan or "")
            if _h:
                fee = int(_h.group(1)) * 3000

        client_short_name = m.get("company_short_name") or m["_filename"]
        # Match client name by filename (with or without extension), short name or company_name
        c_hours = hours_used_map[m["_filename"].replace(".md", "")] or hours_used_map[client_short_name] or hours_used_map[m.get("company_name", "")]

        client = {
            "id":                  m["_filename"],
            "name":                client_short_name,
            "lifecycle":           m.get("lifecycle", "unknown"),
            "support_type":        support_type,
            "support_plan":        support_plan,
            "hours_used_current_month": c_hours,
            "rate":                safe_float(m.get("rate")),
            "monthly_retainer_fee": fee,
            "total_revenue":       safe_float(m.get("total_revenue")),
            "inn":                 str(m.get("inn", "")),
            "email":               m.get("email", ""),
            "telegram":            m.get("telegram", ""),
            "source":              m.get("source", "unknown"),
            "lead_status":         m.get("status", "unknown") if m.get("lifecycle") == "prospect" else None,
            "created_at":          m.get("created", ""),
            "last_contact_at":     m.get("last_contact_at", ""),
            "tags":                tags,
            "has_support":         support_type == "retainer",
            "has_license":         support_type == "license" or "license" in tags,
        }
        clients.append(client)
    return clients

def attach_contracts(clients):
    """Прикрепить к каждому клиенту договоры из 60_Documents/Contracts/.
    Договор сопоставляется клиенту, если имя файла клиента (id) или company_name
    входит в имя файла договора. Расширения: md (карточка), txt, pdf (скан)."""
    cdir = os.path.join(VAULT_DIR, "60_Documents", "Contracts")
    files = []
    if os.path.isdir(cdir):
        for fname in sorted(os.listdir(cdir)):
            if fname.startswith((".", "~")):
                continue
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in ("md", "txt", "pdf"):
                files.append((fname, ext))
    for c in clients:
        names = {str(c.get("id") or "").lower(), str(c.get("name") or "").lower()}
        names.discard("")
        c["contracts"] = [
            {"file": fname, "ext": ext}
            for fname, ext in files
            if any(n in fname.lower() for n in names)
        ]
    return clients


def extract_deals():
    deals = []
    if not os.path.exists(DIR_DEALS):
        return deals
        
    raw = load_dir(DIR_DEALS)
    for m in raw:
        deal = {
            "id": m["_filename"],
            "title": m.get("title", m["_filename"]),
            "status": m.get("status", "new"),
            "expected_revenue": safe_float(m.get("expected_revenue")),
            "client": m.get("client", ""),
            "created": m.get("created", "")
        }
        deals.append(deal)
    return deals

def extract_invoices():
    invoices = []
    raw = load_dir(DIR_INVOICES)
    for m in raw:
        tags = m.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        client_raw = m.get("client", "")
        if isinstance(client_raw, str):
            client_name = client_raw.replace("[[", "").replace("]]", "").strip()
        else:
            client_name = str(client_raw)

        act_checked = m.get("act_status") in ("paid", "signed")
        invoice_pdf = m.get("invoice_pdf")
        act_pdf = m.get("act_pdf")
        edo_status = "edo" in tags or m.get("edo_status") in ("sent", "signed", "true", True)

        # Fallback for old invoices that don't have tabular properties yet
        if m.get("_content"):
            content_str = m["_content"]
            if not act_checked and re.search(r'-\s*\[x\]\s*Акт выполненных работ', content_str, re.IGNORECASE):
                act_checked = True
                
            if not edo_status and re.search(r'-\s*\[x\]\s*Подписанные документы', content_str, re.IGNORECASE):
                edo_status = True
                
            inv_match = re.search(r'(Invoice_[A-Za-z0-9\-]+\.pdf)', content_str)
            if inv_match and not invoice_pdf:
                invoice_pdf = inv_match.group(1)
                
            act_match = re.search(r'(Act_[A-Za-z0-9\-]+\.pdf)', content_str)
            if act_match and not act_pdf:
                act_pdf = act_match.group(1)

        inv = {
            "id":             m["_filename"],
            "number":         m.get("invoice_number", ""),
            "client":         client_name,
            "amount":         safe_float(m.get("amount")),
            "status":         m.get("status", "unknown"),
            "invoice_date":   safe_date(m.get("invoice_date")),
            "payment_date":   safe_date(m.get("payment_date")),
            "period":         m.get("period", ""),
            "tags":           tags,
            "sent":           "sent" in tags or "unpaid_invoice" in tags,
            "sent_count":     int(m.get("sent_count", 1 if "sent" in tags else 0)),
            "act_status":     "paid" if act_checked else "unpaid",
            "invoice_pdf":    invoice_pdf,
            "act_pdf":        act_pdf,
            "owner_signed":   m.get("owner_signed"),  # страж актов: false = ждёт подписи в Точке
            "edo_status":     edo_status,
            "items":          m.get("items", []),
            "email_status":   m.get("email_status", "unknown"),
            "email_body":     m.get("email_body_preview", "")
        }
        invoices.append(inv)
    return invoices


def extract_infrastructure():
    items = []
    raw = load_dir(DIR_INFRA)
    for m in raw:
        client_raw = m.get("client", "")
        if isinstance(client_raw, str):
            client_name = client_raw.replace("[[", "").replace("]]", "").strip()
        else:
            client_name = str(client_raw)
        items.append({
            "id":           m["_filename"],
            "client":       client_name,
            "service_type": m.get("service_type", ""),
            "provider":     m.get("provider", ""),
            "amount":       safe_float(m.get("amount")),
            "renewal_date": safe_date(m.get("renewal_date")),
            "status":       m.get("status", ""),
            "agency_fee_percent": safe_float(m.get("agency_fee_percent", 0)),
        })
    return items


def extract_credits():
    credits = []
    raw = load_dir(DIR_CREDITS)
    for m in raw:
        if m.get("status") == "closed":
            continue
        credits.append({
            "id":              m["_filename"],
            "bank":            m.get("bank", "—"),
            "loan_type":       m.get("loan_type", ""),
            "amount":          safe_float(m.get("amount")),
            "rate":            safe_float(m.get("rate")),
            "monthly_payment": safe_float(m.get("monthly_payment")),
            "remaining":       safe_float(m.get("remaining")),
            "start_date":      safe_date(m.get("start_date")),
            "end_date":        safe_date(m.get("end_date")),
            "status":          m.get("status", "active"),
            "purpose":         m.get("purpose", ""),
        })
    return credits


def extract_inbox():
    """Count messages per source for communications panel."""
    items = []
    raw = load_dir(DIR_INBOX)
    for m in raw:
        if not m.get("_filename") or m["_filename"] in ("Inbox", "Inbox.md"):
            continue
        items.append({
            "source":   m.get("source", "unknown"),
            "client":   m.get("client", ""),
            "sender":   m.get("sender", ""),
            "received": safe_date(m.get("date") or m.get("created")),
        })
    return items

def extract_leads():
    """Извлекает лиды из 15_Leads/ (входящие от новых контактов: TG-gateway и др.)."""
    leads = []
    leads_dir = os.path.join(VAULT_DIR, "15_Leads")
    if not os.path.exists(leads_dir):
        return leads
    raw = load_dir(leads_dir)
    for m in raw:
        fname = m.get("_filename", "")
        # Пропускаем служебные/шаблонные файлы
        if not fname or fname.startswith("_") or fname in ("Leads", "Leads.md"):
            continue
        # Технические уведомления мониторинга — не лиды (исключены владельцем 14.09.2026)
        if "scan_alert_2bldesk" in fname.lower() or "scan_alert_2bldesk" in str(m.get("name") or "").lower():
            continue
        # Тело сообщения — текст после frontmatter (первая непустая строка после "---")
        body = ""
        if m.get("_content"):
            content = m["_content"]
            # Снимаем заголовок "# Лид: ..." — берём содержимое после него
            parts = re.split(r"^#.*$", content, flags=re.MULTILINE)
            body = (parts[1].strip() if len(parts) > 1 else content).strip()[:200]
        leads.append({
            "id":         fname,
            "name":       m.get("name") or m.get("_filename"),
            "source":     m.get("source", "unknown"),
            "status":     m.get("status", "new"),
            "telegram":   str(m.get("telegram") or m.get("tg_username") or "").lstrip("@"),
            "phone":      str(m.get("phone") or ""),
            "email":      m.get("email", ""),
            "created":    safe_date(m.get("created")),
            "message":    body,
        })
    # Сортировка: новые сверху
    leads.sort(key=lambda x: x.get("created") or "", reverse=True)
    return leads

def extract_tickets():
    tickets = []
    if not os.path.exists(DIR_TICKETS):
        return tickets
        
    raw = load_dir(DIR_TICKETS)
    now = datetime.now()
    for m in raw:
        client_raw = m.get("client", "")
        if isinstance(client_raw, str):
            client_name = client_raw.replace("[[", "").replace("]]", "").strip()
        else:
            client_name = str(client_raw)
            
        status = m.get("status", "open")
        sla_deadline_str = m.get("sla_deadline", "")
        hours_remaining = None
        
        if sla_deadline_str and status == "open":
            try:
                # Handle ISO format from our tg_listener
                deadline = datetime.fromisoformat(sla_deadline_str.replace("Z", ""))
                hours_remaining = (deadline - now).total_seconds() / 3600
            except Exception as e:
                pass
                
        tickets.append({
            "id": m["_filename"],
            "ticket_id": m.get("id", m["_filename"]),
            "client": client_name,
            "title": m.get("title", "Без названия"),
            "status": status,
            "priority": m.get("priority", "normal"),
            "created": m.get("created", ""),
            "sla_deadline": sla_deadline_str,
            "hours_remaining": round(hours_remaining, 1) if hours_remaining is not None else None,
            "alert_sent": m.get("alert_sent", False)
        })
    return tickets


# ─────────────────────────────────────────────
# Metric Computation
# ─────────────────────────────────────────────
def compute_metrics(clients, invoices, credits, infra):
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    this_month = today.strftime("%Y-%m")

    # MRR
    mrr = sum(c["monthly_retainer_fee"] for c in clients)

    # Revenue by month (paid invoices)
    revenue_by_month = defaultdict(float)
    issued_by_month  = defaultdict(float)
    for inv in invoices:
        mk = month_key(inv["invoice_date"])
        if not mk:
            continue
        issued_by_month[mk] += inv["amount"]
        if inv["status"] == "paid":
            pay_mk = month_key(inv["payment_date"]) or mk
            revenue_by_month[pay_mk] += inv["amount"]

    # Build last-12-months series
    months_series = []
    for i in range(11, -1, -1):
        d = date(today.year, today.month, 1) - timedelta(days=i * 30)
        mk = d.strftime("%Y-%m")
        months_series.append({
            "month":   mk,
            "paid":    round(revenue_by_month.get(mk, 0), 2),
            "issued":  round(issued_by_month.get(mk, 0), 2),
        })

    # Current month metrics
    revenue_this_month = revenue_by_month.get(this_month, 0)

    # Кто оплатил в этом месяце (раскрывашка KPI «Выручка за месяц», владелец 14.09.2026)
    paid_this_month = []
    for inv in invoices:
        if inv["status"] != "paid":
            continue
        pay_mk = month_key(inv["payment_date"]) or month_key(inv["invoice_date"])
        if pay_mk != this_month:
            continue
        paid_this_month.append({
            "client":       inv["client"],
            "amount":       inv["amount"],
            "number":       inv["number"],
            "payment_date": inv["payment_date"] or inv["invoice_date"],
        })
    paid_this_month.sort(key=lambda x: x["amount"], reverse=True)

    # Unpaid invoices. Счёт «ждёт оплаты» не только при status: unpaid —
    # счёт, отправленный через Точку, получает status: sent и иначе
    # выпадал из таблицы (кейс ЭЛМОН B24-9345, 23.09.2026).
    # Набор синхронен с reconcile_payments.py и api_server.py.
    AWAITING_PAYMENT = ("unpaid", "sent", "pending", "awaiting_payment")
    unpaid = [i for i in invoices if i["status"] in AWAITING_PAYMENT]
    total_debt = sum(i["amount"] for i in unpaid)
    overdue = [i for i in unpaid if i["invoice_date"] and i["invoice_date"] < (today - timedelta(days=14)).strftime("%Y-%m-%d")]

    # Credit load
    total_credit_remaining = sum(c["remaining"] for c in credits)
    total_monthly_payments = sum(c["monthly_payment"] for c in credits)
    credit_to_mrr_ratio = (total_monthly_payments / mrr * 100) if mrr > 0 else 0

    # Upcoming renewals (30 days)
    upcoming_renewals = [
        i for i in infra
        if i["renewal_date"] and today_str <= i["renewal_date"] <= (today + timedelta(days=30)).strftime("%Y-%m-%d")
    ]

    # Revenue forecast (next 6 months, base = MRR)
    forecast = []
    for i in range(1, 7):
        d = today.month + i
        y = today.year + (d - 1) // 12
        m = ((d - 1) % 12) + 1
        mk = f"{y}-{m:02d}"
        # Add infrastructure renewal income for that month
        renewal_income = sum(
            itm["amount"] for itm in infra
            if itm.get("renewal_date") and itm["renewal_date"][:7] == mk
               and itm.get("agency_fee_percent", 0) > 0
        )
        base = mrr + renewal_income
        forecast.append({
            "month":       mk,
            "base":        round(base, 2),
            "optimistic":  round(base * 1.2, 2),
            "pessimistic": round(base * 0.9, 2),
        })

    # Clients by support plan
    support_plan_counts = defaultdict(int)
    for c in clients:
        if c["support_type"] == "retainer":
            support_plan_counts[c["support_plan"]] += 1

    # Top clients by revenue (from invoices)
    client_revenue = defaultdict(float)
    for inv in invoices:
        if inv["status"] == "paid":
            c_name = inv["client"].replace("[[", "").replace("]]", "")
            client_revenue[c_name] += inv["amount"]
    top_clients = sorted(client_revenue.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Lead metrics
    leads = [c for c in clients if c["lifecycle"] == "prospect"]
    lead_sources = defaultdict(int)
    lead_funnel = {"new": 0, "contacted": 0, "qualified": 0, "lost": 0}
    unanswered_leads = []
    now = datetime.now()
    
    for l in leads:
        lead_sources[l["source"]] += 1
        st = l["lead_status"]
        if st in lead_funnel:
            lead_funnel[st] += 1
            
        if st == "new":
            # calculate hours since creation
            try:
                cat_val = l["created_at"]
                if isinstance(cat_val, str):
                    cat = datetime.strptime(cat_val[:10], "%Y-%m-%d")
                elif isinstance(cat_val, datetime):
                    cat = cat_val
                else: # date
                    cat = datetime.combine(cat_val, datetime.min.time())
                    
                hours = (now - cat).total_seconds() / 3600
                if hours > 4:
                    unanswered_leads.append({
                        "id": l["id"],
                        "name": l["name"],
                        "source": l["source"],
                        "hours": round(hours, 1)
                    })
            except:
                pass
                
    # Deals pipeline
    deals = extract_deals()
    pipeline = {"presentation": [], "negotiation": [], "won": [], "lost": []}
    for d in deals:
        st = d["status"]
        if st in pipeline:
            pipeline[st].append(d)

    all_tasks = extract_gitactive_tasks()

    return {
        "generated_at":           datetime.now().isoformat(),
        "today":                  today_str,
        "this_month":             this_month,
        "mrr":                    round(mrr, 2),
        "revenue_this_month":     round(revenue_this_month, 2),
        "paid_this_month":        paid_this_month,
        "total_debt":             round(total_debt, 2),
        "overdue_count":          len(overdue),
        "active_clients_count":   len(clients),
        "support_clients_count":  sum(1 for c in clients if c["has_support"]),
        "revenue_monthly_series": months_series,
        "unpaid_invoices":        unpaid,
        "upcoming_renewals":      upcoming_renewals,
        "forecast":               forecast,
        "support_plan_distribution": dict(support_plan_counts),
        "lead_sources":           dict(lead_sources),
        "lead_funnel":            lead_funnel,
        "unanswered_leads":       unanswered_leads,
        "pipeline":               pipeline,
        "tickets":                extract_tickets(),
        "top_clients_revenue":    [{"client": k, "revenue": round(v, 2)} for k, v in top_clients],
        "credit_summary": {
            "total_remaining":     round(total_credit_remaining, 2),
            "total_monthly":       round(total_monthly_payments, 2),
            "credit_to_mrr_ratio": round(credit_to_mrr_ratio, 1),
        },
        "support_matrix":      build_support_matrix(clients, invoices),
        "not_regular_matrix":  build_not_regular_matrix(clients, invoices),
        "tasks_matrix":        build_eisenhower_matrix(all_tasks)
    }

def build_support_matrix(clients, invoices):
    """Build a matrix of client vs month for support payments."""
    support_clients = [c for c in clients if c.get("has_support")]
    matrix = {}
    
    # We'll cover the current year
    year = date.today().year
    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    
    for client in support_clients:
        client_id = client["id"]
        matrix[client_id] = {
            "name": client["name"],
            "months": {}
        }
        
        for m_key in months:
            # Find all invoices for this client and month
            matches = []
            for inv in invoices:
                if "not_regular" in inv.get("tags", []):
                    continue
                if inv["client"] == client["id"] or inv["client"] == client["name"]:
                    inv_month = inv["invoice_date"][:7] if inv["invoice_date"] else None
                    if inv_month == m_key:
                        service_name = inv["period"]
                        if not service_name:
                            if "license" in inv.get("tags", []):
                                service_name = "Лицензия"
                                if inv.get("items"):
                                    # Clean up the item name (remove [[ ]] and x quantity)
                                    first_item = str(inv["items"][0]).replace("[[", "").replace("]]", "")
                                    service_name = first_item.split(" x ")[0].strip()
                            else:
                                service_name = f"Сопровождение {m_key}"
                                
                        matches.append({
                            "invoice_status": inv["status"],
                            "act_status":     inv["act_status"],
                            "amount":         inv["amount"],
                            "payment_date":   inv["payment_date"],
                            "sent_count":     inv["sent_count"],
                            "service_name":   service_name,
                            "id":             inv["id"],
                            "invoice_pdf":    inv.get("invoice_pdf"),
                            "act_pdf":        inv.get("act_pdf"),
                            "edo_status":     inv.get("edo_status"),
                            "email_status":   inv.get("email_status", "unknown"),
                            "email_body":     inv.get("email_body", "")
                        })
            
            matrix[client_id]["months"][m_key] = matches if matches else None
                
    return matrix


def build_not_regular_matrix(clients, invoices):
    """Build a matrix of client vs month for not_regular payments."""
    year = date.today().year
    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    
    valid_clients = set()
    for inv in invoices:
        inv_year = inv["invoice_date"][:4] if inv["invoice_date"] else None
        if inv_year == str(year) and "not_regular" in inv["tags"]:
            # Need to find the client object
            for c in clients:
                if c["id"] == inv["client"] or c["name"] == inv["client"]:
                    valid_clients.add(c["id"])
                    
    matrix = {}
    for c in clients:
        if c["id"] not in valid_clients:
            continue
            
        client_id = c["id"]
        matrix[client_id] = {
            "name": c["name"],
            "months": {}
        }
        
        for m_key in months:
            matches = []
            for inv in invoices:
                if (inv["client"] == c["id"] or inv["client"] == c["name"]) and "not_regular" in inv["tags"]:
                    inv_month = inv["invoice_date"][:7] if inv["invoice_date"] else None
                    if inv_month == m_key:
                        service_name = inv["period"]
                        if not service_name:
                            service_name = "Разовые работы"
                            if inv.get("items"):
                                first_item = str(inv["items"][0]).replace("[[", "").replace("]]", "")
                                service_name = first_item.split(" x ")[0].strip()
                                
                        matches.append({
                            "invoice_status": inv["status"],
                            "act_status":     inv["act_status"],
                            "amount":         inv["amount"],
                            "payment_date":   inv["payment_date"],
                            "sent_count":     inv["sent_count"],
                            "service_name":   service_name,
                            "id":             inv["id"],
                            "invoice_pdf":    inv.get("invoice_pdf"),
                            "act_pdf":        inv.get("act_pdf"),
                            "edo_status":     inv.get("edo_status"),
                            "email_status":   inv.get("email_status", "unknown"),
                            "email_body":     inv.get("email_body", "")
                        })
            
            matrix[client_id]["months"][m_key] = matches if matches else None
                
    return matrix


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def extract_expenses_data():
    today = date.today()
    this_month = today.strftime("%Y-%m")
    first = today.replace(day=1)
    last_month_date = first - timedelta(days=1)
    last_month = last_month_date.strftime("%Y-%m")
    
    expenses_this = get_personal_expenses(this_month)
    expenses_last = get_personal_expenses(last_month)
    
    total = 0
    categories = defaultdict(float)
    recent = []
    
    for exp in expenses_this:
        total += exp['amount']
        categories[exp['category']] += exp['amount']
        if len(recent) < 15:
            recent.append(exp)
            
    total_last = 0
    categories_last = defaultdict(float)
    for exp in expenses_last:
        total_last += exp['amount']
        categories_last[exp['category']] += exp['amount']
        
    # Read planned budgets
    budgets = []
    finances_dir = os.path.join(BASE_DIR, "60_PersonalFinances")
    if os.path.exists(finances_dir):
        for fname in os.listdir(finances_dir):
            if not fname.endswith(".md"): continue
            path = os.path.join(finances_dir, fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                    match = re.search(r'^\s*---\n(.*?)\n---', file_content, re.DOTALL)
                    if match:
                        meta = yaml.safe_load(match.group(1))
                        if meta and 'category' in meta and 'budget' in meta:
                            budgets.append({
                                "category": str(meta['category']),
                                "budget": float(meta['budget']),
                                "due_day": int(meta.get('due_day', 0)),
                                "notify_days": int(meta.get('notify_days_before', 0))
                            })
            except Exception as e:
                pass
                
    # Build Forecast (Прогнозы и планы)
    forecast = []
    total_budget = 0
    planned_cats = set()
    for b in budgets:
        cat = b['category']
        planned_cats.add(cat)
        budget_amt = b['budget']
        actual_amt = categories.get(cat, 0)
        total_budget += budget_amt
        forecast.append({
            "category": cat,
            "budget": budget_amt,
            "actual": actual_amt,
            "type": "planned"
        })
        
    for cat, amt in categories.items():
        if cat not in planned_cats and amt > 0:
            forecast.append({
                "category": cat,
                "budget": amt,
                "actual": amt,
                "type": "unplanned"
            })
            total_budget += amt
            
    forecast.sort(key=lambda x: x['actual'], reverse=True)
            
    # Analytics (сравнение)
    analytics = []
    all_cats = set(categories.keys()).union(set(categories_last.keys()))
    for cat in all_cats:
        curr = categories.get(cat, 0)
        prev = categories_last.get(cat, 0)
        diff = curr - prev
        pct = 0
        if prev > 0:
            pct = round((diff / prev) * 100, 1)
        elif curr > 0:
            pct = 100
            
        if diff != 0:
            analytics.append({
                "category": cat,
                "current": curr,
                "previous": prev,
                "diff": diff,
                "pct": pct
            })
            
    analytics.sort(key=lambda x: x['diff'], reverse=True)
    
    return {
        "total": round(total, 2),
        "total_budget": round(total_budget, 2),
        "free_money": round(total_budget - total, 2),
        "by_category": [{"category": k, "amount": round(v, 2)} for k, v in categories.items()],
        "recent": recent,
        "forecast": forecast,
        "analytics": analytics
    }

def extract_goals() -> list:
    goals = []
    goals_dir = os.path.join(BASE_DIR, "55_Goals")
    if not os.path.exists(goals_dir):
        return goals
        
    for fname in os.listdir(goals_dir):
        if not fname.endswith(".md"): continue
        path = os.path.join(goals_dir, fname)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
            if match:
                meta = yaml.safe_load(match.group(1))
                if meta and 'id' in meta:
                    goals.append({
                        "id": meta.get('id', ''),
                        "title": meta.get('title', fname.replace('.md', '')),
                        "type": meta.get('type', 'general'),
                        "deadline": meta.get('deadline', ''),
                        "target_value": meta.get('target_value', 100),
                        "current_value": meta.get('current_value', 0),
                        "unit": meta.get('unit', ''),
                        "direction": meta.get('direction', 'increase'),
                        "status": meta.get('status', 'active'),
                        "file_path": f"55_Goals/{fname}"
                    })
    return goals

def build_dashboard_data() -> dict:
    clients   = extract_clients()
    invoices  = extract_invoices()
    infra     = extract_infrastructure()
    credits   = extract_credits()
    inbox     = extract_inbox()
    expenses  = extract_expenses_data()
    goals     = extract_goals()
    attach_contracts(clients)

    metrics = compute_metrics(clients, invoices, credits, infra)
    leads   = extract_leads()

    return {
        "meta":      metrics,
        "clients":   clients,
        "invoices":  invoices,
        "infra":     infra,
        "credits":   credits,
        "inbox":     inbox,
        "expenses":  expenses,
        "goals":     goals,
        "leads":     leads,
    }

if __name__ == "__main__":
    from pathlib import Path
    
    print("🔍 Extracting CRM data from Obsidian Vault...")
    data = build_dashboard_data()
    
    # Защита от поломки контракта: сравниваем с прошлым data.json
    old_path = Path(OUTPUT_FILE)
    if old_path.exists():
        try:
            old_data = json.loads(old_path.read_text(encoding="utf-8"))
            old_keys = set(old_data.keys())
            new_keys = set(data.keys())
            if old_keys != new_keys:
                print(f"⚠️  WARNING: keys changed!")
                print(f"   Removed: {old_keys - new_keys}")
                print(f"   Added: {new_keys - old_keys}")
        except Exception as e:
            print(f"⚠️ Could not validate against old data.json: {e}")

    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    
    print(f"\n🚀 Dashboard data written → {OUTPUT_FILE}")
    print(f"✅ data.json written ({len(data)} top-level keys)")
    metrics = data["meta"]
    print(f"   MRR: {metrics['mrr']:,.0f} ₽")
    print(f"   Выручка этого месяца: {metrics['revenue_this_month']:,.0f} ₽")
    print(f"   Задолженность: {metrics['total_debt']:,.0f} ₽")
