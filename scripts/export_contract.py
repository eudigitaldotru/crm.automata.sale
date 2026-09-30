"""
Экспорт договора в DOCX + PDF (пайплайн как в скилле it-report):
  markdown --pandoc--> DOCX --libreoffice headless--> PDF

Использование:
  python3 scripts/export_contract.py "60_Documents/Contracts/Договор ....md"
  python3 scripts/export_contract.py --check          # проверить инструменты

DOCX и PDF создаются рядом с исходным .md (тот же basename).
Стили документа: scripts/contract_reference.docx (Times New Roman 12pt, чёрные
заголовки). Пересобрать эталон: pandoc --print-default-data-file reference.docx,
затем заменить в word/styles.xml шрифты на Times New Roman и цвета на 000000.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS_DIR = os.path.join(BASE_DIR, "60_Documents", "Contracts")
REFERENCE_DOCX = os.path.join(BASE_DIR, "scripts", "contract_reference.docx")
# Отдельный профиль LibreOffice: не конфликтуем с открытым у пользователя soffice
LO_PROFILE = "-env:UserInstallation=file:///tmp/lo_contract_export_profile"


class ExportError(Exception):
    pass


def check_tools():
    missing = [t for t in ("pandoc", "libreoffice") if not shutil.which(t)]
    if missing:
        raise ExportError("Не установлены: " + ", ".join(missing))
    if not os.path.exists(REFERENCE_DOCX):
        raise ExportError(f"Нет эталона стилей: {REFERENCE_DOCX}")


def export_contract(md_path):
    """md → docx → pdf. Возвращает dict с абсолютными путями docx/pdf."""
    md_path = os.path.abspath(md_path)
    if not os.path.isfile(md_path):
        raise ExportError(f"Файл не найден: {md_path}")
    if not md_path.lower().endswith(".md"):
        raise ExportError("Ожидается .md файл договора")

    check_tools()
    stem = os.path.splitext(md_path)[0]
    docx_path = stem + ".docx"
    pdf_path = stem + ".pdf"

    # 1. markdown → docx (pandoc)
    pandoc_cmd = [
        "pandoc", md_path,
        "--reference-doc=" + REFERENCE_DOCX,
        "--from", "gfm+hard_line_breaks",   # таблицы и переносы строк контракта
        "--to", "docx",
        "--output", docx_path,
    ]
    res = subprocess.run(pandoc_cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise ExportError(f"pandoc: {res.stderr.strip()[:300]}")

    # 2. docx → pdf (libreoffice headless)
    with tempfile.TemporaryDirectory() as tmp_out:
        lo_cmd = [
            "libreoffice", "--headless", LO_PROFILE,
            "--convert-to", "pdf",
            "--outdir", tmp_out, docx_path,
        ]
        res = subprocess.run(lo_cmd, capture_output=True, text=True, timeout=300)
        produced = os.path.join(tmp_out, os.path.basename(pdf_path))
        if res.returncode != 0 or not os.path.exists(produced):
            raise ExportError(f"libreoffice: {(res.stderr or res.stdout).strip()[:300]}")
        shutil.move(produced, pdf_path)

    return {"docx": os.path.relpath(docx_path, BASE_DIR),
            "pdf": os.path.relpath(pdf_path, BASE_DIR)}


def main():
    args = sys.argv[1:]
    if args and args[0] == "--check":
        try:
            check_tools()
            print("OK: pandoc, libreoffice, contract_reference.docx")
        except ExportError as e:
            sys.exit(f"❌ {e}")
        return
    if not args:
        sys.exit("Использование: export_contract.py <договор.md> | --check")
    try:
        result = export_contract(args[0])
        print(json.dumps(result, ensure_ascii=False))
    except ExportError as e:
        sys.exit(f"❌ {e}")


if __name__ == "__main__":
    main()
