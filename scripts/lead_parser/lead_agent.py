
from sec_guard import guard_open, guard_requests_get
# Этот скрипт предназначен для запуска на сервере.
# Он использует относительные пути, чтобы сохранить результаты в папку cold, 
# которая затем синхронизируется через Syncthing обратно на ваш ПК.

import urllib.request
import time
import requests
from bs4 import BeautifulSoup
import re
import os
import sys

# Вычисляем путь к папке cold
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.abspath(os.path.join(BASE_DIR, "cold"))

# Убедимся, что папка существует
os.makedirs(RESULTS_DIR, exist_ok=True)

# Тестовая выборка сайтов
leads = [
    {"url": "https://kiostom.ru", "company": "Киостом", "city": "Саратов"},
    {"url": "https://www.medguard.ru", "company": "Медгард", "city": "Саратов"},
    {"url": "https://sovamed.ru", "company": "СОВА", "city": "Саратов"},
]

def check_bitrix_and_seo(url, target_city):
    print(f"[+] Проверка: {url}")
    result = {"url": url, "is_bitrix": False, "ttfb": 0, "geo_issue": False, "emails": set(), "error": None}
    
    try:
        start_time = time.time()
        response = guard_requests_get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        ttfb = time.time() - start_time
        result["ttfb"] = round(ttfb, 2)
        print(f"  - TTFB: {result['ttfb']}s")
        
        html = response.text
        headers = response.headers
        
        if 'bitrix' in headers.get('X-Powered-CMS', '').lower() or '/bitrix/templates/' in html or 'bitrix.info' in html:
            result["is_bitrix"] = True
            print("  - CMS: 1C-Bitrix (Подтверждено)")
        else:
            print("  - CMS: Следов Bitrix не найдено (Пропуск)")
            return result
            
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string if soup.title else ""
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        description = desc_tag['content'] if desc_tag else ""
        
        title_has_city = target_city.lower() in title.lower()
        desc_has_city = target_city.lower() in description.lower()
        
        if not title_has_city or not desc_has_city:
            result["geo_issue"] = True
            print("  - Ошибка SEO: Отсутствие города в Title/Description")
            
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html)
        result["emails"].update(emails)
        if not result["emails"]:
            try:
                _cu = f"{url.rstrip('/')}/contacts/"
                contact_response = guard_requests_get(_cu, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
                emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", contact_response.text)
                result["emails"].update(emails)
            except:
                pass
                
        valid_emails = {e for e in result["emails"] if not e.endswith(('.png', '.jpg', '.jpeg', '.gif', '.css', '.js'))}
        result["emails"] = valid_emails

    except Exception as e:
        result["error"] = str(e)
        
    return result

def generate_cold_email(company, city, ttfb, geo_issue):
    email_text = f"""Здравствуйте, коллеги из {company}!

Анализировал вашу нишу в регионе {city}, наткнулся на ваш сайт. 
Сразу бросаются в глаза критические технические проблемы вашего 1С-Битрикс, которые напрямую режут вам SEO и конверсию:

"""
    if ttfb > 1.0:
         email_text += f"1. Огромный TTFB (Time To First Byte). Ваш сервер отдает страницу за **{ttfb} секунд**. Это катастрофа для мобильной выдачи Яндекс и Google. Картинки и скрипты грузятся еще дольше из-за кривого ресайза и настроек кэша Битрикса.\n"
    
    if geo_issue:
         email_text += f"2. Региональное SEO реализовано криво. Базовые теги Title/Description не содержат связки с городом '{city}'. Вы банально теряете локальный трафик.\n"
         
    email_text += """
Обычные SEO-шники тут не помогут (они просто переписывают тексты), здесь нужно лезть глубоко в ядро Битрикса и архитектуру сервера. 

У меня 20 лет опыта в IT-архитектуре и выстраивании железобетонного GEO-SEO для региональных сетей. Я знаю, как вылечить вашего "динозавра" и заставить его летать.

Давайте созвонимся на 15 минут - я на пальцах покажу, где вы прямо сейчас теряете деньги, и расскажу, как мы это исправим.

С уважением,
[Ваше Имя]
IT-Архитектор | B2B SEO Эксперт
"""
    return email_text

def export_to_obsidian(company_data):
    if not company_data["is_bitrix"]:
        return
        
    emails_str = ", ".join(company_data["emails"]) if company_data["emails"] else "Не найдено"
    filename = f"{company_data['company'].replace(' ', '_')}.md"
    filepath = os.path.join(RESULTS_DIR, filename)
    
    email_content = generate_cold_email(
        company_data['company'], 
        city="Саратов", 
        ttfb=company_data['ttfb'], 
        geo_issue=company_data['geo_issue']
    )
    
    content = f"""---
status: cold_lead
company: {company_data['company']}
url: {company_data['url']}
emails: [{emails_str}]
cms: Bitrix
ttfb: {company_data['ttfb']}
geo_issue: {company_data['geo_issue']}
city: Саратов
---

# {company_data['company']}

## Технический аудит
- **URL**: {company_data['url']}
- **TTFB**: {company_data['ttfb']} сек
- **Ошибки GEO (Саратов)**: {'Да' if company_data['geo_issue'] else 'Нет'}
- **Найденные контакты**: {emails_str}

## Черновик письма для аутрича:

{email_content}
"""
    with guard_open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  [+] Сохранено в Obsidian: {filepath}")

def main():
    print(f"Запуск агента. Файлы будут сохранены в: {RESULTS_DIR}")
    for lead in leads:
        data = check_bitrix_and_seo(lead["url"], lead["city"])
        data["company"] = lead["company"]
        if data["is_bitrix"] and (data["ttfb"] > 1.0 or data["geo_issue"]):
             export_to_obsidian(data)

if __name__ == "__main__":
    main()
