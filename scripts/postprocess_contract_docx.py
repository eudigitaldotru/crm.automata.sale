"""Постобработка DOCX договора после pandoc (использовать перед конвертацией в PDF).

    python3 postprocess_contract_docx.py <файл.docx>

Что делает:
1. Запрещает разрыв строк таблиц между страницами (w:cantSplit).
2. Выставляет соразмерные ширины колонок для таблиц SLA (4 кол.) и формы Акта
   (5 кол.) — pandoc при экспорте из markdown игнорирует пропорции разделителя.
3. Чинит линии-разделители `---`: pandoc выдаёт v:rect width:0, LibreOffice
   рисует такой rect вертикальным штрихом; заменяет ширину на 100%.
4. Удаляет pict-разделитель сразу после таблицы реквизитов (перед заголовком
   «ПРИЛОЖЕНИЯ К ДОГОВОРУ») — на этом месте LO рисует висячий штрих под «М.П.».
"""
import os
import re
import sys
import zipfile

# индексы таблиц по порядку в document.xml -> ширины колонок в twips
# 0: SLA п.6.4 (4 кол.), 2: SLA Прил.1 п.2 (4 кол.), 5: форма Акта Прил.3 (5 кол.)
SLA = [2150, 3850, 1500, 1500]
ACT = [500, 4300, 1500, 1400, 1300]
TARIFF_APP1 = [2000, 1600, 1900, 1500, 2000]   # сетка тарифов Прил.1 (паддинг ячейки LO ~500 twips)
TARIFF_APP6 = [2050, 2200, 1600, 1400, 1750]   # сетка тарифов Прил.6
WIDTH_MAP = {0: SLA, 2: SLA, 3: TARIFF_APP1, 5: ACT, 6: TARIFF_APP6}

# заголовки-«висяки»: абзацы, которые нельзя отрывать от следующего блока
KEEP_WITH_NEXT = (
    '3. Выбранный тарифный план и стоимость',
    '1. Доступные тарифные планы',
)


def set_widths(tbl: str, widths: list) -> str:
    tbl = re.sub(
        r'<w:tblGrid>.*?</w:tblGrid>',
        '<w:tblGrid>' + ''.join(f'<w:gridCol w:w="{w}"/>' for w in widths) + '</w:tblGrid>',
        tbl, flags=re.DOTALL,
    )
    # LibreOffice при tblW=auto берёт ширины из tcW ячеек, а не из tblGrid:
    # прописываем tcW каждой ячейке по её колонке.
    def fix_row(mm) -> str:
        row = mm.group(0)
        idx = [0]

        def fix_cell(m):
            i = idx[0] % len(widths)
            idx[0] += 1
            c = m.group(0)
            tcw = f'<w:tcW w:w="{widths[i]}" w:type="dxa"/>'
            if '<w:tcW' in c:
                return re.sub(r'<w:tcW[^/]*/>', tcw, c, count=1)
            if '<w:tcPr>' in c:
                return c.replace('<w:tcPr>', '<w:tcPr>' + tcw, 1)
            return c.replace('<w:tc>', '<w:tc><w:tcPr>' + tcw + '</w:tcPr>', 1)

        return re.sub(r'<w:tc>.*?</w:tc>', fix_cell, row, flags=re.DOTALL)

    return re.sub(r'<w:tr(?: [^>]*)?>.*?</w:tr>', fix_row, tbl, flags=re.DOTALL)


def main(path: str) -> None:
    z = zipfile.ZipFile(path)
    items = {n: z.read(n) for n in z.namelist()}
    z.close()
    xml = items['word/document.xml'].decode('utf-8')

    # 1-2. ширины таблиц
    out, pos, count = [], 0, 0
    for m in re.finditer(r'<w:tbl>.*?</w:tbl>', xml, re.DOTALL):
        out.append(xml[pos:m.start()])
        tbl = m.group(0)
        if count in WIDTH_MAP:
            tbl = set_widths(tbl, WIDTH_MAP[count])
        out.append(tbl)
        pos = m.end()
        count += 1
    out.append(xml[pos:])
    xml = ''.join(out)

    # 1. cantSplit всем строкам
    def add_cantsplit(mm):
        tr = mm.group(0)
        if '<w:trPr>' in tr[:200]:
            return tr.replace('<w:trPr>', '<w:trPr><w:cantSplit/>', 1)
        return tr.replace('<w:tr>', '<w:tr><w:trPr><w:cantSplit/></w:trPr>', 1)

    xml = re.sub(r'<w:tr>.*?</w:tr>', add_cantsplit, xml, flags=re.DOTALL)

    # 3. разделители `---` на всю ширину
    xml = xml.replace('style="width:0;height:1.5pt"', 'style="width:100%;height:1.5pt"')

    # 3b. keep-with-next для заданных заголовков
    def add_keepnext(mm):
        p = mm.group(0)
        text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', p)).strip()
        if any(text.startswith(t) for t in KEEP_WITH_NEXT):
            if '<w:pPr>' in p[:200]:
                return p.replace('<w:pPr>', '<w:pPr><w:keepNext/>', 1)
            return p.replace('<w:p>', '<w:p><w:pPr><w:keepNext/></w:pPr>', 1)
        return p

    xml = re.sub(r'<w:p>.*?</w:p>', add_keepnext, xml, flags=re.DOTALL)

    # 4. pict-разделитель после таблицы реквизитов
    j = xml.find('приложения-к-договору')
    if j != -1:
        seg_start = xml.rfind('</w:tbl>', 0, j)
        seg = xml[seg_start:j]
        seg2 = re.sub(r'<w:p><w:r><w:pict>.*?</w:pict></w:r></w:p>', '', seg, count=1, flags=re.DOTALL)
        xml = xml[:seg_start] + seg2 + xml[j:]

    items['word/document.xml'] = xml.encode('utf-8')
    with zipfile.ZipFile(path + '.new', 'w', zipfile.ZIP_DEFLATED) as zo:
        for name, data in items.items():
            zo.writestr(name, data)
    os.replace(path + '.new', path)
    print(f'OK: таблиц={count}, cantSplit строк={xml.count("<w:cantSplit/>")}')


if __name__ == '__main__':
    main(sys.argv[1])
