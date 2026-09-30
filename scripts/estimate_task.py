#!/usr/bin/env python3
import os
import sys
import csv
import math
import re
from collections import Counter

# File paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "report.csv")

def parse_hours(time_str):
    """Parse time string in format HH:MM or float hours to float value."""
    try:
        time_str = time_str.strip()
        if not time_str:
            return 0.0
        if ':' in time_str:
            parts = time_str.split(':')
            return float(parts[0]) + float(parts[1]) / 60.0
        return float(time_str)
    except Exception:
        return 0.0

def clean_and_tokenize(text):
    """Tokenize and clean Russian/English text, splitting alphanumeric junctions like Bitrix24."""
    text = text.lower()
    # Separate letters and numbers
    text = re.sub(r'([a-zA-Zа-яА-ЯёЁ])(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([a-zA-Zа-яА-ЯёЁ])', r'\1 \2', text)
    text = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ_]', ' ', text)
    return [w for w in text.split() if len(w) > 1]

class BM25Search:
    def __init__(self, csv_path):
        self.documents = []
        self.doc_len = []
        self.avg_doc_len = 0
        self.idf = {}
        self.load_data(csv_path)
        
    def load_data(self, csv_path):
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Database file not found: {csv_path}")
            
        with open(csv_path, 'r', encoding='utf-8') as f:
            # Detect delimiter (either ; or ,)
            sample = f.read(2048)
            delimiter = ';' if ';' in sample else ','
            f.seek(0)
            
            reader = csv.DictReader(f, delimiter=delimiter)
            
            # Match columns by checking headers
            headers = reader.fieldnames or []
            name_col = next((h for h in headers if 'название' in h.lower()), None)
            time_col = next((h for h in headers if 'время' in h.lower() or 'затрачено' in h.lower()), None)
            date_col = next((h for h in headers if 'дата' in h.lower() or 'завершения' in h.lower()), None)
            id_col = next((h for h in headers if 'id' in h.lower()), 'ID')
            
            if not name_col or not time_col:
                # Fallback to order-based if headers can't be matched
                name_col = headers[1] if len(headers) > 1 else 'Название'
                time_col = headers[2] if len(headers) > 2 else 'Затраченное время'
                date_col = headers[3] if len(headers) > 3 else 'Дата завершения'
            
            total_len = 0
            df = Counter()
            
            for row in reader:
                title = row.get(name_col, "") or ""
                time_str = row.get(time_col, "") or ""
                date_str = row.get(date_col, "") or ""
                task_id = row.get(id_col, "") or ""
                
                hours = parse_hours(time_str)
                # Skip tasks with 0 hours logged to keep dataset clean
                if hours <= 0:
                    continue
                    
                tokens = clean_and_tokenize(title)
                if not tokens:
                    continue
                    
                doc = {
                    "id": task_id,
                    "title": title,
                    "hours": hours,
                    "date": date_str,
                    "tokens": tokens,
                    "counts": Counter(tokens)
                }
                
                self.documents.append(doc)
                self.doc_len.append(len(tokens))
                total_len += len(tokens)
                
                for token in set(tokens):
                    df[token] += 1
            
            N = len(self.documents)
            if N > 0:
                self.avg_doc_len = total_len / N
                
            # Calculate IDF
            for word, count in df.items():
                # Standard BM25 IDF formula
                self.idf[word] = math.log((N - count + 0.5) / (count + 0.5) + 1.0)

    def search(self, query, top_n=5, k1=1.5, b=0.75):
        query_tokens = clean_and_tokenize(query)
        if not query_tokens:
            return []
            
        scores = []
        for i, doc in enumerate(self.documents):
            score = 0.0
            doc_len = self.doc_len[i]
            for token in query_tokens:
                if token in self.idf:
                    tf = doc["counts"].get(token, 0)
                    # BM25 tf formula
                    idf = self.idf[token]
                    tf_factor = (tf * (k1 + 1)) / (tf + k1 * (1.0 - b + b * (doc_len / self.avg_doc_len)))
                    score += idf * tf_factor
            if score > 0:
                scores.append((score, doc))
                
        # Sort by score descending
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores[:top_n]

def main():
    if len(sys.argv) < 2:
        print("Использование: python3 scripts/estimate_task.py \"<описание задачи>\"")
        sys.exit(1)
        
    query = sys.argv[1]
    
    try:
        searcher = BM25Search(CSV_PATH)
    except Exception as e:
        print(f"Ошибка загрузки базы данных: {e}", file=sys.stderr)
        sys.exit(1)
        
    results = searcher.search(query)
    
    if not results:
        print("Совпадений в базе исторических задач не найдено.")
        sys.exit(0)
        
    print(f"\n🔎 Результаты поиска по запросу: \"{query}\"")
    print("-" * 80)
    
    hours_list = []
    for rank, (score, doc) in enumerate(results, 1):
        print(f"{rank}. [{doc['date']}] (ID: {doc['id']}) \"{doc['title']}\"")
        print(f"   Фактическое время: {doc['hours']:.2f} ч. (Релевантность: {score:.2f})")
        hours_list.append(doc['hours'])
        
    print("-" * 80)
    
    # Calculate stats
    avg_hours = sum(hours_list) / len(hours_list)
    sorted_hours = sorted(hours_list)
    n = len(sorted_hours)
    if n % 2 == 1:
        median_hours = sorted_hours[n // 2]
    else:
        median_hours = (sorted_hours[n // 2 - 1] + sorted_hours[n // 2]) / 2.0
        
    print(f"📊 Статистика оценки на основе совпадений:")
    print(f"   • Минимальное время: {sorted_hours[0]:.2f} ч.")
    print(f"   • Максимальное время: {sorted_hours[-1]:.2f} ч.")
    print(f"   • Среднее время: {avg_hours:.2f} ч.")
    print(f"   • Медианное время (рекомендуемое): {median_hours:.2f} ч.")
    print("-" * 80)

if __name__ == "__main__":
    main()
